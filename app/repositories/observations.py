"""SQL access for the `observations` table."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Observation


def list_observations(
    session: Session,
    patient_id: str,
    code: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Observation], int]:
    """Page of a patient's observations matching the filters, plus the total count.

    `min_value`/`max_value` filter on the top-level scalar reading
    (`value_number`), so they don't reach into blood-pressure-style
    component values -- whether that's worth doing is a call for whoever
    calls this with a component code, not this function.

    Eager-loads `components` so `ObservationOut` can serialize blood
    pressure's systolic/diastolic without a lazy query per observation.
    """
    stmt = select(Observation).where(Observation.patient_id == patient_id)

    if code:
        stmt = stmt.where(Observation.code == code)
    if start:
        stmt = stmt.where(Observation.effective_at >= start)
    if end:
        stmt = stmt.where(Observation.effective_at <= end)
    if min_value is not None:
        stmt = stmt.where(Observation.value_number >= min_value)
    if max_value is not None:
        stmt = stmt.where(Observation.value_number <= max_value)

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    stmt = stmt.order_by(Observation.effective_at.desc().nullslast(), Observation.id)
    stmt = stmt.options(selectinload(Observation.components))
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)

    observations = session.execute(stmt).scalars().all()
    return list(observations), total
