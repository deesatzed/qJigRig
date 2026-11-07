import pytest

from qjig.contracts import ContractError
from qjig.indexing import index_entries
from qjig.packets import SIZE_UNIT, build_packet, serialize_packet
from qjig.retrieval import bm25_candidates
from qjig.sources import SourceRevision, decode_source
from qjig.spans import verify_span


def rev(text, source_id):
    return SourceRevision.create(source_id, "/x", decode_source(text.encode("utf-8"), encoding="utf-8"))


def setup():
    revs = {
        "a": rev("# Alpha\n" + "refund rule alpha. " * 6 + "\n", "p/a.md"),
        "b": rev("# Beta\n" + "refund rule beta. " * 20 + "\n", "p/b.md"),
        "c": rev("# Gamma\nrefund gamma short.\n", "p/c.md"),
    }
    entries = [e for r in revs.values() for e in index_entries(r)]
    return revs, bm25_candidates(entries, "refund rule")


def test_serialized_budget():
    revs, cands = setup()
    assert len(cands) == 3
    full = build_packet(cands, max_bytes=100_000)
    assert full.omitted == () and full.truncated_entry_ids == () and len(full.items) == 3
    assert full.size == len(serialize_packet(full)) and full.size_unit == SIZE_UNIT
    # a limit below the full size forces drops or truncation, and the whole packet stays within it
    for limit in range(full.size - 1, 700, -37):
        try:
            p = build_packet(cands, max_bytes=limit)
        except ContractError:
            continue
        assert len(serialize_packet(p)) <= limit, limit
        assert p.size == len(serialize_packet(p))
        # every candidate is either included or omitted with a reason; none vanish
        accounted = [i.entry_id for i in p.items] + [o.entry_id for o in p.omitted]
        assert sorted(accounted) == sorted(c.entry_id for c in cands)
        assert all(o.reason for o in p.omitted)
        # truncated items are marked, and are still exact prefixes of the source span
        for item in p.items:
            if item.truncated:
                assert item.entry_id in p.truncated_entry_ids and item.original_end > item.span.end
                r = next(r for r in revs.values() if r.revision_id == item.span.revision_id)
                verify_span(r, item.span)
            else:
                assert item.entry_id not in p.truncated_entry_ids
    # at least one limit in the sweep exercised each outcome
    kinds = set()
    for limit in range(full.size - 1, 700, -37):
        try:
            p = build_packet(cands, max_bytes=limit)
        except ContractError:
            continue
        kinds |= {"omit"} if p.omitted else set()
        kinds |= {"trunc"} if p.truncated_entry_ids else set()
    assert kinds == {"omit", "trunc"}


def test_budget_too_small_for_even_the_omission_records_is_an_error():
    _, cands = setup()
    with pytest.raises(ContractError):
        build_packet(cands, max_bytes=10)
    for bad in (0, -5, True, 1.5):
        with pytest.raises(ContractError):
            build_packet(cands, max_bytes=bad)


def test_empty_candidate_list_gives_empty_packet():
    p = build_packet([], max_bytes=500)
    assert p.items == () and p.omitted == () and p.size <= 500
