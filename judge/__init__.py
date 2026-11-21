"""Evidence analysis entry point for buyer complaints.

This is a deliberately conservative scaffold, not a video analyzer.
"""

import json
from pathlib import Path
from typing import Any


def run(case_dir: str | Path) -> dict[str, Any]:
    """Return and persist an explicitly unassessed sample verdict.

    The real judge will replace this implementation after the API's shared
    Pydantic Verdict contract is available.
    """
    directory = Path(case_dir)
    directory.mkdir(parents=True, exist_ok=True)
    fixture = Path(__file__).parent / "fixtures" / "verdict.sample.json"
    verdict: dict[str, Any] = json.loads(fixture.read_text(encoding="utf-8"))
    verdict["case_id"] = directory.name
    (directory / "verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return verdict
