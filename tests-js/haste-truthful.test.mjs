import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { SLOT_INSTANCES, evaluate, evaluateTruthful } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { compare } from "../pipeline/trioforge/site/static/engine/milpjson.js";
import { LevelPrograms, buildMilp, hasteLevels } from "../pipeline/trioforge/site/static/engine/model.js";
import { LABEL_NO_INCUMBENT } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { closeSession, createSession, programName, programsOf, setScenario, solve, solveScenario } from "../pipeline/trioforge/site/static/engine/solve.js";
import { caseOf, clone, deepFreeze, exact, kitPairs, sharedOf } from "./engine-cases.mjs";
import { spyOn } from "./engine-spy.mjs";
import { SAMPLE, describeFull } from "./engine-fixtures.mjs";
import { buffOf, buffsetOf, gear, oneHand, profileWith } from "./engine-hand.mjs";

// The weapon term is paid the haste the kit counts (solve.js `solveScenario`, model.js `hasteLevels` and the row `haste.floor`), held to Python (pipeline/trioforge/solver/haste.py):
//
//   * Parity. For every solve of the parity fixtures that records its levels (`haste` is not null: the scenarios of matrix/, pmb36/ and upgrade/, and the truthful instances of brute/): the
//     levels a kit can count are Python's, and the truthful solve of the scenario (the options with no haste fixed) gives the exact value, the kit place for place, the buffs, the haste the kit
//     counts and the level whose program won that Python found, and the program of that level is the model Python built (the row `haste.floor` included).
//   * By hand. A haste belt that the old rule rejected is taken; a trio whose spell haste is at the cap has one level; a haste the options fix is one program; the relaxation bound leaves out only
//     levels that cannot win; a scenario that scores no weapon has one program; `needTime` starts nothing when the time is gone once the model is made.

vi.setConfig({ testTimeout: 120_000 });
const BUDGET_MS = 600_000;

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const sessionFor = (c, extra = {}) => createSession({ highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins, ...extra });
/** The options of a recorded program with no haste fixed: what the scenario was asked with. */
const scenarioOptions = (recorded) => ({ ...clone(recorded.options), haste_assumed: null, haste_floor: null, haste_exact: false });

// ---- parity with Python --------------------------------------------------------------------------------------------------------------------

