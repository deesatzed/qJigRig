"""SQLite catalog of immutable source revisions. One owner process; opened explicitly."""
from __future__ import annotations

import sqlite3
import hashlib
import json
from pathlib import Path

from .contracts import ContractError
from .sources import SourceRevision, decode_source

SCHEMA_VERSION = 8


class CatalogStateChanged(ContractError):
    """The catalog changed before a bound record could be committed."""

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

_INTERVENTION_SCHEMA = """
CREATE TABLE interventions(intervention_id TEXT PRIMARY KEY, parent_revision_id TEXT NOT NULL, child_revision_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TRIGGER interventions_no_update BEFORE UPDATE ON interventions
  BEGIN SELECT RAISE(ABORT, 'interventions are immutable'); END;
CREATE TRIGGER interventions_no_delete BEFORE DELETE ON interventions
  BEGIN SELECT RAISE(ABORT, 'interventions are immutable'); END;
"""

_RUN_SCHEMA = """
CREATE TABLE authored_runs(run_id TEXT PRIMARY KEY, bundle TEXT NOT NULL);
CREATE TRIGGER authored_runs_no_update BEFORE UPDATE ON authored_runs
  BEGIN SELECT RAISE(ABORT, 'authored runs are immutable'); END;
CREATE TRIGGER authored_runs_no_delete BEFORE DELETE ON authored_runs
  BEGIN SELECT RAISE(ABORT, 'authored runs are immutable'); END;
"""

_REVIEW_SCHEMA = """
CREATE TABLE program_reviews(review_id TEXT PRIMARY KEY, record TEXT NOT NULL);
CREATE TRIGGER program_reviews_no_update BEFORE UPDATE ON program_reviews
  BEGIN SELECT RAISE(ABORT, 'program reviews are immutable'); END;
CREATE TRIGGER program_reviews_no_delete BEFORE DELETE ON program_reviews
  BEGIN SELECT RAISE(ABORT, 'program reviews are immutable'); END;
"""

