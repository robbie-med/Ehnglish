"""Deepgram Nova-3: verbatim, fillers kept, no formatting, per-word confidence."""

from __future__ import annotations

from pathlib import Path

import httpx

from ..config import get_settings
from .base import EngineError, Transcript, TWord
from .http import request_with_retry

URL = "https://api.deepgram.com/v1/listen"


def transcribe(path: Path, *, language: str = "en", timeout: float = 120) -> Transcript:
    s = get_settings()
    if not s.deepgram_api_key:
        raise EngineError("EHNGLISH_DEEPGRAM_API_KEY not set")
    params = {
        "model": "nova-3",
        "language": language,
        "smart_format": "false",
        "punctuate": "false",
        "filler_words": "true",
        "numerals": "false",
        "profanity_filter": "false",
    }
    with path.open("rb") as f:
        body = f.read()
    r = request_with_retry(
        lambda: httpx.post(
            URL,
            params=params,
            content=body,
            headers={"Authorization": f"Token {s.deepgram_api_key}", "Content-Type": "audio/wav"},
            timeout=timeout,
        )
    )
    if r.status_code != 200:
        raise EngineError(f"deepgram {r.status_code}: {r.text[:300]}")
    return parse(r.json(), language)


def parse(data: dict, language: str = "en") -> Transcript:
    try:
        alt = data["results"]["channels"][0]["alternatives"][0]
    except (KeyError, IndexError) as e:
        raise EngineError(f"deepgram: unexpected payload ({e})") from e
    words = [
        TWord(w.get("word", ""), w.get("start"), w.get("end"), w.get("confidence"))
        for w in alt.get("words", [])
    ]
    return Transcript(
        "deepgram", alt.get("transcript", ""), words, language, alt.get("confidence"), data
    )
