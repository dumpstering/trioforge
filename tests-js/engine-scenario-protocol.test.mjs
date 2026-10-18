// The scenario request of mode "equip-now" and its answer, checked in both directions (protocol.js): what the page sends the worker, and what the
// worker sends back. The request is
//   {v, kind: "scenario", trio, level, mode: "equip-now", scenario: {race, role, buffs, evidence, setup, deity?}, owned: [[ident, count], ...], budgetMs}
// with an ident `<key>@<tier>`, a count of 1 to 99, at most 1,000 entries and none twice. Every field has an allowlist. The other modes of a scenario
// request have allowlists of their own (engine-scenario-modes-protocol.test.mjs), and a request of any other mode, or of the old generic shape, is a bad request.

import { describe, expect, it } from "vitest";
import { LABEL_NO_INCUMBENT, LABEL_TIME_LIMIT, LIMITS, validateFromWorker, validateRequest, validateToWorker } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { parseManifest } from "../pipeline/trioforge/site/static/engine/manifest.js";

const MANIFEST = parseManifest({
  version: 2,
  highs: "1.15.3",
  data_release: "data-2026-10-14",
  rules_version: "2026-10-13",
  client: { path: "/assets/engine/client-AAAAAAAA.js", bytes: 9000, gzip: 3000 },
  worker: { path: "/assets/engine/worker-BBBBBBBB.js", bytes: 120000, gzip: 40000 },
  wasm: { path: "/assets/engine/highs-0123456789ABCDEF.wasm", bytes: 3531385, gzip: 1200000, sha256: "0123456789abcdef" + "f".repeat(48) },
  items: { path: "/assets/engine/data/items-89ABCDEF01234567.json", bytes: 10346, gzip: 3000, sha256: "89abcdef01234567" + "1".repeat(48) },
  trios: { "pal-mnk-ber": [50] },
});

const SCENARIO = { race: "OGR", role: "balanced", buffs: "own", evidence: "wiki", setup: "dw" };
const request = (over = {}) => ({
  v: 1,
  kind: "scenario",
  trio: "pal-mnk-ber",
  level: 50,
  mode: "equip-now",
  scenario: { ...SCENARIO },
  owned: [["w90001@4", 1], ["w90007@4", 2], ["w80113@0", 99]],
  budgetMs: 5000,
  ...over,
});
const scenario = (over) => request({ scenario: { ...SCENARIO, ...over } });
const bad = (value, manifest) => expect(() => validateRequest(value, manifest)).toThrow(/bad-request/);

