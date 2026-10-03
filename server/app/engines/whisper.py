"""Hosted Whisper large-v3 through any OpenAI-compatible audio endpoint (Groq or OpenAI)."""

from __future__ import annotations

from pathlib import Path

import httpx

from ..config import get_settings
from .base import EngineError, Transcript, TWord
from .http import request_with_retry


def transcribe(path: Path, *, language: str = "en", timeout: float = 180) -> Transcript:
    s = get_settings()
    if not s.whisper_api_key:
        raise EngineError("EHNGLISH_WHISPER_API_KEY not set")
    url = s.whisper_base_url.rstrip("/") + "/audio/transcriptions"

    def _post() -> httpx.Response:
        with path.open("rb") as f:
            return httpx.post(
                url,
                headers={"Authorization": f"Bearer {s.whisper_api_key}"},
                data={
                    "model": s.whisper_model,
                    "language": language,
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "word",
                    "temperature": "0",
                },
                files={"file": (path.name, f, "audio/wav")},
                timeout=timeout,
            )

    r = request_with_retry(_post)
    if r.status_code != 200:
        raise EngineError(f"whisper {r.status_code}: {r.text[:300]}")
    return parse(r.json(), language)


def parse(data: dict, language: str = "en") -> Transcript:
    words = [
        TWord(w.get("word", "").strip(), w.get("start"), w.get("end"), None)
        for w in data.get("words", [])
    ]
    if not words and data.get("segments"):
        for seg in data["segments"]:
            for w in seg.get("words", []):
                words.append(
                    TWord(
                        w.get("word", "").strip(),
                        w.get("start"),
                        w.get("end"),
                        w.get("probability"),
                    )
                )
    return Transcript("whisper", data.get("text", "").strip(), words, language, None, data)
