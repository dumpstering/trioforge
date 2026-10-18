// The page's side of the best-kit mode (client.js): runScenario(request) resolves to the final result, with the progress carrying the stage best-kit, and solve() runs the mode too. A
// request the protocol refuses never reaches the question or the worker, an error of the worker rejects with its code and leaves the worker where it was, and a worker that says
// what no best kit is (the result of another mode, a stage of another mode, a kit of two tiers, a kit with a value that is not its exact value) is dropped, as for the other modes.
// Two kinds of worker here: the real worker core on the real solver (the files are those of the synthetic site fixture), and a scripted one.

import loadHighs from "highs";
import { JSDOM } from "jsdom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { createEngineClient } from "../pipeline/trioforge/site/static/engine/client.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { createWorkerCore } from "../pipeline/trioforge/site/static/engine/worker.js";
import { BASE, SLUG, makeSite, siteFetch } from "./engine-site-fixture.mjs";
import { FINEST_WEIGHTS, REFERENCE, bestKitRequest, caseRequest } from "./best-kit-harness.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const SLIDER = REFERENCE.cases.find((c) => c.weights !== undefined);
const PLAIN = REFERENCE.cases.find((c) => c.weights === undefined);

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

/** A client on fake workers, an in-memory page and the manifests of the site fixture. */
function harness({ script, consent = { ask: async () => true }, site = makeSite() } = {}) {
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
  const client = createEngineClient({ window: dom.window, document: dom.window.document, fetch: pageFetch, createWorker, consent, trustedTypes: null });
  return { client, workers, site, manifestFetches, ...fetching, dom };
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
  for (let i = 0; i < 5000 && !test(); i += 1) await Promise.resolve();
  expect(test()).toBe(true);
}

