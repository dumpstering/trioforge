// The MILP builder: the best kit by the absolute value F, as a mixed-integer program. A port of `build_milp` in pipeline/trioforge/solver/model.py
// (which describes the model in full: the columns, the setups, the curves, the best two pools, the sheet armor class, the haste, the owned
// items), held to the models Python wrote by tests-js/engine-model.test.mjs and compared with milpjson.js.
//
//   buildMilp(profile, items, setup, buffset, options) -> the model JSON v1 document: {version, sense, const, col_names, col_lb, col_ub,
//       integrality, c, row_names, row_lb, row_ub, A: {start, index, value}, item_cols, buff_cols, info}
//
// The program is `maximize const + c . x` over `row_lb <= A x <= row_ub` and `col_lb <= x <= col_ub`, the columns of `integrality` 1 whole; an
// infinite bound is null; `A` is in compressed row form with the column indices rising within a row. The document is what milp_json.to_dict
// writes, frozen all through, and the worker takes it as it is.
//
//   profile   what `assembleProfile` gives, or the profile of a fixture: Profile.to_dict(). It is read with the evaluator's reader (evaluate.js),
//             as Python's builder reads it with `compile_profile`; `deity`, `race` and `spell_haste` are read from it as they are, except that a
//             `spell_haste` below 0 or below the haste of the always-on buffs is refused (a Profile cannot have one).
//   items     a list of the pool: each item as `atTier` gives it (`key`, `tier`, `slots`, `classes`, `deity`, `races`, `lore`, `stats`, `sv`,
//             `haste`, `weight10`, `weapon`, `is_shield`). An item for another class than the trio's, locked to a deity the profile does not
//             have, or for another race than the profile's gets no column.
//   setup     null, "1h-shield", "2h", "dw", "stick" or "ranged" (see weapons.py: which items stand in the hands and the range place, and which of them scores damage).
//   buffset   null (no buffs), or `{set, table}` as the bundle writes them: `bundle.buffs[key].set` and `bundle.buff_table`. A buff is named once in
//             its list and in one list only (a repeat would be two columns of one name), a conflict is `[a, b]` or `[a, b, reasons]` (the bundle
//             writes the reasons, a list of texts, which are not read), and a conflict or a clique names optional buffs only (as Python's builder).
//   options   `any_rule` ("all", the default, or "explicit"), `haste_assumed` (a whole number of at least 0 or null: the haste percent the weapon
//             index assumes; null takes the spell haste on offer plus the best worn haste of the pool, up to the cap), and the owned-item options
//             `owned_caps` ({ident: count}), `new_keys` (a list of idents), `max_new` and `upgrades` ({target ident: source ident}), where an
//             ident is `key@tier`. These are the fields of BuildOptions in model.py, by the same names (they are the options of a fixture's solve).
//             The one option that Python's builder does not have is `monk_bins`, the `monk_bins` block of the bundle: Python computes the bonus of
//             a worn weight in floating point, and the browser reads it from the bins, as the evaluator does (it is needed only when the profile
//             has a Monk curve and the armor class has a weight). The legacy objective and the mutations of the Python builder are not here.
//
// Exactness. The builder is exact: every coefficient, bound and decision is a Rational (rational.js), as Python's is a Fraction, and a number is
// rounded to a double once, when the document is written, to the nearest double with ties to even, which is what Python's float(Fraction) gives.
// So the document is the very one that Python makes, not one within a tolerance. What is decided on the way is decided on exact numbers: which
// two pools count, whether a curve has a kink inside the range, whether a cap can bind, the bins of the Monk bonus.
//
// The constants are not here: the rules of the formulas are CONSTANTS and UNITS of evaluate.js (which a test holds to the bundle), the
// tier limit is MAX_TIER of tiers.js, and the source of this file holds no number but 0 and 1 (tests-js/engine-literals.test.mjs scans it).
// Lookups of a name from the data go through a Map or a Set. A list that is given is read whole: a hole in one is a ModelError.

import { BOW_SKILL, CONSTANTS, DEFAULT_LEVEL, RANGE_GROUP, RANGED_SKILL, UNITS, fallbackBonus, monkTable, profileOf } from "./evaluate.js";
import { CLASS_CODES } from "./items.js";
import { PER_MINUTE_TO_INDEX, ProcTable } from "./procs.js";
import { LIMITS, isPlainObject as isPlain } from "./protocol.js";
import { ONE, Rational, ZERO } from "./rational.js";
import { MAX_TIER } from "./tiers.js";

/** An input of the builder that is not what it reads: the message says which. */
export class ModelError extends Error {
  constructor(message) {
    super(message);
    this.name = "ModelError";
  }
}

/** What is said to a visitor whose items have no bow that the bow setup can use. */
export const NO_BOW = "Add a bow to your list, or switch build";

/**
 * The bow setup puts a bow in the range place whatever it is worth (the row `range.bow`), so a pool with no bow that fits the range place (and that the profile can use: its class, race and
 * deity) has no model. It is a refusal of the request's items, typed so that the worker says bad-request and goes on, where a bare error is an internal fault that replaces the worker.
 */
export class NoBowError extends ModelError {
  constructor(message = NO_BOW) {
    super(message);
    this.name = "NoBowError";
  }
}

const fail = (message) => new ModelError(message);

// ---- the vocabulary, from the constants of the formulas -------------------------------------------------------------------------------

const ATTRIBUTES = CONSTANTS.attributes;
const SCHOOLS = CONSTANTS.schools;
const SCHOOL_SET = new Set(SCHOOLS);
const ITEM_STATS = new Set(CONSTANTS.itemStats);
const COMPONENTS = CONSTANTS.buffComponents;
const COMPONENT_INDEX = new Map(COMPONENTS.map((name, index) => [name, index]));
const HASTE = "HASTE";
const SETUP_SET = new Set(CONSTANTS.setups);
const SLOT_GROUPS = CONSTANTS.slotGroups.map(([name, places]) => [name, Number(places.numerator)]);
const GROUP_SIZE = new Map(SLOT_GROUPS);
const ANY = "ANY";
const MODEL_SLOTS = new Set(SLOT_GROUPS.map(([name]) => name).filter((name) => name !== ANY));
const [PRIMARY, SECONDARY] = CONSTANTS.handPlaces;
/** The groups the weapons rules are asked about: the two hands, and the range place (a bow stands there in the bow setup). */
const WEAPON_GROUPS = new Set([PRIMARY, SECONDARY, RANGE_GROUP]);
const HAND_NAMES = [PRIMARY, SECONDARY];
/** What the gear can give by name (the attributes, the flat points and the regens), and the quantities that have a name of their own. */
const FLATS = ["HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG"];
const GEAR_KEYS = new Set([...ATTRIBUTES, ...FLATS]);
const CORRUPTION = "CORRUPTION";
const RESIST_PREFIX = "SV_";
const STAT_CAP = CONSTANTS.statCap;
const CLASS_SET = new Set(CLASS_CODES);
export const ANY_RULES = ["all", "explicit"];
const RULE_ALL = ANY_RULES[0];
const TIER_TEXT = new Map(Array.from({ length: MAX_TIER + 1 }, (_, tier) => [String(tier), tier]));
const OPTION_KEYS = ["any_rule", "haste_assumed", "haste_floor", "haste_exact", "owned_caps", "new_keys", "max_new", "upgrades", "monk_bins", "procs"];
const BINARY_KINDS = ["ordering", "deficit", "selection", "monk", "haste", "buff", "made"];
const SAFE_CHARS = new Set([..."abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.@|+ "]);
const LABEL_SIGNS = new Set([..."[],#"]);
/** The fields of a conflict as the bundle writes it: the two buffs, and why they exclude each other (a list of texts that nothing reads). */
const CONFLICT_FIELDS = ["a", "b", "reasons"];

// ---- small helpers -----------------------------------------------------------------------------------------------------------------------

const smaller = (a, b) => (a.compare(b) <= 0 ? a : b);
const larger = (a, b) => (a.compare(b) >= 0 ? a : b);
/** A whole number (a safe integer) as a Rational. */
const whole = (count) => new Rational(BigInt(count));
const isRecord = (value) => typeof value === "object" && value !== null && !Array.isArray(value);

/** A field of an object that the caller gave, if it is its own (never one that the prototype has). */
function own(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key) ? object[key] : undefined;
}

/** A name from the data, safe to put in a message: short, and only letters, digits and a few signs. */
function safe(name) {
  if (typeof name !== "string" || name.length === 0 || name.length > LIMITS.maxStringLength) return "?";
  for (const character of name) if (!SAFE_CHARS.has(character)) return "?";
  return name;
}

/** The name of a column or a row as a message can show it: the builder's own signs ([ ] , #) kept, any other sign that is not safe shown as ?. */
function labelOf(name) {
  const text = name.length > LIMITS.maxStringLength ? name.slice(0, LIMITS.maxStringLength) : name;
  return Array.from(text, (character) => (SAFE_CHARS.has(character) || LABEL_SIGNS.has(character) ? character : "?")).join("");
}

/** A value from the caller, as a message can show it. */
function show(value) {
  if (typeof value === "string") return value.length > LIMITS.maxStringLength ? "(a long text)" : JSON.stringify(value);
  if (typeof value === "number" || typeof value === "boolean" || value === null || value === undefined) return String(value);
  return Array.isArray(value) ? "a list" : typeof value;
}

/** The own entries of a plain object, each read once; an accessor or a symbol is not plain data. */
function entriesOf(object, where) {
  if (!isPlain(object)) throw fail(`${where} must be an object`);
  const entries = [];
  for (const key of Reflect.ownKeys(object)) {
    if (typeof key !== "string") throw fail(`${where} has a symbol for a key`);
    const descriptor = Object.getOwnPropertyDescriptor(object, key);
    if (descriptor === undefined || !("value" in descriptor) || descriptor.enumerable !== true) throw fail(`${where} has a property (${safe(key)}) that is not plain data`);
    entries.push([key, descriptor.value]);
  }
  return entries;
}

/** A list (the caller has checked that it is one) with no hole in it: `map` and `forEach` step over a hole. */
function noHoles(list, where) {
  for (let index = 0; index < list.length; index += 1) {
    if (!(index in list)) throw fail(`${where}[${index}] is a hole in the list`);
  }
  return list;
}

/** A JSON number as the exact value Python holds it as: a whole number, or the decimal a double prints as. */
export function exact(value, where) {
  if (typeof value !== "number" || !Number.isFinite(value)) throw fail(`${where} must be a number`);
  if (Number.isInteger(value)) {
    if (!Number.isSafeInteger(value)) throw fail(`${where} is a whole number past 2^53 - 1, which a double does not hold exactly`);
    return whole(value);
  }
  return Rational.fromNumber(value);
}

/** A whole number of at least 0 (a count, a limit, a haste). */
const isCount = (value) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;

/**
 * Text in the order of Python's `sorted` for strings: by code point, not by UTF-16 code unit (the two differ for a character beyond the Basic
 * Multilingual Plane against one of the last 8,192 of it). The order of the columns depends on it.
 */
export function compareText(a, b) {
  if (a === b) return 0;
  const left = Array.from(a);
  const right = Array.from(b);
  const shared = Math.min(left.length, right.length);
  for (let at = 0; at < shared; at += 1) {
    if (left[at] !== right[at]) return left[at].codePointAt(0) < right[at].codePointAt(0) ? -1 : 1;
  }
  return left.length < right.length ? -1 : left.length > right.length ? 1 : 0;
}

/** The text of a Rational as Python's str(Fraction) writes it: "25" for a whole number, "5/2" otherwise. */
const fractionText = (value) => (value.isInteger() ? String(value.numerator) : value.toString());

