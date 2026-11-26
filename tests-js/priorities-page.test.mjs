// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The priorities of the trio page as the page code runs them: the contract copy of the trio page with the page script (trio.js, and priorities.js, which draws the control), the chunk it loads
// when a step is chosen (ui/weights.js with ui/priority-weights.js), the fake site of the engine tests (the manifests, the bundle of the trio, the item table and the evaluator's script) and a
// stand-in for the optimizer's client that the test drives. The weights the page sends are worked out here from the bundle's own file, never by the page's code.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import { ratesOfKit } from "../pipeline/trioforge/site/static/engine/kitvalue.js";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { ratesText } from "../pipeline/trioforge/site/static/ui/priority-weights.js";
import { BUNDLE_BYTES, makeSite, sha256, siteFetch } from "./engine-site-fixture.mjs";
import { REFERENCE } from "./best-kit-harness.mjs";
import { $, $$, mountPage } from "./upgrade-helpers.mjs";
import { fakeEngine } from "./upgrade-answer-helpers.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CONTRACT = resolve(ROOT, "fixtures/site/contract");
const shardFile = (name) => JSON.parse(readFileSync(resolve(CONTRACT, `data/${name}.json`), "utf8"));
const ITEMS_DOCUMENT = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/results/items.json"), "utf8"));
const BUNDLE = JSON.parse(BUNDLE_BYTES.toString("utf8"));
const OWN = (role) => BUNDLE.roles[role].weights;
const MAIN = "/engine-manifest.json";
const EVALUATOR = "/assets/engine/kitvalue-AAAAAAAA.js";
const encode = (value) => new TextEncoder().encode(JSON.stringify(value));
const SCRIPT = new TextEncoder().encode("// the evaluator of the tests: the module the page imports is the engine's own file\n");
const NOTICE = "Your priorities: re-solved in your browser; no runner-ups or robustness labels for this kit";
const HEADING = "Solved for your settings";
const BAD = "The priorities in the address do not fit this page, so every step is Normal.";
const ALL_OFF = "Every priority is off: nothing to optimise. Raise one, or Reset.";
const UPDATED = "Data updated, reload the page to see the new data.";
const NOT_COUNTED = "not counted in this build";
/** A site whose bundle of the trio is changed by `mutate` (the manifest of the trio lists the changed bundle with its own size and SHA-256). */
const siteWith = (mutate) => {
  const doc = structuredClone(BUNDLE);
  mutate(doc);
  return makeSite({ bundles: { "pal-mnk-ber": { 50: new TextEncoder().encode(JSON.stringify(doc)) } } });
};
/** The melee role of this bundle gives haste and mana no weight, as a caster gives haste none and a trio with no mana pool gives mana none. */
const meleeWeighsNoHasteNoMana = (doc) => {
  doc.roles.melee.weights.HASTE = 0;
  doc.roles.melee.weights.MANA = 0;
  doc.roles.melee.weights.MANAREG = 0;
};
const focusControl = () => $("#prio-ac").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
const setAll = (character) => {
  for (const id of ORDER) $(`#prio-${id}`).value = character;
};
/** The reference's view of the Ogre, tank, own buffs, wiki evidence, dual wield at +4, with armor class x2 (Python's answer): the weights of "armor class High" are the same weights. */
const [AC2] = REFERENCE.cases;
const ORDER = ["hp", "ac", "mana", "atk", "dex", "haste", "resists", "end"];
const at = (steps) => ORDER.map((id) => steps[id] ?? "n").join("");

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

/** The page with its code started, a site that serves the manifests, the bundle, the item table and the evaluator, the page's own views, and the stand-in for the optimizer. */
function open({ search = "", offline = [], engine = fakeEngine(), site = makeSite(), bundleFails = false, footer = "", loadWeights, shardRelease = null, ruleOfTank = null } = {}) {
  mountPage(footer);
  document.getElementById("main").dataset.ev = "wiki";
  if (ruleOfTank !== null) Object.assign(document.querySelector('input[name="role"][value="tank"]').dataset, { rule: ruleOfTank.rule, ruleTitle: ruleOfTank.title }); // (a build that cites a rule of its own)
  window.history.replaceState(null, "", `/trio/pal-mnk-ber/${search}`);
  site.manifestJson.kitvalue = { path: EVALUATOR, bytes: SCRIPT.length, gzip: SCRIPT.length, sha256: sha256(SCRIPT) };
  site.files.set(MAIN, encode(site.manifestJson));
  site.files.set(EVALUATOR, SCRIPT);
  const net = siteFetch(site, {
    serve: (url) => {
      if (bundleFails && url.includes("/engine/data/pal-mnk-ber-")) return new Response("no", { status: 500 });
      if (url.endsWith(EVALUATOR)) return new Response(site.files.get(EVALUATOR), { status: 200, headers: { "content-type": "text/javascript" } });
      return undefined;
    },
  });
  engine.consent = "granted";
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(String(url));
    const path = new URL(String(url), "https://trioforge.test").pathname;
    const view = /^\/data\/pal-mnk-ber\/(.+)\.json$/.exec(path);
    if (view === null) return net.fetchImpl(url, init);
    if (offline.includes(view[1])) throw new TypeError("Failed to fetch");
    const doc = structuredClone(shardFile(view[1]));
    if (shardRelease !== null) doc.release = shardRelease; // (a shard of the data released after the page was made)
    return { ok: true, status: 200, json: async () => doc };
  };
  const loadEngine = async (url) => (String(url).endsWith(EVALUATOR) ? import("../pipeline/trioforge/site/static/engine/kitvalue.js") : engine.loadEngine(url));
  const reload = vi.fn();
  const app = initTrio({ document, window, fetch: fetchImpl, reload, loadEngine, ...(loadWeights === undefined ? {} : { loadWeights }) });
  return { app, engine, site, net, calls, reload };
}

const ANNOUNCED = [];
let observer = null;
beforeEach(() => {
  ANNOUNCED.length = 0;
});
function listen() {
  observer?.disconnect();
  const live = $("#announce");
  observer = new MutationObserver(() => {
    if (live.textContent !== "") ANNOUNCED.push(live.textContent);
  });
  observer.observe(live, { childList: true, characterData: true, subtree: true });
}

const change = (element) => element.dispatchEvent(new Event("change", { bubbles: true }));
function pick(id, value) {
  const select = $(`#prio-${id}`);
  select.value = value;
  change(select);
  return select;
}
function choose(selector) {
  const input = $(selector);
  input.checked = true;
  change(input);
}
const tick = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sent = (t, count) => vi.waitFor(() => expect(t.engine.runs).toHaveLength(count), { timeout: 4000, interval: 10 });
const text = (selector) => ($(selector)?.textContent ?? "").replace(/\s+/g, " ").trim();
const query = () => Object.fromEntries(new URLSearchParams(window.location.search));
const shown = () => ORDER.map((id) => $(`#prio-${id}`).value).join("");
const rowNames = () => $$("#kit-body tr").map((tr) => tr.querySelector('[data-f="name"]').textContent);
const result = (c = AC2, over = {}) => ({ kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null, F: c.F, value: c.value, kit: [...c.kit], buffs: [...c.buffs], hasteAssumed: c.hasteAssumed, elapsedMs: 12, ...over });
function shardNames(file, race, role, tier, setup) {
  const doc = shardFile(file);
  const row = doc.rows.find((r) => r[0] === race && r[1] === role && r[2] === tier && r[3] === setup);
  return doc.kits[row[4]].map((index) => (index < 0 ? "Leave empty" : doc.items[index][1]));
}
/** The reference's view on the page: the page is made from the wiki level, so a change event on the buffs it already has makes it read the wiki view. */
async function wikiView(t) {
  choose("#buffs-own");
  await t.app.whenIdle();
}

// ---- the control in the page -----------------------------------------------------------------------------------------------------------------------------

describe("the control in the page", () => {
  it("is drawn by the page script at its start, after the choices it sits beside, with every step Normal, and asks for nothing: no chunk, no data, no optimizer", async () => {
    const t = open();
    await t.app.whenIdle();
    const box = $(".controls > fieldset#prio");
    expect(box).not.toBeNull();
    expect($(".controls").lastElementChild).toBe(box);
    expect($$("#prio select")).toHaveLength(8);
    expect(shown()).toBe("nnnnnnnn");
    expect($(".controls").hasAttribute("data-prio")).toBe(true);
    expect(t.calls.filter((url) => !url.startsWith("/data/pal-mnk-ber/"))).toEqual([]);
    expect(t.engine.loaded).toEqual([]);
    expect($("#prio-reset").disabled).toBe(true);
    expect(query(), "the address of a page nobody changed is the address it had").toEqual({});
  });

  it("leaves the page as it was made for an address that has no priorities or all of them Normal: the precomputed answer, no chunk", async () => {
    for (const search of ["", "?p=nnnnnnnn", "?race=OGR&role=tank&tier=4&buffs=own&p=nnnnnnnn"]) {
      const t = open({ search });
      await t.app.whenIdle();
      expect(t.calls.filter((url) => !url.startsWith("/data/pal-mnk-ber/")), search).toEqual([]);
      expect(text("#solve"), search).toBe("");
      expect(shown()).toBe("nnnnnnnn");
      expect(rowNames(), search).toEqual(shardNames("strict-own", "OGR", "tank", 4, "dw"));
      document.body.innerHTML = "";
    }
  });

  it("writes an address that says every step Normal without it: p=nnnnnnnn is what the page makes of no p, and the address is the page's own form", async () => {
    for (const search of ["?p=nnnnnnnn", "?race=OGR&role=tank&tier=4&buffs=own&p=nnnnnnnn", "?tier=4&p=nnnnnnnn&buffs=own"]) {
      const t = open({ search });
      await t.app.whenIdle();
      expect(window.location.search, search).toBe("?race=OGR&role=tank&tier=4&buffs=own");
      expect(text("#status"), "nothing is wrong with it, and nothing is said").toBe("");
      document.body.innerHTML = "";
    }
    const plain = open({ search: "" });
    await plain.app.whenIdle();
    expect(window.location.search, "an address with no p is as it was").toBe("");
  });
});

