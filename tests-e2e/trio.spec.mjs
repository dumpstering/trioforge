// The built site in a real browser (Chromium), served by `wrangler pages dev` with the production headers.
//
// A test without @once in its title runs in four views: a 1280 px and a 360 px wide window, each with the system in light and in dark
// mode (see playwright.config.mjs). A test with @once does not depend on the view and runs once.
//
// The page is checked against the data files it is built from, which a small reader of our own (support.mjs) understands, never
// against the page's own code. The tests take every switch and every value from the page, so they run unchanged on the synthetic fixture
// (three races, three tiers) and on real results (fifteen races, eleven tiers).

import {
  DATA,
  PAGES,
  RESULTS_PARTIAL,
  TRIO,
  accessibleNames,
  axe,
  expect,
  expectView,
  focusRingWidth,
  loadShard,
  offeredSetups,
  open,
  openAssumptions,
  openSwitches,
  optionValues,
  pick,
  queryOf,
  readControls,
  readHeaderBlocks,
  readHeadersFile,
  readKit,
  readShard,
  tabTo,
  test,
} from "./support.mjs";

const PAGE_LIST = Object.entries(PAGES);
const STATUS_FAILED = /couldn.t load this view; try again/i;

/** The switches and the table as the page arrives. */
async function arrival(page) {
  return { controls: await readControls(page), kit: await readKit(page) };
}

/** A tier other than the one shown, to switch to. */
async function otherTier(page, shown) {
  const tiers = await optionValues(page, "#sw-tier");
  return tiers.find((tier) => tier !== String(shown)) ?? tiers[0];
}

// ---- 1. a page loads and is used with nothing wrong in the console and no policy violation -------------------------------------

async function useHome(page) {
  await expect(page.locator("#picker")).toBeVisible();
  for (const code of ["PAL", "MNK", "BER"]) await pick(page, `class-${code}`);
  await expect(page.locator("#picker-status a")).toHaveAttribute("href", TRIO);
  await pick(page, "class-BER", false); // take one away: the choice is open again
  await expect(page.locator("#picker-status")).toContainText("Pick 1 more class");
}

async function useTrio(page) {
  await openSwitches(page); // on a phone the switches are behind the Change button
  // with both expanders open, the next change of view fetches their files too
  await page.locator("#runnerups > summary").click();
  await page.locator("#robust > summary").click();
  const tiers = await optionValues(page, "#sw-tier");
  const files = Promise.all([
    page.waitForResponse((r) => /\/runnerups\/[a-z]+\.json$/.test(r.url()) && r.ok(), { timeout: 10_000 }),
    page.waitForResponse((r) => r.url().endsWith("/robust.json") && r.ok(), { timeout: 10_000 }),
  ]);
  await page.locator("#sw-tier").selectOption(tiers.at(-1));
  await files;
  await expect(page.locator('[data-f="v-tier"]')).toHaveText(`+${tiers.at(-1)}`);
  // then every other switch once, each of which loads or draws something
  const races = await optionValues(page, "#sw-race");
  await page.locator("#sw-race").selectOption(races.at(-1));
  await page.locator("#assume-buffs > summary").click();
  await pick(page, "buffs-group");
  await expect(page.locator('[data-f="assume-buffs"]')).toHaveText("common group buffs");
  await pick(page, "role-melee");
  await expect(page.locator('[data-f="v-role"]')).toHaveText("Melee damage");
  await expect(page.locator("#status")).toHaveText("");
}

for (const [name, path] of PAGE_LIST) {
  test(`${name} page: no console errors, no CSP or Trusted Types violations, in use`, async ({ page, watch }) => {
    await open(page, path);
    if (name === "home") await useHome(page);
    if (name === "trio") await useTrio(page);
    // until the visitor asks for something to be remembered, nothing is: no cookie, nothing in either storage
    expect(await page.context().cookies(), "no cookies").toEqual([]);
    expect(await page.evaluate(() => localStorage.length + sessionStorage.length), "nothing is stored").toBe(0);
    // the theme button works on every page
    const button = page.locator("#theme-toggle");
    await button.click();
    await expect(button).toHaveText("Theme: light");
    await button.click();
    await expect(button).toHaveText("Theme: dark");
    await button.click();
    await expect(button).toHaveText("Theme: auto");
    expect(watch.problems()).toEqual([]);
  });
}

// ---- 2. the switches work with the keyboard -----------------------------------------------------------------------------------

test.describe("keyboard", () => {
  test("the skip link is the first stop and works; the switches follow in reading order, each with a focus ring", async ({ page, watch }) => {
    await open(page, TRIO);
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.activeElement?.className)).toBe("skip-link");
    const box = await page.locator(".skip-link").boundingBox();
    expect(box && box.y >= 0 && box.y + box.height <= 100, "the focused skip link is on screen").toBe(true);
    await page.keyboard.press("Enter");
    await expect.poll(() => page.evaluate(() => document.activeElement?.id)).toBe("main");
    expect(new URL(page.url()).hash, "the page moves to the content itself: following the anchor would make a history entry with no state, and a reload of it would lose a shared kit").toBe("");

    await page.reload();
    await expect(page.locator("#theme-toggle")).toBeVisible();
    await openSwitches(page, { keyboard: true, assumptions: false }); // on a phone the Change button comes first, then the switches it opens
    // the three choices, then the one folded line of the assumptions (Enter opens it), then the three assumptions it holds
    // (the eight selects of the priorities, which are drawn after the choices, come between the tier and the folded line: the first is a few presses from the tier, and the folded line is the eight after it)
    const stops = ["#sw-race", 'input[name="role"]:checked', "#sw-tier", "#prio-hp", "#assumes > summary", "#assume-buffs > summary", "#assume-weapons > summary"];
    let limit = 20; // the skip link, the logo, the five links and the theme button come first
    for (const stop of stops) {
      await tabTo(page, stop, limit);
      limit = stop === "#prio-hp" ? 10 : 6; // after that each switch is only a few presses from the one before (the folded line, the eight selects of the priorities)
      expect(await focusRingWidth(page), `${stop} shows a focus ring`).toBeGreaterThanOrEqual(2);
      if (stop === "#assumes > summary") await page.keyboard.press("Enter");
    }
    expect(watch.problems()).toEqual([]);
  });

  test("race: Tab to it, an arrow changes it, the table follows", async ({ page, request, watch }) => {
    await open(page, TRIO);
    const shard = await loadShard(request);
    const start = await arrival(page);
    await openSwitches(page, { keyboard: true, assumptions: false });
    await tabTo(page, "#sw-race");
    const races = await optionValues(page, "#sw-race");
    const at = races.indexOf(start.controls.race);
    const [key, back, next] = at < races.length - 1 ? ["ArrowDown", "ArrowUp", races[at + 1]] : ["ArrowUp", "ArrowDown", races[at - 1]];
    await page.keyboard.press(key);
    expect(await page.locator("#sw-race").inputValue()).toBe(next);
    expect(await page.evaluate(() => document.activeElement?.id), "the focus stays on the switch").toBe("sw-race");
    await expectView(page, shard, { ...start.controls, race: next, setup: null, announced: "race" });
    expect(queryOf(page)).toMatchObject({ race: next, role: start.controls.role, tier: String(start.controls.tier) });
    // and back again: the table is the one the page arrived with
    await page.keyboard.press(back);
    await expectView(page, shard, { ...start.controls, setup: null, announced: "race" });
    expect(await readKit(page)).toEqual(start.kit);
    expect(watch.problems()).toEqual([]);
  });

  test("role: Tab to the group, arrows go round it, the table follows and only setups with a scenario are offered", async ({ page, request, watch }) => {
    await open(page, TRIO);
    const shard = await loadShard(request);
    const start = await arrival(page);
    await openSwitches(page, { keyboard: true, assumptions: false });
    await tabTo(page, 'input[name="role"]:checked');
    const roles = await page.$$eval('input[name="role"]', (radios) => radios.map((r) => r.value));
    expect(roles.length).toBeGreaterThanOrEqual(2); // (the fixture's trio offers two builds, the Tank and Melee damage)
    let current = start.controls.role;
    for (let step = 0; step < roles.length; step++) {
      const next = roles[(roles.indexOf(current) + 1) % roles.length];
      await page.keyboard.press("ArrowRight");
      expect(await page.evaluate(() => document.activeElement?.value), "the focus moves with the choice").toBe(next);
      await expectView(page, shard, { ...start.controls, role: next, setup: null, announced: "role" });
      expect((await offeredSetups(page)).sort(), `the weapon setups offered to ${next}`).toEqual(shard.setupsFor(next).sort());
      current = next;
    }
    expect(current, "all the way round").toBe(start.controls.role);
    expect(await readKit(page)).toEqual(start.kit);
    expect(watch.problems()).toEqual([]);
  });

  test("tier: Tab to it, an arrow changes it, the table follows", async ({ page, request, watch }) => {
    await open(page, TRIO);
    const shard = await loadShard(request);
    const start = await arrival(page);
    await openSwitches(page, { keyboard: true, assumptions: false });
    await tabTo(page, "#sw-tier");
    const tiers = await optionValues(page, "#sw-tier");
    const at = tiers.indexOf(String(start.controls.tier));
    const [key, next] = at < tiers.length - 1 ? ["ArrowDown", tiers[at + 1]] : ["ArrowUp", tiers[at - 1]];
    await page.keyboard.press(key);
    expect(await page.locator("#sw-tier").inputValue()).toBe(next);
    await expectView(page, shard, { ...start.controls, tier: Number(next), setup: null, announced: "tier" });
    expect(queryOf(page)).toMatchObject({ tier: next });
    expect(watch.problems()).toEqual([]);
  });

  test("buffs: Tab to Change, Enter opens it, an arrow changes it, the table follows", async ({ page, request, watch }) => {
    await open(page, TRIO);
    const start = await arrival(page);
    await openSwitches(page, { keyboard: true });
    const shard = await loadShard(request, start.controls.ev, "group");
    await tabTo(page, "#assume-buffs > summary");
    await page.keyboard.press("Enter");
    await expect(page.locator("#assume-buffs")).toHaveJSProperty("open", true);
    await tabTo(page, '#assume-buffs input[name="buffs"]:checked', 3);
    await page.keyboard.press("ArrowRight");
    expect(await page.evaluate(() => document.activeElement?.value)).toBe("group");
    await expectView(page, shard, { ...start.controls, buffs: "group", setup: null, announced: "buffs" });
    await expect(page.locator('[data-f="assume-buffs"]')).toHaveText(await page.locator("#buffs-group").getAttribute("data-phrase"));
    expect(queryOf(page)).toMatchObject({ buffs: "group" });
    expect(watch.problems()).toEqual([]);
  });

  test("weapons: Tab to Change, Enter opens it, an arrow moves to the role's next setup, the table follows", async ({ page, request, watch }) => {
    await open(page, TRIO);
    const shard = await loadShard(request);
    const start = await arrival(page);
    await openSwitches(page, { keyboard: true });
    await tabTo(page, "#assume-weapons > summary");
    await page.keyboard.press("Enter");
    await expect(page.locator("#assume-weapons")).toHaveJSProperty("open", true);
    await tabTo(page, '#assume-weapons input[name="setup"]:checked', 3);
    const offered = await offeredSetups(page);
    expect([...offered].sort()).toEqual(shard.setupsFor(start.controls.role).sort());
    expect(offered.length).toBeGreaterThanOrEqual(2);
    // the radio buttons in page order: an arrow goes to the next one that is offered
    const next = offered[(offered.indexOf(start.controls.setup) + 1) % offered.length];
    await page.keyboard.press("ArrowRight");
    expect(await page.evaluate(() => document.activeElement?.value)).toBe(next);
    await expectView(page, shard, { ...start.controls, setup: next, announced: "setup" });
    expect(queryOf(page)).toMatchObject({ setup: next });
    // "best for this role" stays beside the role's best setup alone
    const flagged = await page.$$eval(".best-flag", (flags) => flags.filter((f) => !f.hidden).map((f) => f.closest(".opt").querySelector("input").value));
    expect(flagged).toEqual([shard.best(start.controls.race, start.controls.role, start.controls.tier)]);
    expect(watch.problems()).toEqual([]);
  });

  test("weapons: for a role that lacks a setup the arrow keys go round the setups it has and skip the one it lacks", async ({ page, request, watch }) => {
    await open(page, TRIO);
    const shard = await loadShard(request);
    const start = await arrival(page);
    await openSwitches(page, { keyboard: true, assumptions: false });
    const setups = await page.$$eval('input[name="setup"]', (radios) => radios.map((r) => r.value));
    const roles = await page.$$eval('input[name="role"]', (radios) => radios.map((r) => r.value));
    const role = roles.find((r) => shard.setupsFor(r).length < setups.length);
    test.skip(!role, "every role has every setup in these results");
    // to that role, by keyboard
    await tabTo(page, 'input[name="role"]:checked');
    for (let at = roles.indexOf(start.controls.role); at !== roles.indexOf(role); at = (at + 1) % roles.length) await page.keyboard.press("ArrowRight");
    await expectView(page, shard, { ...start.controls, role, setup: null, announced: "role" });
    // then through its setups
    await tabTo(page, "#assumes > summary", 14); // (the tier, the link that explains the roles, the eight selects of the priorities and the button for their rates come first, then the folded line, then the assumptions it holds)
    await page.keyboard.press("Enter");
    await tabTo(page, "#assume-weapons > summary", 6);
    await page.keyboard.press("Enter");
    await tabTo(page, '#assume-weapons input[name="setup"]:checked', 3);
    const have = shard.setupsFor(role);
    const lacking = setups.filter((s) => !have.includes(s));
    expect(lacking.length).toBeGreaterThan(0);
    const first = (await readControls(page)).setup;
    const visited = [];
    for (let press = 0; press < have.length; press++) {
      await page.keyboard.press("ArrowRight");
      const here = await page.evaluate(() => document.activeElement?.value);
      visited.push(here);
      await expectView(page, shard, { ...start.controls, role, setup: here, announced: "setup" });
    }
    expect(visited.at(-1), "after one turn the keys are back where they began").toBe(first);
    expect([...visited].sort(), "every setup the role has, once").toEqual([...have].sort());
    for (const setup of lacking) expect(visited, `${setup} is never landed on`).not.toContain(setup);
    expect(watch.problems()).toEqual([]);
  });
});

