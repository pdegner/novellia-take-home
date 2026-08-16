"""Unit tests for the pure functions in app/ingest/normalize.py.

No database needed -- every function here takes a FHIR fragment and returns a
plain value.
"""

import base64
from datetime import datetime

from app.ingest.normalize import (
    _as_text,
    canonical_unit,
    classify_value,
    decode_attachment,
    extract_concept,
    extract_quantity,
    extract_status,
    family_name,
    given_names,
    parse_fhir_datetime,
    patient_display_name,
    render_temporal,
)
from app.models import Precision, ValueKind


def test_as_text_strips_and_returns_strings():
    assert _as_text("active") == "active"
    assert _as_text("  active  ") == "active"


def test_as_text_blank_string_is_none():
    assert _as_text("") is None
    assert _as_text("   ") is None


def test_as_text_none_is_none():
    assert _as_text(None) is None


def test_as_text_numbers_become_strings():
    # Codes sometimes arrive as numbers; SQLite would store them silently and
    # later string searches would just find nothing.
    assert _as_text(72) == "72"
    assert _as_text(98.6) == "98.6"


def test_as_text_rejects_bool():
    # bool is a subclass of int in Python, so without this True -> "1".
    assert _as_text(True) is None
    assert _as_text(False) is None


def test_as_text_rejects_containers():
    assert _as_text({"system": "x"}) is None
    assert _as_text(["a", "b"]) is None
    assert _as_text(("a", "b")) is None
    assert _as_text({"a", "b"}) is None


def test_parse_datetime_full_instant_with_z():
    moment, precision = parse_fhir_datetime("2025-01-05T08:00:00Z")
    assert moment == datetime(2025, 1, 5, 8, 0, 0)
    assert precision == Precision.INSTANT


def test_parse_datetime_offset_is_converted_to_utc():
    # -05:00 at 08:00 is 13:00 UTC. Stored naive, so it sorts correctly
    # against every other timestamp in the same column.
    moment, precision = parse_fhir_datetime("2025-01-05T08:00:00-05:00")
    assert moment == datetime(2025, 1, 5, 13, 0, 0)
    assert precision == Precision.INSTANT
    assert moment.tzinfo is None


def test_parse_datetime_no_offset_is_assumed_utc():
    moment, precision = parse_fhir_datetime("2025-01-05T08:00:00")
    assert moment == datetime(2025, 1, 5, 8, 0, 0)
    assert precision == Precision.INSTANT


def test_parse_datetime_date_only():
    moment, precision = parse_fhir_datetime("2023-04-10")
    assert moment == datetime(2023, 4, 10)
    assert precision == Precision.DATE


def test_parse_datetime_year_month():
    moment, precision = parse_fhir_datetime("2019-06")
    assert moment == datetime(2019, 6, 1)
    assert precision == Precision.MONTH


def test_parse_datetime_year_only():
    moment, precision = parse_fhir_datetime("2019")
    assert moment == datetime(2019, 1, 1)
    assert precision == Precision.YEAR


def test_parse_datetime_invalid_calendar_date_is_none():
    # 2023-02-30 matches the YYYY-MM-DD pattern but isn't a real date.
    assert parse_fhir_datetime("2023-02-30") == (None, None)


def test_parse_datetime_garbage_is_none():
    assert parse_fhir_datetime("not a date") == (None, None)


def test_parse_datetime_blank_is_none():
    assert parse_fhir_datetime("") == (None, None)
    assert parse_fhir_datetime("   ") == (None, None)


def test_parse_datetime_non_string_is_none():
    assert parse_fhir_datetime(None) == (None, None)
    assert parse_fhir_datetime(123) == (None, None)


def test_canonical_unit_normalizes_case_and_spacing():
    assert canonical_unit("mmHg") == "mm[Hg]"
    assert canonical_unit(" MMHG ") == "mm[Hg]"
    assert canonical_unit("mm Hg") == "mm[Hg]"


def test_canonical_unit_synonyms_converge():
    # Different clinics, same unit -- all of these must land on one spelling
    # or a range query would silently miss whichever synonym it didn't check.
    assert canonical_unit("beats/minute") == "/min"
    assert canonical_unit("bpm") == "/min"
    assert canonical_unit("beats per minute") == "/min"


def test_canonical_unit_never_converts_lb_to_kg():
    # The map may only rename a unit, never convert the number. lb and kg are
    # different scales, so they must stay on different canonical spellings.
    assert canonical_unit("lb") == "[lb_av]"
    assert canonical_unit("lbs") == "[lb_av]"
    assert canonical_unit("kg") == "kg"


