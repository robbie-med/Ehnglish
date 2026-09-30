"""Generate a speech-like WAV for Chromium's fake audio capture (Playwright smoke test).

Harmonics of a 150 Hz voice with a 4 Hz syllable envelope at about -20 dBFS, 6 s, 48 kHz mono.
No energy near 1 kHz on purpose? Not required: with a fake device the headphone tone is never
captured, so the leak check compares two near-identical windows and passes.
"""

from pathlib import Path

import numpy as np

from app.wav import write_wav

sr = 48000
t = np.arange(6 * sr) / sr
f0 = 150.0
voice = sum((1 / k) * np.sin(2 * np.pi * f0 * k * t + k) for k in range(1, 7))
envelope = 0.55 + 0.45 * np.sin(2 * np.pi * 4 * t) ** 2
x = voice / np.max(np.abs(voice)) * envelope * 0.1  # ≈ -20 dBFS peak
rng = np.random.default_rng(0)
x += rng.normal(0, 0.0005, x.shape)
out = Path(__file__).resolve().parents[2] / "web" / "e2e" / "fixtures" / "speech.wav"
out.parent.mkdir(parents=True, exist_ok=True)
write_wav(out, x.astype(np.float32), sr)
print("wrote", out, out.stat().st_size, "bytes")
