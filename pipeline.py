import re
from typing import Any, Dict

from deepgram_client import transcribe_audio
from openai_client import score_transcript
from supabase_client import is_not_worthy_result, save_result


def extract_student_number(filename: str) -> str:
    """
    Extract the mobile number from the filename.

    Expected format:
    xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx_7974141508.mp3

    Returns the number after the last underscore, before the extension.
    """
    match = re.search(r"_(\d+)\.\w+$", filename)
    if match:
        return match.group(1)

    fallback = re.search(r"(\d{10})", filename)
    if fallback:
        return fallback.group(1)

    return "unknown"


def process_single_file(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """
    Full pipeline for one recording file.

    Returns a status dict with:
    - filename
    - student_number
    - worthy
    - transcript
    - result
    - saved_row
    """
    student_number = extract_student_number(filename)

    transcript = transcribe_audio(file_bytes, filename)
    result = score_transcript(transcript)

    saved_row = save_result(
        student_number=student_number,
        audio_filename=filename,
        transcript=transcript,
        result=result,
    )

    return {
        "filename": filename,
        "student_number": student_number,
        "worthy": not is_not_worthy_result(result),
        "transcript": transcript,
        "result": result,
        "saved_row": saved_row,
    }
