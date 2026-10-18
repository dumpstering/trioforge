// Exact dominance pruning: drop the items that no optimal kit needs. A port of `prune`, `prune_report` and `fit_groups` in
// pipeline/trioforge/solver/prune.py (which states the rule and why it is exact, and is the truth), held to the pools that Python kept by
// tests-js/engine-prune.test.mjs.
//
//   prune(items, profile, tier, setup, buffset, options, owned) -> the kept items, sorted by (key, tier)
//   pruneReport(...)  -> {kept, dropped, hasteAssumed, compared, weightRule}: the same, with the reason each item went
//   fitGroups(item, setup, anyRule)  -> the Set of slot groups the builder gives the item a column in (whether it is eligible is not asked)
//   scoredDimensions(profile, setup) -> the names of the dimensions the objective can reward, and so the ones that are compared
//   hastePercent(profile, hastes, buffs)  -> the haste percent a weapon index assumes for items that carry the worn hastes `hastes` (path.js shares it)
//
// The arguments are those of Python's, in its order, and the builder's own: `items` and `profile` as `buildMilp` takes them (a list of items as
// `atTier` gives them; a profile as `assembleProfile` gives it, read with the evaluator's reader), `tier` a whole number (every item is at it) or null
// for a pool of many tiers (the pool of an Upgrade session), `setup` null, "1h-shield", "2h", "dw" or "stick", `buffset` null or `{set, table}`,
// `options` the builder's options (`any_rule`, `haste_assumed`, `owned_caps`, `new_keys`, `max_new`, `upgrades`, and `monk_bins` for a Monk whose
// weight is scored; the same checks as `buildMilp` makes), and `owned` the idents (`key@tier`) of owned items besides the keys of `owned_caps`. Pass
// it the same setup, buffset and options as the builder: the groups an item fits depend on the setup and on the Any rule, and the weapon index on the
// assumed haste. The input is not changed and the items that come back are the very objects that went in.
//
// The rule in short: an item B goes only if a kept, plain (non-Lore) item A fits every group B fits, is at least as good in every dimension that the
// objective scores (and no heavier, where a Monk's weight is scored), and is not a two-hander where B is not and B fits the primary hand. Of two
// equal items the smaller (key, tier) stays. With owned items: an owned item is never dropped, a candidate is dropped only by a candidate of its own
// tier or by an owned item with enough copies (a count of at least the places of its groups), and an item may not replace one that is less constrained
// than it is (free below new below an upgrade target).
//
// Not here: the test hooks `_MUTATION` and `_OWNED_MUTATION` of the Python module, which break one rule on purpose for Python's own tests.
// The Monk bonus is read from the bins of the bundle (`options.monk_bins`, through the evaluator's `monkTable`), where Python computes it; the bins hold
// the same numbers. Lookups of a name from the data go through a Map or a Set.

import { CONSTANTS, UNITS, monkTable, profileOf } from "./evaluate.js";
import { CLASS_CODES } from "./items.js";
import { ANY_RULES, allowedInHand, compareText, damageIndex, exact, readBuffset, readItem, readOptions } from "./model.js";
import { Rational, ZERO } from "./rational.js";

/** An input that is not what the pruning reads: the message says which. */
export class PruneError extends Error {
  constructor(message) {
    super(message);
    this.name = "PruneError";
  }
}

const fail = (message) => new PruneError(message);

// ---- the vocabulary, from the constants of the formulas ---------------------------------------------------------------------------------

const SLOT_GROUPS = CONSTANTS.slotGroups.map(([name, places]) => [name, Number(places.numerator)]);
const GROUPS = SLOT_GROUPS.map(([name]) => name);
const GROUP_SIZE = new Map(SLOT_GROUPS);
const ANY = "ANY";
const MODEL_SLOTS = new Set(GROUPS.filter((name) => name !== ANY));
const [PRIMARY, SECONDARY] = CONSTANTS.handPlaces;
const HANDS = [PRIMARY, SECONDARY];
const HAND_SET = new Set(HANDS);
const SETUP_SET = new Set(CONSTANTS.setups);
const SCHOOLS = CONSTANTS.schools;
const CLASS_SET = new Set(CLASS_CODES);
const RULE_ALL = ANY_RULES[0];
const HASTE = "HASTE";
const HASTE_INDEX = CONSTANTS.buffComponents.indexOf(HASTE);
const TENTHS_PER_STONE = Number(UNITS.tenthsPerStone.numerator);
/** The item stats (apart from armor class) that follow the stat rule, in the order dimensions are listed (`STAT_DIMS` in prune.py). */
const STAT_DIMS = [...CONSTANTS.attributes, "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG"];
/** What a dimension reads for an item that has no place for it, so that it never blocks a comparison it is not part of (`NO_PLACE` in prune.py). */
const NO_PLACE = -1_000_000_000;
/**
 * How constrained an item is, as the owned-item mode ranks it (`_Roles.rank` in prune.py): an owned item with enough copies, a free item (neither owned
 * nor new), a new one (a candidate: its wears use `max_new`) and an upgrade target (its first wear is made from a copy of its source, and every wear uses
 * `max_new`). An item may not replace one that is less constrained than it is.
 */
const RANK_ENOUGH = -1;
const RANK_FREE = 0;
const RANK_NEW = 1;
const RANK_TARGET = 2;
/** The longest text of the caller's that a message quotes. */
const SHOWN_CHARS = 40;
/** The weight rules: no heavier, or equal (`PruneReport.weight_rule` in prune.py). */
const WEIGHT_LE = "le";
const WEIGHT_EQ = "eq";
const WEIGHT_DIMENSION = "WEIGHT";

const smaller = (a, b) => (a.compare(b) <= 0 ? a : b);
const larger = (a, b) => (a.compare(b) >= 0 ? a : b);
const whole = (count) => new Rational(BigInt(count));
const isRecord = (value) => typeof value === "object" && value !== null && !Array.isArray(value);

/** A field of an object that the caller gave, if it is its own (never one that the prototype has). */
function own(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key) ? object[key] : undefined;
}

/** A name from the data, safe to put in a message. */
const show = (value) => (typeof value === "string" && value.length <= SHOWN_CHARS ? JSON.stringify(value) : typeof value);

function checkSetup(setup) {
  if (!SETUP_SET.has(setup)) throw fail(`unknown setup ${show(setup)} (use ${[...SETUP_SET].map((name) => JSON.stringify(name)).join(", ")})`);
}

// ---- the builder's view of the pool -------------------------------------------------------------------------------------------------------

/** The groups of a read item that the builder gives a column in (`fit_groups` in prune.py). */
function groupsOf(item, setup, anyRule) {
  const hands = setup ?? "stick";
  const fits = new Set();
  for (const group of GROUPS) {
    if (group === ANY) {
      if (item.slots.has(ANY) || (anyRule === RULE_ALL && [...item.slots].some((slot) => MODEL_SLOTS.has(slot)))) fits.add(group);
    } else if (item.slots.has(group) && (!HAND_SET.has(group) || allowedInHand(item, group, hands))) {
      fits.add(group);
    }
  }
  return fits;
}

/**
 * The slot groups `item` has a column in, as `buildMilp` makes them: a group the item lists (a hand only if the setup lets this item stand in it),
 * and the Any group for an item that lists it or, under the Any rule "all", for any item that has a slot. Whether the item is eligible (class,
 * deity) is not asked here. A Set of group names.
 */
export function fitGroups(item, setup, anyRule = RULE_ALL) {
  const hands = setup === undefined ? null : setup;
  checkSetup(hands);
  if (!ANY_RULES.includes(anyRule)) throw fail(`any_rule is one of ${ANY_RULES.join(", ")}, not ${show(anyRule)}`);
  return groupsOf(readItem(item, 0), hands, anyRule);
}

