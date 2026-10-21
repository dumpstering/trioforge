// The pages of the items in a real browser (Chromium), served by `wrangler pages dev` with the production headers.
//
// A test without @once in its title runs in four views: a 1280 px and a 360 px wide window, each with the system in light and in dark mode (see playwright.config.mjs).
// The tests take every item from the page or from the item table the site publishes for its optimizer, so they run unchanged on the synthetic fixture and on real results.

import { TRIO, axe, expect, open, openSwitches, optionValues, readHeadersFile, test } from "./support.mjs";

/** The slots of the places of a kit: an item that lists one of them is a wearable, and a wearable of the strict or the wiki level has a page. */
const WEARABLE = new Set("HEAD FACE EAR NECK SHOULDERS ARMS BACK WRIST HANDS FINGER CHEST LEGS FEET WAIST RANGE ANY PRIMARY SECONDARY".split(" "));
const ITEM_PATH = /^\/item\/[a-z0-9][a-z0-9-]{0,99}\/$/;
const keyOf = (record) => record.key ?? `w${record.id}`;
const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** The item table of the site (the file the manifest of the optimizer names), by the level of its records. */
async function itemTable(request) {
  const manifest = await (await request.get("/engine-manifest.json")).json();
  const table = await (await request.get(manifest.items.path)).json();
  const records = table.items.map((record) => ({ record, key: keyOf(record), level: record.evidence.level }));
  return {
    all: records,
    withPage: records.filter(({ record, level }) => (level === "strict" || level === "wiki") && record.slots.some((slot) => WEARABLE.has(slot))),
    without: (level) => records.filter((one) => one.level === level),
  };
}

/** The links in the names of the 22 rows of Wear this, with the text of each. */
function kitLinks(page) {
  return page.$$eval('#kit-body [data-f="name"] a', (anchors) => anchors.map((a) => ({ href: a.getAttribute("href"), text: a.textContent })));
}

/** The figures of a table of tiers, row by row, as the page shows them. */
function tableRows(page, selector = "#tiers") {
  return page.$$eval(`${selector} tbody tr`, (rows) => rows.map((tr) => ({ label: tr.querySelector("th").textContent, cells: [...tr.querySelectorAll("td")].map((td) => td.textContent) })));
}

// ---- from the trio page to an item page and back --------------------------------------------------------------------------------------------

test("a name in Wear this is a link to the page of the item, which shows that item, and the trio is among the ones it is best for", async ({ page, watch }) => {
  await open(page, TRIO);
  const links = await kitLinks(page);
  expect(links.length, "the kit of the default answer has items, and each name is a link").toBeGreaterThan(0);
  expect(await page.locator('#kit-body [data-f="name"]').count()).toBe(22);
  for (const { href } of links) expect(href).toMatch(ITEM_PATH);
  const [first] = links;
  await page.locator(`#kit-body a[href="${first.href}"]`).first().click();
  await expect(page).toHaveURL(new RegExp(`${escapeRegExp(first.href)}$`));
  await expect(page.locator("#theme-toggle")).toBeVisible(); // the page script has run
  await expect(page.locator("main")).toHaveAttribute("data-page", "item");
  await expect(page.locator("h1")).toHaveText(first.text);
  await expect(page).toHaveTitle(`${first.text} · TrioForge`);
  // the kit shown is the default answer of the trio, so the page of each of its items says that the trio wears it (the first twenty trios are named, and this build has fewer)
  await expect(page.locator(`#best-for a[href="${TRIO}"]`)).toHaveCount(1);
  await page.locator(`#best-for a[href="${TRIO}"]`).click();
  await expect(page).toHaveURL(new RegExp(`${escapeRegExp(TRIO)}$`));
  await expect(page.locator("main")).toHaveAttribute("data-page", "trio");
  expect(watch.problems()).toEqual([]);
});

