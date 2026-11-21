"""Build shared evidence pairs from privacy-approved, grounded comparison findings."""

from collections.abc import Sequence

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from api.app.contracts import Check, Evidence
from judge.matching import CHECK_NAMES, ReviewedListingPhoto, _pixels_valid
from judge.privacy import SanitizedFrame

MAX_LISTING_PHOTOS = 3
ASSET_NAME = r"[A-Za-z0-9_-]{1,100}\.(jpg|jpeg|png|webp)"


class EvidenceError(ValueError):
    """Evidence pairing cannot proceed with the supplied assets."""


class FrameAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    ref: str = Field(pattern=rf"^frames/{ASSET_NAME}$")
    frame: SanitizedFrame


class ListingAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    ref: str = Field(pattern=rf"^listing/{ASSET_NAME}$")
    photo: ReviewedListingPhoto


def _histogram(image: np.ndarray) -> np.ndarray:
    """A bounded-size colour and brightness descriptor for visual pairing."""
    thumbnail = cv2.resize(image, (64, 64), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(thumbnail, cv2.COLOR_BGR2HSV)
    return cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 8], [0, 180, 0, 256, 0, 256])


def build_evidence_pack(
    comparisons: dict[str, Check],
    sent_frames: Sequence[FrameAsset],
    listing_photos: Sequence[ListingAsset],
    *,
    privacy_approved: bool = False,
) -> list[Evidence]:
    """Pair comparison flags using exactly the frames sent to the matcher.

    The caller supplies the relative references for the same reviewed pixels it
    will serve to the shop. This function neither writes nor opens assets.
    Integrity findings stay on the timeline through the integrity checks.
    """
    if privacy_approved is not True:
        raise EvidenceError("Explicit privacy approval is required for the evidence pack.")
    if not 1 <= len(listing_photos) <= MAX_LISTING_PHOTOS:
        raise EvidenceError("Provide one to three listing photos.")
    if any(asset.photo.privacy_reviewed is not True for asset in listing_photos):
        raise EvidenceError("Every listing photo requires explicit privacy approval.")

    frames_by_time = {asset.frame.timestamp_seconds: asset for asset in sent_frames}
    if (
        len(frames_by_time) != len(sent_frames)
        or len({asset.ref for asset in sent_frames}) != len(sent_frames)
        or len({asset.ref for asset in listing_photos}) != len(listing_photos)
    ):
        raise EvidenceError("Evidence frame timestamps and asset references must be unique.")
    if any(not _pixels_valid(asset.frame.image) for asset in sent_frames) or any(
        not _pixels_valid(asset.photo.image) for asset in listing_photos
    ):
        raise EvidenceError("Evidence assets require valid uint8 BGR pixels.")

    pairs = {
        (finding.t, name)
        for name in CHECK_NAMES
        if (check := comparisons.get(name)) is not None and check.status == "flag"
        for finding in check.findings
        if finding.t in frames_by_time
    }
    if not pairs:
        return []

    photo_histograms = [(asset.ref, _histogram(asset.photo.image)) for asset in listing_photos]
    best_photos: dict[float, str] = {}
    for t, _ in sorted(pairs):
        if t not in best_photos:
            frame_histogram = _histogram(frames_by_time[t].frame.image)
            best_photos[t] = min(
                photo_histograms,
                key=lambda photo: cv2.compareHist(
                    frame_histogram, photo[1], cv2.HISTCMP_BHATTACHARYYA
                ),
            )[0]
    return [
        Evidence(
            t=t,
            check=name,
            result="flag",
            frame=frames_by_time[t].ref,
            listing_photo=best_photos[t],
        )
        for t, name in sorted(pairs)
    ]
