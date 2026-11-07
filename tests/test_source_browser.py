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
