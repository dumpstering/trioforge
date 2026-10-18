// The scenario request of mode "best-kit" and its answer, checked in both directions (protocol.js): what the page sends the worker, and what the worker sends back. The best kit
// is the best kit of a view of the trio page, solved over the whole pool of the view as the precompute solves it: there is no owned list and no candidates, the worker makes the pool.
//
//   {v, kind: "scenario", trio, level, mode: "best-kit", scenario: {race, role, buffs, evidence, setup, deity?}, tier, weights?, budgetMs}
//
// `tier` is a whole number from 0 to 10; `weights` is {multipliers?, custom?, regenT?}: the sliders' positions by group, the custom weights by name and the regen window. The protocol
// checks the shape of the weights (an allowlist of the three options, names and numbers, sizes); which groups, positions, names and bounds are allowed is the bundle's
// (weight_groups, regen_ratios), and the worker holds the request to them with weightsOverride. The answer is that of Equip now ({status, proven, label, F, value, kit, buffs,
// hasteAssumed, elapsedMs}), held to the same rules, except that no owned set bounds the kit: the kit wears only items of the pool, which is all at the tier of the request.

import { describe, expect, it } from "vitest";
import { parseManifest } from "../pipeline/trioforge/site/static/engine/manifest.js";
import { LABEL_NO_INCUMBENT, LABEL_TIME_LIMIT, LIMITS, SCENARIO_MODES, STAGES, validateFromWorker, validateRequest, validateToWorker } from "../pipeline/trioforge/site/static/engine/protocol.js";

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
const request = (over = {}) => ({ v: 1, kind: "scenario", trio: "pal-mnk-ber", level: 50, mode: "best-kit", scenario: { ...SCENARIO }, tier: 4, budgetMs: 5000, ...over });
const weighted = (weights, over = {}) => request({ weights, ...over });
const scenario = (over) => request({ scenario: { ...SCENARIO, ...over } });
const bad = (value, manifest) => expect(() => validateRequest(value, manifest)).toThrow(/bad-request/);
const without = (field) => {
  const value = request({ weights: { regenT: 3 } });
  delete value[field];
  return value;
};

describe("the modes and the stages", () => {
  it("are five, the best kit the fifth, and it has the stage of its own", () => {
    expect(SCENARIO_MODES).toEqual(["equip-now", "farm-path", "best-sets", "every-slot", "best-kit"]);
    expect(STAGES).toEqual(["loading", "equip-now", "step", "best-sets", "every-slot", "best-kit"]);
  });
});

