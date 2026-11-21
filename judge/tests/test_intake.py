"""Intake gate contract tests; real video smoke test is documented in the PR."""

from pathlib import Path

import pytest

from judge.intake import IntakeError, inspect_video


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(IntakeError, match="not found"):
        inspect_video(tmp_path / "missing.mp4")


def test_empty_video_is_rejected(tmp_path: Path) -> None:
    video = tmp_path / "empty.mp4"
    video.touch()
    with pytest.raises(IntakeError, match="empty"):
        inspect_video(video)


@pytest.mark.parametrize("duration", [0, 4.99, 120.01, 200])
def test_invalid_duration_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, duration: float
) -> None:
    video = tmp_path / "movie.mp4"
    video.write_bytes(b"test")
    monkeypatch.setattr(
        "judge.intake._probe",
        lambda _: {
            "duration": duration, "width": 8, "height": 8,
            "rotation": 0, "creation_time": None,
        },
    )
    with pytest.raises(IntakeError, match="duration"):
        inspect_video(video)


@pytest.mark.parametrize("duration", [5.0, 120.0])
def test_inclusive_duration_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, duration: float
) -> None:
    video = tmp_path / "movie.mp4"
    video.write_bytes(b"test")
    monkeypatch.setattr(
        "judge.intake._probe",
        lambda _: {
            "duration": duration, "width": 8, "height": 8,
            "rotation": 90, "creation_time": None,
        },
    )
    monkeypatch.setattr("judge.intake._dark_frame_ratio", lambda _: 0.4)
    outcome = inspect_video(video)
    assert outcome.duration_seconds == duration
    assert outcome.rotation_degrees == 90
    assert outcome.warnings == []


def test_excess_darkness_warns_without_rejecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "movie.mp4"
    video.write_bytes(b"test")
    monkeypatch.setattr(
        "judge.intake._probe",
        lambda _: {
            "duration": 10, "width": 8, "height": 8,
            "rotation": 0, "creation_time": None,
        },
    )
    monkeypatch.setattr("judge.intake._dark_frame_ratio", lambda _: 0.41)
    result = inspect_video(video)
    assert result.dark_frame_ratio == 0.41
    assert result.warnings and "dark" in result.warnings[0].lower()


def test_oversize_rejected_before_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "huge.mp4"
    with video.open("wb") as stream:
        stream.truncate(50_000_001)
    monkeypatch.setattr("judge.intake._probe", lambda _: pytest.fail("probe should not run"))
    with pytest.raises(IntakeError, match="50 MB"):
        inspect_video(video)


def test_unreadable_media_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "bad.mp4"
    video.write_bytes(b"not a video")
    monkeypatch.setattr(
        "judge.intake._probe",
        lambda _: (_ for _ in ()).throw(IntakeError("Invalid video")),
    )
    with pytest.raises(IntakeError, match="Invalid video"):
        inspect_video(video)
