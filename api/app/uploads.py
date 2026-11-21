"""Bounded multipart intake for local video jobs."""

from collections.abc import AsyncIterator
from pathlib import Path
from shutil import copyfileobj
from tempfile import NamedTemporaryFile

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from api.app.jobs import JobRunner
from judge.intake import MAX_VIDEO_BYTES, IntakeError, inspect_video


def media_type(header: bytes) -> str | None:
    if header[4:8] == b"ftyp":
        return "video/quicktime" if header[8:12] == b"qt  " else "video/mp4"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm" if b"webm" in header else "video/x-matroska"
    if header.startswith(b"RIFF") and header[8:12] == b"AVI ":
        return "video/x-msvideo"
    return None


def stage_and_submit(video: UploadFile, root: Path, runner: JobRunner, case_id: str) -> list[str]:
    if video.size is not None and video.size > MAX_VIDEO_BYTES:
        raise HTTPException(422, "Video exceeds the 50 MB upload limit.")
    if media_type(video.file.read(64)) is None:
        raise HTTPException(422, "Choose an MP4, MOV, WebM, MKV, or AVI recording.")
    video.file.seek(0)
    incoming = root / ".incoming"
    incoming.mkdir(exist_ok=True)
    staged = NamedTemporaryFile(dir=incoming, suffix=".upload", delete=False)
    path = Path(staged.name)
    try:
        with staged:
            copyfileobj(video.file, staged)
        intake = inspect_video(path)
        runner.submit(case_id, path)
        return intake.warnings
    except IntakeError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)


async def accept_video(request: Request, root: Path, runner: JobRunner, case_id: str) -> list[str]:
    if request.headers.get("content-type", "").partition(";")[0].lower() != "multipart/form-data":
        raise HTTPException(422, "Send the video as multipart form data.")

    async def bounded_body() -> AsyncIterator[bytes]:
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > MAX_VIDEO_BYTES + 65536:
                raise MultiPartException("Video request exceeds the upload limit.")
            yield chunk

    try:
        form = await MultiPartParser(
            request.headers, bounded_body(), max_files=1, max_fields=0
        ).parse()
    except MultiPartException as exc:
        raise HTTPException(422, exc.message) from exc
    try:
        video = form.get("video")
        if not isinstance(video, UploadFile):
            raise HTTPException(422, "A video file is required.")
        return await run_in_threadpool(stage_and_submit, video, root, runner, case_id)
    finally:
        await form.close()
