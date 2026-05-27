import json
import mimetypes
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

AUDIO_BUCKET = "call-recordings"
TRANSCRIPT_BUCKET = "call-transcripts"

FINAL_COLUMNS = [
    "Date",
    "Student Number",
    "Call Type",
    "Call Recording Link",
    "Converted Status",
    "Average Score",
    "Score Parameter Wise",
    "Strengths",
    "Improvement Areas",
    "Learnings",
    "Transcript Link",
]


def get_setting(name: str, default: str | None = None) -> str | None:
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
        call_type = result.get("call_type") or result.get("status")
        return call_type == "not_worthy" or result.get("worthy") is False or result.get("analysis_worthy") is False
    return False


def _plain_summary_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        lines: list[str] = []
        summary = value.get("summary")
        if summary:
            lines.append(str(summary).strip())
        by_parameter = value.get("by_parameter")
        if isinstance(by_parameter, dict) and by_parameter:
            if lines:
                lines.append("")
            lines.append("Parameter-wise details:")
            labels = {
                "guardrails": "Tone + Truth",
                "opening": "Opening",
                "discovery": "Pain Point Discovery",
                "evidence": "Evidence",
                "personal_urgency": "Personal Urgency",
                "real_hesitation_reason": "Hesitation Discovery",
                "clear_next_step": "Next Step Clarity",
                "resonance": "Personal Urgency",
                "diagnosis": "Hesitation Discovery",
                "closure": "Next Step Clarity",
            }
            order = [
                "guardrails",
                "opening",
                "discovery",
                "evidence",
                "personal_urgency",
                "real_hesitation_reason",
                "clear_next_step",
                "resonance",
                "diagnosis",
                "closure",
            ]
            used = set()
            for key in order:
                if key in by_parameter:
                    detail = by_parameter[key]
                    if detail is not None and str(detail).strip() not in {"", "null", "None"}:
                        lines.append(f"- {labels.get(key, key)}: {str(detail).strip()}")
                    used.add(key)
            for key, detail in by_parameter.items():
                if key not in used and detail is not None and str(detail).strip() not in {"", "null", "None"}:
                    label = labels.get(str(key), str(key).replace("_", " ").title())
                    lines.append(f"- {label}: {str(detail).strip()}")
        if lines:
            return "\n".join(lines)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        lines = []
        for item in value:
            if item is None:
                continue
            text = _plain_summary_text(item).strip()
            if not text:
                continue
            if re.match(r"^[-•\d]", text):
                lines.append(text)
            else:
                lines.append(f"- {text}")
        return "\n".join(lines)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return _plain_summary_text(json.loads(text))
            except Exception:
                return value
        text = re.sub(r"\s+(?=\d+[.)]\s+)", "\n", text)
        return text
    return str(value)


def _section(result: Dict[str, Any], final_key: str, old_key: str | None = None) -> Dict[str, Any]:
    value = result.get(final_key)
    if isinstance(value, dict):
        return value
    if old_key:
        old_value = result.get(old_key)
        if isinstance(old_value, dict):
            return old_value
    return {}


def _score_number(section: Dict[str, Any]) -> float | None:
    if not isinstance(section, dict):
        return None
    if section.get("na") is True:
        return None
    score = section.get("score")
    if score is None:
        return None
    if isinstance(score, (int, float)):
        return float(score)
    match = re.search(r"\d+(?:\.\d+)?", str(score))
    return float(match.group(0)) if match else None


def _format_score(score: float | None) -> str:
    if score is None:
        return ""
    if abs(score - round(score)) < 0.001:
        return str(int(round(score)))
    return f"{score:.1f}".rstrip("0").rstrip(".")


def _format_average(score: float | None) -> str:
    if score is None:
        return ""
    return f"{score:.1f}"


def _average_from_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    ratio = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
    if ratio:
        numerator = float(ratio.group(1))
        denominator = float(ratio.group(2))
        if denominator > 0:
            return _format_average((numerator / denominator) * 10)

    number = re.search(r"\d+(?:\.\d+)?", text)
    if number:
        return _format_average(float(number.group(0)))

    return None


def _score_label(section: Dict[str, Any], include_suffix: bool = True) -> str:
    if isinstance(section, dict) and section.get("na") is True:
        return "N/A"
    score = _score_number(section)
    if score is None:
        return ""
    return f"{_format_score(score)}/10" if include_suffix else _format_score(score)


