"""Conservative integrity heuristics, using sanitized frames only."""

from pathlib import Path

import numpy as np
import pytest

from judge.integrity import (
    IntegrityError,
    OpeningObservation,
    assess_integrity,
)
from judge.privacy import SanitizedFrame
from judge.sampling import SampledFrame


def frame(seed: int, timestamp: float, *, flat: bool = False) -> SanitizedFrame:
    image = (
        np.full((96, 96, 3), 125, dtype=np.uint8)
        if flat
        else np.random.default_rng(seed).integers(0, 256, (96, 96, 3), dtype=np.uint8)
    )
    return SanitizedFrame(
        timestamp_seconds=timestamp,
        image=image,
        faces_redacted=0,
        regions_redacted=0,
    )


def steady_frames() -> list[SanitizedFrame]:
    image = np.random.default_rng(25).integers(0, 256, (96, 96, 3), dtype=np.uint8)
    frames = []
    for index in range(7):
        noise = np.random.default_rng(index).integers(-3, 4, image.shape)
        jittered = np.clip(image.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        frames.append(frame(0, float(index)).model_copy(update={"image": jittered}))
    return frames


def opening(
    *, t: float = 0.0, seal: str = "intact", code: str | None = "UJ-48213"
) -> OpeningObservation:
    return OpeningObservation(
        timestamp_seconds=t,
        seal_state=seal,
        seal_confidence=0.96,
        observed_order_id=code,
        label_confidence=0.93,
    )


def test_no_strong_change_is_not_proof_of_unedited_video() -> None:
    report = assess_integrity(steady_frames(), expected_order_id="UJ-48213")
    check = report.checks["continuity"]
    assert check.status == "pass"
    assert "does not prove the video is unedited" in check.note_en
    assert not report.flags
    assert report.checks["seal"].status == "unclear"
    assert report.checks["label"].status == "unclear"


def test_sudden_cut_produces_timestamped_fraud_signal() -> None:
    frames = steady_frames()
    cut = frame(4242, 7.0)
    frames.extend([cut, frame(4242, 8.0)])
    report = assess_integrity(frames, expected_order_id="UJ-48213")
    assert report.checks["continuity"].status == "flag"
    assert any(flag.type == "cut" and flag.t == 7.0 for flag in report.flags)
    assert report.requires_human_review
    assert report.checks["continuity"].findings[0].t == 7.0


def test_too_few_frames_stay_unclear() -> None:
    report = assess_integrity([frame(1, 0.0), frame(2, 1.0)], expected_order_id="UJ-48213")
    assert report.checks["continuity"].status == "unclear"
    assert report.requires_human_review


def test_large_time_gap_is_not_called_a_cut() -> None:
    frames = steady_frames()[:3] + [frame(999, 12.0)]
    report = assess_integrity(frames, expected_order_id="UJ-48213")
    assert report.checks["continuity"].status == "unclear"
    assert not any(flag.type == "cut" for flag in report.flags)


def test_blurry_transition_not_used_as_proof_of_cut() -> None:
    frames = steady_frames()[:4] + [frame(42, 4.0, flat=True)]
    report = assess_integrity(frames, expected_order_id="UJ-48213")
    assert not any(flag.type == "cut" for flag in report.flags)
    assert report.checks["continuity"].status == "unclear"


def test_opened_seal_requires_human_and_has_grounded_timestamp() -> None:
    report = assess_integrity(
        steady_frames(), expected_order_id="UJ-48213", observation=opening(seal="opened")
    )
    assert report.checks["seal"].status == "flag"
    assert any(flag.type == "seal_opened" and flag.t == 0.0 for flag in report.flags)
    assert report.requires_human_review


def test_mismatched_label_flags_without_echoing_ids() -> None:
    report = assess_integrity(
        steady_frames(), expected_order_id="UJ-48213", observation=opening(code="UJ-98765")
    )
    assert report.checks["label"].status == "flag"
    assert any(flag.type == "label_mismatch" for flag in report.flags)
    assert "98765" not in report.model_dump_json()
    assert "48213" not in report.model_dump_json()


@pytest.mark.parametrize("code", ["UJ48213", "UJ-4821B", "UJ-4821", "UJ-482133"])
def test_one_character_ocr_tolerance(code: str) -> None:
    report = assess_integrity(
        steady_frames(), expected_order_id="UJ-48213", observation=opening(code=code)
    )
    assert report.checks["label"].status == "pass"
    assert not any(flag.type == "label_mismatch" for flag in report.flags)


def test_unreadable_label_is_unclear_not_match() -> None:
    report = assess_integrity(
        steady_frames(), expected_order_id="UJ-48213", observation=opening(code=None)
    )
    assert report.checks["label"].status == "unclear"


def test_ungrounded_opening_is_ignored() -> None:
    report = assess_integrity(
        steady_frames(), expected_order_id="UJ-48213", observation=opening(t=0.22, seal="opened")
    )
    assert report.checks["seal"].status == "unclear"
    assert report.checks["label"].status == "unclear"
    assert not report.flags


def test_opening_after_first_ten_seconds_is_not_accepted() -> None:
    frames = steady_frames() + [frame(8, 11.0)]
    report = assess_integrity(
        frames, expected_order_id="UJ-48213", observation=opening(t=11.0, seal="opened")
    )
    assert report.checks["seal"].status == "unclear"


def test_unsanitized_frame_is_rejected() -> None:
    raw = SampledFrame(
        timestamp_seconds=0.0,
        image=frame(1, 0.0).image,
        blur_score=100.0,
        scene_change=False,
    )
    with pytest.raises(IntegrityError, match="SanitizedFrame"):
        assess_integrity([raw], expected_order_id="UJ-48213")  # type: ignore[list-item]


def test_out_of_order_and_duplicate_timestamps_rejected() -> None:
    with pytest.raises(IntegrityError, match="increasing"):
        assess_integrity([frame(1, 1.0), frame(2, 1.0)], expected_order_id="UJ-48213")


def test_no_file_outputs(tmp_path: Path) -> None:
    assess_integrity(steady_frames(), expected_order_id="UJ-48213")
    assert list(tmp_path.iterdir()) == []


def test_low_confidence_opening_remains_unclear() -> None:
    weak = opening(seal="opened", code="UJ-98765").model_copy(
        update={"seal_confidence": 0.3, "label_confidence": 0.3}
    )
    report = assess_integrity(steady_frames(), expected_order_id="UJ-48213", observation=weak)
    assert report.checks["seal"].status == "unclear"
    assert report.checks["label"].status == "unclear"
    assert not report.flags


def test_invalid_empty_order_id_cannot_be_claimed_a_match() -> None:
    report = assess_integrity(steady_frames(), expected_order_id="", observation=opening(code="A"))
    assert report.checks["label"].status == "unclear"


def test_opening_findings_snap_to_supplied_frame_timestamp() -> None:
    report = assess_integrity(
        steady_frames(), expected_order_id="UJ-48213", observation=opening(t=0.03, seal="opened")
    )
    assert report.checks["seal"].findings[0].t == 0.0
    assert report.flags[0].t == 0.0


def test_nonmatching_two_character_ocr_errors_are_flagged() -> None:
    report = assess_integrity(
        steady_frames(), expected_order_id="UJ-48213", observation=opening(code="UJ-482BB")
    )
    assert report.checks["label"].status == "flag"


def test_report_validates_against_shared_verdict_contract() -> None:
    from api.app.contracts import Verdict

    report = assess_integrity(
        steady_frames(),
        expected_order_id="UJ-48213",
        observation=opening(seal="opened", code="UJ-98765"),
    )
    verdict = Verdict.model_validate(
        {
            "case_id": "UJ-48213",
            "verdict": "needs_human",
            "display": "unsure",
            "leaning": "none",
            "confidence": 0.0,
            "flags": [item.model_dump() for item in report.flags],
            "checks": {key: item.model_dump() for key, item in report.checks.items()},
            "evidence": [],
            "reason": {"en": "Needs human review.", "th": "ต้องให้เจ้าหน้าที่ตรวจสอบ"},
            "steps": [],
        }
    )
    assert verdict.display == "unsure"
    assert len(verdict.flags) == 2
    assert "label" in verdict.checks
