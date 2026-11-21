import sqlite3
from pathlib import Path

import pytest

from api.app.store import Store


def test_failed_upgrade_preserves_unversioned_catalog(tmp_path: Path) -> None:
    store = Store(tmp_path)
    with store.transaction() as db:
        db.execute("CREATE TABLE listings (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        db.execute("INSERT INTO listings VALUES ('bad', '{}')")
    with pytest.raises(sqlite3.IntegrityError):
        store.initialize()
    with store.connection() as db:
        assert db.execute("PRAGMA user_version").fetchone() == (0,)
        assert db.execute("SELECT * FROM listings").fetchall() == [("bad", "{}")]
        assert not db.execute("SELECT 1 FROM sqlite_schema WHERE name='products'").fetchone()


def test_newer_database_is_preserved(tmp_path: Path) -> None:
    store = Store(tmp_path)
    with store.transaction() as db:
        db.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="newer"):
        store.initialize()
    with store.connection() as db:
        assert db.execute("PRAGMA user_version").fetchone() == (999,)
        assert not db.execute("SELECT 1 FROM sqlite_schema").fetchone()
