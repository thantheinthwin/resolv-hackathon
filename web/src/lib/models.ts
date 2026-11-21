import type { components } from "../api/types";
type Schema = components["schemas"];
export type Listing = Schema["Listing"];
export type Order = Schema["OrderWithListing"];
export type Report = Schema["BuyerCase"];
export type Case = Schema["Case"];
export type CreatedCase = Schema["CreatedCase"];
export const claims = {
  wrong_item: "Wrong item",
  missing: "Something missing",
  damaged: "Damaged",
  counterfeit: "Looks fake",
};
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
