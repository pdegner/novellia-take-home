"""Turning FHIR's flexible field shapes into columns we can query.

Three problems this module exists to solve, all of them present in the sample
file and all of them guaranteed to be worse in data we have not seen:

1. **Mixed date precision.** `onsetDateTime` is often date-only
   (`"2023-04-10"`) while `effectiveDateTime` carries a full instant
   (`"2025-01-05T08:00:00Z"`). We need one sortable column for the timeline
   without claiming a date-only value happened at midnight.

2. **Inconsistent units.** The file has `mmHg` with a UCUM code on one
   observation and bare `mmHg` on another, plus `beats/minute` where UCUM says
   `/min`. A range query must not depend on which clinic typed which spelling.

3. **Polymorphic values.** `valueQuantity`, `valueString`, and component-only
   observations all live in one table, discriminated by `value_kind`.
"""

import re
from datetime import datetime, timezone

from app.models import Precision, ValueKind

# FHIR's reduced-precision date forms, longest first so YYYY-MM-DD is tried
# before YYYY-MM. `datetime.fromisoformat` handles none of these.
_PARTIAL_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), Precision.DATE),
    (re.compile(r"^(\d{4})-(\d{2})$"), Precision.MONTH),
    (re.compile(r"^(\d{4})$"), Precision.YEAR),
]

# When a CodeableConcept carries several codings, prefer one of these over
# whatever happened to be first in the array. Ordering within the tuple does
# not matter -- the systems are for different domains and never compete.
PREFERRED_CODE_SYSTEMS = (
    "http://loinc.org",
    "http://snomed.info/sct",
    "http://www.nlm.nih.gov/research/umls/rxnorm",
    "http://hl7.org/fhir/sid/icd-10",
    "http://hl7.org/fhir/sid/icd-10-cm",
)

_EMPTY_CONCEPT: dict[str, str | None] = {
    "system": None,
    "code": None,
    "display": None,
    "text": None,
}


def _as_text(value: object) -> str | None:
    """Coerce a scalar to a trimmed string, or None.

    Codes arrive as numbers often enough to be worth handling (`"code": 8867`).
    SQLite would store the int in a String column without complaint, and the
    mismatch would only surface later as a query that silently matches nothing.
    Containers are rejected rather than stringified -- `str({'a': 1})` is never
    a code anyone meant to send.
    """
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    if isinstance(value, (int, float)):
        return str(value)
    return None

# Canonical unit map: lowercased source spelling -> the UCUM code we store in
# `value_unit_canonical`. The spelling as received is kept alongside it, so a
# response can still echo back exactly what the clinic sent.
#
# THE RULE: every entry maps a unit to a *synonym of itself*. Never a
# conversion. `lb -> kg` would look like tidying up and would silently corrupt
# every weight in the database, because we canonicalise the label without
# touching the number. Different scales get different canonical codes and are
# left for a caller to convert deliberately, or not at all.
#
# This map is hand-maintained and deliberately small -- it covers what the
# sample data contains plus the obvious spellings of the same units. It is not
# an attempt to enumerate UCUM. Anything not listed canonicalises to None,
# which handlers report as UNKNOWN_UNIT, so an unrecognised unit shows up in
# /ingest/report rather than quietly poisoning a range query. Being *told* about
# the gap is the design goal; closing every gap in advance is not achievable.
UNIT_ALIASES: dict[str, str] = {
    # Pressure
    "mmhg": "mm[Hg]",
    "mm[hg]": "mm[Hg]",
    "mm hg": "mm[Hg]",
    # Rate (per minute)
    "beats/minute": "/min",
    "beats/min": "/min",
    "beats per minute": "/min",
    "bpm": "/min",
    "/min": "/min",
    "1/min": "/min",
    "breaths/minute": "/min",
    # Proportion
    "%": "%",
    "percent": "%",
    # Mass concentration
    "mg/dl": "mg/dL",
    # Substance concentration -- NOT interchangeable with mg/dL, which is why
    # they canonicalise differently rather than to a shared "concentration".
    "mmol/l": "mmol/L",
    # Mass
    "kg": "kg",
    "kgs": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "g": "g",
    "lb": "[lb_av]",
    "lbs": "[lb_av]",
    # Length
    "cm": "cm",
    "m": "m",
    # Enzyme / hormone activity
    "miu/l": "mIU/L",
    "iu/l": "[IU]/L",
    "u/l": "U/L",
    # Temperature -- again, deliberately distinct canonical codes.
    "c": "Cel",
    "cel": "Cel",
    "degc": "Cel",
    "f": "[degF]",
    "degf": "[degF]",
}


