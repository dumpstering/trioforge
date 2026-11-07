// The sliders and the buff choices of the trio page in a real browser (Chromium), served by `wrangler pages dev` with the production headers: the chunk that draws the sliders, the
// question before the optimizer is downloaded, the real worker on the real solver, and the answer in place of the shard's kit.
//
// On the synthetic fixture the answers are checked against Python's reference (fixtures/site/best-kit.json: the exact value, the kit place for place), read by a reader of our own, never by the
// page's code. Real results (TRIOFORGE_RESULTS) have other items, so the tests that need the reference are skipped there; the ones that need no name run on both.
//
// A test without @once in its title runs in the four views (a 1280 px and a 360 px wide window, in light and in dark).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ROOT, TRIO, axe, expect, madeFrom, open, openSwitches, pick, queryOf, readKit, test } from "./support.mjs";

test.describe.configure({ timeout: 120_000 });

const REAL_RESULTS = "the answers are those of the synthetic results, which these are not";
const FIXTURE_ONLY = Boolean(process.env.TRIOFORGE_RESULTS);
const REFERENCE = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/best-kit.json"), "utf8"));
/** The item table of the results the page is built from (the fixture's, or real results'): the names of the items by their keys, read the plain way. */
const ITEMS = JSON.parse(readFileSync(resolve(ROOT, process.env.TRIOFORGE_RESULTS ?? "fixtures/site/results", "items.json"), "utf8")).items;
const GROUPS = ["AC", "MANA", "ATK+HASTE", "SV", "regen"];
const HEADING = "Solved for your settings";
const ONE = "11111";

const nameOf = (ident) => ITEMS.find((record) => (record.key ?? `w${record.id}`) === ident.split("@")[0]).name;
const namesOf = (kit) => kit.map((ident) => (ident === null ? "Leave empty" : nameOf(ident)));
const grouped = (number) => String(Math.round(number)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const caseNamed = (start) => REFERENCE.cases.find((c) => c.name.startsWith(start));

/** Watch the page for the workers it starts and the WebAssembly and the data it fetches. */
function observe(page) {
  const seen = { workers: [], wasm: [], items: [], bundles: [], manifests: [], chunks: [] };
  page.on("worker", (worker) => seen.workers.push(worker));
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.endsWith(".wasm")) seen.wasm.push(path);
    if (path.startsWith("/assets/engine/data/items-")) seen.items.push(path);
    if (/^\/assets\/engine\/data\/[a-z]{3}-[a-z]{3}-[a-z]{3}-l\d+-/.test(path)) seen.bundles.push(path);
    if (path === "/engine-manifest.json") seen.manifests.push(path);
    if (/^\/assets\/weights-[A-Z0-9]{8}\.js$/.test(path)) seen.chunks.push(path);
  });
  return seen;
}

const answerRows = (page) => readKit(page).then((rows) => rows.map((row) => row.name));
const positions = (page) => page.evaluate((count) => Array.from({ length: count }, (_, index) => document.querySelector(`input[name="w-${index}"]:checked`)?.value ?? "?").join(""), GROUPS.length);

/** A choice in one of the assumptions, the way a visitor makes it: the assumption is opened (its choices are behind its line), then the choice is clicked. */
async function choose(page, assumption, id) {
  const details = page.locator(`#assume-${assumption}`);
  if ((await details.getAttribute("open")) === null) await details.locator("summary").click();
  await pick(page, id);
}

/** The Weights assumption open, the way a visitor does it (on a phone the switches are behind the Change button). */
async function openWeights(page) {
  await openSwitches(page);
  await page.locator("#assume-weights > summary").click();
  await expect(page.locator("#assume-weights input[type=radio]")).toHaveCount(GROUPS.length * 3);
}

/** The question before the optimizer is downloaded is answered with yes. */
async function accept(page) {
  const accept = page.locator('.engine-consent [data-action="accept"]');
  await expect(accept).toBeVisible({ timeout: 20_000 });
  await accept.click();
}

