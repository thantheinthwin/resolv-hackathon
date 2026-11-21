import type { components } from "../api/types";
type Schema = components["schemas"];
export type Listing = Schema["Listing"];
export type Order = Schema["OrderWithListing"];
export type Report = Schema["BuyerCase"];
export type Case = Schema["Case"];
export type CreatedCase = Schema["CreatedCase"];
export type UploadLink = Schema["UploadLink"];
export type UploadResult = Schema["UploadResult"];
export type Claim = Case["claim_type"];
export const claims = {
  wrong_item: "Wrong item, color, or size",
  missing: "Missing items or parts",
  damaged: "Damaged item",
  counterfeit: "Suspected counterfeit",
} satisfies Record<Claim, string>;
export const reasons = [
  "wrong colour seen",
  "item is complete",
  "damage was there before",
  "video unclear",
  "other",
];
export const labels: Record<string, string> = {
  sent: "Sent",
  checking: "Being checked",
  with_shop: "With the shop",
  replied: "Shop replied",
  awaiting_video: "Awaiting video",
  ready: "Ready",
  decided: "Decided",
  failed: "Failed",
};

export type InboxCase = components["schemas"]["ShopSummary"];
