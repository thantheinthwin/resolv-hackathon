from pathlib import Path

import cv2
import numpy as np

from api.app.contracts import Verdict
from api.app.sample import LISTING, ORDER
from judge import run
from judge.pipeline import Inputs


def test_flat_video_has_real_unclear_checks(tmp_path: Path) -> None:
    writer = cv2.VideoWriter(
        str(tmp_path / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 2, (64, 64)
    )
    for _ in range(10):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()
    inputs = Inputs(order=ORDER, listing=LISTING, claim_type="damaged", description="")
    result = run(tmp_path, inputs=inputs)
    assert result.checks["continuity"].status == "unclear"
    assert result.steps[0].name == "sampling"
    assert Verdict.model_validate_json((tmp_path / "verdict.json").read_bytes()) == result