describe("a request for the best kit", () => {
  it("is accepted with or without weights, and a detached copy of it is what is sent", () => {
    const original = weighted({ multipliers: { AC: 2, "ATK+HASTE": 0.5 }, custom: { HP: 3, SV_FIRE: 0.25 }, regenT: 10 });
    const clean = validateRequest(original, MANIFEST);
    expect(clean).toEqual(original);
    expect(clean).not.toBe(original);
    for (const part of ["scenario", "weights"]) expect(clean[part]).not.toBe(original[part]);
    for (const part of ["multipliers", "custom"]) expect(clean.weights[part]).not.toBe(original.weights[part]);
    original.weights.multipliers.AC = 0.5;
    original.weights.custom.HP = 999;
    original.weights.regenT = 60;
    original.scenario.race = "HUM";
    original.tier = 9;
    expect(clean.weights).toEqual({ multipliers: { AC: 2, "ATK+HASTE": 0.5 }, custom: { HP: 3, SV_FIRE: 0.25 }, regenT: 10 }); // what was checked is what is sent
    expect([clean.scenario.race, clean.tier]).toEqual(["OGR", 4]);
    const plain = validateRequest(request(), MANIFEST);
    expect(plain).toEqual(request());
    expect("weights" in plain).toBe(false);
    expect("owned" in plain).toBe(false);
  });

  it("has no owned list, no candidates and no tier mode: it is the pool of the view, and the worker makes it", () => {
    for (const extra of [
      { owned: [] },
      { owned: [["w90001@4", 1]] },
      { candidates: [] },
      { candidates: [["w90001@4", 1]] },
      { tierMode: { mode: "ready4" } },
      { steps: 3 },
      { k: 2 },
      { kit: new Array(22).fill(null) },
      { buffs: [43] },
      { limit: 3 },
    ]) {
      bad(request(extra));
    }
  });

  it("has an allowlist: nothing but its own fields, so that no address, no manifest and no later option slips in (lock and exclude are not in it yet)", () => {
    for (const extra of ["url", "wasmUrl", "href", "manifest", "items", "bundle", "model", "scenarios", "canonical", "owned2", "mode2", "id", "lock", "exclude", "locks", "excludes", "pool", "deity", "regenT", "multipliers", "custom"]) {
      bad(request({ [extra]: "x" }));
      bad(request({ [extra]: [] }));
    }
    for (const poisoned of ['{"__proto__": {"tier": 3}}', '{"constructor": 1}']) {
      bad({ ...request(), ...JSON.parse(poisoned) });
    }
  });

  it("needs a scenario and a tier, and the weights are the only field it may do without", () => {
    for (const field of ["scenario", "tier", "trio", "level", "budgetMs", "mode"]) {
      const value = request();
      delete value[field];
      bad(value);
    }
    expect(validateRequest(without("weights")).tier).toBe(4);
  });

  it("takes the tiers 0 to 10, and no other number and nothing that is not a number", () => {
    for (const tier of [0, 1, 4, 9, 10]) expect(validateRequest(request({ tier })).tier).toBe(tier);
    for (const tier of [-1, 11, 12, 100, 1.5, 0.5, 4.0000001, "4", "0", null, undefined, true, false, Number.NaN, Infinity, -Infinity, [4], { tier: 4 }, 4n, Symbol("x")]) bad(request({ tier }));
  });

  it("keeps the checks of the other modes on the scenario, and takes the buff sets of the bundle", () => {
    expect(Object.keys(validateRequest(scenario({ deity: "Karana" })).scenario)).toEqual(["race", "role", "buffs", "evidence", "setup", "deity"]);
    expect(validateRequest(scenario({ deity: null })).scenario.deity).toBeNull();
    for (const buffs of ["own", "group", "group+enchanter", "raid"]) expect(validateRequest(scenario({ buffs })).scenario.buffs).toBe(buffs);
    for (const field of ["race", "role", "buffs", "evidence", "setup"]) {
      for (const value of ["", "a/b", "https://evil.example", "A".repeat(LIMITS.maxNameLength + 1), "O\u0000R", 5, null, undefined]) bad(scenario({ [field]: value }));
      const missing = request();
      delete missing.scenario[field];
      bad(missing);
    }
    for (const extra of ["tier", "weights", "owned", "mode", "url", "manaReachable"]) bad(scenario({ [extra]: "x" }));
    bad(request({ scenario: [] }));
    bad(request({ scenario: null }));
    bad(request({ budgetMs: 0 }));
    bad(request({ budgetMs: LIMITS.maxBudgetMs + 1 }));
    expect(validateRequest(request({ budgetMs: LIMITS.maxBudgetMs })).budgetMs).toBe(LIMITS.maxBudgetMs);
  });

  it("is checked against the manifest: a trio and a level it lists", () => {
    expect(() => validateRequest(request(), MANIFEST)).not.toThrow();
    for (const over of [{ trio: "war-war-war" }, { trio: "constructor" }, { level: 49 }, { level: 55 }, { level: "50" }]) bad(request(over), MANIFEST);
  });

  describe("has weights that are", () => {
    it("the three options, each a table or a number: the sliders by group, the custom weights by name, the regen window", () => {
      const ok = [
        {},
        { multipliers: {} },
        { custom: {} },
        { regenT: 0 },
        { regenT: 60 },
        { regenT: 2.5 },
        { regenT: null },
        { multipliers: { AC: 2 } },
        { multipliers: { AC: 0.5, MANA: 1, "ATK+HASTE": 2, SV: 1, regen: 0.5 } },
        { custom: { HP: 3 } },
        { custom: { SV: 0, SV_FIRE: 1000, HASTE: 0.05, CHA: 10 } },
        { multipliers: { regen: 2 }, regenT: 10 },
        { multipliers: { AC: 2 }, custom: { HP: 3 }, regenT: 10 },
      ];
      for (const weights of ok) expect(validateRequest(weighted(weights)).weights, JSON.stringify(weights)).toEqual(weights);
    });

    it("checked for their shape and not for their bounds: which groups there are, which positions, which names and how large is the bundle's, and the worker holds the request to them", () => {
      // (weights.js reads them from weight_groups, regen_ratios and constants of the bundle; the protocol has no bundle)
      const shapely = { multipliers: { NOPE: 7 }, custom: { ZZZ: 5000, HP: -1 }, regenT: 99 };
      expect(validateRequest(weighted(shapely)).weights).toEqual(shapely);
    });

    it("refused when they are not a plain object, or have an option that is not one of the three: the mana flag is the worker's, never the page's", () => {
      for (const weights of [[], [{ regenT: 3 }], "regenT", 5, null, undefined, true, new Map(), new Set(), Object.create({ regenT: 3 }), () => ({})]) bad(weighted(weights));
      for (const extra of ["manaReachable", "mana_reachable", "regen_T", "regenTime", "multiplier", "Multipliers", "CUSTOM", "canonical", "lock", "exclude", "url", "__proto__", "constructor", "prototype", ""]) {
        bad(weighted({ [extra]: true }));
        bad(weighted({ regenT: 3, [extra]: {} }));
        bad(weighted({ [extra]: 1 }));
      }
      bad(weighted({ manaReachable: false, multipliers: { MANA: 2 } }));
      bad(weighted({ multipliers: { AC: 2 }, regenT: undefined })); // a field that is given is read: undefined is not a number
      bad(weighted({ multipliers: undefined }));
      bad(weighted(JSON.parse('{"__proto__": {"regenT": 3}}')));
    });

    for (const table of ["multipliers", "custom"]) {
      it(`refused when the ${table} are not a plain table of names and finite numbers`, () => {
        for (const value of [[], [["AC", 2]], "AC", 2, null, undefined, true, new Map([["AC", 2]]), Object.create({ AC: 2 }), () => ({})]) bad(weighted({ [table]: value }));
        for (const number of ["2", "0.5", "", null, undefined, true, false, [2], { x: 2 }, Number.NaN, Infinity, -Infinity, 2n, Symbol("x")]) bad(weighted({ [table]: { AC: number } }));
        for (const name of ["", "a/b", "a\\b", "https://evil.example", "..", "A".repeat(LIMITS.maxNameLength + 1), "O\u0000R", " AC", "A\nC", "A C", "AC ", "é", "a;b", "__proto__", "constructor", "prototype", "+AC", "-AC"]) {
          bad(weighted({ [table]: { [name]: 2 } }));
        }
        bad(weighted({ [table]: JSON.parse('{"__proto__": 2}') }));
        // names with the signs the bundle's names have: a plus sign (ATK+HASTE), an underscore (SV_FIRE)
        for (const name of ["ATK+HASTE", "SV_FIRE", "regen", "AC", "A".repeat(LIMITS.maxNameLength)]) expect(validateRequest(weighted({ [table]: { [name]: 2 } })).weights[table][name]).toBe(2);
      });

      it(`refused when the ${table} have more entries than there are groups and weights to name`, () => {
        const most = Object.fromEntries(Array.from({ length: LIMITS.maxWeightEntries }, (_, at) => [`W${at}`, 1]));
        expect(Object.keys(validateRequest(weighted({ [table]: most })).weights[table])).toHaveLength(LIMITS.maxWeightEntries);
        bad(weighted({ [table]: { ...most, TOO: 1 } }));
        bad(weighted({ [table]: Object.fromEntries(Array.from({ length: 10_000 }, (_, at) => [`W${at}`, 1])) }));
      });
    }

    it("refused when the regen window is anything but a finite number or null", () => {
      for (const regenT of ["10", "", true, false, [10], { regenT: 10 }, Number.NaN, Infinity, -Infinity, 10n, Symbol("x"), undefined]) bad(weighted({ regenT }));
    });

    describe("numbers that are zero, or not too small and not too fine: at least 0.000001 in size and of at most 6 significant digits", () => {
      // The exact value of an answer is a p/q text of at most 200 characters (LIMITS.maxExactLength), and a weight is read as the decimal it prints as, so the digits of the weights
      // set the size of the fraction: a custom weight of 5e-324 makes it 657 characters and a regen window of 1e-100 209, and the page drops a worker that answers with a text that
      // long. The floor and the digits are the protocol's, for the sliders, the custom weights and the window alike; the bundle's own bounds are the worker's to check.
      const PLACES = {
        "a slider position": (value) => weighted({ multipliers: { AC: value } }),
        "a custom weight": (value) => weighted({ custom: { HP: value } }),
        "the regen window": (value) => weighted({ regenT: value }),
      };
      const THE_WORKER = (value) => validateToWorker({ v: 1, type: "solve", id: 3, request: value });

      it("refuse the two weights that made an exact value too long to be read: a custom weight of 5e-324 and a regen window of 1e-100", () => {
        for (const hostile of [weighted({ custom: { HP: 5e-324 } }), weighted({ regenT: 1e-100 })]) {
          expect(() => validateRequest(hostile, MANIFEST), "the page").toThrow(/bad-request/);
          expect(() => THE_WORKER(hostile), "the worker").toThrow(/bad-request/);
        }
        expect(LIMITS.maxExactLength).toBe(200);
      });

      for (const [place, build] of Object.entries(PLACES)) {
        it(`take, for ${place}, zero and the floor itself, and no number below it, whatever its sign`, () => {
          for (const value of [0, -0, 1e-6, 0.000001, 1.5e-6, 1e-5, 0.001, 0.5, 1, 2, 60, 1000]) expect(() => validateRequest(build(value)), String(value)).not.toThrow();
          for (const value of [9.99999e-7, 5e-7, 1e-7, 1e-9, 1e-100, 1e-300, Number.MIN_VALUE, 5e-324, -9.99999e-7, -1e-7, -5e-324]) {
            bad(build(value));
            expect(() => THE_WORKER(build(value)), String(value)).toThrow(/bad-request/);
          }
        });

        it(`take, for ${place}, six significant digits and no more: 1.23457 and 123.456 and 0.123456 but not 1.234567 or 0.30000000000000004`, () => {
          for (const value of [1, 0.1, 0.5, 1.5, 1.23457, 12.3456, 123.456, 0.123456, 999.999, 1.00001, 0.000123457, 1.23457e-6, 654321]) expect(() => validateRequest(build(value)), String(value)).not.toThrow();
          for (const value of [1.234567, 0.1234567, 1000.001, 123456.7, 1234567, 0.30000000000000004, 0.1 + 0.2, Math.PI, 1 / 3, 2 / 3, 1.0000001, 9.999999e-3, 1.234567e-6]) {
            bad(build(value));
            expect(() => THE_WORKER(build(value)), String(value)).toThrow(/bad-request/);
          }
        });
      }

      it("say what the rule is, in words, and name no number that the visitor did not give", () => {
        for (const value of [5e-324, 1.234567]) {
          try {
            validateRequest(weighted({ custom: { HP: value } }));
            expect.unreachable("a number the rule refuses");
          } catch (error) {
            expect(error.code).toBe("bad-request");
            expect(error.message).toMatch(/0\.000001/);
            expect(error.message).toMatch(/6 significant digits/);
            expect(error.message.length).toBeLessThan(LIMITS.maxMessageLength);
            expect(error.message).not.toMatch(/[\u0000-\u001f]/);
          }
        }
      });

      it("do not touch the tables' other rules: a name that is not short, a number that is not finite and the allowlist are refused as they were", () => {
        bad(weighted({ custom: { "a/b": 1 } }));
        bad(weighted({ custom: { HP: Number.NaN } }));
        bad(weighted({ regenT: Infinity }));
        bad(weighted({ manaReachable: true }));
      });
    });

    it("refused when a table or the weights carry an accessor, which could show one value to the check and another to the worker", () => {
      let reads = 0;
      const sneaky = { AC: 2 };
      Object.defineProperty(sneaky, "SV", { enumerable: true, get: () => ((reads += 1), 2) });
      bad(weighted({ multipliers: sneaky }));
      const weights = { regenT: 3 };
      Object.defineProperty(weights, "custom", { enumerable: true, get: () => ((reads += 1), {}) });
      bad(weighted(weights));
      const hidden = { regenT: 3 };
      Object.defineProperty(hidden, "multipliers", { enumerable: false, value: { AC: 2 } });
      bad(weighted(hidden)); // a property that is not listed is not plain data either
      const mine = request();
      Object.defineProperty(mine, "weights", { enumerable: true, get: () => ((reads += 1), {}) });
      bad(mine);
      expect(reads).toBe(0);
    });

    it("copied into tables that have no prototype to poison", () => {
      const clean = validateRequest(weighted({ multipliers: { AC: 2 }, custom: { HP: 3 } })).weights;
      for (const table of [clean.multipliers, clean.custom]) expect(Object.getPrototypeOf(table) === null || Object.getPrototypeOf(table) === Object.prototype).toBe(true);
      expect(Object.keys(validateRequest(weighted({})).weights)).toEqual([]);
    });
  });

  it("reaches the worker as a message, and the hostile ones do not", () => {
    expect(validateToWorker({ v: 1, type: "solve", id: 3, request: weighted({ multipliers: { AC: 2 } }) }).request.mode).toBe("best-kit");
    for (const hostile of [request({ tier: 11 }), request({ owned: [] }), weighted({ manaReachable: true }), weighted({ multipliers: { __proto__x: 2, "a/b": 1 } }), scenario({ race: "x".repeat(60) })]) {
      expect(() => validateToWorker({ v: 1, type: "solve", id: 3, request: hostile })).toThrow(/bad-request/);
    }
  });

  it("is not a request of another mode when the mode is in other letters", () => {
    for (const mode of ["Best-Kit", "best_kit", "best-kit ", " best-kit", "bestkit", "best-kits", "BEST-KIT", "best-kit\n"]) bad(request({ mode }));
  });
});

