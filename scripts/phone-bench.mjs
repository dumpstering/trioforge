// The phone gate: times the browser engine (static/engine: model.js, prune.js, solve.js, path.js, with highs-js) in Chromium under CDP CPU throttling,
// the proxy for a low-end phone, and decides from the numbers how the Upgrade tab's farm path runs.
//
//   node scripts/phone-bench.mjs [--throttle 6] [--port 8799] [--matrix 40] [--upgrade 10] [--json out.json] [--smoke]
//
// It bundles scripts/phone-bench-page.mjs with esbuild (into a temporary folder), serves the bundle, the highs WebAssembly and the fixture documents of
// build/fixtures from a small HTTP server on 127.0.0.1, starts Chromium, and measures, one case after another and never in parallel:
//
//   1. the calibration: one fixed workload (a JavaScript loop, one small highs-js solve) at rate 1 and at the rate chosen; a ratio below 0.6 times
//      the rate means the throttle is not working, and the script says so and exits with 2. The loop in a dedicated worker is timed as well: Chrome's
//      throttle slows the page's main thread, not a worker, which is why the engine is run on the main thread here (it is a worker in the product);
//   2. the cold start: from the WebAssembly bytes in memory (the download is left out) to a started solver, five times, each in a fresh page; then the
//      first small solve of that page, because V8 compiles the module's functions when they are first called, which the time to a started solver leaves out;
//   3. full-pool solves, placement only (`canonical: false`), of the matrix family: pruning, building the model, solving;
//   4. the Upgrade family: Equip now, and the farm path with 8 steps and a budget of 600 s, each step's own time from `onStep`.
//
// Each distribution is reported as its median, its 95th percentile and its maximum. "One farm step" is every Best-1 solve a user waits for: the own time of
// every step of every path, found or not, and, for a path that ended by itself ("no-gain"), the solve that proved no step was left. The engine does not
// report the time of that last solve (`farmPath` tells `onStep` the steps it makes, not the solve that makes none), so it is taken as the time the call took
// after the last step was told (`tailMs` in the page; less the Equip now that a path with no step also contains), and counted only if a solve took place
// then (see the page). The decision (decide) is printed with the numbers it rests on:
//   * the farm path streams if the 95th percentile of one farm step is 8000 ms or less, and otherwise asks for each step after the first;
//   * the reweight sliders snap to precomputed positions if the 95th percentile of a full-pool solve's total is above 10000 ms.
//
// A watchdog guards the calls into the page that measure: a case that has not returned within twice its budget and a minute, or a cold start that has not
// (it counts as having a budget of 30 s), ends the run. What was measured is written to --json if given, the case that hung is named, the browser and the
// server are closed, and the exit code is 1.
//
// What the proxy leaves out: Chrome slows the main thread only, so the compiling of the WebAssembly (which V8 does on helper threads) and any other
// helper thread run at the speed of the machine; the cold start is therefore the least reliable of the numbers. Run it on a machine with nothing else to
// do: the script starts nothing of its own while a case is measured, but the machine's other work is added to every time.
//
// Exit codes: 0 done; 1 done, but a case failed, an answer was not the value Python recorded (a step of a path included), or a solve ended without a proof,
// or the run was ended by the watchdog; 2 not measured (bad options, no fixtures, no browser, or a throttle that does not work).

import { createHash } from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { percentile } from "./bench-highs.mjs";
import { FixtureSet } from "./fixture-reader.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const PAGE_ENTRY = path.join(HERE, "phone-bench-page.mjs");
const FIXTURES_DIRECTORY = path.join(ROOT, "build", "fixtures");
const HIGHS_DIRECTORY = path.join(ROOT, "node_modules", "highs");
const MAKE_FULL = "PYTHONPATH=pipeline python -m trioforge.export.fixtures --out build/fixtures --seed 20261014";
const PROFILES_PATH = "evaluate/profiles.json";

/** The farm path streams if the 95th percentile of one farm step is at most this many milliseconds. */
export const FARM_STEP_LIMIT_MS = 8000;
/** The reweight sliders snap if the 95th percentile of a full-pool solve's total is above this many milliseconds. */
export const FULL_POOL_LIMIT_MS = 10000;
/** The throttle works if each ratio of the calibration is at least this fraction of the rate. */
export const CALIBRATION_FLOOR = 0.6;
/** The target of the bundle the browser gets: ES2021 and Safari 15, the oldest the engine is built for (pipeline/trioforge/site/build.py bundles it the same way). */
export const BUNDLE_TARGET = ["es2021", "safari15"];
/** The fresh pages the cold start is measured in, the repeats of the calibration, and the time a solve or a path may take (the parity tests' own). */
export const COLD_STARTS = 5;
export const CALIBRATION_REPS = 3;
export const BUDGET_MS = 600_000;

export const DEFAULT_OPTIONS = Object.freeze({ throttle: 6, port: 8799, matrix: 40, upgrade: 10, steps: 8, json: null, smoke: false, help: false });
/** What `--smoke` sets: a quick run to see that everything works, not a measurement. */
export const SMOKE_OPTIONS = Object.freeze({ throttle: 1, matrix: 2, upgrade: 1, steps: 2 });

