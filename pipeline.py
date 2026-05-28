import re
from typing import Any, Dict

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


def process_single_file(file_bytes: bytes, filename: str, existing_audio_url: str | None = None) -> Dict[str, Any]:
    """
    Full pipeline for one recording file.
    """
    student_number = extract_student_number(filename)

    transcript = transcribe_audio(file_bytes, filename)

    call_number = get_next_call_number(student_number)
    transcript_for_llm = f"Call Number: {call_number}\n\n{transcript}"

    openai_debug = score_transcript_debug(transcript_for_llm)
    result = openai_debug["parsed_output"]

    saved_row = save_result(
        student_number=student_number,
        audio_filename=filename,
        transcript=transcript_for_llm,
        result=result,
        audio_bytes=None if existing_audio_url else file_bytes,
        existing_audio_url=existing_audio_url,
        call_number=call_number,
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
            "saved_row": saved_row,
        },
    }
