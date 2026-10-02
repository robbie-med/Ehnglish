"""Audio effects for building prompt audio (plan §4.5): phone line, noise at a fixed SNR.

Deterministic: same input + spec → same output bytes (fixed noise seed), so every sitting hears
identical audio. ffmpeg does the G.711 codec round trip; numpy does the mixing.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from ..wav import read_samples, write_wav

NOISE_SEED = 20260930


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def phone_line(src: Path, dst: Path, *, hiss_dbfs: float = -45.0) -> None:
    """Telephone band-limit + μ-law 8 kHz round trip + faint line hiss, back to 16 kHz PCM."""
    if not have_ffmpeg():
        raise RuntimeError("ffmpeg is required for the phone-line effect")
    with tempfile.TemporaryDirectory() as td:
        ulaw = Path(td) / "line.wav"
        # Band-limit, resample to 8 kHz, encode G.711 μ-law (the real narrowband codec).
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-af",
                "highpass=f=300,lowpass=f=3400",
                "-ar",
                "8000",
                "-ac",
                "1",
                "-acodec",
                "pcm_mulaw",
                str(ulaw),
            ],
            check=True,
        )
        back = Path(td) / "back.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(ulaw),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-acodec",
                "pcm_s16le",
                str(back),
            ],
            check=True,
        )
        x, info = read_samples(back)
    mono = x[:, 0].astype(np.float32)
    rng = np.random.default_rng(NOISE_SEED)
    hiss = rng.normal(0, 1, mono.shape).astype(np.float32)
    # Line hiss lives in the phone band too: zero everything outside 300–3400 Hz.
    spec = np.fft.rfft(hiss)
    freqs = np.fft.rfftfreq(len(hiss), 1 / info.sample_rate)
    spec[(freqs < 300) | (freqs > 3400)] = 0
    hiss = np.fft.irfft(spec, len(hiss)).astype(np.float32)
    hiss *= 10 ** (hiss_dbfs / 20) / (np.sqrt(np.mean(hiss**2)) + 1e-9)
    write_wav(dst, np.clip(mono + hiss, -1, 1), info.sample_rate)


def pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """Voss-McCartney-ish pink noise via FFT shaping (1/f)."""
    white = rng.normal(0, 1, n)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n)
    freqs[0] = freqs[1] if n > 1 else 1.0
    spec /= np.sqrt(freqs)
    pink = np.fft.irfft(spec, n)
    return (pink / (np.std(pink) + 1e-9)).astype(np.float32)


def babble_noise(n: int, rng: np.random.Generator, sample_rate: int) -> np.ndarray:
    """Speech-shaped noise: pink noise with syllable-rate amplitude modulation from several
    'talkers'. Not real speech, but it masks like a cafeteria rather than like a fan."""
    base = pink_noise(n, rng)
    t = np.arange(n) / sample_rate
    env = np.zeros(n, dtype=np.float32)
    for _k in range(6):
        f = rng.uniform(3, 6)
        env += (0.5 + 0.5 * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi))) ** 2
    env /= env.max() + 1e-9
    out = base * (0.4 + 0.6 * env)
    return (out / (np.std(out) + 1e-9)).astype(np.float32)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


def add_noise(src: Path, dst: Path, *, snr_db: float, kind: str = "pink") -> float:
    """Mix noise at a fixed SNR relative to the speech RMS (speech measured over active frames).
    Returns the achieved SNR in dB. Noise starts 0.3 s before speech and runs to the end."""
    x, info = read_samples(src)
    speech = x[:, 0].astype(np.float32)
    # active-frame RMS: frames above the 20th percentile energy count as speech
    win = max(1, info.sample_rate // 50)
    frames = speech[: (len(speech) // win) * win].reshape(-1, win)
    fr = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    active = fr[fr > np.percentile(fr, 20)]
    s_rms = float(np.sqrt(np.mean(active**2))) if active.size else rms(speech)
    rng = np.random.default_rng(NOISE_SEED)
    pad = int(0.3 * info.sample_rate)
    n = len(speech) + pad
    noise = babble_noise(n, rng, info.sample_rate) if kind == "babble" else pink_noise(n, rng)
    noise *= s_rms / (10 ** (snr_db / 20)) / rms(noise)
    out = noise.copy()
    out[pad:] += speech
    peak = float(np.max(np.abs(out)))
    if peak > 0.99:
        out *= 0.99 / peak
    write_wav(dst, out, info.sample_rate)
    return round(20 * np.log10(s_rms / rms(noise)), 2)


def speed(src: Path, dst: Path, *, factor: float) -> None:
    """Tempo change without pitch change (ffmpeg atempo). Used when TTS rate control is not enough."""
    if not have_ffmpeg():
        raise RuntimeError("ffmpeg is required for the speed effect")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-af",
            f"atempo={factor}",
            "-acodec",
            "pcm_s16le",
            str(dst),
        ],
        check=True,
    )
