// @vitest-environment jsdom
//
// The page code (switches, theme, picker) run in jsdom against the baked page the generator writes and the browser data
// files it writes for the fixture. Both are committed under fixtures/site/contract/ and checked against the generator by
// pipeline/tests/test_site_build.py, so these tests run on exactly what the Python build produces.

import { readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { initPicker } from "../pipeline/trioforge/site/static/picker.js";
import { applyStoredTheme, bindThemeToggle, getStorage, THEME_KEY } from "../pipeline/trioforge/site/static/theme.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";

// (paths, not URL objects: in this environment the global URL is jsdom's, which file system calls refuse)
const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const STATIC = resolve(HERE, "../pipeline/trioforge/site/static");
const text = (name) => readFileSync(resolve(CONTRACT, name), "utf8");
const dataFile = (name) => JSON.parse(text(`data/${name}.json`));

const MINUS = "−";
const fmt = (n) => (n < 0 ? MINUS : "") + String(Math.abs(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

// ---- the browser data, read the plain way, to know what the page must show ----------------------------------------

function scenarioOf(name, race, role, tier, setup) {
  const doc = dataFile(name);
  const row = doc.rows.find((r) => r[0] === race && r[1] === role && r[2] === tier && r[3] === setup);
  if (!row) throw new Error(`no scenario ${race} ${role} ${tier} ${setup} in ${name}`);
  const kit = doc.kits[row[4]].map((i) => (i < 0 ? null : doc.items[i]));
  const [ac, hp, mana, end, haste, atk, mr, fr, cr, dr, pr, hpreg, manareg, endreg] = doc.totals[row[7]];
  return {
    row,
    kit,
    value: row[5],
    gain: row[6],
    hasteAssumed: row[8],
    totals: { ac, hp, mana, end, haste, atk, mr, fr, cr, dr, pr, hpreg, manareg, endreg },
  };
}

// ---- mounting the baked page --------------------------------------------------------------------------------------

function makeFetch(calls, behaviour = {}) {
  return async (url) => {
    calls.push(String(url));
    const name = String(url).replace("/data/pal-mnk-ber/", "").replace(".json", "");
    const how = behaviour[name];
    if (how && how.json) return { ok: true, status: 200, json: async () => structuredClone(how.json) };
    if (how === "offline") throw new TypeError("Failed to fetch");
    if (how === 404) return { ok: false, status: 404, json: async () => ({}) };
    if (how === "garbage") return { ok: true, status: 200, json: async () => ({ v: 2 }) };
    if (how && typeof how.then === "function") await how;
    return { ok: true, status: 200, json: async () => structuredClone(dataFile(name)) };
  };
}

// `env.footer` is more of the page (the footer, which holds the link that reports a problem); the rest of `env` goes to the page code
function mount(search = "", behaviour = {}, env = {}) {
  const { footer = "", ...extra } = env;
  document.body.innerHTML = text("trio-main.html") + footer;
  window.history.replaceState(null, "", `/trio/pal-mnk-ber/${search}`);
  const calls = [];
  const app = initTrio({ document, window, fetch: makeFetch(calls, behaviour), ...extra });
  return { app, calls, behaviour };
}

function change(element, value) {
  if (value !== undefined) element.value = value;
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function choose(selector) {
  const radio = document.querySelector(selector);
  radio.checked = true;
  radio.dispatchEvent(new Event("change", { bubbles: true }));
}

const $ = (selector) => document.querySelector(selector);
const rowCells = () =>
  [...document.querySelectorAll("#kit-body tr")].map((tr) => {
    const f = (name) => tr.querySelector(`[data-f="${name}"]`).textContent;
    return {
      slot: tr.querySelector("th").textContent,
      name: f("name"),
      tier: f("tier"),
      arrival: f("arrival"),
      reach: f("reach"),
      source: f("source"),
      seal: f("seal"),
      deity: f("deity"),
    };
  });
const shownSetup = () => [...document.querySelectorAll('input[name="setup"]')].find((r) => r.checked)?.value;
const offeredSetups = () =>
  [...document.querySelectorAll('input[name="setup"]')].filter((r) => !r.hidden && !r.disabled).map((r) => r.value);
const status = () => $("#status").textContent.trim();

// ---- the baked page, before any script runs ---------------------------------------------------------------------------

describe("the baked page the tests start from", () => {
  it("shows the default answer: 22 rows, the best race and the default assumptions", () => {
    mount();
    const rows = rowCells();
    expect(rows).toHaveLength(22);
    expect(rows[0]).toMatchObject({ slot: "Head", name: "Helm of the Stoneward", tier: "+4", arrival: "+4" });
    expect(rows[17].name).toBe("<b>x</b>");
    expect($("#sw-race").value).toBe("OGR");
    expect($("#sw-tier").value).toBe("4");
    expect(shownSetup()).toBe("dw");
  });
});

// ---- switching ---------------------------------------------------------------------------------------------------------

describe("switching the tier", () => {
  it("re-renders the whole table from the fetched shard", async () => {
    const { app, calls } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
    const want = scenarioOf("strict-own", "OGR", "balanced", 10, "dw");
    const rows = rowCells();
    expect(rows.map((r) => r.name)).toEqual(want.kit.map((item) => (item ? item[1] : "Leave empty")));
    for (const [index, item] of want.kit.entries()) {
      if (!item) continue;
      expect(rows[index].tier).toBe("+10");
      expect(rows[index].arrival).toBe(`+${item[3]}`);
      expect(rows[index].reach).toBe(`${fmt(2 ** (10 - item[3]))} copies to reach +10`);
      expect(rows[index].source).toBe(item[4]);
      expect(rows[index].seal).toBe("Seen in game");
    }
    expect($("#kit caption").textContent).toContain("+10");
    // dual wield is the role's best setup here and the visitor did not choose it, so the address does not pin it
    expect(window.location.search).toBe("?race=OGR&role=balanced&tier=10&ev=strict&buffs=own");
  });

  it("keeps the fragment of the address when a switch changes it", async () => {
    const { app } = mount("#robust");
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(window.location.search).toBe("?race=OGR&role=balanced&tier=10&ev=strict&buffs=own");
    expect(window.location.hash).toBe("#robust");
    change($("#sw-tier"), "0"); // and it stays through the next change
    await app.whenIdle();
    expect(window.location.search).toContain("tier=0");
    expect(window.location.hash).toBe("#robust");
  });

  it("shows no deity badge on an item that needs none, and the badge on one that does", async () => {
    const doc = JSON.parse(text("data/strict-own.json"));
    const headKey = scenarioOf("strict-own", "OGR", "balanced", 10, "dw").kit[0][0];
    doc.items.find((item) => item[0] === headKey)[6] = ["The Tribunal", "Rodcet Nife"];
    const { app } = mount("", { "strict-own": { json: doc } });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const shown = [...document.querySelectorAll('#kit-body [data-f="deity"]')].filter((node) => !node.hidden);
    expect(shown.map((node) => node.textContent)).toEqual(["Needs deity: The Tribunal or Rodcet Nife"]);
    expect(document.querySelectorAll('#kit-body [data-f="deity"]')).toHaveLength(22);
  });

  it("updates the totals, the kit value and the weapons block", async () => {
    const { app } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const want = scenarioOf("strict-own", "OGR", "balanced", 10, "dw");
    const f = (name) => $(`[data-f="${name}"]`).textContent;
    expect(f("t-ac")).toBe(fmt(want.totals.ac));
    expect(f("t-hp")).toBe(fmt(want.totals.hp));
    expect(f("t-haste")).toBe(`${want.totals.haste}%`);
    expect(f("t-mr")).toBe(fmt(want.totals.mr));
    expect(f("t-hpreg")).toBe(fmt(want.totals.hpreg));
    expect($("#kit-value").textContent).toBe(fmt(Math.round(want.value)));
    expect($("#kit-gain").textContent).toBe(`+${fmt(Math.round(want.gain))}`);
    expect(f("w-main")).toBe(want.kit[20][1]);
    expect(f("w-off")).toBe(want.kit[21][1]);
  });

  it("shows the haste the weapons are scored at in the Assumes line, and it follows the view", async () => {
    const { app } = mount();
    const haste = () => $('[data-f="assume-haste"]').textContent;
    expect(haste()).toBe(`${scenarioOf("strict-own", "OGR", "balanced", 4, "dw").hasteAssumed}%`);
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(haste()).toBe(`${scenarioOf("strict-own", "OGR", "balanced", 10, "dw").hasteAssumed}%`);
    choose("#buffs-group");
    await app.whenIdle();
    expect(haste()).toBe(`${scenarioOf("strict-group", "OGR", "balanced", 10, "dw").hasteAssumed}%`);
    expect($("#assume-weapons summary").textContent.replace(/\s+/g, " ").trim()).toMatch(/^Weapons: dual wield, scored at \d+% haste change$/);
  });

  it("does not fetch again for a view of a shard it already has", async () => {
    const { app, calls } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    change($("#sw-race"), "TRL");
    await app.whenIdle();
    change($("#sw-tier"), "0");
    await app.whenIdle();
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
    const want = scenarioOf("strict-own", "TRL", "balanced", 0, "dw");
    expect(rowCells().map((r) => r.name)).toEqual(want.kit.map((item) => (item ? item[1] : "Leave empty")));
    expect(window.location.search).toContain("race=TRL");
  });

  it("shows the last choice when two changes come quickly", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const { app } = mount("", { "strict-own": gate });
    change($("#sw-tier"), "10");
    change($("#sw-tier"), "0");
    release();
    await app.whenIdle();
    expect(rowCells()[0].tier).toBe("+0");
    expect(window.location.search).toContain("tier=0");
  });

  it("writes only text: a name that looks like markup stays text", async () => {
    const { app } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    change($("#sw-tier"), "4");
    await app.whenIdle();
    expect(rowCells()[17].name).toBe("<b>x</b>");
    expect(document.querySelectorAll("#kit-body b, #kit-body i")).toHaveLength(0);
  });
});

describe("switching the race, the role, the evidence and the buffs", () => {
  it("loads the wiki shard for wiki evidence and badges a wiki-only item", async () => {
    const { app, calls } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    choose("#ev-wiki");
    await app.whenIdle();
    expect(calls.at(-1)).toBe("/data/pal-mnk-ber/wiki-own.json");
    const head = rowCells()[0];
    expect(head.name).toBe("Crown of the Vanguard");
    expect(head.seal).toBe("Wiki");
    expect($('[data-f="assume-ev"]').textContent).toBe("wiki evidence");
    expect(window.location.search).toContain("ev=wiki");
  });

  it("loads the group-buff shard for common group buffs", async () => {
    const { app, calls } = mount();
    choose("#buffs-group");
    await app.whenIdle();
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-group.json"]);
    const want = scenarioOf("strict-group", "OGR", "balanced", 4, "dw");
    expect($('[data-f="t-haste"]').textContent).toBe(`${want.totals.haste}%`);
    expect($('[data-f="assume-buffs"]').textContent).toBe("common group buffs");
  });

  it("switches the role and picks that role's best setup", async () => {
    const { app } = mount();
    choose("#role-tank");
    await app.whenIdle();
    expect(shownSetup()).toBe("1h-shield");
    const want = scenarioOf("strict-own", "OGR", "tank", 4, "1h-shield");
    expect($('[data-f="w-main"]').textContent).toBe(want.kit[20][1]);
    expect($('[data-f="w-setup"]').textContent).toBe("1H + shield");
    expect($("#role-hint").textContent).not.toBe("");
  });

  it("keeps an explicitly chosen setup across a tier change", async () => {
    const { app } = mount();
    choose("#setup-2h");
    await app.whenIdle();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(shownSetup()).toBe("2h");
    expect(window.location.search).toContain("setup=2h");
  });

  it("keeps a setup chosen while the first view is still loading", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const { app } = mount("", { "strict-own": gate });
    choose("#setup-2h");
    change($("#sw-tier"), "10"); // before the data for the first choice has come
    release();
    await app.whenIdle();
    expect(shownSetup()).toBe("2h");
    expect(window.location.search).toContain("setup=2h");
    expect(window.location.search).toContain("tier=10");
  });

  it("lists the other setups of the role with what each would cost", async () => {
    const { app } = mount();
    choose("#role-melee");
    await app.whenIdle();
    const best = scenarioOf("strict-own", "OGR", "melee", 4, "2h");
    const other = scenarioOf("strict-own", "OGR", "melee", 4, "dw");
    const items = [...document.querySelectorAll("#w-others li")].map((li) => li.textContent);
    const delta = Math.round(other.value - best.value);
    expect(items).toEqual([`Dual wield: ${other.kit[20][1]} + ${other.kit[21][1]} (${fmt(delta)})`]);
  });
});

describe("a switch combination with no scenario", () => {
  it("is never offered: Melee has no 1H + shield", async () => {
    const { app } = mount();
    choose("#role-melee");
    await app.whenIdle();
    expect(offeredSetups()).toEqual(["2h", "dw"]);
    expect(document.querySelector('input[name="setup"][value="1h-shield"]').checked).toBe(false);
    expect(shownSetup()).toBe("2h");
    choose("#role-balanced");
    await app.whenIdle();
    expect(offeredSetups()).toEqual(["1h-shield", "2h", "dw"]);
  });

  it("falls back to the role's best setup from a hand-edited link, and says so", async () => {
    const { app } = mount("?role=melee&setup=1h-shield");
    await app.whenIdle();
    expect(shownSetup()).toBe("2h");
    expect(status()).toMatch(/not available for this role/i);
    expect(status()).toMatch(/1H \+ shield/);
    expect(window.location.search).toContain("role=melee");
    expect(window.location.search).not.toContain("setup="); // the visitor asked for a setup that does not exist; the best is shown, not chosen
    const want = scenarioOf("strict-own", "OGR", "melee", 4, "2h");
    expect(rowCells()[20].name).toBe(want.kit[20][1]);
  });

  it("says so when a role switch strands an explicitly chosen setup", async () => {
    const { app } = mount();
    choose("#setup-1h-shield");
    await app.whenIdle();
    choose("#role-melee");
    await app.whenIdle();
    expect(shownSetup()).toBe("2h");
    expect(status()).toMatch(/not available for this role/i);
  });
});

// ---- the address pins a weapon setup only when the visitor chose it ------------------------------------------------------------------
// A view that follows "the role's best setup" must keep following it: if the address wrote the shown setup down, a reload would turn
// the role's best into a choice, and the next change of role would keep it.

describe("the address and the weapon setup", () => {
  const setupInAddress = () => new URLSearchParams(window.location.search).get("setup");

  it("is written only for a setup the visitor chose", async () => {
    const { app } = mount();
    choose("#role-tank");
    await app.whenIdle();
    expect(shownSetup()).toBe("1h-shield"); // the Tank's best
    expect(setupInAddress()).toBeNull();
    choose("#setup-2h"); // a choice
    await app.whenIdle();
    expect(setupInAddress()).toBe("2h");
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(setupInAddress()).toBe("2h"); // kept while the visitor's choice is offered and is not the best
  });

  it("is not written for the choice of the setup that is the role's best: that is following the best", async () => {
    const { app } = mount();
    choose("#setup-2h");
    await app.whenIdle();
    expect(setupInAddress()).toBe("2h");
    choose("#setup-dw"); // the Balanced role's best, chosen on purpose
    await app.whenIdle();
    expect(shownSetup()).toBe("dw");
    expect(setupInAddress()).toBeNull();
    choose("#role-tank"); // and the page follows the best of the role from here on
    await app.whenIdle();
    expect(shownSetup()).toBe("1h-shield");
  });

  it("counts a setup in the address that is the role's best as the best, so a role change shows the new role's best", async () => {
    const { app } = mount("?role=tank&setup=1h-shield");
    await app.whenIdle();
    expect(shownSetup()).toBe("1h-shield");
    expect(setupInAddress()).toBeNull(); // the address is brought back to what it means
    choose("#role-balanced");
    await app.whenIdle();
    expect(shownSetup()).toBe("dw"); // Balanced's best, not the setup the old address happened to name
    const want = scenarioOf("strict-own", "OGR", "balanced", 4, "dw");
    expect(rowCells()[20].name).toBe(want.kit[20][1]);
    expect($("#kit-value").textContent).toBe(fmt(Math.round(want.value)));
    expect(setupInAddress()).toBeNull();
  });

  it("counts the baked default's own setup in the address as the best too, without fetching anything", async () => {
    const { app, calls } = mount("?setup=dw");
    await app.whenIdle();
    expect(calls).toEqual([]);
    choose("#role-tank");
    await app.whenIdle();
    expect(shownSetup()).toBe("1h-shield");
  });

  it("keeps a setup in the address that is not the role's best as the visitor's choice", async () => {
    const { app } = mount("?role=tank&setup=2h");
    await app.whenIdle();
    expect(shownSetup()).toBe("2h");
    expect(setupInAddress()).toBe("2h");
    choose("#role-balanced"); // offered there too, and still the visitor's choice
    await app.whenIdle();
    expect(shownSetup()).toBe("2h");
    expect(setupInAddress()).toBe("2h");
  });

  it("goes round a reload: Tank, reload, Balanced shows the Balanced role's best setup and its value", async () => {
    const first = mount();
    choose("#role-tank");
    await first.app.whenIdle();
    const reloaded = mount(window.location.search); // the page opened again at the address it wrote
    await reloaded.app.whenIdle();
    expect($("#role-tank").checked).toBe(true);
    choose("#role-balanced");
    await reloaded.app.whenIdle();
    const want = scenarioOf("strict-own", "OGR", "balanced", 4, "dw");
    expect(shownSetup()).toBe("dw");
    expect($("#kit-value").textContent).toBe(fmt(Math.round(want.value)));
    expect(rowCells().map((r) => r.name)).toEqual(want.kit.map((item) => (item ? item[1] : "Leave empty")));
  });

  it("never writes the setup of a fall-back", async () => {
    const { app } = mount("?role=melee&setup=1h-shield");
    await app.whenIdle();
    expect(shownSetup()).toBe("2h");
    expect(setupInAddress()).toBeNull();
    expect(status()).toMatch(/not available for this role/i);
  });
});

// ---- an evidence level with fewer setups --------------------------------------------------------------------------------------------
// The weapon setups follow the item pool of each evidence level. A strict pool with no shield the trio can wear has no 1H + shield
// setup, while the wiki pool, which has one, does: the strict shards then have no rows for it. The page code reads the setups of
// the level it shows, so the choice must come and go with the level.

/** The strict data files as a run writes them when the strict pool has no shield: the rows of the shield setup are not there. */
function noStrictShield() {
  const without = (name) => {
    const doc = dataFile(name);
    doc.rows = doc.rows.filter((row) => row[3] !== "1h-shield");
    return { json: doc };
  };
  return { "strict-own": without("strict-own"), "strict-group": without("strict-group") };
}

const shieldRadio = () => document.querySelector('input[name="setup"][value="1h-shield"]');

describe("an evidence level that has no shield setup", () => {
  it("is never offered it, and the other level offers it again", async () => {
    const { app } = mount("", noStrictShield());
    choose("#role-tank");
    await app.whenIdle();
    expect(offeredSetups()).toEqual(["2h", "dw"]);
    expect(shieldRadio().hidden && shieldRadio().disabled && shieldRadio().closest(".opt").hidden).toBe(true);
    expect(shownSetup()).toBe("dw"); // the best setup the level has for a Tank, not the shield
    expect(status()).toBe("");
    choose("#ev-wiki");
    await app.whenIdle();
    expect(offeredSetups()).toEqual(["1h-shield", "2h", "dw"]);
    expect(shieldRadio().hidden || shieldRadio().disabled || shieldRadio().closest(".opt").hidden).toBe(false);
    expect(shownSetup()).toBe("1h-shield"); // the wiki level's best for a Tank
    choose("#ev-strict");
    await app.whenIdle();
    expect(offeredSetups()).toEqual(["2h", "dw"]);
    expect(shieldRadio().disabled).toBe(true);
    expect(shownSetup()).toBe("dw");
  });

  // (the shield is a choice here only for a role whose best setup it is not: for the Balanced role the best is dual wield. For a role
  // whose best it is, naming it is following the best, and a level without it simply shows that level's best: see the test after.)
  it("shows the level's best setup and says so when a change of evidence strands the shield that was chosen", async () => {
    const { app } = mount("?role=balanced&ev=wiki&setup=1h-shield", noStrictShield());
    await app.whenIdle();
    expect(shownSetup()).toBe("1h-shield");
    expect(status()).toBe("");
    choose("#ev-strict");
    await app.whenIdle();
    expect(shownSetup()).toBe("dw");
    expect(offeredSetups()).toEqual(["2h", "dw"]);
    expect(status()).toMatch(/1H \+ shield is not available for this role/i);
    expect(status()).toMatch(/Dual wield/);
    expect(window.location.search).toContain("ev=strict");
    expect(window.location.search).not.toContain("setup="); // the level's best is shown, and was not chosen
    const want = scenarioOf("strict-own", "OGR", "balanced", 4, "dw");
    expect(rowCells()[20].name).toBe(want.kit[20][1]);
    expect(rowCells()[21].name).toBe(want.kit[21] ? want.kit[21][1] : "Leave empty");
  });

  it("follows the best of each level when the shield is the role's best, and has nothing to say about it", async () => {
    const { app } = mount("?role=tank&ev=wiki", noStrictShield());
    await app.whenIdle();
    expect(shownSetup()).toBe("1h-shield"); // the wiki level's best for a Tank, which nobody chose
    choose("#ev-strict");
    await app.whenIdle();
    expect(shownSetup()).toBe("dw"); // the strict level has no shield: its best is shown
    expect(status()).toBe("");
    choose("#ev-wiki");
    await app.whenIdle();
    expect(shownSetup()).toBe("1h-shield");
    expect(status()).toBe("");
  });

  it("shows the file's best setup and says so when a change of buffs moves to a file that lacks the shield that was chosen", async () => {
    // each data file carries its own setups: here only the group-buff file of the strict level has no shield rows
    const doc = dataFile("strict-group");
    doc.rows = doc.rows.filter((row) => row[3] !== "1h-shield");
    const { app } = mount("?role=balanced&setup=1h-shield", { "strict-group": { json: doc } }); // Balanced: the shield is a choice, not the best
    await app.whenIdle();
    expect(shownSetup()).toBe("1h-shield");
    expect(offeredSetups()).toEqual(["1h-shield", "2h", "dw"]);
    expect(status()).toBe("");
    choose("#buffs-group");
    await app.whenIdle();
    expect(shownSetup()).toBe("dw");
    expect(offeredSetups()).toEqual(["2h", "dw"]);
    expect(status()).toMatch(/1H \+ shield is not available for this role/i);
    expect(status()).toMatch(/Dual wield/);
    expect(window.location.search).toContain("buffs=group");
    expect(window.location.search).not.toContain("setup="); // the file's best is shown, and was not chosen
    const want = scenarioOf("strict-group", "OGR", "balanced", 4, "dw");
    expect(rowCells()[20].name).toBe(want.kit[20][1]);
    choose("#buffs-own"); // back to the file that has it: its setups are offered again, and nothing is amiss
    await app.whenIdle();
    expect(offeredSetups()).toEqual(["1h-shield", "2h", "dw"]);
    expect(status()).toBe("");
  });

  it("falls back the same way from a link that asks for the shield under strict evidence", async () => {
    const { app } = mount("?role=tank&setup=1h-shield", noStrictShield());
    await app.whenIdle();
    expect(shownSetup()).toBe("dw");
    expect(status()).toMatch(/not available for this role/i);
    expect(offeredSetups()).toEqual(["2h", "dw"]);
    expect(window.location.search).not.toContain("setup="); // the fall-back is the best setup, which the visitor did not choose
  });

  it("lists only the other setups the level has for the role", async () => {
    const { app } = mount("", noStrictShield());
    choose("#role-tank");
    await app.whenIdle();
    const others = [...document.querySelectorAll("#w-others li")].map((li) => li.textContent);
    expect(others).toHaveLength(1);
    expect(others[0]).toMatch(/^Two-hander: /);
  });
});

describe("reading the link", () => {
  it("shows the view a full link describes", async () => {
    const { app, calls } = mount("?race=TRL&role=tank&tier=0&setup=2h&ev=wiki&buffs=group");
    await app.whenIdle();
    expect(calls).toEqual(["/data/pal-mnk-ber/wiki-group.json"]);
    const want = scenarioOf("wiki-group", "TRL", "tank", 0, "2h");
    expect(rowCells().map((r) => r.name)).toEqual(want.kit.map((item) => (item ? item[1] : "Leave empty")));
    expect($("#sw-race").value).toBe("TRL");
    expect($("#role-tank").checked).toBe(true);
    expect($("#sw-tier").value).toBe("0");
    expect(shownSetup()).toBe("2h");
    expect($("#ev-wiki").checked && $("#buffs-group").checked).toBe(true);
    expect($('[data-f="assume-setup"]').textContent).toBe("two-hander");
  });

  it("ignores values it does not know and keeps the baked answer without a fetch", async () => {
    const { app, calls } = mount("?race=XXX&role=healer&tier=99&ev=nope&buffs=lots&setup=bow");
    await app.whenIdle();
    expect(calls).toEqual([]);
    expect(rowCells()[0].name).toBe("Helm of the Stoneward");
    expect($("#sw-race").value).toBe("OGR");
    expect(status()).toBe("");
  });

  it("leaves the address alone until something changes", async () => {
    const { app } = mount();
    await app.whenIdle();
    expect(window.location.search).toBe("");
  });

  // A value that means nothing is read as the default, and the address is brought back to the view that is shown, so that the link
  // a visitor copies from the address bar is a link to that view and not a malformed one that merely looks like it.
  const DEFAULT_ADDRESS = "?race=OGR&role=balanced&tier=4&ev=strict&buffs=own";

  // The tier switch is the tiers the shards of the trio have (a run is of a scope: +0, +4 and +10 for most trios), and nothing else is offered. A link that names
  // a tier of the game that this page has no data for is read as a value that means nothing.
  it("offers the tiers the page's shards have and no other, and reads a link that names another as a value that means nothing", async () => {
    const { app, calls } = mount("?tier=7");
    await app.whenIdle();
    expect([...document.querySelectorAll("#sw-tier option")].map((o) => o.value)).toEqual(["0", "4", "10"]);
    expect([...document.querySelectorAll("#sw-tier option")].map((o) => o.textContent)).toEqual(["+0", "+4", "+10 (endgame)"]);
    expect(calls).toEqual([]); // the default view is the baked one: nothing is fetched
    expect($("#sw-tier").value).toBe("4");
    expect(rowCells()[0].tier).toBe("+4");
    expect(window.location.search).toBe(DEFAULT_ADDRESS);
    // what else the link says is kept: its role is shown, at the default tier
    const other = mount("?tier=7&role=tank");
    await other.app.whenIdle();
    expect($("#sw-tier").value).toBe("4");
    expect(document.querySelector('input[name="role"]:checked').value).toBe("tank");
    expect(window.location.search).toBe("?race=OGR&role=tank&tier=4&ev=strict&buffs=own");
    for (const tier of ["0", "4", "10"]) {
      const offered = mount(`?tier=${tier}`); // and each tier it offers is one a link can name
      await offered.app.whenIdle();
      expect($("#sw-tier").value, tier).toBe(tier);
    }
  });

  it("writes the address of the default answer over a link whose values mean nothing, without fetching anything", async () => {
    const { app, calls } = mount("?race=XXX&role=healer&tier=99&ev=nope&buffs=lots&setup=bow");
    await app.whenIdle();
    expect(calls).toEqual([]);
    expect(window.location.search).toBe(DEFAULT_ADDRESS);
    expect(rowCells()[0].name).toBe("Helm of the Stoneward");
    expect(status()).toBe("");
  });

  for (const bad of ["race=XXX", "role=healer", "tier=99", "tier=four", "tier=", "tier=7", "tier=1", "tier=11", "ev=nope", "buffs=lots", "setup=bow", "race=", "setup=", "race=ogr"]) {
    it(`treats ${bad} as the default and writes the default address`, async () => {
      const { app, calls } = mount("?" + bad);
      await app.whenIdle();
      expect(calls).toEqual([]);
      expect(window.location.search).toBe(DEFAULT_ADDRESS);
    });
  }

  it("writes the default address for one bad value among good ones, and keeps the good ones that ask for another view", async () => {
    const quiet = mount("?race=OGR&role=balanced&tier=nope");
    await quiet.app.whenIdle();
    expect(window.location.search).toBe(DEFAULT_ADDRESS);
    const { app, calls } = mount("?tier=10&race=ZZZ"); // a view that is not the baked one: loaded, and its address written whole
    await app.whenIdle();
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
    expect(window.location.search).toBe("?race=OGR&role=balanced&tier=10&ev=strict&buffs=own");
    expect($("#sw-tier").value).toBe("10");
  });

  it("does not touch a link whose values are all clear: not for another order, an address of the default view, or a parameter of its own", async () => {
    for (const search of ["?utm_source=a", "?buffs=own&ev=strict", "?race=OGR&role=balanced&tier=4&ev=strict&buffs=own&setup=dw", "?setup=dw"]) {
      const { app, calls } = mount(search);
      await app.whenIdle();
      expect(calls, search).toEqual([]);
      expect(window.location.search, search).toBe(search);
    }
  });

  it("keeps the state of the history entry when it writes the address of the default answer", async () => {
    document.body.innerHTML = text("trio-main.html");
    window.history.replaceState({ kit: "abc" }, "", "/trio/pal-mnk-ber/?race=XXX");
    const app = initTrio({ document, window, fetch: makeFetch([]) });
    await app.whenIdle();
    expect(window.location.search).toBe(DEFAULT_ADDRESS);
    expect(window.history.state).toEqual({ kit: "abc" });
  });

  // The fragment is the visitor's (a place in the page, or a note of their own): writing the query must not take it away.
  it("keeps the fragment of a malformed link when it writes the address of the default answer", async () => {
    const { app, calls } = mount("?race=XXX#robust");
    await app.whenIdle();
    expect(calls).toEqual([]);
    expect(window.location.search).toBe(DEFAULT_ADDRESS);
    expect(window.location.hash).toBe("#robust");
  });

  it("writes only the parameters of the page, a malformed link's fragment kept and the parameter of someone else dropped", async () => {
    const { app } = mount("?utm_source=a&race=XXX&tier=99#robust");
    await app.whenIdle();
    expect(window.location.search).toBe(DEFAULT_ADDRESS);
    expect(window.location.hash).toBe("#robust");
  });

  it("writes nothing, and breaks nothing, where the address cannot be rewritten", async () => {
    const calls = [];
    const refusing = {
      get location() {
        return window.location;
      },
      get history() {
        return {
          state: null,
          replaceState() {
            throw new DOMException("sandboxed", "SecurityError");
          },
        };
      },
    };
    document.body.innerHTML = text("trio-main.html");
    window.history.replaceState(null, "", "/trio/pal-mnk-ber/?race=XXX");
    const app = initTrio({ document, window: refusing, fetch: makeFetch(calls) });
    await app.whenIdle();
    expect(calls).toEqual([]);
    expect(rowCells()[0].name).toBe("Helm of the Stoneward");
    expect(status()).toBe("");
  });
});

// ---- failures ---------------------------------------------------------------------------------------------------------------

describe("a shard that fails to load", () => {
  const snapshot = () => JSON.stringify(rowCells());

  for (const [label, how] of [["is offline", "offline"], ["is a 404", 404], ["is not a shard", "garbage"]]) {
    it(`keeps the baked table and says to try again when the shard ${label}`, async () => {
      const { app } = mount("", { "strict-own": how });
      const before = snapshot();
      change($("#sw-tier"), "10");
      await app.whenIdle();
      expect(snapshot()).toBe(before);
      expect(rowCells()).toHaveLength(22);
      expect(status()).toMatch(/couldn't load this view; try again/i);
      expect($("#sw-tier").value).toBe("4"); // the control goes back to what the table shows
      expect(window.location.search).toBe("");
    });
  }

  // A file that parses but cannot be drawn from must fail the same way: before the page draws, with the same message. Left to fail
  // while it draws, it would leave "Loading this view…" on the page for good, or draw numbers that are none.
  const damaged = {
    "a totals row of the wrong length": (doc) => {
      doc.totals = doc.totals.map((row) => row.slice(0, 10));
    },
    "a totals row that is null": (doc) => {
      doc.totals[doc.rows[0][7]] = null;
    },
    "a totals index that is the name of a property": (doc) => {
      for (const row of doc.rows) row[7] = "length";
    },
    "a kit that names an item the shard does not have": (doc) => {
      for (const kit of doc.kits) kit[0] = doc.items.length + 5;
    },
    "a kit index that is a text": (doc) => {
      for (const row of doc.rows) row[4] = String(row[4]);
    },
  };

  for (const [label, damage] of Object.entries(damaged)) {
    it(`keeps the baked table and says to try again when the shard has ${label}`, async () => {
      const doc = dataFile("strict-own");
      damage(doc);
      const { app } = mount("", { "strict-own": { json: doc } });
      const before = snapshot();
      change($("#sw-tier"), "10");
      await app.whenIdle();
      expect(snapshot()).toBe(before);
      expect(status()).toMatch(/couldn't load this view; try again/i);
      expect(status()).not.toMatch(/loading this view/i);
      expect($("#sw-tier").value).toBe("4");
      expect(window.location.search).toBe("");
    });
  }

  it("offers a Try again button that loads the view once the network is back", async () => {
    const { app, behaviour } = mount("", { "strict-own": "offline" });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const button = $("#status button");
    expect(button.textContent).toBe("Try again");
    delete behaviour["strict-own"];
    button.click();
    await app.whenIdle();
    expect(rowCells()[0].tier).toBe("+10");
    expect($("#sw-tier").value).toBe("10");
    expect(status()).toBe("");
  });

  it("does not remember a failure: the next change tries the network again", async () => {
    const { app, behaviour, calls } = mount("", { "strict-own": "offline" });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    delete behaviour["strict-own"];
    change($("#sw-tier"), "0");
    await app.whenIdle();
    expect(calls).toHaveLength(2);
    expect(rowCells()[0].tier).toBe("+0");
  });

  it("keeps the baked table when the link's own view cannot be fetched", async () => {
    const before = JSON.stringify(
      (() => {
        mount();
        return rowCells();
      })(),
    );
    const { app } = mount("?tier=10", { "strict-own": "offline" });
    await app.whenIdle();
    expect(JSON.stringify(rowCells())).toBe(before);
    expect(status()).toMatch(/couldn't load this view/i);
  });
});

// ---- the baked page and the script agree ---------------------------------------------------------------------------------------

describe("the script's wording is the generator's wording", () => {
  it("re-rendering the default view changes nothing the reader can see", async () => {
    const { app } = mount();
    const read = () => ({
      rows: rowCells(),
      totals: [...document.querySelectorAll("#totals-body [data-f]")].map((n) => `${n.dataset.f}=${n.textContent}`),
      value: $("#kit-value").textContent,
      gain: $("#kit-gain").textContent,
      verdict: $("#kit caption").textContent.replace(/\s+/g, " ").trim(),
      weapons: [...document.querySelectorAll("#weapons [data-f]")].map((n) => n.textContent),
      others: [...document.querySelectorAll("#w-others li")].map((n) => n.textContent),
      runnerups: [...document.querySelectorAll("#runnerups-body tr")].map((tr) => ({
        slot: tr.querySelector("th").textContent.trim(),
        swaps: [...tr.querySelectorAll("li")].map((li) => li.textContent.replace(/\s+/g, " ").trim()),
        listHidden: tr.querySelector('[data-f="swaps"]').hidden,
        noneHidden: tr.querySelector('[data-f="r-none"]').hidden,
      })),
      runnerupsShown: [$("#runnerups-na").hidden, $("#runnerups-table").hidden],
      robust: [$("#robust-summary").textContent, ...[...document.querySelectorAll("#robust-list li")].map((n) => n.textContent)],
      assume: [...document.querySelectorAll('[data-f^="assume-"]')].map((n) => n.textContent),
      hint: $("#role-hint").textContent,
    });
    const before = read();
    await app.refresh();
    expect(read()).toEqual(before);
  });
});

// ---- the expanders -----------------------------------------------------------------------------------------------------------------

const openDetails = (selector) => {
  $(selector).open = true;
  $(selector).dispatchEvent(new Event("toggle"));
};
const RUNNERUPS = "/data/pal-mnk-ber/runnerups/";
// The file of a role holds every tier of the run: its views are [tier, race, setup, slots], and its items are one table for the file.
const runnerupsOf = (role) => JSON.parse(text(`data/runnerups/${role}.json`));
const viewOf = (doc, tier, race = "OGR") => doc.views.find((v) => v[0] === tier && v[1] === race);
const runnerupCalls = (calls) => calls.filter((c) => c.startsWith(RUNNERUPS));
const swapCounts = () => [...document.querySelectorAll("#runnerups-body tr")].map((row) => row.querySelectorAll("li").length);

describe("runner-ups and the robust core", () => {
  it("fetch only the file of the shown role, once, the first time they are opened, and read the tier from it", async () => {
    const { app, calls } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(runnerupCalls(calls)).toEqual([]); // closed: nothing is fetched
    openDetails("#runnerups");
    await app.whenIdle();
    expect(runnerupCalls(calls)).toEqual([RUNNERUPS + "balanced.json"]); // the file of the role, and not one for the tier
    const doc = runnerupsOf("balanced");
    const view = viewOf(doc, 10);
    const rows = [...document.querySelectorAll("#runnerups-body tr")];
    expect(rows).toHaveLength(22);
    const slot = view[3].findIndex((swaps) => swaps.length > 0);
    const lis = [...rows[slot].querySelectorAll("li")].map((li) => li.textContent);
    expect(lis).toHaveLength(view[3][slot].length);
    expect(lis[0]).toContain(doc.items[view[3][slot][0][0]][1]);
    expect(lis[0]).toContain(fmt(Math.round(view[3][slot][0][1])));
    expect($("#runnerups-na").hidden).toBe(true);
    // another race, or another tier of the same role: it is read from the file the page has, and nothing more is fetched
    change($("#sw-race"), "TRL");
    await app.whenIdle();
    expect(runnerupCalls(calls)).toEqual([RUNNERUPS + "balanced.json"]);
    const trl = viewOf(doc, 10, "TRL");
    const trlSlot = trl[3].findIndex((swaps) => swaps.length > 0);
    expect([...document.querySelectorAll("#runnerups-body tr")][trlSlot].querySelectorAll("li")).toHaveLength(trl[3][trlSlot].length);
    change($("#sw-race"), "OGR");
    change($("#sw-tier"), "0");
    await app.whenIdle();
    expect(runnerupCalls(calls)).toEqual([RUNNERUPS + "balanced.json"]);
    expect(swapCounts()).toEqual(viewOf(doc, 0)[3].map((swaps) => swaps.length)); // the swaps of the tier that is shown, from the same file
  });

  it("follow the role and the tier while open: a file for each role, and the tier read from it", async () => {
    const { app, calls } = mount();
    openDetails("#runnerups"); // opened on the baked view: its runner-ups are already in the page
    await app.whenIdle();
    expect(runnerupCalls(calls)).toEqual([]);
    choose("#role-tank");
    await app.whenIdle();
    change($("#sw-tier"), "0");
    await app.whenIdle();
    expect(runnerupCalls(calls)).toEqual([RUNNERUPS + "tank.json"]); // the tier of the same role is in the file the page has
    const doc = runnerupsOf("tank");
    const view = viewOf(doc, 0);
    const head = [...document.querySelectorAll("#runnerups-body tr")][0].querySelectorAll("li");
    expect(head).toHaveLength(view[3][0].length);
    expect(head[0].textContent).toContain(doc.items[view[3][0][0][0]][1]);
    choose("#role-melee");
    await app.whenIdle();
    expect(runnerupCalls(calls)).toEqual([RUNNERUPS + "tank.json", RUNNERUPS + "melee.json"]); // another role, another file
  });

  it("show the badge 'Needs deity' on the one a deity is needed for, first in its slot, with a plus sign when it beats the pick", async () => {
    const { app } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    openDetails("#runnerups");
    await app.whenIdle();
    const doc = runnerupsOf("balanced");
    const view = viewOf(doc, 10);
    const rows = [...document.querySelectorAll("#runnerups-body tr")];
    const head = [...rows[0].querySelectorAll("li")];
    expect(head[0].querySelector('[data-f="r-deity"]').textContent).toBe("Needs deity: The Tribunal");
    expect(view[3][0][0][1]).toBeGreaterThan(0); // a swap of an item that needs a deity can be better than the pick ...
    expect(head[0].querySelector('[data-f="r-delta"]').textContent).toBe("+" + fmt(Math.round(view[3][0][0][1])));
    expect(head.slice(1).every((li) => li.querySelector('[data-f="r-deity"]') === null)).toBe(true);
    expect(head.slice(1).every((li) => li.querySelector('[data-f="r-delta"]').textContent.startsWith(MINUS))).toBe(true); // ... no other can
    const chest = [...rows[13].querySelectorAll("li")][0];
    expect(chest.textContent).toContain("Mantle of the Faithful");
    expect(chest.querySelector('[data-f="r-deity"]').textContent).toBe("Needs deity: The Tribunal or Rodcet Nife");
    expect(chest.querySelector('[data-f="r-delta"]').textContent).toBe(fmt(Math.round(view[3][13][0][1]))); // worse than the pick
  });

  it("are for the default assumptions only: the wiki view says so instead, and fetches nothing", async () => {
    const { app, calls } = mount();
    choose("#ev-wiki");
    await app.whenIdle();
    openDetails("#runnerups");
    await app.whenIdle();
    expect($("#runnerups-na").hidden).toBe(false);
    expect($("#runnerups-na").textContent).toMatch(/default assumptions only/i);
    expect($("#runnerups-table").hidden).toBe(true);
    expect(runnerupCalls(calls)).toEqual([]);
  });

  it("never ask for a role that has no file", async () => {
    document.body.innerHTML = text("trio-main.html");
    $("#runnerups").dataset.files = "tank melee"; // as if the precompute had not made the file of the Balanced role
    window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
    const calls = [];
    const app = initTrio({ document, window, fetch: makeFetch(calls) });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    openDetails("#runnerups");
    await app.whenIdle();
    expect(runnerupCalls(calls)).toEqual([]);
    expect($("#runnerups-na").hidden).toBe(false);
    expect($("#runnerups-table").hidden).toBe(true);
  });

  it("say that a tier the file of the role does not have is not available, and ask for nothing more for it", async () => {
    const doc = runnerupsOf("balanced");
    doc.tiers = doc.tiers.filter((tier) => tier !== 10);
    doc.views = doc.views.filter((v) => v[0] !== 10);
    const { app, calls } = mount("", { "runnerups/balanced": { json: doc } });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    openDetails("#runnerups");
    await app.whenIdle();
    expect(runnerupCalls(calls)).toEqual([RUNNERUPS + "balanced.json"]);
    expect($("#runnerups-na").hidden).toBe(false);
    expect($("#runnerups-table").hidden).toBe(true);
    change($("#sw-tier"), "0"); // a tier it has: shown, from the file the page has
    await app.whenIdle();
    expect(runnerupCalls(calls)).toEqual([RUNNERUPS + "balanced.json"]);
    expect($("#runnerups-table").hidden).toBe(false);
  });

  it("do not use a file whose view is for another setup than the role's best", async () => {
    const doc = runnerupsOf("balanced");
    viewOf(doc, 10)[2] = "2h";
    const { app } = mount("", { "runnerups/balanced": { json: doc } });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    openDetails("#runnerups");
    await app.whenIdle();
    expect($("#runnerups-na").hidden).toBe(false);
    expect($("#runnerups-table").hidden).toBe(true);
  });

  it("say so when the file cannot be loaded, and try again when the section is opened again", async () => {
    const { app, calls, behaviour } = mount("", { "runnerups/balanced": "offline" });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    openDetails("#runnerups");
    await app.whenIdle();
    expect($("#runnerups-na").textContent).toMatch(/couldn't load this section/i);
    expect($("#runnerups-na").hidden).toBe(false);
    expect($("#kit-body tr [data-f=\"name\"]").textContent).not.toBe(""); // the answer itself is untouched
    delete behaviour["runnerups/balanced"];
    $("#runnerups").open = false;
    openDetails("#runnerups");
    await app.whenIdle();
    expect(runnerupCalls(calls)).toHaveLength(2);
    expect($("#runnerups-na").hidden).toBe(true);
    expect($("#runnerups-na").textContent).toMatch(/default assumptions only/i); // the note is restored
    expect($("#runnerups-table").hidden).toBe(false);
  });

  it("show the robust core only where it was computed", async () => {
    const { app } = mount();
    change($("#sw-tier"), "0");
    await app.whenIdle();
    $("#robust").open = true;
    $("#robust").dispatchEvent(new Event("toggle"));
    await app.whenIdle();
    expect($("#robust-na").hidden).toBe(false);
    expect($("#robust-na").textContent).toMatch(/default race at \+4 and \+10 only/);
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect($("#robust-na").hidden).toBe(true);
    expect($("#robust-summary").textContent).toBe("20 of 22 picks hold in every check. The other 2 depend on an assumption:");
    const items = [...document.querySelectorAll("#robust-list li")].map((li) => li.textContent);
    expect(items).toHaveLength(2);
    expect(items.some((t) => t.startsWith("Chest: ") && t.includes("depends on the Monk curve (test B9)"))).toBe(true);
  });

  // The seals are made for one view of each role and tier: the default race, the default evidence level, own buffs and the role's
  // best weapon setup. Any other view gets the note, never the seals of a kit it does not show.
  describe("show the robust core for the exact view it was made for", () => {
    const sealsShown = () => !$("#robust-summary").hidden && $("#robust-na").hidden;
    const notComputed = () => $("#robust-summary").hidden && $("#robust-list").hidden && !$("#robust-na").hidden;

    async function atTen() {
      const { app, calls } = mount();
      change($("#sw-tier"), "10");
      await app.whenIdle();
      openDetails("#robust");
      await app.whenIdle();
      expect(sealsShown()).toBe(true); // Ogre, Balanced, +10, dual wield, strict, own buffs: what the seals were made for
      return { app, calls };
    }

    it("says it was not computed for another weapon setup, and shows the seals again for the best", async () => {
      const { app } = await atTen();
      choose("#setup-2h");
      await app.whenIdle();
      expect(notComputed()).toBe(true);
      expect($("#robust-na").textContent).toMatch(/not computed for this view/i);
      expect($("#robust-na").textContent).toMatch(/dual wield/i); // what it was computed for
      choose("#setup-dw");
      await app.whenIdle();
      expect(sealsShown()).toBe(true);
    });

    it("says it was not computed for another evidence level", async () => {
      const { app } = await atTen();
      choose("#ev-wiki");
      await app.whenIdle();
      expect(notComputed()).toBe(true);
      expect($("#robust-na").textContent).toMatch(/not computed for this view/i);
      expect($("#robust-na").textContent).toMatch(/strict evidence/i);
      choose("#ev-strict");
      await app.whenIdle();
      expect(sealsShown()).toBe(true);
    });

    it("says it was not computed for the other buffs", async () => {
      const { app } = await atTen();
      choose("#buffs-group");
      await app.whenIdle();
      expect(notComputed()).toBe(true);
      expect($("#robust-na").textContent).toMatch(/not computed for this view/i);
      expect($("#robust-na").textContent).toMatch(/your own buffs/i);
      choose("#buffs-own");
      await app.whenIdle();
      expect(sealsShown()).toBe(true);
    });

    it("keeps the older note for another race and for a tier the seals do not cover", async () => {
      const { app } = await atTen();
      change($("#sw-race"), "TRL");
      await app.whenIdle();
      expect(notComputed()).toBe(true);
      expect($("#robust-na").textContent).toMatch(/default race at \+4 and \+10 only/);
      change($("#sw-race"), "OGR");
      await app.whenIdle();
      expect(sealsShown()).toBe(true);
      change($("#sw-tier"), "0");
      await app.whenIdle();
      expect($("#robust-na").textContent).toMatch(/default race at \+4 and \+10 only/);
    });

    it("seals each role for that role's own best setup", async () => {
      const { app } = await atTen();
      choose("#role-tank");
      await app.whenIdle();
      expect(shownSetup()).toBe("1h-shield");
      expect(sealsShown()).toBe(true); // the Tank's seals are for the shield setup
      choose("#setup-dw");
      await app.whenIdle();
      expect(notComputed()).toBe(true);
      expect($("#robust-na").textContent).toMatch(/1H \+ shield/i);
    });

    it("does not show a stale answer while it is closed: opening it afterwards shows the view's own", async () => {
      const { app } = mount();
      choose("#setup-2h");
      await app.whenIdle();
      openDetails("#robust");
      await app.whenIdle();
      expect(notComputed()).toBe(true);
    });
  });
});

// ---- an item with no arrival tier ---------------------------------------------------------------------------------------------------

describe("a summoned item", () => {
  it("arrives at its spell rank: no tier, and no count of copies", async () => {
    const doc = JSON.parse(text("data/strict-own.json"));
    const head = scenarioOf("strict-own", "OGR", "balanced", 10, "dw").kit[0];
    const row = doc.items.find((item) => item[0] === head[0]);
    row[2] = "spell";
    row[3] = null;
    const { app } = mount("", { "strict-own": { json: doc } });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const cells = rowCells();
    expect(cells[0]).toMatchObject({ name: head[1], tier: "+10", arrival: "spell rank", reach: "" });
    expect(cells[1].reach).toMatch(/copies to reach \+10$/); // the others still count theirs
  });

  it("is refused by the data check when its arrival is neither a whole tier nor null", async () => {
    const doc = JSON.parse(text("data/strict-own.json"));
    doc.items[0][3] = "+0 to +4";
    const { app } = mount("", { "strict-own": { json: doc } });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(status()).toMatch(/couldn't load this view/i);
    expect(rowCells()[0].name).toBe("Helm of the Stoneward"); // the baked answer stays
  });
});

// ---- the answer taken from the wiki level while nothing is strict ------------------------------------------------------------------

describe("a page whose default evidence is the wiki level", () => {
  function mountWiki(behaviour = {}) {
    const html = text("trio-main.html")
      .replace('id="ev-strict" value="strict" data-phrase="strict evidence" checked', 'id="ev-strict" value="strict" data-phrase="strict evidence"')
      .replace('id="ev-wiki" value="wiki" data-phrase="wiki evidence"', 'id="ev-wiki" value="wiki" data-phrase="wiki evidence" checked');
    expect(html).not.toBe(text("trio-main.html"));
    document.body.innerHTML = html;
    window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
    const calls = [];
    const app = initTrio({ document, window, fetch: makeFetch(calls, behaviour) });
    return { app, calls };
  }

  it("takes its runner-ups from the files, which are made for that level, and not for strict", async () => {
    const { app, calls } = mountWiki();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(calls).toEqual(["/data/pal-mnk-ber/wiki-own.json"]); // the default level: the wiki shard
    openDetails("#runnerups");
    await app.whenIdle();
    expect(runnerupCalls(calls)).toEqual([RUNNERUPS + "balanced.json"]);
    expect($("#runnerups-na").hidden).toBe(true);
    expect($("#runnerups-table").hidden).toBe(false);
  });

  it("says the runner-ups are for the default assumptions only when strict is chosen", async () => {
    const { app, calls } = mountWiki();
    choose("#ev-strict");
    await app.whenIdle();
    openDetails("#runnerups");
    await app.whenIdle();
    expect($("#runnerups-na").hidden).toBe(false);
    expect($("#runnerups-table").hidden).toBe(true);
    expect(runnerupCalls(calls)).toEqual([]);
    expect(window.location.search).toContain("ev=strict");
  });

  it("treats the baked evidence as the default, so a plain address changes nothing", async () => {
    const { app, calls } = mountWiki();
    await app.whenIdle();
    expect(calls).toEqual([]);
    expect($("#ev-wiki").checked).toBe(true);
  });
});

// ---- the line that says what is shown, and the switches behind it on a phone --------------------------------------------------------------------
// On a narrow screen the switches fold away behind one line ("Ogre · Balanced · +4") and a Change button, so that the answer is on the first
// screen. The fold itself is the stylesheet's (and the e2e tests look at it); the page code keeps the line right and works the button.

describe("the line that says what is shown", () => {
  const line = () => $("#view-summary").textContent.replace(/\s+/g, " ").trim();

  it("is in the page as it is baked, with a Change button that is disabled (and drawn invisible, to keep its room) until the page code runs", () => {
    document.body.innerHTML = text("trio-main.html");
    expect($("#view-bar").hidden).toBe(false); // there from the first paint, so that the answer does not move when the code starts
    expect($("#switches-toggle").disabled).toBe(true);
    expect($("#view-bar").hasAttribute("data-ready")).toBe(false);
  });

  it("is marked ready when the page code starts: a browser that does not know the scripting media query shows the line by that mark", async () => {
    const { app } = mount();
    await app.whenIdle();
    expect($("#view-bar").hasAttribute("data-ready")).toBe(true);
  });

  it("is offered once the page code runs, closed, with a Change button that opens and closes the switches", async () => {
    const { app } = mount();
    await app.whenIdle();
    expect($("#view-bar").hidden).toBe(false);
    const button = $("#switches-toggle");
    expect(button.disabled).toBe(false);
    expect(button.textContent).toBe("Change");
    expect(button.getAttribute("aria-controls")).toBe("switches");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect($("#switches").hasAttribute("data-open")).toBe(false);
    button.click();
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect($("#switches").hasAttribute("data-open")).toBe(true);
    button.click();
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect($("#switches").hasAttribute("data-open")).toBe(false);
  });

  it("says the race, the role and the tier, and the assumptions, as the page arrives", () => {
    mount();
    expect(line()).toBe("Showing Ogre · Balanced · +4 dual wield, strict evidence, your own buffs");
  });

  it("follows every change of the view", async () => {
    const { app } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(line()).toBe("Showing Ogre · Balanced · +10 dual wield, strict evidence, your own buffs");
    choose("#role-tank");
    await app.whenIdle();
    expect(line()).toBe("Showing Ogre · Tank · +10 1H + shield, strict evidence, your own buffs");
    change($("#sw-race"), "TRL");
    choose("#ev-wiki");
    choose("#buffs-group");
    await app.whenIdle();
    expect(line()).toBe("Showing Troll · Tank · +10 1H + shield, wiki evidence, common group buffs");
  });

  it("is untouched by a view that fails to load", async () => {
    const { app } = mount("", { "strict-own": "offline" });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(line()).toBe("Showing Ogre · Balanced · +4 dual wield, strict evidence, your own buffs");
  });
});

// ---- what a change announces -----------------------------------------------------------------------------------------------------------------
// #announce is a polite live region. Its text names the switch that changed, what is shown now and what the kit is worth, so that two changes never
// sound alike (a change of buffs and a change of evidence both say "Ogre, Balanced, +4" and may move the value by the same amount).

describe("what a change of a switch announces", () => {
  const said = () => $("#announce").textContent;
  const value = (name, race, role, tier, setup) => fmt(Math.round(scenarioOf(name, race, role, tier, setup).value));

  it("names the tier that changed, what is shown and the kit value", async () => {
    const { app } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(said()).toBe(`Tier +10. Showing Ogre, Balanced, +10, Dual wield. Kit value ${value("strict-own", "OGR", "balanced", 10, "dw")}.`);
  });

  it("names the race, the role and the weapons", async () => {
    const { app } = mount();
    change($("#sw-race"), "TRL");
    await app.whenIdle();
    expect(said()).toBe(`Race Troll. Showing Troll, Balanced, +4, Dual wield. Kit value ${value("strict-own", "TRL", "balanced", 4, "dw")}.`);
    choose("#role-tank");
    await app.whenIdle();
    expect(said()).toBe(`Role Tank. Showing Troll, Tank, +4, 1H + shield. Kit value ${value("strict-own", "TRL", "tank", 4, "1h-shield")}.`);
    choose("#setup-2h");
    await app.whenIdle();
    expect(said()).toBe(`Weapons Two-hander. Showing Troll, Tank, +4, Two-hander. Kit value ${value("strict-own", "TRL", "tank", 4, "2h")}.`);
  });

  it("names the buffs and the evidence, which the line of what is shown does not repeat", async () => {
    const { app } = mount();
    choose("#buffs-group");
    await app.whenIdle();
    expect(said()).toBe(`Buffs common group buffs. Showing Ogre, Balanced, +4, Dual wield. Kit value ${value("strict-group", "OGR", "balanced", 4, "dw")}.`);
    choose("#buffs-own");
    choose("#ev-wiki");
    await app.whenIdle();
    expect(said()).toBe(`Evidence wiki evidence. Showing Ogre, Balanced, +4, Dual wield. Kit value ${value("wiki-own", "OGR", "balanced", 4, "dw")}.`);
  });

  it("is not the same text for two changes, even where the view and its value are alike", async () => {
    const { app } = mount();
    choose("#buffs-group");
    await app.whenIdle();
    const first = said();
    choose("#buffs-own");
    await app.whenIdle();
    const second = said();
    choose("#ev-wiki");
    await app.whenIdle();
    expect(new Set([first, second, said()]).size).toBe(3);
  });

  it("says nothing when the page opens, not even for an address that asks for another view", async () => {
    const { app } = mount("?tier=10&role=tank");
    await app.whenIdle();
    expect(said()).toBe("");
  });

  it("says nothing of a change that did not happen: a view that fails to load", async () => {
    const { app } = mount("", { "strict-own": "offline" });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(said()).toBe("");
  });
});

// ---- the status, its Try again button and the focus ------------------------------------------------------------------------------------------

describe("the status message, its Try again button and the focus", () => {
  const retryButton = () => $("#status button");

  it("is on the page from the start, empty and quiet, and never taken out of the tree", async () => {
    const { app } = mount();
    await app.whenIdle();
    const status = $("#status");
    expect(status.getAttribute("role")).toBe("status");
    expect(status.classList.contains("quiet")).toBe(true);
    expect(status.hidden).toBe(false);
    expect(status.textContent).toBe("");
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(status.classList.contains("quiet")).toBe(true); // a change that works leaves it as it was
  });

  it("says what went back when a switch cannot be changed, switch by switch", async () => {
    const cases = [
      [() => change($("#sw-tier"), "10"), "The tier is back at +4."],
      [() => change($("#sw-race"), "TRL"), "The race is back at Ogre."],
      [() => choose("#role-tank"), "The role is back at Balanced."],
      [() => choose("#setup-2h"), "The weapons are back at Dual wield."],
      [() => choose("#buffs-group"), "The buffs are back at your own buffs."],
      [() => choose("#ev-wiki"), "The evidence is back at strict evidence."],
    ];
    for (const [act, words] of cases) {
      const { app } = mount("", { "strict-own": "offline", "strict-group": "offline", "wiki-own": "offline" });
      act();
      await app.whenIdle();
      expect(status()).toMatch(/^Couldn't load this view; try again\. /);
      expect($("#status .status-text").textContent).toBe(`Couldn't load this view; try again. ${words}`);
      expect($("#status").classList.contains("quiet")).toBe(false);
    }
  });

  it("says what is still shown when the address asked for more than one thing the page could not load", async () => {
    const { app } = mount("?tier=10&role=tank", { "strict-own": "offline" });
    await app.whenIdle();
    expect($("#status .status-text").textContent).toBe("Couldn't load this view; try again. Still showing Ogre, Balanced, +4, Dual wield.");
  });

  it("keeps the button, and the focus on it, when the retry fails again", async () => {
    const { app, behaviour } = mount("", { "strict-own": "offline" });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const button = retryButton();
    button.focus();
    expect(document.activeElement).toBe(button);
    button.click();
    await app.whenIdle();
    expect(retryButton()).toBe(button); // the same button, not another one made in its place
    expect(document.activeElement).toBe(button);
    expect($("#status .status-text").textContent).toMatch(/^Couldn't load this view; try again\./);
    expect(behaviour["strict-own"]).toBe("offline");
  });

  it("keeps the button while the view loads again, then takes the focus to the answer when it has loaded", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const { app, behaviour } = mount("", { "strict-own": "offline" });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const button = retryButton();
    button.focus();
    behaviour["strict-own"] = gate; // the network is back, slowly
    button.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(retryButton()).toBe(button);
    expect(document.activeElement).toBe(button);
    expect($("#status .status-text").textContent).toBe("Loading this view…");
    release();
    await app.whenIdle();
    expect(retryButton()).toBeNull();
    expect(document.activeElement).toBe($("#wear-h")); // a place that is always there
    expect($("#status").classList.contains("quiet")).toBe(true);
    expect(rowCells()[0].tier).toBe("+10");
  });

  it("does not take the focus to the answer for a choice the visitor makes afterwards", async () => {
    const { app, behaviour } = mount("", { "strict-own": "offline" });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    retryButton().focus();
    retryButton().click();
    await app.whenIdle(); // fails again: still the retry
    delete behaviour["strict-own"];
    $("#sw-race").focus();
    change($("#sw-race"), "TRL"); // the visitor's own choice: the retry is over
    await app.whenIdle();
    expect(document.activeElement).toBe($("#sw-race"));
  });

  it("gives the focus back to the radio button that is checked again when a change of it is refused", async () => {
    const { app } = mount("", { "strict-own": "offline" });
    $("#role-tank").focus();
    choose("#role-tank"); // an arrow key moves the focus and checks the radio button, as this does
    await app.whenIdle();
    expect($("#role-balanced").checked).toBe(true);
    expect($("#role-tank").checked).toBe(false);
    expect(document.activeElement).toBe($("#role-balanced"));
  });
});

// ---- the alternatives of a view that is no longer shown -----------------------------------------------------------------------------------------
// The runner-ups and the robust core belong to one view. While the files of the next view come, what the expanders hold is the old view's, so it is
// taken off the page and a note says that the new one is coming.

describe("the expanders while the file of a new view loads", () => {
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

  it("hide the runner-ups of the old view, say that the new ones are coming, and show them when they come", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const { app } = mount("", { "runnerups/balanced": gate });
    openDetails("#runnerups");
    await app.whenIdle();
    expect($("#runnerups-table").hidden).toBe(false); // the baked view's own
    expect($("#runnerups-loading").hidden).toBe(true);
    expect($("#runnerups").hasAttribute("aria-busy")).toBe(false);
    change($("#sw-tier"), "10");
    for (let n = 0; n < 5; n++) await tick();
    expect($("#runnerups-table").hidden).toBe(true); // not the new view's: not shown
    expect($("#runnerups-na").hidden).toBe(true);
    expect($("#runnerups-loading").hidden).toBe(false);
    expect($("#runnerups").getAttribute("aria-busy")).toBe("true");
    expect(rowCells()[0].tier).toBe("+10"); // the answer itself is already the new view's
    release();
    await app.whenIdle();
    expect($("#runnerups-table").hidden).toBe(false);
    expect($("#runnerups-loading").hidden).toBe(true);
    expect($("#runnerups").hasAttribute("aria-busy")).toBe(false);
    const view = viewOf(runnerupsOf("balanced"), 10);
    expect([...document.querySelectorAll("#runnerups-body tr")][0].querySelectorAll("li")).toHaveLength(view[3][0].length);
  });

  it("hide the robust core of the old view the same way", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const { app } = mount("", { robust: gate });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    openDetails("#robust"); // its file is asked for now, and is slow
    for (let n = 0; n < 5; n++) await tick();
    expect($("#robust-summary").hidden).toBe(true); // the baked +4 summary is not +10's
    expect($("#robust-list").hidden).toBe(true);
    expect($("#robust-loading").hidden).toBe(false);
    expect($("#robust").getAttribute("aria-busy")).toBe("true");
    release();
    await app.whenIdle();
    expect($("#robust-summary").hidden).toBe(false);
    expect($("#robust-loading").hidden).toBe(true);
    expect($("#robust").hasAttribute("aria-busy")).toBe(false);
  });

  it("do not show the old view's content for the moment between opening a closed one and its file", async () => {
    let release;
    const gate = new Promise((resolve) => (release = resolve));
    const { app } = mount("", { "runnerups/balanced": gate });
    change($("#sw-tier"), "10"); // closed: nothing is fetched, and the old content waits behind the closed lid
    await app.whenIdle();
    openDetails("#runnerups");
    for (let n = 0; n < 5; n++) await tick();
    expect($("#runnerups-table").hidden).toBe(true);
    expect($("#runnerups-loading").hidden).toBe(false);
    release();
    await app.whenIdle();
    expect($("#runnerups-table").hidden).toBe(false);
  });

  it("say so, and are not busy any more, when the file cannot be loaded", async () => {
    const { app } = mount("", { "runnerups/balanced": "offline" });
    openDetails("#runnerups");
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect($("#runnerups-loading").hidden).toBe(true);
    expect($("#runnerups").hasAttribute("aria-busy")).toBe(false);
    expect($("#runnerups-na").textContent).toMatch(/couldn't load this section/i);
  });

  // A file that fails after the visitor has moved on belongs to a view that is no longer shown: it must not speak for the one that is. (A role has one file for
  // all its tiers, so the views of two files are those of two roles.)
  const countsOf = (role, tier) => viewOf(runnerupsOf(role), tier)[3].map((swaps) => swaps.length);

  it("ignore the late failure of the file of a view that is no longer shown, when the shown view's section is drawn", async () => {
    let fail;
    const gate = new Promise((resolve, reject) => (fail = reject));
    const { app } = mount("", { "runnerups/tank": gate });
    openDetails("#runnerups");
    choose("#role-tank"); // its file is asked for, and is slow ...
    for (let n = 0; n < 5; n++) await tick();
    choose("#role-balanced"); // ... and the visitor moves on before it comes: the file of this role comes at once
    for (let n = 0; n < 5; n++) await tick();
    expect($("#runnerups-table").hidden).toBe(false);
    fail(new TypeError("Failed to fetch"));
    await app.whenIdle();
    expect($("#runnerups-na").hidden).toBe(true);
    expect($("#runnerups-na").textContent).not.toMatch(/couldn't load this section/i);
    expect($("#runnerups-table").hidden).toBe(false);
    expect($("#runnerups-loading").hidden).toBe(true);
    expect($("#runnerups").hasAttribute("aria-busy")).toBe(false);
    expect(swapCounts()).toEqual(countsOf("balanced", 4));
  });

  it("ignore the late failure of the file of a view that is no longer shown, while the shown view's file is still coming", async () => {
    let fail;
    let release;
    const slow = new Promise((resolve, reject) => (fail = reject));
    const next = new Promise((resolve) => (release = resolve));
    const { app, calls } = mount("", { "runnerups/tank": slow, "runnerups/balanced": next });
    openDetails("#runnerups");
    choose("#role-tank");
    for (let n = 0; n < 5; n++) await tick();
    choose("#role-balanced");
    for (let n = 0; n < 5; n++) await tick();
    fail(new TypeError("Failed to fetch"));
    for (let n = 0; n < 5; n++) await tick();
    // the shown view's section is still waiting for its own file, and says so; nothing says the section could not be loaded
    expect($("#runnerups-loading").hidden).toBe(false);
    expect($("#runnerups").getAttribute("aria-busy")).toBe("true");
    expect($("#runnerups-na").hidden).toBe(true);
    release();
    await app.whenIdle();
    expect($("#runnerups-table").hidden).toBe(false);
    expect($("#runnerups-loading").hidden).toBe(true);
    expect(swapCounts()).toEqual(countsOf("balanced", 4));
    // and the section is not marked as one to fetch again: closing it and opening it asks for nothing more
    const asked = runnerupCalls(calls).length;
    $("#runnerups").open = false;
    openDetails("#runnerups");
    await app.whenIdle();
    expect(runnerupCalls(calls)).toHaveLength(asked);
  });

  it("still say so when the failing file is the shown view's own", async () => {
    const { app } = mount("", { "runnerups/balanced": "offline" });
    openDetails("#runnerups");
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect($("#runnerups-na").textContent).toMatch(/couldn't load this section/i);
    expect($("#runnerups-na").hidden).toBe(false);
    expect($("#runnerups-table").hidden).toBe(true);
  });
});

// ---- the switches before and after the page code -------------------------------------------------------------------------------------------
// The page is baked with every switch disabled: without the page code there is nothing to switch to, and a control that does nothing says so.

describe("the switches before and after the page code", () => {
  const SWITCH = '#sw-race, #sw-tier, input[name="role"], input[name="setup"], input[name="buffs"], input[name="ev"]';
  const controls = () => [...document.querySelectorAll(SWITCH)];
  const disabled = () => controls().filter((control) => control.disabled).map((control) => control.id);

  it("are all disabled in the page as it is baked", () => {
    document.body.innerHTML = text("trio-main.html");
    expect(controls().length).toBeGreaterThanOrEqual(12);
    expect(controls().filter((control) => !control.disabled).map((control) => control.id)).toEqual([]);
  });

  it("are enabled when the code runs, but for the weapon setups that the role has no scenario for", async () => {
    const { app } = mount();
    await app.whenIdle();
    expect(disabled()).toEqual([]); // the default role has every setup
    choose("#role-melee"); // the fixture's Melee has no 1H + shield
    await app.whenIdle();
    expect(disabled()).toEqual(["setup-1h-shield"]);
    choose("#role-balanced");
    await app.whenIdle();
    expect(disabled()).toEqual([]);
  });
});

// ---- the history entry ---------------------------------------------------------------------------------------------------------------------------
// The address is rewritten with replaceState on every change of the view. The entry may hold a state that something else keeps there (a link
// to a kit, in the next phase): rewriting the address must not throw it away.

describe("the history entry", () => {
  it("keeps the state it has when the address is rewritten", async () => {
    const { app } = mount();
    window.history.replaceState({ kit: "a1b2" }, "", window.location.href);
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(window.location.search).toBe("?race=OGR&role=balanced&tier=10&ev=strict&buffs=own");
    expect(window.history.state).toEqual({ kit: "a1b2" });
  });

  it("keeps no state when it has none", async () => {
    const { app } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(window.history.state).toBeNull();
  });

  it("keeps the state through the rewrite of the address a link asks for", async () => {
    document.body.innerHTML = text("trio-main.html");
    window.history.replaceState({ kit: "c3d4" }, "", "/trio/pal-mnk-ber/?tier=10&role=tank");
    const app = initTrio({ document, window, fetch: makeFetch([], {}) });
    await app.whenIdle();
    expect(window.location.search).toBe("?race=OGR&role=tank&tier=10&ev=strict&buffs=own");
    expect(window.history.state).toEqual({ kit: "c3d4" });
  });
});

// ---- a data file that does not belong to the page ------------------------------------------------------------------------------------------------
// Every data file names the release it was made from, and the page names the release it was built for. A site that was published again while the
// page was open serves files of the new release to the old page; those are not used, and the page says to reload.

describe("a data file of another release than the page", () => {
  const release = () => $("#main").dataset.release;
  const elsewhere = (name, patch = {}) => ({ json: { ...dataFile(name), release: "data-2099-01-01", ...patch } });
  const words = () => $("#status .status-text")?.textContent;
  const UPDATED = "Data updated, reload the page to see the new data.";

  it("names a release, and so does every file of the fixture, the same one", () => {
    mount();
    expect(release()).toMatch(/^data-\d{4}-\d{2}-\d{2}$/);
    for (const name of ["strict-own", "strict-group", "wiki-own", "wiki-group", "robust", "runnerups/balanced"]) expect(dataFile(name).release, name).toBe(release());
  });

  it("is not used: the answer stays, the switches go back, and the status says that the data was updated and offers a reload", async () => {
    const reload = vi.fn();
    const { app } = mount("", { "strict-own": elsewhere("strict-own") }, { reload });
    const before = rowCells();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(words()).toBe(`${UPDATED} The tier is back at +4.`); // and which switch went back
    expect(rowCells()).toEqual(before);
    expect($("#sw-tier").value).toBe("4");
    expect(window.location.search).toBe("");
    expect([...document.querySelectorAll("#status button")].map((button) => button.textContent)).toEqual(["Reload"]); // trying again would fetch the same file
    expect($("#status").classList.contains("quiet")).toBe(false);
    $("#status button").click();
    expect(reload).toHaveBeenCalledTimes(1);
    expect($("#announce").textContent).toBe(""); // nothing changed, so nothing is announced
  });

  it("is not used when it names no release at all: it is from before the release was written", async () => {
    const { app } = mount("", { "strict-own": elsewhere("strict-own", { release: undefined }) });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(words()).toBe(`${UPDATED} The tier is back at +4.`);
    expect(rowCells()[0].tier).toBe("+4");
  });

  it("is a failure to load, and not an update, when the file is no data file at all", async () => {
    const { app } = mount("", { "strict-own": { json: { v: 2, release: "data-2099-01-01" } } });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(words()).toMatch(/^Couldn't load this view; try again\./);
    expect($("#status button").textContent).toBe("Try again");
  });

  it("is looked for in every file the page asks for, the runner-ups and the robust core as well", async () => {
    const { app } = mount("", { "runnerups/balanced": elsewhere("runnerups/balanced"), robust: elsewhere("robust") });
    openDetails("#runnerups");
    openDetails("#robust");
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(rowCells()[0].tier).toBe("+10"); // the shard is of the page's release: the answer is shown
    expect(words() ?? "").toBe("");
    for (const name of ["runnerups", "robust"]) {
      expect($(`#${name}-na`).hidden, name).toBe(false);
      expect($(`#${name}-na`).textContent, name).toMatch(/^Data updated, reload the page to see/);
      expect($(`#${name}-loading`).hidden, name).toBe(true);
      expect($(`#${name}`).hasAttribute("aria-busy"), name).toBe(false);
    }
    expect($("#runnerups-table").hidden).toBe(true);
    expect($("#robust-summary").hidden).toBe(true);
  });

  it("is used when it is of the page's release, which is what every other test in this file shows", async () => {
    const { app } = mount("", { "strict-own": elsewhere("strict-own", { release: release() }) });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(rowCells()[0].tier).toBe("+10");
    expect(status()).toBe("");
  });
});

// ---- the link that reports a problem -------------------------------------------------------------------------------------------------------------
// The footer's link opens a new issue about the page. On the trio page it names the view the visitor is looking at (the trio is in the address
// of the page), so that a report can be looked at as it was seen. The build writes it for the default view; the page code keeps it right.

describe("the link that reports a problem", () => {
  const baked = () => text("trio-report-link.txt").trim();
  const attribute = (value) => value.replaceAll("&", "&amp;").replaceAll('"', "&quot;");
  const footer = () => `<footer><a id="report-link" href="${attribute(baked())}">Report a problem with this page</a></footer>`;
  const link = () => document.getElementById("report-link");
  const parts = (href) => {
    const url = new URL(href);
    const page = new URL(url.searchParams.get("page"));
    return { start: url.origin + url.pathname, template: url.searchParams.get("template"), title: url.searchParams.get("title"), page: page.origin + page.pathname, view: Object.fromEntries(page.searchParams) };
  };

  it("is what the build writes for the view the page opens on, and the page code leaves it alone until the view changes", async () => {
    const { app } = mount("", {}, { footer: footer() });
    await app.whenIdle();
    expect(link().getAttribute("href")).toBe(baked());
    expect(parts(baked()).view).toEqual({ race: "OGR", role: "balanced", tier: "4", setup: "dw", ev: "strict", buffs: "own" });
  });

  it("names the view that is shown: race, role, tier, weapons, evidence and buffs, with the weapons even where they are the role's best", async () => {
    const { app } = mount("", {}, { footer: footer() });
    change($("#sw-tier"), "10");
    choose("#role-tank");
    await app.whenIdle();
    const now = parts(link().getAttribute("href"));
    const first = parts(baked());
    expect(now.start).toBe(first.start);
    expect(now.template).toBe(first.template);
    expect(now.page).toBe(first.page); // the address of the page as the build knows it, with the view for a query
    expect(now.view).toEqual({ race: "OGR", role: "tank", tier: "10", setup: "1h-shield", ev: "strict", buffs: "own" });
    expect(now.title).toBe(first.title); // the title names the page; the view is in the address of the page
    change($("#sw-race"), "TRL");
    choose("#ev-wiki");
    choose("#buffs-group");
    choose("#setup-2h");
    await app.whenIdle();
    expect(parts(link().getAttribute("href")).view).toEqual({ race: "TRL", role: "tank", tier: "10", setup: "2h", ev: "wiki", buffs: "group" });
  });

  it("is the very text the build wrote when the view is the one the page opened on again: the script and the build word it alike", async () => {
    const { app } = mount("", {}, { footer: footer() });
    change($("#sw-tier"), "10");
    choose("#ev-wiki");
    await app.whenIdle();
    expect(link().getAttribute("href")).not.toBe(baked());
    change($("#sw-tier"), "4");
    choose("#ev-strict");
    await app.whenIdle();
    expect(link().getAttribute("href")).toBe(baked());
  });

  it("follows the view a link asks for", async () => {
    const { app } = mount("?tier=10&role=tank", {}, { footer: footer() });
    await app.whenIdle();
    expect(parts(link().getAttribute("href")).view).toEqual({ race: "OGR", role: "tank", tier: "10", setup: "1h-shield", ev: "strict", buffs: "own" });
  });

  it("is not changed by a view that could not be loaded", async () => {
    const { app } = mount("", { "strict-own": "offline" }, { footer: footer() });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(link().getAttribute("href")).toBe(baked());
  });

  it("is left alone when it is not on the page (a preview has no account to report to), and nothing breaks", async () => {
    const { app } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(document.getElementById("report-link")).toBeNull();
    expect(rowCells()[0].tier).toBe("+10");
  });

  it("is left alone when it is not an address", async () => {
    const { app } = mount("", {}, { footer: '<footer><a id="report-link" href="not an address">Report</a></footer>' });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(rowCells()[0].tier).toBe("+10");
    expect(link().getAttribute("href")).toBe("not an address");
  });
});

// ---- the theme ---------------------------------------------------------------------------------------------------------------------

function memoryStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => void map.set(key, String(value)),
    removeItem: (key) => void map.delete(key),
    map,
  };
}
const deniedStorage = {
  getItem() {
    throw new DOMException("denied", "SecurityError");
  },
  setItem() {
    throw new DOMException("denied", "SecurityError");
  },
  removeItem() {
    throw new DOMException("denied", "SecurityError");
  },
};

describe("the theme", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    document.body.innerHTML = '<button type="button" id="theme-toggle" class="theme-toggle" hidden>Theme</button>';
  });

  it("leaves the system setting alone on a first visit and writes nothing", () => {
    const storage = memoryStorage();
    applyStoredTheme(document, storage);
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    bindThemeToggle(document, storage);
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(storage.map.size).toBe(0);
    expect($("#theme-toggle").hidden).toBe(false);
    expect($("#theme-toggle").textContent).toBe("Theme: auto");
  });

  it("applies a stored choice and ignores anything else", () => {
    applyStoredTheme(document, memoryStorage({ [THEME_KEY]: "dark" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    document.documentElement.removeAttribute("data-theme");
    applyStoredTheme(document, memoryStorage({ [THEME_KEY]: "<script>" }));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("cycles auto, light, dark, auto and remembers each choice", () => {
    const storage = memoryStorage();
    bindThemeToggle(document, storage);
    const button = $("#theme-toggle");
    button.click();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(storage.getItem(THEME_KEY)).toBe("light");
    expect(button.textContent).toBe("Theme: light");
    button.click();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(storage.getItem(THEME_KEY)).toBe("dark");
    button.click();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(storage.getItem(THEME_KEY)).toBeNull();
    expect(button.textContent).toBe("Theme: auto");
  });

  it("starts from the stored choice when the button appears", () => {
    bindThemeToggle(document, memoryStorage({ [THEME_KEY]: "light" }));
    expect($("#theme-toggle").textContent).toBe("Theme: light");
  });

  it("still works when storage is blocked", () => {
    applyStoredTheme(document, deniedStorage);
    bindThemeToggle(document, deniedStorage);
    $("#theme-toggle").click();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    const blocked = {};
    Object.defineProperty(blocked, "localStorage", {
      get() {
        throw new DOMException("denied", "SecurityError");
      },
    });
    expect(getStorage(blocked)).toBeNull();
    document.documentElement.removeAttribute("data-theme");
    document.body.innerHTML = '<button type="button" id="theme-toggle" class="theme-toggle" hidden>Theme</button>';
    bindThemeToggle(document, null);
    $("#theme-toggle").click();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});

// ---- the home page picker ----------------------------------------------------------------------------------------------------------

describe("the trio picker", () => {
  beforeEach(() => {
    document.body.innerHTML = text("home-main.html");
    initPicker(document);
  });
  const pick = (...codes) => {
    for (const code of codes) {
      const box = document.querySelector(`#picker input[value="${code}"]`);
      box.checked = true;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    }
  };

  it("is offered once the script runs", () => {
    expect(document.getElementById("picker").hidden).toBe(false);
  });

  it("opens the live trio in any order of picking", () => {
    pick("BER", "PAL", "MNK");
    const link = document.querySelector("#picker-status a");
    expect(link.getAttribute("href")).toBe("/trio/pal-mnk-ber/");
    expect(link.textContent).toContain("Paladin / Monk / Berserker");
  });

  it("says coming soon for every other trio", () => {
    pick("PAL", "MNK", "ROG");
    expect(document.querySelector("#picker-status a")).toBeNull();
    expect(document.getElementById("picker-status").textContent).toMatch(/coming soon/i);
    expect(document.getElementById("picker-status").textContent).toContain("Paladin / Monk / Rogue");
  });

  it("stops at three classes and gives the choice back when one is removed", () => {
    pick("PAL", "MNK", "BER");
    const others = [...document.querySelectorAll('#picker input[type="checkbox"]')].filter((b) => !b.checked);
    expect(others.every((b) => b.disabled)).toBe(true);
    const first = document.querySelector('#picker input[value="PAL"]');
    first.checked = false;
    first.dispatchEvent(new Event("change", { bubbles: true }));
    expect(others.every((b) => !b.disabled)).toBe(true);
    expect(document.getElementById("picker-status").textContent).toMatch(/pick .*(one|1) more/i);
  });
});

// ---- the names of the items are links to their pages -----------------------------------------------------------------------------------

describe("the names of the items in Wear this", () => {
  /** For each of the 22 rows, the addresses of the links in its name (none for an empty place or for plain text). */
  const anchors = () => [...document.querySelectorAll("#kit-body tr")].map((tr) => [...tr.querySelectorAll('[data-f="name"] a')].map((a) => a.getAttribute("href")));
  const linked = (kit) => kit.map((item) => (item ? [`/item/${item[0]}/`] : []));
  /** The baked page with its `<main>` changed by `edit`, the page code started on it, and a switch of the tier to +10, which paints a kit the page code made. */
  async function switched(edit, behaviour = {}) {
    document.body.innerHTML = edit(text("trio-main.html"));
    window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
    const calls = [];
    const app = initTrio({ document, window, fetch: makeFetch(calls, behaviour) });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    return app;
  }

  it("are links to the pages of the items in the baked page, and the empty place is not one", () => {
    mount();
    const want = scenarioOf("strict-own", "OGR", "balanced", 4, "dw");
    expect($("#main").dataset.items).toBe("/item/");
    expect(anchors()).toEqual(linked(want.kit));
    expect(anchors()[19]).toEqual([]); // "Leave empty"
    expect(rowCells()[0].name).toBe("Helm of the Stoneward"); // the words are the same with or without the link
    expect(document.querySelector('#kit-body [data-f="name"] a').textContent).toBe("Helm of the Stoneward");
  });

  it("stay links, to the pages of the items that are shown now, when a switch paints another kit", async () => {
    const { app } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const want = scenarioOf("strict-own", "OGR", "balanced", 10, "dw");
    expect(anchors()).toEqual(linked(want.kit));
    for (const [index, item] of want.kit.entries()) {
      if (item) expect(document.querySelectorAll('#kit-body [data-f="name"]')[index].textContent).toBe(item[1]);
    }
    choose("#role-tank");
    await app.whenIdle();
    expect(anchors()).toEqual(linked(scenarioOf("strict-own", "OGR", "tank", 10, "1h-shield").kit)); // another kit, other items, other addresses
  });

  it("are links to the right items when a place that was empty is filled and a place that was filled is emptied", async () => {
    const doc = JSON.parse(text("data/strict-own.json"));
    const row = doc.rows.find((r) => r[0] === "OGR" && r[1] === "balanced" && r[2] === 10 && r[3] === "dw");
    const kit = doc.kits[row[4]];
    expect(kit[19]).toBe(-1); // the second Any slot is empty in the fixture's kit
    kit[19] = kit[0]; // filled with the item of the head ...
    kit[0] = -1; // ... which the head gives up
    const { app } = mount("", { "strict-own": { json: doc } });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const head = document.querySelectorAll("#kit-body tr")[0].querySelector('[data-f="name"]');
    const any = document.querySelectorAll("#kit-body tr")[19].querySelector('[data-f="name"]');
    expect(head.textContent).toBe("Leave empty");
    expect(head.querySelector("a")).toBeNull();
    expect(any.querySelector("a").getAttribute("href")).toBe(`/item/${doc.items[kit[19]][0]}/`);
    expect(any.textContent).toBe(doc.items[kit[19]][1]);
  });

  it("are plain text, after a switch, in a page that does not say that every item it can show has a page", async () => {
    const app = await switched((html) => html.replace(' data-items="/item/"', ""));
    expect(document.querySelectorAll('#kit-body [data-f="name"] a')).toHaveLength(0);
    const want = scenarioOf("strict-own", "OGR", "balanced", 10, "dw");
    expect(rowCells().map((r) => r.name)).toEqual(want.kit.map((item) => (item ? item[1] : "Leave empty")));
    expect(app).not.toBeNull();
  });

  it("are not links to any address but the one the build writes: another base is not followed", async () => {
    await switched((html) => html.replace('data-items="/item/"', 'data-items="https://example.invalid/item/"'));
    expect(document.querySelectorAll('#kit-body [data-f="name"] a')).toHaveLength(0);
    await switched((html) => html.replace('data-items="/item/"', 'data-items="/rules/"'));
    expect(document.querySelectorAll('#kit-body [data-f="name"] a')).toHaveLength(0);
  });

  it("are plain text for a key that the build would never have made a page of", async () => {
    const doc = JSON.parse(text("data/strict-own.json"));
    const row = doc.rows.find((r) => r[0] === "OGR" && r[1] === "balanced" && r[2] === 10 && r[3] === "dw");
    const kit = doc.kits[row[4]];
    const odd = ["../../rules", "W90001", "w90001/../x", "javascript:alert(1)", "a b", ""];
    const places = kit.map((index, place) => [index, place]).filter(([index]) => index >= 0).slice(0, odd.length);
    expect(places).toHaveLength(odd.length);
    // the shard is read as it comes: a key is text, and the page code decides what an address may be
    for (const [n, [index]] of places.entries()) doc.items[index][0] = odd[n];
    const { app } = mount("", { "strict-own": { json: doc } });
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const shown = anchors();
    for (const [, place] of places) expect(shown[place], `place ${place}`).toEqual([]);
    expect(shown.flat().length).toBe(kit.filter((index) => index >= 0).length - odd.length); // the others are links
    expect(rowCells()[places[0][1]].name).toBe(doc.items[places[0][0]][1]); // and the name is still shown
  });

  it("are the same links when the default view is drawn again by the page code", async () => {
    const { app } = mount();
    const before = anchors();
    await app.refresh();
    expect(anchors()).toEqual(before);
    expect(before.flat()).toHaveLength(21);
  });

  it("are written with the DOM (an element, an attribute and text) and never as a string of HTML", () => {
    const source = readFileSync(resolve(STATIC, "trio.js"), "utf8");
    expect(source).toMatch(/createElement\("a"\)/);
    expect(source).toMatch(/const ITEM_KEY = \/\^\(\?:w\[1-9\]\[0-9\]\{0,14\}\|r\[a-z0-9\]\[a-z0-9-\]\{0,99\}\)\$\/;/); // the one pattern of an item key (data.py: KEY_PATTERN, which the build uses too)
    expect(source).not.toMatch(/innerHTML|insertAdjacentHTML/);
  });
});

// ---- no string-to-DOM sinks anywhere in the page code --------------------------------------------------------------------------------

describe("the page code", () => {
  const files = readdirSync(STATIC).filter((name) => name.endsWith(".js"));
  const sinks =
    /innerHTML|outerHTML|insertAdjacentHTML|document\s*\.\s*write|createContextualFragment|\beval\s*\(|new\s+Function|setAttribute\(\s*["']on|srcdoc|DOMParser|execScript|importScripts|setTimeout\(\s*["'`]|setInterval\(\s*["'`]/;

  it("has the files of the page code", () => {
    expect(files).toEqual(expect.arrayContaining(["app.js", "trio.js", "theme.js", "boot.js", "picker.js"]));
  });

  for (const name of files) {
    it(`${name} uses no innerHTML, insertAdjacentHTML, document.write, eval or other string-to-DOM sink`, () => {
      const source = readFileSync(resolve(STATIC, name), "utf8");
      expect(source).not.toMatch(sinks);
    });
  }

  it("makes no request except to its own data folder", () => {
    for (const name of files) {
      const source = readFileSync(resolve(STATIC, name), "utf8");
      expect(source).not.toMatch(/https?:\/\//);
      expect(source).not.toMatch(/XMLHttpRequest|WebSocket|sendBeacon|EventSource/);
    }
  });
});
