// The item table as the browser reads it (items.js, readItemTable): the file `items.json` that the precompute writes beside the shards (pipeline/trioforge/
// export/browser.py, `items`), read into a lookup by item key. It is the reader's contract with the writer: the format number, the fields of the table and of
// a record, what an absent field means (the table's own `defaults`), and nothing the writer does not write. The items of the table go through `atTier` for the
// numbers the model sees; that is tested in engine-items.test.mjs, and the table of the synthetic site fixture is read here whole.

import { describe, expect, it } from "vitest";
import { ITEM_DEFAULTS, ItemError, MAX_ITEM_KEY_LENGTH, atTier, readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { BUNDLE_BYTES, ITEMS_BYTES } from "./engine-site-fixture.mjs";

const TABLE = JSON.parse(ITEMS_BYTES.toString("utf8"));
const BUNDLE = readBundle(JSON.parse(BUNDLE_BYTES.toString("utf8")));
const copy = (change) => {
  const table = structuredClone(TABLE);
  change(table);
  return table;
};
const record = (table, key) => table.items.find((r) => (r.key ?? `w${r.id}`) === key);

describe("the item table of the site fixture", () => {
  const read = readItemTable(TABLE);

  it("is read into the release it was made for, the rules version and a lookup by item key", () => {
    expect(read.dataRelease).toBe("data-2026-10-14");
    expect(read.rulesVersion).toBe(BUNDLE.rules_version);
    expect(read.dataRelease).toBe(BUNDLE.data_release);
    expect(read.count).toBe(TABLE.count);
    expect(read.records).toBeInstanceOf(Map);
    expect(read.records.size).toBe(TABLE.items.length);
    expect(read.records.get("w90001").name).toBe("Helm of the Stoneward");
    expect(read.records.get("constructor")).toBeUndefined();
    expect(read.records.get("__proto__")).toBeUndefined();
  });

  it("finds a record by the key it has or the key its page id gives", () => {
    expect(TABLE.items.some((r) => r.key === undefined)).toBe(true); // the keys of the wiki items are left out: w and the page id
    for (const r of TABLE.items) expect(read.records.get(r.key ?? `w${r.id}`)).toBe(r);
  });

  it("gives the numbers of an item at a tier from a record, under the rules of the bundle", () => {
    const helm = atTier(read.records.get("w90001"), 4, BUNDLE);
    expect(helm.key).toBe("w90001");
    expect(helm.tier).toBe(4);
    expect(helm.stats.AC).toBeGreaterThan(30);
    expect(atTier(read.records.get("w80524"), 4, BUNDLE).weapon.two_handed).toBe(true);
    expect(atTier(read.records.get("w80758"), 0, BUNDLE).is_shield).toBe(true);
    expect(atTier(read.records.get("w90041"), 0, BUNDLE).key).toBe("w90041"); // an item that only a player may own
  });

  it("says what an absent field means in the table's own defaults, which are the module's", () => {
    expect(read.defaults).toEqual(ITEM_DEFAULTS);
    expect(TABLE.defaults).toEqual(ITEM_DEFAULTS);
  });
});

const BAD = {
  "no table at all": [null, [], "items", 5, undefined],
  "another version": [copy((t) => (t.version = 2)), copy((t) => (t.version = true)), copy((t) => (t.version = "1")), copy((t) => delete t.version)],
  "a field of the table that is not allowed": [copy((t) => (t.price = 1)), copy((t) => (t.url = "/x"))],
  "a field of the table that is missing": [copy((t) => delete t.items), copy((t) => delete t.defaults), copy((t) => delete t.count), copy((t) => delete t.rules_version), copy((t) => delete t.data_release)],
  "a release that is not text or null": [copy((t) => (t.data_release = 5)), copy((t) => (t.data_release = ""))],
  "a rules version that is not text": [copy((t) => (t.rules_version = 5)), copy((t) => (t.rules_version = null)), copy((t) => (t.rules_version = ""))],
  "a count that is not the number of records": [copy((t) => (t.count = t.count + 1)), copy((t) => (t.count = 0)), copy((t) => (t.count = "48")), copy((t) => (t.count = 1.5))],
  "defaults that are not the exporter's": [
    copy((t) => (t.defaults.lore = true)),
    copy((t) => (t.defaults.classes = ["PAL"])),
    copy((t) => delete t.defaults.owned_only),
    copy((t) => (t.defaults.extra = 1)),
    copy((t) => (t.defaults = [])),
  ],
  "records that are not a list": [copy((t) => (t.items = {})), copy((t) => (t.items = "w1")), copy((t) => (t.items = null))],
  "a record that is not an object": [copy((t) => t.items.push("w1")), copy((t) => t.items.push(null)), copy((t) => t.items.push([1]))],
  "a record with a field that is not allowed": [copy((t) => (t.items[0].price = 5)), copy((t) => (t.items[0].url = "/x")), copy((t) => (t.items[0].constructor = {}))],
  "a record with a prototype key": [
    copy((t) => {
      t.items[0] = JSON.parse(`{"id": 546, "name": "x", "slots": ["HEAD"], "tier_rule": "drop", "weight10": null, "evidence": {"level": "wiki"}, "__proto__": {"a": 1}}`);
    }),
  ],
  "a record with no name": [copy((t) => delete t.items[0].name), copy((t) => (t.items[0].name = "")), copy((t) => (t.items[0].name = 5))],
  "a record with no slots, or slots that are not the catalog's": [copy((t) => delete t.items[0].slots), copy((t) => (t.items[0].slots = [])), copy((t) => (t.items[0].slots = ["HAT"])), copy((t) => (t.items[0].slots = "HEAD"))],
  "a record with a tier rule that is not one": [copy((t) => (t.items[0].tier_rule = "loot")), copy((t) => delete t.items[0].tier_rule), copy((t) => (t.items[0].tier_rule = 5))],
  "a record with an evidence that is not a level": [copy((t) => (t.items[0].evidence = "wiki")), copy((t) => (t.items[0].evidence = { level: "legend" })), copy((t) => delete t.items[0].evidence), copy((t) => (t.items[0].evidence = { level: "wiki", extra: 1 }))],
  "a hidden item that is not flagged, and a flag on an item that is not hidden": [copy((t) => delete record(t, "w90041").owned_only), copy((t) => (record(t, "w90001").owned_only = true)), copy((t) => (record(t, "w90041").owned_only = false))],
  "a record with no page id": [copy((t) => delete t.items[0].id), copy((t) => (t.items[0].id = "546")), copy((t) => (t.items[0].id = 0)), copy((t) => (t.items[0].id = 1.5))],
  "a record with a key that is not an item key": [copy((t) => (t.items[0].key = "Helm")), copy((t) => (t.items[0].key = "w")), copy((t) => (t.items[0].key = "__proto__")), copy((t) => (t.items[0].key = ""))],
  "a record with no page id and no key": [copy((t) => (t.items[0].id = null))],
  "two records of one key": [copy((t) => t.items.push(structuredClone(t.items[0])))],
  "stats that are not whole numbers": [copy((t) => (t.items[0].stats = { AC: "many" })), copy((t) => (t.items[0].stats = { AC: 1.5 })), copy((t) => (t.items[0].stats = [1]))],
  "a weight that is not whole tenths or null": [copy((t) => (t.items[0].weight10 = 1.5)), copy((t) => (t.items[0].weight10 = -1)), copy((t) => (t.items[0].weight10 = "3")), copy((t) => delete t.items[0].weight10)],
  "a weapon without its four fields": [copy((t) => (record(t, "w80988").weapon = { skill: "1H Slashing", dmg: 18 })), copy((t) => (record(t, "w80988").weapon = { skill: "1H Slashing", dmg: "x", delay: 26, bonus: null }))],
  "classes or races that are not texts": [copy((t) => (t.items[0].classes = [5])), copy((t) => (t.items[0].races = "ALL")), copy((t) => (t.items[0].deity = []))],
  "a flag that is only there when it is true": [copy((t) => (t.items[0].lore = false)), copy((t) => (t.items[0].lore = "yes"))],
  "a source that is not an object": [copy((t) => (t.items[0].source = "The Hole")), copy((t) => (t.items[0].source = []))],
  "a table of too many records": [copy((t) => (t.items.length = 0)), copy((t) => (t.count = 200_001))],
};

describe("an item table that is not what the precompute writes", () => {
  for (const [name, values] of Object.entries(BAD)) {
    it(`is refused: ${name}`, () => {
      for (const value of values) expect(() => readItemTable(value)).toThrow(ItemError);
    });
  }

  it("is refused with a message that names the part and does not quote the file", () => {
    let message = "";
    try {
      readItemTable(copy((t) => (t.items[0].name = "https://evil.example/x\u0000")));
    } catch (error) {
      message = error.message;
    }
    expect(message).toMatch(/^item table: /);
    expect(message).not.toContain("evil.example");
  });

  it("is refused when it is far too big to be one, before its records are read", () => {
    const table = copy(() => {});
    table.items = new Array(200_001).fill(table.items[0]);
    table.count = table.items.length;
    expect(() => readItemTable(table)).toThrow(ItemError);
  });
});

// ---- what the reader takes from the writer, and no more -------------------------------------------------------------------------------------------
// The limits of a record are the reader's own: the build holds the files to them (site/data.py checks the same limits, and the engine's own readers are run on
// everything the build publishes), so that no file passes the build that the worker then refuses.

/** A table of the records given, otherwise as the fixture's. */
const tableOf = (...records) => copy((t) => ((t.items = records), (t.count = records.length)));
const cap = (over = {}) => ({ id: 70001, name: "Test Cap", slots: ["HEAD"], weight10: 10, tier_rule: "fixed0", evidence: { level: "wiki" }, ...over });
const refuses = (document) => expect(() => readItemTable(document)).toThrow(ItemError);
const reads = (document) => expect(() => readItemTable(document)).not.toThrow();

describe("the keys of the items", () => {
  it("are w and a page id with no zero in front, or r and a name: the same item is not written two ways", () => {
    for (const key of ["w7", "w70001", "w123456789012345", "rcap", "r7-up", "r1-2-3", `r${"a".repeat(99)}`]) reads(tableOf(cap({ id: null, key })));
    for (const key of ["w07", "w0", "w00", "w0123", "w007", "w1234567890123456", "W7", "w", "w-7", "w7.0", "r", "r-a", `r${"a".repeat(101)}`]) refuses(tableOf(cap({ id: null, key })));
  });

  it("are at most MAX_ITEM_KEY_LENGTH characters long, the number that the matcher of a dump reads keys by too", () => {
    expect(MAX_ITEM_KEY_LENGTH).toBe(101);
    reads(tableOf(cap({ id: null, key: `r${"a".repeat(MAX_ITEM_KEY_LENGTH - 1)}` })));
    refuses(tableOf(cap({ id: null, key: `r${"a".repeat(MAX_ITEM_KEY_LENGTH)}` })));
  });

  it("are not made of a page id with a zero in front either: an id is a whole number, and w07 is not the key of page 7", () => {
    refuses(tableOf(cap({ id: 7 }), cap({ id: 8, key: "w07" })));
    expect(readItemTable(tableOf(cap({ id: 7 }))).records.has("w7")).toBe(true);
    expect(readItemTable(tableOf(cap({ id: 7 }))).records.has("w07")).toBe(false);
  });

  it("name one item each: a key that another record has, written out or made of its page id, is refused", () => {
    refuses(tableOf(cap({ id: 7 }), cap({ id: 8, key: "w7" }))); // the key of page 7, written out for page 8
    refuses(tableOf(cap({ id: 8, key: "w7" }), cap({ id: 7 })));
    refuses(tableOf(cap({ id: null, key: "rcap" }), cap({ id: null, key: "rcap" })));
    refuses(tableOf(cap({ id: 7 }), cap({ id: 7 })));
    reads(tableOf(cap({ id: 7 }), cap({ id: 8 }), cap({ id: null, key: "rcap" })));
  });

  it("belong to one page id: two records of one page are refused, whatever keys they have", () => {
    refuses(tableOf(cap({ id: 7 }), cap({ id: 7, key: "rother" })));
    refuses(tableOf(cap({ id: 7, key: "rone" }), cap({ id: 7, key: "rtwo" })));
    reads(tableOf(cap({ id: null, key: "rone" }), cap({ id: null, key: "rtwo" }))); // items with no page have none to share
  });
});

describe("the stats and the resists of a record", () => {
  const STATS = ["AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG", "HASTE"];
  const SCHOOLS = ["FIRE", "COLD", "MAGIC", "POISON", "DISEASE", "CORRUPTION"];

  it("are named as atTier names them: a stat it would refuse is refused when the table is read, not at the first tier asked for", () => {
    reads(tableOf(cap({ stats: Object.fromEntries(STATS.map((name) => [name, 3])), sv: Object.fromEntries(SCHOOLS.map((name) => [name, 4])) })));
    for (const stats of [{ FOO: 3 }, { ac: 3 }, { AC: 3, "": 1 }, { HASTE_: 1 }, { SV: 2 }, { ATTACK: 2 }]) refuses(tableOf(cap({ stats })));
    for (const sv of [{ FOO: 3 }, { fire: 3 }, { ALL: 3 }, { PHYSICAL: 1 }]) refuses(tableOf(cap({ sv })));
  });

  it("are the same for the whole table: every record at every tier is worked out by atTier once the table is read", () => {
    const read = readItemTable(TABLE);
    for (const record of read.records.values()) for (let tier = 0; tier <= 10; tier += 1) expect(() => atTier(record, tier, BUNDLE), `${record.id} at +${tier}`).not.toThrow();
  });
});

describe("the limits of a record", () => {
  it("are those the build holds the files to: 16 deities, 16 races, 17 classes, 64 aliases, 40 characters of item type, 40 reason codes", () => {
    reads(tableOf(cap({ deity: Array.from({ length: 16 }, (_, n) => `God ${n}`), races: Array.from({ length: 16 }, (_, n) => `R${n}`), aliases: Array.from({ length: 64 }, (_, n) => `A ${n}` ) })));
    reads(tableOf(cap({ item_type: "x".repeat(40), evidence: { level: "wiki", codes: Array.from({ length: 40 }, (_, n) => `code-${n}`) } })));
    refuses(tableOf(cap({ deity: Array.from({ length: 17 }, (_, n) => `God ${n}`) })));
    refuses(tableOf(cap({ races: Array.from({ length: 17 }, (_, n) => `R${n}`) })));
    refuses(tableOf(cap({ classes: Array.from({ length: 18 }, (_, n) => `C${n}`) })));
    refuses(tableOf(cap({ aliases: Array.from({ length: 65 }, (_, n) => `A ${n}`) })));
    refuses(tableOf(cap({ item_type: "x".repeat(41) })));
    refuses(tableOf(cap({ evidence: { level: "wiki", codes: Array.from({ length: 41 }, (_, n) => `code-${n}`) } })));
  });

  it("have names and texts without a control or a separator character: a line or a paragraph separator is none of a name", () => {
    for (const bad of ["a b", "a b", "a\u0000b", "a\nb", "a\u0085b", "a\u007fb", "a\u009fb"]) {
      refuses(tableOf(cap({ name: bad })));
      refuses(tableOf(cap({ item_type: bad })));
      refuses(tableOf(cap({ aliases: [bad] })));
      refuses(tableOf(cap({ evidence: { level: "wiki", codes: [bad] } })));
    }
    reads(tableOf(cap({ name: "Cap of the Élan" })));
  });
});

describe("the source of an item", () => {
  const SHAPES = {
    "a zone it drops in": { drops: ["The Hole"] },
    "zones it drops in, with the ones that did not fit counted": { drops: ["A", "B", "C"], more: { drops: 4 } },
    "zones it is sold in": { sold: ["A", "B"] },
    "zones it is foraged in, with some more": { forage: ["A", "B"], more: { forage: 1 } },
    "quests, with more": { quests: ["Plane of Sky quest", "Another quest"], more: { quests: 3 } },
    "crafted": { crafted: 5 },
    "several of them": { drops: ["A"], sold: ["B", "C", "D"], forage: ["E"], quests: ["Q"], crafted: 1, more: { sold: 2 } },
    "a quest of a sentence": { quests: ["x".repeat(200)] },
  };
  for (const [name, source] of Object.entries(SHAPES)) {
    it(`is taken as the exporter writes it: ${name}`, () => {
      reads(tableOf(cap({ source })));
    });
  }

  const BAD_SOURCES = {
    "no object": ["The Hole", ["The Hole"], 5, null, true],
    "an object with nothing in it": [{}],
    "a key the exporter does not write": [{ url: "/x" }, { drops: ["A"], price: 5 }, { Drops: ["A"] }, { sold_by: ["A"] }, { foraged: ["A"] }, { crafted: 1, extra: 1 }],
    "a key that could poison a lookup": [JSON.parse(`{"drops": ["A"], "__proto__": {"a": 1}}`)],
    "a list that is not a list of texts": [{ drops: "A" }, { drops: [5] }, { drops: [null] }, { drops: [["A"]] }, { drops: {} }, { quests: [{ name: "Q" }] }],
    "an empty list": [{ drops: [] }, { quests: [] }],
    "a list longer than the exporter makes it": [{ drops: ["A", "B", "C", "D"] }, { sold: ["A", "B", "C", "D"] }, { forage: ["A", "B", "C"] }, { quests: ["A", "B", "C"] }],
    "a list with a place twice": [{ drops: ["A", "A"] }],
    "a text that is empty or long or has a control or a separator": [
      { drops: [""] },
      { drops: ["x".repeat(201)] },
      { drops: ["a b"] },
      { sold: ["a b"] },
      { forage: ["a\u0000b"] },
      { quests: ["a\nb"] },
      { quests: ["a\u0085b"] },
    ],
    "a count that is not a whole number of at least one": [{ crafted: 0 }, { crafted: -1 }, { crafted: 1.5 }, { crafted: "2" }, { crafted: null }, { crafted: true }, { crafted: 1_000_000_001 }],
    "more that is not an object of counts": [{ drops: ["A", "B", "C"], more: 4 }, { drops: ["A", "B", "C"], more: [] }, { drops: ["A", "B", "C"], more: {} }, { drops: ["A", "B", "C"], more: null }],
    "more of a kind that the exporter does not count": [{ drops: ["A", "B", "C"], more: { crafted: 1 } }, { drops: ["A", "B", "C"], more: { other: 1 } }],
    "more with a count that is not a whole number of at least one": [
      { drops: ["A", "B", "C"], more: { drops: 0 } },
      { drops: ["A", "B", "C"], more: { drops: -2 } },
      { drops: ["A", "B", "C"], more: { drops: 1.5 } },
      { drops: ["A", "B", "C"], more: { drops: "2" } },
    ],
    "more of a kind that is not full (the exporter counts only what did not fit)": [{ drops: ["A"], more: { drops: 2 } }, { more: { drops: 2 } }, { drops: ["A", "B", "C"], more: { sold: 1 } }],
    "more alone": [{ more: { quests: 1 } }],
  };
  for (const [name, sources] of Object.entries(BAD_SOURCES)) {
    it(`is refused: ${name}`, () => {
      for (const source of sources) refuses(tableOf(cap({ source })));
    });
  }

  it("is refused with a message that names the part and does not quote the file", () => {
    let message = "";
    try {
      readItemTable(tableOf(cap({ source: { drops: ["https://evil.example/x "] } })));
    } catch (error) {
      message = error.message;
    }
    expect(message).toMatch(/^item table: /);
    expect(message).toMatch(/source/);
    expect(message).not.toContain("evil.example");
  });

  it("is, in the item table of the site fixture, as the exporter writes it (the fixture is read whole above)", () => {
    expect(TABLE.items.filter((r) => r.source !== undefined).length).toBeGreaterThan(10);
  });
});

describe("the fingerprint of the inputs", () => {
  const FINGERPRINT = "0123456789abcdef".repeat(4);

  it("is an optional field of the table: 64 lower-case hexadecimal digits, handed on by the reader, or none", () => {
    expect(readItemTable(copy(() => {})).inputs).toBe(TABLE.inputs ?? null);
    const given = readItemTable(copy((t) => (t.inputs = FINGERPRINT)));
    expect(given.inputs).toBe(FINGERPRINT);
    const none = readItemTable(copy((t) => delete t.inputs));
    expect(none.inputs).toBeNull();
  });

  it("is refused when it is anything else", () => {
    for (const inputs of ["", FINGERPRINT.toUpperCase(), FINGERPRINT.slice(1), `${FINGERPRINT}0`, `g${FINGERPRINT.slice(1)}`, 5, null, true, [FINGERPRINT], { sha: FINGERPRINT }]) {
      refuses(copy((t) => (t.inputs = inputs)));
    }
  });
});
