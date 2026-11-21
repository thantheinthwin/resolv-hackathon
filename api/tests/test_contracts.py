import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.app.contracts import Case, Decision, Listing, Verdict
from judge import run

SAMPLE = Path(__file__).resolve().parents[2] / "judge" / "fixtures" / "verdict.sample.json"


@pytest.fixture
def sample() -> Verdict:
    return Verdict.model_validate_json(SAMPLE.read_bytes())


def test_judge_fixture_return_and_file_share_a_contract(sample: Verdict, tmp_path: Path) -> None:
    directory = tmp_path / "UJ-1234"
    returned = Verdict.model_validate(run(directory))
    persisted = Verdict.model_validate_json((directory / "verdict.json").read_bytes())
    assert returned == persisted == sample.model_copy(update={"case_id": directory.name})
    assert returned.model_dump(mode="json") == json.loads((directory / "verdict.json").read_bytes())


@pytest.mark.parametrize(
    ("leaning", "verdict"), [("buyer", "buyer_right"), ("seller", "seller_right")]
)
def test_clear_at_threshold(sample: Verdict, leaning: str, verdict: str) -> None:
    result = Verdict.model_validate(
        {
            **sample.model_dump(),
            "display": "clear",
            "leaning": leaning,
            "verdict": verdict,
            "confidence": 0.9,
        }
    )
    assert result.verdict == verdict


@pytest.mark.parametrize(
    "override",
    [
        {"confidence": 0.89},
        {"confidence": 1.01},
        {"confidence": float("nan")},
        {"leaning": "none"},
        {"verdict": "seller_right"},
        {"flags": [{"type": "cut", "t": 0, "note": "jump"}]},
        {"display": "unsure"},
    ],
)
def test_inconsistent_clear_verdict_rejected(sample: Verdict, override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Verdict.model_validate(
            {
                **sample.model_dump(),
                "confidence": 1,
                "verdict": "buyer_right",
                "leaning": "buyer",
                "display": "clear",
                **override,
            }
        )


@pytest.mark.parametrize(
    ("choice", "display", "reason", "allowed"),
    [
        ("agree", "clear", None, True),
        ("disagree", "clear", "other", True),
        ("disagree", "clear", None, False),
        ("disagree", "clear", "unknown", False),
        ("agree", "unsure", None, False),
        ("disagree", "unsure", "video unclear", False),
        ("side_buyer", "unsure", None, True),
        ("side_seller", "unsure", None, True),
        ("side_buyer", "clear", None, False),
        ("side_seller", "clear", None, False),
    ],
)
def test_case_decision_choices(
    sample: Verdict, choice: str, display: str, reason: str | None, allowed: bool
) -> None:
    verdict = sample.model_dump()
    if display == "clear":
        verdict.update(display="clear", leaning="buyer", verdict="buyer_right", confidence=0.99)
    case = {
        "id": sample.case_id,
        "order_id": "order",
        "claim_type": "wrong_item",
        "description": "Different item",
        "status": "decided",
        "created_at": "2026-11-21T00:00:00Z",
        "verdict": verdict,
        "decision": {"choice": choice, "reason": reason},
    }
    if allowed:
        assert Case.model_validate(case).decision == Decision.model_validate(case["decision"])
    else:
        with pytest.raises(ValidationError):
            Case.model_validate(case)


def test_case_rejects_clear_counterfeit_or_wrong_verdict_id(sample: Verdict) -> None:
    case = {
        "id": sample.case_id,
        "order_id": "order",
        "claim_type": "counterfeit",
        "description": "Fake",
        "status": "ready",
        "created_at": "2026-11-21T00:00:00Z",
        "verdict": sample.model_dump(),
    }
    assert Case.model_validate(case).verdict == sample
    with pytest.raises(ValidationError, match="different case"):
        Case.model_validate({**case, "id": "ANOTHER"})
    with pytest.raises(ValidationError, match="Counterfeit"):
        Case.model_validate(
            {
                **case,
                "verdict": {
                    **sample.model_dump(),
                    "display": "clear",
                    "leaning": "buyer",
                    "verdict": "buyer_right",
                    "confidence": 1,
                },
            }
        )


def test_listing_limits_and_photo_order() -> None:
    photos = ["/api/files/first.jpg", "/api/files/second.jpg", "/api/files/third.jpg"]
    fields = {
        "id": "listing",
        "title": "Shirt",
        "description": "A" * 1500,
        "price": 100,
        "photos": photos,
        "colors": ["Blue"],
        "sizes": ["S"],
        "box_contents": ["Shirt"],
    }
    assert Listing.model_validate(fields).photos == photos
    for update in (
        {"photos": []},
        {"photos": photos + ["fourth.jpg"]},
        {"description": "A" * 1501},
    ):
        with pytest.raises(ValidationError):
            Listing.model_validate({**fields, **update})


@pytest.mark.parametrize("status", ["awaiting_video", "checking", "failed", "ready", "decided"])
@pytest.mark.parametrize("with_verdict", [False, True])
@pytest.mark.parametrize("with_decision", [False, True])
def test_case_review_lifecycle(
    sample: Verdict, status: str, with_verdict: bool, with_decision: bool
) -> None:
    fields = {
        "id": sample.case_id,
        "order_id": "order",
        "claim_type": "missing",
        "description": "Missing item",
        "created_at": "2026-11-21T00:00:00Z",
        "status": status,
        "verdict": sample if with_verdict else None,
        "decision": {"choice": "side_buyer"} if with_decision else None,
    }
    valid_states = {
        ("awaiting_video", False, False),
        ("checking", False, False),
        ("failed", False, False),
        ("ready", True, False),
        ("decided", True, True),
    }
    if (status, with_verdict, with_decision) in valid_states:
        assert Case.model_validate(fields).status == status
    else:
        with pytest.raises(ValidationError):
            Case.model_validate(fields)
