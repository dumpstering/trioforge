// A trio's bundle, read, and the profile of a scenario put together from it.
//
// The bundle (pipeline/trioforge/export/browser.py, `bundle`) is one JSON document per trio and level with everything the engine needs to rebuild
// any profile: the part of the profile that does not vary (`profile_common`), what varies with the race (`races`), the role (`roles`: the weights
// and the weapon setups, those of a profile with no pool to read in `setups` and one list for each evidence level in `setups_by_evidence`) and the
// buff set (`buffs`), and the constants and rules the rest of the engine reads (`constants`, `monk_bins`, `tier_rules`, `weapon_rules`,
// `weight_groups`, `regen_ratios`).
//
// `readBundle` is the one door the bundle goes through. It takes the parsed document, checks it, and gives back a copy that nothing can change:
//   * plain data only (null, booleans, finite numbers, text, lists, objects), to a depth and a size that are capped, walked with a stack of its
//     own so that no input can exhaust the call stack; a getter, a symbol, a class, a function, a hole in a list, a number that is not finite
//     or a whole number a double cannot hold exactly is refused;
//   * no key that could poison a lookup (__proto__, constructor, prototype) anywhere, and no such name in a list of names (the attributes, the
//     weight keys, the setups ...), since the names become keys downstream;
//   * the shape of everything `assembleProfile` and the other ports read, field by field: the version, the trio and the level, the common part
//     with exactly the fields of Profile.to_dict() that do not vary, the races, the roles with their weights and non-empty setups at every evidence
//     level, the buff sets -- and nothing else: the top level, a row of the races, the roles and the buff sets, and an entry of a pool list have
//     exactly the fields that the exporter writes (a mana pool names its stat, no other does); the buff table holds whole numbers only, under the
//     component names of the bundle (the builder adds the always-on buffs in exact numbers, Python as floats: they agree for whole numbers); and every exact number in the six exact blocks a
//     reduced "p/q" text (a bare number there, or a rational with a zero denominator or not in lowest terms, is refused) -- the same texts that
//     `unrat` in browser.py takes, but for the size of a text (at most
//     MAX_DIGITS = 64 digits a part) and the number of them (at most 2,500 in a bundle): reducing a text costs the square of its digits, and a
//     bundle of 400 texts of 4,096 digits took the reader 24 s, where a document within the limits is now read, or refused, in 0.15 s at most.
// A bundle that `readBundle` made is recognised when it comes back, so it is read once and handed on. Lookups by a name that a visitor or a
// bundle chose go through a Map, never through an object.
//
// `assembleProfile(bundle, {race, role, buffs, deity, evidence})` is `assemble` of browser.py: Profile.to_dict() of that choice, as a frozen
// object whose parts are frozen too. With an `evidence` level the weapon setups are those of the solve pool of that level
// (`roles[role].setups_by_evidence[evidence]`) and the profile carries the label; with none they are `roles[role].setups`. A race, role, buff key
// or evidence level the bundle does not have and a blank deity are a ChoiceError (a BundleError that is the asker's fault); a choice other than the five above, and any bundle that is not
// what the exporter writes, are a BundleError that is not.

import { MAX_DIGITS, MAX_TEXT_LENGTH, Rational, RationalError } from "./rational.js";

/** A bundle that is not what the exporter writes, or a choice the bundle does not have (that is a ChoiceError, below). */
export class BundleError extends Error {
  constructor(message) {
    super(message);
    this.name = "BundleError";
  }
}

/**
 * A choice the bundle does not have: a race, a role, a buff key, an evidence level, or a deity that is no name. A BundleError that says the fault is in what was asked for and not in
 * the bundle, so that whoever asked can refuse the request and still trust the bundle; any other BundleError is the bundle's own.
 */
export class ChoiceError extends BundleError {
  constructor(message) {
    super(message);
    this.name = "ChoiceError";
  }
}

/** The format number of the bundle (FORMAT in browser.py). */
export const BUNDLE_VERSION = 1;