def test_canonical_unit_unknown_is_none_not_original():
    # Falling back to the original spelling would make this column only
    # sometimes standardised.
    assert canonical_unit("furlongs") is None


def test_canonical_unit_non_string_is_none():
    assert canonical_unit(None) is None
    assert canonical_unit(5) is None
    assert canonical_unit({}) is None


def test_extract_concept_none_is_all_none():
    assert extract_concept(None) == {
        "system": None, "code": None, "display": None, "text": None,
    }


def test_extract_concept_bare_string_becomes_text():
    # Not valid FHIR, but readable -- treated as text, no code claimed.
    assert extract_concept("just a string") == {
        "system": None, "code": None, "display": None, "text": "just a string",
    }


def test_extract_concept_wrong_type_is_all_none():
    assert extract_concept(123) == {
        "system": None, "code": None, "display": None, "text": None,
    }


def test_extract_concept_text_only_no_coding():
    assert extract_concept({"text": "Hypertension"}) == {
        "system": None, "code": None, "display": None, "text": "Hypertension",
    }


def test_extract_concept_missing_code_is_not_an_error():
    # cond-nw-bad-001: a real active diagnosis with no code at all. It still
    # belongs in the patient's history.
    assert extract_concept({}) == {
        "system": None, "code": None, "display": None, "text": None,
    }


def test_extract_concept_prefers_known_system_over_list_order():
    # A local code listed first must not win over LOINC listed second --
    # the stored code shouldn't depend on the sender's array order.
    concept = {
        "text": "BP",
        "coding": [
            {"system": "http://example.org/local", "code": "X1", "display": "Local BP"},
            {"system": "http://loinc.org", "code": "8480-6", "display": "Systolic BP"},
        ],
    }
    assert extract_concept(concept) == {
        "system": "http://loinc.org",
        "code": "8480-6",
        "display": "Systolic BP",
        "text": "BP",
    }


def test_extract_concept_falls_back_to_first_coding_when_none_recognized():
    concept = {"coding": [{"system": "http://example.org/local", "code": "X1"}]}
    result = extract_concept(concept)
    assert result["system"] == "http://example.org/local"
    assert result["code"] == "X1"


def test_extract_concept_empty_coding_list_is_all_none_but_keeps_text():
    assert extract_concept({"text": "note", "coding": []}) == {
        "system": None, "code": None, "display": None, "text": "note",
    }


def test_extract_concept_malformed_coding_entries_are_skipped():
    concept = {"coding": ["not a dict", {"system": "x", "code": "y"}]}
    result = extract_concept(concept)
    assert result["system"] == "x"
    assert result["code"] == "y"


def test_extract_concept_coding_not_a_list_is_ignored():
    assert extract_concept({"coding": "not a list"}) == {
        "system": None, "code": None, "display": None, "text": None,
    }


def test_extract_status_plain_string_is_lowercased():
    assert extract_status("Active") == "active"


def test_extract_status_coded_value_uses_the_code():
    assert extract_status({"coding": [{"system": "http://loinc.org", "code": "Final"}]}) == "final"


def test_extract_status_missing_is_none():
    assert extract_status(None) is None
    assert extract_status(123) is None


def test_extract_quantity_prefers_code_for_canonical_but_keeps_unit_label():
    value, unit, canonical = extract_quantity({"value": 72, "unit": "beats/minute", "code": "bpm"})
    assert value == 72.0
    assert unit == "beats/minute"
    assert canonical == "/min"


def test_extract_quantity_string_number_is_converted():
    value, unit, canonical = extract_quantity({"value": "72.5", "unit": "kg"})
    assert value == 72.5
    assert unit == "kg"
    assert canonical == "kg"


def test_extract_quantity_rejects_bool_value():
    # float(True) == 1.0, which would look like a real reading of 1.
    value, unit, canonical = extract_quantity({"value": True, "unit": "kg"})
    assert value is None


def test_extract_quantity_unparseable_string_value_is_none():
    value, unit, canonical = extract_quantity({"value": "not a number", "unit": "kg"})
    assert value is None


def test_extract_quantity_not_a_dict_is_all_none():
    assert extract_quantity("not a dict") == (None, None, None)


def test_extract_quantity_no_unit_is_all_none_unit():
    assert extract_quantity({"value": 5}) == (5.0, None, None)