function parityTests(set, families) {
  const shared = sharedOf(set);
  for (const family of families) {
    const paths = set.paths("case", `${family}/`);
    describe(`${family}/`, () => {
      for (const path of paths) {
        const doc = set.read(path);
        const truthful = doc.solves.filter((recorded) => recorded.haste !== null);
        if (truthful.length === 0) continue;
        it(`${doc.id} (${doc.label}): the levels, the winning level and the truthful answer of ${truthful.length === 1 ? "its solve" : "each of its solves"} are Python's`, () => {
          const c = caseOf(shared, doc);
          const session = sessionFor(c);
          try {
            for (const recorded of truthful) {
              const label = `${doc.id} ${recorded.label}`;
              const options = scenarioOptions(recorded);
              const items = c.poolOf(recorded);
              const scoresWeapons = c.setup !== null && c.setup !== "stick" && Number(c.profile.weights.DMG) !== 0;
              // (a scenario that scores no weapon has one program, at the haste its kit counts: the levels a kit could count are not looked at)
              if (scoresWeapons) expect(hasteLevels(c.profile, items, c.setup, c.buffset, c.withBins(options)), `${label}: the levels`).toEqual(recorded.haste.levels);
              else expect(recorded.haste.levels, `${label}: one program`).toEqual([recorded.haste.level]);
              const answer = solveScenario(session, { name: recorded.label, items, options: deepFreeze(clone(options)), budgetMs: BUDGET_MS, canonical: true });
              const want = recorded.result;
              expect(answer.status, label).toBe("optimal");
              expect(answer.levels, `${label}: the levels of the answer`).toEqual(recorded.haste.levels);
              expect(answer.level, `${label}: the level that won`).toBe(recorded.haste.level);
              expect(answer.hasteAssumed, `${label}: the haste the kit counts`).toBe(want.haste_assumed);
              expect(answer.F.toString(), `${label}: F`).toBe(exact(want.F).toString());
              expect(kitPairs(answer.kit), `${label}: the kit, place for place`).toEqual(want.kit);
              expect(answer.buffs, `${label}: the buffs`).toEqual(want.buffs);
              // every level's program, made from the one shared build, is the model the builder makes for it (to the last bit), whatever the level
              if (scoresWeapons) {
                const withBins = c.withBins(options);
                const programs = new LevelPrograms(c.profile, items, c.setup, c.buffset, withBins);
                for (const level of programs.levels) {
                  const direct = buildMilp(c.profile, items, c.setup, c.buffset, { ...withBins, haste_assumed: level, haste_floor: level, haste_exact: true });
                  expect(compare(programs.programFor(level), direct), `${label}: the shared build at level ${level}`).toEqual([]);
                  expect(JSON.stringify(programs.programFor(level)) === JSON.stringify(direct), `${label}: the document at level ${level} is the builder's to the last bit`).toBe(true);
                }
              }
              // the program of the winning level is the model Python built
              expect(compare(session.scenarios.get(answer.program).model, recorded.model).slice(0, 5), `${label}: the model`).toEqual([]);
              // and the value is the evaluator's at the haste the kit counts
              const options2 = { setup: c.setup, monkBins: c.bins, buffset: c.buffset ?? undefined };
              const kitValue = evaluateTruthful(c.profile, answer.kit, c.buffset === null ? null : answer.buffs, options2);
              expect(kitValue.F.toString(), `${label}: the truthful value of the kit`).toBe(answer.F.toString());
              expect(Number(kitValue.breakdown.totals.haste.counted.floor())).toBe(answer.hasteAssumed);
              // evaluateTruthful values the kit once; it is the evaluation at the haste the kit counts, to the last bit (F and every part)
              const twice = evaluate(c.profile, answer.kit, c.buffset === null ? null : answer.buffs, { ...options2, hasteAssumed: kitValue.breakdown.totals.haste.counted });
              expect(kitValue.F.toString(), `${label}: F, valued once`).toBe(twice.F.toString());
              expect(Object.entries(kitValue.breakdown.parts).map(([name, part]) => [name, part.toString()]), `${label}: the parts, valued once`).toEqual(
                Object.entries(twice.breakdown.parts).map(([name, part]) => [name, part.toString()]),
              );
              if (family === "brute") expect(answer.F.toString(), `${label}: the brute-force maximum`).toBe(exact(doc.expected.brute_F).toString());
            }
          } finally {
            closeSession(session);
          }
        }, 300_000);
      }
    });
  }
}

describe("the committed sample", () => parityTests(SAMPLE, ["matrix", "pmb36", "upgrade", "brute"]));
describeFull("the full set", (full) => parityTests(full, ["matrix", "pmb36", "upgrade", "brute"]));

// ---- by hand -------------------------------------------------------------------------------------------------------------------------------

const SWORD = gear("sword", ["PRIMARY", "SECONDARY"], { weapon: oneHand(20, 30) });
const HAND = { any_rule: "explicit" };
const placeOf = (answer, place) => answer.kit.flatMap((item, at) => (item !== null && SLOT_INSTANCES[at] === place ? [item.key] : []));
/** The weapons are worth about 510 more at 30 percent haste; the stat belt is worth about 94. */
const beltPool = () => [gear("sash", ["WAIST"], { stats: { STA: 10 } }), gear("belt", ["WAIST"], { haste: 30 }), SWORD];

