"use client";
import { useState, useEffect, useEffectEvent } from "react";
export function CheckProgress({ id, onDone }: { id: string; onDone: () => void }) {
  const [step, setStep] = useState("Being checked");
  const complete = useEffectEvent(onDone);
  useEffect(() => {
    const stream = new EventSource("/api/cases/" + encodeURIComponent(id) + "/events");
    function update(e: MessageEvent) {
      try {
        const data = JSON.parse(e.data);
        if (typeof data.step === "string") setStep(data.step);
      } catch {
        /* Resume on the next event. */
      }
    }
    stream.onmessage = update;
    for (const name of ["started", "finished"]) stream.addEventListener(name, update);
    stream.addEventListener("done", () => {
      stream.close();
      complete();
    });
    return () => stream.close();
  }, [id]);
  return <span aria-live="polite">{step}</span>;
}
