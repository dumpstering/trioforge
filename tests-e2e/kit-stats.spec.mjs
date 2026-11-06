// The stats and the why line of the rows of Wear this in a real browser (p7kit): a button under each name opens them (aria-expanded), the default view has the why line, every other view has
// the stats of its items and a note instead, and the page stays readable in a narrow window, in light and in dark.
//
// A test without @once runs in the four views of playwright.config.mjs (1280 and 360 px wide, light and dark). The pictures at the end are only taken when $TRIOFORGE_PICTURES names a folder.

import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { TRIO, axe, expect, loadShard, open, openSwitches, optionValues, readControls, test } from "./support.mjs";
import { test as plain } from "@playwright/test";

const toggles = (page) => page.locator("#kit-body .kit-more > summary:visible");

/** The stats the data file says an item has at a tier, for the item shown in a row. */
function statsOf(doc, tier, name) {
  const item = doc.items.find((entry) => entry[1] === name);
  return item[7][doc.stat_tiers.indexOf(tier)];
}

test("a button beside each name opens the stats and the why line, closed to begin with, with aria-expanded", async ({ page, watch }) => {
  await open(page, TRIO);
  const buttons = toggles(page);
  expect(await buttons.count()).toBeGreaterThanOrEqual(15);
  const first = buttons.first();
  await expect(first).toHaveAttribute("aria-expanded", "false");
  const panel = first.locator("xpath=..");
  await expect(panel.locator('[data-f="stats"]')).toBeHidden();
  await first.focus();
  await page.keyboard.press("Enter"); // a keyboard opens it, as a click does
  await expect(first).toHaveAttribute("aria-expanded", "true");
  await expect(panel.locator('[data-f="stats"]')).toBeVisible();
  await expect(panel.locator('[data-f="stats"]')).toContainText(/^AC \+\d+/);
  await expect(panel.locator('[data-f="why"]')).toContainText(/^Lost without it: /);
  await page.keyboard.press("Space");
  await expect(first).toHaveAttribute("aria-expanded", "false");
  await expect(panel.locator('[data-f="stats"]')).toBeHidden();
  expect(await first.evaluate((node) => node.getAttribute("aria-label"))).toMatch(/^Stats and why for /);
  expect(watch.problems()).toEqual([]);
});

test("the button that opens them all follows the rows, and the open page has nothing wrong with its colours or its targets", async ({ page, watch }, testInfo) => {
  await open(page, TRIO);
  const all = page.locator("#kit-stats-all");
  await expect(all).toHaveAttribute("aria-expanded", "false");
  await all.click();
  await expect(all).toHaveAttribute("aria-expanded", "true");
  for (const button of await toggles(page).all()) await expect(button).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#kit-body .kit-more[open]")).not.toHaveCount(0);
  await axe(page, testInfo);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "no sideways scroll with every row open").toBeLessThanOrEqual(0);
  await all.click();
  await expect(page.locator("#kit-body .kit-more[open]")).toHaveCount(0);
  expect(watch.problems()).toEqual([]);
});

test("another view shows the stats of its items at its tier and no why line, with the note", async ({ page, request, watch }) => {
  await open(page, TRIO);
  const shard = await loadShard(request, "strict", "own");
  const controls = await readControls(page);
  const tiers = await optionValues(page, "#sw-tier");
  const other = Number(tiers.find((tier) => tier !== String(controls.tier)));
  await expect(page.locator("#why-note")).toBeHidden();
  await openSwitches(page);
  await page.locator("#sw-tier").selectOption(String(other));
  await expect(page.locator("#kit-caption")).toContainText(`+${other}`);
  await page.locator("#kit-stats-all").click();
  const names = await page.$$eval("#kit-body tr", (rows) => rows.map((tr) => tr.querySelector('[data-f="name"]').textContent));
  const shown = await page.$$eval("#kit-body tr", (rows) => rows.map((tr) => tr.querySelector('[data-f="stats"]')?.textContent ?? ""));
  names.forEach((name, index) => {
    if (name === "Leave empty") return;
    expect(shown[index], name).toBe(statsOf(shard.doc, other, name));
  });
  await expect(page.locator("#kit-body .kit-why:visible")).toHaveCount(0);
  await expect(page.locator("#why-note")).toBeVisible();
  await expect(page.locator("#why-note")).toContainText("default view only");
  await page.locator("#sw-tier").selectOption(String(controls.tier)); // and back to the page's own view: the why line returns
  await expect(page.locator("#kit-body .kit-why:visible").first()).toContainText("Lost without it");
  await expect(page.locator("#why-note")).toBeHidden();
  expect(watch.problems()).toEqual([]);
});

// ---- the captures: a trio page with the rows open, at a phone's and a desktop's size, in light and in dark ------------------------------------------------

plain("screen captures of the trio page with the rows open @once", async ({ browser, baseURL }) => {
  const folder = process.env.TRIOFORGE_PICTURES;
  plain.skip(!folder, "TRIOFORGE_PICTURES names the folder the captures go to");
  mkdirSync(folder, { recursive: true });
  for (const [size, viewport] of [["phone-390x844", { width: 390, height: 844 }], ["desktop-1280x900", { width: 1280, height: 900 }]]) {
    for (const colorScheme of ["light", "dark"]) {
      const context = await browser.newContext({ viewport, colorScheme, baseURL });
      const page = await context.newPage();
      await page.goto(TRIO);
      await page.locator("#kit-stats-all").waitFor();
      await page.locator("#kit-stats-all").click();
      await page.locator("#wear-h").scrollIntoViewIfNeeded();
      const table = page.locator("section.answer");
      await table.screenshot({ path: resolve(folder, `trio-${size}-${colorScheme}-rows-open.png`) });
      await page.locator("#kit-stats-all").click();
      await table.screenshot({ path: resolve(folder, `trio-${size}-${colorScheme}-rows-closed.png`) });
      await page.locator("#kit-body .kit-more > summary:visible").first().click();
      await page.locator("#kit-body .kit-more > summary:visible").nth(1).click();
      await table.screenshot({ path: resolve(folder, `trio-${size}-${colorScheme}-two-rows-open.png`) });
      await context.close();
    }
  }
});
