import json

import pytest

from qjig.contracts import Budget, ContractError, Request


def make_request():
    return Request(
        request_id="r-1",
        question="Does module A call module B?",
        role="reviewer",
        role_version="2",
        scope="repo:alpha",
    )


def test_roundtrip_request():
    request = make_request()
    wire = json.dumps(request.to_dict())
    parsed = Request.from_dict(json.loads(wire))
    assert parsed == request
    # role and scope are kept exactly, with no case folding or trimming
    odd = Request(
        request_id="r-2", question="q", role=" Reviewer ", role_version="2", scope="Repo:Alpha"
    )
    assert Request.from_dict(odd.to_dict()) == odd
    assert Request.from_dict(odd.to_dict()).role == " Reviewer "
    # unknown schema version is rejected, not guessed at
    bad = request.to_dict()
    bad["schema_version"] = "qjig.request.v999"
    with pytest.raises(ContractError):
        Request.from_dict(bad)
    missing = request.to_dict()
    del missing["schema_version"]
    with pytest.raises(ContractError):
        Request.from_dict(missing)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_calls", True),
        ("max_tokens", True),
        ("max_cost_usd", True),
        ("max_calls", -1),
        ("max_tokens", -5),
        ("max_cost_usd", -0.01),
        ("max_calls", 1.5),
        ("max_calls", "3"),
        ("max_cost_usd", float("nan")),
        ("max_cost_usd", float("inf")),
    ],
)
def test_reject_invalid_budget(field, value):
    limits = {"max_calls": 3, "max_tokens": 1000, "max_cost_usd": 0.5}
    limits[field] = value
    with pytest.raises(ContractError):
        Budget(**limits)
    # also rejected when arriving through a request, before anything else runs
    data = make_request().to_dict()
    data["budget"] = limits
    with pytest.raises(ContractError):
        Request.from_dict(data)


def test_valid_budget_roundtrips_and_zero_is_allowed():
    request = Request(
        request_id="r-3", question="q", role="r", role_version="1", scope="s",
        budget=Budget(max_calls=0, max_tokens=0, max_cost_usd=0),
    )
    assert Request.from_dict(json.loads(json.dumps(request.to_dict()))) == request
    assert make_request().budget is None
