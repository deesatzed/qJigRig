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


from qjig.applicability import date_applicability


def dated(observed_at, start="2026-01-01", end=OPEN):
    return member("r", start, end, observed_at=observed_at)


def test_historical_observation():
    as_of = "2026-06-01"
    review = dated("2026-12-01")  # effective in June, but only recorded in December
    # as-currently-known: the late observation is fine
    assert date_applicability(review, as_of, historical_as_known=False).overall is Applicability.MATCH
    # as-known-then: a review observed after the request cannot settle it
    v = date_applicability(review, as_of, historical_as_known=True)
    assert v.overall is Applicability.NO_MATCH
    assert v.effective.value is Applicability.MATCH  # the two checks stay separate
    assert v.observation.value is Applicability.NO_MATCH and v.observation.reason == "observed_after_request"
    # observed on or before the request date is fine
    assert date_applicability(dated("2026-06-01"), as_of, historical_as_known=True).overall is Applicability.MATCH


def test_dates_are_applied_independently():
    as_of = "2026-06-01"
    # observed in time but not yet in effect: still no match, for the effective reason
    early = dated("2026-01-05", start="2026-09-01")
    v = date_applicability(early, as_of, historical_as_known=True)
    assert v.overall is Applicability.NO_MATCH
    assert v.effective.value is Applicability.NO_MATCH and v.observation.value is Applicability.MATCH
    # unknown observation date stays unresolved for historical requests, irrelevant otherwise
    unseen = dated(None)
    assert date_applicability(unseen, as_of, historical_as_known=True).overall is Applicability.UNKNOWN
    assert date_applicability(unseen, as_of, historical_as_known=False).overall is Applicability.MATCH
    # a definite NO_MATCH wins over an UNKNOWN
    both = dated(None, start="2026-09-01")
    assert date_applicability(both, as_of, historical_as_known=True).overall is Applicability.NO_MATCH
    with pytest.raises(ContractError):
        dated("12/01/2026")
