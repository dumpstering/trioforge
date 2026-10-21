// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The answer of the Upgrade section as the page code runs it: the contract copy of the trio page with the code of the page (trio.js), the fake site of the engine tests (the
// manifest, the item table), the data files of the page's own views, and a stand-in for the optimizer's client. What the page code gives the section is checked here: the view the
// page shows (and its changes), the words of the kit, the address of the client's code and the page's notices. Every name is invented.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SECTION_UPDATED, initUpgrade } from "../pipeline/trioforge/site/static/ui/upgrade-input.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import { makeSite, siteFetch } from "./engine-site-fixture.mjs";
import { $, $$, mountPage } from "./upgrade-helpers.mjs";
import { CLIENT_URL, UPDATED_TEXT, addByName, ended, equipStep, fakeEngine, flush, kitOf, pathStep, textOf } from "./upgrade-answer-helpers.mjs";

const CONTRACT = resolve(dirname(fileURLToPath(import.meta.url)), "../fixtures/site/contract");
const shardFile = (name) => JSON.parse(readFileSync(resolve(CONTRACT, `data/${name}.json`), "utf8"));
const MAIN = "/engine-manifest.json";
const encode = (value) => new TextEncoder().encode(JSON.stringify(value));

afterEach(() => {
  document.body.innerHTML = "";
});

/** The page with its code started, a site that serves the manifest, the item table and the page's own views, and the stand-in for the optimizer. */
function open({ offline = [] } = {}) {
  mountPage();
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  const made = makeSite();
  made.files.set(MAIN, encode(made.manifestJson));
  const net = siteFetch(made);
  const engine = fakeEngine();
  const reload = vi.fn();
  const fetchImpl = async (url, init) => {
    const path = new URL(String(url), "https://trioforge.test").pathname;
    const view = /^\/data\/pal-mnk-ber\/(.+)\.json$/.exec(path);
    if (view === null) return net.fetchImpl(url, init);
    if (offline.includes(view[1])) throw new TypeError("Failed to fetch");
    return { ok: true, status: 200, json: async () => structuredClone(shardFile(view[1])) };
  };
  const app = initTrio({ document, window, fetch: fetchImpl, reload, loadEngine: engine.loadEngine });
  return { app, engine, reload, made };
}

/** The first use of the section: the code and the item list come, and the controls work. */
async function wake(t) {
  $("#upgrade-pick").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
  await t.app.whenIdle();
  expect(t.app.upgrade?.gear).toBeTruthy();
}
const sent = (t, count) => vi.waitFor(() => expect(t.engine.runs).toHaveLength(count), { timeout: 4000, interval: 10 });
const checked = (name) => document.querySelector(`input[name="${name}"]:checked`).value;
const pageView = () => ({ race: $("#sw-race").value, role: checked("role"), buffs: checked("buffs"), evidence: document.getElementById("main").dataset.ev, setup: checked("setup") }); // (the one evidence level the page is made from)

