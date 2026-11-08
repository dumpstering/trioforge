import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { closeSession, createSession, setScenario, solve, solveScenario } from "../pipeline/trioforge/site/static/engine/solve.js";
import { caseOf, clone, deepFreeze, kitPairs, sharedOf } from "./engine-cases.mjs";
import { SAMPLE } from "./engine-fixtures.mjs";
import { spyOn } from "./engine-spy.mjs";

// The tie stage of the canonical solve chooses among the kits whose value is within 1e-7 of the best, and it is the dearest part of a canonical solve. When every kit of that
// band wears the items of the first stage's kit (the sets of items are settled), the tie stage has the buffs alone to choose among, and `itemsAreSettled` of solve.js proves it
// with a cheaper program; the tie stage then fixes the item columns (or, with no optional buff, is not run at all). The answer must be the answer of the whole tie stage, and
// the shortcut must not be taken when the band holds another set of items. `tieShortcut: false` runs the whole tie stage always: the reference here.
//
//   * Every recorded solve of the committed parity sample (matrix/, upgrade/, pmb36/ and the brute-force instances) comes out the same with and without the shortcut: the kit
//     place for place, the buffs, the exact value and the haste; and the whole tie stage is run less often.
//   * The pools of the sample with every worn item given a twin of the same stats under another key (two sets of items of the very same value): the answers are the same, and
//     the whole tie stage still runs (a shortcut that looked at the wrong kits would say "settled" here, and take the first stage's items).
//   * The buff sets of the sample with a twin of the first optional buff (the same effects under another id, excluding it, so that two buffs tie): the answers are the same, the buffs included.
//   * The truthful solve (`solveScenario`, the ladder of haste levels) takes the same option through, and is the same with and without.
//   * The proof and the tie stage have each the whole allowance of the call, as the first stage and the tie stage always had.

vi.setConfig({ testTimeout: 300_000 });
const BUDGET_MS = 600_000;

/**
 * HiGHS as the worker runs it, with its tie programs counted: a program that minimizes and has whole columns. The whole tie stage ends in the row of the band (a lower bound
 * only); the shortcut's has one row for each worn item after it, an equality (`last` keeps the program, for the tests that read it).
 */
let highs;
const counts = { tie: 0, whole: 0, last: null, keys: new Map() };
beforeAll(async () => {
  const loaded = await loadHighs();
  highs = Object.create(loaded, {
    createModel: {
      value(data, ...rest) {
        if (data.sense === loaded.constants.objectiveSense.minimize && data.integrality.some((flag) => flag === 1)) {
          counts.tie += 1;
          counts.last = data;
          const last = data.numRows - 1;
          if (data.rowLower[last] !== data.rowUpper[last]) counts.whole += 1;
        }
        const solver = loaded.createModel(data, ...rest);
        const set = solver.options.set.bind(solver.options);
        solver.options.set = (key, value) => {
          if (typeof key === "string") counts.keys.set(`${key}=${value}`, (counts.keys.get(`${key}=${value}`) ?? 0) + 1);
          return set(key, value);
        };
        return solver;
      },
    },
  });
});

const sessionFor = (c, solver = highs) => createSession({ highs: solver, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins });

/** The part of an answer that the shortcut must leave as it is. */
const essence = (answer) => ({
  status: answer.status,
  kit: answer.kit === null ? null : kitPairs(answer.kit),
  buffs: answer.buffs,
  F: answer.F === null ? null : answer.F.toString(),
  hasteAssumed: answer.hasteAssumed,
  canonical: answer.canonical,
  tieStage: answer.tieStage,
});

/** The tie programs one call ran (`tie` all of them, `whole` the ones with the items free), and its answer. */
function counted(run) {
  const before = { ...counts };
  const answer = run();
  return { answer, tie: counts.tie - before.tie, whole: counts.whole - before.whole };
}

