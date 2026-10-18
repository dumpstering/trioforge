import { describe, expect, it } from "vitest";
import { BundleError, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { WeightsError, weightsOverride } from "../pipeline/trioforge/site/static/engine/weights.js";
import { mulberry32 } from "./engine-models.mjs";
import { SAMPLE, describeFull } from "./engine-fixtures.mjs";

// The weights of a role under the sliders, the custom weights and the regen window: a port of `weights_override` in
// pipeline/trioforge/model/roles.py. Python does all of it in exact fractions on the decimals the weights are written as and rounds once, to
// a float, at the end; this does the same on BigInt rationals (rational.js), so the doubles are the same ones, bit for bit. The constants (the
// slider groups and positions, the settable weights, the bounds, ten ticks a minute, the tolerance of the role's own window) come from the
// bundle (`weight_groups`, `regen_ratios`, `constants`), not from the code.

const BUNDLE = "profiles/pal-mnk-ber-l50.bundle.json";
const clone = (value) => JSON.parse(JSON.stringify(value));
const RAW = SAMPLE.read(BUNDLE);
const RULES = readBundle(RAW);
/** The Tank weights of PAL/MNK/BER (AC 6, ATK 2, DMG 600 x 2, HP 1, MANA 0.5 ...). */
const BASE = RAW.roles.tank.weights;
const SCHOOLS = ["FIRE", "COLD", "MAGIC", "POISON", "DISEASE"];
const GROUPS = ["AC", "MANA", "ATK+HASTE", "SV", "regen"];
const rulesWith = (change) => {
  const raw = clone(RAW);
  change(raw);
  return raw;
};
const override = (base, multipliers, custom, regenT, manaReachable) => weightsOverride(RULES, base, { multipliers, custom, regenT, manaReachable });

/** Whether two weight tables hold the same names in the same order and the very same doubles. */
function sameBits(got, want) {
  const names = Object.keys(want);
  if (JSON.stringify(Object.keys(got)) !== JSON.stringify(names)) return false;
  return names.every((name) => Object.is(got[name], want[name]));
}

// ---- parity with Python --------------------------------------------------------------------------------------------------------

function parityTests(set, compositions) {
  const bundles = set.paths("bundle");
  const rules = readBundle(set.read(BUNDLE));

  it("has the same weight rules in every bundle, so that one set of rules serves every composition", () => {
    expect(bundles.length).toBeGreaterThan(0);
    for (const path of bundles) {
      const other = set.read(path);
      expect(other.weight_groups, path).toEqual(rules.weight_groups);
      expect(other.regen_ratios, path).toEqual(rules.regen_ratios);
      expect(other.constants.weight_keys, path).toEqual(rules.constants.weight_keys);
      expect(other.constants.schools, path).toEqual(rules.constants.schools);
    }
  });

  it(`gives, for each of the ${compositions} random compositions of the sliders, custom weights and regen window, the doubles Python gave`, () => {
    const doc = set.read("profiles/weights.json");
    expect(doc.compositions.length).toBe(compositions);
    const wrong = [];
    let moved = 0;
    let withCustom = 0;
    let withWindow = 0;
    for (const row of doc.compositions) {
      const got = weightsOverride(rules, row.base, { multipliers: row.multipliers, custom: row.custom, regenT: row.regen_T, manaReachable: row.mana_reachable });
      if (!sameBits(got, row.result)) wrong.push({ row, got });
      moved += JSON.stringify(got) !== JSON.stringify(row.base);
      withCustom += Object.keys(row.custom).length > 0;
      withWindow += row.regen_T !== null;
    }
    expect(wrong.slice(0, 2)).toEqual([]);
    expect(moved).toBeGreaterThan(compositions / 2);
    expect(withCustom).toBeGreaterThan(compositions / 4);
    expect(withWindow).toBeGreaterThan(compositions / 4);
  });

  it("gives, for the weights that the matrix and neutral 36 scenarios compose, the doubles Python gave (and the profile has them)", () => {
    let found = 0;
    for (const path of [...set.paths("case", "matrix/"), ...set.paths("case", "pmb36/")]) {
      const doc = set.read(path);
      const weights = doc.inputs.weights;
      if (weights === null) continue;
      const got = weightsOverride(rules, weights.base, { multipliers: weights.multipliers, custom: weights.custom, regenT: weights.regen_T, manaReachable: weights.mana_reachable });
      expect(sameBits(got, weights.result), path).toBe(true);
      expect(sameBits(got, doc.inputs.profile.weights), path).toBe(true);
      found += 1;
    }
    expect(found).toBeGreaterThanOrEqual(3);
  });

  it("leaves the weights of every role exactly as they are when nothing is asked, and when every slider is at 1 and the window is the default", () => {
    const minutes = Number(rules.regen_ratios.default_minutes.split("/")[0]);
    let checked = 0;
    for (const path of bundles) {
      const bundle = set.read(path);
      for (const [role, row] of Object.entries(bundle.roles)) {
        const label = `${path} ${role}`;
        expect(sameBits(weightsOverride(rules, row.weights), row.weights), label).toBe(true);
        expect(sameBits(weightsOverride(rules, row.weights, {}), row.weights), label).toBe(true);
        expect(sameBits(weightsOverride(rules, row.weights, { multipliers: Object.fromEntries(GROUPS.map((g) => [g, 1])), regenT: minutes }), row.weights), label).toBe(true);
        expect(sameBits(weightsOverride(rules, row.weights, { regenT: minutes + 0 }), row.weights), label).toBe(true);
        checked += 1;
      }
    }
    expect(checked).toBeGreaterThanOrEqual(3);
  });
}

describe("the committed sample", () => parityTests(SAMPLE, 60));
describeFull("the full set", (full) => {
  parityTests(full, 500);

  it("keeps the role's own regen weight to the last digit when its stored value is a rounded fraction", () => {
    // Balanced of CLR/SHD/SHM has END = 17/60, which a double cannot hold: read as the decimal it prints as, 30 x END is a hair under 8.5
    const rules = readBundle(full.read("profiles/clr-shd-shm-l50.bundle.json"));
    const base = rules.roles.balanced.weights;
    expect(base.ENDREG).toBe(8.5);
    expect(Rational.fromNumber(base.END).mul(30).equals(Rational.fromNumber(base.ENDREG))).toBe(false);
    expect(weightsOverride(rules, base, { regenT: 3 }).ENDREG).toBe(base.ENDREG);
  });
});

// ---- worked examples -----------------------------------------------------------------------------------------------------------

describe("the examples", () => {
  it("has the Tank weights of the bundle that the examples are written for", () => {
    expect(BASE).toMatchObject({ AC: 6, ATK: 2, DMG: 1200, HASTE: 1.5, HP: 1, HPREG: 30, MANA: 0.5, MANAREG: 15, END: 0.5, ENDREG: 15, DEX: 0.1 });
  });

  it("scales a custom weight by its slider, and the damage weight follows the attack weight", () => {
    // Tank: ATK 2 and DMG 600 x 2 = 1200. Custom ATK 3 under ATK+HASTE x2 is an ATK of 6, and 600 x 6 = 3600 of DMG
    const result = override(BASE, { "ATK+HASTE": 2 }, { ATK: 3 });
    expect(result.ATK).toBe(6);
    expect(result.DMG).toBe(3600);
    expect(result.HASTE).toBe(3); // the role's own 1.5, doubled
  });

  it("puts every part at once", () => {
    const result = override(BASE, { "ATK+HASTE": 2, AC: 0.5, regen: 2, SV: 0.5, MANA: 2 }, { ATK: 3, HP: 2 }, 60);
    expect([result.ATK, result.HASTE, result.DMG]).toEqual([6, 3, 3600]);
    expect([result.AC, result.MANA]).toEqual([3, 1]);
    for (const school of SCHOOLS) expect(result[`SV_${school}`]).toBe(0.2);
    expect([result.HP, result.DEX, result.END]).toEqual([2, BASE.DEX, BASE.END]);
    // regen: 10 x 60 x the weight in effect (the slider on MANA does not feed MANAREG), then the regen slider x2
    expect(result.HPREG).toBe(2400);
    expect(result.MANAREG).toBe(600);
    expect(result.ENDREG).toBe(600);
  });

  it("moves the regen weight with the weight of its resource while the window is the role's own", () => {
    const result = override(BASE, {}, { HP: 2, END: 1 });
    expect(result.HPREG).toBe(60);
    expect(result.ENDREG).toBe(30);
    expect(result.MANAREG).toBe(BASE.MANAREG);
  });

  it("sets the value of a regen point to ten ticks a minute times the window", () => {
    const result = override(BASE, {}, {}, 1.5);
    expect([result.HPREG, result.MANAREG, result.ENDREG]).toEqual([15, 7.5, 7.5]);
    for (const [name, value] of Object.entries(BASE)) if (!name.endsWith("REG")) expect(result[name], name).toBe(value);
    const none = override(BASE, {}, {}, 0);
    expect([none.HPREG, none.MANAREG, none.ENDREG]).toEqual([0, 0, 0]);
  });

  it("keeps the role's own window for a window within a part in a trillion of it, and moves for a hair more", () => {
    expect(override(BASE, {}, {}, 3 * (1 + 1e-13))).toEqual(BASE);
    expect(override(BASE, {}, {}, 3 * (1 - 1e-13))).toEqual(BASE);
    const moved = override(BASE, {}, {}, 3 * (1 + 1e-9));
    expect(moved.HPREG).not.toBe(BASE.HPREG);
    expect(moved.HPREG).toBeCloseTo(BASE.HPREG, 6);
  });

  it("scores no damage for a Caster stick whatever the attack weight, and keeps a zero attack weight's damage", () => {
    const caster = { AC: 1, ATK: 2, DMG: 0, HP: 1, MANA: 1, END: 1, HPREG: 30, MANAREG: 30, ENDREG: 30 };
    expect(override(caster, { "ATK+HASTE": 2 }, { ATK: 50 }).DMG).toBe(0);
    const noAttack = { ATK: 0, DMG: 5, HASTE: 1 };
    expect(override(noAttack, {}, { ATK: 3 }).DMG).toBe(5); // nothing to follow: the role's own, and only the slider scales it
    expect(override(noAttack, { "ATK+HASTE": 2 }, { ATK: 3 }).DMG).toBe(10);
  });

  it("keeps, for a Balanced with a Caster in it, the ratio of its own damage to its attack weight", () => {
    const balanced = { ATK: 53 / 30, DMG: 1000, HP: 1 };
    const result = override(balanced, {}, { ATK: 2 });
    const want = Rational.fromNumber(1000).mul(2).div(Rational.fromNumber(balanced.ATK)).toNumber();
    expect(result.DMG).toBe(want);
    expect(result.DMG).toBeLessThan(600 * 2);
    expect(override({ ATK: 2, DMG: 1200 }, {}, { ATK: 4 }).DMG).toBe(2400);
  });

  it("keeps mana and mana regen at zero for a trio with no mana pool", () => {
    const melee = { HP: 1, AC: 2, MANA: 0, MANAREG: 0, END: 1, ENDREG: 30 };
    for (const minutes of [undefined, null, 3, 60]) {
      const result = override(melee, { MANA: 2, regen: 2 }, { MANA: 9 }, minutes);
      expect([result.MANA, result.MANAREG]).toEqual([0, 0]);
    }
  });

  it("lets the caller say whether mana is reachable", () => {
    const off = override(BASE, {}, { MANA: 8 }, 3, false);
    expect([off.MANA, off.MANAREG]).toEqual([0, 0]);
    expect(override(BASE, {}, { MANA: 8 }, 3, true).MANAREG).toBe(240);
    const noMana = { HP: 1, MANA: 0, MANAREG: 0 };
    expect(override(noMana, {}, { MANA: 8 }, 3, true)).toMatchObject({ MANA: 8, MANAREG: 240 });
    expect(override(noMana, {}, { MANA: 8 }, 3, null)).toMatchObject({ MANA: 0, MANAREG: 0 });
    expect(override(noMana, {}, { MANA: 8 }, 3, undefined)).toMatchObject({ MANA: 0, MANAREG: 0 });
  });

  it("lets a custom weight switch on a weight the role does not have, after the base, sorted", () => {
    const base = { AC: 1, HP: 1, HPREG: 30, HASTE: 0 };
    expect(override(base, { "ATK+HASTE": 2 }, { HASTE: 1.5 }).HASTE).toBe(3);
    expect(override(base, {}, { HP: 0 }).HPREG).toBe(0);
    const added = override({ AC: 1 }, {}, { SV_POISON: 3, CHA: 1, DEX: 2 });
    expect(Object.keys(added)).toEqual(["AC", "CHA", "DEX", "SV_POISON"]);
  });

  it("sets all five schools with SV, lets a school of its own beat it, and scales a bare SV weight like the schools", () => {
    const result = override(BASE, {}, { SV: 0.25, SV_FIRE: 1 });
    expect(result.SV_FIRE).toBe(1);
    for (const school of SCHOOLS.filter((s) => s !== "FIRE")) expect(result[`SV_${school}`]).toBe(0.25);
    expect(override(BASE, {}, { SV_FIRE: 1, SV: 0.25 })).toEqual(result); // the order of the table is no matter
    expect(override(BASE, { SV: 2 }, { SV: 0.25 }).SV_COLD).toBe(0.5);
    const bare = { HP: 1, AC: 2, SV: 0.4 };
    const set = override(bare, { SV: 2 }, { SV: 0.5 });
    expect([set.SV, set.SV_FIRE, set.HP]).toEqual([1, 1, 1]);
    expect(override(bare, { SV: 2 }, {})).toEqual({ HP: 1, AC: 2, SV: 0.8 });
  });

  it("takes the three positions of a slider in any numeric form, and a Rational for a number", () => {
    for (const position of [0.5, 1, 2, 1.0, 2.0, Rational.parse("1/2"), Rational.parse("2/1")]) {
      const half = position instanceof Rational ? position.toNumber() : position;
      expect(override(BASE, { AC: position }).AC).toBe(BASE.AC * half);
    }
    expect(override(BASE, {}, { HP: Rational.parse("7/4") }).HP).toBe(1.75);
    expect(override(BASE, {}, {}, Rational.parse("3/2")).HPREG).toBe(15);
    expect(override({ HP: Rational.parse("1/2") }).HP).toBe(0.5);
  });
});

// ---- properties ----------------------------------------------------------------------------------------------------------------

describe("the composition", () => {
  const next = mulberry32(1014);
  const pick = (list) => list[Math.floor(next() * list.length)];
  function composition() {
    const multipliers = {};
    for (const group of GROUPS) if (next() < 0.4) multipliers[group] = pick([0.5, 1, 2]);
    const custom = {};
    for (const key of ["HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "SV", "CHA", "SV_FIRE", "SV_COLD"]) if (next() < 0.25) custom[key] = pick([0, 1, 2, 3.5, Math.round(next() * 40000) / 1000, 1000]);
    const minutes = pick([undefined, null, 0, 0.5, 1.5, 3, 3.0, 7, 60, 12.25]);
    return { multipliers, custom, minutes };
  }
  const shuffled = (object) => Object.fromEntries(Object.entries(object).sort(() => next() - 0.5));

  it("is the same whatever order the tables are written in", () => {
    for (let i = 0; i < 200; i += 1) {
      const { multipliers, custom, minutes } = composition();
      const expected = override(BASE, multipliers, custom, minutes);
      const result = override(shuffled(BASE), shuffled(multipliers), shuffled(custom), minutes);
      expect(Object.keys(result).sort()).toEqual(Object.keys(expected).sort());
      for (const key of Object.keys(expected)) expect(Object.is(result[key], expected[key]), key).toBe(true);
    }
  });

  it("makes the sliders a last multiplication that commutes with the custom weights and the window", () => {
    for (let i = 0; i < 200; i += 1) {
      const { multipliers, custom, minutes } = composition();
      const plain = override(BASE, {}, custom, minutes);
      const full = override(BASE, multipliers, custom, minutes);
      for (const [key, value] of Object.entries(plain)) {
        const group = GROUPS.find((name) => RAW.weight_groups.groups[name].includes(key));
        const slider = group === undefined ? 1 : (multipliers[group] ?? 1);
        expect(full[key], key).toBe(Rational.fromNumber(value).mul(Rational.fromNumber(slider)).toNumber());
      }
    }
  });

  it("makes the window touch only the regen weights", () => {
    for (let i = 0; i < 100; i += 1) {
      const { multipliers, custom } = composition();
      const open = override(BASE, multipliers, custom, undefined);
      const timed = override(BASE, multipliers, custom, pick([0, 0.5, 1.5, 7, 60]));
      for (const key of Object.keys(open)) if (!key.endsWith("REG")) expect(timed[key], key).toBe(open[key]);
    }
  });

  it("makes a custom weight touch only itself and the weight derived from it", () => {
    const base = override(BASE, {}, {}, undefined);
    for (const [key, derived] of [["HP", ["HPREG"]], ["END", ["ENDREG"]], ["MANA", ["MANAREG"]], ["ATK", ["DMG"]], ["AC", []], ["DEX", []], ["CHA", []]]) {
      const moved = override(BASE, {}, { [key]: 7 });
      for (const name of Object.keys(base)) {
        if (name === key || derived.includes(name)) continue;
        expect(moved[name], `${key} -> ${name}`).toBe(base[name]);
      }
      expect(moved[key]).toBe(7);
    }
  });

  it("gives finite non-negative doubles, a new frozen object, and leaves the inputs alone", () => {
    const base = clone(BASE);
    const multipliers = { AC: 2, regen: 0.5 };
    const custom = { HP: 2, SV: 1.25 };
    const result = override(base, multipliers, custom, 7);
    expect(result).not.toBe(base);
    expect(base).toEqual(BASE);
    expect(multipliers).toEqual({ AC: 2, regen: 0.5 });
    expect(custom).toEqual({ HP: 2, SV: 1.25 });
    expect(Object.values(result).every((value) => typeof value === "number" && Number.isFinite(value) && value >= 0)).toBe(true);
    expect(Object.keys(result)).toEqual(Object.keys(base));
    expect(Object.isFrozen(result)).toBe(true);
    expect(() => {
      result.AC = 1;
    }).toThrow(TypeError);
    expect(Object.is(override(base)["AC"], base.AC)).toBe(true);
  });

  it("is made from a base that is frozen or has no prototype just the same", () => {
    const frozen = Object.freeze(clone(BASE));
    expect(override(frozen, { AC: 2 })).toEqual(override(BASE, { AC: 2 }));
    expect(override(Object.assign(Object.create(null), BASE), Object.assign(Object.create(null), { AC: 2 }))).toEqual(override(BASE, { AC: 2 }));
  });
});

// ---- what is refused -------------------------------------------------------------------------------------------------------------

describe("what is refused", () => {
  it("is a multiplier that is not one of the three positions", () => {
    for (const value of [0.7, 3, 4, 0, -1, -2, 0.25, 1.5, true, null, undefined, "2", NaN, Infinity, [2], {}, 2.0000000001]) {
      expect(() => override(BASE, { AC: value }), String(value)).toThrow(WeightsError);
      expect(() => override(BASE, { AC: value }), String(value)).toThrow(/multiplier/);
    }
  });

  it("is a slider group that is not one of the five", () => {
    for (const group of ["ac", "ATK", "HASTE", "DMG", "HP", "regen ", "", "__proto__", "constructor", "toString", "SV_FIRE"]) {
      const multipliers = Object.defineProperty({}, group, { value: 2, enumerable: true });
      expect(() => override(BASE, multipliers), JSON.stringify(group)).toThrow(/group/);
    }
  });

  it("is multipliers or custom weights that are not a table", () => {
    for (const bad of [[["AC", 2]], "AC", 5, true, () => ({})]) {
      expect(() => override(BASE, bad), String(bad)).toThrow(/multipliers/);
      expect(() => override(BASE, {}, bad), String(bad)).toThrow(/custom/);
    }
    expect(() => override(BASE, new Map([["AC", 2]]))).toThrow(/multipliers/);
    expect(() => override(BASE, null, null)).not.toThrow();
  });

  it("is a custom weight that is not one of the settable ones", () => {
    for (const key of ["DMG", "HPREG", "MANAREG", "ENDREG", "SV_CORRUPTION", "hp", "LUCK", "", "__proto__", "constructor"]) {
      const custom = Object.defineProperty({}, key, { value: 1, enumerable: true });
      expect(() => override(BASE, {}, custom), JSON.stringify(key)).toThrow(/custom/);
    }
  });

  it("is a custom weight that is not a number from 0 to the maximum", () => {
    for (const value of [-0.1, -1, NaN, Infinity, -Infinity, true, false, null, undefined, "3", [1], {}, 1000.0001, 1001, 1e9]) {
      expect(() => override(BASE, {}, { HP: value }), String(value)).toThrow(/custom/);
    }
    expect(override(BASE, {}, { HP: 0 }).HP).toBe(0);
    expect(override(BASE, {}, { HP: 1000 }).HP).toBe(1000);
  });

  it("is a regen window that is not a number of minutes from 0 to the maximum", () => {
    for (const minutes of [-1, -0.001, 61, 60.0001, NaN, Infinity, -Infinity, true, "3", [3], {}]) {
      expect(() => override(BASE, {}, {}, minutes), String(minutes)).toThrow(/regenT/);
    }
    expect(override(BASE, {}, {}, 0).HPREG).toBe(0);
    expect(override(BASE, {}, {}, 60).HPREG).toBe(10 * 60 * BASE.HP);
  });

  it("is base weights that are not a table of known non-negative numbers", () => {
    for (const bad of [{ LUCK: 1 }, { HP: -1 }, { HP: NaN }, { HP: Infinity }, { HP: true }, { HP: "1" }, { HP: null }, { HP: 1e16 }, [["HP", 1]], null, undefined, 3, "HP", Object.defineProperty({}, "__proto__", { value: 1, enumerable: true })]) {
      expect(() => weightsOverride(RULES, bad, {}), JSON.stringify(bad)).toThrow(WeightsError);
      expect(() => weightsOverride(RULES, bad, {}), JSON.stringify(bad)).toThrow(/base/);
    }
    expect(override({ HP: 1e15 }).HP).toBe(1e15);
    expect(override({}, {}, { HP: 2 })).toEqual({ HP: 2 });
  });

  it("is a mana flag that is neither true, false, null nor undefined", () => {
    for (const flag of [0, 1, "yes", [], {}]) expect(() => override(BASE, {}, {}, undefined, flag), String(flag)).toThrow(WeightsError);
  });

  it("is options that are not an object", () => {
    for (const bad of ["x", 5, true, []]) expect(() => weightsOverride(RULES, BASE, bad), String(bad)).toThrow(WeightsError);
    expect(weightsOverride(RULES, BASE, undefined)).toEqual(BASE);
    expect(weightsOverride(RULES, BASE, null)).toEqual(BASE);
  });

  it("is an option that weightsOverride does not read (a misspelt regenT or multipliers would be ignored, and the weights look right)", () => {
    expect(weightsOverride(RULES, BASE, { regenT: 1 }).HPREG).not.toBe(BASE.HPREG);
    expect(weightsOverride(RULES, BASE, { multipliers: { AC: 2 } }).AC).toBe(BASE.AC * 2);
    for (const [key, value] of [
      ["regen_T", 1], ["regent", 1], ["RegenT", 1], ["regenMinutes", 1], ["multiplier", { AC: 2 }], ["Multipliers", { AC: 2 }], ["customs", { HP: 2 }],
      ["custom_weights", { HP: 2 }], ["mana_reachable", false], ["manareachable", false], ["minutes", 3],
    ]) {
      const options = Object.defineProperty({}, key, { value, enumerable: true });
      expect(() => weightsOverride(RULES, BASE, options), key).toThrow(WeightsError);
      expect(() => weightsOverride(RULES, BASE, options), key).toThrow(key);
    }
    expect(() => weightsOverride(RULES, BASE, { regenT: 1, minutes: 3 })).toThrow(/minutes/); // a right option does not excuse a wrong one
    expect(() => weightsOverride(RULES, BASE, Object.defineProperty({}, "__proto__", { value: 1, enumerable: true }))).toThrow(WeightsError);
    expect(() => weightsOverride(RULES, BASE, { [`evil\n${"x".repeat(100)}`]: 1 })).toThrow(/\(\?\)/); // a key that is long is not echoed back
  });

  it("is a bundle that is not one", () => {
    for (const bad of [null, undefined, {}, [], "rules", 5]) expect(() => weightsOverride(bad, BASE), String(bad)).toThrow(BundleError);
  });

  it("is an error of its own kind with a message", () => {
    let caught;
    try {
      override(BASE, { AC: 0.7 });
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(WeightsError);
    expect(caught).toBeInstanceOf(Error);
    expect(caught.name).toBe("WeightsError");
    expect(caught.message).toMatch(/AC/);
  });
});

// ---- the constants come from the bundle -----------------------------------------------------------------------------------------

describe("the rules of the bundle", () => {
  it("decide the largest custom weight", () => {
    const rules = rulesWith((raw) => {
      raw.weight_groups.custom_max = "10/1";
    });
    expect(weightsOverride(rules, BASE, { custom: { HP: 10 } }).HP).toBe(10);
    expect(() => weightsOverride(rules, BASE, { custom: { HP: 11 } })).toThrow(/custom/);
  });

  it("decide the slider positions", () => {
    const rules = rulesWith((raw) => {
      raw.weight_groups.multipliers = ["1/1", "3/1"];
    });
    expect(weightsOverride(rules, BASE, { multipliers: { AC: 3 } }).AC).toBe(18);
    expect(() => weightsOverride(rules, BASE, { multipliers: { AC: 0.5 } })).toThrow(/multiplier/);
  });

  it("decide the ticks a minute, the longest window and the window that is the role's own", () => {
    const twenty = rulesWith((raw) => {
      raw.regen_ratios.ticks_per_minute = "20/1";
    });
    expect(weightsOverride(twenty, BASE, { regenT: 2 }).HPREG).toBe(20 * 2 * BASE.HP);
    const short = rulesWith((raw) => {
      raw.regen_ratios.max_minutes = "10/1";
      raw.weight_groups.regen_t_max = "10/1";
    });
    expect(() => weightsOverride(short, BASE, { regenT: 11 })).toThrow(/regenT/);
    expect(weightsOverride(short, BASE, { regenT: 10 }).HPREG).toBe(10 * 10 * BASE.HP);
    // a wider tolerance makes 3.001 the role's own window
    const wide = rulesWith((raw) => {
      raw.regen_ratios.match = "1/100";
    });
    expect(weightsOverride(wide, BASE, { regenT: 3.001 })).toEqual(BASE);
    expect(weightsOverride(RULES, BASE, { regenT: 3.001 }).HPREG).not.toBe(BASE.HPREG);
  });

  it("decide the weights a slider group holds", () => {
    const rules = rulesWith((raw) => {
      raw.weight_groups.groups.AC = ["AC", "DEX"];
    });
    expect(weightsOverride(rules, BASE, { multipliers: { AC: 2 } }).DEX).toBe(BASE.DEX * 2);
    expect(weightsOverride(RULES, BASE, { multipliers: { AC: 2 } }).DEX).toBe(BASE.DEX);
  });

  it("decide the weights a trio with no mana pool zeroes", () => {
    const rules = rulesWith((raw) => {
      raw.weight_groups.mana_keys = ["MANA"];
    });
    const result = weightsOverride(rules, BASE, { manaReachable: false });
    expect([result.MANA, result.MANAREG]).toEqual([0, BASE.MANAREG]);
  });

  it("are refused when they do not fit together", () => {
    for (const [name, change] of [
      ["the longest window of the two blocks differ", (raw) => (raw.regen_ratios.max_minutes = "30/1")],
      ["a slider group holds a weight there is none of", (raw) => (raw.weight_groups.groups.AC = ["AC", "LUCK"])],
      ["a weight is in two slider groups", (raw) => (raw.weight_groups.groups.MANA = ["MANA", "AC"])],
      ["the slider groups lack the regen group", (raw) => delete raw.weight_groups.groups.regen],
      ["the slider groups lack the attack group", (raw) => delete raw.weight_groups.groups["ATK+HASTE"]],
      ["no slider position", (raw) => (raw.weight_groups.multipliers = [])],
      ["a slider position is below zero", (raw) => (raw.weight_groups.multipliers = ["-1/1", "1/1"])],
      ["the settable weights lack SV", (raw) => (raw.weight_groups.custom_keys = raw.weight_groups.custom_keys.filter((key) => key !== "SV"))],
      ["a settable weight is none", (raw) => (raw.weight_groups.custom_keys.push("LUCK"))],
      ["the damage weight follows nothing", (raw) => (raw.weight_groups.damage_follows = "LUCK")],
      ["a regen weight follows nothing", (raw) => (raw.weight_groups.regen_sources.HPREG = "LUCK")],
      ["the derived weights lack the damage weight", (raw) => (raw.weight_groups.derived = ["HPREG", "MANAREG", "ENDREG"])],
      ["no ticks a minute", (raw) => (raw.regen_ratios.ticks_per_minute = "0/1")],
      ["the maximum of the custom weights is below zero", (raw) => (raw.weight_groups.custom_max = "-1/1")],
      ["the weight rules are missing", (raw) => delete raw.weight_groups.custom_max],
      ["the weight rules are the wrong type", (raw) => (raw.weight_groups.groups = [])],
    ]) {
      const rules = rulesWith(change);
      expect(() => weightsOverride(rules, BASE), name).toThrow(BundleError);
    }
  });
});

// ---- exactness -----------------------------------------------------------------------------------------------------------------

describe("exactness", () => {
  it("matches an independent calculation with fractions on random compositions (a seeded series)", () => {
    const next = mulberry32(99);
    const pick = (list) => list[Math.floor(next() * list.length)];
    const q = (x) => Rational.fromNumber(x);
    const rules = RAW.weight_groups;
    for (let i = 0; i < 400; i += 1) {
      const multipliers = {};
      for (const group of GROUPS) if (next() < 0.5) multipliers[group] = pick([0.5, 1, 2]);
      const custom = {};
      for (const key of ["HP", "AC", "ATK", "HASTE", "END", "MANA"]) if (next() < 0.3) custom[key] = pick([0, 0.75, 1, 3.25, 12.5, 100]);
      const minutes = pick([undefined, 0, 1.5, 3, 7.25, 60]);
      const got = override(BASE, multipliers, custom, minutes);
      // the definition again, in the order the documentation gives it
      const slider = (group) => q(multipliers[group] ?? 1);
      const inEffect = (key) => (key in custom ? q(custom[key]) : q(BASE[key]));
      const groupOf = (key) => GROUPS.find((name) => rules.groups[name].includes(key));
      const want = {};
      for (const key of Object.keys(BASE)) {
        if (["DMG", "HPREG", "MANAREG", "ENDREG"].includes(key)) continue;
        want[key] = inEffect(key).mul(groupOf(key) === undefined ? 1 : slider(groupOf(key)));
      }
      want.DMG = q(BASE.DMG).mul(inEffect("ATK")).div(q(BASE.ATK)).mul(slider("ATK+HASTE"));
      for (const [regen, resource] of [["HPREG", "HP"], ["MANAREG", "MANA"], ["ENDREG", "END"]]) {
        const own = q(BASE[regen]);
        const keepsOwn = minutes === undefined || q(10).mul(q(minutes)).mul(q(BASE[resource])).sub(own).abs().compare(own.mul(Rational.parse("1/1000000000000"))) <= 0;
        want[regen] = (keepsOwn ? own.mul(inEffect(resource)).div(q(BASE[resource])) : q(10).mul(q(minutes)).mul(inEffect(resource))).mul(slider("regen"));
      }
      for (const key of Object.keys(BASE)) expect(got[key], `${key} ${JSON.stringify({ multipliers, custom, minutes })}`).toBe(want[key].toNumber());
    }
  });
});
