import os
from datetime import date, datetime, time
from typing import Any, Dict, List

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


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
        return (
            result.get("status") == "not_worthy"
            or result.get("worthy") is False
        )

    return False


def _score_value(section: Dict[str, Any]) -> str | None:
    score = (section or {}).get("score")
    return None if score is None else str(score)


def _overall_total(overall: Dict[str, Any]) -> str | None:
    """
    Supports both:
    - new prompt shape: overall_score.total = "42/60"
    - old prompt shape: overall.total_score/out_of/percentage
    """
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


def build_db_row(
    student_number: str,
    audio_filename: str,
    transcript: str,
    result: dict | str,
) -> Dict[str, Any]:
    """
    Convert one scoring result into the Supabase row format.
    """
    if is_not_worthy_result(result):
        return {
            "student_number": student_number,
            "call_audio_link": audio_filename,
            "call_transcript": transcript,
            "analysis_worthy": False,
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

    diag = result.get("diagnosis", {}) or {}
    overall = result.get("overall_score", {}) or result.get("overall", {}) or {}

    return {
        "student_number": student_number,
        "call_audio_link": audio_filename,
        "call_transcript": transcript,
        "analysis_worthy": True,
        "guardrails": (result.get("guardrails", {}) or {}).get("result"),
        "opening_score": _score_value(result.get("opening", {}) or {}),
        "discovery_score": _score_value(result.get("discovery", {}) or {}),
        "evidence_score": _score_value(result.get("evidence", {}) or {}),
        "resonance_score": _score_value(result.get("resonance", {}) or {}),
        "diagnosis_score": "N/A" if diag.get("na") else _score_value(diag),
        "closure_score": _score_value(result.get("closure", {}) or {}),
        "overall_score": _overall_total(overall),
        "top_strength": result.get("top_strength"),
        "biggest_improvement_area": result.get("biggest_improvement_area"),
        "coaching_note": result.get("coaching_note"),
    }


def save_result(
    student_number: str,
    audio_filename: str,
    transcript: str,
    result: dict | str,
) -> Dict[str, Any]:
    """
    Save one call's results to Supabase and return the inserted row.
    """
    client = get_client()
    row = build_db_row(student_number, audio_filename, transcript, result)
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
    """
    Fetch rows created on a specific date.
    """
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
