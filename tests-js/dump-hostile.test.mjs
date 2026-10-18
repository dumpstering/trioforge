// Hostile and unusual input for the dump parser: 28 variants (24 hostile files and 4 harmless re-encodings),
// built with invented names from the synthetic dump.
// Every non-ASCII character is built at run time from its code point, never typed into this file.
import { describe, expect, it } from "vitest";
import { ERRORS, parseDump, parseDumpBytes } from "../pipeline/trioforge/site/static/input/dump.js";
import {
  HEADER,
  KEYRING_HEADER,
  bytes,
  crlf,
  empty,
  file,
  fixture,
  insertAt,
  keyRow,
  problemsIn,
  row,
  utf16,
  utf8,
  withLine,
} from "./dump-helpers.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

const FULL = fixture("synthetic-full");
const SMALL = fixture("synthetic-small");
const base = parseDumpBytes(bytes(FULL));
const H = HEADER + "\r\n";
const NECK = FULL.split("\r\n").findIndex((l) => l.startsWith("Neck\t")) + 1; // line 13
const swapNeck = (line) => withLine(FULL, NECK, line);
const CYRILLIC_A = String.fromCharCode(0x430);
const BIDI_OVERRIDE = String.fromCharCode(0x202e);
const ZERO_WIDTH_SPACE = String.fromCharCode(0x200b);

const same = (r) => {
  expect(base.rows).toHaveLength(54); // the reference itself is not empty, so "the same" means something
  expect(r.errors).toEqual([]);
  expect(r.warnings).toEqual([]);
  expect(r.rows).toEqual(base.rows);
  expect(r.worn).toEqual(base.worn);
  expect(r.owned).toEqual(base.owned);
};
/** Rejected: exactly one error, and no data at all. */
const rejected = (message) => (r) => {
  expect(r.errors).toHaveLength(1);
  if (typeof message === "string") expect(r.errors[0]).toBe(message);
  else expect(r.errors[0]).toMatch(message);
  expect([r.rows, r.worn.size, r.owned.size, r.warnings]).toEqual([[], 0, 0, []]);
};
/** Quarantined: no error, one warning for the line, and every other row is still read. */
const skipped = (line) => (r) => {
  expect(r.errors).toEqual([]);
  expect(r.warnings.filter((w) => w.startsWith(`Line ${line} was skipped`))).toHaveLength(1);
  expect(r.rows).toHaveLength(base.rows.length - 1);
  expect(r.worn.has("NECK")).toBe(false);
  expect(r.worn.get("HEAD")).toEqual(base.worn.get("HEAD"));
};

