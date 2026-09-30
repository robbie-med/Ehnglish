"""Take endpoints: chunked resumable upload, finalize, typed responses, events, audio download."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import queue, wav
from ..auth import get_current_user
from ..config import Settings, get_settings
from ..db import get_db
from ..models import Take, TakeEvent, TestSession, TypedResponse, UploadChunk, User
from ..schemas import EventIn, ResultOut, TakeFinalize, TakeOut, TypedSubmit, UploadStatus

router = APIRouter(prefix="/takes", tags=["takes"])


def take_out(t: Take) -> TakeOut:
    return TakeOut(
        id=t.id,
        session_id=t.session_id,
        task_id=t.task_id,
        item_id=t.item_id,
        attempt=t.attempt,
        kind=t.kind,
        status=t.status,
        sample_rate=t.sample_rate,
        channels=t.channels,
        duration_s=t.duration_s,
        sha256=t.sha256,
        wav_path=t.wav_path,
        quality=t.quality,
        error=t.error,
        created_at=t.created_at,
        finalized_at=t.finalized_at,
        text=t.typed.text if t.typed else None,
        keystroke_count=t.typed.keystroke_count if t.typed else None,
        events=[{"name": e.name, "t_client_ms": e.t_client_ms, "meta": e.meta} for e in t.events],
        results=[
            ResultOut(
                id=r.id,
                kind=r.kind,
                pipeline_version=r.pipeline_version,
                result=r.result,
                created_at=r.created_at,
            )
            for r in t.results
        ],
    )


def own_take(db: Session, user: User, take_id: uuid.UUID) -> Take:
    t = db.scalar(
        select(Take)
        .join(TestSession)
        .where(Take.id == take_id, TestSession.user_id == user.id)
        .options(selectinload(Take.events), selectinload(Take.results), selectinload(Take.typed))
    )
    if t is None:
        raise HTTPException(404, "take not found")
    return t


def parts_dir(settings: Settings, take_id: uuid.UUID) -> Path:
    return settings.raw_dir / "uploads" / str(take_id)


def final_rel_path(t: Take, ext: str) -> str:
    return f"sessions/{t.session_id}/{t.task_id}_{t.item_id}_a{t.attempt}_{t.id}.{ext}"


@router.get("/{take_id}", response_model=TakeOut)
def get_take(
    take_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> TakeOut:
    return take_out(own_take(db, user, take_id))


@router.get("/{take_id}/upload-status", response_model=UploadStatus)
def upload_status(
    take_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> UploadStatus:
    t = own_take(db, user, take_id)
    idx = db.scalars(
        select(UploadChunk.index).where(UploadChunk.take_id == t.id).order_by(UploadChunk.index)
    ).all()
    return UploadStatus(take_id=t.id, status=t.status, received=list(idx))


@router.put("/{take_id}/chunks/{index}")
async def put_chunk(
    take_id: uuid.UUID,
    index: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    t = own_take(db, user, take_id)
    if t.kind != "audio":
        raise HTTPException(400, "chunks are for audio takes")
    if t.status != "uploading":
        raise HTTPException(409, f"take is {t.status}")
    if index < 0 or index > 100_000:
        raise HTTPException(400, "bad chunk index")
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty chunk")
    if len(body) > settings.chunk_max_bytes:
        raise HTTPException(413, "chunk too large")
    d = parts_dir(settings, t.id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{index:06d}.part").write_bytes(body)
    row = db.get(UploadChunk, (t.id, index))
    if row is None:
        db.add(UploadChunk(take_id=t.id, index=index, size=len(body)))
    else:
        row.size = len(body)
    db.commit()
    return {"take_id": str(t.id), "index": index, "size": len(body)}


@router.post("/{take_id}/finalize", response_model=TakeOut)
def finalize(
    take_id: uuid.UUID,
    body: TakeFinalize,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> TakeOut:
    t = own_take(db, user, take_id)
    if t.kind != "audio":
        raise HTTPException(400, "finalize is for audio takes")
    if t.status == "finalized" or t.status == "processed":
        return take_out(t)  # idempotent retry
    if t.status != "uploading":
        raise HTTPException(409, f"take is {t.status}")
    received = set(db.scalars(select(UploadChunk.index).where(UploadChunk.take_id == t.id)).all())
    missing = [i for i in range(body.chunk_count) if i not in received]
    if missing:
        raise HTTPException(409, {"missing": missing[:50], "message": "chunks missing"})

    d = parts_dir(settings, t.id)
    rel = final_rel_path(t, "wav")
    final = settings.raw_dir / rel
    final.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    tmp = final.with_suffix(".wav.tmp")
    with tmp.open("wb") as out:
        for i in range(body.chunk_count):
            chunk = (d / f"{i:06d}.part").read_bytes()
            h.update(chunk)
            out.write(chunk)
    digest = h.hexdigest()

    def reject(msg: str) -> TakeOut:
        tmp.unlink(missing_ok=True)
        t.status = "failed"
        t.error = msg
        db.commit()
        raise HTTPException(400, msg)

    if digest != body.sha256.lower():
        reject(f"sha256 mismatch: client {body.sha256[:12]}…, server {digest[:12]}…")
    try:
        info = wav.read_info(tmp)
    except wav.WavError as e:
        reject(f"invalid WAV: {e}")
    if info.sample_rate != t.sample_rate or info.channels != t.channels:
        reject(
            f"WAV header ({info.sample_rate} Hz, {info.channels} ch) does not match the take "
            f"({t.sample_rate} Hz, {t.channels} ch)"
        )
    tmp.rename(final)
    shutil.rmtree(d, ignore_errors=True)
    for row in db.scalars(select(UploadChunk).where(UploadChunk.take_id == t.id)).all():
        db.delete(row)

    t.sha256 = digest
    t.wav_path = rel
    t.total_bytes = final.stat().st_size
    t.bits_per_sample = info.bits_per_sample
    t.duration_s = round(info.duration_s, 4)
    t.quality = body.quality
    t.status = "finalized"
    t.finalized_at = datetime.now(UTC)
    queue.enqueue(db, "wav_probe", {"take_id": str(t.id)})
    db.commit()
    db.expire_all()  # relationships were loaded before this request's writes
    return take_out(own_take(db, user, t.id))


@router.post("/{take_id}/typed", response_model=TakeOut)
def submit_typed(
    take_id: uuid.UUID,
    body: TypedSubmit,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> TakeOut:
    t = own_take(db, user, take_id)
    if t.kind != "typed":
        raise HTTPException(400, "typed submit is for typed takes")
    if t.status != "uploading":
        raise HTTPException(409, f"take is {t.status}")
    rel = final_rel_path(t, "keys.jsonl")
    path = settings.raw_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for k in body.keystrokes:
            f.write(json.dumps(k.model_dump(exclude_none=True), ensure_ascii=False) + "\n")
    db.add(
        TypedResponse(
            take_id=t.id,
            text=body.text,
            keystroke_log_path=rel,
            keystroke_count=len(body.keystrokes),
        )
    )
    t.status = "finalized"
    t.finalized_at = datetime.now(UTC)
    db.commit()
    db.expire_all()
    return take_out(own_take(db, user, t.id))


@router.post("/{take_id}/events", status_code=204)
def add_events(
    take_id: uuid.UUID,
    body: list[EventIn],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    t = own_take(db, user, take_id)
    for e in body[:200]:
        db.add(TakeEvent(take_id=t.id, name=e.name, t_client_ms=e.t_client_ms, meta=e.meta))
    db.commit()


@router.get("/{take_id}/audio")
def get_audio(
    take_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    t = own_take(db, user, take_id)
    if not t.wav_path:
        raise HTTPException(404, "no audio for this take")
    return FileResponse(settings.raw_dir / t.wav_path, media_type="audio/wav")
