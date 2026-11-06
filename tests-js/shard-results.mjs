// A folder of precompute results (the shards, the browser bundle and the item table: pipeline/trioforge/precompute/shards.py has the format), read and
// held to the browser engine, for tests-js/shard-parity.test.mjs. Nothing here is a test; nothing here is read by the site.
//
//   readResults(directory)                -> {table, trios}: the item table of the folder and, for each trio folder, each level that has a bundle and shards
//   chunksOf(results)                     -> the views of the folder in a fixed order: one chunk is a view across the races (evidence, buffs, role, setup, tier)
//   checkResults(results, {highs, ...})   -> {views, chunks, failures, ties, defaults, timing, ...}: every view solved by the engine and compared with its shard
//   pythonRound2(number)                  -> Python's round(number, 2), which is how a shard keeps F
//   parseSample("3/20")                   -> {index: 3, count: 20}
//   parsePart("3/12")                     -> {index: 3, count: 12}: the part of the work (TRIOFORGE_SHARD_PART), so that K processes can share one check
//   workOf(results, {...})                -> the units of work of a check (the plan of each defaults.json, the sampled chunks), and the part of them that is asked for
//
// What a view is. A shard row is [race, role, tier, setup, kit, F, gain, totals, buffs, haste]: one race in one view of the grid. The precompute
// (pipeline/trioforge/precompute/grid.py, `solve_chunk`) solved it like this, and so the engine is asked the same question, built from the very files the
// browser reads (items.json and engine-l<level>.json). It is asked of `bestKit` (engine/bestkit.js), the very function the worker calls for the best kit of a view of the
// trio page, so that the two cannot drift: nothing here makes a pool, prunes it or builds a model. The view is given to it with the tie stage and the builder options
// the shard records, and it does what the precompute did:
//
//   * the profile is the bundle's, for the race, role, buff set and evidence level of the view, with the deity the shard assumed and the role's own weights;
//   * the pool is the solve pool of the evidence level at the tier of the view: the records of the item table that are strict (for the strict level) or
//     strict and wiki (for the wiki level), that are not marked not-for-bis, that have no deity, that have a place in a kit and that a class of the trio can
//     wear (`select_items` and `Context.pool`), each at the tier. The race is not asked: the builder leaves out an item the race cannot wear, as Python's does;
//   * the pool is pruned as the chunk pruned it. The chunk prunes once for each set of race-only items that a race can wear, with the profile of the first race of
//     the chunk that wears that set; the pruning depends on the race only through those items, so pruning with the profile of the race itself is the same pruning. The
//     pruning is exact for the value, but which of several kits of equal value is the canonical one depends on the pool, and so does the haste the weapons were scored at;
//   * the model is built with the builder options the shard records, and solved with the tie stage and the canonical placement (`canonical: true`).
//
// What is compared: the exact value F, the kit place for place, the optional buffs and the haste assumed. A shard keeps F as `round(float(F), 2)` (shards.py,
// `_rounded`), so the engine's exact value is brought to that: the nearest double, then Python's round to two decimals (`pythonRound2`), and the two doubles
// must be equal. (The exact value is compared in full by the parity tests of the fixtures; a shard cannot hold it.)
//
// A tie of buffs. Two optional buffs of equal value give the same kit at the same value, and the engine may name the other one than the precompute did. A view whose F,
// kit and haste are equal and whose buff sets differ passes, and is counted and printed as a tie (`isBuffTie`); a difference in F, the kit or the haste still fails.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { bestKit, poolRecords } from "../pipeline/trioforge/site/static/engine/bestkit.js";
import { CONSTANTS } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";

/** A folder of results that cannot be held to the engine: it is not one run, or not what the precompute writes. Nobody's view is to blame. */
export class ResultsError extends Error {
  constructor(message) {
    super(message);
    this.name = "ResultsError";
  }
}

