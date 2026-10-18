// Faults of the engine told by what they are (scenario.js, worker.js): a fault of the solver is `solver` and closes the session that met it; a bundle that no
// session can be made of is a fault of the data (`engine-load`) and is dropped; and the visitor's own mistakes stay bad requests. The solver here is the real
// one, with a spy that makes it do what an answer cannot be made from; the files are those of the synthetic site fixture (see engine-scenario.test.mjs for the
// answers, and engine-solve.test.mjs for the SolverFault itself).

import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { EvaluateError } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { ItemError } from "../pipeline/trioforge/site/static/engine/items.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { createWorkerCore } from "../pipeline/trioforge/site/static/engine/worker.js";
import { BASE, EQUIP_NOW, SLUG, makeSite, siteFetch } from "./engine-site-fixture.mjs";
import { spyOn } from "./engine-spy.mjs";

// the session of the engine is made by solve.js, and the numbers of an item by items.js: a test can make either fail once
const failing = vi.hoisted(() => ({ session: null, item: null }));
vi.mock("../pipeline/trioforge/site/static/engine/items.js", async (importOriginal) => {
  const real = await importOriginal();
  return {
    ...real,
    atTier(...args) {
      if (failing.item !== null) {
        const error = failing.item;
        failing.item = null;
        throw error;
      }
      return real.atTier(...args);
    },
  };
});
vi.mock("../pipeline/trioforge/site/static/engine/solve.js", async (importOriginal) => {
  const real = await importOriginal();
  return {
    ...real,
    createSession(...args) {
      if (failing.session !== null) {
        const error = failing.session;
        failing.session = null;
        throw error;
      }
      return real.createSession(...args);
    },
  };
});

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const c0 = EQUIP_NOW.cases[0];
const requestOf = (over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "equip-now", scenario: { ...c0.scenario }, owned: c0.owned.map((pair) => [...pair]), budgetMs: 120_000, ...over });

/** A worker core on the scenario engine over `solver` (the loaded solver, or a spy on it), with the fake fetch of the site. */
function harness(solver = highs) {
  const site = makeSite();
  const fetching = siteFetch(site);
  const scenarios = createScenarioEngine({ highs: solver, fetchImpl: fetching.fetchImpl, baseUrl: BASE });
  const posted = [];
  const core = createWorkerCore({
    post: (message) => posted.push(structuredClone(message)),
    loadManifest: async () => site.manifest,
    loadEngine: async () => ({
      version: "1.15.3",
      async solveModel() {
        throw new Error("a model request is not what is tested here");
      },
      equipNow: (request, options) => scenarios.equipNow(request, options),
    }),
  });
  let id = 0;
  return {
    scenarios,
    ...fetching,
    async start() {
      await core.handle({ v: 1, type: "init" });
      posted.length = 0;
    },
    async ask(request = requestOf()) {
      id += 1;
      posted.length = 0;
      await core.handle({ v: 1, type: "solve", id, request });
      return posted[posted.length - 1];
    },
  };
}

