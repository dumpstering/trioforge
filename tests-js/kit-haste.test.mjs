// @vitest-environment jsdom
//
// The worn haste of a row of Wear this (race-explain): a chip beside the name ("Haste 19%") for an item that has worn haste, without opening Stats. The page code run in jsdom against the baked
// page and the data files of the contract fixture. The chip of a row the code paints is made from the words the row's stats say ("Haste +19%": the generator's own text, which
// pipeline/tests/test_site_kit_haste.py holds to the model); a row of the baked page has the chip the generator wrote.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { hasteChip } from "../pipeline/trioforge/site/static/format.js";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract");
const text = (name) => readFileSync(resolve(CONTRACT, name), "utf8");
const dataFile = (name) => JSON.parse(text(`data/${name}.json`));

/** The page code started on the baked page; `prepare` may change the baked page first (the page of a build whose default kit has a worn haste, say). */
function mount(prepare = () => {}) {
  document.body.innerHTML = text("trio-main.html");
  prepare();
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  const fetch = async (url) => {
    const name = String(url).replace("/data/pal-mnk-ber/", "").replace(".json", "");
    return { ok: true, status: 200, json: async () => structuredClone(dataFile(name)) };
  };
  return initTrio({ document, window, fetch });
}

const $ = (selector) => document.querySelector(selector);
const rows = () => [...document.querySelectorAll("#kit-body tr")];
const chip = (row) => row.querySelector(".kit-haste");
/** What a reader of the row sees as its chip: the text of a chip that is shown, else nothing (a row with no chip, or a hidden one, has none). */
const seen = (row) => (chip(row) === null || chip(row).hidden ? "" : chip(row).textContent);
const chips = () => rows().map(seen);
const HASTE_SLOT = 3; // the second ear: the fixture's Gold Hoop of Haste, in its melee views
const choose = (selector) => {
  const radio = $(selector);
  radio.checked = true;
  radio.dispatchEvent(new Event("change", { bubbles: true }));
};
const change = (element, value) => {
  element.value = value;
  element.dispatchEvent(new Event("change", { bubbles: true }));
};

/** The haste the shard file says for the item of a place in a view, from its stats text (what the page was given). */
function shardHaste(name, race, role, tier, setup) {
  const doc = dataFile(name);
  const row = doc.rows.find((r) => r[0] === race && r[1] === role && r[2] === tier && r[3] === setup);
  const at = doc.stat_tiers.indexOf(tier);
  return doc.kits[row[4]].map((i) => {
    const line = i < 0 ? "" : doc.items[i][7][at];
    const found = /Haste \+(\d+)%/.exec(line);
    return found ? `Haste ${found[1]}%` : "";
  });
}

describe("the words of the chip", () => {
  it("is Haste and the figure, from the row's stats text, whatever else the row says", () => {
    expect(hasteChip("AGI +5, Haste +19%, Weight 0.1")).toBe("Haste 19%");
    expect(hasteChip("Haste +15%")).toBe("Haste 15%");
    expect(hasteChip("STA +10, Haste +100%")).toBe("Haste 100%");
  });

  it("is nothing for an item with no haste, for no stats and for text that is no stats", () => {
    expect(hasteChip("AC +42, STA +18, HP +30, Weight 1.2")).toBe("");
    expect(hasteChip("No stats")).toBe("");
    expect(hasteChip("")).toBe("");
    expect(hasteChip(null)).toBe("");
    expect(hasteChip(undefined)).toBe("");
    expect(hasteChip("Its stats at this tier are on the page of the item.")).toBe("");
    expect(hasteChip("Its stats are not on this page.")).toBe("");
  });

  it("does not take a figure for haste that is another stat's, or a loss of haste", () => {
    expect(hasteChip("Mana regen +4, End regen +2")).toBe("");
    expect(hasteChip("Haste −3%")).toBe("");
    expect(hasteChip("Hasted +9%")).toBe("");
    expect(hasteChip("Corruption resist +9, Haste")).toBe("");
  });

  it("agrees with the generator on every stats text of the contract shards", () => {
    for (const name of ["strict-own", "strict-group", "wiki-own", "wiki-group"]) {
      const doc = dataFile(name);
      const seen = new Set();
      for (const item of doc.items) {
        for (const line of item[7]) {
          const want = /(?:^|, )Haste \+(\d+)%(?:,|$)/.exec(line);
          expect(hasteChip(line)).toBe(want ? `Haste ${want[1]}%` : "");
          if (want) seen.add(hasteChip(line));
        }
      }
      expect([...seen].sort()).toEqual(["Haste 15%", "Haste 19%", "Haste 25%"]);
    }
  });
});

