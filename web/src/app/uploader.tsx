"use client";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Progress } from "../components/ui/progress";
import { Alert, AlertDescription } from "../components/ui/alert";
import { useState } from "react";
export function Uploader({
  endpoint,
  onDone,
}: {
  endpoint: string;
  onDone: (warning: string) => void;
}) {
  const [file, pick] = useState<File>(),
    [progress, setProgress] = useState<number | null>(null),
    [error, setError] = useState("");
  function upload() {
    if (!file) return;
    setError("");
    if (file.size > 50000000) {
      setError("Choose a video up to 50 MB.");
      return;
    }
    const form = new FormData();
    form.append("video", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/" + endpoint);
    setProgress(0);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onerror = () => {
      setProgress(null);
      setError("Upload interrupted. Please retry.");
    };
    xhr.onload = () => {
      setProgress(null);
      let body;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {}
      if (xhr.status >= 200 && xhr.status < 300)
        onDone(body?.warning || body?.warnings?.join(" ") || "");
      else
        setError(typeof body?.detail === "string" ? body.detail : "Upload failed. Please retry.");
    };
    xhr.send(form);
  }
  return (
    <section className="panel">
      <label>
        Unboxing video
        <Input
          type="file"
          accept="video/*"
          disabled={progress !== null}
          onChange={(e) => pick(e.target.files?.[0])}
        />
      </label>
      <small>5 seconds – 2 minutes · Up to 50 MB</small>
      {progress !== null && <Progress aria-label="Upload progress" value={progress} max={100} />}
      <Button disabled={!file || progress !== null} onClick={upload}>
        {progress === null ? "Send video" : progress + "% uploaded"}
      </Button>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </section>
  );
}