/** The shards of a trio, in the order the site and the precompute list them. */
export const SHARD_NAMES = Object.freeze(["strict-own", "strict-group", "wiki-own", "wiki-group"]);
const ITEM_KEYS = ["key", "name", "slots", "tier_rule", "arrival", "source", "evidence", "deity"];
const ENGINE_FILE = /^engine-l([1-9][0-9]*)\.json$/;
const ROW_FIELDS = 10;
/** The most a solve may take: the precompute sets no time limit, so neither does the engine here (the test has its own timeout). */
const BUDGET_MS = 3_600_000;
const RACES_FILE = new URL("../rules/races.json", import.meta.url);

// ---- reading -----------------------------------------------------------------------------------------------------------------------------

function readJson(path, label) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    throw new ResultsError(`${label}: cannot be read (${error.code ?? error.name})`);
  }
}

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** The races in the order of the table of races (rules/races.json), which is the order a chunk of the precompute solves them in; null when the file is not there. */
function tableRaceOrder() {
  try {
    const document = JSON.parse(readFileSync(RACES_FILE, "utf8"));
    return document.races.filter((race) => race.active).map((race) => race.code);
  } catch {
    return null;
  }
}

/** One shard, read and decoded: its rows with their kits as item keys, grouped into chunks (a view across the races). */
function readShard(folder, slug, name) {
  const where = `${slug}/${name}.json`;
  const document = readJson(join(folder, `${name}.json`), where);
  const need = (ok, problem) => {
    if (!ok) throw new ResultsError(`${where}: ${problem}`);
  };
  const [evidence, buffs] = name.split("-");
  need(document !== null && typeof document === "object" && !Array.isArray(document), "is not an object");
  need(document.version === 1, "is not format 1");
  need(document.trio === slug, "names another trio than its folder");
  need(document.evidence === evidence && document.buffs === buffs, "names another evidence level or buff set than its file name");
  need(Number.isInteger(document.level) && document.level >= 1, "has no level");
  need(document.solver !== null && typeof document.solver === "object" && document.solver.canonical === true,
    "was made without the tie stage (--plain), so its kits are not canonical and cannot be held to the engine's");
  need(Number.isInteger(document.pool) && document.pool >= 0, "has no pool size");
  need(document.build_options !== null && typeof document.build_options === "object", "has no build options");
  need(document.assumptions !== null && typeof document.assumptions === "object", "has no assumptions");
  for (const field of ["items", "kits", "buff_sets", "scenarios", "places", "roles"]) need(Array.isArray(document[field]), `has no list ${field}`);
  need(same(document.items_keys, ITEM_KEYS), "does not describe its item rows as the precompute writes them");
  need(document.places.length === CONSTANTS.slotGroups.reduce((sum, [, count]) => sum + Number(count.numerator), 0), "does not list the places of a kit");
  const keys = document.items.map((row) => row[0]);
  const kits = document.kits.map((kit, at) => {
    need(Array.isArray(kit) && kit.length === document.places.length, `kit ${at} is not a kit`);
    return kit.map((index) => {
      need(Number.isInteger(index) && index >= -1 && index < keys.length, `kit ${at} names an item the file does not list`);
      return index < 0 ? null : keys[index];
    });
  });
  const rows = document.scenarios.map((row, at) => {
    need(Array.isArray(row) && row.length === ROW_FIELDS, `scenario ${at} is not [race, role, tier, setup, kit, F, gain, totals, buffs, haste]`);
    const [race, role, tier, setup, kit, value, , , buffSet, haste] = row;
    need(typeof race === "string" && typeof role === "string" && typeof setup === "string", `scenario ${at} has no race, role or setup`);
    need(Number.isInteger(tier) && tier >= 0, `scenario ${at} has no tier`);
    need(Number.isInteger(kit) && kit >= 0 && kit < kits.length, `scenario ${at} names a kit the file does not list`);
    need(typeof value === "number" && Number.isFinite(value), `scenario ${at} has no value`);
    need(Number.isInteger(buffSet) && buffSet >= 0 && buffSet < document.buff_sets.length, `scenario ${at} names a buff list the file does not hold`);
    need(Number.isInteger(haste) && haste >= 0, `scenario ${at} has no assumed haste`);
    return { race, role, tier, setup, kit: kits[kit], F: value, buffs: document.buff_sets[buffSet], haste };
  });
  // a chunk is a view across the races; its place in a fixed order does not depend on the order of the rows
  const found = new Map();
  for (const row of rows) {
    const id = `${row.role}\u0000${row.setup}\u0000${row.tier}`;
    if (!found.has(id)) found.set(id, { role: row.role, setup: row.setup, tier: row.tier, rows: [] });
    found.get(id).rows.push(row);
  }
  const roleAt = (role) => document.roles.indexOf(role);
  const setupAt = (chunk) => (document.setups?.[chunk.role] ?? []).indexOf(chunk.setup);
  const chunks = [...found.values()].sort((a, b) => roleAt(a.role) - roleAt(b.role) || setupAt(a) - setupAt(b) || a.tier - b.tier || (a.setup < b.setup ? -1 : a.setup > b.setup ? 1 : 0));
  return {
    name,
    evidence,
    buffs,
    level: document.level,
    places: document.places,
    setups: document.setups !== null && typeof document.setups === "object" ? document.setups : {},
    races: Array.isArray(document.races) ? document.races : [],
    items: document.items,
    buildOptions: document.build_options,
    assumptions: document.assumptions,
    pool: document.pool,
    keptFirst: document.solver.kept_first ?? 0,
    release: [document.data_release, document.rules_version],
    rows,
    chunks,
  };
}