const SAFE = BigInt(Number.MAX_SAFE_INTEGER);

/** The nearest double (ties to even), and never -0: the number the document holds. */
function real(value) {
  const { numerator, denominator } = value;
  if (denominator === 1n && numerator <= SAFE && numerator >= -SAFE) return Number(numerator) + 0;
  return value.toNumber() + 0;
}

/** A document that nothing can change, all through. */
function deepFreeze(root) {
  const stack = [root];
  while (stack.length > 0) {
    const node = stack.pop();
    if (node === null || typeof node !== "object" || Object.isFrozen(node)) continue;
    Object.freeze(node);
    for (const child of Array.isArray(node) ? node : Object.values(node)) stack.push(child);
  }
  return root;
}

/** The ident of an item in the owned-item options: `key@tier` (a catalog key has no `@`). */
export function ident(key, tier) {
  return `${key}@${tier}`;
}

/** The key and the tier of an ident: `key@tier` with a key that has no `@` and a tier from 0 to MAX_TIER. */
function parseIdent(name, what) {
  const at = typeof name === "string" ? name.indexOf("@") : -1;
  const tier = at > 0 ? TIER_TEXT.get(name.slice(at + 1)) : undefined;
  if (tier === undefined) throw fail(`${what}: ${show(name)} is not an item ident (key@tier, with a tier from 0 to ${MAX_TIER})`);
  return { key: name.slice(0, at), tier };
}

// ---- the options -------------------------------------------------------------------------------------------------------------------------

/** The options of a build, read and checked as `BuildOptions.__post_init__` checks them: sorted maps of idents, never a list with a hole. */
export function readOptions(raw) {
  const given = new Map(raw === undefined || raw === null ? [] : entriesOf(raw, "the options"));
  for (const key of given.keys()) {
    if (!OPTION_KEYS.includes(key)) throw fail(`the options have an option (${safe(key)}) that buildMilp does not read (it reads ${OPTION_KEYS.join(", ")})`);
  }

  const anyRule = given.has("any_rule") ? given.get("any_rule") : RULE_ALL;
  if (!ANY_RULES.includes(anyRule)) throw fail(`any_rule is one of ${ANY_RULES.join(", ")}, not ${show(anyRule)}`);

  const hasteAssumed = given.get("haste_assumed") ?? null;
  if (hasteAssumed !== null && !isCount(hasteAssumed)) throw fail(`haste_assumed is a whole number of at least 0, not ${show(hasteAssumed)}`);
  const hasteFloor = given.get("haste_floor") ?? null;
  if (hasteFloor !== null && !isCount(hasteFloor)) throw fail(`haste_floor is null or a whole number of at least 0, not ${show(hasteFloor)}`);

  if (hasteFloor !== null && hasteAssumed === null) throw fail("haste_floor needs haste_assumed: a level program pays the weapon term at its own level");
  const hasteExact = given.get("haste_exact") ?? false;
  if (typeof hasteExact !== "boolean") throw fail(`haste_exact is true or false, not ${show(hasteExact)}`);
  if (hasteExact && hasteFloor === null) throw fail("haste_exact needs haste_floor: it makes the kit count exactly that haste");

  const caps = new Map();
  const capsGiven = given.get("owned_caps");
  if (capsGiven !== undefined && capsGiven !== null) {
    for (const [name, count] of entriesOf(capsGiven, "owned_caps")) {
      parseIdent(name, "owned_caps");
      if (!isCount(count)) throw fail(`owned_caps: the count of ${safe(name)} is a whole number of at least 0, not ${show(count)}`);
      caps.set(name, count);
    }
  }
  const ownedCaps = new Map([...caps].sort((a, b) => compareText(a[0], b[0])));

  const newGiven = given.get("new_keys");
  let newKeys = new Set();
  if (newGiven !== undefined && newGiven !== null) {
    if (!(Array.isArray(newGiven) || newGiven instanceof Set)) throw fail(`new_keys is a list of idents, not ${show(newGiven)}`);
    const names = Array.isArray(newGiven) ? noHoles(newGiven, "new_keys") : [...newGiven];
    for (const name of names) parseIdent(name, "new_keys");
    newKeys = new Set(names);
  }

  const maxNew = given.get("max_new") ?? null;
  if (maxNew !== null && !isCount(maxNew)) throw fail(`max_new is null or a whole number of at least 0, not ${show(maxNew)}`);

  const ups = new Map();
  const upsGiven = given.get("upgrades");
  if (upsGiven !== undefined && upsGiven !== null) {
    for (const [target, source] of entriesOf(upsGiven, "upgrades")) {
      const to = parseIdent(target, "upgrades");
      const from = parseIdent(source, "upgrades");
      if (to.key !== from.key || to.tier <= from.tier) throw fail(`upgrades: ${safe(target)} is not the same key as ${safe(source)} at a higher tier`);
      if (caps.has(target)) throw fail(`upgrades: the target ${safe(target)} is owned; an upgrade makes an item the visitor lacks`);
      if ((caps.get(source) ?? 0) < 1) throw fail(`upgrades: the source ${safe(source)} is not owned (it needs a count of at least 1)`);
      ups.set(target, source);
    }
  }
  const upgrades = new Map([...ups].sort((a, b) => compareText(a[0], b[0])));
  const procs = given.get("procs") ?? null;
  if (procs !== null && !(procs instanceof ProcTable)) throw fail("procs is the table of procs of the trio (readProcs of engine/procs.js), or null");
  return { anyRule, hasteAssumed, hasteFloor, hasteExact, ownedCaps, newKeys, maxNew, upgrades, monkBins: given.get("monk_bins"), procs };
}

// ---- the items ---------------------------------------------------------------------------------------------------------------------------

/** A table of whole numbers by name (an item's stats or resists), as a Map. */
function amounts(table, where) {
  if (table === undefined || table === null) return new Map();
  const found = new Map();
  for (const [name, value] of entriesOf(table, where)) {
    if (typeof value !== "number" || !Number.isSafeInteger(value)) throw fail(`${where}: ${safe(name)} must be a whole number`);
    found.set(name, value);
  }
  return found;
}

/** A list of texts (the slots, the classes, the deities, the races) as a Set. */
function textSet(list, where) {
  if (!Array.isArray(list)) throw fail(`${where} must be a list`);
  noHoles(list, where);
  for (const entry of list) if (typeof entry !== "string") throw fail(`${where} must be a list of texts`);
  return new Set(list);
}

/** An item of the pool, checked and read into the form the builder works with. */
export function readItem(raw, at) {
  const where = `items[${at}]`;
  if (!isPlain(raw)) throw fail(`${where} must be an item, an object such as atTier gives`);
  const key = own(raw, "key");
  if (typeof key !== "string" || key.length === 0) throw fail(`${where} must have a key`);
  const label = `item ${safe(key)}`;
  const tier = own(raw, "tier");
  if (!Number.isInteger(tier) || tier < 0 || tier > MAX_TIER) throw fail(`${label}: the tier must be a whole number from 0 to ${MAX_TIER}`);
  const stats = amounts(own(raw, "stats"), `${label}: stats`);
  for (const stat of stats.keys()) if (!ITEM_STATS.has(stat)) throw fail(`${label}: unknown stat ${safe(stat)}`);
  const sv = amounts(own(raw, "sv"), `${label}: sv`);
  for (const school of sv.keys()) if (!SCHOOL_SET.has(school) && school !== CORRUPTION) throw fail(`${label}: unknown resist ${safe(school)}`);
  const haste = own(raw, "haste");
  const weight10 = own(raw, "weight10");
  if (!Number.isSafeInteger(haste)) throw fail(`${label}: haste must be a whole number`);
  if (!Number.isSafeInteger(weight10)) throw fail(`${label}: weight10 must be a whole number`);
  if (typeof own(raw, "lore") !== "boolean") throw fail(`${label}: lore must be true or false`);
  if (typeof own(raw, "is_shield") !== "boolean") throw fail(`${label}: is_shield must be true or false`);
  const deity = own(raw, "deity");
  const races = own(raw, "races");
  let weapon = null;
  const weaponGiven = own(raw, "weapon");
  if (weaponGiven !== undefined && weaponGiven !== null) {
    if (!isPlain(weaponGiven)) throw fail(`${label}: weapon must be null or an object`);
    const dmg = own(weaponGiven, "dmg");
    const delay = own(weaponGiven, "delay");
    const bonus = own(weaponGiven, "bonus") ?? null;
    if (!Number.isSafeInteger(dmg) || !Number.isSafeInteger(delay)) throw fail(`${label}: the weapon's dmg and delay must be whole numbers`);
    if (bonus !== null && !Number.isSafeInteger(bonus)) throw fail(`${label}: the weapon's bonus must be null or a whole number`);
    if (typeof own(weaponGiven, "two_handed") !== "boolean") throw fail(`${label}: the weapon's two_handed must be true or false`);
    const skill = own(weaponGiven, "skill");
    weapon = { dmg, delay, bonus, twoHanded: own(weaponGiven, "two_handed"), skill: typeof skill === "string" ? skill : null };
  }
  return {
    key,
    tier,
    ident: ident(key, tier),
    stats,
    sv,
    slots: textSet(own(raw, "slots"), `${label}: slots`),
    classes: textSet(own(raw, "classes"), `${label}: classes`),
    deity: deity === undefined || deity === null ? null : textSet(deity, `${label}: deity`),
    races: races === undefined || races === null ? null : textSet(races, `${label}: races`),
    lore: own(raw, "lore"),
    haste,
    weight10,
    weapon,
    isShield: own(raw, "is_shield"),
  };
}

/** Whether the item is a weapon (a damage and a delay above 0). */
const isWeapon = (item) => item.weapon !== null && item.weapon.dmg > 0 && item.weapon.delay > 0;

/** Whether the item is a bow (`is_bow` in weapons.py): a weapon of the archery skill, in any case, that fits the range place. */
export const isBow = (item) => isWeapon(item) && item.weapon.skill !== null && item.weapon.skill.toLowerCase() === BOW_SKILL && item.slots.has(RANGE_GROUP);

/**
 * Whether the setup lets the item stand in the hand (`allowed_in_hand` in weapons.py; whether the item fits the slot is for the caller): a
 * two-hander is never in the off hand, a weapon of a ranged skill never in a hand, `stick` and `ranged` take anything else, the shield setup takes a shield in the off hand and a one-hander in the main hand,
 * `2h` a two-hander in the main hand, `dw` a one-hander in either. The range place takes a bow in the `ranged` setup and anything that fits it in the others.
 */
export function allowedInHand(item, hand, setup) {
  if (hand === RANGE_GROUP) return setup === "ranged" ? isBow(item) : true;
  if (RANGED_SKILL.test(item.weapon?.skill ?? "")) return false; // (`_ranged_skill` in weapons.py: archery, or a skill that begins with "throwing", in any case)
  if (hand === SECONDARY && item.weapon !== null && item.weapon.twoHanded) return false;
  if (setup === "stick" || setup === "ranged") return true;
  if (setup === "1h-shield" && hand === SECONDARY) return item.isShield;
  if (!isWeapon(item)) return false;
  if (setup === "2h") return hand === PRIMARY && item.weapon.twoHanded;
  return !item.weapon.twoHanded;
}

/** The procs of `hand` that the best pair can need, best first (`candidates` of procs.py): every proc up to and including the first one that nothing can block, since a proc that a worn Lore copy blocks leaves the next one in its place. */
export function procCandidates(table, item, hand) {
  const cell = table.cell(item, hand);
  if (cell.candidates === undefined) {
    const chosen = [];
    for (const entry of table.every(item, hand)) {
      chosen.push(entry);
      if (table.natives(item).has(entry.effect) || !table.sources(item, hand, entry.effect).every((key) => table.loreKeys.has(key))) break;
    }
    cell.candidates = chosen;
  }
  return cell.candidates;
}