def parse_fhir_datetime(value: object) -> tuple[datetime | None, str | None]:
    """Parse a FHIR date or dateTime into (naive UTC datetime, precision).

    Returns `(None, None)` for anything unparseable, leaving the caller to
    decide whether that deserves an issue -- an absent optional date is normal,
    a malformed one is not, and only the handler knows which field it is.

    Three decisions worth defending:

    * **Partial dates are parsed, not rejected.** FHIR permits `YYYY` and
      `YYYY-MM`, and `datetime.fromisoformat` rejects both, so the reduced
      forms are matched explicitly. Missing parts are padded to January 1st
      purely so the value can be ordered; `precision` is what stops that
      padding being read as fact.
    * **Everything is stored naive-UTC.** Offsets are converted, then tzinfo is
      dropped. SQLite will happily store a mix of aware and naive values in one
      column, and Python raises when you try to sort them against each other --
      so the timeline would break on whichever record happened to arrive
      without a `Z`.
    * **A naive input is assumed to be UTC.** FHIR requires an offset on
      instants; feeds omit it anyway. Assuming UTC is a guess, but it is a
      bounded one, and refusing the value would discard a real measurement over
      a formatting error.
    """
    if not isinstance(value, str):
        return None, None

    text = value.strip()
    if not text:
        return None, None

    # Reduced-precision forms first: fromisoformat cannot parse these.
    for pattern, precision in _PARTIAL_DATE_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        parts = [int(part) for part in match.groups()]
        year, month, day = (parts + [1, 1])[:3]
        try:
            return datetime(year, month, day), precision
        except ValueError:
            # Well-formed but impossible, e.g. 2023-02-30.
            return None, None

    candidate = f"{text[:-1]}+00:00" if text[-1] in "Zz" else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None, None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed, Precision.INSTANT


def canonical_unit(unit: object) -> str | None:
    """Map a source unit spelling to its canonical UCUM code, or None if unknown.

    Returning None for an unrecognised unit is the important half. The
    tempting alternative -- falling back to the original spelling -- would make
    `value_unit_canonical` a column that is *sometimes* canonical, and a range
    query filtering on it would then silently miss every record from a clinic
    that spelled the unit differently. A NULL is a gap you can see; a
    plausible-looking wrong value is not.

    Handlers pair this with an UNKNOWN_UNIT issue when a unit was present but
    did not canonicalise, which is how a unit we have never seen becomes a line
    in /ingest/report instead of a silent hole in the data.
    """
    if not isinstance(unit, str):
        return None
    key = unit.strip().lower()
    return UNIT_ALIASES.get(key)


