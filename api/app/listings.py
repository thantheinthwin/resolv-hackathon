"""The shop catalog and its ordered, validated photo uploads."""

from io import BytesIO
from uuid import uuid4

from fastapi import HTTPException, Request, Response
from PIL import Image
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile

from api.app.catalog import create_reportable_product
from api.app.contracts import Listing
from api.app.multipart import bounded_form
from api.app.photo_formats import PHOTO_FORMATS
from api.app.sample import LISTING
from api.app.store import Store
from api.app.views import ListingForm

MAX_PHOTO_BYTES = 10_000_000
MAX_PHOTO_PIXELS = 24_000_000
MAX_FORM_BYTES = 3 * MAX_PHOTO_BYTES + 65_536


def catalog(store: Store) -> list[Listing]:
    with store.connection() as db:
        rows = db.execute("SELECT body FROM products ORDER BY (id = ?) DESC, rowid", (LISTING.id,))
        return [Listing.model_validate_json(body) for (body,) in rows]


def photo_response(store: Store, path: str) -> Response:
    with store.connection() as db:
        row = db.execute(
            "SELECT mime, image FROM listing_photos WHERE path = ?", (path,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "File not found.")
    return Response(row[1], media_type=row[0], headers={"X-Content-Type-Options": "nosniff"})


def photo_format(data: bytes) -> tuple[str, str]:
    try:
        with Image.open(BytesIO(data), formats=list(PHOTO_FORMATS)) as image:
            if image.width * image.height > MAX_PHOTO_PIXELS:
                raise HTTPException(422, "A product photo exceeds 24 megapixels.")
            image.load()
            return PHOTO_FORMATS[image.format]
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Use a readable JPEG, PNG, or WebP product photo.") from exc


def save_listing(store: Store, form: FormData) -> Listing:
    images = []
    for upload in form.getlist("photos"):
        if not isinstance(upload, UploadFile):
            raise HTTPException(422, "Attach product photos as files.")
        if upload.size is not None and upload.size > MAX_PHOTO_BYTES:
            raise HTTPException(422, "A product photo exceeds 10 MB.")
        images.append(upload.file.read(MAX_PHOTO_BYTES + 1))
        if len(images[-1]) > MAX_PHOTO_BYTES:
            raise HTTPException(422, "A product photo exceeds 10 MB.")
    try:
        product = ListingForm.model_validate(
            {
                **dict(form),
                "colors": form.getlist("colors"),
                "sizes": form.getlist("sizes"),
                "box_contents": form.getlist("box_contents"),
                "photos": images,
            }
        )
    except ValidationError as exc:
        error = exc.errors(include_input=False)[0]
        raise HTTPException(422, f"{error['loc'][0]}: {error['msg']}") from exc
    listing_id = f"LS-{uuid4().hex}"
    photos = []
    for position, image in enumerate(images, 1):
        extension, mime = photo_format(image)
        photos.append((f"listings/{listing_id}/{position}.{extension}", mime, image))
    listing = Listing(
        **product.model_dump(exclude={"photos"}),
        id=listing_id,
        photos=[f"/api/files/{path}" for path, _, _ in photos],
    )
    with store.transaction() as db:
        create_reportable_product(db, listing)
        db.executemany("INSERT INTO listing_photos (path, mime, image) VALUES (?, ?, ?)", photos)
    return listing


async def accept_listing(store: Store, request: Request) -> Listing:
    async with bounded_form(request, max_bytes=MAX_FORM_BYTES, max_files=3, max_fields=256) as form:
        return await run_in_threadpool(save_listing, store, form)
