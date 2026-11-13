// The four Upgrade modes of the worker under weights, held to Python's reference. fixtures/site/weighted.json (pipeline/tests/engine_fixture.py makes it, and
// test_site_engine_fixture.py keeps it current) has the Equip now scenarios of the site fixture, each with weights drawn from a fixed seed (the sliders at x0.5 and x2, custom
// weights, a regen window) and a tier mode, and what upgrade.equip_now, farm_path, best_sets and every_slot give for a profile whose weights are roles.weights_override's.
// A request of the mode with the same `weights` must give that answer: the exact value as a reduced p/q text, the kit place for place, the optional buffs, the haste assumed
// and, for a path, every step (the item, how it is got, the value and the gain), for the best sets what they acquire and for Every slot every swap.
//
// The weights are the best kit's: the same function composes them on the role's own for the five modes (bestkit.js, `viewProfile`), a choice the bundle does not have is a bad
// request, and weights that are the role's own change nothing (they share the session of a request with none).

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { validateFromWorker } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { BUNDLE_BYTES, EQUIP_NOW, SLUG, WEIGHTED, makeSite } from "./engine-site-fixture.mjs";
import { harness, pageChecks } from "./best-kit-harness.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE = (name) => readFileSync(resolve(ROOT, "pipeline/trioforge/site/static/engine", name), "utf8");

const pick = (object, keys) => Object.fromEntries(keys.map((key) => [key, object[key]]));
const ANSWER = ["F", "value", "kit", "buffs", "hasteAssumed"];
const START = ["F", "value", "kit", "buffs"];
const STEP = ["ident", "kind", "sourceTier", "F", "value", "gain", "gainValue", "kit", "buffs", "hasteAssumed"];
const stepsOf = (messages) => messages.filter((message) => message.type === "step");
const strip = ({ id, elapsedMs, ...rest }) => rest;

const request = (c, mode, over = {}) => ({
  v: 1,
  kind: "scenario",
  trio: SLUG,
  level: 50,
  mode,
  scenario: { ...c.scenario },
  owned: c.owned.map((pair) => [...pair]),
  weights: structuredClone(c.weights),
  budgetMs: 120_000,
  ...over,
});
const equip = (c, over) => request(c, "equip-now", over);
const farm = (c, over) => request(c, "farm-path", { tierMode: { ...c.tierMode }, steps: c.farmPath.steps, ...over });
const sets = (c, k, over) => request(c, "best-sets", { tierMode: { ...c.tierMode }, k, ...over });
const slots = (c, over) => request(c, "every-slot", { tierMode: { ...c.tierMode }, kit: [...c.everySlot.kit], buffs: [...c.everySlot.buffs], limit: c.everySlot.limit, ...over });
/** The same request with no weights: the role's own. */
const plain = (built) => {
  const { weights, ...rest } = built;
  return rest;
};

describe("the reference", () => {
  it("has a weighted case for each Equip now scenario, in the three tier modes, with every kind of weight and every kind of step", () => {
    expect(WEIGHTED).toMatchObject({ trio: SLUG, level: 50 });
    expect(WEIGHTED.cases.length).toBeGreaterThanOrEqual(6);
    expect(new Set(WEIGHTED.cases.map((c) => c.scenario.race))).toEqual(new Set(EQUIP_NOW.cases.map((c) => c.scenario.race)));
    expect(new Set(WEIGHTED.cases.map((c) => c.tierMode.mode))).toEqual(new Set(["ready4", "arrives", "fixed"]));
    expect(new Set(WEIGHTED.cases.flatMap((c) => Object.keys(c.weights.multipliers)))).toEqual(new Set(["AC", "MANA", "ATK+HASTE", "SV", "regen"]));
    expect(WEIGHTED.cases.some((c) => c.weights.custom !== undefined) && WEIGHTED.cases.some((c) => c.weights.regenT !== undefined)).toBe(true);
    expect(WEIGHTED.cases.every((c) => c.farmPath.path.length >= 1 && c.bestSets.every((s) => s.acquired.length >= 1))).toBe(true);
    expect(WEIGHTED.cases.some((c) => c.everySlot.rows.some((row) => row.swaps.length > 0))).toBe(true);
  });
});

