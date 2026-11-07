// Times the browser engine on views of a folder of precompute results, and says what the slow ones have in common. No behaviour change: it only reads.
//
//   node scripts/profile-engine.mjs --results <dir> [--sample 150] [--defaults 6] [--procs 4] [--slowest 12] [--out <file.json>]
//   node scripts/profile-engine.mjs --results <dir> --ids 123,456 --procs 1 [--out <file.json>]      solve (again) the views with these ids
//   node --cpu-prof --cpu-prof-dir <dir> scripts/profile-engine.mjs --results <dir> --ids 123 --inline      the same, in this process, so that --cpu-prof sees the solves
//
//   --results <dir>       the folder of results (TRIOFORGE_RESULTS names it too); it is only read
//   --plain               no tie stage, as a visitor's browser solves (the default is the shard parity check's: `canonical: true`)
//   --haste N             fix the weapon haste at N percent (`haste_assumed`): one program instead of the ladder of haste levels; to see what the ladder costs
//
// A view is one row of a shard (a race in a chunk: evidence level, buff set, role, setup, tier), as tests-js/shard-results.mjs lists them, and it is solved the way the
// shard parity check solves it: by `bestKit` (engine/bestkit.js, the function the worker calls for the trio page) with the tie stage and the options the shard records. The
// `id` of a view is its place in that list, so the same folder gives the same ids.
//
// For each view the script records the wall time and its parts (pool, pruning, model, solve), and what explains them: the haste levels the truthful solve looked at and what
// became of each, the runs of the solver (the relaxations that bound the levels, the integer solves, the tie stage) with their times, the size of the model (columns, rows),
// the size of the pool and the pruned pool in all and per slot, and the nodes. Then it prints the slowest views and the means by role, setup, tier, evidence, buffs, trio and
// race, and how the time follows the number of levels and the size of the model.
//
// --procs P runs P worker processes (at most 8) that take the views by turns; the times of a view are its own wall time in its process, and more processes than cores slow
// every view. The views are chosen by a fixed stride over the whole list (so they spread over every trio, evidence level, role and tier), plus `--defaults` views of the
// default view of the trios (the views `defaults.json` is made from).

import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { bestKit } from "../pipeline/trioforge/site/static/engine/bestkit.js";
import { chunksOf, readResults, workOf } from "../tests-js/shard-results.mjs";

const MAX_PROCS = 8;
const BUDGET_MS = 3_600_000;
const SELF = fileURLToPath(import.meta.url);

// ---- the views -----------------------------------------------------------------------------------------------------------------------------

/** The views of the results as one list: `count` of them, and `at(id)` for the unit (chunk) and row of a place. */
export function viewList(results) {
  const units = chunksOf(results);
  const starts = [];
  let total = 0;
  for (const unit of units) {
    starts.push(total);
    total += unit.chunk.rows.length;
  }
  return {
    count: total,
    units,
    starts,
    at(id) {
      let low = 0;
      let high = units.length - 1;
      while (low < high) {
        const middle = (low + high + 1) >> 1;
        if (starts[middle] <= id) low = middle;
        else high = middle - 1;
      }
      return { unit: units[low], row: units[low].chunk.rows[id - starts[low]] };
    },
  };
}

/** The ids of a fixed-stride sample of `n` views, then the views of the default views of `defaults` trios (spread over the trios). */
function chooseIds(results, views, { sample, defaults, directory }) {
  const ids = new Set();
  const stride = Math.max(1, Math.floor(views.count / Math.max(1, sample)));
  // (an offset that is not a multiple of the number of races, so that the stride does not keep to one race)
  for (let id = Math.floor(stride / 2) + 1; id < views.count && ids.size < sample; id += stride) ids.add(id);
  if (defaults > 0) {
    const plans = workOf(results, { directory }).plans;
    const chunkStart = new Map(views.units.map((unit, at) => [unit.chunk, views.starts[at]]));
    const step = Math.max(1, Math.floor(plans.length / defaults));
    for (let at = 0; at < plans.length && ids.size < sample + defaults; at += step) {
      const plan = plans[at];
      const chunk = plan.chunks[0];
      if (chunk === undefined) continue;
      ids.add(chunkStart.get(chunk) + (at % chunk.rows.length));
    }
  }
  return [...ids].sort((a, b) => a - b);
}