/** The dimensions the builder's terms read, from the weights and the pools of a compiled profile (`_scored` in prune.py), in a fixed order. */
function scoredOf(p, setup) {
  const on = (weight) => weight.sign() > 0;
  const weights = p.weights;
  const weapons = on(weights.DMG) && (setup ?? "stick") !== "stick";
  const names = new Set();
  if (on(weights.HP)) ["HP", "STA"].forEach((name) => names.add(name));
  if (on(weights.END)) ["END", "STR", "STA", "DEX", "AGI"].forEach((name) => names.add(name));
  if (on(weights.MANA) && p.pools.MANA.length > 0) {
    names.add("MANA");
    for (const pool of p.pools.MANA) names.add(pool.wis ? "WIS" : "INT");
  }
  if (on(weights.AC)) ["AC", "AGI"].forEach((name) => names.add(name));
  if (on(weights.ATK)) ["ATK", "STR"].forEach((name) => names.add(name));
  if (on(weights.DEX)) names.add("DEX");
  if (on(weights.CHA)) names.add("CHA");
  ["HPREG", "MANAREG", "ENDREG"].forEach((name, at) => {
    if (on(weights.regen[at])) names.add(name);
  });
  SCHOOLS.forEach((school, at) => {
    if (on(weights.schools[at])) names.add(`SV_${school}`);
  });
  if (on(weights.HASTE) || weapons) names.add(HASTE); // the assumed haste of the weapon term is the best haste of the pool
  if (weapons) names.add("DMG");
  const order = [...STAT_DIMS, "AC", HASTE, ...SCHOOLS.map((school) => `SV_${school}`), "DMG"];
  return order.filter((name) => names.has(name));
}

/**
 * The names of the dimensions the objective of `profile` can reward under `setup`, and so the ones that are compared: item stats (`STR` ... `ENDREG`),
 * `AC`, `HASTE`, `SV_<school>` and `DMG` (the weapon index). `HASTE` is also there when only the weapon term is on: the weapon index is taken at the
 * best haste of the pool. The Monk weight depends on the pool and is not in this list (see `weightRule` of the report).
 */
export function scoredDimensions(profile, setup = null) {
  checkSetup(setup);
  return scoredOf(profileOf(profile), setup);
}

/**
 * The spell haste of the profile as an exact number, null when it has none (`getattr(profile, "spell_haste", None)` in prune.py). A Profile requires
 * it to be at least 0 and at least the haste of the always-on buffs, so a profile that is not is refused here, as the builder refuses it.
 */
function spellHasteOf(profile, p) {
  const given = own(profile, "spell_haste");
  if (given === undefined || given === null) return null;
  const spell = exact(given, "profile.spell_haste");
  if (spell.sign() < 0 || spell.compare(p.buff[HASTE_INDEX]) < 0) {
    throw fail(`profile.spell_haste must be at least 0 and at least the haste of the always-on buffs, not ${spell.toString()}`);
  }
  return spell;
}

/**
 * The haste percent a weapon index assumes for items that carry the worn hastes `hastes` (`_assumed_haste` in prune.py, and the same formula in the
 * builder and in `session_haste` of upgrade.py): the profile's own spell haste, else the best spell haste on offer (the always-on buffs' and the best
 * optional buff's), plus the best worn haste (a slowing item counts for nothing), up to the cap. `buffs` is the buff set as `readBuffset` reads it
 * (or null).
 */
export function hastePercent(profile, hastes, buffs) {
  const p = profileOf(profile);
  let spell = spellHasteOf(profile, p);
  if (spell === null) {
    spell = p.buff[HASTE_INDEX];
    for (const buff of buffs === null ? [] : buffs.optional) spell = larger(spell, buff.haste);
  }
  let worn = ZERO;
  for (const haste of hastes) if (haste > 0) worn = larger(worn, whole(haste));
  return Number(smaller(p.hasteCap, larger(spell, ZERO).add(worn)).floor());
}

/** The haste percent the weapon index assumes in a pruning: the options' value, or the one `hastePercent` gives for the pool. */
function assumedHaste(profile, placed, buffs, options) {
  if (options.hasteAssumed !== null) return options.hasteAssumed;
  return hastePercent(profile, placed.map(({ item }) => item.haste), buffs);
}

/**
 * How the worn weight is compared (`_weight_rule` in prune.py): null, "le" (no heavier) or "eq" (equal). It only moves the Monk bonus, so it matters
 * for a Monk trio whose armor class is scored, and when the bonus differs within the weights the pool can reach (the builder's own range).
 */
function weightRuleOf(p, scored, placed, monkBins) {
  if (p.monk === null || !scored.includes("AC")) return null;
  let top = 0; // the heaviest kit the pool can build, by group
  for (const group of GROUPS) {
    const size = GROUP_SIZE.get(group);
    let take = size;
    const here = placed.filter(({ fits }) => fits.has(group)).map(({ item }) => [item.weight10, item.lore ? 1 : size]);
    here.sort((a, b) => b[0] - a[0] || b[1] - a[1]);
    for (const [weight, copies] of here) {
      if (take <= 0 || weight <= 0) break;
      const count = Math.min(copies, take);
      top += weight * count;
      take -= count;
    }
  }
  const table = monkTable(p, monkBins, "options.monk_bins");
  // the bonus of every whole stone up to the heaviest kit; the last bin of the table is the bonus of every weight beyond it, which adds no new value
  const stones = Math.min(Math.floor(top / TENTHS_PER_STONE), table.length - 1);
  const bonus = [];
  for (let stone = 0; stone <= stones; stone += 1) bonus.push(table[stone]);
  if (new Set(bonus).size === 1) return null; // every weight the pool can reach gets the same bonus: the weight is worth nothing
  return bonus.every((value, at) => at === 0 || bonus[at - 1] >= value) ? WEIGHT_LE : WEIGHT_EQ;
}

/** The dense ranks of exact values (null, an item with no place in the hand, below all of them). */
function ranksOf(values) {
  const distinct = [];
  const seen = new Set();
  for (const value of values) {
    if (value !== null && !seen.has(value.toString())) {
      seen.add(value.toString());
      distinct.push(value);
    }
  }
  distinct.sort((a, b) => a.compare(b));
  const rank = new Map(distinct.map((value, at) => [value.toString(), at]));
  return values.map((value) => (value === null ? -1 : rank.get(value.toString())));
}

/** One row per item: a vector in which "A can replace B" is "every entry of A is at least that of B" (`_matrix` in prune.py). */
function matrixOf(placed, p, setup, scored, weightRule, hasteAssumed) {
  const columns = [];
  const column = (values) => columns.push(values);
  for (const group of GROUPS) column(placed.map(({ fits }) => (fits.has(group) ? 1 : 0)));
  const scoredSet = new Set(scored);
  for (const name of STAT_DIMS) if (scoredSet.has(name)) column(placed.map(({ item }) => item.stats.get(name) ?? 0));
  if (scoredSet.has(HASTE)) column(placed.map(({ item }) => Math.max(item.haste, 0))); // a slowing item counts for nothing
  for (const school of SCHOOLS) if (scoredSet.has(`SV_${school}`)) column(placed.map(({ item }) => item.sv.get(school) ?? 0));
  if (scoredSet.has("AC")) {
    // armor class counts one way in the primary hand, the Any group and every armor place (worn) and another way for a shield in the secondary hand
    const armor = placed.map(({ item }) => item.stats.get("AC") ?? 0);
    const main = placed.map(({ fits }) => [...fits].some((group) => group !== SECONDARY));
    const second = placed.map(({ fits }) => fits.has(SECONDARY));
    const shield = placed.map(({ item }) => item.isShield);
    column(armor.map((value, at) => (main[at] ? value : NO_PLACE)));
    column(armor.map((value, at) => (second[at] ? (shield[at] ? 0 : value) : NO_PLACE)));
    column(armor.map((value, at) => (second[at] ? (shield[at] ? value : 0) : NO_PLACE)));
  }
  if (scoredSet.has("DMG")) {
    for (const hand of HANDS) {
      const index = placed.map(({ item, fits }) => (fits.has(hand) ? damageIndex(item, hand, setup ?? "stick", hasteAssumed, p.dwFactor) : null));
      column(ranksOf(index));
    }
  }
  if (weightRule !== null) {
    column(placed.map(({ item }) => -item.weight10));
    if (weightRule === WEIGHT_EQ) column(placed.map(({ item }) => item.weight10));
  }
  return placed.map((_, at) => Float64Array.from(columns, (values) => values[at]));
}

