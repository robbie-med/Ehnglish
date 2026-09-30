"""CPU phoneme recognizer: wav2vec2 fine-tuned to IPA (bookbot/wav2vec2-ljspeech-gruut, English).
Optional dependency group `phonemes` (torch CPU + transformers). Model weights are cached in
HF_HOME (a Docker volume in production) on first use."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from ..config import get_settings
from ..wav import read_samples
from .base import EngineError

MODEL_ID = "bookbot/wav2vec2-ljspeech-gruut"


@lru_cache
def _model():
    try:
        import torch
        from transformers import AutoProcessor, Wav2Vec2ForCTC
    except ImportError as e:  # pragma: no cover
        raise EngineError("phoneme model not installed (uv sync --extra phonemes)") from e
    torch.set_num_threads(max(1, get_settings().phoneme_threads))
    proc = AutoProcessor.from_pretrained(MODEL_ID)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL_ID).eval()
    return proc, model, torch


def _to_16k(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == 16000:
        return x
    n = int(round(len(x) * 16000 / sr))
    idx = np.linspace(0, len(x) - 1, n)
    return np.interp(idx, np.arange(len(x)), x).astype(np.float32)


def recognize(path: Path) -> str:
    """Space-separated IPA phones for the whole file (chunked to bound memory)."""
    if not get_settings().phonemes_enabled:
        raise EngineError("EHNGLISH_PHONEMES_ENABLED not set")
    proc, model, torch = _model()
    x, info = read_samples(path)
    mono = x.mean(axis=1) if info.channels > 1 else x[:, 0]
    mono = _to_16k(mono.astype(np.float32), info.sample_rate)
    chunk = 16000 * 20
    out: list[str] = []
    with torch.no_grad():
        for s in range(0, len(mono), chunk):
            seg = mono[s : s + chunk]
            if len(seg) < 1600:
                continue
            inputs = proc(seg, sampling_rate=16000, return_tensors="pt")
            logits = model(**inputs).logits
            ids = torch.argmax(logits, dim=-1)
            out.append(proc.batch_decode(ids)[0])
    return " ".join(t for t in out if t)
