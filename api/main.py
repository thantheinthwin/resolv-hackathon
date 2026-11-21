"""First-hour API: a persistent sample case and typed integration boundaries."""

import asyncio
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
    Request,
    Response,
)
from pydantic import BaseModel
from fastapi.responses import FileResponse, StreamingResponse

from api.app.contracts import Case, Decision, Listing, ProgressEvent
from api.app.fake import FakeJudge, Judge, write_sample_verdict
from api.app.jobs import JobRunner
from api.app.uploads import accept_video, media_type
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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        store.initialize()
        with store.transaction() as db:
            if not db.execute("SELECT 1 FROM initialized WHERE name='sample'").fetchone():
                folder = store.root / "cases" / "UJ-SAMPLE"
                folder.mkdir(parents=True, exist_ok=True)
                verdict = write_sample_verdict(folder)
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
        runner = JobRunner(store, app.state.judge)
        runner.start()
        app.state.runner = runner
        app.state.intake_slots = asyncio.Semaphore(2)
        try:
            yield
        finally:
            await asyncio.to_thread(runner.close)

    app = FastAPI(title="Case review API", lifespan=lifespan)
    app.state.judge = judge if judge is not None else FakeJudge()
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
        with store.connection() as db:
            return buyer_view(get_case(db, id))

    @router.get("/my/cases")
    def my_cases() -> list[BuyerCase]:
        with store.connection() as db:
            return [buyer_view(case) for case in list_cases(db)]

    @router.get("/shop/cases")
    def inbox() -> list[ShopSummary]:
        with store.connection() as db:
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
        with store.connection() as db:
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
            if case.status == "checking":
                raise HTTPException(409, "Case is being checked. Retry deletion once it finishes.")
            for parent in (".replaced", "cases"):
                folder = store.root / parent / case.id
                if folder.exists():
                    shutil.rmtree(folder)
            db.execute("DELETE FROM replaced_uploads WHERE case_id=?", (id,))
            db.execute("DELETE FROM cases WHERE id=?", (id,))
        return Response(status_code=204)

    @router.get(
        "/cases/{id}/events",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}}, 409: {"model": ErrorDetail}},
    )
    def events(id: str) -> StreamingResponse:
        """Stream persisted progress in order, including earlier events."""

        def snapshot() -> Case:
            with store.connection() as db:
                return get_case(db, id)

        initial = snapshot()
        if initial.status == "awaiting_video":
            raise HTTPException(409, "Upload a video first.")

        async def stream() -> AsyncIterator[str]:
            case = initial
            offset = 0
            while True:
                for item in case.progress[offset:]:
                    yield f"event: {item.event}\ndata: {item.model_dump_json()}\n\n"
                offset = len(case.progress)
                if case.status != "checking":
                    return
                await asyncio.sleep(0.25)
                try:
                    case = await asyncio.to_thread(snapshot)
                except HTTPException as exc:
                    if exc.status_code == 404:
                        return
                    raise

        return StreamingResponse(stream(), media_type="text/event-stream")

    @router.post(
        "/cases/{id}/video",
        status_code=202,
        openapi_extra=multipart(VideoForm),
        responses={
            409: {"model": ErrorDetail, "description": "Case already has a video"},
            422: {
                "description": "Invalid video or request",
                "content": {
                    "application/json": {
                        "schema": {
                            "anyOf": [
                                {"$ref": "#/components/schemas/ErrorDetail"},
                                {"$ref": "#/components/schemas/HTTPValidationError"},
                            ]
                        }
                    }
                },
            },
        },
    )
    async def upload(id: str, request: Request) -> UploadResult:
        with store.connection() as db:
            case = get_case(db, id)
        if case.status not in ("awaiting_video", "failed"):
            raise HTTPException(409, "This case already has a video.")
        async with app.state.intake_slots:
            warnings = await accept_video(request, store.root, app.state.runner, id)
        return UploadResult(id=id, status="checking", warnings=warnings)

    @router.post("/cases/{id}/upload-link", responses=deferred)
    def upload_link(id: str) -> UploadLink:
        with store.connection() as db:
            get_case(db, id)
        raise HTTPException(501, "Phone upload is not implemented in the sample API.")

    @router.post("/uploads/{token}", responses=deferred, openapi_extra=multipart(VideoForm))
    def phone_upload(token: str) -> UploadResult:
        raise HTTPException(501, "Phone upload is not implemented in the sample API.")

    @router.get(
        "/files/{path:path}",
        response_class=FileResponse,
        responses={
            200: {
                "content": {
                    mime: {}
                    for mime in (
                        "image/png",
                        "video/mp4",
                        "video/quicktime",
                        "video/webm",
                        "video/x-matroska",
                        "video/x-msvideo",
                    )
                }
            }
        },
    )
    def media(path: str) -> FileResponse:
        """Serve catalog images and videos associated with an uploaded case."""
        if path == "listings/sample/tee.png":
            return FileResponse(
                Path(__file__).parent / "fixtures" / "tee.png", media_type="image/png"
            )
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == "cases" and parts[2] == "video.mp4":
            with store.connection() as db:
                case = get_case(db, parts[1])
                if case.video_url == f"/api/files/{path}":
                    video = store.root / "cases" / case.id / "video.mp4"
                    if video.is_file():
                        with video.open("rb") as handle:
                            content_type = media_type(handle.read(64))
                        return FileResponse(
                            video,
                            media_type=content_type or "application/octet-stream",
                            headers={"X-Content-Type-Options": "nosniff"},
                        )
        raise HTTPException(404, "File not found.")

    app.include_router(router)
    return app


app = create_app()