// ---- the address -----------------------------------------------------------------------------------------------------------------------------------------

describe("the address parameter p", () => {
  it("is written for a choice, one character for each stat in the fixed order, after the page's own parameters, and left out when every step is Normal", async () => {
    const t = open();
    await wikiView(t);
    pick("ac", "t");
    await t.app.whenIdle();
    expect(query()).toEqual({ race: "OGR", role: "tank", tier: "4", buffs: "own", p: "ntnnnnnn" });
    pick("end", "0");
    await t.app.whenIdle();
    expect(query().p).toBe("ntnnnnn0");
    expect(window.location.search).toBe("?race=OGR&role=tank&tier=4&buffs=own&p=ntnnnnn0");
    pick("ac", "n");
    pick("end", "n");
    await t.app.whenIdle();
    expect(query()).toEqual({ race: "OGR", role: "tank", tier: "4", buffs: "own" });
  });

  it("is read from the address: the steps are chosen, the optimizer is asked for the kit of those steps, and the address keeps what it had", async () => {
    const t = open({ search: "?p=0lnht0ln" });
    await sent(t, 1);
    expect(shown()).toBe("0lnht0ln");
    expect(query().p).toBe("0lnht0ln");
    expect($("#prio-reset").disabled).toBe(false);
  });

  it("is carried with the sliders' w when both are set, and a link that has both opens the page with both", async () => {
    const t = open();
    await wikiView(t);
    $("#assume-weights").open = true;
    $("#assume-weights").dispatchEvent(new Event("toggle"));
    await t.app.whenIdle();
    choose("#w-0-2");
    await t.app.whenIdle();
    pick("hp", "h");
    await t.app.whenIdle();
    expect(query()).toMatchObject({ w: "21111", p: "hnnnnnnn" });
    document.body.innerHTML = "";
    const again = open({ search: window.location.search });
    await sent(again, 1);
    expect(shown()).toBe("hnnnnnnn");
    expect(again.engine.runs[0].request.weights).toEqual({ multipliers: { AC: 2 }, custom: { HP: OWN("tank").HP * 2 } });
  });

  it("ignores a value that is not one it can take, whole, says so, and writes the address without it: every step Normal and the precomputed answer", async () => {
    for (const bad of ["nnnnnnn", "nnnnnnnnn", "nnnnnnnx", "NNNNNNNN", "", "12345678", "nhnnnnn%20"]) {
      const t = open({ search: `?p=${bad}` });
      await t.app.whenIdle();
      expect(shown(), bad).toBe("nnnnnnnn");
      expect(text("#status"), bad).toContain(BAD);
      expect(query(), bad).not.toHaveProperty("p");
      expect(t.engine.runs, bad).toHaveLength(0);
      expect(text("#solve"), bad).toBe("");
      document.body.innerHTML = "";
    }
  });

  it("ignores a p that is given twice, as it does a w: which of the two? And the rest of the address is kept", async () => {
    const t = open({ search: "?p=nhnnnnnn&p=nnhnnnnn&tier=10" });
    await t.app.whenIdle();
    expect(shown()).toBe("nnnnnnnn");
    expect(text("#status")).toContain(BAD);
    expect(query()).toMatchObject({ tier: "10", buffs: "own" });
    expect(query()).not.toHaveProperty("p");
  });

  it("does not touch an address that has none: the addresses of the older links are as they were, byte for byte", async () => {
    for (const search of ["?race=OGR&role=tank&tier=10&buffs=own", "?race=TRL&role=melee&tier=4&setup=dw&buffs=group", "?race=OGR&role=tank&tier=4&buffs=own&w=2111h"]) {
      const t = open({ search });
      await t.app.whenIdle();
      expect(window.location.search, "the address the page rewrites is the one it was given").toBe(search);
      expect(new URLSearchParams(window.location.search).has("p"), search).toBe(false);
      document.body.innerHTML = "";
    }
  });
});

// ---- the request -----------------------------------------------------------------------------------------------------------------------------------------

describe("the request for the kit of a choice", () => {
  it("carries each stat's own weight in the role times its step as custom weights, and nothing else: armor class High is the role's armor class weight twice", async () => {
    const t = open();
    await wikiView(t);
    pick("ac", "h");
    await sent(t, 1);
    expect(t.engine.runs[0].request).toEqual({
      v: 1,
      kind: "scenario",
      trio: "pal-mnk-ber",
      level: 50,
      mode: "best-kit",
      scenario: { race: "OGR", role: "tank", buffs: "own", evidence: "wiki", setup: "1h-shield" },
      tier: 4,
      weights: { custom: { AC: OWN("tank").AC * 2 } },
      budgetMs: 60_000,
    });
  });

  it("is made of the weights of the role the page shows: another role, other weights", async () => {
    const t = open();
    await wikiView(t);
    choose("#role-tank");
    await t.app.whenIdle();
    pick("ac", "t");
    pick("resists", "0");
    await sent(t, 1);
    const school = { SV_FIRE: 0, SV_COLD: 0, SV_MAGIC: 0, SV_POISON: 0, SV_DISEASE: 0 };
    expect(t.engine.runs[0].request.weights).toEqual({ custom: { AC: OWN("tank").AC * 4, ...school } });
    expect(t.engine.runs[0].request.scenario.role).toBe("tank");
  });

  it("sets every stat that is not Normal, with the step's number, and no stat that is", async () => {
    const t = open();
    await wikiView(t);
    for (const [id, step] of [["hp", "0"], ["mana", "l"], ["atk", "h"], ["dex", "t"], ["haste", "h"], ["end", "l"]]) pick(id, step);
    await sent(t, 1);
    const own = OWN("tank");
    expect(t.engine.runs[0].request.weights).toEqual({ custom: { HP: 0, MANA: own.MANA * 0.5, ATK: own.ATK * 2, DEX: own.DEX * 4, HASTE: own.HASTE * 2, END: own.END * 0.5 } });
  });

  it("has the sliders' multipliers beside the custom weights, and the buffs and weapons the page shows", async () => {
    const t = open();
    await wikiView(t);
    $("#assume-weights").open = true;
    $("#assume-weights").dispatchEvent(new Event("toggle"));
    await t.app.whenIdle();
    choose("#buffs-group");
    await t.app.whenIdle();
    choose("#w-3-h");
    pick("hp", "t");
    await sent(t, 1);
    expect(t.engine.runs[0].request.weights).toEqual({ multipliers: { SV: 0.5 }, custom: { HP: OWN("tank").HP * 4 } });
    expect(t.engine.runs[0].request.scenario.buffs).toBe("group");
  });

  it("is in the view the Upgrade section is given as well, once the role's own weights are read: the same custom weights, with the sliders' multipliers", async () => {
    const t = open();
    await wikiView(t);
    expect(t.app.weightsTable("11111", "nhnnnnnn", "tank"), "before the weights of the role are read the table has no weights of the choice").toBeNull();
    pick("ac", "h");
    await sent(t, 1);
    expect(t.app.weightsTable("11111", "nhnnnnnn", "tank")).toEqual({ custom: { AC: OWN("tank").AC * 2 } });
    expect(t.app.weightsTable("2h111", "nhnnnnnn", "tank")).toEqual({ multipliers: { AC: 2, MANA: 0.5 }, custom: { AC: OWN("tank").AC * 2 } });
    expect(t.app.weightsTable("11111", "nnnnnnnn", "tank")).toBeNull();
    expect(t.app.weightsTable("21111", "nnnnnnnn", "tank")).toEqual({ multipliers: { AC: 2 } });
  });

  it("is not sent for a stat put back to Normal: all Normal is the shards' answer again", async () => {
    const t = open();
    await wikiView(t);
    pick("ac", "t");
    await sent(t, 1);
    pick("ac", "n");
    await t.app.whenIdle();
    expect(t.engine.runs).toHaveLength(1);
    expect($("#solve").hidden).toBe(true);
  });

  it("is made after the pause, once, for the last step of a run of changes, as a slider's is", async () => {
    const t = open();
    await wikiView(t);
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    pick("ac", "l");
    await vi.advanceTimersByTimeAsync(100);
    pick("ac", "h");
    await vi.advanceTimersByTimeAsync(100);
    pick("ac", "t");
    await vi.advanceTimersByTimeAsync(5000);
    expect(t.engine.runs).toHaveLength(1);
    expect(t.engine.runs[0].request.weights).toEqual({ custom: { AC: OWN("tank").AC * 4 } });
  });

  it("asks nothing of the bundle or the chunk until the control is touched: a page nobody uses the priorities on has nothing more to fetch", async () => {
    const t = open();
    await wikiView(t);
    choose("#role-tank");
    await t.app.whenIdle();
    $("#sw-tier").value = "10";
    change($("#sw-tier"));
    await t.app.whenIdle();
    expect(t.net.asked.filter((url) => url.includes("/engine/data/") || url.includes("/engine-trios/") || url.includes("engine-manifest"))).toEqual([]);
  });

  it("asks nothing of the bundle until a step is not Normal, and then reads the weights of the role from the bundle the manifest lists, checked by its SHA-256", async () => {
    const t = open();
    await wikiView(t);
    expect(t.net.asked.filter((url) => url.includes("/engine/data/"))).toEqual([]);
    pick("ac", "h");
    await sent(t, 1);
    expect(t.net.asked.filter((url) => url.includes("pal-mnk-ber-l50"))).toHaveLength(1);
    expect(t.net.asked.filter((url) => url.endsWith("/engine-trios/pal-mnk-ber.json"))).toHaveLength(1);
  });
});

