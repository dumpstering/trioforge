// The solver worker: HiGHS (the solver of the Python side, built for the browser) in a module Web Worker.
//
// The page starts this file as a module worker, through the Trusted Types policy of tt-policy.js, and talks to it with the
// messages of protocol.js. The worker
//   * reads the build's manifest itself and works out the path of the WebAssembly from it (no request or message carries an address);
//   * downloads the WebAssembly (checking its type, its size and its SHA-256 against the manifest, and reporting how far it is), compiles it
//     only if all three are right, and hands the compiled module back to the page, which keeps it: if this worker has to be stopped, the next
//     one is given the module and does not download or compile anything. It says in `ready` which file it checked (its SHA-256), and the page
//     compares that with its own manifest: a release between the page's read of the manifest and the worker's is seen, not run;
//   * solves models in the JSON v1 shape with the same determinism options as the Python solver, inside the time it was given, and
//     says honestly when the best answer found is not proven optimal.
//
// highs-js 1.15.3 accepts a `wasmModule` option in its documentation but its loader does not read it; the Emscripten hook
// `instantiateWasm` is what is used here to give it a module that is already compiled.
//
// The warm-up. Right after HiGHS starts, and before the worker says it is ready, it solves one small built-in program with integer columns that needs
// branching (`warmUpModel`), with the options of every real solve. The solver's branch and bound is compiled by the browser when it first runs (the phone
// gate found about four seconds of that on the first real solve under a six-fold throttle, 0.4 s without one), so the first real request would pay for it
// after the visitor has asked; this way the start pays, under the loading panel. The answer is known: a warm-up that fails, or does not find it, is a start that
// failed (engine-load), and a solver that does not do what it should is not used.
//
// Scenario requests are checked against the manifest and answered by the scenario engine (scenario.js), in this worker, from the data the manifest lists (the item table and the
// bundle of the trio, fetched on the first request for a trio, checked and kept). The five modes are Equip now (the best kit from the items a visitor owns), the farm path
// (Equip now and then the best addition, one step at a time), the best sets (the best kit when two or three additions are made at once), Every slot (the swaps of each place, among the candidates and the items the visitor owns)
// and the best kit (the best kit of a view over its whole pool at a tier, with the weights of the request).
// The farm path streams: Equip now and each step are sent to the page as `step` messages the moment they are made, and the final result follows. Between two steps the worker
// yields to the event loop (a macrotask), so that a `stop` from the page is seen: a stop is handled at once, not behind the queue of requests. If it names the farm path in
// flight, that path ends before the next step the worker begins after it has seen the stop, with its final result (`stopped`: "stopped"); the step being worked out when the stop
// arrives is finished and sent. In a browser a stop that the page sent from the callback of a step message can be delivered after the worker has yielded and looked, so the path can
// end one step later than the step the page was looking at (tests that deliver messages as microtasks see it end exactly there). A stop for any other id, or for a request of
// another mode, is ignored, and there is no reply to a stop. A fault in a step ends the path with the error code that fault has for any scenario (solver, engine-load, bad-request, internal), and the steps sent before
// it stand. The budget of every mode is counted from the moment the data is in, and a farm path's is the whole path's.

import loadHighs from "highs";
import { EngineFault, WASM_FILE, fetchBytes, sameOriginUrl, sha256Hex } from "./download.js";
import { SOLVER_OPTIONS, toModelData } from "./highs-data.js";
import { MANIFEST_PATH, fetchTextWithin, parseManifest } from "./manifest.js";
import { EvaluateError } from "./evaluate.js";
import { PathError } from "./path.js";
import { BundleError } from "./profile.js";
import {
  BEST_KIT,
  BEST_SETS,
  EQUIP_NOW,
  ERROR_CODES,
  EVERY_SLOT,
  FARM_PATH,
  LABEL_NO_INCUMBENT,
  LABEL_TIME_LIMIT,
  LIMITS,
  PROTOCOL_VERSION,
  ProtocolError,
  STARTUP_COMPILE_MS,
  STARTUP_STALL_MS,
  checkAgainstManifest,
  isPlainObject,
  validateToWorker,
} from "./protocol.js";
import { PruneError } from "./prune.js";
import { createScenarioEngine } from "./scenario.js";
import { ExactnessError, PlacementError, SolveError, SolverFault } from "./solve.js";
import { TierError } from "./tiers.js";

