// A build with page counts (Cloudflare Web Analytics) in a real browser, served by the third preview of the configuration (an invented token; the counter's own script is never fetched: every test
// answers for it, with a stand-in that does what a counter does with an address and sends it where the header lets it send).
//
// The design (Part M): no page carries a script for the counter. The build gives a page the token as data (a <meta name="trioforge-counter">), and the page script adds ONE script element for the counter,
// last, through the site's Trusted Types policy, only to a page that was opened with no kit link (counter.js). A page opened from a kit link is not counted at all: the navigation entry of the
// Performance API keeps the address the document was loaded with, kit included, whatever the page script does to the address (a fact that no script of the page can change), so the counter's script is
// not loaded there, and a reload of the cleaned address is a kit page still (the kit lives on in the history entry). The stand-in below reads every place that holds an address, when it runs and at
// every popstate and hashchange, so a test fails the day one of them holds a kit.
//
// What these tests hold, and what they cannot: the counter's script is added by the page script and by nothing else, and never on a page that holds a kit; no request goes to any host but the site and
// the two hosts of the counter; the 404 page loads none of it; no cookie and no stored value comes of the site; the headers of this build are what the file it was built to says, and so are those of
// the plain build. What they cannot hold is what the real script of Cloudflare reads or sends: it is never fetched here.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ANALYTICS_ORIGIN, ANALYTICS_TOKEN, ORIGIN } from "../playwright.config.mjs";
import { checkHeaders, expectedHeaders } from "../scripts/smoke_live.mjs";
import { ROOT, TRIO, axe, expect, open, test } from "./support.mjs";

test.use({ baseURL: ANALYTICS_ORIGIN });

const SCRIPT_HOST = "https://static.cloudflareinsights.com";
const DATA_HOST = "https://cloudflareinsights.com";
const PAYLOAD = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyAhIiMkJSYnKCkqKywtLi8wMTIzNDU2Nzg5Ojs8PT4_QEFC"; // (made up: the address test needs a payload, not a decodable kit)
const META = `<meta name="trioforge-counter" content="${ANALYTICS_TOKEN}">`;
const KIT_LINK = `${TRIO}#k=${PAYLOAD}`;

/** A counter that reads every place that holds an address, when it runs, at every popstate, hashchange and pagehide, and at the Navigation API's navigate and currententrychange (which a browser fires before popstate), and sends what it read to the data host as a counter does. */
const STAND_IN = `(() => {
  const own = document.currentScript;
  const read = (event, destination) => ({
    event,
    href: location.href,
    url: document.URL,
    base: document.baseURI,
    referrer: document.referrer,
    navigation: performance.getEntriesByType("navigation").map((entry) => entry.name),
    entries: typeof navigation === "object" && navigation !== null ? navigation.entries().map((entry) => entry.url) : [],
    state: JSON.stringify(history.state),
    cleared: document.documentElement.dataset.kitFragment ?? null,
    token: own ? own.getAttribute("data-cf-beacon") : null,
    asyncAsAdded: own ? own.async : null,
    hasDefer: own ? own.hasAttribute("defer") : null,
    scripts: [...document.scripts].map((script) => script.src || "(inline)"),
    destination,
  });
  const send = (event, destination = null) => navigator.sendBeacon("${DATA_HOST}/cdn-cgi/rum", JSON.stringify(read(event, destination)));
  send("load");
  for (const type of ["popstate", "hashchange", "pagehide"]) window.addEventListener(type, () => send(type));
  if (typeof navigation === "object" && navigation !== null) {
    for (const type of ["navigate", "currententrychange"]) navigation.addEventListener(type, (event) => send(type, event.destination ? event.destination.url : null));
  }
})();`;

