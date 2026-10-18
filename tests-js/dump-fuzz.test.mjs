// Fuzzing the dump parser: random bytes, mutations of a valid dump, random lines from a hostile grammar, and
// random VALID dumps generated from a model and read back exactly. A fixed seed makes every run the same.
import { describe, expect, it } from "vitest";
import { ERRORS, parseDump, parseDumpBytes } from "../pipeline/trioforge/site/static/input/dump.js";
import { HEADER, KEYRING_HEADER, bytes, empty, file, fixture, keyRow, problemsIn, row, utf16 } from "./dump-helpers.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const ints = (rand) => (n) => Math.floor(rand() * n);

const SMALL = fixture("synthetic-small");
const FULL = fixture("synthetic-full");
const SMALL_BYTES = bytes(SMALL);

const OBJECT_PROTOTYPE_KEYS = Object.getOwnPropertyNames(Object.prototype).sort().join();
const never = (r, what) => {
  const problems = problemsIn(r);
  if (problems.length) throw new Error(`${what}: ${problems.slice(0, 3).join("; ")}`);
  if (r.errors[0] === ERRORS.internal) throw new Error(`${what}: the parser fell back to its internal error`);
};

function mutate(rand, source) {
  const pick = ints(rand);
  const a = Array.from(source);
  const rounds = 1 + pick(4);
  for (let k = 0; k < rounds && a.length > 0; k++) {
    const at = pick(a.length);
    switch (pick(11)) {
      case 0: a[at] ^= 1 << pick(8); break;
      case 1: a[at] = pick(256); break;
      case 2: a.splice(at, 1 + pick(20)); break;
      case 3: a.splice(at, 0, ...Array.from({ length: 1 + pick(20) }, () => pick(256))); break;
      case 4: a.splice(pick(a.length), 0, ...a.slice(at, at + 10 + pick(70))); break; // repeat a stretch
      case 5: a.length = at; break; // cut the file short
      case 6: a.splice(at, 0, ...[[13], [10], [13, 10], [9], [9, 9]][pick(5)]); break;
      case 7: for (let i = at; i < Math.min(a.length, at + 1 + pick(12)); i++) a[i] = 57; break; // a run of nines
      case 8: { const b = pick(a.length); [a[at], a[b]] = [a[b], a[at]]; break; }
      case 9: a.splice(at, 0, ...bytes("-Slot" + (1 + pick(12)))); break;
      default: a.splice(at, 0, pick(2) ? 128 + pick(128) : pick(32)); break;
    }
  }
  return Uint8Array.from(a);
}

const ROOTS = ["Head", "Ear", "Neck", "Wrist", "Fingers", "Any Slot", "Ammo", "Primary", "General 1", "General 12", "General 13", "Bank1", "Bank24", "Bank25", "SharedBank6", "SharedBank7", "Held", "Equipment", "Foo", "__proto__", ""];
const NAMES = ["Empty", "Plain Cap", "Plain Cap +3", "Plain Cap* +2", "Plain Cap +3*", "Zed (Exaltation)", "Zed (Exaltation) +1", "constructor", "<b>", "Plain Cap (Ornamentation)", "A".repeat(100), "", " x", "x ", "+7", "Plain +0"];
const NUMS = ["0", "1", "10", "80", "81", "99999", "100000", "2147483647", "2147483648", "00007", "-1", "1e3", "", "x", "12345678901"];

function grammarText(rand) {
  const pick = ints(rand);
  const of = (list) => list[pick(list.length)];
  const eol = () => of(["\r\n", "\n", "\r", "\r\n"]);
  let out = rand() < 0.9 ? HEADER + eol() : of(NAMES) + eol();
  const lines = 1 + pick(40);
  for (let i = 0; i < lines; i++) {
    const r = rand();
    if (r < 0.05) out += eol();
    else if (r < 0.1) out += KEYRING_HEADER + eol();
    else if (r < 0.2) out += [of(["Equipment", "Activated", "Augmentation", "Mount", "Foo"]), of(NAMES), of(NUMS)].join("\t") + eol();
    else {
      let loc = of(ROOTS);
      for (let d = pick(5); d > 0; d--) loc += "-Slot" + of(["0", "1", "2", "7", "8", "10", "99", "100", "01", "x", ""]);
      out += [loc, of(NAMES), of(NUMS), of(NUMS), of(NUMS)].join("\t") + (pick(20) === 0 ? "\t" + of(NUMS) : "") + eol();
    }
  }
  return pick(8) === 0 ? out.slice(0, pick(out.length + 1)) : out;
}

