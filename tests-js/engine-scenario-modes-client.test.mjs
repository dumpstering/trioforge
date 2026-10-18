// The page's side of the other scenario modes (client.js): runScenario(request, {onStep, onProgress}) for the four modes, resolving to the final result, with each step of a
// farm path handed to onStep as it comes; stop(), which asks the worker to end the farm path in flight before its next step; the watchdog, which every step is a sign of life
// for; and the checks that drop a worker which sends a step that is not right. Two kinds of worker here: the real worker core on the real solver (the files are those of the
// synthetic site fixture), and a scripted one that says what a test wants it to say, under fake timers.

import loadHighs from "highs";
import { JSDOM } from "jsdom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { createEngineClient } from "../pipeline/trioforge/site/static/engine/client.js";
import { KIT_PLACE_NAMES, LABEL_NO_INCUMBENT, WATCHDOG_GRACE_MS } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { SolverFault } from "../pipeline/trioforge/site/static/engine/solve.js";
import { createWorkerCore } from "../pipeline/trioforge/site/static/engine/worker.js";
import { BASE, EQUIP_NOW, SLUG, makeSite, siteFetch, siteWithNoCandidates } from "./engine-site-fixture.mjs";
import { handMilp } from "./engine-models.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});
afterEach(() => {
  vi.useRealTimers();
});

const [C0, C1] = EQUIP_NOW.cases;
const READY4 = { mode: "ready4" };
const base = (c, over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, scenario: { ...c.scenario }, owned: c.owned.map((pair) => [...pair]), budgetMs: 120_000, ...over });
const farm = (c, over = {}) => base(c, { mode: "farm-path", tierMode: { ...READY4 }, steps: 3, ...over });
const sets = (c, over = {}) => base(c, { mode: "best-sets", tierMode: { ...READY4 }, k: 2, ...over });
const slots = (c, over = {}) => base(c, { mode: "every-slot", tierMode: { ...READY4 }, kit: [...c.kit], buffs: [...c.buffs], ...over });
const equip = (c, over = {}) => base(c, { mode: "equip-now", ...over });

/** A worker object for the client: the core of a real worker behind it (`core`), or a script that says what the worker says (`script(message, reply, worker)`). */
class FakeWorker {
  constructor({ core, script }) {
    this.core = core;
    this.script = script;
    this.terminated = false;
    this.sent = [];
    this.onmessage = null;
    this.onerror = null;
    this.onmessageerror = null;
    core?.attach((message) => this.reply(message));
  }

  reply(message) {
    queueMicrotask(() => {
      if (!this.terminated) this.onmessage?.({ data: structuredClone(message) });
    });
  }

  postMessage(data) {
    const copy = structuredClone(data);
    this.sent.push(copy);
    queueMicrotask(() => {
      if (this.terminated) return;
      if (this.script) this.script(copy, (message) => this.reply(message), this);
      else this.core.handle(copy);
    });
  }

  terminate() {
    this.terminated = true;
  }
}

/** A client on fake workers, an in-memory page and the manifests of the site fixture. `engineOver` replaces methods of the engine of the real worker. */
function harness({ script, consent = { ask: async () => true }, site = makeSite(), engineOver = {}, now } = {}) {
  const fetching = siteFetch(site);
  const dom = new JSDOM('<!doctype html><html><body><main id="main"></main></body></html>', { url: "https://trioforge.test/trio/pal-mnk-ber/" });
  const manifestFetches = [];
  const pageFetch = async (url) => {
    manifestFetches.push(String(url));
    const text = String(url) === "/engine-manifest.json" ? JSON.stringify(site.manifestJson) : String(url).startsWith("/engine-trios/") ? JSON.stringify(site.trioJson[String(url).slice("/engine-trios/".length).replace(/\.json$/, "")]) : undefined;
    if (text === undefined) return { ok: false, status: 404, text: async () => "not found" };
    return { ok: true, status: 200, text: async () => text };
  };
  const workers = [];
  const scenarios = [];
  const createWorker = () => {
    let worker;
    if (script) {
      worker = new FakeWorker({ script });
    } else {
      const engine = createScenarioEngine({ highs, fetchImpl: fetching.fetchImpl, baseUrl: BASE, ...(now === undefined ? {} : { now }) });
      scenarios.push(engine);
      let sink = () => {};
      const core = createWorkerCore({
        now,
        post: (message) => sink(message),
        loadManifest: async () => site.manifest,
        loadEngine: async () => ({
          version: "1.15.3",
          wasm: site.manifest.wasm.sha256,
          async solveModel() {
            throw new Error("no model here");
          },
          equipNow: (request, options) => engine.equipNow(request, options),
          farmPath: (request, options) => engine.farmPath(request, options),
          bestSets: (request, options) => engine.bestSets(request, options),
          everySlot: (request, options) => engine.everySlot(request, options),
          ...engineOver,
        }),
      });
      core.attach = (fn) => {
        sink = fn;
      };
      worker = new FakeWorker({ core });
    }
    workers.push(worker);
    return worker;
  };
  const client = createEngineClient({ window: dom.window, document: dom.window.document, fetch: pageFetch, createWorker, consent, trustedTypes: null });
  return { client, workers, scenarios, site, manifestFetches, ...fetching, dom };
}

