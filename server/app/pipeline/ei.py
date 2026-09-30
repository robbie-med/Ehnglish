"""Elicited imitation (sentence repetition) scoring against a known target.

Syllable-level credit: words in the response are aligned to the target with edit distance; each
correctly reproduced target word earns its syllable count. A word with a small phonetic slip still
earns partial credit when its edit similarity is high. Also reports the longest target (in
syllables) she reproduced fully.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cmudict
from rapidfuzz.distance import Levenshtein

from .text import normalize

_CMU = cmudict.dict()


def phones(word: str) -> list[str] | None:
    """CMUdict phonemes without stress marks, or None if unknown."""
    prons = _CMU.get(word.lower())
    if not prons:
        return None
    return [re.sub(r"\d", "", ph) for ph in prons[0]]


def similarity(a: str, b: str) -> float:
    """Phoneme-level similarity when both words are in the dictionary, else letter-level."""
    pa, pb = phones(a), phones(b)
    if pa and pb:
        return Levenshtein.normalized_similarity(pa, pb)
    return Levenshtein.normalized_similarity(a, b)


def syllables(word: str) -> int:
    """CMUdict syllable count with a vowel-group fallback."""
    prons = _CMU.get(word.lower())
    if prons:
        return max(1, sum(1 for ph in prons[0] if ph[-1].isdigit()))
    groups = re.findall(r"[aeiouy]+", word.lower())
    n = len(groups)
    if word.lower().endswith("e") and n > 1 and not word.lower().endswith(("le", "ee")):
        n -= 1
    return max(1, n)


@dataclass
class EIScore:
    target_words: int
    target_syllables: int
    words_correct: int
    syllables_correct: float
    pct_syllables: float
    exact: bool
    alignment: list[tuple[str, str | None, float]]  # (target word, response word, credit)


def score_repetition(target: str, response: str, *, partial_threshold: float = 0.6) -> EIScore:
    t = normalize(target)
    r = normalize(response, drop_fillers=True)
    t_syl = [syllables(w) for w in t]
    ops = Levenshtein.editops(t, r)
    matched: dict[int, int | None] = {}
    i = j = 0
    for op in ops:
        while i < op.src_pos and j < op.dest_pos:
            matched[i] = j
            i += 1
            j += 1
        if op.tag == "replace":
            matched[i] = j
            i += 1
            j += 1
        elif op.tag == "delete":
            matched[i] = None
            i += 1
        else:  # insert
            j += 1
    while i < len(t) and j < len(r):
        matched[i] = j
        i += 1
        j += 1
    while i < len(t):
        matched[i] = None
        i += 1
    alignment: list[tuple[str, str | None, float]] = []
    syl_credit = 0.0
    words_ok = 0
    for idx, tw in enumerate(t):
        j = matched.get(idx)
        rw = r[j] if j is not None else None
        if rw is None:
            credit = 0.0
        elif rw == tw:
            credit = 1.0
            words_ok += 1
        else:
            sim = similarity(tw, rw)
            credit = 0.5 if sim >= partial_threshold else 0.0
        alignment.append((tw, rw, credit))
        syl_credit += credit * t_syl[idx]
    total_syl = sum(t_syl)
    return EIScore(
        target_words=len(t),
        target_syllables=total_syl,
        words_correct=words_ok,
        syllables_correct=round(syl_credit, 2),
        pct_syllables=round(100 * syl_credit / total_syl, 1) if total_syl else 0.0,
        exact=words_ok == len(t) == len(r),
        alignment=alignment,
    )


def longest_exact(scores: list[tuple[int, EIScore]]) -> int:
    """Given (target_syllables, score) pairs, the longest sentence repeated exactly."""
    return max((n for n, s in scores if s.exact), default=0)
