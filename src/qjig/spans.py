"""Exact text spans: Unicode code-point offsets, end-exclusive, bound to a revision."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import ContractError
from .sources import SourceRevision


@dataclass(frozen=True)
class Span:
    revision_id: str
    text_sha256: str
    start: int
    end: int
    text: str


def _check_offsets(start: object, end: object, length: int) -> None:
    if type(start) is not int or type(end) is not int:
        raise ContractError("span offsets must be integers")
    if not (0 <= start < end <= length):
        raise ContractError(f"span offsets out of range: [{start}, {end}) in text of {length}")


def make_span(revision: SourceRevision, start: int, end: int) -> Span:
    text = revision.decoded.text
    _check_offsets(start, end, len(text))
    return Span(revision.revision_id, revision.decoded.text_sha256, start, end, text[start:end])


def verify_span(revision: SourceRevision, span: Span) -> None:
    """Raise ContractError unless span is exactly a slice of this revision's text."""
    if span.revision_id != revision.revision_id:
        raise ContractError("span is bound to a different revision")
    if span.text_sha256 != revision.decoded.text_sha256:
        raise ContractError("span text hash does not match the revision text")
    text = revision.decoded.text
    _check_offsets(span.start, span.end, len(text))
    if text[span.start : span.end] != span.text:
        raise ContractError("span text does not match the source at these offsets")
