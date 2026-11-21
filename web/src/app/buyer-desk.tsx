"use client";

import { ArrowLeft, ArrowRight, CircleCheck, Package, QrCode } from "lucide-react";
import Link from "next/link";
import QRCode from "qrcode";
import { useEffect, useEffectEvent, useRef, useState, type ReactNode } from "react";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { RadioGroup, RadioGroupItem } from "../components/ui/radio-group";
import { Textarea } from "../components/ui/textarea";
import { api, ApiError } from "../lib/client";
import {
  changeBuyerSession,
  deleteReport,
  ensureDraftCase,
  rememberReceipt,
  summarizeOrder,
  useBuyerSession,
  videoReceived,
  type Draft,
  type OrderSummary,
} from "../lib/buyer-session";
import { claims, type Claim, type Order, type Report, type UploadLink } from "../lib/models";
import { DeskShell } from "./desk-shell";
import { Uploader } from "./uploader";

const guidance: Record<Claim, { example: string; prompt: string; video: string }> = {
  wrong_item: {
    example: "You ordered a medium, but a large arrived.",
    prompt: "What item, color, or size did you receive?",
    video: "Show the item and its color, size, or model label.",
  },
  missing: {
    example: "An item, accessory, or part is missing.",
    prompt: "Which items or parts were missing?",
    video: "Show everything that came in the parcel, including any empty compartments.",
  },
  damaged: {
    example: "The item arrived torn, cracked, or dented.",
    prompt: "Where is the damage, and what does it look like?",
    video: "Show the whole item, then move closer to the damaged area.",
  },
  counterfeit: {
    example: "The branding or packaging looks different.",
    prompt: "What made you question whether the item is genuine?",
    video: "Show the markings or packaging that raised your concern.",
  },
};

const reportStates: Record<Report["status"], { label: string; next: string }> = {
  sent: {
    label: "Waiting for upload confirmation",
    next: "Check whether your video finished uploading.",
  },
  checking: {
    label: "Being checked",
    next: "No action needed. We’ll update this report when the video check finishes.",
  },
  with_shop: { label: "With the shop", next: "The shop owner is reviewing your report." },
  replied: { label: "Shop replied", next: "Review complete." },
  failed: {
    label: "Video received · Checking failed",
    next: "Contact the shop with your report ID for help.",
  },
};

function OrderDetails({ order }: { order: OrderSummary }) {
  return (
    <>
      {order.photo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="order-photo" src={order.photo} alt="" />
      ) : (
        <span className="order-photo order-icon">
          <Package aria-hidden />
        </span>
      )}
      <div>
        <strong>{order.title}</strong>
        <p>{[order.color, order.size, "Qty " + order.quantity].filter(Boolean).join(" · ")}</p>
        <small>Order {order.id}</small>
      </div>
    </>
  );
}

