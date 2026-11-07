"""Verify retrieved candidates against stored sources; exclude unavailable ones; use alternatives."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .applicability import Applicability, Collection, date_applicability, entity_applicability
from .contracts import ContractError
from .packets import EvidencePacket, build_packet
from .retrieval import Candidate
from .spans import verify_span
from .store import Catalog


@dataclass(frozen=True)
class Exclusion:
    entry_id: str
    reason: str  # source_missing | source_changed | span_mismatch
    detail: str = ""


@dataclass(frozen=True)
class RecoveryResult:
    packet: EvidencePacket
    exclusions: tuple[Exclusion, ...]
    alternatives: dict[str, str]  # excluded entry_id -> the verified entry that took its place
    unfilled: int = 0  # requested evidence slots that no suitable candidate filled


def check_candidate(catalog: Catalog, c: Candidate) -> Exclusion | None:
    try:
        revision = catalog.get_revision(c.revision_id)
    except KeyError:
        return Exclusion(c.entry_id, "source_missing", c.revision_id)
    except ContractError as exc:
        return Exclusion(c.entry_id, "source_changed", str(exc))
    try:
        verify_span(revision, c.span)
    except ContractError as exc:
        return Exclusion(c.entry_id, "span_mismatch", str(exc))
    return None


def applicability_filter(
    collection: Collection, request_entities: frozenset[str], as_of: str, *, historical_as_known: bool
) -> Callable[[Candidate], Applicability]:
    """Combine entity and date applicability per source member. Missing metadata is UNKNOWN."""

    def check(c: Candidate) -> Applicability:
        try:
            member = collection.member(c.revision_id)
        except KeyError:
            return Applicability.UNKNOWN
        values = {
            entity_applicability(member, request_entities).value,
            date_applicability(member, as_of, historical_as_known=historical_as_known).overall,
        }
        if Applicability.NO_MATCH in values:
            return Applicability.NO_MATCH
        return Applicability.UNKNOWN if Applicability.UNKNOWN in values else Applicability.MATCH

    return check


def recover_packet(
    catalog: Catalog,
    candidates: list[Candidate],
    *,
    want: int,
    max_bytes: int,
    applicability: Callable[[Candidate], Applicability] | None = None,
) -> RecoveryResult:
    """Walk candidates in rank order, keep the first `want` that verify, record every exclusion.

    The packet is built only from verified candidates. Each exclusion is linked to the next
    verified candidate chosen after it, if any.
    """
    if type(want) is not int or want < 1:
        raise ContractError("want must be a positive integer")
    chosen: list[Candidate] = []
    exclusions: list[Exclusion] = []
    waiting: list[Exclusion] = []
    alternatives: dict[str, str] = {}
    for c in candidates:
        if len(chosen) >= want:
            break
        problem = check_candidate(catalog, c)
        if problem is None and applicability is not None:
            verdict = applicability(c)
            if verdict is Applicability.NO_MATCH:
                problem = Exclusion(c.entry_id, "inapplicable")
            elif verdict is Applicability.UNKNOWN:
                problem = Exclusion(c.entry_id, "applicability_unknown")
        if problem:
            exclusions.append(problem)
            waiting.append(problem)
            continue
        chosen.append(c)
        for ex in waiting:
            alternatives[ex.entry_id] = c.entry_id
        waiting = []
    return RecoveryResult(
        build_packet(chosen, max_bytes=max_bytes), tuple(exclusions), alternatives, want - len(chosen)
    )
