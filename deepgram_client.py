import os
from typing import Any, Dict, Iterable, List

from deepgram import DeepgramClient, FileSource, PrerecordedOptions
from dotenv import load_dotenv

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


def _as_dict(obj: Any) -> Dict[str, Any]:
    """Deepgram SDK responses can be object-like or dict-like depending on version."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return {}


def _get_words(response: Any) -> List[Dict[str, Any]]:
    data = _as_dict(response)

    # Preferred dict path
    try:
        words = data["results"]["channels"][0]["alternatives"][0].get("words", [])
        return [_as_dict(w) for w in words]
    except Exception:
        pass

    # Object path fallback
    try:
        words = response.results.channels[0].alternatives[0].words
        return [_as_dict(w) for w in words]
    except Exception:
        return []


def transcribe_audio(file_bytes: bytes, filename: str) -> str:
    """
    Send audio bytes to Deepgram.
    Returns a diarized transcript.

    Speaker mapping assumption:
    - Speaker 0 = Agent
    - Speaker 1 = Student

    Verify this with a few real recordings. If the student speaks first in your audio,
    swap the labels in _speaker_label().
    """
    api_key = get_setting("DEEPGRAM_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPGRAM_API_KEY is missing.")

    client = DeepgramClient(api_key)

    payload: FileSource = {"buffer": file_bytes}

    options = PrerecordedOptions(
        model="nova-3",
        language="hi",
        diarize=True,
        punctuate=True,
        smart_format=True,
    )

    response = client.listen.prerecorded.v("1").transcribe_file(payload, options)
    words = _get_words(response)

    if not words:
        raise RuntimeError(f"No transcript words returned by Deepgram for {filename}.")

    transcript_lines: list[str] = []
    current_speaker = None
    current_text: list[str] = []

    for item in words:
        speaker = item.get("speaker", 0)
        word = item.get("word") or item.get("punctuated_word") or ""

        if word == "":
            continue

        if speaker != current_speaker:
            if current_text:
                transcript_lines.append(
                    f"{_speaker_label(current_speaker)}: {' '.join(current_text)}"
                )
                current_text = []
            current_speaker = speaker

        current_text.append(word)

    if current_text:
        transcript_lines.append(
            f"{_speaker_label(current_speaker)}: {' '.join(current_text)}"
        )

    return "\n".join(transcript_lines)


def _speaker_label(speaker: int | None) -> str:
    if speaker == 0:
        return "Speaker A (Agent)"
    if speaker == 1:
        return "Speaker B (Student)"
    return f"Speaker {speaker}"
