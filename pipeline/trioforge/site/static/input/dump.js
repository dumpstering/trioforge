// Reader for the file that the game's "/outputfile inventory" command writes.
//
// The file is untrusted input: a visitor may drop any file, or a file that someone else made. So the reader
//   * checks the size before it reads a byte, and refuses anything over 1 MiB;
//   * never uploads, stores or shows the file or its name;
//   * is one forward pass over the text (no recursion, no regular expressions), so the time it takes grows
//     with the length of the file and nothing else;
//   * keeps what it learns only in Maps, Sets and plain frozen objects with fixed keys;
//   * says things only in fixed sentences and numbers: a message never contains a piece of the file.
//
// Names are DATA. A name is checked by its characters (letters, digits, spaces and a few marks), not by what it says,
// so a name such as "javascript:alert(1)" or "https://example.invalid/x" is accepted and comes back as exactly the
// text it is. This module never makes a link, a URL, markup or a style from a name, and the page must not either: it
// must never build a link or a URL from a dump name. Show a name with textContent only, and never put one into an
// href, a src, a location, a style, an attribute that holds code, or a query string.
//
// A file is either REFUSED (one plain error; nothing else is returned) or READ. Reading may SKIP single rows, each
// with a warning, so that one odd row does not cost a visitor the whole file. What is refused and what is skipped:
//
//   refused  too big, empty, binary, not text, too many lines, a line over 256 characters, the wrong header, a
//            blank or other line where the layout does not allow it, a row with the wrong number of columns, an
//            ID, Count or Slots that is not 1 to 10 digits or is out of range, an Empty row that is not
//            Empty/0/0/0, a position row with no row at all at its container's location, a file that looks cut
//            off, a file with no readable inventory row at all.
//   skipped  a row with a character outside TAB and 0x20-0x7E, a location this reader does not know (or lists a
//            second time), a row nested more than 3 levels deep, an item name no item has, an item with ID 0 or
//            Count 0, and the rows that sit in a skipped row or an Empty one. A skipped row still holds its
//            position in its container.
//   warned   things that are odd but readable: a tier above +10, sockets that do not fit the tier, a container
//            with fewer positions than its size, one ID with two names, a missing KeyRing section (and, when the
//            rows also stop before SharedBank6, that the file may be cut off), a last line with no line end, line ends
//            written CR CR LF (a CRLF file converted twice; read as one line end each)...
//
// What a row means. The dump has five columns: Location, Name, ID, Count, Slots. A row whose location ends in
// "-SlotN" sits inside the nearest earlier row (that is not Empty) whose location is exactly what comes before it.
// Whether position N is a bag position or a socket is decided by that parent: a bag prints every position from 1
// to its Slots; an item prints Slots 10 and only positions 1, 2 and 7 to 10. So a parent is a bag if it prints all
// its positions, or has any other Slots, or prints a position from 3 to 6, which an item never does (a bag that lost
// a row is still a bag). Whatever sits in a socket is socket content: never a bag, never owned, and neither is
// anything under it, however deep. The look of the location never decides.

export const LIMITS = Object.freeze({
  maxBytes: 1 << 20,
  maxLines: 20000,
  maxLineLength: 256,
  maxDepth: 3, // "-SlotN" suffixes after the root
  maxId: 2147483647,
  maxCount: 99999,
  warnCount: 1000,
  maxSlots: 80,
  maxLocationLength: 64,
  maxNameLength: 96,
  maxTier: 10,
  maxWarnings: 100,
  keyRingWarnRows: 200, // a guess at "more than usual": the game allows overcap, so this only warns
});

/** The 22 places of a kit, in the solver's order (Python's SLOT_INSTANCES), pairs numbered by occurrence. */
export const SOLVER_SLOT_IDS = Object.freeze([
  "HEAD", "FACE", "EAR1", "EAR2", "NECK", "SHOULDERS", "ARMS", "BACK", "WRIST1", "WRIST2", "HANDS", "FINGER1", "FINGER2",
  "CHEST", "LEGS", "FEET", "WAIST", "RANGE", "ANY1", "ANY2", "PRIMARY", "SECONDARY",
]);

/** The errors that do not name a line. */
export const ERRORS = Object.freeze({
  notAFile: "That is not a file the browser can read.",
  tooLarge: "This file is larger than 1 MiB, so it is not an inventory dump; nothing was read.",
  empty: "The file is empty; re-run /outputfile inventory.",
  readFailed: "The browser could not read the file.",
  binary: "This is a binary file, not the text file that /outputfile inventory writes.",
  encoding: "The file is not plain text that /outputfile inventory writes; re-run it and do not re-save the file.",
  notADump: "This is not an inventory dump: the first line is not the expected header; re-run /outputfile inventory.",
  noRows: "The file has no inventory rows that could be read; re-run /outputfile inventory.",
  tooManyLines: "The file has more than 20000 lines; re-run /outputfile inventory.",
  cutOff: "the file looks cut off; re-run /outputfile inventory",
  internal: "The file could not be read; re-run /outputfile inventory.",
});