/** What the item adds in the hand under the setup at the percent haste, exactly (`damage_index_exact` in weapons.py). */
export function damageIndex(item, hand, setup, hastePercent, dwFactor, rangedFactor = ONE, swingFactor = ONE, level = DEFAULT_LEVEL) {
  if (setup === "stick" || !allowedInHand(item, hand, setup) || !isWeapon(item)) return ZERO;
  if ((setup === "ranged") !== (hand === RANGE_GROUP)) return ZERO; // the hands of the bow setup are stat sticks, and the range place scores in no other setup
  const { weapon } = item;
  const haste = ONE.add(whole(hastePercent).div(UNITS.percent));
  const damage = whole(weapon.dmg);
  const delay = whole(weapon.delay);
  if (hand === SECONDARY) return damage.div(delay).mul(haste).mul(dwFactor).mul(swingFactor);
  if (hand === RANGE_GROUP) return damage.div(delay).mul(haste).mul(rangedFactor); // a bow's own damage per delay: no bonus, which is a main hand's; and no stance's factor
  const bonus = weapon.bonus !== null && weapon.bonus !== 0 ? whole(weapon.bonus) : fallbackBonus(weapon.twoHanded, delay, damage, level);
  return damage.add(bonus).div(delay).mul(haste).mul(swingFactor);
}

// ---- the buff set ------------------------------------------------------------------------------------------------------------------------

/** A buff of the table: its stats, its resists and its spell haste, each exact (a component it does not have is 0). */
function readBuff(id, entry) {
  if (!isPlain(entry)) throw fail(`the buff table has no entry for the buff ${id}`);
  const vec = own(entry, "vec");
  const stats = new Map();
  const sv = new Map();
  let haste = ZERO;
  for (const [name, value] of entriesOf(vec, `the buff ${id}: vec`)) {
    if (!COMPONENT_INDEX.has(name)) throw fail(`the buff ${id}: vec has a component (${safe(name)}) that the builder does not read`);
    const amount = exact(value, `the buff ${id}: ${safe(name)}`);
    if (name === HASTE) haste = amount;
    else if (SCHOOL_SET.has(name)) sv.set(name, amount);
    else stats.set(name, amount);
  }
  return { id, stats, sv, haste };
}

const isId = (value) => typeof value === "number" && Number.isSafeInteger(value);

/** The ids of the buffs of a list, each once: a buff that a list names twice would be two columns of one name, and be added twice to the totals. */
function idsOnce(list, where) {
  const ids = new Set();
  for (const { id } of list) {
    if (ids.has(id)) throw fail(`${where} names buff ${id} twice`);
    ids.add(id);
  }
  return ids;
}

/** The buff set (`{set, table}`) read into the buffs in the order of the set, and the rows that bind them; null for no buffs. */
export function readBuffset(raw) {
  if (raw === undefined || raw === null) return null;
  if (!isPlain(raw)) throw fail("the buff set is null or an object with a set and a table");
  const set = own(raw, "set");
  const tableRaw = own(raw, "table");
  if (!isPlain(set) || !isPlain(tableRaw)) throw fail("the buff set needs a set and a table (as the bundle writes them)");
  const table = new Map(entriesOf(tableRaw, "the buff table"));
  const buffs = (list, where) => {
    const found = own(set, list);
    if (!Array.isArray(found)) throw fail(`${where} must be a list of buff ids`);
    noHoles(found, where);
    return found.map((id, at) => {
      if (!isId(id)) throw fail(`${where}[${at}] must be the id of a buff (a whole number)`);
      return readBuff(id, table.get(String(id)));
    });
  };
  const alwaysOn = buffs("always_on", "the buff set's always_on");
  const optional = buffs("optional", "the buff set's optional");
  const fixedIds = idsOnce(alwaysOn, "the buff set's always_on");
  const optionalIds = idsOnce(optional, "the buff set's optional");
  for (const id of fixedIds) if (optionalIds.has(id)) throw fail(`buff ${id} is both always on and optional`);
  const conflictsRaw = own(set, "conflicts");
  const cliquesRaw = own(set, "cliques");
  if (!Array.isArray(conflictsRaw) || !Array.isArray(cliquesRaw)) throw fail("the buff set needs lists of conflicts and cliques");
  noHoles(conflictsRaw, "the buff set's conflicts");
  noHoles(cliquesRaw, "the buff set's cliques");
  const conflicts = conflictsRaw.map((entry, at) => {
    const where = `the buff set's conflicts[${at}]`;
    const wrong = fail(`${where} must be a pair of buff ids, and the list of reasons (texts) that the bundle writes after them, if any`);
    const listed = Array.isArray(entry) && entry.length === CONFLICT_FIELDS.length;
    if (!Array.isArray(entry) || (!listed && entry.length !== CONFLICT_FIELDS.length - 1)) throw wrong;
    noHoles(entry, where);
    const [a, b, reasons] = entry;
    if (!isId(a) || !isId(b)) throw wrong;
    if (listed) {
      if (!Array.isArray(reasons)) throw wrong;
      noHoles(reasons, `${where}[${CONFLICT_FIELDS.length - 1}]`);
      if (!reasons.every((text) => typeof text === "string")) throw wrong;
    }
    return [a, b];
  });
  const cliques = cliquesRaw.map((clique, at) => {
    if (!Array.isArray(clique)) throw fail(`the buff set's cliques[${at}] must be a list of buff ids`);
    noHoles(clique, `the buff set's cliques[${at}]`);
    for (const id of clique) if (!isId(id)) throw fail(`the buff set's cliques[${at}] must be a list of buff ids`);
    return clique.slice();
  });
  const cardinality = own(set, "cardinality") ?? null;
  if (cardinality !== null && !isCount(cardinality)) throw fail("the buff set's cardinality must be null or a whole number");
  return { alwaysOn, optional, conflicts, cliques, cardinality };
}

// ---- exact linear expressions --------------------------------------------------------------------------------------------------------------

/** `constant + sum(coefficient x column)` with exact coefficients, none of them 0. Never changed once made. */
class Lin {
  /** `terms` is a Map from a column to its coefficient; a coefficient of 0 is dropped, unless `clean` says that there is none. */
  constructor(constant, terms, clean) {
    this.constant = constant;
    if (terms === undefined) {
      this.terms = new Map();
    } else if (clean === true) {
      this.terms = terms;
    } else {
      this.terms = new Map();
      for (const [column, coefficient] of terms) if (coefficient.sign() !== 0) this.terms.set(column, coefficient);
    }
  }

  scaled(factor) {
    if (factor.sign() === 0) return new Lin(ZERO);
    const terms = new Map();
    for (const [column, coefficient] of this.terms) terms.set(column, coefficient.mul(factor));
    return new Lin(this.constant.mul(factor), terms, true);
  }

  plus(other, factor = ONE) {
    const terms = new Map(this.terms);
    for (const [column, coefficient] of other.terms) {
      const sum = (terms.get(column) ?? ZERO).add(coefficient.mul(factor));
      if (sum.sign() === 0) terms.delete(column);
      else terms.set(column, sum);
    }
    return new Lin(this.constant.add(other.constant.mul(factor)), terms, true);
  }
}

/** The continuous piecewise-linear value of x from 0 (`pwl` in formulas.py): a slope a band, nothing at or below 0. */
function pwl(x, breaks, slopes) {
  let total = ZERO;
  let low = ZERO;
  for (let at = 0; at < breaks.length && at < slopes.length; at += 1) {
    if (x.compare(low) <= 0) return total;
    total = total.add(slopes[at].mul(smaller(x, breaks[at]).sub(low)));
    low = breaks[at];
  }
  return x.compare(low) > 0 ? total.add(slopes[slopes.length - 1].mul(x.sub(low))) : total;
}

/**
 * How to sum the best two of some pools `base + fac x input` over the reachable range of their inputs (`plan_top_pools` in model.py). `specs` has
 * `{base, fac, key, lo, hi}` for each pool: pools with the same `key` share one input that runs over [lo, hi]; pools with different keys are compared
 * on the boxes of their ranges (a safe overestimate of what can happen together). Returns `{mode, indices}`: "none" for no pools, "all" when no more
 * than the pools that count exist, "fixed" with the pair that is a top two at every reachable point (the others never beat anything in it), and
 * "select" otherwise: which count depends on the gear, and the model needs binaries.
 */
export function planTopPools(specs) {
  const count = specs.length;
  if (count === 0) return { mode: "none", indices: [] };
  const counted = Number(CONSTANTS.poolsCounted.numerator);
  const everything = Array.from({ length: count }, (_, at) => at);
  if (count <= counted) return { mode: "all", indices: everything };

  const canBeat = (e, d) => {
    const a = specs[e];
    const b = specs[d];
    if (a.key === b.key) {
      const gap = a.base.sub(b.base);
      const slope = a.fac.sub(b.fac);
      return larger(gap.add(slope.mul(a.lo)), gap.add(slope.mul(a.hi))).sign() > 0;
    }
    const topOfA = larger(a.base.add(a.fac.mul(a.lo)), a.base.add(a.fac.mul(a.hi)));
    const bottomOfB = smaller(b.base.add(b.fac.mul(b.lo)), b.base.add(b.fac.mul(b.hi)));
    return topOfA.compare(bottomOfB) > 0;
  };

  // every way to leave out `count - counted` pools, in the order of itertools.combinations
  const leaveOut = count - counted;
  const choose = (from, size) => {
    if (size === 0) return [[]];
    const found = [];
    for (let at = from; at + size <= count; at += 1) for (const rest of choose(at + 1, size - 1)) found.push([at, ...rest]);
    return found;
  };
  for (const excluded of choose(0, leaveOut)) {
    const rest = everything.filter((at) => !excluded.includes(at));
    if (!excluded.some((e) => rest.some((d) => canBeat(e, d)))) return { mode: "fixed", indices: rest };
  }
  return { mode: "select", indices: everything };
}

// ---- the builder -------------------------------------------------------------------------------------------------------------------------

/** A bound of the document: null for none, else the number. */
const bound = (value) => (value === null ? null : real(value));

/** The CSR arrays `{start, index, value}` of rows `{terms, lb, ub}` (the columns of a row rise). */
function csrOf(rows) {
  const start = [0];
  const index = [];
  const value = [];
  for (const { terms } of rows) {
    for (const column of [...terms.keys()].sort((a, b) => a - b)) {
      index.push(column);
      value.push(real(terms.get(column)));
    }
    start.push(index.length);
  }
  return { start, index, value };
}

