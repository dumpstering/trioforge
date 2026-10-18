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

/** Item evidence: the words of the seal column and the id of its icon. */
export const ITEM_SEALS = {
  strict: ["Seen in game", "i-strict"],
  wiki: ["Wiki", "i-wiki"],
};

export const EMPTY_NAME = "Leave empty";
export const DASH = "—";
export const EN_DASH = "–";

/** The badge of an item only some deities can use; `names` is the list of those deities. */
export function deityText(names) {
  return names && names.length > 0 ? "Needs deity: " + names.join(" or ") : "";
}