/**
 * The results of a folder: its item table (`items.json`, read by the engine's `readItemTable`) and, for each folder of a trio (one that holds a shard),
 * each level that has a bundle (`engine-l<level>.json`, read by `readBundle`) and shards. A `ResultsError` for a folder that is not one run: a shard of
 * another release or level than its bundle, a bundle and an item table made from other inputs, a shard that shows an item the table lacks.
 */
export function readResults(directory) {
  const root = resolve(directory);
  if (!existsSync(root)) throw new ResultsError("the folder of results does not exist");
  let table;
  try {
    table = readItemTable(readJson(join(root, "items.json"), "items.json"));
  } catch (error) {
    if (error instanceof ResultsError) throw error;
    throw new ResultsError(`items.json: ${error.message}`);
  }
  const order = tableRaceOrder();
  const trios = [];
  for (const entry of readdirSync(root, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))) {
    if (!entry.isDirectory()) continue;
    const folder = join(root, entry.name);
    const present = SHARD_NAMES.filter((name) => existsSync(join(folder, `${name}.json`)));
    if (present.length === 0) continue;
    const slug = entry.name;
    const shards = present.map((name) => readShard(folder, slug, name));
    const bundles = readdirSync(folder).map((name) => ENGINE_FILE.exec(name)).filter((found) => found !== null).map((found) => Number(found[1])).sort((a, b) => a - b);
    for (const shard of shards) {
      if (!bundles.includes(shard.level)) throw new ResultsError(`${slug}/${shard.name}.json: is of level ${shard.level}, and the folder has no bundle (engine-l${shard.level}.json) for it`);
    }
    const levels = [];
    for (const level of bundles) {
      const mine = shards.filter((shard) => shard.level === level);
      if (mine.length === 0) continue; // a bundle with no shard has nothing precomputed to be held to
      levels.push(readLevel(folder, slug, level, mine, table, order));
    }
    trios.push({ slug, levels });
  }
  if (trios.length === 0) throw new ResultsError("the folder holds no trio (a folder with a shard in it)");
  return { table, trios };
}

