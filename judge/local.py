"""Offline integrity-only verdict for an upload without a prior human review."""

from pathlib import Path
from time import monotonic

from api.app.contracts import Check, ClaimType, ProgressEvent, Step, Verdict
from judge.integrity import assess_integrity
from judge.matching import CHECK_NAMES
from judge.pipeline import Progress, write_atomically
from judge.privacy import sanitize_frames
from judge.sampling import NoSharpFrames, sample_frames
from judge.verdict import decide_verdict


def run_local(
    directory: Path, claim_type: ClaimType, order_id: str, *, progress: Progress | None = None
) -> Verdict:
    started = monotonic()
    if progress is not None:
        progress(ProgressEvent(event="started", step="sampling"))
    try:
        frames = sanitize_frames(sample_frames(directory / "video.mp4"))
    except NoSharpFrames:
        frames = []
    integrity = assess_integrity(frames, expected_order_id=order_id)
    if progress is not None:
        progress(ProgressEvent(event="finished", step="sampling"))
    steps = [
        Step(
            name="sampling",
            kind="code",
            seconds=monotonic() - started,
            output=f"{len(frames)} usable sanitized frames; local integrity checks complete.",
        )
    ]
    checks = {name: Check(status="unclear", confidence=0, findings=[]) for name in CHECK_NAMES}
    verdict = decide_verdict(
        case_id=directory.name,
        claim_type=claim_type,
        claim_confidence=0,
        comparisons=checks,
        integrity=integrity,
    )
    verdict.steps = steps
    write_atomically(directory / "verdict.json", verdict.model_dump_json().encode())
    return verdict
