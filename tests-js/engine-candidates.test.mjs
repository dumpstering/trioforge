import { describe, expect, it } from "vitest";
import { candidatesFor } from "../pipeline/trioforge/site/static/engine/candidates.js";
import { atTier, readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { TierError } from "../pipeline/trioforge/site/static/engine/tiers.js";
import { BUNDLE_BYTES, ITEMS_BYTES } from "./engine-site-fixture.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

// The candidates of a scenario, made from the tier mode and not carried by the request (candidates.js): the records of the item table whose evidence level is in
// the scenario's set ("strict": strict only; "wiki": strict and wiki; the rule of the precompute's candidates, deity-locked items included), that are not marked
// not-for-bis (a temporary item, or one a quest takes on hand-in: select_items leaves them out) and that the profile can use (a class of the trio, a race and a
// deity it admits: the rule of the model builder and of upgrade.py's usability check, path.js usableBy), each at the
// tier its mode gives it, through atTier with the bundle's rules. A hidden record is never a candidate, and a key has one candidate. Checked on the records of
// the site fixture (its items are invented), by hand.

const TABLE = readItemTable(JSON.parse(ITEMS_BYTES.toString("utf8")));
const BUNDLE = readBundle(JSON.parse(BUNDLE_BYTES.toString("utf8")));
const profileOf = (over = {}) => assembleProfile(BUNDLE, { race: "OGR", role: "balanced", buffs: "own", evidence: "wiki", ...over });
const READY4 = { mode: "ready4" };
const make = (over = {}, { evidence = "wiki", tierMode = READY4, records = TABLE.records } = {}) => candidatesFor(records, BUNDLE, profileOf({ evidence, ...over }), { evidence, tierMode });
const keysOf = (list) => list.map((item) => item.key);
const tiersOf = (list) => Object.fromEntries(list.map((item) => [item.key, item.tier]));

describe("which records are candidates", () => {
  it("takes the strict records and no other for the strict evidence level, and the strict and the wiki records for the wiki level", () => {
    const strict = make({}, { evidence: "strict" });
    const wiki = make({}, { evidence: "wiki" });
    const levelOf = (item) => TABLE.records.get(item.key).evidence.level;
    expect(new Set(strict.map(levelOf))).toEqual(new Set(["strict"]));
    expect(new Set(wiki.map(levelOf))).toEqual(new Set(["strict", "wiki"]));
    expect(keysOf(wiki)).toEqual(expect.arrayContaining(keysOf(strict)));
    expect(keysOf(wiki)).toContain("w90003"); // a wiki record: in the wiki set only
    expect(keysOf(strict)).not.toContain("w90003");
  });

  it("never takes a hidden record (an item that only a player may own), whatever the level", () => {
    expect(TABLE.records.get("w90041").owned_only).toBe(true);
    for (const evidence of ["strict", "wiki"]) expect(keysOf(make({}, { evidence }))).not.toContain("w90041");
    // and not a record that says so while it holds another level (a table the reader would refuse, but this function does not rely on the reader)
    const records = new Map(TABLE.records);
    records.set("w90001", { ...TABLE.records.get("w90001"), owned_only: true });
    expect(keysOf(make({}, { evidence: "strict", records }))).not.toContain("w90001");
  });

  it("takes what the profile can use: an item for a class that is not in the trio is left out, and so is one for another race", () => {
    expect(TABLE.records.get("w90040").classes).toEqual(["WIZ"]);
    expect(keysOf(make())).not.toContain("w90040");
    expect(TABLE.records.get("w90033").races).toEqual(["OGR", "TRL"]);
    expect(keysOf(make({ race: "OGR" }))).toContain("w90033");
    expect(keysOf(make({ race: "TRL" }))).toContain("w90033");
    expect(keysOf(make({ race: "HUM" }))).not.toContain("w90033");
  });

  it("keeps a deity-locked item for the deity it names and not for another, or for none", () => {
    expect(TABLE.records.get("w90004").deity).toEqual(["The Tribunal"]);
    expect(TABLE.records.get("w90046").deity).toEqual(["The Tribunal", "Rodcet Nife"]);
    const wiki = (deity) => keysOf(make(deity === undefined ? {} : { deity }));
    expect(wiki()).not.toContain("w90004");
    expect(wiki()).not.toContain("w90046");
    expect(wiki("The Tribunal")).toEqual(expect.arrayContaining(["w90004", "w90046"]));
    expect(wiki("Rodcet Nife")).toContain("w90046");
    expect(wiki("Rodcet Nife")).not.toContain("w90004");
    expect(wiki("Bertoxxulous")).not.toContain("w90004");
    // a strict set has no such item here, whatever the deity
    expect(keysOf(make({ deity: "The Tribunal" }, { evidence: "strict" }))).not.toContain("w90004");
  });

  it("counts, for the fixture: every strict record the trio and the race can use, and the wiki ones the deity admits", () => {
    expect(TABLE.count).toBe(48);
    expect(make({}, { evidence: "strict" })).toHaveLength(43); // 44 strict, less the cap for wizards
    expect(make({ race: "HUM" }, { evidence: "strict" })).toHaveLength(42); // and the sabatons for ogres and trolls
    expect(make()).toHaveLength(44); // the wiki crown
    expect(make({ deity: "The Tribunal" })).toHaveLength(46); // and the two items of the Tribunal
    expect(make({ deity: "Rodcet Nife" })).toHaveLength(45);
  });

  it("has one candidate for a key, each an item as atTier gives it", () => {
    const list = make({ deity: "The Tribunal" });
    expect(new Set(keysOf(list)).size).toBe(list.length);
    for (const item of list) expect(item).toEqual(atTier(TABLE.records.get(item.key), item.tier, BUNDLE));
  });
});

describe("a record that is not for best in slot", () => {
  // The precompute drops such a record before any list of candidates is made (select_items in precompute/grid.py: a temporary item, or one a quest takes on hand-in,
  // whatever its level); the item table writes the codes of a record's reasons in evidence.codes. Invented records: the site fixture's own, with the code put on.
  const marked = (key, codes = ["not-for-bis"]) => {
    const record = TABLE.records.get(key);
    return [key, { ...record, evidence: { ...record.evidence, codes } }];
  };
  const tableWith = (...entries) => new Map([...TABLE.records, ...entries]); // (a key given again keeps its place in the table)
  const MODES = [READY4, ...[0, 1, 2, 3, 4].map((D) => ({ mode: "arrives", D })), ...[0, 4, 10].map((N) => ({ mode: "fixed", N }))];

  it("is nothing in the site fixture that the counts rest on: no record of it carries the code", () => {
    expect([...TABLE.records.values()].filter((record) => (record.evidence.codes ?? []).includes("not-for-bis"))).toEqual([]);
  });

  it("is never a candidate, in any tier mode: a strict record at either level, and a wiki record at the wiki level; the same record without the code is", () => {
    expect(TABLE.records.get("w90001").evidence.level).toBe("strict");
    expect(TABLE.records.get("w90003").evidence.level).toBe("wiki");
    const records = tableWith(marked("w90001"), marked("w90003"));
    for (const tierMode of MODES) {
      for (const evidence of ["strict", "wiki"]) {
        const label = `${evidence}, ${JSON.stringify(tierMode)}`;
        expect(keysOf(make({}, { evidence, tierMode })), `${label}: without the code`).toContain("w90001");
        expect(keysOf(make({}, { evidence, tierMode, records })), `${label}: with the code`).not.toContain("w90001");
      }
      expect(keysOf(make({}, { tierMode })), `${JSON.stringify(tierMode)}: without the code`).toContain("w90003");
      expect(keysOf(make({}, { tierMode, records })), `${JSON.stringify(tierMode)}: with the code`).not.toContain("w90003");
    }
  });

  it("takes out nothing else: every other record is still a candidate, with the same item", () => {
    const records = tableWith(marked("w90001"), marked("w90003"));
    const without = make({}, { records });
    const all = make();
    expect(keysOf(without)).toEqual(keysOf(all).filter((key) => key !== "w90001" && key !== "w90003"));
    for (const item of without) expect(item).toEqual(all.find((other) => other.key === item.key));
  });

  it("is dropped when it is deity-locked too: the code is read before the deity", () => {
    expect(TABLE.records.get("w90004").deity).toEqual(["The Tribunal"]);
    expect(keysOf(make({ deity: "The Tribunal" }))).toContain("w90004");
    expect(keysOf(make({ deity: "The Tribunal" }, { records: tableWith(marked("w90004")) }))).not.toContain("w90004");
  });

  it("is a record that has exactly the code: another code, a code that only looks like it and an empty list are not it", () => {
    const records = tableWith(marked("w90001", ["not-for-default-kits", "wiki-marked-revamped"]), marked("w90002", []), marked("w90006", ["not-for-bis-later", "NOT-FOR-BIS"]));
    const list = keysOf(make({}, { records }));
    expect(list).toEqual(expect.arrayContaining(["w90001", "w90002", "w90006"]));
    // and the code among others is the code
    expect(keysOf(make({}, { records: tableWith(marked("w90001", ["removed-by-patch", "not-for-bis"])) }))).not.toContain("w90001");
  });

  it("is dropped before the tier mode is read, so that a bad mode is still the error it was", () => {
    expect(() => make({}, { tierMode: { mode: "fixed", N: 11 }, records: tableWith(marked("w90001")) })).toThrow(TierError);
  });
});

describe("the tier of a candidate", () => {
  const record = (key) => TABLE.records.get(key);

  it("is +4 for every candidate in the mode ready4", () => {
    const list = make();
    expect(new Set(list.map((item) => item.tier))).toEqual(new Set([4]));
  });

  it("is the tier an item arrives at in the mode arrives: +D for a drop, +0 for the rest, D from 0 to 4", () => {
    expect(record("w90001").tier_rule).toBe("drop");
    expect(record("w90002").tier_rule).toBe("fixed0");
    for (const D of [0, 1, 2, 3, 4]) {
      const tiers = tiersOf(make({}, { tierMode: { mode: "arrives", D } }));
      expect(tiers.w90001, `a drop, D=${D}`).toBe(D);
      expect(tiers.w90002, `a crafted item, D=${D}`).toBe(0);
    }
    const all = make({}, { tierMode: { mode: "arrives", D: 0 } });
    expect(new Set(all.map((item) => item.tier))).toEqual(new Set([0])); // arrives at +0: every candidate is at +0
    for (const item of all) expect(item).toEqual(atTier(record(item.key), 0, BUNDLE));
  });

  it("is +N for every candidate in the mode fixed, N from 0 to 10", () => {
    for (const N of [0, 4, 7, 10]) {
      const list = make({}, { tierMode: { mode: "fixed", N } });
      expect(new Set(list.map((item) => item.tier)), `N=${N}`).toEqual(new Set([N]));
    }
    const ten = make({}, { tierMode: { mode: "fixed", N: 10 } });
    const cap = ten.find((item) => item.key === "w90001");
    expect(cap).toEqual(atTier(record("w90001"), 10, BUNDLE));
    expect(cap.stats.AC).toBeGreaterThan(atTier(record("w90001"), 4, BUNDLE).stats.AC);
  });

  it("is a TierError for a mode or a number that is not one (the request is checked before, so this is the second line)", () => {
    expect(() => make({}, { tierMode: { mode: "arrives", D: 5 } })).toThrow(TierError);
    expect(() => make({}, { tierMode: { mode: "fixed", N: 11 } })).toThrow(TierError);
    expect(() => make({}, { tierMode: { mode: "fixed" } })).toThrow(TierError);
    expect(() => make({}, { tierMode: { mode: "sometimes" } })).toThrow(TierError);
  });
});

describe("what it does not do", () => {
  it("does not change the table: the records are read and the candidates are new objects", () => {
    const before = JSON.stringify([...TABLE.records.values()]);
    const first = make();
    expect(JSON.stringify([...TABLE.records.values()])).toBe(before);
    expect(Object.isFrozen(first[0])).toBe(true); // an item as atTier gives it
    expect(make()[0]).not.toBe(first[0]);
  });

  it("is quick on a table the size of the real one (about 6,800 records)", () => {
    const records = new Map();
    for (let at = 0; at < 6800; at += 1) {
      const source = TABLE.records.get(`w${90001 + (at % 40)}`) ?? TABLE.records.get("w90001");
      records.set(`w${1000 + at}`, { ...source, id: 1000 + at });
    }
    const watch = stopwatch();
    const list = make({}, { evidence: "strict", records });
    const took = watch.stop();
    expect(list.length).toBeGreaterThan(5000);
    expect(new Set(keysOf(list)).size).toBe(list.length);
    expectWithin(took, 3000, "the candidates of a table of 6,800 records (a loose bound: it takes a few tens of milliseconds)");
  });
});