// ---- the answer ------------------------------------------------------------------------------------------------------------------------------------------

describe("the answer for a choice", () => {
  it("says in one line near the kit that it is the browser's own and has no runner-ups or robustness labels, with a Reset, and draws the optimizer's kit in place of the shard's", async () => {
    const t = open();
    await wikiView(t);
    listen();
    pick("ac", "h");
    await sent(t, 1);
    expect(text("#solve")).toContain(NOTICE);
    expect($("#solve .solve-prio").previousElementSibling, "first in the answer area, which comes right after the heading of the kit").toBeNull();
    expect($("#solve").previousElementSibling.id).toBe("wear-h");
    expect($("#solve-prio-reset").textContent).toBe("Reset");
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(rowNames()).toEqual(AC2.kit.map((ident) => (ident === null ? "Leave empty" : ITEMS_DOCUMENT.items.find((record) => (record.key ?? `w${record.id}`) === ident.split("@")[0]).name)));
    expect(text("#solve")).toContain(NOTICE);
    expect(ANNOUNCED.at(-1)).toMatch(/^Priorities armor class High\. Solved for your settings\. Showing /);
  });

  it("is said for the choice and for no other: the note is gone when every step is Normal again, and the kit is the shard's", async () => {
    const t = open();
    await wikiView(t);
    const first = rowNames();
    pick("ac", "h");
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    pick("ac", "n");
    await t.app.whenIdle();
    expect($("#solve").hidden).toBe(true);
    expect($("#solve .solve-prio").hidden).toBe(true);
    expect(text("#solve")).not.toContain("Your priorities");
    expect(rowNames()).toEqual(first);
    expect(rowNames()).toEqual(shardNames("wiki-own", "OGR", "tank", 4, "1h-shield"));
  });

  it("is reset by the Reset of the note: every step Normal, the address without p, the precomputed kit, and the focus on the heading of the kit", async () => {
    const t = open();
    await wikiView(t);
    pick("ac", "t");
    pick("haste", "0");
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    $("#solve-prio-reset").focus();
    $("#solve-prio-reset").click();
    await t.app.whenIdle();
    expect(shown()).toBe("nnnnnnnn");
    expect(query()).not.toHaveProperty("p");
    expect(rowNames()).toEqual(shardNames("wiki-own", "OGR", "tank", 4, "1h-shield"));
    expect($("#solve").hidden).toBe(true);
    expect(document.activeElement.id).toBe("wear-h");
  });

  it("is reset by the Reset of the control as well, and by Back to the precomputed answer, which goes back to every default", async () => {
    const t = open();
    await wikiView(t);
    pick("dex", "h");
    await sent(t, 1);
    $("#prio-reset").click();
    await t.app.whenIdle();
    expect(shown()).toBe("nnnnnnnn");
    expect(query()).not.toHaveProperty("p");
    pick("dex", "h");
    await sent(t, 2);
    t.engine.runs[1].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    const back = [...$$("#solve button")].find((button) => button.textContent === "Back to the precomputed answer");
    back.click();
    await t.app.whenIdle();
    expect(shown()).toBe("nnnnnnnn");
    expect(query()).not.toHaveProperty("p");
  });

  it("takes the note away when the kit shown is the precomputed one after all: Stop, and a fault, and brings it back with Try again", async () => {
    const t = open();
    await wikiView(t);
    pick("ac", "h");
    await sent(t, 1);
    expect($(".solve-prio").hidden).toBe(false);
    const stop = [...$$("#solve button")].find((button) => button.textContent === "Stop");
    stop.click();
    expect($(".solve-prio").hidden, "stopped: the table shows the shard's kit").toBe(true);
    expect(text("#solve")).toContain("Stopped.");
    [...$$("#solve button")].find((button) => button.textContent === "Try again").click();
    await vi.waitFor(() => expect(t.engine.runs.length).toBeGreaterThan(1), { timeout: 4000 });
    expect($(".solve-prio").hidden, "asked again: the note is back").toBe(false);
    t.engine.runs.at(-1).fail(Object.assign(new Error("It broke."), { code: "something" }));
    await vi.waitFor(() => expect(text("#solve")).toContain("Couldn't work out the kit"));
    expect($(".solve-prio").hidden, "a fault: the table shows the shard's kit").toBe(true);
  });

  it("gives the runner-ups and the robust core back with the precomputed kit, and not before: they are for the page's own answer", async () => {
    const t = open();
    await wikiView(t);
    $("#runnerups").open = true;
    $("#runnerups").dispatchEvent(new Event("toggle"));
    await t.app.whenIdle();
    const shardRunnerups = !$("#runnerups-table").hidden;
    pick("ac", "h");
    await sent(t, 1);
    expect($("#runnerups-table").hidden).toBe(true);
    expect($("#runnerups-na").hidden).toBe(false);
    pick("ac", "n");
    await t.app.whenIdle();
    expect($("#runnerups-table").hidden).toBe(!shardRunnerups);
  });

  it("is said in the lines that say what is assumed, and the folded line says so in its first word", async () => {
    const t = open();
    await wikiView(t);
    expect(text('[data-f="a-lead"]')).toBe("Assumptions");
    pick("ac", "h");
    await sent(t, 1);
    expect(text('[data-f="a-lead"]')).toBe("Assumptions changed");
    expect(text("#view-summary")).toContain("your priorities");
    pick("ac", "n");
    await t.app.whenIdle();
    expect(text('[data-f="a-lead"]')).toBe("Assumptions");
    expect(text("#view-summary")).not.toContain("your priorities");
  });

  it("is named by the link that reports a problem: the page in it has the choice, once the kit of the choice is drawn", async () => {
    const footer = '<footer><a id="report-link" href="https://example.test/issues/new?page=https%3A%2F%2Ftrioforge.test%2Ftrio%2Fpal-mnk-ber%2F%3Frace%3DOGR">Report</a></footer>';
    const t = open({ footer });
    await wikiView(t);
    pick("ac", "h");
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    const page = new URL(new URL($("#report-link").getAttribute("href")).searchParams.get("page"));
    expect(page.searchParams.get("p")).toBe("nhnnnnnn");
  });
});

// ---- when the weights cannot be had ------------------------------------------------------------------------------------------------------------------------

describe("a choice that cannot be worked out", () => {
  it("goes back when the bundle of the trio cannot be loaded: the controls show what the page shows, the page says so with a Try again, and nothing is sent", async () => {
    const t = open({ bundleFails: true });
    await wikiView(t);
    pick("ac", "h");
    await vi.waitFor(() => expect(text("#status")).toContain("Couldn't load this view"));
    expect(shown()).toBe("nnnnnnnn");
    expect(t.engine.runs).toHaveLength(0);
    expect(rowNames()).toEqual(shardNames("wiki-own", "OGR", "tank", 4, "1h-shield"));
    expect(text("#status")).toMatch(/priorities are back at all Normal/);
  });
});

// ---- the exchange rates -------------------------------------------------------------------------------------------------------------------------------------

// ---- the data was released again while the page was open -------------------------------------------------------------------------------------------------

describe("a release of the data while the page is open", () => {
  it("is said as it is said everywhere: when the manifest of the trio is of another release than the site's, a step ends in the Data updated line with a Reload, and not in a Try again that can never work", async () => {
    const site = makeSite();
    site.trioJson["pal-mnk-ber"].data_release = "data-2099-01-01";
    site.files.set(site.trioPath, encode(site.trioJson["pal-mnk-ber"]));
    const t = open({ site });
    await wikiView(t);
    pick("ac", "h");
    await vi.waitFor(() => expect(text("#status")).toContain(UPDATED));
    expect(text("#status")).not.toContain("Couldn't load this view");
    expect(text("#status")).toContain("The priorities are back at all Normal.");
    expect([...$$("#status button")].map((button) => button.textContent)).toEqual(["Reload"]);
    expect(shown()).toBe("nnnnnnnn");
    expect(t.engine.runs).toHaveLength(0);
    expect(t.reload).not.toHaveBeenCalled();
    $("#status button").click();
    expect(t.reload).toHaveBeenCalledTimes(1);
  });

  it("is said the same when the main manifest is of another release than the page: the page was made for the release it names", async () => {
    const site = makeSite();
    site.manifestJson.data_release = "data-2099-01-01";
    const t = open({ site });
    await wikiView(t);
    pick("ac", "h");
    await vi.waitFor(() => expect(text("#status")).toContain(UPDATED));
    expect([...$$("#status button")].map((button) => button.textContent)).toEqual(["Reload"]);
    expect(t.engine.runs).toHaveLength(0);
  });

  it("reaches the rates the same way: the line says they could not be worked out, and the page says the data was updated", async () => {
    const site = makeSite();
    site.manifestJson.data_release = "data-2099-01-01";
    const t = open({ site });
    await wikiView(t);
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(text("#status")).toContain(UPDATED));
    expect($("#prio-rates-text").textContent).toMatch(/could not be worked out/i);
  });
});

