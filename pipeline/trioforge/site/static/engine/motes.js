// The order in which to spend void-touched motes on a kit: a port of `mote_order` in pipeline/trioforge/motes.py, held to the exact fractions Python wrote
// (tests-js/motes.test.mjs, fixtures/site/mote-orders.json).
//
// A void-touched mote raises any one item by one whole tier, at any tier, up to +10, with no limit on the motes one item takes (the rule `tier.void_mote`). The kit is fixed: the same
// items in the same places, only the tiers change. The kit is valued as the page values a kit everywhere (`evaluateTruthful`, the weapons paid the haste the kit counts, the view's
// profile, weapon setup and the optional buffs the kit was made with, all held fixed).
//
// A step is a RUN. A gain can sit more than one mote away on one item (a weapon whose damage rises only every second tier, a haste that counts only once it passes the best worn one), so
// for each worn item below +10 its run is the smallest k from 1 such that raising it k tiers (the rest of the kit as it stands) changes the kit value by more than nothing, and its rate is
// that gain divided by k, exactly; an item that gains at no k has no run. An item whose one-tier gain is not above nothing is the only one looked at past k = 1. A step takes the run with the
// highest rate (of equal rates the shorter run, then the place that comes first in the kit's order) and applies the whole of it: one line of the list, k motes spent. With a limit of motes a run
// longer than the motes left is not eligible. The order ends when every item is at +10 ("top": an empty kit ends so too), when the motes asked for are spent or no eligible run fits in what is
// left ("motes", with `nextRun` the length of the run that did not fit, or null when the limit was reached), or when no item has a run ("no-gain": nothing that is left gains anything, at any
// length). It is greedy: the best run after the runs before it, not a proven best plan.
//
//   createMoteWalk({profile, kit, itemAt, setup, monkBins, buffset, buffs, motes}) -> {start, step(), ending(), left(), spent(), nextRun()}
//       the walk: `kit` the 22 places, each an item as `atTier` gives it (frozen, with its `key` and its `tier`) or null (undefined is taken as null, as Python takes None); `itemAt(key, tier)` the
//       item at another tier (it throws for an item with no record: that is found at the start, as the reference finds it, and is a MoteError); `setup`, `monkBins` and `buffset` the evaluator's
//       options; `buffs` the ids of the optional buffs of the set that the kit is valued with (copied once; given with no buff set, a MoteError); `motes` the limit, or null for every one.
//       `start` is the exact value of the kit before any mote. `step()` works out the next run and gives it as {index (the line, from 1), place, key, from, to, motes (to - from), spent (the motes
//       spent up to and with it), gain (of the whole run), F (the kit after it), moved}, or null when the walk is over; `ending()` is null until then, and "top", "motes" or "no-gain" after;
//       `left()` is how many more motes could be spent (the tiers left under +10, over every item); `spent()` how many were; `nextRun()` is as above
//   collect(walk) -> {start, steps, ending, left, spent, nextRun}  the whole order of a walk, to its end
//
// `moved` is a list of [name, change] pairs: the kit totals the evaluator counts that the step changed (MOVED_ORDER), each by an exact Rational, in that order, and DMG, the damage of
// the item itself when it is a weapon. Every number is exact: a Rational, never a double.

import { SLOT_INSTANCES, evaluateTruthful } from "./evaluate.js";
import { Rational } from "./rational.js";
import { MAX_TIER } from "./tiers.js";

/** Something that is not a kit or a limit the walk can take. */
export class MoteError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = "MoteError";
  }
}

const PLACES = SLOT_INSTANCES.length;
const SCHOOLS = ["FIRE", "COLD", "MAGIC", "POISON", "DISEASE"];
const ATTRIBUTES = ["STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA"];
const REGENS = ["HPREG", "MANAREG", "ENDREG"];
/** The stats a step may move, in the order they are listed (the same as MOVED_ORDER of motes.py): the totals of the evaluator, then the damage of a weapon. */
export const MOVED_ORDER = Object.freeze(["AC", "HP", "MANA", "END", ...ATTRIBUTES, "HASTE", "ATK", ...SCHOOLS, ...REGENS, "DMG"]);

/** The totals the order lists (everything of MOVED_ORDER but the damage of a weapon), as a Map from the name to an exact Rational. */
function totalsOf(totals) {
  const found = new Map([
    ["AC", totals.sheet.total],
    ["HP", totals.pools.HP],
    ["MANA", totals.pools.MANA],
    ["END", totals.pools.END],
    ["HASTE", totals.haste.counted],
    ["ATK", totals.atk],
  ]);
  for (const name of ATTRIBUTES) found.set(name, totals.attributes[name]);
  for (const school of SCHOOLS) found.set(school, totals.resists[school].counted);
  for (const name of REGENS) found.set(name, totals.regen[name].counted);
  return found;
}

