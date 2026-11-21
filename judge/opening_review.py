"""Capture a grounded seal and label observation from a trusted local operator."""

import subprocess
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from getpass import GetPassWarning, getpass
from typing import Self, cast

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from judge.integrity import OPENING_WINDOW_SECONDS, OpeningObservation, SealState
from judge.privacy import RedactionRegion
from judge.sampling import SampledFrame
from judge.vision import _encode_jpeg


class OpeningReviewError(ValueError):
    """The trusted operator could not supply a usable opening observation."""


@dataclass(frozen=True)
class OpeningReviewFrame:
    """Private JPEG preview of an exact sampled frame."""

    number: int
    timestamp_seconds: float
    width: int
    height: int
    jpeg: bytes = field(repr=False)


@dataclass(frozen=True)
class OpeningReviewRequest:
    """Show these previews to the host operator only."""

    frames: tuple[OpeningReviewFrame, ...]


class OpeningReviewSelection(BaseModel):
    """Use the displayed frame number so the worker supplies the actual timestamp."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    frame_number: int = Field(ge=1)
    seal_state: SealState
    label_region: RedactionRegion | None = None
    order_code: SecretStr | None = Field(default=None, max_length=128, repr=False)

    @model_validator(mode="after")
    def require_label_mask(self) -> Self:
        if (
            self.order_code
            and self.order_code.get_secret_value().strip()
            and self.label_region is None
        ):
            raise ValueError("A readable order code requires a label mask on the selected frame.")
        return self


OpeningReviewer = Callable[[OpeningReviewRequest], OpeningReviewSelection | None]


def _preview(number: int, frame: SampledFrame) -> OpeningReviewFrame:
    height, width = frame.image.shape[:2]
    return OpeningReviewFrame(
        number=number,
        timestamp_seconds=frame.timestamp_seconds,
        width=width,
        height=height,
        jpeg=_encode_jpeg(frame.image),
    )


def _fits(frame: OpeningReviewFrame, region: RedactionRegion) -> bool:
    return region.x + region.width <= frame.width and region.y + region.height <= frame.height


def collect_opening_review(
    frames: Sequence[SampledFrame], reviewer: OpeningReviewer
) -> tuple[OpeningObservation, RedactionRegion | None] | None:
    """Collect a local observation and a mask to apply before visual analysis."""
    early = (frame for frame in frames if frame.timestamp_seconds <= OPENING_WINDOW_SECONDS)
    previews = tuple(_preview(number, frame) for number, frame in enumerate(early, start=1))
    if not previews:
        return None
    selection = reviewer(OpeningReviewRequest(frames=previews))
    if selection is None:
        return None
    if not isinstance(selection, OpeningReviewSelection) or not 1 <= selection.frame_number <= len(
        previews
    ):
        raise OpeningReviewError("Choose one of the displayed opening frames.")

    frame = previews[selection.frame_number - 1]
    region = selection.label_region
    if region is not None and not _fits(frame, region):
        raise OpeningReviewError("The label mask must be inside the selected opening frame.")
    code = selection.order_code.get_secret_value().strip() if selection.order_code else ""
    if code and region is None:
        raise OpeningReviewError(
            "A readable order code requires a label mask on the selected frame."
        )
    return (
        OpeningObservation(
            timestamp_seconds=frame.timestamp_seconds,
            seal_state=selection.seal_state,
            seal_confidence=0 if selection.seal_state == "unclear" else 1,
            observed_order_id=code or None,
            label_confidence=1 if code else 0,
        ),
        region,
    )


def _show_with_ffplay(frame: OpeningReviewFrame) -> None:
    """View one private JPEG through a local process pipe."""
    try:
        subprocess.run(
            [
                "ffplay",
                "-loglevel",
                "error",
                "-protocol_whitelist",
                "pipe",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "-i",
                "pipe:0",
                "-window_title",
                f"Opening frame {frame.timestamp_seconds} s (close to continue)",
            ],
            input=frame.jpeg,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise OpeningReviewError("Could not display the opening frame with local ffplay.") from exc


def _read_code(prompt: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        try:
            return getpass(prompt)
        except GetPassWarning:
            raise OpeningReviewError("Use a private terminal to enter the order code.") from None


def _prompt_mask(frame: OpeningReviewFrame, read: Callable[[str], str]) -> RedactionRegion | None:
    while box := read(
        f"Label mask x y width height within {frame.width}x{frame.height} (Enter to skip): "
    ).strip():
        try:
            x, y, width, height = map(int, box.split())
            region = RedactionRegion(x=x, y=y, width=width, height=height)
            if _fits(frame, region):
                return region
        except ValueError:
            pass
        print("Enter four integers for a rectangle inside the frame.")
    return None


def prompt_opening_review(
    request: OpeningReviewRequest,
    *,
    show: Callable[[OpeningReviewFrame], None] = _show_with_ffplay,
    read: Callable[[str], str] = input,
    read_code: Callable[[str], str] = _read_code,
) -> OpeningReviewSelection | None:
    """Review the seal and label in a private terminal on the API host."""
    print("Choose a frame before the buyer begins opening the parcel.")
    for frame in request.frames:
        print(f"  {frame.number}. {frame.timestamp_seconds} s")
    try:
        while answer := read("Opening frame number (Enter to skip): ").strip():
            if not answer.isascii() or not answer.isdecimal() or len(answer) > 3:
                print("Choose one of the displayed frame numbers.")
                continue
            number = int(answer)
            if not 1 <= number <= len(request.frames):
                print("Choose one of the displayed frame numbers.")
                continue
            frame = request.frames[number - 1]
            show(frame)
            state = read("Seal before opening (intact/opened/unclear/back): ").strip().lower()
            if state not in ("intact", "opened", "unclear"):
                continue
            region = _prompt_mask(frame, read)
            code = read_code("Visible order code (Enter if unreadable): ").strip() if region else ""
            return OpeningReviewSelection(
                frame_number=number,
                seal_state=cast(SealState, state),
                label_region=region,
                order_code=SecretStr(code) if code else None,
            )
    except EOFError:
        return None
    return None