async function solved(page) {
  await expect(page.locator("#solve h3")).toHaveText(HEADING, { timeout: 90_000 });
}

/** The request for a view, written here (not read from the page): what the optimizer's client is asked directly, to compare with what the page draws. */
function requestFor({ race, role, tier, setup, evidence, buffs }, multipliers) {
  return { v: 1, kind: "scenario", trio: REFERENCE.trio, level: REFERENCE.level, mode: "best-kit", scenario: { race, role, buffs, evidence, setup }, tier, weights: { multipliers }, budgetMs: 60_000 };
}

/** Ask the page's one client (the module the manifest names) for an answer, as the chunk of the sliders does, and resolve to the result. */
async function askDirectly(page, request, body) {
  const manifest = await (await request.get("/engine-manifest.json")).json();
  return page.evaluate(
    async ({ path, message }) => {
      const { getEngineClient } = await import(new URL(path, location.href).href);
      return getEngineClient().runScenario(message);
    },
    { path: manifest.client.path, message: body },
  );
}

/** The view the page shows, read from its switches. */
const viewOf = (page) =>
  page.evaluate(() => {
    const checked = (name) => document.querySelector(`input[name="${name}"]:checked`).value;
    return { race: document.querySelector("#sw-race").value, role: checked("role"), tier: Number(document.querySelector("#sw-tier").value), setup: checked("setup"), evidence: document.querySelector("#main").dataset.ev, buffs: checked("buffs") };
  });

/**
 * The switches the shards answer, set to a view of the reference (nothing is asked of the optimizer for any of them). The page has no switch for the evidence level: it is made from one,
 * and the page is opened again made from the level of the view (a release is made from the wiki level).
 */
async function showView(page, { race, role, tier, setup, evidence }) {
  await madeFrom(page, evidence);
  await open(page, TRIO);
  await openSwitches(page);
  await page.locator("#sw-race").selectOption(race);
  await pick(page, `role-${role}`);
  await page.locator("#sw-tier").selectOption(String(tier));
  await choose(page, "weapons", `setup-${setup}`);
  await expect(page.locator('[data-f="v-tier"]')).toHaveText(`+${tier}`);
  await expect(page.locator('[data-f="v-setup"]')).not.toHaveText("");
}

// ---- the first load and the chunk ----------------------------------------------------------------------------------------------------------

test("the chunk of the sliders and the optimizer are asked for when a control is used, and not before @once", async ({ page, watch }) => {
  const seen = observe(page);
  await open(page, TRIO);
  await expect(page.locator("#assume-weights input")).toHaveCount(0);
  await expect(page.locator("#buffs-raid")).toBeEnabled();
  await openSwitches(page);
  // the choices the shards answer are the page's own
  await choose(page, "buffs", "buffs-group");
  await expect(page.locator('[data-f="assume-buffs"]')).toHaveText("common group buffs");
  expect(seen.chunks, "no chunk before a control for the sliders is used").toEqual([]);
  await page.locator("#assume-weights > summary").click();
  await expect(page.locator("#assume-weights input[type=radio]")).toHaveCount(GROUPS.length * 3);
  expect(seen.chunks).toHaveLength(1);
  expect(seen.manifests, "drawing the sliders asks for nothing of the optimizer").toEqual([]);
  expect(seen.workers).toHaveLength(0);
  await expect(page.locator('[data-f="assume-weights"]')).toHaveText("role's own");
  expect(watch.problems()).toEqual([]);
  expect(watch.violations()).toEqual([]);
});

// ---- a slider, the question, the answer ------------------------------------------------------------------------------------------------------------

