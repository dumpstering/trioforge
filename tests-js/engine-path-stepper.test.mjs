import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { PathError, createFarmPath, equipNow, farmPath } from "../pipeline/trioforge/site/static/engine/path.js";
import { closeSession, createSession } from "../pipeline/trioforge/site/static/engine/solve.js";
import { caseOf, exact, identOf, kitPairs, sharedOf } from "./engine-cases.mjs";
import { SAMPLE } from "./engine-fixtures.mjs";
import { gear, profileWith } from "./engine-hand.mjs";
import { spyOn } from "./engine-spy.mjs";

// The stepper under the farm path (path.js, createFarmPath): the same path as farmPath makes, one call at a time, so that a caller can do something between
// the steps (the worker sends each step to the page and looks for a stop). farmPath is a loop over it, and its own tests (engine-path.test.mjs) hold both to
// Python; these hold the stepper itself: stepping by hand gives the recorded path, start() is Equip now, stop() ends the path before its next step, and the
// deadline is the one of the moment the path was made.

vi.setConfig({ testTimeout: 120_000 });
const BUDGET_MS = 900_000;

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const optionsOf = (doc) => ({ any_rule: doc.solves[0].options.any_rule });
const sessionFor = (c, doc, extra = {}) => createSession({ highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins, options: optionsOf(doc), ...extra });

/** Step a path to its end by hand: Equip now, then every step. */
function walk(path) {
  const baseline = path.start();
  const steps = [];
  for (let step = path.next(); step !== null; step = path.next()) steps.push(step);
  return { baseline, steps, result: path.result() };
}

describe("stepping by hand", () => {
  const shared = sharedOf(SAMPLE);
  for (const file of SAMPLE.paths("case", "upgrade/")) {
    const doc = SAMPLE.read(file);
    const { expected } = doc;

    it(`${doc.id} (${doc.label}): gives the recorded path, step by step, and ends for the recorded reason`, () => {
      const c = caseOf(shared, doc);
      const session = sessionFor(c, doc);
      try {
        const path = createFarmPath(session, c.owned(), c.candidates(), { steps: doc.inputs.steps, budgetMs: BUDGET_MS, canonical: true });
        const { baseline, steps, result } = walk(path);
        expect(baseline.status).toBe("optimal");
        expect(baseline.F.toString()).toBe(exact(doc.solves[expected.equip_now].result.F).toString());
        expect(steps.map((step) => step.index)).toEqual(expected.steps.map((want) => want.index));
        steps.forEach((step, at) => {
          const want = expected.steps[at];
          expect(identOf(step.item), `step ${want.index}: the item`).toBe(want.item);
          expect(step.kind).toBe(want.kind);
          expect(step.sourceTier).toBe(want.source_tier);
          expect(step.F.toString()).toBe(exact(want.F).toString());
          expect(step.gain.toString()).toBe(exact(want.gain).toString());
          expect(step.owned).toEqual(want.owned);
        });
        expect(result.stopped).toBe(expected.stopped);
        expect(result.hasteAssumed, "the haste of Equip now").toBe(doc.solves[expected.equip_now].result.haste_assumed);
        // the result is the very objects that were handed out, and asking again after the end gives nothing
        expect(result.baseline).toBe(baseline);
        result.steps.forEach((step, at) => expect(step).toBe(steps[at]));
        expect(path.next()).toBeNull();
        expect(path.result()).toBe(result);
        expect(result.elapsedMs).toBeGreaterThan(0);
      } finally {
        closeSession(session);
      }
    }, 600_000);
  }

  it("is the path farmPath makes: farmPath is a loop over the stepper and streams the objects that it returns", () => {
    const doc = SAMPLE.read(SAMPLE.paths("case", "upgrade/")[0]);
    const c = caseOf(shared, doc);
    const session = sessionFor(c, doc);
    try {
      const streamed = [];
      const whole = farmPath(session, c.owned(), c.candidates(), { steps: doc.inputs.steps, budgetMs: BUDGET_MS, canonical: true, onStep: (step) => streamed.push(step) });
      const by = walk(createFarmPath(session, c.owned(), c.candidates(), { steps: doc.inputs.steps, budgetMs: BUDGET_MS, canonical: true }));
      expect(by.steps.map((step) => [step.index, identOf(step.item), step.kind, step.F.toString(), step.gain.toString()])).toEqual(
        whole.steps.map((step) => [step.index, identOf(step.item), step.kind, step.F.toString(), step.gain.toString()]),
      );
      expect(by.result.stopped).toBe(whole.stopped);
      expect(by.result.hasteAssumed).toBe(whole.hasteAssumed);
      expect(by.baseline.F.toString()).toBe(whole.baseline.F.toString());
      expect(kitPairs(by.baseline.kit)).toEqual(kitPairs(whole.baseline.kit));
      streamed.forEach((step, at) => expect(step).toBe(whole.steps[at]));
      expect(streamed).toHaveLength(whole.steps.length);
    } finally {
      closeSession(session);
    }
  });
});

