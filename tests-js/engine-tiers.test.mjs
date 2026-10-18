import { describe, expect, it } from "vitest";
import {
  MAX_DIFFICULTY,
  MAX_TIER,
  MODES,
  READY_TIER,
  TIER_RULES,
  TierError,
  arrivalTier,
  costToReach,
  tierForMode,
} from "../pipeline/trioforge/site/static/engine/tiers.js";
import { SAMPLE, describeFull } from "./engine-fixtures.mjs";

// The tier a candidate is scored at under a tier mode, and what bringing an item from one tier to another costs: ports of
// pipeline/trioforge/model/tiers.py (tier_for_mode, cost_to_reach), held to the tables Python wrote (items/tiers.json).

// an invented item, the shape of a record of the item table: only the tier rule matters here
const cap = (rule) => ({ id: 900001, name: "Test Cap of Examples", slots: ["HEAD"], tier_rule: rule });

describe("the constants are the ones of the rules", () => {
  it("are the ones the bundle writes", () => {
    const rules = SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json").tier_rules;
    expect(MAX_TIER).toBe(Number(rules.max_tier.split("/")[0]));
    expect(rules.max_tier).toBe(`${MAX_TIER}/1`);
    expect(rules.max_fresh_drop).toBe(`${MAX_DIFFICULTY}/1`);
    expect([...TIER_RULES]).toEqual(rules.tier_rule_values);
    expect(READY_TIER).toBe(4);
    expect([...MODES]).toEqual(["ready4", "arrives", "fixed"]);
    expect(Object.isFrozen(TIER_RULES) && Object.isFrozen(MODES)).toBe(true);
  });
});

function tableTests(set) {
  const tables = set.read("items/tiers.json");

  it("has the exp rule the bundle writes", () => {
    expect(tables.exp_needed).toBe(set.read("profiles/pal-mnk-ber-l50.bundle.json").tier_rules.exp_needed);
  });

  it("gives, for every tier rule, mode, difficulty and fixed tier, the tier Python gives", () => {
    expect(tables.modes.length).toBe(3 * (5 + 5 + 55));
    const wrong = [];
    for (const row of tables.modes) {
      const options = row.N === null ? { D: row.D } : { D: row.D, N: row.N };
      const got = tierForMode(row.rule, row.mode, options);
      const fromRecord = tierForMode(cap(row.rule), row.mode, options);
      if (got !== row.tier || fromRecord !== row.tier) wrong.push([row.rule, row.mode, row.D, row.N, row.tier, got]);
    }
    expect(wrong).toEqual([]);
  });

  it("gives, for every rule, difficulty and pair of tiers, the cost Python gives (the same keys, the same values)", () => {
    expect(tables.costs.length).toBe(3 * 5 * 66);
    const wrong = [];
    for (const row of tables.costs) {
      const got = costToReach(row.rule, row.from, row.to, { D: row.D });
      const want = { exp: row.exp, copies_at_arrival: row.copies_at_arrival, potentials: row.potentials };
      if (JSON.stringify(got) !== JSON.stringify(want) || Object.keys(got).join() !== "exp,copies_at_arrival,potentials") wrong.push([row, got]);
    }
    expect(wrong).toEqual([]);
  });
}

describe("the committed sample", () => tableTests(SAMPLE));
describeFull("the full set", (full) => tableTests(full));