/** A random byte string; a third of them start like a real file so that the deeper checks are reached. */
function randomBytes(pick) {
  const length = pick(8) === 0 ? 0 : pick(2049);
  const data = new Uint8Array(length);
  for (let k = 0; k < length; k++) data[k] = pick(256);
  if (pick(3) === 0 && length > 40) data.set(bytes(HEADER + "\r\n"), 0);
  if (pick(12) === 0 && length > 3) data.set([[0xff, 0xfe], [0xfe, 0xff], [0xef, 0xbb, 0xbf], [0x50, 0x4b, 0x03, 0x04]][pick(4)], 0);
  return data;
}

describe("fuzzing", { timeout: 60000 }, () => {
  it("10,000 random byte strings: no exception, a well-formed result each time", () => {
    const pick = ints(mulberry32(1));
    const watch = stopwatch();
    for (let i = 0; i < 10000; i++) never(parseDumpBytes(randomBytes(pick)), `random ${i}`);
    const took = watch.stop();
    console.info(`fuzz: 10,000 random byte strings in ${took.ms.toFixed(0)} ms (with the checks of every result)`);
    expectWithin(took, 6000, "10,000 random byte strings, with the checks of every result");
  });

  it("10,000 random strings and 10,000 mutations are parsed in under 2 s together", () => {
    const pick = ints(mulberry32(1));
    const rand = mulberry32(2);
    const inputs = [];
    for (let i = 0; i < 10000; i++) inputs.push(randomBytes(pick));
    for (let i = 0; i < 10000; i++) inputs.push(mutate(rand, SMALL_BYTES));
    const watch = stopwatch();
    let refused = 0;
    for (const data of inputs) if (parseDumpBytes(data).errors.length) refused++;
    const took = watch.stop();
    console.info(`fuzz: parsing the 20,000 inputs alone took ${took.ms.toFixed(0)} ms (${refused} refused)`);
    expectWithin(took, 2000, "parsing 10,000 random strings and 10,000 mutations");
  });

  it("10,000 mutations of a valid dump: no exception, a well-formed result each time", () => {
    const rand = mulberry32(2);
    const watch = stopwatch();
    let accepted = 0;
    let rejected = 0;
    for (let i = 0; i < 10000; i++) {
      const r = parseDumpBytes(mutate(rand, SMALL_BYTES));
      never(r, `mutation ${i}`);
      if (r.errors.length) rejected++;
      else accepted++;
    }
    const took = watch.stop();
    console.info(`fuzz: 10,000 mutations in ${took.ms.toFixed(0)} ms (${accepted} read, ${rejected} refused)`);
    expectWithin(took, 6000, "10,000 mutations of a valid dump, with the checks of every result");
    // the mutations are small, so both outcomes must be common: the suite is not just feeding the first check
    expect(accepted).toBeGreaterThan(1000);
    expect(rejected).toBeGreaterThan(1000);
  });

  it("5,000 mutations of the full dump, which has bags, sockets and a key ring", () => {
    const rand = mulberry32(3);
    const source = bytes(FULL);
    const watch = stopwatch();
    for (let i = 0; i < 5000; i++) never(parseDumpBytes(mutate(rand, source)), `full mutation ${i}`);
    const took = watch.stop();
    console.info(`fuzz: 5,000 mutations of the full dump in ${took.ms.toFixed(0)} ms`);
    expectWithin(took, 8000, "5,000 mutations of the full dump, with the checks of every result");
  });

  it("5,000 random lines from a hostile grammar: roots, positions, names, numbers", () => {
    const rand = mulberry32(4);
    const watch = stopwatch();
    for (let i = 0; i < 5000; i++) {
      const text = grammarText(rand);
      never(parseDumpBytes(bytes(text)), `grammar ${i}`);
      if (i % 25 === 0) {
        const again = parseDumpBytes(bytes(text));
        expect(again).toEqual(parseDumpBytes(bytes(text))); // the same text always reads the same
      }
    }
    expectWithin(watch.stop(), 6000, "5,000 random lines from a hostile grammar");
  });

  it("is deterministic and leaves the global objects as it found them", () => {
    const rand = mulberry32(5);
    for (let i = 0; i < 300; i++) {
      const data = mutate(rand, SMALL_BYTES);
      expect(parseDumpBytes(data)).toEqual(parseDumpBytes(data));
    }
    expect(Object.getOwnPropertyNames(Object.prototype).sort().join()).toBe(OBJECT_PROTOTYPE_KEYS);
    expect(({}).polluted).toBeUndefined();
  });

  it("reads random bytes through the File path without ever rejecting", async () => {
    const rand = mulberry32(6);
    for (let i = 0; i < 400; i++) {
      const r = await parseDump(file(mutate(rand, SMALL_BYTES)));
      never(r, `file ${i}`);
    }
  });
});

