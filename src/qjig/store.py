"""SQLite catalog of immutable source revisions. One owner process; opened explicitly."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .contracts import ContractError
from .sources import SourceRevision, decode_source

SCHEMA_VERSION = 1

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


class Catalog:
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    @classmethod
    def open(cls, path: str | Path) -> "Catalog":
        con = sqlite3.connect(str(path))
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            con.executescript(_SCHEMA + f"PRAGMA user_version = {SCHEMA_VERSION};")
        elif version != SCHEMA_VERSION:
            con.close()
            raise ContractError(f"unsupported catalog schema version {version}")
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
