"""Exercise the submission entry point across all buyer evidence combinations."""

from base64 import b64decode
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from api.app.contracts import ProgressEvent, Verdict
from api.app.sample import LISTING, ORDER
from judge import ReviewRequest, ReviewRequired
from judge.intake import IntakeError
from judge.matching import ReviewedListingPhoto
from judge.pipeline import PipelineError
from judge.privacy import RedactionRegion
from judge.submission import (
    MAX_BUYER_PHOTOS,
    BuyerPhoto,
    SubmissionInputs,
    SubmissionResult,
    run_submission,
)

DESCRIPTION = "พบรอยแตกบนเครื่อง private-complaint"


class Responses:
    def __init__(self, photo_result: object = None) -> None:
        self.calls: list[tuple[str, object]] = []
        self.photo_result = photo_result

    def parse(self, **kwargs: object) -> SimpleNamespace:
        schema = kwargs["text_format"].__name__
        self.calls.append((schema, kwargs["input"]))
        assert kwargs["store"] is False
        if schema == "PhotoMatch":
            result = self.photo_result
            if result is None:
                result = {"findings": [_finding(0), _finding(1)]}
        else:
            assert schema == "ComplaintSelection"
            result = {"confidence": 0.98, "allegations": [{"kind": "damage", "finding_ids": [0]}]}
        return SimpleNamespace(output_parsed=result)


def _finding(index: int) -> dict[str, object]:
    return {
        "photo_index": index,
        "check": "damage",
        "status": "flag",
        "note_en": "A crack is visible.",
        "note_th": "เห็นรอยแตก",
    }


def _inputs(*, written: bool = False, media: bool = False) -> SubmissionInputs:
    pixels = np.full((64, 64, 3), 250, dtype=np.uint8)
    return SubmissionInputs(
        claim_type="damaged",
        description=DESCRIPTION if written else "   ",
        order=ORDER,
        listing=LISTING,
        listing_photos=(ReviewedListingPhoto(image=pixels, privacy_reviewed=True),)
        if media
        else (),
    )


def _photos() -> tuple[BuyerPhoto, ...]:
    return (
        BuyerPhoto(
            image=np.full((64, 64, 3), 250, dtype=np.uint8),
            redactions=(RedactionRegion(x=0, y=0, width=32, height=32),),
        ),
    )


def _allow(request: ReviewRequest) -> bool:
    return True


@pytest.mark.parametrize(
    ("written", "photo", "video"),
    [
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (True, True, False),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ],
)
def test_accepts_each_evidence_combination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    written: bool,
    photo: bool,
    video: bool,
) -> None:
    sample = Verdict.model_validate_json(
        Path("judge/fixtures/verdict.sample.json").read_bytes()
    ).model_copy(update={"case_id": tmp_path.name})
    video_descriptions: list[str] = []

    def run_video(directory: Path, inputs: SubmissionInputs, **kwargs: object) -> Verdict:
        video_descriptions.append(inputs.description)
        return sample

    monkeypatch.setattr("judge.submission.run_uploaded_case", run_video)
    if video:
        (tmp_path / "video.mp4").write_bytes(b"video placeholder")
    responses = Responses()

    result = run_submission(
        tmp_path,
        _inputs(written=written, media=video or photo),
        buyer_photos=_photos() if photo else (),
        review=_allow,
        model="test-model",
        client=SimpleNamespace(responses=responses),
    )

    assert result.video_status == ("analyzed" if video else "absent")
    assert bool(result.photo_findings) is photo
    assert len(result.buyer_photos) == int(photo)
    assert video_descriptions == ([DESCRIPTION if written else "   "] if video else [])
    assert [kind for kind, _ in responses.calls] == (
        ["PhotoMatch"] * photo + ["ComplaintSelection"] * (written and not video)
    )
    if video:
        assert result.verdict == sample
    else:
        assert result.verdict.verdict == "needs_human"
        assert result.verdict.evidence == []
        assert result.verdict.flags == []
        assert not any(check.findings for check in result.verdict.checks.values())
        assert result.verdict.reason.en and result.verdict.reason.th
        assert bool(result.complaint) is written
        if result.complaint:
            assert result.complaint.allegations[0].evidence == []
    assert (
        SubmissionResult.model_validate_json((tmp_path / "submission.json").read_bytes()) == result
    )
    assert DESCRIPTION not in (tmp_path / "submission.json").read_text()


