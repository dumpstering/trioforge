// The priorities of the trio page in a real browser (Chromium), served by `wrangler pages dev` with the production headers: a select for each of eight stats, drawn by the page script next to the
// role and tier choices, five steps each (Off, Low, Normal, High, Top, which multiply the role's own weight by 0, 0.5, 1, 2 and 4); the kit re-solved in the visitor's browser by the real worker on
// the real solver, with the weights of the steps; the note near the kit and its Reset; the address (`p`, one character for each stat); and the line of the exchange rates.
//
// On the synthetic fixture the answer is checked against Python's reference (fixtures/site/best-kit.json, read by a reader of our own, never by the page's code): "armor class High" is the role's
// armor class weight times two, which is the weights of the reference's first case (the armor class slider at x2) to the digit, so the kit is the reference's, place for place. Real results
// (TRIOFORGE_RESULTS) have other items, so the tests that need the reference are skipped there.
//
// A test without @once in its title runs in the four views (a 1280 px and a 360 px wide window, in light and in dark). With TRIOFORGE_PICTURES set to a folder, the tests that have the answer on
// the page save a screenshot of it there.

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { ROOT, TRIO, axe, expect, madeFrom, open, openAssumptions, openSwitches, pick, queryOf, readKit, test } from "./support.mjs";

test.describe.configure({ timeout: 120_000 });

const FIXTURE_ONLY = Boolean(process.env.TRIOFORGE_RESULTS);
const REAL_RESULTS = "the answers are those of the synthetic results, which these are not";
const REFERENCE = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/best-kit.json"), "utf8"));
const ITEMS = JSON.parse(readFileSync(resolve(ROOT, process.env.TRIOFORGE_RESULTS ?? "fixtures/site/results", "items.json"), "utf8")).items;
const [AC2] = REFERENCE.cases; // an Ogre, tank, own buffs, wiki evidence, dual wield, +4: armor class x2 (the weights of "armor class High")
const IDS = ["hp", "ac", "mana", "atk", "dex", "haste", "resists", "end"];
const LABELS = ["Hit points", "Armor class", "Mana", "Attack (strength)", "Dexterity", "Haste", "Resists", "Endurance"];
const OPTIONS = ["Off (x0)", "Low (x0.5)", "Normal (x1)", "High (x2)", "Top (x4)"];
const NOTICE = "Your priorities: re-solved in your browser; no runner-ups or robustness labels for this kit.";
const ALL_OFF = "Every priority is off: nothing to optimise. Raise one, or Reset.";
const FIGURE = String.raw`(?:[\d.]+|under 0\.1)`;
const HEADING = "Solved for your settings";
const PICTURES = process.env.TRIOFORGE_PICTURES;

const nameOf = (ident) => ITEMS.find((record) => (record.key ?? `w${record.id}`) === ident.split("@")[0]).name;
const namesOf = (kit) => kit.map((ident) => (ident === null ? "Leave empty" : nameOf(ident)));
const answerRows = (page) => readKit(page).then((rows) => rows.map((row) => row.name));

/** The page the way a release makes it (from the wiki level), opened, with the switches where a visitor finds them. */
async function start(page, path = TRIO) {
  await madeFrom(page, "wiki");
  await open(page, path);
  await openSwitches(page, { assumptions: false });
}

/**
 * The page opened as `start` does, with the weapons of the reference (dual wield) chosen: the page of a release is made from the wiki level, but the fixture's page is made from its default view (the
 * strict level, the Tank's dual wield), and the Tank's best weapons on the wiki level are another setup, so a test that holds the kit it shows against the kit of a later view of the same page, or
 * against the reference's, begins here.
 */
async function startOnWiki(page) {
  await start(page);
  const baked = await answerRows(page);
  await openAssumptions(page);
  const weapons = page.locator("#assume-weapons");
  if ((await weapons.getAttribute("open")) === null) await weapons.locator("summary").click();
  await pick(page, "setup-1h-shield"); // (the page is on dual wield, the baked view's weapons: the other choice is the wiki level's own best, a view of its shard)
  await expect.poll(() => answerRows(page), "the wiki shard's kit is drawn").not.toEqual(baked);
  await pick(page, "setup-dw"); // (and the weapons of the reference)
  await expect.poll(() => page.url(), "the view of the weapons is drawn (the address is written after it is)").toContain("setup=dw");
}

