import pytest

from qjig.contracts import ContractError
from qjig.indexing import index_markdown_headings, load_entries, resolve_entry, save_entries
from qjig.sources import SourceRevision, decode_source
from qjig.spans import verify_span
from qjig.store import Catalog


def rev(text, source_id="p/policy.md"):
    return SourceRevision.create(source_id, "/x", decode_source(text.encode("utf-8"), encoding="utf-8"))


DOC = "# Policy\r\nintro\r\n\r\n## Refunds\r\nRefund within 30 days.\r\n\r\n## Shipping\r\nShips in 2 days.\r\n"


def test_heading_span(tmp_path):
    revision = rev(DOC)
    entries = index_markdown_headings(revision)
    assert [e.title for e in entries] == ["Policy", "Refunds", "Shipping"]
    refunds = entries[1]
    assert refunds.span.text == "## Refunds\r\nRefund within 30 days."  # exact slice, CRLF kept, no trailing blank
    assert refunds.kind == "heading" and refunds.revision_id == revision.revision_id
    assert entries[0].span.text.startswith("# Policy") and entries[0].span.text.endswith("Ships in 2 days.")
    # store, reopen, and resolve back to exact pinned text
    db = tmp_path / "c.sqlite"
    with Catalog.open(db) as cat:
        cat.add_revision(revision)
        save_entries(cat, entries)
    with Catalog.open(db) as cat:
        loaded = load_entries(cat, revision.revision_id)
        assert loaded == entries
        entry, span, source = resolve_entry(cat, refunds.entry_id)
        assert entry == refunds and span.text == refunds.span.text
        verify_span(source, span)


def test_headings_inside_code_fences_and_non_headings_are_ignored():
    text = "# Real\n```\n# not a heading\n```\n#hashtag\n    # indented code\n"
    entries = index_markdown_headings(rev(text))
    assert [e.title for e in entries] == ["Real"]
    assert index_markdown_headings(rev("plain text only\n")) == []


def test_entry_ids_are_deterministic_and_separate_from_text(tmp_path):
    a, b = index_markdown_headings(rev(DOC)), index_markdown_headings(rev(DOC))
    assert [e.entry_id for e in a] == [e.entry_id for e in b]
    assert len({e.entry_id for e in a}) == 3


def test_saving_entries_for_unstored_revision_is_refused(tmp_path):
    with Catalog.open(tmp_path / "c.sqlite") as cat:
        with pytest.raises(ContractError):
            save_entries(cat, index_markdown_headings(rev(DOC)))
