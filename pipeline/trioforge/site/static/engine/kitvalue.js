// The value of a kit in the page, worked out with the engine's own evaluator: what the Upgrade section shows for a kit that came in a link. No solver, no worker and no
// download of the optimizer are needed, so the page asks for none and asks the visitor nothing: the data is the bundle of the trio and the item table, which the page has
// fetched and checked the way the worker does (the paths, sizes and SHA-256 of the manifests).
//
//   valueOfKit({bundle, records, race, role, buffs, evidence, deity, places, searchLimit}) -> {value, F, buffs, counted, left, setup, hasteAssumed, exact, evaluations}
//
//   bundle        the parsed bundle of the trio and the level (the document the manifest of the trio lists), read here by readBundle (profile.js) and remembered for the next call
//   records       the item table's records, a Map from the key ("w<page id>") to the record, as readItemTable (items.js) gives it
//   race          the race of the kit (a code of the bundle); role, buffs and evidence are the view's (as assembleProfile takes them): the role and the evidence level the page shows
//                 and the buff set it shows, "own" or "group" (the bundle has more)
//   deity         the deity of the profile, or null (the page has none): an item that needs one is not worn without it
//   places        [{slotIndex, key, tier}], at most one for each of the 22 places of a kit (SLOT_INSTANCES of evaluate.js), the item at the tier it is worn at
//   searchLimit   the most calls to the evaluator the search for the buffs may make (BUFF_SEARCH_LIMIT by default; a whole number from 1)
//
// The kit is valued as its own, never as the page's view of weapons. A link carries the items and where they stand, and nothing about the weapon setup, the haste or the buffs of the
// one who made it, so none of the three is the page's to give:
//
//   The setup is read from the hands. A two-hander in the main hand is "2h", a shield in the off hand "1h-shield", otherwise "dw"; a hand that holds something that is no weapon
//   (and no shield in the off hand) makes it "stick", the setup that takes anything in either hand and scores no weapon damage. The setups are tried in that order, and the first
//   that lets both hands stand as they are is the kit's; when none does, the one that refuses the fewest (the earlier of two) is, and what it refuses is left out.
//
//   The hands are the model's own: `allowedInHand` of model.js decides what a setup lets into a hand (a two-hander is never in the off hand, "2h" takes a two-hander in the main
//   hand, "dw" a one-hander in either, "1h-shield" a one-hander and a shield, "stick" anything), and a two-hander in the main hand leaves the off hand empty (the row "two_hander" of
//   the builder). An item the rules refuse is left out, with the reason "hands".
//
//   The haste the weapons are scored at is the model's rule (`hastePercent` of prune.js, which `_assumed_haste` of the builder and `session_haste` of upgrade.py are): the best
//   spell haste the buff set offers, plus the best worn haste of the items the value counts, up to the cap. It is a whole number, and not the page's: the one the page shows is its
//   own answer's, a scenario's, and moves with the tier, the weapons and the race.
//
//   The buffs are the best the set allows for this kit: a choice of its optional buffs, at most the cardinality of the set and no two that exclude each other, with the greatest
//   value. The search is exact (`exact` is true), or it ran out of calls (`exact` is false) and the value is the best that was found: at least that.
//
// The result is {value, F, buffs, counted, left, setup, hasteAssumed, exact, evaluations}: `F` the exact value as a reduced "p/q" text and `value` its number, `buffs` the ids of the
// optional buffs the value counts, `counted` how many items it holds, `left` the places whose item it does not hold, [{slotIndex, reason}], `setup` and `hasteAssumed` what the value is
// for, `exact` whether the buffs are the best there are, and `evaluations` how many calls to the evaluator the search made. An item that is not worn there is left out and counts for
// nothing; a link is not trusted to be a kit that could be worn, and the page says which place and why. The reasons: "unknown" (the item table has no such item), "slot" (the item has
// no such place: an Any place takes an item with any place of a kit), "class" (none of the trio's classes can use it), "race", "deity" (it needs one), "hands" (a two-hander takes both
// hands: the rules of the setup refuse it in this hand, or the item in the off hand it leaves empty) and "lore" (the second copy of a lore item).
//
// The search for the buffs is a branch and bound, and exact. The value never falls when a buff is added that takes nothing away (every part of it rises with every component of the
// buffs, and the weights are not negative: the evaluator refuses a profile that has one), and a buff can take something away (Divine Purpose costs mana regeneration), so it is a
// choice and not a rule. The optional buffs are ranked by what each adds alone, and a depth-first search decides them one by one: in, then out, within the cardinality and the
// exclusions. Each step is cut when the best it could reach is no better than the best kit found: the bound is the value with, on top of the buffs chosen, a buff of every
// component's best `c` positive amounts (the best `c` summed, the best one for haste) among the buffs left, `c` the room that is left, which no choice can beat (a negative amount is
// left out of it, so it is above a choice that has one). The bound is worked out by the evaluator itself, with a buff of that size (under an id above every id of the set and of its
// table, so that it takes the place of none). On the 6 kits and the 12 views of the fixtures
// (tests-js/engine-kitvalue.test.mjs) it takes 60 calls at most for the group set (19 optional buffs, a cap of 15) and 2,400 for the raid set (32 optional buffs, a cap of 15, 8 pairs
// that exclude each other), about a fifth of a second at the most. The worst case is the limit: the search stops at BUFF_SEARCH_LIMIT calls, 6,000 (about half a second on a machine
// that makes a call in 0.1 ms, a few seconds on a slow one), and the answer is then a lower bound ("at least"). The whole search is in the order of the ranking, so a longer limit
// finds at least what a shorter one does.
//
//   loadKitBundle({manifest, trio, level, fetchImpl, base, stallMs, bodyMs}) -> the parsed bundle of the trio and the level
//
// The bundle is fetched as the worker fetches it (scenario.js): the manifest of the trio at the address the main manifest (`manifest`, as parseManifest gives it) lists for the trio, then
// the bundle at the path that manifest lists for the level, the type and the size checked as the body is read and the SHA-256 before a byte is parsed. Nothing here takes an address from
// anywhere but the manifests. A failure is an EngineFault with a message for the visitor.
//
// Everything is the engine's own: the profile (assembleProfile), the items at their tiers (atTier), the rules of the hands and of the haste (model.js, prune.js) and the evaluator
// (evaluate). A name from outside is looked up in a Map. This file is a script of its own in the build (assets/engine/kitvalue-<hash>.js, listed in the engine manifest), loaded by the
// page for a shared kit and by nothing else: the optimizer's client does not carry it.

