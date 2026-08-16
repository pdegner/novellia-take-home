"""The fidelity escape hatch.

Everything else in this API is translated for a product consumer. This route
hands back the original resource byte-for-byte, for when translation is
wrong: an integration engineer debugging an odd-looking record, or a
downstream system that speaks FHIR directly.

Costs almost nothing -- `raw_resources` already holds every line, including
types we have no handler for. That's what makes "data you haven't seen" a
survivable event, not a data-loss event.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import RawResource
from app.schemas.common import Page

router = APIRouter(prefix="/fhir", tags=["raw fhir"])


@router.get("/{resource_type}/{resource_id}")
def get_raw_resource(
    resource_type: str,
    resource_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """Return the source resource exactly as it arrived."""
    row = session.execute(
        select(RawResource).where(
            RawResource.resource_type == resource_type,
            RawResource.resource_id == resource_id,
        )
    ).scalars().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": f"No {resource_type} with id {resource_id!r} was present in the source data",
            },
        )
    if row.raw_json is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "RESOURCE_UNPARSEABLE",
                "message": f"{resource_type}/{resource_id} was present but is not valid JSON; "
                "see /ingest/issues",
            },
        )
    return row.raw_json


@router.get("/{resource_type}")
def list_raw_resources(
    resource_type: str,
    session: Session = Depends(get_session),
    limit: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    offset: int = Query(0, ge=0),
) -> Page[dict]:
    """List source resources of one type, including types we do not model."""
    where = (RawResource.resource_type == resource_type,)
    total = session.scalar(select(func.count()).select_from(RawResource).where(*where)) or 0
    rows = session.execute(
        select(RawResource).where(*where).order_by(RawResource.line_no).limit(limit).offset(offset)
    ).scalars().all()
    return Page[dict](
        items=[row.raw_json for row in rows if row.raw_json is not None],
        total=total,
        limit=limit,
        offset=offset,
    )
