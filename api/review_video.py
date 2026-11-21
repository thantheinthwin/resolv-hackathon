"""Review a case's consented demo material locally before uploading its video."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from api.app.judging import CaseJudge
from api.app.store import Store


def review(stage: str, files: dict[str, bytes]) -> bool:
    with TemporaryDirectory(prefix="judge-review-") as tmp:
        for name, data in files.items():
            path = Path(tmp) / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
        print(f"Inspect every file in {tmp} for personal data ({stage} stage).")
        if input("Approve these exact inputs for external processing? Type APPROVE: ") != "APPROVE":
            raise SystemExit("Review stopped.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id")
    parser.add_argument("video", type=Path)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    verdict = CaseJudge(Store(args.data_dir)).prepare(args.case_id, args.video, review)
    print(f"Prepared {verdict.case_id}. Upload the same recording to this case.")


if __name__ == "__main__":
    main()
