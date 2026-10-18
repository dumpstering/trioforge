// The other scenario modes and their messages (protocol.js), checked in both directions as the mode "equip-now" is (engine-scenario-protocol.test.mjs). A scenario
// request is of one of four modes and of no other; each mode has an allowlist of its own, and every field is read once into a fresh copy:
//
//   equip-now    {scenario, owned}                                            (unchanged)
//   farm-path    {scenario, owned, tierMode, steps}                           steps a whole number from 1 to 8
//   best-sets    {scenario, owned, tierMode, k}                               k 2 or 3
//   every-slot   {scenario, owned, tierMode, kit, buffs, limit?}              kit of exactly 22 places (an ident or null), buffs rising whole numbers from 0, limit 1 to 10 (3)
//
// where tierMode is {mode: "ready4"}, {mode: "arrives", D} (D 0 to 4) or {mode: "fixed", N} (N 0 to 10), exactly those fields. The request never carries candidates:
// the worker makes them from the tier mode. The page sends {v, type: "stop", id} for the farm path in flight. The worker sends, for a farm path, a {type: "step"}
// message for Equip now (index 0) and for every step (1 to 8), then the final result of each mode; its progress carries a stage. The page checks every one of
// them as it checks the answer to Equip now, and a path as a whole (the order of the steps, what each one acquires and the values that follow from it).

import { describe, expect, it } from "vitest";
import {
  KIT_PLACE_NAMES,
  LABEL_NO_INCUMBENT,
  LABEL_TIME_LIMIT,
  LIMITS,
  SCENARIO_MODES,
  createPathWatch,
  validateFromWorker,
  validateRequest,
  validateToWorker,
} from "../pipeline/trioforge/site/static/engine/protocol.js";
import { SLOT_INSTANCES } from "../pipeline/trioforge/site/static/engine/evaluate.js";
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
const OWNED = [["w90001@4", 1], ["w90007@4", 2], ["w80113@0", 1]];
const KIT = ["w90001@4", null, "w90007@4", "w90007@4", ...new Array(17).fill(null), "w80113@0"];
const READY4 = { mode: "ready4" };
const base = (over = {}) => ({ v: 1, kind: "scenario", trio: "pal-mnk-ber", level: 50, scenario: { ...SCENARIO }, owned: OWNED.map((pair) => [...pair]), budgetMs: 5000, ...over });
const farm = (over = {}) => base({ mode: "farm-path", tierMode: { ...READY4 }, steps: 3, ...over });
const sets = (over = {}) => base({ mode: "best-sets", tierMode: { ...READY4 }, k: 2, ...over });
const slots = (over = {}) => base({ mode: "every-slot", tierMode: { ...READY4 }, kit: [...KIT], buffs: [43, 1453], ...over });
const equip = (over = {}) => base({ mode: "equip-now", ...over });
const bad = (value, manifest) => expect(() => validateRequest(value, manifest)).toThrow(/bad-request/);
const without = (build, field) => {
  const value = build();
  delete value[field];
  return value;
};

describe("the modes of a scenario request", () => {
  it("are five, and a request of any other is a bad request: the generic scenario shape is gone (the fifth, best-kit, has its own tests: engine-best-kit-protocol.test.mjs)", () => {
    expect(SCENARIO_MODES).toEqual(["equip-now", "farm-path", "best-sets", "every-slot", "best-kit"]);
    for (const build of [equip, farm, sets, slots]) expect(() => validateRequest(build(), MANIFEST)).not.toThrow();
    for (const mode of ["equip", "best-1", "best-2", "best-sets ", "Farm-Path", "farm_path", "everyslot", "", "constructor", "__proto__", "toString", "hasOwnProperty", "https://evil.example", "//x", "a/b"]) {
      bad(farm({ mode }));
    }
    for (const mode of [5, null, undefined, true, ["farm-path"], { mode: "farm-path" }]) bad(farm({ mode }));
    bad(without(farm, "mode")); // a scenario request names its mode
    // the generic shape: any plain data for a scenario, a list of owned items of any form, and candidates
    bad({ v: 1, kind: "scenario", trio: "pal-mnk-ber", level: 50, scenario: { race: "OGR", role: "balanced", tier: 4 }, owned: [[1234, 4, 1]], candidates: [], mode: "equip", budgetMs: 5000 });
    bad({ v: 1, kind: "scenario", trio: "pal-mnk-ber", level: 50, scenario: { race: "OGR" }, owned: [], candidates: [], budgetMs: 5000 });
  });

  it("never carry candidates, whatever the mode", () => {
    for (const build of [equip, farm, sets, slots]) {
      bad(build({ candidates: [] }));
      bad(build({ candidates: [["w90001@4", 1]] }));
      bad(build({ candidates: [{ key: "w90001", tier: 4 }] }));
    }
  });

  it("have each an allowlist of their own: the fields of another mode are refused", () => {
    const FIELDS = { tierMode: READY4, steps: 3, k: 2, kit: KIT, buffs: [1], limit: 3 };
    const allowed = { "equip-now": [], "farm-path": ["tierMode", "steps"], "best-sets": ["tierMode", "k"], "every-slot": ["tierMode", "kit", "buffs", "limit"] };
    const builders = { "equip-now": equip, "farm-path": farm, "best-sets": sets, "every-slot": slots };
    for (const [mode, build] of Object.entries(builders)) {
      for (const [field, value] of Object.entries(FIELDS)) {
        if (allowed[mode].includes(field)) continue;
        bad(build({ [field]: value }));
      }
      for (const extra of ["url", "wasmUrl", "href", "manifest", "items", "bundle", "model", "scenarios", "canonical", "owned2", "mode2", "id"]) bad(build({ [extra]: "x" }));
    }
  });

  it("need every field of their own, but the limit of every-slot", () => {
    for (const field of ["scenario", "owned", "trio", "level", "budgetMs", "tierMode", "steps"]) bad(without(farm, field));
    for (const field of ["tierMode", "k"]) bad(without(sets, field));
    for (const field of ["tierMode", "kit", "buffs"]) bad(without(slots, field));
    expect(validateRequest(without(slots, "limit")).limit).toBe(3); // and the limit is 3 when it is not given
    expect(validateRequest(slots({ limit: 7 })).limit).toBe(7);
  });

  it("are checked against the manifest as Equip now is: a trio and a level it lists", () => {
    for (const build of [farm, sets, slots]) {
      for (const over of [{ trio: "war-war-war" }, { trio: "constructor" }, { level: 49 }, { level: "50" }]) bad(build(over), MANIFEST);
    }
  });

  it("keep the checks of Equip now on the scenario, the owned set and the budget", () => {
    for (const build of [farm, sets, slots]) {
      bad(build({ scenario: { ...SCENARIO, tier: 4 } }));
      bad(build({ scenario: { ...SCENARIO, race: "a/b" } }));
      bad(build({ owned: [["w5@11", 1]] }));
      bad(build({ owned: [["w5@4", 1], ["w5@4", 1]] }));
      bad(build({ budgetMs: 0 }));
      bad(build({ budgetMs: LIMITS.maxBudgetMs + 1 }));
      expect(validateRequest(build({ owned: [], scenario: { ...SCENARIO, deity: "The Tribunal" } })).scenario.deity).toBe("The Tribunal");
    }
  });

  it("are copied: what was checked is what is sent, whatever the caller does afterwards", () => {
    for (const build of [farm, sets, slots]) {
      const original = build();
      const clean = validateRequest(original);
      expect(clean).toEqual(original.mode === "every-slot" ? { ...original, limit: 3 } : original);
      expect(clean.tierMode).not.toBe(original.tierMode);
      expect(clean.owned).not.toBe(original.owned);
      expect(clean.scenario).not.toBe(original.scenario);
      original.tierMode.mode = "fixed";
      original.owned.push(["w2@0", 1]);
      expect(clean.tierMode).toEqual(READY4);
      expect(clean.owned).toHaveLength(3);
    }
    const original = slots();
    const clean = validateRequest(original);
    expect(clean.kit).not.toBe(original.kit);
    expect(clean.buffs).not.toBe(original.buffs);
    original.kit[0] = null;
    original.buffs.push(9999);
    expect(clean.kit[0]).toBe("w90001@4");
    expect(clean.buffs).toEqual([43, 1453]);
  });

  it("are read once: a field that is an accessor is refused, and so is one inside the tier mode or the kit", () => {
    let reads = 0;
    const sneaky = farm();
    Object.defineProperty(sneaky, "steps", { enumerable: true, get: () => ((reads += 1), 3) });
    bad(sneaky);
    const mode = { ...READY4 };
    Object.defineProperty(mode, "mode", { enumerable: true, get: () => ((reads += 1), "ready4") });
    bad(farm({ tierMode: mode }));
    const kit = [...KIT];
    Object.defineProperty(kit, 0, { enumerable: true, get: () => ((reads += 1), "w90001@4") });
    bad(slots({ kit }));
    expect(reads).toBeLessThanOrEqual(1);
  });

  it("arrive as a message to the worker as they are checked in the page", () => {
    for (const build of [farm, sets, slots]) expect(validateToWorker({ v: 1, type: "solve", id: 3, request: build() }).request.mode).toBe(build().mode);
    for (const hostile of [farm({ candidates: [] }), farm({ steps: 9 }), sets({ k: 4 }), slots({ kit: KIT.slice(1) }), base({ mode: "best-1" })]) {
      expect(() => validateToWorker({ v: 1, type: "solve", id: 3, request: hostile })).toThrow(/bad-request/);
    }
  });
});

