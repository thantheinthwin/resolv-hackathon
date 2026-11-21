"""Durable case jobs for a single API process per data directory."""

import logging
import os
import shutil
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from threading import Lock

from fastapi import HTTPException

from api.app.contracts import Case, ProgressEvent, Verdict
from api.app.fake import Judge
from api.app.store import Store, case_for_upload_link, get_case, save_case

log = logging.getLogger(__name__)


@contextmanager
def _owner_lock(root: Path) -> Iterator[None]:
    """The kernel releases ownership if the previous API process crashes."""
    with (root / ".jobs.lock").open("a+b") as lock:
        try:
            if os.name == "nt":
                import msvcrt

                if lock.seek(0, os.SEEK_END) == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                "A job runner must have exclusive use of its data directory."
            ) from exc
        yield


class JobRunner:
    def __init__(self, store: Store, judge: Judge) -> None:
        self.store = store
        self.judge = judge
        self._lifecycle = Lock()
        self._resources = ExitStack()
        self._pool: ThreadPoolExecutor | None = None

    def start(self) -> None:
        with self._lifecycle, ExitStack() as startup:
            if self._pool is not None:
                raise RuntimeError("Job runner already started.")
            startup.enter_context(_owner_lock(self.store.root))
            for upload in (self.store.root / ".incoming").glob("*.upload"):
                if upload.is_dir():
                    shutil.rmtree(upload)
                elif upload.is_file():
                    upload.unlink()
            pool = startup.enter_context(
                ThreadPoolExecutor(max_workers=2, thread_name_prefix="case")
            )
            with self.store.transaction() as db:
                # This journal distinguishes a committed replacement (including one
                # that subsequently failed judging) from a rolled-back upload.
                retired = db.execute("SELECT case_id FROM replaced_uploads").fetchall()
                for (case_id,) in retired:
                    backup = self._backup(case_id)
                    if backup.exists():
                        shutil.rmtree(backup)
                db.execute("DELETE FROM replaced_uploads")
                rows = db.execute("SELECT id, status FROM cases").fetchall()
            for case_id, status in rows:
                folder = self._case_dir(case_id)
                # A leftover backup without a journal entry belongs to an upload
                # whose SQLite transaction rolled back when the API stopped.
                previous = self._backup(case_id)
                if previous.exists():
                    if folder.exists():
                        shutil.rmtree(folder)
                    previous.replace(folder)
                if status == "awaiting_video" and (folder / "video.mp4").is_file():
                    # An initial upload was installed but its transaction rolled back.
                    shutil.rmtree(folder)
                if status == "checking":
                    pool.submit(self._run, case_id, True)
            self._resources = startup.pop_all()
            self._pool = pool

    def close(self) -> None:
        with self._lifecycle:
            self._pool = None
            # Drain the thread pool before releasing process ownership.
            self._resources.close()

    def _case_dir(self, case_id: str) -> Path:
        if not case_id or case_id in {".", ".."} or "/" in case_id or "\\" in case_id:
            raise ValueError("Invalid stored case identifier")
        return self.store.root / "cases" / case_id

    def _backup(self, case_id: str) -> Path:
        return self.store.root / ".replaced" / self._case_dir(case_id).name

    def submit(
        self,
        case_id: str,
        staged_video: Path,
        link_digest: bytes | None = None,
        photos: Path | None = None,
    ) -> None:
        """Accept an inspected upload, or reject a competing attempt without touching its file."""
        with self._lifecycle:
            if self._pool is None:
                raise HTTPException(503, "The job runner is unavailable.")
            with staged_video.open("r+b") as source:
                os.fsync(source.fileno())
            photo_files = sorted(photos.iterdir()) if photos and photos.is_dir() else []
            for photo in photo_files:
                with photo.open("r+b") as handle:
                    os.fsync(handle.fileno())
            previous: Path | None = None
            installed: Path | None = None
            try:
                with self.store.transaction() as db:
                    if link_digest is not None and case_for_upload_link(db, link_digest) != case_id:
                        raise HTTPException(404, "Upload link does not belong to this case.")
                    case = get_case(db, case_id)
                    folder = self._case_dir(case.id)
                    case.status = "checking"
                    case.video_url = f"/api/files/cases/{case.id}/video.mp4"
                    case.progress = []
                    case.buyer_photo_count = len(photo_files)
                    claim = db.execute(
                        "UPDATE cases SET body=? WHERE id=? AND "
                        "status IN ('awaiting_video','failed')",
                        (case.model_dump_json(), case_id),
                    )
                    if claim.rowcount != 1:
                        raise HTTPException(409, "The case already has an accepted upload.")
                    # Both desktop and phone acceptance revoke the link. Rollback
                    # leaves it usable if the upload cannot be durably installed.
                    db.execute("DELETE FROM upload_links WHERE case_id=?", (case_id,))
                    if folder.exists():
                        backup = self._backup(case_id)
                        if backup.exists():
                            raise HTTPException(503, "Previous upload cleanup is pending.")
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        db.execute("INSERT INTO replaced_uploads VALUES (?)", (case_id,))
                        folder.replace(backup)
                        previous = backup
                    folder.mkdir(parents=True)
                    installed = folder
                    staged_video.replace(folder / "video.mp4")
                    if photo_files and photos:
                        photos.replace(folder / "private-photos")
            except BaseException:
                if installed is not None:
                    # Leave the caller's temporary file usable if commit failed.
                    video = installed / "video.mp4"
                    if video.exists():
                        video.replace(staged_video)
                    if photos and (installed / "private-photos").is_dir():
                        (installed / "private-photos").replace(photos)
                    installed.rmdir()
                if previous is not None:
                    previous.replace(folder)
                raise
            self._pool.submit(self._run, case_id, False)
            if previous is not None:
                try:
                    shutil.rmtree(previous)
                    with self.store.transaction() as db:
                        db.execute("DELETE FROM replaced_uploads WHERE case_id=?", (case_id,))
                except (OSError, sqlite3.Error):
                    log.exception("Will retry retired upload cleanup at startup for %s", case_id)

    def _run(self, case_id: str, recovering: bool) -> None:
        folder = self._case_dir(case_id)
        try:
            with self.store.transaction() as db:
                case = get_case(db, case_id)
                if case.status != "checking":
                    return
                if not case.progress:
                    case.progress.append(ProgressEvent(event="started", step="judge"))
                    save_case(db, case)
            if not (folder / "video.mp4").is_file():
                raise FileNotFoundError("The accepted upload is missing.")
            saved = folder / "verdict.json"
            verdict = None
            if recovering and saved.is_file():
                try:
                    candidate = Verdict.model_validate_json(saved.read_bytes())
                    Case.model_validate(
                        {**case.model_dump(), "status": "ready", "verdict": candidate}
                    )
                    verdict = candidate
                except ValueError:
                    # A crash can leave truncated output; let the judge resume its steps.
                    saved.unlink()
            if verdict is None:
                verdict = self.judge.run(folder)
                if Verdict.model_validate_json(saved.read_bytes()) != verdict:
                    raise ValueError("The returned and persisted verdicts differ.")
            with self.store.transaction() as db:
                case = get_case(db, case_id)
                if case.status == "checking":
                    case.verdict = verdict
                    case.status = "ready"
                    case.progress.extend(
                        [ProgressEvent(event="finished", step="judge"), ProgressEvent(event="done")]
                    )
                    save_case(db, case)
        except Exception:
            log.exception("Judge job failed for %s", case_id)
            with self.store.transaction() as db:
                case = get_case(db, case_id)
                if case.status == "checking":
                    case.status = "failed"
                    case.progress.append(ProgressEvent(event="done"))
                    save_case(db, case)
