import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { LABEL_NO_INCUMBENT, LABEL_TIME_LIMIT } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { compare } from "../pipeline/trioforge/site/static/engine/milpjson.js";
import { PathError, bestSets, classify, equipNow, everySlot, farmPath, sessionHaste } from "../pipeline/trioforge/site/static/engine/path.js";
import { closeSession, createSession, programsOf } from "../pipeline/trioforge/site/static/engine/solve.js";
import { SLOT_INSTANCES, evaluate, evaluateTruthful } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { caseOf, deepFreeze, exact, identOf, kitPairs, sharedOf, shuffled, solverIs } from "./engine-cases.mjs";
import { SAMPLE, describeFull } from "./engine-fixtures.mjs";
import { buffOf, buffsetOf, gear, oneHand, profileWith, q, twoHand } from "./engine-hand.mjs";
import { spyOn } from "./engine-spy.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

// The Upgrade tab's functions in the browser (static/engine/path.js) held to the Python reference (pipeline/trioforge/upgrade.py):
//
//   * Parity. For every Upgrade case of the fixtures (`upgrade/`): the session's haste (none unless fixed: every kit is valued at the haste it counts), Equip now, every step of the farm path (the item
//     acquired, its kind, the tier it is made from, the exact value after it, the exact gain, the owned set after it), why the path stopped, and Every
//     slot (the three best swaps of each of the 22 places) are those Python computed.
//   * The best sets. For every Upgrade case, the best 2 and the best 3 additions made at once: what to acquire, the exact value and gain, the assumed haste,
//     the kit (place for place) and the program that was built (the model of the scenario "best-k", with the pool its pruning left) are Python's.
//   * The farm path on a persistent model. One Best-1 model stays in the solver from step to step: the owned counts change its bounds and rows in
//     place, and each step starts from the last kit.
//   * The budget. Every solve of the path (Equip now, then each step) may use all the time that is left of it, so that the first steps are found whatever
//     the number asked for; the limits handed to the solver never exceed what is left; nothing of a step is started once the budget is spent; and a path
//     that runs out of time stops cleanly, with the step it was in reported.
//   * The best sets by hand. One model with `max_new = k` in a scenario of its own; the same time rules as the path (the whole budget, nothing begun once it
//     is spent, a time-limited answer labelled, "not found in time" with no incumbent); nothing to add; the arguments.
//   * By hand. The kinds of an addition, the Lore copy that adds nothing, the early end, the arguments.

// a solve of the hard programs takes a second or two, and the suite runs its files side by side: the time of a test is not the default five seconds
vi.setConfig({ testTimeout: 120_000 });
const BUDGET_MS = 900_000;

/** HiGHS as the worker runs it (in Node it reads its own file), started once for this file. */
let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const sessionFor = (c, extra = {}) => createSession({ highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins, ...extra });
/** The options of a fixture's session: the Any rule its programs were built under (the invented sessions of Every slot use the explicit one), and the haste if given. */
const optionsOf = (doc, haste) => ({ any_rule: doc.solves[0].options.any_rule, ...(haste === undefined ? {} : { haste_assumed: haste }) });

// ---- parity with Python --------------------------------------------------------------------------------------------------------------

function parityTests(set) {
  const shared = sharedOf(set);
  const paths = set.paths("case", "upgrade/");

  it("has Upgrade cases (all of the family the run made)", () => {
    expect(paths.length).toBeGreaterThan(0);
    expect(paths.length).toBe(set.manifest.families.upgrade.count);
  });

  for (const path of paths) {
    const doc = set.read(path);
    const { expected } = doc;

    it(`${doc.id} (${doc.label}): the session has no haste of its own unless the caller fixes one, as in Python`, () => {
      const c = caseOf(shared, doc);
      const fixed = { any_rule: doc.solves[0].options.any_rule };
      expect(sessionHaste(c.profile, c.owned(), c.candidates(), c.setup, c.buffset, fixed)).toBeNull();
      expect(sessionHaste(c.profile, c.owned(), [], c.setup, c.buffset, fixed)).toBeNull();
      expect(sessionHaste(c.profile, c.owned(), c.candidates(), c.setup, c.buffset, { ...fixed, haste_assumed: 7 })).toBe(7);
    });

    it(`${doc.id} (${doc.label}): Equip now is Python's, with the exact value`, () => {
      const c = caseOf(shared, doc);
      const session = sessionFor(c, { options: optionsOf(doc) });
      try {
        const got = equipNow(session, c.owned(), { budgetMs: BUDGET_MS, canonical: true });
        const want = doc.solves[expected.equip_now].result;
        expect(got.status).toBe("optimal");
        expect(got.F.toString()).toBe(exact(want.F).toString());
        expect(got.hasteAssumed, "the haste its kit counts").toBe(want.haste_assumed);
        expect(kitPairs(got.kit), `${doc.id}: the kit, place for place`).toEqual(want.kit);
        expect(got.buffs).toEqual(want.buffs);
        // the program of the winning level is the recorded one
        expect(compare(session.scenarios.get(got.program).model, doc.solves[expected.equip_now].model).slice(0, 5), `${doc.id}: the model`).toEqual([]);
        expect(got.levels, `${doc.id}: the hastes a kit can count`).toEqual(doc.solves[expected.equip_now].haste.levels);
        // a haste the options fix is the one every kit is valued at, as it always was
        const fixedSession = sessionFor(c, { options: optionsOf(doc, 7) });
        try {
          const fixed = equipNow(fixedSession, c.owned(), { budgetMs: BUDGET_MS });
          expect(fixed.status).toBe("optimal");
          expect(fixed.hasteAssumed).toBe(7);
          expect(fixed.levels).toEqual([7]);
        } finally {
          closeSession(fixedSession);
        }
      } finally {
        closeSession(session);
      }
    }, 300_000);

    it(`${doc.id} (${doc.label}): the farm path is Python's, step by step, and stops for Python's reason`, () => {
      const c = caseOf(shared, doc);
      const session = sessionFor(c, { options: optionsOf(doc) });
      const streamed = [];
      try {
        const got = farmPath(session, c.owned(), c.candidates(), { steps: doc.inputs.steps, budgetMs: BUDGET_MS, canonical: true, onStep: (step) => streamed.push(step) });
        expect(got.hasteAssumed, "Equip now's haste").toBe(doc.solves[expected.equip_now].result.haste_assumed);
        expect(got.baseline.status).toBe("optimal");
        expect(got.baseline.F.toString()).toBe(exact(doc.solves[expected.equip_now].result.F).toString());
        expect(got.steps.every((step) => step.found)).toBe(true);
        expect(got.steps.length, `${doc.id}: the number of steps`).toBe(expected.steps.length);
        got.steps.forEach((step, at) => {
          const want = expected.steps[at];
          const label = `${doc.id} step ${want.index}`;
          expect(step.index, label).toBe(want.index);
          expect(identOf(step.item), `${label}: the item`).toBe(want.item);
          expect(step.kind, `${label}: the kind`).toBe(want.kind);
          expect(step.sourceTier, `${label}: the tier it is made from`).toBe(want.source_tier);
          expect(step.F.toString(), `${label}: F`).toBe(exact(want.F).toString());
          expect(step.gain.toString(), `${label}: the gain`).toBe(exact(want.gain).toString());
          expect(step.hasteAssumed, `${label}: the assumed haste`).toBe(want.haste_assumed);
          expect(step.owned, `${label}: the owned set after it`).toEqual(want.owned);
          expect(step.status, label).toBe("optimal");
          expect(step.label).toBeNull();
          expect(step.solution.F.toString()).toBe(step.F.toString());
        });
        expect(got.stopped, `${doc.id}: why the path stopped`).toBe(expected.stopped);
        // each step was streamed, in order, as the very object that is returned
        expect(streamed.length).toBe(got.steps.length);
        streamed.forEach((step, at) => expect(step).toBe(got.steps[at]));
        // the gains add up to the difference of the values
        const total = got.steps.reduce((sum, step) => sum.add(step.gain), got.baseline.F.sub(got.baseline.F));
        const last = got.steps.length === 0 ? got.baseline.F : got.steps[got.steps.length - 1].F;
        expect(total.toString()).toBe(last.sub(got.baseline.F).toString());
      } finally {
        closeSession(session);
      }
    }, 600_000);

    it(`${doc.id} (${doc.label}): the best 2 and 3 sets are Python's, and so are the program and the kit of each`, () => {
      const c = caseOf(shared, doc);
      const session = sessionFor(c, { options: optionsOf(doc) });
      try {
        expect(expected.best_sets.map((entry) => entry.k)).toEqual([2, 3]);
        const sets = new Map();
        for (const want of expected.best_sets) {
          const label = `${doc.id} best-${want.k}`;
          const got = bestSets(session, c.owned(), c.candidates(), want.k, { budgetMs: BUDGET_MS, canonical: true });
          expect(got.k, label).toBe(want.k);
          expect(got.status, label).toBe("optimal");
          expect(got.label, label).toBeNull();
          expect(got.acquired.map((acquisition) => identOf(acquisition.item)), `${label}: what to acquire`).toEqual(want.acquired);
          expect(got.F.toString(), `${label}: F`).toBe(exact(want.F).toString());
          expect(got.gain.toString(), `${label}: the gain`).toBe(exact(want.gain).toString());
          expect(got.hasteAssumed, `${label}: the assumed haste`).toBe(want.haste_assumed);
          expect(got.baseline.status).toBe("optimal");
          const recorded = doc.solves.find((solve) => solve.label === `best-${want.k}`);
          expect(recorded, `${label}: the program Python built`).toBeDefined();
          // the program: the model the session built for the scenario is the recorded one, from the pool that the pruning left
          const scenario = session.scenarios.get(got.solution.program);
          expect(compare(scenario.model, recorded.model).slice(0, 5), `${label}: the model`).toEqual([]);
          expect(got.solution.levels, `${label}: the hastes a kit can count`).toEqual(recorded.haste.levels);
          expect([...scenario.items.keys()].sort(), `${label}: the pool`).toEqual([...recorded.pool].sort());
          if (want.acquired.length > 0) {
            expect(kitPairs(got.kit), `${label}: the kit, place for place`).toEqual(recorded.result.kit);
            expect(got.buffs, `${label}: the buffs`).toEqual(recorded.result.buffs);
            expect(got.solution.F.toString()).toBe(got.F.toString());
          }
          sets.set(want.k, got);
        }
        // The best set of one is the first step of the path, so every set is at least that; and the best set of k additions is no worse than the path after k
        // steps (the k steps are k additions, and a set may upgrade an owned copy and then add copies of the upgrade); and the larger set is no worse than the smaller.
        for (const [k, got] of sets) {
          if (expected.steps.length >= 1) expect(got.F.compare(exact(expected.steps[0].F)), `${doc.id}: the best ${k} against step 1 of the path`).toBeGreaterThanOrEqual(0);
          if (expected.steps.length >= k) expect(got.F.compare(exact(expected.steps[k - 1].F)), `${doc.id}: the best ${k} against step ${k} of the path`).toBeGreaterThanOrEqual(0);
        }
        expect(sets.get(3).F.compare(sets.get(2).F), `${doc.id}: the best 3 against the best 2`).toBeGreaterThanOrEqual(0);
      } finally {
        closeSession(session);
      }
    }, 600_000);

    it(`${doc.id} (${doc.label}): Every slot is Python's`, () => {
      const c = caseOf(shared, doc);
      const session = sessionFor(c, { options: optionsOf(doc) });
      try {
        // from Python's own Equip now kit over the candidates and the owned items, as the fixture was made: an owned item that is not a candidate counts its copies
        const equip = doc.solves[expected.equip_now].result;
        const kit = equip.kit.map((pair) => (pair === null ? null : c.itemAt(pair[0], pair[1])));
        const rows = everySlot(session, { kit, buffs: equip.buffs }, c.candidates(), { limit: 3, owned: c.owned() });
        expect(rows.length).toBe(expected.every_slot.length);
        rows.forEach((row, at) => {
          const want = expected.every_slot[at];
          expect(row.place).toBe(want.place);
          expect(row.index).toBe(want.index);
          expect(row.current === null ? null : identOf(row.current), `${doc.id} ${want.place}: the item worn`).toBe(want.current);
          expect(
            row.swaps.map((swap) => [identOf(swap.item), swap.delta.toString()]),
            `${doc.id} ${want.place}[${at}]: the swaps`,
          ).toEqual(want.swaps.map((swap) => [swap.item, exact(swap.delta).toString()]));
        });
        // the kit can be given as the 22 places themselves, and the buffs beside it
        const plain = everySlot(session, kit, c.candidates(), { buffs: equip.buffs, limit: 3, owned: c.owned() });
        expect(plain.map((row) => row.swaps.map((swap) => swap.delta.toString()))).toEqual(rows.map((row) => row.swaps.map((swap) => swap.delta.toString())));
      } finally {
        closeSession(session);
      }
    }, 300_000);
  }
}

