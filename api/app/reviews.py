"""Human approvals scoped to a single accepted upload and exact private content."""

import base64
import sqlite3
from secrets import token_hex

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from api.app.contracts import Case, ProgressEvent
from api.app.store import Store, get_case, save_case
from judge.pipeline import ReviewRequest, ReviewRequired, ReviewStage

review_router = APIRouter(prefix="/shop/cases/{id}/review")


class ReviewIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    stage: ReviewStage
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReviewImage(BaseModel):
    name: str
    jpeg_base64: str = Field(repr=False)


class PendingReview(ReviewIdentity):
    text: str = Field(repr=False)
    images: list[ReviewImage] = Field(repr=False)


def initialize_reviews(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS review_uploads "
        "(case_id TEXT PRIMARY KEY, upload_id TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS pending_reviews (case_id TEXT PRIMARY KEY, body TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS review_approvals "
        "(case_id TEXT, stage TEXT, fingerprint TEXT, "
        "PRIMARY KEY(case_id, stage, fingerprint))"
    )


def clear_reviews(db: sqlite3.Connection, case_id: str) -> None:
    db.execute("DELETE FROM review_approvals WHERE case_id=?", (case_id,))
    db.execute("DELETE FROM pending_reviews WHERE case_id=?", (case_id,))
    db.execute("DELETE FROM review_uploads WHERE case_id=?", (case_id,))


def reset_reviews(db: sqlite3.Connection, case_id: str) -> None:
    clear_reviews(db, case_id)
    db.execute("INSERT INTO review_uploads VALUES (?, ?)", (case_id, token_hex(16)))


def require_approval(store: Store, case_id: str, request: ReviewRequest) -> bool:
    fingerprint = request.fingerprint
    with store.transaction() as db:
        if get_case(db, case_id).status != "checking":
            raise ValueError("The case is no longer being checked.")
        row = db.execute(
            "SELECT upload_id FROM review_uploads WHERE case_id=?", (case_id,)
        ).fetchone()
        if row is None:
            # Adopt a checking upload created before the review tables existed.
            upload_id = token_hex(16)
            db.execute("INSERT INTO review_uploads VALUES (?, ?)", (case_id, upload_id))
        else:
            upload_id = row[0]
        approved = db.execute(
            "SELECT 1 FROM review_approvals WHERE case_id=? AND stage=? AND fingerprint=?",
            (case_id, request.stage, fingerprint),
        ).fetchone()
        if approved is not None:
            return True
        pending = PendingReview(
            upload_id=upload_id,
            stage=request.stage,
            fingerprint=fingerprint,
            text=request.text,
            images=[
                ReviewImage(name=name, jpeg_base64=base64.b64encode(image).decode("ascii"))
                for name, image in request.images
            ],
        )
        db.execute(
            "INSERT OR REPLACE INTO pending_reviews VALUES (?, ?)",
            (case_id, pending.model_dump_json()),
        )
    # Commit the preview before pausing the job.
    raise ReviewRequired(request.stage)


def _pending(db: sqlite3.Connection, case_id: str) -> PendingReview | None:
    row = db.execute("SELECT body FROM pending_reviews WHERE case_id=?", (case_id,)).fetchone()
    return PendingReview.model_validate_json(row[0]) if row is not None else None


def _match_pending(db: sqlite3.Connection, case_id: str, identity: ReviewIdentity) -> Case:
    case = get_case(db, case_id)
    pending = _pending(db, case_id)
    if (
        case.status != "checking"
        or pending is None
        or (pending.upload_id, pending.stage, pending.fingerprint)
        != (identity.upload_id, identity.stage, identity.fingerprint)
    ):
        raise HTTPException(409, "This review is no longer pending for the active upload.")
    return case


@review_router.get("")
def pending_review(id: str, request: Request, response: Response) -> PendingReview:
    with request.app.state.runner.store.connection() as db:
        get_case(db, id)
        pending = _pending(db, id)
    if pending is None:
        raise HTTPException(404, "No review is pending for this case.")
    response.headers["Cache-Control"] = "private, no-store"
    return pending


@review_router.post("/approve", status_code=204)
def approve(id: str, approval: ReviewIdentity, request: Request) -> Response:
    runner = request.app.state.runner
    with runner.store.transaction() as db:
        _match_pending(db, id, approval)
        db.execute(
            "INSERT INTO review_approvals VALUES (?, ?, ?)",
            (id, approval.stage, approval.fingerprint),
        )
        db.execute("DELETE FROM pending_reviews WHERE case_id=?", (id,))
    runner.resume(id)
    return Response(status_code=204)


@review_router.post("/decline", status_code=204)
def decline(id: str, identity: ReviewIdentity, request: Request) -> Response:
    with request.app.state.runner.store.transaction() as db:
        case = _match_pending(db, id, identity)
        case.status = "failed"
        case.progress.append(ProgressEvent(event="done"))
        save_case(db, case)
        clear_reviews(db, id)
    return Response(status_code=204)
