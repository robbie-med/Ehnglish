"""Keystroke measures (plan §4.3 R4, §4.4): typing speed from the keystroke log, bursts, pauses,
revisions, and copy-typing accuracy. Works for English and Korean (characters, not words)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from rapidfuzz.distance import Levenshtein

PAUSE_MS = 2000  # a pause ≥2 s separates typing bursts (Wengelin et al. convention)


@dataclass
class TypingReport:
    chars: int
    keystrokes: int
    duration_s: float | None  # first input → last input
    chars_per_min: float | None
    words_per_min: float | None  # chars/5, the usual convention
    bursts: int
    mean_burst_chars: float | None
    pauses: int
    pause_time_s: float
    backspaces: int
    revision_ratio: float | None  # backspaces / chars typed
    accuracy: float | None  # copy typing only: 1 - CER vs the reference

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(keystrokes: list[dict], final_text: str, reference: str | None = None) -> TypingReport:
    downs = [k for k in keystrokes if k.get("type") == "down"]
    inputs = [k for k in keystrokes if k.get("type") == "input"]
    chars = len(final_text)
    backspaces = sum(1 for k in downs if k.get("key") in ("Backspace", "Delete"))
    t0 = inputs[0]["t"] if inputs else None
    t1 = inputs[-1]["t"] if inputs else None
    duration = (t1 - t0) / 1000 if t0 is not None and t1 is not None and t1 > t0 else None
    # bursts: input events separated by < PAUSE_MS
    bursts: list[int] = []
    pauses = 0
    pause_time = 0.0
    last_t = None
    last_len = 0
    cur = 0
    for k in inputs:
        if last_t is not None and k["t"] - last_t >= PAUSE_MS:
            pauses += 1
            pause_time += (k["t"] - last_t) / 1000
            bursts.append(cur)
            cur = 0
        delta = max(0, (k.get("len") or 0) - last_len)
        cur += delta
        last_len = k.get("len") or last_len
        last_t = k["t"]
    if cur or not bursts:
        bursts.append(cur)
    bursts = [b for b in bursts if b > 0]
    accuracy = None
    if reference is not None:
        ref = " ".join(reference.split())
        typed = " ".join(final_text.split())
        cer = Levenshtein.distance(ref, typed) / max(1, len(ref))
        accuracy = round(max(0.0, 1 - cer), 4)
    return TypingReport(
        chars=chars,
        keystrokes=len(downs),
        duration_s=round(duration, 2) if duration else None,
        chars_per_min=round(60 * chars / duration, 1) if duration else None,
        words_per_min=round(60 * chars / 5 / duration, 1) if duration else None,
        bursts=len(bursts),
        mean_burst_chars=round(sum(bursts) / len(bursts), 1) if bursts else None,
        pauses=pauses,
        pause_time_s=round(pause_time, 2),
        backspaces=backspaces,
        revision_ratio=round(backspaces / chars, 3) if chars else None,
        accuracy=accuracy,
    )