describe("the committed sample", () => parityTests(SAMPLE));
describeFull("the full set", (full) => parityTests(full));

// ---- the order of the inputs does not matter ------------------------------------------------------------------------------------------

describe("determinism of the farm path", () => {
  const shared = sharedOf(SAMPLE);
  for (const path of SAMPLE.paths("case", "upgrade/").slice(0, 3)) {
    const doc = SAMPLE.read(path);
    it(`${doc.id} (${doc.label}): the owned set and the candidates in another order give the same canonical path`, () => {
      const c = caseOf(shared, doc);
      const given = sessionFor(c, { options: optionsOf(doc) });
      const other = sessionFor(c, { options: optionsOf(doc) });
      try {
        const a = farmPath(given, c.owned(), c.candidates(), { steps: doc.inputs.steps, budgetMs: BUDGET_MS, canonical: true });
        const b = farmPath(other, shuffled(c.owned(), 4), shuffled(c.candidates(), 9), { steps: doc.inputs.steps, budgetMs: BUDGET_MS, canonical: true });
        expect(b.steps.map((step) => identOf(step.item))).toEqual(a.steps.map((step) => identOf(step.item)));
        expect(b.steps.map((step) => step.F.toString())).toEqual(a.steps.map((step) => step.F.toString()));
        expect(b.steps.map((step) => kitPairs(step.solution.kit))).toEqual(a.steps.map((step) => kitPairs(step.solution.kit)));
        expect(b.stopped).toBe(a.stopped);
      } finally {
        closeSession(given);
        closeSession(other);
      }
    }, 600_000);
  }
});

describe("determinism of the best sets", () => {
  const shared = sharedOf(SAMPLE);
  for (const path of SAMPLE.paths("case", "upgrade/").slice(0, 3)) {
    const doc = SAMPLE.read(path);
    it(`${doc.id} (${doc.label}): the owned set and the candidates in another order give the same canonical sets, kits included`, () => {
      const c = caseOf(shared, doc);
      const given = sessionFor(c, { options: optionsOf(doc) });
      const other = sessionFor(c, { options: optionsOf(doc) });
      try {
        for (const k of [2, 3]) {
          const a = bestSets(given, c.owned(), c.candidates(), k, { budgetMs: BUDGET_MS, canonical: true });
          const b = bestSets(other, shuffled(c.owned(), 4 + k), shuffled(c.candidates(), 9 + k), k, { budgetMs: BUDGET_MS, canonical: true });
          expect(b.acquired.map((found) => found.ident)).toEqual(a.acquired.map((found) => found.ident));
          expect(b.F.toString()).toBe(a.F.toString());
          expect(kitPairs(b.kit)).toEqual(kitPairs(a.kit));
          expect(b.buffs).toEqual(a.buffs);
        }
      } finally {
        closeSession(given);
        closeSession(other);
      }
    }, 600_000);
  }
});

// ---- the persistent model -------------------------------------------------------------------------------------------------------------

describe("the Best-1 model of the farm path", () => {
  const shared = sharedOf(SAMPLE);
  const doc = SAMPLE.read(SAMPLE.paths("case", "upgrade/")[0]);
  const c = caseOf(shared, doc);

  it("stays in the session between steps and between paths, and every step starts from the last kit", () => {
    const session = sessionFor(c);
    try {
      const first = farmPath(session, c.owned(), c.candidates(), { steps: doc.inputs.steps, budgetMs: BUDGET_MS });
      expect(first.steps.length).toBeGreaterThan(0);
      expect(programsOf(session, "best-1").length, "the programs of the Best-1 scenario are in the session").toBeGreaterThan(0);
      expect(programsOf(session, "equip-now").length).toBeGreaterThan(0);
      const solver = session.scenarios.get(first.steps[first.steps.length - 1].solution.program).solver;
      expect(solver).not.toBeNull();
      expect(first.steps.every((step) => step.status === "optimal")).toBe(true);
      // a step reports how its model came about: made anew, or the same columns with changed bounds and rows
      for (const step of first.steps) {
        expect(typeof step.timings.pruneMs).toBe("number");
        expect(typeof step.timings.buildMs).toBe("number");
        expect(typeof step.timings.solveMs).toBe("number");
        expect(typeof step.reused).toBe("boolean");
      }
      // the same path again: the first step's pool is the pool of the last path's first step, in the model of its last step
      const again = farmPath(session, c.owned(), c.candidates(), { steps: doc.inputs.steps, budgetMs: BUDGET_MS });
      expect(again.steps.map((step) => identOf(step.item))).toEqual(first.steps.map((step) => identOf(step.item)));
      expect(again.steps.map((step) => step.F.toString())).toEqual(first.steps.map((step) => step.F.toString()));
    } finally {
      closeSession(session);
    }
  });

  it("is changed in place in some steps (the columns are the same) and made anew in the others, and the solver always holds the model of the builder", () => {
    let reused = 0;
    let steps = 0;
    for (const path of SAMPLE.paths("case", "upgrade/")) {
      const one = SAMPLE.read(path);
      const k = caseOf(shared, one);
      const session = sessionFor(k, { options: optionsOf(one) });
      try {
        const got = farmPath(session, k.owned(), k.candidates(), { steps: one.inputs.steps, budgetMs: BUDGET_MS });
        for (const step of got.steps) {
          steps += 1;
          if (step.reused) reused += 1;
        }
        for (const name of [...programsOf(session, "equip-now"), ...programsOf(session, "best-1")]) solverIs(expect, highs, session, name);
      } finally {
        closeSession(session);
      }
    }
    expect(steps).toBeGreaterThan(0);
    expect(reused, "a step whose pool and columns are those of the step before changes the model in place").toBeGreaterThan(0);
    expect(reused, "a step that brings a new duplicate has a column more").toBeLessThan(steps);
  });

  it("is not pruned once for the whole path: each step prunes its own pool", () => {
    const session = sessionFor(c);
    try {
      const got = farmPath(session, c.owned(), c.candidates(), { steps: doc.inputs.steps, budgetMs: BUDGET_MS, canonical: true });
      const sizes = got.steps.map((step) => step.poolSize);
      sizes.forEach((size, at) => expect(size, `step ${at + 1}`).toBe(doc.solves[at + 1].pool.length));
    } finally {
      closeSession(session);
    }
  });
});

// ---- the budget -----------------------------------------------------------------------------------------------------------------------

