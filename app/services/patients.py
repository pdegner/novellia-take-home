"""Query and assembly logic behind the patient-facing endpoints.

Routers do HTTP; this module does clinical meaning. That split is what makes
the "add a feature live" request cheap -- a new endpoint is usually a new
function here plus four lines of routing.
"""

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.exceptions import InvalidQueryError, PatientNotFoundError
from app.ingest.normalize import render_temporal
from app.models import Condition, Medication, Note, Observation, ObservationComponent, Patient, Procedure
from app.repositories import conditions as conditions_repo
from app.repositories import medications as medications_repo
from app.repositories import notes as notes_repo
from app.repositories import observations as observations_repo
from app.repositories import patients as repo
from app.repositories import procedures as procedures_repo
from app.schemas.clinical import (
    CodeOut,
    ConditionOut,
    MedicationOut,
    NoteOut,
    ObservationComponentOut,
    ObservationOut,
    PatientListItem,
    PatientOut,
    PatientSummary,
    ProcedureOut,
    TemporalOut,
    TimelineEvent,
)


def _resolve_patient_id(session: Session, patient_id: str) -> str:
    """Confirm the patient exists and return their canonical id.

    Two jobs, and both matter: raise PatientNotFoundError up front rather
    than let a bad id fall through to an empty-looking list (`/patients
    /typo123/conditions` and `/patients/noah-wyle/conditions` for a real
    patient with none would otherwise both return `[]`). And return the
    *stored* id, not whatever case the caller used -- `patient_id` foreign
    keys are always the canonical form (`resolve_subject` stores `patient.id`,
    never the raw reference), so looking up `NOAH-WYLE`'s conditions with the
    literal string `"NOAH-WYLE"` would silently match nothing.
    """
    patient = repo.get_patient(session, patient_id)
    if patient is None:
        raise PatientNotFoundError(patient_id)
    return patient.id


def _code_out(code_system: str | None, code: str | None, display: str | None, text: str | None) -> CodeOut:
    return CodeOut(system=code_system, code=code, display=display or text)


def _temporal_out(at: datetime | None, precision: str | None) -> TemporalOut | None:
    if at is None:
        return None
    return TemporalOut(value=render_temporal(at, precision), precision=precision, timestamp=at)


def _age(birth_date: date | None) -> int | None:
    """Whole years as of today, not just year subtraction.

    `today < (month, day)` catches the case where the birthday hasn't
    happened yet this year -- someone born 2000-12-01 isn't 26 in March.
    """
    if birth_date is None:
        return None
    today = date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def _to_patient_out(patient: Patient) -> PatientOut:
    return PatientOut(
        id=patient.id,
        name=patient.display_name,
        family_name=patient.family_name,
        given_names=patient.given_names or [],
        gender=patient.gender,
        birth_date=patient.birth_date,
        age=_age(patient.birth_date),
        active=patient.active,
    )


def _record_count(patient: Patient) -> int:
    """How much data exists on this person, across every category.

    Reads the ORM relationships rather than a SQL count -- five lazy-loaded
    queries per patient on a page. Fine at this dataset's size; a join-based
    aggregate in the repository is the fix if the patient count ever grows
    past what fits on a screen.
    """
    return (
        len(patient.conditions)
        + len(patient.medications)
        + len(patient.observations)
        + len(patient.procedures)
        + len(patient.notes)
    )


def _to_list_item(patient: Patient) -> PatientListItem:
    return PatientListItem(
        id=patient.id,
        name=patient.display_name,
        gender=patient.gender,
        birth_date=patient.birth_date,
        record_count=_record_count(patient),
    )


def _to_condition_out(condition: Condition) -> ConditionOut:
    code = _code_out(condition.code_system, condition.code, condition.display, condition.text)
    return ConditionOut(
        id=condition.id,
        code=code,
        label=code.display,
        clinical_status=condition.clinical_status,
        verification_status=condition.verification_status,
        onset=_temporal_out(condition.onset_at, condition.onset_precision),
        abatement=_temporal_out(condition.abatement_at, condition.abatement_precision),
        recorded_by=condition.recorder_display or condition.recorder_ref,
    )


def _to_medication_out(medication: Medication) -> MedicationOut:
    code = _code_out(medication.code_system, medication.code, medication.display, medication.text)
    return MedicationOut(
        id=medication.id,
        code=code,
        label=code.display,
        status=medication.status,
        intent=medication.intent,
        authored=_temporal_out(medication.authored_at, medication.authored_precision),
        prescribed_by=medication.requester_display or medication.requester_ref,
        dosage=medication.dosage_text,
    )


