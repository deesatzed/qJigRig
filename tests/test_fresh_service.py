"""Synthetic transport exercises the actual fresh pipeline through loopback HTTP."""
import json
import threading
import os
import sqlite3
import urllib.request

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
    total = Budget(60, 200000, 2)
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
        client.import_source({'source_id': 'policy.md', 'text': '# Policy\n'+quote+'\n', 'scope': 'project',
                              'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open',
                              'observed_at': None, 'authority': None})
        request = {'schema_version': 'qjig.request.v1', 'request_id': 'fresh-1', 'question': 'Refund limit?',
                   'role': 'reviewer', 'role_version': '1', 'scope': 'project'}
        result = client._request('POST', '/api/fresh', {'request': request, 'as_of': '2026-11-15', 'entities': []})
        assert result['kind'] == 'fresh' and result['status'] == 'deferred' and result['answer'] is None
        assert result['conditional_outcome'] == 'true' and 'plan_coverage_unestablished' in result['reasons']
        assert result['review']['status'] == 'recorded' and result['review']['assurance'] == 'synthetic_unvalidated'
        assert any(quote in item['text'] for record in result['records'] for item in record['evidence'])
        assert transport.calls_made == 4
        assert (tmp_path / 'fresh' / 'journal.sqlite').is_file()
        assert (tmp_path / 'fresh' / 'runs' / result['run_id'] / 'run.sqlite').is_file()
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
                    client.import_source({'source_id': 'policy.md', 'text': '# Policy\nRefunds are accepted within 30 days.\n',
                        'scope': 'project', 'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open',
                        'observed_at': None, 'authority': None})
                    page.get_by_text('Sources changed since this fresh run. Rerun to inspect the current revision.').wait_for(timeout=7000)
                finally:
                    browser.close()
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        server = create_server(tmp_path / 'catalog.sqlite', host='127.0.0.1', port=0, fresh_backend=backend)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        saved = client._request('GET', '/api/fresh-runs')
        assert any(item['run_id'] == result['run_id'] and item['question'] == 'Refund limit?' for item in saved['runs'])
        replay = client._request('GET', '/api/fresh-runs/' + result['run_id'])
        assert replay['verification']['status'] == 'unanchored'
        assert replay['verification']['semantic_assurance'] == 'not_assessed'
        assert replay['request']['question'] == 'Refund limit?'
        assert replay['result']['status'] == 'deferred'
        assert any(quote in item['text'] for trace in replay['traces'] for item in trace['evidence'])
        assert transport.calls_made == 4
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_address[1]}/api/fresh-runs/{result["run_id"]}/export') as response:
            exported = response.read()
            assert response.headers.get_content_type() == 'application/vnd.sqlite3'
        path = tmp_path / 'export.sqlite'; path.write_bytes(exported)
        from qjig.run_archive import RunArchive
        from qjig.replay import verify_archive
        with sqlite3.connect(path) as con:
            report = verify_archive(RunArchive(con))
            assert report.status == 'unanchored' and report.digest == replay['verification']['digest']
            con.execute('DROP TRIGGER event_no_update')
            con.execute("UPDATE events SET data='{}' WHERE kind='run_result'")
            assert verify_archive(RunArchive(con)).status == 'invalid'
        assert transport.calls_made == 4
        if os.environ.get('QJIG_CHROMIUM_PATH'):
            with playwright.sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ['QJIG_CHROMIUM_PATH'])
                try:
                    page = browser.new_page()
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    page.locator('#fresh-runs').get_by_role('button', name='Refund limit?', exact=False).first.click()
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
