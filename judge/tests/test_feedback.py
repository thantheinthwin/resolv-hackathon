"""Check the single complaint result and the reason a reviewer can act on."""

import pytest

from api.app.contracts import Check, CheckStatus, Evidence, Finding, Step, Verdict
from judge.feedback import ComplaintFeedback, FeedbackState, VideoStatus, build_complaint_feedback
from judge.integrity import IntegrityCheck, IntegrityFlag, IntegrityReport
from judge.verdict import decide_verdict

T = 2.125


def verdict_for(
    status: CheckStatus,
    *,
    confidence: float = 0.98,
    seal: CheckStatus = "pass",
    cut: bool = False,
    evidence_time: float | None = T,
) -> Verdict:
    checks = {
        "damage": Check(
            status=status,
            confidence=confidence,
            findings=(
                [Finding(t=T, note_en="Crack on the product.", note_th="ตัวสินค้าแตก")]
                if status == "flag"
                else []
            ),
        ),
    }
    result = decide_verdict(
        case_id="UJ-FEEDBACK",
        claim_type="damaged",
        claim_confidence=1,
        comparisons=checks,
        integrity=IntegrityReport(
            checks={
                "seal": IntegrityCheck(status=seal, confidence=0.99 if seal == "pass" else 0),
                "continuity": IntegrityCheck(status="flag" if cut else "pass", confidence=0.7),
            },
            flags=[IntegrityFlag(type="cut", t=4.0, note="Possible cut")] if cut else [],
        ),
    )
    if status == "flag" and evidence_time is not None:
        result.evidence = [
            Evidence(
                t=evidence_time,
                check="damage",
                result="flag",
                frame="frames/1.jpg",
                listing_photo="listing/0.jpg",
            )
        ]
    return result


def test_grounded_98_percent_complaint_gets_one_supported_result() -> None:
    verdict = verdict_for("flag")
    assert verdict.verdict == "buyer_right" and verdict.confidence == 0.98
    feedback = build_complaint_feedback(verdict, "damaged", video_status="analyzed")
    assert feedback.result == "complaint_supported"
    assert "damage" in feedback.reason.en.lower() and str(T) in feedback.reason.en
    assert str(T) in feedback.reason.th
    assert set(feedback.model_dump()) == {"result", "reason"}
    assert "%" not in feedback.model_dump_json()


@pytest.mark.parametrize(
    ("verdict", "video_status", "expected", "reason"),
    [
        (verdict_for("pass"), "analyzed", "needs_more_evidence", "damage check"),
        (verdict_for("flag", cut=True), "analyzed", "needs_more_evidence", "4.0"),
        (verdict_for("flag", confidence=0.84), "analyzed", "needs_more_evidence", "damage"),
        (verdict_for("flag", seal="unclear"), "analyzed", "needs_more_evidence", "seal"),
        (verdict_for("unclear"), "analyzed", "needs_more_evidence", "close-up"),
        (verdict_for("flag", evidence_time=None), "analyzed", "needs_more_evidence", "close-up"),
        (verdict_for("flag", evidence_time=3), "analyzed", "needs_more_evidence", "close-up"),
        (
            verdict_for("unclear", seal="unclear"),
            "no_usable_frames",
            "needs_more_evidence",
            "usable",
        ),
        (verdict_for("unclear", seal="unclear"), "absent", "needs_more_evidence", "opening"),
    ],
)
def test_routes_missing_evidence_and_human_judgment(
    verdict: Verdict,
    video_status: VideoStatus,
    expected: str,
    reason: str,
) -> None:
    feedback = build_complaint_feedback(verdict, "damaged", video_status=video_status)
    assert feedback.result == expected
    assert reason in feedback.reason.en and feedback.reason.th
    assert "%" not in feedback.model_dump_json()


