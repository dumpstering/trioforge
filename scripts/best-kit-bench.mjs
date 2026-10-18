// Times the best kit of a view (engine/bestkit.js, the function the worker calls) on the item table and the bundle of a folder of results, in Node.
//
//   node scripts/best-kit-bench.mjs <results folder> [--trio pal-mnk-ber] [--level 50] [--evidence wiki] [--buffs own] [--roles tank,balanced] [--setup 1h-shield]
//                                    [--races HUM,OGR,IKS | all] [--tiers 0,1,...,10] [--heavy 12 | all] [--tie yes | no] [--json out.json]
//
// <results folder> is what the precompute writes (items.json, and <trio>/engine-l<level>.json beside the shards): the shards are not read, so the synthetic results of the site
// fixture (fixtures/site/results) do as well as the real ones. The buff set is `--buffs` (own, group, group+enchanter or raid: any the bundle has), and the command says which it timed,
// in its first line and in the JSON. Two steps:
//
//   1. The heavy views. Every view of the roles, the weapon setup and the races named (`all`: every race of the bundle), at the tiers named (all of 0 to 10 by default), is solved once
//      at the role's own weights (no tie stage). With `--tie yes` the slowest ones are solved again with the tie stage, and the `--heavy` slowest of those are the heavy views; with
//      `--tie no` the heavy views are the `--heavy` slowest of the first solves. `--heavy all` is every view. (The slowest views of the precompute are the wiki-pool views of a tank
//      and a balanced role with a one-hander and a shield.)
//   2. The weights. Each heavy view is solved at the role's own weights and with each slider group at x2, without the tie stage (what the browser's answer does) and, with
//      `--tie yes`, with it (what the precompute and the shard parity test do). The time of a solve is the pool, its pruning, the model and the solver, as the worker spends it after
//      the data is in.
//
// The summary of each setting is the median, the 95th percentile and the maximum over the heavy views, in milliseconds on this machine (a desktop number), and the slowest view of the
// setting: its trio, race, role, tier, weapon setup, evidence level and buff set. The slowest view of all the settings is named at the end. Other work on the machine only adds time,
// so measure alone. The first solve is a warm-up, left out.

import fs from "node:fs";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { pathToFileURL } from "node:url";
import { bestKit } from "../pipeline/trioforge/site/static/engine/bestkit.js";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";

/** The tiers of a pool. */
const TIERS = Array.from({ length: 11 }, (_, tier) => tier);
const OPTIONS = new Map([
  ["trio", "pal-mnk-ber"],
  ["level", "50"],
  ["evidence", "wiki"],
  ["buffs", "own"],
  ["roles", "tank,balanced"],
  ["setup", "1h-shield"],
  ["races", "HUM,OGR,IKS"],
  ["tiers", ""],
  ["heavy", "12"],
  ["tie", "yes"],
  ["json", ""],
]);
const BUDGET_MS = 3_600_000;

/** The percentile (nearest rank) of a list of numbers. */
export function percentile(values, p) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1))];
}

/** `{n, median, p95, max}` of a list of numbers. */
export function summary(values) {
  return { n: values.length, median: percentile(values, 50), p95: percentile(values, 95), max: Math.max(...values) };
}

/** The views of the bundle to look through: each role, at the setup, of the races, at every tier: `{scenario, tier}`. */
export function viewsOf(bundle, { evidence, buffs, roles, setup, races, tiers = TIERS }) {
  const found = [];
  for (const role of roles) {
    if (bundle.roles[role] === undefined || !bundle.roles[role].setups_by_evidence[evidence].includes(setup)) continue;
    for (const race of races) {
      if (!bundle.races.some((row) => row.code === race)) continue;
      for (const tier of tiers) found.push({ scenario: { race, role, buffs, evidence, setup }, tier });
    }
  }
  return found;
}

/** The name of a view: its trio, race, role, tier, weapon setup, evidence level and buff set. */
export function nameOf(bundle, view) {
  const { race, role, setup, evidence, buffs } = view.scenario;
  return `${bundle.trio.map((code) => code.toLowerCase()).join("-")} ${race} ${role} +${view.tier} ${setup} ${evidence} ${buffs}`;
}

