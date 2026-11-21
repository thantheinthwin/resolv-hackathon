from pathlib import Path

import cv2
import numpy as np
import pytest

from api.app.contracts import Verdict
from judge.local import run_local
from judge.sampling import SampledFrame
from judge.submission import SubmissionResult


def _write_flat_video(tmp_path: Path) -> None:
    writer = cv2.VideoWriter(
        str(tmp_path / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 2, (64, 64)
    )
    for _ in range(10):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()


def test_flat_video_has_real_unclear_checks(tmp_path: Path) -> None:
    _write_flat_video(tmp_path)
    result = run_local(tmp_path, "damaged", "UJ-48213")
    assert result.checks["continuity"].status == "unclear"
    assert result.steps[0].name == "sampling"
    assert Verdict.model_validate_json((tmp_path / "verdict.json").read_bytes()) == result


def test_product_link_saves_evidence_request_with_compatible_verdict(tmp_path: Path) -> None:
    _write_flat_video(tmp_path)
    result = run_local(tmp_path, "wrong_item", "")
    submission = SubmissionResult.model_validate_json((tmp_path / "submission.json").read_bytes())

    assert submission.feedback is not None
    assert submission.feedback.result == "needs_more_evidence"
    assert result.reason.en == "Please confirm which item and variant you ordered."
    assert result.reason == submission.feedback.reason
    assert submission.verdict == result
    assert result == Verdict.model_validate_json((tmp_path / "verdict.json").read_bytes())


def test_linked_case_with_usable_frames_asks_shop_to_review_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = SampledFrame(
        timestamp_seconds=0,
        image=np.full((64, 64, 3), 200, dtype=np.uint8),
        blur_score=200,
        scene_change=False,
    )
    monkeypatch.setattr("judge.local.sample_frames", lambda path: [frame])
    result = run_local(tmp_path, "wrong_item", "UJ-48213")
    saved = SubmissionResult.model_validate_json((tmp_path / "submission.json").read_bytes())

    assert saved.verdict == result
    assert saved.feedback is not None and saved.feedback.result == "needs_more_evidence"
    assert "product comparison" in saved.feedback.reason.en