// ---- the numbers ------------------------------------------------------------------------------------------------------------------------

/** The count, the median, the 95th percentile and the maximum of a list of milliseconds (or any finite numbers). A list that is empty is refused. */
export function summarize(values) {
  if (!Array.isArray(values)) throw new TypeError("a summary is made of a list of numbers");
  if (values.length === 0) throw new RangeError("a summary needs at least one value");
  for (const value of values) {
    if (typeof value !== "number" || !Number.isFinite(value)) throw new TypeError(`a summary is made of finite numbers, not ${String(value)}`);
  }
  return { n: values.length, median: percentile(values, 50), p95: percentile(values, 95), max: Math.max(...values) };
}

/**
 * `count` of the names, spread evenly over the names sorted as the code units of the text sort (the order a default sort gives): the name at
 * floor((2k + 1) n / 2 count) of the n, for k = 0 to count - 1, which are `count` different places, as far apart as whole places can be. Asked for as
 * many names as there are, or more, it gives them all. The same names give the same pick, in whatever order they come.
 */
export function pickSpread(names, count) {
  if (!Number.isInteger(count) || count < 1) throw new RangeError(`the number of cases is a whole number from 1, not ${String(count)}`);
  const sorted = [...names].sort();
  if (count >= sorted.length) return sorted;
  return Array.from({ length: count }, (_, k) => sorted[Math.floor(((2 * k + 1) * sorted.length) / (2 * count))]);
}

/**
 * Whether the throttle worked: the calibration ran the workload at rate 1 and at `rate`, and a ratio (the time at the rate over the time at 1) of the
 * loop and of the solve must each be at least `CALIBRATION_FLOOR` times the rate. `failed` names those that were below it.
 */
export function calibrationVerdict({ rate, loopRatio, solveRatio }) {
  if (typeof rate !== "number" || !Number.isFinite(rate) || rate < 1) throw new RangeError(`the rate is a number from 1, not ${String(rate)}`);
  for (const [name, ratio] of [["loop", loopRatio], ["solve", solveRatio]]) {
    if (typeof ratio !== "number" || !Number.isFinite(ratio) || ratio <= 0) throw new RangeError(`the ${name} ratio is a positive number, not ${String(ratio)}`);
  }
  // (twelve digits: 0.6 times 6 is 3.5999999999999996 in floating point, and the line is 3.6)
  const floor = Number((rate * CALIBRATION_FLOOR).toPrecision(12));
  const failed = [];
  if (loopRatio < floor) failed.push("loop");
  if (solveRatio < floor) failed.push("solve");
  return { effective: failed.length === 0, rate, floor, loopRatio, solveRatio, failed };
}

/** What the script says when the throttle did not work (the ratios that fell short, and the line they had to reach). */
export function describeVerdict(verdict) {
  const slower = { loop: `the JS loop ran x${verdict.loopRatio.toFixed(2)} slower`, solve: `the highs solve ran x${verdict.solveRatio.toFixed(2)} slower` };
  return (
    `the CPU throttle is not effective at rate ${verdict.rate}: ${verdict.failed.map((name) => slower[name]).join(" and ")} than at rate 1, ` +
    `and each must be at least x${verdict.floor.toFixed(2)} (${CALIBRATION_FLOOR} times the rate). Nothing was measured.`
  );
}

function p95Of(summary, what) {
  const value = summary?.p95;
  if (typeof value !== "number" || !Number.isFinite(value)) throw new TypeError(`the decision needs the 95th percentile of ${what}, and the summary has none`);
  return value;
}

/**
 * The decision, from the summary of a run (`summary.farmStep`: one farm step, every step of every path; `summary.fullPool.total`: a full-pool solve's
 * total). The two are separate. The farm path is "streaming" if the 95th percentile of one farm step is at most 8000 ms (step 1 starts by itself, later
 * steps are added as they finish) and "on-request" if it is above (step 1 starts by itself, each later step on request). The sliders are "snap" if the
 * 95th percentile of a full-pool solve's total is above 10000 ms and "free" if it is at most that.
 */
export function decide(summary) {
  const farmStepP95Ms = p95Of(summary?.farmStep, "one farm step");
  const fullPoolP95Ms = p95Of(summary?.fullPool?.total, "a full-pool solve's total");
  return {
    farmPath: farmStepP95Ms <= FARM_STEP_LIMIT_MS ? "streaming" : "on-request",
    sliders: fullPoolP95Ms > FULL_POOL_LIMIT_MS ? "snap" : "free",
    farmStepP95Ms,
    farmStepLimitMs: FARM_STEP_LIMIT_MS,
    fullPoolP95Ms,
    fullPoolLimitMs: FULL_POOL_LIMIT_MS,
  };
}

/**
 * A time in milliseconds with one decimal place, with more digits only where one decimal would round it onto the limit it is printed beside (8000.04 is
 * not to read "8000.0 ms, above 8000 ms"): the digits that tell the two apart are printed.
 */
function showMs(value, limit) {
  let digits = 1;
  while (digits < 15 && value !== limit && Number(value.toFixed(digits)) === limit) digits += 1;
  return value.toFixed(digits);
}