// ------------------------------------------------------------------------------------------------------------
// A model of a valid dump. It writes the text and, as it goes, the answer the parser has to give.

const WORN_ORDER = [
  ["Any Slot", "ANY1"], ["Ear", "EAR1"], ["Head", "HEAD"], ["Face", "FACE"], ["Ear", "EAR2"], ["Neck", "NECK"], ["Shoulders", "SHOULDERS"],
  ["Arms", "ARMS"], ["Back", "BACK"], ["Wrist", "WRIST1"], ["Wrist", "WRIST2"], ["Range", "RANGE"], ["Hands", "HANDS"], ["Primary", "PRIMARY"],
  ["Secondary", "SECONDARY"], ["Fingers", "FINGER1"], ["Fingers", "FINGER2"], ["Chest", "CHEST"], ["Legs", "LEGS"], ["Feet", "FEET"],
  ["Waist", "WAIST"], ["Any Slot", "ANY2"], ["Ammo", "AMMO"],
];

function modelDump(seed) {
  const rand = mulberry32(seed);
  const pick = ints(rand);
  const items = Array.from({ length: 40 }, (_, i) => ({ id: 800000 + i, base: `Gizmo ${i}`, star: pick(5) === 0 }));
  const bags = Array.from({ length: 8 }, (_, i) => ({ id: 700000 + i, base: `Sack ${i}`, capacity: [4, 6, 8, 10, 10, 12, 10, 4][i] }));
  const stones = Array.from({ length: 6 }, (_, i) => ({ id: 900000 + i, base: `Spark ${i}` }));
  const text = [HEADER];
  const owned = []; // [id, tier, count, location], in file order
  const worn = {};
  let rows = 0;
  let containers = 0;
  const stats = { tenSlotBag: 0, nestedBag: 0, depth3: 0, star: 0, keyRing: 0, cursor: 0 };

  const label = (it, tier) => `${it.base}${it.star ? "*" : ""}${tier ? ` +${tier}` : ""}`;
  const emitSockets = (loc, pathLength, tier) => {
    if (tier === 0 || pathLength > 2) return;
    for (let s = 7; s <= 6 + Math.min(tier, 4); s++) {
      if (pick(2)) text.push(empty(`${loc}-Slot${s}`));
      else {
        const stone = stones[pick(stones.length)];
        text.push(row(`${loc}-Slot${s}`, `${stone.base} (Exaltation)`, stone.id));
        rows++;
      }
    }
  };
  const emitItem = (loc, pathLength, place, wornSlot) => {
    const item = items[pick(items.length)];
    const tier = pick(11);
    const count = wornSlot === "AMMO" ? 1 + pick(50) : place !== "worn" && pick(7) === 0 ? 2 + pick(40) : 1;
    text.push(row(loc, label(item, tier), item.id, count));
    rows++;
    if (pathLength === 3) stats.depth3++;
    if (item.star) stats.star++;
    if (loc === "Held") stats.cursor++;
    owned.push([item.id, tier, count, loc, place]);
    if (wornSlot) worn[wornSlot] = `${item.id}|${tier}`;
    emitSockets(loc, pathLength, tier);
  };
  const emitBag = (loc, pathLength, place) => {
    const bag = bags[pick(bags.length)];
    text.push(row(loc, bag.base, bag.id, 1, bag.capacity));
    rows++;
    containers++;
    if (bag.capacity === 10) stats.tenSlotBag++;
    if (pathLength > 0) stats.nestedBag++;
    owned.push([bag.id, 0, 1, loc, place]);
    for (let pos = 1; pos <= bag.capacity; pos++) {
      const childLoc = `${loc}-Slot${pos}`;
      const r = pick(100);
      if (r < 50) text.push(empty(childLoc));
      else if (r < 88 || pathLength + 1 > 2) emitItem(childLoc, pathLength + 1, place, null);
      else emitBag(childLoc, pathLength + 1, place);
    }
  };

  for (const [root, slot] of WORN_ORDER) {
    if (pick(10) < 4) emitItem(root, 0, "worn", slot);
    else text.push(empty(root));
  }
  for (let g = 1; g <= 12; g++) {
    const r = pick(10);
    if (r < 4) text.push(empty(`General ${g}`));
    else if (r < 6) emitItem(`General ${g}`, 0, "bag", null);
    else emitBag(`General ${g}`, 0, "bag");
  }
  if (pick(3) === 0) emitItem("Held", 0, "cursor", null);
  else text.push(empty("Held"));
  for (let b = 1; b <= 24; b++) {
    const r = pick(10);
    if (r < 6) text.push(empty(`Bank${b}`));
    else if (r < 8) emitItem(`Bank${b}`, 0, "bank", null);
    else emitBag(`Bank${b}`, 0, "bank");
  }
  for (let s = 1; s <= 6; s++) {
    if (pick(3)) text.push(empty(`SharedBank${s}`));
    else if (pick(2)) emitItem(`SharedBank${s}`, 0, "sharedbank", null);
    else emitBag(`SharedBank${s}`, 0, "sharedbank");
  }
  text.push("", KEYRING_HEADER);
  for (let k = pick(25); k > 0; k--) {
    const type = ["Equipment", "Activated", "Augmentation"][pick(3)];
    if (type === "Augmentation") {
      const stone = stones[pick(stones.length)];
      text.push(keyRow(type, `${stone.base} (Exaltation)`, stone.id));
      rows++;
    } else {
      const item = items[pick(items.length)];
      const tier = pick(11);
      text.push(keyRow(type, label(item, tier), item.id));
      rows++;
      stats.keyRing++;
      owned.push([item.id, tier, 1, type, "keyring"]);
    }
  }
  return { lines: text, owned, worn, rows, containers, stats };
}

