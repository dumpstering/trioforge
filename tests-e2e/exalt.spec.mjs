// The section Effects to exalt of the trio page in a real browser (p7fx2): nothing of it is asked for before it is opened, it shows the plan for the kit, the ranked lists and the carry list
// with their marks, a kit that is not the one the files were made for gets its plan made again in the browser (the matcher is run here on the data read independently, so the page
// is checked against the data and not against its own code), and the open section keeps its colours and its targets in light and in dark, at a phone's width and a desktop's.
//
// A test without @once runs in the four views of playwright.config.mjs (1280 and 360 px wide, light and dark). The pictures at the end are only taken when $TRIOFORGE_PICTURES names a folder.

import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test as plain } from "@playwright/test";
import { PLACES, itemInfo, planKit } from "../pipeline/trioforge/site/static/ui/exalt-plan.js";
import { EXALT_ORIGIN, ORIGIN } from "../playwright.config.mjs";
import { DATA, ROOT, TRIO, axe, expect, loadShard, open, openSwitches, optionValues, readControls, test } from "./support.mjs";

// this page is the fixture's with the effects layer, served by the second preview of the configuration (its results are a copy of the fixture's with the layer's two files)
test.use({ baseURL: EXALT_ORIGIN });

const RESULTS = resolve(ROOT, process.env.TRIOFORGE_RESULTS ?? "fixtures/site/results");
const EFFECTS = "/data/effects.json";
const EXALT = `${DATA}exalt.json`;
const section = (page) => page.locator("#exalt");
const summary = (page) => page.locator("#exalt > summary");

async function files(request) {
  const [effects, exalt] = await Promise.all([request.get(EFFECTS), request.get(EXALT)]);
  expect(effects.ok() && exalt.ok(), "the two files can be fetched").toBe(true);
  return { effects: await effects.json(), exalt: await exalt.json() };
}

/** The table of items as the independent reader of the test has it: item key to what the matcher needs. */
function itemTable() {
  const table = JSON.parse(readFileSync(resolve(RESULTS, "items.json"), "utf8"));
  return new Map(table.items.map((record) => [record.key ?? `w${record.id}`, itemInfo(record, table.defaults)]));
}

async function openSection(page) {
  await summary(page).focus();
  await page.keyboard.press("Enter");
  await expect(summary(page)).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#exalt-plan-table")).toBeVisible();
}

/** What the plan of a role must be for the kit of a scenario, by the matcher on the data read here. */
function expectedPlan({ effects, exalt }, shard, table, { race, role, tier }) {
  const scenario = shard.scenario(race, role, tier, shard.best(race, role, tier));
  const kit = scenario.kit.map((item, index) => (item ? { place: PLACES[index], key: item[0] } : null)).filter(Boolean);
  const donors = new Map();
  for (const [key, entry] of Object.entries(effects.items)) {
    const [, , slots, classes, twoHand, arrival] = entry;
    donors.set(key, itemInfo({ slots: slots.split(" "), classes: classes.split(" "), weapon: { skill: twoHand ? "2H" : "" }, tier_rule: arrival === 4 ? "drop" : arrival === 0 ? "fixed0" : "spell" }));
  }
  const names = new Map(scenario.kit.filter(Boolean).map((item) => [item[0], item[1]]));
  const plan = planKit({
    options: exalt.roles[role],
    kit,
    items: (key) => table.get(key) ?? donors.get(key) ?? null,
    effects: new Map(effects.effects.map((row) => [row.id, row])),
    mass: effects.mass,
    classes: exalt.classes,
    tier,
  });
  const byId = new Map(effects.effects.map((row) => [row.id, row]));
  return { plan, rows: plan.rows.map((row) => ({ slot: row.p, host: names.get(row.h), effect: byId.get(row.e).n })), names };
}

// ---- nothing before the section is opened ---------------------------------------------------------------------------------------------------------------------

test("nothing of the section is asked for before it is opened, and its files come when it is @once", async ({ page, watch }) => {
  const asked = [];
  page.on("request", (request) => asked.push(new URL(request.url()).pathname));
  await open(page, TRIO);
  await page.waitForTimeout(800); // (time for anything the page would fetch by itself)
  expect(asked.filter((path) => /effects\.json|exalt\.json|\/assets\/exalt-/.test(path))).toEqual([]);
  await expect(summary(page)).toHaveAttribute("aria-expanded", "false");
  await expect(section(page)).not.toHaveAttribute("open", "");
  await summary(page).focus();
  await page.keyboard.press("Enter"); // a keyboard opens it
  await expect(summary(page)).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#exalt-plan-table")).toBeVisible();
  expect(asked.filter((path) => path === EFFECTS || path === EXALT).sort()).toEqual([EXALT, EFFECTS].sort());
  expect(asked.filter((path) => /\/assets\/exalt-/.test(path))).toHaveLength(1);
  await page.keyboard.press("Space"); // and closes it
  await expect(summary(page)).toHaveAttribute("aria-expanded", "false");
  expect(watch.problems()).toEqual([]);
  expect(watch.violations()).toEqual([]);
});

