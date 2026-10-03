import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import queue
from ..auth import get_current_user
from ..config import Settings, get_settings
from ..content import get_forms
from ..db import get_db
from ..models import SessionResult, Take, TestSession, User
from ..schemas import SessionCreate, SessionOut, SessionPatch, TakeCreate, TakeOut
from .takes import take_out

router = APIRouter(prefix="/sessions", tags=["sessions"])


def own_session(db: Session, user: User, session_id: uuid.UUID) -> TestSession:
    s = db.scalar(
        select(TestSession)
        .where(TestSession.id == session_id, TestSession.user_id == user.id)
        .options(
            selectinload(TestSession.takes).selectinload(Take.events),
            selectinload(TestSession.takes).selectinload(Take.results),
            selectinload(TestSession.takes).selectinload(Take.typed),
        )
    )
    if s is None:
        raise HTTPException(404, "session not found")
    return s


def session_out(s: TestSession) -> SessionOut:
    return SessionOut(
        id=s.id,
        form_id=s.form_id,
        form_version=s.form_version,
        status=s.status,
        setup=s.setup,
        client=s.client,
        started_at=s.started_at,
        finished_at=s.finished_at,
        takes=[take_out(t) for t in s.takes],
    )


@router.post("", response_model=SessionOut, status_code=201)
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> SessionOut:
    forms = get_forms(str(settings.content_dir))
    if body.form_id not in forms:
        raise HTTPException(404, "unknown form")
    s = TestSession(
        user_id=user.id,
        form_id=body.form_id,
        form_version=forms[body.form_id].version,
        setup=body.setup,
        client=body.client,
    )
    db.add(s)
    db.commit()
    return session_out(own_session(db, user, s.id))


@router.get("", response_model=list[SessionOut])
def list_sessions(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[SessionOut]:
    rows = db.scalars(
        select(TestSession)
        .where(TestSession.user_id == user.id)
        .order_by(TestSession.started_at.desc())
        .options(
            selectinload(TestSession.takes).selectinload(Take.events),
            selectinload(TestSession.takes).selectinload(Take.results),
            selectinload(TestSession.takes).selectinload(Take.typed),
        )
    ).all()
    return [session_out(s) for s in rows]


@router.get("/{session_id}", response_model=SessionOut)
def get_session(
    session_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> SessionOut:
    return session_out(own_session(db, user, session_id))


@router.patch("/{session_id}", response_model=SessionOut)
def patch_session(
    session_id: uuid.UUID,
    body: SessionPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SessionOut:
    s = own_session(db, user, session_id)
    if body.setup is not None:
        s.setup = {**s.setup, **body.setup}
    if body.status is not None:
        s.status = body.status
        if body.status in ("done", "abandoned"):
            s.finished_at = datetime.now(UTC)
        if body.status == "done":
            queue.enqueue(db, "session_summary", {"session_id": str(s.id)}, max_attempts=30)
    db.commit()
    return session_out(own_session(db, user, session_id))


@router.post("/{session_id}/takes", response_model=TakeOut, status_code=201)
def create_take(
    session_id: uuid.UUID,
    body: TakeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> TakeOut:
    s = own_session(db, user, session_id)
    if s.status != "open":
        raise HTTPException(409, "session is closed")
    form = get_forms(str(settings.content_dir))[s.form_id]
    task = next((t for t in form.tasks if t.id == body.task_id), None)
    if task is None or not any(i.id == body.item_id for i in task.items):
        raise HTTPException(400, "task/item not in this form")
    expected_kind = task.kind
    if body.kind != expected_kind:
        raise HTTPException(400, f"task {task.id} expects kind={expected_kind}")
    if body.kind == "audio" and not (body.sample_rate and body.channels):
        raise HTTPException(400, "audio takes need sample_rate and channels")
    # A new attempt supersedes earlier ones for the same item. If the requested attempt number is
    # already taken (a resumed sitting), the server assigns the next one rather than refusing.
    existing = [t for t in s.takes if t.task_id == body.task_id and t.item_id == body.item_id]
    attempt = body.attempt
    if any(t.attempt == attempt for t in existing):
        attempt = max(t.attempt for t in existing) + 1
    for prev in existing:
        if prev.status != "rejected":
            prev.status = "rejected"
    take = Take(
        session_id=s.id,
        task_id=body.task_id,
        item_id=body.item_id,
        attempt=attempt,
        kind=body.kind,
        sample_rate=body.sample_rate,
        channels=body.channels,
        bits_per_sample=body.bits_per_sample or (16 if body.kind == "audio" else None),
        total_bytes=body.total_bytes,
        status="uploading",
    )
    db.add(take)
    try:
        db.commit()
    except Exception as e:  # unique (session, task, item, attempt)
        db.rollback()
        raise HTTPException(409, "that attempt already exists") from e
    db.refresh(take)
    return take_out(take)


@router.get("/{session_id}/results")
def session_results(
    session_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Session-level results (latest row per kind, any pipeline version, newest first)."""
    own_session(db, user, session_id)
    rows = db.scalars(
        select(SessionResult)
        .where(SessionResult.session_id == session_id)
        .order_by(SessionResult.created_at.desc())
    ).all()
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(
            r.kind,
            {
                "pipeline_version": r.pipeline_version,
                "result": r.result,
                "created_at": r.created_at.isoformat(),
            },
        )
    return out
