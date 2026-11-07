"""Real loopback HTTP; user interaction is verified separately in a browser."""
import http.client
import threading
from qjig.service import create_server


def test_browser_workspace_served_from_loopback(tmp_path):
    server = create_server(tmp_path / "catalog.sqlite", host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        connection.request("GET", "/")
        response = connection.getresponse()
        html = response.read().decode()
        assert response.status == 200 and "text/html" in response.getheader("Content-Type")
        assert "Add a source" in html and "Ask a question" in html
        assert 'src="/app.js"' in html and 'href="/app.css"' in html
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_browser_serves_source_linked_interpretation_controls(tmp_path):
    server = create_server(tmp_path / 'catalog.sqlite', host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
        connection.request('GET', '/')
        response = connection.getresponse()
        html = response.read().decode()
        assert response.status == 200
        assert 'Share an interpretation' in html and 'id="interpretation-form"' in html
        assert 'id="interpretation-list"' in html and 'id="selected-source"' in html
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_browser_serves_controlled_intervention_controls(tmp_path):
    server = create_server(tmp_path / 'catalog.sqlite', host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
        connection.request('GET', '/')
        response = connection.getresponse()
        html = response.read().decode()
        assert response.status == 200
        assert 'Edit a source' in html and 'id="intervention-form"' in html
        assert 'id="intervention-message"' in html and 'id="intervention-list"' in html
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_browser_serves_saved_run_controls(tmp_path):
    server = create_server(tmp_path / 'catalog.sqlite', host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
        connection.request('GET', '/')
        response = connection.getresponse()
        html = response.read().decode()
        assert response.status == 200
        assert 'Saved runs' in html and 'id="saved-runs"' in html and 'id="download-run"' in html
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_review_records_are_visible_from_local_workbench(tmp_path):
    import json
    from qjig.contracts import Request
    from qjig.programs import make_review
    from qjig.sources import SourceRevision, decode_source
    from qjig.store import Catalog
    path = tmp_path / 'catalog.sqlite'
    revision = SourceRevision.create('docs/rule.md', 'fixture', decode_source(b'# Rule\nTests pass.\n', encoding='utf-8'))
    metadata = {'scope': 'project', 'authority_id': None, 'entity_keys': [], 'effective_start': '2026-01-01', 'effective_end': 'open', 'observed_at': None}
    binding = {'request': Request('r', 'Can this merge?', 'reviewer', '1', 'project').to_dict(),
               'plan': {'origin': 'fresh', 'predicates': [{'id': 'p', 'question': 'Tests pass?'}], 'expression': {'ref': 'p'}},
               'corpus_revision_ids': [revision.revision_id], 'source_metadata': {revision.revision_id: metadata},
               'as_of': '2026-11-07', 'entities': [], 'historical_as_known': False,
               'planner': {'provider': 'stand-in', 'model': 'planner', 'prompt_sha256': 'b'*64, 'config': {}}}
    reviewer = {'kind': 'synthetic', 'provider': 'stand-in', 'model': 'reviewer', 'prompt_sha256': 'c'*64, 'config': {}}
    record = make_review(binding, reviewer, {'assessment': 'uncertain', 'reason': 'More evidence needed.'})
    with Catalog.open(path) as catalog:
        catalog.add_revision(revision)
        catalog.put_metadata_row((revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
        catalog.save_program_review(record, catalog.source_state())
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=5)
        conn.request('GET', '/api/reviews')
        response = conn.getresponse()
        assert response.status == 200
        data = json.loads(response.read())
        assert len(data['reviews']) == 1
        review = data['reviews'][0]
        assert review['review_id'] == record['sha256'] and review['assurance'] == 'synthetic_review_unvalidated'
        assert review['question'] == 'Can this merge?' and review['source_revisions'] == [revision.revision_id]
        assert review['assessment'] == 'uncertain' and review['reason'] == 'More evidence needed.'
        conn.close()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=5)
        conn.request('GET', '/')
        response = conn.getresponse()
        html = response.read().decode()
        assert 'Saved reviews' in html and 'id="review-list"' in html
        conn.close()
        import sqlite3
        with sqlite3.connect(path) as con:
            con.execute('DROP TRIGGER program_reviews_no_update')
            altered = json.loads(json.dumps(record))
            altered['payload']['result']['reason'] = 'tampered'
            con.execute('UPDATE program_reviews SET record=? WHERE review_id=?', (json.dumps(altered), record['sha256']))
        conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=5)
        conn.request('GET', '/api/reviews')
        response = conn.getresponse()
        assert response.status == 500 and json.loads(response.read())['error'] == 'stored review invalid'
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_review_view_reports_local_source_freshness(tmp_path):
    import json
    from qjig.contracts import Request
    from qjig.indexing import index_entries
    from qjig.programs import make_draft, make_review
    from qjig.sources import SourceRevision, decode_source
    from qjig.store import Catalog
    path = tmp_path / 'catalog.sqlite'
    revision = SourceRevision.create('rule.md', 'fixture', decode_source(b'# Rule\nTests pass.\n', encoding='utf-8'))
    metadata = {'scope': 'project', 'authority_id': None, 'entity_keys': [], 'effective_start': '2026-01-01', 'effective_end': 'open', 'observed_at': None}
    binding = {'request': Request('r', 'Can this merge?', 'reviewer', '1', 'project').to_dict(),
               'plan': {'origin': 'fresh', 'predicates': [{'id': 'p', 'question': 'Tests pass?'}], 'expression': {'ref': 'p'}},
               'corpus_revision_ids': [revision.revision_id], 'source_metadata': {revision.revision_id: metadata},
               'as_of': '2026-11-07', 'entities': [], 'historical_as_known': False,
               'planner': {'provider': 'stand-in', 'model': 'planner', 'prompt_sha256': 'b'*64, 'config': {}}}
    reviewer = {'kind': 'synthetic', 'provider': 'stand-in', 'model': 'reviewer', 'prompt_sha256': 'c'*64, 'config': {}}
    review = make_review(binding, reviewer, {'assessment': 'uncertain', 'reason': 'Fixture'})
    with Catalog.open(path) as catalog:
        catalog.import_snapshot(revision, index_entries(revision), (revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
        draft_id, _ = catalog.save_reviewed_draft(make_draft(binding), review, catalog.source_state())
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def fetch():
        conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=5)
        conn.request('GET', '/api/reviews')
        response = conn.getresponse()
        assert response.status == 200
        result = json.loads(response.read())['reviews'][0]
        conn.close()
        return result
    try:
        assert fetch()['programs'] == [{'draft_id': draft_id, 'source_freshness': 'matches_local_index'}]
        unknown = SourceRevision.create('other.md', 'fixture', decode_source(b'# Other\nNew.\n', encoding='utf-8'))
        with Catalog.open(path) as catalog:
            catalog.add_revision(unknown)
        assert fetch()['programs'][0]['source_freshness'] == 'unknown'
        with Catalog.open(path) as catalog:
            catalog.import_snapshot(unknown, index_entries(unknown), (unknown.revision_id, 'other', None, '[]', '2026-01-01', 'open', None))
        assert fetch()['programs'][0]['source_freshness'] == 'matches_local_index'
        newer = SourceRevision.create('rule.md', 'fixture', decode_source(b'# Rule\nTests and review pass.\n', encoding='utf-8'))
        with Catalog.open(path) as catalog:
            catalog.import_snapshot(newer, index_entries(newer), (newer.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
        assert fetch()['programs'][0]['source_freshness'] == 'stale'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
