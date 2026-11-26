// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// The answer of the Upgrade section: Equip now, the Next step and the steps after it, worked out by the optimizer for the gear of the visitor and drawn under the owned list. The
// optimizer's client is a stand-in that the test drives (the messages are those protocol.js documents), the section is the contract copy of the page with the gear input on a table
// of invented items, and the page's own words come from format.js. The request is held to protocol.js's own check. Every name is invented.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createEngineClient } from "../pipeline/trioforge/site/static/engine/client.js";
import { LIMITS, validateRequest } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { dump, empty, row } from "./dump-helpers.mjs";
import { makeSite, siteFetch } from "./engine-site-fixture.mjs";
import { $, $$, STATIC, press, type } from "./upgrade-helpers.mjs";
import {
  CLIENT_URL,
  UPDATED_TEXT,
  VIEW,
  addByName,
  costOf,
  ended,
  equipStep,
  fakeEngine,
  flush,
  kitOf,
  lostStep,
  mountAnswer,
  pathStep,
  pause,
  textOf,
} from "./upgrade-answer-helpers.mjs";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

const file = (text, name = "inventory.txt") => new File([text], name);
/** Wait until the answer has sent `count` requests (the pause is 0 ms in these tests unless they say otherwise). */
const sent = (t, count) => vi.waitFor(() => expect(t.engine.runs).toHaveLength(count), { timeout: 5000, interval: 5 });
/** The section with a request on its way: one item added, the pause over. */
async function started({ name = "tarn signet", tier = "4", ...options } = {}) {
  const t = mountAnswer({ pauseMs: 0, ...options });
  addByName(name, tier);
  await sent(t, 1);
  return { ...t, run: t.engine.runs[0] };
}

const equipRows = () =>
  $$("#upgrade-equip tbody tr").map((tr) => ({
    slot: tr.querySelector("th").textContent,
    item: tr.querySelector(".owned-name")?.textContent ?? null,
    where: tr.querySelector(".equip-where")?.textContent ?? null,
    empty: tr.querySelector(".muted")?.textContent ?? null,
  }));
const stepOf = (node) => ({
  what: node.querySelector(".step-what")?.textContent ?? null,
  gain: node.querySelector(".step-gain")?.textContent ?? null,
  source: node.querySelector(".step-source")?.textContent ?? null,
  cost: node.querySelector(".step-cost")?.textContent ?? null,
  hint: node.querySelector(".step-hint")?.textContent ?? null,
  label: node.querySelector(".step-label")?.textContent ?? null,
});
const next = () => stepOf($("#upgrade-next .step"));
const then = () => $$("#upgrade-then-list > li").map(stepOf);
const faultText = () => textOf("#upgrade-fault .status-text");
const buttonsOf = (selector) => $$(`${selector} button`).map((b) => b.textContent);

// ---- the request ----------------------------------------------------------------------------------------------------------------------------------

describe("the request", () => {
  it("is a farm path request with exactly the protocol's fields: the view of the page, the owned pairs, ready +4, eight steps and a minute", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    addByName("tarn signet", "4");
    addByName("corbel cap", "0");
    await sent(t, 1);
    const { request } = t.engine.runs[0];
    expect(Object.keys(request).sort()).toEqual(["budgetMs", "kind", "level", "mode", "owned", "scenario", "steps", "tierMode", "trio", "v"]);
    expect(request).toEqual({
      v: 1,
      kind: "scenario",
      trio: "pal-mnk-ber",
      level: 50,
      mode: "farm-path",
      scenario: { race: VIEW.race, role: VIEW.role, buffs: VIEW.buffs, evidence: VIEW.evidence, setup: VIEW.setup },
      owned: [["w80305@0", 1], ["w80301@4", 2]],
      tierMode: { mode: "ready4" },
      steps: 8,
      budgetMs: 60_000,
    });
    expect(request.owned).toEqual(t.gear.toOwnedPairs());
    expect(request.steps).toBe(LIMITS.maxPathSteps);
    expect(validateRequest(request), "protocol.js takes it as it is").toEqual(request);
  });

  it("names the setup the page shows (never none) and the evidence and buffs the page shows", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    t.setView({ race: "OGR", role: "tank", setup: "1h-shield", evidence: "strict", buffs: "group" });
    addByName("tarn signet");
    await sent(t, 1);
    expect(t.engine.runs[0].request.scenario).toEqual({ race: "OGR", role: "tank", buffs: "group", evidence: "strict", setup: "1h-shield" });
  });

  it("loads the client from the address the manifest names, once, and gives it the results area of the section to put its question in", async () => {
    const t = await started();
    addByName("corbel cap");
    await sent(t, 2);
    expect(t.engine.loaded).toEqual([CLIENT_URL]);
    expect(t.engine.options).toHaveLength(1);
    const [options] = t.engine.options;
    expect(options.window).toBe(window);
    expect(options.document).toBe(document);
    expect(options.mount.closest("#upgrade-results")).not.toBeNull();
    expect(options.mount.closest("#upgrade")).toBe(t.root);
    expect(options.mount.children).toHaveLength(0); // (the client builds its question in it)
  });

  it("does not load the client before there is something to ask", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    type($("#upgrade-pick"), "tarn");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(t.engine.loaded).toEqual([]);
    expect(t.engine.runs).toEqual([]);
    addByName("tarn signet");
    await sent(t, 1);
    expect(t.engine.loaded).toEqual([CLIENT_URL]);
  });
});

// ---- when it runs ---------------------------------------------------------------------------------------------------------------------------------