function readLevel(folder, slug, level, shards, table, raceOrder) {
  const where = `${slug}/engine-l${level}.json`;
  let bundle;
  try {
    bundle = readBundle(readJson(join(folder, `engine-l${level}.json`), where));
  } catch (error) {
    if (error instanceof ResultsError) throw error;
    throw new ResultsError(`${where}: ${error.message}`);
  }
  const need = (ok, problem) => {
    if (!ok) throw new ResultsError(`${where}: ${problem}`);
  };
  need(bundle.trio.map((code) => code.toLowerCase()).join("-") === slug, "is not the bundle of this trio");
  need(bundle.level === level, "is not of the level its file name says");
  need((bundle.inputs ?? null) === table.inputs, "was made from other inputs than items.json (another catalog, or other seen flags): run the precompute again");
  need(bundle.data_release === table.dataRelease && bundle.rules_version === table.rulesVersion, "is not of the data release and rules version of items.json");
  for (const shard of shards) {
    need(shard.release[0] === bundle.data_release && shard.release[1] === bundle.rules_version, `${shard.name}.json is not of the data release and rules version of the bundle`);
    need(bundle.buffs[shard.buffs] !== undefined, `has no buff set ${shard.buffs}, which ${shard.name}.json names`);
    need(bundle.evidence_levels.includes(shard.evidence), `has no evidence level ${shard.evidence}, which ${shard.name}.json names`);
    need(same(shard.assumptions.aa, bundle.profile_common.aa), `has other default AA than ${shard.name}.json assumed`);
    // the pool of the evidence level has as many items as the precompute's had: a pool made another way (a class, a level, a deity, a not-for-bis item) is found here
    const pool = poolRecords(table.records, bundle.trio, { evidence: shard.evidence }).length;
    need(pool === shard.pool, `the ${shard.evidence} pool made from items.json has ${pool} items, and ${shard.name}.json says its pool had ${shard.pool}`);
    for (const row of shard.items) {
      const record = table.records.get(row[0]);
      need(record !== undefined && record.evidence.level === row[6] && record.tier_rule === row[3],
        `${shard.name}.json shows an item that items.json lacks or describes otherwise (a kit item: ${row[0]})`);
    }
  }
  // the order a chunk solves its races in is the order of the table of races; a race the table does not know keeps the order of the shard
  const rank = (race, shard) => {
    const at = raceOrder === null ? -1 : raceOrder.indexOf(race);
    return at >= 0 ? at : raceOrder === null ? shard.races.findIndex((row) => row.code === race) : raceOrder.length;
  };
  for (const shard of shards) {
    for (const chunk of shard.chunks) chunk.rows.sort((a, b) => rank(a.race, shard) - rank(b.race, shard));
  }
  return { slug, level, bundle, shards };
}

/** The views of the folder in a fixed order, a chunk each: the trios by name, the levels up, the shards in `SHARD_NAMES` order, then role, setup and tier. */
export function chunksOf(results) {
  const found = [];
  for (const trio of results.trios) {
    for (const level of trio.levels) {
      for (const shard of level.shards) {
        for (const chunk of shard.chunks) found.push({ index: found.length, trio, level, shard, chunk });
      }
    }
  }
  return found;
}

/** The sample a text asks for, "i/n": the chunks whose place in `chunksOf` is i more than a multiple of n (0 <= i < n). Every view is in one of the n samples. */
export function parseSample(text) {
  const found = /^([0-9]{1,6})\/([1-9][0-9]{0,5})$/.exec(String(text).trim());
  if (found === null) throw new ResultsError(`the sample is "i/n", the chunks i, i+n, i+2n ...: not ${JSON.stringify(String(text).slice(0, 40))}`);
  const [index, count] = [Number(found[1]), Number(found[2])];
  if (index >= count) throw new ResultsError(`the sample "${index}/${count}" has no chunks: i is from 0 to n-1`);
  return { index, count };
}

/**
 * The part of the work a text asks for, "k/K" (TRIOFORGE_SHARD_PART): the units of work (`workOf`) whose place is k more than a multiple of K (0 <= k < K). Written
 * as strictly as `parseSample`, which it resembles: K parts, k = 0 to K-1, run side by side, check every unit once.
 */
export function parsePart(text) {
  const found = /^([0-9]{1,6})\/([1-9][0-9]{0,5})$/.exec(String(text).trim());
  if (found === null) throw new ResultsError(`the part is "k/K", the units k, k+K, k+2K ... of the work: not ${JSON.stringify(String(text).slice(0, 40))}`);
  const [index, count] = [Number(found[1]), Number(found[2])];
  if (index >= count) throw new ResultsError(`the part "${index}/${count}" has no units: k is from 0 to K-1`);
  return { index, count };
}

