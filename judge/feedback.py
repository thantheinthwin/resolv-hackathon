"""Turn a judge recommendation into one complaint result with a bilingual reason."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.app.contracts import ClaimType, Reason, Verdict
from judge.integrity import OPENING_OBSERVATION_UNAVAILABLE
from judge.matching import COMPARISON_UNAVAILABLE
from judge.pipeline import COMPLAINT_REVIEW_PENDING
from judge.reasons import CHECK_LABELS
from judge.verdict import deciding_check_name

FeedbackResult = Literal["complaint_supported", "needs_human_check", "needs_more_evidence"]
VideoStatus = Literal["absent", "no_usable_frames", "analyzed"]

INTEGRITY_REASONS = {
    "cut": ("A possible cut was detected", "พบสัญญาณที่อาจเป็นการตัดต่อ"),
    "seal_opened": ("The parcel seal appears to have been opened", "ซีลพัสดุดูเหมือนถูกเปิดแล้ว"),
    "label_mismatch": ("The parcel label may not match the order", "ฉลากพัสดุอาจไม่ตรงกับคำสั่งซื้อ"),
}
PURCHASE_REQUEST = (
    "Please confirm which item and variant you ordered.",
    "โปรดยืนยันสินค้าที่สั่งและรุ่นหรือตัวเลือกสินค้าที่เลือก",
)
EVIDENCE_REQUESTS = {
    "listing": (
        "Show the received product and its model marking, if visible.",
        "โปรดแสดงสินค้าที่ได้รับและเครื่องหมายระบุรุ่น หากมองเห็นได้",
    ),
    "variant": (
        "Show the received item's colour or size marking in clear light.",
        "โปรดแสดงสีหรือเครื่องหมายระบุขนาดของสินค้าที่ได้รับในที่สว่าง",
    ),
    "count": (
        "Show all the delivered items together so they can be counted.",
        "โปรดแสดงสินค้าที่ได้รับทั้งหมดพร้อมกันเพื่อให้ตรวจนับได้",
    ),
    "damage": (
        "Provide a clear close-up of the reported damage with the product visible.",
        "โปรดส่งภาพระยะใกล้ที่เห็นความเสียหายและตัวสินค้าอย่างชัดเจน",
    ),
}


class ComplaintFeedback(BaseModel):
    """One recommendation for shop review and an explanation in both languages."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    result: FeedbackResult
    reason: Reason


def _feedback(result: FeedbackResult, en: str, th: str) -> ComplaintFeedback:
    return ComplaintFeedback(result=result, reason=Reason(en=en, th=th))


def _priority_review_reason(
    verdict: Verdict, claim_type: ClaimType, complaint_pending: bool
) -> tuple[str, str] | None:
    if verdict.flags:
        flag = verdict.flags[0]
        en, th = INTEGRITY_REASONS.get(
            flag.type, ("An integrity concern was detected", "พบข้อกังวลด้านความน่าเชื่อถือ")
        )
        return f"{en} at {flag.t} s.", f"{th}ที่เวลา {flag.t} วินาที"
    if any(
        verdict.checks[name].status == "flag"
        for name in ("seal", "continuity", "label")
        if name in verdict.checks
    ):
        return (
            "The shop needs to verify an integrity concern with the video.",
            "ร้านค้าต้องตรวจสอบข้อกังวลด้านความน่าเชื่อถือของวิดีโอ",
        )
    if claim_type == "counterfeit":
        return (
            "The shop needs to verify the product's authenticity.",
            "ร้านค้าต้องตรวจสอบว่าสินค้าเป็นของแท้หรือไม่",
        )
    if complaint_pending or any(
        step.name == "complaint" and step.output == COMPLAINT_REVIEW_PENDING
        for step in verdict.steps
    ):
        return (
            "The written complaint awaits privacy review.",
            "ข้อร้องเรียนที่เขียนไว้ยังรอการตรวจสอบความเป็นส่วนตัว",
        )
    return None