// ---- 3. accessibility (axe) ---------------------------------------------------------------------------------------------------

for (const [name, path] of PAGE_LIST) {
  test(`axe: ${name} page has no serious or critical violations`, async ({ page }, testInfo) => {
    await open(page, path);
    await axe(page, testInfo);
  });
}

test("axe: the trio page with every expander open and another view shown", async ({ page }, testInfo) => {
  await open(page, TRIO);
  await openSwitches(page);
  for (const id of ["assume-buffs", "assume-weapons", "other-setups", "runnerups", "robust"]) {
    const summary = page.locator(`#${id} > summary`);
    if (await summary.isVisible()) await summary.click();
  }
  await expect(page.locator("#runnerups-table")).toBeVisible();
  const races = await optionValues(page, "#sw-race");
  await page.locator("#sw-race").selectOption(races.at(-1));
  await expect(page.locator('[data-f="v-race"]')).not.toHaveText("");
  await expect(page.locator("#status")).toHaveText("");
  await axe(page, testInfo);
});

test("a weapon setup the role has no scenario for is out of the page whole: no label without its radio button, and axe finds nothing", async ({ page, request, watch }, testInfo) => {
  const shard = await loadShard(request);
  await open(page, TRIO);
  // a role and a setup that the page has a choice for, and that have no scenario together (in the fixture: Melee with 1H + shield)
  const setups = await page.$$eval('input[name="setup"]', (radios) => radios.map((r) => r.value));
  const missing = shard.roles.flatMap((role) => setups.map((setup) => ({ role, setup }))).find(({ role, setup }) => !shard.setupsFor(role).includes(setup));
  test.skip(!missing, "every role has every setup in these results");
  await openSwitches(page);
  await page.locator("#assume-weapons > summary").click(); // the labels are drawn only while this is open
  await pick(page, `role-${missing.role}`);
  await expect(page.locator(`#setup-${missing.setup}`)).toBeHidden();
  const drawn = await page.$$eval('input[name="setup"]', (radios) =>
    radios.map((radio) => {
      const boxes = (element) => element.getClientRects().length;
      const label = document.querySelector(`label[for="${radio.id}"]`);
      return {
        setup: radio.value,
        offered: !radio.hidden && !radio.disabled && radio.closest("[hidden]") === null,
        radio: boxes(radio) > 0,
        wrapper: boxes(radio.closest(".opt")) > 0,
        label: label !== null && boxes(label) > 0,
        text: radio.dataset.label,
      };
    }),
  );
  for (const row of drawn) {
    expect(row.label, `${row.setup}: its label is drawn when its radio button is, and not otherwise`).toBe(row.radio);
    expect(row.wrapper, `${row.setup}: so is the box around both`).toBe(row.radio);
    expect(row.radio, `${row.setup}: it is drawn when it is offered`).toBe(row.offered);
  }
  expect(drawn.find((row) => row.setup === missing.setup)).toMatchObject({ offered: false, radio: false, wrapper: false, label: false });
  expect(drawn.filter((row) => row.offered).map((row) => row.setup).sort()).toEqual([...shard.setupsFor(missing.role)].sort());
  // the accessibility tree has the choices that are offered and not the one that is not
  const named = (text) => page.getByRole("radio", { name: text });
  await expect(named(drawn.find((row) => row.setup === missing.setup).text)).toHaveCount(0);
  for (const row of drawn.filter((r) => r.offered)) await expect(named(row.text)).toHaveCount(1);
  await axe(page, testInfo);
  expect(watch.problems()).toEqual([]);
});

// ---- 4. layout: nothing wider than the window ---------------------------------------------------------------------------------