// ---- Python's round -----------------------------------------------------------------------------------------------------------------------

/**
 * Python's `round(x, 2)` for a finite double: the decimal with two places nearest to the exact value of x, a tie going to the even last digit, as the double
 * nearest to that decimal. (A shard keeps F that way, shards.py `_rounded`.) Done on the exact value of x with BigInt, so that no step goes through a
 * double that is not x itself.
 */
export function pythonRound2(x) {
  if (typeof x !== "number" || !Number.isFinite(x)) throw new ResultsError("only a finite number can be rounded");
  if (x === 0) return 0;
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, Math.abs(x));
  const bits = view.getBigUint64(0);
  const biased = Number((bits >> 52n) & 0x7ffn);
  const fraction = bits & ((1n << 52n) - 1n);
  const mantissa = biased === 0 ? fraction : fraction | (1n << 52n);
  const exponent = (biased === 0 ? 1 : biased) - 1075; // |x| = mantissa * 2^exponent
  const scaled = mantissa * 100n;
  let hundredths;
  if (exponent >= 0) {
    hundredths = scaled << BigInt(exponent);
  } else {
    const shift = BigInt(-exponent);
    const quotient = scaled >> shift;
    const rest = scaled - (quotient << shift);
    const half = 1n << (shift - 1n);
    hundredths = rest > half || (rest === half && (quotient & 1n) === 1n) ? quotient + 1n : quotient;
  }
  const rounded = Number(`${hundredths}e-2`);
  return x < 0 ? -rounded : rounded;
}

// ---- the engine's side of a view -----------------------------------------------------------------------------------------------------------

/** The kit of an engine answer as item keys (null for an empty place). */
const keysOf = (kit) => kit.map((item) => (item === null ? null : item.key));

function kitDifference(want, have, places) {
  let count = 0;
  let first = -1;
  for (let place = 0; place < want.length; place += 1) {
    if (want[place] !== have[place]) {
      count += 1;
      if (first < 0) first = place;
    }
  }
  if (count === 0) return null;
  return `kit: ${count === 1 ? "1 place differs" : `${count} places differ`}, the first ${places[first]}: shard ${want[first] ?? "empty"}, engine ${have[first] ?? "empty"}`;
}

const BUFFS_LINE = "buffs: ";

/**
 * The ways the engine's answer for a row differs from the row, in the order F, kit, haste, buffs (the first is the first difference that matters: the buffs come
 * last, because they alone are a tie, see `isBuffTie`); empty when it is the row. `got` is the answer of `solve` (solve.js). A row kept as a shard keeps it: F rounded
 * as Python rounds it (see the head of this file).
 */
export function compareRow(shard, row, got) {
  const found = [];
  if (got.status !== "optimal") found.push(`the engine's solve ended "${got.status}", not optimal`);
  if (got.F === null || got.kit === null) {
    found.push("the engine found no kit");
    return found;
  }
  const value = pythonRound2(got.F.toNumber());
  if (value !== row.F) found.push(`F: shard ${row.F}, engine ${value} (exactly ${got.F.toString()})`);
  const have = keysOf(got.kit);
  const kit = kitDifference(row.kit, have, shard.places);
  if (kit !== null) found.push(kit);
  if (got.hasteAssumed !== row.haste) found.push(`haste assumed: shard ${row.haste}, engine ${got.hasteAssumed}`);
  const buffs = [...got.buffs].sort((a, b) => a - b);
  const wanted = [...row.buffs].sort((a, b) => a - b);
  if (!same(buffs, wanted)) found.push(`${BUFFS_LINE}shard ${JSON.stringify(wanted)}, engine ${JSON.stringify(buffs)}`);
  return found;
}

