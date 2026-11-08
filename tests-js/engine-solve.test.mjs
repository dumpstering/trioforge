import { readFileSync } from "node:fs";
import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { EvaluateError, SLOT_INSTANCES, evaluate } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { buildMilp } from "../pipeline/trioforge/site/static/engine/model.js";
import { LABEL_NO_INCUMBENT, LABEL_TIME_LIMIT } from "../pipeline/trioforge/site/static/engine/protocol.js";
import {
  EXACTNESS_TOLERANCE,
  ExactnessError,
  PlacementError,
  SolveError,
  SolverFault,
  TIE_TOLERANCE,
  canonicalKit,
  checkExactness,
  checkRearranged,
  closeSession,
  createSession,
  placeCanonically,
  setScenario,
  solve,
  tieRanks,
} from "../pipeline/trioforge/site/static/engine/solve.js";
import { SOLVER_OPTIONS, solveModelWith } from "../pipeline/trioforge/site/static/engine/worker.js";
import { FAMILIES, caseOf, clone, deepFreeze, exact, identOf, kitPairs, sharedOf, shuffled, solverIs } from "./engine-cases.mjs";
import { spyOn } from "./engine-spy.mjs";
import { buffOf, buffsetOf, gear, oneHand, profileWith, q, twoHand } from "./engine-hand.mjs";
import { SAMPLE, describeFull } from "./engine-fixtures.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

// The sessions of the browser engine (static/engine/solve.js) held to the solver wrapper of Python (pipeline/trioforge/solver/solve.py):
//
//   * Canonical solves against Python's, and the brute-force instances: tests-js/engine-solve-parity.test.mjs (the long part, a file of its own so that the
//     suite's files run side by side).
//   * The browser's answer. Without the tie stage the answer has the exact value of the optimum (a kit among equals, placed by the canonical rule).
//   * The placement. The worn items stand by a rule that looks at the items alone (the hands too, among the arrangements worth exactly as much).
//   * The time limit. A stop at a limit with an incumbent is `time_limit` with the evaluator's exact value of the incumbent (never the model's) and its
//     label; with none, the label says "not found in time". A node limit is the same stop.
//   * In place. Changing the counts of a scenario changes bounds and rows of the solver's model in place: it ends equal to a model built afresh.

// a solve of the hard programs takes a second or two, and the suite runs its files side by side: the time of a test is not the default five seconds
vi.setConfig({ testTimeout: 120_000 });
const REL = 1e-9;
const BUDGET_MS = 600_000;
const relative = (got, want) => Math.abs(got - want) / Math.max(1, Math.abs(want));

/** HiGHS as the worker runs it (in Node it reads its own file), started once for this file. */
let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const sessionFor = (c, extra = {}) => createSession({ highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins, ...extra });

/** A program whose proof needs a tree of more than this many nodes is one that a node limit of this many stops before the proof. */
const NODES_TO_STOP_AT = 2;
let aTreeCache = null;
/**
 * A program that needs a tree, so that a node limit stops its proof: the whole pool, not pruned, of the first pruning-check case of the sample whose solve
 * takes more than two nodes. (The pruned programs of the sample are mostly solved at the root, which is why the unpruned ones are looked at; which case it is
 * moves with the catalog the sample was made from.) Found when first asked for, in a test, once the solver is loaded.
 */
function aTree() {
  if (aTreeCache !== null) return aTreeCache;
  const shared = sharedOf(SAMPLE);
  for (const family of ["pmb36", "matrix"]) {
    for (const path of SAMPLE.paths("case", `${family}/`)) {
      const doc = SAMPLE.read(path);
      const [recorded] = doc.solves;
      if (recorded.prune === null) continue;
      const c = caseOf(shared, doc);
      const wide = { ...recorded, pool: recorded.prune.input };
      const session = sessionFor(c);
      try {
        setScenario(session, "probe", c.poolOf(wide), deepFreeze(clone(recorded.options)));
        if (solve(session, { scenario: "probe", budgetMs: BUDGET_MS }).nodes > NODES_TO_STOP_AT) {
          aTreeCache = { c, recorded: wide };
          return aTreeCache;
        }
      } finally {
        closeSession(session);
      }
    }
  }
  throw new Error("the sample holds no program that needs a tree of more than two nodes: a node limit has nothing to stop");
}

// ---- the browser's answer ----------------------------------------------------------------------------------------------------------

function placementOk(kit, model) {
  // every worn item stands in a group the model has a column for it in, within the places of the group, a Lore key once
  const columns = new Set(model.item_cols.map(([, group, key, tier]) => `${group}|${key}@${tier}`));
  const lore = new Map();
  kit.forEach((item, at) => {
    if (item === null) return;
    expect(columns.has(`${SLOT_INSTANCES[at]}|${identOf(item)}`), `${identOf(item)} in ${SLOT_INSTANCES[at]}`).toBe(true);
    if (item.lore) lore.set(item.key, (lore.get(item.key) ?? 0) + 1);
  });
  for (const count of lore.values()) expect(count).toBe(1);
}

function browserTests(set, every) {
  const shared = sharedOf(set);
  for (const family of ["matrix", "upgrade", "pmb36"]) {
    set.paths("case", `${family}/`).forEach((path, number) => {
      if (number % every !== 0) return;
      const doc = set.read(path);
      it(`${doc.id} (${doc.label}): the answer without the tie stage has the exact value of the optimum, and a kit that is placed`, () => {
        const c = caseOf(shared, doc);
        const session = sessionFor(c);
        try {
          for (const recorded of doc.solves) {
            setScenario(session, "main", c.poolOf(recorded), deepFreeze(clone(recorded.options)));
            const got = solve(session, { scenario: "main", budgetMs: BUDGET_MS });
            expect(got.status).toBe("optimal");
            expect(got.canonical).toBe(false);
            expect(got.tieStage).toBeNull();
            expect(got.F.toString(), `${doc.id} ${recorded.label}`).toBe(exact(recorded.result.F).toString());
            expect(got.kit).toHaveLength(SLOT_INSTANCES.length);
            placementOk(got.kit, session.scenarios.get("main").model);
          }
        } finally {
          closeSession(session);
        }
      }, 300_000);
    });
  }
}

describe("the browser's answer, the committed sample", () => browserTests(SAMPLE, 1));
describeFull("the browser's answer, every fifth case of the full set", (full) => browserTests(full, 5));

// ---- the order of the pool does not matter -------------------------------------------------------------------------------------------

function orderTests(set, every) {
  const shared = sharedOf(set);
  for (const family of ["matrix", "upgrade", "pmb36"]) {
    set.paths("case", `${family}/`).forEach((path, number) => {
      if (number % every !== 0) return;
      const doc = set.read(path);
      it(`${doc.id} (${doc.label}): the same inputs in a shuffled pool order give the same canonical kit`, () => {
        const c = caseOf(shared, doc);
        const session = sessionFor(c);
        try {
          const recorded = doc.solves[doc.solves.length - 1];
          const options = recorded.options;
          setScenario(session, "given", c.poolOf(recorded), deepFreeze(clone(options)));
          const given = solve(session, { scenario: "given", budgetMs: BUDGET_MS, canonical: true });
          const reversed = {
            ...clone(options),
            owned_caps: Object.fromEntries(Object.entries(options.owned_caps ?? {}).reverse()),
            new_keys: [...(options.new_keys ?? [])].reverse(),
            upgrades: Object.fromEntries(Object.entries(options.upgrades ?? {}).reverse()),
          };
          setScenario(session, "shuffled", shuffled(c.poolOf(recorded), 3), deepFreeze(reversed));
          const got = solve(session, { scenario: "shuffled", budgetMs: BUDGET_MS, canonical: true });
          expect(kitPairs(got.kit), `${doc.id} ${recorded.label}`).toEqual(kitPairs(given.kit));
          expect(got.buffs).toEqual(given.buffs);
          expect(got.F.toString()).toBe(exact(recorded.result.F).toString());
          expect(JSON.stringify(session.scenarios.get("shuffled").model)).toBe(JSON.stringify(session.scenarios.get("given").model));
        } finally {
          closeSession(session);
        }
      }, 300_000);
    });
  }
}

describe("determinism, every second case of the committed sample", () => orderTests(SAMPLE, 2));
describeFull("determinism, every eighth case of the full set", (full) => orderTests(full, 8));

// ---- the time limit -------------------------------------------------------------------------------------------------------------------