describe("the budget", () => {
  const shared = sharedOf(SAMPLE);
  // the first case of the sample whose programs are each solved at one haste level (Python: every solve of the case has one level in solves[].haste.levels), so that the path is
  // Equip now and its three steps, one solve each, as the tests below count them; a case of a haste ladder (several levels a solve) is solved once for each level
  const doc = SAMPLE.paths("case", "upgrade/").map((path) => SAMPLE.read(path)).find((one) => one.solves.length > 0 && one.solves.every((solve) => solve.haste.levels.length === 1));
  expect(doc, "the sample has a case whose programs have one haste level each").toBeDefined();
  const c = caseOf(shared, doc);
  const TICK = 4;
  const types = () => highs.constants.modelStatus;

  /** A session on a clock that the test moves by hand (it stands still otherwise), on a solver that logs the limits, the runs and the models. */
  function onClock(k, d, hooks = () => ({}), tick = 0) {
    let clock = 0;
    const spied = spyOn(highs, { clock: () => clock, ...hooks(() => clock, (to) => (clock = to)) });
    const session = sessionFor(k, { highs: spied.highs, options: optionsOf(d), now: () => (clock += tick) });
    return { session, log: spied.log, clock: () => clock, set: (to) => (clock = to) };
  }

  it("lets every solve use all the time that is left: on a clock that stands still each is handed the whole budget", () => {
    const { session, log } = onClock(c, doc);
    try {
      const got = farmPath(session, c.owned(), c.candidates(), { steps: 3, budgetMs: 5000 });
      expect(got.steps).toHaveLength(3);
      expect(got.stopped).toBe("limit");
      expect(log.limits).toHaveLength(4); // Equip now and the three steps
      for (const limit of log.limits) expect(limit.limitMs).toBe(5000);
    } finally {
      closeSession(session);
    }
  });

  /** One run of the path on its own session, timed: the steps it found, and the milliseconds it took. */
  function timed(k, d, steps, budgetMs) {
    const session = sessionFor(k, { options: optionsOf(d) });
    try {
      const began = performance.now();
      const got = farmPath(session, k.owned(), k.candidates(), { steps, budgetMs });
      return { got, ms: performance.now() - began, found: got.steps.filter((step) => step.found) };
    } finally {
      closeSession(session);
    }
  }

  /** The path asked for eight steps on a budget that does for three: it has at least those three (the first steps matter most). */
  function threeOfEight(k, d, share) {
    const three = Math.max(timed(k, d, 3, 600_000).ms, timed(k, d, 3, 600_000).ms); // the time that three steps take here, twice over, the larger
    const budgetMs = share * three + 50;
    const eight = timed(k, d, 8, budgetMs);
    expect(eight.found.length, `${d.id}: ${budgetMs.toFixed(0)} ms for three steps that take ${three.toFixed(0)} ms`).toBeGreaterThanOrEqual(3);
    expect(eight.got.baseline.status).toBe("optimal");
    expect(eight.found.slice(0, 3).map((step) => identOf(step.item))).toEqual(timed(k, d, 3, 600_000).found.map((step) => identOf(step.item)));
  }

  it("finds at least three steps when asked for eight on a budget that is enough for three (equal shares of it would find none)", () => {
    threeOfEight(c, doc, 3);
  });

  describeFull("the full set: the case whose first step takes most of the path", (full) => {
    it("finds at least three steps when asked for eight on a budget that is enough for three", () => {
      const big = full.read(full.paths("case", "upgrade/").find((path) => path.endsWith("upgrade-008.json")));
      threeOfEight(caseOf(sharedOf(full), big), big, 2.5);
    });
  });

  it("hands out limits that are what was left of the budget, and begins solves and models only while there was time, on a clock that moves at every look", () => {
    // the budget is spent a little at a time on a clock that moves at every look: at every point of a step, in turn (every whole budget of a window, so
    // that the look that finds a millisecond or two left falls before a solve of some budget, and then a sparser run of the larger ones)
    const budgets = [...Array.from({ length: 100 }, (_, at) => 40 + at), ...Array.from({ length: 36 }, (_, at) => 150 + 10 * at)];
    for (const budgetMs of budgets) {
      const { session, log, clock } = onClock(c, doc, () => ({}), TICK);
      try {
        const before = clock();
        const got = farmPath(session, c.owned(), c.candidates(), { steps: 8, budgetMs });
        const deadline = before + TICK + budgetMs; // the first look at the clock is the start of the path
        expect(["time", "limit", "no-gain"]).toContain(got.stopped);
        // the limit is what was left when it was handed over, and never more (when nothing is left it is 0)
        for (const limit of log.limits) {
          expect(limit.limitMs, `budget ${budgetMs}`).toBeGreaterThanOrEqual(0);
          expect(limit.limitMs, `budget ${budgetMs}`).toBeLessThanOrEqual(Math.max(0, deadline - limit.at) + 1e-6);
        }
        // after Equip now (which always runs) nothing begins once the time is gone, but for the looks at the clock that the call makes between its last
        // look at the budget and the run (four) or the model (two): the exact cases are in the tests that follow
        log.runs.slice(1).forEach((run, at) => expect(run.at, `budget ${budgetMs}, solve ${at + 2}`).toBeLessThanOrEqual(deadline + 4 * TICK + 1e-9));
        log.createdAt.slice(1).forEach((made, at) => expect(made, `budget ${budgetMs}, model ${at + 2}`).toBeLessThanOrEqual(deadline + 2 * TICK + 1e-9));
      } finally {
        closeSession(session);
      }
    }
  });

  const BUDGET = 1000;

  /**
   * A path over one owned ring and one candidate ring, by hand, on a clock that the test moves. The candidate's `haste` is read through a getter that
   * calls `onRead(state)` (once Equip now has been solved), so that the test sees when the path reads the candidates again (to plan a step, and to prune
   * its pool) and can move the clock when it does; `afterEquipNow(state)` is called when the run of Equip now has ended. `state` is
   * `{clock, reads}`, `run()` the path, and `log` that of the spy on the solver.
   */
  function rings({ afterEquipNow = () => {}, onRead = () => {} }) {
    const state = { clock: 0, reads: 0, armed: false };
    const profile = profileWith({ weights: { HP: 1 } });
    const ring = (key, hp) => gear(key, ["FINGER"], { stats: { HP: hp } });
    const candidate = Object.defineProperty({ ...ring("ringB", 15) }, "haste", {
      get: () => {
        if (state.armed) {
          state.reads += 1;
          onRead(state);
        }
        return 0;
      },
      enumerable: true,
    });
    const spied = spyOn(highs, {
      clock: () => state.clock,
      after: () => {
        state.armed = true;
        afterEquipNow(state);
      },
    });
    const session = createSession({ highs: spied.highs, profile, setup: "stick", options: { any_rule: "explicit", haste_assumed: 0 }, now: () => state.clock });
    return { session, log: spied.log, state, run: () => farmPath(session, [[ring("ringA", 10), 1]], [candidate], { steps: 3, budgetMs: BUDGET }) };
  }

  it("begins nothing of a step when Equip now has spent the budget: the candidates are not read again, and no model is made", () => {
    const { session, log, state, run } = rings({ afterEquipNow: (now) => (now.clock = BUDGET + 1) });
    try {
      const got = run();
      expect(got.baseline.status).toBe("optimal");
      expect(got.stopped).toBe("time");
      expect(got.steps).toEqual([]);
      expect(state.reads, "neither the plan nor the pruning of a step was begun").toBe(0);
      expect(log.created).toBe(1);
    } finally {
      closeSession(session);
    }
  });

  it("builds no model when the planning and the pruning of a step spent the budget", () => {
    const { session, log, state, run } = rings({ onRead: (now) => (now.clock = BUDGET + 1) });
    try {
      const got = run();
      expect(got.baseline.status).toBe("optimal");
      expect(state.reads, "the step began: it read the candidates").toBeGreaterThan(0);
      expect(state.clock).toBe(BUDGET + 1);
      expect(got.stopped).toBe("time");
      expect(got.steps).toEqual([]);
      expect(log.created, "no model for the step").toBe(1);
    } finally {
      closeSession(session);
    }
  });

  it("starts no solve when the model of a step spent the budget", () => {
    // the second model made is the step's: the clock moves past the end of the budget as it is made
    let clock = 0;
    let made = 0;
    const spied = spyOn(highs, {
      clock: () => clock,
      created: () => {
        made += 1;
        if (made === 2) clock = BUDGET + 1;
      },
    });
    const session = sessionFor(c, { highs: spied.highs, options: optionsOf(doc), now: () => clock });
    try {
      const got = farmPath(session, c.owned(), c.candidates(), { steps: 3, budgetMs: BUDGET });
      expect(got.stopped).toBe("time");
      expect(got.steps).toEqual([]);
      expect(spied.log.created).toBe(2);
      expect(spied.log.runs).toHaveLength(1); // Equip now's, and not the step's
    } finally {
      closeSession(session);
    }
  });

  it("runs Equip now whatever is left, and then ends the path with nothing made if nothing is", () => {
    const { session, log } = onClock(c, doc, () => ({}), TICK);
    try {
      const got = farmPath(session, c.owned(), c.candidates(), { steps: 3, budgetMs: 1 }); // gone before the model of Equip now is built
      expect(got.stopped).toBe("time");
      expect(got.steps).toEqual([]);
      expect(got.baseline.status).toBe("time_limit");
      expect(log.created).toBe(1); // the model of Equip now, and no other
      expect(programsOf(session, "best-1")).toEqual([]);
    } finally {
      closeSession(session);
    }
  });

  it("ends within the budget by a margin that is HiGHS's lag and the work around the last solve, on the real clock", () => {
    const budgetMs = 120;
    const session = sessionFor(c, { options: optionsOf(doc) });
    try {
      const watch = stopwatch();
      const got = farmPath(session, c.owned(), c.candidates(), { steps: 8, budgetMs });
      const took = watch.stop();
      expect(["time", "limit", "no-gain"]).toContain(got.stopped);
      expectWithin(took, budgetMs + 1500, "the path ends within its budget (loose: the budget, and the lag of the solver and the work around the last solve)");
      expect(got.elapsedMs).toBeLessThanOrEqual(took.ms + 1);
    } finally {
      closeSession(session);
    }
  });

  it("is counted on the clock of the session: a path whose clock runs on stops cleanly when the budget is gone, whatever a look at the clock costs", () => {
    const budgetMs = 1000;
    let partial = 0;
    let empty = 0;
    for (const cost of [2, 5, 10, 20, 50, 100, 200, 500]) {
      let clock = 0;
      const session = sessionFor(c, { options: optionsOf(doc), now: () => (clock += cost) }); // every look at the clock costs `cost` ms of the budget
      try {
        const streamed = [];
        const got = farmPath(session, c.owned(), c.candidates(), { steps: 8, budgetMs, onStep: (step) => streamed.push(step) });
        expect(["time", "limit", "no-gain"], `cost ${cost}`).toContain(got.stopped);
        for (const solved of [got.baseline, ...got.steps.map((step) => step.solution)]) expect(solved.limitMs, `cost ${cost}`).toBeLessThanOrEqual(budgetMs);
        // what was found is a path: each found step improves on the one before, and the steps were streamed as they came
        const found = got.steps.filter((step) => step.found);
        for (let at = 1; at < found.length; at += 1) expect(found[at].F.compare(found[at - 1].F), `cost ${cost}`).toBe(1);
        expect(streamed.length, `cost ${cost}`).toBe(got.steps.length);
        streamed.forEach((step, at) => expect(step).toBe(got.steps[at]));
        if (got.stopped === "time" && found.length > 0) partial += 1;
        if (got.steps.length === 0) empty += 1;
      } finally {
        closeSession(session);
      }
    }
    expect(partial, "some cost leaves a path that was cut short after some steps").toBeGreaterThan(0);
    expect(empty, "and some leaves a path with none").toBeGreaterThan(0);
  });

  it("gives up at once with a budget of nothing, and says that nothing was found in time", () => {
    const session = sessionFor(c, { options: optionsOf(doc) });
    try {
      const got = farmPath(session, c.owned(), c.candidates(), { steps: 3, budgetMs: 0 });
      expect(got.stopped).toBe("time");
      expect(got.steps).toEqual([]);
      expect(got.baseline.status).toBe("time_limit");
    } finally {
      closeSession(session);
    }
    const alone = sessionFor(c, { options: optionsOf(doc) });
    try {
      const none = equipNow(alone, c.owned(), { budgetMs: 0 });
      expect(none.status).toBe("time_limit");
      expect(none.label === LABEL_NO_INCUMBENT || none.F !== null).toBe(true);
    } finally {
      closeSession(alone);
    }
  });

  it("reports a step that ran out of time before the solver had a kit as not found in time, passes it on, and ends the path", () => {
    // the third solve of the path (Equip now and the first step come before it) ends as if the time had run out before the solver had a solution
    const states = highs.constants.modelStatus;
    const forced = () => spied.log.runs.length === 3;
    const spied = spyOn(highs, {
      outcome: (result) => (forced() ? { ...result, modelStatus: states.timeLimit } : result),
      info: (key, value) => (forced() && key === "primal_solution_status" ? highs.constants.solutionStatus.none : value),
    });
    const session = sessionFor(c, { highs: spied.highs, options: optionsOf(doc) });
    try {
      const streamed = [];
      const got = farmPath(session, c.owned(), c.candidates(), { steps: 3, budgetMs: BUDGET_MS, onStep: (step) => streamed.push(step) });
      expect(got.stopped).toBe("time");
      expect(got.steps).toHaveLength(2);
      expect(got.steps[0]).toMatchObject({ index: 1, found: true, status: "optimal" });
      const [, last] = got.steps;
      expect(last).toMatchObject({ index: 2, found: false, status: "time_limit", label: LABEL_NO_INCUMBENT, item: null, kind: null, sourceTier: null, F: null, gain: null });
      expect(last.solution.kit).toBeNull();
      expect(streamed).toHaveLength(2); // the step that was not found is passed on too
      expect(streamed[1]).toBe(last);
    } finally {
      closeSession(session);
    }
  });

  it("reports a step that runs out of time with an addition that improves the value as found, with the status and the label of the solve, and ends the path", () => {
    const states = types();
    const spied = spyOn(highs, {
      // the second run is the first step's: it ends as if the time had run out (its kit is the best there is)
      outcome: (result) => (spied.log.runs.length === 2 ? { ...result, modelStatus: states.timeLimit } : result),
    });
    const session = sessionFor(c, { highs: spied.highs, options: optionsOf(doc) });
    try {
      const streamed = [];
      const got = farmPath(session, c.owned(), c.candidates(), { steps: 3, budgetMs: BUDGET_MS, onStep: (step) => streamed.push(step) });
      expect(got.stopped).toBe("time");
      expect(got.steps).toHaveLength(1);
      const [step] = got.steps;
      expect(step.found).toBe(true);
      expect(step.status).toBe("time_limit");
      expect(step.label).toBe(LABEL_TIME_LIMIT);
      expect(step.gain.sign()).toBe(1);
      expect(step.F.toString()).toBe(exact(doc.expected.steps[0].F).toString());
      expect(streamed).toEqual([step]);
      expect(session.scenarios.get(step.solution.program).last, "the kit of an unproven step is still the start of the next solve").not.toBeNull();
    } finally {
      closeSession(session);
    }
  });

  it("starts the first step from the kit of Equip now, and every later step from the last kit", () => {
    const { highs: spied, log } = spyOn(highs);
    const session = sessionFor(c, { highs: spied, options: optionsOf(doc) });
    try {
      const one = farmPath(session, c.owned(), c.candidates(), { steps: 1, budgetMs: BUDGET_MS });
      expect(one.baseline.start).toBeNull(); // Equip now has nothing to begin from
      expect(one.steps[0].solution.start).toBe("kit");
      expect(log.starts).toHaveLength(1);
      const model = session.scenarios.get(one.steps[0].solution.program).model;
      const wears = new Map();
      one.baseline.kit.forEach((item, at) => {
        if (item === null) return;
        const group = SLOT_INSTANCES[at];
        wears.set(`${group}|${identOf(item)}`, (wears.get(`${group}|${identOf(item)}`) ?? 0) + 1);
      });
      const want = [...model.item_cols.map(([column, group, key, tier]) => [column, wears.get(`${group}|${key}@${tier}`) ?? 0]), ...model.buff_cols.map(([column, id]) => [column, one.baseline.buffs.includes(id) ? 1 : 0])];
      want.sort((a, b) => a[0] - b[0]);
      expect(Array.from(log.starts[0].indices)).toEqual(want.map(([column]) => column));
      expect(Array.from(log.starts[0].values)).toEqual(want.map(([, value]) => value));
      // the later steps: the last solution when the solver's model was changed in place, else the item and buff columns of the last kit
      const more = farmPath(session, c.owned(), c.candidates(), { steps: 3, budgetMs: BUDGET_MS });
      expect(more.steps[0].solution.start).toBe("kit");
      for (const step of more.steps.slice(1)) expect(step.solution.start).toBe(step.reused ? "solution" : "kit");
    } finally {
      closeSession(session);
    }
  });

  it("gives the tie stage of a canonical Equip now and of a canonical step the same allowance as their first stage", () => {
    // each stage takes 300 ms of a clock that stands still otherwise
    const { session, log } = onClock(c, doc, (read, move) => ({ before: () => move(read() + 300) }));
    try {
      const got = farmPath(session, c.owned(), c.candidates(), { steps: 1, budgetMs: 5000, canonical: true });
      expect(got.steps).toHaveLength(1);
      // Equip now and the step, three stages each: the first stage, the proof that the band of the tie stage wears one set of items (a stage of its own), and the tie stage (which
      // follows the proof whenever the scenario has an optional buff, settled band or not)
      expect(log.limits).toHaveLength(6);
      expect(log.limits[0].limitMs).toBe(5000);
      expect(log.limits[1].limitMs).toBe(5000); // the proof of Equip now: the allowance of its first stage, not what the first stage left
      expect(log.limits[2].limitMs).toBe(5000); // and its tie stage the same: the proof before it has not used it up
      expect(log.limits[3].limitMs).toBe(5000 - 900); // the step has what is left of the path after the three stages of Equip now
      expect(log.limits[4].limitMs).toBe(5000 - 900); // and its proof and its tie stage the same
      expect(log.limits[5].limitMs).toBe(5000 - 900);
      const alone = onClock(c, doc, (read, move) => ({ before: () => move(read() + 300) }));
      try {
        equipNow(alone.session, c.owned(), { budgetMs: 1000, canonical: true });
        expect(alone.log.limits.map((limit) => limit.limitMs)).toEqual([1000, 1000, 1000]);
      } finally {
        closeSession(alone.session);
      }
    } finally {
      closeSession(session);
    }
  });
});

