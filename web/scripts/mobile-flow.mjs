import assert from "node:assert/strict";
import { join } from "node:path";
import { chromium, devices, webkit } from "playwright";

const baseURL = process.env.REHEARSAL_URL || "http://127.0.0.1:3000";
const dir = process.env.REHEARSAL_DIR || "../data/rehearsal";
const android = await chromium.launch({ channel: "chrome" });
let safari;
const buyers = [];

async function assertFits(page) {
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    true,
    "The screen should fit without horizontal scrolling",
  );
}

try {
  if (process.env.PHONE_WEBKIT === "1") safari = await webkit.launch();
  for (const { browser, device, name, colorScheme, claim } of [
    {
      browser: safari ?? android,
      device: "iPhone 13",
      name: safari ? "iPhone WebKit" : "iPhone Chromium emulation",
      colorScheme: "light",
      claim: "Something was missing",
    },
    {
      browser: android,
      device: "Pixel 7",
      name: "Android",
      colorScheme: "dark",
      claim: "I think my item might be a fake",
    },
  ]) {
    const page = await browser.newPage({
      ...devices[device],
      baseURL,
      colorScheme,
      reducedMotion: "reduce",
    });
    await page.goto("/");
    if (browser === android) {
      await page.keyboard.press("Tab");
      assert.equal(
        await page
          .getByRole("link", { name: "Skip to content" })
          .evaluate((link) => document.activeElement === link),
        true,
        "Skip link should be first in the keyboard order",
      );
    }
    await page.getByRole("link", { name: "Continue as buyer" }).click();
    await page
      .getByLabel("Product link", { exact: true })
      .fill(new URL("/products/LS-101", page.url()).href);
    await page.getByRole("button", { name: "Find my item" }).click();
    const order = page.getByRole("button", { name: "Yes, this is my item" });
    await order.waitFor();
    await assertFits(page);
    await order.click();
    await page.getByRole("radio", { name: claim }).click();
    const description = `${name} test report`;
    await page.locator("textarea").fill(description);
    await page.getByRole("button", { name: "Next: add a video" }).click();
    await page.getByRole("link", { name: "My reports" }).click();
    await page.waitForURL("**/orders#my-reports");
    await page.reload();
    await page.getByText("Draft", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Resume upload" }).click();
    await page.getByRole("button", { name: "Choose video" }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Show QR code" }).isVisible(), false);
    await assertFits(page);
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Choose video" }).click();
    await (await chooser).setFiles(join(dir, "sample.mp4"));
    await page.getByRole("button", { name: "Replace video" }).waitFor();
    await page.getByLabel("Selected video preview").waitFor();
    const body = page.locator(".claim-frame-body");
    assert(
      await body.evaluate((element) => element.scrollHeight <= element.clientHeight + 1),
      "The phone should scroll the page rather than clip the claim inside a nested scroller",
    );
    await assertFits(page);
    const creating = page.waitForResponse(
      (response) => response.url().endsWith("/api/cases") && response.status() === 201,
    );
    await page.getByRole("button", { name: "Send to the shop" }).click();
    const { id } = await (await creating).json();
    await page.getByRole("heading", { name: "Sent to the shop." }).waitFor();
    await page.getByRole("link", { name: "View my reports" }).click();
    const report = page.locator('[data-report="' + id + '"]');
    await report.getByText(claim, { exact: false }).waitFor();
    assert.equal(
      await report.getByRole("heading", { name: "Everyday cotton tee" }).isVisible(),
      true,
    );
    await report.getByRole("button", { name: "View report details" }).click();
    await report.getByLabel("Your unboxing video").waitFor();
    await report.getByText(description, { exact: true }).waitFor();
    await assertFits(page);
    await page.screenshot({ path: join(dir, `${name.toLowerCase()}-reports.png`), fullPage: true });
    buyers.push({ page, id, description });
    console.log(
      `${name}: direct filing, native picker, draft recovery, receipt and report evidence passed.`,
    );
  }

  const seller = await android.newPage({ ...devices["Pixel 7"], baseURL });
  await seller.goto("/");
  await seller.getByRole("link", { name: "Continue as shop owner" }).click();
  const [first, second] = buyers;
  await seller
    .locator('[data-case="' + first.id + '"]')
    .getByRole("button", { name: "Review case" })
    .click();
  await seller.getByText(first.description).waitFor();
  await seller.getByRole("button", { name: "Cases in the inbox" }).click();
  const mobileCaseList = seller.getByRole("complementary", { name: "Case list" });
  await mobileCaseList
    .locator('[data-review-case="' + first.id + '"]')
    .locator('[aria-current="true"]')
    .waitFor();
  await seller.getByRole("button", { name: "Cases in the inbox" }).click();
  await assertFits(seller);
  const video = await seller.locator("video").boundingBox();
  const evidence = await seller
    .getByRole("heading", { name: "Evidence", exact: true })
    .boundingBox();
  const decision = await seller
    .getByRole("heading", { name: "Shop decision", exact: true })
    .boundingBox();
  assert(video && evidence && decision && video.y < evidence.y && evidence.y < decision.y);
  assert.equal(
    await seller.locator("details.model-details").evaluate((details) => details.open),
    false,
  );
  await seller.screenshot({ path: join(dir, "mobile-seller.png"), fullPage: true });
  await seller.getByLabel("Decision", { exact: true }).selectOption("side_buyer");
  await seller.locator("textarea").fill("   ");
  await seller.getByRole("button", { name: "Save decision" }).click();
  await seller.getByRole("alert").getByText("Enter an explanation for the buyer.").waitFor();
  await seller
    .locator("textarea")
    .fill("We checked the parcel and will contact you about the missing part.");
  await seller.getByRole("button", { name: "Save decision" }).click();
  await seller.getByRole("heading", { name: "Decision saved" }).waitFor();
  await seller.getByRole("button", { name: "Next case" }).click();
  // Other ready sample cases may be ahead of the second report in a shared rehearsal store.
  await seller.getByRole("heading", { name: "Shop decision" }).waitFor();
  await first.page
    .getByText("We checked the parcel and will contact you about the missing part.")
    .waitFor();
  assert.equal(await first.page.getByText("Model details", { exact: true }).count(), 0);
  assert.equal((await second.page.request.get("/api/cases/" + second.id)).ok(), true);
  console.log(
    "Mobile seller: evidence order, required explanation, next case and buyer reply passed.",
  );
} finally {
  await safari?.close();
  await android.close();
}
