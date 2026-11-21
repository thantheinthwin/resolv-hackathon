"""Local SQLite persistence. Each transaction uses its own connection."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from fastapi import HTTPException

from api.app.contracts import Case


class Store:
    def __init__(self, root: Path):
        self.root = root

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS initialized (name TEXT PRIMARY KEY)")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.root / "cases.sqlite3", timeout=10)) as db:
            yield db

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db


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
