// Shared by the tests of the answer of the Upgrade section (not a test file): a stand-in for the optimizer's client that the test drives step by step, the messages it
// hands to the page (the shapes protocol.js documents), and the section mounted on the item table of a test. Every name here is invented (pipeline/tests/test_site_fixture_items.py
// fails when a real item's key or name is in this file).

import { vi } from "vitest";
import { createUpgradeAnswer } from "../pipeline/trioforge/site/static/ui/upgrade-answer.js";
import { createGearInput } from "../pipeline/trioforge/site/static/ui/upgrade-input.js";
import { EMPTY_NAME, arrivalText, displayInt, fmtInt, fmtSigned, reachText, tierLabel } from "../pipeline/trioforge/site/static/format.js";
import { $, mountPage, press, record, tableOf, type, wake } from "./upgrade-helpers.mjs";

export const TRIO = ["PAL", "MNK", "BER"];
export const CLIENT_PATH = "/assets/engine/client-AAAAAAAA.js";
export const CLIENT_URL = `https://trioforge.test${CLIENT_PATH}`;
export const VIEW = Object.freeze({ race: "HUM", role: "balanced", buffs: "own", evidence: "wiki", setup: "dw" });
export const UPDATED_TEXT = "The optimizer was updated. Reload the page to use it.";

/** The words the page code (trio.js) hands to the code of the section: the ones format.js has (the words for an arrival tier too), and the name of a place of the kit as the page's kit table writes it. */
export const words = () => ({
  tierLabel,
  arrivalText,
  reachText,
  fmtInt,
  fmtSigned,
  displayInt,
  emptyName: EMPTY_NAME,
  slotLabel: (index) => document.querySelectorAll("#kit-body tr th")[index]?.textContent ?? "",
});

// ---- the items of the tests -------------------------------------------------------------------------------------------------------------------------

/** A drop arrives at +4 at best; a quest reward, a crafted or a bought item at +0. Each has the source the item table gives (or none). */
export const ITEMS = [
  record(80301, "Tarn Signet", { slots: ["FINGER"], source: { drops: ["The Hole"] } }),
  record(80302, "Quillmark Bracer", { slots: ["WRIST"], tier_rule: "fixed0", source: { sold: ["Freeport"] } }),
  record(80303, "Ashen Gorget", { slots: ["NECK"], tier_rule: "fixed0", source: { quests: ["Lake Rathetear quest"] } }),
  record(80304, "Dunmere Helm", { slots: ["HEAD"], source: { drops: ["Plane of Fear", "Befallen", "Lower Guk"], more: { drops: 2 } } }),
  record(80305, "Corbel Cap", { slots: ["HEAD"], tier_rule: "fixed0", source: { crafted: 1 } }),
  record(80306, "Reedwater Anklet", { slots: ["FEET"], tier_rule: "fixed0", source: { forage: ["Kithicor Forest"] } }),
  record(80307, "Sedge-woven Mantle", { slots: ["BACK"], tier_rule: "fixed0" }),
  record(80308, "Fenwick Greaves", { slots: ["LEGS"], source: { drops: ["Plane of Hate"] } }),
];
export const table = () => tableOf(ITEMS);

// ---- the optimizer's client ---------------------------------------------------------------------------------------------------------------------------

/**
 * A stand-in for the client of the optimizer. `runs` are the requests it was given, each with the callbacks and the means to end it (`finish(result)`, `fail(error)`); `log` is
 * what was done to it, in order ("stop", "run1", "cancel", "withdraw" ...); `loaded` the addresses its module was asked for; `options` what `getEngineClient` was called with.
 *
 * It behaves as the client does where the page relies on it: `stop()` ends every farm path that is not over (each resolves, "stopped", a moment later: set `autoStop` to false for a
 * test that holds a request open, as a long step does), `cancel()` fails every request that is not over at once (code "cancelled"), `consentState()` says what the visitor has
 * agreed to (`consent`: "granted" unless a test says "unknown", when the question is still to be answered, or "declined"). A request made with a `signal` is withdrawn alone when the signal
 * fires ("withdraw" in the log; the request fails with the code "cancelled", and `withdrawn` is set on it). `onSent` is called when the worker has the request: at once, unless the question is
 * still to be answered (a request waits for the yes: `agree()` gives it, and sends what waited), and a request that reports a step or its progress has been sent. With `serial` set
 * the stand-in works one request at a time, as the client does: a request is sent when every one before it is over.
 */
