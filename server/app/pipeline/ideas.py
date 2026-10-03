"""Idea units (plan §5.4 'Ideas'): Claude lists the idea units in a transcript; for a paired
Korean → English retelling it then judges which Korean units the English version conveys. Code
computes the coverage (the expression gap). Three runs each; the run with the median count wins."""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass

from ..engines.claude import RUNS, structured

EXTRACT_SYSTEM = (
    "You segment a spoken transcript into idea units: each distinct proposition, event, claim or "
    "detail the speaker expresses, one short clause each, in the transcript's own language. Keep "
    "the speaker's order. Do not add, merge or interpret; repetitions of the same idea count once. "
    "Words marked [uncertain] were not transcribed reliably: ignore them unless the idea is clear."
)
COVER_SYSTEM = (
    "You compare two versions of the same talk: the source (in Korean) and a retelling (in English). "
    "For each source idea unit decide whether the retelling conveys it (same proposition, even in "
    "simpler words). Judge strictly: partial or vague coverage is 'not covered'. Also list retelling "
    "ideas that have no source counterpart."
)


@dataclass
class IdeaUnits:
    units: list[str]
    runs: list[int]  # unit counts per run
    spread: int

    def to_dict(self) -> dict:
        return asdict(self)


def extract(transcript: str, language: str = "en", *, runs: int = RUNS) -> IdeaUnits:
    schema = {
        "type": "object",
        "properties": {"units": {"type": "array", "items": {"type": "string"}}},
        "required": ["units"],
    }
    outs: list[list[str]] = []
    for _ in range(runs):
        r = structured(
            EXTRACT_SYSTEM,
            f"Language: {language}\nTranscript:\n{transcript}",
            schema,
            tool_name="idea_units",
        )
        outs.append([str(u) for u in r.get("units", [])])
    counts = [len(o) for o in outs]
    med = statistics.median_low(counts)
    return IdeaUnits(outs[counts.index(med)], counts, max(counts) - min(counts))


@dataclass
class Coverage:
    source_units: int
    covered: int
    coverage: float  # covered / source
    covered_flags: list[bool]
    extra_in_retelling: list[str]
    runs: int

    def to_dict(self) -> dict:
        return asdict(self)


def coverage(source_units: list[str], retelling: str, *, runs: int = RUNS) -> Coverage:
    """Majority vote per source unit across runs."""
    schema = {
        "type": "object",
        "properties": {
            "covered": {"type": "array", "items": {"type": "boolean"}},
            "extra": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["covered", "extra"],
    }
    user = (
        "Source idea units:\n"
        + "\n".join(f"{i}. {u}" for i, u in enumerate(source_units))
        + f"\n\nRetelling:\n{retelling}"
    )
    votes = [0] * len(source_units)
    extras: list[str] = []
    for _ in range(runs):
        r = structured(COVER_SYSTEM, user, schema, tool_name="coverage")
        flags = list(r.get("covered", []))
        for i in range(min(len(flags), len(votes))):
            votes[i] += 1 if flags[i] else 0
        extras = [str(e) for e in r.get("extra", [])] or extras
    covered_flags = [v * 2 > runs for v in votes]
    n = len(source_units)
    c = sum(covered_flags)
    return Coverage(n, c, round(c / n, 3) if n else 0.0, covered_flags, extras, runs)
