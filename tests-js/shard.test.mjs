// The reader of the compact data files (pipeline/trioforge/site/static/shard.js): what it asks of a file before the page draws from it.
//
// A file that is not what the generator writes must be refused when it is read, with an Error of the reader's own, so that the page says
// "couldn't load this view" (its fetch is wrapped for that). A file that is let through and then fails when the page draws from it
// (a TypeError from an index that points nowhere, say) leaves the page saying "Loading this view…" for good. Every name here is invented.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { LISTED_FIRST, SETUP_ORDER, parseRunnerups, parseShard } from "../pipeline/trioforge/site/static/shard.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = resolve(HERE, "../fixtures/site/contract/data");
const fixture = (name) => JSON.parse(readFileSync(resolve(CONTRACT, `${name}.json`), "utf8"));

/** What reading the document does: the error it raises, or null. */
function refusal(document) {
  try {
    parseShard(document);
  } catch (error) {
    return error;
  }
  return null;
}

describe("a shard as the generator writes it", () => {
  it("is read, and answers for every scenario it holds", () => {
    const doc = fixture("strict-own");
    const shard = parseShard(doc);
    expect(shard.rows.size).toBe(doc.rows.length);
    const [race, role, tier, setup, kit, value, gain, totalsIndex, haste] = doc.rows[0];
    const scenario = shard.scenario(race, role, tier, setup);
    expect(scenario).toMatchObject({ race, role, tier, setup, value, gain, hasteAssumed: haste });
    expect(scenario.kit).toHaveLength(22);
    expect(Object.keys(scenario.totals)).toHaveLength(14);
    expect(scenario.totals.ac).toBe(doc.totals[totalsIndex][0]);
    expect(scenario.kit.map((item) => (item ? item.name : null))).toEqual(doc.kits[kit].map((i) => (i < 0 ? null : doc.items[i][1])));
  });
});

describe("Shard.has: does the shard hold a row for this race, role and tier", () => {
  /** The fixture with only the rows of the cells named (each `[race, role, tier]`), every other row left out. */
  function cells(...wanted) {
    const doc = fixture("strict-own");
    doc.rows = doc.rows.filter((row) => wanted.some(([race, role, tier]) => row[0] === race && row[1] === role && row[2] === tier));
    return parseShard(doc);
  }

  it("is true for a cell with a row and false for a cell of known parts that has none", () => {
    const shard = cells(["OGR", "tank", 4], ["TRL", "melee", 10]);
    expect(shard.has("OGR", "tank", 4)).toBe(true);
    expect(shard.has("TRL", "melee", 10)).toBe(true);
    // every part is one the shard knows, and no row has them together
    expect([...shard.races].sort()).toEqual(["OGR", "TRL"]);
    expect([...shard.roles].sort()).toEqual(["melee", "tank"]);
    expect([...shard.tiers].sort((a, b) => a - b)).toEqual([4, 10]);
    expect(shard.has("OGR", "tank", 10)).toBe(false);
    expect(shard.has("OGR", "tank", 10)).toBe(false);
    expect(shard.has("TRL", "tank", 4)).toBe(false);
    expect(shard.has("TRL", "tank", 4)).toBe(false);
  });

  it("is true when any setup has the row, and false for a part the shard has not", () => {
    const shard = cells(["OGR", "melee", 0]);
    expect(shard.setupsFor("melee").length).toBeGreaterThan(0);
    expect(shard.has("OGR", "melee", 0)).toBe(true);
    for (const [race, role, tier] of [["ELF", "melee", 0], ["OGR", "healer", 0], ["OGR", "melee", 99], ["OGR", "melee", "0"], ["OGR", "melee", undefined]]) {
      expect(shard.has(race, role, tier), `${race} ${role} ${tier}`).toBe(false);
    }
  });

  it("does not take the parts of one cell for the parts of another when they run together", () => {
    const doc = fixture("strict-own");
    doc.rows = doc.rows.filter((row) => row[0] === "OGR" && row[1] === "tank" && row[2] === 4);
    for (const row of doc.rows) {
      row[0] = "A|B";
      row[1] = "C";
    }
    const shard = parseShard(doc);
    expect(shard.has("A|B", "C", 4)).toBe(true);
    expect(shard.has("A", "B|C", 4)).toBe(false);
    expect(shard.has("A|B|C", "", 4)).toBe(false);
  });
});

