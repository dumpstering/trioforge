import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { OPTIONS, PHONE_FACTOR, benchDirectory, percentile, summarize } from "../scripts/bench-highs.mjs";

// The Python side computes the same statistics (trioforge.bench.percentile); these cases are the ones its tests use.
describe("percentile and summarize", () => {
  it("interpolate between the two nearest ranks", () => {
    expect(percentile([1, 2, 3, 4], 50)).toBe(2.5);
    expect(percentile([4, 1, 3, 2], 50)).toBe(2.5);
    const hundred = Array.from({ length: 100 }, (_, i) => i + 1);
    expect(percentile(hundred, 95)).toBeCloseTo(95.05, 10);
    expect(percentile([7], 95)).toBe(7);
    expect(percentile([3, 9], 0)).toBe(3);
    expect(percentile([3, 9], 100)).toBe(9);
    expect(percentile([0, 10], 25)).toBe(2.5);
  });

  it("refuse an empty list or a q outside 0 to 100", () => {
    expect(() => percentile([], 50)).toThrow();
    expect(() => percentile([1, 2], 101)).toThrow();
  });

  it("summarize gives the count, mean, median, p95 and maximum", () => {
    const s = summarize([1, 2, 3, 4, 10]);
    expect(s.n).toBe(5);
    expect(s.mean).toBe(4);
    expect(s.p50).toBe(3);
    expect(s.p95).toBeCloseTo(8.8, 10);
    expect(s.max).toBe(10);
    expect(summarize([])).toEqual({ n: 0 });
  });
});

// maximize x + y  subject to  x + 2y <= 4,  3x + y <= 6,  x, y integer in [0, 10]  (integer optimum 2).
const TINY_MPS = `NAME          TINY
OBJSENSE
    MAX
ROWS
 N  OBJ
 L  C1
 L  C2
COLUMNS
    MARKER                 'MARKER'                 'INTORG'
    X         OBJ       1   C1        1
    X         C2        3
    Y         OBJ       1   C1        2
    Y         C2        1
    MARKER                 'MARKER'                 'INTEND'
RHS
    RHS       C1        4   C2        6
BOUNDS
 UP BND       X         10
 UP BND       Y         10
ENDATA
`;

describe("scripts/bench-highs.mjs", () => {
  it("solves an MPS model with the project options and reports timings against the expected objective", async () => {
    const dir = mkdtempSync(join(tmpdir(), "bench-highs-"));
    try {
      writeFileSync(join(dir, "01-tiny.mps"), TINY_MPS);
      writeFileSync(join(dir, "02-tiny.mps"), TINY_MPS);
      const result = await benchDirectory(dir, { reps: 2, expected: { "01-tiny.mps": 2, "02-tiny.mps": 2.5 } });
      expect(result.models).toBe(2);
      expect(result.all_optimal).toBe(true);
      expect(result.highs.version).toMatch(/^1\.15\.\d+$/);
      expect(result.per_model.map((m) => m.file)).toEqual(["01-tiny.mps", "02-tiny.mps"]);
      expect(result.per_model[0]).toMatchObject({ cols: 2, rows: 2, status: "optimal", objective: 2, rel_diff: 0 });
      expect(result.per_model[1].rel_diff).toBeCloseTo(0.5 / 2.5, 10); // the wrong expectation shows as a difference
      expect(result.max_rel_objective_diff).toBeCloseTo(0.2, 10);
      expect(result.median_ms).toBeGreaterThanOrEqual(0);
      expect(result.p95_ms).toBeGreaterThanOrEqual(result.median_ms);
      expect(result.typical_median_ms).toBeGreaterThanOrEqual(result.median_ms); // best of the repeats is the lowest
      expect(result.per_model[0].run_median_ms).toBeGreaterThanOrEqual(result.per_model[0].run_ms);
      expect(result.per_model[0].cpu_ms).toBeGreaterThanOrEqual(0);
      expect(result.phone_median_ms).toBe(PHONE_FACTOR * result.median_ms);
      expect(result.options).toEqual(OPTIONS);
      expect(OPTIONS.presolve).toBe("off");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }, 60000);

  it("refuses a directory without models", async () => {
    const dir = mkdtempSync(join(tmpdir(), "bench-highs-"));
    try {
      await expect(benchDirectory(dir)).rejects.toThrow(/no \.mps files/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
