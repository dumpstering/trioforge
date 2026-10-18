// Tests for the /outputfile inventory dump parser. All names, IDs and file names are invented.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  ERRORS,
  LIMITS,
  SOLVER_SLOT_IDS,
  parseDump,
  parseDumpBytes,
} from "../pipeline/trioforge/site/static/input/dump.js";
import {
  CUT_OFF,
  HEADER,
  KEYRING_HEADER,
  MAX_BYTES,
  bytes,
  crlf,
  dump,
  empty,
  file,
  fixture,
  insertAt,
  keyRow,
  padTo,
  problemsIn,
  row,
  utf16,
  utf8,
  withLine,
} from "./dump-helpers.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

const FULL = fixture("synthetic-full");
const SMALL = fixture("synthetic-small");
const parse = (text) => parseDumpBytes(bytes(text));
const lineOf = (text, prefix) => text.split("\r\n").findIndex((l) => l.startsWith(prefix)) + 1;
const at = (r, line) => r.rows.find((x) => x.line === line);
const skippedLine = (r, n) => r.warnings.some((w) => w.startsWith(`Line ${n} was skipped`));
/** A file with only the given main rows (and no key ring section). */
const only = (...rows) => parse(dump(rows));
const warningsAbout = (r, fragment) => r.warnings.filter((w) => w.includes(fragment));

// ------------------------------------------------------------------------------------------------------------

describe("the synthetic full dump", () => {
  const r = parse(FULL);

  it("parses cleanly: no errors, no warnings, a well-formed result", () => {
    expect(r.errors).toEqual([]);
    expect(r.warnings).toEqual([]);
    expect(problemsIn(r)).toEqual([]);
  });

  it("keeps exactly the non-Empty rows, stones and sockets included", () => {
    // independent oracle: count the lines whose Name column is not Empty (header and key ring header excluded)
    const oracle = FULL.split("\r\n")
      .slice(1)
      .filter((l) => l !== "" && !l.startsWith("KeyRing\t"))
      .filter((l) => l.split("\t")[1] !== "Empty").length;
    expect(oracle).toBe(54);
    expect(r.rows).toHaveLength(54);
    expect(r.rows.every((x) => x.name !== "Empty")).toBe(true);
  });

  it("maps the 21 filled worn slots, pairs by occurrence, in file order", () => {
    expect([...r.worn.keys()]).toEqual([
      "ANY1", "EAR1", "HEAD", "FACE", "EAR2", "NECK", "SHOULDERS", "ARMS", "BACK", "WRIST2", "RANGE", "HANDS",
      "PRIMARY", "SECONDARY", "FINGER1", "FINGER2", "CHEST", "LEGS", "FEET", "WAIST", "AMMO",
    ]);
    const seen = Object.fromEntries([...r.worn].map(([slot, x]) => [slot, `${x.name}|${x.tier}`]));
    expect(seen).toEqual({
      ANY1: "Pebble Charm|0",
      EAR1: "Brindle Stud|2",
      HEAD: "Tarnished Quillcap|3",
      FACE: "Mothwing Visor|0",
      EAR2: "Pewter Hoop|1",
      NECK: "Ashen Torque|0",
      SHOULDERS: "Fernwood Mantlet|0",
      ARMS: "Lichen Vambraces|0",
      BACK: "Gullcloak|4",
      WRIST2: "Reedcord Band|0",
      RANGE: "Yarrow Tether|0",
      HANDS: "Thistle Mitts|0",
      PRIMARY: "Cobbled Maul|1",
      SECONDARY: "Dappled Buckler|0",
      FINGER1: "Copper Loop|0",
      FINGER2: "Rushwater Seal|2",
      CHEST: "Moth-Eaten Rag*|0",
      LEGS: "Burlap Leggings|0",
      FEET: "Mudlark Boots|0",
      WAIST: "Hempen Cord|0",
      AMMO: "Flint Dart|0",
    });
    // an Empty row still takes its place in a pair: the filled Wrist is the second one, the filled Any Slot the first
    expect(r.worn.has("WRIST1")).toBe(false);
    expect(r.worn.has("ANY2")).toBe(false);
    expect(r.worn.get("EAR1").line).toBe(3);
    expect(r.worn.get("EAR2").line).toBe(11);
  });

  it("keeps every copy of an item at its own tier, with Count and location", () => {
    const view = (id) => r.owned.get(id).map((e) => [e.tier, e.count, e.place, e.location, e.slot]);
    expect(view(440001)).toEqual([
      [0, 20, "bag", "General 1-Slot1", null],
      [0, 20, "bank", "Bank1-Slot1", null],
    ]);
    // the ID stays the same across tiers: the worn +3 Head item and a +0 copy in a bag are one key, two entries
    expect(view(410003)).toEqual([
      [3, 1, "worn", "Head", "HEAD"],
      [0, 1, "bag", "General 2-Slot4", null],
    ]);
    expect(view(410013)).toEqual([
      [1, 1, "worn", "Primary", "PRIMARY"],
      [0, 1, "bag", "General 4-Slot1", null],
    ]);
    expect(view(410021)).toEqual([[0, 40, "worn", "Ammo", "AMMO"]]);
    expect(r.owned.get(430070).map((e) => e.place)).toEqual(["sharedbank"]);
    expect(r.owned.get(430050)[0]).toMatchObject({ tier: 1, location: "SharedBank1-Slot1", place: "sharedbank" });
    expect(r.owned.get(430060)[0]).toMatchObject({ tier: 2, location: "Bank1-Slot2", place: "bank" });
  });

  it("counts 42 distinct IDs and 45 entries, and a socketed stone never appears in owned", () => {
    expect(r.owned.size).toBe(42);
    expect([...r.owned.values()].reduce((n, list) => n + list.length, 0)).toBe(45);
    expect(r.owned.has(410200)).toBe(false); // Ember Facet exists only as stones
    // Sparkle Shard is also a loose item: one entry, the 4 stones with its ID add nothing
    expect(r.owned.get(410100)).toHaveLength(1);
    expect(r.owned.get(410100)[0]).toMatchObject({ count: 1, location: "General 2-Slot2", name: "Sparkle Shard" });
  });

  it("puts the key ring rows in owned under their type, but never the loose stones", () => {
    expect(r.owned.get(450001)[0]).toMatchObject({ place: "keyring", location: "Activated", count: 1, tier: 0 });
    expect(r.owned.get(450002)[0]).toMatchObject({ place: "keyring", location: "Equipment" });
    expect(r.owned.get(450003)[0]).toMatchObject({ place: "keyring", location: "Equipment", tier: 2, name: "Spare Hoop" });
    const stoneRows = r.rows.filter((x) => x.section === "keyring" && x.stone);
    expect(stoneRows.map((x) => x.line)).toEqual([145, 146]);
  });

  it("builds the tree by document order: depth, parents, containers", () => {
    const pouch = at(r, 62);
    expect(pouch).toMatchObject({ name: "Reed Pouch", container: true, slots: 6, path: [2], place: "bag" });
    // a bag in a bag (depth 2) holds an item (depth 2) whose socket row would be depth 3
    expect(at(r, 66)).toMatchObject({ name: "Quillback Bracer", tier: 1, path: [2, 4], parent: r.rows.indexOf(pouch), container: false });
    expect(r.rows.filter((x) => x.container).map((x) => x.line)).toEqual([38, 47, 60, 62, 78, 92, 132]);
    expect(Math.max(...r.rows.map((x) => x.path.length))).toBe(2);
  });

  it("labels the socket of each stone by the position, and sockets are decided by the parent", () => {
    const sockets = r.rows.filter((x) => x.socket).map((x) => [x.line, x.socket.index, x.socket.kind]);
    expect(sockets).toEqual([
      [4, 7, "Focus"], [7, 7, "Focus"], [8, 8, "Click"], [17, 7, "Focus"], [18, 8, "Click"], [51, 7, "Focus"], [95, 7, "Focus"],
    ]);
    expect(r.rows.filter((x) => x.stone).map((x) => x.line)).toEqual([4, 7, 8, 17, 18, 51, 95, 145, 146]);
    // the children of the bag at General 2 are bag positions, not sockets, although they are numbered like sockets
    expect(at(r, 49).socket).toBe(null);
    expect(at(r, 50).socket).toBe(null);
  });

  it("is the same on every call and returns frozen rows and entries", () => {
    expect(parse(FULL)).toEqual(r);
    expect(r.rows.every((x) => Object.isFrozen(x))).toBe(true);
    expect([...r.owned.values()].flat().every((e) => Object.isFrozen(e))).toBe(true);
  });
});

describe("harmless re-encodings read the same dump", () => {
  const base = parse(FULL);
  const lines = FULL.split("\r\n").slice(0, -1);
  // (a CR-ended line followed by a blank CRLF line would read CR CR LF, which is one doubled line end: so the CR rows stop one line early)
  const endings = lines.map((l, i) => l + (i === 0 ? "\r\n" : i <= 90 ? "\n" : i <= 140 ? "\r" : "\r\n"));
  // a last line with no line end is read, and said to be possibly cut (the file has 149 lines)
  const LAST_LINE = "Line 149 has no line end, so the last line may be cut off; re-run /outputfile inventory.";
  const cases = [
    ["LF only", bytes(FULL.split("\r\n").join("\n")), []],
    ["CR only", bytes(FULL.split("\r\n").join("\r")), []],
    // CRLF header, LF worn rows, lone CR bank rows, CRLF key ring, no final line end
    ["CRLF, LF and lone CR in one file, no final line end", bytes(endings.join("").slice(0, -2)), [LAST_LINE]],
    ["a UTF-8 byte order mark", new Uint8Array([0xef, 0xbb, 0xbf, ...bytes(FULL)]), []],
    ["UTF-16LE with a byte order mark", utf16(FULL), []],
    ["UTF-16BE with a byte order mark", utf16(FULL, { big: true }), []],
    ["no line end after the last row", bytes(FULL.slice(0, -2)), [LAST_LINE]],
    ["blank lines after the last row", bytes(FULL + "\r\n\r\n"), []],
  ];
  it.each(cases)("%s", (_label, data, warnings) => {
    expect(base.rows).toHaveLength(54); // the reference itself is not empty, so "the same" means something
    const r = parseDumpBytes(data);
    expect(r.errors).toEqual([]);
    expect(r.warnings).toEqual(warnings);
    expect(r.rows).toEqual(base.rows);
    expect(r.worn).toEqual(base.worn);
    expect(r.owned).toEqual(base.owned);
  });
});

