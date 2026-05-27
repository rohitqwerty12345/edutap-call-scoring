import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Any, Dict, List, Set

import requests

from email_sender import send_error_report, send_report
from pipeline import process_single_file
from supabase_client import (
    fetch_batch,
    fetch_jobs_for_batch,
    fetch_pending_jobs,
    mark_job_completed,
    mark_job_failed,
    mark_job_processing,
    reset_stale_processing_jobs,
    update_batch,
)


def get_int_setting(name: str, default: int, minimum: int = 1, maximum: int = 100) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except Exception:
        value = default
    return max(minimum, min(value, maximum))


def simple_error_message(exc: Exception) -> str:
    text = str(exc or "").lower()
    if "deepgram_api_key" in text:
        return "The transcription service is not set up."
    if "openai_api_key" in text:
        return "The scoring service is not set up."
    if "supabase_url" in text or "supabase_key" in text:
        return "The database connection is not set up."
    if "no transcript words returned" in text:
        return "The audio could not be read clearly."
    if "json" in text or "expecting value" in text or "decode" in text:
        return "The AI scoring result could not be read properly."
    if "timeout" in text or "timed out" in text:
        return "Processing took too long."
    if "storage" in text or "bucket" in text or "upload" in text:
        return "The call file or transcript could not be saved."
    if "database" in text or "relation" in text or "column" in text or "insert" in text:
        return "The result could not be saved in the database."
    return "This call could not be processed."


def download_audio(job: Dict[str, Any]) -> bytes:
    url = job.get("audio_public_url")
    if not url:
        raise RuntimeError("Audio link is missing for this job.")
    response = requests.get(url, timeout=180)
    response.raise_for_status()
    return response.content


def process_job(job: Dict[str, Any]) -> Dict[str, Any]:
    job_id = job["id"]
    filename = job.get("audio_filename") or "call_recording"
    batch_id = job.get("batch_id")
    student_number = job.get("student_number") or "unknown"

    mark_job_processing(job)
    try:
        audio_bytes = download_audio(job)
        result = process_single_file(
            audio_bytes,
            filename,
            existing_audio_url=job.get("audio_public_url"),
        )
        saved_row = result["saved_row"]
        mark_job_completed(job_id, saved_row)
        return {
            "ok": True,
            "batch_id": batch_id,
            "filename": filename,
            "student_number": student_number,
            "saved_row": saved_row,
        }
    except Exception as exc:
        technical_error = str(exc)
        mark_job_failed(job_id, technical_error)
        return {
            "ok": False,
            "batch_id": batch_id,
            "filename": filename,
            "student_number": student_number,
            "simple_error": simple_error_message(exc),
            "technical_error": technical_error,
        }


def finalize_batch(batch_id: str) -> None:
    batch = fetch_batch(batch_id)
    if not batch:
        return

    jobs = fetch_jobs_for_batch(batch_id)
    completed_jobs = [j for j in jobs if j.get("status") == "completed"]
    failed_jobs = [j for j in jobs if j.get("status") == "failed"]
    pending_jobs = [j for j in jobs if j.get("status") in {"pending", "processing"}]

    updates = {
        "completed_files": len(completed_jobs),
        "failed_files": len(failed_jobs),
    }

    if pending_jobs:
        updates["status"] = "processing" if completed_jobs or failed_jobs else "pending"
        update_batch(batch_id, updates)
        return

    if failed_jobs and completed_jobs:
        updates["status"] = "completed_with_errors"
    elif failed_jobs and not completed_jobs:
        updates["status"] = "failed"
    else:
        updates["status"] = "completed"
    updates["completed_at"] = datetime.utcnow().isoformat()

    report_sent = bool(batch.get("report_sent"))
    error_email_sent = bool(batch.get("error_email_sent"))

    completed_rows: List[Dict[str, Any]] = []
    for job in completed_jobs:
        saved_row = job.get("saved_row_json")
        if isinstance(saved_row, dict):
            completed_rows.append(saved_row)

    if completed_rows and not report_sent:
        send_report(completed_rows, batch_label=str(date.today()))
        updates["report_sent"] = True

    if failed_jobs and not error_email_sent:
        error_items = []
        for job in failed_jobs:
            error_items.append(
                {
                    "filename": job.get("audio_filename", "Unknown file"),
                    "student_number": job.get("student_number", "Unknown"),
                    "simple_error": "This call could not be processed.",
                    "technical_error": job.get("error_message", "Not available"),
                }
            )
        send_error_report(error_items, batch_label=str(date.today()))
        updates["error_email_sent"] = True

    update_batch(batch_id, updates)


def main() -> None:
    max_jobs = get_int_setting("MAX_JOBS_PER_RUN", 50, minimum=1, maximum=100)
    max_parallel_calls = get_int_setting("MAX_PARALLEL_CALLS", 5, minimum=1, maximum=20)

    print("EduTap backend worker started.")
    print(f"MAX_JOBS_PER_RUN={max_jobs}")
    print(f"MAX_PARALLEL_CALLS={max_parallel_calls}")

    reset_stale_processing_jobs(hours=2)
    jobs = fetch_pending_jobs(limit=max_jobs)
    if not jobs:
        print("No pending jobs found. Exiting.")
        return

    print(f"Found {len(jobs)} pending job(s).")
    batch_ids: Set[str] = set(str(j.get("batch_id")) for j in jobs if j.get("batch_id"))

    with ThreadPoolExecutor(max_workers=min(max_parallel_calls, len(jobs))) as executor:
        future_to_job = {executor.submit(process_job, job): job for job in jobs}
        for future in as_completed(future_to_job):
            result = future.result()
            batch_id = result.get("batch_id")
            if batch_id:
                batch_ids.add(str(batch_id))
            if result.get("ok"):
                print(f"Completed: {result.get('filename')}")
            else:
                print(f"Failed: {result.get('filename')} | {result.get('simple_error')} | {result.get('technical_error')}")

    for batch_id in sorted(batch_ids):
        print(f"Finalizing batch: {batch_id}")
        finalize_batch(batch_id)

    print("EduTap backend worker finished.")


if __name__ == "__main__":
    main()