describe("the time limit", () => {
  const shared = sharedOf(SAMPLE);
  const upgrade = caseOf(shared, SAMPLE.read(SAMPLE.paths("case", "upgrade/")[0]));
  const [equip] = SAMPLE.read(SAMPLE.paths("case", "upgrade/")[0]).solves;
  const pmb = caseOf(shared, SAMPLE.read("pmb36/pmb36-001.json"));
  const [hard] = SAMPLE.read("pmb36/pmb36-001.json").solves;

  /** The options of the equip-now solve with the count of one worn item reduced to one less than it is worn, so that the best kit gets worse. */
  const tighter = (name, copies) => deepFreeze({ ...clone(equip.options), owned_caps: { ...equip.options.owned_caps, [name]: copies - 1 } });

  it("a stop at the limit with an incumbent that is not the optimum is time_limit with the exact value of the incumbent, below the optimum", () => {
    const session = sessionFor(upgrade);
    try {
      const pool = upgrade.poolOf(equip);
      setScenario(session, "s", pool, deepFreeze(clone(equip.options)));
      const best = solve(session, { scenario: "s", budgetMs: BUDGET_MS });
      expect(best.status).toBe("optimal");
      // a smaller count of a worn item: the best kit of that program is worse, and it becomes the start of the next solve
      const worn = new Map();
      for (const item of best.kit) if (item !== null) worn.set(identOf(item), (worn.get(identOf(item)) ?? 0) + 1);
      let worse = null;
      for (const [name, copies] of [...worn].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))) {
        const info = setScenario(session, "s", pool, tighter(name, copies));
        expect(info.reused, "only bounds and rows changed: the solver's model is kept").toBe(true);
        const answer = solve(session, { scenario: "s", budgetMs: BUDGET_MS });
        expect(answer.status).toBe("optimal");
        if (answer.F.compare(best.F) < 0) {
          worse = answer;
          break;
        }
      }
      expect(worse, "some worn item is needed for the best kit").not.toBeNull();
      // back to the full counts, and no time at all: the incumbent is the kit of the last solve
      expect(setScenario(session, "s", pool, deepFreeze(clone(equip.options))).reused).toBe(true);
      const limited = solve(session, { scenario: "s", budgetMs: 0 });
      expect(limited.status).toBe("time_limit");
      expect(limited.proven).toBe(false);
      expect(limited.label).toBe(LABEL_TIME_LIMIT);
      expect(limited.F.toString()).toBe(worse.F.toString());
      expect(limited.F.compare(best.F)).toBe(-1);
      expect(kitPairs(limited.kit)).toEqual(kitPairs(worse.kit));
      // the value is the evaluator's exact value of the incumbent kit, not the model's
      const options = { setup: upgrade.setup, hasteAssumed: limited.hasteAssumed, monkBins: upgrade.bins, buffset: upgrade.buffset ?? undefined };
      expect(evaluate(upgrade.profile, limited.kit, upgrade.buffset === null ? null : limited.buffs, options).F.toString()).toBe(limited.F.toString());
      expect(limited.modelF).toBeLessThanOrEqual(limited.F.toNumber() + EXACTNESS_TOLERANCE * Math.max(1, Math.abs(limited.F.toNumber())));
      // and with time the same solve ends where the optimum is
      const again = solve(session, { scenario: "s", budgetMs: BUDGET_MS });
      expect(again.status).toBe("optimal");
      expect(again.F.toString()).toBe(best.F.toString());
    } finally {
      closeSession(session);
    }
  });

  it("a node limit is the same stop: time_limit, the incumbent's exact value at or below the optimum, and the label", () => {
    const { c: wide, recorded: tree } = aTree();
    const session = sessionFor(wide);
    try {
      setScenario(session, "s", wide.poolOf(tree), deepFreeze(clone(tree.options)));
      const optimal = solve(session, { scenario: "s", budgetMs: BUDGET_MS });
      expect(optimal.status).toBe("optimal");
      expect(optimal.nodes).toBeGreaterThan(NODES_TO_STOP_AT); // the program needs a tree, so that a limit of two nodes stops it
      setScenario(session, "fresh", wide.poolOf(tree), deepFreeze(clone(tree.options)));
      const stopped = solve(session, { scenario: "fresh", budgetMs: BUDGET_MS, highsOptions: { mip_max_nodes: NODES_TO_STOP_AT } });
      expect(stopped.status).toBe("time_limit");
      expect(stopped.label).toBe(LABEL_TIME_LIMIT);
      expect(stopped.proven).toBe(false);
      expect(stopped.F).not.toBeNull();
      expect(stopped.F.compare(optimal.F)).toBeLessThanOrEqual(0);
      expect(stopped.nodes).toBeLessThanOrEqual(NODES_TO_STOP_AT);
      // the option was for that call only: the next solve of the scenario runs to the end
      const after = solve(session, { scenario: "fresh", budgetMs: BUDGET_MS });
      expect(after.status).toBe("optimal");
      expect(after.F.toString()).toBe(optimal.F.toString());
    } finally {
      closeSession(session);
    }
  });

  it("a stop with no incumbent says that nothing was found in time, and has no value or kit", () => {
    const session = sessionFor(pmb);
    try {
      setScenario(session, "s", pmb.poolOf(hard), deepFreeze(clone(hard.options)));
      const none = solve(session, { scenario: "s", budgetMs: 0 });
      expect(none.status).toBe("time_limit");
      expect(none.label).toBe(LABEL_NO_INCUMBENT);
      expect(none.proven).toBe(false);
      expect(none.F).toBeNull();
      expect(none.kit).toBeNull();
      expect(none.breakdown).toBeNull();
      expect(none.buffs).toEqual([]);
      expect(LABEL_NO_INCUMBENT).toBe("not found in time");
    } finally {
      closeSession(session);
    }
  });

  it("a stop at the limit stays inside the time it was given, and the solver's own clock does not carry over to the next solve", () => {
    const session = sessionFor(pmb);
    try {
      setScenario(session, "s", pmb.poolOf(hard), deepFreeze(clone(hard.options)));
      const watch = stopwatch();
      const quick = solve(session, { scenario: "s", budgetMs: 30 });
      expectWithin(watch.stop(), 2000, "a solve with a budget of 30 ms stops");
      expect(quick.status).toBe("time_limit");
      expect(quick.limitMs).toBeLessThanOrEqual(30);
      // a second solve after the first gets its own time, however long the first ran
      const full = solve(session, { scenario: "s", budgetMs: BUDGET_MS });
      expect(full.status).toBe("optimal");
    } finally {
      closeSession(session);
    }
  });

  it("reports progress while it solves, in the scale of the model, and only to a function", () => {
    const session = sessionFor(pmb);
    try {
      setScenario(session, "s", pmb.poolOf(hard), deepFreeze(clone(hard.options)));
      const seen = [];
      const got = solve(session, { scenario: "s", budgetMs: BUDGET_MS, onProgress: (fields) => seen.push(fields) });
      expect(got.status).toBe("optimal");
      expect(seen.length).toBeGreaterThan(0);
      for (const fields of seen) {
        expect(fields.phase).toBe("solving");
        expect(fields.elapsedMs).toBeGreaterThanOrEqual(0);
        for (const name of ["objective", "bound", "gap", "nodes"]) if (name in fields) expect(Number.isFinite(fields[name]), name).toBe(true);
      }
      // a kit that HiGHS reports is never worth more than the optimum the model ends with
      for (const fields of seen) if ("objective" in fields) expect(fields.objective).toBeLessThanOrEqual(got.modelF + 1e-6 * Math.max(1, Math.abs(got.modelF)));
      expect(() => solve(session, { scenario: "s", budgetMs: 100, onProgress: 5 })).toThrow(/onProgress/);
    } finally {
      closeSession(session);
    }
  });

  it("answers a program with no column without a solver, and says when the program is infeasible", () => {
    const session = createSession({ highs, profile: profileWith({ weights: { HP: 1 } }), setup: "stick" });
    try {
      setScenario(session, "empty", [], {});
      const empty = solve(session, { scenario: "empty", budgetMs: 1000 });
      expect(empty.status).toBe("optimal");
      expect(empty.proven).toBe(true);
      expect(empty.kit.every((item) => item === null)).toBe(true);
      expect(session.scenarios.get("empty").solver).toBeNull();
      expect(empty.canonical).toBe(false);
      const tied = solve(session, { scenario: "empty", budgetMs: 1000, canonical: true }); // one kit: nothing for the tie stage to separate
      expect([tied.canonical, tied.tieStage]).toEqual([true, "applied"]);
      expect(tied.F.toString()).toBe(empty.F.toString());
      // nothing may be acquired: the empty kit is the answer
      const ring = gear("ring", ["FINGER"], { stats: { HP: 5 } });
      setScenario(session, "none", [ring], { owned_caps: { "ring@0": 0 }, new_keys: ["ring@0"], max_new: 0 });
      const none = solve(session, { scenario: "none", budgetMs: 1000 });
      expect(none.status).toBe("optimal");
      expect(none.kit.every((item) => item === null)).toBe(true);
      // the builder never makes a program with no kit, so make one: a row that no value of the first column can meet
      setScenario(session, "bad", [ring], { any_rule: "explicit" });
      session.scenarios.get("bad").solver.addRow(5, 5, { indices: [0], values: [1] });
      const bad = solve(session, { scenario: "bad", budgetMs: 1000 });
      expect(bad.status).toBe("infeasible");
      expect(bad.label).toBeNull();
      expect(bad.proven).toBe(true);
      expect(bad.F).toBeNull();
      expect(bad.kit).toBeNull();
    } finally {
      closeSession(session);
    }
  });
});

