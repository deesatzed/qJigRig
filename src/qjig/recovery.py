"""Verify retrieved candidates against stored sources; exclude unavailable ones; use alternatives."""
from __future__ import annotations

from dataclasses import dataclass

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


def recover_packet(catalog: Catalog, candidates: list[Candidate], *, want: int, max_bytes: int) -> RecoveryResult:
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
        if problem:
            exclusions.append(problem)
            waiting.append(problem)
            continue
        chosen.append(c)
        for ex in waiting:
            alternatives[ex.entry_id] = c.entry_id
        waiting = []
    return RecoveryResult(build_packet(chosen, max_bytes=max_bytes), tuple(exclusions), alternatives)