/** How far the page reaches past the window to the right, in pixels (0 when it does not), and what sticks out. */
function overflow(page) {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const widest = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
    // an element that sticks out even where something clips it (the skip link waits above the page, the sprite is empty)
    const name = (el) => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}${typeof el.className === "string" && el.className ? `.${el.className.split(" ")[0]}` : ""}`;
    const sticking = [...document.body.querySelectorAll("*")]
      .filter((el) => !el.closest(".sr-only, .sprite, .skip-link") && el.getClientRects().length > 0)
      .map((el) => ({ el, right: el.getBoundingClientRect().right }))
      .filter(({ right }) => right > width + 1)
      .map(({ el, right }) => `${name(el)} ends at ${Math.round(right)}`);
    return { page: Math.max(0, widest - width), sticking: sticking.slice(0, 5), width };
  });
}

async function expectNoOverflow(page) {
  const found = await overflow(page);
  expect(found.page, `the page is ${found.page}px wider than the ${found.width}px window`).toBe(0);
  expect(found.sticking, "nothing reaches past the window").toEqual([]);
}

for (const [name, path] of PAGE_LIST) {
  test(`${name} page: no horizontal scroll`, async ({ page }) => {
    await open(page, path);
    await expectNoOverflow(page);
  });
}

// T8 and T10: the stance note and the two haste notes are words in the Assumptions; they stay inside the window and pass axe, in the four views (a trio with no stance build or no haste spell skips the part it has none of)
test("the haste notes and the stance note say their words inside the window and pass axe, with the assumptions open and the build that plays the stance chosen", async ({ page }, testInfo) => {
  await open(page, TRIO);
  await openSwitches(page);
  const stance = page.locator('input[name="role"][data-stance]');
  if ((await stance.count()) > 0) {
    await pick(page, await stance.first().getAttribute("id"));
    await expect(page.locator("#assume-weapons > summary")).toContainText("Berserker stance"); // (the folded Weapons line says it; the note is inside the panel)
    await page.locator("#assume-weapons > summary").click();
    await expect(page.locator("#stance-note")).toBeVisible();
    await expect(page.locator("#stance-note")).toContainText("times as fast, applied after the haste cap and on top of whatever haste counts");
  }
  await openAssumptions(page);
  if ((await page.locator("#haste-spell-note").count()) > 0) {
    await page.locator("#assume-buffs > summary").click();
    await expect(page.locator("#haste-spell-note")).toBeVisible();
    await expect(page.locator("#haste-spell-note")).toContainText("Without a spell the best worn haste counts in full");
    await expect(page.locator('[data-f="haste-note"]')).toContainText("With no haste spell it counts in full");
  }
  await expectNoOverflow(page);
  await axe(page, testInfo);
});

/** A shard whose item names and sources are 170 characters long with no space in them, served in place of the real one. */
async function withLongNames(page) {
  const long = "Supercalifragilisticexpialidocious".repeat(5);
  await page.route(`**${DATA}strict-own.json`, async (route) => {
    const response = await route.fetch();
    const doc = await response.json();
    for (const item of doc.items) {
      item[1] = `${long}${item[1]}`;
      item[4] = `${long}${item[4]}`;
    }
    await route.fulfill({ response, json: doc });
  });
  await open(page, TRIO);
  await openSwitches(page);
  await page.locator("#sw-tier").selectOption(await otherTier(page, (await readControls(page)).tier));
  await expect(page.locator('[data-f="name"]').first()).toContainText(long);
}

test("very long item names and sources do not widen the page", async ({ page }) => {
  await withLongNames(page);
  await expectNoOverflow(page);
});

test("the kit is a table on a wide window and stacked cards on a narrow one, with its headers either way", async ({ page }, testInfo) => {
  await open(page, TRIO);
  const display = await page.evaluate(() => ({
    row: getComputedStyle(document.querySelector("#kit-body tr")).display,
    cell: getComputedStyle(document.querySelector("#kit-body td")).display,
    head: getComputedStyle(document.querySelector("#kit thead")).display,
  }));
  if (testInfo.project.use.viewport.width <= 600) expect(display).toMatchObject({ row: "flex", cell: "block" });
  else expect(display).toMatchObject({ row: "table-row", cell: "table-cell", head: "table-header-group" });
  // the semantics survive the layout: every slot is a row header and every column has a header
  await expect(page.locator("#kit-body").getByRole("rowheader")).toHaveCount(22);
  await expect(page.locator("#kit").getByRole("columnheader")).toHaveCount(5); // (slot, item, tier, arrives at, source: no seal column)
});

test("the cards of a narrow window say what each small fact is, and a wide window has no such words", async ({ page }, testInfo) => {
  await open(page, TRIO);
  const labels = await page.evaluate(() => {
    const before = (selector) => [...document.querySelectorAll(selector)].map((cell) => getComputedStyle(cell, "::before").content);
    return { kit: before("#kit-body tr:first-child td"), totals: before("#totals-body tr:first-child td") };
  });
  if (testInfo.project.use.viewport.width <= 600) {
    expect(labels.kit).toEqual(["none", '"Tier "', '"Arrives at "', '"Source "']);
    expect(labels.totals).toEqual(["none", '"cap "', "none"]);
  } else {
    for (const content of [...labels.kit, ...labels.totals]) expect(content).toMatch(/^(none|normal)$/);
  }
});

// ---- 5. response headers and the policy ---------------------------------------------------------------------------------------

test.describe("response headers", () => {
  test("every kind of response carries the headers of site/_headers @once", async ({ request }) => {
    const file = readHeadersFile();
    const html = await (await request.get(TRIO)).text();
    const assets = [...html.matchAll(/(?:href|src)="(\/assets\/[^"]+)"/g)].map((m) => m[1]);
    expect(assets, "a stylesheet and two scripts").toHaveLength(3);
    const urls = [...Object.values(PAGES), ...assets, `${DATA}strict-own.json`, `${DATA}robust.json`, "/robots.txt"];
    for (const url of urls) {
      const response = await request.get(url);
      expect(response.status(), url).toBe(200);
      const headers = response.headers();
      expect(headers["content-security-policy"], `${url}: the policy of site/_headers`).toBe(file.get("content-security-policy"));
      expect(headers["permissions-policy"], `${url}: permissions policy`).toBe(file.get("permissions-policy"));
      expect(headers["x-content-type-options"], `${url}: nosniff`).toBe("nosniff");
      expect(headers["referrer-policy"], `${url}: referrer policy`).toBe("no-referrer");
      expect(headers["x-robots-tag"], `${url}: the preview is built noindex`).toBe("noindex");
    }
    // a redirect (the address without its slash) is just as protected
    const redirect = await request.get("/trio/pal-mnk-ber", { maxRedirects: 0 });
    expect(redirect.status()).toBe(308);
    expect(redirect.headers()["content-security-policy"]).toBe(file.get("content-security-policy"));
    expect(redirect.headers()["x-content-type-options"]).toBe("nosniff");
  });

  test("the scripts and the stylesheet are kept for a year, the pages and the data are asked for again on every visit @once", async ({ request }) => {
    // the files under /assets/ have a hash of their content in their names, so a copy never goes stale; nothing else is cached
    const forever = "public, max-age=31536000, immutable";
    expect([...readHeaderBlocks().keys()]).toEqual(["/*", "/assets/*"]);
    expect(readHeadersFile("/assets/*").get("cache-control"), "the rule for /assets/*").toBe(forever);
    expect(readHeadersFile().has("cache-control"), "the rule for every path sets no cache header").toBe(false);
    const file = readHeadersFile();
    const html = await (await request.get(TRIO)).text();
    const assets = [...html.matchAll(/(?:href|src)="(\/assets\/[^"]+)"/g)].map((m) => m[1]);
    expect(assets, "a stylesheet and two scripts").toHaveLength(3);
    for (const url of assets) {
      expect(url, "the name carries a hash").toMatch(/-[A-Z0-9]{8}\.(css|js)$/);
      const response = await request.get(url);
      expect(response.status(), url).toBe(200);
      expect(response.headers()["cache-control"], `${url}: kept for a year`).toBe(forever);
      // the rule for /assets/* adds to the rule for every path and does not replace it
      expect(response.headers()["content-security-policy"], `${url}: still under the policy`).toBe(file.get("content-security-policy"));
      expect(response.headers()["x-content-type-options"], `${url}: nosniff`).toBe("nosniff");
    }
    for (const url of [...Object.values(PAGES), `${DATA}strict-own.json`, `${DATA}robust.json`, "/robots.txt"]) {
      const response = await request.get(url);
      expect(response.status(), url).toBe(200);
      expect(response.headers()["cache-control"] ?? "", `${url} is asked for again on every visit`).not.toMatch(/immutable|max-age=[1-9]/);
    }
  });

  test("the values are the ones the site is built for @once", async ({ request }) => {
    // written out here as well, so that changing site/_headers and what wrangler sends together cannot go unnoticed
    const csp =
      "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; img-src 'self' data:; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'; require-trusted-types-for 'script'; trusted-types trioforge";
    const file = readHeadersFile();
    expect(file.get("content-security-policy")).toBe(csp);
    expect(file.get("x-content-type-options")).toBe("nosniff");
    expect(file.get("referrer-policy")).toBe("no-referrer");
    const features = file.get("permissions-policy").split(/,\s*/);
    expect(features.length).toBeGreaterThan(10);
    for (const feature of features) expect(feature, "every permission is switched off").toMatch(/^[a-z-]+=\(\)$/);
    for (const needed of ["camera", "microphone", "geolocation", "payment", "usb", "browsing-topics", "attribution-reporting", "interest-cohort"]) {
      expect(features).toContain(`${needed}=()`);
    }
    const response = await request.get(TRIO);
    expect(response.headers()["content-security-policy"]).toBe(csp);
  });
});

test("the policy is enforced by the browser, and the watcher sees a violation when there is one @once", async ({ page, watch }) => {
  await open(page, TRIO);
  const outcome = await page.evaluate(async () => {
    const result = {};
    try {
      await fetch("https://example.invalid/data.json");
      result.fetch = "allowed";
    } catch {
      result.fetch = "refused";
    }
    try {
      document.body.insertAdjacentHTML("beforeend", "<b>x</b>");
      result.html = "allowed";
    } catch (error) {
      result.html = `refused (${error.name})`;
    }
    await new Promise((resolve) => {
      const image = new Image();
      image.onerror = () => resolve((result.image = "refused"));
      image.onload = () => resolve((result.image = "allowed"));
      image.src = "https://example.invalid/pixel.png";
    });
    return result;
  });
  expect(outcome).toEqual({ fetch: "refused", html: "refused (TypeError)", image: "refused" });
  await expect.poll(() => watch.violations().map((v) => v.directive).sort()).toEqual(["connect-src", "img-src", "require-trusted-types-for"]);
  expect(watch.violations().every((v) => v.disposition === "enforce"), "refused, not merely reported").toBe(true);
});

// ---- 6. without JavaScript ----------------------------------------------------------------------------------------------------

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("the trio page shows its default answer, baked in @once", async ({ page, request, watch }) => {
    await page.goto(TRIO);
    const shard = await loadShard(request);
    const controls = await readControls(page);
    await expectView(page, shard, controls); // the 22 rows, totals, value, caption and weapons of the view the switches show
    // and all of it is on screen, not merely in the page
    await expect(page.locator("#best-race")).toBeVisible();
    await expect(page.locator("#best-race")).toContainText("Best race for this trio:");
    await expect(page.locator("#kit-body tr")).toHaveCount(22);
    for (const name of await page.locator('#kit-body [data-f="name"]').all()) await expect(name).toBeVisible();
    for (const id of ["#kit-caption", "#totals", "#kit-value", "#weapons"]) await expect(page.locator(id)).toBeVisible();
    await expect(page.locator(".note", { hasText: "need JavaScript" })).toBeVisible();
    await expect(page.locator("#theme-toggle")).toBeHidden();
    // an address that asks for another view changes nothing, and nothing breaks
    await page.goto(`${TRIO}?tier=${await otherTier(page, controls.tier)}&role=melee`);
    await expectView(page, shard, controls);
    expect(watch.problems()).toEqual([]);
  });

  test("the other pages read, and the home page links to the live trio @once", async ({ page }) => {
    for (const [name, path] of PAGE_LIST) {
      if (name === "trio") continue;
      await page.goto(path);
      await expect(page.locator("main h1")).toBeVisible();
      expect((await page.locator("main").innerText()).length, `${name} has text`).toBeGreaterThan(200);
    }
    await page.goto("/");
    // from 13 trios on the list of the pages is folded into an expander, whose links are hidden until it is opened (which a visitor does without a script)
    const folded = page.locator("#all-trios > summary");
    if ((await folded.count()) > 0) await folded.click();
    await expect(page.locator('#live-trios a[href="/trio/pal-mnk-ber/"]')).toBeVisible();
    await expect(page.locator("#picker")).toBeHidden();
  });
});

// ---- 7. a view that cannot be loaded -------------------------------------------------------------------------------------------

/** Ways a data file can fail. A function handles the request; `offline` takes the whole browser off the network instead. */
const BROKEN = {
  "the network is down": "offline",
  "a 404": (route) => route.fulfill({ status: 404, contentType: "text/plain", body: "Not found" }),
  "a 500": (route) => route.fulfill({ status: 500, contentType: "text/plain", body: "Server error" }),
  // Cloudflare Pages answers an unknown path with the home page and a 200 when the site has no 404 page of its own
  "a web page with a 200 in place of the data": (route) =>
    route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: "<!doctype html><title>TrioForge</title><p>Best gear</p>" }),
  "JSON of another version": (route) => route.fulfill({ json: { v: 2 } }),
  "a file cut off in the middle": (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"v":1,"ev":"strict","buffs":"own","items":[["w1","Name"' }),
};

for (const [name, how] of Object.entries(BROKEN)) {
  test(`a view that fails to load (${name}) leaves the answer on the page and says so @once`, async ({ page, context, request, watch }) => {
    const shard = await loadShard(request);
    const shards = `**${DATA}*.json`;
    await open(page, TRIO);
    const start = await arrival(page);
    if (how === "offline") await context.setOffline(true);
    else await page.route(shards, how);

    const other = await otherTier(page, start.controls.tier);
    await page.locator("#sw-tier").selectOption(other);
    const status = page.locator("#status");
    await expect(status).toContainText(STATUS_FAILED);
    await expect(status.getByRole("button", { name: "Try again" })).toBeVisible();
    // the page is not blank: it still shows the answer it arrived with, and its switches say so
    expect(await readKit(page)).toEqual(start.kit);
    await expect(page.locator("#kit-body tr")).toHaveCount(22);
    expect(await readControls(page), "the switches went back to the view that is shown").toEqual(start.controls);
    expect(queryOf(page), "the address was not changed").toEqual({});
    expect(watch.problems(["console", "requestfailed", "http"]), "nothing but the failed request went wrong").toEqual([]);

    // with the network back, Try again shows the view
    if (how === "offline") await context.setOffline(false);
    else await page.unroute(shards);
    await status.getByRole("button", { name: "Try again" }).click();
    await expect(status).toHaveText("");
    await expectView(page, shard, { ...start.controls, tier: Number(other), setup: null, announced: "tier" });
  });
}

test("when the answers to two choices arrive in the other order, the last choice is the one shown @once", async ({ page, request, watch }) => {
  const strict = await loadShard(request, "strict", "own");
  await page.route(`**${DATA}strict-group.json`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await open(page, TRIO);
  const start = await arrival(page);
  await openAssumptions(page);
  await page.locator("#assume-buffs > summary").click();
  const slow = page.waitForResponse((r) => r.url().endsWith("/strict-group.json"));
  await pick(page, "buffs-group"); // its answer is slow
  await pick(page, "buffs-own"); // and the page asks again before it comes
  await expectView(page, strict, { ...start.controls, setup: null });
  await slow;
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 150))); // the slow answer has been handled by now
  await expectView(page, strict, { ...start.controls, setup: null });
  await expect(page.locator("#status")).toHaveText("");
  expect(watch.problems()).toEqual([]);
});

test("an address that asks for a view that fails to load shows the default answer and the message @once", async ({ page, request }) => {
  const shard = await loadShard(request);
  await page.route(`**${DATA}*.json`, (route) => route.abort());
  await page.goto(TRIO);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  const start = await arrival(page);
  await page.goto(`${TRIO}?tier=${await otherTier(page, start.controls.tier)}&buffs=group`);
  await expect(page.locator("#status")).toContainText(STATUS_FAILED);
  expect(await readKit(page)).toEqual(start.kit);
  expect(await readControls(page)).toEqual(start.controls);
  await expectView(page, shard, start.controls);
});

test("runner-ups that fail to load say so and leave the answer alone @once", async ({ page, request, watch }) => {
  const shard = await loadShard(request);
  const runnerups = "**/runnerups/*.json";
  await page.route(runnerups, (route) => route.fulfill({ status: 500, contentType: "text/plain", body: "Server error" }));
  await open(page, TRIO);
  const start = await arrival(page);
  await page.locator("#runnerups > summary").click();
  const other = await otherTier(page, start.controls.tier);
  await page.locator("#sw-tier").selectOption(other);
  await expect(page.locator("#runnerups-na")).toContainText(/couldn.t load this section/i);
  await expect(page.locator("#runnerups-table")).toBeHidden();
  await expectView(page, shard, { ...start.controls, tier: Number(other), setup: null });
  await expect(page.locator("#status")).toHaveText("");
  // repaired, closing and opening the expander tries again
  await page.unroute(runnerups);
  await page.locator("#runnerups > summary").click();
  await page.locator("#runnerups > summary").click();
  await expect(page.locator("#runnerups-table")).toBeVisible();
  await expect(page.locator("#runnerups-na")).toBeHidden();
  expect(watch.problems(["console", "requestfailed", "http"])).toEqual([]);
});

// The seals are made for one view of each role and tier (the default race, the buffs of the default answer, and the
// role's best weapon setup). The page shows them for that view alone: for any other it would describe a kit that is not on the screen.
test("the robust core shows its seals for the view they were made for and says it was not computed for any other @once", async ({ page, request, watch }) => {
  const robust = await (await request.get(`${DATA}robust.json`)).json();
  await open(page, TRIO);
  const start = await arrival(page);
  const sealed = robust.views.find(([role, tier]) => role === start.controls.role && tier === start.controls.tier);
  expect(sealed, "the data has seals for the view the page opens on").toBeTruthy();
  expect(sealed.slice(2, 5), "and they were made for it").toEqual([start.controls.setup, start.controls.ev, start.controls.buffs]);
  await page.locator("#robust > summary").click();
  const shown = () => expect(page.locator("#robust-summary")).toBeVisible();
  const missing = async () => {
    await expect(page.locator("#robust-summary")).toBeHidden();
    await expect(page.locator("#robust-na")).toBeVisible();
    await expect(page.locator("#robust-na")).toContainText(/not computed for this view/i);
  };
  await shown();
  // another weapon setup
  const shard = await loadShard(request);
  const other = shard.setupsFor(start.controls.role).find((setup) => setup !== start.controls.setup);
  await openAssumptions(page);
  await page.locator("#assume-weapons > summary").click();
  await pick(page, `setup-${other}`);
  await missing();
  await pick(page, `setup-${start.controls.setup}`);
  await shown();
  // the other buffs
  await page.locator("#assume-buffs > summary").click();
  await pick(page, `buffs-${start.controls.buffs === "own" ? "group" : "own"}`);
  await missing();
  await pick(page, `buffs-${start.controls.buffs}`);
  await shown();
  expect(watch.problems()).toEqual([]);
});

// ---- 8. an address the visitor wrote by hand ----------------------------------------------------------------------------------

test.describe("addresses", () => {
  test("a setup the role has no scenario for is never offered; the role's best is shown, with a message @once", async ({ page, request, watch }) => {
    const shard = await loadShard(request);
    await page.goto(TRIO);
    // a role and a setup that the page knows, but that have no scenario together (in the fixture: Melee with 1H + shield)
    const setups = await page.$$eval('input[name="setup"]', (radios) => radios.map((r) => r.value));
    const missing = shard.roles.flatMap((role) => setups.map((setup) => ({ role, setup }))).find(({ role, setup }) => !shard.setupsFor(role).includes(setup));
    test.skip(!missing, "every role has every setup in these results");
    await page.goto(`${TRIO}?role=${missing.role}&setup=${missing.setup}`);
    await expect(page.locator("#theme-toggle")).toBeVisible();
    await expect(page.locator("#status")).toContainText("is not available for this role");
    const controls = await readControls(page);
    expect(controls.role).toBe(missing.role);
    expect(controls.setup, "the role's best setup is shown").toBe(shard.best(controls.race, missing.role, controls.tier));
    await expectView(page, shard, { ...controls, setup: null });
    const offered = await offeredSetups(page);
    expect(offered, "the setup without a scenario is not offered").not.toContain(missing.setup);
    expect([...offered].sort()).toEqual(shard.setupsFor(missing.role).sort());
    // the address is rewritten to the view that is shown; the fall-back is the role's best, which nobody chose, so no setup is pinned
    expect(queryOf(page)).toMatchObject({ role: missing.role });
    expect(queryOf(page).setup).toBeUndefined();
    expect(watch.problems()).toEqual([]);
  });

  test("the address pins a setup only when the visitor chose it: Tank, reload, Balanced shows Balanced's best setup and value @once", async ({ page, request, watch }) => {
    const shard = await loadShard(request);
    await open(page, TRIO);
    const start = await arrival(page);
    // a role whose best setup is not the default role's: the one a page that pinned it would keep
    const other = shard.roles.find((role) => role !== start.controls.role && shard.best(start.controls.race, role, start.controls.tier) !== start.controls.setup);
    test.skip(!other, "every role has the same best setup in these results");
    await pick(page, `role-${other}`);
    await expectView(page, shard, { ...start.controls, role: other, setup: null, announced: "role" });
    expect(queryOf(page).role).toBe(other);
    expect(queryOf(page).setup, "the role's best setup is not written into the address").toBeUndefined();
    await page.reload();
    await expect(page.locator("#theme-toggle")).toBeVisible();
    await expectView(page, shard, { ...start.controls, role: other, setup: null });
    await pick(page, `role-${start.controls.role}`); // back to the first role
    await expectView(page, shard, { ...start.controls, setup: null, announced: "role" });
    expect((await readControls(page)).setup, "the first role's best setup, not the one the other role had").toBe(start.controls.setup);
    expect(queryOf(page).setup).toBeUndefined();
    expect(watch.problems()).toEqual([]);
  });

  test("a complete address opens that view @once", async ({ page, request, watch }) => {
    await page.goto(TRIO);
    const races = await optionValues(page, "#sw-race");
    const tiers = await optionValues(page, "#sw-tier");
    const roles = await page.$$eval('input[name="role"]', (radios) => radios.map((r) => r.value));
    const want = { race: races.at(-1), role: roles.at(-1), tier: Number(tiers.at(-1)), buffs: "group" };
    const shard = await loadShard(request, undefined, want.buffs);
    const setup = shard.setupsFor(want.role).at(-1);
    await page.goto(`${TRIO}?${new URLSearchParams({ ...want, ev: "wiki", setup })}`); // (an ev of a link is ignored: the page reads the one level it is made from)
    await expect(page.locator("#theme-toggle")).toBeVisible();
    await expectView(page, shard, { ...want, setup });
    // a setup that is not the role's best is the visitor's choice and stays in the address; the role's best is not a choice and is dropped from it
    const pinned = setup === shard.best(want.race, want.role, want.tier) ? {} : { setup };
    expect(queryOf(page)).toEqual({ ...Object.fromEntries(Object.entries(want).map(([k, v]) => [k, String(v)])), ...pinned });
    expect(watch.problems()).toEqual([]);
  });

  test("an address with values that mean nothing is ignored: the default answer, no message @once", async ({ page, request, watch }) => {
    const shard = await loadShard(request);
    await page.goto(TRIO);
    await expect(page.locator("#theme-toggle")).toBeVisible();
    const start = await arrival(page);
    await page.goto(`${TRIO}?race=XXX&role=%3Cb%3Ex%3C%2Fb%3E&tier=99&setup=zzz&ev=bogus&buffs=%00`);
    await expect(page.locator("#theme-toggle")).toBeVisible();
    await expect(page.locator("#status")).toHaveText("");
    expect(await readControls(page)).toEqual(start.controls);
    await expectView(page, shard, start.controls);
    expect(await readKit(page)).toEqual(start.kit);
    expect(watch.problems()).toEqual([]);
  });

  test("the address of such a link is brought back to the default view it shows, so that it never passes for a link to it @once", async ({ page, watch }) => {
    await page.goto(TRIO);
    await expect(page.locator("#theme-toggle")).toBeVisible();
    const { controls } = await arrival(page);
    expect(queryOf(page), "the address of the page is left alone until something changes").toEqual({});
    // the role's best setup is not the visitor's choice, so it is not written down
    const canonical = { race: controls.race, role: controls.role, tier: String(controls.tier), buffs: controls.buffs };
    for (const junk of ["race=XXX", "role=%3Cb%3Ex%3C%2Fb%3E", "tier=99", "tier=four", "setup=zzz", "buffs=%00", "race="]) {
      await page.goto(`${TRIO}?${junk}`);
      await expect(page.locator("#theme-toggle")).toBeVisible();
      expect(queryOf(page), junk).toEqual(canonical);
      expect(await readControls(page), junk).toEqual(controls);
    }
    // a link whose values are all clear is not touched, and neither is a parameter that is none of the page's
    await page.goto(`${TRIO}?utm_source=a`);
    await expect(page.locator("#theme-toggle")).toBeVisible();
    expect(queryOf(page)).toEqual({ utm_source: "a" });
    expect(watch.problems()).toEqual([]);
  });
});

// ---- 9. dark mode: the system and the button --------------------------------------------------------------------------------

// the colour the theme paints the content column with (--surface; the frame around it is dark in both themes, so the body says nothing of the theme)
const LIGHT_PAGE = "rgb(248, 239, 214)";
const DARK_PAGE = "rgb(33, 26, 18)";

for (const system of ["light", "dark"]) {
  test.describe(`with the system in ${system} mode`, () => {
    test.use({ colorScheme: system });

    test("the page follows the system until the button is used; the button's choice is kept @once", async ({ page, watch }) => {
      const paint = () => page.evaluate(() => getComputedStyle(document.querySelector("main")).backgroundColor);
      const attribute = () => page.evaluate(() => document.documentElement.getAttribute("data-theme"));
      const stored = () => page.evaluate(() => localStorage.getItem("trioforge-theme"));
      const [systemPaint, otherPaint] = system === "dark" ? [DARK_PAGE, LIGHT_PAGE] : [LIGHT_PAGE, DARK_PAGE];

      await open(page, TRIO);
      const button = page.locator("#theme-toggle");
      // first load: nothing chosen, the system rules, and it keeps ruling when it changes
      expect(await attribute()).toBeNull();
      expect(await stored()).toBeNull();
      expect(await paint()).toBe(systemPaint);
      await expect(button).toHaveText("Theme: auto");
      await page.emulateMedia({ colorScheme: system === "dark" ? "light" : "dark" });
      expect(await paint()).toBe(otherPaint);
      await page.emulateMedia({ colorScheme: system });
      expect(await paint()).toBe(systemPaint);

      // the button goes auto, light, dark, auto; a choice beats the system
      await button.click();
      await expect(button).toHaveText("Theme: light");
      expect([await attribute(), await stored(), await paint()]).toEqual(["light", "light", LIGHT_PAGE]);
      await button.click();
      await expect(button).toHaveText("Theme: dark");
      expect([await attribute(), await stored(), await paint()]).toEqual(["dark", "dark", DARK_PAGE]);

      // and it is kept: after a reload (set before the page paints) and on another page
      await page.reload();
      expect(await attribute()).toBe("dark");
      expect(await paint()).toBe(DARK_PAGE);
      await expect(button).toHaveText("Theme: dark");
      await page.goto("/about/");
      await expect(page.locator("#theme-toggle")).toHaveText("Theme: dark");
      expect(await paint()).toBe(DARK_PAGE);

      // back to auto: the stored choice is gone and the system rules again
      await page.locator("#theme-toggle").click();
      await expect(page.locator("#theme-toggle")).toHaveText("Theme: auto");
      expect([await attribute(), await stored(), await paint()]).toEqual([null, null, systemPaint]);
      await page.reload();
      expect(await attribute()).toBeNull();
      expect(await paint()).toBe(systemPaint);
      expect(watch.problems()).toEqual([]);
    });
  });
}

test("blocked storage does not break the theme button @once", async ({ page, watch }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new DOMException("storage is blocked", "SecurityError");
      },
    });
  });
  await open(page, TRIO);
  const button = page.locator("#theme-toggle");
  await button.click();
  await expect(button).toHaveText("Theme: light");
  expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe("light");
  await button.click();
  await expect(button).toHaveText("Theme: dark");
  expect(await page.evaluate(() => getComputedStyle(document.querySelector("main")).backgroundColor)).toBe(DARK_PAGE);
  expect(watch.problems()).toEqual([]);
});

// ---- 9b. the theme is set before the page is drawn ----------------------------------------------------------------------------------
// A remembered choice is put on <html> by a classic script in the head (no defer, no async, no module: those wait for the end of the page, and
// a first frame in the wrong colours would flash). The check does not read the attribute after the load; it learns what it was when <body>
// was inserted, from the order of the changes that a MutationObserver reports (it reports late, and in order): the attribute as it was set
// by the change that follows the insertion, or as it is now when no change follows.

/** Remember `stored` (a theme or null) for the origin, and record the changes of `data-theme` and the insertion of <body> in their order. */
async function recordTheme(page, stored) {
  await page.addInitScript((choice) => {
    try {
      if (choice) window.localStorage.setItem("trioforge-theme", choice);
    } catch {
      // not the page's origin yet (about:blank): nothing to remember there
    }
    const timeline = [];
    window.__tfTimeline = timeline;
    new MutationObserver((records) => {
      for (const record of records) {
        if (record.type === "attributes") timeline.push({ before: record.oldValue });
        else if ([...record.addedNodes].some((node) => node.nodeName === "BODY")) timeline.push({ body: true });
      }
    }).observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-theme"], attributeOldValue: true });
  }, stored);
}

/** What the record says: whether <body> was seen, the theme when it came, and the theme now. */
function readTheme(page) {
  return page.evaluate(() => {
    const timeline = window.__tfTimeline;
    const at = timeline.findIndex((entry) => entry.body);
    const next = at < 0 ? undefined : timeline.slice(at + 1).find((entry) => "before" in entry);
    const now = document.documentElement.getAttribute("data-theme");
    return { sawBody: at >= 0, whenBodyCame: at < 0 ? undefined : next ? next.before : now, now };
  });
}

for (const system of ["light", "dark"]) {
  test.describe(`the theme before the first paint, with the system in ${system} mode`, () => {
    test.use({ colorScheme: system });

    for (const stored of [null, "light", "dark"]) {
      test(`${stored ? `a stored ${stored} choice is on <html>` : "no stored choice leaves <html> alone"} when <body> is inserted @once`, async ({ page, watch }) => {
        await recordTheme(page, stored);
        await open(page, TRIO);
        expect(await readTheme(page)).toEqual({ sawBody: true, whenBodyCame: stored, now: stored });
        const paint = await page.evaluate(() => getComputedStyle(document.querySelector("main")).backgroundColor);
        expect(paint).toBe((stored ?? system) === "dark" ? DARK_PAGE : LIGHT_PAGE);
        expect(watch.problems()).toEqual([]);
      });
    }
  });
}

test("the script that does it is a classic script of the site's own, in the head, that blocks the parser @once", async ({ page, watch }) => {
  await open(page, TRIO);
  const scripts = await page.$$eval("script", (nodes) =>
    nodes.map((node) => ({ src: node.getAttribute("src"), type: node.getAttribute("type"), defer: node.defer, async: node.async, inHead: node.closest("head") !== null, inline: !node.hasAttribute("src") })),
  );
  const boot = scripts.filter((script) => /^\/assets\/boot-[A-Z0-9]+\.js$/.test(script.src ?? ""));
  expect(boot).toEqual([{ src: expect.any(String), type: null, defer: false, async: false, inHead: true, inline: false }]);
  expect(scripts.filter((script) => script.inline), "no inline script").toEqual([]);
  expect(scripts.filter((script) => script.inHead).map((script) => script.src)).toEqual([boot[0].src]);
  expect(watch.violations(), "the policy allows it").toEqual([]);
});

test("the check sees a theme that comes late: with the head script gone, the page sets it only after <body> is inserted @once", async ({ page }) => {
  // the control of the checks above: without the script in the head the page code still sets the choice, but after the page is read
  await page.route(/\/assets\/boot-[A-Z0-9]+\.js$/, (route) => route.fulfill({ contentType: "text/javascript", body: "" }));
  await recordTheme(page, "light");
  await open(page, TRIO);
  expect(await readTheme(page)).toEqual({ sawBody: true, whenBodyCame: null, now: "light" });
});

// ---- 10. the narrowest phones, and the widths in between -----------------------------------------------------------------------------

test.describe("at 320 px", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("no page scrolls sideways, and long names do not change that @once", async ({ page }) => {
    for (const [, path] of PAGE_LIST) {
      await open(page, path);
      await expectNoOverflow(page);
    }
    await withLongNames(page);
    await expectNoOverflow(page);
  });
});

test("no page scrolls sideways at the widths between a phone and a desktop (200% zoom on a desktop is 640 px) @once", async ({ page }) => {
  const widths = [400, 480, 600, 601, 640, 768, 1024];
  for (const [, path] of PAGE_LIST) {
    await open(page, path);
    for (const width of widths) {
      await page.setViewportSize({ width, height: 800 });
      await expectNoOverflow(page);
    }
  }
  await withLongNames(page);
  for (const width of widths) {
    await page.setViewportSize({ width, height: 800 });
    await expectNoOverflow(page);
  }
});

// ---- 10b. a data file that has fewer weapon setups than another ---------------------------------------------------------------------------
// Each data file carries its own weapon setups, because the setups follow the item pool of the evidence level: a strict pool with no shield the
// trio can wear has no 1H + shield setup while the wiki pool has one, and the precompute then writes no rows for it in the strict files. The
// page offers its weapons switch only the setups of the file it shows; when a change of buffs moves it to a file that lacks the
// setup that was chosen, it shows that file's best setup for the role and says so. The fixture's files all have the shield setup, so the
// ones that should not are served as a real run would write them: without its rows.

const SHIELD = "1h-shield";

/** A data file document as a run writes it when its pool has no shield: the rows of the shield setup are not in it. */
const withoutShield = (doc) => ({ ...doc, rows: doc.rows.filter((row) => row[3] !== SHIELD) });

/** Serve the data files that match `pattern` without the shield rows. */
function serveWithoutShield(page, pattern) {
  return page.route(pattern, async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: withoutShield(await response.json()) });
  });
}

/** Choose the shield setup as a visitor does. A choice must be a change: a click on the radio button that is checked does nothing. */
async function chooseShield(page, shard, role) {
  await openAssumptions(page);
  await page.locator("#assume-weapons > summary").click();
  if ((await readControls(page)).setup === SHIELD) await pick(page, `setup-${shard.setupsFor(role).find((s) => s !== SHIELD)}`);
  await pick(page, `setup-${SHIELD}`);
}

test("a change of buffs to a data file that lacks the chosen setup shows that file's best setup, with a message @once", async ({ page, request, watch }) => {
  const own = await loadShard(request, "strict", "own"); // this file has the shield setup ...
  const group = readShard(withoutShield(await (await request.get(`${DATA}strict-group.json`)).json())); // ... and this one has not
  await serveWithoutShield(page, `**${DATA}strict-group.json`);
  await open(page, TRIO);
  const start = await arrival(page);
  const roles = await page.$$eval('input[name="role"]', (radios) => radios.map((r) => r.value));
  const role = roles.find((r) => own.setupsFor(r).includes(SHIELD));
  test.skip(!role, "no role of these results has the shield setup");
  expect(group.setupsFor(role)).not.toContain(SHIELD);
  if (role !== start.controls.role) {
    await pick(page, `role-${role}`);
    await expectView(page, own, { ...start.controls, role, setup: null, announced: "role" });
  }
  await chooseShield(page, own, role);
  await expectView(page, own, { ...start.controls, role, setup: SHIELD, announced: "setup" });
  expect(await offeredSetups(page)).toEqual(own.setupsFor(role));

  // the other buffs: that file's setups are offered, the chosen one is not among them, and its best is shown with a message
  await openAssumptions(page);
  await page.locator("#assume-buffs > summary").click();
  await pick(page, "buffs-group");
  await expect(page.locator("#status")).toContainText("is not available for this role");
  const controls = await readControls(page);
  expect(controls).toMatchObject({ role, buffs: "group" });
  expect(controls.setup).toBe(group.best(controls.race, role, controls.tier));
  await expectView(page, group, { ...controls, setup: null });
  expect(await offeredSetups(page)).toEqual(group.setupsFor(role));
  expect(queryOf(page)).toMatchObject({ buffs: "group", role });
  expect(queryOf(page).setup, "the fall-back is the file's best, which was not chosen").toBeUndefined();

  // and back: the first file offers all its setups again
  await pick(page, "buffs-own");
  await expect(page.locator("#status")).toHaveText("");
  expect(await offeredSetups(page)).toEqual(own.setupsFor(role));
  expect(watch.problems()).toEqual([]);
});

test("an address that asks for the shield setup of a data file that lacks it is shown that file's best setup, with a message @once", async ({ page, request, watch }) => {
  const strict = readShard(withoutShield(await (await request.get(`${DATA}strict-own.json`)).json()));
  const full = await loadShard(request, "strict", "own"); // (the file as it is, with its shield rows)
  await serveWithoutShield(page, `**${DATA}strict-*.json`);
  await page.goto(TRIO);
  const roles = await page.$$eval('input[name="role"]', (radios) => radios.map((r) => r.value));
  const role = roles.find((r) => full.setupsFor(r).includes(SHIELD));
  test.skip(!role, "no role of these results has the shield setup");
  await page.goto(`${TRIO}?role=${role}&setup=${SHIELD}`);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await expect(page.locator("#status")).toContainText("is not available for this role");
  const controls = await readControls(page);
  expect(controls).toMatchObject({ role, ev: "strict" });
  expect(controls.setup).toBe(strict.best(controls.race, role, controls.tier));
  await expectView(page, strict, { ...controls, setup: null });
  expect(await offeredSetups(page)).toEqual(strict.setupsFor(role));
  expect(queryOf(page)).toMatchObject({ role });
  expect(queryOf(page).setup, "the fall-back is the level's best, which was not chosen").toBeUndefined();
  expect(watch.problems()).toEqual([]);
});

// ---- 11. a summoned item -------------------------------------------------------------------------------------------------------------

test("an item that is summoned arrives at its spell rank, and no copies are counted for it @once", async ({ page, request, watch }) => {
  // the data files have no summoned item yet, so one is made: an item of the view to be shown loses its arrival tier
  const doc = await (await request.get(`${DATA}strict-own.json`)).json();
  await open(page, TRIO);
  const start = await arrival(page);
  const other = Number(await otherTier(page, start.controls.tier));
  const plain = readShard(doc);
  const view = plain.scenario(start.controls.race, start.controls.role, other, plain.best(start.controls.race, start.controls.role, other));
  const item = doc.items.find((row) => row[0] === view.kit.find(Boolean)[0]);
  item[2] = "spell";
  item[3] = null;
  await page.route(`**${DATA}strict-own.json`, (route) => route.fulfill({ json: doc }));
  await page.locator("#sw-tier").selectOption(String(other));
  await expectView(page, readShard(doc), { ...start.controls, tier: other, setup: null, announced: "tier" });
  const row = page.locator("#kit-body tr").filter({ has: page.locator('[data-f="name"]', { hasText: item[1] }) }).first();
  await expect(row.locator('[data-f="arrival"]')).toHaveText("spell rank");
  await expect(row.locator('[data-f="reach"]')).toHaveText("");
  expect(watch.problems()).toEqual([]);
});

// ---- 12. an address that leads nowhere ---------------------------------------------------------------------------------------------
// Cloudflare Pages answers an unknown path with the home page and a 200 unless the site has a 404.html of its own, which turns a data
// file that is missing into a web page that does not parse. With one it answers 404 and shows the site's own page.

/** Addresses the site has nothing at: a folder, a page inside a folder that exists, a data file and a script. */
const NOTHING_HERE = ["/no/such/page/", `${TRIO}no-such-page`, `${DATA}no-such-shard.json`, "/assets/app-00000000.js"];

/** Open an address the site has no file for: the answer is a 404, and the page it carries has started (it reveals the theme button). */
async function openMissing(page, path = NOTHING_HERE[0]) {
  const response = await page.goto(path);
  expect(response?.status(), `${path} answers 404`).toBe(404);
  await expect(page.locator("#theme-toggle")).toBeVisible();
}

test.describe("an address that leads nowhere", () => {
  test("is answered with a 404 and the site's own page, never with the home page and a 200 @once", async ({ request }) => {
    const file = readHeadersFile();
    for (const path of NOTHING_HERE) {
      const response = await request.get(path);
      expect(response.status(), `${path} answers 404`).toBe(404);
      expect(response.headers()["content-type"], `${path} is a web page`).toContain("text/html");
      const body = await response.text();
      expect(body, `${path} is the page-not-found page`).toContain("<h1>Page not found</h1>");
      expect(body, `${path} is not the home page`).not.toContain('data-page="home"');
      // the page that reports the error is as well protected as the pages that work
      expect(response.headers()["content-security-policy"], `${path}: the policy of site/_headers`).toBe(file.get("content-security-policy"));
      expect(response.headers()["x-content-type-options"], `${path}: nosniff`).toBe("nosniff");
    }
  });

  test("shows a page that works: the way back, the theme button, nothing the policy refuses @once", async ({ page, watch }) => {
    await openMissing(page);
    const own = page.url(); // the browser reports the 404 of the page itself, as a failed request and in the console
    await expect(page.locator("main h1")).toHaveText("Page not found");
    const button = page.locator("#theme-toggle");
    await button.click();
    await expect(button).toHaveText("Theme: light");
    await button.click();
    await expect(button).toHaveText("Theme: dark");
    await button.click();
    await expect(button).toHaveText("Theme: auto");
    expect(watch.problems().filter((line) => !line.includes(own)), "nothing but the 404 of the page itself").toEqual([]);
    expect(watch.violations(), "no policy violation").toEqual([]);
    // the way back is a link in the page, and it works from an address that is not at the top of the site
    await page.locator("main").getByRole("link", { name: "Go to the home page" }).click();
    await expect(page.locator("#picker")).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/");
  });

  test("axe: the page-not-found page has no serious or critical violations", async ({ page }, testInfo) => {
    await openMissing(page);
    await axe(page, testInfo);
  });

  test("the page-not-found page has no horizontal scroll", async ({ page }) => {
    await openMissing(page);
    await expectNoOverflow(page);
  });

  test("a data file the server really does not have: its own 404 comes back, the answer stays on the page and the page says so @once", async ({ page, request, watch }) => {
    const shard = await loadShard(request);
    await open(page, TRIO);
    const start = await arrival(page);
    // the page asks for a path the server has no file for, and nothing is made up: the server answers by itself
    const lost = `**${DATA}*.json`;
    await page.route(lost, (route) => route.continue({ url: new URL(`${DATA}no-such-shard.json`, route.request().url()).href }));
    const answer = page.waitForResponse((r) => r.url().endsWith("/no-such-shard.json"));
    const other = await otherTier(page, start.controls.tier);
    await page.locator("#sw-tier").selectOption(other);
    const response = await answer;
    expect(response.status(), "the server's answer for a file it does not have").toBe(404);
    expect(response.headers()["content-type"]).toContain("text/html");
    const status = page.locator("#status");
    await expect(status).toContainText(STATUS_FAILED);
    await expect(status.getByRole("button", { name: "Try again" })).toBeVisible();
    // the page is not blank: it still shows the answer it arrived with, and its switches say so
    expect(await readKit(page)).toEqual(start.kit);
    await expect(page.locator("#kit-body tr")).toHaveCount(22);
    expect(await readControls(page), "the switches went back to the view that is shown").toEqual(start.controls);
    expect(queryOf(page), "the address was not changed").toEqual({});
    expect(watch.problems(["console", "requestfailed", "http"]), "nothing but the failed request went wrong").toEqual([]);
    // the file is there again: Try again shows the view
    await page.unroute(lost);
    await status.getByRole("button", { name: "Try again" }).click();
    await expect(status).toHaveText("");
    await expectView(page, shard, { ...start.controls, tier: Number(other), setup: null, announced: "tier" });
  });
});

// ---- 13. the frame of every page: a preview of partial data, no repository to link to, nothing of the build in the served folder ------------------
// The preview is built `--noindex` and without an owner, from the synthetic results, which hold only some races and tiers, or from real
// ones (see playwright.config.mjs).

test.describe("the frame of every page", () => {
  const EVERY_PAGE = [...PAGE_LIST, ["404", "/no/such/page/"]];

  test("a preview says at the top of every page that its data is partial, exactly when it is @once", async ({ page }) => {
    for (const [name, path] of EVERY_PAGE) {
      const response = await page.goto(path);
      expect(response?.status(), `${path} answers ${name === "404" ? 404 : 200}`).toBe(name === "404" ? 404 : 200);
      const banner = page.locator(".preview-banner");
      if (!RESULTS_PARTIAL) {
        expect(await banner.count(), `${name}: no banner over results of the full grid`).toBe(0);
        continue;
      }
      await expect(banner, `${name}: the banner`).toBeVisible();
      await expect(banner).toContainText("Preview: partial data");
      expect(await banner.evaluate((node) => node.closest("header") !== null), `${name}: in the header, above the answer`).toBe(true);
    }
  });

  test("a preview with no owner links to no repository, and says when reports open @once", async ({ page }) => {
    for (const [name, path] of EVERY_PAGE) {
      await page.goto(path);
      const ours = page.locator('a[href^="https://github.com/"][href*="/trioforge/"]');
      expect(await ours.count(), `${name}: no link to a repository`).toBe(0);
      await expect(page.locator("footer"), `${name}: the footer says when reports open`).toContainText("Reports open when the project is public");
    }
    await page.goto(PAGES.about);
    await expect(page.locator("main")).toContainText("Reports open when the project is public");
  });

  test("the folder that is served holds nothing of the build: no marker file @once", async ({ request }) => {
    const response = await request.get("/.trioforge-build");
    expect(response.status(), "the marker of the build folder is not served").toBe(404);
    expect(await response.text()).toContain("<h1>Page not found</h1>");
  });
});

// ---- 14. a phone: the answer on the first screen, with the switches folded behind one line ------------------------------------------------------
// The race, role, tier and assumption switches would fill the first screen of a phone, so they fold into one line that says what is shown and a
// Change button that opens them. Under the banner of this preview and all, "Wear this" and its first row are then on the first screen.

const PHONE = { width: 360, height: 740 };

test.describe("on a phone (360 by 740)", () => {
  test.use({ viewport: PHONE });

  test("the answer is on the first screen, and the switches are behind a Change button that opens them @once", async ({ page, request, watch }) => {
    const shard = await loadShard(request);
    await open(page, TRIO);
    const start = await arrival(page);
    const [raceName, roleName] = await page.evaluate(() => [
      document.querySelector("#sw-race option:checked").dataset.label,
      document.querySelector('input[name="role"]:checked').dataset.label,
    ]);
    // the switches are folded into one line that says what is shown, and a button
    await expect(page.locator("#view-bar")).toBeVisible();
    await expect(page.locator("#view-summary")).toContainText(`${raceName} · ${roleName} · +${start.controls.tier}`);
    await expect(page.locator("#switches")).toBeHidden();
    const toggle = page.locator("#switches-toggle");
    await expect(toggle).toHaveText("Change");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    // the answer: the heading and its first row are on the first screen, under the banner of this preview and all
    const heading = await page.locator("#wear-h").boundingBox();
    expect(heading.y + heading.height, `the heading ends at ${heading.y + heading.height}`).toBeLessThanOrEqual(PHONE.height);
    const first = await page.locator("#kit-body tr").first().boundingBox();
    expect(first.y + first.height, `the first row ends at ${first.y + first.height}`).toBeLessThanOrEqual(PHONE.height);
    // Change opens them, and they work
    await toggle.click();
    await expect(page.locator("#switches")).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const other = await otherTier(page, start.controls.tier);
    await page.locator("#sw-tier").selectOption(other);
    await expectView(page, shard, { ...start.controls, tier: Number(other), setup: null, announced: "tier" });
    await expect(page.locator("#view-summary")).toContainText(`+${other}`);
    // and it closes again, with the focus where the visitor left it: on the button
    await toggle.click();
    await expect(page.locator("#switches")).toBeHidden();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(toggle).toBeFocused();
    expect(watch.problems()).toEqual([]);
  });

  test("the page does not jump when its code starts: the line and the room for the button are there from the first paint @once", async ({ page }) => {
    await page.addInitScript(() => {
      window.__shifts = [];
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) window.__shifts.push(entry.value);
      }).observe({ type: "layout-shift", buffered: true });
    });
    await open(page, TRIO);
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const shifts = await page.evaluate(() => window.__shifts);
    expect(shifts.reduce((total, value) => total + value, 0), `layout shifts: ${JSON.stringify(shifts)}`).toBeLessThan(0.001);
    await expect(page.locator("#switches-toggle")).toBeVisible(); // and the code did start
  });

  test("a browser that does not know the scripting media query gets the line and the button as soon as the page code has started @once", async ({ page }) => {
    // the stylesheet is served as such a browser would read it: the query is one that never matches
    await page.route("**/assets/site-*.css", async (route) => {
      const response = await route.fetch();
      const css = await response.text();
      expect(css, "the stylesheet has the query").toMatch(/\(scripting:\s*enabled\)/);
      await route.fulfill({ response, body: css.replace(/\(scripting:\s*enabled\)/g, "(scripting: never)") });
    });
    await open(page, TRIO);
    await expect(page.locator("#view-bar")).toBeVisible();
    await expect(page.locator("#switches-toggle")).toBeEnabled();
    await page.locator("#switches-toggle").click();
    await expect(page.locator("#switches")).toBeVisible();
  });

  test("the switches fold at 600 px and below, and are all in view above it @once", async ({ page }) => {
    await open(page, TRIO);
    for (const [width, folded] of [
      [320, true],
      [600, true],
      [601, false],
      [1280, false],
    ]) {
      await page.setViewportSize({ width, height: PHONE.height });
      if (folded) {
        await expect(page.locator("#switches"), `${width} px: folded`).toBeHidden();
        await expect(page.locator("#view-bar"), `${width} px: the line and the button`).toBeVisible();
      } else {
        await expect(page.locator("#switches"), `${width} px: in view`).toBeVisible();
        await expect(page.locator("#view-bar"), `${width} px: no line and no button`).toBeHidden();
      }
    }
  });
});

// ---- 15. what a visitor who cannot see the page is told, and where the focus is ---------------------------------------------------------------

test.describe("live regions and focus", () => {
  test("the status and the announcement are on the page from the start; the empty status is out of sight, not out of the accessibility tree @once", async ({ page }) => {
    await open(page, TRIO);
    await expect(page.getByRole("status"), "#status and #announce").toHaveCount(2);
    expect(await accessibleNames(page, "status"), "both are in the accessibility tree of the browser").toHaveLength(2);
    const status = page.locator("#status");
    await expect(status).toHaveAttribute("aria-live", "polite");
    await expect(status).toBeEmpty();
    const drawn = await status.evaluate((node) => {
      const style = getComputedStyle(node);
      const box = node.getBoundingClientRect();
      return { display: style.display, visibility: style.visibility, width: box.width, height: box.height };
    });
    expect(drawn.display, "display: none would take it out of the tree").not.toBe("none");
    expect(drawn.visibility).toBe("visible");
    expect(Math.max(drawn.width, drawn.height), "and it takes no room: out of sight").toBeLessThanOrEqual(1);
  });

  test("a view that cannot be loaded says which switch went back and why, and Try again keeps its place @once", async ({ page, request, watch }) => {
    const shard = await loadShard(request);
    const shards = `**${DATA}*.json`;
    await open(page, TRIO);
    const start = await arrival(page);
    await page.route(shards, (route) => route.abort());
    const other = await otherTier(page, start.controls.tier);
    await page.locator("#sw-tier").selectOption(other);
    const status = page.locator("#status");
    const retry = status.getByRole("button", { name: "Try again" });
    await expect(status).toContainText(STATUS_FAILED);
    await expect(status, "the switch that went back, and where").toContainText(`The tier is back at +${start.controls.tier}.`);
    // another try that fails keeps the button, and the focus on it, instead of making a new one
    await retry.focus();
    const handle = await retry.elementHandle();
    await retry.click();
    await expect(status).toContainText(STATUS_FAILED);
    expect(await handle.evaluate((node) => node.isConnected), "the same button").toBe(true);
    await expect(retry).toBeFocused();
    // a slow network: the button is still there, and still focused, while the view loads again
    await page.unroute(shards);
    await page.route(shards, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 700));
      await route.continue();
    });
    await retry.click();
    await expect(status).toContainText("Loading this view");
    await expect(retry).toBeFocused();
    // it has loaded: the button is gone, and the focus is on the answer, a place that is always there
    await expect(status).toHaveText("");
    await expect(page.locator("#wear-h")).toBeFocused();
    await expectView(page, shard, { ...start.controls, tier: Number(other), setup: null, announced: "tier" });
    expect(watch.problems(["console", "requestfailed", "http"])).toEqual([]);
  });

  test("a role that cannot be loaded goes back too, and the focus goes back to the role that is on @once", async ({ page, request }) => {
    const shard = await loadShard(request);
    await open(page, TRIO);
    const start = await arrival(page);
    const other = shard.roles.find((role) => role !== start.controls.role);
    const [startLabel, otherLabel] = await Promise.all([start.controls.role, other].map((role) => page.locator(`#role-${role}`).getAttribute("data-label")));
    await page.route(`**${DATA}*.json`, (route) => route.abort());
    await tabTo(page, 'input[name="role"]:checked');
    // the keyboard moves the focus and the choice together, as an arrow key does
    for (let pressed = 0; (await readControls(page)).role !== other && pressed < shard.roles.length; pressed++) await page.keyboard.press("ArrowRight");
    await expect(page.locator("#status")).toContainText(`The role is back at ${startLabel}.`);
    expect((await readControls(page)).role).toBe(start.controls.role);
    expect(await page.evaluate(() => document.activeElement?.value), `the focus is on ${startLabel}, not on ${otherLabel}`).toBe(start.controls.role);
  });
});

