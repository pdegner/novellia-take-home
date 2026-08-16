"""The API answers even when the data underneath it is a disaster."""

from tests.conftest import FIXTURES

NASTY = FIXTURES / "nasty.jsonl"


def test_health_responds(client, load):
    load(NASTY)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ingest_report_reconciles(client, load):
    summary = load(NASTY)
    body = client.get("/ingest/report").json()
    assert body["total_lines"] == summary.lines_read
    assert body["accepted"] + body["rejected"] + body["unknown_type"] == body["total_lines"]


def test_issues_are_filterable_by_code(client, load):
    load(NASTY)
    body = client.get("/ingest/issues", params={"code": "UNKNOWN_RESOURCE_TYPE"}).json()
    assert body["total"] >= 4
    assert all(item["code"] == "UNKNOWN_RESOURCE_TYPE" for item in body["items"])


def test_raw_passthrough_serves_unmodelled_types(client, load):
    """An Encounter has no handler and no table, yet is still retrievable."""
    load(NASTY)
    response = client.get("/fhir/Encounter/enc-001")
    assert response.status_code == 200
    assert response.json()["resourceType"] == "Encounter"


def test_raw_passthrough_404_uses_the_error_envelope(client, load):
    load(NASTY)
    response = client.get("/fhir/Patient/nobody-here")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_validation_errors_use_the_error_envelope(client, load):
    load(NASTY)
    response = client.get("/ingest/issues", params={"limit": 0})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_patient_list_and_detail_survive_hostile_data(client, load):
    load(NASTY)
    assert client.get("/patients").status_code == 200
    assert client.get("/patients/ok-patient").status_code == 200


def test_summary_survives_hostile_sibling_data(client, load):
    """The flagship endpoint, not just health/ingest -- a garbage-date
    observation or a no-code condition on ok-patient must not 500 the chart
    view for every other record on it."""
    load(NASTY)
    response = client.get("/patients/ok-patient/summary")
    assert response.status_code == 200


def test_timeline_survives_hostile_sibling_data(client, load):
    load(NASTY)
    response = client.get("/patients/ok-patient/timeline")
    assert response.status_code == 200


def test_all_list_endpoints_survive_hostile_data(client, load):
    load(NASTY)
    for resource in ("conditions", "medications", "observations", "procedures", "notes"):
        response = client.get(f"/patients/ok-patient/{resource}")
        assert response.status_code == 200, resource


def test_unreadable_attachments_still_render_with_a_reason(client, load):
    """docref-missing-binary and docref-bad-base64 are notes the API can
    show, not silent gaps -- the note demonstrably exists, only its text
    doesn't."""
    load(NASTY)
    notes = {n["id"]: n for n in client.get("/patients/ok-patient/notes").json()["items"]}
    for note_id in ("docref-missing-binary", "docref-bad-base64"):
        assert notes[note_id]["text"] is None
        assert notes[note_id]["text_unavailable_reason"]


def test_case_varied_patient_id_returns_the_same_records(client, load):
    """Regression test for a real bug (see DECISIONS.md, 'Query layer'):
    `_resolve_patient_id` once confirmed the patient existed
    case-insensitively but then filtered sub-resources on the caller's
    original-case id, so `/patients/OK-PATIENT/conditions` silently returned
    zero results instead of the real ones. Caught by a manual curl during
    phase 3, not by this suite -- closing that gap here."""
    load(NASTY)
    canonical = client.get("/patients/ok-patient/conditions").json()
    upper = client.get("/patients/OK-PATIENT/conditions").json()
    assert upper["total"] == canonical["total"] > 0