// ---- the sweep -----------------------------------------------------------------------------------------------------------------------------

/**
 * What the owned-item mode knows about each position of the pool (`_Roles` in prune.py). `protectedAt`: owned, never dropped. `dominatesAny`: owned with
 * enough copies, may replace a candidate of any tier. `dominatesSame`: may replace a candidate of its own tier whose `rank` is at least its own. `tiers` and
 * `rank` (-1 an owned item with enough copies, 0 free, 1 new, 2 upgrade target) are the numbers those two clauses compare.
 */
function rolesOf(pool, options, protectedIdents) {
  const caps = options.ownedCaps;
  const ups = options.upgrades;
  const news = new Set([...options.newKeys, ...ups.keys()]); // an upgrade is a new wear whether or not it is listed
  if (protectedIdents.size === 0 && news.size === 0) return null; // the plain rule, unchanged
  const protectedAt = pool.map(({ item }) => protectedIdents.has(item.ident));
  const target = pool.map(({ item }) => ups.has(item.ident));
  const fresh = pool.map(({ item }) => news.has(item.ident));
  const count = pool.map(({ item }) => (caps.has(item.ident) ? caps.get(item.ident) : 1)); // an owned item without a count has one copy
  const places = pool.map(({ fits }) => [...fits].reduce((sum, group) => sum + GROUP_SIZE.get(group), 0));
  const enough = pool.map(({ item }, at) => protectedAt[at] && !item.lore && count[at] >= places[at]);
  const duplicate = pool.map((_, at) => protectedAt[at] && fresh[at] && count[at] >= 1);
  const rank = pool.map((_, at) => (target[at] ? RANK_TARGET : enough[at] ? RANK_ENOUGH : fresh[at] ? RANK_NEW : RANK_FREE));
  const dominatesSame = pool.map((_, at) => (!protectedAt[at] || duplicate[at]) && !target[at]);
  return { protectedAt, dominatesAny: enough, dominatesSame, tiers: pool.map(({ item }) => item.tier), rank };
}

/** Whether every entry of `a` is at least that of `b`. */
function atLeast(a, b) {
  for (let at = 0; at < a.length; at += 1) if (a[at] < b[at]) return false;
  return true;
}

/**
 * The positions kept and, for each dropped one, the position of a kept item that replaces it (`_sweep` in prune.py). A can replace B when A is plain, A's
 * row is at least B's everywhere, and A is not a two-hander where B (which fits the primary hand) is not. Of the items that can replace each other, the
 * smaller (key, tier) stays. A row that dominates another has the larger sum, and rows with equal sums that dominate each other are equal, so the items
 * sorted by (sum descending, plain before Lore, the two-hander-on-the-primary-hand ones last, key) come after every item that can replace them: one pass
 * against the kept plain items finds the maximal ones. `roles` (the owned-item mode) adds to "can replace": see the module comment.
 */
