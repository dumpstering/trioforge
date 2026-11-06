// The exact value of a kit: a port of `evaluate` in pipeline/trioforge/model/formulas.py on BigInt rationals (rational.js), held to the breakdowns
// that Python wrote (tests-js/engine-evaluate.test.mjs: the parity fixtures, and one test per term).
//
//   evaluate(profile, kit, buffsChosen, {setup, hasteAssumed, monkBins, buffset}) -> {F, breakdown}
//
//   profile      what `assembleProfile` gives, Profile.to_dict(): the fields the evaluator reads are `level`, `naked`, `weights`, `pools`,
//                `buff_totals`, `haste_cap`, `softcap`, `cs_pct`, `pe_pct`, `defense_cap`, `monk`, `iksar_ac`, `placement`, `caps`, `bands` and
//                `dw_factor`; the others are not looked at.
//   kit          a list of the 22 places of SLOT_INSTANCES, each null or an item as `atTier` gives it (the fields read are `key`, `stats`, `sv`,
//                `haste`, `weight10`, `weapon` and `is_shield`; `stats` and `sv` hold whole numbers).
//   buffsChosen  null (or undefined): the buffs of the profile, the always-on ones. Else the ids of the optional buffs that are on, which
//                needs `options.buffset`: the totals are then those of the always-on buffs of the set plus the chosen ones, which take the place
//                of `profile.buff_totals` (formulas.evaluate takes totals in that place, `BuffSet.totals(chosen)`). An id twice counts once,
//                an id that is always on is already counted, and an id that is not in the set is an error. The set must be the profile's:
//                its always-on buffs must give exactly `profile.buff_totals` (so a choice is a choice on top of the buffs the profile has),
//                or it is an error.
//   options      `setup` (null, "1h-shield", "2h", "dw" or "stick": which hands score weapon damage), `hasteAssumed` (the haste percent the
//                weapon index assumes: a number, or a Rational), `monkBins` (the `monk_bins` block of the bundle; needed when the profile has
//                a Monk curve) and `buffset` (`{set, table}` as the bundle writes them: `bundle.buffs[key].set` and `bundle.buff_table`, or the
//                `buffset` of a fixture profile).
//
// The result is {F, breakdown}: F is a Rational (`F.toNumber()` is for display), and `breakdown` has exactly the fields of Python's
// `Breakdown`: F, `parts` (the 14 parts of PART_NAMES) and `totals` (attributes, pools, counted, end_average, sheet, haste, regen, resists,
// weight10, atk), every number a Rational and the classes whose pools count lists of class codes. `JSON.stringify` writes the Rationals as the
// "p/q" texts that the fixtures hold. Everything in it is frozen.
//
// Exactness. Every number that decides something is a whole number or a Rational: the knees and caps, the softcap and its floor, which pools
// count, the Monk bonus, Iksar. The only doubles are the plain JSON numbers of the profile that Python itself holds as floats (a softcap
// rate such as 0.33, a pool factor such as 4.4, a band slope such as 2.5, a weight such as 0.05, the dual-wield factor) and `hasteAssumed`
// when it is not whole: each is read once, as the decimal it prints as (`Rational.fromNumber`, which is Python's `fr`), and never again
// computed with. A whole number past 2^53 - 1 in the profile is refused (Python holds the double's own value, and the decimal it prints as
// is another number), as the bundle reader refuses it. The sums over the kit are sums of whole numbers, in doubles that stay exact because
// an item's number is held to 2^40 (22 of them cannot reach 2^53), then handed to BigInt. The Monk bonus is not computed: Python's `monk_bonus` is float arithmetic that exact
// fractions do not reproduce, so the bundle carries its result for every whole stone of worn weight (`monk_bins`, a reduced "p/q" each), and
// the bonus here is the bin of the whole stones of the worn weight, the last bin for a weight beyond the table (by then the penalty has
// stopped growing: a table runs from stone 0 to the hardcap and MONK_STONES_PAST_HARDCAP stones more, 90 of which the penalty needs, and a
// table of any other length is refused). The bins are matched to the profile's curve (and to its alternative, `full_until_stones`) and to its
// level.
//
// The constants are those of the formulas module (CONSTANTS), which the bundle exports as `constants`: the tests hold them to each other.
// A profile that is deeply frozen, as `assembleProfile` gives it, is read once and remembered; any other is read at each call. The same goes
// for the Monk bins and the buff set. Lookups of a name from the data go through a Map or a Set, never through an object. A list that is given
// is read whole: a hole in one (the bins, the alternatives, the bands, the pools, the ids of a buff set) is an EvaluateError, since `map` and
// `forEach` would step over it.
//
// The MILP builder (model.js) reads from here what it shares with the evaluator, as Python's builder does: the profile (`profileOf`), the Monk
// bonus of every whole stone of worn weight (`monkTable`, the table that `evaluate` looks the bonus of a kit up in), the constants (CONSTANTS) and
// the units they are counted in (UNITS: a percent, and the tenths of a stone of a weight), so that its source holds no number but 0 and 1.

import { ONE, Rational, RationalError, ZERO } from "./rational.js";

/** A profile, a kit, a choice of buffs or an option that is not what the evaluator reads. */
export class EvaluateError extends Error {
  constructor(message) {
    super(message);
    this.name = "EvaluateError";
  }
}

// ---- the constants of the formulas module ---------------------------------------------------------------------------------------------

const q = (numerator, denominator = 1n) => new Rational(numerator, denominator);
const names = (...items) => Object.freeze(items);
const curve = (breaks, slopes) => Object.freeze({ breaks: Object.freeze(breaks), slopes: Object.freeze(slopes) });

