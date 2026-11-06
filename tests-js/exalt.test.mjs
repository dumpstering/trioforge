// @vitest-environment jsdom
//
// The section Effects to exalt (static/ui/exalt.js and what trio.js does for it), run in jsdom against the baked page and the files the generator writes for the fixture (both are
// committed under fixtures/site/contract-exalt/ and checked against the generator by pipeline/tests/test_site_exalt.py): nothing is fetched until the section is opened or its summary
// comes into view, the plan in the file is shown for the kit it was made for, a plan for any other kit is made again by the matcher (exalt-plan.js, which tests-js/exalt-plan.test.mjs
// holds to Python), the kit of Equip now is a second source, a file of another release is refused and a failure can be tried again.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PLACES, itemInfo, planKit } from "../pipeline/trioforge/site/static/ui/exalt-plan.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract"); // (the page without the effects layer, and its shards)
const WITH_EFFECTS = resolve(HERE, "../fixtures/site/contract-exalt"); // (the page of the fixture with the layer, and the two files the build publishes for it)
const read = (path) => JSON.parse(readFileSync(path, "utf8"));
const EFFECTS = read(resolve(WITH_EFFECTS, "data/effects.json"));
const EXALT = read(resolve(WITH_EFFECTS, "data/exalt.json"));
const ITEMS = read(resolve(HERE, "../fixtures/site/results/items.json"));
const PAGE_HTML = readFileSync(resolve(WITH_EFFECTS, "trio-main.html"), "utf8");
const ITEM_PATH = "/assets/engine/data/items-0123456789ABCDEF.json";
const $ = (selector) => document.querySelector(selector);
const names = new Map(EFFECTS.effects.map((row) => [row.id, row.n]));
const planNames = () => [...document.querySelectorAll("#exalt-plan-table tbody tr")].map((tr) => tr.cells[1].querySelector(".exalt-name").textContent);
const flush = async (app) => {
  await app.whenIdle();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await app.whenIdle();
};

/** A fetch that answers the files of the section, the manifest and the item list, and keeps a list of what was asked for. */
function makeFetch(calls, behaviour = {}) {
  return async (url) => {
    calls.push(String(url));
    const answer = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (behaviour[url] === "offline") throw new TypeError("Failed to fetch");
    if (behaviour[url]?.json) return answer(behaviour[url].json);
    if (url === "/data/effects.json") return answer(EFFECTS);
    if (url === "/data/pal-mnk-ber/exalt.json") return answer(EXALT);
    if (url === "/engine-manifest.json") return answer({ data_release: EXALT.release, items: { path: ITEM_PATH } });
    if (url === ITEM_PATH) return answer({ data_release: EXALT.release, defaults: ITEMS.defaults, items: ITEMS.items });
    if (String(url).startsWith("/data/pal-mnk-ber/")) return answer(read(resolve(CONTRACT, `data/${String(url).replace("/data/pal-mnk-ber/", "")}`)));
    throw new Error(`not asked for: ${url}`);
  };
}

function mount({ behaviour = {}, observer = false, html = PAGE_HTML, loadExalt, search = "" } = {}) {
  document.body.innerHTML = html;
  window.history.replaceState(null, "", `/trio/pal-mnk-ber/${search}`);
  const calls = [];
  const watchers = [];
  if (observer) {
    window.IntersectionObserver = class {
      constructor(callback) {
        this.callback = callback;
        watchers.push(this);
      }
      observe() {}
      disconnect() {
        this.gone = true;
      }
    };
  }
  const loads = [];
  const app = initTrio({
    document,
    window,
    fetch: makeFetch(calls, behaviour),
    loadExalt: loadExalt ?? (() => (loads.push(1), import("../pipeline/trioforge/site/static/ui/exalt.js"))),
  });
  return { app, calls, loads, watchers };
}

const open = async (app) => {
  const section = $("#exalt");
  section.open = true;
  section.dispatchEvent(new Event("toggle"));
  await flush(app);
};

beforeEach(() => {
  delete window.IntersectionObserver;
});
afterEach(() => {
  document.body.replaceChildren();
});

