// @vitest-environment jsdom
//
// The section "Get these first" of the trio page (trio.js and static/ui/common-items.js), run in jsdom against the baked page of the contract fixture (fixtures/site/contract/): a closed
// details with a static summary and an empty container. Nothing is fetched for it before it is asked for: opening it loads the shard of the default view (the baked answer has none), and
// any change of view that loads a shard draws it, closed or open; it is drawn again whenever the shard, the race or the tier changes. The shards the tests need to say something
// specific are made by hand (tests-js/common-items.mjs); the fixture's own are read the plain way to say what the page must show for them.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import { shardDocument } from "./common-items.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const text = (name) => readFileSync(resolve(CONTRACT, name), "utf8");
const dataFile = (name) => JSON.parse(text(`data/${name}.json`));
const PAGE = text("trio-main.html");

const $ = (selector) => document.querySelector(selector);
const SUMMARY = () => $("#common > summary").textContent;
const STATIC_SUMMARY = "Get these first";
const headings = () => [...document.querySelectorAll("#common-body h3")].map((h) => h.textContent);
const rows = (group) => [...document.querySelectorAll(`#common-body ul[data-group="${group}"] > li`)];
const names = (group) => rows(group).map((li) => li.querySelector("a, .common-name").textContent);

/** The answers of the page's fetch: the fixture's shards by name, others by hand (`custom`: name -> document), a file held back until a test lets it go (`gates`), or one that fails (`offline`). */
function makeFetch(calls, { custom = {}, gates = {}, offline = [] } = {}) {
  return async (url) => {
    calls.push(String(url));
    const name = String(url).replace("/data/pal-mnk-ber/", "").replace(".json", "");
    if (gates[name]) await gates[name];
    if (offline.includes(name)) throw new TypeError("Failed to fetch");
    return { ok: true, status: 200, json: async () => structuredClone(custom[name] ?? dataFile(name)) };
  };
}

function mount({ search = "", html = PAGE, ...behaviour } = {}) {
  document.body.innerHTML = html;
  window.history.replaceState(null, "", `/trio/pal-mnk-ber/${search}`);
  const calls = [];
  const app = initTrio({ document, window, fetch: makeFetch(calls, behaviour) });
  return { app, calls };
}

/** What a click on the summary does in a browser: the details element opens, and says so. */
function openSection() {
  const box = $("#common");
  box.open = true;
  box.dispatchEvent(new Event("toggle"));
}

/** Open the section and let the page finish what that started. */
async function settle(app) {
  openSection();
  await app.whenIdle();
}

const change = (element, value) => {
  element.value = value;
  element.dispatchEvent(new Event("change", { bubbles: true }));
};
const choose = (selector) => {
  const radio = $(selector);
  radio.checked = true;
  radio.dispatchEvent(new Event("change", { bubbles: true }));
};

/** Scenarios for the races of the fixture page: `kits` is { tier: { role: { place: key } } }, every one in the dual-wield setup. */
const grid = (kits, races = ["OGR", "ELF", "TRL"]) =>
  races.flatMap((race) => Object.entries(kits).flatMap(([tier, roles]) => Object.entries(roles).map(([role, kit]) => ({ race, role, tier: Number(tier), setup: "dw", kit }))));
const doc = (kits, names = {}, extra = {}) => shardDocument(grid(kits), names, { ev: "strict", buffs: "own", release: "data-2026-10-14", ...extra });
/** All three roles of the page wear `shared` in the places given and each has a piece of its own at the head. */
const trio = (shared, own = { balanced: "cap", tank: "helm", melee: "hood" }) => ({
  balanced: { 0: own.balanced, ...shared },
  tank: { 0: own.tank, ...shared },
  melee: { 0: own.melee, ...shared },
});

// ---- the baked page ---------------------------------------------------------------------------------------------------------------

