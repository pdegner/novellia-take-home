"""Resolves a FHIR `subject` to a patient id.

Rule: never guess. Attaching a record to the wrong chart because two people
share a name is a patient-safety incident, not a data-quality issue. When the
source is ambiguous, refuse the link, keep the record, and flag it for a
human to reconcile. An orphaned record is visible and fixable; a mis-linked
one is invisible and dangerous.

Resolution order:

  1. Exact match on `Patient/{id}`.
       -> link, no warning. The common case.
  2. Match after trimming whitespace and lowercasing.
       -> link, warn `SUBJECT_CASE_NORMALIZED`.
          Case `med-nw-003`: subject is `Patient/Noah-Wyle`, real id is
          `noah-wyle`. Safe because ids are opaque handles; case is a
          transport artifact, not identity.
  3. Well-formed reference to an id we don't have.
       -> refuse, error `SUBJECT_UNKNOWN_PATIENT`.
          Case `obs-nw-006` -> `Patient/nwyle`. Looks like Noah Wyle,
          probably is, but "probably" isn't a standard for a medical chart.
          The record becomes an orphan.
  4. Subject has a `display` name but no `reference`.
       -> refuse, error `SUBJECT_UNRESOLVABLE`.
          Case `obs-kl-bad-001`: subject is `{"display": "Katherine
          LaNasa"}`. Name matching fails the same way as step 3, so it's
          refused here too.
  5. No subject at all.
       -> refuse, error `SUBJECT_MISSING`.

An unlinked record is stored with `patient_id = NULL`. That NULL plus the
issue row is the whole orphan mechanism; there's no separate quarantine
table.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.context import IngestContext
from app.models import IssueCode, Patient


def resolve_subject(subject: object, ctx: IngestContext) -> str | None:
    """Return the patient id this record belongs to, or None if we won't guess.

    Records the appropriate issue on `ctx` as a side effect. Callers store the
    return value straight into `patient_id`, NULL and all -- an unlinked record
    is a supported state, not a failure to handle.

    Args:
        subject: the raw `subject` value. Trust nothing about its shape.
        ctx: ingest context, for reporting and database access.
    """
    if subject is None:
        ctx.error(IssueCode.SUBJECT_MISSING, "Record has no subject; cannot be attached to anyone")
        return None

    if isinstance(subject, str):
        # Bare string instead of a Reference object. Non-conformant, but the
        # id is explicit -- no identity guess, just a missing wrapper.
        # Allowed, and flagged so it stays visible.
        reference, display = subject, None
        ctx.warn(
            IssueCode.SUBJECT_NON_CONFORMANT,
            "Subject is a bare string rather than a Reference object; read as a reference",
            {"subject": subject},
        )
    elif isinstance(subject, dict):
        reference = subject.get("reference")
        display = subject.get("display")
    else:
        ctx.error(
            IssueCode.SUBJECT_UNRESOLVABLE,
            f"Subject has unusable type {type(subject).__name__}",
            {"subject": repr(subject)[:200]},
        )
        return None

    if not isinstance(reference, str) or not reference.strip():
        if display:
            # Step 4: named by display text only. Refused -- name matching is
            # exactly how clinical data gets attached to the wrong person.
            ctx.error(
                IssueCode.SUBJECT_UNRESOLVABLE,
                f"Subject identifies the patient only by display name ({display!r}). "
                "Not linked: matching patients by name risks attaching clinical "
                "data to the wrong person.",
                {"display": display},
            )
        else:
            ctx.error(
                IssueCode.SUBJECT_MISSING,
                "Subject carries neither a reference nor a display name",
                {"subject": subject if isinstance(subject, dict) else None},
            )
        return None

    patient_id = reference_id(reference, expected_type="Patient")
    if patient_id is None:
        ctx.error(
            IssueCode.SUBJECT_UNRESOLVABLE,
            f"Subject reference {reference!r} is not a usable Patient reference",
            {"reference": reference},
        )
        return None

    patient, was_normalized = find_patient(ctx.session, patient_id)

    if patient is None:
        # Step 3: well-formed reference to a patient we don't have (the
        # `Patient/nwyle` case). Probably means Noah Wyle, but "probably"
        # isn't a standard for a medical record.
        ctx.error(
            IssueCode.SUBJECT_UNKNOWN_PATIENT,
            f"Subject references {reference!r}, which matches no known patient. "
            "Not linked: the record is kept unattached for manual reconciliation.",
            {"reference": reference, "display": display},
        )
        return None

    if was_normalized:
        # Step 2: ids are opaque handles, case is a transport artifact.
        ctx.warn(
            IssueCode.SUBJECT_CASE_NORMALIZED,
            f"Subject reference {reference!r} matched patient {patient.id!r} "
            "only after case normalisation",
            {"reference": reference, "resolved_to": patient.id},
        )

    return patient.id


def find_patient(session: Session, patient_id: str) -> tuple[Patient | None, bool]:
    """Look up a patient by id, tolerating case and whitespace differences.

    Returns:
        (patient, was_normalized) -- `was_normalized` is True when the match
        required the case-insensitive fallback, which is the caller's signal to
        raise SUBJECT_CASE_NORMALIZED.
    """
    exact = session.get(Patient, patient_id)
    if exact is not None:
        return exact, False

    normalized = patient_id.strip().lower()
    if normalized == patient_id:
        # Already canonical, so the fallback would repeat the same lookup.
        return None, False

    # Indexed lookup, not a scan -- `id_normalized` exists for exactly this.
    match = session.execute(
        select(Patient).where(Patient.id_normalized == normalized)
    ).scalars().first()
    return (match, True) if match is not None else (None, False)


def reference_id(reference: object, expected_type: str = "Patient") -> str | None:
    """Pull the bare id out of a FHIR reference string.

    `"Patient/noah-wyle"` -> `"noah-wyle"`. Returns None when the reference is
    absent, malformed, or points at a different resource type than expected --
    a `Group/...` subject is valid FHIR, but it isn't a patient.

    Handles the three forms seen in practice: relative (`Patient/123`),
    absolute (`https://ehr.example/fhir/Patient/123`), and versioned
    (`Patient/123/_history/2`).

    Contained references (`#p1`) return None. Resolving those means looking
    into the parent resource's `contained` array, which nothing in this
    dataset uses -- a known gap, not implemented halfway.

    `expected_type` is a parameter because notes reuse this for
    `Binary/binary-001`.
    """
    if not isinstance(reference, str):
        return None

    text = reference.strip()
    if not text or text.startswith("#"):
        return None

    parts = [part for part in text.split("/") if part]
    if "_history" in parts:
        parts = parts[: parts.index("_history")]

    if len(parts) < 2:
        return None

    resource_type, resource_id = parts[-2], parts[-1]
    if resource_type != expected_type:
        return None

    return resource_id or None


__all__ = ["IssueCode", "find_patient", "reference_id", "resolve_subject"]
