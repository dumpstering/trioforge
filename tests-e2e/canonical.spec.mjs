// The 404 page and the canonical address of a trio in a real browser (Chromium), served by `wrangler pages dev` with the production headers.
//
// The page for a trio is /trio/<x>-<y>-<z>/ with the classes in the order of the site's classes, and that is the only address the site has a file for. Any other order, case or form of
// it is answered with the site's 404 page (a real 404), whose small script moves the visitor to the right page with location.replace and keeps the query and the #k= fragment, which the
// page of the trio takes from there. The tests take the trios from the optimizer's manifest, so they run unchanged on the fixture (one trio), on real results and on any number of trios.
//
// A test without @once in its title runs in four views: a 1280 px and a 360 px wide window, each with the system in light and in dark mode (see playwright.config.mjs).

import { encodeKit } from "../pipeline/trioforge/site/static/input/kitcode.js";
import { axe, expect, open, optionValues, readControls, readHeadersFile, test } from "./support.mjs";
import { builtTrios, chipCodes, firstUnbuilt, sample } from "./trios.mjs";

const permutations = (items) =>
  items.length <= 1 ? [items] : items.flatMap((item, at) => permutations([...items.slice(0, at), ...items.slice(at + 1)]).map((rest) => [item, ...rest]));

/** Four ways to write a trio in capitals and small letters. */
const STYLES = [
  (text) => text,
  (text) => text.toUpperCase(),
  (text) => text.replace(/(^|-)([a-z])/g, (_, dash, letter) => dash + letter.toUpperCase()),
  (text) => [...text].map((c, at) => (at % 2 ? c : c.toUpperCase())).join(""),
];

/** Every address a document is given at the start, in order: the 404 page first, then the page it moves the visitor to. The note is made before any script of the document runs, so nothing has touched the address yet. */
async function recordStarts(page) {
  const starts = [];
  await page.exposeFunction("__tfStart", (href) => {
    starts.push(href);
  });
  await page.addInitScript(() => {
    window.__tfStart(location.href).catch(() => {});
  });
  return starts;
}

/** Go to an address and return when the answer has begun (the page may move on by itself after that). */
function arrive(page, address) {
  return page.goto(address, { waitUntil: "commit" });
}

/** Open an address the site has no file for and that the 404 page does not move: the answer is a 404 and the page's script has run (it shows the theme button). */
async function staysOn404(page, address) {
  const response = await arrive(page, address);
  expect(response?.status(), `${address} answers 404`).toBe(404);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await expect(page.locator("main h1")).toHaveText("Page not found");
  return response;
}

// ---- every order of every trio -----------------------------------------------------------------------------------------------------

test("every order of each of at most five built trios (a seeded sample) is taken to its page, in any case, with or without the last slash @once", async ({ page, request, watch }) => {
  test.setTimeout(180_000);
  // six loads of a trio page for each trio would not end in any time limit on the whole grid, so the trios are a sample of the build's, the same on every run
  const trios = sample(await builtTrios(request));
  expect(trios.length).toBeGreaterThan(0);
  expect(trios.length).toBeLessThanOrEqual(5);
  const typedPaths = [];
  let moved = 0;
  for (const slug of trios) {
    for (const [n, order] of permutations(slug.split("-")).entries()) {
      const typed = STYLES[n % STYLES.length](order.join("-"));
      const path = `/${n % 2 ? "TRIO" : "trio"}/${typed}${n % 3 === 0 ? "" : "/"}`;
      if (path === `/trio/${slug}/`) continue; // (the right address is not moved)
      typedPaths.push(path);
      const response = await arrive(page, path);
      if (typed !== slug) expect(response?.status(), `${path} is answered with a 404 first`).toBe(404);
      await expect(page, path).toHaveURL(new RegExp(`/trio/${slug}/$`));
      await expect(page.locator("main"), path).toHaveAttribute("data-page", "trio");
      await expect(page.locator("#theme-toggle")).toBeVisible();
      moved += 1;
    }
  }
  expect(moved, "every order but one of every trio").toBeGreaterThanOrEqual(trios.length * 5);
  // nothing went wrong but the 404 that was answered first for each of the addresses that were typed
  expect(watch.problems().filter((line) => !typedPaths.some((path) => line.includes(path)))).toEqual([]);
  expect(watch.violations()).toEqual([]);
});

