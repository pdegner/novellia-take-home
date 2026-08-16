"""Procedure -> procedures."""

from app.ingest import normalize
from app.ingest.context import IngestContext
from app.ingest.references import resolve_subject
from app.ingest.registry import register
from app.models import IssueCode, Procedure


@register("Procedure")
def handle_procedure(resource: dict, ctx: IngestContext) -> None:
    """Store a performed procedure.

    Fields: code (SNOMED), status, performedDateTime, subject, performer.
    `performer` is a list here, unlike Condition's singular `recorder` -- FHIR
    is inconsistent about this and the handler should not assume.
    """
    patient_id = resolve_subject(resource.get("subject"), ctx)

    concept = normalize.extract_concept(resource.get("code"))
    if concept["code"] is None and concept["text"] is None:
        ctx.error(IssueCode.MISSING_CODE, "Procedure has no code and no text; stored as 'Unknown'")

    performed_at, performed_precision = normalize.parse_fhir_datetime(resource.get("performedDateTime"))

    performer = resource.get("performer")
    first = performer[0] if isinstance(performer, list) and performer else None
    actor = first.get("actor") if isinstance(first, dict) else None
    actor = actor if isinstance(actor, dict) else {}

    ctx.session.add(
        Procedure(
            id=ctx.resource_id,
            patient_id=patient_id,
            code_system=concept["system"],
            code=concept["code"],
            display=concept["display"],
            text=concept["text"],
            status=resource.get("status"),
            performed_at=performed_at,
            performed_precision=performed_precision,
            performer_ref=actor.get("reference"),
            performer_display=actor.get("display"),
            raw_json=resource,
        )
    )