def test_last_allowed_photo_finding_round_trips(tmp_path: Path) -> None:
    last_index = MAX_BUYER_PHOTOS - 1
    responses = Responses({"findings": [_finding(last_index)]})
    result = run_submission(
        tmp_path,
        _inputs(media=True),
        buyer_photos=_photos() * MAX_BUYER_PHOTOS,
        review=_allow,
        model="test-model",
        client=SimpleNamespace(responses=responses),
    )

    assert len(result.buyer_photos) == MAX_BUYER_PHOTOS
    [finding] = result.photo_findings
    assert finding.photo == result.buyer_photos[last_index]
    assert finding.photo.startswith(f"buyer-photos/{last_index}-")
    assert (tmp_path / finding.photo).is_file()
    assert (
        SubmissionResult.model_validate_json((tmp_path / "submission.json").read_bytes()) == result
    )


def test_extra_photo_is_rejected_before_review_or_model_call(tmp_path: Path) -> None:
    responses = Responses()
    with pytest.raises(PipelineError, match=f"at most {MAX_BUYER_PHOTOS} buyer photos"):
        run_submission(
            tmp_path,
            _inputs(written=True, media=True),
            buyer_photos=_photos() * (MAX_BUYER_PHOTOS + 1),
            review=lambda _: pytest.fail("Over-limit submissions must not request approval."),
            model="test-model",
            client=SimpleNamespace(responses=responses),
        )

    assert responses.calls == []
    assert not (tmp_path / "submission.json").exists()


def test_empty_submission_is_invalid(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="text, a photo, or a video"):
        run_submission(tmp_path, _inputs())
    assert not (tmp_path / "submission.json").exists()


