"""Run an uploaded case through the judge stages using trusted API inputs."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.app.contracts import (
    ClaimType,
    Listing,
    Order,
    ProgressEvent,
    Reason,
    Seconds,
    Step,
    Verdict,
)
from judge.complaint import ComplaintAssessment, assess_complaint
from judge.config import get_secret
from judge.evidence import FrameAsset, ListingAsset, build_evidence_pack
from judge.feedback import FeedbackState
from judge.intake import DARK_FRAME_THRESHOLD, inspect_video
from judge.integrity import OPENING_WINDOW_SECONDS, OpeningObservation, assess_integrity
from judge.matching import (
    ReviewedListingPhoto,
    _cache_folder,
    _listing_context,
    _read_cache,
    _validate_photos,
    _write_cache,
    compare_listing,
)
from judge.opening_review import OpeningReviewer, collect_opening_review
from judge.privacy import RedactionRegion, SanitizedFrame, mask_frame_regions, sanitize_frames
from judge.reasons import generate_reason
from judge.sampling import NoSharpFrames, sample_frames
from judge.verdict import EvidenceQuality, decide_verdict, deciding_check_name
from judge.vision import (
    SYSTEM_INSTRUCTIONS,
    VisionClient,
    VisionObservation,
    _encode_jpeg,
    _select_frames,
    observe_product,
)

ReviewStage = Literal["visual", "observation", "complaint", "reason"]


class PipelineError(ValueError):
    """An uploaded case cannot be processed with the supplied inputs."""


class ReviewRequired(PipelineError):
    """The job can be requeued after a human approves this request."""

    def __init__(self, stage: ReviewStage) -> None:
        self.stage = stage
        super().__init__(f"Human privacy review required for {stage}.")


class SubmissionInputs(BaseModel):
    """Case context assembled by the trusted API, never from upload form fields."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    claim_type: ClaimType
    description: str = Field(default="", repr=False)
    order: Order = Field(repr=False)
    listing: Listing = Field(repr=False)
    listing_photos: tuple[ReviewedListingPhoto, ...] = Field(default=(), max_length=3, repr=False)
    opening: OpeningObservation | None = Field(default=None, repr=False)
    redactions_by_timestamp: dict[Seconds, tuple[RedactionRegion, ...]] = Field(
        default_factory=dict
    )
    quality: EvidenceQuality = Field(default_factory=EvidenceQuality)


class JudgeInputs(SubmissionInputs):
    """Required inputs for the video worker entry point."""

    listing_photos: tuple[ReviewedListingPhoto, ...] = Field(min_length=1, max_length=3, repr=False)


@dataclass(frozen=True)
class ReviewRequest:
    """Private review data for a single outbound scope."""

    stage: ReviewStage
    text: str = field(repr=False)
    images: tuple[tuple[str, bytes], ...] = field(default=(), repr=False)

    @property
    def fingerprint(self) -> str:
        images = [(name, sha256(data).hexdigest()) for name, data in self.images]
        return sha256(_json((self.stage, self.text, images)).encode("utf-8")).hexdigest()


Review = Callable[[ReviewRequest], bool]
Progress = Callable[[ProgressEvent], None]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _approved(review: Review | None, request: ReviewRequest) -> bool:
    return review is not None and review(request) is True


def _require_review(review: Review | None, request: ReviewRequest) -> None:
    if not _approved(review, request):
        raise ReviewRequired(request.stage)


def write_atomically(path: Path, content: bytes) -> None:
    """Replace a private artifact only after all bytes are written."""
    with NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary_path = Path(output.name)
        try:
            output.write(content)
            output.close()
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)


def _observation(
    frames: list[SanitizedFrame],
    *,
    model: str,
    client: VisionClient | None,
    cache: Path,
    visual: ReviewRequest,
) -> VisionObservation:
    key = sha256(
        _json((model, SYSTEM_INSTRUCTIONS, visual.fingerprint)).encode("utf-8")
    ).hexdigest()
    sent = {frame.timestamp_seconds for frame in frames}
    result = _read_cache(cache, key, VisionObservation)
    if (
        result is not None
        and result.status == "observed"
        and result.findings
        and all(item.t in sent for item in result.findings)
    ):
        return result

    result = observe_product(frames, privacy_approved=True, model=model, client=client)
    if result.status == "observed" and result.findings:
        _write_cache(cache, key, result)
        return result
    return VisionObservation(status="unclear", findings=[], note_en="Visual details unavailable.")