const reencodings = {
  "CRLF": (t) => bytes(t),
  "LF": (t) => bytes(t.split("\r\n").join("\n")),
  "CR, no final line end": (t) => bytes(t.split("\r\n").join("\r").replace(/\r$/, "")),
  "UTF-8 BOM and two blank lines at the end": (t) => new Uint8Array([0xef, 0xbb, 0xbf, ...bytes(t + "\r\n\r\n")]),
  "UTF-16LE": (t) => utf16(t),
  "UTF-16BE": (t) => utf16(t, { big: true }),
};

/** A cheap, exact signature of what a parse returned, to compare six encodings without a deep equality each time. */
const signature = (r) => JSON.stringify([r.rows, [...r.owned], [...r.worn.keys()], r.errors]);

describe("random valid dumps are read back exactly", () => {
  it("300 model dumps: owned items, copies, worn slots, containers and warnings, in six encodings", { timeout: 120000 }, () => {
    let totalRows = 0;
    for (let seed = 1; seed <= 300; seed++) {
      const model = modelDump(seed);
      const text = model.lines.join("\r\n") + "\r\n";
      let firstSignature = null;
      for (const [label, encode] of Object.entries(reencodings)) {
        const r = parseDumpBytes(encode(text));
        const where = `seed ${seed}, ${label}`;
        never(r, where);
        if (firstSignature === null) {
          // the first encoding is compared with the model in full; the others have to equal it
          expect(r.errors, where).toEqual([]);
          expect(r.warnings, where).toEqual([]);
          expect(r.rows, where).toHaveLength(model.rows);
          expect(r.rows.filter((x) => x.container), where).toHaveLength(model.containers);
          const idOfLine = new Map([...r.owned].flatMap(([id, list]) => list.map((e) => [e.line, id])));
          const got = [...r.owned.values()].flat().sort((a, b) => a.line - b.line).map((e) => [idOfLine.get(e.line), e.tier, e.count, e.location, e.place]);
          expect(got, where).toEqual(model.owned);
          expect(Object.fromEntries([...r.worn].map(([slot, x]) => [slot, `${x.id}|${x.tier}`])), where).toEqual(model.worn);
          firstSignature = signature(r);
        } else {
          if (signature(r) !== firstSignature) throw new Error(`${where}: the parse differs from the first encoding`);
          // the same warnings, except that a last line with no line end says so
          const lastLine = `Line ${model.lines.length} has no line end, so the last line may be cut off; re-run /outputfile inventory.`;
          expect(r.warnings, where).toEqual(label === "CR, no final line end" ? [lastLine] : []);
        }
      }
      totalRows += model.rows;
    }
    console.info(`model dumps: 300 files, ${totalRows} rows read back exactly in six encodings each`);
    expect(totalRows).toBeGreaterThan(20000);
  });

  it("the model really exercises bags of 10 positions, nested bags, depth-3 rows, stars, the cursor and the key ring", () => {
    const total = { tenSlotBag: 0, nestedBag: 0, depth3: 0, star: 0, keyRing: 0, cursor: 0 };
    for (let seed = 1; seed <= 300; seed++) for (const [k, v] of Object.entries(modelDump(seed).stats)) total[k] += v;
    for (const [what, n] of Object.entries(total)) expect(n, what).toBeGreaterThan(50);
  });
});

