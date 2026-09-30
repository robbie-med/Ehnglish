"""Text normalisation shared by every scorer. Deterministic, no models."""

from __future__ import annotations

import re
import unicodedata

_NUM = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "10": "ten",
    "11": "eleven",
    "12": "twelve",
}
_CONTRACTIONS = {
    "can't": "cannot",
    "won't": "will not",
    "n't": " not",
    "'re": " are",
    "'ve": " have",
    "'ll": " will",
    "'d": " would",
    "'m": " am",
    "it's": "it is",
    "that's": "that is",
    "what's": "what is",
    "there's": "there is",
    "he's": "he is",
    "she's": "she is",
    "let's": "let us",
}
FILLERS = {"um", "uh", "uhm", "hmm", "mm", "er", "ah", "eh", "mhm", "erm"}


def normalize(
    text: str, *, expand_contractions: bool = True, drop_fillers: bool = False
) -> list[str]:
    """Lower-case word tokens with punctuation stripped. Numbers ≤12 become words."""
    t = unicodedata.normalize("NFKC", text).lower().replace("’", "'")
    if expand_contractions:
        for k, v in _CONTRACTIONS.items():
            t = re.sub(
                rf"(?<=\w){re.escape(k)}\b"
                if k.startswith("'") or k == "n't"
                else rf"\b{re.escape(k)}\b",
                v,
                t,
            )
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    words = []
    for w in t.split():
        w = w.strip("'")
        if not w:
            continue
        w = _NUM.get(w, w)
        if drop_fillers and w in FILLERS:
            continue
        words.append(w)
    return words
