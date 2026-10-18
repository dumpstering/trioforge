import { describe, expect, it } from "vitest";
import {
  KIT_ERRORS,
  MAX_FRAGMENT_LENGTH,
  RACE_CODES,
  TRIO_CODES,
  encodeKit,
} from "../pipeline/trioforge/site/static/input/kitcode.js";
import { decodeKit } from "../pipeline/trioforge/site/static/input/kitdecode.js";
import { expectWithin, stopwatch } from "./timing.mjs";

// Seeded, so a failure repeats. Every check collects its problems and asserts once at the end:
// ten thousand expect() calls would dominate the time the test is meant to bound.

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
const WIDE = `${ALPHABET}+/=%. #&?!@:;,~*'"<>\\|\t\n\r é`;
const KNOWN_MESSAGES = new Set(Object.values(KIT_ERRORS));

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
const toFragment = (bytes) => Buffer.from(bytes).toString("base64url");
const randomChars = (rng, alphabet, length) => {
  let out = "";
  for (let i = 0; i < length; i += 1) out += alphabet[pick(rng, alphabet.length)];
  return out;
};
const randomBytes = (rng, length) => Array.from({ length }, () => pick(rng, 256));

const PAGE_ID_RANGES = [[1, 127], [128, 16383], [16384, 2097151], [2097152, 268435455], [268435456, 2147483647]];
function validKit(rng) {
  const used = new Set();
  const count = pick(rng, 23);
  while (used.size < count) used.add(pick(rng, 22));
  const slots = [...used].map((slotIndex) => {
    const [low, high] = PAGE_ID_RANGES[pick(rng, PAGE_ID_RANGES.length)];
    return [slotIndex, low + pick(rng, high - low + 1), pick(rng, 11)];
  });
  return {
    v: 1,
    trio: TRIO_CODES[pick(rng, TRIO_CODES.length)],
    race: RACE_CODES[pick(rng, RACE_CODES.length)],
    level: 1 + pick(rng, 65),
    slots,
  };
}
// Version 1 and a header whose four numbers are in range, so the decoder gets as far as the slots.
const validHeader = (rng) => [1, ...leb(pick(rng, 560)), ...leb(pick(rng, 15)), ...leb(1 + pick(rng, 65)), ...leb(pick(rng, 23))];

// An item table that knows the odd page ids only, so both kinds of slot occur.
class OddItems extends Map {
  get(key) {
    return Number(key.slice(1)) % 2 === 1 ? { key } : undefined;
  }
}
const ITEMS = new OddItems();

// What every result has to satisfy, whatever went in.
function problemsWith(result, fragment, label) {
  if (result === null || typeof result !== "object") return [`${label}: not an object`];
  const problems = [];
  const keys = Object.keys(result).sort().join(",");
  if (keys !== "errors,kit,unknown") problems.push(`${label}: keys are ${keys}`);
  if (!Array.isArray(result.errors) || !Array.isArray(result.unknown)) return [...problems, `${label}: errors or unknown is not a list`];
  if (result.kit === null) {
    if (result.errors.length !== 1) problems.push(`${label}: ${result.errors.length} errors`);
    else if (!KNOWN_MESSAGES.has(result.errors[0])) problems.push(`${label}: unlisted message ${result.errors[0]}`);
    else if (result.errors[0] === KIT_ERRORS.internal) problems.push(`${label}: internal failure on ${JSON.stringify(String(fragment).slice(0, 80))}`);
    if (result.unknown.length !== 0) problems.push(`${label}: a rejected link has an unknown list`);
    return problems;
  }
  if (result.errors.length !== 0) problems.push(`${label}: a kit with errors`);
  // An accepted link has to be the canonical spelling of its kit: nothing else may decode.
  let again;
  try {
    again = encodeKit(result.kit);
  } catch (error) {
    again = `throws ${error.message}`;
  }
  if (again !== fragment) problems.push(`${label}: accepted a link that is not canonical (${JSON.stringify(String(fragment).slice(0, 80))})`);
  const slots = result.kit.slots;
  if (!Array.isArray(slots) || slots.length > 22) problems.push(`${label}: bad slot list`);
  else {
    const unknown = [];
    slots.forEach((slot, i) => {
      if (i > 0 && slot.slotIndex <= slots[i - 1].slotIndex) problems.push(`${label}: slots out of order`);
      if (slot.unknown === true) unknown.push(slot.slotIndex);
    });
    if (unknown.join() !== result.unknown.join()) problems.push(`${label}: unknown list does not match the placeholders`);
  }
  return problems;
}

