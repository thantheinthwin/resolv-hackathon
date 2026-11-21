"use client";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Alert, AlertDescription } from "../components/ui/alert";
import { useRef, useState } from "react";
import { Case, reasons, claims } from "../lib/models";
import { api, ApiError } from "../lib/client";
export function Review({
  item: c,
  title,
  saved,
  reload,
}: {
  item: Case;
  title: string;
  saved: () => void;
  reload: () => Promise<void>;
}) {
  const v = c.verdict,
    video = useRef<HTMLVideoElement>(null),
    [choice, choose] = useState(""),
    [reason, setReason] = useState(""),
    [note, setNote] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  if (!v) return <p>Waiting for the shop review.</p>;
  const seek = (t: number) => {
    if (video.current) video.current.currentTime = t;
  };
  const file = (f: string) =>
    f.startsWith("/api/files/")
      ? f
      : "/api/files/" +
        (f.startsWith("cases/")
          ? f
          : "cases/" + encodeURIComponent(c.id) + "/" + f.replace(/^\/+/, ""));
  return (
    <>
      <h1>Case review.</h1>
      <div className="context">
        <section>
          <small>Ordered</small>
          <h3>{title}</h3>
          {c.order_id}
        </section>
        <section>
          <small>Buyer said</small>
          <h3>{claims[c.claim_type as keyof typeof claims]}</h3>
          {c.description}
        </section>
      </div>
      <div className="review">
        <section className="panel">
          <small>
            {v.display} · {Math.round(v.confidence * 100)}% confidence
          </small>
          <h2>
            {v.display === "unsure"
              ? "Unsure: check the video"
              : v.verdict === "buyer_right"
                ? "Buyer is right"
                : "Seller is right"}
          </h2>
          <p>Leaning: {v.leaning}</p>
          <p>{v.reason.en}</p>
          <p lang="th">{v.reason.th}</p>
          <meter min={0} max={1} low={0.9} value={v.confidence} />
          {Object.entries({
            seal: "Parcel seal",
            listing: "Listing match",
            damage: "Product damage",
            continuity: "Video continuity",
          }).map(([k, name]) => (
            <p key={k}>
              {name} <b>{v.checks[k]?.status}</b>
              {v.checks[k]?.note_en && <span className="block">{v.checks[k].note_en}</span>}
              {v.checks[k]?.note_th && (
                <span className="block" lang="th">
                  {v.checks[k].note_th}
                </span>
              )}
            </p>
          ))}
          {c.decision ? (
            <div>
              <p>Decision saved</p>
              <p>
                {c.decision.choice.replaceAll("_", " ")} · {c.decision.note_for_buyer}
              </p>
            </div>
          ) : (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                try {
                  await api("shop/cases/" + c.id + "/decision", {
                    choice,
                    reason: choice === "disagree" ? reason : undefined,
                    note_for_buyer: note,
                  });
                  saved();
                } catch (e) {
                  if (e instanceof ApiError && e.status === 409) {
                    try {
                      await reload();
                    } catch (refreshError) {
                      setError(String(refreshError));
                    }
                  } else setError(String(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              <label>
                Decision
                <select required value={choice} onChange={(e) => choose(e.target.value)}>
                  <option value="">Choose decision</option>
                  {(v.display === "clear"
                    ? [
                        ["agree", "Agree"],
                        ["disagree", "Disagree"],
                      ]
                    : [
                        ["side_buyer", "Side with buyer"],
                        ["side_seller", "Side with seller"],
                      ]
                  ).map(([k, n]) => (
                    <option key={k} value={k}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              {choice === "disagree" && (
                <label>
                  Reason
                  <select required value={reason} onChange={(e) => setReason(e.target.value)}>
                    <option value="">Choose reason</option>
                    {reasons.map((r) => (
                      <option key={r}>{r}</option>
                    ))}
                  </select>
                </label>
              )}
              <label>
                Note for buyer
                <Textarea value={note} onChange={(e) => setNote(e.target.value)} />
              </label>
              <Button disabled={busy}>Save decision</Button>
              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
            </form>
          )}
        </section>
        <section className="panel">
          <h2>Video evidence.</h2>
          <video controls ref={video} src={c.video_url ?? undefined} />
          <div aria-label="Evidence timeline">
            {v.evidence.map((e, i) => (
              <Button key={i} onClick={() => seek(e.t)}>
                {e.t}s · {e.check}
              </Button>
            ))}
          </div>
          {v.evidence.map((e, i) => (
            <figure key={i}>
              <img src={file(e.frame)} alt={"Evidence at " + e.t + " seconds"} />
              {e.listing_photo && <img src={file(e.listing_photo)} alt="Comparison" />}
              <figcaption>
                {e.result} · {e.t}s
              </figcaption>
            </figure>
          ))}
          {Object.entries(v.checks).flatMap(([k, check]) =>
            check.findings.map((f, i) => (
              <p key={k + i}>
                <Button onClick={() => seek(f.t)}>{f.t}s</Button> {f.note_en}{" "}
                <span lang="th">{f.note_th}</span>
              </p>
            )),
          )}
          {!v.evidence.length && <p>No timestamped findings in this verdict.</p>}
        </section>
        <aside className="panel">
          <h2>Under the hood.</h2>
          {v.steps.map((s, i) => (
            <p key={i}>
              <small>
                {s.kind} · {s.seconds}s
              </small>
              <strong>{s.name}</strong>
              {s.output}
            </p>
          ))}
          <details>
            <summary>Raw verdict</summary>
            <pre>{JSON.stringify(v, null, 2)}</pre>
          </details>
        </aside>
      </div>
    </>
  );
}
