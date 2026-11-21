"""Command-line entry point for the judge scaffold."""

import argparse
import json
from pathlib import Path

from judge import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a sample unboxing verdict")
    parser.add_argument("case_dir", type=Path, help="Case directory for verdict.json")
    args = parser.parse_args()
    print(json.dumps(run(args.case_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