/**
 * Whether the differences `compareRow` found are a tie: the optional buffs differ and nothing else does, so F, the kit and the assumed haste are equal. Two buffs of
 * equal value give the same kit at the same value, and which of them a solver names is no fault of either (the engine and the precompute break that tie in their own
 * way). A tie passes, and the check counts it and prints it; a difference in F, the kit or the haste, with the buffs or without them, fails.
 */
export function isBuffTie(found) {
  return found.length === 1 && found[0].startsWith(BUFFS_LINE);
}

/** What the engine found for a row of a shard, kept to compare `defaults.json` with: by trio, level, evidence level, buff set, role, setup, tier and race. */
const seenKey = (level, shard, chunk, race) => `${level.slug}|${level.level}|${shard.evidence}|${shard.buffs}|${chunk.role}|${chunk.setup}|${chunk.tier}|${race}`;

const viewName = (level, shard, chunk, race) => `${level.slug} L${level.level} ${shard.evidence}/${shard.buffs} ${race} ${chunk.role} ${chunk.setup} +${chunk.tier}`;

/**
 * Solve the views of a chunk with the engine, as the precompute solved them (see the head of this file), and compare each with its row. Returns the
 * failures; `tally` gets the counts and the times, and `seen` (a Map) the engine's value of every row it solved, by view.
 */
function checkChunk({ highs, table, level, shard, chunk }, tally, seen) {
  const failures = [];
  const options = { any_rule: shard.buildOptions.any_rule, haste_assumed: shard.buildOptions.haste_assumed };
  const deity = shard.assumptions.deity ?? undefined;
  for (const row of chunk.rows) {
    const name = viewName(level, shard, chunk, row.race);
    try {
      const scenario = { race: row.race, role: chunk.role, buffs: shard.buffs, evidence: shard.evidence, setup: chunk.setup };
      if (deity !== undefined) scenario.deity = deity;
      // the pool, its pruning, the model and the solve are the engine's: the function the worker calls for the best kit of a view, here with the tie stage
      const solved = bestKit({ highs, records: table.records, bundle: level.bundle, scenario, tier: chunk.tier, budgetMs: BUDGET_MS, canonical: true, options });
      const got = solved.answer;
      const { timings } = solved;
      tally.pruneMs += timings.poolMs + timings.pruneMs;
      tally.buildMs += timings.buildMs;
      tally.solveMs += timings.solveMs;
      if (timings.solveMs > tally.slowest.ms) tally.slowest = { ms: timings.solveMs, name };
      if (got.F !== null) seen.set(seenKey(level, shard, chunk, row.race), got.F);
      const found = compareRow(shard, row, got);
      if (isBuffTie(found)) tally.ties.push({ name, first: found[0] });
      else if (found.length > 0) {
        const model = new Set(solved.pruned.map((item) => item.key));
        const inPool = new Set(solved.pool.map((item) => item.key));
        const engineKit = got.kit === null ? null : keysOf(got.kit);
        failures.push({
          name,
          first: found[0],
          all: found,
          shardKit: row.kit,
          engineKit,
          kitDiffers: found.some((text) => text.startsWith("kit:")),
          // where the shard's items at the places that differ stand in the engine's own pool: a mapping of the test that is wrong shows here
          shardItems: [...new Set(row.kit.filter((key, place) => key !== null && (engineKit === null || engineKit[place] !== key)))]
            .slice(0, 6)
            .map((key) => `${key}: ${model.has(key) ? "in the engine's pruned pool" : inPool.has(key) ? "pruned away by the engine" : "not in the engine's pool"}`),
          keptFirst: shard.keptFirst,
        });
      }
    } catch (error) {
      failures.push({ name, first: `the engine stopped: ${error.name}: ${String(error.message).slice(0, 200)}`, all: [] });
    } finally {
      tally.views += 1;
    }
  }
  return failures;
}

// ---- the default answer ------------------------------------------------------------------------------------------------------------------

/**
 * The default answer of each trio and level of the folder that has a `defaults.json`: the document, and the chunks it is made from (the default view, one chunk for
 * each weapon setup of its role: `{level, shard, chunks}`). A folder whose default view is not in its shards has none.
 */
