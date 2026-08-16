"""SQL access for the `procedures` table."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Procedure


def list_procedures(
    session: Session,
    patient_id: str,
    code: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Procedure], int]:
    """Page of a patient's procedures matching the filters, plus the total count.

    No `status` filter -- the public endpoint doesn't take one, and nothing
    else needs it yet. Same `limit=None` convention as the other repositories.
    """
    stmt = select(Procedure).where(Procedure.patient_id == patient_id)

    if code:
        stmt = stmt.where(Procedure.code == code)

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    stmt = stmt.order_by(Procedure.performed_at.desc().nullslast(), Procedure.id)
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)

    procedures = session.execute(stmt).scalars().all()
    return list(procedures), total
