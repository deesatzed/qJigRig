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


def test_account_refresh_fetches_after_baseline_and_keeps_only_constraints(tmp_path):
    import json
    from qjig.account_client import refresh_account_constraints
    from qjig.contracts import Budget
    from qjig.goal_budget import GoalBudget
    from qjig.budgets import BudgetExceeded

    key={'data':{'limit_remaining':1,'include_byok_in_limit':False,'is_free_tier':False}}
    credits={'data':{'total_credits':1,'total_usage':0}}
    env=tmp_path/'provider.env'; env.write_text('OPENROUTER_API_KEY=test-secret\n')
    limit=Budget(3,500,1)
    seen=[]
    def fake_get(url, headers, timeout):
        seen.append((url,headers['Authorization'],timeout))
        response=({'data':{**key['data'],'limit_remaining':0.2,'label':'private'}} if url.endswith('/key') else credits)
        return 200,json.dumps(response)
    with GoalBudget.open(tmp_path/'g.sqlite',total=limit,per_request=limit,allocations={'s':limit},account_snapshot=(key,credits)) as goal:
        refresh_account_constraints(goal,env,get=fake_get)
        assert [x[0] for x in seen]==['https://openrouter.ai/api/v1/key','https://openrouter.ai/api/v1/credits']
        assert all(x[1]=='Bearer test-secret' for x in seen)
        assert 'private' not in goal._con.execute('SELECT snapshot FROM account_restrictions').fetchone()[0]
        with pytest.raises(BudgetExceeded):goal.reserve('a','r','s',tokens=1,cost_usd=0.21)


def test_account_refresh_fails_closed_without_leaking_provider_errors(tmp_path):
    from qjig.account_client import refresh_account_constraints, AccountRefreshError
    from qjig.contracts import Budget
    from qjig.goal_budget import GoalBudget
    key={'data':{'limit_remaining':1,'include_byok_in_limit':False,'is_free_tier':False}}
    credits={'data':{'total_credits':1,'total_usage':0}}
    env=tmp_path/'provider.env';env.write_text('OPENROUTER_API_KEY=test-secret\n')
    limit=Budget(1,100,1)
    with GoalBudget.open(tmp_path/'g.sqlite',total=limit,per_request=limit,allocations={'s':limit},account_snapshot=(key,credits)) as goal:
        for response in ((302,'test-secret'),(200,'not json'),(200,'{"data":{}}')):
            with pytest.raises(AccountRefreshError) as error:
                refresh_account_constraints(goal,env,get=lambda *args:response)
            assert 'test-secret' not in str(error.value)
        assert goal._con.execute('SELECT COUNT(*) FROM account_restrictions').fetchone()[0]==0


def test_account_refresh_rejects_ledger_changes_during_fetch(tmp_path):
    import json
    from qjig.account_client import refresh_account_constraints
    from qjig.contracts import Budget
    from qjig.goal_budget import GoalBudget
    key={'data':{'limit_remaining':1,'include_byok_in_limit':False,'is_free_tier':False}}
    credits={'data':{'total_credits':1,'total_usage':0}}
    env=tmp_path/'provider.env';env.write_text('OPENROUTER_API_KEY=test-secret\n')
    limit=Budget(2,100,1)
    with GoalBudget.open(tmp_path/'g.sqlite',total=limit,per_request=limit,allocations={'s':limit},account_snapshot=(key,credits)) as goal:
        def get(url, headers, timeout):
            if url.endswith('/key'):
                goal.reserve('a','r','s',tokens=10,cost_usd=0.1)
                goal.record_usage('a',input_tokens=2,output_tokens=2,cost_usd=0.05)
                return 200,json.dumps(key)
            return 200,json.dumps(credits)
        with pytest.raises(ContractError,match='changed'):
            refresh_account_constraints(goal,env,get=get)
        assert goal._con.execute('SELECT COUNT(*) FROM account_restrictions').fetchone()[0]==0


def test_account_get_refuses_redirect_without_forwarding_credentials():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.error import HTTPError
    from qjig.account_client import _get
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.path)
            self.send_response(302)
            self.send_header('Location', '/destination')
            self.end_headers()
        def log_message(self, *args):
            pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with pytest.raises(HTTPError):
            _get(f'http://127.0.0.1:{server.server_port}/start',{'Authorization':'Bearer dummy'},2)
        assert received==['/start']
    finally:
        server.shutdown();thread.join();server.server_close()


def test_initial_account_snapshot_is_sanitized_and_can_bind_goal(tmp_path):
    import json
    from qjig.account_client import fetch_account_snapshot
    from qjig.contracts import Budget
    from qjig.goal_budget import GoalBudget
    env=tmp_path/'provider.env';env.write_text('OPENROUTER_API_KEY=test-secret\n')
    def get(url, headers, timeout):
        data=({'limit_remaining':0.6,'include_byok_in_limit':False,'is_free_tier':False,
               'label':'private'} if url.endswith('/key') else
              {'total_credits':1,'total_usage':0.2,'account_id':'private'})
        return 200,json.dumps({'data':data})
    snapshot=fetch_account_snapshot(env,get=get)
    assert snapshot==({'data':{'limit_remaining':Decimal('0.6'),'include_byok_in_limit':False,'is_free_tier':False}},
                      {'data':{'total_credits':1,'total_usage':Decimal('0.2')}})
    assert 'private' not in repr(snapshot) and 'test-secret' not in repr(snapshot)
    limit=Budget(2,100,0.6)
    with GoalBudget.open(tmp_path/'g.sqlite',total=limit,per_request=limit,allocations={'s':limit},account_snapshot=snapshot):
        pass


def test_account_snapshot_rejects_changed_credential_before_network(tmp_path):
    from qjig.account_client import fetch_account_snapshot,AccountRefreshError
    env=tmp_path/'env';env.write_text('OPENROUTER_API_KEY=synthetic-new\n')
    sent=[]
    with pytest.raises(AccountRefreshError,match='credential') as error:
        fetch_account_snapshot(env,get=lambda *args:sent.append(args),expected_credential='synthetic-old')
    assert sent==[] and 'synthetic-old' not in str(error.value) and 'synthetic-new' not in str(error.value)


def test_account_snapshot_rejects_invalid_credential_file_safely(tmp_path):
    from qjig.account_client import fetch_account_snapshot,AccountRefreshError
    env=tmp_path/'env';env.write_bytes(b'OPENROUTER_API_KEY=secret-\xff')
    sent=[]
    with pytest.raises(AccountRefreshError) as error:
        fetch_account_snapshot(env,get=lambda *args:sent.append(args))
    assert sent==[] and 'secret' not in str(error.value)