/**
 * What a document may hold. `maxRationals` is the number of "p/q" texts: each costs a reduction (see MAX_DIGITS in rational.js), so a document of
 * texts of the most digits, as many as there are, reads in about a tenth of a second here. The bundles of the exporter hold 104 to 393 (385 in
 * the sample), so 2,500 is a margin of more than six times.
 */
const LIMITS = Object.freeze({ maxDepth: 16, maxNodes: 100_000, maxText: 10_000, maxRationals: 2_500 });
/** The same limits, and the digits a part of a "p/q" may have, for whoever holds a bundle to them before the browser reads it (site/data.py does, and a test holds the two to each other). */
export const BUNDLE_LIMITS = Object.freeze({ ...LIMITS, maxDigits: MAX_DIGITS });

/** The fields of Profile.to_dict(), in order. */
export const PROFILE_FIELDS = Object.freeze([
  "format", "race", "trio", "level", "role", "evidence", "aa", "naked", "buff_totals", "spell_haste", "haste_cap", "softcap", "cs_pct", "pe_pct",
  "defense_cap", "monk", "iksar_ac", "placement", "pools", "caps", "bands", "dw_factor", "weights", "setups", "deity", "haste_bonus", "nd_pct",
]); // fmt: skip
const RACE_FIELDS = ["race", "naked", "iksar_ac"];
const ROLE_FIELDS = ["role", "weights", "setups"];
const BUFF_FIELDS = ["buff_totals", "spell_haste"];
const VARYING = new Set([...RACE_FIELDS, ...ROLE_FIELDS, ...BUFF_FIELDS]);
const COMMON_FIELDS = PROFILE_FIELDS.filter((field) => !VARYING.has(field));
/** The fingerprint of the inputs a bundle (and the item table) was made from: a SHA-256, as 64 lower-case hexadecimal digits. The field is optional. */
const FINGERPRINT = /^[0-9a-f]{64}$/;
const TOP_FIELDS = [
  "version", "data_release", "rules_version", "trio", "level", "profile_common", "evidence_levels", "races", "roles", "buffs", "buff_table", "constants",
  "monk_bins", "tier_rules", "weapon_rules", "weight_groups", "regen_ratios",
]; // fmt: skip
/** The blocks whose every exact number is a "p/q" text (and which hold no bare number). */
const EXACT_BLOCKS = ["constants", "monk_bins", "tier_rules", "weapon_rules", "weight_groups", "regen_ratios"];
/** The roles a bundle may offer (ROLES in pipeline/trioforge/model/roles.py). */
const ROLES = ["balanced", "tank", "melee", "caster"];
const FORBIDDEN_KEYS = new Set(["__proto__", "constructor", "prototype"]);
const SET_FIELDS = ["always_on", "optional", "conflicts", "cliques", "cardinality", "dropped"];
/** The fields of a row of `races`, of `roles` and of `buffs`, and of an entry of a pool list, as `bundle` and `Profile.to_dict()` of browser.py write them. */
const RACE_ROW_FIELDS = ["code", "name", "legal", "naked", "iksar_ac"];
const ROLE_ROW_FIELDS = ["weights", "setups", "setups_by_evidence"];
const BUFF_ROW_FIELDS = ["buff_totals", "spell_haste", "set"];
const POOL_FIELDS = ["cls", "base", "fac"];
const MANA_POOL_FIELDS = ["cls", "base", "fac", "stat"]; // only a mana pool names the stat that it converts
/** The choices `assembleProfile` reads; any other key is a misspelling that would be ignored, and the profile would look right. */
const CHOICE_KEYS = new Set(["race", "role", "buffs", "evidence", "deity"]);

// ---- messages ---------------------------------------------------------------------------------------------------------------------

const fail = (where, problem) => new BundleError(`${where} ${problem}`);

/** A name from the bundle or from a visitor, safe to put in a message: short, and only letters, digits and a few signs. */
function safeName(name) {
  if (typeof name !== "string") return "?";
  if (name.length === 0) return "(empty)";
  if (name.length > 24) return "?";
  for (let i = 0; i < name.length; i += 1) {
    const code = name.charCodeAt(i);
    const ok = (code >= 0x30 && code <= 0x39) || (code >= 0x41 && code <= 0x5a) || (code >= 0x61 && code <= 0x7a) || code === 0x5f || code === 0x2b || code === 0x2e || code === 0x2d;
    if (!ok) return "?";
  }
  return name;
}