function defaultsPlans(results, directory) {
  const plans = [];
  for (const trio of results.trios) {
    for (const level of trio.levels) {
      const path = join(directory, level.slug, "defaults.json");
      if (!existsSync(path)) continue;
      const document = readJson(path, `${level.slug}/defaults.json`);
      const view = document?.view;
      const shard = level.shards.find((candidate) => candidate.evidence === view?.evidence && candidate.buffs === view?.buffs);
      if (shard === undefined || !Array.isArray(document.races) || document.race === null) continue;
      plans.push({ level, shard, document, chunks: shard.chunks.filter((chunk) => chunk.role === view.role && chunk.tier === view.tier) });
    }
  }
  return plans;
}

/**
 * `defaults.json` against the values the engine found for the default view: the value and the best setup of each race, then the default race, the runner-up and
 * the margin (`_best_setups` and `default_race` in the precompute). `seen` holds the engine's value of every row it solved. Returns the differences, or null when
 * the engine did not solve a view the answer is made from.
 */
function checkDefaults({ level, shard, document, chunks }, seen) {
  const { view } = document;
  const order = shard.races.map((race) => race.code);
  const legal = new Set(shard.races.filter((race) => race.legal).map((race) => race.code));
  const found = [];
  const values = new Map();
  for (const row of document.races) {
    // the best setup of the race: the highest value, the first of the role's setups (in the order of the shard) on a tie
    let top = null;
    for (const setup of shard.setups[view.role] ?? []) {
      const chunk = chunks.find((candidate) => candidate.setup === setup);
      const value = chunk === undefined ? undefined : seen.get(seenKey(level, shard, chunk, row.race));
      if (value === undefined) return null;
      const number = value.toNumber();
      if (top === null || number > top.number) top = { number, setup };
    }
    if (top === null) return null;
    values.set(row.race, top.number);
    const name = `defaults.json ${level.slug} L${level.level} ${row.race} ${view.role} +${view.tier} ${view.evidence}/${view.buffs}`;
    if (pythonRound2(top.number) !== row.F) found.push({ name, first: `F: file ${row.F}, engine ${pythonRound2(top.number)}`, all: [] });
    if (top.setup !== row.setup) found.push({ name, first: `best setup: file ${row.setup}, engine ${top.setup}`, all: [] });
  }
  // the default race is the creation-legal race with the highest value (the first in display order on a tie); the margin is its lead over the next one
  const ranked = order.filter((race) => legal.has(race) && values.has(race)).sort((a, b) => values.get(b) - values.get(a) || order.indexOf(a) - order.indexOf(b));
  const name = `defaults.json ${level.slug} L${level.level}`;
  if (ranked.length > 0 && ranked[0] !== document.race) found.push({ name, first: `default race: file ${document.race}, engine ${ranked[0]}`, all: [] });
  if (ranked.length > 1 && ranked[1] !== document.runner_up_race) found.push({ name, first: `runner-up race: file ${document.runner_up_race}, engine ${ranked[1]}`, all: [] });
  if (ranked.length > 1) {
    const margin = pythonRound2(values.get(ranked[0]) - values.get(ranked[1]));
    if (margin !== document.margin) found.push({ name, first: `margin: file ${document.margin}, engine ${margin}`, all: [] });
  }
  return found;
}

// ---- the check ----------------------------------------------------------------------------------------------------------------------------

/**
 * The work of a check, in a fixed order, as units that no part divides: the plan of each `defaults.json` (the chunks of its default view, which are solved and then
 * held to the file together) and then each other chunk that the sample takes (a chunk of a plan belongs to that plan, once). A unit is `{id, plan, units}`: `id` its place in
 * the order, `plan` the plan of `defaultsPlans` or null, `units` the chunks of `chunksOf` it is made of. `part` is `{index, count}` (`parsePart`); with it, only the units
 * whose id is `index` more than a multiple of `count` are kept, so that the `count` parts hold every unit exactly once. Returns `{items, plans, wanted, total}`: the
 * units kept, their plans, their chunks in the order of `chunksOf`, and the views those hold. A part whose `index` is at least the number of units (more parts than units) holds none, checks
 * nothing and passes: K need not be known to be small enough. The arguments are those of `checkResults`.
 */
