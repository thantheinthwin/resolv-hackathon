"""Compose the local and privacy-reviewed stages for an uploaded case."""

from collections.abc import Callable, Sequence
from pathlib import Path
from time import monotonic

import cv2
import numpy as np
from pydantic import BaseModel

from api.app.contracts import Check, ClaimType, Listing, Order, Step, Verdict
from judge.complaint import assess_complaint
from judge.evidence import FrameAsset, ListingAsset, build_evidence_pack
from judge.integrity import assess_integrity
from judge.matching import CHECK_NAMES, ReviewedListingPhoto, analyze_step5
from judge.privacy import sanitize_frames
from judge.reasons import generate_reason
from judge.sampling import NoSharpFrames, sample_frames
from judge.verdict import CLAIM_CHECK, decide_verdict
from judge.vision import _select_frames


class Inputs(BaseModel):
    order: Order
    listing: Listing
    claim_type: ClaimType
    description: str


# The operator must approve the exact image and text payload for each stage.
Review = Callable[[str, dict[str, bytes]], bool]


def png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Cannot encode evidence.")
    return encoded.tobytes()


def analyze(
    directory: Path,
    inputs: Inputs,
    photos: Sequence[bytes],
    review: Review | None,
) -> Verdict:
    started = monotonic()
    try:
        frames = sanitize_frames(sample_frames(directory / "video.mp4"))
    except NoSharpFrames:
        frames = []
    integrity = assess_integrity(frames, expected_order_id=inputs.order.id)
    steps = [
        Step(
            name="sampling",
            kind="code",
            seconds=monotonic() - started,
            output=f"{len(frames)} usable sanitized frames; local integrity checks complete.",
        )
    ]
    checks = {name: Check(status="unclear", confidence=0, findings=[]) for name in CHECK_NAMES}
    confidence = 0.0
    evidence = []
    text_approved = False
    if frames and review is not None and photos:
        selected = _select_frames(frames)
        frame_assets = [
            FrameAsset(ref=f"frames/{i}.png", frame=frame) for i, frame in enumerate(selected)
        ]
        images = {a.ref: png(a.frame.image) for a in frame_assets}
        listing_images = []
        for i, data in enumerate(photos):
            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("Could not decode the order's listing photo.")
            ref = f"listing/{i}.png"
            images[ref] = png(image)
            listing_images.append((ref, image))
        payload = {
            **images,
            "listing.json": inputs.listing.model_dump_json().encode(),
            "variant.json": inputs.order.variant.model_dump_json().encode(),
            "quantity.txt": str(inputs.order.quantity).encode(),
            "times.txt": str([f.timestamp_seconds for f in selected]).encode(),
        }
        if review("visual", payload):
            started = monotonic()
            assets = [
                ListingAsset(
                    ref=ref, photo=ReviewedListingPhoto(image=image, privacy_reviewed=True)
                )
                for ref, image in listing_images
            ]
            result = analyze_step5(
                selected,
                listing=inputs.listing,
                order=inputs.order,
                listing_photos=[a.photo for a in assets],
                privacy_approved=True,
                cache_dir=directory / "cache",
            )
            checks = result.checks
            steps.append(
                Step(
                    name="comparison",
                    kind="model",
                    seconds=monotonic() - started,
                    output="Compared the reviewed frames with the order and listing.",
                )
            )
            text_approved = review(
                "text",
                {
                    "complaint.txt": inputs.description.encode(),
                    "claim.txt": inputs.claim_type.encode(),
                    **{
                        f"{name}.json": check.model_dump_json().encode()
                        for name, check in checks.items()
                    },
                },
            )
            if text_approved or not inputs.description.strip():
                confidence = assess_complaint(
                    inputs.claim_type, inputs.description, checks, privacy_approved=text_approved
                ).claim_confidence
            evidence = build_evidence_pack(checks, frame_assets, assets, privacy_approved=True)
            for ref in {r for pair in evidence for r in (pair.frame, pair.listing_photo)}:
                path = directory / ref
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(images[ref])
    verdict = decide_verdict(
        case_id=directory.name,
        claim_type=inputs.claim_type,
        claim_confidence=confidence,
        comparisons=checks,
        integrity=integrity,
    )
    deciding = CLAIM_CHECK.get(
        inputs.claim_type, "variant" if checks["listing"].status == "pass" else "listing"
    )
    verdict.reason = generate_reason(verdict, deciding, privacy_approved=text_approved)
    verdict.evidence = evidence
    verdict.steps = steps
    return verdict
