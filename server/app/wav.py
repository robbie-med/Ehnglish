"""Minimal RIFF/WAVE parsing and probing. 16-bit PCM only; that is what the recorder produces."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np


class WavError(ValueError):
    pass


@dataclass(frozen=True)
class WavInfo:
    sample_rate: int
    channels: int
    bits_per_sample: int
    data_offset: int
    data_bytes: int

    @property
    def frames(self) -> int:
        return self.data_bytes // (self.channels * self.bits_per_sample // 8)

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate


def parse_header(buf: bytes) -> WavInfo:
    """Parse the header from the first bytes of a file (>= 44 bytes, more if extra chunks)."""
    if len(buf) < 12 or buf[0:4] != b"RIFF" or buf[8:12] != b"WAVE":
        raise WavError("not a RIFF/WAVE file")
    pos = 12
    fmt = None
    while pos + 8 <= len(buf):
        cid = buf[pos : pos + 4]
        (csize,) = struct.unpack("<I", buf[pos + 4 : pos + 8])
        body = pos + 8
        if cid == b"fmt ":
            if csize < 16 or body + 16 > len(buf):
                raise WavError("bad fmt chunk")
            audio_format, channels, sample_rate, _, _, bits = struct.unpack(
                "<HHIIHH", buf[body : body + 16]
            )
            if audio_format != 1:
                raise WavError(f"unsupported format {audio_format}; need PCM (1)")
            fmt = (channels, sample_rate, bits)
        elif cid == b"data":
            if fmt is None:
                raise WavError("data chunk before fmt chunk")
            channels, sample_rate, bits = fmt
            if bits != 16:
                raise WavError(f"unsupported bit depth {bits}; need 16")
            if channels < 1 or sample_rate < 8000:
                raise WavError("implausible channel count or sample rate")
            return WavInfo(sample_rate, channels, bits, body, csize)
        pos = body + csize + (csize & 1)
    raise WavError("no data chunk found")


def read_info(path: Path) -> WavInfo:
    with path.open("rb") as f:
        head = f.read(4096)
    info = parse_header(head)
    actual = path.stat().st_size - info.data_offset
    if actual < info.data_bytes:
        raise WavError(f"data chunk claims {info.data_bytes} bytes, file has {actual}")
    return info


def read_samples(path: Path) -> tuple[np.ndarray, WavInfo]:
    """Return float32 samples in [-1, 1], shape (frames, channels)."""
    info = read_info(path)
    with path.open("rb") as f:
        f.seek(info.data_offset)
        raw = f.read(info.data_bytes)
    pcm = np.frombuffer(raw, dtype="<i2").reshape(-1, info.channels)
    return pcm.astype(np.float32) / 32768.0, info


def probe(path: Path) -> dict:
    """Level statistics for the whole file. Cheap; used by the stub job in M0 and as a QC input later."""
    x, info = read_samples(path)
    mono = x.mean(axis=1) if info.channels > 1 else x[:, 0]
    n = int(mono.shape[0])
    if n == 0:
        return {
            "frames": 0,
            "duration_s": 0.0,
            "peak_dbfs": None,
            "rms_dbfs": None,
            "clip_count": 0,
        }
    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
    clip = int(np.count_nonzero(np.abs(mono) >= 0.999))
    # Noise floor estimate: 5th percentile of RMS over 50 ms windows.
    win = max(1, info.sample_rate // 20)
    usable = (n // win) * win
    if usable >= win:
        frames = mono[:usable].reshape(-1, win).astype(np.float64)
        win_rms = np.sqrt(np.mean(frames**2, axis=1))
        floor = float(np.percentile(win_rms, 5))
    else:
        floor = rms

    def dbfs(v: float) -> float | None:
        return None if v <= 0 else round(20 * np.log10(v), 2)

    return {
        "frames": n,
        "duration_s": round(n / info.sample_rate, 4),
        "sample_rate": info.sample_rate,
        "channels": info.channels,
        "peak_dbfs": dbfs(peak),
        "rms_dbfs": dbfs(rms),
        "noise_floor_dbfs": dbfs(floor),
        "snr_db": None if rms <= 0 or floor <= 0 else round(20 * np.log10(rms / floor), 2),
        "clip_count": clip,
        "clip_ratio": round(clip / n, 6),
    }


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    """Helper for tests and fixtures: float [-1,1] mono -> 16-bit PCM WAV."""
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2").tobytes()
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(pcm))
    path.write_bytes(header + pcm)
