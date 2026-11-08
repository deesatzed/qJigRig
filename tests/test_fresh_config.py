"""The local CLI exposes a trusted configuration without authorizing paid calls."""
import json
import os
import subprocess
import sys
from pathlib import Path
import urllib.error
import urllib.request

import pytest

from qjig.contracts import ContractError
from qjig.fresh_config import load_fresh_config


def config_for(tmp_path):
    def stage(model):
        return {'provider':'openrouter', 'model':{'id':model, 'context_length':10000,
                'top_provider':{'max_completion_tokens':1000},
                'pricing':{'prompt':'0.000001','completion':'0.000002'}},
                'input_tokens':1000, 'output_tokens':100, 'max_price':{'prompt':2,'completion':3}}
    budget = {'max_calls':30,'max_tokens':100000,'max_cost_usd':1}
    return {'schema':'qjig.fresh-config.v1', 'state_dir':str(tmp_path/'state'),
            'env_path':str(tmp_path/'missing.env'), 'partition':'smoke',
            'total':budget.copy(), 'per_request':budget.copy(), 'allocations':{'smoke':budget.copy(),
            **{name:{'max_calls':0,'max_tokens':0,'max_cost_usd':0} for name in ('pilot','holdout','acceptance')}},
            'planner':stage('deepseek/deepseek-v4.1-flash-1017'),
            'judge':stage('tencent/hy4'), 'reviewer':stage('tencent/hy4')}


def test_cli_configures_fresh_backend_but_refuses_unverified_hosted_calls(tmp_path):
    config = config_for(tmp_path)
    path=tmp_path/'config.json'; path.write_text(json.dumps(config))
    process = subprocess.Popen([sys.executable,'-m','qjig','serve','--catalog',str(tmp_path/'catalog.sqlite'),
                                '--port','0','--fresh-config',str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                               env={**os.environ, 'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')})
    try:
        line=process.stdout.readline()
        assert line, process.stderr.read()
        port=json.loads(line)['port']
        request={'schema_version':'qjig.request.v1','request_id':'one','question':'What applies?',
                 'role':'reviewer','role_version':'1','scope':'project'}
        payload=json.dumps({'request':request,'as_of':'2026-11-15','entities':[]}).encode()
        req=urllib.request.Request(f'http://127.0.0.1:{port}/api/fresh',data=payload,
              headers={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{port}'})
        try:
            urllib.request.urlopen(req,timeout=5)
            assert False, 'hosted call must remain gated'
        except urllib.error.HTTPError as exc:
            assert exc.code == 409
            assert json.load(exc)['error'] == 'fresh planning preflight unavailable or budget exhausted'
        assert not (tmp_path/'state'/'goal.sqlite').exists()
    finally:
        process.terminate(); process.wait(timeout=5)


@pytest.mark.parametrize('change', ['goal_limit', 'request_limit', 'allocation', 'model', 'extra'])
def test_invalid_fresh_configuration_is_rejected_before_state_creation(tmp_path, change):
    config = config_for(tmp_path)
    if change == 'goal_limit': config['total']['max_cost_usd'] = 25.01
    if change == 'request_limit': config['per_request']['max_calls'] = 31
    if change == 'allocation': config['allocations']['smoke']['max_calls'] = 31
    if change == 'model': config['judge']['model']['id'] = 'unapproved/model'
    if change == 'extra': config['credential'] = 'must-not-be-accepted'
    path = tmp_path/'config.json'; path.write_text(json.dumps(config))
    with pytest.raises(ContractError): load_fresh_config(path)
    assert not (tmp_path/'state').exists()


def test_configured_goal_refreshes_account_before_using_persistent_budget(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    backend = load_fresh_config(path)
    observations = [
        ({'data': {'limit_remaining': 10, 'include_byok_in_limit': False, 'is_free_tier': False}},
         {'data': {'total_credits': 10, 'total_usage': 0}}),
        ({'data': {'limit_remaining': 0.4, 'include_byok_in_limit': False, 'is_free_tier': False}},
         {'data': {'total_credits': 10, 'total_usage': 9.6}}),
    ]
    monkeypatch.setattr('qjig.account_client.fetch_account_snapshot', lambda path, **kwargs: observations.pop(0))
    with backend.goal_factory() as goal:
        assert goal._account_bound
    with backend.goal_factory() as goal:
        assert goal._con.execute('SELECT COUNT(*) FROM account_restrictions').fetchone()[0] == 1
    assert observations == []


def test_configured_goal_rejects_unavailable_account_before_creating_ledger(tmp_path, monkeypatch):
    from qjig.account_client import AccountRefreshError
    config = config_for(tmp_path)
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    backend = load_fresh_config(path)
    def unavailable(*args, **kwargs):
        raise AccountRefreshError('account observations unavailable or invalid')
    monkeypatch.setattr('qjig.account_client.fetch_account_snapshot', unavailable)
    with pytest.raises(AccountRefreshError):
        backend.goal_factory()
    assert not (tmp_path / 'state' / 'goal.sqlite').exists()


def test_v2_workbenches_share_goal_and_journal_across_state_directories(tmp_path, monkeypatch):
    observations = ({'data': {'limit_remaining': 10, 'include_byok_in_limit': False, 'is_free_tier': False}},
                    {'data': {'total_credits': 10, 'total_usage': 0}})
    monkeypatch.setattr('qjig.account_client.fetch_account_snapshot', lambda path, **kwargs: observations)
    config = config_for(tmp_path)
    config.update(schema='qjig.fresh-config.v2', goal_dir=str(tmp_path / 'shared-goal'))
    first_path = tmp_path / 'first.json'
    first_path.write_text(json.dumps(config))
    first = load_fresh_config(first_path)
    config['state_dir'] = str(tmp_path / 'second-state')
    second_path = tmp_path / 'second.json'
    second_path.write_text(json.dumps(config))
    second = load_fresh_config(second_path)
    with first.goal_factory() as goal:
        goal.reserve('attempt-one', 'request-one', 'smoke', tokens=100, cost_usd=0.1)
        goal.record_usage('attempt-one', input_tokens=50, output_tokens=10, cost_usd=0.01)
    with second.goal_factory() as goal:
        assert goal.totals().max_calls == 1
    assert first.journal_path == second.journal_path == tmp_path / 'shared-goal' / 'journal.sqlite'


def test_v2_rejects_switching_goal_directory_for_same_credential_root(tmp_path):
    config = config_for(tmp_path)
    config.update(schema='qjig.fresh-config.v2', goal_dir=str(tmp_path / 'first-goal'))
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    load_fresh_config(path)
    config['state_dir'] = str(tmp_path / 'other-state')
    config['goal_dir'] = str(tmp_path / 'second-goal')
    path.write_text(json.dumps(config))
    with pytest.raises(ContractError, match='goal directory'):
        load_fresh_config(path)
    assert not (tmp_path / 'second-goal' / 'goal.sqlite').exists()


def test_v2_binding_rejects_legacy_config_that_could_reset_budget(tmp_path):
    config = config_for(tmp_path)
    config.update(schema='qjig.fresh-config.v2', goal_dir=str(tmp_path / 'shared'))
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    load_fresh_config(path)
    config.pop('goal_dir')
    config['schema'] = 'qjig.fresh-config.v1'
    config['state_dir'] = str(tmp_path / 'other-state')
    path.write_text(json.dumps(config))
    with pytest.raises(ContractError, match='v2 configuration required'):
        load_fresh_config(path)