describe("the tier of a mode", () => {
  it("is +4 for every item in ready4, +D for a drop and +0 for the others in arrives, and +N in fixed", () => {
    for (const rule of TIER_RULES) {
      expect(tierForMode(rule, "ready4")).toBe(4);
      expect(tierForMode(rule, "fixed", { N: 7 })).toBe(7);
      expect(tierForMode(rule, "fixed", { N: 0 })).toBe(0);
      expect(tierForMode(rule, "fixed", { N: 10 })).toBe(10);
    }
    for (const D of [0, 1, 2, 3, 4]) {
      expect(tierForMode("drop", "arrives", { D })).toBe(D);
      expect(tierForMode("fixed0", "arrives", { D })).toBe(0);
      expect(tierForMode("spell", "arrives", { D })).toBe(0);
    }
  });

  it("takes an item record, an object with a tier rule, or the rule itself", () => {
    expect(tierForMode(cap("drop"), "arrives", { D: 2 })).toBe(2);
    expect(tierForMode({ tier_rule: "fixed0" }, "arrives", { D: 2 })).toBe(0);
    expect(tierForMode("drop", "arrives", { D: 2 })).toBe(2);
  });

  it("has the difficulty 4 unless it is given, and ignores N unless the mode is fixed", () => {
    expect(tierForMode("drop", "arrives")).toBe(4);
    expect(tierForMode("drop", "arrives", {})).toBe(4);
    expect(tierForMode("drop", "ready4", { N: 99 })).toBe(4);
    expect(tierForMode("drop", "arrives", { N: -3 })).toBe(4);
    expect(arrivalTier("drop")).toBe(4);
    expect(arrivalTier("drop", 1)).toBe(1);
    expect(arrivalTier(cap("spell"), 3)).toBe(0);
  });

  it("takes no options, an empty object or null, and refuses options that are not an object", () => {
    expect(tierForMode("drop", "arrives", null)).toBe(4);
    expect(tierForMode("drop", "arrives", undefined)).toBe(4);
    expect(costToReach("drop", 0, 4, null)).toEqual({ exp: 15, copies_at_arrival: 1, potentials: 4 });
    for (const bad of [5, "D", true, [], [4]]) {
      expect(() => tierForMode("drop", "arrives", bad), String(bad)).toThrow(TierError);
      expect(() => costToReach("drop", 0, 4, bad), String(bad)).toThrow(TierError);
    }
  });

  it("refuses an option that the call does not read (a misspelt D or N would be ignored, and a tier come out as if it were not given)", () => {
    expect(tierForMode("drop", "arrives", { D: 1 })).toBe(1);
    expect(tierForMode("drop", "fixed", { N: 7 })).toBe(7);
    expect(costToReach("drop", 0, 4, { D: 1 })).toEqual({ exp: 15, copies_at_arrival: 8, potentials: 4 });
    for (const key of ["d", "n", "difficulty", "tier", "D ", "Difficulty", "DN"]) {
      const options = Object.defineProperty({}, key, { value: 1, enumerable: true });
      for (const mode of MODES) {
        expect(() => tierForMode("drop", mode, options), `${mode} ${JSON.stringify(key)}`).toThrow(TierError);
        expect(() => tierForMode("drop", mode, options), `${mode} ${JSON.stringify(key)}`).toThrow(/option/);
      }
      expect(() => costToReach("drop", 0, 4, options), JSON.stringify(key)).toThrow(TierError);
    }
    expect(() => tierForMode("drop", "arrives", { d: 1 })).toThrow(/\(d\)/);
    expect(() => tierForMode("drop", "fixed", { n: 7 })).toThrow(/\(n\)/); // not "needs N": the misspelling is named
    expect(() => costToReach("drop", 0, 4, { d: 1 })).toThrow(/\(d\)/);
    expect(() => tierForMode("drop", "arrives", { D: 1, extra: 1 })).toThrow(/extra/); // a right option does not excuse a wrong one
    expect(() => costToReach("drop", 0, 4, { D: 1, N: 3 })).toThrow(/\(N\)/); // costToReach reads D alone
    expect(() => tierForMode("drop", "arrives", Object.defineProperty({}, "__proto__", { value: 1, enumerable: true }))).toThrow(TierError);
    expect(() => tierForMode("drop", "arrives", { [`evil\n${"x".repeat(100)}`]: 1 })).toThrow(/\(\?\)/); // a key that is long is not echoed back
  });

  it("checks the difficulty in every mode", () => {
    for (const mode of MODES) {
      expect(() => tierForMode("drop", mode, { D: 5, N: 3 }), mode).toThrow(TierError);
      expect(() => tierForMode("drop", mode, { D: -1, N: 3 }), mode).toThrow(TierError);
    }
  });

  it("refuses a mode, a rule, a difficulty or a fixed tier that is not one", () => {
    expect(() => tierForMode("drop", "ready5")).toThrow(TierError);
    for (const mode of ["", "READY4", "constructor", "__proto__", "toString", null, undefined, 4, {}, ["ready4"]]) {
      expect(() => tierForMode("drop", mode), String(mode)).toThrow(TierError);
    }
    for (const rule of ["", "Drop", "quest", "constructor", "__proto__", "toString", "hasOwnProperty", null, undefined, 4, [], {}, { tier_rule: "nope" }, { tier_rule: null }, { name: "no rule" }]) {
      expect(() => tierForMode(rule, "ready4"), JSON.stringify(rule)).toThrow(TierError);
      expect(() => costToReach(rule, 0, 4), JSON.stringify(rule)).toThrow(TierError);
    }
    for (const D of [4.5, "4", null, NaN, Infinity, true, [], {}, 2 ** 40, -0.5]) {
      expect(() => tierForMode("drop", "arrives", { D }), String(D)).toThrow(TierError);
      expect(() => costToReach("drop", 0, 4, { D }), String(D)).toThrow(TierError);
    }
    expect(() => tierForMode("drop", "fixed")).toThrow(/needs N/);
    expect(() => tierForMode("drop", "fixed", { N: null })).toThrow(TierError);
    for (const N of [11, -1, 3.5, "3", NaN, Infinity, true, [], {}, 2 ** 40]) {
      expect(() => tierForMode("drop", "fixed", { N }), String(N)).toThrow(TierError);
    }
  });
});

