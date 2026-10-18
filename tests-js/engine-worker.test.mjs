// The solver worker and its main-thread client: the message protocol (checked against a fake engine and against the real
// HiGHS), the manifest, the Trusted Types policy, the consent flow (in jsdom, declining included) and the watchdog.
//
// The environment is Node. The consent tests build their own jsdom pages, so the real HiGHS (which looks at the global
// object to decide where it runs) is not disturbed by a jsdom global. The browser side of all this is tests-e2e/engine.spec.mjs.

import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { JSDOM } from "jsdom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OPTIONS as BENCH_OPTIONS } from "../scripts/bench-highs.mjs";
import { EngineError, createEngineClient, environmentWarnings, forgetEngineClient, getEngineClient } from "../pipeline/trioforge/site/static/engine/client.js";
import { ManifestError, downloadMegabytes, fetchTextWithin, parseManifest } from "../pipeline/trioforge/site/static/engine/manifest.js";
import {
  LABEL_NO_INCUMBENT,
  LABEL_TIME_LIMIT,
  LIMITS,
  LIVENESS_TIMEOUT_MS,
  STARTUP_COMPILE_MS,
  STARTUP_STALL_MS,
  WATCHDOG_GRACE_MS,
  isUrlLike,
  validateFromWorker,
  validateRequest,
  validateToWorker,
} from "../pipeline/trioforge/site/static/engine/protocol.js";
import { EngineFault, SOLVER_OPTIONS, createWorkerCore, describe as describeError, loadHighsEngine, readManifest, solveModelWith } from "../pipeline/trioforge/site/static/engine/worker.js";
import { POLICY_NAME, getAssetPolicy } from "../pipeline/trioforge/site/static/tt-policy.js";
import { canonical, check, handMilp, handOptimum, infeasibleMilp, knapsackMilp, lpMilp } from "./engine-models.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC = resolve(HERE, "../pipeline/trioforge/site/static");
const WASM_FILE = resolve(HERE, "../node_modules/highs/build/highs.wasm");

// ---- fixtures ----------------------------------------------------------------------------------------------------------------

const WORKER_PATH = "/assets/engine/worker-BBBBBBBB.js";
const WASM_PATH = "/assets/engine/highs-0123456789ABCDEF.wasm";
// (the digest the manifest holds for the fake WebAssembly of the tests that do not download one: the real tests use the real file's)
const WASM_SHA = "0123456789abcdef" + "f".repeat(48);
// (the data files the worker reads for a visitor's own gear: tested in engine-manifest-data.test.mjs and engine-scenario*.test.mjs; here, made-up entries)
const dataFile = (path, digit, bytes = 20000) => ({ path, bytes, gzip: 5000, sha256: digit.repeat(64) });
const MANIFEST_JSON = Object.freeze({
  version: 2,
  highs: "1.15.3",
  data_release: "data-2026-10-14",
  rules_version: "2026-10-13",
  client: { path: "/assets/engine/client-AAAAAAAA.js", bytes: 9000, gzip: 3000 },
  worker: { path: WORKER_PATH, bytes: 120000, gzip: 40000 },
  wasm: { path: WASM_PATH, bytes: 3531385, gzip: 1200000, sha256: WASM_SHA },
  items: dataFile("/assets/engine/data/items-1111111111111111.json", "1", 1900000),
  trios: { "pal-mnk-ber": [50], "pal-shd-ber": [50, 55] },
});
const MANIFEST = parseManifest(MANIFEST_JSON);
// (the gzip sizes of the worker and the WebAssembly, 40,000 + 1,200,000 bytes, rounded up to a tenth of a million bytes: what is downloaded)
const MEGABYTES = "1.3";

const EMPTY_MODULE_BYTES = Uint8Array.of(0, 97, 115, 109, 1, 0, 0, 0);
const modelRequest = (over = {}) => ({ v: 1, kind: "model", model: handMilp(), budgetMs: 5000, ...over });
const scenarioRequest = (over = {}) => ({
  v: 1,
  kind: "scenario",
  trio: "pal-mnk-ber",
  level: 50,
  scenario: { race: "OGR", role: "balanced", buffs: "own", evidence: "wiki", setup: "dw" },
  owned: [["w1234@4", 1]],
  mode: "equip-now",
  budgetMs: 5000,
  ...over,
});

/** Resolve after the promise chains that are already waiting have run (no timers: it works under fake timers). */
async function tick(rounds = 40) {
  for (let i = 0; i < rounds; i += 1) await Promise.resolve();
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

// ---- a worker made of the real worker core, in this thread ------------------------------------------------------------------

/** What postMessage does to a message: a structured clone, except that a compiled WebAssembly module is shared, not copied. */
function cloneMessage(data) {
  if (data === null || typeof data !== "object" || !("module" in data)) return structuredClone(data);
  const { module, ...rest } = data;
  return { ...structuredClone(rest), module };
}

class FakeWorker {
  constructor(url, { core, script }) {
    this.url = url;
    this.core = core;
    this.script = script;
    this.terminated = false;
    this.dead = false; // died without a word (see die())
    this.sent = []; // what the page posted to this worker
    this.delivered = []; // what this worker posted back
    this.onmessage = null;
    this.onerror = null;
    this.onmessageerror = null;
    this.firstHandler = null; // the page's message handler as it was when the page first spoke to this worker
    if (core) core.attach((message) => this.reply(message));
  }

  reply(message) {
    this.delivered.push(message);
    queueMicrotask(() => {
      if (!this.terminated && !this.dead) this.onmessage?.({ data: cloneMessage(message) });
    });
  }

  postMessage(data) {
    if (this.terminated) return;
    const copy = cloneMessage(data);
    this.firstHandler ??= this.onmessage;
    this.sent.push(copy);
    queueMicrotask(() => {
      if (this.terminated || this.dead) return; // a worker that died takes what it is sent and says nothing
      if (this.script) this.script(copy, (m) => this.reply(m));
      else this.core.handle(copy);
    });
  }

  terminate() {
    this.terminated = true;
  }

  /** The worker stops the way `self.close()` or the browser stops it: no message, and no error event. */
  die() {
    this.dead = true;
  }

  crash(message = "boom") {
    this.onerror?.({ message, preventDefault() {} });
  }
}

/** The pieces of an engine the worker core needs, with a behaviour a test can change. */
function fakeEngine(state = {}) {
  const calls = [];
  return {
    state,
    calls,
    async load({ manifest, module, onProgress }) {
      calls.push({ type: "load", hadModule: module !== undefined });
      if (module !== undefined && state.failWithModule) throw new Error(state.failWithModule);
      onProgress({ phase: "loading", loaded: 50, total: 100 });
      onProgress({ phase: "compiling" });
      return {
        version: "1.15.1",
        module: module === undefined ? new WebAssembly.Module(EMPTY_MODULE_BYTES) : undefined,
        wasm: module === undefined ? (state.wasm ?? manifest.wasm.sha256) : undefined, // the digest of the file it loaded: only a worker that downloaded one has any
        async solveModel(model, { budgetMs, onProgress: report }) {
          calls.push({ type: "solve", columns: model.c.length, budgetMs });
          report({ phase: "building" });
          report({ phase: "solving", elapsedMs: 5, objective: 30 });
          // a worker that goes on reporting: `beat.times` more reports, one every `beat.every` milliseconds
          for (let n = 1; state.beat !== undefined && n <= state.beat.times; n += 1) {
            await new Promise((resolve) => setTimeout(resolve, state.beat.every));
            report({ phase: "solving", elapsedMs: n * state.beat.every });
          }
          if (state.hang) return new Promise(() => {});
          if (state.fault) throw new EngineFault(state.fault, "the engine says no");
          if (state.throws) throw new Error(state.throws);
          return (
            state.result ?? {
              status: "optimal",
              proven: true,
              objective: 37,
              x: new Array(model.c.length).fill(0),
              bound: 37,
              gap: 0,
              nodes: 3,
              label: null,
            }
          );
        },
      };
    },
  };
}

/** A worker core whose posts go to whoever attaches (the fake worker), loading its engine from `engine.load`. */
function makeCore(engine, now = () => 0, manifest = MANIFEST) {
  let sink = () => {};
  const core = createWorkerCore({
    post: (message) => sink(message),
    loadManifest: async () => manifest,
    loadEngine: (args) => engine.load(args),
    now,
  });
  core.attach = (fn) => {
    sink = fn;
  };
  return core;
}

/** A client wired to fake workers, an in-memory page and a fake manifest fetch. */
function makeHarness(options = {}) {
  const {
    engine = fakeEngine(),
    script,
    scripts,
    consent = { ask: async () => true }, // null: use the question the client puts on the page
    manifest = MANIFEST_JSON,
    trustedTypes,
    navigator,
    storage,
    markup = '<!doctype html><html><body><main id="main"></main></body></html>',
    now,
    createWorker,
    workerManifest = MANIFEST, // the manifest the worker reads for itself (the page's is `manifest`); a function of the number of workers made so far to change it from one worker to the next
    reload, // what the Reload button of the notice that the optimizer was updated does
  } = options;
  const dom = new JSDOM(markup, { url: "https://trioforge.test/trio/pal-mnk-ber/" });
  const workers = [];
  const fetchCalls = [];
  const fetchImpl = async (url) => {
    fetchCalls.push(String(url));
    if (String(url) !== "/engine-manifest.json") return { ok: false, status: 404, text: async () => "not found" };
    return { ok: true, status: 200, text: async () => (typeof manifest === "string" ? manifest : JSON.stringify(manifest)) };
  };
  const scriptFor = (index) => (scripts ? scripts[Math.min(index, scripts.length - 1)] : script);
  const spawn =
    createWorker ??
    ((url) => {
      const chosen = scriptFor(workers.length);
      const worker = new FakeWorker(url, {
        core: chosen ? null : makeCore(engine, now, typeof workerManifest === "function" ? workerManifest(workers.length) : workerManifest),
        script: chosen,
      });
      workers.push(worker);
      return worker;
    });
  const client = createEngineClient({
    window: dom.window,
    document: dom.window.document,
    fetch: fetchImpl,
    createWorker: spawn,
    ...(consent === null ? {} : { consent }),
    ...(trustedTypes === undefined ? {} : { trustedTypes }),
    ...(navigator === undefined ? {} : { navigator }),
    ...(storage === undefined ? {} : { storage }),
    ...(reload === undefined ? {} : { reload }),
  });
  return { client, engine, workers, fetchCalls, dom, document: dom.window.document };
}

afterEach(() => {
  vi.useRealTimers();
});

// ---- the manifest ------------------------------------------------------------------------------------------------------------

describe("the manifest", () => {
  it("is read into numbers, paths and a map of trios", () => {
    expect(MANIFEST.version).toBe(2);
    expect(MANIFEST.worker).toEqual({ path: WORKER_PATH, bytes: 120000, gzip: 40000 });
    expect(MANIFEST.wasm.path).toBe(WASM_PATH);
    expect(MANIFEST.trios).toBeInstanceOf(Map);
    expect(MANIFEST.trios.get("pal-shd-ber").levels).toEqual([50, 55]);
    expect(MANIFEST.trios.get("constructor")).toBeUndefined(); // a map: names from the object chain are not trios
  });

  it("says how many megabytes the optimizer is to download, rounded up to a tenth, from the gzip sizes of the worker and the WebAssembly", () => {
    expect(downloadMegabytes(MANIFEST)).toBe(Number(MEGABYTES));
    const exact = parseManifest({ ...MANIFEST_JSON, worker: { ...MANIFEST_JSON.worker, gzip: 100000 }, wasm: { ...MANIFEST_JSON.wasm, gzip: 3500000 } });
    expect(downloadMegabytes(exact)).toBe(3.6);
    // the sizes the files have once unpacked are not what is downloaded, so they do not count (3.7 MB raw, 1.3 MB on the wire)
    const bigger = parseManifest({ ...MANIFEST_JSON, worker: { ...MANIFEST_JSON.worker, bytes: 9_000_000 }, wasm: { ...MANIFEST_JSON.wasm, bytes: 30_000_000 } });
    expect(downloadMegabytes(bigger)).toBe(Number(MEGABYTES));
    expect(MANIFEST.worker.bytes + MANIFEST.wasm.bytes).toBeGreaterThan(3_500_000);
  });

  const BAD = {
    "not an object": [null, [], "text", 5],
    "another version": [{ ...MANIFEST_JSON, version: 1 }, { ...MANIFEST_JSON, version: 3 }],
    "no worker": [{ ...MANIFEST_JSON, worker: undefined }],
    "an unknown key": [{ ...MANIFEST_JSON, extra: 1 }],
    "a worker path that is not hashed": [{ ...MANIFEST_JSON, worker: { ...MANIFEST_JSON.worker, path: "/assets/engine/worker.js" } }],
    "a worker path with a query": [{ ...MANIFEST_JSON, worker: { ...MANIFEST_JSON.worker, path: `${WORKER_PATH}?x=1` } }],
    "a worker address on another site": [{ ...MANIFEST_JSON, worker: { ...MANIFEST_JSON.worker, path: `https://evil.example${WORKER_PATH}` } }],
    "a protocol-relative worker address": [{ ...MANIFEST_JSON, worker: { ...MANIFEST_JSON.worker, path: `//evil.example${WORKER_PATH}` } }],
    "a worker path that climbs": [{ ...MANIFEST_JSON, worker: { ...MANIFEST_JSON.worker, path: "/assets/engine/../worker-BBBBBBBB.js" } }],
    "a wasm file named .js": [{ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, path: "/assets/engine/highs-0123456789ABCDEF.js" } }],
    "a worker file named .wasm": [{ ...MANIFEST_JSON, worker: { ...MANIFEST_JSON.worker, path: "/assets/engine/worker-BBBBBBBB.wasm" } }],
    "a path outside assets/engine": [{ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, path: "/data/highs-0123456789ABCDEF.wasm" } }],
    "a negative size": [{ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, bytes: -1 } }],
    "a size that is not whole": [{ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, bytes: 3.5 } }],
    "a size in text": [{ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, bytes: "3531385" } }],
    "a trio code that is not a trio": [{ ...MANIFEST_JSON, trios: { "../x": [50] } }],
    "a trio with no levels": [{ ...MANIFEST_JSON, trios: { "pal-mnk-ber": [] } }],
    "a level that is not whole": [{ ...MANIFEST_JSON, trios: { "pal-mnk-ber": [50.5] } }],
    "a pinned version that is not a version": [{ ...MANIFEST_JSON, highs: "latest" }],
    "a WebAssembly with no checksum": [{ ...MANIFEST_JSON, wasm: { path: WASM_PATH, bytes: 3531385, gzip: 1200000 } }],
    "a checksum in capitals": [{ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, sha256: WASM_SHA.toUpperCase() } }],
    "a checksum that is too short": [{ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, sha256: WASM_SHA.slice(1) } }],
    "a checksum that is too long": [{ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, sha256: `${WASM_SHA}0` } }],
    "a checksum that is not hexadecimal": [{ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, sha256: `g${WASM_SHA.slice(1)}` } }],
    "a checksum that is a number": [{ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, sha256: 123 } }],
    "a checksum of the worker": [{ ...MANIFEST_JSON, worker: { ...MANIFEST_JSON.worker, sha256: WASM_SHA } }],
  };
  for (const [name, values] of Object.entries(BAD)) {
    it(`refuses ${name}`, () => {
      for (const value of values) expect(() => parseManifest(value)).toThrow(ManifestError);
    });
  }
});

// ---- requests ----------------------------------------------------------------------------------------------------------------