describe("the page", () => {
  it("has the section closed, with the summary as the button that opens it", () => {
    mount();
    expect($("#exalt")).not.toBeNull();
    expect($("#exalt > summary").getAttribute("aria-expanded")).toBe("false");
    expect($("#exalt").dataset.effects).toBe("/data/effects.json");
    expect($("#exalt").dataset.exalt).toBe("/data/pal-mnk-ber/exalt.json");
  });

  it("asks for nothing of the section until it is opened, then for its code and its two files once", async () => {
    const { app, calls, loads } = mount();
    await flush(app);
    expect(calls.filter((c) => /effects|exalt/.test(c))).toEqual([]);
    expect(loads).toEqual([]);
    await open(app);
    expect($("#exalt > summary").getAttribute("aria-expanded")).toBe("true");
    expect(loads).toHaveLength(1);
    expect(calls.filter((c) => /effects|exalt/.test(c)).sort()).toEqual(["/data/effects.json", "/data/pal-mnk-ber/exalt.json"]);
    await open(app);
    expect(loads).toHaveLength(1);
    expect(calls.filter((c) => /effects|exalt/.test(c))).toHaveLength(2);
    expect(calls).not.toContain("/engine-manifest.json"); // (the plan in the file is for the kit shown: no item list is needed)
  });

  it("loads the section when its summary comes near the window, and not before", async () => {
    const { app, calls, watchers } = mount({ observer: true });
    expect(watchers).toHaveLength(1);
    watchers[0].callback([{ isIntersecting: false }]);
    await flush(app);
    expect(calls.filter((c) => /effects|exalt/.test(c))).toEqual([]);
    watchers[0].callback([{ isIntersecting: true }]);
    await flush(app);
    expect(watchers[0].gone).toBe(true);
    expect(calls.filter((c) => /effects|exalt/.test(c))).toHaveLength(2);
    expect($("#exalt > summary").getAttribute("aria-expanded")).toBe("false"); // (loaded, not opened)
  });

  it("is absent from a page made without the effects files: nothing is asked for and the page starts", async () => {
    const without = PAGE_HTML.replace(/<details class="expander exalt"[\s\S]*?<\/details>\n/, "");
    expect(without).not.toContain('id="exalt"');
    const { app, calls, loads } = mount({ html: without, observer: true });
    await flush(app);
    expect($("#exalt")).toBeNull();
    expect(calls.filter((c) => /effects|exalt/.test(c))).toEqual([]);
    expect(loads).toEqual([]);
  });
});