describe("parseDump reads a file", () => {
  it("returns what parsing the same bytes gives", async () => {
    const r = await parseDump(file(bytes(FULL), "Alpha.txt"));
    expect(r).toEqual(parse(FULL));
  });

  it("asks for slice(0, 1 MiB + 1) once and never calls text()", async () => {
    const blob = new Blob([bytes(SMALL)]);
    const calls = [];
    const stub = {
      size: blob.size,
      slice: (a, b) => {
        calls.push(["slice", a, b]);
        return blob.slice(a, b);
      },
      text: () => {
        calls.push(["text"]);
        throw new Error("text");
      },
      arrayBuffer: () => {
        calls.push(["arrayBuffer"]);
        throw new Error("arrayBuffer");
      },
    };
    const r = await parseDump(stub);
    expect(r.errors).toEqual([]);
    expect(calls).toEqual([["slice", 0, MAX_BYTES + 1]]);
  });

  it("parses a file of exactly 1 MiB", async () => {
    const text = padTo(SMALL, MAX_BYTES);
    expect(text.length).toBe(MAX_BYTES);
    const r = await parseDump(file(bytes(text)));
    expect(r.errors).toEqual([]);
    expect(r.rows.length).toBeGreaterThan(9000);
    expect(problemsIn(r)).toEqual([]);
  });

  it("rejects 1 MiB + 1 byte before reading any of it", async () => {
    const touched = [];
    const trap = (what) => () => {
      touched.push(what);
      throw new Error(what);
    };
    const stub = { size: MAX_BYTES + 1, slice: trap("slice"), text: trap("text"), arrayBuffer: trap("arrayBuffer"), stream: trap("stream") };
    const r = await parseDump(stub);
    expect(r.errors).toEqual([ERRORS.tooLarge]);
    expect(r.errors[0]).toContain("larger than 1 MiB");
    expect(touched).toEqual([]);
    expect(problemsIn(r)).toEqual([]);
  });

  it("rejects a real File of 1 MiB + 1 byte, however valid its content", async () => {
    const text = padTo(SMALL, MAX_BYTES) + "\n";
    expect(text.length).toBe(MAX_BYTES + 1);
    const r = await parseDump(file(bytes(text)));
    expect(r.errors).toEqual([ERRORS.tooLarge]);
    expect(r.rows).toEqual([]);
  });

  it("parseDumpBytes applies the 1 MiB limit itself, before it looks at a byte", () => {
    class Watched extends Uint8Array {
      subarray() {
        throw new Error("read a part of the bytes");
      }
      slice() {
        throw new Error("read a part of the bytes");
      }
    }
    const big = new Watched(MAX_BYTES + 1);
    big.set(bytes(HEADER + "\r\n"), 0); // a perfectly good start
    expect(parseDumpBytes(big).errors).toEqual([ERRORS.tooLarge]);
    // however the bytes come, and whatever they start with (a zip, a UTF-16 mark, a UTF-8 mark are not looked at either)
    for (const start of [[0x50, 0x4b, 0x03, 0x04], [0xff, 0xfe], [0xef, 0xbb, 0xbf], []]) {
      const data = new Uint8Array(MAX_BYTES + 1);
      data.set(start);
      expect(parseDumpBytes(data).errors, `${start}`).toEqual([ERRORS.tooLarge]);
      expect(parseDumpBytes(data.buffer).errors, `${start}`).toEqual([ERRORS.tooLarge]);
      expect(parseDumpBytes(new DataView(data.buffer)).errors, `${start}`).toEqual([ERRORS.tooLarge]);
    }
    expect(parseDumpBytes(Buffer.alloc(MAX_BYTES + 1)).errors).toEqual([ERRORS.tooLarge]);
    // and exactly 1 MiB is read
    expect(parseDumpBytes(bytes(padTo(SMALL, MAX_BYTES))).errors).toEqual([]);
  });

  it("rejects a read that returns more than 1 MiB although size said less", async () => {
    const stub = { size: 100, slice: () => ({ arrayBuffer: async () => new ArrayBuffer(2 * MAX_BYTES) }) };
    const r = await parseDump(stub);
    expect(r.errors).toEqual([ERRORS.tooLarge]);
  });

  it("answers an empty file, a failed read and things that are not files with one error, never an exception", async () => {
    expect((await parseDump(file(new Uint8Array(0)))).errors).toEqual([ERRORS.empty]);
    const failing = { size: 10, slice: () => ({ arrayBuffer: async () => { throw new Error("disk"); } }) };
    expect((await parseDump(failing)).errors).toEqual([ERRORS.readFailed]);
    const throwingSlice = { size: 10, slice: () => { throw new Error("slice"); } };
    expect((await parseDump(throwingSlice)).errors).toEqual([ERRORS.readFailed]);
    // a read that does not give an ArrayBuffer back is a failed read, whatever it gives back
    for (const odd of [5, null, undefined, "text", {}, { byteLength: 3 }, new Uint8Array(3)]) {
      const stub = { size: 10, slice: () => ({ arrayBuffer: async () => odd }) };
      expect((await parseDump(stub)).errors).toEqual([ERRORS.readFailed]);
    }
    for (const bad of [null, undefined, 42, "text", {}, [], { size: -1 }, { size: Number.NaN }, { size: 1.5 }, { size: 10 }, { size: Infinity, slice() {} }]) {
      const r = await parseDump(bad);
      expect(r.errors).toEqual([ERRORS.notAFile]);
      expect(problemsIn(r)).toEqual([]);
    }
  });

  it("never reads the file name, and the name is in no output string", async () => {
    const secret = "Zorbwick-faketown-20250401";
    let touched = false;
    const guarded = new File([bytes(FULL)], `${secret}.txt`);
    Object.defineProperty(guarded, "name", { get() { touched = true; return secret; } });
    const good = await parseDump(guarded);
    expect(touched).toBe(false);

    const failing = new File([bytes(withLine(FULL, 3, "Ear\tonly three\tcolumns"))], `${secret}.txt`);
    const bad = await parseDump(failing);
    expect(bad.errors).toHaveLength(1);
    const outputs = JSON.stringify([good.warnings, good.errors, bad.warnings, bad.errors, good.rows, [...good.owned]]);
    for (const part of ["Zorbwick", "faketown", "20250401", secret]) expect(outputs).not.toContain(part);
    // a file name that is itself a markup payload is just as invisible
    const markup = new File([bytes(withLine(FULL, 2, "bad"))], "<img src=x onerror=alert(1)>.txt");
    expect(JSON.stringify((await parseDump(markup)).errors)).not.toContain("<img");
  });
});

describe("the envelope: lines, line length and characters", () => {
  it("a 257-character line is rejected and the 256-character line is not", () => {
    const longRow = (total) => `Neck\t${"A".repeat(total - "Neck\t".length - "\t4301\t1\t10".length)}\t4301\t1\t10`;
    expect(longRow(257)).toHaveLength(257);
    const tooLong = parse(withLine(SMALL, 10, longRow(257)));
    expect(tooLong.errors).toHaveLength(1);
    expect(tooLong.errors[0]).toMatch(/^Line 10 is longer than 256 characters/);
    expect(tooLong.errors[0]).toContain("re-run /outputfile inventory");
    expect(tooLong.rows).toEqual([]);
    // 256 characters is inside the envelope: the file is read, and this row (a name no item has) is skipped on its own
    const edge = parse(withLine(SMALL, 10, longRow(256)));
    expect(edge.errors).toEqual([]);
    expect(skippedLine(edge, 10)).toBe(true);
    expect(edge.rows.length).toBe(parse(SMALL).rows.length - 1);
  });

  it("a header of 257 characters is rejected, not cut to 256 and compared", () => {
    const r = parse(withLine(SMALL, 1, HEADER + " ".repeat(257 - HEADER.length)));
    expect(r.errors).toHaveLength(1);
    expect(r.errors[0]).toMatch(/^Line 1 is longer than 256 characters/);
  });

  it("20,000 lines are read and 20,001 are rejected", () => {
    const build = (n) => {
      const lines = [HEADER, empty("Head"), "", KEYRING_HEADER];
      for (let i = 0; lines.length < n; i++) lines.push(keyRow("Equipment", `Spare Charm ${i}`, 600000 + i));
      return crlf(lines);
    };
    const ok = parse(build(20000));
    expect(ok.errors).toEqual([]);
    expect(ok.rows).toHaveLength(19996);
    const over = parse(build(20001));
    expect(over.errors).toEqual([ERRORS.tooManyLines]);
    expect(over.errors[0]).toContain("20000 lines");
  });

  it("one byte outside TAB and 0x20-0x7E skips that row only: 0xE9, 0x7F, 0x1B", () => {
    const neck = lineOf(SMALL, "Neck\t");
    for (const bad of ["\xe9", "\x7f", "\x1b"]) {
      const r = parse(withLine(SMALL, neck, row("Neck", `Caf${bad}`, 410006)));
      expect(r.errors).toEqual([]);
      expect(r.warnings).toHaveLength(1);
      expect(r.warnings[0]).toBe(`Line ${neck} was skipped: it has a character that /outputfile never writes.`);
      expect(r.worn.has("NECK")).toBe(false);
      expect(r.owned.has(410006)).toBe(false);
      expect(r.worn.get("CHEST")).toBeDefined(); // every other row is there
      expect(r.rows.length).toBe(parse(SMALL).rows.length - 1);
      expect(JSON.stringify([...r.warnings, ...r.rows])).not.toContain("Caf");
    }
  });

  it("a bad byte in any column skips the row; it is not a field error", () => {
    const neck = lineOf(SMALL, "Neck\t");
    for (const text of [
      `Neck\tAshen Torque\t41\xe90006\t1\t10`,
      `Ne\xe9ck\tAshen Torque\t410006\t1\t10`,
      `Neck\tAshen Torque\t410006\t1\t1\x000`,
      `Neck\tAshen\x01Torque\t410006\t1\t10\textra`,
      `Neck\tAshen Torque\t41\x7f0006\t1\t10`,
      `Neck\x7f\tAshen Torque\t410006\t1\t10`,
      `Neck\tAshen Torque\t410006\t\x7f1\t10`,
      `Neck\tAshen Torque\t410006\t1\t10\x1b`,
    ]) {
      const r = parse(withLine(SMALL, neck, text));
      expect(r.errors, text).toEqual([]);
      expect(r.warnings[0], text).toBe(`Line ${neck} was skipped: it has a character that /outputfile never writes.`);
    }
  });

  it("an unreadable row still occupies its position, so its bag stays a bag", () => {
    // General 1 holds 4 positions; position 2 is an Empty row with a bad byte. The bag must still be a bag.
    const r = parse(withLine(SMALL, 30, "General 1-Slot2\tEmpt\xe9\t0\t0\t0"));
    expect(r.errors).toEqual([]);
    expect(skippedLine(r, 30)).toBe(true);
    expect(at(r, 28).container).toBe(true);
    expect(r.owned.get(440001)).toHaveLength(1); // the Tin Flask in position 1 is still owned
    expect(r.warnings).toHaveLength(1);
  });

  it("skips the rows of a bag whose own row was skipped, instead of calling them orphans", () => {
    const r = parse(withLine(SMALL, 28, "General 1\tWicker Bask\xe9t\t420001\t1\t4"));
    expect(r.errors).toEqual([]);
    expect(skippedLine(r, 28)).toBe(true);
    // the two rows with content are announced; the Empty positions inside the bag go quietly
    expect(r.warnings.map((w) => w.match(/^Line (\d+) /)[1])).toEqual(["28", "29", "31"]);
    expect(r.owned.has(440001)).toBe(false);
    expect(r.worn.get("NECK")).toBeDefined();
    expect(r.rows.length).toBe(parse(SMALL).rows.length - 3); // the bag, the Tin Flask and the Gilded Locket
  });

  it("CR CR LF is one line end, with one warning, not a blank line after every line", () => {
    const DOUBLED = "The file has doubled line ends (CR CR LF); each was read as one line end.";
    const base = parse(SMALL);
    // the review's case: a CRLF file converted once more
    const r = parse(SMALL.split("\r\n").join("\r\r\n"));
    expect(r.errors).toEqual([]);
    expect(r.warnings).toEqual([DOUBLED]);
    expect(r.rows).toEqual(base.rows);
    expect(r.worn).toEqual(base.worn);
    expect(r.owned).toEqual(base.owned);
    // some lines doubled and some tripled, the real blank line kept, still one warning
    const lines = SMALL.split("\r\n").slice(0, -1);
    const some = lines.map((l, i) => l + (i % 7 === 0 ? "\r\r\r\n" : i % 5 === 0 ? "\r\r\n" : "\r\n")).join("");
    const mixed = parse(some);
    expect(mixed.errors).toEqual([]);
    expect(mixed.warnings).toEqual([DOUBLED]);
    expect(mixed.rows).toEqual(base.rows);
    // the same in UTF-16, and with the doubled end on the header and on the last line
    expect(parseDumpBytes(utf16(SMALL.split("\r\n").join("\r\r\n"))).warnings).toEqual([DOUBLED]);
    expect(parse(SMALL.split("\r\n").join("\r\r\n")).rows.at(-1).line).toBe(54);
    // plain CRLF, plain CR with its blank lines, and a CRLF blank line are not doubled
    for (const text of [SMALL, SMALL.split("\r\n").join("\r"), SMALL.split("\r\n").join("\n")]) expect(parse(text).warnings.filter((w) => w.includes("doubled"))).toEqual([]);
    // a very long run of CRs costs no more than any other line ends: it is looked at a few characters at a time
    const watch = stopwatch();
    const flood = parseDumpBytes(bytes(HEADER + "\r".repeat((1 << 20) - HEADER.length - 2) + "\n"));
    expectWithin(watch.stop(), 250, "a megabyte of CRs is read");
    expect(flood.errors).toEqual([ERRORS.tooManyLines]);
  });

  it("a UTF-8 byte order mark is dropped, a UTF-16 one is decoded, UTF-16 without one is refused", () => {
    const bom8 = parseDumpBytes(new Uint8Array([0xef, 0xbb, 0xbf, ...bytes(SMALL)]));
    expect(bom8.errors).toEqual([]);
    expect(bom8.rows).toEqual(parse(SMALL).rows);
    expect(parseDumpBytes(utf16(SMALL)).rows).toEqual(parse(SMALL).rows);
    const noBom = parseDumpBytes(utf16(SMALL, { bom: false }));
    expect(noBom.errors).toEqual([ERRORS.encoding]);
    expect(noBom.rows).toEqual([]);
  });

  it("refuses UTF-32 byte order marks, a second UTF-8 mark and an odd UTF-16 length", () => {
    const ascii = bytes(SMALL);
    expect(parseDumpBytes(new Uint8Array([0xff, 0xfe, 0x00, 0x00, ...ascii])).errors).toEqual([ERRORS.encoding]);
    expect(parseDumpBytes(new Uint8Array([0x00, 0x00, 0xfe, 0xff, ...ascii])).errors).toEqual([ERRORS.encoding]);
    expect(parseDumpBytes(new Uint8Array([0xef, 0xbb, 0xbf, 0xef, 0xbb, 0xbf, ...ascii])).errors).toEqual([ERRORS.encoding]);
    expect(parseDumpBytes(new Uint8Array([...utf16(SMALL), 0x41])).errors).toEqual([ERRORS.encoding]);
  });

  it("refuses binary files and bytes that are not text, naming neither", () => {
    for (const head of [[0x50, 0x4b, 0x03, 0x04], [0x1f, 0x8b, 0x08], [0x25, 0x50, 0x44, 0x46], [0x4d, 0x5a, 0x90], [0x89, 0x50, 0x4e, 0x47], [0x7f, 0x45, 0x4c, 0x46]]) {
      const r = parseDumpBytes(new Uint8Array([...head, ...bytes(SMALL)]));
      expect(r.errors).toEqual([ERRORS.binary]);
    }
    expect(parseDumpBytes(new Uint8Array(0)).errors).toEqual([ERRORS.empty]);
    expect(parseDumpBytes(new Uint8Array([0xff, 0xff, 0xff, 0xff])).errors).toHaveLength(1);
    expect(parseDumpBytes(bytes("hello")).errors).toEqual([ERRORS.notADump]);
  });
});

describe("the structure: header, sections, cut-off files", () => {
  it("the header must be exactly the five columns", () => {
    for (const bad of [
      HEADER + " ",
      HEADER.toLowerCase(),
      HEADER + "\t",
      "Location\tName\tID\tCount",
      " " + HEADER,
      HEADER.replace("Slots", "Slot"),
      HEADER.replace(/\t/g, " "),
    ]) {
      const r = parse(withLine(SMALL, 1, bad));
      expect(r.errors).toEqual([ERRORS.notADump]);
      expect(r.rows).toEqual([]);
    }
    // the header is not the first line
    expect(parse("\r\n" + SMALL).errors).toEqual([ERRORS.notADump]);
    // characters /outputfile never writes in the first line are an encoding problem
    expect(parse(withLine(SMALL, 1, HEADER + "\xe9")).errors).toEqual([ERRORS.encoding]);
  });

  it("a row with 4 or 6 columns is rejected by its line number", () => {
    const neck = lineOf(SMALL, "Neck\t");
    for (const bad of ["Neck\tAshen Torque\t410006\t1", "Neck\tAshen Torque\t410006\t1\t10\textra", "Neck", "Neck\tAshen Torque\t410006\t1\t10\t"]) {
      const r = parse(withLine(SMALL, neck, bad));
      expect(r.errors).toHaveLength(1);
      expect(r.errors[0]).toMatch(new RegExp(`^Line ${neck} does not have the expected columns`));
      expect(r.errors[0]).not.toBe(CUT_OFF);
      expect(r.rows).toEqual([]);
    }
  });

  it("a stray blank line is rejected, wherever it is", () => {
    for (const text of [
      insertAt(SMALL, 2, ""), // right after the header
      insertAt(SMALL, 8, ""), // between worn rows
      insertAt(SMALL, 51, ""), // a second blank line before the key ring header
      insertAt(SMALL, 54, ""), // inside the key ring section
    ]) {
      const r = parse(text);
      expect(r.errors).toHaveLength(1);
      expect(r.errors[0]).toMatch(/^Line \d+ /);
      expect(r.rows).toEqual([]);
    }
  });

  it("the key ring header is accepted with or without its trailing tab, nothing else", () => {
    expect(parse(withLine(SMALL, 52, "KeyRing\tName\tID\t")).errors).toEqual([]);
    expect(parse(withLine(SMALL, 52, "KeyRing\tName\tID")).errors).toEqual([]); // a header without the trailing tab is accepted too
    for (const bad of ["KeyRing\tName\tID\tx", "keyring\tName\tID\t", "KeyRing\tName\tID \t", "KeyRing\tName", "KeyRing\tName\tID\t\t", "Location\tName\tID\tCount\tSlots"]) {
      const r = parse(withLine(SMALL, 52, bad));
      expect(r.errors).toHaveLength(1);
      expect(r.errors[0]).toMatch(/^Line 52 /);
    }
  });

  it("key ring rows have exactly three columns", () => {
    for (const bad of ["Equipment\tSpare Quillcap", "Equipment\tSpare Quillcap\t450002\t1", "Equipment\tSpare Quillcap\t450002\t"]) {
      const r = parse(withLine(SMALL, 54, bad));
      expect(r.errors).toHaveLength(1);
      expect(r.errors[0]).toMatch(/^Line 54 /);
    }
  });

  it("300 Equipment rows are all kept, with one over-capacity warning", () => {
    const rows = Array.from({ length: 300 }, (_, i) => keyRow("Equipment", `Spare Charm ${i}`, 700000 + i));
    const r = parse(dump([empty("Head")], rows));
    expect(r.errors).toEqual([]);
    expect(r.rows).toHaveLength(300);
    expect(warningsAbout(r, "key ring")).toHaveLength(1);
    expect(r.owned.size).toBe(300);
  });

  it("an unknown key ring type is skipped with a warning, the known ones are not", () => {
    const r = parse(dump([empty("Head")], [keyRow("Mount", "Pale Foal Whistle", 710001), keyRow("Activated", "Whistle of Odd Tunes", 450001)]));
    expect(r.errors).toEqual([]);
    expect(r.warnings.filter((w) => w.startsWith("Line 5 was skipped"))).toHaveLength(1);
    expect([...r.owned.keys()]).toEqual([450001]);
  });

  it("every kind of skipped key ring row is announced exactly once", () => {
    const rows = [
      keyRow("Equipment", "Plain <Cap>", 1),
      keyRow("Equipment", "Plain Cap", 0),
      keyRow("Mount", "Pale Foal", 2),
      keyRow("Equipment", "Plain Cap\xe9", 3),
      keyRow("Equipment", "Plain Cap", 4),
    ];
    const r = parse(dump([empty("Head")], rows));
    expect(r.errors).toEqual([]);
    expect(r.warnings.filter((w) => w.startsWith("Line"))).toEqual([
      "Line 5 was skipped: the item name has a character that no item name uses.",
      "Line 6 was skipped: the item has ID 0.",
      "Line 7 was skipped: its location is not one this reader knows.",
      "Line 8 was skipped: it has a character that /outputfile never writes.",
    ]);
    expect([...r.owned.keys()]).toEqual([4]);
  });

  it("a missing key ring section is a warning when the file ends cleanly", () => {
    const main = FULL.split("\r\n").slice(0, 142).join("\r\n") + "\r\n"; // header and the 141 main rows
    const noBlank = parse(main);
    expect(noBlank.errors).toEqual([]);
    expect(warningsAbout(noBlank, "KeyRing")).toHaveLength(1);
    expect(noBlank.rows).toHaveLength(49);
    expect(parse(main + "\r\n").warnings).toEqual(noBlank.warnings);
    // a key ring header with no rows is a key ring section: no warning
    expect(parse(main + "\r\n" + KEYRING_HEADER + "\r\n").warnings).toEqual([]);
    // (and a header with no line end is a last line with no line end)
    expect(parse(main + "\r\n" + KEYRING_HEADER).warnings).toEqual(["Line 144 has no line end, so the last line may be cut off; re-run /outputfile inventory."]);
  });

  it("a last line with no line end, when the lines before it have one, may be cut off", () => {
    const lastLine = (n) => `Line ${n} has no line end, so the last line may be cut off; re-run /outputfile inventory.`;
    // the review's cases: a cut inside the last field is read as a smaller number, and now says so
    const cutSlots = parse([HEADER, row("Head", "Plain Cap", 11), "Bank1\tBurlap Sack\t500\t1\t1"].join("\r\n"));
    expect(cutSlots.errors).toEqual([]);
    expect(cutSlots.rows.at(-1).slots).toBe(1);
    expect(cutSlots.warnings).toContain(lastLine(3));
    const cutId = parse([HEADER, row("Head", "Plain Cap", 11), "", KEYRING_HEADER, "Equipment\tSpare Hoop +2\t4500"].join("\r\n"));
    expect(cutId.errors).toEqual([]);
    expect(cutId.rows.at(-1).id).toBe(4500);
    expect(cutId.warnings).toContain(lastLine(5));
    // a cut that leaves the wrong number of columns is still the cut-off error, not this warning
    expect(parse([HEADER, row("Head", "Plain Cap", 11), "Bank1\tTin Flask\t500\t2"].join("\r\n")).errors).toEqual([CUT_OFF]);
    // with a line end after the last line, there is nothing to say
    for (const text of [SMALL, FULL, SMALL + "\r\n"]) expect(parse(text).warnings.filter((w) => w.includes("last line"))).toEqual([]);
    // every kind of line end counts
    for (const eol of ["\r\n", "\n", "\r"]) {
      const r = parse(SMALL.split("\r\n").join(eol).slice(0, -eol.length));
      expect(r.errors, JSON.stringify(eol)).toEqual([]);
      expect(r.warnings, JSON.stringify(eol)).toEqual([lastLine(54)]);
    }
    expect(parseDumpBytes(utf16(SMALL.slice(0, -2))).warnings).toEqual([lastLine(54)]);
    // the lines before it need not be many
    expect(parse(HEADER + "\r\n" + empty("Head")).warnings).toContain(lastLine(2));
    // a file of one line has no other line to compare with (and is no dump anyway)
    expect(parse(HEADER).errors).toEqual([ERRORS.noRows]);
  });

  it("a file cut cleanly at a line end, with no key ring section and rows that stop before SharedBank6, may be cut off", () => {
    const lines = FULL.split("\r\n");
    const cutBefore = (prefix) => lines.slice(0, lines.findIndex((l) => l.startsWith(prefix))).join("\r\n") + "\r\n";
    const MAY_BE_CUT = "The file has no KeyRing section and its rows stop before SharedBank6, so the file may be cut off; re-run /outputfile inventory.";
    // the review's case: cut in the middle of the bank. It is still read, and it says so
    const r = parse(cutBefore("Bank2\t"));
    expect(r.errors).toEqual([]);
    expect(r.warnings).toEqual([MAY_BE_CUT]);
    expect(r.owned.has(420010)).toBe(true); // what came before the cut is there
    // wherever the cut falls before SharedBank6: after the worn block, in General, after Held, after SharedBank5
    for (const prefix of ["General 1\t", "General 5\t", "Held\t", "Bank1\t", "Bank24\t", "SharedBank1\t", "SharedBank6\t"]) {
      const cut = parse(cutBefore(prefix));
      expect(cut.errors, prefix).toEqual([]);
      expect(cut.warnings, prefix).toEqual([MAY_BE_CUT]);
      // and the same when the cut leaves the blank line that ends the rows
      expect(parse(cutBefore(prefix) + "\r\n").warnings, prefix).toEqual([MAY_BE_CUT]);
    }
    // a minimal dump never reaches SharedBank6 either
    expect(only(empty("Head")).warnings).toContain(MAY_BE_CUT);
    // rows that do reach SharedBank6 (even as an Empty row) and have no key ring section have the plain warning
    const whole = lines.slice(0, 142).join("\r\n") + "\r\n";
    expect(parse(whole).warnings).toEqual(["The file has no KeyRing section."]);
    // a key ring section, even an empty one, means the rows were not cut
    expect(parse(cutBefore("Bank2\t") + "\r\n" + KEYRING_HEADER + "\r\n").warnings).toEqual([]);
  });

  it("a last line with the wrong column count and no line end is the cut-off error", () => {
    const lines = FULL.split("\r\n");
    const cut = (keep, tail) => lines.slice(0, keep).join("\r\n") + "\r\n" + tail;
    // 'Bank12<TAB>Gia' with no line terminator
    const a = parse(cut(118, "Bank12\tGia"));
    expect(a.errors).toEqual([CUT_OFF]);
    expect(a.rows).toEqual([]);
    expect(a.owned.size).toBe(0);
    // cut inside a number
    expect(parse(cut(118, "Bank12\tHempen Chest\t420010\t1\t")).errors).toEqual([CUT_OFF]);
    // cut inside the key ring section
    expect(parse(cut(147, "Equipment\tSpare Quill")).errors).toEqual([CUT_OFF]);
    // 6 well-formed rows, then a 3-column row at the end of the file
    expect(parse(crlf([HEADER, empty("Any Slot"), empty("Ear"), empty("Head"), empty("Face"), empty("Ear")]) + "Neck\tAshen\t41").errors).toEqual([CUT_OFF]);
    // a complete last row without a line end is a clean end
    expect(parse(cut(147, "Equipment\tSpare Quillcap\t450002")).errors).toEqual([]);
  });

  it("the same bad row is an ordinary error when its line was ended", () => {
    const r = parse(crlf([HEADER, empty("Any Slot"), "Neck\tAshen\t41"]));
    expect(r.errors).toHaveLength(1);
    expect(r.errors[0]).toMatch(/^Line 3 does not have the expected columns/);
    expect(r.errors[0]).not.toBe(CUT_OFF);
  });

  it("a header cut in the middle is not a dump, and a header alone has no rows", () => {
    expect(parse("Location\tName").errors).toEqual([ERRORS.notADump]);
    expect(parse(HEADER + "\r\n").errors).toEqual([ERRORS.noRows]);
    expect(parse(HEADER).errors).toEqual([ERRORS.noRows]);
    expect(parse(crlf([HEADER, "", KEYRING_HEADER])).errors).toEqual([ERRORS.noRows]);
    // rows that were all skipped leave nothing to read either
    expect(parse(crlf([HEADER, "Head\tNo\xe9\t1\t1\t10"])).errors).toEqual([ERRORS.noRows]);
  });
});