def _average_score(result: Dict[str, Any], call_type: str) -> str:
    guardrails = _section(result, "guardrails")
    if str(guardrails.get("result", "")).upper() == "FAIL":
        return "0.0"

    overall = result.get("overall_score") or {}
    if isinstance(overall, dict):
        direct = overall.get("average_score")
        normalized = _average_from_text(direct)
        if normalized is not None:
            return normalized

    if call_type == "follow_up_only":
        scores = [_score_number(_section(result, "clear_next_step", "closure"))]
    else:
        scores = [
            _score_number(_section(result, "opening")),
            _score_number(_section(result, "discovery")),
            _score_number(_section(result, "evidence")),
            _score_number(_section(result, "personal_urgency", "resonance")),
            _score_number(_section(result, "real_hesitation_reason", "diagnosis")),
            _score_number(_section(result, "clear_next_step", "closure")),
        ]
    valid = [s for s in scores if s is not None]
    if not valid:
        return ""
    avg = sum(valid) / len(valid)
    return _format_average(avg)


def _tone_truth_fail_details(guardrails: Dict[str, Any]) -> str:
    failed_part = (
        guardrails.get("failed_part")
        or guardrails.get("failure_type")
        or guardrails.get("failed_component")
        or "Not specified"
    )
    what_said = (
        guardrails.get("what_student_partner_said")
        or guardrails.get("quote")
        or guardrails.get("exact_quote")
        or guardrails.get("line_that_failed")
        or "Not specified"
    )
    why_failed = (
        guardrails.get("why_it_failed")
        or guardrails.get("reason")
        or guardrails.get("false_information_detail")
        or "Not specified"
    )
    right_version = (
        guardrails.get("what_should_have_been_said")
        or guardrails.get("correct_version")
        or guardrails.get("right_information")
        or guardrails.get("what_is_right")
        or "Not specified"
    )

    lines = [
        "Tone + Truth: FAIL",
        f"Failed part: {failed_part}",
        f"Student partner said/did: {what_said}",
        f"Why it failed: {why_failed}",
        f"What should have been said/done: {right_version}",
        "Remaining parameters: Not evaluated because Tone + Truth failed",
    ]
    return "\n".join(lines)


def _score_parameter_wise_from_result(result: Dict[str, Any], call_type: str) -> str:
    guardrails = _section(result, "guardrails")
    guardrails_result = guardrails.get("result", "")
    if str(guardrails_result).upper() == "FAIL":
        return _tone_truth_fail_details(guardrails)

    if call_type == "follow_up_only":
        clear_next_step = _section(result, "clear_next_step", "closure")
        return "\n".join([
            f"Tone + Truth: {guardrails_result}",
            f"Next Step Clarity: {_score_label(clear_next_step)}",
        ])

    opening = _section(result, "opening")
    discovery = _section(result, "discovery")
    evidence = _section(result, "evidence")
    personal_urgency = _section(result, "personal_urgency", "resonance")
    real_hesitation = _section(result, "real_hesitation_reason", "diagnosis")
    clear_next_step = _section(result, "clear_next_step", "closure")

    return "\n".join([
        f"Tone + Truth: {guardrails_result}",
        f"Opening: {_score_label(opening)}",
        f"Pain Point Discovery: {_score_label(discovery)}",
        f"Evidence: {_score_label(evidence)}",
        f"Personal Urgency: {_score_label(personal_urgency)}",
        f"Hesitation Discovery: {_score_label(real_hesitation)}",
        f"Next Step Clarity: {_score_label(clear_next_step)}",
    ])


