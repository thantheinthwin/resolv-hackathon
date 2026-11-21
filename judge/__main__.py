"""Command-line entry point for the judge scaffold."""

import argparse
import sys
from pathlib import Path
from uuid import uuid4

from judge import run
from judge.intake import IntakeError, inspect_video


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an unassessed sample verdict")
    parser.add_argument(
        "source",
        type=Path,
        help=(
            "A case directory (created if missing), or an existing video to inspect "
            "and report under data/cases/<case_id>/"
        ),
    )
    source = parser.parse_args().source
    directory = source
    if source.is_file():
        try:
            intake = inspect_video(source)
        except IntakeError as exc:
            parser.error(str(exc))
        for warning in intake.warnings:
            print(warning, file=sys.stderr)
        directory = Path("data/cases") / f"UJ-{uuid4().hex}"
    print(run(directory).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
