import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { readResults } from "./shard-results.mjs";
import { report, solveIds, viewList } from "../scripts/profile-engine.mjs";

// scripts/profile-engine.mjs times the browser engine on the views of a folder of results. It changes nothing, but it counts the solver's runs by wrapping `createModel`
// of the loaded solver, and a wrapper that went wrong would show here: the views come out solved and optimal, the counts add up, and the plain solve (no tie stage) runs no tie stage.

const FIXTURE = fileURLToPath(new URL("../fixtures/site/results-solved/", import.meta.url));
const MODE = { canonical: true, haste: null };

describe("scripts/profile-engine.mjs, on the invented catalog of the site fixture", () => {
  const results = readResults(FIXTURE);
  const views = viewList(results);
  const ids = [0, Math.floor(views.count / 3), Math.floor((2 * views.count) / 3), views.count - 1];

  it("lists every row of the shards once, in the order of the shard parity check", () => {
    expect(views.count).toBe(views.units.reduce((sum, unit) => sum + unit.chunk.rows.length, 0));
    expect(views.at(0).row).toBe(views.units[0].chunk.rows[0]);
    expect(views.at(views.count - 1).row).toBe(views.units.at(-1).chunk.rows.at(-1));
    const seen = new Set();
    for (let id = 0; id < views.count; id += 1) seen.add(views.at(id).row);
    expect(seen.size).toBe(views.count);
  });

  it("solves views to the end and counts what the solver did", async () => {
    const found = await solveIds(FIXTURE, ids, null, MODE);
    expect(found.map((view) => view.id)).toEqual(ids);
    for (const view of found) {
      expect(view.fault).toBeNull();
      expect(view.status).toBe("optimal");
      expect(view.ms).toBeGreaterThan(0);
      expect(view.levels).toBeGreaterThanOrEqual(1);
      expect(view.outcomes.solved + view.outcomes.bound + view.outcomes.infeasible + view.outcomes.time).toBe(view.levels);
      expect(view.pruned).toBeLessThanOrEqual(view.pool);
      expect(view.F).not.toBeNull();
      // a first-stage solve for every level the bound did not rule out, and a tie stage for the levels that were solved to a kit
      expect(view.mipRuns).toBeGreaterThanOrEqual(view.outcomes.solved);
      expect(view.tieRuns).toBeLessThanOrEqual(view.mipRuns);
    }
    expect(found.some((view) => view.mipRuns > 0 && view.tieRuns > 0)).toBe(true);
  });

  it("the plain solve (what a visitor's browser does) runs no tie stage and finds the same value", async () => {
    const [canonical, plain] = [await solveIds(FIXTURE, ids, null, MODE), await solveIds(FIXTURE, ids, null, { canonical: false, haste: null })];
    for (const [at, view] of plain.entries()) {
      expect(view.tieRuns).toBe(0);
      expect(view.F).toBe(canonical[at].F);
    }
  });

  it("a fixed haste is one program, with no levels to bound", async () => {
    const [view] = await solveIds(FIXTURE, [ids[1]], null, { canonical: false, haste: 25 });
    expect(view.levels).toBe(1);
    expect(view.lpRuns).toBe(0);
  });

  it("the report says how many views it has, where the time went and the slowest views", async () => {
    const found = await solveIds(FIXTURE, ids, null, MODE);
    const text = report(found, { slowest: 2 });
    expect(text).toContain(`${found.length} views solved (0 faults)`);
    expect(text).toContain("where the time goes");
    expect(text).toContain("the 2 slowest views:");
    expect(text).toContain(found.slice().sort((a, b) => b.ms - a.ms)[0].name);
  });
});
