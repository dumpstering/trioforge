// Tests for matching dump rows to the item table. The table here is small and invented; the real one comes from
// the Python export.
import { describe, expect, it } from "vitest";
import { parseDumpBytes } from "../pipeline/trioforge/site/static/input/dump.js";
import { matchItems } from "../pipeline/trioforge/site/static/input/match.js";
import { bytes, fixture } from "./dump-helpers.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

const CURLY = String.fromCharCode(0x2019);

/** An item table entry: the shape the export has. */
const item = (pageid, matchName, extra = {}) => ({ key: `w${pageid}`, match_name: matchName, aliases: [], owned_only: false, name: matchName, ...extra });
/** The part of a parsed row that matching reads. */
const R = (name, extra = {}) => ({ name, tier: 0, count: 1, id: 1, stone: false, ornament: false, socket: null, ...extra });

const CATALOG = [
  item(101, "Tarnished Quillcap"),
  item(102, "Moth-Eaten Rag*"),
  item(103, "Moth-Eaten Rag"),
  item(104, "Tinker's Loupe"),
  item(105, "Wanderer`s Cloak"),
  item(106, `Warden${CURLY}s Torc`),
  item(107, "Worn Totem"),
  item(108, "A Worn Totem"),
  item(109, "The Ring of Valor"),
  item(110, "Whittled Spoon", { aliases: ["Whittled Spoon (Weapon)", "Whittled Ladle"] }),
  item(111, "Retired Sentinel Helm", { owned_only: true }),
  item(112, "Wicker Basket"),
  item(113, "Wicker Basket*"),
  item(114, "Whittled Ladle"),
  ...Array.from({ length: 9 }, (_, i) => item(201 + i, "Glimmer Shards", { name: `Glimmer Shards (${i + 1})` })),
];

const one = (name, catalog = CATALOG) => {
  const row = R(name);
  const m = matchItems([row], catalog);
  expect(m.matched.length + m.ambiguous.length + m.unknown.length).toBe(1);
  return { ...m, row };
};

