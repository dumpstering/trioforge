// The weights of a role under the sliders, the custom weights and the regen window: a port of `weights_override` in
// pipeline/trioforge/model/roles.py, held to the doubles Python wrote (tests-js/engine-weights.test.mjs).
//
// `weightsOverride(rules, baseWeights, {multipliers, custom, regenT, manaReachable})` is the one definition of how the sliders, the custom weights
// and the regen window compose. All of it is exact arithmetic on the decimals the weights are written as (a double is read as the decimal it
// prints as, `Rational.fromNumber`), rounded once to a double at the end (`Rational.toNumber`, the nearest, ties to even): that is what Python
// does with Fractions and float(), so the doubles are the same ones, bit for bit. There is no floating-point arithmetic to keep in order.
//
//   1. The weight in effect. For each settable weight (HP AC MANA ATK DEX HASTE END CHA, SV which sets the five schools, and a school of its own,
//      which beats SV) it is the custom value when there is one, else the role's own.
//   2. Derived weights follow. DMG is the role's own DMG times (ATK in effect / the role's own ATK): 600 times the ATK weight for Tank and
//      Melee, 0 for Caster and the other builds that score no weapon (see roles.weapon_factor). A regen weight is ticks a minute x T x the weight in effect of the resource
//      it returns (HP, MANA, END); when `regenT` is none, or within the tolerance of the T the role's weights were made with, the role's own
//      regen weight is kept to the last digit and only follows the resource weight in effect.
//   3. The sliders come last. A slider (x0.5, x1, x2) multiplies every weight of its group, derived ones included. The MANA slider scales MANA
//      only, and the regen slider scales the regen weights only.
//   4. Reachable currencies only. MANA and MANAREG are 0 for a trio with no mana pool, whatever else is asked.
//
// The constants (the groups, the positions, the settable weights, the bounds, the ticks a minute, the tolerance of the role's own window)
// are not in this file: they are read from the bundle (`weight_groups`, `regen_ratios`, `constants`) and checked once for each bundle that
// `readBundle` made. The result is a new frozen object of doubles with the keys of the base in their order, then the custom weights the base
// lacks, sorted.

import { BundleError, readBundle } from "./profile.js";
import { isPlainObject as isTable } from "./protocol.js";
import { ONE, Rational, RationalError, ZERO } from "./rational.js";

/** A base, a slider, a custom weight, a window or a flag that is not allowed. */
export class WeightsError extends Error {
  constructor(message) {
    super(message);
    this.name = "WeightsError";
  }
}

/** The largest base weight, in HP-equivalents a point (`Fraction(10**15)` in roles.py: the exactness proofs of the solver need it finite). */
const BASE_MAX = new Rational(10n ** 15n);
const DAMAGE_KEY = "DMG";
const ATTACK_GROUP = "ATK+HASTE";
const REGEN_GROUP = "regen";
const SV_KEY = "SV";
const MANA_KEY = "MANA";
/** The options `weightsOverride` reads; any other key of the options is a misspelling that would change nothing and look right. */
const OPTION_KEYS = new Set(["multipliers", "custom", "regenT", "manaReachable"]);

// ---- the rules ----------------------------------------------------------------------------------------------------------------------

const COMPILED = new WeakMap();

const unsafe = (name) => (typeof name === "string" && name.length > 0 && name.length <= 32 ? name : "?");

function rational(text, where, { min, positive = false } = {}) {
  let value;
  try {
    value = Rational.parse(text);
  } catch (error) {
    if (error instanceof RationalError) throw new BundleError(`${where} is not a rational p/q`);
    throw error;
  }
  if (positive && value.sign() <= 0) throw new BundleError(`${where} must be above zero`);
  if (min !== undefined && value.compare(min) < 0) throw new BundleError(`${where} must be at least ${min.toString()}`);
  return value;
}

function plainObject(value, where) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new BundleError(`${where} must be an object`);
  return value;
}

/** A list of different names of weights. */
function weightNames(value, where, weightKeys) {
  if (!Array.isArray(value)) throw new BundleError(`${where} must be a list`);
  const seen = new Set();
  for (const name of value) {
    if (typeof name !== "string" || !weightKeys.has(name)) throw new BundleError(`${where} names ${unsafe(name)}, which is not a weight`);
    if (seen.has(name)) throw new BundleError(`${where} names ${unsafe(name)} twice`);
    seen.add(name);
  }
  return seen;
}

function compile(bundle) {
  const rules = plainObject(bundle.weight_groups, "bundle.weight_groups");
  const regen = plainObject(bundle.regen_ratios, "bundle.regen_ratios");
  const weightKeys = new Set(bundle.constants.weight_keys);
  const schools = [...bundle.constants.schools];

  const groups = new Map();
  const groupOf = new Map();
  for (const [name, keys] of Object.entries(plainObject(rules.groups, "bundle.weight_groups.groups"))) {
    groups.set(name, weightNames(keys, `bundle.weight_groups.groups.${unsafe(name)}`, weightKeys));
    for (const key of groups.get(name)) {
      if (groupOf.has(key)) throw new BundleError(`bundle.weight_groups.groups puts ${unsafe(key)} in two groups`);
      groupOf.set(key, name);
    }
  }
  for (const needed of [ATTACK_GROUP, REGEN_GROUP]) {
    if (!groups.has(needed)) throw new BundleError(`bundle.weight_groups.groups has no ${needed} group`);
  }

  if (!Array.isArray(rules.multipliers) || rules.multipliers.length === 0) throw new BundleError("bundle.weight_groups.multipliers must be a list of slider positions");
  const positions = rules.multipliers.map((text) => rational(text, "bundle.weight_groups.multipliers", { min: ZERO }));
  if (!positions.some((position) => position.equals(ONE))) throw new BundleError("bundle.weight_groups.multipliers must have the position 1");

  const customKeys = weightNames(rules.custom_keys, "bundle.weight_groups.custom_keys", weightKeys);
  if (!customKeys.has(SV_KEY)) throw new BundleError("bundle.weight_groups.custom_keys must have SV");
  const derived = weightNames(rules.derived, "bundle.weight_groups.derived", weightKeys);
  if (!derived.has(DAMAGE_KEY)) throw new BundleError(`bundle.weight_groups.derived must have ${DAMAGE_KEY}`);
  const damageFollows = rules.damage_follows;
  if (typeof damageFollows !== "string" || !weightKeys.has(damageFollows)) throw new BundleError("bundle.weight_groups.damage_follows must be a weight");
  const regenSources = [];
  for (const [regenKey, resource] of Object.entries(plainObject(rules.regen_sources, "bundle.weight_groups.regen_sources"))) {
    if (!weightKeys.has(regenKey) || typeof resource !== "string" || !weightKeys.has(resource)) {
      throw new BundleError("bundle.weight_groups.regen_sources must name weights");
    }
    if (!derived.has(regenKey)) throw new BundleError(`bundle.weight_groups.derived must have ${unsafe(regenKey)}`);
    regenSources.push([regenKey, resource]);
  }
  const manaKeys = [...weightNames(rules.mana_keys, "bundle.weight_groups.mana_keys", weightKeys)];

  const customMax = rational(rules.custom_max, "bundle.weight_groups.custom_max", { min: ZERO });
  const regenTMax = rational(rules.regen_t_max, "bundle.weight_groups.regen_t_max", { min: ZERO });
  const maxMinutes = rational(regen.max_minutes, "bundle.regen_ratios.max_minutes", { min: ZERO });
  if (!maxMinutes.equals(regenTMax)) throw new BundleError("bundle.regen_ratios.max_minutes and bundle.weight_groups.regen_t_max must be the same");
  const defaultMinutes = rational(regen.default_minutes, "bundle.regen_ratios.default_minutes", { min: ZERO });
  if (defaultMinutes.compare(regenTMax) > 0) throw new BundleError("bundle.regen_ratios.default_minutes must not be above the longest window");

  return Object.freeze({
    weightKeys,
    schools,
    groups,
    groupOf,
    groupNames: [...groups.keys()],
    positions,
    customKeys,
    derived,
    damageFollows,
    regenSources,
    manaKeys,
    customMax,
    regenTMax,
    ticks: rational(regen.ticks_per_minute, "bundle.regen_ratios.ticks_per_minute", { positive: true }),
    match: rational(regen.match, "bundle.regen_ratios.match", { min: ZERO }),
  });
}