def test_extract_quantity_unrecognized_unit_keeps_label_but_canonical_is_none():
    value, unit, canonical = extract_quantity({"value": 5, "unit": "furlongs"})
    assert unit == "furlongs"
    assert canonical is None


def test_classify_value_quantity():
    assert classify_value({"valueQuantity": {"value": 5}}) == ValueKind.QUANTITY


def test_classify_value_string():
    assert classify_value({"valueString": "abnormal"}) == ValueKind.STRING


def test_classify_value_blank_string_does_not_count():
    assert classify_value({"valueString": "   "}) == ValueKind.NONE


def test_classify_value_component_only():
    # Blood pressure: no top-level value at all.
    assert classify_value({"component": [{"code": {}}]}) == ValueKind.COMPONENT


def test_classify_value_quantity_wins_over_component_when_both_present():
    # A malformed record with both -- keep the number we were plainly given.
    resource = {"valueQuantity": {"value": 5}, "component": [{"code": {}}]}
    assert classify_value(resource) == ValueKind.QUANTITY


def test_classify_value_nothing_present():
    assert classify_value({}) == ValueKind.NONE


def test_classify_value_not_a_dict():
    assert classify_value("not a dict") == ValueKind.NONE


def test_decode_attachment_round_trips_text():
    payload = base64.b64encode(b"hello world").decode()
    assert decode_attachment(payload, "text/plain") == "hello world"


def test_decode_attachment_no_content_type_is_allowed():
    payload = base64.b64encode(b"hello world").decode()
    assert decode_attachment(payload) == "hello world"


def test_decode_attachment_json_content_type_is_text():
    payload = base64.b64encode(b'{"a": 1}').decode()
    assert decode_attachment(payload, "application/json") == '{"a": 1}'


def test_decode_attachment_rejects_non_text_content_type():
    payload = base64.b64encode(b"%PDF-1.4...").decode()
    try:
        decode_attachment(payload, "application/pdf")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "not text" in str(exc)


def test_decode_attachment_rejects_invalid_base64():
    try:
        decode_attachment("not-base64!!!", "text/plain")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_decode_attachment_rejects_empty_payload():
    for empty in ("", "   ", None):
        try:
            decode_attachment(empty, "text/plain")
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_decode_attachment_rejects_non_utf8_bytes():
    payload = base64.b64encode(b"\xff\xfe").decode()
    try:
        decode_attachment(payload, "text/plain")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "UTF-8" in str(exc)


def test_patient_display_name_prefers_official_entry():
    name = [
        {"use": "nickname", "given": ["Noah"], "family": "W"},
        {"use": "official", "given": ["Noah"], "family": "Wyle"},
    ]
    assert patient_display_name(name) == "Noah Wyle"


def test_patient_display_name_single_entry_no_use():
    assert patient_display_name([{"given": ["Noah"], "family": "Wyle"}]) == "Noah Wyle"


def test_patient_display_name_bare_dict_not_wrapped_in_list():
    assert patient_display_name({"given": ["Noah"], "family": "Wyle"}) == "Noah Wyle"


def test_patient_display_name_prefers_pre_rendered_text():
    assert patient_display_name({"text": "Noah Wyle"}) == "Noah Wyle"


def test_patient_display_name_given_as_bare_string_not_list():
    assert patient_display_name([{"given": "Noah", "family": "Wyle"}]) == "Noah Wyle"


def test_patient_display_name_none_is_none():
    assert patient_display_name(None) is None


def test_patient_display_name_empty_list_is_none():
    assert patient_display_name([]) is None


def test_given_names_returns_all_given_parts():
    name = [{"use": "official", "given": ["Noah", "David"], "family": "Wyle"}]
    assert given_names(name) == ["Noah", "David"]


def test_given_names_none_is_empty_list():
    assert given_names(None) == []


def test_family_name_from_official_entry():
    name = [{"use": "official", "given": ["Noah"], "family": "Wyle"}]
    assert family_name(name) == "Wyle"


def test_family_name_none_is_none():
    assert family_name(None) is None


def test_render_temporal_round_trips_each_precision():
    assert render_temporal(datetime(2019, 1, 1), Precision.YEAR) == "2019"
    assert render_temporal(datetime(2019, 6, 1), Precision.MONTH) == "2019-06"
    assert render_temporal(datetime(2023, 4, 10), Precision.DATE) == "2023-04-10"
    assert render_temporal(datetime(2025, 1, 5, 8, 0, 0), Precision.INSTANT) == "2025-01-05T08:00:00Z"


def test_render_temporal_none_is_none():
    assert render_temporal(None, Precision.DATE) is None