/**
 * The bundle of the trio with the tank role giving haste and mana no weight (as a caster gives haste none, and a trio with no mana pool gives mana none), as the site would serve it: the bundle is
 * answered with the changed bytes and the manifest of the trio with their size and SHA-256, so that the page reads it as the real one. Only the page's own requests are changed (it reads the
 * weights of the role from the bundle); the optimizer's worker, which asks for its own copy, is not asked anything in the tests that use this.
 */
async function tankWeighsNoHasteNoMana(page) {
  await page.route("**/engine-trios/pal-mnk-ber.json", async (route) => {
    const response = await route.fetch();
    const manifest = await response.json();
    const entry = manifest.bundles["50"];
    const bundle = await (await page.request.get(new URL(entry.path, route.request().url()).href)).json();
    Object.assign(bundle.roles.tank.weights, { HASTE: 0, MANA: 0, MANAREG: 0 });
    const body = Buffer.from(JSON.stringify(bundle));
    Object.assign(entry, { bytes: body.length, sha256: createHash("sha256").update(body).digest("hex") });
    await page.route(`**${entry.path}`, (inner) => inner.fulfill({ status: 200, contentType: "application/json", body }));
    await route.fulfill({ response, json: manifest });
  });
}

/** The question before the optimizer is downloaded is answered with yes, and the answer is there. */
async function accept(page) {
  const yes = page.locator('.engine-consent [data-action="accept"]');
  await expect(yes).toBeVisible({ timeout: 20_000 });
  await yes.click();
}
const solved = (page) => expect(page.locator("#solve h3")).toHaveText(HEADING, { timeout: 90_000 });
/** The answer, whether or not the visitor is asked first (a page opened again in the same session has said yes already; a window that knows nothing of the session is asked). */
async function solvedOrAsk(page) {
  await expect
    .poll(
      async () => {
        const yes = page.locator('.engine-consent [data-action="accept"]');
        if (await yes.isVisible()) await yes.click();
        return page
          .locator("#solve h3")
          .evaluate((node) => (node.hidden ? "" : node.textContent))
          .catch(() => "");
      },
      { timeout: 90_000 },
    )
    .toBe(HEADING);
}

/** A step chosen with the keyboard alone: the select is focused and the arrow key moves it one option (the first, Off, is five to the left of Top). */
async function stepBy(page, id, key, times = 1) {
  const select = page.locator(`#prio-${id}`);
  await select.focus();
  for (let i = 0; i < times; i += 1) await page.keyboard.press(key);
  return select;
}

async function shot(page, name, testInfo, target) {
  if (!PICTURES) return;
  await page.locator(target).evaluate((node) => node.scrollIntoView({ block: "start" })); // (the part of the page the picture is of is at the top of the window)
  const width = page.viewportSize().width;
  const scheme = testInfo.project.name.endsWith("dark") ? "dark" : "light";
  await page.screenshot({ path: join(PICTURES, `${name}-${width}-${scheme}.png`), fullPage: false });
}

// ---- the control in the page ----------------------------------------------------------------------------------------------------------------