/** The path of a node of the walk, from the chain of entries (only built when something is wrong). */
function pathOf(entry) {
  const keys = [];
  for (let node = entry; node !== null; node = node.parent) if (node.key !== undefined) keys.push(node.key);
  keys.reverse();
  return `bundle${keys.map((key) => (typeof key === "number" ? `[${key}]` : `.${safeName(key)}`)).join("")}`;
}

// ---- the walk: plain data, copied and frozen ------------------------------------------------------------------------------------

function isPlainObject(value) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

/**
 * A copy of plain data, frozen all through. Iterative, with a stack of its own: the depth and the number of nodes are counted, and the
 * walk reads each property once. Plain objects come out as plain objects (with the keys in the order they had), lists as lists.
 */
function copyPlain(root) {
  const containers = [];
  const stack = [{ source: root, depth: 0, parent: null, key: undefined, target: null }];
  let nodes = 0;
  let result;
  while (stack.length > 0) {
    const entry = stack.pop();
    const { source, depth } = entry;
    nodes += 1;
    if (nodes > LIMITS.maxNodes) throw fail(pathOf(entry), "is part of a document that is too large");
    let copy;
    if (source === null || typeof source === "boolean") {
      copy = source;
    } else if (typeof source === "number") {
      if (!Number.isFinite(source)) throw fail(pathOf(entry), "is a number that is not finite");
      if (Number.isInteger(source) && !Number.isSafeInteger(source)) throw fail(pathOf(entry), "is a whole number a double cannot hold exactly");
      copy = source;
    } else if (typeof source === "string") {
      if (source.length > LIMITS.maxText) throw fail(pathOf(entry), "is a text that is too long");
      copy = source;
    } else if (typeof source === "object") {
      if (depth >= LIMITS.maxDepth) throw fail(pathOf(entry), "is nested too deeply");
      if (Array.isArray(source)) {
        if (source.length > LIMITS.maxNodes) throw fail(pathOf(entry), "is a list that is too long");
        copy = new Array(source.length);
        containers.push(copy);
        for (let index = source.length - 1; index >= 0; index -= 1) {
          stack.push({ source: source[index], depth: depth + 1, parent: entry, key: index, target: copy });
        }
      } else if (isPlainObject(source)) {
        copy = {};
        containers.push(copy);
        const keys = Reflect.ownKeys(source);
        for (let index = keys.length - 1; index >= 0; index -= 1) {
          const key = keys[index];
          if (typeof key !== "string") throw fail(pathOf(entry), "has a symbol for a key");
          if (FORBIDDEN_KEYS.has(key)) throw fail(pathOf(entry), "has a key that could poison a lookup");
          const descriptor = Object.getOwnPropertyDescriptor(source, key);
          if (descriptor === undefined || !("value" in descriptor) || descriptor.enumerable !== true) {
            throw fail(pathOf(entry), `has a property (${safeName(key)}) that is not plain data`);
          }
          stack.push({ source: descriptor.value, depth: depth + 1, parent: entry, key, target: copy });
        }
      } else {
        throw fail(pathOf(entry), "is not plain data (an object of a class, a typed array, a date ...)");
      }
    } else {
      throw fail(pathOf(entry), `is not plain data (${typeof source})`);
    }
    if (entry.target === null) result = copy;
    else entry.target[entry.key] = copy;
  }
  for (const container of containers) Object.freeze(container);
  return result;
}

// ---- the shape ------------------------------------------------------------------------------------------------------------------

const isObject = (value) => typeof value === "object" && value !== null && !Array.isArray(value);
const isNumber = (value) => typeof value === "number";
const isWhole = (value) => typeof value === "number" && Number.isInteger(value);

function needObject(value, where) {
  if (!isObject(value)) throw fail(where, "must be an object");
  return value;
}

