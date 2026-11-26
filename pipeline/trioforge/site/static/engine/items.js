// An item of the item table at one upgrade tier, 0 to 10: a port of `at_tier` in pipeline/trioforge/model/items.py, with whole-number
// arithmetic only, held to the item at every tier and both weapon rates that Python wrote (tests-js/engine-items.test.mjs).
//
// `atTier(item, tier, rules, {weaponPct})` takes a record of the item table (items.json: only the fields that differ from `ITEM_DEFAULTS`),
// a tier, the rules (the bundle: its `tier_rules` and `weapon_rules`, which are checked and compiled once for each bundle that `readBundle`
// made; a bundle given raw is read every time, which is slow) and the weapon rate, 5 or 10 percent a tier (the rate of `weapon_rules` when
// none is given, as `at_tier` takes the rule `tier.weapon_damage_pct`). It gives the numbers the model sees when the item is worn at the tier:
//
//   * Stats (AC STR STA AGI DEX WIS INT CHA HP MANA END) and resists: `base + max(n, floor(base * n / 10))` when the base is above zero;
//     a negative stat moves toward zero by the same amount, `max(n, floor(|base| * n / 10))`, and never passes zero (`tier.negatives_scale`, the game
//     client's own calculation, and rules that say anything else are refused). Attack (ATK) is not scaled at all (`tier.unscaled_stats`, the same
//     source): an item's attack at +4 or +10 is its +0 value.
//   * Worn haste and the three regens: a flat `haste_per_tier` / `regen_per_tier` a tier when the base is above zero. Haste is a field of its
//     own, not one of the stats.
//   * Weight, in tenths of a stone: `max(floor, w - w * pct * n // 100)` for a weight w above zero, `pct` the rule `tier.weight_pct` (9, a percent of the
//     base a tier, no minimum step) and the floor a tenth of a stone; a weightless item stays weightless; an item with no weight on its page counts as
//     `unknown_weight10` (1.0 stone) at every tier and keeps `weight_known` false.
//   * Weapon damage: `dmg + dmg * n * pct // 100`, with no minimum of a point a tier; delay and the listed bonus never change. An item has a weapon only
//     when the page gives both a damage and a delay, and a shield has none.
//   * A shield is an item that fits the off hand (the SECONDARY slot) and whose `item_type` is Shield in any case. Nothing else makes one.
//   * Races: null for any race (ALL in any case, or no field), else the sorted codes; an empty list is a page that says Race: NONE.
//
// The result has the fields of ItemVec, named as Python names them (is_shield, weight_known, two_handed), and the sets of Python are sorted lists
// without repeats; zero stats are dropped; everything in it is frozen. No arithmetic here goes through a double that is not a whole number:
// every number is a safe integer (at most a thousand million in size, so that a product of three stays one), and a quotient is taken from a
// multiple of its divisor.

import { isPlainObject as isPlain, safe } from "./plain.js";
import { BundleError, readBundle } from "./profile.js";
import { Rational, RationalError } from "./rational.js";
import { wornHaste } from "./tiers.js";

/** A record that is not what the item table writes, or a tier or rate that is not allowed. */
export class ItemError extends Error {
  constructor(message) {
    super(message);
    this.name = "ItemError";
  }
}

/** The stats that follow the stat rule, in the order of the model. */
export const STAT_KEYS = Object.freeze(["AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK"]);
/** The stats that add a flat amount a tier. */
export const REGEN_KEYS = Object.freeze(["HPREG", "MANAREG", "ENDREG"]);
/** The schools the table knows; the model scores the first five. */
export const SV_KEYS = Object.freeze(["FIRE", "COLD", "MAGIC", "POISON", "DISEASE", "CORRUPTION"]);
/** The sixteen class codes, sorted (what ALL means). */
export const CLASS_CODES = Object.freeze(["BER", "BRD", "BST", "CLR", "DRU", "ENC", "MAG", "MNK", "NEC", "PAL", "RNG", "ROG", "SHD", "SHM", "WAR", "WIZ"]);
/** What an absent field of a record means (ITEM_DEFAULTS in browser.py; the table carries them as `defaults`). */
export const ITEM_DEFAULTS = Object.freeze({
  key: null,
  match_name: null,
  classes: Object.freeze(["ALL"]),
  races: Object.freeze(["ALL"]),
  deity: null,
  lore: false,
  stats: Object.freeze({}),
  sv: Object.freeze({}),
  weapon: null,
  item_type: null,
  item_type_source: null,
  aliases: Object.freeze([]),
  owned_only: false,
});