const AGAIN = "; re-run /outputfile inventory.";
const lineError = {
  tooLong: (n) => `Line ${n} is longer than 256 characters${AGAIN}`,
  columns: (n) => `Line ${n} does not have the expected columns${AGAIN}`,
  digits: (n) => `Line ${n} has a number that is not 1 to 10 digits${AGAIN}`,
  range: (n) => `Line ${n} has a number that is out of range${AGAIN}`,
  empty: (n) => `Line ${n}: an Empty row must have ID, Count and Slots 0${AGAIN}`,
  orphan: (n) => `Line ${n} sits in a container or item row that is missing${AGAIN}`,
  blank: (n) => `Line ${n} is a blank line where none belongs${AGAIN}`,
  start: (n) => `Line ${n} is not where the KeyRing section should start${AGAIN}`,
};
const warning = {
  character: (n) => `Line ${n} was skipped: it has a character that /outputfile never writes.`,
  badName: (n) => `Line ${n} was skipped: the item name has a character that no item name uses.`,
  location: (n) => `Line ${n} was skipped: its location is not one this reader knows.`,
  listedTwice: (n) => `Line ${n} was skipped: that location was already listed.`,
  tooDeep: (n) => `Line ${n} was skipped: it is nested more than 3 levels deep.`,
  extraWorn: (n) => `Line ${n} was skipped: there are more rows for this worn slot than the game has.`,
  inSkipped: (n) => `Line ${n} was skipped: the row it belongs to is Empty or was skipped.`,
  idZero: (n) => `Line ${n} was skipped: the item has ID 0.`,
  countZero: (n) => `Line ${n} was skipped: the item has Count 0.`,
  tierHigh: (n, tier) => `Line ${n}: tier +${tier} is above +10, so it is read as +10.`,
  twoTiers: (n) => `Line ${n}: the name has two tier suffixes; only the last one is read.`,
  stoneTier: (n) => `Line ${n}: a stone with a tier; the tier is ignored.`,
  stoneOutside: (n) => `Line ${n}: a stone outside sockets 7 to 10.`,
  wornStone: (n) => `Line ${n}: a stone or ornament in a worn slot is ignored.`,
  sockets: (n) => `Line ${n}: the sockets listed do not match the item's tier.`,
  socketHigh: (n) => `Line ${n}: a socket number above 10.`,
  positions: (n) => `Line ${n}: the positions listed do not match the container's size.`,
  countBig: (n, count) => `Line ${n}: Count ${count} is above 1000.`,
  wornCount: (n) => `Line ${n}: a worn item with a Count above 1.`,
  idNames: (n, first) => `Line ${n}: this item ID was already used on line ${first} for a different name.`,
  order: "The worn slots are not in the usual order; they were read by name.",
  noKeyRing: "The file has no KeyRing section.",
  maybeCutOff: "The file has no KeyRing section and its rows stop before SharedBank6, so the file may be cut off; re-run /outputfile inventory.",
  doubledEnds: "The file has doubled line ends (CR CR LF); each was read as one line end.",
  lastLine: (n) => `Line ${n} has no line end, so the last line may be cut off; re-run /outputfile inventory.`,
  keyRingBig: (label) => `The ${label} key ring lists more than ${LIMITS.keyRingWarnRows} rows.`,
  more: (n) => `${n} more warnings are not listed.`,
};

const HEADER_LINE = "Location\tName\tID\tCount\tSlots";
const KEYRING_HEADER_LONG = "KeyRing\tName\tID\t"; // the real file ends this line with a tab
const KEYRING_HEADER_SHORT = "KeyRing\tName\tID";
const ITEM_SLOTS = 10; // the Slots column of every item that is not a bag
const EXALTATION = " (Exaltation)";
const ORNAMENT = "(Ornamentation)";

// ---- what a location can be ----------------------------------------------------------------------------------

const place = (name, slots = null) => Object.freeze({ place: name, slots });
/** The worn slots in the order the client lists them. Ear, Wrist, Fingers and Any Slot are pairs: the first row is the first place. */
const WORN_ROOTS = new Map([
  ["Any Slot", place("worn", ["ANY1", "ANY2"])],
  ["Ear", place("worn", ["EAR1", "EAR2"])],
  ["Head", place("worn", ["HEAD"])],
  ["Face", place("worn", ["FACE"])],
  ["Neck", place("worn", ["NECK"])],
  ["Shoulders", place("worn", ["SHOULDERS"])],
  ["Arms", place("worn", ["ARMS"])],
  ["Back", place("worn", ["BACK"])],
  ["Wrist", place("worn", ["WRIST1", "WRIST2"])],
  ["Range", place("worn", ["RANGE"])],
  ["Hands", place("worn", ["HANDS"])],
  ["Primary", place("worn", ["PRIMARY"])],
  ["Secondary", place("worn", ["SECONDARY"])],
  ["Fingers", place("worn", ["FINGER1", "FINGER2"])],
  ["Chest", place("worn", ["CHEST"])],
  ["Legs", place("worn", ["LEGS"])],
  ["Feet", place("worn", ["FEET"])],
  ["Waist", place("worn", ["WAIST"])],
  ["Ammo", place("worn", ["AMMO"])],
]);
const WORN_ORDER = "Any Slot|Ear|Head|Face|Ear|Neck|Shoulders|Arms|Back|Wrist|Wrist|Range|Hands|Primary|Secondary|Fingers|Fingers|Chest|Legs|Feet|Waist|Any Slot|Ammo";
const BAG = place("bag"); // General 1-12
const CURSOR = place("cursor"); // Held: whatever is on the cursor; never a worn slot
const BANK = place("bank"); // Bank1-24
const SHARED = place("sharedbank"); // SharedBank1-6
/** The key ring section's location column. The labels are ours, so that no label in the output is the file's text. */
const KEYRING_TYPES = new Map([
  ["Augmentation", "Augmentation"],
  ["Activated", "Activated"],
  ["Equipment", "Equipment"],
]);