/** Answer for the two hosts of the counter: the script is the stand-in, the data host takes what is sent and keeps it. Nothing leaves the machine. */
async function answerForTheCounter(page) {
  const sent = [];
  const scriptRequests = [];
  await page.route(`${SCRIPT_HOST}/**`, (route) => {
    scriptRequests.push({ url: route.request().url(), referer: route.request().headers().referer ?? null });
    return route.fulfill({ status: 200, contentType: "text/javascript", body: STAND_IN });
  });
  await page.route(`${DATA_HOST}/**`, (route) => {
    const body = route.request().postData() ?? "";
    let read = null;
    try {
      read = JSON.parse(body);
    } catch {
      read = null;
    }
    sent.push({ url: route.request().url(), body, read, referer: route.request().headers().referer ?? null });
    return route.fulfill({ status: 204, body: "" });
  });
  return { sent, scriptRequests, any: () => sent.length + scriptRequests.length };
}

const everyAddress = (read) => [read.href, read.url, read.base, read.referrer, ...read.navigation, ...read.entries.filter((url) => url !== null), ...(read.destination ? [read.destination] : [])];
const NO_KIT = new RegExp(`${PAYLOAD.slice(0, 12)}|#k\\b|[?&#]k=`);

test("a page opened with no kit link is counted: one script added by the page script, the token and the history tracking switched off, a clean address @once", async ({ page, watch }) => {
  const counter = await answerForTheCounter(page);
  await open(page, TRIO);
  await expect.poll(() => counter.sent.length).toBe(1);
  expect(counter.scriptRequests).toHaveLength(1);
  const [{ read }] = counter.sent;
  expect(read.event).toBe("load");
  expect(read.href).toBe(`${ANALYTICS_ORIGIN}${TRIO}`);
  expect(everyAddress(read).filter((address) => address !== "" && !address.startsWith(ANALYTICS_ORIGIN))).toEqual([]);
  expect(read.navigation).toEqual([`${ANALYTICS_ORIGIN}${TRIO}`]);
  expect(read.cleared, "no kit fragment was found: the attribute is absent").toBeNull();
  expect(JSON.parse(read.token)).toEqual({ token: ANALYTICS_TOKEN, spa: false });
  expect(read.hasDefer, "defer does nothing on a script that code adds: it is not said").toBe(false);
  expect(read.asyncAsAdded, "a script added by code is async").toBe(true);
  expect(read.scripts.filter((script) => !script.startsWith(ANALYTICS_ORIGIN))).toEqual([`${SCRIPT_HOST}/beacon.min.js`]);
  // exactly one script element for it in the page, added by the page script (the HTML the site sent has none: the next test)
  await expect(page.locator("script[data-cf-beacon]")).toHaveCount(1);
  for (const one of [...counter.sent, ...counter.scriptRequests]) expect(one.referer, "no referrer is sent to a host of the counter").toBeNull();
  expect(counter.sent[0].url).toBe(`${DATA_HOST}/cdn-cgi/rum`);
  const foreign = watch.events.filter((event) => event.kind === "foreign").map((event) => event.text);
  expect(foreign.sort()).toEqual([`GET ${SCRIPT_HOST}/beacon.min.js`, `POST ${DATA_HOST}/cdn-cgi/rum`].sort());
  expect(watch.problems(["foreign"]), "the page, its policy (Trusted Types included: the script was made through the one policy) and the counter's two hosts agree").toEqual([]);
  expect(watch.violations()).toEqual([]);
});

