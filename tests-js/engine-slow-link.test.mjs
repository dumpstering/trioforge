// A visitor on a slow link: the first Equip now downloads the data (the manifest of the trio, the item table, the bundle) inside the request, and the page's
// watchdog, which stops a worker that has stopped answering, must not take a download that keeps delivering for a hang. Here the real client talks to the
// real worker core on the real solver (in this thread, as in engine-scenario-client.test.mjs), and the fetch of the data is slow: pieces of 512 bytes, one
// every 300 milliseconds, on fake timers. The budget of the request is a second, so the watchdog's window (the budget and five seconds) is 6 seconds, and
// the download takes some twenty.
//
// What the page asks of the worker: every report of progress of a request is a sign of life that gives the watchdog a new window; a download that stops
// is bounded by the stall rule of the download (no byte for STARTUP_STALL_MS), not by the watchdog; and the budget of the solve is counted from the moment
// the data is in, so a download does not eat it, while the elapsed time of the answer still counts the whole request.

import loadHighs from "highs";
import { JSDOM } from "jsdom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { createEngineClient } from "../pipeline/trioforge/site/static/engine/client.js";
import { STARTUP_STALL_MS, WATCHDOG_GRACE_MS } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { createWorkerCore } from "../pipeline/trioforge/site/static/engine/worker.js";
import { BASE, EQUIP_NOW, ITEMS_BYTES, SLUG, makeSite, siteFetch } from "./engine-site-fixture.mjs";

vi.setConfig({ testTimeout: 120_000 });

// The real timer, the real turn of the event loop and the real clock, taken before a test installs the fake ones.
const realSetTimeout = globalThis.setTimeout;
const realSetImmediate = globalThis.setImmediate;
const realNow = performance.now.bind(performance);
const realDelay = (ms) => new Promise((resolve) => realSetTimeout(resolve, ms)); // real time passes (work that takes real time)
const realTurn = () => new Promise((resolve) => realSetImmediate(resolve)); // the real event loop has a turn: what is waiting in it (the end of a digest, say) is handled
/** How long `run` waits, in real time, for a request that has used up its fake time and is still going, and the most it ever waits. */
const REAL_FLOOR_MS = 10_000;
const REAL_CEILING_MS = 90_000;

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});
beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

const C = EQUIP_NOW.cases[1];
const equipNow = (over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "equip-now", scenario: { ...C.scenario }, owned: C.owned.map((pair) => [...pair]), budgetMs: 1000, ...over });
const clock = () => Date.now();

class FakeWorker {
  constructor(core) {
    this.core = core;
    this.terminated = false;
    this.onmessage = null;
    this.onerror = null;
    this.onmessageerror = null;
    core.attach((message) =>
      queueMicrotask(() => {
        if (!this.terminated) this.onmessage?.({ data: structuredClone(message) });
      }),
    );
  }

  postMessage(data) {
    const copy = structuredClone(data);
    queueMicrotask(() => {
      if (!this.terminated) this.core.handle(copy);
    });
  }

  terminate() {
    this.terminated = true;
  }
}

/** A body that comes in pieces of `size` bytes, one every `gap` milliseconds (on the fake clock); after `stopAfter` pieces, none at all. */
function slowBody(bytes, { size = 512, gap = 300, stopAfter = Infinity } = {}) {
  let at = 0;
  let given = 0;
  return new ReadableStream({
    async pull(controller) {
      await new Promise((resolve) => setTimeout(resolve, gap));
      if (given >= stopAfter) return new Promise(() => {}); // the connection has gone quiet
      if (at >= bytes.length) {
        controller.close();
        return undefined;
      }
      controller.enqueue(bytes.slice(at, at + size));
      at += size;
      given += 1;
      return undefined;
    },
  });
}

