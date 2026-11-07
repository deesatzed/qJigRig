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