def test_pending_privacy_review_belongs_with_the_shop() -> None:
    verdict = verdict_for("unclear", seal="unclear")
    verdict.steps = [Step(name="complaint", kind="code", seconds=0, output="Text awaits review")]
    feedback = build_complaint_feedback(
        verdict,
        "damaged",
        video_status="analyzed",
        state=FeedbackState(complaint_review_pending=True),
    )
    assert feedback.result == "needs_more_evidence"
    assert "privacy review" in feedback.reason.en


def test_possible_counterfeit_is_a_human_decision() -> None:
    feedback = build_complaint_feedback(
        verdict_for("unclear", seal="unclear"), "counterfeit", video_status="absent"
    )
    assert feedback.result == "needs_more_evidence"
    assert "authenticity" in feedback.reason.en


@pytest.mark.parametrize("status", ["pass", "flag"])
def test_product_link_requests_purchase_confirmation_even_with_strong_comparison(
    status: CheckStatus,
) -> None:
    feedback = build_complaint_feedback(
        verdict_for(status), "wrong_item", video_status="analyzed", purchase_verified=False
    )
    assert feedback.result == "needs_more_evidence"
    assert feedback.reason.en == "Please confirm which item and variant you ordered."
    assert "รุ่น" in feedback.reason.th


def test_product_link_integrity_flag_takes_priority() -> None:
    feedback = build_complaint_feedback(
        verdict_for("flag", cut=True),
        "damaged",
        video_status="analyzed",
        purchase_verified=False,
    )
    assert feedback.result == "needs_more_evidence"
    assert "cut" in feedback.reason.en and "confirm" in feedback.reason.en


def test_unreviewed_opening_is_a_shop_task() -> None:
    verdict = verdict_for("flag", seal="unclear")
    verdict.checks["seal"].note_en = "Operator skipped this step."
    verdict.checks["seal"].note_th = "ข้ามขั้นตอนนี้"
    feedback = build_complaint_feedback(
        verdict,
        "damaged",
        video_status="analyzed",
        state=FeedbackState(opening_review_pending=True),
    )
    assert feedback.result == "needs_more_evidence"
    assert "opening" in feedback.reason.en


def test_comparison_failure_is_a_shop_task() -> None:
    verdict = verdict_for("unclear")
    verdict.checks["damage"].note_en = "Please try again."
    verdict.checks["damage"].note_th = "โปรดลองอีกครั้ง"
    feedback = build_complaint_feedback(
        verdict,
        "damaged",
        video_status="analyzed",
        state=FeedbackState(failed_comparisons={"damage"}),
    )
    assert feedback.result == "needs_more_evidence"
    assert "comparison could not be completed" in feedback.reason.en


def test_product_link_counterfeit_review_preserves_the_evidence_request() -> None:
    feedback = build_complaint_feedback(
        verdict_for("unclear"), "counterfeit", video_status="analyzed", purchase_verified=False
    )
    assert feedback.result == "needs_more_evidence"
    assert "authenticity" in feedback.reason.en and "confirm" in feedback.reason.en


@pytest.mark.parametrize(
    ("status", "expected"), [("flag", "complaint_supported"), ("unclear", "needs_more_evidence")]
)
def test_model_note_cannot_masquerade_as_a_comparison_failure(
    status: CheckStatus, expected: str
) -> None:
    verdict = verdict_for(status)
    verdict.checks["damage"].note_en = "This check could not be completed reliably."
    verdict.checks["damage"].note_th = "ไม่สามารถดำเนินการตรวจสอบนี้ได้อย่างน่าเชื่อถือ"
    verdict.steps = [
        Step(
            name="complaint",
            kind="model",
            seconds=0,
            output="Written complaint awaits privacy review",
        )
    ]
    feedback = build_complaint_feedback(verdict, "damaged", video_status="analyzed")
    assert feedback.result == expected


def test_saved_human_review_feedback_loads_as_incomplete() -> None:
    feedback = ComplaintFeedback.model_validate(
        {"result": "needs_human_check", "reason": {"en": "Check the evidence.", "th": "ตรวจสอบหลักฐาน"}}
    )
    assert feedback.result == "needs_more_evidence"
    assert feedback.reason.en == "Check the evidence."