describe("the worker's Equip now with the weights of a request", () => {
  for (const c of WEIGHTED.cases) {
    it(`gives Python's answer for ${c.name}`, async () => {
      const h = harness({ solver: highs });
      await h.start();
      const built = equip(c);
      const { id, last, messages } = await h.ask(built);
      expect(last).toMatchObject({ type: "result", mode: "equip-now", status: "optimal", proven: true, label: null });
      expect(pick(last, ANSWER)).toEqual(pick(c.equipNow, ANSWER)); // the exact value, the kit place for place, the buffs, the haste
      expect(pageChecks(built, id, messages).at(-1).F).toBe(c.equipNow.F);
    });
  }

  it("moves the answer from the role's own, which is the answer of the scenario without weights", async () => {
    const h = harness({ solver: highs });
    await h.start();
    for (const c of WEIGHTED.cases) {
      const own = EQUIP_NOW.cases.find((other) => JSON.stringify(other.scenario) === JSON.stringify(c.scenario));
      const got = (await h.ask(plain(equip(c)))).last;
      expect(pick(got, ANSWER), c.name).toEqual(pick(own, ANSWER));
      expect(got.F, `${c.name}: the weights move the value`).not.toBe(c.equipNow.F);
    }
  });
});

describe("the worker's farm path with the weights of a request", () => {
  for (const c of WEIGHTED.cases) {
    it(`takes Python's steps for ${c.name}`, async () => {
      const h = harness({ solver: highs });
      await h.start();
      const built = farm(c);
      const { id, last, messages } = await h.ask(built);
      const steps = stepsOf(pageChecks(built, id, messages)); // every message is what the page accepts, and the path is watched as a whole
      expect(steps.map((step) => step.index)).toEqual(Array.from({ length: c.farmPath.path.length + 1 }, (_, at) => at));
      // Equip now is the start of the path, at the haste of the session
      expect(pick(steps[0], START)).toEqual(c.farmPath.start);
      expect(steps[0]).toMatchObject({ status: "optimal", proven: true, label: null, hasteAssumed: c.equipNow.hasteAssumed });
      // and each step is the best single addition after the steps before it: the item, how it is got, the value, the gain, the kit, the buffs
      expect(steps.slice(1).map((step) => pick(step, STEP))).toEqual(c.farmPath.path);
      for (const step of steps.slice(1)) expect(step).toMatchObject({ found: true, status: "optimal", proven: true, label: null });
      expect(last).toMatchObject({ type: "result", mode: "farm-path", stopped: c.farmPath.stopped, steps: c.farmPath.path.length, hasteAssumed: c.equipNow.hasteAssumed });
    });
  }

  it("moves the first step from the role's own, as the weights move the value", async () => {
    const h = harness({ solver: highs });
    await h.start();
    let moved = 0;
    for (const c of WEIGHTED.cases) {
      const own = stepsOf((await h.ask(plain(farm(c)))).messages);
      expect(own[0].F, `${c.name}: Equip now at the session's haste`).not.toBe(c.farmPath.start.F);
      if (own[1].ident !== c.farmPath.path[0].ident || own[1].F !== c.farmPath.path[0].F) moved += 1;
    }
    expect(moved).toBe(WEIGHTED.cases.length);
  });
});

describe("the worker's best sets with the weights of a request", () => {
  for (const c of WEIGHTED.cases) {
    for (const k of [2, 3]) {
      it(`gives Python's best ${k} sets for ${c.name}`, async () => {
        const h = harness({ solver: highs });
        await h.start();
        const built = sets(c, k);
        const { id, last, messages } = await h.ask(built);
        expect(last).toMatchObject({ type: "result", mode: "best-sets", k, status: "optimal", proven: true, label: null });
        const got = {
          k: last.k,
          acquired: last.acquired.map(({ ident, kind, sourceTier }) => ({ ident, kind, sourceTier })),
          ...pick(last, ["F", "value", "gain", "gainValue", "kit", "buffs", "hasteAssumed"]),
          baseline: last.baseline,
        };
        expect(got).toEqual(c.bestSets.find((set) => set.k === k));
        expect(pageChecks(built, id, messages).at(-1).F).toBe(got.F);
      });
    }
  }
});

