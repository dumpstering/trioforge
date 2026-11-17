// Where a donor comes from, in a real browser (branch exalt-source): under a place of Wear this the word for how hard the donor is to get ("Drop", "Quest or crafted") is a button that opens the texts of the
// Source column of a kit row that say where the donor comes from, beneath the line, and the plan and the lists of the section Effects to exalt show the first of them in plain view beside each donor.
//
// A test without @once runs in the four views of playwright.config.mjs (1280 and 360 px wide, light and dark). The page is the fixture's with the effects layer (the second preview), whose file has no
// texts (it is built without the catalog): tests-e2e/exalt-source-support.mjs gives each donor a list on the way to the page, and the tests hold the page to what it was given. That the build writes the
// texts, in the Source column's words and in the order the word names, is held by pipeline/tests/test_site_exalt_source.py; that the Stats button neither moves nor meets a word with a text open is in layout.spec.mjs.

import { EXALT_ORIGIN } from "../playwright.config.mjs";
import { SOURCE_LISTS, moreOf, textsOf, withDonorSources } from "./exalt-source-support.mjs";
import { TRIO, axe, expect, open, openSwitches, optionValues, readControls, test } from "./support.mjs";

test.use({ baseURL: EXALT_ORIGIN });

const buttons = (page) => page.locator("#kit-body .exalt-hint .exalt-srcbtn");
/** The name of the donor in the accessible name of a button ("Drop: where Crown of the Vanguard comes from"). */
const nameOf = async (button) => /^[^:]+: where (.+) comes from$/.exec((await button.getAttribute("aria-label")) ?? "")?.[1];

async function openSection(page) {
  await page.locator("#exalt > summary").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#exalt > summary")).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#exalt-plan-table")).toBeVisible();
}

test("the word for how hard a donor is to get is a button with a name that starts with the word and says what it opens, a target of at least 24 px, and the texts are not shown until they are asked for", async ({ page, watch }) => {
  const data = await withDonorSources(page);
  await open(page, TRIO);
  const first = buttons(page).first();
  await expect(first).toBeVisible();
  await expect(first).toHaveAttribute("aria-expanded", "false");
  await expect(first).toHaveAccessibleName(/^(Vendor|Quest or crafted|Drop|Raid drop): where .+ comes from$/);
  expect(await page.getByRole("button", { name: /^(Vendor|Quest or crafted|Drop|Raid drop): where .+ comes from$/ }).count()).toBeGreaterThan(0);
  const box = await first.boundingBox();
  expect(box.height, "a target of at least 24 px").toBeGreaterThanOrEqual(24);
  expect(box.width).toBeGreaterThanOrEqual(24);
  const panel = page.locator(`#${await first.getAttribute("aria-controls")}`);
  await expect(panel).toBeHidden();
  const word = (await first.textContent()) ?? "";
  expect((await first.getAttribute("aria-label")).startsWith(`${word}: where `), "the name starts with what the button shows").toBe(true);
  expect(data.file).not.toBeNull();
  expect(watch.problems()).toEqual([]);
});

test("the bracket, the word and the bracket are one piece that never splits over two lines, and the link to the item's page does not break in two", async ({ page, watch }) => {
  await withDonorSources(page);
  await open(page, TRIO);
  await expect(buttons(page).first()).toBeVisible();
  for (const button of await buttons(page).all()) {
    await button.click();
    const unit = await button.evaluate((node) => {
      const piece = node.parentElement;
      return { rects: piece.getClientRects().length, style: getComputedStyle(piece).whiteSpace, text: piece.textContent, before: piece.previousSibling?.textContent.slice(-1), after: piece.nextSibling?.textContent.slice(0, 1) };
    });
    expect(unit.rects, `${unit.text} is on one line`).toBe(1);
    expect(unit.style).toBe("nowrap");
    expect(unit.text).toMatch(/^\((Vendor|Quest or crafted|Drop|Raid drop)\)$/);
    expect(unit.before).toBe(" ");
    expect(unit.after).toBe(";");
  }
  for (const link of await page.locator("#kit-body .exalt-src-page").all()) {
    const found = await link.evaluate((node) => ({ rects: node.getClientRects().length, style: getComputedStyle(node).whiteSpace }));
    expect(found).toEqual({ rects: 1, style: "nowrap" });
  }
  expect(watch.problems()).toEqual([]);
});

