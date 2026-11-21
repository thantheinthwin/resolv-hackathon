import { DatabaseSync } from "node:sqlite";
import type { Case } from "./models";

// Each connection replays stored events before following the active job.
export function caseEvents(open: () => DatabaseSync, id: string, signal: AbortSignal) {
  let dispose = () => {};
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      let sent = 0,
        closed = false;
      controller.enqueue(new TextEncoder().encode(": connected\n\n"));
      const timer = setInterval(send, 150);
      function cleanup() {
        clearInterval(timer);
        signal.removeEventListener("abort", close);
        closed = true;
      }
      function close() {
        if (!closed) {
          cleanup();
          controller.close();
        }
      }
      function send() {
        if (closed) return;
        const db = open();
        try {
          const row = db.prepare("SELECT value FROM records WHERE kind='case' AND id=?").get(id);
          if (!row) {
            close();
            return;
          }
          const c: Case = JSON.parse(String(row.value));
          const events = c.progress ?? [];
          while (sent < events.length) {
            const e = events[sent++];
            controller.enqueue(
              new TextEncoder().encode(
                "event: " + e.event + "\ndata: " + JSON.stringify(e) + "\n\n",
              ),
            );
          }
          if (["ready", "decided", "failed"].includes(c.status)) {
            if (!events.some((e) => e.event === "done"))
              controller.enqueue(
                new TextEncoder().encode('event: done\ndata: {"event":"done"}\n\n'),
              );
            close();
          }
        } finally {
          db.close();
        }
      }
      dispose = cleanup;
      signal.addEventListener("abort", close, { once: true });
      if (signal.aborted) close();
      else send();
    },
    cancel() {
      dispose();
    },
  });
  return new Response(body, {
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
  });
}
