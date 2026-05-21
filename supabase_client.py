import json
import mimetypes
import os
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

AUDIO_BUCKET = "call-recordings"
TRANSCRIPT_BUCKET = "call-transcripts"


def get_setting(name: str, default: str | None = None) -> str | None:
    """Read from environment first, then Streamlit secrets if available."""
    value = os.getenv(name)
    if value:
        return value

    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass

    return default


def get_client() -> Client:
    url = get_setting("SUPABASE_URL")
    key = get_setting("SUPABASE_KEY")

    if not url:
        raise RuntimeError("SUPABASE_URL is missing.")
    if not key:
        raise RuntimeError("SUPABASE_KEY is missing.")

    return create_client(url, key)


def is_not_worthy_result(result: Any) -> bool:
    if isinstance(result, str):
        return result.strip() == "not_worthy"

    if isinstance(result, dict):
        return result.get("status") == "not_worthy" or result.get("worthy") is False

    return False


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _plain_summary_text(value):
    """
    Convert GPT JSON/dict values into complete readable text.

    For fields like top_strength and biggest_improvement_area, GPT may return:
    {
      "summary": "...",
      "by_parameter": {"guardrails": "...", "opening": "..."}
    }

    This function shows BOTH summary and all parameter-wise details.
    """
    if value is None:
        return ""

    if isinstance(value, dict):
        lines = []

        summary = value.get("summary")
        if summary:
            lines.append(str(summary).strip())

        by_parameter = value.get("by_parameter")
        if isinstance(by_parameter, dict) and by_parameter:
            if lines:
                lines.append("")
            lines.append("Parameter-wise details:")

            preferred_order = [
                "guardrails",
                "opening",
                "discovery",
                "evidence",
                "resonance",
                "diagnosis",
                "closure",
            ]

            used = set()
            for key in preferred_order:
                if key in by_parameter:
                    label = key.replace("_", " ").title()
                    detail = str(by_parameter[key]).strip()
                    lines.append(f"- {label}: {detail}")
                    used.add(key)

            for key, detail in by_parameter.items():
                if key not in used:
                    label = str(key).replace("_", " ").title()
                    lines.append(f"- {label}: {str(detail).strip()}")

        if lines:
            return "\n".join(lines)

        return json.dumps(value, ensure_ascii=False)

    if isinstance(value, list):
        return "\n".join(_plain_summary_text(item) for item in value)

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                parsed = json.loads(text)
                return _plain_summary_text(parsed)
            except Exception:
                return value
        return value

    return str(value)


def _score_value(section: Dict[str, Any]) -> str | None:
    score = (section or {}).get("score")
    return None if score is None else str(score)


def _overall_total(overall: Dict[str, Any]) -> str | None:
    if not overall:
        return None

    if overall.get("total"):
        return str(overall.get("total"))

    total = overall.get("total_score")
    out_of = overall.get("out_of")
    percentage = overall.get("percentage")

    if total is None or out_of is None:
        return None

    if percentage is None:
        return f"{total}/{out_of}"

    return f"{total}/{out_of} ({percentage}%)"


def _overall_percentage(overall: Dict[str, Any]) -> str | None:
    if not overall:
        return None

    percentage = overall.get("percentage")
    if percentage is not None:
        return str(percentage)

    return None


