"""Tests-first five-check listing comparison with private image inputs."""

from collections.abc import Callable
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import numpy as np
import pytest

from api.app.sample import LISTING, ORDER
from judge.matching import (
    CHECK_NAMES,
    MatchError,
    ReviewedListingPhoto,
    compare_listing,
    analyze_step5,
)
from judge.privacy import SanitizedFrame
from judge.vision import VisionObservation


def image() -> np.ndarray:
    return np.full((48, 48, 3), 127, dtype=np.uint8)


def frame(t: float = 2.0) -> SanitizedFrame:
    return SanitizedFrame(
        timestamp_seconds=t, image=image(), faces_redacted=0, regions_redacted=1
    )


def photo(*, reviewed: bool = True) -> ReviewedListingPhoto:
    return ReviewedListingPhoto(image=image(), privacy_reviewed=reviewed)


def observation() -> VisionObservation:
    return VisionObservation.model_validate({
        "status": "observed",
        "findings": [
            {"t": 2.0, "category": "color", "value": "navy", "confidence": 0.95}
        ],
        "note_en": "A navy shirt is visible.",
    })


def answer(
    status: str = "pass", t: float = 2.0, *, with_finding: bool = True
) -> dict[str, object]:
    return {
        "status": status,
        "confidence": 0.93,
        "findings": (
            [{"t": t, "note_en": "Color differs.", "note_th": "สีไม่ตรงกัน"}]
            if with_finding else []
        ),
        "note_en": "Compared to the order.",
    }


class FakeResponses:
    def __init__(self, outputs: dict[str, list[object]]) -> None:
        self.outputs = outputs
        self.lock = Lock()
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        with self.lock:
            self.calls.append(kwargs)
            payload = kwargs["input"]
            text = payload[1]["content"][0]["text"]
            task = next(name for name in CHECK_NAMES if f'"check": "{name}"' in text)
            item = self.outputs[task].pop(0)
        if isinstance(item, BaseException):
            raise item
        return SimpleNamespace(output_parsed=item)


class FakeClient:
    def __init__(self, outputs: dict[str, list[object]]) -> None:
        self.responses = FakeResponses(outputs)


def all_passes() -> dict[str, list[object]]:
    return {name: [answer()] for name in CHECK_NAMES}


def compare(
    client: FakeClient,
    *,
    photos: list[ReviewedListingPhoto] | None = None,
    frames: list[SanitizedFrame] | None = None,
    approved: bool = True,
    cache_dir: Path | None = None,
):
    return compare_listing(
        frames if frames is not None else [frame()],
        observation(),
        listing=LISTING,
        order=ORDER,
        listing_photos=photos if photos is not None else [photo()],
        privacy_approved=approved,
        model="mock-vision",
        client=client,
        cache_dir=cache_dir,
    )


def test_five_parallel_checks_have_structured_outputs_and_no_buyer_pii() -> None:
    client = FakeClient(all_passes())
    checks = compare(client)
    assert set(checks) == set(CHECK_NAMES)
    assert len(client.responses.calls) == 5
    for check in checks.values():
        assert check.status == "pass"
        assert check.confidence == 0.93
        assert check.findings[0].t == 2.0
    for call in client.responses.calls:
        assert call["timeout"] == 20.0
        assert call["store"] is False
        payload = str(call["input"])
        assert ORDER.buyer_name not in payload
        assert ORDER.id not in payload
        assert "I ordered black" not in payload


def test_rejects_unapproved_images_before_network() -> None:
    client = FakeClient(all_passes())
    with pytest.raises(MatchError, match="privacy approval"):
        compare(client, approved=False)
    with pytest.raises(MatchError, match="listing photo"):
        compare(client, photos=[photo(reviewed=False)])
    assert not client.responses.calls


def test_rejects_missing_listing_images() -> None:
    client = FakeClient(all_passes())
    with pytest.raises(MatchError, match="listing photo"):
        compare(client, photos=[])


def test_rejects_mismatched_order_listing() -> None:
    client = FakeClient(all_passes())
    changed = ORDER.model_copy(update={"listing_id": "wrong"})
    with pytest.raises(MatchError, match="listing ID"):
        compare_listing(
            [frame()], observation(), listing=LISTING, order=changed,
            listing_photos=[photo()], privacy_approved=True, client=client, model="mock"
        )
    assert not client.responses.calls


def test_flag_at_grounded_time_survives() -> None:
    outputs = all_passes()
    outputs["variant"] = [answer("flag", 2.03)]
    checks = compare(FakeClient(outputs))
    assert checks["variant"].status == "flag"
    assert checks["variant"].findings[0].t == 2.0


