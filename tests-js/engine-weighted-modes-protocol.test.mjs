// The weights in every mode of a scenario request, and the options of the best kit (protocol.js). The weights were a field of the best kit alone; Equip now, the farm path, the best
// sets and Every slot take the same optional `weights`: the same allowlist ({multipliers?, custom?, regenT?}), the same shape (plain tables of short names and numbers, a number
// or null for the regen window) and the same numeric rule (zero, or at least 0.000001 in size with at most 6 significant digits), checked by the same function in the page
// and in the worker. Which groups, positions, names and bounds are allowed is the bundle's, and the worker holds the request to them (tests-js/engine-weighted-modes.test.mjs).
// The best kit has one more optional field, `options`, and no other mode has it: `{weaponTierRate: 5 | 10}`, the percent of damage a weapon grows a tier.

import { describe, expect, it } from "vitest";
import { parseManifest } from "../pipeline/trioforge/site/static/engine/manifest.js";
import { LIMITS, SCENARIO_MODES, validateFromWorker, validateRequest, validateToWorker } from "../pipeline/trioforge/site/static/engine/protocol.js";

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

const SCENARIO = { race: "OGR", role: "tank", buffs: "own", evidence: "wiki", setup: "dw" };
const KIT = new Array(22).fill(null);
const FIELDS = {
  "equip-now": () => ({ owned: [["w90001@4", 1], ["w90002@0", 2]] }),
  "farm-path": () => ({ owned: [["w90001@4", 1]], tierMode: { mode: "ready4" }, steps: 3 }),
  "best-sets": () => ({ owned: [], tierMode: { mode: "arrives", D: 2 }, k: 2 }),
  "every-slot": () => ({ owned: [["w90001@4", 1]], tierMode: { mode: "fixed", N: 6 }, kit: [...KIT], buffs: [43], limit: 3 }),
  "best-kit": () => ({ tier: 4 }),
};
const MODES = Object.keys(FIELDS);
const request = (mode, over = {}) => ({ v: 1, kind: "scenario", trio: "pal-mnk-ber", level: 50, mode, scenario: { ...SCENARIO }, budgetMs: 5000, ...FIELDS[mode](), ...over });
const weighted = (mode, weights, over = {}) => request(mode, { weights, ...over });
const bad = (value, manifest) => expect(() => validateRequest(value, manifest)).toThrow(/bad-request/);
const GOOD = { multipliers: { AC: 2 } };
const THE_WORKER = (value) => validateToWorker({ v: 1, type: "solve", id: 3, request: value });

