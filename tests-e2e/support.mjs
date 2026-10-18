// Shared pieces of the browser tests: a watcher that records everything a page does wrong, an independent reader of the
// data files (so the page is checked against the numbers, not against its own code), and readers of what the page shows.

import AxeBuilder from "@axe-core/playwright";
import { expect, test as base } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const TRIO = "/trio/pal-mnk-ber/";
export const DATA = "/data/pal-mnk-ber/";
/** Whether the results the preview is built from (scripts/preview.mjs: $TRIOFORGE_RESULTS, else the synthetic fixture) are a narrowed run. */
export const RESULTS_PARTIAL =
  JSON.parse(readFileSync(resolve(ROOT, process.env.TRIOFORGE_RESULTS ?? "fixtures/site/results", "pal-mnk-ber", "wiki-own.json"), "utf8")).partial === true;
export const PAGES = {
  home: "/",
  trio: TRIO,
  rules: "/rules/",
  sources: "/sources/",
  about: "/about/",
  changelog: "/changelog/",
};

// ---- the watcher ----------------------------------------------------------------------------------------------------------

/**
 * The Permissions-Policy header switches off the interfaces of the Privacy Sandbox as well. Chrome knows them; the Chromium these tests drive
 * is built without them, and answers a header that names one with a console warning ("Unrecognized feature"). Those six names are expected
 * to warn here; a warning about any other name (a mistyped one, say) is still a problem of the page.
 */
export const UNKNOWN_TO_THE_TEST_BROWSER = [
  "attribution-reporting",
  "join-ad-interest-group",
  "private-aggregation",
  "run-ad-auction",
  "shared-storage",
  "shared-storage-select-url",
];

/** Whether a console message is the test browser saying that it does not know one of the features the header names. */
export function unknownToTheTestBrowser(text) {
  const found = /^Error with Permissions-Policy header: Unrecognized feature: '([a-z-]+)'\.$/.exec(text);
  return found !== null && UNKNOWN_TO_THE_TEST_BROWSER.includes(found[1]);
}

/**
 * `watch` records what goes wrong on a page: console errors and warnings, uncaught exceptions, failed requests, answers
 * with a status of 400 or more, requests to any address but the site's own, and every `securitypolicyviolation` (a content
 * security policy or Trusted Types violation).
 * The violation listener is installed before any script of the page runs and reports into Node, so a violation is kept even
 * if the page navigates straight after it.
 */
export const test = base.extend({
  watch: async ({ page, baseURL }, use, testInfo) => {
    const home = new URL(baseURL);
    const events = [];
    const note = (kind, text, data = {}) => events.push({ kind, text, ...data });
    await page.exposeFunction("__tfViolation", (v) =>
      note("csp", `${v.directive} refused ${v.blocked || "an inline use"} at ${v.source || "the page"}:${v.line}${v.sample ? ` (${v.sample})` : ""}`, {
        directive: v.directive,
        disposition: v.disposition,
      }),
    );
    await page.addInitScript(() => {
      window.addEventListener(
        "securitypolicyviolation",
        (event) => {
          window
            .__tfViolation({
              directive: event.effectiveDirective || event.violatedDirective,
              blocked: event.blockedURI,
              source: event.sourceFile,
              line: event.lineNumber,
              sample: event.sample,
              disposition: event.disposition,
            })
            .catch(() => {});
        },
        true,
      );
    });
    page.on("console", (message) => {
      if (message.type() === "error" || message.type() === "warning") {
        if (unknownToTheTestBrowser(message.text())) return;
        const where = message.location()?.url ? ` (${message.location().url}:${message.location().lineNumber})` : "";
        note("console", `${message.type()}: ${message.text()}${where}`);
      }
    });
    page.on("pageerror", (error) => note("pageerror", error.message));
    page.on("requestfailed", (request) => note("requestfailed", `${request.method()} ${request.url()} ${request.failure()?.errorText ?? ""}`.trim()));
    page.on("response", (response) => {
      if (response.status() >= 400) note("http", `${response.status()} ${response.url()}`);
    });
    // the site talks to its own address and to nobody else
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (["http:", "https:", "ws:", "wss:"].includes(url.protocol) && url.origin !== home.origin) note("foreign", `${request.method()} ${request.url()}`);
    });
    await use({
      events,
      /** What went wrong, as lines of text; kinds named in `ignore` are left out (for tests that break something on purpose). */
      problems: (ignore = []) => events.filter((e) => !ignore.includes(e.kind)).map((e) => `${e.kind}: ${e.text}`),
      violations: () => events.filter((e) => e.kind === "csp"),
    });
    // a test that fails for another reason (a timeout, say) still shows what the page complained about
    if (testInfo.status !== testInfo.expectedStatus && events.length > 0) {
      throw new Error(`the page reported ${events.length} thing(s) before the test failed:\n${events.map((e) => `  ${e.kind}: ${e.text}`).join("\n")}`);
    }
  },
});