test("the move replaces the 404 page in the history: Back goes to the page before it @once", async ({ page, request, watch }) => {
  const [slug] = await builtTrios(request);
  await page.goto("/");
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await arrive(page, `/trio/${slug.split("-").reverse().join("-").toUpperCase()}`);
  await expect(page).toHaveURL(new RegExp(`/trio/${slug}/$`));
  await expect(page.locator("main")).toHaveAttribute("data-page", "trio");
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator("main")).toHaveAttribute("data-page", "home");
  expect(watch.violations()).toEqual([]);
});

test("a trio address in another order is answered with a real 404 and the neutral page @once", async ({ request }) => {
  const [slug] = await builtTrios(request);
  const reversed = slug.split("-").reverse().join("-");
  const file = readHeadersFile();
  for (const path of [`/trio/${reversed.toUpperCase()}/`, `/Trio/${reversed}`, `/trio/${reversed}/`]) {
    const response = await request.get(path, { maxRedirects: 0 });
    expect(response.status(), `${path} is a 404, not a soft redirect or the home page`).toBe(404);
    expect(response.headers()["content-type"]).toContain("text/html");
    const body = await response.text();
    expect(body).toContain("<title>Page not found · TrioForge</title>");
    expect(body).toContain('data-page="notfound"');
    expect(body).not.toContain('data-page="home"');
    expect(response.headers()["content-security-policy"]).toBe(file.get("content-security-policy"));
    expect(response.headers()["x-content-type-options"]).toBe("nosniff");
  }
});

test("the list in the 404 page is the list of the trios of the build, and the trios of a sample of it are pages @once", async ({ request }) => {
  const trios = await builtTrios(request);
  const body = await (await request.get("/no/such/page/")).text();
  expect(/data-trios="([^"]*)"/.exec(body)?.[1]?.split(" ")).toEqual(trios);
  for (const slug of sample(trios)) expect((await request.get(`/trio/${slug}/`)).status(), slug).toBe(200);
});

// ---- the query and the kit fragment -------------------------------------------------------------------------------------------------

test("the query and the kit fragment come to the page of the trio untouched, and the page takes the kit @once", async ({ page, request, watch }) => {
  const [slug] = await builtTrios(request);
  const reversed = slug.split("-").reverse().join("-").toUpperCase();
  const payload = encodeKit({ v: 1, trio: slug, race: "OGR", level: 50, slots: [[0, 2000000001, 4], [5, 2000000002, 0]] });
  const starts = await recordStarts(page);
  await page.goto(`/trio/${slug}/`);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  const shown = await readControls(page);
  const tiers = await optionValues(page, "#sw-tier");
  const other = tiers.find((tier) => tier !== String(shown.tier)) ?? tiers[0];
  starts.length = 0;
  const typed = `/Trio/${reversed}?tier=${other}&junk=%2F%2Fevil.example#k=${payload}`;
  await arrive(page, typed);
  await expect(page.locator("#shared-kit-h")).toHaveText("A kit shared with you", { timeout: 30_000 });
  expect(starts, "the 404 page, then the page of the trio").toHaveLength(2);
  const [first, second] = starts.map((href) => new URL(href));
  expect(first.pathname + first.search + first.hash).toBe(typed);
  // the page of the trio is given the query and the fragment byte for byte, and its address is the right one, on the same site
  expect(second.href).toBe(`${first.origin}/trio/${slug}/?tier=${other}&junk=%2F%2Fevil.example#k=${payload}`);
  // and the page of the trio does what it does with a kit link: the kit goes into the history entry and out of the address, and the query decides the view
  expect(await page.evaluate(() => history.state)).toMatchObject({ k: payload });
  expect(await page.evaluate(() => document.documentElement.dataset.kitFragment)).toBe("cleared");
  expect(new URL(page.url()).hash).toBe("");
  await expect.poll(async () => (await readControls(page)).tier, { message: "the query decides the view" }).toBe(Number(other));
  expect(watch.problems().filter((line) => !line.includes("/Trio/"))).toEqual([]);
  expect(watch.violations()).toEqual([]);
});