describe("the levels", () => {
  const level = (profile, items, buffset = null, options = HAND) => hasteLevels(profile, items, "stick", buffset, options);

  it("are every spell haste crossed with no worn haste and each distinct worn value, cut at the cap, each once", () => {
    const buffset = buffsetOf({ always: [buffOf(900, { HASTE: 5 })], optional: [buffOf(1, { HASTE: 30 }), buffOf(2, { HASTE: 40 })], conflicts: [[1, 2]] });
    const items = [gear("boots", ["FEET"], { haste: 15 }), gear("belt", ["WAIST"], { haste: 25 }), gear("cap", ["HEAD"], { haste: 15 })];
    expect(level(profileWith({ haste_cap: 75, buff_totals: { HASTE: 5 } }), items, buffset)).toEqual([5, 20, 30, 40, 45, 55, 65]);
    const capped = buffsetOf({ optional: [buffOf(1, { HASTE: 30 }), buffOf(2, { HASTE: 45 })], conflicts: [[1, 2]] });
    expect(level(profileWith({ haste_cap: 60 }), [gear("belt", ["WAIST"], { haste: 30 }), gear("cloak", ["BACK"], { haste: 45 })], capped)).toEqual([0, 30, 45, 60]);
  });

  it("have the flat haste of Unbound Alacrity in every spell haste", () => {
    const buffset = buffsetOf({ optional: [buffOf(1, { HASTE: 40 })] });
    expect(level(profileWith({ haste_cap: 85, haste_bonus: 10 }), [gear("belt", ["WAIST"], { haste: 25 })], buffset)).toEqual([10, 35, 50, 75]);
  });

  it("leave out a slow item and an item with no place, and a spell haste at the cap leaves one level", () => {
    expect(level(profileWith(), [gear("anchor", ["FEET"], { haste: -20 }), gear("nowhere", [], { haste: 30 })])).toEqual([0]);
    expect(level(profileWith({ haste_cap: 75, buff_totals: { HASTE: 80 } }), [gear("belt", ["WAIST"], { haste: 25 })])).toEqual([75]);
  });
});

describe("the row that the kit counts at least that haste", () => {
  const prof = profileWith({ weights: { HP: 1 }, haste_cap: 75 });

  it("is in the program when the floor is above what the buffs alone give, is named haste.floor and is told in the info", () => {
    const items = [gear("belt", ["WAIST"], { haste: 30 }), gear("sash", ["WAIST"], { stats: { STA: 50 } })];
    const free = buildMilp(prof, items, "stick", null, { ...HAND, haste_assumed: 0 });
    expect(free.row_names).not.toContain("haste.floor");
    expect(free.info.haste_floor).toBeUndefined();
    const forced = buildMilp(prof, items, "stick", null, { ...HAND, haste_assumed: 30, haste_floor: 30 });
    expect(forced.row_names).toContain("haste.floor");
    expect(forced.info.haste_floor).toBe(30);
    const plain = buildMilp(prof, items, "stick", null, { ...HAND, haste_assumed: 0, haste_floor: 0 });
    expect(plain.row_names).not.toContain("haste.floor"); // (nothing above the base to demand)
    expect(plain.info.haste_floor).toBe(0);
  });

  it("is refused above the cap, and a floor with no haste weight still has the columns it needs", () => {
    expect(() => buildMilp(prof, [gear("belt", ["WAIST"], { haste: 20 })], "stick", null, { ...HAND, haste_assumed: 80, haste_floor: 80 })).toThrow(/above the haste cap/);
    expect(() => buildMilp(prof, [], "stick", null, { ...HAND, haste_floor: -1 })).toThrow(/haste_floor/);
    const weapons = profileWith({ weights: { DMG: 5 }, haste_cap: 75 });
    const model = buildMilp(weapons, [gear("belt", ["WAIST"], { haste: 30 })], "dw", null, { ...HAND, haste_assumed: 30, haste_floor: 30 });
    expect(model.col_names).toContain("haste.q");
    expect(model.row_names).toContain("haste.floor");
  });

  it("counts an optional haste buff and Unbound Alacrity", () => {
    const withBonus = profileWith({ weights: { HP: 1 }, haste_cap: 85, haste_bonus: 10 });
    const buffset = buffsetOf({ optional: [buffOf(1, { HASTE: 40, STA: 5 })] });
    const model = buildMilp(withBonus, [gear("belt", ["WAIST"], { haste: 25 })], "stick", buffset, { ...HAND, haste_assumed: 75, haste_floor: 75 });
    // the floor row: the buff adds 40 to the 10 of Unbound Alacrity, the belt (up to the room left) the rest
    const at = model.row_names.indexOf("haste.floor");
    expect(at).toBeGreaterThanOrEqual(0);
    expect(model.row_lb[at]).toBe(65);
    expect(model.row_ub[at]).toBeNull();
  });
});