def _slug_filename(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    return name or "call_recording"


def _ensure_bucket(client: Client, bucket_name: str) -> None:
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


def _upload_bytes(client: Client, bucket_name: str, object_path: str, file_bytes: bytes, content_type: str) -> str | None:
    _ensure_bucket(client, bucket_name)
    file_options = {"content-type": content_type, "upsert": "true"}
    try:
        client.storage.from_(bucket_name).upload(object_path, file_bytes, file_options=file_options)
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
    existing_audio_url: str | None = None,
) -> tuple[str | None, str | None]:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid4().hex[:8]
    safe_audio_name = _slug_filename(audio_filename)

    audio_url = existing_audio_url
    if audio_bytes and not existing_audio_url:
        content_type = mimetypes.guess_type(safe_audio_name)[0] or "application/octet-stream"
        audio_path = f"{student_number}/{timestamp}_{unique_id}_{safe_audio_name}"
        audio_url = _upload_bytes(client, AUDIO_BUCKET, audio_path, audio_bytes, content_type)

    transcript_bytes = (transcript or "").encode("utf-8")
    transcript_path = f"{student_number}/{timestamp}_{unique_id}_{safe_audio_name}.txt"
    transcript_url = _upload_bytes(client, TRANSCRIPT_BUCKET, transcript_path, transcript_bytes, "text/plain; charset=utf-8")
    return audio_url, transcript_url


def build_db_row(
    student_number: str,
    audio_filename: str,
    transcript: str,
    result: dict | str,
    call_audio_link: str | None = None,
    call_transcript_link: str | None = None,
) -> Dict[str, Any]:
    today = date.today().isoformat()
    base = {
        "Date": today,
        "Student Number": student_number,
        "Call Recording Link": call_audio_link or audio_filename,
        "Transcript Link": call_transcript_link,
    }

    if is_not_worthy_result(result):
        return {
            **base,
            "Call Type": "not_worthy",
            "Converted Status": "Not converted",
            "Average Score": "",
            "Score Parameter Wise": "Not Worthy",
            "Strengths": "",
            "Improvement Areas": "",
            "Learnings": "",
        }

    if not isinstance(result, dict):
        raise RuntimeError("OpenAI returned an unsupported response format.")

    call_type = result.get("call_type") or "full_analysis"
    if call_type not in {"full_analysis", "follow_up_only"}:
        call_type = "full_analysis"

    converted_status = result.get("converted_status")
    if converted_status not in {"Converted", "Not converted"}:
        converted_status = "Not converted"

    return {
        **base,
        "Call Type": call_type,
        "Converted Status": converted_status,
        "Average Score": _average_score(result, call_type),
        "Score Parameter Wise": _score_parameter_wise_from_result(result, call_type),
        "Strengths": _plain_summary_text(result.get("strengths") or result.get("top_strength")),
        "Improvement Areas": _plain_summary_text(result.get("improvement_areas") or result.get("biggest_improvement_area")),
        "Learnings": _plain_summary_text(result.get("learnings") or result.get("coaching_note")),
    }


def save_result(
    student_number: str,
    audio_filename: str,
    transcript: str,
    result: dict | str,
    audio_bytes: bytes | None = None,
    existing_audio_url: str | None = None,
) -> Dict[str, Any]:
    client = get_client()
    audio_url, transcript_url = upload_call_files(
        client,
        student_number,
        audio_filename,
        audio_bytes,
        transcript,
        existing_audio_url=existing_audio_url,
    )
    row = build_db_row(student_number, audio_filename, transcript, result, audio_url, transcript_url)
    response = client.table("call_scores").insert(row).execute()
    if getattr(response, "data", None):
        return response.data[0]
    return row


