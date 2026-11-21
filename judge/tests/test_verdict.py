"""Decision rules at the boundary between grounded checks and the shared verdict."""

from typing import Literal

import pytest

from api.app.contracts import Check, CheckStatus, ClaimType, Finding, Verdict
from judge.integrity import IntegrityCheck, IntegrityFlag, IntegrityReport
from judge.verdict import EvidenceQuality, decide_verdict


def comparison(status: CheckStatus, confidence: float, *, grounded: bool = True) -> Check:
    findings = (
        [Finding(t=8.125, note_en="Visible mismatch", note_th="พบความแตกต่าง")]
        if status == "flag" and grounded
        else []
    )
    return Check(status=status, confidence=confidence, findings=findings)


def review(
    claim: ClaimType = "damaged",
    comparisons: dict[str, Check] | None = None,
    *,
    claim_confidence: float = 1.0,
    seal_confidence: float = 1.0,
    seal_status: CheckStatus = "pass",
    continuity_status: CheckStatus = "pass",
    label_status: CheckStatus = "pass",
    fraud: Literal["seal_opened", "cut", "label_mismatch"] | None = None,
    quality: EvidenceQuality = EvidenceQuality(),
) -> Verdict:
    return decide_verdict(
        case_id="UJ-TEST",
        claim_type=claim,
        claim_confidence=claim_confidence,
        comparisons=comparisons if comparisons is not None else {"damage": comparison("flag", 1)},
        integrity=IntegrityReport(
            flags=[IntegrityFlag(type=fraud, t=2.125, note="Integrity concern")] if fraud else [],
            checks={
                "seal": IntegrityCheck(status=seal_status, confidence=seal_confidence),
                "continuity": IntegrityCheck(status=continuity_status, confidence=0.7),
                "label": IntegrityCheck(status=label_status, confidence=1),
            },
        ),
        quality=quality,
    )


@pytest.mark.parametrize(
    ("status", "confidence", "leaning", "outcome"),
    [
        ("flag", 0.98, "buyer", "buyer_right"),
        ("flag", 0.90, "buyer", "buyer_right"),
        ("pass", 0.90, "seller", "seller_right"),
        ("flag", 0.89, "buyer", "needs_human"),
        ("pass", 0.89, "seller", "needs_human"),
        ("unclear", 0.99, "none", "needs_human"),
    ],
)
def test_deciding_check(status: CheckStatus, confidence: float, leaning: str, outcome: str) -> None:
    verdict = review(comparisons={"damage": comparison(status, confidence)})
    assert (verdict.verdict, verdict.leaning, verdict.confidence) == (outcome, leaning, confidence)
    assert verdict.display == ("unsure" if outcome == "needs_human" else "clear")
    assert ("Confidence is below 90%." in verdict.reason.en) == (confidence == 0.89)
    assert verdict.reason.th
    assert Verdict.model_validate_json(verdict.model_dump_json()) == verdict


@pytest.mark.parametrize(("claim_score", "seal_score"), [(0.88, 0.99), (0.99, 0.88)])
def test_lowest_claim_seal_or_deciding_confidence_controls(
    claim_score: float, seal_score: float
) -> None:
    verdict = review(claim_confidence=claim_score, seal_confidence=seal_score)
    assert (verdict.display, verdict.leaning, verdict.confidence) == ("unsure", "buyer", 0.88)


@pytest.mark.parametrize("fraud", ["seal_opened", "cut", "label_mismatch"])
def test_fraud_forces_review_even_at_full_confidence(
    fraud: Literal["seal_opened", "cut", "label_mismatch"],
) -> None:
    verdict = review(fraud=fraud)
    assert (verdict.verdict, verdict.leaning, verdict.confidence) == ("needs_human", "buyer", 1)
    assert [(flag.type, flag.t) for flag in verdict.flags] == [(fraud, 2.125)]


@pytest.mark.parametrize(
    ("seal", "continuity", "label"),
    [("unclear", "pass", "pass"), ("pass", "unclear", "pass"), ("pass", "pass", "flag")],
)
def test_incomplete_or_flagged_integrity_forces_review(
    seal: CheckStatus, continuity: CheckStatus, label: CheckStatus
) -> None:
    assert review(seal_status=seal, continuity_status=continuity, label_status=label).display == (
        "unsure"
    )


def test_unreadable_label_is_skipped() -> None:
    assert review(label_status="unclear").display == "clear"


@pytest.mark.parametrize("status", ["pass", "flag"])
def test_counterfeit_always_requires_human_review(status: CheckStatus) -> None:
    verdict = review("counterfeit", {"counterfeit": comparison(status, 1)})
    assert (verdict.verdict, verdict.display, verdict.confidence) == ("needs_human", "unsure", 1)
    assert verdict.leaning == ("buyer" if status == "flag" else "seller")


@pytest.mark.parametrize(
    ("listing", "variant", "leaning", "confidence"),
    [
        ("flag", "pass", "buyer", 0.93),
        ("pass", "flag", "buyer", 0.96),
        ("pass", "pass", "seller", 0.93),
        ("unclear", "pass", "none", 0.93),
        ("pass", "unclear", "none", 0.96),
    ],
)
def test_wrong_item_checks_product_before_variant(
    listing: CheckStatus, variant: CheckStatus, leaning: str, confidence: float
) -> None:
    verdict = review(
        "wrong_item", {"listing": comparison(listing, 0.93), "variant": comparison(variant, 0.96)}
    )
    assert (verdict.leaning, verdict.confidence) == (leaning, confidence)
    assert verdict.display == ("unsure" if leaning == "none" else "clear")


def test_missing_claim_uses_count_and_ignores_unrelated_flags() -> None:
    verdict = review("missing", {"count": comparison("pass", 1), "damage": comparison("flag", 1)})
    assert verdict.verdict == "seller_right"
    assert verdict.checks["damage"].findings[0].t == 8.125


def test_missing_check_and_ungrounded_flag_are_unclear() -> None:
    verdict = review(comparisons={"damage": comparison("flag", 1, grounded=False)})
    assert (verdict.display, verdict.leaning, verdict.confidence) == ("unsure", "none", 0)
    assert verdict.checks["damage"].status == "unclear"
    missing = review(comparisons={})
    assert (missing.display, missing.leaning, missing.confidence) == ("unsure", "none", 0)


@pytest.mark.parametrize(
    "quality",
    [
        EvidenceQuality(blurred=True),
        EvidenceQuality(dark=True),
        EvidenceQuality(item_not_fully_shown=True),
    ],
)
def test_poor_evidence_caps_confidence_without_changing_leaning(quality: EvidenceQuality) -> None:
    verdict = review(quality=quality)
    assert (verdict.display, verdict.leaning, verdict.confidence) == ("unsure", "buyer", 0.89)


def test_warm_light_caps_variant_only() -> None:
    quality = EvidenceQuality(warm_light=True)
    checks = {"listing": comparison("pass", 1), "variant": comparison("flag", 0.98)}
    verdict = review("wrong_item", checks, quality=quality)
    assert (verdict.display, verdict.leaning, verdict.confidence) == ("unsure", "buyer", 0.70)
    assert verdict.checks["variant"].confidence == 0.70
    assert checks["variant"].confidence == 0.98
    checks["listing"] = comparison("flag", 0.98)
    assert review("wrong_item", checks, quality=quality).verdict == "buyer_right"
