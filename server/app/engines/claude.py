"""Claude judgment tasks (plan §2.3): structured output via a forced tool call, run three times,
median kept and the spread recorded. Code computes every number from what Claude returns."""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass
from typing import Any

from rapidfuzz.distance import Levenshtein

from ..config import get_settings
from .base import EngineError

RUNS = 3


def _client():
    import anthropic

    s = get_settings()
    if not s.anthropic_api_key:
        raise EngineError("EHNGLISH_ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=s.anthropic_api_key)


def structured(system: str, user: str, schema: dict, *, tool_name: str = "answer") -> dict:
    """One call that must return JSON matching `schema`. The model is asked to call the tool
    (forced tool_choice is not supported on claude-opus-5-5); if it answers in text instead, the
    text is parsed as JSON."""
    client = _client()
    s = get_settings()
    msg = client.messages.create(
        model=s.claude_model,
        max_tokens=4096,
        system=system
        + f"\n\nAlways respond by calling the `{tool_name}` tool with the result; never answer in prose.",
        tools=[{"name": tool_name, "description": "Return the result.", "input_schema": schema}],
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": user}],
    )
    text_parts: list[str] = []
    for block in msg.content:
        if block.type == "tool_use" and block.name == tool_name:
            return dict(block.input)
        if block.type == "text":
            text_parts.append(block.text)
    text = "\n".join(text_parts).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise EngineError(f"claude returned no tool call and no JSON: {text[:200]!r}")


@dataclass
class Correction:
    corrected: str
    runs: list[str]
    edit_distances: list[int]
    spread: int  # max - min edit distance across runs

    def to_dict(self) -> dict[str, Any]:
        return {
            "corrected": self.corrected,
            "runs": self.runs,
            "edit_distances": self.edit_distances,
            "spread": self.spread,
        }


MINIMAL_CORRECTION_SYSTEM = (
    "You are a careful copy editor for spoken-English transcripts from a second-language learner. "
    "Produce the MINIMAL grammatical correction: fix only genuine grammar, word-form, article, "
    "preposition, agreement, tense and word-choice errors. Keep the speaker's words, order, "
    "meaning, register and sentence boundaries wherever they are acceptable. Do not add content, "
    "do not improve style, do not remove fillers or repetitions unless they make the sentence "
    "ungrammatical. The text has no punctuation; add only sentence-final periods where clauses "
    "clearly end. Text marked [uncertain] was not transcribed reliably: leave those words exactly as they are."
)


def minimal_correction(text: str, *, runs: int = RUNS) -> Correction:
    """Three independent corrections; keep the one with the median edit distance from the source."""
    schema = {
        "type": "object",
        "properties": {"corrected": {"type": "string"}},
        "required": ["corrected"],
    }
    outs: list[str] = []
    for _ in range(runs):
        r = structured(
            MINIMAL_CORRECTION_SYSTEM, f"Transcript:\n{text}", schema, tool_name="correction"
        )
        outs.append(str(r.get("corrected", "")).strip())
    dists = [Levenshtein.distance(text.split(), o.split()) for o in outs]
    med = statistics.median_low(dists)
    chosen = outs[dists.index(med)]
    return Correction(chosen, outs, dists, max(dists) - min(dists))


def median_of_runs(values: list[float]) -> tuple[float, float]:
    """(median, spread) for numeric judgments scored several times."""
    return statistics.median(values), max(values) - min(values)