describe("the fields: strict digits and ranges", () => {
  const withNumbers = (id, count, slots) => only(row("General 1", "Plain Hood", id, count, slots));

  it("IDs: 10 digits at most, then up to 2^31 - 1; leading zeros are fine", () => {
    expect(withNumbers("2147483647", 1, 10).rows[0].id).toBe(2147483647);
    expect(withNumbers("2147483648", 1, 10).errors[0]).toMatch(/^Line 2 has a number that is out of range/);
    expect(withNumbers("9999999999", 1, 10).errors[0]).toMatch(/out of range/);
    expect(withNumbers("0000000123", 1, 10).rows[0].id).toBe(123);
    expect(withNumbers("0000000123", 1, 10).errors).toEqual([]);
    expect(withNumbers("00007", 1, 10).rows[0].id).toBe(7);
    expect(withNumbers("00007", 1, 10).warnings.filter((w) => w.startsWith("Line"))).toEqual([]); // and no warning
    expect(withNumbers("12345678901", 1, 10).errors[0]).toMatch(/^Line 2 has a number that is not 1 to 10 digits/);
    for (const bad of ["0x1A", "", "-5", "+5", "1e9", " 7", "7 ", "1_000", "1.5", "Infinity", "NaN", "99999999999999999999"]) {
      const r = withNumbers(bad, 1, 10);
      expect(r.errors, bad).toHaveLength(1);
      expect(r.errors[0], bad).toMatch(/^Line 2 has a number that is not 1 to 10 digits/);
      expect(r.rows, bad).toEqual([]);
    }
  });

  it("Count: warn above 1000, refuse above 99999", () => {
    expect(withNumbers(1, 1000, 10).warnings.filter((w) => w.includes("Count"))).toEqual([]);
    expect(withNumbers(1, 1001, 10).warnings.filter((w) => w.includes("Count"))).toEqual(["Line 2: Count 1001 is above 1000."]);
    const top = withNumbers(1, 99999, 10);
    expect(top.errors).toEqual([]);
    expect(top.rows[0].count).toBe(99999);
    expect(top.warnings.filter((w) => w.includes("Count"))).toHaveLength(1);
    const over = withNumbers(1, 100000, 10);
    expect(over.errors[0]).toMatch(/^Line 2 has a number that is out of range/);
    expect(over.owned.size).toBe(0);
    for (const bad of ["-5", "1e9", "0x10", "5 "]) expect(withNumbers(1, bad, 10).errors[0], bad).toMatch(/not 1 to 10 digits/);
  });

  it("Slots: 80 at most", () => {
    expect(withNumbers(1, 1, 80).errors).toEqual([]);
    expect(withNumbers(1, 1, 81).errors[0]).toMatch(/out of range/);
    expect(withNumbers(1, 1, "x").errors[0]).toMatch(/not 1 to 10 digits/);
  });

  it("Empty is exactly Empty, 0, 0, 0", () => {
    for (const bad of [row("Head", "Empty", 4301, 0, 0), row("Head", "Empty", 0, 1, 0), row("Head", "Empty", 0, 0, 1), row("Head", "Empty", 4301, 1, 10)]) {
      const r = only(bad);
      expect(r.errors).toHaveLength(1);
      expect(r.errors[0]).toMatch(/^Line 2: an Empty row must have ID, Count and Slots 0/);
      expect(r.rows).toEqual([]);
    }
    expect(only(empty("Head"), row("Neck", "Plain Hood", 5)).errors).toEqual([]);
    // only the exact word is the empty marker
    expect(only(row("Head", "empty", 4301)).rows).toHaveLength(1);
  });

  it("an item with ID 0 or Count 0 is not a real item: that row is skipped", () => {
    const zeroId = only(row("Head", "Plain Hood", 0, 1, 10), row("Neck", "Plain Hood", 5));
    expect(zeroId.errors).toEqual([]);
    expect(skippedLine(zeroId, 2)).toBe(true);
    expect(zeroId.rows).toHaveLength(1);
    const zeroCount = only(row("Head", "Plain Hood", 4, 0, 10), row("Neck", "Plain Hood", 5));
    expect(skippedLine(zeroCount, 2)).toBe(true);
    expect(zeroCount.rows).toHaveLength(1);
  });
});

