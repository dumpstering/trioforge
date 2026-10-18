// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://trioforge.test/trio/pal-mnk-ber/"}
//
// A random walk over the trio page with the sliders and the buff choices, against the stand-in for the optimizer's client that the tests drive: the visitor moves sliders, changes the
// evidence level and the buffs, the views the page loads come slowly or not at all, the answers come in any order, a request is cancelled, refused or declined, Stop, Try again and
// Back are pressed, the question is answered. One rule is looked at, the one the page is built to keep: an answer is drawn only when it was worked out for the view that the page shows
// (race, role, tier, weapons, evidence, buffs and sliders alike) and for what the visitor's controls say, and no other view is loading (the rule is looked at the moment `drawSolved`
// draws, and again after every step, for the answer that stands on the page). The walks are seeded, so a walk that breaks the rule can be run again. They are held to the rule by taking a
// guard of the page away: without the `applying` check of `drawSolved` 11 of 300 walks fail, and without `wanted === one` in the chunk's `live()` 149 of 300 do.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { initTrio } from "../pipeline/trioforge/site/static/trio.js";
import * as weightsChunk from "../pipeline/trioforge/site/static/ui/weights.js";
import { makeSite, siteFetch } from "./engine-site-fixture.mjs";
import { REFERENCE } from "./best-kit-harness.mjs";
import { $, mountPage } from "./upgrade-helpers.mjs";
import { fakeEngine } from "./upgrade-answer-helpers.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const shardFile = (name) => JSON.parse(readFileSync(resolve(ROOT, `fixtures/site/contract/data/${name}.json`), "utf8"));
const encode = (value) => new TextEncoder().encode(JSON.stringify(value));
const [AC2] = REFERENCE.cases;
const POSITIONS = ["h", "1", "2"];

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

