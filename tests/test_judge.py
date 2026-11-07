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
    assert r.caveats == ("positive_side_failed:malformed_output",)  # the possible hidden conflict is stated
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
        assert r.caveats == ("negative_side_failed:budget_exceeded",)
