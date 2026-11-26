// The page's side of Equip now (client.js): a scenario request of mode "equip-now" goes to the worker, behind the same question and the same download as
// any request (the consent and the loading are unchanged), and its answer is checked against what was asked. A scenario request of a mode that has no shape (the
// old generic shape, with candidates) is a bad request at once, before the visitor is asked and before anything is read or downloaded (the other modes are in
// engine-scenario-modes-client.test.mjs). The question names the size of the download
// that the request makes (the item table and the bundle of the trio are in it), which is read from the manifest of the trio, fetched before the question; and
// when the data cannot be loaded, or the manifest of the trio is of another release, the page reads the main manifest again: a release that came since
// it began is told with the notice that the page has to be reloaded, not with an error. The worker here is the real worker core on the real solver in this
// thread, with a fake fetch for the data of the synthetic site fixture; the browser's own run of it is tests-e2e/engine.spec.mjs.

import loadHighs from "highs";
import { JSDOM } from "jsdom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { createEngineClient } from "../pipeline/trioforge/site/static/engine/client.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { createWorkerCore } from "../pipeline/trioforge/site/static/engine/worker.js";
import { BASE, EQUIP_NOW, SLUG, makeSite, siteFetch } from "./engine-site-fixture.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const C = EQUIP_NOW.cases[1];
const equipNow = (over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "equip-now", scenario: { ...C.scenario }, owned: C.owned.map((pair) => [...pair]), budgetMs: 120_000, ...over });

/** The core of a worker on the real solver, in this thread, and a worker object for the client to talk to; `answer` may change what Equip now says. */
class FakeWorker {
  constructor(core) {
    this.core = core;
    this.terminated = false;
    this.sent = [];
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
    this.sent.push(copy);
    queueMicrotask(() => {
      if (!this.terminated) this.core.handle(copy);
    });
  }

  terminate() {
    this.terminated = true;
  }
}

function harness({ answer, consent = { ask: async () => true }, site = makeSite(), workerFetch } = {}) {
  const fetching = siteFetch(site, workerFetch);
  const dom = new JSDOM('<!doctype html><html><body><main id="main"></main></body></html>', { url: "https://trioforge.test/trio/pal-mnk-ber/" });
  const manifestFetches = [];
  // what the page's fetch answers for the two manifests: a test changes it to play a release that comes while the page is open
  const state = { manifest: () => JSON.stringify(site.manifestJson), trio: (slug) => (site.trioPaths[slug] ? JSON.stringify(site.trioJson[slug]) : undefined) };
  const pageFetch = async (url) => {
    manifestFetches.push(String(url));
    const text = String(url) === "/engine-manifest.json" ? state.manifest() : String(url).startsWith("/engine-trios/") ? state.trio(String(url).slice("/engine-trios/".length).replace(/\.json$/, "")) : undefined;
    if (text === undefined) return { ok: false, status: 404, text: async () => "not found" };
    return { ok: true, status: 200, text: async () => text };
  };
  const workers = [];
  const createWorker = () => {
    const scenarios = createScenarioEngine({ highs, fetchImpl: fetching.fetchImpl, baseUrl: BASE });
    let sink = () => {};
    const core = createWorkerCore({
      post: (message) => sink(message),
      loadManifest: async () => site.manifest,
      loadEngine: async () => ({
        version: "1.15.3",
        async solveModel() {
          throw new Error("no model here");
        },
        equipNow: answer ?? ((request, options) => scenarios.equipNow(request, options)),
      }),
    });
    core.attach = (fn) => {
      sink = fn;
    };
    const worker = new FakeWorker(core);
    workers.push(worker);
    return worker;
  };
  const client = createEngineClient({ window: dom.window, document: dom.window.document, fetch: pageFetch, createWorker, consent, trustedTypes: null });
  return { client, workers, site, ...fetching, manifestFetches, dom, state };
}

