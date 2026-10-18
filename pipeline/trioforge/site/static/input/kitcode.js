/**
 * Kit link codec: the compact, versioned text behind the `#k=` links that share one kit.
 *
 * A link names one kit: a trio, a race, a level and up to 22 (slot, item, tier) triples. It never
 * carries an owned inventory, a score, a count or any free text. A visitor's page recomputes every
 * score from its own item table, and shows an item it does not know as a placeholder.
 *
 * Wire format, version 1. Byte 0 is the version; everything after it is an unsigned LEB128 varint
 * (7 bits per byte, low group first, the high bit set on every byte but the last):
 *
 *   byte 0     version, always 1
 *   varint     trio index    the position in TRIO_CODES, 0..559
 *   varint     race index    the position in RACE_CODES, 0..14
 *   varint     level         1..65
 *   varint     slot count n  0..22
 *   n times    varint slotIndex  0..21, strictly ascending
 *              varint pageId     1..2^31-1, the number in a catalog key "w<pageId>"
 *              varint tier       0..10
 *
 * The bytes travel as base64url (RFC 4648 section 5) with no padding. A kit is at most 160 bytes, so
 * at most 214 characters; a link may be up to 2,048. There is no compression: nothing here inflates.
 *
 * Every kit has exactly one spelling, and the decoder accepts nothing else: the alphabet is exact,
 * the unused bits of the last character are zero, a varint is the shortest one for its value (and
 * at most 5 bytes), the slots ascend, and every byte must be consumed. So decoding then encoding
 * gives back the same link.
 *
 * A slot index is a position in SLOT_ORDER, the 22 places of a kit in the order the solver lists
 * them. That order is part of the format (see SLOT_ORDER).
 *
 * The tables below are part of the format. Never reorder them. A new race goes at the end of
 * RACE_CODES, and a new class at the end of CLASS_CODES (no existing trio index changes then).
 *
 * The page flow, in order:
 *   1. Run `takeKitFromLocation()` first in the page module, before any other script can read the
 *      URL. It lives in input/kitlocation.js, the one file of the kit link that the page script
 *      carries (this file is code of the Upgrade section, loaded with it). It moves a `#k=` payload
 *      into `history.state` (which survives a reload) and removes the fragment. If `source` is
 *      "fragment" and `cleared` is false, the fragment is still in the URL: turn analytics off for
 *      this page.
 *   2. When `payload` is not null, fetch the item table, then call `decodeKit(payload, items)`
 *      (input/kitdecode.js: the reading half of the codec, which only the panel of a shared kit
 *      imports, and so a chunk of its own in the build).
 *   3. When `errors` is not empty, say that the kit link could not be read. Otherwise show `kit`,
 *      with a visible placeholder for every slot listed in `unknown`.
 *   4. Any later `history.replaceState` must pass `history.state` through, or a reload loses the kit.
 *
 * Two limits that the page has to respect, because no code in this module can:
 *   - Clearing the fragment does not hide it everywhere. The navigation timing entry
 *     `performance.getEntriesByType("navigation")[0].name` keeps the address the page was loaded
 *     with, `#k=` payload included, and anything that reports that name would send the kit. The
 *     Phase 5 preview test asserts that the analytics beacon never sends "#k=". If it ever does,
 *     analytics must stay off for a page opened from a kit link.
 *   - `history.state` belongs to one history entry. Following a link to an in-page anchor
 *     (`<a href="#main">`) makes a new history entry with no state, so a reload would lose the
 *     kit. In-page anchors must not create history entries: the page moves with
 *     `element.scrollIntoView()` (and moves the focus) instead of following the link.
 *
 * The module has no imports, no regular expressions and never decodes percent-escapes. It is the format, the
 * tables, the messages and the writing half (encodeKit, for Share and Remember); the reading half is in
 * input/kitdecode.js, which imports this one.
 */

/**
 * The 22 places of a kit, in kit order: the slot index in a link is a position in this list. It is the
 * order of SLOT_INSTANCES in `pipeline/trioforge/model/items.py` (a test reads that file and compares).
 * Never reorder it: a link stores only the position, so a reorder would silently move the items of
 * every old link into other slots. A different order needs a new link version. This module checks the
 * range of a slot index and nothing more; whether an item fits its slot is for the page.
 */
export const SLOT_ORDER = Object.freeze(
  "HEAD FACE EAR EAR NECK SHOULDERS ARMS BACK WRIST WRIST HANDS FINGER FINGER CHEST LEGS FEET WAIST RANGE ANY ANY PRIMARY SECONDARY".split(" "),
);