def test_hallucinated_flag_time_becomes_unclear() -> None:
    outputs = all_passes()
    outputs["damage"] = [answer("flag", 300.0)]
    checks = compare(FakeClient(outputs))
    assert checks["damage"].status == "unclear"
    assert checks["damage"].confidence == 0.0
    assert checks["damage"].findings == []


def test_clear_pass_with_no_findings_is_allowed() -> None:
    outputs = all_passes()
    outputs["count"] = [answer("pass", with_finding=False)]
    checks = compare(FakeClient(outputs))
    assert checks["count"].status == "pass"
    assert not checks["count"].findings


def test_invalid_schema_retried_only_once_for_one_check() -> None:
    outputs = all_passes()
    outputs["listing"] = [{"status": "invalid"}, answer("flag")]
    client = FakeClient(outputs)
    checks = compare(client)
    assert checks["listing"].status == "flag"
    assert len(client.responses.calls) == 6


def test_two_bad_model_outputs_only_affect_one_check() -> None:
    outputs = all_passes()
    outputs["counterfeit"] = [None, None]
    checks = compare(FakeClient(outputs))
    assert checks["counterfeit"].status == "unclear"
    assert checks["listing"].status == "pass"


def test_exception_message_not_exposed() -> None:
    outputs = all_passes()
    outputs["damage"] = [TimeoutError("private key sk-SECRET"), TimeoutError("again")]
    checks = compare(FakeClient(outputs))
    assert checks["damage"].status == "unclear"
    assert "SECRET" not in checks["damage"].model_dump_json()


def test_cache_is_private_and_avoids_a_second_model_call(tmp_path: Path) -> None:
    client = FakeClient(all_passes())
    first = compare(client, cache_dir=tmp_path / "cache")
    second = compare(client, cache_dir=tmp_path / "cache")
    assert first == second
    assert len(client.responses.calls) == 5
    cached = list((tmp_path / "cache").glob("*.json"))
    assert len(cached) == 5
    assert all(p.stat().st_mode & 0o077 == 0 for p in cached)
    assert all("image_url" not in p.read_text() for p in cached)


def test_corrupt_cache_is_ignored(tmp_path: Path) -> None:
    client = FakeClient(all_passes())
    directory = tmp_path / "cache"
    compare(client, cache_dir=directory)
    entry = next(directory.glob("*.json"))
    entry.write_text("invalid-json")
    # Only this check requires a new request.
    client.responses.outputs = {name: [answer()] for name in CHECK_NAMES}
    compare(client, cache_dir=directory)
    assert len(client.responses.calls) == 6


def test_cache_symlink_rejected(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "cache"
    link.symlink_to(target, target_is_directory=True)
    client = FakeClient(all_passes())
    with pytest.raises(MatchError, match="symlink"):
        compare(client, cache_dir=link)
    assert not client.responses.calls


def test_rejects_untrusted_raw_listing_photo() -> None:
    client = FakeClient(all_passes())
    with pytest.raises(MatchError, match="ReviewedListingPhoto"):
        compare(client, photos=[image()])
    assert not client.responses.calls


def test_full_step5_runs_observation_before_five_checks() -> None:
    class StageResponses(FakeResponses):
        def parse(self, **kwargs: object) -> SimpleNamespace:
            if kwargs["text_format"] is VisionObservation:
                with self.lock:
                    self.calls.append(kwargs)
                return SimpleNamespace(output_parsed=observation())
            return super().parse(**kwargs)

    client = FakeClient(all_passes())
    client.responses = StageResponses(all_passes())
    result = analyze_step5(
        [frame()],
        listing=LISTING,
        order=ORDER,
        listing_photos=[photo()],
        privacy_approved=True,
        client=client,
        model="mock-vision",
    )
    assert result.observation.status == "observed"
    assert set(result.checks) == set(CHECK_NAMES)
    assert len(client.responses.calls) == 6
    assert client.responses.calls[0]["text_format"] is VisionObservation
    assert all(
        call["text_format"] is not VisionObservation
        for call in client.responses.calls[1:]
    )


def test_stage_never_contacts_model_before_privacy_review() -> None:
    client = FakeClient(all_passes())
    with pytest.raises(MatchError, match="privacy approval"):
        analyze_step5(
            [frame()],
            listing=LISTING,
            order=ORDER,
            listing_photos=[photo()],
            client=client,
            model="mock-vision",
        )
    assert not client.responses.calls