test("the files are fetched once, however often the section is opened", async ({ page, watch }) => {
  await open(page, TRIO);
  let count = 0;
  page.on("request", (request) => {
    if (/exalt\.json|effects\.json/.test(request.url())) count += 1;
  });
  await openSection(page);
  await summary(page).click();
  await summary(page).click();
  await expect(page.locator("#exalt-plan-table")).toBeVisible();
  expect(count).toBe(2);
  expect(watch.problems()).toEqual([]);
});

// ---- results made without the effects layer ------------------------------------------------------------------------------------------------------------------

test.describe("a page made from results that have no effects files", () => {
  test.use({ baseURL: ORIGIN }); // (the first preview: the results as they are)
  // (real results have the effects files, so the first preview has the section and there is nothing to check here: the fixture is the results that were made without them)
  test.skip(existsSync(resolve(RESULTS, "effects.json")), "these results have the effects files");

  test("has no section, and asks for nothing of it", async ({ page, watch }) => {
    const asked = [];
    page.on("request", (request) => asked.push(new URL(request.url()).pathname));
    await open(page, TRIO);
    await page.locator("#upgrade").scrollIntoViewIfNeeded();
    await expect(page.locator("#exalt")).toHaveCount(0);
    expect(await page.locator("main").innerText()).not.toContain("Effects to exalt");
    expect(asked.filter((path) => /effects\.json|exalt/.test(path))).toEqual([]);
    expect((await page.request.get("/data/effects.json")).status()).toBe(404);
    expect(watch.problems(["http"])).toEqual([]);
  });
});

// ---- what the section shows ------------------------------------------------------------------------------------------------------------------------------

test("the plan, the lists and the carry list are what the files say, in tables with headers", async ({ page, request, watch }) => {
  const { effects, exalt } = await files(request);
  const byId = new Map(effects.effects.map((row) => [row.id, row]));
  await open(page, TRIO);
  await openSection(page);
  const role = (await readControls(page)).role;
  const entry = exalt.roles[role];
  // the plan: one row for each placed effect, each row an item of the kit and an effect, in the order of the sockets
  await expect(page.locator("#exalt-plan-lead")).toContainText("as the site worked it out");
  const rows = await page.$$eval("#exalt-plan-table tbody tr", (trs) => trs.map((tr) => ({ slot: tr.querySelector("th .exalt-slot").textContent, effect: tr.cells[1].querySelector(".exalt-name").textContent, text: tr.textContent })));
  expect(rows.map((row) => row.effect)).toEqual(entry.plan.map((row) => byId.get(row.e).n));
  for (const row of rows) expect(row.text).toMatch(/opens at \+[1-4]/);
  for (const planned of entry.plan.filter((row) => row.u === 1)) expect(rows[entry.plan.indexOf(planned)].text).toContain("the donor needs");
  // the no-room line names every effect that has no place, with a reason
  const noroom = await page.locator("#exalt-noroom").textContent();
  for (const row of entry.noroom) expect(noroom).toContain(byId.get(row.e).n);
  // the lists: one table for each kind that has rows, with the rows in the order of the file, and column headers
  for (const kind of ["focus", "click", "worn", "proc", "carry"]) {
    const table = page.locator(`#exalt-${kind}`);
    if (entry[kind].length === 0) {
      await expect(table).toHaveCount(0);
      continue;
    }
    await expect(table.locator("thead th[scope='col']")).toHaveCount(2);
    await expect(table.locator("caption")).not.toBeEmpty();
    const names = await table.locator("tbody .exalt-name").allTextContents();
    expect(names).toEqual(entry[kind].map((row) => byId.get(row.e).n));
  }
  await expect(page.locator("#exalt-carry caption")).toContainText("Just carry");
  // a plain meaning, the tier the effect opens at, and where it can come from with a word for how hard it is
  const first = page.locator("#exalt-focus tbody tr").first();
  await expect(first).toContainText(/\d+(\.\d)?%? .*(faster casts|more spell damage|more healing|lower mana cost)/);
  await expect(first).toContainText("Opens at +1");
  await expect(first).toContainText(/touches \d+% of what your .+ casts at 30\+/);
  // (one dot for each item that carries the effect: the donor of the row, and the others after "Also:")
  await expect(page.locator("#exalt-focus tbody tr").first().locator(".exalt-dot")).toHaveCount(1 + (entry.focus[0].o ?? []).length);
  await expect(page.locator("#exalt-focus tbody tr").first()).toContainText(/Vendor|Quest or crafted|Drop|Raid drop|No known source/);
  expect(watch.problems()).toEqual([]);
});

