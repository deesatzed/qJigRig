"""Evidence obligations: what must still be established before a decision can stop.

No retrieval hit never becomes a negative fact. Satisfaction needs explicit evidence references.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .contracts import ContractError
from .recovery import RecoveryResult

KINDS = ("entity", "applicability", "predicate_evidence", "exception", "contradiction")


@dataclass(frozen=True)
class Obligation:
    obligation_id: str
    kind: str
    predicate_id: str
    description: str
    material: bool
    status: str = "open"  # open | evidence_found | unresolved | satisfied
    reason: str = ""
    evidence_entry_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ContractError(f"unknown obligation kind {self.kind!r}")
        if type(self.material) is not bool:
            raise ContractError("material must be a bool")


def _unresolved_reason(result: RecoveryResult) -> str:
    reasons = {e.reason for e in result.exclusions}
    if result.packet.truncated_entry_ids:
        return "truncated"
    if result.packet.omitted:
        return "budget_omission"
    if "source_missing" in reasons or "source_changed" in reasons or "span_mismatch" in reasons:
        return "source_unavailable"
    if "applicability_unknown" in reasons:
        return "applicability_unknown"
    if reasons == {"inapplicable"}:
        return "only_inapplicable_candidates"
    return "no_suitable_candidate"


class ObligationLedger:
    def __init__(self) -> None:
        self._items: dict[str, Obligation] = {}

    def open(self, ob: Obligation) -> None:
        if ob.obligation_id in self._items:
            raise ContractError(f"obligation {ob.obligation_id} already exists")
        self._items[ob.obligation_id] = ob

    def get(self, obligation_id: str) -> Obligation:
        return self._items[obligation_id]

    def record_retrieval(self, obligation_id: str, *, hit_count: int, result: RecoveryResult) -> None:
        ob = self._items[obligation_id]
        if ob.status == "satisfied":
            return
        if hit_count == 0:
            new = replace(ob, status="unresolved", reason="no_retrieval_hit")
        elif result.packet.items and not result.packet.truncated_entry_ids and not result.packet.omitted:
            new = replace(ob, status="evidence_found", reason="", evidence_entry_ids=tuple(i.entry_id for i in result.packet.items))
        else:
            new = replace(ob, status="unresolved", reason=_unresolved_reason(result))
        self._items[obligation_id] = new

    def satisfy(self, obligation_id: str, *, evidence_entry_ids: tuple[str, ...]) -> None:
        if not evidence_entry_ids:
            raise ContractError("an obligation can only be satisfied with evidence references")
        ob = self._items[obligation_id]
        self._items[obligation_id] = replace(ob, status="satisfied", reason="", evidence_entry_ids=tuple(evidence_entry_ids))

    def absence_established(self, obligation_id: str) -> bool:
        """Retrieval cannot establish that an exception does not exist, so this is always False."""
        self._items[obligation_id]
        return False

    def blocking(self) -> list[str]:
        return sorted(i for i, o in self._items.items() if o.material and o.status != "satisfied")
