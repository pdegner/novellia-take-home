"""Resolving a FHIR `subject` to a patient in our database.

This module is the heart of the "messy data" story, so it is worth being
explicit about the principle: **it never guesses.**

Attaching a lab result to the wrong chart because two people share a name is a
patient-safety incident, not a data-quality blemish. Where the source is
ambiguous we refuse the link, keep the record, and surface it for a human to
reconcile. An orphaned record is visible and fixable; a mis-linked one is
invisible and dangerous.

The ladder, in order:

  1. Exact match on `Patient/{id}`.
       -> link, silently. The common case.
  2. Match after trimming whitespace and lowercasing.
       -> link, WARN `SUBJECT_CASE_NORMALIZED`.
          Exercised by `med-nw-003`, whose subject is `Patient/Noah-Wyle`
          while the patient's real id is `noah-wyle`. Safe because ids are
          opaque handles; case is a transport artefact, not identity.
  3. A well-formed reference to an id we do not have.
       -> DO NOT LINK, ERROR `SUBJECT_UNKNOWN_PATIENT`.
          Exercised by `obs-nw-006` -> `Patient/nwyle`. It looks like Noah
          Wyle and probably is, but "probably" is not a standard we can apply
          to a chart. The record becomes an orphan.
  4. A subject with `display` but no `reference`.
       -> DO NOT LINK, ERROR `SUBJECT_UNRESOLVABLE`.
          Exercised by `obs-kl-bad-001`, subject `{"display": "Katherine
          LaNasa"}`. Name matching is exactly the failure mode above, so we
          decline it here too.
  5. No subject at all.
       -> DO NOT LINK, ERROR `SUBJECT_MISSING`.

An unlinked record is stored with `patient_id = NULL`. That NULL plus the issue
row is the whole orphan mechanism -- there is no separate quarantine table.
"""

from sqlalchemy.orm import Session

from app.ingest.context import IngestContext
from app.models import IssueCode, Patient


def resolve_subject(subject: object, ctx: IngestContext) -> str | None:
    """Return the patient id this record belongs to, or None if we won't guess.

    Records the appropriate issue on `ctx` as a side effect. Callers store the
    return value directly into `patient_id`, NULL and all.

    Args:
        subject: the raw `subject` value from the resource. Trust nothing about
            its shape -- it may be a dict, a bare string, or missing entirely.
        ctx: ingest context, for reporting and database access.
    """
    # TODO(Patti): implement the ladder documented above.
    #
    # Suggested shape:
    #   1. Guard the input: None -> SUBJECT_MISSING. A non-dict (a bare string
    #      reference) is worth tolerating; decide and document which way you go.
    #   2. Pull `reference` and `display`.
    #   3. Strip the `Patient/` prefix. Consider what a reference to a
    #      *different* resource type should do -- a `Group/...` subject is
    #      valid FHIR and is not a patient.
    #   4. Try `find_patient(...)` below for steps 1 and 2 of the ladder.
    #   5. Fall through to the error cases, returning None.
    raise NotImplementedError("resolve_subject: see the ladder in this module's docstring")


def find_patient(session: Session, patient_id: str) -> tuple[Patient | None, bool]:
    """Look up a patient by id, tolerating case and whitespace differences.

    Returns:
        (patient, was_normalized) -- `was_normalized` is True when the match
        required falling back to the case-insensitive comparison, which is the
        caller's signal to raise SUBJECT_CASE_NORMALIZED.
    """
    # TODO(Patti): exact match on Patient.id first, then a second lookup on
    # Patient.id_normalized using patient_id.strip().lower(). The
    # `id_normalized` column exists precisely so this stays an indexed lookup
    # rather than a scan.
    raise NotImplementedError("find_patient")


def reference_id(reference: object, expected_type: str = "Patient") -> str | None:
    """Pull the bare id out of a FHIR reference string.

    `"Patient/noah-wyle"` -> `"noah-wyle"`. Returns None when the reference is
    absent, malformed, or points at a different resource type than expected.

    Also used for `Binary/binary-001` when resolving note attachments, which is
    why the resource type is a parameter.
    """
    # TODO(Patti): handle the plain "Type/id" form. Absolute URLs and contained
    # references ("#fragment") also exist in real FHIR -- decide whether to
    # support them now or note the gap in the README.
    raise NotImplementedError("reference_id")


__all__ = ["IssueCode", "find_patient", "reference_id", "resolve_subject"]