export const KIT_VERSION = 1;
export const MAX_FRAGMENT_LENGTH = 2048;
export const MAX_SLOTS = SLOT_ORDER.length;
export const MAX_TIER = 10;
export const MAX_LEVEL = 65;
export const MAX_PAGE_ID = 2147483647; // 2^31 - 1

export const MIN_LEVEL = 1;
export const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

/** The 16 class codes in class-id order: the list in `pipeline/trioforge/classes.py`. */
export const CLASS_CODES = Object.freeze("WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER".split(" "));

/** The 15 race codes in the order of `rules/races.json`. A kit spells a race as written there ("OGR"). */
export const RACE_CODES = Object.freeze("HUM BAR ERU ELF HIE DEF HEF DWF TRL OGR HFL GNM IKS KER FRG".split(" "));

/**
 * All 560 class triples. A trio is spelled as the page address spells it: its class codes in
 * lowercase, in class-id order, joined by "-" ("pal-mnk-ber"). The index of the triple with
 * zero-based class positions a < b < c is a + C(b, 2) + C(c, 3), so the list is ordered by highest
 * class, then middle class, then lowest, and adding a class only appends.
 */
export const TRIO_CODES = Object.freeze(
  (() => {
    const codes = [];
    for (let c = 2; c < CLASS_CODES.length; c += 1) {
      for (let b = 1; b < c; b += 1) {
        for (let a = 0; a < b; a += 1) {
          codes.push(`${CLASS_CODES[a]}-${CLASS_CODES[b]}-${CLASS_CODES[c]}`.toLowerCase());
        }
      }
    }
    return codes;
  })(),
);

/** The trio and race lists a kit is written against. Callers may pass their own; these are the defaults. */
export const DEFAULT_TABLES = Object.freeze({ trios: TRIO_CODES, races: RACE_CODES });

/** Every message `decodeKit` puts in `errors` and `encodeKit` throws. None of them repeats input. */
export const KIT_ERRORS = Object.freeze({
  notText: "kit link is not text",
  empty: "kit link is empty",
  tooLong: `kit link is longer than ${MAX_FRAGMENT_LENGTH} characters`,
  alphabet: "kit link has a character outside the base64url alphabet",
  length: "kit link has an impossible length",
  tail: "kit link is not canonical base64url (unused bits are not zero)",
  version: "unsupported kit version",
  truncated: "kit link ends too early",
  overlong: "a number in the kit link is not in canonical form",
  varintTooLong: "a number in the kit link is too long",
  trio: "unknown trio code",
  race: "unknown race code",
  level: `level out of range (${MIN_LEVEL}..${MAX_LEVEL})`,
  slotCount: `more than ${MAX_SLOTS} slots`,
  slotIndex: `slot index out of range (0..${MAX_SLOTS - 1})`,
  duplicateSlot: "duplicate slot index",
  slotOrder: "slots are not in ascending order of slot index",
  pageId: `page id out of range (1..${MAX_PAGE_ID})`,
  tier: `tier out of range (0..${MAX_TIER})`,
  trailing: "kit link has bytes after the last slot",
  items: "the item table is not available",
  tables: "the trio and race tables are not valid",
  kit: "kit must be an object",
  slots: "slots must be a list of [slotIndex, pageId, tier]",
  internal: "kit link could not be decoded",
});

/** Thrown by `encodeKit` for a kit it will not write. `message` is one of `KIT_ERRORS`. */
export class KitError extends Error {
  constructor(message) {
    super(message);
    this.name = "KitError";
  }
}

const isWhole = (value, low, high) => Number.isSafeInteger(value) && value >= low && value <= high;

// ---- catalog keys ----

/** "w112" -> 112. Null unless the key is "w" and a whole number from 1 to 2^31-1 with no leading zero. */
export function pageIdFromKey(key) {
  if (typeof key !== "string" || key.length < 2 || key.length > 11 || key.charCodeAt(0) !== 119 /* w */) return null;
  if (key.charCodeAt(1) === 48 /* 0 */) return null;
  let id = 0;
  for (let i = 1; i < key.length; i += 1) {
    const digit = key.charCodeAt(i) - 48;
    if (digit < 0 || digit > 9) return null;
    id = id * 10 + digit;
  }
  return id <= MAX_PAGE_ID ? id : null;
}

/** 112 -> "w112". Null unless the id is a whole number from 1 to 2^31-1. */
export function keyFromPageId(pageId) {
  return isWhole(pageId, 1, MAX_PAGE_ID) ? `w${pageId}` : null;
}

// ---- base64url ----

