"""Incremental local run archive. Inputs must already be non-sensitive and sanitized.

Never pass credentials or authorization headers to this archive. The archive retains
raw source and response content, and belongs in an ignored local run directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

from .contracts import ContractError
from .providers import ProviderRequest, RawResponse
from .sources import SourceRevision, _check_source_id, decode_source


class RunArchive:
    def __init__(self, con: sqlite3.Connection):
        self._con = con

    @classmethod
    def open(cls, directory: str | Path) -> "RunArchive":
        path = Path(directory)
        if path.is_symlink():
            raise ContractError("run directory must not be a symlink")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        db = path / "run.sqlite"
        if db.is_symlink():
            raise ContractError("run archive must not be a symlink")
        con = sqlite3.connect(str(db), isolation_level=None)
        try:
            os.chmod(db, 0o600)
            con.executescript('''
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS sources(source_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, raw BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(revision_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, origin TEXT NOT NULL, encoding TEXT NOT NULL, raw BLOB NOT NULL);
                CREATE TRIGGER IF NOT EXISTS revision_no_update BEFORE UPDATE ON revisions BEGIN SELECT RAISE(ABORT, 'immutable revision'); END;
                CREATE TRIGGER IF NOT EXISTS revision_no_delete BEFORE DELETE ON revisions BEGIN SELECT RAISE(ABORT, 'immutable revision'); END;
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, call_id TEXT NOT NULL,
                                                  data TEXT NOT NULL, recorded_at REAL NOT NULL, UNIQUE(kind, call_id));
                CREATE TRIGGER IF NOT EXISTS source_no_update BEFORE UPDATE ON sources BEGIN SELECT RAISE(ABORT, 'immutable source'); END;
                CREATE TRIGGER IF NOT EXISTS source_no_delete BEFORE DELETE ON sources BEGIN SELECT RAISE(ABORT, 'immutable source'); END;
                CREATE TRIGGER IF NOT EXISTS event_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'immutable event'); END;
                CREATE TRIGGER IF NOT EXISTS event_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'immutable event'); END;
            ''')
        except BaseException:
            con.close()
            raise
        return cls(con)

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "RunArchive":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def add_source(self, source_id: str, raw: bytes) -> str:
        _check_source_id(source_id)
        if not isinstance(raw, bytes):
            raise ContractError("source snapshot must be bytes")
        digest = hashlib.sha256(raw).hexdigest()
        row = self._con.execute("SELECT sha256,raw FROM sources WHERE source_id=?", (source_id,)).fetchone()
        if row is not None:
            if row != (digest, raw):
                raise ContractError("source identity already bound to different bytes")
            return digest
        self._con.execute("INSERT INTO sources VALUES(?,?,?)", (source_id, digest, raw))
        return digest

    def source(self, source_id: str) -> bytes:
        row = self._con.execute("SELECT sha256,raw FROM sources WHERE source_id=?", (source_id,)).fetchone()
        if row is None:
            raise KeyError(source_id)
        if hashlib.sha256(row[1]).hexdigest() != row[0]:
            raise ContractError("source snapshot hash mismatch")
        return row[1]

    def add_revision(self, revision: SourceRevision) -> None:
        if not isinstance(revision, SourceRevision):
            raise ContractError("source revision required")
        rebuilt = SourceRevision.create(revision.source_id, revision.origin,
                                        decode_source(revision.decoded.raw, encoding=revision.decoded.encoding))
        if rebuilt != revision:
            raise ContractError("source revision identity does not match bytes and decoding")
        row = self._con.execute("SELECT source_id,origin,encoding,raw FROM revisions WHERE revision_id=?", (revision.revision_id,)).fetchone()
        values = (revision.source_id, revision.origin, revision.decoded.encoding, revision.decoded.raw)
        if row is not None:
            if row != values:
                raise ContractError("revision already bound to different provenance")
            return
        self._con.execute("INSERT INTO revisions VALUES(?,?,?,?,?)", (revision.revision_id, *values))

    def revision(self, revision_id: str) -> SourceRevision:
        row = self._con.execute("SELECT source_id,origin,encoding,raw FROM revisions WHERE revision_id=?", (revision_id,)).fetchone()
        if row is None:
            raise KeyError(revision_id)
        source_id, origin, encoding, raw = row
        revision = SourceRevision.create(source_id, origin, decode_source(raw, encoding=encoding))
        revision.require_pin(revision_id)
        return revision

    def _event(self, kind: str, call_id: str, data: dict) -> None:
        if not isinstance(call_id, str) or not call_id.strip():
            raise ContractError("call id is required")
        encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False)
        self._con.execute("INSERT INTO events(kind,call_id,data,recorded_at) VALUES(?,?,?,?)", (kind, call_id, encoded, time.time()))

    def record_request(self, call_id: str, request: ProviderRequest) -> None:
        self._event("request", call_id, {"stage": request.stage, "provider": request.provider, "model": request.model,
                                          "prompt": request.prompt, "max_tokens": request.max_tokens,
                                          "input_sha256": request.input_sha256()})

    def record_response(self, call_id: str, response: RawResponse) -> None:
        if not self._con.execute("SELECT 1 FROM events WHERE kind='request' AND call_id=?", (call_id,)).fetchone():
            raise ContractError("response has no recorded request")
        self._event("response", call_id, {"http_status": response.http_status, "body": response.body,
                                           "body_sha256": hashlib.sha256(response.body.encode("utf-8")).hexdigest(),
                                           "usage": response.usage, "note": response.note})

    def record_validation(self, call_id: str, value: dict | None, failure: str | None) -> None:
        if not self._con.execute("SELECT 1 FROM events WHERE kind='response' AND call_id=?", (call_id,)).fetchone():
            raise ContractError("validation has no recorded response")
        self._event("validation", call_id, {"value": value, "failure": failure})

    def record_failure(self, call_id: str, failure: str) -> None:
        if not self._con.execute("SELECT 1 FROM events WHERE kind='request' AND call_id=?", (call_id,)).fetchone():
            raise ContractError("failure has no recorded request")
        self._event("failure", call_id, {"failure": failure})

    def events(self) -> list[dict]:
        rows = self._con.execute("SELECT seq,kind,call_id,data,recorded_at FROM events ORDER BY seq").fetchall()
        return [{"seq": r[0], "kind": r[1], "call_id": r[2], "data": json.loads(r[3]), "recorded_at": r[4]} for r in rows]