describe("Equip now from the page", () => {
  it("goes to the worker, behind the question every request meets, and comes back as the worker's answer", async () => {
    const ask = vi.fn(async () => true);
    const h = harness({ consent: { ask } });
    const progress = [];
    const got = await h.client.solve(equipNow(), { onProgress: (p) => progress.push(p.phase) });
    expect(ask).toHaveBeenCalledTimes(1);
    expect(got).toMatchObject({ kind: "scenario", mode: "equip-now", status: "optimal", proven: true, label: null, F: C.F, value: C.value, kit: C.kit, buffs: C.buffs, hasteAssumed: C.hasteAssumed });
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].sent.map((m) => m.type)).toEqual(["init", "solve"]);
    expect(h.workers[0].sent[1].request).toEqual(equipNow()); // the copy of the request that was checked
    expect(progress).toEqual(expect.arrayContaining(["loading", "building"]));
  });

  it("is the same optimizer for the next request: no question, no worker, no download of the data again", async () => {
    const ask = vi.fn(async () => true);
    const h = harness({ consent: { ask } });
    await h.client.solve(equipNow());
    const fetched = h.asked.length;
    const again = await h.client.solve(equipNow({ owned: C.owned.slice(0, 10) }));
    expect(again.status).toBe("optimal");
    expect(ask).toHaveBeenCalledTimes(1);
    expect(h.workers).toHaveLength(1);
    expect(h.asked).toHaveLength(fetched);
    expect(h.client.stats()).toMatchObject({ spawns: 1, solves: 2 });
  });

  it("is declined as any request is when the visitor says no: nothing is downloaded and the request says why", async () => {
    const h = harness({ consent: { ask: async () => false } });
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "declined" });
    expect(h.workers).toHaveLength(0);
    expect(h.asked).toEqual([]); // (the manifest of the trio was read for the size of the question: a few hundred bytes, no data)
    expect(h.manifestFetches).toEqual(["/engine-manifest.json", `/engine-trios/${SLUG}.json`]);
  });

  it("is checked before anything else, like any request: a hostile one is a bad request with no manifest read, no question and no worker", async () => {
    const ask = vi.fn(async () => true);
    const h = harness({ consent: { ask } });
    for (const hostile of [equipNow({ owned: [["__proto__@4", 1]] }), equipNow({ owned: [["w5@11", 1]] }), equipNow({ candidates: [] }), equipNow({ scenario: { ...C.scenario, race: "x".repeat(60) } })]) {
      await expect(h.client.solve(hostile)).rejects.toMatchObject({ code: "bad-request" });
    }
    expect(ask).not.toHaveBeenCalled();
    expect(h.manifestFetches).toEqual([]);
    expect(h.workers).toHaveLength(0);
  });

  it("is checked against the manifest: a trio or a level it does not list is a bad request before the question", async () => {
    const ask = vi.fn(async () => true);
    const h = harness({ consent: { ask } });
    await expect(h.client.solve(equipNow({ trio: "war-war-war" }))).rejects.toMatchObject({ code: "bad-request" });
    await expect(h.client.solve(equipNow({ level: 55 }))).rejects.toMatchObject({ code: "bad-request" });
    expect(ask).not.toHaveBeenCalled();
    expect(h.workers).toHaveLength(0);
  });

  it("brings the worker's error to the caller with its code, and the worker goes on", async () => {
    const h = harness();
    await expect(h.client.solve(equipNow({ owned: [["w999999@4", 1]] }))).rejects.toMatchObject({ code: "bad-request" });
    expect((await h.client.solve(equipNow())).status).toBe("optimal");
    expect(h.workers).toHaveLength(1);
    expect(h.workers[0].terminated).toBe(false);
  });

  it("drops a worker whose answer claims a kit that the request did not own", async () => {
    const h = harness({
      answer: async () => ({ status: "optimal", proven: true, label: null, F: "5/1", value: 5, kit: ["w90001@4", ...new Array(21).fill(null)], buffs: [], hasteAssumed: 0 }),
    });
    await expect(h.client.solve(equipNow({ owned: [["w90002@0", 1]] }))).rejects.toMatchObject({ code: "protocol" });
    expect(h.workers[0].terminated).toBe(true);
  });

  it("drops a worker whose answer says a value that is not its exact value rounded", async () => {
    const h = harness({
      answer: async () => ({ status: "optimal", proven: true, label: null, F: "5/2", value: 2.6, kit: new Array(22).fill(null), buffs: [], hasteAssumed: 0 }),
    });
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "protocol" });
    expect(h.workers[0].terminated).toBe(true);
  });
});

