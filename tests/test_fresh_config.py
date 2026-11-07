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