describe("by hand", () => {
  const profile = profileWith({ weights: { HP: 1 } });
  const ring = (key, hp, tier = 0, more = {}) => gear(key, ["FINGER"], { stats: { HP: hp }, tier, ...more });
  const options = { any_rule: "explicit", haste_assumed: 0 };
  const owned = () => [[ring("ringA", 10, 0), 1]];
  const candidates = () => [ring("ringA", 20, 3), ring("ringB", 15, 0), ring("ringA", 10, 0)];
  const make = (extra = {}) => createSession({ highs, profile, setup: "stick", options, ...extra });
  const request = (over = {}) => ({ steps: 6, budgetMs: 60_000, ...over });

  it("start() is Equip now: the answer of equipNow for the owned items, with the haste of the whole session", () => {
    const session = make();
    try {
      const path = createFarmPath(session, owned(), candidates(), request());
      const baseline = path.start();
      const alone = equipNow(make(), owned(), { budgetMs: 60_000 });
      expect(baseline.status).toBe("optimal");
      expect(baseline.F.toString()).toBe(alone.F.toString());
      expect(kitPairs(baseline.kit)).toEqual(kitPairs(alone.kit));
      expect(path.result().baseline).toBe(baseline);
      expect(path.result().hasteAssumed).toBe(0);
      expect(path.result().steps).toEqual([]);
    } finally {
      closeSession(session);
    }
  });

  it("walks a new item, an upgrade and a copy, and ends when no addition improves the value", () => {
    const session = make();
    try {
      const { steps, result } = walk(createFarmPath(session, owned(), candidates(), request({ canonical: true })));
      expect(steps.map((step) => [step.index, identOf(step.item), step.kind, step.sourceTier, step.gain.toString()])).toEqual([
        [1, "ringB@0", "new", null, "15/1"],
        [2, "ringA@3", "upgrade", 0, "10/1"],
        [3, "ringA@3", "copy", null, "5/1"],
      ]);
      expect(result.stopped).toBe("no-gain");
    } finally {
      closeSession(session);
    }
  });

  it("stop() after the first step: the next call gives nothing, the path says it was stopped, and it has the one step", () => {
    const session = make();
    try {
      const path = createFarmPath(session, owned(), candidates(), request());
      path.start();
      const first = path.next();
      expect(first).toMatchObject({ index: 1, found: true });
      path.stop();
      expect(path.next()).toBeNull();
      const result = path.result();
      expect(result.stopped).toBe("stopped");
      expect(result.steps).toEqual([first]);
      expect(result.steps[0]).toBe(first);
      expect(result.baseline).not.toBeNull();
      expect(result.hasteAssumed).toBe(0);
      expect(path.next()).toBeNull(); // and it stays ended
      expect(path.result().stopped).toBe("stopped");
    } finally {
      closeSession(session);
    }
  });

  it("stop() before start() leaves Equip now alone (start() still gives it) and ends the path before its first step", () => {
    const session = make();
    try {
      const path = createFarmPath(session, owned(), candidates(), request());
      path.stop();
      const baseline = path.start();
      expect(baseline.status).toBe("optimal");
      expect(path.next()).toBeNull();
      expect(path.result()).toMatchObject({ stopped: "stopped", steps: [] });
      expect(path.result().baseline).toBe(baseline);
    } finally {
      closeSession(session);
    }
  });

  it("stop() once the path has ended changes nothing, and stop() twice is stop() once", () => {
    const session = make();
    try {
      const path = createFarmPath(session, owned(), candidates(), request({ steps: 1 }));
      path.start();
      path.next();
      expect(path.next()).toBeNull();
      expect(path.result().stopped).toBe("limit");
      path.stop();
      expect(path.next()).toBeNull();
      expect(path.result().stopped).toBe("limit");
      const other = createFarmPath(session, owned(), candidates(), request());
      other.start();
      other.stop();
      other.stop();
      expect(other.next()).toBeNull();
      expect(other.result().stopped).toBe("stopped");
    } finally {
      closeSession(session);
    }
  });

  it("says nothing was made when there is nothing to add or no step is asked for (no Equip now: the path ended before there was one)", () => {
    const session = make();
    try {
      const bare = createFarmPath(session, owned(), [], request());
      expect(bare.start()).toBeNull();
      expect(bare.next()).toBeNull();
      expect(bare.result()).toMatchObject({ stopped: "no-gain", steps: [], baseline: null, hasteAssumed: null });
      const none = createFarmPath(session, owned(), candidates(), request({ steps: 0 }));
      expect(none.start()).toBeNull();
      expect(none.next()).toBeNull();
      expect(none.result()).toMatchObject({ stopped: "limit", steps: [], baseline: null });
    } finally {
      closeSession(session);
    }
  });

  it("is called in order: next() before start() and a second start() are mistakes", () => {
    const session = make();
    try {
      const path = createFarmPath(session, owned(), candidates(), request());
      expect(() => path.next()).toThrow(PathError);
      path.start();
      expect(() => path.start()).toThrow(PathError);
      expect(() => path.next()).not.toThrow();
    } finally {
      closeSession(session);
    }
  });

  it("takes the deadline from the moment the path is made: the time between the calls counts", () => {
    let clock = 0;
    const session = make({ now: () => clock });
    try {
      const path = createFarmPath(session, owned(), candidates(), request({ budgetMs: 1000 }));
      clock = 5000; // the budget is gone before the first call
      const baseline = path.start();
      expect(baseline.status, "Equip now always runs, with what is left: nothing").toBe("time_limit");
      expect(path.next()).toBeNull();
      expect(path.result().stopped).toBe("time");
      expect(path.result().steps).toEqual([]);
      // the same path made at that moment has its whole budget
      const fresh = createFarmPath(session, owned(), candidates(), request({ budgetMs: 1000 }));
      expect(fresh.start().status).toBe("optimal");
    } finally {
      closeSession(session);
    }
  });

  it("measures the time between two steps against the budget: a step that comes after the deadline is not begun", () => {
    let clock = 0;
    const spied = spyOn(highs, { clock: () => clock });
    const session = make({ highs: spied.highs, now: () => clock });
    try {
      const path = createFarmPath(session, owned(), candidates(), request({ budgetMs: 1000 }));
      path.start();
      expect(path.next()).toMatchObject({ index: 1 });
      const made = spied.log.created;
      clock = 1001; // the caller took its time between the steps
      expect(path.next()).toBeNull();
      expect(path.result().stopped).toBe("time");
      expect(spied.log.created, "no model was made for the step that was not begun").toBe(made);
    } finally {
      closeSession(session);
    }
  });

  describe("onBegin", () => {
    // `onBegin(number)` is called with the number of a step once next() has begun it: after the checks of the stop, the limit and the budget, and before the plan of the step
    // is made. A step that is not begun (the path was stopped, ended, reached its limit or has no time) is not announced.
    it("is called with the number of each step that is begun, in order, and once for each", () => {
      const session = make();
      try {
        const begun = [];
        const { steps } = walk(createFarmPath(session, owned(), candidates(), request({ canonical: true, onBegin: (number) => begun.push(number) })));
        expect(steps.map((step) => step.index)).toEqual([1, 2, 3]);
        expect(begun.slice(0, 3)).toEqual([1, 2, 3]);
        expect(begun.length, "the step that found nothing to add began too: it is the one that said so").toBe(4);
        expect(begun[3]).toBe(4);
      } finally {
        closeSession(session);
      }
    });

    it("is called after the look at the budget and before the plan is made: one look at the clock lies between the entry of next() and the call", () => {
      let looks = 0;
      const session = make({ now: () => (looks += 1, 0) });
      try {
        const seen = [];
        let entered = 0;
        const path = createFarmPath(session, owned(), candidates(), request({ onBegin: () => seen.push(looks - entered) }));
        path.start();
        for (const wanted of [1, 2]) {
          entered = looks;
          expect(path.next()).toMatchObject({ index: wanted });
        }
        expect(seen).toEqual([1, 1]); // the check of the budget is the one look; the plan, the pruning and the solve come after
      } finally {
        closeSession(session);
      }
    });

    it("is not called for a step that is not begun: after stop(), after the last step asked for, after a step that ended the path, and when the budget is spent", () => {
      const session = make();
      try {
        const begun = [];
        const onBegin = (number) => begun.push(number);
        // after stop()
        const stopped = createFarmPath(session, owned(), candidates(), request({ onBegin }));
        stopped.start();
        stopped.next();
        stopped.stop();
        expect(stopped.next()).toBeNull();
        expect(begun).toEqual([1]);
        // after the last step asked for
        begun.length = 0;
        const limited = createFarmPath(session, owned(), candidates(), request({ steps: 2, onBegin }));
        limited.start();
        limited.next();
        limited.next();
        expect(limited.next()).toBeNull();
        expect(limited.result().stopped).toBe("limit");
        expect(begun).toEqual([1, 2]);
        // before start() ended it, and with nothing to add
        begun.length = 0;
        const bare = createFarmPath(session, owned(), [], request({ onBegin }));
        expect(bare.start()).toBeNull();
        expect(bare.next()).toBeNull();
        expect(begun).toEqual([]);
      } finally {
        closeSession(session);
      }
    });

    it("is not called for the step after one that ended the path: a step not proven the best leaves no time, and the call after it begins nothing", () => {
      const states = highs.constants.modelStatus;
      // the second run is the first step's: it ends as if the time had run out (its kit is the best there is)
      const spied = spyOn(highs, { outcome: (result) => (spied.log.runs.length === 2 ? { ...result, modelStatus: states.timeLimit } : result) });
      const session = make({ highs: spied.highs });
      try {
        const begun = [];
        const path = createFarmPath(session, owned(), candidates(), request({ steps: 6, onBegin: (number) => begun.push(number) }));
        path.start();
        expect(path.next()).toMatchObject({ index: 1, found: true, status: "time_limit" });
        expect(path.next()).toBeNull();
        expect(path.result().stopped).toBe("time");
        expect(begun).toEqual([1]);
      } finally {
        closeSession(session);
      }
    });

    it("is not called for a step that comes when the budget is spent: the step before used it up, or the caller took its time", () => {
      let clock = 0;
      const spied = spyOn(highs, { clock: () => clock, before: () => (clock += 600) });
      const session = make({ highs: spied.highs, now: () => clock });
      try {
        const begun = [];
        const path = createFarmPath(session, owned(), candidates(), request({ budgetMs: 1500, steps: 6, onBegin: (number) => begun.push(number) }));
        path.start(); // Equip now ends at 600
        expect(path.next()).toMatchObject({ index: 1 }); // begun with 900 left, ends at 1200
        expect(path.next()).toMatchObject({ index: 2 }); // begun with 300 left, ends at 1800
        expect(path.next()).toBeNull(); // nothing is left
        expect(path.result().stopped).toBe("time");
        expect(begun).toEqual([1, 2]);
        // and a step that comes after the deadline because the caller was slow
        const late = createFarmPath(session, owned(), candidates(), request({ budgetMs: 1000, onBegin: (number) => begun.push(number * 10) }));
        late.start();
        clock += 5000;
        expect(late.next()).toBeNull();
        expect(begun).toEqual([1, 2]);
      } finally {
        closeSession(session);
      }
    });

    it("is a function or nothing, is read by createFarmPath only, and changes nothing of what the path finds", () => {
      const session = make();
      try {
        expect(() => createFarmPath(session, owned(), candidates(), request({ onBegin: "yes" }))).toThrow(/onBegin is a function/);
        expect(() => createFarmPath(session, owned(), candidates(), request({ onBegin: null }))).toThrow(PathError);
        expect(() => createFarmPath(session, owned(), candidates(), request({ onBegin: undefined }))).not.toThrow();
        expect(() => farmPath(session, owned(), candidates(), request({ onBegin: () => {} }))).toThrow(/does not read/);
        const plain = walk(createFarmPath(session, owned(), candidates(), request({ canonical: true })));
        const watched = walk(createFarmPath(session, owned(), candidates(), request({ canonical: true, onBegin: () => {} })));
        expect(watched.steps.map((step) => [step.index, identOf(step.item), step.kind, step.F.toString()])).toEqual(plain.steps.map((step) => [step.index, identOf(step.item), step.kind, step.F.toString()]));
        expect(watched.result.stopped).toBe(plain.result.stopped);
      } finally {
        closeSession(session);
      }
    });
  });

  it("refuses what farmPath refuses, and the options of farmPath that are not the stepper's", () => {
    const session = make();
    try {
      expect(() => createFarmPath({}, owned(), candidates(), request())).toThrow(PathError);
      expect(() => createFarmPath(session, owned(), candidates(), request({ steps: -1 }))).toThrow(/steps/);
      expect(() => createFarmPath(session, owned(), candidates(), request({ steps: 1.5 }))).toThrow(PathError);
      expect(() => createFarmPath(session, owned(), candidates(), { steps: 3 })).toThrow(/budgetMs/);
      expect(() => createFarmPath(session, owned(), candidates(), request({ canonical: "yes" }))).toThrow(/canonical/);
      expect(() => createFarmPath(session, owned(), candidates(), request({ onStep: () => {} }))).toThrow(/does not read/);
      expect(() => createFarmPath(session, owned(), candidates(), request({ haste: 1 }))).toThrow(/does not read/);
      expect(() => createFarmPath(session, owned(), [ring("a", 1), ring("a", 1)], request())).toThrow(/twice/);
      expect(() => createFarmPath(session, [[ring("a", 1), -1]], candidates(), request())).toThrow(PathError);
    } finally {
      closeSession(session);
    }
  });
});
