// The home page in a real browser (Chromium), served by `wrangler pages dev` with the production headers: the picker with its search box and its chips, the list of every trio page that
// works without JavaScript, and what the first load of the page asks for.
//
// The tests take the trios from the optimizer's manifest and the classes from the chips, so they run unchanged on the fixture (one trio built), on real results, on any number of trios, and on a
// grid whose every trio is built (where the steps about a trio that is "coming soon" are left out, and the test says so).
//
// A test without @once in its title runs in four views: a 1280 px and a 360 px wide window, each with the system in light and in dark mode (see playwright.config.mjs).

import { encodeKit } from "../pipeline/trioforge/site/static/input/kitcode.js";
import { MAX_QUERY_LENGTH } from "../pipeline/trioforge/site/static/picker.js";
import { axe, expect, open, optionValues, pick, readControls, test } from "./support.mjs";
import { builtTrios, firstUnbuilt, trioCount } from "./trios.mjs";

const permutations = (items) =>
  items.length <= 1 ? [items] : items.flatMap((item, at) => permutations([...items.slice(0, at), ...items.slice(at + 1)]).map((rest) => [item, ...rest]));

/** The classes the chips offer: code and name, in the order of the page (which is the order of the site's classes). */
function chipClasses(page) {
  return page.$$eval('#picker input[type="checkbox"]', (boxes) => boxes.map((box) => ({ code: box.value, name: document.querySelector(`label[for="${box.id}"]`).textContent })));
}

const nameOf = (classes, slug) => slug.split("-").map((code) => classes.find((one) => one.code === code.toUpperCase()).name).join(" / ");

async function type(page, text) {
  const box = page.locator("#trio-search");
  await box.fill(text);
}

const chosen = (page) => page.$$eval('#picker input[type="checkbox"]:checked', (boxes) => boxes.map((box) => box.value));

// ---- the search --------------------------------------------------------------------------------------------------------------------------

test("typing the classes of a built trio into the search box, in any order and any case, selects them and offers the page", async ({ page, request, watch }) => {
  const [slug] = await builtTrios(request);
  await open(page, "/");
  const classes = await chipClasses(page);
  const codes = slug.split("-");
  const full = nameOf(classes, slug).split(" / ");
  await expect(page.locator("#picker")).toBeVisible();
  for (const order of permutations([0, 1, 2])) {
    for (const typed of [order.map((i) => codes[i]).join(" "), order.map((i) => codes[i].toUpperCase()).join("  "), order.map((i) => full[i]).join(", ")]) {
      await type(page, typed);
      await expect(page.locator("#picker-status a"), typed).toHaveAttribute("href", `/trio/${slug}/`);
      expect(await chosen(page), typed).toEqual(codes.map((code) => code.toUpperCase()));
    }
  }
  expect(watch.problems()).toEqual([]);
});

test("the chips, chosen in any order, offer the same page, and the box shows what they chose", async ({ page, request }) => {
  const [slug] = await builtTrios(request);
  await open(page, "/");
  const codes = slug.toUpperCase().split("-");
  for (const order of permutations(codes)) {
    for (const code of codes) await pick(page, `class-${code}`, false);
    for (const code of order) await pick(page, `class-${code}`);
    await expect(page.locator("#picker-status a"), order.join(" ")).toHaveAttribute("href", `/trio/${slug}/`);
    await expect(page.locator("#trio-search")).toHaveValue(codes.map((code) => code.toLowerCase()).join(" "));
  }
});

test("a trio that is not built says coming soon, plainly, and has no link @once", async ({ page, request }) => {
  const trios = await builtTrios(request);
  await open(page, "/");
  const classes = await chipClasses(page);
  const unbuilt = firstUnbuilt(classes.map((one) => one.code), trios);
  test.skip(unbuilt === null, "every trio of the grid is built, so none is left to be coming soon");
  const codes = unbuilt.toUpperCase().split("-");
  const name = nameOf(classes, unbuilt);
  await type(page, codes.map((code) => code.toLowerCase()).reverse().join(" "));
  await expect(page.locator("#picker-status")).toHaveText(`${name}: coming soon. There is no page for this trio yet.`);
  await expect(page.locator("#picker-status a")).toHaveCount(0);
  expect(await chosen(page)).toEqual(codes);
  // through the chips as well
  await type(page, "");
  for (const code of codes) await pick(page, `class-${code}`);
  await expect(page.locator("#picker-status")).toHaveText(`${name}: coming soon. There is no page for this trio yet.`);
});

