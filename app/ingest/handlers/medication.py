"""MedicationRequest -> medications."""

from app.ingest import normalize
from app.ingest.context import IngestContext
from app.ingest.references import resolve_subject
from app.ingest.registry import register
from app.models import IssueCode, Medication


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
    patient_id = resolve_subject(resource.get("subject"), ctx)

    concept = normalize.extract_concept(resource.get("medicationCodeableConcept"))
    if concept["code"] is None and concept["text"] is None:
        ctx.error(IssueCode.MISSING_CODE, "MedicationRequest has no code and no text; stored as 'Unknown'")

    authored_at, authored_precision = normalize.parse_fhir_datetime(resource.get("authoredOn"))

    requester = resource.get("requester")
    requester = requester if isinstance(requester, dict) else {}

    dosage = resource.get("dosageInstruction")
    first_dosage = dosage[0] if isinstance(dosage, list) and dosage else None
    dosage_text = first_dosage.get("text") if isinstance(first_dosage, dict) else None

    ctx.session.add(
        Medication(
            id=ctx.resource_id,
            patient_id=patient_id,
            code_system=concept["system"],
            code=concept["code"],
            display=concept["display"],
            text=concept["text"],
            status=resource.get("status"),
            intent=resource.get("intent"),
            authored_at=authored_at,
            authored_precision=authored_precision,
            requester_ref=requester.get("reference"),
            requester_display=requester.get("display"),
            dosage_text=dosage_text,
            raw_json=resource,
        )
    )
