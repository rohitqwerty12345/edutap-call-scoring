import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Any, Dict, List, Set

import requests

from email_sender import send_cost_report, send_error_report, send_report
from cost_utils import merge_cost_parts
from openai_client import (
    build_batch_request,
    create_openai_batch,
    download_openai_file_text,
    parse_batch_output_text,
    retrieve_openai_batch,
)
from pipeline import process_single_file, transcribe_and_prepare_llm_input
from supabase_client import (
    fetch_batch,
    fetch_jobs_for_batch,
    fetch_openai_batches_to_check,
    fetch_pending_jobs,
    mark_batch_openai_submitted,
    mark_job_completed,
    mark_job_failed,
    mark_job_openai_batch_submitted,
    mark_job_processing,
    mark_job_transcribed,
    reset_stale_processing_jobs,
    save_result,
    update_batch,
    update_batch_openai_status,
    update_job,
)


def get_int_setting(name: str, default: int, minimum: int = 1, maximum: int = 100) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except Exception:
        value = default
    return max(minimum, min(value, maximum))


def get_processing_mode() -> str:
    mode = (os.getenv("OPENAI_PROCESSING_MODE") or "standard").strip().lower()
    return "batch" if mode == "batch" else "standard"


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


def process_standard_job(job: Dict[str, Any]) -> Dict[str, Any]:
    job_id = job["id"]
    filename = job.get("audio_filename") or "call_recording"
    batch_id = job.get("batch_id")
    student_number = job.get("student_number") or "unknown"

    mark_job_processing(job)
    try:
        print(f"Downloading audio: {filename}", flush=True)
        audio_bytes = download_audio(job)
        print(f"Processing through Deepgram + OpenAI: {filename}", flush=True)
        result = process_single_file(
            audio_bytes,
            filename,
            existing_audio_url=job.get("audio_public_url"),
        )
        saved_row = result["saved_row"]
        cost_json = result.get("cost_json")
        mark_job_completed(job_id, saved_row, cost_json=cost_json)
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


