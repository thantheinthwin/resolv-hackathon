import { execFileSync } from "node:child_process";
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
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
  await page.getByText("Report a problem").waitFor();
  await shot();
  await page.getByText("Report a problem").click();
  assert.equal(await page.getByRole("radio", { checked: true }).count(), 0);
  assert.equal(await page.getByRole("button", { name: "Continue to video" }).isDisabled(), true);
  await page.getByRole("radio", { name: "Wrong item, color, or size" }).click();
  await page.locator("textarea").fill("The colour looks different from my order.");
  await shot();
  await page.getByText("Continue to video").click();
  await page.reload();
  await page.getByText("Resume report").click();
  const created = page.waitForResponse(
    (r) => r.url().endsWith("/api/cases") && r.request().method() === "POST",
  );
  await page
    .locator("input[type=file]")
    .setInputFiles({ name: "bad.mp4", mimeType: "video/mp4", buffer: Buffer.from("invalid") });
  await page.getByRole("button", { name: "Send to the shop" }).click();
  const { id } = await (await created).json();
  await page.getByText("Choose a readable video.").waitFor();
  await page.locator("input[type=file]").setInputFiles(dir + "/sample.mp4");
  await shot();
  const accepted = page.waitForResponse(
    (r) => r.url().endsWith("/api/cases/" + id + "/video") && r.status() === 202,
  );
  await page.getByRole("button", { name: "Send to the shop" }).click();
  await accepted;
  await page.getByText("Sent to the shop.", { exact: true }).waitFor();
  await shot();
  await page.getByRole("button", { name: /Unboxing Judge/ }).click();
  await page.getByText("Continue as shop owner").click();
  const row = page.locator('[data-case="' + id + '"]');
  await row.getByText("Review case").click();
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
  await page.getByText("My reports", { exact: true }).click();
  await page.getByText("We will contact you to arrange a replacement.").first().waitFor();
  await shot();
  const video = page.video();
  await page.reload();
  const result = await (await page.request.get("/api/cases/" + id)).json();
  assert.deepEqual(Object.keys(result).sort(), ["id", "note_for_buyer", "status"]);
  assert.equal(result.status, "replied");
  await page.close();
  await video.saveAs(dir + "/buyer-to-shop.webm");
  console.log(
    "Passed buyer upload rejection/retry, sample judge, shop decision and buyer response privacy.",
  );
} finally {
  await browser.close();
}
