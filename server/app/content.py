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
    # read_aloud: the text she reads. typed_response: the prompt she answers.
    text: str | None = None
    prompt: Text2 | None = None
    audio: str | None = None  # relative path under content/audio/, for listening tasks later
    # Target properties used by scoring (syllables, frequency band, structure, min words...).
    target: dict = Field(default_factory=dict)


TaskType = Literal["read_aloud", "typed_response"]


class Task(BaseModel):
    id: str
    type: TaskType
    title: Text2
    instructions: Text2
    timing: Timing
    allow_rerecord: bool = True
    items: list[Item]

    @model_validator(mode="after")
    def _items_fit_type(self) -> Task:
        for it in self.items:
            if self.type == "read_aloud" and not it.text:
                raise ValueError(f"{self.id}/{it.id}: read_aloud items need text")
            if self.type == "typed_response" and not it.prompt:
                raise ValueError(f"{self.id}/{it.id}: typed_response items need a prompt")
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
