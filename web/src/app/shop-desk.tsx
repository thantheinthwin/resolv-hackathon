"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { api } from "../lib/client";
import { claims, type Case, type InboxCase, type Listing } from "../lib/models";
import { CheckProgress } from "./check-progress";
import { DeskShell } from "./desk-shell";
import { Products } from "./products";
import { Review } from "./review";

const queues = [
  ["review", "Needs review"],
  ["checking", "Checking"],
  ["resolved", "Resolved"],
] as const;
type Queue = (typeof queues)[number][0];

function queueFor(status: InboxCase["status"]): Queue | undefined {
  switch (status) {
    case "ready":
    case "failed":
      return "review";
    case "checking":
      return "checking";
    case "decided":
      return "resolved";
  }
}

const emptyQueue: Record<Queue, string> = {
  review: "New reports will appear here once their video checks finish.",
  checking: "No videos are being checked right now.",
  resolved: "Cases will appear here after you save a decision.",
};

function compareCases(a: InboxCase, b: InboxCase) {
  return (
    Number(b.status === "ready") - Number(a.status === "ready") ||
    (a.status === "ready" && b.status === "ready"
      ? Number(b.display === "unsure") - Number(a.display === "unsure")
      : 0) ||
    b.created_at.localeCompare(a.created_at)
  );
}

export function ShopDesk({ onHome }: { onHome: () => void }) {
  const [view, setView] = useState<"inbox" | "case" | "products">("inbox");
  const [cases, setCases] = useState<InboxCase[]>();
  const [listings, setListings] = useState<Listing[]>();
  const [queue, setQueue] = useState<Queue>("review");
  const [current, setCurrent] = useState<{ item: Case; summary: InboxCase; saved: boolean }>();
  const [revision, refresh] = useState(0);
  const [opening, setOpening] = useState("");
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const productsView = view === "products";

  useEffect(() => {
    let active = true;
    let loading = false;
    async function load() {
      if (loading) return;
      loading = true;
      try {
        if (productsView) {
          const result = await api<Listing[]>("listings");
          if (active) setListings(result);
        } else {
          const result = await api<InboxCase[]>("shop/cases");
          if (active) setCases(result.sort(compareCases));
        }
        if (active) setLoadError("");
      } catch {
        if (active)
          setLoadError(productsView ? "Couldn’t load products." : "Couldn’t load the inbox.");
      } finally {
        loading = false;
      }
    }
    void load();
    const timer = productsView ? undefined : setInterval(load, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [productsView, revision]);

  function navigate(target: "inbox" | "products") {
    setError("");
    setLoadError("");
    setView(target);
  }

  async function openCase(summary: InboxCase) {
    if (opening) return;
    setOpening(summary.id);
    setError("");
    try {
      const item = await api<Case>("shop/cases/" + encodeURIComponent(summary.id));
      setCurrent({ item, summary, saved: false });
      setView("case");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Couldn’t open this case. Try again.");
    } finally {
      setOpening("");
    }
  }

  function recordDecision(item: Case) {
    setCurrent((existing) =>
      existing?.item.id === item.id ? { ...existing, item, saved: true } : existing,
    );
    setCases((items) =>
      items?.map((entry) => (entry.id === item.id ? { ...entry, status: item.status } : entry)),
    );
    refresh((value) => value + 1);
  }

  const visibleCases = cases?.filter((item) => queueFor(item.status) === queue);
  const nextCase = cases?.find((item) => item.id !== current?.item.id && item.status === "ready");
  const navigation = (
    <>
      <Button
        variant="ghost"
        aria-current={!productsView ? "page" : undefined}
        disabled={!!opening}
        onClick={() => navigate("inbox")}
      >
        Inbox
      </Button>
      <Button
        variant="ghost"
        aria-current={productsView ? "page" : undefined}
        disabled={!!opening}
        onClick={() => navigate("products")}
      >
        Products
      </Button>
    </>
  );

  return (
    <DeskShell
      role="Shop owner"
      view={view === "case" ? (current?.item.id ?? view) : view}
      navigation={navigation}
      onHome={onHome}
    >
      {(error || loadError) && (
        <Alert variant="destructive">
          <AlertDescription>
            {error || loadError}
            {!error && (
              <Button variant="ghost" onClick={() => refresh((value) => value + 1)}>
                Try again
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}
      {view === "products" && (
        <Products items={listings ?? []} refresh={() => refresh((value) => value + 1)} />
      )}
      {view === "case" && current && (
        <>
          <Button variant="ghost" className="back-link" onClick={() => navigate("inbox")}>
            <ArrowLeft aria-hidden /> Back to inbox
          </Button>
          <Review
            key={current.item.id}
            item={current.item}
            title={current.summary.product}
            saved={current.saved}
            onDecision={recordDecision}
            reload={async () => {
              const item = await api<Case>("shop/cases/" + encodeURIComponent(current.item.id));
              if (item.decision) recordDecision(item);
            }}
            next={nextCase && !opening ? () => openCase(nextCase) : undefined}
            openingNext={!!opening}
          />
        </>
      )}
      {view === "inbox" && (
        <>
          <h1 tabIndex={-1}>
            Inbox<span className="heading-period">.</span>
          </h1>
          <div className="queue-picker" role="group" aria-label="Inbox queue">
            {queues.map(([key, label]) => (
              <Button
                key={key}
                variant="ghost"
                aria-pressed={queue === key}
                onClick={() => setQueue(key)}
              >
                {label}
              </Button>
            ))}
          </div>
          {!cases && !loadError && (
            <p className="loading-row" role="status">
              Loading the inbox…
            </p>
          )}
          {visibleCases?.length === 0 && <p className="empty-state">{emptyQueue[queue]}</p>}
          <ul
            className="inbox-list"
            aria-label={queues.find(([key]) => key === queue)?.[1] + " cases"}
          >
            {visibleCases?.map((item) => (
              <li className="inbox-row" key={item.id} data-case={item.id}>
                <div>
                  <h2>{item.product}</h2>
                  <p>{claims[item.claim_type]}</p>
                  <small>
                    Order {item.order_id} · {new Date(item.created_at).toLocaleDateString()}
                  </small>
                </div>
                <div className="queue-status">
                  {item.status === "checking" ? (
                    <CheckProgress id={item.id} onDone={() => refresh((value) => value + 1)} />
                  ) : (
                    <Badge
                      variant="secondary"
                      className={item.status === "failed" ? "failed-badge" : undefined}
                    >
                      {item.status === "decided"
                        ? "Resolved"
                        : item.status === "failed"
                          ? "Video check failed"
                          : item.display === "unsure"
                            ? "Needs human review"
                            : "Ready for review"}
                    </Badge>
                  )}
                </div>
                {(item.status === "ready" || item.status === "decided") && (
                  <Button
                    variant={item.status === "decided" ? "outline" : "default"}
                    disabled={!!opening}
                    onClick={() => openCase(item)}
                  >
                    {opening === item.id
                      ? "Opening…"
                      : item.status === "decided"
                        ? "View decision"
                        : "Review case"}
                    <ArrowRight aria-hidden />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </DeskShell>
  );
}