test("the search says how many classes are left, names a word that is no class, and does not mind a word still being typed @once", async ({ page }) => {
  await open(page, "/");
  await type(page, "pal");
  await expect(page.locator("#picker-status")).toHaveText("Pick 2 more classes.");
  await type(page, "pal mnk bers");
  await expect(page.locator("#picker-status")).toHaveText("Pick 1 more class.");
  await type(page, "pal mnk xyz");
  await expect(page.locator("#picker-status")).toHaveText("Pick 1 more class. Not a class: xyz.");
  await type(page, "");
  await expect(page.locator("#picker-status")).toHaveText("");
  await expect(page.locator("#picker-status")).not.toContainText("Not a class");
});

test("a trio is opened from the keyboard alone: type the classes, press Enter @once", async ({ page, request }) => {
  const [slug] = await builtTrios(request);
  await open(page, "/");
  await page.locator("#trio-search").focus();
  await page.keyboard.type(slug.split("-").reverse().join(" "));
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/trio/${slug}/$`));
  await expect(page.locator("main")).toHaveAttribute("data-page", "trio");
});

test("the search box has the cursor when the address says #search, and not otherwise @once", async ({ page }) => {
  await open(page, "/#search");
  await expect(page.locator("#trio-search")).toBeFocused();
  await open(page, "/");
  await expect(page.locator("#trio-search")).not.toBeFocused();
});

test("nothing is stored and no cookie is set by searching @once", async ({ page, watch }) => {
  await open(page, "/");
  await type(page, "pal mnk ber");
  await type(page, "");
  expect(await page.context().cookies(), "no cookies").toEqual([]);
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length), "nothing is stored").toBe(0);
  expect(watch.problems()).toEqual([]);
  expect(watch.violations()).toEqual([]);
});

// ---- a link pasted into the box, a name of two words, the status line, the length -------------------------------------------------------------------------

test("a link to a trio page pasted into the search box, in another order of the classes, is offered with its query and its kit, and opens the page with the kit @once", async ({ page, request, watch }) => {
  const [slug] = await builtTrios(request);
  const reversed = slug.split("-").reverse().join("-");
  const payload = encodeKit({ v: 1, trio: slug, race: "OGR", level: 50, slots: [[0, 2000000001, 4], [5, 2000000002, 0]] });
  await page.goto(`/trio/${slug}/`);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  const shown = await readControls(page);
  const tiers = await optionValues(page, "#sw-tier");
  const other = tiers.find((tier) => tier !== String(shown.tier)) ?? tiers[0];
  for (const how of ["click", "enter"]) {
    await open(page, "/");
    const link = `${new URL(page.url()).origin}/Trio/${reversed.toUpperCase()}/?tier=${other}#k=${payload}`;
    await type(page, link);
    const offered = page.locator("#picker-status a");
    await expect(offered).toHaveAttribute("href", `/trio/${slug}/?tier=${other}#k=${payload}`);
    await expect(page.locator("#picker-status")).not.toContainText(/Not class/);
    if (how === "click") await offered.click();
    else await page.locator("#trio-search").press("Enter");
    await expect(page.locator("#shared-kit-h")).toHaveText("A kit shared with you", { timeout: 30_000 });
    expect(new URL(page.url()).pathname).toBe(`/trio/${slug}/`);
    expect(await page.evaluate(() => history.state), "the kit of the pasted link is in the history entry of the page").toMatchObject({ k: payload });
    expect(await page.evaluate(() => document.documentElement.dataset.kitFragment)).toBe("cleared");
    await expect.poll(async () => (await readControls(page)).tier, { message: "the query of the pasted link decides the view" }).toBe(Number(other));
  }
  expect(watch.problems()).toEqual([]);
  expect(watch.violations()).toEqual([]);
});