describe("when it runs", () => {
  it("waits for a pause of 600 ms after a change, and sends one request for a burst of changes", async () => {
    vi.useFakeTimers();
    const t = mountAnswer();
    addByName("tarn signet");
    await vi.advanceTimersByTimeAsync(300);
    addByName("corbel cap");
    await vi.advanceTimersByTimeAsync(599);
    await flush();
    expect(t.engine.runs).toHaveLength(0);
    await pause(1);
    expect(t.engine.runs).toHaveLength(1);
    expect(t.engine.runs[0].request.owned).toHaveLength(2);
    await pause(5000);
    expect(t.engine.runs, "and not again").toHaveLength(1);
  });

  it("stops the path in flight and then sends the new request, each time", async () => {
    const t = await started();
    addByName("corbel cap");
    await sent(t, 2);
    expect(t.engine.log).toEqual(["stop", "run1", "stop", "run2"]);
    t.setView({ role: "melee" });
    await sent(t, 3);
    expect(t.engine.log.slice(-2)).toEqual(["stop", "run3"]);
  });

  it("sends the new request even if the first one is still waiting for the optimizer", async () => {
    const t = await started();
    t.run.onProgress({ phase: "loading", stage: "loading" });
    addByName("fenwick greaves");
    await sent(t, 2);
    expect(t.engine.runs[1].request.owned.map(([ident]) => ident)).toEqual(["w80308@4", "w80301@4"]);
  });

  it("restarts when a switch the request uses changes, and not when the page shows the same view again", async () => {
    const t = await started();
    t.setView({});
    t.setView({ race: VIEW.race });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(t.engine.runs, "the same view: nothing new").toHaveLength(1);
    let count = 1;
    for (const change of [{ race: "OGR" }, { role: "melee" }, { setup: "2h" }, { buffs: "group" }, { evidence: "strict" }]) {
      t.setView(change);
      count += 1;
      await sent(t, count);
      expect(t.engine.runs[count - 1].request.scenario).toMatchObject(change);
    }
    expect(t.engine.log.filter((entry) => entry === "stop")).toHaveLength(6);
  });

  it("sends nothing for a switch while nothing is owned, and the view of the moment when something is", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    t.setView({ race: "OGR" });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(t.engine.runs).toEqual([]);
    expect(t.engine.loaded).toEqual([]);
    addByName("tarn signet");
    await sent(t, 1);
    expect(t.engine.runs[0].request.scenario.race).toBe("OGR");
  });

  it("sends nothing for an empty list; when the list becomes empty the path is stopped at once and the results go", async () => {
    const t = await started();
    t.run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    expect($("#upgrade-equip").hidden).toBe(false);
    const before = t.engine.log.length;
    $("#upgrade-owned button").click(); // Remove: the last row
    expect(t.engine.log.slice(before), "stopped when the list changed, not after the pause").toEqual(["stop"]);
    expect($("#upgrade-equip").hidden).toBe(true);
    expect(equipRows()).toEqual([]);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(t.engine.runs, "and nothing is sent").toHaveLength(1);
    expect($("#upgrade-stop")).toBeNull();
  });

  it("is stopped and cleared by Clear, and what the stopped request says afterwards is not drawn", async () => {
    const t = await started();
    t.run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.run.onStep(pathStep(1, { ident: "w80308@4", gain: 50 }));
    $("#upgrade-clear").click();
    expect(t.engine.log.at(-1)).toBe("stop");
    expect($("#upgrade-equip").hidden).toBe(true);
    expect($("#upgrade-next").hidden).toBe(true);
    t.run.onStep(pathStep(2, { ident: "w80305@4", gain: 40 }));
    t.run.onProgress({ phase: "solving", stage: "step", step: 3 });
    t.run.finish(ended("stopped", 2));
    await flush();
    expect($("#upgrade-then").hidden).toBe(true);
    expect(textOf("#upgrade-end")).toBe("");
    expect(textOf("#upgrade-progress")).toBe("");
    expect(t.spoken).toEqual([`Equip now is ready: 1 of 22 places filled. Next step: Get Fenwick Greaves +4, gain +50.`]); // (what was said before the stop stands)
  });

  it("draws nothing of a request that a newer one superseded: not its steps, not its progress, not its result", async () => {
    const t = await started();
    t.run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.run.onStep(pathStep(1, { ident: "w80308@4", gain: 50, kit: kitOf({ 11: "w80301@4", 14: "w80308@4" }) }));
    addByName("corbel cap"); // a change of the gear in the middle of the path
    await sent(t, 2);
    expect(t.engine.log.slice(-2)).toEqual(["stop", "run2"]);
    expect($("#upgrade-equip").hidden, "the old answer is gone once the new request is sent").toBe(true);
    expect($("#upgrade-next").hidden).toBe(true);
    // the old path was stopped, and may land one step late
    t.run.onStep(pathStep(2, { ident: "w80305@4", gain: 40 }));
    t.run.onProgress({ phase: "solving", stage: "step", step: 3 });
    t.run.finish(ended("stopped", 2));
    await flush();
    expect($("#upgrade-then").hidden).toBe(true);
    expect($("#upgrade-equip").hidden).toBe(true);
    expect(textOf("#upgrade-end")).toBe("");
    expect(textOf("#upgrade-progress")).not.toContain("step 3");
    // the new one is drawn
    const second = t.engine.runs[1];
    second.onStep(equipStep({ kit: kitOf({ 1: "w80305@4" }) }));
    expect(equipRows()[1]).toMatchObject({ slot: "Face", item: "Corbel Cap +4" });
    expect(equipRows()[11].empty).toBe("Leave empty");
    second.onStep(pathStep(1, { ident: "w80308@4", gain: 60 }));
    expect(next().what).toBe("Get Fenwick Greaves +4");
    second.finish(ended("no-gain", 1));
    await flush();
    expect(textOf("#upgrade-end")).toBe("Nothing more you can add gains anything.");
  });

  it("does not draw the faults of a superseded request either", async () => {
    const t = await started();
    addByName("corbel cap");
    await sent(t, 2);
    t.run.fail(Object.assign(new Error("The optimizer stopped working."), { code: "worker-failed" }));
    await flush();
    expect($("#upgrade-fault")?.hidden ?? true).toBe(true);
    expect(textOf("#upgrade-fault")).toBe("");
  });

  it("keeps at most one request waiting: those that a newer change superseded while the path was ending never begin, and so never load or solve anything", async () => {
    const t = await started();
    t.engine.autoStop = false; // a long step: the path does not end the moment it is told to
    t.run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    const stops = () => t.engine.log.filter((entry) => entry === "stop").length;
    addByName("corbel cap");
    await vi.waitFor(() => expect(stops()).toBe(2)); // the second request was sent: it told the first to stop, and waits for it
    addByName("fenwick greaves");
    await vi.waitFor(() => expect(stops()).toBe(3));
    addByName("dunmere helm");
    await vi.waitFor(() => expect(stops()).toBe(4));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(t.engine.runs, "none of the three is given to the client while the first has not ended").toHaveLength(1);
    t.run.finish(ended("stopped", 0)); // the long step ends
    await sent(t, 2);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(t.engine.runs, "and then the last one only").toHaveLength(2);
    expect(t.engine.runs[1].request.owned.map(([ident]) => ident)).toEqual(["w80305@4", "w80304@4", "w80308@4", "w80301@4"]);
    expect(t.engine.log).toEqual(["stop", "run1", "stop", "stop", "stop", "run2"]);
  });

  it("does not restart for nothing: a view that comes back to what was sent within the pause, or an item added and taken out, stops nothing and sends nothing", async () => {
    vi.useFakeTimers();
    const t = mountAnswer();
    addByName("tarn signet");
    await pause(600);
    expect(t.engine.runs).toHaveLength(1);
    const log = [...t.engine.log];
    t.setView({ race: "OGR" });
    await vi.advanceTimersByTimeAsync(100);
    t.setView({ race: VIEW.race }); // the race the request was sent with
    await pause(600);
    expect(t.engine.log, "the view came back: nothing is stopped, nothing is sent").toEqual(log);
    addByName("corbel cap");
    await vi.advanceTimersByTimeAsync(100);
    $$("#upgrade-owned li").find((li) => li.dataset.ident === "w80305@4").querySelector("button").click(); // taken out again
    await pause(600);
    expect(t.engine.log, "the list came back: nothing is stopped, nothing is sent").toEqual(log);
    addByName("fenwick greaves"); // a real change still goes
    await pause(600);
    expect(t.engine.runs).toHaveLength(2);
  });

  it("sends an identical request again when the last one failed, and when the section was cleared in between", async () => {
    vi.useFakeTimers();
    const t = mountAnswer();
    addByName("tarn signet");
    await pause(600);
    t.engine.runs[0].fail(Object.assign(new Error("The optimizer stopped working."), { code: "worker-failed" }));
    await flush();
    addByName("corbel cap");
    await vi.advanceTimersByTimeAsync(100);
    $$("#upgrade-owned li").find((li) => li.dataset.ident === "w80305@4").querySelector("button").click();
    await pause(600);
    expect(t.engine.runs, "what failed is asked again").toHaveLength(2);
    expect(t.engine.runs[1].request).toEqual(t.engine.runs[0].request);
    $("#upgrade-clear").click();
    addByName("tarn signet");
    await pause(600);
    expect(t.engine.runs, "after Clear the same gear is a new request").toHaveLength(3);
  });

  it("withdraws the request that waits for the visitor's answer instead of stopping it, when Clear empties the section while the question is up", async () => {
    const engine = fakeEngine();
    engine.consent = "unknown"; // the question has not been answered: nothing is loaded, and no worker is there
    const t = await started({ engine });
    $("#upgrade-clear").click();
    expect(t.engine.log.slice(-1), "withdrawn, so that a yes to the question loads nothing for an answer that is thrown away").toEqual(["withdraw"]);
    expect(t.engine.log).not.toContain("stop");
    expect(t.engine.log, "the request is taken back alone: the client is never told to cancel what every part of the page asked for").not.toContain("cancel");
  });

  it("does not kill a worker that is there: a request that is on it is only stopped when Clear empties the section", async () => {
    const t = await started(); // (the optimizer was agreed to)
    $("#upgrade-clear").click();
    expect(t.engine.log.slice(-1)).toEqual(["stop"]);
    expect(t.engine.log).not.toContain("withdraw");
    expect(t.engine.log).not.toContain("cancel");
  });

  it("withdraws the waiting request when a change comes while the question is up, and sends the new one at once: the question is for the new one", async () => {
    const engine = fakeEngine();
    engine.consent = "unknown";
    const t = await started({ engine });
    addByName("corbel cap");
    await sent(t, 2);
    expect(t.engine.log).toEqual(["run1", "withdraw", "run2"]);
    expect(t.engine.runs[1].request.owned).toHaveLength(2);
  });

  it("does not send a request that a newer one superseded while the code of the optimizer was still coming, and lets it stop nothing", async () => {
    const engine = fakeEngine();
    let arrive;
    const real = engine.loadEngine;
    engine.loadEngine = (url) => new Promise((resolve) => (arrive = () => resolve(real(url))));
    const t = mountAnswer({ pauseMs: 0, engine });
    addByName("tarn signet");
    await vi.waitFor(() => expect(arrive).toBeTypeOf("function"));
    addByName("corbel cap"); // a second change while the code is still coming
    await new Promise((resolve) => setTimeout(resolve, 40));
    arrive();
    await vi.waitFor(() => expect(t.engine.runs.length).toBeGreaterThan(0), { timeout: 5000, interval: 5 });
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(t.engine.runs, "one request").toHaveLength(1);
    expect(t.engine.runs[0].request.owned.map(([ident]) => ident)).toEqual(["w80305@4", "w80301@4"]);
    expect(t.engine.log, "and the one that was superseded did not even tell the path in flight to stop").toEqual(["stop", "run1"]);
  });
});