function weightRules(rules) {
  const bundle = readBundle(rules);
  let compiled = COMPILED.get(bundle);
  if (compiled === undefined) {
    compiled = compile(bundle);
    COMPILED.set(bundle, compiled);
  }
  return compiled;
}

// ---- the arguments ------------------------------------------------------------------------------------------------------------------

/** The value as an exact rational when it is a finite number (a double, read as the decimal it prints as) or a Rational from `low` to `high`, else null. */
function inRange(value, low, high) {
  let number;
  if (value instanceof Rational) number = value;
  else if (typeof value === "number" && Number.isFinite(value)) number = Rational.fromNumber(value);
  else return null;
  return number.compare(low) >= 0 && number.compare(high) <= 0 ? number : null;
}

const describe = (value) => (typeof value === "string" ? JSON.stringify(value.length > 24 ? `${value.slice(0, 24)}...` : value) : typeof value === "number" ? String(value) : typeof value);

/**
 * The weights after the sliders, the custom weights and the regen window, composed as the head of this file says.
 *
 * `rules` is the bundle. `baseWeights` are the role's weights (a profile's `weights`): a table of known, non-negative numbers. `multipliers` maps a
 * slider group to one of its positions (a group left out is x1). `custom` maps a settable weight (or SV) to a weight from 0 to the maximum. `regenT`
 * is the regen window in minutes, from 0 to the longest, or none for the role's own. `manaReachable` says whether the trio has a mana pool; none
 * reads it from the base (a trio with no mana pool has a MANA of 0). A WeightsError for a base that is not a table of known non-negative numbers,
 * a slider group that does not exist, a multiplier that is not one of the positions, a custom weight that is not settable or out of range, an option it does not read (a misspelt regenT) and a
 * window out of range; a BundleError for a bundle that is not one or whose weight rules do not fit together.
 */
