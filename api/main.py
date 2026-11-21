"""First-hour API: a persistent sample case and typed integration boundaries."""

import asyncio
import hmac
import hashlib
import secrets
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
    Query,
    Request,
    Response,
)
from pydantic import BaseModel
from fastapi.responses import FileResponse, StreamingResponse

from api.app.catalog import delivered_orders, require_order
from api.app.contracts import Case, Decision, Listing, ProgressEvent
from api.app.fake import Judge, write_sample_verdict
from api.app.jobs import JobRunner
from api.app.judging import CaseJudge
from api.app.listings import accept_listing, catalog, photo_response
from api.app.uploads import accept_video, media_type
from api.app.sample import ORDER, OrderWithListing
from api.app.store import Store, case_for_upload_link, get_case, list_cases, save_case
from api.app.usage import consume_case_quota
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
    """Describe multipart fields for handlers that parse a bounded request stream."""
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
    app.state.judge = judge if judge is not None else CaseJudge(store)
    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/orders")
    def orders() -> list[OrderWithListing]:
        with store.connection() as db:
            return delivered_orders(db)

    @router.get("/listings")
    def listings() -> list[Listing]:
        return catalog(store)

    multipart_errors = {
        422: {
            "description": "Invalid multipart form or request",
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
    }

    @router.post(
        "/listings",
        status_code=201,
        responses=multipart_errors,
        openapi_extra=multipart(ListingForm),
    )
    async def add_listing(request: Request) -> Listing:
        """Add a product with 1–3 JPEG, PNG, or WebP photos (10 MB and 24 megapixels each).

        Send colors, sizes and box_contents as repeated fields. The first photo is the main one.
        """
        async with app.state.intake_slots:
            return await accept_listing(store, request)

    @router.post(
        "/cases",
        status_code=201,
        responses={429: {"model": ErrorDetail, "description": "Daily case limit reached"}},
    )
    def create_case(body: CreateCase, request: Request) -> CreatedCase:
        with store.transaction() as db:
            require_order(db, body.order_id)
            case = Case(
                id=f"UJ-{uuid4().hex}",
                **body.model_dump(),
                created_at=datetime.now(UTC),
                status="awaiting_video",
            )
            consume_case_quota(db, request.client.host if request.client else None, case.created_at)
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
            rows = db.execute(
                "SELECT c.body, p.title FROM cases AS c "
                "LEFT JOIN orders AS o ON o.id=c.order_id "
                "LEFT JOIN products AS p ON p.id=o.product_id"
            )
            summaries = []
            for body, title in rows:
                case = Case.model_validate_json(body)
                summaries.append(
                    ShopSummary(
                        id=case.id,
                        product=title or "Unknown product",
                        order_id=case.order_id,
                        claim_type=case.claim_type,
                        status=case.status,
                        verdict=case.verdict.verdict if case.verdict else None,
                        display=case.verdict.display if case.verdict else None,
                        confidence=case.verdict.confidence if case.verdict else None,
                        created_at=case.created_at,
                    )
                )
        return sorted(
            summaries, key=lambda row: (row.display == "unsure", row.created_at), reverse=True
        )

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

    @router.delete(
        "/cases/{id}",
        status_code=204,
        responses={409: {"model": ErrorDetail}},
    )
    def delete_case(
        id: str,
        draft: Annotated[bool, Query(description="Delete only if awaiting a video.")] = False,
    ) -> Response:
        with store.transaction() as db:
            case = get_case(db, id)
            if draft and case.status != "awaiting_video":
                raise HTTPException(409, "The video has already been received.")
            if case.status == "checking":
                raise HTTPException(409, "Case is being checked. Retry deletion once it finishes.")
            for parent in (".replaced", "cases"):
                folder = store.root / parent / case.id
                if folder.exists():
                    shutil.rmtree(folder)
            db.execute("DELETE FROM replaced_uploads WHERE case_id=?", (id,))
            db.execute("DELETE FROM upload_links WHERE case_id=?", (id,))
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

    upload_responses = {
        404: {"model": ErrorDetail, "description": "Unknown case or upload link"},
        409: {"model": ErrorDetail, "description": "Case already has a video"},
        **multipart_errors,
    }

    @router.post(
        "/cases/{id}/video",
        status_code=202,
        openapi_extra=multipart(VideoForm),
        responses=upload_responses,
    )
    async def upload(id: str, request: Request) -> UploadResult:
        with store.connection() as db:
            case = get_case(db, id)
        if case.status not in ("awaiting_video", "failed"):
            raise HTTPException(409, "This case already has a video.")
        async with app.state.intake_slots:
            warnings = await accept_video(request, store.root, app.state.runner, id)
        return UploadResult(id=id, status="checking", warnings=warnings)

    @router.post(
        "/cases/{id}/upload-link",
        responses={
            404: {"model": ErrorDetail},
            409: {"model": ErrorDetail},
        },
    )
    def upload_link(id: str) -> UploadLink:
        """Issue a one-time phone link, replacing any previous link for the case."""
        with store.transaction() as db:
            case = get_case(db, id)
            if case.status not in ("awaiting_video", "failed"):
                raise HTTPException(409, "This case already has a video.")
            token = secrets.token_urlsafe(32)
            db.execute(
                "INSERT INTO upload_links(case_id, digest) VALUES (?, ?) "
                "ON CONFLICT(case_id) DO UPDATE SET digest=excluded.digest",
                (id, hashlib.sha256(token.encode()).digest()),
            )
        return UploadLink(token=token, url=f"/upload/{token}")

    @router.post(
        "/uploads/{token}",
        status_code=202,
        responses=upload_responses,
        openapi_extra=multipart(VideoForm),
    )
    async def phone_upload(token: str, request: Request) -> UploadResult:
        """Accept an upload for the case identified by its current phone link."""
        digest = hashlib.sha256(token.encode()).digest()
        with store.connection() as db:
            case_id = case_for_upload_link(db, digest)
        async with app.state.intake_slots:
            warnings = await accept_video(request, store.root, app.state.runner, case_id, digest)
        return UploadResult(id=case_id, status="checking", warnings=warnings)

    @router.get(
        "/files/{path:path}",
        response_class=FileResponse,
        responses={
            200: {
                "content": {
                    mime: {}
                    for mime in (
                        "image/png",
                        "image/jpeg",
                        "image/webp",
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
    def media(path: str) -> Response:
        """Serve catalog images, uploaded videos and evidence referenced by a case verdict."""
        if path == "listings/sample/tee.png":
            return FileResponse(
                Path(__file__).parent / "fixtures" / "tee.png", media_type="image/png"
            )
        if path.startswith("listings/"):
            return photo_response(store, path)
        parts = path.split("/")
        if len(parts) == 4 and parts[0] == "cases" and parts[2] in {"frames", "listing"}:
            with store.connection() as db:
                case = get_case(db, parts[1])
            ref = "/".join(parts[2:])
            if case.verdict and any(
                ref in (pair.frame, pair.listing_photo) for pair in case.verdict.evidence
            ):
                asset = store.root / "cases" / case.id / ref
                if asset.is_file():
                    return FileResponse(asset)
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
