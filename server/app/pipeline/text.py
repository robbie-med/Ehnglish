"""Text normalisation shared by every scorer. Deterministic, no models."""

from __future__ import annotations

import re
import unicodedata

_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = {
    2: "twenty",
    3: "thirty",
    4: "forty",
    5: "fifty",
    6: "sixty",
    7: "seventy",
    8: "eighty",
    9: "ninety",
}


def _num_words(n: int) -> list[str]:
    """0–999 as spoken words (no 'and'), so '20' and 'twenty' compare equal."""
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        t, o = divmod(n, 10)
        return [_TENS[t]] + ([_ONES[o]] if o else [])
    h, rest = divmod(n, 100)
    return [_ONES[h], "hundred"] + (_num_words(rest) if rest else [])


_NUM = {str(n): " ".join(_num_words(n)) for n in range(0, 1000)}
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
    """Lower-case word tokens with punctuation stripped. Numbers below 1000 become words."""
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
    t = re.sub(r"[^\w' ]+", " ", t)  # \w keeps Hangul and other Unicode letters
    t = t.replace("_", " ")
    words = []
    for w in t.split():
        w = w.strip("'")
        if not w:
            continue
        if w in _NUM:
            words.extend(_NUM[w].split())
            continue
        if drop_fillers and w in FILLERS:
            continue
        words.append(w)
    return words