describe("the worker's Every slot with the weights of a request", () => {
  for (const c of WEIGHTED.cases) {
    it(`gives Python's swaps for every place for ${c.name}`, async () => {
      const h = harness({ solver: highs });
      await h.start();
      const built = slots(c);
      const { id, last, messages } = await h.ask(built);
      expect(last).toMatchObject({ type: "result", mode: "every-slot" });
      const rows = last.rows.map((row) => ({
        place: row.place,
        index: row.index,
        current: row.current,
        swaps: row.swaps.map(({ ident, delta, deltaValue }) => ({ ident, delta, deltaValue })),
      }));
      expect(rows).toEqual(c.everySlot.rows); // the same gains, exactly, in the same order
      expect(pageChecks(built, id, messages).at(-1).rows).toHaveLength(22);
    });
  }

  it("moves the swaps from the role's own: the same kit is worth other gains", async () => {
    const h = harness({ solver: highs });
    await h.start();
    for (const c of WEIGHTED.cases) {
      const own = (await h.ask(plain(slots(c)))).last;
      const deltas = (rows) => JSON.stringify(rows.map((row) => row.swaps.map((swap) => swap.delta)));
      expect(deltas(own.rows), c.name).not.toBe(deltas(c.everySlot.rows));
    }
  });
});

describe("weights that are the role's own", () => {
  const [C0] = WEIGHTED.cases;
  const SPELLED = [
    ["none at all", {}],
    ["every slider at x1, no custom weight and no window", { multipliers: { AC: 1, MANA: 1, "ATK+HASTE": 1, SV: 1, regen: 1 }, custom: {}, regenT: null }],
    ["a window of null", { regenT: null }],
    ["one slider at x1", { multipliers: { AC: 1 } }],
  ];

  for (const mode of ["equip-now", "farm-path", "best-sets", "every-slot"]) {
    const build = (c, over) => ({ "equip-now": equip, "farm-path": farm, "best-sets": (x, o) => sets(x, 2, o), "every-slot": slots })[mode](c, over);
    it(`change nothing in ${mode}: the answer is the answer with no weights, and they share its session`, async () => {
      const h = harness({ solver: highs });
      await h.start();
      const none = await h.ask(plain(build(C0)));
      const sessions = h.scenarios.stats().sessions;
      for (const [name, weights] of SPELLED) {
        const got = await h.ask(build(C0, { weights }));
        const comparable = (answer) => ({ messages: answer.messages.map(strip), last: strip(answer.last) });
        expect(comparable(got).last, name).toEqual(comparable(none).last);
        expect(stepsOf(got.messages).map(strip), name).toEqual(stepsOf(none.messages).map(strip));
        expect(h.scenarios.stats().sessions, `${name}: no new session`).toBe(sessions);
      }
    });
  }

  it("are still held to the bundle's rules: a slider group there is not is refused at x1 as at x2", async () => {
    const h = harness({ solver: highs });
    await h.start();
    for (const weights of [{ multipliers: { NOPE: 1 } }, { custom: { NOPE: 0 } }]) {
      expect((await h.ask(equip(C0, { weights }))).last, JSON.stringify(weights)).toMatchObject({ type: "error", code: "bad-request" });
    }
  });
});

