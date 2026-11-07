from dataclasses import replace

from qjig.indexing import index_entries
from qjig.recovery import recover_packet
from qjig.retrieval import bm25_candidates
from qjig.sources import SourceRevision, decode_source
from qjig.spans import verify_span
from qjig.store import Catalog


def rev(text, source_id):
    return SourceRevision.create(source_id, "/x", decode_source(text.encode("utf-8"), encoding="utf-8"))


BEST = rev("# Refund policy\nrefund refund refund policy for orders\n", "p/best.md")
ALT = rev("# Refund notes\nrefund policy summary for orders\n", "p/alt.md")
WEAK = rev("# Misc\nrefund\n", "p/weak.md")


def candidates():
    entries = [e for r in (BEST, ALT, WEAK) for e in index_entries(r)]
    cands = bm25_candidates(entries, "refund policy")
    assert cands[0].revision_id == BEST.revision_id  # BEST is the top-ranked candidate
    return cands


def test_missing_source_alternative(tmp_path):
    with Catalog.open(tmp_path / "c.sqlite") as cat:
        cat.add_revision(ALT)
        cat.add_revision(WEAK)  # BEST was never stored / is gone
        cands = candidates()
        result = recover_packet(cat, cands, want=1, max_bytes=5000)
    (ex,) = result.exclusions
    assert ex.entry_id == cands[0].entry_id and ex.reason == "source_missing"
    (item,) = result.packet.items
    assert item.span.revision_id == ALT.revision_id
    verify_span(ALT, item.span)  # the alternative is an exact, verified span
    assert result.alternatives == {ex.entry_id: item.entry_id}


def test_no_exclusion_when_top_candidate_is_available(tmp_path):
    with Catalog.open(tmp_path / "c.sqlite") as cat:
        for r in (BEST, ALT, WEAK):
            cat.add_revision(r)
        result = recover_packet(cat, candidates(), want=2, max_bytes=5000)
    assert result.exclusions == () and result.alternatives == {}
    assert [i.span.revision_id for i in result.packet.items] == [BEST.revision_id, ALT.revision_id]


def test_forged_span_is_excluded_not_trusted(tmp_path):
    with Catalog.open(tmp_path / "c.sqlite") as cat:
        for r in (BEST, ALT, WEAK):
            cat.add_revision(r)
        cands = candidates()
        forged = replace(cands[0], span=replace(cands[0].span, text="refund is free forever"))
        result = recover_packet(cat, [forged] + cands[1:], want=1, max_bytes=5000)
    assert [e.reason for e in result.exclusions] == ["span_mismatch"]
    assert result.packet.items[0].span.revision_id == ALT.revision_id


def test_all_unavailable_gives_empty_packet_and_no_alternative(tmp_path):
    with Catalog.open(tmp_path / "c.sqlite") as cat:  # nothing stored
        result = recover_packet(cat, candidates(), want=1, max_bytes=5000)
    assert result.packet.items == ()
    assert len(result.exclusions) == 3 and result.alternatives == {}