describe("what the open section shows", () => {
  it("is the plan in the file for the kit shown, the lists and the carry list, with the names of the file", async () => {
    const { app } = mount();
    await open(app);
    const role = "balanced";
    expect($("#exalt-plan-lead").textContent).toContain("as the site worked it out");
    expect(planNames()).toEqual(EXALT.roles[role].plan.map((row) => names.get(row.e)));
    const hosts = [...document.querySelectorAll("#exalt-plan-table tbody th")].map((th) => th.textContent);
    expect(hosts[0]).toContain(EXALT.names[EXALT.roles[role].plan[0].h]);
    for (const kind of ["focus", "click", "worn", "proc", "carry"]) {
      const shown = [...document.querySelectorAll(`#exalt-${kind} tbody .exalt-name`)].map((n) => n.textContent);
      expect(shown).toEqual(EXALT.roles[role][kind].map((row) => names.get(row.e)));
      expect(document.querySelectorAll(`#exalt-${kind} thead th[scope="col"]`)).toHaveLength(2);
    }
    expect($("#exalt-noroom").textContent).toContain("No room for");
  });

  it("writes names as text, never as markup (an item called <b>x</b> is a name, not an element)", async () => {
    const { app } = mount();
    await open(app);
    expect($("#exalt-body b")).toBeNull();
    expect($("#exalt-plan-table").textContent).toContain("<b>x</b>");
  });

  it("says what an effect does, what a focus touches, the tier it opens at, and where it comes from with a word for how hard it is", async () => {
    const { app } = mount();
    await open(app);
    const first = $("#exalt-focus tbody tr").textContent;
    expect(first).toMatch(/15% faster casts for all spells with a cast time of 2 s or more/);
    expect(first).toContain("Opens at +1");
    expect(first).toMatch(/touches 83% of what your Paladin casts at 30\+/);
    expect(first).toContain("Spells up to level 44 get all of it; each level above loses 5% of it.");
    expect(first).toContain("Crown of the Vanguard");
    expect(first).toContain("Vendor");
    expect($("#exalt-click").textContent).toMatch(/Raid drop/);
    expect($("#exalt-carry caption").textContent).toContain("Just carry");
    expect($("#exalt-carry").textContent).toContain("Needs no socket");
  });

  it("marks a row built on an assumption, and the mark is a button that opens the reason", async () => {
    const { app } = mount();
    await open(app);
    const marks = [...document.querySelectorAll("#exalt-body .exalt-mark")];
    expect(marks.length).toBeGreaterThan(3);
    const mark = marks[0];
    const reason = document.getElementById(mark.getAttribute("aria-controls"));
    expect(mark.getAttribute("aria-expanded")).toBe("false");
    expect(reason.hidden).toBe(true);
    mark.click();
    expect(mark.getAttribute("aria-expanded")).toBe("true");
    expect(reason.hidden).toBe(false);
    expect(reason.textContent.length).toBeGreaterThan(20);
    mark.click();
    expect(reason.hidden).toBe(true);
  });

  it("has a why-not note for a focus type that other families lost, a disclosure that says whether it is open", async () => {
    const { app } = mount();
    await open(app);
    const summary = $("#exalt-focus summary");
    expect(summary.getAttribute("aria-expanded")).toBe("false");
    const details = summary.parentElement;
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    expect(summary.getAttribute("aria-expanded")).toBe("true");
    expect(details.textContent).toContain("Enhancement Haste");
  });

  it("shows nothing but a message for a role the file has no plan for", async () => {
    const odd = structuredClone(EXALT);
    delete odd.roles.tank;
    const { app } = mount({ behaviour: { "/data/pal-mnk-ber/exalt.json": { json: odd } } });
    await open(app);
    document.querySelector('input[name="role"][value="tank"]').checked = true;
    document.querySelector('input[name="role"][value="tank"]').dispatchEvent(new Event("change", { bubbles: true }));
    await flush(app);
    expect($("#exalt-plan-lead").textContent).toContain("no effect plan");
    expect(document.querySelectorAll("#exalt-lists table")).toHaveLength(0);
  });
});

