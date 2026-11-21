"""Read local video metadata with the judge's shared ffprobe settings."""

import json
import subprocess
from pathlib import Path
from typing import Any


def probe_video_metadata(path: Path, entries: str) -> dict[str, Any]:
    """Read the requested JSON fields from the first video stream and its container."""
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-select_streams",
            "v:0",
            "-show_entries",
            entries,
            "-of",
            "json",
            "-i",
            str(path.resolve()),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    metadata = json.loads(process.stdout)
    if not isinstance(metadata, dict):
        raise ValueError("Expected a video metadata object from ffprobe.")
    return metadata
