// Matching the rows of a dump to the item table.
//
// The dump has no stats, class or race, only a name, so the name has to say which item a row is. This module never
// guesses: a name that fits one item is matched, a name that fits several is AMBIGUOUS (all of them are listed),
// and a name that fits none is UNKNOWN. A caller shows the last two and lets the visitor choose; until then
// they count for nothing. Nothing is ever learned from a dump: the table is only read, never changed or kept.
//
// The item table is an array of { key: "w<pageid>", match_name, aliases: [], owned_only: bool, name }.
//
// A name is looked up in two steps.
//   Stages 1 to 3 make ONE POOL of candidates:
//     1  items whose match_name is the name exactly as written. The star is part of the name: "Club*" is not "Club".
//     2  items whose match_name is the name once every kind of quotation mark counts as one (the game writes ` or ',
//        the wiki ’).
//     3  items with the name as an alias, quotation marks again counted as one (a wiki title such as "Spoon (Weapon)").
//   An item reached by several of these is one candidate, and its stage is the earliest. One candidate: matched. More
//   than one: ambiguous, all of them listed in the table's order. An item that has the name as its match_name and
//   another that has it as an alias are both candidates; neither wins because of the stage it was found at.
//   Stage 4 is tried only when the pool is empty:
//     4  items whose match_name or alias is the name without a leading "a ", "an " or "the " and without regard to case.
//   A stage-4 hit is only ever OFFERED: it is ambiguous even when it is one item, because the name written is not the
//   name the item has, and a caller lets the visitor confirm it.
// Hidden items are in the table too, flagged owned_only: they match like any other, and say so.
//
// Rows that are not gear are never matched: the stones in sockets, the ornaments, and whatever sits in a socket.

import { MAX_ITEM_KEY_LENGTH } from "../engine/items.js";

const MAX_NAME_LENGTH = 256;
const MAX_ALIASES = 64;

/** Every character that stands for an apostrophe: ` ' and the typographic ones (and the one a bad decode leaves). */
const QUOTE_CODES = new Set([0x60, 0x27, 0x2018, 0x2019, 0x201b, 0x2032, 0xb4, 0xfffd]);

/** The name with every quotation mark turned into a plain apostrophe (the picker of the Upgrade section folds the names and what is typed the same way). */
export function foldQuotes(name) {
  let out = "";
  let from = 0;
  for (let i = 0; i < name.length; i++) {
    const c = name.charCodeAt(i);
    if (c !== 0x27 && QUOTE_CODES.has(c)) {
      out += name.slice(from, i) + "'";
      from = i + 1;
    }
  }
  return from === 0 ? name : out + name.slice(from);
}

/** A name that is already quote-folded, in lower case and without one leading article. */
function withoutArticle(folded) {
  const lower = folded.toLowerCase();
  if (lower.startsWith("a ")) return lower.slice(2);
  if (lower.startsWith("an ")) return lower.slice(3);
  if (lower.startsWith("the ")) return lower.slice(4);
  return lower;
}

function add(map, name, key) {
  const keys = map.get(name);
  if (keys === undefined) map.set(name, [key]);
  else if (!keys.includes(key)) keys.push(key);
}

/** The four lookups, one per stage, which keys are hidden items, and each key's place in the table. Entries that are not usable are left out. */
function buildIndex(items) {
  const index = { exact: new Map(), quote: new Map(), alias: new Map(), article: new Map(), hidden: new Map(), order: new Map() };
  if (!Array.isArray(items)) return index;
  for (const item of items) {
    if (item === null || typeof item !== "object") continue;
    const key = item.key;
    const name = item.match_name;
    if (typeof key !== "string" || key.length < 1 || key.length > MAX_ITEM_KEY_LENGTH) continue;
    if (typeof name !== "string" || name.length < 1 || name.length > MAX_NAME_LENGTH) continue;
    if (!index.hidden.has(key)) {
      index.hidden.set(key, item.owned_only === true);
      index.order.set(key, index.order.size);
    }
    const folded = foldQuotes(name);
    add(index.exact, name, key);
    add(index.quote, folded, key);
    add(index.article, withoutArticle(folded), key);
    const aliases = item.aliases;
    if (!Array.isArray(aliases)) continue;
    for (let i = 0; i < aliases.length && i < MAX_ALIASES; i++) {
      const alias = aliases[i];
      if (typeof alias !== "string" || alias.length < 1 || alias.length > MAX_NAME_LENGTH) continue;
      const foldedAlias = foldQuotes(alias);
      add(index.alias, foldedAlias, key);
      add(index.article, withoutArticle(foldedAlias), key);
    }
  }
  return index;
}

/**
 * What a name could be. Stages 1 to 3 make one pool, each item with the earliest stage that reached it; only when the pool
 * is empty is stage 4 tried, and its hits are only offered. Returns { keys, stage, offered } or null; the keys are in the table's order.
 */
function lookup(index, name) {
  const folded = foldQuotes(name);
  const pool = new Map(); // key -> the earliest stage that reached it
  const reach = (keys, stage) => {
    if (keys !== undefined) for (const key of keys) if (!pool.has(key)) pool.set(key, stage);
  };
  reach(index.exact.get(name), 1);
  reach(index.quote.get(folded), 2);
  reach(index.alias.get(folded), 3);
  if (pool.size > 0) {
    const keys = Array.from(pool.keys()).sort((a, b) => index.order.get(a) - index.order.get(b));
    return { keys, stage: Math.min(...pool.values()), offered: false };
  }
  const close = index.article.get(withoutArticle(folded));
  if (close !== undefined) return { keys: close, stage: 4, offered: true };
  return null;
}

/**
 * Match dump rows (the `rows` of parseDump) to the item table.
 * @returns {{
 *   matched: {row: object, key: string, ownedOnly: boolean, stage: number}[],
 *   ambiguous: {row: object, keys: string[], stage: number}[],
 *   unknown: {row: object}[]
 * }}
 *   Each row that is gear is in exactly one list, in the order given; `row` is the very object that was passed in.
 *   `keys` are in the table's order, and there are two or more of them unless `stage` is 4 (a close name, offered).
 *   `stage` is the earliest stage at which any of the keys was found. Anything in `rows` that is not an object with a
 *   string `name` is ignored.
 */
export function matchItems(rows, items) {
  const matched = [];
  const ambiguous = [];
  const unknown = [];
  if (!Array.isArray(rows)) return { matched, ambiguous, unknown };
  const index = buildIndex(items);
  const found = new Map(); // a name seen before -> its lookup
  for (const row of rows) {
    if (row === null || typeof row !== "object" || typeof row.name !== "string") continue;
    if (row.stone === true || row.ornament === true || (row.socket !== null && row.socket !== undefined)) continue;
    let hit = found.get(row.name);
    if (hit === undefined) {
      hit = lookup(index, row.name);
      found.set(row.name, hit);
    }
    if (hit === null) unknown.push({ row });
    else if (!hit.offered && hit.keys.length === 1) matched.push({ row, key: hit.keys[0], ownedOnly: index.hidden.get(hit.keys[0]) === true, stage: hit.stage });
    else ambiguous.push({ row, keys: hit.keys.slice(), stage: hit.stage });
  }
  return { matched, ambiguous, unknown };
}