/** Follow a promise without making a rejection unhandled. */
function track(promise) {
  const outcome = { state: "pending", value: undefined, error: undefined };
  promise.then(
    (value) => Object.assign(outcome, { state: "resolved", value }),
    (error) => Object.assign(outcome, { state: "rejected", error }),
  );
  return outcome;
}
/** Let the promise chains that are waiting run (no timers: it works under fake timers). */
async function flush(rounds = 60) {
  for (let i = 0; i < rounds; i += 1) await Promise.resolve();
}
/** Wait, on promises alone (the clock of a fake-timer test must not move), until `test()` is true. */
async function until(test) {
  for (let i = 0; i < 5000 && !test(); i += 1) await Promise.resolve();
  expect(test()).toBe(true);
}

// ---- with the real worker -----------------------------------------------------------------------------------------------------------------

describe("runScenario with the real worker", () => {
  it("runs a farm path: onStep gets Equip now and each step as it comes, with no envelope, and the promise resolves to the final result", async () => {
    const h = harness();
    const seen = [];
    const progress = [];
    const result = await h.client.runScenario(farm(C0), { onStep: (message) => seen.push(message), onProgress: (report) => progress.push(report) });
    expect(seen.map((message) => message.index)).toEqual([0, 1, 2, 3]);
    expect(seen.every((message) => message.v === undefined && message.type === undefined && message.id === undefined)).toBe(true);
    expect(seen[0]).toMatchObject({ status: "optimal", proven: true });
    expect(seen.slice(1).every((message) => message.found === true)).toBe(true);
    expect(result).toMatchObject({ kind: "scenario", mode: "farm-path", stopped: "limit", steps: 3, hasteAssumed: seen[0].hasteAssumed });
    expect(result.elapsedMs).toBeGreaterThan(0);
    // the reports carry the stage they are in
    expect(progress.filter((report) => report.stage !== undefined).length).toBeGreaterThan(0);
    expect(progress.filter((report) => report.stage === "step").map((report) => report.step)).toEqual([1, 2, 3]);
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].sent.map((message) => message.type)).toEqual(["init", "solve"]);
  });

  it("stop() sends a stop for the farm path in flight; the path ends before its next step and the promise resolves with 'stopped'", async () => {
    const h = harness();
    const seen = [];
    const result = await h.client.runScenario(farm(C0, { steps: 8 }), {
      onStep: (message) => {
        seen.push(message.index);
        if (message.index === 1) h.client.stop();
      },
    });
    expect(seen).toEqual([0, 1]);
    expect(result).toMatchObject({ mode: "farm-path", stopped: "stopped", steps: 1 });
    const stops = h.workers[0].sent.filter((message) => message.type === "stop");
    expect(stops).toEqual([{ v: 1, type: "stop", id: h.workers[0].sent.find((message) => message.type === "solve").id }]);
    // the worker was not stopped: the next request is answered by it
    expect((await h.client.runScenario(equip(C1))).status).toBe("optimal");
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].terminated).toBe(false);
  });

  it("stop() asked twice sends one stop", async () => {
    const h = harness();
    await h.client.runScenario(farm(C0, { steps: 8 }), {
      onStep: (message) => {
        if (message.index === 1) {
          h.client.stop();
          h.client.stop();
        }
      },
    });
    expect(h.workers[0].sent.filter((message) => message.type === "stop")).toHaveLength(1);
  });

  it("stop() does nothing when no request is in flight, or when the request in flight is not a farm path", async () => {
    const h = harness();
    h.client.stop(); // nothing in flight, no worker
    expect(h.workers).toHaveLength(0);
    const progress = [];
    const got = await h.client.runScenario(equip(C0), {
      onProgress: (report) => {
        progress.push(report);
        h.client.stop();
      },
    });
    expect(got).toMatchObject({ mode: "equip-now", status: "optimal" });
    expect(progress.length).toBeGreaterThan(0);
    const sets_ = await h.client.runScenario(sets(C0), { onProgress: () => h.client.stop() });
    expect(sets_).toMatchObject({ mode: "best-sets", status: "optimal" });
    expect(h.workers[0].sent.filter((message) => message.type === "stop")).toEqual([]);
    h.client.stop(); // and nothing in flight again
    expect(h.workers[0].sent.filter((message) => message.type === "stop")).toEqual([]);
  });

  it("stop() asked while the request waits for the visitor's answer is sent right after the request: Equip now comes, and the path ends before its first step", async () => {
    let answer;
    const consent = { ask: () => new Promise((resolve) => (answer = resolve)) };
    const h = harness({ consent });
    const seen = [];
    const request = h.client.runScenario(farm(C0, { steps: 8 }), { onStep: (message) => seen.push(message.index) });
    const outcome = track(request);
    await vi.waitFor(() => expect(answer).toBeTypeOf("function"));
    h.client.stop(); // the visitor has not said yes yet, and no worker has the request
    expect(h.workers).toHaveLength(0);
    answer(true);
    const result = await request;
    expect(outcome.state).toBe("resolved");
    expect(h.workers[0].sent.map((message) => message.type)).toEqual(["init", "solve", "stop"]);
    expect(seen).toEqual([0]);
    expect(result).toMatchObject({ stopped: "stopped", steps: 0 });
  });

  it("resolves a request for the best sets and one for Every slot to their final results", async () => {
    const h = harness();
    const set = await h.client.runScenario(sets(C0, { k: 3 }));
    expect(set).toMatchObject({ kind: "scenario", mode: "best-sets", k: 3, status: "optimal", proven: true });
    expect(set.acquired.length).toBeGreaterThan(0);
    const every = await h.client.runScenario(slots(C0));
    expect(every).toMatchObject({ kind: "scenario", mode: "every-slot" });
    expect(every.rows).toHaveLength(22);
    expect(h.workers).toHaveLength(1);
  });

  it("is the same question for every mode: the size of the download is the figure of Equip now, and the question is asked once", async () => {
    const ask = vi.fn(async () => true);
    const sized = makeSite({ lie: { items: { gzip: 400_000 }, bundle: { gzip: 90_000 } } });
    for (const build of [equip, farm, sets, slots]) {
      const h = harness({ consent: { ask }, site: sized });
      await h.client.runScenario(build(C0));
    }
    expect(ask).toHaveBeenCalledTimes(4);
    expect(new Set(ask.mock.calls.map((call) => call[0].megabytes))).toEqual(new Set([1.8]));
  });

  it("takes every one of the four modes: none is answered with not-implemented, and solve() runs any of them too, without handing the steps to anyone", async () => {
    const h = harness();
    for (const build of [equip, farm, sets, slots]) {
      const got = await h.client.solve(build(C0));
      expect(got).toMatchObject({ kind: "scenario", mode: build(C0).mode });
    }
    expect(h.client.stats()).toMatchObject({ spawns: 1, solves: 4 });
  });

  it("refuses a request that is not a scenario request as a bad request, before anything is asked or fetched", async () => {
    const ask = vi.fn(async () => true);
    const h = harness({ consent: { ask } });
    await expect(h.client.runScenario({ v: 1, kind: "model", model: {}, budgetMs: 1000 })).rejects.toMatchObject({ code: "bad-request" });
    await expect(h.client.runScenario({ ...farm(C0), candidates: [] })).rejects.toMatchObject({ code: "bad-request" });
    await expect(h.client.runScenario({ ...farm(C0), mode: "best-1" })).rejects.toMatchObject({ code: "bad-request" });
    expect(ask).not.toHaveBeenCalled();
    expect(h.manifestFetches).toEqual([]);
    expect(h.workers).toHaveLength(0);
  });

  it("rejects with the code of a fault in a step, after the steps before it were handed to onStep, and goes on with a new session", async () => {
    let engine;
    const h = harness({
      engineOver: {
        farmPath: (request, options) => {
          let sent = 0;
          engine ??= h.scenarios[0];
          return engine.farmPath(request, {
            ...options,
            onStep: (body) => {
              options.onStep(body);
              sent += 1;
              if (sent === 2) throw new SolverFault("the solver ended with a status the solve does not accept");
            },
          });
        },
      },
    });
    const seen = [];
    await expect(h.client.runScenario(farm(C0), { onStep: (message) => seen.push(message.index) })).rejects.toMatchObject({ code: "solver" });
    expect(seen).toEqual([0, 1]);
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].terminated).toBe(false);
    expect((await h.client.runScenario(equip(C1))).status).toBe("optimal");
  });

  it("accepts a path with nothing to add: Equip now alone, ended 'no-gain', and 'time' when that Equip now did not finish (end to end, through the client's checks)", async () => {
    const h = harness({ site: siteWithNoCandidates() });
    const seen = [];
    const done = await h.client.runScenario(farm(C0), { onStep: (message) => seen.push(message) });
    expect(seen.map((message) => message.index)).toEqual([0]);
    expect(done).toMatchObject({ mode: "farm-path", stopped: "no-gain", steps: 0 });
    // and a clock that uses up the budget before Equip now: step 0 is not finished, and the path says it ran out of time
    const clock = { t: 0 };
    const slow = harness({ site: siteWithNoCandidates(), now: () => (clock.t += 10) });
    const steps = [];
    const result = await slow.client.runScenario(farm(C0, { budgetMs: 1 }), { onStep: (message) => steps.push(message) });
    expect(steps.map((message) => message.index)).toEqual([0]);
    expect(steps[0]).toMatchObject({ status: "time_limit", proven: false });
    expect(result).toMatchObject({ mode: "farm-path", stopped: "time", steps: 0 });
    expect(slow.workers[0].terminated).toBe(false);
  });

  it("accepts the answers of all three modes under every tier mode: the page holds them to the tier of the mode and to the kit it sent, and they keep to both", async () => {
    const h = harness();
    for (const tierMode of [{ mode: "ready4" }, { mode: "arrives", D: 2 }, { mode: "arrives", D: 0 }, { mode: "fixed", N: 10 }, { mode: "fixed", N: 0 }]) {
      const label = JSON.stringify(tierMode);
      expect(await h.client.runScenario(farm(C0, { tierMode, steps: 2 })), label).toMatchObject({ mode: "farm-path" });
      expect(await h.client.runScenario(sets(C0, { tierMode, k: 2 })), label).toMatchObject({ mode: "best-sets" });
      expect((await h.client.runScenario(slots(C0, { tierMode }))).rows, label).toHaveLength(22);
    }
    expect(h.workers).toHaveLength(1); // none of the answers dropped the worker
  });

  it("goes on when the page's own onStep throws: a bug in a callback is not the worker's", async () => {
    const h = harness();
    const result = await h.client.runScenario(farm(C0, { steps: 2 }), {
      onStep: () => {
        throw new Error("a bug in the page");
      },
    });
    expect(result).toMatchObject({ stopped: "limit", steps: 2 });
  });
});

