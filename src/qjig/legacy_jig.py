"""Translation boundary for legacy JIG snapshot offsets and quotes. Pure; no JIG import.

Legacy JIG hashes the UTF-8 encoding of its snapshot text (the decoded raw text, newlines kept)
and refers to it by code-point offsets or by a quote that occurs exactly once.
"""
from __future__ import annotations

from .contracts import ContractError
from .sources import SourceRevision
from .spans import Span, make_span


def _require_same_text(revision: SourceRevision, legacy_sha256: str) -> None:
    if revision.decoded.text_sha256 != legacy_sha256:
        raise ContractError("legacy snapshot hash does not match this revision's text")


def translate_jig_offsets(
    revision: SourceRevision, legacy_sha256: str, start: int, end: int, quote: str
) -> Span:
    _require_same_text(revision, legacy_sha256)
    span = make_span(revision, start, end)
    if span.text != quote:
        raise ContractError("legacy quote does not match the text at its offsets")
    return span


def translate_jig_quote(revision: SourceRevision, legacy_sha256: str, quote: str) -> Span:
    _require_same_text(revision, legacy_sha256)
    if not isinstance(quote, str) or not quote.strip():
        raise ContractError("citation must contain non-whitespace text")
    text = revision.decoded.text
    first = text.find(quote)
    if first < 0:
        raise ContractError("citation not found in revision text")
    if text.find(quote, first + 1) >= 0:
        raise ContractError("citation is ambiguous in revision text")
    return make_span(revision, first, first + len(quote))
