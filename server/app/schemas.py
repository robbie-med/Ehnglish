"""Request/response models for the API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MeOut(BaseModel):
    email: str
    env: str
    role: str = "learner"


class FormSummary(BaseModel):
    id: str
    version: int
    kind: str
    title: dict[str, str]
    task_count: int
    item_count: int


class SessionCreate(BaseModel):
    form_id: str
    setup: dict = Field(default_factory=dict)
    client: dict = Field(default_factory=dict)


class SessionPatch(BaseModel):
    setup: dict | None = None
    status: Literal["open", "done", "abandoned"] | None = None


class TakeCreate(BaseModel):
    task_id: str
    item_id: str
    attempt: int = 1
    kind: Literal["audio", "typed"]
    sample_rate: int | None = None
    channels: int | None = None
    bits_per_sample: int | None = None
    total_bytes: int | None = None


class TakeFinalize(BaseModel):
    sha256: str = Field(min_length=64, max_length=64)
    chunk_count: int = Field(ge=1)
    quality: dict | None = None


class Keystroke(BaseModel):
    t: float  # ms, performance.now() on the client
    type: Literal["down", "up", "input"]
    key: str | None = None
    code: str | None = None
    len: int | None = None  # text length after an input event


class TypedSubmit(BaseModel):
    text: str
    keystrokes: list[Keystroke] = Field(default_factory=list)


class EventIn(BaseModel):
    name: str = Field(max_length=32)
    t_client_ms: float
    meta: dict | None = None


class ResultOut(BaseModel):
    id: uuid.UUID
    kind: str
    pipeline_version: str
    result: dict
    created_at: datetime


class TakeOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    task_id: str
    item_id: str
    attempt: int
    kind: str
    status: str
    sample_rate: int | None
    channels: int | None
    duration_s: float | None
    sha256: str | None
    wav_path: str | None
    quality: dict | None
    error: str | None
    created_at: datetime
    finalized_at: datetime | None
    text: str | None = None
    keystroke_count: int | None = None
    events: list[dict] = Field(default_factory=list)
    results: list[ResultOut] = Field(default_factory=list)


class SessionOut(BaseModel):
    id: uuid.UUID
    form_id: str
    form_version: int
    status: str
    setup: dict
    client: dict
    started_at: datetime
    finished_at: datetime | None
    takes: list[TakeOut] = Field(default_factory=list)


class UploadStatus(BaseModel):
    take_id: uuid.UUID
    status: str
    received: list[int]