function toBase64Url(bytes) {
  let text = "";
  let i = 0;
  for (; i + 2 < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
    text += ALPHABET[n >> 18] + ALPHABET[(n >> 12) & 63] + ALPHABET[(n >> 6) & 63] + ALPHABET[n & 63];
  }
  if (bytes.length - i === 1) {
    const n = bytes[i] << 16;
    text += ALPHABET[n >> 18] + ALPHABET[(n >> 12) & 63];
  } else if (bytes.length - i === 2) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8);
    text += ALPHABET[n >> 18] + ALPHABET[(n >> 12) & 63] + ALPHABET[(n >> 6) & 63];
  }
  return text;
}

// ---- varints ----

function pushVarint(out, value) {
  let rest = value;
  while (rest >= 128) {
    out.push((rest % 128) | 128);
    rest = Math.floor(rest / 128);
  }
  out.push(rest);
}

// ---- encoding ----

export function tablesOf(tables) {
  if (tables === null || typeof tables !== "object" || !Array.isArray(tables.trios) || !Array.isArray(tables.races)) {
    throw new KitError(KIT_ERRORS.tables);
  }
  return tables;
}

// The slots as [slotIndex, pageId, tier] triples in ascending slot order. Reads a list or an object per slot.
function canonicalSlots(slots) {
  if (!Array.isArray(slots)) throw new KitError(KIT_ERRORS.slots);
  if (slots.length > MAX_SLOTS) throw new KitError(KIT_ERRORS.slotCount);
  const list = [];
  for (let i = 0; i < slots.length; i += 1) {
    const entry = slots[i];
    let slotIndex;
    let pageId;
    let tier;
    if (Array.isArray(entry)) {
      if (entry.length !== 3) throw new KitError(KIT_ERRORS.slots);
      [slotIndex, pageId, tier] = entry;
    } else if (entry !== null && typeof entry === "object") {
      ({ slotIndex, pageId, tier } = entry);
    } else {
      throw new KitError(KIT_ERRORS.slots);
    }
    if (!isWhole(slotIndex, 0, MAX_SLOTS - 1)) throw new KitError(KIT_ERRORS.slotIndex);
    if (!isWhole(pageId, 1, MAX_PAGE_ID)) throw new KitError(KIT_ERRORS.pageId);
    if (!isWhole(tier, 0, MAX_TIER)) throw new KitError(KIT_ERRORS.tier);
    list.push([slotIndex, pageId, tier]);
  }
  list.sort((left, right) => left[0] - right[0]);
  for (let i = 1; i < list.length; i += 1) {
    if (list[i][0] === list[i - 1][0]) throw new KitError(KIT_ERRORS.duplicateSlot);
  }
  return list;
}

/**
 * Writes a kit as a link payload (the text after `#k=`).
 * @param {{v: 1, trio: string, race: string, level: number, slots: Array<[number, number, number]
 *   | {slotIndex: number, pageId: number, tier: number}>}} kit
 *   `trio` and `race` are spelled as in the tables; slots may come in any order and are written
 *   in ascending slot order; properties other than these are ignored (and never written).
 * @param {{trios: string[], races: string[]}} [tables]
 * @returns {string} base64url without padding, at most 214 characters
 * @throws {KitError} for any kit that is not exactly writable; nothing is returned then
 */
export function encodeKit(kit, tables = DEFAULT_TABLES) {
  if (kit === null || typeof kit !== "object") throw new KitError(KIT_ERRORS.kit);
  if (kit.v !== KIT_VERSION) throw new KitError(KIT_ERRORS.version);
  const { trios, races } = tablesOf(tables);
  const trio = trios.indexOf(kit.trio);
  if (trio < 0) throw new KitError(KIT_ERRORS.trio);
  const race = races.indexOf(kit.race);
  if (race < 0) throw new KitError(KIT_ERRORS.race);
  if (!isWhole(kit.level, MIN_LEVEL, MAX_LEVEL)) throw new KitError(KIT_ERRORS.level);
  const slots = canonicalSlots(kit.slots);
  const bytes = [KIT_VERSION];
  pushVarint(bytes, trio);
  pushVarint(bytes, race);
  pushVarint(bytes, kit.level);
  pushVarint(bytes, slots.length);
  for (const [slotIndex, pageId, tier] of slots) {
    pushVarint(bytes, slotIndex);
    pushVarint(bytes, pageId);
    pushVarint(bytes, tier);
  }
  const text = toBase64Url(bytes);
  if (text.length > MAX_FRAGMENT_LENGTH) throw new KitError(KIT_ERRORS.tooLong); // cannot happen: 214 is the most
  return text;
}
