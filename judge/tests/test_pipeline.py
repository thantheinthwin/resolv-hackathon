"""Run the real worker with local video stages and a fake model transport."""

import json
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from api.app.contracts import ProgressEvent, Verdict
from api.app.sample import LISTING, ORDER
from judge import JudgeInputs, ReviewRequest, ReviewRequired, run
from judge.intake import IntakeResult
from judge.integrity import OpeningObservation
from judge.matching import ReviewedListingPhoto
from judge.opening_review import OpeningReviewRequest, OpeningReviewSelection
from judge.pipeline import PipelineError
from judge.privacy import RedactionRegion
from judge.sampling import NoSharpFrames, SampledFrame
from judge.submission import SubmissionResult, run_submission

DESCRIPTION = "เห็นรอยแตกเมื่อเปิดกล่อง private-complaint"
FINDING_TIME = 4.1254


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.lock = Lock()
        self.extra_finding = False

    def parse(self, **kwargs: object) -> SimpleNamespace:
        schema = kwargs["text_format"].__name__
        messages = kwargs["input"]
        with self.lock:
            self.calls.append((schema, str(messages)))
        assert kwargs["store"] is False
        if schema == "VisionObservation":
            result = {
                "status": "observed",
                "findings": [
                    {"t": 4.13, "category": "damage", "value": "crack", "confidence": 0.98}
                ],
                "note_en": "A crack is visible.",
            }
        elif schema == "MatchResponse":
            name = json.loads(messages[1]["content"][0]["text"].splitlines()[0])["check"]
            findings = (
                [{"t": 4.13, "note_en": "Crack on case.", "note_th": "ตัวเคสแตก"}]
                if name == "damage"
                else []
            )
            if findings and self.extra_finding:
                findings.insert(
                    0, {"t": 3.1254, "note_en": "Packaging crease.", "note_th": "กล่องมีรอยพับ"}
                )
            result = {
                "status": "flag" if findings else "pass",
                "confidence": 0.97,
                "findings": findings,
                "note_en": "Compared with listing.",
            }
        elif schema == "ComplaintSelection":
            result = {
                "confidence": 0.96,
                "allegations": [
                    {
                        "kind": "damage",
                        "finding_ids": [int(self.extra_finding)],
                        "supporting_finding_ids": [int(self.extra_finding)],
                    }
                ],
            }
        else:
            assert schema == "ReasonSelection"
            result = {"finding_id": 0}
        return SimpleNamespace(output_parsed=result)


@pytest.fixture
def case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, JudgeInputs, FakeResponses]:
    folder = tmp_path / "UJ-PIPELINE"
    folder.mkdir()
    (folder / "video.mp4").write_bytes(b"local test placeholder")
    grid = ((np.indices((64, 64)).sum(axis=0) % 2) * 255).astype(np.uint8)
    image = np.repeat(grid[:, :, None], 3, axis=2)
    frames = [
        SampledFrame(timestamp_seconds=i + 0.1254, image=image, blur_score=900, scene_change=False)
        for i in range(6)
    ]
    monkeypatch.setattr("judge.pipeline.sample_frames", lambda path: frames)
    monkeypatch.setattr(
        "judge.pipeline.inspect_video",
        lambda path: IntakeResult(
            duration_seconds=6,
            size_bytes=22,
            width=64,
            height=64,
            rotation_degrees=0,
            dark_frame_ratio=0,
        ),
    )
    inputs = JudgeInputs(
        claim_type="damaged",
        description=DESCRIPTION,
        order=ORDER,
        listing=LISTING,
        listing_photos=(ReviewedListingPhoto(image=image, privacy_reviewed=True),),
        opening=OpeningObservation(
            timestamp_seconds=frames[0].timestamp_seconds,
            seal_state="intact",
            seal_confidence=0.99,
            observed_order_id=ORDER.id,
            label_confidence=0.99,
        ),
        redactions_by_timestamp={FINDING_TIME: (RedactionRegion(x=0, y=0, width=16, height=16),)},
    )
    return folder, inputs, FakeResponses()


