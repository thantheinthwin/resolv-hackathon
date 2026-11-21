"""Conservative unboxing-video integrity checks on privacy-sanitized frames.

Continuity is a heuristic signal, not proof of editing or authenticity. Seal
and order-label checks require a separately supplied, grounded observation;
this module does not call a model, read raw video, or save any images.
"""

import re
from collections.abc import Sequence
from statistics import median
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from judge.privacy import SanitizedFrame

MIN_HISTORY = 3
MAX_COMPARABLE_GAP_SECONDS = 2.0
MIN_SHARPNESS = 60.0
JUMP_MULTIPLIER = 4.0
MIN_JUMP_SCORE = 0.05
MIN_PHASH_DISTANCE = 20
GROUNDING_TOLERANCE_SECONDS = 0.05
OPENING_WINDOW_SECONDS = 10.0
NO_CUT_PROOF = "No strong scene change in the sampled frames. "
NO_CUT_PROOF += "This does not prove the video is unedited."
CheckStatus = Literal["pass", "flag", "unclear"]


class IntegrityError(ValueError):
    """Input frames have not met the integrity checker contract."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpeningObservation(StrictModel):
    """Transient output of a future local/vision observation, never persisted.

    The caller must perform necessary local order-label reading before masking
    its PII, and only pass observations grounded in a supplied first-10s frame.
    No model or OCR implementation is provided in this step.
    """

    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    seal_state: Literal["intact", "opened", "unclear"] = "unclear"
    seal_confidence: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    observed_order_id: str | None = None
    label_confidence: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)


class IntegrityFinding(StrictModel):
    t: float = Field(ge=0, allow_inf_nan=False)
    note_en: str
    note_th: str


class IntegrityCheck(StrictModel):
    status: CheckStatus
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    findings: list[IntegrityFinding] = Field(default_factory=list)
    note_en: str | None = None


class IntegrityFlag(StrictModel):
    type: Literal["cut", "seal_opened", "label_mismatch"]
    t: float = Field(ge=0, allow_inf_nan=False)
    note: str


class IntegrityReport(StrictModel):
    """Matches the planned flags/checks shapes in the future Verdict contract."""

    flags: list[IntegrityFlag]
    checks: dict[str, IntegrityCheck]

    @property
    def requires_human_review(self) -> bool:
        return bool(self.flags) or any(check.status == "unclear" for check in self.checks.values())


def _check_frames(frames: Sequence[SanitizedFrame]) -> None:
    previous = -1.0
    for frame in frames:
        if not isinstance(frame, SanitizedFrame):
            raise IntegrityError("Expected only privacy-processed SanitizedFrame inputs.")
        image = frame.image
        if (
            not isinstance(image, np.ndarray)
            or image.ndim != 3
            or image.shape[2] != 3
            or image.dtype != np.uint8
            or min(image.shape[:2]) == 0
        ):
            raise IntegrityError("Invalid sanitized image; expected nonempty uint8 BGR.")
        if frame.timestamp_seconds <= previous:
            raise IntegrityError("Frame timestamps must be strictly increasing.")
        previous = frame.timestamp_seconds


def _gray(frame: SanitizedFrame) -> np.ndarray:
    image = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
    return cv2.resize(image, (64, 64), interpolation=cv2.INTER_AREA)


def _sharp(frame: SanitizedFrame) -> bool:
    """Match the project's blur score scale: up to 320 px wide."""
    gray = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    if width > 320:
        scaled_height = max(1, round(height * 320 / width))
        gray = cv2.resize(gray, (320, scaled_height), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var()) >= MIN_SHARPNESS


def _phash(gray: np.ndarray) -> np.ndarray:
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(small.astype(np.float32))[:8, :8]
    threshold = float(np.median(dct.ravel()[1:]))
    return (dct > threshold).ravel()


def _continuity(frames: Sequence[SanitizedFrame]) -> tuple[IntegrityCheck, list[IntegrityFlag]]:
    if len(frames) < MIN_HISTORY + 2:
        return IntegrityCheck(
            status="unclear",
            confidence=0.0,
            note_en="Not enough sampled frames to inspect continuity.",
        ), []

    previous_gray = _gray(frames[0])
    previous_sharp = _sharp(frames[0])
    previous_hash = _phash(previous_gray)
    history: list[float] = []
    skipped = 0
    flags: list[IntegrityFlag] = []
    findings: list[IntegrityFinding] = []
    for earlier, current in zip(frames, frames[1:]):
        current_gray = _gray(current)
        current_sharp = _sharp(current)
        current_hash = _phash(current_gray)
        gap = current.timestamp_seconds - earlier.timestamp_seconds
        if gap > MAX_COMPARABLE_GAP_SECONDS or not (previous_sharp and current_sharp):
            skipped += 1
            history.clear()  # Don't compare a jump across unseen or unreadable footage.
        else:
            difference = float(cv2.absdiff(previous_gray, current_gray).mean()) / 255.0
            hashes_apart = int(np.count_nonzero(previous_hash != current_hash))
            if len(history) >= MIN_HISTORY and (
                difference > JUMP_MULTIPLIER * max(median(history[-8:]), 0.01)
                and difference > MIN_JUMP_SCORE
                and hashes_apart >= MIN_PHASH_DISTANCE
            ):
                note = "Abrupt visual jump in sampled frames; possible edit, not proof."
                flags.append(IntegrityFlag(type="cut", t=current.timestamp_seconds, note=note))
                findings.append(
                    IntegrityFinding(
                        t=current.timestamp_seconds,
                        note_en=note,
                        note_th="พบการเปลี่ยนภาพฉับพลัน อาจมีการตัดต่อ แต่ยังไม่ใช่ข้อพิสูจน์",
                    )
                )
                history.clear()
            else:
                history.append(difference)
        previous_gray = current_gray
        previous_sharp = current_sharp
        previous_hash = current_hash

    if flags:
        return IntegrityCheck(
            status="flag",
            confidence=0.7,
            findings=findings,
            note_en="Suspicious discontinuity detected; the video needs human review.",
        ), flags
    if skipped or len(history) < MIN_HISTORY:
        return IntegrityCheck(
            status="unclear",
            confidence=0.0,
            note_en="Continuity could not be evaluated across all required sampled frames.",
        ), []
    return IntegrityCheck(status="pass", confidence=0.7, note_en=NO_CUT_PROOF), []


