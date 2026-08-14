"""Liveness and a one-glance view of what the process has loaded."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import Patient, RawResource

router = APIRouter(tags=["meta"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    return {
        "status": "ok",
        "source_file": settings.data_file,
        "resources_loaded": session.scalar(select(func.count()).select_from(RawResource)) or 0,
        "patients": session.scalar(select(func.count()).select_from(Patient)) or 0,
    }
