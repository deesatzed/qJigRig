"""Evidence packets with a hard size budget over the complete serialized form. Pure.

Size is the UTF-8 byte length of canonical JSON (SIZE_UNIT); no model tokenizer is implied.
Transport framing around the packet is outside this budget.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace

from .contracts import ContractError
from .retrieval import Candidate
from .spans import Span

SIZE_UNIT = "utf8_json_bytes"
PACKET_SCHEMA = "qjig.packet.v1"
MIN_PREFIX_CHARS = 40

REASON_EXCEEDS_BUDGET = "exceeds_budget"


@dataclass(frozen=True)
class PacketItem:
    entry_id: str
    span: Span
    truncated: bool = False
    original_end: int | None = None


@dataclass(frozen=True)
class Omission:
    entry_id: str
    reason: str


@dataclass(frozen=True)
class EvidencePacket:
    items: tuple[PacketItem, ...]
    omitted: tuple[Omission, ...]
    truncated_entry_ids: tuple[str, ...]
    limit: int
    size: int
    size_unit: str = SIZE_UNIT


def _body(items, omitted, limit) -> dict:
    return {
        "schema": PACKET_SCHEMA,
        "size_unit": SIZE_UNIT,
        "limit": limit,
        "items": [
            {
                "entry_id": i.entry_id, "revision_id": i.span.revision_id,
                "text_sha256": i.span.text_sha256, "start": i.span.start, "end": i.span.end,
                "text": i.span.text, "truncated": i.truncated, "original_end": i.original_end,
            }
            for i in items
        ],
        "omitted": [{"entry_id": o.entry_id, "reason": o.reason} for o in omitted],
    }


def _size(items, omitted, limit) -> int:
    return len(json.dumps(_body(items, omitted, limit), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def serialize_packet(packet: EvidencePacket) -> bytes:
    return json.dumps(
        _body(packet.items, packet.omitted, packet.limit), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def build_packet(candidates: list[Candidate], *, max_bytes: int) -> EvidencePacket:
    """Include candidates in the given order while the complete packet stays within max_bytes.

    Invariant at every step: even if every undecided candidate were omitted, the packet fits.
    The first candidate that does not fit whole may be cut to an exact prefix and is marked
    truncated; others that do not fit are omitted with a reason. Nothing disappears silently.
    """
    if type(max_bytes) is not int or max_bytes < 1:
        raise ContractError("max_bytes must be a positive integer")
    items: list[PacketItem] = []
    omitted: list[Omission] = []
    pending = [Omission(c.entry_id, REASON_EXCEEDS_BUDGET) for c in candidates]
    if _size(items, pending, max_bytes) > max_bytes:
        raise ContractError("max_bytes is too small for the packet's own omission records")
    truncated_used = False
    for idx, c in enumerate(candidates):
        rest = pending[idx + 1 :]
        whole = PacketItem(c.entry_id, c.span)
        if _size(items + [whole], omitted + rest, max_bytes) <= max_bytes:
            items.append(whole)
            continue
        if not truncated_used and len(c.span.text) > MIN_PREFIX_CHARS:
            lo, hi, best = MIN_PREFIX_CHARS, len(c.span.text) - 1, 0
            while lo <= hi:
                mid = (lo + hi) // 2
                cut = replace(c.span, end=c.span.start + mid, text=c.span.text[:mid])
                trial = PacketItem(c.entry_id, cut, True, c.span.end)
                if _size(items + [trial], omitted + rest, max_bytes) <= max_bytes:
                    best, lo = mid, mid + 1
                else:
                    hi = mid - 1
            if best:
                cut = replace(c.span, end=c.span.start + best, text=c.span.text[:best])
                items.append(PacketItem(c.entry_id, cut, True, c.span.end))
                truncated_used = True
                continue
        omitted.append(pending[idx])
    return EvidencePacket(
        tuple(items), tuple(omitted), tuple(i.entry_id for i in items if i.truncated),
        max_bytes, _size(items, omitted, max_bytes),
    )