function Steps({ current }: { current: "complaint" | "video" | "sent" }) {
  const steps = [
    ["complaint", "Report the problem"],
    ["video", "Add video"],
    ["sent", "Sent"],
  ];
  const index = steps.findIndex(([step]) => step === current);
  return (
    <ol className="report-steps" aria-label="Report progress">
      {steps.map(([step, label], position) => (
        <li
          key={step}
          aria-current={step === current ? "step" : undefined}
          data-done={position < index}
        >
          <span aria-hidden="true">{position + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}

function ReportRow({
  title,
  detail,
  badge,
  children,
}: {
  title: string;
  detail?: string;
  badge: string;
  children: ReactNode;
}) {
  return (
    <li className="report-row">
      <div className="report-row-title">
        <div>
          <h2>{title}</h2>
          {detail && <p className="muted-copy">{detail}</p>}
        </div>
        <Badge variant="secondary">{badge}</Badge>
      </div>
      {children}
    </li>
  );
}

export function BuyerDesk({ home }: { home: "orders" | "reports" }) {
  const { draft, receipts } = useBuyerSession();
  const [step, setStep] = useState<"complaint" | "video" | "sent">();
  const [receipt, setReceipt] = useState<{
    id: string;
    order: OrderSummary;
    claim: Claim;
    failed: boolean;
    warning: string;
  }>();
  const [orders, setOrders] = useState<Order[]>();
  const [reports, setReports] = useState<Report[]>();
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [sending, setSending] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatedHandoff, setHandoff] = useState<{ caseId: string; url: string; image: string }>();
  const [deleting, setDeleting] = useState(false);

  const view = step ?? home;
  const caseId = draft?.caseId;
  const handoff = generatedHandoff?.caseId === caseId ? generatedHandoff : undefined;
  const claim = draft?.claim;
  const deletingIds = useRef(new Set<string>());

  useEffect(() => {
    if (view !== "orders" && view !== "reports") return;
    let active = true;
    let loading = false;
    async function load() {
      if (loading) return;
      loading = true;
      try {
        if (view === "orders") {
          const result = await api<Order[]>("orders");
          if (active) setOrders(result);
        } else {
          const result = await api<Report[]>("my/cases");
          if (active) setReports(result.filter(({ id }) => !deletingIds.current.has(id)));
        }
        if (active) setLoadError("");
      } catch {
        if (active)
          setLoadError("Couldn’t load " + (view === "orders" ? "your orders." : "your reports."));
      } finally {
        loading = false;
      }
    }
    void load();
    const timer = view === "reports" ? setInterval(load, 2000) : undefined;
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [view, refresh]);

  function finish(id: string, failed = false, warning = "") {
    if (draft?.claim) {
      setReceipt({ id, order: draft.order, claim: draft.claim, failed, warning });
      setStep("sent");
    }
    rememberReceipt(id);
  }

  const reconcile = useEffectEvent((report: Report) => {
    if (!videoReceived(report.status)) return;
    if (view === "video") finish(report.id, report.status === "failed");
    else rememberReceipt(report.id);
  });

  useEffect(() => {
    if (!caseId || sending || !["orders", "reports", "video"].includes(view)) return;
    const endpoint = "cases/" + encodeURIComponent(caseId);
    let active = true;
    async function check() {
      try {
        const report = await api<Report>(endpoint);
        if (active) reconcile(report);
      } catch (error) {
        if (active && error instanceof ApiError && error.status === 404) {
          setError("This draft is no longer available. Discard it from My reports to start again.");
        }
      }
    }
    void check();
    const timer = setInterval(check, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [caseId, sending, view]);

  function updateDraft(update: Partial<Draft>) {
    changeBuyerSession((session) =>
      session.draft ? { ...session, draft: { ...session.draft, ...update } } : session,
    );
  }

  function resume() {
    if (!draft) return;
    setError("");
    setStep(draft.step);
  }

  function newReport(order: OrderSummary) {
    if (draft?.order.id === order.id) {
      resume();
      return;
    }
    if (draft) {
      setError("Resume or discard your current draft in My reports before starting another.");
      return;
    }
    changeBuyerSession((session) => ({
      ...session,
      draft: { order, description: "", step: "complaint" },
    }));
    setError("");
    setStep("complaint");
  }

  async function generateHandoff() {
    if (generating || sending || !draft) return;
    setGenerating(true);
    setError("");
    try {
      const id = await ensureDraftCase();
      const { url } = await api<UploadLink>("cases/" + encodeURIComponent(id) + "/upload-link", {});
      const origin = process.env.NEXT_PUBLIC_WEB_ORIGIN || location.origin;
      const link = new URL(url, origin);
      if (process.env.NEXT_PUBLIC_WEB_ORIGIN) {
        const configured = new URL(origin);
        link.protocol = configured.protocol;
        link.host = configured.host;
      }
      link.searchParams.set("order", draft.order.id);
      const href = link.href;
      setHandoff({ caseId: id, url: href, image: await QRCode.toDataURL(href) });
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "Couldn’t prepare a phone upload. Try again.",
      );
    } finally {
      setGenerating(false);
    }
  }

  async function remove(id?: string, isDraft = false) {
    if (
      deleting ||
      !window.confirm(
        isDraft
          ? "Discard this draft? This permanently deletes the report and any video or evidence attached to it."
          : "Delete this report, video and evidence permanently?",
      )
    )
      return;
    setDeleting(true);
    setError("");
    try {
      const result = await deleteReport(id, isDraft);
      if (!result.deleted) {
        setMessage("Your video reached the shop. The report is still in My reports.");
        return;
      }
      if (result.id) {
        deletingIds.current.add(result.id);
        setReports((items) => items?.filter((item) => item.id !== result.id));
      }
      setMessage(isDraft ? "Draft discarded." : "Report deleted.");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Couldn’t delete this report. Try again.");
    } finally {
      setDeleting(false);
    }
  }

  const navigation = (
    <>
      <Link
        href="/orders"
        aria-current={home === "orders" ? "page" : undefined}
        onClick={
          home === "orders"
            ? () => {
                setStep(undefined);
                setError("");
              }
            : undefined
        }
      >
        Your orders
      </Link>
      <Link
        href="/reports"
        aria-current={home === "reports" ? "page" : undefined}
        onClick={
          home === "reports"
            ? () => {
                setStep(undefined);
                setError("");
              }
            : undefined
        }
      >
        My reports
      </Link>
    </>
  );

  return (
    <DeskShell role="Buyer" view={view} navigation={navigation}>
      {view !== "video" && error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {loadError && (view === "orders" || view === "reports") && (
        <Alert variant="destructive">
          <AlertDescription>
            {loadError}{" "}
            <Button variant="ghost" onClick={() => setRefresh((value) => value + 1)}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {message && <p role="status">{message}</p>}
      {view === "orders" && (
        <>
          <h1 tabIndex={-1}>
            Your orders<span className="heading-period">.</span>
          </h1>
          {!orders && !loadError && (
            <p className="loading-row" role="status">
              Loading your orders…
            </p>
          )}
          {orders?.length === 0 && (
            <p className="empty-state">Delivered orders will appear here.</p>
          )}
          <ul className="order-list">
            {orders?.map(summarizeOrder).map((order) => (
              <li className="panel order-row" key={order.id}>
                <div className="order-context">
                  <OrderDetails order={order} />
                </div>
                <Button onClick={() => newReport(order)}>
                  {draft?.order.id === order.id ? "Resume report" : "Report a problem"}{" "}
                  <ArrowRight aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}
      {view === "complaint" && draft && (
        <div className="buyer-form">
          <Steps current="complaint" />
          <h1 tabIndex={-1}>
            Tell us what went wrong<span className="heading-period">.</span>
          </h1>
          <div className="order-context order-recap">
            <OrderDetails order={draft.order} />
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!claim) return;
              updateDraft({ step: "video" });
              setError("");
              setStep("video");
            }}
          >
            <RadioGroup
              aria-label="What went wrong?"
              className="choices"
              value={claim ?? ""}
              required
              onValueChange={(value) => updateDraft({ claim: value as Claim })}
            >
              {(Object.keys(claims) as Claim[]).map((id) => (
                <label className="claim-option" key={id}>
                  <RadioGroupItem
                    value={id}
                    aria-labelledby={"claim-" + id}
                    aria-describedby={"example-" + id}
                  />
                  <span>
                    <strong id={"claim-" + id}>{claims[id]}</strong>
                    <span id={"example-" + id}>{guidance[id].example}</span>
                  </span>
                </label>
              ))}
            </RadioGroup>
            <div className="description-field">
              <label htmlFor="buyer-description">
                What happened? <span className="muted-copy">(optional)</span>
              </label>
              {claim && (
                <p className="muted-copy" id="description-tip">
                  {guidance[claim].prompt}
                </p>
              )}
              <Textarea
                id="buyer-description"
                value={draft.description}
                aria-describedby={claim ? "description-tip" : undefined}
                onChange={(event) => updateDraft({ description: event.target.value })}
              />
            </div>
            <Button disabled={!claim}>
              Continue to video <ArrowRight aria-hidden />
            </Button>
          </form>
        </div>
      )}
      {view === "video" && draft && claim && (
        <>
          <Steps current="video" />
          <h1 tabIndex={-1}>
            Add your unboxing video<span className="heading-period">.</span>
          </h1>
          <div className="order-recap">
            <div className="order-context">
              <OrderDetails order={draft.order} />
            </div>
            <Badge variant="secondary">{claims[claim]}</Badge>
          </div>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="upload-layout">
            <div className="filming-tip">
              <h2>What to show</h2>
              <p>{guidance[claim].video}</p>
              <p className="muted-copy">Keep faces and personal details out of the frame.</p>
            </div>
            <Uploader
              blocked={generating}
              getEndpoint={async () =>
                "cases/" + encodeURIComponent(await ensureDraftCase()) + "/video"
              }
              onSending={setSending}
              onDone={({ id, warnings }) => finish(id, false, warnings?.join(" "))}
              sendLabel="Send to the shop"
            />
            <section className="panel phone-handoff">
              <QrCode aria-hidden />
              <h2>Upload from your phone</h2>
              {handoff ? (
                <>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={handoff.image}
                    alt="Scan to upload from your phone"
                    width="148"
                    height="148"
                  />
                  <p>Scan to choose a video.</p>
                  <a href={handoff.url} className="text-link">
                    Open phone upload
                  </a>
                </>
              ) : (
                <Button
                  variant="outline"
                  disabled={sending || generating}
                  onClick={generateHandoff}
                >
                  {generating ? "Preparing the code…" : "Show QR code"}
                </Button>
              )}
            </section>
          </div>
          {!caseId && (
            <Button
              variant="ghost"
              disabled={sending || generating}
              onClick={() => {
                updateDraft({ step: "complaint" });
                setStep("complaint");
              }}
            >
              <ArrowLeft aria-hidden /> Back to the claim
            </Button>
          )}
        </>
      )}
      {view === "sent" && receipt && (
        <section className="panel receipt">
          <CircleCheck aria-hidden />
          <Steps current="sent" />
          <h1 tabIndex={-1}>
            {receipt.failed ? "Video received. Checking failed." : "Sent to the shop."}
          </h1>
          <div className="order-context">
            <OrderDetails order={receipt.order} />
          </div>
          <p>
            {claims[receipt.claim]} · Report {receipt.id.slice(0, 8)}
          </p>
          <p>
            {receipt.failed
              ? reportStates.failed.next
              : "The shop will reply in My reports. No action is needed right now."}
          </p>
          {receipt.warning && (
            <p className="warning-copy" role="status">
              {receipt.warning}
            </p>
          )}
          {home === "reports" ? (
            <Button onClick={() => setStep(undefined)}>
              View my reports <ArrowRight aria-hidden />
            </Button>
          ) : (
            <Button asChild>
              <Link href="/reports">
                View my reports <ArrowRight aria-hidden />
              </Link>
            </Button>
          )}
        </section>
      )}
      {view === "reports" && (
        <>
          <h1 tabIndex={-1}>
            My reports<span className="heading-period">.</span>
          </h1>
          {!reports && !loadError && (
            <p className="loading-row" role="status">
              Loading your reports…
            </p>
          )}
          {reports?.length === 0 && !draft && (
            <p className="empty-state">Reports you send to the shop will appear here.</p>
          )}
          <ul className="report-list">
            {draft && (
              <ReportRow
                title={draft.order.title}
                detail={claim ? claims[claim] : "Choose a claim to continue"}
                badge="Draft"
              >
                <div className="action-row">
                  <Button onClick={resume}>
                    {draft.step === "video" ? "Resume upload" : "Continue report"}
                  </Button>
                  <Button variant="ghost" disabled={deleting} onClick={() => remove(caseId, true)}>
                    Discard draft
                  </Button>
                </div>
              </ReportRow>
            )}
            {reports
              ?.filter((report) => report.id !== caseId)
              .map((report) => {
                const saved = receipts[report.id];
                const copy = reportStates[report.status];
                const confirmed = report.status === "sent" && saved;
                return (
                  <ReportRow
                    key={report.id}
                    title={saved?.order.title ?? "Report " + report.id.slice(0, 8)}
                    detail={saved && claims[saved.claim] + " · Report " + report.id.slice(0, 8)}
                    badge={confirmed ? "Sent" : copy.label}
                  >
                    <p>
                      {report.note_for_buyer?.trim() ||
                        (confirmed ? "No action needed. The shop will reply here." : copy.next)}
                    </p>
                    <Button variant="ghost" disabled={deleting} onClick={() => remove(report.id)}>
                      Delete report
                    </Button>
                  </ReportRow>
                );
              })}
          </ul>
        </>
      )}
    </DeskShell>
  );
}