def extract_concept(concept: object) -> dict[str, str | None]:
    """Flatten a FHIR CodeableConcept into system / code / display / text.

    Returns all-None rather than raising when the concept is missing. That is
    the whole point: `cond-nw-bad-001` is an active diagnosis with no `code` at
    all, and it still belongs in the patient's history. A function that threw
    here would turn one malformed field into a lost condition.

    No fallback between fields happens here -- `display` and `text` are
    returned as received and stored in separate columns. Choosing a label from
    them is a presentation decision, so it lives at serialisation, where it can
    be changed without a reload.

    When several codings are present (real feeds routinely carry SNOMED plus
    ICD-10 plus a local code), the first from a recognised system wins, falling
    back to the first coding of any kind. Always taking `coding[0]` would make
    the stored code depend on the sending system's array order.
    """
    if concept is None:
        return _EMPTY_CONCEPT.copy()

    # Tolerate a bare string where a CodeableConcept was expected. It is not
    # valid FHIR, but it is unambiguous: treat it as the human text and claim
    # no code, rather than discarding a label we can plainly read.
    if isinstance(concept, str):
        return {**_EMPTY_CONCEPT, "text": _as_text(concept)}

    if not isinstance(concept, dict):
        return _EMPTY_CONCEPT.copy()

    text = _as_text(concept.get("text"))

    codings = concept.get("coding")
    if not isinstance(codings, list):
        codings = []
    codings = [entry for entry in codings if isinstance(entry, dict)]

    chosen: dict | None = None
    for entry in codings:
        if entry.get("system") in PREFERRED_CODE_SYSTEMS:
            chosen = entry
            break
    if chosen is None and codings:
        chosen = codings[0]
    if chosen is None:
        return {**_EMPTY_CONCEPT, "text": text}

    return {
        "system": _as_text(chosen.get("system")),
        "code": _as_text(chosen.get("code")),
        "display": _as_text(chosen.get("display")),
        "text": text,
    }


def extract_status(concept: object) -> str | None:
    """Pull the code out of a status CodeableConcept.

    `clinicalStatus` and `verificationStatus` arrive as full CodeableConcepts
    (`{"coding": [{"system": ..., "code": "active"}]}`) but are only ever useful
    as the bare code, so they get flattened to a string column.
    """
    # TODO(Patti): reuse extract_concept and return its "code".
    raise NotImplementedError("extract_status")


def extract_quantity(quantity: object) -> tuple[float | None, str | None, str | None]:
    """Flatten a FHIR Quantity into (value, unit, canonical_unit).

    Be defensive about the numeric: real feeds send `"138"` as a string, and
    occasionally something that is not a number at all.
    """
    # TODO(Patti): coerce the value with float(), catching TypeError/ValueError.
    # Prefer the UCUM `code` field over `unit` when present -- `code` is the
    # machine-readable one; `unit` is the human label.
    raise NotImplementedError("extract_quantity")


def classify_value(resource: dict) -> str:
    """Decide which `ValueKind` an Observation carries.

    `quantity` when valueQuantity is present, `string` for valueString,
    `component` when the value lives in the components (blood pressure), and
    `none` when the observation records no value at all.
    """
    # TODO(Patti): check in that order and return the matching ValueKind.
    raise NotImplementedError("classify_value")


def decode_attachment(data: object) -> str:
    """Base64-decode a Binary payload into text.

    `docref-001` points at `Binary/binary-001`, whose `data` is base64. The
    consumer should never see base64, so we decode at ingest.

    Raises ValueError when the payload is not decodable, which the note handler
    turns into an ATTACHMENT_UNDECODABLE issue.
    """
    # TODO(Patti): base64.b64decode(..., validate=True), then .decode("utf-8").
    # Both steps can fail; wrap them into ValueError so callers catch one type.
    # Non-text contentTypes (a PDF attachment) should not be forced into str --
    # decide what to do there and document it.
    raise NotImplementedError("decode_attachment")


def patient_display_name(name: object) -> str | None:
    """Build a human-readable name from FHIR's `name` array.

    Prefers the entry with `use: "official"`. Every patient in the sample file
    has exactly one well-formed name, which is precisely why this should be
    written to tolerate zero, several, or malformed ones.
    """
    # TODO(Patti): return something like "Noah Wyle" from given + family.
    raise NotImplementedError("patient_display_name")


__all__ = [
    "UNIT_ALIASES",
    "Precision",
    "ValueKind",
    "canonical_unit",
    "classify_value",
    "decode_attachment",
    "extract_concept",
    "extract_quantity",
    "extract_status",
    "parse_fhir_datetime",
    "patient_display_name",
]