describe("the question", () => {
  /** A site whose item table and bundle have gzip sizes of their own, so that the figure of the question tells which files it counts. */
  const sized = (items, bundle) => makeSite({ lie: { items: { gzip: items }, bundle: { gzip: bundle } } });

  it("names the size of the download of the request: the worker, the WebAssembly, the item table and the bundle of the trio, from the manifests", async () => {
    // 40,000 + 1,200,000 (the worker and the WebAssembly of the fixture) + 400,000 + 90,000 = 1,730,000
    const ask = vi.fn(async () => true);
    const h = harness({ site: sized(400_000, 90_000), consent: { ask } });
    await h.client.solve(equipNow());
    expect(ask).toHaveBeenCalledTimes(1);
    expect(ask.mock.calls[0][0]).toMatchObject({ megabytes: 1.8 });
    // without the data it would have said 1.3 (the worker and the WebAssembly), or 1.7 (and no bundle)
  });

  it("reads the manifest of the trio before the question, from the address of a trio the main manifest lists", async () => {
    const atTheQuestion = [];
    const h = harness({ consent: { ask: async () => (atTheQuestion.push([...h.manifestFetches]), true) } });
    await h.client.solve(equipNow());
    expect(atTheQuestion).toEqual([["/engine-manifest.json", `/engine-trios/${SLUG}.json`]]);
    expect(h.workers).toHaveLength(1);
  });

  it("reads the manifest of the trio once for the trio, and asks nothing again for the next request", async () => {
    const ask = vi.fn(async () => true);
    const h = harness({ consent: { ask } });
    await h.client.solve(equipNow());
    await h.client.solve(equipNow({ owned: C.owned.slice(0, 5) }));
    expect(h.manifestFetches).toEqual(["/engine-manifest.json", `/engine-trios/${SLUG}.json`]);
    expect(ask).toHaveBeenCalledTimes(1);
  });

  it("names the item table in a question asked before any request, and no bundle (it does not know the trio)", async () => {
    const ask = vi.fn(async () => true);
    const h = harness({ site: sized(400_000, 90_000), consent: { ask } });
    expect(await h.client.askConsent()).toBe(true);
    expect(ask.mock.calls[0][0]).toMatchObject({ megabytes: 1.7 }); // 40,000 + 1,200,000 + 400,000
    expect(h.manifestFetches).toEqual(["/engine-manifest.json"]);
  });

  it("is not asked when the manifest of the trio cannot be read: the request fails with unavailable, and no worker is started", async () => {
    const ask = vi.fn(async () => true);
    const h = harness({ consent: { ask } });
    h.state.trio = () => undefined; // a 404
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "unavailable" });
    h.state.trio = () => "this is not json";
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "unavailable" });
    h.state.trio = () => JSON.stringify({ ...h.site.trioJson[SLUG], url: "https://evil.example/x" });
    const error = await h.client.solve(equipNow()).then(() => null, (e) => e);
    expect(error).toMatchObject({ code: "unavailable" });
    expect(error.message).not.toContain("evil.example");
    expect(ask).not.toHaveBeenCalled();
    expect(h.workers).toHaveLength(0);
    h.state.trio = (slug) => JSON.stringify(h.site.trioJson[slug]); // and it works once the file is right: nothing was kept of the failures
    expect((await h.client.solve(equipNow())).status).toBe("optimal");
  });

  it("is not asked for a manifest of a trio that is larger than the limit of its own", async () => {
    const ask = vi.fn(async () => true);
    const h = harness({ consent: { ask } });
    h.state.trio = () => " ".repeat(9000) + JSON.stringify(h.site.trioJson[SLUG]);
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "unavailable" });
    expect(ask).not.toHaveBeenCalled();
  });
});