test("a keyboard opens and closes the texts, which say where the donor comes from, and the focus stays on the button", async ({ page, watch }) => {
  const data = await withDonorSources(page);
  await open(page, TRIO);
  const line = page.locator("#kit-body .exalt-hint", { has: page.locator(".exalt-srcbtn") }).first();
  await expect(line).toBeVisible();
  const open_ = line.locator(".exalt-srcbtn");
  // Tab goes from the name of the effect to the button: it is a stop of the page's order, in the line
  await line.locator(".exalt-eff button").focus();
  await page.keyboard.press("Tab");
  await expect(open_).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(open_).toHaveAttribute("aria-expanded", "true");
  const panel = line.locator(".exalt-src");
  await expect(panel).toBeVisible();
  const donor = await nameOf(open_);
  const entry = data.file.src[data.keyOf(donor)];
  await expect(panel.locator(".exalt-src-text")).toHaveText(textsOf(entry));
  await expect(panel.locator(".exalt-src-label")).toHaveText("Where:");
  await expect(panel).toHaveAccessibleName(`Where ${donor} comes from`);
  if (moreOf(entry) > 0) await expect(panel.locator(".exalt-src-more")).toHaveText(`and ${moreOf(entry)} more on the item page`);
  await expect(open_).toBeFocused();
  await page.keyboard.press("Space");
  await expect(open_).toHaveAttribute("aria-expanded", "false");
  await expect(panel).toBeHidden();
  await page.keyboard.press("Enter");
  await expect(panel).toBeVisible();
  expect(watch.problems()).toEqual([]);
});

test("every line of the kit says where its donor comes from, all the texts the file says in the order it says them, and the text is text", async ({ page, watch }) => {
  const data = await withDonorSources(page);
  await open(page, TRIO);
  await expect(buttons(page).first()).toBeVisible();
  const count = await buttons(page).count();
  expect(count).toBeGreaterThan(3);
  const seen = new Set();
  for (let n = 0; n < count; n += 1) {
    const button = buttons(page).nth(n);
    await button.click();
    const panel = page.locator(`#${await button.getAttribute("aria-controls")}`);
    await expect(panel).toBeVisible();
    const entry = data.file.src[data.keyOf(await nameOf(button))];
    await expect(panel.locator(".exalt-src-text")).toHaveText(textsOf(entry));
    await expect(panel.locator(".exalt-src-more")).toHaveCount(moreOf(entry) > 0 ? 1 : 0);
    seen.add(entry.length);
  }
  expect(await page.locator("#kit-body .exalt-src b").count(), "no markup came out of a text").toBe(0);
  const lines = await page.locator("#kit-body .exalt-hint").count();
  expect(lines, "a line for each donor that has a text, and a button in each").toBe(count);
  if (data.file.src && Object.values(data.file.src).some((entry) => SOURCE_LISTS.some((one) => JSON.stringify(one) === JSON.stringify(entry)))) expect(seen.size, "lists of different lengths were opened").toBeGreaterThan(1);
  expect(watch.problems()).toEqual([]);
});

test("axe finds nothing wrong with texts open, in the colours of the theme of this view", async ({ page, watch }, testInfo) => {
  await withDonorSources(page);
  await open(page, TRIO);
  const first = buttons(page).first();
  await expect(first).toBeVisible();
  await first.click();
  await expect(page.locator(`#${await first.getAttribute("aria-controls")}`)).toBeVisible();
  await buttons(page).nth(1).click();
  await buttons(page).nth(2).click();
  await axe(page, testInfo);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "no sideways scroll with texts open").toBeLessThanOrEqual(0);
  expect(watch.problems()).toEqual([]);
});

