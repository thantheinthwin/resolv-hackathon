"""Input snapshots and content-bound listing approvals for uploaded jobs."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from api.app import judging
from api.app.contracts import Case, Evidence, Verdict
from api.app.fake import SAMPLE_VERDICT
from api.app.sample import ORDER
from api.app.store import Store, save_case
from judge import ReviewRequest, ReviewRequired
from judge.vision import _encode_jpeg


def test_restarted_worker_uses_original_input_and_exact_reviewed_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path)
    store.initialize()
    case = Case(
        id="UJ-UPLOAD",
        order_id=ORDER.id,
        claim_type="wrong_item",
        description="Original complaint",
        status="checking",
        created_at=datetime.now(UTC),
    )
    with store.transaction() as db:
        save_case(db, case)
    directory = tmp_path / "cases" / case.id
    directory.mkdir(parents=True)
    (directory / "video.mp4").touch()
    monkeypatch.setattr(judging, "get_secret", lambda setting: "configured")
    previews: list[ReviewRequest] = []

    def pause(store: Store, case_id: str, request: ReviewRequest) -> bool:
        previews.append(request)
        raise ReviewRequired(request.stage)

    monkeypatch.setattr(judging, "require_approval", pause)
    with pytest.raises(ReviewRequired):
        judging.CaseJudge(store).run(directory)
    snapshot = directory / ".judge-inputs.json"
    assert snapshot.stat().st_mode & 0o077 == 0

    # A restart may load a changed demo catalog before the reviewer approves.
    monkeypatch.setattr(judging, "ORDER", ORDER.model_copy(update={"id": "NEW-ORDER"}))
    case.description = "Changed complaint"
    with store.transaction() as db:
        save_case(db, case)
    with pytest.raises(ReviewRequired):
        judging.CaseJudge(store).run(directory)
    assert previews[1].fingerprint == previews[0].fingerprint
    context = judging.CaseInputs.model_validate_json(snapshot.read_bytes())
    inputs = context.reviewed_inputs(lambda request: request.fingerprint == previews[0].fingerprint)
    assert inputs.description == "Original complaint" and inputs.order.id == case.order_id
    assert _encode_jpeg(inputs.listing_photos[0].image) == previews[0].images[0][1]

    # Interrupted model jobs may not silently publish a local-only verdict.
    monkeypatch.setattr(judging, "get_secret", lambda setting: None)
    with pytest.raises(ValueError, match="requires OPENAI_MODEL"):
        judging.CaseJudge(store).run(directory)
    assert not (directory / "verdict.json").exists()


def test_review_every_catalog_photo_before_building_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path)
    store.initialize()
    refs = [f"listings/LS-101/{i}.png" for i in range(3)]
    order = ORDER.model_copy(
        update={
            "listing": ORDER.listing.model_copy(
                update={"photos": [f"/api/files/{ref}" for ref in refs]}
            )
        }
    )
    monkeypatch.setattr(judging, "ORDER", order)
    photo = (Path(__file__).resolve().parents[1] / "fixtures" / "tee.png").read_bytes()
    with store.transaction() as db:
        db.executemany(
            "INSERT INTO listing_photos VALUES (?, ?, ?)",
            [(ref, "image/png", photo) for ref in refs],
        )
        case = Case(
            id="three-photos",
            order_id=order.id,
            claim_type="missing",
            description="",
            status="checking",
            created_at=datetime.now(UTC),
        )
        save_case(db, case)
    context = judging.CaseJudge(store)._context(case.id)

    def decline(request: ReviewRequest) -> bool:
        assert len(request.images) == 3
        assert all(data.startswith(b"\xff\xd8") for _, data in request.images)
        return False

    with pytest.raises(ReviewRequired):
        context.reviewed_inputs(decline)
    inputs = context.reviewed_inputs(lambda request: True)
    assert len(inputs.listing_photos) == 3
    assert all(photo.privacy_reviewed for photo in inputs.listing_photos)


@pytest.mark.parametrize(
    "invalid", ["reference", "source_dir", "target_dir", "source_image", "target_image"]
)
def test_invalid_prepared_assets_do_not_publish_any_files(tmp_path: Path, invalid: str) -> None:
    store = Store(tmp_path)
    case_dir = tmp_path / "cases" / "UJ-TEST"
    case_dir.mkdir(parents=True)
    source = tmp_path / ".judge-reviews" / case_dir.name / "pack"
    source.mkdir(parents=True)
    verdict = Verdict.model_validate_json(SAMPLE_VERDICT.read_bytes())
    verdict.case_id = case_dir.name
    pair = Evidence(
        t=0, check="variant", result="flag", frame="frames/0.jpg", listing_photo="listing/0.jpg"
    )
    verdict.evidence = [pair]
    for ref in (pair.frame, pair.listing_photo):
        path = source / ref
        path.parent.mkdir()
        path.write_bytes(b"image")
    separate = tmp_path / "separate"
    separate.mkdir()
    unrelated = separate / "unrelated.jpg"
    unrelated.write_bytes(b"untouched")
    if invalid == "reference":
        pair.frame = "other/image.jpg"
    elif invalid == "source_dir":
        (source / "frames").rename(separate / "original")
        (source / "frames").symlink_to(separate / "original", target_is_directory=True)
    elif invalid == "target_dir":
        (case_dir / "frames").symlink_to(separate, target_is_directory=True)
    elif invalid == "source_image":
        (source / pair.frame).unlink()
        (source / pair.frame).symlink_to(unrelated)
    else:
        (case_dir / "frames").mkdir()
        (case_dir / pair.frame).symlink_to(unrelated)
    (source / "verdict.json").write_text(verdict.model_dump_json())
    with pytest.raises(ValueError, match="Invalid prepared evidence"):
        judging.CaseJudge(store)._publish_prepared(case_dir, source, lambda event: None)
    assert unrelated.read_bytes() == b"untouched"
    assert not (case_dir / "verdict.json").exists()
    assert not (case_dir / "listing").exists()