export { expect };

/**
 * Choose (or clear) a radio button or check box the way a visitor does, with a click on it. The input of a chip or a segment
 * lies invisibly over its label, and in the assumption panels the label lies over the input; either way the click lands
 * where the browser sends it, so Playwright's own check of what is under the pointer is switched off here, and the result
 * (that the control is now in the wanted state) is checked instead.
 */
export function pick(page, id, on = true) {
  return page.locator(`#${id}`).setChecked(on, { force: true });
}

/** How long open() waits for the page's script to show the theme button. */
export const THEME_TOGGLE_WAIT_MS = 20_000;

/** The most paths (or lines) of one kind that a report of a load lists. */
const MOST_LISTED = 20;

/** The path of an address, with no origin, query or fragment (an address that is none stays as it is), and no longer than a line should be. */
function pathOf(address) {
  let path = String(address);
  try {
    path = new URL(address).pathname;
  } catch {
    // (not an address: it is listed as it is)
  }
  return path.length > 160 ? `${path.slice(0, 160)}…` : path;
}

/** One line of text from a message of the page, which may run over several. */
const lineOf = (text) => String(text).replace(/\s+/g, " ").trim().slice(0, 300);

/**
 * Record what a page does while it loads, so that a page whose script did not start can say why: the requests that failed, the ones that were made and never finished, the answers with a
 * status of 400 or more, the console errors and the uncaught exceptions. `report()` is the text for a failure message (paths of addresses only, at most 20 of each kind, and a line that says
 * how many more there were); `stop()` ends the recording. Nothing is retried and nothing is waited for: this only listens.
 */
export function recordLoad(page) {
  const unfinished = new Map(); // request -> its line
  const failed = [];
  const refused = [];
  const consoleErrors = [];
  const pageErrors = [];
  const label = (request) => `${request.method()} ${pathOf(request.url())}`;
  const listeners = {
    request: (request) => unfinished.set(request, label(request)),
    requestfinished: (request) => unfinished.delete(request),
    requestfailed: (request) => {
      unfinished.delete(request);
      failed.push(`${label(request)} ${request.failure()?.errorText ?? ""}`.trim());
    },
    response: (response) => {
      if (response.status() >= 400) refused.push(`${response.status()} ${pathOf(response.url())}`);
    },
    console: (message) => {
      if (message.type() !== "error") return;
      const url = message.location()?.url;
      consoleErrors.push(`${lineOf(message.text())}${url ? ` (${pathOf(url)})` : ""}`);
    },
    pageerror: (error) => pageErrors.push(lineOf(error?.message ?? error)),
  };
  for (const [name, listener] of Object.entries(listeners)) page.on(name, listener);
  const list = (title, lines) => {
    if (lines.length === 0) return `${title} (0): none`;
    const shown = lines.slice(0, MOST_LISTED).map((line) => `  ${line}`);
    if (lines.length > MOST_LISTED) shown.push(`  … and ${lines.length - MOST_LISTED} more`);
    return [`${title} (${lines.length}):`, ...shown].join("\n");
  };
  return {
    report: () =>
      [
        list("requests that failed", failed),
        list("requests that never finished", [...unfinished.values()]),
        list("answers with a status of 400 or more", refused),
        list("console errors", consoleErrors),
        list("page errors", pageErrors),
      ].join("\n"),
    stop: () => {
      for (const [name, listener] of Object.entries(listeners)) page.off(name, listener);
    },
  };
}

/**
 * Open a page and wait until its script has started (the script reveals the theme button). When the button does not show in `toggleMs` (20 seconds, unless a test of this helper asks
 * for less), the error says what the page did while it loaded (recordLoad): the failed, unfinished and refused requests and the errors of the console and of the page.
 */
