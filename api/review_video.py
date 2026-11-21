"""Review a case's consented demo material locally before uploading its video."""

import argparse
from pathlib import Path

from api.app.judging import CaseJudge
from api.app.review_prompt import review_choice
from api.app.store import Store
from judge import ReviewRequest
from judge.opening_review import prompt_opening_review


def review(request: ReviewRequest) -> bool:
    if review_choice(request) != "approve":
        raise SystemExit("Review stopped.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id")
    parser.add_argument("video", type=Path)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    verdict = CaseJudge(Store(args.data_dir)).prepare(
        args.case_id, args.video, review, opening_review=prompt_opening_review
    )
    print(f"Prepared {verdict.case_id}. Upload the same recording to this case.")


if __name__ == "__main__":
    main()
