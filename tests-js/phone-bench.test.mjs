import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { percentile } from "../scripts/bench-highs.mjs";
import {
  BUDGET_MS,
  BUNDLE_TARGET,
  CALIBRATION_FLOOR,
  COLD_START_BUDGET_MS,
  DEFAULT_OPTIONS,
  FARM_STEP_LIMIT_MS,
  FULL_POOL_LIMIT_MS,
  SMOKE_OPTIONS,
  WATCHDOG_EXTRA_MS,
  WatchdogError,
  buildSummary,
  bundlePage,
  calibrationVerdict,
  decide,
  describeVerdict,
  formatDecision,
  formatReport,
  parseArgs,
  pickSpread,
  summarize,
  watchdogLimit,
  withTimeout,
} from "../scripts/phone-bench.mjs";
import { CALIBRATION_OBJECTIVE, coldStart, createRunner, jsLoop, smallSolve, workload } from "../scripts/phone-bench-page.mjs";
import { SAMPLE } from "./engine-fixtures.mjs";

// The phone gate (scripts/phone-bench.mjs) measures the browser engine in Chromium under CPU throttling; the measuring itself is for a quiet machine and is
// not run here. What is held here: the numbers it reports (the summary), the choice of cases, the verdict on the throttle, the decision, the command
// line, and the page's own measuring functions (scripts/phone-bench-page.mjs), run in Node on the committed sample fixtures, whose answers are the ones
// Python recorded (so a case that is set up wrongly shows).

const HERE = dirname(fileURLToPath(import.meta.url));
const WASM_FILE = resolve(HERE, "../node_modules/highs/build/highs.wasm");

const names = (prefix, count) => Array.from({ length: count }, (_, at) => `${prefix}-${String(at + 1).padStart(3, "0")}`);
const stat = (p95) => ({ n: 10, median: p95 / 2, p95, max: p95 * 2 });

// ---- the summary ---------------------------------------------------------------------------------------------------------------------

describe("summarize", () => {
  it("gives the count, the median, the 95th percentile and the maximum, as bench-highs reads a percentile", () => {
    expect(summarize([5, 1, 3])).toEqual({ n: 3, median: 3, p95: percentile([1, 3, 5], 95), max: 5 });
    expect(summarize([5, 1, 3]).p95).toBeCloseTo(4.8, 10);
    const forty = Array.from({ length: 40 }, (_, at) => at + 1);
    const s = summarize(forty);
    expect(s.n).toBe(40);
    expect(s.median).toBe(20.5);
    expect(s.p95).toBeCloseTo(38.05, 10); // between the 38th and the 39th value, at the 0.05 of the way
    expect(s.max).toBe(40);
  });

  it("does not depend on the order of the values, and does not change the list", () => {
    const values = [9, 2, 7, 4, 1];
    const copy = [...values];
    expect(summarize(values)).toEqual(summarize([...values].reverse()));
    expect(values).toEqual(copy);
  });

  it("is the value itself for one value", () => {
    expect(summarize([7.5])).toEqual({ n: 1, median: 7.5, p95: 7.5, max: 7.5 });
  });

  it("refuses an empty list, and anything that is not a list of finite numbers", () => {
    expect(() => summarize([])).toThrow(/at least one/);
    expect(() => summarize(undefined)).toThrow();
    expect(() => summarize("12")).toThrow();
    expect(() => summarize([1, Number.NaN])).toThrow(/finite/);
    expect(() => summarize([1, Number.POSITIVE_INFINITY])).toThrow(/finite/);
    expect(() => summarize([1, "2"])).toThrow(/finite/);
    expect(() => summarize([1, null])).toThrow(/finite/);
  });
});

// ---- the choice of cases -------------------------------------------------------------------------------------------------------------

describe("pickSpread", () => {
  it("picks the number asked for, in the order of the names, whatever the order they came in", () => {
    const matrix = names("matrix", 96);
    const picked = pickSpread(matrix, 40);
    expect(picked).toHaveLength(40);
    expect(new Set(picked).size).toBe(40);
    expect(picked).toEqual([...picked].sort());
    expect(pickSpread([...matrix].reverse(), 40)).toEqual(picked);
    const shuffled = matrix.map((name, at) => [(at * 37) % 96, name]).sort((a, b) => a[0] - b[0]).map(([, name]) => name);
    expect(pickSpread(shuffled, 40)).toEqual(picked);
  });

  it("spreads them evenly: the gaps differ by one at most, and the first and last picks are within one gap of the two ends", () => {
    const matrix = names("matrix", 96);
    for (const count of [1, 2, 3, 10, 40, 95]) {
      const at = pickSpread(matrix, count).map((name) => matrix.indexOf(name));
      const gaps = at.slice(1).map((place, k) => place - at[k]);
      if (gaps.length > 0) expect(Math.max(...gaps) - Math.min(...gaps), `${count}: ${gaps}`).toBeLessThanOrEqual(1);
      expect(at[0] - 0, `${count}: the first pick`).toBeLessThanOrEqual(Math.ceil(96 / count));
      expect(95 - at[at.length - 1], `${count}: the last pick`).toBeLessThanOrEqual(Math.ceil(96 / count));
    }
  });

  it("gives the cases that the real runs go through (40 of 96, 10 of 19, and the two of the smoke run)", () => {
    const matrix = names("matrix", 96);
    const picked = pickSpread(matrix, 40);
    expect(picked[0]).toBe("matrix-002");
    expect(picked[1]).toBe("matrix-004");
    expect(picked[39]).toBe("matrix-095");
    expect(pickSpread(matrix, 2)).toEqual(["matrix-025", "matrix-073"]);
    const upgrade = [...names("upgrade", 16), "upgrade-slots-softcap", "upgrade-slots-twohand-2h", "upgrade-slots-twohand"];
    expect(upgrade).toHaveLength(19);
    const ten = pickSpread(upgrade, 10);
    expect(ten).toEqual([
      "upgrade-001", "upgrade-003", "upgrade-005", "upgrade-007", "upgrade-009", "upgrade-011", "upgrade-013", "upgrade-015",
      "upgrade-slots-softcap", "upgrade-slots-twohand-2h",
    ]);
    expect(pickSpread(upgrade, 1)).toEqual(["upgrade-010"]);
  });

  it("sorts by name as the code units of the text go (a name that is the start of another comes first)", () => {
    const list = ["upgrade-slots-twohand-2h", "upgrade-slots-twohand", "upgrade-010", "upgrade-001"];
    expect(pickSpread(list, 4)).toEqual(["upgrade-001", "upgrade-010", "upgrade-slots-twohand", "upgrade-slots-twohand-2h"]);
    expect(pickSpread(["b", "a", "c"], 2)).toEqual(["a", "c"]);
  });

  it("gives every case when it is asked for as many as there are, or more", () => {
    const upgrade = names("upgrade", 19);
    expect(pickSpread(upgrade, 19)).toEqual(upgrade);
    expect(pickSpread(upgrade, 20)).toEqual(upgrade);
    expect(pickSpread([...upgrade].reverse(), 1000)).toEqual(upgrade);
    expect(pickSpread(["only"], 5)).toEqual(["only"]);
    expect(pickSpread([], 3)).toEqual([]);
  });

  it("does not change the list it is given, and refuses a count that is not a whole number from 1", () => {
    const list = ["c", "a", "b"];
    pickSpread(list, 2);
    expect(list).toEqual(["c", "a", "b"]);
    for (const count of [0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY, "3", undefined, null]) {
      expect(() => pickSpread(list, count), String(count)).toThrow(/whole number/);
    }
  });
});

