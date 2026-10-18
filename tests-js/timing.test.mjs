// The helper for wall-clock bounds (tests-js/timing.mjs): a bound that guards against a blow-up of an algorithm must hold on a busy machine and still fail on a real blow-up.
//
// What is checked on the real clock here holds on any machine at any load (a sleep that is too long for its budget fails whatever the factor is; a load of busy threads gives a factor above 1; the
// factor is always between 1 and 8). Everything that depends on how fast a loop is on the machine is checked with times that are given, not measured: the machine under test may be slower than the one
// the reference was taken on (CI is), or busy with other suites, and a test of the helper must not fail for that.
import os from "node:os";
import { describe, expect, it } from "vitest";
import { MAX_FACTOR, MIN_FACTOR, REFERENCE_MS, Timing, busyThreads, expectWithin, factorFrom, loadFactor, stopwatch, timeLoop } from "./timing.mjs";

/** Block this thread for `ms` without using the CPU: a stand-in that is slow while the machine is not busy. */
const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
const R = REFERENCE_MS;

describe("the load factor of a list of loop times", () => {
  it("is 1 when the loop takes as long as the reference, which is how long it took on an idle machine", () => {
    expect(factorFrom([R, R, R, R, R])).toBe(1);
    expect(factorFrom([0.97 * R, 1.02 * R, R, 1.03 * R, 0.98 * R])).toBe(1); // the mean of these is the reference itself
    expect(factorFrom([1.04 * R, 1.05 * R, 1.06 * R])).toBeCloseTo(1.05, 10);
  });

  it("is how many times slower the loop is than the reference: the mean of the times over the reference", () => {
    expect(factorFrom([2 * R, 2 * R, 2 * R])).toBeCloseTo(2, 10);
    expect(factorFrom([2 * R, 4 * R, 3 * R])).toBeCloseTo(3, 10);
    expect(factorFrom([2 * R, 3 * R, 4 * R, 5 * R])).toBeCloseTo(3.5, 10);
    expect(factorFrom([5 * R])).toBeCloseTo(5, 10);
  });

  it("counts a run that another thread cut short: one run in five that took six times as long makes the machine twice as slow", () => {
    // (the work that is timed meets that thread as often as the runs do, so the runs that were not cut do not say how slow the work will be)
    expect(factorFrom([R, R, 6 * R, R, R])).toBeCloseTo(2, 10);
    expect(factorFrom([R, 6 * R, R, R, R])).toBeCloseTo(2, 10);
  });

  it("is never below 1: a machine faster than the reference is not given a stricter bound", () => {
    expect(factorFrom([R / 2])).toBe(MIN_FACTOR);
    expect(factorFrom([0.001])).toBe(MIN_FACTOR);
    expect(MIN_FACTOR).toBe(1);
  });

  it("is never above 8: past that a bound would hide a real blow-up, and one long pause cannot take it there by much", () => {
    expect(factorFrom([8 * R])).toBe(MAX_FACTOR);
    expect(factorFrom([9 * R])).toBe(MAX_FACTOR);
    expect(factorFrom([R, R, R, R, 1000 * R])).toBe(MAX_FACTOR);
    expect(factorFrom([1e9])).toBe(MAX_FACTOR);
    expect(factorFrom([Infinity])).toBe(MAX_FACTOR);
    expect(MAX_FACTOR).toBe(8);
  });

  it("refuses a list that is empty or holds what is not a time", () => {
    expect(() => factorFrom([])).toThrow(TypeError);
    expect(() => factorFrom([R, Number.NaN, R])).toThrow(TypeError);
    expect(() => factorFrom([R, -1, R])).toThrow(TypeError);
    expect(() => factorFrom([R, "10", R])).toThrow(TypeError);
    expect(() => factorFrom(R)).toThrow(TypeError);
  });
});

