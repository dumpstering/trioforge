import { describe, expect, it } from "vitest";
import { CONSTANTS, SLOT_INSTANCES, evaluate, fallbackBonus } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { atTier } from "../pipeline/trioforge/site/static/engine/items.js";
import { assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { damageIndex } from "../pipeline/trioforge/site/static/engine/model.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { SAMPLE } from "./engine-fixtures.mjs";

// The five rule changes of 2026-10-22 (branch p7rules) as the browser engine has them, with numbers worked out by hand; pipeline/tests/test_p7rules.py holds
// Python to the same numbers and the parity fixtures hold the two together:
//   * weapon damage 10 percent of the base a tier, no minimum step (5 stays the other choice); * weight 9 percent of the base a tier to a floor of a tenth;
//   * Unbound Alacrity: 10 haste for a trio with a Monk, on top of the spell haste and the best worn haste, up to the cap; * the dual-wield factor by trio;
//   * a main hand with no listed bonus gets the client's formula of the level, (level / 100) x max(damage, level) x f x min(delay, 50) / 40 (T9: it was 0.67 x min(delay, 50) for a two-hander and 0.5 x delay for a one-hander).

const BUNDLE = "profiles/pal-mnk-ber-l50.bundle.json";
const RULES = readBundle(SAMPLE.read(BUNDLE));
const record = (changes = {}) => ({ id: 9001, name: "Invented Thing", slots: ["PRIMARY"], weight10: 10, tier_rule: "drop", ...changes });
const sword = (dmg, delay = 30, bonus = null, skill = "1H Slashing") => ({ skill, dmg, delay, bonus });
const dmgAt = (dmg, tier, options) => atTier(record({ weapon: sword(dmg) }), tier, RULES, options).weapon.dmg;
const weightAt = (weight10, tier) => atTier(record({ slots: ["HEAD"], weight10 }), tier, RULES).weight10;
const q = (numerator, denominator = 1) => new Rational(BigInt(numerator), BigInt(denominator));

describe("weapon damage: 10 percent of the base a tier, with no minimum step", () => {
  it("has 10 as the rate of the rules and 5 as the other choice", () => {
    expect(RULES.weapon_rules.damage_pct).toBe("10/1");
    expect(RULES.weapon_rules.damage_pct_choices).toEqual(["5/1", "10/1"]);
  });

  it("reads a weapon of damage 6 as 8 at +4 and 9 at +5", () => {
    expect(dmgAt(6, 4)).toBe(8);
    expect(dmgAt(6, 5)).toBe(9);
  });

  it("gives a weapon of damage 3 nothing until the percent adds up to a point", () => {
    expect(Array.from({ length: 11 }, (_, tier) => dmgAt(3, tier))).toEqual([3, 3, 3, 3, 4, 4, 4, 5, 5, 5, 6]);
  });

  it("has no minimum step at the 5 percent rate either", () => {
    expect(Array.from({ length: 11 }, (_, tier) => dmgAt(3, tier, { weaponPct: 5 }))).toEqual([3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4]);
    expect(dmgAt(20, 4, { weaponPct: 5 })).toBe(24);
  });

  it("rounds down: dmg + dmg * n * pct // 100", () => {
    for (const [dmg, tier, want] of [[20, 1, 22], [45, 3, 58], [100, 10, 200], [7, 5, 10]]) expect(dmgAt(dmg, tier), `${dmg} at +${tier}`).toBe(want);
  });
});

describe("weight: 9 percent of the base a tier, no minimum step, to the floor", () => {
  it("has the rule in the bundle", () => {
    expect(RULES.tier_rules.weight_pct).toBe("9/1");
  });

  it("makes 19 tenths 18 at +1, 10 tenths 7 at +4 and 2 tenths 2 at +5", () => {
    expect(weightAt(19, 1)).toBe(18);
    expect(weightAt(10, 4)).toBe(7);
    expect(weightAt(2, 5)).toBe(2);
  });

  it("stops at the floor of a tenth, and keeps a weightless item weightless and an unknown weight at 1.0 stone", () => {
    expect(weightAt(10, 10)).toBe(1);
    expect(weightAt(1, 10)).toBe(1);
    expect(weightAt(0, 7)).toBe(0);
    for (const tier of [0, 5, 10]) expect(atTier(record({ weight10: null }), tier, RULES)).toMatchObject({ weight10: 10, weight_known: false });
  });

  it("rounds the reduction down: w - w * 9 * n // 100", () => {
    for (const [tenths, tier, want] of [[73, 4, 47], [15, 4, 10], [15, 1, 14], [50, 3, 37], [35, 10, 4]]) expect(weightAt(tenths, tier), `${tenths} at +${tier}`).toBe(want);
  });
});

describe("the damage bonus of a main hand when none is listed (the client's formula of the level, T9)", () => {
  const delay = (n) => q(n);
  // (level, damage, delay, two-handed, the bonus worked out by hand): the same cases as BONUS_CASES of pipeline/tests/test_p7rules.py
  const CASES = [
    [50, 20, 30, false, q(15)],
    [50, 50, 40, false, q(20)],
    [50, 60, 30, false, q(18)],
    [50, 10, 80, false, q(25)], // the delay counts at most 50 for a one-hander too
    [50, 40, 60, true, q(34375, 1000)], // 0.6875 x min(delay, 50): the old rule had 0.67
    [50, 40, 40, true, q(2750, 100)],
    [50, 70, 60, true, q(48125, 1000)],
    [40, 20, 30, false, q(96, 10)],
    [28, 10, 40, false, q(28, 100).mul(28).mul(q(4, 5))],
    [27, 10, 40, false, q(0)], // none below level 28
    [1, 99, 60, true, q(0)],
  ];
  it("is (level / 100) x max(damage, level) x f x min(delay, 50) / 40, from level 28, f 0.8 for a one-hander and 1.1 for a two-hander", () => {
    for (const [level, damage, delayOf, two, want] of CASES) {
      expect(fallbackBonus(two, delay(delayOf), q(damage), level).equals(want), `${level} ${damage} ${delayOf} ${two}`).toBe(true);
    }
    expect(CONSTANTS.weaponIndex.bonusDelayCap.equals(q(50))).toBe(true);
  });

  it("is what the damage index of the builder uses at the level of the profile, and a listed bonus is not capped", () => {
    const item = (delayOf, bonus = null, dmg = 40) => ({ weapon: { dmg, delay: delayOf, bonus, twoHanded: true }, slots: new Set(["PRIMARY"]), isShield: false });
    expect(damageIndex(item(60), "PRIMARY", "2h", 0, q(1)).equals(q(40).add(q(34375, 1000)).div(q(60)))).toBe(true); // (no level named: level 50)
    expect(damageIndex(item(40), "PRIMARY", "2h", 0, q(1)).equals(q(40).add(q(2750, 100)).div(q(40)))).toBe(true);
    expect(damageIndex(item(60, 33), "PRIMARY", "2h", 0, q(1)).equals(q(73, 60))).toBe(true);
    expect(damageIndex(item(60), "PRIMARY", "2h", 25, q(1), q(1), q(1), 40).equals(q(40).add(q(22)).div(q(60)).mul(q(5, 4)))).toBe(true); // level 40: 0.4 x 40 x 1.1 x 50 / 40 = 22
    expect(damageIndex(item(60, null, 70), "PRIMARY", "2h", 0, q(1)).equals(q(70).add(q(48125, 1000)).div(q(60)))).toBe(true); // more damage than the level
    expect(damageIndex(item(60), "PRIMARY", "2h", 0, q(1), q(1), q(1), 27).equals(q(40, 60))).toBe(true); // no bonus below level 28
  });

  it("is what the evaluator uses at the level of the profile", () => {
    const base = assembleProfile(RULES, { race: "OGR", role: "tank", buffs: "own" });
    const axe = { key: "axe", stats: {}, sv: {}, haste: 0, weight10: 1, weapon: { skill: "2H Slashing", dmg: 40, delay: 60, bonus: null, two_handed: true }, is_shield: false };
    const kit = new Array(SLOT_INSTANCES.length).fill(null);
    kit[SLOT_INSTANCES.indexOf("PRIMARY")] = axe;
    const at = (level) => evaluate({ ...JSON.parse(JSON.stringify(base)), level, weights: { DMG: 1 }, monk: null, stance: null }, kit, null, { setup: "2h", hasteAssumed: 0 }).breakdown.parts.WEAPON;
    expect(at(50).equals(q(40).add(q(34375, 1000)).div(q(60)))).toBe(true);
    expect(at(27).equals(q(40, 60))).toBe(true);
  });
});

describe("the profile of a trio: Unbound Alacrity and the dual-wield factor", () => {
  const listing = SAMPLE.read("evaluate/profiles.json");
  const rows = listing.profiles.map((row) => row.profile);
  const withMonk = rows.filter((profile) => profile.trio.includes("MNK"));
  const without = rows.filter((profile) => !profile.trio.includes("MNK"));
  const HEAD = SLOT_INSTANCES.indexOf("HEAD");
  const counted = (profile, spell, worn) => {
    const kit = new Array(SLOT_INSTANCES.length).fill(null);
    if (worn > 0) kit[HEAD] = { key: "hat", stats: {}, sv: {}, haste: worn, weight10: 1, weapon: null, is_shield: false };
    const own = { ...JSON.parse(JSON.stringify(profile)), buff_totals: spell > 0 ? { HASTE: spell } : {}, weights: { HASTE: 1 } };
    const bins = listing.monk_bins[String(profile.level)];
    return Number(evaluate(own, kit, null, { monkBins: bins }).breakdown.totals.haste.counted.toString().split("/")[0]);
  };

  it("has both kinds of trio in the sample", () => {
    expect(withMonk.length).toBeGreaterThan(0);
    expect(without.length).toBeGreaterThan(0);
  });

  it("gives a trio with a Monk the dual-wield factor 0.83 and 10 haste, and a trio without one 0.69 and none", () => {
    for (const profile of withMonk) expect([profile.dw_factor, profile.haste_bonus]).toEqual([0.83, 10]);
    for (const profile of without) expect([profile.dw_factor, profile.haste_bonus]).toEqual([0.69, 0]);
  });

  it("assembles the profile of the bundle (a Monk trio) with them", () => {
    const profile = assembleProfile(RULES, { race: "HUM", role: "tank", buffs: "own" });
    expect([profile.dw_factor, profile.haste_bonus]).toEqual([0.83, 10]);
    expect(profile.spell_haste).toBe(RULES.buffs.own.spell_haste);
    expect(profile.spell_haste).toBeGreaterThanOrEqual(10);
  });

  it("counts 10 haste for a Monk's trio with no other haste, and none for a trio without a Monk", () => {
    for (const profile of withMonk.slice(0, 3)) expect(counted(profile, 0, 0)).toBe(10);
    for (const profile of without.slice(0, 3)) expect(counted(profile, 0, 0)).toBe(0);
  });

  it("stacks it with the spell haste and the best worn haste up to the cap (85 with a Monk, 75 without, at level 50)", () => {
    for (const profile of withMonk.filter((one) => one.level === 50).slice(0, 3)) {
      expect(counted(profile, 45, 40)).toBe(85);
      expect(counted(profile, 20, 30)).toBe(60);
      expect(counted(profile, 0, 25)).toBe(35);
    }
    for (const profile of without.filter((one) => one.level === 50).slice(0, 3)) {
      expect(counted(profile, 45, 40)).toBe(75);
      expect(counted(profile, 20, 30)).toBe(50);
    }
  });

  it("has the cap of the level in the profile: at level 55 it is 85, and 95 with a Monk (T7)", () => {
    const at55 = rows.filter((one) => one.level === 55);
    expect(at55.length).toBeGreaterThan(0);
    for (const profile of at55) {
      const cap = profile.trio.includes("MNK") ? 95 : 85;
      expect(profile.haste_cap).toBe(cap);
      expect(counted(profile, 45, 40)).toBe(Math.min(cap, 45 + profile.haste_bonus + 40));
    }
  });
});
