// The weapon procs of a trio, as the weapon term counts them: the port of pipeline/trioforge/model/procs.py (its module docstring has the rules in words).
//
//   readProcs(doc, trio) -> ProcTable | null     the `procs` block of a bundle (null: no proc is worth anything to the trio); the block is the one to_doc of procs.py writes (the exporter's tests hold it to that, and the bundle is checked by its SHA-256)
//   table.best(primary, secondary, factor, worn) -> {primary, secondary}   the proc each hand counts: an entry {value, effect, name, donor, mode}, or null
//
// A proc adds `DMG x value / 600` to the weapon part of the hand that swings it, with no haste factor. Below the socket tier an item counts its own best proc only; at or above it the best of its own
// and the ones it can host. Two hands that both count a proc need two distinct physical copies to supply them (a Lore item is one copy, any other item two), and a Lore item that the kit wears
// anywhere is no donor for a hand it is not in (`worn`: the keys of the Lore items the kit wears; the two hands' own items count as worn). The values are Rationals, as the evaluator's are.
// Items are those `atTier` gives, or as the model reads them (`key`, `slots`, `classes`, `tier`; a list or a Set).
//
// This file is what the evaluator of a shared kit needs, and nothing more (its size is held to a budget): the lists the builder and the pruning compare are in model.js (`procCandidates`).
// `best` looks through the procs of each hand best first and stops at the first pair that nothing can beat, which is the best pair of Python's too (`ProcTable.best` does the same).

import { BundleError } from "./profile.js";
import { Rational, ZERO } from "./rational.js";

/** A minute is 600 tenths of a second: `procs a minute x damage / 600` is damage per tenth of a second, the unit of the weapon index. */
export const PER_MINUTE_TO_INDEX = new Rational(600n);
const NO_KEYS = new Set();
const byText = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const holds = (list, value) => (list instanceof Set ? list.has(value) : list.includes(value)); // (the slots and the classes of an item are a list or a Set)
const READ = new WeakMap();

/** The table of a `procs` block, and null for a null block. */
export function readProcs(doc, trio) {
  if (doc === null || doc === undefined) return null;
  if (!READ.has(doc)) READ.set(doc, made(doc, trio));
  return READ.get(doc);
}

/** The table of procs of a bundle (read once), or null for a bundle with none. */
export function procsOf(bundle) {
  return readProcs(bundle.procs, bundle.trio);
}

const refuse = (what) => new BundleError(`procs: ${what}`);
const flag = (value) => value === 0 || value === 1;
const texts = (list) => Array.isArray(list) && list.every((one) => typeof one === "string");
/** The value of an effect: a reduced p/q text above zero, as `from_doc` of procs.py takes it (`Rational.parse` refuses the rest of it, with an error that is not the engine's, so it is made one). */
function valued(text) {
  try {
    const value = Rational.parse(text);
    if (value.sign() > 0) return value;
  } catch {
    // (a RationalError: refused below, as an error of the bundle)
  }
  throw refuse("the value of an effect is a reduced p/q text above zero");
}

/** The table of a block, after the look at its shape that `from_doc` of procs.py takes (the exporter's tests hold the rest): what is not that is a BundleError, a bad request of the data, not a fault of the worker. */
function made(doc, trio) {
  const { socket_tier: tier, effects, donors } = doc !== null && typeof doc === "object" && !Array.isArray(doc) && Object.keys(doc).length === 3 ? doc : {};
  if (!Number.isInteger(tier) || tier < 0 || !Array.isArray(effects) || !Array.isArray(donors)) throw refuse("an object with a socket tier (a whole number), effects and donors (lists), and no more");
  for (const row of effects) if (!Array.isArray(row) || row.length !== 3 || !row.every((cell) => typeof cell === "string")) throw refuse("an effect is [id, name, value], three texts");
  const ids = new Set(effects.map((row) => row[0]));
  if (ids.size !== effects.length) throw refuse("an effect is in the table twice");
  for (const row of donors) {
    if (!Array.isArray(row) || row.length !== 6 || typeof row[1] !== "string" || !ids.has(row[0]) || !texts(row[2]) || !texts(row[3]) || !flag(row[4]) || !flag(row[5])) {
      throw refuse("a donor is [effect, key, slots, classes, primary only, lore] of an effect of the table, the slots and classes lists of texts, the two flags 0 or 1");
    }
  }
  return new ProcTable(
    trio,
    tier,
    effects.map(([id, name, value]) => ({ id, name, value: valued(value) })),
    donors.map(([effect, key, slots, classes, primaryOnly, lore]) => ({ effect, key, slots: new Set(slots), classes: new Set(classes), primaryOnly: primaryOnly === 1, lore: lore === 1 })),
  );
}