describe("the plan follows the kit", () => {
  const records = new Map(ITEMS.items.map((record) => [record.key ?? `w${record.id}`, record]));
  const donors = new Map(
    Object.entries(EFFECTS.items).map(([key, [, , slots, classes, twoHand, arrival]]) => [
      key,
      itemInfo({ slots: slots.split(" "), classes: classes.split(" "), weapon: { skill: twoHand ? "2H" : "" }, tier_rule: arrival === 4 ? "drop" : arrival === 0 ? "fixed0" : "spell" }),
    ]),
  );
  const infos = (key) => (records.has(key) ? itemInfo(records.get(key), ITEMS.defaults) : (donors.get(key) ?? null));
  const matched = (role, kit, tier) =>
    planKit({ options: EXALT.roles[role], kit, items: infos, effects: new Map(EFFECTS.effects.map((row) => [row.id, row])), mass: EFFECTS.mass, classes: EXALT.classes, tier });

  it("makes the plan again for another tier (the kit of the shard at that tier), reads the item list once, and leaves the lists alone", async () => {
    const { app, calls } = mount();
    await open(app);
    const lists = $("#exalt-lists").innerHTML;
    const tier = document.querySelector("#sw-tier");
    tier.value = "0";
    tier.dispatchEvent(new Event("change", { bubbles: true }));
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("matched in your browser"));
    const shard = read(resolve(CONTRACT, "data/strict-own.json"));
    const row = shard.rows.find((r) => r[0] === "OGR" && r[1] === "balanced" && r[2] === 0 && r[3] === app.shown.scenario.setup);
    const kit = shard.kits[row[4]].map((index, place) => (index < 0 ? null : { place: PLACES[place], key: shard.items[index][0] })).filter(Boolean);
    const want = matched("balanced", kit, 0);
    expect(planNames()).toEqual(want.rows.map((r) => names.get(r.e)));
    expect(want.rows).toEqual([]); // (nothing opens at +0)
    expect($("#exalt-noroom").textContent).toContain("below the tier its socket opens at");
    expect($("#exalt-lists").innerHTML).toBe(lists);
    tier.value = "4";
    tier.dispatchEvent(new Event("change", { bubbles: true }));
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("as the site worked it out"));
    expect(planNames()).toEqual(EXALT.roles.balanced.plan.map((r) => names.get(r.e)));
    expect(calls.filter((c) => c === ITEM_PATH)).toHaveLength(1);
  });

  it("offers the kit of Equip now as a second source, matched with the records the Upgrade section has, tier by tier", async () => {
    const { app, calls } = mount();
    await open(app);
    expect($(".exalt-source").hidden).toBe(true);
    const keys = EXALT.roles.balanced.plan.map((row) => row.h);
    const unique = [...new Set(keys)];
    const kit = Array.from({ length: 22 }, () => null);
    unique.forEach((key, index) => (kit[index === 0 ? 0 : PLACES.indexOf(EXALT.roles.balanced.plan.find((row) => row.h === key).p)] = { key, name: `Mine ${index}`, tier: index % 2 === 0 ? 4 : 1 }));
    app.setEquipKit({ kit, record: (key) => records.get(key) ?? null, defaults: ITEMS.defaults });
    await flush(app);
    expect($(".exalt-source").hidden).toBe(false);
    $('input[name="exalt-source"][value="equip"]').click();
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("Equip now"));
    const want = matched("balanced", kit.map((it, i) => (it ? { place: PLACES[i], key: it.key, tier: it.tier } : null)).filter(Boolean), 0);
    expect(planNames()).toEqual(want.rows.map((r) => names.get(r.e)));
    expect(want.rows.length).toBeGreaterThan(0);
    const lowKeys = new Set(kit.filter((it) => it && it.tier === 1).map((it) => it.key));
    expect(want.rows.filter((row) => lowKeys.has(row.h)).every((row) => row.k === "focus")).toBe(true); // (an item at +1 opens the focus socket and none above it)
    expect(want.rows.some((row) => !lowKeys.has(row.h) && row.k !== "focus")).toBe(true);
    expect(calls).not.toContain(ITEM_PATH);
    // the kit goes away: the plan is the page's again
    app.setEquipKit(null);
    await flush(app);
    expect($(".exalt-source").hidden).toBe(true);
    expect($("#exalt-plan-lead").textContent).toContain("Wear this");
  });
});

describe("what goes wrong", () => {
  it("refuses a file of another release, tells the page, and offers a reload", async () => {
    const other = { ...structuredClone(EFFECTS), release: "data-2020-01-01" };
    const reload = vi.fn();
    document.body.innerHTML = PAGE_HTML;
    const calls = [];
    const app = initTrio({ document, window, fetch: makeFetch(calls, { "/data/effects.json": { json: other } }), reload });
    await open(app);
    expect($("#exalt-status").textContent).toContain("Data updated");
    expect($("#status").textContent).toContain("Data updated");
    expect($("#exalt-plan-table")).toBeNull();
    $("#exalt-status button").click();
    expect(reload).toHaveBeenCalled();
  });

  it("says that the files could not be had, and tries again when asked", async () => {
    const behaviour = { "/data/effects.json": "offline" };
    const { app } = mount({ behaviour });
    await open(app);
    expect($("#exalt-status").textContent).toContain("Couldn't load the effects");
    expect($("#exalt-plan-table")).toBeNull();
    delete behaviour["/data/effects.json"];
    $("#exalt-status button").click();
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-table")).not.toBeNull());
    expect($("#exalt-status").hidden).toBe(true);
  });

  it("keeps the plan of the file, and says so, when the item list for another kit cannot be had", async () => {
    const { app } = mount({ behaviour: { "/engine-manifest.json": "offline" } });
    await open(app);
    const tier = document.querySelector("#sw-tier");
    tier.value = "0";
    tier.dispatchEvent(new Event("change", { bubbles: true }));
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("Couldn't load the item list"));
    expect(planNames()).toEqual(EXALT.roles.balanced.plan.map((r) => names.get(r.e)));
  });

  it("says that the code could not be had", async () => {
    const { app } = mount({ loadExalt: () => Promise.reject(new Error("no chunk")) });
    await open(app);
    expect($("#exalt-status").hidden).toBe(false);
    expect($("#exalt-status").textContent).toContain("Reload the page");
    expect($("#announce").textContent).toContain("Reload the page");
  });

  it("refuses an address for the files that is not one of the page's own", async () => {
    const hostile = PAGE_HTML.replace('data-effects="/data/effects.json"', 'data-effects="https://elsewhere.test/effects.json"');
    const { app, calls, loads } = mount({ html: hostile });
    await open(app);
    expect(loads).toEqual([]);
    expect(calls.filter((c) => /elsewhere/.test(c))).toEqual([]);
  });
});

