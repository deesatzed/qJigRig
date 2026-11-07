"""STAND-IN transport only (D018): authored judge answers. Tests the mapping of answers to states,
not the quality of any real judge."""
import itertools
import json

import pytest

from qjig.budgets import BudgetLedger
from qjig.contracts import Budget
from qjig.indexing import index_entries
from qjig.journal import Journal
from qjig.judge import judge_predicate
from qjig.logic import Outcome
from qjig.packets import build_packet
from qjig.providers import RawResponse, StandInTransport
from qjig.retrieval import bm25_candidates
from qjig.sources import SourceRevision, decode_source

USAGE = {"prompt_tokens": 20, "completion_tokens": 5, "cost_usd": None}
QUESTION = "Is the purchase inside the 14 day refund window?"


def packet():
    r = SourceRevision.create("p/a.md", "/x", decode_source(b"# Refunds\nRefunds are accepted within 14 days of purchase.\n", encoding="utf-8"))
    return build_packet(bm25_candidates(index_entries(r), "refund days"), max_bytes=3000)


def side(supported, quote="", reason="r"):
    return RawResponse(200, json.dumps({"supported": supported, "quote": quote, "reason": reason}), USAGE)


_n = itertools.count()


def run(tmp_path, pos, neg, calls=4):
    j = Journal.open(tmp_path / f"j{next(_n)}.sqlite")  # a fresh journal per run: caps do not leak between cases
    ledger = BudgetLedger(Budget(calls, 9000, 1.0), j, "req-1")
    t = StandInTransport([pos, neg])
    with j:
        result = judge_predicate(ledger, t, QUESTION, packet(), provider="stand-in", model="stand-in-model")
        return result, ledger.used_calls(), t


Q = "Refunds are accepted within 14 days of purchase."


def test_false_support_unknown(tmp_path):
    # "the positive claim is NOT supported" is not evidence for the negative claim
    r, used, t = run(tmp_path, side(False), side(False))
    assert r.outcome is Outcome.UNKNOWN and r.observation.reason == "judge_no_support"
    r, _, _ = run(tmp_path, side(False), side(False, reason="could not tell"))
    assert r.outcome is Outcome.UNKNOWN and r.positive.support.value == "unknown" and r.negative.support.value == "unknown"


def test_paired_support_maps_to_all_four_states(tmp_path):
    cases = [
        (side(True, Q), side(False), Outcome.TRUE, "judge_positive_supported"),
        (side(False), side(True, Q), Outcome.FALSE, "judge_negative_supported"),
        (side(False), side(False), Outcome.UNKNOWN, "judge_no_support"),
        (side(True, Q), side(True, Q), Outcome.CONFLICT, "judge_both_supported"),
    ]
    for pos, neg, outcome, reason in cases:
        r, used, t = run(tmp_path, pos, neg)
        assert (r.outcome, r.observation.outcome, r.observation.reason) == (outcome, outcome, reason)
        assert t.calls_made == 2 and used == 2  # one physical call per side, both counted


def test_supported_without_quote_and_provider_failures_stay_unknown_with_a_reason(tmp_path):
    r, _, _ = run(tmp_path, side(True, ""), side(False))
    assert r.outcome is Outcome.UNKNOWN and r.positive.reason == "supported_without_quote"
    # a failed side is unknown and its failure is the reported reason; the other side cannot decide alone
    r, _, _ = run(tmp_path, RawResponse(200, "not json", USAGE), side(True, Q))
    assert r.outcome is Outcome.FALSE  # the negative side is supported and the positive side only FAILED (unknown)
    assert r.positive.failure == "malformed_output"
    assert r.caveats == ("positive_side_failed:malformed_output", "applicability_not_assessed")  # the possible hidden conflict is stated
    r, _, _ = run(tmp_path, RawResponse(500, "oops", None), RawResponse(200, "[]", USAGE))
    assert r.outcome is Outcome.UNKNOWN and r.observation.reason == "provider_http_error"
    assert (r.positive.failure, r.negative.failure) == ("http_error", "schema_violation")


