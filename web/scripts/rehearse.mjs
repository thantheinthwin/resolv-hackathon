import { execFileSync } from "node:child_process";
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdir, readFile, truncate, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
const dir = process.env.REHEARSAL_DIR || resolve("../data/rehearsal");
await mkdir(dir, { recursive: true });
execFileSync("ffmpeg", [
  "-loglevel",
  "error",
  "-f",
  "lavfi",
  "-i",
  "testsrc2=size=480x270:rate=12",
  "-t",
  "6",
  "-c:v",
  "libx264",
  "-pix_fmt",
  "yuv420p",
  "-y",
  dir + "/sample.mp4",
]);
const baseURL = process.env.REHEARSAL_URL || "http://127.0.0.1:3000";
const browser = await chromium.launch({ channel: "chrome", headless: true, slowMo: 130 });

function measureClaimFrame(page) {
  return page.evaluate(() => {
    const frame = document.querySelector(".claim-frame").getBoundingClientRect();
    const title = document.querySelector("#claim-title").getBoundingClientRect();
    const stage = document.querySelector("#claim-step-title").getBoundingClientRect();
    const reports = document.querySelector("#buyer-reports-title").getBoundingClientRect();
    return {
      frameX: frame.x + window.scrollX,
      frameY: frame.y + window.scrollY,
      frameWidth: frame.width,
      frameHeight: frame.height,
      titleY: title.y + window.scrollY,
      stageY: stage.y + window.scrollY,
      reportsY: reports.y + window.scrollY,
    };
  });
}

async function assertStableFrame(page, expected, step) {
  const actual = await measureClaimFrame(page);
  for (const [key, value] of Object.entries(expected))
    assert(
      Math.abs(actual[key] - value) <= 1,
      `${step}: ${key} moved from ${value} to ${actual[key]}`,
    );
}

function fileTransfer(page, files) {
  return page.evaluateHandle((items) => {
    const transfer = new DataTransfer();
    for (const { name, type, base64 = "" } of items) {
      const bytes = Uint8Array.from(atob(base64), (character) => character.charCodeAt(0));
      transfer.items.add(new File([bytes], name, { type }));
    }
    return transfer;
  }, files);
}

async function dropFiles(page, surface, files) {
  const dataTransfer = await fileTransfer(page, files);
  try {
    await surface.dispatchEvent("drop", { dataTransfer });
  } finally {
    await dataTransfer.dispose();
  }
}