/** The value of canonical decimal digits (1 or 2 of them, no leading zero) in text[from..], within 1..max; else 0. */
function smallNumber(text, from, max) {
  const length = text.length - from;
  if (length < 1 || length > 2) return 0;
  let value = 0;
  for (let i = from; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c < 48 || c > 57) return 0;
    value = value * 10 + (c - 48);
  }
  if (text.charCodeAt(from) === 48) return 0;
  return value >= 1 && value <= max ? value : 0;
}

function classifyRoot(root) {
  const worn = WORN_ROOTS.get(root);
  if (worn !== undefined) return worn;
  if (root === "Held") return CURSOR;
  if (root.startsWith("General ")) return smallNumber(root, 8, 12) ? BAG : null;
  if (root.startsWith("SharedBank")) return smallNumber(root, 10, 6) ? SHARED : null;
  if (root.startsWith("Bank")) return smallNumber(root, 4, 24) ? BANK : null;
  return null;
}

/** What a socket position is called: 1 and 2 are the ornament/legacy places, 7 to 10 the four sockets an item unlocks. */
function socketKind(position) {
  if (position <= 2) return "Ornament";
  if (position === 7) return "Focus";
  if (position === 8) return "Click";
  if (position === 9) return "Worn";
  if (position === 10) return "Proc";
  return "Unknown";
}

/** A character a location is made of: a letter, a digit, a space or a hyphen. */
function isLocationCharacter(c) {
  return (c >= 48 && c <= 57) || (c >= 65 && c <= 90) || (c >= 97 && c <= 122) || c === 32 || c === 45;
}

/**
 * Split "Root-SlotA-SlotB..." into the root and the numbers. Returns null for anything that is not that shape:
 * a position is 1 or 2 digits without a leading zero (1 to 99).
 */
function parseLocation(location) {
  const length = location.length;
  if (length < 1 || length > LIMITS.maxLocationLength) return null;
  let at = location.indexOf("-Slot");
  if (at === -1) return { root: location, path: [], lastStart: -1 };
  const root = location.slice(0, at);
  const path = [];
  let lastStart = -1;
  while (at !== -1) {
    let end = at + 5;
    const first = end;
    while (end < length) {
      const c = location.charCodeAt(end);
      if (c < 48 || c > 57) break;
      end++;
    }
    const digitCount = end - first;
    if (digitCount < 1 || digitCount > 2 || location.charCodeAt(first) === 48) return null;
    path.push(digitCount === 1 ? location.charCodeAt(first) - 48 : (location.charCodeAt(first) - 48) * 10 + (location.charCodeAt(first + 1) - 48));
    lastStart = at;
    if (end === length) break;
    if (!location.startsWith("-Slot", end)) return null;
    at = end;
  }
  return { root, path, lastStart };
}

// ---- what a name can be --------------------------------------------------------------------------------------

/** The characters an item name may have: the catalog's, and a little more. */
const NAME_OK = new Uint8Array(128);
for (let c = 48; c <= 57; c++) NAME_OK[c] = 1; // digits
for (let c = 65; c <= 90; c++) NAME_OK[c] = NAME_OK[c + 32] = 1; // letters
for (const mark of " '`,:.-()*#/!?&+") NAME_OK[mark.charCodeAt(0)] = 1;

/** If `name` ends in " +N" or " +N*" (N from 1 to 999, no leading zero, one space before the plus), the name without it and N; else null. */
function peelTier(name) {
  let end = name.length;
  let star = false;
  if (end > 0 && name.charCodeAt(end - 1) === 42) {
    star = true;
    end--;
  }
  let first = end;
  while (first > 0) {
    const c = name.charCodeAt(first - 1);
    if (c < 48 || c > 57) break;
    first--;
  }
  const digitCount = end - first;
  if (digitCount < 1 || digitCount > 3 || first < 2) return null;
  if (name.charCodeAt(first - 1) !== 43 || name.charCodeAt(first - 2) !== 32) return null;
  if (first >= 3 && name.charCodeAt(first - 3) === 32) return null; // two spaces: the name would end in a space
  if (name.charCodeAt(first) === 48) return null; // the game prints nothing for +0
  let value = 0;
  for (let i = first; i < end; i++) value = value * 10 + (name.charCodeAt(i) - 48);
  return { base: name.slice(0, first - 2) + (star ? "*" : ""), value };
}

