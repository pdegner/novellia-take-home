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
