"""The API contract: what a product consumer receives.

Note how little FHIR vocabulary survives here. No CodeableConcepts, no
`value[x]`, no references to chase. That translation is the whole argument for
this API existing rather than handing someone the JSONL file.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TemporalOut(BaseModel):
    """A clinical date, honest about how precisely it was recorded.

    `value` renders at the precision we received (`"2023-04-10"` for a
    date-only onset), while `timestamp` is the normalised UTC instant used for
    sorting. A client that renders `value` never shows a fabricated 00:00.
    """

    value: str
    precision: Literal["year", "month", "date", "instant"]
    timestamp: datetime


class CodeOut(BaseModel):
    """A clinical concept, flattened.

    `display` falls back to the resource's `text` and finally to None. A record
    with no code at all (`cond-nw-bad-001`) still serialises -- the consumer
    sees an entry with no label rather than the entry vanishing.
    """

    system: str | None = None
    code: str | None = None
    display: str | None = None


class PatientOut(BaseModel):
    id: str
    name: str | None
    family_name: str | None
    given_names: list[str] = Field(default_factory=list)
    gender: str | None
    birth_date: date | None
    age: int | None = Field(None, description="Derived from birth_date at request time")
    active: bool | None

    model_config = {"from_attributes": True}


class ConditionOut(BaseModel):
    id: str
    code: CodeOut
    label: str | None = Field(description="Best available human label for the diagnosis")
    clinical_status: str | None
    verification_status: str | None
    onset: TemporalOut | None
    abatement: TemporalOut | None
    recorded_by: str | None


class MedicationOut(BaseModel):
    id: str
    code: CodeOut
    label: str | None
    status: str | None
    intent: str | None
    authored: TemporalOut | None
    prescribed_by: str | None
    dosage: str | None


class ObservationComponentOut(BaseModel):
    code: CodeOut
    label: str | None
    value: float | None
    unit: str | None
    unit_canonical: str | None


class ObservationOut(BaseModel):
    id: str
    code: CodeOut
    label: str | None
    status: str | None
    effective: TemporalOut | None
    # One of these carries the reading, per `value_kind`. Blood pressure uses
    # `components` and leaves the scalar fields null.
    value_kind: Literal["quantity", "string", "component", "none"]
    value: float | None = None
    unit: str | None = None
    unit_canonical: str | None = None
    value_text: str | None = None
    components: list[ObservationComponentOut] = Field(default_factory=list)


class ProcedureOut(BaseModel):
    id: str
    code: CodeOut
    label: str | None
    status: str | None
    performed: TemporalOut | None
    performed_by: str | None


class NoteOut(BaseModel):
    id: str
    source_type: str = Field(
        description="Which upstream shape this came from: ClinicalNote or DocumentReference"
    )
    type: CodeOut | None
    status: str | None
    authored: TemporalOut | None
    author: str | None
    text: str | None
    text_unavailable_reason: str | None = Field(
        None, description="Set when the note exists but its content could not be retrieved"
    )


class TimelineEvent(BaseModel):
    """One entry in the merged chronological view.

    Deliberately uniform across record types so a client can render a single
    list. `detail` carries the type-specific payload for a client that wants to
    expand an entry.
    """

    kind: Literal["condition", "medication", "observation", "procedure", "note"]
    id: str
    occurred: TemporalOut
    label: str | None
    summary: str | None = Field(None, description="One-line human-readable description")
    detail: dict | None = None


class PatientSummary(BaseModel):
    """The flagship response: everything a chart view needs in one call.

    Built to answer "what is going on with this person right now", which is a
    different question from "what resources exist", and is the reason the
    endpoint is not just five list calls stitched together client-side.
    """

    patient: PatientOut
    active_conditions: list[ConditionOut]
    resolved_conditions: list[ConditionOut]
    current_medications: list[MedicationOut]
    latest_vitals: list[ObservationOut] = Field(
        description="Most recent reading per distinct observation code"
    )
    recent_notes: list[NoteOut]
    counts: dict[str, int] = Field(description="Total records held per category")


class PatientListItem(BaseModel):
    id: str
    name: str | None
    gender: str | None
    birth_date: date | None
    record_count: int

    model_config = {"from_attributes": True}
