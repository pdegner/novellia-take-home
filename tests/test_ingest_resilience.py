"""The load must survive anything the file throws at it.

These tests deliberately assert *resilience*, not clinical correctness: that no
input kills the process, that nothing vanishes silently, and that every
imperfection is addressable afterwards. They pass before the handlers are
written and must keep passing after.
"""

from sqlalchemy import func, select

from app.ingest import registry
from app.models import IngestIssue, IssueCode, RawResource, RawStatus
from tests.conftest import FIXTURES, REAL_DATA

NASTY = FIXTURES / "nasty.jsonl"


def _codes(session) -> set[str]:
    return set(session.execute(select(IngestIssue.code)).scalars().all())


def test_hostile_file_does_not_raise(load, session):
    """Twenty-five lines of malice, and the loader returns normally."""
    summary = load(NASTY)
    assert summary.lines_read > 0


def test_every_line_is_accounted_for(load, session):
    """accepted + rejected + unknown_type == lines read. Nothing dropped silently."""
    summary = load(NASTY)
    stored = session.scalar(select(func.count()).select_from(RawResource))
    assert stored == summary.lines_read
    assert summary.accepted + summary.rejected + summary.unknown_type == summary.lines_read


def test_malformed_lines_are_rejected_not_fatal(load, session):
    load(NASTY)
    rejected = session.execute(
        select(RawResource).where(RawResource.status == RawStatus.REJECTED)
    ).scalars().all()
    assert rejected, "expected the unparseable lines to be recorded"
    # The raw text is retained so an operator can see what actually arrived.
    assert any(r.raw_text and "not json at all" in r.raw_text for r in rejected)
    assert IssueCode.MALFORMED_JSON in _codes(session)


def test_unknown_resource_types_are_preserved_not_discarded(load, session):
    """The 'data you haven't seen' case.

    AllergyIntolerance, Encounter, Immunization and CarePlan have no handlers.
    They must land in the raw store, be counted, and stay retrievable.
    """
    load(NASTY)
    unknown = session.execute(
        select(RawResource.resource_type).where(RawResource.status == RawStatus.UNKNOWN_TYPE)
    ).scalars().all()
    assert {"AllergyIntolerance", "Encounter", "Immunization", "CarePlan"} <= set(unknown)
    assert IssueCode.UNKNOWN_RESOURCE_TYPE in _codes(session)


def test_duplicate_ids_are_flagged_and_first_wins(load, session):
    load(NASTY)
    assert IssueCode.DUPLICATE_ID in _codes(session)
    stored = session.execute(
        select(func.count())
        .select_from(RawResource)
        .where(RawResource.resource_id == "cond-dup", RawResource.status == RawStatus.ACCEPTED)
    ).scalar()
    assert stored == 1


def test_resource_without_id_is_flagged(load, session):
    load(NASTY)
    assert IssueCode.MISSING_ID in _codes(session)


def test_missing_file_is_survivable(load, session):
    """A misconfigured path must not stop the API from booting."""
    summary = load(FIXTURES / "does-not-exist.jsonl")
    assert summary.lines_read == 0


def test_empty_file_is_survivable(load, session, tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert load(empty).lines_read == 0


def test_real_file_loads_completely(load, session):
    """The supplied dataset: 129 resources, every line classified.

    (129, not 128 -- the file has no trailing newline, so `wc -l` undercounts.)
    """
    summary = load(REAL_DATA)
    assert summary.lines_read == 129
    assert summary.accepted + summary.rejected + summary.unknown_type == 129
    # Every resourceType in the file has a registered handler, so nothing in
    # the real data should fall through to unknown_type. If this fails, a
    # handler registration was lost.
    assert summary.unknown_type == 0


def test_all_expected_types_have_handlers():
    registry.load_handlers()
    expected = {
        "Patient", "Condition", "MedicationRequest", "Observation",
        "Procedure", "ClinicalNote", "Binary", "DocumentReference",
    }
    assert expected <= registry.registered_types()