function needList(value, where, { min = 0, exactly } = {}) {
  if (!Array.isArray(value)) throw fail(where, "must be a list");
  if (exactly !== undefined && value.length !== exactly) throw fail(where, `must have ${exactly} entries`);
  if (value.length < min) throw fail(where, min === 1 ? "must not be empty" : `must have at least ${min} entries`);
  return value;
}

function needText(value, where) {
  if (typeof value !== "string" || value.length === 0) throw fail(where, "must be a text that is not empty");
  return value;
}

function needNumber(value, where, { min } = {}) {
  if (!isNumber(value)) throw fail(where, "must be a number");
  if (min !== undefined && value < min) throw fail(where, `must be at least ${min}`);
  return value;
}

function needWhole(value, where, min) {
  if (!isWhole(value)) throw fail(where, "must be a whole number");
  if (value < min) throw fail(where, `must be at least ${min}`);
  return value;
}

function needBoolean(value, where) {
  if (typeof value !== "boolean") throw fail(where, "must be true or false");
  return value;
}

/** An object with exactly these fields. */
function needFields(value, fields, where) {
  needObject(value, where);
  const have = new Set(Object.keys(value));
  for (const field of fields) if (!have.has(field)) throw fail(where, `has no ${field}`);
  if (have.size !== fields.length) {
    const want = new Set(fields);
    for (const field of have) if (!want.has(field)) throw fail(where, `has a field (${safeName(field)}) that it should not have`);
  }
  return value;
}

/** A list of different texts, none empty. */
function needNames(value, where, { min = 1, within } = {}) {
  needList(value, where, { min });
  const seen = new Set();
  for (const name of value) {
    if (typeof name !== "string" || name.length === 0 || name.length > 64) throw fail(where, "must hold texts that are not empty");
    if (FORBIDDEN_KEYS.has(name)) throw fail(where, `names ${safeName(name)}, which could poison a lookup (the names become the keys of objects)`);
    if (seen.has(name)) throw fail(where, `names ${safeName(name)} twice`);
    if (within !== undefined && !within.has(name)) throw fail(where, `names ${safeName(name)}, which there is none of`);
    seen.add(name);
  }
  return seen;
}

/** A "p/q" text read: every one costs a reduction, so a document holds only LIMITS.maxRationals of them. RationalError for a text that is not one. */
function readRational(text, context, where) {
  context.rationals += 1;
  if (context.rationals > LIMITS.maxRationals) throw fail(where, `is one exact number too many: a bundle holds at most ${LIMITS.maxRationals}`);
  return Rational.parse(text);
}

/** A number that Profile.to_dict() writes for a pool: a number, or a "p/q" text when a float could not carry it. */
function needPoolNumber(value, where, context) {
  if (isNumber(value)) return;
  if (typeof value === "string") {
    try {
      readRational(value, context, where);
      return;
    } catch (error) {
      if (!(error instanceof RationalError)) throw error;
    }
  }
  throw fail(where, "must be a number");
}

const RATIONAL_LIKE = /^[0-9+.\/-]+$/;
const CLASS_CODE = /^[A-Z]{3}$/;

/**
 * In an exact block every number is a reduced p/q text: no bare number, and a text made of digits and slashes must be one. A text is looked at
 * for no more than the longest rational (`MAX_TEXT_LENGTH`) and a character, so one that begins like a number and goes on for longer is refused
 * as one, and no text is scanned to its end whatever its length.
 */
function checkExact(root, where, context) {
  const stack = [[root, where]];
  while (stack.length > 0) {
    const [node, path] = stack.pop();
    if (typeof node === "number") throw fail(path, "is a bare number, where every exact number is a reduced p/q text");
    if (typeof node === "string") {
      if (node.includes("/") && RATIONAL_LIKE.test(node.length > MAX_TEXT_LENGTH ? node.slice(0, MAX_TEXT_LENGTH + 1) : node)) {
        try {
          readRational(node, context, path);
        } catch (error) {
          if (error instanceof RationalError) throw fail(path, "is not a reduced rational p/q (a zero denominator, not in lowest terms, or a stray sign or point)");
          throw error;
        }
      }
    } else if (Array.isArray(node)) {
      for (let index = 0; index < node.length; index += 1) stack.push([node[index], `${path}[${index}]`]);
    } else if (node !== null && typeof node === "object") {
      for (const key of Object.keys(node)) stack.push([node[key], `${path}.${safeName(key)}`]);
    }
  }
}

