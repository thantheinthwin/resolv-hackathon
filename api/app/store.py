"""Local SQLite persistence. Each transaction uses its own connection."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path

from fastapi import HTTPException

from api.app.contracts import Case


class Store:
    def __init__(self, root: Path):
        self.root = root

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Existing installations also store private review previews in this database.
        database = self.root / "cases.sqlite3"
        database.touch(mode=0o600, exist_ok=True)
        database.chmod(0o600)
        for name in ("cases", ".judge-reviews", ".incoming", ".replaced"):
            private_dir = self.root / name
            private_dir.mkdir(exist_ok=True, mode=0o700)
            private_dir.chmod(0o700)
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS listings (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS listing_photos "
                "(path TEXT PRIMARY KEY, mime TEXT NOT NULL, image BLOB NOT NULL)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS initialized (name TEXT PRIMARY KEY)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS upload_links "
                "(case_id TEXT PRIMARY KEY, digest BLOB UNIQUE NOT NULL)"
            )

            db.execute(
                "CREATE TABLE IF NOT EXISTS daily_case_usage "
                "(day TEXT NOT NULL, client TEXT NOT NULL, created INTEGER NOT NULL, "
                "PRIMARY KEY(day, client))"
            )
            if db.execute(
                "INSERT OR IGNORE INTO initialized(name) VALUES ('daily_case_usage')"
            ).rowcount:
                # Older cases have no recorded client, but count toward today's total.
                db.execute(
                    "INSERT INTO daily_case_usage(day, client, created) "
                    "SELECT date('now'), '', COUNT(*) FROM cases "
                    "WHERE id != 'UJ-SAMPLE' AND date(json_extract(body, '$.created_at')) "
                    "= date('now') HAVING COUNT(*) > 0"
                )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.root / "cases.sqlite3", timeout=10)) as db:
            yield db

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db


def consume_case_quota(db: sqlite3.Connection, day: date, client: str) -> None:
    """Charge one accepted creation inside the same write transaction as the case."""
    today = day.isoformat()
    db.execute("DELETE FROM daily_case_usage WHERE day < ?", (today,))
    total, per_client = db.execute(
        "SELECT COALESCE(SUM(created), 0), "
        "COALESCE(SUM(CASE WHEN client = ? THEN created END), 0) "
        "FROM daily_case_usage WHERE day = ?",
        (client, today),
    ).fetchone()
    if total >= 50 or per_client >= 10:
        raise HTTPException(429, "Daily case limit reached. Try again after midnight UTC.")
    db.execute(
        "INSERT INTO daily_case_usage(day, client, created) VALUES (?, ?, 1) "
        "ON CONFLICT(day, client) DO UPDATE SET created = created + 1",
        (today, client),
    )


def get_case(db: sqlite3.Connection, case_id: str) -> Case:
    row = db.execute("SELECT body FROM cases WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Case not found.")
    return Case.model_validate_json(row[0])


def save_case(db: sqlite3.Connection, case: Case) -> None:
    validated = Case.model_validate(case.model_dump())
    db.execute(
        "INSERT OR REPLACE INTO cases VALUES (?, ?)", (validated.id, validated.model_dump_json())
    )


def list_cases(db: sqlite3.Connection) -> list[Case]:
    cases = [Case.model_validate_json(body) for (body,) in db.execute("SELECT body FROM cases")]
    return sorted(cases, key=lambda case: case.created_at, reverse=True)


def case_for_upload_link(db: sqlite3.Connection, digest: bytes) -> str:
    row = db.execute("SELECT case_id FROM upload_links WHERE digest=?", (digest,)).fetchone()
    if row is None:
        raise HTTPException(404, "Upload link is invalid or has already been used.")
    return row[0]