test("a slider at x2 asks the visitor first, then gives Python's answer for the view, in place of the shard's kit; the optimizer is downloaded once @once", async ({ page, watch }) => {
  test.skip(FIXTURE_ONLY, REAL_RESULTS);
  const seen = observe(page);
  const c = REFERENCE.cases[0]; // an Ogre, balanced, own buffs, wiki evidence, dual wield, +4: armor class x2
  await open(page, TRIO);
  await showView(page, { race: "OGR", role: "balanced", tier: 4, setup: "dw", evidence: "wiki" });
  const shard = await answerRows(page);
  await openWeights(page);
  await pick(page, "w-0-2");
  // nothing is downloaded before the visitor says yes
  const question = page.locator("section.answer .engine-slot .engine-consent"); // (in the answer area, where the visitor is looking)
  await expect(question).toBeVisible({ timeout: 20_000 });
  await expect(question.locator("h3")).toHaveText("Load the optimizer?");
  expect(seen.workers).toHaveLength(0);
  expect(seen.wasm).toHaveLength(0);
  expect(await answerRows(page), "the shard's kit stays until there is an answer").toEqual(shard);
  await accept(page);
  await solved(page);
  expect(await answerRows(page)).toEqual(namesOf(c.kit));
  await expect(page.locator("#solve")).toContainText(c.F);
  await expect(page.locator("#solve")).toContainText(`Kit value ${grouped(c.value)}`);
  await expect(page.locator("#solve button")).toHaveText("Back to the precomputed answer");
  await expect(page.locator("#announce")).toHaveText(new RegExp(String.raw`^Weights armor class x2\. Solved for your settings\. Showing .+\. Kit value ${grouped(c.value)}\.$`)); // (the value is the reference's, as in the line above)
  expect(queryOf(page)).toMatchObject({ buffs: "own", w: "21111" });
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  // a second answer comes from the same worker, with nothing downloaded again
  const second = REFERENCE.cases[1]; // armor class x0.5
  await pick(page, "w-0-h");
  await expect(page.locator("#solve")).toContainText(second.F);
  expect(await answerRows(page)).toEqual(namesOf(second.kit));
  expect(seen.workers).toHaveLength(1);
  expect(seen.wasm).toHaveLength(1);
  expect(seen.bundles).toHaveLength(1);
  expect(new Set(seen.items).size).toBe(1);
  expect(watch.violations()).toEqual([]);
  expect(watch.problems()).toEqual([]);
});

test("moving a slider and back restores the shard's kit, with no question and nothing downloaded; and so does the button after an answer @once", async ({ page, watch }) => {
  test.skip(FIXTURE_ONLY, REAL_RESULTS);
  const seen = observe(page);
  await open(page, TRIO);
  await showView(page, { race: "OGR", role: "balanced", tier: 4, setup: "dw", evidence: "wiki" });
  const shard = await answerRows(page);
  await openWeights(page);
  await pick(page, "w-0-2");
  await pick(page, "w-0-1");
  await page.waitForTimeout(700); // longer than the pause: a request would have been sent
  expect(await answerRows(page)).toEqual(shard);
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(seen.manifests).toEqual([]);
  expect(seen.workers).toHaveLength(0);
  expect(queryOf(page)).not.toHaveProperty("w");
  // after an answer
  await pick(page, "w-3-h");
  await accept(page);
  await solved(page);
  expect(await answerRows(page)).not.toEqual(shard);
  // the totals and the weapon setups are the shard's kit's: out of sight while the answer is shown, and back with the shard's kit
  await expect(page.locator("#why")).toBeHidden();
  await expect(page.locator("#weapons")).toBeHidden();
  await expect(page.locator("#kit")).toHaveCSS("opacity", "1");
  await pick(page, "w-3-1");
  await expect(page.locator("#solve")).toBeHidden();
  await expect(page.locator("#why")).toBeVisible();
  await expect(page.locator("#weapons")).toBeVisible();
  expect(await answerRows(page)).toEqual(shard);
  expect(await positions(page)).toBe(ONE);
  expect(seen.workers).toHaveLength(1);
  expect(watch.problems()).toEqual([]);
});

