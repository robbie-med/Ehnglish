"""Google Cloud Speech-to-Text v1 as an optional fourth voter (owner's Google project, service
account JSON). Sync recognition accepts ≤ 60 s inline, so longer takes are cut into ~50 s chunks at
the quietest point near the boundary and word offsets are shifted back. Word confidence and time
offsets are requested so the vote can use them like the other engines."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import numpy as np

from ..config import get_settings
from ..wav import read_samples, write_wav
from .base import EngineError, Transcript, TWord
from .http import request_with_retry

URL = "https://speech.googleapis.com/v1/speech:recognize"
CHUNK_S = 50.0
SEARCH_S = 5.0  # look for the quietest 300 ms within ±5 s of each boundary

_token_cache: dict[str, object] = {}


def _token() -> str:
    s = get_settings()
    if not s.google_credentials:
        raise EngineError("EHNGLISH_GOOGLE_CREDENTIALS not set")
    creds = _token_cache.get("creds")
    if creds is None:
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            s.google_credentials, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        _token_cache["creds"] = creds
    from google.auth.transport.requests import Request

    if not creds.valid:  # type: ignore[attr-defined]
        creds.refresh(Request())  # type: ignore[attr-defined]
    return creds.token  # type: ignore[attr-defined]


def _split_points(x: np.ndarray, sr: int) -> list[int]:
    """Sample indices where chunks start, choosing quiet spots near each 50 s boundary."""
    n = len(x)
    if n <= CHUNK_S * sr:
        return [0]
    win = max(1, int(0.3 * sr))
    energy = np.convolve(x.astype(np.float64) ** 2, np.ones(win) / win, mode="same")
    points = [0]
    pos = int(CHUNK_S * sr)
    while pos < n:
        lo = max(points[-1] + sr, int(pos - SEARCH_S * sr))
        hi = min(n - 1, int(pos + SEARCH_S * sr))
        cut = lo + int(np.argmin(energy[lo:hi])) if hi > lo else pos
        points.append(cut)
        pos = cut + int(CHUNK_S * sr)
    return points


def transcribe(path: Path, *, language: str = "en", timeout: float = 120) -> Transcript:
    token = _token()
    x, info = read_samples(path)
    mono = x[:, 0] if info.channels >= 1 else x.ravel()
    sr = info.sample_rate
    starts = _split_points(mono, sr)
    bounds = list(zip(starts, starts[1:] + [len(mono)], strict=False))
    words: list[TWord] = []
    texts: list[str] = []
    confs: list[float] = []
    raws: list[dict] = []
    import tempfile

    for a, b in bounds:
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            write_wav(Path(tmp.name), mono[a:b].astype(np.float32), sr)
            content = Path(tmp.name).read_bytes()
        body = {
            "config": {
                "encoding": "LINEAR16",
                "sampleRateHertz": sr,
                "languageCode": {"en": "en-US", "ko": "ko-KR"}.get(language, language),
                "model": "latest_long",
                "enableWordTimeOffsets": True,
                "enableWordConfidence": True,
                "enableAutomaticPunctuation": False,
                "profanityFilter": False,
            },
            "audio": {"content": base64.b64encode(content).decode()},
        }
        r = request_with_retry(
            lambda body=body: httpx.post(
                URL, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=timeout
            )
        )
        if r.status_code == 403 and "PERMISSION_DENIED" in r.text:
            # API not enabled on the project (or the service account lacks the role): skip, don't block
            raise EngineError(f"google not enabled: {r.text[:200]}")
        if r.status_code != 200:
            raise EngineError(f"google {r.status_code}: {r.text[:300]}")
        data = r.json()
        raws.append(data)
        part = parse(data, language, offset_s=a / sr)
        words.extend(part.words)
        if part.text:
            texts.append(part.text)
        if part.conf is not None:
            confs.append(part.conf)
    return Transcript(
        "google",
        " ".join(texts),
        words,
        language,
        sum(confs) / len(confs) if confs else None,
        {"chunks": raws},
    )


def _secs(s: str | None) -> float | None:
    if not s:
        return None
    return float(s.rstrip("s"))


def parse(data: dict, language: str = "en", offset_s: float = 0.0) -> Transcript:
    words: list[TWord] = []
    texts: list[str] = []
    confs: list[float] = []
    for res in data.get("results", []):
        alts = res.get("alternatives") or []
        if not alts:
            continue
        alt = alts[0]
        if alt.get("transcript"):
            texts.append(alt["transcript"].strip())
        if alt.get("confidence") is not None:
            confs.append(float(alt["confidence"]))
        for w in alt.get("words", []):
            st, en = _secs(w.get("startTime")), _secs(w.get("endTime"))
            words.append(
                TWord(
                    w.get("word", ""),
                    st + offset_s if st is not None else None,
                    en + offset_s if en is not None else None,
                    w.get("confidence"),
                )
            )
    return Transcript(
        "google", " ".join(texts), words, language, sum(confs) / len(confs) if confs else None, data
    )
