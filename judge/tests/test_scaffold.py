import json
import subprocess
import sys
from pathlib import Path

import pytest

from judge import run
from judge.__main__ import main


def test_run_returns_and_persists_sample_verdict(tmp_path: Path) -> None:
    from api.app.contracts import Verdict

    verdict = run(tmp_path)
    saved = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    assert isinstance(verdict, Verdict)
    assert verdict.model_dump(mode="json") == saved
    assert verdict.verdict == "needs_human"
    assert verdict.display == "unsure"
    assert verdict.leaning == "none"
    assert verdict.confidence == 0
    assert verdict.case_id == tmp_path.name


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


def test_cli_accepts_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    video = tmp_path / "example.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=white:s=32x32:r=2:d=5",
            "-c:v",
            "mpeg4",
            str(video),
        ],
        check=True,
    )
    monkeypatch.setattr(sys, "argv", ["judge", str(video)])
    main()
    verdict = json.loads(capsys.readouterr().out)
    saved = tmp_path / "data" / "cases" / verdict["case_id"] / "verdict.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == verdict
    assert verdict["verdict"] == "needs_human"


def test_cli_rejects_invalid_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    video = tmp_path / "example.mp4"
    video.touch()
    monkeypatch.setattr(sys, "argv", ["judge", str(video)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "empty" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()


def test_cli_creates_missing_directory_with_dotted_name(tmp_path: Path) -> None:
    case_dir = tmp_path / "case.v1"
    result = subprocess.run(
        [sys.executable, "-m", "judge", str(case_dir)],
        capture_output=True,
        text=True,
        check=True,
    )
    verdict = json.loads(result.stdout)
    assert verdict["case_id"] == case_dir.name
    assert json.loads((case_dir / "verdict.json").read_bytes()) == verdict