describe("the tier mode of a request", () => {
  const accepted = [{ mode: "ready4" }, { mode: "arrives", D: 0 }, { mode: "arrives", D: 4 }, { mode: "arrives", D: 2 }, { mode: "fixed", N: 0 }, { mode: "fixed", N: 10 }, { mode: "fixed", N: 7 }];
  const refused = {
    "ready4 with a field more": [{ mode: "ready4", D: 4 }, { mode: "ready4", N: 4 }, { mode: "ready4", url: "x" }],
    "arrives with a D beyond 0 to 4": [{ mode: "arrives", D: 5 }, { mode: "arrives", D: -1 }, { mode: "arrives", D: 10 }, { mode: "arrives", D: 4.5 }, { mode: "arrives", D: "4" }, { mode: "arrives", D: null }],
    "arrives without its D, or with an N": [{ mode: "arrives" }, { mode: "arrives", D: 4, N: 4 }, { mode: "arrives", N: 4 }],
    "fixed with an N beyond 0 to 10": [{ mode: "fixed", N: 11 }, { mode: "fixed", N: -1 }, { mode: "fixed", N: 10.5 }, { mode: "fixed", N: "4" }, { mode: "fixed", N: null }, { mode: "fixed", N: Number.NaN }],
    "fixed without its N, or with a D": [{ mode: "fixed" }, { mode: "fixed", N: 4, D: 4 }, { mode: "fixed", D: 4 }],
    "a mode that is not one of the three": [{ mode: "arrive" }, { mode: "Ready4" }, { mode: "ready" }, { mode: "" }, { mode: null }, { mode: 4 }, { mode: "__proto__" }, { mode: "constructor" }, {}],
    "a tier mode that is not a plain object": ["ready4", 4, null, undefined, ["ready4"], new Map([["mode", "ready4"]]), Object.create({ mode: "ready4" })],
  };
  for (const build of [farm, sets, slots]) {
    it(`is exactly ${accepted.length} shapes in a ${build().mode} request`, () => {
      for (const tierMode of accepted) expect(validateRequest(build({ tierMode })).tierMode).toEqual(tierMode);
    });
    for (const [name, values] of Object.entries(refused)) {
      it(`refuses ${name} in a ${build().mode} request`, () => {
        for (const tierMode of values) bad(build({ tierMode }));
      });
    }
  }

  it("refuses a field that could poison a lookup", () => {
    const poisoned = JSON.parse('{"mode": "ready4", "__proto__": {"mode": "fixed"}}');
    bad(farm({ tierMode: poisoned }));
  });
});

describe("the steps, k, the kit, the buffs and the limit of a request", () => {
  it("takes a number of steps from 1 to 8 and no other", () => {
    for (const steps of [1, 2, 7, 8]) expect(validateRequest(farm({ steps })).steps).toBe(steps);
    for (const steps of [0, 9, -1, 1.5, "3", null, undefined, true, [3], Number.NaN, Infinity, 2 ** 31]) bad(farm({ steps }));
  });

  it("takes k of 2 or 3, and no other (a set of one is the first step of the path)", () => {
    for (const k of [2, 3]) expect(validateRequest(sets({ k })).k).toBe(k);
    for (const k of [0, 1, 4, 5, -2, 2.5, "2", "3", null, undefined, [2], Number.NaN]) bad(sets({ k }));
  });

  it("takes a kit of exactly 22 places, each an ident or empty", () => {
    expect(validateRequest(slots({ kit: new Array(22).fill(null) })).kit).toHaveLength(22);
    expect(validateRequest(slots()).kit).toEqual(KIT);
    for (const kit of [KIT.slice(0, 21), [...KIT, null], [], new Array(21).fill(null), new Array(23).fill(null), "kit", null, undefined, { length: 22 }, new Set(KIT)]) bad(slots({ kit }));
    for (const place of [5, "w90001", "w5@11", "__proto__@4", "w07@4", "https://evil.example/x@4", "", undefined, true, ["w5@4"], { ident: "w5@4" }]) {
      bad(slots({ kit: [place, ...KIT.slice(1)] }));
    }
    // eslint-disable-next-line no-sparse-arrays
    bad(slots({ kit: [, ...KIT.slice(1)] }));
  });

  it("takes buffs that are whole numbers from 0, rising, once each, at most as many as a result may have", () => {
    for (const buffs of [[], [0], [43], [1, 2, 3], [20011, 20012, Number.MAX_SAFE_INTEGER], Array.from({ length: LIMITS.maxBuffs }, (_, n) => n)]) {
      expect(validateRequest(slots({ buffs })).buffs).toEqual(buffs);
    }
    for (const buffs of [[2, 1], [1, 1], [1, 3, 2], [-1], [1.5], ["1"], [null], [Number.NaN], [Infinity], [2 ** 53], Array.from({ length: LIMITS.maxBuffs + 1 }, (_, n) => n), "1", null, undefined, { 0: 1, length: 1 }]) {
      bad(slots({ buffs }));
    }
    // eslint-disable-next-line no-sparse-arrays
    bad(slots({ buffs: [1, , 3] }));
  });

  it("takes a limit from 1 to 10, or none (3)", () => {
    for (const limit of [1, 3, 10]) expect(validateRequest(slots({ limit })).limit).toBe(limit);
    for (const limit of [0, 11, -1, 2.5, "3", null, [3], Number.NaN]) bad(slots({ limit }));
  });
});

describe("a stop", () => {
  it("is {v, type: 'stop', id} with the id of a request: a whole number from 1 to the most an id may be, and nothing else", () => {
    expect(validateToWorker({ v: 1, type: "stop", id: 7 })).toEqual({ v: 1, type: "stop", id: 7 });
    expect(validateToWorker({ v: 1, type: "stop", id: LIMITS.maxId })).toEqual({ v: 1, type: "stop", id: LIMITS.maxId });
    const sent = { v: 1, type: "stop", id: 3 };
    expect(validateToWorker(sent)).not.toBe(sent);
    for (const id of [0, -1, 1.5, "3", null, undefined, LIMITS.maxId + 1, Number.NaN, Infinity, [3], true]) {
      expect(() => validateToWorker({ v: 1, type: "stop", id })).toThrow(/bad-request/);
    }
    for (const extra of [{ request: farm() }, { reason: "x" }, { url: "/x" }, { id2: 4 }]) {
      expect(() => validateToWorker({ v: 1, type: "stop", id: 3, ...extra })).toThrow(/bad-request/);
    }
    expect(() => validateToWorker({ v: 2, type: "stop", id: 3 })).toThrow(/bad-request/);
    expect(() => validateToWorker({ v: 1, type: "stop" })).toThrow(/bad-request/);
  });

  it("is not a message the page may confuse with another type", () => {
    for (const type of ["Stop", "stop ", "cancel", "abort", "STOP"]) expect(() => validateToWorker({ v: 1, type, id: 3 })).toThrow(/bad-request/);
  });
});

// ---- the worker's messages ---------------------------------------------------------------------------------------------------------------

const PLACES = [...SLOT_INSTANCES];
it("lists the places of a kit as the evaluator does (protocol.js keeps a list of its own: it imports nothing heavy)", () => {
  expect([...KIT_PLACE_NAMES]).toEqual(PLACES);
  expect(PLACES).toHaveLength(22);
});
const wear = (...entries) => {
  const kit = new Array(22).fill(null);
  for (const [place, ident] of entries) kit[place] = ident;
  return kit;
};
/** The numbers and texts of an exact value, as the worker writes them: the reduced p/q text and the number. */
const exactOf = (numerator, denominator = 1) => ({ F: `${numerator}/${denominator}`, value: numerator / denominator });

