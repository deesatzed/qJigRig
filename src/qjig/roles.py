"""Role definitions and role-usefulness estimates. Estimates are proposals, never authority."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .contracts import ContractError


@dataclass(frozen=True)
class RoleDefinition:
    role_id: str
    version: str
    purpose: str

    def __post_init__(self) -> None:
        for name in ("role_id", "version", "purpose"):
            v = getattr(self, name)
            if not isinstance(v, str) or not v.strip():
                raise ContractError(f"{name} must be a non-empty string")


@dataclass(frozen=True)
class RoleEstimate:
    role_id: str
    role_version: str
    entry_id: str
    revision_id: str
    estimated_usefulness: float  # uncalibrated, in [0, 1]
    method: str
    receipt: str
    state: str = "proposed"

    def __post_init__(self) -> None:
        s = self.estimated_usefulness
        if type(s) not in (int, float) or not math.isfinite(s) or not 0 <= s <= 1:
            raise ContractError("estimated_usefulness must be a finite number in [0, 1]")


class RoleEstimateStore:
    """In-memory (not persisted). Keyed by role, role version, entry and revision."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str, str], RoleEstimate] = {}

    def put(self, e: RoleEstimate) -> None:
        key = (e.role_id, e.role_version, e.entry_id, e.revision_id)
        if key in self._items:
            raise ContractError("an estimate for this role version, entry and revision already exists")
        self._items[key] = e

    def current_prior(self, role_id: str, role_version: str, entry_id: str, revision_id: str) -> RoleEstimate | None:
        return self._items.get((role_id, role_version, entry_id, revision_id))

    def all_for(self, entry_id: str) -> list[RoleEstimate]:
        return sorted(
            (e for e in self._items.values() if e.entry_id == entry_id),
            key=lambda e: (e.role_id, e.role_version, e.revision_id),
        )
