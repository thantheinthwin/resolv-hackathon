"use client";

import { useEffect, useState } from "react";
import { Button } from "../components/ui/button";
import { api } from "../lib/client";
import { claims, type ReportDetails } from "../lib/models";

export function ReportEvidence({ id }: { id: string }) {
  const [details, setDetails] = useState<ReportDetails>();
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [videoFailed, setVideoFailed] = useState(false);

  useEffect(() => {
    let active = true;
    api<ReportDetails>("cases/" + encodeURIComponent(id)).then(
      (report) => {
        if (active) setDetails(report);
      },
      () => {
        if (active) setError(true);
      },
    );
    return () => {
      active = false;
    };
  }, [id, retry]);

  if (error)
    return (
      <div className="report-evidence action-row" role="status">
        Couldn’t load this report’s details.
        <Button
          variant="outline"
          onClick={() => {
            setError(false);
            setRetry((value) => value + 1);
          }}
        >
          Try again
        </Button>
      </div>
    );
  if (!details) return <p role="status">Loading report details…</p>;

  return (
    <div className="report-evidence">
      <dl>
        <div>
          <dt>{details.order_id ? "Order" : "Product reference"}</dt>
          <dd>{details.order_id ?? details.listing_id?.slice(0, 8) ?? "Unavailable"}</dd>
        </div>
        {details.claim_type && (
          <div>
            <dt>Claim</dt>
            <dd>{claims[details.claim_type]}</dd>
          </div>
        )}
        {details.created_at && (
          <div>
            <dt>Submitted</dt>
            <dd>
              <time dateTime={details.created_at}>
                {new Date(details.created_at).toLocaleDateString()}
              </time>
            </dd>
          </div>
        )}
        <div>
          <dt>Your description</dt>
          <dd className="report-description">
            {details.description?.trim() || "No description added."}
          </dd>
        </div>
      </dl>
      <p>
        <strong>Original video</strong>
      </p>
      {details.video_url && !videoFailed ? (
        <video
          className="evidence-video"
          src={details.video_url}
          aria-label="Your unboxing video"
          controls
          playsInline
          preload="metadata"
          onError={() => setVideoFailed(true)}
        />
      ) : (
        <p className="muted-copy">The original video is unavailable.</p>
      )}
    </div>
  );
}