describe("matching by name, stage by stage", () => {
  it("stage 1: the exact match_name, case and punctuation as written", () => {
    const m = one("Tarnished Quillcap");
    expect(m.matched).toEqual([{ row: m.row, key: "w101", ownedOnly: false, stage: 1 }]);
    expect(m.ambiguous).toEqual([]);
    expect(m.unknown).toEqual([]);
    expect(one("Tinker's Loupe").matched[0]).toMatchObject({ key: "w104", stage: 1 });
    expect(one("Wanderer`s Cloak").matched[0]).toMatchObject({ key: "w105", stage: 1 });
  });

  it("the entry carries the very row object it was given", () => {
    const row = R("Tarnished Quillcap");
    expect(matchItems([row], CATALOG).matched[0].row).toBe(row);
  });

  it("the star is part of the name at every stage", () => {
    expect(one("Moth-Eaten Rag*").matched[0]).toMatchObject({ key: "w102", stage: 1 });
    expect(one("Moth-Eaten Rag").matched[0]).toMatchObject({ key: "w103", stage: 1 });
    expect(one("Wicker Basket").matched[0].key).toBe("w112");
    expect(one("Wicker Basket*").matched[0].key).toBe("w113");
    // with only the starred item in the table, the plain name finds nothing, and the reverse
    expect(one("Moth-Eaten Rag", [item(102, "Moth-Eaten Rag*")]).unknown).toHaveLength(1);
    expect(one("Moth-Eaten Rag*", [item(103, "Moth-Eaten Rag")]).unknown).toHaveLength(1);
    expect(one("the moth-eaten rag", [item(102, "Moth-Eaten Rag*")]).unknown).toHaveLength(1);
    expect(one("Moth-Eaten Rag**", [item(102, "Moth-Eaten Rag*")]).unknown).toHaveLength(1);
  });

  it("stage 2: quotation marks do not matter (straight, backtick, curly, and the mis-decoded one)", () => {
    for (const q of ["'", "`", String.fromCharCode(0x2018), CURLY, String.fromCharCode(0x201b), String.fromCharCode(0x2032), String.fromCharCode(0xb4), String.fromCharCode(0xfffd)]) {
      const loupe = one(`Tinker${q}s Loupe`);
      expect(loupe.matched[0], `Tinker ${q.charCodeAt(0)}`).toMatchObject({ key: "w104", stage: q === "'" ? 1 : 2 });
      const torc = one(`Warden${q}s Torc`);
      expect(torc.matched[0], `Warden ${q.charCodeAt(0)}`).toMatchObject({ key: "w106", stage: q === CURLY ? 1 : 2 });
    }
    expect(one("Wanderer's Cloak").matched[0]).toMatchObject({ key: "w105", stage: 2 });
    // a quotation mark is not an apostrophe that may be dropped
    expect(one("Tinkers Loupe").unknown).toHaveLength(1);
    expect(one("Tinker''s Loupe").unknown).toHaveLength(1);
  });

  it("stage 3: the aliases of an item, such as a wiki disambiguation title", () => {
    expect(one("Whittled Spoon (Weapon)").matched[0]).toMatchObject({ key: "w110", stage: 3 });
    expect(one("Whittled Spoon").matched[0]).toMatchObject({ key: "w110", stage: 1 });
    // without any other item of that name, the alias is found
    expect(one("Whittled Ladle", CATALOG.filter((x) => x.key !== "w114")).matched[0]).toMatchObject({ key: "w110", stage: 3 });
  });

  it("stages 1 to 3 make one pool of candidates: an exact match_name and an alias of another item are both candidates", () => {
    // w114 has the name as its match_name, w110 has it as an alias: neither may win silently
    const m = one("Whittled Ladle");
    expect(m.matched).toEqual([]);
    expect(m.ambiguous).toEqual([{ row: m.row, keys: ["w110", "w114"], stage: 1 }]);
  });

  it("the review's case: the in-game name is one item's match_name and another's alias", () => {
    const table = [item(901, "Obsidian Shard"), item(902, "Obsidian Shard (Sky)", { aliases: ["Obsidian Shard"] })];
    const m = one("Obsidian Shard", table);
    expect(m.matched).toEqual([]);
    expect(m.ambiguous).toEqual([{ row: m.row, keys: ["w901", "w902"], stage: 1 }]);
    // the wiki title alone is exact for one item only
    expect(one("Obsidian Shard (Sky)", table).matched[0]).toMatchObject({ key: "w902", stage: 1 });
  });

  it("the pool joins the stages: items that differ only in a quotation mark are both candidates for either spelling", () => {
    const table = [item(1, "Tinker's Loupe"), item(2, "Tinker`s Loupe")];
    for (const spelling of ["Tinker's Loupe", "Tinker`s Loupe", `Tinker${CURLY}s Loupe`]) {
      const m = one(spelling, table);
      expect(m.matched, spelling).toEqual([]);
      expect(m.ambiguous.map((a) => a.keys), spelling).toEqual([["w1", "w2"]]);
    }
  });

  it("an item reached at several stages is one candidate, and its stage is the earliest", () => {
    const table = [item(5, "Plain Hood", { aliases: ["Plain Hood", "Plain Hood"] })];
    expect(one("Plain Hood", table).matched[0]).toMatchObject({ key: "w5", stage: 1 });
    expect(one("Plain Hood", [item(5, "Plain Cap", { aliases: ["Plain Hood"] }), item(5, "Plain Hood")]).matched[0]).toMatchObject({ key: "w5", stage: 1 });
    expect(one("Wanderer's Cloak", [item(5, "Wanderer`s Cloak", { aliases: ["Wanderer's Cloak"] })]).matched[0]).toMatchObject({ key: "w5", stage: 2 });
  });

  it("stage 4: a leading A, An or The is ignored on both sides, and case is ignored; it is never a silent match", () => {
    expect(one("The Ring of Valor").matched[0]).toMatchObject({ key: "w109", stage: 1 });
    // a stage-4 hit is always offered, never matched, even when only one item fits
    for (const name of ["Ring of Valor", "A Ring of Valor", "an ring of valor", "the RING of valor"]) {
      const m = one(name);
      expect(m.matched, name).toEqual([]);
      expect(m.ambiguous, name).toEqual([{ row: m.row, keys: ["w109"], stage: 4 }]);
    }
    // an article is a word: letters that merely begin with one are not an article
    expect(one("Anvil of Doom", [item(1, "vil of Doom")]).unknown).toHaveLength(1);
    expect(one("Theory of Valor", [item(1, "ory of Valor")]).unknown).toHaveLength(1);
    // the article goes from the front only
    expect(one("Valor, The Ring", [item(1, "The Ring of Valor")]).unknown).toHaveLength(1);
  });

  it("the review's stage-4 case: a different case or an article never matches silently", () => {
    const table = [item(1, "Lion-Skin Leggings"), item(2, "Torch"), item(3, "Hammer")];
    const rows = ["Lion-skin leggings", "The Torch", "A Hammer", "an hammer", "THE HAMMER"].map((name) => R(name));
    const m = matchItems(rows, table);
    expect(m.matched).toEqual([]);
    expect(m.unknown).toEqual([]);
    expect(m.ambiguous.map((a) => [a.row.name, a.keys, a.stage])).toEqual([
      ["Lion-skin leggings", ["w1"], 4],
      ["The Torch", ["w2"], 4],
      ["A Hammer", ["w3"], 4],
      ["an hammer", ["w3"], 4],
      ["THE HAMMER", ["w3"], 4],
    ]);
  });

  it("stage 4 is tried only when stages 1 to 3 found nothing: an exact name beats the article forms", () => {
    expect(one("Worn Totem").matched[0]).toMatchObject({ key: "w107", stage: 1 });
    expect(one("A Worn Totem").matched[0]).toMatchObject({ key: "w108", stage: 1 });
    // 'The Worn Totem' is neither, and at stage 4 both of them are what it could mean
    const m = one("The Worn Totem");
    expect(m.matched).toEqual([]);
    expect(m.ambiguous).toEqual([{ row: m.row, keys: ["w107", "w108"], stage: 4 }]);
  });

  it("a trailing ', The' is not an article form this matcher reads, so it finds nothing", () => {
    expect(one("Worn Totem, The", [item(1, "The Worn Totem")]).unknown).toHaveLength(1);
  });

  it("nine items with one name are one ambiguous row with nine keys, never merged", () => {
    const m = one("Glimmer Shards");
    expect(m.matched).toEqual([]);
    expect(m.unknown).toEqual([]);
    expect(m.ambiguous).toHaveLength(1);
    expect(m.ambiguous[0].keys).toEqual(["w201", "w202", "w203", "w204", "w205", "w206", "w207", "w208", "w209"]);
    expect(m.ambiguous[0].stage).toBe(1);
    // two rows of that name are two entries, each with the nine
    const two = matchItems([R("Glimmer Shards", { id: 55001 }), R("Glimmer Shards", { id: 55002 })], CATALOG);
    expect(two.ambiguous.map((a) => a.keys.length)).toEqual([9, 9]);
    expect(two.ambiguous.map((a) => a.row.id)).toEqual([55001, 55002]);
  });

  it("hidden items match, flagged owned_only; a hidden and a visible item of one name are ambiguous", () => {
    expect(one("Retired Sentinel Helm").matched).toEqual([expect.objectContaining({ key: "w111", ownedOnly: true, stage: 1 })]);
    expect(one("Tarnished Quillcap").matched[0].ownedOnly).toBe(false);
    const both = one("Plain Hood", [item(1, "Plain Hood"), item(2, "Plain Hood", { owned_only: true })]);
    expect(both.ambiguous[0].keys).toEqual(["w1", "w2"]);
    expect(both.matched).toEqual([]);
  });

  it("unknown names are listed as unknown and nothing else", () => {
    const m = one("Zzz Not In Catalog");
    expect(m.unknown).toEqual([{ row: m.row }]);
    expect(m.matched).toEqual([]);
    expect(m.ambiguous).toEqual([]);
    expect(one("").unknown).toHaveLength(1);
    expect(one("   ").unknown).toHaveLength(1);
  });

  it("the same item reached twice (name and alias, or listed twice) is one candidate, not an ambiguity", () => {
    const twice = one("Plain Hood", [item(7, "Plain Hood", { aliases: ["Plain Hood", "Plain Hood"] })]);
    expect(twice.matched[0]).toMatchObject({ key: "w7", stage: 1 });
    const listedTwice = one("Plain Hood", [item(7, "Plain Hood"), item(7, "Plain Hood")]);
    expect(listedTwice.matched[0].key).toBe("w7");
    const viaAliasOnly = one("Plain Hood", [item(7, "Plain Cap", { aliases: ["Plain Hood", "Plain Hood"] })]);
    expect(viaAliasOnly.matched[0]).toMatchObject({ key: "w7", stage: 3 });
  });
});

