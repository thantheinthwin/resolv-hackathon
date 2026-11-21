"""First-hour API: a persistent sample case and typed integration boundaries."""

import hmac
import os
import shutil
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Response,
)
from pydantic import BaseModel
from fastapi.responses import FileResponse, StreamingResponse

from api.app.contracts import Case, Decision, Listing, ProgressEvent
from api.app.fake import FakeJudge, Judge
from api.app.sample import LISTING, ORDER, OrderWithListing
from api.app.store import Store, get_case, list_cases, save_case
from api.app.views import (
    BuyerCase,
    CreatedCase,
    CreateCase,
    ErrorDetail,
    ListingForm,
    VideoForm,
    ShopSummary,
    UploadLink,
    UploadResult,
    buyer_view,
)


def multipart(form: type[BaseModel]) -> dict[str, object]:
    """Document a future form without parsing or spooling requests to the placeholder."""
    return {
        "requestBody": {
            "required": True,
            "content": {"multipart/form-data": {"schema": form.model_json_schema()}},
        }
    }


def authorize(x_demo_passcode: Annotated[str, Header()]) -> None:
    expected = os.environ.get("DEMO_PASSCODE")
    if not expected:
        raise HTTPException(503, "Demo access is not configured.")
    if not hmac.compare_digest(expected.encode(), x_demo_passcode.encode()):
        raise HTTPException(403, "Invalid demo passcode.")


def create_app(data_dir: Path | None = None, judge: Judge | None = None) -> FastAPI:
    store = Store(data_dir or Path("data"))
    worker = judge or FakeJudge()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        with store.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS initialized (name TEXT PRIMARY KEY)")
            if not db.execute("SELECT 1 FROM initialized WHERE name='sample'").fetchone():
                folder = store.root / "cases" / "UJ-SAMPLE"
                folder.mkdir(parents=True, exist_ok=True)
                verdict = worker.run(folder)
                save_case(
                    db,
                    Case(
                        id=folder.name,
                        order_id=ORDER.id,
                        claim_type="wrong_item",
                        description="Sample case for integration.",
                        status="ready",
                        created_at=datetime(2026, 11, 20, tzinfo=UTC),
                        verdict=verdict,
                        progress=[
                            ProgressEvent(event="started", step="scaffold"),
                            ProgressEvent(event="finished", step="scaffold"),
                            ProgressEvent(event="done"),
                        ],
                    ),
                )
                db.execute("INSERT INTO initialized VALUES ('sample')")
        yield

    app = FastAPI(title="Case review API", lifespan=lifespan)
    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])
    deferred = {
        501: {"model": ErrorDetail, "description": "Planned for the upload integration checkpoint."}
    }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/orders")
    def orders() -> list[OrderWithListing]:
        return [ORDER]

    @router.get("/listings")
    def listings() -> list[Listing]:
        return [LISTING]

    @router.post("/listings", responses=deferred, openapi_extra=multipart(ListingForm))
    def add_listing() -> Listing:
        raise HTTPException(501, "Listing uploads are not implemented in the sample API.")

    @router.post("/cases", status_code=201)
    def create_case(body: CreateCase) -> CreatedCase:
        if body.order_id != ORDER.id:
            raise HTTPException(404, "Order not found.")
        case = Case(
            id=f"UJ-{uuid4().hex}",
            **body.model_dump(),
            created_at=datetime.now(UTC),
            status="awaiting_video",
        )
        with store.transaction() as db:
            save_case(db, case)
        return CreatedCase(id=case.id)

    @router.get("/cases/{id}")
    def buyer_case(id: str) -> BuyerCase:
        with store.transaction() as db:
            return buyer_view(get_case(db, id))

    @router.get("/my/cases")
    def my_cases() -> list[BuyerCase]:
        with store.transaction() as db:
            return [buyer_view(case) for case in list_cases(db)]

    @router.get("/shop/cases")
    def inbox() -> list[ShopSummary]:
        with store.transaction() as db:
            cases = list_cases(db)
        summaries = [
            ShopSummary(
                id=c.id,
                product=LISTING.title,
                order_id=c.order_id,
                claim_type=c.claim_type,
                status=c.status,
                verdict=c.verdict.verdict if c.verdict else None,
                display=c.verdict.display if c.verdict else None,
                confidence=c.verdict.confidence if c.verdict else None,
                created_at=c.created_at,
            )
            for c in cases
        ]
        return sorted(summaries, key=lambda s: s.display != "unsure")

    @router.get("/shop/cases/{id}")
    def shop_case(id: str) -> Case:
        with store.transaction() as db:
            return get_case(db, id)

    @router.post("/shop/cases/{id}/decision")
    def decide(id: str, decision: Decision) -> Case:
        with store.transaction() as db:
            case = get_case(db, id)
            if case.status != "ready" or case.verdict is None:
                raise HTTPException(409, "This case is not awaiting a decision.")
            try:
                decision.validate_for(case.verdict.display)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            case.status = "decided"
            case.decision = decision
            save_case(db, case)
            return case

    @router.delete("/cases/{id}", status_code=204)
    def delete_case(id: str) -> Response:
        with store.transaction() as db:
            case = get_case(db, id)
            folder = store.root / "cases" / case.id
            if folder.exists():
                shutil.rmtree(folder)
            db.execute("DELETE FROM cases WHERE id=?", (id,))
        return Response(status_code=204)

    @router.get(
        "/cases/{id}/events",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}}, **deferred},
    )
    def events(id: str) -> StreamingResponse:
        """Replay the sample events for a completed case."""
        with store.transaction() as db:
            case = get_case(db, id)
        if case.status not in ("ready", "decided"):
            raise HTTPException(501, "Live job events arrive with the upload integration.")
        return StreamingResponse(
            (f"event: {item.event}\ndata: {item.model_dump_json()}\n\n" for item in case.progress),
            media_type="text/event-stream",
        )

    @router.post("/cases/{id}/video", responses=deferred, openapi_extra=multipart(VideoForm))
    def upload(id: str) -> UploadResult:
        with store.transaction() as db:
            get_case(db, id)
        raise HTTPException(501, "Video upload is not implemented in the sample API.")

    @router.post("/cases/{id}/upload-link", responses=deferred)
    def upload_link(id: str) -> UploadLink:
        with store.transaction() as db:
            get_case(db, id)
        raise HTTPException(501, "Phone upload is not implemented in the sample API.")

    @router.post("/uploads/{token}", responses=deferred, openapi_extra=multipart(VideoForm))
    def phone_upload(token: str) -> UploadResult:
        raise HTTPException(501, "Phone upload is not implemented in the sample API.")

    @router.get(
        "/files/{path:path}",
        response_class=FileResponse,
        responses={200: {"content": {"image/png": {}}}},
    )
    def media(path: str) -> FileResponse:
        """Serve the sample catalog image; case media is introduced with video upload."""
        if path != "listings/sample/tee.png":
            raise HTTPException(404, "File not found.")
        return FileResponse(Path(__file__).parent / "fixtures" / "tee.png", media_type="image/png")

    app.include_router(router)
    return app


app = create_app()
