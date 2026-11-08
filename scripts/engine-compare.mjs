// Holds the browser engine to itself: solves a fixed set of views of a folder of precompute results in both modes (the shard parity check's, with the tie stage, and a phone's,
// without it) and either saves what came out (a baseline) or diffs it against a saved baseline. The gate of a speed-up: it must change no answer, so every view must come out
// with the same kit (the item and tier of every place), the same optional buffs, the same exact value F and the same haste, in both modes.
//
//   node scripts/engine-compare.mjs --results <dir> --out <baseline.json>                  [--sample 300] [--defaults 12] [--ids 1,2,3] [--procs 6]
//   node scripts/engine-compare.mjs --results <dir> --against <baseline.json> [--out <new.json>] [--procs 6]
//
//   --results <dir>     the folder of results (TRIOFORGE_RESULTS names it too); it is only read
//   --sample n          n views by a fixed stride over the whole folder, plus --defaults views of the default views of the trios (the choice of scripts/profile-engine.mjs)
//   --ids a,b,c         more views, by id (the ids of scripts/profile-engine.mjs)
//   --against <file>    solve the views that file holds and print every difference; the exit status is 1 if any view differs in either mode
//   --procs P           worker processes (at most 12); the times of a view are its own wall time in its process
//
// Each view is solved by `bestKit`, as the shard parity check solves it (canonical: true) and as a visitor's browser does (canonical: false), with the options the shard
// records. What is saved for a view in a mode: the kit (`key@tier` or null, place by place), the buffs, F as the exact text, the haste the weapons were scored at, the level
// the kit came from, the status, the milliseconds, and what the solver did (runs of each kind and their time, nodes).

import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { bestKit } from "../pipeline/trioforge/site/static/engine/bestkit.js";
import { readResults } from "../tests-js/shard-results.mjs";
import { chooseIds, countingHighs, viewList } from "./profile-engine.mjs";

const MAX_PROCS = 12;
const BUDGET_MS = 3_600_000;
const SELF = fileURLToPath(import.meta.url);
const MODES = ["canonical", "plain"];

const round = (ms) => Math.round(ms * 1000) / 1000;

/** The answer of one view in one mode, as the data that is compared (`answer`) and the data that is only timed (`time`). */
function solveView(context, id, canonical) {
  const { highs, runs, results, views } = context;
  const { unit, row } = views.at(id);
  const { level, shard, chunk } = unit;
  const scenario = { race: row.race, role: chunk.role, buffs: shard.buffs, evidence: shard.evidence, setup: chunk.setup };
  if (shard.assumptions.deity != null) scenario.deity = shard.assumptions.deity;
  const options = { any_rule: shard.buildOptions.any_rule, haste_assumed: shard.buildOptions.haste_assumed };
  runs.length = 0;
  const began = performance.now();
  let fault = null;
  let solved = null;
  try {
    solved = bestKit({ highs, records: results.table.records, bundle: level.bundle, scenario, tier: chunk.tier, budgetMs: BUDGET_MS, canonical, options });
  } catch (error) {
    fault = `${error.name}: ${String(error.message).slice(0, 200)}`;
  }
  const ms = performance.now() - began;
  const name = `${level.slug} L${level.level} ${shard.evidence}/${shard.buffs} ${row.race} ${chunk.role} ${chunk.setup} +${chunk.tier}`;
  if (solved === null) return { name, answer: { fault }, time: { ms: round(ms) } };
  const { answer } = solved;
  const total = (kind) => round(runs.filter((run) => run.kind === kind).reduce((sum, run) => sum + run.ms, 0));
  const count = (kind) => runs.filter((run) => run.kind === kind).length;
  return {
    name,
    answer: {
      kit: answer.kit === null ? null : answer.kit.map((item) => (item === null ? null : `${item.key}@${item.tier}`)),
      buffs: answer.buffs,
      F: answer.F === null ? null : answer.F.toString(),
      hasteAssumed: answer.hasteAssumed,
      level: answer.level ?? null,
      status: answer.status,
      tieStage: answer.tieStage,
    },
    time: {
      ms: round(ms),
      lpRuns: count("lp"), lpMs: total("lp"), mipRuns: count("mip"), mipMs: total("mip"), tieRuns: count("tie"), tieMs: total("tie"),
      nodes: answer.nodes ?? 0,
      levels: (answer.levels ?? []).length,
      outcomes: Object.fromEntries(["solved", "bound", "infeasible", "time"].map((kind) => [kind, (answer.runs ?? []).filter((run) => run.outcome === kind).length])),
    },
  };
}

