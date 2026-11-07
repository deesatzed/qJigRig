"""Loopback-only catalog API foundation; no hosted models or browser workflow yet."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .applicability import MemberMetadata, Interval
from .cli import _dec, _member_from_row, _member_row, run_authored
from .contracts import ContractError, Request
from .claims import add_interpretation, list_interpretations
from .interventions import apply_intervention, list_interventions
from .export import export_authored, verify_authored_export
from .indexing import index_entries
from .sources import SourceRevision, decode_source
from .programs import make_draft
from .store import Catalog, CatalogStateChanged

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
        elif self.path == "/api/catalog-state":
            try:
                with Catalog.open(self.server.catalog) as catalog:
                    state = catalog.source_state()
                self._reply(200, {"source_state": state})
            except sqlite3.Error:
                self._reply(500, {"error": "local storage failure"})
        elif self.path == "/api/runs":
            try:
                with Catalog.open(self.server.catalog) as catalog:
                    runs = []
                    for ident, text in catalog.authored_run_rows():
                        bundle = json.loads(text)
                        if bundle.get('sha256') != ident or verify_authored_export(bundle)['status'] != 'unanchored':
                            raise ContractError('stored run invalid')
                        result = bundle['payload']['result']
                        runs.append({'run_id': ident, 'request_id': result['request']['request_id'],
                                     'question': result['request']['question'], 'status': result['status']})
                self._reply(200, {'runs': runs})
            except (ContractError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error):
                self._reply(500, {'error': 'stored run invalid'})
        elif self.path.startswith("/api/runs/"):
            ident = self.path.removeprefix("/api/runs/")
            if not re.fullmatch(r"[0-9a-f]{64}", ident):
                self._reply(404, {'error': 'not found'})
                return
            try:
                with Catalog.open(self.server.catalog) as catalog:
                    text = catalog.authored_run_row(ident)
                if text is None:
                    self._reply(404, {'error': 'not found'})
                    return
                bundle = json.loads(text)
                verification = verify_authored_export(bundle)
                if bundle.get('sha256') != ident or verification['status'] != 'unanchored':
                    raise ContractError('stored run invalid')
                self._reply(200, {'bundle': bundle, 'verification': verification})
            except (ContractError, ValueError, TypeError, AttributeError, sqlite3.Error):
                self._reply(500, {'error': 'stored run invalid'})
        elif self.path == "/api/programs":
            try:
                with Catalog.open(self.server.catalog) as catalog:
                    programs = []
                    for ident in catalog.program_draft_ids():
                        draft = catalog.program_draft(ident)
                        binding = draft['payload']['binding']
                        status = catalog.program_status(ident, binding)
                        request = binding['request']
                        programs.append({'draft_id': ident, 'question': request['question'],
                                         'scope': request['scope'], 'role': request['role'],
                                         'role_version': request['role_version'], 'as_of': binding['as_of'],
                                         'source_revisions': binding['corpus_revision_ids'],
                                         'origin': binding['plan']['origin'], 'status': status['status'], 'source_freshness': status['source_freshness']['status'],
                                         'review_ids': status['review_ids'], 'activation': status['activation'],
                                         'semantic_assurance': status['semantic_assurance']})
                self._reply(200, {'programs': programs})
            except (ContractError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error):
                self._reply(500, {'error': 'stored program invalid'})
        elif self.path == "/api/reviews":
            try:
                with Catalog.open(self.server.catalog) as catalog:
                    reviews = []
                    programs_by_review = {}
                    for draft_id in catalog.program_draft_ids():
                        draft = catalog.program_draft(draft_id)
                        status = catalog.program_status(draft_id, draft['payload']['binding'])
                        for review_id in status['review_ids']:
                            programs_by_review.setdefault(review_id, []).append({
                                'draft_id': draft_id, 'source_freshness': status['source_freshness']['status']})
                    for ident in catalog.program_review_ids():
                        record = catalog.program_review(ident)
                        payload = record['payload']
                        binding, reviewer, result = payload['binding'], payload['reviewer'], payload['result']
                        reviews.append({'review_id': ident, 'assurance': payload['assurance'],
                                        'question': binding['request']['question'], 'scope': binding['request']['scope'],
                                        'role': binding['request']['role'], 'role_version': binding['request']['role_version'],
                                        'as_of': binding['as_of'], 'source_revisions': binding['corpus_revision_ids'],
                                        'reviewer_kind': reviewer['kind'], 'provider': reviewer['provider'], 'model': reviewer['model'],
                                        'assessment': result.get('assessment') if isinstance(result.get('assessment'), str) else None,
                                        'reason': result.get('reason') if isinstance(result.get('reason'), str) else None,
                                        'programs': programs_by_review.get(ident, [])})
                self._reply(200, {'reviews': reviews})
            except (ContractError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error):
                self._reply(500, {'error': 'stored review invalid'})
        elif self.path == "/api/interpretations":
            try:
                with Catalog.open(self.server.catalog) as catalog:
                    interpretations = list_interpretations(catalog)
                self._reply(200, {"interpretations": interpretations})
            except ContractError:
                self._reply(500, {"error": "stored interpretation invalid"})
        elif self.path == "/api/interventions":
            try:
                with Catalog.open(self.server.catalog) as catalog:
                    interventions = list_interventions(catalog)
                self._reply(200, {"interventions": interventions})
            except ContractError:
                self._reply(500, {"error": "stored intervention invalid"})
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
        if self.path not in ("/api/sources", "/api/ask", "/api/interpretations", "/api/interventions", "/api/programs/from-run"):
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
            elif self.path == "/api/programs/from-run":
                if not isinstance(body, dict) or set(body) != {'run_id'} or not isinstance(body['run_id'], str) or not re.fullmatch(r'[0-9a-f]{64}', body['run_id']):
                    raise ContractError('invalid run identity')
                with self.server.writer_lock, Catalog.open(self.server.catalog) as catalog:
                    text = catalog.authored_run_row(body['run_id'])
                    if text is None:
                        raise ContractError('saved run unavailable')
                    bundle = json.loads(text)
                    if bundle.get('sha256') != body['run_id'] or verify_authored_export(bundle)['status'] != 'unanchored':
                        raise ContractError('saved run invalid')
                    payload = bundle['payload']
                    state = catalog.source_state()
                    if state != payload['source_state']:
                        raise CatalogStateChanged('saved run source state changed')
                    live = sorted({row[1] for row in catalog.live_index_rows()})
                    rows = {row[0]: row for row in catalog.metadata_rows()}
                    if not live or any(ident not in rows for ident in live):
                        raise ContractError('source metadata unavailable')
                    metadata = {ident: {'scope': rows[ident][1], 'authority_id': rows[ident][2],
                                        'entity_keys': json.loads(rows[ident][3]), 'effective_start': rows[ident][4],
                                        'effective_end': rows[ident][5], 'observed_at': rows[ident][6]} for ident in live}
                    policy = payload['policy']
                    binding = {'request': payload['result']['request'], 'plan': policy['plan'],
                               'corpus_revision_ids': live, 'source_metadata': metadata, 'as_of': policy['as_of'],
                               'entities': policy.get('entities', []), 'historical_as_known': policy.get('historical_as_known', False),
                               'planner': {'kind': 'authored_control', 'policy': policy, 'source_run_sha256': body['run_id']}}
                    ident = catalog.save_program_draft(make_draft(binding), state)
                self._reply(200, {'draft_id': ident, 'origin': 'authored_control', 'activation': False})
            elif self.path == "/api/interpretations":
                with self.server.writer_lock, Catalog.open(self.server.catalog) as catalog:
                    result, created = add_interpretation(catalog, body)
                self._reply(201 if created else 200, result)
            elif self.path == "/api/interventions":
                with self.server.writer_lock, Catalog.open(self.server.catalog) as catalog:
                    result, created = apply_intervention(catalog, body)
                self._reply(201 if created else 200, result)
            else:
                if not isinstance(body, dict) or set(body) != {"request", "policy"}:
                    raise ContractError("request and policy required")
                if not isinstance(body["request"], dict) or not isinstance(body["policy"], dict):
                    raise ContractError("request and policy must be objects")
                request = Request.from_dict(body["request"])
                run_id = None
                with self.server.writer_lock:
                    with Catalog.open(self.server.catalog) as catalog:
                        before = catalog.source_state()
                    result, _ = run_authored(self.server.catalog, request, body["policy"])
                    with Catalog.open(self.server.catalog) as catalog:
                        after = catalog.source_state()
                        if before == after and result['plan_origin'] == 'authored':
                            try:
                                bundle = export_authored(catalog, result, body['policy'], after)
                                run_id = catalog.save_authored_run(bundle, after)
                            except CatalogStateChanged:
                                after = catalog.source_state()
                if before != after:
                    result["status"], result["outcome"] = "deferred", None
                    result["reasons"] = list(result["reasons"]) + ["catalog_changed_during_run"]
                self._reply(200, {"kind": "deterministic", "result": result,
                                  "source_state_before": before, "source_state_after": after, "run_id": run_id})
        except CatalogStateChanged:
            self._reply(409, {"error": "source state changed; rerun before creating draft"})
            return
        except (ValueError, TypeError, KeyError, UnicodeError, ContractError, ArithmeticError, re.error):
            self._reply(400, {"error": "invalid request"})
            return
        except sqlite3.Error:
            self._reply(500, {"error": "local storage failure"})
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
        entries = index_entries(revision)
        with self.server.writer_lock, Catalog.open(self.server.catalog) as catalog:
            created = catalog.import_snapshot(revision, entries, row)
        return {"source_id": revision.source_id, "revision_id": revision.revision_id, "entries": len(entries)}, created


def create_server(catalog: str | Path, *, host: str = "127.0.0.1", port: int = 8766) -> LocalServer:
    if host != "127.0.0.1" or type(port) is not int or not 0 <= port <= 65535:
        raise ContractError("service requires IPv4 loopback and a valid port")
    path = Path(catalog)
    with Catalog.open(path):
        pass
    return LocalServer(path, (host, port))