def _to_observation_component_out(component: ObservationComponent) -> ObservationComponentOut:
    code = _code_out(component.code_system, component.code, component.display, None)
    return ObservationComponentOut(
        code=code,
        label=code.display,
        value=component.value_number,
        unit=component.value_unit,
        unit_canonical=component.value_unit_canonical,
    )


def _to_observation_out(observation: Observation) -> ObservationOut:
    code = _code_out(observation.code_system, observation.code, observation.display, observation.text)
    return ObservationOut(
        id=observation.id,
        code=code,
        label=code.display,
        status=observation.status,
        effective=_temporal_out(observation.effective_at, observation.effective_precision),
        value_kind=observation.value_kind,
        value=observation.value_number,
        unit=observation.value_unit,
        unit_canonical=observation.value_unit_canonical,
        value_text=observation.value_string,
        components=[_to_observation_component_out(c) for c in observation.components],
    )


def _to_procedure_out(procedure: Procedure) -> ProcedureOut:
    code = _code_out(procedure.code_system, procedure.code, procedure.display, procedure.text)
    return ProcedureOut(
        id=procedure.id,
        code=code,
        label=code.display,
        status=procedure.status,
        performed=_temporal_out(procedure.performed_at, procedure.performed_precision),
        performed_by=procedure.performer_display or procedure.performer_ref,
    )


def _to_note_out(note: Note) -> NoteOut:
    # Note has no `type_system` column -- DocumentReference.type never needed
    # one for the sample file, so system is always None here, not looked up.
    note_type = (
        CodeOut(system=None, code=note.type_code, display=note.type_display)
        if note.type_code or note.type_display
        else None
    )
    return NoteOut(
        id=note.id,
        source_type=note.source_type,
        type=note_type,
        status=note.status,
        authored=_temporal_out(note.authored_at, note.authored_precision),
        author=note.author_ref,
        text=note.text,
        text_unavailable_reason=note.text_unavailable_reason,
    )


def list_patients(
    session: Session,
    name: str | None = None,
    gender: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PatientListItem], int]:
    """List patients with a total count for pagination.

    `name` matches family, given, or display name, case-insensitive.
    """
    patients, total = repo.list_patients(session, name, gender, limit, offset)
    return [_to_list_item(patient) for patient in patients], total


def get_patient(session: Session, patient_id: str) -> PatientOut:
    """Fetch one patient. Raises PatientNotFoundError.

    Accepts `NOAH-WYLE` as well as `noah-wyle`: the ingest ladder already
    tolerates case in *references*, and refusing it in the public API would
    be a different, harder-to-defend rule for the same identifier. Cheap to
    do -- `repo.get_patient` matches on the indexed `id_normalized` column.
    """
    patient = repo.get_patient(session, patient_id)
    if patient is None:
        raise PatientNotFoundError(patient_id)
    return _to_patient_out(patient)


def _latest_by_code(observations: list[Observation]) -> list[Observation]:
    """One observation per distinct code -- the first one seen.

    Leans on `observations_repo.list_observations` already sorting
    newest-first with nulls last: the first occurrence of a code in that
    order is the latest reading, so no date comparison happens here. That's
    a real coupling, not just an optimization -- if that repo's ordering
    ever changed, this would silently return the wrong reading instead of
    erroring.
    """
    seen: set[str | None] = set()
    latest: list[Observation] = []
    for observation in observations:
        if observation.code in seen:
            continue
        seen.add(observation.code)
        latest.append(observation)
    return latest