// ------------------------------------------------------------------------------------------------------------
// Damage to the model's valid dumps that must not change what the dump holds.

/** What a parse says is owned, in file order, as the model writes it: [id, tier, count, location, place]. */
function ownedOf(r) {
  const idOfLine = new Map([...r.owned].flatMap(([id, list]) => list.map((e) => [e.line, id])));
  return [...r.owned.values()].flat().sort((a, b) => a.line - b.line).map((e) => [idOfLine.get(e.line), e.tier, e.count, e.location, e.place]);
}
const parseLines = (lines) => parseDumpBytes(bytes(lines.join("\r\n") + "\r\n"));

/** Where the model's lines name things: location -> name, for the rows that are not Empty. */
function namesAt(lines) {
  const names = new Map();
  for (const line of lines.slice(1)) {
    const f = line.split("\t");
    if (f.length === 5 && f[1] !== "Empty") names.set(f[0], f[1]);
  }
  return names;
}
/** The indexes of the Empty rows that are positions of a bag (the model names its bags "Sack n" and its items "Gizmo n"). */
function bagPositionLines(lines) {
  const names = namesAt(lines);
  const found = [];
  lines.forEach((line, i) => {
    const f = line.split("\t");
    if (f.length !== 5 || f[1] !== "Empty") return;
    const cut = f[0].lastIndexOf("-Slot");
    if (cut > 0 && (names.get(f[0].slice(0, cut)) ?? "").startsWith("Sack ")) found.push(i);
  });
  return found;
}
/** The indexes of the rows at position 7 of an item that is at most one level down, so that a bag can be put there. */
function socketSevenLines(lines) {
  const names = namesAt(lines);
  const found = [];
  lines.forEach((line, i) => {
    const f = line.split("\t");
    if (f.length !== 5 || !f[0].endsWith("-Slot7")) return;
    const parent = f[0].slice(0, f[0].lastIndexOf("-Slot"));
    if ((names.get(parent) ?? "").startsWith("Gizmo ") && parent.split("-Slot").length <= 2) found.push(i);
  });
  return found;
}

