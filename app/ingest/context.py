"""Per-line state handed to every handler."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models import IngestIssue, Severity


@dataclass
class IngestContext:
    """What a handler is allowed to touch, and how it reports trouble.

    Handlers never raise for bad data -- they call `warn()` or `error()` and
    carry on with whatever they could salvage. Raising is reserved for genuine
    programming errors, which the loader catches and records as HANDLER_FAILED.
    """

    session: Session
    line_no: int
    resource_type: str | None = None
    resource_id: str | None = None
    issues: list[IngestIssue] = field(default_factory=list)

    def _record(
        self,
        severity: str,
        code: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        # Deliberately not session.add() here. Each resource is handled inside a
        # SAVEPOINT so a crash rolls back only that record's rows; if issues
        # lived in the same savepoint, the explanation would roll back with the
        # failure. The loader persists these after the savepoint resolves.
        self.issues.append(
            IngestIssue(
                line_no=self.line_no,
                resource_type=self.resource_type,
                resource_id=self.resource_id,
                severity=severity,
                code=code,
                message=message,
                detail=detail,
            )
        )

    def warn(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        """We handled it and kept the record fully usable."""
        self._record(Severity.WARNING, code, message, detail)

    def error(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        """We refused to guess; the record is stored but degraded or unlinked."""
        self._record(Severity.ERROR, code, message, detail)
