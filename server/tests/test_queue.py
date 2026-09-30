from datetime import UTC, datetime

from app import queue, worker
from app.models import Job


def test_retry_backoff_then_failed(db) -> None:
    calls = {"n": 0}

    def boom(_db, _job):
        calls["n"] += 1
        raise RuntimeError("nope")

    worker.HANDLERS["boom"] = boom
    try:
        job = queue.enqueue(db, "boom", {}, max_attempts=2)
        db.commit()
        j1 = worker.run_once(db)
        assert j1 is not None and j1.status == "queued" and j1.attempts == 1
        assert j1.run_after > datetime.now(UTC)  # backoff
        assert "nope" in (j1.last_error or "")
        assert worker.run_once(db) is None  # not runnable yet
        j1.run_after = datetime.now(UTC)
        db.commit()
        j2 = worker.run_once(db)
        assert j2 is not None and j2.status == "failed" and j2.attempts == 2
        assert calls["n"] == 2
        assert db.get(Job, job.id).finished_at is not None
    finally:
        worker.HANDLERS.pop("boom", None)


def test_unknown_handler_fails_without_crashing(db) -> None:
    queue.enqueue(db, "does_not_exist", {}, max_attempts=1)
    db.commit()
    j = worker.run_once(db)
    assert j is not None and j.status == "failed" and "no handler" in j.last_error


def test_fifo_order(db) -> None:
    seen = []
    worker.HANDLERS["rec"] = lambda _db, job: seen.append(job.payload["i"])
    try:
        for i in range(3):
            queue.enqueue(db, "rec", {"i": i})
        db.commit()
        while worker.run_once(db):
            pass
        assert seen == [0, 1, 2]
    finally:
        worker.HANDLERS.pop("rec", None)
