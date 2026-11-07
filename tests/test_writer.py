"""Real SQLite and loopback service fault injection; synthetic source data."""
import sqlite3
import threading
import pytest
from qjig.agents import ClientError, RoleClient
from qjig.indexing import load_live_entries
from qjig.roles import RoleDefinition
from qjig.service import create_server
from qjig.store import Catalog


def test_source_import_rolls_back_all_changes_on_failure(tmp_path):
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = RoleClient(server.server_address[1], RoleDefinition('builder', '1', 'Build'))
    source = {'source_id': 'policy.md', 'text': '# Rule\nOld evidence.\n', 'scope': 'project', 'entities': [],
              'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
    try:
        old = client.import_source(source)['revision_id']
        with sqlite3.connect(path) as con:
            con.execute("CREATE TRIGGER fail_metadata BEFORE INSERT ON member_metadata BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        with pytest.raises(ClientError):
            client.import_source({**source, 'text': '# Rule\nNew evidence.\n'})
        with Catalog.open(path) as catalog:
            assert catalog.revision_ids() == [old]
            assert {item.revision_id for item in load_live_entries(catalog)} == {old}
            assert len(catalog.metadata_rows()) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_two_service_instances_serialize_identical_imports(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path / 'catalog.sqlite'
    servers = [create_server(path, host='127.0.0.1', port=0) for _ in range(2)]
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for t in threads:
        t.start()
    try:
        clients = [RoleClient(s.server_address[1], RoleDefinition('builder', '1', 'Build')) for s in servers]
        source = {'source_id': 'policy.md', 'text': '# Rule\nShared evidence.\n', 'scope': 'project', 'entities': [],
                  'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda client: client.import_source(source), clients))
        assert results[0] == results[1]
        with Catalog.open(path) as catalog:
            assert catalog.revision_ids() == [results[0]['revision_id']]
            assert len(catalog.metadata_rows()) == 1 and len(load_live_entries(catalog)) == 1
    finally:
        for s in servers:
            s.shutdown()
            s.server_close()
        for t in threads:
            t.join(timeout=5)


def test_process_exit_during_import_rolls_back_snapshot(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = {'source_id': 'policy.md', 'text': '# Rule\nOld evidence.\n', 'scope': 'project', 'entities': [],
              'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
    try:
        old = RoleClient(server.server_address[1], RoleDefinition('builder', '1', 'Build')).import_source(source)['revision_id']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    code = '''
import os, sys
from qjig.store import Catalog
from qjig.sources import SourceRevision, decode_source
from qjig.indexing import index_entries
from qjig.cli import _member_row
from qjig.applicability import MemberMetadata, Interval, OPEN
with Catalog.open(sys.argv[1]) as cat:
    rev = SourceRevision.create('policy.md', 'api:policy.md', decode_source(b'# Rule\\nNew evidence.\\n', encoding='utf-8'))
    meta = _member_row(rev.revision_id, MemberMetadata(rev.revision_id, 'project', Interval('2026-01-01', OPEN)))
    cat._con.create_function('die_now', 0, lambda: os._exit(23))
    cat._con.execute('CREATE TEMP TRIGGER kill_import BEFORE INSERT ON member_metadata BEGIN SELECT die_now(); END')
    cat.import_snapshot(rev, index_entries(rev), meta)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    child = subprocess.run([sys.executable, '-c', code, str(path)], env=env, timeout=10, capture_output=True)
    assert child.returncode == 23, child.stderr.decode()
    with Catalog.open(path) as catalog:
        assert catalog.revision_ids() == [old]
        assert {entry.revision_id for entry in load_live_entries(catalog)} == {old}
        assert len(catalog.metadata_rows()) == 1
