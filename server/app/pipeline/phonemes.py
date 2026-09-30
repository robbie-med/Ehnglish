"""Expected-vs-produced phoneme comparison (plan §5.1): ARPAbet expectations from CMUdict mapped
to IPA, aligned against the phoneme recognizer's IPA output. Reports substitutions, deletions and
insertions, and tallies the Korean-L1 contrasts the plan cares about.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from rapidfuzz.distance import Levenshtein

from .ei import phones as cmu_phones
from .text import normalize

ARPA_TO_IPA = {
    "AA": "ɑ",
    "AE": "æ",
    "AH": "ʌ",
    "AO": "ɔ",
    "AW": "aʊ",
    "AY": "aɪ",
    "B": "b",
    "CH": "tʃ",
    "D": "d",
    "DH": "ð",
    "EH": "ɛ",
    "ER": "ɝ",
    "EY": "eɪ",
    "F": "f",
    "G": "ɡ",
    "HH": "h",
    "IH": "ɪ",
    "IY": "i",
    "JH": "dʒ",
    "K": "k",
    "L": "l",
    "M": "m",
    "N": "n",
    "NG": "ŋ",
    "OW": "oʊ",
    "OY": "ɔɪ",
    "P": "p",
    "R": "ɹ",
    "S": "s",
    "SH": "ʃ",
    "T": "t",
    "TH": "θ",
    "UH": "ʊ",
    "UW": "u",
    "V": "v",
    "W": "w",
    "Y": "j",
    "Z": "z",
    "ZH": "ʒ",
}
# Recognizer output normalisation: collapse allophones/notation variants to the table above.
IPA_CANON = {
    "r": "ɹ",
    "g": "ɡ",
    "ɚ": "ɝ",
    "ə": "ʌ",
    "ɐ": "ʌ",
    "ɾ": "t",
    "ʔ": "t",
    "ɫ": "l",
    "e": "eɪ",
    "o": "oʊ",
    "ɜ": "ɝ",
    "ɔɪ": "ɔɪ",
}
# Contrast categories from the plan. A substitution is tagged when {expected, produced} matches.
CONTRASTS: dict[str, set[frozenset[str]]] = {
    "r/l": {frozenset({"ɹ", "l"})},
    "f/p": {frozenset({"f", "p"})},
    "v/b": {frozenset({"v", "b"})},
    "z/dʒ": {frozenset({"z", "dʒ"}), frozenset({"z", "ʒ"})},
    "θ/s": {frozenset({"θ", "s"}), frozenset({"ð", "d"}), frozenset({"θ", "t"})},
    "i/ɪ": {frozenset({"i", "ɪ"})},
    "ʃ/s": {frozenset({"ʃ", "s"})},
}
VOWELS = {"ɑ", "æ", "ʌ", "ɔ", "aʊ", "aɪ", "ɛ", "ɝ", "eɪ", "ɪ", "i", "oʊ", "ɔɪ", "ʊ", "u"}


def expected_ipa(text: str) -> list[list[str]]:
    """Per word: IPA phones (empty list for out-of-dictionary words)."""
    out: list[list[str]] = []
    for w in normalize(text):
        ph = cmu_phones(w)
        out.append([ARPA_TO_IPA.get(p, p.lower()) for p in ph] if ph else [])
    return out


def tokenize_ipa(s: str) -> list[str]:
    """Split a recognizer string ('ð ʌ f ɑ ɹ m ʌ s i' or 'ðʌfɑɹ...') into canonical phones."""
    toks = s.split() if " " in s.strip() else list(s.strip())
    out: list[str] = []
    i = 0
    while i < len(toks):
        two = "".join(toks[i : i + 2])
        if two in {"aʊ", "aɪ", "eɪ", "oʊ", "ɔɪ", "tʃ", "dʒ"}:
            out.append(two)
            i += 2
            continue
        t = toks[i]
        if t in ("ː", "ˈ", "ˌ", "̩", "̃"):
            i += 1
            continue
        out.append(IPA_CANON.get(t, t))
        i += 1
    return out


@dataclass
class PhonemeReport:
    expected: list[str]
    produced: list[str]
    n_expected: int
    correct: int
    substitutions: int
    deletions: int
    insertions: int
    phone_accuracy: float | None  # correct / expected
    per: float | None  # phone error rate = (S+D+I)/expected
    confusions: list[dict]  # {expected, produced, n}
    contrast_errors: dict[str, int]
    extra_vowels: int  # inserted vowels (epenthesis after final consonants / in clusters)

    def to_dict(self) -> dict:
        return asdict(self)


def compare(expected_words: list[list[str]], produced: list[str]) -> PhonemeReport:
    exp = [p for w in expected_words for p in w]
    ops = Levenshtein.editops(exp, produced)
    subs = dels = ins = 0
    conf: Counter[tuple[str, str]] = Counter()
    contrast: Counter[str] = Counter()
    extra_v = 0
    for op in ops:
        if op.tag == "replace":
            subs += 1
            e, p = exp[op.src_pos], produced[op.dest_pos]
            conf[(e, p)] += 1
            pair = frozenset({e, p})
            for name, pairs in CONTRASTS.items():
                if pair in pairs:
                    contrast[name] += 1
        elif op.tag == "delete":
            dels += 1
            conf[(exp[op.src_pos], "")] += 1
        else:
            ins += 1
            conf[("", produced[op.dest_pos])] += 1
            if produced[op.dest_pos] in VOWELS:
                extra_v += 1
    n = len(exp)
    correct = n - subs - dels
    return PhonemeReport(
        expected=exp,
        produced=produced,
        n_expected=n,
        correct=correct,
        substitutions=subs,
        deletions=dels,
        insertions=ins,
        phone_accuracy=round(correct / n, 4) if n else None,
        per=round((subs + dels + ins) / n, 4) if n else None,
        confusions=[{"expected": e, "produced": p, "n": k} for (e, p), k in conf.most_common(30)],
        contrast_errors=dict(contrast),
        extra_vowels=extra_v,
    )
