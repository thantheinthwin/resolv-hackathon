"""Apply upload bounds while parsing authenticated multipart requests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException, Request
from python_multipart.exceptions import FormParserError
from starlette.datastructures import FormData
from starlette.formparsers import MultiPartException, MultiPartParser


@asynccontextmanager
async def bounded_form(
    request: Request, *, max_bytes: int, max_files: int, max_fields: int
) -> AsyncIterator[FormData]:
    if (
        request.headers.get("content-type", "").partition(";")[0].strip().lower()
        != "multipart/form-data"
    ):
        raise HTTPException(422, "Send the upload as multipart form data.")

    async def bounded_body() -> AsyncIterator[bytes]:
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > max_bytes:
                raise MultiPartException("Request exceeds the upload limit.")
            yield chunk

    try:
        form = await MultiPartParser(
            request.headers,
            bounded_body(),
            max_files=max_files,
            max_fields=max_fields,
            max_part_size=65_536,
        ).parse()
    except MultiPartException as exc:
        raise HTTPException(422, exc.message) from exc
    except FormParserError as exc:
        raise HTTPException(422, "Invalid multipart data.") from exc
    try:
        yield form
    finally:
        await form.close()