// ---- the throttle -----------------------------------------------------------------------------------------------------------------------

describe("calibrationVerdict", () => {
  it("takes a ratio of 0.6 times the rate or more for a throttle that works, and one below for a throttle that does not", () => {
    expect(CALIBRATION_FLOOR).toBe(0.6);
    // rate 6: the line is 3.6
    expect(calibrationVerdict({ rate: 6, loopRatio: 3.6, solveRatio: 3.6 })).toMatchObject({ effective: true, floor: 3.6, failed: [] });
    expect(calibrationVerdict({ rate: 6, loopRatio: 6.78, solveRatio: 5.2 }).effective).toBe(true);
    expect(calibrationVerdict({ rate: 6, loopRatio: 3.59, solveRatio: 6 })).toMatchObject({ effective: false, failed: ["loop"] });
    expect(calibrationVerdict({ rate: 6, loopRatio: 6, solveRatio: 3.5999 })).toMatchObject({ effective: false, failed: ["solve"] });
    expect(calibrationVerdict({ rate: 6, loopRatio: 1.02, solveRatio: 1.01 })).toMatchObject({ effective: false, failed: ["loop", "solve"] });
  });

  it("scales the line with the rate, and at rate 1 asks only that the second run was not much faster than the first", () => {
    expect(calibrationVerdict({ rate: 4, loopRatio: 2.4, solveRatio: 2.4 })).toMatchObject({ effective: true, floor: 2.4 });
    expect(calibrationVerdict({ rate: 4, loopRatio: 2.39, solveRatio: 4 }).effective).toBe(false);
    expect(calibrationVerdict({ rate: 12, loopRatio: 7.2, solveRatio: 7.2 })).toMatchObject({ effective: true, floor: 7.2 });
    expect(calibrationVerdict({ rate: 1, loopRatio: 1, solveRatio: 1.02 }).effective).toBe(true);
    expect(calibrationVerdict({ rate: 1, loopRatio: 0.6, solveRatio: 0.6 })).toMatchObject({ effective: true, floor: 0.6 });
    expect(calibrationVerdict({ rate: 1, loopRatio: 0.59, solveRatio: 1 }).effective).toBe(false);
  });

  it("says what it was given", () => {
    expect(calibrationVerdict({ rate: 6, loopRatio: 5, solveRatio: 4 })).toEqual({ effective: true, rate: 6, floor: 3.6, loopRatio: 5, solveRatio: 4, failed: [] });
  });

  it("refuses a rate below 1 and a ratio that is not a positive number", () => {
    for (const rate of [0.5, 0, -2, Number.NaN, Number.POSITIVE_INFINITY, "6", undefined]) {
      expect(() => calibrationVerdict({ rate, loopRatio: 5, solveRatio: 5 }), String(rate)).toThrow(/rate/);
    }
    for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY, "5", undefined, null]) {
      expect(() => calibrationVerdict({ rate: 6, loopRatio: bad, solveRatio: 5 }), `loop ${bad}`).toThrow(/ratio/);
      expect(() => calibrationVerdict({ rate: 6, loopRatio: 5, solveRatio: bad }), `solve ${bad}`).toThrow(/ratio/);
    }
  });
});

describe("describeVerdict", () => {
  it("says which ratios fell short, and the line they had to reach", () => {
    const text = describeVerdict(calibrationVerdict({ rate: 6, loopRatio: 1.02, solveRatio: 5.5 }));
    expect(text).toMatch(/not effective at rate 6/);
    expect(text).toContain("JS loop ran x1.02");
    expect(text).not.toContain("highs solve ran");
    expect(text).toContain("x3.60");
    expect(text).toMatch(/Nothing was measured/);
    expect(describeVerdict(calibrationVerdict({ rate: 4, loopRatio: 1, solveRatio: 1.1 }))).toMatch(
      /JS loop ran x1\.00 slower and the highs solve ran x1\.10 slower/,
    );
  });
});

// ---- the watchdog -----------------------------------------------------------------------------------------------------------------------

