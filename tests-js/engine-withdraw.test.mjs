// The client's withdraw of one request (client.js): `runScenario(request, {signal})` with an AbortSignal. A section of the page that no longer wants an answer takes back its own
// request and no other: a request that waits is taken out of the queue and rejected as "cancelled"; a request that the worker is working on is rejected the same way and the worker is
// stopped, since a solve cannot be interrupted from outside, and the next request is answered by a worker that starts again from the module the client kept. Nothing else is touched:
// not the request that runs when a request that waits is withdrawn, not a request of another section, and never the worker of a request that is not that one. `onSent` says when the worker has
// the request. A newer best-kit request with `replaceWaiting` replaces a best kit that has not reached the worker either (the one the client began for and that waits for the visitor's
// answer to the question), so that a yes does not solve what is thrown away. Two kinds of worker here: a scripted one, and the real worker core on the real solver.

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

const [FIRST, , LAST] = REFERENCE.cases; // the reference's view with armor class x2 and with attack and haste x2
const OWNED = EQUIP_NOW.cases[1];
/** A request of another mode than the best kit, as another section of the page makes (the answer to it is one message). */
const equipRequest = (over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "equip-now", scenario: { ...OWNED.scenario }, owned: OWNED.owned.map((pair) => [...pair]), budgetMs: 120_000, ...over });
const pathRequest = (over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "farm-path", scenario: { ...OWNED.scenario }, owned: OWNED.owned.map((pair) => [...pair]), tierMode: { mode: "ready4" }, steps: 3, budgetMs: 120_000, ...over });

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
  const manifestFetches = [];
  const pageFetch = async (url) => {
    manifestFetches.push(String(url));
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
  return { client, workers, site, ask, manifestFetches, ...fetching };
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
  for (let i = 0; i < 4000 && !test(); i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
  expect(test()).toBe(true);
}
const solves = (worker) => worker.sent.filter((message) => message.type === "solve");
const quiet = (site) => (message, reply) => {
  if (message.type === "init") reply({ v: 1, type: "ready", highs: "1.15.1", wasm: site.manifest.wasm.sha256 });
  if (message.type === "ping") reply({ v: 1, type: "pong" });
};
function scripted(options = {}) {
  const site = makeSite();
  return harness({ site, script: quiet(site), ...options });
}
const KIT = FIRST.kit;
const answer = (id, over = {}) => ({ v: 1, type: "result", id, kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null, F: FIRST.F, value: FIRST.value, kit: [...KIT], buffs: FIRST.buffs, hasteAssumed: FIRST.hasteAssumed, elapsedMs: 5, ...over });
const equipDone = (id) => ({ v: 1, type: "result", id, kind: "scenario", mode: "equip-now", status: "optimal", proven: true, label: null, F: OWNED.F, value: OWNED.value, kit: [...OWNED.kit], buffs: [...OWNED.buffs], hasteAssumed: OWNED.hasteAssumed, elapsedMs: 5 });
const code = (outcome) => outcome.error?.code;

/** A request is started and the worker has it: resolves with its outcome and the id the worker was given. */
async function running(h, request, options = {}) {
  const controller = new AbortController();
  const outcome = track(h.client.runScenario(request, { signal: controller.signal, ...options }));
  await until(() => h.workers[0] !== undefined && solves(h.workers[0]).length >= 1);
  return { outcome, controller, id: solves(h.workers[0])[0].id };
}

describe("a request withdrawn with its signal", () => {
  it("is rejected as cancelled at once when the signal was aborted before the request was made: nothing is asked of the visitor, fetched or started", async () => {
    const h = scripted();
    const controller = new AbortController();
    controller.abort();
    await expect(h.client.runScenario(caseRequest(FIRST), { signal: controller.signal })).rejects.toMatchObject({ name: "EngineError", code: "cancelled" });
    expect(h.ask).not.toHaveBeenCalled();
    expect(h.manifestFetches).toEqual([]);
    expect(h.workers).toHaveLength(0);
  });

  it("is taken out of the queue when it waits, and rejected as cancelled; the request that runs and the ones behind it are not touched, and the worker is not stopped", async () => {
    const h = scripted();
    const first = await running(h, caseRequest(FIRST));
    const waiting = new AbortController();
    const withdrawn = track(h.client.runScenario(caseRequest(LAST), { signal: waiting.signal }));
    const behind = track(h.client.runScenario(caseRequest(FIRST, { tier: 0 })));
    await flush();
    expect(withdrawn.state).toBe("pending");
    waiting.abort();
    await flush();
    expect(withdrawn).toMatchObject({ state: "rejected", error: { name: "EngineError", code: "cancelled" } });
    expect(first.outcome.state).toBe("pending");
    expect(behind.state).toBe("pending");
    expect(h.workers[0].terminated).toBe(false);
    // the request that runs is answered, and the one behind it takes its turn on the same worker: the withdrawn one is never sent
    h.workers[0].reply(answer(first.id));
    await until(() => solves(h.workers[0]).length === 2);
    expect(first.outcome.state).toBe("resolved");
    expect(solves(h.workers[0])[1].request.tier).toBe(0);
    h.workers[0].reply(answer(solves(h.workers[0])[1].id, { kit: KIT.map((ident) => (ident === null ? null : ident.replace("@4", "@0"))) }));
    await flush();
    expect(behind.state).toBe("resolved");
    expect(h.workers).toHaveLength(1);
    expect(h.client.stats()).toMatchObject({ spawns: 1, solves: 2 });
  });

  it("stops the worker when the request is the one it is working on, rejects it as cancelled and leaves the request behind it to a worker that starts again", async () => {
    const h = scripted();
    const first = await running(h, caseRequest(FIRST));
    const behind = track(h.client.runScenario(caseRequest(LAST)));
    await flush();
    first.controller.abort();
    await flush();
    expect(first.outcome).toMatchObject({ state: "rejected", error: { code: "cancelled" } });
    expect(h.workers[0].terminated).toBe(true);
    await until(() => h.workers[1] !== undefined && solves(h.workers[1]).length === 1);
    expect(solves(h.workers[1])[0].request).toEqual(caseRequest(LAST));
    expect(behind.state).toBe("pending");
    h.workers[1].reply(answer(solves(h.workers[1])[0].id));
    await flush();
    expect(behind.state).toBe("resolved");
    expect(h.client.stats()).toMatchObject({ spawns: 2, solves: 2 });
    expect(h.ask).toHaveBeenCalledTimes(1); // (the visitor agreed once: a worker that starts again asks nothing)
  });

  it("never stops the worker of a request that is not the withdrawn one: a request that waits is withdrawn while a path of another section runs", async () => {
    const h = scripted();
    const { outcome: path, id } = await running(h, equipRequest());
    const controller = new AbortController();
    const slider = track(h.client.runScenario(caseRequest(FIRST), { signal: controller.signal, replaceWaiting: true }));
    await flush();
    controller.abort();
    await flush();
    expect(slider).toMatchObject({ state: "rejected", error: { code: "cancelled" } });
    expect(path.state).toBe("pending");
    expect(h.workers[0].terminated).toBe(false);
    h.workers[0].reply(equipDone(id));
    await flush();
    expect(path.state).toBe("resolved");
  });

  it("does not touch the request that runs when the signal of a request behind it fires twice or after the request was over", async () => {
    const h = scripted();
    const first = await running(h, caseRequest(FIRST));
    const behind = new AbortController();
    const outcome = track(h.client.runScenario(caseRequest(LAST), { signal: behind.signal }));
    await flush();
    behind.abort();
    behind.abort();
    await flush();
    expect(outcome.state).toBe("rejected");
    h.workers[0].reply(answer(first.id));
    await flush();
    expect(first.outcome.state).toBe("resolved");
    first.controller.abort(); // (it is over: nothing is left to withdraw)
    await flush();
    expect(first.outcome.state).toBe("resolved");
    expect(h.workers[0].terminated).toBe(false);
  });

  it("is withdrawn while the visitor's question is open: it is rejected at once, and a yes then loads nothing for it", async () => {
    let yes;
    const ask = vi.fn(() => new Promise((resolve) => (yes = resolve)));
    const h = scripted({ ask });
    const controller = new AbortController();
    const outcome = track(h.client.runScenario(caseRequest(FIRST), { signal: controller.signal }));
    await until(() => ask.mock.calls.length === 1);
    controller.abort();
    await flush();
    expect(outcome).toMatchObject({ state: "rejected", error: { code: "cancelled" } });
    yes(true);
    await flush();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(h.workers).toHaveLength(0); // (nothing was started for the request that was thrown away)
    // the next request is asked for by nobody: the yes was given, and it is the next request that loads
    const next = track(h.client.runScenario(caseRequest(LAST)));
    await until(() => h.workers[0] !== undefined && solves(h.workers[0]).length === 1);
    expect(ask).toHaveBeenCalledTimes(1);
    h.workers[0].reply(answer(solves(h.workers[0])[0].id));
    await flush();
    expect(next.state).toBe("resolved");
  });

  it("leaves a request of another section that waits for the question as it was", async () => {
    let yes;
    const ask = vi.fn(() => new Promise((resolve) => (yes = resolve)));
    const h = scripted({ ask });
    const other = track(h.client.runScenario(equipRequest())); // the one the question was asked for
    await until(() => ask.mock.calls.length === 1);
    const controller = new AbortController();
    const mine = track(h.client.runScenario(caseRequest(FIRST), { signal: controller.signal }));
    await flush();
    controller.abort();
    await flush();
    expect(mine).toMatchObject({ state: "rejected", error: { code: "cancelled" } });
    expect(other.state).toBe("pending");
    yes(true);
    await until(() => h.workers[0] !== undefined && solves(h.workers[0]).length === 1);
    expect(solves(h.workers[0])[0].request.mode).toBe("equip-now");
    h.workers[0].reply(equipDone(solves(h.workers[0])[0].id));
    await flush();
    expect(other.state).toBe("resolved");
  });
});

describe("onSent", () => {
  it("is called once when the worker has the request, and not while the request waits", async () => {
    const h = scripted();
    const sentFirst = vi.fn();
    const sentSecond = vi.fn();
    const first = track(h.client.runScenario(caseRequest(FIRST), { onSent: sentFirst }));
    const second = track(h.client.runScenario(caseRequest(LAST), { onSent: sentSecond }));
    await until(() => h.workers[0] !== undefined && solves(h.workers[0]).length === 1);
    expect(sentFirst).toHaveBeenCalledTimes(1);
    expect(sentSecond).not.toHaveBeenCalled();
    h.workers[0].reply(answer(solves(h.workers[0])[0].id));
    await until(() => solves(h.workers[0]).length === 2);
    expect(sentFirst).toHaveBeenCalledTimes(1);
    expect(sentSecond).toHaveBeenCalledTimes(1);
    h.workers[0].reply(answer(solves(h.workers[0])[1].id));
    await flush();
    expect([first.state, second.state]).toEqual(["resolved", "resolved"]);
  });

  it("is not called for a request that was withdrawn before its turn, and a callback that throws breaks nothing", async () => {
    const h = scripted();
    const first = await running(h, caseRequest(FIRST), { onSent: () => { throw new Error("a bug of the page"); } });
    const sent = vi.fn();
    const controller = new AbortController();
    track(h.client.runScenario(caseRequest(LAST), { signal: controller.signal, onSent: sent }));
    await flush();
    controller.abort();
    h.workers[0].reply(answer(first.id));
    await flush();
    expect(first.outcome.state).toBe("resolved");
    expect(sent).not.toHaveBeenCalled();
    expect(h.workers[0].terminated).toBe(false);
  });
});

describe("replaceWaiting and the request that has not reached the worker", () => {
  it("replaces a best kit that the client has begun for and that waits for the visitor's answer: a yes solves the newest request and nothing else", async () => {
    let yes;
    const ask = vi.fn(() => new Promise((resolve) => (yes = resolve)));
    const h = scripted({ ask });
    const old = track(h.client.runScenario(caseRequest(FIRST), { replaceWaiting: true }));
    await until(() => ask.mock.calls.length === 1);
    const newest = track(h.client.runScenario(caseRequest(LAST), { replaceWaiting: true }));
    await flush();
    expect(old).toMatchObject({ state: "rejected", error: { code: "cancelled" } }); // (the request the question was asked for is not wanted any more)
    expect(newest.state).toBe("pending");
    yes(true);
    await until(() => h.workers[0] !== undefined && solves(h.workers[0]).length === 1);
    expect(solves(h.workers[0])[0].request).toEqual(caseRequest(LAST));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(solves(h.workers[0])).toHaveLength(1); // (the replaced one was never sent)
    expect(ask).toHaveBeenCalledTimes(1);
    h.workers[0].reply(answer(solves(h.workers[0])[0].id));
    await flush();
    expect(newest.state).toBe("resolved");
  });

  it("replaces nothing when the newer best kit is refused as busy: the queue is full of other requests, and the best kit the client has begun for is still waiting for the question (G3)", async () => {
    let yes;
    const ask = vi.fn(() => new Promise((resolve) => (yes = resolve)));
    const h = scripted({ ask });
    const old = track(h.client.runScenario(caseRequest(FIRST), { replaceWaiting: true })); // the one the question was asked for
    await until(() => ask.mock.calls.length === 1);
    const others = Array.from({ length: 64 }, () => track(h.client.runScenario(equipRequest()))); // (as many as the queue holds)
    await flush();
    expect(others.every((one) => one.state === "pending")).toBe(true);
    const newer = track(h.client.runScenario(caseRequest(LAST), { replaceWaiting: true }));
    await flush();
    expect(code(newer), "the queue is full: the newer request is refused").toBe("busy");
    expect(old.state, "and the one it was to replace is not destroyed for it").toBe("pending");
    yes(false); // (the visitor says no: everything that waited is declined, and the test is over)
    await until(() => old.state !== "pending");
    expect(code(old)).toBe("declined");
  });

  it("does not replace a request of another mode that has not reached the worker, nor the best kit that the worker has", async () => {
    let yes;
    const ask = vi.fn(() => new Promise((resolve) => (yes = resolve)));
    const h = scripted({ ask });
    const path = track(h.client.runScenario(equipRequest(), { replaceWaiting: true })); // (replaceWaiting asks for nothing of another mode)
    await until(() => ask.mock.calls.length === 1);
    const kit = track(h.client.runScenario(caseRequest(LAST), { replaceWaiting: true }));
    await flush();
    expect(path.state).toBe("pending");
    expect(kit.state).toBe("pending");
    yes(true);
    await until(() => h.workers[0] !== undefined && solves(h.workers[0]).length === 1);
    expect(solves(h.workers[0])[0].request.mode).toBe("equip-now");
    h.workers[0].reply(equipDone(solves(h.workers[0])[0].id));
    await until(() => solves(h.workers[0]).length === 2);
    const later = track(h.client.runScenario(bestKitRequest(FIRST.scenario, 4, { multipliers: { SV: 2 } }), { replaceWaiting: true }));
    await flush();
    expect(kit.state, "the best kit that the worker has is the one that runs: it is never replaced").toBe("pending");
    expect(later.state).toBe("pending");
  });
});

describe("a withdraw with the real worker", () => {
  it("stops the running solve of a best kit only, keeps the data (one download of the item table and the bundle), and the request behind it is answered right", async () => {
    const h = harness();
    const controller = new AbortController();
    const slider = track(h.client.runScenario(caseRequest(FIRST), { signal: controller.signal }));
    await until(() => h.workers[0] !== undefined && h.workers[0].sent.some((message) => message.type === "solve"));
    const path = track(h.client.runScenario(pathRequest({ steps: 2 })));
    controller.abort();
    await until(() => path.state !== "pending");
    expect(slider).toMatchObject({ state: "rejected", error: { code: "cancelled" } });
    expect(path).toMatchObject({ state: "resolved", value: { mode: "farm-path" } });
    expect(h.client.stats().spawns).toBe(2);
    const data = h.asked.filter((url) => url.includes("/assets/engine/data/"));
    expect(new Set(data).size).toBe(2); // (the item table and the bundle: the worker that started again read them again, from the browser's own copy)
    expect(h.ask).toHaveBeenCalledTimes(1);
  });
});
