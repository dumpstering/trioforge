// scripts/best-kit-bench.mjs: the timing of the best kit of a view with the sliders at x2. Here it runs on the synthetic results of the site fixture (an invented catalog of 48 items,
// solved in milliseconds) to hold what the script does and says: the views it looks through, the heavy ones it picks, the summary it prints. Its numbers on real results
// are the maintainer's to take, alone on a quiet machine.

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { measure, percentile, summary, timeView, viewsOf } from "../scripts/best-kit-bench.mjs";
import { BUNDLE_BYTES, ITEMS_BYTES } from "./engine-site-fixture.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const records = readItemTable(JSON.parse(ITEMS_BYTES.toString("utf8"))).records;
const bundle = readBundle(JSON.parse(BUNDLE_BYTES.toString("utf8")));
const GROUPS = Object.keys(bundle.weight_groups.groups);
const SCRIPT = fileURLToPath(new URL("../scripts/best-kit-bench.mjs", import.meta.url));
const RESULTS = fileURLToPath(new URL("../fixtures/site/results/", import.meta.url));

describe("the summary", () => {
  it("is the median, the 95th percentile and the maximum by nearest rank, of a list that is left as it was", () => {
    const list = [9, 1, 5, 3, 7, 10, 2, 8, 4, 6];
    expect(summary(list)).toEqual({ n: 10, median: 5, p95: 10, max: 10 });
    expect(list).toEqual([9, 1, 5, 3, 7, 10, 2, 8, 4, 6]);
    expect(summary([4])).toEqual({ n: 1, median: 4, p95: 4, max: 4 });
    expect(summary([3, 1])).toEqual({ n: 2, median: 1, p95: 3, max: 3 });
    expect(percentile(Array.from({ length: 100 }, (_, at) => at + 1), 95)).toBe(95);
  });
});

describe("the views it looks through", () => {
  const base = { evidence: "wiki", buffs: "own", roles: ["tank", "balanced"], setup: "1h-shield", races: ["OGR", "IKS"] };

  it("are each role that plays the setup, each race of the bundle and every tier 0 to 10", () => {
    const views = viewsOf(bundle, base);
    expect(views).toHaveLength(2 * 2 * 11);
    expect(new Set(views.map((view) => view.tier))).toEqual(new Set(Array.from({ length: 11 }, (_, tier) => tier)));
    expect(views[0]).toEqual({ scenario: { race: "OGR", role: "tank", buffs: "own", evidence: "wiki", setup: "1h-shield" }, tier: 0 });
  });

  it("leave out a role that does not play the setup, a role the trio is not offered and a race the bundle does not have", () => {
    expect(viewsOf(bundle, { ...base, roles: ["melee"] })).toEqual([]);
    expect(viewsOf(bundle, { ...base, roles: ["caster", "balanced"], races: ["OGR", "ZZZ"] })).toHaveLength(11);
  });
});

describe("a timed view", () => {
  it("has the weights it was given: a slider at x2 moves the value, and the parts of the time add up to no more than the whole", () => {
    const view = { scenario: { race: "OGR", role: "balanced", buffs: "own", evidence: "wiki", setup: "dw" }, tier: 4 };
    const own = timeView({ highs, records, bundle, view, weights: undefined, canonical: false });
    const heavier = timeView({ highs, records, bundle, view, weights: { multipliers: { AC: 2 } }, canonical: false });
    expect(heavier.F).not.toBe(own.F);
    expect(own).toMatchObject({ status: "optimal", pool: 44 });
    expect(own.poolMs + own.pruneMs + own.buildMs + own.solveMs).toBeLessThanOrEqual(own.totalMs + 1);
    expect(timeView({ highs, records, bundle, view, weights: undefined, canonical: true }).F).toBe(own.F);
  });
});

describe("the measure", () => {
  it("picks the heavy views by their time with the tie stage, and times each of them at the role's own weights and at x2 on each group, with and without the tie stage", () => {
    const views = viewsOf(bundle, { evidence: "wiki", buffs: "own", roles: ["tank", "balanced"], setup: "1h-shield", races: ["OGR", "IKS"], tiers: [0, 4, 10] });
    const lines = [];
    const found = measure({ highs, records, bundle, views, heavy: 3, groups: GROUPS, progress: (text) => lines.push(text) });
    expect(found.heavy).toHaveLength(3);
    expect(new Set(found.heavy.map((one) => one.name)).size).toBe(3);
    expect(found.heavy.map((one) => one.canonicalMs)).toEqual([...found.heavy.map((one) => one.canonicalMs)].sort((a, b) => b - a));
    expect(Object.keys(found.settings)).toEqual(["own", ...GROUPS.map((group) => `${group} x2`)]);
    for (const row of Object.values(found.settings)) {
      for (const how of ["plain", "canonical"]) {
        expect(row[how].n).toBe(3);
        expect(row[how].median).toBeLessThanOrEqual(row[how].p95);
        expect(row[how].p95).toBeLessThanOrEqual(row[how].max);
        expect(row[how].median).toBeGreaterThan(0);
      }
    }
    expect(lines.length).toBeGreaterThanOrEqual(1 + GROUPS.length);
  });
});

