// Equip now in the worker, on the synthetic site fixture: a scenario request of mode "equip-now" goes through the worker's handler (createWorkerCore) to the
// scenario engine (scenario.js), which fetches the data, makes the session of the profile the scenario names, makes the owned items into item vectors and lets
// path.js work out the best kit from them alone. The answers are held to those of Python's reference (fixtures/site/equip-now.json, made by
// pipeline/tests/engine_fixture.py with upgrade.equip_now, the tie stage included): the exact value, the kit place for place, the optional buffs chosen and
// the haste the weapon index assumed. The worker's own answer has no tie stage (a browser's answer is `canonical: false`); the owned sets of the fixture are
// chosen so that the best kit is the same with and without it. How the data is fetched and checked is tested in engine-scenario-data.test.mjs.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { parseManifest } from "../pipeline/trioforge/site/static/engine/manifest.js";
import { BundleError } from "../pipeline/trioforge/site/static/engine/profile.js";
import { EvaluateError } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { ItemError } from "../pipeline/trioforge/site/static/engine/items.js";
import { ModelError } from "../pipeline/trioforge/site/static/engine/model.js";
import { PathError } from "../pipeline/trioforge/site/static/engine/path.js";
import { PruneError } from "../pipeline/trioforge/site/static/engine/prune.js";
import { LABEL_NO_INCUMBENT, LABEL_TIME_LIMIT, validateFromWorker } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { ExactnessError, PlacementError, SolveError, SolverFault } from "../pipeline/trioforge/site/static/engine/solve.js";
import { TierError } from "../pipeline/trioforge/site/static/engine/tiers.js";
import { EngineFault, createWorkerCore, loadHighsEngine } from "../pipeline/trioforge/site/static/engine/worker.js";
import { BASE, BUNDLE_BYTES, EQUIP_NOW, ITEMS_BYTES, SLUG, makeSite, siteFetch } from "./engine-site-fixture.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const requestOf = (c, over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "equip-now", scenario: { ...c.scenario }, owned: c.owned.map((pair) => [...pair]), budgetMs: 120_000, ...over });
const expectationOf = (request, id) => ({ id, kind: "scenario", mode: "equip-now", owned: request.owned });

/** A worker core on the real solver and the scenario engine, with a fake fetch for the data of the site; `fake` replaces the engine's Equip now. */
function harness(site = makeSite(), { fetch, now = () => performance.now(), fake } = {}) {
  const fetching = siteFetch(site, fetch);
  const scenarios = createScenarioEngine({ highs, fetchImpl: fetching.fetchImpl, baseUrl: BASE, now });
  const posted = [];
  const core = createWorkerCore({
    post: (message) => posted.push(structuredClone(message)),
    loadManifest: async () => site.manifest,
    loadEngine: async () => ({
      version: "1.15.3",
      wasm: site.manifest.wasm.sha256,
      async solveModel() {
        throw new Error("a model request is not what is tested here");
      },
      ...(fake === null ? {} : { equipNow: fake ?? ((request, options) => scenarios.equipNow(request, options)) }),
    }),
    now,
  });
  let id = 0;
  return {
    core,
    posted,
    scenarios,
    ...fetching,
    async start() {
      await core.handle({ v: 1, type: "init" });
      posted.length = 0;
    },
    /** Send a request and return what came back for it: the messages after it, and the last one. */
    async ask(request) {
      id += 1;
      posted.length = 0;
      await core.handle({ v: 1, type: "solve", id, request });
      return { id, messages: [...posted], last: posted[posted.length - 1] };
    },
  };
}

