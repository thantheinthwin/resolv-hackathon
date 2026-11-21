"use client";

import { useSyncExternalStore } from "react";
import { api, ApiError } from "./client";
import type { Claim, CreatedCase, Order, Report } from "./models";

export type OrderSummary = {
  id: string;
  title: string;
  color: string;
  size: string;
  quantity: number;
  photo?: string;
};

export function summarizeOrder(order: Order): OrderSummary {
  return {
    id: order.id,
    title: order.listing.title,
    color: order.variant.color,
    size: order.variant.size,
    quantity: order.quantity,
    photo: order.listing.photos[0],
  };
}

export type Draft = {
  order: OrderSummary;
  claim?: Claim;
  description: string;
  step: "complaint" | "video";
  caseId?: string;
};

type ReceiptSummary = { order: OrderSummary; claim: Claim };
type BuyerSession = { draft?: Draft; receipts: Record<string, ReceiptSummary> };

const storageKey = "unboxing-judge.buyer.v1";
const sessionChanged = "buyer-session-changed";
const initial: BuyerSession = { receipts: {} };
let memory = initial;
let cachedValue: string | null | undefined;
let creating: Promise<string> | undefined;

function readSession(): BuyerSession {
  try {
    const value = sessionStorage.getItem(storageKey);
    if (value !== cachedValue) {
      cachedValue = value;
      memory = value ? JSON.parse(value) : initial;
    }
  } catch {
    // Keep the in-memory draft when the browser limits storage.
  }
  return memory;
}

export function changeBuyerSession(change: (previous: BuyerSession) => BuyerSession) {
  memory = change(readSession());
  try {
    const value = JSON.stringify(memory);
    sessionStorage.setItem(storageKey, value);
    cachedValue = value;
  } catch {
    // The current page can still complete the report.
  }
  window.dispatchEvent(new Event(sessionChanged));
}

function subscribe(listener: () => void) {
  window.addEventListener(sessionChanged, listener);
  return () => window.removeEventListener(sessionChanged, listener);
}

export function useBuyerSession() {
  return useSyncExternalStore(subscribe, readSession, () => initial);
}

export function ensureDraftCase(): Promise<string> {
  if (creating) return creating;
  const draft = readSession().draft;
  if (!draft?.claim) return Promise.reject(new Error("Choose a claim before adding a video."));
  if (draft.caseId) return Promise.resolve(draft.caseId);

  creating = api<CreatedCase>("cases", {
    order_id: draft.order.id,
    claim_type: draft.claim,
    description: draft.description,
  })
    .then(({ id }) => {
      changeBuyerSession((session) => ({ ...session, draft: { ...draft, caseId: id } }));
      return id;
    })
    .finally(() => {
      creating = undefined;
    });
  return creating;
}

export function rememberReceipt(id: string) {
  changeBuyerSession((session) => {
    const draft = session.draft;
    if (draft?.caseId !== id || !draft.claim) return session;
    return {
      receipts: { ...session.receipts, [id]: { order: draft.order, claim: draft.claim } },
    };
  });
}

export async function deleteReport(id?: string, isDraft = false) {
  if (!id && creating) id = await creating;
  if (id) {
    const endpoint = "cases/" + encodeURIComponent(id);
    try {
      if (isDraft) {
        const report = await api<Report>(endpoint);
        if (videoReceived(report.status)) {
          rememberReceipt(id);
          return { deleted: false, id };
        }
      }
      await api(endpoint, undefined, "DELETE");
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) throw error;
    }
  }
  changeBuyerSession((session) => {
    const receipts = { ...session.receipts };
    if (id) delete receipts[id];
    return {
      receipts,
      draft: session.draft?.caseId === id ? undefined : session.draft,
    };
  });
  return { deleted: true, id };
}

export function videoReceived(status: Report["status"]) {
  return (
    status === "checking" || status === "with_shop" || status === "replied" || status === "failed"
  );
}
