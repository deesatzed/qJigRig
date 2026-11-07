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
