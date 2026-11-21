import { DatabaseSync } from "node:sqlite";
import { randomUUID } from "node:crypto";
import { caseEvents } from "./sample-events";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { readFile, writeFile, unlink } from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import {
  type CaseReference,
  type Claim,
  type Listing,
  type Order,
  type Report,
  type ShopCase,
  claims,
  reasons,
} from "./models";
const exec = promisify(execFile);
const root = path.resolve(process.cwd(), ".."),
  dir = process.env.SAMPLE_DATA_DIR || path.join(root, "data/web-sample");
function worker(operation: string, value: string) {
  return exec(
    path.join(root, ".venv/bin/python"),
    [path.join(root, "web/scripts/sample_worker.py"), operation, value],
    { cwd: root, env: { ...process.env, PYTHONPATH: root }, timeout: 120000 },
  );
}
function database() {
  mkdirSync(dir, { recursive: true });
  const db = new DatabaseSync(path.join(dir, "sample.sqlite"));
  db.exec(
    "CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT, value TEXT); CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY, id TEXT)",
  );
  db.exec("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, expires INTEGER NOT NULL)");
  // Recover abandoned reservations even when the next request is a read or SSE reconnect.
  db.exec("BEGIN IMMEDIATE");
  try {
    db.prepare("DELETE FROM jobs WHERE expires<=?").run(Date.now());
    db.exec(`UPDATE records SET value=json_set(value,'$.status','failed',
      '$.progress',json_insert(COALESCE(json_extract(value,'$.progress'),'[]'),'$[#]',json_object('event','done')))
      WHERE kind='case' AND json_extract(value,'$.status')='checking'
      AND NOT EXISTS (SELECT 1 FROM jobs WHERE jobs.id=records.id)`);
    db.exec("COMMIT");
  } catch (e) {
    db.exec("ROLLBACK");
    db.close();
    throw e;
  }
  return db;
}
const seed: Listing = {
  id: "LS-101",
  title: "Everyday cotton tee",
  description: "Crew-neck cotton tee.",
  price: 390,
  colors: ["Midnight Black"],
  sizes: ["M", "L"],
  box_contents: ["Cotton tee"],
  photos: ["/api/files/listings/sample/tee.png"],
};
const orders: Order[] = [
  {
    id: "UJ-48213",
    listing_id: seed.id,
    listing: seed,
    variant: { color: "Midnight Black", size: "M" },
    quantity: 1,
    buyer_name: "Demo buyer",
    delivered_at: "2026-11-20T00:00:00Z",
  },
];
const reply = (value: unknown, status = 200) => Response.json(value, { status });
const fail = (detail: string, status = 422) => reply({ detail }, status);
const buyerStatus: Record<ShopCase["status"], Report["status"]> = {
  awaiting_video: "sent",
  checking: "checking",
  ready: "with_shop",
  decided: "replied",
  failed: "failed",
};

