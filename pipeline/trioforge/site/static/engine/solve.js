// Sessions: the solver for one visitor's scenarios, in the browser. A port of the solver wrapper in pipeline/trioforge/solver/solve.py (the
// determinism options, the exact value of the answer, the exactness check, the canonical placement and the tie stage), held to the canonical solves
// that Python recorded by tests-js/engine-solve.test.mjs, with what Python has no use for: models that stay in the solver between solves.
//
//   createSession({highs, profile, setup, buffset, monkBins, options, now}) -> session
//   setScenario(session, name, items, options)   -> {name, reused, columns, rows, buildMs, syncMs}
//   solve(session, {scenario, budgetMs, deadline, canonical, start, highsOptions, onProgress}) -> the answer, below
//   closeSession(session)
//   placeCanonically, canonicalKit, tieRanks, checkExactness, checkRearranged   the pieces of the solver wrapper of Python, for the tests and the checks of a
//               precomputed scenario
//
// A session holds one profile, weapon setup, buff set and Monk table (read once, and copied: nothing the caller does to them afterwards is seen) and
// one HiGHS model for each scenario it is asked about (`session.scenarios`, a Map from the name of the scenario). `setScenario` builds the model JSON
// of the scenario with the MILP builder (model.js: the pool `items` and the builder's `options`, the owned-item options included) and puts it in the
// scenario's solver. When the columns are the same as the solver already holds (the same pool, the same curves) and only bounds and rows differ, which
// is what a change of the owned counts does, the solver's model is changed in place: bounds of columns and rows are set, rows that appeared or whose
// entries changed are added, rows that went are deleted. Otherwise the solver's model is made anew. Either way the solver ends with the model that the
// builder made, and the next solve starts from the kit of the last one, or from a kit that the caller gives (`start`: `{kit, buffs}`, say the answer of
// another scenario whose kit is feasible here): the previous solution as it is when the columns are the same, else the item and buff columns of a kit (a
// value for each of those columns, 0 for what the kit does not wear), and nothing for the other columns, which HiGHS completes. A solve never reads what an
// earlier one left behind except through that start.
//
// solve(...) runs HiGHS on the scenario inside `budgetMs` (a time in milliseconds, for this call) with the determinism options of the Python solver that
// the one-thread build takes (SOLVER_OPTIONS of highs-data.js), reads the kit back, places the worn items by the canonical rule, and values the kit with
// the exact evaluator. The time handed to HiGHS is all that is left of the budget at the moment it is handed over, and never more. A caller that has a
// moment of its own to end by, as a path of several solves has, gives it as `deadline` (on the session's clock): the first stage ends by the earlier of
// it and the end of the budget, and the tie stage's allowance stays `budgetMs`. HiGHS looks at the clock now and then, so it can end a little after its
// limit, and the work around the run (the start, the reading back, the exact value) takes its time too: a call can overrun its budget by those, and
// only by those. The answer is
//
//   status      "optimal", "time_limit" or "infeasible" (the statuses of the protocol). A stop at a time limit, a node limit or an interrupt is
//               `time_limit`: the answer is the best kit HiGHS had, which is not proven the best.
//   label       null; LABEL_TIME_LIMIT for a `time_limit` with a kit; LABEL_NO_INCUMBENT ("not found in time") for a `time_limit` without one.
//   proven      whether the status is a proof (optimal, or infeasible).
//   F, kit, buffs, breakdown   the exact value (a Rational) of the kit with its buffs, the kit (22 places, the items of the pool or null), the ids of
//               the chosen optional buffs, and the evaluator's breakdown. All null (buffs empty) when there is no kit. F is always the evaluator's:
//               never the model's value, and for a `time_limit` it is a lower bound of the optimum.
//   modelF, gap, nodes, bound   what the model and HiGHS said (the model's own value of the kit; HiGHS's relative gap, node count and dual bound).
//   canonical, tieStage   with `canonical: true` and an optimal first stage, the tie stage runs: "applied" (its kit is the answer; canonical true when the last stage,
//               below, ran to its end) or "kept-first" (it was worse by the exact evaluator, or did not finish: the first stage's kit stands). Both null/false otherwise.
//   hasteAssumed, highsStatus, limitMs, timings   the haste the weapon index assumed, the model status HiGHS ended with, the time the first stage's
//               HiGHS was given, and the milliseconds the stages took.
//   start       what the first stage began from: null (nothing), "solution" (the last solution, as it was) or "kit" (the item and buff columns of a kit).
//
// With `canonical: true` the answer is the kit of Python's `solve_canonical` (placement and tie stage). That is for tests and for checking a precomputed
// scenario. A browser's answer is `canonical: false`: placement only. Each of the two stages has the whole `budgetMs` to itself, as each solve of Python
// has its time limit, so that a canonical call can take about four times `budgetMs` (the first stage, the proof below, the tie stage, and the last stage's solve that finds nothing more tied, with one more for each kit of a tie). The tie stage is cut down when the band of kits it chooses
// from wears one set of items, which a cheaper proof shows (`itemsAreSettled`): it then looks only for the buffs, with the items fixed, or for nothing at all where the
// scenario has no optional buff. The answer is the same either way, and `tieShortcut: false` (a test hook) runs the whole tie stage always.
//
// The last stage (`_settle_ties` in solve.py: its head has the whole account). Kits of the same exact value and the same total rank are not told apart by the rank (items ranked 1 and 4
// against 2 and 3), and which of them a solver names was its own path's, not the same in the two engines. Once the tie stage has a kit of the least total rank R, the program is
// solved again, maximizing the value (the program's own objective, which bounds a kit best: with the rank as the objective the same proof took some seven times the time of the tie stage,
// and it is a maximum, so that it is no tie program) over the kits with the rows `total rank <= R` and "not the worn items (copies counted) and chosen buffs of the kits found so far",
// with the cutoff of the proof of the shortcut's kind at `TIE_PROOF_TOLERANCE` under the best value (a solve of its own, as the proof is, with the whole allowance), until one has no kit
// worth the cutoff: the proof that the tie has no more members. The answer is the member
// first in the order of the kits (`compareKits`): the canonical kits place by place in the order of the 22 places, an item before an empty place and the lower (key, tier) first (the
// key by code point), the first place that differs deciding; when every place is alike, the chosen buff ids as sorted lists, the lower first. A kit of a higher exact value, or of the
// same value and a lower rank, takes the place of the answer first (the value, the rank, the order of the kits). `canonical` is true when the proof ran to its end; a solve of the stage
// that stops at its limit, or a tie of more than `MAX_TIED_KITS` kits (`tiedKits`, a test hook, sets another number), ends the stage with the best kit it has and `canonical` false.
//
// Where the worn items stand (`place_canonically` in solve.py). Only the two hands make the place of an item matter to the value (the weapon index of what is in
// them, the shield bonus of an off-hand shield), so the kit is placed by a rule that looks at the items alone. Among the arrangements of the worn items
// that the builder allows (an item stands in a hand only if the model has a column for it there; a two-hander leaves the off hand empty; a pair of one item
// needs two copies; what is left must still have a place outside the hands) and whose exact value equals the solver's own, the main hand is filled before
// it is left empty, by the smaller (key, tier), and then the off hand the same way; only the arrangements that come before the solver's in that order are
// valued. The other items go by (key, tier) into the earliest group of the slot order that leaves every item after them a place. Only the arrangement may
// change. What is checked afterwards is the items (copies counted), always, and the exact value of the kit, whenever arrangements were compared (a
// PlacementError if they differ); the tie stage cannot change, since its ranks belong to the items alone (`tieRanks`), not to the places they stand in. Two
// engines that choose the same items, with the same value, end with the same kit, place for place.
//
// Progress (`onProgress`) is told as `{phase: "solving", stage, elapsedMs, ...}`. The events of the first stage (`stage` "solve") carry the model's
// `objective` (its constant included), and the solver's `bound`, `gap` and `nodes`. The tie stage minimizes a rank, whose objective, bound and gap are not
// values of the kit: its events (`stage` "tie") carry the first stage's `objective`, which is the value they keep, and `nodes`. So do the events of the proof of the tie stage's shortcut (`stage` "proof").
//
// Exactness. A model value more than 1e-6 relative above the evaluator's value of its own kit is an ExactnessError at any status: the model and the
// evaluator disagree, which is a bug and never a rounding. A model value below the evaluator's is not an error: a kit from a time limit or from the tie
// stage need not sit at its best continuous values.

import { CONSTANTS, RANGE_GROUP, evaluate, profileOf } from "./evaluate.js";
import { buildMilpWithItems, compareText, ident, LevelPrograms, readOptions } from "./model.js";
import { ProcTable } from "./procs.js";
import { LABEL_NO_INCUMBENT, LABEL_TIME_LIMIT } from "./protocol.js";
import { SOLVER_OPTIONS, toModelData } from "./highs-data.js";

/** The most the model's own value of a kit may differ from the evaluator's, relative (`EXACTNESS_TOLERANCE` in solve.py). */
export const EXACTNESS_TOLERANCE = 1e-6;
/** The second stage keeps every kit within this relative distance of the best value (`TIE_TOLERANCE` in solve.py). */
export const TIE_TOLERANCE = 1e-7;
/** The most kits of one tie that the last stage sets apart one by one (`MAX_TIED_KITS` in solve.py). */
export const MAX_TIED_KITS = 200;
/** How far under the best value (relative) the last stage's cutoff is: a tenth of the tie stage's band (`TIE_PROOF_TOLERANCE` in solve.py). */
export const TIE_PROOF_TOLERANCE = 1e-8;
/** How far from a whole number a column of a whole kind may be (`_integral` in model.py). */
const INTEGRAL_TOLERANCE = 1e-6;
const MS_PER_SECOND = 1000;
/** The longest name of a scenario, and the longest piece of the solver's own message or of a caller's text that a message quotes. */
const MAX_NAME_LENGTH = 60;
const MESSAGE_CHARS = 200;
const SHOWN_CHARS = 40;
/** How often progress is reported, at most (the worker's own rate). */
const PROGRESS_EVERY_MS = 50;

/** An input that is not what a session reads, or a solver that ended in a way the answer cannot be made from. */
export class SolveError extends Error {
  constructor(message) {
    super(message);
    this.name = "SolveError";
  }
}

/**
 * The solver, or the model the builder made for it, did what an answer cannot be made from: HiGHS refused the model, the run ended in a status that the
 * solve does not accept, or the solution has an entry that is not a number or a column that is not whole. Nobody's input is to blame: it is a fault of the
 * solver or of the builder, and a session that met one is not to be trusted with another solve. A SolveError, so that whoever catches those catches these
 * too; the worker tells them apart (as `solver`, not as a mistake in a request).
 */
export class SolverFault extends SolveError {
  constructor(message) {
    super(message);
    this.name = "SolverFault";
  }
}

/** The model's objective for its own kit is above the exact evaluator's value of that kit (a bug of the model). */
export class ExactnessError extends SolveError {
  constructor(message) {
    super(message);
    this.name = "ExactnessError";
  }
}

/** The canonical placement changed more than where the worn items stand: other items, or another exact value (a bug of the rule). */
export class PlacementError extends SolveError {
  constructor(message) {
    super(message);
    this.name = "PlacementError";
  }
}

const fail = (message) => new SolveError(message);
const solverFault = (message) => new SolverFault(message);

// ---- the vocabulary, from the constants of the formulas -------------------------------------------------------------------------------

const SLOT_GROUPS = CONSTANTS.slotGroups.map(([name, places]) => [name, Number(places.numerator)]);
const GROUP_ORDER = new Map(SLOT_GROUPS.map(([name], at) => [name, at]));
/** The group of each place of a kit, in kit order. */
const PLACE_GROUPS = SLOT_GROUPS.flatMap(([name, places]) => new Array(places).fill(name));
const PLACES = PLACE_GROUPS.length;
const HANDS = [...CONSTANTS.handPlaces];
/** The groups whose occupant the value depends on, and so the places the canonical rule arranges (`_arranged` in solve.py): the two hands, and under the bow setup the range place too. */
const arrangedFor = (setup) => (setup === "ranged" ? [...HANDS, RANGE_GROUP] : HANDS);
const SETUP_SET = new Set(CONSTANTS.setups);
const SESSION_KEYS = new Set(["highs", "profile", "setup", "buffset", "monkBins", "procs", "options", "now"]);
const SESSION_OPTION_KEYS = new Set(["any_rule", "haste_assumed"]);
const SOLVE_KEYS = new Set(["scenario", "budgetMs", "deadline", "canonical", "highsOptions", "onProgress", "start", "cutoff", "tieShortcut", "tiedKits"]);
const TRUTHFUL_KEYS = new Set(["name", "items", "options", "budgetMs", "deadline", "canonical", "highsOptions", "onProgress", "start", "bound", "needTime", "tieShortcut", "floor"]);
/** The two stages of a solve, as the progress events name them. */
const STAGE_SOLVE = "solve";
const STAGE_TIE = "tie";
/** The proof that the items of the band are settled (`itemsAreSettled`): its events are the tie stage's in kind (the first stage's objective, no bound or gap). */
const STAGE_PROOF = "proof";
/** The options of HiGHS that a call may not set: the budget is the time limit, and the build has one thread. */
const REFUSED_HIGHS_OPTIONS = new Set(["time_limit", "threads"]);
/** The largest number the solver takes for an option that is infinite by default (its options take no infinity), and treats as none: the value an option is put back to. */
const LARGEST_OPTION = 1e300;

// ---- small helpers -----------------------------------------------------------------------------------------------------------------------

const isRecord = (value) => typeof value === "object" && value !== null && !Array.isArray(value);
const defaultNow = () => performance.now();

/** How deep a copy goes into lists and objects: the data of a profile is some six deep, and an object that holds itself never ends. */
const MAX_COPY_DEPTH = 32;

/**
 * A copy of plain data that nothing can change, all through (so that the evaluator and the builder read it once and remember it). Plain data is `null`, a
 * truth value, a finite number, a text, a list with no hole in it and an object of plain properties with texts for keys: anything else (`undefined`, a
 * function, a symbol, a big integer, NaN or an infinity, an accessor, an object of a class, a cycle) is refused, where a copy through JSON would turn it into
 * null or leave it out. The numbers are copied as they are (-0 stays -0), and so is the order of the keys.
 */
function frozenCopy(value, what) {
  const copy = (node, where, depth) => {
    if (node === null || typeof node === "string" || typeof node === "boolean") return node;
    if (typeof node === "number") {
      if (!Number.isFinite(node)) throw fail(`${what}${where} must be a finite number, not ${node}`);
      return node;
    }
    if (typeof node !== "object") throw fail(`${what}${where} is not plain data (it is ${typeof node})`);
    if (depth >= MAX_COPY_DEPTH) throw fail(`${what}${where} is nested too deep, or holds itself`);
    if (Array.isArray(node)) {
      const list = [];
      for (let at = 0; at < node.length; at += 1) {
        if (!(at in node)) throw fail(`${what}${where}[${at}] is a hole in the list`);
        list.push(copy(node[at], `${where}[${at}]`, depth + 1));
      }
      return Object.freeze(list);
    }
    const prototype = Object.getPrototypeOf(node);
    if (prototype !== Object.prototype && prototype !== null) throw fail(`${what}${where} is not plain data (an object of a class)`);
    const entries = [];
    for (const key of Reflect.ownKeys(node)) {
      if (typeof key !== "string") throw fail(`${what}${where} has a symbol for a key`);
      const descriptor = Object.getOwnPropertyDescriptor(node, key);
      if (!("value" in descriptor) || descriptor.enumerable !== true) throw fail(`${what}${where}.${show(key)} is not plain data (an accessor or a hidden property)`);
      entries.push([key, copy(descriptor.value, `${where}.${show(key)}`, depth + 1)]);
    }
    return Object.freeze(Object.fromEntries(entries));
  };
  return copy(value, "", 0);
}

/** A name from the caller, short and plain, to put in a message. */
const show = (value) => (typeof value === "string" && value.length <= SHOWN_CHARS ? JSON.stringify(value) : typeof value);

function openSession(session) {
  if (!isRecord(session) || !(session.scenarios instanceof Map)) throw fail("the session is what createSession gives");
  if (session.closed) throw fail("the session is closed");
  return session;
}

// ---- the exactness check, the placement and the ranks (solve.py) --------------------------------------------------------------------

/** Refuse a model that overstates what its own kit is worth (see the head of this file). */
export function checkExactness(modelValue, value) {
  if (!Number.isFinite(modelValue) || !Number.isFinite(value)) {
    throw new ExactnessError(`the model's objective ${modelValue} or the evaluator's value ${value} of its kit is not a number`);
  }
  if (modelValue > value + EXACTNESS_TOLERANCE * Math.max(1, Math.abs(value))) {
    throw new ExactnessError(
      `the model's objective ${modelValue} overstates the evaluator's value ${value} of its kit by more than ${EXACTNESS_TOLERANCE} relative`,
    );
  }
}

const byKeyThenTier = (a, b) => compareText(a.key, b.key) || a.tier - b.tier;

/** The kit of `Map {group: [items]}`: each group sorted by key (then tier) into its places, empty places last (`canonical_kit` in solve.py). */
export function canonicalKit(groups) {
  const kit = [];
  for (const [name, size] of SLOT_GROUPS) {
    const placed = [...(groups.get(name) ?? [])].sort(byKeyThenTier);
    if (placed.length > size) throw fail(`${placed.length} items in ${name}, which has ${size} places`);
    kit.push(...placed, ...new Array(size - placed.length).fill(null));
  }
  return kit;
}

/**
 * The order of the kits that the last stage settles (`kit_order` in solve.py): -1, 0 or 1 for two kits of 22 places with their chosen buff ids (sorted). The places in turn, an item
 * before an empty place, two items by key (by code point) and then tier; when every place is alike, the buff ids as lists, the lower first (a list before the list it begins).
 */
export function compareKits(kitA, buffsA, kitB, buffsB) {
  for (let at = 0; at < PLACES; at += 1) {
    const a = kitA[at];
    const b = kitB[at];
    if (a === null && b === null) continue;
    if (a === null) return 1;
    if (b === null) return -1;
    const order = compareText(a.key, b.key) || a.tier - b.tier;
    if (order !== 0) return order < 0 ? -1 : 1;
  }
  const shared = Math.min(buffsA.length, buffsB.length);
  for (let at = 0; at < shared; at += 1) {
    if (buffsA[at] !== buffsB[at]) return buffsA[at] < buffsB[at] ? -1 : 1;
  }
  return Math.sign(buffsA.length - buffsB.length);
}

/**
 * Whether every item (`options[i]` are the groups item `i` may stand in) can have a place, given the places `room` (a Map) still left in each group: a
 * matching of items to places, found by augmenting paths (`_all_placed` in solve.py).
 */
function allPlaced(options, room) {
  const stands = new Map([...room.keys()].map((group) => [group, []]));
  const place = (item, tried) => {
    for (const group of options[item]) {
      if (tried.has(group)) continue;
      tried.add(group);
      const here = stands.get(group);
      if (here.length < room.get(group)) {
        here.push(item);
        return true;
      }
      for (let position = 0; position < here.length; position += 1) {
        if (place(here[position], tried)) {
          // the other item moves to another group, this one takes its place
          here[position] = item;
          return true;
        }
      }
    }
    return false;
  };
  return options.every((_, item) => place(item, new Set()));
}

const nameOf = (item) => ident(item.key, item.tier);

/** Whether an item is a two-hander. An item with no `weapon` field is one with no weapon, as the builder reads it (the evaluator has its own word for it). */
const isTwoHander = (item) => item.weapon !== null && item.weapon !== undefined && item.weapon.two_handed === true;

/** Where an item comes in the order of one hand: a filled hand before an empty one, then the smaller (key, tier) (`_hand_order` in solve.py). */
function compareHand(a, b) {
  if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
  return byKeyThenTier(a, b);
}

/** The places the model has a column for: `{outside, inHand}`, `outside` a Map from an item's ident to its groups outside the hands in slot order, `inHand` for each hand (and the range place under the bow setup) the set of idents (`_columns` in solve.py). */
function columnsOf(model, arranged) {
  const outside = new Map();
  const inHand = new Map(arranged.map((hand) => [hand, new Set()]));
  for (const [, group, key, tier] of model.item_cols) {
    const name = ident(key, tier);
    if (inHand.has(group)) {
      inHand.get(group).add(name);
    } else {
      if (!outside.has(name)) outside.set(name, []);
      outside.get(name).push(group);
    }
  }
  for (const options of outside.values()) options.sort((a, b) => GROUP_ORDER.get(a) - GROUP_ORDER.get(b));
  return { outside, inHand };
}

/**
 * The items that are not in a hand as a Map {group: [items]}, each in the earliest group of the slot order that the model has a column for it in and that has a
 * place left, provided every item after it can still be given a place; taken in the order of (key, tier) (`_place_outside` in solve.py).
 */
function placeOutside(items, outside, arranged) {
  const movable = [...items].sort(byKeyThenTier);
  const options = movable.map((item) => outside.get(nameOf(item)) ?? []);
  const room = new Map(SLOT_GROUPS.filter(([group]) => !arranged.includes(group)));
  const placed = new Map();
  movable.forEach((item, number) => {
    let done = false;
    for (const group of options[number]) {
      if (room.get(group) === 0) continue;
      room.set(group, room.get(group) - 1);
      if (allPlaced(options.slice(number + 1), room)) {
        if (!placed.has(group)) placed.set(group, []);
        placed.get(group).push(item);
        done = true;
        break;
      }
      room.set(group, room.get(group) + 1);
    }
    if (!done) throw fail(`no place can be found for ${item.key} and the items after it: not a placement of this model`);
  });
  return placed;
}

/** A kit with `chosen` in the arranged places (the hands, and the range place under the bow setup) and `rest` in the other places in any order (the evaluator reads only what stands in the arranged places from the place). */
function kitOf(rest, chosen, arranged) {
  let next = 0;
  return PLACE_GROUPS.map((group) => (arranged.includes(group) ? chosen[arranged.indexOf(group)] : next < rest.length ? rest[next++] : null));
}

/**
 * `placeCanonically` and, when it had to compare arrangements, the exact value of the solver's own (else null) (`_place` in solve.py). `value(kit)` is the exact
 * value of a kit of 22 places (a Rational). `setup` is the one of the model: under "ranged" the range place is arranged with the hands.
 */
function placeHands(model, groups, value, setup = null) {
  const arranged = arrangedFor(setup);
  for (const hand of arranged) {
    const held = groups.get(hand) ?? [];
    if (held.length > 1) throw fail(`${held.length} items in ${hand}, which has one place`);
  }
  const { outside, inHand } = columnsOf(model, arranged);
  const worn = [...groups.values()].flat();
  const solver = arranged.map((hand) => (groups.get(hand) ?? [])[0] ?? null);
  const copies = new Map();
  const byName = new Map();
  for (const item of worn) {
    const name = nameOf(item);
    copies.set(name, (copies.get(name) ?? 0) + 1);
    if (!byName.has(name)) byName.set(name, item);
  }
  const names = [...byName.values()].sort(byKeyThenTier);
  const stand = new Map(SLOT_GROUPS.filter(([group]) => !arranged.includes(group)));

  const restWithout = (...taken) => {
    const left = new Map(copies);
    for (const item of taken) if (item !== null) left.set(nameOf(item), left.get(nameOf(item)) - 1);
    return names.flatMap((item) => new Array(left.get(nameOf(item))).fill(byName.get(nameOf(item))));
  };
  /** What is left for the places outside the arranged ones when `choice` stands in them, or null when that is not an arrangement the builder allows. */
  const legal = (choice) => {
    const used = new Map();
    for (const item of choice) if (item !== null) used.set(nameOf(item), (used.get(nameOf(item)) ?? 0) + 1);
    for (const [name, count] of used) if (count > copies.get(name)) return null; // an item stands in two places only if it is worn twice
    if (choice[0] !== null && choice[1] !== null && isTwoHander(choice[0])) return null; // a two-hander leaves the off hand empty
    const rest = restWithout(...choice);
    return allPlaced(rest.map((item) => outside.get(nameOf(item)) ?? []), stand) ? rest : null;
  };

  const options = arranged.map((hand) => [...names.filter((item) => inHand.get(hand).has(nameOf(item))), null]);
  const before = (choice) => {
    for (let at = 0; at < choice.length; at += 1) {
      const order = compareHand(choice[at], solver[at]);
      if (order !== 0) return order;
    }
    return 0;
  }; // below 0: before the solver's arrangement in the order
  let solverValue = null;
  let chosen = solver;
  const walk = (at, choice) => {
    if (at === options.length) {
      if (before(choice) >= 0) return "stop"; // the solver's own arrangement is reached: none before it was as good, and it stands
      const rest = legal(choice);
      if (rest === null) return "go on";
      if (solverValue === null) solverValue = value(kitOf(restWithout(...solver), solver, arranged));
      if (value(kitOf(rest, choice, arranged)).equals(solverValue)) {
        chosen = [...choice];
        return "stop";
      }
      return "go on";
    }
    for (const item of options[at]) {
      if (walk(at + 1, [...choice, item]) === "stop") return "stop";
    }
    return "go on";
  };
  walk(0, []);
  const placed = placeOutside(restWithout(...chosen), outside, arranged);
  arranged.forEach((hand, at) => {
    if (chosen[at] !== null) placed.set(hand, [chosen[at]]);
  });
  return { placed: new Map([...placed].map(([group, items]) => [group, [...items].sort(byKeyThenTier)])), solverValue };
}

/**
 * `Map {group: [items]}` with the same items, placed by the canonical rule (`place_canonically` in solve.py; see the head of this file). The hands come first:
 * of the arrangements of the worn items that the model has columns for, that leave the rest a place outside the hands and that are worth exactly what the
 * arrangement in `groups` is, the one that fills the main hand before leaving it empty, by the smaller (key, tier), and then the off hand the same way.
 * `value(kit)` is the exact value (a Rational) of a kit of 22 places, under the profile, setup, assumed haste and chosen buffs of the solution; it is required,
 * because the arrangements are compared by it. The others are taken in the order of (key, tier), and each goes into the earliest group of the slot order that
 * the model has a column for it in (outside the hands) and that has a place left, provided every item after it can still be given a place. The result depends
 * on the set of items alone, not on where the solver put them. A SolveError if no place can be found (`groups` is not a placement of the model).
 */
export function placeCanonically(model, groups, value, setup = null) {
  if (typeof value !== "function") throw fail("placeCanonically needs the function that values a kit exactly: placeCanonically(model, groups, value, setup)");
  return placeHands(model, groups, value, setup).placed;
}

/**
 * Only the arrangement may change: the same items (copies counted) and, when the rule compared values, the same exact value. `valueBefore` is null when the
 * hands were left as they were, and nothing could have changed the value (`_check_rearranged` in solve.py). A PlacementError otherwise.
 */
export function checkRearranged(before, after, valueBefore, valueAfter) {
  const count = (groups) => {
    const counts = new Map();
    for (const items of groups.values()) for (const item of items) counts.set(nameOf(item), (counts.get(nameOf(item)) ?? 0) + 1);
    return counts;
  };
  const was = count(before);
  const now = count(after);
  const text = (counts) => [...counts].sort(([a], [b]) => compareText(a, b)).map(([name, copies]) => `${name} x${copies}`).join(", ");
  if (was.size !== now.size || [...was].some(([name, copies]) => now.get(name) !== copies)) {
    throw new PlacementError(`the canonical placement changed the items: ${text(was)} became ${text(now)}`);
  }
  if (valueBefore !== null && !valueAfter.equals(valueBefore)) {
    throw new PlacementError(`the canonical placement changed the value of the kit from ${valueBefore.toString()} to ${valueAfter.toString()}`);
  }
}

/** Whether the tie stage's kit replaces the first stage's: its exact value (a Rational) is not less (`second_is_taken` in solve.py: one rule). */
export const secondIsTaken = (first, second) => second.compare(first) >= 0;

/**
 * The rank of every column the tie stage prices, as a Map from the column: an item column costs its item's place among the sorted eligible items
 * (`eligible` is `[key, tier]` in that order, counted from 1), a buff column costs the place of its id among the optional buffs after all the items
 * (`tie_ranks` in solve.py).
 */
export function tieRanks(model, eligible) {
  const position = new Map(eligible.map(([key, tier], at) => [ident(key, tier), at + 1]));
  const ranks = new Map();
  for (const [column, , key, tier] of model.item_cols) ranks.set(column, position.get(ident(key, tier)));
  const base = eligible.length;
  const place = new Map(model.buff_cols.map(([, id]) => id).sort((a, b) => a - b).map((id, at) => [id, base + at + 1]));
  for (const [column, id] of model.buff_cols) ranks.set(column, place.get(id));
  return ranks;
}

// ---- the session ------------------------------------------------------------------------------------------------------------------------

/**
 * A session for one profile, weapon setup and buff set. `highs` is the loaded solver (the module that `highs`' loader gives), `profile` what
 * `assembleProfile` gives (or a fixture's `Profile.to_dict()`), `setup` null, "1h-shield", "2h", "dw" or "stick", `buffset` null or `{set, table}`,
 * `monkBins` the `monk_bins` block of the bundle (needed when the profile has a Monk curve and the armor class a weight). `options` are the base options
 * of the session, `any_rule` and `haste_assumed` (the functions of path.js set the owned-item options, and `setScenario` takes them whole). `now`
 * reads a clock in milliseconds (the budget is counted on it; the default is `performance.now`).
 *
 * The session is a plain object that the tests read: `scenarios` (a Map from a name to `{name, model, eligible, items, solver, rowNames, epoch, last}`),
 * `current` (the name `solve` takes when it names none), `closed`.
 */
export function createSession(config) {
  if (!isRecord(config)) throw fail("createSession takes an object: {highs, profile, setup, buffset, monkBins, options, now}");
  for (const key of Object.keys(config)) {
    if (!SESSION_KEYS.has(key)) throw fail(`createSession has an option (${show(key)}) that it does not read (it reads ${[...SESSION_KEYS].join(", ")})`);
  }
  const { highs, setup = null, buffset = null, monkBins = undefined, procs = null, options = {}, now = defaultNow } = config;
  if (procs !== null && !(procs instanceof ProcTable)) throw fail("procs is the table of procs of the trio (readProcs of engine/procs.js), or null");
  if (!isRecord(highs) || typeof highs.createModel !== "function" || !isRecord(highs.constants) || typeof highs.infinity !== "number") {
    throw fail("createSession needs the loaded solver (highs)");
  }
  if (!SETUP_SET.has(setup)) throw fail(`unknown setup ${show(setup)} (use ${[...SETUP_SET].map((name) => JSON.stringify(name)).join(", ")})`);
  if (typeof now !== "function") throw fail("now must be a function that reads a clock in milliseconds");
  if (!isRecord(config.profile)) throw fail("the profile is what assembleProfile gives, an object");
  const profile = frozenCopy(config.profile, "the profile");
  profileOf(profile); // a profile the evaluator would not read is refused now, not at the first solve
  if (buffset !== null && !isRecord(buffset)) throw fail("the buff set is null or an object with a set and a table");
  if (!isRecord(options)) throw fail("the options are an object, such as {haste_assumed: 25}");
  for (const key of Object.keys(options)) {
    if (!SESSION_OPTION_KEYS.has(key)) {
      throw fail(`the options of a session are any_rule and haste_assumed, not ${show(key)} (the owned-item options are set by the functions that solve; the Monk bins are monkBins)`);
    }
  }
  const read = readOptions(options);
  return {
    highs,
    profile,
    setup,
    buffset: buffset === null ? null : frozenCopy(buffset, "the buff set"),
    monkBins: monkBins === undefined || monkBins === null ? undefined : frozenCopy(monkBins, "the Monk bins"),
    procs,
    options: Object.freeze({ any_rule: read.anyRule, haste_assumed: read.hasteAssumed }),
    now,
    scenarios: new Map(),
    current: null,
    closed: false,
  };
}

/** Dispose of the solver of a scenario, if it has one. */
function dispose(scenario) {
  const { solver } = scenario;
  scenario.solver = null;
  scenario.rowNames = [];
  if (solver !== null && !solver.disposed) solver.dispose();
}

/** Make the solver's model from a model JSON: the options of the Python solver that this build takes. */
function createSolver(session, model) {
  const { highs } = session;
  let solver;
  try {
    solver = highs.createModel(toModelData(highs, model));
  } catch (error) {
    // the solver's own refusal of what it was given is the model's fault; anything else came out of the WebAssembly
    if (isRecord(highs.errors) && typeof highs.errors.HighsError === "function" && error instanceof highs.errors.HighsError) {
      throw solverFault(`The optimizer would not take this model: ${String(error.message).slice(0, MESSAGE_CHARS)}`);
    }
    throw error;
  }
  solver.options.set(SOLVER_OPTIONS);
  return solver;
}

/** Whether two models have the same columns: the same names, in the same order, and the same kinds. */
function sameColumns(a, b) {
  if (a.c.length !== b.c.length) return false;
  for (let at = 0; at < a.c.length; at += 1) {
    if (a.col_names[at] !== b.col_names[at] || a.integrality[at] !== b.integrality[at]) return false;
  }
  return true;
}

/** Whether row `r` of `a` and row `s` of `b` have the same entries (the column indices rise within a row, so the lists can be compared as they are). */
function sameEntries(a, r, b, s) {
  const length = a.A.start[r + 1] - a.A.start[r];
  if (length !== b.A.start[s + 1] - b.A.start[s]) return false;
  for (let k = 0; k < length; k += 1) {
    if (a.A.index[a.A.start[r] + k] !== b.A.index[b.A.start[s] + k] || a.A.value[a.A.start[r] + k] !== b.A.value[b.A.start[s] + k]) return false;
  }
  return true;
}

/**
 * Change the solver's model, which is `scenario.model`, into `next`, which has the same columns: costs and bounds of columns, bounds of rows that stay,
 * and the rows that are gone or changed deleted and the rows that are new or changed added at the end. The rows go by name.
 */
function updateInPlace(session, scenario, next) {
  const { solver, model } = scenario;
  const infinity = session.highs.infinity;
  const orInfinite = (value, sign) => (value === null ? sign * infinity : value);
  for (let column = 0; column < next.c.length; column += 1) {
    if (next.c[column] !== model.c[column]) solver.changeColCost(column, next.c[column]);
    if (next.col_lb[column] !== model.col_lb[column] || next.col_ub[column] !== model.col_ub[column]) {
      solver.changeColBounds(column, orInfinite(next.col_lb[column], -1), orInfinite(next.col_ub[column], 1));
    }
  }
  const oldAt = new Map(model.row_names.map((name, r) => [name, r]));
  const newAt = new Map(next.row_names.map((name, s) => [name, s]));
  const position = new Map(scenario.rowNames.map((name, at) => [name, at]));
  const doomed = [];
  for (const [name, r] of oldAt) {
    const s = newAt.get(name);
    if (s === undefined || !sameEntries(model, r, next, s)) {
      doomed.push(position.get(name));
    } else if (next.row_lb[s] !== model.row_lb[r] || next.row_ub[s] !== model.row_ub[r]) {
      solver.changeRowBounds(position.get(name), orInfinite(next.row_lb[s], -1), orInfinite(next.row_ub[s], 1));
    }
  }
  if (doomed.length > 0) {
    doomed.sort((a, b) => a - b);
    solver.deleteRows({ kind: "set", indices: doomed });
    const gone = new Set(doomed);
    scenario.rowNames = scenario.rowNames.filter((_, at) => !gone.has(at));
  }
  for (const [name, s] of newAt) {
    const r = oldAt.get(name);
    if (r !== undefined && sameEntries(model, r, next, s)) continue;
    const from = next.A.start[s];
    const to = next.A.start[s + 1];
    solver.addRow(orInfinite(next.row_lb[s], -1), orInfinite(next.row_ub[s], 1), { indices: next.A.index.slice(from, to), values: next.A.value.slice(from, to) });
    scenario.rowNames.push(name);
  }
}

/**
 * Make `name` the scenario of the pool `items` under the builder's `options` (the owned-item options included), build its model, and bring the
 * solver's model to it: in place when the columns are the same, else made anew. Returns `{name, reused, columns, rows, buildMs, syncMs}`: `reused` is
 * true when the solver's model was kept (changed in place), `buildMs` the time the builder took and `syncMs` the time the solver's model took. The
 * Monk bins of the session are added to the options unless they name their own. A pool or an option that the builder refuses leaves the scenario as
 * it was (a ModelError or an EvaluateError). The scenario becomes the one `solve` takes when it names none.
 */
export function setScenario(session, name, items, options = {}) {
  openSession(session);
  if (typeof name !== "string" || name.length === 0 || name.length > MAX_NAME_LENGTH) throw fail(`the name of a scenario is a text of one to ${MAX_NAME_LENGTH} characters`);
  if (options === null || options === undefined) options = {};
  if (!isRecord(options)) throw fail("the options are an object, the builder's");
  const built = session.now();
  const withBins = builderOptions(session, options);
  const { model, eligible } = buildMilpWithItems(session.profile, items, session.setup, session.buffset, withBins);
  return installScenario(session, name, items, { model, eligible }, built);
}

/** `setScenario` from a model that was built already (`built` is when its build began): the scenario's solver is brought to it. */
function installScenario(session, name, items, { model, eligible }, built) {
  const byIdent = new Map(items.map((item) => [ident(item.key, item.tier), item]));
  const synced = session.now();

  let scenario = session.scenarios.get(name);
  if (scenario === undefined) {
    scenario = { name, model: null, eligible: [], items: new Map(), solver: null, rowNames: [], epoch: 0, last: null };
    session.scenarios.set(name, scenario);
  }
  let reused = false;
  try {
    if (model.c.length === 0) {
      // HiGHS refuses a program without a column: the answer is the empty vector if every row allows 0 (as in the Python solver)
      dispose(scenario);
      scenario.epoch += 1;
    } else if (scenario.solver !== null && scenario.model !== null && sameColumns(scenario.model, model)) {
      updateInPlace(session, scenario, model);
      reused = true;
    } else {
      dispose(scenario);
      scenario.solver = createSolver(session, model);
      scenario.rowNames = [...model.row_names];
      scenario.epoch += 1;
    }
  } catch (error) {
    // the solver's model may be half changed: it is not trusted again
    dispose(scenario);
    scenario.model = null;
    scenario.last = null;
    throw error;
  }
  scenario.model = model;
  scenario.eligible = eligible;
  scenario.items = byIdent;
  session.current = name;
  const done = session.now();
  return { name, reused, columns: model.c.length, rows: model.row_lb.length, buildMs: synced - built, syncMs: done - synced };
}

/** Dispose of every solver of the session. Closing twice is no harm; a closed session answers nothing. */
export function closeSession(session) {
  if (!isRecord(session) || !(session.scenarios instanceof Map)) throw fail("the session is what createSession gives");
  for (const scenario of session.scenarios.values()) dispose(scenario);
  session.scenarios.clear();
  session.current = null;
  session.closed = true;
}

// ---- running the solver ------------------------------------------------------------------------------------------------------------------

function modelStatusName(highs, code) {
  for (const [name, value] of Object.entries(highs.constants.modelStatus)) if (value === code) return name;
  return String(code);
}

const finiteOrNull = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);

/** The statuses that end a run before it proves anything: a limit of time, of nodes or of solutions, an interrupt. HiGHS keeps its best kit. */
function stopStatuses(highs) {
  const states = highs.constants.modelStatus;
  return new Set([states.timeLimit, states.iterationLimit, states.solutionLimit, states.interrupted, states.objectiveBound, states.objectiveTarget]);
}

/** The options of one call (checked), applied to a solver; returns what undoes them. */
function applyHighsOptions(solver, given) {
  if (given === undefined) return () => {};
  const before = [];
  try {
    for (const [name, value] of Object.entries(given)) {
      before.push([name, solver.options.get(name)]);
      solver.options.set(name, value);
    }
  } catch (error) {
    for (const [name, value] of before.reverse()) solver.options.set(name, typeof value === "number" && !Number.isFinite(value) ? Math.sign(value) * LARGEST_OPTION : value);
    throw fail(`the solver would not take the option: ${String(error.message).slice(0, MESSAGE_CHARS)}`);
  }
  // (an option that was infinite, as objective_bound is, is put back as the largest number the solver takes: it takes no infinity and treats this as none)
  const restored = (value) => (typeof value === "number" && !Number.isFinite(value) ? Math.sign(value) * LARGEST_OPTION : value);
  return () => {
    for (const [name, value] of before.reverse()) solver.options.set(name, restored(value));
  };
}

/**
 * The solver callbacks that report progress, throttled; `undefined` when nobody listens. The events of the first stage (`stage` "solve") carry the model's
 * objective and the solver's bound and gap. The tie stage minimizes a rank, whose objective, bound and gap are not values of the kit: its events (`stage`
 * "tie") carry `shown`, the objective of the first stage, which is the value the tie stage keeps, and the node count.
 */
function progressCallbacks(session, model, onProgress, { startedAt, stage, shown }) {
  if (onProgress === undefined) return undefined;
  const types = session.highs.constants.callbackType;
  let lastReport = Number.NEGATIVE_INFINITY;
  const report = (fields) => {
    const at = session.now();
    if (at - lastReport < PROGRESS_EVERY_MS) return;
    lastReport = at;
    onProgress({ phase: "solving", stage, elapsedMs: Math.max(0, at - startedAt), ...fields });
  };
  return {
    [types.mipImprovingSolution](event) {
      const value = finiteOrNull(event.data.objective_function_value);
      if (stage === STAGE_TIE || stage === STAGE_PROOF) report({ objective: shown });
      else if (value !== null) report({ objective: value + model.const });
    },
    [types.mipLogging](event) {
      const fields = {};
      if (stage === STAGE_TIE || stage === STAGE_PROOF) {
        fields.objective = shown;
      } else {
        const bound = finiteOrNull(event.data.mip_dual_bound);
        const gap = finiteOrNull(event.data.mip_gap);
        if (bound !== null) fields.bound = bound + model.const;
        if (gap !== null && gap >= 0) fields.gap = gap;
      }
      const nodes = Number(event.data.mip_node_count);
      if (Number.isInteger(nodes) && nodes >= 0) fields.nodes = nodes;
      report(fields);
    },
  };
}

/**
 * One run of a solver: its start (a solution to begin from, dense or sparse; the solver is cleared first, so that nothing left by an earlier run is
 * taken for a start), the moment its time ends (`deadline`, on the session's clock), and what came out: `{status, highsStatus, x, bound, gap, nodes,
 * limitMs}`, `limitMs` the time the solver was given. `x` is the column vector of the best kit
 * the run had (the proven optimum, or the incumbent at a stop), null when there is none. A SolveError for a status that is no answer.
 */
function run(session, solver, model, { deadline, start, highsOptions, onProgress, startedAt, stage, shown }) {
  const { highs } = session;
  solver.clearSolver();
  if (start !== null) solver.setSolution(start);
  const undo = applyHighsOptions(solver, highsOptions);
  try {
    // the time is what is left when it is handed over (the start above may have taken some), and never more
    const limitMs = Math.max(0, deadline - session.now());
    solver.options.set("time_limit", limitMs / MS_PER_SECOND);
    solver.zeroAllClocks(); // the solver's clock runs on from one run to the next; each run has its own time
    const outcome = solver.run(progressCallbacks(session, model, onProgress, { startedAt, stage, shown }));
    const states = highs.constants.modelStatus;
    const code = outcome.modelStatus;
    const stopped = stopStatuses(highs).has(code);
    if (code !== states.optimal && code !== states.infeasible && !stopped) {
      throw solverFault(`The solver ended with the status ${modelStatusName(highs, code)}.`);
    }
    const hasSolution =
      code === states.optimal || (stopped && Number(solver.info.get("primal_solution_status")) === highs.constants.solutionStatus.feasible);
    const x = hasSolution ? solver.getSolution().colValue : null;
    if (x !== null) {
      // a solution with an entry that is not a number is no solution: every comparison with it would pass
      for (let column = 0; column < x.length; column += 1) {
        if (!Number.isFinite(x[column])) throw solverFault(`the solver's solution has an entry that is not a number: column ${model.col_names[column] ?? column} is ${x[column]}`);
      }
    }
    // A program with no integer column is a linear program: HiGHS searches no tree for it, so its node count (-1) and its MIP dual bound (0, whatever
    // the objective) mean nothing.
    const isMip = model.integrality.some((flag) => flag === 1);
    const dualBound = isMip ? finiteOrNull(solver.info.get("mip_dual_bound")) : null;
    let gap = isMip ? finiteOrNull(Number(solver.info.get("mip_gap"))) : null;
    if (gap !== null && gap < 0) gap = 0;
    const counted = Number(solver.info.get("mip_node_count"));
    const nodes = isMip && Number.isFinite(counted) ? Math.max(0, Math.trunc(counted)) : 0;
    const status = code === states.optimal ? "optimal" : code === states.infeasible ? "infeasible" : "time_limit";
    return {
      status,
      highsStatus: modelStatusName(highs, code),
      x,
      bound: dualBound === null ? null : dualBound + model.const,
      gap: status === "optimal" ? gap ?? 0 : x === null ? null : gap,
      nodes,
      limitMs,
    };
  } finally {
    undo();
  }
}

/** A whole-number column of a solution, rounded; a SolverFault if it is not a number or not whole (`_integral` in model.py). */
function integral(value, name) {
  const rounded = Math.round(value);
  if (!Number.isFinite(value) || Math.abs(value - rounded) > INTEGRAL_TOLERANCE) throw solverFault(`column ${name} is not an integer: ${value}`);
  return rounded;
}

/** The items worn in each group (sorted by key) and the ids of the chosen optional buffs, of a solution vector. */
function decode(scenario, x) {
  const { model, items } = scenario;
  const groups = new Map();
  const wears = new Map();
  for (const [column, group, key, tier] of model.item_cols) {
    const copies = integral(x[column], model.col_names[column]);
    wears.set(`${group}|${ident(key, tier)}`, copies);
    const item = items.get(ident(key, tier));
    for (let copy = 0; copy < copies; copy += 1) {
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(item);
    }
  }
  for (const placed of groups.values()) placed.sort(byKeyThenTier);
  const buffs = [];
  for (const [column, id] of model.buff_cols) {
    if (integral(x[column], model.col_names[column]) !== 0) buffs.push(id);
    wears.set(`buff|${id}`, integral(x[column], model.col_names[column]));
  }
  buffs.sort((a, b) => a - b);
  return { groups, buffs, wears };
}

/** What a run's solution is worth: the kit placed by the canonical rule, valued exactly, and checked against the model's own value. */
function valueOf(session, scenario, x) {
  const { model } = scenario;
  const decoded = decode(scenario, x);
  const evaluateKit = (kit) =>
    evaluate(session.profile, kit, session.buffset === null ? null : decoded.buffs, {
      setup: session.setup,
      hasteAssumed: model.info.haste_assumed,
      monkBins: session.monkBins,
      buffset: session.buffset ?? undefined,
      procs: session.procs ?? undefined,
    });
  const { placed, solverValue } = placeHands(model, decoded.groups, (kit) => evaluateKit(kit).F, session.setup);
  const kit = canonicalKit(placed);
  const evaluated = evaluateKit(kit);
  checkRearranged(decoded.groups, placed, solverValue, evaluated.F);
  let modelValue = model.const;
  for (let column = 0; column < x.length; column += 1) modelValue += model.c[column] * x[column];
  checkExactness(modelValue, evaluated.F.toNumber());
  return { kit, buffs: decoded.buffs, wears: decoded.wears, F: evaluated.F, breakdown: evaluated.breakdown, modelF: modelValue };
}

/** The wears of a kit as the solver's columns count them: `group|ident` for the copies of an item in a group, `buff|id` for a chosen buff. */
function wearsOfKit(kit, buffs) {
  const wears = new Map();
  kit.forEach((item, at) => {
    if (item === null) return;
    const name = `${PLACE_GROUPS[at]}|${ident(item.key, item.tier)}`;
    wears.set(name, (wears.get(name) ?? 0) + 1);
  });
  for (const id of buffs) wears.set(`buff|${id}`, 1);
  return wears;
}

/**
 * A start from the wears of a kit: a value for every item column and every buff column of the model (0 for what the kit does not wear), and none for the
 * rest, which the solver completes (the continuous columns, and the columns of the curves and pools that follow from the choice of items and buffs).
 */
function startFromWears(model, wears) {
  const found = [];
  for (const [column, group, key, tier] of model.item_cols) found.push([column, wears.get(`${group}|${ident(key, tier)}`) ?? 0]);
  for (const [column, id] of model.buff_cols) found.push([column, wears.get(`buff|${id}`) ?? 0]);
  if (found.length === 0) return null;
  found.sort((a, b) => a[0] - b[0]);
  return { indices: found.map(([column]) => column), values: found.map(([, value]) => value) };
}

/**
 * The start for the next run of a scenario and what it is: the kit it is given (`kit`), else the last solution as it is when the solver's columns are the
 * same (`solution`), else the item and buff columns of the last kit (`kit`), else none (null).
 */
function startOf(scenario, given) {
  const { last, model } = scenario;
  if (given !== undefined) {
    const start = startFromWears(model, wearsOfKit(given.kit, given.buffs));
    return { start, kind: start === null ? null : "kit" };
  }
  if (last === null) return { start: null, kind: null };
  if (last.epoch === scenario.epoch) return { start: { colValue: last.x }, kind: "solution" };
  const start = startFromWears(model, last.wears);
  return { start, kind: start === null ? null : "kit" };
}

/** A kit to start from, as the request gives it: `{kit, buffs}`, a kit of the places (an item or null in each) and the ids of the chosen buffs. */
function readStart(start) {
  if (!isRecord(start) || !Array.isArray(start.kit) || start.kit.length !== PLACES) throw fail(`start is a kit, {kit, buffs}, with a kit of ${PLACES} places`);
  for (let at = 0; at < PLACES; at += 1) {
    if (!(at in start.kit)) throw fail(`start.kit[${at}] is a hole in the list`);
    const item = start.kit[at];
    if (item !== null && !(isRecord(item) && typeof item.key === "string" && Number.isInteger(item.tier))) throw fail(`start.kit[${at}] is an item or null`);
  }
  const buffs = start.buffs === undefined ? [] : start.buffs;
  if (!Array.isArray(buffs)) throw fail("start.buffs is a list of buff ids");
  for (let at = 0; at < buffs.length; at += 1) {
    if (!(at in buffs) || !Number.isSafeInteger(buffs[at])) throw fail(`start.buffs[${at}] is the id of a buff, a whole number`);
  }
  return { kit: start.kit, buffs };
}

/** The answer of a scenario that has no column: the empty vector if every row allows 0, else no kit. */
function runEmpty(scenario) {
  const { model } = scenario;
  const feasible = model.row_lb.every((low) => low === null || low <= 0) && model.row_ub.every((high) => high === null || high >= 0);
  return { status: feasible ? "optimal" : "infeasible", highsStatus: "none", x: feasible ? new Float64Array(0) : null, bound: feasible ? model.const : null, gap: feasible ? 0 : null, nodes: 0, limitMs: 0 };
}

/** The answer record of a run (see the head of this file). */
function answerOf(session, scenario, found, extra) {
  const { highsStatus, status, bound, gap, nodes } = found;
  const solved = found.value ?? null;
  const label = status !== "time_limit" ? null : solved === null ? LABEL_NO_INCUMBENT : LABEL_TIME_LIMIT;
  return {
    status,
    label,
    proven: status !== "time_limit",
    F: solved === null ? null : solved.F,
    kit: solved === null ? null : solved.kit,
    buffs: solved === null ? [] : solved.buffs,
    breakdown: solved === null ? null : solved.breakdown,
    modelF: solved === null ? null : solved.modelF,
    gap,
    nodes,
    bound,
    canonical: false,
    tieStage: null,
    hasteAssumed: scenario.model.info.haste_assumed,
    highsStatus,
    limitMs: found.limitMs,
    start: found.startKind ?? null,
    timings: { solveMs: found.ms, tieMs: 0 },
    ...extra,
  };
}

/** A copy of a model that binary columns and rows can be added to (the proof of the shortcut and the last stage make programs of their own from the scenario's). */
class Editor {
  constructor(model) {
    this.model = model;
    this.c = [...model.c];
    this.col_lb = [...model.col_lb];
    this.col_ub = [...model.col_ub];
    this.integrality = [...model.integrality];
    this.col_names = [...model.col_names];
    this.A = { start: [...model.A.start], index: [...model.A.index], value: [...model.A.value] };
    this.row_lb = [...model.row_lb];
    this.row_ub = [...model.row_ub];
    this.row_names = [...model.row_names];
  }

  addBinary(name) {
    this.c.push(0);
    this.col_lb.push(0);
    this.col_ub.push(1);
    this.integrality.push(1);
    this.col_names.push(name);
    return this.c.length - 1;
  }

  addRow(name, terms, lb, ub) {
    for (const [column, value] of terms) {
      this.A.index.push(column);
      this.A.value.push(value);
    }
    this.A.start.push(this.A.index.length);
    this.row_lb.push(lb);
    this.row_ub.push(ub);
    this.row_names.push(name);
    return this.row_lb.length - 1;
  }

  /** The model as it is now, with `changes` (a new objective, a sense) on top. */
  made(changes = {}) {
    const { c, col_lb, col_ub, integrality, col_names, A, row_lb, row_ub, row_names } = this;
    return { ...this.model, c, col_lb, col_ub, integrality, col_names, A, row_lb, row_ub, row_names, ...changes };
  }
}

/** The columns of each item of a model, in a Map from its ident. */
function columnsByItem(model) {
  const byItem = new Map();
  for (const [column, , key, tier] of model.item_cols) {
    const name = ident(key, tier);
    if (!byItem.has(name)) byItem.set(name, []);
    byItem.get(name).push(column);
  }
  return byItem;
}

/**
 * Add to `editor` the row that says "not the worn items (copies counted) of the solution `x`, and, when `buffColumns` is given (`[column, id]` pairs), not its chosen buffs either" (the row
 * `tie.other` of the proof of the shortcut says it of the items alone, `itemsAreSettled`, whose head has the account of how the row works, and the last stage says it of the buffs too).
 * A buff counts for the row when it is on and the kit has it off, or off and the kit has it on: `(1 - y)` for a buff that the kit has on, so the row's lower bound is 1 less for each.
 * `label` keeps the names of the rows and columns of one kit apart from those of another.
 */
function addDifferenceRow(editor, byItem, x, buffColumns, label) {
  const differs = []; // the terms of the row that says the worn items are not the kit's
  let lower = 1;
  for (const [name, own] of byItem) {
    const worn = Math.round(own.reduce((sum, column) => sum + x[column], 0));
    if (worn === 0) {
      for (const column of own) differs.push([column, 1]);
      continue;
    }
    const reach = own.reduce((sum, column) => sum + editor.col_ub[column], 0);
    if (reach > worn) {
      const more = editor.addBinary(`tie.more[${label}${name}]`); // 1 only if the item is worn more often than the kit wears it
      editor.addRow(`tie.more.row[${label}${name}]`, [...own.map((column) => [column, 1]), [more, -(worn + 1)]], 0, null);
      differs.push([more, 1]);
    }
    const fewer = editor.addBinary(`tie.fewer[${label}${name}]`); // 1 only if the item is worn less often
    editor.addRow(`tie.fewer.row[${label}${name}]`, [...own.map((column) => [column, 1]), [fewer, reach - worn + 1]], null, reach);
    differs.push([fewer, 1]);
  }
  for (const [column] of buffColumns ?? []) {
    if (Math.round(x[column]) === 1) {
      differs.push([column, -1]);
      lower -= 1;
    } else {
      differs.push([column, 1]);
    }
  }
  editor.addRow(`tie.other${label === "" ? "" : `[${label.slice(0, -1)}]`}`, differs, lower, null);
}

/**
 * Whether the band of the tie stage holds one set of worn items (`{settled, nodes}`, the nodes of the proof): no other set of items (copies counted), whatever buffs are chosen, has a model value of at least
 * `best - 1e-7 max(1, |best|)`. The tie stage chooses among the kits of that band, and it is a hard program (the rank is a dense objective that the relaxation bounds badly);
 * this is the cheaper way to learn that the items at least are settled: the program of the scenario with one more row that excludes every kit that wears the first stage's
 * items, and a cutoff at the bottom of the band, which is a proof of the kind the levels' cutoff runs are ("no kit is worth that much": ended optimal below the cutoff, or
 * infeasible). Any answer but a proof (another set of items in the band, a stop at the time limit) is "no", and the tie stage runs as it always did.
 *
 * What a yes lets the tie stage do. Every kit of the band wears the first stage's items, so what is left to choose is the buffs, and where the items stand. Where they stand is
 * the solver's to choose in the tie stage, as it always was (an off-hand shield goes into the softcap term of the armor class, so a buff can make one place worth more than
 * another): the columns of the items are not fixed, which would fix the places too. The tie stage keeps one row for each item, `sum of its columns = N*_i`, which is exactly
 * what was proven (the copies of each item) and no more, and looks for the least rank: every kit of the band satisfies the rows, so the optimum of the whole tie stage is
 * the optimum of this one, in the places too. With no optional buff there is nothing left to choose but the places, which the canonical placement undoes (`placeHands`
 * depends on the set of worn items alone), and the kit of the first stage is the tie stage's.
 *
 * The row that excludes the kits. A worn set is `N_i` copies of each item `i` (the sum of its columns, in every group). `N != N*` is `sum over the items i with N*_i = 0
 * of N_i + sum over the other items of (more_i + fewer_i) >= 1`, where `more_i` may be 1 only if `N_i >= N*_i + 1` (the row `N_i >= (N*_i + 1) more_i`) and `fewer_i` only if
 * `N_i <= N*_i - 1` (`N_i + (reach_i - N*_i + 1) fewer_i <= reach_i`, `reach_i` the most the columns of `i` can hold). A kit whose set differs makes at least one term of the
 * sum 1, and each added binary can be 1 only where it is true, so the kits that the row leaves out are exactly the ones that wear the set of the first stage's kit, whatever
 * buffs they choose, and no other. (Rows that said `N_i >= N*_i` for `more_i` and `N_i <= N*_i` for `fewer_i` would leave out the kits that wear more or less than the first
 * stage's, which makes "yes" the answer for want of looking: tests-js/engine-tie-shortcut.test.mjs holds the shortcut to the whole tie stage on pools with tied items, where
 * that mistake shows.)
 */
function itemsAreSettled(session, scenario, first, { deadline, startedAt, highsOptions, onProgress }) {
  const { model } = scenario;
  const columns = model.c.length;
  const best = first.value.modelF;
  const cutoff = best - TIE_TOLERANCE * Math.max(1, Math.abs(best));
  const editor = new Editor(model);
  addDifferenceRow(editor, columnsByItem(model), first.x, null, ""); // the worn items are not the first stage's
  const other = editor.made();
  const solver = createSolver(session, other);
  try {
    const found = run(session, solver, other, {
      deadline,
      start: null,
      highsOptions: { ...highsOptions, objective_bound: -(cutoff - model.const) }, // (the program is a maximum and the solver minimizes the negative)
      onProgress,
      startedAt,
      stage: STAGE_PROOF,
      shown: best,
    });
    if (found.status === "infeasible") return { settled: true, nodes: found.nodes };
    if (found.status !== "optimal") return { settled: false, nodes: found.nodes };
    if (found.x === null) return { settled: true, nodes: found.nodes };
    let value = model.const;
    for (let column = 0; column < columns; column += 1) value += model.c[column] * found.x[column];
    return { settled: value < cutoff, nodes: found.nodes }; // (a kit worth less than the cutoff is what the solver came across, not a kit of the band)
  } finally {
    solver.dispose();
  }
}

/**
 * The second stage (`solve_canonical` in solve.py): once the best value is known, solve again with the extra row `F >= best - 1e-7 max(1, |best|)` and
 * the objective "minimize the total rank" (`tieRanks`), on a model of its own so that the scenario's solver is left as it was. Returns the kit of the
 * second stage, or null when it did not end optimal.
 */
function tieStage(session, scenario, first, { deadline, allowance, highsOptions, onProgress, startedAt, shortcut, tiedKits }) {
  const { highs } = session;
  const { model } = scenario;
  let settled = false; // the items are the first stage's in every kit of the band: the tie stage keeps the copies of each item as they are
  let proofNodes = 0;
  if (shortcut) {
    const proof = itemsAreSettled(session, scenario, first, { deadline, startedAt, highsOptions, onProgress });
    settled = proof.settled;
    proofNodes = proof.nodes;
    if (settled && model.buff_cols.length === 0) return { ...first, nodes: proofNodes }; // (a band of one set of items and no buff has nothing to choose but the places)
    deadline = session.now() + allowance; // (the proof was a stage of its own: the tie stage has its whole allowance still)
  }
  const best = first.value.modelF;
  const tolerance = TIE_TOLERANCE * Math.max(1, Math.abs(best));
  const cost = new Array(model.c.length).fill(0);
  for (const [column, rank] of tieRanks(model, scenario.eligible)) cost[column] = rank;
  const live = [];
  model.c.forEach((coefficient, column) => {
    if (coefficient !== 0) live.push(column); // the row F >= best - tolerance, over the columns that carry value
  });
  const tie = {
    ...model,
    sense: "min",
    c: cost,
    row_lb: [...model.row_lb, best - model.const - tolerance],
    row_ub: [...model.row_ub, null],
    A: {
      start: [...model.A.start, model.A.start[model.A.start.length - 1] + live.length],
      index: [...model.A.index, ...live],
      value: [...model.A.value, ...live.map((column) => model.c[column])],
    },
  };
  if (settled) {
    // one row for each item that the kit wears, `sum of its columns = the copies the kit wears`: what the proof proved, and not where the copies stand
    const copies = new Map();
    for (const [column, , key, tier] of model.item_cols) {
      const name = ident(key, tier);
      if (!copies.has(name)) copies.set(name, []);
      copies.get(name).push(column);
    }
    for (const columns of copies.values()) {
      const worn = Math.round(columns.reduce((sum, column) => sum + first.x[column], 0));
      if (worn === 0) continue;
      tie.row_lb.push(worn);
      tie.row_ub.push(worn);
      tie.A.index.push(...columns);
      tie.A.value.push(...columns.map(() => 1));
      tie.A.start.push(tie.A.index.length);
    }
  }
  const solver = createSolver(session, tie);
  try {
    const found = run(session, solver, tie, { deadline, start: { colValue: first.x }, highsOptions, onProgress, startedAt, stage: STAGE_TIE, shown: best });
    if (found.status !== "optimal" || found.x === null) return null;
    const second = { ...found, nodes: found.nodes + proofNodes, value: valueOf(session, scenario, found.x) };
    if (!secondIsTaken(first.value.F, second.value.F)) return second; // (the caller keeps the first stage's kit: nothing to settle)
    return settleTies(session, scenario, tie, cost, second, { allowance, highsOptions, onProgress, startedAt, tiedKits, shown: best });
  } finally {
    solver.dispose();
  }
}

/**
 * The last stage (`_settle_ties` in solve.py, and the head of this file): `second` is the kit of the tie stage, `tie` its program and `cost` the ranks of its columns. Returns the member of
 * the tie that is first in the order of the kits, as `second` with `x`, `value` and `nodes` of its own, and `complete`, whether the proof that nothing more ties ran to its end. Each
 * solve has the whole `allowance` (a deadline of its own). The program is the tie stage's with the objective the scenario's own (a maximum of the value, so that it is no tie program of the
 * tests, which count the programs that minimize), the band of its row narrowed to `TIE_PROOF_TOLERANCE`, the cutoff of that band as the solver's `objective_bound`, and two things added: the row
 * `total rank <= R`, and for each kit found so far a row that leaves it out. A run that ends infeasible, or optimal with a kit worth less than the cutoff, is the proof.
 */
function settleTies(session, scenario, tie, cost, second, { allowance, highsOptions, onProgress, startedAt, tiedKits, shown }) {
  const { model } = scenario;
  const columns = model.c.length;
  const byItem = columnsByItem(model);
  if (byItem.size === 0 && model.buff_cols.length === 0) return { ...second, complete: true }; // (no column carries a rank: one kit)
  const ranked = [];
  cost.forEach((rank, column) => {
    if (rank !== 0) ranked.push([column, rank]);
  });
  const rankOf = (x) => Math.round(ranked.reduce((sum, [column, rank]) => sum + rank * x[column], 0));
  const editor = new Editor(tie);
  editor.c = [...model.c]; // (the value, not the rank)
  const floor = shown - TIE_PROOF_TOLERANCE * Math.max(1, Math.abs(shown)); // the lowest value (the constant included) of a kit that can tie
  editor.row_lb[model.row_lb.length] = floor - model.const; // (the row of the band that the tie stage added, narrowed)
  const options = { ...highsOptions, objective_bound: -(floor - model.const) }; // (the program is a maximum and the solver minimizes the negative)
  const rankRow = editor.addRow("tie.rank", ranked, null, null);
  const limit = tiedKits ?? MAX_TIED_KITS;
  let best = second;
  let bestRank = rankOf(second.x);
  let nodes = second.nodes;
  addDifferenceRow(editor, byItem, second.x, model.buff_cols, "0:");
  for (let found = 1; found <= limit; found += 1) {
    editor.row_ub[rankRow] = bestRank;
    const program = editor.made({ sense: "max" });
    const solver = createSolver(session, program);
    let probe;
    try {
      probe = run(session, solver, program, { deadline: session.now() + allowance, start: null, highsOptions: options, onProgress, startedAt, stage: STAGE_TIE, shown });
    } finally {
      solver.dispose();
    }
    nodes += probe.nodes;
    if (probe.status === "infeasible") return { ...best, nodes, complete: true };
    if (probe.status !== "optimal" || probe.x === null) return { ...best, nodes, complete: false };
    const x = probe.x.slice(0, columns);
    const value = valueOf(session, scenario, x);
    if (value.modelF < floor) return { ...best, nodes, complete: true }; // (the kit the solver came across is worth less than the cutoff: none of the band is left)
    const rank = rankOf(x);
    const byValue = value.F.compare(best.value.F);
    if (byValue > 0 || (byValue === 0 && (rank < bestRank || (rank === bestRank && compareKits(value.kit, value.buffs, best.value.kit, best.value.buffs) < 0)))) {
      best = { ...probe, x, value };
      bestRank = rank;
    }
    addDifferenceRow(editor, byItem, x, model.buff_cols, `${found}:`);
  }
  return { ...best, nodes, complete: false };
}

/**
 * Solve a scenario of the session and value the answer exactly (see the head of this file). `request` is
 * `{scenario, budgetMs, deadline, canonical, start, highsOptions, onProgress, cutoff}`: `cutoff` (optional) a value of the model, the constant included, that a kit must reach:
 * the first stage looks for none worth less and ends "infeasible" if there is none; `scenario` the name given to `setScenario` (the last one set when omitted),
 * `budgetMs` the whole time of the call (required: a number from 0), `deadline` a moment on the clock of the session by which the first stage must end
 * if that is earlier than the end of the budget, `start` a kit to begin from (`{kit, buffs}`, say an answer), `canonical` whether to run the tie stage
 * (default false), `highsOptions` single options of the solver for this call (a test hook: `mip_max_nodes`, say; never `threads` or `time_limit`),
 * `onProgress` a function that gets `{phase: "solving", stage, elapsedMs, objective?, bound?, gap?, nodes?}` (`stage` is "solve", "proof" or "tie", see the head of
 * this file). A SolveError for a request that is not understood, a solver status that is no answer, and an ExactnessError for a model that overstates its
 * own kit.
 */
