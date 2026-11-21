from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from judge.submission import PhotoFinding
from api.app.contracts import Case, CaseReference, CaseStatus, ClaimType, Display


class CreateCase(CaseReference):
    claim_type: ClaimType
    description: str = ""


class CreatedCase(BaseModel):
    id: str
    status: Literal["awaiting_video"] = "awaiting_video"


class BuyerCase(BaseModel):
    id: str
    status: Literal["sent", "checking", "with_shop", "replied", "failed"]
    note_for_buyer: str | None


def buyer_view(case: Case) -> BuyerCase:
    status: dict[CaseStatus, Literal["sent", "checking", "with_shop", "replied", "failed"]] = {
        "awaiting_video": "sent",
        "checking": "checking",
        "ready": "with_shop",
        "decided": "replied",
        "failed": "failed",
    }
    return BuyerCase(
        id=case.id,
        status=status[case.status],
        note_for_buyer=case.decision.note_for_buyer if case.decision else None,
    )


class ShopSummary(CaseReference):
    id: str
    product: str
    claim_type: ClaimType
    status: CaseStatus
    verdict: Literal["buyer_right", "seller_right", "needs_human"] | None
    display: Display | None
    confidence: float | None = Field(ge=0, le=1)
    created_at: datetime


class UploadLink(BaseModel):
    token: str
    url: str


class UploadResult(BaseModel):
    id: str
    status: Literal["checking"]
    warnings: list[str]


class ErrorDetail(BaseModel):
    detail: str


class ShopCase(Case):
    photo_findings: list[PhotoFinding] = Field(default_factory=list)


class VideoForm(BaseModel):
    video: bytes
    photos: list[bytes] = Field(default_factory=list, max_length=3)


class ListingForm(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    description: str = Field(default="", max_length=1500)
    box_contents: list[str] = Field(default_factory=list)
    price: float = Field(ge=0, allow_inf_nan=False)
    colors: list[str] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)
    photos: list[bytes] = Field(min_length=1, max_length=3)