// ---- the fix round of part 2 ---------------------------------------------------------------------------------------------------------------------------

describe("the kit shown is the default kit only when the view is the default view", () => {
  const setRace = (value) => {
    const race = $("#sw-race");
    race.value = value;
    race.dispatchEvent(new Event("change", { bubbles: true }));
  };

  it("matches the plan again when only the race is changed (the role's best setup, every other assumption the default)", async () => {
    const { app } = mount();
    await open(app);
    expect(app.exaltShown.exact).toBe(true);
    const other = [...$("#sw-race").options].map((o) => o.value).find((v) => v !== "OGR");
    setRace(other);
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("matched in your browser"));
    expect(app.exaltShown.exact).toBe(false);
    expect(app.exaltShown.race).toBe(other);
    setRace("OGR");
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("as the site worked it out"));
    expect(app.exaltShown.exact).toBe(true);
  });

  it("is not the default view for a tier other than the default", async () => {
    const { app } = mount();
    await open(app);
    const tier = $("#sw-tier");
    tier.value = "0";
    tier.dispatchEvent(new Event("change", { bubbles: true }));
    await flush(app);
    expect(app.exaltShown.exact).toBe(false);
    expect(app.exaltShown.tier).toBe(0);
  });

  it("is not the default kit before the first view is painted, when the address asks for another view: the plan of the file is not shown for it", async () => {
    const { app } = mount({ search: "?race=TRL" });
    expect(app.exaltShown.exact).toBe(false); // (nothing is painted yet: the address asks for the Troll)
    await open(app);
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("matched in your browser"));
    expect($("#exalt-plan-lead").textContent).toContain("Troll");
    expect(app.exaltShown.race).toBe("TRL");
  });

  it("is the default kit when the address names the default view", async () => {
    const { app } = mount({ search: "?race=OGR&role=balanced&tier=4&buffs=own" });
    expect(app.exaltShown.exact).toBe(true);
    await open(app);
    expect($("#exalt-plan-lead").textContent).toContain("as the site worked it out");
  });
});

describe("a failure leaves nothing of an earlier view", () => {
  it("tries the item list again after it failed: the failed read is not kept", async () => {
    const behaviour = { "/engine-manifest.json": "offline" };
    const { app, calls } = mount({ behaviour });
    await open(app);
    const tier = $("#sw-tier");
    tier.value = "0";
    tier.dispatchEvent(new Event("change", { bubbles: true }));
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("Couldn't load the item list"));
    delete behaviour["/engine-manifest.json"];
    tier.value = "3";
    tier.dispatchEvent(new Event("change", { bubbles: true }));
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("matched in your browser"));
    expect(calls.filter((c) => c === "/engine-manifest.json")).toHaveLength(2);
  });

  it("clears the old plan and the old lists, and says so, when the file does not fit the view (a plan row of an effect the shared file lacks)", async () => {
    const odd = structuredClone(EXALT);
    odd.roles.tank.plan[0].e = "e999";
    const { app } = mount({ behaviour: { "/data/pal-mnk-ber/exalt.json": { json: odd } } });
    await open(app);
    expect($("#exalt-plan-table")).not.toBeNull();
    document.querySelector('input[name="role"][value="tank"]').checked = true;
    document.querySelector('input[name="role"][value="tank"]').dispatchEvent(new Event("change", { bubbles: true }));
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("Couldn't show"));
    expect($("#exalt-plan-table")).toBeNull();
    expect($("#exalt-lists table")).toBeNull();
    expect($("#announce").textContent).toContain("Couldn't show");
  });

  it("treats a role with no list of a kind, or a list that is no list, as having none", async () => {
    const odd = structuredClone(EXALT);
    delete odd.roles.balanced.worn;
    odd.roles.balanced.proc = "none";
    const { app } = mount({ behaviour: { "/data/pal-mnk-ber/exalt.json": { json: odd } } });
    await open(app);
    expect($("#exalt-plan-table")).not.toBeNull();
    expect($("#exalt-worn")).toBeNull();
    expect($("#exalt-proc")).toBeNull();
    expect($("#exalt-focus")).not.toBeNull();
  });
});