describe("validating a request", () => {
  it("accepts a model request and returns a detached copy", () => {
    const original = modelRequest();
    const clean = validateRequest(original);
    expect(clean).toEqual(original);
    expect(clean).not.toBe(original);
    expect(clean.model.A.index).not.toBe(original.model.A.index);
    original.model.c[0] = 12345;
    original.model.A.value.push(1);
    expect(clean.model.c[0]).toBe(9); // what was checked is what is sent, whatever the caller does afterwards
  });

  it("refuses yes/no flags in the integrality list: model JSON v1 has the numbers 0 and 1, and the Python reader refuses true and false", () => {
    for (const flag of [true, false]) {
      const model = handMilp();
      model.integrality[0] = flag;
      expect(() => validateRequest(modelRequest({ model }))).toThrow(/bad-request/);
    }
  });

  it("takes a model as the exporter writes it, with its item columns, its buff columns and its info, and hands the worker all of it", () => {
    const model = handMilp();
    model.item_cols = [[0, "HEAD", "w1", 4], [2, "NECK", "w2", 0]];
    model.buff_cols = [[7, 100], [3, -1]];
    model.info = { cols: 9, rows: 4, pools: { HP: "fixed" }, binaries: { buff: 2 } };
    const clean = validateRequest(modelRequest({ model })).model;
    expect(clean).toEqual(model);
    expect(clean.item_cols).not.toBe(model.item_cols);
    model.item_cols[0][1] = "CHEST";
    expect(clean.item_cols[0][1]).toBe("HEAD"); // a detached copy, as for every other field
    expect(validateToWorker({ v: 1, type: "solve", id: 2, request: modelRequest({ model: clean }) }).request.model).toEqual(clean);
  });

  it("refuses an integer column with a bound that is not a whole number, and does not round it; any other column may have one", () => {
    const integer = 3; // a yes/no column of the hand model
    for (const [key, value] of [["col_lb", 0.5], ["col_ub", 2.5], ["col_lb", -0.1], ["col_ub", 1e-9], ["col_ub", 1.9999999999]]) {
      const model = handMilp();
      if (key === "col_ub") model.col_lb[integer] = -5;
      else model.col_ub[integer] = 7;
      model[key][integer] = value;
      expect(() => validateRequest(modelRequest({ model })), `${key} ${value}`).toThrow(/bad-request.*integer column 3.*whole number/);
    }
    for (const [key, value] of [["col_lb", -3], ["col_ub", 7], ["col_ub", 1e15], ["col_ub", null], ["col_lb", null]]) {
      const model = handMilp();
      model[key][integer] = value;
      expect(() => validateRequest(modelRequest({ model })), `${key} ${value}`).not.toThrow();
    }
    const continuous = handMilp();
    continuous.col_lb[8] = 0.125; // y, the one column that is not an integer column
    continuous.col_ub[8] = 2.5;
    expect(validateRequest(modelRequest({ model: continuous })).model.col_ub[8]).toBe(2.5);
  });

  it("accepts a scenario request of the mode Equip now: a scenario and an owned list of idents (the other modes are in engine-scenario-modes-protocol.test.mjs)", () => {
    const clean = validateRequest(scenarioRequest());
    expect(clean.trio).toBe("pal-mnk-ber");
    expect(clean.owned).toEqual([["w1234@4", 1]]);
  });

  const URL_FIELDS = {
    url: "https://evil.example/engine.wasm",
    wasmUrl: "/assets/engine/highs.wasm",
    workerUrl: "blob:https://trioforge.test/1234",
    href: "//evil.example/x",
    src: "data:text/javascript,1",
    script: "alert(1)",
    importScripts: ["https://evil.example/x.js"],
    manifest: { wasm: { path: "/x" } },
  };
  for (const [key, value] of Object.entries(URL_FIELDS)) {
    it(`refuses a model request with the field ${key}`, () => {
      expect(() => validateRequest({ ...modelRequest(), [key]: value })).toThrow(/bad-request|not allowed|unknown/i);
    });
    it(`refuses a scenario request with the field ${key}`, () => {
      expect(() => validateRequest({ ...scenarioRequest(), [key]: value })).toThrow(/bad-request|not allowed|unknown/i);
    });
  }

  const URL_TEXT = [
    "https://evil.example/x",
    "http://evil.example",
    "//evil.example/x",
    "\\\\evil.example\\x",
    "/assets/engine/highs-0123456789ABCDEF.wasm",
    "../secret.json",
    "./x.js",
    "javascript:alert(1)",
    "  javascript:alert(1)",
    "java\tscript:alert(1)",
    "data:text/html,<b>x</b>",
    "blob:https://trioforge.test/1",
    "file:///etc/passwd",
    "wss://evil.example",
    "a/../../b",
    "x://y",
  ];
  for (const text of URL_TEXT) {
    it(`sees an address in ${JSON.stringify(text)}`, () => {
      expect(isUrlLike(text)).toBe(true);
    });
  }
  for (const text of ["pal-mnk-ber", "n[HEAD|w123@4]", "cap.AC", "balanced", "Rusty Dagger +4", "x[0]", "", "50"]) {
    it(`does not see an address in ${JSON.stringify(text)}`, () => {
      expect(isUrlLike(text)).toBe(false);
    });
  }

  describe("a request that is a valid Equip now request but for one thing that names an address", () => {
    // Each case is the request of scenarioRequest(), which the first test shows to be valid, with ONE thing added or changed; the detail of the refusal is the one of the
    // allowlist or the check that the thing meets, so that the case is refused for the reason it is a case of and not for a field that is missing.
    const refused = (request, detail) => expect(() => validateRequest(request)).toThrow(new RegExp(`^bad-request: .*${detail}`));

    it("is accepted when nothing is added: the base of the cases that follow", () => {
      const clean = validateRequest(scenarioRequest());
      expect(clean).toMatchObject({ kind: "scenario", mode: "equip-now", trio: "pal-mnk-ber", level: 50 });
      expect(Object.keys(clean.scenario)).toEqual(["race", "role", "buffs", "evidence", "setup"]);
    });

    it("has a field of the request, named like an address, that is not allowed: the detail says which", () => {
      for (const key of ["url", "URL", "wasmUrl", "baseURL", "base_url", "workerUrl", "worker-path", "workerurl", "href", "src", "link", "Links", "importScripts", "script", "endpoint", "origin", "host", "wasm", "worker", "myUri", "candidates"]) {
        refused({ ...scenarioRequest(), [key]: "/assets/engine/highs-0123456789ABCDEF.wasm" }, `a field that is not allowed \\(${key.replace(/[-]/g, "\\-")}\\)`);
      }
    });

    it("has a field of the scenario that is not one of its six, whatever it is called: the detail says so", () => {
      const scenario = scenarioRequest().scenario;
      for (const key of ["url", "URL", "wasmUrl", "baseURL", "base_url", "workerUrl", "worker-path", "workerurl", "href", "src", "link", "Links", "importScripts", "script", "endpoint", "origin", "host", "wasm", "worker", "myUri"]) {
        refused(scenarioRequest({ scenario: { ...scenario, [key]: 1 } }), "the scenario has a field that is not allowed");
      }
      for (const key of ["description", "original", "ghost", "source", "tier", "haste_assumed", "weights", "regenT"]) {
        refused(scenarioRequest({ scenario: { ...scenario, [key]: 1 } }), "the scenario has a field that is not allowed");
      }
      refused(scenarioRequest({ scenario: { ...scenario, nested: { deeper: ["/assets/x.js"] } } }), "the scenario has a field that is not allowed");
    });

    it("has an address for a value that is a name: a choice of the scenario, the mode, an ident of the owned set", () => {
      const scenario = scenarioRequest().scenario;
      for (const field of ["race", "role", "buffs", "evidence", "setup"]) refused(scenarioRequest({ scenario: { ...scenario, [field]: "//evil.example" } }), "must be a short name");
      refused(scenarioRequest({ scenario: { ...scenario, deity: "https://evil.example" } }), "must be a short name");
      refused(scenarioRequest({ mode: "https://evil.example" }), "names no mode");
      refused(scenarioRequest({ owned: [["/assets/x.js", 1]] }), "does not name an item by an ident");
      refused(scenarioRequest({ trio: "https://evil.example" }), "names no trio");
    });

    it("has data that is not the plain data of a list, an object or a name in the place of one", () => {
      refused(scenarioRequest({ owned: [{ url: "x" }] }), "an owned entry must be a list");
      refused(scenarioRequest({ owned: { url: "x" } }), "the owned set must be a list");
      refused(scenarioRequest({ scenario: [{ wasmUrl: "x" }] }), "the scenario");
    });
  });

  describe("the labels of a model (names, the group and key of an item column, the keys and texts of the info) are any text, as in milp_json.py", () => {
    const LABELS = {
      "a slash": "a/b",
      "an address": "https://evil.example/x",
      "a scheme": "slot:head",
      "a backslash": "c\\d",
      "a control character": "x\u0000y",
      "a line separator": "line\u2028sep",
      "161 characters": "x".repeat(161),
      "3000 characters": "x".repeat(3000),
      "the name of a key of an object": "__proto__",
      "text from many scripts": "na\u00efve \u4e2d\u6587 \u{1F600}",
    };
    for (const [name, label] of Object.entries(LABELS)) {
      it(`takes ${name} as a name of a column and of a row, as the group and key of an item column, and in the info`, () => {
        const model = handMilp();
        model.col_names[2] = label;
        model.row_names[1] = label;
        model.item_cols = [[0, label, label, 4]];
        model.info = { [`k ${name}`]: label, nested: [{ text: label }] };
        const clean = validateRequest(modelRequest({ model })).model;
        expect(clean).toEqual(model);
        expect(validateToWorker({ v: 1, type: "solve", id: 1, request: modelRequest({ model: clean }) }).request.model).toEqual(clean);
      });
    }

    it("takes the info keys that the old rules read as addresses or odd, such as worker_count, PAL MNK, a slash, an empty key and a long key", () => {
      for (const key of ["worker_count", "PAL MNK", "a/b", "", "x".repeat(60), "url", "wasm", "worker", "src", "slot:x", "\u00e9t\u00e9"]) {
        const model = handMilp();
        model.info = { [key]: 1, deeper: { [key]: [key] } };
        expect(validateRequest(modelRequest({ model })).model.info, JSON.stringify(key)).toEqual(model.info);
      }
      const model = handMilp();
      model.info = { trio: "PAL/MNK/BER", cols: 9, rows: 4 };
      expect(validateRequest(modelRequest({ model })).model.info).toEqual(model.info);
    });

    it("still refuses a name that is not text, or empty, or used twice", () => {
      for (const change of [(m) => (m.col_names[0] = 5), (m) => (m.row_names[0] = null), (m) => (m.col_names[0] = ""), (m) => (m.row_names[1] = m.row_names[0]), (m) => (m.item_cols = [[0, 5, "k", 1]]), (m) => (m.item_cols = [[0, "g", null, 1]])]) {
        expect(() => validateRequest(mutate(change))).toThrow(/bad-request/);
      }
    });

    it("copies the labels as they are, to the last character", () => {
      const model = handMilp();
      model.col_names[0] = "x\u0000\u2028/\\:y\ud800";
      model.info = { "k\u0001": "v\u2029" };
      const clean = validateRequest(modelRequest({ model })).model;
      expect(clean.col_names[0]).toBe(model.col_names[0]);
      expect(Object.keys(clean.info)).toEqual(["k\u0001"]);
      expect(clean.info["k\u0001"]).toBe("v\u2029");
    });
  });

  describe("the info of a model is plain data, to the depth and the size milp_json.py holds it to", () => {
    const withInfo = (info) => modelRequest({ model: { ...handMilp(), info } });
    const levels = (count) => {
      let value = 0;
      for (let i = 1; i < count; i += 1) value = [value];
      return { k: value };
    };

    it("takes 8 levels and 100,000 values, and refuses 9 levels and 100,001 values", () => {
      expect(() => validateRequest(withInfo(levels(8)))).not.toThrow();
      expect(() => validateRequest(withInfo(levels(9)))).toThrow(/bad-request.*too deeply/);
      expect(() => validateRequest(withInfo({ k: new Array(LIMITS.maxNodes - 2).fill(0) }))).not.toThrow();
      expect(() => validateRequest(withInfo({ k: new Array(LIMITS.maxNodes - 1).fill(0) }))).toThrow(/bad-request.*too large/);
    });

    it("refuses the keys that could poison a lookup, anywhere in it, and takes a key that merely contains one", () => {
      for (const key of ["__proto__", "constructor", "prototype"]) {
        expect(() => validateRequest(withInfo(JSON.parse(`{"${key}": 1}`))), key).toThrow(/bad-request/);
        expect(() => validateRequest(withInfo(JSON.parse(`{"a": [{"b": {"${key}": 1}}]}`))), key).toThrow(/bad-request/);
        expect(() => validateRequest(withInfo({ [`x${key}`]: 1 })), key).not.toThrow();
      }
      expect(Object.prototype.polluted).toBeUndefined();
    });

    it("refuses a number that is not finite, such as the Infinity that the text 1e999 is read as, and anything that is not JSON data", () => {
      expect(() => validateRequest(withInfo(JSON.parse('{"x": 1e999}')))).toThrow(/bad-request/);
      expect(() => validateRequest(withInfo({ x: Number.NaN }))).toThrow(/bad-request/);
      for (const value of [undefined, () => 1, 10n, Symbol("s"), new Date(0), new Map()]) {
        expect(() => validateRequest(withInfo({ x: value })), String(typeof value)).toThrow(/bad-request/);
      }
    });
  });

  describe("the sizes milp_json.py holds a document to", () => {
    /** A valid model of the given size with nothing in it. */
    const wide = (columns, rows = 0) => ({
      version: 1,
      sense: "max",
      const: 0,
      col_names: Array.from({ length: columns }, (_, i) => `c${i}`),
      col_lb: new Array(columns).fill(null),
      col_ub: new Array(columns).fill(null),
      integrality: new Array(columns).fill(0),
      c: new Array(columns).fill(0),
      row_names: Array.from({ length: rows }, (_, i) => `r${i}`),
      row_lb: new Array(rows).fill(null),
      row_ub: new Array(rows).fill(null),
      A: { start: new Array(rows + 1).fill(0), index: [], value: [] },
      item_cols: [],
      buff_cols: [],
      info: {},
    });

    it("takes 50,000 columns and 50,000 rows, and refuses one more of either", () => {
      expect([LIMITS.maxColumns, LIMITS.maxRows, LIMITS.maxNonzeros]).toEqual([50_000, 50_000, 1_000_000]);
      expect(() => validateRequest(modelRequest({ model: wide(LIMITS.maxColumns) }))).not.toThrow();
      expect(() => validateRequest(modelRequest({ model: wide(LIMITS.maxColumns + 1) }))).toThrow(/bad-request/);
      expect(() => validateRequest(modelRequest({ model: wide(0, LIMITS.maxRows) }))).not.toThrow();
      expect(() => validateRequest(modelRequest({ model: wide(0, LIMITS.maxRows + 1) }))).toThrow(/bad-request/);
    });

    it("takes a million entries of the matrix, and refuses one more", () => {
      const columns = 1000;
      const rows = 1000;
      const model = wide(columns, rows);
      model.A = {
        start: Array.from({ length: rows + 1 }, (_, r) => r * columns),
        index: Array.from({ length: columns * rows }, (_, k) => k % columns),
        value: new Array(columns * rows).fill(1),
      };
      expect(() => validateRequest(modelRequest({ model }))).not.toThrow();
      model.row_names.push("one more");
      model.row_lb.push(null);
      model.row_ub.push(null);
      model.A.start.push(model.A.start.at(-1) + 1);
      model.A.index.push(0);
      model.A.value.push(1);
      expect(() => validateRequest(modelRequest({ model }))).toThrow(/bad-request/);
    }, 30_000);
  });

  describe("a buff id is a whole number that a double holds exactly", () => {
    const withIds = (...ids) => modelRequest({ model: { ...handMilp(), buff_cols: ids.map((id, column) => [column, id]) } });
    it("takes ±(2^53 - 1), and refuses 2^53, 2^60 and what is beyond", () => {
      expect(() => validateRequest(withIds(Number.MAX_SAFE_INTEGER, Number.MIN_SAFE_INTEGER, 0, -1))).not.toThrow();
      for (const id of [2 ** 53, -(2 ** 53), 2 ** 60, 1e300, JSON.parse("1" + "0".repeat(400))]) {
        expect(() => validateRequest(withIds(id)), String(id)).toThrow(/bad-request.*buff id/);
      }
    });
  });

  const NOT_REQUESTS = {
    "nothing": undefined,
    "null": null,
    "a number": 5,
    "text": "solve",
    "an array": [modelRequest()],
    "a Map": new Map(Object.entries(modelRequest())),
    "a class instance": new (class Request {
      constructor() {
        Object.assign(this, modelRequest());
      }
    })(),
    "an object with a getter": Object.defineProperty({ ...modelRequest() }, "budgetMs", { get: () => 1000, enumerable: true }),
    "no version": { ...modelRequest(), v: undefined },
    "another version": modelRequest({ v: 2 }),
    "a version in text": modelRequest({ v: "1" }),
    "no kind": { ...modelRequest(), kind: undefined },
    "an unknown kind": modelRequest({ kind: "fetch" }),
    "no budget": { ...modelRequest(), budgetMs: undefined },
    "a budget of zero": modelRequest({ budgetMs: 0 }),
    "a negative budget": modelRequest({ budgetMs: -5 }),
    "a budget that is not whole": modelRequest({ budgetMs: 100.5 }),
    "a budget in text": modelRequest({ budgetMs: "5000" }),
    "a budget that is not a number": modelRequest({ budgetMs: Number.NaN }),
    "an endless budget": modelRequest({ budgetMs: Number.POSITIVE_INFINITY }),
    "a budget over the limit": modelRequest({ budgetMs: LIMITS.maxBudgetMs + 1 }),
  };
  for (const [name, value] of Object.entries(NOT_REQUESTS)) {
    it(`refuses ${name}`, () => {
      expect(() => validateRequest(value)).toThrow(/bad-request/);
    });
  }

  const mutate = (change) => {
    const model = handMilp();
    change(model);
    return modelRequest({ model });
  };
  const BAD_MODELS = {
    "a sense that is neither max nor min": (m) => (m.sense = "maximize"),
    "a constant that is not a number": (m) => (m.const = "10"),
    "an infinite constant": (m) => (m.const = Infinity),
    "no objective": (m) => delete m.c,
    "an objective of the wrong length": (m) => m.c.pop(),
    "a NaN in the objective": (m) => (m.c[2] = Number.NaN),
    "an infinite coefficient": (m) => (m.A.value[3] = Infinity),
    "a string in the objective": (m) => (m.c[1] = "7"),
    "a column bound of the wrong length": (m) => m.col_lb.pop(),
    "an infinite column bound given as a number": (m) => (m.col_ub[0] = Infinity),
    "a lower column bound above the upper": (m) => (m.col_lb[0] = 2),
    "a lower row bound above the upper": (m) => ((m.row_lb[0] = 20), (m.row_ub[0] = 3)),
    "a row bound of the wrong length": (m) => m.row_ub.pop(),
    "an integrality flag of 2": (m) => (m.integrality[0] = 2),
    "an integrality list of the wrong length": (m) => m.integrality.pop(),
    "column names of the wrong length": (m) => m.col_names.pop(),
    "a column name that is not text": (m) => (m.col_names[0] = 5),
    "row names of the wrong length": (m) => m.row_names.pop(),
    "no matrix": (m) => delete m.A,
    "a matrix start that does not begin at 0": (m) => (m.A.start[0] = 1),
    "a matrix start of the wrong length": (m) => m.A.start.pop(),
    "a matrix start that goes down": (m) => ((m.A.start[2] = 0), (m.A.start[1] = 5)),
    "a matrix start that does not end at the entry count": (m) => (m.A.start[m.A.start.length - 1] += 1),
    "a column index out of range": (m) => (m.A.index[0] = 99),
    "a negative column index": (m) => (m.A.index[0] = -1),
    "a column index that is not whole": (m) => (m.A.index[0] = 0.5),
    "the same column twice in a row": (m) => (m.A.index[1] = m.A.index[0]),
    "values of another length than the indices": (m) => m.A.value.pop(),
    "an unknown model field": (m) => (m.extra = 1),
    "another model version": (m) => (m.version = 2),
    "no model version": (m) => delete m.version,
    "no column names": (m) => delete m.col_names,
    "no item columns": (m) => delete m.item_cols,
    "no info": (m) => delete m.info,
    "a column name used twice": (m) => (m.col_names[1] = m.col_names[0]),
    "an empty row name": (m) => (m.row_names[0] = ""),
    "column indices of a row that do not rise": (m) => ([m.A.index[0], m.A.index[1]] = [m.A.index[1], m.A.index[0]]),
    "an item column that does not exist": (m) => (m.item_cols = [[99, "HEAD", "w1", 4]]),
    "an item column with a tier of 11": (m) => (m.item_cols = [[0, "HEAD", "w1", 11]]),
    "a buff column named twice": (m) => (m.buff_cols = [[7, 100], [7, 101]]),
    "an info that is not an object": (m) => (m.info = []),
    "an info with a key that could poison a lookup": (m) => (m.info = JSON.parse('{"__proto__": 1}')),
    "typed arrays in place of lists": (m) => (m.c = Float64Array.from(m.c)),
    "a sparse list": (m) => (m.c = Object.assign([], { length: m.col_lb.length })),
    "more columns than the limit": (m) => {
      const n = LIMITS.maxColumns + 1;
      m.c = new Array(n).fill(1);
      m.col_lb = new Array(n).fill(0);
      m.col_ub = new Array(n).fill(1);
      m.integrality = new Array(n).fill(1);
      m.col_names = Array.from({ length: n }, (_, j) => `x${j}`); // every list agrees, so that the limit is what refuses it
    },
  };
  for (const [name, change] of Object.entries(BAD_MODELS)) {
    it(`refuses a model with ${name}`, () => {
      expect(() => validateRequest(mutate(change))).toThrow(/bad-request/);
    });
  }

  it("refuses plain data that is too deep, too big, or built to poison a lookup", () => {
    let deep = [];
    for (let i = 0; i < LIMITS.maxDepth + 5; i += 1) deep = [deep];
    expect(() => validateRequest(scenarioRequest({ candidates: deep }))).toThrow(/bad-request/);
    const wide = Array.from({ length: LIMITS.maxNodes + 1 }, () => 1);
    expect(() => validateRequest(scenarioRequest({ owned: wide }))).toThrow(/bad-request/);
    for (const key of ["__proto__", "constructor", "prototype"]) {
      const poisoned = JSON.parse(`{"${key}": {"x": 1}}`);
      expect(() => validateRequest(scenarioRequest({ scenario: poisoned }))).toThrow(/bad-request/);
    }
    expect(Object.prototype.polluted).toBeUndefined();
  });

  it("reads each field of a request once, so a getter cannot show one thing to the check and another to the sender", () => {
    let reads = 0;
    const sneaky = { v: 1, kind: "model", model: handMilp() };
    Object.defineProperty(sneaky, "budgetMs", { enumerable: true, get: () => ((reads += 1), 1000) });
    expect(() => validateRequest(sneaky)).toThrow(/bad-request/); // accessors are refused outright
    expect(reads).toBe(0);
  });
});

describe("checking a request against the manifest", () => {
  const WITH_MANIFEST = (request) => validateRequest(request, MANIFEST);
  it("accepts a trio and a level the manifest lists", () => {
    expect(() => WITH_MANIFEST(scenarioRequest())).not.toThrow();
    expect(() => WITH_MANIFEST(scenarioRequest({ trio: "pal-shd-ber", level: 55 }))).not.toThrow();
  });
  it("refuses a trio the manifest does not list, a level it does not list for that trio, and names from the object chain", () => {
    for (const trio of ["war-war-war", "constructor", "__proto__", "toString", "pal-mnk-ber ", "PAL-MNK-BER", ""]) {
      expect(() => WITH_MANIFEST(scenarioRequest({ trio }))).toThrow(/bad-request/);
    }
    for (const level of [49, 55, 0, -50, 50.5, "50", null, 1e9]) {
      expect(() => WITH_MANIFEST(scenarioRequest({ level }))).toThrow(/bad-request/);
    }
  });
  it("needs no trio for a model request", () => {
    expect(() => WITH_MANIFEST(modelRequest())).not.toThrow();
  });
});

// ---- messages to the worker --------------------------------------------------------------------------------------------------

describe("validating what the page sends the worker", () => {
  it("accepts init, with or without a compiled module, and a solve with a valid request", () => {
    expect(validateToWorker({ v: 1, type: "init" })).toEqual({ v: 1, type: "init" });
    const module = new WebAssembly.Module(EMPTY_MODULE_BYTES);
    expect(validateToWorker({ v: 1, type: "init", module }).module).toBe(module);
    const message = validateToWorker({ v: 1, type: "solve", id: 3, request: modelRequest() });
    expect(message).toMatchObject({ type: "solve", id: 3 });
    expect(message.request.kind).toBe("model");
  });
  for (const [name, value] of Object.entries({
    "nothing": undefined,
    "text": "init",
    "an array": [],
    "another version": { v: 2, type: "init" },
    "an unknown type": { v: 1, type: "fetch" },
    "an init with a url": { v: 1, type: "init", url: "/x.wasm" },
    "an init with a module that is not a module": { v: 1, type: "init", module: {} },
    "a solve without an id": { v: 1, type: "solve", request: modelRequest() },
    "a solve with an id of 0": { v: 1, type: "solve", id: 0, request: modelRequest() },
    "a solve with a text id": { v: 1, type: "solve", id: "1", request: modelRequest() },
    "a solve with a bad request": { v: 1, type: "solve", id: 1, request: { ...modelRequest(), url: "/x" } },
    "a solve with extra fields": { v: 1, type: "solve", id: 1, request: modelRequest(), wasm: "/x" },
  })) {
    it(`refuses ${name}`, () => {
      expect(() => validateToWorker(value)).toThrow(/bad-request/);
    });
  }
});

// ---- messages from the worker ------------------------------------------------------------------------------------------------

describe("validating what the worker sends back", () => {
  const result = (over = {}) => ({
    v: 1,
    type: "result",
    id: 4,
    kind: "model",
    status: "optimal",
    proven: true,
    objective: 37,
    x: [1, 0, 1],
    bound: 37,
    gap: 0,
    nodes: 3,
    elapsedMs: 12,
    label: null,
    ...over,
  });
  const expectation = { id: 4, kind: "model", columns: 3 };

  it("accepts each good message", () => {
    expect(validateFromWorker(result(), expectation)).toMatchObject({ type: "result", status: "optimal" });
    expect(validateFromWorker(result({ status: "infeasible", proven: true, objective: null, x: null, bound: null, gap: null }), expectation).x).toBeNull();
    expect(
      validateFromWorker(result({ status: "time_limit", proven: false, gap: 0.01, label: LABEL_TIME_LIMIT }), expectation).label,
    ).toBe(LABEL_TIME_LIMIT);
    expect(
      validateFromWorker(result({ status: "time_limit", proven: false, objective: null, x: null, bound: 40, gap: null, label: LABEL_NO_INCUMBENT }), expectation).x,
    ).toBeNull();
    expect(validateFromWorker({ v: 1, type: "ready", highs: "1.15.1" }).type).toBe("ready");
    const compiled = new WebAssembly.Module(EMPTY_MODULE_BYTES);
    expect(validateFromWorker({ v: 1, type: "ready", highs: "1.15.1", wasm: WASM_SHA })).toEqual({ v: 1, type: "ready", highs: "1.15.1", wasm: WASM_SHA });
    expect(validateFromWorker({ v: 1, type: "ready", highs: "1.15.1", wasm: WASM_SHA, module: compiled }).module).toBe(compiled);
    expect(validateFromWorker({ v: 1, type: "progress", phase: "loading", loaded: 5, total: 10 }).phase).toBe("loading");
    expect(validateFromWorker({ v: 1, type: "progress", id: 4, phase: "solving", elapsedMs: 3, objective: 1.5, bound: 2, gap: 0.2, nodes: 7 }, expectation).nodes).toBe(7);
    expect(validateFromWorker({ v: 1, type: "error", id: 4, code: "bad-model", message: "no" }, expectation).code).toBe("bad-model");
    expect(validateFromWorker({ v: 1, type: "error", code: "engine-load", message: "no" }).id).toBeUndefined();
  });

  const BAD = {
    "nothing": undefined,
    "null": null,
    "text": "result",
    "an array": [result()],
    "another version": result({ v: 2 }),
    "a version in text": result({ v: "1" }),
    "an unknown type": result({ type: "log" }),
    "a result for another request": result({ id: 5 }),
    "a result without an id": result({ id: undefined }),
    "a result of another kind": result({ kind: "scenario" }),
    "an unknown status": result({ status: "maybe" }),
    "an optimal result that is not proven": result({ proven: false }),
    "a time-limited result that claims to be proven": result({ status: "time_limit", proven: true, label: LABEL_TIME_LIMIT }),
    "a time-limited result without its label": result({ status: "time_limit", proven: false, label: null }),
    "a time-limited result with another label": result({ status: "time_limit", proven: false, label: "optimal" }),
    "a time-limited result with no kit under the wrong label": result({ status: "time_limit", proven: false, x: null, objective: null, label: LABEL_TIME_LIMIT }),
    "an infeasible result with a solution": result({ status: "infeasible", proven: true }),
    "an optimal result without a solution": result({ x: null }),
    "a solution of the wrong length": result({ x: [1, 0] }),
    "a solution with NaN": result({ x: [1, Number.NaN, 0] }),
    "a solution with Infinity": result({ x: [1, Infinity, 0] }),
    "a solution with text": result({ x: [1, "0", 0] }),
    "a solution with an undefined hole": result({ x: [1, undefined, 0] }),
    "an objective in text": result({ objective: "37" }),
    "an objective that is NaN": result({ objective: Number.NaN }),
    "a negative node count": result({ nodes: -1 }),
    "a node count that is not whole": result({ nodes: 1.5 }),
    "an elapsed time below zero": result({ elapsedMs: -1 }),
    "a gap that is NaN": result({ gap: Number.NaN }),
    "an extra field": result({ url: "/x" }),
    "a label that is not text": result({ label: 5 }),
    "a progress report with an unknown phase": { v: 1, type: "progress", phase: "dancing" },
    "a progress report with a negative size": { v: 1, type: "progress", phase: "loading", loaded: -1, total: 10 },
    "a progress report with more than the total": { v: 1, type: "progress", phase: "loading", loaded: 11, total: 10 },
    "a progress report for another request": { v: 1, type: "progress", id: 9, phase: "solving" },
    "a progress report with an extra field": { v: 1, type: "progress", phase: "solving", href: "/x" },
    "a ready message with no version of the solver": { v: 1, type: "ready" },
    "a ready message with a version that is not a version": { v: 1, type: "ready", highs: "<b>1</b>" },
    "a ready message with a module that is not a module": { v: 1, type: "ready", highs: "1.15.1", module: { a: 1 } },
    "a ready message with a module and no checksum of the file it was made from": { v: 1, type: "ready", highs: "1.15.1", module: new WebAssembly.Module(EMPTY_MODULE_BYTES) },
    "a ready message with a checksum in capitals": { v: 1, type: "ready", highs: "1.15.1", wasm: WASM_SHA.toUpperCase() },
    "a ready message with a checksum that is too short": { v: 1, type: "ready", highs: "1.15.1", wasm: WASM_SHA.slice(2) },
    "a ready message with a checksum that is not text": { v: 1, type: "ready", highs: "1.15.1", wasm: 5 },
    "a ready message with a checksum that looks like an address": { v: 1, type: "ready", highs: "1.15.1", wasm: "/assets/engine/highs-0123456789ABCDEF.wasm" },
    "an error with an unknown code": { v: 1, type: "error", code: "oops", message: "x" },
    "an error with a message that is not text": { v: 1, type: "error", code: "solver", message: 5 },
    "an error with a very long message": { v: 1, type: "error", code: "solver", message: "x".repeat(LIMITS.maxMessageLength + 1) },
    "an error with a message with a control character": { v: 1, type: "error", code: "solver", message: "x\u0007" },
  };
  for (const [name, value] of Object.entries(BAD)) {
    it(`refuses ${name}`, () => {
      expect(() => validateFromWorker(value, expectation)).toThrow(/protocol/);
    });
  }
});

// ---- the Trusted Types policy ------------------------------------------------------------------------------------------------

describe("the Trusted Types policy", () => {
  function fakeTrustedTypes() {
    const created = [];
    return {
      created,
      createPolicy(name, rules) {
        created.push({ name, rules });
        return { name, createScriptURL: (input) => ({ trusted: true, value: rules.createScriptURL(input), toString: () => String(rules.createScriptURL(input)) }) };
      },
    };
  }

  it("is one policy named trioforge, with only the script-address rule", () => {
    const tt = fakeTrustedTypes();
    const policy = getAssetPolicy(tt, [WORKER_PATH]);
    getAssetPolicy(tt, [WORKER_PATH]);
    getAssetPolicy(tt, [WORKER_PATH, WASM_PATH]);
    expect(POLICY_NAME).toBe("trioforge");
    expect(tt.created).toHaveLength(1);
    expect(tt.created[0].name).toBe("trioforge");
    expect(Object.keys(tt.created[0].rules)).toEqual(["createScriptURL"]); // no page-HTML or inline-script rule
    expect(policy.scriptURL(WORKER_PATH)).toMatchObject({ trusted: true, value: WORKER_PATH });
    // the rule the browser holds checks as well, whoever calls it: the policy object has no other way in
    const rule = tt.created[0].rules.createScriptURL;
    expect(rule(WORKER_PATH)).toBe(WORKER_PATH);
    expect(rule(WASM_PATH)).toBe(WASM_PATH); // listed by the third call
    for (const refused of ["/assets/engine/worker-CCCCCCCC.js", "https://evil.example/x.js", "javascript:1", "", undefined, 5]) {
      expect(() => rule(refused), String(refused)).toThrow(TypeError);
    }
  });

  it("gives out a trusted address for a path the manifest lists, and for nothing else", () => {
    const tt = fakeTrustedTypes();
    const policy = getAssetPolicy(tt, [WORKER_PATH]);
    for (const refused of [
      "/assets/engine/worker-CCCCCCCC.js",
      `${WORKER_PATH}?v=2`,
      `${WORKER_PATH}#x`,
      `https://trioforge.test${WORKER_PATH}`,
      `//evil.example${WORKER_PATH}`,
      "/assets/app-AAAAAAAA.js",
      "blob:https://trioforge.test/1",
      "data:text/javascript,1",
      "javascript:1",
      "",
      " " + WORKER_PATH,
      WORKER_PATH + " ",
    ]) {
      expect(() => policy.scriptURL(refused), refused).toThrow(TypeError);
    }
    for (const notText of [undefined, null, 5, {}, { toString: () => WORKER_PATH }, [WORKER_PATH]]) {
      expect(() => policy.scriptURL(notText)).toThrow(TypeError);
    }
  });

  it("refuses to list a path that is not a hashed engine file", () => {
    const tt = fakeTrustedTypes();
    for (const path of ["/assets/app.js", "/assets/engine/worker.js", "https://evil.example/x.js", "/assets/engine/../x-AAAAAAAA.js", ""]) {
      expect(() => getAssetPolicy(tt, [path])).toThrow(TypeError);
    }
  });

  it("works without Trusted Types: the same check, and a plain address back", () => {
    for (const none of [undefined, null, {}, { createPolicy: 5 }]) {
      const policy = getAssetPolicy(none, [WORKER_PATH]);
      expect(policy.scriptURL(WORKER_PATH)).toBe(WORKER_PATH);
      expect(() => policy.scriptURL("/assets/engine/worker-CCCCCCCC.js")).toThrow(TypeError);
    }
  });

  it("lets the error of a policy that cannot be made come through", () => {
    const refusing = {
      createPolicy() {
        throw new TypeError("Policy with name trioforge disallowed.");
      },
    };
    expect(() => getAssetPolicy(refusing, [WORKER_PATH])).toThrow(/disallowed/);
  });
});

// ---- the protocol: a client, a worker core and a fake engine -----------------------------------------------------------------

describe("the protocol, client and worker core against a fake engine", () => {
  it("sends a request, reports progress and returns the result without the envelope", async () => {
    const h = makeHarness();
    const progress = [];
    const result = await h.client.solve(modelRequest(), { onProgress: (p) => progress.push(p) });
    expect(result).toEqual({
      kind: "model",
      status: "optimal",
      proven: true,
      objective: 37,
      x: new Array(9).fill(0),
      bound: 37,
      gap: 0,
      nodes: 3,
      elapsedMs: 0,
      label: null,
    });
    expect(progress.map((p) => p.phase)).toEqual(["loading", "compiling", "building", "solving"]);
    expect(progress[0]).toEqual({ phase: "loading", loaded: 50, total: 100 });
    expect(progress.at(-1)).toMatchObject({ phase: "solving", elapsedMs: 5, objective: 30 });
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].url).toBe(WORKER_PATH);
    expect(h.workers[0].sent.map((m) => m.type)).toEqual(["init", "solve"]);
    expect(h.workers[0].sent[1]).toMatchObject({ v: 1, id: 1, request: { kind: "model", budgetMs: 5000 } });
    expect(h.engine.calls).toEqual([{ type: "load", hadModule: false }, { type: "solve", columns: 9, budgetMs: 5000 }]);
  });

  it("gives the engine the clock it counts the request on, and the moment the request arrived on it", async () => {
    let seen;
    const engine = fakeEngine();
    const load = engine.load.bind(engine);
    engine.load = async (args) => {
      const loaded = await load(args);
      return {
        ...loaded,
        async solveModel(model, options) {
          seen = options;
          return loaded.solveModel(model, options);
        },
      };
    };
    let clock = 5000;
    const h = makeHarness({ engine, now: () => clock });
    await h.client.solve(modelRequest());
    expect(seen.startedAt).toBe(5000);
    expect(seen.now()).toBe(5000);
    clock = 7000;
    expect(seen.now()).toBe(7000); // the very clock of the core, not a copy of its reading
  });

  it("starts the worker once and reuses it for the next requests, in the order they were made", async () => {
    const h = makeHarness();
    const order = [];
    const all = [1, 2, 3].map((n) => h.client.solve(modelRequest()).then(() => order.push(n)));
    await Promise.all(all);
    expect(order).toEqual([1, 2, 3]);
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].sent.filter((m) => m.type === "solve").map((m) => m.id)).toEqual([1, 2, 3]);
    expect(h.engine.calls.filter((c) => c.type === "load")).toHaveLength(1);
    expect(h.client.stats()).toMatchObject({ spawns: 1, solves: 3 });
  });

  it("sends the second request only when the first has an answer", async () => {
    const gate = { release: null };
    const engine = fakeEngine();
    const original = engine.load.bind(engine);
    engine.load = async (args) => {
      const loaded = await original(args);
      const solve = loaded.solveModel;
      loaded.solveModel = async (...a) => {
        await new Promise((resolve) => (gate.release = resolve));
        return solve(...a);
      };
      return loaded;
    };
    const h = makeHarness({ engine });
    const first = track(h.client.solve(modelRequest()));
    const second = track(h.client.solve(modelRequest()));
    await tick(80);
    expect(h.workers[0].sent.filter((m) => m.type === "solve")).toHaveLength(1);
    gate.release();
    await tick(80);
    expect(first.state).toBe("resolved");
    expect(h.workers[0].sent.filter((m) => m.type === "solve")).toHaveLength(2);
    gate.release();
    await tick(80);
    expect(second.state).toBe("resolved");
  });

  it("is not hurt by a progress callback that throws", async () => {
    const h = makeHarness();
    const result = await h.client.solve(modelRequest(), {
      onProgress: () => {
        throw new Error("a bug in the page");
      },
    });
    expect(result.status).toBe("optimal");
  });

  it("returns a time-limited result with its honest label, and keeps the worker", async () => {
    const engine = fakeEngine({
      result: { status: "time_limit", proven: false, objective: 30, x: new Array(9).fill(0), bound: 40, gap: 0.25, nodes: 9, label: LABEL_TIME_LIMIT },
    });
    const h = makeHarness({ engine });
    const result = await h.client.solve(modelRequest());
    expect(result).toMatchObject({ status: "time_limit", proven: false, label: "best found, not proven optimal" });
    expect(h.workers[0].terminated).toBe(false);
  });

  it("passes a fault the engine reports on as an EngineError and keeps the worker for the next request", async () => {
    for (const code of ["solver", "bad-model"]) {
      const engine = fakeEngine({ fault: code });
      const h = makeHarness({ engine });
      const failed = h.client.solve(modelRequest());
      await expect(failed).rejects.toBeInstanceOf(EngineError);
      await expect(failed).rejects.toMatchObject({ code });
      expect(h.workers[0].terminated).toBe(false);
      engine.state.fault = undefined;
      await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
      expect(h.workers).toHaveLength(1);
    }
  });

  it("replaces a worker whose WebAssembly failed in a way the engine does not know (an abort when the memory ran out, say)", async () => {
    const engine = fakeEngine({ throws: "Aborted(OOM)" });
    const h = makeHarness({ engine });
    const failed = h.client.solve(modelRequest());
    await expect(failed).rejects.toMatchObject({ code: "internal" });
    expect(h.workers[0].terminated).toBe(true); // an instance that aborted is not used again
    engine.state.throws = undefined;
    await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(h.workers).toHaveLength(2);
    expect(engine.calls.filter((c) => c.type === "load").map((c) => c.hadModule)).toEqual([false, true]); // from the kept module
  });

  it("answers a scenario request of a mode that has no shape with a bad request at once, before the manifest is read and before anything is asked or downloaded", async () => {
    const ask = vi.fn(async () => true);
    const h = makeHarness({ consent: { ask } });
    await expect(h.client.solve(scenarioRequest({ mode: "best-1" }))).rejects.toMatchObject({ code: "bad-request" });
    expect(ask).not.toHaveBeenCalled(); // the visitor is not asked to download several megabytes for an answer that cannot come
    expect(h.workers).toHaveLength(0);
    expect(h.fetchCalls).toEqual([]); // not even the list of files
    expect(h.client.consentState()).toBe("unknown");
    expect(h.engine.calls).toEqual([]);
  });

  it("does not show the question or keep a yes for a scenario request that is a bad request, and a model request after it is asked as usual", async () => {
    const h = makeHarness({ consent: null, navigator: {} });
    await expect(h.client.solve(scenarioRequest({ mode: "best-1" }))).rejects.toMatchObject({ code: "bad-request" });
    expect(h.document.querySelector(".engine-consent")).toBeNull();
    expect(h.dom.window.sessionStorage.getItem("trioforge-engine-consent")).toBeNull();
    expect(h.workers).toHaveLength(0);
    const later = track(h.client.solve(modelRequest()));
    await vi.waitFor(() => expect(h.document.querySelector('[data-action="accept"]')).not.toBeNull());
    expect(later.state).toBe("pending");
    h.document.querySelector('[data-action="accept"]').click();
    await vi.waitFor(() => expect(later.state).toBe("resolved"));
  });

  it("still answers a scenario request with not-implemented when it is posted straight to a worker whose engine has nothing for its mode", async () => {
    const worker = new FakeWorker("x", { core: makeCore(fakeEngine()) });
    const replies = [];
    worker.onmessage = (event) => replies.push(event.data);
    worker.postMessage({ v: 1, type: "init" });
    await tick(40);
    worker.postMessage({ v: 1, type: "solve", id: 1, request: scenarioRequest() });
    await tick(40);
    expect(replies.at(-1)).toMatchObject({ type: "error", id: 1, code: "not-implemented" });
  });

  it("refuses a scenario for a trio or a level the manifest does not list, before it asks for anything", async () => {
    const ask = vi.fn(async () => true);
    const h = makeHarness({ consent: { ask } });
    await expect(h.client.solve(scenarioRequest({ trio: "war-war-war" }))).rejects.toMatchObject({ code: "bad-request" });
    await expect(h.client.solve(scenarioRequest({ level: 99 }))).rejects.toMatchObject({ code: "bad-request" });
    expect(ask).not.toHaveBeenCalled();
    expect(h.workers).toHaveLength(0);
  });

  it("refuses a request that carries an address, before the manifest, the consent question or a worker", async () => {
    const ask = vi.fn(async () => true);
    const h = makeHarness({ consent: { ask } });
    for (const extra of [{ url: "https://evil.example/x.wasm" }, { wasmUrl: "/assets/engine/highs.wasm" }, { href: "//evil.example" }, { importScripts: ["x"] }]) {
      await expect(h.client.solve({ ...modelRequest(), ...extra })).rejects.toMatchObject({ code: "bad-request" });
      await expect(h.client.solve({ ...scenarioRequest(), ...extra })).rejects.toMatchObject({ code: "bad-request" });
    }
    // (a name in the model that looks like an address is a label like any other, as in milp_json.py: nothing reads it as an address)
    expect(h.fetchCalls).toEqual([]);
    expect(ask).not.toHaveBeenCalled();
    expect(h.workers).toHaveLength(0);
  });

  it("refuses the same requests again in the worker, when something posts them straight to it", async () => {
    const engine = fakeEngine();
    const posted = [];
    const core = createWorkerCore({ post: (m) => posted.push(m), loadManifest: async () => MANIFEST, loadEngine: (a) => engine.load(a), now: () => 0 });
    await core.handle({ v: 1, type: "init" });
    expect(posted.map((m) => m.type)).toContain("ready");
    posted.length = 0;
    await core.handle({ v: 1, type: "solve", id: 7, request: { ...modelRequest(), url: "https://evil.example/x.wasm" } });
    await core.handle({ v: 1, type: "solve", id: 8, request: scenarioRequest({ trio: "war-war-war" }) });
    await core.handle({ v: 1, type: "solve", id: 9, request: scenarioRequest({ mode: "https://evil.example" }) });
    await core.handle({ v: 1, type: "solve", id: 10, request: modelRequest({ budgetMs: -1 }) });
    await core.handle("solve");
    await core.handle({ v: 1, type: "fetch", url: "/x" });
    await core.handle(null);
    expect(posted.map((m) => [m.type, m.code, m.id])).toEqual([
      ["error", "bad-request", 7],
      ["error", "bad-request", 8],
      ["error", "bad-request", 9],
      ["error", "bad-request", 10],
      ["error", "bad-request", undefined],
      ["error", "bad-request", undefined],
      ["error", "bad-request", undefined],
    ]);
    expect(engine.calls.filter((c) => c.type === "solve")).toEqual([]);
  });

  it("describes a failure in one short, plain line, whatever it was made of", () => {
    expect(describeError(new Error("tab\there\nnewline\u0000nul"))).toBe("tab here newline nul");
    expect(describeError(new Error("na\u00efve \u202e"))).toBe("na ve");
    expect(describeError("x".repeat(1000))).toHaveLength(LIMITS.maxMessageLength);
    for (const nothing of [undefined, null, 5, {}, new Error(""), "   "]) expect(describeError(nothing)).toBe("The optimizer failed.");
  });

  it("makes the worker answer a solve before init with an error, and refuses a second init", async () => {
    const engine = fakeEngine();
    const posted = [];
    const core = createWorkerCore({ post: (m) => posted.push(m), loadManifest: async () => MANIFEST, loadEngine: (a) => engine.load(a), now: () => 0 });
    await core.handle({ v: 1, type: "solve", id: 1, request: modelRequest() });
    expect(posted.at(-1)).toMatchObject({ type: "error", id: 1, code: "not-ready" });
    await core.handle({ v: 1, type: "init" });
    await core.handle({ v: 1, type: "init" });
    expect(posted.at(-1)).toMatchObject({ type: "error", code: "bad-request" });
    expect(engine.calls.filter((c) => c.type === "load")).toHaveLength(1);
  });

  it("still reports ready when the browser will not copy the compiled module to the page", async () => {
    const posted = [];
    const cloneError = () => new DOMException("could not be cloned", "DataCloneError");
    const core = createWorkerCore({
      post: (message) => {
        if ("module" in message) throw cloneError();
        posted.push(message);
      },
      loadManifest: async () => MANIFEST,
      loadEngine: (args) => fakeEngine().load(args),
      now: () => 0,
    });
    await core.handle({ v: 1, type: "init" });
    expect(posted.at(-1)).toEqual({ v: 1, type: "ready", highs: "1.15.1", wasm: WASM_SHA }); // ready, with the checksum of the file it loaded and without the module
    await core.handle({ v: 1, type: "solve", id: 1, request: modelRequest() });
    expect(posted.at(-1)).toMatchObject({ type: "result", id: 1, status: "optimal" });
  });

  it("names the file its manifest lists in ready also when it was given a compiled module, so that the page can see a newer manifest than the module's", async () => {
    const newer = parseManifest({ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, path: "/assets/engine/highs-FEDCBA9876543210.wasm", sha256: "fedcba9876543210".padEnd(64, "0") } });
    for (const [manifest, sha] of [[MANIFEST, WASM_SHA], [newer, newer.wasm.sha256]]) {
      const posted = [];
      const core = createWorkerCore({ post: (message) => posted.push(message), loadManifest: async () => manifest, loadEngine: (args) => fakeEngine().load(args), now: () => 0 });
      await core.handle({ v: 1, type: "init", module: new WebAssembly.Module(EMPTY_MODULE_BYTES) });
      expect(posted.at(-1)).toEqual({ v: 1, type: "ready", highs: "1.15.1", wasm: sha }); // no module of its own to hand back: it compiled nothing
    }
  });

  it("starts a worker without the kept module when the browser will not copy it in, and goes on", async () => {
    const engine = fakeEngine();
    const made = [];
    const createWorker = (url) => {
      const worker = new FakeWorker(url, { core: makeCore(engine) });
      if (made.length === 1) {
        const original = worker.postMessage.bind(worker);
        worker.postMessage = (data) => {
          if (data && "module" in data) throw new DOMException("could not be cloned", "DataCloneError");
          original(data);
        };
      }
      made.push(worker);
      return worker;
    };
    const h = makeHarness({ engine, createWorker });
    await h.client.solve(modelRequest());
    expect(h.client.stats().moduleKept).toBe(true);
    made[0].crash(); // the first worker is lost; the second is started with the module, which this browser refuses to copy
    await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(made).toHaveLength(2);
    expect(engine.calls.filter((c) => c.type === "load").map((c) => c.hadModule)).toEqual([false, false]); // it compiled for itself
    expect(made[1].terminated).toBe(false);
  });

  it("reports an engine that cannot load, and the next request tries again with a new worker", async () => {
    const engine = fakeEngine();
    let failures = 1;
    const load = engine.load.bind(engine);
    engine.load = async (args) => {
      if (failures > 0) {
        failures -= 1;
        throw new Error("the optimizer file did not load");
      }
      return load(args);
    };
    const h = makeHarness({ engine });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "engine-load" });
    expect(h.workers[0].terminated).toBe(true);
    await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(h.workers).toHaveLength(2);
  });

  it("clears the kept module when a worker that was given it cannot start, so that the next worker downloads a fresh one", async () => {
    const engine = fakeEngine();
    const h = makeHarness({ engine });
    await h.client.solve(modelRequest()); // worker 1 downloads and the page keeps its module
    expect(h.client.stats().moduleKept).toBe(true);
    h.workers[0].crash(); // the worker is lost; the next one is started from the kept module
    await tick(10);
    engine.state.failWithModule = "the kept module will not start";
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "engine-load" });
    expect(h.workers[1].sent[0].module).toBeInstanceOf(WebAssembly.Module); // it was given the kept one
    expect(h.client.stats().moduleKept).toBe(false); // and the page does not keep a module that failed
    engine.state.failWithModule = null;
    await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(h.workers[2].sent[0].module).toBeUndefined(); // a fresh download, not the module that failed
    expect(engine.calls.filter((c) => c.type === "load").map((c) => c.hadModule)).toEqual([false, true, false]);
    expect(h.client.stats().moduleKept).toBe(true); // and the new one is kept
  });

  it("keeps the module when the request that started a worker from it is cancelled: that is not the module's fault", async () => {
    const engine = fakeEngine();
    const h = makeHarness({ engine });
    await h.client.solve(modelRequest());
    h.workers[0].crash();
    await tick(10);
    const load = engine.load.bind(engine);
    engine.load = (args) => (args.module === undefined ? load(args) : new Promise(() => {})); // the second worker never finishes starting
    const waiting = track(h.client.solve(modelRequest()));
    await tick(80);
    h.client.cancel();
    await tick(10);
    expect(waiting.error).toMatchObject({ code: "cancelled" });
    expect(h.client.stats().moduleKept).toBe(true);
  });

  it("keeps the module when a worker that started from it and works sends an error that no request asked for", async () => {
    // only a worker that could not start says something about the module it was given; this one started, and is dropped for what it said later
    const second = (message, reply) => {
      if (message.type === "init") reply({ v: 1, type: "ready", highs: "1.15.1", wasm: WASM_SHA }); // (every ready names the file its manifest lists, also when it was given the module)
      else if (message.type === "solve") reply({ v: 1, type: "error", code: "bad-request", message: "an error that nobody asked for" });
    };
    const h = makeHarness({ scripts: [undefined, second] });
    await h.client.solve(modelRequest());
    expect(h.client.stats().moduleKept).toBe(true);
    h.workers[0].crash();
    await tick(10);
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "bad-request" });
    expect(h.workers[1].sent[0].module).toBeInstanceOf(WebAssembly.Module);
    expect(h.workers[1].terminated).toBe(true);
    expect(h.client.stats().moduleKept).toBe(true);
  });

  it("drops a worker that loaded another file than the one the page's manifest lists, and keeps nothing it made", async () => {
    // a release between the page's read of the manifest and the worker's: the worker lists, downloads and checks another file
    const other = parseManifest({ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, path: "/assets/engine/highs-FEDCBA9876543210.wasm", sha256: "fedcba9876543210".padEnd(64, "0") } });
    const h = makeHarness({ workerManifest: other });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(/changed|new version|reload/i) });
    expect(h.workers[0].terminated).toBe(true);
    expect(h.client.stats().moduleKept).toBe(false); // the module of the other file is not kept
  });

  it("drops a worker that downloaded the optimizer and does not say which file it was", async () => {
    const script = (message, reply) => {
      if (message.type === "init") reply({ v: 1, type: "ready", highs: "1.15.1" }); // no module was given, so it downloaded one: it must say which
    };
    const h = makeHarness({ script });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "protocol" });
    expect(h.workers[0].terminated).toBe(true);
  });

  it("sends nothing but the version, the type and the module in init, and no address", async () => {
    const h = makeHarness();
    await h.client.solve(modelRequest());
    expect(Object.keys(h.workers[0].sent[0]).sort()).toEqual(["type", "v"]);
    const everything = JSON.stringify(h.workers[0].sent.map(({ module, ...rest }) => rest));
    expect(everything).not.toMatch(/https?:|wasm|assets\/|\.js/);
  });
});

// ---- replies that cannot be trusted ------------------------------------------------------------------------------------------

describe("malformed replies", () => {
  const READY = { v: 1, type: "ready", highs: "1.15.1", wasm: WASM_SHA }; // (a worker that downloaded the file the manifest lists says so)
  const GOOD = {
    v: 1,
    type: "result",
    id: 1,
    kind: "model",
    status: "optimal",
    proven: true,
    objective: 37,
    x: new Array(9).fill(0),
    bound: 37,
    gap: 0,
    nodes: 1,
    elapsedMs: 4,
    label: null,
  };
  const REPLIES = {
    "text in place of a message": "result",
    "null": null,
    "an array": [GOOD],
    "a message of another version": { ...GOOD, v: 2 },
    "a message of an unknown type": { ...GOOD, type: "banner" },
    "a result for a request that is not in flight": { ...GOOD, id: 99 },
    "a result with an address in it": { ...GOOD, url: "https://evil.example/x" },
    "a solution of the wrong length": { ...GOOD, x: [0, 1] },
    "a solution with NaN": { ...GOOD, x: [0, 0, 0, 0, 0, 0, 0, 0, Number.NaN] },
    "an objective in text": { ...GOOD, objective: "37" },
    "a status that is not one": { ...GOOD, status: "fine" },
    "an optimal result that is not proven": { ...GOOD, proven: false },
    "a progress report that is not one": { v: 1, type: "progress", id: 1, phase: "dancing" },
    "a second ready message": READY,
    "an error with a code that is not one": { v: 1, type: "error", id: 1, code: "oops", message: "x" },
  };
  /** A worker that behaves: ready for init, a good result for each solve. */
  const goodScript = (message, send) => {
    if (message.type === "init") send(READY);
    else if (message.type === "solve") send({ ...GOOD, id: message.id });
  };

  for (const [name, reply] of Object.entries(REPLIES)) {
    it(`rejects ${name}, drops the worker and goes on with a new one`, async () => {
      const badScript = (message, send) => {
        if (message.type === "init") send(READY);
        else if (message.type === "solve") send(reply);
      };
      const h = makeHarness({ scripts: [badScript, goodScript] });
      await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "protocol" });
      expect(h.workers[0].terminated).toBe(true);
      // the next request gets a new worker, and a good answer from it is accepted
      await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
      expect(h.workers).toHaveLength(2);
      expect(h.workers[1].terminated).toBe(false);
    });
  }

  it("drops a worker that speaks when nothing was asked", async () => {
    let speak = null;
    const script = (message, send) => {
      speak = send;
      goodScript(message, send);
    };
    const h = makeHarness({ scripts: [script, goodScript] });
    await h.client.solve(modelRequest());
    speak({ ...GOOD, id: 1 }); // an answer to a request that was answered long ago
    await tick(20);
    expect(h.workers[0].terminated).toBe(true);
    await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(h.workers).toHaveLength(2);
  });

  it("rejects a reply to init that is not ready", async () => {
    const script = (message, send) => {
      if (message.type === "init") send({ ...READY, v: 2 });
    };
    const h = makeHarness({ script });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "protocol" });
    expect(h.workers[0].terminated).toBe(true);
  });

  it("treats an unreadable message and a crash of the worker as a failure of the worker", async () => {
    const quiet = (message, send) => {
      if (message.type === "init") send(READY);
    };
    const h = makeHarness({ script: quiet });
    const a = track(h.client.solve(modelRequest()));
    await tick(80);
    h.workers[0].onmessageerror?.({});
    await tick(20);
    expect(a.state).toBe("rejected");
    expect(a.error).toMatchObject({ code: "protocol" });
    expect(h.workers[0].terminated).toBe(true);

    const b = track(h.client.solve(modelRequest()));
    await tick(80);
    h.workers[1].crash("Uncaught SyntaxError");
    await tick(20);
    expect(b.error).toMatchObject({ code: "worker-failed" });
    expect(h.workers[1].terminated).toBe(true);
  });

  it("fails a request, and does not leave it waiting, when the worker is lost between its ready message and the request", async () => {
    let harness = null;
    const flaky = (message, send) => {
      if (message.type !== "init") return;
      send(READY);
      queueMicrotask(() => harness.workers[0].crash("lost")); // right behind the ready message
    };
    harness = makeHarness({ scripts: [flaky, goodScript] });
    await expect(harness.client.solve(modelRequest())).rejects.toMatchObject({ code: "worker-failed" });
    expect(harness.workers[0].terminated).toBe(true);
    await expect(harness.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(harness.workers).toHaveLength(2);
  });

  it("fails a request, and starts a new worker for the next, when the worker is lost while it is starting", async () => {
    let harness = null;
    const silent = () => {}; // never answers init
    harness = makeHarness({ scripts: [silent, goodScript] });
    const first = track(harness.client.solve(modelRequest()));
    await tick(80);
    expect(first.state).toBe("pending");
    harness.workers[0].crash("could not load the worker's file");
    await tick(20);
    expect(first.error).toMatchObject({ code: "worker-failed" });
    await expect(harness.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(harness.workers).toHaveLength(2);
  });

  it("does not pass on the progress of a worker that has just been dropped, while its request is still the one being handled", async () => {
    const seen = [];
    const h = makeHarness({ engine: fakeEngine({ hang: true }) });
    const request = track(h.client.solve(modelRequest(), { onProgress: (p) => seen.push(p) }));
    await tick(80);
    expect(seen.some((p) => p.phase === "solving")).toBe(true);
    const stale = h.workers[0].firstHandler;
    const before = seen.length;
    h.client.cancel(); // the worker is dropped; its request is still `current` until the turn ends
    stale({ data: { v: 1, type: "progress", id: 1, phase: "solving", elapsedMs: 99 } }); // a report that was already on its way
    expect(seen).toHaveLength(before);
    await tick(10);
    expect(request.error).toMatchObject({ code: "cancelled" });
    expect(seen).toHaveLength(before);
  });

  it("does not let a worker that was dropped speak again: a late message from it changes nothing", async () => {
    const broken = (message, send) => {
      if (message.type === "init") send(READY);
      else if (message.type === "solve") send({ ...GOOD, v: 3 });
    };
    const quiet = (message, send) => {
      if (message.type === "init") send(READY);
    };
    const h = makeHarness({ scripts: [broken, quiet] });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "protocol" });
    const second = track(h.client.solve(modelRequest())); // in flight on the new worker, with id 2
    await tick(80);
    expect(h.workers).toHaveLength(2);
    const stale = h.workers[0].firstHandler;
    expect(typeof stale).toBe("function");
    // a message already on its way from the dropped worker, and a good one: it must not answer the request that is waiting
    stale({ data: { ...GOOD, id: 2 } });
    await tick(20);
    expect(second.state).toBe("pending");
    expect(h.workers[1].terminated).toBe(false);
  });
});

// ---- cancel and the watchdog -------------------------------------------------------------------------------------------------