test("declining the question keeps the precomputed answer and offers the optimizer; a yes then gives the answer @once", async ({ page, watch }) => {
  test.skip(FIXTURE_ONLY, REAL_RESULTS);
  const seen = observe(page);
  const c = REFERENCE.cases[0];
  await open(page, TRIO);
  await showView(page, { race: "OGR", role: "balanced", tier: 4, setup: "dw", evidence: "wiki" });
  const shard = await answerRows(page);
  await openWeights(page);
  await pick(page, "w-0-2");
  await page.getByRole("button", { name: "Not now" }).click({ timeout: 20_000 });
  await expect(page.locator("#solve")).toContainText("The optimizer was not loaded");
  expect(await answerRows(page)).toEqual(shard);
  expect(seen.workers).toHaveLength(0);
  expect(seen.wasm).toHaveLength(0);
  await page.getByRole("button", { name: "Load the optimizer" }).click();
  await accept(page);
  await solved(page);
  expect(await answerRows(page)).toEqual(namesOf(c.kit));
  expect(seen.workers).toHaveLength(1);
  expect(watch.problems()).toEqual([]);
});

test("Stop ends the work and Try again asks again @once", async ({ page, watch }) => {
  test.skip(FIXTURE_ONLY, REAL_RESULTS);
  const c = REFERENCE.cases[0];
  await open(page, TRIO);
  await showView(page, { race: "OGR", role: "balanced", tier: 4, setup: "dw", evidence: "wiki" });
  const shard = await answerRows(page);
  await openWeights(page);
  await pick(page, "w-0-2");
  await accept(page);
  await expect(page.locator("#solve")).toContainText("Working out the kit for these settings", { timeout: 30_000 });
  await expect(page.locator("#kit")).toHaveCSS("opacity", "0.6"); // (the kit shown is not for these settings: dimmed while the work goes on)
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.locator("#solve")).toContainText("Stopped.");
  await expect(page.locator("#kit")).toHaveCSS("opacity", "1");
  expect(await answerRows(page)).toEqual(shard);
  await page.getByRole("button", { name: "Try again" }).click();
  await solved(page);
  expect(await answerRows(page)).toEqual(namesOf(c.kit));
  expect(watch.problems()).toEqual([]);
});

// ---- the four buff sets ---------------------------------------------------------------------------------------------------------------------

// The reference has the full raid and the Enchanter's group for an Iksar only, a race the fixture's page does not offer (it has an Ogre, a Troll and a Wood Elf): for those two the answer of the page is
// held to the answer of the optimizer's own client to the request written above, which the engine's end-to-end test holds to Python's for the Iksar. The own buffs and the common group buffs are Python's.
const TROLL = { race: "TRL", role: "tank", tier: 4, setup: "1h-shield", evidence: "wiki" };
const BUFF_SETS = [
  { buffs: "own", reference: REFERENCE.cases[0] },
  { buffs: "group", reference: caseNamed("a Troll, tank, group buffs, strict evidence, one-hander and shield, +4: armor class x0.5") },
  { buffs: "raid", direct: { view: TROLL, multipliers: { AC: 2 } } },
  { buffs: "group+enchanter", direct: { view: TROLL, multipliers: { regen: 2 } } },
];

for (const { buffs, reference, direct } of BUFF_SETS) {
  test(`the ${buffs} buffs with a slider give the answer for the view @once`, async ({ page, request, watch }) => {
    test.skip(FIXTURE_ONLY, REAL_RESULTS);
    const view = reference
      ? { race: reference.scenario.race, role: reference.scenario.role, tier: reference.tier, setup: reference.scenario.setup, evidence: reference.scenario.evidence }
      : direct.view;
    const multipliers = reference ? reference.weights.multipliers : direct.multipliers;
    if (reference) expect(reference.scenario.buffs).toBe(buffs);
    await open(page, TRIO);
    await showView(page, view);
    await openWeights(page);
    await choose(page, "buffs", buffs === "raid" ? "buffs-raid" : buffs === "own" ? "buffs-own" : "buffs-group");
    if (buffs === "group+enchanter") await pick(page, "buffs-ench");
    const [group, number] = Object.entries(multipliers)[0];
    await pick(page, `w-${GROUPS.indexOf(group)}-${number === 2 ? "2" : "h"}`);
    await accept(page);
    await solved(page);
    expect(queryOf(page).buffs).toBe(buffs === "group+enchanter" ? "enchanter" : buffs); // (the address says the Enchanter's group as enchanter: no plus sign to be read as a space)
    let answer = reference;
    if (!reference) {
      answer = await askDirectly(page, request, requestFor({ ...view, buffs }, multipliers));
      expect(answer.proven, JSON.stringify(answer)).toBe(true);
    }
    await expect(page.locator("#solve")).toContainText(answer.F);
    expect(await answerRows(page)).toEqual(namesOf(answer.kit));
    expect(watch.violations()).toEqual([]);
    expect(watch.problems()).toEqual([]);
  });
}

