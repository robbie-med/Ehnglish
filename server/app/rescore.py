"""Re-score past sittings after a pipeline change (plan §2.6): bump EHNGLISH_PIPELINE_VERSION,
then `python -m app.rescore [--form core-A] [--session <id>] [--dry-run]`. Every finalized or
processed take gets a new process_take job and every finished session a session_summary job; the
old result rows stay, tagged with their version, so trends never mix methods."""

from __future__ import annotations

import argparse
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import queue
from .config import get_settings
from .db import get_sessionmaker
from .models import Take, TestSession


def enqueue_rescore(
    db: Session, *, form_id: str | None = None, session_id: uuid.UUID | None = None
) -> dict:
    q = select(TestSession).where(TestSession.status == "done")
    if form_id:
        q = q.where(TestSession.form_id == form_id)
    if session_id:
        q = q.where(TestSession.id == session_id)
    sessions = db.scalars(q.order_by(TestSession.started_at)).all()
    n_takes = 0
    for s in sessions:
        takes = db.scalars(
            select(Take).where(Take.session_id == s.id, Take.status.in_(("finalized", "processed")))
        ).all()
        for t in takes:
            queue.enqueue(db, "process_take", {"take_id": str(t.id)}, max_attempts=5)
            n_takes += 1
        queue.enqueue(db, "session_summary", {"session_id": str(s.id)}, max_attempts=30)
    db.commit()
    return {
        "sessions": len(sessions),
        "takes": n_takes,
        "pipeline_version": get_settings().pipeline_version,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--form")
    ap.add_argument("--session")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    with get_sessionmaker()() as db:
        if args.dry_run:
            q = select(TestSession).where(TestSession.status == "done")
            if args.form:
                q = q.where(TestSession.form_id == args.form)
            n = len(db.scalars(q).all())
            print(f"would re-score {n} sessions at pipeline {get_settings().pipeline_version}")
            return
        out = enqueue_rescore(
            db, form_id=args.form, session_id=uuid.UUID(args.session) if args.session else None
        )
        print(out)


if __name__ == "__main__":
    main()