describe("a release that comes while the page is open", () => {
  const UPDATED = /was updated\. Reload the page/;
  /** A manifest of the release after: the same site with the release of its data changed. */
  const NEWER = (site) => JSON.stringify({ ...site.manifestJson, data_release: "data-2026-10-20" });
  const NEWER_TRIO = (site) => JSON.stringify({ ...site.trioJson[SLUG], data_release: "data-2026-10-20" });
  const newConsent = () => ({ ask: vi.fn(async () => true), updated: vi.fn(), loading: vi.fn(), close: vi.fn() });

  it("is told with the notice that the page has to be reloaded when a file of the data is gone: the page reads the manifest again and finds another release", async () => {
    const consent = newConsent();
    const h = harness({
      consent,
      workerFetch: {
        serve: (url) => {
          if (new URL(url).pathname !== h.site.itemsPath) return undefined;
          h.state.manifest = () => NEWER(h.site); // the deploy that took the old files away
          return new Response("gone", { status: 404 });
        },
      },
    });
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(UPDATED) });
    expect(consent.updated).toHaveBeenCalledTimes(1);
    expect(h.manifestFetches.filter((url) => url === "/engine-manifest.json")).toHaveLength(2);
    expect(h.client.stats().updated).toBe(true);
    expect(h.workers[0].terminated).toBe(true);
    // and from then on every request fails at once with the same notice, until the page is reloaded
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(UPDATED) });
    expect(h.workers).toHaveLength(1);
    expect(consent.updated.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("is told the same when the manifest of the trio is of the newer release (the worker refuses it: it is not the release of its own manifest)", async () => {
    const consent = newConsent();
    const h = harness({
      consent,
      workerFetch: {
        serve: (url) => {
          if (new URL(url).pathname !== h.site.trioPath) return undefined;
          h.state.manifest = () => NEWER(h.site);
          return new Response(NEWER_TRIO(h.site), { headers: { "content-type": "application/json" } });
        },
      },
    });
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(UPDATED) });
    expect(consent.updated).toHaveBeenCalledTimes(1);
    expect(h.client.stats().updated).toBe(true);
  });

  it("is told the same when it is the page's own read of the manifest of the trio that meets the newer release: no question is asked and no worker started", async () => {
    const consent = newConsent();
    const h = harness({ consent });
    // the first manifest was read before the deploy, the manifest of the trio after it, and the manifest is read once more to see whether it is the release it began with
    h.state.trio = () => NEWER_TRIO(h.site);
    const reads = [];
    const original = h.state.manifest;
    h.state.manifest = () => (reads.push(1), reads.length === 1 ? original() : NEWER(h.site));
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(UPDATED) });
    expect(reads).toHaveLength(2);
    expect(consent.ask).not.toHaveBeenCalled();
    expect(consent.updated).toHaveBeenCalledTimes(1);
    expect(h.workers).toHaveLength(0);
    expect(h.client.stats().updated).toBe(true);
  });

  it("is told with an error, as before, when the data fails to load and the release is the same: the page and the worker go on", async () => {
    const consent = newConsent();
    let broken = true;
    const h = harness({ consent, workerFetch: { serve: (url) => (broken && new URL(url).pathname === h.site.itemsPath ? new Response("busy", { status: 503 }) : undefined) } });
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(/503/) });
    expect(consent.updated).not.toHaveBeenCalled();
    expect(h.client.stats().updated).toBe(false);
    expect(h.manifestFetches.filter((url) => url === "/engine-manifest.json")).toHaveLength(2); // it looked
    expect(h.workers[0].terminated).toBe(false);
    broken = false;
    expect((await h.client.solve(equipNow())).status).toBe("optimal");
    expect(h.workers).toHaveLength(1);
  });

  it("is told with the error when the page cannot read the manifest again (the release is not known to have changed)", async () => {
    const consent = newConsent();
    const h = harness({
      consent,
      workerFetch: {
        serve: (url) => {
          if (new URL(url).pathname !== h.site.itemsPath) return undefined;
          h.state.manifest = () => undefined; // the host does not answer
          return new Response("gone", { status: 404 });
        },
      },
    });
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(/404/) });
    expect(consent.updated).not.toHaveBeenCalled();
    expect(h.client.stats().updated).toBe(false);
  });

  it.each([
    ["the page of an error of the host", "<html><body>503 Service Unavailable</body></html>"],
    ["a text that is not JSON at all", "{\"data_release\": "],
    ["JSON that is no manifest of the site", "{\"not\": \"a manifest\"}"],
  ])("E13: is told with the error when the manifest read again is %s: another text is no release unless it is a manifest", async (_name, garbage) => {
    const consent = newConsent();
    const h = harness({
      consent,
      workerFetch: {
        serve: (url) => {
          if (new URL(url).pathname !== h.site.itemsPath) return undefined;
          h.state.manifest = () => garbage;
          return new Response("gone", { status: 404 });
        },
      },
    });
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(/404/) });
    expect(consent.updated).not.toHaveBeenCalled();
    expect(h.client.stats().updated).toBe(false);
    expect(h.workers[0].terminated).toBe(false);
  });

  it.each([
    ["a manifest of a newer format (a version and a field this client does not know)", (site) => JSON.stringify({ ...site.manifestJson, version: 3, data_release: "data-2026-10-20", novelty: { later: true } })],
    ["an object with nothing but the release", () => JSON.stringify({ data_release: "data-2026-10-20" })],
    ["a manifest that this client cannot read at all, of another release", (site) => JSON.stringify({ ...site.manifestJson, items: null, data_release: "data-2026-10-20" })],
  ])("F12: is a release when the manifest read again is %s: any JSON object whose data_release is a text other than ours is one", async (_name, make) => {
    const consent = newConsent();
    const h = harness({
      consent,
      workerFetch: {
        serve: (url) => {
          if (new URL(url).pathname !== h.site.itemsPath) return undefined;
          h.state.manifest = () => make(h.site);
          return new Response("gone", { status: 404 });
        },
      },
    });
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(UPDATED) });
    expect(consent.updated).toHaveBeenCalledTimes(1);
    expect(h.client.stats().updated).toBe(true);
  });

  it.each([
    ["the same release in a format this client cannot read", (site) => JSON.stringify({ ...site.manifestJson, version: 3, novelty: 1 })],
    ["a release that is not a text", (site) => JSON.stringify({ ...site.manifestJson, version: 3, data_release: 20261020 })],
    ["a list", () => JSON.stringify([{ data_release: "data-2026-10-20" }])],
  ])("F12: is no release when the manifest read again is %s", async (_name, make) => {
    const consent = newConsent();
    const h = harness({
      consent,
      workerFetch: {
        serve: (url) => {
          if (new URL(url).pathname !== h.site.itemsPath) return undefined;
          h.state.manifest = () => make(h.site);
          return new Response("gone", { status: 404 });
        },
      },
    });
    await expect(h.client.solve(equipNow())).rejects.toMatchObject({ code: "engine-load", message: expect.stringMatching(/404/) });
    expect(consent.updated).not.toHaveBeenCalled();
    expect(h.client.stats().updated).toBe(false);
  });

  it("does not look again for an error of the request itself: a bad request is not a release", async () => {
    const consent = newConsent();
    const h = harness({ consent });
    await expect(h.client.solve(equipNow({ owned: [["w999999@4", 1]] }))).rejects.toMatchObject({ code: "bad-request" });
    expect(h.manifestFetches.filter((url) => url === "/engine-manifest.json")).toHaveLength(1);
    expect(consent.updated).not.toHaveBeenCalled();
  });

  it("does not look again for the other requests: a model that fails is not about the data", async () => {
    const consent = newConsent();
    const h = harness({ consent });
    await h.client.solve(equipNow());
    expect(h.manifestFetches.filter((url) => url === "/engine-manifest.json")).toHaveLength(1);
  });
});

describe("a scenario request of the old generic shape", () => {
  const farm = (over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "farm-path", scenario: { race: "OGR" }, owned: [], candidates: [], budgetMs: 10_000, ...over });

  it("is a bad request at once: no manifest read, no question, no worker, no download, no stored yes", async () => {
    const ask = vi.fn(async () => true);
    const h = harness({ consent: { ask } });
    await expect(h.client.solve(farm())).rejects.toMatchObject({ code: "bad-request" });
    await expect(h.client.solve(farm({ mode: "best-sets" }))).rejects.toMatchObject({ code: "bad-request" });
    expect(ask).not.toHaveBeenCalled();
    expect(h.workers).toHaveLength(0);
    expect(h.asked).toEqual([]);
    expect(h.manifestFetches).toEqual([]);
    expect(h.client.consentState()).toBe("unknown");
    expect(h.dom.window.sessionStorage.getItem("trioforge-engine-consent")).toBeNull();
  });

  it("does not stop an Equip now request that comes after it", async () => {
    const h = harness();
    await expect(h.client.solve(farm())).rejects.toMatchObject({ code: "bad-request" });
    expect((await h.client.solve(equipNow())).status).toBe("optimal");
  });
});
