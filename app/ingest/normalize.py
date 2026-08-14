"""Cleans up FHIR's messy field shapes so we can store and query them.

Three problems, all present in the sample file:

1. Dates come at different precisions -- "2023-04-10" in one place,
   "2025-01-05T08:00:00Z" in another. We need one sortable column without
   pretending a date-only value happened at midnight.
2. Units are spelled inconsistently -- "mmHg" and "beats/minute" and bare "%".
   Searching by value shouldn't depend on which clinic typed what.
3. Observation values come in three different shapes (number, text, or split
   into parts like blood pressure).
"""

import base64
import binascii
import re
from datetime import datetime, timezone

from app.models import Precision, ValueKind

# We only decode text attachments. A PDF forced through str() would be garbage.
_TEXT_CONTENT_TYPES = {"application/json", "application/xml"}

# FHIR allows partial dates. Longest pattern first so YYYY-MM-DD wins over YYYY-MM.
# datetime.fromisoformat() can't parse any of these.
_PARTIAL_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), Precision.DATE),
    (re.compile(r"^(\d{4})-(\d{2})$"), Precision.MONTH),
    (re.compile(r"^(\d{4})$"), Precision.YEAR),
]

# A record can carry several codes for the same thing (SNOMED plus a local one).
# Prefer these well-known systems over whatever happens to be listed first.
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

# Maps how a unit was written -> the standard spelling we store for searching.
#
# IMPORTANT: every line maps a unit to another name for the SAME unit. Never a
# conversion. Mapping "lb" to "kg" would look tidy and would quietly corrupt
# every weight, because we only change the label -- never the number.
#
# This list is maintained by hand and covers what the sample data uses plus
# obvious spellings. Anything missing returns None, which handlers report as
# UNKNOWN_UNIT so it shows up in /ingest/report. Knowing what we missed is the
# goal; predicting every unit in advance isn't possible.
UNIT_ALIASES: dict[str, str] = {
    # Pressure
    "mmhg": "mm[Hg]",
    "mm[hg]": "mm[Hg]",
    "mm hg": "mm[Hg]",
    # Per minute
    "beats/minute": "/min",
    "beats/min": "/min",
    "beats per minute": "/min",
    "bpm": "/min",
    "/min": "/min",
    "1/min": "/min",
    "breaths/minute": "/min",
    # Percentage
    "%": "%",
    "percent": "%",
    # Concentration -- mg/dL and mmol/L are different scales, so they stay
    # separate rather than collapsing to one "concentration".
    "mg/dl": "mg/dL",
    "mmol/l": "mmol/L",
    # Weight
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
    # Lab activity
    "miu/l": "mIU/L",
    "iu/l": "[IU]/L",
    "u/l": "U/L",
    # Temperature -- again kept separate, never converted.
    "c": "Cel",
    "cel": "Cel",
    "degc": "Cel",
    "f": "[degF]",
    "degf": "[degF]",
}


