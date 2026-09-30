"""Transcript voting across engines (ROVER-style, simplified).

Input: one word list per engine, each word with optional timing and confidence. The first engine
is the backbone; the others are aligned onto it by edit-distance alignment, producing slots. Each
slot is voted by majority; slots without a majority (or with low mean confidence) are marked
uncertain. Uncertain words stay in the transcript (for timing) but are excluded from counts.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from rapidfuzz.distance import Levenshtein

from .text import normalize


@dataclass
class Word:
    text: str
    start: float | None = None
    end: float | None = None
    conf: float | None = None


@dataclass
class VotedWord:
    text: str
    votes: int
    engines: int
    uncertain: bool
    start: float | None = None
    end: float | None = None
    candidates: dict[str, int] = field(default_factory=dict)


@dataclass
class VoteResult:
    words: list[VotedWord]
    agreement: float  # share of slots where all engines agreed
    uncertain_share: float
    n_engines: int

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words if w.text)

    @property
    def confident_text(self) -> str:
        return " ".join(w.text for w in self.words if w.text and not w.uncertain)


def _norm_words(words: list[Word]) -> list[Word]:
    out: list[Word] = []
    for w in words:
        toks = normalize(w.text)
        for tok in toks:
            out.append(Word(tok, w.start, w.end, w.conf))
    return out


def _align(backbone: list[str], other: list[str]) -> list[tuple[int | None, int | None]]:
    """Pairs of (backbone index, other index); None marks an insertion/deletion."""
    ops = Levenshtein.editops(backbone, other)
    pairs: list[tuple[int | None, int | None]] = []
    i = j = 0
    for op in ops:
        while i < op.src_pos and j < op.dest_pos:
            pairs.append((i, j))
            i += 1
            j += 1
        if op.tag == "replace":
            pairs.append((i, j))
            i += 1
            j += 1
        elif op.tag == "delete":
            pairs.append((i, None))
            i += 1
        elif op.tag == "insert":
            pairs.append((None, j))
            j += 1
    while i < len(backbone) and j < len(other):
        pairs.append((i, j))
        i += 1
        j += 1
    while i < len(backbone):
        pairs.append((i, None))
        i += 1
    while j < len(other):
        pairs.append((None, j))
        j += 1
    return pairs


def vote(engines: dict[str, list[Word]], *, min_conf: float = 0.5) -> VoteResult:
    """Majority vote over aligned words. `engines` maps engine name -> words; order matters
    only in that the first engine is the alignment backbone (use the most verbatim one)."""
    names = list(engines)
    if not names:
        return VoteResult([], 0.0, 0.0, 0)
    norm = {n: _norm_words(engines[n]) for n in names}
    backbone_name = names[0]
    backbone = norm[backbone_name]
    n = len(names)
    # slots: keyed by (backbone index, insertion sub-index). Each holds {engine: Word|None}.
    slots: dict[tuple[int, int], dict[str, Word | None]] = {}
    for i in range(len(backbone)):
        slots[(i, 0)] = {backbone_name: backbone[i]}
    for name in names[1:]:
        other = norm[name]
        pairs = _align([w.text for w in backbone], [w.text for w in other])
        last_bb = -1
        ins = 0
        for bi, oi in pairs:
            if bi is not None:
                last_bb = bi
                ins = 0
                slots.setdefault((bi, 0), {})[name] = other[oi] if oi is not None else None
            else:
                ins += 1
                slots.setdefault((last_bb, ins), {})[name] = other[oi] if oi is not None else None
    out: list[VotedWord] = []
    agree = 0
    uncertain = 0
    for key in sorted(slots):
        slot = slots[key]
        # Engines missing from an insertion slot voted for "nothing".
        cands = Counter()
        for name in names:
            w = slot.get(name)
            cands[w.text if w else ""] += 1
        best, best_votes = cands.most_common(1)[0]
        winners = [w for w in slot.values() if w and w.text == best]
        confs = [w.conf for w in winners if w and w.conf is not None]
        mean_conf = sum(confs) / len(confs) if confs else None
        is_unc = best_votes * 2 <= n or (mean_conf is not None and mean_conf < min_conf)
        if best_votes == n:
            agree += 1
        if best == "" and not is_unc:
            continue  # majority says nothing was said here
        starts = [w.start for w in winners if w and w.start is not None]
        ends = [w.end for w in winners if w and w.end is not None]
        vw = VotedWord(
            text=best,
            votes=best_votes,
            engines=n,
            uncertain=is_unc,
            start=min(starts) if starts else None,
            end=max(ends) if ends else None,
            candidates=dict(cands),
        )
        if is_unc:
            uncertain += 1
        out.append(vw)
    total = len(slots) or 1
    return VoteResult(out, round(agree / total, 4), round(uncertain / total, 4), n)