describe("a file that is not a shard of this version is refused with an Error of the reader's own, not a TypeError", () => {
  /** A case changes a copy of the fixture in place (`edit`), or gives the document that replaces it. */
  const edit = (change) => (doc) => {
    change(doc);
    return doc;
  };
  const cases = {
    // the shape of the whole file
    "a document that is null": () => null,
    "another version": (d) => ({ ...d, v: 2 }),
    "rows that are not a list": (d) => ({ ...d, rows: {} }),
    "no rows": (d) => ({ ...d, rows: [] }),
    // the items
    "an item that is not a list": edit((d) => (d.items[3] = null)),
    "an item whose name is a number": edit((d) => (d.items[3][1] = 7)),
    // the kits
    "a kit that is not a list": edit((d) => (d.kits[2] = null)),
    "a kit of 21 places": edit((d) => d.kits[2].pop()),
    "a kit of 23 places": edit((d) => d.kits[2].push(-1)),
    "a kit whose place is a text": edit((d) => (d.kits[2][4] = "3")),
    "a kit whose place is a fraction": edit((d) => (d.kits[2][4] = 1.5)),
    "a kit whose place is null": edit((d) => (d.kits[2][4] = null)),
    "a kit whose place is below the mark for empty": edit((d) => (d.kits[2][4] = -2)),
    "a kit whose place is past the items": edit((d) => (d.kits[2][4] = d.items.length)),
    "a kit that no row names and whose places are past the items": edit((d) => d.kits.push(d.kits[0].map(() => d.items.length))),
    // the totals
    "a totals row that is not a list": edit((d) => (d.totals[1] = null)),
    "a totals row of 13 numbers": edit((d) => d.totals[1].pop()),
    "a totals row of 15 numbers": edit((d) => d.totals[1].push(0)),
    "a totals row that is empty": edit((d) => (d.totals[1] = [])),
    "a totals row with a text in it": edit((d) => (d.totals[1][3] = "3050")),
    "a totals row with a null in it": edit((d) => (d.totals[1][3] = null)),
    "a totals row with a number that is not finite": edit((d) => (d.totals[1][3] = Infinity)),
    "a totals row that no row names and is short": edit((d) => d.totals.push([1, 2, 3])),
    // the indices of a row
    "a kit index that is a text": edit((d) => (d.rows[5][4] = String(d.rows[5][4]))),
    "a kit index that is the name of a property": edit((d) => (d.rows[5][4] = "length")),
    "a kit index that is a fraction": edit((d) => (d.rows[5][4] = 0.5)),
    "a kit index that is negative": edit((d) => (d.rows[5][4] = -1)),
    "a kit index past the kits": edit((d) => (d.rows[5][4] = d.kits.length)),
    "a kit index that is null": edit((d) => (d.rows[5][4] = null)),
    "a kit index that is a list": edit((d) => (d.rows[5][4] = [0])),
    "a kit index that is true": edit((d) => (d.rows[5][4] = true)),
    "a totals index that is a text": edit((d) => (d.rows[5][7] = String(d.rows[5][7]))),
    "a totals index that is the name of a property": edit((d) => (d.rows[5][7] = "length")),
    "a totals index that is a fraction": edit((d) => (d.rows[5][7] = 1.5)),
    "a totals index that is negative": edit((d) => (d.rows[5][7] = -1)),
    "a totals index past the totals": edit((d) => (d.rows[5][7] = d.totals.length)),
    "a totals index that is null": edit((d) => (d.rows[5][7] = null)),
    "a totals index that is a list": edit((d) => (d.rows[5][7] = [0])),
    // the rest of a row
    "a row that is null": edit((d) => (d.rows[5] = null)),
    "a row that is an object": edit((d) => (d.rows[5] = {})),
    "a row of 8 fields": edit((d) => d.rows[5].pop()),
    "a row of 10 fields": edit((d) => d.rows[5].push(0)),
    "a value that is a text": edit((d) => (d.rows[5][5] = "8859.75")),
    "a value that is null": edit((d) => (d.rows[5][5] = null)),
    "a gain that is a text": edit((d) => (d.rows[5][6] = "1")),
    "a haste that is a fraction": edit((d) => (d.rows[5][8] = 50.5)),
    "a race that is a number": edit((d) => (d.rows[5][0] = 7)),
    "a role that is null": edit((d) => (d.rows[5][1] = null)),
    "a tier that is a text": edit((d) => (d.rows[5][2] = "4")),
    "a tier that is a fraction": edit((d) => (d.rows[5][2] = 4.5)),
    "a setup that is an object": edit((d) => (d.rows[5][3] = {})),
  };

  for (const [label, damage] of Object.entries(cases)) {
    it(`refuses ${label}`, () => {
      const error = refusal(damage(fixture("strict-own")));
      expect(error, "the file is refused").toBeInstanceOf(Error);
      expect(error, `${error?.name}: ${error?.message}`).not.toBeInstanceOf(TypeError);
      expect(error.constructor).toBe(Error);
    });
  }

  it("still reads the unchanged files, so that each case above is the one change that is refused", () => {
    for (const name of ["strict-own", "strict-group", "wiki-own", "wiki-group"]) expect(refusal(fixture(name)), name).toBeNull();
  });
});