// ---- by hand ----------------------------------------------------------------------------------------------------------------------------

describe("the kinds of an addition", () => {
  const profile = profileWith({ weights: { HP: 1 } });
  const ring = (key, hp, tier = 0, more = {}) => gear(key, ["FINGER"], { stats: { HP: hp }, tier, ...more });
  const options = { any_rule: "explicit", haste_assumed: 0 };
  const make = (extra = {}) => createSession({ highs, profile, setup: "stick", options, ...extra });

  it("tells a copy, an upgrade and a new item from what is owned", () => {
    const owned = [[ring("band", 10, 0), 1], [ring("band", 12, 2), 1], [ring("sig", 5, 1), 2]];
    expect(classify(ring("band", 12, 2), owned)).toEqual(["copy", null]);
    expect(classify(ring("band", 30, 5), owned)).toEqual(["upgrade", 2]); // the highest tier below
    expect(classify(ring("band", 20, 1), owned)).toEqual(["upgrade", 0]);
    expect(classify(ring("sig", 9, 0), owned)).toEqual(["new", null]); // below every owned tier of its key: another copy, at its tier
    expect(classify(ring("fresh", 9, 3), owned)).toEqual(["new", null]);
    expect(classify(ring("band", 1, 0), [[ring("band", 10, 0), 0]])).toEqual(["new", null]); // a count of 0 is not owned
  });

  it("refuses an owned set that is not one", () => {
    expect(() => classify(ring("a", 1), [[ring("a", 1), -1]])).toThrow(PathError);
    expect(() => classify(ring("a", 1), [[ring("a", 1), 1.5]])).toThrow(PathError);
    expect(() => classify(ring("a", 1), [[ring("a", 1), 1], [ring("a", 1), 2]])).toThrow(/twice/);
    expect(() => classify(ring("a", 1), "a")).toThrow(PathError);
    expect(() => classify(ring("a", 1), [ring("a", 1)])).toThrow(PathError);
  });

  it("walks the path of a new item, an upgrade and a copy, and ends when no addition improves the value", () => {
    const session = make();
    try {
      const owned = [[ring("ringA", 10, 0), 1]];
      const candidates = [ring("ringA", 20, 3), ring("ringB", 15, 0), ring("ringA", 10, 0)];
      const got = farmPath(session, owned, candidates, { steps: 6, budgetMs: 60_000, canonical: true });
      expect(got.stopped).toBe("no-gain");
      expect(got.steps.map((step) => [identOf(step.item), step.kind, step.sourceTier, step.gain.toString()])).toEqual([
        ["ringB@0", "new", null, "15/1"], // 10 + 15 against 10
        ["ringA@3", "upgrade", 0, "10/1"], // the copy of ringA@0 becomes ringA@3: 20 + 15 against 10 + 15
        ["ringA@3", "copy", null, "5/1"], // a second ringA@3 in the place of ringB: 20 + 20 against 20 + 15
      ]);
      expect(got.steps.map((step) => step.owned)).toEqual([
        [["ringA@0", 1], ["ringB@0", 1]],
        [["ringA@3", 1], ["ringB@0", 1]],
        [["ringA@3", 2], ["ringB@0", 1]],
      ]);
      expect(got.steps.map((step) => step.index)).toEqual([1, 2, 3]);
      expect(got.baseline.F.toString()).toBe(got.steps[0].F.sub(got.steps[0].gain).toString());
    } finally {
      closeSession(session);
    }
  });

  it("reports the last step, which finds nothing to add, as not found when it runs out of time with the kit it began from", () => {
    // the fifth solve of the path, the fourth step's (Equip now and three steps come before it), ends as if the time had run out: its kit is the one of the
    // step before, with no gain
    const states = highs.constants.modelStatus;
    const spied = spyOn(highs, { outcome: (result) => (spied.log.runs.length === 5 ? { ...result, modelStatus: states.timeLimit } : result) });
    const session = createSession({ highs: spied.highs, profile, setup: "stick", options });
    try {
      const owned = [[ring("ringA", 10, 0), 1]];
      const candidates = [ring("ringA", 20, 3), ring("ringB", 15, 0), ring("ringA", 10, 0)];
      const streamed = [];
      const got = farmPath(session, owned, candidates, { steps: 6, budgetMs: 60_000, onStep: (step) => streamed.push(step) });
      expect(got.stopped).toBe("time");
      expect(got.steps).toHaveLength(4);
      expect(got.steps.slice(0, 3).every((step) => step.found && step.status === "optimal")).toBe(true);
      const last = got.steps[3];
      expect(last.found).toBe(false);
      expect(last.index).toBe(4);
      expect(last.status).toBe("time_limit");
      expect(last.label).toBe(LABEL_NO_INCUMBENT); // not found in time, though the solve has a kit: it adds nothing
      expect(last.solution.kit).not.toBeNull();
      expect(last.solution.label).toBe(LABEL_TIME_LIMIT);
      expect(last.item).toBeNull();
      expect(streamed).toEqual(got.steps);
    } finally {
      closeSession(session);
    }
  });

  it("stops at the number of steps asked for, and says so", () => {
    const session = make();
    try {
      const owned = [[ring("ringA", 10, 0), 1]];
      const candidates = [ring("ringA", 20, 3), ring("ringB", 15, 0)];
      const two = farmPath(session, owned, candidates, { steps: 2, budgetMs: 60_000 });
      expect(two.steps.length).toBe(2);
      expect(two.stopped).toBe("limit");
      const none = farmPath(session, owned, candidates, { steps: 0, budgetMs: 60_000 });
      expect(none.steps).toEqual([]);
      expect(none.stopped).toBe("limit");
    } finally {
      closeSession(session);
    }
  });

  it("leaves out a Lore copy (it adds nothing) and ends at once when nothing is offered", () => {
    const session = make();
    try {
      const lore = ring("sigil", 30, 0, { lore: true });
      const got = farmPath(session, [[lore, 1]], [lore], { steps: 3, budgetMs: 60_000 });
      expect(got.steps).toEqual([]);
      expect(got.stopped).toBe("no-gain");
      expect(farmPath(session, [[lore, 1]], [], { steps: 3, budgetMs: 60_000 }).stopped).toBe("no-gain");
      expect(farmPath(session, [], [], { steps: 3, budgetMs: 60_000 }).steps).toEqual([]);
      // a Lore item that is new is an addition: worn once
      const fresh = farmPath(session, [], [lore], { steps: 3, budgetMs: 60_000 });
      expect(fresh.steps.map((step) => identOf(step.item))).toEqual(["sigil@0"]);
      expect(fresh.stopped).toBe("no-gain");
    } finally {
      closeSession(session);
    }
  });

  it("values every kit at the haste it counts: Equip now at its own, each step at its own, so a step's gain is a difference of the values of two kits", () => {
    const boots = gear("boots", ["FEET"], { stats: { HP: 1 }, haste: 30 });
    const sword = gear("sword", ["PRIMARY"], { weapon: oneHand(40, 40) });
    const dagger = gear("dagger", ["PRIMARY"], { weapon: oneHand(30, 20) });
    const weapons = profileWith({ weights: { DMG: 100, HP: 1 } });
    const session = createSession({ highs, profile: weapons, setup: "dw", options: { any_rule: "explicit" } }); // no haste fixed: every kit is valued at the haste it counts
    try {
      const got = farmPath(session, [[sword, 1]], [boots, dagger], { steps: 3, budgetMs: 60_000 });
      expect(got.hasteAssumed, "the result says Equip now's haste").toBe(0);
      expect(got.baseline.hasteAssumed).toBe(0);
      // the dagger swings faster than the sword at any haste; the boots then give its 30
      expect(got.steps.map((step) => identOf(step.item))).toEqual(["dagger@0", "boots@0"]);
      expect(got.steps.map((step) => step.hasteAssumed)).toEqual([0, 30]);
      expect(got.steps.every((step) => step.solution.hasteAssumed === step.hasteAssumed)).toBe(true);
      let before = got.baseline.F;
      for (const step of got.steps) {
        const kit = step.solution.kit;
        expect(step.F.toString()).toBe(evaluate(weapons, kit, null, { setup: "dw", hasteAssumed: step.hasteAssumed }).F.toString());
        expect(step.F.toString()).toBe(evaluateTruthful(weapons, kit, null, { setup: "dw" }).F.toString());
        expect(step.gain.toString()).toBe(step.F.sub(before).toString());
        before = step.F;
      }
      // a haste the session fixes is the one every kit is valued at
      const fixed = createSession({ highs, profile: weapons, setup: "dw", options: { any_rule: "explicit", haste_assumed: 12 } });
      try {
        const same = farmPath(fixed, [[sword, 1]], [boots, dagger], { steps: 3, budgetMs: 60_000 });
        expect(same.hasteAssumed).toBe(12);
        expect(same.steps.every((step) => step.hasteAssumed === 12)).toBe(true);
      } finally {
        closeSession(fixed);
      }
    } finally {
      closeSession(session);
    }
  });
});