/** The decision as the lines the script prints: what to do, and the numbers it rests on. */
export function formatDecision(decision) {
  const step = `${showMs(decision.farmStepP95Ms, decision.farmStepLimitMs)} ms`;
  const total = `${showMs(decision.fullPoolP95Ms, decision.fullPoolLimitMs)} ms`;
  const lines = [];
  if (decision.farmPath === "streaming") {
    lines.push(`farm path: streaming (the 95th percentile of one farm step is ${step}, at most ${decision.farmStepLimitMs} ms): step 1 starts automatically,`);
    lines.push("  later steps are added as they finish, up to 8 steps or a 60 s soft budget, with Stop");
  } else {
    lines.push(`farm path: on-request (the 95th percentile of one farm step is ${step}, above ${decision.farmStepLimitMs} ms): step 1 runs automatically,`);
    lines.push('  each later step on request ("Next step")');
  }
  if (decision.sliders === "snap") {
    lines.push(`reweight sliders: snap (the 95th percentile of a full-pool solve's total is ${total}, above ${decision.fullPoolLimitMs} ms): the sliders snap to`);
    lines.push("  precomputed positions only, custom weights are Advanced-only, with a progress bar");
  } else {
    lines.push(`reweight sliders: free (the 95th percentile of a full-pool solve's total is ${total}, at most ${decision.fullPoolLimitMs} ms)`);
  }
  return lines;
}

// ---- the summary of a run ------------------------------------------------------------------------------------------------------------------

const succeeded = (cases) => cases.filter((measured) => measured.error === undefined);
const countOf = (cases, test) => cases.filter(test).length;

/**
 * The summary of what was measured: `coldStarts` (each `{compileMs, startMs, totalMs, firstSolveMs}`), `matrix` and `upgrade` (the results of the page's `matrixCase` and
 * `upgradeCase`, or `{name, error}` for a case that failed). A part with nothing measured is refused.
 *
 * The distribution of one farm step (`farmStep`) is made of every Best-1 solve that a user waits for: the own time of every step of every path, found or
 * not, and, for a path that ended by itself ("no-gain"), the solve that proved no step was left (`proofMs`, which the page measures only when there was
 * such a solve: a path that ended at its limit, or that had no candidate left to add, has none). `farmStepSamples` counts the three kinds. `firstStep` is
 * the own time of step 1 of each path that found one.
 */
export function buildSummary({ coldStarts, matrix, upgrade }) {
  if (coldStarts.length === 0) throw new RangeError("no cold start was measured");
  const matrixOk = succeeded(matrix);
  const upgradeOk = succeeded(upgrade);
  if (matrixOk.length === 0) throw new RangeError("no matrix case was measured");
  if (upgradeOk.length === 0) throw new RangeError("no upgrade case was measured");
  const steps = upgradeOk.flatMap((measured) => measured.steps);
  const foundSteps = steps.filter((step) => step.found);
  const proofs = upgradeOk.filter((measured) => measured.stopped === "no-gain" && typeof measured.proofMs === "number");
  const samples = [...steps.map((step) => step.ownMs), ...proofs.map((measured) => measured.proofMs)];
  if (samples.length === 0) throw new RangeError("no farm step was timed in any path, so there is no distribution of one farm step");
  const first = foundSteps.filter((step) => step.index === 1);
  return {
    coldStart: {
      compile: summarize(coldStarts.map((start) => start.compileMs)),
      start: summarize(coldStarts.map((start) => start.startMs)),
      total: summarize(coldStarts.map((start) => start.totalMs)),
      firstSolve: summarize(coldStarts.map((start) => start.firstSolveMs)),
    },
    fullPool: {
      cases: matrixOk.length,
      failed: matrix.length - matrixOk.length,
      recordedInputs: countOf(matrixOk, (measured) => measured.pruneInput === "recorded"),
      notProven: countOf(matrixOk, (measured) => measured.status !== "optimal"),
      mismatches: countOf(matrixOk, (measured) => measured.fOk === false),
      prune: summarize(matrixOk.map((measured) => measured.pruneMs)),
      build: summarize(matrixOk.map((measured) => measured.buildMs)),
      solve: summarize(matrixOk.map((measured) => measured.solveMs)),
      total: summarize(matrixOk.map((measured) => measured.totalMs)),
    },
    upgrade: {
      cases: upgradeOk.length,
      failed: upgrade.length - upgradeOk.length,
      notProven: countOf(
        upgradeOk,
        (measured) => measured.stopped === "time" || (measured.equipStatus !== undefined && measured.equipStatus !== "optimal") || measured.steps.some((step) => step.status !== "optimal"),
      ),
      mismatches: countOf(upgradeOk, (measured) => measured.hasteOk === false || measured.equipFOk === false || measured.stepsOk === false),
      equipNow: summarize(upgradeOk.map((measured) => measured.equipMs)),
      path: summarize(upgradeOk.map((measured) => measured.pathMs)),
      stepsFound: summarize(upgradeOk.map((measured) => measured.stepsFound)),
      stopped: {
        limit: countOf(upgradeOk, (measured) => measured.stopped === "limit"),
        "no-gain": countOf(upgradeOk, (measured) => measured.stopped === "no-gain"),
        time: countOf(upgradeOk, (measured) => measured.stopped === "time"),
      },
    },
    farmStep: summarize(samples),
    farmStepSamples: { found: foundSteps.length, notFound: steps.length - foundSteps.length, proofs: proofs.length },
    firstStep: first.length === 0 ? null : summarize(first.map((step) => step.ownMs)),
  };
}

