"""Acoustic timing via Praat (parselmouth): syllable nuclei (De Jong & Wempe 2009 style), pauses,
speech and articulation rate, mean length of run, voice onset (for response latency), pitch and
intensity summaries. Everything is transcript-independent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import parselmouth

PAUSE_MIN_S = 0.25  # plan §5.4: pauses ≥250 ms


@dataclass
class Nucleus:
    t: float
    db: float


@dataclass
class Pause:
    start: float
    end: float

    @property
    def dur(self) -> float:
        return self.end - self.start


@dataclass
class TimingReport:
    duration_s: float
    speaking_time_s: float  # duration minus pauses ≥250 ms
    n_syllables: int
    n_pauses: int
    pause_time_s: float
    mean_pause_s: float | None
    pauses_per_min: float
    speech_rate_syl_per_s: float  # syllables / total duration
    articulation_rate_syl_per_s: float  # syllables / speaking time
    mean_length_of_run_syl: float | None  # syllables between pauses
    onset_s: float | None  # first voiced/loud frame — response latency when timed from record start
    pitch_median_hz: float | None
    pitch_iqr_hz: float | None
    intensity_mean_db: float | None
    nuclei: list[float]
    pauses: list[tuple[float, float]]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["nuclei"] = [round(x, 3) for x in self.nuclei]
        d["pauses"] = [(round(a, 3), round(b, 3)) for a, b in self.pauses]
        return d


def load(path: Path) -> parselmouth.Sound:
    snd = parselmouth.Sound(str(path))
    if snd.n_channels > 1:
        snd = snd.convert_to_mono()
    return snd


def syllable_nuclei(
    snd: parselmouth.Sound, *, silence_db: float = -25.0, min_dip_db: float = 2.0
) -> tuple[list[Nucleus], float]:
    """Intensity peaks that are voiced and separated by a dip. Returns (nuclei, threshold_db)."""
    intensity = snd.to_intensity(minimum_pitch=50, time_step=0.01)
    values = intensity.values[0]
    times = intensity.xs()
    if values.size == 0:
        return [], 0.0
    max_db = float(np.max(values))
    threshold = max_db + silence_db  # silence_db is relative to the loudest point
    threshold = max(threshold, float(np.percentile(values, 5)) + 3)
    pitch = snd.to_pitch(time_step=0.01, pitch_floor=75, pitch_ceiling=500)
    nuclei: list[Nucleus] = []
    # candidate peaks
    for i in range(1, len(values) - 1):
        if values[i] > values[i - 1] and values[i] >= values[i + 1] and values[i] > threshold:
            # dip before this peak (back to the previous nucleus or start)
            j = i - 1
            min_between = values[i]
            while j > 0 and not (
                values[j] > values[j - 1] and values[j] >= values[j + 1] and values[j] > threshold
            ):
                min_between = min(min_between, values[j])
                j -= 1
            prev_peak = values[j] if j > 0 else values[i]
            if (
                nuclei
                and values[i] - min_between < min_dip_db
                and prev_peak - min_between < min_dip_db
            ):
                continue
            f0 = pitch.get_value_at_time(times[i])
            if f0 is None or np.isnan(f0):
                continue
            nuclei.append(Nucleus(float(times[i]), float(values[i])))
    return nuclei, threshold


def pauses(
    snd: parselmouth.Sound, threshold_db: float, *, min_pause_s: float = PAUSE_MIN_S
) -> list[Pause]:
    intensity = snd.to_intensity(minimum_pitch=50, time_step=0.01)
    values = intensity.values[0]
    times = intensity.xs()
    out: list[Pause] = []
    start: float | None = None
    for t, v in zip(times, values, strict=False):
        if v < threshold_db:
            if start is None:
                start = float(t)
        elif start is not None:
            if t - start >= min_pause_s:
                out.append(Pause(start, float(t)))
            start = None
    if start is not None and times[-1] - start >= min_pause_s:
        out.append(Pause(start, float(times[-1])))
    return out


def analyze(path: Path, *, trim_edges: bool = True) -> TimingReport:
    snd = load(path)
    dur = snd.get_total_duration()
    nuc, thr = syllable_nuclei(snd)
    ps = pauses(snd, thr)
    # Leading/trailing silence is latency / trailing room, not a mid-speech pause.
    onset = nuc[0].t if nuc else None
    offset = nuc[-1].t if nuc else None
    inner = (
        [
            p
            for p in ps
            if onset is not None
            and offset is not None
            and p.start > onset - 0.05
            and p.end < offset + 0.05
        ]
        if trim_edges
        else ps
    )
    pause_time = sum(p.dur for p in inner)
    speaking = (
        max(1e-6, (offset - onset) - pause_time)
        if onset is not None and offset is not None
        else 1e-6
    )
    n = len(nuc)
    # runs between pauses
    runs: list[int] = []
    if nuc:
        count = 0
        pi = 0
        inner_sorted = sorted(inner, key=lambda p: p.start)
        for x in nuc:
            while pi < len(inner_sorted) and inner_sorted[pi].end <= x.t:
                if count:
                    runs.append(count)
                count = 0
                pi += 1
            count += 1
        if count:
            runs.append(count)
    pitch = snd.to_pitch(time_step=0.01, pitch_floor=75, pitch_ceiling=500)
    f0 = pitch.selected_array["frequency"]
    f0 = f0[(f0 > 0) & ~np.isnan(f0)]
    intensity = snd.to_intensity(minimum_pitch=50, time_step=0.01).values[0]
    voiced_int = intensity[intensity > thr] if intensity.size else intensity
    return TimingReport(
        duration_s=round(dur, 3),
        speaking_time_s=round(speaking, 3),
        n_syllables=n,
        n_pauses=len(inner),
        pause_time_s=round(pause_time, 3),
        mean_pause_s=round(pause_time / len(inner), 3) if inner else None,
        pauses_per_min=round(60 * len(inner) / max(dur, 1e-6), 2),
        speech_rate_syl_per_s=round(n / max(dur, 1e-6), 3),
        articulation_rate_syl_per_s=round(n / speaking, 3) if n else 0.0,
        mean_length_of_run_syl=round(float(np.mean(runs)), 2) if runs else None,
        onset_s=round(onset, 3) if onset is not None else None,
        pitch_median_hz=round(float(np.median(f0)), 1) if f0.size else None,
        pitch_iqr_hz=round(float(np.percentile(f0, 75) - np.percentile(f0, 25)), 1)
        if f0.size
        else None,
        intensity_mean_db=round(float(np.mean(voiced_int)), 1) if voiced_int.size else None,
        nuclei=[x.t for x in nuc],
        pauses=[(p.start, p.end) for p in inner],
    )
