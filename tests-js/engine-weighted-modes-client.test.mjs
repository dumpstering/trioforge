// The page's side of the weights in every mode (client.js, which is not changed by them): runScenario takes a request of any of the four Upgrade modes with `weights` and hands the
// worker the very weights it checked, the answer is Python's for those weights (fixtures/site/weighted.json), and a request that is stopped, cancelled or replaced by another with
// other weights keeps the rules it had without weights: a stop ends a path 'stopped' and keeps the worker, a cancel drops the worker and the next request starts a new one, and a
// request is worked out for its own weights and no other. The worker here is the real worker core on the real solver, behind a fake worker object.

import loadHighs from "highs";
import { JSDOM } from "jsdom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { createEngineClient } from "../pipeline/trioforge/site/static/engine/client.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { createWorkerCore } from "../pipeline/trioforge/site/static/engine/worker.js";
import { BASE, SLUG, WEIGHTED, makeSite, siteFetch } from "./engine-site-fixture.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const [C0, C1] = WEIGHTED.cases;
const pick = (object, keys) => Object.fromEntries(keys.map((key) => [key, object[key]]));
const ANSWER = ["F", "value", "kit", "buffs", "hasteAssumed"];
const STEP = ["ident", "kind", "sourceTier", "F", "value", "gain", "gainValue", "kit", "buffs"];
const base = (c, over = {}) => ({
  v: 1,
  kind: "scenario",
  trio: SLUG,
  level: 50,
  scenario: { ...c.scenario },
  owned: c.owned.map((pair) => [...pair]),
  weights: structuredClone(c.weights),
  budgetMs: 120_000,
  ...over,
});
const equip = (c, over) => base(c, { mode: "equip-now", ...over });
const farm = (c, over) => base(c, { mode: "farm-path", tierMode: { ...c.tierMode }, steps: c.farmPath.steps, ...over });
const sets = (c, k, over) => base(c, { mode: "best-sets", tierMode: { ...c.tierMode }, k, ...over });
const slots = (c, over) => base(c, { mode: "every-slot", tierMode: { ...c.tierMode }, kit: [...c.everySlot.kit], buffs: [...c.everySlot.buffs], limit: c.everySlot.limit, ...over });

/** A worker object for the client with the core of a real worker behind it. */
class FakeWorker {
  constructor(core) {
    this.core = core;
    this.terminated = false;
    this.sent = [];
    this.onmessage = null;
    this.onerror = null;
    this.onmessageerror = null;
    core.attach((message) => queueMicrotask(() => !this.terminated && this.onmessage?.({ data: structuredClone(message) })));
  }

  postMessage(data) {
    const copy = structuredClone(data);
    this.sent.push(copy);
    queueMicrotask(() => !this.terminated && this.core.handle(copy));
  }

  terminate() {
    this.terminated = true;
  }
}

/** A client on fake workers, an in-memory page and the manifests of the site fixture. */
function harness() {
  const site = makeSite();
  const fetching = siteFetch(site);
  const dom = new JSDOM('<!doctype html><html><body><main id="main"></main></body></html>', { url: "https://trioforge.test/trio/pal-mnk-ber/" });
  const pageFetch = async (url) => {
    const text = String(url) === "/engine-manifest.json" ? JSON.stringify(site.manifestJson) : String(url).startsWith("/engine-trios/") ? JSON.stringify(site.trioJson[String(url).slice("/engine-trios/".length).replace(/\.json$/, "")]) : undefined;
    if (text === undefined) return { ok: false, status: 404, text: async () => "not found" };
    return { ok: true, status: 200, text: async () => text };
  };
  const workers = [];
  const createWorker = () => {
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
    const worker = new FakeWorker(core);
    workers.push(worker);
    return worker;
  };
  const client = createEngineClient({ window: dom.window, document: dom.window.document, fetch: pageFetch, createWorker, consent: { ask: async () => true }, trustedTypes: null });
  return { client, workers };
}

const solveMessages = (worker) => worker.sent.filter((message) => message.type === "solve");

