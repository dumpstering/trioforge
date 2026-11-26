// The mote order in the page, held to the Python reference (pipeline/trioforge/motes.py) for the recorded cases of fixtures/site/mote-orders.json: twenty kits of the synthetic site
// fixture (Equip now's kits with a limit, small kits in full, kits under drawn weights, a kit with every item at +4, one a tier from the top, one at the top, one whose last motes gain
// nothing, and the runs: a dagger whose damage rises every second tier and an ear that passes a neck's haste only at +6, in full, with eight motes and with three), each with the exact
// value, the gain and the stats that moved at every step, the motes spent and, when a run did not fit, how long it was. The port is `engine/motes.js`; the page reaches it through the
// evaluator's script (`engine/kitvalue.js`, `moteWalkOf`), which makes the profile (the view's role, race, buffs, evidence and weights), the items at their tiers and the buff set, so the
// numbers below are those of the code that ships. Every number is an exact fraction.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { atTier, readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { bestBuffsOfKit, moteWalkOf } from "../pipeline/trioforge/site/static/engine/kitvalue.js";
import { MOVED_ORDER, MoteError, collect, createMoteWalk } from "../pipeline/trioforge/site/static/engine/motes.js";
import { assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const RESULTS = resolve(ROOT, "fixtures/site/results");
const { cases, extra } = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/mote-orders.json"), "utf8"));
// the fixture's item table, with the invented items of the runs added (the records of the fixture file: the page's own table does not have them)
const document = JSON.parse(readFileSync(resolve(RESULTS, "items.json"), "utf8"));
const table = readItemTable({ ...document, count: document.items.length + extra.length, items: [...document.items, ...extra] });
const bundle = JSON.parse(readFileSync(resolve(RESULTS, "pal-mnk-ber/engine-l50.json"), "utf8"));

const split = (ident) => [ident.slice(0, ident.lastIndexOf("@")), Number(ident.slice(ident.lastIndexOf("@") + 1))];
const placesOf = (kit) => kit.flatMap((ident, slotIndex) => (ident === null ? [] : [{ slotIndex, key: split(ident)[0], tier: split(ident)[1] }]));

/** The walk of a recorded case, as the page makes it: the view's profile and weights, the kit at its tiers, the buffs held fixed and the limit of motes. */
function walkOf(row, changes = {}) {
  const { race, role, buffs, evidence, setup, deity } = row.scenario;
  return moteWalkOf({ bundle, records: table.records, race, role, buffs, evidence, deity: deity ?? null, weights: row.weights, setup, chosen: row.buffs, motes: row.motes, places: placesOf(row.kit), ...changes });
}
const shown = (step) => ({
  index: step.index,
  place: step.place,
  key: step.key,
  from: step.from,
  to: step.to,
  motes: step.motes,
  spent: step.spent,
  gain: step.gain.toString(),
  F: step.F.toString(),
  moved: step.moved.map(([name, amount]) => [name, amount.toString()]),
});

describe("the mote order of the page against the Python reference", () => {
  it("has the cases of the fixture: every ending, a limit, weights, the runs", () => {
    expect(cases.length).toBe(26); // (the case of the shortest run, from Part E7, is the last of the runs)
    expect(new Set(cases.map((row) => row.ending))).toEqual(new Set(["top", "motes", "no-gain"]));
    expect(cases.some((row) => row.weights !== undefined)).toBe(true);
    expect(cases.some((row) => row.steps.some((step) => step.motes > 1))).toBe(true);
    expect(cases.some((row) => row.nextRun !== null)).toBe(true);
    expect(cases.find((row) => row.name.includes("shortest run")).nextRun, "E7: the order names the fewest motes of any run left (two), not the length of the run of the best rate (six)").toBe(2);
  });

  it.each(cases.map((row) => [row.name, row]))("gives the order Python gives: %s", (_, row) => {
    const result = collect(walkOf(row));
    expect(result.start.toString()).toBe(row.start);
    expect(result.ending).toBe(row.ending);
    expect(result.left).toBe(row.left);
    expect(result.spent).toBe(row.spent);
    expect(result.nextRun).toBe(row.nextRun);
    expect(result.steps.map(shown)).toEqual(row.steps);
  });

  it("finds the optional buffs Python's solver chose for a kit as the kit is made, by the exact search the page makes for a kit it shows (bestBuffsOfKit)", () => {
    // (the kits that were not given drawn weights: their buffs are the solver's own for the kit, and the page, which does not know them, searches them out; the runs' kits are made up
    // for the order, and carry the buffs of a kit of the fixture)
    const own = cases.filter((row) => row.weights === undefined && !row.kit.some((ident) => ident !== null && /^w910/.test(ident)));
    expect(own.length).toBeGreaterThanOrEqual(10);
    for (const row of own) {
      const { race, role, buffs, evidence, setup, deity } = row.scenario;
      const found = bestBuffsOfKit({ bundle, records: table.records, race, role, buffs, evidence, deity: deity ?? null, setup, places: placesOf(row.kit) });
      expect(found.exact, row.name).toBe(true);
      expect(found.buffs, row.name).toEqual([...row.buffs].sort((a, b) => a - b));
      if (row.steps.length > 0) expect(found.F, row.name).toBe(row.start);
    }
  });

  it("lists the stats that moved in the fixed order, none that changed by nothing", () => {
    const seen = new Set();
    for (const row of cases) {
      for (const step of row.steps) {
        const at = step.moved.map(([name]) => MOVED_ORDER.indexOf(name));
        expect(at.every((index) => index >= 0)).toBe(true);
        expect(at).toEqual([...at].sort((a, b) => a - b));
        expect(step.moved.every(([, amount]) => !amount.startsWith("0/"))).toBe(true);
        for (const [name] of step.moved) seen.add(name);
      }
    }
    expect(seen.has("HP") && seen.has("AC") && seen.has("DMG")).toBe(true);
  });

  it("is a walk that gives one step at a time and says why it ended", () => {
    const row = cases.find((one) => one.ending === "no-gain");
    const walk = walkOf(row);
    expect(walk.start.toString()).toBe(row.start);
    for (const expected of row.steps) {
      const step = walk.step();
      expect(step.index).toBe(expected.index);
      expect(step.F.toString()).toBe(expected.F);
    }
    expect(walk.ending()).toBe(null); // (not over: the next step has not been asked for)
    expect(walk.step()).toBe(null);
    expect(walk.ending()).toBe("no-gain");
    expect(walk.left()).toBe(row.left);
    expect(walk.spent()).toBe(row.spent);
    expect(walk.nextRun()).toBe(null);
    expect(walk.step()).toBe(null); // (and it stays over)
    const top = cases.find((one) => one.steps.length === 0 && one.ending === "top");
    const nothing = walkOf(top);
    expect(nothing.step()).toBe(null);
    expect(nothing.ending()).toBe("top");
    expect(nothing.left()).toBe(0);
  });

  it("takes a limit of motes as Python does: the whole order as far as it fits, then why it stopped", () => {
    const row = cases.find((one) => one.motes === null && one.steps.length > 6 && one.ending === "top" && one.steps.every((step) => step.motes === 1));
    const five = collect(walkOf(row, { motes: 5 }));
    expect(five.steps.map((step) => step.F.toString())).toEqual(row.steps.slice(0, 5).map((step) => step.F));
    expect(five).toMatchObject({ ending: "motes", left: row.steps.length - 5, spent: 5, nextRun: null });
    expect(collect(walkOf(row, { motes: 0 }))).toMatchObject({ ending: "motes", left: row.steps.length, spent: 0 });
    expect(collect(walkOf(row, { motes: row.steps.length }))).toMatchObject({ ending: "top", left: 0 });
    for (const bad of [-1, 1.5, "3", true, Number.NaN]) expect(() => walkOf(row, { motes: bad })).toThrow(/motes/);
  });

  it("refuses what is not a kit of this trio's items", () => {
    const row = cases[0];
    expect(() => walkOf(row, { places: [{ slotIndex: 0, key: "w1", tier: 0 }] })).toThrow(/not in the item table/);
    expect(() => walkOf(row, { places: [{ slotIndex: 22, key: placesOf(row.kit)[0].key, tier: 0 }] })).toThrow(/place/);
    expect(() => walkOf(row, { places: [{ slotIndex: 0, key: placesOf(row.kit)[0].key, tier: 11 }] })).toThrow(/tier/);
    const twice = placesOf(row.kit);
    expect(() => walkOf(row, { places: [...twice, twice[0]] })).toThrow(/two items/);
    expect(() => walkOf(row, { chosen: [987654321] })).toThrow();
  });
});

describe("the walk refuses what the reference refuses (motes.py), with a MoteError", () => {
  const profile = assembleProfile(bundle, { race: "OGR", role: "tank", buffs: "own", evidence: "wiki" });
  const head = placesOf(cases[0].kit)[0]; // an item of the fixture, at its tier
  const item = (key, tier) => atTier(table.records.get(key), tier, bundle);
  const kitWith = (worn) => Array.from({ length: 22 }, (_, at) => worn[at] ?? null);
  const make = (over = {}) => ({ profile, kit: kitWith({ 0: item(head.key, head.tier) }), itemAt: (key, tier) => item(key, tier), setup: "dw", monkBins: readBundle(bundle).monk_bins ?? undefined, buffset: undefined, buffs: [], ...over });

  it("takes optional buffs only with a buff set to choose them from (motes.py: ValueError)", () => {
    expect(() => createMoteWalk(make({ buffs: [138] }))).toThrow(MoteError);
    expect(() => createMoteWalk(make({ buffs: [138] }))).toThrow(/buffset/);
    expect(createMoteWalk(make()).start.sign()).not.toBe(undefined);
  });

  it("copies the buffs it is given once (a list the caller goes on to change changes nothing)", () => {
    const row = cases.find((one) => one.buffs.length > 1 && one.motes !== null && one.weights === undefined);
    const chosen = [...row.buffs];
    const walk = walkOf(row, { chosen });
    chosen.length = 0; // (the caller reuses its list)
    chosen.push(987654321);
    const result = collect(walk);
    expect(result.start.toString()).toBe(row.start);
    expect(result.steps.map(shown)).toEqual(row.steps);
  });

  it("takes a place that is undefined as an empty one, as Python takes None, and refuses what is not an item", () => {
    const sparse = kitWith({ 0: item(head.key, head.tier) });
    const holes = sparse.map((place) => (place === null ? undefined : place));
    const a = collect(createMoteWalk(make({ kit: sparse })));
    const b = collect(createMoteWalk(make({ kit: holes })));
    expect(b.steps.map(shown)).toEqual(a.steps.map(shown));
    expect(b.start.toString()).toBe(a.start.toString());
    const kit = new Array(22); // (holes in the list)
    kit[0] = item(head.key, head.tier);
    expect(collect(createMoteWalk(make({ kit }))).steps.map(shown)).toEqual(a.steps.map(shown));
    for (const bad of [42, "w1", [], { tier: 3 }, { key: "x", tier: "3" }, { key: "x", tier: 11 }, { key: 5, tier: 3 }]) {
      expect(() => createMoteWalk(make({ kit: kitWith({ 0: bad }) })), JSON.stringify(bad)).toThrow(MoteError);
    }
    expect(() => createMoteWalk(make({ kit: sparse.slice(0, 21) }))).toThrow(MoteError);
  });

  it("checks that every item of the kit has a record before it values anything (motes.py: no record for item)", () => {
    let valued = 0;
    const itemAt = (key, tier) => {
      valued += 1;
      if (key === head.key) throw new Error("no such record");
      return item(key, tier);
    };
    expect(() => createMoteWalk(make({ itemAt }))).toThrow(MoteError);
    expect(() => createMoteWalk(make({ itemAt }))).toThrow(new RegExp(`no record for item ${head.key}`));
    expect(valued).toBeGreaterThan(0);
    // and the error is of the kit, at its start: not a step that fails when the walk is half way
    expect(() => moteWalkOf({ bundle, records: new Map(), race: "OGR", role: "tank", buffs: "own", evidence: "wiki", setup: "dw", places: [{ slotIndex: 0, key: head.key, tier: head.tier }] })).toThrow(MoteError);
  });
});