describe("cancel", () => {
  it("rejects the request at once, drops the worker, and the next request gets a new one that keeps the compiled module", async () => {
    const engine = fakeEngine({ hang: true });
    const h = makeHarness({ engine });
    const first = track(h.client.solve(modelRequest()));
    await tick(80);
    expect(h.workers[0].sent.map((m) => m.type)).toEqual(["init", "solve"]);
    const compiled = h.workers[0].delivered.find((m) => m.type === "ready").module;
    expect(compiled).toBeInstanceOf(WebAssembly.Module);

    h.client.cancel();
    await tick(10);
    expect(first.state).toBe("rejected");
    expect(first.error).toMatchObject({ code: "cancelled" });
    expect(h.workers[0].terminated).toBe(true);

    engine.state.hang = false;
    const second = await h.client.solve(modelRequest());
    expect(second.status).toBe("optimal");
    expect(h.workers).toHaveLength(2);
    expect(h.workers[1].sent[0].module).toBe(compiled); // the same compiled module: no download, no compile
    expect(engine.calls.filter((c) => c.type === "load").map((c) => c.hadModule)).toEqual([false, true]);
    expect(h.workers[1].delivered.find((m) => m.type === "ready").module).toBeUndefined(); // nothing new to keep
    expect(h.client.stats()).toMatchObject({ spawns: 2, moduleKept: true });
  });

  it("also rejects every request that is waiting behind the running one", async () => {
    const h = makeHarness({ engine: fakeEngine({ hang: true }) });
    const outcomes = [1, 2, 3].map(() => track(h.client.solve(modelRequest())));
    await tick(80);
    h.client.cancel();
    await tick(10);
    expect(outcomes.map((o) => [o.state, o.error?.code])).toEqual([
      ["rejected", "cancelled"],
      ["rejected", "cancelled"],
      ["rejected", "cancelled"],
    ]);
    expect(h.workers[0].sent.filter((m) => m.type === "solve")).toHaveLength(1); // the others never reached the worker
  });

  it("refuses requests beyond a long line of them, and the ones in line are not affected", async () => {
    const engine = fakeEngine({ hang: true });
    const h = makeHarness({ engine });
    const running = track(h.client.solve(modelRequest()));
    await tick(80);
    const waiting = Array.from({ length: 64 }, () => track(h.client.solve(modelRequest())));
    const extra = track(h.client.solve(modelRequest()));
    await tick(10);
    expect(extra.state).toBe("rejected");
    expect(extra.error).toMatchObject({ code: "busy" });
    expect(waiting.every((w) => w.state === "pending")).toBe(true);
    h.client.cancel();
    await tick(10);
    expect(running.error).toMatchObject({ code: "cancelled" });
    expect(waiting.every((w) => w.error?.code === "cancelled")).toBe(true);
  });

  it("does nothing when nothing is running", async () => {
    const h = makeHarness();
    h.client.cancel();
    await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    h.client.cancel();
    expect(h.workers[0].terminated).toBe(false); // an idle worker is left alone
  });

  it("stops a request that is still waiting for the answer to the consent question", async () => {
    let answer = null;
    const h = makeHarness({ consent: { ask: () => new Promise((resolve) => (answer = resolve)) } });
    const waiting = track(h.client.solve(modelRequest()));
    await tick(80);
    expect(answer).not.toBeNull();
    h.client.cancel();
    await tick(10);
    expect(waiting.error).toMatchObject({ code: "cancelled" });
    answer(true);
    await tick(40);
    expect(h.workers).toHaveLength(0); // the request that asked is gone; nothing starts for it
  });
});

describe("a request that is cancelled, dropped or failed never keeps the next one waiting", () => {
  const fakeTimers = () => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  // the budget of a request tells the scripted worker what to do with it
  const NORMAL = 1000; // answers at once
  const HANG = 2000; // never answers (the watchdog stops it after its budget plus five seconds)
  const FAILS = 3000; // answers with an error that belongs to the request (the worker is fine)
  const ABORTS = 4000; // answers with an `internal` error: the worker is not to be used again

  /** A worker made of a script, with pings that can be held back (an answer that has not arrived yet) and a record of what it was asked to solve. */
  function scripted() {
    const control = { holdPings: false, held: [], solves: [] };
    const script = (message, reply) => {
      if (message.type === "init") {
        reply({ v: 1, type: "ready", highs: "1.15.1", wasm: WASM_SHA, ...(message.module === undefined ? { module: new WebAssembly.Module(EMPTY_MODULE_BYTES) } : {}) });
      } else if (message.type === "ping") {
        const answer = () => reply({ v: 1, type: "pong" });
        if (control.holdPings) control.held.push(answer);
        else answer();
      } else if (message.type === "solve") {
        const { budgetMs } = message.request;
        control.solves.push(budgetMs);
        if (budgetMs === HANG) return;
        if (budgetMs === FAILS) return reply({ v: 1, type: "error", id: message.id, code: "solver", message: "the solver says no" });
        if (budgetMs === ABORTS) return reply({ v: 1, type: "error", id: message.id, code: "internal", message: "the memory ran out" });
        reply({ v: 1, type: "result", id: message.id, kind: "model", status: "optimal", proven: true, objective: 1, x: new Array(message.request.model.c.length).fill(0), bound: 1, gap: 0, nodes: 0, elapsedMs: 1, label: null });
      }
    };
    return {
      control,
      script,
      /** The answers to the pings that were held back arrive now. */
      arrive() {
        for (const answer of control.held.splice(0)) answer();
      },
    };
  }

  it("does not post a request that was cancelled while the question to the worker was out: the slider that previews on input and settles on change", async () => {
    fakeTimers();
    const worker = scripted();
    const h = makeHarness({ script: worker.script });
    await h.client.solve(modelRequest({ budgetMs: NORMAL })); // the worker has worked now, so the next request asks first whether it is still there
    for (let press = 1; press <= 3; press += 1) {
      worker.control.holdPings = true;
      const preview = track(h.client.solve(modelRequest({ budgetMs: HANG }))); // the `input` event
      await tick(60); // (the page runs the microtasks between the two handlers of one key press: the question is out when `change` comes)
      expect(worker.control.held, `press ${press}: the question to the worker is out`).toHaveLength(1);
      h.client.cancel(); // the `change` event
      const final = track(h.client.solve(modelRequest({ budgetMs: NORMAL })));
      worker.arrive(); // the answer to the first question
      await tick(60);
      expect(preview.error, `press ${press}`).toMatchObject({ code: "cancelled" });
      expect(worker.control.held, `press ${press}: the final request asks for itself, the cancelled one did not go on to the worker`).toHaveLength(1);
      worker.control.holdPings = false;
      worker.arrive();
      await tick(60);
      expect(final.state, `press ${press}: the final request is answered`).toBe("resolved");
      expect(worker.control.solves.includes(HANG), `press ${press}: the cancelled request was never posted`).toBe(false);
    }
    expect(h.workers).toHaveLength(1); // and it all happened on the one worker
    expect(vi.getTimerCount()).toBe(0);
  });

  /** A small deterministic source of numbers in [0, 1). */
  function seeded(seed) {
    let state = seed >>> 0;
    return () => {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      return state / 2 ** 32;
    };
  }

  for (let seed = 1; seed <= 60; seed += 1) {
    it(`ends every request, and answers the next, whatever was done to the requests and the worker before (sequence ${seed})`, async () => {
      fakeTimers();
      const worker = scripted();
      const h = makeHarness({ script: worker.script });
      const random = seeded(seed * 7919);
      const pick = (list) => list[Math.floor(random() * list.length)];
      const outcomes = [];
      const asked = (budgetMs) => outcomes.push(track(h.client.solve(modelRequest({ budgetMs }))));
      const story = [];
      await h.client.solve(modelRequest({ budgetMs: NORMAL })); // a worker that has worked
      for (let step = 0; step < 45; step += 1) {
        const move = pick(["normal", "hang", "hang", "fails", "aborts", "cancel", "cancel", "cancel", "crash", "die", "hold", "hold", "arrive", "arrive", "wait", "wait"]);
        story.push(move);
        if (move === "normal") asked(NORMAL);
        else if (move === "hang") asked(HANG);
        else if (move === "fails") asked(FAILS);
        else if (move === "aborts") asked(ABORTS);
        else if (move === "cancel") h.client.cancel();
        else if (move === "crash") h.workers.at(-1).crash();
        else if (move === "die") h.workers.at(-1).die();
        else if (move === "hold") worker.control.holdPings = true;
        else if (move === "arrive") {
          worker.control.holdPings = false;
          worker.arrive();
        } else await vi.advanceTimersByTimeAsync(pick([1, 300, 999, 1000, 1500, 5000, 7100]));
        await tick(Math.floor(random() * 40));
      }
      worker.control.holdPings = false;
      worker.arrive();
      for (let round = 0; round < 12; round += 1) {
        await vi.advanceTimersByTimeAsync(20_000);
        await tick(60);
      }
      expect(
        outcomes.filter((outcome) => outcome.state === "pending").length,
        `requests left waiting after: ${story.join(" ")}`,
      ).toBe(0);
      // The request after all that. A worker that died without a word before it had worked is not asked whether it is there (it has just said it was
      // ready), so the first request to it can end in the watchdog; that worker is dropped with it, and the request after that one is answered.
      const attempt = async () => {
        const outcome = track(h.client.solve(modelRequest({ budgetMs: NORMAL })));
        for (let round = 0; round < 10 && outcome.state === "pending"; round += 1) {
          await vi.advanceTimersByTimeAsync(LIVENESS_TIMEOUT_MS + 100);
          await tick(60);
        }
        return outcome;
      };
      let last = await attempt();
      if (last.state === "rejected" && last.error.code === "watchdog") last = await attempt();
      expect(last.state, `the request after: ${story.join(" ")} (${last.error?.code}: ${last.error?.message})`).toBe("resolved");
      await vi.advanceTimersByTimeAsync(600_000);
      expect(vi.getTimerCount()).toBe(0);
    });
  }

  // The same, with the questions to the visitor (answered late, or never until the end), starts that fail or hang in the compile, and a release that lands.
  const NEWER_RELEASE = parseManifest({ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, path: "/assets/engine/highs-FEDCBA9876543210.wasm", sha256: "fedcba9876543210".padEnd(64, "0") } });

  for (let seed = 1; seed <= 40; seed += 1) {
    it(`ends every request however the questions are answered, the starts go and a release lands (sequence ${seed})`, async () => {
      fakeTimers();
      const random = seeded(seed * 104729);
      const pick = (list) => list[Math.floor(random() * list.length)];
      const world = { start: "ok", released: false }; // how the next download goes, and whether a release has come since the page read its manifest
      const engine = fakeEngine();
      const load = engine.load.bind(engine);
      engine.load = async (args) => {
        if (args.module !== undefined) return load(args);
        if (world.start === "fail") throw new Error("the file did not load");
        args.onProgress({ phase: "loading", loaded: 50, total: 100 });
        if (world.start === "compile") {
          args.onProgress({ phase: "loading", loaded: 100, total: 100 });
          args.onProgress({ phase: "compiling" });
          return new Promise(() => {});
        }
        return load(args);
      };
      const questions = []; // the answers that the visitor has not given yet
      const ask = vi.fn(() => new Promise((resolve) => questions.push(resolve)));
      const h = makeHarness({ consent: { ask }, engine, workerManifest: () => (world.released ? NEWER_RELEASE : MANIFEST) });
      const outcomes = [];
      const story = [];
      for (let step = 0; step < 50; step += 1) {
        const move = pick(["normal", "normal", "hang", "cancel", "cancel", "crash", "die", "fail", "compile", "good", "release", "askConsent", "yes", "yes", "no", "wait", "wait", "late"]);
        story.push(move);
        if (move === "normal") outcomes.push(track(h.client.solve(modelRequest({ budgetMs: NORMAL }))));
        else if (move === "hang") outcomes.push(track(h.client.solve(modelRequest({ budgetMs: HANG }))));
        else if (move === "cancel") h.client.cancel();
        else if (move === "crash") h.workers.at(-1)?.crash();
        else if (move === "die") h.workers.at(-1)?.die();
        else if (move === "fail" || move === "compile") world.start = move;
        else if (move === "good") world.start = "ok";
        else if (move === "release") world.released = true;
        else if (move === "askConsent") outcomes.push(track(h.client.askConsent()));
        else if (move === "yes") questions.shift()?.(true);
        else if (move === "no") questions.shift()?.(false);
        else await vi.advanceTimersByTimeAsync(pick(move === "late" ? [STARTUP_COMPILE_MS + 1, WATCHDOG_GRACE_MS + 2000] : [1, 999, 1000, 7100]));
        await tick(Math.floor(random() * 40));
      }
      // the end: every question gets its answer, yes, and the time goes by
      world.start = "ok";
      for (let round = 0; round < 16; round += 1) {
        while (questions.length > 0) questions.shift()(true);
        await vi.advanceTimersByTimeAsync(20_000);
        await tick(60);
      }
      expect(outcomes.filter((outcome) => outcome.state === "pending").length, `left waiting after: ${story.join(" ")}`).toBe(0);
      if (h.client.consentState() === "declined" && !h.client.stats().updated) {
        const again = track(h.client.askConsent()); // the visitor asks for the optimizer again
        await tick(40);
        questions.shift()?.(true);
        await tick(40);
        expect(again.state, `the question again after: ${story.join(" ")}`).toBe("resolved");
      }
      const attempt = async () => {
        const outcome = track(h.client.solve(modelRequest({ budgetMs: NORMAL })));
        for (let round = 0; round < 12 && outcome.state === "pending"; round += 1) {
          while (questions.length > 0) questions.shift()(true);
          await vi.advanceTimersByTimeAsync(LIVENESS_TIMEOUT_MS + 100);
          await tick(60);
        }
        return outcome;
      };
      let last = await attempt();
      if (last.state === "rejected" && ["watchdog", "engine-load"].includes(last.error.code) && !h.client.stats().updated) last = await attempt();
      const detail = `${story.join(" ")} (${last.error?.code}: ${last.error?.message})`;
      if (h.client.stats().updated) {
        expect(last.state, detail).toBe("rejected");
        expect(last.error, detail).toMatchObject({ code: "engine-load", message: UPDATED });
      } else {
        expect(last.state, `the request after: ${detail}`).toBe("resolved");
      }
      await vi.advanceTimersByTimeAsync(600_000);
      expect(vi.getTimerCount()).toBe(0);
    });
  }
});

describe("the watchdog", () => {
  it("terminates a worker that does not answer, but only after the budget plus five seconds", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const h = makeHarness({ engine: fakeEngine({ hang: true }) });
    const request = track(h.client.solve(modelRequest({ budgetMs: 2000 })));
    await tick(80);
    expect(h.workers[0].sent.map((m) => m.type)).toEqual(["init", "solve"]);
    expect(WATCHDOG_GRACE_MS).toBe(5000);
    await vi.advanceTimersByTimeAsync(2000 + 5000 - 1);
    expect(request.state).toBe("pending");
    expect(h.workers[0].terminated).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await tick(10);
    expect(request.state).toBe("rejected");
    expect(request.error).toMatchObject({ code: "watchdog" });
    expect(h.workers[0].terminated).toBe(true);
  });

  it("does not run while a worker is being loaded, and stops when the answer comes", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const engine = fakeEngine();
    const load = engine.load.bind(engine);
    let release = null;
    engine.load = async (args) => {
      await new Promise((resolve) => (release = resolve)); // a slow download
      return load(args);
    };
    const h = makeHarness({ engine });
    const request = track(h.client.solve(modelRequest({ budgetMs: 1000 })));
    await tick(80);
    await vi.advanceTimersByTimeAsync(600_000); // ten minutes of loading: only a hang of the solve is the watchdog's business
    expect(request.state).toBe("pending");
    expect(h.workers[0].terminated).toBe(false);
    release();
    await tick(80);
    expect(request.state).toBe("resolved");
    await vi.advanceTimersByTimeAsync(600_000);
    expect(h.workers[0].terminated).toBe(false); // the answer cleared the timer
  });

  it("starts the next request on a new worker that reuses the compiled module", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const engine = fakeEngine({ hang: true });
    const h = makeHarness({ engine });
    const first = track(h.client.solve(modelRequest({ budgetMs: 100 })));
    await tick(80);
    const compiled = h.workers[0].delivered.find((m) => m.type === "ready").module;
    await vi.advanceTimersByTimeAsync(100 + 5000);
    await tick(10);
    expect(first.error).toMatchObject({ code: "watchdog" });

    engine.state.hang = false;
    const second = track(h.client.solve(modelRequest({ budgetMs: 100 })));
    await tick(80);
    expect(second.state).toBe("resolved");
    expect(h.workers).toHaveLength(2);
    expect(h.workers[1].sent[0].module).toBe(compiled);
    expect(engine.calls.filter((c) => c.type === "load").map((c) => c.hadModule)).toEqual([false, true]);
  });

  it("gives a request a new window at every report of progress: a worker that keeps reporting is not a hang", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    // the window is the budget and five seconds: six; the worker reports every four seconds for twenty, and then answers
    const h = makeHarness({ engine: fakeEngine({ beat: { every: 4000, times: 5 } }) });
    const request = track(h.client.solve(modelRequest({ budgetMs: 1000 })));
    await tick(80);
    await vi.advanceTimersByTimeAsync(19_999);
    expect(request.state).toBe("pending");
    expect(h.workers[0].terminated).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await tick(20);
    expect(request.state).toBe("resolved");
    expect(h.workers[0].terminated).toBe(false);
    expect(h.client.stats()).toMatchObject({ spawns: 1 });
  });

  it("stops a worker that has gone quiet one window after its last report, not after the first window", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    // it reports at 4, 8 and 12 seconds and then hangs: stopped at 12 + 6 = 18 seconds
    const h = makeHarness({ engine: fakeEngine({ beat: { every: 4000, times: 3 }, hang: true }) });
    const request = track(h.client.solve(modelRequest({ budgetMs: 1000 })));
    await tick(80);
    await vi.advanceTimersByTimeAsync(12_000 + 6000 - 1);
    expect(request.state).toBe("pending");
    expect(h.workers[0].terminated).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await tick(10);
    expect(request.error).toMatchObject({ code: "watchdog" });
    expect(h.workers[0].terminated).toBe(true);
  });

  it("gives every request its own budget plus five seconds", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const engine = fakeEngine();
    const h = makeHarness({ engine });
    await tick(1);
    const quick = track(h.client.solve(modelRequest({ budgetMs: 100 })));
    await tick(80);
    expect(quick.state).toBe("resolved");
    engine.state.hang = true;
    const slow = track(h.client.solve(modelRequest({ budgetMs: 60_000 })));
    await tick(80);
    await vi.advanceTimersByTimeAsync(64_999);
    expect(slow.state).toBe("pending");
    await vi.advanceTimersByTimeAsync(1);
    await tick(10);
    expect(slow.error).toMatchObject({ code: "watchdog" });
  });
});