describe("locations and the tree", () => {
  const bag = (loc, slots = 4, id = 9001) => row(loc, "Plain Sack", id, 1, slots);

  it("unknown locations and a second row for a location are skipped, the file is not", () => {
    const rows = [
      row("Bank0", "Plain Hood", 1), row("Bank25", "Plain Hood", 2), row("General 13", "Plain Hood", 3), row("General 0", "Plain Hood", 4),
      row("SharedBank7", "Plain Hood", 5), row("General1", "Plain Hood", 6), row("Bank01", "Plain Hood", 7), row("Bank", "Plain Hood", 8),
      row("Dragon's Hoard1", "Plain Hood", 9), row("Bank7", "Plain Hood", 10), row("Bank7", "Plain Hood", 11), row("Bank-Slot1", "Plain Hood", 12),
      row("Held", "Plain Cap", 13), row("Neck", "Plain Cap", 14),
    ];
    const r = only(...rows);
    expect(r.errors).toEqual([]);
    expect(r.rows.map((x) => x.id)).toEqual([10, 13, 14]);
    for (const n of [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13]) expect(skippedLine(r, n), `line ${n}`).toBe(true);
    expect(skippedLine(r, 11)).toBe(false);
    expect(skippedLine(r, 12)).toBe(true); // the second Bank7
    expect(r.warnings.find((w) => w.startsWith("Line 12 was skipped"))).toContain("already listed");
    expect(r.warnings.find((w) => w.startsWith("Line 2 was skipped"))).toContain("location");
  });

  it("a leading zero, a space or a different case in a root's number is an unknown location: General 01 is not General 1", () => {
    for (const bad of ["General 01", "General 001", "General 0", "SharedBank01", "Bank01", "Bank001", "General  1", " General 1", "General 1 ", "general 1", "General 1.0", "General +1"]) {
      const r = only(row("Head", "Plain Cap", 1), row(bad, "Plain Hood", 2), row("General 1", "Plain Hood", 3));
      expect(r.errors, bad).toEqual([]);
      expect(r.warnings.filter((w) => w.startsWith("Line 3")), bad).toEqual(["Line 3 was skipped: its location is not one this reader knows."]);
      expect(r.owned.has(2), bad).toBe(false);
      expect(r.owned.has(3), bad).toBe(true); // the real General 1 on the next line is read
    }
    // and the numbers that are right are read: 1 to 12, 1 to 24, 1 to 6
    const good = only(row("General 12", "Plain Cap", 1), row("Bank24", "Plain Cap", 2), row("SharedBank6", "Plain Cap", 3));
    expect(good.warnings.filter((w) => w.startsWith("Line"))).toEqual([]);
    expect([...good.owned.keys()]).toEqual([1, 2, 3]);
  });

  it("a location that is not a position of anything is an unknown location, not an orphan", () => {
    const r = only(row("Slot1", "Plain Hood", 1), row("Neck", "Plain Cap", 2));
    expect(r.errors).toEqual([]);
    expect(skippedLine(r, 2)).toBe(true);
    expect(r.rows).toHaveLength(1);
  });

  it("a position row with no row at all at its container's location is rejected as an orphan", () => {
    // (a) the very first row
    expect(only(row("General 1-Slot1", "Plain Hood", 999)).errors[0]).toMatch(/^Line 2 sits in/);
    // (c) an Empty socket row with no item
    expect(only(empty("Head-Slot7")).errors[0]).toMatch(/^Line 2 sits in/);
    // (d) the parent appears only after its child
    expect(only(row("Bank2-Slot1", "Plain Hood", 1), bag("Bank2")).errors[0]).toMatch(/^Line 2 sits in/);
  });

  it("an Empty row at a location is no parent: what is printed under it is skipped", () => {
    // a row printed under an Empty place has a row at its container's location, an Empty one: it is skipped, the file is not refused
    const under = only(empty("Bank3"), row("Bank3-Slot1", "Plain Hood", 999), row("Head", "Plain Cap", 5));
    expect(under.errors).toEqual([]);
    expect(under.warnings.filter((w) => w.startsWith("Line"))).toEqual(["Line 3 was skipped: the row it belongs to is Empty or was skipped."]);
    expect(under.rows.map((x) => x.name)).toEqual(["Plain Cap"]);
    // the review's case: the second Ear is Empty, and rows are printed under Ear after it
    const r = only(empty("Any Slot"), row("Ear", "Brass Stud +1", 21), empty("Ear-Slot7"), empty("Head"), empty("Face"), empty("Ear"), row("Ear-Slot8", "Ember Facet (Exaltation)", 22), row("Ear-Slot1", "Glimmer Bauble", 23));
    expect(r.errors).toEqual([]);
    expect(skippedLine(r, 8)).toBe(true);
    expect(skippedLine(r, 9)).toBe(true);
    // the first Ear keeps its own socket row only: nothing was printed under it that is not its own
    expect(r.rows.map((x) => x.name)).toEqual(["Brass Stud"]);
    expect(r.rows.filter((x) => x.socket !== null)).toEqual([]);
    expect(r.warnings.filter((w) => w.includes("socket"))).toEqual([]);
    expect([...r.owned.keys()]).toEqual([21]);
    expect(problemsIn(r)).toEqual([]);
  });

  it("the same for every pair of worn slots, and a pair whose first place is Empty keeps the rows of the second", () => {
    for (const root of ["Ear", "Wrist", "Fingers", "Any Slot"]) {
      const stray = only(row(root, "Plain Cap +1", 21), empty(`${root}-Slot7`), empty(root), row(`${root}-Slot8`, "Zorble Gem (Exaltation)", 22));
      expect(stray.errors, root).toEqual([]);
      expect(skippedLine(stray, 5), root).toBe(true);
      expect(stray.rows.map((x) => x.line), root).toEqual([2]);
      // Empty first, a real item second: its rows are its own
      const second = only(empty(root), row(root, "Plain Cap +1", 21), row(`${root}-Slot7`, "Zorble Gem (Exaltation)", 22));
      expect(second.errors, root).toEqual([]);
      expect(second.rows.map((x) => [x.line, x.socket && x.socket.kind]), root).toEqual([[3, null], [4, "Focus"]]);
      expect(second.warnings.filter((w) => w.startsWith("Line")), root).toEqual([]);
    }
  });

  it("three levels of positions are read, a fourth is skipped with a warning and the file is not refused", () => {
    const three = only(bag("Bank1", 4, 1), bag("Bank1-Slot2", 4, 2), bag("Bank1-Slot2-Slot3", 4, 3), row("Bank1-Slot2-Slot3-Slot4", "Plain Hood", 4));
    expect(three.errors).toEqual([]);
    expect(three.rows.map((x) => x.path.length)).toEqual([0, 1, 2, 3]);
    expect(three.owned.get(4)[0].location).toBe("Bank1-Slot2-Slot3-Slot4");
    const four = only(bag("Bank1", 4, 1), bag("Bank1-Slot2", 4, 2), bag("Bank1-Slot2-Slot3", 4, 3), bag("Bank1-Slot2-Slot3-Slot4", 4, 4), row("Bank1-Slot2-Slot3-Slot4-Slot5", "Plain Hood", 5));
    expect(four.errors).toEqual([]);
    expect(four.rows.map((x) => x.path.length)).toEqual([0, 1, 2, 3]); // what is within three levels is read
    expect(four.warnings.filter((w) => w.includes("nested"))).toEqual(["Line 6 was skipped: it is nested more than 3 levels deep."]);
    expect(four.owned.has(5)).toBe(false);
  });

  it("one row four levels down in an otherwise fine file costs that row, not the file", () => {
    // the review's case: a socket row under an item that is already three levels down
    const lines = SMALL.split("\r\n");
    const at = lines.findIndex((l) => l.startsWith("General 2\t"));
    const extra = [
      "General 9\tBurlap Sack\t500\t1\t1",
      "General 9-Slot1\tReed Pouch\t501\t1\t1",
      "General 9-Slot1-Slot1\tTwig Box\t502\t1\t1",
      "General 9-Slot1-Slot1-Slot1\tGarnet Ring +1\t503\t1\t10",
      "General 9-Slot1-Slot1-Slot1-Slot7\tEmpty\t0\t0\t0",
    ];
    lines.splice(at, 0, ...extra);
    const r = parse(lines.join("\r\n"));
    expect(r.errors).toEqual([]);
    expect(r.owned.has(503)).toBe(true); // the item three levels down is read
    expect(r.rows.length).toBe(parse(SMALL).rows.length + 4);
    // an Empty row cannot lose anything, so it is skipped without a word
    expect(r.warnings.filter((w) => w.includes("nested"))).toEqual([]);
    // a stone in that socket is something, so it is said
    lines[at + 4] = "General 9-Slot1-Slot1-Slot1-Slot7\tZorble Gem (Exaltation)\t504\t1\t10";
    const withStone = parse(lines.join("\r\n"));
    expect(withStone.errors).toEqual([]);
    expect(withStone.warnings.filter((w) => w.includes("nested"))).toEqual([`Line ${at + 5} was skipped: it is nested more than 3 levels deep.`]);
  });

  it("an Empty row followed by a second row at the same location skips the second row and what sits in it, and the file is read", () => {
    // the review's case: General 1 is listed Empty, then again as a bag with positions
    const r = only(row("Head", "Plain Cap", 11), empty("General 1"), row("General 1", "Burlap Sack", 500, 1, 2), empty("General 1-Slot1"), empty("General 1-Slot2"));
    expect(r.errors).toEqual([]);
    expect(skippedLine(r, 4)).toBe(true);
    expect(r.rows.map((x) => x.name)).toEqual(["Plain Cap"]);
    // real things in the second row are skipped one by one, each with its warning
    const full = only(row("Head", "Plain Cap", 11), empty("General 1"), row("General 1", "Burlap Sack", 500, 1, 2), row("General 1-Slot1", "Garnet Ring", 503), row("General 1-Slot2", "Tin Flask", 509));
    expect(full.errors).toEqual([]);
    for (const n of [4, 5, 6]) expect(skippedLine(full, n), `line ${n}`).toBe(true);
    expect([...full.owned.keys()]).toEqual([11]);
    expect(problemsIn(full)).toEqual([]);
    // the same one level down: a position listed Empty and then again with a bag in it
    const nested = only(bag("Bank1", 4, 1), empty("Bank1-Slot1"), row("Bank1-Slot1", "Burlap Sack", 500, 1, 2), row("Bank1-Slot1-Slot1", "Garnet Ring", 503), empty("Bank1-Slot2"), empty("Bank1-Slot3"), empty("Bank1-Slot4"));
    expect(nested.errors).toEqual([]);
    expect(skippedLine(nested, 4)).toBe(true); // the second row for Bank1-Slot1
    expect(skippedLine(nested, 5)).toBe(true); // the ring in it
    expect([...nested.owned.keys()]).toEqual([1]);
    expect(problemsIn(nested)).toEqual([]);
  });

  it("a 10-slot bag's children are bag positions even though they are numbered like sockets", () => {
    const children = Array.from({ length: 10 }, (_, i) => row(`General 1-Slot${i + 1}`, `Plain Cap ${i + 1}`, 100 + i));
    const r = only(row("General 1", "Giant Sack", 17010, 1, 10), ...children);
    expect(r.errors).toEqual([]);
    expect(r.warnings.filter((w) => !w.includes("worn") && !w.includes("KeyRing"))).toEqual([]);
    expect(at(r, 2).container).toBe(true);
    expect(r.owned.size).toBe(11); // the bag and all ten items
    expect(r.rows.filter((x) => x.socket !== null)).toEqual([]);
  });

  it("an item with Slots 10 and a lone position 8 holds a Click socket; its content is never owned", () => {
    const r = only(row("General 1", "Zorble Gem +2", 5500), row("General 1-Slot7", "Zorble Gem (Exaltation)", 5500), row("General 1-Slot8", "Zorble Gem (Exaltation)", 5500));
    expect(r.errors).toEqual([]);
    expect(at(r, 2).container).toBe(false);
    expect(at(r, 4).socket).toEqual({ index: 8, kind: "Click" });
    expect(r.owned.get(5500)).toHaveLength(1);
    expect(r.owned.get(5500)[0]).toMatchObject({ count: 1, tier: 2, location: "General 1" });
  });

  it("a parent with Slots 10 that prints any position from 3 to 6 is a bag, because an item never prints those", () => {
    for (const position of [3, 4, 5, 6]) {
      const r = only(row("Bank1", "Plain Sack", 1, 1, 10), row(`Bank1-Slot${position}`, "Plain Cap", 2));
      expect(r.errors, `position ${position}`).toEqual([]);
      expect(at(r, 2).container, `position ${position}`).toBe(true);
      expect(at(r, 3).socket, `position ${position}`).toBe(null);
      expect(r.owned.has(2), `position ${position}`).toBe(true);
      expect(warningsAbout(r, "positions"), `position ${position}`).toEqual(["Line 2: the positions listed do not match the container's size."]);
      expect(problemsIn(r), `position ${position}`).toEqual([]);
    }
    // the same one level down, inside a bag: the item at position 2 is itself a bag
    const nested = only(bag("Bank1", 4, 1), row("Bank1-Slot2", "Gilded Locket", 2), row("Bank1-Slot2-Slot3", "Plain Pebble", 77), empty("Bank1-Slot1"), empty("Bank1-Slot3"), empty("Bank1-Slot4"));
    expect(nested.errors).toEqual([]);
    expect(at(nested, 3).container).toBe(true);
    expect(at(nested, 4).socket).toBe(null);
    expect(nested.owned.has(77)).toBe(true);
    // the positions an item does print leave it an item
    for (const positions of [[1], [2], [1, 2], [7], [7, 8, 9, 10], [1, 2, 7, 8, 9, 10]]) {
      const r = only(row("Bank1", "Plain Hood +4", 1), ...positions.map((p) => row(`Bank1-Slot${p}`, "Zorble Gem (Exaltation)", 2)));
      expect(at(r, 2).container, positions.join()).toBe(false);
      expect(r.rows.slice(1).every((x) => x.socket !== null), positions.join()).toBe(true);
    }
  });

  it("a 10-slot bag that lost one position row is still a bag: all it holds is owned", () => {
    const rows = [
      row("General 1", "Burlap Sack", 500, 1, 10),
      row("General 1-Slot1", "Lantern Oil", 501, 5),
      row("General 1-Slot2", "Reed Pouch", 502, 1, 2),
      row("General 1-Slot2-Slot1", "Garnet Ring", 503),
      empty("General 1-Slot2-Slot2"),
    ];
    for (let p = 3; p <= 9; p++) rows.push(empty(`General 1-Slot${p}`)); // the row for Slot10 is missing
    const r = only(...rows);
    expect(r.errors).toEqual([]);
    expect(r.rows.filter((x) => x.container).map((x) => x.line)).toEqual([2, 4]);
    expect(r.rows.filter((x) => x.socket !== null)).toEqual([]);
    expect([...r.owned.keys()]).toEqual([500, 501, 502, 503]);
    expect(warningsAbout(r, "positions")).toEqual(["Line 2: the positions listed do not match the container's size."]);
    expect(problemsIn(r)).toEqual([]);
  });

  it("an unreadable row whose location has a stray byte keeps its position, so the bag stays whole", () => {
    const rows = [row("Bank3", "Burlap Sack", 500, 1, 10)];
    for (let p = 1; p <= 10; p++) rows.push(p === 4 ? row("Bank3-Slot4\xa0", "Tin Flask", 509) : p === 1 ? row("Bank3-Slot1", "Garnet Ring", 503) : empty(`Bank3-Slot${p}`));
    const r = only(...rows);
    expect(r.errors).toEqual([]);
    expect(r.warnings.filter((w) => w.startsWith("Line"))).toEqual(["Line 6 was skipped: it has a character that /outputfile never writes."]);
    expect(at(r, 2).container).toBe(true);
    expect([...r.owned.keys()]).toEqual([500, 503]); // the Tin Flask could not be read
    expect(warningsAbout(r, "positions")).toEqual([]); // all ten positions are accounted for
    expect(problemsIn(r)).toEqual([]);
  });

  it("an unreadable row is placed only when its location is a clean location followed by stray bytes", () => {
    const bag4 = row("Bank3", "Burlap Sack", 500, 1, 4);
    // the byte is inside the root: nothing can be placed, and the bag (Slots 4) is a bag all the same
    const inside = only(bag4, row("Ban\xa0k3-Slot1", "Tin Flask", 509), empty("Bank3-Slot2"), empty("Bank3-Slot3"), empty("Bank3-Slot4"));
    expect(inside.errors).toEqual([]);
    expect(skippedLine(inside, 3)).toBe(true);
    expect(at(inside, 2).container).toBe(true);
    expect(warningsAbout(inside, "positions")).toHaveLength(1);
    // the byte is followed by a digit: the position it names is not known, so it is not taken
    const unsure = only(bag4, row("Bank3-Slot1\xa00", "Tin Flask", 509), row("Bank3-Slot1", "Garnet Ring", 503), empty("Bank3-Slot2"), empty("Bank3-Slot3"), empty("Bank3-Slot4"));
    expect(unsure.errors).toEqual([]);
    expect(unsure.warnings.filter((w) => w.startsWith("Line"))).toEqual(["Line 3 was skipped: it has a character that /outputfile never writes."]);
    expect(unsure.owned.get(503)[0].location).toBe("Bank3-Slot1");
    expect(warningsAbout(unsure, "positions")).toEqual([]);
  });

  it("socket content is never a bag: nothing in a bag that sits in a socket is owned", () => {
    const r = only(row("Head", "Plain Cap +1", 11), row("Head-Slot7", "Burlap Sack", 500, 1, 2), row("Head-Slot7-Slot1", "Garnet Ring", 503), empty("Head-Slot7-Slot2"));
    expect(r.errors).toEqual([]);
    expect(at(r, 3)).toMatchObject({ container: false, socket: { index: 7, kind: "Focus" } }); // it prints every position of its size, and is still no bag
    expect(at(r, 4)).toMatchObject({ container: false, socket: { index: 1, kind: "Nested" } });
    expect([...r.owned.keys()]).toEqual([11]);
    expect(problemsIn(r)).toEqual([]);
    // what sits in a socket is not asked for sockets of its own, whatever its tier
    const tiered = only(row("Head", "Plain Cap +1", 11), row("Head-Slot7", "Burlap Sack +2", 500, 1, 2), row("Head-Slot7-Slot1", "Garnet Ring", 503));
    expect(tiered.warnings.filter((w) => w.startsWith("Line"))).toEqual([]);
  });

  it("socket status goes down to every descendant, however deep", () => {
    const r = only(
      row("Head", "Plain Cap +1", 11),
      row("Head-Slot7", "Burlap Sack", 500, 1, 2),
      row("Head-Slot7-Slot1", "Reed Pouch", 501, 1, 2),
      row("Head-Slot7-Slot1-Slot1", "Garnet Ring", 503),
      empty("Head-Slot7-Slot1-Slot2"),
      row("Head-Slot7-Slot2", "Tin Flask", 509),
    );
    expect(r.errors).toEqual([]);
    expect(r.rows.map((x) => [x.line, x.container, x.socket && x.socket.kind])).toEqual([
      [2, false, null], [3, false, "Focus"], [4, false, "Nested"], [5, false, "Nested"], [7, false, "Nested"],
    ]);
    expect([...r.owned.keys()]).toEqual([11]);
    expect(problemsIn(r)).toEqual([]);
  });

  it("what sits under a stone or an ornament is socket content too, and neither is ever a bag", () => {
    for (const name of ["Zorble Gem (Exaltation)", "Gilded Frill (Ornamentation)", "Zorble Gem (Exaltation)*"]) {
      const r = only(row("General 1", "Plain Sack", 1, 1, 2), row("General 1-Slot1", name, 5500, 1, 2), row("General 1-Slot1-Slot1", "Garnet Ring", 503), empty("General 1-Slot1-Slot2"), empty("General 1-Slot2"));
      expect(r.errors, name).toEqual([]);
      expect(at(r, 2).container, name).toBe(true);
      expect(at(r, 3), name).toMatchObject({ container: false, socket: null }); // in a bag position: not socket content, but no bag
      expect(at(r, 4), name).toMatchObject({ container: false, socket: { index: 1, kind: "Nested" } });
      expect([...r.owned.keys()], name).toEqual([1]);
      expect(problemsIn(r), name).toEqual([]);
    }
  });

  it("a container that prints fewer positions than its Slots stays a container and gets a warning", () => {
    const r = only(row("General 1", "Wicker Basket", 1, 1, 8), row("General 1-Slot1", "Plain Hood", 2), row("General 1-Slot2", "Plain Cap", 3), empty("General 1-Slot3"));
    expect(r.errors).toEqual([]);
    expect(at(r, 2).container).toBe(true);
    expect(r.owned.has(2) && r.owned.has(3)).toBe(true);
    expect(warningsAbout(r, "positions")).toEqual(["Line 2: the positions listed do not match the container's size."]);
  });

  it("checks the sockets an item prints against its tier, and prints no warning when they agree", () => {
    const warnFor = (tier, sockets) => {
      const name = tier ? `Plain Hood +${tier}` : "Plain Hood";
      return only(row("Head", name, 5), ...sockets.map((s) => empty(`Head-Slot${s}`))).warnings.filter((w) => w.includes("socket"));
    };
    expect(warnFor(0, [])).toEqual([]);
    expect(warnFor(1, [7])).toEqual([]);
    expect(warnFor(4, [7, 8, 9, 10])).toEqual([]);
    expect(warnFor(7, [7, 8, 9, 10])).toEqual([]); // four sockets at most
    expect(warnFor(2, [7])).toEqual(["Line 2: the sockets listed do not match the item's tier."]);
    // socket 10 on a +1 item
    expect(warnFor(1, [7, 10])).toEqual(["Line 2: the sockets listed do not match the item's tier."]);
    expect(warnFor(1, [7, 11])).toHaveLength(2); // no match, and a socket number above 10
    expect(warnFor(1, [7, 11]).some((w) => w.includes("above 10"))).toBe(true);
  });

  it("the worn pairs are told apart by their order; a swapped order warns and is read by name", () => {
    const standard = parse(SMALL);
    expect(standard.warnings).toEqual([]);
    const lines = SMALL.split("\r\n");
    const swapped = [...lines];
    [swapped[21], swapped[11]] = [lines[11], lines[21]]; // Chest (line 22) and Arms (line 12) trade places
    const r = parse(swapped.join("\r\n"));
    expect(r.errors).toEqual([]);
    expect(r.warnings).toEqual(["The worn slots are not in the usual order; they were read by name."]);
    expect(r.worn.get("CHEST").name).toBe("Moth-Eaten Rag*");
    expect(r.worn.get("EAR1").name).toBe("Brindle Stud");
  });

  it("a third Ear row, or a 24th worn row, is skipped and never replaces the second", () => {
    const base = parse(FULL);
    const r = parse(insertAt(FULL, 12, row("Ear", "Rogue Stud", 999001)));
    expect(r.errors).toEqual([]);
    expect(skippedLine(r, 12)).toBe(true);
    expect(r.worn.get("EAR2").name).toBe("Pewter Hoop");
    expect(r.worn.get("EAR1").name).toBe("Brindle Stud");
    expect(r.rows.length).toBe(base.rows.length);
    expect(r.owned.has(999001)).toBe(false);
    // the children of the extra row are skipped with it
    const withKids = parse(insertAt(FULL, 12, row("Ear", "Rogue Stud +1", 999001), row("Ear-Slot7", "Plain Pebble", 999002)));
    expect(skippedLine(withKids, 12)).toBe(true);
    expect(skippedLine(withKids, 13)).toBe(true);
    expect(withKids.errors).toEqual([]);
    // a 24th worn row of another kind
    const extra = parse(insertAt(FULL, 38, row("Head", "Rogue Cap", 999003)));
    expect(skippedLine(extra, 38)).toBe(true);
    expect(extra.worn.get("HEAD").name).toBe("Tarnished Quillcap");
    expect(extra.warnings.some((w) => w.includes("usual order"))).toBe(true);
  });

  it("the Held row is the cursor: in owned for a note, never in the worn slots", () => {
    const cursor = withLine(FULL, 91, row("Held", "Wayward Pebble", 777001));
    const r = parse(cursor);
    expect(r.errors).toEqual([]);
    expect(r.worn.has("HELD")).toBe(false);
    expect(r.worn.has("SECONDARY")).toBe(true);
    expect([...r.worn.values()].every((x) => x.place === "worn")).toBe(true);
    expect(r.owned.get(777001)).toEqual([expect.objectContaining({ place: "cursor", location: "Held", count: 1, slot: null })]);
    expect(at(r, 91)).toMatchObject({ place: "cursor", slot: null });
    // a bag on the cursor has its positions like any bag
    const bagOnCursor = only(row("Held", "Plain Sack", 777002, 1, 2), row("Held-Slot1", "Plain Cap", 777003), empty("Held-Slot2"));
    expect(bagOnCursor.errors).toEqual([]);
    expect(bagOnCursor.owned.get(777003)[0]).toMatchObject({ place: "cursor", location: "Held-Slot1" });
  });

  it("a position is 1 to 99 with no leading zero; anything else is an unknown location", () => {
    const parent = row("Bank1", "Plain Sack", 1, 1, 80);
    for (const bad of ["Bank1-Slot0", "Bank1-Slot100", "Bank1-Slot01", "Bank1-SlotX", "Bank1-Slot", "Bank1-Slot1x", "Bank1-Slot-1", "Bank1-slot1", "Bank1-Slot 1", "Bank1-Slot1-"]) {
      const r = only(parent, row(bad, "Plain Cap", 2));
      expect(r.errors, bad).toEqual([]);
      expect(skippedLine(r, 3), bad).toBe(true);
      expect(r.rows, bad).toHaveLength(1);
    }
    const ok = only(parent, row("Bank1-Slot99", "Plain Cap", 2), row("Bank1-Slot9", "Plain Cap", 3), row("Bank1-Slot10", "Plain Cap", 4));
    expect(ok.errors).toEqual([]);
    expect(ok.owned.get(2)[0].location).toBe("Bank1-Slot99");
    expect(ok.owned.get(4)[0].location).toBe("Bank1-Slot10");
  });

  it("the socket positions are named: 1 and 2 ornament/legacy, 7 Focus, 8 Click, 9 Worn, 10 Proc, above 10 unknown", () => {
    const r = only(row("Head", "Plain Hood +4", 5), ...[1, 2, 7, 8, 9, 10, 11].map((p) => row(`Head-Slot${p}`, "Plain Pebble", 100 + p)));
    expect(r.errors).toEqual([]);
    expect(r.rows.filter((x) => x.socket).map((x) => [x.socket.index, x.socket.kind])).toEqual([
      [1, "Ornament"], [2, "Ornament"], [7, "Focus"], [8, "Click"], [9, "Worn"], [10, "Proc"], [11, "Unknown"],
    ]);
    expect(r.owned.size).toBe(1); // only the Head item itself
  });

  it("a stone or an ornament in a worn slot is not worn: the slot stays empty, with a warning", () => {
    for (const name of ["Zorble Gem (Exaltation)", "Gilded Frill (Ornamentation)"]) {
      const r = only(row("Head", name, 5), row("Neck", "Plain Cap", 6));
      expect(r.errors, name).toEqual([]);
      expect(r.worn.has("HEAD"), name).toBe(false);
      expect(r.worn.has("NECK"), name).toBe(true);
      expect(r.warnings.filter((w) => w.startsWith("Line 2")), name).toEqual(["Line 2: a stone or ornament in a worn slot is ignored."]);
      expect(r.owned.has(5), name).toBe(false);
      expect(r.rows, name).toHaveLength(2);
    }
  });

  it("a worn item with Count above 1 gets a warning, except ammunition", () => {
    const r = parse(withLine(SMALL, 10, row("Neck", "Ashen Torque", 410006, 3)));
    expect(warningsAbout(r, "worn item")).toEqual(["Line 10: a worn item with a Count above 1."]);
    expect(parse(SMALL).warnings).toEqual([]); // the 40 Flint Darts in Ammo are fine
  });
});