test("a row built on an assumption has an unverified mark that opens its reason, and the types that lost have a why-not note", async ({ page, request, watch }) => {
  const { effects, exalt } = await files(request);
  await open(page, TRIO);
  await openSection(page);
  const role = (await readControls(page)).role;
  const marked = effects.effects.filter((row) => row.x.length > 0).map((row) => row.n);
  const shown = await page.locator("#exalt-body .exalt-mark").count();
  expect(shown).toBeGreaterThan(0);
  const mark = page.locator("#exalt-body .exalt-mark").first();
  await expect(mark).toHaveAttribute("aria-expanded", "false");
  const reason = page.locator(`#${await mark.getAttribute("aria-controls")}`);
  await expect(reason).toBeHidden();
  await mark.focus();
  await page.keyboard.press("Enter");
  await expect(mark).toHaveAttribute("aria-expanded", "true");
  await expect(reason).toBeVisible();
  await expect(reason).not.toBeEmpty();
  expect(marked.length).toBeGreaterThan(0);
  // a focus type whose families lost has a note, a disclosure with aria-expanded
  const lost = exalt.roles[role].focus.filter((row) => row.l.length > 0);
  expect(lost.length).toBeGreaterThan(0);
  const why = page.locator("#exalt-focus summary").first();
  await expect(why).toHaveAttribute("aria-expanded", "false");
  await why.focus();
  await page.keyboard.press("Enter");
  await expect(why).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#exalt-focus details[open]")).toContainText(lost[0].l[0]);
  expect(watch.problems()).toEqual([]);
});

// ---- the plan follows the kit ----------------------------------------------------------------------------------------------------------------------------

test("another role shows its own lists and its own plan, as the files have them", async ({ page, request, watch }) => {
  const { effects, exalt } = await files(request);
  const byId = new Map(effects.effects.map((row) => [row.id, row]));
  await open(page, TRIO);
  await openSection(page);
  await openSwitches(page);
  const roles = Object.keys(exalt.roles);
  const current = (await readControls(page)).role;
  const other = roles.find((role) => role !== current);
  await page.locator(`input[name="role"][value="${other}"]`).setChecked(true, { force: true });
  await expect.poll(async () => (await readControls(page)).role).toBe(other);
  await expect
    .poll(() => page.locator("#exalt-click tbody .exalt-name").allTextContents())
    .toEqual(exalt.roles[other].click.map((row) => byId.get(row.e).n));
  const rows = await page.$$eval("#exalt-plan-table tbody tr", (trs) => trs.map((tr) => tr.cells[1].querySelector(".exalt-name").textContent));
  expect(rows).toEqual(exalt.roles[other].plan.map((row) => byId.get(row.e).n));
  expect(watch.problems()).toEqual([]);
});

test("a kit that is not the one the files were made for gets its plan made again in the browser, and the lists stay", async ({ page, request, watch }) => {
  const data = await files(request);
  const table = itemTable();
  await open(page, TRIO);
  await openSection(page);
  await openSwitches(page);
  const controls = await readControls(page);
  const shard = await loadShard(request, controls.ev, controls.buffs); // (the shard of the evidence level and buffs the page is made from: the fixture's are strict and own, a release's wiki)
  const listBefore = await page.locator("#exalt-lists").innerText();
  const tiers = await optionValues(page, "#sw-tier");
  const lowest = tiers.map(Number).sort((a, b) => a - b)[0];
  expect(lowest).toBeLessThan(controls.tier);
  await page.locator("#sw-tier").selectOption(String(lowest));
  await expect(page.locator("#exalt-plan-lead")).toContainText("matched in your browser");
  const want = expectedPlan(data, shard, table, { race: controls.race, role: controls.role, tier: lowest });
  const got = await page.$$eval("#exalt-plan-table tbody tr", (trs) => trs.map((tr) => ({ slot: tr.querySelector("th .exalt-slot").textContent.trim(), effect: tr.cells[1].querySelector(".exalt-name").textContent })));
  expect(got.map((row) => row.effect)).toEqual(want.rows.map((row) => row.effect));
  // at +0 no socket is open: nothing is placed, every recommended effect is in the no-room line
  if (lowest === 0) {
    expect(want.plan.rows).toEqual([]);
    await expect(page.locator("#exalt-plan-table")).toHaveCount(1);
    await expect(page.locator("#exalt-noroom")).toContainText("below the tier its socket opens at");
  }
  // the lists do not depend on the kit
  expect(await page.locator("#exalt-lists").innerText()).toBe(listBefore);
  // and back at the default tier the plan is the one in the file again
  await page.locator("#sw-tier").selectOption(String(controls.tier));
  await expect(page.locator("#exalt-plan-lead")).toContainText("as the site worked it out");
  const back = await page.$$eval("#exalt-plan-table tbody tr", (trs) => trs.map((tr) => tr.cells[1].querySelector(".exalt-name").textContent));
  expect(back).toEqual(data.exalt.roles[controls.role].plan.map((row) => data.effects.effects.find((e) => e.id === row.e).n));
  expect(watch.problems()).toEqual([]);
});

