"""Local SQLite persistence. Each transaction uses its own connection."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from fastapi import HTTPException

from api.app.catalog import initialize_catalog
from api.app.contracts import Case
from api.app.usage import initialize_usage


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class Store:
    def __init__(self, root: Path):
        self.root = root

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            migrations = sorted(MIGRATIONS.glob("*.sql"))
            if version > len(migrations):
                raise RuntimeError("Database schema is newer than this API.")
            for number, path in enumerate(migrations, start=1):
                if int(path.name.split("_", 1)[0]) != number:
                    raise RuntimeError(f"Expected migration {number}, found {path.name}")
                if number <= version:
                    continue
                # executescript would commit the surrounding migration transaction.
                statement = ""
                for line in path.read_text().splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        db.execute(statement)
                        statement = ""
                if statement.strip():
                    raise RuntimeError(f"Incomplete SQL in {path.name}")
                db.execute(f"PRAGMA user_version = {number}")
            initialize_catalog(db)
            initialize_usage(db)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.root / "cases.sqlite3", timeout=10)) as db:
            db.execute("PRAGMA foreign_keys = ON")
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
        "INSERT INTO cases(id, body) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
        (validated.id, validated.model_dump_json()),
    )


def list_cases(db: sqlite3.Connection) -> list[Case]:
    cases = [Case.model_validate_json(body) for (body,) in db.execute("SELECT body FROM cases")]
    return sorted(cases, key=lambda case: case.created_at, reverse=True)


def case_for_upload_link(db: sqlite3.Connection, digest: bytes) -> str:
    row = db.execute("SELECT case_id FROM upload_links WHERE digest=?", (digest,)).fetchone()
    if row is None:
        raise HTTPException(404, "Upload link is invalid or has already been used.")
    return row[0]
