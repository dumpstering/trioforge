// The Upgrade tab's functions: Equip now, the farm path, the best sets and Every slot, on the owned set of a visitor and the candidates they could acquire.
// A port of pipeline/trioforge/upgrade.py (which defines what an addition is, and is the truth), held to the sessions Python recorded by
// tests-js/engine-path.test.mjs: Equip now, each step of the path, why it stopped, the best 2 and 3 sets, and Every slot.
//
//   sessionHaste(profile, owned, candidates, setup, buffset, options)  -> the one haste percent a session values every kit at (the caller's `haste_assumed`), else null
//   classify(item, owned)                                -> ["copy" | "upgrade" | "new", the tier of the owned copy an upgrade is made from]
//   usableBy(profile)                                    -> a function of an item: can the profile use it (a class of the trio, a deity it admits, a race it allows)?
//   equipNow(session, owned, {budgetMs, canonical})      -> the answer of solve.js: the best kit from the owned items alone
//   farmPath(session, owned, candidates, {steps, budgetMs, canonical, onStep}) -> {steps, stopped, hasteAssumed, baseline, elapsedMs}: `hasteAssumed` is Equip now's
//   createFarmPath(session, owned, candidates, {steps, budgetMs, canonical, onBegin}) -> {start, next, stop, result}: the same path, one call at a time
//   bestSets(session, owned, candidates, k, {budgetMs, canonical}) -> {k, acquired, F, gain, hasteAssumed, kit, buffs, status, label, solution, baseline, elapsedMs}
//   everySlot(session, kit, candidates, {buffs, limit, owned}) -> for each of the 22 places the best swaps, the rest of the kit held fixed; the copies of the owned items are counted
//
// `owned` is a list of `[item, count]` pairs (the items the visitor owns, each at the tier of the dump; a Map of item to count is one), `candidates` a
// list of items (what could be acquired, each at the tier of the tier mode; no ident twice), `session` what `createSession` of solve.js gives. Values are
// exact (Rationals from the evaluator), never the solver's.
//
// What an addition is, and the three kinds, are in upgrade.py: an addition is one more copy of a candidate, acquired and worn at the candidate's tier;
// "copy" when the candidate is owned at its tier, "upgrade" when the same key is owned at a lower tier (the highest such tier: that copy becomes the
// candidate, so the key has no more copies than before), "new" otherwise. The farm path's step k is the exact best single addition after the steps
// before it, found on one Best-1 model (the builder's `max_new = 1`) that stays in the session: each step adds the winner to the owned set (as one more
// copy, or as an upgraded copy) and the counts it changes are bounds and rows of the solver's model, changed in place where the columns are the same
// (solve.js), and the solve starts from the last kit (the first step from the kit of Equip now, which wears only what is owned: HiGHS completes the
// rest). Each step prunes its own pool with the owned-aware pruning (prune.js), because what is owned and which candidates are upgrades changes from
// step to step. Every solve is the truthful one of solve.js (`solveScenario`): the weapons are paid the haste the kit counts, so the value of a kit is the
// same wherever it stands and a step's gain is never a revaluation of the kit it started from; the options of the session may fix one haste for every kit instead.
//
// Of additions of exactly the same value. The solve of a step gives one of them, and which one is the solver's path (the canonical solve of Python takes the one of the kit that comes
// first in the order of kits, a visitor's solve, which runs no tie stage, whatever HiGHS reached first): so after it the step looks for a smaller one, the same program with only the
// candidates before the one found on offer (the others held at none in `owned_caps`, on the same pool, in a scenario of its own so that the model of the step stays for the next step), and if its best value is exactly
// the step's the addition it found is the next to look before, until none ties. The step is the first by `(key, tier)` of the additions worth exactly the best value, in the canonical
// path and in the visitor's alike (`_earlier_equal` in upgrade.py), and its kit is the solve of that addition alone (canonical when the path is; the kit of the look when it is not).
// The look is a solve of the same kind as the step's, so a step costs one more; a path with no step that has a smaller candidate costs no more.
//
// The stepper. `createFarmPath` makes the path and does nothing else (the deadline is fixed there: the time between the calls that follow counts against the
// budget); `start()` solves Equip now and gives its answer (`baseline` of farmPath), once, first; `next()` makes the next step and gives exactly the object that
// farmPath's `onStep` is called with, or null once the path has ended; `stop()` ends the path before its next step (the next call of `next()` gives null and
// the path's `stopped` is "stopped"); `result()` is what farmPath returns, valid once `next()` has given null. farmPath is a loop over it. What a caller does
// between two calls (the worker sends the step to the page, and looks for a stop) is its own business and costs the path nothing but the time it takes. The stepper's
// request may have an `onBegin(number)`, called when `next()` begins a step: once the step has passed the checks of the stop, the limit and the budget, and before its plan is
// made. A caller that tells someone which step it is working on does it from there, and so never names a step that is not begun.
//
// The budget. `budgetMs` is the whole time of the call, and every solve of the path may use all of it that is left: Equip now first, then each step. So
// the first steps are found whatever the number of steps asked for (they matter most), and a later step that does not finish costs the earlier ones
// nothing. Equip now always runs, with what is left, which may be nothing: it then ends at once (with no kit, unless the solver had one at once), and
// so does the path. The path ends when a solve is not proven optimal (its time ran out inside it) or when the budget is spent before a step begins:
// nothing of a step is started once the budget is spent, neither its plan, its pruning, its model nor its solve (`stopped` is "time"). A step whose
// solve is not proven the best carries the status "time_limit" and the label of solve.js when its kit adds something (its gain is the incumbent's exact
// value less the value before), and ends the path; a step whose kit adds nothing is reported as a step that was not found ("not found in time"), passed
// to `onStep` like the others, and ends it too. A path that ran its course says why as Python does: "limit" (the steps asked for were made) or
// "no-gain" (no addition improves the value, or the candidates offer none). The limits handed to HiGHS never exceed what is left of the budget when they
// are handed over; a call can still overrun the budget, by the lag of HiGHS past its limit (it looks at the clock now and then) and by the work around a
// solve that was begun in time: the exact value of its kit, and the pruning and the model of a step that began with a little time left. In canonical
// mode (the tests, and the checks of a precomputed scenario) every solve gives its tie stage the same allowance as its first stage, so a call can take
// about twice `budgetMs`.
//
// The best sets (`best_sets` in upgrade.py) are the best kit when up to k additions are made at once: sets, not a path (the best 2 can be worth more than
// the first two steps, and never less with one candidate per key, as the tier modes give: the k steps of the path are k additions, and a set may upgrade an owned
// copy and then add copies of the upgrade).
// One model with `max_new = k`, in a scenario of its own, "best-<k>", solved after Equip now (whose value the gain is counted from),
// from the kit of Equip now, which wears nothing that is not owned and so is feasible there. `acquired` lists what the kit acquires as `{ident, item, kind,
// sourceTier}`, in the order the reference lists it (each upgrade followed by the copies of its target, then the new items, then the copies of owned items);
// when no set improves the value (or the candidates offer none) it is empty, the value and kit are Equip now's and the gain 0. The same time rules as the path: every solve may use all the time that is left, nothing of the set is begun once the budget is
// spent, a set that ran out of time with an incumbent that adds something is labelled "best found, not proven optimal", and one with no incumbent (or an
// incumbent that adds nothing, which the time does not let it call the best) is "not found in time", with no value.
//
// The scenarios "equip-now", "best-1" and "best-<k>" of the session belong to these functions (they keep their models there between calls); a caller's own
// scenarios take other names.

import { SLOT_INSTANCES, CONSTANTS, evaluate, evaluateTruthful, profileOf } from "./evaluate.js";
import { CLASS_CODES } from "./items.js";
import { ModelError, NO_BOW, compareText, ident, isBow, readItem, readOptions } from "./model.js";
import { fitGroups, prune } from "./prune.js";
import { LABEL_NO_INCUMBENT } from "./protocol.js";
import { builderOptions, solveScenario } from "./solve.js";

/** An input that is not what the Upgrade functions read: the message says which. */
export class PathError extends Error {
  constructor(message) {
    super(message);
    this.name = "PathError";
  }
}

const fail = (message) => new PathError(message);

/** The scenarios the functions keep in the session: Equip now, and the persistent Best-1 model of the farm path. */
const EQUIP_NOW = "equip-now";
const BEST_1 = "best-1";
/** The scenario of the look for an earlier equal addition of a step: a model of its own, so that the model of the step stays as it is for the next step. */
const BEST_1_LOOK = "best-1-look";
/** The most additions the path makes at once (the Best-1 model), and the steps it makes unless asked for fewer (`farm_path` in upgrade.py). */
const MAX_NEW = 1;
const DEFAULT_STEPS = 8;
const DEFAULT_SWAPS = 3;
/** An owned set is a list of `[item, count]` pairs. */
const OWNED_ENTRY_LENGTH = 2;
/** The longest text of the caller's that a message quotes. */
const SHOWN_CHARS = 40;
const KIND_COPY = "copy";
const KIND_UPGRADE = "upgrade";
const KIND_NEW = "new";
const STATUS_OPTIMAL = "optimal";
const STOP_LIMIT = "limit";
const STOP_NO_GAIN = "no-gain";
const STOP_TIME = "time";
const STOP_STOPPED = "stopped";

const CLASS_SET = new Set(CLASS_CODES);
const [PRIMARY, SECONDARY] = CONSTANTS.handPlaces;
const PRIMARY_INDEX = SLOT_INSTANCES.indexOf(PRIMARY);
const SECONDARY_INDEX = SLOT_INSTANCES.indexOf(SECONDARY);
const PLACES = SLOT_INSTANCES.length;
const DISTINCT_PLACES = [...new Set(SLOT_INSTANCES)];

const isRecord = (value) => typeof value === "object" && value !== null && !Array.isArray(value);
const show = (value) => (typeof value === "string" && value.length <= SHOWN_CHARS ? JSON.stringify(value) : typeof value);

/** A field of an object that the caller gave, if it is its own (never one that the prototype has). */
function own(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key) ? object[key] : undefined;
}

const byKeyThenTier = (a, b) => compareText(a.key, b.key) || a.tier - b.tier;

// ---- the arguments ------------------------------------------------------------------------------------------------------------------------

function checkSession(session) {
  if (!isRecord(session) || !(session.scenarios instanceof Map) || !isRecord(session.options)) throw fail("the session is what createSession of solve.js gives");
  return session;
}

/** The request of a function (an object of the options it reads, nothing else). */
function readRequest(request, keys, what) {
  if (!isRecord(request)) throw fail(`${what} takes a request: {${keys.join(", ")}}`);
  for (const key of Object.keys(request)) {
    if (!keys.includes(key)) throw fail(`the request has an option (${show(key)}) that ${what} does not read (it reads ${keys.join(", ")})`);
  }
  return request;
}

function budgetOf(request) {
  const { budgetMs } = request;
  if (typeof budgetMs !== "number" || !Number.isFinite(budgetMs) || budgetMs < 0) throw fail("budgetMs is the time of the call in milliseconds, a number from 0");
  return budgetMs;
}

function canonicalOf(request) {
  const { canonical = false } = request;
  if (typeof canonical !== "boolean") throw fail("canonical is true or false");
  return canonical;
}

/** The fields of an item that `atTier` always writes (null for none) and that the builder's reader would take as absent. */
const ITEM_FIELDS_WRITTEN = ["deity", "races", "weapon"];

/**
 * An item as `atTier` gives it, checked with the builder's own reader (and for the fields that it takes as absent when they are not there): a PathError
 * for one that lacks what these functions read, at the door, where a TypeError would come out of the middle of the work.
 */
function checkItem(item, what) {
  if (!isRecord(item)) throw fail(`${what} must be an item as atTier gives it`);
  for (const field of ITEM_FIELDS_WRITTEN) {
    if (own(item, field) === undefined) throw fail(`${what}: ${field} is missing (atTier writes null for none)`);
  }
  try {
    readItem(item, 0);
  } catch (error) {
    if (!(error instanceof ModelError)) throw error;
    const said = error.message.replace(/^items\[\d+\] /, "");
    throw fail(said === error.message ? `${what}: ${said}` : `${what} ${said}`);
  }
  return item;
}

/** A list of items with no hole in it and nothing but items (`map` and `forEach` would step over a hole), each checked. */
function itemList(list, what) {
  if (!Array.isArray(list)) throw fail(`${what} are a list of items`);
  const items = [];
  for (let at = 0; at < list.length; at += 1) {
    if (!(at in list)) throw fail(`${what}[${at}] is a hole in the list`);
    items.push(checkItem(list[at], `${what}[${at}]`));
  }
  return items;
}

/** The pairs of an owned set as a list (a Map of item to count is one, and a list is read whole, once), each item checked. */
function ownedEntries(owned) {
  if (owned === null || typeof owned !== "object" || typeof owned[Symbol.iterator] !== "function") throw fail("owned is a list of [item, count] pairs");
  if (Array.isArray(owned)) {
    for (let at = 0; at < owned.length; at += 1) if (!(at in owned)) throw fail(`owned[${at}] is a hole in the list`);
  }
  const entries = [];
  let at = 0;
  for (const entry of owned) {
    if (!Array.isArray(entry) || entry.length !== OWNED_ENTRY_LENGTH || !(0 in entry) || !(1 in entry)) throw fail(`owned[${at}] is not an [item, count] pair`);
    entries.push([checkItem(entry[0], `owned[${at}]`), entry[1]]);
    at += 1;
  }
  return entries;
}

/** The candidates as a list, each ident once (`_candidates` in upgrade.py). */
function checkedCandidates(candidates) {
  const items = itemList(candidates, "the candidates");
  const seen = new Set();
  for (const item of items) {
    const name = ident(item.key, item.tier);
    if (seen.has(name)) throw fail(`${item.key} at tier ${item.tier} is offered twice`);
    seen.add(name);
  }
  return items;
}

// ---- the owned set -------------------------------------------------------------------------------------------------------------------------

/** The owned items by ident, counts of at least 1 (a count of 0 is not owned): `_Owned` in upgrade.py. */
class Owned {
  constructor(entries) {
    this.items = new Map();
    this.counts = new Map();
    for (const [item, count] of entries) {
      if (!Number.isInteger(count) || count < 0) throw fail(`the count of ${item.key} (tier ${item.tier}) is a whole number of at least 0, not ${show(count)}`);
      if (count === 0) continue;
      const name = ident(item.key, item.tier);
      if (this.items.has(name)) throw fail(`${item.key} at tier ${item.tier} is owned twice (give one count)`);
      this.items.set(name, item);
      this.counts.set(name, count);
    }
  }

  tiers(key) {
    return [...this.items.values()].filter((item) => item.key === key).map((item) => item.tier);
  }

  classify(item) {
    if (this.counts.has(ident(item.key, item.tier))) return [KIND_COPY, null];
    const lower = this.tiers(item.key).filter((tier) => tier < item.tier);
    if (lower.length > 0) return [KIND_UPGRADE, Math.max(...lower)];
    return [KIND_NEW, null];
  }

  add(item) {
    const name = ident(item.key, item.tier);
    if (!this.items.has(name)) this.items.set(name, item);
    this.counts.set(name, (this.counts.get(name) ?? 0) + 1);
  }

  take(key, tier) {
    const name = ident(key, tier);
    const left = this.counts.get(name) - 1;
    if (left === 0) {
      this.counts.delete(name);
      this.items.delete(name);
    } else {
      this.counts.set(name, left);
    }
  }

  /** The owned set as `[ident, count]` pairs, sorted by ident. */
  snapshot() {
    return [...this.counts].sort((a, b) => compareText(a[0], b[0]));
  }
}

/**
 * `[kind, source tier]` of a candidate against the owned set: `["copy", null]` for one owned at its tier, `["upgrade", tier]` for the same key owned below
 * it (the highest such tier), else `["new", null]`. A Lore copy is a `copy` whose acquisition adds nothing; the functions leave it out.
 */
export function classify(item, owned) {
  checkItem(item, "the candidate");
  return new Owned(ownedEntries(owned)).classify(item);
}

// ---- the haste, eligibility ----------------------------------------------------------------------------------------------------------------

/**
 * Whether the profile can use an item at all: a class of the trio, a deity it admits, a race it allows (`_Usable` in upgrade.py, and the rule the model builder
 * leaves an item without a column by). Returns a function of an item as `atTier` gives it. The candidates of a scenario are made with it (candidates.js).
 */
export function usableBy(profile) {
  const pools = profileOf(profile).pools;
  const trio = new Set(pools.HP.map((pool) => pool.cls));
  const byClass = [...trio].every((code) => CLASS_SET.has(code));
  const deity = own(profile, "deity") ?? null;
  const race = own(profile, "race") ?? null;
  return (item) => {
    if (byClass && !item.classes.some((code) => trio.has(code))) return false;
    if (item.deity !== null && item.deity !== undefined && (deity === null || !item.deity.includes(deity))) return false;
    return race === null || item.races === null || item.races === undefined || item.races.includes(race);
  };
}

/**
 * The one haste percent a session values every kit at (`session_haste` in upgrade.py): `options.haste_assumed` when the caller gave one, else null, which means that
 * every kit is valued at the haste it counts itself. The other arguments are checked and decide nothing. `options` are the builder's (`any_rule`, `haste_assumed`).
 */
export function sessionHaste(profile, owned, candidates, setup, buffset = null, options = null) {
  const opts = readOptions(options);
  new Owned(ownedEntries(owned)); // (a count that is not a whole number of at least 0 is refused)
  itemList(candidates, "the candidates");
  return opts.hasteAssumed;
}

// ---- Equip now --------------------------------------------------------------------------------------------------------------------------------

/**
 * Equip now on the Equip-now scenario of the session: the owned items alone, each worn at most as often as it is owned, valued at the haste the kit counts (or the
 * session's one haste, if its options fix one; `equip_now` in upgrade.py). The solve ends by `deadline` (a moment on the clock of the session), the building of the
 * models included. Returns the answer of `solveScenario` (solve.js), with `build` (what `setScenario` said about the models).
 */
function solveEquipNow(session, ledger, { deadline, canonical }) {
  requireBow(session, [...ledger.items.values()]);
  const options = { ...sessionBuilderOptions(session), owned_caps: Object.fromEntries(ledger.counts) };
  return solveScenario(session, { name: EQUIP_NOW, items: [...ledger.items.values()], options, budgetMs: Math.max(0, deadline - session.now()), deadline, canonical });
}

export { NO_BOW };

/**
 * The bow setup puts a bow in the range place whatever it is worth (the row `range.bow` of the model, in Python and here, and in every fixture): Equip now, which has the owned items alone, has no
 * kit in that setup when the list has no bow that the profile can wear. The bow counts only if it passes the builder's own filter (`usableBy`: a class of the trio, the deity, the race), as the model
 * filters its items before it looks for a bow; the model would otherwise refuse the list with an error of its own (typed now, `NoBowError`, and a bad request too). The refusal here is a bad request of
 * the list with a sentence that says what to do, and the worker goes on. (A normal answer with an empty range place would be another model than the one Python holds this to.)
 */
function requireBow(session, items) {
  if (session.setup !== "ranged") return;
  const usable = usableBy(session.profile);
  if (!items.some((item, at) => isBow(readItem(item, at)) && usable(item))) throw fail(NO_BOW);
}

/** The builder's options of a session: its Any rule, and the one haste it fixes if it does. */
function sessionBuilderOptions(session) {
  return session.options.haste_assumed === null ? { any_rule: session.options.any_rule } : { any_rule: session.options.any_rule, haste_assumed: session.options.haste_assumed };
}

/**
 * The best kit from the owned items alone at their tiers, each worn at most as often as it is owned: the answer of `solveScenario` (solve.js), the exact value
 * included, valued at the haste the kit counts unless the options of the session fix one. `request` is `{budgetMs, canonical}`.
 */
export function equipNow(session, owned, request) {
  checkSession(session);
  readRequest(request, ["budgetMs", "canonical"], "equipNow");
  const budgetMs = budgetOf(request);
  const canonical = canonicalOf(request);
  const began = session.now();
  const ledger = new Owned(ownedEntries(owned));
  return solveEquipNow(session, ledger, { deadline: began + budgetMs, canonical });
}

// ---- the plan of a Best-1 solve --------------------------------------------------------------------------------------------------------------

/** The pool and the owned-item options for one Best-k solve, from the owned set and the candidates (`_Plan` in upgrade.py). */
class Plan {
  constructor(ledger, candidates) {
    this.pool = new Map(ledger.items);
    this.caps = new Map(ledger.counts);
    this.news = new Set();
    this.ups = new Map(); // target ident -> source ident
    this.kinds = new Map(); // ident -> [kind, source tier]
    this.cands = new Map(); // every candidate by ident (a copy or a Lore copy too), for the order of the equal additions
    for (const candidate of [...candidates].sort(byKeyThenTier)) {
      const name = ident(candidate.key, candidate.tier);
      this.cands.set(name, candidate);
      const [kind, source] = ledger.classify(candidate);
      if (kind === KIND_COPY) {
        if (!candidate.lore) {
          // a Lore copy adds nothing
          this.news.add(name);
          this.kinds.set(name, [kind, source]);
        }
        continue;
      }
      this.pool.set(name, candidate);
      this.kinds.set(name, [kind, source]);
      if (kind === KIND_UPGRADE) this.ups.set(name, ident(candidate.key, source));
      else this.news.add(name);
    }
  }

  /**
   * The builder's options for `pool` (the whole pool of this solve, or a pruned one): the idents that are no longer in it are left out. With `only` (a Set of idents) only those candidates are on
   * offer: the others are not new items or upgrade targets any more, a candidate that is not owned is held at none (a count of 0 in `owned_caps`) and one that is owned has no copy beyond its
   * count (`_Plan.options` in upgrade.py).
   */
  options(base, pool, maxNew, only = null) {
    const present = new Set(pool.map((item) => ident(item.key, item.tier)));
    const caps = new Map(this.caps);
    let news = [...this.news].filter((name) => present.has(name));
    let ups = [...this.ups].filter(([target]) => present.has(target));
    if (only !== null) {
      for (const name of [...news, ...ups.map(([target]) => target)].sort(compareText)) if (!only.has(name) && !caps.has(name)) caps.set(name, 0);
      news = news.filter((name) => only.has(name));
      ups = ups.filter(([target]) => only.has(target));
    }
    return { ...base, owned_caps: Object.fromEntries(caps), new_keys: news, max_new: maxNew, upgrades: Object.fromEntries(ups) };
  }

  /** The idents of the candidates that come before `limit` (an item: `(key, tier)`): the ones the look for an earlier equal addition puts on offer. */
  before(limit) {
    return new Set([...this.cands].filter(([, candidate]) => byKeyThenTier(candidate, limit) < 0).map(([name]) => name));
  }
}

/**
 * What the kit acquires, as `{item, kind, sourceTier}`, in this order: the upgrade targets worn (the first wear of each is its "upgrade", followed by a "copy"
 * of the target for every other wear), then the new items worn, then the wears above the count of the duplicates (the first wear of each of a duplicate's
 * upgrade targets shares one of its copies). Each group is sorted by ident (`_acquired` in upgrade.py).
 */
function acquiredBy(kit, plan, ledger) {
  const wears = new Map();
  for (const item of kit) {
    if (item === null) continue;
    const name = ident(item.key, item.tier);
    wears.set(name, (wears.get(name) ?? 0) + 1);
  }
  const worn = (name) => wears.get(name) ?? 0;
  const found = [];
  const add = (name, times, kind, sourceTier) => {
    const item = plan.pool.get(name) ?? ledger.items.get(name);
    for (let at = 0; at < times; at += 1) found.push({ item, kind, sourceTier });
  };
  for (const name of [...plan.ups.keys()].sort(compareText)) {
    if (worn(name) === 0) continue;
    const [kind, sourceTier] = plan.kinds.get(name);
    add(name, 1, kind, sourceTier);
    add(name, worn(name) - 1, KIND_COPY, null);
  }
  for (const name of [...plan.news].sort(compareText)) {
    if (!ledger.counts.has(name)) add(name, worn(name), ...plan.kinds.get(name));
  }
  for (const name of [...plan.news].sort(compareText)) {
    if (!ledger.counts.has(name)) continue;
    let shared = worn(name);
    for (const [target, source] of plan.ups) if (source === name && worn(target) > 0) shared += 1;
    add(name, Math.max(0, shared - ledger.counts.get(name)), ...plan.kinds.get(name));
  }
  return found;
}

/**
 * The first by `(key, tier)` of the additions worth exactly `best` (the value of the step) when one comes before `chosen`, else null (`_earlier_equal` in upgrade.py): the step's program is
 * solved again with only the candidates before the addition found on offer, on the same pool and the same model of the session (the others held at none), and if its best value is
 * `best` its addition is the next to look before, until the best value is less (it is never more). The solves are plain ones (no tie stage): which of the equal additions such a solve
 * gives does not matter. Returns `{found, answer, ranOut}`: `found` the addition (`{item, kind, sourceTier}`) and `answer` the solve that found it; `ranOut` is true when a solve of the look
 * had no time or did not end proven, and the look stopped (what it had found stands).
 */
function earlierEqual(session, ledger, plan, kept, sessionOptions, chosen, best, { deadline, left }) {
  const present = new Set(kept.map((item) => ident(item.key, item.tier)));
  let found = null;
  let answer = null;
  let limit = chosen.item;
  for (;;) {
    const offered = new Set([...plan.before(limit)].filter((name) => present.has(name)));
    if (offered.size === 0) return { found, answer, ranOut: false };
    const remaining = left();
    if (remaining <= 0) return { found, answer, ranOut: true };
    // only a kit worth the step's value is looked for (`floor`): a look that finds none ends at once, which is nearly always what it finds
    const solved = solveScenario(session, { name: BEST_1_LOOK, items: kept, options: plan.options(sessionOptions, kept, MAX_NEW, offered), budgetMs: remaining, deadline, canonical: false, needTime: true, floor: best.toNumber() });
    if (solved === null) return { found, answer, ranOut: true };
    if (solved.status === "infeasible") return { found, answer, ranOut: false }; // (no kit of those candidates is worth the step's value: no earlier addition ties)
    if (solved.status !== STATUS_OPTIMAL || solved.kit === null) return { found, answer, ranOut: true };
    if (!solved.F.equals(best)) return { found, answer, ranOut: false };
    const acquired = acquiredBy(solved.kit, plan, ledger);
    if (acquired.length !== 1) throw fail(`the look for an earlier equal addition acquires ${acquired.length} items, not one`);
    found = acquired[0];
    answer = solved;
    limit = found.item;
  }
}

/** The owned set after an acquisition: an upgrade takes a copy from its source and adds one of the target, anything else adds a copy. */
function join(ledger, found) {
  if (found.kind === KIND_UPGRADE) ledger.take(found.item.key, found.sourceTier);
  ledger.add(found.item);
}

// ---- the farm path ----------------------------------------------------------------------------------------------------------------------------

/**
 * The farm path: up to `steps` steps (default 8), each the exact best single addition after the steps before it (see the head of this file). Returns
 * `{steps, stopped, hasteAssumed, baseline, elapsedMs}`: `baseline` is the answer of Equip now (the value the first step's gain is counted from; null if the
 * path ended before there was one), `hasteAssumed` the haste of the whole session, and `steps` a list of
 *
 *   {index, found: true, item, kind, sourceTier, F, gain, hasteAssumed, owned, status, label, solution, poolSize, reused, timings}
 *
 * `item` is the candidate acquired (at its tier), `kind` "new", "copy" or "upgrade", `sourceTier` the tier of the owned copy an upgrade is made from,
 * `F` the exact value after the step and `gain` its exact difference to the value before it (always above 0), `owned` the owned set after the step as
 * sorted `[ident, count]` pairs, `status` and `label` those of the solve ("optimal", or "time_limit" with its label), `solution` the answer of the solve,
 * `poolSize` the items of the pruned pool, `reused` whether the Best-1 model of the session was changed in place, and `timings` the milliseconds of
 * `pruneMs`, `buildMs`, `syncMs`, `solveMs`, `tieMs` and `totalMs` (the whole step). A step that found no kit in its time is `{index, found: false, status: "time_limit",
 * label: "not found in time", item: null, ...}` (its solve ran out of time with no kit, or with one that adds nothing) and ends the path; so does a step
 * whose solve ran out of time with a kit that adds something, which is a step as the others, with the status "time_limit". `onStep(step)` is called with
 * each step as it is made, the one that was not found included.
 *
 * `stopped` is "limit" (the steps asked for were made), "no-gain" (no addition improves the value, or the candidates offer none) or "time" (the budget
 * ran out, see the head of this file); the stepper has a fourth reason, "stopped", that farmPath never gives. `canonical` runs the tie stage of
 * every solve, so that the path is the one Python found (tests and checks of a precomputed scenario); each solve then gives its tie stage the same allowance
 * as its first stage.
 */
export function farmPath(session, owned, candidates, request) {
  const { budgetMs, canonical, wanted, onStep } = readPathRequest(session, request, "farmPath", true);
  const path = makePath(session, owned, candidates, { budgetMs, canonical, wanted });
  path.start();
  for (let step = path.next(); step !== null; step = path.next()) {
    if (onStep !== undefined) onStep(step);
  }
  return path.result();
}

/**
 * The farm path one call at a time (see the head of this file): `{start, next, stop, result}`. `request` is `{steps, budgetMs, canonical}` as farmPath's, without
 * `onStep`, and with an `onBegin(number)` if the caller wants one: it is called with the number of a step (1 to `steps`) when `next()` begins it, after the checks of the stop, the
 * limit and the budget and before the plan of the step is made, and not for a step that is not begun (the path was stopped, has ended or reached its limit, or the budget is
 * spent). A step that is begun may still find nothing to add, and end the path. The deadline is `budgetMs` from the moment of this call.
 *
 *   start()   solves Equip now and returns its answer (`baseline` of farmPath's result), once, first. Equip now always runs, with what is left of the budget,
 *             which may be nothing (it then ends at once, and so does the path). It returns null, and the path has ended, when there was nothing to do before
 *             Equip now: no step asked for ("limit"), or nothing the candidates could add ("no-gain"). A stop asked for before `start()` does not change it.
 *   next()    makes the next step and returns it, the very object farmPath passes to `onStep` (it is in `result().steps` too); null once the path has ended, and
 *             at every call after that. A step that ends the path (not found in time, or not proven the best) is returned as the others; the call after it gives
 *             null. Nothing of a step is begun when the budget is spent, or after `stop()`.
 *   stop()    the next call of `next()` returns null and `stopped` is "stopped". A path that has ended keeps the reason it ended for; calling it twice is calling it
 *             once; it may be called before `start()`.
 *   result()  `{steps, stopped, hasteAssumed, baseline, elapsedMs}` as farmPath returns it: the same object at every call, complete once `next()` has given null
 *             (before that it holds what is known so far).
 *
 * `next()` before `start()` and a second `start()` are a PathError. A call that throws leaves the path where it was: the caller drops it.
 */
export function createFarmPath(session, owned, candidates, request) {
  const { budgetMs, canonical, wanted, onBegin } = readPathRequest(session, request, "createFarmPath", false);
  return makePath(session, owned, candidates, { budgetMs, canonical, wanted, onBegin });
}

/**
 * The session and the request of a path function, in the order they are checked: `{budgetMs, canonical, wanted, onStep, onBegin}` (`onStep` is read by farmPath only, `onBegin`
 * by createFarmPath only).
 */
function readPathRequest(session, request, what, streaming) {
  checkSession(session);
  readRequest(request, streaming ? ["steps", "budgetMs", "canonical", "onStep"] : ["steps", "budgetMs", "canonical", "onBegin"], what);
  const budgetMs = budgetOf(request);
  const canonical = canonicalOf(request);
  const { steps: wanted = DEFAULT_STEPS, onStep, onBegin } = request;
  if (!Number.isInteger(wanted) || wanted < 0) throw fail(`steps is a whole number of at least 0, not ${show(wanted)}`);
  if (onStep !== undefined && typeof onStep !== "function") throw fail("onStep is a function");
  if (onBegin !== undefined && typeof onBegin !== "function") throw fail("onBegin is a function");
  return { budgetMs, canonical, wanted, onStep, onBegin };
}

function makePath(session, owned, candidates, { budgetMs, canonical, wanted, onBegin }) {
  const entries = ownedEntries(owned);
  const ledger = new Owned(entries);
  const offered = checkedCandidates(candidates);
  const started = session.now();
  const deadline = started + budgetMs;
  const left = () => deadline - session.now();
  const result = { steps: [], stopped: STOP_LIMIT, hasteAssumed: null, baseline: null, elapsedMs: 0 };
  const sessionOptions = sessionBuilderOptions(session);
  const withBins = (options) => builderOptions(session, options);
  let phase = "new"; // new -> started (by start()) -> ended
  let ending = null; // why the path ends at the next call, when the step just made was the last (it was not found, or not proven the best)
  let stopping = false;
  let number = 0; // the step the last call began
  let before = null; // the exact value before the step: Equip now's, then the last step's

  /** The path ends for `why`: the one look at the clock for the time it took. Returns null (what `next` gives). */
  const end = (why) => {
    result.stopped = why;
    result.elapsedMs = session.now() - started;
    phase = "ended";
    return null;
  };

  function start() {
    if (phase !== "new") throw fail("start() is called once, and before next()");
    phase = "started";
    if (wanted === 0) return end(STOP_LIMIT);
    if (offered.length === 0) return end(STOP_NO_GAIN);
    // Equip now: the value that the first step's gain is counted from. It has all the time there is.
    const baseline = solveEquipNow(session, ledger, { deadline, canonical });
    result.baseline = baseline;
    result.hasteAssumed = baseline.hasteAssumed;
    if (baseline.status !== STATUS_OPTIMAL) {
      end(STOP_TIME);
      return baseline;
    }
    before = baseline.F;
    return baseline;
  }

  function next() {
    if (phase === "new") throw fail("next() comes after start()");
    if (phase === "ended") return null;
    if (ending !== null) return end(ending);
    if (stopping) return end(STOP_STOPPED);
    number += 1;
    if (number > wanted) return end(STOP_LIMIT);
    // nothing of a step is begun once the budget is spent: not its plan, its pruning, its model, its solve
    if (left() <= 0) return end(STOP_TIME);
    if (onBegin !== undefined) onBegin(number); // the step begins here: the checks are passed, and the plan is not made yet
    const began = session.now();
    const plan = new Plan(ledger, offered);
    if (plan.news.size === 0 && plan.ups.size === 0) return end(STOP_NO_GAIN);
    const pool = [...plan.pool.values()];
    const pruning = session.now();
    const kept = prune(pool, session.profile, null, session.setup, session.buffset, withBins(plan.options(sessionOptions, pool, MAX_NEW)), [...plan.caps.keys()]);
    const pruneMs = session.now() - pruning;
    if (left() <= 0) return end(STOP_TIME);
    const remaining = left(); // one look at the clock: what is found to be left is what is handed over (a second look could find it gone)
    if (remaining <= 0) return end(STOP_TIME);
    // the first step begins from the kit of Equip now (it wears nothing that is not owned, so it is feasible here, and HiGHS completes the rest); the
    // later ones from the last kit of the Best-1 model, which the session keeps
    const answer = solveScenario(session, { name: BEST_1, items: kept, options: plan.options(sessionOptions, kept, MAX_NEW), budgetMs: remaining, deadline, canonical, start: number === 1 ? result.baseline : undefined, needTime: true });
    if (answer === null) return end(STOP_TIME); // the model spent the budget: no solve is started
    const build = answer.build;
    const timings = { pruneMs, buildMs: build.buildMs, syncMs: build.syncMs, solveMs: answer.timings.solveMs, tieMs: answer.timings.tieMs, totalMs: session.now() - began };
    const step = { index: number, found: false, item: null, kind: null, sourceTier: null, F: null, gain: null, hasteAssumed: answer.hasteAssumed, owned: ledger.snapshot(), status: answer.status, label: answer.label, solution: answer, poolSize: kept.length, reused: build.reused, timings };
    const notFound = () => {
      // no kit in the time it had, or a kit that adds nothing and a solve that cannot say that nothing does: the step is reported as not found
      step.label = LABEL_NO_INCUMBENT;
      result.steps.push(step);
      ending = STOP_TIME;
      return step;
    };

    if (answer.kit === null) return notFound();
    let acquired = acquiredBy(answer.kit, plan, ledger);
    const gain = answer.F.sub(before);
    if (acquired.length === 0 || gain.sign() <= 0) {
      // nothing improves the value: proven if the solve is
      if (answer.status !== STATUS_OPTIMAL) return notFound();
      return end(STOP_NO_GAIN);
    }
    if (acquired.length !== 1) throw fail(`step ${number} acquires ${acquired.length} items, not one: the model admitted too much`);
    // of additions worth exactly the same the first by (key, tier) is the step's: the look for an earlier one, on the model of the step (see the head of this file)
    let stepAnswer = answer;
    let lookRanOut = false;
    if (answer.status === STATUS_OPTIMAL) {
      const looking = session.now();
      const look = earlierEqual(session, ledger, plan, kept, sessionOptions, acquired[0], answer.F, { deadline, left });
      lookRanOut = look.ranOut;
      if (look.found !== null) {
        let alone = look.answer; // (the look's own answer: its kit is a kit of that addition, and not canonical)
        if (canonical) {
          const remainingNow = left();
          alone = solveScenario(session, { name: BEST_1, items: kept, options: plan.options(sessionOptions, kept, MAX_NEW, new Set([ident(look.found.item.key, look.found.item.tier)])), budgetMs: remainingNow, deadline, canonical, needTime: true });
          if (alone === null || alone.status !== STATUS_OPTIMAL || alone.kit === null) {
            step.timings.solveMs += session.now() - looking;
            return notFound();
          }
          step.timings.tieMs += alone.timings.tieMs;
        }
        if (!alone.F.equals(answer.F)) throw fail(`step ${number}: the addition that comes first among the equal ones is not worth what the best is`);
        acquired = acquiredBy(alone.kit, plan, ledger);
        if (acquired.length !== 1) throw fail(`step ${number} acquires ${acquired.length} items, not one: the model admitted too much`);
        stepAnswer = alone;
        step.solution = alone;
        step.hasteAssumed = alone.hasteAssumed;
      }
      step.timings.solveMs += session.now() - looking; // (the time of the step's solves: the look and the solve of the addition that came first are among them)
      step.timings.totalMs = session.now() - began;
    }
    join(ledger, acquired[0]);
    before = stepAnswer.F;
    Object.assign(step, { found: true, item: acquired[0].item, kind: acquired[0].kind, sourceTier: acquired[0].sourceTier, F: before, gain, owned: ledger.snapshot() });
    result.steps.push(step);
    // an addition that is not proven the best: it is a step, and the time is gone (so is it when the look for an earlier equal one ran out of time)
    if (answer.status !== STATUS_OPTIMAL || lookRanOut) ending = STOP_TIME;
    return step;
  }

  return {
    start,
    next,
    stop() {
      stopping = true;
    },
    result: () => result,
  };
}

/** The ids of the buff set of a session (the always-on buffs and the optional ones), as the builder reads it; none for a session with no buff set. */
function buffIdsOf(buffset) {
  if (buffset === null) return new Set();
  const set = isRecord(buffset) ? buffset.set : undefined;
  if (!isRecord(set) || !Array.isArray(set.always_on) || !Array.isArray(set.optional)) throw fail("the buff set of the session is not one (it needs a set with always_on and optional)");
  return new Set([...set.always_on, ...set.optional]);
}

/** A list of ids of the buffs of the session's buff set (an id twice counts once, and a session with no buff set has none to choose). */
function checkBuffs(session, buffs, what) {
  if (!Array.isArray(buffs)) throw fail(`${what} is a list of buff ids`);
  const known = buffIdsOf(session.buffset);
  for (let at = 0; at < buffs.length; at += 1) {
    if (!(at in buffs)) throw fail(`${what}[${at}] is a hole in the list`);
    if (!Number.isSafeInteger(buffs[at])) throw fail(`${what}[${at}] is not the id of a buff (a whole number)`);
    if (!known.has(buffs[at])) throw fail(`${what}[${at}]: ${buffs[at]} is not a buff of the buff set${session.buffset === null ? " (the session has none)" : ""}`);
  }
  return buffs;
}

// ---- the best sets ----------------------------------------------------------------------------------------------------------------------------

/** The scenario of the best set of `k` additions: a model of its own in the session. */
const bestScenario = (k) => `best-${k}`;

/**
 * The best kit when up to `k` additions (a whole number from 1) are made at once (`best_sets` in upgrade.py); see the head of this file. Returns
 *
 *   {k, acquired, F, gain, hasteAssumed, kit, buffs, status, label, solution, baseline, elapsedMs}
 *
 * `acquired` is a list of `{ident, item, kind, sourceTier}`, `F` the exact value of the kit and `gain` its exact difference to the value of Equip now (0 when no
 * addition improves it), `kit` and `buffs` those of the answer (Equip now's when `acquired` is empty), `status` and `label` those of the solve ("optimal", or
 * "time_limit" with its label), `solution` the answer of the solve of the set (null when the candidates offer nothing to acquire, or when the budget was spent
 * before it began) and `baseline` the answer of Equip now. A set that is not found in time has `acquired` empty and `F`, `gain` and `kit` null. `request` is
 * `{budgetMs, canonical}`.
 */
export function bestSets(session, owned, candidates, k, request) {
  checkSession(session);
  readRequest(request, ["budgetMs", "canonical"], "bestSets");
  if (!Number.isInteger(k) || k < 1) throw fail(`k is a whole number of at least 1, not ${show(k)}`);
  const budgetMs = budgetOf(request);
  const canonical = canonicalOf(request);
  const ledger = new Owned(ownedEntries(owned));
  const offered = checkedCandidates(candidates);
  const started = session.now();
  const deadline = started + budgetMs;
  const left = () => deadline - session.now();

  const sessionOptions = sessionBuilderOptions(session);
  const withBins = (options) => builderOptions(session, options);
  const baseline = solveEquipNow(session, ledger, { deadline, canonical });
  const result = (more) => ({
    k,
    acquired: [],
    F: null,
    gain: null,
    hasteAssumed: baseline.hasteAssumed,
    kit: null,
    buffs: [],
    status: STATUS_OPTIMAL,
    label: null,
    solution: null,
    baseline,
    elapsedMs: session.now() - started,
    ...more,
  });
  /** No set is found: the time ran out, before the set began or inside its solve. */
  const notFound = (solution) => result({ status: solution === null ? "time_limit" : solution.status, label: LABEL_NO_INCUMBENT, solution });
  /** No addition improves the value: Equip now's kit stands. */
  const nothing = (solution) => result({ F: baseline.F, gain: baseline.F.sub(baseline.F), kit: baseline.kit, buffs: baseline.buffs, solution });

  // without the value of Equip now there is no gain to count, and so no set with a value: whatever Equip now was given of the time, and whatever kit it
  // has, the set is "not found in time" (a result with no value carries that label, as protocol.js has it)
  if (baseline.status !== STATUS_OPTIMAL) return result({ status: baseline.status, label: LABEL_NO_INCUMBENT });
  const plan = new Plan(ledger, offered);
  if (plan.news.size === 0 && plan.ups.size === 0) return nothing(null);
  // nothing of the set is begun once the budget is spent: not its pruning, its model, its solve
  if (left() <= 0) return notFound(null);
  const pool = [...plan.pool.values()];
  const kept = prune(pool, session.profile, null, session.setup, session.buffset, withBins(plan.options(sessionOptions, pool, k)), [...plan.caps.keys()]);
  if (left() <= 0) return notFound(null);
  const remaining = left(); // one look at the clock: what is found to be left is what is handed over
  if (remaining <= 0) return notFound(null);
  // it begins from the kit of Equip now: it wears nothing that is not owned, so it is feasible here, and HiGHS completes the rest
  const answer = solveScenario(session, { name: bestScenario(k), items: kept, options: plan.options(sessionOptions, kept, k), budgetMs: remaining, deadline, canonical, start: baseline, needTime: true });
  if (answer === null) return notFound(null); // the model spent the budget: no solve is started
  if (answer.kit === null) return notFound(answer);
  const acquired = acquiredBy(answer.kit, plan, ledger).map((found) => ({ ident: ident(found.item.key, found.item.tier), ...found }));
  const gain = answer.F.sub(baseline.F);
  if (acquired.length === 0 || gain.sign() <= 0) return answer.status === STATUS_OPTIMAL ? nothing(answer) : notFound(answer);
  return result({ acquired, F: answer.F, gain, kit: answer.kit, buffs: answer.buffs, status: answer.status, label: answer.label, solution: answer, hasteAssumed: answer.hasteAssumed });
}