export function fakeEngine() {
  const runs = [];
  const log = [];
  const loaded = [];
  const engine = { runs, log, loaded, options: [], updated: false, consent: "granted", autoStop: true, serial: false };
  /** Whether a request may be sent now: the question is answered, and (when the stand-in is serial) nothing before it is still on. */
  const mayBeSent = (run) => engine.consent !== "unknown" && (!engine.serial || runs.every((other) => other === run || other.settled || runs.indexOf(other) > runs.indexOf(run)));
  /** Send what waited and may be sent now (one request, when the stand-in is serial: the first that waits). */
  const sendWaiting = () => {
    for (const run of runs) {
      if (run.settled || run.sent || !mayBeSent(run)) continue;
      run.send();
      if (engine.serial) break;
    }
  };
  engine.agree = () => {
    engine.consent = "granted";
    sendWaiting();
  };
  engine.client = {
    runScenario(request, callbacks = {}) {
      return new Promise((resolve, reject) => {
        const cancelled = () => Object.assign(new Error("The request was withdrawn."), { code: "cancelled" });
        if (callbacks.signal?.aborted) {
          reject(cancelled());
          return;
        }
        const run = { request, ...callbacks, delivered: 0, settled: false, sent: false, withdrawn: false };
        run.finish = (result) => {
          run.settled = true;
          resolve(result);
          queueMicrotask(sendWaiting);
        };
        run.fail = (error) => {
          run.settled = true;
          reject(error);
          queueMicrotask(sendWaiting);
        };
        run.send = () => {
          if (run.sent) return;
          run.sent = true;
          callbacks.onSent?.();
        };
        if (callbacks.onStep) {
          run.onStep = (step) => {
            run.send();
            if (step.index > 0) run.delivered += 1;
            callbacks.onStep(step);
          };
        }
        if (callbacks.onProgress) {
          run.onProgress = (report) => {
            run.send();
            callbacks.onProgress(report);
          };
        }
        if (callbacks.signal) {
          callbacks.signal.addEventListener(
            "abort",
            () => {
              if (run.settled) return;
              log.push("withdraw");
              run.withdrawn = true;
              run.fail(cancelled());
            },
            { once: true },
          );
        }
        runs.push(run);
        log.push(`run${runs.length}`);
        if (mayBeSent(run)) run.send();
      });
    },
    stop() {
      log.push("stop");
      if (!engine.autoStop) return;
      // (only a farm path is stopped, as the client does: a best sets or an Every slot request is not a path, and goes on to its end)
      for (const run of runs) if (!run.settled && run.request.mode === "farm-path") queueMicrotask(() => run.settled || run.finish({ kind: "scenario", mode: "farm-path", stopped: "stopped", steps: run.delivered, hasteAssumed: 30, elapsedMs: 1 }));
    },
    cancel() {
      log.push("cancel");
      for (const run of runs) if (!run.settled) run.fail(Object.assign(new Error("The request was cancelled."), { code: "cancelled" }));
    },
    consentState: () => engine.consent,
    askConsent: vi.fn(async () => true),
    stats: () => ({ spawns: 0, solves: runs.length, moduleKept: false, updated: engine.updated }),
  };
  engine.loadEngine = async (url) => {
    loaded.push(url);
    return {
      getEngineClient(options) {
        engine.options.push(options);
        return engine.client;
      },
    };
  };
  return engine;
}

// ---- the messages ---------------------------------------------------------------------------------------------------------------------------------

/** A kit of 22 places from `{index: ident}`. */
export function kitOf(places = {}) {
  const kit = Array(22).fill(null);
  for (const [index, ident] of Object.entries(places)) kit[Number(index)] = ident;
  return kit;
}

/** Equip now as the page's `onStep` gets it (index 0). */
export const equipStep = ({ kit = kitOf(), status = "optimal", proven = true, label = null, value = 1000 } = {}) => ({
  index: 0,
  status,
  proven,
  label,
  F: kit === null ? null : `${value}/1`,
  value: kit === null ? null : value,
  kit,
  buffs: [],
  hasteAssumed: 30,
});

