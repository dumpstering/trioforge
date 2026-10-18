// The browser side of the phone gate (scripts/phone-bench.mjs): the engine's own functions, timed. The gate bundles this file with esbuild (as the site
// bundles the engine: target es2021 and Safari 15) and loads it in Chromium under CDP CPU throttling; the engine runs on the page's main thread, which is
// the thread the throttle slows (a dedicated worker is not slowed by it: the gate's calibration measures that and prints it).
//
//   coldStart({bytes, wasmHref})            -> {version, compileMs, startMs, totalMs, firstSolveMs}: from the WebAssembly bytes in memory to a started HiGHS
//   workload(highs, {reps, worker})         -> {loopMs, solveMs, workerMs}: the fixed workload of the calibration, `reps` times
//   createRunner({highs, read, bundlePaths, profilesPath}) -> {matrixCase(path, {budgetMs}), upgradeCase(path, {steps, budgetMs})}
//
// The runner sets a case up the way the engine's parity tests do (tests-js/engine-cases.mjs, engine-prune.test.mjs, engine-solve-parity.test.mjs and
// engine-path.test.mjs): the profile, the buff set, the Monk bins and the items of a fixture case, then a session of solve.js. What is timed is the engine's
// work alone, in one synchronous stretch (nothing is awaited inside it); reading the fixture and setting the case up are not timed. The answers are held
// to the values Python recorded (`fOk`, `equipFOk`, `stepsOk`), so that a case that is set up wrongly shows instead of being timed.
//
// In a page this file puts `phoneBench` on the global object; in Node (the tests import it) it does not.