def _slug_filename(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    if not name:
        name = "call_recording"
    return name


def _ensure_bucket(client: Client, bucket_name: str) -> None:
    """
    Best-effort bucket creation.
    If it fails because the bucket exists or storage permissions differ, upload may still work.
    """
    try:
        client.storage.create_bucket(bucket_name, options={"public": True})
    except TypeError:
        try:
            client.storage.create_bucket(bucket_name, {"public": True})
        except Exception:
            pass
    except Exception:
        pass


def _public_url(client: Client, bucket_name: str, object_path: str) -> str | None:
    try:
        url = client.storage.from_(bucket_name).get_public_url(object_path)
        if isinstance(url, str):
            return url
        if isinstance(url, dict):
            return url.get("publicUrl") or url.get("public_url") or url.get("signedURL")
    except Exception:
        return None
    return None


def _upload_bytes(
    client: Client,
    bucket_name: str,
    object_path: str,
    file_bytes: bytes,
    content_type: str,
) -> str | None:
    _ensure_bucket(client, bucket_name)

    file_options = {
        "content-type": content_type,
        "upsert": "true",
    }

    try:
        client.storage.from_(bucket_name).upload(
            object_path,
            file_bytes,
            file_options=file_options,
        )
    except TypeError:
        try:
            client.storage.from_(bucket_name).upload(object_path, file_bytes, file_options)
        except Exception:
            return None
    except Exception:
        return None

    return _public_url(client, bucket_name, object_path)


def upload_call_files(
    client: Client,
    student_number: str,
    audio_filename: str,
    audio_bytes: bytes | None,
    transcript: str,
) -> tuple[str | None, str | None]:
    """
    Upload recording and transcript to Supabase Storage and return public URLs.
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid4().hex[:8]
    safe_audio_name = _slug_filename(audio_filename)

    audio_url = None
    if audio_bytes:
        content_type = mimetypes.guess_type(safe_audio_name)[0] or "application/octet-stream"
        audio_path = f"{student_number}/{timestamp}_{unique_id}_{safe_audio_name}"
        audio_url = _upload_bytes(
            client=client,
            bucket_name=AUDIO_BUCKET,
            object_path=audio_path,
            file_bytes=audio_bytes,
            content_type=content_type,
        )

    transcript_bytes = (transcript or "").encode("utf-8")
    transcript_path = f"{student_number}/{timestamp}_{unique_id}_{safe_audio_name}.txt"
    transcript_url = _upload_bytes(
        client=client,
        bucket_name=TRANSCRIPT_BUCKET,
        object_path=transcript_path,
        file_bytes=transcript_bytes,
        content_type="text/plain; charset=utf-8",
    )

    return audio_url, transcript_url


def build_db_row(
    student_number: str,
    audio_filename: str,
    transcript: str,
    result: dict | str,
    call_audio_link: str | None = None,
    call_transcript_link: str | None = None,
) -> Dict[str, Any]:
    """
    Convert one scoring result into the Supabase row format.
    """
    if is_not_worthy_result(result):
        return {
            "student_number": student_number,
            "call_audio_link": call_audio_link or audio_filename,
            "call_transcript": transcript,
            "call_transcript_link": call_transcript_link,
            "analysis_worthy": False,
            "converted_status": "Not converted",
            "ai_output_json": {"status": "not_worthy"},
            "guardrails": None,
            "opening_score": None,
            "discovery_score": None,
            "evidence_score": None,
            "resonance_score": None,
            "diagnosis_score": None,
            "closure_score": None,
            "overall_score": None,
            "top_strength": None,
            "biggest_improvement_area": None,
            "coaching_note": None,
        }

    if not isinstance(result, dict):
        raise RuntimeError("OpenAI returned an unsupported response format.")

    guardrails = result.get("guardrails", {}) or {}
    opening = result.get("opening", {}) or {}
    discovery = result.get("discovery", {}) or {}
    evidence = result.get("evidence", {}) or {}
    resonance = result.get("resonance", {}) or {}
    diagnosis = result.get("diagnosis", {}) or {}
    closure = result.get("closure", {}) or {}
    overall = result.get("overall_score", {}) or result.get("overall", {}) or {}

    converted_status = result.get("converted_status")
    if converted_status not in {"Converted", "Not converted"}:
        converted_status = "Not converted"

    return {
        "student_number": student_number,
        "call_audio_link": call_audio_link or audio_filename,
        "call_transcript": transcript,
        "call_transcript_link": call_transcript_link,
        "analysis_worthy": True,
        "converted_status": converted_status,
        "ai_output_json": result,

        "guardrails": guardrails.get("result"),
        "guardrails_reason": guardrails.get("reason"),
        "guardrails_false_information_flagged": guardrails.get("false_information_flagged"),
        "guardrails_false_information_detail": guardrails.get("false_information_detail"),

        "opening_score": _score_value(opening),
        "opening_what_agent_said_right_after_intro": opening.get("what_agent_said_right_after_intro"),
        "opening_quote": opening.get("quote"),
        "opening_specific_to_student_trial_activity": opening.get("specific_to_student_trial_activity"),
        "opening_why_this_score": opening.get("why_this_score"),

        "discovery_score": _score_value(discovery),
        "discovery_questions_asked_by_agent": _safe_text(discovery.get("questions_asked_by_agent")),
        "discovery_what_agent_found_out": _safe_text(discovery.get("what_agent_found_out")),
        "discovery_student_said_own_problem_out_loud": discovery.get("student_said_own_problem_out_loud"),
        "discovery_best_discovery_moment_quote": discovery.get("best_discovery_moment_quote"),
        "discovery_why_this_score": discovery.get("why_this_score"),

        "evidence_score": _score_value(evidence),
        "evidence_discovery_finding_used": evidence.get("discovery_finding_used"),
        "evidence_master_course_feature_connected": evidence.get("master_course_feature_connected"),
        "evidence_factually_accurate_about_master_course": evidence.get("factually_accurate_about_master_course"),
        "evidence_inaccuracy_detail": evidence.get("inaccuracy_detail"),
        "evidence_quote": evidence.get("quote"),
        "evidence_why_this_score": evidence.get("why_this_score"),

        "resonance_score": _score_value(resonance),
        "resonance_source_of_urgency": resonance.get("source_of_urgency"),
        "resonance_student_situation_used": resonance.get("student_situation_used"),
        "resonance_quote": resonance.get("quote"),
        "resonance_why_this_score": resonance.get("why_this_score"),

        "diagnosis_score": "N/A" if diagnosis.get("na") else _score_value(diagnosis),
        "diagnosis_na": bool(diagnosis.get("na")) if diagnosis.get("na") is not None else False,
        "diagnosis_objection_raised_by_student": diagnosis.get("objection_raised_by_student"),
        "diagnosis_surface_reason_stated": diagnosis.get("surface_reason_stated"),
        "diagnosis_real_reason_found": diagnosis.get("real_reason_found"),
        "diagnosis_quote_of_diagnosis_attempt": diagnosis.get("quote_of_diagnosis_attempt"),
        "diagnosis_why_this_score": diagnosis.get("why_this_score"),

        "closure_score": _score_value(closure),
        "closure_what_happened_at_end": closure.get("what_happened_at_end"),
        "closure_payment_link_sent": closure.get("payment_link_sent"),
        "closure_followup_date_and_time_agreed": closure.get("followup_date_and_time_agreed"),
        "closure_course_details_sent_on_whatsapp": closure.get("course_details_sent_on_whatsapp"),
        "closure_quote_of_closing_line": closure.get("quote_of_closing_line"),
        "closure_why_this_score": closure.get("why_this_score"),

        "overall_score": _overall_total(overall),
        "overall_guardrails": overall.get("guardrails"),
        "overall_opening": overall.get("opening"),
        "overall_discovery": overall.get("discovery"),
        "overall_evidence": overall.get("evidence"),
        "overall_resonance": overall.get("resonance"),
        "overall_diagnosis": overall.get("diagnosis"),
        "overall_closure": overall.get("closure"),
        "overall_total": _overall_total(overall),
        "overall_percentage": _overall_percentage(overall),
        "guardrails_review_flag": overall.get("guardrails_review_flag"),

        "top_strength": _plain_summary_text(result.get("top_strength")),
        "biggest_improvement_area": _plain_summary_text(result.get("biggest_improvement_area")),
        "coaching_note": _plain_summary_text(result.get("coaching_note")),
    }


def save_result(
    student_number: str,
    audio_filename: str,
    transcript: str,
    result: dict | str,
    audio_bytes: bytes | None = None,
) -> Dict[str, Any]:
    """
    Save one call's results to Supabase and return the inserted row.
    """
    client = get_client()

    audio_url, transcript_url = upload_call_files(
        client=client,
        student_number=student_number,
        audio_filename=audio_filename,
        audio_bytes=audio_bytes,
        transcript=transcript,
    )

    row = build_db_row(
        student_number=student_number,
        audio_filename=audio_filename,
        transcript=transcript,
        result=result,
        call_audio_link=audio_url,
        call_transcript_link=transcript_url,
    )

    response = client.table("call_scores").insert(row).execute()

    if getattr(response, "data", None):
        return response.data[0]

    return row


def fetch_all_results(limit: int = 500) -> List[Dict[str, Any]]:
    client = get_client()
    response = (
        client.table("call_scores")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


def fetch_results_for_date(target_date: date) -> List[Dict[str, Any]]:
    client = get_client()

    start = datetime.combine(target_date, time.min).isoformat()
    end = datetime.combine(target_date, time.max).isoformat()

    response = (
        client.table("call_scores")
        .select("*")
        .gte("created_at", start)
        .lte("created_at", end)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []
