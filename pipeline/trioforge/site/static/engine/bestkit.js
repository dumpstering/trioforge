// The best kit of a view of the trio page, solved over the whole pool of the view as the precompute solves it. This is the one place where the pool, its pruning, the weights and the
// solve of a view are put together: the worker's mode "best-kit" (scenario.js) calls it, and so does the shard parity test (tests-js/shard-results.mjs), which solves every view the
// precompute published and holds the answer to its shard, so that the two cannot drift. It is also the one place where the weights of a request are put on a profile: the four
// Upgrade modes of the worker (scenario.js) make the profile of their session with `viewProfile`, as the best kit does.
//
//   bestKit({highs, records, bundle, scenario, tier, weights, weaponTierRate, budgetMs, canonical, now, options})
//        -> {answer, profile, pool, pruned, timings}
//   viewPool({records, bundle, scenario, tier, weights, weaponTierRate, options, now})
//        -> {profile, buffset, monkBins, pool, pruned, pruneOptions, pooledAt, prunedAt}: the profile of the view, its pool and the pool pruned, before any model is made
//   viewProfile(bundle, scenario, weights)        -> the profile of a view: the bundle's for the choices, with the weights of a request composed on the role's own (every mode)
//   weightsKey(weights)                           -> null for weights that are the role's own, else a text that is the same for the weights that compose the same profile
//   poolRecords(records, trio, {evidence, deity}) -> the records of the table that make the solve pool of an evidence level for a trio, in the order of the table
//   weightsAreOwn(weights)                        -> whether the weights of a request are the role's own (none, or all sliders at x1, no custom weight and no window)
//   BestKitError                                  -> the visitor's choices that the bundle does not have (a race, a role, a buff set, a setup, a weight, a weapon tier rate): not a fault of the data
//
// What a view is. `scenario` is {race, role, buffs, evidence, setup, deity?}, `tier` the tier every item of the pool is at (0 to 10), `records` the item table (`readItemTable`:
// a Map from the key of an item to its record) and `bundle` the trio's bundle (`readBundle`). The pool is what the precompute solves (`select_items` and `Context.pool` in
// pipeline/trioforge/precompute/grid.py):
//   * the records of the evidence level: the strict ones for the strict level, the strict and the wiki ones for any other;
//   * not the ones marked not-for-bis, and not the hidden ones that only a player may own;
//   * the ones that have a place in a kit, and that a class of the trio can wear (`poolRecords`);
//   * none locked to a deity, unless the scenario has a deity: then the ones locked to that deity too (the precompute assumes no deity, and its pools have none);
//   * each at the tier (`atTier` under the rules of the bundle), and then only the items the profile can use (`usableBy`: its class, race and deity). A race-only item that the race
//     cannot wear is not in the pool; the builder would leave it without a column, and the pruning would drop it, so the pool and the answer are the same either way.
// The pool is then pruned (`prune`) with the profile, the weapon setup, the buff set and the builder's options of the view. The pruning depends on the race only through the race-only
// items that the race can wear, which the precompute shares between the races that wear the same ones, so pruning with the profile of the race itself is the same pruning.
//
// The weights are the role's own, as the bundle has them (the very object), unless the request asks for others: then `weightsOverride` (weights.js) composes the sliders, the custom
// weights and the regen window on the role's own, with the mana of the trio (a trio with no mana pool has no weight on mana: that is the worker's to say, never the page's), and the
// profile is the bundle's with those weights. `weights` that are the role's own (`weightsAreOwn`) change nothing, but they are still held to the bundle's rules: a slider group there
// is not is a BestKitError at x1 as at x2. The weapons are paid the haste the kit counts, as the precompute pays them (the truthful solve of
// solve.js: one program for each haste a kit can count, the best value over them), unless `options.haste_assumed` fixes one (the parity test passes the options a shard records);
// the weights do not move the levels.
//
// The weapon tier rate. `weaponTierRate` is the percent of damage a weapon grows a tier, 5 or 10: the rule `tier.weapon_damage_pct` (10) is the default, and `at_tier(weapon_pct=)` is
// Python's reference. The items of the pool are made with it (`atTier` with `weaponPct`), so the pruning, which compares the damage the items carry, and the evaluator, which values the
// kit's items, use it without being told: nothing else reads the rate. A rate that is not 5 or 10 is a BestKitError.
//
// The solve is `solve` of solve.js on a session of its own, made and closed here: nothing is kept between two views, and a session that met a fault is never used again. `canonical`
// asks for the tie stage and the canonical placement of the precompute (the parity test); a browser's answer is without the tie stage. `budgetMs` is the time of the whole call,
// the pool and the pruning and the model included; `now` reads a clock in milliseconds. A solve that ran out of time answers with the status "time_limit" and an honest label, as
// solve.js does.
//
// Faults. What the visitor chose that the bundle does not have (a race, a role, a buff set, an evidence level, a setup the role does not play, a deity that is blank, a weight or a
// window that weightsOverride refuses, a tier that is not 0 to 10, a weapon tier rate that is not 5 or 10) is a BestKitError, whatever the mode. Anything else that the engine's functions raise (an item
// that atTier refuses, a profile that the evaluator will not read or that the bundle cannot give for choices it has, a bundle whose weight rules cannot be used, a solver that did what an answer
// cannot be made from) is not the visitor's, and goes on as it is.