test("an address of another site, or of this site and not a trio page, says to open it in the address bar, and nothing is offered @once", async ({ page, request }) => {
  const [slug] = await builtTrios(request);
  await open(page, "/");
  const origin = new URL(page.url()).origin;
  for (const typed of [`https://example.org/trio/${slug}/?tier=4#k=AAAA`, `//example.org/trio/${slug}/`, `${origin}/rules/`, `${origin}/trio/${slug}/extra/`]) {
    await type(page, typed);
    await expect(page.locator("#picker-status"), typed).toHaveText("This is an address, not classes. Open it in the address bar of your browser.");
    await expect(page.locator("#picker-status a")).toHaveCount(0);
    expect(await chosen(page)).toEqual([]);
    await page.locator("#trio-search").press("Enter");
    expect(new URL(page.url()).pathname, "Enter goes nowhere").toBe("/");
  }
  await type(page, `${slug.split("-").join(" ")}`);
  await expect(page.locator("#picker-status a")).toHaveAttribute("href", `/trio/${slug}/`);
});

test("a name of two words is no mistake while it is typed, and a word after three full classes says that the first three are used @once", async ({ page, request }) => {
  const [slug] = await builtTrios(request);
  await open(page, "/");
  const classes = await chipClasses(page);
  for (const typed of ["pal mnk shadow", "pal mnk shadow k", "pal mnk shadow knigh"]) {
    await type(page, typed);
    await expect(page.locator("#picker-status"), typed).toHaveText("Pick 1 more class.");
  }
  await type(page, "pal mnk shadow x");
  await expect(page.locator("#picker-status")).toHaveText("Pick 1 more class. Not classes: shadow, x.");
  // after the three classes of a built trio, the first letters of a class that is not one of them
  const outside = classes.find((one) => !slug.toUpperCase().split("-").includes(one.code));
  for (const extra of [outside.name.slice(0, 4).toLowerCase(), outside.code.toLowerCase()]) {
    await type(page, `${slug.split("-").join(" ")} ${extra}`);
    await expect(page.locator("#picker-status a"), extra).toHaveAttribute("href", `/trio/${slug}/`);
    await expect(page.locator("#picker-status"), extra).toContainText("A trio has three classes: the first three are used.");
  }
  await type(page, `${slug.split("-").join(" ")} and`);
  await expect(page.locator("#picker-status")).not.toContainText("the first three are used");
});

test("the status line is not replaced while it says the same, so that a screen reader does not say it again @once", async ({ page }) => {
  await open(page, "/");
  await page.evaluate(() => {
    window.__statusChanges = 0;
    new MutationObserver((records) => {
      window.__statusChanges += records.length;
    }).observe(document.getElementById("picker-status"), { childList: true, characterData: true, subtree: true });
  });
  const changes = () => page.evaluate(() => window.__statusChanges);
  await page.locator("#trio-search").focus();
  await page.keyboard.type("shadow k"); // eight keys, and the status says nothing after each of them
  await expect(page.locator("#picker-status")).toHaveText("");
  expect(await changes(), "typing the first letters of a class changes nothing it says").toBe(0);
  await page.keyboard.press("Control+A");
  await page.keyboard.type("pal");
  await expect(page.locator("#picker-status")).toHaveText("Pick 2 more classes.");
  const after = await changes();
  expect(after, "a class is named: the words change").toBeGreaterThan(0);
  await page.keyboard.type("  ");
  await page.keyboard.press("Backspace");
  await page.keyboard.press("Backspace");
  expect(await changes(), "spaces put after the class and taken away leave it as it was").toBe(after);
});

test("the search box takes as many characters as the picker reads: a link to a kit of the longest size fits and a paste of thousands is cut @once", async ({ page }) => {
  await open(page, "/");
  const box = page.locator("#trio-search");
  await expect(box).toHaveAttribute("maxlength", String(MAX_QUERY_LENGTH));
  await box.focus();
  await page.keyboard.insertText("x".repeat(MAX_QUERY_LENGTH * 4));
  expect((await box.inputValue()).length).toBe(MAX_QUERY_LENGTH);
  await expect(page.locator("#picker-status")).toContainText("Not a class");
  expect((await page.locator("#picker-status").innerText()).length).toBeLessThan(200);
  // a link with the longest kit that the page reads goes in whole
  await box.fill("");
  const origin = new URL(page.url()).origin;
  const link = `${origin}/trio/pal-mnk-ber/?race=OGR&role=balanced&tier=10#k=${"A".repeat(2048)}`;
  expect(link.length).toBeLessThanOrEqual(MAX_QUERY_LENGTH);
  await box.focus();
  await page.keyboard.insertText(link);
  expect(await box.inputValue()).toBe(link);
});