export function workOf(results, { directory = null, sample = null, select = null, part = null } = {}) {
  const all = chunksOf(results);
  const plans = directory !== null && select === null ? defaultsPlans(results, directory) : []; // (every run: a sample must not leave the defaults out)
  const byChunk = new Map(all.map((unit) => [unit.chunk, unit]));
  const taken = new Set();
  const items = [];
  for (const plan of plans) {
    const mine = plan.chunks.map((chunk) => byChunk.get(chunk)).filter((unit) => unit !== undefined);
    for (const unit of mine) taken.add(unit);
    items.push({ id: items.length, plan, units: mine });
  }
  for (const unit of all) {
    if (taken.has(unit) || !((sample === null || unit.index % sample.count === sample.index) && (select === null || select(unit)))) continue;
    items.push({ id: items.length, plan: null, units: [unit] });
  }
  const kept = part === null ? items : items.filter((item) => item.id % part.count === part.index);
  const wanted = kept.flatMap((item) => item.units).sort((a, b) => a.index - b.index);
  const total = wanted.reduce((sum, unit) => sum + unit.chunk.rows.length, 0);
  return { items: kept, plans: kept.filter((item) => item.plan !== null).map((item) => item.plan), wanted, total };
}

/**
 * Solve every view of the folder (or of a sample of its chunks, or of a part of the work: `part`, see `workOf`) with the engine and compare each with its shard. `highs` is the loaded solver; `sample` is
 * `{index, count}` (`parseSample`); `select(unit)` keeps the chunks it says yes to (a test of the check itself; no sample, no `defaults.json`); `progress(text)` is
 * told how far the check is every few seconds. `directory` is the folder, for `defaults.json`: it is checked in every run, of the whole folder or of any sample (the
 * few chunks of the default view are solved besides the sample's own, so no sample leaves the defaults out; n samples run side by side check them n times, and K parts
 * check each of them once: a plan is in one part).
 *
 * Returns `{views, planned, chunks, failures, ties, defaults, defaultsChecked, timing}`: `views` the number of views checked (`planned` the number the chunks asked for hold),
 * `failures` are `{name, first, all, ...}` in the order the views were checked (`first` is the first difference), `ties` are the `{name, first}` of the views that passed
 * as ties (`isBuffTie`: only the optional buffs differ), `defaults` the differences of `defaults.json`, `defaultsChecked` how many trios and levels it was checked for.
 */
export function checkResults(results, { highs, directory = null, sample = null, select = null, part = null, progress = null } = {}) {
  const began = performance.now();
  const tally = { views: 0, pruneMs: 0, buildMs: 0, solveMs: 0, slowest: { ms: 0, name: null }, ties: [] };
  const failures = [];
  const seen = new Map();
  let last = began;
  const { plans, wanted, total } = workOf(results, { directory, sample, select, part });
  for (const unit of wanted) {
    failures.push(...checkChunk({ highs, table: results.table, level: unit.level, shard: unit.shard, chunk: unit.chunk }, tally, seen));
    const now = performance.now();
    if (progress !== null && now - last >= 5000) {
      last = now;
      progress(`${tally.views} of ${total} views checked, ${failures.length} differ, ${((now - began) / 1000).toFixed(0)} s`);
    }
  }
  const defaults = [];
  let defaultsChecked = 0;
  for (const plan of plans) {
    const found = checkDefaults(plan, seen);
    if (found !== null) {
      defaultsChecked += 1;
      defaults.push(...found);
    }
  }
  return {
    views: tally.views,
    planned: total,
    chunks: wanted.length,
    failures,
    ties: tally.ties,
    defaults,
    defaultsChecked,
    timing: { totalMs: performance.now() - began, pruneMs: tally.pruneMs, buildMs: tally.buildMs, solveMs: tally.solveMs, slowest: tally.slowest },
  };
}