async function solveIds(directory, ids, modes) {
  const results = readResults(directory);
  const views = viewList(results);
  const runs = [];
  const highs = countingHighs(await loadHighs(), runs);
  const context = { highs, runs, results, views };
  const found = [];
  for (const id of ids) {
    const view = { id };
    for (const mode of modes) {
      const one = solveView(context, id, mode === "canonical");
      view.name = one.name;
      view[mode] = { ...one.answer, time: one.time };
    }
    found.push(view);
  }
  return found;
}

// ---- comparing ---------------------------------------------------------------------------------------------------------------------------------

const FIELDS = ["kit", "buffs", "F", "hasteAssumed", "level", "status", "tieStage", "fault"];

/** The differences of a view in a mode between a saved answer and a new one, as texts (none when every compared field is equal). */
export function differences(before, after) {
  const found = [];
  for (const field of FIELDS) {
    const a = JSON.stringify(before[field] ?? null);
    const b = JSON.stringify(after[field] ?? null);
    if (a !== b) found.push(`${field}: ${a} became ${b}`);
  }
  return found;
}

const mean = (list) => (list.length === 0 ? 0 : list.reduce((a, b) => a + b, 0) / list.length);
const quantile = (list, q) => {
  const xs = [...list].sort((a, b) => a - b);
  return xs.length === 0 ? 0 : xs[Math.min(xs.length - 1, Math.floor(q * xs.length))];
};
const fixed = (x, places = 0) => Number(x).toFixed(places);

/** The times of a set of views in a mode, as a line: mean, median, p99 and max, and the total. */
function timeLine(views, mode) {
  const times = views.map((view) => view[mode].time.ms);
  return `mean ${fixed(mean(times))} ms, median ${fixed(quantile(times, 0.5))}, p99 ${fixed(quantile(times, 0.99))}, max ${fixed(Math.max(...times))}, total ${fixed(times.reduce((a, b) => a + b, 0) / 1000, 1)} s`;
}

/** The report of a run: the times by mode for all the views and for the `slowest` of them (the slowest by the saved baseline when there is one). */
export function summary(views, order, slowest) {
  const lines = [];
  const slow = new Set(order.slice(0, slowest));
  for (const mode of MODES) {
    if (views.length === 0 || views[0][mode] === undefined) continue;
    lines.push(`${mode.padEnd(9)} all ${views.length}: ${timeLine(views, mode)}`);
    lines.push(`${"".padEnd(9)} slowest ${slow.size}: ${timeLine(views.filter((view) => slow.has(view.id)), mode)}`);
    const sum = (key) => views.reduce((total, view) => total + view[mode].time[key], 0);
    lines.push(`${"".padEnd(9)} solver runs: lp ${sum("lpRuns")} (${fixed(sum("lpMs") / 1000, 1)} s), mip ${sum("mipRuns")} (${fixed(sum("mipMs") / 1000, 1)} s), tie ${sum("tieRuns")} (${fixed(sum("tieMs") / 1000, 1)} s); levels bound-skipped ${views.reduce((t, v) => t + v[mode].time.outcomes.bound, 0)}, solved ${views.reduce((t, v) => t + v[mode].time.outcomes.solved, 0)}`);
  }
  return lines.join("\n");
}

// ---- running -----------------------------------------------------------------------------------------------------------------------------