describe("the best sets by hand", () => {
  const profile = profileWith({ weights: { HP: 1 } });
  const ring = (key, hp, tier = 0, more = {}) => gear(key, ["FINGER"], { stats: { HP: hp }, tier, ...more });
  const options = { any_rule: "explicit", haste_assumed: 0 };
  const make = (extra = {}) => createSession({ highs, profile, setup: "stick", options, ...extra });
  const owned = () => [[ring("ringA", 10, 0), 1]];
  const candidates = () => [ring("ringA", 20, 3), ring("ringB", 15, 0), ring("ringA", 10, 0)];
  const idents = (set) => set.acquired.map((acquisition) => identOf(acquisition.item));

  it("finds the best k additions made at once, listed as the reference lists them, with the exact value and the gain over Equip now", () => {
    const session = make();
    try {
      const one = bestSets(session, owned(), candidates(), 1, { budgetMs: BUDGET_MS, canonical: true });
      expect(idents(one)).toEqual(["ringB@0"]); // one more ring, the better of the two: 10 + 15
      expect(one.F.sub(one.baseline.F).toString()).toBe("15/1"); // the value is the naked character's and the rings'; the rings are worth their points
      expect(one.gain.toString()).toBe("15/1");
      const two = bestSets(session, owned(), candidates(), 2, { budgetMs: BUDGET_MS, canonical: true });
      // the upgrade first, then a copy of it: the owned ringA@0 becomes ringA@3 (20) and a copy of that takes the other place (20): 40 against 10 (a new
      // ringB, 15, in the other place would give 35)
      expect(two.acquired.map((acquisition) => [identOf(acquisition.item), acquisition.kind, acquisition.sourceTier])).toEqual([
        ["ringA@3", "upgrade", 0],
        ["ringA@3", "copy", null],
      ]);
      expect(two.F.sub(two.baseline.F).toString()).toBe("30/1");
      expect(two.gain.toString()).toBe("30/1");
      expect(two.status).toBe("optimal");
      expect(two.label).toBeNull();
      expect(two.kit.filter((item) => item !== null).map(identOf).sort()).toEqual(["ringA@3", "ringA@3"]);
      expect(two.hasteAssumed).toBe(0);
      expect(two.F.toString()).toBe(two.baseline.F.add(two.gain).toString());
      // three additions: there is no third place that a ring improves (acquiring another copy of ringA@0 and upgrading both would cost three for the same kit)
      const three = bestSets(session, owned(), candidates(), 3, { budgetMs: BUDGET_MS, canonical: true });
      expect(three.acquired.map((acquisition) => [identOf(acquisition.item), acquisition.kind, acquisition.sourceTier])).toEqual([
        ["ringA@3", "upgrade", 0],
        ["ringA@3", "copy", null],
      ]);
      expect(three.gain.toString()).toBe("30/1");
      expect(three.acquired.map((acquisition) => acquisition.ident)).toEqual(idents(three));
    } finally {
      closeSession(session);
    }
  });

  it("may upgrade an owned copy and add a copy of the upgrade, as the steps of the path do", () => {
    // the path upgrades the owned ring and then copies the upgraded one (a copy at its tier needs no source); a set of two additions does the same (the first
    // wear of the target is the upgrade, the second a copy of it), and a third addition has no place to go
    const session = make();
    try {
      const only = [ring("ringA", 20, 3)];
      const path = farmPath(session, owned(), only, { steps: 3, budgetMs: BUDGET_MS, canonical: true });
      expect(path.steps.map((step) => [step.kind, identOf(step.item)])).toEqual([["upgrade", "ringA@3"], ["copy", "ringA@3"]]);
      const upgrade = [["upgrade", "ringA@3", 0]];
      const copy = [["copy", "ringA@3", null]];
      const sets = [1, 2, 3].map((k) => bestSets(session, owned(), only, k, { budgetMs: BUDGET_MS, canonical: true }));
      expect(sets.map((set) => set.acquired.map((found) => [found.kind, found.ident, found.sourceTier]))).toEqual([upgrade, [...upgrade, ...copy], [...upgrade, ...copy]]);
      expect(sets.map((set) => set.F.toString())).toEqual([path.steps[0].F, path.steps[1].F, path.steps[1].F].map(String));
      expect(path.steps[0].F.compare(path.steps[1].F)).toBe(-1);
    } finally {
      closeSession(session);
    }
  });

  it("lists each upgrade with the copies of it, then the new items, then the extra copies of what is owned", () => {
    const session = make();
    try {
      const stud = gear("stud", ["EAR"], { stats: { HP: 9 } });
      const helm = gear("helm", ["HEAD"], { stats: { HP: 30 } });
      const have = [[ring("ring", 10, 0), 1], [stud, 1]];
      const offered = [helm, stud, ring("ring", 20, 3)]; // (in no order of the list)
      const four = bestSets(session, have, offered, 4, { budgetMs: BUDGET_MS, canonical: true });
      expect(four.acquired.map((found) => [found.ident, found.kind, found.sourceTier])).toEqual([
        ["ring@3", "upgrade", 0],
        ["ring@3", "copy", null],
        ["helm@0", "new", null],
        ["stud@0", "copy", null],
      ]);
      expect(four.gain.toString()).toBe("69/1"); // the first ring wear is worth 10 more than the owned one, the second 20, the helm 30 and the second stud 9
      const three = bestSets(session, have, offered, 3, { budgetMs: BUDGET_MS, canonical: true });
      expect(three.acquired.map((found) => [found.ident, found.kind])).toEqual([["ring@3", "upgrade"], ["ring@3", "copy"], ["helm@0", "new"]]);
      expect(three.gain.toString()).toBe("60/1");
    } finally {
      closeSession(session);
    }
  });

  it("keeps a model of its own for each k, besides Equip now's and the path's", () => {
    const session = make();
    try {
      for (const k of [2, 3]) bestSets(session, owned(), candidates(), k, { budgetMs: BUDGET_MS });
      farmPath(session, owned(), candidates(), { steps: 1, budgetMs: BUDGET_MS });
      expect([...session.scenarios.keys()].sort()).toEqual(["best-1", "best-2", "best-3", "equip-now"]);
      expect(session.scenarios.get("best-2").solver).not.toBe(session.scenarios.get("best-3").solver);
      const rows = (name) => session.scenarios.get(name).model.row_names;
      expect(rows("best-2")).toContain("new.limit");
      for (const name of ["best-1", "best-2", "best-3"]) solverIs(expect, highs, session, name);
    } finally {
      closeSession(session);
    }
  });

  it("asked twice, and after the owned set changed, answers for the owned set it is given", () => {
    const session = make();
    try {
      const first = bestSets(session, owned(), candidates(), 2, { budgetMs: BUDGET_MS, canonical: true });
      const again = bestSets(session, owned(), candidates(), 2, { budgetMs: BUDGET_MS, canonical: true });
      expect(idents(again)).toEqual(idents(first));
      expect(again.F.toString()).toBe(first.F.toString());
      expect(first.solution.start).toBe("kit"); // it begins from the kit of Equip now, which is feasible in the model of k additions
      // the visitor owns ringB too now: the upgrade and a copy of it are the best set (20 + 20 against 10 + 15), and the numbers move with the owned set
      const more = bestSets(session, [...owned(), [ring("ringB", 15, 0), 1]], candidates(), 2, { budgetMs: BUDGET_MS, canonical: true });
      expect(idents(more)).toEqual(["ringA@3", "ringA@3"]);
      expect(more.gain.toString()).toBe("15/1");
      expect(more.baseline.F.toString()).toBe(first.baseline.F.add(q(15)).toString());
    } finally {
      closeSession(session);
    }
  });

  it("answers that nothing improves the value, with Equip now's kit, when no addition does", () => {
    const session = make();
    try {
      const rings = [[ring("ringA", 30, 0), 2]];
      const worse = bestSets(session, rings, [ring("ringB", 5, 0), ring("ringC", 20, 0)], 2, { budgetMs: BUDGET_MS, canonical: true });
      expect(worse.acquired).toEqual([]);
      expect(worse.gain.toString()).toBe("0/1");
      expect(worse.F.toString()).toBe(worse.baseline.F.toString());
      expect(worse.status).toBe("optimal");
      expect(worse.kit).toEqual(worse.baseline.kit);
      // and with no candidates at all, or none that adds anything (a Lore copy adds nothing)
      const none = bestSets(session, rings, [], 3, { budgetMs: BUDGET_MS });
      expect(none.acquired).toEqual([]);
      expect(none.F.toString()).toBe(none.baseline.F.toString());
      expect(none.solution).toBeNull();
      const lore = bestSets(session, [[ring("ringL", 30, 0, { lore: true }), 1]], [ring("ringL", 30, 0, { lore: true })], 2, { budgetMs: BUDGET_MS });
      expect(lore.acquired).toEqual([]);
    } finally {
      closeSession(session);
    }
  });

  it("gives the solve all the time that is left and starts nothing once the budget is spent", () => {
    let clock = 0;
    const spied = spyOn(highs, { clock: () => clock, after: () => (clock = 1001) });
    const session = createSession({ highs: spied.highs, profile, setup: "stick", options, now: () => clock });
    try {
      const got = bestSets(session, owned(), candidates(), 2, { budgetMs: 1000 });
      expect(spied.log.limits[0].limitMs).toBe(1000); // Equip now has the whole budget; it spends it
      expect(got.baseline.status).toBe("optimal");
      expect(got.status).toBe("time_limit"); // nothing of the set was begun: no plan, no model, no solve
      expect(got.label).toBe(LABEL_NO_INCUMBENT);
      expect(got.acquired).toEqual([]);
      expect(got.F).toBeNull();
      expect(got.kit).toBeNull();
      expect(spied.log.created).toBe(1);
      expect(spied.log.runs).toHaveLength(1);
      expect(session.scenarios.has("best-2")).toBe(false);
    } finally {
      closeSession(session);
    }
    // with the clock standing still the set's solve is handed the whole budget too
    const still = spyOn(highs);
    const quiet = createSession({ highs: still.highs, profile, setup: "stick", options, now: () => 0 });
    try {
      const got = bestSets(quiet, owned(), candidates(), 2, { budgetMs: 5000 });
      expect(got.status).toBe("optimal");
      expect(still.log.limits.map((limit) => limit.limitMs)).toEqual([5000, 5000]);
    } finally {
      closeSession(quiet);
    }
  });

  it("labels a set that ran out of time with an incumbent that adds something, and says 'not found in time' when it has none", () => {
    const states = highs.constants.modelStatus;
    // the second run is the set's: it ends as if the time had run out
    const incumbent = spyOn(highs, { outcome: (result) => (incumbent.log.runs.length === 2 ? { ...result, modelStatus: states.timeLimit } : result) });
    const session = createSession({ highs: incumbent.highs, profile, setup: "stick", options });
    try {
      const got = bestSets(session, owned(), candidates(), 2, { budgetMs: BUDGET_MS });
      expect(got.status).toBe("time_limit");
      expect(got.label).toBe(LABEL_TIME_LIMIT);
      expect(idents(got)).toEqual(["ringA@3", "ringA@3"]); // the incumbent was the best there is here
      expect(got.F.sub(got.baseline.F).toString()).toBe("30/1"); // valued exactly, whatever the solver said
    } finally {
      closeSession(session);
    }
    const none = spyOn(highs, {
      outcome: (result) => (none.log.runs.length === 2 ? { ...result, modelStatus: states.timeLimit } : result),
      info: (key, value) => (none.log.runs.length === 2 && key === "primal_solution_status" ? highs.constants.solutionStatus.none : value),
    });
    const bare = createSession({ highs: none.highs, profile, setup: "stick", options });
    try {
      const got = bestSets(bare, owned(), candidates(), 2, { budgetMs: BUDGET_MS });
      expect(got.status).toBe("time_limit");
      expect(got.label).toBe(LABEL_NO_INCUMBENT);
      expect(got.acquired).toEqual([]);
      expect(got.F).toBeNull();
      expect(got.gain).toBeNull();
      expect(got.kit).toBeNull();
      expect(got.solution.kit).toBeNull();
    } finally {
      closeSession(bare);
    }
  });

  it("ends with nothing found when Equip now itself ran out of time", () => {
    const session = make();
    try {
      const got = bestSets(session, owned(), candidates(), 2, { budgetMs: 0 });
      expect(got.baseline.status).toBe("time_limit");
      expect(got.status).toBe("time_limit");
      expect(got.label).toBe(LABEL_NO_INCUMBENT);
      expect(got.acquired).toEqual([]);
      expect(got.F).toBeNull();
      expect(got.gain).toBeNull();
      expect(session.scenarios.has("best-2")).toBe(false);
    } finally {
      closeSession(session);
    }
  });

  it("says 'not found in time' when Equip now ran out of time with a kit: a result with no value has no kit to label", () => {
    // the first run, Equip now's, ends as if the time had run out, but with the solution it had: an incumbent, labelled "best found" on its own
    const states = highs.constants.modelStatus;
    const spied = spyOn(highs, { outcome: (result) => (spied.log.runs.length === 1 ? { ...result, modelStatus: states.timeLimit } : result) });
    const session = createSession({ highs: spied.highs, profile, setup: "stick", options });
    try {
      const got = bestSets(session, owned(), candidates(), 2, { budgetMs: BUDGET_MS });
      expect(got.baseline.status).toBe("time_limit");
      expect(got.baseline.kit).not.toBeNull();
      expect(got.baseline.label).toBe(LABEL_TIME_LIMIT);
      expect(got.status).toBe("time_limit");
      expect(got.label).toBe(LABEL_NO_INCUMBENT); // the set has no value, whatever Equip now had
      expect(got.F).toBeNull();
      expect(got.gain).toBeNull();
      expect(got.kit).toBeNull();
      expect(got.acquired).toEqual([]);
      expect(got.solution).toBeNull();
      expect(spied.log.created).toBe(1); // nothing of the set was begun
      expect(session.scenarios.has("best-2")).toBe(false);
    } finally {
      closeSession(session);
    }
  });

  it("refuses what it does not read", () => {
    const session = make();
    try {
      const ask = (k, request = { budgetMs: 1000 }) => () => bestSets(session, owned(), candidates(), k, request);
      for (const bad of [0, -1, 1.5, "2", null, undefined, Number.NaN]) expect(ask(bad), String(bad)).toThrow(PathError);
      expect(ask(2, { budgetMs: -1 })).toThrow(PathError);
      expect(ask(2, {})).toThrow(PathError);
      expect(ask(2, { budgetMs: 1000, steps: 3 })).toThrow(/steps/);
      expect(ask(2, { budgetMs: 1000, canonical: "yes" })).toThrow(PathError);
      expect(() => bestSets(session, "a", candidates(), 2, { budgetMs: 1000 })).toThrow(PathError);
      expect(() => bestSets(session, owned(), [ring("a", 1), ring("a", 1)], 2, { budgetMs: 1000 })).toThrow(/twice/);
      expect(() => bestSets({}, owned(), candidates(), 2, { budgetMs: 1000 })).toThrow(PathError);
    } finally {
      closeSession(session);
    }
  });

  it("does not change what it is given", () => {
    const session = make();
    try {
      const given = deepFreeze({ owned: owned(), candidates: candidates() });
      const before = JSON.stringify(given);
      bestSets(session, given.owned, given.candidates, 2, { budgetMs: BUDGET_MS, canonical: true });
      expect(JSON.stringify(given)).toBe(before);
    } finally {
      closeSession(session);
    }
  });
});