describe("what is matched", () => {
  it("skips stones, socket contents and ornaments: they are not gear", () => {
    const rows = [
      R("Tarnished Quillcap"),
      R("Tarnished Quillcap (Exaltation)", { stone: true }),
      R("Tarnished Quillcap", { socket: { index: 7, kind: "Focus" } }),
      R("Tarnished Quillcap", { ornament: true }),
    ];
    const m = matchItems(rows, CATALOG);
    expect(m.matched.map((x) => x.row)).toEqual([rows[0]]);
    expect(m.ambiguous).toEqual([]);
    expect(m.unknown).toEqual([]);
  });

  it("every considered row lands in exactly one of the three lists, in the order given", () => {
    const parsed = parseDumpBytes(bytes(fixture("synthetic-full")));
    const m = matchItems(parsed.rows, [item(410003, "Tarnished Quillcap"), item(410013, "Cobbled Maul"), item(1, "Spare Quillcap")]);
    const ownable = parsed.rows.filter((x) => !x.stone && !x.ornament && x.socket === null);
    expect(ownable).toHaveLength(45);
    const seen = [...m.matched, ...m.ambiguous, ...m.unknown].map((x) => x.row);
    expect(seen).toHaveLength(45);
    expect(new Set(seen).size).toBe(45);
    expect(seen.every((row) => ownable.includes(row))).toBe(true);
    expect(m.matched.map((x) => x.row.line)).toEqual([...m.matched.map((x) => x.row.line)].sort((a, b) => a - b));
    expect(m.matched.map((x) => [x.row.line, x.key])).toEqual([[6, "w410003"], [25, "w410013"], [53, "w410003"], [79, "w410013"], [148, "w1"]]);
  });

  it("never learns anything: the table, the rows and later calls are untouched by a call", () => {
    const snapshot = structuredClone(CATALOG);
    const rows = [R("Zzz Not In Catalog", { id: 999999 }), R("Tarnished Quillcap")];
    const a = matchItems(rows, CATALOG);
    expect(CATALOG).toEqual(snapshot);
    expect(rows[0]).toEqual(R("Zzz Not In Catalog", { id: 999999 }));
    expect(a.unknown).toEqual([{ row: rows[0] }]);
    // a second call, and a call with another table, see no trace of the first
    expect(matchItems(rows, CATALOG)).toEqual(a);
    expect(matchItems(rows, []).unknown).toHaveLength(2);
    expect(matchItems(rows, [item(5, "Zzz Not In Catalog")]).matched[0].key).toBe("w5");
    expect(matchItems(rows, CATALOG)).toEqual(a);
    // a table that is frozen all the way down is enough to work from
    const frozen = structuredClone(CATALOG);
    for (const it of frozen) {
      Object.freeze(it.aliases);
      Object.freeze(it);
    }
    Object.freeze(frozen);
    expect(matchItems(rows, frozen)).toEqual(a);
  });
});

