// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// Spend your motes, in the Upgrade section of a trio page, end to end in jsdom: the page code, the real code of the section (ui/motes.js and what wakes it) and the engine's own evaluator
// (engine/kitvalue.js, `moteWalkOf`) run against the fake site of the engine tests, whose item table and bundle are the fixture's. The page is the contract copy of the trio page. Every
// number below is the one the Python reference recorded (fixtures/site/mote-orders.json), written the way the page writes a difference; nothing is read back from the code under test.
// Both kits are covered: the best kit of the page (read from the rows of Wear this, a published kit) and the gear (the kit Equip now wears, which the answer hands over). Every name is invented.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bestBuffsOfKit, loadKitBundle, moteWalkOf, valueOfKit } from "../pipeline/trioforge/site/static/engine/kitvalue.js";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { parseManifest } from "../pipeline/trioforge/site/static/engine/manifest.js";
import { STARTUP_COMPILE_MS, STARTUP_STALL_MS } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { displayInt, fmtInt, fmtSigned } from "../pipeline/trioforge/site/static/format.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import { createMotes } from "../pipeline/trioforge/site/static/ui/motes.js";
import { ITEMS_BYTES, makeSite, sha256, siteFetch } from "./engine-site-fixture.mjs";
import { addByName, equipStep, fakeEngine, kitOf, mountAnswer, words } from "./upgrade-answer-helpers.mjs";
import { $, $$, mountPage, type, wake } from "./upgrade-helpers.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const MAIN = "/engine-manifest.json";
const KITVALUE_PATH = "/assets/engine/kitvalue-AAAAAAAA.js";
const KITVALUE_BYTES = new TextEncoder().encode("export const evaluator = true;\n");
const script = (bytes) => new Response(bytes, { status: 200, headers: { "content-type": "text/javascript; charset=utf-8" } });
const TABLE_JSON = JSON.parse(ITEMS_BYTES.toString("utf8"));
const { cases, extra } = JSON.parse(readFileSync(resolve(HERE, "../fixtures/site/mote-orders.json"), "utf8"));
// the item table of the fixture with the invented items of the runs added (the page's own table, in the tests that run the whole page, does not have them)
const WITH_RUNS = readItemTable({ ...TABLE_JSON, count: TABLE_JSON.items.length + extra.length, items: [...TABLE_JSON.items, ...extra] });
const NAMES = new Map([...TABLE_JSON.items, ...extra].map((item) => [item.id, item.name]));
const nameOf = (key) => NAMES.get(Number(key.slice(1))) ?? key;
const BAKED = cases.find((row) => row.name.startsWith("the best kit of the fixture's baked page"));
const EQUIP = cases[0]; // Equip now's kit of the first scenario, with a limit of 40 motes
const WEIGHTED = cases.find((row) => row.weights !== undefined && row.name.startsWith("under drawn weights"));
const OVERTAKE = cases.find((row) => row.name.startsWith("an ear of 25 haste behind a neck"));
const OVERTAKE_THREE = cases.find((row) => row.name.startsWith("the same, with three motes"));
const OVERTAKE_EIGHT = cases.find((row) => row.name.startsWith("the same, with eight motes"));
const PLATEAU = cases.find((row) => row.name.startsWith("a dagger of damage five"));
const EVALUATOR = { moteWalkOf, bestBuffsOfKit, loadKitBundle, valueOfKit };
const dataFile = (name) => JSON.parse(readFileSync(resolve(CONTRACT, `data/${name}.json`), "utf8"));
const serveShards = (url) => {
  if (!String(url).startsWith("/data/pal-mnk-ber/")) return undefined;
  const name = String(url).replace("/data/pal-mnk-ber/", "").replace(".json", "");
  return new Response(JSON.stringify(dataFile(name)), { status: 200, headers: { "content-type": "application/json" } });
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  document.body.replaceChildren();
});

/**
 * The page code on the contract page, with the section's code woken by a first focus on its pick box (or not woken: `wake: false`). `evaluator` is what the evaluator's script is, once the page has
 * fetched it and checked its SHA-256; the stand-in optimizer is the one of the answer's tests.
 */
function open({ wake: woken = true, evaluator = EVALUATOR, loadEvaluator, listed = true, bytes = KITVALUE_BYTES } = {}) {
  mountPage();
  const made = makeSite();
  if (listed) made.manifestJson.kitvalue = { path: KITVALUE_PATH, bytes: KITVALUE_BYTES.length, gzip: 20, sha256: sha256(KITVALUE_BYTES) };
  made.files.set(MAIN, new TextEncoder().encode(JSON.stringify(made.manifestJson)));
  const net = siteFetch(made, { serve: (url) => (new URL(url, "https://trioforge.test").pathname === KITVALUE_PATH ? script(bytes) : serveShards(url)) });
  const engine = fakeEngine();
  const loadEngine = vi.fn(async (url) => (String(url).includes("/kitvalue-") ? (loadEvaluator ? loadEvaluator() : evaluator) : engine.loadEngine(url)));
  const app = initTrio({ document, window, fetch: net.fetchImpl, loadEngine });
  if (woken) $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
  return { app, net, engine, loadEngine };
}

