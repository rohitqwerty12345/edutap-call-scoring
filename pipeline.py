import re
from typing import Any, Dict

from cost_utils import merge_cost_parts
from deepgram_client import transcribe_audio
from openai_client import score_transcript_debug
from supabase_client import get_next_call_number, is_not_worthy_result, save_result


def extract_student_number(filename: str) -> str:
    """
    Extract the mobile number from the filename.

    Expected format:
    xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx_7974141508.mp3
    """
    match = re.search(r"_(\d+)\.\w+$", filename)
    if match:
        return match.group(1)

    fallback = re.search(r"(\d{10})", filename)
    if fallback:
        return fallback.group(1)

    return "unknown"


def transcribe_and_prepare_llm_input(file_bytes: bytes, filename: str, student_number: str | None = None) -> Dict[str, Any]:
    """Transcribe audio, allocate call number, and prepare transcript for LLM scoring."""
    clean_student_number = student_number or extract_student_number(filename)
    transcript = transcribe_audio(file_bytes, filename)
    call_number = get_next_call_number(clean_student_number)
    transcript_for_llm = f"Call Number: {call_number}\n\n{transcript}"
    return {
        "student_number": clean_student_number,
        "transcript": transcript,
        "call_number": call_number,
        "transcript_for_llm": transcript_for_llm,
        "cost_json": {
            "student_number": clean_student_number,
            "audio_filename": filename,
        },
    }


def process_single_file(file_bytes: bytes, filename: str, existing_audio_url: str | None = None) -> Dict[str, Any]:
    """
    Full standard/immediate pipeline for one recording file.
    Batch API mode uses transcribe_and_prepare_llm_input() and saves later.
    """
    student_number = extract_student_number(filename)
    prepared = transcribe_and_prepare_llm_input(file_bytes, filename, student_number=student_number)
    transcript = prepared["transcript"]
    call_number = prepared["call_number"]
    transcript_for_llm = prepared["transcript_for_llm"]

    openai_debug = score_transcript_debug(transcript_for_llm)
    result = openai_debug["parsed_output"]
    cost_json = merge_cost_parts(prepared.get("cost_json"), openai_debug.get("cost"))
    cost_json.update(
        {
            "student_number": student_number,
            "audio_filename": filename,
            "audio_public_url": existing_audio_url,
            "processing_mode": "standard",
            "openai_reasoning_effort": openai_debug.get("reasoning_effort"),
        }
    )

    saved_row = save_result(
        student_number=student_number,
        audio_filename=filename,
        transcript=transcript_for_llm,
        result=result,
        audio_bytes=None if existing_audio_url else file_bytes,
        existing_audio_url=existing_audio_url,
        call_number=call_number,
        cost_json=cost_json,
    )

    call_type = "not_worthy" if is_not_worthy_result(result) else result.get("call_type", "full_analysis") if isinstance(result, dict) else "full_analysis"

    return {
        "filename": filename,
        "student_number": student_number,
        "call_type": call_type,
        "worthy": not is_not_worthy_result(result),
        "transcript": transcript,
        "result": result,
        "saved_row": saved_row,
        "cost_json": cost_json,
        "debug": {
            "deepgram_transcript": transcript,
            "call_number": call_number,
            "llm_transcript": transcript_for_llm,
            "openai_model": openai_debug["model"],
            "openai_reasoning_effort": openai_debug["reasoning_effort"],
            "openai_system_prompt": openai_debug["system_prompt"],
            "openai_user_input": openai_debug["user_input"],
            "openai_raw_output": openai_debug["raw_output"],
            "openai_parsed_output": openai_debug["parsed_output"],
            "openai_usage": openai_debug.get("usage"),
            "cost_json": cost_json,
            "saved_row": saved_row,
        },
    }
