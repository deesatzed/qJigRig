"""Optional real-browser regression for source-inspection failure handling."""
import os
import threading

import pytest

from qjig.indexing import index_entries
from qjig.service import create_server
from qjig.sources import SourceRevision, decode_source
from qjig.store import Catalog


def test_failed_source_selection_hides_prior_preview(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    executable = os.environ.get('QJIG_CHROMIUM_PATH')
    if not executable:
        pytest.skip('QJIG_CHROMIUM_PATH is required for browser verification')
    first = SourceRevision.create('first.md', 'synthetic', decode_source(b'First source evidence', encoding='utf-8'))
    second = SourceRevision.create('second.md', 'synthetic', decode_source(b'Second source evidence', encoding='utf-8'))
    path = tmp_path / 'catalog.sqlite'
    with Catalog.open(path) as catalog:
        for revision in (first, second):
            catalog.import_snapshot(revision, index_entries(revision),
                                    (revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=executable)
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 844})
                page.goto(f'http://127.0.0.1:{server.server_address[1]}/', wait_until='networkidle')
                first_button = page.get_by_role('button', name='first.md', exact=False)
                first_button.focus()
                page.keyboard.press('Enter')
                page.locator('#source-preview').get_by_text('First source evidence').wait_for()
                page.route('**/api/sources/**', lambda route: route.fulfill(status=503, body='unavailable'))
                page.get_by_role('button', name='second.md', exact=False).click()
                page.get_by_text('Could not load source.').wait_for()
                assert page.locator('#source-preview').is_hidden()
                assert page.locator('#source-preview').inner_text() == ''
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_two_browser_clients_show_cross_client_source_change(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    executable = os.environ.get('QJIG_CHROMIUM_PATH')
    if not executable:
        pytest.skip('QJIG_CHROMIUM_PATH is required for browser verification')
    revision = SourceRevision.create('policy.md', 'synthetic', decode_source(
        b'# Refund limit\nRefunds are accepted within 14 days.\n', encoding='utf-8'))
    path = tmp_path / 'catalog.sqlite'
    with Catalog.open(path) as catalog:
        catalog.import_snapshot(revision, index_entries(revision),
                                (revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=executable)
            try:
                reader_context = browser.new_context(viewport={'width': 1280, 'height': 900})
                editor_context = browser.new_context(viewport={'width': 390, 'height': 844})
                reader, editor = reader_context.new_page(), editor_context.new_page()
                url = f'http://127.0.0.1:{server.server_address[1]}/'
                reader.goto(url, wait_until='networkidle')
                editor.goto(url, wait_until='networkidle')
                fields = {'question': 'Refund after 20 days?', 'scope': 'project', 'as_of': '2026-11-15',
                          'value': '20', 'query': 'refund days limit', 'pattern': r'within (\d+) days'}
                for field, value in fields.items():
                    reader.locator(f'#question-form [name="{field}"]').fill(value)
                reader.locator('#question-form button[type="submit"]').click()
                reader.get_by_text('Decided · no').wait_for()
                assert '14 days' in reader.locator('#result').inner_text()
                editor.get_by_role('button', name='policy.md', exact=False).click()
                editor.locator('#source-preview').get_by_text('14 days', exact=False).wait_for()
                editor.locator('#intervention-form [name="passage"]').fill('14')
                editor.locator('#intervention-form [name="replacement"]').fill('30')
                editor.locator('#intervention-form button[type="submit"]').click()
                editor.get_by_text('Revision created. Run the question again to compare.').wait_for()
                reader.get_by_text('Source changed · rerun').wait_for(timeout=10000)
                assert '14 days' in reader.locator('#result').inner_text()
                reader.locator('#question-form button[type="submit"]').click()
                reader.get_by_text('Decided · yes').wait_for()
                assert '30 days' in reader.locator('#result').inner_text()
                assert editor.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_browser_distinguishes_unknown_from_source_conflict(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    executable = os.environ.get('QJIG_CHROMIUM_PATH')
    if not executable:
        pytest.skip('QJIG_CHROMIUM_PATH is required for browser verification')
    path = tmp_path / 'catalog.sqlite'
    with Catalog.open(path) as catalog:
        for name, days in (('first.md', 14), ('second.md', 30)):
            revision = SourceRevision.create(name, 'synthetic', decode_source(
                f'# Refund policy\nRefunds are accepted within {days} days.\n'.encode(), encoding='utf-8'))
            catalog.import_snapshot(revision, index_entries(revision),
                                    (revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=executable)
            try:
                page = browser.new_page(viewport={'width': 1280, 'height': 900})
                page.goto(f'http://127.0.0.1:{server.server_address[1]}/', wait_until='networkidle')
                fields = {'question': 'Refund after 20 days?', 'scope': 'project', 'as_of': '2026-11-15',
                          'value': '20', 'query': 'zephyrunfindable', 'pattern': r'within (\d+) days'}
                for field, value in fields.items():
                    page.locator(f'#question-form [name="{field}"]').fill(value)
                page.locator('#question-form button[type="submit"]').click()
                page.get_by_text('Deferred', exact=True).wait_for()
                result = page.locator('#result')
                assert 'unknown' in result.inner_text().lower()
                page.locator('#question-form [name="query"]').fill('refund days policy')
                page.locator('#question-form button[type="submit"]').click()
                page.wait_for_function("() => document.querySelector('#result').textContent.includes('conflict')")
                assert page.locator('#result-status').inner_text() == 'Deferred'
                text = result.inner_text()
                assert 'multiple_applicable_policies' in text
                assert '14 days' in text and '30 days' in text
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_failed_question_does_not_present_previous_result(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    executable = os.environ.get('QJIG_CHROMIUM_PATH')
    if not executable:
        pytest.skip('QJIG_CHROMIUM_PATH is required for browser verification')
    revision = SourceRevision.create('policy.md', 'synthetic', decode_source(
        b'# Refund policy\nRefunds are accepted within 14 days.\n', encoding='utf-8'))
    path = tmp_path / 'catalog.sqlite'
    with Catalog.open(path) as catalog:
        catalog.import_snapshot(revision, index_entries(revision),
                                (revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=executable)
            try:
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_address[1]}/', wait_until='networkidle')
                fields = {'question': 'Refund after 20 days?', 'scope': 'project', 'as_of': '2026-11-15',
                          'value': '20', 'query': 'refund days policy', 'pattern': r'within (\d+) days'}
                for field, value in fields.items():
                    page.locator(f'#question-form [name="{field}"]').fill(value)
                page.locator('#question-form button[type="submit"]').click()
                page.get_by_text('Decided · no').wait_for()
                assert '14 days' in page.locator('#result').inner_text()
                page.locator('#saved-runs button').first.wait_for()
                page.route('**/api/ask', lambda route: route.fulfill(status=503, body='unavailable'))
                page.locator('#question-form [name="question"]').fill('A different question?')
                page.locator('#question-form button[type="submit"]').click()
                page.get_by_text('Could not run question:', exact=False).wait_for()
                assert page.locator('#result-status').inner_text() == 'Run failed'
                assert '14 days' not in page.locator('#result').inner_text()
                assert page.locator('#saved-runs button').count() == 1
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