// ---- 15b. the tiers of a trio: the scope of the run ---------------------------------------------------------------------------------------------
// A trio is precomputed at a scope of tiers (+0, +4 and +10 for most; every tier for the first trio), and the page offers those and no others.
// The file of each role holds every one of them, and there is no file for a role and a tier.

test("the tier switch offers the tiers of the data and no others, and a link that names another tier shows the default view @once", async ({ page, request, watch }) => {
  const shard = await loadShard(request);
  await open(page, TRIO);
  const start = await arrival(page);
  const offered = await optionValues(page, "#sw-tier");
  expect(offered.map(Number)).toEqual([...shard.tiers].sort((a, b) => a - b)); // the tiers the shard has: not one more, not one fewer
  const absent = ["1", "7", "9", "11", "99"].filter((tier) => !offered.includes(tier));
  expect(absent, "a tier that is not offered").toContain("99");
  for (const tier of absent) {
    await page.goto(`${TRIO}?tier=${tier}`);
    await expect(page.locator("#theme-toggle")).toBeVisible();
    expect(await readControls(page), `?tier=${tier} shows the default view`).toEqual(start.controls);
    expect(await readKit(page)).toEqual(start.kit);
    await expect.poll(() => Number(queryOf(page).tier), { message: `the address says so too: it names the tier that is shown, not +${tier}` }).toBe(start.controls.tier);
  }
  expect(watch.problems()).toEqual([]);
});