describe("a fault of the solver", () => {
  it("is told as `solver` when the run ends in a status the solve does not accept; the session that met it is closed, and the next request gets a new one and is answered", async () => {
    const sick = { on: false };
    const { highs: spied } = spyOn(highs, { outcome: (result) => (sick.on ? { ...result, modelStatus: highs.constants.modelStatus.unbounded } : result) });
    const h = harness(spied);
    await h.start();
    expect((await h.ask()).type).toBe("result");
    expect(h.scenarios.stats()).toMatchObject({ sessions: 1, sessionsClosed: 0 });
    sick.on = true;
    const failed = await h.ask();
    expect(failed).toMatchObject({ type: "error", code: "solver", message: expect.stringMatching(/ended with the status/i) });
    expect(failed.message).toMatch(/^[\x20-\x7e]{1,300}$/);
    expect(h.scenarios.stats()).toMatchObject({ sessions: 1, sessionsClosed: 1 }); // closed: the same scenario is not answered by it again
    sick.on = false;
    const next = await h.ask();
    expect(next).toMatchObject({ type: "result", status: "optimal", F: c0.F });
    expect(h.scenarios.stats()).toMatchObject({ sessions: 2, sessionsClosed: 1 }); // a new session
  });

  it("is told as `solver` for a solution with an entry that is not a number, and for one that is not whole", async () => {
    for (const value of [Number.NaN, 0.5]) {
      const sick = { on: false };
      const poisoned = (solution) => {
        if (!sick.on) return solution;
        const colValue = Float64Array.from(solution.colValue);
        const at = colValue.findIndex((x) => x === 1);
        colValue[at] = value;
        return { ...solution, colValue };
      };
      const { highs: spied } = spyOn(highs, { solution: poisoned });
      const h = harness(spied);
      await h.start();
      expect((await h.ask()).type).toBe("result");
      sick.on = true;
      expect(await h.ask(), String(value)).toMatchObject({ type: "error", code: "solver" });
      expect(h.scenarios.stats().sessionsClosed).toBe(1);
      sick.on = false;
      expect((await h.ask()).type).toBe("result");
    }
  });

  it("is told as `solver` when HiGHS refuses the model the builder made", async () => {
    const refusing = { on: false };
    const spied = Object.create(highs, {
      createModel: {
        value(...args) {
          if (refusing.on) throw new highs.errors.HighsError("a refused model");
          return highs.createModel(...args);
        },
      },
    });
    const h = harness(spied);
    await h.start();
    expect((await h.ask()).type).toBe("result");
    refusing.on = true;
    // another scenario, so that a new model is made
    const other = requestOf({ scenario: { ...c0.scenario, buffs: "group" } });
    expect(await h.ask(other)).toMatchObject({ type: "error", code: "solver", message: expect.stringMatching(/would not take this model/i) });
    refusing.on = false;
    expect((await h.ask(other)).type).toBe("result");
  });
});

describe("a bundle that no session can be made of", () => {
  it("is told as `engine-load`, with the bundle dropped and the same bundle fetched again by the next request, which is answered", async () => {
    const h = harness();
    await h.start();
    failing.session = new EvaluateError("profile.pools.HP must be a list of pools");
    const failed = await h.ask();
    expect(failed).toMatchObject({ type: "error", code: "engine-load", message: expect.stringMatching(/bundle/i) });
    expect(failed.message).not.toMatch(/pools|profile/); // it says which file, not what is in it
    expect(h.scenarios.stats()).toMatchObject({ bundles: 1, sessions: 0 });
    const asked = h.asked.length;
    expect((await h.ask()).type).toBe("result");
    expect(h.scenarios.stats()).toMatchObject({ bundles: 2, sessions: 1 });
    expect(h.asked.length).toBe(asked + 1); // the bundle only: the manifest of the trio and the item table were fine
  });

  it("is not told so of an error that is not the engine's own (a bug is internal)", async () => {
    const h = harness();
    await h.start();
    failing.session = new TypeError("undefined is not a function");
    expect(await h.ask()).toMatchObject({ type: "error", code: "internal" });
    expect((await h.ask()).type).toBe("result");
  });
});

describe("an item that the reader of the table took and atTier cannot work out", () => {
  it("is told as `engine-load`, with the table dropped (and the bundle checked against it): the next request fetches them again and is answered", async () => {
    const h = harness();
    await h.start();
    failing.item = new ItemError("item w90001: unknown stat FOO");
    const failed = await h.ask();
    expect(failed).toMatchObject({ type: "error", code: "engine-load", message: expect.stringMatching(/item table/i) });
    expect(failed.message).not.toMatch(/FOO|w90001/); // it says which file, not what is in it
    expect(h.scenarios.stats()).toMatchObject({ itemTables: 1, bundles: 1 });
    const asked = h.asked.length;
    expect((await h.ask()).type).toBe("result");
    expect(h.scenarios.stats()).toMatchObject({ itemTables: 2, bundles: 2 });
    expect(h.asked.length).toBe(asked + 2); // the table and the bundle (the manifest of the trio was fine)
  });
});

describe("the visitor's mistakes", () => {
  it("stay bad requests, and the data and the session stay", async () => {
    const h = harness();
    await h.start();
    expect((await h.ask()).type).toBe("result");
    expect(await h.ask(requestOf({ scenario: { ...c0.scenario, race: "ZZZ" } }))).toMatchObject({ type: "error", code: "bad-request" });
    expect(await h.ask(requestOf({ owned: [["w999999@4", 1]] }))).toMatchObject({ type: "error", code: "bad-request" });
    expect(h.scenarios.stats()).toMatchObject({ itemTables: 1, bundles: 1, trioManifests: 1 });
  });
});