const MAX_TIER = 10;
const STAT_RULE_TEXT = "base + max(n, floor(base*n/10))";
const NEGATIVES_RULE_TEXT = "toward zero by max(n, floor(|base|*n/10)), never past zero";
const DAMAGE_RULE_TEXT = "dmg + dmg * n * pct // 100";
const WEIGHT_RULE_TEXT = "max(floor, w - w * pct * n // 100)";
const WEAPON_PCTS = [5, 10];
const PERCENT = 100;
/** The largest number a stat, a weight or a damage may be: a product of three of them and a tier stays a safe integer. */
const MAX_VALUE = 1_000_000_000;
const SCALED = new Set([...STAT_KEYS, ...REGEN_KEYS, "HASTE"]);
const SCHOOLS = new Set(SV_KEYS);

// ---- the rules --------------------------------------------------------------------------------------------------------------------

/** The compiled tier rules of each bundle that was read. */
const COMPILED = new WeakMap();

function wholeRule(text, where, { min = 0 } = {}) {
  let value;
  try {
    value = Rational.parse(text);
  } catch (error) {
    if (error instanceof RationalError) throw new BundleError(`${where} is not a rational p/q`);
    throw error;
  }
  if (!value.isInteger() || value.numerator < BigInt(min) || value.numerator > BigInt(MAX_VALUE)) {
    throw new BundleError(`${where} must be a whole number of at least ${min}`);
  }
  return Number(value.numerator);
}

function compile(bundle) {
  const tier = bundle.tier_rules;
  const weapon = bundle.weapon_rules;
  if (tier.stat_rule !== STAT_RULE_TEXT) throw new BundleError(`bundle.tier_rules.stat_rule is not the rule that atTier implements (${STAT_RULE_TEXT})`);
  if (tier.negatives_scale !== NEGATIVES_RULE_TEXT) throw new BundleError(`bundle.tier_rules.negatives_scale is not the rule that atTier implements (${NEGATIVES_RULE_TEXT})`);
  if (!Array.isArray(tier.unscaled_stats) || tier.unscaled_stats.some((name) => typeof name !== "string" || !STAT_KEYS.includes(name))) {
    throw new BundleError(`bundle.tier_rules.unscaled_stats must be a list of stats of the model (${STAT_KEYS.join(", ")})`);
  }
  if (wholeRule(tier.max_tier, "bundle.tier_rules.max_tier") !== MAX_TIER) throw new BundleError(`bundle.tier_rules.max_tier must be ${MAX_TIER}`);
  const divisor = wholeRule(tier.stat_divisor, "bundle.tier_rules.stat_divisor", { min: 1 });
  if (divisor !== 10) throw new BundleError("bundle.tier_rules.stat_divisor must be 10, the 10 of the stat rule");
  if (tier.weight_rule !== WEIGHT_RULE_TEXT) throw new BundleError(`bundle.tier_rules.weight_rule is not the rule that atTier implements (${WEIGHT_RULE_TEXT})`);
  if (weapon.damage_rule !== DAMAGE_RULE_TEXT) throw new BundleError(`bundle.weapon_rules.damage_rule is not the rule that atTier implements (${DAMAGE_RULE_TEXT})`);
  if (!Array.isArray(weapon.damage_pct_choices)) throw new BundleError("bundle.weapon_rules.damage_pct_choices must be a list");
  const choices = weapon.damage_pct_choices.map((text) => wholeRule(text, "bundle.weapon_rules.damage_pct_choices", { min: 1 }));
  if (choices.length !== WEAPON_PCTS.length || choices.some((value, index) => value !== WEAPON_PCTS[index])) {
    throw new BundleError(`bundle.weapon_rules.damage_pct_choices must be ${WEAPON_PCTS.join(" and ")}`);
  }
  const weaponPct = wholeRule(weapon.damage_pct, "bundle.weapon_rules.damage_pct", { min: 1 });
  if (!WEAPON_PCTS.includes(weaponPct)) throw new BundleError(`bundle.weapon_rules.damage_pct must be one of ${WEAPON_PCTS.join(", ")}`);
  return Object.freeze({
    divisor,
    floor10: wholeRule(tier.weight_floor10, "bundle.tier_rules.weight_floor10", { min: 1 }),
    weightPct: wholeRule(tier.weight_pct, "bundle.tier_rules.weight_pct"),
    unknownWeight10: wholeRule(tier.unknown_weight10, "bundle.tier_rules.unknown_weight10"),
    hastePerTier: wholeRule(tier.haste_per_tier, "bundle.tier_rules.haste_per_tier"),
    regenPerTier: wholeRule(tier.regen_per_tier, "bundle.tier_rules.regen_per_tier"),
    weaponPct,
    unscaled: new Set(tier.unscaled_stats),
  });
}

