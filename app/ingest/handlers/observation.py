"""Observation -> observations + observation_components."""

from app.ingest.context import IngestContext
from app.ingest.registry import register


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
    # TODO(Patti): classify_value first, then branch. Add ObservationComponent
    # rows via the `components` relationship so the cascade handles them.
    raise NotImplementedError("handle_observation")