def test_run_writes_grounded_assets_and_shared_verdict(
    case: tuple[Path, JudgeInputs, FakeResponses],
) -> None:
    folder, inputs, responses = case
    reviews: list[ReviewRequest] = []
    progress: list[ProgressEvent] = []

    def approve(request: ReviewRequest) -> bool:
        reviews.append(request)
        return True

    verdict = run(
        folder,
        inputs,
        review=approve,
        progress=progress.append,
        model="test-model",
        client=SimpleNamespace(responses=responses),
    )

    assert (verdict.verdict, verdict.display, verdict.confidence) == ("buyer_right", "clear", 0.96)
    assert Verdict.model_validate_json((folder / "verdict.json").read_bytes()) == verdict
    saved = SubmissionResult.model_validate_json((folder / "submission.json").read_bytes())
    assert saved.verdict == verdict and saved.feedback is not None
    assert saved.feedback.result == "complaint_supported"
    assert len(verdict.evidence) == 1
    evidence = verdict.evidence[0]
    assert evidence.t == FINDING_TIME
    assert "4.1254" in verdict.reason.en and "4.1254" in verdict.reason.th
    assert [request.stage for request in reviews] == [
        "visual",
        "observation",
        "complaint",
        "reason",
    ]
    reviewed_images = dict(reviews[0].images)
    assert (folder / evidence.frame).read_bytes() in reviewed_images.values()
    assert (folder / evidence.listing_photo).read_bytes() in reviewed_images.values()
    assert DESCRIPTION not in (folder / "verdict.json").read_text()
    assert ORDER.id not in "".join(payload for _, payload in responses.calls)
    assert ORDER.buyer_name not in "".join(payload for _, payload in responses.calls)
    assert [schema for schema, _ in responses.calls] == [
        "VisionObservation",
        *["MatchResponse"] * 5,
        "ComplaintSelection",
        "ReasonSelection",
    ]
    assert all(
        DESCRIPTION not in payload
        for schema, payload in responses.calls
        if schema != "ComplaintSelection"
    )
    assert (
        DESCRIPTION
        in [payload for schema, payload in responses.calls if schema == "ComplaintSelection"][0]
    )
    assert [event.step for event in progress if event.event == "finished"] == [
        step.name for step in verdict.steps
    ]


def test_submission_publishes_one_grounded_complaint_result(
    case: tuple[Path, JudgeInputs, FakeResponses],
) -> None:
    folder, inputs, responses = case
    result = run_submission(
        folder,
        inputs,
        review=lambda request: True,
        model="test-model",
        client=SimpleNamespace(responses=responses),
    )
    assert result.feedback is not None
    assert result.feedback.result == "complaint_supported"
    assert str(FINDING_TIME) in result.feedback.reason.en
    assert SubmissionResult.model_validate_json((folder / "submission.json").read_bytes()) == result


def test_pending_review_never_releases_images_or_writes_verdict(
    case: tuple[Path, JudgeInputs, FakeResponses],
) -> None:
    folder, inputs, responses = case
    with pytest.raises(ReviewRequired) as error:
        run(folder, inputs, model="test-model", client=SimpleNamespace(responses=responses))
    assert error.value.stage == "visual"
    assert not responses.calls
    assert not (folder / "verdict.json").exists()
    assert not (folder / "frames").exists()
    assert not (folder / "listing").exists()