describe("the limits on starting the optimizer", () => {
  const fakeTimers = () => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

  it("names its limits in one place: 20 seconds without a byte, a minute for the compile and the start once the last byte is in", () => {
    expect(STARTUP_STALL_MS).toBe(20_000);
    expect(STARTUP_COMPILE_MS).toBe(60_000);
  });

  it("does not give up a download that keeps delivering, however long it takes: ten minutes of progress, and then the answer", async () => {
    fakeTimers();
    const engine = fakeEngine();
    const load = engine.load.bind(engine);
    engine.load = async (args) => {
      for (let loaded = 1; loaded <= 120; loaded += 1) {
        args.onProgress({ phase: "loading", loaded, total: 1000 }); // always something arriving
        await new Promise((resolve) => setTimeout(resolve, 5000)); // 120 times 5 seconds: ten minutes
      }
      return load(args);
    };
    const h = makeHarness({ engine });
    const request = track(h.client.solve(modelRequest()));
    await tick(80);
    await vi.advanceTimersByTimeAsync(600_000 - 1);
    expect(request.state).toBe("pending");
    expect(h.workers[0].terminated).toBe(false);
    await vi.advanceTimersByTimeAsync(5000);
    await tick(80);
    expect(request.state).toBe("resolved");
    expect(h.workers[0].terminated).toBe(false);
    expect(h.client.stats().moduleKept).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  /** An engine that has its file and then hangs in `phase`: it reports the last byte, and the compiling or the starting, and never finishes. */
  function hangsAfterTheDownload(engine, phase) {
    engine.load = async ({ onProgress }) => {
      onProgress({ phase: "loading", loaded: 100, total: 100 });
      onProgress({ phase });
      await new Promise(() => {});
    };
  }

  for (const phase of ["compiling", "starting"]) {
    it(`gives up a ${phase === "compiling" ? "compile" : "start of the solver"} that hangs past the limit for it, which starts when the last byte is in`, async () => {
      fakeTimers();
      const engine = fakeEngine();
      hangsAfterTheDownload(engine, phase);
      const h = makeHarness({ engine });
      const request = track(h.client.solve(modelRequest()));
      await tick(80);
      await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS - 1);
      expect(request.state).toBe("pending");
      expect(h.workers[0].terminated).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      await tick(10);
      expect(request.state).toBe("rejected");
      expect(request.error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/too long|took longer/i) });
      expect(h.workers[0].terminated).toBe(true);
      expect(h.client.stats().moduleKept).toBe(false);
      expect(vi.getTimerCount()).toBe(0);
    });
  }

  it("counts the minute from the last byte, not from the start: a download of ten minutes is followed by a whole minute for the compile", async () => {
    fakeTimers();
    const engine = fakeEngine();
    engine.load = async ({ onProgress }) => {
      for (let loaded = 1; loaded <= 120; loaded += 1) {
        onProgress({ phase: "loading", loaded, total: 1000 });
        await new Promise((resolve) => setTimeout(resolve, 5000));
      }
      onProgress({ phase: "loading", loaded: 1000, total: 1000 });
      onProgress({ phase: "compiling" });
      await new Promise(() => {});
    };
    const h = makeHarness({ engine });
    const request = track(h.client.solve(modelRequest()));
    await tick(80);
    await vi.advanceTimersByTimeAsync(600_000);
    await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS - 1);
    expect(request.state).toBe("pending");
    await vi.advanceTimersByTimeAsync(1);
    await tick(10);
    expect(request.error).toMatchObject({ code: "engine-load" });
    expect(h.workers[0].terminated).toBe(true);
  });

  it("gives a worker that has no download to do (it is given the kept module) the same minute, from the start", async () => {
    fakeTimers();
    const engine = fakeEngine();
    const load = engine.load.bind(engine);
    let hang = false;
    engine.load = (args) => (hang ? new Promise(() => {}) : load(args));
    const h = makeHarness({ engine });
    await h.client.solve(modelRequest({ budgetMs: 1000 })); // the module is kept
    h.workers[0].crash();
    hang = true;
    const request = track(h.client.solve(modelRequest({ budgetMs: 1000 })));
    await tick(80);
    expect(h.workers[1].sent[0].module).toBeDefined();
    await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS - 1);
    expect(request.state).toBe("pending");
    await vi.advanceTimersByTimeAsync(1);
    await tick(10);
    expect(request.error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/too long|took longer/i) });
    expect(h.workers[1].terminated).toBe(true);
  });

  it("lets the next request start again after a start-up that was given up", async () => {
    fakeTimers();
    const engine = fakeEngine();
    const load = engine.load.bind(engine);
    hangsAfterTheDownload(engine, "compiling");
    const ask = vi.fn(async () => true);
    const h = makeHarness({ engine, consent: { ask } });
    const first = track(h.client.solve(modelRequest()));
    await tick(80);
    await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS);
    await tick(10);
    expect(first.error).toMatchObject({ code: "engine-load" });
    expect(h.client.consentState()).toBe("unknown"); // the yes does not start the next download by itself: the next request asks again
    engine.load = load; // the next worker's engine works
    const second = track(h.client.solve(modelRequest()));
    await tick(80);
    expect(second.state).toBe("resolved");
    expect(h.workers).toHaveLength(2);
    expect(ask).toHaveBeenCalledTimes(2);
    expect(h.client.consentState()).toBe("granted");
  });

  it("clears the limits when the optimizer is ready: nothing is left to stop a worker that works", async () => {
    fakeTimers();
    const h = makeHarness();
    await h.client.solve(modelRequest({ budgetMs: 1000 }));
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS * 3);
    expect(h.workers[0].terminated).toBe(false);
  });

  it("does not wait for the list of files for ever: a request for it that is not answered ends in unavailable, and the next one asks again", async () => {
    fakeTimers();
    const asked = [];
    const dom = new JSDOM("<!doctype html><main id='main'></main>", { url: "https://trioforge.test/" });
    const workers = [];
    const answers = [
      () => new Promise(() => {}), // never answered
      () => Promise.resolve({ ok: true, status: 200, text: () => new Promise(() => {}) }), // answered, and the body never ends
      () => Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(MANIFEST_JSON) }),
    ];
    const client = createEngineClient({
      window: dom.window,
      document: dom.window.document,
      fetch: (url, init) => {
        asked.push({ url: String(url), signal: init?.signal });
        return answers[Math.min(asked.length - 1, answers.length - 1)]();
      },
      createWorker: (url) => {
        const worker = new FakeWorker(url, { core: makeCore(fakeEngine()) });
        workers.push(worker);
        return worker;
      },
      consent: { ask: async () => true },
      trustedTypes: null,
    });
    for (let i = 0; i < 2; i += 1) {
      const request = track(client.solve(modelRequest()));
      await tick(40);
      await vi.advanceTimersByTimeAsync(STARTUP_STALL_MS - 1);
      expect(request.state, `before the limit (${i})`).toBe("pending");
      await vi.advanceTimersByTimeAsync(1);
      await tick(10);
      expect(request.error, `at the limit (${i})`).toMatchObject({ code: "unavailable" });
      expect(asked[i].signal.aborted).toBe(true); // and the request itself was stopped, not only no longer waited for
    }
    expect(workers).toHaveLength(0);
    const third = track(client.solve(modelRequest()));
    await tick(80);
    expect(third.state).toBe("resolved");
  });

  it("reads the list of files in the worker with the same limit", async () => {
    fakeTimers();
    let signal;
    const never = (url, init) => {
      signal = init?.signal;
      return new Promise(() => {});
    };
    const reading = track(readManifest({ fetchImpl: never, base: "https://trioforge.test/assets/engine/worker-BBBBBBBB.js" }));
    await tick(20);
    await vi.advanceTimersByTimeAsync(STARTUP_STALL_MS - 1);
    expect(reading.state).toBe("pending");
    await vi.advanceTimersByTimeAsync(1);
    await tick(10);
    expect(reading.state).toBe("rejected");
    expect(reading.error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/did not arrive|in time/i) });
    expect(signal.aborted).toBe(true);
    // and it reads the file when it does arrive, from the manifest's fixed address
    const asked = [];
    const fine = await readManifest({
      fetchImpl: async (url) => {
        asked.push(String(url));
        return { ok: true, status: 200, text: async () => JSON.stringify(MANIFEST_JSON) };
      },
      base: "https://trioforge.test/assets/engine/worker-BBBBBBBB.js",
    });
    expect(asked).toEqual(["https://trioforge.test/engine-manifest.json"]);
    expect(fine.worker.path).toBe(WORKER_PATH);
  });

  it("fetchTextWithin ends the wait even for a fetch that ignores the abort, and says why", async () => {
    fakeTimers();
    const outcome = track(fetchTextWithin(() => new Promise(() => {}), "/x", {}, 1000));
    await tick(10);
    await vi.advanceTimersByTimeAsync(1000);
    await tick(10);
    expect(outcome.value).toEqual({ state: "timeout" });
    expect(await fetchTextWithin(async () => ({ ok: false, status: 503, text: async () => "" }), "/x", {}, 1000)).toEqual({ state: "status", status: 503 });
    expect(
      await fetchTextWithin(async () => {
        throw new TypeError("offline");
      }, "/x", {}, 1000),
    ).toEqual({ state: "failed" });
    expect(await fetchTextWithin(async () => ({ ok: true, status: 200, text: async () => "hello" }), "/x", {}, 1000)).toEqual({ state: "ok", text: "hello" });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("reads the list of files in the worker with a request that says no-cache, as the page's does", async () => {
    const inits = [];
    await readManifest({
      fetchImpl: async (url, init) => {
        inits.push(init);
        return { ok: true, status: 200, text: async () => JSON.stringify(MANIFEST_JSON) };
      },
      base: "https://trioforge.test/assets/engine/worker-BBBBBBBB.js",
    });
    expect(inits).toHaveLength(1);
    expect(inits[0]).toMatchObject({ cache: "no-cache", credentials: "same-origin" });
  });

  describe("fetchTextWithin and a signal the caller passes", () => {
    it("ends the wait at once when the caller aborts, even for a fetch that takes no notice, and the request itself is aborted", async () => {
      fakeTimers();
      const outer = new AbortController();
      let given;
      const fetchImpl = (url, init) => {
        given = init.signal;
        return new Promise(() => {});
      };
      const outcome = track(fetchTextWithin(fetchImpl, "/x", { signal: outer.signal }, 60_000));
      await tick(10);
      expect(outcome.state).toBe("pending");
      expect(given).not.toBe(outer.signal); // the stall controller's own signal, which the caller's feeds
      outer.abort();
      await tick(10);
      expect(outcome.value).toEqual({ state: "failed" });
      expect(given.aborted).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("also ends the wait when the abort comes while the body is being read", async () => {
      fakeTimers();
      const outer = new AbortController();
      const fetchImpl = async () => ({ ok: true, status: 200, text: () => new Promise(() => {}) });
      const outcome = track(fetchTextWithin(fetchImpl, "/x", { signal: outer.signal }, 60_000));
      await tick(10);
      outer.abort();
      await tick(10);
      expect(outcome.value).toEqual({ state: "failed" });
      expect(vi.getTimerCount()).toBe(0);
    });

    it("fails at once for a signal that has been aborted already, and still hands the fetch an aborted signal", async () => {
      fakeTimers();
      const outer = new AbortController();
      outer.abort();
      let given;
      const outcome = await fetchTextWithin(
        (url, init) => {
          given = init.signal;
          return new Promise(() => {});
        },
        "/x",
        { signal: outer.signal },
        60_000,
      );
      expect(outcome).toEqual({ state: "failed" });
      expect(given === undefined || given.aborted).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("keeps its own stall limit beside the caller's signal, and the stall does not abort the caller's signal", async () => {
      fakeTimers();
      const outer = new AbortController();
      let given;
      const outcome = track(
        fetchTextWithin(
          (url, init) => {
            given = init.signal;
            return new Promise(() => {});
          },
          "/x",
          { signal: outer.signal, credentials: "same-origin", cache: "no-cache" },
          1000,
        ),
      );
      await tick(10);
      await vi.advanceTimersByTimeAsync(1000);
      await tick(10);
      expect(outcome.value).toEqual({ state: "timeout" });
      expect(given.aborted).toBe(true);
      expect(outer.signal.aborted).toBe(false);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("lets go of the caller's signal when it is done, and passes the other fields of the init on", async () => {
      const outer = new AbortController();
      const added = [];
      const removed = [];
      const real = outer.signal;
      const watched = new Proxy(real, {
        get(target, key) {
          if (key === "addEventListener") return (type, listener, options) => (added.push(type), target.addEventListener(type, listener, options));
          if (key === "removeEventListener") return (type, listener, options) => (removed.push(type), target.removeEventListener(type, listener, options));
          const value = Reflect.get(target, key, target);
          return typeof value === "function" ? value.bind(target) : value;
        },
      });
      let seen;
      const outcome = await fetchTextWithin(
        async (url, init) => {
          seen = init;
          return { ok: true, status: 200, text: async () => "hello" };
        },
        "/x",
        { signal: watched, credentials: "omit", cache: "no-cache" },
        1000,
      );
      expect(outcome).toEqual({ state: "ok", text: "hello" });
      expect(seen).toMatchObject({ credentials: "omit", cache: "no-cache" });
      expect(added).toEqual(["abort"]);
      expect(removed).toEqual(["abort"]); // nothing is left on a signal that lives on
    });
  });
});

describe("a worker that has died without a word", () => {
  const fakeTimers = () => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

  it("is noticed by the next request, which starts a new worker from the kept module instead of posting into the void", async () => {
    fakeTimers();
    const h = makeHarness();
    await h.client.solve(modelRequest({ budgetMs: 1000 }));
    const compiled = h.workers[0].delivered.find((m) => m.type === "ready").module;
    h.workers[0].die(); // self.close(), or the browser stopped it: no message, no error event
    const next = track(h.client.solve(modelRequest({ budgetMs: 1000 })));
    await tick(60);
    expect(next.state).toBe("pending");
    expect(h.workers[0].sent.map((m) => m.type)).toEqual(["init", "solve", "ping"]); // the request was not posted to the dead worker
    await vi.advanceTimersByTimeAsync(LIVENESS_TIMEOUT_MS - 1);
    expect(next.state).toBe("pending");
    await vi.advanceTimersByTimeAsync(1);
    await tick(80);
    expect(next.state).toBe("resolved"); // long before the watchdog (budget plus 5 seconds) would have said anything
    expect(h.workers).toHaveLength(2);
    expect(h.workers[0].terminated).toBe(true);
    expect(h.workers[1].sent[0].module).toBe(compiled); // started from the kept module, so nothing was downloaded again
    expect(h.workers[1].sent.map((m) => m.type)).toEqual(["init", "solve"]);
    expect(h.client.stats()).toMatchObject({ spawns: 2, moduleKept: true });
    expect(h.client.consentState()).toBe("granted");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("is noticed again after the replacement dies, and the requests after it go on as usual", async () => {
    fakeTimers();
    const h = makeHarness();
    for (let round = 0; round < 3; round += 1) {
      const request = track(h.client.solve(modelRequest({ budgetMs: 1000 })));
      await tick(60);
      await vi.advanceTimersByTimeAsync(LIVENESS_TIMEOUT_MS);
      await tick(60);
      expect(request.state, `round ${round}`).toBe("resolved");
      h.workers.at(-1).die();
    }
    expect(h.workers).toHaveLength(3);
  });

  it("does not ask a worker that has not worked yet whether it is alive, and asks one that has, which answers at once", async () => {
    fakeTimers();
    const h = makeHarness();
    await h.client.solve(modelRequest({ budgetMs: 1000 }));
    expect(h.workers[0].sent.map((m) => m.type)).toEqual(["init", "solve"]); // it has just said it was ready
    await h.client.solve(modelRequest({ budgetMs: 1000 }));
    expect(h.workers[0].sent.map((m) => m.type)).toEqual(["init", "solve", "ping", "solve"]);
    expect(h.workers).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0); // the question and its limit are gone with the answer
  });

  it("gives the request to a worker that answers the question late, as long as it is within the limit", async () => {
    fakeTimers();
    const slow = (message, reply, worker) => {
      if (message.type === "init") reply({ v: 1, type: "ready", highs: "1.15.1", wasm: WASM_SHA, module: new WebAssembly.Module(EMPTY_MODULE_BYTES) });
      else if (message.type === "ping") setTimeout(() => reply({ v: 1, type: "pong" }), LIVENESS_TIMEOUT_MS - 100);
      else if (message.type === "solve") reply({ v: 1, type: "result", id: message.id, kind: "model", status: "optimal", proven: true, objective: 1, x: new Array(message.request.model.c.length).fill(0), bound: 1, gap: 0, nodes: 0, elapsedMs: 1, label: null });
    };
    const h = makeHarness({ script: slow });
    await h.client.solve(modelRequest());
    const second = track(h.client.solve(modelRequest()));
    await tick(60);
    await vi.advanceTimersByTimeAsync(LIVENESS_TIMEOUT_MS - 100);
    await tick(60);
    expect(second.state).toBe("resolved");
    expect(h.workers).toHaveLength(1);
  });

  it("stops asking when the request is cancelled meanwhile, and the request is not posted to anything", async () => {
    fakeTimers();
    const h = makeHarness();
    await h.client.solve(modelRequest({ budgetMs: 1000 }));
    h.workers[0].die();
    const next = track(h.client.solve(modelRequest({ budgetMs: 1000 })));
    await tick(60);
    h.client.cancel();
    await tick(20);
    expect(next.error).toMatchObject({ code: "cancelled" });
    await vi.advanceTimersByTimeAsync(LIVENESS_TIMEOUT_MS * 3);
    await tick(20);
    expect(h.workers[0].sent.filter((m) => m.type === "solve")).toHaveLength(1);
    expect(h.workers).toHaveLength(1); // nobody started a worker for a request that was cancelled
    // the dead worker was dropped when its time ran out, so the next request starts a new one
    const after = await h.client.solve(modelRequest({ budgetMs: 1000 }));
    expect(after.status).toBe("optimal");
    expect(h.workers).toHaveLength(2);
  });

  it("replaces a worker the page cannot even post the question to", async () => {
    const h = makeHarness();
    await h.client.solve(modelRequest());
    const original = h.workers[0].postMessage.bind(h.workers[0]);
    h.workers[0].postMessage = (data) => {
      if (data.type === "ping") throw new Error("the worker is gone");
      return original(data);
    };
    await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(h.workers).toHaveLength(2);
    expect(h.workers[0].terminated).toBe(true);
  });

  it("answers the question in every state of the worker, with nothing but the version and the type", async () => {
    const posted = [];
    const core = createWorkerCore({ post: (m) => posted.push(m), loadManifest: async () => MANIFEST, loadEngine: (args) => fakeEngine().load(args), now: () => 0 });
    await core.handle({ v: 1, type: "ping" }); // before init
    await core.handle({ v: 1, type: "init" });
    await core.handle({ v: 1, type: "ping" }); // after
    expect(posted.filter((m) => m.type === "pong")).toEqual([{ v: 1, type: "pong" }, { v: 1, type: "pong" }]);
    await core.handle({ v: 1, type: "ping", id: 1 }); // a question with a field it should not have is refused, not answered
    expect(posted.at(-1)).toMatchObject({ type: "error", code: "bad-request" });
  });

  it("is a message both sides know: ping to the worker, pong back, and nothing else in them", () => {
    expect(validateToWorker({ v: 1, type: "ping" })).toEqual({ v: 1, type: "ping" });
    expect(() => validateToWorker({ v: 1, type: "ping", url: "/x" })).toThrow(/bad-request/);
    expect(validateFromWorker({ v: 1, type: "pong" })).toEqual({ v: 1, type: "pong" });
    expect(() => validateFromWorker({ v: 1, type: "pong", id: 1 })).toThrow(/protocol/);
    expect(() => validateFromWorker({ v: 2, type: "pong" })).toThrow(/protocol/);
  });

  it("treats a pong nobody asked for as a worker that is not to be trusted", async () => {
    const h = makeHarness();
    await h.client.solve(modelRequest());
    h.workers[0].reply({ v: 1, type: "pong" });
    await tick(10);
    expect(h.workers[0].terminated).toBe(true);
    await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(h.workers).toHaveLength(2);
  });
});

// ---- Trusted Types in the client ---------------------------------------------------------------------------------------------

describe("starting the worker", () => {
  it("makes the worker address with the policy when the browser has Trusted Types, and passes that object on as it is", async () => {
    const issued = [];
    const trustedTypes = {
      createPolicy: (name, rules) => ({
        createScriptURL: (input) => {
          const trusted = { name, address: rules.createScriptURL(input) };
          issued.push(trusted);
          return trusted;
        },
      }),
    };
    const h = makeHarness({ trustedTypes });
    await h.client.solve(modelRequest());
    expect(issued).toEqual([{ name: "trioforge", address: WORKER_PATH }]);
    expect(h.workers[0].url).toBe(issued[0]);
  });

  it("starts the worker with the plain, checked path when there is no Trusted Types", async () => {
    const h = makeHarness({ trustedTypes: null });
    await h.client.solve(modelRequest());
    expect(h.workers[0].url).toBe(WORKER_PATH);
  });

  it("says the browser is unsupported when the policy cannot be made", async () => {
    const trustedTypes = {
      createPolicy() {
        throw new TypeError("Policy with name trioforge disallowed.");
      },
    };
    const h = makeHarness({ trustedTypes });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "unsupported" });
    expect(h.workers).toHaveLength(0);
  });

  it("builds a module worker with a name when it makes the worker itself", async () => {
    const made = [];
    class FakeBrowserWorker {
      constructor(url, options) {
        made.push({ url, options });
        this.postMessage = () => {};
        this.terminate = () => {};
      }
    }
    const dom = new JSDOM("<!doctype html><main id='main'></main>", { url: "https://trioforge.test/" });
    dom.window.Worker = FakeBrowserWorker;
    const client = createEngineClient({
      window: dom.window,
      document: dom.window.document,
      fetch: async () => ({ ok: true, status: 200, text: async () => JSON.stringify(MANIFEST_JSON) }),
      consent: { ask: async () => true },
      trustedTypes: null,
    });
    const started = track(client.solve(modelRequest()));
    await tick(80);
    expect(made).toEqual([{ url: WORKER_PATH, options: { type: "module", name: "trioforge-engine" } }]);
    client.cancel();
    await tick(10);
    expect(started.error).toMatchObject({ code: "cancelled" });
  });

  it("reports a browser with no Web Workers or WebAssembly before it asks anything", async () => {
    const dom = new JSDOM("<!doctype html><main id='main'></main>", { url: "https://trioforge.test/" });
    delete dom.window.Worker;
    const ask = vi.fn(async () => true);
    const client = createEngineClient({ window: dom.window, document: dom.window.document, fetch: async () => ({ ok: false }), consent: { ask }, trustedTypes: null });
    await expect(client.solve(modelRequest())).rejects.toMatchObject({ code: "unsupported" });
    expect(ask).not.toHaveBeenCalled();
  });

  it("reports a manifest that cannot be read, and reads it again for the next request", async () => {
    const answers = [
      { ok: true, status: 200, text: async () => "<!doctype html><title>TrioForge</title>" }, // what Pages sends for an unknown path
      { ok: false, status: 500, text: async () => "Server error" },
      { ok: true, status: 200, text: async () => JSON.stringify({ ...MANIFEST_JSON, version: 9 }) },
      { ok: true, status: 200, text: async () => "x".repeat(LIMITS.maxManifestBytes + 1) },
      { ok: true, status: 200, text: async () => JSON.stringify(MANIFEST_JSON) },
    ];
    const asked = [];
    const dom = new JSDOM("<!doctype html><main id='main'></main>", { url: "https://trioforge.test/" });
    const workers = [];
    const client = createEngineClient({
      window: dom.window,
      document: dom.window.document,
      fetch: async (url) => {
        asked.push(String(url));
        return answers.shift();
      },
      createWorker: (url) => {
        const worker = new FakeWorker(url, { core: makeCore(fakeEngine()) });
        workers.push(worker);
        return worker;
      },
      consent: { ask: async () => true },
      trustedTypes: null,
    });
    for (let i = 0; i < 4; i += 1) {
      await expect(client.solve(modelRequest())).rejects.toMatchObject({ code: "unavailable" });
      expect(workers).toHaveLength(0);
    }
    await expect(client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(asked).toEqual(new Array(5).fill("/engine-manifest.json")); // a failure is not remembered
  });

  it("gives every part of a page the same client, so that there is one worker and one question", async () => {
    const dom = new JSDOM("<!doctype html><main id='main'></main>", { url: "https://trioforge.test/" });
    const workers = [];
    const options = {
      window: dom.window,
      document: dom.window.document,
      fetch: async () => ({ ok: true, status: 200, text: async () => JSON.stringify(MANIFEST_JSON) }),
      createWorker: (url) => {
        const worker = new FakeWorker(url, { core: makeCore(fakeEngine()) });
        workers.push(worker);
        return worker;
      },
      consent: { ask: async () => true },
      trustedTypes: null,
    };
    forgetEngineClient();
    const upgrade = getEngineClient(options);
    const sliders = getEngineClient({ ...options, consent: { ask: async () => false } }); // options of a later call are not used
    expect(sliders).toBe(upgrade);
    await upgrade.solve(modelRequest());
    await sliders.solve(modelRequest());
    expect(workers).toHaveLength(1);
    forgetEngineClient();
    expect(workers[0].terminated).toBe(true);
    expect(getEngineClient(options)).not.toBe(upgrade);
    forgetEngineClient();
  });

  it("reads the manifest once for the whole session", async () => {
    const h = makeHarness();
    await h.client.solve(modelRequest());
    await h.client.solve(modelRequest());
    expect(h.fetchCalls).toEqual(["/engine-manifest.json"]);
  });

  /** A client whose manifest requests are answered by `answers` (a function per request, the last one repeating); `inits` records what each request was given. */
  function manifestClient(answers) {
    const dom = new JSDOM("<!doctype html><main id='main'></main>", { url: "https://trioforge.test/" });
    const inits = [];
    const workers = [];
    const client = createEngineClient({
      window: dom.window,
      document: dom.window.document,
      fetch: (url, init) => {
        inits.push(init);
        return answers[Math.min(inits.length - 1, answers.length - 1)]();
      },
      createWorker: (url) => {
        const worker = new FakeWorker(url, { core: makeCore(fakeEngine()) });
        workers.push(worker);
        return worker;
      },
      consent: { ask: async () => true },
      trustedTypes: null,
    });
    return { client, inits, workers };
  }
  const goodManifest = () => Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(MANIFEST_JSON) });

  it("remembers no failure of the manifest read, however it failed: the next request asks again", async () => {
    const failures = {
      "a request that throws at once": () => {
        throw new TypeError("network down");
      },
      "a request that is rejected": () => Promise.reject(new TypeError("network down")),
      "a body that cannot be read": () => Promise.resolve({ ok: true, status: 200, text: () => Promise.reject(new TypeError("the body broke")) }),
      "an answer of 503": () => Promise.resolve({ ok: false, status: 503, text: async () => "later" }),
      "text that is not JSON": () => Promise.resolve({ ok: true, status: 200, text: async () => "<!doctype html>" }),
    };
    const { client, inits, workers } = manifestClient([...Object.values(failures), goodManifest]);
    let asked = 0;
    for (const name of Object.keys(failures)) {
      await expect(client.solve(modelRequest()), name).rejects.toMatchObject({ code: "unavailable" });
      asked += 1;
      expect(inits, `${name}: asked again by every request`).toHaveLength(asked);
    }
    expect(workers).toHaveLength(0);
    await expect(client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(inits).toHaveLength(asked + 1);
    await client.solve(modelRequest());
    expect(inits).toHaveLength(asked + 1); // and once it is read it is kept
  });

  it("shares a read that is under way with the question for the optimizer, and the next of either asks again when it failed", async () => {
    let fail;
    const pending = () => new Promise((_, reject) => (fail = reject));
    const { client, inits } = manifestClient([pending, goodManifest]);
    const request = track(client.solve(modelRequest()));
    const question = track(client.askConsent());
    await tick(40);
    expect(inits).toHaveLength(1); // one read for both
    fail(new TypeError("network down"));
    await tick(40);
    expect(request.error).toMatchObject({ code: "unavailable" });
    expect(question.error).toMatchObject({ code: "unavailable" });
    await expect(client.askConsent()).resolves.toBe(true);
    expect(inits).toHaveLength(2);
  });

  it("asks the server whether its copy of the manifest is current, whatever the host sends: the init of the request says no-cache", async () => {
    const { client, inits } = manifestClient([goodManifest]);
    await client.solve(modelRequest());
    expect(inits).toHaveLength(1);
    expect(inits[0]).toMatchObject({ cache: "no-cache", credentials: "same-origin" });
  });
});

// ---- consent -----------------------------------------------------------------------------------------------------------------

describe("consent", () => {
  it("asks once per session before the first download, and not again once it is given", async () => {
    const ask = vi.fn(async () => true);
    const h = makeHarness({ consent: { ask } });
    await h.client.solve(modelRequest());
    await h.client.solve(modelRequest());
    expect(ask).toHaveBeenCalledTimes(1);
    expect(ask.mock.calls[0][0]).toMatchObject({ megabytes: Number(MEGABYTES), warnings: [] });
    expect(h.client.consentState()).toBe("granted");
  });

  it("keeps the precomputed answers when the visitor declines: nothing is downloaded and the request says why", async () => {
    const ask = vi.fn(async () => false);
    const h = makeHarness({ consent: { ask } });
    const declined = h.client.solve(modelRequest());
    await expect(declined).rejects.toBeInstanceOf(EngineError);
    await expect(declined).rejects.toMatchObject({ code: "declined" });
    expect(h.workers).toHaveLength(0);
    expect(h.client.consentState()).toBe("declined");
    // asking again by itself would nag at every slider move: the answer stands until the visitor asks for the optimizer
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "declined" });
    expect(ask).toHaveBeenCalledTimes(1);
    expect(h.workers).toHaveLength(0);
  });

  it("asks again when the visitor presses the button that offers the optimizer, and goes on if they accept", async () => {
    const answers = [false, true];
    const ask = vi.fn(async () => answers.shift());
    const h = makeHarness({ consent: { ask } });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "declined" });
    await expect(h.client.askConsent()).resolves.toBe(true);
    expect(ask).toHaveBeenCalledTimes(2);
    expect(h.client.consentState()).toBe("granted");
    await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    await expect(h.client.askConsent()).resolves.toBe(true); // already given: no question
    expect(ask).toHaveBeenCalledTimes(2);
  });

  it("asks one question however many requests are waiting for the answer", async () => {
    let answer = null;
    const ask = vi.fn(() => new Promise((resolve) => (answer = resolve)));
    const h = makeHarness({ consent: { ask } });
    const outcomes = [1, 2, 3].map(() => track(h.client.solve(modelRequest())));
    await tick(80);
    expect(ask).toHaveBeenCalledTimes(1);
    answer(false);
    await tick(80);
    expect(outcomes.map((o) => o.error?.code)).toEqual(["declined", "declined", "declined"]);
  });

  describe("the question on the page", () => {
    const READY_PAGE = '<!doctype html><html><body><header><button id="before">before</button></header><main id="main"><button id="start">Start</button></main></body></html>';

    async function screenOf(h, selector) {
      return vi.waitFor(() => {
        const element = h.document.querySelector(selector);
        expect(element, selector).not.toBeNull();
        return element;
      });
    }

    it("shows Load the optimizer (about N MB), with N from the manifest, on a browser that tells nothing about itself", async () => {
      const h = makeHarness({ consent: null, navigator: {}, markup: READY_PAGE });
      const outcome = track(h.client.solve(modelRequest()));
      const accept = await screenOf(h, '[data-action="accept"]');
      expect(accept.tagName).toBe("BUTTON");
      expect(accept.textContent).toBe(`Load the optimizer (about ${MEGABYTES} MB)`);
      expect(h.document.querySelector('[data-action="decline"]').textContent).toBe("Not now");
      expect(h.document.querySelector(".engine-consent-warning")).toBeNull();
      expect(h.workers).toHaveLength(0); // nothing is downloaded before the click
      expect(outcome.state).toBe("pending");
      accept.click();
      await vi.waitFor(() => expect(outcome.state).toBe("resolved"));
      expect(h.workers).toHaveLength(1);
      expect(h.document.querySelector(".engine-consent")).toBeNull(); // the panel goes away when the optimizer is ready
    });

    it("moves the keyboard focus to the question, never to a button, and back to where it was when the question is closed", async () => {
      const h = makeHarness({ consent: null, navigator: {}, markup: READY_PAGE });
      h.document.getElementById("start").focus();
      const outcome = track(h.client.solve(modelRequest()));
      const accept = await screenOf(h, '[data-action="accept"]');
      const panel = h.document.querySelector(".engine-consent");
      expect(h.document.activeElement).toBe(panel); // the question itself: a key meant for the page cannot press a button
      expect(panel.getAttribute("tabindex")).toBe("-1"); // reachable by script and by a click, not a stop of its own in the tab order
      expect(h.document.activeElement).not.toBe(accept);
      expect(h.document.activeElement.tagName).not.toBe("BUTTON");
      h.document.querySelector('[data-action="decline"]').click();
      await vi.waitFor(() => expect(outcome.state).toBe("rejected"));
      expect(h.document.activeElement).toBe(h.document.getElementById("start"));
      expect(h.document.querySelector(".engine-consent")).toBeNull();
    });

    /**
     * What a browser does with a key, as far as buttons go: Enter presses the focused button when the key goes down (again for each repeat of a key that is held),
     * Space when it comes up, if the button had the focus when it went down. The event goes to the focused element, as it does in a browser.
     */
    function press(win, key, { repeat = false } = {}) {
      const doc = win.document;
      const target = doc.activeElement ?? doc.body;
      const down = new win.KeyboardEvent("keydown", { key, repeat, bubbles: true, cancelable: true });
      if (!target.dispatchEvent(down)) return;
      if (key === "Enter" && target.tagName === "BUTTON") target.click();
      if (key === " ") {
        target.dispatchEvent(new win.KeyboardEvent("keyup", { key, bubbles: true, cancelable: true }));
        if (target.tagName === "BUTTON" && doc.activeElement === target) target.click();
      }
    }

    const KEY_PAGE =
      '<!doctype html><html><body><main id="main"><input id="field" aria-label="gear"><button id="start" type="button">Optimize</button></main></body></html>';

    for (const starter of ["field", "start"]) {
      it(`is not accepted by a key meant for something else: Enter, Space or a held Enter, just before and while the question opens (started from ${starter})`, async () => {
        const h = makeHarness({ consent: null, navigator: {}, markup: KEY_PAGE });
        const win = h.dom.window;
        const asked = [];
        const begin = () => asked.push(track(h.client.solve(modelRequest())));
        h.document.getElementById("field").addEventListener("keydown", (event) => event.key === "Enter" && begin());
        h.document.getElementById("start").addEventListener("click", begin);
        h.document.getElementById(starter).focus();
        press(win, "Enter"); // starts a request: the question is not there yet
        press(win, "Enter", { repeat: true }); // the key is held, and repeats into the same place until the question has opened
        await screenOf(h, '[data-action="accept"]');
        // the question is open now. The key that is still down repeats, and the visitor presses Enter and Space again, meaning the page
        for (const [key, repeat] of [["Enter", true], ["Enter", true], ["Enter", false], [" ", false], [" ", false], ["Enter", true]]) press(win, key, { repeat });
        await tick(60);
        expect(h.client.consentState()).toBe("unknown");
        expect(h.workers).toHaveLength(0);
        expect(h.document.querySelector('[data-action="accept"]')).not.toBeNull(); // the question is still asked
        expect(asked.length).toBeGreaterThan(0);
        expect(asked.every((outcome) => outcome.state === "pending")).toBe(true);
        expect(h.dom.window.sessionStorage.getItem("trioforge-engine-consent")).toBeNull(); // and no yes was written down
        // a visitor who means it gets there by the keyboard all the same: to the button, and Enter
        h.document.querySelector('[data-action="accept"]').focus();
        press(win, "Enter");
        await vi.waitFor(() => expect(asked[0].state).toBe("resolved"));
        expect(h.workers).toHaveLength(1);
        expect(h.client.consentState()).toBe("granted");
      });
    }

    it("declines with the Escape key", async () => {
      const h = makeHarness({ consent: null, navigator: {}, markup: READY_PAGE });
      const outcome = track(h.client.solve(modelRequest()));
      const panel = await screenOf(h, ".engine-consent");
      panel.dispatchEvent(new h.dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await vi.waitFor(() => expect(outcome.state).toBe("rejected"));
      expect(outcome.error).toMatchObject({ code: "declined" });
      expect(h.workers).toHaveLength(0);
    });

    it("shows a progress bar while the optimizer loads", async () => {
      const engine = fakeEngine();
      const load = engine.load.bind(engine);
      let release = null;
      engine.load = async (args) => {
        args.onProgress({ phase: "loading", loaded: 25, total: 100 });
        await new Promise((resolve) => (release = resolve));
        return load(args);
      };
      const h = makeHarness({ consent: null, navigator: {}, engine, markup: READY_PAGE });
      const outcome = track(h.client.solve(modelRequest()));
      (await screenOf(h, '[data-action="accept"]')).click();
      const bar = await screenOf(h, ".engine-consent progress");
      await vi.waitFor(() => expect(Number(bar.value)).toBe(25));
      expect(bar.getAttribute("max")).toBe("100");
      expect(h.document.querySelector(".engine-consent [role='status']").textContent).toMatch(/Loading the optimizer/);
      expect(h.document.querySelector('[data-action="accept"]')).toBeNull();
      // the group keeps a name, and what names it exists (a label that points at nothing is an accessibility error)
      const panel = h.document.querySelector(".engine-consent");
      const pointsAt = panel.getAttribute("aria-labelledby");
      expect(pointsAt === null || h.document.getElementById(pointsAt) !== null).toBe(true);
      expect(panel.getAttribute("aria-label") ?? pointsAt).toBeTruthy();
      release();
      await vi.waitFor(() => expect(outcome.state).toBe("resolved"));
      expect(h.document.querySelector(".engine-consent")).toBeNull();
    });

    it("leaves no pointer at the question on the loading panel after a yes: the text it described the panel by is gone, and the panel is named by its own label", async () => {
      const engine = fakeEngine();
      const load = engine.load.bind(engine);
      let release = null;
      engine.load = async (args) => {
        args.onProgress({ phase: "loading", loaded: 25, total: 100 });
        await new Promise((resolve) => (release = resolve));
        return load(args);
      };
      const h = makeHarness({ consent: null, navigator: {}, engine, markup: READY_PAGE });
      const outcome = track(h.client.solve(modelRequest()));
      const panel = await screenOf(h, ".engine-consent");
      expect(panel.getAttribute("aria-describedby"), "the question describes itself by its text").toBe("engine-consent-text");
      (await screenOf(h, '[data-action="accept"]')).click();
      await screenOf(h, ".engine-consent progress");
      expect(h.document.getElementById("engine-consent-text"), "the text of the question is gone").toBeNull();
      expect(panel.hasAttribute("aria-describedby"), "and the panel does not point at it").toBe(false);
      expect(panel.hasAttribute("aria-labelledby")).toBe(false);
      expect(panel.getAttribute("aria-label")).toBe("Optimizer download");
      await vi.waitFor(() => expect(release).not.toBeNull()); // (the optimizer is being loaded, and waits for the test)
      release();
      await vi.waitFor(() => expect(outcome.state).toBe("resolved"));
    });

    it("follows the phases of the first answer: loading, getting ready, setting up the problem, looking for the answer, and then nothing", async () => {
      const engine = fakeEngine();
      const load = engine.load.bind(engine);
      const releases = {};
      const gate = (name) => new Promise((resolve) => (releases[name] = resolve));
      engine.load = async (args) => {
        args.onProgress({ phase: "loading", loaded: 40, total: 100 });
        await gate("loading");
        const loaded = await load(args); // (reports the end of the loading and the compiling)
        args.onProgress({ phase: "starting" });
        await gate("starting");
        return {
          ...loaded,
          async solveModel(model, { onProgress }) {
            onProgress({ phase: "building" });
            await gate("building");
            onProgress({ phase: "solving", elapsedMs: 5 });
            await gate("solving");
            return { status: "optimal", proven: true, objective: 1, x: new Array(model.c.length).fill(0), bound: 1, gap: 0, nodes: 0, label: null };
          },
        };
      };
      const h = makeHarness({ consent: null, navigator: {}, engine, markup: READY_PAGE });
      const outcome = track(h.client.solve(modelRequest()));
      (await screenOf(h, '[data-action="accept"]')).click();
      const text = () => h.document.querySelector(".engine-consent [role='status']")?.textContent;
      const bar = () => h.document.querySelector(".engine-consent progress");
      await vi.waitFor(() => expect(text()).toBe("Loading the optimizer… 40%"));
      expect(bar().hasAttribute("value")).toBe(true);
      releases.loading();
      await vi.waitFor(() => expect(text()).toBe("Getting the optimizer ready…"));
      expect(bar().hasAttribute("value")).toBe(false); // nothing to count: the bar shows only that something is going on
      releases.starting();
      await vi.waitFor(() => expect(text()).toBe("Setting up the problem…")); // not "getting the optimizer ready" for the rest of the solve
      expect(bar().hasAttribute("value")).toBe(false);
      releases.building();
      await vi.waitFor(() => expect(text()).toBe("Looking for the best answer…"));
      expect(bar().hasAttribute("value")).toBe(false);
      expect(h.document.querySelector(".engine-consent [role='status']").textContent).not.toMatch(/ready|Loading/);
      expect(h.document.querySelector('[data-action="cancel"]')).not.toBeNull(); // and Cancel is still there for a long solve
      releases.solving();
      await vi.waitFor(() => expect(outcome.state).toBe("resolved"));
      expect(h.document.querySelector(".engine-consent")).toBeNull();
    });

    it("labels the bar by what it shows, so that a screen reader is not told about a download while the answer is being looked for", async () => {
      const h = makeHarness({ consent: null, navigator: {}, engine: fakeEngine({ hang: true }), markup: READY_PAGE });
      track(h.client.solve(modelRequest()));
      (await screenOf(h, '[data-action="accept"]')).click();
      await vi.waitFor(() => expect(h.document.querySelector(".engine-consent [role='status']")?.textContent).toBe("Looking for the best answer…"));
      expect(h.document.querySelector(".engine-consent progress").getAttribute("aria-label")).toBe("Looking for the best answer");
    });

    it("has a Cancel button on the loading panel, and the question has none (it has Not now)", async () => {
      const engine = fakeEngine();
      engine.load = () => new Promise(() => {}); // never loads
      const h = makeHarness({ consent: null, navigator: {}, engine, markup: READY_PAGE });
      track(h.client.solve(modelRequest()));
      await screenOf(h, '[data-action="accept"]');
      expect(h.document.querySelector('[data-action="cancel"]')).toBeNull();
      h.document.querySelector('[data-action="accept"]').click();
      const cancel = await screenOf(h, '[data-action="cancel"]');
      expect(cancel.tagName).toBe("BUTTON");
      expect(cancel.getAttribute("type")).toBe("button");
      expect(cancel.textContent).toBe("Cancel");
      expect(h.document.querySelector('[data-action="accept"]')).toBeNull();
      // a visitor at the keyboard stays in the panel: the focus is on it, one Tab from the button
      expect(h.document.activeElement).toBe(h.document.querySelector(".engine-consent"));
    });

    it("gives up the download when Cancel is pressed: the request is cancelled, the worker is gone, and the yes is taken back", async () => {
      const engine = fakeEngine();
      engine.load = () => new Promise(() => {});
      const h = makeHarness({ consent: null, navigator: {}, engine, markup: READY_PAGE });
      h.document.getElementById("start").focus();
      const queued = [track(h.client.solve(modelRequest())), track(h.client.solve(modelRequest()))];
      (await screenOf(h, '[data-action="accept"]')).click();
      await vi.waitFor(() => expect(h.workers).toHaveLength(1));
      expect(h.dom.window.sessionStorage.getItem("trioforge-engine-consent")).toBe("1");
      (await screenOf(h, '[data-action="cancel"]')).click();
      await vi.waitFor(() => expect(queued[0].state).toBe("rejected"));
      expect(queued.map((q) => q.error?.code)).toEqual(["cancelled", "cancelled"]);
      expect(h.workers[0].terminated).toBe(true);
      expect(h.document.querySelector(".engine-consent")).toBeNull();
      expect(h.document.activeElement).toBe(h.document.getElementById("start")); // the focus goes back to where it was
      expect(h.client.consentState()).toBe("declined"); // the precomputed answers stay
      expect(h.dom.window.sessionStorage.getItem("trioforge-engine-consent")).toBeNull(); // and a reload asks again
      // later requests are declined without a question, until the visitor asks for the optimizer again
      await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "declined" });
      expect(h.document.querySelector(".engine-consent")).toBeNull();
      expect(h.workers).toHaveLength(1);
      engine.load = fakeEngine().load;
      const again = track(h.client.askConsent());
      (await screenOf(h, '[data-action="accept"]')).click();
      await vi.waitFor(() => expect(again.state).toBe("resolved"));
      expect(again.value).toBe(true);
      expect(h.client.consentState()).toBe("granted");
    });

    it("keeps the yes when Cancel is pressed after the optimizer has loaded, while it works on the answer", async () => {
      const h = makeHarness({ consent: null, navigator: {}, engine: fakeEngine({ hang: true }), markup: READY_PAGE });
      const outcome = track(h.client.solve(modelRequest()));
      (await screenOf(h, '[data-action="accept"]')).click();
      await vi.waitFor(() => expect(h.workers[0]?.delivered.some((m) => m.type === "progress" && m.phase === "solving")).toBe(true));
      (await screenOf(h, '[data-action="cancel"]')).click(); // the panel is still up: this is the first answer
      await vi.waitFor(() => expect(outcome.state).toBe("rejected"));
      expect(outcome.error).toMatchObject({ code: "cancelled" });
      expect(h.client.consentState()).toBe("granted"); // the visitor did not take back the download, only this request
      expect(h.dom.window.sessionStorage.getItem("trioforge-engine-consent")).toBe("1");
      expect(h.document.querySelector(".engine-consent")).toBeNull();
    });

    it("marks the error of a Cancel pressed on the panel as the visitor's, and not the error of a cancel() from the page: a part of the page asks again for the second one only", async () => {
      const h = makeHarness({ consent: null, navigator: {}, engine: fakeEngine({ hang: true }), markup: READY_PAGE });
      const outcome = track(h.client.solve(modelRequest()));
      (await screenOf(h, '[data-action="accept"]')).click();
      await vi.waitFor(() => expect(h.workers[0]?.delivered.some((m) => m.type === "progress" && m.phase === "solving")).toBe(true));
      (await screenOf(h, '[data-action="cancel"]')).click();
      await vi.waitFor(() => expect(outcome.state).toBe("rejected"));
      expect(outcome.error).toMatchObject({ code: "cancelled", byVisitor: true });
      const second = track(h.client.solve(modelRequest()));
      h.client.cancel();
      await vi.waitFor(() => expect(second.state).toBe("rejected"));
      expect(second.error).toMatchObject({ code: "cancelled" });
      expect(second.error.byVisitor, "a cancel() of the page is not the visitor's").toBeUndefined();
    });

    it("drops the worker that is still starting when the request is cancelled from the page, before the optimizer is ready", async () => {
      const engine = fakeEngine();
      engine.load = () => new Promise(() => {});
      const h = makeHarness({ engine });
      const outcome = track(h.client.solve(modelRequest()));
      await tick(80);
      expect(h.workers).toHaveLength(1);
      expect(h.workers[0].terminated).toBe(false);
      h.client.cancel();
      await tick(10);
      expect(outcome.error).toMatchObject({ code: "cancelled" });
      expect(h.workers[0].terminated).toBe(true); // not left downloading for nobody
      expect(h.client.consentState()).toBe("granted"); // cancel() is the page's call, not the visitor's withdrawal of the yes
    });

    it("builds the panel from text nodes only, so nothing a file contains can become markup", async () => {
      const h = makeHarness({ consent: null, navigator: {}, markup: READY_PAGE });
      track(h.client.solve(modelRequest()));
      const panel = await screenOf(h, ".engine-consent");
      const tags = new Set([...panel.querySelectorAll("*")].map((e) => e.tagName.toLowerCase()));
      for (const tag of tags) expect(["h3", "p", "button", "progress", "div"], tag).toContain(tag);
      expect(panel.querySelectorAll("script, img, a, iframe, style").length).toBe(0);
      for (const element of [panel, ...panel.querySelectorAll("*")]) {
        for (const { name } of element.attributes) expect(name.startsWith("on") || name === "style" || name === "srcdoc", name).toBe(false);
      }
    });

    it("uses a container the page provides, when it provides one", async () => {
      const dom = new JSDOM('<!doctype html><main id="main"><section id="upgrade"><div id="slot"></div></section></main>', { url: "https://trioforge.test/" });
      const client = createEngineClient({
        window: dom.window,
        document: dom.window.document,
        fetch: async () => ({ ok: true, status: 200, text: async () => JSON.stringify(MANIFEST_JSON) }),
        createWorker: () => new FakeWorker(WORKER_PATH, { core: makeCore(fakeEngine()) }),
        mount: dom.window.document.getElementById("slot"),
        navigator: {},
        trustedTypes: null,
      });
      track(client.solve(modelRequest()));
      await vi.waitFor(() => expect(dom.window.document.querySelector("#slot > .engine-consent")).not.toBeNull());
      expect(dom.window.document.querySelectorAll(".engine-consent")).toHaveLength(1);
    });
  });

  describe("warnings", () => {
    const WARNED = {
      "Data Saver": [{ connection: { saveData: true } }, /Data Saver is on/],
      "a slow connection (2g)": [{ connection: { effectiveType: "2g" } }, /connection looks slow/],
      "a slow connection (slow-2g)": [{ connection: { effectiveType: "slow-2g" } }, /connection looks slow/],
      "a slow connection (3g)": [{ connection: { effectiveType: "3g" } }, /connection looks slow/],
      "little memory": [{ deviceMemory: 2 }, /little memory/],
      "very little memory": [{ deviceMemory: 0.5 }, /little memory/],
    };
    for (const [name, [navigator, pattern]] of Object.entries(WARNED)) {
      it(`adds a warning line for ${name}, and the question is the same`, async () => {
        expect(environmentWarnings(navigator).join(" ")).toMatch(pattern);
        const h = makeHarness({ consent: null, navigator });
        const outcome = track(h.client.solve(modelRequest()));
        const accept = await vi.waitFor(() => {
          const el = h.document.querySelector('[data-action="accept"]');
          expect(el).not.toBeNull();
          return el;
        });
        expect(accept.textContent).toBe(`Load the optimizer (about ${MEGABYTES} MB)`);
        expect(h.document.querySelectorAll(".engine-consent-warning")).toHaveLength(1);
        expect(h.document.querySelector(".engine-consent-warning").textContent).toMatch(pattern);
        expect(h.workers).toHaveLength(0); // a warning is not a refusal
        accept.click();
        await vi.waitFor(() => expect(outcome.state).toBe("resolved"));
      });
    }

    it("adds no warning for a fast connection, a lot of memory, or a browser that says nothing", () => {
      expect(environmentWarnings({ connection: { saveData: false, effectiveType: "4g" }, deviceMemory: 8 })).toEqual([]);
      expect(environmentWarnings({})).toEqual([]);
      expect(environmentWarnings(undefined)).toEqual([]);
      expect(environmentWarnings({ connection: { effectiveType: 5 }, deviceMemory: "2" })).toEqual([]);
      expect(environmentWarnings({ deviceMemory: 4 })).toEqual([]);
    });

    it("lists every reason in one line", () => {
      expect(environmentWarnings({ connection: { saveData: true, effectiveType: "2g" }, deviceMemory: 1 })).toHaveLength(3);
    });
  });

  describe("the session", () => {
    it("remembers the answer yes for the tab's session, so a reload does not ask again", async () => {
      const dom = new JSDOM("<!doctype html><main id='main'></main>", { url: "https://trioforge.test/" });
      const storage = dom.window.sessionStorage;
      const ask = vi.fn(async () => true);
      const first = makeHarness({ consent: { ask }, storage });
      await first.client.solve(modelRequest());
      expect(ask).toHaveBeenCalledTimes(1);
      const second = makeHarness({ consent: { ask }, storage });
      expect(second.client.consentState()).toBe("granted");
      await second.client.solve(modelRequest());
      expect(ask).toHaveBeenCalledTimes(1);
    });

    it("does not remember a no", async () => {
      const dom = new JSDOM("<!doctype html><main id='main'></main>", { url: "https://trioforge.test/" });
      const storage = dom.window.sessionStorage;
      const first = makeHarness({ consent: { ask: async () => false }, storage });
      await expect(first.client.solve(modelRequest())).rejects.toMatchObject({ code: "declined" });
      expect(storage.length).toBe(0);
      const second = makeHarness({ consent: { ask: async () => true }, storage });
      expect(second.client.consentState()).toBe("unknown");
    });

    it("works when the browser blocks storage", async () => {
      const blocked = {
        getItem() {
          throw new Error("blocked");
        },
        setItem() {
          throw new Error("blocked");
        },
        removeItem() {
          throw new Error("blocked");
        },
      };
      const ask = vi.fn(async () => true);
      const h = makeHarness({ consent: { ask }, storage: blocked });
      await h.client.solve(modelRequest());
      await h.client.solve(modelRequest());
      expect(ask).toHaveBeenCalledTimes(1);
    });

    it("ignores a stored value that is not the one it writes", () => {
      const storage = { getItem: () => "yes please", setItem() {}, removeItem() {} };
      const h = makeHarness({ storage });
      expect(h.client.consentState()).toBe("unknown");
    });
  });
});