export class ProcTable {
  constructor(trio, socketTier, effects, donors) {
    this.trio = [...trio];
    this.socketTier = socketTier;
    this.effects = [...effects].sort((a, b) => byText(a.id, b.id));
    this.donorsOf = new Map();
    this.own = new Map(); // item key -> the ids of the effects it carries itself (its own procs: the copy that is worn)
    this.loreKeys = new Set(); // the keys of the donors that are Lore items: one copy, which a kit that wears it cannot also give as a donor (any other item has two copies)
    for (const donor of donors) {
      this.donorsOf.set(donor.effect, [...(this.donorsOf.get(donor.effect) ?? []), donor]);
      this.own.set(donor.key, new Set([...(this.own.get(donor.key) ?? []), donor.effect]));
      if (donor.lore) this.loreKeys.add(donor.key);
    }
    this.memo = new WeakMap(); // by item: what the table says of it in each hand (an item at a tier is one object)
  }

  /** The ids of the effects the item itself carries. */
  natives(item) {
    return this.own.get(item.key) ?? NO_KEYS;
  }

  /** What the table remembers of an item in a hand (the lists are made once). */
  cell(item, hand) {
    if (!this.memo.has(item)) this.memo.set(item, { PRIMARY: {}, SECONDARY: {} });
    return this.memo.get(item)[hand];
  }

  /** The keys of the donors of `effect` that `item` can host in `hand` (a donor of its slot and its classes, the primary hand only for a donor that fits only there), but for a Lore one in `worn`. */
  donorKeys(item, hand, effect, worn = NO_KEYS) {
    const keys = (this.donorsOf.get(effect) ?? [])
      .filter((donor) => !(donor.lore && worn.has(donor.key)) && (!donor.primaryOnly || (hand === "PRIMARY" && holds(item.slots, "PRIMARY"))))
      .filter((donor) => [...item.slots].some((slot) => donor.slots.has(slot)) && this.trio.some((code) => donor.classes.has(code) && holds(item.classes, code)))
      .map((donor) => donor.key);
    return [...new Set(keys)].sort(byText);
  }

  /** Every proc `item` can count in `hand`, best first, whatever the kit wears (its own procs; from the socket tier also the procs it can host from a donor, the donor with the smallest key named). */
  every(item, hand) {
    const cell = this.cell(item, hand);
    if (cell.every === undefined) {
      cell.every = [];
      for (const effect of this.effects) {
        const keys = item.tier >= this.socketTier ? this.donorKeys(item, hand, effect.id) : [];
        const entry = { value: effect.value, effect: effect.id, name: effect.name, donor: this.natives(item).has(effect.id) ? item.key : keys[0], mode: this.natives(item).has(effect.id) ? "n" : "h" };
        if (entry.donor !== undefined) cell.every.push(entry);
      }
      cell.every.sort((a, b) => b.value.compare(a.value) || byText(a.donor, b.donor) || byText(a.effect, b.effect));
    }
    return cell.every;
  }

  /** The item keys whose copy can supply `effect` to `item` in `hand`: the item's own key alone for its own proc, else the keys of the donors it can host that are not a worn Lore item. */
  sources(item, hand, effect, worn = NO_KEYS) {
    if (this.natives(item).has(effect)) return [item.key];
    return item.tier >= this.socketTier ? this.donorKeys(item, hand, effect, worn) : [];
  }

  /**
   * The proc each hand counts, `{primary, secondary}` (an entry or null): `primary` and `secondary` are the items that swing in the two hands (null: the hand swings nothing), `factor` the off
   * hand's share (a Rational), `worn` the keys of the Lore items the kit wears anywhere. The best pair by `value + factor x value` among the procs of the two hands that their sources allow,
   * where two hands that both count a proc need two distinct copies to supply them; the first of equal pairs wins.
   */
  best(primary, secondary, factor, worn = NO_KEYS) {
    const blocked = new Set([...worn, primary?.key, secondary?.key].filter((key) => this.loreKeys.has(key)));
    const listed = (item, hand) => (item ? this.every(item, hand).filter((entry) => this.sources(item, hand, entry.effect, blocked).length > 0) : []);
    const off = listed(secondary, "SECONDARY");
    let best = null;
    let top = null;
    for (const a of [...listed(primary, "PRIMARY"), null]) {
      for (const b of [...off, null]) {
        const total = (a ? a.value : ZERO).add(b ? factor.mul(b.value) : ZERO);
        if (top !== null && total.compare(top) <= 0) break; // (the procs of the off hand come best first: no later one makes more)
        let given = [a ? this.sources(primary, "PRIMARY", a.effect, blocked)[0] : null, b ? this.sources(secondary, "SECONDARY", b.effect, blocked)[0] : null]; // (the first source the kit leaves free)
        if (a && b) {
          given = null;
          for (const mine of this.sources(primary, "PRIMARY", a.effect, blocked)) {
            for (const theirs of this.sources(secondary, "SECONDARY", b.effect, blocked)) given ??= mine !== theirs || !this.loreKeys.has(mine) ? [mine, theirs] : null;
          }
          if (given === null) continue;
        }
        top = total;
        best = {
          primary: a && { ...a, donor: given[0], mode: given[0] === primary.key ? "n" : "h" },
          secondary: b && { ...b, donor: given[1], mode: given[1] === secondary.key ? "n" : "h" },
        };
      }
    }
    return best;
  }
}