describe("the session of a request with weights", () => {
  const [C0, C1] = WEIGHTED.cases;

  it("is kept for the same weights and made again for others, in whatever order they come", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const stats = () => h.scenarios.stats();
    const a = (await h.ask(equip(C0))).last;
    expect(stats()).toMatchObject({ sessions: 1, sessionsClosed: 0 });
    await h.ask(farm(C0)); // another mode, the same scenario and weights: the same session
    await h.ask(slots(C0));
    expect(stats()).toMatchObject({ sessions: 1, sessionsClosed: 0 });
    const other = (await h.ask(equip(C0, { weights: C1.weights }))).last; // the weights of another case, for the scenario of this one
    expect(stats()).toMatchObject({ sessions: 2, sessionsClosed: 1 });
    expect(other.F).not.toBe(a.F);
    const again = (await h.ask(equip(C0))).last;
    expect(stats()).toMatchObject({ sessions: 3, sessionsClosed: 2 });
    expect(strip(again)).toEqual(strip(a)); // the very answer again
    const own = (await h.ask(plain(equip(C0)))).last;
    expect(stats()).toMatchObject({ sessions: 4 });
    expect(own.F).not.toBe(a.F);
  });

  it("is made for the weights in effect, whatever order the tables are written in", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const c = WEIGHTED.cases.find((candidate) => candidate.weights.custom !== undefined && Object.keys(candidate.weights.multipliers).length >= 2);
    const reversed = {
      ...(c.weights.regenT === undefined ? {} : { regenT: c.weights.regenT }),
      custom: Object.fromEntries(Object.entries(c.weights.custom).reverse()),
      multipliers: Object.fromEntries(Object.entries(c.weights.multipliers).reverse()),
    };
    const first = (await h.ask(equip(c))).last;
    const second = (await h.ask(equip(c, { weights: reversed }))).last;
    expect(strip(second)).toEqual(strip(first));
    expect(h.scenarios.stats().sessions, "one session for the one set of weights").toBe(1);
  });

  it("does not leak a request's weights into the next one: a request after weights has the role's own, and the candidates are not made again for weights", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const c = WEIGHTED.cases[0];
    await h.ask(farm(c));
    const lists = h.scenarios.stats().candidateLists;
    await h.ask(farm(c, { weights: WEIGHTED.cases[1].weights })); // (weights do not change who can be a candidate: the list is the scenario's and the tier mode's)
    expect(h.scenarios.stats().candidateLists).toBe(lists);
    const own = stepsOf((await h.ask(plain(farm(c)))).messages);
    expect(own[0].F, "the role's own weights, not the weights of the request before").not.toBe(c.farmPath.start.F);
    expect(own[0].F).not.toBe(stepsOf((await h.ask(farm(c, { weights: WEIGHTED.cases[1].weights }))).messages)[0].F);
  });
});

describe("the haste assumed is the haste the kit counts", () => {
  it("is a whole percent that each answer says for its own kit, whatever the weights ask for, and the path says Equip now's", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const c = WEIGHTED.cases[0];
    const heavy = [{ custom: { HASTE: 0, ATK: 0 } }, { multipliers: { "ATK+HASTE": 0.5 } }, { multipliers: { "ATK+HASTE": 2 }, custom: { HASTE: 40 } }, c.weights];
    for (const weights of heavy) {
      const got = (await h.ask(equip(c, { weights }))).last;
      expect(Number.isInteger(got.hasteAssumed) && got.hasteAssumed >= 0 && got.hasteAssumed <= 85, JSON.stringify(weights)).toBe(true);
      const path = await h.ask(farm(c, { weights, steps: 1 }));
      const [start] = stepsOf(path.messages);
      expect(start.hasteAssumed, "Equip now of the path is Equip now").toBe(got.hasteAssumed);
      expect(path.last.hasteAssumed, JSON.stringify(weights)).toBe(start.hasteAssumed);
    }
  });
});

