"""The domain tables a product engineer actually queries.

Shape of every table here: typed columns for anything filterable or sortable,
plus `raw_json` for fidelity. `patient_id` is nullable on purpose across all of
them -- a record whose subject we could not resolve is still real clinical data
and gets stored unlinked (an "orphan") rather than dropped.
"""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, RawMixin


class Patient(Base, RawMixin):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # Lowercased id, used to resolve references that differ only by case
    # (the file contains both `Patient/noah-wyle` and `Patient/Noah-Wyle`).
    id_normalized: Mapped[str] = mapped_column(String, index=True, nullable=False)

    family_name: Mapped[str | None] = mapped_column(String, index=True)
    given_names: Mapped[list | None] = mapped_column(JSON)
    display_name: Mapped[str | None] = mapped_column(String, index=True)
    gender: Mapped[str | None] = mapped_column(String, index=True)
    birth_date: Mapped[date | None] = mapped_column(Date, index=True)
    active: Mapped[bool | None] = mapped_column(Boolean)

    conditions: Mapped[list["Condition"]] = relationship(back_populates="patient")
    medications: Mapped[list["Medication"]] = relationship(back_populates="patient")
    observations: Mapped[list["Observation"]] = relationship(back_populates="patient")
    procedures: Mapped[list["Procedure"]] = relationship(back_populates="patient")
    notes: Mapped[list["Note"]] = relationship(back_populates="patient")


class Condition(Base, RawMixin):
    __tablename__ = "conditions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"), index=True)

    code_system: Mapped[str | None] = mapped_column(String)
    code: Mapped[str | None] = mapped_column(String, index=True)
    display: Mapped[str | None] = mapped_column(String)
    text: Mapped[str | None] = mapped_column(String)

    clinical_status: Mapped[str | None] = mapped_column(String, index=True)
    verification_status: Mapped[str | None] = mapped_column(String)

    onset_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    onset_precision: Mapped[str | None] = mapped_column(String)
    abatement_at: Mapped[datetime | None] = mapped_column(DateTime)
    abatement_precision: Mapped[str | None] = mapped_column(String)

    recorder_ref: Mapped[str | None] = mapped_column(String)
    recorder_display: Mapped[str | None] = mapped_column(String)

    patient: Mapped["Patient | None"] = relationship(back_populates="conditions")


class Medication(Base, RawMixin):
    """A FHIR MedicationRequest, named for what the consumer calls it."""

    __tablename__ = "medications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"), index=True)

    code_system: Mapped[str | None] = mapped_column(String)
    code: Mapped[str | None] = mapped_column(String, index=True)
    display: Mapped[str | None] = mapped_column(String)
    text: Mapped[str | None] = mapped_column(String)

    status: Mapped[str | None] = mapped_column(String, index=True)
    intent: Mapped[str | None] = mapped_column(String)

    authored_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    authored_precision: Mapped[str | None] = mapped_column(String)

    requester_ref: Mapped[str | None] = mapped_column(String)
    requester_display: Mapped[str | None] = mapped_column(String)
    dosage_text: Mapped[str | None] = mapped_column(String)

    patient: Mapped["Patient | None"] = relationship(back_populates="medications")


class Observation(Base, RawMixin):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"), index=True)

    code_system: Mapped[str | None] = mapped_column(String)
    code: Mapped[str | None] = mapped_column(String, index=True)
    display: Mapped[str | None] = mapped_column(String)
    text: Mapped[str | None] = mapped_column(String)

    status: Mapped[str | None] = mapped_column(String, index=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    effective_precision: Mapped[str | None] = mapped_column(String)

    # Discriminator over FHIR's value[x] polymorphism. See models.base.ValueKind:
    # `quantity` (valueQuantity), `string` (valueString), `component` (value
    # lives in the components, e.g. blood pressure), `none`.
    value_kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    value_number: Mapped[float | None] = mapped_column(Float)
    value_unit: Mapped[str | None] = mapped_column(String)
    # Canonical UCUM-ish unit so range queries survive sloppy sources: the file
    # has both `beats/minute` and bare `mmHg` with no unit system.
    value_unit_canonical: Mapped[str | None] = mapped_column(String, index=True)
    value_string: Mapped[str | None] = mapped_column(Text)

    performer_ref: Mapped[str | None] = mapped_column(String)

    components: Mapped[list["ObservationComponent"]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )
    patient: Mapped["Patient | None"] = relationship(back_populates="observations")


class ObservationComponent(Base):
    """Multi-part observations, e.g. blood pressure's systolic + diastolic."""

    __tablename__ = "observation_components"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"), index=True)

    code_system: Mapped[str | None] = mapped_column(String)
    code: Mapped[str | None] = mapped_column(String, index=True)
    display: Mapped[str | None] = mapped_column(String)

    value_number: Mapped[float | None] = mapped_column(Float)
    value_unit: Mapped[str | None] = mapped_column(String)
    value_unit_canonical: Mapped[str | None] = mapped_column(String)

    observation: Mapped["Observation"] = relationship(back_populates="components")


class Procedure(Base, RawMixin):
    __tablename__ = "procedures"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"), index=True)

    code_system: Mapped[str | None] = mapped_column(String)
    code: Mapped[str | None] = mapped_column(String, index=True)
    display: Mapped[str | None] = mapped_column(String)
    text: Mapped[str | None] = mapped_column(String)

    status: Mapped[str | None] = mapped_column(String, index=True)
    performed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    performed_precision: Mapped[str | None] = mapped_column(String)

    performer_ref: Mapped[str | None] = mapped_column(String)
    performer_display: Mapped[str | None] = mapped_column(String)

    patient: Mapped["Patient | None"] = relationship(back_populates="procedures")


class Note(Base, RawMixin):
    """Narrative text, unified across two very different source shapes.

    The file carries notes as a non-standard `ClinicalNote` (text inline) and as
    a `DocumentReference` pointing at a `Binary` holding base64. The consumer
    should not care about that difference, so we resolve and decode at ingest
    and expose one shape.
    """

    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"), index=True)

    source_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    type_code: Mapped[str | None] = mapped_column(String)
    type_display: Mapped[str | None] = mapped_column(String)

    status: Mapped[str | None] = mapped_column(String)
    authored_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    authored_precision: Mapped[str | None] = mapped_column(String)

    author_ref: Mapped[str | None] = mapped_column(String)
    content_type: Mapped[str | None] = mapped_column(String)
    text: Mapped[str | None] = mapped_column(Text)
    # Set when a DocumentReference pointed at a Binary we could not resolve or
    # decode; the note row still exists so the gap is visible rather than silent.
    text_unavailable_reason: Mapped[str | None] = mapped_column(String)

    patient: Mapped["Patient | None"] = relationship(back_populates="notes")


Index("ix_observations_patient_code", Observation.patient_id, Observation.code)
Index("ix_conditions_patient_status", Condition.patient_id, Condition.clinical_status)