function checkCommon(common, bundle, context) {
  const where = "bundle.profile_common";
  needFields(common, COMMON_FIELDS, where);
  if (common.format !== BUNDLE_VERSION) throw fail(`${where}.format`, `must be ${BUNDLE_VERSION}`);
  if (JSON.stringify(common.trio) !== JSON.stringify(bundle.trio)) throw fail(`${where}.trio`, "must be the trio of the bundle");
  if (common.level !== bundle.level) throw fail(`${where}.level`, "must be the level of the bundle");
  if (typeof common.evidence !== "string" || !context.levels.has(common.evidence)) throw fail(`${where}.evidence`, "must be one of the evidence levels of the bundle");
  const aa = needFields(common.aa, ["combat_stability", "natural_durability", "physical_enhancement"], `${where}.aa`);
  needWhole(aa.combat_stability, `${where}.aa.combat_stability`, 0);
  needWhole(aa.natural_durability, `${where}.aa.natural_durability`, 0);
  needBoolean(aa.physical_enhancement, `${where}.aa.physical_enhancement`);
  for (const field of ["haste_cap", "cs_pct", "pe_pct", "defense_cap", "dw_factor"]) needNumber(common[field], `${where}.${field}`);
  needNumber(common.haste_bonus, `${where}.haste_bonus`, { min: 0 });
  // Natural Durability: the percent it adds to the HP that comes from STA. It is already in the `fac` of the HP pools below (the evaluator and the builder read the pools), so it is only checked here
  needNumber(common.nd_pct, `${where}.nd_pct`, { min: 0 });
  needList(common.softcap, `${where}.softcap`, { exactly: 2 }).forEach((value, index) => needNumber(value, `${where}.softcap[${index}]`));
  if (common.monk !== null) {
    needObject(common.monk, `${where}.monk`);
    for (const [key, value] of Object.entries(common.monk)) needNumber(value, `${where}.monk.${safeName(key)}`);
  }
  const placement = needFields(common.placement, ["iksar", "monk"], `${where}.placement`);
  for (const key of ["iksar", "monk"]) {
    if (placement[key] !== "top" && placement[key] !== "inside") throw fail(`${where}.placement.${key}`, 'must be "top" or "inside"');
  }
  const pools = needFields(common.pools, ["END", "HP", "MANA"], `${where}.pools`);
  for (const family of ["END", "HP", "MANA"]) {
    needList(pools[family], `${where}.pools.${family}`).forEach((pool, index) => {
      const at = `${where}.pools.${family}[${index}]`;
      needFields(pool, family === "MANA" ? MANA_POOL_FIELDS : POOL_FIELDS, at);
      needText(pool.cls, `${at}.cls`);
      needPoolNumber(pool.base, `${at}.base`, context);
      needPoolNumber(pool.fac, `${at}.fac`, context);
      if (family === "MANA") needText(pool.stat, `${at}.stat`);
    });
  }
  const caps = needFields(common.caps, ["regen", "resist"], `${where}.caps`);
  needNumber(caps.resist, `${where}.caps.resist`);
  const regen = needFields(caps.regen, ["END", "HP", "MANA"], `${where}.caps.regen`);
  for (const family of ["END", "HP", "MANA"]) needNumber(regen[family], `${where}.caps.regen.${family}`);
  if (common.bands !== null) {
    const bands = needFields(common.bands, ["breaks", "slopes"], `${where}.bands`);
    needList(bands.breaks, `${where}.bands.breaks`).forEach((value) => needNumber(value, `${where}.bands.breaks`));
    needList(bands.slopes, `${where}.bands.slopes`).forEach((value) => needNumber(value, `${where}.bands.slopes`));
  }
  if (common.deity !== null && (typeof common.deity !== "string" || isBlank(common.deity))) throw fail(`${where}.deity`, "must be null or a name");
}