describe("what reaching a tier costs", () => {
  it("is 2^to - 2^from experience, the copies that supply it, and a Potential a tier", () => {
    expect(costToReach("drop", 0, 4)).toEqual({ exp: 15, copies_at_arrival: 1, potentials: 4 }); // one D4 copy, 16 experience for 15
    expect(costToReach("drop", 0, 4, { D: 0 })).toEqual({ exp: 15, copies_at_arrival: 15, potentials: 4 }); // or 15 copies that arrive at +0
    expect(costToReach("drop", 4, 10)).toEqual({ exp: 1008, copies_at_arrival: 63, potentials: 6 }); // 1,008 exactly
    expect(costToReach("drop", 0, 10)).toEqual({ exp: 1023, copies_at_arrival: 64, potentials: 10 }); // 63 copies fall short
    expect(costToReach("fixed0", 0, 10)).toEqual({ exp: 1023, copies_at_arrival: 1023, potentials: 10 });
    expect(costToReach("spell", 3, 5, { D: 2 })).toEqual({ exp: 24, copies_at_arrival: 24, potentials: 2 });
    expect(costToReach(cap("drop"), 2, 6, { D: 3 })).toEqual({ exp: 60, copies_at_arrival: 8, potentials: 4 });
  });

  it("is nothing for a tier already reached", () => {
    for (const tier of [0, 5, 10]) expect(costToReach("drop", tier, tier)).toEqual({ exp: 0, copies_at_arrival: 0, potentials: 0 });
  });

  it("refuses a lower tier, a tier out of range and one that is not a whole number", () => {
    expect(() => costToReach("drop", 5, 4)).toThrow(/brought down/);
    for (const bad of [-1, 11, 4.5, "4", null, undefined, NaN, Infinity, true, [], 2 ** 40]) {
      expect(() => costToReach("drop", bad, 4), String(bad)).toThrow(TierError);
      expect(() => costToReach("drop", 0, bad), String(bad)).toThrow(TierError);
    }
  });

  it("returns a result that cannot be changed", () => {
    const cost = costToReach("drop", 0, 4);
    expect(Object.isFrozen(cost)).toBe(true);
    expect(() => {
      cost.exp = 1;
    }).toThrow(TypeError);
  });
});

describe("the error", () => {
  it("is an error of its own kind with a message", () => {
    let caught;
    try {
      tierForMode("drop", "ready5");
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(TierError);
    expect(caught).toBeInstanceOf(Error);
    expect(caught.name).toBe("TierError");
    expect(caught.message).toMatch(/ready4/);
  });
});
