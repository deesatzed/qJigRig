from qjig.logic import Observation, Outcome
from qjig.obligations import Obligation, ObligationLedger
from qjig.stopping import check_stop

T, F, U = Outcome.TRUE, Outcome.FALSE, Outcome.UNKNOWN
EITHER = {"op": "or", "args": [{"ref": "ordinary"}, {"ref": "exception"}]}


def obs(**kw):
    return {k: Observation(v, "r") for k, v in kw.items()}


def ledger(*items):
    led = ObligationLedger()
    for i in items:
        led.open(i)
    return led


APPLICABILITY = Obligation("ob-app", "applicability", "ordinary", "Does the 30-day rule apply to this customer?", material=True)
SIDE = Obligation("ob-side", "predicate_evidence", "exception", "side detail", material=False)


def test_coverage_blocks_stop():
    # the expression is stable (ordinary=true under OR) but applicability is unresolved
    led = ledger(APPLICABILITY)
    d = check_stop(EITHER, obs(ordinary=T, exception=U), led)
    assert d.stop is False and d.outcome is None
    assert d.blocking_obligations == ("ob-app",) and "material_obligation_unresolved" in d.reasons
    # once it is satisfied with evidence the same expression may stop, with its outcome
    led.satisfy("ob-app", evidence_entry_ids=("e1",))
    d2 = check_stop(EITHER, obs(ordinary=T, exception=U), led)
    assert d2.stop is True and d2.outcome is True and d2.blocking_obligations == ()
    # the unresolved exception is recorded as a caveat, not hidden
    assert "stable_despite_unresolved_predicates" in d2.caveats and d2.unresolved_ids == ("exception",)


def test_unstable_expression_does_not_stop():
    led = ledger()
    d = check_stop(EITHER, obs(ordinary=F, exception=U), led)
    assert d.stop is False and d.reasons == ("outcome_not_determined",) and d.outcome is None


def test_immaterial_obligations_do_not_block_and_fully_known_stops_cleanly():
    led = ledger(SIDE)
    d = check_stop(EITHER, obs(ordinary=F, exception=F), led)
    assert d.stop is True and d.outcome is False and d.caveats == ()


def test_tautology_is_marked_as_expression_only():
    taut = {"op": "or", "args": [{"ref": "a"}, {"op": "not", "args": [{"ref": "a"}]}]}
    d = check_stop(taut, obs(a=U), ledger())
    assert d.stop is True and d.outcome is True
    assert "stable_despite_unresolved_predicates" in d.caveats  # a property of the expression, not of any fact
