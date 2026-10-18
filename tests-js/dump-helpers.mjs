// Shared helpers for the dump parser and matcher tests (not a test file itself).
// Every name, ID and file name used with these helpers is invented.
import { readFileSync } from "node:fs";

export const HEADER = "Location\tName\tID\tCount\tSlots";
export const KEYRING_HEADER = "KeyRing\tName\tID\t";
export const MAX_BYTES = 1048576;
export const CUT_OFF = "the file looks cut off; re-run /outputfile inventory";

// The real dump is CRLF. git stores these fixtures with LF (the repository normalises text files), so the loader
// puts the CRLF back: the parser is always tested on the real line ending, whatever the checkout did.
export function fixture(name) {
  const raw = readFileSync(new URL(`../fixtures/dumps/${name}.txt`, import.meta.url), "latin1");
  return raw.split("\r\n").join("\n").split("\n").join("\r\n");
}

/** ASCII/Latin-1 text -> bytes, one byte per character. */
export const bytes = (text) => new Uint8Array(Buffer.from(text, "latin1"));
/** Text -> UTF-8 bytes (for the tests that need non-ASCII characters on the wire). */
export const utf8 = (text) => new Uint8Array(Buffer.from(text, "utf8"));

/** Text -> UTF-16 bytes, little or big endian, with or without a byte order mark. */
export function utf16(text, { big = false, bom = true } = {}) {
  const out = new Uint8Array((text.length + (bom ? 1 : 0)) * 2);
  let p = 0;
  const put = (unit) => {
    if (big) {
      out[p++] = unit >> 8;
      out[p++] = unit & 0xff;
    } else {
      out[p++] = unit & 0xff;
      out[p++] = unit >> 8;
    }
  };
  if (bom) put(0xfeff);
  for (let i = 0; i < text.length; i++) put(text.charCodeAt(i));
  return out;
}

export const file = (data, name = "dump.txt") => new File([data], name);

/** Join lines with CRLF and end with CRLF, like the real dump. */
export const crlf = (lines) => lines.join("\r\n") + "\r\n";

/** A dump made of the header, the given main rows, and (optionally) the key ring section. */
export function dump(mainRows, keyRows = null) {
  const lines = [HEADER, ...mainRows];
  if (keyRows !== null) lines.push("", KEYRING_HEADER, ...keyRows);
  return crlf(lines);
}

/** A tab-separated main row. */
export const row = (loc, name, id, count = 1, slots = 10) => [loc, name, String(id), String(count), String(slots)].join("\t");
export const empty = (loc) => row(loc, "Empty", 0, 0, 0);
/** A tab-separated key ring row. */
export const keyRow = (type, name, id) => [type, name, String(id)].join("\t");

/**
 * Grow a dump that ends with CRLF and has a key ring section to exactly `size` characters by adding Equipment rows
 * with valid names. (Every character is one byte, as in a real dump.)
 */
export function padTo(text, size) {
  const make = (nameLength, k) => keyRow("Equipment", "N".repeat(nameLength), 500000 + k) + "\r\n";
  const fixed = make(1, 0).length - 1; // the length of a row apart from its name
  let out = text;
  let k = 0;
  while (size - out.length > 220) out += make(90, k++);
  let rest = size - out.length;
  if (rest > 115) {
    const first = Math.floor(rest / 2);
    out += make(first - fixed, k++);
    rest -= first;
  }
  out += make(rest - fixed, k++);
  if (out.length !== size) throw new Error(`padTo built ${out.length} characters, not ${size}`);
  return out;
}

/** Replace the line with the given 1-based number. */
export function withLine(text, n, replacement) {
  const lines = text.split("\r\n");
  lines[n - 1] = replacement;
  return lines.join("\r\n");
}

/** Insert lines before the given 1-based line number. */
export function insertAt(text, n, ...added) {
  const lines = text.split("\r\n");
  lines.splice(n - 1, 0, ...added);
  return lines.join("\r\n");
}