test("the control is next to the role and tier choices, in plain view on a wide window and behind Change on a phone, with a visible label and the five steps for each of the eight stats", async ({ page, watch }, testInfo) => {
  await madeFrom(page, "wiki");
  await open(page, TRIO);
  const phone = (await page.viewportSize()).width < 600;
  if (phone) await expect(page.locator("#prio")).toBeHidden(); // (the choices are folded behind Change, with the role and the tier)
  else await expect(page.locator("#prio")).toBeVisible();
  await openSwitches(page, { assumptions: false });
  await expect(page.locator("#prio")).toBeVisible();
  await expect(page.locator("#prio legend")).toHaveText("Your priorities: how much each stat counts for you");
  for (const [index, id] of IDS.entries()) {
    const select = page.locator(`#prio-${id}`);
    await expect(page.locator(`label[for="prio-${id}"]`)).toHaveText(LABELS[index]);
    expect(await select.locator("option").allTextContents()).toEqual(OPTIONS);
    await expect(select).toHaveValue("n");
    await expect(select).toBeEnabled();
  }
  await expect(page.locator("#prio-reset")).toBeDisabled();
  // it is part of the choices: in the same section as the role and the tier, under them
  const [role, tier, control] = await Promise.all([page.locator("#sw-role").boundingBox(), page.locator("#sw-tier").boundingBox(), page.locator("#prio").boundingBox()]);
  expect(control.y, "under the choices it is next to").toBeGreaterThan(Math.max(role.y + role.height, tier.y + tier.height) - 1);
  expect(await page.locator("#prio").evaluate((node) => node.closest(".controls") === document.querySelector("#sw-role").closest(".controls"))).toBe(true);
  await shot(page, "control-default", testInfo, "#prio");
  expect(watch.problems()).toEqual([]);
  expect(watch.violations()).toEqual([]);
});

test("nothing of the control is asked for before a step is chosen: no chunk, no manifest of the optimizer, no worker, no data, no request of any other site @once", async ({ page, watch }) => {
  const asked = [];
  const workers = [];
  page.on("request", (request) => asked.push(new URL(request.url()).pathname));
  page.on("worker", (worker) => workers.push(worker));
  await madeFrom(page, "wiki");
  await open(page, TRIO);
  await page.waitForTimeout(1500); // (the page script is idle by now; its idle work, the exalt section's, is not the control's)
  expect(asked.filter((path) => /\/assets\/(?:weights|priorities)-/.test(path)), "no chunk of the weights").toEqual([]);
  expect(asked.filter((path) => path === "/engine-manifest.json" || path.startsWith("/engine-trios/") || path.startsWith("/assets/engine/")), "nothing of the optimizer").toEqual([]);
  expect(workers).toHaveLength(0);
  await expect(page.locator("#prio select")).toHaveCount(8);
  expect(watch.problems()).toEqual([]);
});

// ---- a step, the answer, Reset ------------------------------------------------------------------------------------------------------------------

test("a step set with the keyboard re-solves the kit in the browser, says so near the kit with a Reset, carries p in the address, and Reset brings back the precomputed kit @once", async ({ page, watch }, testInfo) => {
  test.skip(FIXTURE_ONLY, REAL_RESULTS);
  await startOnWiki(page);
  const precomputed = await answerRows(page);
  const select = await stepBy(page, "ac", "ArrowDown"); // Normal to High
  await expect(select).toHaveValue("h");
  const question = page.locator("section.answer .engine-slot .engine-consent");
  await expect(question).toBeVisible({ timeout: 20_000 }); // (nothing is downloaded before the visitor says yes)
  expect(await answerRows(page), "the shard's kit stays until there is an answer").toEqual(precomputed);
  await expect(page.locator("#solve")).toContainText(NOTICE); // (said at once, while the kit is worked out)
  await accept(page);
  await solved(page);
  expect(await answerRows(page), "armor class High is the weights of the reference's armor class x2").toEqual(namesOf(AC2.kit));
  expect(await answerRows(page)).not.toEqual(precomputed);
  await expect(page.locator("#solve")).toContainText(NOTICE);
  await expect(page.locator("#solve")).toContainText(AC2.F);
  await expect(page.locator("#solve-prio-reset")).toBeVisible();
  await expect(page.locator("#solve-prio-reset")).toHaveText("Reset");
  await expect(page.locator("#announce")).toHaveText(/^Priorities armor class High\. Solved for your settings\. Showing .+\. Kit value [\d,]+\.$/);
  await expect(page.locator('[data-f="a-lead"]').first()).toHaveText("Assumptions changed");
  expect(queryOf(page)).toEqual({ race: "OGR", role: "tank", tier: "4", setup: "dw", buffs: "own", p: "nhnnnnnn" }); // (the weapons the test chose are in the address)
  await shot(page, "answer-solved", testInfo, "#wear-h");
  // the runner-ups and the robust core are the precomputed kit's: they say that they are not for this one
  await page.locator("#runnerups > summary").click();
  await expect(page.locator("#runnerups-na")).toBeVisible();
  await expect(page.locator("#runnerups-na")).toContainText("Runner-ups are shown for the default assumptions only");
  await page.locator("#robust > summary").click();
  await expect(page.locator("#robust-na")).toContainText("Not computed for this view");
  // Reset: every step Normal, the shard's kit, the address as it was, nothing left of the note
  await page.locator("#solve-prio-reset").click();
  await expect(page.locator("#solve")).toBeHidden();
  expect(await answerRows(page)).toEqual(precomputed);
  expect(queryOf(page)).not.toHaveProperty("p");
  for (const id of IDS) await expect(page.locator(`#prio-${id}`)).toHaveValue("n");
  await expect(page.locator("#wear-h")).toBeFocused();
  await expect(page.locator('[data-f="a-lead"]').first()).toHaveText("Assumptions changed"); // (the weapons the test chose stay chosen: Reset puts the steps back and no more)
  expect(watch.violations()).toEqual([]);
  expect(watch.problems()).toEqual([]);
});