// ---- stop() and the requests that wait ------------------------------------------------------------------------------------------------

describe("stop() and the farm paths that wait their turn", () => {
  // The client runs one request at a time. A visitor who presses Stop means every farm path the client has not finished: the one in flight, and each one that still waits
  // (behind a model request, or behind another path). A waiting path is marked, and its stop is posted right after its request when its turn comes, so that it ends
  // after its Equip now: the worker has the stop before it has begun to load the data, and sees it at its first look, which is after Equip now. A model request, or any other
  // request, is never stopped.
  const modelRequest = (over = {}) => ({ v: 1, kind: "model", model: handMilp(), budgetMs: 20_000, ...over });
  const modelAnswer = (model) => ({ status: "optimal", proven: true, objective: 0, x: new Array(model.c.length).fill(0), bound: 0, gap: 0, nodes: 1, label: null });
  /** A promise that the test settles, and a harness whose model requests wait for it. */
  function gated() {
    let open;
    const gate = new Promise((resolve) => (open = resolve));
    const h = harness({
      engineOver: {
        solveModel: async (model) => {
          await gate;
          return modelAnswer(model);
        },
      },
    });
    return { h, open };
  }
  /** What the client posted to the worker, without the questions whether it is still there. */
  const posted = (h) => h.workers[0].sent.filter((message) => message.type !== "ping").map((message) => ({ type: message.type, id: message.id }));
  const inFlight = (h) => until(() => h.workers[0]?.sent.some((message) => message.type === "solve"));

  it("ends a farm path that waits behind a model request: it comes out 'stopped' after its Equip now (the step 0 and no other), and the model request is not touched", async () => {
    const { h, open } = gated();
    const model = h.client.solve(modelRequest());
    await inFlight(h); // the worker has it, and holds it
    const seen = [];
    const path = h.client.runScenario(farm(C0, { steps: 8 }), { onStep: (message) => seen.push(message.index) }); // waits its turn
    await flush();
    h.client.stop();
    expect(posted(h).map((message) => message.type), "nothing is posted for a request the worker does not have yet").toEqual(["init", "solve"]);
    open();
    const [modelDone, pathDone] = await Promise.allSettled([model, path]);
    expect(modelDone).toMatchObject({ status: "fulfilled", value: { kind: "model", status: "optimal", proven: true } });
    expect(pathDone).toMatchObject({ status: "fulfilled", value: { kind: "scenario", mode: "farm-path", stopped: "stopped", steps: 0 } });
    expect(seen, "Equip now only: the stop was posted right after the request, so the worker saw it at its first look").toEqual([0]);
    const sent = posted(h);
    expect(sent.map((message) => message.type)).toEqual(["init", "solve", "solve", "stop"]);
    expect(sent[3].id, "the stop is the path's, not the model request's").toBe(sent[2].id);
    expect(sent[3].id).not.toBe(sent[1].id);
    expect(h.workers[0].terminated).toBe(false);
  });

  it("ends every farm path that waits, each after its Equip now, and each with its own stop", async () => {
    const { h, open } = gated();
    const model = h.client.solve(modelRequest());
    await inFlight(h);
    const seen = [[], []];
    const first = h.client.runScenario(farm(C0, { steps: 8 }), { onStep: (message) => seen[0].push(message.index) });
    const second = h.client.runScenario(farm(C1, { steps: 8 }), { onStep: (message) => seen[1].push(message.index) });
    await flush();
    h.client.stop();
    open();
    const done = await Promise.allSettled([model, first, second]);
    expect(done[0].status).toBe("fulfilled");
    for (const at of [1, 2]) expect(done[at], `path ${at}`).toMatchObject({ status: "fulfilled", value: { mode: "farm-path", stopped: "stopped", steps: 0 } });
    expect(seen).toEqual([[0], [0]]);
    const sent = posted(h);
    expect(sent.map((message) => message.type)).toEqual(["init", "solve", "solve", "stop", "solve", "stop"]);
    expect(sent[3].id).toBe(sent[2].id);
    expect(sent[5].id).toBe(sent[4].id);
    expect(new Set([sent[1].id, sent[2].id, sent[4].id]).size, "three requests, three ids").toBe(3);
  });

  it("ends the farm path in flight and the one that waits behind it, with the one call", async () => {
    const { h } = gated();
    const seen = [[], []];
    let asked = false;
    const first = h.client.runScenario(farm(C0, { steps: 8 }), {
      onStep: (message) => {
        seen[0].push(message.index);
        if (message.index === 0 && !asked) {
          asked = true;
          h.client.stop(); // the first path is in flight, the second waits
        }
      },
    });
    const second = h.client.runScenario(farm(C1, { steps: 8 }), { onStep: (message) => seen[1].push(message.index) });
    const done = await Promise.allSettled([first, second]);
    for (const at of [0, 1]) expect(done[at], `path ${at}`).toMatchObject({ status: "fulfilled", value: { mode: "farm-path", stopped: "stopped", steps: 0 } });
    expect(seen).toEqual([[0], [0]]);
    const sent = posted(h);
    expect(sent.map((message) => message.type)).toEqual(["init", "solve", "stop", "solve", "stop"]);
    expect(h.workers).toHaveLength(1);
  });

  it("is still a call that does nothing when there is no farm path to stop: nothing in flight, or only other requests, in flight or waiting", async () => {
    const { h, open } = gated();
    h.client.stop(); // nothing at all
    expect(h.workers).toHaveLength(0);
    const model = h.client.solve(modelRequest());
    await inFlight(h);
    const equipNow = h.client.runScenario(equip(C0));
    const bestSets = h.client.runScenario(sets(C0));
    await flush();
    h.client.stop();
    open();
    const done = await Promise.allSettled([model, equipNow, bestSets]);
    expect(done.map((one) => one.status)).toEqual(["fulfilled", "fulfilled", "fulfilled"]);
    expect(done[1].value).toMatchObject({ mode: "equip-now", status: "optimal" });
    expect(done[2].value).toMatchObject({ mode: "best-sets", status: "optimal" });
    expect(posted(h).filter((message) => message.type === "stop")).toEqual([]);
    h.client.stop(); // and nothing in flight again
    expect(posted(h).filter((message) => message.type === "stop")).toEqual([]);
  });

  it("never stops a model request: one in flight is answered whole, and one that waits behind a stopped path runs when its turn comes", async () => {
    const { h, open } = gated();
    open(); // the model requests are answered at once
    const seen = [];
    let asked = false;
    const path = h.client.runScenario(farm(C0, { steps: 8 }), {
      onStep: (message) => {
        seen.push(message.index);
        if (message.index === 0 && !asked) {
          asked = true;
          h.client.stop();
        }
      },
    });
    const model = h.client.solve(modelRequest()); // waits behind the path
    const after = await Promise.allSettled([path, model]);
    expect(after[0]).toMatchObject({ status: "fulfilled", value: { stopped: "stopped", steps: 0 } });
    expect(after[1]).toMatchObject({ status: "fulfilled", value: { kind: "model", status: "optimal", proven: true } });
    const sent = posted(h);
    expect(sent.map((message) => message.type)).toEqual(["init", "solve", "stop", "solve"]);
    expect(sent[2].id).toBe(sent[1].id);
    // a model request that is in flight when stop() is called is not stopped either
    const pending = gated();
    const running = pending.h.client.solve(modelRequest());
    await inFlight(pending.h);
    pending.h.client.stop();
    pending.open();
    expect(await running).toMatchObject({ kind: "model", status: "optimal" });
    expect(posted(pending.h).filter((message) => message.type === "stop")).toEqual([]);
  });
});