describe("a table that is not what it should be", () => {
  const junk = [null, undefined, 5, "text", true, {}, [], { key: 1 }, { key: "w1" }, { key: "w1", match_name: 5 }, { match_name: "Lost Item" }, { key: "w2", match_name: "Plain Cap", aliases: "nope" }, { key: "w3", match_name: "Plain Cap", aliases: [1, null, {}, "Plain Hood"] }, { key: "w4", match_name: "Plain Cap", aliases: { 0: "Plain Veil" } }];

  it("skips the entries it cannot use and still matches the rest", () => {
    const m = matchItems([R("Plain Cap"), R("Plain Hood"), R("Lost Item"), R("Plain Veil")], [...junk, item(9, "Plain Cap")]);
    // w2, w3, w4 and w9 all have the match_name 'Plain Cap' (the aliases of w4 are not a list, so they are ignored)
    expect(m.ambiguous.map((a) => a.keys)).toEqual([["w2", "w3", "w4", "w9"]]);
    expect(m.matched.map((x) => [x.row.name, x.key])).toEqual([["Plain Hood", "w3"]]);
    expect(m.unknown.map((x) => x.row.name)).toEqual(["Lost Item", "Plain Veil"]);
  });

  it("reads at most 64 aliases of an item, and ignores names and keys that are absurdly long", () => {
    const aliases = Array.from({ length: 100 }, (_, i) => `Alias ${i}`);
    const table = [
      item(1, "Plain Cap", { aliases }),
      item(2, "N".repeat(300)),
      { key: "w".repeat(102), match_name: "Long Key Item", aliases: [], owned_only: false }, // (one past the longest key of an item table, 101)
      item(3, "Plain Hood", { aliases: ["A".repeat(300)] }),
    ];
    expect(one("Alias 63", table).matched[0].key).toBe("w1");
    expect(one("Alias 64", table).unknown).toHaveLength(1);
    expect(one("N".repeat(300), table).unknown).toHaveLength(1);
    expect(one("Long Key Item", table).unknown).toHaveLength(1);
    expect(one("A".repeat(300), table).unknown).toHaveLength(1);
    expect(one("Plain Hood", table).matched[0].key).toBe("w3");
  });

  it("takes a key as long as the item table allows, 101 characters, and ignores one that is longer", () => {
    const longest = "r" + "a" + "b".repeat(99);
    expect(longest).toHaveLength(101);
    const table = [
      { key: longest, match_name: "Deep Pocket Cap", aliases: [], owned_only: false },
      { key: longest + "b", match_name: "Deeper Pocket Cap", aliases: [], owned_only: false },
    ];
    expect(one("Deep Pocket Cap", table).matched.map((m) => m.key)).toEqual([longest]);
    expect(one("Deeper Pocket Cap", table).unknown).toHaveLength(1);
  });

  it("answers every row as unknown when the table is not an array, and nothing for rows that are not rows", () => {
    for (const bad of [null, undefined, 5, "text", {}, { length: 3 }, new Map()]) {
      const m = matchItems([R("Plain Cap")], bad);
      expect(m).toEqual({ matched: [], ambiguous: [], unknown: [{ row: expect.objectContaining({ name: "Plain Cap" }) }] });
    }
    for (const bad of [null, undefined, 5, "text", {}]) expect(matchItems(bad, CATALOG)).toEqual({ matched: [], ambiguous: [], unknown: [] });
    expect(matchItems([null, 5, "x", {}, { name: 7 }, { name: null }, []], CATALOG)).toEqual({ matched: [], ambiguous: [], unknown: [] });
  });
});