/**
 * Read a name column. Returns null if it cannot be an item name (a character no item has, empty, over 96
 * characters, a space at either end); else the name without its tier suffix (the star stays: Club* is not Club),
 * the tier, and what kind of row it is. A stone keeps its " (Exaltation)" marker in the name so that nothing can
 * mistake it for the item it came from.
 */
function parseName(raw) {
  const length = raw.length;
  if (length < 1 || length > LIMITS.maxNameLength) return null;
  for (let i = 0; i < length; i++) {
    const c = raw.charCodeAt(i);
    if (c > 127 || NAME_OK[c] !== 1) return null;
  }
  if (raw.charCodeAt(0) === 32 || raw.charCodeAt(length - 1) === 32) return null;

  let name = raw;
  let tier = 0;
  let tierOver = 0;
  let doubleTier = false;
  let stone = false;
  let stoneTier = false;
  const outer = peelTier(name);
  if (outer !== null) name = outer.base;
  // a stone's name may end in a star, as an ornament's does: "Name (Exaltation)*"
  const star = name.endsWith("*");
  const marked = star ? name.slice(0, -1) : name;
  if (marked.endsWith(EXALTATION)) {
    // "Name (Exaltation)", "Name (Exaltation) +N" and "Name +N (Exaltation)", each with or without the star: a stone,
    // which never has a tier
    stone = true;
    stoneTier = outer !== null;
    let source = marked.slice(0, marked.length - EXALTATION.length);
    const inner = peelTier(source);
    if (inner !== null) {
      stoneTier = true;
      source = inner.base;
    }
    name = source + EXALTATION + (star ? "*" : "");
  } else if (outer !== null) {
    tier = outer.value > LIMITS.maxTier ? LIMITS.maxTier : outer.value;
    tierOver = outer.value > LIMITS.maxTier ? outer.value : 0;
    doubleTier = peelTier(name) !== null;
  }
  const ornament = !stone && (name.endsWith(ORNAMENT) || name.endsWith(ORNAMENT + "*"));
  return { name, tier, tierOver, doubleTier, stone, stoneTier, ornament };
}

/** The value of a number column (1 to 10 digits, nothing else), or -1. */
function digitsValue(text) {
  const length = text.length;
  if (length < 1 || length > 10) return -1;
  let value = 0;
  for (let i = 0; i < length; i++) {
    const c = text.charCodeAt(i);
    if (c < 48 || c > 57) return -1;
    value = value * 10 + (c - 48);
  }
  return value;
}

// ---- bytes to text -------------------------------------------------------------------------------------------

class Refusal {
  constructor(message) {
    this.message = message;
  }
}

const refusal = (message) => {
  throw new Refusal(message);
};

/**
 * Bytes to text. Every byte (or UTF-16 unit) is one character, whatever it is: the line check below then decides
 * which rows have a character the game never writes. Nothing is decoded as UTF-8, so a stray byte spoils its row
 * and no more.
 */
function decode(bytes) {
  const n = bytes.length;
  if (n === 0) refusal(ERRORS.empty);
  if (n > LIMITS.maxBytes) refusal(ERRORS.tooLarge);
  const [b0, b1, b2, b3] = [bytes[0], bytes[1], bytes[2], bytes[3]];
  if (
    (b0 === 0x50 && b1 === 0x4b && b2 === 0x03 && b3 === 0x04) || // zip (and Office files)
    (b0 === 0x1f && b1 === 0x8b) || // gzip
    (b0 === 0x25 && b1 === 0x50 && b2 === 0x44 && b3 === 0x46) || // PDF
    (b0 === 0x4d && b1 === 0x5a) || // Windows program
    (b0 === 0x89 && b1 === 0x50 && b2 === 0x4e && b3 === 0x47) || // PNG
    (b0 === 0x7f && b1 === 0x45 && b2 === 0x4c && b3 === 0x46) // ELF program
  ) {
    refusal(ERRORS.binary);
  }
  if ((b0 === 0xff && b1 === 0xfe && b2 === 0 && b3 === 0) || (b0 === 0 && b1 === 0 && b2 === 0xfe && b3 === 0xff)) refusal(ERRORS.encoding); // UTF-32
  let text;
  if (b0 === 0xff && b1 === 0xfe) text = fromUtf16(bytes, false);
  else if (b0 === 0xfe && b1 === 0xff) text = fromUtf16(bytes, true);
  else text = fromBytes(bytes, b0 === 0xef && b1 === 0xbb && b2 === 0xbf ? 3 : 0); // a UTF-8 mark is dropped, once
  if (text.length === 0) refusal(ERRORS.empty);
  return text;
}

function fromBytes(bytes, from) {
  let text = "";
  for (let i = from; i < bytes.length; i += 8192) text += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(bytes.length, i + 8192)));
  return text;
}