test("the names stay links to the right items when the visitor changes the tier, and a click on one reaches its page", async ({ page, watch }) => {
  await open(page, TRIO);
  const before = await kitLinks(page);
  await openSwitches(page);
  const tiers = await optionValues(page, "#sw-tier");
  const other = tiers.at(-1) === (await page.locator("#sw-tier").inputValue()) ? tiers[0] : tiers.at(-1);
  await page.locator("#sw-tier").selectOption(other);
  await expect(page.locator('[data-f="v-tier"]')).toHaveText(`+${other}`);
  const shown = await page.$$eval("#kit-body tr", (rows) =>
    rows.map((tr) => ({ name: tr.querySelector('[data-f="name"]').textContent, href: tr.querySelector('[data-f="name"] a')?.getAttribute("href") ?? null })),
  );
  for (const row of shown) {
    if (row.name === "Leave empty") expect(row.href, "an empty place is no link").toBeNull();
    else expect(row.href, `the name ${row.name} is a link`).toMatch(ITEM_PATH);
  }
  expect(shown.filter((row) => row.href).length).toBeGreaterThan(0);
  expect(before.length).toBeGreaterThan(0);
  const last = shown.filter((row) => row.href).at(-1);
  await page.locator(`#kit-body a[href="${last.href}"]`).first().click();
  await expect(page).toHaveURL(new RegExp(`${escapeRegExp(last.href)}$`));
  await expect(page.locator("h1")).toHaveText(last.name);
  expect(watch.problems()).toEqual([]);
});

test("every name in Wear this is a link to a page that exists @once", async ({ page, request }) => {
  await open(page, TRIO);
  const links = await kitLinks(page);
  expect(links.length).toBeGreaterThan(0);
  for (const { href } of links) {
    const response = await request.get(href);
    expect(response.status(), href).toBe(200);
    expect(await response.text(), href).toContain('data-page="item"');
  }
});

test("the sources page links the items that have a page, and the links reach them @once", async ({ page, request, watch }) => {
  const { withPage } = await itemTable(request);
  const keys = new Set(withPage.map(({ key }) => key));
  await open(page, "/sources/");
  const links = await page.$$eval("#revisions tbody th a", (anchors) => anchors.map((a) => a.getAttribute("href")));
  expect(links.length).toBeGreaterThan(0);
  for (const href of links) {
    expect(href).toMatch(ITEM_PATH);
    expect(keys.has(href.split("/")[2]), `${href} is the page of a strict or wiki wearable`).toBe(true);
  }
  await page.locator("#revisions-box > summary").click(); // the table is in an expander
  await page.locator(`#revisions tbody th a[href="${links[0]}"]`).click();
  await expect(page).toHaveURL(new RegExp(`${escapeRegExp(links[0])}$`));
  await expect(page.locator("main")).toHaveAttribute("data-page", "item");
  expect(watch.problems()).toEqual([]);
});

// ---- the page of an item in the four views --------------------------------------------------------------------------------------------------

/** Some items that the page must show well: the first of the table, a weapon, the one with the most stats, a Lore item and one that needs a deity, where the table has them. */
async function samples(request) {
  const { withPage } = await itemTable(request);
  const stats = ({ record }) => Object.keys(record.stats ?? {}).length + Object.keys(record.sv ?? {}).length;
  const found = [
    withPage[0],
    withPage.find(({ record }) => record.weapon && record.weapon.dmg !== null && record.weapon.delay !== null && !record.item_type),
    withPage.reduce((best, one) => (stats(one) > stats(best) ? one : best), withPage[0]),
    withPage.find(({ record }) => record.lore === true),
    withPage.find(({ record }) => Array.isArray(record.deity)),
  ].filter(Boolean);
  return [...new Map(found.map((one) => [one.key, one])).values()];
}

test("the page of an item is accessible (axe) and has no console error or policy violation, whatever the item", async ({ page, request, watch }, testInfo) => {
  for (const { key, record } of await samples(request)) {
    await open(page, `/item/${key}/`);
    await expect(page.locator("h1")).toHaveText(record.name);
    await axe(page, testInfo, { impacts: ["moderate", "serious", "critical"] }); // a page of an item has no moderate finding either (two landmarks of one name was one)
  }
  expect(watch.problems()).toEqual([]);
});

