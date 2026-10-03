"""Schema v0. Everything raw is kept; every derived number carries a pipeline_version."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TestSession(Base):
    """One sitting of a form (baseline day, monthly core, ...)."""

    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    form_id: Mapped[str] = mapped_column(String(64), nullable=False)
    form_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open"
    )  # open|done|abandoned
    # C0 covariates: mic label, noise floor, headphone check, sleep/stress/mood sliders.
    setup: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Browser, sample rate, timezone, app version.
    client: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    takes: Mapped[list[Take]] = relationship(back_populates="session", order_by="Take.created_at")


class Take(Base):
    """One response to one item: an audio recording or a typed text. Re-records are new attempts."""

    __tablename__ = "takes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # audio | typed
    # uploading | finalized | processed | failed | rejected(re-recorded)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="uploading")
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(Integer)
    bits_per_sample: Mapped[int | None] = mapped_column(Integer)
    total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    wav_path: Mapped[str | None] = mapped_column(Text)  # relative to raw_dir
    duration_s: Mapped[float | None] = mapped_column(Float)
    # Client-side quality check result (clipping, loudness, noise floor, SNR, flags).
    quality: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped[TestSession] = relationship(back_populates="takes")
    events: Mapped[list[TakeEvent]] = relationship(order_by="TakeEvent.t_client_ms")
    results: Mapped[list[ProcessingResult]] = relationship(order_by="ProcessingResult.created_at")
    typed: Mapped[TypedResponse | None] = relationship(uselist=False)

    __table_args__ = (UniqueConstraint("session_id", "task_id", "item_id", "attempt"),)


class UploadChunk(Base):
    """Ledger for resumable uploads. Rows are deleted once the take is finalized."""

    __tablename__ = "upload_chunks"
    take_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("takes.id"), primary_key=True)
    index: Mapped[int] = mapped_column(Integer, primary_key=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TypedResponse(Base):
    __tablename__ = "typed_responses"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    take_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("takes.id"), unique=True, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    keystroke_log_path: Mapped[str | None] = mapped_column(Text)  # JSONL, relative to raw_dir
    keystroke_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TakeEvent(Base):
    """Client-side timeline of a take (prompt_end, record_start, record_stop, ...).

    t_client_ms is performance.now() on the client, so latencies are computed from differences
    within one take and never from server clocks.
    """

    __tablename__ = "take_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    take_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("takes.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    t_client_ms: Mapped[float] = mapped_column(Float, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Job(Base):
    """Postgres-backed CPU job queue (claimed with SELECT ... FOR UPDATE SKIP LOCKED)."""

    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(128))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessingResult(Base):
    """Any derived data about a take. Immutable; re-scoring appends a new row with a new version."""

    __tablename__ = "processing_results"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    take_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("takes.id"), nullable=False, index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id"))
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionResult(Base):
    """Session-level derived data (dictation condition summary, LexTALE score, expression gap,
    typing baselines, self-report vectors). Immutable per pipeline version, like take results."""

    __tablename__ = "session_results"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id"))
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
