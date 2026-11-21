"use client";

import { ArrowRight, Video } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/ui/button";
import { Progress } from "../components/ui/progress";
import { Alert, AlertDescription } from "../components/ui/alert";
import type { UploadResult } from "../lib/models";

export function Uploader({
  getEndpoint,
  onDone,
  onSending,
  blocked = false,
  sendLabel = "Send video",
}: {
  getEndpoint: () => string | Promise<string>;
  onDone: (result: UploadResult) => void;
  onSending?: (sending: boolean) => void;
  blocked?: boolean;
  sendLabel?: string;
}) {
  const picker = useRef<HTMLInputElement>(null);
  const uploading = useRef(false);
  const [selection, setSelection] = useState<{ file: File; url: string }>();
  const [previewFailed, setPreviewFailed] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const previewUrl = selection?.url;

  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  function selectFile(file: File) {
    setError(file.size > 50_000_000 ? "Choose a video up to 50 MB." : "");
    setPreviewFailed(false);
    setSelection({ file, url: URL.createObjectURL(file) });
  }

  async function upload() {
    if (!selection || uploading.current || blocked || selection.file.size > 50_000_000) return;
    uploading.current = true;
    onSending?.(true);
    setError("");
    setProgress(0);

    function finish(message = "") {
      uploading.current = false;
      setProgress(null);
      setError(message);
      onSending?.(false);
    }

    try {
      const endpoint = await getEndpoint();
      const form = new FormData();
      form.append("video", selection.file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/" + endpoint);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) setProgress(Math.round((event.loaded / event.total) * 100));
      };
      xhr.onerror = () => finish("Upload interrupted. Try sending your video again.");
      xhr.onload = () => {
        let body;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          // A proxy may return a non-JSON error.
        }
        if (xhr.status >= 200 && xhr.status < 300 && body?.id && body.status === "checking") {
          finish();
          onDone(body);
        } else {
          finish(typeof body?.detail === "string" ? body.detail : "Upload failed. Try again.");
        }
      };
      xhr.send(form);
    } catch (error) {
      finish(error instanceof Error ? error.message : "Could not start the upload. Try again.");
    }
  }

  const disabled = progress !== null || blocked;
  return (
    <section className="panel upload-card" aria-label="Unboxing video">
      <input
        ref={picker}
        type="file"
        accept="video/*"
        className="sr-only"
        tabIndex={-1}
        aria-label="Unboxing video"
        disabled={disabled}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) selectFile(file);
          event.target.value = "";
        }}
      />
      {selection && !previewFailed && (
        <video
          className="evidence-video"
          src={selection.url}
          controls
          playsInline
          preload="metadata"
          aria-label="Selected video preview"
          onError={() => setPreviewFailed(true)}
        />
      )}
      {selection ? (
        <div className="video-file">
          <strong>{selection.file.name}</strong>
          <small>{(selection.file.size / 1_000_000).toFixed(1)} MB</small>
          {previewFailed && (
            <p className="muted-copy">
              Your browser can’t preview this file. You can still try uploading it.
            </p>
          )}
        </div>
      ) : (
        <>
          <h2>Choose an unboxing video</h2>
          <p className="muted-copy">Pick a clip from your device.</p>
        </>
      )}
      <p className="limit-copy">5 seconds to 2 minutes · Up to 50 MB</p>
      {progress !== null && (
        <div className="upload-progress">
          <Progress aria-label="Upload progress" value={progress} max={100} />
          <p role="status">{progress === 100 ? "Checking video…" : progress + "% uploaded"}</p>
        </div>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="action-row">
        <Button
          type="button"
          variant={selection ? "outline" : "default"}
          disabled={disabled}
          onClick={() => picker.current?.click()}
        >
          <Video aria-hidden /> {selection ? "Replace video" : "Choose video"}
        </Button>
        {selection && (
          <Button
            type="button"
            disabled={disabled || selection.file.size > 50_000_000}
            onClick={upload}
          >
            {sendLabel} <ArrowRight aria-hidden />
          </Button>
        )}
      </div>
    </section>
  );
}
