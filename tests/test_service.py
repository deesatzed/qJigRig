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