function movedOf(before, after, old, raised) {
  const was = totalsOf(before);
  const now = totalsOf(after);
  const moved = [];
  for (const name of MOVED_ORDER) {
    if (!now.has(name)) continue;
    const change = now.get(name).sub(was.get(name));
    if (change.sign() !== 0) moved.push([name, change]);
  }
  if (old.weapon !== null && raised.weapon !== null && raised.weapon.dmg !== old.weapon.dmg) moved.push(["DMG", new Rational(BigInt(raised.weapon.dmg - old.weapon.dmg))]);
  return moved;
}

const times = (count) => new Rational(BigInt(count));

/** Whether run `a` beats run `b`: the higher gain for each mote, of equal rates the shorter run (a tie of both keeps the earlier place, which is the one found first). */
function beats(a, b) {
  const order = a.gain.mul(times(b.k)).compare(b.gain.mul(times(a.k)));
  return order > 0 || (order === 0 && a.k < b.k);
}

/** A place of the kit as the walk takes it: null for an empty place (undefined too), an item that has a key and a tier from 0 to the top otherwise. */
function placeOf(item, at) {
  if (item === undefined || item === null) return null;
  if (typeof item !== "object" || typeof item.key !== "string" || !Number.isInteger(item.tier) || item.tier < 0 || item.tier > MAX_TIER) {
    throw new MoteError(`place ${at} of the kit is not an item with a key and a tier from 0 to ${MAX_TIER}`);
  }
  return item;
}

export function createMoteWalk({ profile, kit, itemAt, setup, monkBins, buffset, buffs = [], motes = null }) {
  if (motes !== null && (!Number.isInteger(motes) || motes < 0)) throw new MoteError(`motes is null or a whole number of at least 0, not ${String(motes)}`);
  if (!Array.isArray(kit) || kit.length !== PLACES) throw new MoteError(`a kit has ${PLACES} places`);
  if (typeof itemAt !== "function") throw new MoteError("itemAt is a function from an item's key and a tier to the item at that tier");
  const slots = Array.from(kit, placeOf);
  const chosen = Array.isArray(buffs) ? [...buffs] : null; // (copied once: the caller's list is its own)
  if (chosen === null) throw new MoteError("buffs is a list of the ids of the optional buffs that are on");
  const hasBuffset = buffset !== null && buffset !== undefined;
  if (chosen.length > 0 && !hasBuffset) throw new MoteError("buffs are chosen from a buffset: none was given");
  // every item of the kit has a record, before anything is valued (the reference checks its records first)
  for (const item of slots) {
    if (item === null) continue;
    try {
      itemAt(item.key, Math.min(item.tier + 1, MAX_TIER));
    } catch (error) {
      throw error instanceof MoteError ? error : new MoteError(`no record for item ${item.key}`, { cause: error });
    }
  }
  const options = { setup, monkBins, buffset: hasBuffset ? buffset : undefined };
  const value = (trial) => evaluateTruthful(profile, trial, hasBuffset ? chosen : null, options);
  let current = value(slots);
  const start = current.F;
  let ended = null;
  let count = 0;
  let spent = 0;
  let nextRun = null;

  const left = () => slots.reduce((total, item) => (item === null ? total : total + (MAX_TIER - item.tier)), 0);

  return {
    start,
    left,
    spent: () => spent,
    ending: () => ended,
    nextRun: () => nextRun,
    step() {
      if (ended !== null) return null;
      if (left() === 0) {
        ended = "top";
        return null;
      }
      if (motes !== null && spent >= motes) {
        ended = "motes";
        return null;
      }
      let best = null; // the best run that fits what is left
      let bestAny = null; // the best run, fitting or not
      for (let place = 0; place < PLACES; place += 1) {
        const item = slots[place];
        if (item === null || item.tier >= MAX_TIER) continue;
        let run = null;
        for (let k = 1; item.tier + k <= MAX_TIER; k += 1) {
          const raised = itemAt(item.key, item.tier + k);
          const trial = slots.slice();
          trial[place] = raised;
          const result = value(trial);
          const gain = result.F.sub(current.F);
          if (gain.sign() > 0) {
            run = { k, gain, place, raised, result };
            break;
          }
        }
        if (run === null) continue; // (no run: not at any length)
        if (bestAny === null || beats(run, bestAny)) bestAny = run;
        if ((motes === null || run.k <= motes - spent) && (best === null || beats(run, best))) best = run;
      }
      if (bestAny === null) {
        ended = "no-gain";
        return null;
      }
      if (best === null) {
        ended = "motes";
        nextRun = bestAny.k;
        return null;
      }
      const old = slots[best.place];
      count += 1;
      spent += best.k;
      const step = {
        index: count,
        place: best.place,
        key: old.key,
        from: old.tier,
        to: best.raised.tier,
        motes: best.k,
        spent,
        gain: best.gain,
        F: best.result.F,
        moved: movedOf(current.breakdown.totals, best.result.breakdown.totals, old, best.raised),
      };
      slots[best.place] = best.raised;
      current = best.result;
      return step;
    },
  };
}

export function collect(walk) {
  const steps = [];
  for (let step = walk.step(); step !== null; step = walk.step()) steps.push(step);
  return { start: walk.start, steps, ending: walk.ending(), left: walk.left(), spent: walk.spent(), nextRun: walk.nextRun() };
}
