"""SQL access for the `patients` table."""

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models import Patient


def list_patients(
    session: Session,
    name: str | None = None,
    gender: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Patient], int]:
    """Page of patients matching the filters, plus the total match count.

    `name` is matched case-insensitively as a substring of the family name,
    given names, or rendered display name.
    """
    stmt = select(Patient)

    if name and name.strip():
        pattern = f"%{name.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Patient.family_name).like(pattern),
                func.lower(Patient.display_name).like(pattern),
                # given_names is a JSON array. SQLite has no case-insensitive
                # "any element contains" operator, so this matches against
                # the array's serialized text instead -- correct for a plain
                # name substring, which is all this filter promises.
                func.lower(cast(Patient.given_names, String)).like(pattern),
            )
        )

    if gender and gender.strip():
        stmt = stmt.where(func.lower(Patient.gender) == gender.strip().lower())

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    stmt = stmt.order_by(Patient.family_name, Patient.display_name, Patient.id)
    patients = session.execute(stmt.offset(offset).limit(limit)).scalars().all()
    return list(patients), total


def get_patient(session: Session, patient_id: str) -> Patient | None:
    """Fetch one patient, tolerant of case (matches the ingest resolution ladder).

    Looks up `id_normalized` rather than `id` so `NOAH-WYLE` finds the same row
    as `noah-wyle` -- the reference ladder already extends this courtesy to
    resources being linked, so the public API extends it to callers too.
    """
    stmt = select(Patient).where(Patient.id_normalized == patient_id.strip().lower())
    return session.execute(stmt).scalar_one_or_none()