function sweep(pool, rows, roles) {
  const n = pool.length;
  const items = pool.map(({ item }) => item);
  const lore = items.map((item) => item.lore);
  const twoHanded = items.map((item) => item.weapon !== null && item.weapon.twoHanded);
  const primary = pool.map(({ fits }) => fits.has(PRIMARY));
  const blocks = twoHanded.map((flag, at) => flag && primary[at]);
  const score = rows.map((row) => row.reduce((sum, value) => sum + value, 0));
  const { protectedAt, dominatesAny, dominatesSame, tiers, rank } = roles ?? {
    protectedAt: new Array(n).fill(false),
    dominatesAny: new Array(n).fill(false),
    dominatesSame: new Array(n).fill(true),
    tiers: items.map((item) => item.tier),
    rank: new Array(n).fill(RANK_FREE),
  };
  const order = Array.from({ length: n }, (_, at) => at).sort(
    (a, b) =>
      score[b] - score[a] ||
      Number(lore[a]) - Number(lore[b]) ||
      Number(blocks[a]) - Number(blocks[b]) ||
      rank[a] - rank[b] ||
      Number(!protectedAt[a]) - Number(!protectedAt[b]) ||
      compareText(items[a].key, items[b].key) ||
      items[a].tier - items[b].tier,
  );
  const plain = []; // the kept plain items that may replace others, in the order they were kept
  const kept = [];
  const replacedBy = new Map();
  for (const at of order) {
    if (plain.length > 0 && !protectedAt[at]) {
      const blocked = primary[at] && !twoHanded[at];
      const hit = plain.find(
        (other) =>
          !(blocked && twoHanded[other]) && (dominatesAny[other] || (tiers[other] === tiers[at] && rank[other] <= rank[at])) && atLeast(rows[other], rows[at]),
      );
      if (hit !== undefined) {
        replacedBy.set(at, hit);
        continue;
      }
    }
    kept.push(at);
    if (!lore[at] && (dominatesAny[at] || dominatesSame[at])) plain.push(at);
  }
  return { kept, replacedBy };
}

// ---- the entry points -----------------------------------------------------------------------------------------------------------------------

/** The idents that are never dropped: `owned` and the keys of `options.owned_caps` (`_owned_idents` in prune.py). */
function ownedIdents(owned, options) {
  if (typeof owned === "string" || owned === null || typeof owned !== "object" || typeof owned[Symbol.iterator] !== "function") {
    throw fail(`owned is a set of idents (key@tier), not ${show(owned)}`);
  }
  const names = new Set();
  for (const name of owned) {
    if (typeof name !== "string") throw fail(`owned names idents (key@tier), not ${show(name)}`);
    names.add(name);
  }
  for (const name of options.ownedCaps.keys()) names.add(name);
  return names;
}

/**
 * `prune` with the reasons: `{kept, dropped, hasteAssumed, compared, weightRule}`. `kept` are the surviving items, sorted by (key, tier). `dropped` maps the
 * ident of every dropped item to `[reason, by]`: "class" (no class of the trio can wear it), "deity" (locked to a deity the profile does not admit) or
 * "race" (its races exclude the race of the profile), "no-slot" (it fits no group under this setup), with `by` null, or "dominated" with `by` the ident of a
 * kept item that replaces it. `hasteAssumed` is the haste the weapon index was taken at, `compared` the names of the dimensions compared ("WEIGHT" among
 * them when the Monk weight is) and `weightRule` null (weight not compared), "le" (no heavier) or "eq" (equal weight).
 *
 * A PruneError for an unknown setup, a tier that is not a whole number or null, an item that is not at a tier given as a whole number, an item twice
 * in the pool, a hole in the list of items or of owned idents and a negative pool factor; a ModelError for an item, a buff set or an option that the
 * builder would refuse; an EvaluateError for a profile the evaluator would not read.
 */