test("the address carries the step: a reload restores it, and a shared link opens the same kit in another window @once", async ({ page, browser, watch }) => {
  test.skip(FIXTURE_ONLY, REAL_RESULTS);
  await start(page);
  await stepBy(page, "ac", "ArrowDown");
  await accept(page);
  await solved(page);
  const url = page.url();
  expect(new URL(url).searchParams.get("p")).toBe("nhnnnnnn");
  const kit = await answerRows(page);
  // a reload: the choice is the address's, the optimizer has been agreed to for the session, and the same kit is worked out
  await page.reload();
  await expect(page.locator("#prio-ac")).toHaveValue("h");
  await solvedOrAsk(page);
  expect(await answerRows(page)).toEqual(kit);
  expect(queryOf(page).p).toBe("nhnnnnnn");
  // a shared link: a window that knows nothing of this one
  const other = await browser.newContext({ viewport: page.viewportSize(), colorScheme: "light" });
  const friend = await other.newPage();
  await madeFrom(friend, "wiki");
  await friend.goto(url);
  await expect(friend.locator("#prio-ac")).toHaveValue("h");
  await solvedOrAsk(friend);
  expect(await answerRows(friend)).toEqual(kit);
  await other.close();
  expect(watch.problems()).toEqual([]);
});

test("a value of p that the page cannot take is ignored whole, and the page says so: every step Normal and the precomputed kit @once", async ({ page, watch }) => {
  await madeFrom(page, "wiki");
  await open(page, `${TRIO}?p=nhnnnnn`);
  await openSwitches(page, { assumptions: false });
  for (const id of IDS) await expect(page.locator(`#prio-${id}`)).toHaveValue("n");
  await expect(page.locator("#status")).toContainText("The priorities in the address do not fit this page, so every step is Normal.");
  expect(queryOf(page)).not.toHaveProperty("p");
  await expect(page.locator("#solve")).toBeHidden();
  expect(watch.problems()).toEqual([]);
});

// ---- the exchange rates ----------------------------------------------------------------------------------------------------------------------------

test("the exchange rates are one line under the control when the button is pressed: what one more point of each stat of the control is worth on the kit shown, said to a screen reader, with the focus where it was", async ({ page, watch }, testInfo) => {
  await start(page);
  const button = page.locator("#prio-rates-show");
  await expect(button).toBeVisible();
  await expect(button).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator("#prio-rates-text")).toBeHidden();
  await button.focus();
  await button.click();
  const line = page.locator("#prio-rates-text");
  const words = new RegExp(
    String.raw`^A point more on this kit is worth about: stamina ${FIGURE}, strength ${FIGURE}, WIS ${FIGURE}, armor class ${FIGURE}, dexterity ${FIGURE}, haste ${FIGURE}, maximum mana ${FIGURE}, endurance ${FIGURE}, one resist ${FIGURE} \(hit points of kit value\)\. Haste counts the best single piece, so its figure is for one more point on that piece\. Mana here comes from WIS \(1 pool\)\.$`,
  );
  await expect(line).toHaveText(words, { timeout: 30_000 });
  await expect(line, "this trio casts with WIS only").not.toContainText("INT");
  await expect(button).toBeVisible();
  await expect(button).toHaveAttribute("aria-expanded", "true");
  await expect(button, "the focus stays on the button: it is not taken to a text that is working").toBeFocused();
  await expect(page.locator("#announce"), "the line is said through the page's live region").toHaveText(words, { timeout: 30_000 });
  const precomputed = await line.textContent();
  // the line follows the kit: another view, other rates (and none while the kit of a choice is worked out)
  await pick(page, "role-melee");
  await expect(line).not.toHaveText(precomputed, { timeout: 30_000 });
  await expect(line).toHaveText(/^A point more on this kit is worth about:/, { timeout: 30_000 });
  await shot(page, "rates", testInfo, "#prio");
  expect(watch.problems()).toEqual([]);
  expect(watch.violations()).toEqual([]);
});