describe("damage to valid dumps that must not change what they hold", () => {
  it("a bag that loses position rows is still a bag, and keeps everything it holds", () => {
    let damaged = 0;
    for (let seed = 1; seed <= 300; seed++) {
      const model = modelDump(seed);
      const candidates = bagPositionLines(model.lines);
      if (candidates.length === 0) continue;
      const pick = ints(mulberry32(seed * 7));
      const drop = new Set();
      for (let k = 1 + pick(3); k > 0; k--) drop.add(candidates[pick(candidates.length)]);
      const r = parseLines(model.lines.filter((_, i) => !drop.has(i)));
      const where = `seed ${seed}, rows ${[...drop]}`;
      never(r, where);
      expect(r.errors, where).toEqual([]);
      expect(ownedOf(r), where).toEqual(model.owned);
      expect(r.rows.filter((x) => x.container), where).toHaveLength(model.containers);
      expect(r.warnings.length, where).toBeGreaterThan(0);
      expect(r.warnings.every((w) => w.includes("positions listed do not match")), `${where}: ${JSON.stringify(r.warnings)}`).toBe(true);
      damaged += drop.size;
    }
    expect(damaged).toBeGreaterThan(300);
  });

  it("a stray byte after the location of a bag position keeps that position: the bag stays whole", () => {
    let damaged = 0;
    for (let seed = 1; seed <= 300; seed++) {
      const model = modelDump(seed);
      const candidates = bagPositionLines(model.lines);
      if (candidates.length === 0) continue;
      const pick = ints(mulberry32(seed * 11));
      const hit = new Set();
      for (let k = 1 + pick(3); k > 0; k--) hit.add(candidates[pick(candidates.length)]);
      const lines = model.lines.map((line, i) => (hit.has(i) ? line.replace("\t", "\xa0\t") : line));
      const r = parseLines(lines);
      const where = `seed ${seed}, rows ${[...hit]}`;
      never(r, where);
      expect(r.errors, where).toEqual([]);
      expect(ownedOf(r), where).toEqual(model.owned);
      expect(r.rows.filter((x) => x.container), where).toHaveLength(model.containers);
      expect(r.warnings, where).toEqual([...hit].sort((a, b) => a - b).map((i) => `Line ${i + 1} was skipped: it has a character that /outputfile never writes.`));
      damaged += hit.size;
    }
    expect(damaged).toBeGreaterThan(300);
  });

  it("a bag put into a socket, with things in it, changes nothing that is owned", () => {
    let planted = 0;
    for (let seed = 1; seed <= 300; seed++) {
      const model = modelDump(seed);
      const candidates = socketSevenLines(model.lines);
      if (candidates.length === 0) continue;
      const at = candidates[ints(mulberry32(seed * 13))(candidates.length)];
      const location = model.lines[at].split("\t")[0];
      const lines = [
        ...model.lines.slice(0, at),
        row(location, "Qzxv Sack", 777777, 1, 2),
        row(`${location}-Slot1`, "Qzxv Ring", 777778),
        empty(`${location}-Slot2`),
        ...model.lines.slice(at + 1),
      ];
      const r = parseLines(lines);
      const where = `seed ${seed}, ${location}`;
      never(r, where);
      expect(r.errors, where).toEqual([]);
      expect(ownedOf(r), where).toEqual(model.owned);
      expect(r.rows.filter((x) => x.container), where).toHaveLength(model.containers);
      expect(r.warnings, where).toEqual([]);
      planted++;
    }
    expect(planted).toBeGreaterThan(100);
  });
});
