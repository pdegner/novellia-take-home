"""Condition -> conditions."""

from app.ingest.context import IngestContext
from app.ingest.registry import register


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
    # TODO(Patti): resolve_subject, extract_concept, extract_status,
    # parse_fhir_datetime, then add a Condition. patient_id may legitimately
    # be None -- do not skip the record when it is.
    raise NotImplementedError("handle_condition")
