"""Canonical qJig records. Pure data and validation; no I/O."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

REQUEST_SCHEMA = "qjig.request.v1"


class ContractError(ValueError):
    """A record violates its contract."""


@dataclass(frozen=True)
class Request:
    request_id: str
    question: str
    role: str
    role_version: str
    scope: str

    _FIELDS = ("request_id", "question", "role", "role_version", "scope")

    def __post_init__(self) -> None:
        for name in self._FIELDS:
            if not isinstance(getattr(self, name), str):
                raise ContractError(f"{name} must be a string")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"schema_version": REQUEST_SCHEMA}
        for name in self._FIELDS:
            out[name] = getattr(self, name)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Request":
        version = data.get("schema_version")
        if version != REQUEST_SCHEMA:
            raise ContractError(f"unsupported request schema_version: {version!r}")
        expected = {"schema_version", *cls._FIELDS}
        keys = set(data)
        if keys != expected:
            raise ContractError(
                f"request fields mismatch: missing={sorted(expected - keys)} "
                f"unknown={sorted(keys - expected)}"
            )
        return cls(**{name: data[name] for name in cls._FIELDS})