describe("the progress of a scenario request", () => {
  const expectation = (mode) => ({ id: 4, kind: "scenario", mode });
  const report = (over = {}) => ({ v: 1, type: "progress", id: 4, phase: "building", ...over });

  it("may carry a stage, and a step with the stage of a step", () => {
    expect(validateFromWorker(report({ phase: "loading", stage: "loading", loaded: 10, total: 20 }), expectation("farm-path"))).toMatchObject({ stage: "loading", loaded: 10 });
    expect(validateFromWorker(report({ stage: "equip-now" }), expectation("farm-path")).stage).toBe("equip-now");
    expect(validateFromWorker(report({ phase: "solving", stage: "step", step: 3 }), expectation("farm-path"))).toMatchObject({ stage: "step", step: 3 });
    expect(validateFromWorker(report({ stage: "best-sets" }), expectation("best-sets")).stage).toBe("best-sets");
    expect(validateFromWorker(report({ stage: "every-slot" }), expectation("every-slot")).stage).toBe("every-slot");
    expect(validateFromWorker(report({ stage: "equip-now" }), expectation("equip-now")).stage).toBe("equip-now");
    expect(validateFromWorker(report(), expectation("farm-path")).stage).toBeUndefined(); // (a report with none is a report as before)
  });

  it("is refused with a stage that is not one of the five, a stage of another mode, or a step that does not go with its stage", () => {
    const protocol = (value, mode = "farm-path") => expect(() => validateFromWorker(value, expectation(mode))).toThrow(/protocol/);
    protocol(report({ stage: "solving" }));
    protocol(report({ stage: "" }));
    protocol(report({ stage: 5 }));
    protocol(report({ stage: "__proto__" }));
    protocol(report({ stage: "best-sets" }), "farm-path");
    protocol(report({ stage: "step", phase: "solving", step: 1 }), "best-sets");
    protocol(report({ stage: "every-slot" }), "equip-now");
    protocol(report({ stage: "step", phase: "solving" })); // a step stage names its step
    protocol(report({ stage: "step", phase: "solving", step: 0 }));
    protocol(report({ stage: "step", phase: "solving", step: 9 }));
    protocol(report({ stage: "step", phase: "solving", step: 1.5 }));
    protocol(report({ stage: "equip-now", step: 1 })); // and only a step stage has one
    // a model request has no stages
    expect(() => validateFromWorker(report({ stage: "loading" }), { id: 4, kind: "model", columns: 3 })).toThrow(/protocol/);
  });
});