import loadHighs from "highs";
import { SOLVER_OPTIONS, toModelData } from "../pipeline/trioforge/site/static/engine/highs-data.js";
import { atTier } from "../pipeline/trioforge/site/static/engine/items.js";
import { equipNow, farmPath, sessionHaste } from "../pipeline/trioforge/site/static/engine/path.js";
import { readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { prune } from "../pipeline/trioforge/site/static/engine/prune.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { closeSession, createSession, setScenario, solve } from "../pipeline/trioforge/site/static/engine/solve.js";

/** How close the value of an answer must be to the value Python recorded (relative, as the parity tests hold it). */
const VALUE_TOLERANCE = 1e-9;
const MAIN = "main";
/** The name path.js gives the Best-1 model that the farm path keeps in the session (the scenario of every step, and of the solve that proves there is none). */
const BEST_1 = "best-1";
const ms = () => performance.now();

// ---- starting the solver --------------------------------------------------------------------------------------------------------------

/**
 * HiGHS started from a compiled module, as the engine's worker starts it (worker.js): the loader is given the module through the Emscripten hook
 * `instantiateWasm`, and a module that does not instantiate makes this reject instead of leaving it waiting.
 */
export function startHighs(compiled, wasmHref) {
  let stop;
  const stopped = new Promise((_, reject) => {
    stop = reject;
  });
  stopped.catch(() => {});
  const starting = loadHighs({
    locateFile: () => wasmHref,
    instantiateWasm(imports, done) {
      WebAssembly.instantiate(compiled, imports)
        .then((instance) => {
          done(instance);
        })
        .catch(stop);
      return {};
    },
  });
  starting.catch(() => {});
  return Promise.race([starting, stopped]);
}

/**
 * The cold start: from the WebAssembly bytes already in memory (the download is not counted) to a solver that is ready, in two parts: the compiling
 * (`compileMs`), and the instantiating and the initializing of HiGHS (`startMs`). After the clock has stopped it reads the version and times the first
 * solve (`firstSolveMs`, the small program of the calibration): V8 compiles the functions of a WebAssembly module when they are first called, so the
 * time to a started solver leaves out a cost that the first solve of a fresh page pays, and this shows how much (compare the warm solves of the calibration).
 */
export async function coldStart({ bytes, wasmHref }) {
  const began = ms();
  const compiled = await WebAssembly.compile(bytes);
  const compiledAt = ms();
  const highs = await startHighs(compiled, wasmHref);
  const readyAt = ms();
  const version = highs.version.string;
  const objective = smallSolve(highs);
  const solvedAt = ms();
  if (Math.abs(objective - CALIBRATION_OBJECTIVE) > 1e-6) throw new Error(`the small program of the calibration found ${objective}, not ${CALIBRATION_OBJECTIVE}`);
  return { version, compileMs: compiledAt - began, startMs: readyAt - compiledAt, totalMs: readyAt - began, firstSolveMs: solvedAt - readyAt };
}

// ---- the calibration workload ---------------------------------------------------------------------------------------------------------

/** The iterations of the loop: about a tenth of a second on a desktop. */
const LOOP_ITERATIONS = 30_000_000;

/** A loop of integer arithmetic that does nothing else: the pure-JavaScript half of the workload (it has no reference to anything outside itself). */
export function jsLoop(n) {
  let x = 1;
  let s = 0;
  for (let i = 0; i < n; i += 1) {
    x = (Math.imul(x, 1664525) + 1013904223) | 0;
    s = (s + (x >>> 8)) % 1000003;
  }
  return s;
}

/** A seeded generator, so that the small program is the same on every machine. */
function lcg(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

/** A knapsack of 35 items and 2 rows with profits that follow the weights: a small program that HiGHS needs some nine hundred nodes for. */
function calibrationModel() {
  const items = 35;
  const rows = 2;
  const random = lcg(1);
  const weights = Array.from({ length: rows }, () => Array.from({ length: items }, () => 10 + Math.floor(random() * 90)));
  const start = [0];
  const index = [];
  const value = [];
  for (const row of weights) {
    row.forEach((weight, column) => {
      index.push(column);
      value.push(weight);
    });
    start.push(index.length);
  }
  return {
    sense: "max",
    c: weights[0].map((weight) => Math.round(weight + 50 + random() * 10)),
    col_lb: new Array(items).fill(0),
    col_ub: new Array(items).fill(1),
    row_lb: new Array(rows).fill(null),
    row_ub: weights.map((row) => Math.floor(row.reduce((sum, weight) => sum + weight, 0) / 2)),
    A: { start, index, value },
    integrality: new Array(items).fill(1),
  };
}

const CALIBRATION_MODEL = calibrationModel();
/** What the small program is worth (its optimum, which every run must find: the workload is the same each time). */
export const CALIBRATION_OBJECTIVE = 2133;

/** Solve the small program with the engine's options and return its objective; the second half of the workload. */
export function smallSolve(highs) {
  const solver = highs.createModel(toModelData(highs, CALIBRATION_MODEL));
  try {
    solver.options.set(SOLVER_OPTIONS);
    solver.options.set("time_limit", 120);
    const outcome = solver.run();
    if (outcome.modelStatus !== highs.constants.modelStatus.optimal) throw new Error("the small program of the calibration did not solve to its optimum");
    return solver.getObjectiveValue();
  } finally {
    solver.dispose();
  }
}

/** The loop run `reps` times in a dedicated worker (timed inside it): whether the throttle slows a worker too. Null where there are no workers. */
async function workerLoop(reps) {
  if (typeof Worker !== "function" || typeof Blob !== "function" || typeof URL.createObjectURL !== "function") return null;
  const source =
    `const loop = ${jsLoop.toString()};` +
    "onmessage = (event) => { const { reps, n } = event.data; loop(n / 10); const times = [];" +
    " for (let rep = 0; rep < reps; rep += 1) { const began = performance.now(); loop(n); times.push(performance.now() - began); }" +
    " postMessage(times); };";
  const url = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
  const worker = new Worker(url);
  try {
    return await new Promise((resolve, reject) => {
      worker.onmessage = (event) => resolve(event.data);
      worker.onerror = (event) => reject(new Error(`the calibration worker failed: ${event.message}`));
      worker.postMessage({ reps, n: LOOP_ITERATIONS });
    });
  } finally {
    worker.terminate();
    URL.revokeObjectURL(url);
  }
}

/**
 * The calibration workload, `reps` times: the loop and the small solve on this thread (`loopMs`, `solveMs`), and with `worker` the loop in a dedicated worker
 * (`workerMs`; null without). The gate runs it at rate 1 and at the rate it measures at, and compares the medians.
 */
export async function workload(highs, { reps = 3, worker = true } = {}) {
  const loopMs = [];
  const solveMs = [];
  let sink = 0;
  for (let rep = 0; rep < reps; rep += 1) {
    const loopBegan = ms();
    sink += jsLoop(LOOP_ITERATIONS);
    loopMs.push(ms() - loopBegan);
    const solveBegan = ms();
    const objective = smallSolve(highs);
    solveMs.push(ms() - solveBegan);
    if (Math.abs(objective - CALIBRATION_OBJECTIVE) > 1e-6) throw new Error(`the small program of the calibration found ${objective}, not ${CALIBRATION_OBJECTIVE}`);
  }
  // (`checksum` is there so that the loop's result is used, and nothing can drop the loop)
  return { loopMs, solveMs, workerMs: worker ? await workerLoop(reps) : null, checksum: sink };
}

// ---- a case of the fixtures --------------------------------------------------------------------------------------------------------

const clone = (value) => JSON.parse(JSON.stringify(value));

/** A copy that nothing can change, all through (the parity tests hand the engine such copies, so that it can only read what it is given). */
function deepFreeze(value) {
  const stack = [value];
  while (stack.length > 0) {
    const node = stack.pop();
    if (node === null || typeof node !== "object" || Object.isFrozen(node)) continue;
    Object.freeze(node);
    for (const child of Array.isArray(node) ? node : Object.values(node)) stack.push(child);
  }
  return value;
}

/** What the cases of a set share: the bundle of each level (the rules of the tiers) and the Monk bins of each level (`caseOf` of tests-js/engine-cases.mjs). */
async function sharedOf(read, bundlePaths, profilesPath) {
  const rules = new Map();
  for (const path of bundlePaths) {
    const bundle = readBundle(await read(path));
    if (!rules.has(bundle.level)) rules.set(bundle.level, bundle);
  }
  if (rules.size === 0) throw new Error("the fixtures have no bundle of the rules of the tiers");
  const profiles = await read(profilesPath);
  return { rules, bins: profiles.monk_bins };
}

/** The inputs of a case as the engine takes them, and the items of its pools (each read once): `caseOf` of tests-js/engine-cases.mjs. */
function caseOf(shared, doc) {
  const { inputs } = doc;
  const profile = deepFreeze(clone(inputs.profile));
  const records = new Map(doc.records.map((record) => [record.key ?? `w${record.id}`, record]));
  const rules = shared.rules.get(inputs.level) ?? [...shared.rules.values()][0];
  const items = new Map();
  const itemNamed = (name) => {
    if (!items.has(name)) {
      const at = name.lastIndexOf("@");
      items.set(name, atTier(records.get(name.slice(0, at)), Number(name.slice(at + 1)), rules, { weaponPct: inputs.weapon_pct }));
    }
    return items.get(name);
  };
  const bins = profile.monk === null ? undefined : deepFreeze(clone(shared.bins[String(inputs.level)]));
  return {
    profile,
    setup: inputs.setup,
    buffset: inputs.buffset === null ? null : deepFreeze(clone(inputs.buffset)),
    bins,
    itemNamed,
    /** The options of a recorded solve or pruning, with the Monk bins the builder reads from the bundle. */
    withBins: (options) => deepFreeze({ ...clone(options), ...(bins === undefined ? {} : { monk_bins: bins }) }),
    poolOf: (solved) => solved.pool.map(itemNamed),
    owned: () => (inputs.owned ?? []).map(([name, count]) => [itemNamed(name), count]),
    candidates: () => (inputs.candidates ?? []).map(itemNamed),
  };
}

/** Whether a value is the exact value that Python recorded (a "p/q" text), within the tolerance of the parity tests. */
function isRecordedValue(got, recorded) {
  if (got === null || got === undefined) return false;
  const want = Rational.parseLong(recorded).toNumber();
  return Math.abs(got.toNumber() - want) / Math.max(1, Math.abs(want)) <= VALUE_TOLERANCE;
}

/**
 * Whether the farm path is the one Python recorded (`expected`), as far as the `asked` steps go: every recorded step up to `asked` was found, in order, with
 * the recorded value (`found` is the steps found, in order); and when the recording ended because no step was left ("no-gain") after fewer steps than were
 * asked, this path ended the same way after the same number of steps. A recording that ended at its own limit (it asked for fewer steps than this run, as
 * the fixtures' three do) says nothing about the steps beyond it.
 */
function agreesWithRecording(expected, found, stopped, asked) {
  const recorded = expected.steps;
  for (let at = 0; at < Math.min(recorded.length, asked); at += 1) {
    if (found[at] === undefined || !isRecordedValue(found[at].F, recorded[at].F)) return false;
  }
  if (expected.stopped === "no-gain" && recorded.length < asked) return stopped === "no-gain" && found.length === recorded.length;
  return true;
}

/** The last solution of the Best-1 model in a session: null while there is none (the farm path makes the model when its first step reaches the solver). */
const lastSolution = (session) => session.scenarios.get(BEST_1)?.last ?? null;

/** The one tier that every item of a pool is at, or null for no item or for several tiers (what `prune` takes for its tier). */
function commonTier(items) {
  const tiers = new Set(items.map((item) => item.tier));
  return tiers.size === 1 ? [...tiers][0] : null;
}

/**
 * The measuring functions over a set of fixture documents. `read(path)` gives the parsed document of a path (`matrix/matrix-001.json`: the path without
 * `.gz`), `bundlePaths` are the paths of the bundles, `profilesPath` that of the profiles with the Monk bins.
 */
export async function createRunner({ highs, read, bundlePaths, profilesPath }) {
  const shared = await sharedOf(read, bundlePaths, profilesPath);

  return {
    /**
     * A full-pool solve of a matrix case, placement only (`canonical: false`): the pool is pruned (`prune`), its model is built and put in the solver
     * (`setScenario`) and solved (`solve`). The case records the whole input of its pruning only sometimes (`pruneInput` "recorded": the pool before
     * Python pruned it); otherwise the pool of the solve, which Python had already pruned, is what is pruned here (`pruneInput` "pool"), and `pruneMs`
     * is then less than the pruning of the whole input would take.
     */
    async matrixCase(path, { budgetMs }) {
      const doc = await read(path);
      const c = caseOf(shared, doc);
      const recorded = doc.solves[0];
      const recording = recorded.prune;
      const input = recording === null ? c.poolOf(recorded) : recording.input.map(c.itemNamed);
      const tier = recording === null ? commonTier(input) : recording.tier;
      const pruneOptions = c.withBins(recording === null ? recorded.options : recording.options);
      const owned = recording === null ? [] : recording.owned;
      const solveOptions = deepFreeze(clone(recorded.options));
      const session = createSession({ highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins });
      try {
        const began = ms();
        const kept = prune(input, c.profile, tier, c.setup, c.buffset, pruneOptions, owned);
        const pruned = ms();
        const built = setScenario(session, MAIN, kept, solveOptions);
        const loaded = ms();
        const answer = solve(session, { scenario: MAIN, budgetMs, canonical: false });
        const solved = ms();
        return {
          name: path,
          id: doc.id,
          label: doc.label,
          setup: c.setup,
          tier,
          pruneInput: recording === null ? "pool" : "recorded",
          inputItems: input.length,
          keptItems: kept.length,
          columns: built.columns,
          rows: built.rows,
          pruneMs: pruned - began,
          buildMs: loaded - pruned,
          builderMs: built.buildMs,
          syncMs: built.syncMs,
          solveMs: solved - loaded,
          totalMs: solved - began,
          status: answer.status,
          proven: answer.proven,
          nodes: answer.nodes,
          tieMs: answer.timings.tieMs,
          F: answer.F === null ? null : answer.F.toString(),
          fOk: isRecordedValue(answer.F, recorded.result.F),
        };
      } finally {
        closeSession(session);
      }
    },

    /**
     * The Upgrade functions on an Upgrade case: Equip now alone (`equipMs`, on a session of its own, the assumed haste fixed at the session's as the farm
     * path fixes it), then the farm path (`pathMs`) asking for `steps` steps, each step as `onStep` is told it: `ownMs` is the step's own time that the
     * engine reports (`timings.totalMs`: its plan, pruning, model and solve), `arrivalMs` the moment it was told, counted from the start of the call (so
     * the first step's includes Equip now, which the path runs first). `tailMs` is what the call took after the last step was told.
     *
     * A user also waits for the solve that proves no step is left, when the path ends by itself ("no-gain"). The engine does not report that solve's time
     * (`farmPath` tells `onStep` the steps it makes and nothing of the solve that makes none), so `proofMs` is the tail: `tailMs`, or when the path made no
     * step the whole call less the time of Equip now, which the engine reports. It is null when the path did not end by itself, and when it ended by
     * itself without a solve: a path that has no candidate left to add stops before it builds a model, and then the tail is bookkeeping. Whether a solve
     * ran after the last step is read from the session: the Best-1 model has a new last solution (solve.js keeps it as `last`).
     *
     * Every step is held to Python's recording (`stepsOk`, see `agreesWithRecording`), and each step keeps its exact value (`F`), the recorded one
     * (`recordedF`) and whether they agree (`fOk`: null where nothing is recorded), with the item and the recorded item.
     */
    async upgradeCase(path, { steps, budgetMs }) {
      const doc = await read(path);
      const c = caseOf(shared, doc);
      const { expected } = doc;
      const anyRule = doc.solves[0].options.any_rule;
      const owned = c.owned();
      const candidates = c.candidates();
      const haste = sessionHaste(c.profile, owned, candidates, c.setup, c.buffset, { any_rule: anyRule });
      const sessionWith = (options) => createSession({ highs, profile: c.profile, setup: c.setup, buffset: c.buffset, monkBins: c.bins, options });

      let equip;
      let equipMs;
      const alone = sessionWith({ any_rule: anyRule, haste_assumed: haste });
      try {
        const began = ms();
        equip = equipNow(alone, owned, { budgetMs, canonical: false });
        equipMs = ms() - began;
      } finally {
        closeSession(alone);
      }

      const session = sessionWith({ any_rule: anyRule });
      try {
        const arrivals = [];
        let lastAtStep = null;
        const began = ms();
        const result = farmPath(session, owned, candidates, {
          steps,
          budgetMs,
          canonical: false,
          onStep: () => {
            arrivals.push(ms() - began);
            lastAtStep = lastSolution(session);
          },
        });
        const pathMs = ms() - began;
        const recorded = expected.steps;
        const made = result.steps.map((step, at) => ({
          index: step.index,
          found: step.found,
          kind: step.kind,
          status: step.status,
          item: step.item === null ? null : `${step.item.key}@${step.item.tier}`,
          recordedItem: recorded[at] === undefined ? null : recorded[at].item,
          F: step.F === null ? null : step.F.toString(),
          recordedF: recorded[at] === undefined ? null : recorded[at].F,
          fOk: recorded[at] === undefined ? null : step.found && isRecordedValue(step.F, recorded[at].F),
          ownMs: step.timings.totalMs,
          pruneMs: step.timings.pruneMs,
          buildMs: step.timings.buildMs,
          syncMs: step.timings.syncMs,
          solveMs: step.timings.solveMs,
          tieMs: step.timings.tieMs,
          poolSize: step.poolSize,
          reused: step.reused,
          arrivalMs: arrivals[at],
        }));
        const found = result.steps.filter((step) => step.found);
        const lastArrival = arrivals.length === 0 ? null : arrivals[arrivals.length - 1];
        const baselineMs = result.baseline === null ? 0 : result.baseline.build.buildMs + result.baseline.build.syncMs + result.baseline.elapsedMs;
        const proved = result.stopped === "no-gain" && lastSolution(session) !== lastAtStep;
        return {
          name: path,
          id: doc.id,
          label: doc.label,
          owned: owned.length,
          candidates: candidates.length,
          hasteOk: haste === expected.session_haste && (result.hasteAssumed === null || result.hasteAssumed === haste),
          equipMs,
          equipStatus: equip.status,
          equipTieMs: equip.timings.tieMs,
          equipFOk: isRecordedValue(equip.F, doc.solves[expected.equip_now].result.F),
          pathMs,
          stopped: result.stopped,
          stepsFound: found.length,
          steps: made,
          tailMs: pathMs - (lastArrival ?? 0),
          proofMs: proved ? Math.max(0, pathMs - (lastArrival ?? baselineMs)) : null,
          recorded: { steps: recorded.length, stopped: expected.stopped },
          stepsOk: agreesWithRecording(expected, found, result.stopped, steps),
        };
      } finally {
        closeSession(session);
      }
    },
  };
}

// ---- the page --------------------------------------------------------------------------------------------------------------------------

if (typeof document !== "undefined") {
  let highs = null;
  let runner = null;
  const fetchBytes = async (url) => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url}: ${response.status}`);
    return new Uint8Array(await response.arrayBuffer());
  };
  const readFixture = async (path) => {
    const response = await fetch(`/fixture/${path}`);
    if (!response.ok) throw new Error(`the fixture ${path} could not be read (${response.status})`);
    return response.json();
  };
  const ready = () => {
    if (highs === null || runner === null) throw new Error("the page is not open yet");
  };
  globalThis.phoneBench = {
    /** In a fresh page: fetch the WebAssembly (not timed), then time the cold start. */
    async coldStart(wasmUrl) {
      const wasmHref = new URL(wasmUrl, location.href).href;
      return coldStart({ bytes: await fetchBytes(wasmHref), wasmHref });
    },
    /** Start the solver (not timed) and read what the cases share. */
    async open({ wasmUrl, bundlePaths, profilesPath }) {
      const wasmHref = new URL(wasmUrl, location.href).href;
      highs = await startHighs(await WebAssembly.compile(await fetchBytes(wasmHref)), wasmHref);
      runner = await createRunner({ highs, read: readFixture, bundlePaths, profilesPath });
      return { version: highs.version.string };
    },
    async workload(options) {
      ready();
      return workload(highs, options);
    },
    async matrixCase(path, options) {
      ready();
      return runner.matrixCase(path, options);
    },
    async upgradeCase(path, options) {
      ready();
      return runner.upgradeCase(path, options);
    },
  };
}