describe("a request whose weights the bundle does not allow", () => {
  const [C0] = WEIGHTED.cases;
  const REFUSED = {
    "a slider group there is not": { multipliers: { NOPE: 2 } },
    "a slider group there is not, at x1": { multipliers: { NOPE: 1 } },
    "a slider position that is not one of the three": { multipliers: { AC: 3 } },
    "a slider position between": { multipliers: { AC: 1.5 } },
    "a custom weight that cannot be set": { custom: { ZZZ: 1 } },
    "a custom weight that is derived": { custom: { DMG: 1 } },
    "a custom weight above the largest": { custom: { HP: 1001 } },
    "a custom weight below 0": { custom: { HP: -1 } },
    "a regen window above the longest": { regenT: 61 },
    "a regen window below 0": { regenT: -0.5 },
  };
  const MODES = {
    "equip-now": (weights) => equip(C0, { weights }),
    "farm-path": (weights) => farm(C0, { weights }),
    "best-sets": (weights) => sets(C0, 2, { weights }),
    "every-slot": (weights) => slots(C0, { weights }),
  };
  for (const [mode, build] of Object.entries(MODES)) {
    for (const [name, weights] of Object.entries(REFUSED)) {
      it(`is a bad request in ${mode}, and the worker goes on: ${name}`, async () => {
        const h = harness({ solver: highs });
        await h.start();
        const { id, last, messages } = await h.ask(build(weights));
        expect(last).toMatchObject({ type: "error", code: "bad-request", id });
        expect(typeof last.message).toBe("string");
        expect(last.message.length).toBeGreaterThan(0);
        expect(validateFromWorker(last, { id, kind: "scenario", mode }).code).toBe("bad-request");
        expect(messages.filter((message) => message.type === "result" || message.type === "step")).toHaveLength(0);
        const next = await h.ask(equip(C0));
        expect(next.last).toMatchObject({ type: "result", status: "optimal", F: C0.equipNow.F });
        expect(h.asked, "the data was not dropped for it").toHaveLength(3);
      });
    }
  }

  it("is refused by the page's check before anything is fetched when the numbers are too small or too fine, in every mode", async () => {
    for (const [mode, build] of Object.entries(MODES)) {
      const h = harness({ solver: highs });
      await h.start();
      for (const weights of [{ custom: { HP: 5e-324 } }, { regenT: 1e-100 }, { custom: { HP: 1.234567 } }]) {
        const { last } = await h.ask(build(weights));
        expect(last, `${mode} ${JSON.stringify(weights)}`).toMatchObject({ type: "error", code: "bad-request" });
        expect(last.message).toMatch(/6 significant digits/);
      }
      expect(h.asked, `${mode}: nothing was fetched for them`).toHaveLength(0);
    }
  });

  it("tells a bundle whose weight rules the engine cannot use as a fault of the data when weights are asked for, and drops it, in every mode: a request with none does not need them", async () => {
    for (const [mode, build] of Object.entries(MODES)) {
      const raw = JSON.parse(BUNDLE_BYTES.toString("utf8"));
      raw.weight_groups.custom_max = "not a number";
      const site = makeSite({ bundles: { [SLUG]: { 50: new TextEncoder().encode(JSON.stringify(raw)) } } });
      const h = harness({ site, solver: highs });
      await h.start();
      expect((await h.ask(plain(equip(C0)))).last, `${mode}: no weights`).toMatchObject({ type: "result", status: "optimal" });
      const faulty = await h.ask(build(C0.weights));
      expect(faulty.last, mode).toMatchObject({ type: "error", code: "engine-load" });
      expect(h.scenarios.stats()).toMatchObject({ bundles: 1 });
      expect((await h.ask(plain(equip(C0)))).last).toMatchObject({ type: "result", status: "optimal" });
      expect(h.scenarios.stats(), `${mode}: the data that was found wrong was dropped and fetched again`).toMatchObject({ bundles: 2 });
    }
  });
});

