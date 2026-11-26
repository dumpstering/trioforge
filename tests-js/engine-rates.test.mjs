// What one more point of a stat is worth on a kit as the page shows it (static/engine/kitvalue.js, `ratesOfKit`): the kit is valued with and without one more point of the stat on
// one of its worn items, by the engine's own evaluator, and the difference is the rate, in the units of the kit's value (hit points). The bundle, the items and the kits are those of the
// synthetic site fixture (every name in them is invented). The expected numbers here are worked out by the test itself, from `evaluateTruthful` and the items at their tiers, the plain way:
// a worn item that is no weapon and no shield, one more point, the best buffs the kit has, the same view.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { SLOT_INSTANCES, evaluateTruthful } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { atTier, readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { viewProfile } from "../pipeline/trioforge/site/static/engine/view.js";
import { bestBuffsOfKit, ratesOfKit } from "../pipeline/trioforge/site/static/engine/kitvalue.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const RESULTS = resolve(ROOT, "fixtures/site/results");
const TABLE_DOCUMENT = JSON.parse(readFileSync(resolve(RESULTS, "items.json"), "utf8"));
const table = readItemTable(TABLE_DOCUMENT);
const bundle = JSON.parse(readFileSync(resolve(RESULTS, "pal-mnk-ber/engine-l50.json"), "utf8"));
const CASES = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/best-kit.json"), "utf8")).cases;
const SCHOOLS = ["FIRE", "COLD", "MAGIC", "POISON", "DISEASE"];
const POINT = 1;

const placesOf = (kit) =>
  kit.flatMap((ident, slotIndex) => (ident === null ? [] : [{ slotIndex, key: ident.slice(0, ident.lastIndexOf("@")), tier: Number(ident.slice(ident.lastIndexOf("@") + 1)) }]));
const [CASE] = CASES;
const VIEW = { ...CASE.scenario, deity: null, places: placesOf(CASE.own.kit) };
const ask = (over = {}) => ratesOfKit({ bundle, records: table.records, ...VIEW, ...over });

/**
 * The rates the plain way: the kit as the page draws it, one point more on the first worn item that is no weapon and no shield (the haste on the piece that has the most worn haste, which is the one that
 * counts: worn haste is the best single piece), with the best buffs of the kit.
 */
function plain(view, weights, point = POINT) {
  const read = readBundle(bundle);
  const profile = viewProfile(read, { race: view.race, role: view.role, buffs: view.buffs, evidence: view.evidence, deity: null, setup: view.setup }, weights);
  const kit = new Array(SLOT_INSTANCES.length).fill(null);
  for (const { slotIndex, key, tier } of view.places) kit[slotIndex] = atTier(table.records.get(key), tier, read);
  const found = bestBuffsOfKit({ bundle, records: table.records, ...view, weights });
  const options = { setup: view.setup, monkBins: read.monk_bins === null ? undefined : read.monk_bins, buffset: Object.freeze({ set: read.buffs[view.buffs].set, table: read.buff_table }) };
  const worth = (items) => evaluateTruthful(profile, items, found.buffs, options).F;
  const base = worth(kit);
  const carrier = kit.findIndex((item) => item !== null && item.weapon === null && item.is_shield === false);
  const more = (field, name) => {
    const trial = kit.slice();
    trial[carrier] = { ...kit[carrier], [field]: { ...kit[carrier][field], [name]: (kit[carrier][field][name] ?? 0) + point } };
    return worth(trial).sub(base).toNumber() / point;
  };
  const hasty = kit.reduce((best, item, at) => (item !== null && (best < 0 || item.haste > kit[best].haste) ? at : best), -1);
  const morehaste = () => {
    const trial = kit.slice();
    trial[hasty] = { ...kit[hasty], haste: kit[hasty].haste + point };
    return worth(trial).sub(base).toNumber() / point;
  };
  return {
    base,
    carrier,
    hasty,
    DEX: more("stats", "DEX"),
    MANA: more("stats", "MANA"),
    END: more("stats", "END"),
    HASTE: morehaste(),
    STA: more("stats", "STA"),
    STR: more("stats", "STR"),
    WIS: more("stats", "WIS"),
    INT: more("stats", "INT"),
    AC: more("stats", "AC"),
    schools: Object.fromEntries(SCHOOLS.map((school) => [school, more("sv", school)])),
  };
}