export async function open(page, path, { toggleMs = THEME_TOGGLE_WAIT_MS } = {}) {
  const load = recordLoad(page);
  try {
    // Waiting until the answer begins ("commit"), not until the page has loaded: a page script that is never answered keeps the load event from coming, and the wait for the button below
    // is the one that says so
    const response = await page.goto(path, { waitUntil: "commit" });
    expect(response?.status(), `${path} answers 200`).toBe(200);
    try {
      await expect(page.locator("#theme-toggle")).toBeVisible({ timeout: toggleMs });
    } catch (error) {
      throw new Error(`${path}: #theme-toggle did not show in ${toggleMs / 1000} s, so the page script did not run.\n${load.report()}\n\n${error.message}`, { cause: error });
    }
    await page.waitForLoadState("load"); // (as before, the page has loaded when open() returns)
  } finally {
    load.stop();
  }
}

/**
 * On a narrow screen the switches are folded away behind a Change button, under the line that says what is shown. Open them the way
 * a visitor does: with a click, or with the keyboard (Tab to the button, then Enter). Where they are shown already (a wide window),
 * or no button is offered (the page has no script), there is nothing to do. Returns whether the panel was opened.
 */
export async function openSwitches(page, { keyboard = false } = {}) {
  const toggle = page.locator("#switches-toggle");
  if (!(await toggle.isVisible())) return false;
  if ((await toggle.getAttribute("aria-expanded")) === "true") return false;
  if (keyboard) {
    await tabTo(page, "#switches-toggle", 30);
    await page.keyboard.press("Enter");
  } else {
    await toggle.click();
  }
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#switches")).toBeVisible();
  return true;
}

// ---- the data, read independently of the page's own code -----------------------------------------------------------------

/** The compact data file of one evidence/buffs pair, read the plain way. */
export function readShard(doc) {
  const rows = doc.rows; // [race, role, tier, setup, kit, value, gain, totals, haste]
  const find = (race, role, tier, setup) => rows.find((r) => r[0] === race && r[1] === role && r[2] === tier && r[3] === setup) ?? null;
  return {
    doc,
    evidence: doc.ev,
    buffs: doc.buffs,
    races: [...new Set(rows.map((r) => r[0]))],
    roles: [...new Set(rows.map((r) => r[1]))],
    tiers: [...new Set(rows.map((r) => r[2]))],
    scenario(race, role, tier, setup) {
      const row = find(race, role, tier, setup);
      if (!row) return null;
      return {
        setup,
        value: row[5],
        gain: row[6],
        haste: row[8],
        totals: doc.totals[row[7]],
        kit: doc.kits[row[4]].map((index) => (index < 0 ? null : doc.items[index])),
      };
    },
    /** The setups a role has scenarios for. */
    setupsFor: (role) => [...new Set(rows.filter((r) => r[1] === role).map((r) => r[3]))],
    /** The role's best setup: the highest value, the first listed on a tie. */
    best(race, role, tier) {
      let top = null;
      for (const row of rows) if (row[0] === race && row[1] === role && row[2] === tier && (top === null || row[5] > top[5])) top = row;
      return top ? top[3] : null;
    },
  };
}

export async function loadShard(request, evidence = "strict", buffs = "own") {
  const response = await request.get(`${DATA}${evidence}-${buffs}.json`);
  expect(response.ok(), `${evidence}-${buffs}.json can be fetched`).toBe(true);
  return readShard(await response.json());
}