test("every role has one runner-up file with every tier of the data in it, and no role has a file for a tier @once", async ({ request }) => {
  const shard = await loadShard(request);
  const tiers = [...shard.tiers].sort((a, b) => a - b);
  for (const role of shard.roles) {
    const response = await request.get(`${DATA}runnerups/${role}.json`);
    expect(response.ok(), `the runner-ups of ${role} can be fetched`).toBe(true);
    const doc = await response.json();
    expect(doc.v).toBe(2);
    expect(doc.role).toBe(role);
    expect(doc.tiers, `the tiers of the file of ${role}`).toEqual(tiers);
    expect([...new Set(doc.views.map((view) => view[0]))].sort((a, b) => a - b), `the file of ${role} has views at every one of them`).toEqual(tiers);
    expect(doc.views.every((view) => view.length === 4 && view[3].length === 22)).toBe(true);
    for (const tier of tiers) {
      expect((await request.get(`${DATA}runnerups/${role}-${tier}.json`)).status(), `no file for ${role} at +${tier}`).toBe(404);
    }
  }
});

// ---- 16. the alternatives of a view that is not shown any more ------------------------------------------------------------------------------------

test.describe("the expanders while the file of another view comes", () => {
  test("the runner-ups of the old view are taken off the page and the expander says it is loading, until the new ones arrive @once", async ({ page, watch }) => {
    await open(page, TRIO);
    const start = await arrival(page);
    await page.locator("#runnerups > summary").click();
    await expect(page.locator("#runnerups-table")).toBeVisible();
    // the baked view's own runner-ups are in the page; the file of its role (every tier is in it) is asked for the first time the view changes
    const files = (await page.locator("#runnerups").getAttribute("data-files")).split(" ");
    expect(files, "the files are those of the roles").toContain(start.controls.role);
    const tier = await otherTier(page, start.controls.tier);
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    await page.route(`**/runnerups/${start.controls.role}.json`, async (route) => {
      await gate;
      await route.continue();
    });
    await page.locator("#sw-tier").selectOption(tier);
    await expect(page.locator("#runnerups-loading")).toBeVisible();
    await expect(page.locator("#runnerups-table"), "the old view's runner-ups are not shown for the new view").toBeHidden();
    await expect(page.locator("#runnerups")).toHaveAttribute("aria-busy", "true");
    await expect(page.locator('[data-f="v-tier"]'), "the answer itself is already the new view's").toHaveText(`+${tier}`);
    release();
    await expect(page.locator("#runnerups-table")).toBeVisible();
    await expect(page.locator("#runnerups-loading")).toBeHidden();
    await expect(page.locator("#runnerups")).not.toHaveAttribute("aria-busy", /.*/);
    expect(watch.problems()).toEqual([]);
  });

  test("the file of a role holds every tier: a change of tier is read from the file the page has, and a change of role fetches the file of that role @once", async ({ page, watch }) => {
    const asked = [];
    page.on("request", (request) => {
      const found = /\/runnerups\/([a-z-]+\.json)$/.exec(request.url());
      if (found) asked.push(found[1]);
    });
    await open(page, TRIO);
    const start = await arrival(page);
    await openSwitches(page);
    await page.locator("#runnerups > summary").click();
    await expect(page.locator("#runnerups-table")).toBeVisible();
    expect(asked, "the baked view's runner-ups are in the page: nothing is asked for yet").toEqual([]);
    const tiers = await optionValues(page, "#sw-tier");
    const walk = tiers.filter((value) => value !== String(start.controls.tier)).slice(0, 3);
    for (const value of walk) {
      await page.locator("#sw-tier").selectOption(value);
      await expect(page.locator('[data-f="v-tier"]')).toHaveText(`+${value}`);
      await expect(page.locator("#runnerups-loading")).toBeHidden();
    }
    expect(asked, `${walk.length} changes of tier, one file for the role`).toEqual([`${start.controls.role}.json`]);
    const roles = (await page.locator("#runnerups").getAttribute("data-files")).split(" ");
    const other = roles.find((role) => role !== start.controls.role);
    test.skip(other === undefined, "the trio has one role");
    await pick(page, `role-${other}`);
    await expect(page.locator('[data-f="v-role"]')).not.toHaveText("");
    await expect(page.locator("#runnerups-loading")).toBeHidden();
    expect(asked).toEqual([`${start.controls.role}.json`, `${other}.json`]);
    expect(watch.problems()).toEqual([]);
  });

  test("the robust core of the old view is taken off the page the same way @once", async ({ page, watch }) => {
    await open(page, TRIO);
    const start = await arrival(page);
    const other = await otherTier(page, start.controls.tier);
    await page.locator("#sw-tier").selectOption(other); // closed, so nothing is asked for yet
    await expect(page.locator('[data-f="v-tier"]')).toHaveText(`+${other}`);
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    await page.route("**/robust.json", async (route) => {
      await gate;
      await route.continue();
    });
    await page.locator("#robust > summary").click(); // its file is asked for now, and is slow
    await expect(page.locator("#robust-loading")).toBeVisible();
    await expect(page.locator("#robust-summary"), "the baked summary belongs to the first view").toBeHidden();
    await expect(page.locator("#robust-list")).toBeHidden();
    await expect(page.locator("#robust")).toHaveAttribute("aria-busy", "true");
    release();
    await expect(page.locator("#robust-loading")).toBeHidden();
    await expect(page.locator("#robust")).not.toHaveAttribute("aria-busy", /.*/);
    expect(watch.problems()).toEqual([]);
  });
});