/** A step of the path (index 1 to 8) that was found. */
export const pathStep = (index, { ident, kind = "new", sourceTier = null, cost = null, gain = 100, kit = kitOf(), status = "optimal", proven = true, label = null } = {}) => ({
  index,
  found: true,
  ident,
  kind,
  sourceTier,
  cost,
  F: `${1000 + gain}/1`,
  value: 1000 + gain,
  gain: `${gain}/1`,
  gainValue: gain,
  kit,
  buffs: [],
  hasteAssumed: 30,
  status,
  proven,
  label,
});

/** A step that was not found: a solve that ran out of time with nothing. */
export const lostStep = (index) => ({
  index,
  found: false,
  ident: null,
  kind: null,
  sourceTier: null,
  cost: null,
  F: null,
  value: null,
  gain: null,
  gainValue: null,
  kit: null,
  buffs: [],
  hasteAssumed: 30,
  status: "time_limit",
  proven: false,
  label: "not found in time",
});

/** The result of a farm path. */
export const ended = (stopped, steps) => ({ kind: "scenario", mode: "farm-path", stopped, steps, hasteAssumed: 30, elapsedMs: 5 });

/** What the cost of an item that reaches a tier from the tier it arrives at (or an owned copy is brought from) is, as a step carries it. */
export const costOf = (from, to, arrival = from) => ({ exp: 2 ** to - 2 ** from, copiesAtArrival: Math.ceil((2 ** to - 2 ** from) / 2 ** arrival), potentials: to - from });

// ---- the section ---------------------------------------------------------------------------------------------------------------------------------

/**
 * The Upgrade section of the contract page with its controls awake, the gear input on a table (the one above by default) and the answer on it, run against a stand-in for the
 * optimizer. `view` is the view of the page, which a test may change with `setView` (the page code tells the section that it changed). The answer speaks through `spoken`, the gear
 * input through `said`. `pauseMs` is the answer's pause before it sends (the default is the section's own).
 */
export function mountAnswer({ items = table(), engine = fakeEngine(), pauseMs, onUpdated = vi.fn(), reload = vi.fn(), level = 50, announce = true, onGear } = {}) {
  const root = mountPage('<p id="announce" class="sr-only" role="status" aria-live="polite"></p>');
  wake(root);
  root.dataset.level = String(level);
  const said = [];
  const spoken = [];
  const gear = createGearInput(root, { items, trio: TRIO, doc: document, win: window, announce: (text) => said.push(text) });
  let view = { ...VIEW };
  const watchers = new Set();
  const answer = createUpgradeAnswer(root, {
    gear,
    records: items.records,
    trio: root.dataset.trio,
    level,
    view: () => ({ ...view }),
    onView: (callback) => {
      watchers.add(callback);
      return () => watchers.delete(callback);
    },
    words: words(),
    clientPath: CLIENT_PATH,
    loadEngine: engine.loadEngine,
    ...(announce ? { announce: (text) => spoken.push(text) } : {}),
    ...(onGear === undefined ? {} : { onGear }),
    onUpdated,
    reload,
    doc: document,
    win: window,
    ...(pauseMs === undefined ? {} : { pauseMs }),
  });
  return {
    root,
    gear,
    answer,
    engine,
    said,
    spoken,
    onUpdated,
    reload,
    setView(change) {
      view = { ...view, ...change };
      for (const watcher of [...watchers]) watcher();
    },
  };
}

/** Add an item by name the way a visitor does: type, choose the first option with the keys, pick the tier, press Add. */
export function addByName(name, tier = "4") {
  const input = $("#upgrade-pick");
  type(input, name);
  press(input, "ArrowDown");
  press(input, "Enter");
  $("#upgrade-tier").value = tier;
  $("#upgrade-add").click();
}

/** Let what is waiting on promises run. */
export const flush = async () => {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
};

/** Wait (with fake timers) for the pause before a request is sent, and for the module of the client to come. */
export async function pause(ms = 600) {
  await vi.advanceTimersByTimeAsync(ms);
  await flush();
}

/** The text of an element, whitespace gathered; the empty text for an element that is not there. */
export const textOf = (selector, within = document) => (within.querySelector(selector)?.textContent ?? "").replace(/\s+/g, " ").trim();