describe("the rates of a kit as the page shows it", () => {
  it("are the change in the kit's value from one more point of the stat on a worn item, as the evaluator gives it", () => {
    const want = plain(VIEW);
    const got = ask();
    expect(got.F).toBe(want.base.toString());
    for (const name of ["STA", "STR", "WIS", "INT", "AC", "DEX", "MANA", "END", "HASTE"]) expect(got.rates[name], name).toBe(want[name]);
    for (const school of SCHOOLS) expect(got.rates.schools[school], school).toBe(want.schools[school]);
    expect(got.rates.resist, "one resist is the best of the five").toBe(Math.max(...Object.values(want.schools)));
    expect(got.exact).toBe(true);
  });

  it("are for the view's weights: the sliders and the custom weights of a request count, so a stat the visitor turned off is worth nothing and one turned up is worth more", () => {
    const own = ask();
    expect(own.rates.AC).toBeGreaterThan(0);
    const off = ask({ weights: { custom: { AC: 0 } } });
    expect(off.rates.AC).toBe(0);
    const top = ask({ weights: { custom: { AC: bundle.roles[VIEW.role].weights.AC * 4 } } });
    expect(top.rates.AC).toBeGreaterThan(own.rates.AC * 1.5);
    expect(ask({ weights: { multipliers: { AC: 2 } } }).rates.AC).toBeGreaterThan(own.rates.AC * 1.5);
    const plainOff = plain(VIEW, { custom: { AC: 0 } });
    expect(off.rates.STA).toBe(plainOff.STA);
  });

  it("have a rate for dexterity, maximum mana and endurance as well, and for haste: one more point on the piece that has the most worn haste, since the best piece is the one that counts", () => {
    const got = ask();
    const want = plain(VIEW);
    for (const name of ["DEX", "MANA", "END", "HASTE"]) expect(Number.isFinite(got.rates[name]), name).toBe(true);
    expect(want.hasty).toBeGreaterThanOrEqual(0);
    expect(got.rates.HASTE, "haste has some value on this kit").toBeGreaterThan(0);
    expect(ask({ weights: { custom: { HASTE: 0, ATK: 0 } } }).rates.HASTE, "worth nothing when the weights give haste and the damage it speeds no value").toBe(0);
    // (dexterity and endurance feed other parts of the score than their own weight too, so a weight of 0 makes them worth less and not nothing)
    expect(ask({ weights: { custom: { DEX: 0 } } }).rates.DEX).toBeLessThan(got.rates.DEX);
    expect(ask({ weights: { custom: { END: 0 } } }).rates.END).toBeLessThanOrEqual(got.rates.END);
  });

  it("make a stat that the weights give no value to worth nothing, whatever the item that carries it", () => {
    const none = ask({ weights: { custom: { HP: 0, END: 0, MANA: 0, DEX: 0, ATK: 0, HASTE: 0, AC: 0, SV: 0 } } });
    expect(none.rates.STA).toBe(0);
    expect(none.rates.AC).toBe(0);
    expect(none.rates.resist).toBe(0);
  });

  it("have every number finite, never negative for the stats of this fixture, and a school for each of the five resists", () => {
    const got = ask();
    expect(Object.keys(got.rates.schools)).toEqual(SCHOOLS);
    for (const value of [got.rates.STA, got.rates.STR, got.rates.WIS, got.rates.INT, got.rates.AC, got.rates.DEX, got.rates.MANA, got.rates.END, got.rates.HASTE, got.rates.resist]) {
      expect(Number.isFinite(value)).toBe(true);
      expect(value).toBeGreaterThanOrEqual(0);
    }
  });

  it("are worked out for the kit that was given: another kit has other rates, and the same call is the same answer", () => {
    const another = CASES.find((c) => c.own && c.own.F !== CASE.own.F);
    const other = ask({ places: placesOf(another.own.kit), ...another.scenario });
    expect(other.F).not.toBe(ask().F);
    expect(ask()).toEqual(ask());
  });

  it("take the records of the item table as the page makes them, a Map from the key of an item to its record as the table has it, with no further reading: the evaluator checks each record it uses", () => {
    const records = new Map(TABLE_DOCUMENT.items.map((record) => [record.key ?? `w${record.id}`, record]));
    expect(records.size).toBe(table.records.size);
    expect(ratesOfKit({ bundle, records, ...VIEW })).toEqual(ask());
  });

  it("refuse what valueOfKit refuses: a search limit that is no whole number from 1, records that are no Map, places that are no list, an item that is not in the table", () => {
    expect(() => ask({ searchLimit: 0 })).toThrow(RangeError);
    expect(() => ask({ records: {} })).toThrow(TypeError);
    expect(() => ask({ places: "all" })).toThrow(TypeError);
    expect(() => ask({ places: [{ slotIndex: 0, key: "w1", tier: 4 }] })).toThrow();
  });

  it("say nothing of the rates of a kit with no worn item to carry the point, and are not fooled by a kit of weapons only", () => {
    const hands = VIEW.places.filter((place) => place.slotIndex >= 20);
    const got = ask({ places: hands });
    expect(got.rates).toBeNull();
  });
});