// ---- 17. forced colours ------------------------------------------------------------------------------------------------------------------------------

test("in forced colours the chosen radio button is still drawn differently from the others @once", async ({ page }) => {
  await open(page, TRIO);
  await page.emulateMedia({ forcedColors: "active" });
  expect(await page.evaluate(() => matchMedia("(forced-colors: active)").matches), "forced colours are on").toBe(true);
  await openAssumptions(page);
  await page.locator("#assume-buffs > summary").click();
  // the dot is drawn by the stylesheet: a ring (and a gradient, which forced colours drop). What the browser computes for it
  const dot = (id) =>
    page.locator(`label[for="${id}"]`).evaluate((label) => {
      const style = getComputedStyle(label, "::before");
      return { border: `${style.borderTopWidth} ${style.borderTopStyle} ${style.borderTopColor}`, fill: style.backgroundColor, image: style.backgroundImage };
    });
  const [chosen, plain] = [await dot("buffs-own"), await dot("buffs-group")];
  expect(chosen.border, "the chosen dot has a ring of its own").not.toBe(plain.border);
  expect(chosen.image, "and no gradient to be dropped").toBe("none");
  // and what is drawn: the pixels of the two dots differ (a shape, not only a colour)
  const picture = async (id) => {
    const box = await page.locator(`label[for="${id}"]`).boundingBox();
    return page.screenshot({ clip: { x: box.x, y: box.y, width: 22, height: box.height } });
  };
  const [pictureOfChosen, pictureOfPlain] = [await picture("buffs-own"), await picture("buffs-group")];
  expect(Buffer.compare(pictureOfChosen, pictureOfPlain), "the two dots are drawn differently").not.toBe(0);
  // choosing the other one moves the difference with it
  await pick(page, "buffs-group");
  await expect(page.locator('[data-f="assume-buffs"]')).toHaveText(await page.locator("#buffs-group").getAttribute("data-phrase"));
  expect((await dot("buffs-group")).border).toBe(chosen.border);
  expect((await dot("buffs-own")).border).toBe(plain.border);
});

