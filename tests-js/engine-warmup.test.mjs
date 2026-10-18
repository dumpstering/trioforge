import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { parseManifest } from "../pipeline/trioforge/site/static/engine/manifest.js";
import { validateRequest } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { EngineFault, createWorkerCore, loadHighsEngine, solveModelWith, warmUp, warmUpModel } from "../pipeline/trioforge/site/static/engine/worker.js";

// The warm-up: right after HiGHS starts and before the worker says it is ready, it solves one small built-in program with integer columns that needs branching, so
// that the code of the solver's branch and bound is compiled before the first real request (the phone gate found about four seconds of lazy compilation on the
// first real solve otherwise). A warm-up that fails is a start that failed: engine-load. "highs" is replaced here by the real solver with a spy on its models,
// to see what is done and when.

const hooks = vi.hoisted(() => ({ events: [], before: () => {}, outcome: null, solution: null }));
vi.mock("highs", async (importOriginal) => {
  const original = await importOriginal();
  const { spyOn } = await import("./engine-spy.mjs");
  return {
    ...original,
    default: async (...args) => {
      const real = await original.default(...args);
      hooks.events.push("started");
      return spyOn(real, {
        created: () => hooks.events.push("model"),
        before: (...given) => {
          hooks.events.push("run");
          hooks.before(...given);
        },
        outcome: (result, run) => (hooks.outcome === null ? result : hooks.outcome(result, run)),
        solution: (given) => (hooks.solution === null ? given : hooks.solution(given)),
      }).highs;
    },
  };
});

const HERE = dirname(fileURLToPath(import.meta.url));
const wasmBytes = readFileSync(resolve(HERE, "../node_modules/highs/build/highs.wasm"));
const ORIGIN = "https://trioforge.test";
const WASM_PATH = "/assets/engine/highs-0123456789ABCDEF.wasm";
const BASE = `${ORIGIN}/assets/engine/worker-BBBBBBBB.js`;
const MANIFEST = parseManifest({
  version: 2,
  highs: "1.15.3",
  data_release: "data-2026-10-14",
  rules_version: "2026-10-13",
  client: { path: "/assets/engine/client-AAAAAAAA.js", bytes: 9000, gzip: 3000 },
  worker: { path: "/assets/engine/worker-BBBBBBBB.js", bytes: 120000, gzip: 40000 },
  wasm: { path: WASM_PATH, bytes: wasmBytes.length, gzip: 1200000, sha256: createHash("sha256").update(wasmBytes).digest("hex") },
  items: { path: "/assets/engine/data/items-1111111111111111.json", bytes: 1900000, gzip: 5000, sha256: "1".repeat(64) },
  trios: { "pal-mnk-ber": [50] },
});
const fetchImpl = async (url) => {
  if (String(url) !== `${ORIGIN}${WASM_PATH}`) return new Response("not found", { status: 404 });
  return new Response(wasmBytes, { status: 200, headers: { "content-type": "application/wasm" } });
};
const load = () => loadHighsEngine({ manifest: MANIFEST, fetchImpl, baseUrl: BASE, onProgress() {} });
const coreOf = (posted) => createWorkerCore({ post: (message) => posted.push(message), loadManifest: async () => MANIFEST, loadEngine: (args) => loadHighsEngine({ ...args, fetchImpl, baseUrl: BASE }) });

beforeEach(() => {
  hooks.events.length = 0;
  hooks.before = () => {};
  hooks.outcome = null;
  hooks.solution = null;
});

describe("the warm-up model", () => {
  let highs;
  beforeAll(async () => {
    highs = await loadHighs();
  });

  it("is a small program with integer columns that the solver has to branch on, and it has an answer that is known", () => {
    const model = warmUpModel();
    expect(model.c.length).toBeGreaterThanOrEqual(20);
    expect(model.c.length).toBeLessThanOrEqual(80);
    expect(model.integrality.every((flag) => flag === 1)).toBe(true);
    expect(model.row_lb.length).toBeGreaterThanOrEqual(3);
    const out = solveModelWith(highs, model, { budgetMs: 60_000, startedAt: performance.now() });
    expect(out.status).toBe("optimal");
    expect(out.nodes, "the solver had to branch").toBeGreaterThan(1);
    expect(out.objective).toBeCloseTo(1527, 6);
  });

  it("is a model the protocol takes (a complete model JSON v1), and the same one every time: nothing in it is chosen at random or by the clock", () => {
    expect(() => validateRequest({ v: 1, kind: "model", model: warmUpModel(), budgetMs: 5000 })).not.toThrow();
    expect(JSON.stringify(warmUpModel())).toBe(JSON.stringify(warmUpModel()));
  });

  it("is solved by warmUp(highs), which says how long it took", () => {
    const ms = warmUp(highs);
    expect(typeof ms).toBe("number");
    expect(ms).toBeGreaterThanOrEqual(0);
  });
});

describe("when the worker warms up", () => {
  it("solves it right after the solver starts and before loadHighsEngine gives the engine back", async () => {
    const engine = await load();
    expect(hooks.events).toEqual(["started", "model", "run"]); // one model, one run, and no request has been made
    expect(engine.warmUpMs).toBeGreaterThan(0);
  });

  it("is over before the worker says ready: the order of a start is solver, warm-up, ready", async () => {
    const posted = [];
    const core = createWorkerCore({
      post: (message) => {
        if (message.type === "ready") hooks.events.push("ready");
        posted.push(message);
      },
      loadManifest: async () => MANIFEST,
      loadEngine: (args) => loadHighsEngine({ ...args, fetchImpl, baseUrl: BASE }),
    });
    await core.handle({ v: 1, type: "init" });
    expect(hooks.events).toEqual(["started", "model", "run", "ready"]);
    expect(posted.map((message) => message.type)).toContain("ready");
    // and it is not done again for a request: the model of the first request is the second the solver has made
    await core.handle({ v: 1, type: "solve", id: 1, request: { v: 1, kind: "model", budgetMs: 5000, model: warmUpModel() } });
    expect(hooks.events.filter((event) => event === "model")).toHaveLength(2);
    expect(posted.at(-1)).toMatchObject({ type: "result", id: 1, kind: "model", status: "optimal" });
  });

  it("is a failed start when the warm-up cannot be solved: engine-load, no ready, and no request is taken afterwards", async () => {
    hooks.before = () => {
      throw new Error("the solver fell over");
    };
    const failure = await load().catch((error) => error);
    expect(failure).toBeInstanceOf(EngineFault);
    expect(failure).toMatchObject({ code: "engine-load" });

    const posted = [];
    const core = coreOf(posted);
    await core.handle({ v: 1, type: "init" });
    expect(posted.map((message) => message.type)).not.toContain("ready");
    expect(posted.at(-1)).toMatchObject({ type: "error", code: "engine-load" });
    expect(posted.at(-1).id).toBeUndefined();
    await core.handle({ v: 1, type: "solve", id: 2, request: { v: 1, kind: "model", budgetMs: 5000, model: warmUpModel() } });
    expect(posted.at(-1)).toMatchObject({ type: "error", code: "not-ready", id: 2 });
  });

  it("is a failed start when the warm-up ends without proving its answer", async () => {
    const states = (await loadHighs()).constants.modelStatus;
    hooks.outcome = (result) => ({ ...result, modelStatus: states.timeLimit });
    await expect(load()).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(/check run/i) });
  });

  it("is a failed start when the warm-up gives another answer than the known one: a solver that does not do what it should is not used", async () => {
    hooks.solution = (given) => ({ ...given, colValue: given.colValue.map(() => 0) });
    await expect(load()).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(/wrong answer/i) });
  });
});