// ---- every stat Off -------------------------------------------------------------------------------------------------------------------------------------

describe("every step Off", () => {
  it("is nothing to optimise: the page says so, sends no request, keeps the kit it shows, writes the address with every step Off, and the selects stay as they were set", async () => {
    const t = open();
    await wikiView(t);
    const kit = rowNames();
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    await tick(450);
    expect(t.engine.runs).toHaveLength(0);
    expect(rowNames()).toEqual(kit);
    expect(shown()).toBe("00000000");
    expect(query(), "the address says every step Off, as it does for every other view, so that a reload returns to the same state (it was the address the page had, before E11)").toEqual({ race: "OGR", role: "tank", tier: "4", buffs: "own", p: "00000000" });
    expect($("#solve").hidden).toBe(true);
    expect($("#prio-reset").disabled).toBe(false);
  });

  it("is left by raising one step: the kit is worked out for the rest Off, and the message goes", async () => {
    const t = open();
    await wikiView(t);
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    pick("haste", "n");
    await sent(t, 1);
    expect(text("#status")).toBe("");
    const own = OWN("tank");
    expect(t.engine.runs[0].request.weights.custom).toEqual({ HP: 0, AC: 0, MANA: 0, ATK: 0, DEX: 0, END: 0, SV_FIRE: 0, SV_COLD: 0, SV_MAGIC: 0, SV_POISON: 0, SV_DISEASE: 0 });
    expect(Object.keys(t.engine.runs[0].request.weights.custom)).not.toContain("CHA");
    expect(own.CHA, "charisma is the build's own weight, and the control does not offer it").toBeGreaterThan(0);
    expect(query().p).toBe("00000n00");
  });

  it("is left by Reset: every step Normal, the message gone, the precomputed kit", async () => {
    const t = open();
    await wikiView(t);
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    $("#prio-reset").click();
    await t.app.whenIdle();
    expect(shown()).toBe("nnnnnnnn");
    expect(text("#status")).toBe("");
    expect(rowNames()).toEqual(shardNames("wiki-own", "OGR", "tank", 4, "1h-shield"));
    expect(t.engine.runs).toHaveLength(0);
  });

  it("is the same from an address: p of eight zeros opens the page with every select Off, the message, and the precomputed kit", async () => {
    const t = open({ search: "?p=00000000" });
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    expect(shown()).toBe("00000000");
    expect(t.engine.runs).toHaveLength(0);
    expect(rowNames()).toEqual(shardNames("wiki-own", "OGR", "tank", 4, "1h-shield")); // (the wiki level is the one the page reads for a view of its own: there, 1H + shield is the Tank's best at +4)
  });

  it("paints the view's own kit when every step goes Off after an answer of the optimizer, and the report link names it (F9)", async () => {
    // the kit of the optimizer was drawn for a step that is gone: it would stay in the table, unlabelled, under an address that says every step Off, and a reload shows the build's own kit
    const footer = '<footer><a id="report-link" href="https://example.test/issues/new?page=https%3A%2F%2Ftrioforge.test%2Ftrio%2Fpal-mnk-ber%2F%3Frace%3DOGR">Report</a></footer>';
    const t = open({ footer });
    await wikiView(t);
    const baked = rowNames();
    pick("ac", "h");
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(rowNames(), "the answer of the optimizer is the kit shown").not.toEqual(baked);
    expect($("#main").classList.contains("solved")).toBe(true);
    expect(new URL(new URL($("#report-link").getAttribute("href")).searchParams.get("page")).searchParams.get("p")).toBe("nhnnnnnn");
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    await t.app.whenIdle();
    expect(rowNames(), "the build's own kit for the view, which is what a reload of the address shows").toEqual(baked);
    expect($("#main").classList.contains("solved"), "no answer of the optimizer is on the table").toBe(false);
    expect(text("#solve")).not.toContain(HEADING);
    expect(shown()).toBe("00000000");
    expect(query()).toEqual({ race: "OGR", role: "tank", tier: "4", buffs: "own", p: "00000000" });
    const page = new URL(new URL($("#report-link").getAttribute("href")).searchParams.get("page"));
    expect(page.searchParams.get("p"), "the report names the answer the table shows: the precomputed one").toBeNull();
    expect(t.engine.runs).toHaveLength(1);
    // a reload of that address shows the same kit
    document.body.innerHTML = "";
    const again = open({ search: window.location.search });
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    expect(rowNames()).toEqual(baked);
    expect(again.engine.runs).toHaveLength(0);
  });

  /** The best kit of a view in the shard the page reads, by the plain rows of its data file: the setup with the greatest value, as the page follows the role's best. */
  const bestKit = (race, role, tier, setup = null) => {
    const rows = shardFile("wiki-own").rows.filter((r) => r[0] === race && r[1] === role && r[2] === tier);
    const row = setup === null ? rows.reduce((best, r) => (r[5] > best[5] ? r : best)) : rows.find((r) => r[3] === setup);
    return shardNames("wiki-own", race, role, tier, row[3]);
  };
  const allOffThen = async (t) => {
    await wikiView(t);
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
  };

  it("paints the build's own kit for the race that is asked for with every step Off: the kit and the controls agree, the selects stay Off, the words stay, the address keeps p", async () => {
    const t = open();
    await allOffThen(t);
    const before = rowNames();
    $("#sw-race").value = "TRL";
    change($("#sw-race"));
    await vi.waitFor(() => expect(rowNames()).toEqual(bestKit("TRL", "tank", 4)));
    expect(rowNames()).not.toEqual(before);
    expect(text("#status")).toBe(ALL_OFF);
    expect(shown()).toBe("00000000");
    expect(query()).toEqual({ race: "TRL", role: "tank", tier: "4", buffs: "own", p: "00000000" });
    expect(text('[data-f="v-race"]')).toBe("Troll");
    expect(t.engine.runs).toHaveLength(0);
    expect($("#solve").hidden).toBe(true);
  });

  it("paints it for the role, the tier and the weapons that are asked for as well, one change at a time", async () => {
    const t = open();
    await allOffThen(t);
    choose("#role-melee");
    await vi.waitFor(() => expect(rowNames()).toEqual(bestKit("OGR", "melee", 4)));
    expect(text("#status")).toBe(ALL_OFF);
    expect(shown()).toBe("00000000");
    expect(query()).toMatchObject({ role: "melee", p: "00000000" });
    $("#sw-tier").value = "10";
    change($("#sw-tier"));
    await vi.waitFor(() => expect(rowNames()).toEqual(bestKit("OGR", "melee", 10)));
    expect(text("#status")).toBe(ALL_OFF);
    expect(query()).toMatchObject({ role: "melee", tier: "10", p: "00000000" });
    choose("#setup-dw");
    await vi.waitFor(() => expect(rowNames()).toEqual(bestKit("OGR", "melee", 10, "dw")));
    expect(text("#status")).toBe(ALL_OFF);
    expect(query()).toMatchObject({ setup: "dw", p: "00000000" });
    expect(shown()).toBe("00000000");
    expect(t.engine.runs).toHaveLength(0);
  });

  it("keeps the kit when only a select changed, as it did: the same view, the words, the address (every step Off)", async () => {
    const t = open();
    await wikiView(t);
    const kit = rowNames();
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    pick("haste", "0");
    await t.app.whenIdle();
    expect(rowNames()).toEqual(kit);
    expect(query()).toHaveProperty("p", "00000000");
    expect(text("#status")).toBe(ALL_OFF);
  });

  it("opens a link that names another view with p of eight zeros on that view's own kit: the race and the role are the ones addressed, the selects Off, the words, and the address as it was", async () => {
    const t = open({ search: "?race=TRL&role=tank&p=00000000" });
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    await vi.waitFor(() => expect(rowNames()).toEqual(bestKit("TRL", "tank", 4)));
    expect($("#sw-race").value).toBe("TRL");
    expect($("#role-tank").checked).toBe(true);
    expect(shown()).toBe("00000000");
    expect(query()).toEqual({ race: "TRL", role: "tank", tier: "4", buffs: "own", p: "00000000" });
    expect(t.engine.runs).toHaveLength(0);
  });

  it("is left from there by Reset (every step Normal, the kit of the view as it is, no p) and by raising one step (the kit of the view asked for)", async () => {
    const t = open();
    await allOffThen(t);
    $("#sw-race").value = "TRL";
    change($("#sw-race"));
    await vi.waitFor(() => expect(rowNames()).toEqual(bestKit("TRL", "tank", 4)));
    $("#prio-reset").click();
    await t.app.whenIdle();
    expect(shown()).toBe("nnnnnnnn");
    expect(rowNames()).toEqual(bestKit("TRL", "tank", 4));
    expect(text("#status")).toBe("");
    expect(query()).toEqual({ race: "TRL", role: "tank", tier: "4", buffs: "own" });
    expect(t.engine.runs).toHaveLength(0);
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    pick("dex", "n");
    await sent(t, 1);
    expect(t.engine.runs[0].request.scenario).toMatchObject({ race: "TRL", role: "tank" });
    expect(text("#status")).toBe("");
    expect(query().p).toBe("0000n000");
  });

  it("is a precomputed view that the sliders or the raid make a stand-in for: the optimizer is asked for the view as it is with every step Normal, and the words stay", async () => {
    const t = open();
    await allOffThen(t);
    choose("#buffs-raid");
    await sent(t, 1);
    expect(t.engine.runs[0].request.scenario).toMatchObject({ buffs: "raid" });
    expect(t.engine.runs[0].request).not.toHaveProperty("weights");
    expect(text("#status")).toBe(ALL_OFF);
    expect($(".solve-prio").hidden, "no note of priorities: the kit asked for is the build's own").toBe(true);
    expect(shown()).toBe("00000000");
  });

  it("draws the answer of the optimizer for a view that is not precomputed, with the selects still Off, the words kept and the address as it is", async () => {
    const t = open();
    await allOffThen(t);
    choose("#buffs-raid");
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    expect(text("#status")).toBe(ALL_OFF);
    expect(shown()).toBe("00000000");
    expect(query()).toMatchObject({ buffs: "raid", p: "00000000" });
  });

  it("goes back when the view asked for cannot be loaded with every step Off: the selects stay Off, the page says what went back (the buffs, and not the priorities), and Try again works", async () => {
    const t = open({ offline: ["wiki-group"] });
    await allOffThen(t);
    const kit = rowNames();
    choose("#buffs-group");
    await vi.waitFor(() => expect($("#status").textContent).toContain("back at"));
    expect($("#status").textContent).not.toContain("riorit");
    expect($("#status").textContent).not.toContain("Still showing");
    expect(shown()).toBe("00000000");
    expect(rowNames()).toEqual(kit);
    expect(query()).toHaveProperty("p", "00000000"); // (the page is still on the view whose address says every step Off)
  });

  it("does not stop a kit that has a stat left on: seven Off and dexterity Normal is worked out", async () => {
    const t = open();
    await wikiView(t);
    setAll("0");
    $("#prio-dex").value = "n";
    change($("#prio-ac"));
    await sent(t, 1);
    expect(text("#status")).toBe("");
  });

  it("counts a stat that the build does not weigh as Off: with haste and mana at no weight, the six others Off is nothing to optimise, whatever those two say", async () => {
    const t = open({ site: siteWith(meleeWeighsNoHasteNoMana) });
    await wikiView(t);
    choose("#role-melee");
    await t.app.whenIdle();
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    expect(t.engine.runs).toHaveLength(0);
  });
});