// ---- the runner-ups of a role: one file with every tier of the run in it ------------------------------------------------------------------------------

const runnerups = (role) => JSON.parse(readFileSync(resolve(CONTRACT, "runnerups", `${role}.json`), "utf8"));

/** What reading the runner-up document does: the error it raises, or null. */
function runnerupRefusal(document) {
  try {
    parseRunnerups(document);
  } catch (error) {
    return error;
  }
  return null;
}

describe("a runner-up file as the generator writes it: the file of a role, a view for each race at each tier", () => {
  it("is read, and gives the swaps of a race at a tier of the file", () => {
    const doc = runnerups("tank");
    const file = parseRunnerups(doc);
    expect(file.role).toBe("tank");
    expect(file.tiers).toEqual([0, 4, 10]);
    expect(file.release).toBe(doc.release);
    expect(file.items).toHaveLength(doc.items.length);
    expect(file.items[0]).toMatchObject({ key: doc.items[0][0], name: doc.items[0][1] });
    for (const [tier, race, setup, slots] of doc.views) {
      const view = file.view(tier, race);
      expect(view, `${race} at +${tier}`).toEqual({ setup, slots });
      expect(view.slots).toHaveLength(22);
    }
    expect(new Set(doc.views.map(([tier]) => tier))).toEqual(new Set([0, 4, 10])); // every tier of the run has views in the file
  });

  it("gives the view of the tier asked for, and none for a tier or a race the file has not", () => {
    const doc = runnerups("tank");
    const file = parseRunnerups(doc);
    const at = (tier) => doc.views.find((v) => v[0] === tier && v[1] === "OGR");
    expect(file.view(0, "OGR").slots).toEqual(at(0)[3]);
    expect(file.view(10, "OGR").slots).toEqual(at(10)[3]);
    expect(file.view(0, "OGR").slots).not.toEqual(file.view(10, "OGR").slots); // the tiers are not mixed up
    for (const [tier, race] of [[7, "OGR"], [1, "OGR"], [4, "HUM"], [11, "OGR"], ["4", "OGR"], [4.5, "OGR"], [null, "OGR"], [undefined, "OGR"], [4, undefined]]) {
      expect(file.view(tier, race), `${race} at ${tier}`).toBeNull();
    }
  });

  it("does not take the tier and the race of one view for those of another when they run together", () => {
    const doc = runnerups("tank");
    doc.tiers = [1, 10];
    doc.views = [
      [1, "0|A", "dw", doc.views[0][3]],
      [10, "A", "dw", doc.views[1][3]],
    ];
    const file = parseRunnerups(doc);
    expect(file.view(1, "0|A").setup).toBe("dw");
    expect(file.view(10, "A")).not.toBeNull();
    expect(file.view(1, "A")).toBeNull();
    expect(file.view(10, "0|A")).toBeNull();
  });

  it("is refused, with an Error of the reader's own and not a TypeError, when it is not what the generator writes", () => {
    const edit = (change) => () => {
      const doc = runnerups("tank");
      change(doc);
      return doc;
    };
    const cases = {
      "a file of the earlier version, one for a role and a tier": edit((d) => (d.v = 1)),
      "a file of a version that is a text": edit((d) => (d.v = "2")),
      "a document that is not an object": () => null,
      "a document that is a list": () => [],
      "no items": edit((d) => delete d.items),
      "items that are not a list": edit((d) => (d.items = {})),
      "an item that is not a list": edit((d) => (d.items[1] = null)),
      "an item whose name is a number": edit((d) => (d.items[1][1] = 7)),
      "no views": edit((d) => delete d.views),
      "views that are not a list": edit((d) => (d.views = {})),
      "no tiers": edit((d) => delete d.tiers),
      "tiers that are not a list": edit((d) => (d.tiers = "0,4,10")),
      "a tier that is a text": edit((d) => (d.tiers[1] = "4")),
      "a tier that is a fraction": edit((d) => (d.tiers[1] = 4.5)),
      "a tier that is negative": edit((d) => (d.tiers[0] = -1)),
      "a tier that is null": edit((d) => (d.tiers[2] = null)),
      "a tier listed twice": edit((d) => d.tiers.push(4)),
      "a view of the earlier shape, [race, setup, slots]": edit((d) => (d.views[0] = d.views[0].slice(1))),
      "a view of five fields": edit((d) => d.views[0].push(0)),
      "a view that is null": edit((d) => (d.views[0] = null)),
      "a view of a tier the file does not list": edit((d) => (d.views[0][0] = 7)),
      "a view whose tier is a text": edit((d) => (d.views[0][0] = "0")),
      "a view whose race is a number": edit((d) => (d.views[0][1] = 7)),
      "a view whose setup is null": edit((d) => (d.views[0][2] = null)),
      "a view with no list of slots": edit((d) => (d.views[0][3] = null)),
      "a view of 21 slots": edit((d) => d.views[0][3].pop()),
      "a view of 23 slots": edit((d) => d.views[0][3].push([])),
      "a slot that is not a list": edit((d) => (d.views[0][3][4] = null)),
      "a swap that is not a pair": edit((d) => (d.views[0][3][0] = [[0]])),
      "a swap whose item is a text": edit((d) => (d.views[0][3][0] = [["0", -1]])),
      "a swap whose item is past the items": edit((d) => (d.views[0][3][0] = [[d.items.length, -1]])),
      "a swap whose item is negative": edit((d) => (d.views[0][3][0] = [[-1, -1]])),
      "a swap whose item is a fraction": edit((d) => (d.views[0][3][0] = [[0.5, -1]])),
      "a swap whose change is a text": edit((d) => (d.views[0][3][0] = [[0, "-1"]])),
      "a swap whose change is not finite": edit((d) => (d.views[0][3][0] = [[0, Infinity]])),
      "a race at a tier twice": edit((d) => d.views.push(d.views[0])),
    };
    for (const [label, damage] of Object.entries(cases)) {
      const error = runnerupRefusal(damage());
      expect(error, `${label}: the file is refused`).toBeInstanceOf(Error);
      expect(error, `${label}: ${error?.name}: ${error?.message}`).not.toBeInstanceOf(TypeError);
      expect(error.constructor, label).toBe(Error);
    }
  });

  it("still reads the unchanged files, so that each case above is the one change that is refused", () => {
    for (const role of ["tank", "melee"]) expect(runnerupRefusal(runnerups(role)), role).toBeNull();
  });
});