// ---- Every slot --------------------------------------------------------------------------------------------------------------------------------

/**
 * For each of the 22 places, the `limit` best swaps (default 3): the exact change of the value when one item stands in that place and the rest of the
 * kit stays as it is, the buffs too, and the swapped kit valued at the haste it counts (`every_slot` in upgrade.py). `kit` is the answer of `equipNow` (or any object with a `kit` and
 * its `buffs`) or a list of the 22 places; `buffs` (in the request) the ids of the chosen optional buffs for a list.
 *
 * The items on offer, and their copies. They are the `candidates` of the tier mode and the items the visitor owns (`owned` in the request, `[item, count]` pairs
 * as everywhere in this file; none by default):
 *   - a candidate (an item that can be got at the tier of the mode) has no count limit: the swap means getting another copy of it, as an addition does. An ident
 *     that is both owned and a candidate counts as a candidate;
 *   - an owned item whose ident is not a candidate's is a swap for a place only while the visitor's owned count of that ident is greater than the copies the
 *     kit wears in its OTHER places, so that the kit after the swap wears it no more often than it is owned. One ring owned once and worn on Finger 1 is not a
 *     swap for Finger 2; with a second copy owned it is. (With the kit of Equip now, which is the best kit of what is owned, such a swap never gains.)
 * An item the profile cannot use, one already worn in that place, a Lore item worn in another place (Lore stays as it is: a Lore item is never worn twice,
 * whatever is owned), a two-hander in the main hand over a worn off hand and anything in the off hand under a two-hander are not offered. Best gain first,
 * ties by (key, tier); a worse item is a swap with a negative gain. Returns, for each place, `{place, index, current, swaps: [{item, delta}]}`.
 */
export function everySlot(session, kit, candidates, request = {}) {
  checkSession(session);
  readRequest(request, ["buffs", "limit", "owned"], "everySlot");
  const { buffs, limit = DEFAULT_SWAPS, owned } = request;
  if (!Number.isInteger(limit) || limit < 0) throw fail(`limit is a whole number of at least 0, not ${show(limit)}`);
  const answer = !Array.isArray(kit) && isRecord(kit);
  const places = answer ? kit.kit : kit;
  if (!Array.isArray(places)) throw fail("the kit is the answer of equipNow or a list of the places");
  if (places.length !== PLACES) throw fail(`a kit has ${PLACES} places, not ${places.length}`);
  const slots = [];
  for (let at = 0; at < PLACES; at += 1) {
    if (!(at in places)) throw fail(`kit[${at}] is a hole in the list`);
    slots.push(places[at] === null ? null : checkItem(places[at], `kit[${at}]`));
  }
  const listed = buffs !== undefined ? buffs : answer && kit.buffs !== undefined ? kit.buffs : [];
  const chosen = checkBuffs(session, listed, buffs !== undefined ? "buffs" : "kit.buffs");
  const offered = checkedCandidates(candidates);
  const ledger = new Owned(owned === undefined ? [] : ownedEntries(owned));

  const { profile, setup, buffset, monkBins, procs } = session;
  const base = session.options;
  // a swap is valued at the haste the swapped kit counts (the one haste of the session's options when they fix one)
  const usable = usableBy(profile);
  const evaluated = { setup, monkBins, buffset: buffset ?? undefined, procs: procs ?? undefined };
  const value = (trial) =>
    base.haste_assumed === null
      ? evaluateTruthful(profile, trial, buffset === null ? null : chosen, evaluated).F
      : evaluate(profile, trial, buffset === null ? null : chosen, { ...evaluated, hasteAssumed: base.haste_assumed }).F;
  const start = value(slots);

  const named = new Set(offered.map((item) => ident(item.key, item.tier)));
  const counted = new Set(); // the owned items that are not candidates: held to the counts
  const owning = [];
  for (const [name, item] of ledger.items) {
    if (named.has(name)) continue;
    counted.add(name);
    owning.push(item);
  }
  const pool = [...offered, ...owning].filter(usable).sort(byKeyThenTier);
  const fits = new Map(pool.map((item) => [ident(item.key, item.tier), fitGroups(item, setup, base.any_rule)]));
  const byPlace = new Map(DISTINCT_PLACES.map((place) => [place, pool.filter((item) => fits.get(ident(item.key, item.tier)).has(place))]));
  const wears = new Map();
  for (const item of slots) {
    if (item === null) continue;
    const name = ident(item.key, item.tier);
    wears.set(name, (wears.get(name) ?? 0) + 1);
  }

  return SLOT_INSTANCES.map((place, index) => {
    const current = slots[index];
    const wornElsewhere = new Set();
    slots.forEach((item, other) => {
      if (other !== index && item !== null && item.lore) wornElsewhere.add(item.key);
    });
    const swaps = [];
    for (const candidate of byPlace.get(place)) {
      if (current !== null && candidate.key === current.key && candidate.tier === current.tier) continue;
      if (candidate.lore && wornElsewhere.has(candidate.key)) continue;
      const name = ident(candidate.key, candidate.tier);
      // (the candidate is not the item worn in this place, so every copy the kit wears is in another place)
      if (counted.has(name) && ledger.counts.get(name) <= (wears.get(name) ?? 0)) continue;
      const trial = [...slots];
      trial[index] = candidate;
      const primary = trial[PRIMARY_INDEX];
      const holdsTwoHander = primary !== null && primary.weapon !== null && primary.weapon.two_handed;
      if (place === PRIMARY && holdsTwoHander && trial[SECONDARY_INDEX] !== null) continue;
      if (place === SECONDARY && holdsTwoHander) continue;
      swaps.push({ item: candidate, delta: value(trial).sub(start) });
    }
    swaps.sort((a, b) => b.delta.compare(a.delta) || byKeyThenTier(a.item, b.item));
    return { place, index, current, swaps: swaps.slice(0, limit) };
  });
}
