"""Run the team's intake or sample judge for the local web rehearsal."""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi import HTTPException

from api.app.listings import photo_format, photo_preview
from judge import run
from judge.intake import IntakeError, inspect_video


def main(operation: str, value: str) -> None:
    if operation == "inspect":
        try:
            intake = inspect_video(value)
        except IntakeError as exc:
            print(json.dumps({"error": str(exc)}))
            return
        print(json.dumps({"warnings": intake.warnings}))
    elif operation == "photo":
        try:
            _, mime = photo_format(Path(value).read_bytes())
        except HTTPException as exc:
            print(json.dumps({"error": exc.detail}))
        else:
            print(json.dumps({"mime": mime}))
    elif operation == "claim-photo":
        try:
            path = Path(value)
            path.write_bytes(photo_preview(path.read_bytes()))
        except HTTPException as exc:
            print(json.dumps({"error": exc.detail}))
        else:
            print(json.dumps({"mime": "image/jpeg"}))
    elif operation == "judge":
        # Publish the result only if the owning case still exists.
        with TemporaryDirectory() as scratch:
            print(run(Path(scratch) / value).model_dump_json())
    else:
        raise ValueError("Unknown sample operation")


if __name__ == "__main__":
    main(*sys.argv[1:])