describe("a stop and a request that is replaced keep the rules they had", () => {
  const [C0, C1] = WEIGHTED.cases;

  it("a stop sent after the first step of a path with weights ends it 'stopped' with the steps Python found so far, and no reply to the stop", async () => {
    const h = harness({ solver: highs });
    await h.start();
    h.hooks.onPost = (message) => {
      if (message.type === "step" && message.index === 1) h.stopOf(h.currentId());
    };
    const built = farm(C0, { steps: 8 });
    const { id, messages, last } = await h.ask(built);
    pageChecks(built, id, messages);
    const steps = stepsOf(messages);
    expect(steps.map((step) => step.index)).toEqual([0, 1]);
    expect(pick(steps[0], START)).toEqual(C0.farmPath.start);
    expect(pick(steps[1], STEP)).toEqual(C0.farmPath.path[0]);
    expect(last).toMatchObject({ type: "result", mode: "farm-path", stopped: "stopped", steps: 1 });
    expect(messages.filter((message) => message.type === "error")).toEqual([]);
  });

  it("a stop for a request that is not in flight does nothing, with weights or without", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const first = await h.ask(farm(C0));
    await h.stopOf(first.id); // it ended already
    await h.stopOf(999);
    const next = await h.ask(farm(C0, { weights: C1.weights }));
    expect(next.last).toMatchObject({ type: "result", mode: "farm-path" });
    expect(stepsOf(next.messages).length).toBeGreaterThanOrEqual(2);
  });

  it("a request that follows one with other weights is worked out for its own: nothing of the first is in its answer", async () => {
    const h = harness({ solver: highs });
    await h.start();
    const asked = [farm(C0), farm(C0, { weights: C1.weights }), farm(C0)];
    const answers = [];
    for (const built of asked) answers.push(stepsOf((await h.ask(built)).messages).map((step) => step.F));
    expect(answers[0]).not.toEqual(answers[1]);
    expect(answers[2]).toEqual(answers[0]);
    expect(answers[0].slice(1)).toEqual(C0.farmPath.path.map((step) => step.F));
  });
});