// ---- the command line ---------------------------------------------------------------------------------------------------------------

/** An option the script does not understand. */
export class UsageError extends Error {
  constructor(message) {
    super(message);
    this.name = "UsageError";
  }
}

/** Something the run needs that is not there (the fixtures, the port, the browser): nothing was measured. */
export class SetupError extends Error {
  constructor(message) {
    super(message);
    this.name = "SetupError";
  }
}

export const USAGE = `usage: node scripts/phone-bench.mjs [options]
  --throttle N   the CPU throttling rate of Chromium, 1 or more (default ${DEFAULT_OPTIONS.throttle})
  --port N       the port of the local server on 127.0.0.1 (default ${DEFAULT_OPTIONS.port})
  --matrix N     the number of matrix cases (default ${DEFAULT_OPTIONS.matrix}), spread evenly over the cases sorted by name
  --upgrade N    the number of upgrade cases (default ${DEFAULT_OPTIONS.upgrade}), spread the same way
  --json FILE    write every number and the summary to FILE
  --smoke        a quick check, not a measurement: ${SMOKE_OPTIONS.matrix} matrix cases, ${SMOKE_OPTIONS.upgrade} upgrade case with ${SMOKE_OPTIONS.steps} steps, throttle ${SMOKE_OPTIONS.throttle}
                 (an option given beside it wins)
  -h, --help     this text`;

const WHOLE = /^[0-9]+$/;
const DECIMAL = /^[0-9]+(\.[0-9]+)?$/;

function wholeNumber(option, text, least, most = Number.MAX_SAFE_INTEGER) {
  const value = WHOLE.test(text) ? Number(text) : Number.NaN;
  if (!(value >= least && value <= most)) throw new UsageError(`${option} is a whole number from ${least}${most === Number.MAX_SAFE_INTEGER ? "" : ` to ${most}`}, not ${JSON.stringify(text)}`);
  return value;
}

const PARSERS = {
  "--throttle": (text) => {
    const value = DECIMAL.test(text) ? Number(text) : Number.NaN;
    if (!(value >= 1)) throw new UsageError(`--throttle is a rate of 1 or more, not ${JSON.stringify(text)}`);
    return ["throttle", value];
  },
  "--port": (text) => ["port", wholeNumber("--port", text, 0, 65535)],
  "--matrix": (text) => ["matrix", wholeNumber("--matrix", text, 1)],
  "--upgrade": (text) => ["upgrade", wholeNumber("--upgrade", text, 1)],
  "--json": (text) => {
    if (text === "" || text.startsWith("--")) throw new UsageError(`--json is the name of a file, not ${JSON.stringify(text)}`);
    return ["json", text];
  },
};

/** The options of a command line, over the defaults (and over `--smoke`'s, which sit between). A UsageError for anything else. */
export function parseArgs(argv) {
  const given = {};
  let smoke = false;
  let help = false;
  for (let at = 0; at < argv.length; at += 1) {
    const arg = argv[at];
    if (arg === "--smoke") {
      smoke = true;
    } else if (arg === "-h" || arg === "--help") {
      help = true;
    } else if (Object.prototype.hasOwnProperty.call(PARSERS, arg)) {
      if (at + 1 >= argv.length) throw new UsageError(`${arg} needs a value`);
      at += 1;
      const [name, value] = PARSERS[arg](argv[at]);
      given[name] = value;
    } else {
      throw new UsageError(`unknown option ${JSON.stringify(arg)}`);
    }
  }
  return { ...DEFAULT_OPTIONS, ...(smoke ? SMOKE_OPTIONS : {}), ...given, smoke, help };
}

// ---- the report ---------------------------------------------------------------------------------------------------------------------------

const pad = (text, width) => String(text).padEnd(width);
const lpad = (text, width) => String(text).padStart(width);
/** Milliseconds to the digits that mean something: whole above 100, a tenth below. */
const shown = (value) => (value >= 100 ? value.toFixed(0) : value.toFixed(1));

