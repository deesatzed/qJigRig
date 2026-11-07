import sqlite3

import pytest

from qjig.contracts import ContractError
from qjig.sources import SourceRevision, decode_source
from qjig.store import Catalog


def rev(raw: bytes, source_id="p/policy.md", origin="/a/policy.md", encoding="utf-8"):
    return SourceRevision.create(source_id, origin, decode_source(raw, encoding=encoding))


def test_reopen_revision(tmp_path):
    db = tmp_path / "catalog.sqlite"
    old, new = rev(b"limit 10\r\n"), rev("limit 20 é\r\n".encode("latin-1"), encoding="latin-1")
    assert old.revision_id != new.revision_id and old.source_id == new.source_id
    with Catalog.open(db) as cat:
        cat.add_revision(old)
        cat.add_revision(new)
    with Catalog.open(db) as cat:
        got_old, got_new = cat.get_revision(old.revision_id), cat.get_revision(new.revision_id)
        assert got_old == old and got_new == new
        assert got_old.decoded.raw == b"limit 10\r\n"  # raw bytes preserved
        assert got_new.decoded.encoding == "latin-1"
        assert {r.revision_id for r in cat.list_revisions("p/policy.md")} == {old.revision_id, new.revision_id}
        with pytest.raises(KeyError):
            cat.get_revision("rev1:" + "0" * 64)


def test_revisions_cannot_be_overwritten(tmp_path):
    db = tmp_path / "catalog.sqlite"
    first = rev(b"limit 10\n", origin="/a/policy.md")
    moved = rev(b"limit 10\n", origin="/elsewhere/policy.md")
    assert first.revision_id == moved.revision_id
    with Catalog.open(db) as cat:
        cat.add_revision(first)
        cat.add_revision(moved)  # same identity re-imported from another place: idempotent
        assert cat.get_revision(first.revision_id).origin == "/a/policy.md"  # first origin kept
        assert len(cat.list_revisions("p/policy.md")) == 1
    # direct SQL cannot update or delete a stored revision either
    raw = sqlite3.connect(db)
    with pytest.raises(sqlite3.DatabaseError):
        raw.execute("UPDATE revisions SET raw = x'00'")
    with pytest.raises(sqlite3.DatabaseError):
        raw.execute("DELETE FROM revisions")
    raw.close()


def test_tampered_store_is_detected_on_read(tmp_path):
    db = tmp_path / "catalog.sqlite"
    r = rev(b"limit 10\n")
    with Catalog.open(db) as cat:
        cat.add_revision(r)
    raw = sqlite3.connect(db)
    raw.execute("DROP TRIGGER revisions_no_update")
    raw.execute("UPDATE revisions SET raw = ?", (b"limit 99\n",))
    raw.commit()
    raw.close()
    with Catalog.open(db) as cat:
        with pytest.raises(ContractError):
            cat.get_revision(r.revision_id)


def test_unknown_catalog_version_refused(tmp_path):
    db = tmp_path / "catalog.sqlite"
    con = sqlite3.connect(db)
    con.execute("PRAGMA user_version = 99")
    con.commit()
    con.close()
    with pytest.raises(ContractError):
        Catalog.open(db)


def test_version_1_catalog_migrates_to_add_index_table(tmp_path):
    db = tmp_path / "catalog.sqlite"
    r = rev(b"limit 10\n")
    with Catalog.open(db) as cat:
        cat.add_revision(r)
    con = sqlite3.connect(db)
    con.execute("DROP TABLE index_entries")
    con.execute("DROP TABLE member_metadata")
    con.execute("PRAGMA user_version = 1")
    con.commit()
    con.close()
    with Catalog.open(db) as cat:
        assert cat.get_revision(r.revision_id) == r  # old data intact
        assert cat.index_rows(r.revision_id) == []  # new table present
    assert sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0] == 3


def test_version_2_catalog_migrates_to_add_metadata_table(tmp_path):
    db = tmp_path / "catalog.sqlite"
    r = rev(b"limit 10\n")
    with Catalog.open(db) as cat:
        cat.add_revision(r)
    con = sqlite3.connect(db)
    con.execute("DROP TABLE member_metadata")
    con.execute("PRAGMA user_version = 2")
    con.commit()
    con.close()
    with Catalog.open(db) as cat:
        assert cat.get_revision(r.revision_id) == r
        cat.put_metadata_row((r.revision_id, "project", None, "[]", "2026-01-01", "open", None))
        assert len(cat.metadata_rows()) == 1
