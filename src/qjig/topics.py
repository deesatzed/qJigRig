"""Topic views over index entries. Links reference spans by identity and never copy text."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import ContractError
from .indexing import IndexEntry
from .spans import Span

TOPIC_METHOD = "manual_attach_v1"


@dataclass(frozen=True)
class SpanRef:
    revision_id: str
    start: int
    end: int
    text_sha256: str


def span_ref(span: Span) -> SpanRef:
    return SpanRef(span.revision_id, span.start, span.end, span.text_sha256)


@dataclass(frozen=True)
class TopicLink:
    topic: str
    entry_id: str
    span_ref: SpanRef
    method: str
    state: str  # proposed until a reviewer accepts


class TopicIndex:
    """In-memory topic map (not yet persisted)."""

    def __init__(self) -> None:
        self._links: dict[tuple[str, str], TopicLink] = {}

    def attach(self, topic: str, entry: IndexEntry) -> TopicLink:
        if not isinstance(topic, str) or not topic.strip():
            raise ContractError("topic must be a non-empty string")
        key = (topic, entry.entry_id)
        if key not in self._links:
            self._links[key] = TopicLink(topic, entry.entry_id, span_ref(entry.span), TOPIC_METHOD, "proposed")
        return self._links[key]

    def links(self) -> list[TopicLink]:
        return sorted(self._links.values(), key=lambda l: (l.topic, l.entry_id))

    def topics_for(self, entry_id: str) -> list[str]:
        return sorted(t for (t, e) in self._links if e == entry_id)

    def entry_ids_for(self, topic: str) -> list[str]:
        return sorted(e for (t, e) in self._links if t == topic)