describe("Equip now through the worker's handler", () => {
  for (const c of EQUIP_NOW.cases) {
    it(`gives Python's answer for ${c.name}`, async () => {
      const h = harness();
      await h.start();
      const request = requestOf(c);
      const { id, last, messages } = await h.ask(request);
      expect(last).toMatchObject({ v: 1, type: "result", id, kind: "scenario", mode: "equip-now", status: "optimal", proven: true, label: null });
      expect(last.F).toBe(c.F); // the exact value, as a reduced p/q text
      expect(last.value).toBe(c.value);
      expect(last.kit, "the kit, place for place").toEqual(c.kit);
      expect(last.buffs).toEqual(c.buffs);
      expect(last.hasteAssumed).toBe(c.hasteAssumed);
      expect(last.elapsedMs).toBeGreaterThanOrEqual(0);
      expect(Object.keys(last).sort()).toEqual(["F", "buffs", "elapsedMs", "hasteAssumed", "id", "kind", "kit", "label", "mode", "proven", "status", "type", "v", "value"].sort());
      // what the page makes of it: the reply passes the page's own check, and so does every progress report on the way
      expect(validateFromWorker(last, expectationOf(request, id)).F).toBe(c.F);
      for (const message of messages.slice(0, -1)) expect(validateFromWorker(message, expectationOf(request, id)).type).toBe("progress");
    });
  }

  it("answers an owned set of nothing with the naked character: no place filled, and a value", async () => {
    const h = harness();
    await h.start();
    const request = requestOf(EQUIP_NOW.cases[0], { owned: [] });
    const { last, id } = await h.ask(request);
    expect(last).toMatchObject({ type: "result", status: "optimal", proven: true, buffs: expect.any(Array) });
    expect(last.kit).toEqual(new Array(22).fill(null));
    expect(Number(last.value)).toBeGreaterThan(0);
    expect(validateFromWorker(last, expectationOf(request, id)).kit).toHaveLength(22);
  });

  it("keeps owned items that the trio cannot wear, and an item that only a player may own, and wears them or not by their value", async () => {
    const h = harness();
    await h.start();
    const c = EQUIP_NOW.cases[0];
    expect(c.owned.some(([ident]) => ident === "w90040@4")).toBe(true); // a cap for wizards
    const { last } = await h.ask(requestOf(c));
    expect(last.kit).not.toContain("w90040@4");
    expect(last.kit).toContain("w90041@4"); // the hidden relic helm, owned, is worn
    expect(last.kit.filter((ident) => ident === "w90026@4")).toHaveLength(1); // a Lore ring owned twice is worn once
  });

  it("wears no more of an item than the owned count, and leaves an item locked to a deity the scenario lacks", async () => {
    const h = harness();
    await h.start();
    const c = EQUIP_NOW.cases[0]; // no deity: the Tribunal's crown is owned and not worn
    expect(c.owned.some(([ident]) => ident === "w90004@4")).toBe(true);
    const { last } = await h.ask(requestOf(c));
    expect(last.kit).not.toContain("w90004@4");
    const worn = new Map();
    for (const ident of last.kit.filter(Boolean)) worn.set(ident, (worn.get(ident) ?? 0) + 1);
    for (const [ident, times] of worn) expect(times).toBeLessThanOrEqual(new Map(c.owned).get(ident));
    const follower = EQUIP_NOW.cases[1]; // a follower of the Tribunal wears its crown
    expect((await h.ask(requestOf(follower))).last.kit).toContain("w90004@4");
  });
});