describe("28 variants: hostile files and harmless re-encodings", () => {
  const variants = [
    // ---- harmless re-encodings: read correctly
    ["LF-only line endings", bytes(FULL.split("\r\n").join("\n")), same],
    ["CR-only line endings", bytes(FULL.split("\r\n").join("\r")), same],
    ["UTF-8 BOM prefixed", new Uint8Array([0xef, 0xbb, 0xbf, ...bytes(FULL)]), same],
    ["UTF-16LE with BOM (Notepad 'Unicode')", utf16(FULL), same],
    // ---- rejected: the envelope
    ["UTF-16LE without BOM", utf16(FULL, { bom: false }), rejected(ERRORS.encoding)],
    ["zip magic", new Uint8Array([0x50, 0x4b, 0x03, 0x04, ...bytes(FULL).subarray(0, 100)]), rejected(ERRORS.binary)],
    ["2 MiB file", bytes(H + "General 1\tEmpty\t0\t0\t0\r\n".repeat(90000)), rejected(ERRORS.tooLarge)],
    ["30,000 short lines (under the byte cap)", bytes(H + "Bank1\tEmpty\t0\t0\t0\r\n".repeat(30000)), rejected(ERRORS.tooManyLines)],
    ["one 300 KB line", bytes(H + "Head\t" + " ".repeat(300000) + "x\t1\t1\t10\r\n"), rejected(/^Line 2 is longer than 256 characters/)],
    // ---- quarantined: one row is skipped with a warning
    ["markup in a name", bytes(swapNeck(row("Neck", "<img src=x onerror=alert(1)>", 410006))), skipped(NECK)],
    ["__proto__ as Location", bytes(swapNeck(row("__proto__", "Pitted Skiver", 410006))), skipped(NECK)],
    ["__proto__ as Name", bytes(swapNeck(row("Neck", "__proto__", 410006))), skipped(NECK)],
    ["homoglyph in a name (Cyrillic a)", utf8(swapNeck(row("Neck", `Bl${CYRILLIC_A}deward`, 410006))), skipped(NECK)],
    ["bidi override in a name", utf8(swapNeck(row("Neck", `Fern${BIDI_OVERRIDE}wick`, 410006))), skipped(NECK)],
    // ---- an ordinary name that only looks odd
    [
      "constructor as Name",
      bytes(swapNeck(row("Neck", "constructor", 410006))),
      (r) => {
        expect(r.errors).toEqual([]);
        expect(r.worn.get("NECK")).toMatchObject({ name: "constructor", id: 410006 });
        expect(r.warnings).toEqual([]);
      },
    ],
    // ---- rejected: a field is not a number in range
    ["ID overflow 99999999999999999999", bytes(swapNeck(row("Neck", "Pitted Skiver", "99999999999999999999"))), rejected(/^Line 13 has a number that is not 1 to 10 digits/)],
    ["ID hex 0x1A", bytes(swapNeck(row("Neck", "Pitted Skiver", "0x1A"))), rejected(/^Line 13 has a number that is not 1 to 10 digits/)],
    ["Count 1e9", bytes(swapNeck(row("Neck", "Pitted Skiver", 410006, "1e9"))), rejected(/^Line 13 has a number that is not 1 to 10 digits/)],
    ["negative Count", bytes(swapNeck(row("Neck", "Pitted Skiver", 410006, "-5"))), rejected(/^Line 13 has a number that is not 1 to 10 digits/)],
    // ---- flagged: read, with a warning
    [
      "tier +99",
      bytes(swapNeck(row("Neck", "Dome-Capped Sallet +99", 410006))),
      (r) => {
        expect(r.errors).toEqual([]);
        expect(r.worn.get("NECK")).toMatchObject({ name: "Dome-Capped Sallet", tier: 10 });
        expect(r.warnings).toEqual(["Line 13: tier +99 is above +10, so it is read as +10."]);
      },
    ],
    // ---- rejected or quarantined: structure
    ["orphan socket row", bytes(H + empty("Head-Slot7") + "\r\n"), rejected(/^Line 2 sits in a container or item row that is missing/)],
    [
      "three Ear rows",
      bytes(H + [row("Ear", "Tin Earbob", 10351), row("Ear", "Tin Earbob", 10351), row("Ear", "Tin Earbob", 10351)].join("\r\n") + "\r\n"),
      (r) => {
        expect(r.errors).toEqual([]);
        expect(r.warnings.filter((w) => w.startsWith("Line 4 was skipped"))).toHaveLength(1);
        expect([...r.worn.keys()]).toEqual(["EAR1", "EAR2"]);
        expect(r.owned.get(10351)).toHaveLength(2);
      },
    ],
    [
      "socket 10 on a +1 item",
      bytes(H + [row("Head", "Dome-Capped Sallet +1", 4301), empty("Head-Slot7"), empty("Head-Slot10")].join("\r\n") + "\r\n"),
      (r) => {
        expect(r.errors).toEqual([]);
        expect(r.warnings.filter((w) => w.startsWith("Line 2: the sockets"))).toEqual(["Line 2: the sockets listed do not match the item's tier."]);
        expect(r.worn.get("HEAD").tier).toBe(1);
      },
    ],
    [
      "depth 5 location",
      bytes(swapNeck(row("General 1" + "-Slot1".repeat(5), "Plain Cap", 410006))),
      (r) => {
        skipped(NECK)(r);
        expect(r.warnings[0]).toBe("Line 13 was skipped: it is nested more than 3 levels deep.");
      },
    ],
    ["6 fields", bytes(swapNeck(row("Neck", "Pitted Skiver", 410006) + "\tEXTRA")), rejected(/^Line 13 does not have the expected columns/)],
    ["Empty with nonzero ID", bytes(swapNeck(row("Neck", "Empty", 4301))), rejected(/^Line 13: an Empty row must have ID, Count and Slots 0/)],
    [
      "second KeyRing header mid-file",
      bytes(H + row("Head", "Plain Cap", 1) + "\r\n\r\n" + KEYRING_HEADER + "\r\n" + KEYRING_HEADER + "\r\n"),
      rejected(/^Line 5 does not have the expected columns/),
    ],
    // ---- names that end in digits are not tiers
    [
      "catalog-legal names ending in digits",
      bytes(H + [row("General 1", "Zephyr Blade 4", 1), row("General 2", "Quarry Mattock 628 +3", 2), row("General 3", "Nettle Primer Pg. 450", 3)].join("\r\n") + "\r\n"),
      (r) => {
        expect(r.errors).toEqual([]);
        expect(r.rows.map((x) => [x.name, x.tier])).toEqual([["Zephyr Blade 4", 0], ["Quarry Mattock 628", 3], ["Nettle Primer Pg. 450", 0]]);
      },
    ],
  ];

  it("has all 28", () => expect(variants).toHaveLength(28));

  it.each(variants)("%s", (_label, data, check) => {
    const r = parseDumpBytes(data);
    check(r);
    expect(problemsIn(r)).toEqual([]);
  });

  it("the oversized variants are also refused unread when they arrive as files", async () => {
    for (const [label, data] of variants.filter((v) => /2 MiB/.test(v[0]))) {
      const r = await parseDump(file(data));
      expect(r.errors, label).toEqual([ERRORS.tooLarge]);
    }
  });
});

