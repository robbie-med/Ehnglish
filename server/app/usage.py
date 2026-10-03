"""Cost ledger. Engines report quantities (audio seconds, tokens, characters); prices come from
content/pricing.yaml so they can be corrected without a code change. A context variable carries
the current take/session so deep calls (Claude inside a scorer) can record without plumbing."""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Usage

_ctx: contextvars.ContextVar[Scope | None] = contextvars.ContextVar("usage_scope", default=None)


@dataclass
class Scope:
    db: Session
    session_id: uuid.UUID | None
    take_id: uuid.UUID | None


def set_scope(
    db: Session, session_id: uuid.UUID | None, take_id: uuid.UUID | None
) -> contextvars.Token:
    return _ctx.set(Scope(db, session_id, take_id))


def reset_scope(token: contextvars.Token) -> None:
    _ctx.reset(token)


@lru_cache
def _prices(path: str, mtime: float) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def prices() -> dict:
    p = Path(get_settings().content_dir) / "pricing.yaml"
    return _prices(str(p), p.stat().st_mtime if p.exists() else 0.0)


def price_for(engine: str, unit: str) -> float:
    """USD per unit. Units in pricing.yaml are per minute of audio, per 1M tokens, per 1M chars."""
    rates = prices().get(engine, {})
    if unit == "audio_s":
        return float(rates.get("per_minute_audio", 0.0)) / 60
    if unit == "tokens_in":
        return float(rates.get("per_million_tokens_in", 0.0)) / 1e6
    if unit == "tokens_out":
        return float(rates.get("per_million_tokens_out", 0.0)) / 1e6
    if unit == "chars":
        return float(rates.get("per_million_chars", 0.0)) / 1e6
    return 0.0


def record(
    engine: str,
    unit: str,
    quantity: float,
    *,
    note: str | None = None,
    db: Session | None = None,
    session_id: uuid.UUID | None = None,
    take_id: uuid.UUID | None = None,
) -> float:
    """Record one call. Returns the estimated cost. Silently no-op outside a scope and without db."""
    scope = _ctx.get()
    db = db or (scope.db if scope else None)
    if db is None:
        return 0.0
    if scope:
        session_id = session_id or scope.session_id
        take_id = take_id or scope.take_id
    cost = round(quantity * price_for(engine, unit), 6)
    db.add(
        Usage(
            session_id=session_id,
            take_id=take_id,
            engine=engine,
            unit=unit,
            quantity=round(quantity, 3),
            cost_usd=cost,
            note=note,
        )
    )
    return cost


def session_cost(db: Session, session_id: uuid.UUID) -> dict:
    rows = db.execute(
        select(
            Usage.engine,
            Usage.unit,
            func.sum(Usage.quantity),
            func.sum(Usage.cost_usd),
            func.count(Usage.id),
        )
        .where(Usage.session_id == session_id)
        .group_by(Usage.engine, Usage.unit)
    ).all()
    by_engine: dict[str, dict] = {}
    total = 0.0
    for engine, unit, qty, cost, n in rows:
        e = by_engine.setdefault(engine, {"cost_usd": 0.0, "units": {}, "calls": 0})
        e["cost_usd"] = round(e["cost_usd"] + float(cost), 4)
        e["units"][unit] = round(float(qty), 2)
        e["calls"] += int(n)
        total += float(cost)
    return {
        "total_usd": round(total, 4),
        "by_engine": by_engine,
        "prices_from": "content/pricing.yaml",
    }


def total_cost(db: Session) -> dict:
    rows = db.execute(select(Usage.engine, func.sum(Usage.cost_usd)).group_by(Usage.engine)).all()
    return {
        "total_usd": round(sum(float(c) for _, c in rows), 4),
        "by_engine": {e: round(float(c), 4) for e, c in rows},
    }