function fromUtf16(bytes, bigEndian) {
  const payload = bytes.length - 2;
  if (payload % 2 !== 0) refusal(ERRORS.encoding);
  const units = new Uint16Array(payload / 2);
  for (let i = 0; i < units.length; i++) {
    const a = bytes[2 + 2 * i];
    const b = bytes[3 + 2 * i];
    units[i] = bigEndian ? (a << 8) | b : (b << 8) | a;
  }
  let text = "";
  for (let i = 0; i < units.length; i += 8192) text += String.fromCharCode.apply(null, units.subarray(i, Math.min(units.length, i + 8192)));
  return text;
}

// ---- the reader ----------------------------------------------------------------------------------------------

const HEADER_STATE = 0;
const MAIN_STATE = 1;
const GAP_STATE = 2; // after the blank line: the KeyRing header, or the end of the file
const KEYRING_STATE = 3;

function readText(text) {
  const textLength = text.length;
  const warnings = [];
  let suppressed = 0;
  const warn = (message) => {
    if (warnings.length < LIMITS.maxWarnings) warnings.push(message);
    else suppressed++;
  };

  const rows = []; // the rows that were read, in file order
  const kidPositions = []; // per row: every position printed under it (Empty and skipped rows too)
  const kidRows = []; // per row: the indexes of the rows under it
  const lastAt = new Map(); // location -> index of the latest row read there (an Empty row is never a parent)
  const skippedAt = new Set(); // locations of skipped and Empty rows, so that the rows inside them are skipped, not orphans
  const listedTop = new Set(); // top-level locations (other than worn slots) already listed
  const wornSeen = new Map(); // worn root -> how many rows it has had
  const wornOrder = [];
  const nameOfId = new Map(); // id -> { name, line } of the first row with that ID (stones aside)
  const clashed = new Set();
  const keyRingRows = new Map();

  let state = HEADER_STATE;
  let mainRead = 0;
  let gapBlanks = 0;
  let keyRingBlankLine = 0;
  let lineNo = 0;
  let unterminated = false; // the line being read is the last one and has no line end
  let doubledEnds = false; // some line end was CR CR LF

  /** Stop reading the file. `truncation`: this kind of damage is what a file cut short looks like. */
  const refuse = (message, truncation = false) => refusal(truncation && unterminated ? ERRORS.cutOff : message);

  /**
   * Find where a row sits. Returns { info, path, slot, parent } or null when the row is skipped (with a warning
   * if `announce`). `strict` rows may refuse the file: a position row without its container, or rows nested too deep.
   */
  function locate(location, announce, strict) {
    const parsed = parseLocation(location);
    if (parsed === null) {
      if (announce) warn(warning.location(lineNo));
      return null;
    }
    if (parsed.path.length > LIMITS.maxDepth) {
      if (announce) warn(warning.tooDeep(lineNo));
      return null;
    }
    const info = classifyRoot(parsed.root);
    if (info === null) {
      if (announce) warn(warning.location(lineNo));
      return null;
    }
    if (parsed.path.length === 0) {
      if (info.slots !== null) {
        const count = (wornSeen.get(parsed.root) || 0) + 1;
        wornSeen.set(parsed.root, count);
        if (wornOrder.length < 40) wornOrder.push(parsed.root);
        if (count > info.slots.length) {
          if (announce) warn(warning.extraWorn(lineNo));
          lastAt.delete(location);
          skippedAt.add(location);
          return null;
        }
        return { info, path: parsed.path, slot: info.slots[count - 1], parent: -1 };
      }
      if (listedTop.has(location)) {
        if (announce) warn(warning.listedTwice(lineNo));
        skippedAt.add(location); // what is printed under this second row is skipped with it, not taken for orphans
        return null;
      }
      listedTop.add(location);
      return { info, path: parsed.path, slot: null, parent: -1 };
    }
    const parentLocation = location.slice(0, parsed.lastStart);
    const parent = lastAt.get(parentLocation);
    if (parent === undefined) {
      if (skippedAt.has(parentLocation)) {
        if (announce) warn(warning.inSkipped(lineNo));
        skippedAt.add(location);
        lastAt.delete(location);
        return null;
      }
      if (strict) refuse(lineError.orphan(lineNo));
      return null;
    }
    const position = parsed.path[parsed.path.length - 1];
    const taken = kidPositions[parent];
    if (taken.includes(position)) {
      if (announce) warn(warning.listedTwice(lineNo));
      skippedAt.add(location);
      return null;
    }
    taken.push(position);
    return { info, path: parsed.path, slot: null, parent };
  }

  /**
   * A row that cannot be read keeps the place it has, so that its bag is still a bag and its rows are skipped. The place
   * is the Location column when that is clean, or a clean location followed by nothing but stray characters (a
   * byte at the end of "Bank3-Slot4"); a stray byte inside the location, or one followed by more of it, names no place.
   */
  function skipUnreadable(lineText) {
    warn(warning.character(lineNo));
    const tab = lineText.indexOf("\t");
    const column = tab === -1 ? lineText : lineText.slice(0, tab);
    let end = 0;
    while (end < column.length && isLocationCharacter(column.charCodeAt(end))) end++;
    for (let i = end; i < column.length; i++) if (isLocationCharacter(column.charCodeAt(i))) return;
    const location = column.slice(0, end);
    if (location.length < 1 || location.length > LIMITS.maxLocationLength) return;
    if (locate(location, false, false) !== null) {
      skippedAt.add(location);
      lastAt.delete(location);
    }
  }

  /** The row of a name that is not an item's, an ID of 0 and so on: skipped, and what sits inside it with it. */
  function skipRow(location, message) {
    warn(message);
    skippedAt.add(location);
    lastAt.delete(location);
  }

  /** The checks that belong to a name, and the row itself. */
  function addRow(section, location, where, name, id, count, slots) {
    const index = rows.length;
    const row = {
      line: lineNo,
      section,
      location,
      place: section === "keyring" ? "keyring" : where.info.place,
      slot: where.slot,
      path: where.path,
      id,
      name: name.name,
      tier: name.tier,
      count,
      slots,
      stone: name.stone,
      ornament: name.ornament,
      socket: null,
      container: false,
      parent: where.parent,
    };
    if (name.tierOver > 0) warn(warning.tierHigh(lineNo, name.tierOver));
    if (name.doubleTier) warn(warning.twoTiers(lineNo));
    if (name.stoneTier) warn(warning.stoneTier(lineNo));
    if (count > LIMITS.warnCount) warn(warning.countBig(lineNo, count));
    if (where.slot !== null && where.slot !== "AMMO" && count > 1) warn(warning.wornCount(lineNo));
    if (!name.stone) {
      const earlier = nameOfId.get(id);
      if (earlier === undefined) nameOfId.set(id, { name: name.name, line: lineNo });
      else if (earlier.name !== name.name && !clashed.has(id)) {
        clashed.add(id);
        warn(warning.idNames(lineNo, earlier.line));
      }
    }
    rows.push(row);
    kidPositions.push([]);
    kidRows.push([]);
    if (where.parent >= 0) kidRows[where.parent].push(index);
    lastAt.set(location, index);
  }

  function readMainRow(lineText, bad) {
    if (bad) {
      skipUnreadable(lineText);
      return;
    }
    const f = lineText.split("\t");
    if (f.length !== 5) refuse(lineError.columns(lineNo), true);
    const id = digitsValue(f[2]);
    const count = digitsValue(f[3]);
    const slots = digitsValue(f[4]);
    if (id < 0 || count < 0 || slots < 0) refuse(lineError.digits(lineNo), true);
    if (id > LIMITS.maxId || count > LIMITS.maxCount || slots > LIMITS.maxSlots) refuse(lineError.range(lineNo));
    const location = f[0];
    const isEmpty = f[1] === "Empty";
    if (isEmpty && (id !== 0 || count !== 0 || slots !== 0)) refuse(lineError.empty(lineNo));
    const where = locate(location, !isEmpty, true);
    if (where === null) return;
    if (isEmpty) {
      // Nothing sits in an Empty place. An earlier row at the same location (the first Ear of a pair) is no parent of
      // what is printed after this row, and what is printed under it is skipped, not given to that earlier row.
      lastAt.delete(location);
      skippedAt.add(location);
      mainRead++;
      return;
    }
    const name = parseName(f[1]);
    if (name === null) return skipRow(location, warning.badName(lineNo));
    if (id === 0) return skipRow(location, warning.idZero(lineNo));
    if (count === 0) return skipRow(location, warning.countZero(lineNo));
    addRow("main", location, where, name, id, count, slots);
    mainRead++;
  }

  function readKeyRingRow(lineText, bad) {
    if (bad) {
      warn(warning.character(lineNo));
      return;
    }
    const f = lineText.split("\t");
    if (f.length !== 3) refuse(lineError.columns(lineNo), true);
    const id = digitsValue(f[2]);
    if (id < 0) refuse(lineError.digits(lineNo), true);
    if (id > LIMITS.maxId) refuse(lineError.range(lineNo));
    if (f[1] === "Empty") {
      if (id !== 0) refuse(lineError.empty(lineNo));
      return;
    }
    const label = KEYRING_TYPES.get(f[0]);
    if (label === undefined) return warn(warning.location(lineNo));
    const name = parseName(f[1]);
    if (name === null) return warn(warning.badName(lineNo));
    if (id === 0) return warn(warning.idZero(lineNo));
    keyRingRows.set(label, (keyRingRows.get(label) || 0) + 1);
    addRow("keyring", label, { info: null, path: [], slot: null, parent: -1 }, name, id, 1, null);
  }

  // ---- one pass over the lines
  let pos = 0;
  while (pos < textLength) {
    const start = pos;
    const limit = Math.min(textLength, start + LIMITS.maxLineLength + 1);
    let end = start;
    let bad = false;
    let ender = 0; // the length of the line end that follows: 0 none, 1 CR or LF, 2 CRLF, 3 or more CR CR LF
    while (end < limit) {
      const c = text.charCodeAt(end);
      if (c === 10) {
        ender = 1;
        break;
      }
      if (c === 13) {
        // CR LF is one line end, and so is CR CR LF (a CRLF file converted once more); a few CRs at most are looked at
        let k = end + 1;
        while (k < textLength && k - end <= 3 && text.charCodeAt(k) === 13) k++;
        if (k < textLength && text.charCodeAt(k) === 10) {
          ender = k - end + 1;
          if (k - end > 1) doubledEnds = true;
        } else ender = 1;
        break;
      }
      if ((c < 32 && c !== 9) || c > 126) bad = true;
      end++;
    }
    lineNo++;
    if (ender === 0 && end - start > LIMITS.maxLineLength) refusal(lineError.tooLong(lineNo));
    if (lineNo > LIMITS.maxLines) refusal(ERRORS.tooManyLines);
    pos = end + ender;
    unterminated = ender === 0;

    if (state === HEADER_STATE) {
      if (bad) refusal(ERRORS.encoding);
      if (text.slice(start, end) !== HEADER_LINE) refusal(ERRORS.notADump);
      state = MAIN_STATE;
      continue;
    }
    if (end === start) {
      // a blank line: one ends the rows, none may stand inside a section
      if (state === MAIN_STATE) {
        state = GAP_STATE;
        gapBlanks = 1;
      } else if (state === GAP_STATE) gapBlanks++;
      else if (keyRingBlankLine === 0) keyRingBlankLine = lineNo;
      continue;
    }
    if (state === GAP_STATE) {
      const lineText = bad ? "" : text.slice(start, end);
      if (lineText !== KEYRING_HEADER_LONG && lineText !== KEYRING_HEADER_SHORT) refuse(lineError.start(lineNo), true);
      if (gapBlanks > 1) refuse(lineError.blank(lineNo));
      state = KEYRING_STATE;
      continue;
    }
    if (state === KEYRING_STATE && keyRingBlankLine !== 0) refusal(lineError.blank(keyRingBlankLine));
    if (state === MAIN_STATE) readMainRow(text.slice(start, end), bad);
    else readKeyRingRow(text.slice(start, end), bad);
  }

  if (mainRead === 0) refusal(ERRORS.noRows);
  // A last line with no line end whose columns are all there is read, but a cut inside its last field would also look like this
  if (unterminated && lineNo > 1) warn(warning.lastLine(lineNo));
  if (doubledEnds) warn(warning.doubledEnds);
  // No key ring section: complete if the rows got as far as the last shared bank slot, else most likely a file cut at a line end
  if (state !== KEYRING_STATE) warn(listedTop.has("SharedBank6") ? warning.noKeyRing : warning.maybeCutOff);
  if (wornOrder.join("|") !== WORN_ORDER) warn(warning.order);
  for (const [label, count] of keyRingRows) if (count > LIMITS.keyRingWarnRows) warn(warning.keyRingBig(label));

  // ---- what the printed positions say about each parent: a bag, or an item with sockets. One pass in file order,
  // so that a parent is settled before its children are: socket content is never a bag, and everything under a
  // socket (a stone, an ornament, anything) is socket content too.
  for (let i = 0; i < rows.length; i++) {
    const printed = kidPositions[i];
    if (printed.length === 0) continue;
    const row = rows[i];
    const sorted = printed.slice().sort((a, b) => a - b);
    let exact = sorted.length === row.slots;
    for (let k = 0; exact && k < sorted.length; k++) if (sorted[k] !== k + 1) exact = false;
    let itemPosition = false; // a position that only a bag has: items print 1, 2 and 7 to 10
    for (const p of sorted) if (p >= 3 && p <= 6) itemPosition = true;
    const inside = row.socket !== null || row.stone || row.ornament;
    // A bag prints every position from 1 to its size. An item prints Slots 10 whatever it is, and only the positions
    // above; anything else with positions under it is a bag that did not print them all.
    row.container = !inside && (exact || row.slots !== ITEM_SLOTS || itemPosition);
    if (row.container) {
      if (!exact) warn(warning.positions(row.line));
      continue;
    }
    if (!inside) {
      const sockets = [];
      for (const p of sorted) if (p >= 7) sockets.push(p);
      const wanted = Math.min(row.tier, 4);
      let fits = sockets.length === wanted;
      for (let k = 0; fits && k < wanted; k++) if (sockets[k] !== 7 + k) fits = false;
      if (!fits) warn(warning.sockets(row.line));
      if (sorted[sorted.length - 1] > 10) warn(warning.socketHigh(row.line));
    }
    for (const index of kidRows[i]) {
      const child = rows[index];
      const at = child.path[child.path.length - 1];
      child.socket = Object.freeze({ index: at, kind: inside ? "Nested" : socketKind(at) });
      if (!inside && child.stone && (at < 7 || at > 10)) warn(warning.stoneOutside(child.line));
    }
  }

  const worn = new Map();
  const owned = new Map();
  for (const row of rows) {
    Object.freeze(row.path);
    Object.freeze(row);
    if (row.slot !== null) {
      if (row.stone || row.ornament) warn(warning.wornStone(row.line));
      else worn.set(row.slot, row);
    }
    if (row.stone || row.ornament || row.socket !== null) continue; // sockets and stones are not things one owns
    let list = owned.get(row.id);
    if (list === undefined) {
      list = [];
      owned.set(row.id, list);
    }
    list.push(Object.freeze({ tier: row.tier, count: row.count, location: row.location, place: row.place, slot: row.slot, name: row.name, line: row.line }));
  }
  if (suppressed > 0) warnings.push(warning.more(suppressed));
  return { rows, worn, owned, warnings, errors: [] };
}