def _write_flat_video(case_dir: Path, frames: int) -> None:
    writer = cv2.VideoWriter(
        str(case_dir / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 2, (64, 64)
    )
    assert writer.isOpened()
    for _ in range(frames):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()


def test_rejects_an_invalid_video_before_requesting_photo_review(tmp_path: Path) -> None:
    _write_flat_video(tmp_path, frames=6)
    requests: list[ReviewRequest] = []
    responses = Responses()

    def approve(request: ReviewRequest) -> bool:
        requests.append(request)
        return True

    with pytest.raises(IntakeError, match="duration"):
        run_submission(
            tmp_path,
            _inputs(media=True),
            buyer_photos=_photos(),
            review=approve,
            model="test-model",
            client=SimpleNamespace(responses=responses),
        )
    assert requests == []
    assert responses.calls == []
    assert not (tmp_path / "submission.json").exists()


def test_no_sharp_frames_keeps_photos_and_text(tmp_path: Path) -> None:
    _write_flat_video(tmp_path, frames=12)
    events: list[ProgressEvent] = []
    result = run_submission(
        tmp_path,
        _inputs(written=True, media=True),
        buyer_photos=_photos(),
        review=_allow,
        progress=events.append,
        model="test-model",
        client=SimpleNamespace(responses=Responses()),
    )
    assert result.video_status == "no_usable_frames"
    assert result.verdict.verdict == "needs_human"
    assert result.complaint is not None and result.complaint.allegations
    assert len(result.photo_findings) == 1
    assert "usable frames" in result.verdict.reason.en
    assert result.feedback is not None
    assert result.feedback.result == "needs_more_evidence"
    assert "usable video" in result.feedback.reason.en
    assert (events[-1].step, events[-1].event) == ("sampling", "finished")
    assert [step.name for step in result.verdict.steps] == ["intake", "sampling"]


def test_photo_model_uses_exact_reviewed_redacted_jpegs_and_never_the_complaint(
    tmp_path: Path,
) -> None:
    requests: list[ReviewRequest] = []
    responses = Responses()

    def approve_visual(request: ReviewRequest) -> bool:
        requests.append(request)
        return request.stage == "visual"

    result = run_submission(
        tmp_path,
        _inputs(written=True, media=True),
        buyer_photos=_photos(),
        review=approve_visual,
        model="test-model",
        client=SimpleNamespace(responses=responses),
    )
    assert [request.stage for request in requests] == ["visual", "complaint"]
    assert [name for name, _ in responses.calls] == ["PhotoMatch"]
    assert result.complaint is None
    assert len(result.photo_findings) == 1
    record = result.photo_findings[0]
    assert "t" not in record.model_dump()
    assert record.photo.startswith("buyer-photos/")
    _, messages = responses.calls[0]
    assert all(
        private not in str(messages) for private in (DESCRIPTION, ORDER.id, ORDER.buyer_name)
    )
    outbound = [
        b64decode(entry["image_url"].split(",", 1)[1])
        for entry in messages[1]["content"]
        if entry["type"] == "input_image"
    ]
    assert outbound == [jpeg for _, jpeg in requests[0].images]
    assert (tmp_path / record.photo).read_bytes() == outbound[0]
    decoded = cv2.imdecode(np.frombuffer(outbound[0], dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded[16, 16].max() == 0
    assert decoded[48, 48].min() > 200


def test_photo_refusal_prevents_every_model_call(tmp_path: Path) -> None:
    responses = Responses()
    with pytest.raises(ReviewRequired, match="visual"):
        run_submission(
            tmp_path,
            _inputs(written=True, media=True),
            buyer_photos=_photos(),
            model="test-model",
            client=SimpleNamespace(responses=responses),
        )
    assert responses.calls == []
    assert not (tmp_path / "submission.json").exists()


def test_malformed_photo_response_retries_then_returns_no_findings(tmp_path: Path) -> None:
    responses = Responses({"findings": [{**_finding(0), "t": 0.0}]})
    result = run_submission(
        tmp_path,
        _inputs(media=True),
        buyer_photos=_photos(),
        review=_allow,
        model="test-model",
        client=SimpleNamespace(responses=responses),
    )
    assert len(responses.calls) == 2
    assert result.photo_findings == []
    assert result.verdict.verdict == "needs_human"
    assert len(result.buyer_photos) == 1
    assert (tmp_path / result.buyer_photos[0]).is_file()


def test_text_approval_matches_the_transmitted_payload(tmp_path: Path) -> None:
    requests: list[ReviewRequest] = []
    responses = Responses()

    def approve(request: ReviewRequest) -> bool:
        requests.append(request)
        return True

    run_submission(
        tmp_path,
        _inputs(written=True),
        review=approve,
        model="test-model",
        client=SimpleNamespace(responses=responses),
    )
    assert len(requests) == 1 and requests[0].stage == "complaint"
    name, messages = responses.calls[0]
    assert name == "ComplaintSelection"
    assert requests[0].text == messages[1]["content"]


@pytest.mark.parametrize("video_offset", [0, 2])
def test_mixed_submission_cites_the_presentation_time_of_a_variable_rate_frame(
    tmp_path: Path, video_offset: int
) -> None:
    manifest: list[str] = []
    for index, duration in enumerate((1.8, 1.5, 2.6, 2.2, 1.0)):
        image = np.random.default_rng(index).integers(0, 255, (96, 96, 3), dtype=np.uint8)
        name = f"image-{index}.png"
        assert cv2.imwrite(str(tmp_path / name), image)
        manifest.extend([f"file {name}", f"duration {duration}"])
    manifest.append(f"file {name}")
    source = tmp_path / "input.txt"
    source.write_text("\n".join(manifest) + "\n")
    clip = tmp_path / "video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-itsoffset",
            str(video_offset),
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=400:duration=12",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:a",
            "aac",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
        timeout=15,
    )
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "json",
            str(clip),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    t = float(json.loads(probe.stdout)["frames"][2]["best_effort_timestamp_time"])
    assert t == 3.32 + video_offset

    class VideoResponses(Responses):
        def parse(self, **kwargs: object) -> SimpleNamespace:
            schema = kwargs["text_format"].__name__
            if schema == "VisionObservation":
                return SimpleNamespace(
                    output_parsed={
                        "status": "observed",
                        "findings": [
                            {"t": t, "category": "damage", "value": "crack", "confidence": 0.96}
                        ],
                        "note_en": "Compared the evidence.",
                    }
                )
            if schema == "MatchResponse":
                text = kwargs["input"][1]["content"][0]["text"]
                relevant = json.loads(text.splitlines()[0])["check"] == "damage"
                return SimpleNamespace(
                    output_parsed={
                        "status": "flag" if relevant else "unclear",
                        "confidence": 0.96 if relevant else 0,
                        "findings": [
                            {"t": t, "note_en": "A crack is visible.", "note_th": "เห็นรอยแตก"}
                        ]
                        if relevant
                        else [],
                        "note_en": "Compared the evidence.",
                    }
                )
            return super().parse(**kwargs)

    requests: list[ReviewRequest] = []

    def approve(request: ReviewRequest) -> bool:
        requests.append(request)
        return request.stage != "reason"

    result = run_submission(
        tmp_path,
        _inputs(written=True, media=True),
        buyer_photos=_photos(),
        review=approve,
        model="test-model",
        client=SimpleNamespace(responses=VideoResponses()),
    )
    assert result.video_status == "analyzed"
    frame_review = next(r for r in requests if "frame_times" in r.text)
    assert t in json.loads(frame_review.text)["frame_times"]
    [video_evidence] = result.verdict.evidence
    assert video_evidence.t == t
    assert (tmp_path / video_evidence.frame).read_bytes() == dict(frame_review.images)[
        video_evidence.frame
    ]
    [photo_evidence] = result.photo_findings
    assert (tmp_path / photo_evidence.photo).is_file()
