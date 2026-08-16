"""Patient -> patients.

Runs in Phase.SUBJECTS, before anything that could reference a patient.
"""

from app.ingest import normalize
from app.ingest.context import IngestContext
from app.ingest.registry import Phase, register
from app.models import Patient


@register("Patient", phase=Phase.SUBJECTS)
def handle_patient(resource: dict, ctx: IngestContext) -> None:
    """Store a patient.

    Fields: id, name[] -> family_name / given_names / display_name,
    gender, birthDate, active.

    `id_normalized` must be set to `id.strip().lower()` -- the case-insensitive
    reference lookup in references.find_patient depends on it.
    """
    name = resource.get("name")
    birth_date, _ = normalize.parse_fhir_datetime(resource.get("birthDate"))

    ctx.session.add(
        Patient(
            id=ctx.resource_id,
            id_normalized=ctx.resource_id.strip().lower(),
            family_name=normalize.family_name(name),
            given_names=normalize.given_names(name),
            display_name=normalize.patient_display_name(name),
            gender=resource.get("gender"),
            birth_date=birth_date.date() if birth_date else None,
            active=resource.get("active"),
            raw_json=resource,
        )
    )
