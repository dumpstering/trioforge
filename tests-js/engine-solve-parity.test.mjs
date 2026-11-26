import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { evaluate } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { closeSession, createSession, setScenario, solve } from "../pipeline/trioforge/site/static/engine/solve.js";
import { caseOf, clone, deepFreeze, exact, kitPairs, sharedOf } from "./engine-cases.mjs";
import { SAMPLE, describeFull } from "./engine-fixtures.mjs";

// The canonical solves of the browser engine's sessions (static/engine/solve.js) held to the solver wrapper of Python (pipeline/trioforge/solver/solve.py):
//
//   * For every solve of matrix/, upgrade/ and pmb36/ (the best 2 and 3 sets of the Upgrade sessions included) the model that the session builds and solves,
//     with the tie stage and the canonical placement, gives the exact value F, the buffs and the kit that Python's `solve_canonical` found: the very kit, place
//     for place. The canonical kit depends on the items alone: among the kits of equal value the tie stage takes the least total rank, and where the same items
//     can stand in the hands and the Any places in several ways that are worth the same, the placement takes the one the rule of the hands gives (solve.py:
//     "Where the worn items stand"). The two engines (HiGHS built for the browser, and the native one) do find different arrangements on the very same model;
//     the placement makes them one.
//   * On brute/ the exact value is the maximum found by trying every legal kit, and the kit is Python's too.
//
// A session solves the solves of a case one after the other, on one model that it updates in place. The other tests of the sessions are in
// tests-js/engine-solve.test.mjs.

// a solve of the hard programs takes a second or two, and the suite runs its files side by side: the time of a test is not the default five seconds
vi.setConfig({ testTimeout: 120_000 });
const BUDGET_MS = 600_000;

/** HiGHS as the worker runs it (in Node it reads its own file), started once for this file. */
let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const sessionFor = (c, extra = {}) => createSession({ highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins, procs: c.procs, ...extra });

/** The kit and the buffs are Python's: the very kit, place for place (the exact value is checked by the caller). */
function expectPythonsKit(got, want, label) {
  expect(kitPairs(got.kit), `${label}: the kit, place for place`).toEqual(want.kit);
  expect(got.buffs, `${label}: the buffs`).toEqual(want.buffs);
}

// ---- canonical solves against Python -------------------------------------------------------------------------------------------------

function canonicalTests(set, families) {
  const shared = sharedOf(set);
  for (const family of families) {
    const paths = set.paths("case", `${family}/`);
    describe(`${family}/`, () => {
      it("has cases (all of the family the run made)", () => {
        expect(paths.length).toBeGreaterThan(0);
        expect(paths.length).toBe(set.manifest.families[family].count);
      });

      for (const path of paths) {
        const doc = set.read(path);
        it(`${doc.id} (${doc.label}): every canonical solve is the kit, place for place, the buffs and the exact value that Python found`, () => {
          const c = caseOf(shared, doc);
          const session = sessionFor(c);
          try {
            for (const recorded of doc.solves) {
              const info = setScenario(session, "main", c.poolOf(recorded), deepFreeze(clone(recorded.options)));
              expect(info.columns, `${doc.id} ${recorded.label}`).toBe(recorded.model.col_names.length);
              const got = solve(session, { scenario: "main", budgetMs: BUDGET_MS, canonical: true });
              const want = recorded.result;
              expect(got.status, `${doc.id} ${recorded.label}`).toBe("optimal");
              expect(got.label).toBeNull();
              expect(got.proven).toBe(true);
              expect(got.tieStage, `${doc.id} ${recorded.label}: the tie stage`).toBe(want.tie_stage);
              expect(got.canonical).toBe(want.tie_stage === "applied");
              expect(got.hasteAssumed).toBe(want.haste_assumed);
              expect(got.F.toString(), `${doc.id} ${recorded.label}: F`).toBe(exact(want.F).toString());
              expect(got.breakdown.F.equals(got.F)).toBe(true);
              expectPythonsKit(got, want, `${doc.id} ${recorded.label}`);
              // the value of the kit is the evaluator's, whatever the solver said
              const options = { setup: c.setup, hasteAssumed: got.hasteAssumed, monkBins: c.bins, buffset: c.buffset ?? undefined, procs: c.procs ?? undefined };
              expect(evaluate(c.profile, got.kit, c.buffset === null ? null : got.buffs, options).F.equals(got.F)).toBe(true);
            }
          } finally {
            closeSession(session);
          }
        }, 300_000);
      }
    });
  }
}

describe("canonical solves, the committed sample", () => canonicalTests(SAMPLE, ["matrix", "upgrade", "pmb36"]));
describeFull("canonical solves, the full set", (full) => canonicalTests(full, ["matrix", "upgrade", "pmb36"]));

function bruteTests(set) {
  const shared = sharedOf(set);
  const paths = set.paths("case", "brute/");
  it("has brute-force cases (all of the family the run made)", () => {
    expect(paths.length).toBeGreaterThan(0);
    expect(paths.length).toBe(set.manifest.families.brute.count);
  });
  for (const path of paths) {
    const doc = set.read(path);
    it(`${doc.id} (${doc.label}): F is the best of every legal kit and buff set, and the canonical kit is Python's, place for place`, () => {
      const c = caseOf(shared, doc);
      const [recorded] = doc.solves;
      const session = sessionFor(c);
      try {
        setScenario(session, "main", c.poolOf(recorded), deepFreeze(clone(recorded.options)));
        const got = solve(session, { scenario: "main", budgetMs: 60_000, canonical: true });
        expect(got.status).toBe("optimal");
        expect(got.F.toString(), `${doc.id}: ${got.F.toString()} against the brute-force maximum`).toBe(exact(doc.expected.brute_F).toString());
        expectPythonsKit(got, recorded.result, doc.id);
      } finally {
        closeSession(session);
      }
    }, 60_000);
  }
}

describe("brute force, the committed sample", () => bruteTests(SAMPLE));
describeFull("brute force, the full set", (full) => bruteTests(full));