test("a page opened from a kit link is never counted: no request to either host, not after the fragment is cleared, not after a reload of the cleaned address @once", async ({ page, watch }) => {
  const counter = await answerForTheCounter(page);
  await open(page, KIT_LINK);
  await page.waitForLoadState("networkidle");
  expect(await page.evaluate(() => document.documentElement.dataset.kitFragment)).toBe("cleared");
  expect(await page.evaluate(() => location.hash)).toBe("");
  expect(await page.evaluate(() => history.state?.k)).toBe(PAYLOAD.slice(0, 2048)); // (the kit is in the history entry, where the page code finds it: not in the address)
  // (the navigation entry of the Performance API still holds the address the document was loaded with, kit included, and no script of the page can change that: that is why this page is not counted at all)
  await expect(page.locator("script[data-cf-beacon]")).toHaveCount(0);
  expect(counter.any()).toBe(0);
  // a reload of the cleaned address: no fragment is in it, and the kit lives on in the history entry, so the page is a kit page still, and is not counted
  await page.reload();
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(await page.evaluate(() => history.state?.k)).toBe(PAYLOAD.slice(0, 2048));
  expect(await page.evaluate(() => document.documentElement.dataset.kitFragment ?? null), "no fragment was in the address this time").toBeNull();
  await expect(page.locator("script[data-cf-beacon]")).toHaveCount(0);
  expect(counter.any(), "no request to the script host or to the data host, at any time").toBe(0);
  expect(watch.events.filter((event) => event.kind === "foreign")).toEqual([]);
  // and the rule is about the kit, not the page: the same page, opened by an address with no kit and no kit in its history entry, is counted
  await page.goto(`${ANALYTICS_ORIGIN}/rules/`);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await page.goto(`${ANALYTICS_ORIGIN}${TRIO}`);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await expect.poll(() => counter.scriptRequests.length).toBeGreaterThan(0);
  expect(counter.sent.every((one) => !NO_KIT.test(JSON.stringify(everyAddress(one.read))))).toBe(true);
});

test("a page opened with a malformed switch and a foreign parameter or a kit in its query is never counted, though the page code rewrites the address before the counter is added; an ordinary switch link is @once", async ({ page }) => {
  for (const [what, query, rewritten] of [
    ["a campaign parameter", "?race=zzz&utm_source=newsletter", "utm_source"],
    ["a kit spelled as a query parameter", `?race=zzz&k=${PAYLOAD.slice(0, 40)}`, "k="],
  ]) {
    const counter = await answerForTheCounter(page);
    await open(page, `${TRIO}${query}`);
    await page.waitForLoadState("networkidle");
    expect(await page.evaluate(() => location.search), `${what}: the page code rewrote the address, which now looks clean`).not.toContain(rewritten);
    expect(await page.evaluate(() => performance.getEntriesByType("navigation")[0].name), "the navigation entry still holds the address it was loaded with").toContain(rewritten);
    await expect(page.locator("script[data-cf-beacon]"), what).toHaveCount(0);
    expect(counter.any(), `${what}: no request to either host`).toBe(0);
    await page.unrouteAll({ behavior: "ignoreErrors" });
  }
  const counter = await answerForTheCounter(page);
  await open(page, `${TRIO}?race=OGR&role=tank&tier=4&buffs=own`);
  await expect.poll(() => counter.scriptRequests.length, "an ordinary switch link is counted").toBe(1);
  await expect(page.locator("script[data-cf-beacon]")).toHaveCount(1);
});

test("a page whose kit fragment could not be cleared is never counted: replaceState refused ('kept') @once", async ({ page }) => {
  const counter = await answerForTheCounter(page);
  await page.addInitScript(() => {
    history.replaceState = () => {
      throw new Error("refused");
    };
  });
  await open(page, KIT_LINK);
  await page.waitForLoadState("networkidle");
  expect(await page.evaluate(() => document.documentElement.dataset.kitFragment)).toBe("kept");
  expect(await page.evaluate(() => location.hash)).toBe(`#k=${PAYLOAD}`); // (the fragment is in the address: the browser would not rewrite it)
  await expect(page.locator("script[data-cf-beacon]")).toHaveCount(0);
  expect(counter.any(), "nothing was asked of either host, with the kit in the address").toBe(0);
});

test("a page whose own script does not run is never counted, kit link or not: there is no tag in the HTML to run without it @once", async ({ page }) => {
  const counter = await answerForTheCounter(page);
  await page.route("**/assets/app-*.js", (route) => route.abort());
  for (const address of [KIT_LINK, TRIO]) {
    await page.goto(`${ANALYTICS_ORIGIN}${address}`, { waitUntil: "load" });
    await page.waitForLoadState("networkidle");
    expect(await page.locator("#theme-toggle").isVisible(), `${address}: the page script did not run`).toBe(false);
    expect(await page.evaluate(() => location.hash), "the fragment is in the address, and nothing came to read it").toBe(address === KIT_LINK ? `#k=${PAYLOAD}` : "");
    await expect(page.locator("script[data-cf-beacon]")).toHaveCount(0);
  }
  expect(counter.any()).toBe(0);
});

