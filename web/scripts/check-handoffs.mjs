import { chromium, request } from "playwright";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const browser = await chromium.launch({ channel: "chrome" });
const baseURL = process.env.REHEARSAL_URL || "http://127.0.0.1:3000";
const dir = process.env.REHEARSAL_DIR || "../data/rehearsal";

async function startOrderReport(page) {
  const order = page.getByRole("button", { name: "Yes, this is my item" });

  await page
    .getByLabel("Product link", { exact: true })
    .fill(new URL("/products/LS-101", page.url()).href);
  await page.getByRole("button", { name: "Find my item" }).click();
  await order.click();
}

try {
  const desktop = await browser.newPage({ baseURL, viewport: { width: 1300, height: 900 } });
  await desktop.goto("/");
  await desktop.getByText("Continue as buyer").click();
  await startOrderReport(desktop);
  await desktop.getByRole("radio", { name: "Something was missing" }).click();
  await desktop.getByText("Next: add a video").click();
  const create = desktop.waitForResponse((r) => r.url().endsWith("/api/cases"));
  await desktop.getByRole("button", { name: "Show QR code" }).click();
  const { id } = await (await create).json();
  const seller = await browser.newPage({ baseURL });
  await seller.goto("/");
  await seller.getByText("Continue as shop owner").click();
  await seller.getByRole("heading", { name: "Inbox." }).waitFor();
  await seller.getByText("Loading the inbox…").waitFor({ state: "hidden" });
  assert.equal(await seller.locator('[data-case="' + id + '"]').count(), 0);
  await seller.getByRole("button", { name: "Checking" }).click();
  assert.equal(await seller.locator('[data-case="' + id + '"]').count(), 0);
  const url = await desktop.getByText("Open phone upload").getAttribute("href");
  await desktop.reload();
  await desktop.getByRole("button", { name: "Resume upload", exact: true }).click();
  await desktop.getByRole("heading", { name: "Add your unboxing video." }).waitFor();
  const phone = await browser.newPage({
    baseURL,
    viewport: { width: 390, height: 844 },
    isMobile: true,
  });
  await phone.goto(url);
  await phone.getByText("Order UJ-48213").waitFor();
  await phone.locator("input").setInputFiles(dir + "/sample.mp4");
  await phone.getByText("Send video").click();
  await phone.getByText("Done. You can close this page.").waitFor();
  await desktop.getByText("Sent to the shop.", { exact: true }).waitFor();
  const token = new URL(url).pathname.split("/").pop();
  const multipart = {
    video: {
      name: "sample.mp4",
      mimeType: "video/mp4",
      buffer: await readFile(dir + "/sample.mp4"),
    },
  };
  // A legal MP4 free-space box exercises the upload path above Next's default 10 MiB proxy limit.
  const padding = Buffer.alloc(11 * 1024 * 1024);
  padding.writeUInt32BE(padding.length);
  padding.write("free", 4);
  const largeMultipart = {
    video: { ...multipart.video, buffer: Buffer.concat([multipart.video.buffer, padding]) },
  };
  assert.equal((await phone.request.post("/api/uploads/" + token, { multipart })).status(), 404);

  // Generate a QR in this mounted desk, then complete the report and start another.
  await desktop.getByRole("link", { name: "Report a problem" }).click();
  await startOrderReport(desktop);
  await desktop.getByRole("radio", { name: "My item arrived damaged" }).click();
  await desktop.getByRole("button", { name: "Next: add a video" }).click();
  const secondCreated = desktop.waitForResponse((response) =>
    response.url().endsWith("/api/cases"),
  );
  await desktop.getByRole("button", { name: "Show QR code" }).click();
  const { id: secondId } = await (await secondCreated).json();
  const secondUrl = await desktop.getByText("Open phone upload").getAttribute("href");
  const secondToken = new URL(secondUrl).pathname.split("/").pop();
  assert.equal(
    (await phone.request.post("/api/uploads/" + secondToken, { multipart })).status(),
    202,
  );
  await desktop.getByRole("heading", { name: "Sent to the shop." }).waitFor();
  await desktop.getByRole("link", { name: "Report a problem" }).click();
  await startOrderReport(desktop);
  await desktop.getByRole("radio", { name: "My item arrived damaged" }).click();
  await desktop.getByRole("button", { name: "Next: add a video" }).click();
  assert.equal(await desktop.getByText("Open phone upload").count(), 0);
  const thirdCreated = desktop.waitForResponse((response) => response.url().endsWith("/api/cases"));
  await desktop.getByRole("button", { name: "Show QR code" }).click();
  const { id: thirdId } = await (await thirdCreated).json();
  const thirdUrl = await desktop.getByText("Open phone upload").getAttribute("href");
  const thirdToken = new URL(thirdUrl).pathname.split("/").pop();
  assert.notEqual(thirdToken, secondToken);
  const replacement = await desktop.request.post("/api/cases/" + thirdId + "/upload-link");
  assert.equal(replacement.status(), 200);
  const { token: activeToken } = await replacement.json();
  assert.notEqual(activeToken, thirdToken);
  assert.equal(
    (await phone.request.post("/api/uploads/" + thirdToken, { multipart })).status(),
    404,
  );

  // Hold the polling view one update behind the phone upload.
  await desktop.route("**/api/cases/" + thirdId, (route) =>
    route.fulfill({ json: { id: thirdId, status: "sent", note_for_buyer: null } }),
  );
  await desktop.getByRole("link", { name: "My reports" }).click();
  const confirmDiscard = desktop.waitForEvent("dialog");
  const discard = desktop.getByRole("button", { name: "Discard draft" }).click();
  const dialog = await confirmDiscard;
  try {
    assert.match(dialog.message(), /permanently deletes.*video/);
    assert.equal(
      (
        await phone.request.post("/api/uploads/" + activeToken, { multipart: largeMultipart })
      ).status(),
      202,
    );
  } finally {
    await dialog.accept();
  }
  await discard;
  await desktop
    .getByText("Your video reached the shop. The report is still in My reports.")
    .waitFor();
  await desktop.getByRole("heading", { name: "Which item do you need help with?" }).waitFor();
  await desktop.getByLabel("Product link", { exact: true }).waitFor();
  const lateDiscard = await phone.request.delete("/api/cases/" + thirdId + "?draft=true");
  assert.equal(lateDiscard.status(), 409);
  const preserved = await phone.request.get("/api/shop/cases/" + thirdId);
  assert.equal(preserved.status(), 200);
  assert((await preserved.json()).video_url);

  await seller.route("**/api/shop/cases/" + secondId, async (route) => {
    const response = await route.fetch();
    const item = await response.json();
    item.verdict.leaning = "seller";
    await route.fulfill({ json: item });
  });
  const decisionReceived = Promise.withResolvers();
  const deliverDecision = Promise.withResolvers();
  const decisionPath = "/api/shop/cases/" + id + "/decision";
  await seller.route("**" + decisionPath, async (route) => {
    const response = await route.fetch();
    decisionReceived.resolve(response.status());
    await deliverDecision.promise;
    await route.fulfill({ response });
  });
  await seller.getByRole("button", { name: "Needs review" }).click();
  await seller
    .locator('[data-case="' + id + '"]')
    .getByText("Review case")
    .click();
  await seller.getByRole("heading", { name: "Evidence", exact: true }).waitFor();
  await seller.getByText("Unsure: check the video").waitFor();
  await seller.getByLabel("Decision", { exact: true }).selectOption("side_buyer");
  await seller.getByLabel("Explanation for the buyer").fill("Decision for the first report.");
  await seller.getByRole("button", { name: "Save decision" }).click();
  const decisionResponse = seller.waitForResponse(
    (response) => response.url().endsWith(decisionPath) && response.status() === 200,
  );
  try {
    assert.equal(await decisionReceived.promise, 200);
    await seller.getByRole("button", { name: "Back to inbox" }).click();
    await seller
      .locator('[data-case="' + secondId + '"]')
      .getByText("Review case")
      .click();
    await seller.getByText("Model leans toward the shop.").waitFor();
  } finally {
    deliverDecision.resolve();
  }
  const queueRefreshed = seller.waitForRequest(
    (request) => request.url().endsWith("/api/shop/cases") && request.method() === "GET",
  );
  await (await decisionResponse).finished();
  await queueRefreshed;
  assert.equal(await seller.getByRole("heading", { name: "Damaged item" }).isVisible(), true);
  assert.equal(await seller.getByRole("heading", { name: "Decision saved" }).count(), 0);
  await seller.getByRole("button", { name: "Back to inbox" }).click();
  await seller.getByRole("button", { name: "Resolved" }).click();
  await seller
    .locator('[data-case="' + id + '"]')
    .getByText("View decision")
    .waitFor();

  await desktop.getByRole("button", { name: /Unboxing Judge/ }).click();
  await desktop.getByText("Continue as shop owner").click();
  await desktop.route("**/api/shop/cases/" + secondId, async (route) => {
    const res = await route.fetch();
    const c = await res.json();
    const photo = "/api/files/listings/sample/tee.png";
    c.verdict.evidence = [
      { t: 2, check: "listing", result: "flag", frame: photo, listing_photo: photo },
    ];
    c.verdict.display = "clear";
    c.verdict.verdict = "buyer_right";
    await route.fulfill({ json: c });
  });
  await desktop
    .locator('[data-case="' + secondId + '"]')
    .getByText("Review case")
    .click();
  await desktop
    .locator("video")
    .evaluate(
      (v) =>
        v.readyState >= 1 ||
        new Promise((r) => v.addEventListener("loadedmetadata", r, { once: true })),
    );
  await desktop.getByRole("button", { name: "0:02 Listing match" }).click();
  await desktop.waitForFunction(
    () => Math.abs(document.querySelector("video").currentTime - 2) < 0.1,
  );
  await desktop.getByRole("img", { name: "Listing photo of Everyday cotton tee" }).waitFor();
  await desktop.locator("form select").first().selectOption("disagree");
  assert.equal(
    await desktop
      .locator("form select")
      .last()
      .evaluate((s) => s.validity.valueMissing),
    true,
  );
  await desktop.getByText("Products", { exact: true }).click();
  await desktop.getByText("Add product").click();
  await desktop.getByLabel("Product name").fill("Walkthrough sample");
  await desktop.getByLabel("Price", { exact: true }).fill("75");
  await desktop.getByRole("button", { name: "Continue", exact: true }).click();
  await desktop.getByRole("button", { name: "Continue", exact: true }).click();
  await desktop.locator("input[type=file]").setInputFiles(dir + "/screen-01.png");
  await desktop.getByText("Save product").click();
  await desktop.getByRole("heading", { name: "Walkthrough sample.", exact: true }).waitFor();
  console.log(
    "Passed QR handoff and token isolation, discard during phone upload, late seller save, unsure leaning, evidence seek, disagreement validation and product creation.",
  );

  const integrated = process.env.INTEGRATED_REHEARSAL_URL;
  if (integrated) {
    const passcode = process.env.INTEGRATED_REHEARSAL_PASSCODE;
    assert(passcode, "Set INTEGRATED_REHEARSAL_PASSCODE for the isolated integrated instance.");
    const api = (path) => new URL("/api/" + path, integrated).href;
    const anonymous = await phone.request.get(api("shop/cases"));
    assert.equal(anonymous.status(), 401);
    assert.match(anonymous.headers()["www-authenticate"], /^Basic /);
    const authenticated = await request.newContext({
      httpCredentials: {
        username: "demo",
        password: passcode,
        origin: new URL(integrated).origin,
        send: "always",
      },
    });
    try {
      const created = await authenticated.post(api("cases"), {
        data: { order_id: "UJ-48213", claim_type: "damaged" },
      });
      assert.equal(created.status(), 201);
      const { id: caseId } = await created.json();
      const path = "cases/" + caseId;
      assert.equal((await (await authenticated.get(api(path))).json()).status, "sent");
      const handoff = await authenticated.post(api(path + "/upload-link"));
      assert.equal(handoff.status(), 200);
      const { token } = await handoff.json();
      const accepted = await phone.request.post(api("uploads/" + token), {
        multipart: largeMultipart,
      });
      assert.equal(accepted.status(), 202);
      assert.match(await (await authenticated.get(api(path + "/events"))).text(), /^event: done/m);
      assert.equal((await (await authenticated.get(api(path))).json()).status, "with_shop");

      const lateDiscard = await authenticated.delete(api(path + "?draft=1"));
      assert.equal(lateDiscard.status(), 409);
      const review = await authenticated.get(api("shop/cases/" + caseId));
      assert.equal(review.status(), 200);
      const { video_url } = await review.json();
      const footage = await authenticated.get(new URL(video_url, integrated).href);
      assert.equal(footage.status(), 200);
      assert.equal(footage.headers()["x-content-type-options"], "nosniff");
      assert.deepEqual(await footage.body(), largeMultipart.video.buffer);
      assert.equal((await authenticated.delete(api(path))).status(), 204);
      console.log("Passed draft-only deletion through the integrated proxy after a phone upload.");
    } finally {
      await authenticated.dispose();
    }
  }
} finally {
  await browser.close();
}