describe("item names", () => {
  const nameOf = (name) => only(row("Head", name, 4301)).rows[0];
  const warnsOf = (name) => only(row("Head", name, 4301)).warnings.filter((w) => w.startsWith("Line 2"));

  it("the tier is a trailing ' +N' suffix; both star positions are accepted", () => {
    expect(nameOf("Plain Hood +10")).toMatchObject({ name: "Plain Hood", tier: 10 });
    expect(warnsOf("Plain Hood +10")).toEqual([]);
    expect(nameOf("Plain Hood +1")).toMatchObject({ name: "Plain Hood", tier: 1 });
    expect(nameOf("Plain Hood* +3")).toMatchObject({ name: "Plain Hood*", tier: 3 });
    expect(nameOf("Plain Hood +3*")).toMatchObject({ name: "Plain Hood*", tier: 3 });
    expect(nameOf("Plain Hood*")).toMatchObject({ name: "Plain Hood*", tier: 0 });
    // tier 0 prints nothing, so there is no warning for it
    expect(warnsOf("Plain Hood")).toEqual([]);
  });

  it("a tier above +10 is read as +10 with a warning", () => {
    expect(nameOf("Plain Hood +11")).toMatchObject({ name: "Plain Hood", tier: 10 });
    expect(warnsOf("Plain Hood +11")).toEqual(["Line 2: tier +11 is above +10, so it is read as +10."]);
    expect(nameOf("Plain Hood +99").tier).toBe(10);
    expect(nameOf("Plain Hood +999").tier).toBe(10);
  });

  it("anything else stays part of the name: no space, +0, leading zero, four digits", () => {
    expect(nameOf("Plain Hood+3")).toMatchObject({ name: "Plain Hood+3", tier: 0 });
    expect(nameOf("Plain Hood +0")).toMatchObject({ name: "Plain Hood +0", tier: 0 });
    expect(nameOf("Plain Hood +03")).toMatchObject({ name: "Plain Hood +03", tier: 0 });
    expect(nameOf("Plain Hood +1000")).toMatchObject({ name: "Plain Hood +1000", tier: 0 });
    expect(nameOf("Plain Hood + 3")).toMatchObject({ name: "Plain Hood + 3", tier: 0 });
    expect(nameOf("+3")).toMatchObject({ name: "+3", tier: 0 });
    // the no-space forms are literal names; only 'Name* +3' and 'Name +3*' are tier suffixes
    expect(nameOf("Plain Hood*+3")).toMatchObject({ name: "Plain Hood*+3", tier: 0 });
    expect(nameOf("Plain Hood+3*")).toMatchObject({ name: "Plain Hood+3*", tier: 0 });
  });

  it("two spaces before ' +N' are not a tier suffix: the name keeps them and never ends in a space", () => {
    for (const raw of ["Plain Hood  +5", "Plain Hood  +5*", "Plain Hood   +5", "Plain Hood*  +5", "Plain Hood  +10"]) {
      const x = nameOf(raw);
      expect(x, raw).toMatchObject({ name: raw, tier: 0 });
      expect(x.name.endsWith(" "), raw).toBe(false);
      expect(problemsIn(only(row("Head", raw, 4301))), raw).toEqual([]);
    }
    // one space is a tier, as before, and a stone's name is handled the same way
    expect(nameOf("Plain Hood +5")).toMatchObject({ name: "Plain Hood", tier: 5 });
    expect(nameOf("Plain Hood +5*")).toMatchObject({ name: "Plain Hood*", tier: 5 });
    expect(nameOf("Zorble Gem  +2 (Exaltation)")).toMatchObject({ name: "Zorble Gem  +2 (Exaltation)", stone: true, tier: 0 });
  });

  it("two tier suffixes: the last one is read, once, with a warning", () => {
    expect(nameOf("Plain Hood +3 +4")).toMatchObject({ name: "Plain Hood +3", tier: 4 });
    expect(warnsOf("Plain Hood +3 +4")).toEqual(["Line 2: the name has two tier suffixes; only the last one is read."]);
  });

  it("names that end in digits keep them: only ' +N' is a tier", () => {
    const r = only(row("General 1", "Zephyr Blade 4", 1), row("General 2", "Quarry Mattock 628 +3", 2), row("General 3", "Nettle Primer Pg. 450", 3));
    expect(r.rows.map((x) => [x.name, x.tier])).toEqual([["Zephyr Blade 4", 0], ["Quarry Mattock 628", 3], ["Nettle Primer Pg. 450", 0]]);
  });

  it("accepts the characters the catalog's names use and a little more, up to 96 of them", () => {
    for (const ok of ["Tunare's Blessing", "Tunare`s Blessing", "Ring: Of, Odd. Things-(Old)/New #1 & Co!?", "A".repeat(96), "x"]) {
      expect(only(row("Head", ok, 4301)).rows, ok).toHaveLength(1);
    }
  });

  it("skips a row whose name has other characters, is empty, is too long, or starts or ends with a space", () => {
    for (const bad of ["Plain <Hood>", 'Plain "Hood"', "Plain=Hood", "Plain_Hood", "__proto__", "Plain;Hood", "Plain%Hood", "Plain[Hood]", "Plain|Hood", "Plain\\Hood", "~Plain", "", " Plain Hood", "Plain Hood ", "A".repeat(97)]) {
      const r = only(row("Head", bad, 4301), row("Neck", "Plain Cap", 5));
      expect(r.errors, bad).toEqual([]);
      expect(skippedLine(r, 2), bad).toBe(true);
      expect(r.rows, bad).toHaveLength(1);
    }
  });

  it("stones share their source's ID but add nothing to owned", () => {
    const r = only(
      row("General 2", "Zorble Gem +2", 5500),
      row("General 2-Slot7", "Zorble Gem (Exaltation)", 5500),
      row("General 2-Slot8", "Zorble Gem (Exaltation)", 5500),
    );
    expect(r.errors).toEqual([]);
    expect(r.warnings.filter((w) => w.startsWith("Line"))).toEqual([]);
    expect(r.owned.get(5500)).toHaveLength(1);
    expect(r.owned.get(5500)[0].count).toBe(1);
    expect(r.rows.filter((x) => x.stone).map((x) => [x.line, x.id])).toEqual([[3, 5500], [4, 5500]]);
    expect(r.rows.filter((x) => x.stone).every((x) => x.name.endsWith(" (Exaltation)"))).toBe(true);
  });

  it("a stone that carries a tier gets one warning and adds nothing", () => {
    for (const stone of ["Zorble Gem (Exaltation) +2", "Zorble Gem +2 (Exaltation)"]) {
      const r = only(row("General 2", "Zorble Gem +2", 5500), row("General 2-Slot7", stone, 5500), row("General 2-Slot8", "Zorble Gem (Exaltation)", 5500));
      expect(r.errors, stone).toEqual([]);
      expect(r.warnings.filter((w) => w.startsWith("Line 3")), stone).toEqual(["Line 3: a stone with a tier; the tier is ignored."]);
      expect(r.rows.find((x) => x.line === 3)).toMatchObject({ stone: true, tier: 0 });
      expect(r.owned.get(5500)).toHaveLength(1);
    }
  });

  it("a stone outside sockets 7 to 10 gets one warning and adds nothing", () => {
    // positions 1 and 2 are the ornament/legacy places of an item, not sockets 7 to 10
    for (const position of [1, 2]) {
      const r = only(
        row("General 2", "Zorble Gem +2", 5500),
        row(`General 2-Slot${position}`, "Zorble Gem (Exaltation)", 5500),
        row("General 2-Slot7", "Zorble Gem (Exaltation)", 5500),
        row("General 2-Slot8", "Zorble Gem (Exaltation)", 5500),
      );
      expect(r.errors, `position ${position}`).toEqual([]);
      expect(r.warnings.filter((w) => w.startsWith("Line")), `position ${position}`).toEqual(["Line 3: a stone outside sockets 7 to 10."]);
      expect(r.owned.get(5500), `position ${position}`).toHaveLength(1);
    }
    // so is a stone beyond socket 10
    const high = only(row("Chest", "Plain Tunic", 41), row("Chest-Slot11", "Stone of Might (Exaltation)", 12345));
    expect(high.warnings.filter((w) => w.startsWith("Line 3"))).toEqual(["Line 3: a stone outside sockets 7 to 10."]);
    expect(high.owned.has(12345)).toBe(false);
    // a stone at position 3 to 6 makes its parent a bag (an item never prints those), so it is no socket stone
    for (const position of [3, 6]) {
      const bagLike = only(row("Chest", "Plain Tunic", 41), row(`Chest-Slot${position}`, "Stone of Might (Exaltation)", 12345));
      expect(at(bagLike, 2).container, `position ${position}`).toBe(true);
      expect(bagLike.warnings.filter((w) => w.startsWith("Line 3")), `position ${position}`).toEqual([]);
      expect(bagLike.owned.has(12345), `position ${position}`).toBe(false);
    }
  });

  it("a name that looks like a link or a script is data: it comes back as the plain text it is, and the header says never to build a link from it", () => {
    for (const text of ["javascript:alert(1)", "JavaScript:alert(document.cookie)", "data:text/html,x", "vbscript:x", "https://example.invalid/path", "//example.invalid/x", "file:/etc/passwd"]) {
      const x = nameOf(text);
      expect(x.name, text).toBe(text); // not escaped, not encoded, not cut
      expect(typeof x.name, text).toBe("string");
      expect(Object.keys(x).filter((k) => typeof x[k] === "object" && x[k] !== null && k !== "path" && k !== "socket"), text).toEqual([]); // no object made from it
      expect(only(row("Head", text, 4301)).owned.get(4301)[0].name, text).toBe(text);
      expect(only(row("Head", text, 4301)).errors, text).toEqual([]);
    }
    // the header of the module states the rule for whoever shows these names
    const header = readFileSync(new URL("../pipeline/trioforge/site/static/input/dump.js", import.meta.url), "utf8").split("\n").slice(0, 60).join("\n");
    expect(header).toContain("javascript:alert(1)");
    expect(header).toMatch(/never build a link/i);
    expect(header).toContain("textContent");
  });

  it("a stone's name may end in a star, like an ornament's: it is still a stone, in every place a stone is", () => {
    const names = ["Zorble Gem (Exaltation)*", "Zorble Gem (Exaltation)* +2", "Zorble Gem (Exaltation) +2*", "Zorble Gem +2 (Exaltation)*"];
    for (const stoneName of names) {
      const r = only(row("General 2", "Zorble Gem +2", 5500), row("General 2-Slot7", stoneName, 5501), row("General 2-Slot8", "Zorble Gem (Exaltation)", 5500));
      expect(r.errors, stoneName).toEqual([]);
      expect(r.rows.find((x) => x.line === 3), stoneName).toMatchObject({ stone: true, tier: 0, name: "Zorble Gem (Exaltation)*", socket: { index: 7, kind: "Focus" } });
      expect(r.owned.has(5501), stoneName).toBe(false);
      expect([...r.owned.keys()], stoneName).toEqual([5500]);
      // a tier after or before the marker is said, a plain starred stone is not
      expect(r.warnings.filter((w) => w.startsWith("Line 3")), stoneName).toEqual(stoneName === names[0] ? [] : ["Line 3: a stone with a tier; the tier is ignored."]);
      expect(problemsIn(r), stoneName).toEqual([]);
    }
    // loose in the key ring, and in a worn slot
    const loose = parse(dump([empty("Head")], [keyRow("Augmentation", "Zorble Gem (Exaltation)*", 5501), keyRow("Equipment", "Plain Cap", 5502)]));
    expect(loose.rows.find((x) => x.line === 5)).toMatchObject({ stone: true, name: "Zorble Gem (Exaltation)*" });
    expect([...loose.owned.keys()]).toEqual([5502]);
    const worn = only(row("Head", "Zorble Gem (Exaltation)*", 5501), row("Neck", "Plain Cap", 6));
    expect(worn.worn.has("HEAD")).toBe(false);
    expect(worn.warnings.filter((w) => w.startsWith("Line 2"))).toEqual(["Line 2: a stone or ornament in a worn slot is ignored."]);
    // a star on its own is part of the name of an ordinary item, and "(Exaltation)*" without the space is no marker
    expect(nameOf("Zorble Gem*")).toMatchObject({ stone: false, name: "Zorble Gem*" });
    expect(nameOf("(Exaltation)*")).toMatchObject({ stone: false });
    expect(nameOf("Zorble Gem(Exaltation)*")).toMatchObject({ stone: false });
  });

  it("ornament rows are recognised by name and never owned", () => {
    const r = only(row("Head", "Plain Hood +1", 4301), row("Head-Slot1", "Gilded Frill (Ornamentation)", 8801), row("Head-Slot2", "Gilded Frill (Ornamentation)*", 8802), row("Head-Slot7", "Plain Pebble", 5));
    expect(r.errors).toEqual([]);
    expect(r.rows.filter((x) => x.ornament).map((x) => x.line)).toEqual([3, 4]);
    expect(r.rows.find((x) => x.line === 3).socket).toEqual({ index: 1, kind: "Ornament" });
    expect(r.owned.has(8801) || r.owned.has(8802) || r.owned.has(5)).toBe(false);
    expect(r.warnings.filter((w) => w.startsWith("Line"))).toEqual([]);
  });

  it("the same name with two IDs is two items; one ID with two names is a warning, both kept", () => {
    const two = only(row("Bank2", "Glimmer Shards", 55001), row("Bank3", "Glimmer Shards", 55002));
    expect([...two.owned.keys()]).toEqual([55001, 55002]);
    expect(two.warnings.filter((w) => w.startsWith("Line"))).toEqual([]);
    const clash = only(row("General 5", "Alpha Cap", 4242), row("Bank1", "Beta Cap", 4242));
    expect(clash.errors).toEqual([]);
    expect(clash.warnings.filter((w) => w.startsWith("Line"))).toEqual(["Line 3: this item ID was already used on line 2 for a different name."]);
    expect(clash.owned.get(4242).map((e) => e.name)).toEqual(["Alpha Cap", "Beta Cap"]);
    // the same name at different tiers is one item
    expect(only(row("General 5", "Alpha Cap +2", 4242), row("Bank1", "Alpha Cap", 4242)).warnings.filter((w) => w.startsWith("Line"))).toEqual([]);
  });

  it("copies in several places accumulate; they never overwrite each other", () => {
    const r = only(row("General 3", "Water Flask", 13001, 20), row("Bank4", "Water Flask", 13001, 20), row("Bank5", "Water Flask", 13001, 7));
    expect(r.owned.get(13001).map((e) => [e.tier, e.count, e.location])).toEqual([[0, 20, "General 3"], [0, 20, "Bank4"], [0, 7, "Bank5"]]);
    expect(r.owned.get(13001).reduce((n, e) => n + e.count, 0)).toBe(47);
  });

  it("an item and its starred twin stay two items with different names", () => {
    const r = only(row("General 1", "Wicker Basket", 17005, 1, 4), row("General 2", "Wicker Basket*", 32601, 1, 4));
    expect(r.rows.map((x) => x.name)).toEqual(["Wicker Basket", "Wicker Basket*"]);
    expect([...r.owned.keys()]).toEqual([17005, 32601]);
  });
});

