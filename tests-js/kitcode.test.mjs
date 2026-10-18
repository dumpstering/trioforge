import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  CLASS_CODES,
  DEFAULT_TABLES,
  KIT_ERRORS,
  KIT_VERSION,
  KitError,
  MAX_FRAGMENT_LENGTH,
  MAX_LEVEL,
  MAX_PAGE_ID,
  MAX_SLOTS,
  MAX_TIER,
  RACE_CODES,
  SLOT_ORDER,
  TRIO_CODES,
  encodeKit,
  keyFromPageId,
  pageIdFromKey,
} from "../pipeline/trioforge/site/static/input/kitcode.js";
import { decodeKit } from "../pipeline/trioforge/site/static/input/kitdecode.js";
import { expectWithin, stopwatch } from "./timing.mjs";

const MODULE_URL = new URL("../pipeline/trioforge/site/static/input/kitcode.js", import.meta.url);

// ---- helpers that do not use the module under test: they are the format, written a second time ----

// Canonical unsigned LEB128.
function leb(value) {
  const out = [];
  let rest = BigInt(value);
  do {
    let byte = Number(rest & 0x7fn);
    rest >>= 7n;
    if (rest > 0n) byte |= 0x80;
    out.push(byte);
  } while (rest > 0n);
  return out;
}

// The same number one byte longer: the continuation bit on the last byte, then a 0x00.
function overlong(value) {
  const bytes = leb(value);
  bytes[bytes.length - 1] |= 0x80;
  bytes.push(0x00);
  return bytes;
}

// A number in a field list is written as a canonical varint; an array is written as the raw bytes it holds.
function bytesOf(version, ...fields) {
  const out = [version];
  for (const field of fields) {
    if (Array.isArray(field)) out.push(...field);
    else out.push(...leb(field));
  }
  return out;
}
const toFragment = (bytes) => Buffer.from(bytes).toString("base64url");
const fragOf = (version, ...fields) => toFragment(bytesOf(version, ...fields));

function binom(n, k) {
  let result = 1;
  for (let i = 1; i <= k; i += 1) result = (result * (n - k + i)) / i;
  return result;
}
// The documented trio index: c1 + C(c2, 2) + C(c3, 3) over the zero-based class positions c1 < c2 < c3.
function trioIndexOf(code) {
  const [a, b, c] = code.split("-").map((part) => CLASS_CODES.indexOf(part.toUpperCase()));
  return a + binom(b, 2) + binom(c, 3);
}