// ---- in place ------------------------------------------------------------------------------------------------------------------------

const expectSolverIs = (session, name) => solverIs(expect, highs, session, name);

describe("a scenario's model, in place", () => {
  const shared = sharedOf(SAMPLE);
  const doc = SAMPLE.read(SAMPLE.paths("case", "upgrade/")[0]);
  const c = caseOf(shared, doc);
  const [equip, step1, step2] = doc.solves;

  it("is created from the document, and the solver holds the options of the Python solver", () => {
    const session = sessionFor(c);
    try {
      const info = setScenario(session, "s", c.poolOf(equip), deepFreeze(clone(equip.options)));
      expect(info.reused).toBe(false);
      expectSolverIs(session, "s");
      const scenario = session.scenarios.get("s");
      for (const [name, value] of Object.entries(SOLVER_OPTIONS)) expect(scenario.solver.options.get(name), name).toBe(value);
      expect(JSON.stringify(scenario.model)).toBe(JSON.stringify(buildMilp(c.profile, c.poolOf(equip), c.setup, c.buffset, c.optionsOf(equip))));
      // and it still does after solves (clearing the solver before a run does not reset them), canonical ones included
      solve(session, { scenario: "s", budgetMs: BUDGET_MS });
      solve(session, { scenario: "s", budgetMs: BUDGET_MS, canonical: true });
      for (const [name, value] of Object.entries(SOLVER_OPTIONS)) expect(scenario.solver.options.get(name), `${name} after the solves`).toBe(value);
      expectSolverIs(session, "s");
    } finally {
      closeSession(session);
    }
  });

  it("changes the bounds of columns and rows in place when only the counts change, and ends equal to a model built afresh", () => {
    const session = sessionFor(c);
    try {
      const pool = c.poolOf(equip);
      setScenario(session, "s", pool, deepFreeze(clone(equip.options)));
      const before = session.scenarios.get("s").solver;
      const caps = { ...equip.options.owned_caps };
      // every count that can bind goes up or down by one; the rows that bind change their bounds, a count that stops binding loses its row
      const names = Object.keys(caps);
      const changed = Object.fromEntries(names.map((name, at) => [name, at % 3 === 0 ? Math.max(1, caps[name] + 1) : at % 3 === 1 ? Math.max(1, caps[name] - 1) : caps[name]]));
      const info = setScenario(session, "s", pool, deepFreeze({ ...clone(equip.options), owned_caps: changed }));
      expect(info.reused).toBe(true);
      expect(session.scenarios.get("s").solver).toBe(before);
      expectSolverIs(session, "s");
      const fresh = buildMilp(c.profile, pool, c.setup, c.buffset, { ...clone(equip.options), owned_caps: changed, ...(c.bins === undefined ? {} : { monk_bins: c.bins }) });
      expect(JSON.stringify(session.scenarios.get("s").model)).toBe(JSON.stringify(fresh));
      // and the answer is the answer of the model built afresh
      const got = solve(session, { scenario: "s", budgetMs: BUDGET_MS });
      const want = solveModelWith(highs, fresh, { budgetMs: BUDGET_MS, startedAt: performance.now(), onProgress() {} });
      expect(relative(got.modelF, want.objective)).toBeLessThanOrEqual(REL);
    } finally {
      closeSession(session);
    }
  });

  it("adds and removes rows in place when the counts make a row appear or disappear, and keeps the solver's model equal to the document", () => {
    const session = sessionFor(c);
    try {
      const pool = c.poolOf(equip);
      setScenario(session, "s", pool, deepFreeze(clone(equip.options)));
      const solver = session.scenarios.get("s").solver;
      const rowsBefore = session.scenarios.get("s").model.row_names.filter((name) => name.startsWith("own."));
      // a count of 9 can never bind: its row is gone; a count of 1 on every item makes most of them bind
      const loose = Object.fromEntries(Object.keys(equip.options.owned_caps).map((name) => [name, 9]));
      const tight = Object.fromEntries(Object.keys(equip.options.owned_caps).map((name) => [name, 1]));
      for (const caps of [loose, tight, equip.options.owned_caps, tight]) {
        const info = setScenario(session, "s", pool, deepFreeze({ ...clone(equip.options), owned_caps: caps }));
        expect(info.reused).toBe(true);
        expect(session.scenarios.get("s").solver).toBe(solver);
        expectSolverIs(session, "s");
      }
      expect(session.scenarios.get("s").model.row_names.filter((name) => name.startsWith("own.")).length).toBeGreaterThan(0);
      expect(rowsBefore.length).toBeGreaterThan(0);
    } finally {
      closeSession(session);
    }
  });

  it("makes a new model when the columns change, and warm starts from the last kit all the same", () => {
    const session = sessionFor(c);
    try {
      setScenario(session, "s", c.poolOf(step1), deepFreeze(clone(step1.options)));
      const first = solve(session, { scenario: "s", budgetMs: BUDGET_MS });
      const solver = session.scenarios.get("s").solver;
      const info = setScenario(session, "s", c.poolOf(step2), deepFreeze(clone(step2.options)));
      if (JSON.stringify(c.poolOf(step1).map(identOf)) !== JSON.stringify(c.poolOf(step2).map(identOf))) {
        expect(info.reused).toBe(false);
        expect(session.scenarios.get("s").solver).not.toBe(solver);
      }
      expectSolverIs(session, "s");
      const second = solve(session, { scenario: "s", budgetMs: BUDGET_MS, canonical: true });
      expect(second.F.toString()).toBe(exact(step2.result.F).toString());
      expect(first.status).toBe("optimal");
    } finally {
      closeSession(session);
    }
  });

  it("keeps the scenarios of a session apart: a solver for each name", () => {
    const session = sessionFor(c);
    try {
      setScenario(session, "a", c.poolOf(equip), deepFreeze(clone(equip.options)));
      setScenario(session, "b", c.poolOf(step1), deepFreeze(clone(step1.options)));
      expect(session.scenarios.get("a").solver).not.toBe(session.scenarios.get("b").solver);
      const a = solve(session, { scenario: "a", budgetMs: BUDGET_MS, canonical: true });
      const b = solve(session, { scenario: "b", budgetMs: BUDGET_MS, canonical: true });
      expect(a.F.toString()).toBe(exact(equip.result.F).toString());
      expect(b.F.toString()).toBe(exact(step1.result.F).toString());
      // the last scenario set is the one a solve takes when it names none
      setScenario(session, "a", c.poolOf(equip), deepFreeze(clone(equip.options)));
      expect(solve(session, { budgetMs: BUDGET_MS }).F.toString()).toBe(exact(equip.result.F).toString());
    } finally {
      closeSession(session);
    }
  });
});

// ---- placement, ranks, the tie stage ---------------------------------------------------------------------------------------------------