const text = (selector) => ($(selector)?.textContent ?? "").replace(/\s+/g, " ").trim();
const waitFor = (check, timeout = 5000) => vi.waitFor(check, { timeout, interval: 10 });
const lines = () => $$("#upgrade-motes-list > li").map((li) => li.querySelector(".step-what").textContent);
const factsOf = (li) => [...li.querySelectorAll(".owned-meta")].map((node) => node.textContent);
const tick = () => $("#upgrade-motes-open");
const slot = (index) => document.querySelectorAll("#kit-body tr th")[index].textContent;
/** A change in kit value as the page writes a difference (the section's own rule): half up, "+<1" for a gain that rounds to nothing. */
function signed(value) {
  const shown = displayInt(value);
  if (shown === 0 && value > 0) return "+<1";
  if (shown === 0 && value < 0) return `${fmtSigned(-1).slice(0, -1)}<1`;
  return fmtSigned(shown);
}
const number = (fraction) => Number(BigInt(fraction.split("/")[0])) / Number(BigInt(fraction.split("/")[1]));
const STATS = new Map([["HASTE", "Haste"], ["FIRE", "FR"], ["COLD", "CR"], ["MAGIC", "MR"], ["POISON", "PR"], ["DISEASE", "DR"], ["MANA", "Mana"], ["END", "End"], ["HPREG", "HP regen"], ["MANAREG", "Mana regen"], ["ENDREG", "End regen"], ["DMG", "Damage"]]); // prettier-ignore
/** The line of a step that Python recorded, as the page words it: "Chest: <item> +7 to +8, +142". */
const lineOf = (step) => `${slot(step.place)}: ${nameOf(step.key)} +${step.from} to +${step.to}, ${step.motes > 1 ? `${step.motes} motes, ` : ""}${signed(number(step.gain))}`;
const movedOf = (step) => step.moved.map(([name, amount]) => `${STATS.get(name) ?? name} ${signed(number(amount))}`).join(", ");
const valueOf = (step) => `kit value ${fmtInt(displayInt(number(step.F)))}`;
/** The motes spent so far, said once a run has made them differ from the number of the line. */
const spentOf = (step) => (step.spent === step.index ? [] : [`${step.spent} motes so far`]);
/** The list on the page is the first `count` steps Python recorded for the row: the line, the stats that moved and the kit value after the step. */
const check = (row, count = row.steps.length) => {
  expect(lines()).toEqual(row.steps.slice(0, count).map(lineOf));
  $$("#upgrade-motes-list > li").forEach((li, at) => {
    const step = row.steps[at];
    expect(factsOf(li), `step ${step.index}`).toEqual([...(step.moved.length === 0 ? [] : [movedOf(step)]), valueOf(step), ...spentOf(step)]);
  });
};
/** The visitor ticks the box (a click, which is what a pointer or the space key does to a check box). */
const tickBox = () => tick().click();
/** The kit of the page is drawn again at another tier, as a switch does (the rows of Wear this are written). */
function drawKit({ tier }) {
  for (const row of document.querySelectorAll("#kit-body tr")) {
    if (row.querySelector('[data-f="name"] a') !== null) row.querySelector('[data-f="tier"]').textContent = `+${tier}`;
  }
}
const choose = (selector) => {
  const radio = $(selector);
  radio.checked = true;
  radio.dispatchEvent(new Event("change", { bubbles: true }));
};

