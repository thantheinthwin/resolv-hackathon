"use client";

import { ArrowLeft, ArrowRight, ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { api } from "../lib/client";
import { claims, type ShopCase, type InboxCase, type Listing, type Order } from "../lib/models";
import { CheckProgress } from "./check-progress";
import { DeskShell } from "./desk-shell";
import { ProductWizard } from "./product-wizard";
import { ListingOverview, ProductClaimLink, Products } from "./products";
import { Review } from "./review";

const queues = [
  ["review", "Needs review"],
  ["checking", "Checking"],
  ["resolved", "Resolved"],
] as const;
type Queue = (typeof queues)[number][0];
type ShopView = "inbox" | "case" | "products" | "product" | "add-product";

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

function newestFirst(a: InboxCase, b: InboxCase) {
  return b.created_at.localeCompare(a.created_at);
}

function compareCases(a: InboxCase, b: InboxCase) {
  return (
    Number(b.status === "ready") - Number(a.status === "ready") ||
    (a.status === "ready" && b.status === "ready"
      ? Number(b.display === "unsure") - Number(a.display === "unsure")
      : 0) ||
    newestFirst(a, b)
  );
}

function caseStatus(item: InboxCase) {
  if (item.status === "checking") return "Checking";
  if (item.status === "failed") return "Video check failed";
  if (item.status === "decided") return "Resolved";
  return item.display === "unsure" ? "Needs human review" : "Ready for review";
}

function caseCanOpen(item: InboxCase) {
  return item.status === "ready" || item.status === "decided";
}

function CaseRows({
  items,
  label,
  opening,
  product,
  onOpen,
  onChecked,
}: {
  items: InboxCase[];
  label: string;
  opening: string;
  product?: boolean;
  onOpen: (item: InboxCase) => void;
  onChecked: () => void;
}) {
  return (
    <ul className="inbox-list" aria-label={label}>
      {items.map((item) => (
        <li className="inbox-row" key={item.id} data-case={item.id}>
          <div>
            <h2>{product ? claims[item.claim_type] : item.product}</h2>
            {!product && <p>{claims[item.claim_type]}</p>}
            <small>
              {item.order_id !== undefined
                ? "Order " + item.order_id
                : "Product reference " + item.listing_id.slice(0, 8)}{" "}
              ·{" "}
              <time dateTime={item.created_at}>
                {new Date(item.created_at).toLocaleDateString()}
              </time>
            </small>
          </div>
          <div className="queue-status">
            {item.status === "checking" ? (
              product ? (
                <Badge variant="secondary">Checking</Badge>
              ) : (
                <CheckProgress id={item.id} onDone={onChecked} />
              )
            ) : (
              <Badge
                variant="secondary"
                className={item.status === "failed" ? "failed-badge" : undefined}
              >
                {caseStatus(item)}
              </Badge>
            )}
          </div>
          {caseCanOpen(item) && (
            <Button
              variant={item.status === "decided" ? "outline" : "default"}
              disabled={!!opening}
              onClick={() => onOpen(item)}
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
  );
}

function CaseSidebar({
  items,
  currentId,
  opening,
  product,
  onOpen,
}: {
  items: InboxCase[];
  currentId: string;
  opening: string;
  product: boolean;
  onOpen: (item: InboxCase) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const title = product ? "Cases for this product" : "Cases in the inbox";

  return (
    <aside className="case-sidebar panel" aria-label="Case list" data-expanded={expanded}>
      <h2 className="case-sidebar-heading">{title}</h2>
      <Button
        variant="ghost"
        className="case-sidebar-toggle"
        aria-expanded={expanded}
        aria-controls="review-case-list"
        onClick={() => setExpanded((value) => !value)}
      >
        {title} <ChevronDown aria-hidden />
      </Button>
      <ul className="review-case-list" id="review-case-list">
        {items.map((item) => {
          const active = item.id === currentId;
          const details = (
            <>
              {!product && <strong>{item.product}</strong>}
              <span>{claims[item.claim_type]}</span>
              <small>Report {item.id.slice(0, 8)}</small>
              <Badge
                variant="secondary"
                className={item.status === "failed" ? "failed-badge" : undefined}
              >
                {caseStatus(item)}
              </Badge>
            </>
          );
          return (
            <li key={item.id} data-review-case={item.id}>
              {caseCanOpen(item) ? (
                <button
                  type="button"
                  className="case-sidebar-row"
                  aria-current={active ? "true" : undefined}
                  disabled={!!opening}
                  onClick={() => {
                    if (active) return;
                    setExpanded(false);
                    onOpen(item);
                  }}
                >
                  {details}
                </button>
              ) : (
                <div className="case-sidebar-row">{details}</div>
              )}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

export function ShopDesk({ sampleMode }: { sampleMode: boolean }) {
  const [view, setView] = useState<ShopView>("inbox");
  const [cases, setCases] = useState<InboxCase[]>();
  const [listings, setListings] = useState<Listing[]>();
  const [orderListings, setOrderListings] = useState<Map<string, string>>();
  const [product, setProduct] = useState<Listing>();
  const [dirtyProduct, setDirtyProduct] = useState(false);
  const [savingProduct, setSavingProduct] = useState(false);
  const [queue, setQueue] = useState<Queue>("review");
  const [current, setCurrent] = useState<{
    item: ShopCase;
    summary: InboxCase;
    saved: boolean;
    product?: Listing;
  }>();
  const [reviewOrder, setReviewOrder] = useState<string[]>();
  const [revision, refresh] = useState(0);
  const [opening, setOpening] = useState("");
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [orderError, setOrderError] = useState("");
  const productsNav =
    view === "products" ||
    view === "product" ||
    view === "add-product" ||
    (view === "case" && !!current?.product);
  const loadListings = view === "products";
  const loadCases = view === "inbox" || view === "product" || view === "case";
  const loadOrders = view === "product" || (view === "case" && !!current?.product);

  const reload = () => refresh((value) => value + 1);

  useEffect(() => {
    if (!loadListings && !loadCases) return;
    let active = true;
    let loading = false;
    async function load() {
      if (loading) return;
      loading = true;
      try {
        if (loadListings) {
          const result = await api<Listing[]>("listings");
          if (active) setListings(result);
        } else {
          const result = await api<InboxCase[]>("shop/cases");
          if (active) {
            const sorted = result.sort(compareCases);
            setCases(sorted);
            setReviewOrder((ids) => {
              if (!ids) return ids;
              const existing = new Set(ids);
              const added = sorted
                .filter((item) => queueFor(item.status) && !existing.has(item.id))
                .map(({ id }) => id);
              return added.length ? [...ids, ...added] : ids;
            });
          }
        }
        if (active) setLoadError("");
      } catch {
        if (active)
          setLoadError(loadListings ? "Couldn’t load products." : "Couldn’t load claims.");
      } finally {
        loading = false;
      }
    }
    void load();
    const timer = loadCases ? setInterval(load, 2000) : undefined;
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [loadListings, loadCases, revision]);

  useEffect(() => {
    if (!loadOrders) return;
    let active = true;
    // The demo order feed supplies the stable order-to-listing relation.
    void api<Order[]>("orders").then(
      (orders) => {
        if (!active) return;
        setOrderListings(new Map(orders.map(({ id, listing_id }) => [id, listing_id])));
        setOrderError("");
      },
      () => {
        if (active) setOrderError("Couldn’t load the orders for this listing.");
      },
    );
    return () => {
      active = false;
    };
  }, [loadOrders, revision]);

  useEffect(() => {
    if (view !== "add-product" || (!dirtyProduct && !savingProduct)) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [view, dirtyProduct, savingProduct]);

  function canLeave() {
    return (
      view !== "add-product" ||
      (!savingProduct && (!dirtyProduct || window.confirm("Discard unsaved product changes?")))
    );
  }

  function navigate(target: ShopView) {
    if (!canLeave()) return;
    if (view === "add-product") setDirtyProduct(false);
    setError("");
    setLoadError("");
    if (target === "product") setOrderError("");
    setReviewOrder(undefined);
    setView(target);
  }

  function openProduct(listing: Listing) {
    setProduct(listing);
    navigate("product");
  }

  function saveProduct(listing: Listing) {
    setListings((items) => [listing, ...(items ?? [])]);
    setProduct(listing);
    setDirtyProduct(false);
    setOrderError("");
    setView("product");
  }

  async function openCase(summary: InboxCase, listing?: Listing) {
    if (opening || (view === "case" && summary.id === current?.item.id)) return;
    setOpening(summary.id);
    setError("");
    try {
      const item = await api<ShopCase>("shop/cases/" + encodeURIComponent(summary.id));
      if (view !== "case" && !listing)
        setReviewOrder(cases?.filter((item) => queueFor(item.status)).map(({ id }) => id));
      setCurrent({ item, summary, saved: false, product: listing });
      setView("case");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Couldn’t open this case. Try again.");
    } finally {
      setOpening("");
    }
  }

  function recordDecision(item: ShopCase) {
    setCurrent((existing) =>
      existing?.item.id === item.id ? { ...existing, item, saved: true } : existing,
    );
    setCases((items) =>
      items?.map((entry) => (entry.id === item.id ? { ...entry, status: item.status } : entry)),
    );
    reload();
  }

  const visibleCases = cases?.filter((item) => queueFor(item.status) === queue);
  const selectedProduct = view === "case" ? current?.product : product;
  const productCases =
    cases && orderListings && selectedProduct
      ? cases
          .filter(
            (item) =>
              item.status !== "awaiting_video" &&
              (item.listing_id ?? (item.order_id && orderListings.get(item.order_id))) ===
                selectedProduct.id,
          )
          .sort(newestFirst)
      : undefined;
  const submittedCases = (current?.product ? productCases : cases) ?? [];
  const queuePositions = new Map(reviewOrder?.map((id, index) => [id, index]));
  const endOfQueue = queuePositions.size;
  const caseList = submittedCases
    .filter((item) => queueFor(item.status))
    .sort(
      (a, b) => (queuePositions.get(a.id) ?? endOfQueue) - (queuePositions.get(b.id) ?? endOfQueue),
    );
  const currentIndex = caseList.findIndex((item) => item.id === current?.item.id);
  const nextCase = [
    ...caseList.slice(currentIndex + 1),
    ...caseList.slice(0, Math.max(currentIndex, 0)),
  ].find((item) => item.status === "ready");
  const navigation = (
    <>
      <Button
        variant="ghost"
        aria-current={!productsNav ? "page" : undefined}
        disabled={!!opening || savingProduct}
        onClick={() => navigate("inbox")}
      >
        Inbox
      </Button>
      <Button
        variant="ghost"
        aria-current={productsNav ? "page" : undefined}
        disabled={!!opening || savingProduct}
        onClick={() => navigate("products")}
      >
        Products
      </Button>
    </>
  );
  const displayedError =
    error || (view !== "add-product" && (loadError || (view === "product" && orderError)));

  return (
    <DeskShell
      role="Shop owner"
      view={view === "case" ? (current?.item.id ?? view) : view}
      navigation={navigation}
      canLeave={canLeave}
    >
      {displayedError && (
        <Alert variant="destructive">
          <AlertDescription>
            {displayedError}
            {!error && (
              <Button variant="ghost" onClick={reload}>
                Try again
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}
      {view === "products" && (
        <Products
          items={listings ?? []}
          loading={!listings && !loadError}
          onAdd={() => navigate("add-product")}
          onOpen={openProduct}
        />
      )}
      {view === "add-product" && (
        <ProductWizard
          onCancel={() => navigate("products")}
          onSaved={saveProduct}
          onDraftChange={setDirtyProduct}
          onSaving={setSavingProduct}
        />
      )}
      {view === "product" && product && (
        <>
          <Button
            variant="ghost"
            className="back-link"
            disabled={!!opening}
            onClick={() => navigate("products")}
          >
            <ArrowLeft aria-hidden /> Back to products
          </Button>
          <div className="product-heading">
            <h1 tabIndex={-1}>
              {product.title}
              <span className="heading-period">.</span>
            </h1>
            {sampleMode && <ProductClaimLink key={product.id} id={product.id} />}
          </div>
          <section className="panel product-details" aria-label="Listing details">
            <ListingOverview listing={product} />
          </section>
          <section className="product-claims" aria-labelledby="product-claims">
            <h2 id="product-claims">Claims for this product</h2>
            {!productCases && !displayedError && (
              <p className="loading-row" role="status">
                Loading product claims…
              </p>
            )}
            {productCases?.length === 0 && !loadError && !orderError && (
              <p className="empty-state">No claims yet for this product.</p>
            )}
            {productCases && productCases.length > 0 && (
              <CaseRows
                items={productCases}
                label="Product claims"
                opening={opening}
                product
                onOpen={(item) => openCase(item, product)}
                onChecked={reload}
              />
            )}
          </section>
        </>
      )}
      {view === "case" && current && (
        <>
          <Button
            variant="ghost"
            className="back-link"
            disabled={!!opening}
            onClick={() => (current.product ? openProduct(current.product) : navigate("inbox"))}
          >
            <ArrowLeft aria-hidden /> {current.product ? "Back to product" : "Back to inbox"}
          </Button>
          <h1 tabIndex={-1}>
            Review case<span className="heading-period">.</span>
          </h1>
          <div className="review-layout">
            <CaseSidebar
              items={caseList}
              currentId={current.item.id}
              opening={opening}
              product={!!current.product}
              onOpen={(item) => void openCase(item, current.product)}
            />
            <div className="review-content">
              <Review
                key={current.item.id}
                item={current.item}
                title={current.summary.product}
                saved={current.saved}
                onDecision={recordDecision}
                reload={async () => {
                  const item = await api<ShopCase>(
                    "shop/cases/" + encodeURIComponent(current.item.id),
                  );
                  if (item.decision) recordDecision(item);
                }}
                next={nextCase ? () => openCase(nextCase, current.product) : undefined}
                openingNext={!!opening}
              />
            </div>
          </div>
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
          <CaseRows
            items={visibleCases ?? []}
            label={queues.find(([key]) => key === queue)?.[1] + " cases"}
            opening={opening}
            onOpen={openCase}
            onChecked={reload}
          />
        </>
      )}
    </DeskShell>
  );
}