def _review_assets(
    sent_frames: list[SanitizedFrame],
    photos: tuple[ReviewedListingPhoto, ...],
) -> tuple[list[FrameAsset], list[ListingAsset], dict[str, bytes]]:
    files: dict[str, bytes] = {}
    frame_assets: list[FrameAsset] = []
    listing_assets: list[ListingAsset] = []
    for index, frame in enumerate(sent_frames):
        jpeg = _encode_jpeg(frame.image)
        ref = f"frames/{index}-{sha256(jpeg).hexdigest()}.jpg"
        files[ref] = jpeg
        frame_assets.append(FrameAsset(ref=ref, frame=frame))
    for index, photo in enumerate(photos):
        jpeg = _encode_jpeg(photo.image)
        ref = f"listing/{index}-{sha256(jpeg).hexdigest()}.jpg"
        files[ref] = jpeg
        listing_assets.append(ListingAsset(ref=ref, photo=photo))
    return frame_assets, listing_assets, files


def run_uploaded_case(
    directory: Path,
    inputs: SubmissionInputs,
    *,
    review: Review | None,
    opening_review: OpeningReviewer | None,
    progress: Progress | None,
    model: str | None,
    client: VisionClient | None,
    steps: list[Step] | None = None,
    feedback_state: FeedbackState | None = None,
) -> Verdict:
    """Assemble a verdict and stage its evidence before publishing the JSON."""
    video = directory / "video.mp4"
    if video.is_symlink() or not video.is_file():
        raise PipelineError("The case must contain a regular video.mp4 file.")
    inputs = inputs.model_copy(deep=True)
    if inputs.order.listing_id != inputs.listing.id:
        raise PipelineError("The order does not reference the supplied listing.")
    _validate_photos(inputs.listing_photos)
    steps = [] if steps is None else steps

    @contextmanager
    def step(name: str, kind: Literal["code", "model"], output: str) -> Iterator[None]:
        start = perf_counter()
        if progress is not None:
            progress(ProgressEvent(event="started", step=name))
        yield
        steps.append(Step(name=name, kind=kind, seconds=perf_counter() - start, output=output))
        if progress is not None:
            progress(ProgressEvent(event="finished", step=name))

    with step("intake", "code", "Validated the local video"):
        intake = inspect_video(video)
    sampling_error = None
    with step("sampling", "code", "Checked the video for usable frames"):
        try:
            sampled = sample_frames(video)
        except NoSharpFrames as exc:
            sampling_error = exc
    if sampling_error is not None:
        raise sampling_error
    opening = inputs.opening
    label_region = None
    if opening is None and opening_review is not None:
        with step("opening_review", "code", "Checked the opening with the local reviewer"):
            reviewed = collect_opening_review(sampled, opening_review)
            if reviewed is not None:
                opening, label_region = reviewed
    with step("privacy", "code", "Redacted frames for human review"):
        times = {frame.timestamp_seconds for frame in sampled}
        if inputs.redactions_by_timestamp.keys() - times:
            raise PipelineError("Redaction timestamps must match selected frames exactly.")
        frames = sanitize_frames(sampled, redactions_by_timestamp=inputs.redactions_by_timestamp)
        sent = _select_frames(frames)
        if opening is not None and label_region is not None:
            sent = [
                mask_frame_regions(frame, (label_region,))
                if frame.timestamp_seconds == opening.timestamp_seconds
                else frame
                for frame in sent
            ]
        frame_assets, listing_assets, files = _review_assets(sent, inputs.listing_photos)
        context = _listing_context(inputs.listing, inputs.order)
        visual = ReviewRequest(
            stage="visual",
            text=_json(
                {"comparison_context": context, "frame_times": [f.timestamp_seconds for f in sent]}
            ),
            images=tuple(files.items()),
        )
        _require_review(review, visual)
    with step("integrity", "code", "Checked continuity and the recorded opening observation"):
        if opening is not None and (
            opening.timestamp_seconds > OPENING_WINDOW_SECONDS
            or opening.timestamp_seconds not in times
        ):
            raise PipelineError(
                "Opening observation must cite an exact sampled time in the first 10 seconds."
            )
        integrity = assess_integrity(frames, expected_order_id=inputs.order.id, observation=opening)
        if feedback_state is not None:
            feedback_state.opening_review_pending = opening is None

    selected_model = model or get_secret("OPENAI_MODEL")
    if not selected_model:
        raise PipelineError("OPENAI_MODEL must be configured for the judge.")
    cache = _cache_folder(directory / ".judge-cache")
    with step("observation", "model", "Described product evidence"):
        observation = _observation(
            sent, model=selected_model, client=client, cache=cache, visual=visual
        )
    with step(
        "comparison", "model", "Compared the product, variant, count, damage and counterfeit signs"
    ):
        if observation.findings:
            _require_review(
                review, ReviewRequest(stage="observation", text=observation.model_dump_json())
            )
        comparisons = compare_listing(
            sent,
            observation,
            listing=inputs.listing,
            order=inputs.order,
            listing_photos=inputs.listing_photos,
            privacy_approved=True,
            model=selected_model,
            client=client,
            cache_dir=cache,
            failed_checks=feedback_state.failed_comparisons if feedback_state is not None else None,
        )

    description = inputs.description
    complaint_approved = not description.strip() or _approved(
        review,
        ReviewRequest(
            stage="complaint",
            text=_json(
                {
                    "claim_type": inputs.claim_type,
                    "description": description,
                    "findings": {
                        name: [finding.model_dump(mode="json") for finding in check.findings]
                        for name, check in comparisons.items()
                    },
                }
            ),
        ),
    )
    if feedback_state is not None:
        feedback_state.complaint_review_pending = not complaint_approved
    with step(
        "complaint",
        "model" if description.strip() and complaint_approved else "code",
        "Assessed the selected claim"
        if complaint_approved
        else "Written complaint awaits privacy review",
    ):
        complaint = (
            assess_complaint(
                inputs.claim_type,
                description,
                comparisons,
                privacy_approved=True,
                model=selected_model,
                client=client,
                cache_dir=cache,
            )
            if complaint_approved
            else ComplaintAssessment(claim_confidence=0, allegations=[])
        )
    with step("verdict", "code", "Applied deterministic verdict rules"):
        quality = inputs.quality.model_copy(
            update={"dark": inputs.quality.dark or intake.dark_frame_ratio > DARK_FRAME_THRESHOLD}
        )
        verdict = decide_verdict(
            case_id=directory.name,
            claim_type=inputs.claim_type,
            claim_confidence=complaint.claim_confidence,
            comparisons=comparisons,
            integrity=integrity,
            quality=quality,
        )
        if not complaint_approved:
            verdict.reason = Reason(
                en=f"{verdict.reason.en} The written complaint awaits privacy review.",
                th=f"{verdict.reason.th} ข้อร้องเรียนที่เขียนไว้ยังรอการตรวจสอบความเป็นส่วนตัว",
            )

    linked = {
        (reference.check, reference.t)
        for allegation in complaint.allegations
        for reference in allegation.evidence
    }
    with step("evidence", "code", "Paired exact frame times with reviewed listing photos"):
        evidence = build_evidence_pack(
            verdict.checks, frame_assets, listing_assets, privacy_approved=True
        )
        evidence.sort(key=lambda pair: (pair.check, pair.t) not in linked)

    deciding_check = deciding_check_name(inputs.claim_type, verdict.checks)
    check = verdict.checks[deciding_check]
    scoped_findings = [
        finding for finding in check.findings if (deciding_check, finding.t) in linked
    ]
    reason_context = verdict
    if scoped_findings:
        check = check.model_copy(update={"findings": scoped_findings})
        reason_context = verdict.model_copy(
            update={"checks": {**verdict.checks, deciding_check: check}}
        )
    reason_approved = bool(check.findings) and _approved(
        review,
        ReviewRequest(
            stage="reason",
            text=_json(
                {
                    "check": deciding_check,
                    "status": check.status,
                    "findings": [finding.model_dump(mode="json") for finding in check.findings],
                }
            ),
        ),
    )
    with step(
        "reason",
        "model" if reason_approved else "code",
        "Prepared the English and Thai explanations",
    ):
        reason = generate_reason(
            reason_context,
            deciding_check,
            privacy_approved=reason_approved,
            model=selected_model,
            client=client,
            cache_dir=cache,
        )

    result = Verdict.model_validate(
        {
            **verdict.model_dump(),
            "reason": reason,
            "steps": steps,
            "evidence": evidence,
        }
    )
    refs = {ref for pair in evidence for ref in (pair.frame, pair.listing_photo)}
    for ref in sorted(refs):
        asset = directory / ref
        _cache_folder(asset.parent)
        write_atomically(asset, files[ref])
    return result
