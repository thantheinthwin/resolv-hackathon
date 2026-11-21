"""Review a case's consented demo material locally before uploading its video."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from api.app.judging import CaseJudge
from api.app.store import Store


from judge import ReviewRequest


def review(request: ReviewRequest) -> bool:
    with TemporaryDirectory(prefix="judge-review-") as tmp:
        (Path(tmp) / "context.txt").write_text(request.text, encoding="utf-8")
        for name, data in request.images:
            path = Path(tmp) / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
        print(f"Inspect every file in {tmp} for personal data ({request.stage} stage).")
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