describe("runScenario with the real worker", () => {
  it("resolves a request for the best kit to its final result, with the progress in the stage best-kit, and hands no step to anyone", async () => {
    const h = harness();
    const progress = [];
    const steps = [];
    const request = caseRequest(SLIDER);
    const result = await h.client.runScenario(request, { onStep: (message) => steps.push(message), onProgress: (report) => progress.push(report) });
    expect(result).toMatchObject({ kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null, F: SLIDER.F, kit: SLIDER.kit, buffs: SLIDER.buffs, hasteAssumed: SLIDER.hasteAssumed });
    expect(result.v).toBeUndefined();
    expect(result.elapsedMs).toBeGreaterThan(0);
    expect(steps).toEqual([]);
    expect([...new Set(progress.map((report) => report.stage).filter((stage) => stage !== undefined))]).toEqual(["loading", "best-kit"]);
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].sent.map((message) => message.type)).toEqual(["init", "solve"]);
    expect(h.workers[0].sent[1].request).toEqual(request);
  });

  it("accepts the real worker's kit at every tier it is asked at: the page holds it to the tier of the request, and the real worker's kit is at that tier", async () => {
    const h = harness();
    for (const tier of [0, 4, 10]) {
      const result = await h.client.runScenario(bestKitRequest(SLIDER.scenario, tier, SLIDER.weights));
      const worn = result.kit.filter((ident) => ident !== null);
      expect(worn.length, `+${tier}`).toBeGreaterThan(0);
      expect(worn.every((ident) => ident.endsWith(`@${tier}`)), `+${tier}`).toBe(true);
    }
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].terminated).toBe(false);
  });

  it("takes the mode as it takes the others: solve() runs it too, one question is asked, and it is the question of the other modes' size", async () => {
    const ask = vi.fn(async () => true);
    const sized = makeSite({ lie: { items: { gzip: 400_000 }, bundle: { gzip: 90_000 } } });
    const h = harness({ consent: { ask }, site: sized });
    const first = await h.client.solve(caseRequest(PLAIN));
    expect(first).toMatchObject({ kind: "scenario", mode: "best-kit", F: PLAIN.F });
    await h.client.solve(caseRequest(SLIDER));
    expect(ask).toHaveBeenCalledTimes(1);
    expect(ask.mock.calls[0][0].megabytes).toBe(1.8);
    expect(h.client.stats()).toMatchObject({ spawns: 1, solves: 2 });
  });

  it("rejects with the code of the worker's error for a request the data does not fit, and the worker is not dropped for it", async () => {
    const h = harness();
    await expect(h.client.runScenario(bestKitRequest(SLIDER.scenario, SLIDER.tier, { multipliers: { NOPE: 2 } }))).rejects.toMatchObject({ code: "bad-request" });
    await expect(h.client.runScenario(bestKitRequest({ ...SLIDER.scenario, race: "ZZZ" }, SLIDER.tier))).rejects.toMatchObject({ code: "bad-request" });
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].terminated).toBe(false);
    expect((await h.client.runScenario(caseRequest(PLAIN))).F).toBe(PLAIN.F);
    expect(h.workers).toHaveLength(1);
  });

  it("refuses a weight with a number too small or too fine at once, as a bad request, and drops no worker for the exact value of any weight it lets through", async () => {
    // a custom weight of 5e-324 made an exact value of 657 characters, and a regen window of 1e-100 one of 209: the page reads up to 200 and drops a worker that sends more
    const ask = vi.fn(async () => true);
    const h = harness({ consent: { ask } });
    for (const weights of [{ custom: { HP: 5e-324 } }, { regenT: 1e-100 }, { multipliers: { AC: 9.99999e-7 } }, { custom: { HP: 1.234567 } }, { regenT: 0.30000000000000004 }]) {
      await expect(h.client.runScenario(bestKitRequest(SLIDER.scenario, 4, weights)), JSON.stringify(weights)).rejects.toMatchObject({ code: "bad-request" });
    }
    expect(ask).not.toHaveBeenCalled();
    expect(h.manifestFetches).toEqual([]);
    expect(h.workers).toHaveLength(0);
    for (const weights of [FINEST_WEIGHTS, { custom: { HP: 1e-6 } }, { regenT: 1e-6 }, { custom: { HP: 0 }, regenT: 0 }]) {
      const result = await h.client.runScenario(bestKitRequest(SLIDER.scenario, 4, weights));
      expect(result, JSON.stringify(weights)).toMatchObject({ mode: "best-kit", status: "optimal" });
      expect(result.F.length).toBeLessThan(100);
    }
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].terminated).toBe(false);
  });

  it("refuses a request the protocol refuses at once: nothing is asked of the visitor, nothing is fetched and no worker is made", async () => {
    const ask = vi.fn(async () => true);
    const h = harness({ consent: { ask } });
    const refused = [
      { ...caseRequest(SLIDER), owned: [] },
      { ...caseRequest(SLIDER), candidates: [] },
      { ...caseRequest(SLIDER), tierMode: { mode: "ready4" } },
      caseRequest(SLIDER, { tier: 11 }),
      bestKitRequest(SLIDER.scenario, 4, { manaReachable: true }),
      bestKitRequest(SLIDER.scenario, 4, { multipliers: { AC: "2" } }),
      bestKitRequest(SLIDER.scenario, 4, { regenT: Number.NaN }),
      bestKitRequest(SLIDER.scenario, 4, { lock: ["w90003@4"] }),
    ];
    for (const request of refused) await expect(h.client.runScenario(request)).rejects.toMatchObject({ code: "bad-request" });
    expect(ask).not.toHaveBeenCalled();
    expect(h.manifestFetches).toEqual([]);
    expect(h.workers).toHaveLength(0);
  });
});

