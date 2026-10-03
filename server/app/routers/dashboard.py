"""Dashboard, export and recording-viewer endpoints (plan §6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import metrics, usage
from ..auth import get_current_user
from ..calibration import load_calibration
from ..config import Settings, get_settings
from ..content import get_forms
from ..db import get_db
from ..models import Take, TestSession, User

router = APIRouter(tags=["dashboard"])

EXPORT_SCHEMA = "assessment_result.v1"


def _subject(db: Session, user: User, settings: Settings, subject: str | None) -> User:
    """The learner is the default subject; anchors may look at themselves or the learner."""
    if subject in (None, "", "learner"):
        learner = None
        if settings.learner_email:
            learner = db.scalar(select(User).where(User.email == settings.learner_email.lower()))
        if learner is None:
            learner = db.scalar(
                select(User).where(User.role == "learner").order_by(User.created_at)
            )
        return learner or user
    if subject == "me":
        return user
    if user.role != "anchor":
        raise HTTPException(403, "only anchors may view other subjects")
    u = db.scalar(select(User).where(User.email == subject.lower()))
    if u is None:
        raise HTTPException(404, "unknown subject")
    return u


def _bundle(db: Session, s: TestSession, forms: dict) -> dict:
    form = forms.get(s.form_id)
    ttype = {t.id: t.type for t in form.tasks} if form else {}
    takes = []
    for t in s.takes:
        if t.status == "rejected":
            continue
        latest: dict[str, Any] = {}
        for r in sorted(t.results, key=lambda r: r.created_at):
            latest[r.kind] = r.result  # newest version wins
        takes.append(
            {
                "id": str(t.id),
                "task_id": t.task_id,
                "item_id": t.item_id,
                "attempt": t.attempt,
                "kind": t.kind,
                "status": t.status,
                "task_type": ttype.get(t.task_id, ""),
                "duration_s": t.duration_s,
                "quality": t.quality,
                "text": t.typed.text if t.typed else None,
                "events": [{"name": e.name, "t_client_ms": e.t_client_ms} for e in t.events],
                "results": latest,
                "pipeline_versions": sorted({r.pipeline_version for r in t.results}),
            }
        )
    srs: dict[str, Any] = {}
    for r in sorted(s.session_results, key=lambda r: r.created_at):
        srs[r.kind] = r.result
    return {
        "session": {
            "id": str(s.id),
            "form_id": s.form_id,
            "form_version": s.form_version,
            "form_kind": form.kind if form else "dummy",
            "status": s.status,
            "started_at": s.started_at.isoformat(),
            "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            "takes": len(takes),
            "items_total": sum(len(t.items) for t in form.tasks) if form else None,
            "items_done": len(
                {
                    (t["task_id"], t["item_id"])
                    for t in takes
                    if t["status"] in ("finalized", "processed")
                }
            ),
            "processed": sum(1 for t in takes if t["status"] == "processed"),
            "headphone_override": bool(((s.setup or {}).get("headphones") or {}).get("override")),
            "mic": (s.setup or {}).get("deviceLabel"),
        },
        "setup": s.setup or {},
        "client": s.client or {},
        "takes": takes,
        "session_results": srs,
    }


def _sessions(db: Session, user: User) -> list[TestSession]:
    """Every sitting of this user that has at least one take, finished or not (status is reported)."""
    return [
        s
        for s in db.scalars(
            select(TestSession)
            .where(TestSession.user_id == user.id)
            .order_by(TestSession.started_at)
            .options(
                selectinload(TestSession.takes).selectinload(Take.results),
                selectinload(TestSession.takes).selectinload(Take.events),
                selectinload(TestSession.takes).selectinload(Take.typed),
                selectinload(TestSession.session_results),
            )
            .execution_options(populate_existing=True)
        ).all()
        if any(t.status != "rejected" for t in s.takes)
    ]


def _anchor_means(db: Session, forms: dict, form_id: str) -> dict[str, float]:
    """Mean of each metric over all anchor sessions on the same form (plan §7)."""
    anchors = db.scalars(select(User).where(User.role == "anchor")).all()
    acc: dict[str, list[float]] = {}
    for a in anchors:
        for s in _sessions(db, a):
            if s.form_id != form_id or s.status != "done":
                continue
            b = _bundle(db, s, forms)
            for mid, mv in metrics.evaluate(b, b["session"]["form_kind"]).items():
                if mv.value is not None:
                    acc.setdefault(mid, []).append(mv.value)
    return {mid: sum(v) / len(v) for mid, v in acc.items()}


@router.get("/dashboard")
def dashboard(
    subject: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    forms = get_forms(str(settings.content_dir))
    who = _subject(db, user, settings, subject)
    sessions = _sessions(db, who)
    anchor_cache: dict[str, dict[str, float]] = {}
    per_session = []
    series: dict[str, list[dict]] = {}
    latest_by_metric: dict[str, dict] = {}
    for s in sessions:
        b = _bundle(db, s, forms)
        kind = b["session"]["form_kind"]
        vals = metrics.evaluate(b, kind)
        if who.role != "anchor":
            if s.form_id not in anchor_cache:
                anchor_cache[s.form_id] = _anchor_means(db, forms, s.form_id)
            metrics.apply_anchor(vals, anchor_cache[s.form_id])
        row = {
            "session": b["session"],
            "metrics": {mid: mv.to_dict() for mid, mv in vals.items()},
            "estimates": [
                metrics.estimate_skill(sk, vals)
                for sk in ("speaking", "listening", "reading", "writing")
            ],
        }
        per_session.append(row)
        for mid, mv in vals.items():
            series.setdefault(mid, []).append(
                {
                    "session_id": str(s.id),
                    "form_id": s.form_id,
                    "started_at": b["session"]["started_at"],
                    "value": mv.value,
                    "ci95": mv.ci95,
                    "scale": mv.scale,
                }
            )
            latest_by_metric[mid] = {
                **mv.to_dict(),
                "session_id": str(s.id),
                "form_id": s.form_id,
                "started_at": b["session"]["started_at"],
            }
    noise = metrics.retest_noise(
        [
            {
                "form_id": r["session"]["form_id"],
                "started_at": r["session"]["started_at"],
                "metrics": {k: v["value"] for k, v in r["metrics"].items()},
            }
            for r in per_session
        ]
    )
    trends = {mid: metrics.trend(pts, noise.get(mid)) for mid, pts in series.items()}
    calib = load_calibration(settings.content_dir)
    offsets = metrics.calibration_offsets(
        calib.get("external", []),
        [
            (r["session"]["started_at"], {e["skill"]: e["cefr"] for e in r["estimates"]})
            for r in per_session
        ],
    )
    for r in per_session:
        r["estimates"] = [
            metrics.apply_offset(e, offsets.get(e["skill"], 0)) for e in r["estimates"]
        ]
    domains: dict[str, list[dict]] = {}
    for m in metrics.METRICS:
        if m.id in latest_by_metric:
            domains.setdefault(m.domain, []).append(
                {
                    "id": m.id,
                    "unit": m.unit,
                    "direction": m.direction,
                    "definition": {"en": m.en, "ko": m.ko},
                    "latest": latest_by_metric[m.id],
                    "trend": trends.get(m.id),
                }
            )
    latest_estimates = per_session[-1]["estimates"] if per_session else []
    # best estimate per skill across the most recent session of each kind
    est: dict[str, dict] = {}
    for row in per_session:
        for e in row["estimates"]:
            if e["cefr"]:
                est[e["skill"]] = {
                    **e,
                    "session_id": row["session"]["id"],
                    "form_id": row["session"]["form_id"],
                }
    return {
        "subject": {"email": who.email, "role": who.role},
        "viewer": {"email": user.email, "role": user.role},
        "sessions": [r["session"] for r in per_session],
        "domains": domains,
        "estimates": list(est.values()) or latest_estimates,
        "per_session": per_session,
        "anchors_available": {fid: bool(v) for fid, v in anchor_cache.items()},
        "retest_noise": noise,
        "costs": (
            {
                "sessions": {str(s.id): usage.session_cost(db, s.id) for s in sessions},
                "all_time": usage.total_cost(db),
            }
            if user.email.lower() in settings.owner_email_set
            else None
        ),
        "calibration": {"external": calib.get("external", []), "offsets": offsets},
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/sessions/{session_id}/export")
def export_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    """assessment_result.v1.json: the contract with the Trainer (plan §6.2)."""
    s = db.scalar(
        select(TestSession)
        .where(TestSession.id == session_id)
        .options(
            selectinload(TestSession.takes).selectinload(Take.results),
            selectinload(TestSession.takes).selectinload(Take.events),
            selectinload(TestSession.takes).selectinload(Take.typed),
            selectinload(TestSession.session_results),
        )
        .execution_options(populate_existing=True)
    )
    if s is None or (s.user_id != user.id and user.role != "anchor"):
        raise HTTPException(404, "session not found")
    forms = get_forms(str(settings.content_dir))
    b = _bundle(db, s, forms)
    vals = metrics.evaluate(b, b["session"]["form_kind"])
    owner = db.get(User, s.user_id)
    if owner and owner.role != "anchor":
        metrics.apply_anchor(vals, _anchor_means(db, forms, s.form_id))
    return {
        "schema": EXPORT_SCHEMA,
        "exported_at": datetime.now(UTC).isoformat(),
        "subject": {"email": owner.email if owner else None, "role": owner.role if owner else None},
        "pipeline_versions": sorted({v for t in b["takes"] for v in t["pipeline_versions"]}),
        **b,
        "metrics": {
            mid: {
                **mv.to_dict(),
                "unit": metrics.BY_ID[mid].unit,
                "direction": metrics.BY_ID[mid].direction,
                "domain": metrics.BY_ID[mid].domain,
                "definition": {"en": metrics.BY_ID[mid].en, "ko": metrics.BY_ID[mid].ko},
            }
            for mid, mv in vals.items()
        },
        "estimates": [
            metrics.estimate_skill(sk, vals)
            for sk in ("speaking", "listening", "reading", "writing")
        ],
    }


@router.get("/takes/{take_id}/viewer")
def take_viewer(
    take_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Word timings, pauses and phoneme mismatches for the recording viewer (plan §6.1)."""
    t = db.scalar(
        select(Take)
        .join(TestSession)
        .where(Take.id == take_id)
        .options(selectinload(Take.results), selectinload(Take.events))
        .execution_options(populate_existing=True)
    )
    if t is None:
        raise HTTPException(404, "take not found")
    owner = db.get(TestSession, t.session_id)
    if owner is None or (owner.user_id != user.id and user.role != "anchor"):
        raise HTTPException(404, "take not found")
    latest: dict[str, Any] = {}
    for r in sorted(t.results, key=lambda r: r.created_at):
        latest[r.kind] = r.result
    words = []
    al = latest.get("alignment") or {}
    if al.get("words"):
        words = [
            {"text": w["word"], "start": w["start"], "end": w["end"], "uncertain": False}
            for w in al["words"]
        ]
    else:
        tr = latest.get("transcript") or {}
        words = [
            {
                "text": w["text"],
                "start": w.get("start"),
                "end": w.get("end"),
                "uncertain": w.get("uncertain", False),
            }
            for w in tr.get("words", [])
        ]
    pron = latest.get("pron") or {}
    mismatches = [
        {
            "word": w["word"],
            "accuracy": w.get("accuracy"),
            "error_type": w.get("error_type"),
            "start": w.get("start"),
            "end": w.get("end"),
            "phonemes": [p for p in w.get("phonemes", []) if (p.get("accuracy") or 100) < 60],
        }
        for w in pron.get("words", [])
        if w.get("error_type") or (w.get("accuracy") is not None and w["accuracy"] < 60)
    ]
    timing = latest.get("timing") or {}
    return {
        "take_id": str(t.id),
        "task_id": t.task_id,
        "item_id": t.item_id,
        "duration_s": t.duration_s,
        "audio_url": f"/api/takes/{t.id}/audio",
        "words": words,
        "pauses": timing.get("pauses", []),
        "nuclei": timing.get("nuclei", []),
        "mismatches": mismatches,
        "phonemes": {
            k: v
            for k, v in (latest.get("phonemes") or {}).items()
            if k in ("confusions", "contrast_errors", "extra_vowels", "per")
        },
        "quality": t.quality,
        "events": [{"name": e.name, "t_client_ms": e.t_client_ms} for e in t.events],
    }