describe("the session of a scenario", () => {
  const c0 = EQUIP_NOW.cases[0];
  const scenarioWith = (changes) => ({ ...c0, scenario: { ...c0.scenario, ...changes } });

  it("is kept for the next request with the same trio, level, race, role, buffs, evidence, setup and deity", async () => {
    const h = harness();
    await h.start();
    const first = await h.ask(requestOf(c0));
    const smaller = { ...c0, owned: c0.owned.slice(0, 12) };
    const second = await h.ask(requestOf(smaller));
    const third = await h.ask(requestOf(c0));
    expect(h.scenarios.stats()).toMatchObject({ sessions: 1, sessionsClosed: 0 });
    expect(third.last.F).toBe(first.last.F); // a session that is used again answers as it did
    expect(second.last.status).toBe("optimal");
    expect(second.last.F).not.toBe(first.last.F);
  });

  for (const [what, changes] of Object.entries({
    "the race": { race: "TRL" },
    "the role": { role: "melee" },
    "the buffs": { buffs: "group" },
    "the evidence": { evidence: "strict" },
    "the setup": { setup: "2h" },
    "the deity": { deity: "The Tribunal" },
  })) {
    it(`is closed and made again when ${what} changes`, async () => {
      const h = harness();
      await h.start();
      const dispose = vi.spyOn(highs, "createModel");
      await h.ask(requestOf(c0));
      expect(h.scenarios.stats()).toMatchObject({ sessions: 1, sessionsClosed: 0 });
      const { last } = await h.ask(requestOf(scenarioWith(changes)));
      expect(last.type).toBe("result");
      expect(h.scenarios.stats()).toMatchObject({ sessions: 2, sessionsClosed: 1 });
      dispose.mockRestore();
    });
  }

  it("is closed when the trio changes, and a new one is made from the bundle of the new trio", async () => {
    const other = new TextEncoder().encode(
      JSON.stringify(
        (() => {
          const document = JSON.parse(BUNDLE_BYTES.toString("utf8"));
          document.trio = ["PAL", "SHD", "BER"];
          document.profile_common.trio = ["PAL", "SHD", "BER"];
          return document;
        })(),
      ),
    );
    const h = harness(makeSite({ bundles: { [SLUG]: { 50: BUNDLE_BYTES }, "pal-shd-ber": { 50: other } } }));
    await h.start();
    await h.ask(requestOf(c0));
    const { last } = await h.ask(requestOf(c0, { trio: "pal-shd-ber" }));
    expect(last.type).toBe("result");
    expect(h.scenarios.stats()).toMatchObject({ sessions: 2, sessionsClosed: 1 });
  });

  it("is closed when a request fails to make its own: nothing is left that belongs to neither", async () => {
    const h = harness();
    await h.start();
    await h.ask(requestOf(c0));
    const { last } = await h.ask(requestOf(scenarioWith({ race: "ZZZ" })));
    expect(last).toMatchObject({ type: "error", code: "bad-request" });
    expect((await h.ask(requestOf(c0))).last.type).toBe("result"); // and the next one works
  });
});

describe("a request the data does not fit", () => {
  const c0 = EQUIP_NOW.cases[0];
  const BAD = {
    "an owned item that is not in the item table": requestOf(c0, { owned: [["w999999@4", 1]] }),
    "an owned item that is not in the item table, among others that are": requestOf(c0, { owned: [["w90001@4", 1], ["w31337@0", 1]] }),
    "a race the bundle does not have": requestOf({ ...c0, scenario: { ...c0.scenario, race: "ZZZ" } }),
    "a role the trio is not offered": requestOf({ ...c0, scenario: { ...c0.scenario, role: "caster" } }),
    "a buff set the bundle does not have": requestOf({ ...c0, scenario: { ...c0.scenario, buffs: "mega" } }),
    "an evidence level the bundle does not have": requestOf({ ...c0, scenario: { ...c0.scenario, evidence: "hidden" } }),
    "a weapon setup that is not one of the role's at that evidence level": requestOf({ ...c0, scenario: { ...c0.scenario, role: "melee", setup: "1h-shield" } }),
    "a weapon setup that no role has": requestOf({ ...c0, scenario: { ...c0.scenario, setup: "bow" } }),
    "an owned item that is a prototype word": null, // the checks of the request refuse it; see engine-scenario-protocol.test.mjs
  };
  for (const [name, request] of Object.entries(BAD)) {
    if (request === null) continue;
    it(`is a bad request: ${name}`, async () => {
      const h = harness();
      await h.start();
      const { last, id } = await h.ask(request);
      expect(last).toMatchObject({ type: "error", id, code: "bad-request" });
      expect(last.message).toMatch(/^[\x20-\x7e]{1,300}$/);
      expect(last.message).not.toMatch(/w999999|w31337/); // an owned ident is not echoed back (the other choices are short names that the protocol has checked)
      expect(validateFromWorker(last, expectationOf(request, id)).code).toBe("bad-request");
    });
  }

  it("takes a deity that nobody follows: it only locks out the items that need another", async () => {
    const h = harness();
    await h.start();
    const { last } = await h.ask(requestOf({ ...c0, scenario: { ...c0.scenario, deity: "Nobody" } }));
    expect(last).toMatchObject({ type: "result", status: "optimal" });
    expect(last.kit).not.toContain("w90004@4");
  });

  it("answers a request of the old generic shape (a mode with candidates, or no mode) with a bad request, though it can do Equip now", async () => {
    const h = harness();
    await h.start();
    const other = { v: 1, kind: "scenario", trio: SLUG, level: 50, mode: "farm-path", scenario: {}, owned: [], candidates: [], budgetMs: 5000 };
    const { last } = await h.ask(other);
    expect(last).toMatchObject({ type: "error", code: "bad-request" });
    const bare = { v: 1, kind: "scenario", trio: SLUG, level: 50, budgetMs: 5000 };
    expect((await h.ask(bare)).last).toMatchObject({ type: "error", code: "bad-request" });
    expect(h.asked).toEqual([]); // nothing was fetched for it
  });

  it("answers an Equip now request with not-implemented when the engine has no such thing (an engine made before)", async () => {
    const h = harness(makeSite(), { fake: null });
    await h.start();
    expect((await h.ask(requestOf(c0))).last).toMatchObject({ type: "error", code: "not-implemented" });
  });

  it("refuses a trio or a level the manifest does not list, before it fetches anything", async () => {
    const h = harness();
    await h.start();
    for (const over of [{ trio: "war-war-war" }, { level: 55 }]) expect((await h.ask(requestOf(c0, over))).last).toMatchObject({ type: "error", code: "bad-request" });
    expect(h.asked).toEqual([]);
  });

  it("refuses a request that was not checked, as it refuses any message: before it has fetched anything", async () => {
    const h = harness();
    await h.start();
    const { last } = await h.ask({ ...requestOf(c0), url: "https://evil.example/x" });
    expect(last).toMatchObject({ type: "error", code: "bad-request" });
    expect(h.asked).toEqual([]);
  });

  it("is not ready before the optimizer is: not-ready, and nothing fetched", async () => {
    const h = harness();
    const { last } = await h.ask(requestOf(c0));
    expect(last).toMatchObject({ type: "error", code: "not-ready" });
    expect(h.asked).toEqual([]);
  });
});

