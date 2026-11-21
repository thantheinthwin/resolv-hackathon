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
from api.app.reviews import initialize_reviews, reset_reviews
from api.app.store import Store, case_for_upload_link, get_case, save_case
from judge import ReviewRequired

log = logging.getLogger(__name__)


def persist_progress(store: Store, case_id: str, event: ProgressEvent) -> None:
    """Publish a worker stage once, including when a reviewed job replays it."""
    if event.event not in {"started", "finished"} or not event.step:
        raise ValueError("The judge can only publish stage progress.")
    with store.transaction() as db:
        case = get_case(db, case_id)
        if case.status == "checking" and event not in case.progress:
            case.progress.append(event)
            save_case(db, case)


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
        self._dispatch = Lock()
        # An approval can arrive while the worker is still unwinding ReviewRequired.
        # Keep that wakeup and coalesce repeats without running two jobs on one upload.
        self._scheduled: dict[str, bool] = {}
        self._resources = ExitStack()
        self._pool: ThreadPoolExecutor | None = None

    def start(self) -> None:
        with self._lifecycle, ExitStack() as startup:
            if self._pool is not None:
                raise RuntimeError("Job runner already started.")
            startup.enter_context(_owner_lock(self.store.root))
            for upload in (self.store.root / ".incoming").glob("*.upload"):
                if upload.is_file():
                    upload.unlink()
            pool = startup.enter_context(
                ThreadPoolExecutor(max_workers=2, thread_name_prefix="case")
            )
            with self.store.transaction() as db:
                initialize_reviews(db)
                # This journal distinguishes a committed replacement (including one
                # that subsequently failed judging) from a rolled-back upload.
                db.execute("CREATE TABLE IF NOT EXISTS replaced_uploads (case_id TEXT PRIMARY KEY)")
                retired = db.execute("SELECT case_id FROM replaced_uploads").fetchall()
                for (case_id,) in retired:
                    backup = self._backup(case_id)
                    if backup.exists():
                        shutil.rmtree(backup)
                db.execute("DELETE FROM replaced_uploads")
                pending_reviews = {
                    row[0] for row in db.execute("SELECT case_id FROM pending_reviews")
                }
                rows = db.execute("SELECT id, json_extract(body,'$.status') FROM cases").fetchall()
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
                if status == "checking" and case_id not in pending_reviews:
                    self._schedule(pool, case_id, True)
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

    def submit(self, case_id: str, staged_video: Path, link_digest: bytes | None = None) -> None:
        """Accept an inspected upload, or reject a competing attempt without touching its file."""
        with self._lifecycle:
            if self._pool is None:
                raise HTTPException(503, "The job runner is unavailable.")
            with staged_video.open("r+b") as source:
                os.fsync(source.fileno())
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
                    claim = db.execute(
                        "UPDATE cases SET body=? WHERE id=? AND "
                        "json_extract(body, '$.status') IN ('awaiting_video','failed')",
                        (case.model_dump_json(), case_id),
                    )
                    if claim.rowcount != 1:
                        raise HTTPException(409, "The case already has an accepted upload.")
                    reset_reviews(db, case_id)
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
            except BaseException:
                if installed is not None:
                    # Leave the caller's temporary file usable if commit failed.
                    video = installed / "video.mp4"
                    if video.exists():
                        video.replace(staged_video)
                    installed.rmdir()
                if previous is not None:
                    previous.replace(folder)
                raise
            self._schedule(self._pool, case_id, False)
            if previous is not None:
                try:
                    shutil.rmtree(previous)
                    with self.store.transaction() as db:
                        db.execute("DELETE FROM replaced_uploads WHERE case_id=?", (case_id,))
                except (OSError, sqlite3.Error):
                    log.exception("Will retry retired upload cleanup at startup for %s", case_id)

    def resume(self, case_id: str) -> None:
        """Wake a checking job after a reviewer has committed their decision."""
        with self._lifecycle:
            if self._pool is None:
                raise HTTPException(503, "The job runner is unavailable.")
            self._schedule(self._pool, case_id, False)

    def _schedule(self, pool: ThreadPoolExecutor, case_id: str, recovering: bool) -> None:
        with self._dispatch:
            if case_id in self._scheduled:
                self._scheduled[case_id] = True
                return
            self._scheduled[case_id] = False
            pool.submit(self._drain, case_id, recovering)

    def _drain(self, case_id: str, recovering: bool) -> None:
        while True:
            try:
                self._run(case_id, recovering)
            except Exception as error:
                # A storage error can prevent even the failure status being saved.
                # Startup will recover a case that is still checking.
                log.error("Could not update job %s (%s)", case_id, type(error).__name__)
            with self._dispatch:
                if not self._scheduled[case_id]:
                    del self._scheduled[case_id]
                    return
                self._scheduled[case_id] = False
            recovering = False

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
        except ReviewRequired:
            # The private review request is durable. Keep checking until its
            # approval endpoint schedules a new run or the API restarts.
            return
        except Exception as error:
            # Provider and validation errors can include private request content.
            log.error("Judge job failed for %s (%s)", case_id, type(error).__name__)
            with self.store.transaction() as db:
                case = get_case(db, case_id)
                if case.status == "checking":
                    case.status = "failed"
                    case.progress.append(ProgressEvent(event="done"))
                    save_case(db, case)
