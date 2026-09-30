"""Syntactic complexity from spaCy parses, and error classification with ERRANT against Claude's
minimal correction (plan §5.4). All deterministic given the inputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache

CLAUSE_DEPS = {"ROOT", "ccomp", "xcomp", "advcl", "relcl", "acl", "csubj", "conj"}
SUBORDINATE_DEPS = {"ccomp", "xcomp", "advcl", "relcl", "acl", "csubj"}


@lru_cache
def nlp():
    import spacy

    return spacy.load("en_core_web_sm")


@dataclass
class SyntaxReport:
    words: int
    sentences: int
    clauses: int
    subordinate_clauses: int
    mean_sentence_len: float | None
    mean_clause_len: float | None
    subordination_ratio: float | None  # subordinate / clauses
    mean_np_len: float | None
    verbs_per_clause: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(text: str) -> SyntaxReport:
    doc = nlp()(text)
    words = [t for t in doc if not t.is_punct and not t.is_space]
    sents = list(doc.sents)
    clause_heads = [t for t in doc if t.pos_ in ("VERB", "AUX") and t.dep_ in CLAUSE_DEPS]
    # `conj` counts as a clause only when it is a verb coordinated with another verb
    clause_heads = [
        t for t in clause_heads if not (t.dep_ == "conj" and t.head.pos_ not in ("VERB", "AUX"))
    ]
    n_cl = max(len(clause_heads), 1 if words else 0)
    sub = sum(1 for t in clause_heads if t.dep_ in SUBORDINATE_DEPS)
    nps = [len([x for x in ch if not x.is_punct]) for ch in doc.noun_chunks]
    verbs = sum(1 for t in words if t.pos_ == "VERB")
    return SyntaxReport(
        words=len(words),
        sentences=len(sents),
        clauses=n_cl,
        subordinate_clauses=sub,
        mean_sentence_len=round(len(words) / len(sents), 2) if sents else None,
        mean_clause_len=round(len(words) / n_cl, 2) if n_cl else None,
        subordination_ratio=round(sub / n_cl, 3) if n_cl else None,
        mean_np_len=round(sum(nps) / len(nps), 2) if nps else None,
        verbs_per_clause=round(verbs / n_cl, 2) if n_cl else None,
    )


@dataclass
class ErrorReport:
    edits: list[dict]  # {type, orig, cor, o_start, o_end}
    per_100_words: float
    by_type: dict[str, int]
    error_free_clause_share: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@lru_cache
def _annotator():
    import errant

    return errant.load("en", nlp())


def classify_errors(original: str, corrected: str) -> ErrorReport:
    ann = _annotator()
    orig = ann.parse(original)
    cor = ann.parse(corrected)
    edits = ann.annotate(orig, cor)
    out = []
    by_type: dict[str, int] = {}
    for e in edits:
        if e.type == "noop":
            continue
        out.append(
            {
                "type": e.type,
                "orig": e.o_str,
                "cor": e.c_str,
                "o_start": e.o_start,
                "o_end": e.o_end,
            }
        )
        by_type[e.type] = by_type.get(e.type, 0) + 1
    n_words = max(1, sum(1 for t in orig if not t.is_punct))
    # error-free clauses: clause heads (in the original parse) whose subtree contains no edit span
    clause_heads = [t for t in orig if t.pos_ in ("VERB", "AUX") and t.dep_ in CLAUSE_DEPS]
    spans = [(e["o_start"], e["o_end"]) for e in out]
    free = 0
    for h in clause_heads:
        lo, hi = h.left_edge.i, h.right_edge.i + 1
        if not any(s < hi and e > lo for s, e in spans):
            free += 1
    return ErrorReport(
        edits=out,
        per_100_words=round(100 * len(out) / n_words, 2),
        by_type=by_type,
        error_free_clause_share=round(free / len(clause_heads), 3) if clause_heads else None,
    )