describe("the load factor of this machine, now", () => {
  it("is a number from 1 to 8 each time it is asked, and the loop it times does real work", () => {
    for (let at = 0; at < 3; at += 1) {
      const factor = loadFactor();
      expect(factor).toBeGreaterThanOrEqual(1);
      expect(factor).toBeLessThanOrEqual(8);
    }
    // the best of 15 runs: a busy machine only makes a run longer, so this holds at any load. A loop that did nothing would take no time, and nothing would be measured.
    const best = Math.min(...Array.from({ length: 15 }, () => timeLoop()));
    expect(best, `the fastest of 15 runs of the loop, against the reference of ${R} ms`).toBeGreaterThan(R / 4);
  });

  it("is clearly more than 1 under a synthetic load: worker threads that spin, two for each logical processor", async () => {
    // (a run of 10 ms is cut by the other threads only now and then, so a reading can be 1.0 on a machine that is loaded: the test takes readings, over ten seconds at most, until one is clearly above 1)
    const load = await busyThreads(2 * os.availableParallelism());
    try {
      const readings = [];
      const until = performance.now() + 10_000;
      while (Math.max(0, ...readings) <= 1.5 && performance.now() < until) readings.push(loadFactor());
      console.info(`load factor under ${load.threads} busy threads: ${readings.map((factor) => factor.toFixed(2)).join(" ")}`);
      expect(Math.max(...readings)).toBeGreaterThan(1.5);
    } finally {
      await load.stop();
    }
  }, 30_000); // (the threads take a moment to start on a machine that is busy already)

  it("starts the threads it is asked for, and stops them", async () => {
    const load = await busyThreads(2);
    expect(load.threads).toBe(2);
    await expect(load.stop()).resolves.toBeUndefined();
    await expect(load.done).resolves.toBeUndefined(); // they have ended
  }, 30_000); // (the same)

  it("ends the threads by itself when maxMs is over, so that a load that is forgotten does not go on", async () => {
    const began = performance.now();
    const load = await busyThreads(2, { maxMs: 300 });
    await expect(load.done).resolves.toBeUndefined(); // (no stop() is called)
    expect(performance.now() - began).toBeGreaterThanOrEqual(250);
  }, 30_000); // (the same)
});

describe("a time with the load factors around it", () => {
  it("holds the factors as they were measured, and the larger of the two is the one that counts", () => {
    const timing = new Timing(120, 1.5, 3);
    expect([timing.ms, timing.before, timing.after, timing.factor]).toEqual([120, 1.5, 3, 3]);
    expect(new Timing(120, 4, 2).factor).toBe(4);
    expect(new Timing(120).factor).toBe(1);
    expect(new Timing(120, 2).factor).toBe(2); // one factor given: it stands for both
  });

  it("clamps the factors it is given to 1 to 8", () => {
    const timing = new Timing(5, 0.2, 99);
    expect([timing.before, timing.after, timing.factor]).toEqual([1, 8, 8]);
  });

  it("refuses a time that is not a number of milliseconds of 0 or more, and a factor that is not a number", () => {
    expect(() => new Timing(-1)).toThrow(TypeError);
    expect(() => new Timing(Number.NaN)).toThrow(TypeError);
    expect(() => new Timing("5")).toThrow(TypeError);
    expect(() => new Timing(5, Number.NaN)).toThrow(TypeError);
  });

  it("per(n) is the time of one of n: the milliseconds over n, with the same factors", () => {
    const each = new Timing(500, 2, 3).per(1000);
    expect([each.ms, each.before, each.after]).toEqual([0.5, 2, 3]);
    expect(() => new Timing(500).per(0)).toThrow(TypeError);
  });
});