describe("the section on the page", () => {
  it("sends the view the page shows, for the trio and the level the page is for, to the client named by the manifest, with the results area of the section for its question", async () => {
    const t = open();
    await wake(t);
    addByName("larkspur", "4");
    await sent(t, 1);
    const { request } = t.engine.runs[0];
    expect(request).toMatchObject({ v: 1, kind: "scenario", mode: "farm-path", trio: "pal-mnk-ber", level: 50, owned: [["w8091@4", 1]], scenario: pageView() });
    expect(pageView()).toMatchObject({ race: "OGR", setup: "dw" });
    expect(t.engine.loaded).toEqual([CLIENT_URL]);
    expect(t.engine.options[0].mount.closest("#upgrade-results")).not.toBeNull();
    expect(t.engine.options[0].window).toBe(window);
  });

  it("restarts the path when a switch changes the view the page shows: the race, the role, the weapons and the buffs", async () => {
    const t = open();
    await wake(t);
    addByName("larkspur", "4");
    await sent(t, 1);
    const pick = async (selector, count) => {
      const input = $(selector);
      input.checked = true;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await t.app.whenIdle();
      await sent(t, count);
      expect(t.engine.runs[count - 1].request.scenario).toEqual(pageView());
    };
    await pick('input[name="role"][value="tank"]', 2);
    expect(t.engine.runs[1].request.scenario.role).toBe("tank");
    await pick('input[name="buffs"][value="group"]', 3);
    expect(t.engine.runs[2].request.scenario).toMatchObject({ role: "tank", buffs: "group" });
    expect(t.engine.runs[2].request.scenario.evidence).toBe("strict"); // (no switch moves the evidence level: the page asks at the level it is made from)
    const race = $("#sw-race");
    race.value = [...race.options].find((o) => o.value !== race.value).value;
    race.dispatchEvent(new Event("change", { bubbles: true }));
    await t.app.whenIdle();
    await sent(t, 4);
    expect(t.engine.runs[3].request.scenario.race).toBe(race.value);
    const offered = [...document.querySelectorAll('input[name="setup"]')].filter((r) => !r.disabled && !r.checked);
    expect(offered.length).toBeGreaterThan(0);
    await pick(`input[name="setup"][value="${offered[0].value}"]`, 5);
    expect(t.engine.runs[4].request.scenario.setup).toBe(offered[0].value);
  }, 30_000);

  it("does not restart for a switch the request does not use (the tier), nor for a view that could not be loaded", async () => {
    const t = open({ offline: ["strict-group"] });
    await wake(t);
    addByName("larkspur", "4");
    await sent(t, 1);
    const tier = $("#sw-tier");
    tier.value = "10";
    tier.dispatchEvent(new Event("change", { bubbles: true }));
    await t.app.whenIdle();
    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(t.engine.runs).toHaveLength(1);
    // (the view of other buffs is not there: the page goes back to what it shows, and the answer stays as it was)
    $('input[name="buffs"][value="group"]').checked = true;
    $('input[name="buffs"][value="group"]').dispatchEvent(new Event("change", { bubbles: true }));
    await t.app.whenIdle();
    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(t.engine.runs).toHaveLength(1);
  }, 30_000); // (2.4 s when the machine is idle, with two waits of 0.8 s in it: past the 5 s of the default when it is busy)

  it("names the places of the kit as the page's kit table does, and tiers as the page writes them", async () => {
    const t = open();
    await wake(t);
    addByName("larkspur", "4");
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 5: "w8091@4" }) }));
    const slots = $$("#upgrade-equip tbody th").map((th) => th.textContent);
    expect(slots).toEqual($$("#kit-body tr th").map((th) => th.textContent));
    const row = (n) => $$(`#upgrade-equip tbody tr:nth-child(${n}) > *`).map((cell) => cell.textContent.trim());
    expect(row(6)).toEqual(["Shoulders", "Larkspur Pauldrons +4"]);
    expect(row(1)).toEqual(["Head", "Leave empty"]);
  });

  it("says what it has to say through the page's own live region, and the page still has two live regions", async () => {
    const t = open();
    await wake(t);
    addByName("larkspur", "4");
    await sent(t, 1);
    $("#announce").textContent = "";
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 5: "w8091@4" }) }));
    expect($("#announce").textContent).toBe("");
    t.engine.runs[0].onStep(pathStep(1, { ident: "w90013@4", gain: 321 }));
    expect($("#announce").textContent).toBe("Equip now is ready: 1 of 22 places filled. Next step: Get Pauldrons of the Vanguard +4, gain +321.");
    t.engine.runs[0].finish(ended("no-gain", 1));
    await flush();
    expect($("#announce").textContent).toBe("1 step.");
    expect($$('[role="status"], [aria-live]').map((node) => node.id)).toEqual(["status", "announce"]);
    expect($$('#upgrade [role="status"], #upgrade [role="alert"], #upgrade [role="log"], #upgrade [aria-live]')).toHaveLength(0);
  });

  it("shows the page's notice and the section's own line, each with Reload, when the optimizer says the site was released again", async () => {
    const t = open();
    await wake(t);
    addByName("larkspur", "4");
    await sent(t, 1);
    t.engine.updated = true;
    t.engine.runs[0].fail(Object.assign(new Error(UPDATED_TEXT), { code: "engine-load" }));
    await flush();
    expect(textOf("#status .status-text")).toBe("Data updated, reload the page to see the new data.");
    expect(textOf("#upgrade-fault .status-text")).toBe("Data updated, reload the page to see this section.");
    $("#upgrade-fault button").click();
    expect(t.reload).toHaveBeenCalledTimes(1);
    $("#status button").click();
    expect(t.reload).toHaveBeenCalledTimes(2);
  });

  it("stops the path and clears the results when Clear is used, and sends nothing for the empty list", async () => {
    const t = open();
    await wake(t);
    addByName("larkspur", "4");
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 5: "w8091@4" }) }));
    $("#upgrade-clear").click();
    expect(t.engine.log.at(-1)).toBe("stop");
    expect($("#upgrade-equip").hidden).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(t.engine.runs).toHaveLength(1);
  });

  it("draws the answer for a file that was dropped before the code of the section had come", async () => {
    const t = open();
    const text = readFileSync(resolve(CONTRACT, "../../dumps/site-small.txt"), "latin1").split("\r\n").join("\n").split("\n").join("\r\n");
    const file = new File([text], "inventory.txt");
    const event = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: { files: [file], types: ["Files"], dropEffect: "none" } });
    $("#upgrade-drop").dispatchEvent(event);
    await vi.waitFor(() => expect(t.app.upgrade?.gear).toBeTruthy(), { timeout: 4000 });
    await sent(t, 1);
    expect(t.engine.runs[0].request.owned.length).toBe(12);
  });
});