def _as_text(value: object) -> str | None:
    """Turn a value into a clean string, or None.

    Codes sometimes arrive as numbers. SQLite would store an int in a text
    column without complaining, and later searches would just find nothing.
    Booleans are rejected -- in Python bool is a kind of int, so True would
    otherwise become the string "True".
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


def parse_fhir_datetime(value: object) -> tuple[datetime | None, str | None]:
    """Parse a FHIR date into (timestamp, how precise it was).

    Returns (None, None) if it can't be parsed. The caller decides whether
    that's worth flagging -- only the handler knows if the field was required.

    Three choices worth knowing about:

    * Partial dates like "2019" are parsed, not rejected. Missing parts are
      filled in with January 1st just so the value can be sorted. The precision
      we return is what stops that filler being mistaken for fact.
    * Everything is stored as UTC with the timezone stripped off. SQLite will
      happily mix timezone-aware and naive dates in one column, and Python then
      crashes when you sort them together -- so the timeline would break on
      whichever record arrived without a "Z".
    * A timestamp with no timezone is assumed to be UTC. That's a guess, but a
      small one, and throwing away a real measurement over a formatting slip is
      worse.
    """
    if not isinstance(value, str):
        return None, None

    text = value.strip()
    if not text:
        return None, None

    for pattern, precision in _PARTIAL_DATE_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        parts = [int(part) for part in match.groups()]
        year, month, day = (parts + [1, 1])[:3]
        try:
            return datetime(year, month, day), precision
        except ValueError:
            # Looks right but isn't a real date, e.g. 2023-02-30.
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
    """Look up the standard spelling of a unit. Returns None if we don't know it.

    Returning None rather than the original spelling is the important part.
    Falling back to whatever was typed would make this column only sometimes
    standardised, and a search by value range would then quietly skip records
    from any clinic that spelled the unit differently. An empty value is a gap
    you can see; a plausible wrong one isn't.

    Handlers flag UNKNOWN_UNIT when a unit was present but we didn't recognise
    it, so it appears in /ingest/report instead of disappearing.
    """
    if not isinstance(unit, str):
        return None
    return UNIT_ALIASES.get(unit.strip().lower())


def extract_concept(concept: object) -> dict[str, str | None]:
    """Flatten a FHIR coded value into system / code / display / text.

    Returns all-None instead of raising when something's missing. That's the
    point: cond-nw-bad-001 is a real active diagnosis with no code at all, and
    it still belongs in the patient's history. Throwing here would turn one bad
    field into a lost condition.

    Display and text are returned exactly as received, with no falling back
    between them -- picking which one to show is a display decision, so it
    happens later and can be changed without reloading the data.

    If several codes are present, the first one from a system we recognise
    wins. Just taking the first in the list would mean the code we store
    depends on the order the sender happened to use.
    """
    if concept is None:
        return _EMPTY_CONCEPT.copy()

    # Sometimes a plain string turns up where a coded value belongs. Not valid
    # FHIR, but readable -- treat it as the text and claim no code.
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
    """Get a status value, whether it arrived as plain text or a coded value.

    FHIR is inconsistent about this even within one file: Observation.status is
    plain ("final") while Condition.clinicalStatus is a coded object. Handling
    both here means handlers don't have to remember which is which.

    Lowercased, because these get compared in filters and "Active" vs "active"
    would split one status into two without anything looking broken.
    """
    if isinstance(concept, str):
        text = _as_text(concept)
        return text.lower() if text else None

    code = extract_concept(concept)["code"]
    return code.lower() if code else None


def extract_quantity(quantity: object) -> tuple[float | None, str | None, str | None]:
    """Split a measurement into (number, unit as written, standard unit).

    Both unit fields are used, because they're for different readers. `unit` is
    what the clinic typed and we keep it to show people. `code` is the
    machine-readable version and is the better thing to standardise from.
    Using `code` for both would throw away the clinic's own wording, which we
    promised to show back.

    Numbers often arrive as text ("72.5") so those are converted. Booleans are
    rejected: float(True) is 1.0, which would look like a real reading of 1.
    """
    if not isinstance(quantity, dict):
        return None, None, None

    raw_value = quantity.get("value")
    value: float | None
    if isinstance(raw_value, bool) or raw_value is None:
        value = None
    elif isinstance(raw_value, (int, float)):
        value = float(raw_value)
    elif isinstance(raw_value, str):
        try:
            value = float(raw_value.strip())
        except ValueError:
            value = None
    else:
        value = None

    label = _as_text(quantity.get("unit"))
    code = _as_text(quantity.get("code"))

    unit = label or code
    canonical = canonical_unit(code) or canonical_unit(label)
    return value, unit, canonical


def classify_value(resource: dict) -> str:
    """Work out which kind of value an Observation holds.

    Order matters. A record with both a top-level value and parts is malformed;
    treating the top-level one as the real answer keeps the number we were
    plainly given, with the parts still stored alongside.

    Parts are checked before "no value" so blood pressure -- which has no
    top-level value at all -- isn't misread as an empty result.
    """
    if not isinstance(resource, dict):
        return ValueKind.NONE

    if isinstance(resource.get("valueQuantity"), dict):
        return ValueKind.QUANTITY
    if _as_text(resource.get("valueString")):
        return ValueKind.STRING

    components = resource.get("component")
    if isinstance(components, list) and any(isinstance(c, dict) for c in components):
        return ValueKind.COMPONENT

    return ValueKind.NONE


def decode_attachment(data: object, content_type: object = None) -> str:
    """Decode a base64 attachment into text.

    Note text sometimes sits in a separate Binary record as base64. We decode
    it once here so no client ever has to.

    Only text is decoded. A PDF or image would come out as garbage, and a note
    full of garbage is worse than one honestly marked unreadable -- so those
    raise instead, and the handler records the reason with the note still saved.

    Raises:
        ValueError: no payload, not valid base64, or not readable as text.
    """
    if not isinstance(data, str) or not data.strip():
        raise ValueError("Binary has no data payload")

    declared = _as_text(content_type)
    if declared and not (declared.startswith("text/") or declared in _TEXT_CONTENT_TYPES):
        raise ValueError(f"Attachment content type {declared!r} is not text")

    try:
        decoded = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Payload is not valid base64: {exc}") from exc

    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Payload did not decode as UTF-8 text: {exc}") from exc


def _preferred_name(name: object) -> dict | None:
    """Pick which name entry to use: the official one, else the first usable one."""
    entries = [name] if isinstance(name, dict) else name
    if not isinstance(entries, list):
        return None

    entries = [entry for entry in entries if isinstance(entry, dict)]
    if not entries:
        return None

    return next((e for e in entries if e.get("use") == "official"), entries[0])


def patient_display_name(name: object) -> str | None:
    """Build a readable name like "John Doe" from FHIR's name list.

    Every patient in the sample file has exactly one tidy name, which is
    exactly why this copes with none, several, or broken ones. Returns None
    rather than a half-built string so callers can tell "no name" apart from a
    blank one.
    """
    chosen = _preferred_name(name)
    if chosen is None:
        return _as_text(name)

    # FHIR sometimes provides the whole name already formatted.
    if rendered := _as_text(chosen.get("text")):
        return rendered

    given = chosen.get("given")
    given_parts = [_as_text(p) for p in given] if isinstance(given, list) else [_as_text(given)]
    parts = [part for part in given_parts if part]

    if family := _as_text(chosen.get("family")):
        parts.append(family)

    return " ".join(parts) or None


def given_names(name: object) -> list[str]:
    """The first names from the chosen name entry."""
    chosen = _preferred_name(name)
    if chosen is None:
        return []

    given = chosen.get("given")
    if not isinstance(given, list):
        given = [given]
    return [part for part in (_as_text(p) for p in given) if part]


def family_name(name: object) -> str | None:
    """The surname from the chosen name entry."""
    chosen = _preferred_name(name)
    return _as_text(chosen.get("family")) if chosen else None


def render_temporal(moment: datetime | None, precision: str | None) -> str | None:
    """Write a stored date back out as precisely as it came in.

    The reverse of parse_fhir_datetime, and the reason precision is worth a
    column: "2019" goes in and "2019" comes back out, rather than
    "2019-01-01T00:00:00" implying a day and time nobody recorded.
    """
    if moment is None:
        return None
    if precision == Precision.YEAR:
        return f"{moment.year:04d}"
    if precision == Precision.MONTH:
        return f"{moment.year:04d}-{moment.month:02d}"
    if precision == Precision.DATE:
        return moment.date().isoformat()
    return moment.replace(microsecond=0).isoformat() + "Z"


__all__ = [
    "PREFERRED_CODE_SYSTEMS",
    "UNIT_ALIASES",
    "Precision",
    "ValueKind",
    "canonical_unit",
    "classify_value",
    "decode_attachment",
    "extract_concept",
    "extract_quantity",
    "extract_status",
    "family_name",
    "given_names",
    "parse_fhir_datetime",
    "patient_display_name",
    "render_temporal",
]