describe("the truthful solve by hand", () => {
  const prof = () => profileWith({ weights: { DMG: 1000, HP: 1 } });
  const make = (profile = prof(), setup = "dw", extra = {}) => createSession({ highs, profile, setup, ...extra });

  it("takes a haste belt that the old rule rejected: the weapons were paid its 30 whether or not the kit wore it", () => {
    const old = make();
    const fresh = make();
    try {
      // the builder with no haste fixed assumes the 30 of the best item of the pool for every kit
      setScenario(old, "old", beltPool(), HAND);
      expect(old.scenarios.get("old").model.info.haste_assumed).toBe(30);
      const oldKit = solve(old, { scenario: "old", budgetMs: BUDGET_MS, canonical: true });
      expect(placeOf(oldKit, "WAIST")).toEqual(["sash"]);
      const got = solveScenario(fresh, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS, canonical: true });
      expect(got.status).toBe("optimal");
      expect(placeOf(got, "WAIST")).toEqual(["belt"]);
      expect(got.hasteAssumed).toBe(30);
      expect(got.level).toBe(30);
      // the old kit, valued at the haste it counts, is worth less, and its shown value was above that
      const truth = evaluateTruthful(prof(), oldKit.kit, null, { setup: "dw" });
      expect(truth.F.compare(got.F)).toBeLessThan(0);
      expect(oldKit.F.compare(truth.F)).toBeGreaterThan(0);
      // the value is the evaluator's at the haste the kit counts
      expect(got.F.toString()).toBe(evaluate(prof(), got.kit, null, { setup: "dw", hasteAssumed: 30 }).F.toString());
      expect(programsOf(fresh, "main").length).toBeGreaterThan(0);
    } finally {
      closeSession(old);
      closeSession(fresh);
    }
  });

  it("with a floor looks only for a kit worth it: the best at the floor, no kit above it, over the levels and for one program (R14)", () => {
    const session = make();
    try {
      const best = solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS });
      const value = best.F.toNumber();
      expect(best.levels.length).toBeGreaterThan(1);
      // a floor at the best value: the best kit, found as without a floor
      const at = solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS, floor: value });
      expect(at.status).toBe("optimal");
      expect(at.F.toString()).toBe(best.F.toString());
      // a floor above it: no kit is worth it, and the answer says so (no kit, proven)
      const above = solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS, floor: value + 1 });
      expect(above.status).toBe("infeasible");
      expect(above.kit).toBeNull();
      expect(above.proven).toBe(true);
      // and for a program with a haste fixed (one program, no levels)
      const fixed = solveScenario(session, { name: "one", items: beltPool(), options: { ...HAND, haste_assumed: 0 }, budgetMs: BUDGET_MS });
      const same = solveScenario(session, { name: "one", items: beltPool(), options: { ...HAND, haste_assumed: 0 }, budgetMs: BUDGET_MS, floor: fixed.F.toNumber() });
      expect(same.status).toBe("optimal");
      expect(same.F.toString()).toBe(fixed.F.toString());
      const none = solveScenario(session, { name: "one", items: beltPool(), options: { ...HAND, haste_assumed: 0 }, budgetMs: BUDGET_MS, floor: fixed.F.toNumber() + 1 });
      expect(none.status).toBe("infeasible");
      expect(none.kit).toBeNull();
      for (const bad of ["x", null, Number.NaN, Number.POSITIVE_INFINITY]) {
        expect(() => solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: 1, floor: bad }), String(bad)).toThrow(/floor/);
      }
    } finally {
      closeSession(session);
    }
  });

  it("has one level when the spell haste is at the cap, and the kit is the one program's", () => {
    const profile = profileWith({ weights: { DMG: 1000, HP: 1, AC: 2 }, buff_totals: { HASTE: 80 }, haste_cap: 75 });
    const items = [gear("sash", ["WAIST"], { stats: { AC: 30 } }), gear("belt", ["WAIST"], { haste: 30, stats: { AC: 5 } }), SWORD];
    const session = make(profile);
    const old = make(profile);
    try {
      const got = solveScenario(session, { name: "main", items, options: HAND, budgetMs: BUDGET_MS, canonical: true });
      expect(got.levels).toEqual([75]);
      expect(got.runs).toHaveLength(1);
      expect(session.scenarios.get(got.program).model.row_names).not.toContain("haste.floor");
      setScenario(old, "old", items, HAND);
      const one = solve(old, { scenario: "old", budgetMs: BUDGET_MS, canonical: true });
      expect(kitPairs(got.kit)).toEqual(kitPairs(one.kit));
      expect(got.F.toString()).toBe(one.F.toString());
      expect(got.hasteAssumed).toBe(75);
    } finally {
      closeSession(session);
      closeSession(old);
    }
  });

  it("is one program at the constant when the options fix a haste, and the belt is not taken at 0 percent", () => {
    const session = make();
    try {
      const got = solveScenario(session, { name: "main", items: beltPool(), options: { ...HAND, haste_assumed: 0 }, budgetMs: BUDGET_MS, canonical: true });
      expect(got.levels).toEqual([0]);
      expect(got.hasteAssumed).toBe(0);
      expect(got.program).toBe("main");
      expect(placeOf(got, "WAIST")).toEqual(["sash"]);
      expect(() => solveScenario(session, { name: "main", items: beltPool(), options: { ...HAND, haste_floor: 10 }, budgetMs: BUDGET_MS })).toThrow(/haste_floor needs haste_assumed/);
    } finally {
      closeSession(session);
    }
  });

  it("takes an optional haste buff for the weapons, with the belt for the room it leaves", () => {
    const profile = profileWith({ weights: { DMG: 1000, HP: 1 }, haste_cap: 85, haste_bonus: 10 });
    const buffset = buffsetOf({ optional: [buffOf(1, { HASTE: 40 }), buffOf(2, { HASTE: 20, STA: 4 })], conflicts: [[1, 2]] });
    const session = make(profile, "dw", { buffset });
    try {
      const got = solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS, canonical: true });
      expect(got.buffs).toEqual([1]);
      expect(placeOf(got, "WAIST")).toEqual(["belt"]);
      expect(got.hasteAssumed).toBe(80); // 10 + 40 + 30, under the cap of 85
    } finally {
      closeSession(session);
    }
  });

  it("leaves out only the levels whose relaxation cannot win: the answer is the same with and without the bound", () => {
    const bounded = make();
    const every = make();
    try {
      const a = solveScenario(bounded, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS, canonical: true });
      const b = solveScenario(every, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS, canonical: true, bound: false });
      expect(b.runs.every((run) => run.outcome === "solved" || run.outcome === "infeasible")).toBe(true);
      expect(a.F.toString()).toBe(b.F.toString());
      expect(kitPairs(a.kit)).toEqual(kitPairs(b.kit));
      expect(a.hasteAssumed).toBe(b.hasteAssumed);
      expect(a.runs.filter((run) => run.outcome === "bound").length).toBeGreaterThan(0);
    } finally {
      closeSession(bounded);
      closeSession(every);
    }
  });

  it("has one program when no weapon is scored (the stick, or no damage weight), and says the haste the kit counts", () => {
    const profile = profileWith({ weights: { DMG: 1000, HP: 1, HASTE: 2 } });
    const session = make(profile, "stick");
    try {
      const got = solveScenario(session, { name: "main", items: [gear("belt", ["WAIST"], { haste: 30, stats: { STA: 1 } }), SWORD], options: HAND, budgetMs: BUDGET_MS, canonical: true });
      expect(got.levels).toHaveLength(1);
      expect(got.runs).toHaveLength(1);
      expect(got.hasteAssumed).toBe(30);
      expect(got.level).toBe(30);
      expect(got.program).toBe("main");
    } finally {
      closeSession(session);
    }
  });

  it("starts nothing when it needs time and the time is gone once the model is made, and returns null", () => {
    let clock = 0;
    const session = make(prof(), "dw", { now: () => clock });
    try {
      const spent = solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: 0, deadline: 0, needTime: true });
      expect(spent).toBeNull();
      expect(programsOf(session, "main").length).toBeGreaterThan(0); // (the model was made)
      clock = 5;
      const without = solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: 0, deadline: 0 });
      expect(without.status === "time_limit" || without.status === "optimal").toBe(true); // (it runs with what is left, which may be nothing)
    } finally {
      closeSession(session);
    }
  });

  it("checks its request", () => {
    const session = make();
    try {
      expect(() => solveScenario(session, null)).toThrow(/takes a request/);
      expect(() => solveScenario(session, { name: "main", items: [], budgetMs: -1 })).toThrow(/budgetMs/);
      expect(() => solveScenario(session, { name: "main", items: [], budgetMs: 1, nope: 1 })).toThrow(/does not read/);
      expect(() => solveScenario(session, { name: "main", items: [], budgetMs: 1, bound: "yes" })).toThrow(/bound is true or false/);
    } finally {
      closeSession(session);
    }
  });
});