describe("what the worker says of an error of the engine", () => {
  const c0 = EQUIP_NOW.cases[0];
  // (the faults of the solver, of the bundle's data and of the item table are not for the visitor to mend: they are told as such, by scenario.js, as
  // `solver` and `engine-load`; see "a fault that is not the visitor's" below. What is bad-request is what a visitor's request can be: a name the bundle
  // does not have, an item the table does not have)
  const CODES = [
    [new PathError("p"), "bad-request"],
    [new SolveError("s"), "bad-request"],
    [new SolverFault("a status the solve does not accept"), "solver"],
    [new PruneError("p"), "bad-request"],
    [new EvaluateError("e"), "bad-request"],
    [new BundleError("b"), "bad-request"],
    [new TierError("t"), "bad-request"],
    [new EngineFault("bad-request", "f"), "bad-request"],
    [new EngineFault("engine-load", "The data could not be loaded."), "engine-load"],
    [new ExactnessError("x"), "internal"], // a model that overstates its kit is a fault of the engine, not of the visitor's input
    [new PlacementError("x"), "internal"],
    [new ModelError("m"), "internal"],
    [new ItemError("i"), "internal"],
    [new TypeError("t"), "internal"],
    [new RangeError("r"), "internal"],
    [new Error("plain"), "internal"],
    ["a string", "internal"],
    [undefined, "internal"],
  ];
  for (const [error, code] of CODES) {
    it(`${error?.constructor?.name ?? typeof error} (${error instanceof Error ? error.message : String(error)}) is ${code}`, async () => {
      const h = harness(makeSite(), {
        fake: async () => {
          throw error;
        },
      });
      await h.start();
      const { last, id } = await h.ask(requestOf(c0));
      expect(last).toMatchObject({ type: "error", id, code });
      expect(last.message).toMatch(/^[\x20-\x7e]{1,300}$/);
    });
  }

  it("never lets a message carry more than the safe text the protocol allows: a long message with a newline and non-ASCII signs is cut and cleaned", async () => {
    const h = harness(makeSite(), {
      fake: async () => {
        throw new BundleError(`race "${"x".repeat(500)}"\nis é‮ not here`);
      },
    });
    await h.start();
    const { last } = await h.ask(requestOf(c0));
    expect(last.code).toBe("bad-request");
    expect(last.message).toMatch(/^[\x20-\x7e]{1,300}$/);
  });

  it("refuses an item table that names a stat the model does not know when the table is loaded: engine-load, whatever the request owns, and nothing is kept", async () => {
    const table = JSON.parse(ITEMS_BYTES.toString("utf8"));
    table.items.find((r) => r.id === 90001).stats = { FOO: 3 }; // a stat that atTier would refuse, found when the table is read and not at the first tier asked for
    const h = harness(makeSite({ items: new TextEncoder().encode(JSON.stringify(table)) }));
    await h.start();
    for (const owned of [[["w90001@4", 1]], [["w90002@0", 1]], []]) {
      const { last } = await h.ask(requestOf(c0, { owned }));
      expect(last, JSON.stringify(owned)).toMatchObject({ type: "error", code: "engine-load", message: expect.stringMatching(/item table/i) });
    }
    expect(h.scenarios.stats()).toMatchObject({ itemTables: 0, bundles: 0, sessions: 0 });
  });
});