import { DATA_FILE, EngineFault, fetchBytes, sameOriginUrl, sha256Hex } from "./download.js";
import { SLOT_INSTANCES, evaluate } from "./evaluate.js";
import { atTier } from "./items.js";
import { ManifestReleaseError, fetchTextWithin, parseTrioManifest, trioManifestPath } from "./manifest.js";
import { allowedInHand, readItem } from "./model.js";
import { hastePercent } from "./prune.js";
import { assembleProfile, readBundle } from "./profile.js";
import { LIMITS, STARTUP_COMPILE_MS, STARTUP_STALL_MS } from "./protocol.js";

const PLACES = SLOT_INSTANCES.length;
const ANY = "ANY";
/** The names of the places of a kit that an Any place takes an item of (every one but Any itself). */
const KIT_PLACES = new Set(SLOT_INSTANCES.filter((name) => name !== ANY));
const PRIMARY = SLOT_INSTANCES.indexOf("PRIMARY");
const SECONDARY = SLOT_INSTANCES.indexOf("SECONDARY");
/** The most calls to the evaluator that the search for the optional buffs makes (see the header for what that costs and what it needs). */
export const BUFF_SEARCH_LIMIT = 6000;
/** The bundles that were read, by the document they were read from (a bundle is read once for the page), with the buff sets made of them. */
const READ = new WeakMap();

function bundleOf(raw) {
  const known = typeof raw === "object" && raw !== null ? READ.get(raw) : undefined;
  if (known !== undefined) return known;
  const entry = { read: readBundle(raw), buffsets: new Map() };
  if (typeof raw === "object" && raw !== null) READ.set(raw, entry);
  return entry;
}