/** The sequence of the review of Part M (finding 3): a kit page whose script did not run, a link to a clean page of the same tab. `policy` is the Referrer-Policy the kit page is served with. */
async function kitPageThenACleanPage(browserPage, counter, policy) {
  await browserPage.route("**/assets/app-*.js", (route) => route.abort());
  if (policy !== null) {
    await browserPage.route(`${ANALYTICS_ORIGIN}${TRIO}*`, async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, headers: { ...response.headers(), "referrer-policy": policy } });
    });
  }
  await browserPage.goto(`${ANALYTICS_ORIGIN}${KIT_LINK}`, { waitUntil: "load" });
  expect(await browserPage.evaluate(() => location.hash), "the kit is in the address: nothing took it out").toBe(`#k=${PAYLOAD}`);
  await browserPage.unroute("**/assets/app-*.js");
  await browserPage.click('header nav a[href="/about/"]'); // (an ordinary link: the page script did not run, so nothing took it over)
  await browserPage.waitForURL(`${ANALYTICS_ORIGIN}/about/`);
  await expect(browserPage.locator("#theme-toggle")).toBeVisible(); // (the page script ran on the clean page: it could have counted it)
  await browserPage.waitForLoadState("networkidle");
  expect(await browserPage.evaluate(() => performance.getEntriesByType("navigation")[0].name), "the page itself is clean").toBe(`${ANALYTICS_ORIGIN}/about/`);
  return counter;
}

test("a kit page whose script did not run, then a link to a clean page: under the site's own Referrer-Policy the earlier entry's address is hidden from the clean page, which is counted, and no script sees a kit @once", async ({ page }) => {
  // (the Navigation API lists the entries of the tab, and gives the address of an entry of another document as null when that entry's page was served with Referrer-Policy no-referrer or origin: the site
  // sends no-referrer, which the headers check of every build and of the weekly smoke check holds. So the kit of the earlier page is not within the reach of a script of this page, the stand-in's own read
  // of the entries shows it, and the page is counted. Where the policy is not that, the next test.)
  const counter = await answerForTheCounter(page);
  await kitPageThenACleanPage(page, counter, null);
  expect(await page.evaluate(() => navigation.entries().map((entry) => entry.url)), "the entry of the kit page is there and has no address for this page").toEqual([null, `${ANALYTICS_ORIGIN}/about/`]);
  await expect.poll(() => counter.sent.length).toBe(1);
  const [{ read }] = counter.sent;
  expect(read.entries.filter((url) => url !== null && NO_KIT.test(url)), "no entry address that holds a kit is seen by the counter").toEqual([]);
  expect(everyAddress(read).filter((address) => NO_KIT.test(address))).toEqual([]);
});

test("a kit page whose script did not run, served WITHOUT that policy, then a link to a clean page: the earlier entry's address is within reach, so the clean page is not counted @once", async ({ page }) => {
  const counter = await answerForTheCounter(page);
  await kitPageThenACleanPage(page, counter, "unsafe-url");
  expect(await page.evaluate(() => navigation.entries().map((entry) => entry.url)), "the address of the kit page is visible now").toContain(`${ANALYTICS_ORIGIN}${KIT_LINK}`);
  await expect(page.locator("script[data-cf-beacon]")).toHaveCount(0);
  expect(counter.any(), "no request to either host").toBe(0);
});

/** The reads of a stand-in that first.js's listeners come before (the load of the script, popstate, hashchange): what first.js can make clean. The others come before first.js can act, or as the page is left. */
const AFTER_THE_TAKE = ["load", "popstate", "hashchange"];