const failed = (message) => ({ rows: [], worn: new Map(), owned: new Map(), warnings: [], errors: [message] });

function asBytes(input) {
  if (ArrayBuffer.isView(input)) return new Uint8Array(input.buffer, input.byteOffset, input.byteLength);
  if (Object.prototype.toString.call(input) === "[object ArrayBuffer]") return new Uint8Array(input);
  return null;
}

/**
 * Read the bytes of a dump. Never throws.
 *
 * @returns {{rows: object[], worn: Map, owned: Map, warnings: string[], errors: string[]}}
 *   `errors` has one message when the file was refused, and then everything else is empty. Otherwise:
 *
 *   `rows`      the rows that were read (the Empty ones are not rows), in file order, frozen. A row is
 *               { line, section: "main" | "keyring", location, place, slot, path, id, name, tier, count, slots,
 *                 stone, ornament, socket, container, parent }:
 *                 line      the 1-based line number in the file
 *                 location  the Location column as written ("Bank1-Slot2"), or the key ring type ("Equipment")
 *                 place     "worn" | "bag" (General 1-12) | "bank" | "sharedbank" | "cursor" (Held) | "keyring"
 *                 slot      a solver slot id (see SOLVER_SLOT_IDS, or "AMMO") for a worn slot's own row, else null
 *                 path      the position numbers after the root, [] for a top-level row; at most 3
 *                 name      the name without its tier suffix; the star stays ("Club*"); a stone ends in " (Exaltation)"
 *                 tier      0 to 10
 *                 slots     the Slots column (bag size for a bag); null on a key ring row
 *                 stone / ornament   an exaltation stone, an ornament: neither is gear
 *                 socket    null, or { index, kind } for socket content: a row under an item (decided by its parent),
 *                           and every row anywhere under socket content, a stone or an ornament. kind is "Ornament"
 *                           (positions 1, 2), "Focus", "Click", "Worn", "Proc" (7 to 10), "Unknown" (above 10), or
 *                           "Nested" for a row further down
 *                 container true for a bag: it printed every position from 1 to its Slots, or its Slots is not 10, or
 *                           it printed a position from 3 to 6. Never true for socket content, a stone or an ornament
 *                 parent    the index in `rows` of the row it sits in, or -1
 *   `worn`      solver slot id -> row, for the filled worn slots. Pairs (EAR, WRIST, FINGER, ANY) are told apart by
 *               their order in the file. The Held row (the cursor) is never in it.
 *   `owned`     item ID (a number: the dump's own ID, the same across tiers) -> one entry per copy, in file order:
 *               { tier, count, location, place, slot, name, line }. Stones, ornaments and whatever sits in a socket
 *               are not in it.
 *   `warnings`  plain sentences, at most 100, then "N more warnings are not listed."
 */
