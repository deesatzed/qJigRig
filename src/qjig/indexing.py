"""Derived, rebuildable index entries over immutable source revisions.

Entries never copy or replace source text: each points at an exact Span of a pinned revision.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .contracts import ContractError
from .sources import SourceRevision
from .spans import Span, make_span, verify_span
from .store import Catalog

HEADING_METHOD = "markdown_atx_heading_v1"
FALLBACK_METHOD = "extractive_unheaded_v1"

_HEADING = re.compile(r" {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*\r?\n?$")
_FENCE = re.compile(r" {0,3}(```|~~~)")


@dataclass(frozen=True)
class IndexEntry:
    entry_id: str
    revision_id: str
    span: Span
    kind: str  # heading | extractive_fallback | paragraph
    title: str | None
    method: str
    state: str  # proposed | accepted | rejected | stale
    parent_entry_id: str | None = None


def make_entry_id(revision_id: str, kind: str, method: str, start: int, end: int) -> str:
    return hashlib.sha256(f"{revision_id}\0{kind}\0{method}\0{start}\0{end}".encode()).hexdigest()


def _lines(text: str) -> list[tuple[int, str]]:
    """(offset, line including its '\\n') split on LF only, so CRLF offsets stay exact."""
    out, pos = [], 0
    for m in re.finditer(r"[^\n]*\n|[^\n]+", text):
        out.append((m.start(), m.group()))
        pos = m.end()
    assert pos == len(text)
    return out


def index_markdown_headings(revision: SourceRevision) -> list[IndexEntry]:
    """One entry per ATX heading; a section runs to the next heading of the same or higher level."""
    text = revision.decoded.text
    heads: list[tuple[int, int, str]] = []  # (offset, level, title)
    fence: str | None = None
    for offset, line in _lines(text):
        f = _FENCE.match(line)
        if f:
            fence = None if fence == f.group(1) else (fence or f.group(1))
            continue
        if fence:
            continue
        m = _HEADING.fullmatch(line)
        if m and m.group(2).strip():
            heads.append((offset, len(m.group(1)), m.group(2).strip()))
    entries = []
    for i, (offset, level, title) in enumerate(heads):
        end = len(text)
        for later_offset, later_level, _ in heads[i + 1 :]:
            if later_level <= level:
                end = later_offset
                break
        end = offset + len(text[offset:end].rstrip())
        span = make_span(revision, offset, end)
        entries.append(
            IndexEntry(
                make_entry_id(revision.revision_id, "heading", HEADING_METHOD, offset, end),
                revision.revision_id, span, "heading", title, HEADING_METHOD, "accepted",
            )
        )
    return entries


def save_entries(catalog: Catalog, entries: list[IndexEntry]) -> None:
    for e in entries:
        if not catalog.has_revision(e.revision_id):
            raise ContractError(f"cannot index unstored revision {e.revision_id}")
    catalog.put_index_rows(
        [
            (e.entry_id, e.revision_id, e.kind, e.title, e.method, e.state,
             e.span.start, e.span.end, e.span.text_sha256, e.parent_entry_id)
            for e in entries
        ]
    )


def _entry_from_row(catalog: Catalog, row: tuple) -> tuple[IndexEntry, SourceRevision]:
    entry_id, revision_id, kind, title, method, state, start, end, text_sha, parent = row
    revision = catalog.get_revision(revision_id)
    span = make_span(revision, start, end)
    if span.text_sha256 != text_sha:
        raise ContractError(f"index entry {entry_id} no longer matches its revision text")
    return IndexEntry(entry_id, revision_id, span, kind, title, method, state, parent), revision


def load_entries(catalog: Catalog, revision_id: str) -> list[IndexEntry]:
    return [_entry_from_row(catalog, r)[0] for r in catalog.index_rows(revision_id)]


def resolve_entry(catalog: Catalog, entry_id: str) -> tuple[IndexEntry, Span, SourceRevision]:
    """Return the entry, its span re-sliced from the stored source, and that source revision."""
    row = catalog.index_row(entry_id)
    if row is None:
        raise KeyError(entry_id)
    entry, revision = _entry_from_row(catalog, row)
    verify_span(revision, entry.span)
    return entry, entry.span, revision


def index_entries(revision: SourceRevision) -> list[IndexEntry]:
    """Heading entries plus a proposed, title-less extractive entry for any unheaded leading text."""
    text = revision.decoded.text
    headings = index_markdown_headings(revision)
    limit = headings[0].span.start if headings else len(text)
    lead = text[:limit]
    entries: list[IndexEntry] = []
    if lead.strip():
        start = len(lead) - len(lead.lstrip())
        end = len(lead.rstrip())
        span = make_span(revision, start, end)
        entries.append(
            IndexEntry(
                make_entry_id(revision.revision_id, "extractive_fallback", FALLBACK_METHOD, start, end),
                revision.revision_id, span, "extractive_fallback", None, FALLBACK_METHOD, "proposed",
            )
        )
    return entries + headings
