"""Condition -> conditions."""

from app.ingest import normalize
from app.ingest.context import IngestContext
from app.ingest.references import resolve_subject
from app.ingest.registry import register
from app.models import Condition, IssueCode


@register("Condition")
def handle_condition(resource: dict, ctx: IngestContext) -> None:
    """Store a diagnosis.

    Fields: code (SNOMED), clinicalStatus, verificationStatus, onsetDateTime,
    abatementDateTime, subject, recorder.

    Two things worth deciding deliberately here:

    * `cond-nw-bad-001` has **no `code`**. Keep the record and raise
      MISSING_CODE. Dropping it would erase a real active diagnosis from a
      patient's history, which is a worse outcome than an unlabelled entry.
    * `onsetDateTime` is date-only throughout this file while other resources
      carry full instants. Store the precision so the timeline can render
      "2023" rather than a fake 00:00.
    """
    patient_id = resolve_subject(resource.get("subject"), ctx)

    concept = normalize.extract_concept(resource.get("code"))
    if concept["code"] is None and concept["text"] is None:
        ctx.error(IssueCode.MISSING_CODE, "Condition has no code and no text; stored as 'Unknown'")

    onset_at, onset_precision = normalize.parse_fhir_datetime(resource.get("onsetDateTime"))
    abatement_at, abatement_precision = normalize.parse_fhir_datetime(resource.get("abatementDateTime"))

    recorder = resource.get("recorder")
    recorder = recorder if isinstance(recorder, dict) else {}

    ctx.session.add(
        Condition(
            id=ctx.resource_id,
            patient_id=patient_id,
            code_system=concept["system"],
            code=concept["code"],
            display=concept["display"],
            text=concept["text"],
            clinical_status=normalize.extract_status(resource.get("clinicalStatus")),
            verification_status=normalize.extract_status(resource.get("verificationStatus")),
            onset_at=onset_at,
            onset_precision=onset_precision,
            abatement_at=abatement_at,
            abatement_precision=abatement_precision,
            recorder_ref=recorder.get("reference"),
            recorder_display=recorder.get("display"),
            raw_json=resource,
        )
    )
