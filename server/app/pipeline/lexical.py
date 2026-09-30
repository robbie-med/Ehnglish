"""Lexical measures: diversity (MTLD, TTR), frequency profile (wordfreq ranks as band proxies),
and domain coverage (patient-side medical list). Uses the confident words only."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

from .text import FILLERS

BANDS = [("1k", 1000), ("2k", 2000), ("3k", 3000), ("5k", 5000), ("10k", 10000)]


@lru_cache
def _rank_table(n: int = 10000) -> dict[str, int]:
    return {w: i + 1 for i, w in enumerate(top_n_list("en", n))}


@lru_cache
def _medical_words() -> frozenset[str]:
    p = Path(__file__).resolve().parents[3] / "content" / "lexicon" / "patient_side.txt"
    if not p.exists():
        return frozenset()
    return frozenset(
        w.strip().lower()
        for w in p.read_text(encoding="utf-8").splitlines()
        if w.strip() and not w.startswith("#")
    )


def mtld(tokens: list[str], ttr_threshold: float = 0.72) -> float | None:
    """McCarthy & Jarvis (2010) measure of textual lexical diversity, forward + backward mean."""
    if len(tokens) < 10:
        return None

    def one_pass(seq: list[str]) -> float:
        factors = 0.0
        types: set[str] = set()
        count = 0
        for tok in seq:
            count += 1
            types.add(tok)
            if len(types) / count <= ttr_threshold:
                factors += 1
                types = set()
                count = 0
        if count:
            ttr = len(types) / count
            factors += (1 - ttr) / (1 - ttr_threshold) if ttr < 1 else 0
        return len(seq) / factors if factors else float(len(seq))

    return round((one_pass(tokens) + one_pass(tokens[::-1])) / 2, 2)


@dataclass
class LexicalReport:
    tokens: int
    types: int
    ttr: float | None
    mtld: float | None
    mean_zipf: float | None
    band_shares: dict[str, float]  # share of tokens whose rank ≤ band cut, cumulative
    off_list_share: float
    medical_tokens: int
    medical_types: list[str]
    fillers: int

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(words: list[str]) -> LexicalReport:
    toks = [w.lower() for w in words if w]
    content = [w for w in toks if w not in FILLERS]
    n = len(content)
    if n == 0:
        return LexicalReport(
            0, 0, None, None, None, {b: 0.0 for b, _ in BANDS}, 0.0, 0, [], len(toks) - n
        )
    ranks = _rank_table()
    rs = [ranks.get(w) for w in content]
    bands = {b: round(sum(1 for r in rs if r is not None and r <= cut) / n, 4) for b, cut in BANDS}
    zipfs = [zipf_frequency(w, "en") for w in content]
    med = _medical_words()
    med_hits = [w for w in content if w in med]
    return LexicalReport(
        tokens=n,
        types=len(set(content)),
        ttr=round(len(set(content)) / n, 4),
        mtld=mtld(content),
        mean_zipf=round(sum(zipfs) / n, 3),
        band_shares=bands,
        off_list_share=round(sum(1 for r in rs if r is None) / n, 4),
        medical_tokens=len(med_hits),
        medical_types=sorted(set(med_hits)),
        fillers=len(toks) - n,
    )