test("the query alone, the fragment alone and an odd query are kept as well @once", async ({ page, request }) => {
  const [slug] = await builtTrios(request);
  const reversed = slug.split("-").reverse().join("-");
  const starts = await recordStarts(page);
  for (const tail of ["", "?x=1", "#k=AAAA", "?a=b&c=d#top", "?%E2%9C%93=%F0%9F%98%80"]) {
    starts.length = 0;
    await arrive(page, `/trio/${reversed.toUpperCase()}/${tail}`);
    await expect(page.locator("main")).toHaveAttribute("data-page", "trio");
    expect(starts).toHaveLength(2);
    expect(starts[1].slice(starts[1].indexOf("/trio/"))).toBe(`/trio/${slug}/${tail}`);
  }
});

// ---- what is not moved ---------------------------------------------------------------------------------------------------------------

test("an address that is not a trio of the build is not moved, whatever it holds, and the browser never leaves the site @once", async ({ page, request, watch }) => {
  test.setTimeout(120_000);
  const trios = await builtTrios(request);
  const [slug] = trios;
  const unbuilt = firstUnbuilt(await chipCodes(request), trios); // (null when every trio of the grid is built: then none is left to be a trio that the build does not have)
  if (unbuilt === null) test.info().annotations.push({ type: "skipped steps", description: "every trio is built, so the two addresses of a trio that is not built are left out" });
  const origin = new URL((await request.get("/")).url()).origin;
  const hostile = [
    ...(unbuilt === null ? [] : [`/trio/${unbuilt}/`, `/trio/${unbuilt.split("-").reverse().join("-").toUpperCase()}`]),
    `//evil.example/trio/${slug}/`,
    `//evil.example//trio/${slug}/`,
    `/%5Cevil.example/trio/${slug}/`,
    `/trio%2F${slug}/`,
    `/trio/${slug}%2F/`,
    `/trio/${slug}%5C/`,
    `/trio/%2570${slug.slice(1)}/`,
    `/trio/${slug}%252F/`,
    `/trio/${slug}/no-such-page`,
    "/trio/pal-mn%E2%84%AA-ber/",
    "/trio/%EF%BD%90al-mnk-ber/",
    `/trio/${slug.replace(/-/g, "_")}/`,
    `/trio/${slug.replace(/-/g, "%20")}/`,
    "/trio/https:/evil.example/",
    "/trio/javascript:alert(1)/",
    "/trio/<script>/",
  ];
  const reached = [];
  for (const path of hostile) {
    const response = await arrive(page, `${origin}${path}`);
    // (the server reads some of these itself: to it an encoded slash is a slash, so the address of a trio page written with one is that page and is answered 200, and never reaches the 404 page)
    if (response?.status() !== 404) {
      expect(response?.status(), `${path} is answered by the server itself`).toBe(200);
      await expect(page.locator("main")).toHaveAttribute("data-page", "trio");
      continue;
    }
    reached.push(path);
    await expect(page.locator("#theme-toggle")).toBeVisible();
    await expect(page.locator("main h1"), path).toHaveText("Page not found");
    expect(new URL(page.url()).origin, `${path} stays on the site`).toBe(origin);
    expect(new URL(page.url()).pathname, `${path} stays where it is`).toBe(new URL(`${origin}${path}`).pathname);
  }
  expect(reached.length, "most of them are answered with the 404 page").toBeGreaterThanOrEqual(hostile.length - 4);
  expect(watch.events.filter((event) => event.kind === "foreign"), "no request went to another address").toEqual([]);
  expect(watch.violations()).toEqual([]);
});

test("a 404 on the right address is not moved to itself: the page shows and does not load again @once", async ({ page, request }) => {
  const [slug] = await builtTrios(request);
  const body = await (await request.get("/no/such/page/")).text();
  await page.route(`**/trio/${slug}/`, (route) => route.fulfill({ status: 404, contentType: "text/html; charset=utf-8", body }));
  const starts = await recordStarts(page);
  await page.goto(`/trio/${slug}/`);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await expect(page.locator("main h1")).toHaveText("Page not found");
  await page.waitForTimeout(600); // a loop would have loaded the page again by now
  expect(starts).toHaveLength(1);
});

// ---- no beacon -----------------------------------------------------------------------------------------------------------------------------

