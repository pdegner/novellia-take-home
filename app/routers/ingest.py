"""The data-quality surface: what arrived, and what we couldn't make sense of.

Most APIs hide this. Exposing it is deliberate -- the brief promises messy,
unseen data, and an operator's first question when a chart looks wrong is
"did it not arrive, or did it not link?" These two endpoints answer that
without a database console.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import IngestIssue
from app.schemas.common import Page
from app.schemas.ingest import IngestReport, IssueOut
from app.services.ingest_report import build_report

router = APIRouter(prefix="/ingest", tags=["data quality"])


@router.get("/report", response_model=IngestReport)
def ingest_report(session: Session = Depends(get_session)) -> IngestReport:
    """Counts by resource type and by issue code, reconcilable to the line count."""
    return build_report(session)


@router.get("/issues", response_model=Page[IssueOut])
def list_issues(
    session: Session = Depends(get_session),
    code: str | None = Query(None, description="Filter by issue code, e.g. SUBJECT_UNKNOWN_PATIENT"),
    severity: str | None = Query(None, description="warning or error"),
    resource_type: str | None = Query(None),
    limit: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    offset: int = Query(0, ge=0),
) -> Page[IssueOut]:
    """The individual records that were imperfect, and why."""
    filters = []
    if code:
        filters.append(IngestIssue.code == code)
    if severity:
        filters.append(IngestIssue.severity == severity)
    if resource_type:
        filters.append(IngestIssue.resource_type == resource_type)

    total = session.scalar(select(func.count()).select_from(IngestIssue).where(*filters)) or 0

    rows = session.execute(
        select(IngestIssue)
        .where(*filters)
        .order_by(IngestIssue.line_no, IngestIssue.id)
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return Page[IssueOut](
        items=[IssueOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