describe("sessionHaste", () => {
  const weapons = (changes = {}) => profileWith({ weights: { DMG: 100 }, ...changes });
  const boots = gear("boots", ["FEET"], { haste: 20 });
  const quick = gear("quick", ["HEAD"], { haste: 45 });
  const options = { any_rule: "explicit" };

  it("is the options' own value when they give one", () => {
    expect(sessionHaste(weapons(), [[boots, 1]], [quick], "2h", null, { haste_assumed: 12 })).toBe(12);
  });

  it("is null when they give none: every kit is valued at the haste it counts, whatever the items, the profile's spell haste and the buffs", () => {
    expect(sessionHaste(weapons(), [[boots, 1]], [], "2h", null, options)).toBeNull();
    expect(sessionHaste(weapons(), [[boots, 1]], [quick], "2h", null, options)).toBeNull();
    expect(sessionHaste(weapons({ spell_haste: 40 }), [[boots, 1]], [quick], "2h", null, options)).toBeNull();
    const buffset = buffsetOf({ optional: [buffOf(1, { HASTE: 25 }), buffOf(2, { HASTE: 10 })], conflicts: [[1, 2]] });
    expect(sessionHaste(weapons(), [[boots, 1]], [], "2h", buffset, options)).toBeNull();
    expect(sessionHaste(weapons({ haste_cap: 85 }), [], [quick], "2h", null, options)).toBeNull();
  });

  it("checks the owned set, the candidates and the options, and an owned count of 0 is not owned", () => {
    expect(() => sessionHaste(weapons(), [[boots, 1]], [], "2h", null, { owned_caps: { "boots@0": 1 } })).not.toThrow(); // the options are the builder's; they are read
    expect(() => sessionHaste(weapons(), [[boots, 1]], [], "2h", null, { not_an_option: 1 })).toThrow();
    expect(() => sessionHaste(weapons(), [[boots, -1]], [], "2h", null, options)).toThrow(PathError);
    expect(() => sessionHaste(weapons(), [[quick, 0]], [boots], "2h", null, options)).not.toThrow();
  });
});

