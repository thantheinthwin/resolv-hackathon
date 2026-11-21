"""Show private previews to the local operator and ask for an explicit decision."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from judge import ReviewRequest


def review_choice(request: ReviewRequest) -> Literal["approve", "decline"] | None:
    with TemporaryDirectory(prefix="judge-review-") as tmp:
        folder = Path(tmp)
        (folder / "context.txt").write_text(request.text, encoding="utf-8")
        names: list[str] = []
        for index, (name, data) in enumerate(request.images, 1):
            # Only generated filenames reach the filesystem. Keep references as plain text.
            extension = "png" if data.startswith(b"\x89PNG") else "jpg"
            filename = f"image-{index}.{extension}"
            (folder / filename).write_bytes(data)
            names.append(f"{filename} — {name}")
        if names:
            (folder / "images.txt").write_text("\n".join(names), encoding="utf-8")
        print(f"Inspect every file in {tmp} for personal data ({request.stage} stage).")
        choice = input("Type APPROVE to allow this transfer, DECLINE to reject, or Enter to stop: ")
    if choice == "APPROVE":
        return "approve"
    if choice == "DECLINE":
        return "decline"
    return None
