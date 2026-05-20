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

    # Fallback for SDK/object-shape changes.
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


def score_transcript(transcript: str) -> dict | str:
    """
    Send transcript to the highest reasoning model configured for this app.
    Default model is gpt-5.5 with xhigh reasoning effort.
    Returns either:
    - "not_worthy"
    - parsed JSON dict
    """
    if not transcript or not transcript.strip():
        return "not_worthy"

    api_key = get_setting("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    response = client.responses.create(
        model=get_setting("OPENAI_MODEL", "gpt-5.5"),
        instructions=SCORING_PROMPT,
        input=f"Here is the call transcript to analyze:\n\n{transcript}",
        reasoning={"effort": get_setting("OPENAI_REASONING_EFFORT", "xhigh")},
    )

    raw = _get_response_text(response)
    return _parse_model_output(raw)