function tierRules(rules) {
  const bundle = readBundle(rules);
  let compiled = COMPILED.get(bundle);
  if (compiled === undefined) {
    compiled = compile(bundle);
    COMPILED.set(bundle, compiled);
  }
  return compiled;
}

/**
 * Check the tier and weapon rules of a bundle, and compile them (once: `atTier` uses what is compiled here). A BundleError for rules that are not the ones this
 * port implements. Whoever loads a bundle calls this, so that a bundle with rules it cannot use is refused when it is loaded and not at the first item that
 * is worked out under it.
 */
export function checkTierRules(rules) {
  tierRules(rules);
}

// ---- the record -------------------------------------------------------------------------------------------------------------------



function recordKey(id, key) {
  if (typeof key === "string" && key.length > 0) return key;
  if (typeof id === "number" && Number.isSafeInteger(id)) return `w${id}`;
  throw new ItemError("an item record has no key and no page id");
}

function sortedUnique(list) {
  if (list.length < 2) return list.slice();
  return [...new Set(list)].sort();
}

function textList(value, field, label) {
  if (!Array.isArray(value)) throw new ItemError(`item ${label}: ${field} must be a list`);
  for (const entry of value) if (typeof entry !== "string") throw new ItemError(`item ${label}: ${field} must be a list of texts`);
  return value;
}

/** A whole number a stat, a weight or a damage may be: a safe integer of at most a thousand million. */
function amount(value, field, label) {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value > MAX_VALUE || value < -MAX_VALUE) {
    throw new ItemError(`item ${label}: ${field} must be a whole number`);
  }
  return value;
}

/** The quotient of x by d, for x of zero or more: x less its remainder is a multiple of d, so the division is exact. */
function quotient(x, d) {
  return (x - (x % d)) / d;
}

/** The stat rule: `base + max(n, base * n // 10)` above zero; below zero the stat moves toward zero by `max(n, |base| * n // 10)`, never past it; zero stays. */
function scaled(base, n, divisor) {
  if (base > 0) return base + Math.max(n, quotient(base * n, divisor));
  if (base < 0) return base + Math.min(-base, Math.max(n, quotient(-base * n, divisor)));
  return base;
}

function checkTier(tier) {
  if (typeof tier !== "number" || !Number.isInteger(tier)) throw new ItemError(`the tier must be a whole number from 0 to ${MAX_TIER}`);
  if (tier < 0 || tier > MAX_TIER) throw new ItemError(`the tier must be a whole number from 0 to ${MAX_TIER}, not ${tier}`);
  return tier;
}

function checkPct(pct) {
  if (typeof pct !== "number" || !WEAPON_PCTS.includes(pct)) throw new ItemError(`the weapon damage rate must be one of ${WEAPON_PCTS.join(", ")} percent a tier`);
  return pct;
}

function twoHanded(skill) {
  const text = (skill ?? "").toLowerCase().split("-").join(" ");
  return text.startsWith("2h") || text.startsWith("two hand");
}

