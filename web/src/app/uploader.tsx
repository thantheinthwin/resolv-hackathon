"use client";

import { ArrowRight, FileVideo, Video } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "../components/ui/button";
import { Progress } from "../components/ui/progress";
import { Alert, AlertDescription } from "../components/ui/alert";
import type { UploadResult } from "../lib/models";
import styles from "./uploader.module.css";

const maxVideoBytes = 50_000_000;
const ambiguousVideoTypes = ["", "application/octet-stream", "application/mp4", "application/mxf"];

export function Uploader({
  getEndpoint,
  onDone,
  onSending,
  blocked = false,
  sendLabel = "Send video",
  sendActionTarget,
}: {
  getEndpoint: () => string | Promise<string>;
  onDone: (result: UploadResult) => void;
  onSending?: (sending: boolean) => void;
  blocked?: boolean;
  sendLabel?: string;
  sendActionTarget?: HTMLElement | null;
}) {
  const picker = useRef<HTMLInputElement>(null);
  const replace = useRef<HTMLButtonElement>(null);
  const uploading = useRef(false);
  const dragDepth = useRef(0);
  const limitsId = useId();
  const [selection, setSelection] = useState<{ file: File; url: string }>();
  const [previewFailed, setPreviewFailed] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const previewUrl = selection?.url;

  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  function selectFiles(files: FileList, fromPicker = false) {
    if (uploading.current || blocked) return;
    if (files.length !== 1) {
      if (files.length > 1) setError("Choose one video at a time.");
      return;
    }
    const file = files[0];
    if (!file.type.startsWith("video/") && !ambiguousVideoTypes.includes(file.type)) {
      setError("Choose a video file.");
      return;
    }
    if (file.size > maxVideoBytes) {
      setError("Choose a video up to 50 MB.");
      return;
    }
    setError("");
    setPreviewFailed(false);
    setSelection({ file, url: URL.createObjectURL(file) });
    if (fromPicker && !selection) requestAnimationFrame(() => replace.current?.focus());
  }

  async function upload() {
    if (!selection || uploading.current || blocked) return;
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
  const sendAction = selection && (
    <Button type="button" disabled={disabled} onClick={upload}>
      {sendLabel} <ArrowRight aria-hidden />
    </Button>
  );
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
          if (event.target.files) selectFiles(event.target.files, true);
          event.target.value = "";
        }}
      />
      <div
        className={styles.mediaSurface}
        data-upload-dropzone=""
        data-dragging={dragging && !disabled}
        onDragEnter={(event) => {
          if (!event.dataTransfer.types.includes("Files")) return;
          event.preventDefault();
          dragDepth.current += 1;
          if (!disabled) setDragging(true);
        }}
        onDragOver={(event) => {
          if (!event.dataTransfer.types.includes("Files")) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = disabled ? "none" : "copy";
        }}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (!dragDepth.current) setDragging(false);
        }}
        onDrop={(event) => {
          const { files, types } = event.dataTransfer;
          if (!files.length && !types.includes("Files")) return;
          event.preventDefault();
          dragDepth.current = 0;
          setDragging(false);
          selectFiles(files);
        }}
      >
        {selection ? (
          previewFailed ? (
            <div className={styles.previewFallback}>
              <FileVideo size={24} aria-hidden />
              <p>Your browser can’t preview this file. You can still try uploading it.</p>
            </div>
          ) : (
            <video
              key={selection.url}
              className={styles.preview}
              src={selection.url}
              controls
              playsInline
              preload="metadata"
              aria-label="Selected video preview"
              onError={() => setPreviewFailed(true)}
            />
          )
        ) : (
          <button
            type="button"
            className={styles.pickSurface}
            aria-label="Choose video"
            aria-describedby={limitsId}
            disabled={disabled}
            onClick={() => picker.current?.click()}
          >
            <Video size={24} aria-hidden />
            <span className={styles.dropHint}>Drop your video here</span>
            <span className={styles.pickLabel}>Choose video</span>
          </button>
        )}
        {dragging && !disabled && (
          <div className={styles.dropFeedback} aria-hidden>
            <Video size={24} />
            Drop to select video
          </div>
        )}
      </div>
      {selection ? (
        <div className={styles.fileDetails}>
          <strong>{selection.file.name}</strong>
          <small>{(selection.file.size / 1_000_000).toFixed(1)} MB</small>
        </div>
      ) : null}
      <p id={limitsId} className="limit-copy">
        5 seconds to 2 minutes · Up to 50 MB
      </p>
      {selection && (
        <div className="action-row">
          <Button
            ref={replace}
            type="button"
            variant="outline"
            disabled={disabled}
            onClick={() => picker.current?.click()}
          >
            <Video aria-hidden /> Replace video
          </Button>
          {sendActionTarget === undefined && sendAction}
        </div>
      )}
      {sendActionTarget && sendAction && createPortal(sendAction, sendActionTarget)}
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
    </section>
  );
}