// ---- a stat the build does not weigh -----------------------------------------------------------------------------------------------------------------------

describe("a stat the build does not weigh", () => {
  const open1 = (extra = {}) => open({ site: siteWith(meleeWeighsNoHasteNoMana), ...extra });

  it("is shown disabled with a visible note when the control is touched, for the build the page shows, and offered again when the role is one that weighs it", async () => {
    const t = open1();
    await wikiView(t);
    choose("#role-melee");
    await t.app.whenIdle();
    expect($("#prio-haste").disabled, "the build is not known before the control is touched").toBe(false);
    focusControl();
    await vi.waitFor(() => expect($("#prio-haste").disabled).toBe(true));
    expect($("#prio-mana").disabled).toBe(true);
    for (const id of ["haste", "mana"]) {
      expect($(`#prio-${id}-note`).hidden).toBe(false);
      expect($(`#prio-${id}-note`).textContent).toBe(NOT_COUNTED);
      expect($(`#prio-${id}`).value).toBe("n");
    }
    expect($("#prio-ac").disabled).toBe(false);
    choose("#role-tank");
    await t.app.whenIdle();
    expect($("#prio-haste").disabled).toBe(false);
    expect($("#prio-mana-note").hidden).toBe(true);
    choose("#role-melee");
    await t.app.whenIdle();
    expect($("#prio-haste").disabled, "and disabled again for the role that does not").toBe(true);
  });

  it("is never sent, never makes a request and never reaches the address, whatever step it is given: a step chosen before the build was known is Normal when it is read", async () => {
    const t = open1();
    await wikiView(t);
    choose("#role-melee");
    await t.app.whenIdle();
    pick("haste", "t");
    await t.app.whenIdle();
    await tick(450);
    expect(t.engine.runs).toHaveLength(0);
    expect(shown()).toBe("nnnnnnnn");
    expect(query()).not.toHaveProperty("p");
    pick("mana", "0");
    await t.app.whenIdle();
    await tick(450);
    expect(t.engine.runs).toHaveLength(0);
    expect(query()).not.toHaveProperty("p");
    expect($("#solve").hidden).toBe(true);
  });

  it("is left out of a request that has another step in it, and out of the address: haste Top and armor class High are armor class High", async () => {
    const t = open1();
    await wikiView(t);
    choose("#role-melee");
    await t.app.whenIdle();
    $("#prio-haste").value = "t";
    pick("ac", "h");
    await sent(t, 1);
    expect(t.engine.runs[0].request.weights).toEqual({ custom: { AC: OWN("melee").AC * 2 } });
    expect(query().p).toBe("nhnnnnnn");
    expect(shown()).toBe("nhnnnnnn");
  });

  it("is accepted in an address and its character ignored: the page is the one without it, and the address is written with n", async () => {
    const t = open1({ search: "?role=melee&p=nnntttnn" });
    await vi.waitFor(() => expect($("#prio-haste").disabled).toBe(true));
    await t.app.whenIdle();
    expect(shown(), "the step of haste is Normal, the others are as they were").toBe("nnnttnnn");
    expect(query().p).toBe("nnnttnnn");
    expect(text("#status"), "nothing is wrong with the address").not.toContain(BAD);
    await sent(t, 1);
    expect(t.engine.runs[0].request.weights).toEqual({ custom: { ATK: OWN("melee").ATK * 4, DEX: OWN("melee").DEX * 4 } });
  });

  it("makes no view of its own: an address that sets steps for stats that are not counted alone is the page as made, with no request and no note", async () => {
    const t = open1({ search: "?role=melee&p=nnhnnhnn" });
    await t.app.whenIdle();
    await tick(450);
    expect(t.engine.runs).toHaveLength(0);
    expect($("#solve").hidden).toBe(true);
    expect(query()).not.toHaveProperty("p");
    expect(shown()).toBe("nnnnnnnn");
  });
});

// ---- the exchange rates -------------------------------------------------------------------------------------------------------------------------------------

