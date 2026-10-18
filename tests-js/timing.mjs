// Wall-clock bounds that hold up on a busy machine (not a test file itself; its tests are in timing.test.mjs).
//
// The bounds of the tests ("a flood of CR is parsed in under 250 ms", "a hostile dump in under 500 ms") are there to catch an algorithm that has become 10 or 100 times slower, not one that
// has become twice as slow because other suites and agents are using the machine. A busy machine (this one, with several suites running) made them fail with no defect, and a failure that
// means nothing teaches everyone to ignore failures. So the budget is multiplied by the load factor of the machine, the larger of the factors measured just before the timed work and just
// after it, and the factor stops at 8: a time of 8 times its budget or more fails whatever the load is.
//
//   const watch = stopwatch();                      // measures the load factor, then starts the clock
//   ...the work that is timed...
//   expectWithin(watch.stop(), 250, "a flood of CR is parsed");   // stops the clock, then measures the load factor again
//
// `watch.stop(ms)` takes a time that the test measured itself (the slowest of a number of runs, say) and gives it the factors of the whole interval. `expectWithin` also takes a bare
// number of milliseconds, and then the factor is the one measured when it is called, after the work.
//
// The load factor is how many times slower this machine is now than when it was idle: a fixed CPU-bound loop is timed a few times and the mean of the times is taken over REFERENCE_MS.
// It is a mean and not a median on purpose. Against 48 threads that spin in the process, a job of 200 ms took 2.5 times as long as when idle (the median of 48 jobs). The median of five runs
// of the loop, taken before and after each job, was under two thirds of that job's slowdown in 15 of the 48 jobs; the mean of the five runs, in none. (One long pause can raise a mean;
// the factor only loosens a bound, and stops at 8.)
import { createHash } from "node:crypto";
import { Worker } from "node:worker_threads";
import { expect } from "vitest";

/** The real clock, taken now: a test that installs fake timers later does not change the time of a bound. */
const now = performance.now.bind(performance);

/**
 * What the loop takes when the machine is idle, in milliseconds.
 *
 * Measured on 2026-10-17 on the maintainer's desktop (12 cores, Node 24.14): 1,200 runs, 100 in each of twelve new node processes, each timed right after the warm-up,
 * with other work using 20% of the processors. The median of the runs was 10.01 ms (the quartiles 9.98 and 10.05, the fastest run 9.90, the slowest 11.12). A slower machine (the CI runner)
 * has a factor above 1 for the same reason a busy one has, which is wanted: the budgets were set on this machine. A faster one has a factor of 1.
 */
export const REFERENCE_MS = 10.0;

/** The least and the most a budget is multiplied by. */
export const MIN_FACTOR = 1;
export const MAX_FACTOR = 8;

/** How many runs of the loop make a load factor. */
const SAMPLES = 5;

const BLOCK = Buffer.alloc(256 * 1024, 7);
const BLOCKS = 33;
let warm = false;

/**
 * The loop: the MD5 of 33 blocks of 256 KB, about 10 ms when the machine is idle. It is native code that depends on nothing but the speed of the core and the share of it that the thread gets,
 * and not on what the engine has compiled: a loop written in JavaScript was fast for its first 400 runs and five times slower from then on, whatever the load of the machine was (the engine
 * kept throwing its optimised code away).
 */
function spin() {
  const hash = createHash("md5");
  for (let at = 0; at < BLOCKS; at += 1) hash.update(BLOCK);
  hash.digest();
}

/** The time of one run of the loop, in milliseconds. The first call runs it twice before it is timed, so that what it needs is loaded. */
export function timeLoop() {
  if (!warm) {
    spin();
    spin();
    warm = true;
  }
  const began = now();
  spin();
  return now() - began;
}

const clamp = (factor) => Math.min(MAX_FACTOR, Math.max(MIN_FACTOR, factor));

/** The load factor of some times of the loop: their mean over REFERENCE_MS, from 1 to 8. */
export function factorFrom(times) {
  if (!Array.isArray(times) || times.length === 0 || times.some((time) => typeof time !== "number" || Number.isNaN(time) || time < 0)) {
    throw new TypeError("the load factor is worked out from a list of times of the loop, each a number of milliseconds of 0 or more");
  }
  return clamp(times.reduce((sum, time) => sum + time, 0) / times.length / REFERENCE_MS);
}

