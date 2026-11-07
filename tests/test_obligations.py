import pytest

from qjig.contracts import ContractError
from qjig.obligations import Obligation, ObligationLedger
from qjig.packets import build_packet
from qjig.recovery import Exclusion, RecoveryResult


def ledger_with_exception():
    ledger = ObligationLedger()
    ledger.open(Obligation("ob-exc", "exception", "refund_ok", "Any waiver or exception to the 30-day rule?", material=True))
    return ledger


def empty_result(exclusions=(), unfilled=1):
    return RecoveryResult(build_packet([], max_bytes=2000), tuple(exclusions), {}, unfilled)


def test_no_hit_is_unknown():
    ledger = ledger_with_exception()
    assert ledger.get("ob-exc").status == "open"
    ledger.record_retrieval("ob-exc", hit_count=0, result=empty_result())
    ob = ledger.get("ob-exc")
    # no hit leaves the question unresolved with its own reason; it is not a "no exception exists" fact
    assert ob.status == "unresolved" and ob.reason == "no_retrieval_hit"
    assert not ledger.absence_established("ob-exc")
    assert ledger.blocking() == ["ob-exc"]
    # repeating a miss does not change that; only an explicit satisfaction with evidence closes it
    ledger.record_retrieval("ob-exc", hit_count=0, result=empty_result())
    assert ledger.get("ob-exc").status == "unresolved"
    with pytest.raises(ContractError):
        ledger.satisfy("ob-exc", evidence_entry_ids=())
    ledger.satisfy("ob-exc", evidence_entry_ids=("e1",))
    assert ledger.get("ob-exc").status == "satisfied" and ledger.blocking() == []


def test_unresolved_reasons_stay_distinct():
    cases = [
        (3, [Exclusion("a", "source_missing")], "source_unavailable"),
        (2, [Exclusion("a", "inapplicable"), Exclusion("b", "inapplicable")], "only_inapplicable_candidates"),
        (1, [Exclusion("a", "applicability_unknown")], "applicability_unknown"),
        (1, [Exclusion("a", "inapplicable"), Exclusion("b", "applicability_unknown")], "applicability_unknown"),
    ]
    seen = set()
    for hits, exclusions, reason in cases:
        ledger = ledger_with_exception()
        ledger.record_retrieval("ob-exc", hit_count=hits, result=empty_result(exclusions))
        assert ledger.get("ob-exc").status == "unresolved" and ledger.get("ob-exc").reason == reason
        seen.add(reason)
    assert len(seen) == 3 and "no_retrieval_hit" not in seen


def test_found_truncated_and_immaterial_cases():
    from qjig.indexing import index_entries
    from qjig.retrieval import bm25_candidates
    from qjig.sources import SourceRevision, decode_source

    r = SourceRevision.create("p/x.md", "/x", decode_source(("# T\n" + "refund waiver text. " * 30).encode(), encoding="utf-8"))
    cands = bm25_candidates(index_entries(r), "refund waiver")
    ok = RecoveryResult(build_packet(cands, max_bytes=5000), (), {}, 0)
    ledger = ledger_with_exception()
    ledger.record_retrieval("ob-exc", hit_count=1, result=ok)
    assert ledger.get("ob-exc").status == "evidence_found"  # found is not yet evaluated or satisfied
    assert ledger.blocking() == ["ob-exc"]
    cut = RecoveryResult(build_packet(cands, max_bytes=500), (), {}, 0)
    assert cut.packet.truncated_entry_ids
    ledger2 = ledger_with_exception()
    ledger2.record_retrieval("ob-exc", hit_count=1, result=cut)
    assert ledger2.get("ob-exc").status == "unresolved" and ledger2.get("ob-exc").reason == "truncated"
    # an immaterial obligation does not block, but is still recorded as unresolved
    ledger3 = ObligationLedger()
    ledger3.open(Obligation("ob-x", "predicate_evidence", "p2", "side detail", material=False))
    ledger3.record_retrieval("ob-x", hit_count=0, result=empty_result())
    assert ledger3.get("ob-x").status == "unresolved" and ledger3.blocking() == []


def test_duplicate_and_unknown_ids_rejected():
    ledger = ledger_with_exception()
    with pytest.raises(ContractError):
        ledger.open(Obligation("ob-exc", "exception", "p", "dup", material=True))
    with pytest.raises(KeyError):
        ledger.record_retrieval("nope", hit_count=0, result=empty_result())
    with pytest.raises(ContractError):
        Obligation("o", "not-a-kind", "p", "d", material=True)


def test_skip_is_recorded_and_never_applies_to_request_level_obligations():
    ledger = ObligationLedger()
    ledger.open(Obligation("ob-p", "predicate_evidence", "p", "d", material=True))
    ledger.open(Obligation("ob-app", "applicability", "p", "d", material=True))
    ledger.skip("ob-p", reason="a=false (outside_window)")
    assert ledger.get("ob-p").status == "skipped" and "outside_window" in ledger.get("ob-p").reason
    assert ledger.blocking() == ["ob-app"]
    with pytest.raises(ContractError):
        ledger.skip("ob-app", reason="because")
    with pytest.raises(ContractError):
        ledger.skip("ob-p", reason="  ")
