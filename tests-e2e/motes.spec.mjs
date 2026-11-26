// Spend your motes in a real browser (Chromium), served by `wrangler pages dev` with the production headers (Trusted Types and the content security policy included): the box at the end
// of the Upgrade section that opens it, the best kit of the page (read from Wear this) and the gear (the kit Equip now wears), the number of motes, a change of the page's view while the
// panel is open, the keyboard, the narrow window (360 px) and the accessibility checks in the four views.
//
// The numbers are those of Python's reference (fixtures/site/mote-orders.json, made by pipeline/tests/engine_fixture.py), written the way the page writes a difference; the page code
// is not asked what they should be. The fixture's items are invented, so the tests that read them are skipped on real results (TRIOFORGE_RESULTS); the ones that need no name run on both.
//
// A test without @once in its title runs in the four views (a 1280 px and a 360 px wide window, in light and in dark).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ROOT, TRIO, axe, expect, fmtInt, fmtSigned, focusRingWidth, open, openSwitches, pick, tabTo, test } from "./support.mjs";

const FIXTURE = !process.env.TRIOFORGE_RESULTS;
const REAL_RESULTS = "the numbers are those of the synthetic fixture's invented items, which real results do not have";
const { cases } = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/mote-orders.json"), "utf8"));
const BAKED = cases.find((row) => row.name.startsWith("the best kit of the fixture's baked page"));
const GEAR = cases.find((row) => row.name.startsWith("the kit Equip now finds for the gear of the browser test"));
const NAMES = new Map(JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/results/items.json"), "utf8")).items.map((item) => [item.id, item.name]));
const nameOf = (key) => NAMES.get(Number(key.slice(1))) ?? key;
const dump = (name) => readFileSync(resolve(ROOT, "fixtures", "dumps", `${name}.txt`), "latin1").split("\r\n").join("\n").split("\n").join("\r\n");

const number = (fraction) => Number(BigInt(fraction.split("/")[0])) / Number(BigInt(fraction.split("/")[1]));
/** A change in kit value as the page writes a difference: half up, "+<1" for a gain that rounds to nothing. */
function signed(value) {
  const shown = Math.floor(value + 0.5);
  if (shown === 0 && value > 0) return "+<1";
  if (shown === 0 && value < 0) return `${fmtSigned(-1).slice(0, -1)}<1`;
  return fmtSigned(shown);
}
const STATS = new Map([["HASTE", "Haste"], ["FIRE", "FR"], ["COLD", "CR"], ["MAGIC", "MR"], ["POISON", "PR"], ["DISEASE", "DR"], ["MANA", "Mana"], ["END", "End"], ["HPREG", "HP regen"], ["MANAREG", "Mana regen"], ["ENDREG", "End regen"], ["DMG", "Damage"]]); // prettier-ignore

const box = (page) => page.locator("#upgrade-motes-open");
const panel = (page) => page.locator("#upgrade-motes");
const list = (page) => page.locator("#upgrade-motes-list > li");
const slotLabels = (page) => page.$$eval("#kit-body tr th", (cells) => cells.map((cell) => cell.textContent));
/** The line Python recorded for a step, as the page words it, with the labels of the places that the page uses: "Chest: <item> +7 to +8, +142". */
const lineOf = (labels, step) => `${labels[step.place]}: ${nameOf(step.key)} +${step.from} to +${step.to}, ${signed(number(step.gain))}`;
const factsOf = (step) => [...(step.moved.length === 0 ? [] : [step.moved.map(([name, amount]) => `${STATS.get(name) ?? name} ${signed(number(amount))}`).join(", ")]), `kit value ${fmtInt(Math.floor(number(step.F) + 0.5))}`];
/** Tick the box the way a visitor does: a click on its label (the check box lies invisibly over it). */
const tickBox = (page) => page.locator('label[for="upgrade-motes-open"]').click();
/** Open the page and the panel, on the page's own kit. */
async function opened(page) {
  await open(page, TRIO);
  await tickBox(page);
  await expect(panel(page)).toBeVisible({ timeout: 30_000 });
}
/** Drop a file of /outputfile inventory on the section the way a browser does. */
async function dropFile(page, text, name = "inventory.txt") {
  const dataTransfer = await page.evaluateHandle(
    ([content, fileName]) => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([content], fileName, { type: "text/plain" }));
      return transfer;
    },
    [text, name],
  );
  for (const type of ["dragenter", "dragover", "drop"]) await page.dispatchEvent("#upgrade-drop", type, { dataTransfer });
}
const yes = (page) => page.locator("#upgrade-results .engine-consent").getByRole("button", { name: /^Load the optimizer \(about/ });

// ---- loaded when it is used ----------------------------------------------------------------------------------------------------------------

test("nothing of the panel is fetched before its box is used; the box then fetches the evaluator, the bundle of the trio and the item list, and never the optimizer @once", async ({ page, watch }) => {
  const seen = [];
  page.on("request", (request) => seen.push(new URL(request.url()).pathname));
  await open(page, TRIO);
  expect(seen.filter((path) => /upgrade-input|engine-manifest|\/assets\/engine\//.test(path)), "nothing of the section before it is used").toEqual([]);
  await expect(box(page)).toBeEnabled();
  await expect(page.locator("#upgrade-motes")).toHaveCount(0);
  await tickBox(page);
  await expect(list(page).first()).toBeVisible({ timeout: 30_000 });
  expect(seen.filter((path) => /^\/assets\/engine\/kitvalue-[A-Z0-9]{8}\.js$/.test(path)), "the evaluator is asked for to be checked and to be run").toHaveLength(2);
  expect(seen.filter((path) => /^\/assets\/engine\/data\/pal-mnk-ber-l50-[A-Z0-9]{16}\.json$/.test(path))).toHaveLength(1);
  expect(seen.filter((path) => /^\/assets\/engine\/data\/items-[A-Z0-9]{16}\.json$/.test(path))).toHaveLength(1);
  expect(seen.filter((path) => /\/assets\/engine\/(client|worker|highs)-/.test(path)), "no worker, no solver and no question: the order is worked out by the evaluator").toEqual([]);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(watch.problems()).toEqual([]);
});

// ---- the best kit of the page ---------------------------------------------------------------------------------------------------------------

test("the panel says what it is, and the best kit of the page is its first choice when there is no gear", async ({ page, watch }) => {
  await opened(page);
  await expect(page.locator("#upgrade-motes-h")).toHaveText("Spend your motes");
  await expect(panel(page)).toContainText("A mote gives one whole tier at any tier, so it saves the most work on the highest tiers.");
  await expect(panel(page)).toContainText("This is the best single next step, not a proven best plan for the motes you have");
  await expect(page.locator("#upgrade-motes-source-page")).toBeChecked();
  await expect(box(page)).toHaveAttribute("aria-expanded", "true");
  await expect(list(page).first()).toBeVisible({ timeout: 30_000 });
  expect(watch.problems()).toEqual([]);
});

test("the list for the kit Wear this shows is the order Python recorded, line by line, with the stats that moved and the kit value, and ends by saying so", async ({ page, watch }) => {
  test.skip(!FIXTURE, REAL_RESULTS);
  await opened(page);
  // (T1: the best kit of the fixture's baked page wears an item whose only stat is attack, which no tier grows, so six motes could still be spent and none of them gains anything)
  await expect(page.locator("#upgrade-motes-end")).toHaveText("After these, no mote adds any kit value: 6 could still be spent, and none of them gains anything.", { timeout: 30_000 });
  const labels = await slotLabels(page);
  await expect(list(page)).toHaveCount(BAKED.steps.length);
  expect(await page.$$eval("#upgrade-motes-list > li .step-what", (nodes) => nodes.map((node) => node.textContent))).toEqual(BAKED.steps.map((step) => lineOf(labels, step)));
  expect(await page.$$eval("#upgrade-motes-list > li", (items) => items.map((item) => [...item.querySelectorAll(".owned-meta")].map((node) => node.textContent)))).toEqual(BAKED.steps.map(factsOf));
  await expect(page.locator("#announce")).toContainText(`First: ${lineOf(labels, BAKED.steps[0])}.`);
  expect(watch.problems()).toEqual([]);
});

test("a number of motes limits the list to the first lines of the order, an empty box gives it all again, and a number that is no number is refused", async ({ page, watch }) => {
  await opened(page);
  await expect(page.locator("#upgrade-motes-end")).not.toHaveText("", { timeout: 30_000 });
  const whole = await list(page).count();
  expect(whole).toBeGreaterThan(5);
  const first = await page.$$eval("#upgrade-motes-list > li .step-what", (nodes) => nodes.map((node) => node.textContent));
  const entry = page.getByLabel("Motes to spend");
  await entry.fill("5");
  await expect(list(page)).toHaveCount(5);
  expect(await page.$$eval("#upgrade-motes-list > li .step-what", (nodes) => nodes.map((node) => node.textContent))).toEqual(first.slice(0, 5));
  await expect(page.locator("#upgrade-motes-end")).toHaveText("These are the first 5 motes.");
  await entry.fill("0");
  await expect(entry).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#upgrade-motes-bad")).toHaveText("Use a whole number of motes from 1, or leave the box empty.");
  await entry.fill("99999999999"); // (more than there are to spend: the whole order)
  await expect(entry).toHaveAttribute("aria-invalid", "false");
  await expect(list(page)).toHaveCount(whole, { timeout: 30_000 });
  await entry.fill("5");
  await expect(list(page)).toHaveCount(5);
  await entry.fill("0");
  await expect(list(page)).toHaveCount(5);
  await entry.fill("");
  await expect(list(page)).toHaveCount(whole);
  await expect(entry).toHaveAttribute("aria-invalid", "false");
  expect(watch.problems()).toEqual([]);
});

test("the controls of the panel are where they were before the list came, and the page does not scroll sideways at either width", async ({ page, watch }) => {
  // the evaluator's data comes slowly, so that the panel can be seen before its list
  await page.route(/\/assets\/engine\/data\/pal-mnk-ber-l50-/, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.continue();
  });
  await open(page, TRIO);
  await tickBox(page);
  await expect(page.locator("#upgrade-motes-state")).toContainText("Working out the order of motes", { timeout: 20_000 });
  const places = () =>
    page.evaluate(() => {
      const at = (selector) => {
        const rect = document.querySelector(selector).getBoundingClientRect();
        return [Math.round(rect.left * 10) / 10, Math.round((rect.top + window.scrollY) * 10) / 10, Math.round(rect.width * 10) / 10, Math.round(rect.height * 10) / 10];
      };
      return ["#upgrade-motes-h", "#upgrade-motes fieldset", "#upgrade-motes-n", "#upgrade-motes-help", "#upgrade-motes-open"].map(at);
    });
  const before = await places();
  await expect(list(page).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#upgrade-motes-end")).not.toHaveText("", { timeout: 30_000 });
  expect(await places(), "nothing above the list moved when it arrived").toEqual(before);
  const wide = await page.evaluate(() => ({ sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth, window: window.innerWidth, right: Math.max(...[...document.querySelectorAll("#upgrade-motes, #upgrade-motes *")].filter((node) => node.getClientRects().length > 0).map((node) => node.getBoundingClientRect().right)) }));
  expect(wide.sideways, "no sideways scroll").toBeLessThanOrEqual(0);
  expect(wide.right, "nothing of the panel is wider than the window").toBeLessThanOrEqual(wide.window + 0.5);
  expect(watch.problems()).toEqual([]);
});

test("the panel has no serious accessibility violation, with its list, in the view", async ({ page }, testInfo) => {
  await opened(page);
  await expect(page.locator("#upgrade-motes-end")).not.toHaveText("", { timeout: 30_000 });
  await axe(page, testInfo);
});

// ---- the keyboard -----------------------------------------------------------------------------------------------------------------------------

test("the box is reached with Tab, opens with the space key and keeps the focus, and the choices, the number and the list are used with the keyboard alone", async ({ page, watch }) => {
  await open(page, TRIO);
  await page.locator("#upgrade-pick").focus(); // (the first use of the section: its code and its item list come)
  await expect(page.locator("#upgrade-add")).toBeEnabled();
  await tabTo(page, "#upgrade-motes-open", 12);
  expect(await focusRingWidth(page), "the box shows that it has the focus").toBeGreaterThan(0);
  await page.keyboard.press("Space");
  await expect(panel(page)).toBeVisible();
  await expect(box(page)).toBeChecked();
  await expect(box(page)).toHaveAttribute("aria-expanded", "true");
  await expect(box(page)).toBeFocused();
  await expect(list(page).first()).toBeVisible({ timeout: 30_000 });
  await expect(box(page), "the list coming in did not take the focus").toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Void-touched mote" })).toBeFocused(); // (the link to the rule that says what a mote is comes first in the panel)
  await page.keyboard.press("Tab");
  await expect(page.locator("#upgrade-motes-source-page")).toBeFocused(); // (the chosen one of the two is the one in the tab order)
  await page.keyboard.press("ArrowUp"); // the gear, which has no kit here: it is said, and nothing is listed
  await expect(page.locator("#upgrade-motes-source-gear")).toBeChecked();
  await expect(page.locator("#upgrade-motes-state")).toContainText("There is no kit from Equip now yet.");
  await expect(list(page)).toHaveCount(0);
  await page.keyboard.press("ArrowDown");
  await expect(page.locator("#upgrade-motes-source-page")).toBeChecked();
  await expect(list(page).first()).toBeVisible({ timeout: 30_000 });
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Motes to spend")).toBeFocused();
  await page.keyboard.type("3");
  await expect(list(page)).toHaveCount(3);
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByLabel("Motes to spend")).toBeFocused();
  await box(page).focus();
  await page.keyboard.press("Space");
  await expect(panel(page)).toBeHidden();
  await expect(box(page)).toHaveAttribute("aria-expanded", "false");
  await expect(list(page)).toHaveCount(0);
  expect(watch.problems()).toEqual([]);
});

// ---- the page's view ------------------------------------------------------------------------------------------------------------------------

test("a change of the page's tier takes the list at once and works out the kit that is shown: a list of another kit is never on the page under it", async ({ page, watch }) => {
  test.skip(!FIXTURE, REAL_RESULTS);
  await opened(page);
  await expect(page.locator("#upgrade-motes-end")).not.toHaveText("", { timeout: 30_000 });
  const labels = await slotLabels(page);
  await page.evaluate(() => {
    // every frame: the tier the page shows, and the first line of the list
    window.__tfFrames = [];
    const sample = () => {
      window.__tfFrames.push({ tier: document.querySelector('#kit-body tr [data-f="tier"]')?.textContent ?? "", line: document.querySelector("#upgrade-motes-list > li .step-what")?.textContent ?? null });
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
  await openSwitches(page);
  await page.selectOption("#sw-tier", "0");
  await expect(page.locator('#kit-body tr [data-f="tier"]').first()).toHaveText("+0", { timeout: 30_000 });
  await expect(list(page).first()).toContainText("+0 to +1", { timeout: 30_000 });
  await expect(page.locator("#upgrade-motes-end")).not.toHaveText("", { timeout: 30_000 });
  expect(await list(page).count(), "twenty-one items, from +0 to +10").toBe(210);
  await page.selectOption("#sw-tier", "10");
  await expect(page.locator("#upgrade-motes-end")).toHaveText("Every item is at +10, so there is nothing to spend a mote on.", { timeout: 30_000 });
  await expect(list(page)).toHaveCount(0);
  await page.selectOption("#sw-tier", "4");
  await expect(list(page)).toHaveCount(BAKED.steps.length, { timeout: 30_000 });
  expect(await page.$$eval("#upgrade-motes-list > li .step-what", (nodes) => nodes.map((node) => node.textContent))).toEqual(BAKED.steps.map((step) => lineOf(labels, step)));
  const frames = await page.evaluate(() => window.__tfFrames);
  expect(frames.length).toBeGreaterThan(10);
  for (const frame of frames) {
    if (frame.line === null) continue;
    const tier = frame.tier.replace("+", "");
    if (/^\d+$/.test(tier)) expect(frame.line, `a frame that shows ${frame.tier} with a list of another kit`).toMatch(new RegExp(` \\+${tier} to \\+${Number(tier) + 1}, `));
  }
  expect(watch.problems()).toEqual([]);
});

test("the list follows the buffs of the page: the group buffs are another published kit, and the raid, which the shards do not answer, has none @once", async ({ page, watch }) => {
  test.skip(!FIXTURE, REAL_RESULTS);
  await opened(page);
  await expect(page.locator("#upgrade-motes-end")).not.toHaveText("", { timeout: 30_000 });
  await openSwitches(page);
  await page.locator("#assume-buffs > summary").click();
  await pick(page, "buffs-group");
  await expect(page.locator("#assume-buffs [data-f='assume-buffs']")).toContainText(/group/i, { timeout: 30_000 });
  await expect(list(page).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#upgrade-motes-for")).toContainText("group", { ignoreCase: true });
  // the full raid is not a view the shards answer: Wear this shows the optimizer's answer for it, and the panel says that it has no published kit, and lists nothing
  await pick(page, "buffs-raid");
  await expect(page.locator("#assume-buffs [data-f='assume-buffs']")).toContainText(/raid/i, { timeout: 30_000 });
  await expect(page.locator("#upgrade-motes-state")).toContainText("not a published one", { timeout: 30_000 });
  await expect(list(page)).toHaveCount(0);
  await expect(page.locator("#upgrade-motes-for")).toBeHidden();
  expect(watch.problems()).toEqual([]);
});

// ---- the gear ---------------------------------------------------------------------------------------------------------------------------------

test("the gear: the order for the kit Equip now wears is the one Python recorded for it, and it goes the moment the view changes, to come back with the new Equip now @once", async ({ page, watch }) => {
  test.skip(!FIXTURE, REAL_RESULTS);
  test.setTimeout(300_000);
  await open(page, TRIO);
  await dropFile(page, dump("site-small"));
  await expect(page.locator("#upgrade-owned > li")).toHaveCount(12);
  await yes(page).click({ timeout: 60_000 });
  await expect(page.locator("#upgrade-equip")).toBeVisible({ timeout: 120_000 });
  await tickBox(page);
  await expect(page.locator("#upgrade-motes-source-gear")).toBeChecked(); // (Equip now has a kit: the gear is the first choice)
  const labels = await slotLabels(page);
  await page.getByLabel("Motes to spend").fill(String(GEAR.motes));
  await expect(list(page)).toHaveCount(GEAR.motes, { timeout: 30_000 });
  expect(await page.$$eval("#upgrade-motes-list > li .step-what", (nodes) => nodes.map((node) => node.textContent))).toEqual(GEAR.steps.map((step) => lineOf(labels, step)));
  await expect(page.locator("#upgrade-motes-for")).toContainText("your gear");
  // a change of the view: Equip now is worked out again, and the order of the old kit goes at once and is never drawn again for the new view
  await page.evaluate(() => {
    window.__tfGear = [];
    const sample = () => {
      window.__tfGear.push(document.querySelectorAll("#upgrade-motes-list > li").length);
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
  await openSwitches(page);
  await pick(page, "role-melee"); // (the page opens on the Tank: another build is another view)
  await expect(list(page)).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator("#upgrade-motes-state")).toContainText(/Waiting for Equip now's kit/, { timeout: 30_000 });
  await expect(page.locator("#upgrade-equip")).toBeVisible({ timeout: 120_000 });
  await expect(list(page).first()).toBeVisible({ timeout: 120_000 });
  expect(watch.problems()).toEqual([]);
});