export function solve(session, request) {
  openSession(session);
  if (!isRecord(request)) throw fail("solve takes a request: {scenario, budgetMs, canonical}");
  for (const key of Object.keys(request)) {
    if (!SOLVE_KEYS.has(key)) throw fail(`the request has an option (${show(key)}) that solve does not read (it reads ${[...SOLVE_KEYS].join(", ")})`);
  }
  const { budgetMs, deadline, canonical = false, highsOptions, onProgress, start: given, cutoff, tieShortcut = true, tiedKits } = request;
  if (typeof tieShortcut !== "boolean") throw fail("tieShortcut is true or false");
  if (tiedKits !== undefined && (!Number.isInteger(tiedKits) || tiedKits < 1)) throw fail("tiedKits is the most kits of a tie that the last stage sets apart, a whole number from 1");
  if (cutoff !== undefined && (typeof cutoff !== "number" || !Number.isFinite(cutoff))) throw fail("cutoff is a value of the model (the constant included) that a kit must reach, a number");
  if (typeof budgetMs !== "number" || !Number.isFinite(budgetMs) || budgetMs < 0) throw fail("budgetMs is the time of the call in milliseconds, a number from 0");
  if (deadline !== undefined && (typeof deadline !== "number" || !Number.isFinite(deadline))) throw fail("deadline is a moment on the clock of the session, in milliseconds");
  if (typeof canonical !== "boolean") throw fail("canonical is true or false");
  if (onProgress !== undefined && typeof onProgress !== "function") throw fail("onProgress is a function");
  const offered = given === undefined ? undefined : readStart(given);
  if (highsOptions !== undefined) {
    if (!isRecord(highsOptions)) throw fail("highsOptions is an object of solver options");
    for (const name of Object.keys(highsOptions)) {
      if (REFUSED_HIGHS_OPTIONS.has(name)) throw fail(`the solver option ${name} is not for a call to set (the budget is the time limit, and the build has one thread)`);
    }
  }
  const name = request.scenario === undefined ? session.current : request.scenario;
  const scenario = typeof name === "string" ? session.scenarios.get(name) : undefined;
  if (scenario === undefined || scenario.model === null) throw fail(`there is no scenario ${show(name)}: set one with setScenario first`);

  const startedAt = session.now();

  // the first stage: the time that is left of the call's budget is what the solver is handed, when it is handed
  const began = session.now();
  const chosen = scenario.solver === null ? { start: null, kind: null } : startOf(scenario, offered);
  const found =
    scenario.solver === null
      ? { ...runEmpty(scenario) }
      : run(session, scenario.solver, scenario.model, {
          deadline: deadline === undefined ? startedAt + budgetMs : Math.min(startedAt + budgetMs, deadline),
          start: chosen.start,
          highsOptions: cutoff === undefined ? highsOptions : { ...highsOptions, objective_bound: -(cutoff - scenario.model.const) }, // (the first stage only; the program is a maximum and the solver minimizes the negative)
          onProgress,
          startedAt,
          stage: STAGE_SOLVE,
          shown: null,
        });
  if (found.x !== null) found.value = valueOf(session, scenario, found.x);
  found.startKind = chosen.kind;
  found.ms = session.now() - began;
  let answer = answerOf(session, scenario, found, {});
  let used = found;

  // the second stage has a budget of its own, as in Python, where each solve is given its time limit (a canonical call can take about three times `budgetMs`: the first stage, the proof of `itemsAreSettled`, the tie stage);
  // a program with no column has one kit, and so nothing to separate: it is canonical as it stands
  if (canonical && found.status === "optimal" && scenario.solver === null) {
    answer.canonical = true;
    answer.tieStage = "applied";
  } else if (canonical && found.status === "optimal" && !(cutoff !== undefined && found.value !== undefined && found.value.modelF < cutoff)) {
    // (with a cutoff, a kit worth less than it is what the solver came across, not the best there is: there is nothing to separate)
    const tied = session.now();
    const second = tieStage(session, scenario, found, { deadline: tied + budgetMs, allowance: budgetMs, highsOptions, onProgress, startedAt, shortcut: tieShortcut, tiedKits });
    const tieMs = session.now() - tied;
    if (second !== null && secondIsTaken(found.value.F, second.value.F)) {
      // the band is a net for float noise, not a licence to lose value: the kit is accepted unless it is worth less (a better kit than the first stage's is the better answer, as in Python)
      answer = answerOf(
        session,
        scenario,
        { ...second, gap: found.gap, nodes: found.nodes + second.nodes, bound: found.bound, limitMs: found.limitMs, ms: found.ms, startKind: found.startKind },
        { canonical: second.complete !== false, tieStage: "applied" },
      );
      used = second;
    } else {
      answer.tieStage = "kept-first";
    }
    answer.timings = { solveMs: found.ms, tieMs };
  }

  // the next solve starts from this kit
  if (used.x !== null && used.value !== undefined) scenario.last = { epoch: scenario.epoch, x: Float64Array.from(used.x), wears: used.value.wears };
  answer.elapsedMs = session.now() - startedAt;
  return answer;
}

// ---- the truthful solve ---------------------------------------------------------------------------------------------------------------------------

/**
 * The weapon term is paid the haste the kit really counts (`solve_scenario` in haste.py has the whole account). A program assumes one haste for the weapon index; the kit
 * counts one of a few hastes (an active spell haste plus the best worn piece, or none, cut at the cap: `hasteLevels` of model.js lists them). For each level `H` the
 * program is built with `haste_assumed` and `haste_floor` both `H` (the kit counts at least `H`), solved, and its kit valued again at the haste it counts; the best truthful
 * value is the optimum. A kit whose assumed haste is the haste it counts goes before one that counts more, and among equals the lower level wins. The levels are solved
 * best first (the level whose linear relaxation allows the most), and a level whose linear relaxation cannot reach the best value found is not solved, nor any after it. The program of a level is the scenario `<name>#<level>` of the
 * session, and stays there between calls (the scenario of a path keeps its models). An option `haste_assumed` fixes one haste, as it always did: one program, no levels; a
 * scenario that scores no weapon (no damage weight, or a setup that scores none) has one program too.
 *
 * `request` is `{name, items, options, budgetMs, deadline, canonical, start, highsOptions, onProgress, bound, needTime, floor}`: the builder's pool and options as `setScenario`
 * takes them, and what `solve` takes; `budgetMs` is the time of the whole call (with a `deadline`, the call ends by it, and the budget is what was left of it), `bound: false` solves every level, and `needTime: true` begins no solve when the time is gone by
 * the moment the first model is made (the call then returns null, with the model made: a path that has spent its budget starts nothing), and `floor` (a number, a value of the kit) says that only a kit worth at least that is
 * looked for: the levels whose relaxation cannot reach it are left out, the others are searched with the cutoff of the first stage's kind, and when no kit is worth it the answer is the one of no kit at all (`infeasible`,
 * `kit` null, proven): the look for an earlier equal addition of the farm path asks for no more than that, and it is far cheaper than the best kit. It returns the answer of `solve` for the winning level with
 * `F`, `kit`, `buffs` and `breakdown` those of the winner at the haste it counts, `hasteAssumed` that haste, `level` the level whose program the kit came from, `levels`
 * every level of the scenario, `program` the name of the scenario of the session that holds the program of the winner, `runs` what became of each (`{level, outcome: "solved" | "bound" | "infeasible" | "time", status, F, counted, bound}`), `nodes` the nodes of every
 * solve added up, `timings` the milliseconds of the solves added up, `build` what `setScenario` said, added up (`{buildMs, syncMs, reused, columns, rows}`), and
 * `status`/`label`/`proven` those of the whole: `optimal` when every level that was solved ended optimal and none was left for want of time.
 */
