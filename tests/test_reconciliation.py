"""POST /ingest/issues/{id}/resolve -- closing the loop the reference ladder opens.

references.py refuses to guess and leaves ambiguous records orphaned. These
cover the human override: linking an orphan by hand, and every way that
override can be misused.
"""

from tests.conftest import FIXTURES

NASTY = FIXTURES / "nasty.jsonl"


def _issue_for(client, code, resource_type=None):
    params = {"code": code}
    if resource_type:
        params["resource_type"] = resource_type
    items = client.get("/ingest/issues", params=params).json()["items"]
    assert len(items) == 1, f"expected exactly one {code} issue, got {items}"
    return items[0]


def test_resolving_an_unknown_patient_reference_links_the_record(client, load):
    """obs-unknown-patient: a well-formed reference to a patient who doesn't
    exist. The ladder refuses to guess; a human saying "it's ok-patient" is
    allowed to finish the job."""
    load(NASTY)
    issue = _issue_for(client, "SUBJECT_UNKNOWN_PATIENT")

    response = client.post(f"/ingest/issues/{issue['id']}/resolve", json={"patient_id": "ok-patient"})
    assert response.status_code == 200
    body = response.json()
    assert body["resolved_patient_id"] == "ok-patient"
    assert body["resolved_at"] is not None

    observations = client.get("/patients/ok-patient/observations").json()["items"]
    assert any(o["id"] == "obs-unknown-patient" for o in observations)


def test_resolving_a_display_only_subject_links_the_record(client, load):
    """obs-display-only-subject: named but not referenced. The ladder refuses
    to name-match; a human recognizing the name can link it anyway."""
    load(NASTY)
    issue = _issue_for(client, "SUBJECT_UNRESOLVABLE")

    response = client.post(f"/ingest/issues/{issue['id']}/resolve", json={"patient_id": "ok-patient"})
    assert response.status_code == 200

    observations = client.get("/patients/ok-patient/observations").json()["items"]
    assert any(o["id"] == "obs-display-only-subject" for o in observations)


def test_resolving_a_missing_subject_links_the_record(client, load):
    """proc-no-subject: no subject at all, not even a display name."""
    load(NASTY)
    issue = _issue_for(client, "SUBJECT_MISSING", resource_type="Procedure")

    response = client.post(f"/ingest/issues/{issue['id']}/resolve", json={"patient_id": "ok-patient"})
    assert response.status_code == 200

    procedures = client.get("/patients/ok-patient/procedures").json()["items"]
    assert any(p["id"] == "proc-no-subject" for p in procedures)


def test_resolved_issue_is_kept_not_deleted(client, load):
    """A design call worth defending live (DECISIONS.md, 'Reconciliation'):
    resolving marks the issue, it doesn't erase the history of what was wrong."""
    load(NASTY)
    issue = _issue_for(client, "SUBJECT_UNKNOWN_PATIENT")
    client.post(f"/ingest/issues/{issue['id']}/resolve", json={"patient_id": "ok-patient"})

    refetched = client.get("/ingest/issues", params={"code": "SUBJECT_UNKNOWN_PATIENT"}).json()["items"]
    assert len(refetched) == 1
    assert refetched[0]["resolved_patient_id"] == "ok-patient"


def test_resolving_twice_is_rejected(client, load):
    load(NASTY)
    issue = _issue_for(client, "SUBJECT_UNKNOWN_PATIENT")
    client.post(f"/ingest/issues/{issue['id']}/resolve", json={"patient_id": "ok-patient"})

    response = client.post(f"/ingest/issues/{issue['id']}/resolve", json={"patient_id": "ok-patient"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"


def test_resolving_to_a_nonexistent_patient_404s_and_does_not_mutate(client, load):
    load(NASTY)
    issue = _issue_for(client, "SUBJECT_UNKNOWN_PATIENT")

    response = client.post(f"/ingest/issues/{issue['id']}/resolve", json={"patient_id": "nobody-at-all"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PATIENT_NOT_FOUND"

    # A failed resolve must not half-apply -- the record stays an orphan.
    unresolved = _issue_for(client, "SUBJECT_UNKNOWN_PATIENT")
    assert unresolved["resolved_at"] is None
    observations = client.get("/patients/ok-patient/observations").json()["items"]
    assert not any(o["id"] == "obs-unknown-patient" for o in observations)


def test_resolving_an_unknown_issue_404s(client, load):
    load(NASTY)
    response = client.post("/ingest/issues/999999/resolve", json={"patient_id": "ok-patient"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ISSUE_NOT_FOUND"


def test_resolving_a_non_orphan_issue_is_rejected(client, load):
    """obs-weird-unit is already linked -- UNKNOWN_UNIT is a unit problem, not
    a missing patient. There's nothing here for this endpoint to do."""
    load(NASTY)
    issue = _issue_for(client, "UNKNOWN_UNIT")

    response = client.post(f"/ingest/issues/{issue['id']}/resolve", json={"patient_id": "ok-patient"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY"