describe("the answer to a request for the best kit", () => {
  const expectation = { id: 4, kind: "scenario", mode: "best-kit" };
  const KIT = ["w90003@4", "w80816@4", "w90009@4", "w90009@4", ...new Array(17).fill(null), "w80113@4"];
  const reply = (over = {}) => ({
    v: 1,
    type: "result",
    id: 4,
    kind: "scenario",
    mode: "best-kit",
    status: "optimal",
    proven: true,
    label: null,
    F: "41952357833/2200000",
    value: 41952357833 / 2200000,
    kit: [...KIT],
    buffs: [1453],
    hasteAssumed: 44,
    elapsedMs: 12.5,
    ...over,
  });

  it("is accepted, as a copy, with the exact value as a reduced p/q text and its number", () => {
    const original = reply();
    const clean = validateFromWorker(original, expectation);
    expect(clean).toEqual(original);
    expect(clean.kit).not.toBe(original.kit);
    expect(clean.buffs).not.toBe(original.buffs);
    expect(validateFromWorker(reply({ F: "5/1", value: 5 }), expectation).F).toBe("5/1");
    expect(validateFromWorker(reply({ F: "0/1", value: 0 }), expectation).value).toBe(0);
  });

  it("is accepted with the tier of the request in the expectation, and without it (the page's client does not name the tier yet)", () => {
    expect(validateFromWorker(reply(), { ...expectation, tier: 4 }).status).toBe("optimal");
    expect(validateFromWorker(reply(), expectation).status).toBe("optimal");
  });

  it("wears an item as often as it likes: the pool has no count, and a kit of one item in every place is a kit", () => {
    const worn = reply({ kit: new Array(22).fill("w90003@4") });
    expect(validateFromWorker(worn, { ...expectation, tier: 4 }).kit).toHaveLength(22);
  });

  it("has no kit and no value when no kit was found in time, and says so with its label", () => {
    const none = reply({ status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT, F: null, value: null, kit: null, buffs: [] });
    expect(validateFromWorker(none, { ...expectation, tier: 4 })).toEqual(none);
    expect(validateFromWorker(reply({ status: "time_limit", proven: false, label: LABEL_TIME_LIMIT }), expectation).label).toBe(LABEL_TIME_LIMIT);
    const infeasible = reply({ status: "infeasible", proven: true, label: null, F: null, value: null, kit: null, buffs: [] });
    expect(validateFromWorker(infeasible, expectation).status).toBe("infeasible");
  });

  it("may name no place at all: a kit of 22 empty places is a kit (the naked character, when the pool has nothing to wear)", () => {
    expect(validateFromWorker(reply({ kit: new Array(22).fill(null), buffs: [] }), { ...expectation, tier: 7 }).kit).toHaveLength(22);
  });

  const BAD = {
    "a reply for another request": reply({ id: 5 }),
    "a reply with no id": reply({ id: undefined }),
    "a reply of the kind model": reply({ kind: "model" }),
    "a reply with no kind": reply({ kind: undefined }),
    "a reply for another mode": reply({ mode: "equip-now" }),
    "a reply for the farm path": reply({ mode: "farm-path" }),
    "a reply for the best sets": reply({ mode: "best-sets" }),
    "a reply for Every slot": reply({ mode: "every-slot" }),
    "a reply with no mode": reply({ mode: undefined }),
    "a reply with an extra field": reply({ url: "/x" }),
    "a reply with the owned set of Equip now": reply({ owned: [] }),
    "a reply with the tier": reply({ tier: 4 }),
    "a reply with the weights": reply({ weights: {} }),
    "a reply with the fields of a model result": { v: 1, type: "result", id: 4, kind: "scenario", mode: "best-kit", status: "optimal", proven: true, objective: 3, x: [1], bound: 3, gap: 0, nodes: 0, elapsedMs: 1, label: null },
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
    "an exact value in decimals": reply({ F: "2.5", value: 2.5 }),
    "an exact value that is very long": reply({ F: `${"9".repeat(5000)}/1`, value: 5 }),
    "an exact value that is not the number beside it": reply({ F: "5/2", value: 2.6 }),
    "a number beside the exact value that is NaN": reply({ F: "5/2", value: Number.NaN }),
    "a number beside the exact value that is text": reply({ F: "5/2", value: "2.5" }),
    "a kit of 21 places": reply({ kit: KIT.slice(0, 21) }),
    "a kit of 23 places": reply({ kit: [...KIT, null] }),
    "a kit that is an object": reply({ kit: { 0: "w90003@4", length: 22 } }),
    "a kit with a number in it": reply({ kit: [5, ...KIT.slice(1)] }),
    "a kit with an item that is no ident": reply({ kit: ["w90003", ...KIT.slice(1)] }),
    "a kit with a prototype word for an ident": reply({ kit: ["__proto__@4", ...KIT.slice(1)] }),
    "a kit with an ident of a tier above 10": reply({ kit: ["w90003@11", ...KIT.slice(1)] }),
    "a kit with an ident that is an address": reply({ kit: ["https://evil.example/x@4", ...KIT.slice(1)] }),
    "a kit with a hole in it": reply({ kit: [undefined, ...KIT.slice(1)] }),
    "buffs that are not a list": reply({ buffs: { 0: 1453 } }),
    "buffs with a number that is not whole": reply({ buffs: [43.5] }),
    "buffs with a text": reply({ buffs: ["43"] }),
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

  it("refuses a kit that wears items of two tiers, whether or not the page names the tier: the pool of a best kit is at one tier", () => {
    const mixed = reply({ kit: ["w90003@4", "w80816@5", ...KIT.slice(2)] });
    expect(() => validateFromWorker(mixed, expectation)).toThrow(/protocol/);
    expect(() => validateFromWorker(mixed, { ...expectation, tier: 4 })).toThrow(/protocol/);
    expect(() => validateFromWorker(reply({ kit: ["w90003@0", ...KIT.slice(1)] }), expectation)).toThrow(/protocol/);
  });

  it("refuses a kit whose items are at another tier than the request's, when the page names it", () => {
    expect(() => validateFromWorker(reply(), { ...expectation, tier: 5 })).toThrow(/protocol/);
    expect(() => validateFromWorker(reply(), { ...expectation, tier: 0 })).toThrow(/protocol/);
    expect(() => validateFromWorker(reply({ kit: KIT.map((ident) => (ident === null ? null : ident.replace("@4", "@10"))) }), { ...expectation, tier: 4 })).toThrow(/protocol/);
    expect(validateFromWorker(reply({ kit: KIT.map((ident) => (ident === null ? null : ident.replace("@4", "@10"))) }), { ...expectation, tier: 10 }).status).toBe("optimal");
  });

  it("is refused when the request in flight was for a model or for another mode, and the other way round", () => {
    expect(() => validateFromWorker(reply(), { id: 4, kind: "model", columns: 3 })).toThrow(/protocol/);
    for (const mode of ["equip-now", "farm-path", "best-sets", "every-slot"]) expect(() => validateFromWorker(reply(), { id: 4, kind: "scenario", mode })).toThrow(/protocol/);
    expect(() => validateFromWorker(reply(), { id: 4 })).toThrow(/protocol/); // it must be known what was asked
    const equip = reply({ mode: "equip-now" });
    expect(() => validateFromWorker(equip, expectation)).toThrow(/protocol/);
    expect(validateFromWorker(equip, { id: 4, kind: "scenario", mode: "equip-now", owned: [["w90003@4", 1], ["w80816@4", 1], ["w90009@4", 2], ["w80113@4", 1]] }).mode).toBe("equip-now");
  });

  it("is refused with an accessor, which could show one value to the check and another to the page", () => {
    const sneaky = reply();
    let reads = 0;
    Object.defineProperty(sneaky, "F", { enumerable: true, get: () => ((reads += 1), "5/1") });
    expect(() => validateFromWorker(sneaky, expectation)).toThrow(/protocol/);
    expect(reads).toBe(0);
  });

  it("takes an error for the request, with its code, as any request's", () => {
    expect(validateFromWorker({ v: 1, type: "error", id: 4, code: "bad-request", message: "The weights ask for a slider that there is not." }, expectation).code).toBe("bad-request");
    expect(validateFromWorker({ v: 1, type: "error", id: 4, code: "engine-load", message: "The optimizer's data could not be loaded." }, expectation).code).toBe("engine-load");
  });

  describe("reports its progress", () => {
    const report = (over = {}) => ({ v: 1, type: "progress", id: 4, phase: "building", ...over });

    it("with the stage best-kit, and the stage loading while the data is loaded, and no other", () => {
      expect(validateFromWorker(report({ stage: "best-kit" }), expectation).stage).toBe("best-kit");
      expect(validateFromWorker(report({ phase: "loading", stage: "loading", loaded: 10, total: 20 }), expectation)).toMatchObject({ stage: "loading", loaded: 10, total: 20 });
      for (const stage of ["equip-now", "step", "best-sets", "every-slot", "solve", "tie", "", "Best-Kit", "best_kit"]) {
        expect(() => validateFromWorker(report({ stage }), expectation), stage).toThrow(/protocol/);
      }
      expect(() => validateFromWorker(report({ stage: "best-kit", step: 1 }), expectation)).toThrow(/protocol/); // a step goes with the stage of a step
      expect(validateFromWorker(report({ stage: "best-kit", phase: "solving", elapsedMs: 5, objective: 12, bound: 13, gap: 0.01, nodes: 4 }), expectation).stage).toBe("best-kit");
    });

    it("and the stage best-kit is the stage of no other mode", () => {
      for (const mode of ["equip-now", "farm-path", "best-sets", "every-slot"]) {
        expect(() => validateFromWorker(report({ stage: "best-kit" }), { id: 4, kind: "scenario", mode }), mode).toThrow(/protocol/);
      }
      expect(() => validateFromWorker(report({ stage: "best-kit" }), { id: 4, kind: "model", columns: 3 })).toThrow(/protocol/);
    });
  });
});
