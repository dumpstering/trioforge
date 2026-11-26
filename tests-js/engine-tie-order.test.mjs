import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { SLOT_INSTANCES } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { MAX_TIED_KITS, closeSession, compareKits, createSession, setScenario, solve } from "../pipeline/trioforge/site/static/engine/solve.js";
import { caseOf, clone, deepFreeze, kitPairs, sharedOf, shuffled } from "./engine-cases.mjs";
import { SAMPLE } from "./engine-fixtures.mjs";
import { buffOf, buffsetOf, gear, profileWith } from "./engine-hand.mjs";
import { spyOn } from "./engine-spy.mjs";

// The last stage of the canonical solve (`_settle_ties` in solve.py): among the kits of the same exact value and the same total rank, the answer is the first in the order of the
// kits, which both engines share: place by place in the order of the 22 places, an item before an empty place and the lower (key, tier) first, then the chosen buffs as sorted lists.
// These tests are the JavaScript side of pipeline/tests/test_solve.py: the same pools and the same answers.

vi.setConfig({ testTimeout: 120_000 });
const BUDGET_MS = 60_000;
const OPTIONS = { any_rule: "explicit", haste_assumed: 0 };

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

/** Fire and cold pieces for the head and the neck, 750 of one resist each, with a cap of 1000 a school: only a fire piece with a cold one reaches 1500. */
const tiedPool = ([headFire, headCold, neckFire, neckCold]) => [
  gear(headFire, ["HEAD"], { sv: { FIRE: 750 } }),
  gear(headCold, ["HEAD"], { sv: { COLD: 750 } }),
  gear(neckFire, ["NECK"], { sv: { FIRE: 750 } }),
  gear(neckCold, ["NECK"], { sv: { COLD: 750 } }),
];
const resists = profileWith({ weights: { SV: 1 }, caps: { regen: { HP: 30, MANA: 15, END: 15 }, resist: 1000 } });
const wornOf = (answer) => Object.fromEntries(answer.kit.flatMap((item, at) => (item === null ? [] : [[SLOT_INSTANCES[at], item.key]])));

function answerFor(profile, pool, setup = "stick", buffset = null, request = {}, solver = highs) {
  const session = createSession({ highs: solver, profile, setup, buffset });
  try {
    setScenario(session, "s", pool, OPTIONS);
    return solve(session, { scenario: "s", budgetMs: BUDGET_MS, canonical: true, ...request });
  } finally {
    closeSession(session);
  }
}

describe("the order of the kits", () => {
  const kit = (...places) => [...places, ...new Array(22 - places.length).fill(null)];
  const item = (key, tier = 0) => ({ key, tier });

  it("compares the places in turn, an item before an empty place, the key as text and then the tier, and the buffs last", () => {
    expect(compareKits(kit(item("a")), [], kit(item("b")), [])).toBeLessThan(0);
    expect(compareKits(kit(item("a", 2)), [], kit(item("a", 0)), [])).toBeGreaterThan(0);
    expect(compareKits(kit(item("a"), null), [], kit(null, item("a")), [])).toBeLessThan(0); // (an item before an empty place)
    expect(compareKits(kit(item("b"), item("a")), [], kit(item("a"), item("c")), [])).toBeGreaterThan(0); // (the first place that differs decides)
    expect(compareKits(kit(item("a")), [1, 4], kit(item("a")), [2, 3])).toBeLessThan(0);
    expect(compareKits(kit(item("a")), [1], kit(item("a")), [1, 2])).toBeLessThan(0); // (a list is before the list it begins)
    expect(compareKits(kit(item("a")), [3], kit(item("a")), [3])).toBe(0);
    expect(compareKits(kit(item("Z")), [], kit(item("a")), [])).toBeLessThan(0); // (by code point, as Python's str compares)
  });
});