describe("runScenario with weights", () => {
  it("hands the worker the weights it checked, in every mode, and resolves to Python's answer for them", async () => {
    const h = harness();
    const got = await h.client.runScenario(equip(C0));
    expect(pick(got, ANSWER)).toEqual(pick(C0.equipNow, ANSWER));
    const seen = [];
    const path = await h.client.runScenario(farm(C0), { onStep: (step) => seen.push(step) });
    expect(path).toMatchObject({ mode: "farm-path", stopped: C0.farmPath.stopped, steps: C0.farmPath.path.length, hasteAssumed: C0.farmPath.hasteAssumed });
    expect(pick(seen[0], ["F", "value", "kit", "buffs"])).toEqual(C0.farmPath.start);
    expect(seen.slice(1).map((step) => pick(step, STEP))).toEqual(C0.farmPath.path);
    const set = await h.client.runScenario(sets(C0, 3));
    expect(pick(set, ["F", "value", "gain", "kit", "buffs", "hasteAssumed"])).toEqual(pick(C0.bestSets[1], ["F", "value", "gain", "kit", "buffs", "hasteAssumed"]));
    const rows = await h.client.runScenario(slots(C0));
    expect(rows.rows.map((row) => row.swaps.map((swap) => swap.delta))).toEqual(C0.everySlot.rows.map((row) => row.swaps.map((swap) => swap.delta)));
    // the weights the worker was sent are the weights that were checked, mode by mode
    expect(solveMessages(h.workers[0]).map((message) => [message.request.mode, message.request.weights])).toEqual(
      ["equip-now", "farm-path", "best-sets", "every-slot"].map((mode) => [mode, C0.weights]),
    );
    expect(h.workers).toHaveLength(1);
  });

  it("refuses weights that the protocol does not allow at once, in every mode: no worker, no download, no question", async () => {
    const h = harness();
    const modes = [equip, farm, (c, over) => sets(c, 2, over), slots];
    for (const build of modes) {
      for (const weights of [{ manaReachable: true }, { custom: { HP: 1.234567 } }, { regenT: 1e-100 }, { multipliers: { AC: "2" } }, []]) {
        await expect(h.client.runScenario(build(C0, { weights })), JSON.stringify(weights)).rejects.toMatchObject({ code: "bad-request" });
      }
    }
    expect(h.workers).toHaveLength(0);
    expect(h.client.consentState()).not.toBe("granted");
  });

  it("stop() ends a farm path with weights 'stopped', with the steps Python found so far, and the worker is kept for the next request", async () => {
    const h = harness();
    const seen = [];
    const result = await h.client.runScenario(farm(C0, { steps: 8 }), {
      onStep: (step) => {
        seen.push(step);
        if (step.index === 1) h.client.stop();
      },
    });
    expect(seen.map((step) => step.index)).toEqual([0, 1]);
    expect(pick(seen[1], STEP)).toEqual(C0.farmPath.path[0]);
    expect(result).toMatchObject({ mode: "farm-path", stopped: "stopped", steps: 1 });
    const next = await h.client.runScenario(equip(C1));
    expect(pick(next, ANSWER)).toEqual(pick(C1.equipNow, ANSWER));
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].terminated).toBe(false);
  });

  it("cancel() with a weighted request in flight rejects it, drops the worker and starts a new one for the next request, which is answered for its own weights", async () => {
    const h = harness();
    let cancelled = null;
    const running = h.client.runScenario(farm(C0, { steps: 8 }), {
      onStep: (step) => {
        if (step.index === 1) {
          cancelled = step;
          h.client.cancel();
        }
      },
    });
    await expect(running).rejects.toMatchObject({ code: "cancelled" });
    expect(cancelled).not.toBeNull();
    expect(h.workers[0].terminated).toBe(true);
    const next = await h.client.runScenario(equip(C1));
    expect(pick(next, ANSWER)).toEqual(pick(C1.equipNow, ANSWER));
    expect(h.workers).toHaveLength(2);
    expect(h.client.stats()).toMatchObject({ spawns: 2 });
  });

  it("works out a request that replaces another for its own weights: the answer of the first is nowhere in it", async () => {
    const h = harness();
    const first = h.client.runScenario(equip(C0));
    const second = h.client.runScenario(equip(C0, { weights: C1.weights })); // the weights of another case, for this scenario
    const third = h.client.runScenario(equip(C0));
    const [a, b, c] = await Promise.all([first, second, third]);
    expect(pick(a, ANSWER)).toEqual(pick(C0.equipNow, ANSWER));
    expect(b.F).not.toBe(a.F);
    expect(pick(c, ANSWER)).toEqual(pick(a, ANSWER));
    expect(h.workers).toHaveLength(1);
  });
});