describe("the watchdog", () => {
  it("allows a case twice its budget and a minute", () => {
    expect(WATCHDOG_EXTRA_MS).toBe(60_000);
    expect(watchdogLimit(600_000)).toBe(1_260_000);
    expect(watchdogLimit(BUDGET_MS)).toBe(2 * BUDGET_MS + 60_000);
    expect(watchdogLimit(0)).toBe(60_000);
    expect(watchdogLimit(COLD_START_BUDGET_MS)).toBe(2 * COLD_START_BUDGET_MS + 60_000);
    for (const bad of [-1, Number.NaN, Number.POSITIVE_INFINITY, "600000", undefined]) expect(() => watchdogLimit(bad), String(bad)).toThrow(/budget/);
  });

  it("gives the value of a promise that settles in time, and its own error if it fails in time", async () => {
    await expect(withTimeout(Promise.resolve(42), 1000, "case a")).resolves.toBe(42);
    await expect(withTimeout(new Promise((resolve) => setTimeout(() => resolve("a little late"), 5)), 1000, "case a")).resolves.toBe("a little late");
    const failure = new Error("boom");
    await expect(withTimeout(Promise.reject(failure), 1000, "case a")).rejects.toBe(failure);
  });

  it("ends the wait with a WatchdogError that names what hung and the limit, when the promise does not settle in time", async () => {
    const error = await withTimeout(new Promise(() => {}), 20, "matrix case matrix-025").catch((caught) => caught);
    expect(error).toBeInstanceOf(WatchdogError);
    expect(error.what).toBe("matrix case matrix-025");
    expect(error.limitMs).toBe(20);
    expect(error.message).toMatch(/^matrix case matrix-025 did not return within /);
    expect(new WatchdogError("upgrade case upgrade-010", 1_260_000).message).toBe(
      "upgrade case upgrade-010 did not return within 1260 s (twice its budget and a minute)",
    );
  });

  it("leaves no timer running, whether the promise settled or the wait was given up", async () => {
    vi.useFakeTimers();
    try {
      await expect(withTimeout(Promise.resolve("done"), 1000, "case")).resolves.toBe("done");
      expect(vi.getTimerCount()).toBe(0);
      await expect(withTimeout(Promise.reject(new Error("failed")), 1000, "case")).rejects.toThrow("failed");
      expect(vi.getTimerCount()).toBe(0);
      const hung = expect(withTimeout(new Promise(() => {}), 1000, "case")).rejects.toBeInstanceOf(WatchdogError);
      expect(vi.getTimerCount()).toBe(1);
      await vi.advanceTimersByTimeAsync(999);
      expect(vi.getTimerCount()).toBe(1); // not yet
      await vi.advanceTimersByTimeAsync(1);
      await hung;
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not turn a failure that comes after the wait was given up into an unhandled rejection", async () => {
    let failLate;
    const late = new Promise((_, reject) => {
      failLate = reject;
    });
    await expect(withTimeout(late, 10, "case")).rejects.toBeInstanceOf(WatchdogError);
    failLate(new Error("too late"));
    await new Promise((resolve) => setTimeout(resolve, 30)); // (the test run reports an unhandled rejection as an error)
  });

  it("refuses a limit that is not a positive number of milliseconds", () => {
    for (const bad of [0, -5, Number.NaN, Number.POSITIVE_INFINITY, "10", undefined]) expect(() => withTimeout(Promise.resolve(1), bad, "case"), String(bad)).toThrow(/limit/);
  });
});

// ---- the decision -----------------------------------------------------------------------------------------------------------------------

describe("decide", () => {
  const summary = (farmStep, fullPoolTotal) => ({ farmStep: stat(farmStep), fullPool: { total: stat(fullPoolTotal) } });

  it("has the two limits the gate is judged by", () => {
    expect(FARM_STEP_LIMIT_MS).toBe(8000);
    expect(FULL_POOL_LIMIT_MS).toBe(10000);
  });

  it("streams the farm path when the 95th percentile of one farm step is 8000 ms or less, and asks for each step after the first otherwise", () => {
    expect(decide(summary(8000, 0)).farmPath).toBe("streaming"); // at the limit
    expect(decide(summary(7999.999, 0)).farmPath).toBe("streaming");
    expect(decide(summary(0, 0)).farmPath).toBe("streaming");
    expect(decide(summary(8000.001, 0)).farmPath).toBe("on-request"); // just above
    expect(decide(summary(8001, 0)).farmPath).toBe("on-request");
    expect(decide(summary(60000, 0)).farmPath).toBe("on-request");
  });

  it("snaps the reweight sliders only when the 95th percentile of a full-pool solve's total is above 10000 ms", () => {
    expect(decide(summary(0, 10000)).sliders).toBe("free"); // at the limit: not above it
    expect(decide(summary(0, 9999.999)).sliders).toBe("free");
    expect(decide(summary(0, 0)).sliders).toBe("free");
    expect(decide(summary(0, 10000.001)).sliders).toBe("snap"); // just above
    expect(decide(summary(0, 10001)).sliders).toBe("snap");
    expect(decide(summary(0, 120000)).sliders).toBe("snap");
  });

  it("decides the two separately", () => {
    expect(decide(summary(9000, 5000))).toMatchObject({ farmPath: "on-request", sliders: "free" });
    expect(decide(summary(5000, 11000))).toMatchObject({ farmPath: "streaming", sliders: "snap" });
    expect(decide(summary(9000, 11000))).toMatchObject({ farmPath: "on-request", sliders: "snap" });
    expect(decide(summary(5000, 5000))).toMatchObject({ farmPath: "streaming", sliders: "free" });
  });

  it("carries the numbers it rests on, and the limits", () => {
    expect(decide(summary(6123.4, 10555.5))).toEqual({
      farmPath: "streaming",
      sliders: "snap",
      farmStepP95Ms: 6123.4,
      farmStepLimitMs: 8000,
      fullPoolP95Ms: 10555.5,
      fullPoolLimitMs: 10000,
    });
  });

  it("reads the 95th percentile, not the median or the maximum", () => {
    const only = { farmStep: { n: 5, median: 100, p95: 9000, max: 1 }, fullPool: { total: { n: 5, median: 100, p95: 11000, max: 1 } } };
    expect(decide(only)).toMatchObject({ farmPath: "on-request", sliders: "snap" });
    const low = { farmStep: { n: 5, median: 99999, p95: 10, max: 99999 }, fullPool: { total: { n: 5, median: 99999, p95: 10, max: 99999 } } };
    expect(decide(low)).toMatchObject({ farmPath: "streaming", sliders: "free" });
  });

  it("refuses a summary that lacks a number it rests on", () => {
    expect(() => decide({})).toThrow(/farm step/);
    expect(() => decide(null)).toThrow();
    expect(() => decide({ farmStep: stat(1000) })).toThrow(/full-pool/);
    expect(() => decide({ fullPool: { total: stat(1000) } })).toThrow(/farm step/);
    expect(() => decide({ farmStep: { n: 0 }, fullPool: { total: stat(1000) } })).toThrow(/farm step/);
    expect(() => decide({ farmStep: stat(Number.NaN), fullPool: { total: stat(1000) } })).toThrow(/farm step/);
    expect(() => decide({ farmStep: stat(1000), fullPool: { total: { n: 1, p95: Number.POSITIVE_INFINITY } } })).toThrow(/full-pool/);
    expect(() => decide({ farmStep: stat("8000"), fullPool: { total: stat(1000) } })).toThrow(/farm step/);
  });

  it("prints the decision with the numbers it rests on", () => {
    const streaming = formatDecision(decide(summary(6123.4, 7000))).join("\n");
    expect(streaming).toMatch(/streaming/);
    expect(streaming).toContain("6123");
    expect(streaming).toContain("8000");
    expect(streaming).toContain("7000");
    expect(streaming).toContain("10000");
    expect(streaming).toMatch(/Stop/);
    const onRequest = formatDecision(decide(summary(9000, 12000))).join("\n");
    expect(onRequest).toMatch(/on-request/);
    expect(onRequest).toContain("Next step");
    expect(onRequest).toContain("9000");
    expect(onRequest).toContain("12000");
    expect(onRequest).toMatch(/snap/i);
    expect(onRequest).toMatch(/progress bar/);
  });

  it("prints the 95th percentile with one decimal place, so that it never reads as the limit when it is on the other side of it", () => {
    const text = (farmStep, fullPoolTotal) => formatDecision(decide(summary(farmStep, fullPoolTotal))).join("\n");
    expect(text(8000.4, 0)).toContain("is 8000.4 ms, above 8000 ms");
    expect(text(8000, 0)).toContain("is 8000.0 ms, at most 8000 ms");
    expect(text(7999.5, 0)).toContain("is 7999.5 ms, at most 8000 ms");
    expect(text(0, 10000.4)).toContain("is 10000.4 ms, above 10000 ms");
    expect(text(0, 10000)).toContain("is 10000.0 ms, at most 10000 ms");
    expect(text(0, 9999.5)).toContain("is 9999.5 ms, at most 10000 ms");
    expect(text(6123.4, 0)).toContain("is 6123.4 ms");
    // so near a limit that one decimal rounds onto it: the digits that tell the two apart are printed
    expect(text(8000.04, 0)).toContain("is 8000.04 ms, above 8000 ms");
    expect(text(7999.96, 0)).toContain("is 7999.96 ms, at most 8000 ms");
    expect(text(0, 10000.004)).toContain("is 10000.004 ms, above 10000 ms");
    expect(text(0, 9999.996)).toContain("is 9999.996 ms, at most 10000 ms");
  });
});

// ---- the command line -------------------------------------------------------------------------------------------------------------------

describe("parseArgs", () => {
  it("has the defaults: throttle 6, port 8799, 40 matrix cases, 10 upgrade cases, 8 steps", () => {
    expect(parseArgs([])).toEqual({ throttle: 6, port: 8799, matrix: 40, upgrade: 10, steps: 8, json: null, smoke: false, help: false });
    expect(parseArgs([])).toMatchObject(DEFAULT_OPTIONS);
  });

  it("takes the options of the brief", () => {
    expect(parseArgs(["--throttle", "4", "--port", "9100", "--matrix", "12", "--upgrade", "3", "--json", "out/bench.json"])).toEqual({
      throttle: 4,
      port: 9100,
      matrix: 12,
      upgrade: 3,
      steps: 8,
      json: "out/bench.json",
      smoke: false,
      help: false,
    });
    expect(parseArgs(["--throttle", "2.5"]).throttle).toBe(2.5);
    expect(parseArgs(["--port", "0"]).port).toBe(0);
    expect(parseArgs(["-h"]).help).toBe(true);
    expect(parseArgs(["--help"]).help).toBe(true);
  });

  it("means 2 matrix cases, 1 upgrade case with 2 steps and throttle 1 by --smoke, and lets an option given beside it win", () => {
    expect(SMOKE_OPTIONS).toEqual({ throttle: 1, matrix: 2, upgrade: 1, steps: 2 });
    expect(parseArgs(["--smoke"])).toEqual({ throttle: 1, port: 8799, matrix: 2, upgrade: 1, steps: 2, json: null, smoke: true, help: false });
    expect(parseArgs(["--smoke", "--throttle", "6"])).toMatchObject({ throttle: 6, matrix: 2, upgrade: 1, steps: 2, smoke: true });
    expect(parseArgs(["--matrix", "5", "--smoke"])).toMatchObject({ throttle: 1, matrix: 5, upgrade: 1, steps: 2 });
  });

  it("refuses what it does not understand", () => {
    for (const bad of [
      ["--throttle"],
      ["--throttle", "0.5"],
      ["--throttle", "fast"],
      ["--throttle", "Infinity"],
      ["--port", "70000"],
      ["--port", "-1"],
      ["--port", "88.5"],
      ["--matrix", "0"],
      ["--matrix", "1.5"],
      ["--matrix", "--smoke"],
      ["--upgrade", "-3"],
      ["--upgrade"],
      ["--json"],
      ["--json", ""],
      ["--steps", "3"],
      ["--bogus"],
      ["somewhere"],
    ]) {
      expect(() => parseArgs(bad), bad.join(" ")).toThrow();
    }
  });
});

// ---- the summary of a run ---------------------------------------------------------------------------------------------------------------

const matrixCase = (name, ms, extra = {}) => ({
  name,
  pruneInput: "recorded",
  pruneMs: ms.prune,
  buildMs: ms.build,
  solveMs: ms.solve,
  totalMs: ms.prune + ms.build + ms.solve,
  status: "optimal",
  fOk: true,
  ...extra,
});
const stepOf = (index, ownMs, extra = {}) => ({ index, found: true, status: "optimal", ownMs, ...extra });
const upgradeCase = (name, equipMs, pathMs, steps, stopped = "limit", extra = {}) => ({
  name,
  equipMs,
  pathMs,
  stopped,
  stepsFound: steps.filter((step) => step.found).length,
  steps,
  proofMs: null,
  equipFOk: true,
  stepsOk: true,
  ...extra,
});

describe("buildSummary", () => {
  const measured = () => ({
    coldStarts: [
      { version: "1.15.1", compileMs: 100, startMs: 300, totalMs: 400, firstSolveMs: 900 },
      { version: "1.15.1", compileMs: 110, startMs: 310, totalMs: 420, firstSolveMs: 950 },
      { version: "1.15.1", compileMs: 90, startMs: 290, totalMs: 380, firstSolveMs: 850 },
    ],
    matrix: [
      matrixCase("matrix/a", { prune: 10, build: 20, solve: 100 }),
      matrixCase("matrix/b", { prune: 30, build: 40, solve: 200 }, { pruneInput: "pool" }),
      matrixCase("matrix/c", { prune: 20, build: 30, solve: 300 }),
    ],
    upgrade: [
      // a path that ends at the steps asked for; one that ends by itself, with a solve that proved no step was left (70 ms); one that ends by itself with no
      // solve at all (no candidate was left to add)
      upgradeCase("upgrade/a", 50, 900, [stepOf(1, 100), stepOf(2, 300), stepOf(3, 200)], "limit", { tailMs: 5 }),
      upgradeCase("upgrade/b", 70, 500, [stepOf(1, 400), stepOf(2, 50)], "no-gain", { tailMs: 70, proofMs: 70 }),
      upgradeCase("upgrade/c", 10, 20, [], "no-gain", { tailMs: 20 }),
    ],
  });

  it("takes the median, the 95th percentile and the maximum of each part of a full-pool solve and of its total", () => {
    const { fullPool } = buildSummary(measured());
    expect(fullPool.cases).toBe(3);
    expect(fullPool.prune).toEqual(summarize([10, 30, 20]));
    expect(fullPool.build).toEqual(summarize([20, 40, 30]));
    expect(fullPool.solve).toEqual(summarize([100, 200, 300]));
    expect(fullPool.total).toEqual(summarize([130, 270, 350]));
    expect(fullPool.total.max).toBe(350);
    expect(fullPool.recordedInputs).toBe(2);
    expect(fullPool.notProven).toBe(0);
    expect(fullPool.mismatches).toBe(0);
  });

  it("makes the distribution of one farm step from every Best-1 solve a user waits for: every step, and the solve that proved no step was left", () => {
    const summary = buildSummary(measured());
    expect(summary.farmStep).toEqual(summarize([100, 300, 200, 400, 50, 70])); // five steps found, and the proof of path b
    expect(summary.farmStep.n).toBe(6);
    expect(summary.farmStepSamples).toEqual({ found: 5, notFound: 0, proofs: 1 });
    expect(summary.firstStep).toEqual(summarize([100, 400])); // step 1 of the paths that have one, as before
    expect(summary.upgrade.cases).toBe(3);
    expect(summary.upgrade.equipNow).toEqual(summarize([50, 70, 10]));
    expect(summary.upgrade.path).toEqual(summarize([900, 500, 20]));
    expect(summary.upgrade.stepsFound).toEqual(summarize([3, 2, 0]));
    expect(summary.upgrade.stopped).toEqual({ limit: 1, "no-gain": 2, time: 0 });
  });

  it("counts a step that was not found as a solve the user waited for too, and leaves a case that failed out", () => {
    const run = measured();
    run.upgrade[0].steps.push({ index: 4, found: false, status: "time_limit", ownMs: 600000 });
    run.upgrade.push({ name: "upgrade/d", error: "boom" });
    run.matrix.push({ name: "matrix/d", error: "boom" });
    const summary = buildSummary(run);
    expect(summary.farmStep.n).toBe(7);
    expect(summary.farmStep.max).toBe(600000);
    expect(summary.farmStepSamples).toEqual({ found: 5, notFound: 1, proofs: 1 });
    expect(summary.firstStep).toEqual(summarize([100, 400])); // (a step 1 that was not found would not be in it either)
    expect(summary.fullPool.cases).toBe(3);
    expect(summary.fullPool.failed).toBe(1);
    expect(summary.upgrade.cases).toBe(3);
    expect(summary.upgrade.failed).toBe(1);
  });

  it("counts what a path did after its last step as a sample only if the path ended by itself and a solve proved it", () => {
    const run = measured();
    run.upgrade[0].proofMs = 999; // ended at the steps asked for: what is left over is bookkeeping, not a solve
    run.upgrade[2].proofMs = undefined; // ended by itself, but no solve ran: no candidate was left to add
    let summary = buildSummary(run);
    expect(summary.farmStepSamples.proofs).toBe(1);
    expect(summary.farmStep.max).toBe(400);
    run.upgrade[2].proofMs = 12; // and this one was proved by a solve
    summary = buildSummary(run);
    expect(summary.farmStepSamples).toEqual({ found: 5, notFound: 0, proofs: 2 });
    expect(summary.farmStep).toEqual(summarize([100, 300, 200, 400, 50, 70, 12]));
    run.upgrade[1].stopped = "time"; // a path the budget ended is no proof either
    expect(buildSummary(run).farmStepSamples.proofs).toBe(1);
  });

  it("has a distribution of one farm step from the proof alone when a path found no step but proved there is none", () => {
    const run = measured();
    run.upgrade = [upgradeCase("upgrade/c", 10, 90, [], "no-gain", { proofMs: 80 })];
    const summary = buildSummary(run);
    expect(summary.farmStep).toEqual(summarize([80]));
    expect(summary.farmStepSamples).toEqual({ found: 0, notFound: 0, proofs: 1 });
    expect(summary.firstStep).toBeNull();
  });

  it("counts the solves that ended without a proof and the answers that are not Python's", () => {
    const run = measured();
    run.matrix[1].status = "time_limit";
    run.matrix[2].fOk = false;
    run.upgrade[2].stepsOk = false; // a step of the path that is not Python's
    let summary = buildSummary(run);
    expect(summary.fullPool.notProven).toBe(1);
    expect(summary.fullPool.mismatches).toBe(1);
    expect(summary.upgrade.mismatches).toBe(1);
    run.upgrade[1].equipFOk = false;
    expect(buildSummary(run).upgrade.mismatches).toBe(2);
    run.upgrade[0].hasteOk = false;
    expect(buildSummary(run).upgrade.mismatches).toBe(3);
    run.upgrade[0].step1FOk = false; // (the old check of step 1 alone is not read any more)
    run.upgrade[2].stepsOk = true;
    summary = buildSummary(run);
    expect(summary.upgrade.mismatches).toBe(2);
  });

  it("takes the three parts of the cold start, and the first solve after it", () => {
    const { coldStart: cold } = buildSummary(measured());
    expect(cold.compile).toEqual(summarize([100, 110, 90]));
    expect(cold.start).toEqual(summarize([300, 310, 290]));
    expect(cold.total).toEqual(summarize([400, 420, 380]));
    expect(cold.firstSolve).toEqual(summarize([900, 950, 850]));
  });

  it("feeds decide: the numbers it rests on are the ones in the summary", () => {
    const decision = decide(buildSummary(measured()));
    expect(decision.farmStepP95Ms).toBe(summarize([100, 300, 200, 400, 50, 70]).p95);
    expect(decision.fullPoolP95Ms).toBe(summarize([130, 270, 350]).p95);
    expect(decision.farmPath).toBe("streaming");
    expect(decision.sliders).toBe("free");
  });

  it("refuses a run in which nothing was measured for a part", () => {
    const noSteps = measured();
    noSteps.upgrade = [upgradeCase("upgrade/c", 10, 20, [], "no-gain")]; // no step, and no solve after it either
    expect(() => buildSummary(noSteps)).toThrow(/farm step/);
    expect(() => buildSummary({ ...measured(), matrix: [] })).toThrow(/matrix/);
    expect(() => buildSummary({ ...measured(), matrix: [{ name: "matrix/d", error: "boom" }] })).toThrow(/matrix/);
    expect(() => buildSummary({ ...measured(), coldStarts: [] })).toThrow(/cold start/);
  });
});

describe("formatReport", () => {
  const report = () => {
    const run = {
      coldStarts: [{ version: "1.15.1", compileMs: 4, startMs: 10.5, totalMs: 14.5, firstSolveMs: 300 }],
      matrix: [matrixCase("matrix/matrix-001.json", { prune: 10, build: 20, solve: 100 }), matrixCase("matrix/matrix-002.json", { prune: 30, build: 40, solve: 2000 })],
      upgrade: [upgradeCase("upgrade/upgrade-001.json", 50, 900, [stepOf(1, 100), stepOf(2, 300)], "limit")],
    };
    const summary = buildSummary(run);
    return {
      environment: { browser: "Chromium 1", platform: "win32 x64", node: "v24", highs: "1.15.3", highsLibrary: "1.15.1", fixtures: { release: "data-x", seed: 7 } },
      options: { ...DEFAULT_OPTIONS },
      plan: { matrix: ["a", "b"], upgrade: ["c"], matrixAll: 96, upgradeAll: 19 },
      calibration: { rate: 6, loopRatio: 6.7, solveRatio: 9.6, workerRatio: 1, floor: 3.6 },
      summary,
      decision: decide(summary),
    };
  };

  it("has a line for each distribution, the calibration and the decision, and no number that is missing", () => {
    const text = formatReport(report()).join("\n");
    for (const part of [
      "cold start: compile",
      "cold start: instantiate + init",
      "cold start: total",
      "first small solve",
      "full pool: prune",
      "full pool: build (setScenario)",
      "full pool: solve",
      "full pool: total",
      "upgrade: Equip now",
      "upgrade: whole farm path",
      "upgrade: one farm step (every Best-1 solve)",
      "upgrade: farm step 1",
      "one farm step: 2 samples (found steps 2, steps not found 0, proofs of no step 0)",
      "calibration (rate 1 -> 6): JS loop x6.70, highs solve x9.60",
      "dedicated worker loop x1.00",
      "2 of 96 matrix cases, 1 of 19 upgrade cases",
      "decision",
      "farm path: streaming",
      "reweight sliders: free",
    ]) {
      expect(text, part).toContain(part);
    }
    expect(text).not.toMatch(/NaN|undefined|null|Infinity/);
    expect(text).not.toContain("WARNING");
  });

  it("says how many of the samples of one farm step are steps that were not found and proofs that no step is left", () => {
    const run = {
      coldStarts: [{ version: "1.15.1", compileMs: 4, startMs: 10.5, totalMs: 14.5, firstSolveMs: 300 }],
      matrix: [matrixCase("matrix/matrix-001.json", { prune: 10, build: 20, solve: 100 })],
      upgrade: [
        upgradeCase("upgrade/upgrade-001.json", 50, 900, [stepOf(1, 100), stepOf(2, 300), { index: 3, found: false, status: "time_limit", ownMs: 700 }], "time"),
        upgradeCase("upgrade/upgrade-002.json", 50, 400, [stepOf(1, 100)], "no-gain", { proofMs: 60 }),
      ],
    };
    const summary = buildSummary(run);
    const text = formatReport({ ...report(), summary, decision: decide(summary) }).join("\n");
    expect(text).toContain("one farm step: 5 samples (found steps 3, steps not found 1, proofs of no step 1)");
  });

  it("warns of a case that failed, a value that is not Python's and a solve without a proof", () => {
    const run = report();
    run.summary.fullPool.failed = 1;
    run.summary.fullPool.mismatches = 2;
    run.summary.upgrade.notProven = 3;
    expect(formatReport(run).join("\n")).toMatch(/WARNING: 1 case\(s\) failed; 2 case\(s\) did not end in the value Python recorded; 3 case\(s\) ran out of time/);
  });

  it("says that a smoke run is not a measurement", () => {
    expect(formatReport(report()).join("\n")).not.toContain("SMOKE RUN");
    const smoke = { ...report(), options: { ...DEFAULT_OPTIONS, ...SMOKE_OPTIONS, smoke: true } };
    expect(formatReport(smoke).join("\n")).toMatch(/SMOKE RUN: a check that everything works, not a measurement/);
  });

  it("says when the worker was not timed", () => {
    const run = report();
    run.calibration.workerRatio = null;
    expect(formatReport(run).join("\n")).toContain("dedicated worker loop not run");
  });
});

describe("the bundle of the page", () => {
  it("is made by esbuild for ES2021 and Safari 15, with the solver's loader in it and no import of a file left", async () => {
    expect(BUNDLE_TARGET).toEqual(["es2021", "safari15"]);
    const directory = mkdtempSync(join(tmpdir(), "phone-bench-test-"));
    try {
      const text = (await bundlePage(directory)).toString("utf8");
      expect(text.length).toBeGreaterThan(100_000);
      expect(text).toContain("phoneBench");
      expect(text).toContain("instantiateWasm");
      expect(text).not.toMatch(/from\s*["']\.{1,2}\//);
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  }, 60_000);
});

// ---- the page's measuring, in Node, on the committed sample --------------------------------------------------------------------------------

describe("the page's measuring functions", () => {
  let highs;
  let runner;
  beforeAll(async () => {
    highs = await loadHighs();
    runner = await createRunner({ highs, read: async (path) => SAMPLE.read(path), bundlePaths: SAMPLE.paths("bundle"), profilesPath: "evaluate/profiles.json" });
  }, 60_000);

  const finite = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0;

  it("times a matrix case from a recorded pruning in three parts, and gets the value that Python recorded", async () => {
    const path = SAMPLE.paths("case", "matrix/").find((candidate) => SAMPLE.read(candidate).solves[0].prune !== null);
    expect(path, "the sample has a matrix case that records its pruning").toBeTruthy();
    const doc = SAMPLE.read(path);
    const got = await runner.matrixCase(path, { budgetMs: 120_000 });
    expect(got.name).toBe(path);
    expect(got.pruneInput).toBe("recorded");
    expect(got.inputItems).toBe(doc.solves[0].prune.input.length);
    expect(got.keptItems).toBe(doc.solves[0].pool.length); // the pool that Python's solve was given
    expect(got.status).toBe("optimal");
    expect(got.proven).toBe(true);
    expect(got.fOk, `${path}: F ${got.F} against ${doc.solves[0].result.F}`).toBe(true);
    for (const key of ["pruneMs", "buildMs", "builderMs", "syncMs", "solveMs", "totalMs"]) expect(finite(got[key]), key).toBe(true);
    expect(got.totalMs).toBeCloseTo(got.pruneMs + got.buildMs + got.solveMs, 6);
    expect(got.tieMs, "placement only: the tie stage does not run").toBe(0);
    expect(got.buildMs).toBeGreaterThanOrEqual(got.builderMs);
    expect(got.columns).toBe(doc.solves[0].model.col_names.length);
  }, 180_000);

  it("prunes the pool itself for a case that records no pruning, and says so", async () => {
    const path = SAMPLE.paths("case", "matrix/").find((candidate) => SAMPLE.read(candidate).solves[0].prune === null);
    expect(path, "the sample has a matrix case that records no pruning").toBeTruthy();
    const doc = SAMPLE.read(path);
    const got = await runner.matrixCase(path, { budgetMs: 120_000 });
    expect(got.pruneInput).toBe("pool");
    expect(got.inputItems).toBe(doc.solves[0].pool.length);
    expect(got.keptItems).toBeLessThanOrEqual(got.inputItems);
    expect(got.status).toBe("optimal");
    expect(got.fOk, `${path}: F ${got.F} against ${doc.solves[0].result.F}`).toBe(true);
  }, 180_000);

  it("times Equip now and a farm path of an Upgrade case, step by step, and finds every step that Python found", async () => {
    const path = "upgrade/upgrade-slots-softcap.json";
    const recorded = SAMPLE.read(path).expected;
    const got = await runner.upgradeCase(path, { steps: 2, budgetMs: 120_000 });
    expect(got.name).toBe(path);
    expect(got.hasteOk).toBe(true);
    expect(got.equipFOk).toBe(true);
    expect(got.equipStatus).toBe("optimal");
    expect(got.stepsOk).toBe(true);
    expect(got).not.toHaveProperty("step1FOk");
    expect(got.recorded).toEqual({ steps: 2, stopped: "limit" });
    got.steps.forEach((step, at) => {
      // each step keeps its exact value, the recorded one and the item, so that a mismatch can be found in the JSON
      expect(typeof step.F, `step ${at + 1}`).toBe("string");
      expect(step.recordedF).toBe(recorded.steps[at].F);
      expect(step.fOk, `step ${at + 1}`).toBe(true);
      expect(step.item).toBe(recorded.steps[at].item);
      expect(step.recordedItem).toBe(recorded.steps[at].item);
    });
    expect(got.proofMs, "the path ended at its limit: no solve proved anything").toBeNull();
    expect(finite(got.equipMs) && finite(got.pathMs) && finite(got.tailMs)).toBe(true);
    expect(got.stepsFound).toBe(got.steps.filter((step) => step.found).length);
    expect(got.stepsFound).toBeGreaterThan(0);
    expect(got.stepsFound).toBeLessThanOrEqual(2);
    expect(["limit", "no-gain", "time"]).toContain(got.stopped);
    expect(got.equipTieMs, "placement only: the tie stage does not run").toBe(0);
    got.steps.forEach((step, at) => {
      expect(step.index).toBe(at + 1);
      expect(step.tieMs).toBe(0);
      for (const key of ["ownMs", "pruneMs", "buildMs", "syncMs", "solveMs", "tieMs", "arrivalMs"]) expect(finite(step[key]), `${at + 1} ${key}`).toBe(true);
      if (at > 0) expect(step.arrivalMs).toBeGreaterThanOrEqual(got.steps[at - 1].arrivalMs);
    });
    expect(got.steps[0].arrivalMs).toBeGreaterThanOrEqual(got.steps[0].ownMs);
    expect(got.pathMs).toBeGreaterThanOrEqual(got.steps[got.steps.length - 1].arrivalMs);
    expect(got.stepsFound).toBe(2); // this session has more gains than two to find, so the path ends at its limit
    expect(got.stopped).toBe("limit");
  }, 180_000);

  it("gets the value Python recorded in every matrix case of the sample, whether the case records its pruning or not", async () => {
    const paths = SAMPLE.paths("case", "matrix/");
    expect(paths.length).toBeGreaterThan(5);
    const kinds = new Set();
    for (const path of paths) {
      const got = await runner.matrixCase(path, { budgetMs: 120_000 });
      kinds.add(got.pruneInput);
      expect(got.status, path).toBe("optimal");
      expect(got.fOk, `${path}: F ${got.F} against ${SAMPLE.read(path).solves[0].result.F}`).toBe(true);
      expect(got.totalMs, path).toBeGreaterThanOrEqual(got.solveMs);
    }
    expect([...kinds].sort()).toEqual(["pool", "recorded"]);
  }, 300_000);

  it("gets Python's assumed haste, Equip now and every recorded step in every Upgrade case of the sample, with eight steps asked", async () => {
    const paths = SAMPLE.paths("case", "upgrade/");
    expect(paths.length).toBeGreaterThan(3);
    for (const path of paths) {
      const recorded = SAMPLE.read(path).expected;
      const got = await runner.upgradeCase(path, { steps: 8, budgetMs: 120_000 });
      expect([got.hasteOk, got.equipFOk, got.stepsOk], path).toEqual([true, true, true]);
      expect(got.recorded, path).toEqual({ steps: recorded.steps.length, stopped: recorded.stopped });
      expect(got.stepsFound, path).toBeGreaterThanOrEqual(recorded.steps.length);
      expect(got.stepsFound, path).toBeLessThanOrEqual(8);
      expect(got.stopped, path).toBe(got.stepsFound === 8 ? "limit" : "no-gain"); // (a budget of 120 s is never spent here)
      expect(got.steps.every((step) => step.found), path).toBe(true);
      got.steps.forEach((step, at) => expect(step.fOk, `${path} step ${at + 1}`).toBe(at < recorded.steps.length ? true : null)); // (null: nothing recorded to check it by)
      // a path that ended by itself ended in a solve that proved it (the three invented sessions), and one that ended at its limit did not
      expect(got.proofMs === null, path).toBe(got.stopped === "limit");
    }
  }, 300_000);

  it("times the solve that proves no step is left, and only when there was one", async () => {
    const path = "upgrade/upgrade-slots-softcap.json";
    const altered = new Map();
    const read = async (name) => altered.get(name) ?? SAMPLE.read(name);
    const own = await createRunner({ highs, read, bundlePaths: SAMPLE.paths("bundle"), profilesPath: "evaluate/profiles.json" });
    const change = (name, edit) => {
      const doc = structuredClone(SAMPLE.read(name));
      edit(doc);
      altered.set(name, doc);
    };

    // the two gains are found, and a third solve proves that nothing more is to be had: its time is what the path took after the last step was told
    const proved = await own.upgradeCase(path, { steps: 8, budgetMs: 120_000 });
    expect(proved.stopped).toBe("no-gain");
    expect(proved.stepsFound).toBe(2);
    expect(proved.proofMs).toBeGreaterThan(0);
    expect(proved.proofMs).toBeCloseTo(proved.tailMs, 6);

    // a path that stops at the steps asked for did nothing after its last step but bookkeeping
    const limited = await own.upgradeCase(path, { steps: 2, budgetMs: 120_000 });
    expect(limited.stopped).toBe("limit");
    expect(limited.proofMs).toBeNull();

    // the two candidates cannot be had twice (Lore): after they are had no candidate is left to add, the path ends by itself, and no solve proved it
    change(path, (doc) => {
      const keys = new Set(doc.inputs.candidates.map((name) => name.slice(0, name.lastIndexOf("@"))));
      for (const record of doc.records) if (keys.has(record.key)) record.lore = true;
    });
    const exhausted = await own.upgradeCase(path, { steps: 8, budgetMs: 120_000 });
    expect(exhausted.stopped).toBe("no-gain");
    expect(exhausted.stepsFound).toBe(2);
    expect(exhausted.proofMs).toBeNull();
    expect(exhausted.stepsOk).toBe(true);

    // no step at all, and the solve that proved there is none: what the path took without Equip now, which it runs first
    const twohand = "upgrade/upgrade-slots-twohand.json";
    change(twohand, (doc) => {
      for (const record of doc.records) if (record.key === "it-axe") record.stats = {}; // the one candidate adds nothing
      doc.expected.steps = [];
      doc.expected.stopped = "no-gain";
    });
    const nothing = await own.upgradeCase(twohand, { steps: 8, budgetMs: 120_000 });
    expect(nothing.stopped).toBe("no-gain");
    expect(nothing.stepsFound).toBe(0);
    expect(nothing.stepsOk).toBe(true);
    expect(finite(nothing.proofMs)).toBe(true);
    expect(nothing.proofMs).toBeLessThanOrEqual(nothing.pathMs);
    expect(nothing.proofMs).toBeLessThan(nothing.tailMs); // (the tail is the whole path here, Equip now included)

    // no step and no solve: the one candidate is a Lore copy of an item that is owned
    change(twohand, (doc) => {
      doc.inputs.candidates = ["it-sword@0"];
      for (const record of doc.records) if (record.key === "it-sword") record.lore = true;
      doc.expected.steps = [];
      doc.expected.stopped = "no-gain";
    });
    const none = await own.upgradeCase(twohand, { steps: 8, budgetMs: 120_000 });
    expect(none.stopped).toBe("no-gain");
    expect(none.stepsFound).toBe(0);
    expect(none.proofMs).toBeNull();
  }, 120_000);

  it("flags an answer that is not the value Python recorded (a case set up wrongly would be timed for nothing)", async () => {
    const altered = new Map();
    const read = async (path) => altered.get(path) ?? SAMPLE.read(path);
    const checking = await createRunner({ highs, read, bundlePaths: SAMPLE.paths("bundle"), profilesPath: "evaluate/profiles.json" });
    const change = (path, edit) => {
      const doc = structuredClone(SAMPLE.read(path));
      edit(doc);
      altered.set(path, doc);
    };

    const matrixPath = SAMPLE.paths("case", "matrix/")[0];
    expect((await checking.matrixCase(matrixPath, { budgetMs: 120_000 })).fOk).toBe(true);
    change(matrixPath, (doc) => {
      doc.solves[0].result.F = "1/1";
    });
    expect((await checking.matrixCase(matrixPath, { budgetMs: 120_000 })).fOk).toBe(false);

    const path = "upgrade/upgrade-slots-softcap.json";
    const run = async (steps = 2) => checking.upgradeCase(path, { steps, budgetMs: 120_000 });
    const fOks = (got) => got.steps.map((step) => step.fOk);
    expect(await run()).toMatchObject({ hasteOk: true, equipFOk: true, stepsOk: true });
    change(path, (doc) => {
      doc.solves[doc.expected.equip_now].result.F = "1/1";
    });
    expect(await run()).toMatchObject({ hasteOk: true, equipFOk: false, stepsOk: true });
    change(path, (doc) => {
      doc.expected.steps[0].F = "1/1";
    });
    const first = await run();
    expect(first).toMatchObject({ hasteOk: true, equipFOk: true, stepsOk: false });
    expect(fOks(first)).toEqual([false, true]);
    change(path, (doc) => {
      doc.expected.steps[1].F = "1/1"; // every recorded step is held to its value, not the first alone
    });
    const second = await run();
    expect(second.stepsOk).toBe(false);
    expect(fOks(second)).toEqual([true, false]);
    expect(second.steps[1].recordedF).toBe("1/1"); // (and the JSON keeps both values)
    expect(second.steps[1].F).not.toBe("1/1");
    expect((await run(1)).stepsOk, "a recorded step beyond the steps asked for is not held to anything").toBe(true);
    change(path, (doc) => {
      doc.expected.session_haste = 99;
    });
    expect((await run()).hasteOk).toBe(false);
    change(path, (doc) => {
      doc.expected.steps = [];
      doc.expected.stopped = "no-gain";
    });
    expect((await run()).stepsOk, "Python found no step before it was out of them, and this found some").toBe(false);
    change(path, (doc) => {
      doc.expected.steps = doc.expected.steps.slice(0, 1);
      doc.expected.stopped = "no-gain";
    });
    expect((await run()).stepsOk, "Python was out of steps after 1 of the 2 asked for, and this went on to a second").toBe(false);

    // the invented session with one gain: Python ran out of steps after 1
    const twohand = "upgrade/upgrade-slots-twohand.json";
    const ran = async (steps) => checking.upgradeCase(twohand, { steps, budgetMs: 120_000 });
    expect(await ran(2)).toMatchObject({ stepsOk: true, stopped: "no-gain", stepsFound: 1 });
    expect(await ran(1)).toMatchObject({ stepsOk: true, stopped: "limit", stepsFound: 1 }); // asked for 1: running out after 1 is not asked about
    change(twohand, (doc) => {
      doc.expected.steps.push({ ...doc.expected.steps[0], index: 2, F: "1/1" }); // a second step that Python found and this does not
      doc.expected.stopped = "limit";
    });
    expect((await ran(2)).stepsOk, "this found fewer steps than Python did").toBe(false);
    expect((await ran(1)).stepsOk).toBe(true);
  }, 120_000);

  it("reports a case that fails as an error, and refuses a path that is not in the fixtures", async () => {
    await expect(runner.matrixCase("matrix/not-there.json", { budgetMs: 1000 })).rejects.toThrow(/not-there/);
    await expect(runner.upgradeCase("upgrade/not-there.json", { steps: 1, budgetMs: 1000 })).rejects.toThrow(/not-there/);
  });

  it("measures the cold start from the bytes: compile, then the start of the solver", async () => {
    const bytes = new Uint8Array(readFileSync(WASM_FILE));
    const got = await coldStart({ bytes, wasmHref: "http://127.0.0.1/highs.wasm" });
    expect(got.version).toMatch(/^1\.15\.\d+$/);
    for (const key of ["compileMs", "startMs", "totalMs", "firstSolveMs"]) expect(finite(got[key]), key).toBe(true);
    expect(got.totalMs).toBeCloseTo(got.compileMs + got.startMs, 6); // (the first solve comes after the clock has stopped)
    expect(got.firstSolveMs).toBeGreaterThan(0);
  }, 60_000);

  it("has a calibration workload that is the same every time: a loop and a small solve", async () => {
    expect(jsLoop(1000)).toBe(jsLoop(1000));
    expect(jsLoop(1000)).not.toBe(jsLoop(1001));
    expect(smallSolve(highs)).toBeCloseTo(CALIBRATION_OBJECTIVE, 6);
    expect(smallSolve(highs)).toBeCloseTo(CALIBRATION_OBJECTIVE, 6);
    const got = await workload(highs, { reps: 2, worker: false });
    expect(got.loopMs).toHaveLength(2);
    expect(got.solveMs).toHaveLength(2);
    expect(got.workerMs).toBeNull();
    for (const ms of [...got.loopMs, ...got.solveMs]) expect(ms).toBeGreaterThan(0);
  }, 60_000);
});