describe("a fault that is not the visitor's", () => {
  const c0 = EQUIP_NOW.cases[0];
  const withBundle = (change) => {
    const bundle = JSON.parse(BUNDLE_BYTES.toString("utf8"));
    change(bundle);
    return new TextEncoder().encode(JSON.stringify(bundle));
  };

  it("is found in the bundle's tier rules when the bundle is loaded, whether the request owns an item or not: engine-load, and the bundle is not kept", async () => {
    // rules that the bundle's reader takes (they are text) and that atTier does not implement: found at the first atTier of the first owned item, so far
    const bundle = withBundle((b) => (b.tier_rules.stat_rule = "base + n"));
    for (const owned of [[], [["w90001@4", 1]]]) {
      const h = harness(makeSite({ bundles: { [SLUG]: { 50: bundle } } }));
      await h.start();
      const { last, id } = await h.ask(requestOf(c0, { owned }));
      expect(last, JSON.stringify(owned)).toMatchObject({ type: "error", id, code: "engine-load", message: expect.stringMatching(/bundle/i) });
      expect(last.message).not.toMatch(/stat_rule|base \+ n/); // (it says which file, not what is in it)
      expect(h.scenarios.stats()).toMatchObject({ bundles: 0, sessions: 0 }); // the bundle was not kept, and no session was made of it
    }
  });

  it("is found in rules of weapons the same way", async () => {
    const bundle = withBundle((b) => (b.weapon_rules.damage_rule = "dmg"));
    const h = harness(makeSite({ bundles: { [SLUG]: { 50: bundle } } }));
    await h.start();
    expect((await h.ask(requestOf(c0, { owned: [] }))).last).toMatchObject({ type: "error", code: "engine-load" });
    expect(h.scenarios.stats().bundles).toBe(0);
  });

  it("is not the visitor's choice of a race, a role or a weapon setup: those stay bad-request, with the bundle kept", async () => {
    const h = harness();
    await h.start();
    expect((await h.ask(requestOf({ ...c0, scenario: { ...c0.scenario, race: "ZZZ" } }))).last).toMatchObject({ type: "error", code: "bad-request" });
    expect((await h.ask(requestOf(c0))).last.type).toBe("result");
    expect(h.scenarios.stats()).toMatchObject({ bundles: 1 });
  });
});