describe("more files that should not be believed", () => {
  it("a dump followed by a second dump, a stray header row, or text", () => {
    expect(parseDumpBytes(bytes(FULL + FULL)).errors).toHaveLength(1);
    expect(parseDumpBytes(bytes(FULL + "trailing text\r\n")).errors[0]).toMatch(/^Line 150 does not have the expected columns/);
    // the header repeated as a data row is not a second header: its ID, Count and Slots are not numbers
    const r = parseDumpBytes(bytes(insertAt(SMALL, 3, HEADER)));
    expect(r.errors).toHaveLength(1);
    expect(r.errors[0]).toMatch(/^Line 3 has a number that is not 1 to 10 digits/);
  });

  it("a container named __proto__ and its children are unknown locations, nothing more", () => {
    const rows = [row("__proto__", "Plain Sack", 1, 1, 4), row("__proto__-Slot1", "Plain Cap", 2), row("__proto__-Slot2", "Plain Cap", 3), empty("__proto__-Slot3")];
    const r = parseDumpBytes(bytes(insertAt(SMALL, 50, ...rows)));
    expect(r.errors).toEqual([]);
    expect(r.warnings.map((w) => w.match(/^Line (\d+) was skipped/)?.[1])).toEqual(["50", "51", "52"]);
    expect(r.owned.has(2)).toBe(false);
    expect(({}).constructor).toBe(Object);
    expect(Object.getPrototypeOf({})).toBe(Object.prototype);
  });

  it("a byte order mark or a zero-width space inside the file skips only its row", () => {
    const mid = new Uint8Array([...bytes(SMALL.split("\r\n").slice(0, 9).join("\r\n") + "\r\n"), 0xef, 0xbb, 0xbf, ...bytes(SMALL.split("\r\n").slice(9).join("\r\n"))]);
    const r = parseDumpBytes(mid);
    expect(r.errors).toEqual([]);
    // its location is unreadable too, so the worn block is one row short and the pair order can no longer be trusted
    expect(r.warnings).toHaveLength(2);
    expect(r.warnings[0]).toMatch(/^Line 10 was skipped/);
    expect(r.warnings[1]).toContain("usual order");
    expect(r.worn.has("NECK")).toBe(false);
    expect(r.rows).toHaveLength(parseDumpBytes(bytes(SMALL)).rows.length - 1);
    const invisible = parseDumpBytes(utf8(withLine(SMALL, 10, row("Neck", `Ashen${ZERO_WIDTH_SPACE}Torque`, 410006))));
    expect(invisible.errors).toEqual([]);
    expect(invisible.worn.has("NECK")).toBe(false);
  });

  it("NUL bytes, a megabyte of them, or a line of only tabs, end in one plain error", () => {
    expect(parseDumpBytes(new Uint8Array(1 << 20)).errors).toHaveLength(1);
    expect(parseDumpBytes(new Uint8Array(1 << 19)).errors).toHaveLength(1);
    const tabs = parseDumpBytes(bytes(H + "\t".repeat(255) + "\r\n"));
    expect(tabs.errors[0]).toMatch(/^Line 2 does not have the expected columns/);
  });
});