/** The lines of the table on stdout: the run, the calibration, each distribution as median, 95th percentile and maximum, and the decision. */
export function formatReport({ environment, options, plan, calibration, summary, decision }) {
  const lines = [];
  lines.push(`phone-bench: ${environment.browser} on ${environment.platform}, CPU throttle ${options.throttle}x, highs-js ${environment.highs} (HiGHS ${environment.highsLibrary}), Node ${environment.node}`);
  lines.push(`fixtures ${environment.fixtures.release} (seed ${environment.fixtures.seed}): ${plan.matrix.length} of ${plan.matrixAll} matrix cases, ${plan.upgrade.length} of ${plan.upgradeAll} upgrade cases, up to ${options.steps} farm steps`);
  if (options.smoke) lines.push("SMOKE RUN: a check that everything works, not a measurement; the decision below means nothing.");
  const worker = calibration.workerRatio === null ? "not run" : `x${calibration.workerRatio.toFixed(2)}`;
  lines.push(
    `calibration (rate 1 -> ${calibration.rate}): JS loop x${calibration.loopRatio.toFixed(2)}, highs solve x${calibration.solveRatio.toFixed(2)} ` +
      `(the throttle works from x${calibration.floor.toFixed(2)}); dedicated worker loop ${worker}`,
  );
  lines.push("");
  lines.push(`${pad("milliseconds", 44)}${lpad("n", 4)}${lpad("median", 10)}${lpad("p95", 10)}${lpad("max", 10)}`);
  const row = (label, stat) => lines.push(`${pad(label, 44)}${lpad(stat.n, 4)}${lpad(shown(stat.median), 10)}${lpad(shown(stat.p95), 10)}${lpad(shown(stat.max), 10)}`);
  row("cold start: compile", summary.coldStart.compile);
  row("cold start: instantiate + init", summary.coldStart.start);
  row("cold start: total", summary.coldStart.total);
  row("cold start: then the first small solve", summary.coldStart.firstSolve);
  const { fullPool, upgrade } = summary;
  row("full pool: prune", fullPool.prune);
  row("full pool: build (setScenario)", fullPool.build);
  row("full pool: solve", fullPool.solve);
  row("full pool: total", fullPool.total);
  row("upgrade: Equip now", upgrade.equipNow);
  row("upgrade: whole farm path", upgrade.path);
  row("upgrade: one farm step (every Best-1 solve)", summary.farmStep);
  if (summary.firstStep !== null) row("upgrade: farm step 1", summary.firstStep);
  const stops = Object.entries(upgrade.stopped).map(([reason, count]) => `${reason} ${count}`).join(", ");
  lines.push("");
  lines.push(`full pool: ${fullPool.cases} cases, pruned from the recorded input in ${fullPool.recordedInputs} and from the already-pruned pool in ${fullPool.cases - fullPool.recordedInputs}`);
  lines.push(`upgrade: ${upgrade.cases} cases, steps found per path median ${upgrade.stepsFound.median} (max ${upgrade.stepsFound.max}); paths ended by: ${stops}`);
  const samples = summary.farmStepSamples;
  lines.push(`one farm step: ${summary.farmStep.n} samples (found steps ${samples.found}, steps not found ${samples.notFound}, proofs of no step ${samples.proofs})`);
  const trouble = [];
  if (fullPool.failed + upgrade.failed > 0) trouble.push(`${fullPool.failed + upgrade.failed} case(s) failed`);
  if (fullPool.mismatches + upgrade.mismatches > 0) trouble.push(`${fullPool.mismatches + upgrade.mismatches} case(s) did not end in the value Python recorded`);
  if (fullPool.notProven + upgrade.notProven > 0) trouble.push(`${fullPool.notProven + upgrade.notProven} case(s) ran out of time before a proof`);
  if (trouble.length > 0) lines.push(`WARNING: ${trouble.join("; ")}`);
  lines.push("");
  lines.push("decision");
  for (const line of formatDecision(decision)) lines.push(`  ${line}`);
  return lines;
}

// ---- the server and the bundle ----------------------------------------------------------------------------------------------------