/**
 * The item (a record of the item table) at the tier (0 to 10) under the rules of a bundle. `weaponPct` replaces the rate of the rules (5 or 10
 * percent a tier). An ItemError for a tier or a rate that is not allowed, for an option it does not read (a misspelt weaponPct) and for a record that is not what the table writes (an unknown stat
 * or resist included); a BundleError for rules that are not the ones this port implements.
 */
export function atTier(item, tier, rules, options) {
  const rule = tierRules(rules);
  const n = checkTier(tier);
  if (options !== undefined && options !== null && (typeof options !== "object" || Array.isArray(options))) {
    throw new ItemError("the options are an object, such as {weaponPct: 10}");
  }
  if (options !== undefined && options !== null) {
    for (const key of Object.keys(options)) {
      if (key !== "weaponPct") throw new ItemError(`the options have an option (${safe(key)}) that atTier does not read (it reads weaponPct)`);
    }
  }
  const given = options === undefined || options === null ? undefined : options.weaponPct;
  const pct = given === undefined || given === null ? rule.weaponPct : checkPct(given);

  if (!isPlain(item)) throw new ItemError("an item is a record of the item table, an object");
  const { id, key: written, name, slots, classes, races, deity, lore, stats, sv, weight10, weapon, item_type: type } = item;
  const key = recordKey(id, written);
  if (typeof name !== "string") throw new ItemError(`item ${safe(key)}: name must be text`);
  const slotList = textList(slots, "slots", safe(key));
  const label = safe(key);

  // stats, regen and haste
  const rawStats = stats === undefined ? ITEM_DEFAULTS.stats : stats;
  if (!isPlain(rawStats)) throw new ItemError(`item ${label}: stats must be an object`);
  for (const name of Object.keys(rawStats)) if (!SCALED.has(name)) throw new ItemError(`item ${label}: unknown stat ${safe(name)}`);
  const outStats = {};
  for (const name of STAT_KEYS) {
    const base = rawStats[name];
    if (base !== undefined && base !== null && base !== 0) {
      const value = amount(base, `stat ${name}`, label);
      const tiered = rule.unscaled.has(name) ? value : scaled(value, n, rule.divisor);
      if (tiered !== 0) outStats[name] = tiered; // (a negative stat that the tiers have shrunk to nothing is gone, like any zero)
    }
  }
  for (const name of REGEN_KEYS) {
    const base = rawStats[name];
    if (base !== undefined && base !== null && base !== 0) {
      const value = amount(base, `stat ${name}`, label);
      outStats[name] = value > 0 ? value + n * rule.regenPerTier : value;
    }
  }
  const hasteBase = rawStats.HASTE === undefined || rawStats.HASTE === null ? 0 : amount(rawStats.HASTE, "stat HASTE", label);
  const haste = wornHaste(hasteBase, n, rule.hastePerTier);

  // resists
  const rawSv = sv === undefined ? ITEM_DEFAULTS.sv : sv;
  if (!isPlain(rawSv)) throw new ItemError(`item ${label}: sv must be an object`);
  for (const name of Object.keys(rawSv)) if (!SCHOOLS.has(name)) throw new ItemError(`item ${label}: unknown resist ${safe(name)}`);
  const outSv = {};
  for (const name of SV_KEYS) {
    const base = rawSv[name];
    if (base !== undefined && base !== null && base !== 0) {
      const tiered = scaled(amount(base, `resist ${name}`, label), n, rule.divisor);
      if (tiered !== 0) outSv[name] = tiered;
    }
  }

  // who may wear it
  const slotSet = sortedUnique(slotList);
  const classList = classes === undefined ? ITEM_DEFAULTS.classes : textList(classes, "classes", label);
  const allClasses = classList.includes("ALL");
  const deityList = deity === undefined || deity === null ? null : sortedUnique(textList(deity, "deity", label));
  let raceList = null;
  if (races !== undefined && races !== null) {
    if (!Array.isArray(races) || Array.from(races).some((code) => typeof code !== "string")) throw new ItemError(`item ${label}: races must be a list of race codes`);
    raceList = races.some((code) => code.toUpperCase() === "ALL") ? null : sortedUnique(races);
  }
  if (lore !== undefined && typeof lore !== "boolean") throw new ItemError(`item ${label}: lore must be true or false`);
  if (type !== undefined && type !== null && typeof type !== "string") throw new ItemError(`item ${label}: item_type must be text`);
  const isShield = slotList.includes("SECONDARY") && typeof type === "string" && type.toLowerCase() === "shield";

  // the weapon
  let outWeapon = null;
  if (weapon !== undefined && weapon !== null) {
    if (!isPlain(weapon)) throw new ItemError(`item ${label}: weapon must be an object`);
    const { skill, dmg, delay, bonus } = weapon;
    if (skill !== null && typeof skill !== "string") throw new ItemError(`item ${label}: the weapon skill must be text`);
    for (const [field, value] of [["dmg", dmg], ["delay", delay], ["bonus", bonus]]) {
      if (value !== null) amount(value, `weapon ${field}`, label);
    }
    if (!isShield && dmg !== null && delay !== null) {
      outWeapon = Object.freeze({ skill, dmg: dmg > 0 ? dmg + quotient(dmg * n * pct, PERCENT) : dmg, delay, bonus, two_handed: twoHanded(skill) });
    }
  }

  // the weight, in tenths of a stone
  let weight;
  let known = true;
  if (weight10 === null) {
    weight = rule.unknownWeight10;
    known = false;
  } else {
    const tenths = amount(weight10, "weight10", label);
    weight = tenths <= 0 ? 0 : Math.max(rule.floor10, tenths - quotient(tenths * n * rule.weightPct, PERCENT));
  }

  return Object.freeze({
    key,
    name,
    slots: Object.freeze(slotSet),
    classes: allClasses ? CLASS_CODES : Object.freeze(sortedUnique(classList)),
    deity: deityList === null ? null : Object.freeze(deityList),
    lore: lore === true,
    stats: Object.freeze(outStats),
    sv: Object.freeze(outSv),
    haste,
    weight10: weight,
    weapon: outWeapon,
    is_shield: isShield,
    tier: n,
    weight_known: known,
    races: raceList === null ? null : Object.freeze(raceList),
  });
}

