"""Shared Team Activity coordinator. Run one instance per project."""

import hashlib
import hmac
import json
import os
import sqlite3
import time
import unicodedata
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field, StringConstraints, field_validator

LEASE_SECONDS = 15 * 60
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Scope = Annotated[str, StringConstraints(min_length=1, max_length=500)]


class Claim(BaseModel):
    member: Label
    agent: Label
    task: Label
    branch: Label
    paths: list[Scope] = Field(min_length=1, max_length=64)

    @field_validator("paths")
    @classmethod
    def canonical_paths(cls, paths: list[str]) -> list[str]:
        result = set()
        for raw in paths:
            path = PurePosixPath(raw)
            if (
                not raw.strip()
                or path.is_absolute()
                or ".." in path.parts
                or any(c in raw for c in "\\:*?[]")
                or any(ord(c) < 32 for c in raw)
            ):
                raise ValueError("Use literal repository-relative POSIX paths")
            result.add(str(path))
        return sorted(result)


class Activity(Claim):
    expires_at: int


def overlaps(left: str, right: str) -> bool:
    # The team edits from both case-sensitive and case-insensitive filesystems.
    a, b = (PurePosixPath(unicodedata.normalize("NFC", path).casefold()) for path in (left, right))
    return a.is_relative_to(b) or b.is_relative_to(a)


def create_app() -> FastAPI:
    token = os.environ["TEAM_ACTIVITY_TOKEN"]
    if len(token) < 32 or not all(33 <= ord(c) <= 126 for c in token):
        raise ValueError("TEAM_ACTIVITY_TOKEN requires at least 32 visible ASCII characters")
    db_path = Path(os.environ.get("TEAM_ACTIVITY_DB", "data/team-activity.sqlite3"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS leases (id TEXT PRIMARY KEY, body TEXT, ends INTEGER)"
        )

    def authorize(authorization: Annotated[str, Header()] = "") -> None:
        if not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
            raise HTTPException(401, "Invalid team credential")

    def lease_id(x_activity_session: Annotated[str, Header(min_length=32, max_length=128)]) -> str:
        return hashlib.sha256(x_activity_session.encode()).hexdigest()

    @contextmanager
    def write() -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM leases WHERE ends <= ?", (int(time.time()),))
            yield db

    app = FastAPI(dependencies=[Depends(authorize)])

    @app.get("/activity")
    def activity(response: Response) -> list[Activity]:
        response.headers["Cache-Control"] = "no-store"
        with closing(sqlite3.connect(db_path)) as db:
            rows = db.execute(
                "SELECT body, ends FROM leases WHERE ends > ? ORDER BY id", (int(time.time()),)
            )
            return [Activity(**json.loads(body), expires_at=ends) for body, ends in rows]

    @app.put("/claim")
    def claim(body: Claim, session: Annotated[str, Depends(lease_id)]) -> Activity:
        with write() as db:
            for (existing,) in db.execute("SELECT body FROM leases WHERE id != ?", (session,)):
                existing_claim = Claim.model_validate_json(existing)
                if any(overlaps(a, b) for a in body.paths for b in existing_claim.paths):
                    raise HTTPException(409, {"conflicting_claim": existing_claim.model_dump()})
            ends = int(time.time()) + LEASE_SECONDS
            db.execute(
                "INSERT OR REPLACE INTO leases VALUES (?, ?, ?)",
                (session, body.model_dump_json(), ends),
            )
        return Activity(**body.model_dump(), expires_at=ends)

    @app.post("/heartbeat")
    def heartbeat(session: Annotated[str, Depends(lease_id)]) -> dict[str, int]:
        with write() as db:
            ends = int(time.time()) + LEASE_SECONDS
            if not db.execute("UPDATE leases SET ends=? WHERE id=?", (ends, session)).rowcount:
                raise HTTPException(
                    404, "Claim expired or released. Claim paths again before editing."
                )
        return {"expires_at": ends}

    @app.delete("/claim", status_code=204)
    def release(session: Annotated[str, Depends(lease_id)]) -> Response:
        with write() as db:
            db.execute("DELETE FROM leases WHERE id=?", (session,))
        return Response(status_code=204)

    return app