// ---- the question of the optimizer, with the client itself -----------------------------------------------------------------------------------------------

describe("the optimizer's own question", () => {
  /** The client of the optimizer itself, on the fake site of the engine tests, with workers that are counted and do nothing: what the page asks of it is what it does. */
  function realClient() {
    const made = makeSite();
    made.files.set("/engine-manifest.json", new TextEncoder().encode(JSON.stringify(made.manifestJson)));
    const net = siteFetch(made);
    const spawned = [];
    return {
      spawned,
      loadEngine: async () => ({
        getEngineClient: (options) =>
          createEngineClient({
            ...options,
            fetch: (url, init) => net.fetchImpl(new URL(String(url), "https://trioforge.test").href, init),
            trustedTypes: null,
            storage: null,
            createWorker: (url) => {
              spawned.push(String(url));
              return { postMessage() {}, terminate() {}, onmessage: null, onmessageerror: null, onerror: null };
            },
          }),
      }),
    };
  }
  const accept = () =>
    vi.waitFor(
      () => {
        const button = document.querySelector('#upgrade-results [data-action="accept"]');
        if (button === null) throw new Error("the question is not up yet");
        return button;
      },
      { timeout: 5000, interval: 10 },
    );

  it("starts no download for a request that Clear withdrew while the question was up: a yes afterwards loads nothing, and the panel goes", async () => {
    const engine = realClient();
    mountAnswer({ pauseMs: 0, engine });
    addByName("tarn signet");
    const yesButton = await accept();
    $("#upgrade-clear").click();
    yesButton.click();
    await vi.waitFor(() => expect(document.querySelector("#upgrade-results .engine-consent")).toBeNull(), { timeout: 2000 });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(engine.spawned, "no worker was started, so nothing was downloaded").toEqual([]);
  });

  it("starts one download, for the request that replaced the one that waited, when the visitor says yes", async () => {
    const engine = realClient();
    mountAnswer({ pauseMs: 0, engine });
    addByName("tarn signet");
    const yesButton = await accept();
    addByName("corbel cap"); // a change while the question is up: the waiting request is withdrawn, and the new one waits in its place
    await new Promise((resolve) => setTimeout(resolve, 60));
    yesButton.click();
    await vi.waitFor(() => expect(engine.spawned).toHaveLength(1), { timeout: 2000 });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(engine.spawned).toHaveLength(1);
  });
});

// ---- Stop and the working line are for a path that is being worked out --------------------------------------------------------------------------------

describe("while the question of the optimizer is up", () => {
  it("shows no Stop and no working line: nothing is worked out until the visitor has said yes", async () => {
    const engine = fakeEngine();
    engine.consent = "unknown";
    await started({ engine });
    expect($("#upgrade-stop")).toBeNull();
    expect($("#upgrade-progress").hidden).toBe(true);
    expect(textOf("#upgrade-progress")).toBe("");
  });

  it("shows both when the client reports on its loading after a yes, and the line then follows the reports", async () => {
    const engine = fakeEngine();
    engine.consent = "unknown";
    const t = await started({ engine });
    expect($("#upgrade-stop"), "not before").toBeNull();
    engine.consent = "granted"; // the visitor said yes
    t.run.onProgress({ phase: "loading", loaded: 10, total: 100 }); // the optimizer is being downloaded
    expect($("#upgrade-stop")).not.toBeNull();
    expect($("#upgrade-stop").textContent).toBe("Stop");
    expect(textOf("#upgrade-progress")).toBe("Working out your answer…");
    t.run.onProgress({ phase: "building", stage: "equip-now" });
    expect(textOf("#upgrade-progress")).toBe("Working out what to equip now…");
    expect($$("#upgrade-stop")).toHaveLength(1);
  });

  it("shows Stop when a step comes, if no report came before it", async () => {
    const engine = fakeEngine();
    engine.consent = "unknown";
    const t = await started({ engine });
    t.run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    expect($("#upgrade-stop")).not.toBeNull();
    t.run.finish(ended("no-gain", 0));
    await flush();
    expect($("#upgrade-stop"), "and not again when the path is over").toBeNull();
    t.run.onProgress({ phase: "solving", stage: "step", step: 2 }); // (nothing comes after the result, and a stray report does not bring them back)
    expect($("#upgrade-stop")).toBeNull();
    expect($("#upgrade-progress").hidden).toBe(true);
  });

  it("keeps the line of the fault, alone, when the visitor says not now", async () => {
    const engine = fakeEngine();
    engine.consent = "unknown";
    const t = await started({ engine });
    engine.consent = "declined";
    t.run.fail(Object.assign(new Error("The optimizer was not loaded: the visitor chose to keep the precomputed answers."), { code: "declined" }));
    await flush();
    expect(textOf("#upgrade-fault .status-text")).toBe("The optimizer was not loaded, so there is no answer for your gear yet.");
    expect($("#upgrade-stop")).toBeNull();
    expect($("#upgrade-progress").hidden).toBe(true);
  });

  it("shows them at once, in the place of the old answer, for a visitor who has agreed already: a later request", async () => {
    const t = await started(); // (the optimizer was agreed to)
    t.run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    addByName("corbel cap");
    await sent(t, 2);
    expect($("#upgrade-equip").hidden, "the old answer is gone").toBe(true);
    expect($("#upgrade-stop")).not.toBeNull();
    expect(textOf("#upgrade-progress")).toBe("Working out your answer…");
  });

  it("shows nothing of them before the client is there to say whether the question is up, and then only when it is not", async () => {
    for (const [consent, shown] of [
      ["granted", true],
      ["unknown", false],
    ]) {
      const engine = fakeEngine();
      engine.consent = consent;
      let arrive;
      const real = engine.loadEngine;
      engine.loadEngine = (url) => new Promise((resolve) => (arrive = () => resolve(real(url))));
      const t = mountAnswer({ pauseMs: 0, engine });
      addByName("tarn signet");
      await vi.waitFor(() => expect(arrive).toBeTypeOf("function"));
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect($("#upgrade-stop"), "the first request, before the code has come").toBeNull();
      expect($("#upgrade-progress").hidden).toBe(true);
      arrive();
      await sent(t, 1);
      expect($("#upgrade-stop") !== null, `the code is there, the optimizer is ${consent}`).toBe(shown);
      expect(textOf("#upgrade-progress")).toBe(shown ? "Working out your answer…" : "");
      document.body.innerHTML = "";
    }
  });

  it("shows neither while the question of the client itself is up", async () => {
    const real = (() => {
      const made = makeSite();
      made.files.set("/engine-manifest.json", new TextEncoder().encode(JSON.stringify(made.manifestJson)));
      const net = siteFetch(made);
      return {
        loadEngine: async () => ({
          getEngineClient: (options) =>
            createEngineClient({
              ...options,
              fetch: (url, init) => net.fetchImpl(new URL(String(url), "https://trioforge.test").href, init),
              trustedTypes: null,
              storage: null,
              createWorker: () => ({ postMessage() {}, terminate() {}, onmessage: null, onmessageerror: null, onerror: null }),
            }),
        }),
      };
    })();
    mountAnswer({ pauseMs: 0, engine: real });
    addByName("tarn signet");
    await vi.waitFor(
      () => {
        const button = document.querySelector('#upgrade-results [data-action="accept"]');
        if (button === null) throw new Error("the question is not up yet");
        return button;
      },
      { timeout: 5000, interval: 10 },
    );
    expect(document.querySelector("#upgrade-stop"), "the question is up with the client's own words, and nothing is worked out").toBeNull();
    expect(textOf("#upgrade-progress")).toBe("");
  });
});

// ---- Equip now ------------------------------------------------------------------------------------------------------------------------------------