def test_budget_exhaustion_midway_leaves_the_other_side_unknown(tmp_path):
    j = Journal.open(tmp_path / "j.sqlite")
    ledger = BudgetLedger(Budget(1, 9000, 1.0), j, "req-1")
    t = StandInTransport([side(True, Q), side(False)])
    with j:
        r = judge_predicate(ledger, t, QUESTION, packet(), provider="stand-in", model="stand-in-model")
        assert t.calls_made == 1
        assert r.positive.support.value == "supported" and r.negative.failure == "budget_exceeded"
        assert r.outcome is Outcome.TRUE  # the mapping is unchanged, but the unasked side is carried as a caveat
        assert r.observation.reason == "judge_positive_supported"
        assert r.caveats == ("negative_side_failed:budget_exceeded", "applicability_not_assessed")


from qjig.applicability import Applicability
from qjig.spans import make_span, verify_span

QUOTE_42 = "Refunds are accepted within 14 days of purchase."
QUOTE_7 = "Refunds are accepted within 30 days of purchase."


def two_source_packet():
    a = SourceRevision.create("p/c42.md", "/x", decode_source(f"# Customer 42\n{QUOTE_42}\n".encode(), encoding="utf-8"))
    b = SourceRevision.create("p/c7.md", "/x", decode_source(f"# Customer 7\n{QUOTE_7}\n".encode(), encoding="utf-8"))
    entries = index_entries(a) + index_entries(b)
    return a, b, build_packet(bm25_candidates(entries, "refund days purchase"), max_bytes=4000)


def run_assured(tmp_path, pos, neg, applicability="default"):
    a, b, pk = two_source_packet()
    check = (lambda rid: Applicability.MATCH if rid == a.revision_id else Applicability.NO_MATCH) if applicability == "default" else applicability
    j = Journal.open(tmp_path / f"a{next(_n)}.sqlite")
    ledger = BudgetLedger(Budget(4, 9000, 1.0), j, "req-1")
    with j:
        return judge_predicate(ledger, StandInTransport([pos, neg]), QUESTION, pk, provider="stand-in", model="stand-in-model", applicability=check), a, b


def test_quote_not_semantic_proof(tmp_path):
    # an exact quote from the WRONG customer's source: the text is genuine, but it is not support for this request
    r, a, b = run_assured(tmp_path, side(True, QUOTE_7), side(False))
    assert r.outcome is Outcome.UNKNOWN and r.positive.reason == "quote_source_inapplicable"
    assert r.positive.assurance.span_integrity == "verified"  # the quote really is in the evidence...
    assert r.positive.assurance.applicability is Applicability.NO_MATCH  # ...of a source that does not apply
    assert r.positive.assurance.independently_supported is False
    # a fabricated quote fails integrity even though the verdict says supported
    r, _, _ = run_assured(tmp_path, side(True, "Refunds are free forever."), side(False))
    assert r.outcome is Outcome.UNKNOWN and r.positive.reason == "quote_not_in_evidence"
    assert r.positive.assurance.span_integrity == "failed"
    # the right customer's exact quote is supported, with a verified location, and still only model-judged
    r, a, b = run_assured(tmp_path, side(True, QUOTE_42), side(False))
    assert r.outcome is Outcome.TRUE
    ass = r.positive.assurance
    assert (ass.span_integrity, ass.applicability, ass.semantic) == ("verified", Applicability.MATCH, "model_judged")
    assert ass.independently_supported is False
    ref = r.positive.quote_ref
    assert ref.revision_id == a.revision_id and a.decoded.text[ref.start : ref.end] == QUOTE_42  # exact absolute offsets
    verify_span(a, make_span(a, ref.start, ref.end))  # the located quote is a valid span of the source


def test_quote_must_sit_inside_one_span_and_applicability_unknown_stays_unknown(tmp_path):
    joined = QUOTE_42 + " " + QUOTE_7  # stitched from two different sources
    r, _, _ = run_assured(tmp_path, side(True, joined), side(False))
    assert r.positive.reason == "quote_not_in_evidence"
    r, _, _ = run_assured(tmp_path, side(True, QUOTE_42), side(False), applicability=lambda rid: Applicability.UNKNOWN)
    assert r.outcome is Outcome.UNKNOWN and r.positive.reason == "quote_source_applicability_unknown"


def test_unassessed_applicability_is_disclosed(tmp_path):
    r, _, _ = run_assured(tmp_path, side(True, QUOTE_42), side(False), applicability=None)
    assert r.outcome is Outcome.TRUE and r.positive.assurance.applicability is None
    assert "applicability_not_assessed" in r.caveats
