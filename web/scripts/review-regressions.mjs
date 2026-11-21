import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { DatabaseSync } from "node:sqlite";
import { chromium } from "playwright";

const base = process.env.REHEARSAL_URL,
  dir = process.env.REHEARSAL_DIR,
  store = process.env.SAMPLE_DATA_DIR;
assert(base && dir && store, "Set isolated rehearsal URL, media and sample store directories");
const api = (p, opts) => fetch(base + "/api/" + p, opts);
const json = (p, body) =>
  api(p, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
const create = async () => {
  const r = await json("cases", {
    order_id: "UJ-48213",
    claim_type: "wrong_item",
    description: "Regression fixture",
  });
  assert.equal(r.status, 201);
  return (await r.json()).id;
};
const del = (id) => api("cases/" + id, { method: "DELETE" });
const upload = async (id, bytes) => {
  const form = new FormData();
  form.append("video", new Blob([bytes], { type: "video/mp4" }), "clip.mp4");
  return api("cases/" + id + "/video", { method: "POST", body: form });
};
function clip(color, seconds) {
  const file = join(dir, color + seconds + ".mp4");
  execFileSync("ffmpeg", [
    "-loglevel",
    "error",
    "-f",
    "lavfi",
    "-i",
    "color=c=" + color + ":s=64x64:r=1",
    "-t",
    String(seconds),
    "-c:v",
    "libx264",
    "-y",
    file,
  ]);
  return readFileSync(file);
}
const old = await create(),
  token = (await (await json("cases/" + old + "/upload-link", {})).json()).token;
assert.equal((await del(old)).status, 204);
assert.equal((await api("uploads/" + token, { method: "POST" })).status, 404);
const id = await create();
assert.equal((await api("cases/" + id + "/events")).status, 409);
assert.equal(
  (
    await api("cases/" + id + "/video", {
      method: "POST",
      headers: { "Content-Type": "multipart/form-data; boundary=fixture" },
      body: "incomplete multipart",
    })
  ).status,
  422,
);
const listingsBefore = (await (await api("listings")).json()).length;
for (const [price, photo] of [
  ["Infinity", readFileSync(join(dir, "screen-01.png"))],
  ["50", Buffer.from("not a PNG")],
  ["50", Buffer.alloc(10_000_001)],
]) {
  const listing = new FormData();
  listing.set("title", "Rejected product");
  listing.set("price", price);
  listing.set("photos", new Blob([photo], { type: "image/png" }), "photo.png");
  assert.equal((await api("listings", { method: "POST", body: listing })).status, 422);
}
assert.equal((await (await api("listings")).json()).length, listingsBefore);
const dark = clip("black", 6),
  bright = clip("white", 5);
for (const bytes of [
  Buffer.from("invalid"),
  clip("white", 4),
  clip("white", 121),
  Buffer.alloc(50000001),
])
  assert.equal((await upload(id, bytes)).status, 422);
const damaged = Buffer.from(bright); // Preserve the container metadata but corrupt the coded samples.
const mdat = damaged.indexOf("mdat");
const end = mdat - 4 + damaged.readUInt32BE(mdat - 4);
damaged.fill(0, mdat + 4, end);
assert.equal((await upload(id, damaged)).status, 422);
const accepted = await upload(id, dark);
assert.equal(accepted.status, 202);
assert.match((await accepted.json()).warnings.join(" "), /dark/i);
const events = (await api("cases/" + id + "/events")).text();
const replay = await (await api("cases/" + id + "/events")).text();
assert.match(replay, /event: started/);
assert.match(replay, /event: done/);
const seq = await events;
assert.match(seq, /event: started[\s\S]+event: finished[\s\S]+event: done/);
assert.doesNotMatch(seq, /verdict|confidence|evidence/);
const malformed = await json("shop/cases/" + id + "/decision", {
  choice: "side_buyer",
  note_for_buyer: 42,
});
assert.equal(malformed.status, 422);
const votes = await Promise.all(
  ["first", "second"].map((note) =>
    json("shop/cases/" + id + "/decision", { choice: "side_buyer", note_for_buyer: note }),
  ),
);
assert.deepEqual(votes.map((r) => r.status).sort(), [200, 409]);
const winner = ["first", "second"][votes.findIndex((r) => r.ok)];
assert.equal((await (await api("cases/" + id)).json()).note_for_buyer, winner);
const active = await create();
const ok = await upload(active, clip("white", 120));
assert.equal(ok.status, 202);
assert.deepEqual((await ok.json()).warnings, []);
const activeCase = await (await api("shop/cases/" + active)).json();
assert.equal((await del(active)).status, 204);
await delay(1200);
assert.equal(existsSync(join(store, active)), false);
assert.equal((await fetch(base + activeCase.video_url)).status, 404);
const db = new DatabaseSync(join(store, "sample.sqlite"));
const failed = await create();
const record = JSON.parse(db.prepare("SELECT value FROM records WHERE id=?").get(failed).value);
record.status = "checking";
record.progress = [{ event: "started", step: "scaffold" }];
db.prepare("UPDATE records SET value=? WHERE id=?").run(JSON.stringify(record), failed);
db.prepare("INSERT INTO jobs VALUES(?,?)").run(failed, Date.now() - 1000);
db.close();
assert.match(await (await api("cases/" + failed + "/events")).text(), /event: done/);
assert.equal((await (await api("cases/" + failed)).json()).status, "failed");
const b = await chromium.launch({ channel: "chrome" });
try {
  const p = await b.newPage({ baseURL: base, viewport: { width: 743, height: 979 } });
  await p.goto("/");
  await p.getByText("Continue as shop owner").click();
  const failure = p.locator('[data-case="' + failed + '"]');
  await failure.getByText("Video check failed").waitFor();
  assert.equal(await failure.getByRole("button", { name: "Review case" }).count(), 0);
  await p.getByRole("button", { name: "Resolved" }).click();
  await p
    .locator('[data-case="' + id + '"]')
    .getByText("View decision")
    .click();
  await p.getByRole("heading", { name: "Review case." }).waitFor();
  await p.getByRole("heading", { name: "Everyday cotton tee" }).waitFor();
  await p.getByText("Support the buyer").waitFor();
  await p.getByText(winner, { exact: true }).waitFor();
  await p.getByRole("button", { name: /Unboxing Judge/ }).click();
  await p.getByText("Continue as buyer").click();
  await p.getByRole("link", { name: "My reports", exact: true }).click();
  const report = p.locator('[data-report="' + id + '"]');
  const button = report.getByText("Delete report");
  p.once("dialog", (dialog) => dialog.dismiss());
  await button.click();
  assert.equal((await api("cases/" + id)).status, 200);
  const deleteUrl = "**/api/cases/" + id;
  const checkingError = "Case is being checked. Retry deletion once it finishes.";
  await p.route(deleteUrl, (route) =>
    route.request().method() === "DELETE"
      ? route.fulfill({ status: 409, json: { detail: checkingError } })
      : route.continue(),
  );
  p.once("dialog", (dialog) => dialog.accept());
  await button.click();
  await report.getByRole("alert").getByText(checkingError).waitFor();
  await p.unroute(deleteUrl);
  p.once("dialog", (dialog) => dialog.accept());
  await button.click();
  await button.waitFor({ state: "detached" });
  await p.reload();
  await p.getByRole("heading", { name: "My reports.", exact: true }).waitFor();
  assert.equal(await button.count(), 0);
  assert.equal((await api("shop/cases/" + id)).status, 404);
  assert(!existsSync(join(store, id)));
  assert.equal((await api("cases/" + failed)).status, 200);
  assert.equal((await api("listings")).status, 200);
  await p.getByRole("button", { name: /Unboxing Judge/ }).click();
  await p.getByText("Continue as buyer").click();
  await p.getByText("Use an existing order", { exact: true }).click();
  await p.getByText("Report a problem").click();
  await p.getByRole("radio", { name: "Damaged item" }).click();
  await p.getByText("Continue to video").click();
  await p.evaluate(() => {
    XMLHttpRequest.prototype.send = function () {
      window.reviewUpload = this;
    };
  });
  await p.locator("input[type=file]").setInputFiles(join(dir, "white5.mp4"));
  await p.getByRole("button", { name: "Send to the shop" }).click();
  const bar = p.getByRole("progressbar");
  await bar.waitFor();
  assert.equal(await bar.getAttribute("aria-valuenow"), "0");
  const sellerLink = p.getByRole("link", { name: "Switch to shop owner" });
  assert.equal(await sellerLink.getAttribute("aria-disabled"), "true");
  assert.equal(await p.getByRole("button", { name: /Unboxing Judge/ }).isDisabled(), true);
  assert.equal(
    await sellerLink.evaluate((link) =>
      link.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })),
    ),
    false,
  );
  assert.equal(new URL(p.url()).pathname, "/orders");
  await p.waitForFunction(() => !!window.reviewUpload);
  await p.evaluate(() =>
    window.reviewUpload.upload.dispatchEvent(
      new ProgressEvent("progress", { lengthComputable: true, loaded: 42, total: 100 }),
    ),
  );
  await p.getByText("42% uploaded").waitFor();
  assert.equal(await bar.getAttribute("aria-valuenow"), "42");
  await p.evaluate(() => window.reviewUpload.dispatchEvent(new ProgressEvent("error")));
  await p.getByText("Upload interrupted. Try sending your video again.").waitFor();
  assert.equal(await sellerLink.getAttribute("aria-disabled"), null);
} finally {
  await b.close();
}
console.log(
  "PASS: deletion lifecycle and confirmation, intake boundaries and warnings, concurrent decisions, direct shop context, progress replay/completion and accessible percentage.",
);