try {
  const page = await browser.newPage({
    recordVideo: { dir, size: { width: 1440, height: 920 } },
    baseURL,
    viewport: { width: 1440, height: 920 },
  });
  await page.goto(baseURL, { waitUntil: "domcontentloaded" });
  let n = 0;
  const shot = async () =>
    page.screenshot({
      path: dir + "/screen-" + String(++n).padStart(2, "0") + ".png",
      timeout: 12000,
    });
  await page.getByText("Continue as buyer").click();
  await page
    .getByLabel("Product link", { exact: true })
    .fill(new URL("/products/LS-101", page.url()).href);
  await page.getByRole("button", { name: "Find my item" }).click();
  await page.getByText("Yes, this is my item").waitFor();
  const frameBody = page.locator(".claim-frame-body");
  const initialBody = await frameBody.elementHandle();
  await shot();
  await page.getByText("Yes, this is my item").click();
  await page.getByRole("heading", { name: "What happened?" }).waitFor();
  assert.equal(await frameBody.evaluate((body, previous) => body === previous, initialBody), true);
  await initialBody.dispose();
  assert.equal(await page.getByRole("radio", { checked: true }).count(), 0);
  assert.equal(await page.getByRole("button", { name: "Next: add a video" }).isDisabled(), true);
  await page.getByRole("radio", { name: "I received the wrong item, colour or size" }).click();
  await page.locator("textarea").fill("The colour looks different from my order.");
  const frameBaseline = await measureClaimFrame(page);
  await shot();
  await page.getByText("Next: add a video").click();
  await page.getByRole("heading", { name: "Add your unboxing video." }).waitFor();
  await assertStableFrame(page, frameBaseline, "Video");
  await page.reload();
  await page.getByRole("button", { name: "Resume upload", exact: true }).click();
  await page.getByRole("button", { name: "Choose video", exact: true }).waitFor();
  const uploadBody = await frameBody.elementHandle();
  const dropzone = page.locator("[data-upload-dropzone]");
  await dropzone.waitFor();
  const oversized = resolve(dir, "oversized.mp4");
  await writeFile(oversized, "");
  await truncate(oversized, 50_000_001);
  await page.locator('input[accept="video/*"]').setInputFiles(oversized);
  await page
    .getByRole("alert")
    .getByText("Your video is too large. Choose a video that is 50 MB or smaller.")
    .waitFor();
  const corrupt = {
    name: "bad.mp4",
    type: "video/mp4",
    base64: Buffer.from("invalid").toString("base64"),
  };
  const dragged = await fileTransfer(page, [corrupt]);
  await dropzone.dispatchEvent("dragenter", { dataTransfer: dragged });
  await page.locator('[data-upload-dropzone][data-dragging="true"]').waitFor();
  await dropzone.dispatchEvent("dragleave", { dataTransfer: dragged });
  await page.locator('[data-upload-dropzone][data-dragging="true"]').waitFor({ state: "detached" });
  await dragged.dispose();
  await dropFiles(page, dropzone, [{ name: "notes.txt", type: "text/plain" }]);
  await page.getByText("Choose one video and up to three JPEG, PNG or WebP photos.").waitFor();
  await dropFiles(page, dropzone, [corrupt, { ...corrupt, name: "second.mp4" }]);
  await page.getByText("Choose one video and up to three JPEG, PNG or WebP photos.").waitFor();
  assert.equal(await page.getByRole("button", { name: "Send to the shop" }).count(), 0);

  const created = page.waitForResponse(
    (r) => r.url().endsWith("/api/cases") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Show QR code" }).click();
  const { id } = await (await created).json();
  await page.getByRole("link", { name: "Open phone upload" }).waitFor();
  await assertStableFrame(page, frameBaseline, "QR");

  await dropFiles(page, dropzone, [corrupt]);
  await page.getByText("bad.mp4", { exact: true }).waitFor();
  await page.route(
    "**/api/cases/" + id + "/video",
    (route) => route.fulfill({ status: 413, contentType: "text/plain", body: "Payload Too Large" }),
    { times: 1 },
  );
  await page.getByRole("button", { name: "Send to the shop" }).click();
  await page
    .getByRole("alert")
    .getByText("Your video is too large to upload. Choose a smaller video.")
    .waitFor();
  await page.getByRole("button", { name: "Send to the shop" }).click();
  await page.getByText("Choose a readable video.").waitFor();
  await assertStableFrame(page, frameBaseline, "Upload rejected");
  await dropFiles(page, dropzone, [
    {
      name: "sample.mp4",
      type: "video/mp4",
      base64: await readFile(dir + "/sample.mp4", "base64"),
    },
  ]);
  await page.getByLabel("Selected video preview").waitFor();
  await page.getByRole("button", { name: "Replace video" }).waitFor();
  await dropFiles(page, dropzone, [{ name: "notes.txt", type: "text/plain" }]);
  await page.getByText("Choose one video and up to three JPEG, PNG or WebP photos.").waitFor();
  await page.getByLabel("Selected video preview").waitFor();
  await dropFiles(page, dropzone, [
    {
      name: "recording",
      type: "application/octet-stream",
      base64: await readFile(dir + "/sample.mp4", "base64"),
    },
  ]);
  await page.getByText("recording", { exact: true }).waitFor();
  assert.match(await frameBody.evaluate((body) => getComputedStyle(body).overflowY), /auto|scroll/);
  const send = page.getByRole("button", { name: "Send to the shop" });
  await send.scrollIntoViewIfNeeded();
  await assertStableFrame(page, frameBaseline, "Preview with QR");
  await shot();
  const accepted = page.waitForResponse(
    (r) => r.url().endsWith("/api/cases/" + id + "/video") && r.status() === 202,
  );
  await send.click();
  await accepted;
  await page.getByText("Sent to the shop.", { exact: true }).waitFor();
  await assertStableFrame(page, frameBaseline, "Receipt");
  assert.equal(await frameBody.evaluate((body, previous) => body === previous, uploadBody), true);
  await uploadBody.dispose();
  await shot();
  await page.getByRole("button", { name: /Unboxing Judge/ }).click();
  await page.getByText("Continue as shop owner").click();
  const row = page.locator('[data-case="' + id + '"]');
  await row.getByText("Review case").click();
  await page.getByRole("heading", { name: "Evidence", exact: true }).waitFor();
  await page.getByText("Unsure: check the video").waitFor();
  await shot();
  await page.locator("select").selectOption("side_buyer");
  assert.equal(
    await page.locator("textarea").evaluate((input) => input.validity.valueMissing),
    true,
  );
  await page.locator("textarea").fill("We will contact you to arrange a replacement.");
  await page.getByText("Save decision").click();
  await page.getByText("Decision saved").waitFor();
  await page.getByRole("button", { name: "Back to inbox" }).click();
  assert.equal(await row.count(), 0);
  await page.getByRole("button", { name: "Resolved" }).click();
  await row.getByText("View decision").waitFor();
  await page.getByRole("button", { name: /Unboxing Judge/ }).click();
  await page.getByText("Continue as buyer").click();
  await page.getByRole("link", { name: "My reports", exact: true }).click();
  await page.getByText("We will contact you to arrange a replacement.").first().waitFor();
  await shot();
  const video = page.video();
  await page.reload();
  const result = await (await page.request.get("/api/cases/" + id)).json();
  assert.deepEqual(Object.keys(result).sort(), [
    "claim_type",
    "created_at",
    "description",
    "id",
    "note_for_buyer",
    "order_id",
    "product",
    "status",
    "video_url",
  ]);
  assert.equal(result.status, "replied");
  assert.equal(result.description, "The colour looks different from my order.");
  await page.close();
  await video.saveAs(dir + "/buyer-to-shop.webm");
  console.log(
    "Passed stable desktop claim frame, drag and drop, upload rejection/retry, sample judge, shop decision and buyer response privacy.",
  );
} finally {
  await browser.close();
}