/** The buff set of a key as the evaluator takes it, one object for the bundle (it is frozen all through, so the evaluator reads it once and remembers it). */
function buffsetOf(entry, key) {
  let made = entry.buffsets.get(key);
  if (made === undefined) {
    made = Object.freeze({ set: entry.read.buffs[key].set, table: entry.read.buff_table });
    entry.buffsets.set(key, made);
  }
  return made;
}

/** Why an item cannot be worn in a place of the kit by this profile, or null: the names of the reasons are in the header ("hands" and "lore" are decided afterwards). */
function reasonOf(item, slotIndex, trio, race, deity) {
  const place = SLOT_INSTANCES[slotIndex];
  if (!item.slots.includes(place) && !(place === ANY && item.slots.some((name) => KIT_PLACES.has(name)))) return "slot";
  if (!item.classes.some((code) => trio.has(code))) return "class";
  if (item.races !== null && !item.races.includes(race)) return "race";
  if (item.deity !== null && (deity === null || !item.deity.includes(deity))) return "deity";
  return null;
}

/**
 * The weapon setup of the hands of a kit of items that can be worn, and the hands the rules refuse under it (see the header): `{setup, refused}`, `refused` the places (the main hand's,
 * the off hand's) whose item the setup does not let stand there.
 */
function handsOf(kit) {
  const [main, off] = [kit[PRIMARY], kit[SECONDARY]].map((item) => (item === null ? null : readItem(item, 0)));
  const twoHanded = main !== null && main.weapon !== null && main.weapon.twoHanded;
  const order = [];
  if (twoHanded) order.push("2h");
  if (off !== null && off.isShield) order.push("1h-shield");
  order.push("dw", "stick");
  const refusedBy = (setup) => {
    const refused = [];
    if (main !== null && !allowedInHand(main, "PRIMARY", setup)) refused.push(PRIMARY);
    if (off !== null && (twoHanded || !allowedInHand(off, "SECONDARY", setup))) refused.push(SECONDARY); // (a two-hander in the main hand leaves the off hand empty)
    return refused;
  };
  let chosen = null;
  for (const setup of order) {
    const refused = refusedBy(setup);
    if (chosen === null || refused.length < chosen.refused.length) chosen = { setup, refused };
    if (refused.length === 0) break;
  }
  return chosen;
}

/** The search ran out of calls. */
const OUT_OF_CALLS = Symbol("out of calls");

/**
 * An id above every id of a buff set and its table, for a buff that is not in the bundle: the keys of the table, the buffs of the set that are always on and the optional ones (which
 * the evaluator reads) and the ones the exclusions and the cliques name (which it only compares). The ids of one spell line are consecutive, so the id one above the largest optional
 * one can be a buff that is always on, and a table that held both would have the new buff's amounts in the place of that buff's.
 */
function idAbove({ set, table }) {
  let top = 0;
  const see = (id) => {
    if (Number.isSafeInteger(id) && id > top) top = id;
  };
  for (const key of Object.keys(table)) see(Number(key));
  for (const id of [...set.always_on, ...set.optional]) see(id);
  for (const group of [...set.conflicts, ...set.cliques]) for (const id of group) see(id); // (an exclusion also names its reasons, which are text, not ids)
  return top + 1;
}

/**
 * The best choice of the optional buffs for a kit, `{chosen, F, exact, evaluations}`: see the header for how. `options` are the evaluator's (setup, haste, Monk bins) and `buffset`
 * the buff set of the bundle; `limit` is the most calls to the evaluator that may be made (the first, for the kit with no optional buff, always is).
 */
