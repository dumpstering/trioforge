// @vitest-environment jsdom
//
// The exalt hints of Wear this (static/ui/exalt.js and what trio.js does for it): after the page has shown, the page loads the code of the section Effects to exalt and its two files
// without waiting for the section to be opened (when it is asked to: `exaltAhead`, which the page's own script gives), and under each place of the kit that the plan gives an effect
// there is one short line saying which effect to put on that item and which donor item it comes from. The lines follow the kit that is drawn, and are not there when the kit is being
// worked out, when the role has no plan, or when the files could not be had. Run against the committed contract of the section (fixtures/site/contract-exalt/), as exalt.test.mjs is.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PLACES, itemInfo, planKit } from "../pipeline/trioforge/site/static/ui/exalt-plan.js";
import { focusCeiling, focusMeaning, meaning } from "../pipeline/trioforge/site/static/ui/exalt.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const WITH_EFFECTS = resolve(HERE, "../fixtures/site/contract-exalt");
const read = (path) => JSON.parse(readFileSync(resolve(path), "utf8"));
const EFFECTS = read(resolve(WITH_EFFECTS, "data/effects.json"));
const EXALT = read(resolve(WITH_EFFECTS, "data/exalt.json"));
const ITEMS = read(resolve(HERE, "../fixtures/site/results/items.json"));
const PAGE_HTML = readFileSync(resolve(WITH_EFFECTS, "trio-main.html"), "utf8");
const ITEM_PATH = "/assets/engine/data/items-0123456789ABCDEF.json";
const $ = (selector) => document.querySelector(selector);
const BODY = () => [...document.querySelectorAll("#kit-body tr")];
const ROW = (place) => BODY()[PLACES.indexOf(place)];
/** What a line says, without the popup of its effect and the link to the plan (they have their own tests). */
const lineText = (node) => {
  const copy = node.cloneNode(true);
  for (const extra of copy.querySelectorAll(".exalt-tip, .exalt-hint-plan")) extra.remove();
  return copy.textContent.replace(/\s+/g, " ").trim();
};
const hints = (place) => [...ROW(place).querySelectorAll(".exalt-hint")].map(lineText);
const describeEffect = (effect) => (effect.k === "focus" && effect.f ? focusMeaning(effect) : meaning(effect));
const allHints = () => [...document.querySelectorAll("#kit-body .exalt-hint")];
const effectName = new Map(EFFECTS.effects.map((row) => [row.id, row.n]));
const isFile = (path) => /effects\.json|exalt\.json/.test(path);

const waitFor = (check) => vi.waitFor(check, { timeout: 2000 });
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