// ---- every step Off, a stat the build does not weigh, a script that does not come ------------------------------------------------------------------------

test("every step Off is nothing to optimise: the page says so, keeps the kit it shows and writes the address with every step Off, and raising one step or Reset is the way on", async ({ page, watch }, testInfo) => {
  await startOnWiki(page);
  const kit = await answerRows(page);
  // seven of the eight set without a change (the visitor sets them one by one; the page is told of the last), the last by the keyboard
  await page.evaluate(() => {
    for (const id of ["hp", "ac", "mana", "atk", "dex", "haste", "resists"]) document.querySelector(`#prio-${id}`).value = "0";
  });
  const select = page.locator("#prio-end");
  await select.focus();
  await page.keyboard.press("Home"); // the first option is Off
  await expect(select).toHaveValue("0");
  await expect(page.locator("#status")).toHaveText(ALL_OFF);
  await expect(page.locator(".engine-consent"), "no optimizer is asked for: there is nothing to work out").toHaveCount(0);
  await page.waitForTimeout(700); // (longer than the pause of a request)
  await expect(page.locator(".engine-consent")).toHaveCount(0);
  expect(await answerRows(page), "the kit it shows is the last valid one").toEqual(kit);
  expect(queryOf(page), "the address says every step Off, as it does for every other view").toMatchObject({ p: "00000000" });
  for (const id of IDS) await expect(page.locator(`#prio-${id}`)).toHaveValue("0");
  await shot(page, "all-off", testInfo, "#prio");
  await shot(page, "all-off-kit", testInfo, "#wear-h");
  // Reset is the way back
  await page.locator("#prio-reset").click();
  for (const id of IDS) await expect(page.locator(`#prio-${id}`)).toHaveValue("n");
  await expect(page.locator("#status")).not.toHaveText(ALL_OFF);
  expect(await answerRows(page)).toEqual(kit);
  expect(watch.problems()).toEqual([]);
});

test("every step Off on the page as a release made it: the lead stays plain, and Reset is back at the plain baked lead (the view a visitor opens first)", async ({ page, watch }) => {
  await start(page); // (the page as it is opened: no weapons chosen, so nothing but the steps differs from the baked view)
  const lead = page.locator('[data-f="a-lead"]').first();
  await expect(lead).toHaveText("Assumptions");
  await page.evaluate(() => {
    for (const id of ["hp", "ac", "mana", "atk", "dex", "haste", "resists"]) document.querySelector(`#prio-${id}`).value = "0";
  });
  const select = page.locator("#prio-end");
  await select.focus();
  await page.keyboard.press("Home");
  await expect(select).toHaveValue("0");
  await expect(page.locator("#status")).toHaveText(ALL_OFF);
  await page.waitForTimeout(700);
  await expect(page.locator(".engine-consent"), "nothing to work out: no optimizer is asked for").toHaveCount(0);
  const own = await answerRows(page); // (the build's own kit for the view the page then shows: the fixture's page is baked from another level than the wiki's shard, so this is the shard's kit)
  expect(queryOf(page)).toMatchObject({ p: "00000000" });
  await expect(lead, "nothing but the steps was changed, and every step Off is the build's own kit: the lead stays plain").toHaveText("Assumptions");
  await page.locator("#prio-reset").click();
  for (const id of IDS) await expect(page.locator(`#prio-${id}`)).toHaveValue("n");
  await expect(page.locator("#status")).not.toHaveText(ALL_OFF);
  expect(await answerRows(page), "Reset puts the steps back and keeps the kit").toEqual(own);
  expect(queryOf(page)).not.toHaveProperty("p");
  await expect(lead, "Reset is back at the plain baked lead: no weapons were chosen").toHaveText("Assumptions");
  expect(watch.problems()).toEqual([]);
});

