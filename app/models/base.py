"""Declarative base and the column conventions shared by every table."""

from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RawMixin:
    """Every clinical row keeps the exact source resource it came from.

    Fidelity half of the hybrid schema: typed columns above for anything we
    query, the untouched original here so `/fhir/{type}/{id}` can hand back
    exactly what the clinic sent. Also means a field we forgot to model is
    never lost.
    """

    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)


class PrecisionMixin:
    """FHIR dates come at different precisions; don't fake accuracy.

    `onsetDateTime: "2023-04-10"` and `effectiveDateTime: "2025-01-05T08:00:00Z"`
    are both valid. Store a UTC timestamp for ordering plus the precision
    received, so a date-only value never masquerades as midnight.
    """


class Precision:
    """How precisely a clinical date was actually recorded.

    FHIR permits YYYY, YYYY-MM, YYYY-MM-DD, and full instants in the same
    field -- "diabetic since 2019" is a year, a lab draw is a timestamp.
    Store the normalized instant for ordering plus this, so nothing
    downstream mistakes a padded value for a measured one.
    """

    YEAR = "year"
    MONTH = "month"
    DATE = "date"
    INSTANT = "instant"


class ValueKind:
    QUANTITY = "quantity"
    STRING = "string"
    COMPONENT = "component"
    NONE = "none"


class RawStatus:
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN_TYPE = "unknown_type"


class Severity:
    WARNING = "warning"
    ERROR = "error"


class IssueCode:
    """Stable, greppable reasons a record is imperfect.

    These strings are part of the API contract: `/ingest/issues?code=...`
    filters on them, so treat renames as breaking changes.
    """

    SUBJECT_CASE_NORMALIZED = "SUBJECT_CASE_NORMALIZED"
    SUBJECT_UNKNOWN_PATIENT = "SUBJECT_UNKNOWN_PATIENT"
    SUBJECT_UNRESOLVABLE = "SUBJECT_UNRESOLVABLE"
    SUBJECT_MISSING = "SUBJECT_MISSING"
    SUBJECT_NON_CONFORMANT = "SUBJECT_NON_CONFORMANT"
    MISSING_CODE = "MISSING_CODE"
    MISSING_ID = "MISSING_ID"
    DUPLICATE_ID = "DUPLICATE_ID"
    UNKNOWN_RESOURCE_TYPE = "UNKNOWN_RESOURCE_TYPE"
    MALFORMED_JSON = "MALFORMED_JSON"
    MALFORMED_RESOURCE = "MALFORMED_RESOURCE"
    UNPARSEABLE_DATE = "UNPARSEABLE_DATE"
    UNPARSEABLE_VALUE = "UNPARSEABLE_VALUE"
    UNKNOWN_UNIT = "UNKNOWN_UNIT"
    ATTACHMENT_UNRESOLVED = "ATTACHMENT_UNRESOLVED"
    ATTACHMENT_UNDECODABLE = "ATTACHMENT_UNDECODABLE"
    HANDLER_FAILED = "HANDLER_FAILED"