const ATTRIBUTES = names("STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA");
const SCHOOLS = names("FIRE", "COLD", "MAGIC", "POISON", "DISEASE");
/** The components of the buff totals, in the order of the buff engine; the first fifteen are the stats an item can carry. */
const COMPONENTS = names(
  "AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG", "FIRE", "COLD", "MAGIC", "POISON", "DISEASE", "HASTE",
);
const ITEM_STAT_COUNT = 15;
const SETUPS = names(null, "1h-shield", "2h", "dw", "stick");
const HAND_PLACES = names("PRIMARY", "SECONDARY");
const PLACEMENTS = names("top", "inside");
export const PART_NAMES = names("HP", "MANA", "END", "AC", "EVASION", "ATK", "DEX", "HASTE", "REGEN", "RESISTS", "CHA", "WEAPON", "MONK", "IKSAR");
const WEIGHT_KEYS = names("HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "CHA", "HPREG", "MANAREG", "ENDREG", "DMG", "SV", ...SCHOOLS.map((school) => `SV_${school}`));
const BUFF_KEYS = names(...ATTRIBUTES, "AC", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG", "HASTE", "SV");
const SLOT_GROUPS = names(
  ["HEAD", 1], ["FACE", 1], ["EAR", 2], ["NECK", 1], ["SHOULDERS", 1], ["ARMS", 1], ["BACK", 1], ["WRIST", 2], ["HANDS", 1], ["FINGER", 2], ["CHEST", 1], ["LEGS", 1], ["FEET", 1],
  ["WAIST", 1], ["RANGE", 1], ["ANY", 2], ["PRIMARY", 1], ["SECONDARY", 1],
);
/** The group of each place of a kit, in kit order: `kit[i]` is worn in `SLOT_INSTANCES[i]`. */
export const SLOT_INSTANCES = Object.freeze(SLOT_GROUPS.flatMap(([name, count]) => new Array(count).fill(name)));

/** The module constants of formulas.py, as the bundle exports them in `constants` (camel case), each an exact Rational. */
export const CONSTANTS = Object.freeze({
  attributes: ATTRIBUTES,
  schools: SCHOOLS,
  setups: SETUPS,
  handPlaces: HAND_PLACES,
  placements: PLACEMENTS,
  breakdownParts: PART_NAMES,
  weightKeys: names(...[...WEIGHT_KEYS].sort()),
  buffTotalKeys: names(...[...BUFF_KEYS].sort()),
  itemStats: names(...[...COMPONENTS.slice(0, ITEM_STAT_COUNT)].sort()),
  buffComponents: COMPONENTS,
  slotGroups: names(...SLOT_GROUPS.map(([name, count]) => names(name, q(BigInt(count))))),
  statKnee: q(255n),
  statCap: q(510n),
  hpPoolConstant: q(5n),
  poolsCounted: q(2n),
  staCurve: curve([q(255n), q(510n)], [q(1n), q(1n, 2n), q(0n)]),
  manaBands: curve([q(100n), q(200n), q(510n)], [q(1n), q(5n, 2n), q(5n, 4n), q(0n)]),
  endCurve: curve([q(100n), q(201n)], [q(1n), q(5n, 2n), q(5n, 4n)]),
  strToAtk: q(666667n, 1000000n),
  agiToAc: q(1111n, 5000n),
  dexPastKnee: q(1n, 10n),
  sheet: Object.freeze({ itemMult: q(4n, 3n), defenseDiv: q(3n), spellAcDiv: q(4n), agiDiv: q(20n) }),
  weaponIndex: Object.freeze({ bonusOneHanded: q(1n, 2n), bonusTwoHanded: q(67n, 100n), bonusTwoHandedDelayCap: q(50n) }),
});

const STAT_CAP = CONSTANTS.statCap;
const POOLS_COUNTED = Number(CONSTANTS.poolsCounted.numerator);
/** The cap of a stat on its own (STR for attack, AGI for evasion, CHA): one slope up to the cap, none after. */
const CAPPED = curve([STAT_CAP], [ONE, ZERO]);
/** DEX: a point a point to the knee, a tenth of a point to the cap, none after. */
const DEX_CURVE = curve([CONSTANTS.statKnee, STAT_CAP], [ONE, CONSTANTS.dexPastKnee, ZERO]);
const FOUR = q(4n);
/**
 * The units that the formulas count in, which are not rules of the game: a percent is a hundredth, and the weight of an item (`weight10`) is in
 * tenths of a stone. The builder (model.js) reads them from here, as it reads the constants above, so that its source holds no number.
 */
export const UNITS = Object.freeze({ percent: q(100n), tenthsPerStone: q(10n) });
const HUNDRED = UNITS.percent;
const TENTHS_PER_STONE = Number(UNITS.tenthsPerStone.numerator);

// ---- the vocabulary: positions and sets, looked up through Maps -------------------------------------------------------------------------

const COMPONENT_INDEX = new Map(COMPONENTS.map((name, index) => [name, index]));
const ITEM_STAT_INDEX = new Map(COMPONENTS.slice(0, ITEM_STAT_COUNT).map((name, index) => [name, index]));
/** A resist of an item: the five schools that are scored, and CORRUPTION, which never is (-1). */
const RESIST_INDEX = new Map([...SCHOOLS.map((school) => [school, COMPONENT_INDEX.get(school)]), ["CORRUPTION", -1]]);
const WEIGHT_SET = new Set(WEIGHT_KEYS);
const BUFF_SET = new Set(BUFF_KEYS);
const SCHOOL_SET = new Set(SCHOOLS);
const SETUP_SET = new Set(SETUPS);
const PLACEMENT_SET = new Set(PLACEMENTS);
const OPTION_KEYS = new Set(["setup", "hasteAssumed", "monkBins", "buffset"]);

const PLACES = SLOT_INSTANCES.length;
const PRIMARY = SLOT_INSTANCES.indexOf("PRIMARY");
const SECONDARY = SLOT_INSTANCES.indexOf("SECONDARY");
const HANDS = names(PRIMARY, SECONDARY);
const AC = COMPONENT_INDEX.get("AC");
const HP = COMPONENT_INDEX.get("HP");
const MANA = COMPONENT_INDEX.get("MANA");
const END = COMPONENT_INDEX.get("END");
const ATK = COMPONENT_INDEX.get("ATK");
const HASTE = COMPONENT_INDEX.get("HASTE");
const REGEN = names(COMPONENT_INDEX.get("HPREG"), COMPONENT_INDEX.get("MANAREG"), COMPONENT_INDEX.get("ENDREG"));
const REGEN_FAMILY = names("HP", "MANA", "END");
const REGEN_NAMES = names("HPREG", "MANAREG", "ENDREG");
const ATTRIBUTE_COMPONENT = names(...ATTRIBUTES.map((name) => COMPONENT_INDEX.get(name)));
/** The position of an attribute in ATTRIBUTES, which is the position in the totals of the attributes. */
const at = (name) => ATTRIBUTES.indexOf(name);
const STR = at("STR");
const STA = at("STA");
const AGI = at("AGI");
const DEX = at("DEX");
const WIS = at("WIS");
const INT = at("INT");
const CHA = at("CHA");
/** An item's number is held to this: the sum of 22 of them stays a whole number a double holds exactly. */
const AMOUNT_LIMIT = 2 ** 40;

// ---- reading what is given ---------------------------------------------------------------------------------------------------------------

const isRecord = (value) => typeof value === "object" && value !== null && !Array.isArray(value);

/** A name from the data, safe to put in a message: short, and only letters, digits and a few signs. */
function safe(name) {
  if (typeof name !== "string" || name.length === 0 || name.length > 32) return "?";
  for (let i = 0; i < name.length; i += 1) {
    const code = name.charCodeAt(i);
    if (!((code >= 0x30 && code <= 0x39) || (code >= 0x41 && code <= 0x5a) || (code >= 0x61 && code <= 0x7a) || code === 0x5f || code === 0x2d || code === 0x2e)) return "?";
  }
  return name;
}

function own(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key) ? object[key] : undefined;
}

function record(value, where) {
  if (!isRecord(value)) throw new EvaluateError(`${where} must be an object`);
  return value;
}

/**
 * A list (the caller has checked that it is one) with no hole in it. `map` and `forEach` skip a hole, so a sparse list would pass the checks made
 * with them and fail later on an `undefined` (or never be read at all); `index in list` tells a hole from an entry that is undefined.
 */
function noHoles(list, where) {
  for (let index = 0; index < list.length; index += 1) {
    if (!(index in list)) throw new EvaluateError(`${where}[${index}] is a hole in the list`);
  }
  return list;
}

/**
 * A JSON number as the exact value Python holds it as: a whole number, or the decimal a double prints as. A whole number that a double cannot
 * hold exactly (past 2^53 - 1) is refused, as the bundle reader refuses it: Python would hold the double's own value, and the decimal it prints
 * as is another number.
 */
function number(value, where) {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new EvaluateError(`${where} must be a number`);
  if (Number.isInteger(value)) {
    if (!Number.isSafeInteger(value)) throw new EvaluateError(`${where} is a whole number past 2^53 - 1, which a double does not hold exactly`);
    return new Rational(BigInt(value));
  }
  return Rational.fromNumber(value);
}

function nonNegative(value, where) {
  const result = number(value, where);
  if (result.sign() < 0) throw new EvaluateError(`${where} must not be negative`);
  return result;
}

/** A number of a pool, which Profile.to_dict() writes as "p/q" text when a double could not carry it. */
function poolNumber(value, where) {
  if (typeof value !== "string") return number(value, where);
  try {
    return Rational.parse(value);
  } catch (error) {
    if (error instanceof RationalError) throw new EvaluateError(`${where} must be a number or a reduced p/q text`);
    throw error;
  }
}

function ratioText(value, where) {
  if (typeof value !== "string") throw new EvaluateError(`${where} must be a reduced p/q text`);
  try {
    return Rational.parse(value);
  } catch (error) {
    if (error instanceof RationalError) throw new EvaluateError(`${where} must be a reduced p/q text`);
    throw error;
  }
}

/** Whether a value and everything inside it cannot be changed (a walk with a stack of its own). */
function isDeepFrozen(root) {
  const stack = [root];
  const seen = new Set();
  while (stack.length > 0) {
    const node = stack.pop();
    if (node === null || typeof node !== "object" || seen.has(node)) continue;
    seen.add(node);
    if (!Object.isFrozen(node)) return false;
    for (const key of Object.keys(node)) stack.push(node[key]);
  }
  return true;
}

/** The whole number that a Rational of a whole value holds, as a double: only for table positions (the Monk bins). */
function wholeNumber(value, where) {
  if (!value.isInteger() || value.numerator > 1_000_000_000n || value.numerator < -1_000_000_000n) throw new EvaluateError(`${where} must be a whole number`);
  return Number(value.numerator);
}

const whole = (count) => (count === 0 ? ZERO : new Rational(BigInt(count)));
const smaller = (a, b) => (a.compare(b) <= 0 ? a : b);
const larger = (a, b) => (a.compare(b) >= 0 ? a : b);

// ---- the profile -----------------------------------------------------------------------------------------------------------------------

const PROFILES = new WeakMap();

function validBands(raw, where) {
  const bands = record(raw, where);
  if (!Array.isArray(bands.breaks) || !Array.isArray(bands.slopes)) throw new EvaluateError(`${where} needs a list of breaks and a list of slopes`);
  noHoles(bands.breaks, `${where}.breaks`);
  noHoles(bands.slopes, `${where}.slopes`);
  const breaks = bands.breaks.map((value, index) => number(value, `${where}.breaks[${index}]`));
  const slopes = bands.slopes.map((value, index) => number(value, `${where}.slopes[${index}]`));
  let rising = true;
  for (let i = 1; i < breaks.length; i += 1) rising = rising && breaks[i - 1].compare(breaks[i]) < 0;
  if (slopes.length !== breaks.length + 1 || !rising || slopes.some((slope) => slope.sign() < 0)) {
    throw new EvaluateError(`${where} needs one more slope than breaks, rising breaks and slopes of at least 0`);
  }
  return curve(breaks, slopes);
}

function compilePools(raw, family, { stats }) {
  if (!Array.isArray(raw)) throw new EvaluateError(`profile.pools.${family} must be a list of pools`);
  if (raw.length === 0 && family !== "MANA") throw new EvaluateError(`profile.pools.${family} must not be empty (a trio has HP and END pools)`);
  noHoles(raw, `profile.pools.${family}`);
  return raw.map((entry, index) => {
    const where = `profile.pools.${family}[${index}]`;
    const pool = record(entry, where);
    const cls = own(pool, "cls");
    if (typeof cls !== "string" || cls.length === 0) throw new EvaluateError(`${where}.cls must be the name of a class`);
    const stat = own(pool, "stat");
    if (stat !== undefined && stat !== null && stat !== "WIS" && stat !== "INT") throw new EvaluateError(`${where}.stat must be WIS or INT`);
    if (stats && stat !== "WIS" && stat !== "INT") throw new EvaluateError(`${where}.stat must be WIS or INT (a mana pool names its stat)`);
    const base = poolNumber(own(pool, "base"), `${where}.base`);
    return Object.freeze({ cls, base, base5: base.add(CONSTANTS.hpPoolConstant), fac: poolNumber(own(pool, "fac"), `${where}.fac`), wis: stat === "WIS" });
  });
}

function compileBuffView(raw, where) {
  const totals = record(raw, where);
  const view = new Array(COMPONENTS.length).fill(ZERO);
  for (const key of Object.keys(totals)) {
    if (!BUFF_SET.has(key)) throw new EvaluateError(`${where} has a total (${safe(key)}) that the evaluator does not read`);
    if (key === "SV") {
      const schools = record(totals[key], `${where}.SV`);
      for (const school of Object.keys(schools)) {
        if (!SCHOOL_SET.has(school)) throw new EvaluateError(`${where}.SV has a school (${safe(school)}) that the evaluator does not read`);
        view[COMPONENT_INDEX.get(school)] = number(schools[school], `${where}.SV.${school}`);
      }
    } else {
      view[COMPONENT_INDEX.get(key)] = number(totals[key], `${where}.${key}`);
    }
  }
  return view;
}

/** The full Monk bonus of a level: int(4 x (level + 5) / 3), the quotient of whole numbers (Python's `_full_monk_bonus`). */
const fullMonkBonus = (level) => (4n * (BigInt(level) + 5n)) / 3n;

function compileProfile(raw) {
  if (!isRecord(raw)) throw new EvaluateError("profile must be an object (what assembleProfile gives)");
  const level = own(raw, "level");
  if (typeof level !== "number" || !Number.isSafeInteger(level) || level < 1) throw new EvaluateError("profile.level must be a whole number of at least 1");

  const nakedRaw = record(own(raw, "naked"), "profile.naked");
  const naked = ATTRIBUTES.map((name) => number(own(nakedRaw, name), `profile.naked.${name}`));

  const weightsRaw = record(own(raw, "weights"), "profile.weights");
  const weights = new Map();
  for (const key of Object.keys(weightsRaw)) {
    if (!WEIGHT_SET.has(key)) throw new EvaluateError(`profile.weights has a weight (${safe(key)}) that the evaluator does not read`);
    weights.set(key, nonNegative(weightsRaw[key], `profile.weights.${key}`));
  }
  const weight = (key) => weights.get(key) ?? ZERO;

  const poolsRaw = record(own(raw, "pools"), "profile.pools");
  const pools = Object.freeze({
    HP: Object.freeze(compilePools(own(poolsRaw, "HP"), "HP", { stats: false })),
    MANA: Object.freeze(compilePools(own(poolsRaw, "MANA"), "MANA", { stats: true })),
    END: Object.freeze(compilePools(own(poolsRaw, "END"), "END", { stats: false })),
  });

  const buff = compileBuffView(own(raw, "buff_totals"), "profile.buff_totals");
  const hasteCap = nonNegative(own(raw, "haste_cap"), "profile.haste_cap");

  const softcapRaw = own(raw, "softcap");
  if (!Array.isArray(softcapRaw) || softcapRaw.length !== 2) throw new EvaluateError("profile.softcap must be a pair, the cap and the rate past it");
  const softcap = nonNegative(softcapRaw[0], "profile.softcap[0]");
  const rate = number(softcapRaw[1], "profile.softcap[1]");
  if (rate.sign() < 0 || rate.compare(ONE) > 0) throw new EvaluateError("profile.softcap[1], the rate past the softcap, must be from 0 to 1");
  const csPct = nonNegative(own(raw, "cs_pct"), "profile.cs_pct");
  const pePct = nonNegative(own(raw, "pe_pct"), "profile.pe_pct");
  const defenseCap = nonNegative(own(raw, "defense_cap"), "profile.defense_cap");
  const iksarAc = nonNegative(own(raw, "iksar_ac"), "profile.iksar_ac");
  const dwFactor = nonNegative(own(raw, "dw_factor"), "profile.dw_factor");
  // the flat haste of Unbound Alacrity (10 with a Monk in the trio); a profile written without it has none
  const hasteBonus = own(raw, "haste_bonus") === undefined ? ZERO : nonNegative(own(raw, "haste_bonus"), "profile.haste_bonus");

  const monkRaw = own(raw, "monk");
  let monk = null;
  if (monkRaw === undefined) throw new EvaluateError("profile.monk must be null or the Monk curve");
  if (monkRaw !== null) {
    record(monkRaw, "profile.monk");
    const soft = number(own(monkRaw, "softcap_stones"), "profile.monk.softcap_stones");
    const hard = number(own(monkRaw, "hardcap_stones"), "profile.monk.hardcap_stones");
    const fullRaw = own(monkRaw, "full_bonus_ac");
    const untilRaw = own(monkRaw, "full_until_stones");
    const full = fullRaw === undefined ? null : number(fullRaw, "profile.monk.full_bonus_ac");
    const until = untilRaw === undefined ? null : number(untilRaw, "profile.monk.full_until_stones");
    if (full !== null && !full.equals(q(fullMonkBonus(level)))) {
      throw new EvaluateError(`profile.monk.full_bonus_ac is ${full.toString()}, but level ${level} gives ${fullMonkBonus(level)}`);
    }
    monk = Object.freeze({ soft, hard, full, until });
  }

  const placementRaw = record(own(raw, "placement"), "profile.placement");
  const placementKeys = Object.keys(placementRaw);
  if (placementKeys.length !== 2 || !placementKeys.includes("monk") || !placementKeys.includes("iksar")) {
    throw new EvaluateError('profile.placement must say "top" or "inside" for monk and iksar, and for nothing else');
  }
  for (const key of placementKeys) {
    if (!PLACEMENT_SET.has(placementRaw[key])) throw new EvaluateError(`profile.placement.${key} must be "top" or "inside"`);
  }

  const capsRaw = record(own(raw, "caps"), "profile.caps");
  const regenRaw = record(own(capsRaw, "regen"), "profile.caps.regen");
  const regenCaps = REGEN_FAMILY.map((family) => number(own(regenRaw, family), `profile.caps.regen.${family}`));
  const resistCap = number(own(capsRaw, "resist"), "profile.caps.resist");

  const bandsRaw = own(raw, "bands");
  if (bandsRaw === undefined) throw new EvaluateError("profile.bands must be null or the bands of WIS and INT");
  const bands = bandsRaw === null ? CONSTANTS.manaBands : validBands(bandsRaw, "profile.bands");

  const weightAc = weight("AC");
  // frozen all through: the compiled profile is remembered for a frozen profile and shared by every reader of it (the evaluator and the MILP builder), so
  // a list that one of them could assign to would change what the next one reads
  return Object.freeze({
    level,
    naked: Object.freeze(naked),
    pools,
    buff: Object.freeze(buff),
    hasteCap,
    hasteBonus,
    rate,
    otherRate: ONE.sub(rate),
    softcapFloor: q((softcap.mul(HUNDRED.add(csPct).add(pePct)).div(HUNDRED)).floor()), // floor(cap x (100 + cs + pe) / 100)
    defenseTerm: defenseCap.div(CONSTANTS.sheet.defenseDiv),
    iksarAc,
    dwFactor,
    monk,
    monkInside: placementRaw.monk === "inside",
    iksarInside: placementRaw.iksar === "inside",
    regenCaps: Object.freeze(regenCaps),
    resistCap,
    bands,
    weights: Object.freeze({
      HP: weight("HP"),
      MANA: weight("MANA"),
      END: weight("END"),
      AC: weightAc,
      ATK: weight("ATK"),
      DEX: weight("DEX"),
      HASTE: weight("HASTE"),
      CHA: weight("CHA"),
      DMG: weight("DMG"),
      regen: Object.freeze(REGEN_NAMES.map((key) => weight(key))),
      schools: Object.freeze(SCHOOLS.map((school) => (weights.has(`SV_${school}`) ? weights.get(`SV_${school}`) : weight("SV")))),
    }),
    perSheetPoint: weightAc.div(CONSTANTS.sheet.itemMult),
    evasion: weightAc.mul(CONSTANTS.agiToAc),
  });
}

/**
 * The profile as the evaluator reads it (a frozen profile is read once and remembered; any other at each call): the level, the naked attributes,
 * the pools, the buff totals by component, the caps, the weights ... all exact. An EvaluateError for a profile that is not what is read. The MILP
 * builder (model.js) reads the profile with this too, as the Python builder reads it with `compile_profile`. The result is frozen all through, lists
 * and exact numbers included: it is remembered for a profile and shared by every reader of it, so none of them can change what the next one reads.
 */
export function profileOf(profile) {
  if (isRecord(profile)) {
    const known = PROFILES.get(profile);
    if (known !== undefined) return known;
    const compiled = compileProfile(profile);
    if (isDeepFrozen(profile)) PROFILES.set(profile, compiled);
    return compiled;
  }
  return compileProfile(profile);
}

// ---- the Monk bins ---------------------------------------------------------------------------------------------------------------------

const BINS = new WeakMap();

/**
 * How many whole stones the table of Monk bins runs past the hardcap: `monk_bins` of browser.py writes a bin for each whole stone from 0 to the
 * hardcap and this many more (`_MONK_STONES_PAST_HARDCAP`, which a test holds this to). The penalty stops growing 90 stones past the hardcap, so
 * the last bin is the bonus of every weight beyond the table.
 */
export const MONK_STONES_PAST_HARDCAP = 100;

function binTable(curveRaw, bonusRaw, where) {
  const description = record(curveRaw, `${where}.curve`);
  const soft = ratioText(own(description, "softcap_stones"), `${where}.curve.softcap_stones`);
  const hard = ratioText(own(description, "hardcap_stones"), `${where}.curve.hardcap_stones`);
  const full = ratioText(own(description, "full_bonus_ac"), `${where}.curve.full_bonus_ac`);
  const untilRaw = own(description, "full_until_stones");
  const until = untilRaw === undefined ? null : ratioText(untilRaw, `${where}.curve.full_until_stones`);
  if (!Array.isArray(bonusRaw) || bonusRaw.length === 0) throw new EvaluateError(`${where}.bonus must be a list of the bonus of each whole stone`);
  noHoles(bonusRaw, `${where}.bonus`);
  const stones = wholeNumber(hard, `${where}.curve.hardcap_stones`);
  const length = stones + MONK_STONES_PAST_HARDCAP + 1;
  if (bonusRaw.length !== length) {
    throw new EvaluateError(
      `${where}.bonus must have ${length} entries (a bin for each whole stone from 0 to the hardcap, ${stones}, and ${MONK_STONES_PAST_HARDCAP} more), not ${bonusRaw.length}`,
    );
  }
  const table = bonusRaw.map((text, index) => wholeNumber(ratioText(text, `${where}.bonus[${index}]`), `${where}.bonus[${index}]`));
  return Object.freeze({ soft, hard, full, until, table: Object.freeze(table) });
}

function compileBins(raw) {
  const block = record(raw, "options.monkBins");
  const tables = [binTable(own(block, "curve"), own(block, "bonus"), "options.monkBins")];
  const alternatives = own(block, "alternatives");
  if (!Array.isArray(alternatives)) throw new EvaluateError("options.monkBins.alternatives must be a list");
  noHoles(alternatives, "options.monkBins.alternatives");
  alternatives.forEach((alternative, index) => {
    const row = record(alternative, `options.monkBins.alternatives[${index}]`);
    tables.push(binTable(own(row, "curve"), own(row, "bonus"), `options.monkBins.alternatives[${index}]`));
  });
  return Object.freeze(tables);
}

function binsOf(raw) {
  if (isRecord(raw)) {
    const known = BINS.get(raw);
    if (known !== undefined) return known;
    const compiled = compileBins(raw);
    if (isDeepFrozen(raw)) BINS.set(raw, compiled);
    return compiled;
  }
  return compileBins(raw);
}

/**
 * The table of the Monk bonus for the Monk curve and the level of a compiled profile: the bonus (a whole number) of each whole stone of worn weight,
 * from stone 0, read from the `monk_bins` block of a bundle (`raw`; `name` is what an error calls it). The bins are matched to the curve of the
 * profile and to its level. The builder (model.js) reads the bonus of every bin from this.
 */
export function monkTable(profile, raw, name = "options.monkBins") {
  if (raw === undefined || raw === null) throw new EvaluateError(`the profile has a Monk curve, so ${name} (the monk_bins block of the bundle) is needed to read the bonus`);
  const { soft, hard, full, until } = profile.monk;
  let found = null;
  for (const candidate of binsOf(raw)) {
    if (!candidate.soft.equals(soft) || !candidate.hard.equals(hard)) continue;
    if ((candidate.until === null) !== (until === null) || (until !== null && !candidate.until.equals(until))) continue;
    if (full !== null && !candidate.full.equals(full)) continue;
    found = candidate;
    break;
  }
  if (found === null) throw new EvaluateError(`${name} has no bins for the Monk curve of the profile (the softcap, the hardcap and the alternative reading must be the same)`);
  if (!found.full.equals(q(fullMonkBonus(profile.level)))) {
    throw new EvaluateError(`${name} are for another level than ${profile.level} (their full bonus is ${found.full.toString()}, the level's is ${fullMonkBonus(profile.level)})`);
  }
  return found.table;
}

/** The Monk bonus (a whole number) for a worn weight in tenths of a stone: the bin of the whole stones of it. */
function monkBonus(profile, weight10, raw) {
  const table = monkTable(profile, raw);
  const rest = ((weight10 % TENTHS_PER_STONE) + TENTHS_PER_STONE) % TENTHS_PER_STONE; // whole stones, rounded down, for a weight of any sign
  const stones = (weight10 - rest) / TENTHS_PER_STONE;
  return table[stones < 0 ? 0 : stones >= table.length ? table.length - 1 : stones];
}

// ---- the buff set ----------------------------------------------------------------------------------------------------------------------

const BUFFSETS = new WeakMap();

function idList(raw, where) {
  if (!Array.isArray(raw)) throw new EvaluateError(`${where} must be a list of buff ids`);
  noHoles(raw, where);
  raw.forEach((id, index) => {
    if (!Number.isSafeInteger(id)) throw new EvaluateError(`${where}[${index}] must be the id of a buff (a whole number)`);
  });
  return raw;
}

/** The amounts of a buff of the table: `[component, Rational]` for each that it has. */
function buffAmounts(table, id) {
  const entry = table.get(String(id));
  if (entry === undefined) throw new EvaluateError(`the buff set names the buff ${id}, which its table has no entry for`);
  const vec = record(own(record(entry, `options.buffset.table.${id}`), "vec"), `options.buffset.table.${id}.vec`);
  return Object.keys(vec).map((component) => {
    const index = COMPONENT_INDEX.get(component);
    if (index === undefined) throw new EvaluateError(`options.buffset.table.${id}.vec has a component (${safe(component)}) that the evaluator does not read`);
    return [index, number(vec[component], `options.buffset.table.${id}.vec.${component}`)];
  });
}

function compileBuffset(raw) {
  const given = record(raw, "options.buffset");
  const set = record(own(given, "set"), "options.buffset.set");
  const tableRaw = record(own(given, "table"), "options.buffset.table");
  const table = new Map(Object.keys(tableRaw).map((key) => [key, tableRaw[key]]));
  const alwaysOn = idList(own(set, "always_on"), "options.buffset.set.always_on");
  const optional = idList(own(set, "optional"), "options.buffset.set.optional");
  const base = new Array(COMPONENTS.length).fill(ZERO);
  for (const id of alwaysOn) {
    for (const [index, amount] of buffAmounts(table, id)) {
      if (index === HASTE) base[HASTE] = larger(base[HASTE], amount);
      else base[index] = base[index].add(amount);
    }
  }
  const choices = new Map(optional.map((id) => [id, buffAmounts(table, id)]));
  const conflictsRaw = own(set, "conflicts");
  if (!Array.isArray(conflictsRaw)) throw new EvaluateError("options.buffset.set.conflicts must be a list of the pairs of buffs that exclude each other");
  noHoles(conflictsRaw, "options.buffset.set.conflicts");
  const conflicts = conflictsRaw.map((pair, index) => {
    if (!Array.isArray(pair) || pair.length < 2 || !Number.isSafeInteger(pair[0]) || !Number.isSafeInteger(pair[1])) {
      throw new EvaluateError(`options.buffset.set.conflicts[${index}] must be a pair of buff ids`);
    }
    return [pair[0], pair[1]];
  });
  const limit = own(set, "cardinality");
  if (limit !== null && !(Number.isSafeInteger(limit) && limit >= 0)) throw new EvaluateError("options.buffset.set.cardinality must be null or a whole number");
  return Object.freeze({ base, fixed: new Set(alwaysOn), choices, conflicts, limit });
}

function buffsetOf(raw) {
  if (isRecord(raw)) {
    const known = BUFFSETS.get(raw);
    if (known !== undefined) return known;
    const compiled = compileBuffset(raw);
    if (isDeepFrozen(raw)) BUFFSETS.set(raw, compiled);
    return compiled;
  }
  return compileBuffset(raw);
}

/**
 * Whether the always-on buffs of the set are the buffs of the profile: a choice among the optional buffs is a choice on top of the always-on
 * ones, so a set whose always-on buffs give other totals than `profile.buff_totals` would value the kit under buffs the profile never had.
 */
function requireProfilesBuffs(buffset, profile) {
  for (let i = 0; i < COMPONENTS.length; i += 1) {
    if (!buffset.base[i].equals(profile.buff[i])) {
      throw new EvaluateError(
        `options.buffset is not the buff set of the profile: its always-on buffs give ${COMPONENTS[i]} ${buffset.base[i].toString()}, but profile.buff_totals has ${profile.buff[i].toString()}`,
      );
    }
  }
}

/** The buff totals of the always-on buffs of the set and the chosen ones (`BuffSet.totals(chosen)`), the best haste of them and not the sum. */
function chosenTotals(buffset, chosen) {
  const totals = buffset.base.slice();
  const taken = new Set();
  const picked = new Set();
  for (let i = 0; i < chosen.length; i += 1) {
    const id = chosen[i];
    if (!Number.isSafeInteger(id)) throw new EvaluateError(`buffsChosen[${i}] must be the id of a buff (a whole number)`);
    if (taken.has(id)) continue;
    taken.add(id);
    if (buffset.fixed.has(id)) continue;
    const amounts = buffset.choices.get(id);
    if (amounts === undefined) throw new EvaluateError(`buff ${id} is not one of the optional buffs of the set`);
    for (const [index, amount] of amounts) {
      if (index === HASTE) totals[HASTE] = larger(totals[HASTE], amount);
      else totals[index] = totals[index].add(amount);
    }
    picked.add(id);
  }
  if (buffset.limit !== null && picked.size > buffset.limit) {
    throw new EvaluateError(`buffsChosen names ${picked.size} optional buffs, but the buff set allows at most ${buffset.limit}`);
  }
  for (const [a, b] of buffset.conflicts) {
    if (picked.has(a) && picked.has(b)) throw new EvaluateError(`buffsChosen names the buffs ${a} and ${b}, which exclude each other`);
  }
  return totals;
}

// ---- the options -----------------------------------------------------------------------------------------------------------------------

const NO_OPTIONS = Object.freeze({ setup: null, haste: ZERO, monkBins: undefined, buffset: undefined });

function readOptions(options) {
  if (options === undefined || options === null) return NO_OPTIONS;
  if (!isRecord(options)) throw new EvaluateError("options must be an object, such as {setup: 'dw', hasteAssumed: 25}");
  for (const key of Object.keys(options)) {
    if (!OPTION_KEYS.has(key)) throw new EvaluateError(`options has an option (${safe(key)}) that the evaluator does not read (it reads setup, hasteAssumed, monkBins and buffset)`);
  }
  const setup = options.setup === undefined ? null : options.setup;
  if (!SETUP_SET.has(setup)) throw new EvaluateError("options.setup must be null, '1h-shield', '2h', 'dw' or 'stick'");
  let haste = ZERO;
  if (options.hasteAssumed instanceof Rational) haste = options.hasteAssumed;
  else if (options.hasteAssumed !== undefined) haste = number(options.hasteAssumed, "options.hasteAssumed");
  return { setup, haste, monkBins: options.monkBins, buffset: options.buffset === null ? undefined : options.buffset };
}

// ---- the formulas ----------------------------------------------------------------------------------------------------------------------

/** The continuous piecewise-linear value of x from 0 (Python's `pwl`): a slope a band, nothing at or below 0. */
function pwl(x, { breaks, slopes }) {
  let total = ZERO;
  let low = ZERO;
  for (let i = 0; i < breaks.length; i += 1) {
    if (x.compare(low) <= 0) return total;
    total = total.add(slopes[i].mul(smaller(x, breaks[i]).sub(low)));
    low = breaks[i];
  }
  return x.compare(low) > 0 ? total.add(slopes[slopes.length - 1].mul(x.sub(low))) : total;
}

/** The two largest values count, ties in the order given: the pools that count and their sum (Python's `_best`). */
function topPools(pools, values) {
  const order = values.map((_, index) => index).sort((a, b) => values[b].compare(values[a]) || a - b);
  const counted = order.slice(0, POOLS_COUNTED);
  let sum = ZERO;
  for (const index of counted) sum = sum.add(values[index]);
  return { sum, counted: counted.map((index) => pools[index].cls) };
}

/**
 * The damage bonus of a weapon whose page lists none (`weapons._bonus`): half the delay for a one-hander, 0.67 x the delay for a two-hander, the delay counting
 * at most 50 for a two-hander. `delay` is a Rational.
 */
export function fallbackBonus(twoHanded, delay) {
  const { bonusOneHanded, bonusTwoHanded, bonusTwoHandedDelayCap } = CONSTANTS.weaponIndex;
  return twoHanded ? bonusTwoHanded.mul(smaller(delay, bonusTwoHandedDelayCap)) : bonusOneHanded.mul(delay);
}

function weaponIndex(weapon, hand, setup, haste, dwFactor) {
  if (setup === null || setup === "stick" || !(weapon.dmg > 0) || !(weapon.delay > 0)) return ZERO;
  let allowed;
  if (setup === "2h") allowed = hand === PRIMARY && weapon.two_handed;
  else if (setup === "dw") allowed = !weapon.two_handed;
  else allowed = hand === PRIMARY && !weapon.two_handed; // "1h-shield"
  if (!allowed) return ZERO;
  const speed = ONE.add(haste.div(HUNDRED));
  if (hand === SECONDARY) return new Rational(BigInt(weapon.dmg), BigInt(weapon.delay)).mul(speed).mul(dwFactor);
  const bonus = weapon.bonus !== null && weapon.bonus !== 0 ? whole(weapon.bonus) : fallbackBonus(weapon.two_handed, whole(weapon.delay));
  return whole(weapon.dmg).add(bonus).div(weapon.delay).mul(speed);
}

const isAmount = (value) => typeof value === "number" && Number.isSafeInteger(value) && value >= -AMOUNT_LIMIT && value <= AMOUNT_LIMIT;

/** A kit's worth: its sums over the 22 places (whole numbers), the best worn haste, the hands. Throws for an item that is not what is read. */
function readKit(kit) {
  if (!Array.isArray(kit)) throw new EvaluateError("the kit must be a list with one entry for each of the 22 places");
  if (kit.length !== PLACES) throw new EvaluateError(`the kit must have one entry for each of the ${PLACES} places, not ${kit.length}`);
  const gear = new Array(COMPONENTS.length).fill(0);
  let shield = 0;
  let weight10 = 0;
  let bestHaste = 0;
  for (let place = 0; place < PLACES; place += 1) {
    const item = kit[place];
    if (item === null) continue;
    const where = `kit[${place}] (${SLOT_INSTANCES[place]})`;
    if (!isRecord(item)) throw new EvaluateError(`${where} must be an item or null`);
    const label = `${where}, item ${safe(item.key)}`;
    if (typeof item.key !== "string") throw new EvaluateError(`${where}: the item has no key`);
    const stats = item.stats;
    if (!isRecord(stats)) throw new EvaluateError(`${label}: stats must be an object`);
    for (const name of Object.keys(stats)) {
      const index = ITEM_STAT_INDEX.get(name);
      if (index === undefined) {
        const hint = name === "HASTE" ? " (worn haste is the field haste of the item)" : "";
        throw new EvaluateError(`${label}: unknown stat ${safe(name)}${hint}`);
      }
      const amount = stats[name];
      if (!isAmount(amount)) throw new EvaluateError(`${label}: stat ${name} must be a whole number of at most 2^40`);
      if (index === AC && place === SECONDARY && item.is_shield === true) shield += amount;
      else gear[index] += amount;
    }
    const resists = item.sv;
    if (!isRecord(resists)) throw new EvaluateError(`${label}: sv must be an object`);
    for (const name of Object.keys(resists)) {
      const index = RESIST_INDEX.get(name);
      if (index === undefined) throw new EvaluateError(`${label}: unknown resist ${safe(name)}`);
      const amount = resists[name];
      if (!isAmount(amount)) throw new EvaluateError(`${label}: resist ${name} must be a whole number of at most 2^40`);
      if (index >= 0) gear[index] += amount;
    }
    if (!isAmount(item.haste)) throw new EvaluateError(`${label}: haste must be a whole number of at most 2^40`);
    if (!isAmount(item.weight10)) throw new EvaluateError(`${label}: weight10 must be a whole number of at most 2^40`);
    if (typeof item.is_shield !== "boolean") throw new EvaluateError(`${label}: is_shield must be true or false`);
    const weapon = item.weapon;
    if (weapon !== null) {
      if (!isRecord(weapon)) throw new EvaluateError(`${label}: weapon must be null or an object`);
      if (!isAmount(weapon.dmg)) throw new EvaluateError(`${label}: weapon dmg must be a whole number of at most 2^40`);
      if (!isAmount(weapon.delay)) throw new EvaluateError(`${label}: weapon delay must be a whole number of at most 2^40`);
      if (weapon.bonus !== null && !isAmount(weapon.bonus)) throw new EvaluateError(`${label}: weapon bonus must be null or a whole number of at most 2^40`);
      if (typeof weapon.two_handed !== "boolean") throw new EvaluateError(`${label}: weapon two_handed must be true or false`);
    }
    if (item.haste > bestHaste) bestHaste = item.haste;
    weight10 += item.weight10;
  }
  return { gear, shield, weight10, bestHaste };
}

/**
 * The value F of the kit under the profile, and the breakdown of it. See the top of the file for what each argument is. An EvaluateError
 * for anything that is not what is read: the message says which.
 */
export function evaluate(profile, kit, buffsChosen, options) {
  const p = profileOf(profile);
  const { setup, haste: hasteAssumed, monkBins, buffset } = readOptions(options);
  const { gear, shield, weight10, bestHaste } = readKit(kit);

  let buff = p.buff;
  if (buffsChosen !== null && buffsChosen !== undefined) {
    if (!Array.isArray(buffsChosen)) throw new EvaluateError("buffsChosen must be null or a list of the ids of the optional buffs that are on");
    if (buffset !== undefined) {
      const compiled = buffsetOf(buffset);
      requireProfilesBuffs(compiled, p);
      buff = chosenTotals(compiled, buffsChosen);
    } else if (buffsChosen.length > 0) throw new EvaluateError("buffsChosen names buffs, so options.buffset (the buff set to choose from) is needed");
  }

  const w = p.weights;
  // the attribute totals: what the race gives, the buffs and the kit
  const total = ATTRIBUTE_COMPONENT.map((component, index) => p.naked[index].add(buff[component]).add(gear[component]));

  // HP, mana and END: the two largest pools of each count, and flat points are added whole
  const effectiveSta = pwl(total[STA], CONSTANTS.staCurve);
  const hpPools = p.pools.HP;
  const hp = topPools(hpPools, hpPools.map((pool) => pool.base5.add(pool.fac.mul(effectiveSta))));
  const hpTotal = hp.sum.add(gear[HP]).add(buff[HP]);

  const manaPools = p.pools.MANA;
  let manaTotal = ZERO;
  let manaCounted = [];
  if (manaPools.length > 0) {
    const converted = [null, null]; // WIS, INT: each only when a pool reads it
    const read = (isWis) => {
      const slot = isWis ? 0 : 1;
      if (converted[slot] === null) converted[slot] = pwl(isWis ? total[WIS] : total[INT], p.bands);
      return converted[slot];
    };
    const mana = topPools(manaPools, manaPools.map((pool) => pool.base.add(pool.fac.mul(read(pool.wis)))));
    manaTotal = mana.sum.add(gear[MANA]).add(buff[MANA]);
    manaCounted = mana.counted;
  }

  let statSum = ZERO;
  for (const index of [STR, STA, DEX, AGI]) statSum = statSum.add(smaller(total[index], STAT_CAP));
  const endAverage = statSum.div(FOUR);
  const endConverted = pwl(endAverage, CONSTANTS.endCurve);
  const endPools = p.pools.END;
  const end = topPools(endPools, endPools.map((pool) => pool.base.add(pool.fac.mul(endConverted))));
  const endTotal = end.sum.add(gear[END]).add(buff[END]);

  // armor class: the sheet, with the Monk and Iksar bonuses on top of the cap or inside X
  const monk = p.monk === null ? 0 : monkBonus(p, weight10, monkBins);
  const monkValue = whole(monk);
  const insideBonus = (p.monkInside ? monkValue : ZERO).add(p.iksarInside ? p.iksarAc : ZERO);
  const topMonk = p.monkInside ? ZERO : monkValue;
  const topIksar = p.iksarInside ? ZERO : p.iksarAc;
  const sheetConstants = CONSTANTS.sheet;
  const wornAc = whole(gear[AC]);
  const shieldAc = whole(shield);
  const x = sheetConstants.itemMult
    .mul(wornAc.add(shieldAc))
    .add(p.defenseTerm)
    .add(buff[AC].div(sheetConstants.spellAcDiv))
    .add(smaller(total[AGI], STAT_CAP).div(sheetConstants.agiDiv))
    .add(insideBonus);
  const y = p.softcapFloor.add(shieldAc);
  const past = p.rate.mul(x).add(p.otherRate.mul(y));
  const capped = smaller(x, past);

  // the other terms
  const attack = CONSTANTS.strToAtk.mul(pwl(total[STR], CAPPED)).add(gear[ATK]).add(buff[ATK]);
  const spell = buff[HASTE].add(p.hasteBonus); // the spell haste and the flat haste of Unbound Alacrity
  const wornCounted = smaller(whole(bestHaste), larger(ZERO, p.hasteCap.sub(spell)));
  const hasteCounted = smaller(spell, p.hasteCap).add(wornCounted);

  let regenPart = ZERO;
  const regen = {};
  for (let i = 0; i < REGEN.length; i += 1) {
    const carried = gear[REGEN[i]];
    const counted = smaller(whole(carried), p.regenCaps[i]).add(buff[REGEN[i]]);
    regen[REGEN_NAMES[i]] = Object.freeze({ gear: whole(carried), buff: buff[REGEN[i]], counted });
    regenPart = regenPart.add(w.regen[i].mul(counted));
  }
  let resistPart = ZERO;
  const resists = {};
  for (let i = 0; i < SCHOOLS.length; i += 1) {
    const index = COMPONENT_INDEX.get(SCHOOLS[i]);
    const carried = whole(gear[index]);
    const counted = smaller(carried.add(buff[index]), p.resistCap);
    resists[SCHOOLS[i]] = Object.freeze({ gear: carried, buff: buff[index], counted });
    resistPart = resistPart.add(w.schools[i].mul(counted));
  }

  let weaponPart = ZERO;
  for (const hand of HANDS) {
    const item = kit[hand];
    if (item !== null && item.weapon !== null) weaponPart = weaponPart.add(w.DMG.mul(weaponIndex(item.weapon, hand, setup, hasteAssumed, p.dwFactor)));
  }

  const parts = {
    HP: w.HP.mul(hpTotal),
    MANA: w.MANA.mul(manaTotal),
    END: w.END.mul(endTotal),
    AC: p.perSheetPoint.mul(capped),
    EVASION: p.evasion.mul(pwl(total[AGI], CAPPED)),
    ATK: w.ATK.mul(attack),
    DEX: w.DEX.mul(pwl(total[DEX], DEX_CURVE)),
    HASTE: w.HASTE.mul(hasteCounted),
    REGEN: regenPart,
    RESISTS: resistPart,
    CHA: w.CHA.mul(pwl(total[CHA], CAPPED)),
    WEAPON: weaponPart,
    MONK: p.perSheetPoint.mul(topMonk),
    IKSAR: p.perSheetPoint.mul(topIksar),
  };
  let F = ZERO;
  for (const name of PART_NAMES) F = F.add(parts[name]);

  const attributes = {};
  ATTRIBUTES.forEach((name, index) => {
    attributes[name] = total[index];
  });
  const totals = {
    attributes: Object.freeze(attributes),
    pools: Object.freeze({ HP: hpTotal, MANA: manaTotal, END: endTotal }),
    counted: Object.freeze({ HP: Object.freeze(hp.counted), MANA: Object.freeze(manaCounted), END: Object.freeze(end.counted) }),
    end_average: endAverage,
    sheet: Object.freeze({
      worn_ac: wornAc,
      shield_ac: shieldAc,
      X: x,
      Y: y,
      capped,
      monk_bonus: monkValue,
      iksar: p.iksarAc,
      total: capped.add(topMonk).add(topIksar),
    }),
    haste: Object.freeze({ spell, worn_best: whole(bestHaste), worn_counted: wornCounted, counted: hasteCounted }),
    regen: Object.freeze(regen),
    resists: Object.freeze(resists),
    weight10: whole(weight10),
    atk: attack,
  };
  const breakdown = Object.freeze({ F, parts: Object.freeze(parts), totals: Object.freeze(totals) });
  return Object.freeze({ F, breakdown });
}

/**
 * `evaluate` with the weapon index taken at the haste the kit itself counts (`evaluate_truthful` in formulas.py), not at one the caller assumes: the value of a kit as it is.
 * `options.hasteAssumed` is not read here (the kit's own is). A kit that counts no haste, or that scores no weapon, is valued once.
 */
export function evaluateTruthful(profile, kit, buffsChosen, options) {
  const { hasteAssumed, ...rest } = isRecord(options) ? options : {};
  if (hasteAssumed !== undefined) throw new EvaluateError("evaluateTruthful takes no hasteAssumed: the kit's own haste is used");
  const first = evaluate(profile, kit, buffsChosen, rest);
  const counted = first.breakdown.totals.haste.counted;
  if (counted.sign() === 0 || first.breakdown.parts.WEAPON.sign() === 0) return first; // (the index is its value at 0 haste times 1 + haste / 100)
  // nothing but the weapon part depends on the assumed haste, and each weapon's index is its value at 0 haste times 1 + haste / 100 (the same rationals as a second
  // evaluation at the counted haste, which the tests compare), so the kit is not evaluated twice
  const weapon = first.breakdown.parts.WEAPON;
  const scaled = weapon.mul(ONE.add(counted.div(HUNDRED)));
  const F = first.F.sub(weapon).add(scaled);
  const breakdown = Object.freeze({ F, parts: Object.freeze({ ...first.breakdown.parts, WEAPON: scaled }), totals: first.breakdown.totals });
  return Object.freeze({ F, breakdown });
}