describe("Equip now", () => {
  const WORN_AND_MOVED = {
    0: "w80304@4", // Dunmere Helm: worn
    1: "w80305@4", // Corbel Cap: added by name
    4: "w80303@4", // Ashen Gorget: in the bank
    8: "w80302@4", // Quillmark Bracer: in the shared bank
    11: "w80301@4", // Tarn Signet: in a bag
  };
  const inventory = () =>
    dump(
      [
        empty("Any Slot"),
        row("Head", "Dunmere Helm +4", 610001),
        row("General 1", "Wicker Basket", 610100, 1, 4),
        row("General 1-Slot1", "Tarn Signet +4", 610002),
        row("Bank1", "Ashen Gorget +4", 610003),
        row("SharedBank1", "Quillmark Bracer +4", 610004),
      ],
      [],
    );

  it("shows the best kit from what is owned, place by place in the order of the kit, at its tiers, and says that a place is empty", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    await t.gear.readFile(file(inventory()));
    addByName("corbel cap", "4");
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf(WORN_AND_MOVED), value: 12345 }));
    const rows = equipRows();
    expect(rows).toHaveLength(22);
    expect(rows.map((r) => r.slot)).toEqual(
      ["Head", "Face", "Ear 1", "Ear 2", "Neck", "Shoulders", "Arms", "Back", "Wrist 1", "Wrist 2", "Hands", "Finger 1", "Finger 2", "Chest", "Legs", "Feet", "Waist", "Range", "Any slot 1", "Any slot 2", "Main hand", "Off hand"],
    );
    expect(rows[0]).toMatchObject({ item: "Dunmere Helm +4", empty: null });
    expect(rows[2]).toEqual({ slot: "Ear 1", item: null, where: null, empty: "Leave empty" });
    expect($("#upgrade-equip").hidden).toBe(false);
    expect(textOf("#upgrade-equip-h")).toBe("Equip now");
  });

  it("says where the copies the kit wears are when they are not worn: in your bags, in your bank, in your shared bank; nothing for a copy that is worn or was added by name", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    await t.gear.readFile(file(inventory()));
    addByName("corbel cap", "4");
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf(WORN_AND_MOVED) }));
    const where = Object.fromEntries(equipRows().map((r) => [r.slot, r.where]));
    expect(where["Head"]).toBeNull(); // worn
    expect(where["Face"]).toBeNull(); // added by name: there is no place to say
    expect(where["Neck"]).toBe("in your bank: move to worn");
    expect(where["Wrist 1"]).toBe("in your shared bank: move to worn");
    expect(where["Finger 1"]).toBe("in your bags: move to worn");
  });

  it("looks for a copy that is not worn in the bags first, then the bank, then the shared bank", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    const text = dump([empty("Any Slot"), row("SharedBank1", "Tarn Signet +4", 610002), row("Bank1", "Tarn Signet +4", 610002), row("General 1", "Wicker Basket", 610100, 1, 4), row("General 1-Slot1", "Tarn Signet +4", 610002)], []);
    await t.gear.readFile(file(text));
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4", 12: "w80301@4", 18: "w80301@4" }) }));
    expect(equipRows().filter((r) => r.where !== null).map((r) => [r.slot, r.where])).toEqual([
      ["Finger 1", "in your bags: move to worn"],
      ["Finger 2", "in your bank: move to worn"],
      ["Any slot 1", "in your shared bank: move to worn"],
    ]);
  });

  it("gives no place to a copy that was added by name, even when the file has other copies of the item", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    await t.gear.readFile(file(dump([empty("Any Slot"), row("Bank1", "Tarn Signet +4", 610002)], [])));
    addByName("tarn signet", "4");
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4", 12: "w80301@4" }) }));
    expect(t.gear.owned()).toEqual([{ key: "w80301", tier: 4, count: 2, locations: [{ location: "bank", count: 1 }] }]);
    expect(equipRows().filter((r) => r.where !== null).map((r) => [r.slot, r.where])).toEqual([["Finger 1", "in your bank: move to worn"]]);
  });

  it("counts the copies: of two the kit wears, the one that is worn needs no note and the one in the bank does", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    const text = dump([empty("Any Slot"), row("Fingers", "Tarn Signet +4", 610002), row("Bank1", "Tarn Signet +4", 610002)], []);
    await t.gear.readFile(file(text));
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4", 12: "w80301@4" }) }));
    expect(equipRows().filter((r) => r.where !== null).map((r) => [r.slot, r.where])).toEqual([["Finger 2", "in your bank: move to worn"]]);
  });

  it("writes the notes from the owned list as it was when the request was sent, whatever the visitor has done since", async () => {
    const t = mountAnswer({ pauseMs: 150 });
    await t.gear.readFile(file(inventory()));
    await sent(t, 1);
    const bank = $$("#upgrade-owned li").find((li) => li.dataset.ident === "w80303@4");
    bank.querySelector("button").click(); // the Ashen Gorget is taken out of the list while the path runs; the pause before the new request is not over
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 4: "w80303@4" }) }));
    expect(equipRows()[4]).toMatchObject({ slot: "Neck", where: "in your bank: move to worn" });
    await sent(t, 2);
    expect($("#upgrade-equip").hidden, "and the new request begins afresh").toBe(true);
  });

  it("says that the kit was found in the time allowed, never that it is the best, when the solve ran out of time", async () => {
    const { run } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }), status: "time_limit", proven: false, label: "best found, not proven optimal", value: 900 }));
    const label = textOf("#upgrade-equip-label");
    expect(label).toContain("best found, not proven optimal");
    expect(label).not.toMatch(/the best kit/i);
    expect(label).toContain("900");
  });

  it("says that the best kit from what is owned is proven when the solver proved it", async () => {
    const { run } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }), value: 12345 }));
    expect(textOf("#upgrade-equip-label")).toBe("The best kit from the gear you have (kit value 12,345).");
  });

  it("says that no kit was found in the time allowed, with the label of the protocol, and shows no places", async () => {
    const { run } = await started();
    run.onStep(equipStep({ kit: null, status: "time_limit", proven: false, label: "not found in time" }));
    expect(textOf("#upgrade-equip-label")).toBe("Not found in time.");
    expect(equipRows()).toEqual([]);
  });

  it("is a table whose rows name their places", async () => {
    const { run } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    expect($$("#upgrade-equip thead th")).toHaveLength(2);
    expect($$("#upgrade-equip tbody th").every((th) => th.getAttribute("scope") === "row")).toBe(true);
    expect($("#upgrade-equip").getAttribute("aria-labelledby")).toBe("upgrade-equip-h");
  });
});

// ---- the Next step ----------------------------------------------------------------------------------------------------------------------------------

describe("the Next step", () => {
  it.each([
    [
      "a new item that arrives at the tier it is scored at",
      pathStep(1, { ident: "w80301@4", kind: "new", cost: costOf(4, 4), gain: 1234 }),
      { what: "Get Tarn Signet +4", gain: "Gain +1,234 kit value", source: "Source: The Hole", cost: null },
    ],
    [
      "a new item that has to be brought up to the tier",
      pathStep(1, { ident: "w80302@4", kind: "new", cost: costOf(0, 4), gain: 800 }),
      { what: "Get Quillmark Bracer +4", gain: "Gain +800 kit value", source: "Source: vendor: Freeport", cost: "16 copies to reach +4" },
    ],
    [
      "another copy of an item the kit wears",
      pathStep(1, { ident: "w80303@4", kind: "copy", cost: costOf(0, 4), gain: 99 }),
      { what: "Get another Ashen Gorget +4", gain: "Gain +99 kit value", source: "Source: quest: Lake Rathetear quest", cost: "16 copies to reach +4" },
    ],
    [
      "an upgrade of an owned copy of an item that arrives at +0",
      pathStep(1, { ident: "w80302@4", kind: "upgrade", sourceTier: 2, cost: costOf(2, 4, 0), gain: 5000 }),
      { what: "Upgrade your Quillmark Bracer +2 to +4", gain: "Gain +5,000 kit value", source: "Source: vendor: Freeport", cost: "12 copies to reach +4" },
    ],
    [
      "an upgrade of an owned copy of a drop, which arrives at +4 and so needs one copy",
      pathStep(1, { ident: "w80301@4", kind: "upgrade", sourceTier: 2, cost: costOf(2, 4, 4), gain: 70 }),
      { what: "Upgrade your Tarn Signet +2 to +4", gain: "Gain +70 kit value", source: "Source: The Hole", cost: "1 copy to reach +4" },
    ],
    [
      "an item whose tier the mode scores below the tier it arrives at (nothing to bring up)",
      pathStep(1, { ident: "w80301@2", kind: "new", cost: null, gain: 30 }),
      { what: "Get Tarn Signet +2", gain: "Gain +30 kit value", source: "Source: The Hole", cost: null },
    ],
  ])("shows %s with its gain, its source and its cost to reach the tier", async (_, step, expected) => {
    const { run } = await started();
    run.onStep(equipStep());
    run.onStep(step);
    expect($("#upgrade-next").hidden).toBe(false);
    expect(textOf("#upgrade-next-h")).toBe("Next step");
    expect(next()).toMatchObject(expected);
  });

  it("words the source as the page words one: where it drops, the quest, the vendor, a recipe, foraging; and says how many places are not named", async () => {
    const words = [
      ["w80304", "Source: Plane of Fear, Befallen, Lower Guk and 2 more"],
      ["w80303", "Source: quest: Lake Rathetear quest"],
      ["w80302", "Source: vendor: Freeport"],
      ["w80305", "Source: crafted"],
      ["w80306", "Source: Foraged in Kithicor Forest"],
      ["w80307", null],
    ];
    const { run } = await started();
    run.onStep(equipStep());
    for (const [key, source] of words) {
      run.onStep(pathStep(1, { ident: `${key}@4`, cost: null }));
      expect(next().source, key).toBe(source);
    }
  });

  it("shows the gain as the page shows a runner-up's difference in kit value: rounded, with its sign and thousands separated", async () => {
    const { run } = await started();
    run.onStep(equipStep());
    run.onStep(pathStep(1, { ident: "w80301@4", gain: 12345.5 }));
    expect(next().gain).toBe("Gain +12,346 kit value");
  });

  it("shows a gain that is more than nothing but rounds to nothing as +<1, in the line and in what is said, and a gain of a half as +1", async () => {
    const { run, spoken } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    run.onStep(pathStep(1, { ident: "w80308@4", gain: 0.3 }));
    expect(next().gain).toBe("Gain +<1 kit value");
    expect(spoken).toEqual(["Equip now is ready: 1 of 22 places filled. Next step: Get Fenwick Greaves +4, gain +<1."]);
    run.onStep(pathStep(2, { ident: "w80301@4", gain: 0.49 }));
    run.onStep(pathStep(3, { ident: "w80302@4", gain: 0.5 })); // the page rounds a half up
    expect(then().map((line) => line.gain)).toEqual(["Gain +<1 kit value", "Gain +1 kit value"]);
  });

  it("says that a step that was not found in time was not, with its label", async () => {
    const { run } = await started();
    run.onStep(equipStep());
    run.onStep(lostStep(1));
    expect(textOf("#upgrade-next")).toContain("Step 1: not found in time.");
    expect(next().what).toBeNull();
  });

  it("shows the label of a step that was found in the time allowed and not proven the best", async () => {
    const { run } = await started();
    run.onStep(equipStep());
    run.onStep(pathStep(1, { ident: "w80301@4", status: "time_limit", proven: false, label: "best found, not proven optimal" }));
    expect(next().label).toBe("(best found, not proven optimal)");
  });

  it("shows nothing of a Next step before the step comes", async () => {
    const { run } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    expect($("#upgrade-next").hidden).toBe(true);
  });
});