def get_summary(session: Session, patient_id: str) -> PatientSummary:
    """Assemble the chart view.

    Decisions this function embodies, all fair game in review:

    * **Active vs resolved conditions** split on `clinical_status`. Only one
      sample record has `abatementDateTime`, so status is the reliable
      signal, not an end date's presence. "Resolved" here means "not active"
      -- remission and inactive land in that bucket too, since the schema
      only has two buckets and a condition disappearing from the summary
      entirely would be worse than an imprecise label.
    * **Latest vitals** means the most recent reading per observation code --
      not the most recent N observations, which would show three blood
      pressures and no weight. Grouping by code is what makes it a chart, not
      a log.
    * **Ordering** is newest-first everywhere; a chart view is about the
      present. The timeline endpoint is where history reads chronologically.
    * Records with `status = "entered-in-error"` shouldn't appear in a
      summary. Nothing in the sample file has that status, which is exactly
      why it's worth handling now. For conditions that's `verification_status`,
      not `clinical_status` -- FHIR puts "entered-in-error" on verification,
      not on the active/resolved axis.
    * **`recent_notes`** caps at 5. Nothing pins the number down; a chart
      view wants a taste, not the full history -- `/patients/{id}/notes`
      is where the rest lives.
    * **`counts`** are unfiltered totals per category (same relationship-
      length approach as `PatientListItem.record_count`), not counts of what
      made it into the buckets above -- it answers "how much data exists",
      not "how much is shown".
    """
    patient = repo.get_patient(session, patient_id)
    if patient is None:
        raise PatientNotFoundError(patient_id)
    canonical_id = patient.id

    conditions, _ = conditions_repo.list_conditions(session, canonical_id, limit=None)
    conditions = [c for c in conditions if c.verification_status != "entered-in-error"]
    active_conditions = [c for c in conditions if c.clinical_status == "active"]
    resolved_conditions = [c for c in conditions if c.clinical_status != "active"]

    medications, _ = medications_repo.list_medications(session, canonical_id, status="active", limit=None)

    observations, _ = observations_repo.list_observations(session, canonical_id, limit=None)
    observations = [o for o in observations if o.status != "entered-in-error"]
    latest_vitals = _latest_by_code(observations)

    notes, _ = notes_repo.list_notes(session, canonical_id, limit=5)

    return PatientSummary(
        patient=_to_patient_out(patient),
        active_conditions=[_to_condition_out(c) for c in active_conditions],
        resolved_conditions=[_to_condition_out(c) for c in resolved_conditions],
        current_medications=[_to_medication_out(m) for m in medications],
        latest_vitals=[_to_observation_out(o) for o in latest_vitals],
        recent_notes=[_to_note_out(n) for n in notes],
        counts={
            "conditions": len(patient.conditions),
            "medications": len(patient.medications),
            "observations": len(patient.observations),
            "procedures": len(patient.procedures),
            "notes": len(patient.notes),
        },
    )


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """Match `parse_fhir_datetime`'s storage convention for `start`/`end`.

    Stored timestamps are naive UTC. A client's `start`/`end` query param can
    arrive timezone-aware (FastAPI parses a trailing `Z` into one), and
    comparing aware to naive raises instead of filtering -- the same trap
    `parse_fhir_datetime` already dodges on the way in.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _truncate(text: str | None, limit: int = 140) -> str | None:
    if not text:
        return None
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _condition_event(condition: Condition) -> TimelineEvent | None:
    occurred = _temporal_out(condition.onset_at, condition.onset_precision)
    if occurred is None:
        return None
    out = _to_condition_out(condition)
    return TimelineEvent(
        kind="condition", id=condition.id, occurred=occurred,
        label=out.label, summary=out.label, detail=out.model_dump(mode="json"),
    )


def _medication_event(medication: Medication) -> TimelineEvent | None:
    occurred = _temporal_out(medication.authored_at, medication.authored_precision)
    if occurred is None:
        return None
    out = _to_medication_out(medication)
    return TimelineEvent(
        kind="medication", id=medication.id, occurred=occurred,
        label=out.label, summary=out.label, detail=out.model_dump(mode="json"),
    )


def _observation_summary(out: ObservationOut) -> str | None:
    """A reading, not just a name -- "Heart rate" alone is useless in a feed."""
    if out.value_kind == "quantity" and out.value is not None:
        unit = f" {out.unit}" if out.unit else ""
        return f"{out.value:g}{unit}"
    if out.value_kind == "string":
        return out.value_text or out.label
    if out.value_kind == "component" and out.components:
        parts = [
            f"{component.label or 'value'} {component.value:g}"
            f"{f' {component.unit}' if component.unit else ''}"
            for component in out.components
            if component.value is not None
        ]
        if parts:
            return ", ".join(parts)
    return out.label


def _observation_event(observation: Observation) -> TimelineEvent | None:
    occurred = _temporal_out(observation.effective_at, observation.effective_precision)
    if occurred is None:
        return None
    out = _to_observation_out(observation)
    return TimelineEvent(
        kind="observation", id=observation.id, occurred=occurred,
        label=out.label, summary=_observation_summary(out), detail=out.model_dump(mode="json"),
    )


def _procedure_event(procedure: Procedure) -> TimelineEvent | None:
    occurred = _temporal_out(procedure.performed_at, procedure.performed_precision)
    if occurred is None:
        return None
    out = _to_procedure_out(procedure)
    return TimelineEvent(
        kind="procedure", id=procedure.id, occurred=occurred,
        label=out.label, summary=out.label, detail=out.model_dump(mode="json"),
    )


def _note_event(note: Note) -> TimelineEvent | None:
    occurred = _temporal_out(note.authored_at, note.authored_precision)
    if occurred is None:
        return None
    out = _to_note_out(note)
    label = (out.type.display if out.type else None) or "Note"
    return TimelineEvent(
        kind="note", id=note.id, occurred=occurred,
        label=label, summary=_truncate(out.text), detail=out.model_dump(mode="json"),
    )


_TIMELINE_KINDS = ("condition", "medication", "observation", "procedure", "note")


def get_timeline(
    session: Session,
    patient_id: str,
    kinds: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[TimelineEvent], int]:
    """Merge every dated record for a patient into one chronological stream.

    The subtlety: a date-only onset and a timestamped observation on the same
    day still have to sort against each other. Sorting on the normalized
    `timestamp` puts the date-only record at 00:00, first -- a defensible
    convention, but a convention. The `precision` field on every event is
    what stops it becoming a lie.

    Oldest-first, unlike everywhere else in this module -- `get_summary`'s
    docstring calls this out explicitly: a chart view is about the present
    (newest-first), a timeline is a history read start to finish.

    A record with no date at all can't appear -- `TimelineEvent.occurred` is
    required, not optional. It still shows up via the plain list endpoints;
    it just can't be placed on a timeline with nothing to place it at.

    Raises PatientNotFoundError.
    """
    patient = repo.get_patient(session, patient_id)
    if patient is None:
        raise PatientNotFoundError(patient_id)
    canonical_id = patient.id

    wanted = set(kinds) if kinds else set(_TIMELINE_KINDS)

    events: list[TimelineEvent] = []

    if "condition" in wanted:
        conditions, _ = conditions_repo.list_conditions(session, canonical_id, limit=None)
        events += [event for c in conditions if (event := _condition_event(c))]

    if "medication" in wanted:
        medications, _ = medications_repo.list_medications(session, canonical_id, limit=None)
        events += [event for m in medications if (event := _medication_event(m))]

    if "observation" in wanted:
        observations, _ = observations_repo.list_observations(session, canonical_id, limit=None)
        events += [event for o in observations if (event := _observation_event(o))]

    if "procedure" in wanted:
        procedures, _ = procedures_repo.list_procedures(session, canonical_id, limit=None)
        events += [event for p in procedures if (event := _procedure_event(p))]

    if "note" in wanted:
        notes, _ = notes_repo.list_notes(session, canonical_id, limit=None)
        events += [event for n in notes if (event := _note_event(n))]

    lower_bound = _to_naive_utc(start)
    upper_bound = _to_naive_utc(end)
    if lower_bound is not None:
        events = [e for e in events if e.occurred.timestamp >= lower_bound]
    if upper_bound is not None:
        events = [e for e in events if e.occurred.timestamp <= upper_bound]

    events.sort(key=lambda e: e.occurred.timestamp)

    total = len(events)
    page = events[offset : offset + limit]
    return page, total


def list_conditions(
    session: Session,
    patient_id: str,
    status: str | None = None,
    code: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ConditionOut], int]:
    """List a patient's conditions. Raises PatientNotFoundError."""
    patient_id = _resolve_patient_id(session, patient_id)
    conditions, total = conditions_repo.list_conditions(session, patient_id, status, code, limit, offset)
    return [_to_condition_out(c) for c in conditions], total