function makeRng(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const pick = (rng, n) => Math.floor(rng() * n);
function shuffle(rng, list) {
  const copy = [...list];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = pick(rng, i + 1);
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}
// Page ids of every varint length, one to five bytes.
const PAGE_ID_RANGES = [
  [1, 127],
  [128, 16383],
  [16384, 2097151],
  [2097152, 268435455],
  [268435456, 2147483647],
];
function randomPageId(rng) {
  const [low, high] = PAGE_ID_RANGES[pick(rng, PAGE_ID_RANGES.length)];
  return low + pick(rng, high - low + 1);
}
function randomKit(rng) {
  const classes = [];
  while (classes.length < 3) {
    const c = pick(rng, 16);
    if (!classes.includes(c)) classes.push(c);
  }
  classes.sort((a, b) => a - b);
  const slotIndexes = shuffle(rng, [...Array(22).keys()]).slice(0, pick(rng, 23));
  return {
    v: 1,
    trio: classes.map((c) => CLASS_CODES[c].toLowerCase()).join("-"),
    race: RACE_CODES[pick(rng, 15)],
    level: 1 + pick(rng, 65),
    slots: slotIndexes.map((slotIndex) => [slotIndex, randomPageId(rng), pick(rng, 11)]),
  };
}
// The bytes the format asks for, slots in ascending order.
function expectedBytes(kit) {
  const slots = [...kit.slots].sort((a, b) => a[0] - b[0]);
  return bytesOf(
    1,
    trioIndexOf(kit.trio),
    RACE_CODES.indexOf(kit.race),
    kit.level,
    slots.length,
    ...slots.flat(),
  );
}

// A table in which every key is known, and one with a few items.
class EveryItem extends Map {
  get(key) {
    return { key };
  }
}
const itemsOf = (ids) => new Map(ids.map((id) => [`w${id}`, { name: `Test item ${id}`, id }]));

// pal-mnk-ber (472), Ogre (9), level 50, then fields.
const HEAD = [472, 9, 50];
const GOOD = "AdgDCTIDAHAEAru2BAAV_____wcK"; // slots [0, 112, 4], [2, 72507, 0], [21, 2147483647, 10]
const GOOD_ITEMS = itemsOf([112, 72507, 2147483647]);

function reject(fragment, message, ...table) {
  const result = decodeKit(fragment, table.length > 0 ? table[0] : GOOD_ITEMS);
  expect(result.errors).toEqual([message]);
  expect(result.kit).toBeNull();
  expect(result.unknown).toEqual([]);
}
function expectKitError(fn, message) {
  let caught;
  try {
    fn();
  } catch (error) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(KitError);
  expect(caught.message).toBe(message);
}

// ---- the constants ----

describe("constants", () => {
  it("states the limits of version 1", () => {
    expect(KIT_VERSION).toBe(1);
    expect(MAX_FRAGMENT_LENGTH).toBe(2048);
    expect(MAX_SLOTS).toBe(22);
    expect(MAX_TIER).toBe(10);
    expect(MAX_LEVEL).toBe(65);
    expect(MAX_PAGE_ID).toBe(2 ** 31 - 1);
  });

  it("CLASS_CODES is the Python class list, in class-id order", () => {
    const text = readFileSync(new URL("../pipeline/trioforge/classes.py", import.meta.url), "utf8");
    const start = text.indexOf("CLASS_NAMES = {");
    const block = text.slice(start, text.indexOf("}", start));
    const codes = [...block.matchAll(/^\s*"([A-Z]{3})":/gm)].map((match) => match[1]);
    expect(codes).toHaveLength(16);
    expect([...CLASS_CODES]).toEqual(codes);
  });

  it("RACE_CODES is the race table of rules/races.json, in file order", () => {
    const races = JSON.parse(readFileSync(new URL("../rules/races.json", import.meta.url), "utf8")).races;
    expect(races).toHaveLength(15);
    expect([...RACE_CODES]).toEqual(races.map((race) => race.code));
  });

  it("TRIO_CODES lists all 560 class triples in the documented, append-stable order", () => {
    expect(TRIO_CODES).toHaveLength(560);
    expect(new Set(TRIO_CODES).size).toBe(560);
    TRIO_CODES.forEach((code, index) => {
      const classes = code.split("-");
      expect(classes).toHaveLength(3);
      expect(code).toBe(code.toLowerCase());
      const positions = classes.map((part) => CLASS_CODES.indexOf(part.toUpperCase()));
      expect(positions.every((p) => p >= 0)).toBe(true);
      expect(positions[0] < positions[1] && positions[1] < positions[2]).toBe(true);
      expect(trioIndexOf(code)).toBe(index);
    });
    expect(TRIO_CODES[0]).toBe("war-clr-pal");
    expect(TRIO_CODES[559]).toBe("enc-bst-ber");
    expect(TRIO_CODES.indexOf("pal-mnk-ber")).toBe(472);
  });

  it("the tables are frozen, so no other module can shift an index", () => {
    expect(Object.isFrozen(CLASS_CODES)).toBe(true);
    expect(Object.isFrozen(RACE_CODES)).toBe(true);
    expect(Object.isFrozen(TRIO_CODES)).toBe(true);
    expect(Object.isFrozen(DEFAULT_TABLES)).toBe(true);
    expect(DEFAULT_TABLES.trios).toBe(TRIO_CODES);
    expect(DEFAULT_TABLES.races).toBe(RACE_CODES);
    expect(Object.isFrozen(KIT_ERRORS)).toBe(true);
  });

  it("every error message is a distinct, non-empty string", () => {
    const messages = Object.values(KIT_ERRORS);
    expect(messages.length).toBeGreaterThanOrEqual(20);
    expect(messages.every((m) => typeof m === "string" && m.length > 0)).toBe(true);
    expect(new Set(messages).size).toBe(messages.length);
  });
});

// ---- the slot order ----

describe("slot order", () => {
  // The kit order of SLOT_INSTANCES in pipeline/trioforge/model/items.py, copied here on purpose. A link
  // stores a position in this list, so the list can never change without a new link version: every old
  // link would silently move its items into other slots.
  const FIXED_SLOT_ORDER = [
    "HEAD", "FACE", "EAR", "EAR", "NECK", "SHOULDERS", "ARMS", "BACK", "WRIST", "WRIST", "HANDS",
    "FINGER", "FINGER", "CHEST", "LEGS", "FEET", "WAIST", "RANGE", "ANY", "ANY", "PRIMARY", "SECONDARY",
  ];

  it("is a frozen list of the 22 places of a kit, and a slot index is a position in it", () => {
    expect(Object.isFrozen(SLOT_ORDER)).toBe(true);
    expect(SLOT_ORDER).toHaveLength(22);
    expect(SLOT_ORDER).toHaveLength(MAX_SLOTS);
  });

  it("is the order old links were written against: a literal copy, changed only with a new link version", () => {
    expect([...SLOT_ORDER]).toEqual(FIXED_SLOT_ORDER);
  });

  it("is the kit order of the Python model: SLOT_INSTANCES of items.py, read from the source", () => {
    const text = readFileSync(new URL("../pipeline/trioforge/model/items.py", import.meta.url), "utf8");
    // The kit order is SLOT_GROUPS with each group repeated by its count. If that derivation changes, so may the order.
    expect(text).toContain("SLOT_INSTANCES: tuple[str, ...] = tuple(name for name, count in SLOT_GROUPS for _ in range(count))");
    const start = text.indexOf("SLOT_GROUPS: tuple[tuple[str, int], ...] = (");
    expect(start).toBeGreaterThanOrEqual(0);
    const block = text.slice(start, text.indexOf("\n)", start));
    const groups = [...block.matchAll(/\("([A-Z]+)",\s*(\d+)\)/g)].map((match) => [match[1], Number(match[2])]);
    expect(groups).toHaveLength(18); // the 18 slot groups
    const instances = groups.flatMap(([name, count]) => new Array(count).fill(name));
    expect(
      [...SLOT_ORDER],
      "the kit order of items.py differs from SLOT_ORDER: reordering it would move the items of every old kit link; keep the order, or add a new link version",
    ).toEqual(instances);
  });
});

// ---- page-id keys ----

describe("catalog keys and page ids", () => {
  it("maps w<pageid> to the number and back", () => {
    expect(pageIdFromKey("w112")).toBe(112);
    expect(pageIdFromKey("w72507")).toBe(72507);
    expect(pageIdFromKey("w2147483647")).toBe(2147483647);
    expect(keyFromPageId(112)).toBe("w112");
    expect(keyFromPageId(2147483647)).toBe("w2147483647");
  });

  it("refuses anything that is not exactly w, then a positive integer without leading zeros", () => {
    for (const key of [
      "w0", "w01", "w-1", "w1.5", "w1e3", "w 1", "w1 ", " w1", "W1", "x1", "w", "", "1", "w+1", "w0x10",
      "w2147483648", "w99999999999", "w٣", "w１", "w1\n", "wNaN", "constructor", "__proto__",
    ]) {
      expect(pageIdFromKey(key)).toBeNull();
    }
    for (const notText of [undefined, null, 5, {}, [], ["w1"], Symbol("w1"), 10n]) {
      expect(pageIdFromKey(notText)).toBeNull();
    }
    for (const id of [0, -1, 1.5, 2 ** 31, NaN, Infinity, "5", null, undefined, 2 ** 53]) {
      expect(keyFromPageId(id)).toBeNull();
    }
  });
});

// ---- the wire format ----

describe("wire format", () => {
  it("matches the golden vectors", () => {
    expect(encodeKit({ v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [] })).toBe("AdgDCTIA");
    expect(
      encodeKit({
        v: 1,
        trio: "pal-mnk-ber",
        race: "OGR",
        level: 50,
        slots: [[0, 112, 4], [2, 72507, 0], [21, 2147483647, 10]],
      }),
    ).toBe(GOOD);
    expect(encodeKit({ v: 1, trio: "war-clr-pal", race: "HUM", level: 1, slots: [] })).toBe("AQAAAQA");
  });

  it("decodes the golden vectors", () => {
    const result = decodeKit(GOOD, GOOD_ITEMS);
    expect(result.errors).toEqual([]);
    expect(result.unknown).toEqual([]);
    expect(result.kit).toMatchObject({ v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50 });
    expect(result.kit.slots.map((s) => [s.slotIndex, s.pageId, s.tier, s.key])).toEqual([
      [0, 112, 4, "w112"],
      [2, 72507, 0, "w72507"],
      [21, 2147483647, 10, "w2147483647"],
    ]);
    expect(decodeKit("AQAAAQA", GOOD_ITEMS).kit).toEqual({
      v: 1, trio: "war-clr-pal", race: "HUM", level: 1, slots: [],
    });
  });

  it("is byte 0 = version, then varints for trio, race, level and slot count, then three varints per slot, and nothing else", () => {
    const rng = makeRng(7);
    for (let i = 0; i < 300; i += 1) {
      const kit = randomKit(rng);
      const bytes = [...Buffer.from(encodeKit(kit), "base64url")];
      expect(bytes).toEqual(expectedBytes(kit));
      expect(bytes[0]).toBe(1);
    }
  });

  it("writes the slots in ascending slot order whatever order they are given in", () => {
    const slots = [[21, 900, 10], [3, 5, 0], [0, 7, 4], [12, 2147483647, 9]];
    const shuffled = encodeKit({ v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots });
    const sorted = encodeKit({
      v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [...slots].sort((a, b) => a[0] - b[0]),
    });
    expect(shuffled).toBe(sorted);
  });

  it("accepts slots as [slotIndex, pageId, tier] lists or as {slotIndex, pageId, tier} objects, and ignores other properties", () => {
    const asLists = encodeKit({ v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [[0, 112, 4], [2, 72507, 0]] });
    const asObjects = encodeKit({
      v: 1,
      trio: "pal-mnk-ber",
      race: "OGR",
      level: 50,
      score: 123456,
      slots: [
        { slotIndex: 0, pageId: 112, tier: 4, item: { name: "x" }, key: "w112" },
        { slotIndex: 2, pageId: 72507, tier: 0, unknown: true },
      ],
    });
    expect(asObjects).toBe(asLists);
  });

  it("does not change the kit it is given", () => {
    const kit = { v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [[5, 9, 1], [1, 8, 2]] };
    const before = structuredClone(kit);
    encodeKit(kit);
    expect(kit).toEqual(before);
  });
});

// ---- round trips ----

describe("round trip", () => {
  it("decode(encode(kit)) gives the kit back in canonical order, and encode(decode(link)) gives the link back, on 2,000 random kits", () => {
    const rng = makeRng(20261014);
    const items = new EveryItem();
    for (let i = 0; i < 2000; i += 1) {
      const kit = randomKit(rng);
      const fragment = encodeKit(kit);
      expect(fragment.length).toBeLessThanOrEqual(MAX_FRAGMENT_LENGTH);
      expect(fragment).toMatch(/^[A-Za-z0-9_-]+$/);
      expect(fragment).toBe(toFragment(expectedBytes(kit)));
      const decoded = decodeKit(fragment, items);
      expect(decoded.errors).toEqual([]);
      expect(decoded.unknown).toEqual([]);
      const sorted = [...kit.slots].sort((a, b) => a[0] - b[0]);
      expect(decoded.kit.v).toBe(1);
      expect(decoded.kit.trio).toBe(kit.trio);
      expect(decoded.kit.race).toBe(kit.race);
      expect(decoded.kit.level).toBe(kit.level);
      expect(decoded.kit.slots.map((s) => [s.slotIndex, s.pageId, s.tier])).toEqual(sorted);
      expect(encodeKit(decoded.kit)).toBe(fragment);
    }
  });

  it("every trio with every race survives, 8,400 pairs", () => {
    const items = new EveryItem();
    let pairs = 0;
    for (const trio of TRIO_CODES) {
      for (const race of RACE_CODES) {
        const fragment = encodeKit({ v: 1, trio, race, level: 50, slots: [[0, 112, 4]] });
        const kit = decodeKit(fragment, items).kit;
        expect(kit.trio).toBe(trio);
        expect(kit.race).toBe(race);
        pairs += 1;
      }
    }
    expect(pairs).toBe(560 * 15);
  });

  it("every level, tier and slot index survives", () => {
    const items = new EveryItem();
    for (let level = 1; level <= 65; level += 1) {
      const fragment = encodeKit({ v: 1, trio: "pal-mnk-ber", race: "OGR", level, slots: [] });
      expect(decodeKit(fragment, items).kit.level).toBe(level);
    }
    for (let slotIndex = 0; slotIndex <= 21; slotIndex += 1) {
      for (let tier = 0; tier <= 10; tier += 1) {
        const fragment = encodeKit({ v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [[slotIndex, 1, tier]] });
        const slot = decodeKit(fragment, items).kit.slots[0];
        expect([slot.slotIndex, slot.tier]).toEqual([slotIndex, tier]);
      }
    }
  });
});

// ---- limits ----

describe("limits", () => {
  const maxKit = {
    v: 1,
    trio: TRIO_CODES[559],
    race: RACE_CODES[14],
    level: 65,
    slots: [...Array(22).keys()].map((slotIndex) => [slotIndex, 2147483647, 10]),
  };

  it("the longest legal kit is 214 characters, far under the 2,048 cap", () => {
    // 1 version + 2 trio + 1 race + 1 level + 1 count + 22 slots of (1 + 5 + 1) bytes = 160 bytes.
    const fragment = encodeKit(maxKit);
    expect(fragment).toHaveLength(214);
    expect(fragment.length).toBeLessThanOrEqual(2048);
    const decoded = decodeKit(fragment, new EveryItem());
    expect(decoded.errors).toEqual([]);
    expect(decoded.kit.slots).toHaveLength(22);
  });

  it("no random kit is longer than that", () => {
    const rng = makeRng(99);
    let longest = 0;
    for (let i = 0; i < 5000; i += 1) longest = Math.max(longest, encodeKit(randomKit(rng)).length);
    expect(longest).toBeLessThanOrEqual(214);
  });

  it("refuses 23 slots when encoding and when decoding, and accepts 22", () => {
    const slots = [...Array(23).keys()].map((i) => [i % 22, 5, 1]);
    expectKitError(() => encodeKit({ ...maxKit, slots }), KIT_ERRORS.slotCount);
    reject(fragOf(1, ...HEAD, 23, ...slots.flat()), KIT_ERRORS.slotCount);
    reject(fragOf(1, ...HEAD, 23), KIT_ERRORS.slotCount); // refused before any slot is read
    expect(() => encodeKit(maxKit)).not.toThrow();
  });

  it("a slot count of 22 with fewer slots behind it ends too early", () => {
    const body = [...Array(21).keys()].flatMap((i) => [i, 5, 1]);
    reject(fragOf(1, ...HEAD, 22, ...body), KIT_ERRORS.truncated);
  });

  it("refuses a link of 2,049 characters before looking at what is in it", () => {
    reject("A".repeat(2049), KIT_ERRORS.tooLong);
    reject("!".repeat(2049), KIT_ERRORS.tooLong); // the length is judged before the alphabet
    reject("A".repeat(1_000_000), KIT_ERRORS.tooLong);
    const watch = stopwatch();
    decodeKit("é".repeat(5_000_000), GOOD_ITEMS);
    expectWithin(watch.stop(), 200, "a link of 5 million characters is refused");
  });

  it("lets 2,048 characters past the length check (a legal kit never needs them, so the content then fails)", () => {
    const result = decodeKit("A".repeat(2048), GOOD_ITEMS);
    expect(result.kit).toBeNull();
    expect(result.errors).not.toEqual([KIT_ERRORS.tooLong]);
    // 2,048 characters carry 1,536 bytes: a 6-byte kit followed by 1,530 trailing bytes.
    const padded = toFragment([...bytesOf(1, ...HEAD, 0), ...new Array(1530).fill(0)]);
    expect(padded).toHaveLength(2048);
    reject(padded, KIT_ERRORS.trailing);
  });

  it("carries a slot index, a page id and a tier per slot and no count, location or quantity", () => {
    const kit = { v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [[3, 300, 7]], quantity: 40, location: "bank", count: 9 };
    const bytes = [...Buffer.from(encodeKit(kit), "base64url")];
    expect(bytes).toEqual(bytesOf(1, 472, 9, 50, 1, 3, 300, 7));
  });
});

// ---- field ranges ----

describe("field ranges when decoding", () => {
  it("accepts every boundary value", () => {
    const items = new EveryItem();
    const edge = [
      fragOf(1, 559, 14, 65, 1, 21, 2147483647, 10),
      fragOf(1, 0, 0, 1, 1, 0, 1, 0),
      fragOf(1, 0, 0, 1, 0),
    ];
    for (const fragment of edge) expect(decodeKit(fragment, items).errors).toEqual([]);
  });

  it.each([
    ["trio", [560, 561, 2 ** 31, 2 ** 35 - 1], (v) => fragOf(1, v, 9, 50, 0), KIT_ERRORS.trio],
    ["race", [15, 99, 2 ** 31, 2 ** 35 - 1], (v) => fragOf(1, 472, v, 50, 0), KIT_ERRORS.race],
    ["level", [0, 66, 100, 1024, 2 ** 31], (v) => fragOf(1, 472, 9, v, 0), KIT_ERRORS.level],
    ["slot count", [23, 100, 2 ** 31], (v) => fragOf(1, 472, 9, 50, v), KIT_ERRORS.slotCount],
    ["slot index", [22, 23, 99, 2 ** 31], (v) => fragOf(1, ...HEAD, 1, v, 112, 4), KIT_ERRORS.slotIndex],
    ["page id", [0, 2 ** 31, 2 ** 32, 2 ** 35 - 1], (v) => fragOf(1, ...HEAD, 1, 0, v, 4), KIT_ERRORS.pageId],
    ["tier", [11, 12, 127, 1_000_000, 2 ** 35 - 1], (v) => fragOf(1, ...HEAD, 1, 0, 112, v), KIT_ERRORS.tier],
  ])("rejects a %s out of range, naming the field", (field, values, build, message) => {
    for (const value of values) {
      const result = decodeKit(build(value), GOOD_ITEMS);
      expect(result.kit).toBeNull();
      expect(result.errors).toEqual([message]);
    }
  });

  it("names the field in each message", () => {
    expect(KIT_ERRORS.trio).toMatch(/trio/);
    expect(KIT_ERRORS.race).toMatch(/race/);
    expect(KIT_ERRORS.level).toMatch(/level/);
    expect(KIT_ERRORS.slotCount).toMatch(/22 slots/);
    expect(KIT_ERRORS.slotIndex).toMatch(/slot index/);
    expect(KIT_ERRORS.pageId).toMatch(/page id/);
    expect(KIT_ERRORS.tier).toMatch(/tier/);
  });

  it("rejects a number of six bytes or more in any field, without reading on", () => {
    const six = [0xff, 0xff, 0xff, 0xff, 0xff, 0x01];
    reject(fragOf(1, six, 9, 50, 0), KIT_ERRORS.varintTooLong);
    reject(fragOf(1, 472, six, 50, 0), KIT_ERRORS.varintTooLong);
    reject(fragOf(1, 472, 9, six, 0), KIT_ERRORS.varintTooLong);
    reject(fragOf(1, 472, 9, 50, six), KIT_ERRORS.varintTooLong);
    reject(fragOf(1, ...HEAD, 1, six, 112, 4), KIT_ERRORS.varintTooLong);
    reject(fragOf(1, ...HEAD, 1, 0, six, 4), KIT_ERRORS.varintTooLong);
    reject(fragOf(1, ...HEAD, 1, 0, 112, six), KIT_ERRORS.varintTooLong);
  });

  it("rejects duplicate and out-of-order slot indices as different faults", () => {
    reject(fragOf(1, ...HEAD, 2, 3, 10, 1, 3, 11, 2), KIT_ERRORS.duplicateSlot);
    reject(fragOf(1, ...HEAD, 2, 5, 10, 1, 3, 11, 2), KIT_ERRORS.slotOrder);
    reject(fragOf(1, ...HEAD, 3, 0, 10, 1, 7, 11, 2, 6, 12, 3), KIT_ERRORS.slotOrder);
    reject(fragOf(1, ...HEAD, 3, 0, 10, 1, 7, 11, 2, 7, 12, 3), KIT_ERRORS.duplicateSlot);
    reject(fragOf(1, ...HEAD, 2, 21, 10, 1, 0, 11, 2), KIT_ERRORS.slotOrder);
    expect(decodeKit(fragOf(1, ...HEAD, 2, 0, 10, 1, 1, 10, 1), GOOD_ITEMS).errors).toEqual([]); // the same item twice is fine
  });
});

// ---- rejections ----

describe("rejections when decoding", () => {
  it("rejects every version but 1: 0, 2, 3, 0x7F, 0x80, 0x81 and 0xFF", () => {
    for (const version of [0, 2, 3, 9, 0x7f, 0x80, 0x81, 0xfe, 0xff]) {
      reject(fragOf(version, ...HEAD, 0), KIT_ERRORS.version);
      reject(fragOf(version, ...HEAD, 1, 0, 112, 4), KIT_ERRORS.version);
    }
    expect(decodeKit(fragOf(1, ...HEAD, 0), GOOD_ITEMS).errors).toEqual([]);
  });

  it("reads the version as a plain byte, not as a varint", () => {
    reject(toFragment([0x81, 0x00, ...bytesOf(1, ...HEAD, 0).slice(1)]), KIT_ERRORS.version);
  });

  it("rejects a non-canonical (overlong) varint in every numeric position", () => {
    const fields = [472, 9, 50, 1, 0, 112, 4]; // trio, race, level, count, slot index, page id, tier
    for (let position = 0; position < fields.length; position += 1) {
      const swapped = fields.map((value, i) => (i === position ? overlong(value) : value));
      reject(fragOf(1, ...swapped), KIT_ERRORS.overlong);
      // the canonical spelling of the same kit reads fine
      expect(decodeKit(fragOf(1, ...fields), GOOD_ITEMS).errors).toEqual([]);
    }
  });

  it("rejects 85 00 for 5, 81 00 for 1, and 80 80 80 80 00 for 0", () => {
    reject(fragOf(1, 472, 9, [0x85, 0x00], 0), KIT_ERRORS.overlong);
    reject(fragOf(1, 472, 9, [0x81, 0x00], 0), KIT_ERRORS.overlong);
    reject(fragOf(1, 472, 9, 50, [0x80, 0x80, 0x80, 0x80, 0x00]), KIT_ERRORS.overlong);
    reject(fragOf(1, 472, 9, 50, [0x80, 0x00]), KIT_ERRORS.overlong);
    expect(decodeKit(fragOf(1, 472, 9, 5, 0), GOOD_ITEMS).errors).toEqual([]); // the canonical 05
  });

  it("rejects a long run of continuation bytes quickly, and never reads past five", () => {
    reject(fragOf(1, ...HEAD, new Array(100).fill(0x80), 0x01), KIT_ERRORS.varintTooLong);
    reject(toFragment([1, ...new Array(1500).fill(0x80)]), KIT_ERRORS.varintTooLong);
    reject(toFragment([1, ...new Array(1500).fill(0xff)]), KIT_ERRORS.varintTooLong);
    const watch = stopwatch();
    for (let i = 0; i < 500; i += 1) decodeKit(toFragment([1, ...new Array(1500).fill(0xff)]), GOOD_ITEMS);
    expectWithin(watch.stop(), 500, "500 links with a long run of continuation bytes are rejected");
  });

  it("rejects bytes after the last slot", () => {
    const base = bytesOf(1, ...HEAD, 1, 0, 112, 4);
    for (const extra of [[0x00], [0x01], [0x80], [0x00, 0x00], [0xff, 0xff, 0xff, 0xff, 0x07], new Array(100).fill(0x41)]) {
      reject(toFragment([...base, ...extra]), KIT_ERRORS.trailing);
    }
    reject(toFragment([...bytesOf(1, ...HEAD, 0), 0x00]), KIT_ERRORS.trailing);
    expect(decodeKit(toFragment(base), GOOD_ITEMS).errors).toEqual([]);
  });

  it("rejects a link one byte short, and every shorter prefix", () => {
    const bytes = bytesOf(1, ...HEAD, 3, 0, 112, 4, 2, 72507, 0, 21, 2147483647, 10);
    expect(decodeKit(toFragment(bytes), GOOD_ITEMS).errors).toEqual([]);
    for (let length = 1; length < bytes.length; length += 1) {
      reject(toFragment(bytes.slice(0, length)), KIT_ERRORS.truncated);
    }
  });

  it("rejects an empty link and anything that is not text, without throwing", () => {
    reject("", KIT_ERRORS.empty);
    for (const value of [undefined, null, 0, 5, true, {}, [], ["AQAAAQA"], new String("AQAAAQA"), Symbol("k"), 10n, () => "AQAAAQA"]) {
      reject(value, KIT_ERRORS.notText);
    }
  });

  it("rejects every character outside the base64url alphabet, wherever it sits", () => {
    const bad = ["+", "/", "=", " ", "%", ".", "!", "\n", "\r", "\t", "\0", "é", "ｂ", "‮", "​", "#", "&", "?", "~", "*", "\\", '"', "\ud83d"];
    for (const ch of bad) {
      for (const position of [0, 5, GOOD.length - 1]) {
        const fragment = GOOD.slice(0, position) + ch + GOOD.slice(position + 1);
        reject(fragment, KIT_ERRORS.alphabet);
      }
      reject(GOOD + ch, KIT_ERRORS.alphabet);
    }
  });

  it("rejects standard base64 and its padding, and a #k= prefix", () => {
    const rng = makeRng(5);
    let sawPlus = false;
    let sawSlash = false;
    for (let i = 0; i < 200 && !(sawPlus && sawSlash); i += 1) {
      const kit = randomKit(rng);
      const standard = Buffer.from(expectedBytes(kit)).toString("base64"); // padded, with + and /
      if (standard.includes("+")) sawPlus = true;
      if (standard.includes("/")) sawSlash = true;
      if (/[+/=]/.test(standard)) {
        reject(standard, KIT_ERRORS.alphabet);
        expect(decodeKit(encodeKit(kit), new EveryItem()).errors).toEqual([]);
      }
    }
    expect(sawPlus && sawSlash).toBe(true);
    reject(`${GOOD}==`, KIT_ERRORS.alphabet);
    reject(`${GOOD}=`, KIT_ERRORS.alphabet);
    reject(`#k=${GOOD}`, KIT_ERRORS.alphabet);
    reject(`k=${GOOD}`, KIT_ERRORS.alphabet);
  });

  it("does not percent-decode: %2B, %41 and %3D stay percent signs", () => {
    reject(`${GOOD.slice(0, 4)}%2B${GOOD.slice(4)}`, KIT_ERRORS.alphabet);
    reject(`%41${GOOD.slice(1)}`, KIT_ERRORS.alphabet);
    reject(`${GOOD}%3D`, KIT_ERRORS.alphabet);
    reject(encodeURIComponent("é"), KIT_ERRORS.alphabet);
  });

  it("rejects the lengths no byte string can have", () => {
    for (const fragment of ["A", "AAAAA", "AdgDCTIAA", GOOD.slice(0, 25)]) {
      expect(fragment.length % 4).toBe(1);
      reject(fragment, KIT_ERRORS.length);
    }
  });

  it("rejects base64url whose unused bits are not zero, so two links never mean the same kit", () => {
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    // One link whose length leaves 2 characters in the last group of four, and one that leaves 3.
    const rng = makeRng(31);
    const byRest = new Map([[3, "AQAAAQA"]]); // seven characters: the smallest kit
    while (!byRest.has(2)) {
      const fragment = encodeKit(randomKit(rng));
      if (fragment.length % 4 === 2) byRest.set(2, fragment);
    }
    for (const [rest, fragment] of byRest) {
      expect(fragment.length % 4).toBe(rest);
      const mask = rest === 2 ? 0b1111 : 0b11; // the unused low bits of the last character
      const head = fragment.slice(0, -1);
      const canonicalTail = alphabet.indexOf(fragment.at(-1));
      expect(canonicalTail & mask).toBe(0);
      expect(decodeKit(fragment, new EveryItem()).errors).toEqual([]);
      for (let value = 0; value < 64; value += 1) {
        if ((value & mask) !== 0) reject(head + alphabet[value], KIT_ERRORS.tail, new EveryItem());
      }
    }
  });

  it("returns no partial kit and no unknown list when it rejects", () => {
    const result = decodeKit(toFragment([...bytesOf(1, ...HEAD, 2, 0, 999999, 4, 1, 112, 99)]), new Map());
    expect(result).toEqual({ kit: null, unknown: [], errors: [KIT_ERRORS.tier] });
  });
});

// ---- encoding refuses what it should not write ----

describe("encodeKit refuses an unwritable kit and writes no link", () => {
  const good = { v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [[0, 112, 4]] };
  const withSlot = (slot) => ({ ...good, slots: [slot] });

  it("needs an object of version 1", () => {
    for (const bad of [undefined, null, 5, "kit", [], () => 1]) {
      expect(() => encodeKit(bad)).toThrow(KitError);
    }
    for (const v of [0, 2, "1", undefined, null, 1.5, NaN]) {
      expectKitError(() => encodeKit({ ...good, v }), KIT_ERRORS.version);
    }
  });

  it("needs a trio and a race from the table, spelled exactly", () => {
    for (const trio of ["PAL-MNK-BER", "mnk-pal-ber", "pal-pal-ber", "pal-mnk", "pal-mnk-ber ", "pal-mnk-ber-war", "", null, undefined, 472, ["pal", "mnk", "ber"]]) {
      expectKitError(() => encodeKit({ ...good, trio }), KIT_ERRORS.trio);
    }
    for (const race of ["ogr", "Ogre", "XXX", "", null, undefined, 9, ["OGR"]]) {
      expectKitError(() => encodeKit({ ...good, race }), KIT_ERRORS.race);
    }
  });

  it("needs a level from 1 to 65", () => {
    for (const level of [0, -1, 66, 1024, 50.5, "50", NaN, Infinity, null, undefined]) {
      expectKitError(() => encodeKit({ ...good, level }), KIT_ERRORS.level);
    }
    expect(() => encodeKit({ ...good, level: 1 })).not.toThrow();
    expect(() => encodeKit({ ...good, level: 65 })).not.toThrow();
  });

  it("needs a slot index from 0 to 21, a page id from 1 to 2^31-1 and a tier from 0 to 10, all whole numbers", () => {
    for (const slotIndex of [22, -1, 1.5, "3", NaN, Infinity, null, undefined, 2 ** 31]) {
      expectKitError(() => encodeKit(withSlot([slotIndex, 112, 4])), KIT_ERRORS.slotIndex);
    }
    for (const pageId of [0, -1, 2 ** 31, 2 ** 53, 1.5, "112", "w112", NaN, Infinity, null, undefined]) {
      expectKitError(() => encodeKit(withSlot([0, pageId, 4])), KIT_ERRORS.pageId);
    }
    for (const tier of [11, -1, 1.5, "4", NaN, Infinity, null, undefined, 1_000_000]) {
      expectKitError(() => encodeKit(withSlot([0, 112, tier])), KIT_ERRORS.tier);
    }
    expect(() => encodeKit(withSlot([21, 1, 10]))).not.toThrow();
    expect(() => encodeKit(withSlot([0, 2147483647, 0]))).not.toThrow();
  });

  it("needs a list of well-formed slots", () => {
    for (const slots of [undefined, null, "abc", {}, 5, { length: 1, 0: [0, 1, 1] }]) {
      expectKitError(() => encodeKit({ ...good, slots }), KIT_ERRORS.slots);
    }
    for (const slot of [undefined, null, 5, "abc", [], [0, 112], [0, 112, 4, 9], [[0, 112, 4]]]) {
      expectKitError(() => encodeKit({ ...good, slots: [slot] }), KIT_ERRORS.slots);
    }
    expectKitError(() => encodeKit({ ...good, slots: new Array(1) }), KIT_ERRORS.slots); // a hole
  });

  it("refuses duplicate slot indices and more than 22 slots", () => {
    expectKitError(() => encodeKit({ ...good, slots: [[3, 1, 1], [3, 2, 2]] }), KIT_ERRORS.duplicateSlot);
    expectKitError(() => encodeKit({ ...good, slots: [[0, 1, 1], [1, 2, 2], [0, 3, 3]] }), KIT_ERRORS.duplicateSlot);
    expectKitError(() => encodeKit({ ...good, slots: new Array(23).fill([0, 1, 1]) }), KIT_ERRORS.slotCount);
    expectKitError(() => encodeKit({ ...good, slots: new Array(1_000_000).fill([0, 1, 1]) }), KIT_ERRORS.slotCount);
  });
});

// ---- placeholders ----

describe("unknown page ids", () => {
  const items = itemsOf([112, 72507]);

  it("become visible placeholders; the rest of the kit is unchanged", () => {
    const fragment = encodeKit({
      v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [[0, 112, 4], [5, 999999, 7], [9, 72507, 0]],
    });
    const result = decodeKit(fragment, items);
    expect(result.errors).toEqual([]);
    expect(result.unknown).toEqual([5]);
    expect(result.kit.slots).toHaveLength(3);
    expect(result.kit.slots[1]).toMatchObject({ slotIndex: 5, pageId: 999999, unknown: true });
    expect(result.kit.slots[1].item).toBeUndefined();
    expect(result.kit.slots[0]).toEqual({ slotIndex: 0, pageId: 112, tier: 4, key: "w112", item: items.get("w112") });
    expect(result.kit.slots[2]).toEqual({ slotIndex: 9, pageId: 72507, tier: 0, key: "w72507", item: items.get("w72507") });
  });

  it("keep their tier, so a re-shared link loses nothing", () => {
    const fragment = encodeKit({ v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [[5, 999999, 7], [2, 424242, 3]] });
    const result = decodeKit(fragment, items);
    expect(result.kit.slots[0]).toEqual({ slotIndex: 2, pageId: 424242, tier: 3, unknown: true });
    expect(result.kit.slots[1]).toEqual({ slotIndex: 5, pageId: 999999, tier: 7, unknown: true });
    expect(encodeKit(result.kit)).toBe(fragment);
  });

  it("are listed in ascending slot order", () => {
    const fragment = encodeKit({
      v: 1, trio: "pal-mnk-ber", race: "OGR", level: 50, slots: [[20, 7, 1], [4, 8, 1], [11, 112, 1], [0, 9, 1], [17, 10, 1]],
    });
    expect(decodeKit(fragment, items).unknown).toEqual([0, 4, 17, 20]);
  });

  it("all of them: an empty table makes every slot a placeholder, with no error", () => {
    const result = decodeKit(GOOD, new Map());
    expect(result.errors).toEqual([]);
    expect(result.unknown).toEqual([0, 2, 21]);
    expect(result.kit.slots.every((slot) => slot.unknown === true)).toBe(true);
  });

  it("returns the table's own item objects and leaves the table alone", () => {
    const table = itemsOf([112, 72507, 2147483647]);
    const sizeBefore = table.size;
    const result = decodeKit(GOOD, table);
    expect(result.kit.slots[0].item).toBe(table.get("w112"));
    expect(result.kit.slots[2].item).toBe(table.get("w2147483647"));
    expect(table.size).toBe(sizeBefore);
  });

  it("treats a key that maps to undefined or null as unknown", () => {
    const table = new Map([["w112", undefined], ["w72507", null], ["w2147483647", { name: "x" }]]);
    expect(decodeKit(GOOD, table).unknown).toEqual([0, 2]);
  });

  it("looks up only keys of the form w<digits>, so no other key of the table can be reached", () => {
    const seen = [];
    const spy = { get: (key) => { seen.push(key); return undefined; } };
    decodeKit(GOOD, spy);
    expect(seen).toEqual(["w112", "w72507", "w2147483647"]);
  });

  it("reports a table that throws as a failed decode, without repeating what it threw", () => {
    const broken = { get: () => { throw new TypeError("secret detail"); } };
    const result = decodeKit(GOOD, broken);
    expect(result).toEqual({ kit: null, unknown: [], errors: [KIT_ERRORS.internal] });
    expect(JSON.stringify(result)).not.toContain("secret");
  });

  it("takes any object with a get method as the table, and reports a missing table as an error rather than throwing", () => {
    expect(decodeKit(GOOD, { get: () => ({ name: "x" }) }).errors).toEqual([]);
    for (const table of [undefined, null, {}, [], "table", 5, Object.create(null), { get: "no" }]) {
      reject(GOOD, KIT_ERRORS.items, table);
    }
    // a malformed link is still reported as itself
    reject("!!", KIT_ERRORS.alphabet, undefined);
  });
});

// ---- the trio and race tables can be passed in ----

describe("tables", () => {
  const tables = { trios: ["aaa-bbb-ccc", "ddd-eee-fff"], races: ["XX", "YY", "ZZ"] };
  const kit = { v: 1, trio: "ddd-eee-fff", race: "ZZ", level: 20, slots: [[1, 5, 2]] };

  it("encode and decode with the tables they are given", () => {
    const fragment = encodeKit(kit, tables);
    expect([...Buffer.from(fragment, "base64url")]).toEqual(bytesOf(1, 1, 2, 20, 1, 1, 5, 2));
    expect(decodeKit(fragment, new EveryItem(), tables).kit).toMatchObject({ trio: "ddd-eee-fff", race: "ZZ" });
  });

  it("refuse a code that is not in them", () => {
    expectKitError(() => encodeKit({ ...kit, trio: "pal-mnk-ber" }, tables), KIT_ERRORS.trio);
    expectKitError(() => encodeKit({ ...kit, race: "OGR" }, tables), KIT_ERRORS.race);
    expect(decodeKit(fragOf(1, 2, 0, 20, 0), new EveryItem(), tables).errors).toEqual([KIT_ERRORS.trio]);
    expect(decodeKit(fragOf(1, 0, 3, 20, 0), new EveryItem(), tables).errors).toEqual([KIT_ERRORS.race]);
  });

  it("must be {trios, races} lists", () => {
    for (const bad of [null, 5, "tables", {}, { trios: [] }, { races: [] }, { trios: "a", races: "b" }, []]) {
      expectKitError(() => encodeKit(kit, bad), KIT_ERRORS.tables);
      expect(decodeKit(GOOD, new EveryItem(), bad).errors).toEqual([KIT_ERRORS.tables]);
    }
  });
});

// ---- the source ----

describe("the module source", () => {
  const source = readFileSync(MODULE_URL, "utf8");
  // Comments out, so a sentence in a comment cannot trip a check. (The module holds no "//" inside a string.)
  const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  const header = source.slice(0, source.indexOf("*/") + 2);

  it("tells the page, in the header, what clearing the fragment does not hide", () => {
    // The navigation timing entry keeps the address the page was loaded with, fragment included.
    expect(header).toContain('performance.getEntriesByType("navigation")[0].name');
    expect(header).toContain('never sends "#k="');
  });

  it("tells the page, in the header, that an in-page anchor loses the kit and what to do instead", () => {
    // A fragment link makes a new history entry with no state, and a reload of it has no kit to restore.
    expect(header).toContain("new history entry");
    expect(header).toContain("scrollIntoView");
  });

  it("imports nothing and uses no Node-only or legacy decoders", () => {
    expect(code).not.toMatch(/\bimport\b|\brequire\b|\bprocess\b|\bBuffer\b|\batob\b|\bbtoa\b/);
  });

  it("never percent-decodes, evaluates or writes HTML", () => {
    expect(code).not.toMatch(/decodeURI|decodeURIComponent|unescape|\beval\b|new\s+Function|innerHTML|outerHTML|insertAdjacentHTML|document\.write/);
    expect(code).not.toMatch(/set(Timeout|Interval)\s*\(\s*["'`]/);
  });

  it("uses no regular expression at all, so no input can make one run long", () => {
    expect(code).not.toMatch(/RegExp|\.exec\(|\.match\(|\.matchAll\(|\.search\(|\.replace\(|\.replaceAll\(|\.test\(|\.split\(\s*\//);
  });

  it("starts no request and no navigation", () => {
    expect(code).not.toMatch(/\bfetch\b|XMLHttpRequest|sendBeacon|location\.(assign|replace|reload|href\s*=)|window\.open|WebSocket|Worker/);
  });

  it("exports ES module names only (no default export, no side effects at import)", () => {
    expect(code).not.toMatch(/export\s+default/);
    expect(source).toMatch(/^export /m);
  });
});