function parseArguments(argv) {
  const found = { results: process.env.TRIOFORGE_RESULTS ?? null, sample: 300, defaults: 12, ids: [], procs: 6, out: null, against: null, worker: null, idsFile: null, modes: MODES };
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
    else if (flag === "--ids") found.ids = value().split(",").filter((text) => text !== "").map(Number);
    else if (flag === "--procs") found.procs = Number(value());
    else if (flag === "--out") found.out = value();
    else if (flag === "--against") found.against = value();
    else if (flag === "--modes") found.modes = value().split(",");
    else if (flag === "--worker") found.worker = value();
    else if (flag === "--ids-file") found.idsFile = value();
    else throw new Error(`unknown option ${flag}`);
  }
  if (found.results === null || found.results === "") throw new Error("name the folder of results: --results <dir>, or TRIOFORGE_RESULTS (it is only read)");
  if (!Number.isInteger(found.procs) || found.procs < 1 || found.procs > MAX_PROCS) throw new Error(`--procs is from 1 to ${MAX_PROCS}`);
  for (const mode of found.modes) if (!MODES.includes(mode)) throw new Error(`unknown mode ${mode}`);
  return found;
}

function runWorker(args, ids, index, scratch) {
  return new Promise((done, fail) => {
    const file = join(scratch, `ids-${index}.json`);
    const out = join(scratch, `out-${index}.json`);
    writeFileSync(file, JSON.stringify(ids));
    const child = spawn(process.execPath, [SELF, "--results", args.results, "--ids-file", file, "--out", out, "--worker", String(index), "--modes", args.modes.join(",")], { stdio: ["ignore", "inherit", "inherit"] });
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
    writeFileSync(args.out, JSON.stringify(await solveIds(directory, ids, args.modes)));
    return;
  }
  const started = performance.now();
  let baseline = null;
  let ids;
  if (args.against !== null) {
    baseline = JSON.parse(readFileSync(args.against, "utf8"));
    ids = baseline.views.map((view) => view.id);
  } else {
    const results = readResults(directory);
    const views = viewList(results);
    ids = [...new Set([...chooseIds(results, views, { sample: args.sample, defaults: args.defaults, directory }), ...args.ids])].sort((a, b) => a - b);
  }
  console.log(`solving ${ids.length} views in ${args.modes.join(" and ")} mode with ${args.procs} process(es)`);
  const scratch = join(tmpdir(), `engine-compare-${process.pid}`);
  mkdirSync(scratch, { recursive: true });
  let all;
  try {
    // by turns, so that each process gets a mixture of the cheap and the dear views
    const shares = Array.from({ length: args.procs }, (_, k) => ids.filter((_, at) => at % args.procs === k));
    all = (await Promise.all(shares.map((share, k) => runWorker(args, share, k, scratch)))).flat();
  } finally {
    rmSync(scratch, { recursive: true, force: true }); // (the folder this run made in the temp directory)
  }
  all.sort((a, b) => a.id - b.id);
  const slowestIds = (baseline === null ? all : baseline.views).slice().sort((a, b) => (b.canonical ?? b.plain).time.ms - (a.canonical ?? a.plain).time.ms).map((view) => view.id);
  if (args.out !== null) writeFileSync(args.out, JSON.stringify({ results: "(named by the caller)", modes: args.modes, views: all }));
  let differing = 0;
  if (baseline !== null) {
    const was = new Map(baseline.views.map((view) => [view.id, view]));
    for (const mode of args.modes) {
      let equal = 0;
      let shown = 0;
      for (const view of all) {
        const found = was.get(view.id)?.[mode] === undefined ? ["no baseline for this mode"] : differences(was.get(view.id)[mode], view[mode]);
        if (found.length === 0) {
          equal += 1;
          continue;
        }
        differing += 1;
        if (shown < 5) console.log(`DIFFERS ${mode} id ${view.id} ${view.name}\n    ${found.join("\n    ")}`);
        shown += 1;
      }
      console.log(`${mode}: ${equal} of ${all.length} views equal`);
    }
    console.log("\nbaseline times:");
    console.log(summary(baseline.views, slowestIds, 40));
  }
  console.log(baseline === null ? "times:" : "\nnew times:");
  console.log(summary(all, slowestIds, 40));
  console.log(`\n(${fixed((performance.now() - started) / 1000)} s in all)`);
  if (differing > 0) process.exitCode = 1;
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === resolve(SELF)) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