export function pruneReport(items, profile, tier, setup, buffset = null, options = null, owned = []) {
  const hands = setup === undefined ? null : setup;
  checkSetup(hands);
  if (!Array.isArray(items)) throw fail("the items are a list of the pool");
  if (!isRecord(profile)) throw fail("the profile is what assembleProfile gives, an object");
  if (tier !== null && !Number.isInteger(tier)) throw fail(`the tier is a whole number, or null for a pool of many tiers, not ${show(tier)}`);
  const opts = readOptions(options);
  const protectedIdents = ownedIdents(owned, opts);
  const p = profileOf(profile);
  for (const family of [p.pools.HP, p.pools.MANA, p.pools.END]) {
    for (const pool of family) {
      if (pool.fac.sign() < 0) throw fail(`the pool factor of ${show(pool.cls)} is negative (${pool.fac.toString()}); the objective is not monotone`);
    }
  }
  const buffs = readBuffset(buffset);
  const trio = new Set(p.pools.HP.map((pool) => pool.cls)); // one HP pool per class
  const byClass = [...trio].every((code) => CLASS_SET.has(code));
  const deity = own(profile, "deity") ?? null;
  const race = own(profile, "race") ?? null; // an evaluator profile has none: no item is left out for its race

  const dropped = new Map();
  const eligible = [];
  const strangers = []; // owned items the builder gives no column: in the result all the same
  const seen = new Set();
  for (let at = 0; at < items.length; at += 1) {
    if (!(at in items)) throw fail(`items[${at}] is a hole in the list`); // `forEach` and `map` would step over it
    const raw = items[at];
    const item = readItem(raw, at);
    if (tier !== null && item.tier !== tier) throw fail(`item ${show(item.key)} is at tier ${item.tier}, but the pool is at tier ${tier}`);
    if (seen.has(item.ident)) throw fail(`item ${show(item.key)} (tier ${item.tier}) is in the pool twice`);
    seen.add(item.ident);
    let reason = null;
    if (byClass && ![...item.classes].some((code) => trio.has(code))) reason = "class";
    else if (item.deity !== null && (deity === null || !item.deity.has(deity))) reason = "deity";
    else if (race !== null && item.races !== null && !item.races.has(race)) reason = "race";
    if (reason === null) eligible.push({ raw, item });
    else if (protectedIdents.has(item.ident)) strangers.push(raw);
    else dropped.set(item.ident, [reason, null]);
  }

  const placed = [];
  for (const { raw, item } of eligible) {
    const fits = groupsOf(item, hands, opts.anyRule);
    if (fits.size > 0) placed.push({ raw, item, fits });
    else if (protectedIdents.has(item.ident)) strangers.push(raw);
    else dropped.set(item.ident, ["no-slot", null]);
  }
  const hasteAssumed = assumedHaste(profile, placed, buffs, opts);
  const scored = scoredOf(p, hands);
  const weightRule = weightRuleOf(p, scored, placed, opts.monkBins);
  const rows = matrixOf(placed, p, hands, scored, weightRule, hasteAssumed);
  const roles = rolesOf(placed, opts, protectedIdents);
  const { kept, replacedBy } = sweep(placed, rows, roles);
  for (const [at, by] of replacedBy) dropped.set(placed[at].item.ident, ["dominated", placed[by].item.ident]);
  const survivors = [...kept.map((at) => placed[at].raw), ...strangers];
  survivors.sort((a, b) => compareText(a.key, b.key) || a.tier - b.tier);
  return {
    kept: survivors,
    dropped,
    hasteAssumed,
    compared: weightRule === null ? scored : [...scored, WEIGHT_DIMENSION],
    weightRule,
  };
}

/**
 * The pool without the items that a kept plain item can replace (see the head of this file and prune.py), sorted by (key, tier). The arguments are
 * those of `pruneReport`, and the errors too. The items that come back are the objects that went in.
 */
export function prune(items, profile, tier, setup, buffset = null, options = null, owned = []) {
  return pruneReport(items, profile, tier, setup, buffset, options, owned).kept;
}
