"""Check the probe settings and error mapping through both metadata consumers."""

import json
import subprocess
from pathlib import Path

import pytest

from judge.intake import IntakeError, inspect_video
from judge.sampling import SamplingError, _presentation_start_offset


def test_intake_and_sampling_request_their_fields_with_the_same_local_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "-upload.mp4"
    path.write_bytes(b"video fixture")
    fields: list[str] = []
    payload = {
        "format": {"duration": "12.5", "start_time": "0.25"},
        "streams": [
            {
                "width": 640,
                "height": 480,
                "start_time": "2.75",
                "tags": {"creation_time": "2025-01-01T00:00:00Z"},
                "side_data_list": [{"rotation": 90}],
            }
        ],
    }

    def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        assert command[0] == "ffprobe"
        assert command[command.index("-protocol_whitelist") + 1] == "file"
        assert command[command.index("-select_streams") + 1] == "v:0"
        assert command[-2:] == ["-i", str(path.resolve())]
        assert options == {"capture_output": True, "text": True, "timeout": 15, "check": True}
        fields.append(command[command.index("-show_entries") + 1])
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload))

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr("judge.intake._dark_frame_ratio", lambda _: 0.0)

    intake = inspect_video(path)
    assert (intake.duration_seconds, intake.width, intake.height) == (12.5, 640, 480)
    assert intake.rotation_degrees == 90
    assert intake.creation_time == "2025-01-01T00:00:00Z"
    assert _presentation_start_offset(path) == 2.5
    assert fields == [
        "format=duration:format_tags=creation_time:"
        "stream=width,height,duration:stream_tags=rotate,creation_time:stream_side_data=rotation",
        "stream=start_time:format=start_time",
    ]


@pytest.mark.parametrize(
    ("outcome", "intake_message"),
    [
        (FileNotFoundError("ffprobe"), "inspection unavailable"),
        (subprocess.TimeoutExpired(["ffprobe"], 15), "inspection unavailable"),
        (subprocess.CalledProcessError(1, ["ffprobe"]), "Invalid or unreadable video"),
        (
            subprocess.CompletedProcess(["ffprobe"], 0, stdout="invalid JSON"),
            "Invalid video metadata",
        ),
        (subprocess.CompletedProcess(["ffprobe"], 0, stdout="[]"), "Invalid video metadata"),
        (
            subprocess.CompletedProcess(
                ["ffprobe"], 0, stdout='{"streams":[{"width":640,"height":480}],"format":[]}'
            ),
            "Invalid video metadata",
        ),
    ],
)
def test_probe_failures_get_stage_specific_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: Exception | subprocess.CompletedProcess[str],
    intake_message: str,
) -> None:
    path = tmp_path / "upload.mp4"
    path.write_bytes(b"video fixture")

    def run(*args: object, **options: object) -> subprocess.CompletedProcess[str]:
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(IntakeError, match=intake_message):
        inspect_video(path)
    with pytest.raises(SamplingError, match="playback timeline could not be read"):
        _presentation_start_offset(path)