def build_complaint_feedback(
    verdict: Verdict,
    claim_type: ClaimType,
    *,
    video_status: VideoStatus,
    complaint_pending: bool = False,
    purchase_verified: bool = True,
    comparison_pending: bool = False,
) -> ComplaintFeedback:
    """Route cases with missing evidence separately from cases needing judgment."""
    priority_reason = _priority_review_reason(verdict, claim_type, complaint_pending)
    if priority_reason is not None:
        en, th = priority_reason
        if not purchase_verified:
            en = f"{en} {PURCHASE_REQUEST[0]}"
            th = f"{th} {PURCHASE_REQUEST[1]}"
        return _feedback("needs_human_check", en, th)
    if not purchase_verified:
        return _feedback("needs_more_evidence", *PURCHASE_REQUEST)
    if video_status != "analyzed":
        return _feedback(
            "needs_more_evidence",
            "Add a usable video showing the parcel opening and the reported issue.",
            "โปรดเพิ่มวิดีโอที่เห็นการเปิดพัสดุและปัญหาที่แจ้งอย่างชัดเจน",
        )
    if comparison_pending:
        return _feedback(
            "needs_human_check",
            "The shop needs to review the video and listing before the product comparison.",
            "ร้านค้าต้องตรวจสอบวิดีโอและรายละเอียดสินค้าก่อนเปรียบเทียบสินค้า",
        )
    seal = verdict.checks.get("seal")
    if seal is not None and seal.note_en == OPENING_OBSERVATION_UNAVAILABLE:
        return _feedback(
            "needs_human_check",
            "The shop needs to inspect the parcel opening in the supplied footage.",
            "ร้านค้าต้องตรวจสอบช่วงเปิดพัสดุจากวิดีโอที่ส่งมา",
        )
    if seal is None or seal.status == "unclear":
        return _feedback(
            "needs_more_evidence",
            "Show the parcel seal clearly before opening the parcel.",
            "โปรดแสดงซีลพัสดุให้เห็นชัดเจนก่อนเปิดพัสดุ",
        )
    continuity = verdict.checks.get("continuity")
    if continuity is None or continuity.status == "unclear":
        return _feedback(
            "needs_more_evidence",
            "Provide a clear, continuous clip from parcel opening to the reported issue.",
            "โปรดส่งวิดีโอที่ชัดเจนและต่อเนื่องตั้งแต่เปิดพัสดุจนเห็นปัญหาที่แจ้ง",
        )

    check_name = deciding_check_name(claim_type, verdict.checks)
    check = verdict.checks.get(check_name)
    if (
        check is not None
        and check.status == "unclear"
        and (check.note_en, check.note_th) == COMPARISON_UNAVAILABLE
    ):
        return _feedback(
            "needs_human_check",
            "The product comparison could not be completed. The shop needs to review the case.",
            "ไม่สามารถเปรียบเทียบสินค้าได้สำเร็จ ร้านค้าต้องตรวจสอบกรณีนี้",
        )
    en_label, th_label = CHECK_LABELS[check_name]
    if verdict.verdict == "seller_right":
        return _feedback(
            "needs_human_check",
            f"The {en_label} check favors the shop. Review it alongside the buyer's complaint.",
            f"ผลการ{th_label}สนับสนุนข้อมูลของร้านค้า โปรดพิจารณาร่วมกับข้อร้องเรียนของผู้ซื้อ",
        )
    if verdict.verdict == "buyer_right" and check is not None and check.status == "flag":
        times = {finding.t for finding in check.findings}
        for evidence in verdict.evidence:
            if evidence.check == check_name and evidence.result == "flag" and evidence.t in times:
                return _feedback(
                    "complaint_supported",
                    f"The {en_label} check supports the complaint at {evidence.t} s.",
                    f"ผลการ{th_label}สนับสนุนข้อร้องเรียนที่เวลา {evidence.t} วินาที",
                )
    if check is None or check.status == "unclear" or verdict.verdict == "buyer_right":
        return _feedback("needs_more_evidence", *EVIDENCE_REQUESTS[check_name])
    return _feedback(
        "needs_human_check",
        f"The {en_label} check was inconclusive. The shop needs to review it.",
        f"ผลการ{th_label}ยังสรุปไม่ได้ ร้านค้าต้องตรวจสอบ",
    )