describe("the exchange rates under the control", () => {
  const records = readItemTable(ITEMS_DOCUMENT).records;
  const placesOf = (kit, tier) => kit.flatMap((key, slotIndex) => (key === null ? [] : [{ slotIndex, key, tier }]));
  const WORDS = { casting: ["WIS"], mana: true, haste: true, pools: ["WIS"], counted: 2 }; // (the trio has one mana pool, the Paladin's, of WIS)
  const keysOfShard = () => {
    const doc = shardFile("wiki-own");
    const row = doc.rows.find((r) => r[0] === "OGR" && r[1] === "tank" && r[2] === 4 && r[3] === "1h-shield");
    return doc.kits[row[4]].map((index) => (index < 0 ? null : doc.items[index][0]));
  };
  const ratesFor = (role, weights, steps = false, kit = null) => {
    const done = ratesOfKit({ bundle: BUNDLE, records, race: "OGR", role, buffs: "own", evidence: "wiki", deity: null, weights, setup: "1h-shield", places: placesOf(kit ?? keysOfShard(), 4) });
    return ratesText({ ...done, ...WORDS, steps });
  };
  const line = () => $("#prio-rates-text").textContent;
  const said = () => $("#announce").textContent;
  /** Every text the page's live region is given from now on. */
  function listenRates() {
    const heard = [];
    const watcher = new MutationObserver(() => heard.push($("#announce").textContent));
    watcher.observe($("#announce"), { childList: true, characterData: true, subtree: true });
    return heard;
  }

  it("are a collapsed disclosure until they are asked for, and ask for nothing before that", async () => {
    const t = open();
    await wikiView(t);
    expect($("#prio-rates-show").getAttribute("aria-expanded")).toBe("false");
    expect($("#prio-rates-text").hidden).toBe(true);
    expect(t.net.asked.filter((url) => url.includes(EVALUATOR))).toEqual([]);
  });

  it("are one line for the kit shown: the evaluator is fetched by the path and SHA-256 of the manifest, the line is what it makes of the kit, the button stays where the focus is, and the line is said through the live region", async () => {
    const t = open();
    await wikiView(t);
    const heard = listenRates();
    $("#prio-rates-show").focus();
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toContain("A point more on this kit is worth about:"), { timeout: 4000 });
    expect(t.net.asked.filter((url) => url.endsWith(EVALUATOR))).toHaveLength(1);
    const want = ratesFor("tank", undefined);
    expect(line()).toBe(want);
    expect(line()).toContain("WIS ");
    expect(line(), "this trio casts with WIS only").not.toContain("INT");
    expect(line()).toContain("(hit points of kit value)");
    expect(line()).toContain(" Mana here comes from WIS (1 pool)."); // (the trio's one mana class: the line of where the mana comes from is in the rates line)
    expect($("#prio-rates-text").hidden).toBe(false);
    expect($("#prio-rates-show").hidden).toBe(false);
    expect($("#prio-rates-show").getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement.id, "the focus stays on the button: it is not taken to a text that is working").toBe("prio-rates-show");
    await vi.waitFor(() => expect(said(), "the line is said through the page's live region").toBe(want), { timeout: 4000 });
    expect(heard.filter((text) => /working/i.test(text)), "what is said is the result, not that it works").toEqual([]);
  });

  it("go away with a second press, and come back with a third", async () => {
    const t = open();
    await wikiView(t);
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    $("#prio-rates-show").click();
    await t.app.whenIdle();
    expect($("#prio-rates-text").hidden).toBe(true);
    expect($("#prio-rates-show").getAttribute("aria-expanded")).toBe("false");
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    expect($("#prio-rates-show").getAttribute("aria-expanded")).toBe("true");
  });

  it("follow the kit: for a choice they are for the optimizer's kit, under the choice's own weights, in the points of the build's score, and said again", async () => {
    const t = open();
    await wikiView(t);
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    const before = line();
    pick("ac", "t");
    await sent(t, 1);
    expect(line(), "no rates of a kit that is not the one shown").not.toBe(before);
    expect(line()).toMatch(/no rate for these settings yet/i);
    await vi.waitFor(() => expect(said()).toMatch(/no rate for these settings yet/i), { timeout: 4000 });
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    const want = ratesFor("tank", { custom: { AC: OWN("tank").AC * 4 } }, true, AC2.kit.map((ident) => (ident === null ? null : ident.slice(0, ident.lastIndexOf("@")))));
    expect(line()).toBe(want);
    expect(line()).toContain("(points of this build's score)");
    expect(line()).not.toContain("hit point");
    await vi.waitFor(() => expect(said()).toBe(want), { timeout: 4000 });
  });

  it("are not worked out for a kit that stands in for one that is on its way: pressed while the optimizer works, the line says there is no rate yet and the evaluator is not asked for", async () => {
    const t = open();
    await wikiView(t);
    pick("ac", "t");
    await sent(t, 1);
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toMatch(/no rate for these settings yet/i));
    await tick(200);
    expect(t.net.asked.filter((url) => url.endsWith(EVALUATOR)), "the stand-in kit is never valued under the choice's weights").toEqual([]);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
  });

  it("say that there is no rate for the settings when the kit shown is the precomputed one after a Stop or a fault, and wait again with Try again", async () => {
    const t = open();
    await wikiView(t);
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    pick("ac", "h");
    await sent(t, 1);
    [...$$("#solve button")].find((button) => button.textContent === "Stop").click();
    expect(line()).toMatch(/no rate for these settings yet/i);
    await vi.waitFor(() => expect(said()).toMatch(/no rate for these settings yet/i), { timeout: 4000 });
    [...$$("#solve button")].find((button) => button.textContent === "Try again").click();
    expect(line()).toMatch(/no rate for these settings yet|working/i);
    await vi.waitFor(() => expect(t.engine.runs.length).toBeGreaterThan(1), { timeout: 4000 });
    t.engine.runs.at(-1).fail(Object.assign(new Error("It broke."), { code: "something" }));
    await vi.waitFor(() => expect(text("#solve")).toContain("Couldn't work out the kit"));
    expect(line()).toMatch(/no rate for these settings yet/i);
    [...$$("#solve button")].find((button) => button.textContent === "Try again").click();
    await vi.waitFor(() => expect(t.engine.runs.length).toBeGreaterThan(2), { timeout: 4000 });
    t.engine.runs.at(-1).finish(result());
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
  });

  it("show every stat of the control that the build weighs: dexterity, haste, mana and endurance as well, and leave out the haste and the mana of a build that does not weigh them", async () => {
    const t = open();
    await wikiView(t);
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    for (const word of ["stamina", "strength", "WIS", "armor class", "dexterity", "haste", "maximum mana", "endurance", "one resist"]) expect(line(), word).toContain(word);
    expect(line()).toContain("Haste counts the best single piece");
    document.body.innerHTML = "";
    const tank = open({ site: siteWith(meleeWeighsNoHasteNoMana), search: "?role=melee" });
    await tank.app.whenIdle();
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    expect(line()).not.toContain("haste");
    expect(line()).not.toContain("mana");
    expect(line()).not.toContain("Haste counts");
  });

  it("leave out the mana and the haste that the reader set to Off, as it does a build that does not weigh them: the words read the weight in effect, the build's times the step", async () => {
    const t = open();
    await wikiView(t);
    pick("mana", "0");
    pick("haste", "0");
    await sent(t, 1);
    t.engine.runs[0].finish(result());
    await vi.waitFor(() => expect(text("#solve h3")).toBe(HEADING));
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    expect(line()).not.toContain("maximum mana");
    expect(line()).not.toContain("haste");
    expect(line()).not.toContain("Haste counts");
    expect(line()).toContain("(points of this build's score)");
    for (const word of ["stamina", "strength", "armor class", "dexterity", "endurance", "one resist"]) expect(line(), word).toContain(word);
    pick("haste", "n");
    await sent(t, 2);
    t.engine.runs[1].finish(result());
    await vi.waitFor(() => expect(line()).toContain("haste "), { timeout: 4000 });
    expect(line(), "haste is back at Normal, mana is still Off").toContain("Haste counts");
    expect(line()).not.toContain("maximum mana");
    pick("mana", "h");
    await sent(t, 3);
    t.engine.runs[2].finish(result());
    await vi.waitFor(() => expect(line()).toContain("maximum mana"), { timeout: 4000 });
  });

  it("show INT as well as WIS for a trio that casts with both, and INT alone for one that casts with INT", async () => {
    const both = siteWith((doc) => {
      doc.profile_common.pools.MANA = [...doc.profile_common.pools.MANA, { cls: "MNK", base: 900, fac: 4.5, stat: "INT" }];
    });
    const t = open({ site: both });
    await wikiView(t);
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    expect(line()).toMatch(/WIS [\d.]+, INT [\d.]+, armor class/);
    document.body.innerHTML = "";
    const only = siteWith((doc) => {
      doc.profile_common.pools.MANA = [{ cls: "PAL", base: 900, fac: 4.5, stat: "INT" }];
    });
    const u = open({ site: only });
    await wikiView(u);
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    expect(line()).toContain("INT ");
    expect(line()).not.toContain("WIS");
  });

  it("fetch the item table once for the evaluator however many ask at the same time, ask again only for items it has not met, and keep no copy of the table", async () => {
    const t = open();
    await wikiView(t);
    const fetched = () => t.net.asked.filter((url) => url.endsWith(t.site.itemsPath)).length;
    expect(fetched()).toBe(0);
    $("#prio-rates-show").click();
    choose("#role-melee"); // (a second ask at once: the page drew another kit while the first was still working)
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    await t.app.whenIdle();
    expect(fetched(), "one fetch for the two").toBe(1);
    $("#sw-tier").value = "10"; // a kit of +10: items that the evaluator has not met
    change($("#sw-tier"));
    await t.app.whenIdle();
    await vi.waitFor(() => expect(fetched(), "items it has not met are read from the table again: the table is not kept").toBe(2));
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    $("#prio-rates-show").click(); // away, and back: the same kit, the same items
    await t.app.whenIdle();
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toContain("A point more"), { timeout: 4000 });
    await tick(100);
    expect(fetched(), "the same items again: nothing is fetched").toBe(2);
  });

  it("say that they could not be worked out when the evaluator is not the one the manifest lists, close the disclosure, and offer Try again", async () => {
    const t = open();
    await wikiView(t);
    t.site.files.set(EVALUATOR, new TextEncoder().encode("// another script, of the same size....................................................\n"));
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(line()).toMatch(/could not be worked out/i), { timeout: 4000 });
    expect($("#prio-rates-show").hidden).toBe(false);
    expect($("#prio-rates-show").textContent).toBe("Try again");
    expect($("#prio-rates-show").getAttribute("aria-expanded")).toBe("false");
    await vi.waitFor(() => expect(said()).toMatch(/could not be worked out/i), { timeout: 4000 });
  });
});

// ---- the preset "Resists first" ---------------------------------------------------------------------------------------------------------------------