// ---- the spare copy ---------------------------------------------------------------------------------------------------------------------------------

describe("the spare copy", () => {
  /** The section owning a Quillmark Bracer (it arrives at +0) at each of the tiers in `owned`, and a step as its first: `worn` is the kit after it. */
  async function firstStep({ owned, worn, kind = "copy", sourceTier = null, cost = costOf(0, 4) }) {
    const t = mountAnswer({ pauseMs: 0 });
    for (const tier of owned) addByName("quillmark bracer", String(tier));
    await sent(t, 1);
    const run = t.engine.runs[0];
    run.onStep(equipStep({ kit: kitOf({ 8: "w80302@4" }) }));
    run.onStep(pathStep(1, { ident: "w80302@4", kind, sourceTier, cost, gain: 400, kit: kitOf(worn) }));
    return { t, run };
  }
  const TWO = { 8: "w80302@4", 9: "w80302@4" };

  it("offers to upgrade the spare copy instead when that costs fewer copies", async () => {
    await firstStep({ owned: [4, 2], worn: TWO });
    expect(next().cost).toBe("16 copies to reach +4");
    expect(next().hint).toBe("or upgrade your spare +2 copy (cheaper)");
  });

  it("counts the copy that is got itself: a spare at +0 of an item that arrives at +0 needs 15 copies, against 16 for another one, and is cheaper", async () => {
    await firstStep({ owned: [4, 0], worn: TWO });
    expect(next().cost).toBe("16 copies to reach +4"); // (what the line says is what the spare is compared with)
    expect(next().hint).toBe("or upgrade your spare +0 copy (cheaper)");
  });

  it("names the spare that is nearest the tier when there are several", async () => {
    await firstStep({ owned: [4, 0, 3, 1], worn: TWO });
    expect(next().hint).toBe("or upgrade your spare +3 copy (cheaper)");
  });

  it("offers nothing when the kit after the step wears the lower copy", async () => {
    await firstStep({ owned: [4, 2], worn: { 8: "w80302@4", 9: "w80302@2" } });
    expect(next().hint).toBeNull();
  });

  it("offers nothing when there is no lower copy", async () => {
    await firstStep({ owned: [4], worn: TWO });
    expect(next().hint).toBeNull();
  });

  it("offers nothing when the step is not a copy", async () => {
    await firstStep({ owned: [2, 0], worn: { 8: "w80302@4", 9: "w80302@0" }, kind: "upgrade", sourceTier: 2, cost: costOf(2, 4, 0) });
    expect(next().what).toBe("Upgrade your Quillmark Bracer +2 to +4");
    expect(next().hint).toBeNull();
  });

  it("offers nothing when the step has no cost to compare with", async () => {
    await firstStep({ owned: [4, 2], worn: TWO, cost: null });
    expect(next().hint).toBeNull();
  });

  it("says that it costs the same when upgrading the spare costs as many copies as getting another: a drop arrives at +4 under ready4, and both are one drop", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("tarn signet", "4");
    addByName("tarn signet", "2");
    await sent(t, 1);
    const run = t.engine.runs[0];
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4", 12: "w80301@2" }) }));
    run.onStep(pathStep(1, { ident: "w80301@4", kind: "copy", cost: costOf(4, 4), gain: 400, kit: kitOf({ 11: "w80301@4", 12: "w80301@4" }) }));
    expect(next().cost, "nothing to bring up: it arrives at the tier").toBeNull();
    expect(next().hint).toBe("or upgrade your spare +2 copy (the same cost)");
  });

  it("follows the steps before it: a copy an earlier step turned into the item is not a spare, and the hint is on the lines of Then as well", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("quillmark bracer", "2");
    addByName("quillmark bracer", "0");
    await sent(t, 1);
    const run = t.engine.runs[0];
    run.onStep(equipStep({ kit: kitOf({ 8: "w80302@2", 9: "w80302@0" }) }));
    run.onStep(pathStep(1, { ident: "w80302@4", kind: "upgrade", sourceTier: 2, cost: costOf(2, 4, 0), kit: kitOf({ 8: "w80302@4", 9: "w80302@0" }) }));
    expect(next().hint).toBeNull();
    run.onStep(pathStep(2, { ident: "w80302@4", kind: "copy", cost: costOf(0, 4), kit: kitOf({ 8: "w80302@4", 9: "w80302@4" }) }));
    expect(then()[0].hint).toBe("or upgrade your spare +0 copy (cheaper)"); // (the +2 copy is the +4 now; the +0 one needs 15 copies against 16)
  });

  it("offers a spare once: a lower copy that the line of an earlier step already offered is not offered again", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("quillmark bracer", "4");
    addByName("quillmark bracer", "2");
    await sent(t, 1);
    const run = t.engine.runs[0];
    run.onStep(equipStep({ kit: kitOf({ 8: "w80302@4", 9: "w80302@2" }) }));
    // another +4 displaces the +2, which is offered for the copy; a third +4 (the item fits three places in this test) leaves it idle still, but it was offered already
    run.onStep(pathStep(1, { ident: "w80302@4", kind: "copy", cost: costOf(0, 4), kit: kitOf({ 8: "w80302@4", 9: "w80302@4" }) }));
    expect(next().hint).toBe("or upgrade your spare +2 copy (cheaper)");
    run.onStep(pathStep(2, { ident: "w80302@4", kind: "copy", cost: costOf(0, 4), kit: kitOf({ 8: "w80302@4", 9: "w80302@4", 10: "w80302@4" }) }));
    expect(then()[0].hint, "the one spare cannot be the copy of both steps").toBeNull();
  });

  it("offers each of two spares once", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    addByName("quillmark bracer", "4");
    addByName("quillmark bracer", "2");
    addByName("quillmark bracer", "2");
    await sent(t, 1);
    const run = t.engine.runs[0];
    run.onStep(equipStep({ kit: kitOf({ 8: "w80302@4", 9: "w80302@2" }) }));
    run.onStep(pathStep(1, { ident: "w80302@4", kind: "copy", cost: costOf(0, 4), kit: kitOf({ 8: "w80302@4", 9: "w80302@4" }) }));
    run.onStep(pathStep(2, { ident: "w80302@4", kind: "copy", cost: costOf(0, 4), kit: kitOf({ 8: "w80302@4", 9: "w80302@4", 10: "w80302@4" }) }));
    run.onStep(pathStep(3, { ident: "w80302@4", kind: "copy", cost: costOf(0, 4), kit: kitOf({ 8: "w80302@4", 9: "w80302@4", 10: "w80302@4", 11: "w80302@4" }) }));
    expect([next().hint, then()[0].hint, then()[1].hint]).toEqual(["or upgrade your spare +2 copy (cheaper)", "or upgrade your spare +2 copy (cheaper)", null]);
  });
});