describe("the canonical placement", () => {
  const profile = profileWith({ weights: { HP: 1 } });
  const setup = "stick";
  const options = { any_rule: "all", haste_assumed: 0 };
  const cloak = gear("cloak", ["BACK"], { stats: { HP: 50 } });
  const ring = gear("ring", ["FINGER"], { stats: { HP: 40 } });
  const band = gear("band", ["FINGER"], { stats: { HP: 30 } });
  const model = buildMilp(profile, [cloak, ring, band], setup, null, options);
  /** The exact value of a kit, which the placement compares arrangements by. */
  const valuing = (given, how) => (kit) => evaluate(given, kit, null, { setup: how, hasteAssumed: 0 }).F;
  const worth = valuing(profile, setup);

  it("takes the items that are not in a hand by (key, tier), each into the earliest group that fits and leaves every item a place", () => {
    // the cloak fits BACK and ANY (any rule "all"), the rings FINGER (two places) and ANY (two places): the earliest group of the slot order wins
    const keys = (placed) => Object.fromEntries([...placed].map(([group, items]) => [group, items.map((item) => item.key)]));
    const placed = placeCanonically(model, new Map([["ANY", [ring, cloak]], ["FINGER", [band]]]), worth);
    expect(keys(placed)).toEqual({ BACK: ["cloak"], FINGER: ["band", "ring"] });
    // the same items placed another way give the same placement
    const other = placeCanonically(model, new Map([["FINGER", [ring, band]], ["BACK", [cloak]]]), worth);
    expect(keys(other)).toEqual(keys(placed));
  });

  it("leaves the hands where the solver put them when every other arrangement of the items is worth a different amount", () => {
    // a weapon index is worth something in a hand and nothing in an Any place, and the sword is worth more in the main hand than the dagger is
    const damaging = profileWith({ weights: { HP: 1, DMG: 50 }, dw_factor: 0.8 });
    const sword = gear("sword", ["PRIMARY"], { weapon: oneHand(10, 20) });
    const dagger = gear("dagger", ["PRIMARY", "SECONDARY"], { weapon: oneHand(5, 20) });
    const hands = buildMilp(damaging, [sword, dagger], "dw", null, options);
    const placed = placeCanonically(hands, new Map([["SECONDARY", [dagger]], ["PRIMARY", [sword]]]), valuing(damaging, "dw"));
    expect(Object.fromEntries([...placed].map(([group, items]) => [group, items.map((item) => item.key)]))).toEqual({ SECONDARY: ["dagger"], PRIMARY: ["sword"] });
  });

  it("refuses a placement that is not one of this model", () => {
    expect(() => placeCanonically(model, new Map([["FINGER", [cloak]]]), worth)).not.toThrow(); // the cloak has a column in ANY and BACK: it is moved there
    const stray = gear("stray", ["HEAD"], { stats: { HP: 1 } });
    expect(() => placeCanonically(model, new Map([["HEAD", [stray]]]), worth)).toThrow(SolveError);
    expect(() => placeCanonically(model, new Map([["FINGER", [cloak]]]))).toThrow(SolveError); // the placement values arrangements: it needs the function that does
  });

  it("writes a kit of 22 places: each group in key order, then its empty places", () => {
    const kit = canonicalKit(new Map([["FINGER", [ring, band]], ["BACK", [cloak]]]));
    expect(kit).toHaveLength(22);
    const sorted = canonicalKit(new Map([["FINGER", [band, ring]], ["BACK", [cloak]]]));
    expect(kit.map((item) => item && item.key)).toEqual(sorted.map((item) => item && item.key));
    expect(kit.filter((item) => item !== null).map((item) => item.key)).toEqual(["cloak", "band", "ring"]);
    expect(() => canonicalKit(new Map([["BACK", [cloak, ring]]]))).toThrow(SolveError); // one place in BACK
  });
});

describe("the hands", () => {
  // Where the worn items stand changes the value of a kit only through the two hands: the weapon index of what is in them, and the shield bonus of an
  // off-hand shield. Among the arrangements of the same items that the builder allows and that are worth exactly what the solver's is, the hands are filled
  // by one rule that looks at the items alone: the main hand before it is left empty, by the smaller (key, tier); then the off hand the same way
  // (`place_canonically` in solve.py, tests/test_placement.py).
  const stick = profileWith({ weights: { HP: 1 } });
  const damaging = profileWith({ weights: { HP: 1, DMG: 50 }, dw_factor: 0.8 }); // the production factor: with 1 the two hands of a pair are worth the same
  const valuing = (given, how) => (kit) => evaluate(given, kit, null, { setup: how, hasteAssumed: 0 }).F;
  const options = { any_rule: "all", haste_assumed: 0 };
  const explicit = { any_rule: "explicit", haste_assumed: 0 };
  const eitherHand = ["PRIMARY", "SECONDARY"];
  /** One-handers that are worth the same wherever they stand when no damage is scored. */
  const oneHanders = (keys, more = {}) => keys.map((key) => gear(key, eitherHand, { stats: { HP: 10 }, weapon: oneHand(10, 30), ...more }));
  const keysOf = (placed) => Object.fromEntries([...placed].filter(([, items]) => items.length > 0).map(([group, items]) => [group, items.map((item) => item.key)]));
  const place = (given, how, items, groups, extra = options) => placeCanonically(buildMilp(given, items, how, null, extra), new Map(Object.entries(groups)), valuing(given, how));

  it("fills the main hand first, by the smaller key, whatever the solver chose", () => {
    const three = oneHanders(["axe", "mace", "sword"]);
    const want = { PRIMARY: ["axe"], SECONDARY: ["mace"], ANY: ["sword"] };
    let seen = 0;
    const places = ["PRIMARY", "SECONDARY", "ANY", "ANY"];
    for (let i = 0; i < places.length; i += 1) {
      for (let j = 0; j < places.length; j += 1) {
        for (let k = 0; k < places.length; k += 1) {
          if (new Set([i, j, k]).size < 3) continue; // the three items stand in three different places of the four
          const groups = {};
          [i, j, k].forEach((at, number) => (groups[places[at]] ??= []).push(three[number]));
          expect(keysOf(place(stick, "stick", three, groups)), JSON.stringify(Object.fromEntries(Object.entries(groups).map(([g, v]) => [g, v.map((x) => x.key)])))).toEqual(want);
          seen += 1;
        }
      }
    }
    expect(seen).toBe(24);
  });

  it("fills a hand when it can be filled, though the solver left it empty", () => {
    const [axe, mace] = oneHanders(["axe", "mace"]);
    expect(keysOf(place(stick, "stick", [axe, mace], { ANY: [axe, mace] }))).toEqual({ PRIMARY: ["axe"], SECONDARY: ["mace"] });
    expect(keysOf(place(stick, "stick", [axe, mace], { ANY: [mace] }))).toEqual({ PRIMARY: ["mace"] });
  });

  it("tells equal keys apart by tier", () => {
    const [low] = oneHanders(["axe"], { tier: 2 });
    const [high] = oneHanders(["axe"], { tier: 4 });
    const got = place(stick, "stick", [low, high], { PRIMARY: [high], SECONDARY: [low] }, explicit);
    expect(got.get("PRIMARY").map((item) => item.tier)).toEqual([2]);
    expect(got.get("SECONDARY").map((item) => item.tier)).toEqual([4]);
  });

  it("never takes an arrangement that is worth more or less, whatever the keys say", () => {
    const big = gear("zz-big", eitherHand, { stats: { HP: 10 }, weapon: oneHand(20, 30) });
    const small = gear("aa-small", eitherHand, { stats: { HP: 10 }, weapon: oneHand(8, 20) });
    expect(keysOf(place(damaging, "dw", [big, small], { PRIMARY: [big], SECONDARY: [small] }))).toEqual({ PRIMARY: ["zz-big"], SECONDARY: ["aa-small"] });
    expect(keysOf(place(damaging, "dw", [big, small], { PRIMARY: [small], SECONDARY: [big] }))).toEqual({ PRIMARY: ["aa-small"], SECONDARY: ["zz-big"] });
    // a weapon in an Any place scores nothing, and the kit that holds it in a hand is worth more: that is another kit
    expect(keysOf(place(damaging, "dw", [big, small], { PRIMARY: [big], ANY: [small] }))).toEqual({ PRIMARY: ["zz-big"], ANY: ["aa-small"] });
  });

  it("tells two weapons of the same index apart by key only among themselves", () => {
    const alike = oneHanders(["b-alike", "c-alike"]);
    const other = gear("a-other", eitherHand, { stats: { HP: 10 }, weapon: oneHand(4, 30) });
    const got = place(damaging, "dw", [...alike, other], { PRIMARY: [alike[1]], SECONDARY: [alike[0]], ANY: [other] });
    expect(keysOf(got)).toEqual({ PRIMARY: ["b-alike"], SECONDARY: ["c-alike"], ANY: ["a-other"] });
  });

  it("leaves the off hand empty for a two-hander, and never puts a two-hander in it", () => {
    const axe = gear("axe-2h", ["PRIMARY"], { stats: { HP: 10 }, weapon: twoHand(20, 40) });
    const sword = gear("sword", eitherHand, { stats: { HP: 10 }, weapon: oneHand(10, 30) });
    // by key the two-hander is first, and with it in the main hand the sword cannot take the off hand: the next arrangement is the two-hander alone
    for (const groups of [{ PRIMARY: [sword], ANY: [axe] }, { PRIMARY: [axe], ANY: [sword] }, { ANY: [axe, sword] }]) {
      expect(keysOf(place(stick, "stick", [axe, sword], groups))).toEqual({ PRIMARY: ["axe-2h"], ANY: ["sword"] });
    }
    // with a one-hander whose key is first, that one takes the main hand, and the two-hander has no hand to stand in
    const lone = gear("a-lone", eitherHand, { stats: { HP: 10 }, weapon: oneHand(10, 30) });
    expect(keysOf(place(stick, "stick", [axe, lone], { ANY: [axe, lone] }))).toEqual({ PRIMARY: ["a-lone"], ANY: ["axe-2h"] });
  });

  it("lets the setup decide what may stand in the off hand", () => {
    const [sword, dagger] = oneHanders(["a-sword", "b-dagger"]);
    const guard = gear("c-guard", ["SECONDARY"], { stats: { HP: 10 }, shield: true });
    expect(keysOf(place(stick, "1h-shield", [sword, dagger, guard], { PRIMARY: [dagger], ANY: [sword, guard] }))).toEqual({ PRIMARY: ["a-sword"], SECONDARY: ["c-guard"], ANY: ["b-dagger"] });
    // no weapon may take the off hand under the shield setup, though both list it
    expect(keysOf(place(stick, "1h-shield", [sword, dagger], { PRIMARY: [dagger], ANY: [sword] }))).toEqual({ PRIMARY: ["a-sword"], ANY: ["b-dagger"] });
  });

  it("fills both hands with two copies of one item, and one hand with one", () => {
    const [dagger] = oneHanders(["dagger"]);
    expect(keysOf(place(stick, "dw", [dagger], { ANY: [dagger, dagger] }))).toEqual({ PRIMARY: ["dagger"], SECONDARY: ["dagger"] });
    expect(keysOf(place(stick, "dw", [dagger], { ANY: [dagger] }))).toEqual({ PRIMARY: ["dagger"] });
  });

  it("does not take an arrangement that leaves an item without a place", () => {
    const [dagger] = oneHanders(["a-dagger"]);
    const club = gear("b-club", ["PRIMARY"], { stats: { HP: 10 }, weapon: oneHand(12, 30) });
    // the explicit rule: no Any place takes either, so the dagger in the main hand would leave the club nowhere to stand
    expect(keysOf(place(stick, "stick", [dagger, club], { PRIMARY: [club], SECONDARY: [dagger] }, explicit))).toEqual({ PRIMARY: ["b-club"], SECONDARY: ["a-dagger"] });
  });

  it("values only the arrangements that come before the solver's in the order", () => {
    const [axe, mace, sword] = oneHanders(["axe", "mace", "sword"]);
    const model = buildMilp(stick, [axe, mace, sword], "stick", null, options);
    let calls = 0;
    const counting = (kit) => {
      calls += 1;
      return valuing(stick, "stick")(kit);
    };
    placeCanonically(model, new Map([["PRIMARY", [axe]], ["SECONDARY", [mace]], ["ANY", [sword]]]), counting);
    expect(calls).toBe(0); // the solver's arrangement is the first of the order: there is nothing to compare it with
    placeCanonically(model, new Map([["PRIMARY", [mace]], ["SECONDARY", [axe]], ["ANY", [sword]]]), counting);
    expect(calls).toBe(2); // its own value, and the first arrangement of the order, which is worth as much: no more
  });

  it("reads an item with no weapon field as an item with no weapon: the evaluator's own error meets it, never a TypeError", () => {
    // the builder takes a missing weapon as none, so such items get columns in the hands; the evaluator wants the field (null for none)
    const bare = (key) => {
      const item = { ...oneHanders([key])[0] };
      delete item.weapon;
      return item;
    };
    const [axe, mace] = [bare("axe"), bare("mace")];
    const model = buildMilp(stick, [axe, mace], "stick", null, options);
    const groups = () => new Map([["PRIMARY", [mace]], ["SECONDARY", [axe]]]); // the arrangement before this one has both hands filled: the main hand is read for a two-hander
    let caught = null;
    try {
      placeCanonically(model, groups(), valuing(stick, "stick"));
    } catch (error) {
      caught = error;
    }
    expect(caught, "the evaluator refuses an item with no weapon field").toBeInstanceOf(EvaluateError);
    expect(caught).not.toBeInstanceOf(TypeError);
    // and with a value that takes the items as they are, they are no two-handers: the pair of the order stands in the hands
    expect(keysOf(placeCanonically(model, groups(), () => q(0)))).toEqual({ PRIMARY: ["axe"], SECONDARY: ["mace"] });
  });

  it("refuses a rearrangement that changed the items or the value", () => {
    const [a, b] = oneHanders(["a", "b"]);
    const was = new Map([["ANY", [a, b]]]);
    expect(() => checkRearranged(was, new Map([["PRIMARY", [b]], ["SECONDARY", [a]]]), q(5), q(5))).not.toThrow();
    expect(() => checkRearranged(was, new Map([["PRIMARY", [b]], ["SECONDARY", [a]]]), null, q(5))).not.toThrow(); // the hands were left as they were
    expect(() => checkRearranged(was, new Map([["PRIMARY", [b]]]), q(5), q(5))).toThrow(PlacementError);
    expect(() => checkRearranged(new Map([["ANY", [a, a]]]), new Map([["PRIMARY", [a]], ["SECONDARY", [b]]]), q(5), q(5))).toThrow(/items/);
    expect(() => checkRearranged(was, new Map([["PRIMARY", [b]], ["SECONDARY", [a]]]), q(5), q(6))).toThrow(/value/);
    expect(new PlacementError("x")).toBeInstanceOf(SolveError);
  });

  it("gives a solved kit the same hands whatever the order of the pool", () => {
    const pool = oneHanders(["k1", "k2", "k3", "k4", "k5"], { lore: true }); // Lore: the kit holds four different ones, not four copies of the first
    const seen = new Set();
    for (let run = 0; run < 6; run += 1) {
      const session = createSession({ highs, profile: stick, setup: "stick" });
      try {
        setScenario(session, "s", shuffled(pool, run), options);
        const got = solve(session, { scenario: "s", budgetMs: 60_000, canonical: true });
        seen.add(JSON.stringify(got.kit.map((item) => (item === null ? null : item.key))));
      } finally {
        closeSession(session);
      }
    }
    expect([...seen]).toEqual([JSON.stringify([...new Array(18).fill(null), "k3", "k4", "k1", "k2"])]); // the Any places, then the main hand and the off hand
  });
});

