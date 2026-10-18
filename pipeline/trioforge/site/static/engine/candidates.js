// The candidates of a scenario: what a visitor could acquire, made in the worker from the tier mode of the request (the page never sends candidates).
//
//   candidatesFor(records, rules, profile, {evidence, tierMode}) -> a list of items as `atTier` gives them, one for each key
//
// `records` are the records of the item table (a Map from key to record, as `readItemTable` gives them, or any list of records), `rules` the bundle (what `atTier` reads
// the tier and weapon rules from), `profile` the one the scenario's session is made of (`assembleProfile`: the trio, the race and the deity), `evidence` the scenario's
// evidence level and `tierMode` `{mode: "ready4"}`, `{mode: "arrives", D}` or `{mode: "fixed", N}` (tiers.js).
//
// A record is a candidate when it is one that the precompute offers, and the profile can use it. The precompute makes its candidates in two steps
// (pipeline/trioforge/precompute/grid.py): `select_items` keeps the items of a level, strict or wiki, that are not marked `not-for-bis`, and `Context.candidates` offers
// those whose level is in the scenario's set. So a record is a candidate when
//   * its evidence level is in the scenario's set: "strict" takes the strict records, any other level (the scenario's is "wiki") the strict and the wiki records;
//   * it is not marked not-for-bis: a temporary item, or one a quest takes on hand-in, is out whatever its level says. The table writes the codes of a record's reasons
//     in `evidence.codes` (without their details), and `select_items` reads the same reason;
//   * a deity-locked item is in the set (`Context.candidates` keeps the items that are locked to a deity: the solve pool leaves them out, the candidates do not);
//   * it is not a hidden record (`owned_only`: an item that only a player may own and that no search could offer), whatever its level says;
//   * the profile can use it: a class of the trio, a race and a deity it admits (a deity-locked item is kept for the deity it names and for no other, and for none
//     when the profile has none). This is the rule of the model builder (model.js `collect`, which leaves the rest without a column) and of upgrade.py's usability
//     check, which path.js has as `usableBy`: the very function is used here, so that there is one rule.
// and it is read at `tierForMode(record, mode, {D, N})`, through `atTier` with the bundle's rules. A key has one record, so it has one candidate: the list never
// holds two items of one key (the Upgrade functions would take them, and the "best k sets are never worth less than the first k steps" holds with one a key).
//
// The records are read and not changed, and nothing is kept: the scenario engine keeps the last list made (scenario.js).
//
// Faults. A record that `atTier` refuses (an ItemError), a tier or a rule it cannot use (a TierError) and rules that are not the ones it implements (a BundleError)
// are raised as they are: the data is wrong, not the visitor's request, and the caller tells it so.

import { atTier } from "./items.js";
import { usableBy } from "./path.js";
import { tierForMode } from "./tiers.js";

const STRICT = ["strict"];
const STRICT_AND_WIKI = ["strict", "wiki"];
/** The code of a record that is not for best in slot (a temporary item, or one a quest takes on hand-in): the precompute never offers such an item. */
const NOT_FOR_BIS = "not-for-bis";

/** Whether the table marks a record not-for-bis: the code is among the codes of its evidence (a record may have none). */
const notForBis = (record) => Array.isArray(record.evidence.codes) && record.evidence.codes.includes(NOT_FOR_BIS);

/** The options `tierForMode` reads, from a tier mode that was checked by the protocol (and is checked again by tierForMode): D for `arrives`, N for `fixed`. */
function tierOptions(tierMode) {
  if (tierMode.mode === "arrives") return { D: tierMode.D };
  if (tierMode.mode === "fixed") return { N: tierMode.N };
  return {};
}

export function candidatesFor(records, rules, profile, { evidence, tierMode }) {
  const levels = evidence === "strict" ? STRICT : STRICT_AND_WIKI;
  const options = tierOptions(tierMode);
  tierForMode("drop", tierMode.mode, options); // the mode and its numbers are checked once, whether any record is read or not
  const usable = usableBy(profile);
  const list = [];
  for (const record of records instanceof Map ? records.values() : records) {
    if (record.owned_only === true || !levels.includes(record.evidence.level) || notForBis(record)) continue;
    const item = atTier(record, tierForMode(record, tierMode.mode, options), rules);
    if (usable(item)) list.push(item);
  }
  return list;
}