describe("a request for Equip now", () => {
  it("is accepted, and a detached copy of it is what is sent", () => {
    const original = request();
    const clean = validateRequest(original, MANIFEST);
    expect(clean).toEqual(original);
    expect(clean).not.toBe(original);
    expect(clean.scenario).not.toBe(original.scenario);
    expect(clean.owned).not.toBe(original.owned);
    expect(clean.owned[0]).not.toBe(original.owned[0]);
    original.owned[0][0] = "w1@0";
    original.owned.push(["w2@0", 1]);
    original.scenario.race = "HUM";
    expect(clean.owned).toEqual([["w90001@4", 1], ["w90007@4", 2], ["w80113@0", 99]]); // what was checked is what is sent, whatever the caller does afterwards
    expect(clean.scenario.race).toBe("OGR");
  });

  it("has a scenario whose copy has no prototype to poison, and nothing but its five fields and the deity", () => {
    const clean = validateRequest(request());
    expect(Object.getPrototypeOf(clean.scenario) === null || Object.getPrototypeOf(clean.scenario) === Object.prototype).toBe(true);
    expect(Object.keys(clean.scenario)).toEqual(["race", "role", "buffs", "evidence", "setup"]);
    expect(Object.keys(validateRequest(scenario({ deity: "Karana" })).scenario)).toEqual(["race", "role", "buffs", "evidence", "setup", "deity"]);
  });

  it("takes a deity that is a short name, or null, or none", () => {
    for (const deity of ["Karana", "The Tribunal", "Brell Serilis", "Cazic-Thule", "Rallos Zek", "A".repeat(LIMITS.maxNameLength)]) {
      expect(validateRequest(scenario({ deity })).scenario.deity).toBe(deity);
    }
    expect(validateRequest(scenario({ deity: null })).scenario.deity).toBeNull();
    expect("deity" in validateRequest(request()).scenario).toBe(false);
  });

  it("takes the names a bundle has: the buff sets with a plus sign, the weapon setups with a hyphen or a digit, race codes, role names, evidence levels", () => {
    for (const [field, values] of Object.entries({
      race: ["HUM", "OGR", "IKS", "FRG"],
      role: ["balanced", "tank", "melee", "caster"],
      buffs: ["own", "group", "group+enchanter", "raid"],
      evidence: ["strict", "wiki"],
      setup: ["1h-shield", "2h", "dw", "stick"],
    })) {
      for (const value of values) expect(validateRequest(scenario({ [field]: value })).scenario[field]).toBe(value);
    }
  });

  it("takes an owned set of no item, of one, and of the most there may be (1,000 entries), with counts from 1 to 99 and tiers from 0 to 10", () => {
    expect(validateRequest(request({ owned: [] })).owned).toEqual([]);
    expect(validateRequest(request({ owned: [["w1@0", 1]] })).owned).toEqual([["w1@0", 1]]);
    const most = Array.from({ length: LIMITS.maxOwnedEntries }, (_, n) => [`w${n + 1}@${n % 11}`, (n % 99) + 1]);
    expect(LIMITS.maxOwnedEntries).toBe(1000);
    expect(validateRequest(request({ owned: most })).owned).toEqual(most);
    for (const tier of ["0", "1", "9", "10"]) expect(validateRequest(request({ owned: [[`w5@${tier}`, 1]] })).owned[0][0]).toBe(`w5@${tier}`);
    for (const count of [1, 2, 98, 99]) expect(validateRequest(request({ owned: [["w5@4", count]] })).owned[0][1]).toBe(count);
    expect(LIMITS.maxOwnedCount).toBe(99);
  });

  it("takes the keys of the item table: w and a page number, or an r and a short slug", () => {
    for (const key of ["w1", "w8091", "w123456789012345", "rabc", "r1-2-3", `r${"a".repeat(100)}`]) {
      expect(validateRequest(request({ owned: [[`${key}@4`, 1]] })).owned[0][0]).toBe(`${key}@4`);
    }
  });

  it("is checked against the manifest: a trio and a level it lists", () => {
    expect(() => validateRequest(request(), MANIFEST)).not.toThrow();
    for (const over of [{ trio: "war-war-war" }, { trio: "constructor" }, { level: 49 }, { level: 55 }, { level: "50" }]) bad(request(over), MANIFEST);
  });

  describe("refuses, in the page and in the worker alike,", () => {
    const BAD_IDENTS = {
      "an ident that is a prototype word": ["__proto__@4", "constructor@4", "prototype@4", "toString@4", "hasOwnProperty@4", "__proto__@0"],
      "a tier above 10": ["w5@11", "w5@12", "w5@100", "w5@999999"],
      "a tier below 0": ["w5@-1", "w5@-0"],
      "a tier written some other way": ["w5@04", "w5@4.0", "w5@4e0", "w5@0x4", "w5@ 4", "w5@4 ", "w5@+4", "w5@four", "w5@", "w5@٤"],
      "no tier": ["w5", "w5@@4", "@4", "w5@4@4", "w5#4", "w5:4", "w5 4"],
      "a key that is not an item key": ["W5@4", "w@4", "w5a@4", "x5@4", "5@4", "r@4", "rA@4", "r-a@4", "w1234567890123456@4", `r${"a".repeat(101)}@4`, "w-5@4", "w5.0@4"],
      "a key with a zero in front of the page id (w07 is not another name of w7)": ["w0@4", "w00@4", "w05@4", "w007@4", "w0123@4", "w00000000000001@4", "w012345678901234@4"],
      "an ident that looks like an address": ["https://evil.example/x@4", "//evil.example@4", "w5/../@4", "w5\\x@4", "javascript:alert(1)@4", "w5@4?x=1", "w5@4#x"],
      "an ident with a character that is not allowed": ["w5\u0000@4", "w5\n@4", "w5​@4", "w5é@4", "w5 @4", "w5 @4"],
      "an ident that is far too long": [`w5${"0".repeat(500)}@4`, `${"w".repeat(5000)}@4`],
      "an ident that is empty": [""],
    };
    for (const [name, idents] of Object.entries(BAD_IDENTS)) {
      it(name, () => {
        for (const ident of idents) bad(request({ owned: [[ident, 1]] }));
      });
    }

    it("a count that is not a whole number from 1 to 99", () => {
      for (const count of [0, 100, 101, 1000, -1, 1.5, 0.5, 98.99, "2", "99", null, undefined, true, false, Number.NaN, Infinity, -Infinity, [2], { n: 2 }, 2n]) {
        bad(request({ owned: [["w5@4", count]] }));
      }
    });

    it("more than 1,000 entries, however small they are", () => {
      const over = Array.from({ length: LIMITS.maxOwnedEntries + 1 }, (_, n) => [`w${n + 1}@0`, 1]);
      bad(request({ owned: over }));
      bad(request({ owned: Array.from({ length: 100_000 }, () => ["w5@4", 1]) })); // and a list that big is refused before anything is copied
    });

    it("an ident twice, in one tier or the same text spelled in the same way, and the same ident with other counts", () => {
      bad(request({ owned: [["w5@4", 1], ["w5@4", 1]] }));
      bad(request({ owned: [["w5@4", 1], ["w6@4", 1], ["w5@4", 2]] }));
      expect(validateRequest(request({ owned: [["w5@4", 1], ["w5@5", 1], ["w6@4", 1]] })).owned).toHaveLength(3); // the same key at other tiers is another item
    });

    it("an entry that is not a pair of an ident and a count", () => {
      for (const entry of [[], ["w5@4"], ["w5@4", 1, 1], [["w5@4"], 1], [5, 1], [null, 1], [undefined, 1], { ident: "w5@4", count: 1 }, "w5@4", 5, null, undefined, true, ["w5@4", 1, "x"]]) {
        bad(request({ owned: [entry] }));
      }
    });

    it("an owned set that is not a list, or a list with a hole in it, or one with extra properties", () => {
      for (const owned of [{}, "w5@4", 5, null, undefined, new Map([["w5@4", 1]]), new Set(["w5@4"]), { 0: ["w5@4", 1], length: 1 }]) bad(request({ owned }));
      // eslint-disable-next-line no-sparse-arrays
      bad(request({ owned: [["w5@4", 1], , ["w6@4", 1]] }));
      bad(request({ owned: [new Array(2)] })); // an entry that is two holes
      const extra = [["w5@4", 1]];
      extra.note = "x";
      expect(() => validateRequest(request({ owned: extra }))).not.toThrow(); // (a list is read by its length: what is on it besides is not carried over)
      expect(Object.keys(validateRequest(request({ owned: extra })).owned)).toEqual(["0"]);
    });

    it("an owned set or an entry with an accessor, which could show one value to the check and another to the sender", () => {
      let reads = 0;
      const entry = ["w5@4", 1];
      Object.defineProperty(entry, 0, { enumerable: true, get: () => ((reads += 1), "w5@4") });
      bad(request({ owned: [entry] }));
      const sneaky = request();
      Object.defineProperty(sneaky, "owned", { enumerable: true, get: () => ((reads += 1), []) });
      bad(sneaky);
      expect(reads).toBeLessThanOrEqual(1);
    });

    it("a scenario that is not a plain object", () => {
      for (const value of [[], "OGR", 5, null, undefined, true, new Map(), Object.create({ race: "OGR" })]) bad(request({ scenario: value }));
    });

    it("a scenario with a field that is not one of the five and the deity", () => {
      for (const extra of ["tier", "mode", "url", "wasmUrl", "owned", "haste_assumed", "weights", "candidates", "constructor", "prototype", "RACE", "race ", ""]) {
        bad(scenario({ [extra]: "x" }));
      }
      const poisoned = request();
      poisoned.scenario = JSON.parse('{"race": "OGR", "role": "balanced", "buffs": "own", "evidence": "wiki", "setup": "dw", "__proto__": {"race": "HUM"}}');
      bad(poisoned);
    });

    it("a scenario with a field missing", () => {
      for (const field of ["race", "role", "buffs", "evidence", "setup"]) {
        const missing = request();
        delete missing.scenario[field];
        bad(missing);
        bad(scenario({ [field]: undefined }));
      }
      bad(request({ scenario: {} }));
    });

    const BAD_NAMES = {
      "a name that is empty": [""],
      "a name that is not text": [5, null, undefined, true, ["OGR"], { name: "OGR" }, 5n, Symbol("x")],
      "a name that is long": ["A".repeat(LIMITS.maxNameLength + 1), "a".repeat(1000), "o".repeat(100_000)],
      "a name with a slash or a colon or a backslash, which an address has": ["a/b", "https://evil.example", "//evil.example", "..", "../x", "a\\b", "javascript:alert(1)", "a:b"],
      "a name with a character that is not a plain sign": ["O\u0000R", "OGR\n", "OG\tR", "OGR​", "‮OGR", "OGé", "OGR ", "OGR\u007f", "<b>x</b>", "a;b", "a,b", "a(b)", 'a"b', "a'b", "a=b", "a%41"],
      "a name with a space at the start, or a sign at the start": [" OGR", "-OGR", "+OGR", ".OGR", "_OGR"],
      "a name that is a prototype word with its sign": ["__proto__"],
    };
    for (const field of ["race", "role", "buffs", "evidence", "setup", "deity"]) {
      for (const [name, values] of Object.entries(BAD_NAMES)) {
        it(`${name} for the ${field}`, () => {
          for (const value of values) {
            if (field === "deity" && (value === null || value === undefined)) continue; // null and none are the deity's own choices
            bad(scenario({ [field]: value }));
          }
        });
      }
    }

    it("a field of the request that is not one of its own: a candidate list, an address, a manifest, a second scenario", () => {
      for (const extra of [{ candidates: [] }, { candidates: [["w5@4", 1]] }, { url: "/x" }, { wasmUrl: "/x" }, { href: "//evil.example" }, { manifest: {} }, { steps: 8 }, { items: [] }, { bundle: {} }, { model: {} }]) {
        bad(request(extra));
      }
    });

    it("a request with the scenario, the owned set or the mode missing, or the mode in other letters", () => {
      const missing = (field) => {
        const value = request();
        delete value[field];
        return value;
      };
      bad(missing("scenario"));
      bad(missing("owned"));
      bad(missing("trio"));
      bad(missing("level"));
      bad(missing("budgetMs"));
      for (const mode of ["Equip-Now", "equip_now", "equip-now ", " equip-now", "equip-now\n", "EQUIP-NOW"]) {
        // not this mode: the generic scenario checks apply, and these are not the generic mode name either
        bad(request({ mode }));
      }
    });

    it("a budget that is not a whole number of milliseconds in range", () => {
      for (const budgetMs of [0, -1, 1.5, "5000", null, undefined, LIMITS.maxBudgetMs + 1, Number.NaN, Infinity]) bad(request({ budgetMs }));
      expect(validateRequest(request({ budgetMs: 1 })).budgetMs).toBe(1);
      expect(validateRequest(request({ budgetMs: LIMITS.maxBudgetMs })).budgetMs).toBe(LIMITS.maxBudgetMs);
    });

    it("the same requests when they arrive as a message to the worker", () => {
      expect(validateToWorker({ v: 1, type: "solve", id: 3, request: request() }).request.mode).toBe("equip-now");
      for (const hostile of [request({ owned: [["__proto__@4", 1]] }), request({ owned: [["w5@11", 1]] }), scenario({ race: "x".repeat(60) }), request({ candidates: [] })]) {
        expect(() => validateToWorker({ v: 1, type: "solve", id: 3, request: hostile })).toThrow(/bad-request/);
      }
    });
  });

  it("does not keep the generic shape of the other modes: any short mode name, a scenario of any plain data, candidates, a request with no mode are bad requests", () => {
    const other = { v: 1, kind: "scenario", trio: "pal-mnk-ber", level: 50, scenario: { race: "OGR", role: "balanced", tier: 4 }, owned: [[1234, 4, 1]], candidates: [], mode: "equip", budgetMs: 5000 };
    bad(other, MANIFEST);
    bad({ ...other, mode: "farm-path" }, MANIFEST); // (its own shape has a tier mode and steps, and no candidates)
    const { mode, candidates, ...bare } = other;
    bad(bare, MANIFEST); // a scenario request names its mode
    bad({ ...bare, mode: "equipnow" }, MANIFEST); // another short name is not a mode
  });
});

