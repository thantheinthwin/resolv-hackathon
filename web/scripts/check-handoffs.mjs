import { chromium } from "playwright";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const browser = await chromium.launch({ channel: "chrome" });
const baseURL = process.env.REHEARSAL_URL || "http://127.0.0.1:3000";
const dir = process.env.REHEARSAL_DIR || "../data/rehearsal";
try {
  const desktop = await browser.newPage({ baseURL, viewport: { width: 1300, height: 900 } });
  await desktop.goto("/");
  await desktop.getByText("Continue as buyer").click();
  await desktop.getByText("Report a problem").click();
  const create = desktop.waitForResponse((r) => r.url().endsWith("/api/cases"));
  await desktop.getByText("Continue to video").click();
  const { id } = await (await create).json();
  await desktop.getByText("Upload from phone").click();
  const url = await desktop.getByText("Open phone upload").getAttribute("href");
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
  assert.equal(
    (
      await phone.request.post("/api/uploads/" + token, {
        multipart: {
          video: {
            name: "x.mp4",
            mimeType: "video/mp4",
            buffer: await readFile(dir + "/sample.mp4"),
          },
        },
      })
    ).status(),
    404,
  );
  await desktop.getByRole("button", { name: /Unboxing Judge/ }).click();
  await desktop.getByText("Continue as shop owner").click();
  await desktop.route("**/api/shop/cases/" + id, async (route) => {
    const res = await route.fetch();
    const c = await res.json();
    c.verdict.evidence = [{ t: 2, check: "listing", result: "flag", frame: "frame.jpg" }];
    c.verdict.display = "clear";
    c.verdict.verdict = "buyer_right";
    await route.fulfill({ json: c });
  });
  await desktop
    .locator('[data-case="' + id + '"]')
    .getByText("Review case")
    .click();
  await desktop
    .locator("video")
    .evaluate(
      (v) =>
        v.readyState >= 1 ||
        new Promise((r) => v.addEventListener("loadedmetadata", r, { once: true })),
    );
  await desktop.getByText("2s · listing").click();
  await desktop.waitForFunction(
    () => Math.abs(document.querySelector("video").currentTime - 2) < 0.1,
  );
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
  await desktop.locator("input[type=file]").setInputFiles(dir + "/screen-01.png");
  await desktop.getByText("Save product").click();
  await desktop.getByText("Walkthrough sample", { exact: true }).first().waitFor();
  console.log(
    "Passed emulated phone upload, desktop confirmation, spent token rejection, fixture evidence seek, disagreement validation and product creation.",
  );
} finally {
  await browser.close();
}