test("a kit link pasted into an open counted page: at load, popstate and hashchange the counter sees no address that holds the kit; at the events that come earlier or later it is recorded, and cannot be prevented @once", async ({ page }, testInfo) => {
  // WHAT THIS CAN SHOW: first.js listens for popstate and hashchange before the stand-in does (the stand-in is added afterwards, as the real script would be), takes the kit out of the address at the first
  // of them, and a later listener finds the address clean: that is asserted for the reads at load, popstate and hashchange. WHAT IT CANNOT SHOW: the Navigation API's `navigate` and
  // `currententrychange` fire before popstate for a fragment navigation, `pagehide` fires as the page is left, and a running script cannot be unloaded: the stand-in reads at these too, and what it read is
  // RECORDED (an annotation of the test), not asserted clean, since nothing in the page script can make it so. The About page says that a kit link opened in a tab that is already counted can be seen by the
  // script that is running there. The history entry holds the kit after the take (a reload finds it there): see the lines below.
  const counter = await answerForTheCounter(page);
  await open(page, TRIO);
  await expect.poll(() => counter.sent.length).toBe(1);
  await page.evaluate((payload) => {
    location.hash = `#k=${payload}`;
  }, PAYLOAD);
  // the page takes the kit out of the address (at popstate, before any script that listens after it) and loads itself again to show it
  await expect.poll(() => page.evaluate(() => performance.getEntriesByType("navigation")[0].type).catch(() => null)).toBe("reload"); // (a read that falls in the middle of the navigation is a null)
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await page.waitForLoadState("networkidle");
  const events = counter.sent.filter((one) => one.read.event !== "load");
  expect(events.length, "the stand-in listened to the history, and was told of the paste").toBeGreaterThan(0);
  for (const one of counter.sent.filter((sent) => AFTER_THE_TAKE.includes(sent.read.event))) {
    expect(everyAddress(one.read).filter((address) => NO_KIT.test(address)), `${one.read.event}: no address that holds the kit`).toEqual([]);
    expect(one.read.href).toBe(`${ANALYTICS_ORIGIN}${TRIO}`);
  }
  for (const one of counter.sent.filter((sent) => !AFTER_THE_TAKE.includes(sent.read.event))) {
    const held = everyAddress(one.read).filter((address) => NO_KIT.test(address)).length;
    testInfo.annotations.push({ type: `read at ${one.read.event}`, description: held ? `${held} address(es) of the page held the kit (before first.js could clear it, or as the page was left)` : "no address held the kit" });
  }
  // (the history entry holds the kit after the take: it has to, a reload finds it there; a script of the page can read it, which the About page says in its words about a script that runs in the page)
  expect(await page.evaluate(() => history.state?.k)).toBe(PAYLOAD.slice(0, 2048));
  await expect(page.locator("script[data-cf-beacon]"), "the page that shows the kit has no counter").toHaveCount(0);
  expect(counter.scriptRequests, "the script was asked for once, by the page before the paste").toHaveLength(1);
});

