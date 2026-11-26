// The browser's port of the table of procs (static/engine/procs.js) against Python's ProcTable: fixtures/procs/table.json, made by pipeline/tests/procs_fixture.py. For every table, item and hand the
// lists of procs and the sources of every effect are Python's, and for every pair of hands (with the Lore items a kit may wear) the best pair is Python's, entry for entry.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { procCandidates } from "../pipeline/trioforge/site/static/engine/model.js";
import { ProcTable, readProcs } from "../pipeline/trioforge/site/static/engine/procs.js";
import { BundleError } from "../pipeline/trioforge/site/static/engine/profile.js";
import { scenarioErrorCode } from "../pipeline/trioforge/site/static/engine/worker.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE = JSON.parse(readFileSync(resolve(HERE, "../fixtures/procs/table.json"), "utf8"));

const item = (spec) => Object.freeze({ key: spec.key, slots: Object.freeze([...spec.slots]), classes: Object.freeze([...spec.classes]), tier: spec.tier });
const shown = (entry) => (entry === null ? null : [entry.effect, entry.name, entry.donor, entry.mode, entry.value.toString()]);

describe("the table of procs of a bundle", () => {
  it("is read from the block of the bundle, and null for a trio with no proc worth anything", () => {
    expect(readProcs(null, ["WAR", "SHM", "ENC"])).toBeNull();
    const table = readProcs(FIXTURE.tables[0].procs, FIXTURE.tables[0].trio);
    expect(table).toBeInstanceOf(ProcTable);
    expect(readProcs(FIXTURE.tables[0].procs, FIXTURE.tables[0].trio)).toBe(table); // (read once)
  });

  it("refuses a value that is not a reduced p/q text (the engine's reader of exact numbers says so); the other checks of the block are the exporter's and its tests' (the bundle is held to its SHA-256)", () => {
    expect(() => readProcs({ socket_tier: 4, effects: [["e0", "E", "0.5"]], donors: [] }, ["WAR", "SHM", "ENC"])).toThrow();
  });
});

describe("a block of procs that is not the shape the exporter writes (F14)", () => {
  const TRIO = ["WAR", "SHM", "ENC"];
  const good = () => ({ socket_tier: 4, effects: [["e0", "Zero", "5/2"]], donors: [["e0", "w1", ["PRIMARY"], ["WAR"], 0, 0]] });
  const bad = {
    "a list": [],
    "a text": "procs",
    "no socket tier": (doc) => delete doc.socket_tier,
    "a socket tier that is not a whole number": (doc) => (doc.socket_tier = 4.5),
    "a socket tier below zero": (doc) => (doc.socket_tier = -1),
    "effects that are not a list": (doc) => (doc.effects = "e0"),
    "donors that are not a list": (doc) => (doc.donors = null),
    "an effect with two fields": (doc) => (doc.effects[0] = ["e0", "Zero"]),
    "an effect whose id is not a text": (doc) => (doc.effects[0][0] = 7),
    "an effect whose value is not a text": (doc) => (doc.effects[0][2] = 2.5),
    "a donor with five fields": (doc) => (doc.donors[0] = ["e0", "w1", ["PRIMARY"], ["WAR"], 0]),
    "a donor whose slots are not a list": (doc) => (doc.donors[0][2] = "PRIMARY"),
    "a donor whose classes are not a list": (doc) => (doc.donors[0][3] = null),
    "a donor of an effect the table does not have": (doc) => (doc.donors[0][0] = "e9"),
    "a donor whose flag is not 0 or 1": (doc) => (doc.donors[0][4] = 2),
    "a donor whose key is not a text": (doc) => (doc.donors[0][1] = null),
    // (G2) what Python's from_doc refuses too
    "a value that is not reduced": (doc) => (doc.effects[0][2] = "4/2"),
    "a value that is no number": (doc) => (doc.effects[0][2] = "abc"),
    "a value with no denominator": (doc) => (doc.effects[0][2] = "5"),
    "a value that is zero": (doc) => (doc.effects[0][2] = "0/1"),
    "a value below zero": (doc) => (doc.effects[0][2] = "-5/1"),
    "an effect in the table twice": (doc) => doc.effects.push(["e0", "Again", "7/2"]),
    "donor slots that are not texts": (doc) => (doc.donors[0][2] = [1]),
    "donor classes that are not texts": (doc) => (doc.donors[0][3] = [null]),
    "a field more": (doc) => (doc.extra = 1),
    "a field fewer": (doc) => delete doc.donors,
  };

  it("refuses a part of a value of more than 64 digits, which Python's reader takes (the one place the browser's is stricter: no build writes such a text)", () => {
    const doc = good();
    doc.effects[0][2] = `1${"0".repeat(69)}/1`;
    expect(() => readProcs(doc, TRIO)).toThrow(BundleError);
    doc.effects[0][2] = `1${"0".repeat(63)}/1`; // (64 digits: read)
    expect(readProcs(doc, TRIO)).toBeInstanceOf(ProcTable);
  });

  it("reads the block that has the shape", () => {
    expect(readProcs(good(), TRIO)).toBeInstanceOf(ProcTable);
  });

  it.each(Object.entries(bad))("refuses it with a BundleError that says which part, which the worker answers as a bad request and not as an internal fault that replaces it: %s", (_, change) => {
    const doc = typeof change === "function" ? good() : change;
    if (typeof change === "function") change(doc);
    expect(() => readProcs(doc, TRIO)).toThrow(BundleError);
    try {
      readProcs(doc, TRIO);
    } catch (error) {
      expect(error.message).toMatch(/^procs/);
      expect(scenarioErrorCode(error)).toBe("bad-request");
    }
  });
});