const PAGE_HTML = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>phone bench</title></head><body><script type="module" src="/bench.js"></script></body></html>
`;

/**
 * A minimal HTTP server on 127.0.0.1: the page, the bundle, the highs WebAssembly, and the fixture documents by their path (`/fixture/matrix/matrix-001.json`,
 * whether the file is stored compressed or not). Nothing else is served, and nothing is cached by the browser.
 */
function startServer({ port, bundle, wasm, fixtures }) {
  const files = new Map([
    ["/", ["text/html; charset=utf-8", PAGE_HTML]],
    ["/bench.html", ["text/html; charset=utf-8", PAGE_HTML]],
    ["/bench.js", ["text/javascript; charset=utf-8", bundle]],
    ["/highs.wasm", ["application/wasm", wasm]],
  ]);
  const server = http.createServer((request, response) => {
    const send = (status, type, body) => {
      const data = Buffer.isBuffer(body) ? body : Buffer.from(body, "utf8");
      response.writeHead(status, { "content-type": type, "content-length": data.length, "cache-control": "no-store", "x-content-type-options": "nosniff" });
      response.end(request.method === "HEAD" ? undefined : data);
    };
    try {
      if (request.method !== "GET" && request.method !== "HEAD") return send(405, "text/plain", "method not allowed");
      const route = new URL(request.url, "http://127.0.0.1").pathname;
      if (files.has(route)) return send(200, ...files.get(route));
      if (route.startsWith("/fixture/")) {
        const name = decodeURIComponent(route.slice("/fixture/".length));
        return fixtures.has(name) ? send(200, "application/json; charset=utf-8", fixtures.text(name)) : send(404, "text/plain", "no such fixture");
      }
      return send(404, "text/plain", "not found");
    } catch (error) {
      return send(500, "text/plain", `server error: ${error.message}`);
    }
  });
  return new Promise((resolve, reject) => {
    server.once("error", (error) => reject(error.code === "EADDRINUSE" ? new SetupError(`port ${port} is in use (choose another with --port)`) : error));
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function stopServer(server) {
  return new Promise((resolve) => {
    server.close(() => resolve());
    server.closeAllConnections();
  });
}

/** Bundle the page's file with esbuild into `directory` (outside the repository), as the site bundles the engine; returns the bundle's bytes. */
export async function bundlePage(directory) {
  const { build } = await import("esbuild");
  const outfile = path.join(directory, "bench.js");
  await build({
    entryPoints: [PAGE_ENTRY],
    outfile,
    bundle: true,
    minify: true,
    charset: "utf8",
    legalComments: "none",
    format: "esm",
    target: BUNDLE_TARGET,
    external: ["node:module"], // the solver's loader asks for it only when it finds itself in Node, which a browser never is
    logLevel: "warning",
  });
  return fs.readFileSync(outfile);
}

// ---- the watchdog -----------------------------------------------------------------------------------------------------------------------

/** What a case may take beyond twice its budget before the run gives up on it. */
export const WATCHDOG_EXTRA_MS = 60_000;
/** The budget a cold start counts as having for the watchdog: it has no solver budget, and takes a fraction of a second (a few seconds under a heavy throttle). */
export const COLD_START_BUDGET_MS = 30_000;

/** How long a case whose calls each have the solver budget `budgetMs` may take before the run gives up on it: twice the budget, and a minute. */
export function watchdogLimit(budgetMs) {
  if (typeof budgetMs !== "number" || !Number.isFinite(budgetMs) || budgetMs < 0) throw new RangeError(`the budget is a number of milliseconds from 0, not ${String(budgetMs)}`);
  return 2 * budgetMs + WATCHDOG_EXTRA_MS;
}

/** A call into the page that did not return within its limit: `what` names it. */
export class WatchdogError extends Error {
  constructor(what, limitMs) {
    super(`${what} did not return within ${limitMs >= 1000 ? `${Math.round(limitMs / 1000)} s` : `${limitMs} ms`} (twice its budget and a minute)`);
    this.name = "WatchdogError";
    this.what = what;
    this.limitMs = limitMs;
  }
}

/**
 * The promise's own outcome if it settles within `limitMs`, else a WatchdogError that names `what`. The timer is cleared either way, and a failure of the
 * promise after the wait was given up is not left unhandled.
 */
export function withTimeout(promise, limitMs, what) {
  if (typeof limitMs !== "number" || !Number.isFinite(limitMs) || limitMs <= 0) throw new RangeError(`the limit is a number of milliseconds above 0, not ${String(limitMs)}`);
  let timer;
  const expired = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new WatchdogError(what, limitMs)), limitMs);
  });
  return Promise.race([promise, expired]).finally(() => clearTimeout(timer));
}

// ---- the measuring --------------------------------------------------------------------------------------------------------------------

const log = (text) => process.stderr.write(`${text}\n`);
const caseName = (name) => name.replace(/^.*\//, "").replace(/\.json$/, "");
const median = (values) => percentile(values, 50);
const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
/** The pause after the cold-start pages are closed (their processes shut down) and before the first case. */
const SETTLE_MS = 1000;
/** How long a close of a page or of the browser is waited for (what is being closed may be the thing that hung), and how long the process may take to end. */
const CLOSE_MS = 10_000;
const EXIT_GRACE_MS = 10_000;
/** Chromium's flags so that no page is slowed because another is in front of it (the usual ones for timing in a browser). */
const BROWSER_ARGS = ["--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"];

/** Wait for `promise` (a close) for `limitMs` at most, and never fail: the run goes on to close the rest. */
async function within(promise, limitMs = CLOSE_MS) {
  let timer;
  const gaveUp = new Promise((resolve) => {
    timer = setTimeout(resolve, limitMs);
  });
  try {
    await Promise.race([promise.catch(() => {}), gaveUp]);
  } finally {
    clearTimeout(timer);
  }
}

/** Throttle the page's main thread (the CDP command that DevTools' own CPU throttling sends). */
const throttle = (cdp, rate) => cdp.send("Emulation.setCPUThrottlingRate", { rate });

/** A page that reports what goes wrong in it, opened on the local server in a context of its own (so that nothing is shared with another page). */
async function openPage(browser, origin) {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on("pageerror", (error) => log(`  page error: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") log(`  page console error: ${message.text()}`);
  });
  await page.goto(`${origin}/bench.html`);
  if (!(await page.evaluate(() => typeof globalThis.phoneBench === "object"))) throw new Error("the bench page did not start (see the page errors above)");
  return { context, page, cdp: await context.newCDPSession(page) };
}

/** The ratios of the calibration, from the workload at rate 1 (`at1`) and at the chosen rate (`atRate`): the medians of each. */
function ratiosOf(at1, atRate) {
  return {
    loopRatio: median(atRate.loopMs) / median(at1.loopMs),
    solveRatio: median(atRate.solveMs) / median(at1.solveMs),
    workerRatio: at1.workerMs === null || atRate.workerMs === null ? null : median(atRate.workerMs) / median(at1.workerMs),
  };
}

