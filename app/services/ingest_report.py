"""Aggregates the provenance tables into the data-quality view."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Condition,
    IngestIssue,
    Medication,
    Note,
    Observation,
    Procedure,
    RawResource,
    RawStatus,
    Severity,
)
from app.schemas.ingest import CodeCount, IngestReport, TypeBreakdown

# Every table where a row may legitimately sit unlinked from a patient.
CLINICAL_MODELS = (Condition, Medication, Observation, Procedure, Note)


def build_report(session: Session) -> IngestReport:
    status_rows = session.execute(
        select(RawResource.resource_type, RawResource.status, func.count())
        .group_by(RawResource.resource_type, RawResource.status)
    ).all()

    breakdown: dict[str, TypeBreakdown] = {}
    totals = {RawStatus.ACCEPTED: 0, RawStatus.REJECTED: 0, RawStatus.UNKNOWN_TYPE: 0}
    for resource_type, status, count in status_rows:
        key = resource_type or "(unparseable)"
        entry = breakdown.setdefault(key, TypeBreakdown(resource_type=key))
        setattr(entry, status, getattr(entry, status) + count)
        totals[status] = totals.get(status, 0) + count

    issue_rows = session.execute(
        select(IngestIssue.code, IngestIssue.severity, func.count())
        .group_by(IngestIssue.code, IngestIssue.severity)
        .order_by(func.count().desc())
    ).all()

    linked = 0
    orphaned = 0
    for model in CLINICAL_MODELS:
        linked += session.scalar(
            select(func.count()).select_from(model).where(model.patient_id.is_not(None))
        ) or 0
        orphaned += session.scalar(
            select(func.count()).select_from(model).where(model.patient_id.is_(None))
        ) or 0

    return IngestReport(
        source_file=settings.data_file,
        total_lines=sum(totals.values()),
        accepted=totals.get(RawStatus.ACCEPTED, 0),
        rejected=totals.get(RawStatus.REJECTED, 0),
        unknown_type=totals.get(RawStatus.UNKNOWN_TYPE, 0),
        linked_records=linked,
        orphaned_records=orphaned,
        errors=sum(c for _, sev, c in issue_rows if sev == Severity.ERROR),
        warnings=sum(c for _, sev, c in issue_rows if sev == Severity.WARNING),
        by_type=sorted(breakdown.values(), key=lambda b: b.resource_type),
        by_issue_code=[
            CodeCount(code=code, severity=severity, count=count)
            for code, severity, count in issue_rows
        ],
    )