describe("the box that opens it", () => {
  it("is in the page: a check box, off, labelled Spend motes, one of the controls that wake the section's code, at the end of the section, under the answer", () => {
    mountPage();
    const box = tick();
    expect(box.type).toBe("checkbox");
    expect(box.checked).toBe(false);
    expect(box.hasAttribute("data-wake")).toBe(true);
    expect(box.disabled).toBe(true); // (made off, like the other controls of the section, until the page code runs)
    expect(document.querySelector(`label[for="upgrade-motes-open"]`).textContent).toBe("Spend motes");
    expect($("#upgrade-results").compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(box.closest(".opt").nextElementSibling).toBeNull(); // (the last thing in the section: the list under it grows into nothing)
    expect(box.closest("#upgrade")).not.toBeNull();
  });

  it("is enabled by the page code, and nothing is fetched or loaded until it is used", async () => {
    const { app, net, loadEngine } = open({ wake: false });
    expect(tick().disabled).toBe(false);
    expect(net.asked).toEqual([]);
    expect(loadEngine).not.toHaveBeenCalled();
    await app.whenIdle();
    expect($("#upgrade-motes")).toBeNull();
  });

  it("opens the panel when it is ticked before the section's code is there (the click that woke the code is not lost), and says what it is for, in plain words", async () => {
    const { app } = open({ wake: false });
    tickBox(); // the click wakes the section (a click on one of its controls); the box has changed by itself
    expect(tick().checked).toBe(true);
    await app.whenIdle();
    await waitFor(() => expect($("#upgrade-motes")).not.toBeNull());
    const panel = $("#upgrade-motes");
    expect(panel.hidden).toBe(false);
    expect(panel.tagName).toBe("SECTION");
    expect(tick().closest(".opt").nextElementSibling, "right under the box").toBe(panel);
    expect(panel.getAttribute("aria-labelledby")).toBe("upgrade-motes-h");
    expect($("#upgrade-motes-h").textContent).toBe("Spend your motes");
    expect(tick().getAttribute("aria-expanded")).toBe("true");
    expect(tick().getAttribute("aria-controls")).toBe("upgrade-motes");
    const said = panel.textContent;
    expect(said).toContain("A mote gives one whole tier at any tier, so it saves the most work on the highest tiers.");
    expect(said).toContain("This is the best single next step, not a proven best plan for the motes you have");
    expect(said).not.toContain("change gradually as it progresses"); // (the page says that once, in the section about the stats)
    expect(panel.querySelector('a[href="/rules/#tier.void_mote"]').textContent, "the rule that says what a mote is").toBe("Void-touched mote");
  });
});

describe("the best kit of the page", () => {
  /** The panel is open on the page's kit (no gear): the list of the baked kit, all the way. */
  async function opened() {
    const run = open();
    await run.app.whenIdle();
    await waitFor(() => expect($("#upgrade-motes")).not.toBeNull());
    tickBox();
    await waitFor(() => expect($("#upgrade-motes-end").hidden).toBe(false));
    return run;
  }

  it("is the choice when there is no gear, and its list is the one Python recorded for the kit Wear this shows, line by line: place, item, tiers, gain, the stats that moved and the kit value", async () => {
    await opened();
    expect($("#upgrade-motes-source-page").checked).toBe(true);
    expect($("#upgrade-motes-source-gear").checked).toBe(false);
    expect(BAKED.steps.length).toBe(120);
    check(BAKED);
    expect(lines()[0]).toMatch(/^[A-Za-z0-9 ]+: .+ \+4 to \+5, [+−]?[\d,<+]+$/); // "Chest: <item> +4 to +5, +142"
    expect(text("#upgrade-motes-end")).toBe("After these, no mote adds any kit value: 6 could still be spent, and none of them gains anything.");
    expect(text("#upgrade-motes-for")).toMatch(/^For the best kit of this page \(.+\): kit value now [\d,]+\.$/);
    expect($("#upgrade-motes-state").classList.contains("quiet")).toBe(true);
  });

  it("says the list once through the page's live region, when it is ready: how many motes, for what, and the first one", async () => {
    await opened();
    await waitFor(() => expect($("#announce").textContent).toContain("Spend your motes: 120 motes"));
    const what = /^For (the best kit of this page \(.+\)): kit value now/.exec(text("#upgrade-motes-for"))[1];
    expect($("#announce").textContent).toBe(`Spend your motes: 120 motes for ${what}. First: ${lineOf(BAKED.steps[0])}. After these, no mote adds any kit value: 6 could still be spent, and none of them gains anything.`);
  });

  it("shows only as many lines as the motes asked for, and the first N lines of the whole order are the order for N motes", async () => {
    await opened();
    const box = $("#upgrade-motes-n");
    expect(box.type).toBe("number");
    expect(document.querySelector('label[for="upgrade-motes-n"]').textContent).toBe("Motes to spend");
    expect(box.getAttribute("aria-describedby")).toBe("upgrade-motes-help");
    expect(text("#upgrade-motes-help")).toBe("Leave empty for every mote there is to spend.");
    type(box, "5");
    check(BAKED, 5);
    expect(text("#upgrade-motes-end")).toBe("These are the first 5 motes.");
    type(box, "1");
    check(BAKED, 1);
    expect(text("#upgrade-motes-end")).toBe("These are the first 1 mote.");
    type(box, "9999"); // (more than there are to spend: an order of its own, which ends where the whole one does)
    await waitFor(() => expect(lines()).toHaveLength(120));
    check(BAKED);
    expect(text("#upgrade-motes-end")).toBe("After these, no mote adds any kit value: 6 could still be spent, and none of them gains anything.");
    type(box, ""); // (the whole order was worked out already: it is there at once)
    check(BAKED);
  });

  it("works out each number of motes once and keeps it, and the whole order too: going back to a number or to the whole is no new work", async () => {
    const walks = vi.fn(moteWalkOf);
    const run = open({ evaluator: { ...EVALUATOR, moteWalkOf: walks } });
    await run.app.whenIdle();
    await waitFor(() => expect($("#upgrade-motes")).not.toBeNull());
    type($("#upgrade-motes-n"), "3"); // before the box is ticked: the number is waiting
    tickBox();
    await waitFor(() => expect(lines()).toHaveLength(3));
    expect(text("#upgrade-motes-end")).toBe("These are the first 3 motes.");
    type($("#upgrade-motes-n"), "10");
    await waitFor(() => expect(lines()).toHaveLength(10));
    check(BAKED, 10);
    type($("#upgrade-motes-n"), "2");
    check(BAKED, 2);
    type($("#upgrade-motes-n"), "");
    await waitFor(() => expect(lines()).toHaveLength(120));
    check(BAKED);
    for (const again of ["3", "10", ""]) type($("#upgrade-motes-n"), again); // (nothing new to work out: what was worked out is kept)
    await waitFor(() => expect(lines()).toHaveLength(120));
    expect(walks).toHaveBeenCalledTimes(4); // 3, 10, 2 and the whole order
  });

  it("takes a number of seven digits or more as a number: more motes than there are to spend means the whole order", async () => {
    await opened();
    const box = $("#upgrade-motes-n");
    for (const long of ["1000000", "99999999999999999999", "0000009"]) {
      type(box, long);
      expect(box.getAttribute("aria-invalid"), long).toBe("false");
      expect($("#upgrade-motes-bad").hidden, long).toBe(true);
    }
    type(box, "9");
    await waitFor(() => expect(lines()).toHaveLength(9));
    type(box, "99999999999999999999");
    await waitFor(() => expect(lines()).toHaveLength(120));
    expect(text("#upgrade-motes-end")).toBe("After these, no mote adds any kit value: 6 could still be spent, and none of them gains anything.");
  });

  it("refuses a number that is not a whole number of at least one: the list stays, the box says it is wrong, and nothing is worked out again", async () => {
    await opened();
    const box = $("#upgrade-motes-n");
    type(box, "4");
    for (const bad of ["0", "-3", "2.5", "1e2", "00"]) {
      type(box, bad);
      expect(box.getAttribute("aria-invalid"), bad).toBe("true");
      expect(text("#upgrade-motes-bad"), bad).toBe("Use a whole number of motes from 1, or leave the box empty.");
      expect($("#upgrade-motes-bad").hidden, bad).toBe(false);
      expect(box.getAttribute("aria-describedby"), bad).toBe("upgrade-motes-help upgrade-motes-bad");
      check(BAKED, 4);
    }
    type(box, "7");
    expect(box.getAttribute("aria-invalid")).toBe("false");
    expect($("#upgrade-motes-bad").hidden).toBe(true);
    expect(box.getAttribute("aria-describedby")).toBe("upgrade-motes-help");
    check(BAKED, 7);
  });

  it("says a number that is being typed once it settles, not at every key", async () => {
    await opened();
    await waitFor(() => expect($("#announce").textContent).toContain("Spend your motes: 120 motes"));
    $("#announce").textContent = "";
    type($("#upgrade-motes-n"), "1");
    type($("#upgrade-motes-n"), "12");
    expect($("#announce").textContent).toBe("");
    await waitFor(() => expect($("#announce").textContent).toContain("Spend your motes: 12 motes"), 3000);
    expect($("#announce").textContent).toContain(`First: ${lineOf(BAKED.steps[0])}.`);
    expect($("#announce").textContent).toContain("These are the first 12 motes.");
  });

  it("goes when the kit of the page changes, and is worked out again for the kit that is shown: an old list is never left under a new kit", async () => {
    await opened();
    expect(lines()).toHaveLength(120);
    drawKit({ tier: 9 }); // the visitor switches the tier: every row is drawn again at +9, one mote each
    await waitFor(() => expect(lines()).toHaveLength(0)); // at once, the old list is gone
    await waitFor(() => expect(lines()).toHaveLength(20), 5000);
    expect(lines().every((line) => / \+9 to \+10, /.test(line))).toBe(true);
    expect(text("#upgrade-motes-end")).toBe("After these, no mote adds any kit value: 1 could still be spent, and none of them gains anything.");
    expect(text("#upgrade-motes-for")).toMatch(/^For the best kit of this page/);
    drawKit({ tier: 10 });
    await waitFor(() => expect(text("#upgrade-motes-end")).toBe("Every item is at +10, so there is nothing to spend a mote on."), 5000);
    expect(lines()).toEqual([]);
    expect($("#upgrade-motes-list").children).toHaveLength(0);
  });

  it("does not draw what a run that a change has ended was still working at", async () => {
    const run = open();
    await run.app.whenIdle();
    await waitFor(() => expect($("#upgrade-motes")).not.toBeNull());
    let time = 0;
    vi.spyOn(window.performance, "now").mockImplementation(() => (time += 50)); // every step ends its slice: the run takes many turns, and a change comes in the middle
    tickBox();
    await waitFor(() => expect(lines().length).toBeGreaterThan(3));
    drawKit({ tier: 9 });
    await waitFor(() => expect(lines()).toHaveLength(0));
    const seen = [];
    const watcher = new MutationObserver(() => seen.push(lines().slice()));
    watcher.observe($("#upgrade-motes-list"), { childList: true });
    await waitFor(() => expect(lines().length).toBeGreaterThan(0), 5000);
    watcher.disconnect();
    for (const list of seen) expect(list.every((line) => / \+9 to \+10, /.test(line)), "a line of the old kit, drawn after the change").toBe(true);
    await waitFor(() => expect(lines()).toHaveLength(20), 8000);
  });

  it("says so when it cannot read the kit that is shown (an item with no link), and offers nothing", async () => {
    open();
    await waitFor(() => expect(tick().disabled).toBe(false));
    document.querySelector('#kit-body tr [data-f="name"] a').replaceWith("An item with no page");
    tickBox();
    await waitFor(() => expect($("#upgrade-motes")).not.toBeNull());
    await waitFor(() => expect(text("#upgrade-motes-state")).toBe("The kit shown on this page could not be read here."));
    expect(lines()).toEqual([]);
  });

  it("goes when the box is unticked and is worked out again when it is ticked", async () => {
    await opened();
    tickBox();
    expect($("#upgrade-motes").hidden).toBe(true);
    expect(tick().getAttribute("aria-expanded")).toBe("false");
    expect(lines()).toEqual([]);
    tickBox();
    expect($("#upgrade-motes").hidden).toBe(false);
    await waitFor(() => expect(lines()).toHaveLength(120));
    check(BAKED);
  });

  it("follows a switch of the page: the group buffs are another published kit, so the list is worked out again under them", async () => {
    await opened();
    choose('input[name="buffs"][value="group"]');
    await waitFor(() => expect(lines()).toHaveLength(0));
    await waitFor(() => expect(text("#upgrade-motes-for")).toMatch(/group/i), 8000);
    await waitFor(() => expect(lines().length).toBeGreaterThan(0), 8000);
  });

  it("is a form a keyboard can use: the box, the two choices in one group with a legend, the number with its label, and the list with the heading's name", async () => {
    await opened();
    expect(tick().tabIndex).toBe(0);
    const group = $("#upgrade-motes fieldset");
    expect(group.querySelector("legend").textContent).toBe("Spend them on");
    expect([...group.querySelectorAll("input")].map((input) => [input.type, input.name, input.value])).toEqual([["radio", "upgrade-motes-source", "gear"], ["radio", "upgrade-motes-source", "page"]]);
    for (const input of document.querySelectorAll("#upgrade-motes input")) {
      expect(document.querySelector(`label[for="${input.id}"]`), input.id).not.toBeNull();
      expect(input.disabled).toBe(false);
    }
    expect($("#upgrade-motes-list").getAttribute("aria-labelledby")).toBe("upgrade-motes-h");
    expect($("#upgrade-motes-h").getAttribute("tabindex")).toBe("-1");
    expect(document.querySelectorAll("#upgrade-motes [aria-live], #upgrade-motes [role=status], #upgrade-motes [role=alert]")).toHaveLength(0); // (what is said is said through the page's live region)
    $("#upgrade-motes-n").focus();
    type($("#upgrade-motes-n"), "6");
    expect(document.activeElement, "the focus is not moved by the list coming in").toBe($("#upgrade-motes-n"));
  });

  it("says that the order could not be worked out when the evaluator could not be had, with Try again, and works when the retry can", async () => {
    let fail = true;
    const run = open({ loadEvaluator: async () => (fail ? Promise.reject(new Error("no")) : EVALUATOR) });
    await run.app.whenIdle();
    await waitFor(() => expect($("#upgrade-motes")).not.toBeNull());
    tickBox();
    await waitFor(() => expect(text("#upgrade-motes-state")).toMatch(/^The order of motes could not be worked out here\./));
    expect($("#announce").textContent).toBe("The order of motes could not be worked out here.");
    expect(lines()).toEqual([]);
    fail = false;
    $("#upgrade-motes-state button").click();
    await waitFor(() => expect(lines()).toHaveLength(120));
    expect(text("#upgrade-motes-state")).toBe("");
  });

  it("refuses an evaluator that is not the one the manifest lists, and one the manifest does not list", async () => {
    const wrong = open({ bytes: new TextEncoder().encode("export const evaluator = false;\n") });
    await wrong.app.whenIdle();
    await waitFor(() => expect($("#upgrade-motes")).not.toBeNull());
    tickBox();
    await waitFor(() => expect(text("#upgrade-motes-state")).toMatch(/^The order of motes could not be worked out here\./));
    expect(wrong.loadEngine.mock.calls.filter(([url]) => String(url).includes("/kitvalue-"))).toHaveLength(0);
    document.body.replaceChildren();
    const none = open({ listed: false });
    await none.app.whenIdle();
    await waitFor(() => expect($("#upgrade-motes")).not.toBeNull());
    tickBox();
    await waitFor(() => expect(text("#upgrade-motes-state")).toMatch(/^The order of motes could not be worked out here\./));
  });
});

/**
 * The panel on its own, made on the contract page with a view and watchers that the test drives (as `mountAnswer` does for the answer), for what needs a view that the page's own switches
 * cannot give in jsdom (custom weights, the raid) and for the gear that Equip now hands over (`setGear`).
 */
function mountPanel({ view = {}, evaluator = EVALUATOR } = {}) {
  const root = mountPage();
  wake(root);
  root.dataset.level = "50";
  const made = makeSite();
  made.manifestJson.kitvalue = { path: KITVALUE_PATH, bytes: KITVALUE_BYTES.length, gzip: 20, sha256: sha256(KITVALUE_BYTES) };
  made.files.set(MAIN, new TextEncoder().encode(JSON.stringify(made.manifestJson)));
  const net = siteFetch(made, { serve: (url) => (new URL(url, "https://trioforge.test").pathname === KITVALUE_PATH ? script(KITVALUE_BYTES) : undefined) });
  let shown = { race: "OGR", role: "tank", buffs: "own", evidence: "strict", setup: "dw", weights: null, ...view };
  const watchers = new Set();
  const spoken = [];
  const panel = createMotes(root, {
    records: WITH_RUNS.records,
    listed: parseManifest(JSON.parse(JSON.stringify(made.manifestJson))),
    trio: "pal-mnk-ber",
    level: 50,
    view: () => ({ ...shown }),
    onView: (callback) => {
      watchers.add(callback);
      return () => watchers.delete(callback);
    },
    words: words(),
    announce: (text) => spoken.push(text),
    doc: document,
    win: window,
    fetchImpl: net.fetchImpl,
    base: window.location.href,
    stallMs: STARTUP_STALL_MS,
    bodyMs: STARTUP_COMPILE_MS,
    loadEngine: async () => evaluator,
  });
  return {
    root,
    panel,
    spoken,
    setView(change) {
      shown = { ...shown, ...change };
      for (const watcher of [...watchers]) watcher();
    },
  };
}

describe("a view that has no published kit", () => {
  it("is not offered for custom weights, or for buffs other than the own and the group ones, where Wear this shows the optimizer's answer", async () => {
    const { setView } = mountPanel();
    tickBox();
    await waitFor(() => expect(lines()).toHaveLength(120));
    setView({ buffs: "raid" });
    await waitFor(() => expect(text("#upgrade-motes-state")).toMatch(/^The kit shown here is the optimizer's answer for these buffs or weights, not a published one\./));
    expect(lines()).toEqual([]);
    expect($("#upgrade-motes-end").hidden).toBe(true);
    expect($("#upgrade-motes-for").hidden).toBe(true);
    setView({ buffs: "own" });
    await waitFor(() => expect(lines()).toHaveLength(120));
    setView({ weights: { multipliers: { HP: 2 } } });
    await waitFor(() => expect(lines()).toEqual([]));
    await waitFor(() => expect(text("#upgrade-motes-state")).toMatch(/not a published one/));
    setView({ weights: null });
    await waitFor(() => expect(lines()).toHaveLength(120), 8000);
    check(BAKED);
  });

  it("drops the list at once when the view changes, and works out the kit that is shown", async () => {
    const { setView } = mountPanel();
    tickBox();
    await waitFor(() => expect(lines()).toHaveLength(120));
    setView({ role: "melee" });
    expect(lines(), "at once, before the pause that lets a change settle").toEqual([]);
    await waitFor(() => expect(lines()).toHaveLength(120), 8000);
  });
});

describe("the gear", () => {
  /** What the answer hands over when it draws Equip now: the request it was made for (the view and the weights), the kit and the optional buffs. */
  const gearOf = (row) => ({ request: { scenario: row.scenario, ...(row.weights === undefined ? {} : { weights: row.weights }) }, kit: row.kit, buffs: row.buffs });

  function opened(row = EQUIP) {
    const run = mountPanel();
    run.panel.setGear(gearOf(row));
    tickBox();
    return run;
  }

  it("is the choice when Equip now has a kit, and its list is the order Python recorded for that kit at the tiers of the gear (the buffs it was found with held fixed)", async () => {
    opened();
    expect($("#upgrade-motes-source-gear").checked).toBe(true);
    type($("#upgrade-motes-n"), String(EQUIP.motes));
    await waitFor(() => expect(lines()).toHaveLength(40));
    check(EQUIP);
    expect(text("#upgrade-motes-end")).toBe("These are the first 40 motes.");
    expect(text("#upgrade-motes-for")).toMatch(/^For your gear \(the kit Equip now wears\): kit value now [\d,]+\.$/);
  });

  it("takes the weights of the request Equip now was made for", async () => {
    opened(WEIGHTED);
    type($("#upgrade-motes-n"), String(WEIGHTED.motes));
    await waitFor(() => expect(lines()).toHaveLength(WEIGHTED.motes));
    check(WEIGHTED);
  });

  it("goes the moment Equip now's kit goes, and says that it waits for the new one; the list that comes with the new kit is that kit's", async () => {
    const { panel } = opened();
    type($("#upgrade-motes-n"), "5");
    await waitFor(() => expect(lines()).toHaveLength(5));
    panel.setGear(null, true); // (the gear or the view changed: Equip now is being worked out again)
    expect(lines()).toEqual([]);
    expect($("#upgrade-motes-end").hidden).toBe(true);
    expect(text("#upgrade-motes-state")).toBe("Waiting for Equip now's kit for your gear…");
    panel.setGear(gearOf(cases[1]));
    await waitFor(() => expect(lines()).toHaveLength(5));
    expect(lines()).toEqual(cases[1].steps.slice(0, 5).map(lineOf));
    panel.setGear(null, false); // (the list was emptied)
    expect(lines()).toEqual([]);
    expect(text("#upgrade-motes-state")).toMatch(/^There is no kit from Equip now yet\. Add your gear above/);
  });

  it("does not draw what a run for a kit that has gone was still working at", async () => {
    const { panel } = mountPanel();
    let time = 0;
    vi.spyOn(window.performance, "now").mockImplementation(() => (time += 50));
    panel.setGear(gearOf(EQUIP));
    tickBox();
    await waitFor(() => expect(lines().length).toBeGreaterThan(2));
    panel.setGear(null, true);
    expect(lines()).toEqual([]);
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(lines(), "nothing of the run that was ended comes back").toEqual([]);
    panel.setGear(gearOf(cases[2]));
    await waitFor(() => expect(lines().length).toBeGreaterThan(2));
    expect(lines().slice(0, 2)).toEqual(cases[2].steps.slice(0, 2).map(lineOf));
  });

  it("has the visitor choose between the gear and the page's kit, and the choice stands when Equip now's kit comes or goes", async () => {
    const { panel } = opened();
    type($("#upgrade-motes-n"), "3");
    await waitFor(() => expect(lines()).toHaveLength(3));
    expect(text("#upgrade-motes-for")).toMatch(/^For your gear \(the kit Equip now wears\)/);
    choose("#upgrade-motes-source-page");
    await waitFor(() => expect(text("#upgrade-motes-for")).toMatch(/^For the best kit of this page/));
    await waitFor(() => expect(lines()).toEqual(BAKED.steps.slice(0, 3).map(lineOf)));
    panel.setGear(null, true); // (not the chosen source: the page's list stands)
    panel.setGear(gearOf(cases[1]));
    expect(lines()).toEqual(BAKED.steps.slice(0, 3).map(lineOf));
    choose("#upgrade-motes-source-gear");
    await waitFor(() => expect(lines()).toEqual(cases[1].steps.slice(0, 3).map(lineOf)));
  });

  it("says that there is no kit yet when the gear is chosen and Equip now has none", () => {
    mountPanel();
    tickBox();
    expect($("#upgrade-motes-source-page").checked).toBe(true); // (no kit: the page's kit is the first choice)
    choose("#upgrade-motes-source-gear");
    expect(text("#upgrade-motes-state")).toMatch(/^There is no kit from Equip now yet\./);
    expect(lines()).toEqual([]);
  });
});

describe("the answer hands Equip now's kit over", () => {
  it("tells the panel the kit (the request's view and weights, the kit as idents and the buffs) when Equip now is drawn, and takes it back at once when the gear or the view changes", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const onGear = vi.fn();
    const run = mountAnswer({ onGear });
    addByName("Tarn Signet", "4");
    await vi.advanceTimersByTimeAsync(700);
    expect(run.engine.runs).toHaveLength(1);
    const kit = kitOf({ 0: "w80301@4" });
    run.engine.runs[0].onStep({ ...equipStep({ kit }), buffs: [11, 12] });
    expect(onGear).toHaveBeenLastCalledWith({ request: expect.objectContaining({ scenario: expect.objectContaining({ race: "HUM", role: "tank", buffs: "own", evidence: "wiki", setup: "dw" }) }), kit, buffs: [11, 12] }, false);
    onGear.mockClear();
    addByName("Quillmark Bracer", "0"); // the gear changes: the kit that was drawn is old from this moment, before the pause is over
    expect(onGear).toHaveBeenCalledWith(null, true);
    expect(onGear.mock.calls.every(([source]) => source === null)).toBe(true);
    await vi.advanceTimersByTimeAsync(700);
    onGear.mockClear();
    run.setView({ role: "melee" }); // the view changes: the same
    expect(onGear).toHaveBeenLastCalledWith(null, true);
    onGear.mockClear();
    run.gear.clear(); // emptied: nothing is coming
    expect(onGear).toHaveBeenLastCalledWith(null, false);
  });

  it("hands the kit over again when a change is undone within the pause and the answer that was there stands", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const onGear = vi.fn();
    const run = mountAnswer({ onGear });
    addByName("Tarn Signet", "4");
    await vi.advanceTimersByTimeAsync(700);
    const kit = kitOf({ 0: "w80301@4" });
    run.engine.runs[0].onStep(equipStep({ kit }));
    run.engine.runs[0].finish({ kind: "scenario", mode: "farm-path", stopped: "no-gain", steps: 0, hasteAssumed: 30, elapsedMs: 5 });
    await vi.advanceTimersByTimeAsync(10);
    onGear.mockClear();
    run.setView({ role: "melee" });
    run.setView({ role: "tank" }); // (undone before the pause is over: the page opens on the Tank)
    expect(onGear).toHaveBeenLastCalledWith(null, true);
    await vi.advanceTimersByTimeAsync(700);
    expect(run.engine.runs).toHaveLength(1); // (the request is the one sent last: nothing is sent again)
    expect(onGear).toHaveBeenLastCalledWith({ request: expect.any(Object), kit, buffs: [] }, false);
  });
});

// ---- what a run is on the page, what the panel says of the buffs, and the faults found in review ----------------------------------------------

/** What the answer hands over for a recorded kit: the request it was made for, the kit as idents and the buffs (as in the tests of the gear). */
const gearOf = (row) => ({ request: { scenario: row.scenario, ...(row.weights === undefined ? {} : { weights: row.weights }) }, kit: row.kit, buffs: row.buffs });

describe("a run of motes on the page", () => {
  it("is one line that says how many motes it takes, and the motes spent so far are said from then on, so that the lines and the motes are both clear", async () => {
    const { panel } = mountPanel();
    panel.setGear(gearOf(OVERTAKE));
    tickBox();
    await waitFor(() => expect(lines()).toHaveLength(5));
    check(OVERTAKE);
    expect(lines()[0]).toMatch(/: .+ \+0 to \+6, 6 motes, \+\d/); // "Ear: <item> +0 to +6, 6 motes, +120"
    expect(lines()[1]).toMatch(/ \+6 to \+7, [+\d]/); // (one mote: no count)
    const facts = $$("#upgrade-motes-list > li").map((li) => factsOf(li).at(-1));
    expect(facts).toEqual(["6 motes so far", "7 motes so far", "8 motes so far", "9 motes so far", "10 motes so far"]);
    expect($("#upgrade-motes-list").tagName).toBe("OL"); // (the lines are numbered by the list: 1 to 5, and the motes are in the lines)
    expect(text("#upgrade-motes-end")).toBe("That is every mote there is to spend: every item is then at +10.");
  });

  it("is two motes for a damage that rises every second tier, line after line, with a head piece that gains at every tier first", async () => {
    const { panel, spoken } = mountPanel();
    panel.setGear(gearOf(PLATEAU));
    tickBox();
    await waitFor(() => expect(lines()).toHaveLength(PLATEAU.steps.length));
    check(PLATEAU);
    expect(PLATEAU.steps.some((step) => step.motes === 2)).toBe(true);
    expect(lines().filter((line) => / 2 motes, /.test(line))).toHaveLength(PLATEAU.steps.filter((step) => step.motes === 2).length);
    await waitFor(() => expect(spoken.at(-1)).toMatch(/^Spend your motes: 16 motes in 11 lines for your gear/));
  });

  it("takes a run only when the motes allow it: with eight motes the run of six and two more, with three none, and it says how long the run is that did not fit", async () => {
    const { panel } = mountPanel();
    panel.setGear(gearOf(OVERTAKE));
    tickBox();
    await waitFor(() => expect(lines()).toHaveLength(5));
    type($("#upgrade-motes-n"), "8");
    await waitFor(() => expect(lines()).toHaveLength(3));
    check(OVERTAKE_EIGHT);
    expect(text("#upgrade-motes-end")).toBe("These are the first 8 motes, in 3 lines.");
    type($("#upgrade-motes-n"), "3");
    await waitFor(() => expect(text("#upgrade-motes-end")).toBe("The next gain needs 6 motes on one item and only 3 are left, so the list stops here."));
    expect(lines()).toEqual([]);
    expect(OVERTAKE_THREE.steps).toEqual([]);
    type($("#upgrade-motes-n"), "6");
    await waitFor(() => expect(lines()).toHaveLength(1));
    expect(text("#upgrade-motes-end")).toBe("These are the first 6 motes, in 1 line.");
    type($("#upgrade-motes-n"), "");
    await waitFor(() => expect(lines()).toHaveLength(5));
  });

  it("is said in lines and motes, once, and the same words end the list as the announcement ends with", async () => {
    const { panel, spoken } = mountPanel();
    panel.setGear(gearOf(OVERTAKE));
    tickBox();
    await waitFor(() => expect(spoken).toHaveLength(1));
    expect(spoken[0]).toMatch(/^Spend your motes: 10 motes in 5 lines for your gear \(the kit Equip now wears\)\. First: .+ \+0 to \+6, 6 motes, .+\. That is every mote there is to spend: every item is then at \+10\.$/);
  });
});

describe("the buffs of the kit", () => {
  it("says, in plain words, that the order is worked out with the buffs this kit has now and holds them", async () => {
    mountPanel();
    expect(text("#upgrade-motes-buffs")).toBe("The order is worked out with the buffs this kit has now, and they stay as they are however the tiers change.");
  });

  it("says that the buffs may not be the best ones when the search for them ran out, for the page's kit, and says nothing when it did not", async () => {
    const tired = { ...EVALUATOR, bestBuffsOfKit: (view) => ({ ...bestBuffsOfKit(view), exact: false }) };
    mountPanel({ evaluator: tired });
    tickBox();
    await waitFor(() => expect(lines()).toHaveLength(120));
    expect($("#upgrade-motes-inexact").hidden).toBe(false);
    expect(text("#upgrade-motes-inexact")).toBe("The best buffs for this kit were not searched out completely, so they may not be the best ones.");
    expect(lines(), "the list is still made, with the buffs it found").toHaveLength(120);
    document.body.replaceChildren();
    mountPanel();
    tickBox();
    await waitFor(() => expect(lines()).toHaveLength(120));
    expect($("#upgrade-motes-inexact").hidden).toBe(true);
  });

  it("does not say it for the gear, whose buffs are Equip now's own, and drops it with the list", async () => {
    const tired = { ...EVALUATOR, bestBuffsOfKit: (view) => ({ ...bestBuffsOfKit(view), exact: false }) };
    const { panel } = mountPanel({ evaluator: tired });
    panel.setGear(gearOf(EQUIP));
    tickBox();
    type($("#upgrade-motes-n"), "4");
    await waitFor(() => expect(lines()).toHaveLength(4));
    expect($("#upgrade-motes-inexact").hidden).toBe(true);
    choose("#upgrade-motes-source-page");
    await waitFor(() => expect($("#upgrade-motes-inexact").hidden).toBe(false));
    panel.setGear(null, true);
    choose("#upgrade-motes-source-gear");
    await waitFor(() => expect($("#upgrade-motes-inexact").hidden).toBe(true));
  });
});

describe("what a review found in the panel", () => {
  /** A clock that makes every step end its slice, so that a run takes many turns. */
  const slowClock = () => {
    let time = 0;
    vi.spyOn(window.performance, "now").mockImplementation(() => (time += 50));
  };

  it("keeps the message about a number that is no number while a run goes on: the next slice does not wipe it", async () => {
    mountPanel();
    slowClock();
    tickBox();
    await waitFor(() => expect(lines().length).toBeGreaterThan(3));
    expect(lines().length).toBeLessThan(120);
    const box = $("#upgrade-motes-n");
    type(box, "0");
    expect(box.getAttribute("aria-invalid")).toBe("true");
    const during = lines().length;
    await waitFor(() => expect(lines().length).toBeGreaterThan(during + 3));
    expect(text("#upgrade-motes-bad"), "after more slices").toBe("Use a whole number of motes from 1, or leave the box empty.");
    expect($("#upgrade-motes-bad").hidden).toBe(false);
    expect(box.getAttribute("aria-invalid")).toBe("true");
    await waitFor(() => expect(lines()).toHaveLength(120), 15000);
    expect($("#upgrade-motes-bad").hidden, "and when the run is over").toBe(false);
    expect(box.getAttribute("aria-invalid")).toBe("true");
    type(box, "5");
    expect($("#upgrade-motes-bad").hidden).toBe(true);
  });

  it("keeps a run that failed failed: a number typed after the fault does not draw it as if it had ended, and Try again and the message stay", async () => {
    let breaks = true;
    const flaky = (...args) => {
      const walk = moteWalkOf(...args);
      let calls = 0;
      return { ...walk, step: () => (breaks && (calls += 1) === 4 ? (() => { throw new Error("it broke"); })() : walk.step()) };
    };
    mountPanel({ evaluator: { ...EVALUATOR, moteWalkOf: flaky } });
    tickBox();
    await waitFor(() => expect(text("#upgrade-motes-state")).toMatch(/^The order of motes could not be worked out here\./));
    const before = lines();
    expect($("#upgrade-motes-end").hidden).toBe(true);
    for (const typed of ["5", "50", "", "2"]) {
      type($("#upgrade-motes-n"), typed);
      expect(text("#upgrade-motes-state"), typed).toMatch(/^The order of motes could not be worked out here\./);
      expect($("#upgrade-motes-state button"), typed).not.toBeNull();
      expect($("#upgrade-motes-end").hidden, `${typed}: it does not claim that every item is at +10`).toBe(true);
      expect(text("#upgrade-motes-end")).toBe("");
      expect(lines(), typed).toEqual(before);
    }
    breaks = false;
    $("#upgrade-motes-state button").click(); // (Try again works it out again, for the number that is in the box)
    await waitFor(() => expect(lines()).toHaveLength(2));
    expect(text("#upgrade-motes-state")).toBe("");
  });

  it("keeps a run that could not even start failed when a number is typed", async () => {
    const run = open({ loadEvaluator: async () => Promise.reject(new Error("no")) });
    await run.app.whenIdle();
    await waitFor(() => expect($("#upgrade-motes")).not.toBeNull());
    tickBox();
    await waitFor(() => expect(text("#upgrade-motes-state")).toMatch(/^The order of motes could not be worked out here\./));
    type($("#upgrade-motes-n"), "7");
    expect(text("#upgrade-motes-state")).toMatch(/^The order of motes could not be worked out here\./);
    expect($("#upgrade-motes-end").hidden).toBe(true);
    expect(lines()).toEqual([]);
  });

  it("does not say a wrong number of motes for a panel that is shut, or one that has been cleared", async () => {
    const { spoken, setView } = mountPanel();
    tickBox();
    await waitFor(() => expect(lines()).toHaveLength(120));
    spoken.length = 0;
    type($("#upgrade-motes-n"), "0");
    tickBox(); // the panel is shut before the pause is over
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(spoken).toEqual([]);
    tickBox();
    await waitFor(() => expect(lines()).toHaveLength(120));
    spoken.length = 0;
    type($("#upgrade-motes-n"), "00");
    setView({ role: "melee" }); // the list is cleared before the pause is over
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(spoken.filter((said) => /whole number/.test(said))).toEqual([]);
  });

  it("lets go of everything when it is destroyed: the box, the choices and the number do nothing, and the view and the page's kit are not watched", async () => {
    const { panel, setView } = mountPanel();
    tickBox();
    await waitFor(() => expect(lines()).toHaveLength(120));
    panel.destroy();
    $("#upgrade-motes-n").dispatchEvent(new Event("input", { bubbles: true }));
    type($("#upgrade-motes-n"), "3");
    expect(lines(), "the number is not taken").toHaveLength(120);
    tickBox();
    expect($("#upgrade-motes").hidden, "the box is not heard").toBe(false);
    choose("#upgrade-motes-source-gear");
    expect(text("#upgrade-motes-state")).toBe("");
    setView({ role: "melee" });
    drawKit({ tier: 9 });
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(lines(), "the page's kit is not watched").toHaveLength(120);
    panel.setGear(gearOf(EQUIP));
    expect(lines()).toHaveLength(120);
  });

  it("announces only a list that the visitor asked for: not the one a change of the gear or the view starts again by itself, which would take the place of what the page and Equip now say", async () => {
    const { panel, spoken, setView } = mountPanel();
    panel.setGear(gearOf(EQUIP));
    tickBox(); // the visitor opens the panel: said
    type($("#upgrade-motes-n"), "6");
    await waitFor(() => expect(spoken.at(-1)).toMatch(/^Spend your motes: 6 motes/));
    const said = spoken.length;
    panel.setGear(null, true); // the gear changed: Equip now is worked out again...
    panel.setGear(gearOf(cases[1])); // ...and drawn: the list is made again, and not said (Equip now says its own)
    await waitFor(() => expect(lines()).toEqual(cases[1].steps.slice(0, 6).map(lineOf)));
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(spoken).toHaveLength(said);
    choose("#upgrade-motes-source-page"); // the visitor chooses the page's kit: said
    await waitFor(() => expect(spoken.at(-1)).toMatch(/^Spend your motes: 6 motes for the best kit of this page/));
    const again = spoken.length;
    setView({ role: "melee" }); // the view changed: the list is made again, and not said (the page says its own)
    await waitFor(() => expect($("#upgrade-motes-for").hidden).toBe(true));
    await waitFor(() => expect(lines()).toHaveLength(6));
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(spoken).toHaveLength(again);
    type($("#upgrade-motes-n"), "7"); // a number typed afterwards is the visitor's: said
    await waitFor(() => expect(spoken.at(-1)).toMatch(/^Spend your motes: 7 motes/));
  });
});