describe("the donor a single swinging hand records (F3)", () => {
  const TRIO = ["WAR", "SHM", "ENC"];
  const DOC = {
    socket_tier: 4,
    effects: [["e-rare", "rare", "900/1"], ["e-poor", "poor", "100/1"]],
    donors: [
      ["e-poor", "rag", ["PRIMARY", "SECONDARY"], ["WAR"], 0, 0],
      ["e-rare", "arc", ["PRIMARY", "SECONDARY"], ["WAR"], 0, 1], // a Lore item whose key is the smallest
      ["e-rare", "club", ["PRIMARY", "SECONDARY"], ["WAR"], 0, 0],
    ],
  };
  const axe = item({ key: "axe", slots: ["PRIMARY", "SECONDARY"], classes: ["WAR"], tier: 4 });
  const half = Rational.parse("1/2");

  it("is the smallest key when the kit wears nothing, and never a Lore item that the kit wears", () => {
    const table = readProcs(DOC, TRIO);
    const free = table.best(axe, null, half, new Set());
    expect(shown(free.primary)).toEqual(["e-rare", "rare", "arc", "h", "900/1"]);
    for (const worn of [new Set(["arc"]), new Set(["arc", "other"])]) {
      const main = table.best(axe, null, half, worn);
      expect([main.primary.effect, main.primary.donor, main.primary.mode], "the main hand alone").toEqual(["e-rare", "club", "h"]);
      expect(main.secondary).toBeNull();
      const off = table.best(null, axe, half, worn);
      expect(off.primary).toBeNull();
      expect([off.secondary.effect, off.secondary.donor, off.secondary.mode], "the off hand alone").toEqual(["e-rare", "club", "h"]);
      for (const entry of [main.primary, off.secondary]) expect(worn.has(entry.donor)).toBe(false);
    }
  });

  it("keeps the copy that is worn as the source of a native proc", () => {
    const table = readProcs({ socket_tier: 4, effects: [["e-rare", "rare", "900/1"]], donors: [["e-rare", "arc", ["PRIMARY", "SECONDARY"], ["WAR"], 0, 1]] }, TRIO);
    const mine = table.best(item({ key: "arc", slots: ["PRIMARY", "SECONDARY"], classes: ["WAR"], tier: 4 }), null, half, new Set(["arc"]));
    expect([mine.primary.donor, mine.primary.mode]).toEqual(["arc", "n"]);
  });
});

describe("the answers of the table against Python's", () => {
  it.each(FIXTURE.tables.map((table, index) => [index, table]))("table %i: the procs of every item in each hand, its candidates and its sources of every effect", (_, doc) => {
    const table = readProcs(doc.procs, doc.trio);
    for (const row of doc.items) {
      const one = item(row.item);
      for (const hand of ["PRIMARY", "SECONDARY"]) {
        const want = row[hand];
        expect(table.every(one, hand).map(shown), `${row.item.key} ${hand} every`).toEqual(want.every);
        expect(procCandidates(table, one, hand).map(shown), `${row.item.key} ${hand} candidates`).toEqual(want.candidates);
        for (const [effect, sources] of Object.entries(want.sources)) expect(table.sources(one, hand, effect), `${row.item.key} ${hand} ${effect}`).toEqual(sources);
      }
    }
  });

  it.each(FIXTURE.tables.map((table, index) => [index, table]))("table %i: the best pair of hands, with the Lore items a kit wears and without", (_, doc) => {
    const table = readProcs(doc.procs, doc.trio);
    let counted = 0;
    for (const pair of doc.pairs) {
      const got = table.best(item(pair.primary), pair.secondary === null ? null : item(pair.secondary), Rational.parse(pair.factor), new Set(pair.worn));
      expect([shown(got.primary), shown(got.secondary)], JSON.stringify(pair)).toEqual(pair.best);
      if (got.primary !== null || got.secondary !== null) counted += 1;
    }
    expect(counted).toBeGreaterThan(0);
  });

  it("has Lore donors that a worn copy blocks somewhere in the fixture: the rule is exercised", () => {
    const blocked = FIXTURE.tables.flatMap((doc) => doc.pairs).filter((pair) => pair.worn.length > 0);
    expect(blocked.length).toBeGreaterThan(20);
  });
});