// ---- the list of the trio pages, without JavaScript ----------------------------------------------------------------------------------

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("the list names every built trio as a link, the picker is not offered, and each link opens its page @once", async ({ page, request }) => {
    const trios = await builtTrios(request);
    await page.goto("/");
    await expect(page.locator("#picker")).toBeHidden();
    await expect(page.locator("#picker-status")).toBeHidden();
    await expect(page.locator("#theme-toggle")).toBeHidden();
    const list = page.locator("#live-trios");
    if ((await page.locator("#all-trios").count()) > 0) await page.locator("#all-trios > summary").click(); // (a long list is folded into an expander, which opens without a script)
    await expect(list).toBeVisible();
    const links = await list.locator("a").evaluateAll((anchors) => anchors.map((a) => a.getAttribute("href")));
    expect(links).toEqual(trios.map((slug) => `/trio/${slug}/`));
    for (const slug of trios.slice(0, 3)) {
      await page.goto("/");
      if ((await page.locator("#all-trios").count()) > 0) await page.locator("#all-trios > summary").click();
      await page.locator(`#live-trios a[href="/trio/${slug}/"]`).click();
      await expect(page).toHaveURL(new RegExp(`/trio/${slug}/$`));
      await expect(page.locator("main")).toHaveAttribute("data-page", "trio");
      await expect(page.locator("#kit-body tr")).toHaveCount(22);
    }
  });

  test("the page says in words which trios are not built yet, or that every one is built @once", async ({ page, request }) => {
    await page.goto("/");
    const trios = await builtTrios(request);
    const possible = trioCount((await chipClasses(page)).length); // (the chips are in the page whether or not a script shows them)
    const text = await page.locator("main").innerText();
    if (trios.length < possible) expect(text).toContain("Every other trio is coming soon.");
    else expect(text).not.toContain("coming soon");
  });
});

test("the list of the trio pages is the list of the optimizer, link for link, and the picker offers those and no others @once", async ({ page, request }) => {
  const trios = await builtTrios(request);
  await open(page, "/");
  const live = await page.locator("#picker").getAttribute("data-live");
  expect(live.split(" ")).toEqual(trios);
  const hrefs = await page.locator("#live-trios a").evaluateAll((anchors) => anchors.map((a) => a.getAttribute("href")));
  expect(hrefs).toEqual(trios.map((slug) => `/trio/${slug}/`));
  for (const href of hrefs.slice(0, 5)) expect((await request.get(href)).status(), href).toBe(200);
});

// ---- the first load -----------------------------------------------------------------------------------------------------------------------

