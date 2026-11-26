import { describe, expect, it } from "vitest";
import { SLOT_INSTANCES, evaluate } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { damageIndex, readItem } from "../pipeline/trioforge/site/static/engine/model.js";
import { assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { SAMPLE } from "./engine-fixtures.mjs";
import { gear, oneHand, q } from "./engine-hand.mjs";

// The third round of the bow setup in the browser's engine, held to what pipeline/tests/test_ranged_round3.py holds Python to: a bow is scored on its own damage per delay,
// at the haste the kit counts, times the profile's bow factor. The damage bonus that a main hand adds (the bonus its page lists, else half its delay) is not counted for a
// bow, listed or not, and arrow damage never is. Every item here is invented.

const bowOf = (dmg, delay, bonus = null) => ({ skill: "Archery", dmg, delay, bonus, two_handed: false });
const read = (item) => readItem(item, 0);
const RANGE = SLOT_INSTANCES.indexOf("RANGE");

describe("the measure of a bow", () => {
  const arrows = read(gear("it-bow", ["RANGE"], { weapon: bowOf(45, 60) }));
  it("is its damage over its delay at the haste, with no main-hand bonus", () => {
    for (const haste of [0, 25, 100]) {
      expect(damageIndex(arrows, "RANGE", "ranged", haste, q(1)).equals(q(45 * (100 + haste), 60 * 100))).toBe(true);
    }
  });
  it("is the same for a bow that lists a bonus, which a main hand's measure counts", () => {
    const listed = read(gear("it-listed", ["RANGE"], { weapon: bowOf(45, 60, 25) }));
    for (const haste of [0, 10]) expect(damageIndex(listed, "RANGE", "ranged", haste, q(1)).equals(damageIndex(arrows, "RANGE", "ranged", haste, q(1)))).toBe(true);
    const main = read(gear("it-main", ["PRIMARY"], { weapon: oneHand(45, 60, 25) }));
    expect(damageIndex(main, "PRIMARY", "dw", 10, q(1)).equals(q((45 + 25) * 110, 60 * 100))).toBe(true);
  });
  it("is multiplied by the factor", () => {
    expect(damageIndex(arrows, "RANGE", "ranged", 0, q(1), q(3, 4)).equals(q(45 * 3, 60 * 4))).toBe(true);
    expect(damageIndex(arrows, "RANGE", "ranged", 20, q(1), q(2)).equals(q(45 * 120 * 2, 60 * 100))).toBe(true);
  });
});

describe("the evaluator", () => {
  const bundle = readBundle(SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json"));
  const profile = assembleProfile(bundle, { race: "OGR", role: "tank", buffs: "own" });
  it("scores the bow in the range place on its own damage per delay", () => {
    const placed = new Array(SLOT_INSTANCES.length).fill(null);
    placed[RANGE] = gear("it-bow", ["RANGE"], { weapon: bowOf(45, 60) });
    const parts = evaluate(profile, placed, null, { setup: "ranged", hasteAssumed: 20, monkBins: bundle.monk_bins }).breakdown.parts.WEAPON;
    const weight = evaluate({ ...profile, ranged_factor: 2 }, placed, null, { setup: "ranged", hasteAssumed: 20, monkBins: bundle.monk_bins }).breakdown.parts.WEAPON;
    expect(weight.equals(parts.mul(q(2)))).toBe(true);
    const asMain = new Array(SLOT_INSTANCES.length).fill(null);
    asMain[SLOT_INSTANCES.indexOf("PRIMARY")] = gear("it-sword", ["PRIMARY"], { weapon: oneHand(45, 60) });
    const hand = evaluate(profile, asMain, null, { setup: "dw", hasteAssumed: 20, monkBins: bundle.monk_bins }).breakdown.parts.WEAPON;
    // the same damage and delay in a main hand scores (45 + 25) / 60 (T9: the client's bonus at level 50, 0.5 x 50 x 0.8 x 50 / 40) and the bow's 45 / 60: the ratio is 70 to 45
    expect(hand.mul(q(45)).equals(parts.mul(q(70)))).toBe(true);
  });
});
