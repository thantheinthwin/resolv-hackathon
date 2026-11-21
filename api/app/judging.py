"""Case-to-judge adapter and content-bound handoff for reviewed demo recordings."""

import hashlib
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from api.app.contracts import Case, Verdict
from api.app.sample import ORDER
from api.app.store import Store, get_case
from judge import JudgeInputs, ReviewRequest, ReviewRequired, run
from judge.intake import inspect_video
from judge.pipeline import Review
from judge.matching import ReviewedListingPhoto
from judge.local import run_local


class CaseJudge:
    def __init__(self, store: Store):
        self.store = store

    def _context(self, case_id: str) -> tuple[Case, bytes]:
        with self.store.connection() as db:
            case = get_case(db, case_id)
        # The catalog currently accepts cases only for this order.
        if case.order_id != ORDER.id:
            raise ValueError("The case order is unavailable.")
        photo = Path(__file__).resolve().parents[1] / "fixtures" / "tee.png"
        return case, photo.read_bytes()

    def _review_path(self, directory: Path, case: Case, photo: bytes) -> Path:
        with (directory / "video.mp4").open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256")
        for data in [
            case.claim_type.encode(),
            case.description.encode(),
            ORDER.model_dump_json().encode(),
            photo,
        ]:
            digest.update(hashlib.sha256(data).digest())
        return self.store.root / ".judge-reviews" / directory.name / digest.hexdigest()

    def run(self, directory: Path) -> Verdict:
        case, photo = self._context(directory.name)
        reviewed = self._review_path(directory, case, photo)
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
    def _uploadable(self, case_id: str) -> Iterator[None]:
        # Serialize publication with the upload claim, never with model calls.
        with self.store.transaction() as db:
            if get_case(db, case_id).status not in {"awaiting_video", "failed"}:
                raise ValueError("Review must finish before an upload is accepted for this case.")
            yield

    def prepare(self, case_id: str, video: Path, review: Review) -> Verdict:
        with self._uploadable(case_id):
            case, photo = self._context(case_id)
        root = self.store.root / ".judge-reviews" / case_id
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with TemporaryDirectory(dir=root) as tmp:
            directory = Path(tmp) / case_id
            directory.mkdir()
            clip = directory / "video.mp4"
            shutil.copyfile(video, clip)
            inspect_video(clip)
            dest = self._review_path(directory, case, photo)
            with self._uploadable(case_id):
                if dest.is_dir():
                    return Verdict.model_validate_json((dest / "verdict.json").read_bytes())
            if not review(ReviewRequest("visual", "Listing photo", (("listing/tee.png", photo),))):
                raise ReviewRequired("visual")
            image = cv2.imdecode(np.frombuffer(photo, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("Could not decode listing photo.")
            inputs = JudgeInputs(
                order=ORDER,
                listing=ORDER.listing,
                claim_type=case.claim_type,
                description=case.description,
                listing_photos=(ReviewedListingPhoto(image=image, privacy_reviewed=True),),
            )
            verdict = run(directory, inputs=inputs, review=review)
            clip.unlink()
            shutil.rmtree(directory / ".judge-cache", ignore_errors=True)
            with self._uploadable(case_id):
                if dest.is_dir():
                    return Verdict.model_validate_json((dest / "verdict.json").read_bytes())
                directory.rename(dest)
            return verdict
