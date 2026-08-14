"""Patient-centric endpoints -- the primary product surface.

Routing only: parse, delegate, wrap. Every route here is a thin call into
app.services.patients.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.schemas.clinical import (
    ConditionOut,
    MedicationOut,
    NoteOut,
    ObservationOut,
    PatientListItem,
    PatientOut,
    PatientSummary,
    ProcedureOut,
    TimelineEvent,
)
from app.schemas.common import Page
from app.services import patients as service

router = APIRouter(prefix="/patients", tags=["patients"])

Limit = Query(settings.default_page_size, ge=1, le=settings.max_page_size)
Offset = Query(0, ge=0)


@router.get("", response_model=Page[PatientListItem])
def list_patients(
    session: Session = Depends(get_session),
    name: str | None = Query(None, description="Case-insensitive match on any part of the name"),
    gender: str | None = Query(None),
    limit: int = Limit,
    offset: int = Offset,
) -> Page[PatientListItem]:
    items, total = service.list_patients(session, name, gender, limit, offset)
    return Page[PatientListItem](items=items, total=total, limit=limit, offset=offset)


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: str, session: Session = Depends(get_session)) -> PatientOut:
    return service.get_patient(session, patient_id)


@router.get("/{patient_id}/summary", response_model=PatientSummary)
def get_summary(patient_id: str, session: Session = Depends(get_session)) -> PatientSummary:
    """Everything a chart view needs, in one request."""
    return service.get_summary(session, patient_id)


@router.get("/{patient_id}/timeline", response_model=Page[TimelineEvent])
def get_timeline(
    patient_id: str,
    session: Session = Depends(get_session),
    kind: list[str] | None = Query(
        None, description="Repeatable. condition | medication | observation | procedure | note"
    ),
    start: datetime | None = Query(None, description="Inclusive lower bound"),
    end: datetime | None = Query(None, description="Inclusive upper bound"),
    limit: int = Limit,
    offset: int = Offset,
) -> Page[TimelineEvent]:
    """Every dated record for this patient, merged and ordered."""
    items, total = service.get_timeline(session, patient_id, kind, start, end, limit, offset)
    return Page[TimelineEvent](items=items, total=total, limit=limit, offset=offset)


@router.get("/{patient_id}/conditions", response_model=Page[ConditionOut])
def list_conditions(
    patient_id: str,
    session: Session = Depends(get_session),
    status: str | None = Query(None, description="active | resolved | remission"),
    code: str | None = Query(None, description="SNOMED code"),
    limit: int = Limit,
    offset: int = Offset,
) -> Page[ConditionOut]:
    items, total = service.list_conditions(session, patient_id, status, code, limit, offset)
    return Page[ConditionOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/{patient_id}/medications", response_model=Page[MedicationOut])
def list_medications(
    patient_id: str,
    session: Session = Depends(get_session),
    status: str | None = Query(None),
    code: str | None = Query(None, description="RxNorm code"),
    limit: int = Limit,
    offset: int = Offset,
) -> Page[MedicationOut]:
    items, total = service.list_medications(session, patient_id, status, code, limit, offset)
    return Page[MedicationOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/{patient_id}/observations", response_model=Page[ObservationOut])
def list_observations(
    patient_id: str,
    session: Session = Depends(get_session),
    code: str | None = Query(None, description="LOINC code"),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    min_value: float | None = Query(None, description="Only meaningful alongside `code`"),
    max_value: float | None = Query(None, description="Only meaningful alongside `code`"),
    limit: int = Limit,
    offset: int = Offset,
) -> Page[ObservationOut]:
    items, total = service.list_observations(
        session, patient_id, code, start, end, min_value, max_value, limit, offset
    )
    return Page[ObservationOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/{patient_id}/procedures", response_model=Page[ProcedureOut])
def list_procedures(
    patient_id: str,
    session: Session = Depends(get_session),
    code: str | None = Query(None, description="SNOMED code"),
    limit: int = Limit,
    offset: int = Offset,
) -> Page[ProcedureOut]:
    items, total = service.list_procedures(session, patient_id, code, limit, offset)
    return Page[ProcedureOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/{patient_id}/notes", response_model=Page[NoteOut])
def list_notes(
    patient_id: str,
    session: Session = Depends(get_session),
    limit: int = Limit,
    offset: int = Offset,
) -> Page[NoteOut]:
    """Notes from both source shapes, already decoded to text."""
    items, total = service.list_notes(session, patient_id, limit, offset)
    return Page[NoteOut](items=items, total=total, limit=limit, offset=offset)
