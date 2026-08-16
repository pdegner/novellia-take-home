"""SQL access for the `notes` table."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Note


def list_notes(
    session: Session,
    patient_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Note], int]:
    """Page of a patient's notes, newest first, plus the total count.

    No filters beyond patient -- notes don't carry a clinical code, and
    nothing has asked for filtering by source_type or status yet.
    """
    stmt = select(Note).where(Note.patient_id == patient_id)

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    stmt = stmt.order_by(Note.authored_at.desc().nullslast(), Note.id)
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)

    notes = session.execute(stmt).scalars().all()
    return list(notes), total