describe("the rows that make a level exact", () => {
  const prof = profileWith({ weights: { HP: 1 }, haste_cap: 75, haste_bonus: 10 });
  const buffset = buffsetOf({ optional: [buffOf(1, { HASTE: 30 }), buffOf(2, { HASTE: 45 })], conflicts: [[1, 2]] });
  const items = [gear("boots", ["FEET"], { haste: 15 }), gear("belt", ["WAIST"], { haste: 25 })];
  const rowsOf = (floor, over = {}) => buildMilp(prof, items, "stick", buffset, { ...HAND, haste_assumed: floor, haste_floor: floor, haste_exact: true, ...over }).row_names.filter((row) => /^haste\.(ceil|over)/.test(row));

  it("keep a worn piece out under the spell haste that already makes the level, and a buff that alone counts more", () => {
    // level 40: Unbound Alacrity's 10 leaves 30 for a worn piece, which neither has; buff 1 (40) alone is the level; buff 2 (55) alone is above it
    expect(rowsOf(40)).toEqual(["haste.ceil[40]", "haste.over[55]"]);
    expect(rowsOf(20)).toEqual(["haste.ceil[10]", "haste.over[40]", "haste.over[55]"]);
    expect(rowsOf(75)).toEqual([]); // the cap: nothing counts more
  });

  it("need a floor, and are told in the info", () => {
    expect(() => buildMilp(prof, items, "stick", buffset, { ...HAND, haste_exact: true })).toThrow(/haste_exact needs haste_floor/);
    expect(() => buildMilp(prof, items, "stick", buffset, { ...HAND, haste_assumed: 40, haste_floor: 40, haste_exact: "yes" })).toThrow(/haste_exact is true or false/);
    expect(buildMilp(prof, items, "stick", buffset, { ...HAND, haste_assumed: 40, haste_floor: 40, haste_exact: true }).info.haste_exact).toBe(true);
    expect(buildMilp(prof, items, "stick", buffset, { ...HAND, haste_assumed: 40, haste_floor: 40 }).info.haste_exact).toBeUndefined();
  });
});