import { CONSTANTS } from "./evaluate.js";
import { ITEM_DEFAULTS, atTier } from "./items.js";
import { usableBy } from "./path.js";
import { ChoiceError, assembleProfile } from "./profile.js";
import { WEAPON_TIER_RATES } from "./protocol.js";
import { prune } from "./prune.js";
import { closeSession, createSession, solveScenario } from "./solve.js";
import { MAX_TIER } from "./tiers.js";
import { WeightsError, weightsOverride } from "./weights.js";

/** A choice of the visitor that the data does not have, or weights the bundle's rules refuse. */
export class BestKitError extends Error {
  constructor(message) {
    super(message);
    this.name = "BestKitError";
  }
}

const defaultNow = () => performance.now();
const STRICT = ["strict"];
const STRICT_AND_WIKI = ["strict", "wiki"];
/** The code of a record that is not for best in slot (a temporary item, or one a quest takes on hand-in): the precompute never offers such an item. */
const NOT_FOR_BIS = "not-for-bis";
/** The places of the model's slot groups that an item can be worn in (an item that lists none of them is no wearable). */
const WEARABLE_SLOTS = new Set(CONSTANTS.slotGroups.map(([name]) => name).filter((name) => name !== "ANY"));
/** The name of the scenario of the session. */
const SCENARIO = "best-kit";

/**
 * The records that make the solve pool of an evidence level for a trio (`trio` the class codes; see the head of this file), in the order of the table. `records` is the Map of the
 * item table, or any list of records; `deity` is the deity of the scenario, or none.
 */
export function poolRecords(records, trio, { evidence, deity = null }) {
  const levels = evidence === "strict" ? STRICT : STRICT_AND_WIKI;
  const classes = new Set(trio);
  const found = [];
  for (const record of records instanceof Map ? records.values() : records) {
    if (!levels.includes(record.evidence.level)) continue;
    if (Array.isArray(record.evidence.codes) && record.evidence.codes.includes(NOT_FOR_BIS)) continue;
    if (record.owned_only === true) continue;
    if (record.deity !== undefined && record.deity !== null && (deity === null || deity === undefined || !record.deity.includes(deity))) continue;
    if (!record.slots.some((slot) => WEARABLE_SLOTS.has(slot))) continue;
    const allowed = record.classes ?? ITEM_DEFAULTS.classes;
    if (!allowed.includes("ALL") && !allowed.some((code) => classes.has(code))) continue;
    found.push(record);
  }
  return found;
}

/** Whether the weights of a request are the role's own: none, or every slider at x1, no custom weight and no regen window. */
export function weightsAreOwn(weights) {
  if (weights === undefined || weights === null) return true;
  const { multipliers, custom, regenT } = weights;
  if (multipliers !== undefined && multipliers !== null && Object.values(multipliers).some((position) => position !== 1)) return false;
  if (custom !== undefined && custom !== null && Object.keys(custom).length > 0) return false;
  return regenT === undefined || regenT === null;
}

/**
 * What a session is kept by, for the weights of a request: null for weights that are the role's own (they change nothing), else a text that is the same for the weights that
 * compose the same profile (the order of the tables, a slider at x1, an empty table or a window of null do not count), and another for any others. A key for weights that
 * `viewProfile` has not checked: it does not say they are allowed.
 */
export function weightsKey(weights) {
  if (weightsAreOwn(weights)) return null;
  const { multipliers, custom, regenT } = weights;
  const table = (values) => Object.keys(values ?? {}).sort().map((name) => [name, values[name]]);
  return JSON.stringify([table(multipliers).filter(([, position]) => position !== 1), table(custom), regenT ?? null]);
}

/**
 * The profile of a view: the bundle's for the choices (a race, a role, a buff set, an evidence level, perhaps a deity, and a weapon setup the role plays at the level), with the
 * weights of a request composed on the role's own when they are not the role's own. The one function for every mode of the worker. A BestKitError for a choice the bundle does not
 * have (the choices are checked first, and `assembleProfile` says so with a ChoiceError) and for weights its rules refuse (a slider group there is not, at x1 as at x2). Whatever
 * else goes wrong is not the asker's: it is an error of the bundle itself (rules of weights the engine cannot use, a profile it cannot give for choices it has).
 */