// ---- solving and counting --------------------------------------------------------------------------------------------------------------------

/** A loaded solver whose models count their runs: `runs` is told {kind, ms, ints, columns, rows} for each (kind: "lp" a relaxation, "mip" a first stage, "tie" the tie stage). */
function countingHighs(highs, runs) {
  const make = highs.createModel;
  const maximize = highs.constants.objectiveSense.maximize;
  highs.createModel = function createModel(data, ...rest) {
    const solver = make.call(this, data, ...rest);
    const ints = data.integrality.reduce((sum, flag) => sum + (flag === 1 ? 1 : 0), 0);
    const kind = ints === 0 ? "lp" : data.sense === maximize ? "mip" : "tie";
    const run = solver.run;
    solver.run = function countedRun(...args) {
      const began = performance.now();
      try {
        return run.apply(this, args);
      } finally {
        runs.push({ kind, ms: performance.now() - began, ints, columns: data.numCols, rows: data.numRows });
      }
    };
    return solver;
  };
  return highs;
}

const slotCounts = (items) => {
  const found = {};
  for (const item of items) for (const slot of item.slots ?? []) found[slot] = (found[slot] ?? 0) + 1;
  return found;
};

const round = (ms) => Math.round(ms * 1000) / 1000;

/** Solve one view and say what it took. */
function profileView(context, id) {
  const { highs, runs, results, views } = context;
  const { unit, row } = views.at(id);
  const { level, shard, chunk } = unit;
  const scenario = { race: row.race, role: chunk.role, buffs: shard.buffs, evidence: shard.evidence, setup: chunk.setup };
  if (shard.assumptions.deity != null) scenario.deity = shard.assumptions.deity;
  const options = { any_rule: shard.buildOptions.any_rule, haste_assumed: context.haste ?? shard.buildOptions.haste_assumed };
  runs.length = 0;
  const began = performance.now();
  let solved = null;
  let fault = null;
  try {
    solved = bestKit({ highs, records: results.table.records, bundle: level.bundle, scenario, tier: chunk.tier, budgetMs: BUDGET_MS, canonical: context.canonical, options });
  } catch (error) {
    fault = `${error.name}: ${String(error.message).slice(0, 200)}`;
  }
  const ms = performance.now() - began;
  const view = {
    id,
    name: `${level.slug} L${level.level} ${shard.evidence}/${shard.buffs} ${row.race} ${chunk.role} ${chunk.setup} +${chunk.tier}`,
    trio: level.slug, level: level.level, evidence: shard.evidence, buffs: shard.buffs, race: row.race, role: chunk.role, setup: chunk.setup, tier: chunk.tier,
    ms: round(ms), fault,
  };
  if (solved === null) return view;
  const { answer, timings } = solved;
  const outcomes = { solved: 0, bound: 0, infeasible: 0, time: 0 };
  for (const run of answer.runs ?? []) outcomes[run.outcome] += 1;
  const byKind = (kind) => runs.filter((run) => run.kind === kind);
  const sum = (list) => round(list.reduce((total, run) => total + run.ms, 0));
  const mip = byKind("mip");
  const biggest = runs.reduce((top, run) => (run.columns * run.rows > top.columns * top.rows ? run : top), { columns: 0, rows: 0, ints: 0 });
  return {
    ...view,
    status: answer.status,
    poolMs: round(timings.poolMs), pruneMs: round(timings.pruneMs), buildMs: round(timings.buildMs), solveMs: round(timings.solveMs),
    levels: (answer.levels ?? []).length, outcomes,
    lpRuns: byKind("lp").length, lpMs: sum(byKind("lp")),
    mipRuns: mip.length, mipMs: sum(mip),
    tieRuns: byKind("tie").length, tieMs: sum(byKind("tie")),
    slowestRunMs: round(runs.reduce((top, run) => Math.max(top, run.ms), 0)),
    columns: biggest.columns, rows: biggest.rows, intColumns: biggest.ints,
    nodes: answer.nodes ?? 0,
    pool: solved.pool.length, pruned: solved.pruned.length,
    poolSlots: slotCounts(solved.pool), prunedSlots: slotCounts(solved.pruned),
    won: answer.level ?? null, F: answer.F === null ? null : answer.F.toString(),
  };
}