function harness({ slow = {}, only } = {}) {
  const site = makeSite();
  const fast = siteFetch(site);
  const asked = [];
  const slowFetch = async (url, init) => {
    asked.push(new URL(String(url)).pathname);
    const path = new URL(String(url)).pathname;
    const bytes = site.files.get(path);
    if (bytes === undefined || (only !== undefined && !only(path, site))) return fast.fetchImpl(url, init);
    return new Response(slowBody(bytes, typeof slow === "function" ? slow(path, site) : slow), { status: 200, headers: { "content-type": "application/json" } });
  };
  const dom = new JSDOM('<!doctype html><html><body><main id="main"></main></body></html>', { url: "https://trioforge.test/trio/pal-mnk-ber/" });
  const pageFetch = async (url) => {
    const text = String(url) === "/engine-manifest.json" ? JSON.stringify(site.manifestJson) : String(url) === `/engine-trios/${SLUG}.json` ? JSON.stringify(site.trioJson[SLUG]) : undefined;
    return text === undefined ? { ok: false, status: 404, text: async () => "not found" } : { ok: true, status: 200, text: async () => text };
  };
  const workers = [];
  const scenarios = createScenarioEngine({ highs, fetchImpl: slowFetch, baseUrl: BASE, now: clock });
  const createWorker = () => {
    let sink = () => {};
    const core = createWorkerCore({
      post: (message) => sink(message),
      loadManifest: async () => site.manifest,
      loadEngine: async () => ({
        version: "1.15.3",
        async solveModel() {
          throw new Error("no model here");
        },
        equipNow: (request, options) => scenarios.equipNow(request, options),
      }),
      now: clock,
    });
    core.attach = (fn) => {
      sink = fn;
    };
    const worker = new FakeWorker(core);
    workers.push(worker);
    return worker;
  };
  const client = createEngineClient({ window: dom.window, document: dom.window.document, fetch: pageFetch, createWorker, consent: { ask: async () => true }, trustedTypes: null });
  return { client, workers, site, asked, scenarios };
}

/**
 * Run a request on the fake clock until it ends: what it came to, and how long it took (in fake time).
 *
 * The fake clock goes in steps of 100 ms, and after each step the real event loop has a turn. Work that no timer drives (the digest of a file, WebAssembly, a worker's messages) goes
 * on in real time, and the fake clock, which goes as fast as the CPU does (300 s of it in a tenth of a second), ran out while that work was still pending: on a busy machine the
 * request had not ended, and the test read a result that was not there. Now what the request waits for is real time as well as fake time: one that is still going when `limitMs` of
 * fake time has passed is given up on only when REAL_FLOOR_MS of real time has passed too (it hung), and in any case after REAL_CEILING_MS. (Fake time that passes while such work is
 * pending does no harm: the timers that are due fire as they would have, and a worker that is loading data reports every second, which gives the watchdog new windows.)
 */
async function run(promise, limitMs = 300_000) {
  let outcome;
  promise.then(
    (value) => (outcome = { ok: true, value }),
    (error) => (outcome = { ok: false, error }),
  );
  const began = Date.now();
  const realBegan = realNow();
  while (outcome === undefined) {
    const real = realNow() - realBegan;
    if (real >= REAL_CEILING_MS || (Date.now() - began >= limitMs && real >= REAL_FLOOR_MS)) break;
    await vi.advanceTimersByTimeAsync(100);
    await realTurn();
  }
  return { outcome, tookMs: Date.now() - began };
}

