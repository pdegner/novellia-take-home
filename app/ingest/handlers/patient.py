"""Patient -> patients.

Runs in Phase.SUBJECTS, before anything that could reference a patient.
"""

from app.ingest.context import IngestContext
from app.ingest.registry import Phase, register


@register("Patient", phase=Phase.SUBJECTS)
def handle_patient(resource: dict, ctx: IngestContext) -> None:
    """Store a patient.

    Fields: id, name[] -> family_name / given_names / display_name,
    gender, birthDate, active.

    `id_normalized` must be set to `id.strip().lower()` -- the case-insensitive
    reference lookup in references.find_patient depends on it.
    """
    # TODO(Patti): build a Patient and ctx.session.add() it.
    # Use normalize.patient_display_name and normalize.parse_fhir_datetime
    # (birthDate is a plain date -- store the .date() part).
    raise NotImplementedError("handle_patient")
