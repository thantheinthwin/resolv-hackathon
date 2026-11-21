"""Trusted local seal and parcel-label review."""

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from judge.opening_review import (
    OpeningReviewError,
    OpeningReviewRequest,
    OpeningReviewSelection,
    collect_opening_review,
    prompt_opening_review,
)
from judge.privacy import RedactionRegion
from judge.sampling import SampledFrame

REGION = RedactionRegion(x=2, y=3, width=12, height=8)


def frame(t: float) -> SampledFrame:
    return SampledFrame(
        timestamp_seconds=t,
        image=np.full((32, 48, 3), 180, dtype=np.uint8),
        blur_score=100,
        scene_change=False,
    )


def test_operator_sees_exact_early_frames_and_only_the_selected_frame_sets_time() -> None:
    def review(request: OpeningReviewRequest) -> OpeningReviewSelection:
        assert [preview.timestamp_seconds for preview in request.frames] == [0.1254, 10.0]
        assert [preview.number for preview in request.frames] == [1, 2]
        pixels = cv2.imdecode(
            np.frombuffer(request.frames[1].jpeg, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        assert pixels.shape == (32, 48, 3)
        assert "jpeg=" not in repr(request)
        return OpeningReviewSelection(
            frame_number=2, seal_state="intact", order_code=" UJ-48721 ", label_region=REGION
        )

    result = collect_opening_review([frame(0.1254), frame(10), frame(10.001)], review)
    assert result is not None
    observation, region = result
    assert observation.timestamp_seconds == 10.0
    assert observation.seal_state == "intact" and observation.seal_confidence == 1
    assert observation.observed_order_id == "UJ-48721" and observation.label_confidence == 1
    assert region == REGION
    assert "UJ-48721" not in repr(observation)


def test_skip_and_no_early_frames_leave_opening_unknown() -> None:
    def should_not_call(request: OpeningReviewRequest) -> OpeningReviewSelection:
        pytest.fail("No early frames were available")

    assert collect_opening_review([frame(12)], should_not_call) is None
    assert collect_opening_review([frame(0)], lambda request: None) is None


def test_unclear_seal_and_unreadable_label_preserve_a_requested_mask() -> None:
    selection = OpeningReviewSelection(frame_number=1, seal_state="unclear", label_region=REGION)
    result = collect_opening_review([frame(0)], lambda request: selection)
    assert result is not None
    observation, region = result
    assert observation.seal_confidence == observation.label_confidence == 0
    assert observation.observed_order_id is None
    assert region == REGION


def test_order_code_requires_a_label_mask_and_is_hidden_in_selection_repr() -> None:
    with pytest.raises(ValidationError, match="label mask") as error:
        OpeningReviewSelection(frame_number=1, seal_state="opened", order_code="private-code")
    assert "private-code" not in str(error.value)
    selection = OpeningReviewSelection(
        frame_number=1, seal_state="opened", order_code="private-code", label_region=REGION
    )
    assert "private-code" not in repr(selection)


@pytest.mark.parametrize(
    ("number", "region", "message"),
    [
        (2, REGION, "displayed"),
        (1, RedactionRegion(x=42, y=3, width=12, height=8), "inside"),
    ],
)
def test_invalid_choice_is_rejected_before_any_external_processing(
    number: int, region: RedactionRegion, message: str
) -> None:
    with pytest.raises(OpeningReviewError, match=message):
        collect_opening_review(
            [frame(0.3)],
            lambda request: OpeningReviewSelection(
                frame_number=number, seal_state="intact", label_region=region
            ),
        )


def test_terminal_prompt_can_inspect_two_frames_and_enter_a_code_privately(
    capsys: pytest.CaptureFixture[str],
) -> None:
    answers = iter(["4", "1", "back", "2", "opened", "not a rectangle", "2 3 12 8"])
    shown: list[float] = []

    def operator(request: OpeningReviewRequest) -> OpeningReviewSelection | None:
        return prompt_opening_review(
            request,
            show=lambda preview: shown.append(preview.timestamp_seconds),
            read=lambda _: next(answers),
            read_code=lambda _: "UJ-99887",
        )

    result = collect_opening_review([frame(1), frame(2)], operator)
    assert result is not None
    assert shown == [1.0, 2.0]
    assert result[0].seal_state == "opened"
    assert result[0].observed_order_id == "UJ-99887"
    assert result[1] == REGION
    output = capsys.readouterr().out
    assert "UJ-99887" not in output
