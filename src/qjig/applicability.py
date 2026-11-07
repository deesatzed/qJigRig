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
