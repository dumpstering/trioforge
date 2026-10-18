// The client's option replaceWaiting (client.js): `runScenario(request, {replaceWaiting: true})`. The sliders of the trio page send a request for the best kit at every change, and the
// worker does one at a time, so a newer best-kit request takes the place of the one that waits (that one is rejected as "cancelled"); the one that runs finishes, and its answer is the
// caller's to drop when it is old. Nothing else is touched: not a request of another mode, not a request that was made without the option, not the one that runs. Two kinds of worker
// here: the real worker core on the real solver (the files are those of the synthetic site fixture), and a scripted one.

import loadHighs from "highs";
import { JSDOM } from "jsdom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { createEngineClient } from "../pipeline/trioforge/site/static/engine/client.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { createWorkerCore } from "../pipeline/trioforge/site/static/engine/worker.js";
import { BASE, EQUIP_NOW, SLUG, makeSite, siteFetch } from "./engine-site-fixture.mjs";
import { REFERENCE, bestKitRequest, caseRequest } from "./best-kit-harness.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const [FIRST, , LAST] = REFERENCE.cases; // the same view with armor class x2 and with attack and haste x2: Python's answers for both

/** A worker object for the client: the core of a real worker behind it, or a script that says what the worker says. */
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

function harness({ script, ask = vi.fn(async () => true), site = makeSite() } = {}) {
  const fetching = siteFetch(site);
  const dom = new JSDOM('<!doctype html><html><body><main id="main"></main></body></html>', { url: "https://trioforge.test/trio/pal-mnk-ber/" });
  const pageFetch = async (url) => {
    const text = String(url) === "/engine-manifest.json" ? JSON.stringify(site.manifestJson) : String(url).startsWith("/engine-trios/") ? JSON.stringify(site.trioJson[String(url).slice("/engine-trios/".length).replace(/\.json$/, "")]) : undefined;
    if (text === undefined) return { ok: false, status: 404, text: async () => "not found" };
    return { ok: true, status: 200, text: async () => text };
  };
  const workers = [];
  const createWorker = () => {
    let worker;
    if (script) {
      worker = new FakeWorker({ script });
    } else {
      const engine = createScenarioEngine({ highs, fetchImpl: fetching.fetchImpl, baseUrl: BASE });
      let sink = () => {};
      const core = createWorkerCore({
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
          bestKit: (request, options) => engine.bestKit(request, options),
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
  const client = createEngineClient({ window: dom.window, document: dom.window.document, fetch: pageFetch, createWorker, consent: { ask }, trustedTypes: null });
  return { client, workers, site, ask, ...fetching };
}

function track(promise) {
  const outcome = { state: "pending", value: undefined, error: undefined };
  promise.then(
    (value) => Object.assign(outcome, { state: "resolved", value }),
    (error) => Object.assign(outcome, { state: "rejected", error }),
  );
  return outcome;
}
async function flush(rounds = 60) {
  for (let i = 0; i < rounds; i += 1) await Promise.resolve();
}
async function until(test) {
  for (let i = 0; i < 4000 && !test(); i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); // (the real worker's data and solver need more than microtasks)
  expect(test()).toBe(true);
}
const solves = (worker) => worker.sent.filter((message) => message.type === "solve");

/** The requests of ten changes of a slider: the first and the last are the references', the eight between them are other positions of the mana slider. */
function tenRequests() {
  const between = Array.from({ length: 8 }, (_, at) => bestKitRequest(FIRST.scenario, FIRST.tier, { multipliers: { MANA: at % 2 === 0 ? 0.5 : 2 } }));
  return [caseRequest(FIRST), ...between, caseRequest(LAST)];
}

describe("replaceWaiting with the real worker", () => {
  it("ten changes while one solve runs: one answer from the running request, eight requests cancelled, one answer from the last; one worker, one download", async () => {
    const h = harness();
    const requests = tenRequests();
    expect(requests).toHaveLength(10);
    const outcomes = [];
    outcomes.push(track(h.client.runScenario(requests[0], { replaceWaiting: true })));
    await until(() => h.workers[0] !== undefined && solves(h.workers[0]).length === 1); // it is running: the question was answered and the worker has it
    for (const request of requests.slice(1)) outcomes.push(track(h.client.runScenario(request, { replaceWaiting: true })));
    await flush();
    // the eight in the middle were replaced as the next one came: rejected as cancelled, and never sent to the worker
    for (const outcome of outcomes.slice(1, 9)) expect(outcome).toMatchObject({ state: "rejected", error: { name: "EngineError", code: "cancelled" } });
    expect(outcomes[9].state).toBe("pending"); // the last waits for the one that runs
    await until(() => outcomes[0].state !== "pending" && outcomes[9].state !== "pending");
    expect(outcomes[0]).toMatchObject({ state: "resolved", value: { mode: "best-kit", status: "optimal", F: FIRST.F, kit: FIRST.kit } }); // the running request finished: its answer is the caller's to drop
    expect(outcomes[9]).toMatchObject({ state: "resolved", value: { mode: "best-kit", status: "optimal", F: LAST.F, kit: LAST.kit } });
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].terminated).toBe(false);
    expect(solves(h.workers[0]).map((message) => message.request)).toEqual([requests[0], requests[9]]); // the worker saw two requests, the first and the last
    expect(h.ask).toHaveBeenCalledTimes(1);
    expect(h.client.stats()).toMatchObject({ spawns: 1, solves: 2 });
    const data = h.asked.filter((url) => url.includes("/assets/engine/data/"));
    expect(data.map((url) => new URL(url).pathname)).toEqual([h.site.itemsPath, h.site.bundlePath]); // one download: the item table once and the bundle once
  });

  it("does not replace anything without the option: the ten requests are all answered, in the order they were made", async () => {
    const h = harness();
    const requests = tenRequests().slice(0, 4);
    const outcomes = requests.map((request) => track(h.client.runScenario(request)));
    await until(() => outcomes.every((outcome) => outcome.state !== "pending"));
    expect(outcomes.map((outcome) => outcome.state)).toEqual(["resolved", "resolved", "resolved", "resolved"]);
    expect(solves(h.workers[0])).toHaveLength(4);
  });
});

describe("replaceWaiting with a scripted worker", () => {
  const quiet = (site) => (message, reply) => {
    if (message.type === "init") reply({ v: 1, type: "ready", highs: "1.15.1", wasm: site.manifest.wasm.sha256 });
    if (message.type === "ping") reply({ v: 1, type: "pong" }); // (an idle worker that has worked is asked whether it is still there before it gets the next request)
  };
  function scripted() {
    const site = makeSite();
    return harness({ site, script: quiet(site) });
  }
  const KIT = FIRST.kit;
  const answer = (id, over = {}) => ({ v: 1, type: "result", id, kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null, F: FIRST.F, value: FIRST.value, kit: [...KIT], buffs: FIRST.buffs, hasteAssumed: FIRST.hasteAssumed, elapsedMs: 5, ...over });
  const idOf = (worker, at) => solves(worker)[at].id;
  async function running(h, request) {
    const outcome = track(h.client.runScenario(request, { replaceWaiting: true }));
    await until(() => h.workers[0] !== undefined && solves(h.workers[0]).length === 1);
    return outcome;
  }

  it("replaces the request that waits with a newer one, and the newer one takes its turn after the one that runs", async () => {
    const h = scripted();
    const first = await running(h, caseRequest(FIRST));
    const second = track(h.client.runScenario(caseRequest(LAST), { replaceWaiting: true }));
    const third = track(h.client.runScenario(caseRequest(FIRST, { tier: 0 }), { replaceWaiting: true }));
    await flush();
    expect(second).toMatchObject({ state: "rejected", error: { code: "cancelled" } });
    expect(third.state).toBe("pending");
    expect(first.state).toBe("pending");
    const worker = h.workers[0];
    worker.reply(answer(idOf(worker, 0)));
    await until(() => solves(worker).length === 2);
    expect(first.state).toBe("resolved"); // the running request finished
    expect(solves(worker)[1].request.tier).toBe(0); // and the worker has the newest request, not the replaced one
    worker.reply(answer(idOf(worker, 1), { kit: KIT.map((ident) => (ident === null ? null : ident.replace("@4", "@0"))) }));
    await flush();
    expect(third.state).toBe("resolved");
  });

  it("never touches the request that runs, and a request that fails the protocol's check replaces nothing", async () => {
    const h = scripted();
    const first = await running(h, caseRequest(FIRST));
    const waiting = track(h.client.runScenario(caseRequest(LAST), { replaceWaiting: true }));
    await expect(h.client.runScenario(caseRequest(FIRST, { tier: 11 }), { replaceWaiting: true })).rejects.toMatchObject({ code: "bad-request" });
    await flush();
    expect(first.state).toBe("pending");
    expect(waiting.state).toBe("pending"); // the bad request was refused before it could take anyone's place
    expect(h.workers[0].terminated).toBe(false);
  });

  it("replaces the request that waits for the visitor's answer to the question as well, since it has not reached the worker: the question stays, and a yes solves the newest request", async () => {
    let answerQuestion;
    const ask = vi.fn(() => new Promise((resolve) => (answerQuestion = resolve)));
    const site = makeSite();
    const h = harness({ site, script: quiet(site), ask });
    const asking = track(h.client.runScenario(caseRequest(FIRST), { replaceWaiting: true })); // the question is open: this request is the one the client is working on
    await until(() => ask.mock.calls.length === 1);
    const newer = track(h.client.runScenario(caseRequest(LAST), { replaceWaiting: true }));
    const newest = track(h.client.runScenario(caseRequest(FIRST, { tier: 0 }), { replaceWaiting: true }));
    await flush();
    expect(asking).toMatchObject({ state: "rejected", error: { code: "cancelled" } }); // (it was asked for, and nothing of it was sent: a yes would only solve what is thrown away)
    expect(newer).toMatchObject({ state: "rejected", error: { code: "cancelled" } });
    expect(newest.state).toBe("pending");
    answerQuestion(true);
    await until(() => solves(h.workers[0] ?? { sent: [] }).length === 1);
    expect(solves(h.workers[0])[0].request.tier).toBe(0); // (the newest request is the one the worker is given)
    expect(ask).toHaveBeenCalledTimes(1);
  });

  it("replaces only the requests of the best kit: a request of another mode that waits stays, and a newer request of another mode replaces nothing", async () => {
    const h = scripted();
    const first = await running(h, caseRequest(FIRST));
    const equip = track(h.client.runScenario({ v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "equip-now", scenario: { ...EQUIP_NOW.cases[1].scenario }, owned: EQUIP_NOW.cases[1].owned.map((pair) => [...pair]), budgetMs: 120_000 }, { replaceWaiting: true }));
    const waitingKit = track(h.client.runScenario(caseRequest(LAST), { replaceWaiting: true }));
    const newerKit = track(h.client.runScenario(bestKitRequest(FIRST.scenario, 4, { multipliers: { SV: 2 } }), { replaceWaiting: true }));
    await flush();
    expect(waitingKit).toMatchObject({ state: "rejected", error: { code: "cancelled" } });
    expect(equip.state).toBe("pending"); // waiting, and not replaced by a best kit (nor does it replace the best kit that follows it)
    expect(newerKit.state).toBe("pending");
    expect(first.state).toBe("pending");
  });

  it("is not a way to replace anything unless asked: a best-kit request made without the option leaves the ones that wait", async () => {
    const h = scripted();
    await running(h, caseRequest(FIRST));
    const waiting = track(h.client.runScenario(caseRequest(LAST), { replaceWaiting: true }));
    const plain = track(h.client.runScenario(bestKitRequest(FIRST.scenario, 4, { multipliers: { SV: 2 } })));
    await flush();
    expect(waiting.state).toBe("pending");
    expect(plain.state).toBe("pending");
  });
});