/** How many times slower this machine is now than when it was idle, from 1 to 8. It takes SAMPLES runs of the loop, some 50 ms on an idle machine. */
export function loadFactor() {
  return factorFrom(Array.from({ length: SAMPLES }, () => timeLoop()));
}

const asFactor = (factor) => {
  if (typeof factor !== "number" || Number.isNaN(factor)) throw new TypeError(`a load factor is a number, not ${String(factor)}`);
  return clamp(factor);
};

const asTime = (ms) => {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) throw new TypeError(`a time is a number of milliseconds of 0 or more, not ${String(ms)}`);
  return ms;
};

/** A time in milliseconds with the load factors measured before and after it (each from 1 to 8; one given stands for both). */
export class Timing {
  constructor(ms, before = MIN_FACTOR, after = before) {
    this.ms = asTime(ms);
    this.before = asFactor(before);
    this.after = asFactor(after);
    Object.freeze(this);
  }

  /** The larger of the two: the load that the work may have been under. */
  get factor() {
    return Math.max(this.before, this.after);
  }

  /** The time of one of `count`, with the same factors. */
  per(count) {
    if (typeof count !== "number" || !(count > 0)) throw new TypeError(`a count is a number above 0, not ${String(count)}`);
    return new Timing(this.ms / count, this.before, this.after);
  }
}

/** Measure the load factor and start the clock. `stop()` stops the clock, measures the factor again and gives the Timing; `stop(ms)` gives the time that the test measured instead. */
export function stopwatch() {
  const before = loadFactor();
  const began = now();
  return {
    stop(ms) {
      const took = now() - began;
      return new Timing(ms === undefined ? took : ms, before, loadFactor());
    },
  };
}

/**
 * Fail unless `measured` (a Timing, or a bare number of milliseconds) is below `budget` times the load factor. The message gives the time, the budget, the factor and what was timed.
 * A time that passes only because of the factor is told in the output of the test.
 */
export function expectWithin(measured, budget, what) {
  if (typeof budget !== "number" || !Number.isFinite(budget) || !(budget > 0)) throw new TypeError(`a budget is a number of milliseconds above 0, not ${String(budget)}`);
  const known = measured instanceof Timing;
  const timing = known ? measured : new Timing(asTime(measured), MIN_FACTOR, loadFactor()); // (what is not a time is refused before the load is measured)
  const limit = budget * timing.factor;
  const factors = known ? `factor ${timing.before.toFixed(2)} before the work, ${timing.after.toFixed(2)} after` : `factor ${timing.after.toFixed(2)}, measured after the work and not before it`;
  if (timing.ms >= budget && timing.ms < limit) console.info(`timing: ${what}: ${timing.ms.toFixed(1)} ms is over the budget of ${budget} ms and within ${limit.toFixed(0)} ms (${factors})`);
  expect(timing.ms, `${what}: took ${timing.ms.toFixed(1)} ms, over the budget of ${budget} ms x load factor ${timing.factor.toFixed(2)} = ${limit.toFixed(0)} ms (${factors})`).toBeLessThan(limit);
}

/**
 * A synthetic load: `count` worker threads that spin until `stop()` is called, or until `maxMs` is over (so that a load that is forgotten ends by itself). Resolves once all of them run.
 * `done` resolves once all of them have ended. For the tests of this helper, and to load the machine by hand when a suite is run.
 */
export async function busyThreads(count, { maxMs = 60_000 } = {}) {
  // (the clock is read once for every million steps: read in every step, 24 threads together used 3 cores and not 24)
  const code = `let x = 1; const end = Date.now() + ${Number(maxMs)}; require("node:worker_threads").parentPort.postMessage("up"); for (;;) { for (let i = 0; i < 1e6; i += 1) x = (Math.imul(x, 1103515245) + 12345) | 0; if (Date.now() > end) break; }`;
  const workers = [];
  const exits = [];
  try {
    for (let at = 0; at < count; at += 1) {
      const worker = new Worker(code, { eval: true });
      workers.push(worker);
      exits.push(new Promise((resolve) => worker.once("exit", resolve)));
    }
    await Promise.all(
      workers.map(
        (worker) =>
          new Promise((resolve, reject) => {
            worker.once("message", resolve);
            worker.once("error", reject);
          }),
      ),
    );
  } catch (error) {
    await Promise.all(workers.map((worker) => worker.terminate()));
    throw error;
  }
  return {
    threads: count,
    done: Promise.all(exits).then(() => undefined),
    async stop() {
      await Promise.all(workers.map((worker) => worker.terminate()));
    },
  };
}