describe("expectWithin", () => {
  const budget = 100;
  const message = (timing, what = "the thing that was timed") => {
    try {
      expectWithin(timing, budget, what);
    } catch (error) {
      return error.message;
    }
    return null;
  };

  it("passes below the budget times the load factor, and fails at it and above", () => {
    expectWithin(new Timing(99, 1, 1), budget, "x");
    expectWithin(new Timing(299, 3, 3), budget, "x");
    expect(() => expectWithin(new Timing(100, 1, 1), budget, "x")).toThrow();
    expect(() => expectWithin(new Timing(300, 3, 3), budget, "x")).toThrow();
    expect(() => expectWithin(new Timing(301, 3, 3), budget, "x")).toThrow();
  });

  it("takes the larger of the factors measured before the work and after it", () => {
    expectWithin(new Timing(250, 1, 3), budget, "x");
    expectWithin(new Timing(250, 3, 1), budget, "x");
    expect(() => expectWithin(new Timing(250, 2, 2), budget, "x")).toThrow();
    expect(() => expectWithin(new Timing(250, 1, 2), budget, "x")).toThrow();
  });

  it("says in its message the time, the budget, the factor and what was timed", () => {
    const text = message(new Timing(500, 2, 3), "a flood of line ends is read");
    expect(text).toContain("a flood of line ends is read");
    expect(text).toContain("500.0 ms");
    expect(text).toContain("budget of 100 ms");
    expect(text).toContain("load factor 3.00");
    expect(text).toContain("300 ms");
    expect(message(new Timing(50, 1, 1))).toBeNull();
  });

  it("judges a bare number of milliseconds by the factor measured when it is called: below the budget it always passes, and at 8 times the budget it always fails", () => {
    expectWithin(1, budget, "x");
    expectWithin(0, budget, "x");
    expect(() => expectWithin(8 * budget, budget, "x")).toThrow();
    expect(() => expectWithin(20 * budget, budget, "x")).toThrow();
    expect(message(20 * budget, "a bare number")).toContain("a bare number");
  });

  it("refuses a budget that is not a positive number, and a time that is not a number", () => {
    for (const bad of [0, -5, Number.NaN, Infinity, "100", undefined]) expect(() => expectWithin(new Timing(1), bad, "x"), String(bad)).toThrow(TypeError);
    for (const bad of [Number.NaN, -1, Infinity, "5", undefined, null]) expect(() => expectWithin(bad, budget, "x"), String(bad)).toThrow(TypeError);
  });

  it("fails a time of 20 times the budget at every load factor, because the factor stops at 8", () => {
    for (const factor of [1, 1.5, 2, 4, 7.9, 8, 9, 100, 1e9]) {
      expect(() => expectWithin(new Timing(20 * budget, factor, factor), budget, "a planted slowdown"), `factor ${factor}`).toThrow(/a planted slowdown/);
    }
    // and just below 8 times the budget passes at the largest factor there is, as the bound is meant to let a very busy machine through
    expectWithin(new Timing(7.99 * budget, 1e9, 1e9), budget, "x");
  });
});

describe("the stopwatch", () => {
  it("times the work between its start and its stop, and has the load factors measured around it", () => {
    const watch = stopwatch();
    sleep(30);
    const timing = watch.stop();
    expect(timing).toBeInstanceOf(Timing);
    expect(timing.ms).toBeGreaterThanOrEqual(25);
    expect(timing.ms).toBeLessThan(5000);
    for (const factor of [timing.before, timing.after]) {
      expect(factor).toBeGreaterThanOrEqual(1);
      expect(factor).toBeLessThanOrEqual(8);
    }
  });

  it("does not count the time it takes to measure the load in the time of the work", () => {
    const began = performance.now();
    loadFactor();
    const cost = performance.now() - began; // some tens of milliseconds on an idle machine, and more on a busy one
    const watch = stopwatch(); // measures the load before the clock starts
    const timing = watch.stop(); // and after it stops
    expect(timing.ms).toBeLessThan(cost / 2);
  });

  it("stop(ms) keeps the factors of the interval and takes the time that was measured by hand (the slowest of a number of runs, say)", () => {
    const watch = stopwatch();
    sleep(5);
    const timing = watch.stop(123.5);
    expect(timing.ms).toBe(123.5);
    expect(timing.factor).toBeGreaterThanOrEqual(1);
  });

  it("a stand-in that takes 20 times its budget fails the real bound whatever the load of the machine: a planted sleep is not hidden", () => {
    const budget = 25;
    const watch = stopwatch();
    sleep(20 * budget); // the planted slowdown: 500 ms in a function that is allowed 25
    const timing = watch.stop();
    expect(timing.ms).toBeGreaterThanOrEqual(20 * budget - 10);
    expect(() => expectWithin(timing, budget, "a stand-in with a planted sleep")).toThrow(/a stand-in with a planted sleep/);
  });
});
