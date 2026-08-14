"""Importing this package registers every mapped class on Base.metadata."""

from app.models.base import (
    Base,
    IssueCode,
    Precision,
    RawStatus,
    Severity,
    ValueKind,
)
from app.models.clinical import (
    Condition,
    Medication,
    Note,
    Observation,
    ObservationComponent,
    Patient,
    Procedure,
)
from app.models.provenance import IngestIssue, RawResource

__all__ = [
    "Base",
    "Condition",
    "IngestIssue",
    "IssueCode",
    "Medication",
    "Note",
    "Observation",
    "ObservationComponent",
    "Patient",
    "Precision",
    "Procedure",
    "RawResource",
    "RawStatus",
    "Severity",
    "ValueKind",
]