describe("the baked page", () => {
  it("has no chip in a row whose item has no worn haste: the default kit of the fixture has none", () => {
    document.body.innerHTML = text("trio-main.html");
    expect(rows()).toHaveLength(22);
    expect(document.querySelectorAll(".kit-haste")).toHaveLength(0);
    expect(chips()).toEqual(new Array(22).fill(""));
  });

  it("keeps the chip the generator wrote in a row that has one, when the code starts and when the default view comes back", async () => {
    // the page of a build whose default kit wears a worn haste in the second ear: the chip and the stats say the same figure, as the generator writes them (its chip is before the panel)
    const wear = () => {
      const row = rows()[HASTE_SLOT];
      row.querySelector('[data-f="stats"]').textContent = "AGI +5, Haste +19%, Weight 0.1";
      const made = document.createElement("span");
      made.className = "kit-haste";
      made.textContent = "Haste 19%";
      row.querySelector('[data-f="more"]').before(made);
    };
    const app = mount(wear);
    expect(chips()).toEqual(rows().map((row, index) => (index === HASTE_SLOT ? "Haste 19%" : "")));
    change($("#sw-tier"), "10");
    await app.whenIdle();
    expect(chips().filter(Boolean)).toEqual([]); // (the balanced view at +10 has no worn haste in the fixture)
    change($("#sw-tier"), "4");
    await app.whenIdle();
    expect(chips()).toEqual(rows().map((row, index) => (index === HASTE_SLOT ? "Haste 19%" : ""))); // repainted from the baked stats, which say the haste
    expect(document.querySelectorAll(".kit-haste")).toHaveLength(1); // (the one chip, not a second made beside it)
  });
});

describe("a view the code paints", () => {
  it("shows the chip of the item that has worn haste at the tier of the view, made where the page puts it, and no other", async () => {
    const app = mount();
    choose("#role-melee");
    await app.whenIdle();
    const want = shardHaste("strict-own", "OGR", "melee", 4, "2h");
    expect(want[HASTE_SLOT]).toBe("Haste 19%");
    expect(chips()).toEqual(want);
    const made = chip(rows()[HASTE_SLOT]);
    expect(made.hidden).toBe(false);
    expect(made.className).toBe("kit-haste");
    expect(made.nextElementSibling.getAttribute("data-f")).toBe("more"); // (before the panel, as the generator puts it)
    expect(made.previousElementSibling.getAttribute("data-f")).toBe("deity");
    expect(document.querySelectorAll(".kit-haste")).toHaveLength(1); // (no row without worn haste is given a chip)
  });

  it("follows the tier: the same item says 15 at +0, 19 at +4 and 25 at +10", async () => {
    const app = mount();
    choose("#role-melee");
    await app.whenIdle();
    for (const [tier, figure] of [["0", 15], ["10", 25], ["4", 19]]) {
      change($("#sw-tier"), tier);
      await app.whenIdle();
      expect(chip(rows()[HASTE_SLOT]).textContent).toBe(`Haste ${figure}%`);
      expect(chips().filter(Boolean)).toEqual([`Haste ${figure}%`]);
      expect(document.querySelectorAll(".kit-haste")).toHaveLength(1);
    }
  });

  it("is gone again when the view has no worn haste: hidden, and nothing left in it for a reader of the text", async () => {
    const app = mount();
    choose("#role-melee");
    await app.whenIdle();
    expect(chips().filter(Boolean)).toHaveLength(1);
    choose("#role-balanced");
    await app.whenIdle();
    expect(chips()).toEqual(new Array(22).fill(""));
    for (const node of document.querySelectorAll(".kit-haste")) {
      expect(node.hidden).toBe(true);
      expect(node.textContent).toBe("");
    }
  });

  it("is made for an item of the optimizer's answer from the stats the loaded shards know, and for none whose stats the page does not have", async () => {
    const app = mount();
    choose("#role-melee");
    await app.whenIdle();
    const doc = dataFile("strict-own");
    const hoop = doc.items.findIndex((item) => item[1] === "Gold Hoop of Haste");
    const [key, name, rule, arrival, source] = doc.items[hoop];
    const items = new Array(22).fill(null);
    items[0] = { key, name, rule, arrival, source, evidence: "strict", deity: [] };
    items[1] = { key: "w4242", name: "Stranger", rule: "drop", arrival: 4, source: "x", evidence: "strict", deity: [] };
    expect(app.drawSolved({ items, tier: 4, hasteAssumed: 0, value: 1, kind: "buffs" })).toBe(true);
    expect(seen(rows()[0])).toBe("Haste 19%");
    expect(seen(rows()[1])).toBe(""); // (its stats are not on the page)
    expect(seen(rows()[2])).toBe(""); // (a place left empty)
    expect(chips().filter(Boolean)).toEqual(["Haste 19%"]);
  });
});

describe("a page without the stats of its rows", () => {
  it("has no panel to put the stats in and the code makes no chip", async () => {
    const app = mount(() => document.querySelectorAll('[data-f="more"]').forEach((node) => node.remove()));
    choose("#role-melee");
    await app.whenIdle();
    expect(document.querySelectorAll(".kit-haste")).toHaveLength(0);
  });
});
