import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { differences, summary } from "../scripts/engine-compare.mjs";

// scripts/engine-compare.mjs holds the engine to itself: a saved baseline of kits, buffs, F and haste, and a diff of a new run against it. It is the gate of a speed-up, so
// the diff must see every field of an answer, and a run against a baseline made by the same engine must find nothing.

const FIXTURE = fileURLToPath(new URL("../fixtures/site/results-solved/", import.meta.url));
const SCRIPT = fileURLToPath(new URL("../scripts/engine-compare.mjs", import.meta.url));

describe("scripts/engine-compare.mjs", () => {
  const answer = { kit: ["a@0", null], buffs: [3], F: "7/2", hasteAssumed: 30, level: 30, status: "optimal", tieStage: "applied" };

  it("sees a change in any field of an answer, and none in the times", () => {
    expect(differences({ ...answer, time: { ms: 1 } }, { ...answer, time: { ms: 99 } })).toEqual([]);
    for (const change of [{ kit: ["b@0", null] }, { kit: ["a@0", "a@0"] }, { buffs: [] }, { F: "15/4" }, { hasteAssumed: 25 }, { level: 25 }, { status: "time_limit" }, { tieStage: "kept-first" }, { fault: "x" }]) {
      expect(differences(answer, { ...answer, ...change }), JSON.stringify(change)).toHaveLength(1);
    }
  });

  it("a run against a baseline made by the same engine finds every view equal, in both modes, and exits 0", () => {
    const scratch = mkdtempSync(join(tmpdir(), "engine-compare-test-"));
    try {
      const base = join(scratch, "base.json");
      const make = spawnSync(process.execPath, [SCRIPT, "--results", FIXTURE, "--out", base, "--sample", "6", "--defaults", "2", "--procs", "2"], { encoding: "utf8" });
      expect(make.status, make.stderr).toBe(0);
      const saved = JSON.parse(readFileSync(base, "utf8"));
      expect(saved.views.length).toBeGreaterThan(0);
      for (const view of saved.views) {
        expect(view.canonical.F).not.toBeNull();
        expect(view.plain.tieStage).toBeNull();
      }
      const again = spawnSync(process.execPath, [SCRIPT, "--results", FIXTURE, "--against", base, "--procs", "3"], { encoding: "utf8" });
      expect(again.status, again.stdout + again.stderr).toBe(0);
      expect(again.stdout).toContain(`canonical: ${saved.views.length} of ${saved.views.length} views equal`);
      expect(again.stdout).toContain(`plain: ${saved.views.length} of ${saved.views.length} views equal`);
      expect(summary(saved.views, saved.views.map((view) => view.id), 2)).toContain("canonical");
    } finally {
      rmSync(scratch, { recursive: true, force: true }); // (the folder this test made in the temp directory)
    }
  }, 120_000);
});