describe("strings that are dangerous elsewhere are inert here", () => {
  const dangerous = [
    "constructor",
    "hasOwnProperty",
    "toString",
    "valueOf",
    "isPrototypeOf",
    "prototype",
    "proto",
    "__proto__",
    "__defineGetter__",
    "<img src=x onerror=window.__pwned=1>",
    '" onmouseover="alert(1)',
    "'><script>alert(1)</script>",
    "<svg/onload=alert(1)>",
    "javascript:alert(1)",
    "{{constructor.constructor('alert(1)')()}}",
    "${alert(1)}",
    "&lt;script&gt;",
    "%3Cscript%3E",
    "a\\b",
  ];

  it("a battery of names pollutes nothing and runs nothing", () => {
    const before = Object.getOwnPropertyNames(Object.prototype).sort().join();
    const rows = dangerous.map((name, i) => row("Bank" + (i + 1), name, 3000 + i));
    const r = parseDumpBytes(bytes(crlf([HEADER, ...rows, "", KEYRING_HEADER, ...dangerous.map((name, i) => keyRow("Equipment", name, 4000 + i))])));
    expect(r.errors).toEqual([]);
    expect(problemsIn(r)).toEqual([]);
    expect(Object.getOwnPropertyNames(Object.prototype).sort().join()).toBe(before);
    expect(({}).polluted).toBeUndefined();
    expect(({}).pwned).toBeUndefined();
    expect(globalThis.__pwned).toBeUndefined();
    expect(Object.getPrototypeOf({})).toBe(Object.prototype);
    expect(r.owned).toBeInstanceOf(Map);
    // what is read is the names whose characters are all ones an item name may have
    const kept = r.rows.filter((x) => x.section === "main").map((x) => x.name);
    expect(kept).toEqual(["constructor", "hasOwnProperty", "toString", "valueOf", "isPrototypeOf", "prototype", "proto", "javascript:alert(1)"]);
    // nothing that carries a markup character appears in any string of the output
    const out = JSON.stringify([r.warnings, r.errors, r.rows, [...r.owned], [...r.worn]]);
    for (const payload of dangerous.filter((p) => /[<>"=_%$&{}\\]/.test(p))) expect(out).not.toContain(payload);
  });

  it("a name or location that is a method name is looked up in a Map and found nowhere else", () => {
    const rows = [row("toString", "Plain Cap", 1), row("valueOf-Slot1", "Plain Cap", 2), row("hasOwnProperty", "Plain Cap", 3), row("Neck", "toString", 4)];
    const r = parseDumpBytes(bytes(insertAt(SMALL, 51, ...rows)));
    expect(r.errors).toEqual([]);
    expect(r.warnings.filter((w) => /^Line 5[1-3] was skipped/.test(w))).toHaveLength(3);
    expect(r.worn.get("NECK").name).toBe("Ashen Torque"); // the second Neck row (line 54) is the extra one
  });
});

describe("long lines and odd shapes cost time in proportion to their length, not more", { timeout: 60000 }, () => {
  const shapes = [
    ["spaces", (n) => " ".repeat(n) + "x"],
    ["position suffixes", (n) => "-Slot1".repeat(Math.ceil(n / 6)) + "x"],
    ["tier suffixes", (n) => " +1".repeat(Math.ceil(n / 3)) + "x"],
    ["open parentheses", (n) => "(a".repeat(Math.ceil(n / 2))],
    ["tabs", (n) => "\t".repeat(n)],
    ["one letter", (n) => "A".repeat(n)],
    ["stone markers", (n) => " (Exaltation)".repeat(Math.ceil(n / 13))],
    ["stars", (n) => "*".repeat(n)],
  ];
  const sizes = [40, 90, 200, 255, 300, 5000, 40000, 240000];

  it("none of the shapes at any size takes more than a few milliseconds, in any column", () => {
    const columns = [
      (s) => row("Neck", s, 410006),
      (s) => `${s}\tAshen Torque\t410006\t1\t10`,
      (s) => `Neck\tAshen Torque\t${s}\t1\t10`,
      (s) => `Neck\tAshen Torque\t410006\t${s}\t10`,
    ];
    for (const [label, make] of shapes) {
      const watch = stopwatch(); // (the load is measured around the parses of one shape, so that a blow-up is found at once and not after all of them)
      let slowest = { ms: 0, size: 0 };
      for (const n of sizes) {
        for (const column of columns) {
          const data = bytes(withLine(SMALL, 10, column(make(n))));
          const t = performance.now();
          const r = parseDumpBytes(data);
          const ms = performance.now() - t;
          if (ms > slowest.ms) slowest = { ms, size: n };
          expect(problemsIn(r), `${label} ${n}`).toEqual([]);
          if (r.errors.length) expect(r.errors[0], `${label} ${n}`).toMatch(/^Line \d+ (is longer than 256 characters|does not have|has a number)/);
        }
      }
      expectWithin(watch.stop(slowest.ms), 250, `the slowest parse of ${label} (at ${slowest.size})`);
    }
  });

  it("a 40,000-character line with no tab is refused by the length cap in well under 50 ms", () => {
    const data = bytes(H + "A".repeat(40000) + "\r\n");
    const watch = stopwatch();
    const r = parseDumpBytes(data);
    expectWithin(watch.stop(), 50, "a 40,000-character line with no tab is refused");
    expect(r.errors[0]).toMatch(/^Line 2 is longer than 256 characters/);
  });

  it("a megabyte of one line, and a megabyte of line ends, are plain errors in well under a second", () => {
    const watch = stopwatch();
    expect(parseDumpBytes(bytes("A".repeat((1 << 20) - 10))).errors).toHaveLength(1);
    expect(parseDumpBytes(bytes(H + "\n".repeat((1 << 20) - H.length - 10))).errors).toHaveLength(1);
    expect(parseDumpBytes(bytes(H + "\r".repeat((1 << 20) - H.length - 10))).errors).toHaveLength(1);
    expectWithin(watch.stop(), 2000, "a megabyte of one line and two megabytes of line ends are refused");
  });
});

describe("size and depth, as a stress", { timeout: 60000 }, () => {
  it("20,000 lines that nest deeper and deeper are skipped at the depth cap, without a stack overflow", () => {
    const lines = [HEADER, row("Bank1", "Sack", 1, 1, 80)];
    for (let i = 1; i <= 19998; i++) lines.push(row("Bank1" + "-Slot1".repeat(Math.min(i, 4)), "Cap", 100 + (i % 9000)));
    expect(lines).toHaveLength(20000);
    const data = bytes(crlf(lines));
    expect(data.length).toBeLessThan(1 << 20); // small enough to be read at all
    const watch = stopwatch();
    const r = parseDumpBytes(data);
    expectWithin(watch.stop(), 500, "20,000 lines that nest deeper and deeper are skipped");
    // lines 3, 4, 5 are depths 1, 2, 3 and are read; every line from 6 on has four position suffixes and is skipped
    expect(r.errors).toEqual([]);
    expect(r.rows.map((x) => x.line)).toEqual([2, 3, 4, 5]);
    expect(r.warnings).toHaveLength(101);
    expect(r.warnings[0]).toBe("Line 6 was skipped: it is nested more than 3 levels deep.");
    // 19,995 skipped lines, and three warnings after them (the bag at line 2 prints one position of 80, the worn order, no key ring section)
    expect(r.warnings[100]).toBe(`${19995 + 3 - 100} more warnings are not listed.`);
  });

  it("a legal dump of 17,305 lines (24 bags of 80 bags of 8) is read in well under 2 s", () => {
    const lines = [HEADER];
    let id = 1000;
    const bag = (root) => {
      lines.push(row(root, "Plain Sack", id++, 1, 80));
      for (let s = 1; s <= 80; s++) {
        lines.push(row(`${root}-Slot${s}`, "Plain Pouch", id++, 1, 8));
        for (let u = 1; u <= 8; u++) lines.push(row(`${root}-Slot${s}-Slot${u}`, `Pebble ${id}`, id++));
      }
    };
    for (let g = 1; g <= 12; g++) bag(`General ${g}`);
    for (let b = 1; b <= 12; b++) bag(`Bank${b}`);
    const data = bytes(crlf(lines));
    expect(lines).toHaveLength(17305);
    expect(data.length).toBeLessThan(1 << 20);
    const watch = stopwatch();
    const r = parseDumpBytes(data);
    expectWithin(watch.stop(), 1000, "a legal dump of 17,305 lines is read");
    expect(r.errors).toEqual([]);
    expect(r.rows).toHaveLength(17304);
    expect(r.rows.filter((x) => x.container)).toHaveLength(24 * 81);
    expect(r.owned.size).toBe(17304);
    expect(r.warnings.filter((w) => w.startsWith("Line"))).toEqual([]);
    expect(problemsIn(r)).toEqual([]);
  });

  it("a flood of rows to skip costs a hundred warnings and one summary, and little time", () => {
    const lines = [HEADER, ...Array.from({ length: 19999 }, (_, i) => row("Bank0", "Plain Cap", 1 + i))];
    const watch = stopwatch();
    const r = parseDumpBytes(bytes(crlf(lines)));
    expectWithin(watch.stop(), 500, "a flood of rows to skip is read");
    expect(r.errors).toEqual([ERRORS.noRows]);
    const withOneGood = parseDumpBytes(bytes(crlf([HEADER, empty("Head"), ...lines.slice(2)])));
    expect(withOneGood.errors).toEqual([]);
    // 19,998 skipped rows, plus the two warnings at the end of the file (worn order, no key ring section)
    expect(withOneGood.warnings).toHaveLength(101);
    expect(withOneGood.warnings[100]).toBe(`${19998 + 2 - 100} more warnings are not listed.`);
  });

  it("many copies of one position under one parent are skipped, not scanned again and again", () => {
    const lines = [HEADER, row("Bank1", "Plain Sack", 1, 1, 80), ...Array.from({ length: 19990 }, () => row("Bank1-Slot1", "Plain Cap", 2))];
    const watch = stopwatch();
    const r = parseDumpBytes(bytes(crlf(lines)));
    expectWithin(watch.stop(), 500, "many copies of one position under one parent are read");
    expect(r.errors).toEqual([]);
    expect(r.rows).toHaveLength(2);
  });
});

describe("hostile inputs through the File path", () => {
  it("never reject the promise, whatever the bytes are", async () => {
    let seed = 7;
    const next = () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed;
    };
    for (let i = 0; i < 300; i++) {
      const length = next() % 3000;
      const data = new Uint8Array(length);
      for (let k = 0; k < length; k++) data[k] = next() & 0xff;
      const r = await parseDump(file(data));
      expect(problemsIn(r)).toEqual([]);
    }
  });
});