def enqueue_call_batch(file_payloads: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
    """Upload raw call recordings and create pending backend jobs."""
    if not file_payloads:
        raise RuntimeError("No files were selected.")

    client = get_client()
    batch_id = uuid4().hex
    now_iso = datetime.utcnow().isoformat()

    batch_row = {
        "batch_id": batch_id,
        "created_at": now_iso,
        "status": "pending",
        "total_files": len(file_payloads),
        "completed_files": 0,
        "failed_files": 0,
        "report_sent": False,
        "error_email_sent": False,
    }
    client.table("call_processing_batches").insert(batch_row).execute()

    queued_files: List[Dict[str, Any]] = []
    job_rows: List[Dict[str, Any]] = []
    for payload in file_payloads:
        filename = str(payload.get("name") or "call_recording")
        file_bytes = payload.get("bytes") or b""
        student_number = str(payload.get("student_number") or "unknown")
        safe_audio_name = _slug_filename(filename)
        unique_id = uuid4().hex[:8]
        content_type = mimetypes.guess_type(safe_audio_name)[0] or "application/octet-stream"
        object_path = f"queued/{batch_id}/{student_number}_{unique_id}_{safe_audio_name}"
        audio_url = _upload_bytes(client, AUDIO_BUCKET, object_path, file_bytes, content_type)
        if not audio_url:
            raise RuntimeError(f"Could not upload {filename} to storage.")

        job_rows.append(
            {
                "batch_id": batch_id,
                "status": "pending",
                "student_number": student_number,
                "audio_filename": filename,
                "audio_storage_path": object_path,
                "audio_public_url": audio_url,
                "attempt_count": 0,
            }
        )
        queued_files.append(
            {
                "filename": filename,
                "student_number": student_number,
                "audio_public_url": audio_url,
            }
        )

    client.table("call_processing_jobs").insert(job_rows).execute()
    return batch_id, queued_files


def fetch_recent_batches(limit: int = 50) -> List[Dict[str, Any]]:
    client = get_client()
    response = (
        client.table("call_processing_batches")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


def fetch_pending_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    client = get_client()
    response = (
        client.table("call_processing_jobs")
        .select("*")
        .eq("status", "pending")
        .order("created_at")
        .limit(limit)
        .execute()
    )
    return response.data or []


def mark_job_processing(job: Dict[str, Any]) -> None:
    client = get_client()
    attempt_count = int(job.get("attempt_count") or 0) + 1
    client.table("call_processing_jobs").update(
        {
            "status": "processing",
            "started_at": datetime.utcnow().isoformat(),
            "attempt_count": attempt_count,
            "error_message": None,
        }
    ).eq("id", job["id"]).execute()


def mark_job_completed(job_id: str, saved_row: Dict[str, Any]) -> None:
    client = get_client()
    client.table("call_processing_jobs").update(
        {
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
            "saved_row_json": saved_row,
            "error_message": None,
        }
    ).eq("id", job_id).execute()


def mark_job_failed(job_id: str, error_message: str) -> None:
    client = get_client()
    client.table("call_processing_jobs").update(
        {
            "status": "failed",
            "completed_at": datetime.utcnow().isoformat(),
            "error_message": error_message[:4000],
        }
    ).eq("id", job_id).execute()


def reset_stale_processing_jobs(hours: int = 2) -> None:
    client = get_client()
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    try:
        client.table("call_processing_jobs").update({"status": "pending"}).eq("status", "processing").lt("started_at", cutoff).execute()
    except Exception:
        pass


def fetch_jobs_for_batch(batch_id: str) -> List[Dict[str, Any]]:
    client = get_client()
    response = (
        client.table("call_processing_jobs")
        .select("*")
        .eq("batch_id", batch_id)
        .order("created_at")
        .execute()
    )
    return response.data or []


def update_batch(batch_id: str, updates: Dict[str, Any]) -> None:
    client = get_client()
    client.table("call_processing_batches").update(updates).eq("batch_id", batch_id).execute()


def fetch_batch(batch_id: str) -> Dict[str, Any] | None:
    client = get_client()
    response = client.table("call_processing_batches").select("*").eq("batch_id", batch_id).limit(1).execute()
    rows = response.data or []
    return rows[0] if rows else None


def _date_only(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if "T" in text:
        return text.split("T", 1)[0]
    if " " in text:
        return text.split(" ", 1)[0]
    return text[:10]


def _normalize_display_row(row: Dict[str, Any]) -> Dict[str, Any]:
    row["Date"] = _date_only(row.get("Date"))
    normalized_average = _average_from_text(row.get("Average Score"))
    if normalized_average is not None:
        row["Average Score"] = normalized_average
    row["Learnings"] = _plain_summary_text(row.get("Learnings"))
    row["Strengths"] = _plain_summary_text(row.get("Strengths"))
    row["Improvement Areas"] = _plain_summary_text(row.get("Improvement Areas"))
    return row


def _sort_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = [_normalize_display_row(dict(r)) for r in rows]
    return sorted(normalized, key=lambda r: str(r.get("Date", "")), reverse=True)


def fetch_all_results(limit: int = 500) -> List[Dict[str, Any]]:
    client = get_client()
    response = client.table("call_scores").select("*").limit(limit).execute()
    return _sort_rows(response.data or [])


def fetch_results_for_date(target_date: date) -> List[Dict[str, Any]]:
    rows = fetch_all_results(limit=2000)
    target = target_date.isoformat()
    return [r for r in rows if str(r.get("Date", ""))[:10] == target]