describe("kits of the same exact value and the same total rank", () => {
  it.each([
    [["b", "a", "d", "c"], { HEAD: "a", NECK: "d" }], // {b, c} and {a, d} cost 2 + 3 = 1 + 4: the head comes first, and a is before b
    [["c", "a", "d", "b"], { HEAD: "a", NECK: "d" }], // {c, b} and {a, d}: 3 + 2 = 1 + 4
    [["d", "b", "c", "a"], { HEAD: "b", NECK: "c" }], // {d, a} and {b, c}: 4 + 1 = 2 + 3
    [["a", "b", "c", "d"], { HEAD: "a", NECK: "d" }], // {a, d} and {b, c}: 1 + 4 = 2 + 3
  ])("come out as the first in the order of the kits, whatever the order of the pool: %j", (names, first) => {
    const pool = tiedPool(names);
    for (let run = 0; run < 6; run += 1) {
      for (const shortcut of [true, false]) {
        const answer = answerFor(resists, shuffled(pool, run), "stick", null, { tieShortcut: shortcut });
        expect(answer.F.toNumber()).toBe(1500);
        expect(answer.canonical).toBe(true);
        expect(answer.tieStage).toBe("applied");
        expect(wornOf(answer), `${names} run ${run}`).toEqual(first);
      }
    }
  });

  it("are told apart by the buffs when the items are the same: the lower list of ids", () => {
    const four = (ids) => buffsetOf({ optional: ids.map((id) => buffOf(id, { HP: 15 })), conflicts: [[ids[0], ids[1]], [ids[0], ids[2]], [ids[3], ids[1]], [ids[3], ids[2]]], cardinality: 2 });
    const profile = profileWith({ weights: { HP: 1 } });
    // the pairs {1, 2}, {1, 3}, {4, 2} and {4, 3} are refused, so the best are {1, 4} and {2, 3}: 1 + 4 = 2 + 3 in rank
    expect(answerFor(profile, [], "stick", four([1, 2, 3, 4])).buffs).toEqual([1, 4]);
    expect(answerFor(profile, [], "stick", four([5, 6, 7, 8])).buffs).toEqual([5, 8]);
    for (const shortcut of [true, false]) expect(answerFor(profile, [], "stick", four([1, 2, 3, 4]), { tieShortcut: shortcut }).buffs).toEqual([1, 4]);
  });

  it("with a tie of more kits than the last stage sets apart (tiedKits), the answer is the best found and is not called canonical", () => {
    const pool = tiedPool(["b", "a", "d", "c"]);
    const cut = answerFor(resists, pool, "stick", null, { tiedKits: 1, tieShortcut: false });
    expect(cut.tieStage).toBe("applied");
    expect(cut.canonical).toBe(false);
    expect(cut.F.toNumber()).toBe(1500);
    const enough = answerFor(resists, pool, "stick", null, { tiedKits: 2, tieShortcut: false });
    expect(enough.canonical).toBe(true);
    expect(wornOf(enough)).toEqual({ HEAD: "a", NECK: "d" });
    expect(MAX_TIED_KITS).toBe(200);
    expect(() => answerFor(resists, pool, "stick", null, { tiedKits: 0 })).toThrow(/tiedKits/);
    expect(() => answerFor(resists, pool, "stick", null, { tiedKits: 1.5 })).toThrow(/tiedKits/);
  });

  it("a solve of the last stage that does not finish says so, and the best kit it has stands", () => {
    let runs = 0;
    const timeLimit = highs.constants.modelStatus.timeLimit;
    const { highs: spied } = spyOn(highs, {
      outcome: (result) => {
        runs += 1;
        return runs === 3 ? { ...result, modelStatus: timeLimit } : result; // the first stage, the tie stage, then the proof that nothing more ties
      },
      info: (key, value) => (runs === 3 && key === "primal_solution_status" ? highs.constants.solutionStatus.none : value),
    });
    const answer = answerFor(resists, tiedPool(["b", "a", "d", "c"]), "stick", null, { tieShortcut: false }, spied);
    expect(runs).toBe(3);
    expect(answer.tieStage).toBe("applied");
    expect(answer.canonical).toBe(false);
    expect(answer.F.toNumber()).toBe(1500);
  });

  it("each solve of the last stage has the whole allowance of the call", () => {
    let now = 0;
    const spied = spyOn(highs, { clock: () => now, before: () => { now += 300; } });
    const session = createSession({ highs: spied.highs, profile: resists, setup: "stick", buffset: null, now: () => now });
    try {
      setScenario(session, "s", tiedPool(["b", "a", "d", "c"]), OPTIONS);
      const answer = solve(session, { scenario: "s", budgetMs: 1000, canonical: true, tieShortcut: false });
      expect(answer.canonical).toBe(true);
      // the first stage, the tie stage, the solve that finds the other kit, and the solve that proves there is no third
      expect(spied.log.limits.map((limit) => limit.limitMs)).toEqual([1000, 1000, 1000, 1000]);
    } finally {
      closeSession(session);
    }
  });
});

describe("the committed sample, every worn item given a twin of the same stats (more sets of items of one value)", () => {
  const shared = sharedOf(SAMPLE);

  it("gives the same canonical kit whatever the order of the pool, with the shortcut and without", () => {
    let looked = 0;
    for (const path of SAMPLE.paths("case", "brute/").slice(0, 20)) {
      const doc = SAMPLE.read(path);
      const c = caseOf(shared, doc);
      const [recorded] = doc.solves;
      const options = deepFreeze(clone(recorded.options));
      const pool = c.poolOf(recorded);
      const session = createSession({ highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins });
      try {
        setScenario(session, "alone", pool, options);
        const alone = solve(session, { scenario: "alone", budgetMs: BUDGET_MS, canonical: true });
        if (alone.kit === null) continue;
        const worn = new Set(alone.kit.filter((found) => found !== null).map((found) => `${found.key}@${found.tier}`));
        const twins = pool.filter((found) => worn.has(`${found.key}@${found.tier}`)).map((found) => ({ ...found, key: `${found.key}~twin` }));
        const both = [...pool, ...twins];
        const answers = [];
        for (let run = 0; run < 3; run += 1) {
          for (const shortcut of [true, false]) {
            setScenario(session, "tied", shuffled(both, run), options);
            const answer = solve(session, { scenario: "tied", budgetMs: BUDGET_MS, canonical: true, tieShortcut: shortcut });
            expect(answer.canonical, doc.id).toBe(true);
            answers.push([JSON.stringify(kitPairs(answer.kit)), answer.buffs, answer.F.toString()]);
          }
        }
        looked += 1;
        for (const answer of answers) expect(answer, doc.id).toEqual(answers[0]);
      } finally {
        closeSession(session);
      }
    }
    expect(looked).toBeGreaterThan(0);
  });
});