describe("the steps of a farm path", () => {
  const OWNED_TWO = [["w90001@4", 1], ["w90007@4", 2], ["w80113@0", 1]];
  const expectationOf = (path) => ({ id: 4, kind: "scenario", mode: "farm-path", owned: OWNED_TWO, steps: 3, ...(path === undefined ? {} : { path }) });
  const watchOf = () => createPathWatch(farm({ owned: OWNED_TWO, steps: 3 }));

  const KIT0 = wear([0, "w90001@4"], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@0"]);
  const equipNowStep = (over = {}) => ({ v: 1, type: "step", id: 4, index: 0, status: "optimal", proven: true, label: null, ...exactOf(100), kit: [...KIT0], buffs: [43], hasteAssumed: 40, ...over });
  /** Step 1: a new item, in the empty place 1 (a ring of a drop, brought to +4 from its arrival at +4: it costs nothing). */
  const KIT1 = wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@0"]);
  const stepOne = (over = {}) => ({
    v: 1,
    type: "step",
    id: 4,
    index: 1,
    found: true,
    ident: "w90009@4",
    kind: "new",
    sourceTier: null,
    cost: { exp: 0, copiesAtArrival: 0, potentials: 0 },
    ...exactOf(130),
    gain: "30/1",
    gainValue: 30,
    kit: [...KIT1],
    buffs: [43],
    hasteAssumed: 40,
    status: "optimal",
    proven: true,
    label: null,
    ...over,
  });

  it("begins with Equip now, as the answer to Equip now is checked: its fields, its kit that wears only owned items", () => {
    const original = equipNowStep();
    const clean = validateFromWorker(original, expectationOf());
    expect(clean).toEqual(original);
    expect(clean.kit).not.toBe(original.kit);
    expect(clean.buffs).not.toBe(original.buffs);
    const protocol = (value) => expect(() => validateFromWorker(value, expectationOf())).toThrow(/protocol/);
    protocol(equipNowStep({ kit: ["w99999@4", ...KIT0.slice(1)] })); // not owned
    protocol(equipNowStep({ kit: ["w90001@4", "w90001@4", ...KIT0.slice(2)] })); // more than owned
    protocol(equipNowStep({ status: "optimal", proven: false }));
    protocol(equipNowStep({ status: "time_limit", proven: false, label: null }));
    protocol(equipNowStep({ F: "10/4", value: 2.5 }));
    protocol(equipNowStep({ hasteAssumed: 1001 }));
    protocol(equipNowStep({ found: true })); // a field of the steps after it
    protocol(equipNowStep({ elapsedMs: 5 })); // a field of a result
    protocol(equipNowStep({ mode: "farm-path" }));
    protocol({ ...equipNowStep(), id: 5 });
    expect(validateFromWorker(equipNowStep({ status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT, F: null, value: null, kit: null, buffs: [] }), expectationOf()).kit).toBeNull();
  });

  it("goes on with steps: a step is found or it is not, and the fields of the one are not the fields of the other", () => {
    expect(validateFromWorker(stepOne(), expectationOf())).toEqual(stepOne());
    const notFound = stepOne({ found: false, ident: null, kind: null, sourceTier: null, cost: null, F: null, value: null, gain: null, gainValue: null, kit: null, buffs: [], status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT });
    expect(validateFromWorker(notFound, expectationOf())).toEqual(notFound);
    // a step in time with a kit, not proven the best: it is a step with the label of a solve that ran out of time
    const late = stepOne({ status: "time_limit", proven: false, label: LABEL_TIME_LIMIT });
    expect(validateFromWorker(late, expectationOf()).label).toBe(LABEL_TIME_LIMIT);
    const protocol = (value) => expect(() => validateFromWorker(value, expectationOf())).toThrow(/protocol/);
    protocol(stepOne({ found: "yes" }));
    protocol(stepOne({ found: false })); // ... with everything of a found one still in it
    protocol({ ...notFound, ident: "w90009@4" });
    protocol({ ...notFound, kind: "new" });
    protocol({ ...notFound, cost: { exp: 0, copiesAtArrival: 0, potentials: 0 } });
    protocol({ ...notFound, F: "130/1", value: 130 });
    protocol({ ...notFound, status: "optimal", proven: true, label: null });
    protocol({ ...notFound, label: LABEL_TIME_LIMIT });
    protocol(stepOne({ index: 9 })); // a path has eight steps at most
    protocol(stepOne({ index: -1 }));
    protocol(stepOne({ index: 1.5 }));
    protocol(stepOne({ index: "1" }));
    protocol(stepOne({ index: undefined }));
    protocol(stepOne({ extra: 1 }));
    protocol(stepOne({ gain: undefined }));
    protocol(stepOne({ elapsedMs: 3 }));
  });

  it("says what a step acquires as an ident, a kind and a tier it is made from, and the three go together", () => {
    const protocol = (value) => expect(() => validateFromWorker(value, expectationOf())).toThrow(/protocol/);
    for (const kind of ["new", "copy"]) expect(validateFromWorker(stepOne({ kind }), expectationOf()).kind).toBe(kind);
    protocol(stepOne({ kind: "upgrade" })); // an upgrade names the tier of the copy it is made from
    protocol(stepOne({ kind: "new", sourceTier: 0 }));
    protocol(stepOne({ kind: "buy" }));
    protocol(stepOne({ kind: null }));
    protocol(stepOne({ ident: "w90009" }));
    protocol(stepOne({ ident: "__proto__@4" }));
    protocol(stepOne({ ident: "w90009@11" }));
    protocol(stepOne({ ident: "w90003@4" })); // an item the kit does not wear is not what the step acquired
    const upgrade = stepOne({ ident: "w90009@4", kind: "upgrade", sourceTier: 0, cost: { exp: 15, copiesAtArrival: 1, potentials: 4 } });
    expect(validateFromWorker(upgrade, expectationOf()).sourceTier).toBe(0);
    protocol({ ...upgrade, sourceTier: 4 }); // a copy of the same tier is no upgrade
    protocol({ ...upgrade, sourceTier: 5 });
    protocol({ ...upgrade, sourceTier: -1 });
    protocol({ ...upgrade, sourceTier: 1.5 });
    protocol({ ...upgrade, cost: null }); // an upgrade always costs something
  });

  it("says what reaching the tier costs: experience, copies and potentials that agree with each other and with the tier", () => {
    const protocol = (value) => expect(() => validateFromWorker(value, expectationOf())).toThrow(/protocol/);
    // from +0 to +4: 15 experience; 15 copies that arrive at +0, or one that arrives at +4 (16 experience); four potentials
    for (const cost of [{ exp: 15, copiesAtArrival: 15, potentials: 4 }, { exp: 15, copiesAtArrival: 1, potentials: 4 }, { exp: 15, copiesAtArrival: 8, potentials: 4 }, { exp: 0, copiesAtArrival: 0, potentials: 0 }, { exp: 8, copiesAtArrival: 8, potentials: 1 }]) {
      expect(validateFromWorker(stepOne({ cost }), expectationOf()).cost).toEqual(cost);
    }
    protocol(stepOne({ cost: { exp: 15, copiesAtArrival: 15 } }));
    protocol(stepOne({ cost: { exp: 15, copiesAtArrival: 15, potentials: 4, extra: 1 } }));
    protocol(stepOne({ cost: { exp: 14, copiesAtArrival: 14, potentials: 4 } })); // 2^4 - 2^0 is 15
    protocol(stepOne({ cost: { exp: 15, copiesAtArrival: 15, potentials: 3 } })); // and from +1 it would be 14
    protocol(stepOne({ cost: { exp: 15, copiesAtArrival: 0, potentials: 4 } })); // 15 experience needs a copy
    protocol(stepOne({ cost: { exp: 15, copiesAtArrival: 16, potentials: 4 } })); // and never more copies than experience
    protocol(stepOne({ cost: { exp: 15, copiesAtArrival: 15, potentials: 5 } })); // five potentials is more than the tier
    protocol(stepOne({ cost: { exp: -15, copiesAtArrival: 15, potentials: 4 } }));
    protocol(stepOne({ cost: { exp: 15.5, copiesAtArrival: 15, potentials: 4 } }));
    protocol(stepOne({ cost: { exp: "15", copiesAtArrival: 15, potentials: 4 } }));
    protocol(stepOne({ cost: [15, 15, 4] }));
    // an upgrade is made from the tier it names: its potentials are the tiers between
    const upgrade = (sourceTier, cost) => stepOne({ kind: "upgrade", sourceTier, cost });
    expect(validateFromWorker(upgrade(1, { exp: 14, copiesAtArrival: 1, potentials: 3 }), expectationOf()).cost.potentials).toBe(3);
    protocol(upgrade(1, { exp: 15, copiesAtArrival: 1, potentials: 4 }));
    protocol(upgrade(0, { exp: 14, copiesAtArrival: 1, potentials: 3 }));
  });

  it("is in order as a whole, when the page watches the path: index 0, then 1, 2, ... and none after the end", () => {
    const watch = watchOf();
    expect(validateFromWorker(equipNowStep(), expectationOf(watch)).index).toBe(0);
    expect(validateFromWorker(stepOne(), expectationOf(watch)).index).toBe(1);
    const again = watchOf();
    validateFromWorker(equipNowStep(), expectationOf(again));
    expect(() => validateFromWorker(stepOne({ index: 2 }), expectationOf(again))).toThrow(/protocol/); // 1 comes before 2
    const first = watchOf();
    expect(() => validateFromWorker(stepOne(), expectationOf(first))).toThrow(/protocol/); // and 0 before 1
    const twice = watchOf();
    validateFromWorker(equipNowStep(), expectationOf(twice));
    expect(() => validateFromWorker(equipNowStep(), expectationOf(twice))).toThrow(/protocol/);
    // never more steps than the request asked for
    const capped = createPathWatch(farm({ owned: OWNED_TWO, steps: 1 }));
    validateFromWorker(equipNowStep(), { ...expectationOf(capped), steps: 1 });
    validateFromWorker(stepOne(), { ...expectationOf(capped), steps: 1 });
    expect(() => validateFromWorker(stepOne({ index: 2 }), { ...expectationOf(capped), steps: 1 })).toThrow(/protocol/);
  });

  it("ends at a step that was not found, or at Equip now that has no kit: nothing follows them", () => {
    const notFound = stepOne({ found: false, ident: null, kind: null, sourceTier: null, cost: null, F: null, value: null, gain: null, gainValue: null, kit: null, buffs: [], status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT });
    const watch = watchOf();
    validateFromWorker(equipNowStep(), expectationOf(watch));
    validateFromWorker(notFound, expectationOf(watch));
    expect(() => validateFromWorker({ ...stepOne({ index: 2 }) }, expectationOf(watch))).toThrow(/protocol/);
    const noKit = watchOf();
    validateFromWorker(equipNowStep({ status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT, F: null, value: null, kit: null, buffs: [] }), expectationOf(noKit));
    expect(() => validateFromWorker(stepOne(), expectationOf(noKit))).toThrow(/protocol/);
  });

  it("adds up as a whole: the gain of a step is its value less the value before it, above 0, and the assumed haste is one for the path", () => {
    const protocol = (value, setup = () => {}) => {
      const watch = watchOf();
      validateFromWorker(equipNowStep(), expectationOf(watch));
      setup(watch);
      expect(() => validateFromWorker(value, expectationOf(watch))).toThrow(/protocol/);
    };
    protocol(stepOne({ gain: "29/1", gainValue: 29 })); // 130 less 100 is 30
    protocol(stepOne({ ...exactOf(130), gain: "30/2", gainValue: 15 })); // and a text that is not reduced is no value
    protocol(stepOne({ ...exactOf(100), gain: "0/1", gainValue: 0 })); // a step gains something
    protocol(stepOne({ ...exactOf(90), gain: "-10/1", gainValue: -10 }));
    protocol(stepOne({ gainValue: 31 })); // the number is the text rounded
    protocol(stepOne({ hasteAssumed: 41 })); // the haste of Equip now was 40
    // the second step counts from the first
    const watch = watchOf();
    validateFromWorker(equipNowStep(), expectationOf(watch));
    validateFromWorker(stepOne(), expectationOf(watch));
    const KIT2 = wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [4, "w90011@4"], [21, "w80113@0"]);
    const two = (over = {}) => stepOne({ index: 2, ident: "w90011@4", ...exactOf(145), gain: "15/1", gainValue: 15, kit: KIT2, ...over });
    expect(() => validateFromWorker(two({ gain: "45/1", gainValue: 45 }), expectationOf(watch))).toThrow(/protocol/); // 145 less 100: the path's first value
    expect(validateFromWorker(two(), expectationOf(watch)).index).toBe(2);
  });

  it("wears what is owned and what was acquired and nothing else: an upgrade turns an owned copy into the item, a copy adds one", () => {
    const watch = watchOf();
    validateFromWorker(equipNowStep(), expectationOf(watch));
    // an item that is neither owned nor acquired
    const strange = wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [4, "w55555@4"], [21, "w80113@0"]);
    expect(() => validateFromWorker(stepOne({ kit: strange }), expectationOf(watch))).toThrow(/protocol/);
    // a new item worn twice when one was acquired
    const doubled = wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90009@4"], [3, "w90007@4"], [21, "w80113@0"]);
    expect(() => validateFromWorker(stepOne({ kit: doubled }), expectationOf(watch))).toThrow(/protocol/);
    // an upgrade of a copy that is not owned
    expect(() => validateFromWorker(stepOne({ ident: "w90009@4", kind: "upgrade", sourceTier: 0, cost: { exp: 15, copiesAtArrival: 1, potentials: 4 } }), expectationOf(watch))).toThrow(/protocol/);
    // an upgrade of an owned copy: the ring at +0 is gone from the kit and the ring at +4 stands in its place; a second wear of the source is more than is owned
    const upgraded = wear([0, "w90001@4"], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@4"]);
    const up = stepOne({ ident: "w80113@4", kind: "upgrade", sourceTier: 0, cost: { exp: 15, copiesAtArrival: 1, potentials: 4 }, kit: upgraded });
    expect(validateFromWorker(up, expectationOf(watch)).kind).toBe("upgrade");
    const after = watchOf();
    validateFromWorker(equipNowStep(), expectationOf(after));
    const stillWearing = wear([0, "w90001@4"], [2, "w90007@4"], [3, "w90007@4"], [20, "w80113@0"], [21, "w80113@4"]);
    expect(() => validateFromWorker({ ...up, kit: stillWearing }, expectationOf(after))).toThrow(/protocol/);
  });
});