test("every step Off after an answer of the optimizer: the view's own kit is drawn, the answer is gone, the address says Off, and a reload shows the same kit (F9) @once", async ({ page, watch }) => {
  test.skip(FIXTURE_ONLY, REAL_RESULTS);
  await start(page);
  await stepBy(page, "ac", "ArrowDown"); // Normal to High
  await expect(page.locator("section.answer .engine-slot .engine-consent")).toBeVisible({ timeout: 20_000 });
  const shard = await answerRows(page); // (the view's own kit, the shard's, which stands in until there is an answer)
  await accept(page);
  await solved(page);
  const answer = await answerRows(page);
  expect(answer, "the optimizer's kit is the one shown").not.toEqual(shard);
  const report = page.locator("#report-link");
  const reportedP = async () => (await report.count()) === 0 ? null : new URL(new URL((await report.getAttribute("href")) ?? "", "https://x.test").searchParams.get("page") ?? "https://x.test/").searchParams.get("p");
  if ((await report.count()) > 0) expect(await reportedP(), "the report link names the choice while its answer is drawn").toBe("nhnnnnnn");
  await page.evaluate(() => {
    for (const id of ["hp", "ac", "mana", "atk", "dex", "haste", "resists"]) document.querySelector(`#prio-${id}`).value = "0";
  });
  const select = page.locator("#prio-end");
  await select.focus();
  await page.keyboard.press("Home");
  await expect(select).toHaveValue("0");
  await expect(page.locator("#status")).toHaveText(ALL_OFF);
  await expect.poll(() => answerRows(page), "the build's own kit for the view is drawn again").toEqual(shard);
  await expect(page.locator("#solve h3"), "no answer of the optimizer is labelled on the table").not.toHaveText(HEADING);
  expect(queryOf(page)).toMatchObject({ p: "00000000" });
  if ((await report.count()) > 0) expect(await reportedP(), "the report link follows the kit the table shows: the precomputed one").toBeNull();
  // a reload of the address shows the same kit, the words and the selects
  await page.reload();
  await openSwitches(page, { assumptions: false });
  await expect(page.locator("#status")).toHaveText(ALL_OFF);
  expect(await answerRows(page), "a reload of the address shows the same kit").toEqual(shard);
  for (const id of IDS) await expect(page.locator(`#prio-${id}`)).toHaveValue("0");
  expect(watch.problems()).toEqual([]);
});

test("every step Off on a view that no shard answers (the raid), after two answers of the optimizer: the view's own kit is asked for and drawn, and a reload of the address shows the same kit (G1) @once", async ({ page, watch }) => {
  test.skip(FIXTURE_ONLY, REAL_RESULTS);
  await start(page);
  await openAssumptions(page);
  await page.locator("#assume-buffs > summary").click();
  await pick(page, "buffs-raid");
  await accept(page);
  await solved(page);
  const raid = await answerRows(page); // (the raid view's own kit: the optimizer's, for the role's own weights)
  await stepBy(page, "ac", "ArrowDown"); // Normal to High
  await expect.poll(() => answerRows(page), { timeout: 90_000 }).not.toEqual(raid);
  await page.evaluate(() => {
    for (const id of ["hp", "ac", "mana", "atk", "dex", "haste", "resists"]) document.querySelector(`#prio-${id}`).value = "0";
  });
  const select = page.locator("#prio-end");
  await select.focus();
  await page.keyboard.press("Home");
  await expect(select).toHaveValue("0");
  await expect(page.locator("#status")).toHaveText(ALL_OFF);
  await expect.poll(() => answerRows(page), { timeout: 90_000, message: "the raid view's own kit is worked out again and drawn, not left as the shard's stand-in" }).toEqual(raid);
  await expect(page.locator("#solve h3")).toHaveText(HEADING);
  expect(queryOf(page)).toMatchObject({ buffs: "raid", p: "00000000" });
  // a reload of that address works out the same kit and shows it
  await page.reload();
  await openSwitches(page, { assumptions: false });
  await expect(page.locator("#status")).toHaveText(ALL_OFF);
  await solvedOrAsk(page);
  expect(await answerRows(page), "a reload shows the same kit").toEqual(raid);
  for (const id of IDS) await expect(page.locator(`#prio-${id}`)).toHaveValue("0");
  expect(watch.problems()).toEqual([]);
});