test("the table of tiers has the tiers for its headers and eleven figures in each row, and it scrolls inside its own region on a phone and fits on a desktop", async ({ page, request }, testInfo) => {
  const [{ key, record }] = await samples(request);
  await open(page, `/item/${key}/`);
  await expect(page.locator("#tiers thead th")).toHaveText(["Stat", ...Array.from({ length: 11 }, (_, tier) => `+${tier}`)]);
  const rows = await tableRows(page);
  expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) expect(row.cells, row.label).toHaveLength(11);
  const region = page.locator(".scroll").first();
  await expect(region).toHaveAttribute("tabindex", "0");
  await expect(region).toHaveAttribute("role", "region");
  const box = await region.evaluate((node) => ({ scroll: node.scrollWidth, client: node.clientWidth }));
  if (testInfo.project.use.viewport.width <= 600) {
    expect(box.scroll, "the table is wider than the phone and scrolls in its region").toBeGreaterThan(box.client);
    await region.focus();
    for (let press = 0; press < 3; press++) await page.keyboard.press("ArrowRight");
    expect(await region.evaluate((node) => node.scrollLeft), "the arrow keys scroll the region sideways").toBeGreaterThan(0);
    await expect(page.locator("#tiers tbody tr").first().locator("th")).toBeInViewport(); // the names of the stats stay in view
  } else {
    expect(box.scroll, "the table fits a desktop window").toBeLessThanOrEqual(box.client);
  }
  // the +0 figure of a stat is the stat of the table's record, whatever the item
  const first = rows.find((row) => row.label === "Strength" || row.label === "AC" || row.label === "Hit points" || row.label === "Mana");
  if (first) {
    const stat = { Strength: "STR", AC: "AC", "Hit points": "HP", Mana: "MANA" }[first.label];
    expect(Number(first.cells[0].replace(/,/g, "").replace("−", "-"))).toBe(record.stats[stat]);
  }
});

test("a weapon has a second table with its damage and its delay, and the seal of the rule that raises the damage", async ({ page, request }) => {
  const weapon = (await samples(request)).find(({ record }) => record.weapon && record.weapon.dmg !== null);
  test.skip(!weapon, "these results have no weapon with a page");
  await open(page, `/item/${weapon.key}/`);
  const rows = await tableRows(page, "#weapon-tiers");
  expect(rows.map((row) => row.label)).toEqual(["Damage", "Delay"]);
  expect(rows[0].cells[0]).toBe(String(weapon.record.weapon.dmg));
  expect(new Set(rows[1].cells)).toEqual(new Set([String(weapon.record.weapon.delay)]));
  const rule = page.locator("#weapon a[href='/rules/#tier.weapon_damage_pct']");
  await expect(rule).toHaveCount(1);
  await expect(page.locator("#weapon .seal")).toHaveCount(1);
});

