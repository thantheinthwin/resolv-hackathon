"""Judge boundary for the sample API."""

from pathlib import Path
from typing import Protocol

from api.app.contracts import Verdict


class Judge(Protocol):
    def run(self, case_dir: Path) -> Verdict: ...


class FakeJudge:
    def run(self, case_dir: Path) -> Verdict:
        sample = Path(__file__).resolve().parents[2] / "judge/fixtures/verdict.sample.json"
        verdict = Verdict.model_validate_json(sample.read_text(encoding="utf-8"))
        verdict.case_id = case_dir.name
        (case_dir / "verdict.json").write_text(verdict.model_dump_json(), encoding="utf-8")
        return verdict