// ---- the table --------------------------------------------------------------------------------------------------------------------

/**
 * The item table as the precompute writes it (`items.json` beside the shards; `items` in pipeline/trioforge/export/browser.py documents it, and site/data.py
 * checks it when it is built into the site): `{version, data_release, rules_version, count, defaults, items}`, one record for every wearable of the catalog,
 * which has only the fields that differ from the table's `defaults` (what an absent field means, ITEM_DEFAULTS here). `readItemTable` reads the parsed
 * document, refusing, with an ItemError, whatever the writer does not write: another version, a field of the table or of a record that is not in the format,
 * a count that is not the number of records, defaults that are not the writer's, a record with a name, slots, tier rule or evidence that is not one, an owned-only
 * flag on an item that is not hidden. It returns `{dataRelease, rulesVersion, count, defaults, records}`, `records` a Map from the item key (a record's `key`, else
 * `w` and its page id) to the record, which `atTier` turns into the numbers of the item at a tier (and which checks the stats and resists it uses).
 */
const TABLE_VERSION = 1;
const TABLE_FIELDS = ["version", "data_release", "rules_version", "count", "defaults", "items"];
/** The fingerprint of the inputs the table was made from (the catalog, and the evidence level of every item once the flags are merged): optional. */
const FINGERPRINT = /^[0-9a-f]{64}$/;
const RECORD_FIELDS = new Set([
  "id", "key", "name", "match_name", "aliases", "slots", "classes", "races", "deity", "lore", "stats", "sv", "weight10", "weapon", "item_type", "item_type_source",
  "tier_rule", "evidence", "owned_only", "source",
]); // fmt: skip
/** The slots a record may list: the places of a kit but the Any places, and three that no place of a kit has (the catalog's schema). */
const SLOT_NAMES = new Set([
  "HEAD", "FACE", "EAR", "NECK", "SHOULDERS", "ARMS", "BACK", "WRIST", "HANDS", "FINGER", "CHEST", "LEGS", "FEET", "WAIST", "RANGE", "PRIMARY", "SECONDARY", "AMMO", "CHARM", "POWERSOURCE",
]); // fmt: skip
const LEVELS = new Set(["strict", "wiki", "disputed", "hidden"]);
const TIER_RULE_NAMES = new Set(["drop", "fixed0", "spell"]);
/** The longest key an item has: "r", a letter or digit, and up to 99 more letters, digits and hyphens (the catalog's schema, site/data.py, and the matcher of a dump, input/match.js, read keys by this length). */
export const MAX_ITEM_KEY_LENGTH = 101;
// a page id has no zero in front: w07 is not another way of writing w7 (and not a second record of page 7)
const ITEM_KEY = new RegExp(`^(?:w[1-9][0-9]{0,14}|r[a-z0-9][a-z0-9-]{0,${MAX_ITEM_KEY_LENGTH - 2}})$`);
/**
 * What a record may hold, one number for each limit (the build holds the files to the same ones, site/data.py RECORD_LIMITS, and a test holds the two to each other):
 * the length of a text and of the name of a stat, how many aliases, classes, races, deities, reason codes and slots, the length of an item type, of a reason code and of
 * a place of the source, and how many records a table has.
 */