describe("the tie ranks and the tie stage", () => {
  it("ranks an item column by the place of its item among the sorted eligible items, counted from 1, and a buff after all of them", () => {
    const profile = profileWith({ weights: { HP: 1 } });
    const items = [gear("b", ["HEAD"], { stats: { HP: 1 } }), gear("a", ["HEAD"], { stats: { HP: 2 } }), gear("c", ["NECK"], { stats: { HP: 3 }, classes: ["MNK"] })];
    const buffset = buffsetOf({ optional: [buffOf(30, { HP: 5 }), buffOf(20, { HP: 6 })], conflicts: [[20, 30]] });
    const model = buildMilp(profile, items, "stick", buffset, { any_rule: "explicit" });
    // c is for a Monk: no class of this trio can wear it, so it is not eligible and takes no rank
    const eligible = [["a", 0], ["b", 0]];
    const ranks = tieRanks(model, eligible);
    const byName = Object.fromEntries([...ranks].map(([col, rank]) => [model.col_names[col], rank]));
    expect(byName["n[HEAD|a]"]).toBe(1);
    expect(byName["n[HEAD|b]"]).toBe(2);
    expect(byName["buff[20]"]).toBe(3);
    expect(byName["buff[30]"]).toBe(4);
    expect(Object.keys(byName)).toHaveLength(4);
  });

  it("keeps the first stage's kit when the band admits a kit that is exactly worse (a heavy weight against a tiny one)", () => {
    // HP is worth 1000 a point and CHA a thousandth: the value is some 10^7, the band 1, and the ring that adds 0.1 can be dropped for a lower rank
    const profile = profileWith({ weights: { HP: 1000, CHA: 0.001 } });
    const ring = gear("cha-ring", ["FINGER"], { stats: { CHA: 100 } });
    const session = createSession({ highs, profile, setup: "stick" });
    try {
      setScenario(session, "s", [ring], { any_rule: "explicit", haste_assumed: 0 });
      const got = solve(session, { scenario: "s", budgetMs: 60_000, canonical: true });
      expect(got.status).toBe("optimal");
      expect(got.tieStage).toBe("kept-first");
      expect(got.canonical).toBe(false);
      expect(got.kit.filter((item) => item !== null).map((item) => item.key)).toEqual(["cha-ring", "cha-ring"]); // the first stage's kit: both rings
      const empty = solve(session, { scenario: "s", budgetMs: 60_000 });
      expect(got.F.toString()).toBe(empty.F.toString());
      expect(TIE_TOLERANCE * got.F.toNumber()).toBeGreaterThan(0.2); // the band is wider than the rings' worth
    } finally {
      closeSession(session);
    }
  });

  it("applies the tie stage, and keeps the item of the smaller rank, when the kits are exactly equal", () => {
    const profile = profileWith({ weights: { HP: 1 } });
    const twins = [gear("m-ring", ["FINGER"], { stats: { HP: 10 } }), gear("a-ring", ["FINGER"], { stats: { HP: 10 } }), gear("z-ring", ["FINGER"], { stats: { HP: 10 } })];
    const session = createSession({ highs, profile, setup: "stick" });
    try {
      for (const order of [twins, [...twins].reverse(), [twins[1], twins[2], twins[0]]]) {
        setScenario(session, "s", order, { any_rule: "explicit", haste_assumed: 0 });
        const got = solve(session, { scenario: "s", budgetMs: 60_000, canonical: true });
        expect(got.tieStage).toBe("applied");
        expect(got.canonical).toBe(true);
        expect(got.kit.filter((item) => item !== null).map((item) => item.key)).toEqual(["a-ring", "a-ring"]);
      }
    } finally {
      closeSession(session);
    }
  });
});

