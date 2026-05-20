import json
import os
from typing import Any, Dict

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


client = OpenAI(api_key=get_setting("OPENAI_API_KEY"))


def _get_response_text(response: Any) -> str:
    """Return text from an OpenAI Responses API response."""
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
    """
    The prompt contract is:
    - raw text: not_worthy
    - JSON object: analysis-worthy scoring result
    """
    text = (raw or "").strip()

    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()

    if text == "not_worthy":
        return "not_worthy"

    return json.loads(text)


def build_openai_input(transcript: str) -> str:
    """Exact user input sent to OpenAI after the system/developer prompt."""
    return f"Here is the call transcript to analyze:\n\n{transcript}"


def score_transcript(transcript: str) -> dict | str:
    """
    Normal scoring function used by the pipeline.
    Returns either:
    - "not_worthy"
    - parsed JSON dict
    """
    debug_result = score_transcript_debug(transcript)
    return debug_result["parsed_output"]


def score_transcript_debug(transcript: str) -> dict:
    """
    Temporary debug function.
    Returns the exact prompt, exact transcript input, raw OpenAI output, and parsed output.
    """
    if not transcript or not transcript.strip():
        return {
            "model": get_setting("OPENAI_MODEL", "gpt-5.5"),
            "reasoning_effort": get_setting("OPENAI_REASONING_EFFORT", "xhigh"),
            "system_prompt": SCORING_PROMPT,
            "user_input": build_openai_input(transcript),
            "raw_output": "not_worthy",
            "parsed_output": "not_worthy",
        }

    api_key = get_setting("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    model = get_setting("OPENAI_MODEL", "gpt-5.5")
    reasoning_effort = get_setting("OPENAI_REASONING_EFFORT", "xhigh")
    user_input = build_openai_input(transcript)

    response = client.responses.create(
        model=model,
        instructions=SCORING_PROMPT,
        input=user_input,
        reasoning={"effort": reasoning_effort},
    )

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