export const RECORD_LIMITS = Object.freeze({
  text: 300, statName: 24, aliases: 64, classes: 17, races: 16, deity: 16, itemType: 40, codes: 40, codeText: 80, sourceText: 200, slots: SLOT_NAMES.size, records: 200_000,
}); // fmt: skip
const MAX_RECORDS = RECORD_LIMITS.records;
const MAX_TEXT = RECORD_LIMITS.text;

const tableFail = (detail) => new ItemError(`item table: ${detail}`);
const has = (object, name) => Object.prototype.hasOwnProperty.call(object, name);
const CONTROL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/;
const isText = (value, max = MAX_TEXT) => typeof value === "string" && value.length > 0 && value.length <= max && !CONTROL.test(value);
const isAmount = (value) => typeof value === "number" && Number.isSafeInteger(value) && value >= -MAX_VALUE && value <= MAX_VALUE;

/** Whether two pieces of plain data are the same: the same keys (in any order) and the same values, all through. */
function sameData(a, b) {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null || Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(a);
  if (keys.length !== Object.keys(b).length) return false;
  return keys.every((key) => has(b, key) && sameData(a[key], b[key]));
}

function listOf(value, where, name, { min = 0, max, test = isText }) {
  if (!Array.isArray(value) || value.length < min || value.length > max) throw tableFail(`${where}: ${name} must be a list of ${min === 1 ? "1 to " : "up to "}${max}`);
  for (let at = 0; at < value.length; at += 1) {
    if (!(at in value) || !test(value[at])) throw tableFail(`${where}: ${name} has an entry that is not allowed`);
  }
}

/** The stats (or the resists) of a record: whole numbers by a name that atTier reads (`allowed`), so that a name it would refuse is refused when the table is read. */
function amounts(value, where, name, allowed) {
  if (!isPlain(value)) throw tableFail(`${where}: ${name} must be an object`);
  for (const [stat, amount] of Object.entries(value)) {
    if (!isText(stat, RECORD_LIMITS.statName) || !allowed.has(stat) || !isAmount(amount)) throw tableFail(`${where}: ${name} must hold whole numbers by a name the model knows`);
  }
}

/** How many places of each kind the summary of the source of an item names (the exporter's _SOURCE_ZONES and _SOURCE_QUESTS in browser.py); the rest are counted in `more`. */
const SOURCE_PLACES = Object.freeze({ drops: 3, sold: 3, forage: 2, quests: 2 });
const MAX_SOURCE_TEXT = RECORD_LIMITS.sourceText;

/**
 * The source of an item as the exporter writes it: lists of zones it drops in (`drops`), is sold in (`sold`) and is foraged in (`forage`) and of the quests it is
 * a reward of (`quests`), each of one to the most the exporter keeps and none twice, texts of at most 200 characters with no control or separator character;
 * `crafted`, how many ways it is crafted, a whole number of at least 1; and `more`, for each full list, how many places did not fit, a whole number of at least 1.
 */
