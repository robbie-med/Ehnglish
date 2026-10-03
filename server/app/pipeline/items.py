"""Scoring for item-based tasks (plan §4.3): multiple choice (vocabulary by band, comprehension),
C-test blanks, reading speed, AXB discrimination. Pure functions plus session-level rollups."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .text import normalize

BLANK = re.compile(r"\{([^{}]+)\}")


# ------------------------------------------------------------------ multiple choice
def score_mc(answer: str | None, correct: int, options: list[str]) -> dict:
    try:
        idx = int(answer) if answer not in (None, "") else None
    except ValueError:
        idx = None
    return {
        "answer": idx,
        "correct_index": correct,
        "correct": idx == correct if idx is not None else None,
        "chosen": options[idx] if idx is not None and 0 <= idx < len(options) else None,
    }


def vocabulary_summary(results: list[dict]) -> dict:
    """results: [{band: '1k'|..|'medical', correct: bool|None}]. Size estimate follows the VST
    logic: each 1k band contributes (proportion correct × 1000) word families."""
    by: dict[str, dict] = {}
    for r in results:
        b = str(r.get("band", "?"))
        d = by.setdefault(b, {"n": 0, "correct": 0})
        d["n"] += 1
        d["correct"] += 1 if r.get("correct") else 0
    for d in by.values():
        d["pct"] = round(100 * d["correct"] / d["n"], 1) if d["n"] else None
    size = 0.0
    freq_bands = [b for b in by if b.endswith("k") and b[:-1].isdigit()]
    for b in freq_bands:
        size += 1000 * by[b]["correct"] / by[b]["n"]
    return {
        "by_band": by,
        "size_estimate": int(round(size)) if freq_bands else None,
        "bands_tested": sorted(freq_bands, key=lambda x: int(x[:-1])),
        "medical_pct": by.get("medical", {}).get("pct"),
    }


def comprehension_summary(results: list[dict]) -> dict:
    n = len(results)
    c = sum(1 for r in results if r.get("correct"))
    return {"n": n, "correct": c, "pct": round(100 * c / n, 1) if n else None}


# ------------------------------------------------------------------ C-test
def ctest_blanks(text: str) -> list[str]:
    """Solutions in order, from {solution} markers."""
    return BLANK.findall(text)


def render_ctest(text: str) -> str:
    """Replace each {solution} with a blank marker the client fills (keeps surrounding letters)."""
    return BLANK.sub("____", text)


def score_ctest(text: str, answers: list[str]) -> dict:
    sols = ctest_blanks(text)
    per = []
    correct = 0
    for i, sol in enumerate(sols):
        a = answers[i].strip().lower() if i < len(answers) else ""
        ok = a == sol.strip().lower()
        correct += int(ok)
        per.append({"solution": sol, "answer": a or None, "correct": ok})
    return {
        "n": len(sols),
        "correct": correct,
        "pct": round(100 * correct / len(sols), 1) if sols else None,
        "blanks": per,
    }


# ------------------------------------------------------------------ reading
@dataclass
class ReadingReport:
    words: int
    reading_time_s: float | None
    wpm: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def reading_speed(passage: str, shown_ms: float | None, done_ms: float | None) -> ReadingReport:
    words = len(normalize(passage))
    secs = (
        (done_ms - shown_ms) / 1000
        if shown_ms is not None and done_ms is not None and done_ms > shown_ms
        else None
    )
    return ReadingReport(
        words, round(secs, 2) if secs else None, round(60 * words / secs, 1) if secs else None
    )


def effective_reading_speed(wpm: float | None, comprehension_pct: float | None) -> float | None:
    if wpm is None or comprehension_pct is None:
        return None
    return round(wpm * comprehension_pct / 100, 1)


# ------------------------------------------------------------------ AXB
def score_axb(answer: str | None, correct: str, contrast: str | None) -> dict:
    a = (answer or "").strip().upper() or None
    return {
        "answer": a,
        "correct_answer": correct,
        "correct": a == correct if a else None,
        "contrast": contrast,
    }


def axb_summary(results: list[dict]) -> dict:
    by: dict[str, dict] = {}
    for r in results:
        c = str(r.get("contrast") or "other")
        d = by.setdefault(c, {"n": 0, "correct": 0})
        d["n"] += 1
        d["correct"] += 1 if r.get("correct") else 0
    for d in by.values():
        d["pct"] = round(100 * d["correct"] / d["n"], 1) if d["n"] else None
    n = sum(d["n"] for d in by.values())
    c = sum(d["correct"] for d in by.values())
    return {"n": n, "correct": c, "pct": round(100 * c / n, 1) if n else None, "by_contrast": by}
