"""Tables that record what we received and what we couldn't make sense of.

These exist because the brief promises data we haven't seen. An unrecognized
type isn't an error here -- it lands in `raw_resources` as `unknown_type`,
gets counted in the ingest report, and stays retrievable through the raw
endpoint. Nothing is silently discarded.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RawResource(Base):
    """One row per line of the source file, whatever that line turned out to be."""

    __tablename__ = "raw_resources"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    resource_type: Mapped[str | None] = mapped_column(String, index=True)
    resource_id: Mapped[str | None] = mapped_column(String, index=True)

    # accepted | rejected | unknown_type -- see models.base.RawStatus
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Parsed JSON when the line was valid JSON, otherwise null.
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    # The literal line text, kept only when parsing failed so the operator can
    # see what actually arrived.
    raw_text: Mapped[str | None] = mapped_column(Text)


class IngestIssue(Base):
    """Every imperfection found during ingest, addressable and filterable.

    Warnings mean we handled it and linked the record anyway (a case-mismatched
    reference). Errors mean we refused to guess and the record is unlinked.
    """

    __tablename__ = "ingest_issues"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    line_no: Mapped[int | None] = mapped_column(Integer, index=True)

    resource_type: Mapped[str | None] = mapped_column(String, index=True)
    resource_id: Mapped[str | None] = mapped_column(String, index=True)

    severity: Mapped[str] = mapped_column(String, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String, nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # The offending fragment (a bad reference, an unparseable value), not the
    # whole resource -- the whole resource is one join away in raw_resources.
    detail: Mapped[dict | None] = mapped_column(JSON)

    # Set once a human links the orphaned record to a patient. Kept on this
    # row rather than deleted -- the issue is history now, not erased. No
    # `resolved_by`: there's no auth in this API, so there's no principal to
    # attribute it to (see DECISIONS.md, "Reconciliation").
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    resolved_patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"))


Index("ix_issues_code_severity", IngestIssue.code, IngestIssue.severity)
Index("ix_raw_type_id", RawResource.resource_type, RawResource.resource_id)
