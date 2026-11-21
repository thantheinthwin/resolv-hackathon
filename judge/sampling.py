"""Select informative video frames in memory for the downstream privacy gate.

These images are UNSANITIZED. Never persist or transmit them before face/PII
redaction succeeds. This module intentionally performs no external requests.
"""

import math
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

SAMPLE_INTERVAL_SECONDS = 0.5
MIN_BLUR_VARIANCE = 60.0
DUPLICATE_HASH_DISTANCE = 6
SCENE_CHANGE_SCORE = 0.30
MAX_SELECTED_FRAMES = 30
OUTPUT_WIDTH = 768


class SamplingError(ValueError):
    """A video cannot be sampled into usable in-memory frames."""


class SampledFrame(BaseModel):
    """Raw video frame and metadata, for privacy processing only."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    timestamp_seconds: float = Field(ge=0)
    image: np.ndarray
    blur_score: float = Field(ge=0)
    scene_change: bool


def _gray_for_scoring(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    if width > 320:
        gray = cv2.resize(
            gray, (320, max(1, round(height * 320 / width))), interpolation=cv2.INTER_AREA
        )
    return gray


def _phash(gray: np.ndarray) -> np.ndarray:
    """Return the standard 64-bit DCT perceptual fingerprint."""
    reduced = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    coefficients = cv2.dct(reduced.astype(np.float32))[:8, :8]
    median = float(np.median(coefficients.ravel()[1:]))
    return (coefficients > median).ravel()


def _resize_for_output(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    if width <= OUTPUT_WIDTH:
        return frame.copy()
    target_height = max(1, round(height * OUTPUT_WIDTH / width))
    return cv2.resize(
        frame, (OUTPUT_WIDTH, target_height), interpolation=cv2.INTER_AREA
    )


def sample_frames(
    video_path: str | Path, *, max_frames: int = MAX_SELECTED_FRAMES
) -> list[SampledFrame]:
    """Sample up to 2 fps and retain sharp, nonduplicate moments across the video.

    A frame is kept at approximately one-second intervals or at detected large
    scene changes. If over the limit, select evenly across the whole recording.
    The scene-change score is a simple pixel-distance approximation, not the
    ffmpeg scene filter; tune or replace it after evaluation.
    """
    if max_frames < 1:
        raise ValueError("max_frames must be positive")
    video = Path(video_path)
    if not video.is_file():
        raise SamplingError("Video file not found.")
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise SamplingError("Video cannot be decoded.")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not math.isfinite(fps) or fps <= 0:
            raise SamplingError("Invalid video frame rate.")

        selected: list[SampledFrame] = []
        last_hash: np.ndarray | None = None
        previous_small: np.ndarray | None = None
        next_sample_time = 0.0
        last_keep_time = -math.inf
        index = 0
        decoded = False
        while True:
            success, frame = capture.read()
            if not success:
                break
            decoded = True
            timestamp = index / fps
            index += 1
            if timestamp + 1e-8 < next_sample_time:
                continue
            next_sample_time += SAMPLE_INTERVAL_SECONDS

            gray = _gray_for_scoring(frame)
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            small = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
            scene_change = (
                previous_small is not None
                and float(cv2.absdiff(small, previous_small).mean()) / 255.0
                > SCENE_CHANGE_SCORE
            )
            previous_small = small
            if sharpness < MIN_BLUR_VARIANCE:
                continue

            fingerprint = _phash(gray)
            if (
                last_hash is not None
                and int(np.count_nonzero(fingerprint != last_hash))
                <= DUPLICATE_HASH_DISTANCE
            ):
                continue
            if timestamp - last_keep_time < 1.0 and not scene_change:
                continue

            selected.append(
                SampledFrame(
                    timestamp_seconds=round(timestamp, 3),
                    image=_resize_for_output(frame),
                    blur_score=sharpness,
                    scene_change=scene_change,
                )
            )
            last_hash = fingerprint
            last_keep_time = timestamp

        if not decoded:
            raise SamplingError("Video contains no decodable frames.")
        if not selected:
            raise SamplingError("Video contains no usable sharp frames.")
        limit = min(max_frames, MAX_SELECTED_FRAMES)
        if len(selected) > limit:
            indices = np.linspace(0, len(selected) - 1, num=limit).astype(int)
            selected = [selected[int(i)] for i in indices]
        return selected
    finally:
        capture.release()
