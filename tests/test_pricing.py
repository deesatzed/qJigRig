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


def test_capped_routing_reservation_covers_ceiling_and_snapshot():
    from qjig.providers import ProviderRequest, make_call_reservation
    request = ProviderRequest('judge', 'openrouter', 'synthetic/model', 'question', 50,
                              max_price={'prompt': 10.0, 'completion': 20.0})
    model = {'id': request.model, 'context_length': 1000, 'top_provider': {'max_completion_tokens': 100},
             'pricing': {'prompt': '0.0000001', 'completion': '0.0000002', 'input_cache_write': '0.0000003'}}
    snapshot_cost = upper_cost(model, input_tokens=100, output_tokens=50)
    ceiling_cost = Decimal('10') * 100 / 1000000 + Decimal('20') * 50 / 1000000
    reservation = make_call_reservation(request, model, input_tokens=100, input_bound_provenance='fixture')
    assert Decimal(str(reservation.cost_usd)) >= snapshot_cost + ceiling_cost


def test_discounts_reserve_at_least_the_undiscounted_price():
    model = {'id':'synthetic/model','context_length':1000,'top_provider':{'max_completion_tokens':100},
             'pricing':{'prompt':'0.000001','completion':'0.000002','input_cache_read':'0.0000001','discount':0}}
    assert upper_cost(model,input_tokens=100,output_tokens=50) == Decimal('0.0002100')
    discounted = {**model, 'pricing': {**model['pricing'], 'discount': 0.5}}
    assert upper_cost(discounted,input_tokens=100,output_tokens=50) >= Decimal('0.0004200')
    for value in (-1, 1, 2, True, '0', None, float('nan')):
        with pytest.raises(ContractError):
            upper_cost({**model,'pricing':{**model['pricing'],'discount':value}},input_tokens=100,output_tokens=50)
    with pytest.raises(ContractError):
        upper_cost({**model,'pricing':{**model['pricing'],'web_search':'0.01'}},input_tokens=100,output_tokens=50)


def test_endpoint_snapshot_checks_model_identity_and_preserves_price_categories():
    from qjig.pricing import parse_endpoint_snapshot
    payload = {'data': {'id': 'tencent/hy4', 'endpoints': [
        {'provider_name':'Tencent', 'model_id':'tencent/hy4', 'context_length':10000,
         'max_completion_tokens':1000, 'pricing':{'prompt':'0.1', 'completion':'0.2', 'discount':0.5}}]}}
    snapshot = parse_endpoint_snapshot(payload, expected_model='tencent/hy4')
    assert snapshot['endpoints'][0]['pricing']['discount'] == 0.5
    changed = {'data': {**payload['data'], 'id': 'different/model'}}
    with pytest.raises(ContractError):
        parse_endpoint_snapshot(changed, expected_model='tencent/hy4')
    with pytest.raises(ContractError):
        parse_endpoint_snapshot({'data': {'id':'tencent/hy4', 'endpoints':[]}}, expected_model='tencent/hy4')


def test_endpoint_fetch_refuses_redirect_and_does_not_return_unchecked_body():
    from qjig.pricing import fetch_endpoint_snapshot
    with pytest.raises(ContractError):
        fetch_endpoint_snapshot('tencent/hy4', get=lambda url, timeout: (302, '{}'))
    with pytest.raises(ContractError):
        fetch_endpoint_snapshot('unapproved/model', get=lambda url, timeout: pytest.fail('unexpected request'))


def test_endpoint_snapshot_model_reserves_across_all_routes_and_rejects_unknown_prices():
    from datetime import datetime, timezone
    from qjig.pricing import model_from_endpoint_snapshot
    from qjig.providers import ProviderRequest, make_call_reservation
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    first = {'model_id':'tencent/hy4','provider_name':'A','context_length':1000,'max_completion_tokens':100,
             'pricing':{'prompt':'0.000001','completion':'0.000002','discount':0}}
    second = {'model_id':'tencent/hy4','provider_name':'B','context_length':800,'max_completion_tokens':80,
              'pricing':{'prompt':'0.000003','completion':'0.000001','input_cache_read':'0.000001','discount':0}}
    snapshot = {'model':'tencent/hy4','source':'openrouter_public_endpoint_catalog',
                'observed_at':now.isoformat(),'endpoints':[first,second]}
    model = model_from_endpoint_snapshot(snapshot, now=now, max_age_seconds=30)
    req = ProviderRequest('judge','openrouter','tencent/hy4','question',50,
                          max_price={'prompt':10,'completion':20})
    bound = make_call_reservation(req,model,input_tokens=100,input_bound_provenance='synthetic estimate')
    assert Decimal(str(bound.cost_usd)) >= Decimal('0.0005')
    changed = {**snapshot,'endpoints':[first,{**second,'pricing':{**second['pricing'],'discount':1}}]}
    with pytest.raises(ContractError):
        model_from_endpoint_snapshot(changed,now=now,max_age_seconds=30)
    with pytest.raises(ContractError):
        model_from_endpoint_snapshot(snapshot,now=now.replace(minute=1),max_age_seconds=30)


