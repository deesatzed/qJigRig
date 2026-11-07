import pytest

from qjig.applicability import (
    OPEN,
    UNKNOWN_BOUND,
    Applicability,
    Collection,
    Interval,
    MemberMetadata,
    parse_date,
)
from qjig.contracts import ContractError


def member(rev, start, end, **kw):
    return MemberMetadata(revision_id=rev, scope="project", effective=Interval(start, end), **kw)


def test_per_member_dates():
    old = member("rev-old", "2026-01-01", "2026-10-31")
    new = member("rev-new", "2026-11-01", OPEN)
    coll = Collection((old, new))  # JIG's legacy builder rejected exactly this
    # each member keeps its own interval; the collection has no shared one
    assert coll.member("rev-old").effective == Interval("2026-01-01", "2026-10-31")
    assert coll.member("rev-new").effective == Interval("2026-11-01", OPEN)
    assert not hasattr(coll, "effective")
    # on any date, the members answer independently
    assert old.effective.contains("2026-10-15") is Applicability.MATCH
    assert new.effective.contains("2026-10-15") is Applicability.NO_MATCH
    assert old.effective.contains("2026-11-15") is Applicability.NO_MATCH
    assert new.effective.contains("2026-11-15") is Applicability.MATCH
    # inclusive boundaries
    assert old.effective.contains("2026-10-31") is Applicability.MATCH
    assert new.effective.contains("2026-11-01") is Applicability.MATCH
    assert new.effective.contains("2099-01-01") is Applicability.MATCH  # open end


def test_unknown_boundary_is_not_compatible():
    unknown_end = Interval("2026-01-01", UNKNOWN_BOUND)
    assert unknown_end.contains("2026-06-01") is Applicability.UNKNOWN
    assert unknown_end.contains("2025-12-31") is Applicability.NO_MATCH  # before a known start
    unknown_start = Interval(UNKNOWN_BOUND, "2026-01-31")
    assert unknown_start.contains("2026-02-01") is Applicability.NO_MATCH  # after a known end
    assert unknown_start.contains("2026-01-15") is Applicability.UNKNOWN
    assert Interval(UNKNOWN_BOUND, UNKNOWN_BOUND).contains("2026-01-15") is Applicability.UNKNOWN


@pytest.mark.parametrize("bad", ["2026-13-01", "2026-02-30", "20261106", "2026-1-1", "", None, 20261106])
def test_dates_must_be_iso_calendar_dates(bad):
    with pytest.raises(ContractError):
        parse_date(bad)
    with pytest.raises(ContractError):
        Interval(bad, OPEN)


def test_interval_and_collection_validation():
    with pytest.raises(ContractError):
        Interval("2026-02-01", "2026-01-01")
    with pytest.raises(ContractError):
        Interval(OPEN, "2026-01-01")  # an open start is not defined in this contract
    with pytest.raises(ContractError):
        Collection((member("r", "2026-01-01", OPEN), member("r", "2026-02-01", OPEN)))


from qjig.applicability import entity_applicability


def ent(*keys):
    return member("r", "2026-01-01", OPEN, entity_keys=frozenset(keys))


def test_missing_entity_unknown():
    # source records no subject, request names one: unknown, never "not applicable"
    r = entity_applicability(ent(), frozenset({"customer:42"}))
    assert r.value is Applicability.UNKNOWN and r.reason == "source_entity_unrecorded"
    # request names no subject but source is about specific ones: unknown
    r = entity_applicability(ent("customer:42"), frozenset())
    assert r.value is Applicability.UNKNOWN and r.reason == "request_entity_missing"


def test_entity_match_and_explicit_mismatch():
    assert entity_applicability(ent("customer:42", "customer:7"), frozenset({"customer:7"})).value is Applicability.MATCH
    r = entity_applicability(ent("customer:42"), frozenset({"customer:7"}))
    assert r.value is Applicability.NO_MATCH and r.reason == "entity_mismatch"
    # neither side names a subject: nothing to bind
    assert entity_applicability(ent(), frozenset()).value is Applicability.MATCH
    # keys are compared exactly, not case-folded
    assert entity_applicability(ent("Customer:42"), frozenset({"customer:42"})).value is Applicability.NO_MATCH
