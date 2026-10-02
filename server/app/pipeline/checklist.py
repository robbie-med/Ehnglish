"""Phone-call scoring: goal checklist (Claude, 3 runs, majority per goal) and fixed-phrase use
(code, fuzzy match). Plan §4.2 C4 and §5.4."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from rapidfuzz import fuzz

from ..engines.claude import RUNS, structured
from .text import normalize

CHECKLIST_SYSTEM = (
    "You are scoring a learner's side of a scripted phone call with a clinic, pharmacy or office. "
    "You see the caller's scripted lines and the learner's transcribed replies, turn by turn. For "
    "each goal, decide strictly from the learner's words whether the learner accomplished it "
    "(asked for it, stated it, confirmed it). Vague or partial attempts count as not done. Quote "
    "the learner's words that support each decision. Words marked [uncertain] were not transcribed "
    "reliably; do not rely on them alone."
)


@dataclass
class ChecklistResult:
    goals: list[dict]  # {goal, done, votes, evidence}
    done: int
    total: int
    completion: float
    runs: int

    def to_dict(self) -> dict:
        return asdict(self)


def score_goals(goals: list[str], turns: list[dict], *, runs: int = RUNS) -> ChecklistResult:
    """turns: [{caller: str, learner: str}] in order. Majority across runs decides each goal."""
    schema = {
        "type": "object",
        "properties": {
            "goals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "done": {"type": "boolean"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["index", "done", "evidence"],
                },
            }
        },
        "required": ["goals"],
    }
    convo = "\n".join(
        f"Caller: {t.get('caller', '')}\nLearner: {t.get('learner', '') or '(no reply)'}"
        for t in turns
    )
    user = "Goals:\n" + "\n".join(f"{i}. {g}" for i, g in enumerate(goals)) + f"\n\nCall:\n{convo}"
    votes: list[Counter] = [Counter() for _ in goals]
    evidence: list[list[str]] = [[] for _ in goals]
    for _ in range(runs):
        r = structured(CHECKLIST_SYSTEM, user, schema, tool_name="checklist")
        for g in r.get("goals", []):
            i = int(g.get("index", -1))
            if 0 <= i < len(goals):
                votes[i][bool(g.get("done"))] += 1
                if g.get("evidence"):
                    evidence[i].append(str(g["evidence"]))
    out = []
    done = 0
    for i, g in enumerate(goals):
        yes = votes[i][True]
        is_done = yes * 2 > runs
        done += int(is_done)
        out.append({"goal": g, "done": is_done, "votes": yes, "evidence": evidence[i][:3]})
    return ChecklistResult(
        out, done, len(goals), round(done / len(goals), 3) if goals else 0.0, runs
    )


def phrase_use(phrases: list[str], transcript: str, *, threshold: int = 85) -> dict:
    """Which of the target fixed phrases appear (fuzzy, order-free) in the learner's speech."""
    text = " ".join(normalize(transcript))
    found = []
    for p in phrases:
        pn = " ".join(normalize(p))
        score = fuzz.partial_ratio(pn, text) if pn and text else 0
        found.append({"phrase": p, "used": score >= threshold, "score": score})
    return {"phrases": found, "used": sum(1 for f in found if f["used"]), "total": len(phrases)}