class Builder {
  constructor(profile, rawItems, setup, buffset, options) {
    if (!SETUP_SET.has(setup)) throw fail(`unknown setup ${show(setup)} (use ${[...SETUP_SET].map((name) => JSON.stringify(name)).join(", ")})`);
    if (!isRecord(profile)) throw fail("the profile is what assembleProfile gives, an object");
    this.opts = readOptions(options);
    this.setup = setup;
    this.p = profileOf(profile);
    const deity = own(profile, "deity") ?? null;
    const race = own(profile, "race") ?? null;
    if ((deity !== null && typeof deity !== "string") || (race !== null && typeof race !== "string")) throw fail("the profile's deity and race are texts or null");
    this.deity = deity;
    this.race = race; // an evaluator profile has none: no item is left out for its race
    this.spellHaste = this.readSpellHaste(own(profile, "spell_haste"));
    this.trio = new Set(this.p.pools.HP.map((spec) => spec.cls)); // one HP pool per class
    this.byClass = [...this.trio].every((code) => CLASS_SET.has(code)); // pools named by something else: no class to filter the pool by
    this.buffset = readBuffset(buffset);
    // the columns
    this.names = [];
    this.columnNames = new Set();
    this.rowNameSet = new Set();
    this.lb = [];
    this.ub = [];
    this.integer = [];
    this.obj = new Map();
    this.constant = ZERO;
    this.rows = [];
    this.rowNames = [];
    this.rowUses = new Map();
    this.inputIdents = new Set();
    this.colGroup = new Map();
    this.itemCols = [];
    this.index = new Map(); // group -> the labels of its item columns
    this.colsOfItem = new Map();
    this.buffCols = new Map();
    this.buffOfCol = new Map();
    this.info = { pools: { HP: "off", MANA: "off", END: "off" }, binaries: Object.fromEntries(BINARY_KINDS.map((kind) => [kind, 0])) };
    this.keys = 0;
    this.cache = new Map();
    this.hasteAssumed = 0;
    // the programs of the haste levels (LevelPrograms) are built once, leaving out what depends on the level: the rows after the worn-haste columns (haste.floor and the
    // ceilings) and the weapon part of the objective
    this.capture = false;
    this.hasteCtx = null;
    this.hasteSlot = 0;
    this.weaponCols = [];
    this.items = this.collect(rawItems);
  }

  // -- small helpers ----------------------------------------------------------------------------------------------------------------------

  /**
   * The profile's own spell haste as an exact number, null when it has none (an evaluator's profile has none). A Profile requires it to be at least 0
   * and at least the haste of the always-on buffs (profile.py), so a profile that is not is refused here, whatever the options say.
   */
  readSpellHaste(given) {
    if (given === undefined || given === null) return null;
    const spell = exact(given, "profile.spell_haste");
    if (spell.sign() < 0 || spell.compare(this.bconst(HASTE)) < 0) {
      throw fail(`profile.spell_haste must be at least 0 and at least the haste of the always-on buffs, not ${spell.toString()}`);
    }
    return spell;
  }

  /** Add a column called `name`. Model JSON names every column and its readers refuse a name twice: a second column of a name is a ModelError. */
  newColumn(name, lb, ub, integer = false) {
    if (this.columnNames.has(name)) throw fail(`two columns are called ${labelOf(name)}`);
    this.columnNames.add(name);
    this.names.push(name);
    this.lb.push(lb);
    this.ub.push(ub);
    this.integer.push(integer ? 1 : 0);
    return this.names.length - 1;
  }

  /** Add the row `lb <= terms <= ub` called `name` (a name that repeats gets #2, #3, ...; a final name that a row has already is a ModelError). */
  row(name, terms, lb, ub) {
    const clean = new Map();
    for (const [column, coefficient] of terms) if (coefficient.sign() !== 0) clean.set(column, coefficient);
    const uses = (this.rowUses.get(name) ?? 0) + 1;
    this.rowUses.set(name, uses);
    const called = uses === 1 ? name : `${name}#${uses}`;
    if (this.rowNameSet.has(called)) throw fail(`two rows are called ${labelOf(called)}`);
    this.rowNameSet.add(called);
    this.rowNames.push(called);
    this.rows.push({ terms: clean, lb, ub });
  }

  addObj(column, coefficient) {
    this.obj.set(column, (this.obj.get(column) ?? ZERO).add(coefficient));
  }

  addLin(lin, weight) {
    this.constant = this.constant.add(lin.constant.mul(weight));
    for (const [column, coefficient] of lin.terms) this.addObj(column, coefficient.mul(weight));
  }

  // -- the item pool ------------------------------------------------------------------------------------------------------------------------

  collect(rawItems) {
    if (!Array.isArray(rawItems)) throw fail("the items are a list of the pool");
    noHoles(rawItems, "items");
    const kept = [];
    const seen = new Set();
    rawItems.forEach((raw, at) => {
      const item = readItem(raw, at);
      if (seen.has(item.ident)) throw fail(`item ${safe(item.key)} (tier ${item.tier}) is in the pool twice`);
      seen.add(item.ident);
      this.inputIdents.add(item.ident);
      if (this.byClass && ![...item.classes].some((code) => this.trio.has(code))) return;
      if (item.deity !== null && (this.deity === null || !item.deity.has(this.deity))) return;
      if (this.race !== null && item.races !== null && !item.races.has(this.race)) return;
      kept.push(item);
    });
    return kept.sort((a, b) => compareText(a.key, b.key) || a.tier - b.tier);
  }

  fits(item, group) {
    if (group === ANY) return item.slots.has(ANY) || (this.opts.anyRule === RULE_ALL && [...item.slots].some((slot) => MODEL_SLOTS.has(slot)));
    if (!item.slots.has(group)) return false;
    if (WEAPON_GROUPS.has(group)) return allowedInHand(item, group, this.setup ?? "stick");
    return true;
  }

  // -- build --------------------------------------------------------------------------------------------------------------------------------

  build() {
    this.itemColumns();
    this.buffColumns();
    return this.buildTerms();
  }

  buildTerms() {
    this.hasteAssumed = this.assumedHaste();
    for (const term of [
      this.termHp, this.termMana, this.termEnd, this.termAc, this.termAtk, this.termDex, this.termCha, this.termHaste, this.termRegen, this.termResists,
      this.termWeapons, this.termProcs,
    ]) {
      term.call(this);
    }
    return this.finish();
  }

  itemColumns() {
    const byGroup = new Map();
    const loreCols = new Map();
    for (const [group, size] of SLOT_GROUPS) {
      this.items.forEach((item, position) => {
        if (!this.fits(item, group)) return;
        const labels = this.index.get(group) ?? new Set();
        this.index.set(group, labels);
        const label = labels.has(item.key) ? `${item.key}@${item.tier}` : item.key;
        const column = this.newColumn(`n[${group}|${label}]`, ZERO, item.lore ? ONE : whole(size), true);
        this.colGroup.set(column, group);
        this.itemCols.push({ col: column, group, item });
        labels.add(label);
        if (!this.colsOfItem.has(position)) this.colsOfItem.set(position, []);
        this.colsOfItem.get(position).push(column);
        if (!byGroup.has(group)) byGroup.set(group, []);
        byGroup.get(group).push(column);
        if (item.lore) {
          if (!loreCols.has(item.key)) loreCols.set(item.key, []);
          loreCols.get(item.key).push(column);
        }
      });
    }
    for (const [group, columns] of byGroup) {
      const reach = columns.reduce((sum, column) => sum.add(this.ub[column]), ZERO);
      if (reach.compare(whole(GROUP_SIZE.get(group))) > 0) this.row(`group.${group}`, new Map(columns.map((column) => [column, ONE])), null, whole(GROUP_SIZE.get(group)));
    }
    if (this.setup === "ranged") {
      // the bow setup is the one in which the range place holds a bow: it is filled even when the damage is worth nothing (the row range.bow of the Python builder)
      const bows = byGroup.get(RANGE_GROUP) ?? [];
      if (bows.length === 0) throw new NoBowError();
      this.row("range.bow", new Map(bows.map((column) => [column, ONE])), ONE, null);
    }
    for (const [key, columns] of loreCols) {
      if (columns.length > 1) this.row(`lore.${key}`, new Map(columns.map((column) => [column, ONE])), null, ONE);
    }
    // a two-hander in the primary hand leaves the secondary hand empty
    const twoHanded = this.itemCols.filter(({ group, item }) => group === PRIMARY && item.weapon !== null && item.weapon.twoHanded).map(({ col }) => col);
    const secondary = this.itemCols.filter(({ group }) => group === SECONDARY).map(({ col }) => col);
    if (twoHanded.length > 0 && secondary.length > 0) this.row("two_hander", new Map([...twoHanded, ...secondary].map((column) => [column, ONE])), null, ONE);
    this.ownershipRows();
    this.info.items = this.itemCols.length;
  }

  /**
   * The rows of the owned-item options: `own.<ident>` for every count that can bind (with a `made.<target>` row before it for each upgrade target that
   * can be worn more than once), then `new.limit` (see model.py). The options are read in sorted order, so the rows do not depend on the order of a mapping.
   */
  ownershipRows() {
    const caps = this.opts.ownedCaps;
    const ups = this.opts.upgrades;
    const news = new Set([...this.opts.newKeys, ...ups.keys()]); // an upgrade is a new wear whether or not it is listed
    if (caps.size === 0 && news.size === 0) return;
    const absent = [...new Set([...caps.keys(), ...news, ...ups.values()])].filter((name) => !this.inputIdents.has(name)).sort(compareText);
    if (absent.length > 0) throw fail(`${safe(absent[0])} is not an item of the pool`);
    const byIdent = new Map();
    const lore = new Map();
    for (const { col, item } of this.itemCols) {
      if (!byIdent.has(item.ident)) byIdent.set(item.ident, []);
      byIdent.get(item.ident).push(col);
      lore.set(item.ident, item.lore);
    }
    const targetsOf = new Map();
    for (const [target, source] of ups) {
      if (!targetsOf.has(source)) targetsOf.set(source, []);
      targetsOf.get(source).push(target);
    }
    const reachOf = (columns) => columns.reduce((sum, column) => sum.add(this.ub[column]), ZERO);
    const newTerms = new Map();
    for (const [name, count] of caps) {
      if (news.has(name) && count === 0) continue; // listed as owned with none, and a candidate: a plain new item, below
      const targets = targetsOf.get(name) ?? [];
      const members = [...(byIdent.get(name) ?? [])];
      const repeated = []; // the targets that can be worn more than once, as [target, columns, reach]
      for (const target of targets) {
        const columns = byIdent.get(target) ?? [];
        const top = this.opts.maxNew === null ? reachOf(columns) : smaller(reachOf(columns), whole(this.opts.maxNew)); // the most wears of the target the model can hold
        if (columns.length > 0 && lore.get(target) !== true && top.compare(ONE) > 0) repeated.push([target, columns, top]); // more than one wear (a whole number): one copy of the source makes the first (below)
        else members.push(...columns); // worn once at most: the upgraded copy is its wear
      }
      if (members.length === 0 && repeated.length === 0) continue; // the profile cannot use it: no column, nothing to count
      const isLore = lore.get(name) === true || targets.some((target) => lore.get(target) === true);
      const reach = reachOf(members).add(whole(repeated.length)); // (a repeated target counts at most one copy)
      const cap = whole(count);
      if (cap.compare(isLore ? smaller(reach, ONE) : reach) >= 0) continue; // the count can never bind (a Lore item is worn once whatever its count)
      const terms = new Map(members.map((column) => [column, ONE]));
      for (const [target, columns, top] of repeated) {
        const made = this.newColumn(`made[${target}]`, ZERO, ONE, true); // 1 when the target is worn at all
        this.info.binaries.made += 1;
        this.row(`made.${target}`, new Map([...columns.map((column) => [column, ONE]), [made, top.neg()]]), null, ZERO);
        terms.set(made, ONE);
      }
      if (news.has(name) && !isLore) {
        // a duplicate: copies above the count are acquired ones
        const room = this.opts.maxNew === null ? reach.sub(cap) : smaller(reach.sub(cap), whole(this.opts.maxNew));
        const extra = this.newColumn(`new[${name}]`, ZERO, room);
        terms.set(extra, ONE.neg());
        newTerms.set(extra, ONE);
      }
      this.row(`own.${name}`, terms, null, cap);
    }
    for (const name of [...news].filter((candidate) => (caps.get(candidate) ?? 0) === 0).sort(compareText)) {
      for (const column of byIdent.get(name) ?? []) newTerms.set(column, ONE);
    }
    if (this.opts.maxNew !== null && newTerms.size > 0) {
      const limit = whole(this.opts.maxNew);
      if (limit.compare(reachOf([...newTerms.keys()])) < 0) this.row("new.limit", newTerms, null, limit);
    }
  }