describe("what the output says", () => {
  it("states only fixed text and numbers: no file content in any message", () => {
    const token = "ZQXVMARK";
    const bad = [
      withLine(SMALL, 1, `${token} ${HEADER}`),
      withLine(SMALL, 10, `Neck\t${token}<\t410006\t1\t10`),
      withLine(SMALL, 10, `${token}\tAshen Torque\t410006\t1\t10`),
      withLine(SMALL, 10, `Neck\tAshen Torque\t${token}\t1\t10`),
      withLine(SMALL, 10, `Neck\tAshen Torque\t410006\t1\t10\t${token}`),
      withLine(SMALL, 10, `Neck-Slot1\t${token}\t410006\t1\t10`),
      withLine(SMALL, 52, `${token}\tName\tID\t`),
      withLine(SMALL, 54, `${token}\tSpare Quillcap\t450002`),
      withLine(SMALL, 54, `Equipment\t${token}!<\t450002`),
      withLine(SMALL, 10, `Neck\tAshen Torque\t410006\t1\t10 ${token}`),
    ];
    for (const text of bad) {
      const r = parse(text);
      expect(JSON.stringify([r.errors, r.warnings]), text).not.toContain(token);
      expect(problemsIn(r), text).toEqual([]);
    }
  });

  it("lists at most 100 warnings and says how many more there were", () => {
    const extra = Array.from({ length: 150 }, (_, i) => row("Bank0", "Plain Hood", 1 + i));
    const r = parse(insertAt(SMALL, 51, ...extra));
    expect(r.errors).toEqual([]);
    expect(r.warnings).toHaveLength(101);
    expect(r.warnings[0]).toMatch(/^Line 51 was skipped/);
    expect(r.warnings[100]).toBe("50 more warnings are not listed.");
  });
});