describe("names and links", () => {
  const equipKit = (entries, record) => {
    const kit = Array.from({ length: 22 }, () => null);
    entries.forEach((entry, index) => (kit[index] = entry));
    return { kit, record, defaults: ITEMS.defaults };
  };

  it("links the host names of a kit that has pages, and not an item of Equip now that has none", async () => {
    const { app } = mount();
    await open(app);
    expect($("#exalt-plan-table tbody th a")).not.toBeNull(); // (the kit of the page: every item has a page)
    const hosts = EXALT.roles.balanced.plan.map((row) => row.h);
    const slots = ["HEAD", "FACE", "EAR", "NECK", "BACK", "WRIST", "FINGER", "WAIST", "ARMS", "SHOULDERS", "HANDS", "CHEST", "LEGS", "FEET"];
    const hidden = { ...ITEMS.items[0], evidence: { level: "hidden" }, key: hosts[0], name: "Secret", slots };
    app.setEquipKit(equipKit([{ key: hosts[0], name: "Secret", tier: 4 }], (key) => (key === hosts[0] ? hidden : null)));
    await flush(app);
    $('input[name="exalt-source"][value="equip"]').click();
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("Equip now"));
    const secret = [...document.querySelectorAll("#exalt-plan-table tbody th")].find((th) => th.textContent.includes("Secret"));
    expect(secret).toBeDefined();
    expect(secret.querySelector("a")).toBeNull();
  });

  it("falls back to the names of the files for a kit entry that has no name, and never writes undefined", async () => {
    const { app } = mount();
    await open(app);
    const hosts = [...new Set(EXALT.roles.balanced.plan.map((row) => row.h))];
    const record = (key) => ITEMS.items.find((r) => (r.key ?? `w${r.id}`) === key) ?? null;
    app.setEquipKit(equipKit(hosts.map((key) => ({ key, name: undefined, tier: 4 })), record));
    await flush(app);
    $('input[name="exalt-source"][value="equip"]').click();
    await flush(app);
    await vi.waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("Equip now"));
    expect($("#exalt-plan-table").textContent).not.toContain("undefined");
    expect($("#exalt-plan-table").textContent).toContain(EXALT.names[hosts[0]]);
  });
});

describe("the status of the section", () => {
  it("is cleared by a later successful wake, and a failed wake of a closed section is not announced", async () => {
    let fail = true;
    const loads = [];
    const real = () => import("../pipeline/trioforge/site/static/ui/exalt.js");
    const { app } = mount({ loadExalt: () => (loads.push(1), fail ? Promise.reject(new Error("no chunk")) : real()) });
    app.wakeExalt($("#exalt")); // (what the observer does when the closed section is scrolled to)
    await flush(app);
    expect($("#exalt-status").hidden).toBe(false);
    expect($("#announce").textContent).toBe("");
    fail = false;
    await open(app); // (opened: it wakes again, and this time the code comes)
    await vi.waitFor(() => expect($("#exalt-plan-table")).not.toBeNull());
    expect($("#exalt-status").hidden).toBe(true);
    expect($("#exalt-status").textContent).toBe("");
    expect(loads).toHaveLength(2);
  });

  it("announces a failed wake of an open section", async () => {
    const { app } = mount({ loadExalt: () => Promise.reject(new Error("no chunk")) });
    await open(app);
    expect($("#announce").textContent).toContain("Reload the page");
  });
});
