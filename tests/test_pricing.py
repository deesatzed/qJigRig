"""Synthetic catalog records; no network or paid calls."""
from decimal import Decimal
import pytest
from qjig.contracts import ContractError
from qjig.pricing import upper_cost


def test_conservative_price_includes_overrides_and_cache_categories():
    model = {"id": "synthetic/model", "context_length": 1000, "top_provider": {"max_completion_tokens": 200},
             "pricing": {"prompt": "0.0001", "completion": "0.0002", "input_cache_write": "0.00005",
                         "overrides": [{"prompt": "0.0003", "completion": "0.0004", "min_prompt_tokens": 100}]}}
    # Count every recognized input category at its maximum rate; this is a bound, not an estimate.
    assert upper_cost(model, input_tokens=100, output_tokens=50) == Decimal("0.05500")


def test_missing_or_unbounded_pricing_is_refused():
    valid = {"id": "synthetic/model", "context_length": 1000, "top_provider": {"max_completion_tokens": 200},
             "pricing": {"prompt": "0.0001", "completion": "0.0002"}}
    cases = [
        {**valid, "pricing": {"prompt": "0.1"}},
        {**valid, "pricing": {"prompt": "nan", "completion": "0.1"}},
        {**valid, "pricing": {"prompt": "0.1", "completion": "0.1", "request": "0.5"}},
        {**valid, "pricing": {"prompt": "0.1", "completion": "0.1", "overrides": [{"mystery": "1"}]}},
    ]
    for model in cases:
        with pytest.raises(ContractError):
            upper_cost(model, input_tokens=100, output_tokens=50)
    for input_tokens, output_tokens in [(True, 20), (-1, 20), (900, 101), (1, 201)]:
        with pytest.raises(ContractError):
            upper_cost(valid, input_tokens=input_tokens, output_tokens=output_tokens)


def test_provider_context_limit_is_also_enforced():
    model = {"id": "synthetic/model", "context_length": 1000,
             "top_provider": {"context_length": 120, "max_completion_tokens": 100},
             "pricing": {"prompt": "0.001", "completion": "0.001"}}
    with pytest.raises(ContractError):
        upper_cost(model, input_tokens=100, output_tokens=21)


def test_reservation_rounds_float_up_and_binds_model():
    from qjig.providers import ProviderRequest, make_call_reservation
    request = ProviderRequest("planner", "stand-in", "synthetic/model", "question", 10)
    model = {"id": "synthetic/model", "context_length": 1000, "top_provider": {"max_completion_tokens": 100},
             "pricing": {"prompt": "0.000000000000000003333333333", "completion": "0.000000000000000002"}}
    exact = upper_cost(model, input_tokens=17, output_tokens=10)
    reservation = make_call_reservation(request, model, input_tokens=17, input_bound_provenance="synthetic fixture")
    assert Decimal(str(reservation.cost_usd)) >= exact
    with pytest.raises(ContractError):
        make_call_reservation(request, {**model, "id": "another/model"}, input_tokens=17, input_bound_provenance="fixture")