// the options and the model document are in highs-data.js (a leaf, so that solve.js need not import this file); they are exported from here as well
export { SOLVER_OPTIONS, toModelData };

const nowMs = () => performance.now();

/** A short, plain, one-line description of an error, for the page to show; never the stack and never markup. */
export function describe(error) {
  const raw = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  let text = "";
  for (let i = 0; i < raw.length && text.length < LIMITS.maxMessageLength; i += 1) {
    const code = raw.charCodeAt(i);
    text += code < 0x20 || code > 0x7e ? " " : raw[i];
  }
  text = text.trim();
  return text.length > 0 ? text : "The optimizer failed.";
}

// (EngineFault, the address of a file of this site, the SHA-256 and the fetching of a file in pieces are in download.js: the data of scenarios is fetched the same way)
export { EngineFault };

// ---- loading the engine ---------------------------------------------------------------------------------------------------------

/**
 * Download the WebAssembly (see fetchBytes), check its SHA-256 against the manifest (before a single byte of it is compiled), and compile it.
 * `file` is the manifest's entry: `{path, bytes, gzip, sha256}`.
 */
async function downloadAndCompile(url, file, fetchImpl, onProgress, stallMs, bodyMs) {
  const bytes = await fetchBytes(url, file.bytes, fetchImpl, onProgress, stallMs, bodyMs, WASM_FILE);
  onProgress({ phase: "loading", loaded: file.bytes, total: file.bytes });
  // The file has the right type and size; it is the right file only if its digest is the one the manifest lists. Nothing is compiled before that.
  if ((await sha256Hex(bytes)) !== file.sha256) throw new EngineFault("engine-load", "The optimizer file is not the one the site lists (its checksum differs).");
  onProgress({ phase: "compiling" });
  return WebAssembly.compile(bytes);
}