_PROGRAM_SCHEMA = """
CREATE TABLE program_drafts(draft_id TEXT PRIMARY KEY, record TEXT NOT NULL);
CREATE TRIGGER program_drafts_no_update BEFORE UPDATE ON program_drafts
  BEGIN SELECT RAISE(ABORT, 'program drafts are immutable'); END;
CREATE TRIGGER program_drafts_no_delete BEFORE DELETE ON program_drafts
  BEGIN SELECT RAISE(ABORT, 'program drafts are immutable'); END;
CREATE TABLE program_review_links(draft_id TEXT NOT NULL REFERENCES program_drafts(draft_id), review_id TEXT NOT NULL REFERENCES program_reviews(review_id), PRIMARY KEY(draft_id, review_id));
CREATE TRIGGER program_review_links_no_update BEFORE UPDATE ON program_review_links
  BEGIN SELECT RAISE(ABORT, 'program review links are immutable'); END;
CREATE TRIGGER program_review_links_no_delete BEFORE DELETE ON program_review_links
  BEGIN SELECT RAISE(ABORT, 'program review links are immutable'); END;
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
                scripts = {0: _SCHEMA + _INDEX_SCHEMA + _METADATA_SCHEMA + _CLAIM_SCHEMA + _INTERVENTION_SCHEMA + _RUN_SCHEMA + _REVIEW_SCHEMA + _PROGRAM_SCHEMA,
                           1: _INDEX_SCHEMA + _METADATA_SCHEMA + _CLAIM_SCHEMA + _INTERVENTION_SCHEMA + _RUN_SCHEMA + _REVIEW_SCHEMA + _PROGRAM_SCHEMA,
                           2: _METADATA_SCHEMA + _CLAIM_SCHEMA + _INTERVENTION_SCHEMA + _RUN_SCHEMA + _REVIEW_SCHEMA + _PROGRAM_SCHEMA,
                           3: _CLAIM_SCHEMA + _INTERVENTION_SCHEMA + _RUN_SCHEMA + _REVIEW_SCHEMA + _PROGRAM_SCHEMA, 4: _INTERVENTION_SCHEMA + _RUN_SCHEMA + _REVIEW_SCHEMA + _PROGRAM_SCHEMA,
                           5: _RUN_SCHEMA + _REVIEW_SCHEMA + _PROGRAM_SCHEMA, 6: _REVIEW_SCHEMA + _PROGRAM_SCHEMA, 7: _PROGRAM_SCHEMA}
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

    def import_snapshot(self, revision: SourceRevision, entries: list, metadata: tuple, *, parent_link: tuple | None = None) -> bool:
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
            if parent_link is not None:
                ident, parent, child, payload = parent_link
                if child != revision.revision_id or self.get_revision(parent).source_id != revision.source_id:
                    raise ContractError("invalid intervention linkage")
                saved = self._con.execute("SELECT intervention_id,parent_revision_id,child_revision_id,payload FROM interventions WHERE intervention_id=?", (ident,)).fetchone()
                if saved is not None:
                    if saved != parent_link:
                        raise ContractError("intervention identity conflict")
                    self._con.commit()
                    return False
                active = self._con.execute("SELECT DISTINCT revision_id FROM index_entries WHERE state IN ('proposed','accepted') AND revision_id IN (SELECT revision_id FROM revisions WHERE source_id=?)", (revision.source_id,)).fetchall()
                if active != [(parent,)]:
                    raise ContractError("intervention parent is not current")
            existing = self._con.execute("SELECT * FROM member_metadata WHERE revision_id=?", (revision.revision_id,)).fetchone()
            if existing is not None:
                if parent_link is not None:
                    raise ContractError("intervention child already exists")
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
            if parent_link is not None:
                self._con.execute("INSERT INTO interventions VALUES (?,?,?,?)", parent_link)
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

    def source_state(self) -> str:
        """Hash a consistent catalog snapshot of source, index and metadata rows."""
        self._con.execute("BEGIN")
        try:
            state = self._source_state_in_transaction()
            self._con.commit()
        except BaseException:
            self._con.rollback()
            raise
        return state

    def _source_state_in_transaction(self) -> str:
        revisions = self._con.execute("SELECT revision_id,source_id FROM revisions ORDER BY revision_id").fetchall()
        entries = self._con.execute(f"SELECT {self._ENTRY_COLS} FROM index_entries ORDER BY entry_id").fetchall()
        metadata = self._con.execute("SELECT * FROM member_metadata ORDER BY revision_id").fetchall()
        data = json.dumps({"revisions": revisions, "entries": entries, "metadata": metadata},
                          sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    def save_authored_run(self, bundle: dict, expected_source_state: str) -> str:
        """Commit a validated bundle only while its source-catalog binding holds."""
        from .export import verify_authored_export
        if verify_authored_export(bundle)['status'] != 'unanchored' or bundle['payload']['source_state'] != expected_source_state:
            raise ContractError('invalid authored run bundle')
        run_id = bundle['sha256']
        data = json.dumps(bundle, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        self._con.execute('BEGIN IMMEDIATE')
        try:
            if self._source_state_in_transaction() != expected_source_state:
                raise CatalogStateChanged('catalog changed before run storage')
            self._con.execute('INSERT OR IGNORE INTO authored_runs VALUES (?,?)', (run_id, data))
            if self._con.execute('SELECT bundle FROM authored_runs WHERE run_id=?', (run_id,)).fetchone()[0] != data:
                raise ContractError('run identity collision')
            self._con.commit()
            return run_id
        except BaseException:
            self._con.rollback()
            raise

    def authored_run_rows(self) -> list[tuple[str, str]]:
        return self._con.execute('SELECT run_id,bundle FROM authored_runs ORDER BY run_id').fetchall()

    def authored_run_row(self, run_id: str) -> str | None:
        row = self._con.execute('SELECT bundle FROM authored_runs WHERE run_id=?', (run_id,)).fetchone()
        return None if row is None else row[0]

    def _check_program_sources(self, binding: dict) -> None:
        rows = {row[0]: row for row in self.metadata_rows()}
        for revision in binding['corpus_revision_ids']:
            try:
                self.get_revision(revision)
                row = rows[revision]
                metadata = {'scope': row[1], 'authority_id': row[2], 'entity_keys': sorted(json.loads(row[3])),
                            'effective_start': row[4], 'effective_end': row[5], 'observed_at': row[6]}
            except (KeyError, ValueError, TypeError) as exc:
                raise ContractError('program source or metadata unavailable') from exc
            if metadata != binding['source_metadata'][revision]:
                raise ContractError('program source metadata differs')

    def save_program_review(self, record: dict, expected_source_state: str) -> str:
        """Persist an unvalidated review bound to intact local revisions and metadata."""
        from .programs import verify_review
        try:
            payload = record['payload']
            if verify_review(record, payload['binding'], payload['reviewer'])['status'] != 'matching_unvalidated':
                raise ContractError('invalid review record')
            data = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            ident = record['sha256']
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError('invalid review record') from exc
        self._con.execute('BEGIN IMMEDIATE')
        try:
            if self._source_state_in_transaction() != expected_source_state:
                raise CatalogStateChanged('catalog changed before review storage')
            self._check_program_sources(payload['binding'])
            self._con.execute('INSERT OR IGNORE INTO program_reviews VALUES (?,?)', (ident, data))
            if self._con.execute('SELECT record FROM program_reviews WHERE review_id=?', (ident,)).fetchone()[0] != data:
                raise ContractError('review identity collision')
            self._con.commit()
            return ident
        except BaseException:
            self._con.rollback()
            raise

    def program_review(self, review_id: str) -> dict | None:
        """Read an immutable record and recheck its content identity."""
        from .programs import verify_review
        row = self._con.execute('SELECT record FROM program_reviews WHERE review_id=?', (review_id,)).fetchone()
        if row is None:
            return None
        try:
            record = json.loads(row[0])
            payload = record['payload']
            if record['sha256'] != review_id or verify_review(record, payload['binding'], payload['reviewer'])['status'] != 'matching_unvalidated':
                raise ContractError('stored review integrity failure')
            return record
        except (ValueError, TypeError, KeyError) as exc:
            raise ContractError('stored review integrity failure') from exc

    def program_review_ids(self) -> list[str]:
        return [row[0] for row in self._con.execute('SELECT review_id FROM program_reviews ORDER BY review_id')]

    def save_reviewed_draft(self, draft: dict, review: dict, expected_source_state: str) -> tuple[str, str]:
        """Atomically save an exact-bound draft, review and link; never activate."""
        from .programs import verify_draft, verify_review
        try:
            binding = draft['payload']['binding']
            if (verify_draft(draft, binding) != 'matching' or
                    verify_review(review, binding, review['payload']['reviewer'])['status'] != 'matching_unvalidated'):
                raise ContractError('draft and review binding differs')
            draft_id, review_id = draft['sha256'], review['sha256']
            draft_data = json.dumps(draft, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            review_data = json.dumps(review, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError('invalid draft or review') from exc
        self._con.execute('BEGIN IMMEDIATE')
        try:
            if self._source_state_in_transaction() != expected_source_state:
                raise CatalogStateChanged('catalog changed before reviewed draft storage')
            self._check_program_sources(binding)
            self._con.execute('INSERT OR IGNORE INTO program_drafts VALUES (?,?)', (draft_id, draft_data))
            self._con.execute('INSERT OR IGNORE INTO program_reviews VALUES (?,?)', (review_id, review_data))
            if (self._con.execute('SELECT record FROM program_drafts WHERE draft_id=?', (draft_id,)).fetchone()[0] != draft_data or
                    self._con.execute('SELECT record FROM program_reviews WHERE review_id=?', (review_id,)).fetchone()[0] != review_data):
                raise ContractError('draft or review identity collision')
            self._con.execute('INSERT OR IGNORE INTO program_review_links VALUES (?,?)', (draft_id, review_id))
            self._con.commit()
            return draft_id, review_id
        except BaseException:
            self._con.rollback()
            raise

    def save_program_draft(self, draft: dict, expected_source_state: str) -> str:
        from .programs import verify_draft
        try:
            if verify_draft(draft, draft['payload']['binding']) != 'matching':
                raise ContractError('invalid draft')
            data = json.dumps(draft, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            ident = draft['sha256']
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError('invalid draft') from exc
        self._con.execute('BEGIN IMMEDIATE')
        try:
            if self._source_state_in_transaction() != expected_source_state:
                raise CatalogStateChanged('catalog changed before draft storage')
            self._check_program_sources(draft['payload']['binding'])
            self._con.execute('INSERT OR IGNORE INTO program_drafts VALUES (?,?)', (ident, data))
            if self._con.execute('SELECT record FROM program_drafts WHERE draft_id=?', (ident,)).fetchone()[0] != data:
                raise ContractError('draft identity collision')
            self._con.commit()
            return ident
        except BaseException:
            self._con.rollback()
            raise

    def program_draft(self, draft_id: str) -> dict | None:
        from .programs import verify_draft
        row = self._con.execute('SELECT record FROM program_drafts WHERE draft_id=?', (draft_id,)).fetchone()
        if row is None:
            return None
        try:
            draft = json.loads(row[0])
            if draft['sha256'] != draft_id or verify_draft(draft, draft['payload']['binding']) != 'matching':
                raise ContractError('stored draft integrity failure')
            return draft
        except (ValueError, TypeError, KeyError) as exc:
            raise ContractError('stored draft integrity failure') from exc

    def link_program_review(self, draft_id: str, review_id: str, expected_source_state: str) -> None:
        from .programs import verify_review
        self._con.execute('BEGIN IMMEDIATE')
        try:
            if self._source_state_in_transaction() != expected_source_state:
                raise CatalogStateChanged('catalog changed before review linking')
            draft, review = self.program_draft(draft_id), self.program_review(review_id)
            if draft is None or review is None:
                raise ContractError('draft or review unavailable')
            binding = draft['payload']['binding']
            self._check_program_sources(binding)
            if verify_review(review, binding, review['payload']['reviewer'])['status'] != 'matching_unvalidated':
                raise ContractError('review binding differs from draft')
            self._con.execute('INSERT OR IGNORE INTO program_review_links VALUES (?,?)', (draft_id, review_id))
            self._con.commit()
        except BaseException:
            self._con.rollback()
            raise

    def program_status(self, draft_id: str, candidate_binding: dict) -> dict:
        """Compare a supplied candidate and local index; does not prove corpus completeness."""
        from .programs import verify_draft, verify_review
        draft = self.program_draft(draft_id)
        if draft is None:
            raise ContractError('draft unavailable')
        match = verify_draft(draft, candidate_binding)
        if match == 'invalid':
            raise ContractError('invalid candidate binding')
        review_ids = [row[0] for row in self._con.execute('SELECT review_id FROM program_review_links WHERE draft_id=? ORDER BY review_id', (draft_id,))]
        for review_id in review_ids:
            review = self.program_review(review_id)
            if review is None or verify_review(review, draft['payload']['binding'], review['payload']['reviewer'])['status'] != 'matching_unvalidated':
                raise ContractError('stored review link invalid')
        freshness = self.program_source_freshness(draft_id)
        status = ('stale' if match == 'stale' or freshness['status'] == 'stale' else
                  'source_state_unknown' if freshness['status'] == 'unknown' else
                  'review_record_linked' if review_ids else 'draft')
        return {'status': status, 'review_ids': review_ids, 'source_freshness': freshness,
                'activation': False, 'semantic_assurance': 'not_assessed'}

    def program_source_freshness(self, draft_id: str) -> dict:
        """Compare against a local catalog snapshot, not external files or source authority."""
        from .applicability import Applicability, ApplicabilityInputs, scope_applicability
        self._con.execute('BEGIN')
        try:
            draft = self.program_draft(draft_id)
            if draft is None:
                raise ContractError('draft unavailable')
            binding = draft['payload']['binding']
            revisions = dict(self._con.execute('SELECT revision_id,source_id FROM revisions').fetchall())
            metadata = {row[0]: row for row in self.metadata_rows()}
            states = {}
            for ident, state in self._con.execute('SELECT revision_id,state FROM index_entries').fetchall():
                states.setdefault(ident, set()).add(state)
            live = {}
            for ident, source in revisions.items():
                if states.get(ident, set()) & {'proposed', 'accepted'}:
                    live.setdefault(source, set()).add(ident)
            bound = set(binding['corpus_revision_ids'])
            bound_sources, stale, unknown = set(), [], []
            for ident in sorted((set(states) | set(metadata)) - set(revisions)):
                unknown.append(f'orphan_catalog_record:{ident}')
            for ident, values in states.items():
                if not values <= {'proposed', 'accepted', 'rejected', 'stale'}:
                    unknown.append(f'invalid_index_state:{ident}')
            for ident in sorted(bound):
                source = revisions.get(ident)
                if source is None or ident not in metadata:
                    unknown.append(f'bound_source_unavailable:{ident}')
                    continue
                if source in bound_sources:
                    unknown.append(f'multiple_bound_revisions:{source}')
                bound_sources.add(source)
                try:
                    self.get_revision(ident)
                    row = metadata[ident]
                    actual = {'scope': row[1], 'authority_id': row[2], 'entity_keys': sorted(json.loads(row[3])),
                              'effective_start': row[4], 'effective_end': row[5], 'observed_at': row[6]}
                except (ContractError, ValueError, TypeError):
                    unknown.append(f'bound_source_invalid:{ident}')
                    continue
                if actual != binding['source_metadata'][ident]:
                    stale.append(f'bound_metadata_changed:{ident}')
                current = live.get(source, set())
                if not current or len(current) > 1:
                    unknown.append(f'current_revision_ambiguous:{source}')
                elif current != {ident}:
                    stale.append(f'bound_revision_superseded:{ident}')
            for ident, source in sorted(revisions.items()):
                if ident in bound:
                    continue
                entry_states = states.get(ident, set())
                if entry_states and entry_states <= {'stale'}:
                    continue
                if source in bound_sources:
                    if not entry_states:
                        unknown.append(f'unindexed_revision:{ident}')
                    continue
                row = metadata.get(ident)
                if row is None:
                    unknown.append(f'source_metadata_unavailable:{ident}')
                    continue
                try:
                    self.get_revision(ident)
                    member = {'revision_id': ident, 'scope': row[1], 'authority_id': row[2],
                              'entity_keys': json.loads(row[3]), 'effective_start': row[4],
                              'effective_end': row[5], 'observed_at': row[6]}
                    inputs = ApplicabilityInputs.from_dict({'as_of': binding['as_of'],
                        'historical_as_known': binding['historical_as_known'], 'request_entities': binding['entities'],
                        'scope_authority_assurance': 'recorded_not_assessed', 'members': [member]})
                    scope = scope_applicability(binding['request']['scope'], row[1])
                    verdict = inputs.verdict(ident)
                except (ContractError, ValueError, TypeError):
                    unknown.append(f'source_metadata_invalid:{ident}')
                    continue
                if Applicability.NO_MATCH in (scope, verdict):
                    continue
                if Applicability.UNKNOWN in (scope, verdict) or not entry_states or not entry_states & {'proposed', 'accepted'}:
                    unknown.append(f'source_applicability_or_index_unknown:{ident}')
                elif len(live.get(source, set())) > 1:
                    unknown.append(f'current_revision_ambiguous:{source}')
                else:
                    stale.append(f'new_applicable_source:{ident}')
            snapshot = self._source_state_in_transaction()
            self._con.commit()
        except BaseException:
            self._con.rollback()
            raise
        return {'status': 'stale' if stale else 'unknown' if unknown else 'matches_local_index',
                'reasons': sorted(set(stale + unknown)), 'source_state': snapshot,
                'activation': False, 'semantic_assurance': 'not_assessed'}

    def put_interpretation(self, claim_id: str, payload: str) -> bool:
        with self._con:
            cursor = self._con.execute("INSERT OR IGNORE INTO agent_interpretations VALUES (?,?)", (claim_id, payload))
            return cursor.rowcount == 1

    def interpretation_rows(self) -> list[tuple[str, str]]:
        return self._con.execute("SELECT claim_id,payload FROM agent_interpretations ORDER BY claim_id").fetchall()

    def intervention_rows(self) -> list[tuple[str, str, str, str]]:
        return self._con.execute("SELECT intervention_id,parent_revision_id,child_revision_id,payload FROM interventions ORDER BY intervention_id").fetchall()
