"""The operator's pre-upload command requests a local opening review."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from api import review_video
from judge.opening_review import prompt_opening_review


def test_preparation_uses_local_opening_prompt(tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    args = ["review_video", "UJ-DEMO", str(video), "--data-dir", str(tmp_path)]
    with patch.object(sys, "argv", args), patch.object(review_video, "CaseJudge") as worker:
        prepare = worker.return_value.prepare
        prepare.return_value = SimpleNamespace(case_id="UJ-DEMO")
        review_video.main()
    prepare.assert_called_once_with(
        "UJ-DEMO", video, review_video.review, opening_review=prompt_opening_review
    )