function bestBuffs(profile, kit, options, buffset, limit) {
  const { optional, conflicts, cardinality } = buffset.set;
  const room = cardinality === null ? optional.length : cardinality;
  let calls = 0;
  const spend = () => {
    if (calls >= limit) throw OUT_OF_CALLS;
    calls += 1;
  };
  const worth = (ids) => {
    spend();
    return evaluate(profile, kit, ids, { ...options, buffset }).F;
  };

  // what each buff adds to which component of the buffs (the amounts of the table, as numbers), and the buffs that exclude each other
  const amounts = new Map();
  const names = new Set();
  for (const id of optional) {
    const vec = buffset.table[String(id)].vec;
    const own = new Map(Object.entries(vec).filter(([, amount]) => Number.isFinite(amount)));
    for (const name of own.keys()) names.add(name);
    amounts.set(id, own);
  }
  const excludes = new Map(optional.map((id) => [id, new Set()]));
  for (const [a, b] of conflicts) {
    excludes.get(a)?.add(b);
    excludes.get(b)?.add(a);
  }
  const blocked = (id, chosen) => chosen.some((other) => excludes.get(id).has(other));

  // the bound: a buff of the best amounts, as the evaluator takes it, in a buff set of its own that is the bundle's with that buff (and no cardinality and no exclusion), under an id
  // that no buff of the set or of its table has, so that it takes nobody's place
  const virtual = idAbove(buffset);
  const virtualVec = {};
  const boundBuffset = {
    set: { ...buffset.set, optional: [...optional, virtual], conflicts: [], cardinality: null },
    table: { ...buffset.table, [String(virtual)]: { name: "bound", vec: virtualVec } },
  }; // (not frozen, so the evaluator reads it again at each call: the amounts of the buff that is the bound change)
  const bound = (chosen, left, count) => {
    for (const name of Object.keys(virtualVec)) delete virtualVec[name];
    for (const name of names) {
      const given = left.map((id) => amounts.get(id).get(name) ?? 0).filter((amount) => amount > 0);
      if (given.length === 0) continue;
      if (name === "HASTE") {
        virtualVec[name] = Math.max(...given); // (the best haste counts, not the sum)
        continue;
      }
      given.sort((a, b) => b - a);
      const sum = given.slice(0, count).reduce((total, amount) => total + amount, 0);
      virtualVec[name] = Number.isInteger(sum) ? sum : Math.ceil(sum);
    }
    spend();
    return evaluate(profile, kit, [virtual, ...chosen], { ...options, buffset: boundBuffset }).F;
  };

  let best = null;
  let exact = true;
  try {
    best = { ids: [], F: worth([]) };
    // the buffs, the ones that add most alone first (the first path of the search is the greedy choice, and the bound cuts the most from a good one)
    const added = new Map(optional.map((id) => [id, worth([id])]));
    const ranked = [...optional].sort((a, b) => added.get(b).compare(added.get(a)));
    const consider = (chosen) => {
      const F = chosen.length === 0 ? best.F : worth(chosen);
      if (F.compare(best.F) > 0) best = { ids: [...chosen], F };
    };
    const search = (start, chosen) => {
      let at = start;
      while (at < ranked.length && blocked(ranked[at], chosen)) at += 1;
      const left = ranked.slice(at).filter((id) => !blocked(id, chosen));
      if (chosen.length >= room || left.length === 0) {
        consider(chosen);
        return;
      }
      if (bound(chosen, left, room - chosen.length).compare(best.F) <= 0) return;
      const next = ranked[at];
      search(at + 1, [...chosen, next]);
      search(at + 1, chosen);
    };
    search(0, []);
  } catch (error) {
    if (error !== OUT_OF_CALLS) throw error;
    exact = false;
  }
  return { chosen: [...best.ids].sort((a, b) => a - b), F: best.F, exact, evaluations: calls };
}

