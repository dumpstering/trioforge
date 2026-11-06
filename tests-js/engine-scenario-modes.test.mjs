// The other scenario modes in the worker, on the synthetic site fixture: a request of the mode farm-path, best-sets or every-slot goes through the worker's handler
// (createWorkerCore) to the scenario engine (scenario.js), which fetches the data, makes the session, the owned items and the candidates (from the tier mode: the request
// carries none) and lets path.js work. The messages are held to what the page checks of them (protocol.js: every one is validated as the client validates it, and a farm path is
// watched as a whole), and the answers to the functions of path.js called directly on the same inputs. A stop is handled at once, not behind the queue; between two steps
// the engine yields to the event loop, so that a stop that arrives is seen; the budget of every mode counts from the moment the data is in.

import loadHighs from "highs";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { candidatesFor } from "../pipeline/trioforge/site/static/engine/candidates.js";
import { atTier, readItemTable } from "../pipeline/trioforge/site/static/engine/items.js";
import { PathError, everySlot, farmPath } from "../pipeline/trioforge/site/static/engine/path.js";
import { assembleProfile, readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { LABEL_NO_INCUMBENT, createPathWatch, validateFromWorker, validateRequest } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { createScenarioEngine } from "../pipeline/trioforge/site/static/engine/scenario.js";
import { SolverFault, createSession, closeSession } from "../pipeline/trioforge/site/static/engine/solve.js";
import { EngineFault, createWorkerCore } from "../pipeline/trioforge/site/static/engine/worker.js";
import { BASE, BUNDLE_BYTES, EQUIP_NOW, ITEMS_BYTES, SLUG, makeSite, siteFetch, siteWithNoCandidates } from "./engine-site-fixture.mjs";
import { spyOn } from "./engine-spy.mjs";

vi.setConfig({ testTimeout: 120_000 });

let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

const [C0, C1, C2] = EQUIP_NOW.cases;
const READY4 = { mode: "ready4" };
const base = (c, over = {}) => ({ v: 1, kind: "scenario", trio: SLUG, level: 50, scenario: { ...c.scenario }, owned: c.owned.map((pair) => [...pair]), budgetMs: 120_000, ...over });
const farm = (c, over = {}) => base(c, { mode: "farm-path", tierMode: { ...READY4 }, steps: 3, ...over });
const sets = (c, over = {}) => base(c, { mode: "best-sets", tierMode: { ...READY4 }, k: 2, ...over });
const slots = (c, over = {}) => base(c, { mode: "every-slot", tierMode: { ...READY4 }, kit: [...c.kit], buffs: [...c.buffs], ...over });
const equip = (c, over = {}) => base(c, { mode: "equip-now", ...over });
const rational = (text) => Rational.parseLong(text);
/** A record of the fixture's item table (the table is read once). */
const TABLE_RECORD = (() => {
  const table = readItemTable(JSON.parse(ITEMS_BYTES.toString("utf8")));
  return (key) => table.records.get(key);
})();
/** The choices `assembleProfile` takes from a scenario (the setup is another thing). */
const choices = (c) => ({ race: c.scenario.race, role: c.scenario.role, buffs: c.scenario.buffs, evidence: c.scenario.evidence, deity: c.scenario.deity });

/** A worker core on the real solver and the scenario engine, with the fake fetch of a site; `engineOver` replaces methods of the engine, `post` sees every message as it is sent. */
function harness({ site = makeSite(), fetch, now = () => performance.now(), solver = highs, scenarioOptions = {}, engineOver = {} } = {}) {
  const fetching = siteFetch(site, fetch);
  const scenarios = createScenarioEngine({ highs: solver, fetchImpl: fetching.fetchImpl, baseUrl: BASE, now, ...scenarioOptions });
  const hooks = { onPost: null };
  const posted = [];
  const core = createWorkerCore({
    post: (message) => {
      posted.push(structuredClone(message));
      hooks.onPost?.(message);
    },
    loadManifest: async () => site.manifest,
    loadEngine: async () => ({
      version: "1.15.3",
      wasm: site.manifest.wasm.sha256,
      async solveModel() {
        throw new Error("a model request is not what is tested here");
      },
      equipNow: (request, options) => scenarios.equipNow(request, options),
      farmPath: (request, options) => scenarios.farmPath(request, options),
      bestSets: (request, options) => scenarios.bestSets(request, options),
      everySlot: (request, options) => scenarios.everySlot(request, options),
      ...engineOver,
    }),
    now,
  });
  let id = 0;
  const stopOf = (to) => core.handle({ v: 1, type: "stop", id: to });
  return {
    core,
    posted,
    hooks,
    scenarios,
    site,
    ...fetching,
    stopOf,
    /** The id of the request that was asked last (the one in flight, when called while it runs). */
    currentId: () => id,
    async start() {
      await core.handle({ v: 1, type: "init" });
      posted.length = 0;
    },
    /** Send a request and return what came back for it: its id, the messages after it, and the last one. */
    async ask(request) {
      id += 1;
      const mine = id;
      posted.length = 0;
      await core.handle({ v: 1, type: "solve", id: mine, request });
      return { id: mine, messages: [...posted], last: posted[posted.length - 1] };
    },
    /** Send a request without waiting for its answer. */
    send(request) {
      id += 1;
      return { id, done: core.handle({ v: 1, type: "solve", id, request }) };
    },
  };
}

/** What the page does with the messages of a request: each one is checked against what was asked, as the client checks it, and a farm path is watched as a whole. */
function pageChecks(request, id, messages) {
  const clean = validateRequest(request);
  const path = clean.mode === "farm-path" ? createPathWatch(clean) : undefined;
  const expectation = { id, kind: "scenario", mode: clean.mode, owned: clean.owned, steps: clean.steps, k: clean.k, limit: clean.limit, tierMode: clean.tierMode, kit: clean.kit, path };
  return messages.map((message) => validateFromWorker(message, expectation));
}
const stepsOf = (messages) => messages.filter((message) => message.type === "step");
const progressOf = (messages) => messages.filter((message) => message.type === "progress");

// ---- the farm path ----------------------------------------------------------------------------------------------------------------

describe("a farm path", () => {
  it("streams Equip now as the step 0 and then the steps in order, and ends with its result", async () => {
    const h = harness();
    await h.start();
    const request = farm(C0);
    const { id, messages, last } = await h.ask(request);
    const checked = pageChecks(request, id, messages); // every message is what the page accepts
    const steps = stepsOf(checked);
    expect(steps.map((step) => step.index)).toEqual([0, 1, 2, 3]);
    expect(steps[0]).toMatchObject({ status: "optimal", proven: true, label: null });
    for (const step of steps.slice(1)) expect(step).toMatchObject({ found: true, status: "optimal", proven: true, label: null });
    expect(last).toMatchObject({ type: "result", id, kind: "scenario", mode: "farm-path", stopped: "limit", steps: 3 });
    expect(last.hasteAssumed).toBe(steps[0].hasteAssumed);
    expect(last.elapsedMs).toBeGreaterThan(0);
    // the steps come before the result, and nothing but progress and steps comes before it
    expect(messages.map((message) => message.type).filter((type) => type !== "progress")).toEqual(["step", "step", "step", "step", "result"]);
    // what each step acquires costs something that the tier mode explains, and the gains add up to the difference of the values
    const total = steps.slice(1).reduce((sum, step) => sum.add(rational(step.gain)), rational("0/1"));
    expect(rational(steps.at(-1).F).sub(rational(steps[0].F)).toString()).toBe(total.toString());
  });

  it("is the path path.js finds on the same inputs: the same items, kinds and values, step by step", async () => {
    const h = harness();
    await h.start();
    const { messages } = await h.ask(farm(C1, { steps: 4 }));
    const steps = stepsOf(messages);
    // the same path, made by hand: the session of the scenario, the owned items and the candidates of the tier mode
    const table = readItemTable(JSON.parse(ITEMS_BYTES.toString("utf8")));
    const bundle = readBundle(JSON.parse(BUNDLE_BYTES.toString("utf8")));
    const profile = assembleProfile(bundle, choices(C1));
    const session = createSession({
      highs,
      profile,
      setup: C1.scenario.setup,
      buffset: { set: bundle.buffs[C1.scenario.buffs].set, table: bundle.buff_table },
      monkBins: bundle.monk_bins === null ? undefined : bundle.monk_bins,
      options: {},
    });
    try {
      const owned = C1.owned.map(([name, count]) => [atTier(table.records.get(name.slice(0, name.lastIndexOf("@"))), Number(name.slice(name.lastIndexOf("@") + 1)), bundle), count]);
      const candidates = candidatesFor(table.records, bundle, profile, { evidence: C1.scenario.evidence, tierMode: READY4 });
      const direct = farmPath(session, owned, candidates, { steps: 4, budgetMs: 120_000 });
      expect(steps.slice(1).map((step) => [step.ident, step.kind, step.sourceTier, step.F, step.gain])).toEqual(
        direct.steps.map((step) => [`${step.item.key}@${step.item.tier}`, step.kind, step.sourceTier, step.F.toString(), step.gain.toString()]),
      );
      expect(steps[0].F).toBe(direct.baseline.F.toString());
      expect(steps[0].hasteAssumed).toBe(direct.hasteAssumed);
    } finally {
      closeSession(session);
    }
  });

  it("reports what it is working on: the stage of every report, and the step of a step", async () => {
    const h = harness();
    await h.start();
    const request = farm(C0);
    const { id, messages } = await h.ask(request);
    const reports = progressOf(pageChecks(request, id, messages));
    expect(reports.every((report) => report.stage !== undefined)).toBe(true);
    const stages = reports.map((report) => report.stage);
    expect(stages.indexOf("loading")).toBe(0);
    expect(stages.indexOf("equip-now")).toBeGreaterThan(stages.lastIndexOf("loading"));
    expect(reports.filter((report) => report.stage === "step").map((report) => report.step)).toEqual([1, 2, 3]);
    // in the order the work goes: loading, then Equip now, then the steps
    const order = [...new Set(stages)];
    expect(order).toEqual(["loading", "equip-now", "step"]);
    // each report of a step comes just before the step it announces
    const types = messages.filter((message) => message.type === "step" || (message.type === "progress" && message.stage === "step")).map((message) => (message.type === "step" ? `step ${message.index}` : `working ${message.step}`));
    expect(types).toEqual(["step 0", "working 1", "step 1", "working 2", "step 2", "working 3", "step 3"]);
  });

  describe("announces a step when it begins and not before", () => {
    // The progress {stage: "step", step} names the step the engine is working on. It is sent when the stepper begins the step (path.js onBegin), so that it never names a step
    // that does not begin: after a stop, after the last step asked for, and after a step that ended the path there is none.
    const announced = (messages) => progressOf(messages).filter((report) => report.stage === "step").map((report) => report.step);

    it("after a stop, there is no announcement of the step that does not begin", async () => {
      const h = harness();
      await h.start();
      h.hooks.onPost = (message) => {
        if (message.type === "step" && message.index === 1) h.stopOf(h.currentId());
      };
      const request = farm(C0, { steps: 8 });
      const { id, messages, last } = await h.ask(request);
      pageChecks(request, id, messages);
      expect(last).toMatchObject({ stopped: "stopped", steps: 1 });
      expect(announced(messages)).toEqual([1]);
    });

    it("after the last step asked for, there is none for the step after it", async () => {
      const h = harness();
      await h.start();
      const request = farm(C0, { steps: 2 });
      const { id, messages, last } = await h.ask(request);
      pageChecks(request, id, messages);
      expect(last).toMatchObject({ stopped: "limit", steps: 2 });
      expect(announced(messages)).toEqual([1, 2]);
    });

    it("after a step that ended the path (not proven the best, the time gone), there is none for the step that would have come", async () => {
      const clock = { t: 0 };
      const { highs: spied } = spyOn(highs, { clock: () => clock.t, before: () => (clock.t += 600) });
      const h = harness({ now: () => clock.t, solver: spied });
      await h.start();
      const request = farm(C0, { budgetMs: 6000, steps: 8 });
      const { id, messages, last } = await h.ask(request);
      pageChecks(request, id, messages);
      // (every run of the solver takes 600 ms of the clock, and a step runs once for each haste level it looks at: the path ends after a step or two)
      expect(last).toMatchObject({ stopped: "time" });
      expect(last.steps).toBeGreaterThanOrEqual(1);
      // each step that was sent was announced, and at most the one whose model spent the budget (it began, and no solve was started) was announced and never sent
      const told = announced(messages);
      expect(told.slice(0, last.steps)).toEqual(Array.from({ length: last.steps }, (_, at) => at + 1));
      expect(told.length).toBeLessThanOrEqual(last.steps + 1);
    });

    it("each announcement comes before the message of its step and after the message of the step before", async () => {
      const h = harness();
      await h.start();
      const request = farm(C0, { steps: 3 });
      const { messages } = await h.ask(request);
      const order = messages.filter((message) => message.type === "step" || (message.type === "progress" && message.stage === "step")).map((message) => (message.type === "step" ? `step ${message.index}` : `begin ${message.step}`));
      expect(order).toEqual(["step 0", "begin 1", "step 1", "begin 2", "step 2", "begin 3", "step 3"]);
    });

    it("a path with nothing to add announces no step", async () => {
      const h = harness({ site: siteWithNoCandidates() });
      await h.start();
      const request = farm(C0, { steps: 4 });
      const { messages } = await h.ask(request);
      expect(announced(messages)).toEqual([]);
    });
  });

  it("makes the candidates from the tier mode: the cost of a step is counted as the mode counts it", async () => {
    const h = harness();
    await h.start();
    const arrives = stepsOf((await h.ask(farm(C0, { tierMode: { mode: "arrives", D: 2 }, steps: 4 }))).messages).slice(1);
    for (const step of arrives) {
      expect(step.ident.endsWith("@2") || step.ident.endsWith("@0")).toBe(true); // a drop arrives at +D, anything else at +0
      if (step.kind !== "upgrade") expect(step.cost).toMatchObject({ exp: 0, potentials: 0 }); // it is scored at the tier it arrives at
    }
    const fixed = stepsOf((await h.ask(farm(C0, { tierMode: { mode: "fixed", N: 10 }, steps: 3 }))).messages).slice(1);
    expect(fixed.every((step) => step.ident.endsWith("@10"))).toBe(true);
    expect(fixed.every((step) => step.cost !== null && step.cost.exp > 0)).toBe(true);
    // the cost of an item that arrives at +4 (a drop, or an owned +4 copy that is upgraded) and is brought to +10: 2^10 - 2^4 experience, 63 copies that arrive at +4, six potentials
    const brought = fixed.find((step) => step.cost.potentials === 6);
    expect(brought?.cost).toEqual({ exp: 1008, copiesAtArrival: 63, potentials: 6 });
  });

  it("keeps the last list of candidates: another request for the same scenario and tier mode does not make it again, another tier mode, evidence or deity does", async () => {
    const h = harness();
    await h.start();
    expect(h.scenarios.stats().candidateLists).toBe(0);
    await h.ask(farm(C0));
    await h.ask(farm(C0, { steps: 2 })); // the steps are not part of it
    await h.ask(sets(C0));
    await h.ask(slots(C0));
    expect(h.scenarios.stats().candidateLists).toBe(1);
    await h.ask(farm(C0, { tierMode: { mode: "fixed", N: 4 } }));
    expect(h.scenarios.stats().candidateLists).toBe(2);
    await h.ask(farm(C0, { scenario: { ...C0.scenario, evidence: "strict" } }));
    expect(h.scenarios.stats().candidateLists).toBe(3);
    await h.ask(farm(C0, { scenario: { ...C0.scenario, deity: "The Tribunal" } }));
    expect(h.scenarios.stats().candidateLists).toBe(4);
    await h.ask(farm(C0, { scenario: { ...C0.scenario, race: "TRL" } }));
    expect(h.scenarios.stats().candidateLists).toBe(5);
    await h.ask(farm(C0, { scenario: { ...C0.scenario, race: "TRL" } }));
    expect(h.scenarios.stats().candidateLists).toBe(5);
  });

  it("answers Equip now alone for a path with nothing to add: no candidates, so no step, and the result says why", async () => {
    // every strict record of the table is read as a wiki record: the strict evidence level has no candidate
    const table = JSON.parse(ITEMS_BYTES.toString("utf8"));
    for (const record of table.items) if (record.evidence.level === "strict") record.evidence = { ...record.evidence, level: "wiki" };
    const h = harness({ site: makeSite({ items: new TextEncoder().encode(JSON.stringify(table)) }) });
    await h.start();
    const request = farm(C0, { scenario: { ...C0.scenario, evidence: "strict" } });
    const { id, messages, last } = await h.ask(request);
    const steps = stepsOf(pageChecks(request, id, messages));
    expect(steps.map((step) => step.index)).toEqual([0]);
    expect(steps[0]).toMatchObject({ status: "optimal", proven: true });
    expect(last).toMatchObject({ type: "result", mode: "farm-path", stopped: "no-gain", steps: 0, hasteAssumed: steps[0].hasteAssumed });
  });

  it("ends 'no-gain' when the table offers nothing at any level and Equip now finished, and the page accepts the path", async () => {
    const h = harness({ site: siteWithNoCandidates() });
    await h.start();
    for (const evidence of ["strict", "wiki"]) {
      const request = farm(C0, { scenario: { ...C0.scenario, evidence } });
      const { id, messages, last } = await h.ask(request);
      const steps = stepsOf(pageChecks(request, id, messages));
      expect(steps.map((step) => step.index)).toEqual([0]);
      expect(steps[0]).toMatchObject({ status: "optimal", proven: true });
      expect(last).toMatchObject({ type: "result", mode: "farm-path", stopped: "no-gain", steps: 0 });
    }
  });

  it("ends 'time' when it has nothing to add and the Equip now it answers alone did not finish: a path whose Equip now ran out of time says so", async () => {
    const clock = { t: 0 };
    const h = harness({ site: siteWithNoCandidates(), now: () => (clock.t += 10) }); // every look at the clock costs ten milliseconds of a budget of one
    await h.start();
    const request = farm(C0, { budgetMs: 1 });
    const { id, messages, last } = await h.ask(request);
    const steps = stepsOf(pageChecks(request, id, messages)); // (the page's watch refuses a path that ran out of time and says anything else)
    expect(steps.map((step) => step.index)).toEqual([0]);
    expect(steps[0]).toMatchObject({ status: "time_limit", proven: false });
    expect(last).toMatchObject({ type: "result", mode: "farm-path", stopped: "time", steps: 0, hasteAssumed: steps[0].hasteAssumed });
  });

  it("is a request like any other for the data: a trio the manifest does not list is a bad request, and nothing is fetched", async () => {
    const h = harness();
    await h.start();
    const { last } = await h.ask(farm(C0, { trio: "war-war-war" }));
    expect(last).toMatchObject({ type: "error", code: "bad-request" });
    expect(h.asked).toEqual([]);
  });
});

// ---- the stop -----------------------------------------------------------------------------------------------------------------------

describe("a stop", () => {
  it("sent after Equip now ends the path before its first step, with the result 'stopped' and no step", async () => {
    const h = harness();
    await h.start();
    h.hooks.onPost = (message) => {
      if (message.type === "step" && message.index === 0) h.stopOf(h.currentId());
    };
    const request = farm(C0, { steps: 8 });
    const { id, messages, last } = await h.ask(request);
    pageChecks(request, id, messages);
    expect(stepsOf(messages).map((step) => step.index)).toEqual([0]);
    expect(last).toMatchObject({ type: "result", mode: "farm-path", stopped: "stopped", steps: 0 });
  });

  it("sent after the first step message ends the path with 'stopped' and that one step", async () => {
    const h = harness();
    await h.start();
    h.hooks.onPost = (message) => {
      if (message.type === "step" && message.index === 1) h.stopOf(h.currentId());
    };
    const request = farm(C0, { steps: 8 });
    const { id, messages, last } = await h.ask(request);
    pageChecks(request, id, messages);
    expect(stepsOf(messages).map((step) => step.index)).toEqual([0, 1]);
    expect(last).toMatchObject({ type: "result", stopped: "stopped", steps: 1 });
    // there was no reply to the stop: the last messages are the step and the result
    expect(messages.filter((message) => message.type === "error")).toEqual([]);
  });

  it("arrives as a message does, in a macrotask of its own: the engine yields between two steps, and the stop is seen", async () => {
    const h = harness();
    await h.start();
    h.hooks.onPost = (message) => {
      if (message.type === "step" && message.index === 1) setTimeout(() => h.stopOf(h.currentId()), 0);
    };
    const { messages, last } = await h.ask(farm(C0, { steps: 8 }));
    expect(stepsOf(messages).map((step) => step.index)).toEqual([0, 1]);
    expect(last).toMatchObject({ stopped: "stopped", steps: 1 });
  });

  it("delivered after the worker has yielded and begun the next step ends the path one step later: that step is finished and sent, as it can be in a browser", async () => {
    // The page sends the stop from the callback of the first step message. In a browser it may reach the worker after the worker has yielded for 0 ms and looked: it looks,
    // sees nothing, and begins the second step. The stop is seen at the look after that step, so the path ends there, with that step in it (the test above delivers the stop
    // first, as microtasks and the earlier timers do, and the path ends after one step).
    const h = harness();
    await h.start();
    h.hooks.onPost = (message) => {
      if (message.type === "step" && message.index === 1) setTimeout(() => h.stopOf(h.currentId()), 3); // after the worker's own yield of one millisecond
    };
    const request = farm(C0, { steps: 8 });
    const { id, messages, last } = await h.ask(request);
    pageChecks(request, id, messages);
    expect(stepsOf(messages).map((step) => step.index)).toEqual([0, 1, 2]);
    expect(last).toMatchObject({ type: "result", stopped: "stopped", steps: 2 });
  });

  it("is a yield between the steps, a macrotask each, after the step has been sent", async () => {
    const events = [];
    const h = harness({
      scenarioOptions: {
        yieldNow: () => {
          events.push("yield");
          return new Promise((resolve) => setTimeout(resolve, 0));
        },
      },
    });
    await h.start();
    h.hooks.onPost = (message) => {
      if (message.type === "step") events.push(`step ${message.index}`);
      if (message.type === "result") events.push("result");
    };
    await h.ask(farm(C0, { steps: 2 }));
    expect(events).toEqual(["step 0", "yield", "step 1", "yield", "step 2", "yield", "result"]);
  });

  it("sent while the data is still loading does not stop Equip now: it comes, and the path ends before its first step", async () => {
    let trigger = () => {};
    const h = harness({
      fetch: {
        serve: (url) => {
          if (url.includes("/assets/engine/data/items-")) trigger();
          return undefined;
        },
      },
    });
    await h.start();
    trigger = () => h.stopOf(h.currentId());
    const request = farm(C0, { steps: 8 });
    const { id, messages, last } = await h.ask(request);
    pageChecks(request, id, messages);
    expect(stepsOf(messages).map((step) => step.index)).toEqual([0]);
    expect(last).toMatchObject({ stopped: "stopped", steps: 0 });
  });

  it("is handled at once and not behind the queue: it ends the farm path that is running, and the request queued behind it is answered after", async () => {
    const h = harness();
    await h.start();
    h.hooks.onPost = (message) => {
      if (message.id === 1 && message.type === "step" && message.index === 0) h.stopOf(1);
    };
    const first = h.send(farm(C0, { steps: 8 }));
    const second = h.send(equip(C1));
    await Promise.all([first.done, second.done]);
    const results = h.posted.filter((message) => message.type === "result");
    expect(results.map((message) => [message.id, message.mode])).toEqual([[1, "farm-path"], [2, "equip-now"]]);
    expect(results[0]).toMatchObject({ stopped: "stopped", steps: 0 });
    expect(results[1]).toMatchObject({ status: "optimal", F: C1.F });
  });

  it("stops a farm path that is still waiting in the queue the moment it begins: Equip now, and then it ends", async () => {
    const h = harness();
    await h.start();
    const first = h.send(farm(C0, { steps: 3 }));
    const second = h.send(farm(C1, { steps: 8 }));
    h.stopOf(second.id); // before the first has ended, and long before the second began
    await Promise.all([first.done, second.done]);
    const results = h.posted.filter((message) => message.type === "result");
    expect(results[0]).toMatchObject({ id: first.id, stopped: "limit", steps: 3 });
    expect(results[1]).toMatchObject({ id: second.id, stopped: "stopped", steps: 0 });
    expect(h.posted.filter((message) => message.type === "step" && message.id === second.id).map((step) => step.index)).toEqual([0]);
  });

  it("changes nothing for another request: an id that is not in flight, an Equip now request in flight, a request that ended", async () => {
    const h = harness();
    await h.start();
    const request = farm(C0, { steps: 2 });
    h.hooks.onPost = (message) => {
      if (message.type === "step" && message.index === 0) {
        h.stopOf(h.currentId() + 1); // the id of a request that has not been made
        h.stopOf(99);
        h.stopOf(1_000_000);
      }
    };
    const first = await h.ask(request);
    expect(first.last).toMatchObject({ stopped: "limit", steps: 2 });
    // an Equip now request is not a farm path, whatever is said to it
    h.hooks.onPost = (message) => {
      if (message.type === "progress") h.stopOf(h.currentId());
    };
    expect((await h.ask(equip(C1))).last).toMatchObject({ type: "result", status: "optimal", F: C1.F });
    h.hooks.onPost = null;
    // a request that has ended
    const ended = h.currentId();
    h.posted.length = 0;
    await h.stopOf(ended);
    await h.stopOf(first.id);
    expect(h.posted).toEqual([]);
    // and the next farm path is whole
    expect((await h.ask(farm(C2, { steps: 2 }))).last).toMatchObject({ stopped: "limit", steps: 2 });
  });

  it("is a message with an id that is not an id: refused as any message is, with the error of a bad request, and no request is stopped by it", async () => {
    const h = harness();
    await h.start();
    h.hooks.onPost = (message) => {
      if (message.type === "step" && message.index === 0) {
        h.core.handle({ v: 1, type: "stop", id: 0 });
        h.core.handle({ v: 1, type: "stop" });
        h.core.handle({ v: 1, type: "stop", id: h.currentId(), request: farm(C0) });
      }
    };
    const { last } = await h.ask(farm(C0, { steps: 2 }));
    expect(last).toMatchObject({ type: "result", stopped: "limit", steps: 2 });
    await new Promise((resolve) => setTimeout(resolve, 0)); // (a message that is not understood is refused in its turn: after the request that was running)
    const errors = h.posted.filter((message) => message.type === "error");
    expect(errors).toHaveLength(3);
    expect(errors.every((error) => error.code === "bad-request")).toBe(true);
  });

  it("is not a way to make a farm path of an id twice: a second request with the id of one in flight is refused", async () => {
    const h = harness();
    await h.start();
    const first = h.core.handle({ v: 1, type: "solve", id: 5, request: farm(C0, { steps: 2 }) });
    const second = h.core.handle({ v: 1, type: "solve", id: 5, request: farm(C1, { steps: 2 }) });
    await Promise.all([first, second]);
    const results = h.posted.filter((message) => message.type === "result");
    const errors = h.posted.filter((message) => message.type === "error");
    expect(results).toHaveLength(1);
    expect(results[0]).toMatchObject({ id: 5, stopped: "limit", steps: 2 });
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatchObject({ code: "bad-request", id: 5 });
  });
});

// ---- the faults of a step -----------------------------------------------------------------------------------------------------------

describe("a fault in a step", () => {
  /** A farm path of a fake engine that sends Equip now and one step and then meets `error`. */
  const failing = (error) => ({
    async farmPath(request, { onStep }) {
      onStep({ index: 0, status: "optimal", proven: true, label: null, F: "100/1", value: 100, kit: new Array(22).fill(null), buffs: [], hasteAssumed: 0 });
      onStep({
        index: 1,
        found: true,
        ident: "w90001@4",
        kind: "new",
        sourceTier: null,
        cost: null,
        F: "110/1",
        value: 110,
        gain: "10/1",
        gainValue: 10,
        kit: ["w90001@4", ...new Array(21).fill(null)],
        buffs: [],
        hasteAssumed: 0,
        status: "optimal",
        proven: true,
        label: null,
      });
      throw error;
    },
  });

  for (const [name, error, code] of [
    ["a solver that did what an answer cannot be made from", new SolverFault("the solver ended with a status the solve does not accept"), "solver"],
    ["data that cannot be loaded", new EngineFault("engine-load", "The optimizer's item table could not be loaded."), "engine-load"],
    ["an input the engine refuses", new PathError("an owned item is not what the model reads"), "bad-request"],
    ["anything else", new TypeError("not a thing"), "internal"],
  ]) {
    it(`ends the path with the error code of ${name} (${code}), and the steps sent before it stand`, async () => {
      const h = harness({ engineOver: failing(error) });
      await h.start();
      const { messages, last } = await h.ask(farm(C0));
      expect(stepsOf(messages).map((step) => step.index)).toEqual([0, 1]);
      expect(last).toMatchObject({ type: "error", code, id: 1 });
      expect(messages.filter((message) => message.type === "result")).toEqual([]);
      // and the worker goes on
      expect((await h.ask(equip(C1))).last).toMatchObject({ type: "result", status: "optimal", F: C1.F });
    });
  }

  it("is, with the real engine, a fault of the solver in the second step: `solver`, the session closed, Equip now and the first step delivered, and the next request is answered", async () => {
    const sick = { on: false };
    const { highs: spied } = spyOn(highs, { outcome: (result) => (sick.on ? { ...result, modelStatus: highs.constants.modelStatus.unbounded } : result) });
    const h = harness({ solver: spied });
    await h.start();
    // the solver falls ill once the first step is delivered: the next run of it is the second step's (a step runs once for each haste level it looks at)
    h.hooks.onPost = (message) => {
      if (message.type === "step" && message.index === 1) sick.on = true;
    };
    const { messages, last } = await h.ask(farm(C0, { steps: 4 }));
    expect(stepsOf(messages).map((step) => step.index)).toEqual([0, 1]);
    expect(last).toMatchObject({ type: "error", code: "solver" });
    expect(h.scenarios.stats()).toMatchObject({ sessions: 1, sessionsClosed: 1 });
    sick.on = false;
    h.hooks.onPost = null;
    const next = await h.ask(farm(C0, { steps: 2 }));
    expect(next.last).toMatchObject({ type: "result", stopped: "limit", steps: 2 });
    expect(h.scenarios.stats()).toMatchObject({ sessions: 2, sessionsClosed: 1 });
  });
});

// ---- the budget -----------------------------------------------------------------------------------------------------------------------

describe("the budget", () => {
  it("of a farm path counts from the moment the data is in: a download that takes longer than the budget costs the path nothing", async () => {
    const clock = { t: 0 };
    const h = harness({
      now: () => clock.t,
      fetch: {
        serve: (url) => {
          if (url.includes("/assets/engine/data/items-")) clock.t += 50_000; // the item table takes fifty seconds to arrive
          return undefined;
        },
      },
    });
    await h.start();
    const request = farm(C0, { budgetMs: 20_000, steps: 3 });
    const { id, messages, last } = await h.ask(request);
    const steps = stepsOf(pageChecks(request, id, messages));
    expect(steps[0]).toMatchObject({ status: "optimal", proven: true });
    expect(steps.map((step) => step.index)).toEqual([0, 1, 2, 3]);
    expect(last).toMatchObject({ stopped: "limit", steps: 3 });
    expect(last.elapsedMs).toBeGreaterThanOrEqual(50_000); // the elapsed time is the whole request
  });

  it("of a farm path is the whole path's: each step may use all that is left, and the path ends when it is spent", async () => {
    const clock = { t: 0 };
    // every run of the solver takes 600 ms of the clock of the engine (a step runs once for each haste level it looks at): the budget of 6,000 is gone after a step or two
    const { highs: spied } = spyOn(highs, { clock: () => clock.t, before: () => (clock.t += 600) });
    const h = harness({ now: () => clock.t, solver: spied });
    await h.start();
    const request = farm(C0, { budgetMs: 6000, steps: 8 });
    const { id, messages, last } = await h.ask(request);
    const steps = stepsOf(pageChecks(request, id, messages));
    expect(last).toMatchObject({ stopped: "time" });
    expect(last.steps).toBeGreaterThanOrEqual(1);
    expect(last.steps).toBeLessThan(8);
    expect(steps.map((step) => step.index).slice(0, last.steps + 1)).toEqual(Array.from({ length: last.steps + 1 }, (_, at) => at)); // Equip now, then the steps in order
  });

  it("of the best sets and Every slot counts from the moment the data is in too", async () => {
    const clock = { t: 0 };
    const h = harness({
      now: () => clock.t,
      fetch: {
        serve: (url) => {
          if (url.includes("/assets/engine/data/items-")) clock.t += 50_000;
          return undefined;
        },
      },
    });
    await h.start();
    const set = (await h.ask(sets(C0, { budgetMs: 20_000 }))).last;
    expect(set).toMatchObject({ type: "result", mode: "best-sets", status: "optimal", proven: true });
    const every = (await h.ask(slots(C0, { budgetMs: 20_000 }))).last;
    expect(every).toMatchObject({ type: "result", mode: "every-slot" });
  });

  it("of the best sets that is spent before it begins gives a set that was not found in time, and Equip now has none either", async () => {
    const clock = { t: 0 };
    const h = harness({ now: () => (clock.t += 10) }); // every look at the clock costs ten milliseconds of a budget of one
    await h.start();
    const request = sets(C0, { budgetMs: 1 });
    const { id, messages, last } = await h.ask(request);
    pageChecks(request, id, messages);
    expect(last).toMatchObject({ type: "result", mode: "best-sets", status: "time_limit", proven: false, label: LABEL_NO_INCUMBENT, kit: null, F: null, gain: null, acquired: [] });
  });
});

// ---- the best sets ----------------------------------------------------------------------------------------------------------------------

describe("the best sets", () => {
  for (const [name, c] of [["case 0", C0], ["case 1", C1], ["case 2", C2]]) {
    it(`of ${name} are valid, are worth at least the path's step 2, and start from the same Equip now`, async () => {
      const h = harness();
      await h.start();
      const path = await h.ask(farm(c, { steps: 3 }));
      const pathSteps = stepsOf(pathChecked(path, farm(c, { steps: 3 })));
      for (const k of [2, 3]) {
        const request = sets(c, { k });
        const { id, messages, last } = await h.ask(request);
        const [result] = pageChecks(request, id, messages).filter((message) => message.type === "result");
        expect(result).toMatchObject({ mode: "best-sets", k, status: "optimal", proven: true, label: null });
        expect(result.acquired.length).toBeLessThanOrEqual(k);
        expect(result.baseline.F).toBe(pathSteps[0].F); // the same Equip now
        expect(Number.isInteger(result.hasteAssumed)).toBe(true); // the haste its own kit counts
        if (result.acquired.length === 0) expect(result.hasteAssumed).toBe(pathSteps[0].hasteAssumed);
        if (result.acquired.length > 0) {
          expect(rational(result.gain).sign()).toBe(1);
          // k additions at once are worth at least the first k steps of the path
          const stepK = pathSteps[Math.min(k, pathSteps.length - 1)];
          if (stepK.index === k) expect(rational(result.F).compare(rational(stepK.F))).toBeGreaterThanOrEqual(0);
        }
        expect(last).toBe(messages.at(-1));
      }
    });
  }

  it("of a case that has something to add acquire it with a cost that the tier mode explains", async () => {
    const h = harness();
    await h.start();
    const request = sets(C0, { k: 3, tierMode: { mode: "fixed", N: 10 } });
    const { id, messages } = await h.ask(request);
    const [result] = pageChecks(request, id, messages).filter((message) => message.type === "result");
    expect(result.acquired.length).toBeGreaterThan(0);
    for (const entry of result.acquired) {
      expect(entry.ident.endsWith("@10")).toBe(true);
      expect(entry.cost.exp).toBeGreaterThan(0);
    }
    expect(rational(result.F).sub(rational(result.baseline.F)).toString()).toBe(result.gain);
  });

  it("report their stage, and nothing else of a path", async () => {
    const h = harness();
    await h.start();
    const request = sets(C0);
    const { id, messages } = await h.ask(request);
    const reports = progressOf(pageChecks(request, id, messages));
    expect([...new Set(reports.map((report) => report.stage))]).toEqual(["loading", "best-sets"]);
    expect(stepsOf(messages)).toEqual([]);
  });
});

// ---- Every slot ---------------------------------------------------------------------------------------------------------------------------

describe("Every slot", () => {
  it("gives 22 rows, one for each place of the kit, sorted as everySlot of path.js sorts them, and the rows that it gives on the pool of candidates and owned items", async () => {
    const h = harness();
    await h.start();
    for (const c of [C0, C1, C2]) {
      const request = slots(c, { limit: 3 });
      const { id, messages } = await h.ask(request);
      const [result] = pageChecks(request, id, messages).filter((message) => message.type === "result");
      expect(result.rows).toHaveLength(22);
      expect(result.rows.map((row) => row.index)).toEqual([...Array(22).keys()]);
      expect(result.rows.map((row) => row.current)).toEqual(c.kit);
      for (const row of result.rows) expect(row.swaps.length).toBeLessThanOrEqual(3);
      // the very rows of the function, called on the same session, kit, buffs and candidates
      const table = readItemTable(JSON.parse(ITEMS_BYTES.toString("utf8")));
      const bundle = readBundle(JSON.parse(BUNDLE_BYTES.toString("utf8")));
      const profile = assembleProfile(bundle, choices(c));
      const session = createSession({
        highs,
        profile,
        setup: c.scenario.setup,
        buffset: { set: bundle.buffs[c.scenario.buffs].set, table: bundle.buff_table },
        monkBins: bundle.monk_bins === null ? undefined : bundle.monk_bins,
        options: {},
      });
      try {
        const itemOf = (name) => atTier(table.records.get(name.slice(0, name.lastIndexOf("@"))), Number(name.slice(name.lastIndexOf("@") + 1)), bundle);
        const candidates = candidatesFor(table.records, bundle, profile, { evidence: c.scenario.evidence, tierMode: READY4 });
        // the items on offer, as the reference makes them (`_every_slot` in fixture_cases.py): the candidates, and the owned items with their counts
        const owned = c.owned.map(([name, count]) => [itemOf(name), count]);
        const direct = everySlot(session, c.kit.map((name) => (name === null ? null : itemOf(name))), candidates, { buffs: c.buffs, limit: 3, owned });
        expect(result.rows.map((row) => row.swaps.map((swap) => [swap.ident, swap.delta]))).toEqual(
          direct.map((row) => row.swaps.map((swap) => [`${swap.item.key}@${swap.item.tier}`, swap.delta.toString()])),
        );
      } finally {
        closeSession(session);
      }
    }
  });

  describe("offers the visitor's own items too, as the reference does: the pool of a swap is the candidates and the owned items", () => {
    // C0 owns w90029 at +4 and at +10 (a chest piece), w90002 at +0 only (a crafted item: a ready4 candidate would be at +4), w90001 at +0 and +4, and the hidden record w90041;
    // its kit wears the +10 chest piece in the chest place (13). Here the visitor wears the +4 one instead and carries the +10 one.
    const wearing = (changes) => {
      const kit = [...C0.kit];
      for (const [at, name] of Object.entries(changes)) kit[Number(at)] = name;
      return kit;
    };
    const rowsOf = async (request) => {
      const h = harness();
      await h.start();
      const { id, messages } = await h.ask(request);
      return pageChecks(request, id, messages).find((message) => message.type === "result").rows;
    };
    const idents = (row) => row.swaps.map((swap) => swap.ident);

    it("an owned item that is not worn and beats the worn one in its place is a swap with a gain: the +10 chest piece over the +4 one", async () => {
      // (since Natural Durability the best kit wears the +4 chest piece in the chest place and the +10 one in the Any place 18, where it used to wear w80758@4: the visitor here wears those two and carries the +10 one)
      expect(C0.kit[18]).toBe("w90029@10");
      const rows = await rowsOf(slots(C0, { kit: wearing({ 13: "w90029@4", 18: "w80758@4" }), limit: 10 }));
      expect(rows[13].current).toBe("w90029@4");
      const offer = rows[13].swaps.find((swap) => swap.ident === "w90029@10");
      expect(offer, "the +10 copy is owned").toBeDefined();
      expect(offer.deltaValue).toBeGreaterThan(0);
      // it is not a candidate (the ready4 candidate of the key is the +4 one), so nothing but the owned set offers it
      const list = candidatesFor(readItemTable(JSON.parse(ITEMS_BYTES.toString("utf8"))).records, readBundle(JSON.parse(BUNDLE_BYTES.toString("utf8"))), assembleProfile(readBundle(JSON.parse(BUNDLE_BYTES.toString("utf8"))), choices(C0)), {
        evidence: C0.scenario.evidence,
        tierMode: READY4,
      });
      expect(list.some((item) => item.key === "w90029" && item.tier === 10)).toBe(false);
    });

    it("an owned item and a candidate of the same key at two tiers are two swaps: the crafted item owned at +0 and the same item at +4 as a candidate", async () => {
      const rows = await rowsOf(slots(C0, { limit: 10 }));
      const head = rows[0];
      expect(idents(head)).toEqual(expect.arrayContaining(["w90002@0", "w90002@4"]));
      const [owned, candidate] = ["w90002@0", "w90002@4"].map((name) => head.swaps.find((swap) => swap.ident === name));
      expect(owned.delta).not.toBe(candidate.delta);
      expect(C0.owned.some(([name]) => name === "w90002@4")).toBe(false); // the +4 one is not owned: it is the candidate
    });

    it("an item that is owned and is a candidate at that tier is one swap, not two", async () => {
      const rows = await rowsOf(slots(C0, { limit: 10 }));
      for (const row of rows) expect(new Set(idents(row)).size, `place ${row.index}`).toBe(row.swaps.length);
      expect(C0.owned.some(([name]) => name === "w90001@4")).toBe(true);
      expect(C0.kit[0]).not.toBe("w90001@4"); // (C0 wears another helm now: this one is owned, not worn, and a ready4 candidate)
      expect(idents(rows[0]).filter((name) => name === "w90001@4")).toHaveLength(1); // owned, and a ready4 candidate
    });

    it("a hidden record the visitor owns is offered, though no search would offer it, while a copy of it is free", async () => {
      expect(TABLE_RECORD("w90041").owned_only).toBe(true);
      expect(C0.kit[19]).toBe("w90041@4"); // C0 wears its one copy in an Any place, where it is no swap for the head; the visitor here carries it instead
      const rows = await rowsOf(slots(C0, { kit: wearing({ 19: null }), limit: 10 }));
      const offered = rows[0].swaps.find((swap) => swap.ident === "w90041@4");
      expect(offered, "owned, and not worn, so a swap").toBeDefined();
      expect(offered.deltaValue).toBeGreaterThan(0);
    });

    it("a hidden record the visitor owns once and wears is no swap for the head: the page cannot tell it from a candidate, so only the worker's own count drops it", async () => {
      expect(C0.kit[19]).toBe("w90041@4"); // C0's own kit wears its one copy of the relic helm on Any 2
      expect(C0.owned.find(([name]) => name === "w90041@4")[1]).toBe(1);
      const request = slots(C0, { limit: 10 });
      const h = harness();
      await h.start();
      const { id, messages } = await h.ask(request);
      const result = messages.find((message) => message.type === "result"); // as the worker sent it, before the page's check
      expect(result.rows[0].swaps.map((swap) => swap.ident)).not.toContain("w90041@4"); // the head
      for (const row of result.rows) expect(row.swaps.map((swap) => swap.ident), `place ${row.index}`).not.toContain("w90041@4"); // nor any other place: no copy is free
      // +4 is the tier of ready4, where a candidate could be, so the page takes a swap to it: nothing but the worker's count keeps it out
      const phantom = { ...result, rows: result.rows.map((row) => (row.index === 0 ? { ...row, swaps: [{ ident: "w90041@4", delta: "1/1", deltaValue: 1 }] } : row)) };
      expect(() => pageChecks(request, id, [phantom])).not.toThrow();
    });

    it("an owned item the profile cannot use is left out, as a candidate is", async () => {
      expect(TABLE_RECORD("w90040").classes).toEqual(["WIZ"]);
      expect(C0.owned.some(([name]) => name === "w90040@4")).toBe(true);
      const rows = await rowsOf(slots(C0, { limit: 10 }));
      for (const row of rows) expect(idents(row).some((name) => name.startsWith("w90040@")), `place ${row.index}`).toBe(false);
    });
  });

  describe("counts the copies of the visitor's own items: an owned item that is not a candidate is a swap only while a copy is free", () => {
    // The signet w90027 is a ring (Finger), owned at +4. Under the tier mode "fixed +10" the candidates are at +10, so the owned +4 one is no candidate; under "ready4" it is
    // one (a +4 item of the table). C0 wears it on Finger 2 (place 12), where it is its one copy.
    const FINGER_1 = 11;
    const FINGER_2 = 12;
    const RING = "w90027@4";
    const FIXED10 = { mode: "fixed", N: 10 };
    const ownedWith = (count) => C0.owned.map(([name, held]) => [name, name === RING ? count : held]);
    const rowsOf = async (request) => {
      const h = harness();
      await h.start();
      const { id, messages } = await h.ask(request);
      return pageChecks(request, id, messages).find((message) => message.type === "result").rows;
    };
    const idents = (row) => row.swaps.map((swap) => swap.ident);

    it("does not offer a ring owned once and worn on one finger for the other, and offers it with a second copy owned", async () => {
      expect(C0.kit[FINGER_2]).toBe(RING);
      expect(C0.owned.find(([name]) => name === RING)[1]).toBe(1);
      const once = await rowsOf(slots(C0, { tierMode: FIXED10, owned: ownedWith(1), limit: 10 }));
      expect(idents(once[FINGER_1])).not.toContain(RING); // the one ring is on Finger 2
      const twice = await rowsOf(slots(C0, { tierMode: FIXED10, owned: ownedWith(2), limit: 10 }));
      expect(idents(twice[FINGER_1])).toContain(RING); // a spare copy is a swap
      expect(idents(twice[FINGER_2])).not.toContain(RING); // (never for the place that wears it)
    });

    it("puts no count on a candidate: the same ring, a candidate under ready4, is offered with the one copy worn", async () => {
      const rows = await rowsOf(slots(C0, { tierMode: { ...READY4 }, owned: ownedWith(1), limit: 10 }));
      expect(idents(rows[FINGER_1])).toContain(RING); // getting another copy
    });
  });

  it("gives at most the limit of swaps for a place (3 when the request says none), and no solve is made", async () => {
    const h = harness();
    await h.start();
    const one = (await h.ask(slots(C0, { limit: 1 }))).last;
    expect(one.rows.every((row) => row.swaps.length <= 1)).toBe(true);
    expect(one.rows.some((row) => row.swaps.length === 1)).toBe(true);
    const ten = (await h.ask(slots(C0, { limit: 10 }))).last;
    expect(ten.rows.some((row) => row.swaps.length > 3)).toBe(true);
    const request = slots(C0);
    delete request.limit;
    const none = (await h.ask(request)).last;
    expect(none.rows.every((row) => row.swaps.length <= 3)).toBe(true);
    expect(none.rows.map((row) => row.swaps.length)).toEqual((await h.ask(slots(C0, { limit: 3 }))).last.rows.map((row) => row.swaps.length));
  });

  it("takes a kit with empty places, and no optional buffs", async () => {
    const h = harness();
    await h.start();
    const request = slots(C0, { kit: new Array(22).fill(null), buffs: [] });
    const { id, messages } = await h.ask(request);
    const [result] = pageChecks(request, id, messages).filter((message) => message.type === "result");
    expect(result.rows.every((row) => row.current === null)).toBe(true);
    expect(result.rows.some((row) => row.swaps.length > 0)).toBe(true);
  });

  it("refuses a kit that wears an item that is not owned, or more of it than is owned, as a bad request, and the worker goes on", async () => {
    const h = harness();
    await h.start();
    const worn = C0.kit.find((name) => name !== null);
    const strange = [...C0.kit];
    strange[strange.indexOf(null)] = "w90002@7"; // owned at no tier
    expect((await h.ask(slots(C0, { kit: strange }))).last).toMatchObject({ type: "error", code: "bad-request", message: expect.stringMatching(/not owned/i) });
    const doubled = new Array(22).fill(null);
    const count = C0.owned.find(([name]) => name === worn)[1];
    for (let at = 0; at <= count; at += 1) doubled[at] = worn; // one more than owned
    expect((await h.ask(slots(C0, { kit: doubled }))).last).toMatchObject({ type: "error", code: "bad-request" });
    expect((await h.ask(slots(C0, { owned: [] }))).last).toMatchObject({ type: "error", code: "bad-request" }); // nothing owned, and a kit that wears something
    expect((await h.ask(slots(C0))).last).toMatchObject({ type: "result", mode: "every-slot" });
  });

  it("refuses an owned item that the table does not have, and a buff that the buff set does not have, as bad requests", async () => {
    const h = harness();
    await h.start();
    expect((await h.ask(slots(C0, { owned: [...C0.owned, ["w999999@4", 1]] }))).last).toMatchObject({ type: "error", code: "bad-request" });
    expect((await h.ask(slots(C0, { buffs: [987654] }))).last).toMatchObject({ type: "error", code: "bad-request" });
    expect((await h.ask(slots(C0))).last).toMatchObject({ type: "result", mode: "every-slot" });
  });

  it("reports its stage", async () => {
    const h = harness();
    await h.start();
    const request = slots(C0);
    const { id, messages } = await h.ask(request);
    expect([...new Set(progressOf(pageChecks(request, id, messages)).map((report) => report.stage))]).toEqual(["loading", "every-slot"]);
  });
});

// ---- the worker's handling of the modes ----------------------------------------------------------------------------------------------

describe("the modes in the worker's handler", () => {
  it("answers a request of a mode that the optimizer has no shape for with a bad request, and an engine that lacks the method of a mode with not-implemented", async () => {
    const h = harness();
    await h.start();
    for (const mode of ["best-1", "equip", "farm_path"]) {
      expect((await h.ask({ ...farm(C0), mode })).last).toMatchObject({ type: "error", code: "bad-request" });
    }
    expect(h.asked).toEqual([]);
    const old = harness({ engineOver: { farmPath: undefined, bestSets: undefined, everySlot: undefined } });
    await old.start();
    for (const request of [farm(C0), sets(C0), slots(C0)]) expect((await old.ask(request)).last).toMatchObject({ type: "error", code: "not-implemented" });
    expect((await old.ask(equip(C1))).last).toMatchObject({ type: "result", F: C1.F });
  });

  it("keeps the answer of Equip now after the other modes ran on the same session: nothing of a path, a set or a row is left in it", async () => {
    const h = harness();
    await h.start();
    for (const request of [farm(C0), sets(C0), slots(C0)]) await h.ask(request);
    const { last } = await h.ask(equip(C0));
    expect(last).toMatchObject({ type: "result", mode: "equip-now", status: "optimal", F: C0.F, value: C0.value, kit: C0.kit, buffs: C0.buffs, hasteAssumed: C0.hasteAssumed });
    expect(h.scenarios.stats().sessions, "one session served all four").toBe(1);
  });

  it("keeps the answers of Equip now as they were, with the stage of its reports", async () => {
    const h = harness();
    await h.start();
    let first = true;
    for (const c of EQUIP_NOW.cases) {
      const request = equip(c);
      const { id, messages, last } = await h.ask(request);
      pageChecks(request, id, messages);
      expect(last).toMatchObject({ type: "result", mode: "equip-now", status: "optimal", F: c.F, kit: c.kit });
      // the first request loads the data; the others find it there
      expect([...new Set(progressOf(messages).map((report) => report.stage))]).toEqual(first ? ["loading", "equip-now"] : ["equip-now"]);
      first = false;
    }
  });
});

/** The messages of a farm path request that was asked with `h.ask`, checked as the page checks them. */
function pathChecked(answer, request) {
  return pageChecks(request, answer.id, answer.messages);
}
