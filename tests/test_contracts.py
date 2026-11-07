import json

import pytest

from qjig.contracts import ContractError, Request


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