describe("the edges of the level loop (the fix round)", () => {
  const prof = () => profileWith({ weights: { DMG: 1000, HP: 1 } });
  const states = () => highs.constants.modelStatus;
  const withSpy = (hooks, extra = {}) => {
    const spied = spyOn(highs, hooks);
    return { ...spied, session: createSession({ highs: spied.highs, profile: prof(), setup: "dw", ...extra }) };
  };
  const levelsOfBelts = () => hasteLevels(prof(), beltPool(), "dw", null, HAND).length;

  it("answers infeasible, and does not throw, when every level is infeasible (the bound on too)", () => {
    const { session } = withSpy({ outcome: (result) => ({ ...result, modelStatus: states().infeasible }) });
    try {
      const got = solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS });
      expect(got.status).toBe("infeasible");
      expect(got.kit).toBeNull();
      expect(got.proven).toBe(true);
      expect(got.runs.every((run) => run.outcome === "infeasible")).toBe(true);
      expect(got.level).toBe(got.levels[got.levels.length - 1]);
      expect(got.program).toBe(programName("main", got.level));
    } finally {
      closeSession(session);
    }
  });

  it("says time_limit, with the level it is of, when a level stopped on its time with no kit and the next is infeasible", () => {
    let runs = 0;
    const { session } = withSpy({
      outcome: (result) => {
        runs += 1;
        return { ...result, modelStatus: runs === 1 ? states().timeLimit : states().infeasible };
      },
      info: (key, value) => (key === "primal_solution_status" ? highs.constants.solutionStatus.none : value),
    });
    try {
      const got = solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS, bound: false });
      expect(got.status).toBe("time_limit");
      expect(got.proven).toBe(false);
      expect(got.label).toBe(LABEL_NO_INCUMBENT);
      expect(got.kit).toBeNull();
      expect(got.level).toBe(got.levels[got.levels.length - 1]); // the level that stopped is the first taken, the highest
      expect(got.program).toBe(programName("main", got.level));
    } finally {
      closeSession(session);
    }
  });

  it("drops a level in the relaxation only on a proof of infeasibility: a relaxation that stopped, or went wrong, gives no bound and the level is solved", () => {
    const want = (() => {
      const plain = withSpy({});
      try {
        return solveScenario(plain.session, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS, canonical: true });
      } finally {
        closeSession(plain.session);
      }
    })();
    for (const bad of ["timeLimit", "unbounded"]) {
      let runs = 0;
      const { session } = withSpy({ outcome: (result) => ((runs += 1) === 1 ? { ...result, modelStatus: states()[bad] } : result) }); // (the first run is the first bound; after one that gave none the solver is not asked again)
      try {
        const got = solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS, canonical: true });
        expect(got.runs.some((run) => run.outcome === "infeasible"), bad).toBe(false);
        expect(got.runs.filter((run) => run.outcome === "solved").length, bad).toBeGreaterThanOrEqual(1);
        expect(got.F.toString(), bad).toBe(want.F.toString());
        expect(got.status, bad).toBe("optimal");
      } finally {
        closeSession(session);
      }
    }
  });

  it("checks the bound before the time: once the budget is spent a level the bound rules out is finished, not unfinished, and the answer is proven", () => {
    let clock = 0;
    let runs = 0;
    const { session } = withSpy(
      { clock: () => clock, before: () => { runs += 1; if (runs > levelsOfBelts()) clock += 100_000; } }, // the first solve of a level spends the whole budget
      { now: () => clock },
    );
    try {
      const got = solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: 5000 });
      expect(got.runs.some((run) => run.outcome === "time")).toBe(false);
      expect(got.runs.filter((run) => run.outcome === "bound").length).toBeGreaterThan(0);
      expect(got.status).toBe("optimal");
      expect(got.proven).toBe(true);
    } finally {
      closeSession(session);
    }
  });

  it("refuses two haste buffs that can be active together, and a haste floor without a haste assumed", () => {
    const two = buffsetOf({ optional: [buffOf(1, { HASTE: 30 }), buffOf(2, { HASTE: 40 })] });
    expect(() => buildMilp(prof(), [], "stick", two, HAND)).toThrow(/both carry spell haste and can be active together/);
    expect(() => hasteLevels(prof(), [], "stick", two, HAND)).toThrow(/both carry spell haste/);
    const ok = buffsetOf({ optional: [buffOf(1, { HASTE: 30 }), buffOf(2, { HASTE: 40 })], conflicts: [[1, 2]] });
    expect(buildMilp(prof(), [], "stick", ok, HAND).row_names.some((row) => row.startsWith("buff."))).toBe(true);
    expect(() => buildMilp(prof(), [], "stick", null, { ...HAND, haste_floor: 10 })).toThrow(/haste_floor needs haste_assumed/);
    expect(() => buildMilp(prof(), [], "stick", null, { ...HAND, haste_floor: 10, haste_exact: true })).toThrow(/haste_floor needs haste_assumed/);
  });
});

