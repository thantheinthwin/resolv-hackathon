"""Shared data exchanged by the case API, judge and web client."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
ClaimType = Literal["wrong_item", "missing", "damaged", "counterfeit"]
CaseStatus = Literal["awaiting_video", "checking", "ready", "decided", "failed"]
Display = Literal["clear", "unsure"]
CheckStatus = Literal["pass", "flag", "unclear"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Listing(Contract):
    id: str
    title: str
    description: str = Field(max_length=1500)
    box_contents: list[str]
    price: float = Field(ge=0, allow_inf_nan=False)
    colors: list[str]
    sizes: list[str]
    photos: list[str] = Field(min_length=1, max_length=3)


class Variant(Contract):
    color: str
    size: str


class Order(Contract):
    id: str
    listing_id: str
    variant: Variant
    quantity: int = Field(gt=0)
    delivered_at: datetime
    buyer_name: str


class Flag(Contract):
    type: str
    t: Seconds
    note: str


class Finding(Contract):
    t: Seconds
    note_en: str
    note_th: str


class Check(Contract):
    status: CheckStatus
    confidence: Confidence
    findings: list[Finding]
    note_en: str | None = None
    note_th: str | None = None


class Evidence(Contract):
    t: Seconds
    check: str
    result: CheckStatus
    frame: str
    listing_photo: str


class Reason(Contract):
    en: str
    th: str


class Step(Contract):
    name: str
    kind: Literal["code", "model"]
    seconds: Seconds
    output: str


class Verdict(Contract):
    case_id: str
    verdict: Literal["buyer_right", "seller_right", "needs_human"]
    display: Display
    leaning: Literal["buyer", "seller", "none"]
    confidence: Confidence
    flags: list[Flag]
    checks: dict[str, Check]
    evidence: list[Evidence]
    reason: Reason
    steps: list[Step]

    @model_validator(mode="after")
    def check_outcome(self) -> Self:
        if self.display == "unsure":
            if self.verdict != "needs_human":
                raise ValueError("An unsure verdict requires human review")
        elif (
            self.confidence < 0.9
            or self.flags
            or self.leaning == "none"
            or self.verdict != f"{self.leaning}_right"
        ):
            raise ValueError(
                "A clear verdict requires a matching leaning, confidence ≥ 0.90 and no flags"
            )
        return self


class Decision(Contract):
    choice: Literal["agree", "disagree", "side_buyer", "side_seller"]
    reason: (
        Literal[
            "wrong colour seen",
            "item is complete",
            "damage was there before",
            "video unclear",
            "other",
        ]
        | None
    ) = None
    note_for_buyer: str | None = None

    @model_validator(mode="after")
    def require_disagreement_reason(self) -> Self:
        if self.choice == "disagree" and self.reason is None:
            raise ValueError("Disagree requires a reason")
        return self

    def validate_for(self, display: Display) -> None:
        if (self.choice in ("agree", "disagree")) != (display == "clear"):
            raise ValueError(f"Decision {self.choice} is unavailable for a {display} verdict")


class ProgressEvent(Contract):
    event: Literal["started", "finished", "done"]
    step: str | None = None


class Case(Contract):
    id: str
    order_id: str
    claim_type: ClaimType
    description: str
    status: CaseStatus
    created_at: datetime
    video_url: str | None = None
    verdict: Verdict | None = None
    decision: Decision | None = None
    progress: list[ProgressEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_review(self) -> Self:
        if (self.status in ("ready", "decided")) != (self.verdict is not None):
            raise ValueError("A case must have a verdict exactly when ready or decided")
        if (self.status == "decided") != (self.decision is not None):
            raise ValueError("A case must have a decision exactly when decided")
        if self.verdict is not None:
            if self.verdict.case_id != self.id:
                raise ValueError("Verdict belongs to a different case")
            if self.claim_type == "counterfeit" and self.verdict.display == "clear":
                raise ValueError("Counterfeit claims require human review")
            if self.decision is not None:
                self.decision.validate_for(self.verdict.display)
        return self