describe("the command", () => {
  it("prints the heavy views and the summary of every setting for the results of a folder, and writes them as JSON when asked", () => {
    const scratch = mkdtempSync(join(tmpdir(), "best-kit-bench-"));
    try {
      const json = join(scratch, "bench.json");
      const out = execFileSync(process.execPath, [SCRIPT, RESULTS, "--races", "OGR", "--roles", "balanced", "--setup", "dw", "--heavy", "2", "--json", json], { encoding: "utf8" });
      expect(out).toMatch(/the heavy views/);
      for (const label of ["own", ...GROUPS.map((group) => `${group} x2`)]) expect(out).toContain(label);
      expect(out).toMatch(/median\s+\d+\s+p95\s+\d+\s+max\s+\d+\s+\(n=2\)/);
      const written = JSON.parse(readFileSync(json, "utf8"));
      expect(written.heavy).toHaveLength(2);
      expect(Object.keys(written.settings)).toHaveLength(1 + GROUPS.length);
      expect(() => execFileSync(process.execPath, [SCRIPT, RESULTS, "--roles", "melee"], { encoding: "utf8", stdio: "pipe" })).toThrow(/no view to look through/);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  });
});

describe("the command for a heavy buff set, over all the races, with no tie stage", () => {
  // The browser's answer has no tie stage, and the buff sets that are not precomputed (group+enchanter, raid) and the group set are the heavy ones to time: every race of the bundle, the role's own
  // weights and each slider group at x2, with the plain solve alone. The command says which buff set it timed and names the slowest view of it.
  const NAME = /^pal-mnk-ber [A-Z]{3} (?:tank|balanced) \+\d+ [0-9a-z-]+ (?:strict|wiki) (?:own|group|group\+enchanter|raid)$/;
  const run = (...args) => execFileSync(process.execPath, [SCRIPT, RESULTS, ...args], { encoding: "utf8" });

  it("takes every race of the bundle for races all, and the tiers it is told", () => {
    const every = viewsOf(bundle, { evidence: "wiki", buffs: "raid", roles: ["balanced"], setup: "dw", races: bundle.races.map((row) => row.code), tiers: [0, 4] });
    expect(every).toHaveLength(bundle.races.length * 2);
    expect(new Set(every.map((view) => view.scenario.race)).size).toBe(bundle.races.length);
    expect(bundle.races.length).toBeGreaterThanOrEqual(15);
  });

  it("prints the buff set it timed, in the heading and in the JSON, times every view the roles and the races make, and names the slowest of them", () => {
    const scratch = mkdtempSync(join(tmpdir(), "best-kit-bench-"));
    try {
      const json = join(scratch, "raid.json");
      const out = run("--buffs", "raid", "--races", "all", "--tiers", "0,4", "--roles", "balanced", "--setup", "dw", "--heavy", "all", "--tie", "no", "--json", json);
      expect(out).toMatch(/^buff set: raid\b/m);
      const written = JSON.parse(readFileSync(json, "utf8"));
      expect(written).toMatchObject({ buffs: "raid", trio: "pal-mnk-ber", evidence: "wiki", races: "all" });
      const views = bundle.races.length * 2;
      expect(written.heavy).toHaveLength(views); // all of them, none left out by the time they took
      for (const [label, row] of Object.entries(written.settings)) {
        expect(row.canonical, `${label}: no tie stage`).toBeUndefined();
        expect(row.plain.n, label).toBe(views);
        expect(row.plain.median).toBeLessThanOrEqual(row.plain.p95);
        expect(row.plain.p95).toBeLessThanOrEqual(row.plain.max);
        expect(row.plain.slowest.name, label).toMatch(NAME);
        expect(row.plain.slowest.ms, label).toBe(row.plain.max);
      }
      expect(Object.keys(written.settings)).toEqual(["own", ...GROUPS.map((group) => `${group} x2`)]);
      expect(written.slowest.name).toMatch(NAME);
      expect(written.slowest.ms).toBe(Math.max(...Object.values(written.settings).map((row) => row.plain.max)));
      expect(Object.values(written.settings).map((row) => row.plain.slowest.name)).toContain(written.slowest.name);
      expect(out).not.toMatch(/with the tie stage|canonical/);
      expect(out).toContain(`the slowest view of the buff set raid: ${written.slowest.name}`);
      expect(out).toMatch(/median\s+\d+\s+p95\s+\d+\s+max\s+\d+\s+\(n=\d+\)/);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  });

  it("times a view of another buff set as that buff set: the heading and the names say group, and the value moves with the set", () => {
    const scratch = mkdtempSync(join(tmpdir(), "best-kit-bench-"));
    try {
      const json = join(scratch, "group.json");
      const out = run("--buffs", "group", "--races", "OGR", "--tiers", "4", "--roles", "balanced", "--setup", "dw", "--heavy", "all", "--tie", "no", "--json", json);
      expect(out).toMatch(/^buff set: group\b/m);
      const written = JSON.parse(readFileSync(json, "utf8"));
      expect(written.buffs).toBe("group");
      expect(written.slowest.name).toMatch(/ wiki group$/);
      expect(written.heavy).toHaveLength(1);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  });

  it("refuses a buff set the bundle does not have, and a tie option or a tier that is not one", () => {
    for (const args of [["--buffs", "everything"], ["--tie", "maybe"], ["--tiers", "11"], ["--tiers", "a"], ["--heavy", "0"], ["--heavy", "some"]]) {
      expect(() => execFileSync(process.execPath, [SCRIPT, RESULTS, "--races", "OGR", "--roles", "balanced", "--setup", "dw", ...args], { encoding: "utf8", stdio: "pipe" }), args.join(" ")).toThrow();
    }
  });
});
