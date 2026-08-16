"""Closes the loop the subject resolution ladder opens.

`references.py` refuses to guess and leaves a record orphaned rather than
risk attaching it to the wrong chart. That's the right call for a machine,
but it can't be the end of the story -- a human who actually knows the
patient needs a way to finish what the ladder wouldn't. This is that way.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.exceptions import InvalidQueryError, IssueNotFoundError, PatientNotFoundError
from app.models import Condition, IngestIssue, IssueCode, Medication, Note, Observation, Procedure
from app.repositories import patients as patients_repo

# Only resource types that land in a table with a `patient_id` column are
# linkable. Patient and Binary rows have no subject of their own, so an issue
# against one of those (a MISSING_ID, say) is never in this map -- there's
# nothing to attach.
_LINKABLE_TYPES: dict[str, type] = {
    "Condition": Condition,
    "MedicationRequest": Medication,
    "Observation": Observation,
    "Procedure": Procedure,
    "ClinicalNote": Note,
    "DocumentReference": Note,
}

# The only codes that mean "this record exists but isn't attached to anyone."
# Everything else (UNKNOWN_UNIT, MISSING_CODE, ...) describes a record that's
# already linked and imperfect in some other way -- resolving it here would
# be a no-op wearing a reconciliation costume.
_ORPHAN_CODES = {
    IssueCode.SUBJECT_UNKNOWN_PATIENT,
    IssueCode.SUBJECT_UNRESOLVABLE,
    IssueCode.SUBJECT_MISSING,
}


def resolve_issue(session: Session, issue_id: int, patient_id: str) -> IngestIssue:
    """Link the orphaned record behind `issue_id` to `patient_id`.

    This is a human override, not another rung on the ladder -- the ladder
    never name-matches because "probably" isn't good enough for a machine to
    decide alone. A person who actually recognizes the patient is a different
    source of truth, so this trusts whatever id they give it, same as any
    other authenticated write would. Raises IssueNotFoundError,
    InvalidQueryError (wrong kind of issue, or already resolved), or
    PatientNotFoundError.
    """
    issue = session.get(IngestIssue, issue_id)
    if issue is None:
        raise IssueNotFoundError(issue_id)

    if issue.resolved_at is not None:
        raise InvalidQueryError(f"Issue {issue_id} was already resolved")

    if issue.code not in _ORPHAN_CODES:
        raise InvalidQueryError(
            f"Issue {issue_id} has code {issue.code!r}, not an unlinked-subject issue -- "
            "there's no patient link to make"
        )

    model = _LINKABLE_TYPES.get(issue.resource_type or "")
    if model is None or issue.resource_id is None:
        raise InvalidQueryError(
            f"Issue {issue_id} isn't tied to a record that can be linked "
            f"(resource_type={issue.resource_type!r})"
        )

    record = session.get(model, issue.resource_id)
    if record is None:
        raise InvalidQueryError(f"Record {issue.resource_id!r} that issue {issue_id} points at no longer exists")

    patient = patients_repo.get_patient(session, patient_id)
    if patient is None:
        raise PatientNotFoundError(patient_id)

    record.patient_id = patient.id
    issue.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    issue.resolved_patient_id = patient.id
    session.flush()
    return issue