function checkRaces(races, context) {
  needList(races, "bundle.races", { min: 1 });
  const rows = new Map();
  races.forEach((row, index) => {
    const at = `bundle.races[${index}]`;
    needFields(row, RACE_ROW_FIELDS, at);
    const code = needText(row.code, `${at}.code`);
    if (rows.has(code)) throw fail(at, `has the code ${safeName(code)} again`);
    needText(row.name, `${at}.name`);
    needBoolean(row.legal, `${at}.legal`);
    const naked = needFields(row.naked, context.attributes, `${at}.naked`);
    for (const attribute of context.attributes) needNumber(naked[attribute], `${at}.naked.${attribute}`);
    needNumber(row.iksar_ac, `${at}.iksar_ac`);
    rows.set(code, row);
  });
  return rows;
}

function checkRoles(roles, context) {
  needObject(roles, "bundle.roles");
  const rows = new Map();
  for (const role of Object.keys(roles)) {
    const at = `bundle.roles.${safeName(role)}`;
    if (!ROLES.includes(role)) throw fail("bundle.roles", `names a role (${safeName(role)}) that there is none of`);
    const row = needFields(roles[role], ROLE_ROW_FIELDS, at);
    const weights = needObject(row.weights, `${at}.weights`);
    for (const key of Object.keys(weights)) {
      if (!context.weightKeys.has(key)) throw fail(`${at}.weights`, `has a weight (${safeName(key)}) that the evaluator does not read`);
      needNumber(weights[key], `${at}.weights.${safeName(key)}`, { min: 0 });
    }
    needNames(row.setups, `${at}.setups`, { within: context.setups });
    const byLevel = needObject(row.setups_by_evidence, `${at}.setups_by_evidence`);
    const given = Object.keys(byLevel);
    if (given.length !== context.levels.size || given.some((level) => !context.levels.has(level))) {
      throw fail(`${at}.setups_by_evidence`, "must have one list for each evidence level of the bundle, and no other");
    }
    for (const level of given) needNames(byLevel[level], `${at}.setups_by_evidence.${safeName(level)}`, { within: context.setups });
    rows.set(role, row);
  }
  if (rows.size === 0) throw fail("bundle.roles", "must not be empty");
  return rows;
}

function checkBuffs(buffs, context) {
  needObject(buffs, "bundle.buffs");
  const rows = new Map();
  for (const key of Object.keys(buffs)) {
    const at = `bundle.buffs.${safeName(key)}`;
    if (key.length === 0 || key.length > 32) throw fail("bundle.buffs", "has a key of an odd length");
    const row = needFields(buffs[key], BUFF_ROW_FIELDS, at);
    const totals = needObject(row.buff_totals, `${at}.buff_totals`);
    for (const name of Object.keys(totals)) {
      if (!context.buffTotalKeys.has(name)) throw fail(`${at}.buff_totals`, `has a total (${safeName(name)}) that there is none of`);
      if (name === "SV") {
        const schools = needObject(totals.SV, `${at}.buff_totals.SV`);
        for (const school of Object.keys(schools)) {
          if (!context.schools.has(school)) throw fail(`${at}.buff_totals.SV`, `has a school (${safeName(school)}) that there is none of`);
          needNumber(schools[school], `${at}.buff_totals.SV.${safeName(school)}`);
        }
      } else {
        needNumber(totals[name], `${at}.buff_totals.${safeName(name)}`);
      }
    }
    needNumber(row.spell_haste, `${at}.spell_haste`, { min: 0 });
    const set = needFields(row.set, SET_FIELDS, `${at}.set`);
    for (const field of ["always_on", "optional", "conflicts", "cliques", "dropped"]) needList(set[field], `${at}.set.${field}`);
    if (set.cardinality !== null) needWhole(set.cardinality, `${at}.set.cardinality`, 0);
    rows.set(key, row);
  }
  if (rows.size === 0) throw fail("bundle.buffs", "must not be empty");
  return rows;
}

