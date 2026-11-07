"""Synthetic account metadata; no credential or network access."""
from decimal import Decimal
import pytest
from qjig.contracts import ContractError
from qjig.account_limits import account_spend_constraints


def test_account_ceiling_uses_strictest_remaining_limit_without_claiming_authorization():
    key={'data':{'limit_remaining':7.25,'include_byok_in_limit':False,'is_free_tier':False}}
    credits={'data':{'total_credits':20.0,'total_usage':11.0}}
    result=account_spend_constraints(key,credits,goal_ceiling_usd=25)
    assert result['openrouter_credit_ceiling_usd']==Decimal('7.25')
    assert result['byok_spend_assurance']=='unknown' and result['hosted_authorized'] is False
    assert result['source_assurance']=='caller_supplied_snapshot'
    key['data']['limit_remaining']=None
    assert account_spend_constraints(key,credits,goal_ceiling_usd=5)['openrouter_credit_ceiling_usd']==Decimal('5')
    key['data']['limit_remaining']=7.25;key['data']['include_byok_in_limit']=True
    assert account_spend_constraints(key,credits,goal_ceiling_usd=25)['byok_spend_assurance']=='provider_claimed_key_limit'
    credits['data']['total_usage']=21
    assert account_spend_constraints(key,credits,goal_ceiling_usd=25)['openrouter_credit_ceiling_usd']==Decimal('0')


def test_account_ceiling_refuses_missing_nonfinite_or_malformed_inputs():
    key={'data':{'limit_remaining':7,'include_byok_in_limit':False,'is_free_tier':False}}
    credits={'data':{'total_credits':20,'total_usage':10}}
    for bad in (True,float('nan'),float('inf'),-1,'7'):
        with pytest.raises(ContractError):
            account_spend_constraints({'data':{**key['data'],'limit_remaining':bad}},credits,goal_ceiling_usd=25)
    for bad in ({'data':{}},{'data':{'total_credits':True,'total_usage':0}},
                {'data':{'total_credits':1,'total_usage':-1}}):
        with pytest.raises(ContractError):account_spend_constraints(key,bad,goal_ceiling_usd=25)
    for bad in (0,26,True,float('nan')):
        with pytest.raises(ContractError):account_spend_constraints(key,credits,goal_ceiling_usd=bad)


def test_credit_subtraction_never_rounds_a_near_cap_upward():
    key={'data':{'limit_remaining':None,'include_byok_in_limit':False,'is_free_tier':False}}
    credits={'data':{'total_credits':Decimal('1000000000000000000000000000000000000000024.999999999999999999999999999999'),
                     'total_usage':Decimal('1000000000000000000000000000000000000000000')}}
    result=account_spend_constraints(key,credits,goal_ceiling_usd=25)
    assert result['openrouter_credit_ceiling_usd']==Decimal('24.999999999999999999999999999999')
