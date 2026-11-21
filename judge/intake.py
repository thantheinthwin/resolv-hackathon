"""Local video intake checks. No frames are saved or sent to external services."""

import json
import math
import subprocess
from pathlib import Path
from typing import Any

import cv2
from pydantic import BaseModel, Field

MIN_DURATION_SECONDS = 5.0
MAX_DURATION_SECONDS = 120.0
MAX_VIDEO_BYTES = 50_000_000
DARK_FRAME_THRESHOLD = 0.40
DARK_PIXEL_MEAN = 40.0
SAMPLE_FPS = 2.0


class IntakeError(ValueError):
    """User-facing reason why a video cannot be accepted."""


class IntakeResult(BaseModel):
    """Validated metadata and recording-quality warnings (not a privacy pass)."""

    duration_seconds: float = Field(ge=MIN_DURATION_SECONDS, le=MAX_DURATION_SECONDS)
    size_bytes: int = Field(gt=0, le=MAX_VIDEO_BYTES)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    rotation_degrees: int
    creation_time: str | None = None
    dark_frame_ratio: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


def _probe(path: Path) -> dict[str, Any]:
    """Get actual video stream metadata using ffprobe, without a shell."""
    try:
        process = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "format=duration:format_tags=creation_time:"
                "stream=width,height,duration:stream_tags=rotate,creation_time:"
                "stream_side_data=rotation",
                "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise IntakeError("Video metadata inspection unavailable; please retry.") from exc
    if process.returncode != 0:
        raise IntakeError("Invalid or unreadable video file.")
    try:
        payload = json.loads(process.stdout)
        streams = payload["streams"]
        stream = streams[0]
        format_data = payload.get("format", {})
        duration = float(format_data.get("duration") or stream["duration"])
        rotation = stream.get("tags", {}).get("rotate", 0)
        for side_data in stream.get("side_data_list", []):
            if "rotation" in side_data:
                rotation = side_data["rotation"]
                break
        return {
            "duration": duration,
            "width": int(stream["width"]),
            "height": int(stream["height"]),
            "rotation": int(float(rotation)),
            "creation_time": stream.get("tags", {}).get("creation_time")
            or format_data.get("tags", {}).get("creation_time"),
        }
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
        raise IntakeError("Invalid video metadata; please upload a supported video.") from exc


def _dark_frame_ratio(path: Path) -> float:
    """Sample decoded frames in memory; never retain or transmit raw frames."""
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise IntakeError("Video cannot be decoded; please upload a different recording.")
    dark = 0
    sampled = 0
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise IntakeError("Video frame rate is invalid.")
        step = max(1, round(fps / SAMPLE_FPS))
        frame_index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % step == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                dark += float(gray.mean()) < DARK_PIXEL_MEAN
                sampled += 1
            frame_index += 1
    finally:
        capture.release()
    if not sampled:
        raise IntakeError("Video has no decodable frames.")
    return dark / sampled


def inspect_video(path: str | Path) -> IntakeResult:
    """Validate a local video and warn when more than 40% of sampled frames are dark.

    Does not certify privacy or authorize remote model calls.
    """
    video = Path(path)
    if not video.is_file():
        raise IntakeError("Video file not found.")
    size = video.stat().st_size
    if size == 0:
        raise IntakeError("Video file is empty.")
    if size > MAX_VIDEO_BYTES:
        raise IntakeError("Video exceeds the 50 MB upload limit.")

    metadata = _probe(video)
    duration = metadata["duration"]
    if not math.isfinite(duration) or not MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS:
        raise IntakeError("Video duration must be between 5 and 120 seconds.")
    if metadata["width"] <= 0 or metadata["height"] <= 0:
        raise IntakeError("Video has invalid dimensions.")
    dark_ratio = _dark_frame_ratio(video)
    return IntakeResult(
        duration_seconds=duration,
        size_bytes=size,
        width=metadata["width"],
        height=metadata["height"],
        rotation_degrees=metadata["rotation"],
        creation_time=metadata["creation_time"],
        dark_frame_ratio=dark_ratio,
        warnings=(
            ["More than 40% of video frames are dark; please consider re-recording."]
            if dark_ratio > DARK_FRAME_THRESHOLD else []
        ),
    )