test("every step Off while the view changes: the kit is the build's own for the view asked for, the selects stay Off, the words stay, the address keeps p, and a link of eight zeros opens the same way", async ({ page, watch }) => {
  await start(page);
  const balanced = await answerRows(page);
  await page.evaluate(() => {
    for (const id of ["hp", "ac", "mana", "atk", "dex", "haste", "resists"]) document.querySelector(`#prio-${id}`).value = "0";
  });
  const select = page.locator("#prio-end");
  await select.focus();
  await page.keyboard.press("Home");
  await expect(page.locator("#status")).toHaveText(ALL_OFF);
  await pick(page, "role-tank");
  await expect.poll(() => answerRows(page), { timeout: 15_000 }).not.toEqual(balanced);
  const tank = await answerRows(page);
  await expect(page.locator("#status")).toHaveText(ALL_OFF);
  for (const id of IDS) await expect(page.locator(`#prio-${id}`)).toHaveValue("0");
  expect(queryOf(page)).toMatchObject({ role: "tank", p: "00000000" });
  await expect(page.locator(".engine-consent"), "the build's own kit is the precomputed one: no optimizer is asked for").toHaveCount(0);
  // the way out is Reset: the same kit, every step Normal, no p
  await page.locator("#prio-reset").click();
  await expect(page.locator("#status")).not.toHaveText(ALL_OFF);
  expect(await answerRows(page)).toEqual(tank);
  await expect(page.locator("#prio-hp"), "the focus is on a select that can take it").toBeFocused();
  expect(queryOf(page)).not.toHaveProperty("p");
  // a link of eight zeros for that role: the kit of the role, the selects Off, the words
  await open(page, `${TRIO}?role=tank&p=00000000`);
  await openSwitches(page, { assumptions: false });
  await expect(page.locator("#status")).toHaveText(ALL_OFF);
  expect(await answerRows(page)).toEqual(tank);
  for (const id of IDS) await expect(page.locator(`#prio-${id}`)).toHaveValue("0");
  await expect(page.locator("#role-tank")).toBeChecked();
  expect(queryOf(page)).toMatchObject({ role: "tank", p: "00000000" });
  expect(watch.problems()).toEqual([]);
});

test("a stat that the build does not weigh is disabled with a visible note, and is given back for a role that weighs it", async ({ page, watch }, testInfo) => {
  await tankWeighsNoHasteNoMana(page);
  await start(page);
  await pick(page, "role-tank");
  await expect(page.locator("#prio-haste")).toBeEnabled(); // (the build is read when the control is touched: nothing is fetched for a page that is not)
  await page.locator("#prio-ac").focus();
  for (const id of ["haste", "mana"]) {
    await expect(page.locator(`#prio-${id}`)).toBeDisabled();
    await expect(page.locator(`#prio-${id}-note`)).toBeVisible();
    await expect(page.locator(`#prio-${id}-note`)).toHaveText("not counted in this build");
    await expect(page.locator(`#prio-${id}`)).toHaveAttribute("aria-describedby", `prio-${id}-note`);
  }
  await expect(page.locator("#prio-ac")).toBeEnabled();
  await expect(page.locator("#prio-haste"), "disabled looks disabled").toHaveCSS("opacity", "0.55");
  await shot(page, "disabled-select", testInfo, "#prio");
  await pick(page, "role-melee");
  await expect(page.locator("#prio-haste")).toBeEnabled();
  await expect(page.locator("#prio-haste-note")).toBeHidden();
  await pick(page, "role-tank");
  await expect(page.locator("#prio-haste")).toBeDisabled();
  expect(watch.problems()).toEqual([]);
});