// ---- 18. the switches without script, and what the radio buttons are called ---------------------------------------------------------------------------

test.describe("without JavaScript, the switches", () => {
  test.use({ javaScriptEnabled: false });

  test("are disabled, and the note that says why comes before them @once", async ({ page }) => {
    await page.goto(TRIO);
    for (const selector of ["#sw-race", "#sw-tier", 'input[name="role"]', 'input[name="setup"]', 'input[name="buffs"]']) {
      const controls = await page.locator(selector).all();
      expect(controls.length, selector).toBeGreaterThan(0);
      for (const control of controls) await expect(control, selector).toBeDisabled();
    }
    await expect(page.locator(".note", { hasText: "need JavaScript" })).toBeVisible();
    const noteFirst = await page.evaluate(
      () => Boolean(document.querySelector("noscript").compareDocumentPosition(document.querySelector("#switches")) & Node.DOCUMENT_POSITION_FOLLOWING),
    );
    expect(noteFirst, "the note is before the switches it is about").toBe(true);
  });

  test.describe("on a phone", () => {
    test.use({ viewport: PHONE });

    test("offer no button that cannot work: the note, then the answer on the first screen @once", async ({ page }) => {
      await page.goto(TRIO);
      await expect(page.locator("#view-bar")).toBeHidden();
      await expect(page.locator("#switches")).toBeHidden();
      await expect(page.locator(".note", { hasText: "need JavaScript" })).toBeVisible();
      const first = await page.locator("#kit-body tr").first().boundingBox();
      expect(first.y + first.height, "the first row is on the first screen").toBeLessThanOrEqual(PHONE.height);
    });
  });
});