test("the section's plan shows where each donor comes from in plain view, the first text and +N more as a link to the item's page, and its list of donors to farm and its ranked lists do too", async ({ page, watch }, testInfo) => {
  const data = await withDonorSources(page);
  await open(page, TRIO);
  await expect(buttons(page).first()).toBeVisible();
  await openSection(page);
  const plan = page.locator("#exalt-plan-table .exalt-from");
  expect(await plan.count()).toBeGreaterThan(0);
  const firsts = new Set(Object.values(data.file.src).map((entry) => textsOf(entry)[0]));
  for (const node of await plan.all()) {
    await expect(node).toBeVisible();
    expect(firsts.has((await node.textContent()) ?? ""), await node.textContent()).toBe(true);
  }
  const row = page.locator("#exalt-plan-table tbody tr", { has: page.locator(".exalt-from") }).first();
  await expect(row).toContainText("From ");
  await expect(row.locator(".exalt-from").first()).toBeVisible();
  // a donor with other sources has "+N more", a link to its page, in plain view, with a name of its own
  const more = page.locator("#exalt-plan-table a.exalt-more");
  expect(await more.count()).toBeGreaterThan(0);
  for (const link of await more.all()) {
    await expect(link).toBeVisible();
    expect(await link.getAttribute("href")).toMatch(/^\/item\/[^/]+\/$/);
    expect((await link.getAttribute("aria-label")) ?? "").toMatch(/^\+\d+ more sources of .+, on its item page$/);
    expect(await link.evaluate((node) => ({ rects: node.getClientRects().length, style: getComputedStyle(node).whiteSpace }))).toEqual({ rects: 1, style: "nowrap" });
  }
  const farm = page.locator("#exalt-donors .exalt-from");
  expect(await farm.count()).toBeGreaterThan(0);
  await expect(farm.first()).toBeVisible();
  const listed = page.locator("#exalt-lists .exalt-from");
  expect(await listed.count()).toBeGreaterThan(0);
  await expect(listed.first()).toBeVisible();
  // the texts are those of the file
  for (const text of new Set(await page.locator("#exalt-body .exalt-from").allTextContents())) expect(firsts.has(text), text).toBe(true);
  await axe(page, testInfo);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "no sideways scroll with the section open").toBeLessThanOrEqual(0);
  const wide = await page.$$eval("#exalt-body table", (tables) => tables.filter((t) => t.scrollWidth > t.parentElement.clientWidth + 1).length);
  expect(wide, "no table wider than the section").toBe(0);
  expect(watch.problems()).toEqual([]);
});

test("the kit of another tier has its lines with their texts again, and asks for no new file", async ({ page, watch }) => {
  const data = await withDonorSources(page);
  const asked = [];
  page.on("request", (request) => asked.push(new URL(request.url()).pathname));
  await open(page, TRIO);
  await expect(buttons(page).first()).toBeVisible();
  const controls = await readControls(page);
  const tiers = (await optionValues(page, "#sw-tier")).map(Number).filter((tier) => tier !== controls.tier && tier >= 1);
  await openSwitches(page);
  await page.locator("#sw-tier").selectOption(String(tiers.sort((a, b) => b - a)[0]));
  await expect(page.locator('#kit-caption [data-f="v-tier"]')).toContainText(`+${tiers[0]}`);
  await expect.poll(() => buttons(page).count()).toBeGreaterThan(0);
  for (const button of await buttons(page).all()) {
    await button.click();
    const entry = data.file.src[data.keyOf(await nameOf(button))];
    await expect(page.locator(`#${await button.getAttribute("aria-controls")}`).locator(".exalt-src-text")).toHaveText(textsOf(entry));
  }
  expect(asked.filter((path) => /effects\.json$/.test(path)), "the file with the texts is the one that was fetched, once").toHaveLength(1);
  expect(watch.problems()).toEqual([]);
});
