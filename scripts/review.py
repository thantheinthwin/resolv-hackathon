"""Run the team review for the exact commits being published."""

import subprocess
import sys
import tempfile
from pathlib import Path


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def review(revision: str) -> None:
    head = git("rev-parse", "--verify", f"{revision}^{{commit}}")
    base = git("rev-parse", "--verify", "refs/remotes/origin/main^{commit}")
    if head == base:
        return
    receipt = Path(git("rev-parse", "--git-path", f"competition-review/{base}/{head}"))
    if receipt.is_file() and receipt.read_text().splitlines()[-1:] == ["REVIEW_PASS"]:
        print(f"Four-gate review already passed for {head[:12]} against {base[:12]}.")
        return

    prompt = (
        f"Independently review the committed diff from git diff {base}...{head}. "
        f"Read the workflow with git show {head}:docs/WORKFLOW.md. "
        "Apply its UX/API, security, bugs and code-quality gates. For quality findings "
        "state the failure or maintenance cost and a regression check. Identify the relevant "
        "service reviewers for the PR. Inspect committed blobs at the supplied revisions, "
        "even if the working tree differs. Change nothing. Report findings with file and line. "
        "Finish with a separate line REVIEW_PASS only if all four gates pass. "
        "For findings or incomplete review, finish with REVIEW_BLOCKED."
    )
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "review.txt"
        subprocess.run(
            [
                "codex",
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "-c",
                'model_reasoning_effort="high"',
                "-o",
                str(output),
                prompt,
            ],
            stdin=subprocess.DEVNULL,
            check=True,
        )
        report = output.read_text().strip()
    print(report)
    if not report or report.splitlines()[-1].strip() != "REVIEW_PASS":
        raise SystemExit("Publication blocked. Address the review findings and retry.")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(report + "\n")


if __name__ == "__main__":
    try:
        review(sys.argv[1] if len(sys.argv) > 1 else "HEAD")
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"Could not complete the publication review: {error}")