  // -- buffs --------------------------------------------------------------------------------------------------------------------------------

  /** The buff total of the profile (the always-on buffs) of a component, a stat or a resist or the haste. */
  bconst(name) {
    return this.p.buff[COMPONENT_INDEX.get(name)];
  }

  buffColumns() {
    const buffset = this.buffset;
    if (buffset === null) return;
    if (buffset.alwaysOn.length > 0) {
      // the buffs of the set that are always on must be the buffs of the profile
      const want = new Array(COMPONENTS.length).fill(ZERO);
      for (const buff of buffset.alwaysOn) {
        for (const [name, amount] of buff.stats) want[COMPONENT_INDEX.get(name)] = want[COMPONENT_INDEX.get(name)].add(amount);
        for (const [school, amount] of buff.sv) want[COMPONENT_INDEX.get(school)] = want[COMPONENT_INDEX.get(school)].add(amount);
        want[COMPONENT_INDEX.get(HASTE)] = larger(want[COMPONENT_INDEX.get(HASTE)], buff.haste);
      }
      COMPONENTS.forEach((name, at) => {
        if (!want[at].equals(this.p.buff[at])) throw fail(`profile.buff_totals disagrees with the always-on buffs of the buffset at ${name}`);
      });
    }
    const optional = new Map(buffset.optional.map((buff) => [buff.id, buff]));
    for (const buff of buffset.optional) {
      const column = this.newColumn(`buff[${buff.id}]`, ZERO, ONE, true);
      this.buffCols.set(column, buff.id);
      this.buffOfCol.set(column, buff);
    }
    this.info.binaries.buff = buffset.optional.length;
    const colOf = new Map([...this.buffCols].map(([column, id]) => [id, column]));
    const covered = new Set();
    const pairKey = (a, b) => `${a},${b}`;
    for (const clique of buffset.cliques) {
      const unknown = clique.filter((id) => !optional.has(id));
      if (unknown.length > 0) throw fail(`a clique names buff ${unknown[0]}, which is not optional`);
      this.row(`buff.clique[${clique.join(",")}]`, new Map(clique.map((id) => [colOf.get(id), ONE])), null, ONE);
      const sorted = [...clique].sort((a, b) => a - b);
      for (let i = 0; i < sorted.length; i += 1) for (let j = i + 1; j < sorted.length; j += 1) covered.add(pairKey(sorted[i], sorted[j]));
    }
    for (const [a, b] of buffset.conflicts) {
      if (!optional.has(a) || !optional.has(b)) throw fail(`a conflict names buff ${a} or ${b}, which is not optional`);
      const [low, high] = a < b ? [a, b] : [b, a];
      if (!covered.has(pairKey(low, high))) {
        this.row(`buff.conflict[${low},${high}]`, new Map([[colOf.get(a), ONE], [colOf.get(b), ONE]]), null, ONE);
        covered.add(pairKey(low, high));
      }
    }
    if (buffset.cardinality !== null) this.row("buff.limit", new Map([...this.buffCols.keys()].map((column) => [column, ONE])), null, whole(buffset.cardinality));
    const hasty = [...optional].filter(([, buff]) => buff.haste.sign() > 0).map(([id]) => id).sort((a, b) => a - b);
    for (let i = 0; i < hasty.length; i += 1) {
      for (let j = i + 1; j < hasty.length; j += 1) {
        if (!covered.has(pairKey(hasty[i], hasty[j]))) throw fail(`buffs ${hasty[i]} and ${hasty[j]} both carry spell haste and can be active together: only the best counts`);
      }
    }
  }

  // -- quantities as expressions ------------------------------------------------------------------------------------------------------------

  /** The coefficient of a quantity in an item worn in a group (a whole number). */
  itemCoef(name, item, group) {
    if (GEAR_KEYS.has(name)) return item.stats.get(name) ?? 0;
    if (name === "ACW" || name === "ACS") {
      const armor = item.stats.get("AC") ?? 0;
      const offHandShield = item.isShield && group === SECONDARY;
      return (name === "ACS") === offHandShield ? armor : 0;
    }
    if (name === "W10") return item.weight10;
    if (name.startsWith(RESIST_PREFIX)) return item.sv.get(name.slice(RESIST_PREFIX.length)) ?? 0;
    throw fail(`${name} is not a quantity of an item`);
  }

  /** The worn items' part of a quantity, with no constant. */
  gear(name) {
    const key = `gear:${name}`;
    if (!this.cache.has(key)) {
      const terms = new Map();
      for (const { col, group, item } of this.itemCols) {
        const coefficient = this.itemCoef(name, item, group);
        if (coefficient !== 0) terms.set(col, whole(coefficient));
      }
      this.cache.set(key, new Lin(ZERO, terms, true));
    }
    return this.cache.get(key);
  }

  /** The buffs' part of a quantity: the always-on constant and one term per optional buff. */
  buffpart(name) {
    const key = `buff:${name}`;
    if (!this.cache.has(key)) {
      const school = name.startsWith(RESIST_PREFIX) ? name.slice(RESIST_PREFIX.length) : null;
      const terms = new Map();
      for (const [column, buff] of this.buffOfCol) {
        const coefficient = (school === null ? buff.stats.get(name) : buff.sv.get(school)) ?? ZERO;
        if (coefficient.sign() !== 0) terms.set(column, coefficient);
      }
      this.cache.set(key, new Lin(this.bconst(school === null ? name : school), terms, true));
    }
    return this.cache.get(key);
  }

  /** Naked (attributes only) + buffs + gear. */
  total(name) {
    const key = `total:${name}`;
    if (!this.cache.has(key)) {
      let total = this.gear(name).plus(this.buffpart(name));
      const attribute = ATTRIBUTES.indexOf(name);
      if (attribute >= 0) total = new Lin(total.constant.add(this.p.naked[attribute]), total.terms, true);
      this.cache.set(key, total);
    }
    return this.cache.get(key);
  }

  /** The lowest and highest value that `lin` can take (item columns by group, with the places of each). */
  range(lin) {
    let lo = lin.constant;
    let hi = lin.constant;
    const byGroup = new Map();
    for (const [column, coefficient] of lin.terms) {
      const group = this.colGroup.get(column);
      if (group === undefined) {
        const low = this.lb[column];
        const high = this.ub[column];
        if (low === null || high === null) throw fail(`column ${this.names[column]} is unbounded inside a range`);
        const a = coefficient.mul(low);
        const b = coefficient.mul(high);
        lo = lo.add(smaller(a, b));
        hi = hi.add(larger(a, b));
      } else {
        if (!byGroup.has(group)) byGroup.set(group, []);
        byGroup.get(group).push({ coefficient, copies: Number(this.ub[column].numerator) });
      }
    }
    for (const [group, entries] of byGroup) {
      const places = GROUP_SIZE.get(group);
      let take = places;
      for (const { coefficient, copies } of entries.filter((entry) => entry.coefficient.sign() > 0).sort((a, b) => b.coefficient.compare(a.coefficient))) {
        if (take <= 0) break;
        const n = Math.min(copies, take);
        hi = hi.add(coefficient.mul(whole(n)));
        take -= n;
      }
      take = places;
      for (const { coefficient, copies } of entries.filter((entry) => entry.coefficient.sign() < 0).sort((a, b) => a.coefficient.compare(b.coefficient))) {
        if (take <= 0) break;
        const n = Math.min(copies, take);
        lo = lo.add(coefficient.mul(whole(n)));
        take -= n;
      }
    }
    return [lo, hi];
  }

  // -- curves -------------------------------------------------------------------------------------------------------------------------------

  /**
   * The value `f(max(lin, 0))` of a piecewise-linear curve from 0, as an expression over new columns. The curve is laid out over the reachable
   * range of `lin` only. Every user of the result is non-decreasing in it, so the maximizing solver fills the segments as far as the total allows.
   * Returns `{lin, lo, hi, key}`: the expression, the range of its value, and an identity for pools that share it.
   */
  curve(lin, breaks, slopes, label) {
    const [tLo, tHi] = this.range(lin);
    const effLo = larger(tLo, ZERO);
    const fLo = pwl(effLo, breaks, slopes);
    const fHi = pwl(larger(tHi, ZERO), breaks, slopes);
    const key = this.keys;
    this.keys += 1;
    if (fHi.equals(fLo)) return { lin: new Lin(fLo), lo: fLo, hi: fHi, key }; // flat over the whole range (or the range is a point)
    const bands = [];
    for (let k = 0; k < slopes.length; k += 1) {
      const start = k === 0 ? ZERO : breaks[k - 1];
      const stop = k < breaks.length ? breaks[k] : null;
      const a = larger(start, effLo);
      const b = stop === null ? tHi : smaller(stop, tHi);
      if (b.compare(a) > 0) bands.push({ slope: slopes[k], length: b.sub(a) });
    }
    while (bands.length > 0 && bands[bands.length - 1].slope.sign() === 0) bands.pop(); // a flat tail needs no segment: the sum below is only bounded above
    const xs = bands.map((band, k) => this.newColumn(`${label}.seg${k}`, ZERO, band.length));
    const row = new Map(xs.map((x) => [x, ONE]));
    for (const [column, coefficient] of lin.terms) row.set(column, (row.get(column) ?? ZERO).sub(coefficient));
    if (tLo.sign() >= 0) {
      this.row(`${label}.total`, row, null, lin.constant.sub(effLo)); // the sum of the segments is at most the total less the lowest total
    } else {
      // the total can be negative, where the value is flat: u is the deficit, one binary decides
      const u = this.newColumn(`${label}.u`, ZERO, tLo.neg());
      const wz = this.newColumn(`${label}.wz`, ZERO, ONE, true);
      this.info.binaries.deficit += 1;
      row.set(u, ONE.neg());
      this.row(`${label}.total`, row, null, lin.constant);
      this.row(`${label}.deficit`, new Map([[u, ONE], [wz, tLo.neg()]]), null, tLo.neg());
      const flat = new Map(xs.map((x) => [x, ONE]));
      flat.set(wz, bands.reduce((sum, band) => sum.add(band.length), ZERO).neg());
      this.row(`${label}.flat`, flat, null, ZERO);
    }
    const count = bands.length;
    for (let i = 0; i + 1 < count; i += 1) {
      if (!bands.slice(i + 1).some((later) => later.slope.compare(bands[i].slope) > 0)) continue;
      const z = this.newColumn(`${label}.ord${i}`, ZERO, ONE, true);
      this.info.binaries.ordering += 1;
      this.row(`${label}.ord${i}.full`, new Map([[xs[i], ONE], [z, bands[i].length.neg()]]), ZERO, null); // segment i is full when z = 1
      for (let j = i + 1; j < count; j += 1) {
        this.row(`${label}.ord${i}.empty${j}`, new Map([[xs[j], ONE], [z, bands[j].length.neg()]]), null, ZERO); // and every later one is empty when z = 0
      }
    }
    return { lin: new Lin(fLo, new Map(xs.map((x, k) => [x, bands[k].slope]))), lo: fLo, hi: fHi, key };
  }

  /** `min(total, cap)` of an attribute: the total itself when it cannot reach the cap, else a capped column. */
  capped(name) {
    const key = `capped:${name}`;
    if (!this.cache.has(key)) {
      const total = this.total(name);
      const [lo, hi] = this.range(total);
      let lin;
      if (hi.compare(STAT_CAP) <= 0) {
        lin = total;
      } else if (lo.compare(STAT_CAP) >= 0) {
        lin = new Lin(STAT_CAP);
      } else {
        const column = this.newColumn(`cap.${name}`, lo, STAT_CAP);
        const row = new Map([[column, ONE]]);
        for (const [c, coefficient] of total.terms) row.set(c, (row.get(c) ?? ZERO).sub(coefficient));
        this.row(`cap.${name}.max`, row, null, total.constant);
        lin = new Lin(ZERO, new Map([[column, ONE]]));
      }
      this.cache.set(key, lin);
    }
    return this.cache.get(key);
  }