export async function sample(req: Request, parts: string[]) {
  const db = database();
  let reservedJob: string | undefined;
  const [area, key, action] = parts;
  const get = (id: string) => {
    const row = db.prepare("SELECT value FROM records WHERE id=?").get(id);
    return row ? JSON.parse(String(row.value)) : undefined;
  };
  const save = (id: string, kind: string, value: unknown) =>
    db.prepare("INSERT OR REPLACE INTO records VALUES(?,?,?)").run(id, kind, JSON.stringify(value));
  const rows = (kind: string) =>
    db
      .prepare("SELECT value FROM records WHERE kind=? ORDER BY rowid DESC")
      .all(kind)
      .map((r) => JSON.parse(String(r.value)));
  const listingById = (id: string): Listing | undefined => {
    if (id === seed.id) return seed;
    const row = db.prepare("SELECT value FROM records WHERE kind='listing' AND id=?").get(id);
    return row ? JSON.parse(String(row.value)) : undefined;
  };
  const listingFor = (c: ShopCase) =>
    c.listing_id ? listingById(c.listing_id) : orders.find((o) => o.id === c.order_id)?.listing;
  const buyer = (c: ShopCase): Report => ({
    id: c.id,
    status: buyerStatus[c.status],
    note_for_buyer: c.decision?.note_for_buyer ?? null,
    product: listingFor(c)?.title,
    claim_type: c.claim_type,
  });
  try {
    if (area === "orders") return reply(orders);
    if (area === "my")
      return reply(
        (rows("case") as ShopCase[])
          .filter((c) => c.status !== "awaiting_video")
          .sort((a, b) => b.created_at.localeCompare(a.created_at))
          .map(buyer),
      );
    if (parts.join("/") === "files/listings/sample/tee.png")
      return new Response(new Uint8Array(await readFile(path.join(root, "api/fixtures/tee.png"))), {
        headers: { "Content-Type": "image/png" },
      });
    if (area === "files") {
      const meta = get(key);
      if (!meta || !meta.mime) return fail("File unavailable", 404);
      const bytes = new Uint8Array(await readFile(path.join(dir, key)));
      const headers = new Headers({
        "Content-Type": meta.mime,
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
      });
      const range = req.headers.get("range");
      if (range) {
        const match = /^bytes=(\d+)-(\d*)$/.exec(range);
        const start = Number(match?.[1]),
          end = match?.[2] ? Math.min(Number(match[2]), bytes.length - 1) : bytes.length - 1;
        if (!match || start > end || start >= bytes.length)
          return new Response(null, {
            status: 416,
            headers: { "Content-Range": "bytes */" + bytes.length },
          });
        headers.set("Content-Range", "bytes " + start + "-" + end + "/" + bytes.length);
        headers.set("Content-Length", String(end - start + 1));
        return new Response(bytes.slice(start, end + 1), { status: 206, headers });
      }
      headers.set("Content-Length", String(bytes.length));
      return new Response(bytes, { headers });
    }
    if (area === "listings") {
      if (req.method === "GET") return reply([seed, ...rows("listing")]);
      const f = await req.formData(),
        photos = f.getAll("photos");
      if (
        !String(f.get("title") || "").trim() ||
        !photos.length ||
        photos.length > 3 ||
        String(f.get("description") || "").length > 1500
      )
        return fail("Check the product name, description and photos.");
      const urls = [];
      if (
        !photos.every(
          (p): p is File =>
            p instanceof File && ["image/jpeg", "image/png", "image/webp"].includes(p.type),
        )
      )
        return fail("Use JPEG, PNG or WebP photos.");
      for (const p of photos) {
        const id = randomUUID();
        await writeFile(path.join(dir, id), Buffer.from(await p.arrayBuffer()));
        save(id, "file", { mime: p.type });
        urls.push("/api/files/" + id);
      }
      const listing = {
        ...Object.fromEntries(f),
        id: randomUUID(),
        photos: urls,
        price: Number(f.get("price")),
        colors: f.getAll("colors"),
        sizes: f.getAll("sizes"),
        box_contents: f.getAll("box_contents"),
      };
      save(listing.id, "listing", listing);
      return reply(listing, 201);
    }
    if (area === "shop" && !action)
      return reply(
        (rows("case") as ShopCase[]).map((c) => ({
          id: c.id,
          order_id: c.order_id,
          listing_id: c.listing_id,
          product: listingFor(c)?.title ?? "Unknown product",
          claim_type: c.claim_type,
          status: c.status,
          created_at: c.created_at,
          verdict: c.verdict?.verdict ?? null,
          display: c.verdict?.display ?? null,
          confidence: c.verdict?.confidence ?? null,
        })),
      );
    if (area === "cases" && !key) {
      const b = await req.json().catch(() => null);
      if (!b || typeof b.claim_type !== "string" || !Object.hasOwn(claims, b.claim_type))
        return fail("Choose a claim.");
      const order = b.listing_id === undefined && orders.find((o) => o.id === b.order_id);
      const listing =
        b.order_id === undefined && typeof b.listing_id === "string" && listingById(b.listing_id);
      const source: CaseReference | undefined = order
        ? { order_id: order.id }
        : listing
          ? { listing_id: listing.id }
          : undefined;
      if (!source) return fail("Choose a delivered order or an available product.");
      const c: ShopCase = {
        ...source,
        id: randomUUID(),
        claim_type: b.claim_type as Claim,
        description: typeof b.description === "string" ? b.description : "",
        status: "awaiting_video",
        created_at: new Date().toISOString(),
      };
      save(c.id, "case", c);
      return reply({ id: c.id, status: c.status }, 201);
    }
    const token =
      area === "uploads" ? db.prepare("SELECT id FROM tokens WHERE token=?").get(key) : null;
    const id = area === "shop" ? action : area === "uploads" ? String(token?.id || "") : key;
    const record = db.prepare("SELECT value FROM records WHERE kind='case' AND id=?").get(id);
    const c: ShopCase | undefined = record ? JSON.parse(String(record.value)) : undefined;
    if (!c) return fail("This case or upload link is unavailable.", 404);
    if (req.method === "DELETE") {
      const draft = new URL(req.url).searchParams.get("draft")?.toLowerCase();
      const onlyDraft = draft !== undefined && ["1", "on", "t", "true", "y", "yes"].includes(draft);
      if (
        draft !== undefined &&
        !onlyDraft &&
        !["0", "off", "f", "false", "n", "no"].includes(draft)
      )
        return fail("Use a boolean value for draft.");
      db.exec("BEGIN IMMEDIATE");
      try {
        const latest = get(id) as ShopCase | undefined;
        if (!latest) {
          db.exec("ROLLBACK");
          return fail("Case unavailable", 404);
        }
        if (onlyDraft && latest.status !== "awaiting_video") {
          db.exec("ROLLBACK");
          return fail("The video has already been received.", 409);
        }
        const file = latest.video_url?.match(/^\/api\/files\/([a-f0-9-]{36})$/)?.[1];
        if (file) {
          rmSync(path.join(dir, file), { force: true });
          db.prepare("DELETE FROM records WHERE kind='file' AND id=?").run(file);
        }
        rmSync(path.join(dir, id), { force: true, recursive: true });
        db.prepare("DELETE FROM tokens WHERE id=?").run(id);
        db.prepare("DELETE FROM records WHERE id=? AND kind='case'").run(id);
        db.exec("COMMIT");
        return new Response(null, { status: 204 });
      } catch (e) {
        db.exec("ROLLBACK");
        throw e;
      }
    }
    if (area === "shop") {
      if (req.method === "GET") return reply(c);
      const d = await req.json();
      if (c.status !== "ready") return fail("This case is not awaiting a decision.", 409);
      if (
        !(
          c.verdict?.display === "clear" ? ["agree", "disagree"] : ["side_buyer", "side_seller"]
        ).includes(d.choice) ||
        (d.choice === "disagree" && !reasons.includes(d.reason))
      )
        return fail("Choose a valid decision and reason.");
      c.decision = d;
      c.status = "decided";
      const changed = db
        .prepare(
          "UPDATE records SET value=? WHERE id=? AND kind='case' AND json_extract(value,'$.status')='ready'",
        )
        .run(JSON.stringify(c), id);
      return changed.changes ? reply(c) : fail("This case is not awaiting a decision.", 409);
    }
    if (action === "events") return caseEvents(database, id, req.signal);
    if (action === "upload-link") {
      if (c.status !== "awaiting_video") return fail("Video already received", 409);
      const t = randomUUID();
      db.prepare("INSERT INTO tokens VALUES(?,?)").run(t, id);
      return reply({ token: t, url: "/upload/" + t });
    }
    if (action === "video" || area === "uploads") {
      if (c.status !== "awaiting_video") return fail("Video already received.", 409);
      db.exec("BEGIN IMMEDIATE");
      try {
        const now = Date.now();

        if (db.prepare("SELECT id FROM jobs WHERE id=?").get(id)) {
          db.exec("ROLLBACK");
          return fail("Video is already being processed.", 409);
        }
        if (Number(db.prepare("SELECT COUNT(*) AS count FROM jobs").get()?.count) >= 2) {
          db.exec("ROLLBACK");
          return fail("Two videos are being processed. Please retry.", 429);
        }
        // Both subprocesses have a two-minute timeout; allow their combined duration plus cleanup.
        db.prepare("INSERT INTO jobs VALUES(?,?)").run(id, now + 300000);
        reservedJob = id;
        db.exec("COMMIT");
      } catch (e) {
        db.exec("ROLLBACK");
        throw e;
      }
      const f = await req.formData(),
        v = f.get("video") ?? f.get("file");
      if (!(v instanceof File) || v.size > 50000000) return fail("Choose a video up to 50 MB.");
      const file = randomUUID(),
        location = path.join(dir, file);
      await writeFile(location, Buffer.from(await v.arrayBuffer()));
      const rejectFile = async (detail: string, status = 422) => {
        await unlink(location);
        return fail(detail, status);
      };
      let duration: number;
      try {
        const { stdout } = await exec(
          "ffprobe",
          [
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            "mov,matroska,webm,avi,mpeg,mpegts",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type:format=duration",
            "-of",
            "json",
            location,
          ],
          { timeout: 8000 },
        );
        const info = JSON.parse(stdout);
        duration = Number(info.format.duration);
        if (!info.streams.length || !Number.isFinite(duration)) throw Error();
      } catch {
        return rejectFile("Choose a readable video.");
      }
      if (duration < 5 || duration > 120)
        return rejectFile("Video must be between 5 seconds and 2 minutes.");
      let intake: { warnings?: string[]; error?: string };
      try {
        intake = JSON.parse((await worker("inspect", location)).stdout);
      } catch {
        return rejectFile("Video intake is unavailable. Please retry.", 503);
      }
      if (intake.error) return rejectFile(intake.error);
      db.exec("BEGIN IMMEDIATE");
      try {
        if (get(id)?.status !== "awaiting_video") {
          db.exec("ROLLBACK");
          return rejectFile("Case unavailable or video already received.", 409);
        }
        c.status = "checking";
        c.video_url = "/api/files/" + file;
        c.progress = [{ event: "started", step: "scaffold" }];
        save(file, "file", { mime: v.type.startsWith("video/") ? v.type : "video/mp4" });
        save(id, "case", c);
        db.prepare("DELETE FROM tokens WHERE id=?").run(id);
        db.exec("COMMIT");
      } catch (e) {
        db.exec("ROLLBACK");
        await unlink(location);
        throw e;
      }
      reservedJob = undefined; // The judge completion releases this slot.
      worker("judge", id)
        .then(({ stdout }) => {
          c.verdict = JSON.parse(stdout);
          c.status = "ready";
          c.progress?.push({ event: "finished", step: "scaffold" });
        })
        .catch(() => {
          c.status = "failed";
        })
        .finally(() => {
          c.progress?.push({ event: "done", step: null });
          const done = database();
          try {
            done.exec("BEGIN IMMEDIATE");
            const changed = done
              .prepare(
                "UPDATE records SET value=? WHERE id=? AND kind='case' AND json_extract(value,'$.status')='checking'",
              )
              .run(JSON.stringify(c), id);
            if (changed.changes && c.verdict) {
              mkdirSync(path.join(dir, id), { recursive: true });
              writeFileSync(path.join(dir, id, "verdict.json"), JSON.stringify(c.verdict));
            }
            done.exec("COMMIT");
          } finally {
            done.prepare("DELETE FROM jobs WHERE id=?").run(id);
            done.close();
          }
        });
      return reply({ id, status: "checking", warnings: intake.warnings ?? [] }, 202);
    }
    return reply({
      ...buyer(c),
      description: c.description,
      created_at: c.created_at,
      order_id: c.order_id,
      listing_id: c.listing_id,
      video_url: c.video_url ?? null,
    });
  } finally {
    if (reservedJob) db.prepare("DELETE FROM jobs WHERE id=?").run(reservedJob);
    db.close();
  }
}
