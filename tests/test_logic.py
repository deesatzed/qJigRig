import pytest

from qjig.contracts import ContractError
from qjig.logic import Outcome, Support, combine_support


@pytest.mark.parametrize(
    "pos,neg,expected",
    [
        (Support.SUPPORTED, Support.UNKNOWN, Outcome.TRUE),
        (Support.UNKNOWN, Support.SUPPORTED, Outcome.FALSE),
        (Support.UNKNOWN, Support.UNKNOWN, Outcome.UNKNOWN),
        (Support.SUPPORTED, Support.SUPPORTED, Outcome.CONFLICT),
    ],
)
def test_support_state_table(pos, neg, expected):
    assert combine_support(pos, neg) is expected


def test_four_combinations_give_four_distinct_outcomes():
    results = {combine_support(p, n) for p in Support for n in Support}
    assert results == {Outcome.TRUE, Outcome.FALSE, Outcome.UNKNOWN, Outcome.CONFLICT}


@pytest.mark.parametrize("pos,neg", [(True, False), (False, False), ("supported", Support.UNKNOWN), (None, Support.UNKNOWN), (Support.UNKNOWN, 0)])
def test_only_explicit_support_states_are_accepted(pos, neg):
    # a bare boolean/score cannot stand in for support on the negative side
    with pytest.raises(ContractError):
        combine_support(pos, neg)
