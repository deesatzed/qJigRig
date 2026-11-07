"""Synthetic transport exercises the actual fresh pipeline through loopback HTTP."""
import json
import hashlib
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
        imported = client.import_source({'source_id': 'policy.md', 'text': '# Policy\n'+quote+'\nContact support for help.\n', 'scope': 'project',
                              'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open',
                              'observed_at': None, 'authority': None})
        result = client.ask_fresh('fresh-1', 'Refund limit?', 'project', as_of='2026-11-15', entities=[])
        assert result['kind'] == 'fresh' and result['status'] == 'deferred' and result['answer'] is None
        assert result['plan']['origin'] == 'fresh' and result['plan']['expression'] == {'ref':'p'}
        assert result['plan']['predicates'][0]['question'] == 'Refund limit?'
        assert result['conditional_outcome'] == 'true' and 'plan_coverage_unestablished' in result['reasons']
        assert result['review']['status'] == 'recorded' and result['review']['assurance'] == 'synthetic_review_unvalidated'
        assert result['review']['assessment'] == 'uncertain' and result['review']['reason'] == 'fixture review'
        assert result['review']['review_id']
        judgment = result['records'][0]['judgment']
        assert judgment['positive']['support'] == 'supported'
        assert judgment['positive']['quote'] == quote
        assert judgment['positive']['quote_ref']['revision_id'] == imported['revision_id']
        assert judgment['negative']['support'] == 'unknown' and judgment['negative']['quote'] is None
        assert any('Contact support for help.' in item['text'] for item in result['records'][0]['evidence'])
        assert 'Contact support' not in judgment['positive']['quote']
        assert 'exception' in result['records'][0]['channels']['missing']
        assert 'ob-plan-coverage' in result['blocking_obligations']
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
                    assert 'synthetic_review_unvalidated' in page.locator('#fresh-result').inner_text()
                    assert 'fixture review' in page.locator('#fresh-result').inner_text()
                    assert 'Model-generated plan' in page.locator('#fresh-result').inner_text()
                    assert 'Refund limit?' in page.locator('#fresh-result').inner_text()
                    assert 'Model-cited passage' in page.locator('#fresh-result').inner_text()
                    assert 'Retrieved passages' in page.locator('#fresh-result').inner_text()
                    assert 'No retrieved hits for:' in page.locator('#fresh-result').inner_text()
                    assert 'exception' in page.locator('#fresh-result').inner_text()
                    assert 'A missing hit does not establish absence.' in page.locator('#fresh-result').inner_text()
                    assert 'Material obligations remain open: ob-plan-coverage' in page.locator('#fresh-result').inner_text()
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
                    page.locator('#fresh-result').get_by_text(updated_quote).first.wait_for(timeout=7000)
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
        assert replay['plan'] == result['plan']
        assert 'ob-plan-coverage' in replay['result']['blocking_obligations']
        assert replay['review']['review_id'] == result['review']['review_id']
        assert replay['review']['assessment'] == 'uncertain' and replay['review']['reason'] == 'fixture review'
        assert replay['resources']['status'] == 'recorded_unverified'
        assert replay['resources']['calls'] == 4 and replay['resources']['cost_status'] == 'known'
        assert replay['resources']['known_cost_usd'] == 0.0004
        assert replay['traces'][0]['judgment']['positive']['quote'] == quote
        assert replay['traces'][0]['judgment']['positive']['quote_ref']['revision_id'] == imported['revision_id']
        assert replay['traces'][0]['judgment']['negative']['quote'] is None
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
            judgments = {'stale': 'must be cleared'}
            plan_output = {'stale': 'must be cleared'}
            assert verify_archive(RunArchive(con), judgments_out=judgments, plan_out=plan_output).status == 'invalid'
            assert judgments == {} and plan_output == {}
        checked = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
        assert checked.returncode != 0 and json.loads(checked.stdout)['status'] == 'invalid'
        assert transport.calls_made == 4
        receipt = client._request('GET', '/api/fresh-runs/' + result['run_id'] + '/receipt')
        assert {event['request_id'] for event in receipt['payload']['journal']} == {'fresh-1'}
        from qjig.fresh_receipt import verify_fresh_receipt
        checked_receipt = verify_fresh_receipt(receipt)
        assert checked_receipt['status'] == 'unanchored'
        assert verify_fresh_receipt(receipt, expected_digest=receipt['sha256'])['status'] == 'structurally_verified'
        assert verify_fresh_receipt(receipt, expected_digest='0' * 64)['status'] == 'invalid'
        assert checked_receipt['resources']['calls'] == 4
        assert checked_receipt['resources']['reserved_tokens'] == 4400
        assert checked_receipt['resources']['actual_input_tokens'] == 40
        assert checked_receipt['resources']['actual_output_tokens'] == 20
        assert checked_receipt['resources']['reserved_cost_usd'] == 0.014
        assert checked_receipt['resources']['cost_status'] == 'known'
        assert checked_receipt['resources']['known_cost_usd'] == 0.0004
        receipt_path = tmp_path / 'fresh-receipt.json'
        receipt_path.write_text(json.dumps(receipt))
        receipt_command = [sys.executable, '-m', 'qjig', 'verify-fresh-receipt', '--file', str(receipt_path)]
        receipt_check = subprocess.run(receipt_command, env=env, capture_output=True, text=True, timeout=10)
        assert receipt_check.returncode == 0 and json.loads(receipt_check.stdout)['status'] == 'unanchored'
        altered = json.loads(json.dumps(receipt))
        altered['payload']['journal'][0]['stage'] = 'other'
        assert verify_fresh_receipt(altered)['status'] == 'invalid'
        altered = json.loads(json.dumps(receipt))
        intent = next(event for event in altered['payload']['journal'] if event['kind'] == 'intent')
        intent['payload']['reserve_cost_usd'] = 0.0001  # covers actual usage, but not the declared routing ceiling
        canonical = json.dumps(altered['payload'], sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
        altered['sha256'] = hashlib.sha256(canonical).hexdigest()
        assert verify_fresh_receipt(altered)['status'] == 'invalid'
        altered = json.loads(json.dumps(receipt))
        terminal = next(event for event in altered['payload']['journal'] if event['kind'] == 'receipt')
        terminal['payload']['usage']['cost_usd'] = 0
        canonical = json.dumps(altered['payload'], sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
        altered['sha256'] = hashlib.sha256(canonical).hexdigest()
        assert verify_fresh_receipt(altered)['status'] == 'invalid'
        altered = json.loads(json.dumps(receipt))
        altered['payload']['journal'] = []
        canonical = json.dumps(altered['payload'], sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
        altered['sha256'] = hashlib.sha256(canonical).hexdigest()
        missing_journal = verify_fresh_receipt(altered)
        assert missing_journal['status'] == 'incomplete' and missing_journal['resources']['calls'] is None
        assert missing_journal['resources']['cost_status'] == 'unknown'
        altered = json.loads(json.dumps(receipt))
        intent = next(event for event in altered['payload']['journal'] if event['kind'] == 'intent')
        intent['payload']['reserve_output_tokens'] += 1
        canonical = json.dumps(altered['payload'], sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
        altered['sha256'] = hashlib.sha256(canonical).hexdigest()
        assert verify_fresh_receipt(altered)['status'] == 'invalid'
        altered = json.loads(json.dumps(receipt))
        intent = next(event for event in altered['payload']['journal'] if event['kind'] == 'intent')
        intent['payload']['reserve_input_tokens'] = 0
        intent['payload']['reserve_tokens'] = intent['payload']['reserve_output_tokens']
        canonical = json.dumps(altered['payload'], sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
        altered['sha256'] = hashlib.sha256(canonical).hexdigest()
        assert verify_fresh_receipt(altered)['status'] == 'invalid'
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
                    assert 'fixture review' in page.locator('#fresh-replay').inner_text()
                    assert 'Model-generated plan' in page.locator('#fresh-replay').inner_text()
                    assert 'Recorded calls: 4' in page.locator('#fresh-replay').inner_text()
                    assert 'Model-cited passage' in page.locator('#fresh-replay').inner_text()
                    assert 'No retrieved hits for:' in page.locator('#fresh-replay').inner_text()
                    assert 'exception' in page.locator('#fresh-replay').inner_text()
                    assert 'Material obligations remain open: ob-plan-coverage' in page.locator('#fresh-replay').inner_text()
                    with page.expect_download() as info:
                        page.get_by_role('link', name='Download fresh archive').click()
                    assert info.value.suggested_filename.endswith('.sqlite')
                    download_path = tmp_path / 'browser-export.sqlite'
                    info.value.save_as(download_path)
                    with sqlite3.connect(download_path) as con:
                        assert verify_archive(RunArchive(con)).status == 'unanchored'
                    with page.expect_download() as info:
                        page.get_by_role('link', name='Download fresh receipt').click()
                    receipt_download = tmp_path / 'browser-receipt.json'
                    info.value.save_as(receipt_download)
                    assert verify_fresh_receipt(json.loads(receipt_download.read_text()))['status'] == 'unanchored'
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
        from qjig.fresh_receipt import verify_fresh_receipt
        partial_receipt = client._request('GET', '/api/fresh-runs/' + run_id + '/receipt')
        partial_check = verify_fresh_receipt(partial_receipt)
        assert partial_check['status'] == 'incomplete' and partial_check['resources']['cost_status'] == 'unknown'
        assert partial_check['resources']['reserved_tokens'] == 1100
        assert partial_check['resources']['actual_input_tokens'] is None
        assert replay['review'] is None
        assert replay['reconciliation']['status'] == 'required'
        with pytest.raises(ClientError):
            client.check_fresh_cases(run_id, [{'case_id':'unavailable','assignments':{},'expected':'true'}])
        assert replay['reconciliation']['unresolved'][0]['stage'] == 'planner'
        assert replay['resources']['calls'] == 1 and replay['resources']['cost_status'] == 'unknown'
        assert replay['resources']['known_cost_usd'] is None
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
            missing = client.get_fresh_run(run_id)
            assert missing['reconciliation']['status'] == 'unknown' and missing['resources']['status'] == 'unknown'
        finally:
            moved.rename(journal)
        second = {'request': {**request, 'request_id': 'after-interruption'}, 'as_of':'2026-11-15', 'entities':[]}
        followup = backend.run(path, second)
        assert followup['status'] == 'deferred' and followup['plan_failure'] == 'reconciliation_required'
        assert followup['review']['status'] == 'unavailable' and followup['review']['assurance'] == 'not_assessed'
        assert followup['review']['assessment'] is None and followup['review']['review_id'] is None
        assert transport.calls_made == 1
        if os.environ.get('QJIG_CHROMIUM_PATH'):
            with playwright.sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ['QJIG_CHROMIUM_PATH'])
                try:
                    page = browser.new_page(); page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    index = [item['run_id'] for item in client.list_fresh_runs() if item['question']].index(followup['run_id'])
                    page.locator('#fresh-runs').get_by_role('button', name='Refund limit?', exact=False).nth(index).click()
                    page.get_by_text('Planning unavailable: reconciliation_required').wait_for(timeout=5000)
                finally:
                    browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_failed_fresh_review_is_not_labeled_reviewed(tmp_path):
    from qjig.fresh_service import FreshWorkbench
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    spec={'provider':'stand-in','model':model,'input_tokens':1000,'output_tokens':100,
          'max_price':{'prompt':2,'completion':3}}
    limit=Budget(30,100000,1)
    usage={'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.0001}
    raw=lambda value: RawResponse(200,json.dumps(value),usage)
    transport=StandInTransport([raw({'predicates':[{'id':'p','question':'Refund limit?'}],'expression':{'ref':'p'}}),
        raw({'supported':True,'quote':'Refunds within 14 days.','reason':'fixture'}),
        raw({'supported':False,'quote':'','reason':'fixture'}),
        RawResponse(200,'not json',usage)])
    backend=FreshWorkbench(tmp_path/'fresh',goal_factory=lambda:GoalBudget.open(tmp_path/'goal.sqlite',
        total=limit,per_request=limit,allocations={'smoke':limit}),transport_factory=lambda:transport,
        partition='smoke',planner=spec,judge=spec,reviewer=spec,budget=limit)
    server=create_server(tmp_path/'catalog.sqlite',port=0,fresh_backend=backend)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        client=RoleClient(server.server_address[1],RoleDefinition('reviewer','1','Review'))
        client.import_source({'source_id':'policy.md','text':'# Policy\nRefunds within 14 days.\n','scope':'project',
            'entities':[],'effective_from':'2026-01-01','effective_to':'open','observed_at':None,'authority':None})
        result=client.ask_fresh('failed-review','Refund limit?','project',as_of='2026-11-15',entities=[])
        assert result['status']=='deferred' and result['review']['status']=='unavailable'
        assert result['review']['assurance']=='not_assessed' and result['review']['review_id'] is None
        assert result['review']['assessment'] is None and result['review']['failure']=='malformed_output'
        replay = client.get_fresh_run(result['run_id'])
        assert replay['verification']['status'] == 'incomplete'
        assert all(trace['judgment'] is None for trace in replay['traces'])
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_mandatory_only_exception_reaches_service_and_replays(tmp_path):
    from qjig.fresh_service import FreshWorkbench
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    spec={'provider':'stand-in','model':model,'input_tokens':1000,'output_tokens':100,
          'max_price':{'prompt':2,'completion':3}}
    limit=Budget(30,100000,1)
    usage={'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.0001}
    raw=lambda value: RawResponse(200,json.dumps(value),usage)
    quote='Special case: veterans are eligible.'
    transport=StandInTransport([
        raw({'predicates':[{'id':'p1','question':'Does a former soldier satisfy this condition?'}],'expression':{'ref':'p1'}}),
        raw({'supported':True,'quote':quote,'reason':'synthetic'}),
        raw({'supported':False,'quote':'','reason':'synthetic'}),
        raw({'assessment':'uncertain','reason':'synthetic review'})])
    backend=FreshWorkbench(tmp_path/'fresh',goal_factory=lambda:GoalBudget.open(tmp_path/'goal.sqlite',
        total=limit,per_request=limit,allocations={'smoke':limit}),transport_factory=lambda:transport,
        partition='smoke',planner=spec,judge=spec,reviewer=spec,budget=limit)
    server=create_server(tmp_path/'catalog.sqlite',port=0,fresh_backend=backend)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        client=RoleClient(server.server_address[1],RoleDefinition('reviewer','1','Review'))
        source=client.import_source({'source_id':'exception.md','text':'# Exceptions\n'+quote+'\n',
            'scope':'project','entities':[],'effective_from':'2026-01-01','effective_to':'open',
            'observed_at':None,'authority':None})
        result=client.ask_fresh('exception-only','Does a military member qualify?','project',
                                as_of='2026-11-15',entities=[])
        assert result['status']=='deferred' and result['answer'] is None
        assert result['conditional_outcome']=='true' and 'ob-plan-coverage' in result['blocking_obligations']
        assert len(result['records'])==2 and result['records'][0]['reason']=='no_retrieval_hit'
        assert result['records'][0]['judgment'] is None
        final=result['records'][1]
        assert final['channels']['hits']['primary']==0 and 'exception' in final['channels']['delivered']
        assert final['judgment']['positive']['quote']==quote
        assert final['judgment']['positive']['quote_ref']['revision_id']==source['revision_id']
        assert result['review']['assurance']=='synthetic_review_unvalidated' and transport.calls_made==4
        replay=client.get_fresh_run(result['run_id'])
        assert replay['verification']['status']=='unanchored'
        assert replay['traces'][0]['judgment'] is None
        assert replay['traces'][1]['judgment']['positive']['quote']==quote
        from qjig.fresh_receipt import verify_fresh_receipt
        receipt=client._request('GET','/api/fresh-runs/'+result['run_id']+'/receipt')
        verified=verify_fresh_receipt(receipt)
        assert verified['status']=='unanchored' and verified['resources']['calls']==4
        if os.environ.get('QJIG_CHROMIUM_PATH'):
            playwright=pytest.importorskip('playwright.sync_api')
            with playwright.sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=os.environ['QJIG_CHROMIUM_PATH'])
                try:
                    page=browser.new_page(); page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    page.locator('#fresh-runs').get_by_role('button',name='Does a military member qualify?',exact=False).click()
                    area=page.locator('#fresh-replay')
                    area.get_by_text('Model-cited passage',exact=False).wait_for()
                    assert quote in area.inner_text() and 'A missing hit does not establish absence.' in area.inner_text()
                    assert 'Material obligations remain open:' in area.inner_text()
                    assert 'ob-plan-coverage' in area.inner_text()
                finally:
                    browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_mandatory_only_contradiction_remains_conflict_in_service_and_replay(tmp_path):
    from qjig.fresh_service import FreshWorkbench
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    spec={'provider':'stand-in','model':model,'input_tokens':1000,'output_tokens':100,
          'max_price':{'prompt':2,'completion':3}}
    limit=Budget(30,100000,1); usage={'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.0001}
    raw=lambda value: RawResponse(200,json.dumps(value),usage)
    positive='Veterans are eligible.'; negative='Veterans are not eligible.'
    transport=StandInTransport([
        raw({'predicates':[{'id':'p1','question':'Does a former soldier satisfy this condition?'}],'expression':{'ref':'p1'}}),
        raw({'supported':True,'quote':positive,'reason':'synthetic'}),
        raw({'supported':True,'quote':negative,'reason':'synthetic'}),
        raw({'assessment':'uncertain','reason':'synthetic review'})])
    backend=FreshWorkbench(tmp_path/'fresh',goal_factory=lambda:GoalBudget.open(tmp_path/'goal.sqlite',
        total=limit,per_request=limit,allocations={'smoke':limit}),transport_factory=lambda:transport,
        partition='smoke',planner=spec,judge=spec,reviewer=spec,budget=limit)
    server=create_server(tmp_path/'catalog.sqlite',port=0,fresh_backend=backend)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        client=RoleClient(server.server_address[1],RoleDefinition('reviewer','1','Review'))
        client.import_source({'source_id':'conflict.md','text':'# Contradiction\n'+positive+' '+negative+'\n',
            'scope':'project','entities':[],'effective_from':'2026-01-01','effective_to':'open',
            'observed_at':None,'authority':None})
        result=client.ask_fresh('contradiction-only','Does a military member qualify?','project',
                                as_of='2026-11-15',entities=[])
        assert result['status']=='deferred' and result['answer'] is None
        assert result['conditional_outcome']=='conflict' and 'ob-plan-coverage' in result['blocking_obligations']
        assert len(result['records'])==2 and result['records'][0]['reason']=='no_retrieval_hit'
        final=result['records'][1]
        assert final['channels']['hits']['primary']==0 and 'contradiction' in final['channels']['delivered']
        assert final['outcome']=='conflict' and final['judgment']['positive']['quote']==positive
        assert final['judgment']['negative']['quote']==negative and transport.calls_made==4
        replay=client.get_fresh_run(result['run_id'])
        assert replay['verification']['status']=='unanchored'
        assert replay['traces'][1]['observation']['outcome']=='conflict'
        assert replay['traces'][1]['judgment']['positive']['quote']==positive
        assert replay['traces'][1]['judgment']['negative']['quote']==negative
        from qjig.fresh_receipt import verify_fresh_receipt
        receipt=client._request('GET','/api/fresh-runs/'+result['run_id']+'/receipt')
        assert verify_fresh_receipt(receipt)['status']=='unanchored'
        if os.environ.get('QJIG_CHROMIUM_PATH'):
            playwright=pytest.importorskip('playwright.sync_api')
            with playwright.sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=os.environ['QJIG_CHROMIUM_PATH'])
                try:
                    page=browser.new_page(); page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    page.locator('#fresh-runs').get_by_role('button',name='Does a military member qualify?',exact=False).click()
                    area=page.locator('#fresh-replay')
                    area.get_by_text('p1: conflict').wait_for()
                    assert positive in area.inner_text() and negative in area.inner_text()
                    assert 'Material obligations remain open:' in area.inner_text()
                    assert 'ob-plan-coverage' in area.inner_text()
                finally:
                    browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_fresh_enabling_graph_is_visible_and_replayed(tmp_path):
    from qjig.fresh_service import FreshWorkbench
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    spec={'provider':'stand-in','model':model,'input_tokens':1000,'output_tokens':100,
          'max_price':{'prompt':2,'completion':3}}
    limit=Budget(30,100000,1); usage={'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.0001}
    raw=lambda value: RawResponse(200,json.dumps(value),usage)
    graph={'op':'and','args':[{'ref':'eligible'},{'op':'or','args':[{'ref':'ordinary'},{'ref':'exception'}]}]}
    plan={'predicates':[{'id':'eligible','question':'Is the customer a member?'},
                        {'id':'ordinary','question':'Does the ordinary limit cover twenty days?'},
                        {'id':'exception','question':'Does the exception cover twenty days?'}], 'expression':graph}
    positive=lambda quote: raw({'supported':True,'quote':quote,'reason':'synthetic'})
    unknown=raw({'supported':False,'quote':'','reason':'synthetic'})
    transport=StandInTransport([raw(plan),positive('The customer is a member.'),unknown,
        unknown,positive('Ordinary returns end after 14 days.'),
        positive('An exception permits returns for 30 days.'),unknown,
        raw({'assessment':'uncertain','reason':'synthetic review'})])
    backend=FreshWorkbench(tmp_path/'fresh',goal_factory=lambda:GoalBudget.open(tmp_path/'goal.sqlite',
        total=limit,per_request=limit,allocations={'smoke':limit}),transport_factory=lambda:transport,
        partition='smoke',planner=spec,judge=spec,reviewer=spec,budget=limit)
    server=create_server(tmp_path/'catalog.sqlite',port=0,fresh_backend=backend)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        client=RoleClient(server.server_address[1],RoleDefinition('reviewer','1','Review'))
        client.import_source({'source_id':'rules.md','text':'# Rules and exceptions\nThe customer is a member. '
            'Ordinary returns end after 14 days. An exception permits returns for 30 days.\n',
            'scope':'project','entities':[],'effective_from':'2026-01-01','effective_to':'open',
            'observed_at':None,'authority':None})
        result=client.ask_fresh('enabling','Can this member return after twenty days?','project',
                                as_of='2026-11-15',entities=[])
        assert result['plan']['expression']==graph
        assert [item['id'] for item in result['plan']['predicates']]==['eligible','ordinary','exception']
        assert result['conditional_outcome']=='true' and result['status']=='deferred' and result['answer'] is None
        assert 'ob-plan-coverage' in result['blocking_obligations'] and transport.calls_made==8
        replay=client.get_fresh_run(result['run_id'])
        assert replay['plan']==result['plan'] and replay['verification']['status']=='unanchored'
        controls = client.check_fresh_cases(result['run_id'], [
            {'case_id':'enabling', 'assignments':{'eligible':'true','ordinary':'false','exception':'true'}, 'expected':'true'},
            {'case_id':'missing', 'assignments':{'eligible':'true','ordinary':'false'}, 'expected':'true'},
            {'case_id':'opposite', 'assignments':{'eligible':'true','ordinary':'false','exception':'true'}, 'expected':'false'}])
        assert controls['archive_digest'] == replay['verification']['digest']
        assert controls['independent'] is False and controls['attribution'] == 'authored_hypothetical'
        assert [item['classification'] for item in controls['results']] == [
            'matches_authored_expectation','inconclusive','contradicts_authored_expectation']
        with pytest.raises(ClientError):
            client.check_fresh_cases(result['run_id'], [{'case_id':'invalid','assignments':{'other':'true'},'expected':'true'}])
        with pytest.raises(ClientError):
            client.check_fresh_cases(result['run_id'], [])
        duplicate = {'case_id':'same','assignments':{},'expected':'true'}
        with pytest.raises(ClientError):
            client.check_fresh_cases(result['run_id'], [duplicate, duplicate])
        with pytest.raises(ClientError, match='404'):
            client.check_fresh_cases('0'*64, [{'case_id':'missing','assignments':{},'expected':'true'}])
        assert client.get_fresh_run(result['run_id'])['verification']['digest'] == controls['archive_digest']
        assert transport.calls_made == 8
        if os.environ.get('QJIG_CHROMIUM_PATH'):
            playwright=pytest.importorskip('playwright.sync_api')
            with playwright.sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=os.environ['QJIG_CHROMIUM_PATH'])
                try:
                    page=browser.new_page(); page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    page.locator('#fresh-runs').get_by_role('button',name='Can this member return',exact=False).click()
                    page.get_by_text('Conditional graph: (eligible AND (ordinary OR exception))').wait_for()
                    assert 'Plan completeness and correctness are not established.' in page.locator('#fresh-replay').inner_text()
                finally:
                    browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
