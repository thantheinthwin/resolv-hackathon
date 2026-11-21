import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "playwright";

const baseURL = process.env.REHEARSAL_URL || "http://127.0.0.1:3000";
const dir = process.env.REHEARSAL_DIR || "../data/rehearsal";
const browser = await chromium.launch({ channel: "chrome" });
const duplicateColor = "Indigo " + Date.now().toString(36);
const next = (page) => page.getByRole("button", { name: "Continue", exact: true }).click();
const productRow = (page, title) => page.getByRole("button", { name: new RegExp(title) });
const claimRow = (page, id) => page.locator('[data-case="' + id + '"]');
const reportRow = (page, id) => page.locator('[data-report="' + id + '"]');
const reviewRow = (page, id) => page.locator('[data-review-case="' + id + '"]');
const videoUpload = {
  video: {
    name: "sample.mp4",
    mimeType: "video/mp4",
    buffer: await readFile(join(dir, "sample.mp4")),
  },
};

async function addProduct(page, title, price) {
  await page.getByRole("button", { name: "Add product" }).click();
  await page.getByLabel("Product name").fill(title);
  await page.getByLabel("Price", { exact: true }).fill(price);
}
async function assertFits(page) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
}

try {
  const page = await browser.newPage({ baseURL, viewport: { width: 1280, height: 900 } });
  const older = await page.request.post("/api/cases", {
    data: {
      order_id: "UJ-48213",
      claim_type: "counterfeit",
      description: "Older claim for the same listing.",
    },
  });
  assert.equal(older.status(), 201);
  const { id: olderId } = await older.json();
  assert.equal(
    (
      await page.request.post("/api/cases/" + olderId + "/video", { multipart: videoUpload })
    ).status(),
    202,
  );
  await page.goto("/");
  await page.getByRole("link", { name: "Continue as buyer" }).click();
  await page.getByText("Use an existing order", { exact: true }).click();
  await page.getByRole("button", { name: "Report a problem" }).click();
  await page.getByRole("radio", { name: "Damaged item" }).click();
  await page.locator("textarea").fill("A tear appeared on the sleeve.");
  await page.getByRole("link", { name: "Switch to shop owner" }).click();
  await page.waitForURL("**/shop");
  await page.getByRole("heading", { name: "Inbox." }).waitFor();
  await page.getByRole("link", { name: "Switch to buyer" }).click();
  await page.getByRole("button", { name: "Continue report" }).click();
  assert.equal(await page.locator("textarea").inputValue(), "A tear appeared on the sleeve.");
  await page.getByRole("button", { name: "Continue to video" }).click();
  await page.locator("input[type=file]").setInputFiles(join(dir, "sample.mp4"));
  const created = page.waitForResponse((r) => r.url().endsWith("/api/cases") && r.status() === 201);
  await page.getByRole("button", { name: "Send to the shop" }).click();
  const { id } = await (await created).json();
  await page.getByRole("heading", { name: "Sent to the shop." }).waitFor();
  await page.getByRole("link", { name: "Switch to shop owner" }).click();
  await page.waitForURL("**/shop");
  const second = await page.request.post("/api/cases", {
    data: {
      order_id: "UJ-48213",
      claim_type: "missing",
      description: "Second claim for the same listing.",
    },
  });
  assert.equal(second.status(), 201);
  const { id: secondId } = await second.json();
  const uploaded = await page.request.post("/api/cases/" + secondId + "/video", {
    multipart: videoUpload,
  });
  assert.equal(uploaded.status(), 202);
  await page.route("**/api/shop/cases", async (route) => {
    const response = await route.fetch();
    const cases = await response.json();
    const fixture = cases.find((item) => item.id === id);
    await route.fulfill({
      json: [
        ...cases,
        {
          ...fixture,
          id: "unrelated-case",
          order_id: "unrelated-order",
          status: "ready",
          display: "unsure",
          created_at: "2099-01-01T00:00:00Z",
        },
        ...["checking", "failed"].map((status) => ({
          ...fixture,
          id: status + "-fixture",
          status,
        })),
      ],
    });
  });
  await page.getByRole("button", { name: "Products", exact: true }).click();
  await productRow(page, "Everyday cotton tee.*Midnight Black").click();
  await page.getByRole("heading", { name: "Claims for this product" }).waitFor();
  await claimRow(page, secondId).getByRole("button", { name: "Review case" }).waitFor();
  assert.equal(await claimRow(page, "unrelated-case").count(), 0);
  await claimRow(page, id).getByRole("button", { name: "Review case" }).click();
  await page.getByText("A tear appeared on the sleeve.").waitFor();
  const sidebar = page.getByRole("complementary", { name: "Case list" });
  await sidebar.waitFor();
  await reviewRow(page, id).locator('[aria-current="true"]').waitFor();
  await reviewRow(page, "checking-fixture").getByText("Checking", { exact: true }).waitFor();
  await reviewRow(page, "failed-fixture").getByText("Video check failed").waitFor();
  assert.equal(await reviewRow(page, "checking-fixture").getByRole("button").count(), 0);
  assert.equal(await reviewRow(page, "failed-fixture").getByRole("button").count(), 0);
  assert.equal(await reviewRow(page, "unrelated-case").count(), 0);
  await reviewRow(page, secondId).getByRole("button").click();
  await page.getByText("Second claim for the same listing.").waitFor();
  await reviewRow(page, id).getByRole("button").click();
  await page.getByText("Model details", { exact: true }).click();
  await page.getByText(/Model score/).waitFor();
  await page.getByRole("button", { name: "Back to product" }).click();
  await claimRow(page, id).getByRole("button", { name: "Review case" }).click();
  await reviewRow(page, id).locator('[aria-current="true"]').waitFor();
  await reviewRow(page, olderId).getByRole("button").waitFor();
  const queueOrder = await sidebar
    .locator("[data-review-case]")
    .evaluateAll((rows) => rows.map((row) => row.getAttribute("data-review-case")));
  await page.getByLabel("Decision", { exact: true }).selectOption("side_buyer");
  await page.getByLabel("Explanation for the buyer").fill("We found the tear and will follow up.");
  await page.getByRole("button", { name: "Save decision" }).click();
  await page.getByRole("heading", { name: "Decision saved" }).waitFor();
  await reviewRow(page, id).getByText("Resolved", { exact: true }).waitFor();
  assert.deepEqual(
    await sidebar
      .locator("[data-review-case]")
      .evaluateAll((rows) => rows.map((row) => row.getAttribute("data-review-case"))),
    queueOrder,
  );
  await page.getByRole("button", { name: "Next case" }).click();
  await page.getByText("Older claim for the same listing.").waitFor();
  await reviewRow(page, olderId).locator('[aria-current="true"]').waitFor();
  await page.getByRole("button", { name: "Back to product" }).click();
  await claimRow(page, id).getByRole("button", { name: "View decision" }).click();
  await page.getByText("We found the tear and will follow up.").waitFor();
  await page.getByRole("button", { name: "Back to product" }).click();
  await page.getByRole("button", { name: "Back to products" }).click();

  await page.getByRole("button", { name: "Add product" }).click();
  await next(page);
  assert.equal(
    await page.getByLabel("Product name").evaluate((field) => field.validity.valueMissing),
    true,
  );
  await page.getByLabel("Product name").fill("Everyday cotton tee");
  await page.getByLabel("Description").fill("A separate listing with the same name.");
  await page.getByLabel("Price", { exact: true }).fill("-1");
  await next(page);
  assert.equal(
    await page
      .getByLabel("Price", { exact: true })
      .evaluate((field) => field.validity.rangeUnderflow),
    true,
  );
  await page.getByLabel("Price", { exact: true }).fill("425");
  await next(page);
  await page.getByLabel("Colors", { exact: true }).fill(duplicateColor);
  await page.getByRole("button", { name: "Add color" }).click();
  await page.getByLabel("Sizes or models", { exact: true }).fill("Small");
  await page.getByLabel("Sizes or models", { exact: true }).press("Enter");
  await page.getByLabel("Box contents", { exact: true }).fill("Tee and care card");
  await next(page);
  await page.getByRole("button", { name: "Save product" }).click();
  await page.getByRole("alert").getByText("Choose at least one product photo.").waitFor();
  const image = await readFile(join(dir, "screen-01.png"));
  const file = (index) => ({
    name: "photo-" + index + ".png",
    mimeType: "image/png",
    buffer: image,
  });
  await page.locator("input[type=file]").setInputFiles([0, 1, 2, 3].map(file));
  await page.getByRole("alert").getByText("Choose up to three photos.").waitFor();
  await page.locator("input[type=file]").setInputFiles([file(0), file(1)]);
  await page.getByText("Main image", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.getByRole("button", { name: "Back", exact: true }).click();
  assert.equal(
    await page.getByLabel("Description").inputValue(),
    "A separate listing with the same name.",
  );
  await next(page);
  await page.getByRole("button", { name: "Remove Tee and care card" }).waitFor();
  await next(page);
  await page.getByRole("button", { name: "Remove photo-0.png" }).waitFor();
  await page.route(
    "**/api/listings",
    async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({ status: 503, json: { detail: "Try saving again." } });
      } else {
        await route.continue();
      }
    },
    { times: 1 },
  );
  await page.getByRole("button", { name: "Save product" }).click();
  await page.getByRole("alert").getByText("Try saving again.").waitFor();
  const saved = page.waitForResponse(
    (r) => r.url().endsWith("/api/listings") && r.status() === 201,
  );
  await page.getByRole("button", { name: "Save product" }).click();
  const listing = await (await saved).json();
  await page.getByRole("heading", { name: "Everyday cotton tee.", exact: true }).waitFor();
  await page.getByText("A separate listing with the same name.").waitFor();
  await page.getByText("No claims yet for this product.").waitFor();
  assert.equal(
    await page.getByRole("list", { name: "Product photos" }).getByRole("img").count(),
    2,
  );
  await page.getByRole("button", { name: "Back to products" }).click();
  await productRow(page, "Everyday cotton tee.*" + duplicateColor).click();
  await page.getByText("No claims yet for this product.").waitFor();
  assert.equal(await claimRow(page, id).count(), 0);
  assert.equal(listing.title, "Everyday cotton tee");
  const claimLink = new URL("/orders", baseURL);
  claimLink.searchParams.set("product", listing.id);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByRole("button", { name: "Copy claim link" }).click();
  await page.waitForFunction(
    (url) => navigator.clipboard.readText().then((text) => text === url),
    claimLink.href,
  );

  const pastedBuyer = await browser.newPage({ baseURL });
  await pastedBuyer.goto("/reports");
  await pastedBuyer.waitForURL("**/orders#my-reports");
  const productLinkInput = pastedBuyer.getByRole("searchbox", { name: "Find your product" });
  await productLinkInput.fill("https://example.invalid/orders?product=" + listing.id);
  await pastedBuyer.getByText("Use a claim link from this app or type the product name.").waitFor();
  await productLinkInput.fill(new URL("/orders?product=unavailable", baseURL).href);
  await pastedBuyer.getByText("This product is unavailable. Try searching by name.").waitFor();
  await productLinkInput.fill(claimLink.href);
  const preview = pastedBuyer.getByRole("group", { name: "Product to confirm" });
  await preview.getByText(duplicateColor, { exact: false }).waitFor();
  await preview.getByText("Tee and care card", { exact: false }).waitFor();
  assert.equal(await pastedBuyer.getByRole("radio").count(), 0);
  await pastedBuyer.getByRole("button", { name: "Confirm product" }).click();
  await pastedBuyer.getByRole("radio", { name: "Damaged item" }).click();
  const seededLink = new URL("/orders?product=LS-101", baseURL);
  await pastedBuyer.goto(seededLink.href);
  pastedBuyer.once("dialog", (dialog) => {
    assert.match(dialog.message(), /Replace your current draft/);
    return dialog.accept();
  });
  await pastedBuyer.getByRole("button", { name: "Confirm product" }).click();
  await pastedBuyer
    .locator(".order-recap")
    .getByText(/Midnight Black/)
    .waitFor();
  assert.equal(await pastedBuyer.getByRole("radio", { checked: true }).count(), 0);

  const phone = await browser.newPage({
    baseURL,
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  await phone.goto(claimLink.href);
  const linkedPreview = phone.getByRole("group", { name: "Product to confirm" });
  await linkedPreview.getByText(duplicateColor, { exact: false }).waitFor();
  await assertFits(phone);
  await phone.goto("/orders");
  const search = phone.getByRole("searchbox", { name: "Find your product" });
  const suggestions = phone.getByRole("list", { name: "Matching products" });
  await search.fill("black cototn t-shirt");
  await suggestions
    .getByRole("button")
    .first()
    .getByText(/Midnight Black/)
    .waitFor();
  await search.press("ArrowDown");
  assert.match(await phone.locator(":focus").textContent(), /Midnight Black/);
  await search.fill("black cotton t-shirt");
  await search.press("Enter");
  await linkedPreview.getByText(/Midnight Black/).waitFor();
  await search.fill("Everyday cotton tee");
  await productRow(phone, "Everyday cotton tee.*Midnight Black").waitFor();
  await productRow(phone, "Everyday cotton tee.*" + duplicateColor).click();
  await linkedPreview.getByText("Tee and care card", { exact: false }).waitFor();
  await phone.getByRole("button", { name: "Confirm product" }).click();
  const claimRegion = phone.locator("#start-a-claim");
  await claimRegion.getByRole("heading", { name: "Start a claim." }).waitFor();
  await claimRegion.getByRole("heading", { name: "Tell us what went wrong." }).waitFor();
  assert.equal(await claimRegion.getByRole("searchbox").count(), 0);
  await phone.getByRole("radio", { name: "Missing items or parts" }).click();
  const standaloneDescription = "The care card was missing from the indigo tee.";
  await phone.locator("textarea").fill(standaloneDescription);
  await claimRegion.getByRole("button", { name: "Change product" }).click();
  await linkedPreview.getByText(/Tee and care card/).waitFor();
  await claimRegion.getByRole("button", { name: "Confirm product" }).click();
  assert.equal(await phone.locator("textarea").inputValue(), standaloneDescription);

  await phone.goto(seededLink.href);
  await linkedPreview.getByText("Midnight Black", { exact: false }).waitFor();
  phone.once("dialog", (dialog) => {
    assert.match(dialog.message(), /Replace your current draft/);
    return dialog.dismiss();
  });
  await phone.getByRole("button", { name: "Confirm product" }).click();
  await phone.getByRole("button", { name: "Continue report", exact: true }).click();
  assert.equal(await phone.locator("textarea").inputValue(), standaloneDescription);
  await phone.getByRole("button", { name: "Continue to video" }).click();
  await phone.locator("input[type=file]").setInputFiles(join(dir, "sample.mp4"));
  const standaloneCreated = phone.waitForResponse(
    (r) => r.url().endsWith("/api/cases") && r.status() === 201,
  );
  await phone.getByRole("button", { name: "Send to the shop" }).click();
  const standaloneResponse = await standaloneCreated;
  assert.deepEqual(standaloneResponse.request().postDataJSON(), {
    listing_id: listing.id,
    claim_type: "missing",
    description: standaloneDescription,
  });
  const { id: standaloneId } = await standaloneResponse.json();
  await phone.getByRole("heading", { name: "Sent to the shop." }).waitFor();
  await phone.getByRole("link", { name: "View my reports" }).click();
  const standaloneReport = reportRow(phone, standaloneId);
  await standaloneReport.getByRole("button", { name: "View report details" }).click();
  await standaloneReport.getByText(standaloneDescription, { exact: true }).waitFor();
  const player = standaloneReport.getByLabel("Your unboxing video");
  await player.evaluate(async (video) => {
    video.muted = true;
    await video.play();
  });
  await phone.waitForFunction(
    () => document.querySelector('video[aria-label="Your unboxing video"]')?.currentTime > 0,
  );
  await player.evaluate((video) => video.pause());
  await assertFits(phone);
  await phone.screenshot({ path: join(dir, "product-claim-mobile.png"), fullPage: true });
  assert.equal(await phone.getByText("Model details", { exact: true }).count(), 0);
  const details = await (await pastedBuyer.request.get("/api/cases/" + standaloneId)).json();
  assert.equal(details.listing_id, listing.id);
  assert.equal(details.order_id, undefined);
  await pastedBuyer.route("**" + details.video_url, (route) => route.fulfill({ status: 404 }));
  const unavailableReport = reportRow(pastedBuyer, standaloneId);
  await unavailableReport.getByRole("button", { name: "View report details" }).click();
  await unavailableReport.getByText("The original video is unavailable.").waitFor();
  await unavailableReport.getByText(standaloneDescription, { exact: true }).waitFor();

  await claimRow(page, standaloneId).getByRole("button", { name: "Review case" }).click();
  await page.getByText(standaloneDescription, { exact: true }).waitFor();
  await reviewRow(page, standaloneId).locator('[aria-current="true"]').waitFor();
  assert.equal(await reviewRow(page, secondId).count(), 0);
  await page.getByLabel("Decision", { exact: true }).selectOption("side_buyer");
  const standaloneReply = "We will send you the care card.";
  await page.getByLabel("Explanation for the buyer").fill(standaloneReply);
  await page.getByRole("button", { name: "Save decision" }).click();
  await page.getByText("No more cases to review", { exact: false }).waitFor();
  await standaloneReport.getByText(standaloneReply, { exact: true }).waitFor();
  await page.getByRole("button", { name: "Back to product" }).click();
  await claimRow(page, standaloneId).getByRole("button", { name: "View decision" }).waitFor();
  await page.getByRole("button", { name: "Back to products" }).click();
  await productRow(page, "Everyday cotton tee.*Midnight Black").click();
  await claimRow(page, secondId).getByRole("button", { name: "Review case" }).waitFor();
  assert.equal(await claimRow(page, standaloneId).count(), 0);

  await phone.goto("/shop");
  await phone.getByRole("button", { name: "Products", exact: true }).click();
  await productRow(phone, "Everyday cotton tee.*" + duplicateColor).click();
  await claimRow(phone, standaloneId).getByRole("button", { name: "View decision" }).click();
  await phone.getByRole("button", { name: "Cases for this product" }).click();
  await reviewRow(phone, standaloneId).getByText("Resolved", { exact: true }).waitFor();
  await assertFits(phone);
  await phone.getByRole("button", { name: "Back to product" }).click();
  await phone.getByRole("button", { name: "Back to products" }).click();
  await addProduct(phone, "Phone listing", "99");
  await assertFits(phone);
  phone.once("dialog", (dialog) => dialog.dismiss());
  await phone.getByRole("link", { name: "Switch to buyer" }).click();
  await phone.getByRole("heading", { name: "Add product." }).waitFor();
  phone.once("dialog", (dialog) => dialog.dismiss());
  await phone.getByRole("button", { name: "Cancel", exact: true }).click();
  assert.equal(await phone.getByLabel("Product name").inputValue(), "Phone listing");
  phone.once("dialog", (dialog) => dialog.accept());
  await phone.getByRole("button", { name: "Cancel", exact: true }).click();
  await phone.getByRole("heading", { name: "Products.", exact: true }).waitFor();
  await addProduct(phone, "Phone listing", "99");
  await next(phone);
  await assertFits(phone);
  await next(phone);
  await phone.locator("input[type=file]").setInputFiles(file(0));
  await assertFits(phone);
  await phone.getByRole("button", { name: "Save product" }).click();
  await phone.getByRole("heading", { name: "Phone listing." }).waitFor();
  await assertFits(phone);
  await phone.screenshot({ path: join(dir, "product-details-mobile.png"), fullPage: true });
  await phone.goto("/reports");
  await phone.waitForURL("**/orders#my-reports");
  await standaloneReport.getByText(standaloneReply, { exact: true }).waitFor();
  console.log(
    "Passed product wizard, role switching, product link and search, draft recovery, original video playback, same-title isolation, scoped review and buyer response.",
  );
} finally {
  await browser.close();
}
