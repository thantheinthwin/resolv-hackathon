from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.app.contracts import Case, CaseStatus, ClaimType, Display


class CreateCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str
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


class ShopSummary(BaseModel):
    id: str
    product: str
    order_id: str
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


class VideoForm(BaseModel):
    video: bytes


class ListingForm(BaseModel):
    title: str
    description: str = Field(max_length=1500)
    box_contents: list[str]
    price: float = Field(ge=0)
    colors: list[str]
    sizes: list[str]
    photos: list[bytes] = Field(min_length=1, max_length=3)
