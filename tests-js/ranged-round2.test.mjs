import loadHighs from "highs";
import { beforeAll, describe, expect, it } from "vitest";
import { SLOT_INSTANCES } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { buildMilp } from "../pipeline/trioforge/site/static/engine/model.js";
import { assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { closeSession, createSession, solveScenario } from "../pipeline/trioforge/site/static/engine/solve.js";
import { SAMPLE } from "./engine-fixtures.mjs";
import { gear, profileWith } from "./engine-hand.mjs";

// The second round of the bow setup in the browser's engine, held to what pipeline/tests/test_ranged_round2.py holds Python to: in the bow setup the range place is
// always filled (the row range.bow: a bow is forced into it, even when damage is worth nothing, and a pool with no bow for it is refused), and the bundle may list no
// setup for a role at an evidence level (the Ranged role plays the bow and nothing else, so a pool with no bow does not offer it). Every item here is invented.

const bowOf = (dmg, delay) => ({ skill: "Archery", dmg, delay, bonus: null, two_handed: false });
const bow = (key, dmg, delay, more = {}) => gear(key, ["RANGE"], { classes: ["WAR"], weapon: bowOf(dmg, delay), ...more });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

describe("the range place of the bow setup is filled", () => {
  const options = { any_rule: "explicit" };
  const low = bow("it-low", 20, 40);
  const high = bow("it-high", 33, 40);
  const ring = gear("it-ring", ["FINGER"], { stats: { HP: 30 }, classes: ["WAR"] });

  function best(items, setup, weights) {
    const session = createSession({ highs, profile: profileWith({ weights }), setup, buffset: null, monkBins: undefined });
    try {
      return solveScenario(session, { name: "main", items, options: { ...options, haste_assumed: null, haste_floor: null, haste_exact: false }, budgetMs: 60_000 });
    } finally {
      closeSession(session);
    }
  }
  const worn = (answer, place) => answer.kit.filter((item, at) => item !== null && SLOT_INSTANCES[at] === place).map((item) => item.key);

  it("puts a bow in it when damage is worth nothing, and the better bow when it is worth something", () => {
    for (const weights of [{ HP: 1, DMG: 0 }, { HP: 1 }]) {
      const answer = best([low, high, ring], "ranged", weights);
      expect(worn(answer, "RANGE")).toHaveLength(1);
      expect(["it-low", "it-high"]).toContain(worn(answer, "RANGE")[0]);
    }
    expect(worn(best([low, high, ring], "ranged", { HP: 1, DMG: 600 }), "RANGE")).toEqual(["it-high"]);
  });

  it("has the row that fills it in the bow setup and in no other", () => {
    for (const setup of ["stick", "2h", "dw", "1h-shield"]) {
      expect(buildMilp(profileWith({ weights: { HP: 1 } }), [low, ring], setup, null, { ...options, haste_assumed: 0 }).row_names).not.toContain("range.bow");
    }
    expect(buildMilp(profileWith({ weights: { HP: 1 } }), [low, ring], "ranged", null, { ...options, haste_assumed: 0 }).row_names).toContain("range.bow");
  });

  it("refuses the bow setup when no bow fits the range place", () => {
    const charm = gear("it-charm", ["RANGE"], { stats: { HP: 30 }, classes: ["WAR"] });
    for (const pool of [[ring], [ring, charm]]) {
      expect(() => buildMilp(profileWith({ weights: { HP: 1 } }), pool, "ranged", null, { ...options, haste_assumed: 0 })).toThrow(/bow/);
    }
  });
});

describe("a role with no setup at an evidence level", () => {
  const bundle = JSON.parse(JSON.stringify(SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json")));
  const [role] = Object.keys(bundle.roles);

  it("is read, and its profile is refused at that level and made at the others", () => {
    bundle.roles[role].setups_by_evidence.strict = [];
    const read = readBundle(bundle);
    expect(() => assembleProfile(read, { race: "OGR", role, buffs: "own", evidence: "strict" })).toThrow(/not offered/);
    expect(assembleProfile(read, { race: "OGR", role, buffs: "own", evidence: "wiki" }).setups.length).toBeGreaterThan(0);
    expect(assembleProfile(read, { race: "OGR", role, buffs: "own" }).setups.length).toBeGreaterThan(0); // (with no level: the setups of a profile with no pool)
  });
});
