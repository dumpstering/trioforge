// What each race gets you, and the worn haste of a row, in a real browser (race-explain): the section of "How the best race was judged" shows a card for each race the page names (value, kit totals, starting stats,
// racial abilities said to be scored or not) and credits the wiki; a row of Wear this whose item has worn haste shows a chip without opening Stats; the totals say that only the highest worn haste counts.
//
// A test without @once runs in the four views of playwright.config.mjs (1280 and 360 px wide, light and dark). The fixture build's default view wears no worn haste, so the chip is looked for in the melee view,
// where the fixture's Gold Hoop of Haste is worn; the baked chip of a page whose default kit has worn haste is held by pipeline/tests/test_site_kit_haste.py and, on the real results, by the pictures of the build.

import { TRIO, axe, expect, open, openSwitches, pick, test } from "./support.mjs";

const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test("the section opens inside the expander with a card for the best race and the runner-up, and the page stays inside its window", async ({ page, watch }, testInfo) => {
  await open(page, TRIO);
  const details = page.locator("#race-why");
  await expect(details).not.toHaveAttribute("open", "");
  await expect(page.locator("#race-gets")).toBeHidden();
  await details.locator("summary").click();
  await expect(page.locator("#race-gets")).toBeVisible();
  const cards = page.locator("#race-gets .race-cards > li");
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0).locator("p").first()).toHaveText("Ogre best race");
  await expect(cards.nth(1).locator("p").first()).toHaveText("Troll runner-up");
  // the figures of the page, from the results: the best race's value, the runner-up's gap in the same words as the margin above
  await expect(cards.nth(0).locator("dt", { hasText: "Value" }).locator("xpath=following-sibling::dd[1]")).toHaveText("10,720");
  await expect(cards.nth(1).locator("dd").nth(1)).toHaveText("−813 (−7.58%)");
  await expect(cards.nth(1)).toContainText("Its best kit against Ogre's best kit");
  await expect(cards.nth(1)).toContainText("−80 HP, −40 attack, −10 AC");
  // every racial says whether it is scored; the fixture's two races score none of theirs
  const racials = page.locator("#race-gets dd ul li");
  expect(await racials.count()).toBeGreaterThan(5);
  for (const item of await racials.all()) await expect(item).toContainText("(not scored)");
  await expect(page.locator("#race-credit")).toHaveText("Racial abilities: eqlwiki, CC BY-SA 4.0 (pages and revisions)");
  await expect(page.locator("#race-credit a").first()).toHaveAttribute("href", "https://eqlwiki.com/");
  expect(await overflow(page), "no sideways scroll with the section open").toBeLessThanOrEqual(0);
  const box = await page.locator("#race-gets").boundingBox();
  const width = page.viewportSize().width;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width, "the section is inside the window").toBeLessThanOrEqual(width);
  await axe(page, testInfo);
  expect(watch.problems()).toEqual([]);
});

test("the section is plain text for a reader: terms and definitions, one list of racials in each card, the credit links open nothing else", async ({ page, watch }) => {
  await open(page, TRIO);
  await page.locator("#race-why summary").click();
  for (const card of await page.locator("#race-gets .race-cards > li").all()) {
    const terms = await card.locator("dt").allTextContents();
    expect(terms[0]).toBe("Value");
    expect(terms.at(-1)).toBe("Racial abilities");
    expect(await card.locator("dd").count()).toBe(terms.length);
  }
  const links = await page.locator("#race-credit a").evaluateAll((nodes) => nodes.map((node) => [node.getAttribute("href"), node.getAttribute("rel")]));
  expect(links).toEqual([
    ["https://eqlwiki.com/", "noopener noreferrer"],
    ["https://creativecommons.org/licenses/by-sa/4.0/legalcode", "noopener noreferrer"],
    ["/sources/#races-box", null],
  ]);
  expect(watch.problems()).toEqual([]);
});

test("a row whose item has worn haste shows the chip without opening its Stats, and the rows without it show none", async ({ page, watch }, testInfo) => {
  await open(page, TRIO);
  await expect(page.locator("#kit-body .kit-haste:visible")).toHaveCount(0); // (the default view wears none)
  await openSwitches(page);
  await pick(page, "role-melee");
  await expect(page.locator("#kit-caption")).toContainText("Melee");
  const chips = page.locator("#kit-body .kit-haste:visible");
  await expect(chips).toHaveCount(1);
  await expect(chips).toHaveText("Haste 19%");
  const row = page.locator("#kit-body tr").filter({ has: page.locator(".kit-haste:visible") });
  await expect(row.locator("th")).toHaveText("Ear 2");
  await expect(row.locator(".name")).toHaveText("Gold Hoop of Haste");
  await expect(row.locator('[data-f="stats"]')).toBeHidden(); // (the Stats panel is closed: the chip is what says it)
  await expect(row.locator("details.kit-more")).not.toHaveAttribute("open", "");
  expect(await overflow(page), "no sideways scroll with the chip").toBeLessThanOrEqual(0);
  await axe(page, testInfo);
  await page.locator("#sw-tier").selectOption("10");
  await expect(page.locator("#kit-body .kit-haste:visible")).toHaveText("Haste 25%");
  await pick(page, "role-tank");
  await expect(page.locator("#kit-caption")).toContainText("Tank");
  await expect(page.locator("#kit-body .kit-haste:visible")).toHaveCount(0);
  expect(watch.problems()).toEqual([]);
});

test("the haste row of the totals says that only the highest worn haste counts", async ({ page, watch }) => {
  await open(page, TRIO);
  const row = page.locator("#totals-body tr").filter({ has: page.locator('th:text-is("Haste")') });
  await expect(row.locator(".row-note")).toHaveText(/^Only the highest worn haste counts\./); // (T10: with a haste spell among the buffs the note goes on with the two answers)
  await expect(page.locator("#totals-body .row-note")).toHaveCount(1);
  expect(watch.problems()).toEqual([]);
});