export function solveScenario(session, request) {
  openSession(session);
  if (!isRecord(request)) throw fail("solveScenario takes a request: {name, items, options, budgetMs, canonical}");
  for (const key of Object.keys(request)) {
    if (!TRUTHFUL_KEYS.has(key)) throw fail(`the request has an option (${show(key)}) that solveScenario does not read (it reads ${[...TRUTHFUL_KEYS].join(", ")})`);
  }
  const { name, items, budgetMs, deadline, canonical = false, start, highsOptions, onProgress, bound = true, needTime = false, tieShortcut = true, floor } = request;
  if (floor !== undefined && (typeof floor !== "number" || !Number.isFinite(floor))) throw fail("floor is the least value of a kit that is looked for, a number");
  const options = request.options === undefined || request.options === null ? {} : request.options;
  if (typeof budgetMs !== "number" || !Number.isFinite(budgetMs) || budgetMs < 0) throw fail("budgetMs is the time of the call in milliseconds, a number from 0");
  if (typeof bound !== "boolean") throw fail("bound is true or false");
  if (typeof needTime !== "boolean") throw fail("needTime is true or false");
  if (typeof tieShortcut !== "boolean") throw fail("tieShortcut is true or false");
  if (!isRecord(options)) throw fail("the options are an object, the builder's");
  const opts = readOptions(options);
  if (opts.hasteFloor !== null && opts.hasteAssumed === null) throw fail("haste_floor without haste_assumed: the levels set both");
  // the call ends by its deadline if it has one (the budget is then what was left of it when the call was made), else `budgetMs` from now: one look at the clock, and none if there is a deadline
  const callEnd = deadline !== undefined ? deadline : session.now() + budgetMs;
  const left = () => Math.max(0, callEnd - session.now());
  const call = { deadline, canonical, highsOptions, onProgress, tieShortcut };
  const finish = (answer, more) => Object.assign(answer, more);
  const profile = profileOf(session.profile);
  const scoresWeapons = session.setup !== null && session.setup !== "stick" && profile.weights.DMG.sign() !== 0;

  // one program: a fixed haste, or no weapon to score
  if (opts.hasteAssumed !== null || !scoresWeapons) {
    const fixed = opts.hasteAssumed !== null;
    const cutoff = floor === undefined ? undefined : floor - EXACTNESS_TOLERANCE * Math.max(1, Math.abs(floor));
    const program = solveProgram(session, name, items, fixed ? options : { ...options, haste_assumed: 0 }, null, { left, call, start, needTime, cutoff });
    if (program === null) return null;
    const { build, answer } = program;
    if (cutoff !== undefined && (answer.status === "infeasible" || (answer.status === "optimal" && (answer.kit === null || answer.modelF < cutoff)))) {
      // (with a cutoff, a kit worth less than it is what the solver came across, not the best there is: no kit is worth the floor)
      const level = answer.hasteAssumed;
      return finish(infeasibleAnswer(level), { build, level, levels: [level], program: name, runs: [{ level, outcome: "bound", status: answer.status, F: null, counted: null, bound: null }] });
    }
    if (!fixed && answer.kit !== null) {
      // no weapon is scored, so the value is the same at any haste: the answer says the haste the kit counts
      const counted = Number(answer.breakdown.totals.haste.counted.floor());
      const again = evaluateAt(session, answer.kit, answer.buffs, counted);
      answer.F = again.F;
      answer.breakdown = again.breakdown;
      answer.hasteAssumed = counted;
    }
    const level = answer.hasteAssumed;
    return finish(answer, { build, level, levels: [level], program: name, runs: [{ level, outcome: "solved", status: answer.status, F: answer.F, counted: null, bound: null }] });
  }

  const withBins = builderOptions(session, options);
  const build = { buildMs: 0, syncMs: 0, reused: true, columns: 0, rows: 0 };
  // (the build is timed on the real clock: the session's clock is looked at for the budget, and a look is a look)
  const sharedAt = performance.now();
  const shared = new LevelPrograms(session.profile, items, session.setup, session.buffset, withBins); // the programs of the levels share one build
  const levels = shared.levels;
  build.buildMs += performance.now() - sharedAt;
  const runs = [];
  const timings = { solveMs: 0, tieMs: 0 };
  let won = null;
  let nodes = 0;
  let stopped = false;
  let last = null;
  let begun = false; // a program of the call has been solved
  // the program of each level, with the best value its relaxation allows; with the bound they are solved best first (and the levels below the best value found are left
  // out), else from the highest level down
  const programs = [];
  const bounds = bound && levels.length > 1 ? levelBounds(session, shared, callEnd) : null;
  try {
    for (const level of [...levels].reverse()) {
      const scenarioName = programName(name, level);
      let ceiling;
      if (bounds !== null) {
        ceiling = bounds.of(level);
        if (ceiling === null) {
          runs.push({ level, outcome: "infeasible", status: null, F: null, counted: null, bound: null });
          continue;
        }
      }
      programs.push({ level, scenarioName, ceiling });
    }
  } finally {
    if (bounds !== null) bounds.close();
  }
  if (bound && levels.length > 1) programs.sort((a, b) => (b.ceiling ?? Infinity) - (a.ceiling ?? Infinity) || b.level - a.level);
  for (const { level, scenarioName, ceiling } of programs) {
    if ((won !== null || floor !== undefined) && ceiling !== undefined) {
      const best = won !== null ? won.answer.F.toNumber() : floor;
      if (ceiling < best - EXACTNESS_TOLERANCE * Math.max(1, Math.abs(best))) {
        runs.push({ level, outcome: "bound", status: null, F: null, counted: null, bound: ceiling });
        continue; // (a level the bound rules out is finished, whatever the time)
      }
    }
    if (won !== null && left() <= 0) {
      // the time is gone: the levels that could still win are not looked at, and their programs are not built
      runs.push({ level, outcome: "time", status: null, F: null, counted: null, bound: ceiling ?? null });
      stopped = true;
      continue;
    }
    const modelAt = performance.now();
    const model = shared.programFor(level);
    build.buildMs += performance.now() - modelAt;
    const made = installScenario(session, scenarioName, items, { model, eligible: shared.eligible }, session.now()); // (only a level the bound does not rule out, and the time allows, has a scenario)
    const started = won !== null ? { kit: won.answer.kit, buffs: won.answer.buffs } : start;
    // a level is only worth looking for a kit of at least the best value found: the search is told so (a level that has none ends "infeasible", and is "bound")
    let cutoff;
    if (bound && won !== null && !stopped) {
      const best = won.answer.F.toNumber();
      cutoff = best - EXACTNESS_TOLERANCE * Math.max(1, Math.abs(best));
    } else if (floor !== undefined && won === null) {
      cutoff = floor - EXACTNESS_TOLERANCE * Math.max(1, Math.abs(floor)); // (no kit is worth less than the floor: a level that has none is "bound")
    }
    const solved = solveProgram(session, scenarioName, items, null, made, { left, call, start: started, needTime: needTime && !begun, cutoff });
    if (solved === null) return null;
    begun = true;
    addBuild(build, solved.build);
    const answer = solved.answer;
    timings.solveMs += answer.timings.solveMs;
    timings.tieMs += answer.timings.tieMs;
    if (answer.status === "infeasible" || (cutoff !== undefined && answer.status === "optimal" && (answer.kit === null || answer.modelF < cutoff))) {
      // (with a cutoff, a kit worth less than it is what the solver came across, not the level's best: the level cannot win)
      runs.push({ level, outcome: cutoff === undefined ? "infeasible" : "bound", status: answer.status, F: null, counted: null, bound: ceiling ?? null });
      continue;
    }
    last = { answer, level };
    nodes += answer.nodes ?? 0;
    if (answer.status !== "optimal") stopped = true;
    if (answer.kit === null) {
      runs.push({ level, outcome: "solved", status: answer.status, F: null, counted: null, bound: ceiling ?? null });
      continue;
    }
    const counted = Number(answer.breakdown.totals.haste.counted.floor());
    const consistent = counted === level;
    let candidate = answer;
    if (!consistent) {
      const again = evaluateAt(session, answer.kit, answer.buffs, counted);
      candidate = { ...answer, F: again.F, breakdown: again.breakdown, hasteAssumed: counted };
    }
    runs.push({ level, outcome: "solved", status: answer.status, F: candidate.F, counted, bound: ceiling ?? null });
    // the larger value wins, then the kit that counts what its program assumed, then the lower level
    const order = won === null ? 1 : candidate.F.compare(won.answer.F) || Number(consistent) - Number(won.consistent) || won.level - level;
    if (order > 0) won = { answer: candidate, level, consistent };
  }
  if (won === null) {
    if (last === null) {
      // no level has a kit: the answer is that there is none, at the highest level (its program is the first the call made)
      const top = levels[levels.length - 1];
      return finish(infeasibleAnswer(top), { build, level: top, levels, program: programName(name, top), runs, nodes, timings });
    }
    // one level stopped on its time with no kit and the others had none: the answer says the time ran out (and which level it is of)
    const status = stopped ? "time_limit" : last.answer.status;
    const label = status !== "time_limit" ? null : last.answer.kit === null ? LABEL_NO_INCUMBENT : LABEL_TIME_LIMIT;
    return finish(last.answer, { status, label, proven: status !== "time_limit", build, level: last.level, levels, program: programName(name, last.level), runs, nodes, timings });
  }
  const winner = won.answer;
  const status = stopped ? "time_limit" : winner.status;
  const label = status !== "time_limit" ? null : winner.kit === null ? LABEL_NO_INCUMBENT : LABEL_TIME_LIMIT;
  return finish(winner, { status, label, proven: status !== "time_limit", nodes, timings, build, level: won.level, levels, program: programName(name, won.level), runs });
}

/** The name of the scenario that holds the program of a haste level of the scenario `name` (`solveScenario`). */
export const programName = (name, level) => `${name}#${level}`;

/** The names of the scenarios of the session that `solveScenario` made for `name`: the program of each level it looked at (a call with one program, fixed or alone, made `name` itself). */
export function programsOf(session, name) {
  openSession(session);
  return [...session.scenarios.keys()].filter((key) => key === name || key.startsWith(`${name}#`));
}

/** The answer of a call with no kit at all: nothing satisfies the rows of any level. */
function infeasibleAnswer(level) {
  return {
    status: "infeasible", label: null, proven: true, F: null, kit: null, buffs: [], breakdown: null, modelF: null, gap: null, nodes: 0, bound: null,
    canonical: false, tieStage: null, hasteAssumed: level, highsStatus: "none", limitMs: 0, start: null, timings: { solveMs: 0, tieMs: 0 },
  };
}

/** The kit valued exactly at an assumed haste, under the session's profile, setup and buff set. */
function evaluateAt(session, kit, buffs, haste) {
  return evaluate(session.profile, kit, session.buffset === null ? null : buffs, {
    setup: session.setup,
    hasteAssumed: haste,
    monkBins: session.monkBins,
    buffset: session.buffset ?? undefined,
    procs: session.procs ?? undefined,
  });
}

/** The builder's options of a call, with the Monk bins and the table of procs of the session in them (what the caller gave stands). */
export function builderOptions(session, options) {
  const has = (name) => Object.prototype.hasOwnProperty.call(options, name);
  const withBins = session.monkBins !== undefined && !has("monk_bins") ? { ...options, monk_bins: session.monkBins } : options;
  return session.procs !== null && session.procs !== undefined && !has("procs") ? { ...withBins, procs: session.procs } : withBins;
}

/** Add what `setScenario` said about a program to the account of the call. */
function addBuild(total, made) {
  total.buildMs += made.buildMs;
  total.syncMs += made.syncMs;
  total.reused = total.reused && made.reused;
  total.columns = made.columns;
  total.rows = made.rows;
}

/** `setScenario` (unless the program was just made, for its relaxation) and `solve` of one program, as `{build, answer}`; null when `needTime` and the time was gone once the model was made. */
function solveProgram(session, scenarioName, items, options, made, { left, call, start, needTime, cutoff }) {
  const build = made ?? setScenario(session, scenarioName, items, options);
  const remaining = left(); // one look at the clock: what is found to be left is what is handed over
  if (needTime && remaining <= 0) return null;
  const answer = solve(session, {
    scenario: scenarioName,
    budgetMs: remaining,
    deadline: call.deadline,
    canonical: call.canonical,
    tieShortcut: call.tieShortcut,
    highsOptions: call.highsOptions,
    onProgress: call.onProgress,
    start,
    ...(cutoff === undefined ? {} : { cutoff }),
  });
  return { build, answer };
}

/**
 * The best value of the program of a level with its integer columns relaxed (an upper bound of its optimum, the constant included), for the levels of one call, from one solver that is
 * changed from level to level (the objective and the rows of the level) so that the basis of a level starts the next. `of(level)` is a number; null when no point satisfies the rows;
 * undefined when there is no bound (the solver did not get to the end by `callEnd`, or went wrong, or the program has no column). `close()` disposes of the solver.
 */
function levelBounds(session, shared, callEnd) {
  const { base } = shared;
  const columns = base.c.length;
  const baseRows = base.row_lb.length;
  const { highs } = session;
  const orInfinite = (value, sign) => (value === null ? sign * highs.infinity : value);
  let solver = null;
  let appended = 0; // the rows of the last level, after the rows of the level-free model
  let broken = columns === 0; // a solve that did not end: no more bounds from this solver (the levels are solved, never left out)
  return {
    /** The bound of `level`: a number, null for a proof that no point satisfies the rows, undefined for no bound. */
    of(level) {
      if (broken) return undefined;
      const { c, rows } = shared.parts(level);
      try {
        if (solver === null) solver = createSolver(session, { ...base, integrality: base.integrality.map(() => 0) });
        if (appended > 0) solver.deleteRows({ kind: "range", from: baseRows, to: baseRows + appended - 1 });
        appended = 0;
        if (rows.count > 0) {
          solver.addRows({
            lower: Float64Array.from(rows.lb, (value) => orInfinite(value, -1)),
            upper: Float64Array.from(rows.ub, (value) => orInfinite(value, 1)),
            matrix: { format: "csr", numRows: rows.count, numCols: columns, starts: Int32Array.from(rows.start), indices: Int32Array.from(rows.index), values: Float64Array.from(rows.value) },
          });
          appended = rows.count;
        }
        solver.changeColsCost({ kind: "range", from: 0, to: columns - 1 }, Float64Array.from(c));
        // (the solver is not cleared between levels: the basis of one level starts the next)
        solver.options.set("time_limit", Math.max(0, callEnd - session.now()) / MS_PER_SECOND);
        solver.zeroAllClocks();
        const code = solver.run().modelStatus;
        const states = highs.constants.modelStatus;
        if (code === states.infeasible) return null; // (only a proof of infeasibility drops a level)
        const sol = code === states.optimal ? solver.getSolution().colValue : null;
        if (sol === null) {
          broken = true;
          return undefined;
        }
        let value = base.const;
        for (let column = 0; column < columns; column += 1) {
          if (!Number.isFinite(sol[column])) {
            broken = true;
            return undefined;
          }
          value += c[column] * sol[column];
        }
        return value;
      } catch (error) {
        broken = true; // unbounded, numeric trouble: no bound, and the level is solved
        if (error instanceof SolverFault || error instanceof SolveError || (isRecord(highs.errors) && typeof highs.errors.HighsError === "function" && error instanceof highs.errors.HighsError)) return undefined;
        throw error;
      }
    },
    close() {
      if (solver !== null) solver.dispose();
      solver = null;
    },
  };
}
