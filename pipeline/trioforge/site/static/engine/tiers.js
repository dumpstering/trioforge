// The tier rules of the Upgrade tab: the tier a candidate is scored at, and what bringing an item to a tier costs. A port of
// pipeline/trioforge/model/tiers.py, held to the tables Python writes (items/tiers.json of the parity fixtures) by tests-js/engine-tiers.test.mjs.
//
// Where an item arrives (`arrivalTier`): the item table says how it gets its tier (`tier_rule`): a `drop` arrives at the difficulty of the
// instance, +0 to +4 (`D`); `fixed0` (a quest reward, a crafted or a vendor item) arrives at +0; `spell` (a summoned item) arrives at the rank
// of its spell, which is not known yet, so it counts as +0.
//
// The tier a candidate is scored at (`tierForMode`), by the visitor's tier mode: `ready4` is +4 for every item; `arrives` is the arrival tier
// above, with D from 0 to 4; `fixed` is +N for every item, N from 0 to 10.
//
// What reaching a tier costs (`costToReach`): tier N needs 2^N - 1 experience in all, an item at tier M holds 2^M - 1, and a copy that arrives
// at +k gives 2^k. So going from `from` to `to` needs 2^to - 2^from experience and `copies_at_arrival` arriving copies (at least) supply it;
// `potentials` is how many Void-touched Potentials would do it alone, one tier each.
//
// The constants are those of the bundle's `tier_rules` (max_tier, max_fresh_drop, tier_rule_values); a test compares them. All of it is
// whole-number arithmetic on small integers.

/** A tier rule, mode, tier or difficulty that is not one of the allowed. */
export class TierError extends Error {
  constructor(message) {
    super(message);
    this.name = "TierError";
  }
}

export const TIER_RULES = Object.freeze(["drop", "fixed0", "spell"]);
export const MODES = Object.freeze(["ready4", "arrives", "fixed"]);
export const MAX_TIER = 10;
/** The highest tier a fresh drop has been seen at (`tier.max_fresh_drop`). */
export const MAX_DIFFICULTY = 4;
/** The tier of the mode `ready4`. */
export const READY_TIER = 4;

function whole(value, name, low, high) {
  if (typeof value !== "number" || !Number.isInteger(value)) throw new TierError(`${name} must be a whole number from ${low} to ${high}`);
  if (value < low || value > high) throw new TierError(`${name} must be a whole number from ${low} to ${high}, not ${value}`);
  return value;
}

/** A name from the caller, safe to put in a message: short, and only letters, digits and a few signs. */
function safe(name) {
  if (typeof name !== "string" || name.length === 0 || name.length > 32) return "?";
  for (let i = 0; i < name.length; i += 1) {
    const code = name.charCodeAt(i);
    if (!((code >= 0x30 && code <= 0x39) || (code >= 0x41 && code <= 0x5a) || (code >= 0x61 && code <= 0x7a) || code === 0x5f || code === 0x2d || code === 0x2e)) return "?";
  }
  return name;
}

/**
 * The options of a call: an object, or none. `known` are the options the call reads: any other key is a TierError, since a misspelt D or N
 * would be ignored and the call would answer as if it had not been given.
 */
function optionsOf(options, call, known) {
  if (options === undefined || options === null) return {};
  if (typeof options !== "object" || Array.isArray(options)) throw new TierError("the options are an object, such as {D: 2}");
  for (const key of Object.keys(options)) {
    if (!known.includes(key)) throw new TierError(`the options have an option (${safe(key)}) that ${call} does not read (it reads ${known.join(" and ")})`);
  }
  return options;
}

/** The tier rule of an item record, of an object with a `tier_rule`, or of the rule itself. */
function ruleOf(item) {
  let rule = item;
  if (typeof item === "object" && item !== null) rule = Array.isArray(item) ? undefined : item.tier_rule;
  if (typeof rule !== "string" || !TIER_RULES.includes(rule)) throw new TierError(`the tier rule is one of ${TIER_RULES.join(", ")}`);
  return rule;
}

/** The tier an item arrives at: +D for a drop, +0 for `fixed0` and `spell` (no rank is known yet). */
export function arrivalTier(item, D = MAX_DIFFICULTY) {
  const rule = ruleOf(item);
  const difficulty = whole(D, "D", 0, MAX_DIFFICULTY);
  return rule === "drop" ? difficulty : 0;
}

/**
 * The tier a candidate is scored at under a tier mode. `item` is an item record, an object with a `tier_rule`, or the rule. `D` is the
 * instance difficulty, 0 to 4 (4 unless given), checked in every mode; `N` is the tier of `fixed` mode, 0 to 10, required there and
 * ignored in the others. A TierError for an unknown mode or rule, for a number out of range or not whole, and for an option it does not read (a misspelt D or N).
 */
export function tierForMode(item, mode, options) {
  const { D = MAX_DIFFICULTY, N } = optionsOf(options, "tierForMode", ["D", "N"]);
  const rule = ruleOf(item);
  const difficulty = whole(D, "D", 0, MAX_DIFFICULTY);
  if (typeof mode !== "string" || !MODES.includes(mode)) throw new TierError(`the tier mode is one of ${MODES.join(", ")}`);
  if (mode === "ready4") return READY_TIER;
  if (mode === "arrives") return rule === "drop" ? difficulty : 0;
  if (N === undefined || N === null) throw new TierError("the fixed tier mode needs N, the tier (0 to 10)");
  return whole(N, "N", 0, MAX_TIER);
}

/**
 * What it takes to bring an item from `fromTier` to `toTier`: `{exp, copies_at_arrival, potentials}`. `exp` is 2^to - 2^from; `copies_at_arrival`
 * the fewest copies that arrive at the item's arrival tier (`arrivalTier`, with D) whose experience adds up to it; `potentials` the Void-touched
 * Potentials that would do it alone, to - from. A tier already reached costs nothing; a lower one is a TierError, as is a tier outside 0 to 10 or
 * a difficulty outside 0 to 4, or an option it does not read (it reads D alone).
 */
export function costToReach(item, fromTier, toTier, options) {
  const { D = MAX_DIFFICULTY } = optionsOf(options, "costToReach", ["D"]);
  const arrives = arrivalTier(item, D);
  const start = whole(fromTier, "from_tier", 0, MAX_TIER);
  const stop = whole(toTier, "to_tier", 0, MAX_TIER);
  if (stop < start) throw new TierError(`an item cannot be brought down from +${start} to +${stop}`);
  const need = (1 << stop) - (1 << start);
  // the copies are the experience over 2^arrives, rounded up: a shift takes the quotient of a power of two
  return Object.freeze({ exp: need, copies_at_arrival: (need + (1 << arrives) - 1) >> arrives, potentials: stop - start });
}