describe("the exactness check", () => {
  it("refuses a model value more than 1e-6 relative above the evaluator's, and not one at or below it", () => {
    expect(EXACTNESS_TOLERANCE).toBe(1e-6);
    expect(TIE_TOLERANCE).toBe(1e-7);
    expect(() => checkExactness(10 + 1e-3, 10)).toThrow(ExactnessError);
    expect(() => checkExactness(10 + 0.9e-5, 10)).not.toThrow();
    expect(() => checkExactness(10, 10)).not.toThrow();
    expect(() => checkExactness(9, 10)).not.toThrow(); // below is no error
    expect(() => checkExactness(1e9 * (1 + 1.1e-6), 1e9)).toThrow(ExactnessError);
    expect(() => checkExactness(1e9 * (1 + 0.9e-6), 1e9)).not.toThrow();
    // a value below 1 is held to an absolute 1e-6
    expect(() => checkExactness(1.1e-6, 0)).toThrow(ExactnessError);
    expect(() => checkExactness(0.9e-6, 0)).not.toThrow();
    // a value that is not a number is no value to compare: the comparison would call it fine
    for (const [model, value] of [[Number.NaN, 1], [1, Number.NaN], [Number.POSITIVE_INFINITY, 1], [1, Number.NEGATIVE_INFINITY]]) expect(() => checkExactness(model, value)).toThrow(ExactnessError);
    expect(new ExactnessError("x")).toBeInstanceOf(SolveError);
  });
});

describe("the arguments", () => {
  const profile = profileWith({ weights: { HP: 1 } });
  const make = (changes = {}) => createSession({ highs, profile, setup: "stick", ...changes });

  it("refuses what a session cannot be made from", () => {
    expect(() => createSession({ profile, setup: "stick" })).toThrow(SolveError); // no solver
    expect(() => createSession({ highs, setup: "stick" })).toThrow(); // no profile
    expect(() => make({ setup: "bow" })).toThrow(/setup/);
    expect(() => make({ extra: 1 })).toThrow(/extra/);
    expect(() => make({ options: { owned_caps: {} } })).toThrow(/owned_caps/);
    expect(() => make({ options: { any_rule: "some" } })).toThrow();
    expect(() => make({ now: 5 })).toThrow(SolveError);
    expect(() => createSession(null)).toThrow(SolveError);
    closeSession(make());
  });

  it("refuses a request that is not understood, and says which option", () => {
    const session = make();
    try {
      setScenario(session, "s", [gear("ring", ["FINGER"], { stats: { HP: 5 } })], {});
      expect(() => solve(session, {})).toThrow(/budgetMs/);
      expect(() => solve(session, { budgetMs: -1 })).toThrow(/budgetMs/);
      expect(() => solve(session, { budgetMs: Number.NaN })).toThrow(/budgetMs/);
      expect(() => solve(session, { budgetMs: Infinity })).toThrow(/budgetMs/);
      expect(() => solve(session, { budgetMs: "5" })).toThrow(/budgetMs/);
      expect(() => solve(session, { budgetMs: 100, canonical: "yes" })).toThrow(/canonical/);
      expect(() => solve(session, { budgetMs: 100, speed: 1 })).toThrow(/speed/);
      expect(() => solve(session, { budgetMs: 100, scenario: "nope" })).toThrow(/scenario/);
      expect(() => solve(session, { budgetMs: 100, highsOptions: { threads: 2 } })).toThrow(/threads/);
      expect(() => solve(session, { budgetMs: 100, highsOptions: { time_limit: 5 } })).toThrow(/time_limit/);
      expect(() => solve(session, { budgetMs: 100, highsOptions: { no_such_option: 5 } })).toThrow(SolveError);
      expect(() => solve(null, { budgetMs: 100 })).toThrow(SolveError);
      expect(() => solve(make(), { budgetMs: 100 })).toThrow(/scenario/); // nothing set yet
      expect(() => setScenario(session, "", [], {})).toThrow(/name/);
      expect(() => setScenario(session, "s", "ring", {})).toThrow();
      expect(() => setScenario(session, "s", [], { hast: 1 })).toThrow(); // an option the builder does not read
      // a refused build leaves the scenario as it was
      expect(solve(session, { scenario: "s", budgetMs: 1000 }).status).toBe("optimal");
    } finally {
      closeSession(session);
    }
  });

  it("does not use a session that was closed", () => {
    const session = make();
    setScenario(session, "s", [], {});
    closeSession(session);
    closeSession(session); // twice is no harm
    expect(() => solve(session, { scenario: "s", budgetMs: 100 })).toThrow(/closed/);
    expect(() => setScenario(session, "s", [], {})).toThrow(/closed/);
  });

  it("reads a profile, a buff set and the Monk bins once, and does not change what it is given", () => {
    const given = clone(profile);
    const before = JSON.stringify(given);
    const session = createSession({ highs, profile: given, setup: "stick" });
    try {
      setScenario(session, "s", [gear("ring", ["FINGER"], { stats: { HP: 5 } })], {});
      expect(JSON.stringify(given)).toBe(before);
      expect(Object.isFrozen(given)).toBe(false);
      given.weights.HP = 99; // a change after the session was made is not seen by it
      expect(solve(session, { scenario: "s", budgetMs: 1000 }).F.toNumber()).toBeLessThan(1e6);
    } finally {
      closeSession(session);
    }
  });

  it("copies a profile, a buff set and Monk bins exactly, and refuses what is not plain data instead of turning it into null or dropping it", () => {
    const naked = (change) => ({ ...profile, naked: { ...profile.naked, ...change } });
    class Odd {}
    const cycle = { ...profile };
    cycle.self = cycle;
    const holey = { ...profile, softcap: new Array(2) };
    const refused = {
      "NaN": naked({ STR: Number.NaN }),
      "Infinity": naked({ STR: Number.POSITIVE_INFINITY }),
      "-Infinity": naked({ STR: Number.NEGATIVE_INFINITY }),
      "undefined": naked({ STR: undefined }),
      "a function": naked({ STR: () => 1 }),
      "a symbol": naked({ STR: Symbol("x") }),
      "a bigint": naked({ STR: 5n }),
      "a Date": naked({ STR: new Date(0) }),
      "a Map": naked({ STR: new Map() }),
      "an instance of a class": naked({ STR: new Odd() }),
      "a hole in a list": holey,
      "a cycle": cycle,
      "a symbol for a key": { ...profile, [Symbol("k")]: 1 },
      "an accessor": Object.defineProperty({ ...profile }, "level", { get: () => 50, enumerable: true }),
    };
    for (const [what, bad] of Object.entries(refused)) {
      expect(() => createSession({ highs, profile: bad, setup: "stick" }), what).toThrow(SolveError);
    }
    const buffset = buffsetOf({ optional: [buffOf(7, { HP: 100 })] });
    expect(() => createSession({ highs, profile, setup: "stick", buffset: { ...buffset, table: { ...buffset.table, 7: { vec: { HP: Number.NaN } } } } })).toThrow(SolveError);
    expect(() => createSession({ highs, profile, setup: "stick", monkBins: { curve: undefined, bonus: [] } })).toThrow(SolveError);
    // what is plain is copied as it is, -0 and the order of the keys included, into an object of its own that is frozen all through
    const given = { ...clone(profile), softcap: [0, -0] };
    const session = createSession({ highs, profile: given, setup: "stick" });
    try {
      expect(session.profile).toEqual(given);
      expect(Object.is(session.profile.softcap[1], -0)).toBe(true);
      expect(Object.keys(session.profile)).toEqual(Object.keys(given));
      expect(session.profile).not.toBe(given);
      expect(Object.isFrozen(session.profile) && Object.isFrozen(session.profile.pools.HP[0])).toBe(true);
    } finally {
      closeSession(session);
    }
  });

  it("refuses a solution that has an entry which is not a number, whichever column it is in", () => {
    const poisoned = (column, value) => (solution) => {
      const colValue = Float64Array.from(solution.colValue);
      colValue[column] = value;
      return { ...solution, colValue };
    };
    for (const value of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
      for (const kind of ["item", "other"]) {
        const probe = createSession({ highs, profile, setup: "stick", options: { any_rule: "explicit", haste_assumed: 0 } });
        const ring = gear("ring", ["FINGER"], { stats: { HP: 5, STA: 3 } });
        setScenario(probe, "s", [ring], {});
        const model = probe.scenarios.get("s").model;
        const column = kind === "item" ? model.item_cols[0][0] : model.col_names.findIndex((name) => !name.startsWith("n["));
        closeSession(probe);
        expect(column, kind).toBeGreaterThanOrEqual(0);
        const { highs: spied } = spyOn(highs, { solution: poisoned(column, value) });
        const session = createSession({ highs: spied, profile, setup: "stick", options: { any_rule: "explicit", haste_assumed: 0 } });
        try {
          setScenario(session, "s", [ring], {});
          expect(() => solve(session, { scenario: "s", budgetMs: 60_000 }), `${kind} column ${column} = ${value}`).toThrow(SolveError);
        } finally {
          closeSession(session);
        }
      }
    }
  });
});