describe("the expanders on the page", () => {
  it("are worded with the page's own words: the options of the tier mode are the tiers as the page writes them, and the arrival tiers as it writes the Arrives-at column", async () => {
    const t = open();
    await wake(t);
    addByName("larkspur", "4");
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 5: "w8091@4" }) }));
    expect($("#upgrade-more").hidden).toBe(false);
    expect($$("#upgrade-mode-d option").map((o) => o.textContent)).toEqual(["+0", "+1", "+2", "+3", "+4"]);
    expect($$("#upgrade-mode-n option").map((o) => o.textContent)).toEqual(["+0", "+1", "+2", "+3", "+4", "+5", "+6", "+7", "+8", "+9", "+10"]);
    expect($("#upgrade-mode > summary").textContent).toBe("Tier mode: Ready +4");
    expect($$("#upgrade-results [role], #upgrade-results [aria-live]"), "and the page still has the two live regions it had").toHaveLength(0);
    expect($$('[role="status"], [aria-live]').map((node) => node.id)).toEqual(["status", "announce"]);
  });

  it("restart the path when the tier mode is chosen, with the view the page shows, and ask for the sets with it once the path has ended", async () => {
    const t = open();
    await wake(t);
    addByName("larkspur", "4");
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 5: "w8091@4" }) }));
    $("#upgrade-mode-fixed").click();
    await sent(t, 2);
    expect(t.engine.runs[1].request).toMatchObject({ mode: "farm-path", tierMode: { mode: "fixed", N: 4 }, scenario: pageView() });
    t.engine.runs[1].onStep(equipStep({ kit: kitOf({ 5: "w8091@4" }) }));
    t.engine.runs[1].finish(ended("no-gain", 0));
    $("#upgrade-sets > summary").click();
    await sent(t, 3);
    expect(t.engine.runs[2].request).toMatchObject({ mode: "best-sets", k: 2, tierMode: { mode: "fixed", N: 4 }, scenario: pageView(), trio: "pal-mnk-ber", level: 50 });
  });
});

describe("the section started without the page", () => {
  it("has the gear input and no answer when the page gives it no view, and leaves the place for the answer empty", async () => {
    const root = mountPage();
    const made = makeSite();
    made.files.set(MAIN, encode(made.manifestJson));
    const upgrade = initUpgrade(root, { doc: document, win: window, fetch: siteFetch(made).fetchImpl, release: null });
    await upgrade.ready();
    expect(upgrade.gear).not.toBeNull();
    expect(upgrade.answer).toBeNull();
    expect($("#upgrade-results").children).toHaveLength(0);
  });

  it("keeps the gear input working when the answer cannot be set up: the list is not lost with it", async () => {
    const root = mountPage();
    const made = makeSite();
    made.files.set(MAIN, encode(made.manifestJson));
    const upgrade = initUpgrade(root, {
      doc: document,
      win: window,
      fetch: siteFetch(made).fetchImpl,
      release: null,
      view: () => ({}),
      words: {},
      onView: () => {
        throw new Error("the page cannot say when its view changes");
      },
    });
    await upgrade.ready();
    expect(upgrade.gear).not.toBeNull();
    expect(upgrade.answer).toBeNull();
    expect(textOf("#upgrade-load"), "no complaint about the item list: it loaded").toBe("");
    expect($("#upgrade-add").disabled).toBe(false);
    addByName("larkspur", "4");
    expect(upgrade.gear.owned()).toEqual([{ key: "w8091", tier: 4, count: 1, locations: [] }]);
  });

  it("leaves nothing listening when the answer cannot be set up: the list asks for no optimizer and draws nothing, and the place for the answer is empty", async () => {
    const root = mountPage();
    const made = makeSite();
    made.files.set(MAIN, encode(made.manifestJson));
    const engine = fakeEngine();
    const upgrade = initUpgrade(root, {
      doc: document,
      win: window,
      fetch: siteFetch(made).fetchImpl,
      release: null,
      loadEngine: engine.loadEngine,
      view: () => ({ race: "OGR", role: "balanced", buffs: "own", evidence: "strict", setup: "dw" }),
      words: {},
      onView: () => {
        throw new Error("the page cannot say when its view changes");
      },
    });
    await upgrade.ready();
    expect(upgrade.answer).toBeNull();
    addByName("larkspur", "4");
    await new Promise((resolve) => setTimeout(resolve, 900)); // (longer than the pause before a request)
    expect(engine.loaded, "the optimizer's code was not asked for").toEqual([]);
    expect(engine.runs).toEqual([]);
    expect($("#upgrade-results").children, "nothing of a half-made answer is left in its place").toHaveLength(0);
  });

  it("still says what it says in its own place when the data is of another release, in the words the answer uses too", () => {
    expect(SECTION_UPDATED).toBe("Data updated, reload the page to see this section.");
  });
});