describe("the answer to a request for Equip now", () => {
  const OWNED = [["w90001@4", 1], ["w90007@4", 2], ["w80113@0", 1]];
  const expectation = { id: 4, kind: "scenario", mode: "equip-now", owned: OWNED };
  const KIT = ["w90001@4", null, "w90007@4", "w90007@4", ...new Array(17).fill(null), "w80113@0"];
  const reply = (over = {}) => ({
    v: 1,
    type: "result",
    id: 4,
    kind: "scenario",
    mode: "equip-now",
    status: "optimal",
    proven: true,
    label: null,
    F: "73440556337/4400000",
    value: 73440556337 / 4400000,
    kit: [...KIT],
    buffs: [43, 1453],
    hasteAssumed: 40,
    elapsedMs: 12.5,
    ...over,
  });

  it("is accepted, as a copy, with the exact value as a reduced p/q text and its number", () => {
    const original = reply();
    const clean = validateFromWorker(original, expectation);
    expect(clean).toEqual(original);
    expect(clean.kit).not.toBe(original.kit);
    expect(clean.buffs).not.toBe(original.buffs);
    expect(validateFromWorker(reply({ F: "5/1", value: 5 }), expectation).F).toBe("5/1"); // a whole number is 5/1, as the Python side writes it
    expect(validateFromWorker(reply({ F: "-7/2", value: -3.5 }), expectation).value).toBe(-3.5);
    expect(validateFromWorker(reply({ F: "0/1", value: 0 }), expectation).value).toBe(0);
  });

  it("is accepted without an owned list in the expectation, and with an owned list as a Map or a list of pairs", () => {
    expect(validateFromWorker(reply(), { id: 4, kind: "scenario", mode: "equip-now" }).status).toBe("optimal");
    expect(validateFromWorker(reply(), { ...expectation, owned: new Map(OWNED) }).status).toBe("optimal");
  });

  it("has no kit and no value when no kit was found in time, and says so with its label", () => {
    const none = reply({ status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT, F: null, value: null, kit: null, buffs: [] });
    expect(validateFromWorker(none, expectation)).toEqual(none);
    const some = reply({ status: "time_limit", proven: false, label: LABEL_TIME_LIMIT });
    expect(validateFromWorker(some, expectation).label).toBe(LABEL_TIME_LIMIT);
    const infeasible = reply({ status: "infeasible", proven: true, label: null, F: null, value: null, kit: null, buffs: [] });
    expect(validateFromWorker(infeasible, expectation).status).toBe("infeasible");
  });

  it("may name no place at all: a kit of 22 empty places is a kit (the naked character)", () => {
    const naked = reply({ kit: new Array(22).fill(null), buffs: [] });
    expect(validateFromWorker(naked, expectation).kit).toHaveLength(22);
  });

  const BAD = {
    "a reply for another request": reply({ id: 5 }),
    "a reply with no id": reply({ id: undefined }),
    "a reply of the kind model": reply({ kind: "model" }),
    "a reply with no kind": reply({ kind: undefined }),
    "a reply for another mode": reply({ mode: "farm-path" }),
    "a reply with no mode": reply({ mode: undefined }),
    "a reply with an extra field": reply({ url: "/x" }),
    "a reply with an extra field of a model result": reply({ x: [1] }),
    "a reply with the fields of a model result (a kit in x)": { v: 1, type: "result", id: 4, kind: "scenario", mode: "equip-now", status: "optimal", proven: true, objective: 3, x: [1], bound: 3, gap: 0, nodes: 0, elapsedMs: 1, label: null },
    "an unknown status": reply({ status: "maybe" }),
    "an optimal result that is not proven": reply({ proven: false }),
    "a proven result that is not a truth value": reply({ proven: "yes" }),
    "an optimal result with a label": reply({ label: LABEL_TIME_LIMIT }),
    "an optimal result without a kit": reply({ kit: null }),
    "an optimal result without a value": reply({ F: null, value: null }),
    "a time-limited result that claims to be proven": reply({ status: "time_limit", proven: true, label: LABEL_TIME_LIMIT }),
    "a time-limited result without its label": reply({ status: "time_limit", proven: false, label: null }),
    "a time-limited result with another label": reply({ status: "time_limit", proven: false, label: "optimal" }),
    "a time-limited result with a kit under the label for none": reply({ status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT }),
    "a time-limited result with no kit under the label for one": reply({ status: "time_limit", proven: false, label: LABEL_TIME_LIMIT, F: null, value: null, kit: null }),
    "a time-limited result with a kit and no value": reply({ status: "time_limit", proven: false, label: LABEL_TIME_LIMIT, F: null, value: null }),
    "a time-limited result with a value and no kit": reply({ status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT, kit: null }),
    "an infeasible result with a kit": reply({ status: "infeasible", F: null, value: null, buffs: [] }),
    "an infeasible result that is not proven": reply({ status: "infeasible", proven: false, F: null, value: null, kit: null, buffs: [] }),
    "no kit but some buffs": reply({ status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT, F: null, value: null, kit: null }),
    "an exact value that is a bare number": reply({ F: 5 }),
    "an exact value that is not reduced": reply({ F: "10/4", value: 2.5 }),
    "an exact value with a zero denominator": reply({ F: "1/0", value: 0 }),
    "an exact value with a plus sign": reply({ F: "+5/1", value: 5 }),
    "an exact value with a space": reply({ F: " 5/1", value: 5 }),
    "an exact value in decimals": reply({ F: "2.5", value: 2.5 }),
    "an exact value that is not text": reply({ F: ["5", "1"], value: 5 }),
    "an exact value that is very long": reply({ F: `${"9".repeat(5000)}/1`, value: 5 }),
    "an exact value that is not the number beside it": reply({ F: "5/2", value: 2.6 }),
    "a number beside the exact value that is NaN": reply({ F: "5/2", value: Number.NaN }),
    "a number beside the exact value that is Infinity": reply({ F: "5/2", value: Infinity }),
    "a number beside the exact value that is text": reply({ F: "5/2", value: "2.5" }),
    "a kit of 21 places": reply({ kit: KIT.slice(0, 21) }),
    "a kit of 23 places": reply({ kit: [...KIT, null] }),
    "a kit that is an object": reply({ kit: { 0: "w90001@4", length: 22 } }),
    "a kit with a number in it": reply({ kit: [5, ...KIT.slice(1)] }),
    "a kit with an item that is no ident": reply({ kit: ["w90001", ...KIT.slice(1)] }),
    "a kit with a prototype word for an ident": reply({ kit: ["__proto__@4", ...KIT.slice(1)] }),
    "a kit with an ident of a tier above 10": reply({ kit: ["w90001@11", ...KIT.slice(1)] }),
    "a kit with an ident that is an address": reply({ kit: ["https://evil.example/x@4", ...KIT.slice(1)] }),
    "a kit with a hole in it": reply({ kit: [undefined, ...KIT.slice(1)] }),
    "a kit with an item that is not owned": reply({ kit: ["w99999@4", ...KIT.slice(1)] }),
    "a kit with an item owned at another tier": reply({ kit: ["w90001@5", ...KIT.slice(1)] }),
    "a kit with more copies of an item than are owned": reply({ kit: ["w90001@4", "w90001@4", ...KIT.slice(2)] }),
    "buffs that are not a list": reply({ buffs: { 0: 43 } }),
    "buffs with a number that is not whole": reply({ buffs: [43.5] }),
    "buffs with a text": reply({ buffs: ["43"] }),
    "buffs with a number beyond what a double holds exactly": reply({ buffs: [2 ** 53] }),
    "buffs out of order": reply({ buffs: [1453, 43] }),
    "buffs with one twice": reply({ buffs: [43, 43] }),
    "buffs, more of them than there can be": reply({ buffs: Array.from({ length: LIMITS.maxBuffs + 1 }, (_, n) => n) }),
    "no buffs field": reply({ buffs: undefined }),
    "a haste that is not whole": reply({ hasteAssumed: 40.5 }),
    "a haste below 0": reply({ hasteAssumed: -1 }),
    "a haste above any cap": reply({ hasteAssumed: 1001 }),
    "a haste in text": reply({ hasteAssumed: "40" }),
    "no haste": reply({ hasteAssumed: undefined }),
    "an elapsed time below 0": reply({ elapsedMs: -1 }),
    "an elapsed time that is NaN": reply({ elapsedMs: Number.NaN }),
    "an elapsed time in text": reply({ elapsedMs: "12" }),
    "a label that is not text": reply({ status: "time_limit", proven: false, label: 5 }),
    "a version in text": reply({ v: "1" }),
    "another version": reply({ v: 2 }),
  };
  for (const [name, value] of Object.entries(BAD)) {
    it(`refuses ${name}`, () => {
      expect(() => validateFromWorker(value, expectation)).toThrow(/protocol/);
    });
  }

  it("refuses a result of this kind when the request in flight was for a model, and the other way round", () => {
    expect(() => validateFromWorker(reply(), { id: 4, kind: "model", columns: 3 })).toThrow(/protocol/);
    expect(() => validateFromWorker(reply(), { id: 4, kind: "scenario", mode: "farm-path" })).toThrow(/protocol/);
    expect(() => validateFromWorker(reply(), { id: 4 })).toThrow(/protocol/); // it must be known what was asked
    const model = { v: 1, type: "result", id: 4, kind: "model", status: "optimal", proven: true, objective: 37, x: [1, 0, 1], bound: 37, gap: 0, nodes: 3, elapsedMs: 12, label: null };
    expect(() => validateFromWorker(model, expectation)).toThrow(/protocol/);
    expect(validateFromWorker(model, { id: 4, kind: "model", columns: 3 }).kind).toBe("model");
  });

  it("refuses a result with an accessor, which could show one value to the check and another to the page", () => {
    const sneaky = reply();
    let reads = 0;
    Object.defineProperty(sneaky, "F", { enumerable: true, get: () => ((reads += 1), "5/1") });
    expect(() => validateFromWorker(sneaky, expectation)).toThrow(/protocol/);
    expect(reads).toBe(0);
  });

  it("takes an error for the request, with its code, as any request's", () => {
    expect(validateFromWorker({ v: 1, type: "error", id: 4, code: "bad-request", message: "An owned item is not in the item table." }, expectation).code).toBe("bad-request");
    expect(validateFromWorker({ v: 1, type: "error", id: 4, code: "engine-load", message: "The optimizer's data could not be loaded." }, expectation).code).toBe("engine-load");
  });

  it("takes the progress of loading the data, a report with a size and a total, for the request", () => {
    const report = { v: 1, type: "progress", id: 4, phase: "loading", loaded: 10, total: 20 };
    expect(validateFromWorker(report, expectation)).toEqual(report);
    expect(() => validateFromWorker({ ...report, loaded: 21 }, expectation)).toThrow(/protocol/);
  });
});
