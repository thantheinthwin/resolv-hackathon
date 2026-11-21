"""Case-to-judge adapter and content-bound handoff for reviewed demo recordings."""

import hashlib
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from api.app.contracts import Verdict
from api.app.sample import ORDER
from api.app.store import Store, get_case
from judge import run
from judge.intake import inspect_video
from judge.pipeline import Inputs, Review


class CaseJudge:
    def __init__(self, store: Store):
        self.store = store

    def _context(self, case_id: str) -> tuple[Inputs, list[bytes]]:
        with self.store.connection() as db:
            case = get_case(db, case_id)
        # The catalog currently accepts cases only for this order.
        if case.order_id != ORDER.id:
            raise ValueError("The case order is unavailable.")
        photo = Path(__file__).resolve().parents[1] / "fixtures" / "tee.png"
        return Inputs(
            order=ORDER,
            listing=ORDER.listing,
            claim_type=case.claim_type,
            description=case.description,
        ), [photo.read_bytes()]

    def _review_path(self, directory: Path, inputs: Inputs, photos: list[bytes]) -> Path:
        with (directory / "video.mp4").open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256")
        for data in [inputs.model_dump_json().encode(), *photos]:
            digest.update(hashlib.sha256(data).digest())
        return self.store.root / ".judge-reviews" / directory.name / digest.hexdigest()

    def run(self, directory: Path) -> Verdict:
        inputs, photos = self._context(directory.name)
        reviewed = self._review_path(directory, inputs, photos)
        if not reviewed.is_dir():
            return run(directory, inputs=inputs)
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
            inputs, photos = self._context(case_id)
        root = self.store.root / ".judge-reviews" / case_id
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with TemporaryDirectory(dir=root) as tmp:
            directory = Path(tmp) / case_id
            directory.mkdir()
            clip = directory / "video.mp4"
            shutil.copyfile(video, clip)
            inspect_video(clip)
            dest = self._review_path(directory, inputs, photos)
            with self._uploadable(case_id):
                if dest.is_dir():
                    return Verdict.model_validate_json((dest / "verdict.json").read_bytes())
            verdict = run(directory, inputs=inputs, photos=photos, review=review)
            clip.unlink()
            shutil.rmtree(directory / "cache", ignore_errors=True)
            with self._uploadable(case_id):
                if dest.is_dir():
                    return Verdict.model_validate_json((dest / "verdict.json").read_bytes())
                directory.rename(dest)
            return verdict
