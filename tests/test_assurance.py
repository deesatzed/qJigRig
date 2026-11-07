"""Authored hypothetical controls, not independent labels or model-quality evidence."""
import json
from pathlib import Path
from qjig.assurance import Counterexample, check_counterexamples
from qjig.logic import Observation, Outcome
from qjig.plans import parse_plan


def test_saved_expression_fails_enabling_exception_control():
    report = json.loads((Path(__file__).resolve().parents[1] / "reports/t048-fresh-live.json").read_text())
    saved = report["runs"][1]
    plan = parse_plan({"origin": "fresh", "predicates": [{"id": p[0], "question": p[1]} for p in saved["predicates"]], "expression": saved["expression"]})
    # Hypothesis for this mechanical counterexample: p4 represents an applicable enabling
    # exception. The saved predicate itself asks only whether an exception COULD change the
    # result, so this assignment does not establish what that model intended or what is true.
    case = Counterexample("enabling", {"p1": Observation(Outcome.TRUE), "p2": Observation(Outcome.FALSE),
                                        "p3": Observation(Outcome.TRUE), "p4": Observation(Outcome.TRUE)},
                          expected=Outcome.TRUE, attribution="authored_hypothetical")
    (result,) = check_counterexamples(plan, [case])
    assert result.actual is Outcome.FALSE
    assert result.classification == "contradicts_authored_expectation"
    assert result.attribution == "authored_hypothetical"
    assert result.independent is False


def test_authored_enabling_restricting_and_unknown_controls():
    predicates = [{"id": x, "question": x} for x in ("eligible", "ordinary", "exception")]
    enabling = parse_plan({"origin": "authored", "predicates": predicates,
                           "expression": {"op": "and", "args": [
                               {"ref": "eligible"}, {"op": "or", "args": [{"ref": "ordinary"}, {"ref": "exception"}]}]}})
    restricting = parse_plan({"origin": "authored", "predicates": predicates,
                             "expression": {"op": "and", "args": [{"ref": "eligible"}, {"ref": "ordinary"},
                                              {"op": "not", "args": [{"ref": "exception"}]}]}})
    yes, no, conflict = Observation(Outcome.TRUE), Observation(Outcome.FALSE), Observation(Outcome.CONFLICT, "conflicting_sources")
    enabling_case = Counterexample("enabling", {"eligible": yes, "ordinary": no, "exception": yes}, Outcome.TRUE, "authored_control")
    restricting_case = Counterexample("restricting", {"eligible": yes, "ordinary": yes, "exception": yes}, Outcome.FALSE, "authored_control")
    missing_case = Counterexample("missing", {"eligible": yes, "ordinary": no}, Outcome.UNKNOWN, "authored_control")
    conflict_case = Counterexample("conflict", {"eligible": yes, "ordinary": no, "exception": conflict}, Outcome.CONFLICT, "authored_control")
    assert all(r.classification == "matches_authored_expectation" for r in check_counterexamples(enabling, [enabling_case, missing_case, conflict_case]))
    assert check_counterexamples(restricting, [restricting_case])[0].actual is Outcome.FALSE
    uncertain = Counterexample("unproven", {"eligible": yes, "ordinary": no}, Outcome.TRUE, "authored_control")
    assert check_counterexamples(enabling, [uncertain])[0].classification == "inconclusive"