function checkSource(source, where) {
  if (!isPlain(source)) throw tableFail(`${where}: the source must be an object`);
  const keys = Object.keys(source);
  if (keys.length === 0) throw tableFail(`${where}: the source has nothing in it`);
  for (const key of keys) {
    if (!(has(SOURCE_PLACES, key) || key === "crafted" || key === "more")) throw tableFail(`${where}: the source has a part that is not allowed`);
  }
  for (const [kind, most] of Object.entries(SOURCE_PLACES)) {
    if (!has(source, kind)) continue;
    listOf(source[kind], where, `the source ${kind}`, { min: 1, max: most, test: (text) => isText(text, MAX_SOURCE_TEXT) });
    if (new Set(source[kind]).size !== source[kind].length) throw tableFail(`${where}: the source ${kind} names a place twice`);
  }
  const count = (value) => typeof value === "number" && Number.isSafeInteger(value) && value >= 1 && value <= MAX_VALUE;
  if (has(source, "crafted") && !count(source.crafted)) throw tableFail(`${where}: the source's crafted must be a whole number of at least 1`);
  if (has(source, "more")) {
    const { more } = source;
    if (!isPlain(more) || Object.keys(more).length === 0) throw tableFail(`${where}: the source's more must be an object of counts`);
    for (const [kind, extra] of Object.entries(more)) {
      if (!has(SOURCE_PLACES, kind) || !has(source, kind) || source[kind].length !== SOURCE_PLACES[kind]) {
        throw tableFail(`${where}: the source's more counts only the places that did not fit in a full list`);
      }
      if (!count(extra)) throw tableFail(`${where}: the source's more must hold whole numbers of at least 1`);
    }
  }
}

/** One record of the table, checked; returns its item key and its page id (null for an item that has none). */
function checkRecord(record, at) {
  const where = `record ${at + 1}`;
  if (!isPlain(record)) throw tableFail(`${where} is not an object`);
  for (const name of Object.keys(record)) {
    if (!RECORD_FIELDS.has(name)) throw tableFail(`${where} has a field that is not allowed`);
  }
  if (!has(record, "id")) throw tableFail(`${where} has no page id`);
  const { id } = record;
  if (id !== null && !(Number.isSafeInteger(id) && id >= 1)) throw tableFail(`${where}: the page id must be a whole number from 1, or null`);
  let key = `w${id}`;
  if (has(record, "key")) {
    key = record.key;
    if (typeof key !== "string" || !ITEM_KEY.test(key)) throw tableFail(`${where}: the key is not the key of an item`);
  } else if (id === null) {
    throw tableFail(`${where} has neither a key nor a page id`);
  }
  if (!isText(record.name)) throw tableFail(`${where}: the name must be text`);
  if (has(record, "match_name") && !isText(record.match_name)) throw tableFail(`${where}: match_name must be text`);
  if (has(record, "aliases")) listOf(record.aliases, where, "aliases", { max: RECORD_LIMITS.aliases });
  if (!has(record, "slots")) throw tableFail(`${where} lists no slots`);
  listOf(record.slots, where, "slots", { min: 1, max: RECORD_LIMITS.slots, test: (slot) => SLOT_NAMES.has(slot) });
  if (has(record, "classes")) listOf(record.classes, where, "classes", { max: RECORD_LIMITS.classes });
  if (has(record, "races")) listOf(record.races, where, "races", { max: RECORD_LIMITS.races });
  if (has(record, "deity")) listOf(record.deity, where, "deity", { min: 1, max: RECORD_LIMITS.deity });
  if (has(record, "lore") && record.lore !== true) throw tableFail(`${where}: lore is there only when it is true`);
  if (has(record, "stats")) amounts(record.stats, where, "stats", SCALED);
  if (has(record, "sv")) amounts(record.sv, where, "sv", SCHOOLS);
  if (!has(record, "weight10")) throw tableFail(`${where} has no weight`);
  if (record.weight10 !== null && !(Number.isSafeInteger(record.weight10) && record.weight10 >= 0 && record.weight10 <= MAX_VALUE)) {
    throw tableFail(`${where}: the weight must be whole tenths of a stone, or null`);
  }
  if (has(record, "weapon")) {
    const { weapon } = record;
    if (!isPlain(weapon) || Object.keys(weapon).length !== 4 || !["skill", "dmg", "delay", "bonus"].every((name) => has(weapon, name))) {
      throw tableFail(`${where}: a weapon has a skill, a damage, a delay and a bonus`);
    }
    if (weapon.skill !== null && !isText(weapon.skill)) throw tableFail(`${where}: the weapon skill must be text or null`);
    for (const name of ["dmg", "delay", "bonus"]) {
      if (weapon[name] !== null && !isAmount(weapon[name])) throw tableFail(`${where}: the weapon ${name} must be a whole number or null`);
    }
  }
  if (has(record, "item_type")) {
    if (!isText(record.item_type, RECORD_LIMITS.itemType)) throw tableFail(`${where}: the item type must be text`);
    if (has(record, "item_type_source") && record.item_type_source !== null && !isText(record.item_type_source, RECORD_LIMITS.itemType)) throw tableFail(`${where}: the item type source must be text or null`);
  } else if (has(record, "item_type_source")) {
    throw tableFail(`${where}: an item type source comes with an item type`);
  }
  if (!TIER_RULE_NAMES.has(record.tier_rule)) throw tableFail(`${where}: the tier rule is not one of the rules`);
  const evidence = record.evidence;
  if (!isPlain(evidence) || !LEVELS.has(evidence.level) || Object.keys(evidence).some((name) => name !== "level" && name !== "codes")) {
    throw tableFail(`${where}: the evidence is a level and, if there are any, the codes of its reasons`);
  }
  if (has(evidence, "codes")) listOf(evidence.codes, where, "the evidence codes", { max: RECORD_LIMITS.codes, test: (code) => isText(code, RECORD_LIMITS.codeText) });
  if (has(record, "owned_only") && record.owned_only !== true) throw tableFail(`${where}: owned_only is there only when it is true`);
  if (has(record, "owned_only") !== (evidence.level === "hidden")) throw tableFail(`${where}: owned_only is for a hidden item and no other`);
  if (has(record, "source")) checkSource(record.source, where);
  return { key, id };
}

