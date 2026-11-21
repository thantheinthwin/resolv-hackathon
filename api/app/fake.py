"""Judge boundary for the sample API."""

from pathlib import Path
from typing import Protocol

from api.app.contracts import Verdict


class Judge(Protocol):
    def run(self, case_dir: Path) -> Verdict: ...


SAMPLE_VERDICT = Path(__file__).resolve().parents[2] / "judge/fixtures/verdict.sample.json"


def write_sample_verdict(case_dir: Path) -> Verdict:
    verdict = Verdict.model_validate_json(SAMPLE_VERDICT.read_text(encoding="utf-8"))
    verdict.case_id = case_dir.name
    (case_dir / "verdict.json").write_text(verdict.model_dump_json(), encoding="utf-8")
    return verdict


class FakeJudge:
    def run(self, case_dir: Path) -> Verdict:
        return write_sample_verdict(case_dir)
