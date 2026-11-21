"""Tests for privacy processing; no unsanitized frame may be written here."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from judge.privacy import (
    PrivacyError,
    RedactionRegion,
    _load_face_detector,
    sanitize_frame,
    sanitize_frames,
)
from judge.sampling import SampledFrame


class FakeDetector:
    def __init__(
        self, boxes: list[tuple[int, int, int, int]], *, fail: bool = False
    ) -> None:
        self.boxes = boxes
        self.fail = fail
        self.calls = 0

    def detectMultiScale(
        self,
        image: np.ndarray,
        *,
        scaleFactor: float,
        minNeighbors: int,
        minSize: tuple[int, int],
    ) -> np.ndarray:
        self.calls += 1
        assert image.ndim == 2
        if self.fail:
            raise RuntimeError("detector failed")
        return np.asarray(self.boxes, dtype=np.int32).reshape(-1, 4)


def frame(seed: int = 9, *, image: np.ndarray | None = None) -> SampledFrame:
    if image is None:
        image = np.random.default_rng(seed).integers(
            0, 256, size=(96, 96, 3), dtype=np.uint8
        )
    return SampledFrame(
        timestamp_seconds=1.5,
        image=image,
        blur_score=100.0,
        scene_change=False,
    )


def test_no_faces_copies_input_but_does_not_claim_full_pii_safety() -> None:
    source = frame()
    original = source.image.copy()
    result = sanitize_frame(source, detector=FakeDetector([]))
    assert result.timestamp_seconds == 1.5
    assert result.faces_redacted == 0
    assert result.manual_review_required
    assert np.array_equal(result.image, original)
    assert result.image is not source.image
    assert not np.shares_memory(result.image, source.image)


def test_face_is_strongly_obscured_and_source_is_untouched() -> None:
    source = frame()
    original = source.image.copy()
    result = sanitize_frame(source, detector=FakeDetector([(20, 20, 24, 24)]))
    assert result.faces_redacted == 1
    assert not np.array_equal(result.image[20:44, 20:44], original[20:44, 20:44])
    assert np.array_equal(source.image, original)
    assert result.manual_review_required


def test_multiple_faces_and_edge_padding() -> None:
    source = frame()
    original = source.image.copy()
    result = sanitize_frame(
        source, detector=FakeDetector([(0, 0, 22, 22), (68, 66, 28, 30)])
    )
    assert result.faces_redacted == 2
    assert not np.array_equal(result.image[0:22, 0:22], original[0:22, 0:22])
    assert not np.array_equal(result.image[66:96, 68:96], original[66:96, 68:96])


def test_manual_parcel_label_masking_obscures_entire_region() -> None:
    source = frame()
    original = source.image.copy()
    mask = RedactionRegion(x=10, y=25, width=45, height=17)
    result = sanitize_frame(source, detector=FakeDetector([]), redactions=[mask])
    assert result.regions_redacted == 1
    assert np.count_nonzero(result.image[25:42, 10:55]) == 0
    assert np.array_equal(result.image[0:10, 0:10], original[0:10, 0:10])
    assert np.array_equal(source.image, original)


def test_mask_outside_frame_fails_closed() -> None:
    source = frame()
    with pytest.raises(PrivacyError, match="outside"):
        sanitize_frame(
            source,
            detector=FakeDetector([]),
            redactions=[RedactionRegion(x=90, y=5, width=10, height=10)],
        )


@pytest.mark.parametrize(
    "bad_image",
    [
        np.zeros((24, 24), dtype=np.uint8),
        np.zeros((24, 24, 4), dtype=np.uint8),
        np.zeros((24, 24, 3), dtype=np.float32),
        np.zeros((0, 24, 3), dtype=np.uint8),
    ],
)
def test_invalid_pixel_data_is_rejected(bad_image: np.ndarray) -> None:
    with pytest.raises(PrivacyError, match="8-bit BGR"):
        sanitize_frame(frame(image=bad_image), detector=FakeDetector([]))


def test_detector_errors_fail_closed() -> None:
    with pytest.raises(PrivacyError, match="Face detection failed"):
        sanitize_frame(frame(), detector=FakeDetector([], fail=True))


def test_detector_unavailable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingCascade:
        def empty(self) -> bool:
            return True

    monkeypatch.setattr(cv2, "CascadeClassifier", lambda _: MissingCascade())
    with pytest.raises(PrivacyError, match="unavailable"):
        _load_face_detector()


def test_invalid_detector_box_fails_closed() -> None:
    with pytest.raises(PrivacyError, match="invalid"):
        sanitize_frame(frame(), detector=FakeDetector([(10, 10, -3, 20)]))


def test_batch_reuses_detector_and_preserves_order() -> None:
    detector = FakeDetector([(12, 12, 24, 24)])
    source = [frame(4), frame(5)]
    source[1] = source[1].model_copy(update={"timestamp_seconds": 2.0})
    result = sanitize_frames(source, detector=detector)
    assert detector.calls == 2
    assert [item.timestamp_seconds for item in result] == [1.5, 2.0]
    assert all(item.faces_redacted == 1 for item in result)


def test_batch_masks_timestamp_specific_region() -> None:
    source = [frame(4)]
    result = sanitize_frames(
        source,
        detector=FakeDetector([]),
        redactions_by_timestamp={
            1.5: [RedactionRegion(x=0, y=0, width=10, height=10)]
        },
    )
    assert np.count_nonzero(result[0].image[:10, :10]) == 0


def test_sanitizer_has_no_file_side_effects(tmp_path: Path) -> None:
    sanitize_frame(frame(), detector=FakeDetector([(10, 10, 22, 22)]))
    assert list(tmp_path.iterdir()) == []