  // -- pools --------------------------------------------------------------------------------------------------------------------------------

  /** The best two pools of a family, summed: `specs` has `{cls, base, fac, conv}` for each pool, `conv` the curve (see `curve`) that is its input. */
  poolFamily(family, specs, weight) {
    const { mode, indices } = planTopPools(specs.map(({ base, fac, conv }) => ({ base, fac, key: conv.key, lo: conv.lo, hi: conv.hi })));
    this.info.pools[family] = mode;
    if (mode === "all" || mode === "fixed") {
      for (const at of indices) {
        const { base, fac, conv } = specs[at];
        this.constant = this.constant.add(weight.mul(base));
        this.addLin(conv.lin, weight.mul(fac));
      }
      return;
    }
    const flags = [];
    for (const { cls, base, fac, conv } of specs) {
      const top = larger(base.add(fac.mul(conv.hi)), ZERO); // the largest absolute pool value, never a delta
      const bottom = smaller(base.add(fac.mul(conv.lo)), ZERO);
      const depth = bottom.neg(); // B: how far below zero the pool can fall; 0 for a pool that never does
      const kept = this.newColumn(`pool.${family}.kept.${cls}`, bottom, top);
      const z = this.newColumn(`pool.${family}.z.${cls}`, ZERO, ONE, true);
      const row = new Map([[kept, ONE], [z, depth]]);
      for (const [column, coefficient] of conv.lin.terms) row.set(column, (row.get(column) ?? ZERO).sub(fac.mul(coefficient)));
      // kept <= pool + B (1 - z): the pool itself when selected; when not, a pool below zero must not be subtracted
      this.row(`pool.${family}.kept.${cls}.le_pool`, row, null, base.add(fac.mul(conv.lin.constant)).add(depth));
      this.row(`pool.${family}.kept.${cls}.le_chosen`, new Map([[kept, ONE], [z, top.neg()]]), null, ZERO); // and zero unless the pool is selected
      this.addObj(kept, weight);
      flags.push(z);
    }
    const counted = CONSTANTS.poolsCounted;
    this.row(`pool.${family}.picks`, new Map(flags.map((z) => [z, ONE])), counted, counted);
    for (let i = 0; i + 1 < specs.length; i += 1) {
      // identical pools are interchangeable: take the first
      const a = specs[i];
      const b = specs[i + 1];
      if (a.base.equals(b.base) && a.fac.equals(b.fac) && a.conv.key === b.conv.key) this.row(`pool.${family}.twin${i}`, new Map([[flags[i], ONE], [flags[i + 1], ONE.neg()]]), ZERO, null);
    }
    this.info.binaries.selection += specs.length;
  }

  termHp() {
    const w = this.p.weights.HP;
    if (w.sign() === 0) return;
    this.addLin(this.total("HP"), w);
    const { breaks, slopes } = CONSTANTS.staCurve;
    const sta = this.curve(this.total("STA"), breaks, slopes, "curve.HP.sta");
    this.poolFamily("HP", this.p.pools.HP.map((q) => ({ cls: q.cls, base: q.base5, fac: q.fac, conv: sta })), w);
  }

  termMana() {
    const w = this.p.weights.MANA;
    const pools = this.p.pools.MANA;
    if (w.sign() === 0) return;
    if (pools.length === 0) {
      this.info.pools.MANA = "none"; // no mana class: no mana, whatever the items give
      return;
    }
    const { breaks, slopes } = this.p.bands;
    this.addLin(this.total("MANA"), w);
    const convs = new Map();
    const specs = [];
    for (const q of pools) {
      const stat = q.wis ? "WIS" : "INT";
      if (!convs.has(stat)) convs.set(stat, this.curve(this.total(stat), breaks, slopes, `curve.MANA.${stat}`));
      specs.push({ cls: q.cls, base: q.base, fac: q.fac, conv: convs.get(stat) });
    }
    this.poolFamily("MANA", specs, w);
  }

  termEnd() {
    const w = this.p.weights.END;
    if (w.sign() === 0) return;
    this.addLin(this.total("END"), w);
    const stats = ["STR", "STA", "DEX", "AGI"];
    let average = new Lin(ZERO);
    for (const stat of stats) average = average.plus(this.capped(stat), ONE.div(whole(stats.length)));
    const { breaks, slopes } = CONSTANTS.endCurve;
    const conv = this.curve(average, breaks, slopes, "curve.END.avg");
    this.poolFamily("END", this.p.pools.END.map((q) => ({ cls: q.cls, base: q.base, fac: q.fac, conv })), w);
  }

  // -- armor class, attack, dexterity, charisma -----------------------------------------------------------------------------------------------

  /** The Monk bonus as an expression: a constant when one bin covers the reachable weights, else one binary for each bin. */
  monkBonusLin() {
    const weight = this.gear("W10");
    const top = this.range(weight)[1];
    const stones = Number(top.div(UNITS.tenthsPerStone).floor());
    const table = monkTable(this.p, this.opts.monkBins, "options.monk_bins");
    const bins = []; // the runs of whole stones with the same bonus: {first stone, last stone, bonus}
    const beyond = table.length - 1; // the last entry of the table is the bonus of every weight beyond it
    for (let stone = 0; stone <= Math.min(stones, beyond); stone += 1) {
      if (bins.length > 0 && bins[bins.length - 1].bonus === table[stone]) bins[bins.length - 1].last = stone;
      else bins.push({ first: stone, last: stone, bonus: table[stone] });
    }
    if (stones > beyond) bins[bins.length - 1].last = stones; // and its bin goes on as far as the weights reach (a heavy kit costs no more to read than a light one)
    if (bins.length === 1) return new Lin(whole(bins[0].bonus));
    const zs = bins.map((_, n) => this.newColumn(`monk.z${n}`, ZERO, ONE, true));
    this.info.binaries.monk += bins.length;
    this.row("monk.one", new Map(zs.map((z) => [z, ONE])), ONE, ONE);
    const tenths = UNITS.tenthsPerStone;
    const upper = new Map(weight.terms);
    // the weight is at most the last tenth of the last stone of the bin: 10 (last + 1) - 1
    zs.forEach((z, n) => upper.set(z, tenths.mul(whole(bins[n].last + 1)).sub(ONE).neg()));
    this.row("monk.upper", upper, null, ZERO);
    const lower = new Map();
    for (const [column, coefficient] of weight.terms) lower.set(column, coefficient.neg());
    zs.forEach((z, n) => lower.set(z, tenths.mul(whole(bins[n].first))));
    this.row("monk.lower", lower, null, ZERO); // 10 first <= the weight
    return new Lin(ZERO, new Map(zs.map((z, n) => [z, whole(bins[n].bonus)])));
  }

  /** The two rows `a <= X` and `a <= rate X + (1 - rate) Y` and the worth of `a`: `perPoint` each. */
  cappedSheet(x, y, rate, perPoint) {
    const a = this.newColumn("sheet.a", null, null);
    const below = new Map([[a, ONE]]);
    const past = new Map([[a, ONE]]);
    for (const [column, coefficient] of x.terms) {
      below.set(column, (below.get(column) ?? ZERO).sub(coefficient));
      past.set(column, (past.get(column) ?? ZERO).sub(rate.mul(coefficient)));
    }
    const rest = ONE.sub(rate);
    for (const [column, coefficient] of y.terms) past.set(column, (past.get(column) ?? ZERO).sub(rest.mul(coefficient)));
    this.row("sheet.below", below, null, x.constant);
    this.row("sheet.past", past, null, rate.mul(x.constant).add(rest.mul(y.constant)));
    this.addObj(a, perPoint);
  }

  termAc() {
    const w = this.p.weights.AC;
    if (w.sign() === 0) return;
    const p = this.p;
    const sheet = CONSTANTS.sheet;
    const perPoint = w.div(sheet.itemMult);
    const monk = p.monk !== null ? this.monkBonusLin() : new Lin(ZERO);
    let inside = new Lin(ZERO);
    if (p.monkInside) inside = inside.plus(monk);
    else this.addLin(monk, perPoint);
    if (p.iksarInside) inside = inside.plus(new Lin(p.iksarAc));
    else this.constant = this.constant.add(perPoint.mul(p.iksarAc));
    const gear = this.gear("ACW");
    const shield = this.gear("ACS");
    const x = gear
      .plus(shield)
      .scaled(sheet.itemMult)
      .plus(new Lin(p.defenseTerm))
      .plus(this.buffpart("AC"), ONE.div(sheet.spellAcDiv));
    // (the Berserker stance: agility counts for nothing in the armor class and the evasion, and then neither term is made)
    const agiShare = p.agiShare;
    const withAgi = agiShare.sign() === 0 ? x : x.plus(this.capped("AGI"), ONE.div(sheet.agiDiv).mul(agiShare));
    const xAll = withAgi.plus(inside);
    const y = new Lin(p.softcapFloor).plus(shield);
    this.cappedSheet(xAll, y, p.rate, perPoint);
    if (agiShare.sign() !== 0) {
      const evasion = this.curve(this.total("AGI"), [STAT_CAP], [ONE, ZERO], "curve.AC.agi");
      this.addLin(evasion.lin, w.mul(CONSTANTS.agiToAc).mul(agiShare));
    }
  }

  termAtk() {
    const w = this.p.weights.ATK;
    if (w.sign() === 0) return;
    this.addLin(this.total("ATK"), w);
    const strength = this.curve(this.total("STR"), [STAT_CAP], [ONE, ZERO], "curve.ATK.str");
    this.addLin(strength.lin, w.mul(CONSTANTS.strToAtk));
  }

  termDex() {
    const w = this.p.weights.DEX;
    if (w.sign() === 0) return;
    const dex = this.curve(this.total("DEX"), [CONSTANTS.statKnee, STAT_CAP], [ONE, CONSTANTS.dexPastKnee, ZERO], "curve.DEX.dex");
    this.addLin(dex.lin, w);
  }

  termCha() {
    const w = this.p.weights.CHA;
    if (w.sign() === 0) return;
    const cha = this.curve(this.total("CHA"), [STAT_CAP], [ONE, ZERO], "curve.CHA.cha");
    this.addLin(cha.lin, w);
  }

  // -- haste, regen, resists --------------------------------------------------------------------------------------------------------------------

  /** The haste percent the weapon index assumes: the best spell haste on offer plus the best worn haste of the pool, up to the cap. */
  assumedHaste() {
    if (this.opts.hasteAssumed !== null) return this.opts.hasteAssumed;
    let spell = this.spellHaste;
    if (spell === null) {
      spell = this.bconst(HASTE);
      for (const buff of this.buffset === null ? [] : this.buffset.optional) spell = larger(spell, buff.haste);
      spell = spell.add(this.p.hasteBonus); // Unbound Alacrity stacks with the spell haste
    }
    let worn = ZERO;
    this.items.forEach((item, position) => {
      if (item.haste > 0 && this.colsOfItem.has(position)) worn = larger(worn, whole(item.haste));
    });
    return Number(smaller(this.p.hasteCap, larger(spell, ZERO).add(worn)).floor());
  }