// ---- a start that failed, the panel of every download, the question on its own, the Escape key, a release during the start --------

const PANEL_PAGE =
  '<!doctype html><html><body><header><button id="before">before</button></header><main id="main"><button id="start">Start</button></main></body></html>';
const UPDATED = "The optimizer was updated. Reload the page to use it.";

/** The first element of the page that matches (waiting for it to appear). */
function elementOf(h, selector) {
  return vi.waitFor(() => {
    const element = h.document.querySelector(selector);
    expect(element, selector).not.toBeNull();
    return element;
  });
}

/** An engine whose first `times` loads fail, the way a file that does not arrive or does not check out does. */
function failingEngine(times = 1) {
  const engine = fakeEngine();
  const load = engine.load.bind(engine);
  let left = times;
  engine.load = async (args) => {
    if (left > 0) {
      left -= 1;
      throw new Error("the file did not load");
    }
    return load(args);
  };
  return engine;
}

describe("starting again after a start that failed", () => {
  const NOTE = "The optimizer did not load last time.";
  const fakeTimers = () => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

  it("asks the question again at the next request instead of downloading by itself, says in a line that the optimizer did not load last time, and forgets the stored yes", async () => {
    const h = makeHarness({ consent: null, navigator: {}, engine: failingEngine(), markup: PANEL_PAGE });
    const first = track(h.client.solve(modelRequest()));
    (await elementOf(h, '[data-action="accept"]')).click();
    await vi.waitFor(() => expect(first.state).toBe("rejected"));
    expect(first.error).toMatchObject({ code: "engine-load" });
    expect(h.document.querySelector(".engine-consent")).toBeNull(); // the panel of the start that failed is gone
    expect(h.client.consentState()).toBe("unknown"); // the yes no longer starts a download
    expect(h.dom.window.sessionStorage.getItem("trioforge-engine-consent")).toBeNull(); // and a reload would ask too
    const second = track(h.client.solve(modelRequest()));
    const accept = await elementOf(h, '[data-action="accept"]');
    expect(h.workers).toHaveLength(1); // nothing was started by itself
    expect(h.document.querySelectorAll(".engine-consent-warning")).toHaveLength(1);
    expect(h.document.querySelector(".engine-consent-warning").textContent).toBe(NOTE);
    expect(accept.textContent).toBe(`Load the optimizer (about ${MEGABYTES} MB)`);
    accept.click();
    await vi.waitFor(() => expect(second.state).toBe("resolved"));
    expect(h.workers).toHaveLength(2);
    expect(h.client.consentState()).toBe("granted");
    expect(h.dom.window.sessionStorage.getItem("trioforge-engine-consent")).toBe("1");
    expect(h.document.querySelector(".engine-consent")).toBeNull();
  });

  it("tells a question about the failure, and only that question: the one after a yes is the plain one", async () => {
    const ask = vi.fn(async () => true);
    const h = makeHarness({ consent: { ask }, engine: failingEngine(2) });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "engine-load" });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "engine-load" });
    await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(ask).toHaveBeenCalledTimes(3);
    expect(ask.mock.calls.map(([info]) => info.failedLastTime === true)).toEqual([false, true, true]);
    await h.client.solve(modelRequest());
    expect(ask).toHaveBeenCalledTimes(3); // the yes of the last question stands
  });

  const CAUSES = {
    "the worker says it could not load": () => ({ engine: failingEngine() }),
    "the worker fails while it starts (its script, say)": () => {
      const engine = fakeEngine();
      engine.load = () => new Promise(() => {});
      return {
        engine,
        cause: async (h) => {
          await tick(80);
          h.workers[0].crash();
        },
      };
    },
    "the worker breaks the protocol while it starts": () => {
      let broken = true;
      return {
        script: (message, reply) => {
          if (message.type === "init" && broken) {
            broken = false;
            reply({ v: 1, type: "pong" });
          } else if (message.type === "init") {
            reply({ v: 1, type: "ready", highs: "1.15.1", wasm: WASM_SHA, module: new WebAssembly.Module(EMPTY_MODULE_BYTES) });
          } else if (message.type === "solve") {
            reply({ v: 1, type: "result", id: message.id, kind: "model", status: "optimal", proven: true, objective: 1, x: new Array(message.request.model.c.length).fill(0), bound: 1, gap: 0, nodes: 0, elapsedMs: 1, label: null });
          }
        },
      };
    },
    "the compile or the start of the solver hangs": () => {
      const engine = fakeEngine();
      engine.load = async ({ onProgress }) => {
        onProgress({ phase: "loading", loaded: 100, total: 100 });
        onProgress({ phase: "compiling" });
        await new Promise(() => {});
      };
      return {
        engine,
        cause: async () => {
          await tick(80);
          await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS);
        },
      };
    },
  };
  for (const [name, make] of Object.entries(CAUSES)) {
    it(`asks again after a start that failed because ${name}, and downloads again only after a yes`, async () => {
      fakeTimers();
      const answers = [];
      const ask = vi.fn(() => new Promise((resolve) => answers.push(resolve)));
      const { engine, script, cause } = make();
      const h = makeHarness({ consent: { ask }, ...(engine ? { engine } : {}), ...(script ? { script } : {}) });
      const first = track(h.client.solve(modelRequest()));
      await tick(40);
      answers.shift()(true); // the first question: yes
      await tick(40);
      await cause?.(h);
      await tick(80);
      expect(first.state, name).toBe("rejected");
      expect(ask).toHaveBeenCalledTimes(1);
      const spawned = h.workers.length;
      if (engine) engine.load = fakeEngine().load; // what was wrong is mended
      const second = track(h.client.solve(modelRequest()));
      await tick(80);
      expect(ask, "the next request asks again").toHaveBeenCalledTimes(2);
      expect(ask.mock.calls[1][0].failedLastTime).toBe(true);
      expect(h.workers, "and nothing is started before the answer").toHaveLength(spawned);
      answers.shift()(true);
      await tick(80);
      expect(second.state).toBe("resolved");
      expect(h.workers).toHaveLength(spawned + 1);
    });
  }

  it("keeps the precomputed answers when the visitor says no to that question, as for any no, and the question after it has no such line", async () => {
    const answers = [true, false, true];
    const ask = vi.fn(async () => answers.shift());
    const h = makeHarness({ consent: { ask }, engine: failingEngine() });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "engine-load" });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "declined" });
    expect(ask).toHaveBeenCalledTimes(2);
    expect(h.workers).toHaveLength(1);
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "declined" }); // no new question
    expect(ask).toHaveBeenCalledTimes(2);
    await expect(h.client.askConsent()).resolves.toBe(true);
    expect(ask.mock.calls[2][0].failedLastTime).toBe(false);
  });

  it("asks at the request that was waiting behind the one whose start failed, and does not download for it by itself", async () => {
    const ask = vi.fn(async () => true);
    const h = makeHarness({ consent: { ask }, engine: failingEngine() });
    const outcomes = [h.client.solve(modelRequest()), h.client.solve(modelRequest())].map(track);
    await tick(200);
    expect(outcomes.map((o) => o.state)).toEqual(["rejected", "resolved"]);
    expect(ask).toHaveBeenCalledTimes(2);
    expect(ask.mock.calls[1][0].failedLastTime).toBe(true);
  });

  it("does not ask again after what is not a failed start: a worker that dies after it was ready, a request that fails, a watchdog, a cancel", async () => {
    fakeTimers();
    const ask = vi.fn(async () => true);
    const engine = fakeEngine();
    const h = makeHarness({ consent: { ask }, engine });
    await h.client.solve(modelRequest({ budgetMs: 1000 }));
    h.workers[0].crash(); // a worker that was ready
    await h.client.solve(modelRequest({ budgetMs: 1000 })); // restarted from the kept module
    engine.state.fault = "solver";
    await expect(h.client.solve(modelRequest({ budgetMs: 1000 }))).rejects.toMatchObject({ code: "solver" });
    engine.state.fault = undefined;
    engine.state.hang = true;
    const hung = track(h.client.solve(modelRequest({ budgetMs: 100 })));
    await tick(80);
    await vi.advanceTimersByTimeAsync(100 + WATCHDOG_GRACE_MS);
    await tick(20);
    expect(hung.error).toMatchObject({ code: "watchdog" });
    engine.state.hang = false;
    const load = engine.load.bind(engine);
    engine.load = () => new Promise(() => {}); // the next start never finishes
    const cancelled = track(h.client.solve(modelRequest({ budgetMs: 1000 })));
    await tick(80);
    h.client.cancel(); // the page cancels a start that is under way
    await tick(20);
    expect(cancelled.error).toMatchObject({ code: "cancelled" });
    engine.load = load;
    await h.client.solve(modelRequest({ budgetMs: 1000 }));
    expect(ask).toHaveBeenCalledTimes(1);
    expect(h.client.consentState()).toBe("granted");
  });
});