test("the 404 page has no analytics beacon: no script of another site, no beacon call, no request but its own files @once", async ({ page, request, watch }) => {
  const file = readHeadersFile();
  await page.addInitScript(() => {
    window.__beacons = 0;
    const original = navigator.sendBeacon ? navigator.sendBeacon.bind(navigator) : null;
    navigator.sendBeacon = (...args) => {
      window.__beacons += 1;
      return original ? original(...args) : false;
    };
  });
  const asked = [];
  page.on("request", (one) => asked.push(new URL(one.url())));
  await staysOn404(page, "/item/no-such-item/");
  await page.waitForLoadState("networkidle");
  expect(await page.evaluate(() => window.__beacons)).toBe(0);
  const scripts = await page.evaluate(() => [...document.scripts].map((script) => new URL(script.src).pathname));
  expect(scripts).toHaveLength(2);
  expect(scripts[0]).toMatch(/^\/assets\/boot-[A-Z0-9]{8}\.js$/);
  expect(scripts[1]).toMatch(/^\/assets\/notfound-[A-Z0-9]{8}\.js$/);
  expect(await page.evaluate(() => document.documentElement.outerHTML)).not.toMatch(/cloudflareinsights|data-cf-beacon|beacon\.min/i);
  const network = asked.filter((url) => url.protocol.startsWith("http"));
  expect(new Set(network.map((url) => url.origin)).size, "every request is to the site itself").toBe(1);
  const assets = network.filter((url) => url.pathname.startsWith("/assets/"));
  expect(assets.filter((url) => !url.pathname.endsWith(".png")).map((url) => url.pathname.split("-")[0]).sort()).toEqual(["/assets/boot", "/assets/notfound", "/assets/site"]);
  // (the stylesheet's own pictures: PNGs beside it, hashed, of this site; nothing else)
  for (const url of assets.filter((url) => url.pathname.endsWith(".png"))) expect(url.pathname, "a picture of the theme").toMatch(/^\/assets\/[a-z0-9-]+-[A-Z0-9]{8}\.png$/);
  expect(network.filter((url) => url.pathname.endsWith(".json")), "it asks for no data").toEqual([]);
  // the page that answers has the policy of every page, which names no analytics host
  const response = await request.get("/item/no-such-item/");
  expect(response.headers()["content-security-policy"]).toBe(file.get("content-security-policy"));
  expect(response.headers()["content-security-policy"]).not.toMatch(/cloudflare/i);
  expect(watch.events.filter((event) => event.kind === "foreign")).toEqual([]);
  expect(watch.violations()).toEqual([]);
});

test("the 404 page does not take a kit link out of the address: the fragment is still there while the page is @once", async ({ page }) => {
  const response = await arrive(page, "/no/such/page/#k=AAAA");
  expect(response?.status()).toBe(404);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  expect(new URL(page.url()).hash).toBe("#k=AAAA");
  expect(await page.evaluate(() => history.state)).toBeNull();
  expect(await page.evaluate(() => "kitFragment" in document.documentElement.dataset)).toBe(false);
});

test("the 404 page has a policy of its own that forbids every connection, and the browser enforces it @once", async ({ page, watch }) => {
  const reached = [];
  await page.route("**/no-beacon-here", (route) => {
    reached.push(route.request().url());
    return route.abort();
  });
  await staysOn404(page, "/no/such/page/");
  await expect(page.locator('head meta[http-equiv="Content-Security-Policy"]')).toHaveAttribute("content", "script-src 'self'; connect-src 'none'");
  const fetched = await page.evaluate(async () => {
    try {
      await fetch("/engine-manifest.json");
      return "allowed";
    } catch {
      return "refused";
    }
  });
  expect(fetched, "not a request to the site's own address either").toBe("refused");
  await page.evaluate(() => navigator.sendBeacon("/no-beacon-here", "x")); // (it says that the data is queued; the browser then refuses to send it)
  await expect.poll(() => watch.violations().filter((v) => v.directive === "connect-src" && v.text.includes("no-beacon-here")).length).toBe(1);
  await expect.poll(() => watch.violations().filter((v) => v.directive === "connect-src" && v.text.includes("engine-manifest")).length).toBe(1);
  expect(reached, "nothing was sent").toEqual([]);
  // the control: the home page has no such policy, and its script may ask the server for a file
  await open(page, "/");
  expect(await page.evaluate(async () => (await fetch("/engine-manifest.json")).status)).toBe(200);
});

