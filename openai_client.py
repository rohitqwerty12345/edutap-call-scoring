import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List

from dotenv import load_dotenv
from openai import OpenAI

from scoring_prompt import SCORING_PROMPT

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


def get_client() -> OpenAI:
    api_key = get_setting("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    return OpenAI(api_key=api_key)


def current_openai_model() -> str:
    return get_setting("OPENAI_MODEL", "gpt-5.5") or "gpt-5.5"


def current_reasoning_effort() -> str:
    # Medium is the production-safe default for cost/speed. Override in secrets if needed.
    return get_setting("OPENAI_REASONING_EFFORT", "medium") or "medium"


def _get_response_text(response: Any) -> str:
    """Return text from an OpenAI Responses API response or a dict body."""
    if isinstance(response, dict):
        text = response.get("output_text")
        if text:
            return str(text).strip()
        parts: list[str] = []
        for item in response.get("output", []) or []:
            for content in item.get("content", []) or []:
                if isinstance(content, dict):
                    value = content.get("text")
                    if value:
                        parts.append(str(value))
        return "\n".join(parts).strip()

    text = getattr(response, "output_text", None)
    if text:
        return text.strip()

    try:
        parts = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                value = getattr(content, "text", None)
                if value:
                    parts.append(value)
        return "\n".join(parts).strip()
    except Exception:
        return ""


def _parse_model_output(raw: str) -> dict | str:
    text = (raw or "").strip()

    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()

    if text == "not_worthy":
        return "not_worthy"

    return json.loads(text)


def build_openai_input(transcript: str) -> str:
    return f"Here is the call transcript to analyze:\n\n{transcript}"


def build_responses_body(transcript: str) -> Dict[str, Any]:
    """Build the body used by both standard Responses API and Batch API."""
    return {
        "model": current_openai_model(),
        "instructions": SCORING_PROMPT,
        "input": build_openai_input(transcript or ""),
        "reasoning": {"effort": current_reasoning_effort()},
    }


def score_transcript(transcript: str) -> dict | str:
    debug_result = score_transcript_debug(transcript)
    return debug_result["parsed_output"]


def score_transcript_debug(transcript: str) -> dict:
    """
    Standard/immediate OpenAI scoring.
    Returns exact prompt, transcript input, raw model output, and parsed output.
    """
    model = current_openai_model()
    reasoning_effort = current_reasoning_effort()
    user_input = build_openai_input(transcript or "")

    if not transcript or not transcript.strip():
        return {
            "model": model,
            "reasoning_effort": reasoning_effort,
            "system_prompt": SCORING_PROMPT,
            "user_input": user_input,
            "raw_output": "not_worthy",
            "parsed_output": "not_worthy",
        }

    client = get_client()
    response = client.responses.create(**build_responses_body(transcript))

    raw = _get_response_text(response)
    parsed = _parse_model_output(raw)

    return {
        "model": model,
        "reasoning_effort": reasoning_effort,
        "system_prompt": SCORING_PROMPT,
        "user_input": user_input,
        "raw_output": raw,
        "parsed_output": parsed,
    }


def build_batch_request(custom_id: str, transcript: str) -> Dict[str, Any]:
    """One JSONL line for OpenAI Batch API using the Responses API endpoint."""
    return {
        "custom_id": str(custom_id),
        "method": "POST",
        "url": "/v1/responses",
        "body": build_responses_body(transcript),
    }


def create_openai_batch(requests: Iterable[Dict[str, Any]], description: str = "EduTap call scoring batch") -> Dict[str, Any]:
    """Upload JSONL and create an OpenAI batch. Returns IDs/status for DB storage."""
    request_list = list(requests)
    if not request_list:
        raise RuntimeError("No OpenAI batch requests were prepared.")

    client = get_client()

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        for item in request_list:
            tmp.write(json.dumps(item, ensure_ascii=False) + "\n")

    try:
        with tmp_path.open("rb") as fh:
            input_file = client.files.create(file=fh, purpose="batch")

        batch = client.batches.create(
            input_file_id=input_file.id,
            endpoint="/v1/responses",
            completion_window="24h",
            metadata={"description": description},
        )

        return {
            "input_file_id": input_file.id,
            "batch_id": batch.id,
            "status": getattr(batch, "status", "submitted"),
        }
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def retrieve_openai_batch(openai_batch_id: str) -> Dict[str, Any]:
    client = get_client()
    batch = client.batches.retrieve(openai_batch_id)
    return {
        "id": getattr(batch, "id", openai_batch_id),
        "status": getattr(batch, "status", None),
        "output_file_id": getattr(batch, "output_file_id", None),
        "error_file_id": getattr(batch, "error_file_id", None),
        "request_counts": getattr(batch, "request_counts", None),
        "raw": batch,
    }


def download_openai_file_text(file_id: str) -> str:
    client = get_client()
    content = client.files.content(file_id)

    # Newer SDKs expose text directly.
    text = getattr(content, "text", None)
    if callable(text):
        return text()
    if isinstance(text, str):
        return text

    # Binary/read fallback.
    read = getattr(content, "read", None)
    if callable(read):
        data = read()
        if isinstance(data, bytes):
            return data.decode("utf-8")
        return str(data)

    if isinstance(content, bytes):
        return content.decode("utf-8")
    return str(content)


def parse_batch_output_text(output_text: str) -> List[Dict[str, Any]]:
    """Parse OpenAI batch output JSONL into custom_id/result/error records."""
    parsed_lines: list[dict[str, Any]] = []
    for line_no, line in enumerate((output_text or "").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            custom_id = str(item.get("custom_id") or "")
            error = item.get("error")
            response = item.get("response") or {}
            body = response.get("body") if isinstance(response, dict) else None
            status_code = response.get("status_code") if isinstance(response, dict) else None

            if error or not body or (status_code is not None and int(status_code) >= 400):
                parsed_lines.append(
                    {
                        "custom_id": custom_id,
                        "ok": False,
                        "error": error or body or f"OpenAI batch response status {status_code}",
                        "raw_item": item,
                    }
                )
                continue

            raw_output = _get_response_text(body)
            parsed_output = _parse_model_output(raw_output)
            parsed_lines.append(
                {
                    "custom_id": custom_id,
                    "ok": True,
                    "raw_output": raw_output,
                    "parsed_output": parsed_output,
                    "raw_item": item,
                }
            )
        except Exception as exc:
            parsed_lines.append(
                {
                    "custom_id": "",
                    "ok": False,
                    "error": f"Could not parse batch output line {line_no}: {exc}",
                    "raw_item": line,
                }
            )
    return parsed_lines
