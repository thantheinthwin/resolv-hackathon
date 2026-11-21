"""Case-to-judge adapter and content-bound handoff for reviewed demo recordings."""

import hashlib
import re
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from api.app.contracts import ClaimType, ProgressEvent, Verdict
from api.app.jobs import persist_progress
from api.app.reviews import require_approval
from api.app.sample import ORDER, OrderWithListing
from api.app.store import Store, get_case
from judge import JudgeInputs, ReviewRequest, ReviewRequired, run
from judge.config import get_secret
from judge.evidence import ASSET_NAME
from judge.intake import inspect_video
from judge.local import run_local
from judge.matching import ReviewedListingPhoto
from judge.opening_review import OpeningReviewer
from judge.pipeline import Progress, Review, write_atomically
from judge.vision import VisionClient, _encode_jpeg


class CaseInputs(BaseModel):
    """Immutable local input snapshot, removed along with the upload directory."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", ser_json_bytes="base64", val_json_bytes="base64"
    )

    claim_type: ClaimType
    description: str = Field(repr=False)
    order: OrderWithListing = Field(repr=False)
    photos: tuple[bytes, ...] = Field(min_length=1, max_length=3, repr=False)

    def reviewed_inputs(self, review: Review) -> JudgeInputs:
        images = []
        for data in self.photos:
            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("Could not decode listing photo.")
            images.append(image)
        request = ReviewRequest(
            "visual",
            "Inspect each listing photo for personal information before external processing.",
            tuple(
                (f"listing/{index}.jpg", _encode_jpeg(image)) for index, image in enumerate(images)
            ),
        )
        if review(request) is not True:
            raise ReviewRequired(request.stage)
        return JudgeInputs(
            order=self.order,
            listing=self.order.listing,
            claim_type=self.claim_type,
            description=self.description,
            listing_photos=tuple(
                ReviewedListingPhoto(image=image, privacy_reviewed=True) for image in images
            ),
        )


def _local_photo(db: sqlite3.Connection, ref: str) -> bytes:
    if ref == "/api/files/listings/sample/tee.png":
        return (Path(__file__).resolve().parents[1] / "fixtures" / "tee.png").read_bytes()
    if ref.startswith("/api/files/listings/"):
        row = db.execute(
            "SELECT image FROM listing_photos WHERE path=?", (ref.removeprefix("/api/files/"),)
        ).fetchone()
        if row is not None:
            return row[0]
    raise ValueError("The stored listing photo is unavailable.")


class CaseJudge:
    def __init__(
        self, store: Store, *, model: str | None = None, client: VisionClient | None = None
    ) -> None:
        self.store = store
        self.model = model
        self.client = client

    def _context(self, case_id: str) -> CaseInputs:
        with self.store.connection() as db:
            case = get_case(db, case_id)
            # The catalog currently accepts cases only for this order.
            if case.order_id != ORDER.id or ORDER.listing.id != ORDER.listing_id:
                raise ValueError("The case order or listing is unavailable.")
            photos = tuple(_local_photo(db, ref) for ref in ORDER.listing.photos)
        return CaseInputs(
            claim_type=case.claim_type, description=case.description, order=ORDER, photos=photos
        )

    def _review_path(self, directory: Path, context: CaseInputs) -> Path:
        with (directory / "video.mp4").open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256")
        for data in [
            context.claim_type.encode(),
            context.description.encode(),
            context.order.model_dump_json().encode(),
            *context.photos,
        ]:
            digest.update(hashlib.sha256(data).digest())
        return self.store.root / ".judge-reviews" / directory.name / digest.hexdigest()

    def run(self, directory: Path) -> Verdict:
        progress = partial(persist_progress, self.store, directory.name)
        snapshot = directory / ".judge-inputs.json"
        if snapshot.exists():
            context = CaseInputs.model_validate_json(snapshot.read_bytes())
        else:
            context = self._context(directory.name)
            reviewed = self._review_path(directory, context)
            if reviewed.is_dir():
                return self._publish_prepared(directory, reviewed, progress)
            if self.client is None and not get_secret("OPENAI_API_KEY"):
                return run_local(directory, context.claim_type, context.order.id, progress=progress)
            write_atomically(snapshot, context.model_dump_json().encode())

        model = self.model or get_secret("OPENAI_MODEL")
        if not model or (self.client is None and not get_secret("OPENAI_API_KEY")):
            raise ValueError("Model judging requires OPENAI_MODEL and OPENAI_API_KEY.")
        review = partial(require_approval, self.store, directory.name)
        return run(
            directory,
            inputs=context.reviewed_inputs(review),
            review=review,
            progress=progress,
            client=self.client,
            model=model,
        )

    def _publish_prepared(self, directory: Path, reviewed: Path, progress: Progress) -> Verdict:
        root = self.store.root.resolve()
        source = root / ".judge-reviews" / directory.name / reviewed.name
        target = root / "cases" / directory.name
        verdict_path = source / "verdict.json"
        if directory.resolve() != target or verdict_path.resolve() != verdict_path:
            raise ValueError("Invalid prepared verdict path.")
        verdict = Verdict.model_validate_json(verdict_path.read_bytes())
        if verdict.case_id != directory.name:
            raise ValueError("Reviewed verdict belongs to another case.")

        # Validate the entire pack before creating an asset directory or writing files.
        assets: set[str] = set()
        for pair in verdict.evidence:
            for kind, ref in (("frames", pair.frame), ("listing", pair.listing_photo)):
                if not re.fullmatch(rf"{kind}/{ASSET_NAME}", ref):
                    raise ValueError("Invalid prepared evidence reference.")
                src, dest = source / ref, target / ref
                if src.resolve() != src or dest.resolve() != dest or not src.is_file():
                    raise ValueError("Invalid prepared evidence path.")
                assets.add(ref)
        for ref in assets:
            dest = target / ref
            dest.parent.mkdir(mode=0o700, exist_ok=True)
            write_atomically(dest, (source / ref).read_bytes())
        for step in verdict.steps:
            progress(ProgressEvent(event="started", step=step.name))
            progress(ProgressEvent(event="finished", step=step.name))
        # Publish last so crash recovery only finds a complete evidence pack and stage history.
        write_atomically(target / "verdict.json", verdict.model_dump_json().encode())
        return verdict

    @contextmanager
    def _uploadable(self, case_id: str) -> Iterator[None]:
        # Serialize publication with the upload claim, never with model calls.
        with self.store.transaction() as db:
            if get_case(db, case_id).status not in {"awaiting_video", "failed"}:
                raise ValueError("Review must finish before an upload is accepted for this case.")
            yield

    def prepare(
        self,
        case_id: str,
        video: Path,
        review: Review,
        *,
        opening_review: OpeningReviewer | None = None,
    ) -> Verdict:
        with self._uploadable(case_id):
            context = self._context(case_id)
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
            verdict = run(
                directory,
                inputs=context.reviewed_inputs(review),
                review=review,
                opening_review=opening_review,
                client=self.client,
                model=self.model,
            )
            clip.unlink()
            shutil.rmtree(directory / ".judge-cache", ignore_errors=True)
            with self._uploadable(case_id):
                if dest.is_dir():
                    return Verdict.model_validate_json((dest / "verdict.json").read_bytes())
                directory.rename(dest)
            return verdict
