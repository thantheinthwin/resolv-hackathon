"""Evidence analysis entry point for buyer complaints."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from api.app.contracts import Verdict


def run(case_dir: str | Path) -> Verdict:
    """Return the unassessed fixture and persist the same verdict for the API."""
    directory = Path(case_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
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
