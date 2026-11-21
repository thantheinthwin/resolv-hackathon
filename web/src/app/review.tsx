"use client";

import { ArrowRight, CircleCheck } from "lucide-react";
import { useRef, useState } from "react";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Alert, AlertDescription } from "../components/ui/alert";
import { claims, reasons, type Case } from "../lib/models";
import { api, ApiError } from "../lib/client";

type Verdict = NonNullable<Case["verdict"]>;
type Decision = NonNullable<Case["decision"]>;
const checkLabels: Record<string, string> = {
  seal: "Parcel seal",
  listing: "Listing match",
  damage: "Product damage",
  continuity: "Video continuity",
};
const choices: Record<Decision["choice"], string> = {
  agree: "Agree",
  disagree: "Disagree",
  side_buyer: "Support the buyer",
  side_seller: "Support the shop",
};

function findingsFor(verdict: Verdict) {
  const findings = Object.entries(verdict.checks).flatMap(([check, value]) =>
    value.findings.map(({ t, note_en, note_th }) => ({
      check,
      t,
      note: note_en,
      thai: note_th,
      evidence: verdict.evidence.find((frame) => frame.check === check && frame.t === t),
    })),
  );
  for (const evidence of verdict.evidence) {
    if (!findings.some(({ t, check }) => t === evidence.t && check === evidence.check)) {
      findings.push({
        check: evidence.check,
        t: evidence.t,
        note: checkLabels[evidence.check] ?? evidence.check,
        thai: "",
        evidence,
      });
    }
  }
  return findings.sort((a, b) => a.t - b.t);
}

function timestamp(seconds: number) {
  const time = Math.floor(seconds);
  return Math.floor(time / 60) + ":" + String(time % 60).padStart(2, "0");
}

