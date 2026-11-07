"""Actual localhost HTTP and temporary synthetic sources; no hosted models."""
import http.client
import json
import threading

import pytest
from qjig.contracts import ContractError
from qjig.service import create_server


def test_loopback_catalog_import_and_origin_guard(tmp_path):
    server = create_server(tmp_path / "catalog.sqlite", host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    def request(method, path, payload=None, origin_value=None, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        headers = {}
        if payload is not None:
            payload = json.dumps(payload)
            headers["Content-Type"] = "application/json"
        if origin_value is not None:
            headers["Origin"] = origin_value
        if host is not None:
            headers["Host"] = host
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result
    try:
        status, health = request("GET", "/api/health")
        assert status == 200 and health == {"ok": True, "service": "qjig"}
        source = {"source_id": "docs/example.md", "text": "# Policy\nRefunds within 14 days.\n",
                  "scope": "project", "entities": ["customer:42"], "effective_from": "2026-01-01",
                  "effective_to": "open", "observed_at": "2026-01-02", "authority": "team:docs"}
        assert request("POST", "/api/sources", source)[0] == 403
        assert request("POST", "/api/sources", source, "http://evil.example")[0] == 403
        assert request("POST", "/api/sources", source, origin, "evil.example")[0] == 403
        status, imported = request("POST", "/api/sources", source, origin)
        assert status == 201 and imported["revision_id"].startswith("rev1:")
        status, listed = request("GET", "/api/sources")
        assert status == 200 and listed["sources"][0]["revision_id"] == imported["revision_id"]
        status, detail = request("GET", "/api/sources/" + imported["revision_id"])
        assert status == 200 and detail["text"] == source["text"]
        assert detail["revision_id"] == imported["revision_id"] and "origin" not in detail
        assert request("POST", "/api/sources", {**source, "source_id": "../escape"}, origin)[0] == 400
        assert request("POST", "/api/sources", {**source, "scope": "different"}, origin)[0] == 400
        assert request("GET", "/api/not-a-route")[0] == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    with pytest.raises(ContractError):
        create_server(tmp_path / "other.sqlite", host="0.0.0.0", port=0)


def test_concurrent_imports_are_idempotent_and_survive_restart(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "catalog.sqlite"
    server = create_server(path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    source = {"source_id": "policy.md", "text": "# Policy\nText.\n", "scope": "project", "entities": [],
              "effective_from": "2026-01-01", "effective_to": "open", "observed_at": None, "authority": None}
    def send():
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("POST", "/api/sources", json.dumps(source),
                           {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: send(), range(2)))
        assert sorted(item[0] for item in results) == [200, 201]
        assert results[0][1]["revision_id"] == results[1][1]["revision_id"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    restarted = create_server(path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=restarted.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", restarted.server_address[1], timeout=3)
        connection.request("GET", "/api/sources")
        response = connection.getresponse()
        sources = json.loads(response.read())["sources"]
        connection.close()
        assert response.status == 200 and len(sources) == 1
        assert sources[0]["revision_id"] == results[0][1]["revision_id"]
    finally:
        restarted.shutdown()
        restarted.server_close()
        thread.join(timeout=5)


def test_reimporting_old_revision_does_not_stale_current_source(tmp_path):
    from qjig.indexing import load_live_entries
    from qjig.store import Catalog

    path = tmp_path / "catalog.sqlite"
    server = create_server(path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    source = {"source_id": "policy.md", "text": "# Policy\nOld rule.\n", "scope": "project", "entities": [],
              "effective_from": "2026-01-01", "effective_to": "open", "observed_at": None, "authority": None}
    def send(value):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("POST", "/api/sources", json.dumps(value),
                           {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result
    try:
        old_status, old = send(source)
        new_status, new = send({**source, "text": "# Policy\nNew rule.\n"})
        repeat_status, repeat = send(source)
        assert (old_status, new_status, repeat_status) == (201, 201, 200)
        assert repeat["revision_id"] == old["revision_id"] != new["revision_id"]
        with Catalog.open(path) as catalog:
            assert {e.revision_id for e in load_live_entries(catalog)} == {new["revision_id"]}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_cli_starts_real_loopback_service(tmp_path):
    import os
    import selectors
    import subprocess
    import sys
    from pathlib import Path

    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    child = subprocess.Popen([sys.executable, "-m", "qjig", "serve", "--catalog", str(tmp_path / "service.sqlite"), "--port", "0"],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=10), "service did not report startup"
        ready = json.loads(child.stdout.readline())
        assert ready["host"] == "127.0.0.1" and ready["port"] > 0
        connection = http.client.HTTPConnection("127.0.0.1", ready["port"], timeout=3)
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        assert response.status == 200 and json.loads(response.read())["ok"] is True
        connection.close()
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_authored_question_uses_catalog_and_preserves_fresh_deferral(tmp_path):
    server = create_server(tmp_path / "catalog.sqlite", host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    def post(path, payload):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("POST", path, json.dumps(payload), {"Content-Type": "application/json", "Origin": origin})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result
    source = {"source_id": "policy.md", "text": "# Refund limit\nRefunds are accepted within 14 days of purchase.\n",
              "scope": "project", "entities": ["customer:42"], "effective_from": "2026-01-01", "effective_to": "open",
              "observed_at": "2026-01-02", "authority": "team:policy"}
    request = {"schema_version": "qjig.request.v1", "request_id": "request-1", "question": "Refund after 20 days?",
               "role": "reviewer", "role_version": "1", "scope": "project"}
    policy = {"label": "AUTHORED CONTROL", "entities": ["customer:42"], "as_of": "2026-11-15", "mode": "snapshot",
              "facts": {"refund_days": 20},
              "plan": {"origin": "authored", "predicates": [{"id": "within", "question": "Within refund limit?"}], "expression": {"ref": "within"}},
              "needs": {"within": {"query": "refund days limit", "want": 1, "max_bytes": 4000,
                                   "evaluator": {"kind": "numeric_threshold", "field": "refund_days", "pattern": "within (\\d+) days", "operator": "lte"}}}}
    try:
        assert post("/api/sources", source)[0] == 201
        status, payload = post("/api/ask", {"request": request, "policy": policy})
        assert status == 200 and payload["kind"] == "deterministic"
        result = payload["result"]
        assert result["status"] == "decided" and result["outcome"] is False and result["providers_called"] == 0
        assert result["origin_updates"] == []
        status, current = post("/api/ask", {"request": request, "policy": {**policy, "mode": "current_required"}})
        assert status == 200 and current["result"]["status"] == "decided"
        assert current["result"]["origin_updates"] == []
        assert result["records"][0]["evidence"][0]["text"].find("14 days") >= 0
        fresh = {**policy, "plan": {**policy["plan"], "origin": "fresh"}}
        status, payload = post("/api/ask", {"request": request, "policy": fresh})
        assert status == 200 and payload["result"]["status"] == "deferred"
        assert "plan_coverage_unestablished" in payload["result"]["reasons"]
        wrong_scope = {**request, "scope": "other-project"}
        status, payload = post("/api/ask", {"request": wrong_scope, "policy": policy})
        assert status == 200 and payload["result"]["status"] == "deferred"
        assert payload["result"]["records"][0]["exclusions"][0]["reason"] == "inapplicable"
        wrong_entity = {**policy, "entities": ["customer:other"]}
        status, payload = post("/api/ask", {"request": request, "policy": wrong_entity})
        assert status == 200 and payload["result"]["status"] == "deferred"
        assert post("/api/ask", {"request": request})[0] == 400
        assert post("/api/ask", {"request": [], "policy": policy})[0] == 400
        assert post("/api/ask", {"request": request, "policy": []})[0] == 400
        assert post("/api/ask", {"request": request, "policy": {**policy, "as_of": "2025-11-15"}})[1]["result"]["status"] == "deferred"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_catalog_change_during_authored_run_defers(tmp_path, monkeypatch):
    import qjig.service as service
    from qjig.agents import RoleClient
    from qjig.roles import RoleDefinition

    path = tmp_path / 'catalog.sqlite'
    servers = [create_server(path, host='127.0.0.1', port=0) for _ in range(2)]
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for thread in threads:
        thread.start()
    try:
        a, b = [RoleClient(s.server_address[1], RoleDefinition('reviewer', '1', 'Review')) for s in servers]
        source = {'source_id': 'policy.md', 'text': '# Refund limit\nRefunds are accepted within 14 days.\n',
                  'scope': 'project', 'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        a.import_source(source)
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot', 'facts': {'days': 20},
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Within limit?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'query': 'refund days limit', 'want': 1, 'max_bytes': 4000,
                                  'evaluator': {'kind': 'numeric_threshold', 'field': 'days', 'pattern': r'within (\d+) days', 'operator': 'lte'}}}}
        original = service.run_authored
        def change_between_reads(*args, **kwargs):
            result = original(*args, **kwargs)
            b.import_source({**source, 'source_id': 'another.md', 'text': '# Rule\nNew source.\n'})
            return result
        monkeypatch.setattr(service, 'run_authored', change_between_reads)
        result = a.ask('r', 'Refund?', 'project', policy)['result']
        assert result['status'] == 'deferred' and result['outcome'] is None
        assert 'catalog_changed_during_run' in result['reasons']
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)


def test_catalog_state_changes_only_when_source_catalog_changes(tmp_path):
    from qjig.agents import RoleClient
    from qjig.roles import RoleDefinition
    server = create_server(tmp_path / 'catalog.sqlite', host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        initial = client._request('GET', '/api/catalog-state')['source_state']
        source = {'source_id': 'rule.md', 'text': '# Rule\nA source.\n', 'scope': 'project', 'entities': [],
                  'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        revision = client.import_source(source)['revision_id']
        after_import = client._request('GET', '/api/catalog-state')['source_state']
        assert initial != after_import
        client.import_source(source)
        assert client._request('GET', '/api/catalog-state')['source_state'] == after_import
        detail = client.get_source(revision)
        client.add_interpretation('A finding.', {'revision_id': revision, 'text_sha256': detail['text_sha256'], 'start': 0, 'end': 6})
        assert client._request('GET', '/api/catalog-state')['source_state'] == after_import
        client.import_source({**source, 'source_id': 'another.md'})
        assert client._request('GET', '/api/catalog-state')['source_state'] != after_import
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