test.describe("what the radio buttons are called", () => {
  test("a chosen role is named by its label alone: the check mark is drawn and never read", async ({ page }) => {
    await open(page, TRIO);
    await openSwitches(page);
    const labels = await page.$$eval('input[name="role"]', (radios) => radios.map((radio) => radio.dataset.label));
    const names = await accessibleNames(page, "radio");
    for (const label of labels) expect(names, `a radio button named ${label}`).toContain(label);
    expect(names.filter((name) => /[✓✔]/.test(name)), "no name has the check mark in it").toEqual([]);
  });

  test("the best weapon setup of the role is named, and drawn, with a space before (best for this role)", async ({ page }) => {
    await open(page, TRIO);
    await openSwitches(page);
    await page.locator("#assume-weapons > summary").click();
    const best = (await readControls(page)).setup;
    const label = await page.locator(`#setup-${best}`).getAttribute("data-label");
    expect(await accessibleNames(page, "radio")).toContain(`${label} (best for this role)`);
    expect(await page.locator(`label[for="setup-${best}"]`).innerText()).toBe(`${label} (best for this role)`);
  });
});

// ---- 19. a data file that does not belong to the page ---------------------------------------------------------------------------------------------

test("a data file of another release than the page is not used: the page says the data was updated and offers a reload @once", async ({ page, request, watch }) => {
  const shard = await loadShard(request);
  await open(page, TRIO);
  const start = await arrival(page);
  const stale = `**${DATA}*.json`;
  await page.route(stale, async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), release: "data-2099-01-01" } });
  });
  const other = await otherTier(page, start.controls.tier);
  await page.locator("#sw-tier").selectOption(other);
  const status = page.locator("#status");
  await expect(status).toContainText("Data updated, reload");
  await expect(status.getByRole("button", { name: "Reload" })).toBeVisible();
  await expect(status.getByRole("button", { name: "Try again" }), "trying again would only fetch the same file").toHaveCount(0);
  // the answer on the page is still the one that goes with the page
  expect(await readKit(page)).toEqual(start.kit);
  expect(await readControls(page)).toEqual(start.controls);
  expect(queryOf(page)).toEqual({});
  // the reload brings the page that goes with the data
  await page.unroute(stale);
  await Promise.all([page.waitForEvent("load"), status.getByRole("button", { name: "Reload" }).click()]);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await expect(page.locator("#status")).toHaveText("");
  await page.locator("#sw-tier").selectOption(other);
  await expectView(page, shard, { ...start.controls, tier: Number(other), setup: null, announced: "tier" });
  expect(watch.problems()).toEqual([]);
});
