"""SQL access for the `conditions` table."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Condition


def list_conditions(
    session: Session,
    patient_id: str,
    status: str | None = None,
    code: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Condition], int]:
    """Page of a patient's conditions matching the filters, plus the total count.

    `limit=None` returns every match, unpaginated -- what `get_summary` wants
    ("all active conditions"), reusing the same query the list endpoint uses
    so the two views can't drift apart.
    """
    stmt = select(Condition).where(Condition.patient_id == patient_id)

    if status:
        stmt = stmt.where(Condition.clinical_status == status)
    if code:
        stmt = stmt.where(Condition.code == code)

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    stmt = stmt.order_by(Condition.onset_at.desc().nullslast(), Condition.id)
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)

    conditions = session.execute(stmt).scalars().all()
    return list(conditions), total