test("the home page asks for the page, the stylesheet, the boot script and the page script and for nothing else: no data, no chunk, no optimizer @once", async ({ page, request }) => {
  const asked = [];
  page.on("request", (one) => asked.push(new URL(one.url()).pathname));
  await open(page, "/");
  await page.waitForLoadState("networkidle");
  await type(page, "pal mnk ber"); // using the picker asks for nothing either
  await page.waitForLoadState("networkidle");
  expect(asked.filter((path) => !path.startsWith("/assets/"))).toEqual(["/"]);
  const home = await (await request.get("/")).text();
  const assets = [...home.matchAll(/(?:href|src)="(\/assets\/[^"]+)"/g)].map((m) => m[1]).sort();
  expect(assets, "a stylesheet and two scripts").toHaveLength(3);
  // the files the page names, and besides them the pictures of the theme that its stylesheet asks for: hashed PNGs of this site
  const wanted = asked.filter((path) => path.startsWith("/assets/"));
  expect(wanted.filter((path) => !path.endsWith(".png")).sort()).toEqual(assets);
  for (const path of wanted.filter((path) => path.endsWith(".png"))) expect(path, "a picture of the theme").toMatch(/^\/assets\/[a-z0-9-]+-[A-Z0-9]{8}\.png$/);
  const [slug] = await builtTrios(request);
  const trio = await (await request.get(`/trio/${slug}/`)).text();
  expect([...trio.matchAll(/(?:href|src)="(\/assets\/[^"]+)"/g)].map((m) => m[1]).sort(), "the same three files as a trio page").toEqual(assets);
});

// ---- accessibility and layout ---------------------------------------------------------------------------------------------------------------

test("axe: the home page, with nothing chosen, with a built trio chosen, with a trio that is not built and with a word that is no class, has no serious or critical violations", async ({ page, request }, testInfo) => {
  const trios = await builtTrios(request);
  await open(page, "/");
  await axe(page, testInfo);
  const classes = await chipClasses(page);
  await type(page, trios[0].split("-").join(" "));
  await expect(page.locator("#picker-status a")).toBeVisible();
  await axe(page, testInfo);
  const unbuilt = firstUnbuilt(classes.map((one) => one.code), trios);
  if (unbuilt === null) {
    testInfo.annotations.push({ type: "skipped steps", description: "every trio is built, so the state of a trio that is coming soon is left out" });
  } else {
    await type(page, `${unbuilt.split("-").join(" ")} xyz`);
    await expect(page.locator("#picker-status")).toContainText("coming soon");
    await expect(page.locator("#picker-status")).toContainText("Not a class: xyz.");
    await axe(page, testInfo);
  }
  await type(page, "pal");
  await expect(page.locator("#picker-status")).toContainText("Pick 2 more classes.");
  await axe(page, testInfo);
});

test("axe: the home page with the list of the trios open", async ({ page, request }, testInfo) => {
  test.setTimeout(120_000); // (the list of the whole grid has hundreds of links)
  await open(page, "/");
  const folded = page.locator("#all-trios > summary");
  if ((await folded.count()) > 0) await folded.click();
  await expect(page.locator("#live-trios")).toBeVisible();
  expect((await builtTrios(request)).length).toBeGreaterThan(0);
  await axe(page, testInfo);
});

test("nothing on the home page reaches past the window, with the search box and the longest status in it", async ({ page }) => {
  await open(page, "/");
  // the three classes with the longest names (the status says them in the order of the page), and three words that are no class, each as long as one is cut to
  const classes = await chipClasses(page);
  const longest = [...classes].sort((a, b) => b.name.length - a.name.length).slice(0, 3);
  const inOrder = classes.filter((one) => longest.includes(one));
  await type(page, `${longest.map((one) => one.code.toLowerCase()).join(" ")} aaaaaaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbbbbbb cccccccccccccccccccc`);
  await expect(page.locator("#picker-status")).toContainText(inOrder.map((one) => one.name).join(" / "));
  await expect(page.locator("#picker-status")).toContainText("Not classes: aaaaaaaaaaaa, bbbbbbbbbbbb, cccccccccccc.");
  const reach = await page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const widest = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
    const sticking = [...document.body.querySelectorAll("*")]
      .filter((el) => !el.closest(".sr-only, .sprite, .skip-link") && el.getClientRects().length > 0 && el.getBoundingClientRect().right > width + 1)
      .map((el) => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}`);
    return { page: Math.max(0, widest - width), sticking: sticking.slice(0, 5) };
  });
  expect(reach).toEqual({ page: 0, sticking: [] });
});

test("the search box and the chips can be reached and used with the keyboard, each with a focus ring", async ({ page }) => {
  await open(page, "/");
  await page.locator("#trio-search").focus();
  const ring = await page.evaluate(() => {
    const style = getComputedStyle(document.activeElement);
    return style.outlineStyle === "none" ? 0 : Number.parseFloat(style.outlineWidth);
  });
  expect(ring, "the search box shows a focus ring").toBeGreaterThanOrEqual(2);
  const [first] = await chipClasses(page);
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement?.id)).toBe(`class-${first.code}`);
  await page.keyboard.press("Space");
  expect(await chosen(page)).toEqual([first.code]);
  await expect(page.locator("#trio-search")).toHaveValue(first.code.toLowerCase());
});
