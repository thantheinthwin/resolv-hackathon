"""Privacy redaction of selected frames before storage or external model calls.

This module only returns in-memory images. Face detection is best effort, not
proof that an image contains no identifying information. A separate reviewer
must assess labels, background PII, and missed faces before external sharing.
"""

from collections.abc import Mapping, Sequence
import math
from typing import Literal, Protocol

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from judge.sampling import SampledFrame

FACE_PADDING_RATIO = 0.20
FACE_DETECTOR_FILENAME = "haarcascade_frontalface_default.xml"


class PrivacyError(ValueError):
    """Sanitization failed; the source frame must not leave the private pipeline."""


class RedactionRegion(BaseModel):
    """Pixel rectangle to mask after local order-ID verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class SanitizedFrame(BaseModel):
    """Processed frame, still requiring a privacy review before publication."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    image: np.ndarray
    faces_redacted: int = Field(ge=0)
    regions_redacted: int = Field(ge=0)
    manual_review_required: Literal[True] = True
    warnings: list[str] = Field(default_factory=list)


class FaceDetector(Protocol):
    """OpenCV-compatible detector interface, injectable for deterministic tests."""

    def detectMultiScale(
        self,
        image: np.ndarray,
        *,
        scaleFactor: float,
        minNeighbors: int,
        minSize: tuple[int, int],
    ) -> np.ndarray: ...


def _load_face_detector() -> FaceDetector:
    """Require the locally installed frontal-face cascade; fail closed if absent."""
    path = cv2.data.haarcascades + FACE_DETECTOR_FILENAME
    try:
        detector = cv2.CascadeClassifier(path)
        if detector.empty():
            raise PrivacyError("Face detector unavailable; cannot release this frame.")
    except cv2.error as exc:
        raise PrivacyError("Face detector unavailable; cannot release this frame.") from exc
    return detector


def _validate_pixels(image: np.ndarray) -> None:
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
        or image.shape[0] == 0
        or image.shape[1] == 0
    ):
        raise PrivacyError("Expected a nonempty 8-bit BGR video frame.")


def _obscure_face(image: np.ndarray, rect: tuple[int, int, int, int]) -> None:
    """Apply padded, aggressive pixelation and blur to one detected face."""
    height, width = image.shape[:2]
    x, y, face_width, face_height = rect
    if face_width <= 0 or face_height <= 0:
        raise PrivacyError("Face detector produced an invalid rectangle.")
    if x >= width or y >= height or x + face_width <= 0 or y + face_height <= 0:
        raise PrivacyError("Face detector produced an invalid rectangle.")

    padding = max(2, math.ceil(max(face_width, face_height) * FACE_PADDING_RATIO))
    left = max(0, x - padding)
    top = max(0, y - padding)
    right = min(width, x + face_width + padding)
    bottom = min(height, y + face_height + padding)
    if left >= right or top >= bottom:
        raise PrivacyError("Face detector produced an invalid rectangle.")

    roi = image[top:bottom, left:right]
    # Reduce the face to a 3x3 signal before interpolation; Gaussian blur alone
    # can preserve recognizable details at larger face sizes.
    low_resolution = cv2.resize(roi, (3, 3), interpolation=cv2.INTER_AREA)
    pixelated = cv2.resize(
        low_resolution, (right - left, bottom - top), interpolation=cv2.INTER_LINEAR
    )
    kernel = max(3, (min(right - left, bottom - top) // 2) | 1)
    image[top:bottom, left:right] = cv2.GaussianBlur(pixelated, (kernel, kernel), 0)


def sanitize_frame(
    frame: SampledFrame,
    *,
    detector: FaceDetector | None = None,
    redactions: Sequence[RedactionRegion] = (),
) -> SanitizedFrame:
    """Blur visible frontal faces and mask explicitly supplied sensitive areas.

    Additional regions (e.g. shipping-label address and telephone number)
    must be located locally. This function does NOT find text or authorize
    publication. On failure it raises without returning an unredacted image.
    """
    _validate_pixels(frame.image)
    local_detector = detector if detector is not None else _load_face_detector()
    image = frame.image.copy()
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        boxes = local_detector.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24)
        )
        faces = 0
        for box in boxes:
            if len(box) != 4:
                raise PrivacyError("Face detector produced an invalid rectangle.")
            _obscure_face(image, tuple(int(value) for value in box))
            faces += 1
        height, width = image.shape[:2]
        for area in redactions:
            if area.x + area.width > width or area.y + area.height > height:
                raise PrivacyError("Sensitive region extends outside the video frame.")
            image[
                area.y : area.y + area.height,
                area.x : area.x + area.width,
            ] = 0
    except PrivacyError:
        raise
    except (cv2.error, ValueError, TypeError, RuntimeError) as exc:
        raise PrivacyError("Face detection failed; frame cannot be released.") from exc

    return SanitizedFrame(
        timestamp_seconds=frame.timestamp_seconds,
        image=image,
        faces_redacted=faces,
        regions_redacted=len(redactions),
        warnings=[
            "Frontal-face detection can miss profiles or occluded faces; "
            "review all other visible PII before external sharing."
        ],
    )


def sanitize_frames(
    frames: Sequence[SampledFrame],
    *,
    detector: FaceDetector | None = None,
    redactions_by_timestamp: Mapping[float, Sequence[RedactionRegion]] | None = None,
) -> list[SanitizedFrame]:
    """Sanitize frames in order, loading the local face detector only once."""
    if not frames:
        return []
    local_detector = detector if detector is not None else _load_face_detector()
    locations = redactions_by_timestamp or {}
    return [
        sanitize_frame(
            frame,
            detector=local_detector,
            redactions=locations.get(frame.timestamp_seconds, ()),
        )
        for frame in frames
    ]