/** One solve of a view with the weights and the tie stage as given, timed whole and in its parts. */
export function timeView({ highs, records, bundle, view, weights, canonical }) {
  const began = performance.now();
  const got = bestKit({ highs, records, bundle, scenario: view.scenario, tier: view.tier, weights, budgetMs: BUDGET_MS, canonical });
  const totalMs = performance.now() - began;
  return { totalMs, ...got.timings, tieMs: got.answer.timings.tieMs, pool: got.pool.length, pruned: got.pruned.length, F: got.answer.F.toNumber(), status: got.answer.status };
}

/** `summary` of the times of a setting, and its slowest view: `{ms, name}`. */
function settled(times, names) {
  const at = times.indexOf(Math.max(...times));
  return { ...summary(times), slowest: { ms: times[at], name: names[at] } };
}

/**
 * Both steps (see the head of this file). `views` are the views to look through, `heavy` how many heavy views to time (Infinity: all of them), `groups` the slider groups to put at x2,
 * `tie` whether the tie stage is timed as well as the plain solve.
 * Returns `{heavy: [{name, plainMs, canonicalMs}], settings: {label: {plain: summary, canonical?: summary}}, slowest: {ms, name, setting}}`, `label` "own" and then each group at x2; a
 * summary is `{n, median, p95, max, slowest: {ms, name}}`, and `slowest` is the slowest solve of any setting without the tie stage.
 */
export function measure({ highs, records, bundle, views, heavy, groups, tie = true, progress = () => {} }) {
  const solve = (view, weights, canonical) => timeView({ highs, records, bundle, view, weights, canonical });
  solve(views[0], undefined, false); // the warm-up
  const looked = views.map((view) => ({ view, plain: solve(view, undefined, false).totalMs }));
  looked.sort((a, b) => b.plain - a.plain);
  progress(`${looked.length} views looked through; the slowest ${looked[0].plain.toFixed(0)} ms`);
  let chosen;
  if (tie) {
    const candidates = looked.slice(0, 2 * heavy).map((one) => ({ ...one, tied: solve(one.view, undefined, true).totalMs }));
    candidates.sort((a, b) => b.tied - a.tied);
    chosen = candidates.slice(0, heavy);
  } else {
    chosen = looked.slice(0, heavy);
  }
  const names = chosen.map((one) => nameOf(bundle, one.view));
  const settings = {};
  let slowest = { ms: 0, name: "", setting: "" };
  const cases = [["own", undefined], ...groups.map((group) => [`${group} x2`, { multipliers: { [group]: 2 } }])];
  for (const [label, weights] of cases) {
    const row = {};
    for (const canonical of tie ? [false, true] : [false]) {
      const times = chosen.map((one) => solve(one.view, weights, canonical).totalMs);
      row[canonical ? "canonical" : "plain"] = settled(times, names);
    }
    settings[label] = row;
    if (row.plain.slowest.ms > slowest.ms) slowest = { ...row.plain.slowest, setting: label };
    progress(`${label}: ${Object.entries(row).map(([how, found]) => `${how} median ${found.median.toFixed(0)} p95 ${found.p95.toFixed(0)} max ${found.max.toFixed(0)}`).join(", ")}`);
  }
  return { heavy: chosen.map((one, at) => ({ name: names[at], plainMs: one.plain, ...(tie ? { canonicalMs: one.tied } : {}) })), settings, slowest };
}

const wholeNumber = (text, what, low, high) => {
  if (!/^[0-9]{1,6}$/.test(text) || Number(text) < low || Number(text) > high) throw new Error(`${what} is a whole number from ${low} to ${high}, not ${JSON.stringify(text.slice(0, 20))}`);
  return Number(text);
};

