"""Tiny Postgres job queue. Enough for M0; M1 adds real handlers, not a new queue."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Job


def enqueue(db: Session, type_: str, payload: dict, *, max_attempts: int = 3) -> Job:
    job = Job(type=type_, payload=payload, max_attempts=max_attempts)
    db.add(job)
    db.flush()
    return job


def claim(db: Session, worker_id: str) -> Job | None:
    """Atomically take one runnable job. Caller owns the transaction."""
    now = datetime.now(UTC)
    stmt = (
        select(Job)
        .where(Job.status == "queued", Job.run_after <= now)
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = db.scalar(stmt)
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.locked_at = now
    job.locked_by = worker_id
    db.flush()
    return job


def complete(db: Session, job: Job) -> None:
    job.status = "done"
    job.finished_at = datetime.now(UTC)
    job.locked_by = None


def fail(db: Session, job: Job, error: str) -> None:
    job.last_error = error[:4000]
    job.locked_by = None
    if job.attempts >= job.max_attempts:
        job.status = "failed"
        job.finished_at = datetime.now(UTC)
    else:
        job.status = "queued"
        job.run_after = datetime.now(UTC) + timedelta(seconds=30 * job.attempts)


def get(db: Session, job_id: uuid.UUID) -> Job | None:
    return db.get(Job, job_id)