// ---- the time of a call, its stages and its start ------------------------------------------------------------------------------------------

describe("the time of a call", () => {
  const shared = sharedOf(SAMPLE);
  const doc = SAMPLE.read(SAMPLE.paths("case", "upgrade/")[0]);
  const c = caseOf(shared, doc);
  const [equip, step1] = doc.solves;
  const TICK = 3;

  /** A session on a clock that moves by `tick` at every look, on a solver that logs the limits and the starts. */
  function ticking(more = {}, tick = TICK) {
    let clock = 0;
    const spied = spyOn(highs, { clock: () => clock, ...more.hooks?.(() => clock, (to) => (clock = to)) });
    const session = createSession({ highs: spied.highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins, now: () => (clock += tick) });
    return { session, log: spied.log, clock: () => clock, set: (to) => (clock = to) };
  }

  it("hands HiGHS the time that is left at the moment it hands it over, not the time that was left when the call began", () => {
    const { session, log, clock } = ticking();
    try {
      setScenario(session, "s", c.poolOf(equip), deepFreeze(clone(equip.options)));
      const began = clock();
      const budgetMs = 1000;
      const deadline = began + TICK + budgetMs; // the call looks at the clock once, to know when it began
      solve(session, { scenario: "s", budgetMs });
      expect(log.limits).toHaveLength(1);
      const [limit] = log.limits;
      expect(limit.limitMs).toBeLessThanOrEqual(deadline - limit.at + 1e-6);
      expect(limit.limitMs).toBeGreaterThan(deadline - limit.at - 1e-6); // and it is all of what is left
    } finally {
      closeSession(session);
    }
  });

  it("gives each stage of a canonical call its own budget, as Python gives each stage its own time limit", () => {
    // a first stage that takes 400 ms of the clock: the second stage still has the whole budget
    const { session, log, set, clock } = ticking({ hooks: (read, move) => ({ before: () => move(read() + 400) }) });
    try {
      setScenario(session, "s", c.poolOf(equip), deepFreeze(clone(equip.options)));
      // (the whole tie stage, `tieShortcut: false`: the stages of the shortcut have their own test, in engine-tie-shortcut)
      const answer = solve(session, { scenario: "s", budgetMs: 1000, canonical: true, tieShortcut: false });
      expect(answer.tieStage).toBe("applied");
      expect(log.limits).toHaveLength(2);
      expect(log.limits[0].limitMs).toBeGreaterThan(1000 - 4 * TICK);
      expect(log.limits[1].limitMs, "the second stage's own budget, not what the first left of the call's").toBeGreaterThan(1000 - 4 * TICK);
      expect(log.limits[1].limitMs).toBeLessThanOrEqual(1000);
      expect(set).toBeTypeOf("function");
      expect(clock()).toBeGreaterThan(800); // both stages took their 400 ms: the call took about twice its budget's worth of clock, as documented
    } finally {
      closeSession(session);
    }
  });

  it("ends the first stage by the deadline it is given when that is before the end of the budget, and gives the tie stage the budget in full", () => {
    // the clock stands still: the limit is the earlier of the end of the budget and the deadline, as it is when it is handed over, and never below 0
    const { session, log } = ticking({}, 0);
    try {
      setScenario(session, "s", c.poolOf(equip), deepFreeze(clone(equip.options)));
      solve(session, { scenario: "s", budgetMs: 1000, deadline: 300 });
      solve(session, { scenario: "s", budgetMs: 200, deadline: 1000 });
      solve(session, { scenario: "s", budgetMs: 1000, deadline: -5 });
      solve(session, { scenario: "s", budgetMs: 1000, canonical: true, deadline: 300, tieShortcut: false });
      expect(log.limits.map((limit) => limit.limitMs)).toEqual([300, 200, 0, 300, 1000]);
      for (const bad of [Number.NaN, Number.POSITIVE_INFINITY, "300", null, {}, [300]]) {
        expect(() => solve(session, { scenario: "s", budgetMs: 100, deadline: bad }), String(bad)).toThrow(SolveError);
      }
    } finally {
      closeSession(session);
    }
  });

  it("tells progress by stage: the first stage's events carry the model's objective, the tie stage's the first stage's objective and never its own", () => {
    const types = highs.constants.callbackType;
    const fired = (run, callbacks) => {
      if (callbacks === undefined) return;
      callbacks[types.mipImprovingSolution]({ data: { objective_function_value: 123456 } }); // what the solver would report: a number of its own
      callbacks[types.mipLogging]({ data: { mip_dual_bound: 99999, mip_gap: 0.5, mip_node_count: 7 } });
    };
    const spied = spyOn(highs, { before: fired });
    const session = createSession({ highs: spied.highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins });
    const plain = createSession({ highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins });
    try {
      const options = deepFreeze(clone(equip.options));
      setScenario(plain, "s", c.poolOf(equip), options);
      const first = solve(plain, { scenario: "s", budgetMs: BUDGET_MS });
      setScenario(session, "s", c.poolOf(equip), options);
      const events = [];
      // (the tie stage's own events are what is held here: `tieShortcut: false`, since a band of one kit is not searched by the tie stage)
      const answer = solve(session, { scenario: "s", budgetMs: BUDGET_MS, canonical: true, tieShortcut: false, onProgress: (event) => events.push(event) });
      expect(answer.tieStage).toBe("applied");
      const model = session.scenarios.get("s").model;
      const solving = events.filter((event) => event.stage === "solve");
      const tie = events.filter((event) => event.stage === "tie");
      expect(solving.length + tie.length, "every event says which stage it is of").toBe(events.length);
      expect(solving.length).toBeGreaterThan(0);
      expect(tie.length).toBeGreaterThan(0);
      for (const event of solving) {
        expect(event.phase).toBe("solving");
        // the solver's own number plus the constant of the model (the solver's real improving solutions come through too, and are no better than the optimum)
        if ("objective" in event && event.objective !== 123456 + model.const) expect(event.objective).toBeLessThanOrEqual(first.modelF + 1e-6 * Math.abs(first.modelF));
      }
      expect(solving.some((event) => event.objective === 123456 + model.const)).toBe(true);
      for (const event of tie) {
        expect(event.phase).toBe("solving");
        expect(event.objective, "the first stage's objective").toBe(first.modelF);
        expect(event).not.toHaveProperty("bound"); // the bound and the gap of a rank are not those of the value
        expect(event).not.toHaveProperty("gap");
      }
    } finally {
      closeSession(session);
      closeSession(plain);
    }
  });

  it("starts from the kit it is given, then from the last solution, and from the last kit when the solver's model is made anew", () => {
    const { highs: spied, log } = spyOn(highs);
    const session = createSession({ highs: spied, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins });
    try {
      setScenario(session, "s", c.poolOf(equip), deepFreeze(clone(equip.options)));
      const cold = solve(session, { scenario: "s", budgetMs: BUDGET_MS });
      expect(cold.start).toBeNull();
      expect(log.starts).toHaveLength(0);
      expect(solve(session, { scenario: "s", budgetMs: BUDGET_MS }).start).toBe("solution"); // the same columns: the last solution as it is
      expect(log.starts[0]).toHaveProperty("colValue");
      // another scenario, started from the kit of the first: its item and buff columns, and nothing but them
      setScenario(session, "t", c.poolOf(step1), deepFreeze(clone(step1.options)));
      const given = solve(session, { scenario: "t", budgetMs: BUDGET_MS, start: cold });
      expect(given.start).toBe("kit");
      const start = log.starts[log.starts.length - 1];
      const model = session.scenarios.get("t").model;
      const wears = new Map();
      cold.kit.forEach((item, at) => {
        if (item !== null) wears.set(`${SLOT_INSTANCES[at]}|${identOf(item)}`, (wears.get(`${SLOT_INSTANCES[at]}|${identOf(item)}`) ?? 0) + 1);
      });
      const want = [...model.item_cols.map(([column, group, key, tier]) => [column, wears.get(`${group}|${key}@${tier}`) ?? 0]), ...model.buff_cols.map(([column, id]) => [column, cold.buffs.includes(id) ? 1 : 0])];
      want.sort((a, b) => a[0] - b[0]);
      expect(Array.from(start.indices)).toEqual(want.map(([column]) => column));
      expect(Array.from(start.values)).toEqual(want.map(([, value]) => value));
      // a model made anew keeps the item and buff columns of the last kit
      setScenario(session, "t", c.poolOf(equip), deepFreeze(clone(equip.options)));
      expect(solve(session, { scenario: "t", budgetMs: BUDGET_MS }).start).toBe("kit");
      // what is given is checked: a kit of 22 places of items and the ids of buffs
      for (const bad of [null, 5, {}, { kit: [] }, { kit: cold.kit, buffs: [1.5] }, { kit: [...cold.kit.slice(1), 5] }, { kit: cold.kit.slice(1) }, { kit: [...cold.kit.slice(1), {}] }]) {
        expect(() => solve(session, { scenario: "t", budgetMs: 100, start: bad }), JSON.stringify(bad)).toThrow(SolveError);
      }
    } finally {
      closeSession(session);
    }
  });

  it("re-solves a scenario from its warm start under a forced node limit and answers time_limit, with an exact value at or below the optimum, and the label", () => {
    const { c: hard, recorded: hardSolve } = aTree();
    const session = sessionFor(hard);
    try {
      setScenario(session, "s", hard.poolOf(hardSolve), deepFreeze(clone(hardSolve.options)));
      const optimal = solve(session, { scenario: "s", budgetMs: BUDGET_MS });
      expect(optimal.status).toBe("optimal");
      expect(optimal.nodes).toBeGreaterThan(1); // the proof needs a tree, so that a limit of one node stops it
      const stopped = solve(session, { scenario: "s", budgetMs: BUDGET_MS, highsOptions: { mip_max_nodes: 1 } });
      expect(stopped.start).toBe("solution"); // it began from the optimum it had
      expect(stopped.status).toBe("time_limit");
      expect(stopped.proven).toBe(false);
      expect(stopped.label).toBe(LABEL_TIME_LIMIT);
      expect(stopped.F).not.toBeNull();
      expect(stopped.F.compare(optimal.F)).toBeLessThanOrEqual(0);
      const options = { setup: hard.setup, hasteAssumed: stopped.hasteAssumed, monkBins: hard.bins, buffset: hard.buffset ?? undefined };
      expect(evaluate(hard.profile, stopped.kit, hard.buffset === null ? null : stopped.buffs, options).F.toString()).toBe(stopped.F.toString());
      // and the same from a start that is worse than the optimum: a smaller count of what the best kit wears most
      expect(solve(session, { scenario: "s", budgetMs: BUDGET_MS }).status).toBe("optimal"); // nothing is left of the limit
    } finally {
      closeSession(session);
    }
  });
});