export const wornSlotKeys = new Set([
  "HEAD", "FACE", "EAR1", "EAR2", "NECK", "SHOULDERS", "ARMS", "BACK", "WRIST1", "WRIST2", "HANDS", "FINGER1",
  "FINGER2", "CHEST", "LEGS", "FEET", "WAIST", "RANGE", "ANY1", "ANY2", "PRIMARY", "SECONDARY", "AMMO",
]);
const PLACES = new Set(["worn", "bag", "bank", "sharedbank", "cursor", "keyring"]);
const KEYRING_LABELS = new Set(["Augmentation", "Activated", "Equipment"]);
const PAIRS = { "Any Slot": ["ANY1", "ANY2"], Ear: ["EAR1", "EAR2"], Wrist: ["WRIST1", "WRIST2"], Fingers: ["FINGER1", "FINGER2"] };
const SINGLE = { Head: "HEAD", Face: "FACE", Neck: "NECK", Shoulders: "SHOULDERS", Arms: "ARMS", Back: "BACK", Range: "RANGE", Hands: "HANDS", Primary: "PRIMARY", Secondary: "SECONDARY", Chest: "CHEST", Legs: "LEGS", Feet: "FEET", Waist: "WAIST", Ammo: "AMMO" };
/** The place a root belongs to, by the rules of the game's layout (the parser has its own table; this one is independent). */
function placeOfRoot(root) {
  if (Object.hasOwn(PAIRS, root) || Object.hasOwn(SINGLE, root)) return "worn";
  if (root === "Held") return "cursor";
  if (/^General ([1-9]|1[0-2])$/.test(root)) return "bag";
  if (/^SharedBank[1-6]$/.test(root)) return "sharedbank";
  if (/^Bank([1-9]|1[0-9]|2[0-4])$/.test(root)) return "bank";
  return null;
}
const NAME_CHARS = new Set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 '`,:.-()*#/!?&+");

/**
 * Check every promise of the parser's output shape without using expect (the fuzz tests call this tens of
 * thousands of times). Returns the list of problems found; an empty list means the result is well formed.
 */
