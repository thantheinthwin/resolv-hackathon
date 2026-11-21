"""Apply the judge rules to grounded checks without network or filesystem I/O."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, validate_call

from api.app.contracts import Check, ClaimType, Confidence, Flag, Reason, Verdict
from judge.integrity import IntegrityReport

CLEAR_CONFIDENCE = 0.90
LIMITED_EVIDENCE_CAP = 0.89
WARM_VARIANT_CAP = 0.70
CLAIM_CHECK = {
    "missing": "count",
    "damaged": "damage",
    "counterfeit": "counterfeit",
}
LEANING = {"flag": "buyer", "pass": "seller", "unclear": "none"}


class EvidenceQuality(BaseModel):
    """Quality limitations measured on the evidence used by the deciding check."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    blurred: bool = False
    dark: bool = False
    item_not_fully_shown: bool = False
    warm_light: bool = False


def _deciding_check(claim_type: ClaimType, checks: dict[str, Check]) -> tuple[Check, float]:
    unknown = Check(status="unclear", confidence=0, findings=[])
    if claim_type != "wrong_item":
        check = checks.get(CLAIM_CHECK[claim_type], unknown)
        return check, check.confidence

    product = checks.get("listing", unknown)
    if product.status != "pass":
        return product, product.confidence

    variant = checks.get("variant", unknown)
    confidence = variant.confidence
    if variant.status == "pass":
        confidence = min(product.confidence, confidence)
    return variant, confidence


def _reason(
    leaning: Literal["buyer", "seller", "none"],
    confidence: float,
    *,
    fraud: bool,
    integrity_incomplete: bool,
    counterfeit: bool,
) -> Reason:
    messages = {
        "buyer": ("The relevant check supports the complaint.", "ผลการตรวจที่เกี่ยวข้องสนับสนุนข้อร้องเรียน"),
        "seller": ("The relevant check favors the seller.", "ผลการตรวจที่เกี่ยวข้องเอนเอียงไปทางร้านค้า"),
        "none": ("The relevant check was inconclusive.", "ผลการตรวจที่เกี่ยวข้องยังสรุปไม่ได้"),
    }
    en, th = messages[leaning]
    if fraud:
        en += " An integrity concern requires human review."
        th += " พบข้อกังวลเกี่ยวกับความน่าเชื่อถือของวิดีโอ จึงต้องให้คนตรวจสอบ"
    elif integrity_incomplete:
        en += " The seal or video continuity could not be assessed."
        th += " ไม่สามารถประเมินซีลพัสดุหรือความต่อเนื่องของวิดีโอได้"
    if counterfeit:
        en += " Counterfeit claims require human review."
        th += " ข้อร้องเรียนเรื่องสินค้าปลอมต้องให้คนตรวจสอบ"
    if leaning != "none" and confidence < CLEAR_CONFIDENCE:
        en += " Confidence is below 90%."
        th += " ความมั่นใจต่ำกว่า 90%"
    return Reason(en=en, th=th)


@validate_call(config=ConfigDict(strict=True))
def decide_verdict(
    *,
    case_id: str,
    claim_type: ClaimType,
    claim_confidence: Confidence,
    comparisons: dict[str, Check],
    integrity: IntegrityReport,
    quality: EvidenceQuality = EvidenceQuality(),
) -> Verdict:
    """Build a review recommendation from the matcher and integrity outputs.

    Comparisons come from the grounding step, which snaps findings to the
    frames actually sent to the model. Evidence assets are assembled later.
    """
    checks = {
        name: check
        if check.status != "flag" or check.findings
        else Check(
            status="unclear",
            confidence=0,
            findings=[],
            note_en="A reported mismatch lacked grounded video evidence.",
            note_th="ความแตกต่างที่รายงานไม่มีหลักฐานจากเฟรมวิดีโอรองรับ",
        )
        for name, check in comparisons.items()
    }
    checks.update(
        (name, Check.model_validate(check.model_dump())) for name, check in integrity.checks.items()
    )
    variant = checks.get("variant")
    if quality.warm_light and variant is not None:
        checks["variant"] = variant.model_copy(
            update={"confidence": min(variant.confidence, WARM_VARIANT_CAP)}
        )
    flags = [Flag.model_validate(flag.model_dump()) for flag in integrity.flags]
    seal = integrity.checks.get("seal")
    continuity = integrity.checks.get("continuity")
    fraud = bool(flags) or any(check.status == "flag" for check in integrity.checks.values())
    integrity_incomplete = (
        seal is None
        or seal.status == "unclear"
        or continuity is None
        or continuity.status == "unclear"
    )

    deciding, deciding_confidence = _deciding_check(claim_type, checks)
    leaning = LEANING[deciding.status]
    confidence = min(claim_confidence, seal.confidence if seal else 0, deciding_confidence)
    if quality.blurred or quality.dark or quality.item_not_fully_shown:
        confidence = min(confidence, LIMITED_EVIDENCE_CAP)

    counterfeit = claim_type == "counterfeit"
    clear = (
        not fraud
        and not integrity_incomplete
        and not counterfeit
        and leaning != "none"
        and confidence >= CLEAR_CONFIDENCE
    )
    return Verdict(
        case_id=case_id,
        verdict=("buyer_right" if leaning == "buyer" else "seller_right")
        if clear
        else "needs_human",
        display="clear" if clear else "unsure",
        leaning=leaning,
        confidence=confidence,
        flags=flags,
        checks=checks,
        evidence=[],
        reason=_reason(
            leaning,
            confidence,
            fraud=fraud,
            integrity_incomplete=integrity_incomplete,
            counterfeit=counterfeit,
        ),
        steps=[],
    )
