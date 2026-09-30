#!/usr/bin/env python3
"""Build fixed prompt audio for every form item that declares `audio:` (plan §4.5).

Text-to-speech through Azure neural voices (same key as the speech services). Files are generated
once, committed, and never regenerated unless you delete them, so every sitting hears identical
audio. Run from server/: `uv run python ../content/build_audio.py [--voice en-US-AndrewNeural]`.
Requires EHNGLISH_AZURE_SPEECH_KEY and _REGION in the environment (or server/.env).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "server"))
from app.config import get_settings  # noqa: E402
from app.content import load_forms  # noqa: E402

# US voices. Azure has no explicit Northeast-accent voice; these are the most neutral-Northern
# sounding of the standard set. Change here once and rebuild only the files you delete.
DEFAULT_VOICES = {"en": "en-US-AndrewNeural", "ko": "ko-KR-InJoonNeural"}


def tts(text: str, voice: str, *, rate: str = "0%") -> bytes:
    s = get_settings()
    if not s.azure_speech_key or not s.azure_speech_region:
        raise SystemExit("EHNGLISH_AZURE_SPEECH_KEY / EHNGLISH_AZURE_SPEECH_REGION not set")
    lang = voice[:5]
    ssml = (
        f'<speak version="1.0" xml:lang="{lang}"><voice name="{voice}">'
        f'<prosody rate="{rate}">{text}</prosody></voice></speak>'
    )
    r = httpx.post(
        f"https://{s.azure_speech_region}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={
            "Ocp-Apim-Subscription-Key": s.azure_speech_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
            "User-Agent": "ehnglish-build-audio",
        },
        content=ssml.encode("utf-8"),
        timeout=60,
    )
    if r.status_code != 200:
        raise SystemExit(f"TTS failed {r.status_code}: {r.text[:200]}")
    return r.content


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", help="override the English voice")
    ap.add_argument("--form", help="only this form id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    voices = dict(DEFAULT_VOICES)
    if args.voice:
        voices["en"] = args.voice
    forms = load_forms(ROOT)
    made = skipped = 0
    for form in forms.values():
        if args.form and form.id != args.form:
            continue
        for task in form.tasks:
            for item in task.items:
                if not item.audio or not item.text:
                    continue
                out = ROOT / item.audio
                if out.exists():
                    skipped += 1
                    continue
                lang = "ko" if item.target.get("language") == "ko" else "en"
                print(f"{form.id}/{task.id}/{item.id}: {item.text[:50]!r} -> {item.audio}")
                if args.dry_run:
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(tts(item.text, voices[lang]))
                made += 1
    print(f"built {made}, kept {skipped}")


if __name__ == "__main__":
    main()
