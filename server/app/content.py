"""Item bank: YAML forms under content/forms/, validated with pydantic at startup and in CI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

Lang = Literal["en", "ko"]


class Text2(BaseModel):
    """Bilingual string. Both languages are required from day one."""

    en: str
    ko: str


class Timing(BaseModel):
    prep_s: float = 0  # countdown before the response window opens
    respond_s: float = 30  # nominal response window (auto-stop for audio, deadline for typed)
    max_s: float | None = None  # hard cap; defaults to respond_s

    @model_validator(mode="after")
    def _cap(self) -> Timing:
        if self.max_s is None:
            self.max_s = self.respond_s
        if self.max_s < self.respond_s:
            raise ValueError("max_s must be >= respond_s")
        return self


class Item(BaseModel):
    id: str
    # read_aloud: the text she reads. sentence_repeat / quick_answer: the text of the audio prompt
    # (the scoring key; never shown to her). typed_response / describe_opinion: see prompt.
    text: str | None = None
    prompt: Text2 | None = None
    audio: str | None = None  # relative path under content/audio/ (built once, fixed forever)
    image: str | None = None  # relative path under content/images/ (picture description)
    timing: Timing | None = None  # per-item override of the task timing
    fx: AudioFx | None = None  # how the audio is built; None = plain TTS
    scale: Scale | None = None  # rating items
    options: list[str] | None = None  # multiple_choice
    # Target properties used by scoring (syllables, frequency band, structure, min words...).
    target: dict = Field(default_factory=dict)


TaskType = Literal[
    "silence",  # C0: record the room for the noise floor
    "read_aloud",  # C1
    "sentence_repeat",  # C2: hear once, tone, repeat
    "quick_answer",  # C3: hear a question, answer at once (latency)
    "phone_call",  # C4: pre-recorded caller through a phone line, one item per turn
    "describe_opinion",  # C5: describe (picture/process), then opinion with prep
    "dictation",  # C6: hear a sentence (clear/fast/phone/noise), type it
    "rating",  # C7 and self-report: one slider per item, stored as a typed number
    "typed_response",  # R4 / baseline writing
    "lexical_decision",  # LexTALE: word or not, yes/no with reaction time
    "copy_typing",  # typing baseline: copy a shown passage
    "multiple_choice",  # R1 vocabulary, R2/R3 comprehension: stem + options, one correct
    "reading_passage",  # R2: timed reading, she presses Done when finished
    "c_test",  # R2: text with half-deleted words, typed completions
    "axb",  # R3: hear A, X, B; is X the same as A or B?
]
AUDIO_TASKS = {
    "silence",
    "read_aloud",
    "sentence_repeat",
    "quick_answer",
    "phone_call",
    "describe_opinion",
}


class AudioFx(BaseModel):
    """How content/build_audio.py renders an item's prompt audio (plan §4.5)."""

    voice: str | None = None  # Azure voice name override (e.g. the caller)
    rate: str = "0%"  # TTS prosody rate, e.g. "+30%" for the fast dictation condition
    phone: bool = False  # 8 kHz G.711 μ-law round trip, 300–3400 Hz band, line hiss
    noise_snr_db: float | None = None  # mix pink/babble noise at this SNR (None = clean)
    noise_kind: Literal["pink", "babble"] = "pink"
    sequence: list[str] | None = (
        None  # AXB: words rendered one by one with gaps (item.text ignored)
    )
    dialogue: list[dict] | None = None  # [{voice, text}] rendered in turn (conversation clips)
    gap_s: float = 0.6


class Scale(BaseModel):
    min: int = 0
    max: int = 10
    labels: dict[str, Text2] = Field(default_factory=dict)  # {"0": {...}, "10": {...}}


