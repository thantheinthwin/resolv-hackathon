"""Bounded multipart intake for local video jobs."""

from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from api.app.jobs import JobRunner
from api.app.listings import MAX_PHOTO_BYTES, photo_format
from judge.submission import MAX_BUYER_PHOTOS
from api.app.multipart import bounded_form
from judge.intake import MAX_VIDEO_BYTES, IntakeError, inspect_video


def media_type(header: bytes) -> str | None:
    if header[4:8] == b"ftyp":
        return "video/quicktime" if header[8:12] == b"qt  " else "video/mp4"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm" if b"webm" in header else "video/x-matroska"
    if header.startswith(b"RIFF") and header[8:12] == b"AVI ":
        return "video/x-msvideo"
    return None


def stage_and_submit(
    video: UploadFile,
    root: Path,
    runner: JobRunner,
    case_id: str,
    link_digest: bytes | None = None,
    photos: tuple[UploadFile, ...] = (),
) -> list[str]:
    if video.size is not None and video.size > MAX_VIDEO_BYTES:
        raise HTTPException(422, "Video exceeds the 50 MB upload limit.")
    if media_type(video.file.read(64)) is None:
        raise HTTPException(422, "Choose an MP4, MOV, WebM, MKV, or AVI recording.")
    video.file.seek(0)
    incoming = root / ".incoming"
    incoming.mkdir(exist_ok=True)
    try:
        with TemporaryDirectory(dir=incoming, suffix=".upload") as tmp:
            path = Path(tmp) / "video.mp4"
            with path.open("wb") as staged:
                copyfileobj(video.file, staged)
            total = path.stat().st_size
            attachments = Path(tmp) / "private-photos"
            for index, upload in enumerate(photos):
                data = upload.file.read(MAX_PHOTO_BYTES + 1)
                if len(data) > MAX_PHOTO_BYTES:
                    raise HTTPException(422, "Each photo must be 10 MB or smaller.")
                total += len(data)
                if total > MAX_VIDEO_BYTES:
                    raise HTTPException(422, "The video and photos together must fit within 50 MB.")
                ext, _ = photo_format(data)
                attachments.mkdir(exist_ok=True)
                (attachments / f"{index}.{ext}").write_bytes(data)
            intake = inspect_video(path)
            if photos:
                runner.submit(case_id, path, link_digest, attachments)
            else:
                runner.submit(case_id, path, link_digest)
            return intake.warnings
    except IntakeError as exc:
        raise HTTPException(422, str(exc)) from exc


async def accept_video(
    request: Request, root: Path, runner: JobRunner, case_id: str, link_digest: bytes | None = None
) -> list[str]:
    async with bounded_form(
        request, max_bytes=MAX_VIDEO_BYTES + 65_536, max_files=1 + MAX_BUYER_PHOTOS, max_fields=0
    ) as form:
        video = form.get("video")
        photos = form.getlist("photos")
        if (
            set(form) - {"video", "photos"}
            or len(form.getlist("video")) != 1
            or not isinstance(video, UploadFile)
        ):
            raise HTTPException(422, "A video file is required.")
        if len(photos) > MAX_BUYER_PHOTOS or any(
            not isinstance(photo, UploadFile) for photo in photos
        ):
            raise HTTPException(422, "Choose up to three photos.")
        return await run_in_threadpool(
            stage_and_submit, video, root, runner, case_id, link_digest, tuple(photos)
        )