describe("the preset Resists first", () => {
  it("is a button of the control for the builds that stand in front, the Tank and the Shield caster, and for no other build", async () => {
    const t = open();
    await wikiView(t);
    const button = $("#prio-preset-resists");
    expect(button).not.toBeNull();
    expect(button.textContent).toBe("Resists first");
    expect(button.hidden).toBe(false); // (the page opens on the Tank)
    choose("#role-melee");
    await t.app.whenIdle();
    expect(button.hidden).toBe(true);
    choose("#role-tank");
    await t.app.whenIdle();
    expect(button.hidden).toBe(false);
  });

  it("sets the selects, resists Top, armor class Low and the rest Normal, and the address says it with p: the same choice as if the selects were set by hand", async () => {
    const t = open();
    await wikiView(t);
    $("#prio-preset-resists").click();
    await t.app.whenIdle();
    expect(shown()).toBe("nlnnnntn"); // (hit points, armor class, mana, attack, dexterity, haste, resists, endurance)
    expect(query().p).toBe("nlnnnntn");
    expect($("#prio-reset").disabled).toBe(false);
    await sent(t, 1); // (the browser's own answer for the choice: the weights of the Tank, with the armor class at x0.5 and the resists at x4)
    const { request } = t.engine.runs[0];
    // (the Tank's armor class weight is 12 and each resist school 0.4: x0.5 and x4; the numbers are held to the characters by priority-weights.test.mjs)
    expect(request.weights.custom).toEqual({ AC: 6, SV_COLD: 1.6, SV_DISEASE: 1.6, SV_FIRE: 1.6, SV_MAGIC: 1.6, SV_POISON: 1.6 });
  });

  it("is a choice like any other, so Reset takes it back: every step Normal, the address without p", async () => {
    const t = open();
    await wikiView(t);
    $("#prio-preset-resists").click();
    await t.app.whenIdle();
    expect(shown()).toBe("nlnnnntn");
    $("#prio-reset").click();
    await t.app.whenIdle();
    expect(shown()).toBe("nnnnnnnn");
    expect(query()).not.toHaveProperty("p");
  });

  it("is read from an old link whatever its role says: role=balanced opens the page's own build and the weights, the priorities and the buffs of the link are the page's", async () => {
    const t = open({ search: "?role=balanced&w=2111h&p=nlnnnntn&buffs=group" });
    await sent(t, 1);
    expect(shown()).toBe("nlnnnntn");
    expect(document.querySelector('input[name="role"]:checked').value).toBe("tank"); // (the opening build of the trio)
    expect(document.querySelector('input[name="buffs"]:checked').value).toBe("group");
    expect(t.engine.runs[0].request.scenario).toMatchObject({ role: "tank", buffs: "group" });
    expect(t.engine.runs[0].request.weights.multipliers).toMatchObject({ AC: 2 });
    expect(query()).toMatchObject({ role: "tank", buffs: "group", w: "2111h", p: "nlnnnntn" });
  });

  it("is on the page for an address that opens another build too: p is read as written, and the button goes with the build", async () => {
    const t = open({ search: "?role=melee&p=nlnnnntn" });
    await t.app.whenIdle();
    expect(shown()).toBe("nlnnnntn");
    expect($("#prio-preset-resists").hidden).toBe(true);
  });
});


// ---- part E: the code of the weights that does not come (E10), the view that never settles (E11), a release of the data met by the rates and by Get these first (E12), one message (E14) -------------

describe("part E: the code of the weights cannot be had", () => {
  const NOT_LOADED_WEIGHTS = "Couldn't load the weights. Reload the page to try again.";

  it("E10: a step chosen ends in the Reload line of the weights, as the first failure said it, and not in a Try again that could never work", async () => {
    const loadWeights = vi.fn(() => Promise.reject(new Error("chunk")));
    const t = open({ loadWeights });
    await wikiView(t);
    pick("ac", "h");
    await vi.waitFor(() => expect(text("#status")).toContain(NOT_LOADED_WEIGHTS));
    await t.app.whenIdle();
    expect(text("#status")).toContain(NOT_LOADED_WEIGHTS);
    expect([...$$("#status button")].map((button) => button.textContent)).toEqual(["Reload"]);
    $("#status button").click();
    expect(t.reload).toHaveBeenCalledTimes(1);
    expect(shown(), "the priorities are back where they were").toBe("nnnnnnnn");
    expect(t.engine.runs).toHaveLength(0);
  });

  it("E10, F11: the first touch of the control that finds no code is a failure like the others: another focus does not ask again, a change of a step (a user action) does, and the line is not written twice", async () => {
    let fail = true;
    const loadWeights = vi.fn(() => (fail ? Promise.reject(new Error("chunk")) : import("../pipeline/trioforge/site/static/ui/weights.js")));
    const t = open({ loadWeights });
    await wikiView(t);
    const writes = [];
    const watch = new MutationObserver((records) => writes.push(...records));
    watch.observe($("#status"), { subtree: true, childList: true, characterData: true });
    focusControl();
    await t.app.whenIdle();
    await tick(0);
    expect(loadWeights).toHaveBeenCalledTimes(1);
    const first = writes.length;
    expect(first, "the failure is said").toBeGreaterThan(0);
    expect(text("#status")).toContain(NOT_LOADED_WEIGHTS);
    for (let again = 0; again < 4; again += 1) {
      focusControl(); // (a focus again, and again: the control does not ask for the code each time)
      await t.app.whenIdle();
    }
    await tick(0);
    expect(loadWeights, "a focus is not a user action that asks again").toHaveBeenCalledTimes(1);
    expect(writes.length, "the line says it once: the same text is not written twice").toBe(first);
    fail = false;
    pick("ac", "h"); // (a step chosen: the visitor's action, which asks for the code, and re-arms the control)
    await sent(t, 1);
    expect(loadWeights).toHaveBeenCalledTimes(2);
    watch.disconnect();
  });

  it("F11: after a failure at a step chosen, the next change re-arms the first touch once, and a focus asks for the code a time and no more", async () => {
    let fail = true;
    const loadWeights = vi.fn(() => (fail ? Promise.reject(new Error("chunk")) : import("../pipeline/trioforge/site/static/ui/weights.js")));
    const t = open({ loadWeights });
    await wikiView(t);
    focusControl();
    await t.app.whenIdle();
    expect(loadWeights).toHaveBeenCalledTimes(1);
    pick("ac", "h"); // (the choice fails to load the code too: the line of the Reload, the steps back at Normal)
    await vi.waitFor(() => expect(loadWeights.mock.calls.length).toBeGreaterThanOrEqual(2));
    await t.app.whenIdle();
    const afterChange = loadWeights.mock.calls.length;
    focusControl(); // (the change re-armed the first touch: one more ask)
    await t.app.whenIdle();
    expect(loadWeights.mock.calls.length).toBe(afterChange + 1);
    for (let again = 0; again < 3; again += 1) {
      focusControl();
      await t.app.whenIdle();
    }
    expect(loadWeights.mock.calls.length, "and only one").toBe(afterChange + 1);
    fail = false;
  });
});

describe("part E: the view of the address that does not settle (E11)", () => {
  /** What the section Effects to exalt is told the page shows. */
  const told = (t) => t.app.exaltShown;

  it("E11: an address whose view cannot be loaded leaves the page on the baked answer, and the section is told that view and not the one that failed", async () => {
    const t = open({ search: "?race=TRL&role=tank&tier=4&buffs=own", offline: ["strict-own", "wiki-own", "strict-group", "wiki-group"] });
    await vi.waitFor(() => expect(text("#status")).toContain("Couldn't load this view"));
    await t.app.whenIdle();
    expect($("#sw-race").value).toBe("OGR");
    expect(told(t)).toMatchObject({ role: "tank", race: "OGR", tier: 4, exact: true, kit: null });
  });

  it("E11: a default view with every step Off is the shown view: the section is told it, and the notice of the address is said with the line", async () => {
    const t = open({ search: "?setup=dw&p=00000000&w=junk" }); // (the baked view's own weapons: the view of the address is the one the page shows)
    await vi.waitFor(() => expect(text("#status")).toContain(ALL_OFF));
    await t.app.whenIdle();
    expect(told(t)).toMatchObject({ role: "tank", race: "OGR", tier: 4, exact: true, kit: null });
    expect(text("#status"), "the notice of an address with a value that means nothing is not lost").toContain("do not fit the sliders");
    expect(query(), "an address that said every step Off says it still, and the junk is gone").toMatchObject({ p: "00000000" });
    expect(query()).not.toHaveProperty("w");
  });

  it("E11: every step Off chosen on the view shown says so in the address, as it does on any other view, so that a reload returns to the same state", async () => {
    const t = open();
    await wikiView(t);
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    expect(query()).toEqual({ race: "OGR", role: "tank", tier: "4", buffs: "own", p: "00000000" });
    expect(t.engine.runs).toHaveLength(0);
  });
});

describe("part E: a release of the data met by the rates and by Get these first (E12)", () => {
  const RELEASED = "data-2099-01-01";

  it("E12: the rates of a view whose shard is of a newer release say the data was updated, with a Reload, and not that they could not be worked out", async () => {
    const t = open({ shardRelease: RELEASED });
    $("#prio-rates-show").click();
    await vi.waitFor(() => expect(text("#status")).toContain(UPDATED));
    expect([...$$("#status button")].map((button) => button.textContent)).toEqual(["Reload"]);
  });

  it("E12: the section Get these first, opened on a page whose shard is of a newer release, says the data was updated, with a Reload", async () => {
    const t = open({ shardRelease: RELEASED });
    await t.app.whenIdle();
    const box = $("#common");
    box.open = true;
    box.dispatchEvent(new Event("toggle"));
    await vi.waitFor(() => expect(text("#status")).toContain(UPDATED));
    expect([...$$("#status button")].map((button) => button.textContent)).toEqual(["Reload"]);
  });
});