describe("fuzz: decodeKit", () => {
  it("10,000 random fragments, most with a version-1 header, never throw, hang or return a malformed result, in under 2 s", () => {
    const rng = makeRng(0xc0ffee);
    const inputs = [];
    for (let i = 0; i < 10000; i += 1) {
      switch (i % 5) {
        case 0: // any base64url text, 0 to 2,048 characters
          inputs.push(randomChars(rng, ALPHABET, pick(rng, MAX_FRAGMENT_LENGTH + 1)));
          break;
        case 1: // a good header, then noise
          inputs.push(toFragment([...validHeader(rng), ...randomBytes(rng, pick(rng, 150))]));
          break;
        case 2: { // a good header with one field spoiled: overlong, huge, or cut off
          const header = validHeader(rng);
          const at = 1 + pick(rng, header.length - 1);
          const spoiled = [
            header.slice(0, at),
            [[0x80, 0x00], [0xff, 0xff, 0xff, 0xff, 0x0f], [0x80, 0x80, 0x80, 0x80, 0x80, 0x01], []][pick(rng, 4)],
            header.slice(at),
            randomBytes(rng, pick(rng, 40)),
          ].flat();
          inputs.push(toFragment(spoiled));
          break;
        }
        case 3: // text with characters from outside the alphabet
          inputs.push(randomChars(rng, WIDE, pick(rng, 300)));
          break;
        default: // a valid kit
          inputs.push(encodeKit(validKit(rng)));
      }
    }
    const failures = [];
    const results = new Array(inputs.length);
    const watch = stopwatch();
    for (let i = 0; i < inputs.length; i += 1) {
      try {
        results[i] = decodeKit(inputs[i], ITEMS);
      } catch (error) {
        failures.push(`#${i} threw ${error && error.message}`);
      }
    }
    const elapsed = watch.stop();
    inputs.forEach((fragment, i) => {
      if (results[i] !== undefined) failures.push(...problemsWith(results[i], fragment, `#${i}`));
    });
    expect(failures.slice(0, 10)).toEqual([]);
    expectWithin(elapsed, 2000, "decoding the mixed fragments");
    // The mix has to reach all the way in: some links are accepted, most are not.
    const accepted = results.filter((r) => r && r.kit !== null).length;
    expect(accepted).toBeGreaterThan(1500);
    expect(accepted).toBeLessThan(5000);
  });

  it("10,000 mutations of valid links are rejected or are themselves canonical", () => {
    const rng = makeRng(424242);
    const bases = Array.from({ length: 300 }, () => encodeKit(validKit(rng)));
    const edits = [
      (s) => { const i = pick(rng, s.length); return s.slice(0, i) + ALPHABET[pick(rng, 64)] + s.slice(i + 1); },
      (s) => { const i = pick(rng, s.length); return s.slice(0, i) + s.slice(i + 1); },
      (s) => { const i = pick(rng, s.length + 1); return s.slice(0, i) + ALPHABET[pick(rng, 64)] + s.slice(i); },
      (s) => { if (s.length < 2) return s; const i = pick(rng, s.length - 1); return s.slice(0, i) + s[i + 1] + s[i] + s.slice(i + 2); },
      (s) => s.slice(0, pick(rng, s.length)),
      (s) => s + randomChars(rng, ALPHABET, 1 + pick(rng, 6)),
      (s) => { const a = pick(rng, s.length); const b = a + pick(rng, s.length - a); return s.slice(0, b) + s.slice(a, b) + s.slice(b); },
      (s) => { const i = pick(rng, s.length); return s.slice(0, i) + WIDE[pick(rng, WIDE.length)] + s.slice(i + 1); },
      (s) => { const i = pick(rng, s.length); return s.slice(0, i) + "A" + s.slice(i + 1); },
    ];
    const failures = [];
    let accepted = 0;
    let rejected = 0;
    for (let i = 0; i < 10000; i += 1) {
      let fragment = bases[pick(rng, bases.length)];
      for (let n = 1 + pick(rng, 3); n > 0 && fragment.length > 0; n -= 1) fragment = edits[pick(rng, edits.length)](fragment);
      let result;
      try {
        result = decodeKit(fragment, ITEMS);
      } catch (error) {
        failures.push(`#${i} threw ${error && error.message}`);
        continue;
      }
      if (result.kit === null) rejected += 1;
      else accepted += 1;
      failures.push(...problemsWith(result, fragment, `#${i}`));
    }
    expect(failures.slice(0, 10)).toEqual([]);
    expect(accepted).toBeGreaterThan(500);
    expect(rejected).toBeGreaterThan(500);
  });

  it("every spelling of the same bytes but one is refused: random base64url with random trailing bits", () => {
    const rng = makeRng(77);
    const failures = [];
    for (let i = 0; i < 2000; i += 1) {
      const fragment = encodeKit(validKit(rng));
      if (fragment.length % 4 === 0) continue;
      const bits = fragment.length % 4 === 2 ? 4 : 2;
      const head = fragment.slice(0, -1);
      const tail = ALPHABET.indexOf(fragment.at(-1));
      const dirty = head + ALPHABET[tail | (1 + pick(rng, (1 << bits) - 1))];
      const result = decodeKit(dirty, ITEMS);
      if (result.kit !== null) failures.push(`#${i} accepted ${dirty}`);
    }
    expect(failures.slice(0, 10)).toEqual([]);
  });

  it("anything that is not text is refused, never thrown at", () => {
    const hostile = [
      undefined, null, 0, -1, 1.5, NaN, Infinity, true, false, 10n, Symbol("k"), () => "x", class {}, {}, [], [[]], ["AQAAAQA"],
      { toString: () => "AQAAAQA" }, { valueOf: () => "AQAAAQA" }, new String("AQAAAQA"), new Uint8Array([1, 0, 0, 1, 0]),
      Object.create(null), new Proxy({}, { get() { throw new Error("trap"); } }), new Map(), new Date(),
    ];
    for (const value of hostile) {
      expect(decodeKit(value, ITEMS)).toEqual({ kit: null, unknown: [], errors: [KIT_ERRORS.notText] });
    }
  });

  it("huge input is refused at once, and the worst legal-length input is cheap", () => {
    const rng = makeRng(5);
    const huge = randomChars(rng, WIDE, 3_000_000);
    const worst = Array.from({ length: 1000 }, () => randomChars(rng, ALPHABET, MAX_FRAGMENT_LENGTH));
    const watch = stopwatch();
    for (const length of [2049, 10_000, 1_000_000, 10_000_000]) {
      expect(decodeKit("A".repeat(length), ITEMS).errors).toEqual([KIT_ERRORS.tooLong]);
    }
    expect(decodeKit(huge, ITEMS).errors).toEqual([KIT_ERRORS.tooLong]);
    expectWithin(watch.stop(), 1000, "fragments of up to 10 million characters are refused");
    // 2,048 characters is the most the decoder will look at; 1,000 of them cost almost nothing.
    const worstWatch = stopwatch();
    for (const text of worst) decodeKit(text, ITEMS);
    expectWithin(worstWatch.stop(), 1000, "1,000 fragments of the longest legal length are decoded");
  });

  it("a kit that encodes is never longer than 214 characters, over 20,000 random kits", () => {
    const rng = makeRng(123);
    let longest = 0;
    for (let i = 0; i < 20000; i += 1) longest = Math.max(longest, encodeKit(validKit(rng)).length);
    expect(longest).toBeLessThanOrEqual(214);
    expect(longest).toBeLessThanOrEqual(MAX_FRAGMENT_LENGTH);
  });
});
