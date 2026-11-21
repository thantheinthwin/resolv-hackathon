"""Evidence analysis entry point for buyer complaints."""

from pathlib import Path
from tempfile import NamedTemporaryFile
from collections.abc import Sequence

from api.app.contracts import Verdict
from judge.pipeline import Inputs, Review, analyze


def run(
    case_dir: str | Path,
    *,
    inputs: Inputs | None = None,
    photos: Sequence[bytes] = (),
    review: Review | None = None,
) -> Verdict:
    """Analyze a case and atomically publish its verdict. Empty scaffold cases use the demo fixture."""
    directory = Path(case_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if inputs is not None:
        verdict = analyze(directory, inputs, photos, review)
    elif (directory / "video.mp4").exists():
        raise ValueError("Case metadata is required to analyze an uploaded video.")
    else:
        fixture = Path(__file__).parent / "fixtures" / "verdict.sample.json"
        sample = Verdict.model_validate_json(fixture.read_bytes())
        verdict = Verdict.model_validate({**sample.model_dump(), "case_id": directory.name})
    # Readers should see either the previous complete verdict or the new one.
    output = NamedTemporaryFile(dir=directory, delete=False)
    temporary_path = Path(output.name)
    try:
        with output:
            output.write((verdict.model_dump_json(indent=2) + "\n").encode("utf-8"))
        temporary_path.replace(directory / "verdict.json")
    finally:
        temporary_path.unlink(missing_ok=True)
    return verdict