test("a kit link pasted into an open counted page whose replaceState is refused ('kept'): the kit stays in the address while the counter runs, until the page loads again; the page that comes is not counted @once", async ({ page }, testInfo) => {
  // WHAT THIS CAN SHOW: that the stand-in does read the kit in the address in this case (first.js could not take it out), which is the limit stated in DECISIONS (Part P) and in the About page, so that a change
  // of the browser or of first.js shows up here; that the page still loads itself again; and that the page that comes is not counted and the script is not asked for again. WHAT IT CANNOT SHOW: what a real
  // counter would do with what it reads at popstate, hashchange or pagehide (nothing of Cloudflare's script is run here), and it cannot be prevented: a running script cannot be unloaded.
  const counter = await answerForTheCounter(page);
  await open(page, TRIO);
  await expect.poll(() => counter.sent.length).toBe(1);
  await page.evaluate(() => {
    history.replaceState = () => {
      throw new Error("refused");
    };
  });
  await page.evaluate((payload) => {
    location.hash = `#k=${payload}`;
  }, PAYLOAD);
  await expect.poll(() => page.evaluate(() => performance.getEntriesByType("navigation")[0].type).catch(() => null)).toBe("reload");
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await page.waitForLoadState("networkidle");
  const taken = counter.sent.filter((one) => ["popstate", "hashchange", "pagehide"].includes(one.read.event));
  expect(taken.length, "the stand-in was told of the paste").toBeGreaterThan(0);
  const held = taken.filter((one) => NO_KIT.test(one.read.href));
  testInfo.annotations.push({ type: "limit", description: `${held.length} of ${taken.length} reads at popstate, hashchange and pagehide had the kit in the address (it could not be cleared)` });
  expect(held.length, "the kit is in the address while the counter runs: the stated limit").toBeGreaterThan(0);
  await expect(page.locator("script[data-cf-beacon]"), "the page that comes is not counted").toHaveCount(0);
  expect(counter.scriptRequests, "the script was asked for once, by the page before the paste").toHaveLength(1);
});

test("the counter is added once: another fragment, a restored page and a repaint add nothing @once", async ({ page }) => {
  const counter = await answerForTheCounter(page);
  await open(page, TRIO);
  await expect.poll(() => counter.sent.length).toBe(1);
  await page.evaluate(() => {
    location.hash = "#robust";
    window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    window.dispatchEvent(new Event("resize"));
  });
  await page.waitForLoadState("networkidle");
  await expect(page.locator("script[data-cf-beacon]")).toHaveCount(1);
  expect(counter.scriptRequests).toHaveLength(1);
});

test("the 404 page has no data for the counter and loads none of it, though the header would let it @once", async ({ page, request }) => {
  const counter = await answerForTheCounter(page);
  const notFound = await page.goto("/no-page-here/");
  expect(notFound?.status()).toBe(404);
  await expect(page.locator("#theme-toggle")).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(counter.any(), "the 404 page asked for nothing of the counter").toBe(0);
  expect(await page.evaluate(() => document.documentElement.outerHTML)).not.toMatch(/cloudflareinsights|data-cf-beacon|beacon\.min|trioforge-counter/i);
  // the header of that answer is the policy of every page of this build, which names the two hosts; the page gives its own policy as well, which adds to it
  const response = await request.get("/no-page-here/");
  expect(response.status()).toBe(404);
  expect(response.headers()["content-security-policy"]).toContain(SCRIPT_HOST);
  await expect(page.locator('head meta[http-equiv="Content-Security-Policy"]')).toHaveAttribute("content", "script-src 'self'; connect-src 'none'");
});

test("every page but the 404 page has the token once as data in its head and no script for the counter @once", async ({ request }) => {
  for (const path of ["/", "/rules/", "/sources/", "/about/", "/changelog/", TRIO]) {
    const text = await (await request.get(path)).text();
    expect(text.split(META).length - 1, `${path} has the data once`).toBe(1);
    expect(text.indexOf(META), `${path}: in the head`).toBeLessThan(text.indexOf("</head>"));
    expect(text.match(/<script\b/g), `${path}: the boot script and the page script, and no more`).toHaveLength(2);
    expect(text, `${path}: no mark of a script for the counter`).not.toMatch(/cloudflareinsights|data-cf-beacon|beacon\.min/i);
  }
});

test("a page that is counted sets no cookie and leaves the keys of local and session storage as they were @once", async ({ page, context }) => {
  const counter = await answerForTheCounter(page);
  await page.addInitScript(() => {
    window.__keysBefore = JSON.stringify([Object.keys(localStorage), Object.keys(sessionStorage), document.cookie]);
  });
  await open(page, TRIO);
  await expect.poll(() => counter.sent.length).toBe(1); // (the stand-in has run)
  await page.waitForLoadState("networkidle");
  expect(await context.cookies(), "no cookie").toEqual([]);
  expect(await page.evaluate(() => document.cookie)).toBe("");
  expect(await page.evaluate(() => JSON.stringify([Object.keys(localStorage), Object.keys(sessionStorage), document.cookie]))).toBe(await page.evaluate(() => window.__keysBefore));
});

