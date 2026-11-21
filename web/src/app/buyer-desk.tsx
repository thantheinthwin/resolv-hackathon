"use client";

import { ArrowLeft, ArrowRight, CircleCheck, Package, QrCode } from "lucide-react";
import QRCode from "qrcode";
import {
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
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
  type ClaimTarget,
  type Draft,
  type OrderSummary,
} from "../lib/buyer-session";
import { claims, type Claim, type Order, type Report, type UploadLink } from "../lib/models";
import { ClaimProduct, ProductReference } from "./claim-product";
import { DeskShell } from "./desk-shell";
import { ReportEvidence } from "./report-evidence";
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

function ClaimContext({ target }: { target: ClaimTarget }) {
  return target.order ? (
    <OrderDetails order={target.order} />
  ) : (
    <ProductReference listing={target.listing} />
  );
}

function Steps({ current }: { current: "workspace" | "complaint" | "video" | "sent" }) {
  const steps = [
    ["workspace", "Product"],
    ["complaint", "Problem"],
    ["video", "Video"],
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
  id,
  actionError,
  children,
}: {
  title: string;
  detail?: string;
  badge: string;
  id?: string;
  actionError?: string;
  children: ReactNode;
}) {
  return (
    <li className="report-row" data-report={id}>
      <div className="report-row-title">
        <div>
          <h3>{title}</h3>
          {detail && <p className="muted-copy">{detail}</p>}
        </div>
        <Badge variant="secondary">{badge}</Badge>
      </div>
      {children}
      {actionError && (
        <Alert variant="destructive">
          <AlertDescription>{actionError}</AlertDescription>
        </Alert>
      )}
    </li>
  );
}