test("nothing on the page of an item reaches past the window except the table in its own region", async ({ page, request }) => {
  for (const { key } of await samples(request)) {
    await open(page, `/item/${key}/`);
    const found = await page.evaluate(() => {
      const width = document.documentElement.clientWidth;
      const widest = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
      const sticking = [...document.body.querySelectorAll("*")]
        .filter((el) => !el.closest(".sr-only, .sprite, .skip-link, .scroll") && el.getClientRects().length > 0 && el.getBoundingClientRect().right > width + 1)
        .map((el) => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}`);
      return { page: Math.max(0, widest - width), sticking: sticking.slice(0, 5), width };
    });
    expect(found.page, `${key}: the page is ${found.page}px wider than the ${found.width}px window`).toBe(0);
    expect(found.sticking, `${key}: nothing reaches past the window`).toEqual([]);
  }
});

test("the theme button works on the page of an item", async ({ page, request, watch }) => {
  const [{ key }] = await samples(request);
  await open(page, `/item/${key}/`);
  const button = page.locator("#theme-toggle");
  await button.click();
  await expect(button).toHaveText("Theme: light");
  await button.click();
  await expect(button).toHaveText("Theme: dark");
  await button.click();
  await expect(button).toHaveText("Theme: auto");
  expect(await page.context().cookies(), "no cookies").toEqual([]);
  expect(watch.problems()).toEqual([]);
});

// ---- the first load -------------------------------------------------------------------------------------------------------------------------------

test("a page of an item asks for the page, the stylesheet, the boot script and the page script and for nothing else: no data, no chunk, no optimizer @once", async ({ page, request }) => {
  const [{ key }] = await samples(request);
  const asked = [];
  page.on("request", (one) => asked.push(new URL(one.url()).pathname));
  await open(page, `/item/${key}/`);
  await page.waitForLoadState("networkidle");
  expect(asked.filter((path) => !path.startsWith("/assets/"))).toEqual([`/item/${key}/`]);
  // the three files every page loads first: the same as the trio page's
  const trio = await (await request.get(TRIO)).text();
  const trioAssets = [...trio.matchAll(/(?:href|src)="(\/assets\/[^"]+)"/g)].map((m) => m[1]).sort();
  expect(trioAssets, "a stylesheet and two scripts").toHaveLength(3);
  // the files the page names, and besides them the pictures of the theme that its stylesheet asks for: hashed PNGs of this site
  const wanted = asked.filter((path) => path.startsWith("/assets/"));
  expect(wanted.filter((path) => !path.endsWith(".png")).sort()).toEqual(trioAssets);
  for (const path of wanted.filter((path) => path.endsWith(".png"))) expect(path, "a picture of the theme").toMatch(/^\/assets\/[a-z0-9-]+-[A-Z0-9]{8}\.png$/);
});

// ---- an item with no page ---------------------------------------------------------------------------------------------------------------------------

test("an item that is disputed or hidden has no page: the address answers 404 with the page for an address that leads nowhere @once", async ({ page, request }) => {
  const table = await itemTable(request);
  const without = [...table.without("hidden").slice(0, 1), ...table.without("disputed").slice(0, 1)];
  expect(without.length, "the table has an item that is hidden or disputed").toBeGreaterThan(0);
  for (const { key, level } of without) {
    const response = await request.get(`/item/${key}/`);
    expect(response.status(), `/item/${key}/ (${level})`).toBe(404);
    expect(await response.text()).toContain("Page not found");
    const shown = await page.goto(`/item/${key}/`);
    expect(shown?.status()).toBe(404);
    await expect(page).toHaveTitle("Page not found · TrioForge");
    await expect(page.locator("h1")).toHaveText("Page not found");
  }
  // an address that no item has, however it is written
  for (const path of ["/item/w0/", "/item/NOT-A-KEY/", "/item/", "/item"]) {
    const response = await request.get(path, { maxRedirects: 0 });
    expect([301, 308, 404], path).toContain(response.status());
  }
  // and no page of the site links to one of these items
  const hidden = new Set(without.map(({ key }) => `/item/${key}/`));
  for (const path of [TRIO, "/sources/", "/"]) {
    const links = await (await request.get(path)).text();
    for (const address of hidden) expect(links, `${path} links to ${address}`).not.toContain(`href="${address}"`);
  }
});

test("a strict or wiki wearable has a page that answers 200 with the page of an item @once", async ({ request }) => {
  const { withPage } = await itemTable(request);
  expect(withPage.length).toBeGreaterThan(0);
  for (const { key } of [withPage[0], withPage.at(-1)]) {
    const response = await request.get(`/item/${key}/`);
    expect(response.status(), key).toBe(200);
    expect(await response.text()).toContain('data-page="item"');
  }
});

// ---- headers, and without JavaScript ----------------------------------------------------------------------------------------------------------------

test("the page of an item carries the headers of site/_headers like every page @once", async ({ request }) => {
  const [{ key }] = await samples(request);
  const response = await request.get(`/item/${key}/`);
  const file = readHeadersFile();
  expect(response.headers()["content-security-policy"]).toBe(file.get("content-security-policy"));
  expect(response.headers()["x-content-type-options"]).toBe("nosniff");
  expect(response.headers()["referrer-policy"]).toBe("no-referrer");
  expect(response.headers()["x-robots-tag"], "the preview is built noindex").toBe("noindex");
  expect(response.headers()["cache-control"] ?? "", "asked for again on every visit").not.toMatch(/immutable|max-age=[1-9]/);
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("the page of an item is whole: the facts, the tables, the sources, the trios and the credit @once", async ({ page, request }) => {
    const [{ key, record }] = await samples(request);
    await page.goto(`/item/${key}/`);
    await expect(page.locator("h1")).toHaveText(record.name);
    for (const id of ["#tiers", "#credit"]) await expect(page.locator(id)).toBeVisible();
    await expect(page.locator("#tiers tbody tr").first()).toBeVisible();
    expect(await page.locator("h2").allTextContents()).toEqual(expect.arrayContaining(["Stats by tier", "Sources", "Best for these trios", "Wiki credit"]));
    await expect(page.locator("#theme-toggle")).toBeHidden(); // (it is the page script that shows it)
  });
});