export function valueOfKit({ bundle, records, race, role, buffs, evidence, deity = null, places, searchLimit = BUFF_SEARCH_LIMIT, ...unasked }) {
  for (const name of ["setup", "hasteAssumed"]) {
    if (name in unasked) throw new TypeError(`valueOfKit takes no ${name}: the setup is read from the kit's hands and the haste is the model's rule for the kit's items`);
  }
  if (!(records instanceof Map)) throw new TypeError("records is the item table's Map from a key to a record");
  if (!Array.isArray(places)) throw new TypeError("places is a list of {slotIndex, key, tier}");
  if (!Number.isInteger(searchLimit) || searchLimit < 1) throw new RangeError("searchLimit is the most calls to the evaluator, a whole number from 1");
  const entry = bundleOf(bundle);
  const read = entry.read;
  const profile = assembleProfile(read, { race, role, buffs, evidence, deity });
  const trio = new Set(read.trio);

  // the items that could be worn where the link puts them
  const worn = new Array(PLACES).fill(null);
  const left = [];
  const seen = new Set();
  const ordered = [...places].sort((a, b) => a.slotIndex - b.slotIndex);
  for (const { slotIndex, key, tier } of ordered) {
    if (!Number.isInteger(slotIndex) || slotIndex < 0 || slotIndex >= PLACES) throw new RangeError(`place ${slotIndex} is not one of the ${PLACES} places of a kit`);
    if (seen.has(slotIndex)) throw new RangeError(`place ${slotIndex} has two items`);
    seen.add(slotIndex);
    const record = typeof key === "string" ? records.get(key) : undefined;
    if (record === undefined) {
      left.push({ slotIndex, reason: "unknown" });
      continue;
    }
    const item = atTier(record, tier, read);
    const reason = reasonOf(item, slotIndex, trio, race, deity);
    if (reason !== null) {
      left.push({ slotIndex, reason });
      continue;
    }
    worn[slotIndex] = item;
  }

  // the hands: the setup the kit's hands are, and what its rules refuse; then the second copy of a lore item
  const { setup, refused } = handsOf(worn);
  for (const slotIndex of refused) {
    left.push({ slotIndex, reason: "hands" });
    worn[slotIndex] = null;
  }
  const kit = new Array(PLACES).fill(null);
  const lore = new Set();
  worn.forEach((item, slotIndex) => {
    if (item === null) return;
    if (item.lore && lore.has(item.key)) {
      left.push({ slotIndex, reason: "lore" });
      return;
    }
    if (item.lore) lore.add(item.key);
    kit[slotIndex] = item;
  });
  left.sort((a, b) => a.slotIndex - b.slotIndex);

  const counted = kit.filter((item) => item !== null);
  const hasteAssumed = hastePercent(profile, counted.map((item) => item.haste), null);
  const options = { setup, hasteAssumed, monkBins: read.monk_bins === null ? undefined : read.monk_bins };
  const found = bestBuffs(profile, kit, options, buffsetOf(entry, buffs), searchLimit);
  return {
    value: found.F.toNumber(),
    F: found.F.toString(),
    buffs: found.chosen,
    counted: counted.length,
    left,
    setup,
    hasteAssumed,
    exact: found.exact,
    evaluations: found.evaluations,
  };
}

const fault = (message) => new EngineFault("engine-load", message);

/** The bundle of the trio and the level, fetched by the paths of the manifests and checked against their sizes and SHA-256 (see the header). */
export async function loadKitBundle({ manifest, trio, level, fetchImpl, base, stallMs = STARTUP_STALL_MS, bodyMs = STARTUP_COMPILE_MS }) {
  const what = "The list of files for this trio";
  const path = trioManifestPath(manifest, trio);
  if (path === undefined || !manifest.trios.get(trio).levels.includes(level)) throw fault("The site lists no data for this trio and level.");
  const answer = await fetchTextWithin(fetchImpl, sameOriginUrl(path, base).href, { credentials: "same-origin", cache: "no-cache" }, stallMs, LIMITS.maxTrioManifestBytes);
  if (answer.state === "timeout") throw fault(`${what} did not arrive in time.`);
  if (answer.state === "status") throw fault(`${what} could not be loaded (${answer.status}).`);
  if (answer.state !== "ok" || typeof answer.text !== "string") throw fault(`${what} could not be loaded.`);
  let files;
  try {
    files = parseTrioManifest(JSON.parse(answer.text), manifest, trio);
  } catch (error) {
    throw fault(error instanceof ManifestReleaseError ? `${what} is of another release than the site's.` : `${what} is not what was expected.`);
  }
  const file = files.bundles.get(level);
  let bytes;
  try {
    bytes = await fetchBytes(sameOriginUrl(file.path, base), file.bytes, fetchImpl, () => {}, stallMs, bodyMs, DATA_FILE);
  } catch (error) {
    throw error instanceof EngineFault ? error : fault("The data of this trio could not be loaded.");
  }
  if ((await sha256Hex(bytes)) !== file.sha256) throw fault("The data of this trio is not the one the site lists (its checksum differs).");
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw fault("The data of this trio is not what the site writes.");
  }
}
