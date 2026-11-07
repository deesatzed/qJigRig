"""Pure decision logic over explicit true/false/unknown/conflict states."""
from __future__ import annotations

from enum import Enum

from .contracts import ContractError


class Support(Enum):
    SUPPORTED = "supported"
    UNKNOWN = "unknown"


class Outcome(Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


def combine_support(positive: Support, negative: Support) -> Outcome:
    """Combine separate support for a proposition (positive) and for its negation (negative).

    Absence of support for a side is UNKNOWN, never evidence for the other side.
    """
    if not isinstance(positive, Support) or not isinstance(negative, Support):
        raise ContractError("support must be a Support state, not a boolean or score")
    if positive is Support.SUPPORTED and negative is Support.SUPPORTED:
        return Outcome.CONFLICT
    if positive is Support.SUPPORTED:
        return Outcome.TRUE
    if negative is Support.SUPPORTED:
        return Outcome.FALSE
    return Outcome.UNKNOWN
