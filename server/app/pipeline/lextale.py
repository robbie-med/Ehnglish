"""LexTALE (Lemhöfer & Broersma, 2012): 60 trials (40 words, 20 nonwords), unspeeded yes/no.
Score = average of % correct on words and % correct on nonwords, so guessing 'yes' scores 50.
Baseline only (one fixed list), per plan §4.4."""

from __future__ import annotations

from dataclasses import asdict, dataclass

# The published English list, in its standard order. (is_word, item)
ITEMS: list[tuple[bool, str]] = [
    (False, "platery"),
    (True, "denial"),
    (True, "generic"),
    (False, "mensible"),
    (True, "scornful"),
    (True, "stoutly"),
    (True, "ablaze"),
    (False, "kermshaw"),
    (True, "moonlit"),
    (True, "lofty"),
    (True, "hurricane"),
    (True, "flaw"),
    (False, "alberation"),
    (True, "unkempt"),
    (True, "breeding"),
    (True, "festivity"),
    (True, "screech"),
    (True, "savoury"),
    (False, "plaudate"),
    (True, "shin"),
    (True, "fluid"),
    (False, "spaunch"),
    (True, "allied"),
    (True, "slain"),
    (True, "recipient"),
    (False, "exprate"),
    (True, "eloquence"),
    (True, "cleanliness"),
    (True, "dispatch"),
    (False, "rebondicate"),
    (True, "ingenious"),
    (True, "bewitch"),
    (False, "skave"),
    (True, "plaintively"),
    (False, "kilp"),
    (False, "interfate"),
    (True, "hasty"),
    (True, "lengthy"),
    (True, "fray"),
    (False, "crumper"),
    (True, "upkeep"),
    (True, "majestic"),
    (False, "magrity"),
    (True, "nourishment"),
    (False, "abergy"),
    (False, "proom"),
    (True, "turmoil"),
    (True, "carbohydrate"),
    (True, "scholar"),
    (True, "turtle"),
    (False, "fellick"),
    (False, "destription"),
    (True, "cylinder"),
    (True, "censorship"),
    (True, "celestial"),
    (True, "rascality"),
    (False, "purrage"),
    (False, "pulsh"),
    (True, "muddy"),
    (False, "quirty"),
    (False, "pudour"),
    (True, "listless"),
    (True, "wrought"),
]
# 63 entries above: the official test has 60 scored items; the first three ("platery",
# "denial", "generic") are the practice trials and are excluded from scoring.
PRACTICE = 3


@dataclass
class LexTaleScore:
    n_words: int
    n_nonwords: int
    words_correct: int
    nonwords_correct: int
    pct_words: float
    pct_nonwords: float
    score: float  # %correct_av
    mean_rt_ms: float | None
    unanswered: int

    def to_dict(self) -> dict:
        return asdict(self)


def score(responses: list[dict]) -> LexTaleScore:
    """responses: [{is_word: bool, answer: 'yes'|'no'|None, rt_ms: float|None, practice: bool}]"""
    scored = [r for r in responses if not r.get("practice")]
    words = [r for r in scored if r["is_word"]]
    non = [r for r in scored if not r["is_word"]]
    wc = sum(1 for r in words if r.get("answer") == "yes")
    nc = sum(1 for r in non if r.get("answer") == "no")
    pw = 100 * wc / len(words) if words else 0.0
    pn = 100 * nc / len(non) if non else 0.0
    rts = [r["rt_ms"] for r in scored if r.get("rt_ms") is not None and r.get("answer")]
    return LexTaleScore(
        n_words=len(words),
        n_nonwords=len(non),
        words_correct=wc,
        nonwords_correct=nc,
        pct_words=round(pw, 2),
        pct_nonwords=round(pn, 2),
        score=round((pw + pn) / 2, 2),
        mean_rt_ms=round(sum(rts) / len(rts), 1) if rts else None,
        unanswered=sum(1 for r in scored if not r.get("answer")),
    )
