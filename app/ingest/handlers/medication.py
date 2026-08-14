"""MedicationRequest -> medications."""

from app.ingest.context import IngestContext
from app.ingest.registry import register


@register("MedicationRequest")
def handle_medication_request(resource: dict, ctx: IngestContext) -> None:
    """Store a prescription.

    Fields: medicationCodeableConcept (RxNorm), status, intent, authoredOn,
    subject, requester, dosageInstruction[0].text.

    `med-nw-003` is the case-mismatch record (`Patient/Noah-Wyle`): it should
    end up linked to `noah-wyle` with a SUBJECT_CASE_NORMALIZED warning, and it
    must appear in Noah Wyle's medication list.

    Note the naming choice: FHIR calls this a MedicationRequest, our table is
    `medications`. The consumer thinks in "what is this person taking", and
    every resource in this file is an active order. Be ready to say that the
    day a `MedicationStatement` or `MedicationAdministration` shows up, this
    table needs a `source_type` column the way `notes` already has one.
    """
    # TODO(Patti): dosageInstruction is a list -- guard for empty/missing
    # before reaching for [0].
    raise NotImplementedError("handle_medication_request")
