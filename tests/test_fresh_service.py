"""Synthetic transport exercises the actual fresh pipeline through loopback HTTP."""
import json
import threading
import os
import sqlite3
import urllib.request
import subprocess
import sys
from pathlib import Path

import pytest

from qjig.agents import ClientError, RoleClient
from qjig.contracts import Budget
from qjig.goal_budget import GoalBudget
from qjig.providers import RawResponse, StandInTransport
from qjig.roles import RoleDefinition
from qjig.service import create_server


def test_configured_service_runs_fresh_pipeline_and_preserves_deferral(tmp_path):
    from qjig.fresh_service import FreshWorkbench

    model = {'id': 'synthetic/model', 'context_length': 10000,
             'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    price = {'prompt': 2, 'completion': 3}
    spec = {'provider': 'stand-in', 'model': model, 'input_tokens': 1000, 'output_tokens': 100, 'max_price': price}
    limit = Budget(30, 100000, 1)
    total = Budget(120, 400000, 4)
    goal_path = tmp_path / 'goal.sqlite'
    def goal_factory():
        return GoalBudget.open(goal_path, total=total, per_request=limit, allocations={'smoke': total})
    usage = {'prompt_tokens': 10, 'completion_tokens': 5, 'cost_usd': 0.0001}
    quote = 'Refunds are accepted within 14 days.'
    raw = lambda value: RawResponse(200, json.dumps(value), usage)
    transport = StandInTransport([raw({'predicates': [{'id': 'p', 'question': 'Refund limit?'}], 'expression': {'ref': 'p'}}),
                                  raw({'supported': True, 'quote': quote, 'reason': 'fixture'}),
                                  raw({'supported': False, 'quote': '', 'reason': 'fixture'}),
                                  raw({'assessment': 'uncertain', 'reason': 'fixture review'})])
    backend = FreshWorkbench(tmp_path / 'fresh', goal_factory=goal_factory, transport_factory=lambda: transport,
                             partition='smoke', planner=spec, judge=spec, reviewer=spec, budget=limit)
    server = create_server(tmp_path / 'catalog.sqlite', host='127.0.0.1', port=0, fresh_backend=backend)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        imported = client.import_source({'source_id': 'policy.md', 'text': '# Policy\n'+quote+'\n', 'scope': 'project',
                              'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open',
                              'observed_at': None, 'authority': None})
        result = client.ask_fresh('fresh-1', 'Refund limit?', 'project', as_of='2026-11-15', entities=[])
        assert result['kind'] == 'fresh' and result['status'] == 'deferred' and result['answer'] is None
        assert result['conditional_outcome'] == 'true' and 'plan_coverage_unestablished' in result['reasons']
        assert result['review']['status'] == 'recorded' and result['review']['assurance'] == 'synthetic_unvalidated'
        assert any(quote in item['text'] for record in result['records'] for item in record['evidence'])
        assert transport.calls_made == 4
        assert (tmp_path / 'fresh' / 'journal.sqlite').is_file()
        assert (tmp_path / 'fresh' / 'runs' / result['run_id'] / 'run.sqlite').is_file()
        builder_transport = StandInTransport([raw({'predicates': [{'id': 'p', 'question': 'Refund limit?'}], 'expression': {'ref': 'p'}}),
            raw({'supported': True, 'quote': quote, 'reason': 'fixture'}),
            raw({'supported': False, 'quote': '', 'reason': 'fixture'}),
            raw({'assessment': 'uncertain', 'reason': 'fixture review'})])
        backend.transport_factory = lambda: builder_transport
        builder = RoleClient(server.server_address[1], RoleDefinition('builder', '2', 'Build'))
        builder_result = builder.ask_fresh('fresh-2', 'Refund limit?', 'project', as_of='2026-11-15', entities=[])
        builder_replay = client.get_fresh_run(builder_result['run_id'])
        assert (builder_replay['request']['role'], builder_replay['request']['role_version']) == ('builder', '2')
        assert builder_result['records'][0]['evidence'][0]['revision_id'] == result['records'][0]['evidence'][0]['revision_id']
        assert builder_result['status'] == 'deferred' and builder_transport.calls_made == 4
        reviews = client._request('GET', '/api/reviews')['reviews']
        assert {(record['role'], record['role_version']) for record in reviews} == {('reviewer', '1'), ('builder', '2')}
        assert all(record['reviewer_kind'] == 'synthetic' for record in reviews)
        if os.environ.get('QJIG_CHROMIUM_PATH'):
            playwright = pytest.importorskip('playwright.sync_api')
            browser_transport = StandInTransport([raw({'predicates': [{'id': 'p', 'question': 'Refund limit?'}], 'expression': {'ref': 'p'}}),
                raw({'supported': True, 'quote': quote, 'reason': 'fixture'}),
                raw({'supported': False, 'quote': '', 'reason': 'fixture'}),
                raw({'assessment': 'uncertain', 'reason': 'fixture review'})])
            backend.transport_factory = lambda: browser_transport
            with playwright.sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ['QJIG_CHROMIUM_PATH'])
                try:
                    page = browser.new_page()
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    form = page.locator('#fresh-form')
                    form.locator('[name=question]').fill('Refund limit?')
                    form.locator('[name=scope]').fill('project')
                    form.locator('[name=as_of]').fill('2026-11-15')
                    form.get_by_role('button', name='Run fresh planning').click()
                    page.get_by_text('Deferred · coverage remains unestablished').wait_for()
                    assert 'Conditional outcome: true' in page.locator('#fresh-result').inner_text()
                    assert 'synthetic_unvalidated' in page.locator('#fresh-result').inner_text()
                    assert quote in page.locator('#fresh-result').inner_text()
                    assert browser_transport.calls_made == 4
                    page.route('**/api/catalog-state', lambda route: route.fulfill(status=503, json={'error': 'unavailable'}))
                    page.get_by_text('Fresh run source status is unknown; reconnect and check the catalog.').wait_for(timeout=7000)
                    page.unroute('**/api/catalog-state')
                    page.get_by_text('Fresh run source status is unknown; reconnect and check the catalog.').wait_for(state='hidden', timeout=7000)
                    source = builder.get_source(imported['revision_id'])
                    offset = source['text'].index('14')
                    change = builder.intervene(imported['revision_id'], source['text_sha256'], offset, offset + 2, '30')
                    assert change['role_id'] == 'builder' and change['parent_revision_id'] == imported['revision_id']
                    page.get_by_text('Sources changed since this fresh run. Rerun to inspect the current revision.').wait_for(timeout=7000)
                    updated_quote = 'Refunds are accepted within 30 days.'
                    rerun_transport = StandInTransport([raw({'predicates': [{'id': 'p', 'question': 'Refund limit?'}], 'expression': {'ref': 'p'}}),
                        raw({'supported': True, 'quote': updated_quote, 'reason': 'fixture'}),
                        raw({'supported': False, 'quote': '', 'reason': 'fixture'}),
                        raw({'assessment': 'uncertain', 'reason': 'fixture review'})])
                    backend.transport_factory = lambda: rerun_transport
                    prior_runs = {item['run_id'] for item in client.list_fresh_runs()}
                    form.get_by_role('button', name='Run fresh planning').click()
                    page.locator('#fresh-result').get_by_text(updated_quote).wait_for(timeout=7000)
                    assert quote not in page.locator('#fresh-result').inner_text()
                    assert page.locator('#fresh-source-change').count() == 0
                    assert 'Deferred' in page.locator('#fresh-message').inner_text()
                    assert rerun_transport.calls_made == 4
                    new_runs = {item['run_id'] for item in client.list_fresh_runs()} - prior_runs
                    assert len(new_runs) == 1
                    changed_replay = client.get_fresh_run(new_runs.pop())
                    assert any(item['revision_id'] == change['child_revision_id'] and updated_quote in item['text']
                               for trace in changed_replay['traces'] for item in trace['evidence'])
                finally:
                    browser.close()
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        server = create_server(tmp_path / 'catalog.sqlite', host='127.0.0.1', port=0, fresh_backend=backend)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        saved = client.list_fresh_runs()
        assert any(item['run_id'] == result['run_id'] and item['question'] == 'Refund limit?' for item in saved)
        replay = client.get_fresh_run(result['run_id'])
        assert replay['verification']['status'] == 'unanchored'
        assert replay['verification']['semantic_assurance'] == 'not_assessed'
        assert replay['request']['question'] == 'Refund limit?'
        assert replay['request']['role'] == 'reviewer' and replay['request']['role_version'] == '1'
        assert replay['result']['status'] == 'deferred'
        assert any(quote in item['text'] for trace in replay['traces'] for item in trace['evidence'])
        assert transport.calls_made == 4
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_address[1]}/api/fresh-runs/{result["run_id"]}/export') as response:
            exported = response.read()
            assert response.headers.get_content_type() == 'application/vnd.sqlite3'
        path = tmp_path / 'export.sqlite'; path.write_bytes(exported)
        from qjig.run_archive import RunArchive
        from qjig.replay import verify_archive
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        command = [sys.executable, '-m', 'qjig', 'verify-fresh', '--file', str(path)]
        checked = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
        assert checked.returncode == 0, checked.stderr
        assert json.loads(checked.stdout)['status'] == 'unanchored'
        anchored = subprocess.run(command + ['--expected-digest', replay['verification']['digest']],
                                  env=env, capture_output=True, text=True, timeout=10)
        assert anchored.returncode == 0 and json.loads(anchored.stdout)['status'] == 'structurally_verified'
        mismatch = subprocess.run(command + ['--expected-digest', '0' * 64],
                                  env=env, capture_output=True, text=True, timeout=10)
        assert mismatch.returncode != 0 and json.loads(mismatch.stdout)['status'] == 'invalid'
        with sqlite3.connect(path) as con:
            report = verify_archive(RunArchive(con))
            assert report.status == 'unanchored' and report.digest == replay['verification']['digest']
            con.execute('DROP TRIGGER event_no_update')
            con.execute("UPDATE events SET data='{}' WHERE kind='run_result'")
            assert verify_archive(RunArchive(con)).status == 'invalid'
        checked = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
        assert checked.returncode != 0 and json.loads(checked.stdout)['status'] == 'invalid'
        assert transport.calls_made == 4
        if os.environ.get('QJIG_CHROMIUM_PATH'):
            with playwright.sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ['QJIG_CHROMIUM_PATH'])
                try:
                    page = browser.new_page()
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    original_index = [item['run_id'] for item in client.list_fresh_runs() if item['question']].index(result['run_id'])
                    page.locator('#fresh-runs').get_by_role('button', name='Refund limit?', exact=False).nth(original_index).click()
                    page.get_by_text('Saved fresh run · unanchored structural replay').wait_for()
                    assert quote in page.locator('#fresh-replay').inner_text()
                    assert 'Decision correctness not assessed' in page.locator('#fresh-replay').inner_text()
                    with page.expect_download() as info:
                        page.get_by_role('link', name='Download fresh archive').click()
                    assert info.value.suggested_filename.endswith('.sqlite')
                    download_path = tmp_path / 'browser-export.sqlite'
                    info.value.save_as(download_path)
                    with sqlite3.connect(download_path) as con:
                        assert verify_archive(RunArchive(con)).status == 'unanchored'
                finally:
                    browser.close()
        with sqlite3.connect(tmp_path / 'fresh' / 'runs' / result['run_id'] / 'run.sqlite') as con:
            con.execute('DROP TRIGGER event_no_update')
            con.execute("UPDATE events SET data='{}' WHERE kind='run_result'")
        with pytest.raises(ClientError, match='409'):
            client._request('GET', '/api/fresh-runs/' + result['run_id'])
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f'http://127.0.0.1:{server.server_address[1]}/api/fresh-runs/{result["run_id"]}/export')
        assert exc.value.code == 409
        saved = client._request('GET', '/api/fresh-runs')
        assert any(item['run_id'] == result['run_id'] and item['replay_status'] == 'unavailable_or_invalid'
                   for item in saved['runs'])
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_browser_reports_unconfigured_fresh_backend(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    executable = os.environ.get('QJIG_CHROMIUM_PATH')
    if not executable:
        pytest.skip('QJIG_CHROMIUM_PATH is required for browser verification')
    server = create_server(tmp_path / 'catalog.sqlite', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=executable)
            try:
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                form = page.locator('#fresh-form')
                form.locator('[name=question]').fill('What applies?')
                form.locator('[name=scope]').fill('project')
                form.locator('[name=as_of]').fill('2026-11-15')
                form.get_by_role('button', name='Run fresh planning').click()
                page.get_by_text('Fresh planning unavailable: fresh planning is not configured').wait_for()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_interrupted_fresh_run_exposes_pending_attempt_after_restart(tmp_path):
    from qjig.contracts import ContractError
    from qjig.fresh_service import FreshWorkbench

    model = {'id': 'synthetic/model', 'context_length': 10000,
             'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    spec = {'provider': 'stand-in', 'model': model, 'input_tokens': 1000, 'output_tokens': 100,
            'max_price': {'prompt': 2, 'completion': 3}}
    limit, total = Budget(30, 100000, 1), Budget(60, 200000, 2)
    transport = StandInTransport([KeyboardInterrupt()])
    backend = FreshWorkbench(tmp_path / 'fresh', goal_factory=lambda: GoalBudget.open(tmp_path / 'goal.sqlite',
        total=total, per_request=limit, allocations={'smoke': total}), transport_factory=lambda: transport,
        partition='smoke', planner=spec, judge=spec, reviewer=spec, budget=limit)
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, port=0, fresh_backend=backend)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        client.import_source({'source_id':'policy.md','text':'# Policy\nRefunds within 14 days.\n','scope':'project',
                              'entities':[],'effective_from':'2026-01-01','effective_to':'open',
                              'observed_at':None,'authority':None})
        request = {'schema_version':'qjig.request.v1','request_id':'interrupted','question':'Refund limit?',
                   'role':'reviewer','role_version':'1','scope':'project'}
        body = {'request':request,'as_of':'2026-11-15','entities':[]}
        with pytest.raises(KeyboardInterrupt):
            backend.run(path, body)
        assert transport.calls_made == 1
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        server = create_server(path, port=0, fresh_backend=backend)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        run_id = client.list_fresh_runs()[0]['run_id']
        replay = client.get_fresh_run(run_id)
        assert replay['verification']['status'] == 'incomplete'
        assert replay['reconciliation']['status'] == 'required'
        assert replay['reconciliation']['unresolved'][0]['stage'] == 'planner'
        with pytest.raises(ContractError): backend.run(path, body)
        assert transport.calls_made == 1
        if os.environ.get('QJIG_CHROMIUM_PATH'):
            playwright = pytest.importorskip('playwright.sync_api')
            with playwright.sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ['QJIG_CHROMIUM_PATH'])
                try:
                    page = browser.new_page(); page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    page.locator('#fresh-runs').get_by_role('button', name='Refund limit?', exact=False).click()
                    page.get_by_text('Provider outcome unknown; reconciliation is required before retry.').wait_for()
                finally:
                    browser.close()
        journal = tmp_path / 'fresh' / 'journal.sqlite'
        moved = tmp_path / 'fresh' / 'journal-held.sqlite'
        journal.rename(moved)
        try:
            assert client.get_fresh_run(run_id)['reconciliation']['status'] == 'unknown'
        finally:
            moved.rename(journal)
        second = {'request': {**request, 'request_id': 'after-interruption'}, 'as_of':'2026-11-15', 'entities':[]}
        followup = backend.run(path, second)
        assert followup['status'] == 'deferred' and followup['plan_failure'] == 'reconciliation_required'
        assert transport.calls_made == 1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
