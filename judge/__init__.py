"""Evidence analysis entry point for buyer complaints."""

from pathlib import Path

from api.app.contracts import Verdict
from judge.opening_review import OpeningReviewer
from judge.pipeline import (
    JudgeInputs,
    PipelineError,
    Progress,
    Review,
    ReviewRequest,
    ReviewRequired,
    run_uploaded_case,
    write_atomically,
)
from judge.vision import VisionClient

__all__ = ["JudgeInputs", "PipelineError", "ReviewRequest", "ReviewRequired", "run"]


def run(
    case_dir: str | Path,
    inputs: JudgeInputs | None = None,
    *,
    review: Review | None = None,
    opening_review: OpeningReviewer | None = None,
    progress: Progress | None = None,
    model: str | None = None,
    client: VisionClient | None = None,
) -> Verdict:
    """Return and atomically persist the verdict for an uploaded case or fixture."""
    directory = Path(case_dir).resolve()
    if inputs is None:
        video = directory / "video.mp4"
        if video.exists() or video.is_symlink():
            raise PipelineError("An uploaded video requires trusted JudgeInputs.")
        directory.mkdir(parents=True, exist_ok=True)
        fixture = Path(__file__).parent / "fixtures" / "verdict.sample.json"
        sample = Verdict.model_validate_json(fixture.read_bytes())
        verdict = Verdict.model_validate({**sample.model_dump(), "case_id": directory.name})
    else:
        verdict = run_uploaded_case(
            directory,
            inputs,
            review=review,
            opening_review=opening_review,
            progress=progress,
            model=model,
            client=client,
        )
    write_atomically(
        directory / "verdict.json", (verdict.model_dump_json(indent=2) + "\n").encode("utf-8")
    )
    return verdict