class Task(BaseModel):
    id: str
    type: TaskType
    title: Text2
    instructions: Text2
    timing: Timing
    allow_rerecord: bool = True
    # Audio-prompt tasks: recording opens after this beep once the prompt has finished playing.
    tone_hz: int | None = None
    # Task-level scoring targets: phone_call goals/phrases, listening genre, etc.
    target: dict = Field(default_factory=dict)
    # Stimulus played once after the instructions (lecture/sermon/conversation clip) and/or a
    # passage shown alongside the items (reading comprehension).
    audio: str | None = None
    text: str | None = None
    items: list[Item]

    @property
    def kind(self) -> str:
        return "audio" if self.type in AUDIO_TASKS else "typed"

    @model_validator(mode="after")
    def _items_fit_type(self) -> Task:
        for it in self.items:
            where = f"{self.id}/{it.id}"
            if self.type == "read_aloud" and not it.text:
                raise ValueError(f"{where}: read_aloud items need text")
            if self.type in ("sentence_repeat", "quick_answer", "dictation") and not (
                it.text and it.audio
            ):
                raise ValueError(f"{where}: {self.type} items need text (the key) and audio")
            if self.type == "phone_call" and not (it.text and it.audio and it.prompt):
                raise ValueError(
                    f"{where}: phone_call turns need text, audio and a prompt (goal card)"
                )
            if self.type == "dictation" and it.target.get("condition") not in (
                "clear",
                "fast",
                "phone",
                "noise",
            ):
                raise ValueError(f"{where}: dictation items need target.condition")
            if self.type in ("typed_response", "describe_opinion", "rating") and not it.prompt:
                raise ValueError(f"{where}: {self.type} items need a prompt")
            if self.type == "rating" and it.scale is None:
                raise ValueError(f"{where}: rating items need a scale")
            if self.type == "lexical_decision" and (
                not it.text or it.target.get("is_word") not in (True, False)
            ):
                raise ValueError(f"{where}: lexical_decision items need text and target.is_word")
            if self.type == "copy_typing" and not it.text:
                raise ValueError(f"{where}: copy_typing items need the text to copy")
            if self.type == "multiple_choice":
                if not it.text or not it.options or len(it.options) < 2:
                    raise ValueError(f"{where}: multiple_choice items need text and ≥2 options")
                a = it.target.get("answer")
                if not isinstance(a, int) or not 0 <= a < len(it.options):
                    raise ValueError(f"{where}: target.answer must index an option")
            if self.type == "reading_passage" and not it.text:
                raise ValueError(f"{where}: reading_passage items need the passage text")
            if self.type == "c_test" and (not it.text or "{" not in it.text):
                raise ValueError(f"{where}: c_test items need text with {{blank}} markers")
            if self.type == "axb":
                if not it.audio or it.target.get("answer") not in ("A", "B"):
                    raise ValueError(f"{where}: axb items need audio and target.answer A or B")
        if self.type == "phone_call" and not self.target.get("goals"):
            raise ValueError(f"{self.id}: phone_call tasks need target.goals")
        return self


class Form(BaseModel):
    id: str
    version: int
    kind: Literal["core", "rotating", "baseline", "dummy"]
    title: Text2
    tasks: list[Task]

    @model_validator(mode="after")
    def _unique_ids(self) -> Form:
        seen: set[str] = set()
        for t in self.tasks:
            if t.id in seen:
                raise ValueError(f"duplicate task id {t.id}")
            seen.add(t.id)
            item_ids = [i.id for i in t.items]
            if len(item_ids) != len(set(item_ids)):
                raise ValueError(f"duplicate item id in task {t.id}")
        return self


def load_form(path: Path) -> Form:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Form.model_validate(data)


def load_forms(content_dir: Path) -> dict[str, Form]:
    forms: dict[str, Form] = {}
    for p in sorted((content_dir / "forms").glob("*.yaml")):
        form = load_form(p)
        if form.id in forms:
            raise ValueError(f"duplicate form id {form.id} in {p}")
        forms[form.id] = form
    return forms


@lru_cache
def get_forms(content_dir: str) -> dict[str, Form]:
    return load_forms(Path(content_dir))