describe("the order of the setups of a build", () => {
  /** The fixture's Tank rows of one cell, copied as the rows of a Caster that plays the stat stick and the shield setup (and the Tank's others). */
  function withCaster() {
    const doc = fixture("strict-own");
    const tank = doc.rows.filter((row) => row[0] === "OGR" && row[1] === "tank" && row[2] === 4);
    expect(tank.length).toBeGreaterThan(1);
    doc.rows = [...doc.rows, ...tank.filter((row) => row[3] === "1h-shield").map((row) => ["OGR", "caster", 4, "1h-shield", ...row.slice(4)]), ["OGR", "caster", 4, "stick", ...tank[0].slice(4)]];
    return parseShard(doc);
  }

  it("is the order of the page, with the setup a build lists first in front: the Caster's stat stick, which wins a tie", () => {
    const shard = withCaster();
    expect(shard.setupsFor("caster")).toEqual(["stick", "1h-shield"]);
    expect(shard.setupsFor("tank")).toEqual(SETUP_ORDER.filter((setup) => shard.setupsFor("tank").includes(setup))); // (every other build: the order of the page)
  });

  it("takes the first of two setups of equal value as the best: for the Caster that is the stick", () => {
    const shard = withCaster();
    const stick = shard.scenario("OGR", "caster", 4, "stick");
    const shield = shard.scenario("OGR", "caster", 4, "1h-shield");
    expect(stick.value === shield.value ? shard.bestSetup("OGR", "caster", 4) : "unequal").toBe(stick.value === shield.value ? "stick" : "unequal");
  });

  it("has the builds that list a setup first that model/weapons.py has (a test of the pipeline holds the two lists equal)", () => {
    expect(LISTED_FIRST).toEqual({ caster: "stick" });
  });
});
