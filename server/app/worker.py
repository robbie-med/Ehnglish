"""CPU job worker. `python -m app.worker` runs forever; run_once() is for tests.

M0 ships one stub handler (wav_probe). M1 registers the speech pipeline here; every handler writes
ProcessingResult rows stamped with settings.pipeline_version and never mutates raw files.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
import traceback
import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from . import processing, queue, wav
from .config import get_settings
from .db import get_sessionmaker
from .models import Job, ProcessingResult, Take

log = logging.getLogger("worker")
Handler = Callable[[Session, Job], None]
HANDLERS: dict[str, Handler] = {}


def handler(name: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[name] = fn
        return fn

    return deco


@handler("wav_probe")
def wav_probe(db: Session, job: Job) -> None:
    settings = get_settings()
    take = db.get(Take, uuid.UUID(job.payload["take_id"]))
    if take is None or not take.wav_path:
        raise RuntimeError("take missing or has no audio")
    stats = wav.probe(settings.raw_dir / take.wav_path)
    db.add(
        ProcessingResult(
            take_id=take.id,
            job_id=job.id,
            kind="wav_probe",
            pipeline_version=settings.pipeline_version,
            result=stats,
        )
    )
    take.status = "processed"
    # Hand over to the M1 pipeline (separate job so a slow engine never blocks the probe).
    queue.enqueue(db, "process_take", {"take_id": str(take.id)}, max_attempts=5)


@handler("process_take")
def process_take(db: Session, job: Job) -> None:
    take = db.get(Take, uuid.UUID(job.payload["take_id"]))
    if take is None or (take.kind == "audio" and not take.wav_path):
        raise RuntimeError("take missing or has no audio")
    summary = processing.process_take(db, take, job.id)
    log.info("take %s: %s", take.id, summary)


def run_once(db: Session, worker_id: str = "test") -> Job | None:
    """Claim and run one job. Returns the job (done or failed/requeued) or None if idle."""
    job = queue.claim(db, worker_id)
    if job is None:
        db.rollback()
        return None
    db.commit()  # release the row lock; status=running keeps others away
    try:
        fn = HANDLERS.get(job.type)
        if fn is None:
            raise RuntimeError(f"no handler for job type {job.type}")
        fn(db, job)
        queue.complete(db, job)
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        job = db.get(Job, job.id)
        assert job is not None
        queue.fail(db, job, f"{e}\n{traceback.format_exc()}")
        db.commit()
        log.warning("job %s (%s) failed attempt %d: %s", job.id, job.type, job.attempts, e)
    return job


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stop = False

    def _stop(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info(
        "worker %s up, handlers=%s, pipeline=%s",
        worker_id,
        sorted(HANDLERS),
        settings.pipeline_version,
    )
    sm = get_sessionmaker()
    while not stop:
        with sm() as db:
            job = run_once(db, worker_id)
        if job is None:
            time.sleep(settings.worker_poll_s)
        else:
            log.info("job %s %s -> %s", job.id, job.type, job.status)


if __name__ == "__main__":
    main()