function mediaPath(id: string, source: string) {
  if (source.startsWith("/api/files/")) return source;
  if (/^(cases|listings)\//.test(source)) return "/api/files/" + source;
  return "/api/files/cases/" + encodeURIComponent(id) + "/" + source.replace(/^\/+/, "");
}

export function Review({
  item,
  title,
  saved,
  onDecision,
  reload,
  next,
  openingNext,
}: {
  item: Case;
  title: string;
  saved: boolean;
  onDecision: (item: Case) => void;
  reload: () => Promise<void>;
  next?: () => void;
  openingNext: boolean;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const submitting = useRef(false);
  const savedMessage = useRef<HTMLHeadingElement>(null);
  const explanation = useRef<HTMLTextAreaElement>(null);
  const [selected, setSelected] = useState(0);
  const [videoFailed, setVideoFailed] = useState(false);
  const [choice, setChoice] = useState<Decision["choice"] | "">("");
  const [reason, setReason] = useState<Decision["reason"]>();
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const verdict = item.verdict;

  if (!verdict) return <p role="status">This case is still waiting for review.</p>;
  const findings = findingsFor(verdict);
  const activeFinding = findings[selected];
  const summary =
    verdict.display === "unsure"
      ? "Unsure: check the video"
      : verdict.verdict === "buyer_right"
        ? "Buyer is right"
        : "Seller is right";

  async function saveDecision(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || !choice) return;
    if (!note.trim()) {
      setNoteError(true);
      explanation.current?.focus();
      return;
    }
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      const updated = await api<Case>("shop/cases/" + encodeURIComponent(item.id) + "/decision", {
        choice,
        reason: choice === "disagree" ? reason : undefined,
        note_for_buyer: note.trim(),
      } satisfies Decision);
      onDecision(updated);
      requestAnimationFrame(() => savedMessage.current?.focus());
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        try {
          await reload();
          requestAnimationFrame(() => savedMessage.current?.focus());
        } catch {
          setError(
            "Another reviewer may have saved a decision. Return to the inbox and reopen the case.",
          );
        }
      } else {
        setError(error instanceof Error ? error.message : "Couldn’t save the decision. Try again.");
      }
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  return (
    <>
      <h1 tabIndex={-1}>
        Review case<span className="heading-period">.</span>
      </h1>
      <div className="case-context panel">
        <section>
          <small>Ordered</small>
          <h2>{title}</h2>
          <p>Order {item.order_id}</p>
        </section>
        <section>
          <small>Buyer reported</small>
          <h2>{claims[item.claim_type]}</h2>
          {item.description && <p>{item.description}</p>}
        </section>
      </div>
      <div className="evidence-layout">
        <section className="footage" aria-label="Video evidence">
          {item.video_url && !videoFailed ? (
            <video
              className="evidence-video"
              ref={video}
              src={item.video_url}
              controls
              playsInline
              preload="metadata"
              aria-label="Buyer’s unboxing video"
              onError={() => setVideoFailed(true)}
            />
          ) : (
            <p className="empty-state">Video unavailable for this case.</p>
          )}
          {activeFinding?.evidence?.frame && (
            <div className="comparison">
              <figure>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={mediaPath(item.id, activeFinding.evidence.frame)}
                  alt={"Video frame at " + timestamp(activeFinding.t)}
                />
                <figcaption>Video frame · {timestamp(activeFinding.t)}</figcaption>
              </figure>
              {activeFinding.evidence.listing_photo && (
                <figure>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={mediaPath(item.id, activeFinding.evidence.listing_photo)}
                    alt={"Listing photo of " + title}
                  />
                  <figcaption>Shop listing</figcaption>
                </figure>
              )}
            </div>
          )}
        </section>
        <section className="panel findings">
          <h2>Evidence</h2>
          <div className="evidence-timestamps" aria-label="Evidence timeline">
            {findings.length ? (
              findings.map((finding, index) => (
                <Button
                  key={finding.check + "-" + finding.t + "-" + index}
                  type="button"
                  variant="ghost"
                  aria-pressed={index === selected}
                  onClick={() => {
                    setSelected(index);
                    if (video.current) video.current.currentTime = finding.t;
                  }}
                >
                  <time className="time-code">{timestamp(finding.t)}</time>
                  <span>{finding.note}</span>
                </Button>
              ))
            ) : (
              <p className="muted-copy">No timestamped findings. Review the video directly.</p>
            )}
          </div>
          {activeFinding?.thai && <p lang="th">{activeFinding.thai}</p>}
          <hr />
          <Badge variant="secondary">{summary}</Badge>
          {verdict.display === "unsure" && verdict.leaning !== "none" && (
            <p className="muted-copy">
              Model leans toward the {verdict.leaning === "buyer" ? "buyer" : "shop"}.
            </p>
          )}
          <p>{verdict.reason.en}</p>
          <p lang="th">{verdict.reason.th}</p>
          <details className="model-details">
            <summary>Model details</summary>
            <p>Model score · {Math.round(verdict.confidence * 100)}%</p>
            <p className="muted-copy">Use the footage and listing to make your own decision.</p>
            <ul>
              {Object.entries(checkLabels).map(([key, label]) => {
                const check = verdict.checks[key];
                return (
                  check && (
                    <li key={key}>
                      <strong>
                        {label} · {check.status}
                      </strong>
                      {check.note_en && <p>{check.note_en}</p>}
                      {check.note_th && <p lang="th">{check.note_th}</p>}
                    </li>
                  )
                );
              })}
            </ul>
            <details>
              <summary>Pipeline and raw verdict</summary>
              {verdict.steps.map((step, index) => (
                <p key={step.name + index}>
                  <strong>{step.name}</strong> · {step.kind} · {step.seconds}s<br />
                  {step.output}
                </p>
              ))}
              <pre>{JSON.stringify(verdict, null, 2)}</pre>
            </details>
          </details>
        </section>
      </div>
      <section className="panel decision-panel" aria-labelledby="shop-decision">
        {item.decision ? (
          <>
            <h2 id="shop-decision" ref={savedMessage} tabIndex={-1}>
              {saved ? "Decision saved" : "Shop decision"}
            </h2>
            <p>
              <strong>{choices[item.decision.choice]}</strong>
            </p>
            {item.decision.note_for_buyer?.trim() && (
              <p className="buyer-note">{item.decision.note_for_buyer}</p>
            )}
            {(next || openingNext) && (
              <Button onClick={next} disabled={openingNext}>
                Next case <ArrowRight aria-hidden />
              </Button>
            )}
          </>
        ) : (
          <>
            <h2 id="shop-decision">Shop decision</h2>
            <form onSubmit={saveDecision}>
              <div className="decision-field">
                <label htmlFor="decision-choice">Decision</label>
                <select
                  id="decision-choice"
                  required
                  value={choice}
                  onChange={(event) => setChoice(event.target.value as Decision["choice"] | "")}
                >
                  <option value="">Choose a decision</option>
                  {(verdict.display === "clear"
                    ? ["agree", "disagree"]
                    : ["side_buyer", "side_seller"]
                  ).map((value) => (
                    <option key={value} value={value}>
                      {choices[value as Decision["choice"]]}
                    </option>
                  ))}
                </select>
              </div>
              {choice === "disagree" && (
                <div className="decision-field">
                  <label htmlFor="disagreement-reason">Reason for disagreeing</label>
                  <select
                    id="disagreement-reason"
                    required
                    value={reason ?? ""}
                    onChange={(event) => setReason(event.target.value as Decision["reason"])}
                  >
                    <option value="">Choose a reason</option>
                    {reasons.map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </select>
                </div>
              )}
              <div className="decision-field">
                <label htmlFor="buyer-explanation">Explanation for the buyer</label>
                <p id="buyer-explanation-tip" className="muted-copy">
                  Summarize what you found and tell the buyer what happens next.
                </p>
                <Textarea
                  ref={explanation}
                  id="buyer-explanation"
                  value={note}
                  aria-describedby={
                    noteError
                      ? "buyer-explanation-tip buyer-explanation-error"
                      : "buyer-explanation-tip"
                  }
                  required
                  aria-invalid={noteError}
                  onChange={(event) => {
                    setNote(event.target.value);
                    setNoteError(false);
                  }}
                />
              </div>
              {noteError && (
                <p id="buyer-explanation-error" role="alert">
                  Enter an explanation for the buyer.
                </p>
              )}
              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              <Button disabled={busy}>
                {busy ? "Saving decision…" : "Save decision"} <CircleCheck aria-hidden />
              </Button>
            </form>
          </>
        )}
      </section>
    </>
  );
}