// ---- with a scripted worker, under fake timers ---------------------------------------------------------------------------------------

describe("the watchdog and the checks, with a scripted worker", () => {
  const OWNED = [["w90001@4", 1], ["w90007@4", 2], ["w80113@0", 1]];
  const scenarioOf = () => ({ race: "OGR", role: "balanced", buffs: "own", evidence: "wiki", setup: "dw" });
  const request = (over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "farm-path", scenario: scenarioOf(), owned: OWNED.map((pair) => [...pair]), tierMode: { ...READY4 }, steps: 3, budgetMs: 1000, ...over });
  const wear = (...entries) => {
    const kit = new Array(22).fill(null);
    for (const [place, ident] of entries) kit[place] = ident;
    return kit;
  };
  const KIT0 = wear([0, "w90001@4"], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@0"]);
  const KIT1 = wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@0"]);
  const KIT2 = wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [4, "w90011@4"], [21, "w80113@0"]);
  const stepZero = (id, over = {}) => ({ v: 1, type: "step", id, index: 0, status: "optimal", proven: true, label: null, F: "100/1", value: 100, kit: [...KIT0], buffs: [43], hasteAssumed: 40, ...over });
  const stepOne = (id, over = {}) => ({
    v: 1,
    type: "step",
    id,
    index: 1,
    found: true,
    ident: "w90009@4",
    kind: "new",
    sourceTier: null,
    cost: { exp: 0, copiesAtArrival: 0, potentials: 0 },
    F: "130/1",
    value: 130,
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
  const stepTwo = (id, over = {}) => stepOne(id, { index: 2, ident: "w90011@4", F: "145/1", value: 145, gain: "15/1", gainValue: 15, kit: [...KIT2], ...over });
  const result = (id, over = {}) => ({ v: 1, type: "result", id, kind: "scenario", mode: "farm-path", stopped: "limit", steps: 3, hasteAssumed: 40, elapsedMs: 123, ...over });

  /** A script that says ready and nothing else: the test says the rest through `worker.reply`. */
  const quiet = (site) => (message, reply) => {
    if (message.type === "init") reply({ v: 1, type: "ready", highs: "1.15.1", wasm: site.manifest.wasm.sha256 });
  };
  function scripted(over = {}) {
    const site = makeSite();
    const h = harness({ site, script: quiet(site), ...over });
    return h;
  }
  /** Begin a request and bring it to the moment the worker has it: returns the worker, the id and the outcome. */
  async function begin(h, req, options = {}) {
    const outcome = track(h.client.runScenario(req, options));
    await until(() => h.workers[0]?.sent.some((message) => message.type === "solve"));
    const worker = h.workers[0];
    return { worker, id: worker.sent.find((message) => message.type === "solve").id, outcome };
  }

  it("takes every step as a sign of life: a path whose steps come less than a watchdog window apart outlives the window that was set when it began", async () => {
    const h = scripted();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const seen = [];
    const { worker, id, outcome } = await begin(h, request({ budgetMs: 1000 }), { onStep: (message) => seen.push(message.index) });
    const WINDOW = 1000 + WATCHDOG_GRACE_MS; // the budget and the grace after the post of the request, or after the last sign of life
    await vi.advanceTimersByTimeAsync(WINDOW - 500);
    worker.reply(stepZero(id));
    await flush();
    await vi.advanceTimersByTimeAsync(WINDOW - 500); // longer than a window since the post, shorter since Equip now
    worker.reply(stepOne(id));
    await flush();
    await vi.advanceTimersByTimeAsync(WINDOW - 500);
    worker.reply(stepTwo(id));
    await flush();
    await vi.advanceTimersByTimeAsync(WINDOW - 500);
    worker.reply(result(id, { steps: 2, stopped: "no-gain" }));
    await flush();
    expect(outcome.state).toBe("resolved");
    expect(outcome.value).toMatchObject({ stopped: "no-gain", steps: 2 });
    expect(seen).toEqual([0, 1, 2]);
    expect(worker.terminated).toBe(false);
    expect(h.workers).toHaveLength(1);
  });

  it("stops a worker that is silent for a window after its last step: the watchdog still works", async () => {
    const h = scripted();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { worker, id, outcome } = await begin(h, request({ budgetMs: 1000 }));
    await vi.advanceTimersByTimeAsync(3000);
    worker.reply(stepZero(id));
    await flush();
    await vi.advanceTimersByTimeAsync(1000 + WATCHDOG_GRACE_MS - 1);
    expect(outcome.state).toBe("pending");
    await vi.advanceTimersByTimeAsync(2);
    expect(outcome.state).toBe("rejected");
    expect(outcome.error).toMatchObject({ code: "watchdog" });
    expect(worker.terminated).toBe(true);
  });

  it("sends a stop with the id of the request when stop() is called, and the scripted worker's own end of the path resolves the request", async () => {
    const h = scripted();
    const { worker, id, outcome } = await begin(h, request());
    worker.reply(stepZero(id));
    await flush();
    h.client.stop();
    expect(worker.sent.filter((message) => message.type === "stop")).toEqual([{ v: 1, type: "stop", id }]);
    worker.reply(result(id, { stopped: "stopped", steps: 0 }));
    await flush();
    expect(outcome.state).toBe("resolved");
    expect(outcome.value).toMatchObject({ stopped: "stopped", steps: 0 });
    expect(worker.terminated).toBe(false);
  });

  const DROPPED = {
    "a step that comes before Equip now": (id) => stepOne(id),
    "a step with an index that skips one": (id) => stepZero(id, { index: 2 }),
    "an Equip now whose kit wears what is not owned": (id) => stepZero(id, { kit: ["w99999@4", ...KIT0.slice(1)] }),
    "an Equip now with a value that is not its exact value rounded": (id) => stepZero(id, { value: 99 }),
    "an Equip now with a field more": (id) => stepZero(id, { elapsedMs: 5 }),
    "a step of another request": (id) => stepZero(id + 1),
    "a step with no id": (id) => ({ ...stepZero(id), id: undefined }),
  };
  for (const [name, build] of Object.entries(DROPPED)) {
    it(`drops a worker that sends ${name}`, async () => {
      const h = scripted();
      const { worker, id, outcome } = await begin(h, request());
      worker.reply(build(id));
      await flush();
      expect(outcome.state).toBe("rejected");
      expect(outcome.error).toMatchObject({ code: "protocol" });
      expect(worker.terminated).toBe(true);
    });
  }

  it("drops a worker whose step breaks the path: a gain that is not the difference of the values, a kit with what nobody acquired, a haste that changed, a step after the last", async () => {
    const breaks = [
      (id) => stepOne(id, { gain: "29/1", gainValue: 29 }),
      (id) => stepOne(id, { kit: wear([0, "w90001@4"], [1, "w90009@4"], [2, "w90007@4"], [3, "w90007@4"], [4, "w55555@4"], [21, "w80113@0"]) }),
      (id) => stepOne(id, { hasteAssumed: 41 }),
      (id) => stepOne(id, { ident: "w90003@4" }),
      (id) => stepOne(id, { kind: "upgrade", sourceTier: 0, cost: { exp: 15, copiesAtArrival: 1, potentials: 4 } }),
    ];
    for (const build of breaks) {
      const h = scripted();
      const { worker, id, outcome } = await begin(h, request());
      worker.reply(stepZero(id));
      await flush();
      expect(outcome.state).toBe("pending");
      worker.reply(build(id));
      await flush();
      expect(outcome).toMatchObject({ state: "rejected", error: { code: "protocol" } });
      expect(worker.terminated).toBe(true);
    }
    // a step that was not found ends the path: a step after it is a worker that does not know where it is
    const h = scripted();
    const { worker, id, outcome } = await begin(h, request());
    worker.reply(stepZero(id));
    worker.reply(stepOne(id, { found: false, ident: null, kind: null, sourceTier: null, cost: null, F: null, value: null, gain: null, gainValue: null, kit: null, buffs: [], status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT }));
    worker.reply(stepTwo(id));
    await flush();
    expect(outcome).toMatchObject({ state: "rejected", error: { code: "protocol" } });
  });

  it("drops a worker whose result does not agree with the steps that came: another count, a limit that was not reached", async () => {
    for (const bad of [result(1, { steps: 1 }), result(1, { stopped: "limit", steps: 0 }), result(1, { stopped: "no-gain", steps: 1, hasteAssumed: 41 }), result(1, { stopped: "time", steps: 4 })]) {
      const h = scripted();
      const { worker, id, outcome } = await begin(h, request());
      worker.reply(stepZero(id));
      worker.reply(stepOne(id));
      worker.reply({ ...bad, id });
      await flush();
      expect(outcome).toMatchObject({ state: "rejected", error: { code: "protocol" } });
      expect(worker.terminated).toBe(true);
    }
  });

  it("drops a worker that sends a step for a request that is not a farm path, or a step when nothing is in flight", async () => {
    const h = scripted();
    const { worker, id, outcome } = await begin(h, base(C0, { mode: "equip-now" }));
    worker.reply(stepZero(id));
    await flush();
    expect(outcome).toMatchObject({ state: "rejected", error: { code: "protocol" } });
    const idle = scripted();
    const done = track(idle.client.runScenario(request()));
    await until(() => idle.workers[0]?.sent.some((message) => message.type === "solve"));
    const w = idle.workers[0];
    const solveId = w.sent.find((message) => message.type === "solve").id;
    w.reply(stepZero(solveId));
    w.reply(stepOne(solveId));
    w.reply({ ...result(solveId, { steps: 1, stopped: "no-gain" }) });
    await flush();
    expect(done.state).toBe("resolved");
    w.reply(stepZero(solveId + 1)); // a step now that nothing is in flight
    await flush();
    expect(w.terminated).toBe(true);
  });

  it("checks the progress of a request against its mode: a stage of another mode is a worker to drop", async () => {
    const h = scripted();
    const { worker, id, outcome } = await begin(h, request());
    worker.reply({ v: 1, type: "progress", id, phase: "building", stage: "best-sets" });
    await flush();
    expect(outcome).toMatchObject({ state: "rejected", error: { code: "protocol" } });
    expect(worker.terminated).toBe(true);
  });

  describe("the tier mode and the kit that the request had", () => {
    const withoutSteps = () => {
      const { steps, ...rest } = request();
      return rest;
    };
    const setsRequest = (over = {}) => ({ ...withoutSteps(), mode: "best-sets", k: 2, ...over });
    const slotsRequest = (over = {}) => ({ ...withoutSteps(), mode: "every-slot", kit: [...KIT0], buffs: [43], ...over });
    const acquire = (ident, kind = "new") => ({ ident, kind, sourceTier: null, cost: null });
    const setResult = (id, over = {}) => ({
      v: 1,
      type: "result",
      id,
      kind: "scenario",
      mode: "best-sets",
      k: 2,
      acquired: [acquire("w90009@4"), acquire("w90011@4", "copy")],
      F: "145/1",
      value: 145,
      gain: "45/1",
      gainValue: 45,
      kit: [...KIT2],
      buffs: [43],
      status: "optimal",
      proven: true,
      label: null,
      baseline: { F: "100/1", value: 100 },
      hasteAssumed: 40,
      elapsedMs: 250,
      ...over,
    });
    const swap = (ident, delta = "1/1", deltaValue = 1) => ({ ident, delta, deltaValue });
    const rowsOf = (kit, swapsAt = {}) => KIT_PLACE_NAMES.map((place, index) => ({ place, index, current: kit[index], swaps: swapsAt[index] ?? [] }));
    const slotsResult = (id, rows) => ({ v: 1, type: "result", id, kind: "scenario", mode: "every-slot", rows, elapsedMs: 5 });
    /** The worker is dropped for what it said: a protocol error, and the worker terminated. */
    const dropped = async (outcome, worker) => {
      await flush();
      expect(outcome).toMatchObject({ state: "rejected", error: { code: "protocol" } });
      expect(worker.terminated).toBe(true);
    };
    const accepted = async (outcome, worker) => {
      await flush();
      expect(outcome.state).toBe("resolved");
      expect(worker.terminated).toBe(false);
    };

    it("drops a worker whose step acquires an item at a tier that the tier mode does not give, and takes one at the tier it gives", async () => {
      const at = (id, tier) => stepOne(id, { ident: `w90009@${tier}`, cost: null, kit: wear([0, "w90001@4"], [1, `w90009@${tier}`], [2, "w90007@4"], [3, "w90007@4"], [21, "w80113@0"]) });
      for (const [tierMode, wrong, right] of [[READY4, 3, 4], [{ mode: "fixed", N: 10 }, 4, 10], [{ mode: "arrives", D: 2 }, 3, 2], [{ mode: "arrives", D: 2 }, 4, 0]]) {
        const label = `${JSON.stringify(tierMode)}: +${wrong} / +${right}`;
        const bad = scripted();
        const refused = await begin(bad, request({ tierMode }));
        refused.worker.reply(stepZero(refused.id));
        refused.worker.reply(at(refused.id, wrong));
        await flush();
        expect(refused.outcome.state, label).toBe("rejected");
        expect(refused.outcome.error, label).toMatchObject({ code: "protocol" });
        expect(refused.worker.terminated, label).toBe(true);
        const good = scripted();
        const taken = await begin(good, request({ tierMode }));
        taken.worker.reply(stepZero(taken.id));
        taken.worker.reply(at(taken.id, right));
        taken.worker.reply(result(taken.id, { steps: 1, stopped: "no-gain" }));
        await flush();
        expect(taken.outcome.state, label).toBe("resolved");
        expect(taken.worker.terminated, label).toBe(false);
      }
    });

    it("drops a worker whose best set acquires an item at another tier than the mode gives, or whose kit does not wear what the set acquires", async () => {
      const cases = [
        ["an addition at another tier", (id) => setResult(id, { acquired: [acquire("w90009@3"), acquire("w90011@4", "copy")], kit: wear([0, "w90001@4"], [1, "w90009@3"], [2, "w90007@4"], [3, "w90007@4"], [4, "w90011@4"], [21, "w80113@0"]) })],
        ["a kit that does not wear an addition", (id) => setResult(id, { kit: [...KIT1] })],
        ["a kit that wears one copy of what was added twice", (id) => setResult(id, { acquired: [acquire("w90009@4"), acquire("w90009@4", "copy")], kit: [...KIT1] })],
      ];
      for (const [name, build] of cases) {
        const h = scripted();
        const { worker, id, outcome } = await begin(h, setsRequest());
        worker.reply(build(id));
        await flush();
        expect(outcome.state, name).toBe("rejected");
        expect(outcome.error, name).toMatchObject({ code: "protocol" });
        expect(worker.terminated, name).toBe(true);
      }
      // and the set that does both is taken
      const h = scripted();
      const { worker, id, outcome } = await begin(h, setsRequest());
      worker.reply(setResult(id));
      await accepted(outcome, worker);
      expect(outcome.value).toMatchObject({ mode: "best-sets", k: 2 });
    });

    it("drops a worker whose rows do not say what the request's kit wears, and takes the rows that do", async () => {
      const cases = [
        ["nothing where the kit has an item", rowsOf(KIT0.map((ident, at) => (at === 0 ? null : ident)))],
        ["an item where the kit has none", rowsOf(KIT0.map((ident, at) => (at === 1 ? "w90009@4" : ident)))],
        ["another tier of the item the kit has", rowsOf(KIT0.map((ident, at) => (at === 21 ? "w80113@4" : ident)))],
      ];
      for (const [name, rows] of cases) {
        const h = scripted();
        const { worker, id, outcome } = await begin(h, slotsRequest());
        worker.reply(slotsResult(id, rows));
        await flush();
        expect(outcome.state, name).toBe("rejected");
        expect(outcome.error, name).toMatchObject({ code: "protocol" });
        expect(worker.terminated, name).toBe(true);
      }
      const h = scripted();
      const { worker, id, outcome } = await begin(h, slotsRequest());
      worker.reply(slotsResult(id, rowsOf(KIT0)));
      await accepted(outcome, worker);
    });

    it("drops a worker whose swap is an item the visitor does not own, at a tier the mode does not give, and takes an owned one or one at the tier of the mode", async () => {
      const unowned = [["w90009@3", READY4], ["w80113@1", READY4], ["w90009@4", { mode: "fixed", N: 10 }], ["w90009@3", { mode: "arrives", D: 2 }]];
      for (const [ident, tierMode] of unowned) {
        const label = `${ident} under ${JSON.stringify(tierMode)}`;
        const h = scripted();
        const { worker, id, outcome } = await begin(h, slotsRequest({ tierMode }));
        worker.reply(slotsResult(id, rowsOf(KIT0, { 4: [swap(ident)] })));
        await flush();
        expect(outcome.state, label).toBe("rejected");
        expect(outcome.error, label).toMatchObject({ code: "protocol" });
        expect(worker.terminated, label).toBe(true);
      }
      // (a copy to spare of what the kit wears: an owned item that is no candidate of the mode is a swap only while a copy is free)
      const spare = [["w90001@4", 1], ["w90007@4", 3], ["w80113@0", 2]];
      const fine = [["w90009@4", READY4], ["w80113@0", READY4], ["w90007@4", { mode: "fixed", N: 10 }], ["w90009@2", { mode: "arrives", D: 2 }], ["w90009@0", { mode: "arrives", D: 2 }]];
      for (const [ident, tierMode] of fine) {
        const h = scripted();
        const { worker, id, outcome } = await begin(h, slotsRequest({ tierMode, owned: spare.map((pair) => [...pair]) }));
        worker.reply(slotsResult(id, rowsOf(KIT0, { 4: [swap(ident)] })));
        await accepted(outcome, worker);
      }
    });

    it("drops a worker whose swap is an owned item beyond the copies the kit leaves free, when the mode cannot have given it", async () => {
      // the request owns w80113@0 once and w90007@4 twice, and its kit wears them all: no copy is free for another place
      const beyond = [["w80113@0", READY4], ["w80113@0", { mode: "fixed", N: 10 }], ["w90007@4", { mode: "fixed", N: 10 }], ["w90007@4", { mode: "arrives", D: 2 }]];
      for (const [ident, tierMode] of beyond) {
        const h = scripted();
        const { worker, id, outcome } = await begin(h, slotsRequest({ tierMode }));
        worker.reply(slotsResult(id, rowsOf(KIT0, { 4: [swap(ident)] })));
        await dropped(outcome, worker);
      }
      // an owned item at the tier of the mode may be a candidate, and the page cannot tell: it is taken
      const h = scripted();
      const { worker, id, outcome } = await begin(h, slotsRequest({ tierMode: READY4 }));
      worker.reply(slotsResult(id, rowsOf(KIT0, { 4: [swap("w90007@4")] })));
      await accepted(outcome, worker);
    });
  });

  it("hands the reports of progress, with their stage and step, to onProgress, and a step to onStep with nothing of the envelope", async () => {
    const h = scripted();
    const reports = [];
    const steps = [];
    const { worker, id, outcome } = await begin(h, request(), { onProgress: (report) => reports.push(report), onStep: (message) => steps.push(message) });
    worker.reply({ v: 1, type: "progress", id, phase: "building", stage: "equip-now" });
    worker.reply(stepZero(id));
    worker.reply({ v: 1, type: "progress", id, phase: "solving", stage: "step", step: 1 });
    worker.reply(stepOne(id));
    worker.reply(result(id, { steps: 1, stopped: "no-gain" }));
    await flush();
    expect(outcome.state).toBe("resolved");
    expect(reports.filter((report) => report.stage !== undefined)).toEqual([
      { phase: "building", stage: "equip-now" },
      { phase: "solving", stage: "step", step: 1 },
    ]);
    expect(steps.map((message) => message.index)).toEqual([0, 1]);
    expect(Object.keys(steps[1])).not.toEqual(expect.arrayContaining(["v", "type", "id"]));
    expect(outcome.value).toMatchObject({ kind: "scenario", mode: "farm-path", stopped: "no-gain", steps: 1 });
  });
});