describe("part E: one message (E14)", () => {
  it("E14: every step Off after a solve that is still on its way draws no answer for the steps that are gone: the line says nothing to optimise, and no Solved for your settings comes under it", async () => {
    const t = open();
    await wikiView(t);
    pick("ac", "h");
    await sent(t, 1);
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    t.engine.runs[0].finish(result());
    await t.app.whenIdle();
    await tick(50);
    expect(text("#status")).toBe(ALL_OFF);
    expect(text("#solve h3"), "the answer for the steps that were chosen is not the answer for these").not.toBe(HEADING);
    expect($("#solve .solve-prio").hidden).toBe(true);
  });

  it("E14: a baked default view of a build with a rule of its own cites the rule at the start, as every view the page draws does", async () => {
    const t = open({ ruleOfTank: { rule: "roles.ranged_template", title: "Ranged weights" } });
    await t.app.whenIdle();
    expect(document.querySelector(".role-rule")?.textContent ?? "").toContain("Ranged weights");
  });
});

// ---- part G: every step Off where no shard answers (G1) --------------------------------------------------------------------------------------------------------

describe("part G: every step Off on a view that no shard answers (G1)", () => {
  const namesOfKit = (c) => c.kit.map((ident) => (ident === null ? "Leave empty" : ITEMS_DOCUMENT.items.find((record) => (record.key ?? `w${record.id}`) === ident.split("@")[0]).name));
  const [, LOW, ATTACK] = REFERENCE.cases; // (the same view at armor class x0.5, and at attack and haste x2: kits that differ)

  it("G1: after answers of the optimizer for the raid and for armor class High, every step Off sends the request for the raid view's own kit and ends on it: not a stand-in for ever", async () => {
    const t = open();
    await wikiView(t);
    choose("#buffs-raid");
    await sent(t, 1);
    t.engine.runs[0].finish(result(LOW));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(LOW)));
    pick("ac", "h");
    await sent(t, 2);
    t.engine.runs[1].finish(result(ATTACK));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(ATTACK)));
    expect(t.app.exaltShown.pending).toBe(false);
    listen();
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toContain(ALL_OFF));
    await sent(t, 3);
    expect(t.engine.runs[2].request.scenario.buffs, "the raid view's own kit is asked for").toBe("raid");
    expect(t.engine.runs[2].request, "with the role's own weights").not.toHaveProperty("weights");
    expect(t.app.standIn, "the table shows a stand-in while the request is out").toBe(true);
    expect($("#solve").hidden, "and says that it is being worked out").toBe(false);
    t.engine.runs[2].finish(result(LOW));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(LOW)));
    await t.app.whenIdle();
    // (H1) the answer is announced in the words of the choice, as the selects and the line of the status say it: not "all Normal", which is the build's own kit's steps
    expect(ANNOUNCED.at(-1)).toMatch(/^Priorities hit points Off, armor class Off, .*endurance Off\. Solved for your settings\. Showing .+\. Kit value [\d,]+\.$/);
    expect(ANNOUNCED.at(-1)).not.toContain("all Normal");
    expect(t.app.standIn).toBe(false);
    expect(t.app.exaltShown.pending, "the section is told the kit is the view's own").toBe(false);
    expect(shown()).toBe("00000000");
    expect(query()).toMatchObject({ buffs: "raid", p: "00000000" });
    expect(text("#status")).toContain(ALL_OFF);
    // a reload of that address works the same kit out again, and shows it
    document.body.replaceChildren();
    const again = open({ search: window.location.search });
    await sent(again, 1);
    expect(again.engine.runs[0].request.scenario.buffs).toBe("raid");
    again.engine.runs[0].finish(result(LOW));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(LOW)));
  });

  it("G1: an expander that is open is filled again for the view the page ends on (the extras of the answer that was drawn are not the view's)", async () => {
    const t = open();
    await wikiView(t);
    pick("ac", "h");
    await sent(t, 1);
    t.engine.runs[0].finish(result(ATTACK));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(ATTACK)));
    $("#runnerups").open = true;
    $("#runnerups").dispatchEvent(new Event("toggle"));
    $("#robust").open = true;
    $("#robust").dispatchEvent(new Event("toggle"));
    await t.app.whenIdle();
    const fills = vi.spyOn(t.app, "fillExtra");
    listen();
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    await t.app.whenIdle();
    expect(fills.mock.calls.map(([name]) => name).sort(), "both open expanders are filled for the view that is shown now").toEqual(["robust", "runnerups"]);
    expect(ANNOUNCED.at(-1), "the change is said, in the words of the choice (not the build's own kit's: all Normal)").toMatch(/^Priorities hit points Off, .*endurance Off\. Showing /);
  });

  it("G1: a request for a view no shard answers that was still on its way when every step went Off is asked for again for the view's own kit", async () => {
    const t = open();
    await wikiView(t);
    choose("#buffs-raid");
    await sent(t, 1);
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toContain(ALL_OFF));
    // (H2, edited: this asserted a second request, identical to the first, which the visitor then waited for as well; the request that is on its way for the same settings is kept and its answer is used)
    await tick(700);
    expect(t.engine.runs, "no second request for the settings the worker already has").toHaveLength(1);
    expect(t.engine.runs[0].request.scenario.buffs).toBe("raid");
    expect(t.engine.runs[0].request).not.toHaveProperty("weights");
    expect($("#solve").hidden, "the answer is still being worked out").toBe(false);
    t.engine.runs[0].finish(result(LOW));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(LOW)));
    await t.app.whenIdle();
    expect(t.app.standIn).toBe(false);
    expect(t.engine.runs).toHaveLength(1);
    expect(shown()).toBe("00000000");
  });
});

// ---- part H: a request for the same settings is kept (H2) --------------------------------------------------------------------------------------------------------

describe("part H: the request that is on its way for the same settings is kept (H2)", () => {
  const namesOfKit = (c) => c.kit.map((ident) => (ident === null ? "Leave empty" : ITEMS_DOCUMENT.items.find((record) => (record.key ?? `w${record.id}`) === ident.split("@")[0]).name));
  const [, LOW] = REFERENCE.cases;

  it("H2: every step Off while the request is still waiting for the pause is not a second request: the one pause runs out and one request goes", async () => {
    const t = open();
    await wikiView(t);
    choose("#buffs-raid");
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toContain(ALL_OFF));
    await sent(t, 1);
    await tick(700);
    expect(t.engine.runs).toHaveLength(1);
    t.engine.runs[0].finish(result(LOW));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(LOW)));
  });

  it("H2: the announcement of the kept request is the one of the last change, in the words of the choice", async () => {
    const t = open();
    await wikiView(t);
    choose("#buffs-raid");
    await sent(t, 1);
    listen();
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toContain(ALL_OFF));
    t.engine.runs[0].finish(result(LOW));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(LOW)));
    await t.app.whenIdle();
    expect(t.engine.runs).toHaveLength(1);
    expect(ANNOUNCED.at(-1)).toMatch(/^Priorities hit points Off, .*endurance Off\. Solved for your settings\./);
  });

  it("H2: a different view still sends its own request: armor class High on the raid is on its way, every step Off is the raid view's own kit", async () => {
    const t = open();
    await wikiView(t);
    choose("#buffs-raid");
    pick("ac", "h");
    await sent(t, 1);
    expect(t.engine.runs[0].request, "(the request that is on its way has the weights of armor class High)").toHaveProperty("weights");
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toContain(ALL_OFF));
    await sent(t, 2);
    expect(t.engine.runs[1].request.scenario.buffs).toBe("raid");
    expect(t.engine.runs[1].request).not.toHaveProperty("weights");
    t.engine.runs[1].finish(result(LOW));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(LOW)));
    await t.app.whenIdle();
    expect(t.app.standIn).toBe(false);
  });

  it("H2: a request whose answer was drawn is not kept: every step Off on that view repaints the stand-in and asks again", async () => {
    const t = open();
    await wikiView(t);
    choose("#buffs-raid");
    await sent(t, 1);
    t.engine.runs[0].finish(result(LOW));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(LOW)));
    await t.app.whenIdle();
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toContain(ALL_OFF));
    await sent(t, 2); // (the answer that was drawn is gone from the table, which holds the stand-in again: the same settings are asked for)
    expect(t.engine.runs[1].request).toEqual(t.engine.runs[0].request);
    t.engine.runs[1].finish(result(LOW));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(LOW)));
    await t.app.whenIdle();
    expect(t.app.standIn).toBe(false);
  });

  it("H2: a request that the visitor stopped is not kept: every step Off then asks again", async () => {
    const t = open();
    await wikiView(t);
    choose("#buffs-raid");
    await sent(t, 1);
    const stop = $$("#solve button").find((b) => b.textContent === "Stop");
    expect(stop, "the line has its Stop button while the request is out").toBeDefined();
    stop.click();
    await vi.waitFor(() => expect(text("#solve")).toContain("Stopped"));
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toContain(ALL_OFF));
    await sent(t, 2);
    t.engine.runs[1].finish(result(LOW));
    await vi.waitFor(() => expect(rowNames()).toEqual(namesOfKit(LOW)));
  });

  it("H2: every step Off on a view a shard answers still sends no request", async () => {
    const t = open();
    await wikiView(t);
    setAll("0");
    change($("#prio-ac"));
    await vi.waitFor(() => expect(text("#status")).toBe(ALL_OFF));
    await tick(700);
    expect(t.engine.runs).toHaveLength(0);
  });
});