/** The cold start, in a fresh page (and a fresh browser context) each time; each is added to `starts` as it is made. A cold start that hangs is a WatchdogError. */
async function measureColdStarts(browser, origin, rate, starts) {
  for (let at = 0; at < COLD_STARTS; at += 1) {
    const { context, page, cdp } = await openPage(browser, origin);
    try {
      await throttle(cdp, rate);
      const call = page.evaluate((url) => globalThis.phoneBench.coldStart(url), "/highs.wasm");
      const start = await withTimeout(call, watchdogLimit(COLD_START_BUDGET_MS), `cold start ${at + 1}`);
      starts.push(start);
      log(
        `cold start ${at + 1}/${COLD_STARTS}: compile ${shown(start.compileMs)} ms, instantiate + init ${shown(start.startMs)} ms (total ${shown(start.totalMs)} ms), ` +
          `then the first small solve ${shown(start.firstSolveMs)} ms`,
      );
    } finally {
      await within(context.close());
    }
  }
}

/**
 * Run each case in turn in the page, adding each result to `results` as it comes; a case that fails is kept as `{name, error}` and the run goes on. A case
 * that has not returned within the watchdog's limit is kept as `{name, error, hung: true}` and ends the run: it is thrown as a WatchdogError.
 */
async function measureCases(page, names, kind, request, describe, results) {
  const label = kind === "matrixCase" ? "matrix" : "upgrade";
  for (const [at, name] of names.entries()) {
    try {
      const call = page.evaluate(([method, casePath, options]) => globalThis.phoneBench[method](casePath, options), [kind, name, request]);
      const result = await withTimeout(call, watchdogLimit(request.budgetMs), `${label} case ${caseName(name)}`);
      results.push(result);
      log(`${label} ${at + 1}/${names.length} ${caseName(name)}: ${describe(result)}`);
    } catch (error) {
      if (error instanceof WatchdogError) {
        results.push({ name, error: error.message, hung: true });
        throw error;
      }
      if (page.isClosed()) throw error;
      results.push({ name, error: error.message });
      log(`${label} ${at + 1}/${names.length} ${caseName(name)}: FAILED ${error.message}`);
    }
  }
}

const describeMatrix = (r) =>
  `prune ${shown(r.pruneMs)} + build ${shown(r.buildMs)} + solve ${shown(r.solveMs)} = ${shown(r.totalMs)} ms (${r.status}, ${r.inputItems} -> ${r.keptItems} items${r.fOk ? "" : ", NOT the value Python recorded"})`;
const describeUpgrade = (r) =>
  `Equip now ${shown(r.equipMs)} ms, path ${shown(r.pathMs)} ms, ${r.stepsFound} steps [${r.steps.map((step) => shown(step.ownMs)).join(", ")}] ms, ` +
  `ended by ${r.stopped}${r.proofMs === null ? "" : ` (proof ${shown(r.proofMs)} ms)`}` +
  `${r.equipFOk && r.stepsOk && r.hasteOk ? "" : ", NOT the values Python recorded"}`;

function environmentOf(browser, set, wasm) {
  const processor = os.cpus()[0];
  return {
    browser: `Chromium ${browser.version()}`,
    platform: `${process.platform} ${process.arch}`,
    cpu: processor === undefined ? null : `${processor.model.trim()} x${os.cpus().length}`,
    node: process.version,
    highs: JSON.parse(fs.readFileSync(path.join(HIGHS_DIRECTORY, "package.json"), "utf8")).version,
    wasmBytes: wasm.length,
    wasmSha256: createHash("sha256").update(wasm).digest("hex"),
    fixtures: { release: set.manifest.data_release, rules: set.manifest.rules_version, seed: set.manifest.seed, scale: set.manifest.scale },
  };
}