export function BuyerDesk({
  sampleMode,
  linkedProduct,
}: {
  sampleMode: boolean;
  linkedProduct?: string;
}) {
  const { draft, receipts } = useBuyerSession();
  const [step, setStep] = useState<"complaint" | "video" | "sent">();
  const [receipt, setReceipt] = useState<{
    id: string;
    target: ClaimTarget;
    claim: Claim;
    failed: boolean;
    warning: string;
  }>();
  const [orders, setOrders] = useState<Order[]>();
  const [reports, setReports] = useState<Report[]>();
  const [orderError, setOrderError] = useState(false);
  const [reportError, setReportError] = useState(false);
  const [deletionError, setDeletionError] = useState<{ target: string; message: string }>();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [sending, setSending] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatedHandoff, setHandoff] = useState<{ caseId: string; url: string; image: string }>();
  const [deleting, setDeleting] = useState(false);
  const [expandedReport, setExpandedReport] = useState<string>();

  const view = step === "sent" || draft ? (step ?? "workspace") : "workspace";
  const frameBody = useRef<HTMLDivElement>(null);
  const [frameActions, setFrameActions] = useState<HTMLDivElement | null>(null);
  const caseId = draft?.caseId;
  const handoff = generatedHandoff?.caseId === caseId ? generatedHandoff : undefined;
  const claim = draft?.claim;
  const deletingIds = useRef(new Set<string>());
  const replacingDraft = useRef(false);

  useLayoutEffect(() => {
    if (frameBody.current) frameBody.current.scrollTop = 0;
  }, [view]);

  useEffect(() => {
    let active = true;
    api<Order[]>("orders").then(
      (result) => {
        if (active) {
          setOrders(result);
          setOrderError(false);
        }
      },
      () => {
        if (active) setOrderError(true);
      },
    );
    return () => {
      active = false;
    };
  }, [refresh]);

  useEffect(() => {
    let active = true;
    let loading = false;
    async function load() {
      if (loading) return;
      loading = true;
      try {
        const result = await api<Report[]>("my/cases");
        if (active) {
          setReports(result.filter(({ id }) => !deletingIds.current.has(id)));
          setReportError(false);
        }
      } catch {
        if (active) setReportError(true);
      } finally {
        loading = false;
      }
    }
    void load();
    const timer = setInterval(load, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [refresh]);

  function finish(id: string, failed = false, warning = "") {
    if (draft?.claim) {
      setReceipt({ id, target: draft, claim: draft.claim, failed, warning });
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
    if (!caseId || sending || (view !== "workspace" && view !== "video")) return;
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

  function updateDraft(update: Partial<Pick<Draft, "description" | "claim" | "step">>) {
    changeBuyerSession((session) =>
      session.draft ? { ...session, draft: { ...session.draft, ...update } } : session,
    );
  }

  function resume() {
    if (!draft) return;
    setError("");
    setStep(draft.step);
  }

  async function newReport(target: ClaimTarget) {
    if (replacingDraft.current || deleting) return;
    if (
      (target.order && draft?.order?.id === target.order.id) ||
      (target.listing && draft?.listing?.id === target.listing.id)
    ) {
      resume();
      return;
    }
    if (draft) {
      if (!window.confirm("Replace your current draft? Its progress will be discarded.")) return;
      replacingDraft.current = true;
      setDeleting(true);
      try {
        const result = await deleteReport(caseId, true);
        if (!result.deleted) {
          setMessage("Your video reached the shop. The report is still in My reports.");
          return;
        }
      } catch (error) {
        setError(error instanceof Error ? error.message : "Couldn’t replace the draft. Try again.");
        return;
      } finally {
        replacingDraft.current = false;
        setDeleting(false);
      }
    }
    changeBuyerSession((session) => ({
      ...session,
      draft: { ...target, description: "", step: "complaint" },
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
      if (draft.order) link.searchParams.set("order", draft.order.id);
      else link.searchParams.set("product", draft.listing.id.slice(0, 8));
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
    const deletionTarget = isDraft ? "draft" : id;
    if (
      !deletionTarget ||
      deleting ||
      sending ||
      generating ||
      !window.confirm(
        isDraft
          ? "Discard this draft? This permanently deletes the report and any video or evidence attached to it."
          : "Delete this report, video and evidence permanently?",
      )
    )
      return;
    setDeleting(true);
    setDeletionError(undefined);
    setMessage("");
    try {
      const result = await deleteReport(id, isDraft);
      if (!result.deleted) {
        setStep((current) => (current === "sent" ? current : undefined));
        setMessage("Your video reached the shop. The report is still in My reports.");
        return;
      }
      if (result.id) {
        deletingIds.current.add(result.id);
        setReports((items) => items?.filter((item) => item.id !== result.id));
      }
      if (isDraft) setStep(undefined);
      setMessage(isDraft ? "Draft discarded." : "Report deleted.");
    } catch (error) {
      setDeletionError({
        target: deletionTarget,
        message: error instanceof Error ? error.message : "Couldn’t delete this report. Try again.",
      });
    } finally {
      setDeleting(false);
    }
  }

  const navigation = (
    <>
      <a
        href="#start-a-claim"
        onClick={() => {
          if (!sending && !generating) {
            setStep(undefined);
            setError("");
          }
        }}
      >
        Start a claim
      </a>
      <a href="#my-reports">My reports</a>
    </>
  );

  const frameTitle = {
    workspace: "Choose a product or order",
    complaint: "Tell us what went wrong",
    video: "Add your unboxing video",
    sent: receipt?.failed ? "Video received. Checking failed" : "Sent to the shop",
  }[view];
  const target = view === "sent" ? receipt?.target : draft;
  const badgeClaim = view === "sent" ? receipt?.claim : view === "video" ? claim : undefined;

  return (
    <DeskShell role="Buyer" view={view} navigation={navigation} navigationBlocked={sending}>
      <section id="start-a-claim" className="claim-workspace" aria-labelledby="claim-title">
        <h1 id="claim-title" tabIndex={-1}>
          Start a claim<span className="heading-period">.</span>
        </h1>
        <Steps current={view} />
        <div className="panel claim-frame">
          <header className="claim-frame-heading">
            <h2
              className="claim-step-title"
              id="claim-step-title"
              key={view}
              tabIndex={-1}
              data-step-heading
            >
              {frameTitle}
              <span className="heading-period">.</span>
            </h2>
            {view === "sent" && !receipt?.failed && <CircleCheck aria-hidden />}
          </header>
          <div className="claim-frame-body" ref={frameBody}>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {view !== "workspace" && target && (
              <div className="order-recap">
                <div className="order-context">
                  <ClaimContext target={target} />
                </div>
                {view === "complaint" && (
                  <Button
                    variant="outline"
                    onClick={() => {
                      setError("");
                      setStep(undefined);
                    }}
                  >
                    {draft?.order ? "Change order" : "Change product"}
                  </Button>
                )}
                {badgeClaim && <Badge variant="secondary">{claims[badgeClaim]}</Badge>}
              </div>
            )}
            <div hidden={view !== "workspace"}>
              {draft && (
                <div className="claim-draft-callout">
                  <span>
                    You have a draft for{" "}
                    <strong>{draft.order?.title ?? draft.listing?.title}</strong>.
                  </span>
                  <a className="text-link" href="#my-reports">
                    Go to draft
                  </a>
                </div>
              )}
              {sampleMode && (
                <ClaimProduct
                  key={receipt?.id ?? linkedProduct}
                  linkedProduct={linkedProduct}
                  busy={deleting}
                  onConfirm={(listing) => void newReport({ listing })}
                />
              )}
              <details className="claim-existing-orders" open={!sampleMode || undefined}>
                <summary>Use an existing order</summary>
                {orderError ? (
                  <div className="action-row" role="status">
                    Couldn’t load your orders.
                    <Button variant="outline" onClick={() => setRefresh((value) => value + 1)}>
                      Try again
                    </Button>
                  </div>
                ) : !orders ? (
                  <p role="status">Loading your orders…</p>
                ) : (
                  orders.length === 0 && (
                    <p className="muted-copy">Delivered orders will appear here.</p>
                  )
                )}
                <ul className="order-list">
                  {orders?.map(summarizeOrder).map((order) => (
                    <li className="order-row" key={order.id}>
                      <div className="order-context">
                        <OrderDetails order={order} />
                      </div>
                      <Button disabled={deleting} onClick={() => void newReport({ order })}>
                        {draft?.order?.id === order.id ? "Resume report" : "Report a problem"}{" "}
                        <ArrowRight aria-hidden />
                      </Button>
                    </li>
                  ))}
                </ul>
              </details>
            </div>
            {view === "complaint" && draft && (
              <form
                id="claim-problem"
                aria-labelledby="claim-step-title"
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
                  <p className="muted-copy" id="description-tip">
                    {claim
                      ? guidance[claim].prompt
                      : "Describe what was different from what you expected."}
                  </p>
                  <Textarea
                    id="buyer-description"
                    value={draft.description}
                    aria-describedby="description-tip"
                    onChange={(event) => updateDraft({ description: event.target.value })}
                  />
                </div>
              </form>
            )}
            {view === "video" && draft && claim && (
              <div className="upload-layout">
                <div className="filming-tip">
                  <h2>What to show</h2>
                  <p>{guidance[claim].video}</p>
                  <p className="muted-copy">Keep faces and personal details out of the frame.</p>
                </div>
                <Uploader
                  blocked={generating || deleting}
                  getEndpoint={async () =>
                    "cases/" + encodeURIComponent(await ensureDraftCase()) + "/video"
                  }
                  onSending={setSending}
                  onDone={({ id, warnings }) => finish(id, false, warnings?.join(" "))}
                  sendActionTarget={frameActions}
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
            )}
            {view === "sent" && receipt && (
              <div className="claim-receipt">
                <small>Report {receipt.id.slice(0, 8)}</small>
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
              </div>
            )}
          </div>
          <div className="claim-frame-actions" ref={setFrameActions}>
            {view === "complaint" && (
              <Button type="submit" form="claim-problem" disabled={!claim}>
                Continue to video <ArrowRight aria-hidden />
              </Button>
            )}
            {view === "video" && !caseId && (
              <Button
                variant="ghost"
                className="claim-back-action"
                disabled={sending || generating || deleting}
                onClick={() => {
                  updateDraft({ step: "complaint" });
                  setStep("complaint");
                }}
              >
                <ArrowLeft aria-hidden /> Back to the claim
              </Button>
            )}
            {view === "sent" && (
              <Button asChild>
                <a href="#my-reports">
                  View my reports <ArrowRight aria-hidden />
                </a>
              </Button>
            )}
          </div>
        </div>
      </section>
      <section id="my-reports" className="buyer-reports" aria-labelledby="buyer-reports-title">
        <h2 id="buyer-reports-title">
          My reports<span className="heading-period">.</span>
        </h2>
        {message && <p role="status">{message}</p>}
        {reportError && (
          <div className="action-row" role="status">
            Couldn’t load your reports.
            <Button variant="outline" onClick={() => setRefresh((value) => value + 1)}>
              Try again
            </Button>
          </div>
        )}
        {!reports && !reportError && (
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
              title={draft.order ? draft.order.title : draft.listing.title}
              detail={claim ? claims[claim] : "Choose a claim to continue"}
              badge="Draft"
              actionError={deletionError?.target === "draft" ? deletionError.message : undefined}
            >
              <div className="action-row">
                <Button disabled={deleting || sending || generating} onClick={resume}>
                  {draft.step === "video" ? "Resume upload" : "Continue report"}
                </Button>
                <Button
                  variant="ghost"
                  disabled={deleting || sending || generating}
                  onClick={() => remove(caseId, true)}
                >
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
              const savedClaim = report.claim_type ?? saved?.claim;
              const expanded = expandedReport === report.id;
              return (
                <ReportRow
                  key={report.id}
                  id={report.id}
                  title={
                    report.product ??
                    saved?.order?.title ??
                    saved?.listing?.title ??
                    "Report " + report.id.slice(0, 8)
                  }
                  detail={savedClaim && claims[savedClaim] + " · Report " + report.id.slice(0, 8)}
                  badge={confirmed ? "Sent" : copy.label}
                  actionError={
                    deletionError?.target === report.id ? deletionError.message : undefined
                  }
                >
                  <p>
                    {report.note_for_buyer?.trim() ||
                      (confirmed ? "No action needed. The shop will reply here." : copy.next)}
                  </p>
                  <div className="action-row">
                    {sampleMode && (
                      <Button
                        variant="outline"
                        aria-expanded={expanded}
                        aria-controls={"report-evidence-" + report.id}
                        onClick={() => setExpandedReport(expanded ? undefined : report.id)}
                      >
                        {expanded ? "Hide report details" : "View report details"}
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      disabled={deleting || sending || generating}
                      onClick={() => remove(report.id)}
                    >
                      Delete report
                    </Button>
                  </div>
                  {sampleMode && (
                    <div id={"report-evidence-" + report.id} hidden={!expanded}>
                      {expanded && <ReportEvidence id={report.id} />}
                    </div>
                  )}
                </ReportRow>
              );
            })}
        </ul>
      </section>
    </DeskShell>
  );
}
