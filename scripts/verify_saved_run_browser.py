#!/usr/bin/env python3
"""Optional real Chromium walkthrough; requires playwright and a browser executable.

This exercises synthetic local authored data only. It does not establish model
quality, semantic correctness, accessibility or full workflow acceptance.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from qjig.export import verify_authored_export
from qjig.service import create_server


def start(path: Path):
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='qjig-browser-') as directory:
        root = Path(directory)
        server, thread = start(root / 'catalog.sqlite')
        try:
            with sync_playwright() as playwright:
                executable = os.environ.get('QJIG_CHROMIUM_PATH')
                browser = playwright.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 900}, accept_downloads=True)
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/', wait_until='networkidle')
                    for field, value in {'source_id': 'policy.md', 'text': '# Refund limit\nRefunds are accepted within 14 days.\n',
                                         'scope': 'project', 'effective_from': '2026-01-01'}.items():
                        page.locator(f'#source-form [name="{field}"]').fill(value)
                    page.locator('#source-form button[type="submit"]').click()
                    page.wait_for_function("() => document.querySelector('#source-message').textContent.includes('Source saved')")
                    for field, value in {'question': 'Refund after 20 days?', 'scope': 'project', 'as_of': '2026-11-15',
                                         'value': '20', 'query': 'refund days limit', 'pattern': r'within (\d+) days'}.items():
                        page.locator(f'#question-form [name="{field}"]').fill(value)
                    with page.expect_response(lambda response: response.url.endswith('/api/ask') and response.request.method == 'POST') as response_event:
                        page.locator('#question-form button[type="submit"]').click()
                    original = response_event.value.json()
                    assert original['result']['outcome'] is False and original['run_id']
                    run_id = original['run_id']
                    page.wait_for_function("() => document.querySelector('#result-status').textContent === 'Decided · no'")
                    page.locator('#sources li button').first.click()
                    page.wait_for_function("() => document.querySelector('#selected-source').textContent.startsWith('Selected:')")
                    page.locator('#intervention-form [name="passage"]').fill('14')
                    page.locator('#intervention-form [name="replacement"]').fill('30')
                    page.locator('#intervention-form button[type="submit"]').click()
                    page.wait_for_function("() => document.querySelector('#intervention-message').textContent.startsWith('Revision created')")
                    page.wait_for_function("() => document.querySelector('#result-status').textContent === 'Source changed · rerun'")
                    page.locator('#question-form button[type="submit"]').click()
                    page.wait_for_function("() => document.querySelector('#result-status').textContent === 'Decided · yes'")
                    stop(server, thread)
                    server, thread = start(root / 'catalog.sqlite')
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/', wait_until='networkidle')
                    page.locator('#saved-runs button').filter(has_text=run_id[:12]).click()
                    page.wait_for_function("() => document.querySelector('#saved-run-message').textContent.startsWith('Saved snapshot opened')")
                    page.wait_for_function("() => document.querySelector('#result-status').textContent === 'Source changed · rerun'")
                    assert '14 days' in page.locator('#result').inner_text()
                    with page.expect_download() as download_event:
                        page.locator('#download-run').click()
                    download = download_event.value
                    destination = root / 'download.json'
                    download.save_as(destination)
                    bundle = json.loads(destination.read_text(encoding='utf-8'))
                    assert bundle['sha256'] == run_id and bundle['payload']['result']['outcome'] is False
                    assert verify_authored_export(bundle, expected_digest=run_id)['status'] == 'structurally_verified'
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    print(json.dumps({'status': 'passed', 'original_outcome': False, 'changed_outcome': True,
                                      'saved_run_reopened_after_restart': True, 'download_verified': True,
                                      'source_status': 'stale', 'viewport_width': 390,
                                      'semantics': 'not_assessed', 'provider_calls': 0}))
                finally:
                    browser.close()
        finally:
            stop(server, thread)


if __name__ == '__main__':
    main()
