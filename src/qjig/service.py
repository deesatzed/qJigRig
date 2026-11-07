"""Loopback-only catalog API foundation; no hosted models or browser workflow yet."""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .applicability import MemberMetadata, Interval
from .cli import _dec, _member_from_row, _member_row, run_authored
from .contracts import ContractError, Request
from .indexing import index_entries, invalidate_superseded, save_entries
from .sources import SourceRevision, decode_source
from .store import Catalog

MAX_BODY = 1_000_000
_FIELDS = {"source_id", "text", "scope", "entities", "effective_from", "effective_to", "observed_at", "authority"}


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, catalog: Path, address: tuple[str, int]):
        self.catalog = catalog
        self.writer_lock = threading.Lock()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: LocalServer

    def log_message(self, format: str, *args: object) -> None:
        pass  # request bodies and sources must not be copied into server logs

    def _reply(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _trusted_host(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get_all("Host", []) == [f"127.0.0.1:{port}"]

    def _trusted_origin(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get_all("Origin", []) == [f"http://127.0.0.1:{port}"]

    def do_GET(self) -> None:
        if not self._trusted_host():
            self._reply(403, {"error": "untrusted host"})
        elif self.path in ("/", "/app.css", "/app.js"):
            from .web import CSS, HTML, JS
            content, content_type = {"/": (HTML, "text/html"), "/app.css": (CSS, "text/css"), "/app.js": (JS, "text/javascript")}[self.path]
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/health":
            self._reply(200, {"ok": True, "service": "qjig"})
        elif self.path == "/api/sources":
            with Catalog.open(self.server.catalog) as catalog:
                sources = []
                for row in catalog.metadata_rows():
                    member = _member_from_row(row)
                    revision = catalog.get_revision(member.revision_id)
                    sources.append({"source_id": revision.source_id, "revision_id": revision.revision_id,
                                    "scope": member.scope, "authority": member.authority_id,
                                    "entities": sorted(member.entity_keys), "effective_from": row[4],
                                    "effective_to": row[5], "observed_at": member.observed_at})
            self._reply(200, {"sources": sources})
        elif self.path.startswith("/api/sources/"):
            revision_id = self.path.removeprefix("/api/sources/")
            if not re.fullmatch(r"rev1:[0-9a-f]{64}", revision_id):
                self._reply(404, {"error": "not found"})
                return
            with Catalog.open(self.server.catalog) as catalog:
                try:
                    revision = catalog.get_revision(revision_id)
                except KeyError:
                    self._reply(404, {"error": "not found"})
                    return
            self._reply(200, {"source_id": revision.source_id, "revision_id": revision.revision_id,
                              "encoding": revision.decoded.encoding, "raw_sha256": revision.decoded.raw_sha256,
                              "text_sha256": revision.decoded.text_sha256, "text": revision.decoded.text})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._trusted_host() or not self._trusted_origin():
            self._reply(403, {"error": "untrusted host or origin"})
            return
        if self.path not in ("/api/sources", "/api/ask"):
            self._reply(404, {"error": "not found"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit() or self.headers.get("Transfer-Encoding"):
            self._reply(400, {"error": "invalid content length"})
            return
        length = int(lengths[0])
        if length > MAX_BODY:
            self._reply(413, {"error": "request too large"})
            return
        if self.headers.get_content_type() != "application/json":
            self._reply(415, {"error": "application/json required"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if self.path == "/api/sources":
                result, created = self._import_source(body)
                self._reply(201 if created else 200, result)
            else:
                if not isinstance(body, dict) or set(body) != {"request", "policy"}:
                    raise ContractError("request and policy required")
                if not isinstance(body["request"], dict) or not isinstance(body["policy"], dict):
                    raise ContractError("request and policy must be objects")
                request = Request.from_dict(body["request"])
                with self.server.writer_lock:
                    result, _ = run_authored(self.server.catalog, request, body["policy"])
                self._reply(200, {"kind": "deterministic", "result": result})
        except (ValueError, TypeError, KeyError, UnicodeError, ContractError, ArithmeticError, re.error):
            self._reply(400, {"error": "invalid request"})
            return

    def _import_source(self, body: object) -> tuple[dict, bool]:
        if not isinstance(body, dict) or set(body) != _FIELDS:
            raise ContractError("source fields mismatch")
        if any(not isinstance(body[k], str) or not body[k] for k in ("source_id", "text", "scope", "effective_from", "effective_to")):
            raise ContractError("invalid source fields")
        if (not isinstance(body["entities"], list) or not all(isinstance(e, str) and e for e in body["entities"])
                or (body["authority"] is not None and not isinstance(body["authority"], str))
                or (body["observed_at"] is not None and not isinstance(body["observed_at"], str))):
            raise ContractError("invalid metadata")
        revision = SourceRevision.create(body["source_id"], f"api:{body['source_id']}", decode_source(body["text"].encode("utf-8"), encoding="utf-8"))
        member = MemberMetadata(revision.revision_id, body["scope"], Interval(_dec(body["effective_from"]), _dec(body["effective_to"])),
                                body["authority"], frozenset(body["entities"]), body["observed_at"])
        row = _member_row(revision.revision_id, member)
        with self.server.writer_lock, Catalog.open(self.server.catalog) as catalog:
            existing = {item[0]: item for item in catalog.metadata_rows()}.get(revision.revision_id)
            if existing is not None and existing != row:
                raise ContractError("revision metadata conflict")
            entries = index_entries(revision)
            if existing is None:
                catalog.add_revision(revision)
                save_entries(catalog, entries)
                invalidate_superseded(catalog, revision.source_id, current_revision_id=revision.revision_id)
                catalog.put_metadata_row(row)
        return {"source_id": revision.source_id, "revision_id": revision.revision_id, "entries": len(entries)}, existing is None


def create_server(catalog: str | Path, *, host: str = "127.0.0.1", port: int = 8766) -> LocalServer:
    if host != "127.0.0.1" or type(port) is not int or not 0 <= port <= 65535:
        raise ContractError("service requires IPv4 loopback and a valid port")
    path = Path(catalog)
    with Catalog.open(path):
        pass
    return LocalServer(path, (host, port))