describe("the time of a request", () => {
  const c0 = EQUIP_NOW.cases[0];

  it("is spent by the time the solver is called when the clock has run past the budget since the data came in: no kit, and it says so", async () => {
    let clock = 0;
    // the clock moves a second at every look at it, so a budget of a millisecond is gone by the time the session is built and the solver is called
    const h = harness(makeSite(), { now: () => (clock += 1000) });
    await h.start();
    const request = requestOf(c0, { budgetMs: 1 });
    const { last, id } = await h.ask(request);
    expect(last.type).toBe("result");
    expect(last).toMatchObject({ status: "time_limit", proven: false });
    expect(validateFromWorker(last, expectationOf(request, id)).label).toBe(last.kit === null ? LABEL_NO_INCUMBENT : LABEL_TIME_LIMIT); // an honest label, whichever it is
    expect(last.kit).toBeNull(); // (the solver was given nothing, and had no kit at once)
    expect(last).toMatchObject({ F: null, value: null, buffs: [], label: LABEL_NO_INCUMBENT });
  });

  it("is counted from the moment the data is in: a download that takes a minute of the clock does not eat the budget of the solve", async () => {
    let clock = 0;
    // each file takes twenty seconds to arrive (the clock moves when the fetch is asked); the clock does not move otherwise
    const h = harness(makeSite(), {
      now: () => clock,
      fetch: {
        serve: () => {
          clock += 20_000;
          return undefined;
        },
      },
    });
    await h.start();
    const request = requestOf(c0, { budgetMs: 5000 });
    const { last, id } = await h.ask(request);
    expect(h.asked).toHaveLength(3);
    expect(last).toMatchObject({ type: "result", status: "optimal", proven: true, label: null, F: c0.F });
    expect(validateFromWorker(last, expectationOf(request, id)).kit).toEqual(c0.kit);
  });

  it("counts the whole request in the elapsed time of the answer, the download included", async () => {
    let clock = 0;
    const h = harness(makeSite(), {
      now: () => clock,
      fetch: {
        serve: () => {
          clock += 20_000;
          return undefined;
        },
      },
    });
    await h.start();
    const { last } = await h.ask(requestOf(c0, { budgetMs: 5000 }));
    expect(last.type).toBe("result");
    expect(last.elapsedMs).toBe(60_000); // three files of twenty seconds
  });

  it("gives the solver the whole budget, never more: its time limit is the budget of the request", async () => {
    const h = harness();
    await h.start();
    const limits = [];
    const original = highs.createModel.bind(highs);
    const spy = vi.spyOn(highs, "createModel").mockImplementation((...args) => {
      const solver = original(...args);
      return new Proxy(solver, {
        get(target, name) {
          if (name !== "options") return typeof target[name] === "function" ? target[name].bind(target) : target[name];
          return new Proxy(target.options, {
            get(options, method) {
              if (method !== "set") return typeof options[method] === "function" ? options[method].bind(options) : options[method];
              return (key, value) => {
                if (key === "time_limit") limits.push(value);
                return options.set(key, value);
              };
            },
          });
        },
      });
    });
    await h.ask(requestOf(c0, { budgetMs: 30_000 }));
    spy.mockRestore();
    expect(limits.length).toBeGreaterThan(0);
    expect(Math.max(...limits)).toBeLessThanOrEqual(30);
    expect(Math.max(...limits)).toBeGreaterThan(29); // seconds: the whole budget, less only the little that the session took
  });
});

describe("the real engine", () => {
  const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const wasmBytes = readFileSync(resolve(ROOT, "node_modules/highs/build/highs.wasm"));

  it("has Equip now when it is loaded the way the worker loads it, from the manifest's files, and answers as Python does", async () => {
    const site = makeSite();
    const wasmPath = "/assets/engine/highs-0123456789ABCDEF.wasm";
    const manifest = parseManifest({ ...site.manifestJson, wasm: { path: wasmPath, bytes: wasmBytes.length, gzip: 1, sha256: await sha(wasmBytes) } });
    const fetching = siteFetch(site, {
      serve: (url) => (new URL(url).pathname === wasmPath ? new Response(wasmBytes, { headers: { "content-type": "application/wasm" } }) : undefined),
    });
    const engine = await loadHighsEngine({ manifest, fetchImpl: fetching.fetchImpl, baseUrl: BASE, onProgress() {} });
    expect(typeof engine.equipNow).toBe("function");
    const c = EQUIP_NOW.cases[2];
    const answer = await engine.equipNow(requestOf(c), { manifest, startedAt: performance.now(), onProgress() {} });
    expect(answer).toMatchObject({ status: "optimal", proven: true, label: null, F: c.F, value: c.value, kit: c.kit, buffs: c.buffs, hasteAssumed: c.hasteAssumed });
    expect(fetching.asked.map((url) => new URL(url).pathname)).toEqual([wasmPath, site.trioPath, site.itemsPath, site.bundlePath]);
  });

  async function sha(bytes) {
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
    return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
});
