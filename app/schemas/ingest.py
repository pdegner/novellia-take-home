"""Response models for the data-quality surface."""

from pydantic import BaseModel, Field


class IssueOut(BaseModel):
    id: int
    line_no: int | None
    resource_type: str | None
    resource_id: str | None
    severity: str
    code: str
    message: str
    detail: dict | None

    model_config = {"from_attributes": True}


class TypeBreakdown(BaseModel):
    resource_type: str
    accepted: int = 0
    rejected: int = 0
    unknown_type: int = 0


class CodeCount(BaseModel):
    code: str
    severity: str
    count: int


class IngestReport(BaseModel):
    """What happened when we read the file.

    Deliberately reconcilable by hand: `total_lines` equals accepted +
    rejected + unknown_type, so a reviewer can confirm nothing was dropped
    quietly. That guarantee is the point of the endpoint.
    """

    source_file: str
    total_lines: int
    accepted: int
    rejected: int
    unknown_type: int
    linked_records: int = Field(description="Clinical records attached to a patient")
    orphaned_records: int = Field(
        description="Clinical records stored but not attached, because the "
        "subject reference could not be resolved without guessing"
    )
    errors: int
    warnings: int
    by_type: list[TypeBreakdown]
    by_issue_code: list[CodeCount]