describe("the weights of a request", () => {
  it("are an optional field of every one of the five modes", () => {
    expect(MODES).toEqual([...SCENARIO_MODES]);
    for (const mode of MODES) {
      const plain = validateRequest(request(mode), MANIFEST);
      expect("weights" in plain, mode).toBe(false);
      expect(validateRequest(weighted(mode, GOOD), MANIFEST).weights, mode).toEqual(GOOD);
    }
  });

  it("are accepted in every mode with the three options and a detached copy of them is what is sent", () => {
    for (const mode of MODES) {
      const original = weighted(mode, { multipliers: { AC: 2, "ATK+HASTE": 0.5 }, custom: { HP: 3, SV_FIRE: 0.25 }, regenT: 10 });
      const clean = validateRequest(original, MANIFEST);
      expect(clean, mode).toEqual(original);
      expect(clean.weights, mode).not.toBe(original.weights);
      for (const table of ["multipliers", "custom"]) expect(clean.weights[table], mode).not.toBe(original.weights[table]);
      original.weights.multipliers.AC = 0.5;
      original.weights.custom.HP = 999;
      original.weights.regenT = 60;
      expect(clean.weights, `${mode}: what was checked is what is sent`).toEqual({ multipliers: { AC: 2, "ATK+HASTE": 0.5 }, custom: { HP: 3, SV_FIRE: 0.25 }, regenT: 10 });
      for (const table of [clean.weights.multipliers, clean.weights.custom]) {
        const prototype = Object.getPrototypeOf(table);
        expect(prototype === null || prototype === Object.prototype, mode).toBe(true);
      }
    }
  });

  it("take the weights of the best kit's tests: the same tables, the same positions and the same regen window", () => {
    const ok = [
      {},
      { multipliers: {} },
      { custom: {} },
      { regenT: 0 },
      { regenT: 60 },
      { regenT: 2.5 },
      { regenT: null },
      { multipliers: { AC: 0.5, MANA: 1, "ATK+HASTE": 2, SV: 1, regen: 0.5 } },
      { custom: { SV: 0, SV_FIRE: 1000, HASTE: 0.05, CHA: 10 } },
      { multipliers: { regen: 2 }, regenT: 10 },
      { multipliers: { AC: 2 }, custom: { HP: 3 }, regenT: 10 },
    ];
    for (const mode of MODES) for (const weights of ok) expect(validateRequest(weighted(mode, weights)).weights, `${mode} ${JSON.stringify(weights)}`).toEqual(weights);
  });

  it("are checked for their shape and not for their bounds: which groups there are, which positions and how large is the bundle's, and the worker holds the request to them", () => {
    const shapely = { multipliers: { NOPE: 7 }, custom: { ZZZ: 5000, HP: -1 }, regenT: 99 };
    for (const mode of MODES) expect(validateRequest(weighted(mode, shapely)).weights, mode).toEqual(shapely);
  });

  it("are refused, in every mode, when they are not a plain object or have an option that is not one of the three: the mana flag is the worker's, never the page's", () => {
    for (const mode of MODES) {
      expect(() => validateRequest(weighted(mode, GOOD)), `${mode}: a good one is taken`).not.toThrow();
      for (const weights of [[], [{ regenT: 3 }], "regenT", 5, null, undefined, true, new Map(), new Set(), Object.create({ regenT: 3 }), () => ({})]) bad(weighted(mode, weights));
      for (const extra of ["manaReachable", "mana_reachable", "regen_T", "multiplier", "Multipliers", "CUSTOM", "canonical", "lock", "exclude", "url", "options", "tier", "__proto__", "constructor", ""]) {
        bad(weighted(mode, { [extra]: true }));
        bad(weighted(mode, { regenT: 3, [extra]: {} }));
      }
      bad(weighted(mode, { multipliers: { AC: 2 }, regenT: undefined }));
      bad(weighted(mode, JSON.parse('{"__proto__": {"regenT": 3}}')));
    }
  });

  it("are refused, in every mode, when a table is not a plain table of short names and finite numbers", () => {
    for (const mode of MODES) {
      expect(() => validateRequest(weighted(mode, { custom: { HP: 3 } })), mode).not.toThrow();
      for (const table of ["multipliers", "custom"]) {
        for (const value of [[], "AC", 2, null, undefined, true, new Map([["AC", 2]]), Object.create({ AC: 2 }), () => ({})]) bad(weighted(mode, { [table]: value }));
        for (const number of ["2", "", null, undefined, true, [2], { x: 2 }, Number.NaN, Infinity, -Infinity, 2n, Symbol("x")]) bad(weighted(mode, { [table]: { AC: number } }));
        for (const name of ["", "a/b", "https://evil.example", "..", "A".repeat(LIMITS.maxNameLength + 1), "O\u0000R", " AC", "A\nC", "é", "__proto__", "constructor", "prototype", "+AC"]) {
          bad(weighted(mode, { [table]: { [name]: 2 } }));
        }
        bad(weighted(mode, { [table]: JSON.parse('{"__proto__": 2}') }));
        const most = Object.fromEntries(Array.from({ length: LIMITS.maxWeightEntries }, (_, at) => [`W${at}`, 1]));
        expect(Object.keys(validateRequest(weighted(mode, { [table]: most })).weights[table]), `${mode} ${table}`).toHaveLength(LIMITS.maxWeightEntries);
        bad(weighted(mode, { [table]: { ...most, TOO: 1 } }));
      }
      for (const regenT of ["10", "", true, [10], { regenT: 10 }, Number.NaN, Infinity, 10n, Symbol("x"), undefined]) bad(weighted(mode, { regenT }));
    }
  });

  it("are held, in every mode, to the numeric rule of the best kit: zero, or at least 0.000001 in size with at most 6 significant digits, for a slider, a custom weight and the window alike", () => {
    const PLACES = {
      "a slider position": (value) => ({ multipliers: { AC: value } }),
      "a custom weight": (value) => ({ custom: { HP: value } }),
      "the regen window": (value) => ({ regenT: value }),
    };
    for (const mode of MODES) {
      for (const [place, make] of Object.entries(PLACES)) {
        for (const value of [0, -0, 1e-6, 1.5e-6, 0.5, 1, 2, 60, 1.23457, 123.456, 0.123456, 654321]) expect(() => validateRequest(weighted(mode, make(value))), `${mode} ${place} ${value}`).not.toThrow();
        for (const value of [9.99999e-7, 5e-7, 1e-9, 1e-100, 5e-324, -9.99999e-7, -5e-324, 1.234567, 0.30000000000000004, 1 / 3, 1234567]) {
          bad(weighted(mode, make(value)));
          expect(() => THE_WORKER(weighted(mode, make(value))), `${mode} ${place} ${value}: the worker`).toThrow(/bad-request/);
        }
      }
      for (const hostile of [weighted(mode, { custom: { HP: 5e-324 } }), weighted(mode, { regenT: 1e-100 })]) {
        expect(() => validateRequest(hostile, MANIFEST), `${mode}: the page`).toThrow(/bad-request/);
        expect(() => THE_WORKER(hostile), `${mode}: the worker`).toThrow(/bad-request/);
      }
    }
  });

  it("are refused, in every mode, when a table or the weights carry an accessor, which could show one value to the check and another to the worker", () => {
    for (const mode of MODES) {
      let reads = 0;
      expect(() => validateRequest(weighted(mode, GOOD)), mode).not.toThrow();
      const sneaky = { AC: 2 };
      Object.defineProperty(sneaky, "SV", { enumerable: true, get: () => ((reads += 1), 2) });
      bad(weighted(mode, { multipliers: sneaky }));
      const weights = { regenT: 3 };
      Object.defineProperty(weights, "custom", { enumerable: true, get: () => ((reads += 1), {}) });
      bad(weighted(mode, weights));
      const mine = request(mode);
      Object.defineProperty(mine, "weights", { enumerable: true, get: () => ((reads += 1), {}) });
      bad(mine);
      expect(reads, mode).toBe(0);
    }
  });

  it("reach the worker as a message in every mode, and the hostile ones do not", () => {
    for (const mode of MODES) {
      expect(THE_WORKER(weighted(mode, { multipliers: { AC: 2 } })).request.mode, mode).toBe(mode);
      expect(THE_WORKER(weighted(mode, { multipliers: { AC: 2 } })).request.weights, mode).toEqual({ multipliers: { AC: 2 } });
      for (const hostile of [weighted(mode, { manaReachable: true }), weighted(mode, { multipliers: { "a/b": 1 } }), weighted(mode, { custom: { HP: 1.234567 } }), weighted(mode, [])]) {
        expect(() => THE_WORKER(hostile), mode).toThrow(/bad-request/);
      }
    }
  });

  it("keep the allowlist of every mode otherwise: the fields of another mode, an address and a lock are still refused", () => {
    for (const mode of MODES) {
      expect(() => validateRequest(weighted(mode, GOOD)), mode).not.toThrow();
      for (const extra of ["url", "wasmUrl", "manifest", "bundle", "model", "canonical", "lock", "exclude", "candidates", "pool", "deity", "regenT", "multipliers", "custom"]) bad(weighted(mode, GOOD, { [extra]: "x" }));
    }
  });

  it("do not change a request that has none: the five modes' requests are copied as they were", () => {
    for (const mode of MODES) {
      const original = request(mode);
      const clean = validateRequest(original, MANIFEST);
      expect(clean, mode).toEqual(mode === "every-slot" ? { ...original, limit: 3 } : original);
    }
  });
});

