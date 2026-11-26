import loadHighs from "highs";
import { beforeAll, describe, expect, it } from "vitest";
import { CONSTANTS, SLOT_INSTANCES, evaluate } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { allowedInHand, buildMilp, damageIndex, isBow, readItem } from "../pipeline/trioforge/site/static/engine/model.js";
import { fitGroups, prune } from "../pipeline/trioforge/site/static/engine/prune.js";
import { assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { closeSession, createSession, solveScenario } from "../pipeline/trioforge/site/static/engine/solve.js";
import { SAMPLE } from "./engine-fixtures.mjs";
import { gear, oneHand, profileWith, q, twoHand } from "./engine-hand.mjs";

// The bow setup ("ranged") in the browser's engine, held to what pipeline/tests/test_ranged.py holds Python to: in the setup the range place takes a bow and
// only a bow, the bow is scored as a main hand is (the damage and the bonus over the delay, at the haste the kit counts) times the profile's ranged factor, the
// two hands score nothing, and in every other setup the range place scores nothing. Every item here is invented; the numbers are worked out by hand.

const RANGE = SLOT_INSTANCES.indexOf("RANGE");
const PRIMARY = SLOT_INSTANCES.indexOf("PRIMARY");
const bowOf = (dmg, delay, bonus = null, skill = "Archery") => ({ skill, dmg, delay, bonus, two_handed: false });
const bow = (key, dmg, delay, more = {}) => gear(key, ["RANGE"], { classes: ["RNG"], weapon: bowOf(dmg, delay, more.bonus ?? null, more.skill), ...more });
const read = (item) => readItem(item, 0);

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

describe("the vocabulary", () => {
  it("has the setup, last of the setups, and the Ranged role in the bundle reader", () => {
    expect(CONSTANTS.setups).toEqual([null, "1h-shield", "2h", "dw", "stick", "ranged"]);
    const bundle = SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json");
    expect(Object.keys(bundle.profile_common)).toContain("ranged_factor");
    expect(readBundle(bundle).profile_common.ranged_factor).toBe(1);
  });
  it("names the skill of a bow as the bundle does, in any case", () => {
    const bundle = SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json");
    expect(bundle.weapon_rules.bow_skill).toBe("Archery");
    expect(isBow(read(bow("it-a", 10, 30)))).toBe(true);
    expect(isBow(read(bow("it-b", 10, 30, { skill: "archery" })))).toBe(true);
    expect(isBow(read(bow("it-c", 10, 30, { skill: "Throwing" })))).toBe(false);
    expect(isBow(read(gear("it-d", ["PRIMARY"], { weapon: bowOf(10, 30) })))).toBe(false); // no range place
    expect(isBow(read(bow("it-e", 0, 30)))).toBe(false); // no damage
    expect(isBow(read(gear("it-f", ["RANGE"], { stats: { HP: 5 } })))).toBe(false);
  });
});

describe("the hands and the range place", () => {
  const sword = read(gear("it-sword", ["PRIMARY", "SECONDARY"], { weapon: oneHand(20, 30) }));
  const axe = read(gear("it-axe", ["PRIMARY"], { weapon: twoHand(30, 40) }));
  const orb = read(gear("it-orb", ["PRIMARY", "SECONDARY", "RANGE"], { stats: { HP: 10 } }));
  const arrows = read(bow("it-bow", 20, 40));
  const thrown = read(gear("it-spear", ["RANGE"], { weapon: bowOf(9, 30, null, "Throwing") }));

  it("takes anything in the hands, a two-hander never in the off hand, and only a bow in the range place", () => {
    for (const hand of ["PRIMARY", "SECONDARY"]) {
      expect(allowedInHand(sword, hand, "ranged")).toBe(true);
      expect(allowedInHand(orb, hand, "ranged")).toBe(true);
    }
    expect(allowedInHand(axe, "PRIMARY", "ranged")).toBe(true);
    expect(allowedInHand(axe, "SECONDARY", "ranged")).toBe(false);
    expect(allowedInHand(arrows, "RANGE", "ranged")).toBe(true);
    for (const other of [orb, sword, thrown]) expect(allowedInHand(other, "RANGE", "ranged")).toBe(false);
    for (const setup of ["1h-shield", "2h", "dw", "stick"]) expect(allowedInHand(orb, "RANGE", setup) && allowedInHand(thrown, "RANGE", setup)).toBe(true);
  });

  it("scores a bow on its own damage per delay, times the factor, at the haste, and nothing else (no main-hand bonus: ranged-round3.test.mjs holds the measure)", () => {
    for (const haste of [0, 25, 75]) {
      expect(damageIndex(arrows, "RANGE", "ranged", haste, q(1)).equals(q(20 * (100 + haste), 40 * 100))).toBe(true);
    }
    expect(damageIndex(arrows, "RANGE", "ranged", 0, q(1)).equals(q(20, 40))).toBe(true); // no bonus, whatever the delay
    expect(damageIndex(arrows, "RANGE", "ranged", 0, q(1), q(3, 4)).equals(q(20 * 3, 40 * 4))).toBe(true);
    expect(damageIndex(read(bow("it-b", 20, 40, { bonus: 9 })), "RANGE", "ranged", 0, q(1)).equals(q(20, 40))).toBe(true); // a listed bonus is not counted either
    for (const hand of ["PRIMARY", "SECONDARY"]) {
      expect(damageIndex(sword, hand, "ranged", 10, q(1)).sign()).toBe(0);
      expect(damageIndex(arrows, hand, "ranged", 10, q(1)).sign()).toBe(0);
    }
    for (const setup of ["1h-shield", "2h", "dw", "stick"]) expect(damageIndex(arrows, "RANGE", setup, 10, q(1)).sign()).toBe(0);
  });
});

describe("the evaluator", () => {
  const bundle = readBundle(SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json"));
  const profile = assembleProfile(bundle, { race: "OGR", role: "tank", buffs: "own" });
  const monkBins = bundle.monk_bins;
  const kit = (...entries) => {
    const places = new Array(SLOT_INSTANCES.length).fill(null);
    for (const [place, item] of entries) places[place] = item;
    return places;
  };

  it("scores the bow in the range place under the setup and nothing under the others", () => {
    const arrows = gear("it-bow", ["RANGE"], { weapon: bowOf(20, 40) });
    const sword = gear("it-sword", ["PRIMARY"], { weapon: oneHand(40, 30) });
    const placed = kit([RANGE, arrows], [PRIMARY, sword]);
    const ranged = evaluate(profile, placed, null, { setup: "ranged", hasteAssumed: 20, monkBins });
    const stick = evaluate(profile, placed, null, { setup: "stick", hasteAssumed: 20, monkBins });
    const per = (result) => result.breakdown.parts.WEAPON;
    expect(per(stick).sign()).toBe(0);
    expect(per(ranged).sign()).toBeGreaterThan(0);
    // the same damage and delay in a main hand of the dual-wield setup scores (20 + 20) / 40, the main hand's bonus counted, and the bow's 20 / 40 is half of it
    const asHand = evaluate(profile, kit([PRIMARY, gear("it-b2", ["PRIMARY"], { weapon: oneHand(20, 40) })]), null, { setup: "dw", hasteAssumed: 20, monkBins });
    expect(per(asHand).equals(per(ranged).mul(q(2)))).toBe(true);
    // a sword in the range place is no bow
    const odd = evaluate(profile, kit([RANGE, gear("it-sw", ["RANGE"], { weapon: oneHand(40, 30) })]), null, { setup: "ranged", hasteAssumed: 20, monkBins });
    expect(per(odd).sign()).toBe(0);
  });

  it("reads the factor from the profile, and a profile without one has 1", () => {
    const arrows = gear("it-bow", ["RANGE"], { weapon: bowOf(20, 40) });
    const placed = kit([RANGE, arrows]);
    const one = evaluate(profile, placed, null, { setup: "ranged", hasteAssumed: 0, monkBins }).breakdown.parts.WEAPON;
    const twice = evaluate({ ...profile, ranged_factor: 2 }, placed, null, { setup: "ranged", hasteAssumed: 0, monkBins }).breakdown.parts.WEAPON;
    const without = Object.fromEntries(Object.entries(profile).filter(([name]) => name !== "ranged_factor"));
    expect(twice.equals(one.mul(q(2)))).toBe(true);
    expect(evaluate(without, placed, null, { setup: "ranged", hasteAssumed: 0, monkBins }).breakdown.parts.WEAPON.equals(one)).toBe(true);
  });
});

describe("the builder, the pruning and the solve", () => {
  const profile = (changes = {}) => profileWith({ weights: { HP: 1, DMG: 600 }, ...changes });
  const stat = gear("it-charm", ["RANGE"], { stats: { HP: 120 }, classes: ["WAR"] });
  const low = bow("it-low", 20, 40, { stats: { HP: 10 }, classes: ["WAR"] });
  const high = bow("it-high", 33, 40, { stats: { HP: 10 }, classes: ["WAR"] });
  const options = { any_rule: "explicit" };

  function best(items, setup, changes) {
    const session = createSession({ highs, profile: profile(changes), setup, buffset: null, monkBins: undefined });
    try {
      return solveScenario(session, { name: "main", items, options: { ...options, haste_assumed: null, haste_floor: null, haste_exact: false }, budgetMs: 60_000 });
    } finally {
      closeSession(session);
    }
  }
  const worn = (answer, place) => answer.kit.filter((item, at) => item !== null && SLOT_INSTANCES[at] === place).map((item) => item.key);

  it("holds only a bow in the range place and chooses it for its damage, where the other setups choose the stat item", () => {
    const pool = [stat, low, high];
    const model = buildMilp(profile(), pool, "ranged", null, { ...options, haste_assumed: 0 });
    expect(model.col_names.some((name) => name.startsWith("n[RANGE|it-charm"))).toBe(false);
    expect(model.col_names.some((name) => name.startsWith("n[RANGE|it-high"))).toBe(true);
    expect(worn(best(pool, "ranged"), "RANGE")).toEqual(["it-high"]);
    for (const setup of ["stick", "2h", "dw", "1h-shield"]) expect(worn(best(pool, setup), "RANGE")).toEqual(["it-charm"]);
  });

  it("prefers the bow with more damage per delay, whatever its damage, and a bow with stats when they are worth more", () => {
    expect(worn(best([bow("it-slow", 45, 100, { classes: ["WAR"] }), bow("it-quick", 24, 40, { classes: ["WAR"] })], "ranged"), "RANGE")).toEqual(["it-quick"]);
    expect(worn(best([bow("it-damage", 40, 40, { classes: ["WAR"] }), bow("it-stats", 36, 40, { stats: { HP: 2000 }, classes: ["WAR"] })], "ranged"), "RANGE")).toEqual(["it-stats"]);
  });

  it("pays the bow the haste the kit counts", () => {
    const boots = gear("it-boots", ["FEET"], { haste: 30, classes: ["WAR"] });
    const answer = best([bow("it-bow", 20, 40, { stats: { HP: 3 }, classes: ["WAR"] }), boots], "ranged", { haste_cap: 75 });
    expect(worn(answer, "FEET")).toEqual(["it-boots"]);
  });

  it("keeps the range place to bows in the grouping and the pruning, and drops a bow that another beats", () => {
    expect([...fitGroups(bow("it-a", 30, 40), "ranged", "explicit")]).toEqual(["RANGE"]);
    expect([...fitGroups(gear("it-c", ["RANGE"], { stats: { HP: 3 } }), "ranged", "explicit")]).toEqual([]);
    expect([...fitGroups(gear("it-c", ["RANGE"], { stats: { HP: 3 } }), "stick", "explicit")]).toEqual(["RANGE"]);
    const items = [bow("it-a", 30, 40, { classes: ["WAR"] }), bow("it-b", 30, 40, { stats: { HP: 4 }, classes: ["WAR"] }), bow("it-c", 20, 40, { stats: { HP: 9 }, classes: ["WAR"] }), bow("it-d", 10, 40, { classes: ["WAR"] })];
    const kept = prune(items, profile(), 0, "ranged", null, { any_rule: "explicit", haste_assumed: 0 }).map((item) => item.key);
    expect(kept).not.toContain("it-d");
    expect(kept).toContain("it-b");
  });
});