describe("every download shows the loading panel, with progress and a Cancel that works", () => {
  const storageWithYes = () => {
    const store = new Map([["trioforge-engine-consent", "1"]]);
    return { store, storage: { getItem: (key) => store.get(key) ?? null, setItem: (key, value) => store.set(key, value), removeItem: (key) => store.delete(key) } };
  };

  /** An engine that reports a quarter of the download and waits to be released. */
  function gatedEngine() {
    const engine = fakeEngine();
    const load = engine.load.bind(engine);
    const gate = { release: null };
    engine.load = async (args) => {
      args.onProgress({ phase: "loading", loaded: 25, total: 100 });
      await new Promise((resolve) => (gate.release = resolve));
      return load(args);
    };
    return { engine, gate };
  }

  it("is there for a visitor whose yes was remembered and who is therefore not asked: progress, and a Cancel that takes the yes back", async () => {
    const { store, storage } = storageWithYes();
    const { engine } = gatedEngine();
    const h = makeHarness({ consent: null, navigator: {}, engine, storage, markup: PANEL_PAGE });
    expect(h.client.consentState()).toBe("granted");
    h.document.getElementById("start").focus();
    const outcome = track(h.client.solve(modelRequest()));
    const bar = await elementOf(h, ".engine-consent progress");
    expect(h.document.querySelector('[data-action="accept"]')).toBeNull(); // nobody was asked
    await vi.waitFor(() => expect(Number(bar.value)).toBe(25));
    expect(bar.getAttribute("max")).toBe("100");
    expect(h.document.querySelector(".engine-consent [role='status']").textContent).toBe("Loading the optimizer… 25%");
    expect(h.document.activeElement, "the panel does not take the focus from what the visitor was doing").toBe(h.document.getElementById("start"));
    (await elementOf(h, '[data-action="cancel"]')).click();
    await vi.waitFor(() => expect(outcome.state).toBe("rejected"));
    expect(outcome.error).toMatchObject({ code: "cancelled" });
    expect(h.workers[0].terminated).toBe(true);
    expect(h.document.querySelector(".engine-consent")).toBeNull();
    expect(h.client.consentState()).toBe("declined");
    expect(store.has("trioforge-engine-consent")).toBe(false);
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "declined" }); // no download by itself afterwards
    expect(h.workers).toHaveLength(1);
  });

  it("goes away when the optimizer is ready, as the panel that follows a question does", async () => {
    const { storage } = storageWithYes();
    const { engine, gate } = gatedEngine();
    const h = makeHarness({ consent: null, navigator: {}, engine, storage, markup: PANEL_PAGE });
    const outcome = track(h.client.solve(modelRequest()));
    await elementOf(h, ".engine-consent progress");
    gate.release();
    await vi.waitFor(() => expect(outcome.state).toBe("resolved"));
    expect(h.document.querySelector(".engine-consent")).toBeNull();
  });

  it("is not there for a start from the kept module: nothing is downloaded, so there is nothing to wait for", async () => {
    const engine = fakeEngine();
    const h = makeHarness({ consent: { ask: async () => true }, engine });
    await h.client.solve(modelRequest());
    h.workers[0].crash();
    const load = engine.load.bind(engine);
    let release;
    engine.load = (args) => (args.module === undefined ? load(args) : new Promise((resolve) => (release = () => resolve(load(args)))));
    const outcome = track(h.client.solve(modelRequest()));
    await tick(80);
    expect(h.workers).toHaveLength(2);
    expect(h.document.querySelector(".engine-consent")).toBeNull();
    release();
    await tick(80);
    expect(outcome.state).toBe("resolved");
  });

  it("is asked of a page's own consent object too, once, when it has a method for it", async () => {
    const { storage } = storageWithYes();
    const calls = [];
    const consent = { ask: async () => true, loading: () => calls.push("panel"), progress: (report) => calls.push(`report:${report.phase}`), close: () => calls.push("close") };
    const h = makeHarness({ consent, storage });
    await h.client.solve(modelRequest());
    expect(calls[0]).toBe("panel"); // before the first report of the download
    expect(calls.filter((call) => call === "panel")).toHaveLength(1);
    expect(calls).toContain("report:loading");
  });
});

describe("the question asked on its own (askConsent)", () => {
  it("is closed after a yes when no request is waiting: the panel does not stay on Loading the optimizer with nothing loading", async () => {
    const h = makeHarness({ consent: null, navigator: {}, markup: PANEL_PAGE });
    h.document.getElementById("start").focus();
    const asking = track(h.client.askConsent());
    (await elementOf(h, '[data-action="accept"]')).click();
    await vi.waitFor(() => expect(asking.state).toBe("resolved"));
    expect(asking.value).toBe(true);
    await tick(40);
    expect(h.document.querySelector(".engine-consent"), "no panel is left").toBeNull();
    expect(h.document.activeElement).toBe(h.document.getElementById("start"));
    expect(h.workers).toHaveLength(0); // a yes says only that the optimizer may be loaded: the first request loads it
    expect(h.client.consentState()).toBe("granted");
    expect(h.dom.window.sessionStorage.getItem("trioforge-engine-consent")).toBe("1");
  });

  it("is followed by a download under its own panel at the first request, which is not asked again and can be cancelled", async () => {
    const engine = fakeEngine();
    const load = engine.load.bind(engine);
    let release;
    engine.load = async (args) => {
      args.onProgress({ phase: "loading", loaded: 40, total: 100 });
      await new Promise((resolve) => (release = resolve));
      return load(args);
    };
    const h = makeHarness({ consent: null, navigator: {}, engine, markup: PANEL_PAGE });
    const asking = track(h.client.askConsent());
    (await elementOf(h, '[data-action="accept"]')).click();
    await vi.waitFor(() => expect(asking.state).toBe("resolved"));
    const outcome = track(h.client.solve(modelRequest()));
    await elementOf(h, ".engine-consent progress");
    expect(h.document.querySelector('[data-action="accept"]')).toBeNull();
    (await elementOf(h, '[data-action="cancel"]')).click();
    await vi.waitFor(() => expect(outcome.state).toBe("rejected"));
    expect(outcome.error).toMatchObject({ code: "cancelled" });
    expect(h.document.querySelector(".engine-consent")).toBeNull();
    release?.();
  });

  it("keeps the panel when a request is waiting for the same question, since there is something loading", async () => {
    const engine = fakeEngine();
    engine.load = () => new Promise(() => {});
    const h = makeHarness({ consent: null, navigator: {}, engine, markup: PANEL_PAGE });
    const outcome = track(h.client.solve(modelRequest()));
    const asking = track(h.client.askConsent());
    (await elementOf(h, '[data-action="accept"]')).click();
    await vi.waitFor(() => expect(asking.state).toBe("resolved"));
    await elementOf(h, '.engine-consent [data-action="cancel"]');
    expect(h.document.querySelector(".engine-consent [role='status']").textContent).toMatch(/Loading the optimizer/);
    h.document.querySelector('[data-action="cancel"]').click();
    await vi.waitFor(() => expect(outcome.state).toBe("rejected"));
    expect(h.document.querySelector(".engine-consent")).toBeNull();
  });
});

describe("the Escape key during the download", () => {
  /** Which keydown handlers are on a panel of the question at the moment (the page's listeners are added and removed through the window's EventTarget). */
  function keydownHandlersOnThePanel(win) {
    const active = new Set();
    const proto = win.EventTarget.prototype;
    const add = proto.addEventListener;
    const remove = proto.removeEventListener;
    proto.addEventListener = function (type, listener, options) {
      if (type === "keydown" && this.classList?.contains("engine-consent")) active.add(listener);
      return add.call(this, type, listener, options);
    };
    proto.removeEventListener = function (type, listener, options) {
      if (type === "keydown" && this.classList?.contains("engine-consent")) active.delete(listener);
      return remove.call(this, type, listener, options);
    };
    return active;
  }
  const escape = (h, target) => target.dispatchEvent(new h.dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));

  it("does nothing: the download goes on, the panel stays, the yes stands, and Cancel still works afterwards", async () => {
    const engine = fakeEngine();
    engine.load = () => new Promise(() => {});
    const h = makeHarness({ consent: null, navigator: {}, engine, markup: PANEL_PAGE });
    const outcome = track(h.client.solve(modelRequest()));
    (await elementOf(h, '[data-action="accept"]')).click();
    const cancel = await elementOf(h, '[data-action="cancel"]');
    const panel = h.document.querySelector(".engine-consent");
    for (const target of [panel, cancel, h.document.body]) escape(h, target);
    await tick(40);
    expect(outcome.state).toBe("pending");
    expect(h.workers[0].terminated).toBe(false);
    expect(h.document.querySelector(".engine-consent")).toBe(panel);
    expect(h.client.consentState()).toBe("granted");
    expect(h.dom.window.sessionStorage.getItem("trioforge-engine-consent")).toBe("1");
    cancel.click();
    await vi.waitFor(() => expect(outcome.state).toBe("rejected"));
    expect(outcome.error).toMatchObject({ code: "cancelled" });
  });

  it("leaves no handler of the question on the panel once it has been answered, and the handler is there while the question is open", async () => {
    const engine = fakeEngine();
    engine.load = () => new Promise(() => {});
    const h = makeHarness({ consent: null, navigator: {}, engine, markup: PANEL_PAGE });
    const handlers = keydownHandlersOnThePanel(h.dom.window);
    track(h.client.solve(modelRequest()));
    await elementOf(h, '[data-action="accept"]');
    expect(handlers.size, "the open question has its Escape handler").toBe(1);
    h.document.querySelector('[data-action="accept"]').click();
    await elementOf(h, '[data-action="cancel"]');
    expect(handlers.size, "the panel of the download has none").toBe(0);
  });

  it("still declines the question with Escape while it is open, and then leaves no handler either", async () => {
    const h = makeHarness({ consent: null, navigator: {}, markup: PANEL_PAGE });
    const handlers = keydownHandlersOnThePanel(h.dom.window);
    const outcome = track(h.client.solve(modelRequest()));
    const panel = await elementOf(h, ".engine-consent");
    escape(h, panel);
    await vi.waitFor(() => expect(outcome.state).toBe("rejected"));
    expect(outcome.error).toMatchObject({ code: "declined" });
    expect(handlers.size).toBe(0);
  });
});

describe("a release that lands during the start", () => {
  // the worker reads the manifest for itself: if a release came between the page's read and the worker's, it loads another file than the page described
  const OTHER = parseManifest({ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, path: "/assets/engine/highs-FEDCBA9876543210.wasm", sha256: "fedcba9876543210".padEnd(64, "0") } });

  it("stops the trying: the request fails with the plain message, the worker and what it made are dropped, and a notice with a Reload button stays on the page", async () => {
    const reload = vi.fn();
    const h = makeHarness({ consent: null, navigator: {}, workerManifest: OTHER, reload, markup: PANEL_PAGE });
    const first = track(h.client.solve(modelRequest()));
    (await elementOf(h, '[data-action="accept"]')).click();
    await vi.waitFor(() => expect(first.state).toBe("rejected"));
    expect(first.error).toMatchObject({ code: "engine-load", message: UPDATED });
    expect(h.workers[0].terminated).toBe(true);
    expect(h.client.stats().moduleKept).toBe(false);
    const notice = await elementOf(h, ".engine-consent");
    await tick(40); // (the end of the request closes the panel of a start; the notice is not one)
    expect(h.document.querySelector(".engine-consent")).toBe(notice);
    expect(notice.textContent).toContain(UPDATED);
    expect(notice.querySelector("progress")).toBeNull();
    const button = notice.querySelector('[data-action="reload"]');
    expect(button.tagName).toBe("BUTTON");
    expect(button.textContent).toBe("Reload");
    expect(reload).not.toHaveBeenCalled();
    button.click();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("downloads nothing more: every later request fails at once with the same message, the question is not asked, and no worker is started", async () => {
    const ask = vi.fn(async () => true);
    const engine = fakeEngine();
    const h = makeHarness({ consent: { ask }, engine, workerManifest: OTHER });
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "engine-load", message: UPDATED });
    for (let i = 0; i < 3; i += 1) await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "engine-load", message: UPDATED });
    await expect(h.client.askConsent()).resolves.toBe(false);
    expect(h.workers).toHaveLength(1);
    expect(engine.calls.filter((call) => call.type === "load")).toHaveLength(1);
    expect(ask).toHaveBeenCalledTimes(1);
    expect(h.fetchCalls).toEqual(["/engine-manifest.json"]);
    expect(h.client.stats()).toMatchObject({ spawns: 1, moduleKept: false });
  });

  it("shows the one notice, however many requests it refuses, and takes it away when the client is shut down", async () => {
    const h = makeHarness({ consent: null, navigator: {}, workerManifest: OTHER, markup: PANEL_PAGE });
    const first = track(h.client.solve(modelRequest()));
    (await elementOf(h, '[data-action="accept"]')).click();
    await vi.waitFor(() => expect(first.state).toBe("rejected"));
    for (let i = 0; i < 3; i += 1) await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ message: UPDATED });
    expect(h.document.querySelectorAll(".engine-consent")).toHaveLength(1);
    expect(h.document.querySelectorAll('[data-action="reload"]')).toHaveLength(1);
    h.client.dispose();
    expect(h.document.querySelector(".engine-consent")).toBeNull();
  });

  it("never pairs the compiled module it kept with a newer manifest: the worker that is given it reads the newer one, says so, and the module is dropped", async () => {
    const h = makeHarness({ workerManifest: (made) => (made === 0 ? MANIFEST : OTHER) });
    await h.client.solve(modelRequest());
    expect(h.client.stats().moduleKept).toBe(true);
    h.workers[0].crash(); // the next request is given the kept module...
    await tick(10);
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ code: "engine-load", message: UPDATED });
    expect(h.workers).toHaveLength(2);
    expect(h.workers[1].sent[0].module).toBeInstanceOf(WebAssembly.Module);
    expect(h.workers[1].terminated).toBe(true);
    expect(h.client.stats().moduleKept).toBe(false); // ... and it does not live on to be given to another
    await expect(h.client.solve(modelRequest())).rejects.toMatchObject({ message: UPDATED });
    expect(h.workers).toHaveLength(2);
  });

  it("is not an update when the newer manifest lists the same WebAssembly: the worker goes on", async () => {
    const same = parseManifest({ ...MANIFEST_JSON, trios: { ...MANIFEST_JSON.trios, "war-war-war": [50] }, worker: { ...MANIFEST_JSON.worker, path: "/assets/engine/worker-CCCCCCCC.js" } });
    const h = makeHarness({ workerManifest: same });
    await expect(h.client.solve(modelRequest())).resolves.toMatchObject({ status: "optimal" });
    expect(h.client.stats()).toMatchObject({ moduleKept: true });
  });
});

// ---- the real engine, in Node ------------------------------------------------------------------------------------------------