describe("the options of a best kit", () => {
  const options = (value, over = {}) => request("best-kit", { options: value, ...over });

  it("are an optional field of the best kit: the weapon tier rate, 5 or 10, and a detached copy is what is sent", () => {
    expect("options" in validateRequest(request("best-kit"), MANIFEST)).toBe(false);
    for (const rate of [5, 10]) {
      const original = options({ weaponTierRate: rate });
      const clean = validateRequest(original, MANIFEST);
      expect(clean).toEqual(original);
      expect(clean.options).not.toBe(original.options);
      original.options.weaponTierRate = rate === 5 ? 10 : 5;
      expect(clean.options.weaponTierRate, "what was checked is what is sent").toBe(rate);
    }
    expect(validateRequest(options({})).options, "no key is none to refuse").toEqual({});
  });

  it("come with the weights, and with nothing else being changed: both are read, each by its own check", () => {
    const both = request("best-kit", { weights: { multipliers: { "ATK+HASTE": 2 } }, options: { weaponTierRate: 10 } });
    const clean = validateRequest(both, MANIFEST);
    expect(clean).toEqual(both);
    expect(THE_WORKER(both).request.options).toEqual({ weaponTierRate: 10 });
  });

  it("allow the rate 5 and the rate 10 and no other value: not another number, not text, not null, not a list", () => {
    expect(() => validateRequest(options({ weaponTierRate: 5 }))).not.toThrow();
    for (const rate of [0, 1, 4, 6, 7.5, 9, 11, 15, 20, 100, -5, -10, 5.0000001, 10.000001, 0.5, "5", "10", "5%", "", null, undefined, true, false, [5], { rate: 5 }, Number.NaN, Infinity, 5n, Symbol("x")]) {
      bad(options({ weaponTierRate: rate }));
      expect(() => THE_WORKER(options({ weaponTierRate: rate })), `the worker: ${String(rate)}`).toThrow(/bad-request/);
    }
  });

  it("allow the key weaponTierRate and no other: an allowlist, so that a misspelling or a later option does not slip in", () => {
    for (const key of ["weapon_tier_rate", "weaponPct", "weapon_pct", "WeaponTierRate", "weaponTierRate ", "rate", "tierRate", "tier", "weights", "url", "canonical", "lock", "exclude", "deity", "__proto__", "constructor", "prototype", ""]) {
      bad(options({ [key]: 5 }));
      bad(options({ weaponTierRate: 5, [key]: 10 })); // a right option does not excuse a wrong one
    }
    bad(options(JSON.parse('{"__proto__": {"weaponTierRate": 5}}')));
  });

  it("are a plain object: not a list, a text, a number, null, a map, one with a prototype or an accessor", () => {
    for (const value of [[], [{ weaponTierRate: 5 }], "weaponTierRate", 5, null, undefined, true, new Map([["weaponTierRate", 5]]), new Set([5]), Object.create({ weaponTierRate: 5 }), () => ({})]) bad(options(value));
    let reads = 0;
    const sneaky = {};
    Object.defineProperty(sneaky, "weaponTierRate", { enumerable: true, get: () => ((reads += 1), 5) });
    bad(options(sneaky));
    const hidden = {};
    Object.defineProperty(hidden, "weaponTierRate", { enumerable: false, value: 5 });
    bad(options(hidden));
    const mine = request("best-kit");
    Object.defineProperty(mine, "options", { enumerable: true, get: () => ((reads += 1), {}) });
    bad(mine);
    expect(reads).toBe(0);
  });

  it("are a field of the best kit and of no other mode", () => {
    for (const mode of MODES) {
      if (mode === "best-kit") continue;
      bad(request(mode, { options: { weaponTierRate: 5 } }));
      bad(request(mode, { options: {} }));
      bad(request(mode, { weights: GOOD, options: { weaponTierRate: 10 } }));
      expect(() => THE_WORKER(request(mode, { options: { weaponTierRate: 5 } })), mode).toThrow(/bad-request/);
    }
    expect(THE_WORKER(options({ weaponTierRate: 10 })).request.options).toEqual({ weaponTierRate: 10 });
  });

  it("do not change what the answer is held to: the best kit's reply has no rate in it and the page's expectation is the same", () => {
    const reply = (over = {}) => ({ v: 1, type: "result", id: 4, kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null, F: "5/1", value: 5, kit: new Array(22).fill(null), buffs: [], hasteAssumed: 0, elapsedMs: 1, ...over });
    expect(validateFromWorker(reply(), { id: 4, kind: "scenario", mode: "best-kit", tier: 4 }).status).toBe("optimal");
    expect(() => validateFromWorker(reply({ options: { weaponTierRate: 10 } }), { id: 4, kind: "scenario", mode: "best-kit" })).toThrow(/protocol/);
    expect(() => validateFromWorker(reply({ weights: {} }), { id: 4, kind: "scenario", mode: "best-kit" })).toThrow(/protocol/);
  });
});
