from qjig.indexing import index_entries
from qjig.retrieval import BM25_METHOD, bm25_candidates, tokenize
from qjig.sources import SourceRevision, decode_source


def rev(text, source_id):
    return SourceRevision.create(source_id, "/x", decode_source(text.encode("utf-8"), encoding="utf-8"))


def entries_for(*docs):
    out = []
    for source_id, text in docs:
        out += index_entries(rev(text, source_id))
    return out


def test_deterministic_bm25():
    same = "# Refunds\nRefund allowed within thirty days of purchase.\n"
    entries = entries_for(
        ("b/second.md", same),
        ("a/first.md", same),
        ("c/other.md", "# Shipping\nParcels ship in two days.\n"),
        ("d/long.md", "# Refunds\n" + "refund " + "filler " * 40 + "\n"),
    )
    runs = [bm25_candidates(entries, "refund thirty days") for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    ranked = runs[0]
    assert "c/other" not in [c.entry_id for c in ranked]  # no query term, not returned
    identical = [c for c in ranked if c.score == ranked[0].score]
    assert len(identical) == 2  # the two identical documents tie exactly
    assert [c.entry_id for c in identical] == sorted(c.entry_id for c in identical)  # stable ID order
    assert ranked[0].score > ranked[-1].score
    # input order does not matter
    assert bm25_candidates(list(reversed(entries)), "refund thirty days") == ranked


def test_score_provenance_is_recorded():
    entries = entries_for(("a/first.md", "# Refunds\nrefund refund window\n"), ("b/x.md", "# Other\nnothing here\n"))
    (top,) = bm25_candidates(entries, "Refund WINDOW missing")
    p = top.provenance
    assert p.method == BM25_METHOD and p.k1 == 1.2 and p.b == 0.75
    assert p.corpus_size == 2
    assert {t.term for t in p.terms} == {"refund", "window"}  # only matched terms, lowercased
    refund = next(t for t in p.terms if t.term == "refund")
    assert refund.term_frequency == 2 and refund.document_frequency == 1  # no stemming: "Refunds" is another term
    assert top.revision_id == entries[0].revision_id and top.span == entries[0].span


def test_tokenizer_and_empty_cases():
    assert tokenize("Café ÜBER, e-mail 3.5x") == ["café", "über", "e", "mail", "3", "5x"]
    entries = entries_for(("a/first.md", "# T\nbody\n"))
    assert bm25_candidates(entries, "") == []
    assert bm25_candidates(entries, "!!!") == []
    assert bm25_candidates([], "body") == []