def test_current_endpoint_prices_must_fit_the_existing_request_reservation():
    from datetime import datetime, timezone
    from qjig.pricing import model_from_endpoint_snapshot
    from qjig.providers import ProviderRequest, make_call_reservation, check_current_endpoint_cost
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    endpoint = {'model_id':'tencent/hy4','provider_name':'Tencent','context_length':100000,
                'max_completion_tokens':1000,
                'pricing':{'prompt':'0.000001','completion':'0.000002','discount':0}}
    snapshot = {'model':'tencent/hy4','source':'openrouter_public_endpoint_catalog',
                'observed_at':now.isoformat(),'endpoints':[endpoint]}
    request = ProviderRequest('judge','openrouter','tencent/hy4','question',100,
                              max_price={'prompt':10,'completion':20})
    model = model_from_endpoint_snapshot(snapshot, now=now, max_age_seconds=30)
    reservation = make_call_reservation(request, model, input_tokens=5000, input_bound_provenance='synthetic')
    result = check_current_endpoint_cost(request, reservation, snapshot=snapshot, now=now, max_age_seconds=30)
    assert result['current_cost_usd'] <= reservation.cost_usd
    increased = {**snapshot,'endpoints':[{**endpoint,'pricing':{**endpoint['pricing'],'prompt':'0.001'}}]}
    with pytest.raises(ContractError, match='reservation'):
        check_current_endpoint_cost(request,reservation,snapshot=increased,now=now,max_age_seconds=30)


def test_provider_route_candidate_keeps_all_matching_variants_and_refuses_ambiguous_tags():
    from datetime import datetime,timezone
    from qjig.pricing import candidate_provider_pricing
    now=datetime(2026,11,7,tzinfo=timezone.utc)
    def endpoint(tag,prompt):
        return {'model_id':'tencent/hy4','provider_name':'Synthetic','tag':tag,'context_length':1000,
                'max_completion_tokens':100,'pricing':{'prompt':prompt,'completion':'0.000002','discount':0}}
    snapshot={'model':'tencent/hy4','source':'openrouter_public_endpoint_catalog','observed_at':now.isoformat(),
              'endpoints':[endpoint('alpha/fp8','0.000001'),endpoint('alpha/us','0.000003'),endpoint('other/fp8','0.01')]}
    candidate=candidate_provider_pricing(snapshot,provider_slug='alpha',now=now,max_age_seconds=60)
    assert candidate['route_count']==2 and candidate['model']['pricing']['prompt']=='0.000003'
    assert candidate['hosted_authorized'] is False and candidate['assurance']=='catalog_route_candidate_only'
    with pytest.raises(ContractError):
        candidate_provider_pricing(snapshot,provider_slug='missing',now=now,max_age_seconds=60)
    with pytest.raises(ContractError):
        candidate_provider_pricing({**snapshot,'endpoints':snapshot['endpoints']+[endpoint(None,'0.1')]},
                                   provider_slug='alpha',now=now,max_age_seconds=60)
    with pytest.raises(ContractError):
        candidate_provider_pricing(snapshot,provider_slug='alpha/*',now=now,max_age_seconds=60)
    from datetime import timedelta
    with pytest.raises(ContractError):
        candidate_provider_pricing(snapshot,provider_slug='alpha',now=now+timedelta(seconds=61),max_age_seconds=60)
    changed=endpoint('alpha/fp8','0.000001');changed['pricing']['web_search']='0.01'
    with pytest.raises(ContractError):
        candidate_provider_pricing({**snapshot,'endpoints':[changed]},provider_slug='alpha',now=now,max_age_seconds=60)
    variant=candidate_provider_pricing(snapshot,provider_slug='alpha/us',now=now,max_age_seconds=60)
    assert variant['route_count']==1 and variant['model']['pricing']['prompt']=='0.000003'