describe("the real engine", () => {
  const wasmBytes = readFileSync(WASM_FILE);
  const ORIGIN = "https://trioforge.test";
  const REAL_SHA = createHash("sha256").update(wasmBytes).digest("hex");
  // the manifest of a release whose WebAssembly is the real file: its size and its SHA-256
  const REAL_MANIFEST_JSON = { ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, bytes: wasmBytes.length, sha256: REAL_SHA } };
  const manifestFor = (bytes, sha256 = REAL_SHA) => parseManifest({ ...MANIFEST_JSON, wasm: { ...MANIFEST_JSON.wasm, bytes, sha256 } });

  /** A fetch that serves the real WebAssembly under the manifest's path, and records what was asked for. */
  function wasmFetch(overrides = {}) {
    const asked = [];
    const fetchImpl = async (url) => {
      asked.push(String(url));
      if (String(url) !== `${ORIGIN}${WASM_PATH}`) return new Response("not found", { status: 404 });
      return new Response(overrides.body ?? wasmBytes, {
        status: overrides.status ?? 200,
        headers: { "content-type": overrides.type ?? "application/wasm" },
      });
    };
    return { asked, fetchImpl };
  }

  async function load(options = {}) {
    const { asked, fetchImpl } = wasmFetch(options.fetch);
    const progress = [];
    const engine = await loadHighsEngine({
      manifest: options.manifest ?? manifestFor(wasmBytes.length),
      module: options.module,
      fetchImpl,
      baseUrl: `${ORIGIN}/assets/engine/worker-BBBBBBBB.js`,
      onProgress: (p) => progress.push(p),
    });
    return { engine, asked, progress };
  }

  const solveOptions = (budgetMs = 20000) => ({ budgetMs, startedAt: performance.now(), onProgress() {} });

  it("uses the project's determinism options, the same as the Python solver and the benchmark", () => {
    expect(SOLVER_OPTIONS).toEqual(BENCH_OPTIONS);
    expect(SOLVER_OPTIONS).not.toHaveProperty("threads"); // the one-thread build refuses the option
    expect(SOLVER_OPTIONS.presolve).toBe("off");
    expect(SOLVER_OPTIONS.mip_rel_gap).toBe(0);
    expect(SOLVER_OPTIONS.random_seed).toBe(0);
  });

  it("downloads the manifest's WebAssembly, and only that, and reports the download as it goes", async () => {
    const { engine, asked, progress } = await load();
    expect(asked).toEqual([`${ORIGIN}${WASM_PATH}`]);
    expect(engine.version).toMatch(/^1\.15\.\d+$/);
    expect(engine.module).toBeInstanceOf(WebAssembly.Module);
    const loaded = progress.filter((p) => p.phase === "loading");
    expect(loaded.length).toBeGreaterThan(1);
    expect(loaded.map((p) => p.loaded)).toEqual([...loaded.map((p) => p.loaded)].sort((a, b) => a - b));
    expect(loaded.at(-1)).toEqual({ phase: "loading", loaded: wasmBytes.length, total: wasmBytes.length });
    expect(progress.map((p) => p.phase)).toEqual(expect.arrayContaining(["loading", "compiling", "starting"]));
  });

  it("says which file it loaded, by its SHA-256, when it downloaded one, and nothing when it was given a module", async () => {
    const first = await load();
    expect(first.engine.wasm).toBe(REAL_SHA);
    const second = await load({ module: first.engine.module });
    expect(second.engine.wasm).toBeUndefined();
    expect(second.asked).toEqual([]);
  });

  it("refuses a file of the right type and size whose SHA-256 is not the manifest's, and compiles nothing", async () => {
    const tampered = new Uint8Array(wasmBytes);
    tampered[tampered.length >> 1] ^= 1; // one bit
    const compile = vi.spyOn(WebAssembly, "compile").mockRejectedValue(new Error("stopped at the compiler"));
    try {
      const failure = await load({ fetch: { body: tampered } }).catch((error) => error);
      expect(failure).toBeInstanceOf(EngineFault);
      expect(failure).toMatchObject({ code: "engine-load", message: expect.stringMatching(/checksum/i) });
      expect(compile).not.toHaveBeenCalled();
      // the same bytes get as far as the compiler for a manifest that lists their digest, so it is the digest that decided
      const listed = createHash("sha256").update(tampered).digest("hex");
      await expect(load({ manifest: manifestFor(tampered.length, listed), fetch: { body: tampered } })).rejects.toThrow("stopped at the compiler");
      expect(compile).toHaveBeenCalledTimes(1);
    } finally {
      compile.mockRestore();
    }
  });

  it("checks the file when the response has no body to read in pieces", async () => {
    const respond = (bytes) => async () => ({ ok: true, status: 200, headers: new Headers({ "content-type": "application/wasm" }), body: null, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) });
    const options = { manifest: manifestFor(wasmBytes.length), baseUrl: `${ORIGIN}/assets/engine/worker-BBBBBBBB.js`, onProgress() {} };
    const good = await loadHighsEngine({ ...options, fetchImpl: respond(new Uint8Array(wasmBytes)) });
    expect(good.wasm).toBe(REAL_SHA);
    const tampered = new Uint8Array(wasmBytes);
    tampered[100] ^= 1;
    await expect(loadHighsEngine({ ...options, fetchImpl: respond(tampered) })).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(/checksum/i) });
  });

  it("fails closed when the browser cannot compute a SHA-256", async () => {
    vi.stubGlobal("crypto", {});
    try {
      await expect(load()).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(/cannot check/i) });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  describe("a download that stalls", () => {
    const BASE = `${ORIGIN}/assets/engine/worker-BBBBBBBB.js`;
    const fakeTimers = () => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    /** A response whose body is delivered by hand, and that fails the way a real one does when its request is aborted. */
    function byHand(signal) {
      let stream;
      const body = new ReadableStream({
        start(controller) {
          stream = controller;
          signal?.addEventListener("abort", () => {
            try {
              controller.error(new DOMException("The operation was aborted.", "AbortError"));
            } catch {
              // already closed
            }
          });
        },
      });
      return {
        response: new Response(body, { status: 200, headers: { "content-type": "application/wasm" } }),
        push: (bytes) => stream.enqueue(bytes),
        end: () => stream.close(),
      };
    }

    it("is given up when no answer starts for the stall time, and the request itself is aborted", async () => {
      fakeTimers();
      let signal;
      const fetchImpl = (url, init) =>
        new Promise((resolve, reject) => {
          signal = init.signal;
          signal.addEventListener("abort", () => reject(new DOMException("The operation was aborted.", "AbortError")));
        });
      const loading = track(loadHighsEngine({ manifest: manifestFor(wasmBytes.length), fetchImpl, baseUrl: BASE, onProgress() {} }));
      await tick(20);
      await vi.advanceTimersByTimeAsync(STARTUP_STALL_MS - 1);
      expect(loading.state).toBe("pending");
      expect(signal.aborted).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      await tick(10);
      expect(loading.state).toBe("rejected");
      expect(loading.error).toBeInstanceOf(EngineFault);
      expect(loading.error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/stalled/i) });
      expect(signal.aborted).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("is given up when the bytes stop coming for the stall time, however many came before", async () => {
      fakeTimers();
      let signal;
      let delivery;
      const progress = [];
      const fetchImpl = async (url, init) => {
        signal = init.signal;
        delivery = byHand(signal);
        return delivery.response;
      };
      const loading = track(loadHighsEngine({ manifest: manifestFor(wasmBytes.length), fetchImpl, baseUrl: BASE, onProgress: (p) => progress.push(p) }));
      await tick(20);
      for (let piece = 0; piece < 3; piece += 1) {
        delivery.push(wasmBytes.subarray(piece * 100_000, (piece + 1) * 100_000));
        await vi.advanceTimersByTimeAsync(STARTUP_STALL_MS - 1000); // each wait is shorter than the stall time, together they are not
        await tick(10);
      }
      expect(loading.state).toBe("pending");
      await vi.advanceTimersByTimeAsync(STARTUP_STALL_MS - (STARTUP_STALL_MS - 1000) - 1);
      expect(loading.state).toBe("pending");
      await vi.advanceTimersByTimeAsync(1);
      await tick(10);
      expect(loading.state).toBe("rejected");
      expect(loading.error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/stalled/i) });
      expect(signal.aborted).toBe(true);
      expect(progress.some((p) => p.phase === "loading" && p.loaded >= 300_000)).toBe(true);
    });

    it("is not given up while bytes keep coming, even if it takes far longer than the stall time in all", async () => {
      fakeTimers();
      let delivery;
      const fetchImpl = async (url, init) => {
        delivery = byHand(init.signal);
        return delivery.response;
      };
      const loading = track(loadHighsEngine({ manifest: manifestFor(wasmBytes.length), fetchImpl, baseUrl: BASE, onProgress() {} }));
      await tick(20);
      const pieces = 10;
      const size = Math.ceil(wasmBytes.length / pieces);
      for (let piece = 0; piece < pieces; piece += 1) {
        delivery.push(wasmBytes.subarray(piece * size, Math.min(wasmBytes.length, (piece + 1) * size)));
        await vi.advanceTimersByTimeAsync(STARTUP_STALL_MS - 5000); // 150 seconds for the whole file, never 20 without a byte
        await tick(10);
      }
      delivery.end();
      await vi.waitFor(() => expect(loading.state).toBe("resolved"), { timeout: 20_000 });
      expect(loading.value.wasm).toBe(REAL_SHA);
      expect(vi.getTimerCount()).toBe(0);
    }, 30_000);

    it("is not given up by the page either: ten minutes of a download that delivers every 15 seconds, through the client and the worker, ends in the answer", async () => {
      fakeTimers();
      let delivery;
      const fetchImpl = async (url, init) => {
        delivery = byHand(init.signal);
        return delivery.response;
      };
      const harnessEngine = { load: (args) => loadHighsEngine({ ...args, manifest: manifestFor(wasmBytes.length), fetchImpl, baseUrl: BASE }) };
      const h = makeHarness({ engine: harnessEngine, manifest: REAL_MANIFEST_JSON, workerManifest: parseManifest(REAL_MANIFEST_JSON), now: () => 0 });
      const request = track(h.client.solve({ v: 1, kind: "model", model: handMilp(), budgetMs: 20_000 }));
      await tick(80);
      const pieces = 40;
      const size = Math.ceil(wasmBytes.length / pieces);
      for (let piece = 0; piece < pieces; piece += 1) {
        delivery.push(wasmBytes.subarray(piece * size, Math.min(wasmBytes.length, (piece + 1) * size)));
        await vi.advanceTimersByTimeAsync(15_000); // 40 times 15 seconds: ten minutes, and never 20 seconds without a byte
        await tick(10);
        expect(request.state, `after piece ${piece}`).toBe("pending");
        expect(h.workers[0].terminated, `after piece ${piece}`).toBe(false);
      }
      delivery.end();
      await vi.waitFor(() => expect(request.state).toBe("resolved"), { timeout: 30_000 });
      expect(request.value.status).toBe("optimal");
      expect(h.workers).toHaveLength(1);
      expect(vi.getTimerCount()).toBe(0);
    }, 60_000);

    /** A response that cannot be read in pieces (no body to read from), whose bytes arrive when the test says. */
    function unreadableInPieces() {
      const state = { signal: undefined, deliver: undefined };
      const fetchImpl = async (url, init) => {
        state.signal = init.signal;
        return {
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/wasm" }),
          body: null,
          arrayBuffer: () => new Promise((resolve) => (state.deliver = resolve)),
        };
      };
      return { state, fetchImpl };
    }

    it("does not call a long body a stall when the response cannot be read in pieces: once the answer has begun only the long limit applies", async () => {
      fakeTimers();
      const { state, fetchImpl } = unreadableInPieces();
      const loading = track(loadHighsEngine({ manifest: manifestFor(wasmBytes.length), fetchImpl, baseUrl: BASE, onProgress() {} }));
      await tick(20);
      await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS - 1); // three times the stall time, the answer begun and the body still on its way
      expect(loading.state).toBe("pending");
      expect(state.signal.aborted).toBe(false);
      state.deliver(wasmBytes.buffer.slice(wasmBytes.byteOffset, wasmBytes.byteOffset + wasmBytes.byteLength));
      await vi.waitFor(() => expect(loading.state).toBe("resolved"), { timeout: 20_000 });
      expect(loading.value.wasm).toBe(REAL_SHA);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("gives a body that cannot be read in pieces the long limit and no more, and the request itself is aborted", async () => {
      fakeTimers();
      const { state, fetchImpl } = unreadableInPieces();
      const loading = track(loadHighsEngine({ manifest: manifestFor(wasmBytes.length), fetchImpl, baseUrl: BASE, onProgress() {} }));
      await tick(20);
      await vi.advanceTimersByTimeAsync(STARTUP_COMPILE_MS - 1);
      expect(loading.state).toBe("pending");
      await vi.advanceTimersByTimeAsync(1);
      await tick(10);
      expect(loading.state).toBe("rejected");
      expect(loading.error).toBeInstanceOf(EngineFault);
      expect(loading.error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/too long|did not arrive/i) });
      expect(state.signal.aborted).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
    });
  });

  it("solves the hand-written model to the optimum found by trying every choice", async () => {
    const { engine } = await load();
    const model = handMilp();
    const result = await engine.solveModel(model, solveOptions());
    const expected = handOptimum();
    expect(result.status).toBe("optimal");
    expect(result.proven).toBe(true);
    expect(result.label).toBeNull();
    expect(result.objective).toBeCloseTo(expected.objective, 9);
    const verdict = check(model, result.x);
    expect(verdict.problems).toEqual([]);
    expect(verdict.objective).toBeCloseTo(expected.objective, 9);
    expect(result.gap).toBeLessThan(1e-9);
    expect(result.nodes).toBeGreaterThanOrEqual(0);
  });

  it("reads null as an infinite bound, in the columns and in the rows", async () => {
    const { engine } = await load();
    // maximise y with y >= 0 (no upper bound) and y - z <= 4, z in [0, 3]: y = 7
    const model = {
      version: 1,
      sense: "max",
      const: 0,
      col_lb: [0, 0],
      col_ub: [null, 3],
      integrality: [0, 0],
      c: [1, 0],
      row_lb: [null],
      row_ub: [4],
      A: { start: [0, 2], index: [0, 1], value: [1, -1] },
    };
    const result = await engine.solveModel(model, solveOptions());
    expect(result.status).toBe("optimal");
    expect(result.objective).toBeCloseTo(7, 9);
    // minimise y with no lower bound on y, and y - z >= -5 with z in [0, 3]: y = -5
    const free = { ...model, sense: "min", col_lb: [null, 0], row_lb: [-5], row_ub: [null] };
    const minimum = await engine.solveModel(free, solveOptions());
    expect(minimum.status).toBe("optimal");
    expect(minimum.objective).toBeCloseTo(-5, 9);
  });

  // A model with no integer column is a plain linear program: HiGHS runs no tree search for it, and reports -1 nodes and a dual bound of 0.
  const lpModel = lpMilp;

  it("answers a model with no integer column as the linear program it is: optimal, the bound is the optimum, and no nodes", async () => {
    const { engine } = await load();
    // maximise 10 + 2x + y with x <= 4, y <= 3 and x + y <= 5: x = 4, y = 1, 19
    const result = await engine.solveModel(lpModel(), solveOptions());
    expect(result).toMatchObject({ status: "optimal", proven: true, label: null, gap: 0, nodes: 0 });
    expect(result.objective).toBeCloseTo(19, 9);
    expect(result.bound).toBeCloseTo(19, 9); // not the 10 of "the constant and a dual bound of 0"
    expect(result.x[0]).toBeCloseTo(4, 9);
    expect(result.x[1]).toBeCloseTo(1, 9);
    // the same for a minimisation, where the bound is below, not above
    const down = await engine.solveModel({ ...lpModel(), sense: "min", c: [2, 1], col_lb: [-1, -2], const: -3 }, solveOptions());
    expect(down).toMatchObject({ status: "optimal", nodes: 0 });
    expect(down.objective).toBeCloseTo(-3 + 2 * -1 + -2, 9);
    expect(down.bound).toBeCloseTo(down.objective, 9);
  });

  /** A linear program of `n` columns and `m` rows (every row a sum of about forty columns, at most 500), too big to be solved at a glance. */
  function wideLp(n, m) {
    const start = [0];
    const index = [];
    const value = [];
    for (let r = 0; r < m; r += 1) {
      const columns = new Map();
      for (let k = 0; k < 40; k += 1) columns.set((r * 13 + k * 7) % n, 1 + ((r + k) % 5));
      for (const column of [...columns.keys()].sort((a, b) => a - b)) {
        index.push(column);
        value.push(columns.get(column));
      }
      start.push(index.length);
    }
    return {
      version: 1,
      sense: "max",
      const: 7,
      col_lb: new Array(n).fill(0),
      col_ub: new Array(n).fill(10),
      integrality: new Array(n).fill(0),
      c: Array.from({ length: n }, (_, j) => 1 + (j % 7)),
      row_lb: new Array(m).fill(null),
      row_ub: new Array(m).fill(500),
      A: { start, index, value },
    };
  }

  it("reports no bound, no gap and no nodes while a linear program is solved, as it does when it is done: the solver calls nothing back for it", async () => {
    const { engine } = await load();
    for (const [name, model, budgetMs] of [["the small one", lpModel(), 20_000], ["400 by 300", wideLp(400, 300), 20_000], ["3000 by 2500, out of time", wideLp(3000, 2500), 400]]) {
      const reports = [];
      const result = await engine.solveModel(model, { budgetMs, startedAt: performance.now(), onProgress: (report) => reports.push(report) });
      expect(reports[0], name).toEqual({ phase: "building" });
      for (const report of reports) {
        for (const field of ["bound", "gap", "nodes"]) expect(report, `${name}: ${JSON.stringify(report)}`).not.toHaveProperty(field);
      }
      expect(result.nodes, name).toBe(0);
      if (result.status === "optimal") expect(result.bound, name).toBeCloseTo(result.objective, 6);
      else expect(result.bound, `${name}: out of time, with no bound to give`).toBeNull();
    }
  }, 30_000);

  it("answers a linear program through the whole protocol: the reply passes the page's checks and the worker stays", async () => {
    const { fetchImpl } = wasmFetch();
    const harnessEngine = {
      load: (args) => loadHighsEngine({ ...args, manifest: manifestFor(wasmBytes.length), fetchImpl, baseUrl: `${ORIGIN}/assets/engine/worker-BBBBBBBB.js` }),
    };
    const h = makeHarness({ engine: harnessEngine, manifest: REAL_MANIFEST_JSON, workerManifest: parseManifest(REAL_MANIFEST_JSON), now: () => performance.now() });
    const result = await h.client.solve({ v: 1, kind: "model", model: lpModel(), budgetMs: 20000 });
    expect(result).toMatchObject({ kind: "model", status: "optimal", proven: true, nodes: 0, gap: 0 });
    expect(result.objective).toBeCloseTo(19, 9);
    expect(result.bound).toBeCloseTo(19, 9);
    const again = await h.client.solve({ v: 1, kind: "model", model: handMilp(), budgetMs: 20000 }); // a MIP on the same worker after it
    expect(again.status).toBe("optimal");
    expect(h.workers).toHaveLength(1); // the reply was not a protocol violation, so the worker was not dropped
  });

  it("says infeasible when no choice meets the rows, with no kit", async () => {
    const { engine } = await load();
    const result = await engine.solveModel(infeasibleMilp(), solveOptions());
    expect(result).toMatchObject({ status: "infeasible", proven: true, x: null, objective: null });
  });

  it("says the solver's status when it is neither optimal, infeasible nor out of time, and the engine stays usable", async () => {
    const { engine } = await load();
    // maximise y, with no upper bound on y and nothing to hold it
    const model = { version: 1, sense: "max", const: 0, col_lb: [0], col_ub: [null], integrality: [0], c: [1], row_lb: [], row_ub: [], A: { start: [0], index: [], value: [] } };
    const failure = await engine.solveModel(model, solveOptions()).catch((error) => error);
    expect(failure).toBeInstanceOf(EngineFault);
    expect(failure).toMatchObject({ code: "solver" });
    expect(failure.message).toMatch(/unbounded/i);
    expect((await engine.solveModel(handMilp(), solveOptions())).status).toBe("optimal");
  });

  it("tells a model the solver refuses (its fault) from a failure of the WebAssembly (not its fault)", () => {
    class HighsError extends Error {}
    const fake = (thrown) => ({
      infinity: Infinity,
      errors: { HighsError },
      constants: { objectiveSense: { maximize: 1, minimize: -1 } },
      createModel() {
        throw thrown;
      },
    });
    const model = validateRequest(modelRequest()).model;
    const options = { budgetMs: 1000, startedAt: 0, now: () => 0 };
    expect(() => solveModelWith(fake(new HighsError("rows do not fit")), model, options)).toThrow(EngineFault);
    try {
      solveModelWith(fake(new HighsError("rows do not fit")), model, options);
    } catch (error) {
      expect(error).toMatchObject({ code: "bad-model" });
    }
    const abort = new WebAssembly.RuntimeError("Aborted(OOM)");
    expect(() => solveModelWith(fake(abort), model, options)).toThrow(abort);
  });

  it("answers an empty model without calling the solver, as the Python side does", async () => {
    const { engine } = await load();
    const empty = { version: 1, sense: "max", const: 5, col_lb: [], col_ub: [], integrality: [], c: [], row_lb: [-1], row_ub: [1], A: { start: [0, 0], index: [], value: [] } };
    expect(await engine.solveModel(empty, solveOptions())).toMatchObject({ status: "optimal", objective: 5, x: [], proven: true });
    const impossible = { ...empty, row_lb: [1], row_ub: [2] };
    expect(await engine.solveModel(impossible, solveOptions())).toMatchObject({ status: "infeasible", x: null });
  });

  it("returns the best kit found and says it is not proven optimal when the time limit comes first", async () => {
    const { engine } = await load();
    const model = knapsackMilp();
    const watch = stopwatch();
    const result = await engine.solveModel(model, { budgetMs: 400, startedAt: performance.now(), onProgress() {} });
    expectWithin(watch.stop(), 5000, "a solve with a budget of 400 ms stops");
    expect(result.status).toBe("time_limit");
    expect(result.proven).toBe(false);
    if (result.x === null) {
      expect(result.label).toBe(LABEL_NO_INCUMBENT);
      expect(result.objective).toBeNull();
    } else {
      expect(result.label).toBe(LABEL_TIME_LIMIT);
      expect(check(model, result.x).problems).toEqual([]);
      expect(result.objective).toBeCloseTo(check(model, result.x).objective, 6);
    }
  });

  it("counts the time already spent against the budget", async () => {
    const { engine } = await load();
    const watch = stopwatch();
    const began = performance.now();
    const result = await engine.solveModel(knapsackMilp(), { budgetMs: 400, startedAt: began - 399, onProgress() {} });
    expect(result.status).toBe("time_limit");
    expectWithin(watch.stop(), 2000, "a solve that has 1 ms of its budget left stops"); // a second of the budget was left, not a whole solve's worth
  });

  it("reports an improving solution as progress while it solves", async () => {
    const { engine } = await load();
    const seen = [];
    await engine.solveModel(knapsackMilp(7, 40, 4), { budgetMs: 5000, startedAt: performance.now(), onProgress: (p) => seen.push(p) });
    const solving = seen.filter((p) => p.phase === "solving");
    expect(seen[0]).toEqual({ phase: "building" });
    expect(solving.length).toBeGreaterThan(0);
    for (const p of solving) {
      expect(Number.isFinite(p.elapsedMs)).toBe(true);
      if (p.objective !== undefined) expect(Number.isFinite(p.objective)).toBe(true);
    }
  });

  it("reuses a compiled module: no download, no compile, the same answers", async () => {
    const first = await load();
    const second = await load({ module: first.engine.module });
    expect(second.asked).toEqual([]);
    expect(second.engine.module).toBeUndefined(); // nothing new was compiled, so there is nothing new to keep
    expect(second.progress.map((p) => p.phase)).not.toContain("loading");
    const model = handMilp();
    const a = await first.engine.solveModel(model, solveOptions());
    const b = await second.engine.solveModel(model, solveOptions());
    expect(b).toEqual({ ...a, elapsedMs: b.elapsedMs });
  });

  /**
   * HiGHS straight from the package (in Node it reads its own file), with every model it makes watched: its options as they are read back from the
   * solver just before it is disposed, and how often it was disposed. So that what the worker sets on a solver is checked in the solver, not in
   * the constant it was set from.
   */
  async function watchedHighs() {
    const highs = await loadHighs();
    const made = [];
    const create = highs.createModel.bind(highs);
    highs.createModel = (data) => {
      const solver = create(data);
      const seen = { disposals: 0, options: null };
      const dispose = solver.dispose.bind(solver);
      solver.dispose = () => {
        seen.options = Object.fromEntries([...Object.keys(SOLVER_OPTIONS), "time_limit"].map((name) => [name, solver.options.get(name)]));
        seen.disposals += 1;
        return dispose();
      };
      made.push(seen);
      return solver;
    };
    return { highs, made };
  }

  it("sets the project's options on the solver itself, and a time limit of what is left of the budget on the clock it is given", async () => {
    const { highs, made } = await watchedHighs();
    // 400 ms of a budget of 1,000 are spent: the solver gets 600 ms
    solveModelWith(highs, handMilp(), { budgetMs: 1000, startedAt: 600, now: () => 1000, onProgress() {} });
    expect(made).toHaveLength(1);
    expect(made[0].options).toMatchObject(SOLVER_OPTIONS); // read back from the solver: set, not only declared
    expect(made[0].options.time_limit).toBeCloseTo(0.6, 12);
    // all of it spent: no time at all (never a negative one, never the whole budget again)
    solveModelWith(highs, handMilp(), { budgetMs: 1000, startedAt: -5000, now: () => 1000, onProgress() {} });
    expect(made[1].options.time_limit).toBe(0);
  });

  it("frees every model it makes, the one that is solved and the one that fails alike", async () => {
    const { highs, made } = await watchedHighs();
    for (let i = 0; i < 5; i += 1) solveModelWith(highs, handMilp(), solveOptions(5000));
    const unbounded = canonical({ version: 1, sense: "max", const: 0, col_lb: [0], col_ub: [null], integrality: [0], c: [1], row_lb: [], row_ub: [], A: { start: [0], index: [], value: [] } });
    expect(() => solveModelWith(highs, unbounded, solveOptions())).toThrow(EngineFault);
    expect(made.map((m) => m.disposals)).toEqual([1, 1, 1, 1, 1, 1]);
  });

  it("says nothing was found in time, with no solution at all, when the time is up before the solver has one", async () => {
    const { highs } = await watchedHighs();
    // the time is up before the solver starts. HiGHS still has a vector of zeros to show for it, which breaks the rows of this model: it must not be offered
    const result = solveModelWith(highs, handMilp(), { budgetMs: 1, startedAt: -10_000, now: () => 0, onProgress() {} });
    expect(result).toMatchObject({ status: "time_limit", proven: false, x: null, objective: null, label: LABEL_NO_INCUMBENT });
    expect(result.gap).toBeNull();
  });

  it("reads a row with no lower bound as unbounded below, and the other bounds of a row, a column and the constant as they are", async () => {
    const { engine } = await load();
    // minimise y, with y <= 4 (the row has no lower bound) and y >= -10: -10. A lower bound of 0 for the row would give 0
    const open = canonical({ version: 1, sense: "min", const: 0, col_lb: [-10], col_ub: [null], integrality: [0], c: [1], row_lb: [null], row_ub: [4], A: { start: [0, 1], index: [0], value: [1] } });
    expect((await engine.solveModel(open, solveOptions())).objective).toBeCloseTo(-10, 9);
    // maximise y, with y >= -4 (the row has no upper bound) and y <= 5,000,000: 5,000,005 with the constant. A row bound of 0, or of a million
    // standing in for "none", would give 5 or 1,000,005
    const above = canonical({ version: 1, sense: "max", const: 5, col_lb: [null], col_ub: [5_000_000], integrality: [0], c: [1], row_lb: [-4], row_ub: [null], A: { start: [0, 1], index: [0], value: [1] } });
    expect((await engine.solveModel(above, solveOptions())).objective).toBeCloseTo(5_000_005, 6);
    // a row that binds from below: minimise y with y >= 3 (row) and y free: 3
    const binds = canonical({ version: 1, sense: "min", const: 0, col_lb: [null], col_ub: [null], integrality: [0], c: [1], row_lb: [3], row_ub: [null], A: { start: [0, 1], index: [0], value: [1] } });
    expect((await engine.solveModel(binds, solveOptions())).objective).toBeCloseTo(3, 9);
  });

  it("counts a solve on the one clock the worker core is given, whatever the process's own clock says", async () => {
    // the core's clock stands still at 0, a long way from performance.now(): if the engine took its time from performance.now(), a budget of one second would long be spent
    const { fetchImpl } = wasmFetch();
    const harnessEngine = {
      load: (args) => loadHighsEngine({ ...args, manifest: manifestFor(wasmBytes.length), fetchImpl, baseUrl: `${ORIGIN}/assets/engine/worker-BBBBBBBB.js` }),
    };
    const h = makeHarness({ engine: harnessEngine, manifest: REAL_MANIFEST_JSON, workerManifest: parseManifest(REAL_MANIFEST_JSON), now: () => 0 });
    const result = await h.client.solve({ v: 1, kind: "model", model: handMilp(), budgetMs: 1000 });
    expect(result).toMatchObject({ status: "optimal", proven: true, elapsedMs: 0 }); // measured on that clock too
    expect(result.objective).toBeCloseTo(handOptimum().objective, 9);
  });

  it("solves several models one after another on the same engine, and frees each", async () => {
    const { engine } = await load();
    for (let i = 0; i < 25; i += 1) {
      const result = await engine.solveModel(handMilp(), solveOptions());
      expect(result.objective).toBeCloseTo(handOptimum().objective, 9);
    }
  });

  const BAD_FILES = {
    "an answer of 404": [{ status: 404, body: "<!doctype html>" }, /404/],
    "a web page in place of the file": [{ type: "text/html", body: "<!doctype html><p>TrioForge</p>" }, /type/],
    "a file of the wrong size": [{ body: wasmBytes.subarray(0, 1000) }, /size|incomplete/i],
    "bytes that are not WebAssembly": [{ body: new Uint8Array(wasmBytes.length) }, /./],
  };
  for (const [name, [fetchOptions, pattern]] of Object.entries(BAD_FILES)) {
    it(`fails with a message for ${name}`, async () => {
      await expect(load({ fetch: fetchOptions })).rejects.toThrow(pattern);
    });
  }

  it("fails, and does not hang, when the compiled module it was given is not the solver", async () => {
    const wrong = new WebAssembly.Module(EMPTY_MODULE_BYTES);
    const outcome = await Promise.race([
      load({ module: wrong }).then(
        () => "loaded",
        (error) => error,
      ),
      new Promise((resolveTimeout) => setTimeout(() => resolveTimeout("hung"), 8000)),
    ]);
    expect(outcome).toBeInstanceOf(Error);
  }, 15000);

  it("runs the whole protocol on the real engine: client, worker core, real HiGHS", async () => {
    const { fetchImpl, asked } = wasmFetch();
    const harnessEngine = {
      load: (args) => loadHighsEngine({ ...args, manifest: manifestFor(wasmBytes.length), fetchImpl, baseUrl: `${ORIGIN}/assets/engine/worker-BBBBBBBB.js` }),
    };
    const h = makeHarness({ engine: harnessEngine, manifest: REAL_MANIFEST_JSON, workerManifest: parseManifest(REAL_MANIFEST_JSON) });
    const progress = [];
    const model = handMilp();
    const result = await h.client.solve({ v: 1, kind: "model", model, budgetMs: 20000 }, { onProgress: (p) => progress.push(p) });
    expect(result).toMatchObject({ kind: "model", status: "optimal", proven: true });
    expect(result.objective).toBeCloseTo(handOptimum().objective, 9);
    expect(check(model, result.x).problems).toEqual([]);
    expect(progress.map((p) => p.phase)).toEqual(expect.arrayContaining(["loading", "compiling", "building"]));
    // the next request uses the loaded engine: same worker, no second download
    const again = await h.client.solve({ v: 1, kind: "model", model: infeasibleMilp(), budgetMs: 20000 });
    expect(again.status).toBe("infeasible");
    expect(h.workers).toHaveLength(1);
    expect(asked).toEqual([`${ORIGIN}${WASM_PATH}`]);
    // after the worker is dropped the next one is built from the kept module, with no download either
    h.workers[0].crash();
    await tick(10);
    const third = await h.client.solve({ v: 1, kind: "model", model, budgetMs: 20000 });
    expect(third.objective).toBeCloseTo(handOptimum().objective, 9);
    expect(h.workers).toHaveLength(2);
    expect(asked).toEqual([`${ORIGIN}${WASM_PATH}`]);
    expect(h.client.stats()).toMatchObject({ spawns: 2, moduleKept: true });
  });
});

// ---- the code itself ---------------------------------------------------------------------------------------------------------

describe("the source", () => {
  const files = [
    ...readdirSync(resolve(STATIC, "engine")).filter((name) => name.endsWith(".js")).map((name) => resolve(STATIC, "engine", name)),
    resolve(STATIC, "tt-policy.js"),
  ];
  // the sinks the page's policy exists to keep out (spec 8.5): none of them may appear in the engine's code, comments included
  const SINKS = new RegExp(
    [
      "innerHTML",
      "outerHTML",
      "insertAdjacentHTML",
      "document\\s*\\.\\s*write",
      "createContextualFragment",
      "\\beval\\s*\\(",
      "new\\s+Function",
      "setAttribute\\(\\s*[\"']on",
      "srcdoc",
      "DOMParser",
      "execScript",
      "importScripts",
      "\\bset(?:Timeout|Interval)\\(\\s*[\"'`]",
      "createObjectURL",
      "new\\s+Blob",
    ].join("|"),
  );

  it("lists the files the plan names", () => {
    const names = files.map((f) => f.slice(STATIC.length + 1).replaceAll("\\", "/"));
    expect(names).toEqual(expect.arrayContaining(["engine/worker.js", "engine/client.js", "tt-policy.js"]));
  });

  for (const file of files) {
    const name = file.slice(STATIC.length + 1).replaceAll("\\", "/");
    it(`${name} has no string-to-code or string-to-page sink`, () => {
      const text = readFileSync(file, "utf8");
      expect(SINKS.exec(text)?.[0] ?? null, name).toBeNull();
    });
    it(`${name} names no other site and opens no other channel`, () => {
      const text = readFileSync(file, "utf8");
      expect(text).not.toMatch(/https?:\/\//);
      expect(text).not.toMatch(/\bWebSocket\b|\bXMLHttpRequest\b|\bEventSource\b|\bsendBeacon\b/);
    });
    if (name.startsWith("engine/")) {
      // Safari 15.0 to 15.3 runs module workers but lacks what came in 15.4: the static hasOwn of Object, the at and findLast methods of
      // arrays, structuredClone. A page on those versions would get a TypeError where a plain check was meant, so none of them is used.
      it(`${name} uses nothing that Safari 15.0 to 15.3 lacks`, () => {
        const text = readFileSync(file, "utf8");
        const found = [...text.matchAll(/Object\.hasOwn\b|\.findLast\(|\.findLastIndex\(|\.at\(|structuredClone\(/g)].map((match) => match[0]);
        expect(found, name).toEqual([]);
      });
    }
  }

  it("scans the engine's files for the calls that Safari 15.0 to 15.3 lacks (the scan sees them where they are)", () => {
    const pattern = /Object\.hasOwn\b|\.findLast\(|\.findLastIndex\(|\.at\(|structuredClone\(/g;
    const probes = ["Object.hasOwn(x, y)", "list.findLast(f)", "list.findLastIndex(f)", "list.at(-1)", "structuredClone(x)"];
    for (const probe of probes) expect([...probe.matchAll(pattern)], probe).toHaveLength(1);
    for (const fine of ["Object.prototype.hasOwnProperty.call(x, y)", "list[list.length - 1]", "format(x)", "data.attributes"]) expect([...fine.matchAll(pattern)], fine).toHaveLength(0);
  });

  it("the page-side files never read a worker address from a request", () => {
    const client = readFileSync(resolve(STATIC, "engine/client.js"), "utf8");
    expect(client).not.toMatch(/request\.(url|href|src|wasm|worker)/i);
  });
});
