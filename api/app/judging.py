"""Case-to-judge adapter and content-bound handoff for reviewed demo recordings."""

import hashlib
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from api.app.catalog import delivered_order
from api.app.contracts import Case, Verdict
from api.app.sample import LISTING, OrderWithListing
from api.app.store import Store, get_case
from judge import JudgeInputs, ReviewRequest, ReviewRequired, run
from judge.intake import inspect_video
from judge.pipeline import Review
from judge.matching import ReviewedListingPhoto
from judge.local import run_local


@dataclass(frozen=True, repr=False)
class _ReviewContext:
    case: Case
    order: OrderWithListing
    photos: tuple[tuple[str, bytes], ...]


def _context(db: sqlite3.Connection, case: Case) -> _ReviewContext:
    order = delivered_order(db, case.order_id)
    photos = []
    for position, url in enumerate(order.listing.photos, 1):
        if order.listing_id == LISTING.id and url == "/api/files/listings/sample/tee.png":
            photo = Path(__file__).resolve().parents[1] / "fixtures" / "tee.png"
            photos.append(("listing/tee.png", photo.read_bytes()))
            continue
        if not url.startswith(f"/api/files/listings/{order.listing_id}/"):
            raise ValueError("Listing photo does not belong to this product.")
        row = db.execute(
            "SELECT mime, image FROM listing_photos WHERE path = ?",
            (url.removeprefix("/api/files/"),),
        ).fetchone()
        if row is None:
            raise ValueError("A listing photo is unavailable.")
        mime, data = row
        extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(mime)
        if extension is None:
            raise ValueError("Unsupported listing photo format.")
        # The host preview uses these names as paths; generate them on the server.
        photos.append((f"listing/{position}.{extension}", data))
    return _ReviewContext(case, order, tuple(photos))


class CaseJudge:
    def __init__(self, store: Store):
        self.store = store

    def _review_path(self, directory: Path, context: _ReviewContext) -> Path:
        with (directory / "video.mp4").open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256")
        for data in (
            context.case.claim_type.encode(),
            context.case.description.encode(),
            context.order.model_dump_json().encode(),
            *(photo for _, photo in context.photos),
        ):
            digest.update(hashlib.sha256(data).digest())
        return self.store.root / ".judge-reviews" / directory.name / digest.hexdigest()

    def run(self, directory: Path) -> Verdict:
        with self.store.connection() as db:
            # Read the case, its order, and all catalog photos from one snapshot.
            db.execute("BEGIN")
            case = get_case(db, directory.name)
            context = None
            if (self.store.root / ".judge-reviews" / case.id).is_dir():
                try:
                    context = _context(db, case)
                except (ValueError, FileNotFoundError):
                    # Unavailable catalog input cannot match an approved request.
                    pass
        if context is None:
            return run_local(directory, case.claim_type, case.order_id)
        reviewed = self._review_path(directory, context)
        if not reviewed.is_dir():
            return run_local(directory, case.claim_type, case.order_id)
        verdict = Verdict.model_validate_json((reviewed / "verdict.json").read_bytes())
        if verdict.case_id != directory.name:
            raise ValueError("Reviewed verdict belongs to another case.")
        for ref in {r for pair in verdict.evidence for r in (pair.frame, pair.listing_photo)}:
            dest = directory / ref
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(reviewed / ref, dest)
        # Publish last so crash recovery only finds a complete evidence pack.
        temp = directory / ".reviewed-verdict.tmp"
        temp.write_text(verdict.model_dump_json(), encoding="utf-8")
        temp.replace(directory / "verdict.json")
        return verdict

    @contextmanager
    def _uploadable(self, case_id: str) -> Iterator[tuple[sqlite3.Connection, Case]]:
        # Serialize publication with the upload claim, never with model calls.
        with self.store.transaction() as db:
            case = get_case(db, case_id)
            if case.status not in {"awaiting_video", "failed"}:
                raise ValueError("Review must finish before an upload is accepted for this case.")
            yield db, case

    def prepare(self, case_id: str, video: Path, review: Review) -> Verdict:
        with self._uploadable(case_id) as (db, case):
            context = _context(db, case)
        root = self.store.root / ".judge-reviews" / case_id
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with TemporaryDirectory(dir=root) as tmp:
            directory = Path(tmp) / case_id
            directory.mkdir()
            clip = directory / "video.mp4"
            shutil.copyfile(video, clip)
            inspect_video(clip)
            dest = self._review_path(directory, context)
            with self._uploadable(case_id):
                if dest.is_dir():
                    return Verdict.model_validate_json((dest / "verdict.json").read_bytes())
            request = ReviewRequest("visual", "Listing photos", context.photos)
            if review(request) is not True:
                raise ReviewRequired("visual")
            reviewed_photos = []
            for _, photo in context.photos:
                image = cv2.imdecode(np.frombuffer(photo, dtype=np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError("Could not decode listing photo.")
                reviewed_photos.append(ReviewedListingPhoto(image=image, privacy_reviewed=True))
            inputs = JudgeInputs(
                order=context.order,
                listing=context.order.listing,
                claim_type=context.case.claim_type,
                description=context.case.description,
                listing_photos=tuple(reviewed_photos),
            )
            verdict = run(directory, inputs=inputs, review=review)
            clip.unlink()
            shutil.rmtree(directory / ".judge-cache", ignore_errors=True)
            with self._uploadable(case_id):
                if dest.is_dir():
                    return Verdict.model_validate_json((dest / "verdict.json").read_bytes())
                directory.rename(dest)
            return verdict
