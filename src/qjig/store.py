"""SQLite catalog of immutable source revisions. One owner process; opened explicitly."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .contracts import ContractError
from .sources import SourceRevision, decode_source

SCHEMA_VERSION = 4

_SCHEMA = """
CREATE TABLE revisions(
  revision_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  origin TEXT NOT NULL,
  encoding TEXT NOT NULL,
  raw BLOB NOT NULL
);
CREATE INDEX revisions_source ON revisions(source_id);
CREATE TRIGGER revisions_no_update BEFORE UPDATE ON revisions
  BEGIN SELECT RAISE(ABORT, 'revisions are immutable'); END;
CREATE TRIGGER revisions_no_delete BEFORE DELETE ON revisions
  BEGIN SELECT RAISE(ABORT, 'revisions are immutable'); END;
"""

_INDEX_SCHEMA = """
CREATE TABLE index_entries(
  entry_id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES revisions(revision_id),
  kind TEXT NOT NULL,
  title TEXT,
  method TEXT NOT NULL,
  state TEXT NOT NULL,
  start INTEGER NOT NULL,
  "end" INTEGER NOT NULL,
  text_sha256 TEXT NOT NULL,
  parent_entry_id TEXT
);
CREATE INDEX index_entries_revision ON index_entries(revision_id);
"""

_METADATA_SCHEMA = """
CREATE TABLE member_metadata(
  revision_id TEXT PRIMARY KEY REFERENCES revisions(revision_id),
  scope TEXT NOT NULL,
  authority_id TEXT,
  entity_keys TEXT NOT NULL,
  effective_start TEXT NOT NULL,
  effective_end TEXT NOT NULL,
  observed_at TEXT
);
"""

_CLAIM_SCHEMA = """
CREATE TABLE agent_interpretations(claim_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TRIGGER agent_interpretations_no_update BEFORE UPDATE ON agent_interpretations
  BEGIN SELECT RAISE(ABORT, 'interpretations are immutable'); END;
CREATE TRIGGER agent_interpretations_no_delete BEFORE DELETE ON agent_interpretations
  BEGIN SELECT RAISE(ABORT, 'interpretations are immutable'); END;
"""


def _execute_schema(con: sqlite3.Connection, script: str) -> None:
    """Execute schema statements inside the caller's transaction, including triggers."""
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            con.execute(statement)
            statement = ""
    if statement.strip():
        raise ContractError("incomplete catalog schema statement")


class Catalog:
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    @classmethod
    def open(cls, path: str | Path) -> "Catalog":
        con = sqlite3.connect(str(path))
        try:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                con.execute("BEGIN IMMEDIATE")
                version = con.execute("PRAGMA user_version").fetchone()[0]
                scripts = {0: _SCHEMA + _INDEX_SCHEMA + _METADATA_SCHEMA + _CLAIM_SCHEMA,
                           1: _INDEX_SCHEMA + _METADATA_SCHEMA + _CLAIM_SCHEMA,
                           2: _METADATA_SCHEMA + _CLAIM_SCHEMA, 3: _CLAIM_SCHEMA}
                if version == SCHEMA_VERSION:
                    pass  # another opener completed the migration while we waited
                elif version in scripts:
                    _execute_schema(con, scripts[version])
                    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                else:
                    raise ContractError(f"unsupported catalog schema version {version}")
                con.commit()
        except BaseException:
            con.rollback()
            con.close()
            raise
        return cls(con)

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "Catalog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def add_revision(self, revision: SourceRevision) -> None:
        """Store a revision. Re-adding the same revision_id is a no-op that keeps the first origin."""
        with self._con:
            self._con.execute(
                "INSERT OR IGNORE INTO revisions(revision_id, source_id, origin, encoding, raw) "
                "VALUES (?,?,?,?,?)",
                (
                    revision.revision_id,
                    revision.source_id,
                    revision.origin,
                    revision.decoded.encoding,
                    revision.decoded.raw,
                ),
            )

    def import_snapshot(self, revision: SourceRevision, entries: list, metadata: tuple) -> bool:
        """Atomically add one service snapshot, including indexes and supersession."""
        from .spans import verify_span
        if not isinstance(revision, SourceRevision) or len(metadata) != 7 or metadata[0] != revision.revision_id:
            raise ContractError("invalid snapshot metadata")
        rows = []
        for e in entries:
            if e.revision_id != revision.revision_id:
                raise ContractError("index belongs to another revision")
            verify_span(revision, e.span)
            rows.append((e.entry_id, e.revision_id, e.kind, e.title, e.method, e.state,
                         e.span.start, e.span.end, e.span.text_sha256, e.parent_entry_id))
        self._con.execute("BEGIN IMMEDIATE")
        try:
            existing = self._con.execute("SELECT * FROM member_metadata WHERE revision_id=?", (revision.revision_id,)).fetchone()
            if existing is not None:
                if existing != metadata:
                    raise ContractError("revision metadata conflict")
                self.get_revision(revision.revision_id)
                self._con.commit()
                return False
            self._con.execute("INSERT OR IGNORE INTO revisions(revision_id,source_id,origin,encoding,raw) VALUES(?,?,?,?,?)",
                              (revision.revision_id, revision.source_id, revision.origin, revision.decoded.encoding, revision.decoded.raw))
            self.get_revision(revision.revision_id)
            for row in rows:
                present = self.index_row(row[0])
                if present is not None and present != row:
                    raise ContractError("existing snapshot index differs")
                self._con.execute(f"INSERT OR IGNORE INTO index_entries({self._ENTRY_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?)", row)
            self._con.execute("UPDATE index_entries SET state='stale' WHERE state IN ('proposed','accepted') AND revision_id != ? AND revision_id IN (SELECT revision_id FROM revisions WHERE source_id=?)", (revision.revision_id, revision.source_id))
            self._con.execute("INSERT INTO member_metadata VALUES (?,?,?,?,?,?,?)", metadata)
            self._con.commit()
            return True
        except BaseException:
            self._con.rollback()
            raise

    def _load(self, row: tuple) -> SourceRevision:
        revision_id, source_id, origin, encoding, raw = row
        rebuilt = SourceRevision.create(source_id, origin, decode_source(bytes(raw), encoding=encoding))
        if rebuilt.revision_id != revision_id:
            raise ContractError(f"stored revision {revision_id} no longer matches its content")
        return rebuilt

    def get_revision(self, revision_id: str) -> SourceRevision:
        row = self._con.execute(
            "SELECT revision_id, source_id, origin, encoding, raw FROM revisions WHERE revision_id=?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise KeyError(revision_id)
        return self._load(row)

    def list_revisions(self, source_id: str) -> list[SourceRevision]:
        rows = self._con.execute(
            "SELECT revision_id, source_id, origin, encoding, raw FROM revisions "
            "WHERE source_id=? ORDER BY revision_id",
            (source_id,),
        ).fetchall()
        return [self._load(r) for r in rows]

    # Derived index rows. Source text is never copied here; spans are re-sliced from the revision.
    _ENTRY_COLS = "entry_id, revision_id, kind, title, method, state, start, \"end\", text_sha256, parent_entry_id"

    def has_revision(self, revision_id: str) -> bool:
        return self._con.execute("SELECT 1 FROM revisions WHERE revision_id=?", (revision_id,)).fetchone() is not None

    def put_index_rows(self, rows: list[tuple]) -> None:
        with self._con:
            self._con.executemany(
                f"INSERT OR IGNORE INTO index_entries({self._ENTRY_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?)", rows
            )

    def index_rows(self, revision_id: str) -> list[tuple]:
        return self._con.execute(
            f"SELECT {self._ENTRY_COLS} FROM index_entries WHERE revision_id=? ORDER BY start, \"end\", entry_id",
            (revision_id,),
        ).fetchall()

    def index_row(self, entry_id: str) -> tuple | None:
        return self._con.execute(
            f"SELECT {self._ENTRY_COLS} FROM index_entries WHERE entry_id=?", (entry_id,)
        ).fetchone()

    def stale_other_revisions(self, source_id: str, keep_revision_id: str) -> int:
        """Mark live (proposed/accepted) entries of this source's other revisions as stale."""
        with self._con:
            cur = self._con.execute(
                "UPDATE index_entries SET state='stale' WHERE state IN ('proposed','accepted') "
                "AND revision_id != ? AND revision_id IN (SELECT revision_id FROM revisions WHERE source_id=?)",
                (keep_revision_id, source_id),
            )
        return cur.rowcount

    def revision_source_id(self, revision_id: str) -> str | None:
        row = self._con.execute("SELECT source_id FROM revisions WHERE revision_id=?", (revision_id,)).fetchone()
        return row[0] if row else None

    def live_index_rows(self) -> list[tuple]:
        return self._con.execute(
            f"SELECT {self._ENTRY_COLS} FROM index_entries WHERE state IN ('proposed','accepted') "
            "ORDER BY revision_id, start, \"end\", entry_id"
        ).fetchall()

    def put_metadata_row(self, row: tuple) -> None:
        """row = (revision_id, scope, authority_id, entity_keys_json, start, end, observed_at). First write wins."""
        with self._con:
            self._con.execute("INSERT OR IGNORE INTO member_metadata VALUES (?,?,?,?,?,?,?)", row)

    def metadata_rows(self) -> list[tuple]:
        return self._con.execute("SELECT * FROM member_metadata ORDER BY revision_id").fetchall()

    def revision_ids(self) -> list[str]:
        return [r[0] for r in self._con.execute("SELECT revision_id FROM revisions ORDER BY revision_id")]

    def put_interpretation(self, claim_id: str, payload: str) -> bool:
        with self._con:
            cursor = self._con.execute("INSERT OR IGNORE INTO agent_interpretations VALUES (?,?)", (claim_id, payload))
            return cursor.rowcount == 1

    def interpretation_rows(self) -> list[tuple[str, str]]:
        return self._con.execute("SELECT claim_id,payload FROM agent_interpretations ORDER BY claim_id").fetchall()