test("a disabled Reset priorities looks disabled, in this theme too: faded, with a dashed edge", async ({ page }) => {
  await start(page);
  await expect(page.locator("#prio-reset")).toBeDisabled();
  await expect(page.locator("#prio-reset")).toHaveCSS("opacity", "0.55");
  await expect(page.locator("#prio-reset")).toHaveCSS("border-top-style", "dashed");
  await expect(page.locator("#prio-rates-show"), "a button that can be pressed is not faded").toHaveCSS("opacity", "1");
});

test("the room kept for the control is given up when the page script does not draw it @once", async ({ page }) => {
  await page.route("**/assets/app-*.js", (route) => route.abort());
  await page.goto(TRIO, { waitUntil: "domcontentloaded" });
  const gap = () => page.evaluate(() => getComputedStyle(document.querySelector(".controls"), "::after").display);
  await expect.poll(gap, { timeout: 4000 }).toBe("block"); // (kept while the script may still come)
  await expect(page.locator("html")).toHaveAttribute("data-prio-off", "", { timeout: 15_000 });
  expect(await gap(), "no blank gap is left where the control would have been").toBe("none");
  await expect(page.locator("#prio")).toHaveCount(0);
});

// ---- it fits the page -----------------------------------------------------------------------------------------------------------------------------

test("every control of it is at least 24 px by 24 px, and the page has no horizontal scroll, with the answer, the note and the rates on it", async ({ page, watch }, testInfo) => {
  test.skip(FIXTURE_ONLY, REAL_RESULTS);
  await start(page);
  const small = async () =>
    page.evaluate(() => [...document.querySelectorAll("#prio select, #prio button, #solve-prio-reset")].filter((node) => !node.hidden && node.offsetParent !== null).map((node) => ({ id: node.id, ...(({ width, height }) => ({ width, height }))(node.getBoundingClientRect()) })).filter((box) => box.width < 24 || box.height < 24));
  const noScroll = () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
  expect(await small(), "the controls at rest").toEqual([]);
  expect(await noScroll(), "no horizontal scroll at rest").toBe(true);
  await page.locator("#prio-rates-show").click();
  await expect(page.locator("#prio-rates-text")).toContainText("A point more", { timeout: 30_000 });
  await stepBy(page, "ac", "ArrowDown");
  await stepBy(page, "resists", "ArrowUp", 2); // Normal to Low to Off
  await accept(page);
  await solved(page);
  await expect(page.locator("#prio-rates-text")).toContainText("A point more", { timeout: 30_000 });
  expect(await small(), "the controls with the answer").toEqual([]);
  expect(await noScroll(), "no horizontal scroll with the answer, the note and the rates").toBe(true);
  await shot(page, "with-answer-control", testInfo, "#prio");
  await shot(page, "with-answer-kit", testInfo, "#wear-h");
  expect(watch.problems()).toEqual([]);
});

// ---- accessibility, in both themes (the four views) ------------------------------------------------------------------------------------------------

test("axe: the trio page with the priorities control open, at rest", async ({ page }, testInfo) => {
  await start(page);
  await expect(page.locator("#prio")).toBeVisible();
  await axe(page, testInfo);
});

test("axe: the trio page with a step chosen, the note near the kit and the line of the rates", async ({ page }, testInfo) => {
  test.skip(FIXTURE_ONLY, REAL_RESULTS);
  await start(page);
  await page.locator("#prio-rates-show").click();
  await expect(page.locator("#prio-rates-text")).toContainText("A point more", { timeout: 30_000 });
  await stepBy(page, "ac", "ArrowDown");
  await accept(page);
  await solved(page);
  await expect(page.locator("#solve")).toContainText(NOTICE);
  await expect(page.locator("#prio-rates-text")).toContainText("A point more", { timeout: 30_000 });
  await axe(page, testInfo);
});
