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
from app.content import AudioFx, load_forms  # noqa: E402
from app.pipeline import audiofx  # noqa: E402

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


def _concat(parts: list[bytes], gap_s: float, out: Path) -> None:
    """Join WAV renders with silence between them (all Azure renders share one format)."""
    import numpy as np

    from app.wav import read_samples, write_wav

    import tempfile

    chunks = []
    sr = None
    with tempfile.TemporaryDirectory() as td:
        for i, b in enumerate(parts):
            p = Path(td) / f"{i}.wav"
            p.write_bytes(b)
            x, info = read_samples(p)
            sr = info.sample_rate
            chunks.append(x[:, 0])
            chunks.append(np.zeros(int(gap_s * sr), dtype=np.float32))
    write_wav(out, np.concatenate(chunks[:-1]).astype(np.float32), sr or 24000)


def render(text: str, voice: str, fx: AudioFx, out: Path) -> None:
    """TTS (or a word sequence / dialogue), then effects in order: phone line → noise."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cur = Path(td) / "tts.wav"
        if fx.sequence:
            _concat([tts(w, voice, rate=fx.rate) for w in fx.sequence], fx.gap_s, cur)
        elif fx.dialogue:
            _concat([tts(turn["text"], turn.get("voice") or voice, rate=fx.rate) for turn in fx.dialogue], fx.gap_s, cur)
        else:
            cur.write_bytes(tts(text, voice, rate=fx.rate))
        if fx.phone:
            nxt = Path(td) / "phone.wav"
            audiofx.phone_line(cur, nxt)
            cur = nxt
        if fx.noise_snr_db is not None:
            nxt = Path(td) / "noise.wav"
            achieved = audiofx.add_noise(cur, nxt, snr_db=fx.noise_snr_db, kind=fx.noise_kind)
            print(f"    noise {fx.noise_kind} target {fx.noise_snr_db} dB, achieved {achieved} dB")
            cur = nxt
        out.write_bytes(cur.read_bytes())


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
            # Task-level stimulus built from target.tts (a dialogue/lecture script); sermon clips
            # come from content/import_sermon_clip.py instead and are never regenerated here.
            tts_spec = task.target.get("tts")
            if task.audio and tts_spec and not (ROOT / task.audio).exists():
                fx = AudioFx.model_validate(tts_spec)
                print(f"{form.id}/{task.id}: stimulus -> {task.audio}  fx={fx.model_dump(exclude_defaults=True)}")
                if not args.dry_run:
                    (ROOT / task.audio).parent.mkdir(parents=True, exist_ok=True)
                    render("", fx.voice or voices["en"], fx, ROOT / task.audio)
                    made += 1
            for item in task.items:
                if not item.audio or not (item.text or (item.fx and (item.fx.sequence or item.fx.dialogue))):
                    continue
                out = ROOT / item.audio
                if out.exists():
                    skipped += 1
                    continue
                lang = "ko" if item.target.get("language") == "ko" else "en"
                fx = item.fx or AudioFx()
                print(f"{form.id}/{task.id}/{item.id}: {(item.text or '')[:50]!r} -> {item.audio}  fx={fx.model_dump(exclude_defaults=True) or 'plain'}")
                if args.dry_run:
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                render(item.text or "", fx.voice or voices[lang], fx, out)
                made += 1
    print(f"built {made}, kept {skipped}")


if __name__ == "__main__":
    main()
