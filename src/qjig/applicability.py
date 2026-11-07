"""Per-source applicability metadata: dates, scope, authority, entity keys. Pure functions.

Dates and identifiers here are recorded provenance, not authenticated truth. Unknown is never
treated as compatible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .contracts import ContractError


class Applicability(Enum):
    MATCH = "match"
    NO_MATCH = "no_match"
    UNKNOWN = "unknown"


class _Bound(Enum):
    OPEN = "open"  # explicitly no limit
    UNKNOWN = "unknown"  # nobody recorded the boundary


OPEN = _Bound.OPEN
UNKNOWN_BOUND = _Bound.UNKNOWN

_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_date(value: object) -> date:
    if not isinstance(value, str) or not _ISO.fullmatch(value):
        raise ContractError(f"date must be an ISO calendar date YYYY-MM-DD, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(f"invalid calendar date {value!r}") from exc


def _bound(value: object) -> date | _Bound:
    return value if isinstance(value, _Bound) else parse_date(value)


@dataclass(frozen=True)
class Interval:
    """Inclusive [start, end]. Each boundary is an ISO date, OPEN (end only) or UNKNOWN_BOUND."""

    start: object
    end: object

    def __post_init__(self) -> None:
        s, e = _bound(self.start), _bound(self.end)
        if s is OPEN:
            raise ContractError("an open start is not defined; use UNKNOWN_BOUND or a date")
        if isinstance(s, date) and isinstance(e, date) and s > e:
            raise ContractError(f"interval start {self.start} is after end {self.end}")

    def contains(self, day: str) -> Applicability:
        d = parse_date(day)
        s, e = _bound(self.start), _bound(self.end)
        if isinstance(s, date) and d < s:
            return Applicability.NO_MATCH
        if isinstance(e, date) and d > e:
            return Applicability.NO_MATCH
        if s is UNKNOWN_BOUND or e is UNKNOWN_BOUND:
            return Applicability.UNKNOWN
        return Applicability.MATCH


@dataclass(frozen=True)
class MemberMetadata:
    revision_id: str
    scope: str
    effective: Interval
    authority_id: str | None = None
    entity_keys: frozenset[str] = field(default_factory=frozenset)
    observed_at: str | None = None  # when this source was first recorded; None = unknown

    def __post_init__(self) -> None:
        if self.observed_at is not None:
            parse_date(self.observed_at)


@dataclass(frozen=True)
class Collection:
    """A set of sources. Members keep independent metadata; no collection-wide dates exist."""

    members: tuple[MemberMetadata, ...]

    def __post_init__(self) -> None:
        ids = [m.revision_id for m in self.members]
        if len(set(ids)) != len(ids):
            raise ContractError("a collection cannot contain the same revision twice")

    def member(self, revision_id: str) -> MemberMetadata:
        for m in self.members:
            if m.revision_id == revision_id:
                return m
        raise KeyError(revision_id)


@dataclass(frozen=True)
class Verdict:
    value: Applicability
    reason: str


def entity_applicability(member: MemberMetadata, request_entities: frozenset[str]) -> Verdict:
    """Does this source's recorded subject match the request's subject?

    Missing data on either side is UNKNOWN. Only two recorded, disjoint subject sets are NO_MATCH.
    Keys compare exactly.
    """
    source = member.entity_keys
    if not request_entities:
        if source:
            return Verdict(Applicability.UNKNOWN, "request_entity_missing")
        return Verdict(Applicability.MATCH, "no_entity_binding_required")
    if not source:
        return Verdict(Applicability.UNKNOWN, "source_entity_unrecorded")
    if source & request_entities:
        return Verdict(Applicability.MATCH, "entity_match")
    return Verdict(Applicability.NO_MATCH, "entity_mismatch")


@dataclass(frozen=True)
class DateVerdict:
    effective: Verdict
    observation: Verdict
    overall: Applicability


def date_applicability(
    member: MemberMetadata, as_of: str, *, historical_as_known: bool
) -> DateVerdict:
    """Effective-date and observation-date checks, kept separate and then combined.

    The observation check applies only to historical-as-known requests, which require
    observed_at <= as_of. An unknown observation date stays UNKNOWN there.
    """
    eff = member.effective.contains(as_of)
    effective = Verdict(eff, f"effective_{eff.value}")
    if not historical_as_known:
        observation = Verdict(Applicability.MATCH, "observation_not_required")
    elif member.observed_at is None:
        observation = Verdict(Applicability.UNKNOWN, "observation_date_unknown")
    elif parse_date(member.observed_at) > parse_date(as_of):
        observation = Verdict(Applicability.NO_MATCH, "observed_after_request")
    else:
        observation = Verdict(Applicability.MATCH, "observed_by_request")
    values = {effective.value, observation.value}
    if Applicability.NO_MATCH in values:
        overall = Applicability.NO_MATCH
    elif Applicability.UNKNOWN in values:
        overall = Applicability.UNKNOWN
    else:
        overall = Applicability.MATCH
    return DateVerdict(effective, observation, overall)


@dataclass(frozen=True)
class ApplicabilityInputs:
    """Recorded inputs for the existing entity/date checks; scope and authority are provenance."""

    collection: Collection
    request_entities: frozenset[str]
    as_of: str
    historical_as_known: bool

    def __post_init__(self) -> None:
        if not isinstance(self.collection, Collection):
            raise ContractError("collection is required")
        if not isinstance(self.request_entities, frozenset) or any(not isinstance(v, str) or not v for v in self.request_entities):
            raise ContractError("request entities must be a frozenset of non-empty strings")
        parse_date(self.as_of)
        if type(self.historical_as_known) is not bool:
            raise ContractError("historical_as_known must be boolean")

    def verdict(self, revision_id: str) -> Applicability:
        try:
            member = self.collection.member(revision_id)
        except KeyError:
            return Applicability.UNKNOWN
        values = {entity_applicability(member, self.request_entities).value,
                  date_applicability(member, self.as_of, historical_as_known=self.historical_as_known).overall}
        if Applicability.NO_MATCH in values:
            return Applicability.NO_MATCH
        return Applicability.UNKNOWN if Applicability.UNKNOWN in values else Applicability.MATCH

    def to_dict(self) -> dict:
        def bound(value):
            return value.value if isinstance(value, _Bound) else value
        return {"as_of": self.as_of, "historical_as_known": self.historical_as_known,
                "request_entities": sorted(self.request_entities),
                "scope_authority_assurance": "recorded_not_assessed",
                "members": [{"revision_id": m.revision_id, "scope": m.scope, "authority_id": m.authority_id,
                             "entity_keys": sorted(m.entity_keys), "effective_start": bound(m.effective.start),
                             "effective_end": bound(m.effective.end), "observed_at": m.observed_at}
                            for m in sorted(self.collection.members, key=lambda item: item.revision_id)]}

    @classmethod
    def from_dict(cls, data: dict) -> "ApplicabilityInputs":
        expected = {"as_of", "historical_as_known", "request_entities", "scope_authority_assurance", "members"}
        if not isinstance(data, dict) or set(data) != expected or data["scope_authority_assurance"] != "recorded_not_assessed":
            raise ContractError("invalid applicability input record")
        entities, rows = data["request_entities"], data["members"]
        if not isinstance(entities, list) or not all(isinstance(x, str) and x for x in entities) or len(set(entities)) != len(entities):
            raise ContractError("invalid request entities")
        if not isinstance(rows, list):
            raise ContractError("invalid member records")
        required = {"revision_id", "scope", "authority_id", "entity_keys", "effective_start", "effective_end", "observed_at"}
        members = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != required:
                raise ContractError("invalid member record")
            keys = row["entity_keys"]
            if (not isinstance(row["revision_id"], str) or not row["revision_id"] or
                not isinstance(row["scope"], str) or not row["scope"] or
                (row["authority_id"] is not None and not isinstance(row["authority_id"], str)) or
                not isinstance(keys, list) or not all(isinstance(x, str) and x for x in keys) or len(set(keys)) != len(keys)):
                raise ContractError("invalid member fields")
            def parse_bound(value):
                if value == "unknown":
                    return UNKNOWN_BOUND
                if value == "open":
                    return OPEN
                return value
            members.append(MemberMetadata(row["revision_id"], row["scope"],
                                          Interval(parse_bound(row["effective_start"]), parse_bound(row["effective_end"])),
                                          authority_id=row["authority_id"], entity_keys=frozenset(keys), observed_at=row["observed_at"]))
        return cls(Collection(tuple(members)), frozenset(entities), data["as_of"], data["historical_as_known"])