@pytest.mark.parametrize(
    ("order_code", "label_status"), [(ORDER.id, "pass"), ("OTHER-19002", "flag")]
)
def test_local_opening_review_masks_the_label_before_visual_review(
    case: tuple[Path, JudgeInputs, FakeResponses], order_code: str, label_status: str
) -> None:
    folder, inputs, responses = case
    order = []
    region = RedactionRegion(x=8, y=8, width=16, height=16)

    def opening(request: OpeningReviewRequest) -> OpeningReviewSelection:
        order.append("opening")
        assert not responses.calls
        assert sorted(path.name for path in folder.iterdir()) == ["video.mp4"]
        pixels = cv2.imdecode(
            np.frombuffer(request.frames[0].jpeg, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        assert pixels[8:24, 8:24].max() > 128
        return OpeningReviewSelection(
            frame_number=1, seal_state="intact", order_code=order_code, label_region=region
        )

    def approve(request: ReviewRequest) -> bool:
        order.append(request.stage)
        if request.stage == "visual":
            assert not responses.calls
            ref, asset = request.images[0]
            assert ref.startswith("frames/0-")
            pixels = cv2.imdecode(np.frombuffer(asset, dtype=np.uint8), cv2.IMREAD_COLOR)
            assert pixels[8:24, 8:24].max() <= 2
        return True

    verdict = run(
        folder,
        inputs.model_copy(update={"opening": None}),
        opening_review=opening,
        review=approve,
        model="test-model",
        client=SimpleNamespace(responses=responses),
    )
    assert order[:2] == ["opening", "visual"]
    assert (
        verdict.checks["seal"].status == "pass" and verdict.checks["label"].status == label_status
    )
    assert order_code not in (folder / "verdict.json").read_text()
    assert all(order_code not in prompt for _, prompt in responses.calls)
    if label_status == "flag":
        assert [(flag.type, flag.t) for flag in verdict.flags] == [("label_mismatch", 0.1254)]
        assert verdict.display == "unsure"
    else:
        assert verdict.display == "clear"


def test_existing_trusted_opening_observation_skips_the_local_prompt(
    case: tuple[Path, JudgeInputs, FakeResponses],
) -> None:
    folder, inputs, responses = case

    def should_not_call(request: OpeningReviewRequest) -> None:
        pytest.fail("The API already supplied a trusted opening observation")

    verdict = run(
        folder,
        inputs,
        opening_review=should_not_call,
        review=lambda request: True,
        model="test-model",
        client=SimpleNamespace(responses=responses),
    )
    assert verdict.checks["seal"].status == "pass"


def test_observation_checkpoint_allows_retry_without_repeating_the_model_call(
    case: tuple[Path, JudgeInputs, FakeResponses],
) -> None:
    folder, inputs, responses = case
    client = SimpleNamespace(responses=responses)
    with pytest.raises(ReviewRequired) as error:
        run(
            folder,
            inputs,
            review=lambda request: request.stage == "visual",
            model="test-model",
            client=client,
        )
    assert error.value.stage == "observation"
    assert not (folder / "verdict.json").exists()
    verdict = run(folder, inputs, review=lambda request: True, model="test-model", client=client)
    assert verdict.display == "clear"
    assert [schema for schema, _ in responses.calls].count("VisionObservation") == 1


def test_unapproved_complaint_keeps_visual_leaning_and_forces_unsure(
    case: tuple[Path, JudgeInputs, FakeResponses],
) -> None:
    folder, inputs, responses = case
    verdict = run(
        folder,
        inputs,
        review=lambda request: request.stage in ("visual", "observation"),
        model="test-model",
        client=SimpleNamespace(responses=responses),
    )
    assert (verdict.verdict, verdict.leaning, verdict.confidence) == ("needs_human", "buyer", 0)
    assert "complaint" in verdict.reason.en and "4.1254" not in verdict.reason.en
    assert all(
        schema not in ("ComplaintSelection", "ReasonSelection") for schema, _ in responses.calls
    )


def test_retry_after_reason_review_and_publication_failure_reuses_model_results(
    case: tuple[Path, JudgeInputs, FakeResponses], monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, inputs, responses = case
    client = SimpleNamespace(responses=responses)

    def defer_reason(request: ReviewRequest) -> bool:
        if request.stage == "reason":
            raise ReviewRequired(request.stage)
        return True

    with pytest.raises(ReviewRequired, match="reason"):
        run(folder, inputs, review=defer_reason, model="test-model", client=client)

    def fail_publication(path: Path, content: bytes) -> None:
        raise OSError("Synthetic failure before publishing verdict")

    with monkeypatch.context() as patch:
        patch.setattr("judge.write_atomically", fail_publication)
        with pytest.raises(OSError, match="Synthetic failure"):
            run(folder, inputs, review=lambda request: True, model="test-model", client=client)
    assert not (folder / "verdict.json").exists()

    verdict = run(folder, inputs, review=lambda request: True, model="test-model", client=client)
    assert verdict.display == "clear"
    assert [schema for schema, _ in responses.calls] == [
        "VisionObservation",
        *["MatchResponse"] * 5,
        "ComplaintSelection",
        "ReasonSelection",
    ]


def test_grounded_complaint_links_prioritize_evidence_and_scope_the_reason(
    case: tuple[Path, JudgeInputs, FakeResponses],
) -> None:
    folder, inputs, responses = case
    responses.extra_finding = True
    verdict = run(
        folder,
        inputs,
        review=lambda request: True,
        model="test-model",
        client=SimpleNamespace(responses=responses),
    )

    assert verdict.verdict == "buyer_right"
    assert [item.t for item in verdict.evidence] == [FINDING_TIME, 3.1254]
    assert [item.t for item in verdict.checks["damage"].findings] == [3.1254, FINDING_TIME]
    assert "4.1254" in verdict.reason.en and "3.1254" not in verdict.reason.en
    reason_prompt = next(
        payload for schema, payload in responses.calls if schema == "ReasonSelection"
    )
    assert "Packaging crease" not in reason_prompt


def test_uploaded_video_without_inputs_does_not_fall_back_to_sample(
    case: tuple[Path, JudgeInputs, FakeResponses],
) -> None:
    folder, _, _ = case
    with pytest.raises(PipelineError, match="JudgeInputs"):
        run(folder)
    assert not (folder / "verdict.json").exists()


def test_reviewed_video_without_sharp_frames_publishes_evidence_request(
    case: tuple[Path, JudgeInputs, FakeResponses], monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, inputs, responses = case

    def no_sharp_frames(_path: Path) -> list[SampledFrame]:
        raise NoSharpFrames("No usable frames.")

    monkeypatch.setattr("judge.pipeline.sample_frames", no_sharp_frames)
    result = run(folder, inputs.model_copy(update={"description": ""}))

    saved = SubmissionResult.model_validate_json((folder / "submission.json").read_bytes())
    assert saved.verdict == result and saved.feedback is not None
    assert saved.feedback.result == "needs_more_evidence"
    assert "usable video" in saved.feedback.reason.en
    assert responses.calls == []


@pytest.mark.parametrize("usable_video", [True, False])
@pytest.mark.parametrize("complaint", ["empty", "approved", "pending"])
def test_video_entry_points_publish_equivalent_submission(
    case: tuple[Path, JudgeInputs, FakeResponses],
    monkeypatch: pytest.MonkeyPatch,
    usable_video: bool,
    complaint: str,
) -> None:
    folder, inputs, _ = case
    other = folder.parent / "submission" / folder.name
    other.mkdir(parents=True)
    (other / "video.mp4").write_bytes((folder / "video.mp4").read_bytes())
    monkeypatch.setattr("judge.pipeline.perf_counter", lambda: 0)
    if not usable_video:

        def no_frames(_path: Path) -> list[SampledFrame]:
            raise NoSharpFrames("No usable frames.")

        monkeypatch.setattr("judge.pipeline.sample_frames", no_frames)
    if complaint == "empty":
        inputs = inputs.model_copy(update={"description": ""})

    saved_results = []
    requests = []
    outputs = []
    progress_events = []
    for entrypoint, directory in ((run, folder), (run_submission, other)):
        responses = FakeResponses()
        reviews: list[ReviewRequest] = []
        progress: list[ProgressEvent] = []

        def review(request: ReviewRequest) -> bool:
            reviews.append(request)
            return request.stage != "complaint" or complaint == "approved"

        result = entrypoint(
            directory,
            inputs,
            review=review,
            progress=progress.append,
            model="test-model",
            client=SimpleNamespace(responses=responses),
        )
        saved = SubmissionResult.model_validate_json((directory / "submission.json").read_bytes())
        assert (saved.verdict if isinstance(result, Verdict) else saved) == result
        assert saved.video_status == ("analyzed" if usable_video else "no_usable_frames")
        assert saved.feedback is not None
        if not usable_video:
            assert [step.name for step in saved.verdict.steps] == ["intake", "sampling"]
            assert [schema for schema, _ in responses.calls] == (
                ["ComplaintSelection"] if complaint == "approved" else []
            )
        if complaint == "pending":
            assert saved.feedback.result == "needs_more_evidence"
            assert "privacy review" in saved.feedback.reason.en
        saved_results.append(saved)
        requests.append([(request.stage, request.fingerprint) for request in reviews])
        outputs.append(sorted(responses.calls))
        progress_events.append(progress)

    assert saved_results[0] == saved_results[1]
    assert requests[0] == requests[1]
    assert outputs[0] == outputs[1]
    assert progress_events[0] == progress_events[1]
    assert (
        Verdict.model_validate_json((folder / "verdict.json").read_bytes())
        == saved_results[0].verdict
    )


def test_run_requires_video_even_with_a_written_complaint(
    case: tuple[Path, JudgeInputs, FakeResponses],
) -> None:
    folder, inputs, _ = case

    with pytest.raises(PipelineError, match="regular video.mp4 file"):
        run(folder.parent / "no-video", inputs)


@pytest.mark.parametrize("shows_size", [False, True])
def test_written_variant_complaint_needs_a_directly_verified_attribute(
    case: tuple[Path, JudgeInputs, FakeResponses], shows_size: bool
) -> None:
    folder, inputs, _ = case

    class VariantMismatchResponses(FakeResponses):
        def parse(self, **kwargs: object) -> SimpleNamespace:
            response = super().parse(**kwargs)
            schema = kwargs["text_format"].__name__
            if schema == "MatchResponse":
                payload = kwargs["input"][1]["content"][0]["text"]
                if json.loads(payload.splitlines()[0])["check"] == "variant":
                    response.output_parsed = {
                        "status": "flag",
                        "confidence": 0.98,
                        "findings": [
                            {
                                "t": FINDING_TIME,
                                "note_en": "The tag reads S, but the order specifies M."
                                if shows_size
                                else "The shirt is red.",
                                "note_th": "ป้ายระบุขนาด S แต่สั่งขนาด M" if shows_size else "เสื้อสีแดง",
                            }
                        ],
                        "note_en": "Size differs from the order."
                        if shows_size
                        else "Color differs from the order.",
                    }
            if schema == "ComplaintSelection":
                response.output_parsed = {
                    "confidence": 0.98,
                    "allegations": [
                        {
                            "kind": "size",
                            "finding_ids": [0] if shows_size else [],
                            "supporting_finding_ids": [0] if shows_size else [],
                        }
                    ],
                }
            return response

    result = run_submission(
        folder,
        inputs.model_copy(update={"claim_type": "wrong_item", "description": "Wrong size"}),
        review=lambda _: True,
        model="test-model",
        client=SimpleNamespace(responses=VariantMismatchResponses()),
    )

    assert result.verdict.verdict == "buyer_right"
    assert result.feedback is not None
    assert result.feedback.result == ("needs_human_check" if shows_size else "needs_more_evidence")
    if shows_size:
        assert "confirm" in result.feedback.reason.en
    assert result.verdict.evidence[0].t == FINDING_TIME


def test_a_contradicting_frame_cannot_support_a_written_complaint(
    case: tuple[Path, JudgeInputs, FakeResponses],
) -> None:
    folder, inputs, _ = case

    class ContradictingResponses(FakeResponses):
        def parse(self, **kwargs: object) -> SimpleNamespace:
            response = super().parse(**kwargs)
            schema = kwargs["text_format"].__name__
            if schema == "MatchResponse":
                text = kwargs["input"][1]["content"][0]["text"]
                if json.loads(text.splitlines()[0])["check"] == "damage":
                    response.output_parsed["findings"] = [
                        {"t": 3.1254, "note_en": "The screen is intact.", "note_th": "หน้าจอไม่แตก"},
                        {
                            "t": FINDING_TIME,
                            "note_en": "The back is dented.",
                            "note_th": "ด้านหลังบุบ",
                        },
                    ]
            if schema == "ComplaintSelection":
                response.output_parsed["allegations"] = [
                    {
                        "kind": "damage",
                        "finding_ids": [0],
                        "supporting_finding_ids": [],
                    }
                ]
            return response

    result = run_submission(
        folder,
        inputs.model_copy(update={"description": "My screen is cracked."}),
        review=lambda _: True,
        model="test-model",
        client=SimpleNamespace(responses=ContradictingResponses()),
    )

    assert result.verdict.verdict == "buyer_right"
    assert result.verdict.evidence[0].t == 3.1254
    assert result.feedback is not None
    assert result.feedback.result == "needs_more_evidence"
