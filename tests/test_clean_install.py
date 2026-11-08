"""Opt-in installation smoke; builds a fresh environment and uses synthetic data."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import urllib.request
import venv

import pytest


@pytest.mark.skipif(os.environ.get('QJIG_VERIFY_CLEAN_INSTALL') != '1', reason='explicit clean-install verification required')
def test_clean_install_cli_and_loopback_service(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    staging = tmp_path / 'source'
    (staging / 'src').mkdir(parents=True)
    shutil.copy2(repo / 'pyproject.toml', staging / 'pyproject.toml')
    shutil.copytree(repo / 'src' / 'qjig', staging / 'src' / 'qjig', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    environment = tmp_path / 'venv'
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    clean_env = {key: value for key, value in os.environ.items()
                 if key not in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV') and 'API_KEY' not in key}
    clean_env['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
    install = subprocess.run([str(python), '-I', '-m', 'pip', 'install', '--no-deps', str(staging)], cwd=tmp_path,
                             env=clean_env, capture_output=True, text=True, timeout=120)
    assert install.returncode == 0, install.stderr
    origin = subprocess.run([str(python), '-I', '-c', 'import qjig; print(qjig.__file__)'], cwd=tmp_path,
                            env=clean_env, capture_output=True, text=True, timeout=10)
    assert origin.returncode == 0 and Path(origin.stdout.strip()).resolve().is_relative_to(environment.resolve())

    def cli(*args):
        return subprocess.run([str(python), '-I', '-m', 'qjig', *map(str, args)], cwd=tmp_path,
                              env=clean_env, capture_output=True, text=True, timeout=20)

    source = tmp_path / 'policy.md'
    source.write_text('# Refund limit\nRefunds are accepted within 14 days.\n', encoding='utf-8')
    db, request, policy, trace = (tmp_path / name for name in ('catalog.sqlite', 'request.json', 'policy.json', 'trace.json'))
    request.write_text(json.dumps({'schema_version': 'qjig.request.v1', 'request_id': 'clean', 'question': 'After 20 days?',
                                   'role': 'reviewer', 'role_version': '1', 'scope': 'project'}))
    policy.write_text(json.dumps({'label': 'SYNTHETIC', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot',
                                  'facts': {'days': 20}, 'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Within limit?'}], 'expression': {'ref': 'p'}},
                                  'needs': {'p': {'query': 'refund days', 'want': 2, 'max_bytes': 4000,
                                                  'evaluator': {'kind': 'numeric_threshold', 'field': 'days', 'pattern': r'within (\d+) days', 'operator': 'lte'}}}}))
    imported = cli('import', '--catalog', db, '--source-id', 'policy.md', '--file', source, '--encoding', 'utf-8',
                   '--scope', 'project', '--effective-from', '2026-01-01', '--effective-to', 'open')
    assert imported.returncode == 0, imported.stderr
    result = cli('ask', '--catalog', db, '--request', request, '--policy', policy, '--trace-out', trace)
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome['status'] == 'decided' and outcome['outcome'] is False and outcome['providers_called'] == 0
    rendered = cli('trace', '--file', trace)
    assert rendered.returncode == 0 and '14 days' in rendered.stdout

    # Exercise the installed fresh pipeline and exported archive without the
    # checkout on sys.path. All provider responses and source text are synthetic.
    fresh_script = r'''
import json, sys
from pathlib import Path
from qjig.contracts import Budget
from qjig.fresh_service import FreshWorkbench
from qjig.goal_budget import GoalBudget
from qjig.providers import RawResponse, StandInTransport
root = Path(sys.argv[1])
model = {'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
         'pricing':{'prompt':'0.000001','completion':'0.000002'}}
spec = {'provider':'stand-in','model':model,'input_tokens':1000,'output_tokens':100,
        'max_price':{'prompt':2,'completion':3}}
limit = Budget(30,100000,1)
usage = {'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.0001}
def raw(value): return RawResponse(200,json.dumps(value),usage)
responses = [raw({'predicates':[{'id':'p','question':'Refund limit?'}],'expression':{'ref':'p'}}),
             raw({'supported':True,'quote':'Refunds are accepted within 14 days.','reason':'synthetic'}),
             raw({'supported':False,'quote':'','reason':'synthetic'}),
             raw({'assessment':'uncertain','reason':'synthetic review'})]
backend = FreshWorkbench(root/'fresh',goal_factory=lambda:GoalBudget.open(root/'goal.sqlite',
    total=limit,per_request=limit,allocations={'smoke':limit}),transport_factory=lambda:StandInTransport(responses),
    partition='smoke',planner=spec,judge=spec,reviewer=spec,budget=limit)
request={'schema_version':'qjig.request.v1','request_id':'clean-fresh','question':'Refund limit?',
         'role':'reviewer','role_version':'1','scope':'project'}
result=backend.run(root/'catalog.sqlite',{'request':request,'as_of':'2026-11-15','entities':[]})
assert result['status']=='deferred' and result['review']['assurance']=='synthetic_review_unvalidated'
(root/'fresh-export.sqlite').write_bytes(backend.export(result['run_id']))
(root/'fresh-receipt.json').write_text(json.dumps(backend.receipt(result['run_id'])))
print(json.dumps({'run_id':result['run_id']}))
'''
    fresh = subprocess.run([str(python), '-I', '-c', fresh_script, str(tmp_path)], cwd=tmp_path,
                           env=clean_env, capture_output=True, text=True, timeout=20)
    assert fresh.returncode == 0, fresh.stderr
    verified = cli('verify-fresh', '--file', tmp_path / 'fresh-export.sqlite')
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)['status'] == 'unanchored'
    receipt_verified = cli('verify-fresh-receipt', '--file', tmp_path / 'fresh-receipt.json')
    assert receipt_verified.returncode == 0, receipt_verified.stderr
    assert json.loads(receipt_verified.stdout)['status'] == 'unanchored'

    service = subprocess.Popen([str(python), '-I', '-m', 'qjig', 'serve', '--catalog', str(db), '--host', '127.0.0.1', '--port', '0'],
                               cwd=tmp_path, env=clean_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(service.stdout.readline()), daemon=True).start()
        line = lines.get(timeout=15)
        assert line, 'service exited before reporting its address'
        address = json.loads(line)
        with urllib.request.urlopen(f"http://127.0.0.1:{address['port']}/", timeout=5) as response:
            assert response.status == 200 and b'qJig' in response.read()
    finally:
        service.terminate()
        service.wait(timeout=10)

    if os.environ.get('QJIG_CHROMIUM_PATH'):
        deps = subprocess.run([str(python), '-I', '-m', 'pip', 'install', 'pytest>=8', 'playwright'],
                              cwd=tmp_path, env=clean_env, capture_output=True, text=True, timeout=180)
        assert deps.returncode == 0, deps.stderr
        acceptance = tmp_path / 'installed-acceptance'
        acceptance.mkdir()
        for name in ('test_fresh_service.py', 'test_workflow_browser.py'):
            shutil.copy2(repo / 'tests' / name, acceptance / name)
        browser = subprocess.run([str(python), '-I', '-m', 'pytest', '-q',
                                  str(acceptance / 'test_workflow_browser.py::test_complete_synthetic_fresh_browser_journey')],
                                 cwd=acceptance, env=clean_env, capture_output=True, text=True, timeout=120)
        assert browser.returncode == 0 and '1 passed' in browser.stdout, browser.stdout + browser.stderr
        print('Installed browser journey: ' + browser.stdout.strip().splitlines()[-1])
        suite_root = tmp_path / 'installed-suite'
        suite_root.mkdir()
        for name in ('tests', 'scripts', 'reports'):
            shutil.copytree(repo / name, suite_root / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        suite_env = dict(clean_env)
        suite_env.pop('QJIG_VERIFY_CLEAN_INSTALL', None)
        suite = subprocess.run([str(python), '-I', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-o', 'pythonpath=.'],
                               cwd=suite_root, env=suite_env, capture_output=True, text=True, timeout=300)
        assert suite.returncode == 0, suite.stdout + suite.stderr
        print('Installed offline suite: ' + suite.stdout.strip().splitlines()[-1])
