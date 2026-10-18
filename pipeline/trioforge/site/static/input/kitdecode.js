/**
 * The reading half of the kit link codec: `decodeKit` turns the text after `#k=` into a kit, or says why not.
 *
 * The format, the tables, the messages and the writing half are input/kitcode.js's (read its header first: it
 * says what a link is and how the page uses it). This module is only what a visitor who opens a link needs,
 * and what no other visitor does: the Upgrade section's code writes links (Share, Remember) and never reads
 * one, so the reader is a module of its own that only the panel of a shared kit imports, and in the build a
 * chunk of its own, loaded by a dynamic import when a kit link is opened.
 *
 * Every kit has exactly one spelling, and the decoder accepts nothing else: the alphabet is exact, the unused
 * bits of the last character are zero, a varint is the shortest one for its value (and at most 5 bytes), the
 * slots ascend, and every byte must be consumed. So decoding then encoding gives back the same link.
 *
 * The module imports kitcode.js and nothing else, has no regular expressions, never decodes percent-escapes
 * and never throws: a link it cannot read is a list of errors (the messages of KIT_ERRORS) and no kit.
 */

import { ALPHABET, DEFAULT_TABLES, KIT_ERRORS, KIT_VERSION, KitError, MAX_FRAGMENT_LENGTH, MAX_LEVEL, MAX_PAGE_ID, MAX_SLOTS, MAX_TIER, MIN_LEVEL, tablesOf } from "./kitcode.js";

const MAX_VARINT_BYTES = 5;

// ---- base64url ----

const INDEX_OF = new Int8Array(128).fill(-1);
for (let i = 0; i < ALPHABET.length; i += 1) INDEX_OF[ALPHABET.charCodeAt(i)] = i;

// The text is at most MAX_FRAGMENT_LENGTH characters long when this runs.
function fromBase64Url(text) {
  const length = text.length;
  for (let i = 0; i < length; i += 1) {
    const code = text.charCodeAt(i);
    if (code > 127 || INDEX_OF[code] < 0) throw new KitError(KIT_ERRORS.alphabet);
  }
  if (length % 4 === 1) throw new KitError(KIT_ERRORS.length);
  const bytes = new Uint8Array(Math.floor((length * 3) / 4));
  let bits = 0;
  let held = 0;
  let written = 0;
  for (let i = 0; i < length; i += 1) {
    held = (held << 6) | INDEX_OF[text.charCodeAt(i)];
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes[written] = (held >> bits) & 0xff;
      written += 1;
      held &= (1 << bits) - 1;
    }
  }
  if (held !== 0) throw new KitError(KIT_ERRORS.tail);
  return bytes;
}

// ---- varints ----

// Reads one canonical varint of at most MAX_VARINT_BYTES bytes (so a value below 2^35).
function readVarint(cursor) {
  const { bytes } = cursor;
  let value = 0;
  let scale = 1;
  for (let i = 0; i < MAX_VARINT_BYTES; i += 1) {
    if (cursor.position >= bytes.length) throw new KitError(KIT_ERRORS.truncated);
    const byte = bytes[cursor.position];
    cursor.position += 1;
    value += (byte & 0x7f) * scale;
    if ((byte & 0x80) === 0) {
      if (i > 0 && byte === 0) throw new KitError(KIT_ERRORS.overlong);
      return value;
    }
    scale *= 128;
  }
  throw new KitError(KIT_ERRORS.varintTooLong);
}

// ---- decoding ----

// The structure of a link: {trio, race, level, slots: [[slotIndex, pageId, tier]]}, or a KitError.
function parseLink(fragment, tables) {
  if (typeof fragment !== "string") throw new KitError(KIT_ERRORS.notText);
  if (fragment.length === 0) throw new KitError(KIT_ERRORS.empty);
  if (fragment.length > MAX_FRAGMENT_LENGTH) throw new KitError(KIT_ERRORS.tooLong);
  const { trios, races } = tablesOf(tables);
  const bytes = fromBase64Url(fragment);
  if (bytes[0] !== KIT_VERSION) throw new KitError(KIT_ERRORS.version);
  const cursor = { bytes, position: 1 };
  const trioIndex = readVarint(cursor);
  if (trioIndex >= trios.length) throw new KitError(KIT_ERRORS.trio);
  const raceIndex = readVarint(cursor);
  if (raceIndex >= races.length) throw new KitError(KIT_ERRORS.race);
  const level = readVarint(cursor);
  if (level < MIN_LEVEL || level > MAX_LEVEL) throw new KitError(KIT_ERRORS.level);
  const count = readVarint(cursor);
  if (count > MAX_SLOTS) throw new KitError(KIT_ERRORS.slotCount);
  const slots = [];
  let previous = -1;
  for (let i = 0; i < count; i += 1) {
    const slotIndex = readVarint(cursor);
    if (slotIndex >= MAX_SLOTS) throw new KitError(KIT_ERRORS.slotIndex);
    if (slotIndex === previous) throw new KitError(KIT_ERRORS.duplicateSlot);
    if (slotIndex < previous) throw new KitError(KIT_ERRORS.slotOrder);
    previous = slotIndex;
    const pageId = readVarint(cursor);
    if (pageId < 1 || pageId > MAX_PAGE_ID) throw new KitError(KIT_ERRORS.pageId);
    const tier = readVarint(cursor);
    if (tier > MAX_TIER) throw new KitError(KIT_ERRORS.tier);
    slots.push([slotIndex, pageId, tier]);
  }
  if (cursor.position !== bytes.length) throw new KitError(KIT_ERRORS.trailing);
  return { trio: trios[trioIndex], race: races[raceIndex], level, slots };
}

/**
 * Reads a link payload (the text after `#k=`) and looks each page id up in the item table.
 * Never throws. A link that is not in its one canonical spelling, or that has a field out of range,
 * gives `kit: null` and one message in `errors` (see KIT_ERRORS); no partial kit is returned.
 * @param {unknown} fragment the payload, nothing else (no "#k=" prefix, no percent-escapes)
 * @param {{get(key: string): unknown}} items a Map of catalog key ("w<pageId>") to item
 * @param {{trios: string[], races: string[]}} [tables]
 * @returns {{kit: null | {v: 1, trio: string, race: string, level: number, slots: Array<
 *     {slotIndex: number, pageId: number, tier: number, key: string, item: unknown}
 *   | {slotIndex: number, pageId: number, tier: number, unknown: true}>}, unknown: number[], errors: string[]}}
 *   `slots` ascend by slot index; `unknown` lists the slot index of every placeholder (an item the
 *   table does not hold), which keeps its page id and tier so the kit can be shared again.
 */
export function decodeKit(fragment, items, tables = DEFAULT_TABLES) {
  try {
    const parsed = parseLink(fragment, tables);
    if (items === null || typeof items !== "object" || typeof items.get !== "function") {
      throw new KitError(KIT_ERRORS.items);
    }
    const slots = [];
    const unknown = [];
    for (const [slotIndex, pageId, tier] of parsed.slots) {
      const key = `w${pageId}`;
      const item = items.get(key);
      if (item === undefined || item === null) {
        unknown.push(slotIndex);
        slots.push({ slotIndex, pageId, tier, unknown: true });
      } else {
        slots.push({ slotIndex, pageId, tier, key, item });
      }
    }
    return { kit: { v: KIT_VERSION, trio: parsed.trio, race: parsed.race, level: parsed.level, slots }, unknown, errors: [] };
  } catch (error) {
    return { kit: null, unknown: [], errors: [error instanceof KitError ? error.message : KIT_ERRORS.internal] };
  }
}