// ---- Then, and the end of the path -----------------------------------------------------------------------------------------------------------------

describe("Then", () => {
  it("shows the steps as they arrive, each on a line of its own in order: what, gain and cost, under the label of the path", async () => {
    const { run } = await started();
    run.onStep(equipStep());
    run.onStep(pathStep(1, { ident: "w80301@4", gain: 900 }));
    expect($("#upgrade-then").hidden, "nothing to show under Then yet").toBe(true);
    run.onStep(pathStep(2, { ident: "w80302@4", cost: costOf(0, 4), gain: 800 }));
    expect($("#upgrade-then").hidden).toBe(false);
    expect(textOf("#upgrade-then-h")).toBe("Then");
    expect(textOf("#upgrade-then-label")).toContain("Each step is the single best addition after the steps before it");
    expect(then()).toHaveLength(1);
    run.onStep(pathStep(3, { ident: "w80303@4", kind: "copy", cost: costOf(0, 4), gain: 700 }));
    run.onStep(pathStep(4, { ident: "w80308@4", kind: "upgrade", sourceTier: 1, cost: costOf(1, 4, 4), gain: 600 }));
    expect(then()).toMatchObject([
      { what: "Get Quillmark Bracer +4", gain: "Gain +800 kit value", cost: "16 copies to reach +4", source: null },
      { what: "Get another Ashen Gorget +4", gain: "Gain +700 kit value", cost: "16 copies to reach +4" },
      { what: "Upgrade your Fenwick Greaves +1 to +4", gain: "Gain +600 kit value", cost: "1 copy to reach +4" },
    ]);
    expect($("#upgrade-then-list").tagName).toBe("OL");
    expect($("#upgrade-then-list").getAttribute("start")).toBe("2");
  });

  it("takes the first press of Stop only: it is marked aria-disabled, a second press does nothing, and the focus stays where it is", async () => {
    const { engine } = await started();
    engine.autoStop = false; // the step that is being worked out goes on until it is done
    const stop = $("#upgrade-stop");
    expect(stop.hasAttribute("aria-disabled")).toBe(false);
    stop.focus();
    stop.click();
    expect(stop.getAttribute("aria-disabled")).toBe("true");
    stop.click();
    stop.click();
    expect(engine.log, "one stop for the press, and the one that goes before every request").toEqual(["stop", "run1", "stop"]);
    expect(document.activeElement).toBe(stop);
    expect(stop.disabled, "not disabled: a disabled button loses the focus").toBe(false);
    expect($("#upgrade-stop")).toBe(stop);
  });

  it("stops the path as soon as it is sent when Stop was pressed while the request waited for the one before it to end", async () => {
    const t = await started();
    t.engine.autoStop = false; // a long step: the first path does not end the moment it is told to
    addByName("corbel cap");
    await vi.waitFor(() => expect(t.engine.log).toEqual(["stop", "run1", "stop"])); // the second request told the first to stop, and waits for it
    $("#upgrade-stop").click(); // (Stop of the second request, which the client has not been given yet)
    expect(t.engine.log.slice(-1)).toEqual(["stop"]);
    t.run.finish(ended("stopped", 0)); // the first path ends
    await sent(t, 2);
    await flush();
    expect(t.engine.log, "the second request is stopped as soon as it is given").toEqual(["stop", "run1", "stop", "stop", "run2", "stop"]);
  });

  it("has a Stop button while the path runs, and Stop stops the path", async () => {
    const { run, engine } = await started();
    const stop = $("#upgrade-stop");
    expect(stop.textContent).toBe("Stop");
    expect(stop.type).toBe("button");
    const before = engine.log.length;
    stop.click();
    expect(engine.log.slice(before)).toEqual(["stop"]);
    run.onStep(equipStep()); // (a stop may land a step late: nothing is said of it)
    run.onStep(pathStep(1, { ident: "w80301@4" }));
    run.finish(ended("stopped", 1));
    await flush();
    expect($("#upgrade-stop")).toBeNull();
    expect(textOf("#upgrade-end")).toBe("Stopped.");
    expect(textOf("#upgrade-then")).not.toMatch(/late|landed|after the stop/i);
  });

  it("has no Stop button when nothing runs, one while a path runs and none when it has ended", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    expect($("#upgrade-stop")).toBeNull();
    addByName("tarn signet");
    await sent(t, 1);
    expect($("#upgrade-stop")).not.toBeNull();
    t.engine.runs[0].finish(ended("no-gain", 0));
    await flush();
    expect($("#upgrade-stop")).toBeNull();
  });

  it.each([
    ["limit", 8, "These are the first 8 steps."],
    ["no-gain", 3, "Nothing more you can add gains anything."],
    ["time", 3, "Stopped at the time limit: the next steps were not computed."],
    ["stopped", 3, "Stopped."],
  ])("says honestly why the path ended: %s", async (stopped, steps, words) => {
    const { run } = await started();
    run.onStep(equipStep());
    for (let index = 1; index <= steps; index += 1) run.onStep(pathStep(index, { ident: "w80301@4" }));
    expect(textOf("#upgrade-end")).toBe("");
    run.finish(ended(stopped, steps));
    await flush();
    expect(textOf("#upgrade-end")).toBe(words);
    expect($("#upgrade-stop"), "the path is over: no Stop").toBeNull();
    expect(textOf("#upgrade-progress")).toBe("");
  });

  it("says why a path ended that found nothing to add, under Then, with Equip now alone", async () => {
    const { run } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    run.finish(ended("no-gain", 0));
    await flush();
    expect($("#upgrade-next").hidden).toBe(true);
    expect($("#upgrade-then").hidden).toBe(false);
    expect(textOf("#upgrade-end")).toBe("Nothing more you can add gains anything.");
  });

  it("shows the label of a step that ran out of time with a kit, and says so for a step that was not found at all", async () => {
    const { run } = await started();
    run.onStep(equipStep());
    run.onStep(pathStep(1, { ident: "w80301@4" }));
    run.onStep(pathStep(2, { ident: "w80302@4", status: "time_limit", proven: false, label: "best found, not proven optimal" }));
    run.onStep(lostStep(3));
    const lines = then();
    expect(lines[0].label).toBe("(best found, not proven optimal)");
    expect(textOf("#upgrade-then-list li:nth-child(2)")).toBe("Step 3: not found in time.");
    run.finish(ended("time", 3));
    await flush();
    expect(textOf("#upgrade-end")).toBe("Stopped at the time limit: the next steps were not computed.");
  });

  it("says one quiet thing about the progress while the path runs: loading, Equip now, which step", async () => {
    const { run } = await started();
    expect(textOf("#upgrade-progress")).not.toBe("");
    const texts = [];
    for (const report of [
      { phase: "loading", stage: "loading", loaded: 10, total: 100 },
      { phase: "building", stage: "equip-now" },
      { phase: "solving", stage: "step", step: 1 },
      { phase: "solving", stage: "step", step: 4 },
    ]) {
      run.onProgress(report);
      texts.push(textOf("#upgrade-progress"));
    }
    expect(texts).toEqual(["Loading the data…", "Working out what to equip now…", "Working out step 1…", "Working out step 4…"]);
    run.onProgress({ phase: "compiling" }); // the optimizer starting: the client's own panel says so
    expect(textOf("#upgrade-progress")).toBe("Working out step 4…");
    expect($("#upgrade-progress").hasAttribute("role") || $("#upgrade-progress").hasAttribute("aria-live")).toBe(false);
  });
});

// ---- faults -----------------------------------------------------------------------------------------------------------------------------------------