describe("slots and code hygiene", () => {
  it("SOLVER_SLOT_IDS is the Python kit order: the same groups, pairs numbered", () => {
    const py = readFileSync(new URL("../pipeline/trioforge/model/items.py", import.meta.url), "utf8");
    const block = py.slice(py.indexOf("SLOT_GROUPS:"), py.indexOf("SLOT_INSTANCES:"));
    const groups = [...block.matchAll(/\("([A-Z]+)", (\d)\)/g)].map((m) => [m[1], Number(m[2])]);
    const expected = groups.flatMap(([g, n]) => (n === 1 ? [g] : Array.from({ length: n }, (_, i) => `${g}${i + 1}`)));
    expect(expected).toHaveLength(22);
    expect(SOLVER_SLOT_IDS).toEqual(expected);
    expect(Object.isFrozen(SOLVER_SLOT_IDS)).toBe(true);
  });

  it("states the limits", () => {
    expect(LIMITS).toMatchObject({ maxBytes: 1048576, maxLines: 20000, maxLineLength: 256, maxDepth: 3, maxId: 2147483647, maxCount: 99999, maxSlots: 80 });
    expect(Object.isFrozen(LIMITS)).toBe(true);
  });

  it("the sources reach for no document, window, URL, storage or network: nothing can be made into a link", () => {
    for (const name of ["dump.js", "match.js"]) {
      const src = readFileSync(new URL(`../pipeline/trioforge/site/static/input/${name}`, import.meta.url), "utf8");
      const code = src.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
      for (const word of ["URL", "URLSearchParams", "href", "document", "window", "globalThis", "fetch", "XMLHttpRequest", "navigator", "localStorage", "sessionStorage", "indexedDB", "postMessage", "setAttribute", "WebSocket", "Worker"]) {
        expect(code, `${name} must not use ${word}`).not.toMatch(new RegExp(`\\b${word}\\b`));
      }
    }
  });

  it("the sources use no innerHTML, eval, Function, string timers or regular expressions", () => {
    for (const name of ["dump.js", "match.js"]) {
      const src = readFileSync(new URL(`../pipeline/trioforge/site/static/input/${name}`, import.meta.url), "utf8");
      const code = src.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
      for (const banned of [/innerHTML/, /outerHTML/, /insertAdjacentHTML/, /document\.write/, /\beval\s*\(/, /new\s+Function/, /\bFunction\s*\(/, /setTimeout\s*\(\s*["'`]/, /setInterval\s*\(\s*["'`]/, /\bimport\s*\(/, /new\s+RegExp/, /\bRegExp\b/, /\.(test|exec|match|matchAll|search)\s*\(/, /\.(replace|replaceAll|split)\s*\(\s*\//, /=\s*\/[^/*\s][^/\n]*\/[gimsuy]*\s*[;,)]/, /\bwith\s*\(/, /__proto__/]) {
        expect(code, `${name} must not contain ${banned}`).not.toMatch(banned);
      }
    }
  });
});
