"""Procedure -> procedures."""

from app.ingest.context import IngestContext
from app.ingest.registry import register


@register("Procedure")
def handle_procedure(resource: dict, ctx: IngestContext) -> None:
    """Store a performed procedure.

    Fields: code (SNOMED), status, performedDateTime, subject, performer.
    `performer` is a list here, unlike Condition's singular `recorder` -- FHIR
    is inconsistent about this and the handler should not assume.
    """
    # TODO(Patti): straightforward once Condition is done; same shape.
    raise NotImplementedError("handle_procedure")