def list_medications(
    session: Session,
    patient_id: str,
    status: str | None = None,
    code: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MedicationOut], int]:
    """List a patient's medications. Raises PatientNotFoundError."""
    patient_id = _resolve_patient_id(session, patient_id)
    medications, total = medications_repo.list_medications(session, patient_id, status, code, limit, offset)
    return [_to_medication_out(m) for m in medications], total


def list_observations(
    session: Session,
    patient_id: str,
    code: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ObservationOut], int]:
    """Value filtering is why `value_unit_canonical` exists.

    `min_value`/`max_value` only make sense within a single code -- comparing
    glucose to heart rate is nonsense, so a value filter without `code` is
    rejected outright rather than silently returning a meaningless mix.

    Raises PatientNotFoundError, or InvalidQueryError for the case above.
    """
    patient_id = _resolve_patient_id(session, patient_id)
    if (min_value is not None or max_value is not None) and code is None:
        raise InvalidQueryError("min_value/max_value require a code filter")
    observations, total = observations_repo.list_observations(
        session, patient_id, code, start, end, min_value, max_value, limit, offset
    )
    return [_to_observation_out(o) for o in observations], total


def list_procedures(
    session: Session,
    patient_id: str,
    code: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ProcedureOut], int]:
    """List a patient's procedures. Raises PatientNotFoundError."""
    patient_id = _resolve_patient_id(session, patient_id)
    procedures, total = procedures_repo.list_procedures(session, patient_id, code, limit, offset)
    return [_to_procedure_out(p) for p in procedures], total


def list_notes(
    session: Session,
    patient_id: str,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[NoteOut], int]:
    """List a patient's notes. Raises PatientNotFoundError."""
    patient_id = _resolve_patient_id(session, patient_id)
    notes, total = notes_repo.list_notes(session, patient_id, limit, offset)
    return [_to_note_out(n) for n in notes], total