test("another race gets the plan the matcher makes of its kit", async ({ page, request, watch }) => {
  const data = await files(request);
  const table = itemTable();
  await open(page, TRIO);
  await openSection(page);
  await openSwitches(page);
  const controls = await readControls(page);
  const shard = await loadShard(request, controls.ev, controls.buffs); // (the shard of the evidence level and buffs the page is made from: the fixture's are strict and own, a release's wiki)
  const races = await optionValues(page, "#sw-race");
  const other = races.find((race) => race !== controls.race);
  await page.locator("#sw-race").selectOption(other);
  await expect(page.locator("#exalt-plan-lead")).toContainText("matched in your browser");
  const want = expectedPlan(data, shard, table, { race: other, role: controls.role, tier: controls.tier });
  const got = await page.$$eval("#exalt-plan-table tbody tr", (trs) => trs.map((tr) => ({ slot: tr.querySelector("th .exalt-slot").textContent.trim(), host: tr.cells[0].textContent.trim(), effect: tr.cells[1].querySelector(".exalt-name").textContent })));
  expect(got.map((row) => row.effect)).toEqual(want.rows.map((row) => row.effect));
  expect(got.map((row) => row.host)).toEqual(want.rows.map((row) => row.host).map((name, index) => expect.stringContaining(name ?? "")));
  const item = await page.evaluate(() => performance.getEntriesByType("resource").map((entry) => new URL(entry.name).pathname));
  expect(item.filter((path) => /\/assets\/engine\/data\/items-/.test(path))).toHaveLength(1);
  expect(watch.problems()).toEqual([]);
});

// ---- the open section is readable --------------------------------------------------------------------------------------------------------------------------

test("the open section has nothing wrong with its colours or its targets and no sideways scroll", async ({ page, watch }, testInfo) => {
  await open(page, TRIO);
  await openSection(page);
  for (const mark of await page.locator("#exalt-body .exalt-mark").all()) await mark.click();
  for (const why of await page.locator("#exalt-focus summary").all()) await why.click();
  await axe(page, testInfo);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "no sideways scroll with the section open").toBeLessThanOrEqual(0);
  const wide = await page.$$eval("#exalt-body table", (tables) => tables.filter((t) => t.scrollWidth > t.parentElement.clientWidth + 1).length);
  expect(wide, "no table wider than the section").toBe(0);
  expect(watch.problems()).toEqual([]);
});

// ---- the pictures --------------------------------------------------------------------------------------------------------------------------------------------

plain("screen captures of the section at a phone's and a desktop's size, in light and in dark @once", async ({ browser }) => {
  const baseURL = EXALT_ORIGIN;
  const folder = process.env.TRIOFORGE_PICTURES;
  plain.skip(!folder, "TRIOFORGE_PICTURES names the folder the captures go to");
  mkdirSync(folder, { recursive: true });
  for (const [size, viewport] of [["phone-390x844", { width: 390, height: 844 }], ["desktop-1280x900", { width: 1280, height: 900 }]]) {
    for (const colorScheme of ["light", "dark"]) {
      const context = await browser.newContext({ viewport, colorScheme, baseURL });
      const page = await context.newPage();
      await page.goto(TRIO);
      await page.locator("#theme-toggle").waitFor();
      await summary(page).click();
      await page.locator("#exalt-plan-table").waitFor();
      await page.locator("#exalt-body .exalt-mark").first().click();
      await page.locator("#exalt-focus summary").first().click();
      await section(page).screenshot({ path: resolve(folder, `exalt-${size}-${colorScheme}-section.png`) });
      await page.locator("#exalt-plan-h").scrollIntoViewIfNeeded();
      await page.screenshot({ path: resolve(folder, `exalt-${size}-${colorScheme}-plan-view.png`) });
      await context.close();
    }
  }
});