export function viewProfile(bundle, scenario, weights) {
  const { race, role, buffs, evidence, deity } = scenario;
  if (typeof evidence !== "string") throw new BestKitError("The scenario names no evidence level."); // (assembleProfile alone would take none, and the pool would be another)
  let profile;
  try {
    profile = assembleProfile(bundle, { race, role, buffs, evidence, deity });
  } catch (error) {
    if (error instanceof ChoiceError) throw new BestKitError(error.message); // (a BundleError that is not a choice is the bundle's own fault, and goes on as it is)
    throw error;
  }
  if (!profile.setups.includes(scenario.setup)) throw new BestKitError("This weapon setup is not one of the role's setups at this evidence level.");
  if (weights === undefined || weights === null) return profile;
  let composed;
  try {
    composed = weightsOverride(bundle, profile.weights, {
      multipliers: weights.multipliers,
      custom: weights.custom,
      regenT: weights.regenT,
      manaReachable: profile.pools.MANA.length > 0,
    });
  } catch (error) {
    if (error instanceof WeightsError) throw new BestKitError(error.message);
    throw error;
  }
  return weightsAreOwn(weights) ? profile : Object.freeze({ ...profile, weights: composed });
}

/** The options `atTier` takes for a weapon tier rate (`WEAPON_TIER_RATES` of protocol.js: 5 and 10, the rule's own): none for none, else the rate; a BestKitError for any other. */
function weaponOptions(rate) {
  if (rate === undefined) return undefined;
  if (!WEAPON_TIER_RATES.includes(rate)) throw new BestKitError(`The weapon tier rate is ${WEAPON_TIER_RATES.join(" or ")} percent a tier.`);
  return { weaponPct: rate };
}

/** The tier of the pool: a whole number from 0 to the highest tier. */
function checkTier(tier) {
  if (!Number.isInteger(tier) || tier < 0 || tier > MAX_TIER) throw new BestKitError(`The tier is a whole number from 0 to ${MAX_TIER}.`);
}

/** The items of the view's pool at the tier, as `atTier` gives them (at the weapon tier rate, when there is one): the records of `poolRecords` that the profile can use. */
function poolOf(records, bundle, profile, evidence, tier, weapon) {
  const usable = usableBy(profile);
  const items = [];
  for (const record of poolRecords(records, bundle.trio, { evidence, deity: profile.deity ?? null })) {
    const item = atTier(record, tier, bundle, weapon);
    if (usable(item)) items.push(item);
  }
  return items;
}

/**
 * The profile of a view, its pool at the tier and the pool pruned, before any model is made: the first half of `bestKit`, and the part of it that a test can hold to the
 * precompute's. Returns `{profile, buffset, monkBins, pool, pruned, pruneOptions, pooledAt, prunedAt}`: `pruneOptions` the options the pruning was given (the builder's
 * `options` and the Monk bins of the bundle) and `pooledAt` and `prunedAt` the clock `now` read when the pool and the pruning were done (two reads, and no other).
 */
export function viewPool({ records, bundle, scenario, tier, weights, weaponTierRate, options = {}, now = defaultNow }) {
  checkTier(tier);
  const weapon = weaponOptions(weaponTierRate);
  const profile = viewProfile(bundle, scenario, weights);
  const buffset = { set: bundle.buffs[scenario.buffs].set, table: bundle.buff_table };
  const monkBins = bundle.monk_bins === null ? undefined : bundle.monk_bins;
  const pool = poolOf(records, bundle, profile, scenario.evidence, tier, weapon);
  const pooledAt = now();
  const pruneOptions = monkBins === undefined ? options : { ...options, monk_bins: monkBins };
  const pruned = pool.length === 0 ? [] : prune(pool, profile, tier, scenario.setup, buffset, pruneOptions);
  return { profile, buffset, monkBins, pool, pruned, pruneOptions, pooledAt, prunedAt: now() };
}

/**
 * The best kit of a view (see the head of this file). Returns `{answer, profile, pool, pruned, timings}`: `answer` is the answer of `solve` (the exact value `F`, the `kit` of 22
 * places, the `buffs`, the `hasteAssumed`, the status and the label), `profile` the profile that was solved (frozen), `pool` the items of the view's pool and `pruned` the ones the
 * model was made of, and `timings` the milliseconds `{poolMs, pruneMs, buildMs, solveMs}` the parts took (the profile and the weights are in the first).
 */
export function bestKit({ highs, records, bundle, scenario, tier, weights, weaponTierRate, budgetMs, canonical = false, now = defaultNow, options = {} }) {
  checkTier(tier);
  const began = now();
  const { profile, buffset, monkBins, pool, pruned, pooledAt, prunedAt } = viewPool({ records, bundle, scenario, tier, weights, weaponTierRate, options, now });
  const session = createSession({ highs, profile, setup: scenario.setup, buffset, monkBins, options, now });
  try {
    // the truthful solve: the weapons are paid the haste the kit counts (one program for each haste a kit can count, solve.js), unless the options fix one
    const answer = solveScenario(session, { name: SCENARIO, items: pruned, options, budgetMs: Math.max(0, began + budgetMs - prunedAt), canonical });
    const done = now();
    const buildMs = answer.build.buildMs + answer.build.syncMs;
    return { answer, profile, pool, pruned, timings: { poolMs: pooledAt - began, pruneMs: prunedAt - pooledAt, buildMs, solveMs: done - prunedAt - buildMs } };
  } finally {
    closeSession(session);
  }
}