export function problemsIn(r) {
  const out = [];
  const keys = Object.keys(r).sort().join();
  if (keys !== "errors,owned,rows,warnings,worn") return [`keys: ${keys}`];
  if (!Array.isArray(r.rows) || !Array.isArray(r.warnings) || !Array.isArray(r.errors)) return ["not arrays"];
  if (!(r.worn instanceof Map) || !(r.owned instanceof Map)) return ["not maps"];
  for (const list of [r.warnings, r.errors]) {
    for (const m of list) {
      if (typeof m !== "string" || m.length < 1 || m.length > 200) out.push(`message length: ${String(m).length}`);
      else for (let i = 0; i < m.length; i++) if (m.charCodeAt(i) < 0x20 || m.charCodeAt(i) > 0x7e) out.push("message has a non-printable character");
    }
  }
  if (r.errors.length > 1) out.push("more than one error");
  if (r.warnings.length > 101) out.push(`warnings: ${r.warnings.length}`);
  if (r.errors.length > 0) {
    if (r.rows.length || r.worn.size || r.owned.size || r.warnings.length) out.push("data returned together with an error");
    return out;
  }
  if (r.rows.length > 20000) out.push("too many rows");
  const byLine = new Map();
  r.rows.forEach((row, i) => {
    if (!Object.isFrozen(row)) out.push(`row ${i} is not frozen`);
    if (!Number.isInteger(row.line) || row.line < 2 || row.line > 20000) out.push(`row ${i} line`);
    if (byLine.has(row.line)) out.push(`row ${i} line repeats`);
    byLine.set(row.line, row);
    if (row.section !== "main" && row.section !== "keyring") out.push(`row ${i} section`);
    if (!PLACES.has(row.place)) out.push(`row ${i} place`);
    if (typeof row.location !== "string" || row.location.length < 1 || row.location.length > 64) out.push(`row ${i} location`);
    if (row.slot !== null && !wornSlotKeys.has(row.slot)) out.push(`row ${i} slot`);
    if (!Number.isInteger(row.id) || row.id < 1 || row.id > 2147483647) out.push(`row ${i} id`);
    if (!Number.isInteger(row.tier) || row.tier < 0 || row.tier > 10) out.push(`row ${i} tier`);
    if (!Number.isInteger(row.count) || row.count < 1 || row.count > 99999) out.push(`row ${i} count`);
    if (typeof row.name !== "string" || row.name.length < 1 || row.name.length > 96) out.push(`row ${i} name length`);
    else {
      for (let k = 0; k < row.name.length; k++) if (!NAME_CHARS.has(row.name[k])) out.push(`row ${i} name char`);
      if (row.name[0] === " " || row.name[row.name.length - 1] === " ") out.push(`row ${i} name edge space`);
    }
    if (!Array.isArray(row.path) || row.path.length > 3 || row.path.some((p) => !Number.isInteger(p) || p < 1 || p > 99)) out.push(`row ${i} path`);
    if (!Number.isInteger(row.parent) || row.parent < -1 || row.parent >= i) out.push(`row ${i} parent`);
    if (typeof row.stone !== "boolean" || typeof row.ornament !== "boolean" || typeof row.container !== "boolean") out.push(`row ${i} flags`);
    if (row.socket !== null && !(Number.isInteger(row.socket.index) && typeof row.socket.kind === "string")) out.push(`row ${i} socket`);
    if (row.socket !== null && row.parent < 0) out.push(`row ${i} socket without parent`);
    // where the row sits must be what its location says
    if (row.section === "keyring") {
      if (!KEYRING_LABELS.has(row.location) || row.place !== "keyring" || row.path.length !== 0 || row.parent !== -1 || row.slot !== null) out.push(`row ${i} key ring shape`);
      return;
    }
    const cut = row.location.indexOf("-Slot");
    const root = cut < 0 ? row.location : row.location.slice(0, cut);
    if (placeOfRoot(root) !== row.place) out.push(`row ${i} place ${row.place} for root ${root}`);
    if (row.path.map((p) => `-Slot${p}`).join("") !== (cut < 0 ? "" : row.location.slice(cut))) out.push(`row ${i} path does not spell its location`);
    if (row.path.length === 0) {
      if (row.parent !== -1) out.push(`row ${i} top-level row with a parent`);
      const own = Object.hasOwn(PAIRS, root) ? PAIRS[root] : Object.hasOwn(SINGLE, root) ? [SINGLE[root]] : null;
      if (own !== null && !own.includes(row.slot)) out.push(`row ${i} worn root ${root} has slot ${row.slot}`);
    } else {
      const parent = r.rows[row.parent];
      if (row.slot !== null) out.push(`row ${i} slot on a nested row`);
      if (!parent || parent.location !== row.location.slice(0, row.location.lastIndexOf("-Slot"))) out.push(`row ${i} parent is not the row at its parent location`);
      else if (parent.container && row.socket !== null) out.push(`row ${i} is socket content in a bag`);
      else if (!parent.container && row.socket === null) out.push(`row ${i} sits under an item but is not socket content`);
    }
    // socket content, stones and ornaments are never bags
    if ((row.socket !== null || row.stone || row.ornament) && row.container) out.push(`row ${i} is a bag but is socket content, a stone or an ornament`);
  });
  for (const [slot, row] of r.worn) {
    if (!wornSlotKeys.has(slot)) out.push(`worn key ${slot}`);
    if (!r.rows.includes(row) || row.slot !== slot) out.push(`worn ${slot} is not its row`);
  }
  let entries = 0;
  for (const [id, list] of r.owned) {
    if (!Number.isInteger(id) || !Array.isArray(list) || list.length === 0) out.push("owned shape");
    for (const e of list) {
      entries++;
      const src = byLine.get(e.line);
      if (!src || src.id !== id || src.tier !== e.tier || src.count !== e.count || src.name !== e.name || src.location !== e.location) out.push(`owned entry for line ${e.line} does not match its row`);
      else if (src.stone || src.ornament || src.socket !== null) out.push(`owned entry for line ${e.line} is a stone, ornament or socket content`);
      if (!Object.isFrozen(e)) out.push("owned entry is not frozen");
    }
  }
  const expected = r.rows.filter((x) => !x.stone && !x.ornament && x.socket === null).length;
  if (entries !== expected) out.push(`owned entries ${entries} != ownable rows ${expected}`);
  // nothing that sits anywhere under socket content, a stone or an ornament is owned
  const insideSocket = (row) => {
    for (let x = row; x.parent >= 0; x = r.rows[x.parent]) if (x.socket !== null || r.rows[x.parent].stone || r.rows[x.parent].ornament) return true;
    return false;
  };
  for (const [, list] of r.owned) for (const e of list) if (insideSocket(byLine.get(e.line))) out.push(`owned holds line ${e.line}, which sits inside socket content`);
  for (const k in {}) out.push(`Object.prototype has an enumerable key: ${k}`);
  return out;
}