function parse(args) {
  const given = new Map(OPTIONS);
  const rest = [];
  for (let at = 0; at < args.length; at += 1) {
    if (args[at].startsWith("--")) {
      const key = args[at].slice(2);
      if (!given.has(key) || at + 1 >= args.length) throw new Error(`unknown option or no value: ${args[at]}`);
      given.set(key, args[(at += 1)]);
    } else {
      rest.push(args[at]);
    }
  }
  if (rest.length !== 1) {
    throw new Error("usage: node scripts/best-kit-bench.mjs <results folder> [--trio ...] [--evidence ...] [--buffs ...] [--roles a,b] [--setup ...] [--races A,B | all] [--tiers 0,4] [--heavy N | all] [--tie yes | no] [--json out.json]");
  }
  const tie = given.get("tie");
  if (tie !== "yes" && tie !== "no") throw new Error(`--tie is yes or no, not ${JSON.stringify(tie.slice(0, 20))}`);
  const heavy = given.get("heavy") === "all" ? Infinity : wholeNumber(given.get("heavy"), "--heavy", 1, 100000);
  const tiers = given.get("tiers") === "" ? TIERS : given.get("tiers").split(",").map((text) => wholeNumber(text, "a tier of --tiers", 0, TIERS.length - 1));
  return { folder: rest[0], given, tie: tie === "yes", heavy, tiers };
}

async function main() {
  const { folder, given, tie, heavy, tiers } = parse(process.argv.slice(2));
  const { default: loadHighs } = await import("highs");
  const highs = await loadHighs();
  const table = readItemTable(JSON.parse(fs.readFileSync(path.join(folder, "items.json"), "utf8")));
  const bundle = readBundle(JSON.parse(fs.readFileSync(path.join(folder, given.get("trio"), `engine-l${given.get("level")}.json`), "utf8")));
  const buffs = given.get("buffs");
  if (!Object.prototype.hasOwnProperty.call(bundle.buffs, buffs)) throw new Error(`the bundle has no buff set ${JSON.stringify(buffs.slice(0, 30))} (it has ${Object.keys(bundle.buffs).join(", ")})`);
  const list = (key) => given.get(key).split(",").filter(Boolean);
  const races = given.get("races") === "all" ? bundle.races.map((row) => row.code) : list("races");
  const views = viewsOf(bundle, { evidence: given.get("evidence"), buffs, roles: list("roles"), setup: given.get("setup"), races, tiers });
  if (views.length === 0) throw new Error("no view to look through: check the roles, the setup and the races against the bundle");
  const groups = Object.keys(bundle.weight_groups.groups);
  const header = {
    buffs,
    trio: given.get("trio"),
    level: Number(given.get("level")),
    evidence: given.get("evidence"),
    roles: list("roles").join(","),
    setup: given.get("setup"),
    races: given.get("races"),
    tiers: tiers.join(","),
    tie,
    views: views.length,
  };
  console.log(
    `buff set: ${buffs}   (${header.trio} level ${header.level}, ${header.evidence} evidence, roles ${header.roles}, setup ${header.setup}, ${header.races === "all" ? `all ${races.length} races` : `races ${header.races}`}, ` +
      `tiers ${header.tiers}, ${views.length} views, ${tie ? "with and without" : "without"} the tie stage)`,
  );
  const found = { ...header, ...measure({ highs, records: table.records, bundle, views, heavy, groups, tie, progress: (text) => console.log(text) }) };
  const shown = found.heavy.slice(0, 30);
  console.log(`\nthe heavy views (ms, one solve alone${found.heavy.length > shown.length ? `; the ${shown.length} slowest of ${found.heavy.length}` : ""}):`);
  for (const one of shown) console.log(`  plain ${one.plainMs.toFixed(0).padStart(6)}${one.canonicalMs === undefined ? "" : `  with the tie stage ${one.canonicalMs.toFixed(0).padStart(6)}`}  ${one.name}`);
  console.log(`\nms per solve over the ${found.heavy.length} heavy views of the buff set ${buffs}:`);
  for (const [label, row] of Object.entries(found.settings)) {
    for (const how of tie ? ["plain", "canonical"] : ["plain"]) {
      const s = row[how];
      console.log(`  ${label.padEnd(12)} ${how.padEnd(9)} median ${s.median.toFixed(0).padStart(6)}  p95 ${s.p95.toFixed(0).padStart(6)}  max ${s.max.toFixed(0).padStart(6)}  (n=${s.n})  slowest: ${s.slowest.name}`);
    }
  }
  console.log(`\nthe slowest view of the buff set ${buffs}: ${found.slowest.name} (${found.slowest.ms.toFixed(0)} ms, ${found.slowest.setting}, without the tie stage)`);
  if (given.get("json") !== "") fs.writeFileSync(given.get("json"), `${JSON.stringify(found, null, 1)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