// ---- the address -----------------------------------------------------------------------------------------------------------------------------------

test("a page opened with the address of an answer solves it after the question, and shows the precomputed answer and offers the solve if the visitor declines @once", async ({ page, watch }) => {
  test.skip(FIXTURE_ONLY, REAL_RESULTS);
  const c = REFERENCE.cases[0];
  const asked = "?race=OGR&role=balanced&tier=4&ev=wiki&buffs=own&w=21111"; // (the ev is ignored: the page is made from the wiki level here)
  await madeFrom(page, "wiki");
  await open(page, `${TRIO}${asked}`);
  await accept(page);
  await solved(page);
  expect(await answerRows(page)).toEqual(namesOf(c.kit));
  expect(await positions(page)).toBe("21111");
  expect(new URL(page.url()).search).toBe("?race=OGR&role=balanced&tier=4&buffs=own&w=21111"); // (written without the ev)
  // the same address with the visitor saying no (a new session: the yes is kept for the session)
  const other = await page.context().newPage();
  await other.goto(`${TRIO}${asked}`);
  await other.getByRole("button", { name: "Not now" }).click({ timeout: 20_000 });
  await expect(other.locator("#solve")).toContainText("The optimizer was not loaded");
  await expect(other.getByRole("button", { name: "Load the optimizer" })).toBeVisible();
  expect((await other.locator("#kit-body tr").count())).toBe(22);
  expect(watch.problems()).toEqual([]);
});

test("a w that does not fit the sliders is ignored, said once, and not kept in the address @once", async ({ page, watch }) => {
  await open(page, `${TRIO}?w=2111`);
  await expect(page.locator("#status")).toContainText("The weights in the address do not fit the sliders of this page");
  expect(new URL(page.url()).searchParams.has("w")).toBe(false);
  await expect(page.locator('[data-f="assume-weights"]')).toHaveText("role's own");
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  await openSwitches(page);
  await page.locator("#sw-tier").selectOption({ index: 0 });
  await expect(page.locator("#status")).toHaveText("");
  expect(watch.problems()).toEqual([]);
});

test("the Enchanter's group is enchanter in the address, and a page opened with the older spelling, escaped or typed with a raw plus sign, shows it all the same @once", async ({ page, watch }) => {
  for (const spelled of ["enchanter", "group%2Benchanter", "group+enchanter"]) {
    await open(page, `${TRIO}?buffs=${spelled}`);
    await expect(page.locator("#buffs-ench")).toBeChecked();
    await expect(page.locator('input[name="buffs"]:checked')).toHaveValue("group");
    await expect(page.locator("#status")).toHaveText("");
    expect(new URL(page.url()).searchParams.get("buffs"), spelled).toBe("enchanter");
    expect(new URL(page.url()).search).not.toMatch(/\+|%2B/i);
  }
  expect(watch.problems()).toEqual([]);
});

// ---- the keyboard and the focus -----------------------------------------------------------------------------------------------------------------------