/** Start HiGHS from a compiled module. A module that cannot be started makes this reject; it never leaves it waiting. */
function startHighs(compiled, wasmUrl) {
  let stop;
  const stopped = new Promise((_, reject) => {
    stop = reject;
  });
  stopped.catch(() => {});
  const starting = loadHighs({
    locateFile: () => wasmUrl.href,
    instantiateWasm(imports, done) {
      // a module that does not instantiate, and a solver that fails while it takes the instance, both end up in `stop`
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
 * Load the engine: the compiled module (given, or downloaded, checked and compiled here), HiGHS started from it and the warm-up solved (see the head of this
 * file; a failure of it rejects with engine-load). Returns `{version, module, wasm, warmUpMs, solveModel, equipNow}`; `module` is set only when this call
 * compiled one, which is then the page's to keep, `wasm` is the SHA-256 of the file it was made from (set whenever a file was downloaded, so that the page can
 * see which file this worker loaded) and `warmUpMs` the milliseconds the warm-up took.
 * `equipNow`, `farmPath`, `bestSets`, `everySlot` and `bestKit` `(request, {manifest, startedAt, now, onProgress, ...})` answer a scenario request of the mode (scenario.js), fetching the data they
 * need through the same `fetchImpl`, from the manifest's paths.
 */
export async function loadHighsEngine({
  manifest,
  module,
  fetchImpl = (...args) => fetch(...args),
  baseUrl = import.meta.url,
  onProgress = () => {},
  stallMs = STARTUP_STALL_MS,
  bodyMs = STARTUP_COMPILE_MS,
}) {
  const wasmUrl = sameOriginUrl(manifest.wasm.path, baseUrl);
  let compiled = module;
  let fresh;
  if (compiled === undefined) {
    compiled = await downloadAndCompile(wasmUrl, manifest.wasm, fetchImpl, onProgress, stallMs, bodyMs);
    fresh = compiled;
  }
  onProgress({ phase: "starting" });
  const highs = await startHighs(compiled, wasmUrl);
  const warmUpMs = warmUp(highs);
  const scenarios = createScenarioEngine({ highs, fetchImpl, baseUrl, stallMs, bodyMs });
  return {
    version: highs.version.string,
    module: fresh,
    wasm: fresh === undefined ? undefined : manifest.wasm.sha256,
    warmUpMs,
    solveModel: async (model, options) => solveModelWith(highs, model, options),
    equipNow: (request, options) => scenarios.equipNow(request, options),
    farmPath: (request, options) => scenarios.farmPath(request, options),
    bestSets: (request, options) => scenarios.bestSets(request, options),
    everySlot: (request, options) => scenarios.everySlot(request, options),
    bestKit: (request, options) => scenarios.bestKit(request, options),
  };
}

// ---- the warm-up ----------------------------------------------------------------------------------------------------------------

/** What the warm-up program is made of and what its optimum is: forty yes/no columns, five knapsack rows, and some thirty nodes of branching. */
const WARM_UP = Object.freeze({ seed: 5, columns: 40, rows: 5, fill: 0.4, optimum: 1527 });
/** The most time the warm-up may take: a slow phone does it in some seconds, and the start as a whole has the minute of STARTUP_COMPILE_MS. */
const WARM_UP_BUDGET_MS = 30_000;
const WARM_UP_TOLERANCE = 1e-6;

/**
 * The program of the warm-up as a complete model JSON v1: a knapsack with forty yes/no columns and five rows whose numbers come from a small generator with a
 * fixed seed (so that it is the same everywhere, and needs no list of numbers), and an optimum of 1527 that needs the solver to branch.
 */
export function warmUpModel() {
  let state = WARM_UP.seed;
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
  const whole = (low, high) => low + Math.floor(random() * (high - low + 1));
  const { columns, rows, fill } = WARM_UP;
  const start = [0];
  const index = [];
  const value = [];
  const upper = [];
  for (let row = 0; row < rows; row += 1) {
    let total = 0;
    for (let column = 0; column < columns; column += 1) {
      const weight = whole(10, 99);
      total += weight;
      index.push(column);
      value.push(weight);
    }
    upper.push(Math.floor(total * fill));
    start.push(index.length);
  }
  return {
    version: 1,
    sense: "max",
    const: 0,
    col_names: Array.from({ length: columns }, (_, column) => `x${column}`),
    col_lb: new Array(columns).fill(0),
    col_ub: new Array(columns).fill(1),
    integrality: new Array(columns).fill(1),
    c: Array.from({ length: columns }, () => whole(20, 120)),
    row_names: Array.from({ length: rows }, (_, row) => `limit${row}`),
    row_lb: new Array(rows).fill(null),
    row_ub: upper,
    A: { start, index, value },
    item_cols: [],
    buff_cols: [],
    info: {},
  };
}

/**
 * Solve the warm-up program on a started solver, with the options of every real solve, and return the milliseconds it took. An EngineFault (engine-load) when
 * it cannot be solved, is not solved to the end, or has another answer than its known optimum.
 */
export function warmUp(highs, { now = nowMs } = {}) {
  const began = now();
  let outcome;
  try {
    outcome = solveModelWith(highs, warmUpModel(), { budgetMs: WARM_UP_BUDGET_MS, startedAt: began, now });
  } catch (error) {
    throw new EngineFault("engine-load", `The optimizer's check run failed: ${describe(error)}`);
  }
  if (outcome.status !== "optimal") throw new EngineFault("engine-load", "The optimizer's check run did not finish.");
  if (outcome.objective === null || Math.abs(outcome.objective - WARM_UP.optimum) > WARM_UP_TOLERANCE) throw new EngineFault("engine-load", "The optimizer's check run gave a wrong answer.");
  return now() - began;
}

// ---- solving --------------------------------------------------------------------------------------------------------------------

function modelStatusName(highs, code) {
  for (const [name, value] of Object.entries(highs.constants.modelStatus)) {
    if (value === code) return name;
  }
  return String(code);
}

const finiteOrNull = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);

/** A model with no column: HiGHS refuses it, and the answer is the empty vector if every row allows 0 (as in the Python solver). */
function solveEmpty(model) {
  const feasible = model.row_lb.every((low) => low === null || low <= 0) && model.row_ub.every((high) => high === null || high >= 0);
  if (!feasible) return { status: "infeasible", proven: true, objective: null, x: null, bound: null, gap: null, nodes: 0, label: null };
  return { status: "optimal", proven: true, objective: model.const, x: [], bound: model.const, gap: 0, nodes: 0, label: null };
}

/**
 * Solve a model inside the time left of its budget. `startedAt` is when the request arrived (the same clock as `now`), so that building
 * the model counts against the budget. Returns the fields of a result message.
 */
export function solveModelWith(highs, model, { budgetMs, startedAt, onProgress = () => {}, now = nowMs }) {
  onProgress({ phase: "building" });
  if (model.c.length === 0) return solveEmpty(model);
  let solver;
  try {
    solver = highs.createModel(toModelData(highs, model));
  } catch (error) {
    // the solver's own refusal of what it was given is the model's fault; anything else came out of the WebAssembly (see createWorkerCore)
    if (error instanceof highs.errors.HighsError) throw new EngineFault("bad-model", `The optimizer would not take this model: ${describe(error)}`);
    throw error;
  }
  try {
    solver.options.set(SOLVER_OPTIONS);
    solver.options.set("time_limit", Math.max(0, budgetMs - (now() - startedAt)) / 1000);

    let lastReport = Number.NEGATIVE_INFINITY;
    const report = (fields) => {
      const at = now();
      if (at - lastReport < 50) return;
      lastReport = at;
      onProgress({ phase: "solving", elapsedMs: Math.max(0, at - startedAt), ...fields });
    };
    const types = highs.constants.callbackType;
    const outcome = solver.run({
      [types.mipImprovingSolution](event) {
        const value = finiteOrNull(event.data.objective_function_value);
        if (value !== null) report({ objective: value + model.const });
      },
      [types.mipLogging](event) {
        const fields = {};
        const bound = finiteOrNull(event.data.mip_dual_bound);
        const gap = finiteOrNull(event.data.mip_gap);
        if (bound !== null) fields.bound = bound + model.const;
        if (gap !== null && gap >= 0) fields.gap = gap;
        const nodes = Number(event.data.mip_node_count);
        if (Number.isInteger(nodes) && nodes >= 0) fields.nodes = nodes;
        report(fields);
      },
    });

    const states = highs.constants.modelStatus;
    const status = outcome.modelStatus;
    if (status !== states.optimal && status !== states.timeLimit && status !== states.infeasible) {
      throw new EngineFault("solver", `The solver ended with the status ${modelStatusName(highs, status)}.`);
    }
    const hasSolution =
      status === states.optimal || (status === states.timeLimit && Number(solver.info.get("primal_solution_status")) === highs.constants.solutionStatus.feasible);
    const x = hasSolution ? Array.from(solver.getSolution().colValue) : null;
    const objective = x === null ? null : model.const + model.c.reduce((sum, cost, j) => sum + cost * x[j], 0);
    // A model with no integer column is a linear program: HiGHS searches no tree for it, so its node count (-1) and its MIP dual bound
    // (0, whatever the objective) mean nothing. The optimum of a linear program is its own proof: no nodes, no separate bound.
    const isMip = model.integrality.some((flag) => flag === 1);
    const dualBound = isMip ? finiteOrNull(solver.info.get("mip_dual_bound")) : null;
    let gap = isMip ? finiteOrNull(Number(solver.info.get("mip_gap"))) : null;
    if (gap !== null && gap < 0) gap = 0;
    const counted = Number(solver.info.get("mip_node_count"));
    const nodes = isMip && Number.isFinite(counted) ? Math.max(0, Math.trunc(counted)) : 0;
    if (status === states.optimal) {
      return { status: "optimal", proven: true, objective, x, bound: dualBound === null ? objective : dualBound + model.const, gap: gap ?? 0, nodes, label: null };
    }
    if (status === states.infeasible) {
      return { status: "infeasible", proven: true, objective: null, x: null, bound: null, gap: null, nodes, label: null };
    }
    return {
      status: "time_limit",
      proven: false,
      objective,
      x,
      bound: dualBound === null ? null : dualBound + model.const,
      gap: x === null ? null : gap,
      nodes,
      label: x === null ? LABEL_NO_INCUMBENT : LABEL_TIME_LIMIT,
    };
  } finally {
    solver.dispose();
  }
}

// ---- the protocol side ----------------------------------------------------------------------------------------------------------

/** The input errors of the engine's functions: a request that does not fit the data, an item or a profile it cannot use. */
const REFUSALS = [PathError, SolveError, PruneError, EvaluateError, BundleError, TierError];

/**
 * The code of the protocol for an error raised while an answer for a scenario was worked out. A fault with a code of its own keeps it (the data
 * could not be loaded or is not what the site writes: engine-load, with the data dropped by scenario.js; a request the data does not fit: bad-request).
 * A solver that did what an answer cannot be made from (SolverFault: a status the solve does not accept, a solution that is not numbers or not whole, a model
 * that HiGHS refuses) is `solver`: nobody's input is to blame, and the worker goes on with a new session. The engine's input errors that reach this point are
 * the request's fault: bad-request. A model that overstates its own kit (ExactnessError) and an arrangement that changed more than the places
 * (PlacementError) are faults of the engine, not of the input, though the solver module files them with its input errors: internal. Anything else is
 * internal too, and the page replaces a worker that has said so.
 */
export function scenarioErrorCode(error) {
  if (error instanceof EngineFault) return error.code;
  if (error instanceof SolverFault) return "solver";
  if (error instanceof ExactnessError || error instanceof PlacementError) return "internal";
  return REFUSALS.some((type) => error instanceof type) ? "bad-request" : "internal";
}

/** The best effort to find the id of a message that was refused, so that the page can tell which request it was. */
function idOf(data) {
  try {
    if (!isPlainObject(data)) return undefined;
    const id = Object.getOwnPropertyDescriptor(data, "id")?.value;
    return Number.isInteger(id) && id >= 1 && id <= LIMITS.maxId ? id : undefined;
  } catch {
    return undefined;
  }
}

/** The method of the engine that answers each mode of a scenario request. */
const MODE_METHODS = new Map([
  [EQUIP_NOW, "equipNow"],
  [FARM_PATH, "farmPath"],
  [BEST_SETS, "bestSets"],
  [EVERY_SLOT, "everySlot"],
  [BEST_KIT, "bestKit"],
]);

/**
 * The worker's side of the protocol, free of any global so that it can be tested: `post` sends a message to the page, `loadManifest`
 * reads the manifest, `loadEngine({manifest, module, onProgress})` returns an engine `{version, module?, solveModel(model, options), equipNow, farmPath, ...}`.
 * `handle(data)` takes one message from the page and returns a promise that settles when it has been answered. Messages are handled in the order they arrive, but for a
 * stop: it is handled the moment it arrives, so that a farm path that is yielding between two steps sees it. It never throws.
 */
export function createWorkerCore({ post, loadManifest, loadEngine, now = nowMs }) {
  let phase = "new"; // new -> starting -> ready, or failed
  let manifest = null;
  let engine = null;
  let queue = Promise.resolve();
  /** The farm paths that were asked for and have not ended, by the id of their request: `{stopped}`. Only the id of such a request can be stopped. */
  const flights = new Map();

  const send = (message) => post({ v: PROTOCOL_VERSION, ...message });
  const refuse = (code, detail, id) => {
    const message = { type: "error", code: ERROR_CODES.includes(code) ? code : "internal", message: describe(detail) };
    if (id !== undefined) message.id = id;
    send(message);
  };

  async function start(message) {
    if (phase !== "new") return refuse("bad-request", "The optimizer was started already.");
    phase = "starting";
    try {
      manifest = await loadManifest();
      engine = await loadEngine({ manifest, module: message.module, onProgress: (progress) => send({ type: "progress", ...progress }) });
    } catch (error) {
      phase = "failed";
      return refuse("engine-load", error, undefined);
    }
    phase = "ready";
    // Which WebAssembly the manifest this worker read lists: for a file it downloaded, the one it checked and loaded; for a compiled module it was given,
    // the one that module has to have been made from. The page compares it with its own manifest, so that a release between the two reads is seen, and a
    // module that was kept is never run under a newer manifest.
    const ready = { type: "ready", highs: engine.version, wasm: engine.wasm !== undefined ? engine.wasm : manifest.wasm.sha256 };
    if (engine.module !== undefined) ready.module = engine.module;
    try {
      send(ready);
    } catch (error) {
      // a browser that will not copy a compiled module to the page still gets a working worker; the page just cannot keep the module
      if (ready.module === undefined) throw error;
      delete ready.module;
      send(ready);
    }
  }

  /** A scenario request: the engine's method for its mode answers it, the steps of a farm path are sent as they are made, and a stop ends the path before its next step. */
  async function solveScenario({ id, request }, startedAt, flight) {
    try {
      checkAgainstManifest(request, manifest);
    } catch (error) {
      return refuse("bad-request", error.detail ?? error, id);
    }
    const method = MODE_METHODS.get(request.mode);
    if (method === undefined || typeof engine[method] !== "function") return refuse("not-implemented", "Scenario requests are not available in the optimizer yet.", id);
    // the elapsed time of the answer is counted on this core's clock from the moment the request arrived (the data it fetches is part of it); the
    // budget of the work is counted by scenario.js from the moment the data is in
    const options = { manifest, startedAt, now, onProgress: (progress) => send({ type: "progress", id, ...progress }) };
    if (request.mode === FARM_PATH) {
      options.onStep = (body) => send({ type: "step", id, ...body });
      options.stopped = () => flight.stopped;
    }
    let answer;
    try {
      answer = await engine[method](request, options);
    } catch (error) {
      return refuse(scenarioErrorCode(error), error, id);
    }
    return send({ type: "result", id, kind: "scenario", mode: request.mode, ...answer, elapsedMs: Math.max(0, now() - startedAt) });
  }

  async function solve(message, flight) {
    const { id, request } = message;
    try {
      if (phase !== "ready") return refuse("not-ready", "The optimizer is not loaded yet.", id);
      const startedAt = now();
      if (request.kind === "scenario") return await solveScenario(message, startedAt, flight);
      let payload;
      try {
        // one clock for the whole request: the moment it arrived, the time the engine has left of the budget, the progress and the elapsed time of
        // the result are all read from `now`, the core's own (the engine's default would be the worker's performance.now(), a different clock)
        payload = await engine.solveModel(request.model, {
          budgetMs: request.budgetMs,
          startedAt,
          now,
          onProgress: (progress) => send({ type: "progress", id, ...progress }),
        });
      } catch (error) {
        // A fault the engine reports itself (a model it would not take, a status it does not know) leaves the worker as good as it was. Anything
        // else came out of the WebAssembly (an abort when the memory ran out, say): that instance is not to be trusted again, and the page
        // is told so, with the code `internal`, and replaces the worker.
        return refuse(error instanceof EngineFault ? error.code : "internal", error, id);
      }
      const { status, proven, objective, x, bound, gap, nodes, label } = payload;
      return send({ type: "result", id, kind: "model", status, proven, objective, x, bound, gap, nodes, elapsedMs: Math.max(0, now() - startedAt), label });
    } finally {
      if (flight !== undefined) flights.delete(id);
    }
  }

  async function receive(message, flight) {
    try {
      if (message.type === "ping") send({ type: "pong" }); // (the page asks only an idle worker: it answers at once)
      else if (message.type === "init") await start(message);
      else await solve(message, flight);
    } catch (error) {
      refuse("internal", error, message.id);
    }
  }

  return {
    handle(data) {
      let message = null;
      let failure = null;
      try {
        message = validateToWorker(data);
      } catch (error) {
        failure = error;
      }
      // A stop is for the farm path in flight with that id and for nothing else. It is not queued behind the request it is meant for, and it gets no reply.
      if (message !== null && message.type === "stop") {
        const flight = flights.get(message.id);
        if (flight !== undefined) flight.stopped = true;
        return Promise.resolve();
      }
      let flight;
      if (message !== null && message.type === "solve" && message.request.kind === "scenario" && message.request.mode === FARM_PATH) {
        if (flights.has(message.id)) {
          failure = new ProtocolError("bad-request", "A request with this id is in flight.");
          message = null;
        } else {
          flight = { stopped: false };
          flights.set(message.id, flight);
        }
      }
      const done = queue.then(() => (message === null ? refuse("bad-request", failure.detail ?? "The message was not understood.", idOf(data)) : receive(message, flight)));
      queue = done.catch(() => {});
      return done;
    },
  };
}

// ---- the shell, when this file runs as a worker -------------------------------------------------------------------------------

/**
 * Read the manifest for the worker (the page and the worker each read it; the page compares which WebAssembly the worker loaded with its own).
 * The read has the stall limit: a request that is not answered ends in an error, not in a wait with no end.
 */
export async function readManifest({ fetchImpl = (...args) => fetch(...args), base = self.location.href, stallMs = STARTUP_STALL_MS } = {}) {
  // (`no-cache`: ask the server whether the browser's copy is current, whatever the host's caching headers say; as in the page's read)
  const answer = await fetchTextWithin(fetchImpl, new URL(MANIFEST_PATH, base), { credentials: "same-origin", cache: "no-cache" }, stallMs);
  if (answer.state === "timeout") throw new EngineFault("engine-load", "The list of the optimizer's files did not arrive in time.");
  if (answer.state === "failed") throw new EngineFault("engine-load", "The list of the optimizer's files could not be loaded.");
  if (answer.state === "status") throw new EngineFault("engine-load", `The manifest could not be loaded (${answer.status}).`);
  // any other state is a failure too, and the text beside it (if there is one) is not looked at
  if (answer.state !== "ok" || typeof answer.text !== "string") throw new EngineFault("engine-load", "The list of the optimizer's files could not be read.");
  if (answer.text.length > LIMITS.maxManifestBytes) throw new EngineFault("engine-load", "The manifest is too large.");
  return parseManifest(JSON.parse(answer.text));
}

if (typeof WorkerGlobalScope !== "undefined" && typeof self !== "undefined" && self instanceof WorkerGlobalScope) {
  // A refusal by the page's policy inside the worker (the policy applies to the worker's own file) is not seen by the page: it fires on the
  // worker's global object and the page's console does not show it. Say so in the console, where the page's tests and a visitor's
  // developer tools both look. Registered first, before anything is loaded.
  self.addEventListener("securitypolicyviolation", (event) => {
    console.error(`The page's security policy refused something in the optimizer (${String(event.effectiveDirective).slice(0, 40)}).`);
  });
  const core = createWorkerCore({
    post: (message) => self.postMessage(message),
    loadManifest: () => readManifest(),
    loadEngine: (args) => loadHighsEngine(args),
  });
  self.onmessage = (event) => {
    core.handle(event.data);
  };
}