def prepare_batch_job(job: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(job["id"])
    filename = job.get("audio_filename") or "call_recording"
    batch_id = job.get("batch_id")
    student_number = job.get("student_number") or "unknown"

    mark_job_processing(job)
    try:
        print(f"Downloading audio for batch: {filename}", flush=True)
        audio_bytes = download_audio(job)
        print(f"Transcribing for batch: {filename}", flush=True)
        prepared = transcribe_and_prepare_llm_input(audio_bytes, filename, student_number=student_number)
        transcript_for_llm = prepared["transcript_for_llm"]
        call_number = int(prepared["call_number"])
        cost_json = prepared.get("cost_json") or {}
        cost_json.update({
            "student_number": student_number,
            "audio_filename": filename,
            "audio_public_url": job.get("audio_public_url"),
            "processing_mode": "batch",
        })
        mark_job_transcribed(job_id, transcript_for_llm, call_number, cost_json=cost_json)

        custom_id = job_id
        request = build_batch_request(custom_id, transcript_for_llm)
        return {
            "ok": True,
            "batch_id": batch_id,
            "job_id": job_id,
            "filename": filename,
            "student_number": student_number,
            "custom_id": custom_id,
            "request": request,
        }
    except Exception as exc:
        technical_error = str(exc)
        mark_job_failed(job_id, technical_error)
        return {
            "ok": False,
            "batch_id": batch_id,
            "job_id": job_id,
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
    pending_statuses = {
        "pending",
        "processing",
        "transcribed",
        "openai_batch_submitted",
        "openai_batch_validating",
        "openai_batch_in_progress",
        "openai_batch_finalizing",
    }
    pending_jobs = [j for j in jobs if j.get("status") in pending_statuses]

    updates = {
        "completed_files": len(completed_jobs),
        "failed_files": len(failed_jobs),
    }

    if pending_jobs:
        current_status = str(batch.get("status") or "pending")
        updates["status"] = current_status if current_status.startswith("openai_batch_") else "processing"
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
    cost_report_sent = bool(batch.get("cost_report_sent"))
    error_email_sent = bool(batch.get("error_email_sent"))

    completed_rows: List[Dict[str, Any]] = []
    cost_items: List[Dict[str, Any]] = []
    for job in completed_jobs + failed_jobs:
        saved_row = job.get("saved_row_json")
        if isinstance(saved_row, dict) and job in completed_jobs:
            completed_rows.append(saved_row)
        cost_json = job.get("cost_json")
        if isinstance(cost_json, dict):
            enriched_cost = dict(cost_json)
            enriched_cost.setdefault("student_number", job.get("student_number"))
            enriched_cost.setdefault("audio_filename", job.get("audio_filename"))
            enriched_cost.setdefault("audio_public_url", job.get("audio_public_url"))
            enriched_cost.setdefault("job_status", job.get("status"))
            cost_items.append(enriched_cost)

    if completed_rows and not report_sent:
        send_report(completed_rows, batch_label=str(date.today()))
        updates["report_sent"] = True

    if cost_items and not cost_report_sent:
        try:
            send_cost_report(cost_items, batch_label=str(date.today()))
            updates["cost_report_sent"] = True
        except Exception as exc:
            updates["last_error"] = f"Cost report email failed: {str(exc)[:3800]}"
            print(f"Cost report email failed: {exc}", flush=True)

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


def process_pending_standard(jobs: List[Dict[str, Any]], max_parallel_calls: int) -> Set[str]:
    batch_ids: Set[str] = set(str(j.get("batch_id")) for j in jobs if j.get("batch_id"))
    with ThreadPoolExecutor(max_workers=min(max_parallel_calls, len(jobs))) as executor:
        future_to_job = {executor.submit(process_standard_job, job): job for job in jobs}
        for future in as_completed(future_to_job):
            result = future.result()
            batch_id = result.get("batch_id")
            if batch_id:
                batch_ids.add(str(batch_id))
            if result.get("ok"):
                print(f"Completed: {result.get('filename')}", flush=True)
            else:
                print(f"Failed: {result.get('filename')} | {result.get('simple_error')} | {result.get('technical_error')}", flush=True)
    return batch_ids


def submit_pending_as_openai_batch(jobs: List[Dict[str, Any]], max_parallel_calls: int) -> Set[str]:
    batch_ids: Set[str] = set(str(j.get("batch_id")) for j in jobs if j.get("batch_id"))
    prepared_items: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=min(max_parallel_calls, len(jobs))) as executor:
        future_to_job = {executor.submit(prepare_batch_job, job): job for job in jobs}
        for future in as_completed(future_to_job):
            result = future.result()
            batch_id = result.get("batch_id")
            if batch_id:
                batch_ids.add(str(batch_id))
            if result.get("ok"):
                prepared_items.append(result)
                print(f"Transcribed and ready for OpenAI batch: {result.get('filename')}", flush=True)
            else:
                print(f"Failed before OpenAI batch: {result.get('filename')} | {result.get('technical_error')}", flush=True)

    if not prepared_items:
        return batch_ids

    try:
        openai_batch = create_openai_batch(
            [item["request"] for item in prepared_items],
            description=f"EduTap call scoring {date.today().isoformat()}",
        )
        openai_batch_id = openai_batch["batch_id"]
        input_file_id = openai_batch.get("input_file_id")
        status = str(openai_batch.get("status") or "submitted")
        app_status = f"openai_batch_{status}" if status in {"validating", "in_progress", "finalizing"} else "openai_batch_submitted"

        print(f"OpenAI batch submitted: {openai_batch_id} | status={status}", flush=True)
        for item in prepared_items:
            mark_job_openai_batch_submitted(item["job_id"], openai_batch_id, item["custom_id"])
        for batch_id in batch_ids:
            mark_batch_openai_submitted(batch_id, openai_batch_id, input_file_id, status=app_status)
    except Exception as exc:
        error = str(exc)
        print(f"OpenAI batch submission failed: {error}", flush=True)
        for item in prepared_items:
            mark_job_failed(item["job_id"], error)
        for batch_id in batch_ids:
            update_batch(batch_id, {"status": "failed", "last_error": error[:4000]})

    return batch_ids


def _jobs_by_custom_id_for_batches(app_batches: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    jobs_by_custom: Dict[str, Dict[str, Any]] = {}
    for app_batch in app_batches:
        for job in fetch_jobs_for_batch(str(app_batch.get("batch_id"))):
            custom_id = str(job.get("openai_custom_id") or "")
            if custom_id:
                jobs_by_custom[custom_id] = job
    return jobs_by_custom


def poll_openai_batches() -> Set[str]:
    """Check submitted OpenAI batches, save completed results, and finalize app batches."""
    app_batches = fetch_openai_batches_to_check(limit=20)
    touched_batch_ids: Set[str] = set()
    if not app_batches:
        print("No OpenAI batches waiting for polling.", flush=True)
        return touched_batch_ids

    batches_by_openai_id: Dict[str, List[Dict[str, Any]]] = {}
    for app_batch in app_batches:
        openai_batch_id = str(app_batch.get("openai_batch_id") or "")
        if not openai_batch_id:
            continue
        batches_by_openai_id.setdefault(openai_batch_id, []).append(app_batch)

    for openai_batch_id, matching_app_batches in batches_by_openai_id.items():
        app_batch_ids = [str(b.get("batch_id")) for b in matching_app_batches if b.get("batch_id")]
        touched_batch_ids.update(app_batch_ids)
        try:
            info = retrieve_openai_batch(openai_batch_id)
            status = str(info.get("status") or "unknown")
            output_file_id = info.get("output_file_id")
            error_file_id = info.get("error_file_id")
            print(f"OpenAI batch status: {openai_batch_id} | {status}", flush=True)

            if status in {"validating", "in_progress", "finalizing"}:
                app_status = f"openai_batch_{status}"
                for batch_id in app_batch_ids:
                    update_batch_openai_status(batch_id, app_status, openai_batch_status=status)
                continue

            if status == "completed" and output_file_id:
                output_text = download_openai_file_text(str(output_file_id))
                parsed_outputs = parse_batch_output_text(output_text)
                jobs_by_custom = _jobs_by_custom_id_for_batches(matching_app_batches)

                for parsed in parsed_outputs:
                    custom_id = str(parsed.get("custom_id") or "")
                    job = jobs_by_custom.get(custom_id)
                    if not job:
                        print(f"OpenAI batch output had unknown custom_id: {custom_id}", flush=True)
                        continue

                    job_id = str(job["id"])
                    if parsed.get("ok"):
                        try:
                            result = parsed["parsed_output"]
                            cost_json = merge_cost_parts(job.get("cost_json"), parsed.get("cost"))
                            cost_json.update({
                                "student_number": str(job.get("student_number") or "unknown"),
                                "audio_filename": str(job.get("audio_filename") or "call_recording"),
                                "audio_public_url": job.get("audio_public_url"),
                                "processing_mode": "batch",
                            })
                            saved_row = save_result(
                                student_number=str(job.get("student_number") or "unknown"),
                                audio_filename=str(job.get("audio_filename") or "call_recording"),
                                transcript=str(job.get("transcript_text") or ""),
                                result=result,
                                audio_bytes=None,
                                existing_audio_url=job.get("audio_public_url"),
                                call_number=job.get("call_number"),
                                cost_json=cost_json,
                            )
                            update_job(job_id, {"openai_response_json": parsed.get("raw_item"), "cost_json": cost_json})
                            mark_job_completed(job_id, saved_row, cost_json=cost_json)
                            print(f"Saved completed batch result: {job.get('audio_filename')}", flush=True)
                        except Exception as exc:
                            mark_job_failed(job_id, str(exc))
                            print(f"Failed saving batch result: {job.get('audio_filename')} | {exc}", flush=True)
                    else:
                        mark_job_failed(job_id, str(parsed.get("error") or "OpenAI batch request failed."))

                # Any jobs in this OpenAI batch with no output line should be failed so the batch can finalize.
                seen_custom_ids = {str(item.get("custom_id") or "") for item in parsed_outputs}
                for custom_id, job in jobs_by_custom.items():
                    if custom_id not in seen_custom_ids and job.get("status") not in {"completed", "failed"}:
                        mark_job_failed(str(job["id"]), "OpenAI batch completed but no output was returned for this request.")

                for batch_id in app_batch_ids:
                    update_batch_openai_status(
                        batch_id,
                        "openai_batch_completed",
                        openai_batch_status=status,
                        openai_output_file_id=str(output_file_id),
                        openai_error_file_id=str(error_file_id) if error_file_id else None,
                    )
                continue

            # Final bad states.
            if status in {"failed", "expired", "cancelled", "canceled"}:
                for app_batch in matching_app_batches:
                    for job in fetch_jobs_for_batch(str(app_batch.get("batch_id"))):
                        if job.get("status") not in {"completed", "failed"}:
                            mark_job_failed(str(job["id"]), f"OpenAI batch ended with status: {status}")
                for batch_id in app_batch_ids:
                    update_batch_openai_status(
                        batch_id,
                        "failed",
                        openai_batch_status=status,
                        openai_error_file_id=str(error_file_id) if error_file_id else None,
                        last_error=f"OpenAI batch ended with status: {status}",
                    )
                continue

            for batch_id in app_batch_ids:
                update_batch_openai_status(batch_id, "openai_batch_in_progress", openai_batch_status=status)
        except Exception as exc:
            error = str(exc)
            print(f"Error polling OpenAI batch {openai_batch_id}: {error}", flush=True)
            for batch_id in app_batch_ids:
                update_batch_openai_status(batch_id, "openai_batch_in_progress", last_error=error)

    return touched_batch_ids


def main() -> None:
    max_jobs = get_int_setting("MAX_JOBS_PER_RUN", 50, minimum=1, maximum=100)
    max_parallel_calls = get_int_setting("MAX_PARALLEL_CALLS", 5, minimum=1, maximum=20)
    mode = get_processing_mode()

    print("EduTap backend worker started.", flush=True)
    print(f"OPENAI_PROCESSING_MODE={mode}", flush=True)
    print(f"MAX_JOBS_PER_RUN={max_jobs}", flush=True)
    print(f"MAX_PARALLEL_CALLS={max_parallel_calls}", flush=True)

    all_touched_batch_ids: Set[str] = set()

    # Always poll first. This lets scheduled runs complete old OpenAI Batch API jobs.
    all_touched_batch_ids.update(poll_openai_batches())

    reset_stale_processing_jobs(hours=2)
    jobs = fetch_pending_jobs(limit=max_jobs)

    if not jobs:
        print("No pending jobs found.", flush=True)
    else:
        print(f"Found {len(jobs)} pending job(s).", flush=True)
        if mode == "batch":
            all_touched_batch_ids.update(submit_pending_as_openai_batch(jobs, max_parallel_calls))
        else:
            all_touched_batch_ids.update(process_pending_standard(jobs, max_parallel_calls))

    for batch_id in sorted(all_touched_batch_ids):
        print(f"Finalizing batch: {batch_id}", flush=True)
        finalize_batch(batch_id)

    print("EduTap backend worker finished.", flush=True)


if __name__ == "__main__":
    main()
