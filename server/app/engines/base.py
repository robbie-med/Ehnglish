from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class TWord:
    word: str
    start: float | None = None
    end: float | None = None
    conf: float | None = None


@dataclass
class Transcript:
    engine: str
    text: str
    words: list[TWord] = field(default_factory=list)
    language: str = "en"
    conf: float | None = None
    raw: dict | None = None  # engine payload, kept for re-scoring

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class EngineError(RuntimeError):
    pass
