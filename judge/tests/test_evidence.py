"""Evidence pairs keep exact model timestamps and approved asset references."""

import numpy as np
import pytest
from pydantic import ValidationError

from api.app.contracts import Check, CheckStatus, Evidence, Finding
from judge.evidence import EvidenceError, FrameAsset, ListingAsset, build_evidence_pack
from judge.matching import ReviewedListingPhoto
from judge.privacy import SanitizedFrame

BLUE = (220, 50, 10)
RED = (10, 50, 220)


def pixels(color: tuple[int, int, int]) -> np.ndarray:
    return np.full((48, 36, 3), color, dtype=np.uint8)


def frame(t: float, ref: str, color: tuple[int, int, int] = BLUE) -> FrameAsset:
    return FrameAsset(
        ref=ref,
        frame=SanitizedFrame(
            timestamp_seconds=t, image=pixels(color), faces_redacted=1, regions_redacted=1
        ),
    )


def photo(ref: str, color: tuple[int, int, int] = BLUE, *, reviewed: bool = True) -> ListingAsset:
    return ListingAsset(
        ref=ref, photo=ReviewedListingPhoto(image=pixels(color), privacy_reviewed=reviewed)
    )


def check(status: CheckStatus, *times: float) -> Check:
    return Check(
        status=status,
        confidence=0.94,
        findings=[Finding(t=t, note_en="Visible finding", note_th="สิ่งที่เห็น") for t in times],
    )


def test_pairs_only_exact_grounded_comparison_flags_with_closest_photo() -> None:
    blue = frame(8.1254, "frames/0001.jpg")
    red = frame(9.1254, "frames/0002.jpg", RED)
    items = build_evidence_pack(
        {
            "variant": check("flag", 9.1254, 8.1254, 8.1254, 8.125, 300),
            "damage": check("pass", 8.1254),
            "label": check("flag", 8.1254),
            "count": check("unclear", 8.1254),
        },
        [blue, red],
        [photo("listing/1.jpg", RED), photo("listing/2.jpg")],
        privacy_approved=True,
    )
    assert items == [
        Evidence(
            t=8.1254, check="variant", result="flag", frame=blue.ref, listing_photo="listing/2.jpg"
        ),
        Evidence(
            t=9.1254, check="variant", result="flag", frame=red.ref, listing_photo="listing/1.jpg"
        ),
    ]
    assert [Evidence.model_validate_json(item.model_dump_json()) for item in items] == items


def test_photo_ties_follow_listing_order_and_check_identity_is_preserved() -> None:
    frames = [frame(8.125, "frames/0001.jpg")]
    items = build_evidence_pack(
        {"damage": check("flag", 8.125), "listing": check("flag", 8.125)},
        frames,
        [photo("listing/2.jpg"), photo("listing/1.jpg")],
        privacy_approved=True,
    )
    assert [(item.check, item.listing_photo) for item in items] == [
        ("damage", "listing/2.jpg"),
        ("listing", "listing/2.jpg"),
    ]


@pytest.mark.parametrize("approved", [False, True])
def test_both_pack_and_listing_photo_require_human_approval(approved: bool) -> None:
    with pytest.raises(EvidenceError, match="privacy approval"):
        build_evidence_pack(
            {"damage": check("flag", 8.125)},
            [frame(8.125, "frames/0001.jpg")],
            [photo("listing/1.jpg", reviewed=False)],
            privacy_approved=approved,
        )


@pytest.mark.parametrize(
    "ref", ["../frame.jpg", "frames/../frame.jpg", "frames/a%2fimg.jpg", "/frame.jpg"]
)
def test_rejects_unsafe_frame_references(ref: str) -> None:
    with pytest.raises(ValidationError):
        frame(1, ref)


def test_rejects_duplicate_timestamps_and_frame_refs() -> None:
    photos = [photo("listing/1.jpg")]
    with pytest.raises(EvidenceError, match="unique"):
        build_evidence_pack(
            {},
            [frame(1, "frames/1.jpg"), frame(1, "frames/2.jpg")],
            photos,
            privacy_approved=True,
        )
    with pytest.raises(EvidenceError, match="unique"):
        build_evidence_pack(
            {},
            [frame(1, "frames/1.jpg"), frame(2, "frames/1.jpg")],
            photos,
            privacy_approved=True,
        )


def test_rejects_invalid_image_pixels() -> None:
    bad = ListingAsset(
        ref="listing/1.jpg",
        photo=ReviewedListingPhoto(image=np.empty((1, 1)), privacy_reviewed=True),
    )
    with pytest.raises(EvidenceError, match="pixels"):
        build_evidence_pack({}, [], [bad], privacy_approved=True)


def test_missing_exact_frame_produces_no_pair() -> None:
    assert (
        build_evidence_pack(
            {"damage": check("flag", 8.125)},
            [frame(8.126, "frames/1.jpg")],
            [photo("listing/1.jpg")],
            privacy_approved=True,
        )
        == []
    )
