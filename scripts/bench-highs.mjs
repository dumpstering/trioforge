// Times MPS models with the pinned highs-js (the browser engine) in Node.
//
//   node scripts/bench-highs.mjs <dir> [--json out.json] [--reps 5] [--time-limit 120] [--presolve off|on]
//
// <dir> holds the models the benchmark exported (python -m trioforge.bench) and, beside them, a manifest.json that says
// what each should solve to. Every model is read and solved `reps` times with the project's determinism options
// (gap 0, presolve off, seed 0, feasibility 1e-9; the WebAssembly build is single-threaded); the time of a model is the
// best of the solve times over the repeats (other work on the machine only adds time; the median of the repeats and the
// CPU time are reported too). The summary is the median, 95th percentile and maximum over the models, the
// number the phone budget is judged by (median under 1 s, p95 under 5 s). This is a desktop number: a mid-range phone
// is about 4 times slower, and the script prints that estimate too.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { performance } from "node:perf_hooks";

export const PHONE_FACTOR = 4;

// The options of the Python solver (pipeline/trioforge/solver/_highs.py) that the persistent API accepts: it refuses
// `threads` (this build has one) and every file option.
export const OPTIONS = {
  output_flag: false,
  mip_rel_gap: 0,
  mip_abs_gap: 1e-9,
  presolve: "off",
  random_seed: 0,
  mip_feasibility_tolerance: 1e-9,
  primal_feasibility_tolerance: 1e-9,
};

/** The q-th percentile (0 to 100) by linear interpolation between the two nearest ranks, as the Python side does. */
export function percentile(values, q) {
  if (values.length === 0) throw new Error("a percentile needs at least one value");
  if (!(q >= 0 && q <= 100)) throw new Error(`q is a percentage from 0 to 100, not ${q}`);
  const xs = [...values].sort((a, b) => a - b);
  const position = ((xs.length - 1) * q) / 100;
  const low = Math.floor(position);
  const high = Math.ceil(position);
  return xs[low] + (xs[high] - xs[low]) * (position - low);
}

export function summarize(values) {
  if (values.length === 0) return { n: 0 };
  const sum = values.reduce((a, b) => a + b, 0);
  return {
    n: values.length,
    mean: sum / values.length,
    p50: percentile(values, 50),
    p95: percentile(values, 95),
    max: Math.max(...values),
  };
}

/** Reads and solves one MPS file `reps` times; returns the timings of each repeat and the answer of the last.
 * Each repeat has the wall time of the read (`load_ms`) and of the solve (`run_ms`), and the CPU time of the solve
 * (`cpu_ms`, user plus system, from process.cpuUsage; the operating system's clock may tick coarsely). */
export function timeModel(highs, bytes, { reps = 3, timeLimit = 120, presolve = "off" } = {}) {
  const runs = [];
  let answer = null;
  for (let rep = 0; rep < reps; rep += 1) {
    const started = performance.now();
    const model = highs.createModel({ format: "mps", data: bytes });
    const loaded = performance.now();
    try {
      model.options.set({ ...OPTIONS, presolve, time_limit: timeLimit });
      const cpuBefore = process.cpuUsage();
      model.run();
      const finished = performance.now();
      const cpuUsed = process.cpuUsage(cpuBefore);
      const dims = model.getDimensions();
      answer = {
        status: model.getModelStatus(),
        objective: model.getObjectiveValue(),
        nodes: Number(model.info.get("mip_node_count")),
        cols: dims.numCols,
        rows: dims.numRows,
      };
      runs.push({ load_ms: loaded - started, run_ms: finished - loaded, cpu_ms: (cpuUsed.user + cpuUsed.system) / 1000 });
    } finally {
      model.dispose();
    }
  }
  return { runs, answer };
}