const MINUS = "−";
const group = (number) => String(Math.abs(number)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
export const fmtInt = (number) => (number < 0 ? MINUS : "") + group(number);
export const fmtSigned = (number) => (number > 0 ? "+" : "") + fmtInt(number);
const roundHalfUp = (value) => Math.floor(value + 0.5);
const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const SEALS = { strict: "Seen in game", wiki: "Wiki" };
// a summoned item is made at its spell rank, so the data gives it no arrival tier (null) and the page says so
const arrivalWord = (arrival) => (arrival === null ? "spell rank" : `+${arrival}`);

/** The 22 rows of "Wear this" the data says a scenario must show. */
export function expectedKit(scenario, tier) {
  return scenario.kit.map((item) =>
    item
      ? {
          name: item[1],
          deity: item[6].length > 0 ? `Needs deity: ${item[6].join(" or ")}` : "",
          tier: `+${tier}`,
          arrival: arrivalWord(item[3]),
          source: item[4],
          seal: SEALS[item[5]],
        }
      : { name: "Leave empty", deity: "", tier: "—", arrival: "—", source: "—", seal: "—" },
  );
}

/** The totals the "Why this kit" section must show: the columns of a totals entry, in the order the data lists them. */
export function expectedTotals(scenario) {
  const names = ["ac", "hp", "mana", "end", "haste", "atk", "mr", "fr", "cr", "dr", "pr", "hpreg", "manareg", "endreg"];
  return Object.fromEntries(names.map((name, index) => [name, name === "haste" ? `${scenario.totals[index]}%` : fmtInt(scenario.totals[index])]));
}

// ---- what the page shows -------------------------------------------------------------------------------------------------

export function readKit(page) {
  return page.$$eval("#kit-body tr", (rows) =>
    rows.map((tr) => {
      const text = (name) => tr.querySelector(`[data-f="${name}"]`)?.textContent ?? null;
      return { name: text("name"), deity: text("deity"), tier: text("tier"), arrival: text("arrival"), source: text("source"), seal: text("seal") };
    }),
  );
}

/** The state of the switches as the visitor sees them. */
export function readControls(page) {
  return page.evaluate(() => {
    const checked = (name) => document.querySelector(`input[name="${name}"]:checked`)?.value ?? null;
    return {
      race: document.querySelector("#sw-race").value,
      role: checked("role"),
      tier: Number(document.querySelector("#sw-tier").value),
      setup: checked("setup"),
      ev: checked("ev"),
      buffs: checked("buffs"),
    };
  });
}

/** The values of a select's options, in the order they are listed. */
export function optionValues(page, selector) {
  return page.$$eval(`${selector} option`, (options) => options.map((option) => option.value));
}

/** The weapon setups the page offers: shown and not disabled. */
export function offeredSetups(page) {
  return page.$$eval('input[name="setup"]', (radios) => radios.filter((r) => !r.hidden && !r.disabled && r.closest("[hidden]") === null).map((r) => r.value));
}

/** Everything about a view that the page shows, read in one go so that it cannot be caught half way through drawing. */
export function snapshot(page) {
  return page.evaluate(() => {
    const text = (selector) => document.querySelector(selector)?.textContent ?? null;
    const checked = (name) => document.querySelector(`input[name="${name}"]:checked`)?.value ?? null;
    const names = ["ac", "hp", "mana", "end", "haste", "atk", "mr", "fr", "cr", "dr", "pr", "hpreg", "manareg", "endreg"];
    return {
      controls: {
        race: document.querySelector("#sw-race").value,
        role: checked("role"),
        tier: Number(document.querySelector("#sw-tier").value),
        setup: checked("setup"),
        ev: checked("ev"),
        buffs: checked("buffs"),
      },
      caption: (text("#kit-caption") ?? "").replace(/\s+/g, " ").trim(),
      assumes: { buffs: text('[data-f="assume-buffs"]'), setup: text('[data-f="assume-setup"]'), haste: text('[data-f="assume-haste"]'), ev: text('[data-f="assume-ev"]') },
      kit: [...document.querySelectorAll("#kit-body tr")].map((tr) => {
        const field = (name) => tr.querySelector(`[data-f="${name}"]`)?.textContent ?? null;
        return { name: field("name"), deity: field("deity"), tier: field("tier"), arrival: field("arrival"), source: field("source"), seal: field("seal") };
      }),
      totals: Object.fromEntries(names.map((name) => [name, text(`[data-f="t-${name}"]`)])),
      value: text("#kit-value"),
      gain: text("#kit-gain"),
      weapons: { setup: text('[data-f="w-setup"]'), main: text('[data-f="w-main"]'), off: text('[data-f="w-off"]') },
    };
  });
}

/**
 * The page shows exactly the view `want` describes, which the data says looks like this: the 22 rows, the totals, the kit value and gain,
 * the table caption, the assumptions line and the weapons block. `want.setup` is the setup the visitor asked for, or null for the
 * role's best. The page is given time to finish drawing. With `want.announced` the live region that tells screen readers about a change
 * must say so too: which switch the visitor changed (`want.announced` is its name: race, role, tier, setup, buffs or ev; `true` accepts
 * any of them), what is shown now, and what the kit is worth. Returns the scenario that was checked.
 */
export async function expectView(page, shard, want) {
  const setup = want.setup ?? shard.best(want.race, want.role, want.tier);
  const scenario = shard.scenario(want.race, want.role, want.tier, setup);
  expect(scenario, `the data has a scenario for ${want.race} ${want.role} +${want.tier} ${setup}`).not.toBeNull();
  const ev = want.ev ?? shard.evidence;
  const buffs = want.buffs ?? shard.buffs;
  const attribute = (selector, name) => page.locator(selector).first().getAttribute(name);
  const [raceName, roleName, setupName, setupPhrase, buffsPhrase, evPhrase] = await Promise.all([
    attribute(`#sw-race option[value="${want.race}"]`, "data-label"),
    attribute(`input[name="role"][value="${want.role}"]`, "data-label"),
    attribute(`input[name="setup"][value="${setup}"]`, "data-label"),
    attribute(`input[name="setup"][value="${setup}"]`, "data-phrase"),
    attribute(`input[name="buffs"][value="${buffs}"]`, "data-phrase"),
    attribute(`input[name="ev"][value="${ev}"]`, "data-phrase"),
  ]);
  const [main, off] = [scenario.kit[20], scenario.kit[21]];
  const expected = {
    controls: { race: want.race, role: want.role, tier: want.tier, setup, ev, buffs },
    caption: `For ${raceName} · ${roleName} · +${want.tier} · ${setupName}`,
    assumes: { buffs: buffsPhrase, setup: setupPhrase, haste: `${scenario.haste}%`, ev: evPhrase },
    kit: expectedKit(scenario, want.tier),
    totals: expectedTotals(scenario),
    value: fmtInt(roundHalfUp(scenario.value)),
    gain: fmtSigned(roundHalfUp(scenario.gain)),
    weapons: { setup: setupName, main: main ? main[1] : "Empty", off: off ? off[1] : "Empty" },
  };
  await expect.poll(() => snapshot(page), { message: "the page shows the view the data describes", timeout: 7_000 }).toEqual(expected);
  await expect(page.locator("#kit"), "the table is on the page, not hidden").toBeVisible();
  // a change made by the visitor is also announced to screen readers: the switch, what is shown now and what the kit is worth
  if (want.announced) {
    const leads = {
      race: `Race ${raceName}`,
      role: `Role ${roleName}`,
      tier: `Tier +${want.tier}`,
      setup: `Weapons ${setupName}`,
      buffs: `Buffs ${buffsPhrase}`,
      ev: `Evidence ${evPhrase}`,
    };
    expect(want.announced === true || want.announced in leads, `${want.announced} is a switch`).toBe(true);
    const shown = `Showing ${raceName}, ${roleName}, +${want.tier}, ${setupName}. Kit value ${expected.value}.`;
    const said = want.announced === true ? new RegExp(`^(?:${Object.values(leads).map(escapeRegExp).join("|")})\\. ${escapeRegExp(shown)}$`) : `${leads[want.announced]}. ${shown}`;
    await expect(page.locator("#announce")).toHaveText(said);
  }
  return scenario;
}

/** The address query as an object. */
export function queryOf(page) {
  return Object.fromEntries(new URL(page.url()).searchParams);
}

// ---- accessibility -------------------------------------------------------------------------------------------------------

// axe leaves target-size (the one rule of WCAG 2.2 AA) switched off, and four rules on WCAG A and AA criteria are still marked
// experimental; they are all switched on here
const EXTRA_RULES = ["target-size", "css-orientation-lock", "label-content-name-mismatch", "p-as-heading", "table-fake-caption", "td-has-header"];
const describeViolation = (v) => `${v.id} (${v.impact}): ${v.help}; ${v.nodes.length} place(s), first ${v.nodes[0]?.target?.join(" ")}`;

/**
 * Run axe on the page as it is now. Fails on a violation whose impact is one of `impacts` (serious and critical unless the caller names others: the pages of the items name moderate
 * as well). Lesser findings and anything axe could not decide are attached to the test as annotations (the report shows them) without failing it.
 */
export async function axe(page, testInfo, { impacts = ["serious", "critical"] } = {}) {
  const results = await new AxeBuilder({ page }).options({ rules: Object.fromEntries(EXTRA_RULES.map((id) => [id, { enabled: true }])) }).analyze();
  const blocking = results.violations.filter((v) => impacts.includes(v.impact));
  for (const v of results.violations.filter((v) => !blocking.includes(v))) testInfo.annotations.push({ type: "axe-minor", description: describeViolation(v) });
  for (const v of results.incomplete) testInfo.annotations.push({ type: "axe-needs-review", description: `${v.id}: ${v.help}; ${v.nodes.length} place(s)` });
  expect(blocking.map(describeViolation), `${impacts.join(", ")} axe violations`).toEqual([]);
  // axe did look: the checks that matter most were run (a violation would have failed above, so these passed)
  const ran = new Set([...results.passes, ...results.violations, ...results.incomplete].map((rule) => rule.id));
  for (const id of ["color-contrast", "target-size", "html-has-lang", "skip-link", "landmark-one-main", "page-has-heading-one"]) {
    expect(ran.has(id), `axe ran ${id}`).toBe(true);
  }
  return results;
}

// ---- the headers file ----------------------------------------------------------------------------------------------------

/** The blocks of site/_headers: a map from each path pattern to the headers it sets (lower-cased names), in file order. */
export function readHeaderBlocks() {
  const text = readFileSync(resolve(ROOT, "site", "_headers"), "utf8");
  const blocks = new Map();
  let current = null;
  for (const line of text.split(/\r?\n/)) {
    if (line.trim() === "" || line.trim().startsWith("#")) continue; // a blank line or a comment
    const header = /^\s+([A-Za-z][A-Za-z-]*):\s*(.*?)\s*$/.exec(line);
    if (header === null) {
      current = new Map();
      blocks.set(line.trim(), current);
    } else if (current === null) {
      throw new Error(`site/_headers has a header before any path pattern: ${line}`);
    } else {
      current.set(header[1].toLowerCase(), header[2]);
    }
  }
  return blocks;
}

/** The headers site/_headers sets for one path pattern (by default `/*`, every path), lower-cased names. */
export function readHeadersFile(pattern = "/*") {
  const block = readHeaderBlocks().get(pattern);
  if (block === undefined) throw new Error(`site/_headers has no block for ${pattern}`);
  return block;
}

// ---- keyboard ------------------------------------------------------------------------------------------------------------

/** Press Tab until the element matching `selector` has focus; fails if that takes more than `limit` presses. Returns the presses. */
export async function tabTo(page, selector, limit = 40) {
  for (let presses = 1; presses <= limit; presses++) {
    await page.keyboard.press("Tab");
    if (await page.evaluate((s) => document.activeElement?.matches(s) ?? false, selector)) return presses;
  }
  throw new Error(`${selector} was not reached within ${limit} Tab presses`);
}

/**
 * How the focused element shows that it has focus, as a pixel width: its own outline, or for a radio button or check box
 * (whose input is invisible and covers its label) the outline of the label beside it.
 */
export function focusRingWidth(page) {
  return page.evaluate(() => {
    const active = document.activeElement;
    if (!active) return 0;
    const target = active.matches('input[type="radio"], input[type="checkbox"]') ? active.nextElementSibling : active;
    const style = getComputedStyle(target);
    return style.outlineStyle === "none" ? 0 : Number.parseFloat(style.outlineWidth);
  });
}

// ---- names ---------------------------------------------------------------------------------------------------------------

/**
 * The accessible names of the elements of one role, as the browser itself works them out (the accessibility tree of Chromium, read
 * through the DevTools protocol), in page order. An element that is not in the tree (hidden, or not rendered) is not listed. Used
 * where the name depends on how the stylesheet and the browser treat text that only the stylesheet adds (a check mark).
 */
export async function accessibleNames(page, role) {
  const client = await page.context().newCDPSession(page);
  try {
    await client.send("Accessibility.enable");
    const { nodes } = await client.send("Accessibility.getFullAXTree");
    return nodes.filter((node) => !node.ignored && node.role?.value === role).map((node) => node.name?.value ?? "");
  } finally {
    await client.detach();
  }
}
