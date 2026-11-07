import pytest

from qjig.contracts import ContractError
from qjig.indexing import current_entries, invalidate_superseded, index_entries, split_broad_section, index_markdown_headings, load_entries, resolve_entry, save_entries
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


def test_missing_heading_fallback():
    revision = rev("Refunds are allowed within 30 days.\r\nExceptions apply.\r\n")
    assert index_markdown_headings(revision) == []
    entries = index_entries(revision)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "extractive_fallback" and e.state == "proposed"
    assert e.title is None  # no heading is invented
    assert e.span.text == "Refunds are allowed within 30 days.\r\nExceptions apply."
    assert e.method != "markdown_atx_heading_v1"


def test_text_before_first_heading_is_covered_and_headed_docs_are_unchanged():
    revision = rev("Intro note.\n\n# Title\nBody\n")
    entries = index_entries(revision)
    assert [(e.kind, e.title, e.span.text) for e in entries] == [
        ("extractive_fallback", None, "Intro note."),
        ("heading", "Title", "# Title\nBody"),
    ]
    plain = rev(DOC)
    assert index_entries(plain) == index_markdown_headings(plain)  # no fallback when nothing is unheaded


def test_blank_document_has_no_entries():
    assert index_entries(rev("  \r\n\n")) == []


BROAD = "# Rules\r\nFirst paragraph.\r\n\r\nSecond paragraph\r\nspans two lines.\r\n\r\nThird one.\r\n"


def test_broad_heading_paragraphs():
    revision = rev(BROAD)
    (section,) = index_markdown_headings(revision)
    children = split_broad_section(revision, section, max_chars=20)
    assert [c.span.text for c in children] == [
        "# Rules\r\nFirst paragraph.",
        "Second paragraph\r\nspans two lines.",
        "Third one.",
    ]
    for c in children:
        assert c.kind == "paragraph" and c.state == "proposed"
        assert c.parent_entry_id == section.entry_id
        assert c.revision_id == revision.revision_id
        assert section.span.start <= c.span.start and c.span.end <= section.span.end
        verify_span(revision, c.span)  # exact source slice
        assert c.entry_id != section.entry_id
    assert [c.span.start for c in children] == sorted(c.span.start for c in children)
    assert all(a.span.end <= b.span.start for a, b in zip(children, children[1:]))  # no overlap


def test_narrow_or_single_paragraph_sections_are_not_split():
    revision = rev(BROAD)
    (section,) = index_markdown_headings(revision)
    assert split_broad_section(revision, section, max_chars=10_000) == []
    single = rev("# One\nonly paragraph here\n")
    (s1,) = index_markdown_headings(single)
    assert split_broad_section(single, s1, max_chars=5) == []
    with pytest.raises(ContractError):
        split_broad_section(revision, section, max_chars=0)
    with pytest.raises(ContractError):
        split_broad_section(revision, section, max_chars=True)


def test_revision_stales_indexes(tmp_path):
    v1 = rev("# Limit\nten items\n")
    v2 = rev("# Limit\ntwenty items\n")
    other = rev("# Other\nunrelated\n", source_id="p/other.md")
    with Catalog.open(tmp_path / "c.sqlite") as cat:
        for r in (v1, v2, other):
            cat.add_revision(r)
        save_entries(cat, index_entries(v1))
        save_entries(cat, index_entries(other))
        old = load_entries(cat, v1.revision_id)
        assert [e.state for e in old] == ["accepted"]
        # origin gets a new revision: v1 entries go stale, v2 has none until it is indexed
        changed = invalidate_superseded(cat, "p/policy.md", current_revision_id=v2.revision_id)
        assert changed == 1
        assert current_entries(cat, "p/policy.md", v2.revision_id) == []
        # old entries remain inspectable, marked stale, and still resolve to the old pinned text
        stale = load_entries(cat, v1.revision_id)
        assert [e.state for e in stale] == ["stale"]
        entry, span, _ = resolve_entry(cat, stale[0].entry_id)
        assert span.text == "# Limit\nten items"
        # asking for current entries under the OLD revision as if current finds none
        assert current_entries(cat, "p/policy.md", v1.revision_id) == []
        # indexing the new revision makes only its entries current
        save_entries(cat, index_entries(v2))
        cur = current_entries(cat, "p/policy.md", v2.revision_id)
        assert [e.span.text for e in cur] == ["# Limit\ntwenty items"]
        # unrelated sources untouched; repeating is a no-op
        assert [e.state for e in load_entries(cat, other.revision_id)] == ["accepted"]
        assert invalidate_superseded(cat, "p/policy.md", current_revision_id=v2.revision_id) == 0


def test_invalidate_requires_stored_current_revision(tmp_path):
    v1 = rev("# A\nx\n")
    with Catalog.open(tmp_path / "c.sqlite") as cat:
        cat.add_revision(v1)
        with pytest.raises(ContractError):
            invalidate_superseded(cat, "p/policy.md", current_revision_id="rev1:" + "0" * 64)
        other = rev("# A\nx\n", source_id="p/other.md")
        cat.add_revision(other)
        with pytest.raises(ContractError):  # revision belongs to a different source
            invalidate_superseded(cat, "p/policy.md", current_revision_id=other.revision_id)