describe("the shortcut of the tie stage (itemsAreSettled), on the committed parity sample", () => {
  const shared = sharedOf(SAMPLE);
  const cases = SAMPLE.paths("case").map((path) => SAMPLE.read(path));
  const withBuffs = cases.filter((found) => found.solves.length > 0 && found.inputs.buffset !== null && found.inputs.buffset.set.optional.length > 0);

  it("has cases to hold it to", () => {
    expect(cases.length).toBeGreaterThan(0);
    expect(withBuffs.length).toBeGreaterThan(0);
  });

  it("every recorded solve is the same with the shortcut as with the whole tie stage, and the whole tie stage runs less often", () => {
    let solves = 0;
    let withShortcut = 0;
    let without = 0;
    for (const doc of cases) {
      const c = caseOf(shared, doc);
      const session = sessionFor(c);
      try {
        for (const recorded of doc.solves) {
          setScenario(session, "main", c.poolOf(recorded), deepFreeze(clone(recorded.options)));
          const fast = counted(() => solve(session, { scenario: "main", budgetMs: BUDGET_MS, canonical: true }));
          const full = counted(() => solve(session, { scenario: "main", budgetMs: BUDGET_MS, canonical: true, tieShortcut: false }));
          expect(essence(fast.answer), `${doc.id} ${recorded.label}`).toEqual(essence(full.answer));
          solves += 1;
          withShortcut += fast.whole;
          without += full.whole;
          expect(fast.whole, `${doc.id} ${recorded.label}: never more whole tie stages`).toBeLessThanOrEqual(full.whole);
        }
      } finally {
        closeSession(session);
      }
    }
    expect(solves).toBeGreaterThan(0);
    expect(without, "the whole tie stage runs once for every solve that has an optimal first stage").toBeGreaterThan(0);
    expect(withShortcut, "the shortcut is taken where the band wears one set of items").toBeLessThan(without);
  });

  it("a pool with a twin of every item of the answer (the same stats under another key) has a band of several sets of items: the whole tie stage runs, and the answer is its", () => {
    let tied = 0;
    let looked = 0;
    for (const doc of cases.filter((found) => found.solves.length > 0).slice(0, 12)) {
      const c = caseOf(shared, doc);
      const [recorded] = doc.solves;
      const pool = c.poolOf(recorded);
      const options = deepFreeze(clone(recorded.options));
      const session = sessionFor(c);
      try {
        setScenario(session, "main", pool, options);
        const alone = solve(session, { scenario: "main", budgetMs: BUDGET_MS, canonical: true });
        if (alone.kit === null) continue;
        const worn = new Set(alone.kit.filter((item) => item !== null).map((item) => `${item.key}@${item.tier}`));
        const twins = pool.filter((item) => worn.has(`${item.key}@${item.tier}`)).map((item) => ({ ...item, key: `${item.key}~twin` }));
        setScenario(session, "tied", [...pool, ...twins], options);
        const fast = counted(() => solve(session, { scenario: "tied", budgetMs: BUDGET_MS, canonical: true }));
        const full = counted(() => solve(session, { scenario: "tied", budgetMs: BUDGET_MS, canonical: true, tieShortcut: false }));
        looked += 1;
        expect(essence(fast.answer), doc.id).toEqual(essence(full.answer));
        if (twins.length > 0) {
          tied += 1;
          expect(fast.whole, `${doc.id}: a band of several sets of items is searched by the whole tie stage`).toBe(1);
        }
      } finally {
        closeSession(session);
      }
    }
    expect(looked).toBeGreaterThan(0);
    expect(tied).toBeGreaterThan(0);
  });

  it("a buff set with a twin of its first optional buff (the same effects under another id, excluding it) leaves the answer the whole tie stage's, buffs included", () => {
    let looked = 0;
    for (const doc of withBuffs.slice(0, 12)) {
      const c = caseOf(shared, doc);
      const [recorded] = doc.solves;
      const set = clone(c.buffset.set);
      const table = clone(c.buffset.table);
      const top = Math.max(...Object.keys(table).map(Number));
      // (one twin only: with two, the sets {a, twin of b} and {b, twin of a} have the same total rank, and which of the two equal sets the solver names is then its own
      // path's, in the whole tie stage as in the shortcut's)
      const [id] = set.optional;
      const twin = top + 1;
      table[twin] = clone(table[id]);
      set.optional.push(twin);
      // (the twin excludes what the buff excludes, and the buff: two buffs that carry spell haste may not be active together, whichever they are)
      for (const [a, b, reasons] of [...set.conflicts]) if (a === id || b === id) set.conflicts.push([a === id ? twin : a, b === id ? twin : b, reasons]);
      for (const clique of [...set.cliques]) if (clique.includes(id)) set.cliques.push(clique.map((member) => (member === id ? twin : member)));
      set.conflicts.push([id, twin, ["twin"]]);
      set.cliques.push([id, twin]);
      const session = sessionFor({ ...c, buffset: deepFreeze({ set, table }) });
      try {
        setScenario(session, "main", c.poolOf(recorded), deepFreeze(clone(recorded.options)));
        const fast = counted(() => solve(session, { scenario: "main", budgetMs: BUDGET_MS, canonical: true }));
        const full = counted(() => solve(session, { scenario: "main", budgetMs: BUDGET_MS, canonical: true, tieShortcut: false }));
        looked += 1;
        expect(essence(fast.answer), doc.id).toEqual(essence(full.answer));
      } finally {
        closeSession(session);
      }
    }
    expect(looked).toBeGreaterThan(0);
  });

  it("the ladder of haste levels (solveScenario) is the same with the option and without it, and the option is checked", () => {
    for (const doc of cases.filter((found) => found.solves.length > 0).slice(0, 12)) {
      const c = caseOf(shared, doc);
      const [recorded] = doc.solves;
      const items = c.poolOf(recorded);
      const options = deepFreeze(clone(recorded.options));
      const session = sessionFor(c);
      const run = (extra) => solveScenario(session, { name: "ladder", items, options, budgetMs: BUDGET_MS, canonical: true, ...extra });
      try {
        const fast = counted(() => run({}));
        const full = counted(() => run({ tieShortcut: false }));
        expect({ ...essence(fast.answer), level: fast.answer.level }, doc.id).toEqual({ ...essence(full.answer), level: full.answer.level });
        expect(fast.whole).toBeLessThanOrEqual(full.whole);
      } finally {
        closeSession(session);
      }
    }
    const c = caseOf(shared, cases[0]);
    const session = createSession({ highs, profile: c.profile, setup: c.setup, buffset: null, monkBins: undefined });
    try {
      expect(() => solve(session, { scenario: "x", budgetMs: 1, tieShortcut: "no" })).toThrow(/tieShortcut is true or false/);
    } finally {
      closeSession(session);
    }
  });

  it("the proof and the tie stage have each the whole allowance of the call, whatever the first stage and the proof took of the clock", () => {
    // each run takes 300 ms of a clock that stands still otherwise (the limits are read as each run is given its own)
    let now = 0;
    const spied = spyOn(highs, {
      clock: () => now,
      before: () => {
        now += 300;
      },
    });
    const doc = withBuffs[0];
    const c = caseOf(shared, doc);
    const [recorded] = doc.solves;
    const session = createSession({ highs: spied.highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins, now: () => now });
    try {
      setScenario(session, "main", c.poolOf(recorded), deepFreeze(clone(recorded.options)));
      const answer = solve(session, { scenario: "main", budgetMs: 1000, canonical: true });
      expect(answer.tieStage).toBe("applied");
      // the first stage, the proof (a stage of its own) and the tie stage (with the items fixed, a program of its own) are each given the whole 1000 ms
      expect(spied.log.limits.map((limit) => limit.limitMs)).toEqual([1000, 1000, 1000]);
    } finally {
      closeSession(session);
    }
  });
  it("the tie stage of a settled band leaves the places of the items free: it has a row for each worn item, and no item column is fixed", () => {
    let looked = 0;
    for (const doc of cases.filter((found) => found.solves.length > 0)) {
      const c = caseOf(shared, doc);
      const [recorded] = doc.solves;
      const session = sessionFor(c);
      try {
        setScenario(session, "main", c.poolOf(recorded), deepFreeze(clone(recorded.options)));
        const model = session.scenarios.get("main").model;
        counts.last = null;
        const answer = solve(session, { scenario: "main", budgetMs: BUDGET_MS, canonical: true });
        const data = counts.last;
        if (data === null || data.rowLower[data.numRows - 1] !== data.rowUpper[data.numRows - 1]) continue; // (no cut-down tie stage here)
        looked += 1;
        model.item_cols.forEach(([column]) => {
          expect(data.colLower[column], `${doc.id}: an item column keeps its bounds`).toBe(model.col_lb[column]);
          expect(data.colUpper[column]).toBe(model.col_ub[column]);
        });
        const worn = new Set(answer.kit.filter((item) => item !== null).map((item) => `${item.key}@${item.tier}`));
        expect(data.numRows - model.row_lb.length - 1, `${doc.id}: one row for each worn item`).toBe(worn.size);
      } finally {
        closeSession(session);
      }
    }
    expect(looked).toBeGreaterThan(0);
  });

  it("every optional buff of a shield setup, twinned in turn (a buff that can tip the armor class softcap, where the shield stands in the hand or outside it), leaves the answer the whole tie stage's", () => {
    let looked = 0;
    let shields = 0;
    for (const doc of withBuffs.filter((found) => found.inputs.setup === "1h-shield" || found.inputs.setup === "dw")) {
      const c = caseOf(shared, doc);
      const [recorded] = doc.solves;
      shields += 1;
      for (const id of c.buffset.set.optional) {
        const set = clone(c.buffset.set);
        const table = clone(c.buffset.table);
        const twin = Math.max(...Object.keys(table).map(Number)) + 1;
        table[twin] = clone(table[id]);
        set.optional.push(twin);
        for (const [a, b, reasons] of [...set.conflicts]) if (a === id || b === id) set.conflicts.push([a === id ? twin : a, b === id ? twin : b, reasons]);
        for (const clique of [...set.cliques]) if (clique.includes(id)) set.cliques.push(clique.map((member) => (member === id ? twin : member)));
        set.conflicts.push([id, twin, ["twin"]]);
        set.cliques.push([id, twin]);
        const session = sessionFor({ ...c, buffset: deepFreeze({ set, table }) });
        try {
          setScenario(session, "main", c.poolOf(recorded), deepFreeze(clone(recorded.options)));
          const fast = solve(session, { scenario: "main", budgetMs: BUDGET_MS, canonical: true });
          const full = solve(session, { scenario: "main", budgetMs: BUDGET_MS, canonical: true, tieShortcut: false });
          looked += 1;
          expect(essence(fast), `${doc.id} twin of ${id}`).toEqual(essence(full));
        } finally {
          closeSession(session);
        }
      }
    }
    expect(shields).toBeGreaterThan(0);
    expect(looked).toBeGreaterThan(0);
  });

  it("the proof tells its progress as a stage of its own, the caller's solver options reach it, and tieShortcut is checked by solveScenario too", () => {
    const types = highs.constants.callbackType;
    const fired = (run, callbacks) => {
      if (callbacks === undefined) return;
      callbacks[types.mipLogging]({ data: { mip_dual_bound: 99999, mip_gap: 0.5, mip_node_count: 7 } });
    };
    const doc = withBuffs[0];
    const c = caseOf(shared, doc);
    const [recorded] = doc.solves;
    const spied = spyOn(highs, { before: fired });
    const session = createSession({ highs: spied.highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins });
    try {
      setScenario(session, "main", c.poolOf(recorded), deepFreeze(clone(recorded.options)));
      const events = [];
      const first = solve(session, { scenario: "main", budgetMs: BUDGET_MS });
      solve(session, { scenario: "main", budgetMs: BUDGET_MS, canonical: true, onProgress: (event) => events.push(event) });
      const proof = events.filter((event) => event.stage === "proof");
      expect(proof.length, "the proof has events").toBeGreaterThan(0);
      for (const event of proof) {
        expect(event.objective, "the first stage's objective, as the tie stage's events carry").toBe(first.modelF);
        expect(event).not.toHaveProperty("bound");
        expect(event).not.toHaveProperty("gap");
      }
      // the caller's solver options are the proof's too: set on the first stage, the proof and the tie stage, three programs (two if the proof were left out)
      counts.keys.clear();
      solve(session, { scenario: "main", budgetMs: BUDGET_MS, canonical: true, highsOptions: { mip_detect_symmetry: false } });
      expect(counts.keys.get("mip_detect_symmetry=false")).toBe(3);
    } finally {
      closeSession(session);
    }
    const plain = createSession({ highs, profile: c.profile, setup: c.setup, buffset: null, monkBins: undefined });
    try {
      expect(() => solveScenario(plain, { name: "x", items: [], budgetMs: 1, tieShortcut: 1 })).toThrow(/tieShortcut is true or false/);
    } finally {
      closeSession(plain);
    }
  });
});