/**
 * The buff table: an object by spell id, each entry an object whose `vec` names components of the bundle and holds whole numbers. The
 * always-on buffs of a set are added up in exact numbers here and as floats in Python (0.1 + 0.2 is 0.30000000000000004): the two agree for
 * whole numbers, which is all the client files give, so a fraction in the table is refused.
 */
function checkBuffTable(table, components) {
  needObject(table, "bundle.buff_table");
  for (const [id, entry] of Object.entries(table)) {
    const at = `bundle.buff_table.${safeName(id)}`;
    needObject(entry, at);
    const vec = needObject(entry.vec, `${at}.vec`);
    for (const [name, amount] of Object.entries(vec)) {
      if (!components.has(name)) throw fail(`${at}.vec`, `has a component (${safeName(name)}) that there is none of`);
      if (!isWhole(amount)) throw fail(`${at}.vec.${name}`, "must be a whole number");
    }
  }
}

// ---- reading ----------------------------------------------------------------------------------------------------------------------

/** The bundles that `readBundle` made, each with the lookups the ports use. */
const READ = new WeakMap();

function check(bundle) {
  needObject(bundle, "bundle");
  const version = bundle.version;
  if (version !== BUNDLE_VERSION) {
    throw fail("bundle.version", version === undefined ? `is missing; this reader takes version ${BUNDLE_VERSION}` : `is another version; this reader takes version ${BUNDLE_VERSION}`);
  }
  const fingerprinted = Object.prototype.hasOwnProperty.call(bundle, "inputs");
  needFields(bundle, fingerprinted ? [...TOP_FIELDS, "inputs"] : TOP_FIELDS, "bundle");
  if (fingerprinted && !(typeof bundle.inputs === "string" && FINGERPRINT.test(bundle.inputs))) {
    throw fail("bundle.inputs", "must be a fingerprint: 64 lower-case hexadecimal digits");
  }
  if (bundle.data_release !== null) needText(bundle.data_release, "bundle.data_release");
  needText(bundle.rules_version, "bundle.rules_version");
  const trio = needList(bundle.trio, "bundle.trio", { exactly: 3 });
  trio.forEach((code) => {
    if (typeof code !== "string" || !CLASS_CODE.test(code)) throw fail("bundle.trio", "must hold class codes of three capital letters");
  });
  if (new Set(trio).size !== 3) throw fail("bundle.trio", "must hold three different classes");
  needWhole(bundle.level, "bundle.level", 1);
  const levels = needNames(bundle.evidence_levels, "bundle.evidence_levels");

  const constants = needObject(bundle.constants, "bundle.constants");
  const context = {
    levels,
    attributes: [...needNames(constants.attributes, "bundle.constants.attributes")],
    schools: needNames(constants.schools, "bundle.constants.schools"),
    weightKeys: needNames(constants.weight_keys, "bundle.constants.weight_keys"),
    buffTotalKeys: needNames(constants.buff_total_keys, "bundle.constants.buff_total_keys"),
    components: needNames(constants.buff_components, "bundle.constants.buff_components"),
    setups: needNames(constants.weapon_setups, "bundle.constants.weapon_setups"),
    rationals: 0, // the "p/q" texts read so far
  };
  checkCommon(bundle.profile_common, bundle, context);
  const races = checkRaces(bundle.races, context);
  const roles = checkRoles(bundle.roles, context);
  const buffs = checkBuffs(bundle.buffs, context);
  checkBuffTable(bundle.buff_table, context.components);
  if (bundle.monk_bins !== null) needObject(bundle.monk_bins, "bundle.monk_bins");
  for (const block of ["tier_rules", "weapon_rules", "weight_groups", "regen_ratios"]) needObject(bundle[block], `bundle.${block}`);
  for (const block of EXACT_BLOCKS) if (bundle[block] !== null) checkExact(bundle[block], `bundle.${block}`, context);
  return { races, roles, buffs, levels };
}

/**
 * The bundle, checked and copied: a document nothing can change, which is what the other ports take. A bundle that this function made is
 * returned as it is (it is read once); anything else is read from the start. A BundleError for a document that is not what the exporter writes.
 */