/** The whole run; returns the exit code. */
export async function main(argv) {
  const options = parseArgs(argv);
  if (options.help) {
    console.log(USAGE);
    return 0;
  }
  if (!fs.existsSync(path.join(FIXTURES_DIRECTORY, "manifest.json"))) throw new SetupError(`build/fixtures is absent; make the full set with: ${MAKE_FULL}`);
  const set = new FixtureSet(FIXTURES_DIRECTORY, "the full set");
  const matrixAll = set.paths("case", "matrix/");
  const upgradeAll = set.paths("case", "upgrade/");
  const bundlePaths = set.paths("bundle");
  if (matrixAll.length === 0 || upgradeAll.length === 0 || bundlePaths.length === 0 || !set.has(PROFILES_PATH)) throw new SetupError("build/fixtures lacks the matrix or upgrade cases, or the bundles");
  const plan = { matrix: pickSpread(matrixAll, options.matrix), upgrade: pickSpread(upgradeAll, options.upgrade), matrixAll: matrixAll.length, upgradeAll: upgradeAll.length };

  if (options.json !== null) {
    try {
      fs.accessSync(path.dirname(path.resolve(options.json)), fs.constants.W_OK);
    } catch {
      throw new SetupError(`cannot write ${options.json}: its folder is not there or not writable`);
    }
  }
  const wasm = fs.readFileSync(path.join(HIGHS_DIRECTORY, "build", "highs.wasm"));
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "trioforge-phone-bench-"));
  let server = null;
  let browser = null;
  const cleanups = [];
  const cleanup = async () => {
    for (const step of cleanups.splice(0).reverse()) await step().catch(() => {});
  };
  cleanups.push(async () => fs.rmSync(work, { recursive: true, force: true }));
  process.once("SIGINT", () => cleanup().finally(() => process.exit(130)));

  // what has been measured, kept as it comes so that a run that is ended early can say what it has
  const measured = { coldStarts: [], matrix: [], upgrade: [] };
  let environment = null;
  let calibration = null;
  const measuredWith = Object.fromEntries(["throttle", "port", "matrix", "upgrade", "steps", "smoke"].map((name) => [name, options[name]]));
  const write = (document) => {
    if (options.json === null) return;
    fs.writeFileSync(options.json, `${JSON.stringify({ script: "scripts/phone-bench.mjs", ...document }, null, 1)}\n`);
    log(`wrote ${options.json}`);
  };
  try {
    const bundle = await bundlePage(work);
    server = await startServer({ port: options.port, bundle, wasm, fixtures: set });
    cleanups.push(() => stopServer(server));
    const origin = `http://127.0.0.1:${server.address().port}`;
    log(`serving on ${origin}`);

    let chromium;
    try {
      ({ chromium } = await import("@playwright/test"));
      browser = await chromium.launch({ args: BROWSER_ARGS });
    } catch (error) {
      throw new SetupError(`cannot start Chromium (${error.message.split("\n")[0]}); install it with: npx playwright install chromium`);
    }
    cleanups.push(() => within(browser.close(), 2 * CLOSE_MS));
    environment = environmentOf(browser, set, wasm);

    // 1. the calibration, in the page that goes on to measure the cases
    const { page, cdp } = await openPage(browser, origin);
    await page.evaluate((config) => globalThis.phoneBench.open(config), { wasmUrl: "/highs.wasm", bundlePaths, profilesPath: PROFILES_PATH });
    const run = (workloadOptions) => page.evaluate((given) => globalThis.phoneBench.workload(given), workloadOptions);
    await throttle(cdp, 1);
    await run({ reps: 2, worker: false }); // warms the solver and the loop up; not kept
    const at1 = await run({ reps: CALIBRATION_REPS, worker: true });
    await throttle(cdp, options.throttle);
    const atRate = await run({ reps: CALIBRATION_REPS, worker: true });
    const ratios = ratiosOf(at1, atRate);
    const verdict = calibrationVerdict({ rate: options.throttle, loopRatio: ratios.loopRatio, solveRatio: ratios.solveRatio });
    calibration = { ...verdict, workerRatio: ratios.workerRatio, at1, atRate };
    log(`calibration at rate ${options.throttle}: JS loop x${verdict.loopRatio.toFixed(2)}, highs solve x${verdict.solveRatio.toFixed(2)}, dedicated worker loop ${ratios.workerRatio === null ? "not run" : `x${ratios.workerRatio.toFixed(2)}`}`);
    if (!verdict.effective) {
      console.error(`phone-bench: ${describeVerdict(verdict)}`);
      return 2;
    }

    // 2. the cold start (fresh pages; the calibration page stays open and idle meanwhile)
    await measureColdStarts(browser, origin, options.throttle, measured.coldStarts);
    environment.highsLibrary = measured.coldStarts[0].version;

    // 3. and 4. the cases, at the rate, one after another
    await sleep(SETTLE_MS);
    await throttle(cdp, options.throttle);
    await measureCases(page, plan.matrix, "matrixCase", { budgetMs: BUDGET_MS }, describeMatrix, measured.matrix);
    await measureCases(page, plan.upgrade, "upgradeCase", { steps: options.steps, budgetMs: BUDGET_MS }, describeUpgrade, measured.upgrade);
    await throttle(cdp, 1);

    const summary = buildSummary(measured);
    const decision = decide(summary);
    console.log(formatReport({ environment, options, plan, calibration, summary, decision }).join("\n"));
    write({ environment, options: measuredWith, plan, calibration, summary, decision, ...measured });
    const problems = summary.fullPool.failed + summary.upgrade.failed + summary.fullPool.mismatches + summary.upgrade.mismatches + summary.fullPool.notProven + summary.upgrade.notProven;
    return problems > 0 ? 1 : 0;
  } catch (error) {
    // a call into the page that did not return: the run ends here, with what was measured before it
    if (!(error instanceof WatchdogError)) throw error;
    console.error(`phone-bench: ${error.message}; the run is ended here, and what was measured before it is kept`);
    write({
      environment,
      options: measuredWith,
      plan,
      calibration,
      summary: null,
      decision: null,
      ended: { reason: "watchdog", what: error.what, limitMs: error.limitMs },
      ...measured,
    });
    return 1;
  } finally {
    await cleanup();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const finish = (code) => {
    process.exitCode = code;
    // a browser that will not shut down must not keep the process waiting
    setTimeout(() => process.exit(code), EXIT_GRACE_MS).unref();
  };
  main(process.argv.slice(2)).then(finish, (error) => {
    console.error(`phone-bench: ${error.message}`);
    if (error instanceof UsageError) console.error(USAGE);
    finish(2);
  });
}