export async function solveIds(directory, ids, log, mode) {
  const results = readResults(directory);
  const views = viewList(results);
  const runs = [];
  const highs = countingHighs(await loadHighs(), runs);
  const context = { highs, runs, results, views, canonical: mode.canonical, haste: mode.haste };
  const found = [];
  for (const [at, id] of ids.entries()) {
    found.push(profileView(context, id));
    if (log !== null && (at + 1) % 10 === 0) log(`${at + 1} of ${ids.length}`);
  }
  return found;
}

// ---- the report --------------------------------------------------------------------------------------------------------------------------

const mean = (list) => (list.length === 0 ? 0 : list.reduce((a, b) => a + b, 0) / list.length);
const sorted = (list) => [...list].sort((a, b) => a - b);
const quantile = (list, q) => {
  const xs = sorted(list);
  return xs.length === 0 ? 0 : xs[Math.min(xs.length - 1, Math.floor(q * xs.length))];
};
const fixed = (x, places = 2) => Number(x).toFixed(places);

function correlation(xs, ys) {
  const [mx, my] = [mean(xs), mean(ys)];
  let [sxy, sxx, syy] = [0, 0, 0];
  xs.forEach((x, at) => {
    sxy += (x - mx) * (ys[at] - my);
    sxx += (x - mx) ** 2;
    syy += (ys[at] - my) ** 2;
  });
  return sxx === 0 || syy === 0 ? 0 : sxy / Math.sqrt(sxx * syy);
}

function groupLines(title, views, key) {
  const groups = new Map();
  for (const view of views) {
    const name = String(key(view));
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(view);
  }
  const lines = [`by ${title}:`];
  for (const [name, list] of [...groups.entries()].sort((a, b) => mean(b[1].map((v) => v.ms)) - mean(a[1].map((v) => v.ms))).slice(0, 12)) {
    lines.push(`  ${name.padEnd(14)} n=${String(list.length).padStart(4)}  mean ${fixed(mean(list.map((v) => v.ms)), 0).padStart(6)} ms  max ${fixed(Math.max(...list.map((v) => v.ms)), 0).padStart(7)} ms  levels ${fixed(mean(list.map((v) => v.levels)), 1)}  pruned ${fixed(mean(list.map((v) => v.pruned)), 0)}`);
  }
  return lines;
}