describe("a download that keeps delivering", () => {
  it("is not stopped by the watchdog, though it takes longer than the budget and the grace together: every report of progress gives the request a new window", async () => {
    const h = harness({ slow: { size: 512, gap: 300 } });
    const reports = [];
    const { outcome, tookMs } = await run(h.client.solve(equipNow(), { onProgress: (p) => reports.push({ ...p, at: Date.now() }) }));
    expect(outcome, "the request ended").toBeDefined();
    expect(outcome.ok, outcome.error && `${outcome.error.code}: ${outcome.error.message}`).toBe(true);
    expect(tookMs, "it took longer than the window the watchdog gives a request without a sign of life").toBeGreaterThan(1000 + WATCHDOG_GRACE_MS);
    expect(outcome.value).toMatchObject({ status: "optimal", proven: true, F: C.F, kit: C.kit });
    expect(h.client.stats()).toMatchObject({ spawns: 1, solves: 1 }); // no worker was stopped, and none started again
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].terminated).toBe(false);
    expect(h.asked.filter((path) => path === h.site.itemsPath)).toHaveLength(1); // the item table was fetched once, not again after a stop
    expect(h.asked.filter((path) => path === h.site.bundlePath)).toHaveLength(1);
    // the reports came often enough for the window: none further apart than the grace
    const loading = reports.filter((p) => p.phase === "loading");
    expect(loading.length).toBeGreaterThan(5);
    for (let n = 1; n < reports.length; n += 1) expect(reports[n].at - reports[n - 1].at).toBeLessThan(WATCHDOG_GRACE_MS);
    expect(reports.at(-1).phase).toBe("building");
  });

  it("counts the elapsed time of the answer from the start of the request, the download included", async () => {
    const h = harness({ slow: { size: 512, gap: 300 } });
    const { outcome, tookMs } = await run(h.client.solve(equipNow()));
    expect(outcome.ok).toBe(true);
    expect(outcome.value.elapsedMs).toBeGreaterThan(15_000);
    expect(outcome.value.elapsedMs).toBeLessThanOrEqual(tookMs);
  });

  it("leaves the whole budget of the request to the solve once the data is in: a download of twenty seconds does not eat a budget of a second", async () => {
    const h = harness({ slow: { size: 512, gap: 300 } });
    const { outcome, tookMs } = await run(h.client.solve(equipNow({ budgetMs: 1000 })));
    expect(tookMs).toBeGreaterThan(15_000);
    // (counted from the arrival of the request, as before, the budget would have been gone before the solver was called, and the answer would have been
    // "not found in time")
    expect(outcome.ok).toBe(true);
    expect(outcome.value).toMatchObject({ status: "optimal", proven: true, label: null });
    expect(outcome.value.kit).not.toBeNull();
  });

  it("is told by the download itself when it stops: no byte for the stall time ends the request with engine-load, not with the watchdog, and the worker stays", async () => {
    const h = harness({ slow: { size: 512, gap: 300, stopAfter: 3 }, only: (path, site) => path === site.itemsPath });
    const { outcome, tookMs } = await run(h.client.solve(equipNow()));
    expect(outcome.ok).toBe(false);
    expect(outcome.error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/stalled/i) });
    expect(tookMs).toBeGreaterThanOrEqual(STARTUP_STALL_MS);
    expect(tookMs).toBeLessThan(STARTUP_STALL_MS + 5000);
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].terminated).toBe(false);
    expect(h.client.stats()).toMatchObject({ spawns: 1, updated: false });
  });
});

describe("a worker that has gone quiet", () => {
  it("is stopped by the watchdog a window after its last sign of life, as before", async () => {
    // a worker that takes the request and says nothing: no data loading, no report
    const quiet = harness();
    quiet.scenarios.equipNow = () => new Promise(() => {});
    const { outcome, tookMs } = await run(quiet.client.solve(equipNow()), 60_000);
    expect(outcome.ok).toBe(false);
    expect(outcome.error).toMatchObject({ code: "watchdog" });
    expect(tookMs).toBeGreaterThanOrEqual(1000 + WATCHDOG_GRACE_MS - 200);
    expect(tookMs).toBeLessThan(1000 + WATCHDOG_GRACE_MS + 2000);
    expect(quiet.workers[0].terminated).toBe(true);
  });
});

describe("the clock of these tests", () => {
  it("waits for work that no timer drives: when the checks of the files (digests) take real time, the request is waited for and the fake time does not run out meanwhile", async () => {
    const subtle = globalThis.crypto.subtle;
    const real = subtle.digest;
    let late = 0;
    subtle.digest = async function (...args) {
      late += 1;
      await realDelay(300); // (a busy machine: the digest of a file comes late, in real time)
      return Reflect.apply(real, this, args);
    };
    try {
      const h = harness({ slow: { size: 512, gap: 300 } });
      const { outcome } = await run(h.client.solve(equipNow()));
      expect(late, "the files were checked by the slow digest").toBeGreaterThan(0);
      expect(outcome, "the request ended").toBeDefined();
      expect(outcome.ok, outcome.error && `${outcome.error.code}: ${outcome.error.message}`).toBe(true);
      expect(outcome.value).toMatchObject({ status: "optimal", proven: true, F: C.F, kit: C.kit });
    } finally {
      delete subtle.digest; // (the one of the prototype stands again)
    }
  });
});

describe("the fixture", () => {
  it("has an item table of some ten kilobytes, which at 512 bytes every 300 milliseconds takes longer than the window of the watchdog", () => {
    expect(Math.ceil(ITEMS_BYTES.length / 512) * 300).toBeGreaterThan(1000 + WATCHDOG_GRACE_MS);
  });
});