describe("the results of the modes", () => {
  const OWNED_SET = [["w90001@4", 1], ["w90007@4", 2], ["w80113@0", 1]];
  const KIT0 = wear([0, "w90001@4"], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@0"]);

  describe("of a farm path", () => {
    const expectation = { id: 4, kind: "scenario", mode: "farm-path", owned: OWNED_SET, steps: 3 };
    const result = (over = {}) => ({ v: 1, type: "result", id: 4, kind: "scenario", mode: "farm-path", stopped: "limit", steps: 3, hasteAssumed: 40, elapsedMs: 123.5, ...over });

    it("is accepted: why the path stopped, how many steps it made, the haste it assumed and the time it took", () => {
      expect(validateFromWorker(result(), expectation)).toEqual(result());
      for (const stopped of ["no-gain", "time", "stopped"]) expect(validateFromWorker(result({ stopped, steps: 2 }), expectation).stopped).toBe(stopped);
      expect(validateFromWorker(result({ stopped: "stopped", steps: 0 }), expectation).steps).toBe(0);
    });

    it("is refused with anything else", () => {
      const protocol = (value) => expect(() => validateFromWorker(value, expectation)).toThrow(/protocol/);
      protocol(result({ stopped: "done" }));
      protocol(result({ stopped: "Limit" }));
      protocol(result({ stopped: null }));
      protocol(result({ steps: 3, stopped: "no-gain" })); // a path that made every step it was asked for ended at its limit
      protocol(result({ steps: 9 }));
      protocol(result({ steps: -1 }));
      protocol(result({ steps: 1.5 }));
      protocol(result({ steps: "3" }));
      protocol(result({ hasteAssumed: 1001 }));
      protocol(result({ hasteAssumed: 40.5 }));
      protocol(result({ elapsedMs: -1 }));
      protocol(result({ elapsedMs: "1" }));
      protocol(result({ F: "1/1" })); // the fields of another mode
      protocol(result({ rows: [] }));
      protocol(result({ mode: "equip-now" }));
      protocol(result({ id: 5 }));
      protocol({ ...result(), kind: "model" });
      expect(() => validateFromWorker(result(), { id: 4, kind: "scenario", mode: "best-sets" })).toThrow(/protocol/);
      expect(() => validateFromWorker(result(), { id: 4, kind: "scenario", mode: "equip-now" })).toThrow(/protocol/);
    });

    it("agrees with the steps the page saw when it watches the path: the count, and the reason in the light of it", () => {
      const watch = createPathWatch(farm({ owned: OWNED_SET, steps: 3 }));
      const watched = { ...expectation, path: watch };
      validateFromWorker({ v: 1, type: "step", id: 4, index: 0, status: "optimal", proven: true, label: null, F: "100/1", value: 100, kit: [...KIT0], buffs: [43], hasteAssumed: 40 }, watched);
      const KIT1 = wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@0"]);
      validateFromWorker(
        { v: 1, type: "step", id: 4, index: 1, found: true, ident: "w90009@4", kind: "new", sourceTier: null, cost: null, F: "130/1", value: 130, gain: "30/1", gainValue: 30, kit: KIT1, buffs: [43], hasteAssumed: 40, status: "optimal", proven: true, label: null },
        watched,
      );
      const protocol = (value) => expect(() => validateFromWorker(value, watched)).toThrow(/protocol/);
      protocol(result({ steps: 2, stopped: "no-gain" })); // the page saw one step
      protocol(result({ steps: 0, stopped: "stopped" }));
      protocol(result({ steps: 1, stopped: "limit" })); // three steps were asked for: it did not run its course
      protocol(result({ steps: 1, hasteAssumed: 41, stopped: "no-gain" }));
      expect(validateFromWorker(result({ steps: 1, stopped: "no-gain" }), watched).steps).toBe(1);
      expect(validateFromWorker(result({ steps: 1, stopped: "stopped" }), watched).stopped).toBe("stopped");
      expect(validateFromWorker(result({ steps: 1, stopped: "time" }), watched).stopped).toBe("time");
    });

    it("says 'time' when the last step was not found, and not 'limit' or 'no-gain'", () => {
      const watch = createPathWatch(farm({ owned: OWNED_SET, steps: 3 }));
      const watched = { ...expectation, path: watch };
      validateFromWorker({ v: 1, type: "step", id: 4, index: 0, status: "optimal", proven: true, label: null, F: "100/1", value: 100, kit: [...KIT0], buffs: [43], hasteAssumed: 40 }, watched);
      validateFromWorker(
        { v: 1, type: "step", id: 4, index: 1, found: false, ident: null, kind: null, sourceTier: null, cost: null, F: null, value: null, gain: null, gainValue: null, kit: null, buffs: [], hasteAssumed: 40, status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT },
        watched,
      );
      for (const stopped of ["limit", "no-gain", "stopped"]) expect(() => validateFromWorker(result({ steps: 1, stopped }), watched)).toThrow(/protocol/);
      expect(validateFromWorker(result({ steps: 1, stopped: "time" }), watched).stopped).toBe("time");
    });

    it("is refused when Equip now never came: a path begins with it, whatever the result says about the rest", () => {
      const watched = { ...expectation, path: createPathWatch(farm({ owned: OWNED_SET, steps: 3 })) };
      for (const stopped of ["stopped", "no-gain", "time", "limit"]) expect(() => validateFromWorker(result({ steps: 0, stopped }), watched), stopped).toThrow(/protocol/);
    });
  });

  describe("of best sets", () => {
    const expectation = { id: 4, kind: "scenario", mode: "best-sets", owned: OWNED_SET, k: 2 };
    const KIT2 = wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [4, "w90011@4"], [21, "w80113@0"]);
    const set = (over = {}) => ({
      v: 1,
      type: "result",
      id: 4,
      kind: "scenario",
      mode: "best-sets",
      k: 2,
      acquired: [
        { ident: "w90009@4", kind: "new", sourceTier: null, cost: { exp: 0, copiesAtArrival: 0, potentials: 0 } },
        { ident: "w90011@4", kind: "copy", sourceTier: null, cost: { exp: 15, copiesAtArrival: 15, potentials: 4 } },
      ],
      ...exactOf(145),
      gain: "45/1",
      gainValue: 45,
      kit: [...KIT2],
      buffs: [43],
      status: "optimal",
      proven: true,
      label: null,
      baseline: exactOf(100),
      hasteAssumed: 40,
      elapsedMs: 250,
      ...over,
    });

    it("is accepted: what to acquire, the value and the gain over Equip now, the kit and the buffs, and the value of Equip now", () => {
      const original = set();
      const clean = validateFromWorker(original, expectation);
      expect(clean).toEqual(original);
      expect(clean.acquired).not.toBe(original.acquired);
      expect(clean.acquired[0]).not.toBe(original.acquired[0]);
      expect(clean.baseline).not.toBe(original.baseline);
      expect(validateFromWorker(set({ k: 3 }), { ...expectation, k: 3 }).k).toBe(3);
    });

    it("may find nothing to add (the kit of Equip now stands, the gain is 0) and may find no set in time (no kit, no value)", () => {
      const nothing = set({ acquired: [], ...exactOf(100), gain: "0/1", gainValue: 0, kit: [...KIT0] });
      expect(validateFromWorker(nothing, expectation).acquired).toEqual([]);
      const lost = set({ acquired: [], F: null, value: null, gain: null, gainValue: null, kit: null, buffs: [], status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT });
      expect(validateFromWorker(lost, expectation).kit).toBeNull();
      const none = set({ acquired: [], F: null, value: null, gain: null, gainValue: null, kit: null, buffs: [], status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT, baseline: { F: null, value: null } });
      expect(validateFromWorker(none, expectation).baseline).toEqual({ F: null, value: null });
      const late = set({ status: "time_limit", proven: false, label: LABEL_TIME_LIMIT });
      expect(validateFromWorker(late, expectation).label).toBe(LABEL_TIME_LIMIT);
    });

    it("is refused where the answer to Equip now is: the status and the label, the exact value, the kit and the buffs, the haste", () => {
      const protocol = (value) => expect(() => validateFromWorker(value, expectation)).toThrow(/protocol/);
      protocol(set({ status: "optimal", proven: false }));
      protocol(set({ label: LABEL_TIME_LIMIT }));
      protocol(set({ status: "time_limit", proven: false, label: null }));
      protocol(set({ status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT })); // a kit under the label for none
      protocol(set({ F: "290/2", value: 145 }));
      protocol(set({ value: 146 }));
      protocol(set({ F: null, value: null }));
      protocol(set({ kit: KIT2.slice(0, 21) }));
      protocol(set({ buffs: [44, 43] }));
      protocol(set({ hasteAssumed: -1 }));
      protocol(set({ elapsedMs: -1 }));
      protocol(set({ extra: 1 }));
      protocol(set({ steps: 2 })); // a field of the farm path
      protocol(set({ mode: "farm-path" }));
    });

    it("is for the k that was asked for, and lists at most k additions, each as a step names one", () => {
      const protocol = (value, expect_ = expectation) => expect(() => validateFromWorker(value, expect_)).toThrow(/protocol/);
      protocol(set({ k: 3 }));
      protocol(set({ k: 1 }), { ...expectation, k: 1 });
      protocol(set({ acquired: [...set().acquired, { ident: "w90012@4", kind: "new", sourceTier: null, cost: null }] })); // three for k = 2
      protocol(set({ acquired: [{ ident: "w90009", kind: "new", sourceTier: null, cost: null }, set().acquired[1]] }));
      protocol(set({ acquired: [{ ident: "w90009@4", kind: "upgrade", sourceTier: null, cost: null }, set().acquired[1]] }));
      protocol(set({ acquired: [{ ident: "w90009@4", kind: "new", sourceTier: null }, set().acquired[1]] })); // no cost field
      protocol(set({ acquired: [{ ident: "w90009@4", kind: "new", sourceTier: null, cost: null, item: {} }, set().acquired[1]] }));
      protocol(set({ acquired: "w90009@4" }));
      protocol(set({ acquired: [null, set().acquired[1]] }));
    });

    it("adds up: the gain is the value less the value of Equip now, and it is above 0 exactly when something is acquired", () => {
      const protocol = (value) => expect(() => validateFromWorker(value, expectation)).toThrow(/protocol/);
      protocol(set({ gain: "44/1", gainValue: 44 }));
      protocol(set({ gain: "45/1", gainValue: 44 }));
      protocol(set({ acquired: [] })); // a gain with nothing acquired
      protocol(set({ acquired: [], ...exactOf(100), gain: "5/1", gainValue: 5, kit: [...KIT0] }));
      protocol(set({ ...exactOf(90), gain: "-10/1", gainValue: -10 })); // a set is never worth less than Equip now
      protocol(set({ gain: null, gainValue: null })); // a value with no gain
      protocol(set({ baseline: { F: "100/1", value: 99 } }));
      protocol(set({ baseline: { F: "100/1" } }));
      protocol(set({ baseline: { F: "100/1", value: 100, extra: 1 } }));
      protocol(set({ baseline: null }));
      protocol(set({ baseline: { F: null, value: null } })); // no value of Equip now, and a gain over it
    });

    it("wears what is owned and what the set acquires: an upgrade turns an owned copy into the item", () => {
      const protocol = (value) => expect(() => validateFromWorker(value, expectation)).toThrow(/protocol/);
      protocol(set({ kit: wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90009@4"], [3, "w90007@4"], [4, "w90011@4"], [21, "w80113@0"]) })); // two of what one was acquired
      protocol(set({ kit: wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [4, "w77777@4"], [21, "w80113@0"]) })); // nothing of the sort
      const upgrade = [{ ident: "w80113@4", kind: "upgrade", sourceTier: 0, cost: { exp: 15, copiesAtArrival: 1, potentials: 4 } }, { ident: "w80113@4", kind: "copy", sourceTier: null, cost: { exp: 15, copiesAtArrival: 15, potentials: 4 } }];
      const made = set({ acquired: upgrade, kit: wear([0, "w90001@4"], [2, "w90007@4"], [3, "w90007@4"], [20, "w80113@4"], [21, "w80113@4"]) });
      expect(validateFromWorker(made, expectation).acquired).toHaveLength(2);
      protocol({ ...made, kit: wear([0, "w90001@4"], [2, "w90007@4"], [3, "w90007@4"], [19, "w80113@0"], [20, "w80113@4"], [21, "w80113@4"]) }); // the source was turned into the item
      protocol({ ...made, acquired: [upgrade[0], { ...upgrade[0] }, upgrade[1]] });
    });
  });

  describe("of every slot", () => {
    const expectation = { id: 4, kind: "scenario", mode: "every-slot", owned: OWNED_SET, limit: 3 };
    const swap = (ident, delta, deltaValue) => ({ ident, delta, deltaValue });
    const row = (index, current, swaps = []) => ({ place: PLACES[index], index, current, swaps });
    /** The 22 rows; `replace` is `{index: row}` for the rows that are other than the plain ones (a row that is null is a row that is not one). */
    const rows = (replace = {}) =>
      PLACES.map((_, index) => {
        if (index in replace) return replace[index];
        if (index === 0) return row(0, "w90001@4", [swap("w90003@4", "12/1", 12), swap("w90005@4", "1/2", 0.5), swap("w90004@4", "-3/1", -3)]);
        if (index === 1) return row(1, null, [swap("w90002@4", "7/1", 7)]);
        return row(index, null);
      });
    const answer = (over = {}) => ({ v: 1, type: "result", id: 4, kind: "scenario", mode: "every-slot", rows: rows(), elapsedMs: 4.5, ...over });

    it("is accepted: 22 rows, one for each place in the order of a kit, each with the swaps that gain the most", () => {
      const original = answer();
      const clean = validateFromWorker(original, expectation);
      expect(clean).toEqual(original);
      expect(clean.rows).not.toBe(original.rows);
      expect(clean.rows[0].swaps).not.toBe(original.rows[0].swaps);
      expect(clean.rows[0].swaps[0]).not.toBe(original.rows[0].swaps[0]);
      expect(validateFromWorker(answer({ rows: PLACES.map((_, index) => row(index, null)) }), expectation).rows).toHaveLength(22);
    });

    it("takes a swap that gains nothing or loses (a worse item is a swap with a negative gain), and a text with a minus sign", () => {
      const clean = validateFromWorker(answer(), expectation);
      expect(clean.rows[0].swaps.map((entry) => entry.deltaValue)).toEqual([12, 0.5, -3]);
      expect(validateFromWorker(answer({ rows: rows({ 1: row(1, null, [swap("w90002@4", "0/1", 0)]) }) }), expectation).rows[1].swaps[0].delta).toBe("0/1");
    });

    it("is refused with other than 22 rows, in other places or in another order, or with a row that is not a row", () => {
      const protocol = (value) => expect(() => validateFromWorker(value, expectation)).toThrow(/protocol/);
      protocol(answer({ rows: rows().slice(0, 21) }));
      protocol(answer({ rows: [...rows(), row(22, null)] }));
      protocol(answer({ rows: rows().reverse() }));
      protocol(answer({ rows: "rows" }));
      protocol(answer({ rows: rows({ 3: { ...row(3, null), place: "HEAD" } }) })); // the place is the one of its index
      protocol(answer({ rows: rows({ 3: { ...row(3, null), index: 4 } }) }));
      protocol(answer({ rows: rows({ 3: { ...row(3, null), extra: 1 } }) }));
      protocol(answer({ rows: rows({ 3: { place: PLACES[3], index: 3, current: null } }) })); // no swaps
      protocol(answer({ rows: rows({ 3: row(3, "w90001") }) })); // current is an ident or null
      protocol(answer({ rows: rows({ 3: row(3, "__proto__@4") }) }));
      protocol(answer({ rows: rows({ 3: null }) }));
      protocol(answer({ rows: rows({ 3: [] }) }));
      protocol(answer({ extra: 1 }));
      protocol(answer({ steps: 3 }));
      protocol(answer({ elapsedMs: -1 }));
    });

    it("is refused with swaps that are not what a swap is, that are in the wrong order or that are more than the limit", () => {
      const protocol = (value, expect_ = expectation) => expect(() => validateFromWorker(value, expect_)).toThrow(/protocol/);
      const at = (swaps) => answer({ rows: rows({ 2: row(2, null, swaps) }) });
      protocol(at([swap("w90003@4", "12/1", 13)])); // the number is the text rounded
      protocol(at([swap("w90003@4", "24/2", 12)])); // and the text is reduced
      protocol(at([swap("w90003@4", 12, 12)]));
      protocol(at([swap("w90003", "12/1", 12)]));
      protocol(at([swap("w90003@4", "12/1", 12), swap("w90003@4", "7/1", 7)])); // an item once in a place
      protocol(at([swap("w90003@4", "1/1", 1), swap("w90005@4", "2/1", 2)])); // the best first
      protocol(at([swap("w90005@4", "2/1", 2), swap("w90003@4", "2/1", 2)])); // equal gains by key and tier: w90003 before w90005
      protocol(at([swap("w90003@4", "2/1", 2), swap("w90003@3", "2/1", 2)])); // ... and the tier too: 3 before 4
      protocol(at([{ ident: "w90003@4", delta: "1/1" }]));
      protocol(at([{ ...swap("w90003@4", "1/1", 1), item: "x" }]));
      protocol(answer({ rows: rows({ 2: row(2, "w90001@4", [swap("w90001@4", "1/1", 1)]) }) })); // the item worn in a place is not offered for it
      protocol(at([swap("w90003@4", "4/1", 4), swap("w90004@4", "3/1", 3), swap("w90005@4", "2/1", 2), swap("w90006@4", "1/1", 1)])); // four swaps for a limit of 3
      expect(validateFromWorker(at([swap("w90003@4", "4/1", 4), swap("w90004@4", "3/1", 3), swap("w90005@4", "2/1", 2), swap("w90006@4", "1/1", 1)]), { ...expectation, limit: 4 }).rows[2].swaps).toHaveLength(4);
      expect(validateFromWorker(at([swap("w90003@3", "2/1", 2), swap("w90003@4", "2/1", 2)]), expectation).rows[2].swaps).toHaveLength(2); // equal gains: by tier
      expect(validateFromWorker(at([swap("w90003@4", "2/1", 2), swap("w90005@4", "2/1", 2)]), expectation).rows[2].swaps).toHaveLength(2); // ... by key
    });
  });
});

// ---- the results, held to the tier mode and the kit that the request had ---------------------------------------------------------------------

describe("the results held to the tier mode and the kit of the request", () => {
  // What the request named is what the answer is checked against (the client passes the tier mode and, for Every slot, the kit): an item is acquired at the tier of the tier
  // mode (ready4: +4; fixed N: +N; arrives D: +D for an item that drops and +0 for any other, so one of the two), and a set wears what it acquires; the item a row says is
  // worn in its place is the one the request's kit has there, and a swap offers an item the visitor owns (at the tier it owns it at) or one at the tier of the mode.
  const TIER_MODES = [
    { tierMode: { mode: "ready4" }, fits: [4], refused: [0, 1, 3, 5, 10] },
    { tierMode: { mode: "fixed", N: 10 }, fits: [10], refused: [0, 4, 9] },
    { tierMode: { mode: "fixed", N: 0 }, fits: [0], refused: [1, 4, 10] },
    { tierMode: { mode: "arrives", D: 2 }, fits: [2, 0], refused: [1, 3, 4, 10] },
    { tierMode: { mode: "arrives", D: 0 }, fits: [0], refused: [1, 4, 10] },
    { tierMode: { mode: "arrives", D: 4 }, fits: [4, 0], refused: [1, 2, 3, 10] },
  ];
  const label = (tierMode) => JSON.stringify(tierMode);

  describe("the tier of what is acquired", () => {
    const KIT_OF = (ident) => wear([0, "w90001@4"], [1, ident], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@0"]);
    const stepAt = (tier) => ({
      v: 1,
      type: "step",
      id: 4,
      index: 1,
      found: true,
      ident: `w90009@${tier}`,
      kind: "new",
      sourceTier: null,
      cost: null,
      ...exactOf(130),
      gain: "30/1",
      gainValue: 30,
      kit: KIT_OF(`w90009@${tier}`),
      buffs: [43],
      hasteAssumed: 40,
      status: "optimal",
      proven: true,
      label: null,
    });
    const stepExpectation = (tierMode) => ({ id: 4, kind: "scenario", mode: "farm-path", owned: OWNED, steps: 3, tierMode });

    it("is the tier of the mode for a step: +4 for ready4, +N for fixed, +D or +0 for arrives", () => {
      for (const { tierMode, fits, refused } of TIER_MODES) {
        for (const tier of fits) expect(validateFromWorker(stepAt(tier), stepExpectation(tierMode)).ident, `${label(tierMode)} at +${tier}`).toBe(`w90009@${tier}`);
        for (const tier of refused) expect(() => validateFromWorker(stepAt(tier), stepExpectation(tierMode)), `${label(tierMode)} at +${tier}`).toThrow(/protocol/);
      }
    });

    it("is the same for an upgrade, which brings an owned copy to the tier of the mode", () => {
      const upgrade = (tier) => ({ ...stepAt(tier), kind: "upgrade", sourceTier: 0, ident: "w80113@" + tier, cost: { exp: 2 ** tier - 1, copiesAtArrival: Math.ceil((2 ** tier - 1) / 16), potentials: tier }, kit: wear([0, "w90001@4"], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@" + tier]) });
      const mode = { mode: "fixed", N: 3 };
      expect(validateFromWorker(upgrade(3), stepExpectation(mode)).ident).toBe("w80113@3");
      expect(() => validateFromWorker(upgrade(4), stepExpectation(mode))).toThrow(/protocol/);
    });

    it("is checked only when the expectation has the tier mode: a model request, Equip now and the steps of an older caller go as before", () => {
      expect(validateFromWorker(stepAt(7), { id: 4, kind: "scenario", mode: "farm-path", owned: OWNED, steps: 3 }).ident).toBe("w90009@7");
    });

    const KIT2 = wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [4, "w90011@4"], [21, "w80113@0"]);
    const setAt = (tier, over = {}) => ({
      v: 1,
      type: "result",
      id: 4,
      kind: "scenario",
      mode: "best-sets",
      k: 2,
      acquired: [
        { ident: `w90009@${tier}`, kind: "new", sourceTier: null, cost: null },
        { ident: `w90011@${tier}`, kind: "copy", sourceTier: null, cost: null },
      ],
      ...exactOf(145),
      gain: "45/1",
      gainValue: 45,
      kit: wear([0, "w90001@4"], [1, `w90009@${tier}`], [2, "w90007@4"], [3, "w90007@4"], [4, `w90011@${tier}`], [21, "w80113@0"]),
      buffs: [43],
      status: "optimal",
      proven: true,
      label: null,
      baseline: exactOf(100),
      hasteAssumed: 40,
      elapsedMs: 250,
      ...over,
    });
    const setExpectation = (tierMode) => ({ id: 4, kind: "scenario", mode: "best-sets", owned: OWNED, k: 2, tierMode });

    it("is the tier of the mode for each addition of a best set", () => {
      for (const { tierMode, fits, refused } of TIER_MODES) {
        for (const tier of fits) expect(validateFromWorker(setAt(tier), setExpectation(tierMode)).acquired, `${label(tierMode)} at +${tier}`).toHaveLength(2);
        for (const tier of refused) expect(() => validateFromWorker(setAt(tier), setExpectation(tierMode)), `${label(tierMode)} at +${tier}`).toThrow(/protocol/);
      }
      // one addition at the tier and one at another is a set that breaks the rule
      const mixed = setAt(4, { acquired: [setAt(4).acquired[0], { ident: "w90011@3", kind: "copy", sourceTier: null, cost: null }], kit: wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [4, "w90011@3"], [21, "w80113@0"]) });
      expect(() => validateFromWorker(mixed, setExpectation({ mode: "ready4" }))).toThrow(/protocol/);
    });
  });

  describe("what a best set wears", () => {
    const expectation = { id: 4, kind: "scenario", mode: "best-sets", owned: OWNED, k: 2, tierMode: { mode: "ready4" } };
    const acquire = (ident, kind = "new") => ({ ident, kind, sourceTier: null, cost: { exp: 0, copiesAtArrival: 0, potentials: 0 } });
    const set = (over = {}) => ({
      v: 1,
      type: "result",
      id: 4,
      kind: "scenario",
      mode: "best-sets",
      k: 2,
      acquired: [acquire("w90009@4"), acquire("w90011@4", "copy")],
      ...exactOf(145),
      gain: "45/1",
      gainValue: 45,
      kit: wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [4, "w90011@4"], [21, "w80113@0"]),
      buffs: [43],
      status: "optimal",
      proven: true,
      label: null,
      baseline: exactOf(100),
      hasteAssumed: 40,
      elapsedMs: 250,
      ...over,
    });

    it("includes each addition it lists: a kit that does not wear one of them is refused, as a step's kit is", () => {
      expect(validateFromWorker(set(), expectation).acquired).toHaveLength(2);
      const lacking = wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@0"]); // nothing of w90011
      expect(() => validateFromWorker(set({ kit: lacking }), expectation)).toThrow(/protocol/);
      const other = wear([0, "w90001@4"], [2, "w90007@4"], [3, "w90007@4"], [4, "w90011@4"], [21, "w80113@0"]); // nothing of w90009
      expect(() => validateFromWorker(set({ kit: other }), expectation)).toThrow(/protocol/);
    });

    it("includes as many copies as it lists additions of one ident", () => {
      const twice = set({ acquired: [acquire("w90009@4"), acquire("w90009@4", "copy")], kit: wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90009@4"], [3, "w90007@4"], [21, "w80113@0"]) });
      expect(validateFromWorker(twice, expectation).acquired).toHaveLength(2);
      const once = { ...twice, kit: wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@0"]) };
      expect(() => validateFromWorker(once, expectation)).toThrow(/protocol/);
    });

    it("includes the item an upgrade makes: the owned copy is turned into it, and it stands in the kit", () => {
      const up = { ident: "w80113@4", kind: "upgrade", sourceTier: 0, cost: { exp: 15, copiesAtArrival: 1, potentials: 4 } };
      const made = set({ acquired: [up], kit: wear([0, "w90001@4"], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@4"]), ...exactOf(110), gain: "10/1", gainValue: 10 });
      expect(validateFromWorker(made, expectation).acquired[0].kind).toBe("upgrade");
      const kept = { ...made, kit: wear([0, "w90001@4"], [2, "w90007@4"], [3, "w90007@4"]) }; // the upgraded item is not worn
      expect(() => validateFromWorker(kept, expectation)).toThrow(/protocol/);
    });

    it("lists nothing when there is no kit, and then there is nothing to wear", () => {
      const lost = set({ acquired: [], F: null, value: null, gain: null, gainValue: null, kit: null, buffs: [], status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT });
      expect(validateFromWorker(lost, expectation).kit).toBeNull();
    });
  });

  describe("the item worn in a place of Every slot", () => {
    const expectation = { id: 4, kind: "scenario", mode: "every-slot", owned: OWNED, limit: 3, tierMode: { mode: "ready4" }, kit: KIT };
    const swap = (ident, delta = "1/1", deltaValue = 1) => ({ ident, delta, deltaValue });
    /** The 22 rows of the request's kit; `replace` is `{index: row}`. */
    const rowsOf = (kit, replace = {}) => PLACES.map((place, index) => replace[index] ?? { place, index, current: kit[index], swaps: [] });
    const answer = (rows) => ({ v: 1, type: "result", id: 4, kind: "scenario", mode: "every-slot", rows, elapsedMs: 4.5 });

    it("is the item the request's kit has there: each row, empty places included", () => {
      expect(validateFromWorker(answer(rowsOf(KIT)), expectation).rows.map((row) => row.current)).toEqual(KIT);
      for (const at of [0, 1, 2, 3, 10, 21]) {
        const wrong = KIT[at] === null ? "w90002@4" : null;
        expect(() => validateFromWorker(answer(rowsOf(KIT, { [at]: { place: PLACES[at], index: at, current: wrong, swaps: [] } })), expectation), `place ${at}: another item or none`).toThrow(/protocol/);
      }
      // another item of the same key, at another tier, is not it
      expect(() => validateFromWorker(answer(rowsOf(KIT, { 0: { place: PLACES[0], index: 0, current: "w90001@3", swaps: [] } })), expectation)).toThrow(/protocol/);
      // and an item worn where the request's kit has another one
      expect(() => validateFromWorker(answer(rowsOf(KIT, { 2: { place: PLACES[2], index: 2, current: "w90001@4", swaps: [] } })), expectation)).toThrow(/protocol/);
    });

    it("is not checked when the expectation has no kit", () => {
      const { kit, ...without_ } = expectation;
      expect(validateFromWorker(answer(rowsOf(new Array(22).fill(null))), without_).rows).toHaveLength(22);
    });
  });

  describe("the items a swap offers", () => {
    const swap = (ident, delta = "1/1", deltaValue = 1) => ({ ident, delta, deltaValue });
    const rowsWith = (swaps, at = 4) => PLACES.map((place, index) => ({ place, index, current: KIT[index], swaps: index === at ? swaps : [] }));
    const answer = (rows) => ({ v: 1, type: "result", id: 4, kind: "scenario", mode: "every-slot", rows, elapsedMs: 4.5 });
    const expectationOf = (tierMode, owned = OWNED) => ({ id: 4, kind: "scenario", mode: "every-slot", owned, limit: 3, tierMode, kit: KIT });
    const offers = (ident, tierMode, owned) => validateFromWorker(answer(rowsWith([swap(ident)])), expectationOf(tierMode, owned)).rows[4].swaps.map((entry) => entry.ident);
    /** The owned set with a copy to spare of the ring-like items the kit wears (the kit wears all of OWNED). */
    const SPARE = [["w90001@4", 1], ["w90007@4", 3], ["w80113@0", 2]];

    it("is an item at the tier of the mode, whatever the visitor owns", () => {
      for (const { tierMode, fits, refused } of TIER_MODES) {
        for (const tier of fits) expect(offers(`w90009@${tier}`, tierMode), `${label(tierMode)} at +${tier}`).toEqual([`w90009@${tier}`]);
        for (const tier of refused) expect(() => offers(`w90009@${tier}`, tierMode), `${label(tierMode)} at +${tier}`).toThrow(/protocol/);
      }
    });

    it("is also an item the visitor owns, at the tier the visitor owns it at, while a copy is free: the pool is the candidates and the owned items", () => {
      const ready4 = { mode: "ready4" };
      expect(offers("w80113@0", ready4, SPARE)).toEqual(["w80113@0"]); // owned at +0 (twice, one worn), offered at +0 though the mode is +4
      expect(offers("w90007@4", ready4)).toEqual(["w90007@4"]);
      expect(() => offers("w80113@1", ready4)).toThrow(/protocol/); // the same key at a tier that is neither owned nor the mode's
      expect(() => offers("w80113@5", ready4)).toThrow(/protocol/);
      expect(offers("w80113@0", { mode: "fixed", N: 10 }, SPARE)).toEqual(["w80113@0"]);
    });

    it("is an item the visitor owns beyond the copies the kit leaves free only when the tier mode could give it: an owned item that cannot be a candidate is held to its count", () => {
      const ready4 = { mode: "ready4" };
      const fixed10 = { mode: "fixed", N: 10 };
      // w80113@0 is owned once and the kit wears it (in place 21): at +0 it is no candidate of ready4 or fixed 10, so there is no copy to take for another place
      expect(() => offers("w80113@0", ready4)).toThrow(/protocol/);
      expect(() => offers("w80113@0", fixed10)).toThrow(/protocol/);
      expect(offers("w80113@0", ready4, SPARE)).toEqual(["w80113@0"]); // a second copy owned: one is free
      // w90007@4 is owned twice and the kit wears both: it is no candidate of fixed 10, but at +4 it may be one of ready4, which the page cannot tell, so it is not refused there
      expect(() => offers("w90007@4", fixed10)).toThrow(/protocol/);
      expect(offers("w90007@4", fixed10, SPARE)).toEqual(["w90007@4"]);
      expect(offers("w90007@4", ready4)).toEqual(["w90007@4"]);
      // under "arrives" a candidate is at +D or +0: an item owned at either tier may be one
      expect(offers("w80113@0", { mode: "arrives", D: 2 })).toEqual(["w80113@0"]);
      expect(() => offers("w90007@4", { mode: "arrives", D: 2 })).toThrow(/protocol/);
    });

    it("lets an owned item that cannot be a candidate in while the kit wears fewer copies than are owned, and not once it wears as many", () => {
      const fixed10 = { mode: "fixed", N: 10 }; // an item at +4 is no candidate of it
      const kitWith = (...wornAt) => PLACES.map((_, index) => (wornAt.includes(index) ? "w90007@4" : null));
      const answerFor = (kit, at) => answer(PLACES.map((place, index) => ({ place, index, current: kit[index], swaps: index === at ? [swap("w90007@4")] : [] })));
      const asked = (kit, owned, at) => validateFromWorker(answerFor(kit, at), { id: 4, kind: "scenario", mode: "every-slot", owned, limit: 3, tierMode: fixed10, kit });
      const copies = (count) => [["w90007@4", count]];
      expect(asked(kitWith(2), copies(2), 3).rows[3].swaps).toHaveLength(1); // two owned, one worn in another place: one is free
      expect(asked(kitWith(), copies(1), 3).rows[3].swaps).toHaveLength(1); // one owned, none worn
      expect(() => asked(kitWith(2), copies(1), 3)).toThrow(/protocol/); // one owned and worn in another place
      expect(() => asked(kitWith(2, 3), copies(2), 4)).toThrow(/protocol/); // two owned, both worn in other places
      expect(asked(kitWith(2, 3), copies(3), 4).rows[4].swaps).toHaveLength(1); // three owned, two worn
    });

    it("is held to the copies the kit wears only when the expectation has the kit as well as the tier mode and the owned set", () => {
      const rows = answer(rowsWith([swap("w90007@4")])); // owned twice, both worn in the kit: beyond its count under fixed 10
      const fixed10 = { mode: "fixed", N: 10 };
      expect(() => validateFromWorker(rows, expectationOf(fixed10))).toThrow(/protocol/);
      const { kit, ...withoutKit } = expectationOf(fixed10);
      expect(validateFromWorker(rows, withoutKit).rows[4].swaps).toHaveLength(1); // the copies it wears are not known: not checked
      const { owned, ...withoutOwned } = expectationOf(fixed10);
      expect(validateFromWorker(rows, withoutOwned).rows[4].swaps).toHaveLength(1);
    });

    it("is checked only when the expectation has the tier mode and the owned set", () => {
      const rows = rowsWith([swap("w90009@9")]);
      expect(validateFromWorker(answer(rows), { id: 4, kind: "scenario", mode: "every-slot", owned: OWNED, limit: 3 }).rows[4].swaps).toHaveLength(1);
      expect(validateFromWorker(answer(rows), { id: 4, kind: "scenario", mode: "every-slot", limit: 3, tierMode: { mode: "ready4" } }).rows[4].swaps).toHaveLength(1);
    });
  });
});