// ---- the solver's data -----------------------------------------------------------------------------------------------------------------

describe("the solver's data", () => {
  const engine = (name) => new URL(`../pipeline/trioforge/site/static/engine/${name}`, import.meta.url);

  it("lives in a leaf module that worker.js re-exports, so that solve.js does not import the worker (and the worker can import solve.js)", async () => {
    const data = await import("../pipeline/trioforge/site/static/engine/highs-data.js");
    const worker = await import("../pipeline/trioforge/site/static/engine/worker.js");
    expect(Object.keys(data).sort()).toEqual(["SOLVER_OPTIONS", "toModelData"]);
    expect(worker.SOLVER_OPTIONS).toBe(data.SOLVER_OPTIONS);
    expect(worker.toModelData).toBe(data.toModelData);
    expect(SOLVER_OPTIONS).toBe(data.SOLVER_OPTIONS);
    expect(readFileSync(engine("highs-data.js"), "utf8")).not.toMatch(/^\s*(?:import\s|export\s[^=]*\sfrom\s)/m); // a leaf: it imports nothing
    for (const name of ["solve.js", "prune.js", "path.js"]) expect(readFileSync(engine(name), "utf8"), name).not.toMatch(/from\s+"\.\/worker\.js"/);
  });
});

// The solver (or the model the builder made for it) can fail in ways that are nobody's input: a status that the solve does not accept, a solution that is not
// numbers or not whole, a model that HiGHS refuses. These are SolverFaults, which are SolveErrors that the worker tells apart from a mistake in a request.
describe("the faults of the solver", () => {
  const profile = profileWith({ weights: { HP: 1 } });
  const ring = gear("ring", ["FINGER"], { stats: { HP: 5, STA: 3 } });
  const OPTIONS = { any_rule: "explicit", haste_assumed: 0 };
  const sessionWith = (solver) => {
    const session = createSession({ highs: solver, profile, setup: "stick", options: OPTIONS });
    setScenario(session, "s", [ring], {});
    return session;
  };

  it("are a kind of SolveError, so that whoever catches a SolveError catches them, with a name of their own", () => {
    const fault = new SolverFault("x");
    expect(fault).toBeInstanceOf(SolveError);
    expect(fault).toBeInstanceOf(Error);
    expect(fault.name).toBe("SolverFault");
    expect(new SolveError("x")).not.toBeInstanceOf(SolverFault);
    expect(new ExactnessError("x")).not.toBeInstanceOf(SolverFault); // a model that overstates its kit is the builder's fault, not the solver's
    expect(new PlacementError("x")).not.toBeInstanceOf(SolverFault);
  });

  it("include a run that ends in a status the solve does not accept", () => {
    const unbounded = highs.constants.modelStatus.unbounded;
    const { highs: spied } = spyOn(highs, { outcome: (result) => ({ ...result, modelStatus: unbounded }) });
    const session = sessionWith(spied);
    try {
      expect(() => solve(session, { scenario: "s", budgetMs: 60_000 })).toThrow(SolverFault);
      expect(() => solve(session, { scenario: "s", budgetMs: 60_000 })).toThrow(/ended with the status/);
    } finally {
      closeSession(session);
    }
  });

  it("include a solution with an entry that is not a number, and one that is not whole", () => {
    const probe = sessionWith(highs);
    const model = probe.scenarios.get("s").model;
    const column = model.item_cols[0][0];
    closeSession(probe);
    const poisoned = (value) => (solution) => {
      const colValue = Float64Array.from(solution.colValue);
      colValue[column] = value;
      return { ...solution, colValue };
    };
    for (const [value, said] of [[Number.NaN, /not a number/], [Number.POSITIVE_INFINITY, /not a number/], [0.5, /not an integer/]]) {
      const { highs: spied } = spyOn(highs, { solution: poisoned(value) });
      const session = sessionWith(spied);
      try {
        expect(() => solve(session, { scenario: "s", budgetMs: 60_000 }), String(value)).toThrow(SolverFault);
        expect(() => solve(session, { scenario: "s", budgetMs: 60_000 }), String(value)).toThrow(said);
      } finally {
        closeSession(session);
      }
    }
  });

  it("include a model that HiGHS refuses", () => {
    const refusing = Object.create(highs, {
      createModel: {
        value() {
          throw new highs.errors.HighsError("a refused model");
        },
      },
    });
    const session = createSession({ highs: refusing, profile, setup: "stick", options: OPTIONS });
    try {
      expect(() => setScenario(session, "s", [ring], {})).toThrow(SolverFault);
      expect(() => setScenario(session, "s", [ring], {})).toThrow(/would not take this model/);
    } finally {
      closeSession(session);
    }
  });

  it("do not include what a caller gets wrong: an option the solver does not know, a request that is not understood, a session that is closed", () => {
    const session = sessionWith(highs);
    try {
      let error;
      try {
        solve(session, { scenario: "s", budgetMs: 100, highsOptions: { no_such_option: 5 } });
      } catch (caught) {
        error = caught;
      }
      expect(error).toBeInstanceOf(SolveError);
      expect(error).not.toBeInstanceOf(SolverFault);
      expect(() => solve(session, { budgetMs: -1 })).not.toThrow(SolverFault);
    } finally {
      closeSession(session);
    }
    expect(() => solve(session, { scenario: "s", budgetMs: 100 })).toThrow(SolveError);
    try {
      solve(session, { scenario: "s", budgetMs: 100 });
    } catch (error) {
      expect(error).not.toBeInstanceOf(SolverFault);
    }
  });
});

// the families that the tests above go through are the families of the fixtures
describe("the families", () => {
  it("are the four the fixtures hold", () => {
    expect(FAMILIES).toEqual(["matrix", "upgrade", "pmb36", "brute"]);
  });
});