describe("names that are dangerous as object keys", () => {
  const names = ["__proto__", "constructor", "toString", "hasOwnProperty", "valueOf", "prototype", "__defineGetter__"];

  it("find nothing in a table that lacks them, and pollute nothing", () => {
    const before = Object.getOwnPropertyNames(Object.prototype).sort().join();
    const m = matchItems(names.map((n) => R(n)), CATALOG);
    expect(m.unknown).toHaveLength(names.length);
    expect(m.matched).toEqual([]);
    expect(Object.getOwnPropertyNames(Object.prototype).sort().join()).toBe(before);
    expect(({}).polluted).toBeUndefined();
  });

  it("are found when the table really has them, and only then", () => {
    const table = names.map((n, i) => item(900 + i, n, { aliases: [`${n} alias`] }));
    const m = matchItems([...names.map((n) => R(n)), ...names.map((n) => R(`${n} alias`))], table);
    expect(m.matched.map((x) => [x.row.name, x.key, x.stage])).toEqual([
      ...names.map((n, i) => [n, `w${900 + i}`, 1]),
      ...names.map((n, i) => [`${n} alias`, `w${900 + i}`, 3]),
    ]);
    expect(({}).constructor).toBe(Object);
    expect(Object.getPrototypeOf({})).toBe(Object.prototype);
    // and a table with such names does not make other names match
    expect(matchItems([R("Plain Cap")], table).unknown).toHaveLength(1);
  });
});

