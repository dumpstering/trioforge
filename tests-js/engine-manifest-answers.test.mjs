// What the page's client and the worker do with an answer of fetchTextWithin that is none of the four it names (ok, status, failed, timeout).
// The helper is replaced here by one that can say anything, so a state that does not exist yet - a new one added later, say - is seen to be
// a failure and never to fall through to the text beside it. The rest of the engine's tests are in engine-worker.test.mjs.

import { JSDOM } from "jsdom";
import { describe, expect, it, vi } from "vitest";
import { createEngineClient } from "../pipeline/trioforge/site/static/engine/client.js";
import { EngineFault, readManifest } from "../pipeline/trioforge/site/static/engine/worker.js";
import { handMilp } from "./engine-models.mjs";

const answer = vi.hoisted(() => ({ next: null }));

vi.mock("../pipeline/trioforge/site/static/engine/manifest.js", async (importOriginal) => {
  const original = await importOriginal();
  return { ...original, fetchTextWithin: (...args) => (answer.next === null ? original.fetchTextWithin(...args) : answer.next(...args)) };
});

const MANIFEST_JSON = {
  version: 2,
  highs: "1.15.3",
  data_release: "data-2026-10-14",
  rules_version: "2026-10-13",
  client: { path: "/assets/engine/client-AAAAAAAA.js", bytes: 9000, gzip: 3000 },
  worker: { path: "/assets/engine/worker-BBBBBBBB.js", bytes: 120000, gzip: 40000 },
  wasm: { path: "/assets/engine/highs-0123456789ABCDEF.wasm", bytes: 3531385, gzip: 1200000, sha256: "0123456789abcdef" + "f".repeat(48) },
  items: { path: "/assets/engine/data/items-1111111111111111.json", bytes: 1900000, gzip: 180000, sha256: "1".repeat(64) },
  trios: { "pal-mnk-ber": [50] },
};
const GOOD_TEXT = JSON.stringify(MANIFEST_JSON);
const BASE = "https://trioforge.test/assets/engine/worker-BBBBBBBB.js";

/** Answers that are not one of the four, some of them with a perfectly good manifest beside the state. */
const ODD_ANSWERS = {
  "a state nobody knows, with the manifest beside it": { state: "cached", text: GOOD_TEXT },
  "a state nobody knows, with nothing beside it": { state: "weird" },
  "no state at all, with the manifest": { text: GOOD_TEXT },
  "ok, with no text": { state: "ok" },
  "ok, with a text that is not text": { state: "ok", text: 5 },
};

describe("an answer of fetchTextWithin that is none of the four", () => {
  it("is let through to the real helper while no test has put another in its place", async () => {
    answer.next = null;
    const dom = new JSDOM("<!doctype html><main id='main'></main>", { url: "https://trioforge.test/" });
    const client = createEngineClient({
      window: dom.window,
      document: dom.window.document,
      fetch: async () => ({ ok: true, status: 200, text: async () => GOOD_TEXT }),
      createWorker: () => ({ postMessage() {}, terminate() {} }),
      consent: { ask: async () => false },
      trustedTypes: null,
    });
    await expect(client.solve({ v: 1, kind: "model", model: handMilp(), budgetMs: 1000 })).rejects.toMatchObject({ code: "declined" }); // the manifest was read: the question was reached
    const fine = await readManifest({ fetchImpl: async () => ({ ok: true, status: 200, text: async () => GOOD_TEXT }), base: BASE });
    expect(fine.wasm.path).toBe(MANIFEST_JSON.wasm.path);
  });

  for (const [name, odd] of Object.entries(ODD_ANSWERS)) {
    it(`is a failure of the page's read of the list of files: ${name}`, async () => {
      answer.next = async () => odd;
      const dom = new JSDOM("<!doctype html><main id='main'></main>", { url: "https://trioforge.test/" });
      const ask = vi.fn(async () => true);
      const workers = [];
      const client = createEngineClient({
        window: dom.window,
        document: dom.window.document,
        fetch: async () => ({ ok: true, status: 200, text: async () => GOOD_TEXT }),
        createWorker: () => {
          workers.push(1);
          return { postMessage() {}, terminate() {} };
        },
        consent: { ask },
        trustedTypes: null,
      });
      try {
        await expect(client.solve({ v: 1, kind: "model", model: handMilp(), budgetMs: 1000 })).rejects.toMatchObject({ code: "unavailable" });
        expect(ask).not.toHaveBeenCalled(); // no manifest, no question
        expect(workers).toHaveLength(0);
      } finally {
        answer.next = null;
      }
    });

    it(`is a failure of the worker's read of the list of files, with a message of the worker's own: ${name}`, async () => {
      answer.next = async () => odd;
      try {
        const failure = await readManifest({ fetchImpl: async () => ({ ok: true, status: 200, text: async () => GOOD_TEXT }), base: BASE }).catch((error) => error);
        expect(failure).toBeInstanceOf(EngineFault);
        expect(failure).toMatchObject({ code: "engine-load" });
        expect(failure.message).toMatch(/could not|did not|manifest/i);
      } finally {
        answer.next = null;
      }
    });
  }
});