export function readBundle(bundle) {
  if (typeof bundle === "object" && bundle !== null && READ.has(bundle)) return bundle;
  const copy = copyPlain(bundle);
  const index = check(copy);
  READ.set(copy, index);
  return copy;
}

// ---- assembling ---------------------------------------------------------------------------------------------------------------------

/** Python's str.strip() takes these (and only these) for blank: a deity made of them is no name. */
function isBlank(text) {
  for (let i = 0; i < text.length; i += 1) {
    const code = text.charCodeAt(i);
    const space =
      (code >= 0x09 && code <= 0x0d) || (code >= 0x1c && code <= 0x20) || code === 0x85 || code === 0xa0 || code === 0x1680 ||
      (code >= 0x2000 && code <= 0x200a) || code === 0x2028 || code === 0x2029 || code === 0x202f || code === 0x205f || code === 0x3000;
    if (!space) return false;
  }
  return true;
}

function describeChoice(value) {
  if (typeof value !== "string") return typeof value;
  return JSON.stringify(value.length > 40 ? `${value.slice(0, 40)}...` : value);
}

function someNames(names) {
  const list = [...names];
  return list.length > 20 ? `${list.slice(0, 20).join(", ")} ...` : list.join(", ");
}

/**
 * Profile.to_dict() of the race, role and buff key (and the evidence level and deity, when given), put together from the bundle: the common part,
 * the race part, the role part and the buff part, in the field order of the profile, frozen all through. Without an `evidence` level the
 * profile has the evidence of the common part and the `setups` of the role; with one it carries the label and the setups of that level.
 */
export function assembleProfile(bundle, choices) {
  const read = readBundle(bundle);
  const index = READ.get(read);
  if (!isObject(choices)) throw new BundleError("the choices are an object with a race, a role and a buff key");
  for (const key of Object.keys(choices)) {
    if (!CHOICE_KEYS.has(key)) throw new BundleError(`the choices have a choice (${safeName(key)}) that there is none of (they are race, role, buffs, evidence and deity)`);
  }
  const { race, role, buffs, evidence, deity } = choices;
  const raceRow = typeof race === "string" ? index.races.get(race) : undefined;
  if (raceRow === undefined) throw new ChoiceError(`race ${describeChoice(race)} is not in the bundle (it has ${someNames(index.races.keys())})`);
  const roleRow = typeof role === "string" ? index.roles.get(role) : undefined;
  if (roleRow === undefined) throw new ChoiceError(`role ${describeChoice(role)} is not offered to this trio (its roles are ${someNames(index.roles.keys())})`);
  const buffRow = typeof buffs === "string" ? index.buffs.get(buffs) : undefined;
  if (buffRow === undefined) throw new ChoiceError(`buffs ${describeChoice(buffs)} is not a buff set of the bundle (use ${someNames(index.buffs.keys())})`);
  const withEvidence = evidence !== undefined && evidence !== null;
  if (withEvidence && (typeof evidence !== "string" || !index.levels.has(evidence))) {
    throw new ChoiceError(`evidence ${describeChoice(evidence)} is not one of ${someNames(index.levels)}`);
  }
  const withDeity = deity !== undefined && deity !== null;
  if (withDeity && (typeof deity !== "string" || isBlank(deity))) throw new ChoiceError("deity is null or a name, not blank or anything else");

  const parts = new Map([
    ["race", raceRow.code],
    ["naked", raceRow.naked],
    ["iksar_ac", raceRow.iksar_ac],
    ["role", role],
    ["weights", roleRow.weights],
    ["setups", withEvidence ? roleRow.setups_by_evidence[evidence] : roleRow.setups],
    ["buff_totals", buffRow.buff_totals],
    ["spell_haste", buffRow.spell_haste],
  ]);
  if (withEvidence) parts.set("evidence", evidence);
  if (withDeity) parts.set("deity", deity);
  const profile = {};
  for (const field of PROFILE_FIELDS) profile[field] = parts.has(field) ? parts.get(field) : read.profile_common[field];
  return Object.freeze(profile);
}