describe("Every slot", () => {
  const profile = profileWith({ weights: { HP: 1 } });
  const options = { any_rule: "explicit", haste_assumed: 0 };
  const make = () => createSession({ highs, profile, setup: "stick", options });
  const head = (key, hp, more = {}) => gear(key, ["HEAD"], { stats: { HP: hp }, ...more });
  const emptyKit = () => new Array(22).fill(null);

  it("gives the best swaps of each place, best gain first, ties by (key, tier), with a worse item as a negative gain", () => {
    const session = make();
    try {
      const kit = emptyKit();
      kit[0] = head("worn", 20);
      const rows = everySlot(session, kit, [head("b-nine", 29), head("a-nine", 29), head("c-low", 5), head("d-mid", 22), head("worn", 20)], { limit: 3 });
      expect(rows).toHaveLength(22);
      expect(rows[0].place).toBe("HEAD");
      expect(rows[0].current.key).toBe("worn");
      expect(rows[0].swaps.map((swap) => [swap.item.key, swap.delta.toString()])).toEqual([["a-nine", "9/1"], ["b-nine", "9/1"], ["d-mid", "2/1"]]);
      const all = everySlot(session, kit, [head("c-low", 5), head("worn", 20)], { limit: 3 });
      expect(all[0].swaps.map((swap) => [swap.item.key, swap.delta.toString()])).toEqual([["c-low", "-15/1"]]); // the item worn is not offered for its own place
      expect(all[1].swaps).toEqual([]); // nothing fits the face
      expect(everySlot(session, kit, [head("a", 21), head("b", 22)], { limit: 0 })[0].swaps).toEqual([]);
    } finally {
      closeSession(session);
    }
  });

  it("does not offer a Lore item worn in another place, a two-hander over a worn off hand, or anything in the off hand under a two-hander", () => {
    const session = createSession({ highs, profile, setup: "stick", options });
    try {
      const sword = gear("sword", ["PRIMARY", "SECONDARY"], { stats: { HP: 3 }, weapon: oneHand(10, 20) });
      const dagger = gear("dagger", ["PRIMARY", "SECONDARY"], { stats: { HP: 2 }, weapon: oneHand(5, 20) });
      const axe = gear("axe", ["PRIMARY"], { stats: { HP: 9 }, weapon: twoHand(40, 60) });
      const kit = emptyKit();
      kit[20] = sword; // PRIMARY
      kit[21] = dagger; // SECONDARY
      const rows = everySlot(session, kit, [axe, sword, dagger], { limit: 5 });
      const primary = rows[20];
      expect(primary.place).toBe("PRIMARY");
      expect(primary.swaps.map((swap) => swap.item.key)).toEqual(["dagger"]); // the axe would leave the worn off hand with nothing: not offered
      const bare = emptyKit();
      bare[20] = axe;
      const under = everySlot(session, bare, [sword, dagger], { limit: 5 });
      expect(under[21].swaps).toEqual([]); // nothing in the off hand under a two-hander
      expect(under[20].swaps.map((swap) => swap.item.key).sort()).toEqual(["dagger", "sword"]);
      // a Lore ring worn in one finger place is not offered for the other
      const sigil = gear("sigil", ["FINGER"], { stats: { HP: 7 }, lore: true });
      const worn = emptyKit();
      worn[11] = sigil;
      const fingers = everySlot(session, worn, [sigil, gear("plain", ["FINGER"], { stats: { HP: 1 } })], { limit: 5 });
      expect(fingers[12].swaps.map((swap) => swap.item.key)).toEqual(["plain"]);
      expect(fingers[11].swaps.map((swap) => swap.item.key)).toEqual(["plain"]); // and its own place is not offered itself
    } finally {
      closeSession(session);
    }
  });

  it("leaves out the items the profile cannot use, and values the swaps under the buffs of the kit", () => {
    const buffset = buffsetOf({ optional: [buffOf(7, { HP: 100 })] });
    const session = createSession({ highs, profile: profileWith({ weights: { HP: 1 } }), setup: "stick", buffset, options });
    try {
      const kit = emptyKit();
      kit[0] = head("worn", 20);
      const foreign = head("foreign", 99, { classes: ["MNK"] });
      const rows = everySlot(session, { kit, buffs: [7] }, [foreign, head("b", 30)], { limit: 3 });
      expect(rows[0].swaps.map((swap) => swap.item.key)).toEqual(["b"]);
      const asArray = everySlot(session, kit, [head("b", 30)], { buffs: [7], limit: 3 });
      expect(asArray[0].swaps.map((swap) => swap.delta.toString())).toEqual(["10/1"]);
      expect(() => everySlot(session, kit, [head("b", 30)], { buffs: [8] })).toThrow(PathError); // a buff that is not one of the set
    } finally {
      closeSession(session);
    }
  });

  it("refuses a kit that is not 22 places, a candidate offered twice and a limit that is not a count", () => {
    const session = make();
    try {
      expect(() => everySlot(session, [null, null], [], {})).toThrow(PathError);
      expect(() => everySlot(session, emptyKit(), [head("a", 1), head("a", 2)], {})).toThrow(/twice/);
      expect(() => everySlot(session, emptyKit(), [], { limit: -1 })).toThrow(PathError);
      expect(() => everySlot(session, emptyKit(), [], { limit: 1.5 })).toThrow(PathError);
      expect(() => everySlot(session, emptyKit(), [], { extra: 1 })).toThrow(/extra/);
    } finally {
      closeSession(session);
    }
  });

  // The items on offer are the candidates of the tier mode and the items the visitor owns. A candidate may be got again, so a swap to one has no count; an owned
  // item that is not a candidate is a swap for a place only while the visitor owns more of it than the kit wears in the other places (one ring, owned once and worn
  // on Finger 1, is not a swap for Finger 2).
  describe("counts the copies of the items the visitor owns", () => {
    const FINGER_1 = 11;
    const FINGER_2 = 12;
    const ANY_1 = 18;
    const ANY_2 = 19;
    const ring = gear("ring", ["FINGER"], { stats: { HP: 5 } });
    const wearing = (...entries) => {
      const kit = emptyKit();
      for (const [at, item] of entries) kit[at] = item;
      return kit;
    };
    const swapsOf = (row) => row.swaps.map((swap) => [swap.item.key, swap.delta.toString()]);
    const withSession = (body, changes = {}) => {
      const session = createSession({ highs, profile, setup: "stick", options: { ...options, ...changes } });
      try {
        return body(session);
      } finally {
        closeSession(session);
      }
    };

    it("does not offer a ring owned once and worn on the first finger for the second, and offers it once a second copy is owned", () => {
      withSession((session) => {
        const kit = wearing([FINGER_1, ring]);
        const once = everySlot(session, kit, [], { owned: [[ring, 1]] });
        expect(once[FINGER_1].swaps).toEqual([]); // (the item worn in a place is not offered for it)
        expect(once[FINGER_2].swaps).toEqual([]); // the one ring is on Finger 1
        const twice = everySlot(session, kit, [], { owned: [[ring, 2]] });
        expect(twice[FINGER_1].swaps).toEqual([]);
        expect(swapsOf(twice[FINGER_2])).toEqual([["ring", "5/1"]]); // a spare copy is a swap, worth the ring
        expect(swapsOf(everySlot(session, kit, [], { owned: new Map([[ring, 2]]) })[FINGER_2])).toEqual([["ring", "5/1"]]); // a Map of item to count is an owned set too
      });
    });

    it("puts no count on a candidate, and an item that is owned and a candidate counts as a candidate", () => {
      withSession((session) => {
        const kit = wearing([FINGER_1, ring]);
        for (const request of [{}, { owned: [] }, { owned: [[ring, 1]] }, { owned: [[ring, 3]] }]) {
          expect(swapsOf(everySlot(session, kit, [ring], request)[FINGER_2]), JSON.stringify(request.owned?.map(([, count]) => count))).toEqual([["ring", "5/1"]]); // another copy: the swap means getting it
        }
      });
    });

    it("counts the copies the kit wears in all its other places: a swap needs more owned than that", () => {
      withSession(
        (session) => {
          const kit = wearing([FINGER_1, ring], [ANY_1, ring]); // a ring fits an Any place under the "all" rule
          const two = everySlot(session, kit, [], { owned: [[ring, 2]] });
          expect(two.filter((row) => row.swaps.length > 0)).toEqual([]); // both rings are worn: a third place has none to take
          const three = everySlot(session, kit, [], { owned: [[ring, 3]] });
          expect(three.filter((row) => row.swaps.length > 0).map((row) => row.index)).toEqual([FINGER_2, ANY_2]); // one spare: the free places
        },
        { any_rule: "all" },
      );
    });

    it("leaves Lore as it is: a Lore item worn in another place is not offered, however many are owned or whether it is a candidate", () => {
      withSession((session) => {
        const sigil = gear("sigil", ["FINGER"], { stats: { HP: 9 }, lore: true });
        const kit = wearing([FINGER_1, sigil]);
        for (const [owned, candidates] of [[[[sigil, 1]], []], [[[sigil, 3]], []], [[[sigil, 1]], [sigil]], [[], [sigil]]]) {
          expect(everySlot(session, kit, candidates, { owned })[FINGER_2].swaps, `${owned.length} owned, ${candidates.length} candidates`).toEqual([]);
        }
        const bare = everySlot(session, emptyKit(), [], { owned: [[sigil, 1]] });
        expect(swapsOf(bare[FINGER_1])).toEqual([["sigil", "9/1"]]); // worn nowhere: a swap for either finger
        expect(swapsOf(bare[FINGER_2])).toEqual([["sigil", "9/1"]]);
      });
    });

    it("leaves out an owned item the profile cannot use, and refuses an owned set that is not one", () => {
      withSession((session) => {
        const foreign = gear("foreign", ["HEAD"], { stats: { HP: 99 }, classes: ["MNK"] });
        const head = gear("head", ["HEAD"], { stats: { HP: 3 } });
        expect(everySlot(session, emptyKit(), [], { owned: [[foreign, 1], [head, 1]] })[0].swaps.map((swap) => swap.item.key)).toEqual(["head"]);
        expect(everySlot(session, emptyKit(), [], { owned: [[head, 0]] })[0].swaps).toEqual([]); // none owned
        for (const bad of [[[ring, -1]], [[ring, 1.5]], [[ring, "2"]], [[ring, null]], [[ring, 1], [ring, 2]], [[{ key: "x" }, 1]], [[ring]], [ring], 5, null, "ring"]) {
          expect(() => everySlot(session, emptyKit(), [], { owned: bad }), JSON.stringify(bad)).toThrow(PathError);
        }
        expect(() => everySlot(session, emptyKit(), [], { owned: [[ring, 1], [ring, 2]] })).toThrow(/owned twice/);
        const holey = [[ring, 1]];
        holey.length = 2;
        expect(() => everySlot(session, emptyKit(), [], { owned: holey })).toThrow(/hole/);
      });
    });

    it("values a swap at the haste the swapped kit counts when none is fixed: a haste item swapped in changes what the weapons are worth, and an owned item that is not worn counts for nothing", () => {
      const weapons = profileWith({ weights: { DMG: 100 } });
      const sword = gear("sword", ["PRIMARY", "SECONDARY"], { stats: { HP: 3 }, weapon: oneHand(10, 20) });
      const boots = gear("boots", ["FEET"], { haste: 20 });
      const session = createSession({ highs, profile: weapons, setup: "dw", options: { any_rule: "explicit" } });
      try {
        const kit = wearing([20, sword]);
        const rows = everySlot(session, kit, [], { owned: [[sword, 2], [boots, 1]] });
        expect(rows[21].swaps.map((swap) => swap.item.key)).toEqual(["sword"]);
        const trial = wearing([20, sword], [21, sword]);
        const gainAt = (hasteAssumed) => evaluate(weapons, trial, null, { setup: "dw", hasteAssumed }).F.sub(evaluate(weapons, kit, null, { setup: "dw", hasteAssumed }).F);
        expect(gainAt(20).toString()).not.toBe(gainAt(0).toString()); // the weapon index depends on the haste
        expect(rows[21].swaps[0].delta.toString()).toBe(gainAt(0).toString()); // neither kit wears the boots: both count no haste
        // the boots swapped in for the feet raise the haste of the kit: the swap is worth the weapon index at 20 percent and not at 0
        const feet = rows[SLOT_INSTANCES.indexOf("FEET")];
        expect(feet.swaps.map((swap) => swap.item.key)).toEqual(["boots"]);
        const shod = wearing([20, sword], [SLOT_INSTANCES.indexOf("FEET"), boots]);
        expect(feet.swaps[0].delta.toString()).toBe(evaluateTruthful(weapons, shod, null, { setup: "dw" }).F.sub(evaluateTruthful(weapons, kit, null, { setup: "dw" }).F).toString());
        expect(feet.swaps[0].delta.toString()).toBe(evaluate(weapons, shod, null, { setup: "dw", hasteAssumed: 20 }).F.sub(evaluate(weapons, kit, null, { setup: "dw", hasteAssumed: 0 }).F).toString());
      } finally {
        closeSession(session);
      }
    });
  });
});

