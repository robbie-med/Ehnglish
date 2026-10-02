"""Dictation scoring: word error rate of the typed sentence against the key, with the edit
breakdown. Conditions (clear/fast/phone/noise) are tagged by the item; penalties are differences
between condition means and are computed at session level."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from rapidfuzz.distance import Levenshtein

from .text import normalize


@dataclass
class WerReport:
    condition: str
    target_words: int
    typed_words: int
    substitutions: int
    deletions: int
    insertions: int
    wer: float  # (S+D+I)/N, may exceed 1
    exact: bool
    alignment: list[dict]  # {target, typed, op}

    def to_dict(self) -> dict:
        return asdict(self)


def score(target: str, typed: str, condition: str = "clear") -> WerReport:
    t = normalize(target)
    r = normalize(typed)
    ops = Levenshtein.editops(t, r)
    s = sum(1 for o in ops if o.tag == "replace")
    d = sum(1 for o in ops if o.tag == "delete")
    i = sum(1 for o in ops if o.tag == "insert")
    align: list[dict] = []
    ti = ri = 0
    for o in ops:
        while ti < o.src_pos and ri < o.dest_pos:
            align.append({"target": t[ti], "typed": r[ri], "op": "ok"})
            ti += 1
            ri += 1
        if o.tag == "replace":
            align.append({"target": t[ti], "typed": r[ri], "op": "sub"})
            ti += 1
            ri += 1
        elif o.tag == "delete":
            align.append({"target": t[ti], "typed": None, "op": "del"})
            ti += 1
        else:
            align.append({"target": None, "typed": r[ri], "op": "ins"})
            ri += 1
    while ti < len(t) and ri < len(r):
        align.append({"target": t[ti], "typed": r[ri], "op": "ok"})
        ti += 1
        ri += 1
    n = max(1, len(t))
    return WerReport(
        condition=condition,
        target_words=len(t),
        typed_words=len(r),
        substitutions=s,
        deletions=d,
        insertions=i,
        wer=round((s + d + i) / n, 4),
        exact=(s + d + i) == 0,
        alignment=align,
    )


def condition_summary(reports: list[WerReport]) -> dict:
    """Mean WER per condition plus the phone and noise penalties (vs clear)."""
    by: dict[str, list[float]] = {}
    for r in reports:
        by.setdefault(r.condition, []).append(r.wer)
    means = {c: round(sum(v) / len(v), 4) for c, v in by.items()}
    clear = means.get("clear")
    out: dict = {"mean_wer": means, "n": {c: len(v) for c, v in by.items()}}
    for c in ("fast", "phone", "noise"):
        out[f"{c}_penalty"] = (
            round(means[c] - clear, 4) if clear is not None and c in means else None
        )
    return out
