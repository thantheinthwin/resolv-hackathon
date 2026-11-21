import json
import subprocess
import sys
from pathlib import Path

from judge import run


def test_run_returns_and_persists_sample_verdict(tmp_path: Path) -> None:
    verdict = run(tmp_path)
    saved = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    assert verdict == saved
    assert verdict["verdict"] == "needs_human"
    assert verdict["display"] == "unsure"
    assert verdict["leaning"] == "none"
    assert 0 <= verdict["confidence"] <= 1
    assert verdict["case_id"] == tmp_path.name


def test_cli_emits_json_and_writes_verdict(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "judge", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == json.loads(
        (tmp_path / "verdict.json").read_text(encoding="utf-8")
    )