describe("with a scripted worker", () => {
  /** A script that says ready and nothing else: the test says the rest through `worker.reply`. */
  const quiet = (site) => (message, reply) => {
    if (message.type === "init") reply({ v: 1, type: "ready", highs: "1.15.1", wasm: site.manifest.wasm.sha256 });
  };
  function scripted() {
    const site = makeSite();
    return harness({ site, script: quiet(site) });
  }
  async function begin(h, request) {
    const outcome = track(h.client.runScenario(request));
    await until(() => h.workers[0]?.sent.some((message) => message.type === "solve"));
    const worker = h.workers[0];
    return { worker, id: worker.sent.find((message) => message.type === "solve").id, outcome };
  }
  const KIT = ["w90003@4", "w80816@4", "w90009@4", "w90009@4", ...new Array(17).fill(null), "w80113@4"];
  const answer = (id, over = {}) => ({
    v: 1,
    type: "result",
    id,
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
  const request = () => caseRequest(SLIDER);

  it("resolves the request to a result that is right, and a kit of nothing at all is right too", async () => {
    const h = scripted();
    const { worker, id, outcome } = await begin(h, request());
    worker.reply({ v: 1, type: "progress", id, phase: "building", stage: "best-kit" });
    worker.reply(answer(id));
    await flush();
    expect(outcome.state).toBe("resolved");
    expect(outcome.value).toMatchObject({ mode: "best-kit", kit: KIT, F: "41952357833/2200000" });
    const naked = scripted();
    const second = await begin(naked, request());
    second.worker.reply(answer(second.id, { kit: new Array(22).fill(null), buffs: [] }));
    await flush();
    expect(second.outcome.state).toBe("resolved");
  });

  const DROPPED = {
    "the result of another mode": (id) => answer(id, { mode: "equip-now" }),
    "a result with the fields of another mode": (id) => ({ ...answer(id), owned: [] }),
    "a kit with items of two tiers": (id) => answer(id, { kit: ["w90003@4", "w80816@5", ...KIT.slice(2)] }),
    // the request is at +4: a kit that is all at one tier, but not that one, with the exact value and its number as they were, is not the kit of the request
    "a kit all at +7 for a request at +4, the value and its number as they were": (id) => answer(id, { kit: KIT.map((ident) => (ident === null ? null : ident.replace("@4", "@7"))) }),
    "a kit all at +0 for a request at +4": (id) => answer(id, { kit: KIT.map((ident) => (ident === null ? null : ident.replace("@4", "@0"))) }),
    "a kit all at +10 for a request at +4": (id) => answer(id, { kit: KIT.map((ident) => (ident === null ? null : ident.replace("@4", "@10"))) }),
    "a kit with a value that is not its exact value": (id) => answer(id, { value: 99 }),
    "an optimal result that is not proven": (id) => answer(id, { proven: false }),
    "a time-limited result without the label that says so": (id) => answer(id, { status: "time_limit", proven: false, label: null }),
    "a result of another request": (id) => answer(id + 1),
    "a progress report of the stage of another mode": (id) => ({ v: 1, type: "progress", id, phase: "building", stage: "equip-now" }),
    "a progress report of a step": (id) => ({ v: 1, type: "progress", id, phase: "solving", stage: "step", step: 1 }),
    "a step message": (id) => ({ v: 1, type: "step", id, index: 0, status: "optimal", proven: true, label: null, F: "100/1", value: 100, kit: [...KIT], buffs: [], hasteAssumed: 40 }),
  };
  for (const [name, build] of Object.entries(DROPPED)) {
    it(`drops a worker that sends ${name}`, async () => {
      const h = scripted();
      const { worker, id, outcome } = await begin(h, request());
      worker.reply(build(id));
      await flush();
      expect(outcome).toMatchObject({ state: "rejected", error: { code: "protocol" } });
      expect(worker.terminated).toBe(true);
    });
  }

  it("holds the kit to the tier of the request, whatever tier that is: a kit at the request's tier is accepted, at +0 and at +10 as at +4, and one at the tier of another request is not", async () => {
    for (const tier of [0, 4, 10]) {
      const h = scripted();
      const { worker, id, outcome } = await begin(h, caseRequest(SLIDER, { tier }));
      worker.reply(answer(id, { kit: KIT.map((ident) => (ident === null ? null : ident.replace("@4", `@${tier}`))) }));
      await flush();
      expect(outcome.state, `+${tier}`).toBe("resolved");
      expect(worker.terminated).toBe(false);
    }
    const other = scripted();
    const { worker, id, outcome } = await begin(other, caseRequest(SLIDER, { tier: 7 })); // asked at +7, answered at +4
    worker.reply(answer(id));
    await flush();
    expect(outcome).toMatchObject({ state: "rejected", error: { code: "protocol" } });
    expect(worker.terminated).toBe(true);
  });

  it("asks the worker for what the request says and nothing more: the request goes through as it was checked", async () => {
    const h = scripted();
    const original = request();
    const { worker } = await begin(h, original);
    const sent = worker.sent.find((message) => message.type === "solve").request;
    expect(sent).toEqual(original);
    expect(sent.owned).toBeUndefined();
    expect(Object.keys(sent).sort()).toEqual(["budgetMs", "kind", "level", "mode", "scenario", "tier", "trio", "v", "weights"].sort());
    expect(SLUG).toBe(sent.trio);
  });
});