  /**
   * The hastes a kit of this scenario can count, in percent, rising (`haste_levels` in model.py): every spell haste the scenario offers (the always-on buffs' with Unbound
   * Alacrity, or the best of those and one optional haste buff's, plus Unbound Alacrity) with 0 and with each distinct worn haste of the pool added, each cut at the cap.
   * A ModelError for a haste that is not a whole number (the program assumes whole percents).
   */
  hasteLevels() {
    const cap = this.p.hasteCap;
    const bonus = this.p.hasteBonus;
    const base = larger(this.bconst(HASTE).add(bonus), ZERO);
    const spells = new Map([[base.toString(), base]]);
    for (const buff of this.buffOfCol.values()) {
      if (buff.haste.sign() > 0) {
        const spell = larger(base, buff.haste.add(bonus));
        spells.set(spell.toString(), spell);
      }
    }
    const worn = new Map([[ZERO.toString(), ZERO]]);
    this.items.forEach((item, position) => {
      if (item.haste > 0 && this.colsOfItem.has(position)) worn.set(String(item.haste), whole(item.haste));
    });
    const levels = new Map();
    for (const spell of spells.values()) {
      for (const piece of worn.values()) {
        const level = smaller(cap, spell.add(piece));
        levels.set(level.toString(), level);
      }
    }
    return [...levels.values()]
      .sort((a, b) => a.compare(b))
      .map((level) => {
        if (!level.isInteger()) throw fail(`a haste of ${level.toString()} is not a whole number of percent: the weapon term assumes whole percents`);
        return Number(level.floor());
      });
  }

  /** One binary per distinct effective haste value; it may be 1 only if some item of that value is worn. */
  hasteBinaries(valueFor) {
    const byValue = new Map();
    this.items.forEach((item, position) => {
      if (item.haste > 0 && this.colsOfItem.has(position)) {
        const value = valueFor(whole(item.haste));
        if (value.sign() > 0) {
          const text = value.toString();
          if (!byValue.has(text)) byValue.set(text, { value, columns: [] });
          byValue.get(text).columns.push(...this.colsOfItem.get(position));
        }
      }
    });
    const flags = [];
    for (const { value, columns } of [...byValue.values()].sort((a, b) => a.value.compare(b.value))) {
      const y = this.newColumn(`haste.y${fractionText(value)}`, ZERO, ONE, true);
      const worn = new Map(columns.map((column) => [column, ONE.neg()]));
      worn.set(y, ONE);
      this.row(`haste.y${fractionText(value)}.worn`, worn, null, ZERO);
      flags.push([y, value]);
    }
    this.info.binaries.haste += flags.length;
    if (flags.length > 1) this.row("haste.one", new Map(flags.map(([y]) => [y, ONE])), null, ONE);
    return flags;
  }

  termHaste() {
    const w = this.p.weights.HASTE;
    const floor = this.opts.hasteFloor;
    if (w.sign() === 0 && floor === null) return;
    const cap = this.p.hasteCap;
    if (floor !== null && whole(floor).compare(cap) > 0) throw fail(`haste_floor ${floor} is above the haste cap ${cap.toString()}`);
    // The spell haste is the buff haste plus the flat haste of Unbound Alacrity (a trio with a Monk): adding it to the always-on haste and to each buff's own
    // haste shifts every spell haste by the same amount, so "the best one counts" still picks the same buff.
    const bonus = this.p.hasteBonus;
    const base = this.bconst(HASTE).add(bonus); // the haste of the always-on buffs, with Unbound Alacrity
    // Only the best spell haste counts and the haste buffs exclude each other, so the spell haste is one of a few constants: the base while no haste
    // buff is active, max(base, h) while the buff of haste h is.
    const choices = [...this.buffOfCol].filter(([, buff]) => buff.haste.sign() > 0).map(([column, buff]) => [column, buff.haste.add(bonus)]);
    this.constant = this.constant.add(w.mul(smaller(base, cap)));
    for (const [column, h] of choices) this.addObj(column, w.mul(smaller(larger(base, h), cap).sub(smaller(base, cap))));
    // worn haste: the best piece counts, up to the room the active spell haste leaves, max(0, cap - spell)
    const room0 = larger(ZERO, cap.sub(base));
    const rooms = choices.map(([column, h]) => [column, larger(ZERO, cap.sub(larger(base, h)))]);
    let top = room0;
    for (const [, room] of rooms) top = larger(top, room);
    const flags = top.sign() > 0 ? this.hasteBinaries((h) => smaller(h, top)) : [];
    let q = null;
    if (flags.length > 0) {
      q = this.newColumn("haste.q", ZERO, null);
      const best = new Map(flags.map(([y, value]) => [y, value.neg()]));
      best.set(q, ONE);
      this.row("haste.best", best, null, ZERO); // no more than the best worn piece
      const roomLeft = new Map(rooms.map(([column, room]) => [column, room0.sub(room)]));
      roomLeft.set(q, ONE);
      this.row("haste.room", roomLeft, null, room0); // nor than the room left
      if (w.sign() !== 0) this.addObj(q, w);
    }
    this.hasteCtx = { base, cap, choices, q };
    this.hasteSlot = this.rows.length;
    if (floor !== null && !this.capture) this.hasteLevelRows(floor);
  }

  /** The rows that make the kit count the haste `floor` (the only rows of the haste term that depend on it). */
  hasteLevelRows(floor) {
    const { base, cap, choices, q } = this.hasteCtx;
    if (whole(floor).compare(cap) > 0) throw fail(`haste_floor ${floor} is above the haste cap ${cap.toString()}`);
    if (whole(floor).compare(smaller(base, cap)) > 0) {
      // the haste the kit counts is the spell haste of its buffs plus the worn haste q: at least `floor`, so that the weapon term, which assumed `floor`, is true of the kit
      const counted = new Map(choices.map(([column, h]) => [column, smaller(larger(base, h), cap).sub(smaller(base, cap))]));
      if (q !== null) counted.set(q, ONE);
      this.row("haste.floor", counted, whole(floor).sub(smaller(base, cap)), null);
    }
    if (this.opts.hasteExact && whole(floor).compare(cap) < 0) this.hasteCeiling(whole(floor), base, choices);
  }

  /**
   * The kit counts no more than `floor` (below the cap), `_haste_ceiling` in model.py: under each spell haste that a choice of buffs can make active, no worn piece has more
   * than `floor` less that haste, and a haste buff whose own spell haste is above `floor` is not taken. With `haste.floor` the kit counts exactly `floor`.
   */
  hasteCeiling(floor, base, choices) {
    if (floor.compare(base) < 0) throw fail(`haste_floor ${floor.toString()} is below the haste ${base.toString()} that the always-on buffs and Unbound Alacrity give`);
    const classes = new Map(); // a spell haste above the base -> the columns of the buffs that make it
    for (const [column, h] of choices) {
      const spell = larger(base, h);
      if (spell.compare(base) <= 0) continue;
      const key = spell.toString();
      if (!classes.has(key)) classes.set(key, { spell, columns: [] });
      classes.get(key).columns.push(column);
    }
    const stronger = [...classes.values()].flatMap(({ columns }) => columns);
    const over = (allowed) => {
      const columns = [];
      this.items.forEach((item, position) => {
        if (item.haste > 0 && whole(item.haste).compare(allowed) > 0 && this.colsOfItem.has(position)) columns.push(...this.colsOfItem.get(position));
      });
      return columns;
    };
    const big = (columns) => columns.reduce((sum, column) => sum.add(this.ub[column]), ZERO);
    let pieces = over(floor.sub(base));
    if (pieces.length > 0) {
      // no buff stronger than the base is active: the worn piece may not be above what the base leaves
      const m = big(pieces);
      const terms = new Map(pieces.map((column) => [column, ONE]));
      for (const column of stronger) terms.set(column, m.neg());
      this.row(`haste.ceil[${fractionText(base)}]`, terms, null, ZERO);
    }
    for (const { spell, columns } of [...classes.values()].sort((a, b) => a.spell.compare(b.spell))) {
      if (spell.compare(floor) > 0) {
        this.row(`haste.over[${fractionText(spell)}]`, new Map(columns.map((column) => [column, ONE])), null, ZERO);
        continue;
      }
      pieces = over(floor.sub(spell));
      if (pieces.length === 0) continue;
      const m = big(pieces);
      const terms = new Map(pieces.map((column) => [column, ONE]));
      for (const column of columns) terms.set(column, m);
      this.row(`haste.ceil[${fractionText(spell)}]`, terms, null, m);
    }
  }

  termRegen() {
    ["HPREG", "MANAREG", "ENDREG"].forEach((name, at) => {
      const w = this.p.weights.regen[at];
      if (w.sign() === 0) return;
      this.addLin(this.buffpart(name), w);
      const gear = this.gear(name);
      const [lo, hi] = this.range(gear);
      this.cappedTerm(gear, this.p.regenCaps[at], lo, hi, w, `regen.${name}`);
    });
  }

  termResists() {
    SCHOOLS.forEach((school, at) => {
      const w = this.p.weights.schools[at];
      if (w.sign() === 0) return;
      const total = this.gear(`${RESIST_PREFIX}${school}`).plus(this.buffpart(`${RESIST_PREFIX}${school}`));
      const [lo, hi] = this.range(total);
      this.cappedTerm(total, this.p.resistCap, lo, hi, w, `sv.${school}`);
    });
  }

  /** `w x min(lin, cap)`: linear when the cap cannot bind, a constant when it always does, else a column. */
  cappedTerm(lin, cap, lo, hi, w, name) {
    if (hi.compare(cap) <= 0) {
      this.addLin(lin, w);
    } else if (lo.compare(cap) >= 0) {
      this.constant = this.constant.add(w.mul(cap));
    } else {
      const r = this.newColumn(name, null, cap);
      const row = new Map([[r, ONE]]);
      for (const [column, coefficient] of lin.terms) row.set(column, (row.get(column) ?? ZERO).sub(coefficient));
      this.row(`${name}.max`, row, null, lin.constant);
      this.addObj(r, w);
    }
  }

  // -- weapons ------------------------------------------------------------------------------------------------------------------------------

  termWeapons() {
    const w = this.p.weights.DMG;
    if (w.sign() === 0) return;
    const setup = this.setup ?? "stick";
    if (this.capture) {
      // (the coefficients are those of a level: LevelPrograms.programFor adds them)
      this.weaponCols = this.itemCols.filter(({ group }) => WEAPON_GROUPS.has(group));
      return;
    }
    for (const { col, group, item } of this.itemCols) {
      if (!WEAPON_GROUPS.has(group)) continue;
      const index = damageIndex(item, group, setup, this.hasteAssumed, this.p.dwFactor, this.p.rangedFactor, this.p.swing, this.p.level);
      if (index.sign() !== 0) this.addObj(col, w.mul(index));
    }
  }

