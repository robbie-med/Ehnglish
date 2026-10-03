from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import Settings, get_settings
from ..db import get_db
from ..models import User
from ..schemas import MeOut

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    db.execute(text("SELECT 1"))
    return {"ok": True, "env": settings.env, "pipeline_version": settings.pipeline_version}


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)) -> MeOut:
    return MeOut(email=user.email, env=settings.env, role=user.role)
