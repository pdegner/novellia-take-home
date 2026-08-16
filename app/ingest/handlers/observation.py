"""Observation -> observations + observation_components."""

from app.ingest import normalize
from app.ingest.context import IngestContext
from app.ingest.references import resolve_subject
from app.ingest.registry import register
from app.models import IssueCode, Observation, ObservationComponent, ValueKind


@register("Observation")
def handle_observation(resource: dict, ctx: IngestContext) -> None:
    """Store a vital sign or lab result.

    This is the messiest resource in the file and the one most worth getting
    right -- 57 of the 128 lines are Observations.

    Shapes to handle:

    * `valueQuantity` -- the common case (weight, HbA1c, glucose, heart rate).
    * `valueString` -- `obs-pb-002` records smoking status as
      "Former smoker, quit 2019". A schema that assumed every observation was
      numeric would drop it or crash; `value_kind` is why neither happens.
    * `component[]` -- blood pressure carries no top-level value at all; the
      systolic and diastolic readings live in components. Store the parent with
      `value_kind = "component"` and a row per component.
    * Units -- most `valueQuantity` entries have no UCUM `system`/`code`, only
      a `unit` label, and `beats/minute` needs mapping to `/min`. Populate both
      `value_unit` (as received) and `value_unit_canonical` (normalised).

    Bad-subject records to expect: `obs-nw-006` (`Patient/nwyle`, unknown) and
    `obs-kl-bad-001` (display-only subject). Both stay unlinked by design.
    """
    patient_id = resolve_subject(resource.get("subject"), ctx)

    concept = normalize.extract_concept(resource.get("code"))
    if concept["code"] is None and concept["text"] is None:
        ctx.error(IssueCode.MISSING_CODE, "Observation has no code and no text; stored as 'Unknown'")

    effective_at, effective_precision = normalize.parse_fhir_datetime(resource.get("effectiveDateTime"))

    performer = resource.get("performer")
    first = performer[0] if isinstance(performer, list) and performer else None
    performer_ref = first.get("reference") if isinstance(first, dict) else None

    value_kind = normalize.classify_value(resource)

    value_number = value_unit = value_unit_canonical = value_string = None
    if value_kind == ValueKind.QUANTITY:
        value_number, value_unit, value_unit_canonical = normalize.extract_quantity(
            resource.get("valueQuantity")
        )
        if value_unit and value_unit_canonical is None:
            ctx.warn(IssueCode.UNKNOWN_UNIT, f"Unit {value_unit!r} is not in the canonical unit map")
    elif value_kind == ValueKind.STRING:
        # classify_value already confirmed valueString cleans to a non-empty
        # string via this same rule; recomputing it separately would risk the
        # two silently drifting apart.
        value_string = normalize._as_text(resource.get("valueString"))

    observation = Observation(
        id=ctx.resource_id,
        patient_id=patient_id,
        code_system=concept["system"],
        code=concept["code"],
        display=concept["display"],
        text=concept["text"],
        status=resource.get("status"),
        effective_at=effective_at,
        effective_precision=effective_precision,
        value_kind=value_kind,
        value_number=value_number,
        value_unit=value_unit,
        value_unit_canonical=value_unit_canonical,
        value_string=value_string,
        performer_ref=performer_ref,
        raw_json=resource,
    )

    if value_kind == ValueKind.COMPONENT:
        for part in resource.get("component", []):
            if not isinstance(part, dict):
                continue
            part_concept = normalize.extract_concept(part.get("code"))
            part_number, part_unit, part_canonical = normalize.extract_quantity(part.get("valueQuantity"))
            if part_unit and part_canonical is None:
                ctx.warn(IssueCode.UNKNOWN_UNIT, f"Unit {part_unit!r} is not in the canonical unit map")
            observation.components.append(
                ObservationComponent(
                    code_system=part_concept["system"],
                    code=part_concept["code"],
                    display=part_concept["display"],
                    value_number=part_number,
                    value_unit=part_unit,
                    value_unit_canonical=part_canonical,
                )
            )

    ctx.session.add(observation)