export function readItemTable(document) {
  if (!isPlain(document)) throw tableFail("is not an object");
  const fingerprinted = has(document, "inputs");
  if (Object.keys(document).length !== TABLE_FIELDS.length + (fingerprinted ? 1 : 0) || !TABLE_FIELDS.every((name) => has(document, name))) {
    throw tableFail("does not have the fields the precompute writes, and no other");
  }
  if (fingerprinted && !(typeof document.inputs === "string" && FINGERPRINT.test(document.inputs))) {
    throw tableFail("inputs must be a fingerprint: 64 lower-case hexadecimal digits");
  }
  if (document.version !== TABLE_VERSION) throw tableFail(`is of another version (this reader takes version ${TABLE_VERSION})`);
  const { data_release: release, rules_version: rules, count, defaults, items } = document;
  if (release !== null && !isText(release, 40)) throw tableFail("data_release must be text or null");
  if (!isText(rules, 40)) throw tableFail("rules_version must be text");
  if (!sameData(defaults, ITEM_DEFAULTS)) throw tableFail("defaults are not what an absent field of a record means here");
  if (!Array.isArray(items) || items.length > MAX_RECORDS) throw tableFail(`items must be a list of at most ${MAX_RECORDS} records`);
  if (count !== items.length) throw tableFail("count is not the number of records");
  const records = new Map();
  const pages = new Set();
  for (let at = 0; at < items.length; at += 1) {
    if (!(at in items)) throw tableFail(`record ${at + 1} is a hole in the list`);
    const { key, id } = checkRecord(items[at], at);
    if (records.has(key)) throw tableFail(`record ${at + 1} repeats an item`);
    if (id !== null) {
      if (pages.has(id)) throw tableFail(`record ${at + 1} repeats a page`); // a page names one item, whatever keys the records have
      pages.add(id);
    }
    records.set(key, items[at]);
  }
  return Object.freeze({ dataRelease: release, rulesVersion: rules, inputs: fingerprinted ? document.inputs : null, count, defaults: ITEM_DEFAULTS, records });
}