/** A small deterministic generator (mulberry32). */
function generator(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const turns = async (count) => {
  for (let round = 0; round < count; round += 1) await new Promise((done) => setImmediate(done));
};

/** Let the promises and the few real tasks the page waits on (the checksum of a file) run, with the fake clock where it is. */
async function settleAll(w) {
  for (let round = 0; round < 6; round += 1) {
    await vi.advanceTimersByTimeAsync(0);
    await turns(1);
  }
  if (w.held.length === 0) await Promise.race([w.app.whenIdle(), turns(60)]); // (what the page loads, the item list of an answer among it; a view that is held would keep it waiting)
}

function walk(seed, steps) {
  const random = generator(seed);
  const pick = (list) => list[Math.floor(random() * list.length)];
  const engine = fakeEngine();
  engine.serial = random() < 0.5;
  const site = makeSite();
  site.files.set("/engine-manifest.json", encode(site.manifestJson));
  const net = siteFetch(site);
  mountPage();
  window.history.replaceState(null, "", "/trio/pal-mnk-ber/");
  engine.consent = random() < 0.3 ? "unknown" : "granted";
  /** The loads of views the walk holds back: each is {name, settle(ok)}. */
  const held = [];
  const slow = random() < 0.4;
  const fetchImpl = async (url, init) => {
    const path = new URL(String(url), "https://trioforge.test").pathname;
    const view = /^\/data\/pal-mnk-ber\/(.+)\.json$/.exec(path);
    if (view === null) return net.fetchImpl(url, init);
    if (slow && random() < 0.6) {
      await new Promise((release, reject) => held.push({ name: view[1], ok: () => release(), fail: () => reject(new TypeError("Failed to fetch")) }));
    }
    return { ok: true, status: 200, json: async () => structuredClone(shardFile(view[1])) };
  };
  const app = initTrio({ document, window, fetch: fetchImpl, reload: vi.fn(), loadEngine: engine.loadEngine, loadWeights: () => Promise.resolve(weightsChunk) });
  const seen = []; // what the walk did, for the message of a failure
  const violations = [];
  /** The rule at the moment an answer is drawn: it was asked for the view the page shows and for what the visitor's controls say, and no other view is loading. */
  const original = app.drawSolved.bind(app);
  app.drawSolved = (answer) => {
    const drew = original(answer);
    if (drew) {
      tally.drawn += 1;
      const asked = engine.runs[answer.value - 1000].request;
      const shown = app.displayed;
      const controls = app.desired(app.wantedSetup);
      const mismatch = [];
      const same = (what, got, want) => {
        if (JSON.stringify(got) !== JSON.stringify(want)) mismatch.push(`${what}: asked ${JSON.stringify(got)}, shown ${JSON.stringify(want)}`);
      };
      same("scenario", asked.scenario, { race: shown.race, role: shown.role, buffs: shown.buffs, evidence: shown.ev, setup: shown.setup });
      same("tier", asked.tier, shown.tier);
      same("weights", asked.weights ?? null, app.weightsTable(shown.weights));
      same("controls", [asked.scenario.race, asked.scenario.role, asked.tier, asked.scenario.evidence, asked.scenario.buffs, asked.weights ?? null], [controls.race, controls.role, controls.tier, controls.ev, controls.buffs, app.weightsTable(controls.weights)]);
      if (app.applying !== 0) mismatch.push("another view is loading");
      if (mismatch.length > 0) violations.push(`drawn at once: ${mismatch.join("; ")}`);
    }
    return drew;
  };
  const choose = (selector) => {
    const input = $(selector);
    if (input === null || input.disabled) return false;
    input.checked = true;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  };
  const sliderControl = (index, position) => `#w-${index}-${position}`;
  const result = (index) => ({ kind: "scenario", mode: "best-kit", status: "optimal", proven: true, label: null, F: `f${index}`, value: 1000 + index, kit: [...AC2.kit], buffs: [...AC2.buffs], hasteAssumed: AC2.hasteAssumed, elapsedMs: 1 });
  const bestKits = () => engine.runs.filter((run) => run.request.mode === "best-kit");
  const open = () => bestKits().filter((run) => !run.settled);
  const events = [
    ["slider", () => (app.weights === null ? false : choose(sliderControl(Math.floor(random() * 5), pick(POSITIONS))))],
    ["open the weights", () => {
      const details = $("#assume-weights");
      if (details.open) return false;
      details.open = true;
      details.dispatchEvent(new Event("toggle"));
      return true;
    }],
    ["evidence", () => choose(pick(["#ev-wiki", "#ev-strict"]))],
    ["buffs", () => choose(pick(["#buffs-own", "#buffs-group", "#buffs-raid"]))],
    ["tier", () => {
      const select = $("#sw-tier");
      select.value = pick(["0", "4", "10"]);
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }],
    ["enchanter", () => {
      const box = $("#buffs-ench");
      if (box.disabled) return false;
      box.checked = !box.checked;
      box.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }],
    ["an answer", () => {
      const run = pick(open().filter((one) => one.sent));
      if (run === undefined) return false;
      run.finish(result(engine.runs.indexOf(run)));
      return true;
    }],
    ["a fault", () => {
      const run = pick(open());
      if (run === undefined) return false;
      const kind = pick(["cancelled", "visitor", "bad-request", "protocol"]);
      run.fail(Object.assign(new Error(`a ${kind} fault`), kind === "visitor" ? { code: "cancelled", byVisitor: true } : { code: kind }));
      return true;
    }],
    ["a cancel of the page", () => {
      engine.client.cancel();
      return true;
    }],
    ["the question: yes", () => {
      if (engine.consent !== "unknown") return false;
      engine.agree();
      return true;
    }],
    ["the question: no", () => {
      if (engine.consent !== "unknown") return false;
      engine.consent = "declined";
      for (const run of engine.runs.filter((one) => !one.settled)) run.fail(Object.assign(new Error("declined"), { code: "declined" }));
      return true;
    }],
    ["a view arrives", () => {
      const load = held.shift();
      if (load === undefined) return false;
      load.ok();
      return true;
    }],
    ["a view does not arrive", () => {
      const load = held.shift();
      if (load === undefined) return false;
      load.fail();
      return true;
    }],
    ["the button of the answer area", () => {
      const button = $("#solve button");
      if (button === null || button.hidden) return false;
      button.click();
      return true;
    }],
    ["time", () => {
      vi.advanceTimersByTime(pick([50, 120, 310, 700]));
      return true;
    }],
  ];
  const weighted = [];
  for (const event of events) {
    const times = { "an answer": 6, time: 6, slider: 6, "the button of the answer area": 2, "a view arrives": 2, "open the weights": 0 }[event[0]] ?? 1;
    for (let copy = 0; copy < times; copy += 1) weighted.push(event);
  }
  const check = () => {
    expect(violations, `${seen.join(", ")}`).toEqual([]);
    if (!$("#main").classList.contains("solved")) return;
    tally.draws += 1;
    const said = /Exact value \(F\): f(\d+)\./.exec(text("#solve .solve-text"));
    expect(said, `an answer is on the page, and the line names it (${seen.join(", ")})`).not.toBeNull();
    const run = engine.runs[Number(said[1])];
    const shown = app.displayed;
    const asked = run.request;
    const context = `${seen.join(", ")}; the answer was asked for ${JSON.stringify([asked.scenario, asked.tier, asked.weights ?? null])}, the page shows ${JSON.stringify([shown.race, shown.role, shown.buffs, shown.ev, shown.setup, shown.tier, shown.weights])}`;
    expect(asked.scenario, context).toEqual({ race: shown.race, role: shown.role, buffs: shown.buffs, evidence: shown.ev, setup: shown.setup });
    expect(asked.tier, context).toBe(shown.tier);
    expect(asked.weights ?? null, context).toEqual(app.weightsTable(shown.weights));
  };
  return { app, engine, events: weighted, seen, held, random, pick, check, steps, act: (fn) => fn() };
}

/** How many times, over all the walks, the rule had an answer to look at: a walk that never drew one would keep it for nothing. */
const tally = { draws: 0, drawn: 0, walks: 0 };

const text = (selector) => ($(selector)?.textContent ?? "").replace(/\s+/g, " ").trim();

describe("a random walk over the page", () => {
  const SEEDS = Array.from({ length: 60 }, (_, index) => index + 1);
  it.each(SEEDS)("never says that an answer is for the settings when it was worked out for others (seed %i)", async (seed) => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    const w = walk(seed, 40);
    await settleAll(w);
    // the sliders are there from the start (the walk opens the Weights assumption), and the page begins on a view that no shard answers
    const details = $("#assume-weights");
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    await settleAll(w);
    w.act(() => {
      $("#w-0-2").checked = true;
      $("#w-0-2").dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    });
    await settleAll(w);
    for (let step = 0; step < w.steps; step += 1) {
      const [name, act] = w.pick(w.events);
      const did = act();
      if (did !== false) w.seen.push(name);
      await settleAll(w);
      w.check();
    }
    // whatever the walk left held is let go, and the page ends in a state that obeys the rule too
    while (w.held.length > 0) w.held.shift().ok();
    await vi.advanceTimersByTimeAsync(2000);
    await settleAll(w);
    w.check();
    tally.walks += 1;
  }, 60_000);

  it("looked at answers on the page, in the walks above", () => {
    console.log("TALLY", JSON.stringify(tally));
    expect(tally.walks).toBe(SEEDS.length);
    expect(tally.drawn, "the walks drew answers for the rule to be held to").toBeGreaterThan(10);
  });
});