export function parseDumpBytes(input) {
  try {
    const bytes = asBytes(input);
    if (bytes === null) return failed(ERRORS.notAFile);
    // the limit is this function's own, not the caller's: an export that is handed bytes looks at none of them past 1 MiB
    if (bytes.length > LIMITS.maxBytes) return failed(ERRORS.tooLarge);
    return readText(decode(bytes));
  } catch (error) {
    return failed(error instanceof Refusal ? error.message : ERRORS.internal);
  }
}

/**
 * Read a dump from a File or Blob. The size is checked first, and a file over 1 MiB is refused without being read.
 * Never rejects; the file's name is never looked at.
 */
export async function parseDump(file) {
  try {
    if (file === null || (typeof file !== "object" && typeof file !== "function")) return failed(ERRORS.notAFile);
    const size = file.size;
    if (typeof size !== "number" || !Number.isSafeInteger(size) || size < 0) return failed(ERRORS.notAFile);
    if (size > LIMITS.maxBytes) return failed(ERRORS.tooLarge);
    if (size === 0) return failed(ERRORS.empty);
    if (typeof file.slice !== "function") return failed(ERRORS.notAFile);
    let buffer;
    try {
      buffer = await file.slice(0, LIMITS.maxBytes + 1).arrayBuffer();
    } catch {
      return failed(ERRORS.readFailed);
    }
    if (Object.prototype.toString.call(buffer) !== "[object ArrayBuffer]") return failed(ERRORS.readFailed);
    if (buffer.byteLength > LIMITS.maxBytes) return failed(ERRORS.tooLarge);
    return parseDumpBytes(new Uint8Array(buffer));
  } catch {
    return failed(ERRORS.internal);
  }
}