describe("faults", () => {
  const failure = (code, message) => Object.assign(new Error(message), { code });

  it("keeps the steps already shown, says that the rest could not be computed, says what happened, and offers Try again", async () => {
    const { run, engine } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    run.onStep(pathStep(1, { ident: "w80308@4", gain: 50 }));
    run.onStep(pathStep(2, { ident: "w80302@4", gain: 40 }));
    run.fail(failure("worker-failed", "The optimizer stopped working."));
    await flush();
    expect(equipRows()).toHaveLength(22);
    expect(next().what).toBe("Get Fenwick Greaves +4");
    expect(then()).toHaveLength(1);
    expect(textOf("#upgrade-end")).toBe("The rest could not be computed.");
    expect(faultText()).toBe("Couldn't work out your answer. The optimizer stopped working.");
    expect(buttonsOf("#upgrade-fault")).toEqual(["Try again"]);
    expect($("#upgrade-stop")).toBeNull();
    expect(engine.runs).toHaveLength(1);
  });

  it("says nothing of a rest when nothing was shown", async () => {
    const { run } = await started();
    run.fail(failure("engine-load", "The optimizer's data file could not be loaded (404)."));
    await flush();
    expect(textOf("#upgrade-end")).toBe("");
    expect(faultText()).toBe("Couldn't work out your answer. The optimizer's data file could not be loaded (404).");
    expect(buttonsOf("#upgrade-fault")).toEqual(["Try again"]);
  });

  it("asks again with Try again, and the focus goes with it: from the button to Stop, back to the new button if it fails again, to the answer when the path ends", async () => {
    const { run, engine } = await started();
    run.fail(failure("worker-failed", "The optimizer stopped working."));
    await flush();
    const button = $("#upgrade-fault button");
    button.focus();
    button.click();
    await sent({ engine }, 2);
    expect(engine.log.slice(-2)).toEqual(["stop", "run2"]);
    expect(engine.runs[1].request).toEqual(run.request);
    expect($("#upgrade-fault").hidden, "the line is gone while the answer is awaited").toBe(true);
    expect(document.activeElement, "the button is gone, and the focus is on what takes its place").toBe($("#upgrade-stop"));
    engine.runs[1].fail(failure("worker-failed", "The optimizer stopped working.")); // and a second fault
    await flush();
    expect(document.activeElement).toBe($("#upgrade-fault button"));
    $("#upgrade-fault button").click();
    await sent({ engine }, 3);
    engine.runs[2].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    expect(document.activeElement, "the focus does not move while the answer streams").toBe($("#upgrade-stop"));
    engine.runs[2].finish(ended("no-gain", 0));
    await flush();
    expect(document.activeElement, "Stop goes with the end of the path, and the focus is on the answer").toBe($("#upgrade-then-h"));
  });

  it("does not move the focus of a visitor who has gone on elsewhere when the fault line goes", async () => {
    const { run, engine } = await started();
    run.fail(failure("worker-failed", "The optimizer stopped working."));
    await flush();
    addByName("corbel cap");
    await sent({ engine }, 2);
    $("#upgrade-pick").focus();
    engine.runs[1].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    expect(document.activeElement.id).toBe("upgrade-pick");
  });

  it("says that a request the optimizer refused was refused, in the optimizer's words", async () => {
    const { run } = await started();
    run.fail(failure("bad-request", "the owned set is too long"));
    await flush();
    expect(faultText()).toBe("The optimizer would not take your gear list: the owned set is too long.");
    expect(buttonsOf("#upgrade-fault")).toEqual(["Try again"]);
  });

  it("says that the data was updated, with Reload, and tells the page, when the site was released again (the optimizer says so)", async () => {
    const t = await started();
    t.engine.updated = true;
    t.run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.run.fail(failure("engine-load", UPDATED_TEXT));
    await flush();
    expect(faultText()).toBe("Data updated, reload the page to see this section.");
    expect(buttonsOf("#upgrade-fault")).toEqual(["Reload"]);
    expect(t.onUpdated).toHaveBeenCalledTimes(1);
    $("#upgrade-fault button").click();
    expect(t.reload).toHaveBeenCalledTimes(1);
    expect(textOf("#upgrade-end")).toBe("The rest could not be computed.");
  });

  it("offers to load the optimizer when the visitor did not want it, and sends the request again if they now do", async () => {
    const { run, engine } = await started();
    run.fail(failure("declined", "The optimizer was not loaded: the visitor chose to keep the precomputed answers."));
    await flush();
    expect(faultText()).toBe("The optimizer was not loaded, so there is no answer for your gear yet.");
    expect(buttonsOf("#upgrade-fault")).toEqual(["Load the optimizer"]);
    $("#upgrade-fault button").click();
    await sent({ engine }, 2);
    expect(engine.client.askConsent).toHaveBeenCalledTimes(1);
    expect(engine.runs[1].request).toEqual(run.request);
  });

  it("says a fixed sentence when the optimizer sent something it should not have, not the protocol's own detail", async () => {
    const { run } = await started();
    run.fail(failure("protocol", "the steps of the path are not in order"));
    await flush();
    expect(faultText()).toBe("Couldn't work out your answer. The optimizer sent something that was not expected, so it was stopped.");
    expect(textOf("#upgrade-fault")).not.toContain("not in order");
    expect(buttonsOf("#upgrade-fault")).toEqual(["Try again"]);
  });

  it("says that the request was cancelled, not that the optimizer was not loaded, when the optimizer was ready (Cancel on its panel after it had started)", async () => {
    const { run, engine } = await started();
    engine.consent = "granted";
    run.fail(Object.assign(failure("cancelled", "The request was cancelled."), { byVisitor: true })); // (the client marks the error of the Cancel button of its panel: nobody asks again for that)
    await flush();
    expect(faultText()).toBe("Couldn't work out your answer. The request was cancelled.");
    expect(buttonsOf("#upgrade-fault")).toEqual(["Try again"]);
    expect(engine.runs, "the visitor asked for the end of it: it is not sent again").toHaveLength(1);
  });

  it.each(["declined", "unknown"])("says that the optimizer was not loaded for a request cancelled when the visitor had not agreed to it (%s)", async (state) => {
    const { run, engine } = await started();
    engine.consent = state;
    run.fail(failure("cancelled", "The request was cancelled."));
    await flush();
    expect(faultText()).toBe("The optimizer was not loaded, so there is no answer for your gear yet.");
    expect(buttonsOf("#upgrade-fault")).toEqual(["Load the optimizer"]);
  });

  it("does not send the request again if the visitor says no once more", async () => {
    const { run, engine } = await started();
    engine.client.askConsent.mockResolvedValue(false);
    engine.consent = "declined"; // (Cancel on the panel while the optimizer loads takes the visitor's yes back)
    run.fail(failure("cancelled", "The request was cancelled."));
    await flush();
    expect(buttonsOf("#upgrade-fault")).toEqual(["Load the optimizer"]);
    $("#upgrade-fault button").click();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(engine.client.askConsent).toHaveBeenCalledTimes(1);
    expect(engine.runs).toHaveLength(1);
    expect(buttonsOf("#upgrade-fault")).toEqual(["Load the optimizer"]);
  });

  it("says that the code of the optimizer could not be loaded, with Reload (a browser keeps a failed module until the page is reloaded), and tries again for the next change", async () => {
    const engine = fakeEngine();
    let attempts = 0;
    const real = engine.loadEngine;
    engine.loadEngine = async (url) => {
      attempts += 1;
      if (attempts === 1) throw new TypeError("Failed to fetch dynamically imported module");
      return real(url);
    };
    const t = mountAnswer({ pauseMs: 0, engine });
    addByName("tarn signet");
    await vi.waitFor(() => expect(faultText()).toBe("Couldn't load the optimizer. Reload the page to try again."));
    expect(buttonsOf("#upgrade-fault")).toEqual(["Reload"]);
    $("#upgrade-fault button").click();
    expect(t.reload).toHaveBeenCalledTimes(1);
    addByName("corbel cap");
    await sent(t, 1);
    expect(attempts).toBe(2);
  });

  it("says plainly that this browser cannot run the optimizer, without an offer to try again", async () => {
    const { run } = await started();
    run.fail(failure("unsupported", "This browser cannot run the optimizer."));
    await flush();
    expect(faultText()).toBe("Couldn't work out your answer. This browser cannot run the optimizer.");
    expect($$("#upgrade-fault button")).toHaveLength(0);
  });

  it("is a fault with Try again when the client cannot even take the request, and says something went wrong when it says nothing", async () => {
    const engine = fakeEngine();
    engine.client.runScenario = () => {
      throw new Error("");
    };
    const t = mountAnswer({ pauseMs: 0, engine });
    addByName("tarn signet");
    await vi.waitFor(() => expect(faultText()).toBe("Couldn't work out your answer. Something went wrong."));
    expect(buttonsOf("#upgrade-fault")).toEqual(["Try again"]);
    expect(t.engine.runs).toEqual([]);
  });

  it("is a plain line: it has no role and no live region of its own", async () => {
    const { run } = await started();
    run.fail(failure("worker-failed", "The optimizer stopped working."));
    await flush();
    expect($$("#upgrade-results [role], #upgrade-results [aria-live]")).toHaveLength(0);
  });
});