test("the plain build asks for nothing of the counter, whatever the page: no request to either host, no script element for it @once", async ({ page }) => {
  const asked = [];
  page.on("request", (request) => {
    if (/^https?:/.test(request.url()) && !request.url().startsWith(ORIGIN)) asked.push(request.url());
  });
  for (const path of ["/", TRIO, "/about/"]) {
    await page.goto(`${ORIGIN}${path}`);
    await expect(page.locator("#theme-toggle")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.locator("script[data-cf-beacon]")).toHaveCount(0);
  }
  expect(asked).toEqual([]);
});

test("the headers of this build are what the file it was built to says, and so are the plain build's @once", async ({ request }) => {
  const built = readFileSync(resolve(ROOT, "site", "dist-analytics", "_headers"), "utf8");
  const committed = readFileSync(resolve(ROOT, "site", "_headers"), "utf8");
  const live = (await request.get(`${ANALYTICS_ORIGIN}/`)).headers();
  expect(checkHeaders(live, expectedHeaders(built), { indexable: false }), "the counting build against its own file").toEqual([]);
  expect(checkHeaders(live, expectedHeaders(committed), { indexable: false }), "and not against the committed one: it names the two hosts").not.toEqual([]);
  const policy = (text) => expectedHeaders(text)["content-security-policy"];
  expect(policy(built).replace(` ${SCRIPT_HOST}`, "").replace(` ${DATA_HOST}`, "")).toBe(policy(committed));
  // the switch of the smoke check (--analytics) works out the same policy from the committed file alone as the build wrote into its own: the weekly task needs no other file
  expect(expectedHeaders(committed, { analytics: true }), "the check's counting policy is the build's own").toEqual(expectedHeaders(built));
  expect(checkHeaders(live, expectedHeaders(committed, { analytics: true }), { indexable: false, analytics: true }), "the counting build against the committed file with --analytics").toEqual([]);
  expect(checkHeaders((await request.get(`${ORIGIN}/`)).headers(), expectedHeaders(committed, { analytics: true }), { indexable: false, analytics: true }), "the plain build is not a counting site").not.toEqual([]);
  const plainHeaders = (await request.get(`${ORIGIN}/`)).headers();
  const plainBuilt = readFileSync(resolve(ROOT, "site", "dist-e2e", "_headers"), "utf8");
  expect(checkHeaders(plainHeaders, expectedHeaders(plainBuilt), { indexable: false }), "the plain build against its own file").toEqual([]);
  expect(checkHeaders(plainHeaders, expectedHeaders(committed), { indexable: false }), "and against the committed one").toEqual([]);
  expect(plainHeaders["content-security-policy"]).not.toMatch(/cloudflare/i);
});

test("the about page of a counting build says what is counted, and is as accessible as before @once", async ({ page }, testInfo) => {
  await open(page, "/about/");
  const text = await page.locator("main").innerText();
  for (const words of [
    "Page counts are on.",
    "Cloudflare Web Analytics",
    "a script from Cloudflare, a third party",
    "Cloudflare describes it as cookieless",
    "IP address",
    "A page that was opened from a shared kit link is not counted at all, and the script is not loaded there.",
    "A shared kit link that you open in a tab that is already counted is in that tab's address for a moment before the page loads it again, and the script that is running there can see it.",
    "The 404 page is not counted.",
    "The site loads nothing else from other sites.",
    "Cloudflare's counter script runs in the same page as the remembered gear",
    "Remember my gear on this device",
    "None of it is sent anywhere by the site.",
  ]) {
    expect(text).toContain(words);
  }
  expect(text).not.toMatch(/never holds it|removed from the address before the count|only thing the site itself keeps/);
  await expect(page.locator("main")).not.toContainText("has no analytics"); // (a counting build is not the plain build's page, which says it has none)
  await axe(page, testInfo);
});