  /**
   * The procs of the hands that swing (`_term_procs` of solver/model.py, whose docstring has the rows in words): `DMG x value / 600` for the proc a hand counts, with no haste factor, the off hand's by
   * the dual-wield factor. While no proc a hosted column can count has a Lore item among its sources the hands do not meet, and the proc is a constant on the column; else each way a proc can be counted
   * in a hand has a binary (`proc.n[e,hand]` its own, `proc.f[e,hand]` from a donor with a second copy, `proc.l[e,hand,k]` from the Lore item `k`) with the rows `proc.host.<kind>`, `proc.one`,
   * `proc.worn` (a Lore donor the kit wears is no donor) and `proc.copies` (the one copy of a Lore item supplies one hand).
   */
  termProcs() {
    const table = this.opts.procs;
    const w = this.p.weights.DMG;
    if (table === null || w.sign() === 0 || !["1h-shield", "2h", "dw"].includes(this.setup)) return;
    const hands = this.setup === "dw" ? HAND_NAMES : HAND_NAMES.slice(0, 1);
    const factor = { PRIMARY: ONE, SECONDARY: this.p.dwFactor };
    const counts = new Map(hands.map((hand) => [hand, []]));
    for (const { col, group, item } of this.itemCols) {
      if (counts.has(group) && damageIndex(item, group, this.setup, 0, this.p.dwFactor, this.p.rangedFactor, ONE, this.p.level).sign() !== 0) counts.get(group).push({ col, item, entries: procCandidates(table, item, group) });
    }
    const lored = hands.some((hand) =>
      counts.get(hand).some(({ item, entries }) => entries.some((entry) => !table.natives(item).has(entry.effect) && table.sources(item, hand, entry.effect).some((key) => table.loreKeys.has(key)))),
    );
    const value = (hand, effect) => w.mul(factor[hand]).mul(effect).div(PER_MINUTE_TO_INDEX);
    if (!lored) {
      for (const hand of hands) for (const { col, entries } of counts.get(hand)) if (entries.length > 0) this.addObj(col, value(hand, entries[0].value));
      return;
    }
    const byKey = new Map();
    for (const { col, item } of this.itemCols) {
      if (!byKey.has(item.key)) byKey.set(item.key, []);
      byKey.get(item.key).push(col);
    }
    let flags = 0;
    const lone = new Map(); // the flags that take a proc from the one copy of a Lore item, by item (both hands)
    for (const hand of hands) {
      const native = new Map();
      const plain = new Map();
      const lore = new Map();
      const push = (map, key, col) => map.set(key, [...(map.get(key) ?? []), col]);
      for (const { col, item, entries } of counts.get(hand)) {
        const own = table.natives(item);
        for (const entry of entries) {
          if (own.has(entry.effect)) {
            push(native, entry.effect, col);
            continue;
          }
          const found = table.sources(item, hand, entry.effect);
          if (found.some((key) => !table.loreKeys.has(key))) push(plain, entry.effect, col);
          else for (const key of found) push(lore, `${entry.effect}\u0000${key}`, col);
        }
      }
      const kinds = [
        ...[...native].map(([effect, cols]) => ({ kind: "n", effect, key: "", cols })),
        ...[...plain].map(([effect, cols]) => ({ kind: "f", effect, key: "", cols })),
        ...[...lore].map(([pair, cols]) => ({ kind: "l", effect: pair.split("\u0000")[0], key: pair.split("\u0000")[1], cols })),
      ].sort((a, b) => compareText(a.effect, b.effect) || compareText(a.kind, b.kind) || compareText(a.key, b.key));
      const mine = [];
      for (const { kind, effect, key, cols } of kinds) {
        const label = `${effect},${hand}${key === "" ? "" : `,${key}`}`;
        const y = this.newColumn(`proc.${kind}[${label}]`, ZERO, ONE, true);
        flags += 1;
        mine.push(y);
        this.addObj(y, value(hand, table.effects.find((one) => one.id === effect).value));
        this.row(`proc.host.${kind}[${label}]`, new Map([[y, ONE], ...cols.map((col) => [col, ONE.neg()])]), null, ZERO);
        if (kind === "l") {
          lone.set(key, [...(lone.get(key) ?? []), y]);
          if (byKey.has(key)) this.row(`proc.worn[${label}]`, new Map([[y, ONE], ...byKey.get(key).map((col) => [col, ONE])]), null, ONE);
        }
      }
      if (mine.length > 1) this.row(`proc.one[${hand}]`, new Map(mine.map((y) => [y, ONE])), null, ONE);
    }
    if (this.setup === "dw") {
      for (const key of [...lone.keys()].sort(compareText)) {
        if (lone.get(key).length > 1) this.row(`proc.copies[${key}]`, new Map(lone.get(key).map((y) => [y, ONE])), null, ONE);
      }
    }
    if (flags > 0) this.info.binaries.proc = flags;
  }

  // -- the document -------------------------------------------------------------------------------------------------------------------------

  finish() {
    const columns = this.names.length;
    const c = new Array(columns).fill(0);
    for (const [column, coefficient] of this.obj) c[column] = real(coefficient);
    const { start, index, value } = csrOf(this.rows);
    const info = {
      binaries: Object.fromEntries(Object.keys(this.info.binaries).sort().map((kind) => [kind, this.info.binaries[kind]])),
      cols: columns,
      haste_assumed: this.hasteAssumed,
      ...(this.opts.hasteExact ? { haste_exact: true } : {}),
      ...(this.opts.hasteFloor === null ? {} : { haste_floor: this.opts.hasteFloor }),
      items: this.info.items,
      pools: Object.fromEntries(Object.keys(this.info.pools).sort().map((family) => [family, this.info.pools[family]])),
      rows: this.rows.length,
    };
    return deepFreeze({
      version: 1,
      sense: "max",
      const: real(this.constant),
      col_names: this.names,
      col_lb: this.lb.map(bound),
      col_ub: this.ub.map(bound),
      integrality: this.integer,
      c,
      row_names: this.rowNames,
      row_lb: this.rows.map((row) => bound(row.lb)),
      row_ub: this.rows.map((row) => bound(row.ub)),
      A: { start, index, value },
      item_cols: this.itemCols.map(({ col, group, item }) => [col, group, item.key, item.tier]),
      buff_cols: [...this.buffCols].map(([column, id]) => [column, id]),
      info,
    });
  }
}

/**
 * The programs of the haste levels of one scenario, `LevelPrograms` in model.py: what `buildMilp` gives for the options with `haste_assumed`, `haste_floor` set to the level and
 * `haste_exact`, for each level, made from one build. The columns and the rows that do not depend on the level are built once, and `programFor(level)` adds the weapon coefficients of
 * the level and the rows that make the kit count it (the arrays are `buildMilp`'s with the same options, to the last bit). `levels` are `hasteLevels`'; `eligible` is
 * `buildMilpWithItems`'s.
 */
export class LevelPrograms {
  constructor(profile, items, setup, buffset, options) {
    this.options = options === undefined || options === null ? {} : options;
    const builder = new Builder(profile, items, setup === undefined ? null : setup, buffset, { ...this.options, haste_assumed: 0, haste_floor: 0, haste_exact: true });
    builder.capture = true;
    builder.itemColumns();
    builder.buffColumns();
    this.levels = builder.hasteLevels();
    this.base = builder.buildTerms();
    this.builder = builder;
    this.eligible = builder.items.map((item) => [item.key, item.tier]);
    this.made = new Map();
    this.partsMade = new Map();
  }

  /**
   * What a level adds to the level-free build, as `{c, rows}`: the objective of the level (`c`, a plain array) and its rows, `rows` being `{count, lb, ub, start, index, value}`
   * (CSR, the rows of the level only: they go after the first `slot` rows of the level-free model). Made once.
   */
  parts(level) {
    const made = this.partsMade.get(level);
    if (made !== undefined) return made;
    const { builder, base } = this;
    builder.opts = readOptions({ ...this.options, haste_assumed: level, haste_floor: level, haste_exact: true });
    const saved = { rows: builder.rows, rowNames: builder.rowNames, rowUses: builder.rowUses, rowNameSet: builder.rowNameSet };
    builder.rows = [];
    builder.rowNames = [];
    builder.rowUses = new Map(saved.rowUses);
    builder.rowNameSet = new Set(saved.rowNameSet);
    let added;
    try {
      builder.hasteLevelRows(level);
      added = { rows: builder.rows, names: builder.rowNames };
    } finally {
      Object.assign(builder, saved);
    }
    const csr = csrOf(added.rows);
    const c = base.c.slice();
    const w = builder.p.weights.DMG;
    if (w.sign() !== 0) {
      const setup = builder.setup ?? "stick";
      for (const { col, group, item } of builder.weaponCols) {
        const weapon = damageIndex(item, group, setup, level, builder.p.dwFactor, builder.p.rangedFactor, builder.p.swing, builder.p.level);
        if (weapon.sign() !== 0) c[col] = real((builder.obj.get(col) ?? ZERO).add(w.mul(weapon)));
      }
    }
    const parts = {
      c,
      names: added.names,
      rows: { count: added.rows.length, lb: added.rows.map((row) => bound(row.lb)), ub: added.rows.map((row) => bound(row.ub)), start: csr.start, index: csr.index, value: csr.value },
    };
    this.partsMade.set(level, parts);
    return parts;
  }

  /** The model of `level` (made once). */
  programFor(level) {
    const made = this.made.get(level);
    if (made !== undefined) return made;
    const { builder, base } = this;
    const { c, names, rows } = this.parts(level);
    const slot = builder.hasteSlot;
    const cut = base.A.start[slot];
    const start = [...base.A.start.slice(0, slot + 1), ...rows.start.slice(1).map((at) => at + cut), ...base.A.start.slice(slot + 1).map((at) => at + rows.index.length)];
    const index = [...base.A.index.slice(0, cut), ...rows.index, ...base.A.index.slice(cut)];
    const value = [...base.A.value.slice(0, cut), ...rows.value, ...base.A.value.slice(cut)];
    const row_lb = [...base.row_lb.slice(0, slot), ...rows.lb, ...base.row_lb.slice(slot)];
    const row_ub = [...base.row_ub.slice(0, slot), ...rows.ub, ...base.row_ub.slice(slot)];
    const row_names = [...base.row_names.slice(0, slot), ...names, ...base.row_names.slice(slot)];
    const info = {
      binaries: base.info.binaries,
      cols: base.info.cols,
      haste_assumed: level,
      haste_exact: true,
      haste_floor: level,
      items: base.info.items,
      pools: base.info.pools,
      rows: row_names.length,
    };
    const model = deepFreeze({
      version: 1,
      sense: "max",
      const: base.const,
      col_names: base.col_names,
      col_lb: base.col_lb,
      col_ub: base.col_ub,
      integrality: base.integrality,
      c,
      row_names,
      row_lb,
      row_ub,
      A: { start, index, value },
      item_cols: base.item_cols,
      buff_cols: base.buff_cols,
      info,
    });
    this.made.set(level, model);
    return model;
  }
}

/**
 * The model JSON v1 document of the program for `profile`, the item pool `items`, the weapon `setup` and the buff set; see the head of this file for
 * what each is. A ModelError for an input that is not what is read: an unknown setup or stat, a repeated item, an ident that is not an item of the
 * pool, a `buffset` whose always-on buffs are not the profile's buff totals, optional haste buffs that can be active together, an option that is not read.
 * An EvaluateError for a profile that the evaluator would not read either.
 */
export function buildMilp(profile, items, setup, buffset, options) {
  return buildMilpWithItems(profile, items, setup, buffset, options).model;
}

/**
 * The hastes a kit of the scenario can count, in percent, rising (`haste_levels` in model.py). The arguments are those of `buildMilp`; the options decide the Any rule, and so which
 * items have a place.
 */
export function hasteLevels(profile, items, setup, buffset, options) {
  const builder = new Builder(profile, items, setup === undefined ? null : setup, buffset, options);
  builder.itemColumns();
  builder.buffColumns();
  return builder.hasteLevels();
}

/**
 * `buildMilp` and the items that the profile can use, as `{model, eligible}`: `eligible` is `[key, tier]` for every item of the pool that the
 * builder kept (a class of the trio, a deity the profile admits, a race it allows), in the order of `(key, tier)`, whether the item has a column or
 * not. It is `Milp.items` of the Python builder, which the tie stage of the solver ranks the items by (solve.js).
 */
export function buildMilpWithItems(profile, items, setup, buffset, options) {
  const builder = new Builder(profile, items, setup === undefined ? null : setup, buffset, options);
  const model = builder.build();
  return { model, eligible: builder.items.map((item) => [item.key, item.tier]) };
}