// ---- what a visitor who cannot see the page is told -----------------------------------------------------------------------------------------------------

describe("the voice", () => {
  it("says it once when Equip now and the Next step are there, and once more when the path ends: not for each step", async () => {
    const { run, spoken } = await started();
    run.onStep(equipStep({ kit: kitOf({ 0: "w80304@4", 11: "w80301@4", 4: "w80303@4" }) }));
    expect(spoken, "(the Next step is part of the same answer)").toEqual([]);
    run.onStep(pathStep(1, { ident: "w80308@4", gain: 1234 }));
    expect(spoken).toEqual(["Equip now is ready: 3 of 22 places filled. Next step: Get Fenwick Greaves +4, gain +1,234."]);
    for (let index = 2; index <= 5; index += 1) run.onStep(pathStep(index, { ident: "w80301@4" }));
    expect(spoken).toHaveLength(1);
    run.finish(ended("limit", 5));
    await flush();
    expect(spoken).toEqual(["Equip now is ready: 3 of 22 places filled. Next step: Get Fenwick Greaves +4, gain +1,234.", "5 steps."]);
  });

  it("says the upgrade in the words of the step, and the singular", async () => {
    const { run, spoken } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    run.onStep(pathStep(1, { ident: "w80301@4", kind: "upgrade", sourceTier: 2, cost: costOf(2, 4, 4), gain: 70 }));
    run.finish(ended("no-gain", 1));
    await flush();
    expect(spoken).toEqual(["Equip now is ready: 1 of 22 places filled. Next step: Upgrade your Tarn Signet +2 to +4, gain +70.", "1 step."]);
  });

  it("says Equip now with the end when the path ended before there was a next step", async () => {
    const { run, spoken } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    run.finish(ended("no-gain", 0));
    await flush();
    expect(spoken).toEqual(["Equip now is ready: 1 of 22 places filled. Nothing more you can add gains anything."]);
  });

  it("says that a next step was not found in time", async () => {
    const { run, spoken } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    run.onStep(lostStep(1));
    expect(spoken).toEqual(["Equip now is ready: 1 of 22 places filled. Next step: not found in time."]);
  });

  it("uses the live region of the page when it is given no function of its own", async () => {
    const t = mountAnswer({ pauseMs: 0, announce: false });
    addByName("tarn signet");
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    t.engine.runs[0].finish(ended("no-gain", 0));
    await flush();
    expect(textOf("#announce")).toBe("Equip now is ready: 1 of 22 places filled. Nothing more you can add gains anything.");
  });

  it("says that a fault happened in one breath with Equip now when that was not said yet, and does not say Equip now twice", async () => {
    const { run, spoken } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    run.fail(Object.assign(new Error("The optimizer stopped working."), { code: "worker-failed" }));
    await flush();
    expect(spoken).toEqual(["Equip now is ready: 1 of 22 places filled. Couldn't work out your answer. The optimizer stopped working. The rest could not be computed."]);
  });

  it("does not move the focus while the steps stream, or when the path ends if it was elsewhere", async () => {
    const { run } = await started();
    $("#upgrade-pick").focus();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    for (let index = 1; index <= 4; index += 1) {
      run.onStep(pathStep(index, { ident: "w80301@4" }));
      expect(document.activeElement.id).toBe("upgrade-pick");
    }
    run.finish(ended("limit", 4));
    await flush();
    expect(document.activeElement.id).toBe("upgrade-pick");
  });

  it("keeps the focus on Stop while the steps stream, and puts it on Then when Stop goes with the end of the path", async () => {
    const { run } = await started();
    run.onStep(equipStep());
    run.onStep(pathStep(1, { ident: "w80301@4" }));
    $("#upgrade-stop").focus();
    run.onStep(pathStep(2, { ident: "w80302@4" }));
    run.onStep(pathStep(3, { ident: "w80303@4" }));
    expect(document.activeElement).toBe($("#upgrade-stop"));
    run.finish(ended("no-gain", 3));
    await flush();
    expect(document.activeElement).toBe($("#upgrade-then-h"));
  });

  it("puts nothing in the section that is a live region, with the results shown", async () => {
    const { run } = await started();
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    run.onStep(pathStep(1, { ident: "w80301@4" }));
    run.onStep(pathStep(2, { ident: "w80302@4" }));
    expect($$('#upgrade [role="status"], #upgrade [role="alert"], #upgrade [role="log"], #upgrade [aria-live]')).toHaveLength(0);
  });
});

// ---- what is put in the page ----------------------------------------------------------------------------------------------------------------------

describe("what the answer puts in the page", () => {
  it("makes everything of text: a name that looks like markup is shown as it is", async () => {
    const hostile = [
      { id: 80401, name: "<img src=x onerror=alert(1)>", slots: ["FINGER"], stats: { STR: 5 }, weight10: 10, tier_rule: "drop", evidence: { level: "strict" }, source: { drops: ["<b>Zone</b>"] } },
    ];
    const { tableOf } = await import("./upgrade-helpers.mjs");
    const t = mountAnswer({ pauseMs: 0, items: tableOf(hostile) });
    addByName("img", "4");
    await sent(t, 1);
    t.engine.runs[0].onStep(equipStep({ kit: kitOf({ 11: "w80401@4" }) }));
    t.engine.runs[0].onStep(pathStep(1, { ident: "w80401@4", kind: "copy", cost: costOf(4, 4) }));
    expect(equipRows()[11].item).toBe("<img src=x onerror=alert(1)> +4");
    expect(next().source).toBe("Source: <b>Zone</b>");
    expect($$("#upgrade-results img, #upgrade-results b, #upgrade-results script")).toHaveLength(0);
  });

  it("puts the line with Stop and the progress before Equip now, so that no row of the answer pushes it down while the steps arrive", async () => {
    const { run } = await started();
    expect([...$("#upgrade-results").children].map((node) => node.id || node.className)).toEqual(["engine-slot", "path-bar", "upgrade-fault", "upgrade-equip", "upgrade-next", "upgrade-then", "upgrade-more"]);
    run.onStep(equipStep({ kit: kitOf({ 11: "w80301@4" }) }));
    expect($("#upgrade-stop").compareDocumentPosition($("#upgrade-equip")) & Node.DOCUMENT_POSITION_FOLLOWING, "Equip now is below Stop").toBeTruthy();
    expect($("#upgrade-progress").compareDocumentPosition($("#upgrade-then")) & Node.DOCUMENT_POSITION_FOLLOWING, "and so is Then, where the steps are added").toBeTruthy();
    expect($("#upgrade-fault").compareDocumentPosition($("#upgrade-equip")) & Node.DOCUMENT_POSITION_FOLLOWING, "a fault is said above the answer too").toBeTruthy();
  });

  it("keeps the place for the optimizer's question first in the results area, and ahead of the answer", async () => {
    const t = mountAnswer({ pauseMs: 0 });
    const results = $("#upgrade-results");
    expect(results.firstElementChild.classList.contains("engine-slot")).toBe(true);
    expect(t.root.contains(results)).toBe(true);
    expect(results.previousElementSibling.id, "below the owned list").toBe("upgrade-owned");
  });
});

// ---- the source -----------------------------------------------------------------------------------------------------------------------------------

describe("the code of the answer", () => {
  const source = readFileSync(resolve(STATIC, "ui/upgrade-answer.js"), "utf8");

  it("has no way to turn text into markup, a pattern or an address, stores nothing, and uses nothing that Safari 15 lacks", () => {
    const forbidden = [
      /\bRegExp\b/, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|createContextualFragment|DOMParser|srcdoc/, /\beval\s*\(|new\s+Function|setTimeout\(\s*["'`]/,
      /localStorage|sessionStorage|indexedDB|document\.cookie|navigator\.sendBeacon|XMLHttpRequest|WebSocket/,
      /createObjectURL|new\s+Blob|FileReader|window\.open|\.href\s*=|location\.(?:assign|replace)|\bsetAttribute\(\s*["'](?:href|src|on)/,
      /Object\.hasOwn\b|\.at\(|\bfindLast\b|structuredClone|toSorted|toReversed|\.with\(/,
    ];
    for (const pattern of forbidden) expect(source, String(pattern)).not.toMatch(pattern);
  });

  it("does not import the modules the page script imports, which would make the build load a shared chunk with the page: the words come in from the page code", () => {
    expect(source).not.toMatch(/from\s+["']\.\.\/format\.js["']/);
    expect(source).not.toMatch(/from\s+["']\.\.\/engine\/client\.js["']/); // (the client is the page's one, loaded from the manifest's address)
    expect(source).not.toMatch(/from\s+["']\.\.\/trio\.js["']/);
  });
});