test("an arrow key moves a slider, the pause passes, and the focus is on the slider through the answer", async ({ page, watch }) => {
  await open(page, TRIO);
  await openWeights(page);
  const radio = page.locator("#w-0-1");
  await radio.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#w-0-2")).toBeChecked();
  await expect(page.locator("#w-0-2")).toBeFocused();
  await expect(page.locator('[data-f="assume-weights"]')).toHaveText("armor class x2");
  expect(queryOf(page).w).toBe("21111");
  await accept(page);
  await solved(page);
  await expect(page.locator("#w-0-2")).toBeFocused();
  await expect(page.locator("#upgrade-weights"), "the Upgrade section takes the weights now: no line says that it does not").toHaveCount(0);
  expect(watch.problems()).toEqual([]);
});

// ---- on real results as on the fixture: no name needed ----------------------------------------------------------------------------------------------

test("a slider at x2 gives an answer of 22 places with an exact value, the names of the item table for what the optimizer answers, and the button goes back to the precomputed answer @once", async ({ page, request, watch }) => {
  await open(page, TRIO);
  const shard = await answerRows(page);
  await openWeights(page);
  await pick(page, "w-0-2");
  await accept(page);
  await solved(page);
  const rows = await answerRows(page);
  expect(rows).toHaveLength(22);
  await expect(page.locator("#solve")).toContainText(/Exact value \(F\): \d+\/\d+\./);
  // what the page drew is what the optimizer's client answers to the request for the view the page shows, with the names of the item table (read here from the results, not from the page's code)
  const answer = await askDirectly(page, request, requestFor(await viewOf(page), { AC: 2 }));
  expect(answer.proven, JSON.stringify(answer)).toBe(true);
  expect(rows).toEqual(namesOf(answer.kit));
  await expect(page.locator("#solve")).toContainText(answer.F);
  await page.getByRole("button", { name: "Back to the precomputed answer" }).click();
  await expect(page.locator("#solve")).toBeHidden();
  expect(await answerRows(page)).toEqual(shard);
  expect(await positions(page)).toBe(ONE);
  await expect(page.locator("#wear-h")).toBeFocused();
  expect(watch.problems()).toEqual([]);
});

// ---- the Enchanter box ----------------------------------------------------------------------------------------------------------------------------------------

test("the ticked Enchanter box shows a check mark, and the mark is the one of the chosen segments @once", async ({ page }) => {
  await open(page, TRIO);
  await choose(page, "buffs", "buffs-group");
  await pick(page, "buffs-ench");
  const mark = (selector) => page.locator(selector).evaluate((label) => getComputedStyle(label, "::before").content);
  const ticked = await mark('label[for="buffs-ench"]');
  expect(ticked, "what the stylesheet draws in the ticked box").toMatch(/^"✓"( \/ "")?$/);
  expect(ticked).not.toMatch(/[¹³]|\d/);
});

// ---- accessibility, in the four views -----------------------------------------------------------------------------------------------------------------

test("axe finds nothing serious on the page with the Buffs and Weights assumptions open, and in the answer", async ({ page }, testInfo) => {
  await open(page, TRIO);
  await openSwitches(page);
  await page.locator("#assume-buffs > summary").click();
  await pick(page, "buffs-group");
  await expect(page.locator("#buffs-ench")).toBeEnabled();
  await page.locator("#assume-weights > summary").click();
  await expect(page.locator("#assume-weights input[type=radio]")).toHaveCount(GROUPS.length * 3);
  await axe(page, testInfo);
  // in the answer
  await pick(page, "w-3-2");
  await accept(page);
  await solved(page);
  await expect(page.locator("#solve")).toBeVisible();
  await axe(page, testInfo);
});

test("axe finds nothing serious on the page when the visitor has declined the question", async ({ page }, testInfo) => {
  await open(page, TRIO);
  await openWeights(page);
  await pick(page, "w-1-h");
  await page.getByRole("button", { name: "Not now" }).click({ timeout: 20_000 });
  await expect(page.locator("#solve")).toContainText("The optimizer was not loaded");
  await axe(page, testInfo);
});