describe("size and speed", () => {
  it("a table of 11,250 items and a dump of 17,304 rows are matched in well under a second", () => {
    const table = Array.from({ length: 11250 }, (_, i) => item(1000 + i, `Pebble ${1000 + i}`, { aliases: [`Pebble alias ${i}`] }));
    const rows = Array.from({ length: 17304 }, (_, i) => R(i % 3 === 0 ? `Pebble ${1000 + (i % 11250)}` : i % 3 === 1 ? `The pebble ${1000 + (i % 11250)}` : `Unknown ${i}`));
    const watch = stopwatch();
    const m = matchItems(rows, table);
    const took = watch.stop();
    console.info(`match: 17,304 rows against 11,250 items in ${took.ms.toFixed(0)} ms`);
    expectWithin(took, 1000, "17,304 rows are matched against 11,250 items");
    expect(m.matched.length + m.ambiguous.length + m.unknown.length).toBe(17304);
    expect(m.matched.filter((x) => x.stage === 1).length).toBe(5768);
    expect(m.matched).toHaveLength(5768);
    expect(m.ambiguous.filter((x) => x.stage === 4 && x.keys.length === 1)).toHaveLength(5768); // "The pebble ..." is only ever offered
    expect(m.unknown.length).toBe(5768);
  });

  it("random rows against random tables: every row gets the answer of a plain reference reading of the rules", () => {
    let seed = 11;
    const rand = () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    const words = ["Plain", "Cap", "The", "A", "An", "Totem", "Worn", "Rag*", "Rag", "x", "constructor", "__proto__", "'s", "`s", CURLY, "(Weapon)", ""];
    const name = () => Array.from({ length: 1 + Math.floor(rand() * 4) }, () => words[Math.floor(rand() * words.length)]).join(rand() < 0.5 ? " " : "");

    // the rules, written the slow way: a pool from stages 1 to 3 (earliest stage per item), else stage 4, which only offers
    const quotes = new Set([0x60, 0x27, 0x2018, 0x2019, 0x201b, 0x2032, 0xb4, 0xfffd]);
    const fold = (t) => Array.from(t, (ch) => (quotes.has(ch.charCodeAt(0)) ? "'" : ch)).join("");
    const strip = (t) => {
      const lower = fold(t).toLowerCase();
      for (const article of ["a ", "an ", "the "]) if (lower.startsWith(article)) return lower.slice(article.length);
      return lower;
    };
    const reference = (row, table) => {
      const pool = [];
      const close = [];
      for (const it of table) {
        if (it.match_name.length === 0) continue; // an item with no match_name is not usable, aliases and all
        const names = [it.match_name, ...it.aliases].filter((n) => n.length > 0);
        let stage = Infinity;
        if (it.match_name === row) stage = 1;
        else if (fold(it.match_name) === fold(row)) stage = 2;
        if (it.aliases.some((a) => a.length > 0 && fold(a) === fold(row))) stage = Math.min(stage, 3);
        if (stage < Infinity) pool.push([it.key, stage]);
        if (names.some((n) => strip(n) === strip(row))) close.push(it.key);
      }
      if (pool.length === 1) return { kind: "matched", keys: [pool[0][0]], stage: pool[0][1] };
      if (pool.length > 1) return { kind: "ambiguous", keys: pool.map((x) => x[0]), stage: Math.min(...pool.map((x) => x[1])) };
      if (close.length > 0) return { kind: "ambiguous", keys: close, stage: 4 };
      return { kind: "unknown", keys: [], stage: 0 };
    };

    for (let round = 0; round < 300; round++) {
      const table = Array.from({ length: Math.floor(rand() * 30) }, (_, i) =>
        item(i, name(), { aliases: Array.from({ length: Math.floor(rand() * 3) }, name), owned_only: rand() < 0.2 }),
      );
      const rows = Array.from({ length: 40 }, () => R(name()));
      const m = matchItems(rows, table);
      const all = [...m.matched, ...m.ambiguous, ...m.unknown].map((x) => x.row);
      expect(all).toHaveLength(40);
      expect(new Set(all).size).toBe(40);
      for (const a of m.ambiguous) expect(new Set(a.keys).size).toBe(a.keys.length);
      for (const a of m.ambiguous) expect(a.stage === 4 ? a.keys.length : a.keys.length - 1).toBeGreaterThan(0); // stage 4 may offer one item, the others need two
      for (const x of m.matched) expect([1, 2, 3]).toContain(x.stage);
      // every row, one by one, against the reference
      const answers = new Map([...m.matched.map((x) => [x.row, { kind: "matched", keys: [x.key], stage: x.stage }]), ...m.ambiguous.map((x) => [x.row, { kind: "ambiguous", keys: x.keys, stage: x.stage }]), ...m.unknown.map((x) => [x.row, { kind: "unknown", keys: [], stage: 0 }])]);
      for (const row of rows) expect(answers.get(row), JSON.stringify(row.name)).toEqual(reference(row.name, table));
    }
  }, 30_000); // (two seconds alone, and past the five of the default when the machine is busy)
});
