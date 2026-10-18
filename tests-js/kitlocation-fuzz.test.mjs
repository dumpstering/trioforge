// The page's side of the kit link, fuzzed: `takeKitFromLocation` (input/kitlocation.js, the one function of the codec's family that the page script carries). These tests were
// part of kitcode-fuzz.test.mjs and are moved here as they were; the helpers are copied from it, the codec is used to decode what is taken.

import { describe, expect, it } from "vitest";
import { MAX_FRAGMENT_LENGTH } from "../pipeline/trioforge/site/static/input/kitcode.js";
import { decodeKit } from "../pipeline/trioforge/site/static/input/kitdecode.js";
import { takeKitFromLocation } from "../pipeline/trioforge/site/static/input/kitlocation.js";
import { expectWithin, stopwatch } from "./timing.mjs";

// Seeded, so a failure repeats.
const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
const WIDE = `${ALPHABET}+/=%. #&?!@:;,~*'"<>\\|\t\n\r é`;

function makeRng(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const pick = (rng, n) => Math.floor(rng() * n);
const randomChars = (rng, alphabet, length) => {
  let out = "";
  for (let i = 0; i < length; i += 1) out += alphabet[pick(rng, alphabet.length)];
  return out;
};

// An item table that knows the odd page ids only, so both kinds of slot occur.
class OddItems extends Map {
  get(key) {
    return Number(key.slice(1)) % 2 === 1 ? { key } : undefined;
  }
}
const ITEMS = new OddItems();

describe("fuzz: takeKitFromLocation", () => {
  function windowAt(url, state = null) {
    let current = url;
    let held = state;
    const log = { replaceState: 0, navigation: 0, lastState: undefined };
    const location = {
      get href() { return current.href; },
      get hash() { return current.hash; },
      assign() { log.navigation += 1; },
      replace() { log.navigation += 1; },
      reload() { log.navigation += 1; },
    };
    const history = {
      get state() { return held; },
      replaceState(next, title, target) {
        log.replaceState += 1;
        const resolved = new URL(target, current);
        if (resolved.origin !== current.origin) throw new Error("SecurityError");
        held = structuredClone(next);
        log.lastState = held;
        current = resolved;
      },
    };
    return { location, history, log };
  }

  it("5,000 random fragments and states never throw, navigate, or store more than 2,049 characters", () => {
    const rng = makeRng(2026);
    const prefixes = ["#k=", "#k=", "#k", "#K=", "#", "", "#a=1&k=", "#k%3D", "#key=", "#kit=", "#/k="];
    const failures = [];
    for (let i = 0; i < 5000; i += 1) {
      const url = new URL("https://example.test/trio/pal-mnk-ber/?race=OGR");
      const payloadLength = i % 500 === 0 ? 50_000 + pick(rng, 100_000) : pick(rng, 3000);
      const payload = randomChars(rng, i % 2 === 0 ? ALPHABET : WIDE, payloadLength);
      url.hash = `${prefixes[pick(rng, prefixes.length)]}${payload}`;
      const stateChoices = [null, { k: payload.slice(0, 40) }, { k: 42 }, "k", [], { other: 1 }];
      const state = stateChoices[pick(rng, stateChoices.length)];
      const win = windowAt(url, state);
      let taken;
      try {
        taken = takeKitFromLocation(win);
      } catch (error) {
        failures.push(`#${i} threw ${error && error.message}`);
        continue;
      }
      const shape = Object.keys(taken).sort().join();
      if (shape !== "cleared,payload,source") failures.push(`#${i} shape ${shape}`);
      if (win.log.navigation !== 0) failures.push(`#${i} navigated`);
      if (win.log.replaceState > 1) failures.push(`#${i} replaceState x${win.log.replaceState}`);
      if (taken.payload !== null && (typeof taken.payload !== "string" || taken.payload.length > MAX_FRAGMENT_LENGTH + 1)) {
        failures.push(`#${i} payload of ${taken.payload && taken.payload.length}`);
      }
      if (taken.source === "fragment") {
        if (taken.cleared !== true || win.location.hash !== "") failures.push(`#${i} fragment still there`);
        if (win.log.lastState === undefined || win.log.lastState.k !== taken.payload) failures.push(`#${i} state does not hold the payload`);
        else {
          // the page's other state keys stay when the old state was a plain object, and only then
          const plain = state !== null && typeof state === "object" && !Array.isArray(state);
          const wanted = (plain ? [...new Set([...Object.keys(state), "k"])] : ["k"]).sort().join();
          const got = Object.keys(win.log.lastState).sort().join();
          if (got !== wanted) failures.push(`#${i} state keys ${got}, wanted ${wanted}`);
        }
      } else if (win.log.replaceState !== 0) {
        failures.push(`#${i} replaced state without a kit link`);
      }
      if (taken.payload === null && taken.source !== null) failures.push(`#${i} source without payload`);
      if (taken.source === "state" && !(state !== null && typeof state === "object" && typeof state.k === "string")) {
        failures.push(`#${i} read a kit out of a state that holds no text under k`);
      }
      if (typeof taken.payload === "string") {
        const decoded = decodeKit(taken.payload, ITEMS);
        if (decoded.kit === null && decoded.errors.length !== 1) failures.push(`#${i} decode gave ${decoded.errors.length} errors`);
      }
    }
    expect(failures.slice(0, 10)).toEqual([]);
  });

  it("a fragment of 5 MB is cut to 2,049 characters without being parsed", () => {
    const url = new URL("https://example.test/p/");
    url.hash = `#k=${"A".repeat(5_000_000)}`;
    const win = windowAt(url);
    const watch = stopwatch();
    const taken = takeKitFromLocation(win);
    expectWithin(watch.stop(), 500, "a fragment of 5 MB is cut");
    expect(taken.payload).toHaveLength(2049);
    expect(taken.cleared).toBe(true);
  });
});
