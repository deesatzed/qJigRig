"""Canonical qJig records. Pure data and validation; no I/O."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

REQUEST_SCHEMA = "qjig.request.v1"


class ContractError(ValueError):
    """A record violates its contract."""


def _count(name: str, value: Any) -> int:
    # bool is a subclass of int; True must not be read as a limit of 1.
    if type(value) is not int:
        raise ContractError(f"{name} must be an integer, got {type(value).__name__}")
    if value < 0:
        raise ContractError(f"{name} must not be negative")
    return value


def _amount(name: str, value: Any) -> int | float:
    if type(value) not in (int, float):
        raise ContractError(f"{name} must be a number, got {type(value).__name__}")
    if not math.isfinite(value) or value < 0:
        raise ContractError(f"{name} must be finite and not negative")
    return value


@dataclass(frozen=True)
class Budget:
    """Explicit spend limits. Zero means no external work of that kind."""

    max_calls: int
    max_tokens: int
    max_cost_usd: int | float

    def __post_init__(self) -> None:
        _count("max_calls", self.max_calls)
        _count("max_tokens", self.max_tokens)
        _amount("max_cost_usd", self.max_cost_usd)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_calls": self.max_calls,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Budget":
        if not isinstance(data, Mapping):
            raise ContractError("budget must be an object")
        expected = {"max_calls", "max_tokens", "max_cost_usd"}
        if set(data) != expected:
            raise ContractError(f"budget fields mismatch: {sorted(set(data) ^ expected)}")
        return cls(**dict(data))


@dataclass(frozen=True)
class Request:
    request_id: str
    question: str
    role: str
    role_version: str
    scope: str
    budget: Budget | None = None

    _FIELDS = ("request_id", "question", "role", "role_version", "scope")

    def __post_init__(self) -> None:
        for name in self._FIELDS:
            if not isinstance(getattr(self, name), str):
                raise ContractError(f"{name} must be a string")
        if self.budget is not None and not isinstance(self.budget, Budget):
            raise ContractError("budget must be a Budget")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"schema_version": REQUEST_SCHEMA}
        for name in self._FIELDS:
            out[name] = getattr(self, name)
        if self.budget is not None:
            out["budget"] = self.budget.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Request":
        version = data.get("schema_version")
        if version != REQUEST_SCHEMA:
            raise ContractError(f"unsupported request schema_version: {version!r}")
        expected = {"schema_version", *cls._FIELDS}
        keys = set(data) - {"budget"}
        if keys != expected:
            raise ContractError(
                f"request fields mismatch: missing={sorted(expected - keys)} "
                f"unknown={sorted(keys - expected)}"
            )
        budget = Budget.from_dict(data["budget"]) if "budget" in data else None
        return cls(**{name: data[name] for name in cls._FIELDS}, budget=budget)
