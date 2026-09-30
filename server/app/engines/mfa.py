"""Client for the Montreal Forced Aligner HTTP shim (server/mfa_service)."""

from __future__ import annotations

from pathlib import Path

import httpx

from ..config import get_settings
from .base import EngineError


def align(path: Path, transcript: str, *, timeout: float = 600) -> dict:
    """Returns {"words": [{"word","start","end"}], "phones": [{"phone","start","end"}], "unaligned": bool}."""
    s = get_settings()
    if not s.mfa_url:
        raise EngineError("EHNGLISH_MFA_URL not set")
    with path.open("rb") as f:
        r = httpx.post(
            s.mfa_url.rstrip("/") + "/align",
            files={"audio": (path.name, f, "audio/wav")},
            data={"text": transcript},
            timeout=timeout,
        )
    if r.status_code != 200:
        raise EngineError(f"mfa {r.status_code}: {r.text[:300]}")
    return r.json()