describe("malformed input", () => {
  const profile = profileWith({ weights: { HP: 1 } });
  const buffset = buffsetOf({ always: [buffOf(3, {})], optional: [buffOf(7, { HP: 100 })] });
  const make = (extra = {}) => createSession({ highs, profile, setup: "stick", options: { any_rule: "explicit", haste_assumed: 0 }, ...extra });
  const ring = (key, hp, tier = 0) => gear(key, ["FINGER"], { stats: { HP: hp }, tier });
  const without = (item, field) => {
    const copy = { ...item };
    delete copy[field];
    return copy;
  };
  const holey = (list) => {
    const copy = [...list, list[0]];
    delete copy[copy.length - 1];
    return copy;
  };
  const emptyKit = () => new Array(22).fill(null);
  /** Items that lack what the functions read: each is an error of the module, and none is a TypeError. */
  const BROKEN = {
    "no classes": without(ring("a", 1), "classes"),
    "classes that are not a list": { ...ring("a", 1), classes: "WAR" },
    "no weapon field": without(ring("a", 1), "weapon"),
    "no deity field": without(ring("a", 1), "deity"),
    "no races field": without(ring("a", 1), "races"),
    "no haste": without(ring("a", 1), "haste"),
    "no slots": without(ring("a", 1), "slots"),
    "no key": without(ring("a", 1), "key"),
    "no lore": without(ring("a", 1), "lore"),
    "no is_shield": without(ring("a", 1), "is_shield"),
    "a tier that is not one": { ...ring("a", 1), tier: 99 },
    "a weapon that is not one": { ...ring("a", 1), weapon: 5 },
    "a deity that is not a list": { ...ring("a", 1), deity: "Brell" },
    "not an object": 5,
    "null": null,
    "undefined": undefined,
  };

  it("refuses an item that lacks what is read, at the door of every function, with an error of its own", () => {
    const session = make();
    try {
      for (const [what, bad] of Object.entries(BROKEN)) {
        expect(() => classify(bad, []), `classify, candidate: ${what}`).toThrow(PathError);
        expect(() => classify(ring("b", 1), [[bad, 1]]), `classify, owned: ${what}`).toThrow(PathError);
        expect(() => sessionHaste(profile, [[bad, 1]], [], "stick", null, {}), `sessionHaste, owned: ${what}`).toThrow(PathError);
        expect(() => sessionHaste(profile, [], [bad], "stick", null, {}), `sessionHaste, candidate: ${what}`).toThrow(PathError);
        expect(() => equipNow(session, [[bad, 1]], { budgetMs: 100 }), `equipNow: ${what}`).toThrow(PathError);
        expect(() => farmPath(session, [[bad, 1]], [ring("b", 2)], { budgetMs: 100 }), `farmPath, owned: ${what}`).toThrow(PathError);
        expect(() => farmPath(session, [], [bad], { budgetMs: 100 }), `farmPath, candidate: ${what}`).toThrow(PathError);
        const kit = emptyKit();
        kit[0] = bad;
        if (bad !== null) expect(() => everySlot(session, kit, [], {}), `everySlot, kit: ${what}`).toThrow(PathError);
        expect(() => everySlot(session, emptyKit(), [bad], {}), `everySlot, candidate: ${what}`).toThrow(PathError);
      }
    } finally {
      closeSession(session);
    }
  });

  it("takes an item whose weapon, deity and races are null, as atTier writes them, and refuses one that has no such field", () => {
    const session = make();
    try {
      const kit = emptyKit();
      kit[20] = gear("sword", ["PRIMARY"], { stats: { HP: 3 } }); // weapon, deity and races null
      expect(everySlot(session, kit, [gear("dagger", ["PRIMARY"], { stats: { HP: 2 } })], {})).toHaveLength(22);
      expect(sessionHaste(profile, [[ring("a", 1), 1]], [ring("b", 1)], "stick", null, {})).toBeNull();
      expect(equipNow(session, [[ring("a", 1), 1]], { budgetMs: 60_000 }).status).toBe("optimal");
      for (const field of ["weapon", "deity", "races"]) {
        const bad = without(ring("a", 1), field);
        expect(() => classify(bad, []), field).toThrow(new RegExp(`${field} is missing`));
        expect(() => sessionHaste(profile, [], [bad], "stick", null, { haste_assumed: 5 }), field).toThrow(PathError); // the options do not excuse it
      }
    } finally {
      closeSession(session);
    }
  });

  it("refuses a hole in a list as it refuses an entry that is not an item", () => {
    const session = make();
    try {
      const owned = [[ring("a", 1), 1], [ring("b", 2), 1]];
      const candidates = [ring("c", 3), ring("d", 4)];
      expect(() => farmPath(session, owned, holey(candidates), { budgetMs: 100 })).toThrow(PathError);
      expect(() => farmPath(session, owned, holey(candidates), { budgetMs: 100 })).toThrow(/hole/);
      expect(() => farmPath(session, holey(owned), candidates, { budgetMs: 100 })).toThrow(PathError);
      expect(() => equipNow(session, holey(owned), { budgetMs: 100 })).toThrow(PathError);
      expect(() => sessionHaste(profile, owned, holey(candidates), "stick", null, {})).toThrow(PathError);
      expect(() => sessionHaste(profile, holey(owned), candidates, "stick", null, {})).toThrow(PathError);
      expect(() => classify(ring("c", 3), holey(owned))).toThrow(PathError);
      const kit = emptyKit();
      delete kit[5];
      expect(() => everySlot(session, kit, candidates, {})).toThrow(PathError);
      expect(() => everySlot(session, kit, candidates, {})).toThrow(/hole/);
      expect(() => everySlot(session, { kit, buffs: [] }, candidates, {})).toThrow(/hole/);
      expect(() => everySlot(session, emptyKit(), holey(candidates), {})).toThrow(/hole/);
    } finally {
      closeSession(session);
    }
  });

  it("wants every place of a kit to be null or an item", () => {
    const session = make();
    try {
      for (const bad of [undefined, 0, "", "ring", {}, [], true]) {
        const kit = emptyKit();
        kit[3] = bad;
        expect(() => everySlot(session, kit, [], {}), String(bad)).toThrow(PathError);
      }
      expect(() => everySlot(session, { kit: "no", buffs: [] }, [], {})).toThrow(PathError);
      expect(() => everySlot(session, { kit: null, buffs: [] }, [], {})).toThrow(PathError);
      expect(() => everySlot(session, null, [], {})).toThrow(PathError);
    } finally {
      closeSession(session);
    }
  });

  it("wants the buffs of Every slot, from the request or from the kit, to be ids of the buff set", () => {
    const session = make({ buffset });
    const bare = make();
    try {
      const kit = emptyKit();
      kit[0] = gear("worn", ["HEAD"], { stats: { HP: 20 } });
      const head = gear("b", ["HEAD"], { stats: { HP: 30 } });
      for (const bad of [[8], ["7"], [1.5], [Number.NaN], [-1], [null], [7, 8], [[7]], "7", 7, { 7: true }, holey([7])]) {
        expect(() => everySlot(session, kit, [head], { buffs: bad }), `request ${JSON.stringify(bad)}`).toThrow(PathError);
        expect(() => everySlot(session, { kit, buffs: bad }, [head], {}), `kit.buffs ${JSON.stringify(bad)}`).toThrow(PathError);
      }
      expect(() => everySlot(session, { kit, buffs: [7, 8] }, [head], { buffs: [7] })).not.toThrow(); // the request replaces the kit's buffs
      expect(everySlot(session, kit, [head], { buffs: [7, 7, 3] })[0].swaps[0].delta.toString()).toBe("10/1"); // an id twice counts once; an always-on id is already counted
      expect(everySlot(session, { kit, buffs: [] }, [head], {})[0].swaps[0].delta.toString()).toBe("10/1");
      // a session with no buff set has no ids to choose
      expect(() => everySlot(bare, kit, [head], { buffs: [7] })).toThrow(PathError);
      expect(() => everySlot(bare, kit, [head], { buffs: [7] })).toThrow(/buff set/);
      expect(() => everySlot(bare, { kit, buffs: [7] }, [head], {})).toThrow(PathError);
      expect(everySlot(bare, { kit, buffs: [] }, [head], {})[0].swaps.length).toBe(1);
    } finally {
      closeSession(session);
      closeSession(bare);
    }
  });
});

describe("the arguments", () => {
  const profile = profileWith({ weights: { HP: 1 } });
  const options = { any_rule: "explicit", haste_assumed: 0 };
  const ring = (key, hp, tier = 0) => gear(key, ["FINGER"], { stats: { HP: hp }, tier });
  const make = () => createSession({ highs, profile, setup: "stick", options });

  it("refuses a request that is not understood, and says which option", () => {
    const session = make();
    try {
      const owned = [[ring("a", 1), 1]];
      const candidates = [ring("b", 2)];
      expect(() => farmPath(session, owned, candidates, {})).toThrow(/budgetMs/);
      expect(() => farmPath(session, owned, candidates, { budgetMs: -1 })).toThrow(/budgetMs/);
      expect(() => farmPath(session, owned, candidates, { budgetMs: 100, steps: -1 })).toThrow(/steps/);
      expect(() => farmPath(session, owned, candidates, { budgetMs: 100, steps: 1.5 })).toThrow(/steps/);
      expect(() => farmPath(session, owned, candidates, { budgetMs: 100, onStep: 3 })).toThrow(/onStep/);
      expect(() => farmPath(session, owned, candidates, { budgetMs: 100, canonical: "yes" })).toThrow(/canonical/);
      expect(() => farmPath(session, owned, candidates, { budgetMs: 100, speed: 1 })).toThrow(/speed/);
      expect(() => farmPath(session, owned, [ring("b", 2), ring("b", 3)], { budgetMs: 100 })).toThrow(/twice/);
      expect(() => farmPath(session, owned, "b", { budgetMs: 100 })).toThrow(PathError);
      expect(() => farmPath(null, owned, candidates, { budgetMs: 100 })).toThrow();
      expect(() => equipNow(session, owned, {})).toThrow(/budgetMs/);
      expect(() => equipNow(session, owned, { budgetMs: 100, steps: 3 })).toThrow(/steps/);
      expect(() => equipNow(session, [[ring("a", 1), 1], [ring("a", 1), 1]], { budgetMs: 100 })).toThrow(/twice/);
    } finally {
      closeSession(session);
    }
  });

  it("owns the owned-item options: a session cannot be given them", () => {
    expect(() => createSession({ highs, profile, setup: "stick", options: { owned_caps: { "a@0": 1 } } })).toThrow(/owned_caps/);
    expect(() => createSession({ highs, profile, setup: "stick", options: { max_new: 1 } })).toThrow(/max_new/);
  });

  it("does not change what it is given", () => {
    const session = make();
    try {
      const owned = deepFreeze([[ring("a", 5), 1]]);
      const candidates = deepFreeze([ring("b", 9), ring("a", 8, 2)]);
      const before = JSON.stringify([owned, candidates]);
      const got = farmPath(session, owned, candidates, { steps: 3, budgetMs: 60_000 });
      expect(got.steps.length).toBeGreaterThan(0);
      expect(JSON.stringify([owned, candidates])).toBe(before);
    } finally {
      closeSession(session);
    }
  });

  it("says 'not found in time' with the label of the protocol", () => {
    expect(LABEL_NO_INCUMBENT).toBe("not found in time");
  });
});