/** A fetch that answers the files of the section, the manifest and the item list, keeps a list of what was asked for, and can hold a file back until the test lets it go. */
function makeFetch(calls, behaviour = {}, gates = {}) {
  return async (url) => {
    calls.push(String(url));
    const answer = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (gates[url]) await gates[url];
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

let idle = [];
/** Run what the page asked the browser to do when it is idle. */
const runIdle = () => idle.splice(0).forEach((run) => run());

function mount({ behaviour = {}, gates = {}, html = PAGE_HTML, loadExalt, search = "", ahead = true, effects = null, weights = null } = {}) {
  document.body.innerHTML = html;
  window.history.replaceState(null, "", `/trio/pal-mnk-ber/${search}`);
  const calls = [];
  const loads = [];
  const behaviours = effects ? { ...behaviour, "/data/pal-mnk-ber/exalt.json": { json: effects } } : behaviour;
  const app = initTrio({
    document,
    window,
    fetch: makeFetch(calls, behaviours, gates),
    exaltAhead: ahead,
    loadExalt: loadExalt ?? (() => (loads.push(1), import("../pipeline/trioforge/site/static/ui/exalt.js"))),
    loadWeights: weights ?? undefined,
  });
  return { app, calls, loads };
}

/** Mount, let the page be idle, and wait for the hints. */
async function shown(options) {
  const made = mount(options);
  runIdle();
  await waitFor(() => expect(allHints().length).toBeGreaterThan(0));
  return made;
}

/** Open the section, as a visitor does (the toggle event is what the page listens to), and wait for its plan. */
async function openSection() {
  const section = $("#exalt");
  section.open = true;
  section.dispatchEvent(new Event("toggle"));
  await waitFor(() => expect($("#exalt-plan-table")).not.toBeNull());
}

const change = (selector, value) => {
  const node = $(selector);
  node.value = value;
  node.dispatchEvent(new Event("change", { bubbles: true }));
};
const chooseRole = (value) => {
  const radio = $(`input[name="role"][value="${value}"]`);
  radio.checked = true;
  radio.dispatchEvent(new Event("change", { bubbles: true }));
};

beforeEach(() => {
  idle = [];
  delete window.IntersectionObserver;
  window.requestIdleCallback = (run) => idle.push(run);
});
afterEach(() => {
  document.documentElement.classList.remove("exalt-tip-open"); // (a page torn down with a text open leaves the mark: the next test starts clean)
  document.body.replaceChildren();
  delete window.requestIdleCallback;
});

describe("the load after the page has shown", () => {
  it("asks for nothing until the page is idle, then loads the code and the two files, once, without the section being opened", async () => {
    const { app, calls, loads } = mount();
    await app.whenIdle();
    expect(calls.filter(isFile)).toEqual([]);
    expect(loads).toEqual([]);
    runIdle();
    await waitFor(() => expect(allHints().length).toBeGreaterThan(0));
    expect(loads).toHaveLength(1);
    expect(calls.filter(isFile).sort()).toEqual(["/data/effects.json", "/data/pal-mnk-ber/exalt.json"]);
    expect($("#exalt").open).toBe(false);
  });

  it("does nothing of the kind when the page does not ask for it", async () => {
    const { app, calls, loads } = mount({ ahead: false });
    runIdle();
    await app.whenIdle();
    await tick();
    expect(calls.filter(isFile)).toEqual([]);
    expect(loads).toEqual([]);
    expect(allHints()).toHaveLength(0);
  });

  it("uses a short timeout where the browser has no idle callback", async () => {
    delete window.requestIdleCallback;
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    try {
      const { calls } = mount();
      expect(calls.filter(isFile)).toEqual([]);
      await vi.advanceTimersByTimeAsync(1000);
      vi.useRealTimers();
      await waitFor(() => expect(calls.filter(isFile).length).toBe(2));
    } finally {
      vi.useRealTimers();
    }
  });

  it("waits for the first view of an address that asks for another view to be drawn", async () => {
    const { app, calls } = mount({ search: "?race=TRL" });
    runIdle();
    await waitFor(() => expect(calls.filter(isFile)).toHaveLength(2));
    await app.whenIdle();
    const shard = calls.findIndex((url) => /strict-own\.json$/.test(url));
    expect(shard).toBeGreaterThanOrEqual(0);
    expect(calls.findIndex(isFile)).toBeGreaterThan(shard);
  });

  it("fetches each file once whether the inline hints load first or the section is opened first", async () => {
    const first = await shown();
    const section = $("#exalt");
    section.open = true;
    section.dispatchEvent(new Event("toggle"));
    await first.app.whenIdle();
    await tick();
    expect(first.loads).toHaveLength(1);
    expect(first.calls.filter(isFile)).toHaveLength(2);
    expect($("#exalt-plan-table")).not.toBeNull();
    document.body.replaceChildren();
    idle = [];
    const second = mount();
    const opened = $("#exalt");
    opened.open = true;
    opened.dispatchEvent(new Event("toggle"));
    await waitFor(() => expect(allHints().length).toBeGreaterThan(0));
    runIdle();
    await second.app.whenIdle();
    await tick();
    expect(second.loads).toHaveLength(1);
    expect(second.calls.filter(isFile)).toHaveLength(2);
  });
});

describe("the lines under the places of Wear this", () => {
  it("say which effect goes on the item, from which donor, how hard the donor is to get, and what to level", async () => {
    await shown();
    // the Back place: a click effect from a donor that has to be upgraded too
    expect(hints("BACK")).toEqual(["Exalt: Alacrity (click, +2) from Harrowgate Shawl (Quest or crafted); level both to +2"]);
    // the Head: a donor that needs no tier
    expect(hints("HEAD")).toEqual(["Exalt: Spell Haste II (focus, +1) from Crown of the Vanguard (Vendor); level this item to +1"]);
    // the Neck: a donor that needs the tier too
    expect(hints("NECK")).toEqual(["Exalt: Heritage of Mistmoore (worn, +3) from Choker of Seven Pebbles (Quest or crafted); level both to +3"]);
    // a place with two effects has a line for each, in the order of the plan
    expect(hints("CHEST")).toEqual([
      "Exalt: Improved Healing III (focus, +1) from Mantle of the Faithful (Raid drop); level this item to +1",
      "Exalt: Ultravision (worn, +3) from Breastplate of Warding (Drop); level this item to +3",
    ]);
    // a place with no effect has no line
    expect(hints("FACE")).toEqual([]);
  });

  it("are put after the name of the item in its cell, before the stats, and are made with the DOM (a name is text, never markup)", async () => {
    await shown();
    const cell = ROW("RANGE").cells[1];
    expect(lineText(cell.querySelector(".exalt-hint"))).toContain("Earthquake (proc, +4) from Short Bow of the Fallen");
    expect(cell.querySelector("b")).toBeNull();
    const position = (node) => [...cell.querySelectorAll("*")].indexOf(node);
    expect(position(cell.querySelector(".exalt-hints"))).toBeLessThan(position(cell.querySelector('[data-f="more"]')));
    expect(cell.querySelector('[data-f="name"]')).not.toBeNull();
    expect(cell.querySelectorAll(".exalt-hints")).toHaveLength(1);
  });

  it("say nothing when the effect is already on the item", async () => {
    await shown();
    const onItem = EXALT.roles.balanced.plan.filter((row) => row.d === row.h);
    expect(onItem.length).toBeGreaterThan(3);
    for (const row of onItem) expect(hints(row.p).join(" ")).not.toContain(effectName.get(row.e));
    expect(hints("EAR1")).toEqual([]);
    expect(allHints()).toHaveLength(EXALT.roles.balanced.plan.filter((row) => row.d !== row.h).length);
  });

  it("are marked as secondary: a block of their own in the cell, readable in reading order, each with a link to the plan", async () => {
    await shown();
    const line = ROW("BACK").querySelector(".exalt-hint");
    const link = line.querySelector("a.exalt-hint-plan");
    expect(link).not.toBeNull();
    expect(link.textContent).toBe("In the plan");
    expect(link.getAttribute("aria-label")).toContain("Alacrity");
    expect(link.getAttribute("href")).toMatch(/^#exalt/);
    expect(line.querySelectorAll("[aria-hidden]")).toHaveLength(0);
    expect(lineText(line).startsWith("Exalt: ")).toBe(true);
    // the section's own plan is drawn when the link opens it
    const section = $("#exalt");
    expect($("#exalt-plan-table")).toBeNull();
    link.click();
    expect(section.open).toBe(true);
    await waitFor(() => expect($("#exalt-plan-table")).not.toBeNull());
  });

  it("go to the plan row of the effect and open the section when the link is used", async () => {
    await shown();
    const link = ROW("BACK").querySelector(".exalt-hint a.exalt-hint-plan");
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect($("#exalt").open).toBe(true);
    await waitFor(() => expect(document.activeElement?.id).toBe(link.getAttribute("href").slice(1)));
    const target = document.activeElement;
    expect(target.textContent).toContain("Alacrity");
    expect(target.closest("#exalt-plan-table")).not.toBeNull();
  });
});

describe("the lines follow the kit that is drawn", () => {
  const records = new Map(ITEMS.items.map((record) => [record.key ?? `w${record.id}`, record]));
  const donors = new Map(
    Object.entries(EFFECTS.items).map(([key, [, , slots, classes, twoHand, arrival]]) => [
      key,
      itemInfo({ slots: slots.split(" "), classes: classes.split(" "), weapon: { skill: twoHand ? "2H" : "" }, tier_rule: arrival === 4 ? "drop" : arrival === 0 ? "fixed0" : "spell" }),
    ]),
  );
  const infos = (key) => (records.has(key) ? itemInfo(records.get(key), ITEMS.defaults) : (donors.get(key) ?? null));
  const matched = (role, kit, tier) => planKit({ options: EXALT.roles[role], kit, items: infos, effects: new Map(EFFECTS.effects.map((row) => [row.id, row])), mass: EFFECTS.mass, classes: EXALT.classes, tier });

  it("change with the role: the plan of the other role, from the file", async () => {
    await shown();
    chooseRole("tank");
    await waitFor(() => expect(hints("BACK")).toEqual(["Exalt: Superior Healing (click, +2) from Mossgrey Wrap (Vendor); level both to +2"]));
    const tank = EXALT.roles.tank.plan.filter((row) => row.d !== row.h);
    expect(allHints()).toHaveLength(tank.length);
  });

  it("are the matcher's lines for the kit of another tier, read from the item list once, and gone at a tier where no socket is open", async () => {
    const { app, calls } = await shown();
    change("#sw-tier", "0");
    await waitFor(() => expect(app.exaltShown.tier).toBe(0));
    await waitFor(() => (runIdle(), expect(calls).toContain(ITEM_PATH)));
    await waitFor(() => expect(allHints()).toHaveLength(0)); // (nothing opens at +0)
    change("#sw-tier", "10");
    await waitFor(() => (runIdle(), expect(allHints().length).toBeGreaterThan(0)));
    const shard = read(resolve(CONTRACT, "data/strict-own.json"));
    const row = shard.rows.find((r) => r[0] === "OGR" && r[1] === "balanced" && r[2] === 10 && r[3] === app.shown.scenario.setup);
    const kit = shard.kits[row[4]].map((index, place) => (index < 0 ? null : { place: PLACES[place], key: shard.items[index][0] })).filter(Boolean);
    const want = matched("balanced", kit, 10).rows.filter((r) => r.d !== r.h);
    expect(want.length).toBeGreaterThan(0);
    expect(allHints().map((node) => node.querySelector(".exalt-eff button").textContent).sort()).toEqual(want.map((r) => effectName.get(r.e)).sort());
    for (const r of want) expect(hints(r.p).some((text) => text.includes(effectName.get(r.e)))).toBe(true);
    change("#sw-tier", "4");
    await waitFor(() => (runIdle(), expect(hints("BACK")).toEqual(["Exalt: Alacrity (click, +2) from Harrowgate Shawl (Quest or crafted); level both to +2"])));
    expect(calls.filter((c) => c === ITEM_PATH)).toHaveLength(1);
  });

  it("are not there while a kit is being matched: the lines of the kit that left are removed at once, and never stay under another kit", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const made = mount({ gates: { "/engine-manifest.json": gate } });
    runIdle();
    await waitFor(() => expect(allHints().length).toBeGreaterThan(0));
    const before = allHints().length;
    expect(before).toBeGreaterThan(0);
    change("#sw-tier", "10");
    await waitFor(() => expect(made.app.exaltShown.tier).toBe(10));
    await tick();
    await tick();
    expect(made.calls).not.toContain("/engine-manifest.json"); // (the section is closed: the item list waits for the browser to be idle)
    expect(allHints()).toHaveLength(0);
    runIdle();
    await waitFor(() => expect(made.calls).toContain("/engine-manifest.json")); // (the plan for this kit is being made: the item list has been asked for and is held back)
    expect(allHints()).toHaveLength(0);
    release();
    await waitFor(() => expect(allHints().length).toBeGreaterThan(0));
  });

  it("are not there while the optimizer works the kit out, and come back for the kit it drew", async () => {
    const made = mount({ weights: () => new Promise(() => {}) }); // (the chunk of the optimizer never comes: the kit shown stays the shard's stand-in)
    runIdle();
    await waitFor(() => expect(allHints().length).toBeGreaterThan(0));
    $("#buffs-raid").checked = true;
    $("#buffs-raid").dispatchEvent(new Event("change", { bubbles: true }));
    await waitFor(() => expect(made.app.exaltShown.pending).toBe(true));
    await tick();
    await tick();
    expect(allHints()).toHaveLength(0);
    const kit = made.app.shown.scenario.kit;
    expect(made.app.drawSolved({ items: kit, tier: 4, hasteAssumed: 0, value: 0, kind: "buffs" })).toBe(true);
    expect(made.app.exaltShown.pending).toBe(false);
    await waitFor(() => (runIdle(), expect(allHints().length).toBeGreaterThan(0)));
  });

  it("are not there for a role the file has no plan for", async () => {
    const odd = structuredClone(EXALT);
    delete odd.roles.tank;
    await shown({ effects: odd });
    chooseRole("tank");
    await waitFor(() => expect(allHints()).toHaveLength(0));
    chooseRole("balanced");
    await waitFor(() => expect(allHints().length).toBeGreaterThan(0));
  });

  it("are not there for a view that is not drawn yet (an address that asks for another race), and come when it is", async () => {
    const made = mount({ search: "?race=TRL" });
    runIdle();
    await waitFor(() => expect(made.app.exaltShown.race).toBe("TRL"));
    await waitFor(() => expect(made.calls.filter(isFile)).toHaveLength(2));
    await made.app.whenIdle();
    await waitFor(() => expect(made.app.exaltShown.kit).not.toBeNull());
    const shard = read(resolve(CONTRACT, "data/strict-own.json"));
    const row = shard.rows.find((r) => r[0] === "TRL" && r[1] === "balanced" && r[2] === 4 && r[3] === made.app.shown.scenario.setup);
    const kit = shard.kits[row[4]].map((index, place) => (index < 0 ? null : { place: PLACES[place], key: shard.items[index][0] })).filter(Boolean);
    const want = matched("balanced", kit, 4).rows.filter((r) => r.d !== r.h);
    await waitFor(() => (runIdle(), expect(allHints()).toHaveLength(want.length)));
  });
});

describe("a load that fails leaves the kit table as it is", () => {
  const snapshot = () => $("#kit-body").innerHTML;

  it("for a file that cannot be had: no line, no error text in the table, nothing said aloud, and the section's own retry stays", async () => {
    const behaviour = { "/data/effects.json": "offline" };
    const { app } = mount({ behaviour });
    const before = snapshot();
    runIdle();
    await waitFor(() => expect($("#exalt-status").hidden).toBe(false));
    await app.whenIdle();
    expect(snapshot()).toBe(before);
    expect(allHints()).toHaveLength(0);
    expect($("#kit").textContent).not.toMatch(/Couldn't/);
    expect($("#announce").textContent).toBe("");
    expect($("#exalt-status").textContent).toContain("Couldn't load the effects");
    // the retry of the section is what it was
    delete behaviour["/data/effects.json"];
    $("#exalt-status button").click();
    await waitFor(() => expect(allHints().length).toBeGreaterThan(0));
    expect($("#exalt-status").hidden).toBe(true);
  });

  it("for a chunk that cannot be had", async () => {
    const { app } = mount({ loadExalt: () => Promise.reject(new Error("no chunk")) });
    const before = snapshot();
    runIdle();
    await app.whenIdle();
    await tick();
    expect(snapshot()).toBe(before);
    expect(allHints()).toHaveLength(0);
    expect($("#announce").textContent).toBe("");
    expect($("#kit").textContent).not.toMatch(/Couldn't|Reload the page/);
  });

  it("for a file of another release: the page is told, the table is not changed", async () => {
    const other = { ...structuredClone(EFFECTS), release: "data-2020-01-01" };
    const { app } = mount({ behaviour: { "/data/effects.json": { json: other } } });
    const before = snapshot();
    runIdle();
    await waitFor(() => expect($("#status").textContent).toContain("Data updated"));
    await app.whenIdle();
    expect(snapshot()).toBe(before);
    expect(allHints()).toHaveLength(0);
  });
});

describe("the donor items to farm", () => {
  const donorsOf = () => [...document.querySelectorAll("#exalt-donors li")].map((li) => li.textContent);

  it("lists each donor item of the plan that is not in the kit, once, with how hard it is to get and the tier it needs, in the order of the plan", async () => {
    await shown();
    await openSection();
    expect(donorsOf()).toEqual([
      "Crown of the Vanguard: Vendor, no level needed",
      "Mantle of the Faithful: Raid drop, no level needed",
      "Harrowgate Shawl: Quest or crafted, needs +2",
      "Pauldrons of the Vanguard: Drop, no level needed",
      "Choker of Seven Pebbles: Quest or crafted, needs +3",
      "Breastplate of Warding: Drop, no level needed",
      "Short Bow of the Fallen: Drop, no level needed",
    ]);
    const heading = $("#exalt-donors-h");
    expect(heading.textContent).toBe("Donor items to farm");
    expect($("#exalt-plan").firstElementChild.id).toBe("exalt-donors-h"); // (at the top of the plan)
    expect(new Set(donorsOf()).size).toBe(donorsOf().length);
  });

  it("has no duplicates and skips a donor that is in the kit, even when it is not the host", async () => {
    const odd = structuredClone(EXALT);
    const plan = odd.roles.balanced.plan;
    plan[1].d = plan[0].d; // (one donor for two effects: listed once)
    plan[2].d = "w80712"; // (an item that is in the kit, on another place than the host: not to be farmed)
    await shown({ effects: odd });
    await openSection();
    const names = donorsOf();
    expect(new Set(names).size).toBe(names.length);
    expect(names.filter((text) => text.startsWith("Crown of the Vanguard"))).toHaveLength(1);
    expect(names.some((text) => text.startsWith("Weaver's Evening Drape"))).toBe(false);
    expect(names.some((text) => text.startsWith("Rune-etched Earring"))).toBe(false);
  });

  it("asks for the highest tier a donor needs when it serves two effects", async () => {
    const odd = structuredClone(EXALT);
    const plan = odd.roles.balanced.plan;
    const shawl = plan.find((row) => row.k === "click" && row.u === 1);
    const other = plan.find((row) => row.k === "click" && row.u === 0); // (after the shawl's row in the plan)
    other.d = shawl.d;
    other.u = 0;
    await shown({ effects: odd });
    await openSection();
    const lines = donorsOf().filter((text) => text.startsWith("Harrowgate Shawl"));
    expect(lines).toEqual(["Harrowgate Shawl: Quest or crafted, needs +2"]);
  });
});

describe("the section's words", () => {
  it("has the summary 'Exalt plan: effects to move onto this kit' and keeps the planning-aid note", () => {
    document.body.innerHTML = PAGE_HTML;
    expect($("#exalt > summary").textContent).toBe("Exalt plan: effects to move onto this kit");
    expect($("#exalt > .note").textContent).toContain("A planning aid, not a measured best-in-slot");
  });
});

// ---- what an effect does, on hover, on focus and on a tap -------------------------------------------------------------------------------------------------------

describe("the description of an effect", () => {
  const eff = (scope) => scope.querySelector(".exalt-eff");
  const tip = (wrap) => wrap.querySelector(".exalt-tip");
  const button = (wrap) => wrap.querySelector("button");
  const enter = (node) => node.dispatchEvent(new MouseEvent("mouseenter"));
  const leave = (node) => node.dispatchEvent(new MouseEvent("mouseleave"));
  const escape = (node) => node.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  const cap = EFFECTS.cap ?? 50;
  const ceilingOf = (effect) => (effect.k === "focus" && effect.f ? focusCeiling(effect, cap) : "");
  const notes = (wrap) => [...tip(wrap).querySelectorAll(".exalt-tip-note")].map((n) => n.textContent).filter((t) => !t.startsWith("Unverified"));

  async function plan() {
    const made = await shown();
    const section = $("#exalt");
    section.open = true;
    section.dispatchEvent(new Event("toggle"));
    await waitFor(() => expect($("#exalt-plan-table")).not.toBeNull());
    return made;
  }

  it("is on every effect name of the inline lines, with the text of the section's own words for it", async () => {
    await shown();
    const lines = allHints();
    expect(lines.length).toBeGreaterThan(5);
    let ceilings = 0;
    for (const line of lines) {
      const wrap = eff(line);
      const effect = EFFECTS.effects.find((e) => `#exalt-row-${e.id}` === line.querySelector("a.exalt-hint-plan").getAttribute("href"));
      expect(effect).toBeDefined();
      expect(button(wrap).textContent).toBe(effect.n);
      expect(tip(wrap).querySelector(".exalt-tip-text").textContent).toBe(describeEffect(effect));
      const ceiling = ceilingOf(effect);
      expect(notes(wrap)).toEqual(ceiling ? [ceiling] : []);
      if (ceiling) ceilings += 1;
    }
    expect(ceilings).toBeGreaterThan(0); // (the fixture has a focus with a ceiling: the note is checked on a real one)
    expect(tip(eff(ROW("HEAD").querySelector(".exalt-hint"))).textContent).toContain("faster casts");
  });

  it("is on every effect name of the table of the plan, in the cell of the effect, and the name stays the text of its own element", async () => {
    await plan();
    const rows = [...document.querySelectorAll("#exalt-plan-table tbody tr")];
    expect(rows).toHaveLength(EXALT.roles.balanced.plan.length);
    for (const row of rows) {
      const wrap = eff(row.cells[1]);
      expect(wrap).not.toBeNull();
      const name = row.cells[1].querySelector(".exalt-name");
      const effect = EFFECTS.effects.find((e) => `exalt-row-${e.id}` === row.id);
      expect(name.tagName).toBe("BUTTON");
      expect(name.textContent).toBe(effect.n);
      expect(name.textContent).toBe(button(wrap).textContent);
      expect(tip(wrap).querySelector(".exalt-tip-text").textContent).toBe(describeEffect(effect));
    }
  });

  it("is on the effects of the no-room line", async () => {
    await plan();
    const wraps = [...document.querySelectorAll("#exalt-noroom .exalt-eff")];
    expect(wraps).toHaveLength(EXALT.roles.balanced.noroom.length);
    wraps.forEach((wrap, index) => {
      const effect = EFFECTS.effects.find((e) => e.id === EXALT.roles.balanced.noroom[index].e);
      expect(button(wrap).textContent).toBe(effect.n);
      expect(tip(wrap).querySelector(".exalt-tip-text").textContent).toBe(describeEffect(effect));
    });
    expect($("#exalt-noroom").textContent).toContain("No room for");
  });

  it("adds the note of an unverified effect where the lists show one", async () => {
    await plan();
    const marked = EFFECTS.effects.filter((row) => row.x.length > 0).map((row) => row.n);
    expect(marked.length).toBeGreaterThan(0);
    const all = [...document.querySelectorAll("#exalt-plan-table .exalt-eff")];
    const shownMarked = all.filter((wrap) => marked.includes(button(wrap).textContent));
    expect(shownMarked.length).toBeGreaterThan(0);
    for (const wrap of shownMarked) expect(tip(wrap).textContent).toContain("Unverified");
    for (const wrap of all.filter((wrap) => !marked.includes(button(wrap).textContent))) expect(tip(wrap).textContent).not.toContain("Unverified");
  });

  it("is hidden until asked for, and a screen reader reads it as the description of the name", async () => {
    await shown();
    const wrap = eff(ROW("BACK").querySelector(".exalt-hint"));
    expect(tip(wrap).hidden).toBe(true);
    expect(button(wrap).hasAttribute("aria-expanded")).toBe(false); // (a tooltip trigger is not a disclosure: no "collapsed" is read)
    expect(button(wrap).getAttribute("aria-describedby")).toBe(tip(wrap).id);
    expect(tip(wrap).getAttribute("role")).toBe("tooltip");
    expect(button(wrap).getAttribute("type")).toBe("button");
    expect(button(wrap).hasAttribute("title")).toBe(false);
    const ids = [...document.querySelectorAll(".exalt-tip")].map((n) => n.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("shows on hover and goes when the pointer leaves", async () => {
    await shown();
    const wrap = eff(ROW("BACK").querySelector(".exalt-hint"));
    enter(wrap);
    expect(tip(wrap).hidden).toBe(false);
    expect(button(wrap).hasAttribute("aria-expanded")).toBe(false);
    // the description is read once, as the description of the name: the open text is not read again in the page's own order
    expect(tip(wrap).getAttribute("aria-hidden")).toBe("true");
    expect(button(wrap).getAttribute("aria-describedby")).toBe(tip(wrap).id);
    leave(wrap);
    expect(tip(wrap).hidden).toBe(true);
    expect(tip(wrap).hasAttribute("aria-hidden")).toBe(false);
  });

  it("shows on keyboard focus and goes on blur", async () => {
    await shown();
    const wrap = eff(ROW("BACK").querySelector(".exalt-hint"));
    button(wrap).focus();
    expect(tip(wrap).hidden).toBe(false);
    button(wrap).blur();
    expect(tip(wrap).hidden).toBe(true);
  });

  it("shows on a tap (click), stays while the pointer moves away, and a second tap closes it", async () => {
    await shown();
    const wrap = eff(ROW("BACK").querySelector(".exalt-hint"));
    button(wrap).click();
    expect(tip(wrap).hidden).toBe(false);
    leave(wrap);
    expect(tip(wrap).hidden).toBe(false);
    button(wrap).click();
    expect(tip(wrap).hidden).toBe(true);
  });

  it("closes on Escape (the focus stays), and a tap elsewhere closes it too", async () => {
    await shown();
    const wrap = eff(ROW("BACK").querySelector(".exalt-hint"));
    button(wrap).focus();
    expect(tip(wrap).hidden).toBe(false);
    escape(button(wrap));
    expect(tip(wrap).hidden).toBe(true);
    expect(document.activeElement).toBe(button(wrap));
    button(wrap).click();
    expect(tip(wrap).hidden).toBe(false);
    document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    expect(tip(wrap).hidden).toBe(true);
    // a tap inside the popup's own name is not "elsewhere"
    button(wrap).click();
    button(wrap).dispatchEvent(new Event("pointerdown", { bubbles: true }));
    expect(tip(wrap).hidden).toBe(false);
  });

  it("keeps the browser from scrolling the page while a text is open (the text is in the flow: a scroll would move the name from under the pointer and close it again)", async () => {
    await shown();
    const wrap = eff(ROW("BACK").querySelector(".exalt-hint"));
    expect(document.documentElement.classList.contains("exalt-tip-open")).toBe(false);
    enter(wrap);
    expect(document.documentElement.classList.contains("exalt-tip-open")).toBe(true);
    leave(wrap);
    expect(document.documentElement.classList.contains("exalt-tip-open")).toBe(false);
  });

  it("does not leave the mark on the page when the line with an open text is taken off", async () => {
    await shown();
    const wrap = eff(ROW("BACK").querySelector(".exalt-hint"));
    enter(wrap);
    expect(document.documentElement.classList.contains("exalt-tip-open")).toBe(true);
    chooseRole("tank");
    await waitFor(() => expect(hints("BACK")[0]).toContain("Superior Healing"));
    expect(wrap.isConnected).toBe(false);
    expect(document.documentElement.classList.contains("exalt-tip-open")).toBe(false);
    // and when the lines go away for good (a tier with no open socket)
    const again = eff(ROW("BACK").querySelector(".exalt-hint"));
    enter(again);
    expect(document.documentElement.classList.contains("exalt-tip-open")).toBe(true);
    change("#sw-tier", "0");
    await waitFor(() => expect(allHints()).toHaveLength(0));
    expect(document.documentElement.classList.contains("exalt-tip-open")).toBe(false);
  });

  it("starts closed on a line drawn again for a new kit", async () => {
    await shown();
    button(eff(ROW("BACK").querySelector(".exalt-hint"))).click();
    chooseRole("tank");
    await waitFor(() => expect(hints("BACK")[0]).toContain("Superior Healing"));
    expect(tip(eff(ROW("BACK").querySelector(".exalt-hint"))).hidden).toBe(true);
  });
});

// ---- what runs while the section is closed ------------------------------------------------------------------------------------------------------------------

describe("a closed section costs nothing but the hints", () => {
  const drawnCount = () => document.querySelectorAll("#exalt-plan > *").length + document.querySelectorAll("#exalt-lists > *").length;

  it("computes the hints for the default kit without the item table, and draws nothing of the section", async () => {
    const { calls } = await shown();
    expect(calls).not.toContain("/engine-manifest.json");
    expect(calls).not.toContain(ITEM_PATH);
    expect(drawnCount()).toBe(0);
    expect($("#exalt-plan-table")).toBeNull();
  });

  it("does not ask for the item table while the control's change is handled: it comes when the browser is idle, once, and the section stays undrawn", async () => {
    const { app, calls } = await shown();
    change("#sw-tier", "10");
    await waitFor(() => expect(app.exaltShown.tier).toBe(10));
    await tick();
    await tick();
    expect(calls).not.toContain("/engine-manifest.json"); // (nothing is fetched before the browser is idle)
    expect(calls).not.toContain(ITEM_PATH);
    expect(allHints()).toHaveLength(0); // (and no line of the kit that left stays)
    expect(idle.length).toBeGreaterThan(0);
    runIdle();
    await waitFor(() => expect(allHints().length).toBeGreaterThan(0));
    expect(calls.filter((c) => c === ITEM_PATH)).toHaveLength(1);
    expect(drawnCount()).toBe(0); // (no draw of the section ran for any of this)
    // another view: the table is not asked for again
    change("#sw-tier", "4");
    await waitFor(() => expect(app.exaltShown.tier).toBe(4));
    change("#sw-tier", "10");
    await waitFor(() => expect(app.exaltShown.tier).toBe(10));
    runIdle();
    await waitFor(() => expect(allHints().length).toBeGreaterThan(0));
    expect(calls.filter((c) => c === ITEM_PATH)).toHaveLength(1);
    expect(drawnCount()).toBe(0);
  });

  it("draws the section for the view that is shown when it is opened, and keeps it current after", async () => {
    const { app } = await shown();
    change("#sw-tier", "10");
    await waitFor(() => expect(app.exaltShown.tier).toBe(10));
    expect(drawnCount()).toBe(0);
    await openSection();
    await waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("matched in your browser"));
    change("#sw-tier", "4");
    await waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("as the site worked it out"));
  });

  it("does nothing for a kit that is being worked out, in the open section as well: no item table, no plan for the stand-in", async () => {
    const made = mount({ weights: () => new Promise(() => {}) });
    runIdle();
    await waitFor(() => expect(allHints().length).toBeGreaterThan(0));
    await openSection();
    $("#buffs-raid").checked = true;
    $("#buffs-raid").dispatchEvent(new Event("change", { bubbles: true }));
    await waitFor(() => expect(made.app.exaltShown.pending).toBe(true));
    await waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("Waiting"));
    expect($("#exalt-plan-table")).toBeNull();
    expect(allHints()).toHaveLength(0);
    runIdle();
    await tick();
    expect(made.calls).not.toContain(ITEM_PATH);
    expect(made.calls).not.toContain("/engine-manifest.json");
  });
});

describe("the link of a line when the section shows another kit", () => {
  it("switches the section to Wear this and goes to the row of the plan for that kit", async () => {
    const { app } = await shown();
    await openSection();
    const records = new Map(ITEMS.items.map((record) => [record.key ?? `w${record.id}`, record]));
    const hosts = [...new Set(EXALT.roles.balanced.plan.map((row) => row.h))];
    const kit = Array.from({ length: 22 }, () => null);
    hosts.forEach((key, index) => (kit[index] = { key, name: `Mine ${index}`, tier: 4 }));
    app.setEquipKit({ kit, record: (key) => records.get(key) ?? null, defaults: ITEMS.defaults });
    await waitFor(() => expect($(".exalt-source").hidden).toBe(false));
    $('input[name="exalt-source"][value="equip"]').click();
    await waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("Equip now"));
    const link = ROW("BACK").querySelector(".exalt-hint a.exalt-hint-plan");
    link.click();
    await waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("Wear this"));
    expect($('input[name="exalt-source"][value="wear"]').checked).toBe(true);
    await waitFor(() => expect(document.activeElement?.id).toBe(link.getAttribute("href").slice(1)));
    expect(document.activeElement.closest("#exalt-plan-table")).not.toBeNull();
    expect(document.activeElement.textContent).toContain("Alacrity");
  });
});

describe("the donor list when the item table could not be had", () => {
  it("is made against the kit the plan on show was made for, not the kit the visitor changed to", async () => {
    // the plan of the file (default kit) names an item as a donor that is not in the default kit but is in the kit the visitor changed to (the tier 10 kit has w90033)
    const odd = structuredClone(EXALT);
    odd.roles.balanced.plan[1].d = "w90033";
    const { app } = await shown({ effects: odd, behaviour: { "/engine-manifest.json": "offline" } });
    await openSection();
    change("#sw-tier", "10");
    await waitFor(() => expect(app.exaltShown.tier).toBe(10));
    expect([...document.querySelectorAll("#kit-body a")].some((a) => a.getAttribute("href") === "/item/w90033/")).toBe(true);
    await waitFor(() => expect($("#exalt-plan-lead").textContent).toContain("Couldn't load the item list"));
    const donors = [...document.querySelectorAll("#exalt-donors li")].map((li) => li.textContent);
    expect(donors.some((text) => text.startsWith("w90033"))).toBe(true); // (the plan on show needs it, and the default kit does not have it)
    expect(donors).toHaveLength(7);
  });
});
