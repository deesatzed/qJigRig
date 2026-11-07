import pytest

from qjig.contracts import ContractError
from qjig.roles import RoleDefinition, RoleEstimate, RoleEstimateStore


def estimate(role_version="1", score=0.8, entry_id="e1", revision_id="rev-1", role_id="reviewer"):
    return RoleEstimate(
        role_id=role_id, role_version=role_version, entry_id=entry_id, revision_id=revision_id,
        estimated_usefulness=score, method="manual_v1", receipt="hand entered",
    )


def test_role_version_binding():
    store = RoleEstimateStore()
    store.put(estimate(role_version="1", score=0.9))
    assert store.current_prior("reviewer", "1", "e1", "rev-1").estimated_usefulness == 0.9
    # the role definition changes: the old estimate is not a current prior any more
    assert store.current_prior("reviewer", "2", "e1", "rev-1") is None
    # but it is retained and inspectable, still labeled with the version it was made for
    kept = store.all_for("e1")
    assert [(e.role_version, e.estimated_usefulness) for e in kept] == [("1", 0.9)]
    # a new estimate under version 2 is current; version 1 stays unavailable under version 2
    store.put(estimate(role_version="2", score=0.2))
    assert store.current_prior("reviewer", "2", "e1", "rev-1").estimated_usefulness == 0.2
    assert store.current_prior("reviewer", "1", "e1", "rev-1").estimated_usefulness == 0.9
    assert len(store.all_for("e1")) == 2


def test_estimate_is_bound_to_role_and_revision():
    store = RoleEstimateStore()
    store.put(estimate())
    assert store.current_prior("other-role", "1", "e1", "rev-1") is None
    assert store.current_prior("reviewer", "1", "e1", "rev-2") is None  # source changed
    assert store.current_prior("reviewer", "1", "e2", "rev-1") is None
    # re-putting the same key replaces nothing silently
    with pytest.raises(ContractError):
        store.put(estimate(score=0.1))


@pytest.mark.parametrize("score", [True, -0.1, 1.1, float("nan"), "0.5", None])
def test_invalid_scores_rejected(score):
    with pytest.raises(ContractError):
        estimate(score=score)


def test_role_definition_is_frozen_and_validated():
    r = RoleDefinition("reviewer", "1", "Check release rules")
    with pytest.raises(Exception):
        r.version = "2"  # type: ignore[misc]
    with pytest.raises(ContractError):
        RoleDefinition("", "1", "x")
    assert estimate().state == "proposed"
