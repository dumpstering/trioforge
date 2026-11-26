import loadHighs from "highs";
import { beforeAll, describe, expect, it } from "vitest";
import { SLOT_INSTANCES, evaluate } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { buildMilp, damageIndex, readItem } from "../pipeline/trioforge/site/static/engine/model.js";
import { assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { closeSession, createSession, solveScenario } from "../pipeline/trioforge/site/static/engine/solve.js";
import { SAMPLE } from "./engine-fixtures.mjs";
import { gear, oneHand, profileWith, q, twoHand } from "./engine-hand.mjs";

// The Berserker stance in the browser's engine, held to what pipeline/tests/test_formulas.py, test_profile.py and test_weapons.py hold Python to (the stance.berserker rule, T8):
// the swing of the two hands is multiplied by 2.1 after the haste cap (a bow's shot and a proc are not), and agility counts for nothing in the sheet armor class and the evasion.
// Every item here is invented; the numbers are worked out by hand.

const PRIMARY = SLOT_INSTANCES.indexOf("PRIMARY");
const SECONDARY = SLOT_INSTANCES.indexOf("SECONDARY");
const RANGE = SLOT_INSTANCES.indexOf("RANGE");
const FEET = SLOT_INSTANCES.indexOf("FEET");
const STANCE = { swing_factor: 2.1, agi_share: 0 };
const FACTOR = q(21, 10);
const kit = (...entries) => {
  const places = new Array(SLOT_INSTANCES.length).fill(null);
  for (const [place, item] of entries) places[place] = item;
  return places;
};

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

describe("the bundle and the profile", () => {
  const bundle = readBundle(SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json"));
  it("gives the Melee build of a trio with a Berserker the stance, and every other build none", () => {
    expect(bundle.roles.melee.stance).toEqual({ agi_share: 0, swing_factor: 2.1 });
    for (const role of Object.keys(bundle.roles)) if (role !== "melee") expect(bundle.roles[role].stance).toBeNull();
    expect(assembleProfile(bundle, { race: "OGR", role: "melee", buffs: "own" }).stance).toEqual({ agi_share: 0, swing_factor: 2.1 });
    expect(assembleProfile(bundle, { race: "OGR", role: "tank", buffs: "own" }).stance).toBeNull();
  });
  it("refuses a stance that is not a factor above 0 and a share from 0 to 1, in the role row and in the profile", () => {
    const bad = (stance) => {
      const copy = JSON.parse(JSON.stringify(SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json")));
      copy.roles.melee.stance = stance;
      return () => readBundle(copy);
    };
    for (const stance of [{ swing_factor: 0, agi_share: 0 }, { swing_factor: 2.1, agi_share: 2 }, { swing_factor: 2.1 }, { agi_share: 0 }, 5, "berserker"]) expect(bad(stance)).toThrow();
    const profile = assembleProfile(bundle, { race: "OGR", role: "melee", buffs: "own" });
    const monkBins = bundle.monk_bins;
    for (const stance of [{ swing_factor: 0, agi_share: 0 }, { swing_factor: 2.1, agi_share: 2 }, { swing_factor: 2.1 }, 5]) {
      expect(() => evaluate({ ...profile, stance }, kit(), null, { setup: "dw", hasteAssumed: 0, monkBins })).toThrow(/stance/);
    }
  });
});

describe("the damage index", () => {
  const sword = readItem(gear("it-sword", ["PRIMARY", "SECONDARY"], { weapon: oneHand(20, 30) }), 0);
  const axe = readItem(gear("it-axe", ["PRIMARY"], { weapon: twoHand(30, 40) }), 0);
  const arrows = readItem(gear("it-bow", ["RANGE"], { weapon: { skill: "Archery", dmg: 20, delay: 40, bonus: null, two_handed: false } }), 0);
  it("multiplies a hand that swings and not the range place", () => {
    for (const [item, hand, setup] of [[sword, "PRIMARY", "1h-shield"], [sword, "PRIMARY", "dw"], [sword, "SECONDARY", "dw"], [axe, "PRIMARY", "2h"]]) {
      const plain = damageIndex(item, hand, setup, 50, q(69, 100));
      expect(plain.sign()).toBe(1);
      expect(damageIndex(item, hand, setup, 50, q(69, 100), q(1), FACTOR).equals(plain.mul(FACTOR))).toBe(true);
    }
    const shot = damageIndex(arrows, "RANGE", "ranged", 50, q(1), q(3, 4));
    expect(damageIndex(arrows, "RANGE", "ranged", 50, q(1), q(3, 4), FACTOR).equals(shot)).toBe(true);
    expect(damageIndex(sword, "PRIMARY", "stick", 50, q(1), q(1), FACTOR).sign()).toBe(0);
  });
});

describe("the evaluator", () => {
  const bundle = readBundle(SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json"));
  const base = assembleProfile(bundle, { race: "OGR", role: "tank", buffs: "own" });
  const monkBins = bundle.monk_bins;
  const weights = { DMG: 10, AC: 4, HASTE: 1 };
  const plainProfile = { ...base, weights: { ...base.weights, ...weights }, stance: null };
  const stancedProfile = { ...plainProfile, stance: STANCE };
  const sword = gear("it-sword", ["PRIMARY", "SECONDARY"], { weapon: oneHand(20, 30) });
  const boots = gear("it-boots", ["FEET"], { haste: 30 });
  const placed = kit([PRIMARY, sword], [FEET, boots]);
  const run = (profile, setup = "1h-shield") => evaluate(profile, placed, null, { setup, hasteAssumed: 50, monkBins }).breakdown;

  it("multiplies the weapon part by the factor, leaves the haste as it is and takes the agility out of the evasion and the sheet", () => {
    const plain = run(plainProfile);
    const stanced = run(stancedProfile);
    expect(plain.parts.WEAPON.sign()).toBe(1);
    expect(stanced.parts.WEAPON.equals(plain.parts.WEAPON.mul(FACTOR))).toBe(true);
    expect(stanced.parts.HASTE.equals(plain.parts.HASTE)).toBe(true);
    expect(plain.parts.EVASION.sign()).toBe(1);
    expect(stanced.parts.EVASION.sign()).toBe(0);
    expect(stanced.parts.HP.equals(plain.parts.HP)).toBe(true);
  });
  it("takes agility out of the sheet: more agility moves the plain sheet and not the stanced one", () => {
    const more = (profile) => ({ ...profile, naked: { ...profile.naked, AGI: profile.naked.AGI + 40 } });
    expect(run(more(plainProfile)).parts.AC.equals(run(plainProfile).parts.AC)).toBe(false);
    expect(run(more(stancedProfile)).parts.AC.equals(run(stancedProfile).parts.AC)).toBe(true);
  });
  it("does not multiply a bow", () => {
    const bow = gear("it-bow", ["RANGE"], { weapon: { skill: "Archery", dmg: 40, delay: 60, bonus: null, two_handed: false } });
    const shot = (profile) => evaluate(profile, kit([RANGE, bow]), null, { setup: "ranged", hasteAssumed: 0, monkBins }).breakdown.parts.WEAPON;
    expect(shot(stancedProfile).equals(shot(plainProfile))).toBe(true);
  });
  it("reads a profile written without a stance as one with none", () => {
    const { stance, ...without } = plainProfile;
    expect(run(without).parts.WEAPON.equals(run(plainProfile).parts.WEAPON)).toBe(true);
  });
});

describe("the builder and the solve", () => {
  const profile = (changes = {}) => profileWith({ weights: { AC: 4, DMG: 100, HASTE: 0 }, softcap: [1000, 0.5], ...changes });
  const options = { any_rule: "explicit" };
  const agiHat = gear("it-ring", ["HEAD"], { stats: { AGI: 60 }, classes: ["WAR"] });
  const acHat = gear("it-plate", ["HEAD"], { stats: { AC: 6 }, classes: ["WAR"] });

  function best(items, setup, changes) {
    const session = createSession({ highs, profile: profile(changes), setup, buffset: null, monkBins: undefined });
    try {
      return solveScenario(session, { name: "main", items, options: { ...options, haste_assumed: null, haste_floor: null, haste_exact: false }, budgetMs: 60_000 });
    } finally {
      closeSession(session);
    }
  }
  const worn = (answer, place) => answer.kit.filter((item, at) => item !== null && SLOT_INSTANCES[at] === place).map((item) => item.key);

  it("makes no agility term of the sheet or the evasion under the stance, and chooses the armor class over the agility", () => {
    const pool = [agiHat, acHat];
    const plain = buildMilp(profile(), pool, "1h-shield", null, { ...options, haste_assumed: 0 });
    const stanced = buildMilp(profile({ stance: STANCE }), pool, "1h-shield", null, { ...options, haste_assumed: 0 });
    expect(plain.col_names.some((name) => /agi/i.test(name))).toBe(true);
    expect(stanced.col_names.some((name) => /agi/i.test(name))).toBe(false);
    expect(worn(best(pool, "1h-shield"), "HEAD")).toEqual(["it-ring"]); // (60 agility is worth more than 6 armor class: 60 x 0.2222 x 4 for the evasion alone)
    expect(worn(best(pool, "1h-shield", { stance: STANCE }), "HEAD")).toEqual(["it-plate"]);
  });
  it("pays a hand the factor: the answer's value is the evaluator's, with and without the stance", () => {
    const hand = gear("it-axe", ["PRIMARY"], { weapon: oneHand(30, 40), classes: ["WAR"] });
    for (const changes of [{}, { stance: STANCE }]) {
      const answer = best([hand], "1h-shield", changes);
      expect(worn(answer, "PRIMARY")).toEqual(["it-axe"]);
      const value = evaluate(profile(changes), answer.kit, null, { setup: "1h-shield", hasteAssumed: answer.haste_assumed ?? 0, monkBins: undefined }).breakdown;
      expect(value.parts.WEAPON.sign()).toBe(1);
    }
  });
});
