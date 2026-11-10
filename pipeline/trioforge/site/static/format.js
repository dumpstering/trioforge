// The numbers and words the page shows. The generator (pipeline/trioforge/site/view.py) says the same things the same way;
// tests-js/trio.test.mjs re-renders the baked default view and checks that nothing a reader can see changes.

const MINUS = "−";

/** Round half up with one addition and a floor: the same two steps the generator takes. */
export function displayInt(value) {
  return Math.floor(value + 0.5);
}

export function fmtInt(number) {
  const digits = String(Math.abs(number)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return number < 0 ? MINUS + digits : digits;
}

export function fmtSigned(number) {
  return number > 0 ? "+" + fmtInt(number) : fmtInt(number);
}

export function tierLabel(tier) {
  return "+" + tier;
}

/** What reaching `tier` costs for an item that arrives at `arrival`: a duplicate at +k gives 2^k of the 2^N needed.
 * A summoned item (arrival null) is made at its spell rank, so there is nothing to count. */
export function reachText(arrival, tier) {
  return arrival === null || tier <= arrival ? "" : fmtInt(2 ** (tier - arrival)) + " copies to reach " + tierLabel(tier);
}

export const SPELL_RANK = "spell rank";

/** The "Arrives at" cell: a tier, or the spell rank of a summoned item. */
export function arrivalText(arrival) {
  return arrival === null ? SPELL_RANK : tierLabel(arrival);
}

export const EMPTY_NAME = "Leave empty";
export const DASH = "—";
export const EN_DASH = "–";

/** The badge of an item only some deities can use; `names` is the list of those deities. */
export function deityText(names) {
  return names && names.length > 0 ? "Needs deity: " + names.join(" or ") : "";
}

/** The stat of worn haste in the text of a row's stats, as the generator words it among the others ("AGI +5, Haste +19%, Weight 0.1"). */
const HASTE_STAT = /(?:^|, )Haste \+([0-9]+)%(?:,|$)/;

/**
 * The chip of a row whose item has worn haste ("Haste 19%"), made from the stats the row says, which are the generator's own text (view.py: `item_stat_text`), so that the chip
 * and the panel under it never disagree. Nothing for an item with no haste, a place left empty, or text that is no stats (`stats` may be null).
 */
export function hasteChip(stats) {
  const found = typeof stats === "string" ? HASTE_STAT.exec(stats) : null;
  return found === null ? "" : "Haste " + found[1] + "%";
}

/** The chip for a worn haste given as a number (an item of an answer of the optimizer, whose row has no stats text): nothing unless it is a whole number above zero. */
export function hasteWords(percent) {
  return Number.isSafeInteger(percent) && percent > 0 ? "Haste " + percent + "%" : "";
}
