"""SQL access for the `medications` table."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Medication


def list_medications(
    session: Session,
    patient_id: str,
    status: str | None = None,
    code: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Medication], int]:
    """Page of a patient's medications matching the filters, plus the total count.

    Same shape as `conditions.list_conditions`: `limit=None` returns every
    match, unpaginated, so `get_summary` can reuse this instead of writing
    its own "current medications" query.
    """
    stmt = select(Medication).where(Medication.patient_id == patient_id)

    if status:
        stmt = stmt.where(Medication.status == status)
    if code:
        stmt = stmt.where(Medication.code == code)

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    stmt = stmt.order_by(Medication.authored_at.desc().nullslast(), Medication.id)
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)

    medications = session.execute(stmt).scalars().all()
    return list(medications), total