export function weightsOverride(rules, baseWeights, options) {
  const rule = weightRules(rules);
  if (options !== undefined && options !== null && !isTable(options)) throw new WeightsError("the options are an object with multipliers, custom, regenT and manaReachable");
  for (const key of Object.keys(options ?? {})) {
    if (!OPTION_KEYS.has(key)) {
      throw new WeightsError(`the options have an option (${unsafe(key)}) that weightsOverride does not read (it reads multipliers, custom, regenT and manaReachable)`);
    }
  }
  const { multipliers, custom, regenT, manaReachable } = options ?? {};
  if (manaReachable !== undefined && manaReachable !== null && typeof manaReachable !== "boolean") throw new WeightsError("manaReachable is true, false or none");

  if (!isTable(baseWeights)) throw new WeightsError("base weights must be a table of weights by name");
  const base = new Map();
  for (const [key, value] of Object.entries(baseWeights)) {
    const number = inRange(value, ZERO, BASE_MAX);
    if (!rule.weightKeys.has(key) || number === null) throw new WeightsError(`base weights hold a name or a value that is not a weight: ${describe(key)}`);
    base.set(key, number);
  }

  const sliders = new Map(rule.groupNames.map((name) => [name, ONE]));
  if (multipliers !== undefined && multipliers !== null) {
    if (!isTable(multipliers)) throw new WeightsError("multipliers must be a table of slider positions by group");
    for (const [group, value] of Object.entries(multipliers)) {
      if (!rule.groups.has(group)) throw new WeightsError(`unknown slider group ${describe(group)}; the groups are ${rule.groupNames.join(", ")}`);
      const position = inRange(value, ZERO, rule.positions.reduce((high, next) => (next.compare(high) > 0 ? next : high)));
      if (position === null || !rule.positions.some((allowed) => allowed.equals(position))) {
        throw new WeightsError(`the multiplier for ${group} must be one of ${rule.positions.map((allowed) => allowed.toNumber()).join(", ")}, not ${describe(value)}`);
      }
      sliders.set(group, position);
    }
  }

  const values = new Map();
  if (custom !== undefined && custom !== null) {
    if (!isTable(custom)) throw new WeightsError("custom must be a table of weights by name");
    for (const [key, value] of Object.entries(custom)) {
      if (!rule.customKeys.has(key)) throw new WeightsError(`custom weight ${describe(key)} cannot be set; use ${[...rule.customKeys].join(", ")}`);
      const number = inRange(value, ZERO, rule.customMax);
      if (number === null) throw new WeightsError(`custom weight ${key} must be a number from 0 to ${rule.customMax.toNumber()}, not ${describe(value)}`);
      values.set(key, number);
    }
  }

  let minutes = null;
  if (regenT !== undefined && regenT !== null) {
    minutes = inRange(regenT, ZERO, rule.regenTMax);
    if (minutes === null) throw new WeightsError(`regenT must be a number of minutes from 0 to ${rule.regenTMax.toNumber()}, not ${describe(regenT)}`);
  }

  // 1. the weight in effect: the custom value when there is one (a school of its own beats SV), else the role's own
  const effective = new Map(base);
  if (values.has(SV_KEY)) {
    for (const school of rule.schools) effective.set(`${SV_KEY}_${school}`, values.get(SV_KEY));
    if (base.has(SV_KEY)) effective.set(SV_KEY, values.get(SV_KEY));
  }
  for (const [key, number] of values) if (key !== SV_KEY) effective.set(key, number);

  // 3. the sliders, the last multiplication, on the weights in effect
  const result = new Map();
  for (const [key, number] of effective) {
    if (rule.derived.has(key)) continue;
    const group = rule.groupOf.get(key);
    result.set(key, group === undefined ? number : number.mul(sliders.get(group)));
  }

  // 2. the derived weights follow the weights in effect, then their sliders
  if (base.has(DAMAGE_KEY)) {
    const ownAttack = base.get(rule.damageFollows) ?? ZERO;
    const follows = ownAttack.sign() > 0 ? (effective.get(rule.damageFollows) ?? ZERO).div(ownAttack) : ONE;
    result.set(DAMAGE_KEY, base.get(DAMAGE_KEY).mul(follows).mul(sliders.get(ATTACK_GROUP)));
  }
  for (const [regen, resource] of rule.regenSources) {
    if (!base.has(regen)) continue;
    const own = base.get(regen);
    const ownResource = base.get(resource) ?? ZERO;
    const ownWindow = minutes === null || (own.sign() > 0 && rule.ticks.mul(minutes).mul(ownResource).sub(own).abs().compare(own.mul(rule.match)) <= 0);
    const inEffect = effective.get(resource) ?? ZERO;
    let value;
    if (ownWindow) value = ownResource.sign() > 0 ? own.mul(inEffect).div(ownResource) : own;
    else value = rule.ticks.mul(minutes).mul(inEffect);
    result.set(regen, value.mul(sliders.get(REGEN_GROUP)));
  }

  // 4. a currency the trio cannot reach has no weight
  const reachable = manaReachable === undefined || manaReachable === null ? (base.get(MANA_KEY) ?? ZERO).sign() > 0 : manaReachable;
  if (!reachable) for (const key of rule.manaKeys) if (result.has(key)) result.set(key, ZERO);

  const added = [...result.keys()].filter((key) => !base.has(key)).sort();
  const out = {};
  for (const key of [...base.keys(), ...added]) if (result.has(key)) out[key] = result.get(key).toNumber();
  return Object.freeze(out);
}