def _normalize_id(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _within_one_edit(expected: str, observed: str) -> bool:
    """Permit one OCR insertion/deletion/substitution, not arbitrary prefixes."""
    if abs(len(expected) - len(observed)) > 1:
        return False
    if len(expected) == len(observed):
        return sum(a != b for a, b in zip(expected, observed, strict=True)) <= 1
    shorter, longer = sorted((expected, observed), key=len)
    index_short = index_long = errors = 0
    while index_short < len(shorter) and index_long < len(longer):
        if shorter[index_short] == longer[index_long]:
            index_short += 1
        else:
            errors += 1
            if errors > 1:
                return False
        index_long += 1
    return True


def _opening_checks(
    frames: Sequence[SanitizedFrame],
    expected_order_id: str,
    observation: OpeningObservation | None,
) -> tuple[dict[str, IntegrityCheck], list[IntegrityFlag]]:
    unknown = IntegrityCheck(
        status="unclear",
        confidence=0.0,
        note_en="No grounded opening observation available.",
    )
    if observation is None or not any(
        frame.timestamp_seconds <= OPENING_WINDOW_SECONDS
        and abs(frame.timestamp_seconds - observation.timestamp_seconds)
        <= GROUNDING_TOLERANCE_SECONDS
        for frame in frames
    ):
        return {"seal": unknown, "label": unknown.model_copy(deep=True)}, []

    timestamp = next(
        frame.timestamp_seconds
        for frame in frames
        if abs(frame.timestamp_seconds - observation.timestamp_seconds)
        <= GROUNDING_TOLERANCE_SECONDS
    )
    flags: list[IntegrityFlag] = []
    if observation.seal_confidence < 0.5 or observation.seal_state == "unclear":
        seal = IntegrityCheck(
            status="unclear",
            confidence=0.0,
            note_en="Parcel seal cannot be assessed.",
        )
    elif observation.seal_state == "opened":
        note = "Parcel seal appears opened before the filmed unboxing."
        flags.append(IntegrityFlag(type="seal_opened", t=timestamp, note=note))
        finding = IntegrityFinding(
            t=timestamp,
            note_en=note,
            note_th="ซีลพัสดุดูเหมือนถูกเปิดก่อนเริ่มแกะกล่อง",
        )
        seal = IntegrityCheck(
            status="flag",
            confidence=observation.seal_confidence,
            findings=[finding],
        )
    else:
        seal = IntegrityCheck(
            status="pass",
            confidence=observation.seal_confidence,
            note_en="Parcel seal appears intact in the opening frame; not proof of authenticity.",
        )

    expected = _normalize_id(expected_order_id)
    observed = _normalize_id(observation.observed_order_id or "")
    if len(expected) < 5 or len(observed) < 5 or observation.label_confidence < 0.5:
        label = IntegrityCheck(
            status="unclear",
            confidence=0.0,
            note_en="Order label is not readable or reliable.",
        )
    elif not _within_one_edit(expected, observed):
        note = "Visible order code differs from the expected order code."
        flags.append(IntegrityFlag(type="label_mismatch", t=timestamp, note=note))
        finding = IntegrityFinding(
            t=timestamp,
            note_en=note,
            note_th="รหัสคำสั่งซื้อบนพัสดุไม่ตรงกับข้อมูลการสั่งซื้อ",
        )
        label = IntegrityCheck(
            status="flag",
            confidence=observation.label_confidence,
            findings=[finding],
        )
    else:
        label = IntegrityCheck(
            status="pass",
            confidence=observation.label_confidence,
            note_en="Order-code observation matches within one OCR character.",
        )
    return {"seal": seal, "label": label}, flags


def assess_integrity(
    frames: Sequence[SanitizedFrame],
    *,
    expected_order_id: str,
    observation: OpeningObservation | None = None,
) -> IntegrityReport:
    """Return grounded, conservative flags/checks for later verdict integration.

    The observation is supplied by a separate trusted stage, not inferred here.
    No image is saved, transmitted, or approved for external sharing.
    """
    _check_frames(frames)
    continuity, cut_flags = _continuity(frames)
    opening_checks, opening_flags = _opening_checks(frames, expected_order_id, observation)
    checks = {"continuity": continuity, **opening_checks}
    return IntegrityReport(flags=cut_flags + opening_flags, checks=checks)