test("a beacon that the host puts into the 404 page cannot load, even where the header of the page would let it @once", async ({ page, watch }) => {
  // a build with analytics would name the host of the script and the host of its data in the header of every page, and the host's own toggle puts the tag at the end of a page: both are done here
  const tag = `<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{"token": "invented"}'></script>`;
  await page.route(
    (url) => url.pathname === "/" || url.pathname === "/no-page-for-the-beacon/",
    async (route) => {
      const response = await route.fetch();
      const headers = { ...response.headers() };
      delete headers["content-length"];
      delete headers["content-encoding"];
      headers["content-security-policy"] = headers["content-security-policy"]
        .replace("script-src 'self'", "script-src 'self' https://static.cloudflareinsights.com")
        .replace("connect-src 'self'", "connect-src 'self' https://cloudflareinsights.com");
      await route.fulfill({ response, headers, body: (await response.text()).replace("</body>", `${tag}</body>`) });
    },
  );
  await page.route("https://static.cloudflareinsights.com/**", (route) => route.fulfill({ status: 200, contentType: "text/javascript", body: "window.__beaconRan = true;" }));
  // the control: the home page has no policy of its own, so the beacon runs there, and the header and the tag do what they were made to do
  await open(page, "/");
  await expect.poll(() => page.evaluate(() => window.__beaconRan === true)).toBe(true);
  // and the 404 page does not run it
  const response = await page.goto("/no-page-for-the-beacon/");
  expect(response?.status()).toBe(404);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await page.waitForLoadState("load");
  expect(await page.evaluate(() => window.__beaconRan === true), "the beacon did not run").toBe(false);
  const refused = watch.violations().filter((v) => v.text.includes("cloudflareinsights"));
  expect(refused.length, "the browser refused it").toBeGreaterThan(0);
  expect(refused.every((v) => v.directive.startsWith("script-src"))).toBe(true);
});

// ---- a visitor who is lost ----------------------------------------------------------------------------------------------------------------

test("an item that has no page offers the search, and the search is ready for the visitor on the home page @once", async ({ page, watch }) => {
  await staysOn404(page, "/item/no-such-item/");
  const hint = page.locator("#notfound-hint");
  await expect(hint).toBeVisible();
  await expect(hint).toContainText("There is no page for this item.");
  await expect(page.locator("main")).not.toContainText("no-such-item"); // what was typed is not put back into the page
  await hint.getByRole("link", { name: "Search for a trio" }).click();
  await expect(page).toHaveURL(/\/#search$/);
  await expect(page.locator("main")).toHaveAttribute("data-page", "home");
  await expect(page.locator("#trio-search")).toBeFocused();
  expect(watch.problems().filter((line) => !line.includes("no-such-item"))).toEqual([]);
});

test("a trio address that leads nowhere offers the same search @once", async ({ page }) => {
  await staysOn404(page, "/trio/no-such-trio/");
  await expect(page.locator("#notfound-hint")).toBeVisible();
  await expect(page.locator("#notfound-hint")).toContainText("There is no page for this trio");
  await expect(page.locator("#notfound-hint a")).toHaveAttribute("href", "/#search");
});

test("an address that is neither a trio nor an item gets the plain page and no hint @once", async ({ page }) => {
  await staysOn404(page, "/no/such/page/");
  await expect(page.locator("#notfound-hint")).toBeHidden();
  await page.locator("main").getByRole("link", { name: "Go to the home page" }).click();
  await expect(page.locator("main")).toHaveAttribute("data-page", "home");
});

// ---- accessibility and layout -----------------------------------------------------------------------------------------------------------------

for (const [what, path] of [
  ["the plain page", "/no/such/page/"],
  ["the page of an item that has none", "/item/no-such-item/"],
  ["the page of a trio that leads nowhere", "/trio/no-such-trio/"],
]) {
  test(`axe: the 404 page, ${what}, has no serious or critical violations`, async ({ page }, testInfo) => {
    await staysOn404(page, path);
    await axe(page, testInfo);
  });
}

test("the 404 page with its hint has no horizontal scroll", async ({ page }) => {
  await staysOn404(page, "/item/no-such-item/");
  await expect(page.locator("#notfound-hint")).toBeVisible();
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

test("the theme button works on the 404 page and the choice is kept for the page the visitor goes on to @once", async ({ page, request }) => {
  await staysOn404(page, "/item/no-such-item/");
  const button = page.locator("#theme-toggle");
  await button.click();
  await expect(button).toHaveText("Theme: light");
  await button.click();
  await expect(button).toHaveText("Theme: dark");
  const [slug] = await builtTrios(request);
  await page.goto(`/trio/${slug}/`);
  await expect(page.locator("#theme-toggle")).toHaveText("Theme: dark");
  expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe("dark");
});
