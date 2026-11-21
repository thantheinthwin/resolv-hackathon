"""Temporary formatter diagnostic. Must be removed before this PR merges."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("name", ["matching.py", "test_matching.py"])
def test_formatter_preview(tmp_path: Path, name: str) -> None:
    source = Path("judge") / name
    if name.startswith("test_"):
        source = Path("judge/tests") / name
    code = source.read_text(encoding="utf-8").removeprefix("# fmt: off\n")
    target = tmp_path / name
    target.write_text(code, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--diff", str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode in (0, 1)
    if result.stdout:
        pytest.fail("RUFF_FORMAT_DIFF\n" + result.stdout, pytrace=False)
