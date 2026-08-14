"""Reads the JSONL file and dispatches each resource to its handler.

The contract of this module is that it never lets one bad line stop the load.
Every line produces a `raw_resources` row no matter what, then dispatch is
attempted, and any failure becomes an `ingest_issues` row rather than an
exception that reaches the caller.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.ingest import registry
from app.ingest.context import IngestContext
from app.models import IngestIssue, IssueCode, RawResource, RawStatus, Severity

logger = logging.getLogger(__name__)


@dataclass
class ParsedLine:
    line_no: int
    resource: dict
    resource_type: str
    resource_id: str | None


@dataclass
class IngestSummary:
    lines_read: int = 0
    accepted: int = 0
    rejected: int = 0
    unknown_type: int = 0
    warnings: int = 0
    errors: int = 0
    by_type: dict[str, int] = field(default_factory=dict)


def ingest_file(path: str | Path, session: Session) -> IngestSummary:
    """Load every resource in `path` into `session`. Commits before returning."""
    registry.load_handlers()

    summary = IngestSummary()
    parsed: list[ParsedLine] = []
    seen_ids: set[tuple[str, str]] = set()
    pending_issues: list[IngestIssue] = []

    source = Path(path)
    if not source.exists():
        # An empty database is a legitimate state -- the API must still boot and
        # answer, so callers can see the problem through /ingest/report.
        logger.error("Data file not found: %s", source)
        session.commit()
        return summary

    # Pass one: read and classify. The whole file is held in memory, which is
    # fine at this scale and is called out in the README as a known limit.
    with source.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            summary.lines_read += 1

            try:
                resource = json.loads(line)
            except json.JSONDecodeError as exc:
                _reject(session, line_no, None, None, line, summary)
                pending_issues.append(
                    _issue(line_no, None, None, Severity.ERROR, IssueCode.MALFORMED_JSON, str(exc))
                )
                continue

            if not isinstance(resource, dict):
                _reject(session, line_no, None, None, line, summary)
                pending_issues.append(
                    _issue(
                        line_no, None, None, Severity.ERROR, IssueCode.MALFORMED_RESOURCE,
                        f"Expected a JSON object, got {type(resource).__name__}",
                    )
                )
                continue

            resource_type = resource.get("resourceType")
            resource_id = resource.get("id")
            if not isinstance(resource_type, str) or not resource_type:
                _reject(session, line_no, None, resource_id, line, summary, raw_json=resource)
                pending_issues.append(
                    _issue(
                        line_no, None, resource_id, Severity.ERROR,
                        IssueCode.MALFORMED_RESOURCE, "Resource has no resourceType",
                    )
                )
                continue

            if not isinstance(resource_id, str) or not resource_id:
                resource_id = None

            if registry.phase_of(resource_type) is None:
                # Not an error: a type we have not taught the system about yet.
                # Stored, counted, and still served from /fhir/{type}/{id}.
                session.add(
                    RawResource(
                        line_no=line_no, resource_type=resource_type, resource_id=resource_id,
                        status=RawStatus.UNKNOWN_TYPE, raw_json=resource,
                    )
                )
                summary.unknown_type += 1
                summary.by_type[resource_type] = summary.by_type.get(resource_type, 0) + 1
                pending_issues.append(
                    _issue(
                        line_no, resource_type, resource_id, Severity.WARNING,
                        IssueCode.UNKNOWN_RESOURCE_TYPE,
                        f"No handler registered for resourceType {resource_type!r}; "
                        "stored unmapped and retrievable through the raw endpoint",
                    )
                )
                continue

            if resource_id is None:
                pending_issues.append(
                    _issue(
                        line_no, resource_type, None, Severity.ERROR, IssueCode.MISSING_ID,
                        "Resource has no id; cannot be addressed or de-duplicated",
                    )
                )
                _reject(session, line_no, resource_type, None, line, summary, raw_json=resource)
                continue

            if (resource_type, resource_id) in seen_ids:
                pending_issues.append(
                    _issue(
                        line_no, resource_type, resource_id, Severity.ERROR,
                        IssueCode.DUPLICATE_ID,
                        f"{resource_type}/{resource_id} already seen earlier in the file; "
                        "later copy ignored",
                    )
                )
                _reject(session, line_no, resource_type, resource_id, line, summary, raw_json=resource)
                continue

            seen_ids.add((resource_type, resource_id))
            session.add(
                RawResource(
                    line_no=line_no, resource_type=resource_type, resource_id=resource_id,
                    status=RawStatus.ACCEPTED, raw_json=resource,
                )
            )
            summary.accepted += 1
            summary.by_type[resource_type] = summary.by_type.get(resource_type, 0) + 1
            parsed.append(ParsedLine(line_no, resource, resource_type, resource_id))

    session.flush()

    # Pass two: dispatch in phase order, so patients exist before anything
    # references them and Binary blobs exist before notes reach for their text.
    for phase in registry.phases():
        for item in parsed:
            if registry.phase_of(item.resource_type) != phase:
                continue
            pending_issues.extend(_dispatch(session, item))

    session.add_all(pending_issues)
    for issue in pending_issues:
        if issue.severity == Severity.ERROR:
            summary.errors += 1
        else:
            summary.warnings += 1

    session.commit()
    logger.info(
        "Ingest complete: %d lines, %d accepted, %d rejected, %d unknown type, "
        "%d errors, %d warnings",
        summary.lines_read, summary.accepted, summary.rejected,
        summary.unknown_type, summary.errors, summary.warnings,
    )
    return summary


def _dispatch(session: Session, item: ParsedLine) -> list[IngestIssue]:
    """Run one handler inside a SAVEPOINT so its failure is contained."""
    handler = registry.get_handler(item.resource_type)
    if handler is None:  # pragma: no cover - phase_of already screened for this
        return []

    ctx = IngestContext(
        session=session,
        line_no=item.line_no,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
    )

    savepoint = session.begin_nested()
    try:
        handler(item.resource, ctx)
        savepoint.commit()
    except Exception as exc:  # noqa: BLE001 - a handler bug must not stop the load
        savepoint.rollback()
        logger.exception("Handler for %s/%s failed", item.resource_type, item.resource_id)
        return [
            *ctx.issues,
            _issue(
                item.line_no, item.resource_type, item.resource_id, Severity.ERROR,
                IssueCode.HANDLER_FAILED,
                f"{type(exc).__name__}: {exc}",
            ),
        ]
    return ctx.issues


def _issue(
    line_no: int | None,
    resource_type: str | None,
    resource_id: str | None,
    severity: str,
    code: str,
    message: str,
    detail: dict | None = None,
) -> IngestIssue:
    return IngestIssue(
        line_no=line_no,
        resource_type=resource_type,
        resource_id=resource_id,
        severity=severity,
        code=code,
        message=message,
        detail=detail,
    )


def _reject(
    session: Session,
    line_no: int,
    resource_type: str | None,
    resource_id: str | None,
    raw_text: str,
    summary: IngestSummary,
    raw_json: dict | None = None,
) -> None:
    session.add(
        RawResource(
            line_no=line_no,
            resource_type=resource_type,
            resource_id=resource_id,
            status=RawStatus.REJECTED,
            raw_json=raw_json,
            raw_text=raw_text,
        )
    )
    summary.rejected += 1
