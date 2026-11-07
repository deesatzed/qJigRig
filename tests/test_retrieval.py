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


from qjig.retrieval import select_with_mandatory


def build_channels():
    entries = entries_for(
        ("a/refund.md", "# Refund window\nRefund window is thirty days. Refund window applies to all refund orders.\n"),
        ("b/refund2.md", "# Refund window\nThe refund window is thirty days for standard orders.\n"),
        ("c/waiver.md", "# Waiver\nA manager may grant an exception.\n"),
    )
    primary = bm25_candidates(entries, "refund window thirty days")
    exception = bm25_candidates(entries, "exception")
    return entries, primary, exception


def test_role_cannot_hide_exception():
    entries, primary, exception = build_channels()
    waiver = next(e for e in entries if e.span.text.startswith("# Waiver"))
    # the role scores the exception source at zero and the ordinary sources highly
    priors = {c.entry_id: 1.0 for c in primary}
    priors[waiver.entry_id] = 0.0
    sel = select_with_mandatory(
        {"primary": primary, "exception": exception},
        required_channels={"exception"}, limit=2, role_priors=priors,
    )
    chosen = [(ch, c.entry_id) for ch, c in sel.selected]
    assert ("exception", waiver.entry_id) in chosen  # a low role score cannot eliminate it
    assert len(chosen) == 2 and sel.missing_required == () and sel.omitted_required == ()
    # the same selection happens whatever the role score says
    for p in (0.0, 0.5, 1.0):
        priors[waiver.entry_id] = p
        again = select_with_mandatory({"primary": primary, "exception": exception}, {"exception"}, 2, priors)
        assert ("exception", waiver.entry_id) in [(ch, c.entry_id) for ch, c in again.selected]


def test_role_prior_only_breaks_lexical_ties():
    same = "# Refunds\nRefund allowed within thirty days of purchase.\n"
    entries = entries_for(("a/one.md", same), ("b/two.md", same))
    cands = bm25_candidates(entries, "refund")
    assert cands[0].score == cands[1].score
    favored = cands[1].entry_id  # would lose the entry_id tie-break
    sel = select_with_mandatory({"primary": cands}, set(), 2, {favored: 0.9})
    assert [c.entry_id for _, c in sel.selected][0] == favored
    # an unfavored but lexically better candidate is never demoted below a worse one
    entries2 = entries_for(("a/best.md", "# R\nrefund refund refund refund\n"), ("b/weak.md", "# R\nrefund and much other text here today\n"))
    c2 = bm25_candidates(entries2, "refund")
    sel2 = select_with_mandatory({"primary": c2}, set(), 2, {c2[1].entry_id: 1.0, c2[0].entry_id: 0.0})
    assert [c.entry_id for _, c in sel2.selected] == [c.entry_id for c in c2]


def test_missing_and_omitted_required_channels_are_reported():
    entries, primary, exception = build_channels()
    sel = select_with_mandatory({"primary": primary, "exception": []}, {"exception"}, 3, {})
    assert sel.missing_required == ("exception",)  # no hit is reported, not treated as "no exception exists"
    assert len(sel.selected) == len(primary) == 2  # only what exists is returned
    sel2 = select_with_mandatory({"a": primary, "b": exception}, {"a", "b"}, 1, {})
    assert [ch for ch, _ in sel2.selected] == ["a"] and sel2.omitted_required == ("b",)


def test_recorded_live_query_variants():
    """Historical live questions over the same authored synthetic corpus; no model call."""
    import json
    from pathlib import Path
    from qjig.retrieval import bm25_expanded_candidates, EXPANDED_BM25_METHOD

    report = json.loads((Path(__file__).resolve().parents[1] / "reports/t048-fresh-live.json").read_text())
    recorded = []
    for run in report["runs"]:
        predicates = dict(run["predicates"])
        recorded.extend(predicates[pid] for pid, observation in run["observations"].items()
                        if observation == ["unknown", "no_retrieval_hit"])
    assert len(recorded) == 3
    corpus = entries_for(("sample/refunds.md", "# Refunds\nRefunds are accepted within 14 days of purchase.\n\n# Exceptions\nDefective items may be refunded within 30 days.\n"))
    for query in recorded:
        assert bm25_candidates(corpus, query) == []
        expanded = bm25_expanded_candidates(corpus, query)
        assert expanded and all(c.provenance.method == EXPANDED_BM25_METHOD for c in expanded)
        assert any("Refunds are accepted" in c.span.text or "Defective items may be refunded" in c.span.text for c in expanded)
    # Expansion may retrieve a lexical distractor; its presence is not treated as support.
    distractor = entries_for(("other.md", "# Exceptions\nExceptionless control flow.\n"))
    assert bm25_candidates(distractor, recorded[-1]) == []
    assert bm25_expanded_candidates(distractor, recorded[-1])


def test_expansion_is_bounded_deterministic_and_does_not_infer_absence():
    from qjig.retrieval import bm25_expanded_candidates, expand_query_v1

    assert expand_query_v1("refund exception") == "refund exception exceptions refunded refunds"
    assert expand_query_v1("nonrefundable exceptional") == "nonrefundable exceptional"
    entries = entries_for(("policy.md", "# Policy\nRefunds are allowed.\n"), ("other.md", "# Other\nNo relevant text.\n"))
    query = "refund"
    assert bm25_candidates(entries, query) == []
    result = bm25_expanded_candidates(entries, query)
    assert result == bm25_expanded_candidates(list(reversed(entries)), query)
    assert result[0].span.text.startswith("# Policy")
    assert bm25_expanded_candidates(entries, "unmentioned") == []