export function report(all, { slowest }) {
  const views = all.filter((view) => view.fault === null && view.levels !== undefined);
  const lines = [];
  const times = views.map((view) => view.ms);
  const total = times.reduce((a, b) => a + b, 0);
  lines.push(`${views.length} views solved (${all.length - views.length} faults), ${fixed(total / 1000, 1)} s of solving`);
  lines.push(`wall ms per view: mean ${fixed(mean(times), 0)}, median ${fixed(quantile(times, 0.5), 0)}, p90 ${fixed(quantile(times, 0.9), 0)}, p99 ${fixed(quantile(times, 0.99), 0)}, max ${fixed(Math.max(...times), 0)}`);
  const parts = ["poolMs", "pruneMs", "buildMs", "solveMs"].map((key) => `${key.replace("Ms", "")} ${fixed((100 * views.reduce((s, v) => s + v[key], 0)) / total, 1)}%`);
  lines.push(`where the time goes (share of the wall time): ${parts.join(", ")}`);
  const kinds = ["lp", "mip", "tie"].map((kind) => `${kind} ${fixed((100 * views.reduce((s, v) => s + v[`${kind}Ms`], 0)) / total, 1)}% (${fixed(mean(views.map((v) => v[`${kind}Runs`])), 1)} runs a view)`);
  lines.push(`inside the solver, share of the wall time: ${kinds.join(", ")}`);
  // the slowest views hold how much of the time
  const order = [...views].sort((a, b) => b.ms - a.ms);
  const top = Math.max(1, Math.ceil(views.length / 10));
  lines.push(`the slowest ${top} views (10%) hold ${fixed((100 * order.slice(0, top).reduce((s, v) => s + v.ms, 0)) / total, 1)}% of the time`);
  lines.push("");
  lines.push(`the ${slowest} slowest views:`);
  for (const view of order.slice(0, slowest)) {
    lines.push(
      `  id ${String(view.id).padStart(6)} ${fixed(view.ms, 0).padStart(7)} ms  ${view.name}`,
      `       prune ${fixed(view.pruneMs, 0)}, build ${fixed(view.buildMs, 0)}, solve ${fixed(view.solveMs, 0)} ms | levels ${view.levels} (solved ${view.outcomes.solved}, bound ${view.outcomes.bound}, infeasible ${view.outcomes.infeasible}) | runs lp ${view.lpRuns} ${fixed(view.lpMs, 0)} ms, mip ${view.mipRuns} ${fixed(view.mipMs, 0)} ms, tie ${view.tieRuns} ${fixed(view.tieMs, 0)} ms (slowest run ${fixed(view.slowestRunMs, 0)} ms) | ${view.columns} cols x ${view.rows} rows, ${view.intColumns} int | nodes ${view.nodes} | pool ${view.pool} -> ${view.pruned}`,
    );
  }
  lines.push("");
  lines.push("how the time follows the view (correlation with the wall time, over all views):");
  const features = {
    levels: (v) => v.levels, "levels solved": (v) => v.outcomes.solved, "lp runs": (v) => v.lpRuns, "mip runs": (v) => v.mipRuns, columns: (v) => v.columns, rows: (v) => v.rows,
    "int columns": (v) => v.intColumns, nodes: (v) => v.nodes, "pool": (v) => v.pool, "pruned pool": (v) => v.pruned, tier: (v) => v.tier,
  };
  for (const [name, get] of Object.entries(features)) lines.push(`  ${name.padEnd(14)} r = ${fixed(correlation(views.map(get), times), 2)}`);
  lines.push("");
  lines.push(...groupLines("role", views, (v) => v.role));
  lines.push(...groupLines("setup", views, (v) => v.setup));
  lines.push(...groupLines("tier", views, (v) => v.tier));
  lines.push(...groupLines("evidence/buffs", views, (v) => `${v.evidence}/${v.buffs}`));
  lines.push(...groupLines("race", views, (v) => v.race));
  lines.push(...groupLines("number of haste levels", views, (v) => v.levels));
  lines.push(...groupLines("trio", views, (v) => v.trio).slice(0, 9));
  lines.push(...groupLines("class in the trio", views.flatMap((v) => v.trio.split("-").map((code) => ({ ...v, code }))), (v) => v.code));
  return lines.join("\n");
}

// ---- running -----------------------------------------------------------------------------------------------------------------------------