describe("the baked page", () => {
  it("has the section as a closed details with its summary and an empty container, directly below Wear this, and little else", () => {
    mount();
    const section = $("#common");
    expect(section.tagName).toBe("DETAILS");
    expect(section.open).toBe(false);
    expect(section.hidden).toBe(false);
    expect(SUMMARY()).toBe(STATIC_SUMMARY);
    expect($("#common-body").childNodes).toHaveLength(0);
    expect(section.previousElementSibling).toBe($('section.answer[aria-labelledby="wear-h"]')); // (below the answer: it keeps the first screen of a phone)
    expect(section.nextElementSibling).toBe($("#why"));
    expect(section.outerHTML.length).toBeLessThan(250);
  });

  it("fetches nothing for it before it is opened: the baked answer is shown without any data file", async () => {
    const { app, calls } = mount();
    await app.whenIdle();
    await new Promise((go) => setTimeout(go, 400)); // (past the wait the page script gives the browser to be idle)
    expect(calls).toEqual([]);
    expect(SUMMARY()).toBe(STATIC_SUMMARY);
    expect($("#common-body").childNodes).toHaveLength(0);
  });
});

// ---- what it says, for the shards of the fixture ------------------------------------------------------------------------------------

/** What the page must show for a fixture shard, read the plain way: the best setup of each role, the items by role, in order of first place then name. */
function expected(name, race, tier) {
  const file = dataFile(name);
  const best = new Map();
  for (const row of file.rows) {
    if (row[0] !== race || row[2] !== tier) continue;
    const have = best.get(row[1]);
    if (!have || row[5] > have[5]) best.set(row[1], row);
  }
  const roles = [...best.keys()];
  const wearers = new Map();
  for (const [role, row] of best) {
    file.kits[row[4]].forEach((index, place) => {
      if (index < 0) return;
      const entry = wearers.get(index) ?? { name: file.items[index][1], key: file.items[index][0], place, roles: new Set() };
      entry.place = Math.min(entry.place, place);
      entry.roles.add(role);
      wearers.set(index, entry);
    });
  }
  const sorted = (list) => list.sort((a, b) => a.place - b.place || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  const every = [...wearers.values()].filter((e) => e.roles.size === roles.length);
  const most = [...wearers.values()].filter((e) => e.roles.size < roles.length && e.roles.size * 2 > roles.length);
  return { every: sorted(every), most: sorted(most) };
}
const wanted = (name, race, tier) => {
  const found = expected(name, race, tier);
  return { every: found.every.map((entry) => entry.name), most: found.most.map((entry) => entry.name) };
};

describe("the section drawn from the shard of the fixture", () => {
  it("is filled when it is opened, from the shard of the default view, and says so in the summary", async () => {
    const { app, calls } = mount();
    expect(SUMMARY()).toBe(STATIC_SUMMARY);
    expect(calls).toEqual([]); // (nothing is asked before it is opened)
    await settle(app);
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
    const want = wanted("strict-own", "OGR", 4);
    expect(want.every.length).toBeGreaterThan(0);
    expect(want.most.length).toBeGreaterThan(0);
    expect(SUMMARY()).toBe(`Get these first: ${want.every.length} items every role wears, ${want.most.length} most roles wear`);
    expect(names("every")).toEqual(want.every);
    expect(names("most")).toEqual(want.most);
    expect(headings()).toEqual(["Every role", "Most roles"]);
    expect($("#common").hidden).toBe(false);
    expect($("#common").open).toBe(true); // (the visitor's own opening is left as it is)
  });

  it("has the lists as real lists under real headings, with the line that says what the section is", async () => {
    const { app } = mount();
    await settle(app);
    const body = $("#common-body");
    for (const heading of body.querySelectorAll("h3")) {
      const list = heading.nextElementSibling;
      expect(list.tagName).toBe("UL");
      expect(list.getAttribute("data-group")).toBe(heading.textContent === "Every role" ? "every" : "most");
    }
    expect(body.querySelector("p").textContent).toBe(
      "The items each role's best kit has in common at this race and tier. Exalt advice differs by role: see Wear this. Each role uses its own best weapon setup.",
    );
  });

  it("follows the race and the tier, from the same shard, without fetching again", async () => {
    const { app, calls } = mount();
    await settle(app);
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const at10 = wanted("strict-own", "OGR", 10);
    expect(names("every")).toEqual(at10.every);
    change($("#sw-race"), "ELF");
    await app.whenIdle();
    const elf = wanted("strict-own", "ELF", 10);
    expect(names("every")).toEqual(elf.every);
    expect(names("most")).toEqual(elf.most);
    expect(SUMMARY()).toBe(`Get these first: ${elf.every.length} items every role wears, ${elf.most.length} most roles wear`);
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
  });

  it("follows the buffs: the other shard has its own kits", async () => {
    const group = doc({ 4: trio({ 1: "veil", 2: "stud" }) }, {}, { buffs: "group" });
    const { app, calls } = mount({ custom: { "strict-group": group } });
    await settle(app);
    const before = names("every");
    choose("#buffs-group");
    await app.whenIdle();
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json", "/data/pal-mnk-ber/strict-group.json"]);
    expect(names("every")).toEqual(["veil", "stud"]);
    expect(names("every")).not.toEqual(before);
    expect(names("most")).toEqual([]);
    expect(SUMMARY()).toBe("Get these first: 2 items every role wears");
  });

  it("is drawn through the path of Wear this when the address asks for another view, closed, and opening it fetches nothing more", async () => {
    const { app, calls } = mount({ search: "?tier=10&race=TRL" });
    await app.whenIdle();
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
    const want = wanted("strict-own", "TRL", 10);
    expect(names("every")).toEqual(want.every);
    expect($("#common").open).toBe(false);
    expect(SUMMARY()).toContain("every role wears");
    await settle(app);
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
    expect(names("every")).toEqual(want.every);
  });

  it("is drawn by a change of view whether it is open or not, and opening it afterwards shows what that drew", async () => {
    const { app, calls } = mount();
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const at10 = wanted("strict-own", "OGR", 10);
    expect($("#common").open).toBe(false);
    expect(names("every")).toEqual(at10.every);
    expect(SUMMARY()).toBe(`Get these first: ${at10.every.length} items every role wears, ${at10.most.length} most roles wear`);
    const list = document.querySelector("#common-body ul");
    await settle(app);
    expect(document.querySelector("#common-body ul")).toBe(list); // (opening it draws nothing again)
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
  });

  it("opened while a view is loading, leaves the drawing to that view and fetches nothing for itself", async () => {
    let release;
    const gate = new Promise((go) => (release = go));
    const group = doc({ 4: trio({ 1: "veil" }) }, {}, { buffs: "group" });
    const { app, calls } = mount({ gates: { "strict-group": gate }, custom: { "strict-group": group } });
    choose("#buffs-group");
    openSection();
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-group.json"]);
    expect($("#common-body").childNodes).toHaveLength(0);
    release();
    await app.whenIdle();
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-group.json"]);
    expect(names("every")).toEqual(["veil"]);
  });
});

describe("the shard of the baked view arriving late", () => {
  it("does not draw over a view the visitor has chosen and drawn in the meantime", async () => {
    let release;
    const gate = new Promise((go) => (release = go));
    const group = doc({ 4: trio({ 1: "veil", 2: "stud" }) }, {}, { buffs: "group" });
    const { app, calls } = mount({ gates: { "strict-own": gate }, custom: { "strict-group": group } });
    openSection(); // the page asks for the shard of the default view, which is held back
    await new Promise((go) => setTimeout(go, 0));
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
    choose("#buffs-group"); // and the visitor chooses a view of another shard, which comes at once
    await new Promise((go) => setTimeout(go, 0));
    expect(names("every")).toEqual(["veil", "stud"]);
    release();
    await app.whenIdle();
    await new Promise((go) => setTimeout(go, 0));
    await app.whenIdle();
    expect(names("every")).toEqual(["veil", "stud"]); // (the late shard is of a view that is not shown)
    expect(SUMMARY()).toBe("Get these first: 2 items every role wears");
  });
});

// ---- the summary, the groups and the rows, for shards made by hand ------------------------------------------------------------------------

describe("the words of the summary and the rows", () => {
  it("leaves out a half that is zero, and says item for one", async () => {
    // every role wears two items, and two of three wear a third: both halves
    const both = doc({ 4: { balanced: { 0: "helm", 1: "cap", 2: "stud" }, tank: { 0: "helm", 1: "cap", 2: "stud" }, melee: { 0: "helm", 1: "cap", 2: "hood" } } });
    let made = mount({ custom: { "strict-own": both } });
    await settle(made.app);
    expect(SUMMARY()).toBe("Get these first: 2 items every role wears, 1 most roles wear");
    // only the first half
    made = mount({ custom: { "strict-own": doc({ 4: trio({ 1: "veil", 2: "stud" }) }) } });
    await settle(made.app);
    expect(SUMMARY()).toBe("Get these first: 2 items every role wears");
    // only the second
    const second = doc({ 4: { balanced: { 0: "helm", 1: "cap" }, tank: { 0: "helm", 1: "cap" }, melee: { 0: "hood", 1: "veil" } } });
    made = mount({ custom: { "strict-own": second } });
    await settle(made.app);
    expect(SUMMARY()).toBe("Get these first: 2 items most roles wear");
    expect(headings()).toEqual(["Most roles"]); // (a group with nothing in it has no heading and no list)
    expect(document.querySelectorAll("#common-body ul")).toHaveLength(1);
    // one item
    made = mount({ custom: { "strict-own": doc({ 4: trio({ 1: "veil" }) }) } });
    await settle(made.app);
    expect(SUMMARY()).toBe("Get these first: 1 item every role wears");
  });

  it("is hidden when nothing is in common, and when the trio has fewer than two roles", async () => {
    const none = doc({ 4: { balanced: { 0: "a" }, tank: { 0: "b" }, melee: { 0: "c" } } });
    let made = mount({ custom: { "strict-own": none } });
    await settle(made.app);
    expect($("#common").hidden).toBe(true);
    expect($("#common-body").childNodes).toHaveLength(0);
    // one role only
    made = mount({ custom: { "strict-own": doc({ 4: { balanced: { 0: "helm" } } }) } });
    await settle(made.app);
    expect($("#common").hidden).toBe(true);
  });

  it("is shown again when a view that has something in common comes after one that has none", async () => {
    const mixed = doc({
      0: { balanced: { 0: "a" }, tank: { 0: "b" }, melee: { 0: "c" } },
      4: trio({ 1: "veil" }),
      10: trio({ 1: "veil" }),
    });
    const { app } = mount({ custom: { "strict-own": mixed } });
    await settle(app);
    expect($("#common").hidden).toBe(false);
    change($("#sw-tier"), "0");
    await app.whenIdle();
    expect($("#common").hidden).toBe(true);
    change($("#sw-tier"), "4");
    await app.whenIdle();
    expect($("#common").hidden).toBe(false);
    expect(names("every")).toEqual(["veil"]);
  });

  it("says in each row of the second group which roles do not wear the item, in the page's own words for the roles", async () => {
    const kits = {
      4: {
        balanced: { 0: "helm", 1: "cap" },
        tank: { 0: "helm", 1: "cap" },
        melee: { 0: "helm", 1: "hood" },
      },
    };
    const { app } = mount({ custom: { "strict-own": doc(kits) } });
    await settle(app);
    expect(rows("every").map((li) => li.textContent)).toEqual([expect.not.stringContaining("not ")]);
    const [row] = rows("most");
    expect(row.querySelector(".common-miss").textContent).toBe("not Melee");
    expect(rows("every")[0].querySelector(".common-miss")).toBeNull();
  });

  it("names more than one missing role with 'or' (five roles, three of them wearing the item), in the order of the roles", async () => {
    // (the page's label for the caster has a gloss, which the note leaves out: "Caster (healing or nuking)" is "Caster" there)
    const extra = (code, label) => `<span class="seg-item"><input type="radio" name="role" id="role-${code}" value="${code}" data-label="${label}" data-hint="x" data-setups="dw" disabled><label for="role-${code}">${label}</label></span>`;
    const html = PAGE.replace('<span class="seg-item"><input type="radio" name="role" id="role-melee"', extra("caster", "Caster (healing or nuking)") + extra("healer", "Healer") + '<span class="seg-item"><input type="radio" name="role" id="role-melee"');
    const kits = {
      4: {
        balanced: { 0: "helm", 1: "cap" },
        tank: { 0: "helm", 1: "cap" },
        melee: { 0: "helm", 1: "cap" },
        caster: { 0: "helm", 1: "hood" },
        healer: { 0: "helm", 1: "veil" },
      },
    };
    const { app } = mount({ html, custom: { "strict-own": doc(kits) } });
    await settle(app);
    expect(rows("most")[0].querySelector(".common-miss").textContent).toBe("not Caster or Healer");
    expect(rows("every")).toHaveLength(1);
  });

  it("says 2x only when every role that has the item wears two, and counts the item once per role", async () => {
    const kits = {
      4: {
        balanced: { 2: "stud", 3: "stud", 0: "helm", 11: "band", 12: "band" },
        tank: { 2: "stud", 3: "stud", 0: "helm", 11: "band" },
        melee: { 2: "stud", 3: "stud", 0: "helm", 11: "band", 12: "band" },
      },
    };
    const { app } = mount({ custom: { "strict-own": doc(kits, { stud: "Stud of Bashing", band: "Plain Band", helm: "Helm" }) } });
    await settle(app);
    expect(SUMMARY()).toBe("Get these first: 3 items every role wears");
    const byName = Object.fromEntries(rows("every").map((li) => [li.querySelector("a, .common-name").textContent, li]));
    expect(byName["Stud of Bashing"].querySelector(".common-n").textContent).toBe("2x");
    expect(byName["Plain Band"].querySelector(".common-n")).toBeNull();
    expect(byName.Helm.querySelector(".common-n")).toBeNull();
  });

  it("gives each row the name as a link, the slot, and how to get the item, in the words of the rows of Wear this", async () => {
    const { app } = mount();
    await settle(app);
    const file = dataFile("strict-own");
    const first = rows("every")[0];
    const link = first.querySelector("a");
    const [top] = expected("strict-own", "OGR", 4).every;
    expect(link.textContent).toBe(top.name);
    const item = file.items.find((entry) => entry[0] === top.key);
    expect(link.getAttribute("href")).toBe(`/item/${top.key}/`);
    const slot = $("#kit-body").children[top.place].querySelector("th").textContent; // (the word the row of that place of Wear this says)
    const words = first.querySelector(".common-how").textContent;
    expect(words).toContain(`Slot: ${slot}`);
    expect(words).toContain(`Arrives at: +${item[3]}`);
    expect(words).toContain(`Source: ${item[4]}`);
  });

  it("says the reach of an item that arrives below the tier shown, and a summoned item arrives at its spell rank", async () => {
    const base = doc({ 10: trio({ 1: "veil", 2: "spell" }) }, { veil: "Veil", spell: "Summoned Ring" });
    base.items.find((entry) => entry[0] === "veil")[3] = 4; // arrives at +4: 64 copies to reach +10
    base.items.find((entry) => entry[0] === "spell")[3] = null;
    const { app } = mount({ search: "?tier=10", custom: { "strict-own": base } });
    await app.whenIdle();
    const how = Object.fromEntries(rows("every").map((li) => [li.querySelector("a, .common-name").textContent, li.querySelector(".common-how").textContent]));
    expect(how.Veil).toContain("Arrives at: +4");
    expect(how.Veil).toContain("64 copies to reach +10");
    expect(how["Summoned Ring"]).toContain("Arrives at: spell rank");
    expect(how["Summoned Ring"]).not.toContain("copies");
  });

  it("says what deity an item needs, as the rows do", async () => {
    const base = doc({ 4: trio({ 1: "veil" }) }, { veil: "Veil" });
    base.items.find((entry) => entry[0] === "veil")[6] = ["Tunare", "Erollisi Marr"];
    const { app } = mount({ custom: { "strict-own": base } });
    await settle(app);
    expect(rows("every")[0].querySelector(".deity").textContent).toBe("Needs deity: Tunare or Erollisi Marr");
  });

  it("puts an item's name in as text, never as markup, and links it only where the page says its items have pages", async () => {
    const base = doc({ 4: trio({ 1: "w100" }) }, { w100: "<b>x</b> Ring" });
    let made = mount({ custom: { "strict-own": base } });
    await settle(made.app);
    const link = rows("every")[0].querySelector("a");
    expect(link.textContent).toBe("<b>x</b> Ring");
    expect(rows("every")[0].querySelector("b")).toBeNull();
    expect(link.getAttribute("href")).toBe("/item/w100/");
    made = mount({ html: PAGE.replace(' data-items="/item/"', ""), custom: { "strict-own": base } });
    await settle(made.app);
    expect(rows("every")[0].querySelector("a")).toBeNull();
    expect(rows("every")[0].querySelector(".common-name").textContent).toBe("<b>x</b> Ring");
  });
});

// ---- following the controls ----------------------------------------------------------------------------------------------------------------

describe("the section and the switches", () => {
  const by = () => ({ list: document.querySelector("#common-body ul"), text: $("#common-body").textContent, summary: SUMMARY() });

  it("is not redrawn when the role or the weapons change: the same elements, the same words", async () => {
    const { app } = mount();
    await settle(app);
    const before = by();
    const list = document.querySelector("#common-body ul");
    choose("#role-tank");
    await app.whenIdle();
    expect(document.querySelector("#common-body ul")).toBe(list);
    choose("#role-melee");
    await app.whenIdle();
    expect(document.querySelector("#common-body ul")).toBe(list);
    choose("#setup-2h");
    await app.whenIdle();
    expect($("#kit caption").textContent).toContain("Melee");
    expect(document.querySelector("#common-body ul")).toBe(list);
    expect(by().text).toBe(before.text);
    expect(SUMMARY()).toBe(before.summary);
  });

  it("is redrawn when the tier changes", async () => {
    const mixed = doc({ 0: trio({ 1: "veil" }), 4: trio({ 1: "veil", 2: "stud" }), 10: trio({ 2: "stud" }) });
    const { app } = mount({ custom: { "strict-own": mixed } });
    await settle(app);
    expect(names("every")).toEqual(["veil", "stud"]);
    const list = document.querySelector("#common-body ul");
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(names("every")).toEqual(["stud"]);
    expect(document.querySelector("#common-body ul")).not.toBe(list);
    expect(SUMMARY()).toBe("Get these first: 1 item every role wears");
  });

  it("is emptied while another shard is loading, so that a list of the old one is never shown, and drawn from the new one when it comes", async () => {
    let release;
    const gate = new Promise((go) => (release = go));
    const group = doc({ 4: trio({ 5: "veil" }) }, {}, { buffs: "group" });
    const { app } = mount({ gates: { "strict-group": gate }, custom: { "strict-group": group } });
    await settle(app);
    expect(rows("every").length).toBeGreaterThan(0);
    $("#common").open = true;
    choose("#buffs-group");
    await Promise.resolve();
    // the new shard is on its way: nothing of the old one is left, and the summary is the static one
    expect($("#common-body").childNodes).toHaveLength(0);
    expect(SUMMARY()).toBe(STATIC_SUMMARY);
    expect($("#common").open).toBe(true); // (the visitor's own choice is not undone)
    release();
    await app.whenIdle();
    expect(names("every")).toEqual(["veil"]);
    expect(SUMMARY()).toBe("Get these first: 1 item every role wears");
  });

  it("does not empty a section that is hidden, nor show it, while another shard is loading", async () => {
    let release;
    const gate = new Promise((go) => (release = go));
    const none = doc({ 4: { balanced: { 0: "a" }, tank: { 0: "b" }, melee: { 0: "c" } } });
    const { app } = mount({ custom: { "strict-own": none }, gates: { "strict-group": gate } });
    await settle(app);
    expect($("#common").hidden).toBe(true);
    choose("#buffs-group");
    await Promise.resolve();
    expect($("#common").hidden).toBe(true);
    release();
    await app.whenIdle();
    expect($("#common").hidden).toBe(false); // (the group shard is the fixture's, which has things in common)
  });

  it("a shard that fails to load when the section is opened closes it again with its static summary, says nothing of it, and opening it once more tries again", async () => {
    const offline = ["strict-own"];
    const { app, calls } = mount({ offline });
    await settle(app);
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
    expect(SUMMARY()).toBe(STATIC_SUMMARY);
    expect($("#common").hidden).toBe(false);
    expect($("#common").open).toBe(false);
    expect($("#common-body").textContent).toBe("");
    expect($("#status").textContent.trim()).toBe(""); // (the page's own message is for a view the visitor asked for)
    expect($("#common").textContent).not.toMatch(/couldn.t|error|failed/i);
    offline.length = 0; // the network is back
    await settle(app);
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json", "/data/pal-mnk-ber/strict-own.json"]);
    expect($("#common").open).toBe(true);
    expect(rows("every").length).toBeGreaterThan(0);
  });

  it("a view that fails to load after another was drawn leaves the section emptied and closed, with no error text of its own", async () => {
    const { app } = mount({ offline: ["strict-group"] });
    await settle(app);
    expect(rows("every").length).toBeGreaterThan(0);
    choose("#buffs-group");
    await app.whenIdle();
    expect($("#status").textContent).toMatch(/couldn.t load this view/i); // (the page's own, about the view)
    expect(SUMMARY()).toBe(STATIC_SUMMARY);
    expect($("#common-body").childNodes).toHaveLength(0);
    expect($("#common").open).toBe(false);
    expect($("#common").textContent).not.toMatch(/couldn.t|error|failed/i);
    // the view that is still shown has its shard: opening the section shows that view's lists
    await settle(app);
    expect(rows("every").length).toBeGreaterThan(0);
  });

  it("is not changed by the answer of the optimizer or by a kit the visitor made: it describes the site's own kits", async () => {
    const { app } = mount();
    await settle(app);
    const before = [SUMMARY(), $("#common-body").textContent];
    const list = document.querySelector("#common-body ul");
    const kit = Array.from({ length: 22 }, (_, place) => ({ key: `w9000${place}`, name: `Solved ${place}`, arrival: 4, source: "Solved", deity: [] }));
    expect(app.drawSolved({ items: kit, tier: 4, hasteAssumed: 0, value: 100, kind: "buffs" })).toBe(true);
    expect([SUMMARY(), $("#common-body").textContent]).toEqual(before);
    expect(document.querySelector("#common-body ul")).toBe(list);
  });

  it("holds no controls: the lists and the line under the summary have no button, field or stop of their own for the keyboard (the keyboard open is in the e2e spec)", async () => {
    const { app } = mount();
    await settle(app);
    expect($("#common-body").querySelectorAll("button, input, select, textarea, [tabindex]")).toHaveLength(0);
    expect([...$("#common-body").querySelectorAll("a")].every((link) => link.getAttribute("href").startsWith("/item/"))).toBe(true); // (the only things in it that take the focus are the links to the items)
  });
});

// ---- a view that is loading shows no list of another shard, whether or not that shard was asked for before -----------------------------------------------------

const tick = () => new Promise((go) => setTimeout(go, 0));
const status = () => $("#status").textContent.trim();

describe("while a shard is loading", () => {
  it("no list of the old one is shown, though the new one was asked for before and has not come: own drawn, group held back, group, own, group", async () => {
    let release;
    const gate = new Promise((go) => (release = go));
    const group = doc({ 4: trio({ 5: "veil" }) }, {}, { buffs: "group" });
    const { app, calls } = mount({ gates: { "strict-group": gate }, custom: { "strict-group": group } });
    await settle(app);
    expect(rows("every").length).toBeGreaterThan(0);
    choose("#buffs-group"); // the group shard is asked for, and held back
    await tick();
    expect($("#common-body").childNodes).toHaveLength(0);
    choose("#buffs-own"); // the own shard is settled: its list is drawn again at once (the page is not idle: the group view is still being waited for)
    await tick();
    expect(rows("every").length).toBeGreaterThan(0);
    expect(status()).toBe("");
    choose("#buffs-group"); // the group shard is asked for again: it is still on its way, and what is on the page is the own list
    await tick();
    expect($('input[name="buffs"]:checked').value).toBe("group");
    expect($("#common-body").childNodes, "no list of the own shard under the controls of the group").toHaveLength(0);
    expect(SUMMARY()).toBe(STATIC_SUMMARY);
    expect(status()).toBe("Loading this view…");
    expect(calls.filter((call) => call.includes("group"))).toHaveLength(1); // (one request for it, whichever way it was asked for)
    release();
    await app.whenIdle();
    expect(names("every")).toEqual(["veil"]);
    expect(status()).toBe("");
  });

  it("a change of view made while the section's own load is pending says that the view is loading, and the section holds nothing of that load", async () => {
    let release;
    const gate = new Promise((go) => (release = go));
    const { app } = mount({ gates: { "strict-own": gate } });
    openSection(); // the load of the default view's shard for the section is held back
    await tick();
    change($("#sw-tier"), "10");
    await tick();
    expect(status()).toBe("Loading this view…");
    expect($("#common-body").childNodes).toHaveLength(0);
    release();
    await app.whenIdle();
    expect(status()).toBe("");
    expect(names("every")).toEqual(wanted("strict-own", "OGR", 10).every);
    expect($("#kit caption").textContent).toContain("+10");
  });
});

// ---- the load that opening the section starts -----------------------------------------------------------------------------------------------------------------

describe("the load that opening the section starts", () => {
  it("says 'Loading…' in the open section while it is pending, and nothing of it once the section is drawn", async () => {
    let release;
    const gate = new Promise((go) => (release = go));
    const { app } = mount({ gates: { "strict-own": gate } });
    openSection();
    await tick();
    expect($("#common-body").textContent).toBe("Loading…");
    expect($("#common-body").querySelector("ul, h3")).toBeNull();
    expect($("#common").open).toBe(true);
    release();
    await app.whenIdle();
    expect($("#common-body").textContent).not.toContain("Loading");
    expect(rows("every").length).toBeGreaterThan(0);
  });

  it("says nothing of it when the shard does not come: the section is closed again with its summary, and no error text", async () => {
    let release;
    const gate = new Promise((go) => (release = go));
    const { app } = mount({ gates: { "strict-own": gate }, offline: ["strict-own"] });
    openSection();
    await tick();
    expect($("#common-body").textContent).toBe("Loading…");
    release();
    await app.whenIdle();
    expect($("#common-body").childNodes).toHaveLength(0);
    expect($("#common").open).toBe(false);
    expect(SUMMARY()).toBe(STATIC_SUMMARY);
    expect($("#common").textContent).not.toMatch(/loading|couldn.t|error|failed/i);
    expect(status()).toBe("");
  });

  it("closed and opened again after it was drawn, it still says what it said: no 'Loading…' over it, and no new request", async () => {
    const { app, calls } = mount();
    await settle(app);
    const before = [SUMMARY(), $("#common-body").textContent];
    const list = document.querySelector("#common-body ul");
    $("#common").open = false;
    $("#common").dispatchEvent(new Event("toggle"));
    await settle(app); // opened again
    expect([SUMMARY(), $("#common-body").textContent]).toEqual(before);
    expect(document.querySelector("#common-body ul")).toBe(list);
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
    // and the same after a change of view drew it
    change($("#sw-tier"), "10");
    await app.whenIdle();
    const drawn = $("#common-body").textContent;
    $("#common").open = false;
    $("#common").dispatchEvent(new Event("toggle"));
    await settle(app);
    expect($("#common-body").textContent).toBe(drawn);
    expect($("#common-body").textContent).not.toContain("Loading");
  });

  it("is started for a section that was opened before the page code ran", async () => {
    const early = PAGE.replace('<details class="expander" id="common">', '<details class="expander" id="common" open>');
    expect(early).not.toBe(PAGE);
    const { app, calls } = mount({ html: early });
    await app.whenIdle();
    expect(calls).toEqual(["/data/pal-mnk-ber/strict-own.json"]);
    expect($("#common").open).toBe(true);
    expect(rows("every").length).toBeGreaterThan(0);
    expect(SUMMARY()).toContain("every role wears");
  });

  it("a late failure of it does not close a section that has been drawn from another shard since", async () => {
    let release;
    const gate = new Promise((go) => (release = go));
    const group = doc({ 4: trio({ 1: "veil", 2: "stud" }) }, {}, { buffs: "group" });
    const { app } = mount({ gates: { "strict-own": gate }, offline: ["strict-own"], custom: { "strict-group": group } });
    openSection(); // the load of the baked view's shard stalls ...
    await tick();
    choose("#buffs-group"); // ... the visitor changes the buffs, and the section is drawn correctly from the new shard ...
    await tick();
    expect(names("every")).toEqual(["veil", "stud"]);
    release(); // ... and the old load then fails
    await app.whenIdle();
    await tick();
    expect($("#common").open, "the good section was not shut").toBe(true);
    expect(names("every")).toEqual(["veil", "stud"]);
    expect(SUMMARY()).toBe("Get these first: 2 items every role wears");
  });
});
