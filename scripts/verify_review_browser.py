#!/usr/bin/env python3
"""Optional Chromium walkthrough using a synthetic, locally journaled review."""
import json
import os
import tempfile
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright
from qjig.budgets import BudgetLedger
from qjig.contracts import Budget, Request
from qjig.indexing import index_entries
from qjig.journal import Journal
from qjig.packets import build_packet
from qjig.program_review import review_plan
from qjig.providers import RawResponse, StandInTransport
from qjig.retrieval import bm25_candidates
from qjig.run_archive import RunArchive
from qjig.service import create_server
from qjig.sources import SourceRevision, decode_source
from qjig.store import Catalog


def main():
    with tempfile.TemporaryDirectory(prefix='qjig-review-browser-') as directory:
        root = Path(directory)
        revision = SourceRevision.create('docs/rule.md', 'fixture', decode_source(b'# Rule\nTests must pass.\n', encoding='utf-8'))
        metadata = {'scope': 'project', 'authority_id': None, 'entity_keys': [], 'effective_start': '2026-01-01', 'effective_end': 'open', 'observed_at': None}
        binding = {'request': Request('r', 'Can this merge?', 'reviewer', '1', 'project').to_dict(),
                   'plan': {'origin': 'fresh', 'predicates': [{'id': 'p', 'question': 'Tests pass?'}], 'expression': {'ref': 'p'}},
                   'corpus_revision_ids': [revision.revision_id], 'source_metadata': {revision.revision_id: metadata},
                   'as_of': '2026-11-07', 'entities': [], 'historical_as_known': False,
                   'planner': {'provider': 'stand-in', 'model': 'planner', 'prompt_sha256': 'b'*64, 'config': {}}}
        packet = build_packet(bm25_candidates(index_entries(revision), 'tests'), max_bytes=3000)
        response = RawResponse(200, json.dumps({'assessment': 'uncertain', 'reason': 'More evidence needed.'}),
                               {'prompt_tokens': 12, 'completion_tokens': 5, 'cost_usd': 0.01})
        with Catalog.open(root / 'catalog.sqlite') as catalog, Journal.open(root / 'journal.sqlite') as journal, RunArchive.open(root / 'archive') as archive:
            catalog.import_snapshot(revision, index_entries(revision),
                                    (revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
            outcome = review_plan(catalog, BudgetLedger(Budget(2, 10000, 1), journal, 'r'), StandInTransport([response]),
                                  binding, packet, provider='stand-in', model='reviewer', archive=archive)
            assert outcome.status == 'recorded' and not outcome.activation
        server = create_server(root / 'catalog.sqlite', host='127.0.0.1', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                executable = os.environ.get('QJIG_CHROMIUM_PATH')
                browser = playwright.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 900})
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/', wait_until='networkidle')
                    programs = page.locator('#program-list')
                    programs.get_by_text('Can this merge?').wait_for()
                    assert 'review record linked (unvalidated)' in programs.inner_text()
                    assert 'Not active' in programs.inner_text()
                    assert 'Local source index matches this draft' in programs.inner_text()
                    area = page.locator('#review-list')
                    area.get_by_text('Can this merge?').wait_for()
                    assert 'Synthetic review · unvalidated' in area.inner_text()
                    assert 'More evidence needed.' in area.inner_text()
                    assert 'Local source index matches this draft' in area.inner_text()
                    source_button = area.get_by_role('button', name='Inspect source', exact=False)
                    source_button.focus()
                    page.keyboard.press('Enter')
                    page.wait_for_function("() => document.querySelector('#source-preview').textContent.includes('Tests must pass.')")
                    page.locator('#intervention-form [name="passage"]').fill('must pass')
                    page.locator('#intervention-form [name="replacement"]').fill('must pass and be reviewed')
                    page.locator('#intervention-form button[type="submit"]').click()
                    area.get_by_text('Source snapshot changed · review is stale').wait_for()
                    programs.get_by_text('Source snapshot changed · draft is stale').wait_for()
                    programs.get_by_role('button', name='Inspect source', exact=False).click()
                    page.wait_for_function("() => document.querySelector('#source-preview').textContent.includes('Tests must pass.')")
                    area.get_by_role('button', name='Inspect source', exact=False).click()
                    page.wait_for_function("() => document.querySelector('#source-preview').textContent.includes('Tests must pass.')")
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    print(json.dumps({'status': 'passed', 'synthetic_review_visible': True, 'keyboard_source_inspection': True,
                                      'source_change_shown_stale': True, 'draft_status_and_original_source_visible': True,
                                      'viewport_width': 390, 'hosted_calls': 0, 'semantic_assurance': 'not_assessed'}))
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
