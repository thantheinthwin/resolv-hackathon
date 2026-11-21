"""Frame sampling tests. No frame should be written before privacy sanitization."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from judge.sampling import SamplingError, sample_frames


class FakeCapture:
    def __init__(self, frames: list[np.ndarray], fps: float = 2.0) -> None:
        self.frames = frames
        self.fps = fps
        self.index = 0
        self.released = False

    def isOpened(self) -> bool:
        return True

    def get(self, prop: int) -> float:
        return self.fps if prop == cv2.CAP_PROP_FPS else 0.0

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self.index >= len(self.frames):
            return False, None
        frame = self.frames[self.index]
        self.index += 1
        return True, frame

    def release(self) -> None:
        self.released = True


def sharp_frame(seed: int, width: int = 96, height: int = 96) -> np.ndarray:
    return np.random.default_rng(seed).integers(
        0, 256, size=(height, width, 3), dtype=np.uint8
    )


def setup_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frames: list[np.ndarray], fps: float = 2.0
) -> tuple[Path, FakeCapture]:
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"synthetic video")
    capture = FakeCapture(frames, fps)
    monkeypatch.setattr(cv2, "VideoCapture", lambda _: capture)
    return path, capture


def test_missing_video_rejected(tmp_path: Path) -> None:
    with pytest.raises(SamplingError, match="not found"):
        sample_frames(tmp_path / "missing.mp4")


def test_blurry_frames_are_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blurry = np.full((96, 96, 3), 127, dtype=np.uint8)
    path, capture = setup_video(tmp_path, monkeypatch, [blurry, sharp_frame(1)])
    frames = sample_frames(path)
    assert len(frames) == 1
    assert frames[0].timestamp_seconds == 0.5
    assert capture.released


def test_duplicates_are_removed_and_timestamps_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second, third = (sharp_frame(i) for i in range(3))
    path, _ = setup_video(
        tmp_path, monkeypatch, [first, first.copy(), second, second.copy(), third]
    )
    frames = sample_frames(path)
    assert [f.timestamp_seconds for f in frames] == [0.0, 1.0, 2.0]


def test_scene_change_retained_before_one_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = setup_video(tmp_path, monkeypatch, [sharp_frame(1), sharp_frame(2)])
    frames = sample_frames(path)
    assert [f.timestamp_seconds for f in frames] == [0.0, 0.5]
    assert frames[1].scene_change


def test_frame_width_and_image_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = setup_video(tmp_path, monkeypatch, [sharp_frame(1, width=1000, height=200)])
    frames = sample_frames(path)
    assert len(frames) == 1
    assert frames[0].image.shape[1] == 768
    assert isinstance(frames[0].image, np.ndarray)


def test_cap_preserves_start_and_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = setup_video(tmp_path, monkeypatch, [sharp_frame(i) for i in range(100)])
    frames = sample_frames(path, max_frames=30)
    assert len(frames) <= 30
    assert frames[0].timestamp_seconds == 0
    assert frames[-1].timestamp_seconds == 49.5


def test_does_not_write_unsanitized_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = setup_video(tmp_path, monkeypatch, [sharp_frame(5)])
    sample_frames(path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sample.mp4"]


def test_invalid_fps_rejected_and_capture_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, capture = setup_video(tmp_path, monkeypatch, [sharp_frame(1)], fps=0.0)
    with pytest.raises(SamplingError, match="frame rate"):
        sample_frames(path)
    assert capture.released


def test_no_frames_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, capture = setup_video(tmp_path, monkeypatch, [])
    with pytest.raises(SamplingError, match="decodable"):
        sample_frames(path)
    assert capture.released


def test_invalid_max_frames(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        sample_frames(tmp_path / "whatever.mp4", max_frames=0)