function parseArguments(argv) {
  const found = { results: process.env.TRIOFORGE_RESULTS ?? null, sample: 150, defaults: 6, procs: 4, slowest: 12, out: null, ids: null, inline: false, worker: null, idsFile: null, canonical: true, haste: null };
  for (let at = 0; at < argv.length; at += 1) {
    const flag = argv[at];
    const value = () => {
      at += 1;
      if (at >= argv.length) throw new Error(`${flag} needs a value`);
      return argv[at];
    };
    if (flag === "--results") found.results = value();
    else if (flag === "--sample") found.sample = Number(value());
    else if (flag === "--defaults") found.defaults = Number(value());
    else if (flag === "--procs") found.procs = Number(value());
    else if (flag === "--slowest") found.slowest = Number(value());
    else if (flag === "--out") found.out = value();
    else if (flag === "--ids") found.ids = value().split(",").map(Number);
    else if (flag === "--inline") found.inline = true;
    else if (flag === "--plain") found.canonical = false;
    else if (flag === "--haste") found.haste = Number(value());
    else if (flag === "--worker") found.worker = value();
    else if (flag === "--ids-file") found.idsFile = value();
    else throw new Error(`unknown option ${flag}`);
  }
  if (found.results === null || found.results === "") throw new Error("name the folder of results: --results <dir>, or TRIOFORGE_RESULTS (it is only read)");
  if (!Number.isInteger(found.procs) || found.procs < 1 || found.procs > MAX_PROCS) throw new Error(`--procs is from 1 to ${MAX_PROCS}`);
  return found;
}

function runWorker(args, ids, index) {
  return new Promise((done, fail) => {
    const file = join(args.scratch, `ids-${index}.json`);
    const out = join(args.scratch, `out-${index}.json`);
    writeFileSync(file, JSON.stringify(ids));
    const extra = [...(args.canonical ? [] : ["--plain"]), ...(args.haste === null ? [] : ["--haste", String(args.haste)])];
    const child = spawn(process.execPath, [SELF, "--results", args.results, "--ids-file", file, "--out", out, "--worker", String(index), ...extra], { stdio: ["ignore", "inherit", "inherit"] });
    child.on("error", fail);
    child.on("exit", (code) => {
      if (code !== 0) fail(new Error(`worker ${index} ended with ${code}`));
      else done(JSON.parse(readFileSync(out, "utf8")));
    });
  });
}

async function main() {
  const args = parseArguments(process.argv.slice(2));
  const directory = resolve(args.results);
  if (args.worker !== null) {
    const ids = JSON.parse(readFileSync(args.idsFile, "utf8"));
    const found = await solveIds(directory, ids, null, args);
    writeFileSync(args.out, JSON.stringify(found));
    return;
  }
  const started = performance.now();
  let ids = args.ids;
  if (ids === null) {
    const results = readResults(directory);
    const views = viewList(results);
    ids = chooseIds(results, views, { sample: args.sample, defaults: args.defaults, directory });
    console.log(`${views.count} views in the folder; profiling ${ids.length} of them with ${args.procs} process(es)`);
  }
  let all;
  if (args.inline || args.procs === 1 && args.ids !== null) {
    all = await solveIds(directory, ids, (text) => console.log(text), args);
  } else {
    args.scratch = join(tmpdir(), `profile-engine-${process.pid}`);
    mkdirSync(args.scratch, { recursive: true });
    // the views go to the processes by turns, so that each gets a mixture of the cheap and the dear
    const shares = Array.from({ length: args.procs }, (_, k) => ids.filter((_, at) => at % args.procs === k));
    try {
      all = (await Promise.all(shares.map((share, k) => runWorker(args, share, k)))).flat();
    } finally {
      rmSync(args.scratch, { recursive: true, force: true }); // (the folder this run made in the temp directory)
    }
  }
  all.sort((a, b) => a.id - b.id);
  if (args.out !== null) writeFileSync(args.out, JSON.stringify(all));
  console.log(report(all, { slowest: args.slowest }));
  console.log(`\n(${fixed((performance.now() - started) / 1000, 0)} s in all)`);
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === resolve(SELF)) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
