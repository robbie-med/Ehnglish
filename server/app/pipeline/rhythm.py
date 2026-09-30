"""Rhythm metrics from a phone-level alignment (plan §5.3): %V, ΔC, nPVI-V, rPVI-C.

Input is the MFA phone tier: [(phone, start, end)]. Vowels are ARPAbet phones with a vowel
nucleus; silences/pauses are excluded. Adjacent same-class phones merge into one interval.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

ARPA_VOWELS = {
    "AA",
    "AE",
    "AH",
    "AO",
    "AW",
    "AY",
    "EH",
    "ER",
    "EY",
    "IH",
    "IY",
    "OW",
    "OY",
    "UH",
    "UW",
}
SILENCE = {"", "sil", "sp", "spn", "<eps>", "SIL", "SP"}


@dataclass
class RhythmReport:
    n_vocalic: int
    n_consonantal: int
    percent_v: float | None
    delta_c_ms: float | None
    delta_v_ms: float | None
    npvi_v: float | None
    rpvi_c_ms: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def _is_vowel(ph: str) -> bool:
    base = "".join(c for c in ph.upper() if c.isalpha())
    return base in ARPA_VOWELS


def intervals(phones: list[tuple[str, float, float]]) -> tuple[list[float], list[float]]:
    """Merge consecutive phones of the same class; return (vocalic durations, consonantal durations)."""
    v: list[float] = []
    c: list[float] = []
    cur_class: str | None = None
    cur_dur = 0.0
    for ph, start, end in phones:
        if ph in SILENCE:
            if cur_class == "V":
                v.append(cur_dur)
            elif cur_class == "C":
                c.append(cur_dur)
            cur_class, cur_dur = None, 0.0
            continue
        cls = "V" if _is_vowel(ph) else "C"
        if cls == cur_class:
            cur_dur += end - start
        else:
            if cur_class == "V":
                v.append(cur_dur)
            elif cur_class == "C":
                c.append(cur_dur)
            cur_class, cur_dur = cls, end - start
    if cur_class == "V":
        v.append(cur_dur)
    elif cur_class == "C":
        c.append(cur_dur)
    return v, c


def npvi(durs: list[float]) -> float | None:
    if len(durs) < 2:
        return None
    d = np.asarray(durs)
    pairs = np.abs(d[1:] - d[:-1]) / ((d[1:] + d[:-1]) / 2)
    return float(100 * np.mean(pairs))


def rpvi(durs: list[float]) -> float | None:
    if len(durs) < 2:
        return None
    d = np.asarray(durs)
    return float(1000 * np.mean(np.abs(d[1:] - d[:-1])))


def analyze(phones: list[tuple[str, float, float]]) -> RhythmReport:
    v, c = intervals(phones)
    total = sum(v) + sum(c)
    return RhythmReport(
        n_vocalic=len(v),
        n_consonantal=len(c),
        percent_v=round(100 * sum(v) / total, 2) if total else None,
        delta_c_ms=round(1000 * float(np.std(c)), 2) if len(c) > 1 else None,
        delta_v_ms=round(1000 * float(np.std(v)), 2) if len(v) > 1 else None,
        npvi_v=round(npvi(v), 2) if npvi(v) is not None else None,
        rpvi_c_ms=round(rpvi(c), 2) if rpvi(c) is not None else None,
    )