/** Times every .mps file of `dir`; `expected` maps a file name to the objective the Python solver reported. */
export async function benchDirectory(dir, { reps = 5, timeLimit = 120, presolve = "off", expected = {} } = {}) {
  const { default: loadHighs } = await import("highs");
  const highs = await loadHighs();
  const files = fs.readdirSync(dir).filter((name) => name.endsWith(".mps")).sort();
  if (files.length === 0) throw new Error(`no .mps files in ${dir}`);
  const optimal = highs.constants.modelStatus.optimal;
  const bytes = new Map(files.map((name) => [name, new Uint8Array(fs.readFileSync(path.join(dir, name)))]));
  timeModel(highs, bytes.get(files[0]), { reps: 1, timeLimit, presolve }); // warm up the WebAssembly code, untimed
  const models = [];
  for (const name of files) {
    const { runs, answer } = timeModel(highs, bytes.get(name), { reps, timeLimit, presolve });
    // The best repeat is the time without interference (a busy machine only adds time); the median shows the typical one.
    const run = Math.min(...runs.map((r) => r.run_ms));
    const load = Math.min(...runs.map((r) => r.load_ms));
    const wanted = expected[name];
    models.push({
      file: name,
      cols: answer.cols,
      rows: answer.rows,
      status: answer.status === optimal ? "optimal" : `status ${answer.status}`,
      nodes: answer.nodes,
      load_ms: load,
      run_ms: run,
      run_median_ms: percentile(runs.map((r) => r.run_ms), 50),
      cpu_ms: percentile(runs.map((r) => r.cpu_ms), 50),
      objective: answer.objective,
      expected: wanted ?? null,
      rel_diff: wanted === undefined ? null : Math.abs(answer.objective - wanted) / Math.max(1, Math.abs(wanted)),
    });
  }
  const run = models.map((m) => m.run_ms);
  const typical = models.map((m) => m.run_median_ms);
  const cpu = models.map((m) => m.cpu_ms);
  const total = models.map((m) => m.run_ms + m.load_ms);
  const diffs = models.map((m) => m.rel_diff).filter((d) => d !== null);
  const version = highs.version ?? {};
  return {
    engine: "highs-js",
    highs: { version: `${version.major}.${version.minor}.${version.patch}`, githash: version.gitHash ?? null },
    node: process.version,
    reps,
    presolve,
    options: OPTIONS,
    models: models.length,
    median_ms: percentile(run, 50),
    p95_ms: percentile(run, 95),
    max_ms: Math.max(...run),
    mean_ms: summarize(run).mean,
    typical_median_ms: percentile(typical, 50),
    typical_p95_ms: percentile(typical, 95),
    cpu_median_ms: percentile(cpu, 50),
    cpu_p95_ms: percentile(cpu, 95),
    total_median_ms: percentile(total, 50),
    total_p95_ms: percentile(total, 95),
    phone_factor: PHONE_FACTOR,
    phone_median_ms: PHONE_FACTOR * percentile(run, 50),
    phone_p95_ms: PHONE_FACTOR * percentile(run, 95),
    all_optimal: models.every((m) => m.status === "optimal"),
    max_rel_objective_diff: diffs.length ? Math.max(...diffs) : null,
    per_model: models,
  };
}

function parseArgs(argv) {
  const args = { dir: null, json: null, reps: 5, timeLimit: 120, presolve: "off" };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--json") args.json = argv[++i];
    else if (arg === "--reps") args.reps = Number(argv[++i]);
    else if (arg === "--time-limit") args.timeLimit = Number(argv[++i]);
    else if (arg === "--presolve") args.presolve = argv[++i];
    else if (arg.startsWith("--")) throw new Error(`unknown option ${arg}`);
    else args.dir = arg;
  }
  if (!args.dir) throw new Error("usage: node scripts/bench-highs.mjs <dir> [--json out.json] [--reps 5]");
  if (!Number.isInteger(args.reps) || args.reps < 1) throw new Error("--reps is a whole number of at least 1");
  if (!["off", "on"].includes(args.presolve)) throw new Error("--presolve is off or on");
  return args;
}

function report(result) {
  const pad = (text, width) => String(text).padEnd(width);
  const lines = [`${pad("model", 58)}${pad("cols", 7)}${pad("rows", 6)}${pad("load ms", 10)}${pad("run ms", 10)}${pad("cpu ms", 10)}${pad("nodes", 7)}status`];
  for (const m of result.per_model) {
    lines.push(
      `${pad(m.file, 58)}${pad(m.cols, 7)}${pad(m.rows, 6)}${pad(m.load_ms.toFixed(1), 10)}${pad(m.run_ms.toFixed(1), 10)}${pad(m.cpu_ms.toFixed(1), 10)}${pad(m.nodes, 7)}${m.status}`,
    );
  }
  lines.push("");
  lines.push(`highs-js ${result.highs.version} (${result.highs.githash}) on Node ${result.node}, presolve ${result.presolve}, ${result.reps} repeats, ${result.models} models`);
  lines.push(`solve ms, best of ${result.reps}: median ${result.median_ms.toFixed(1)}, p95 ${result.p95_ms.toFixed(1)}, max ${result.max_ms.toFixed(1)}, mean ${result.mean_ms.toFixed(1)}`);
  lines.push(`solve ms, median of ${result.reps}: median ${result.typical_median_ms.toFixed(1)}, p95 ${result.typical_p95_ms.toFixed(1)}; CPU ms: median ${result.cpu_median_ms.toFixed(1)}, p95 ${result.cpu_p95_ms.toFixed(1)}`);
  lines.push(`with the model read: median ${result.total_median_ms.toFixed(1)}, p95 ${result.total_p95_ms.toFixed(1)}`);
  lines.push(
    `phone estimate (x${result.phone_factor}): median ${result.phone_median_ms.toFixed(0)} ms, p95 ${result.phone_p95_ms.toFixed(0)} ms (budget: median under 1000, p95 under 5000)`,
  );
  if (result.max_rel_objective_diff !== null) {
    lines.push(`largest objective difference to the Python solver: ${result.max_rel_objective_diff.toExponential(2)} relative`);
  }
  return lines.join("\n");
}

async function main(argv) {
  const args = parseArgs(argv);
  const manifestPath = path.join(args.dir, "manifest.json");
  const expected = {};
  if (fs.existsSync(manifestPath)) {
    for (const entry of JSON.parse(fs.readFileSync(manifestPath, "utf8")).models) expected[entry.file] = entry.objective;
  }
  const result = await benchDirectory(args.dir, { ...args, expected });
  console.log(report(result));
  if (args.json) fs.writeFileSync(args.json, `${JSON.stringify(result, null, 1)}\n`);
  if (!result.all_optimal) process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main(process.argv.slice(2)).catch((error) => {
    console.error(error.message);
    process.exit(2);
  });
}
