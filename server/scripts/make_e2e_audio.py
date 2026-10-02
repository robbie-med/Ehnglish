"""Synthetic prompt audio for the e2e-core form (1 s tone bursts, 16 kHz). Committed once; real
forms get their audio from content/build_audio.py (Azure TTS)."""

from pathlib import Path

import numpy as np

from app.wav import write_wav

root = Path(__file__).resolve().parents[2] / "content" / "audio" / "e2e-core"
root.mkdir(parents=True, exist_ok=True)
sr = 16000
for name, freq in {"C2-01": 330.0, "C3-01": 440.0, "C4-01": 392.0, "C6-01": 523.0}.items():
    t = np.arange(int(1.0 * sr)) / sr
    env = np.minimum(1, np.minimum(t / 0.05, (1.0 - t) / 0.05))
    x = 0.3 * env * np.sin(2 * np.pi * freq * t)
    write_wav(root / f"{name}.wav", x.astype(np.float32), sr)
    print("wrote", root / f"{name}.wav")