describe("the cutoff of a level's search (the fix round)", () => {
  const prof = () => profileWith({ weights: { DMG: 1000, HP: 1 } });

  it("hides no kit that reaches it: at the best value (less the tolerance) the answer is the level's best, above it there is no kit that reaches it", () => {
    const session = createSession({ highs, profile: prof(), setup: "dw" });
    try {
      for (const level of hasteLevels(prof(), beltPool(), "dw", null, HAND)) {
        const options = { ...HAND, haste_assumed: level, haste_floor: level, haste_exact: true };
        setScenario(session, "lv", beltPool(), options);
        const plain = solve(session, { scenario: "lv", budgetMs: BUDGET_MS });
        if (plain.status === "infeasible") {
          expect(solve(session, { scenario: "lv", budgetMs: BUDGET_MS, cutoff: 0 }).status).toBe("infeasible");
          continue;
        }
        const best = plain.modelF;
        const scale = Math.max(1, Math.abs(best));
        for (const cutoff of [best - 1e-6 * scale, best - 5 * scale, best + 1e-3 * scale, best + 10 * scale]) {
          const cut = solve(session, { scenario: "lv", budgetMs: BUDGET_MS, cutoff });
          if (cut.status === "optimal" && cut.kit !== null && cut.modelF >= cutoff) expect(Math.abs(cut.modelF - best), `level ${level}`).toBeLessThanOrEqual(1e-7 * scale);
          else if (best >= cutoff) throw new Error(`the cutoff ${cutoff} hid the best kit ${best} of level ${level}`);
          else expect(cut.status === "infeasible" || cut.kit === null || cut.modelF < cutoff).toBe(true);
        }
        // the solver's option is put back: the next plain solve is the plain solve again
        expect(solve(session, { scenario: "lv", budgetMs: BUDGET_MS }).modelF).toBe(best);
      }
      expect(() => solve(session, { scenario: "lv", budgetMs: BUDGET_MS, cutoff: Infinity })).toThrow(/cutoff/);
    } finally {
      closeSession(session);
    }
  });

  it("gives the same answer with the cutoff (the bound) as without, and a level it ends is a bound, never a time or an infeasible", () => {
    const session = createSession({ highs, profile: prof(), setup: "dw" });
    try {
      const withCut = solveScenario(session, { name: "a", items: beltPool(), options: HAND, budgetMs: BUDGET_MS, canonical: true });
      const every = solveScenario(session, { name: "b", items: beltPool(), options: HAND, budgetMs: BUDGET_MS, canonical: true, bound: false });
      expect(withCut.F.toString()).toBe(every.F.toString());
      expect(kitPairs(withCut.kit)).toEqual(kitPairs(every.kit));
      expect(withCut.level).toBe(every.level);
      expect(withCut.runs.every((run) => ["solved", "bound"].includes(run.outcome))).toBe(true);
      expect(every.runs.every((run) => run.outcome === "solved")).toBe(true);
    } finally {
      closeSession(session);
    }
  });

  it("makes a scenario only for a level that was solved (the others have no solver)", () => {
    const session = createSession({ highs, profile: prof(), setup: "dw" });
    try {
      const got = solveScenario(session, { name: "main", items: beltPool(), options: HAND, budgetMs: BUDGET_MS });
      const solved = got.runs.filter((run) => run.outcome === "solved").map((run) => programName("main", run.level));
      expect(programsOf(session, "main").sort()).toEqual([...solved, ...got.runs.filter((run) => run.outcome !== "solved" && run.status !== null).map((run) => programName("main", run.level))].sort());
      expect(programsOf(session, "main")).toContain(got.program);
    } finally {
      closeSession(session);
    }
  });
});