describe("the five modes share one function for the weights", () => {
  const scenario = SOURCE("scenario.js");
  const bestkit = SOURCE("bestkit.js");
  const importsOf = (text) => [...text.matchAll(/import\s+(?:\{([^}]*)\}|(\w+))\s+from\s+"([^"]+)"/g)].map((found) => ({ names: (found[1] ?? found[2]).split(",").map((name) => name.trim()).filter(Boolean), from: found[3] }));

  it("is where the profile of a view is made and the weights are composed on the role's own: scenario.js asks bestkit.js for it and composes nothing itself", () => {
    const fromBestKit = importsOf(scenario).find((entry) => entry.from === "./bestkit.js");
    expect(fromBestKit?.names, "scenario.js imports the profile of a view from bestkit.js").toEqual(expect.arrayContaining(["viewProfile"]));
    expect(scenario).not.toMatch(/\bweightsOverride\s*\(/);
    expect(scenario).not.toMatch(/\bweightsAreOwn\s*\(/);
    expect(scenario).not.toMatch(/from "\.\/weights\.js"/);
    // (viewProfile is made in view.js, a file of its own that the evaluator of the page shares for the order of motes; bestkit.js tells it on as it always has)
    const view = SOURCE("view.js");
    expect(view).toMatch(/export function viewProfile\b/);
    expect(bestkit).toMatch(/export \{[^}]*\bviewProfile\b[^}]*\};/);
    expect(bestkit).not.toMatch(/\bweightsOverride\(/);
    expect((view.match(/\bweightsOverride\(/g) ?? []).length, "one place composes the weights").toBe(1);
  });
});

describe("the exact values of the answers are the page's to read", () => {
  it("are exact fractions that the page reads: the value of a weighted path is its Equip now plus the gains, exactly", async () => {
    const h = harness({ solver: highs });
    await h.start();
    for (const c of WEIGHTED.cases) {
      const { messages } = await h.ask(farm(c));
      const steps = stepsOf(messages);
      const total = steps.slice(1).reduce((sum, step) => sum.add(Rational.parseLong(step.gain)), Rational.parseLong("0/1"));
      expect(Rational.parseLong(steps.at(-1).F).sub(Rational.parseLong(steps[0].F)).toString(), c.name).toBe(total.toString());
    }
  });
});

describe("a session that is kept does not skip the check of the weights", () => {
  // A session is kept by the scenario and the weights, and the key leaves out what changes nothing: a slider at x1, an empty table, a window of null. So the weights of a request that
  // the bundle refuses (a slider group there is not, at x1) found the session kept for the same scenario with no weights and were answered: whether a request was refused depended on
  // the request before it. The weights are checked by `viewProfile` for every request, kept session or not, and the key only says which session to reuse.
  const [C0] = WEIGHTED.cases;
  const BUILD = {
    "equip-now": (c, weights) => equip(c, { weights }),
    "farm-path": (c, weights) => farm(c, { weights }),
    "best-sets": (c, weights) => sets(c, 2, { weights }),
    "every-slot": (c, weights) => slots(c, { weights }),
  };
  const BAD = [
    ["a slider group there is not, at x1", { multipliers: { NOPE: 1 } }],
    ["the same beside a good slider at x1", { multipliers: { NOPE: 1, AC: 1 } }],
    ["the same with a window of null and no custom weight", { multipliers: { NOPE: 1 }, custom: {}, regenT: null }],
    ["a slider group there is not, at x2", { multipliers: { NOPE: 2 } }],
    ["a custom weight that cannot be set, at 0", { custom: { NOPE: 0 } }],
  ];
  const refused = (answer) => expect(answer.last).toMatchObject({ type: "error", code: "bad-request" });

  for (const mode of Object.keys(BUILD)) {
    it(`${mode}: the weights are refused whether or not a session is kept for the scenario, and a refusal makes no session and closes none`, async () => {
      const h = harness({ solver: highs });
      await h.start();
      const built = (weights) => BUILD[mode](C0, weights);
      const ask = (weights) => h.ask(built(weights));
      for (const [name, weights] of BAD) expect((await ask(weights)).last, `no session yet: ${name}`).toMatchObject({ type: "error", code: "bad-request" });
      expect(h.scenarios.stats(), "a refusal makes no session").toMatchObject({ sessions: 0, sessionsClosed: 0 });
      await h.ask(plain(built({}))); // a request with no weights: the session of the scenario is kept
      expect(h.scenarios.stats()).toMatchObject({ sessions: 1, sessionsClosed: 0 });
      for (const [name, weights] of BAD) {
        const got = await ask(weights);
        expect(got.last, `a session is kept: ${name}`).toMatchObject({ type: "error", code: "bad-request", id: got.id });
        expect(got.messages.filter((message) => message.type === "step" || message.type === "result"), name).toHaveLength(0);
      }
      expect(h.scenarios.stats(), "and a refusal closes none: the session is there for the next good request").toMatchObject({ sessions: 1, sessionsClosed: 0 });
      const next = await h.ask(plain(built({})));
      expect(next.last.type).not.toBe("error");
      expect(h.scenarios.stats(), "the next good request found it").toMatchObject({ sessions: 1, sessionsClosed: 0 });
    });

    it(`${mode}: also when the session kept was made for weights: the same weights with a slider group there is not at x1 are refused, and the session stays`, async () => {
      const h = harness({ solver: highs });
      await h.start();
      const ask = (weights) => h.ask(BUILD[mode](C0, weights));
      await ask(C0.weights);
      expect(h.scenarios.stats()).toMatchObject({ sessions: 1, sessionsClosed: 0 });
      refused(await ask({ ...C0.weights, multipliers: { ...C0.weights.multipliers, NOPE: 1 } }));
      refused(await ask({ ...C0.weights, custom: { ...C0.weights.custom, NOPE: 0 } }));
      expect(h.scenarios.stats()).toMatchObject({ sessions: 1, sessionsClosed: 0 });
      const again = await ask(C0.weights);
      expect(again.last.type).not.toBe("error");
      expect(h.scenarios.stats(), "the session made for the weights was kept").toMatchObject({ sessions: 1, sessionsClosed: 0 });
    });
  }
});
