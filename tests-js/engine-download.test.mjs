// The stall rule of a download (download.js, fetchBytes): no byte for the stall time ends it, and the request is aborted. The time is counted from the last
// sign that the connection is alive: the request itself, the arrival of the answer (its headers), and each piece of the body. The tests are on fake timers,
// with the numbers of the case that was found: a stall time of 30 seconds, the headers at 29.5 seconds and the first piece of the body at 30.1.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DATA_FILE, EngineFault, WASM_FILE, fetchBytes } from "../pipeline/trioforge/site/static/engine/download.js";

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

const URL_OF_FILE = new URL("https://trioforge.test/assets/engine/data/items-0123456789ABCDEF.json");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const JSON_TYPE = { "content-type": "application/json" };
const BODY = Uint8Array.from({ length: 3000 }, (_, at) => at % 251);

/** A response whose body comes in `pieces` (arrays of bytes), the first after `first` milliseconds and each next one after `gap`; none after `stopAfter` pieces. */
function response(pieces, { first = 0, gap = 0, stopAfter = Infinity } = {}) {
  let at = 0;
  return new Response(
    new ReadableStream({
      async pull(controller) {
        await sleep(at === 0 ? first : gap);
        if (at >= stopAfter) return new Promise(() => {});
        if (at >= pieces.length) return controller.close();
        controller.enqueue(pieces[at]);
        at += 1;
        return undefined;
      },
    }),
    { status: 200, headers: JSON_TYPE },
  );
}
const halves = () => [BODY.slice(0, 1500), BODY.slice(1500)];

/** Start a fetch of the file; what it did and when is in `seen`, and `settled` says how it ended once it has. */
function start({ stallMs, answerAfter, body, expected = BODY.length }) {
  const seen = { signal: null, progress: [], outcome: undefined, endedAt: null };
  const began = Date.now();
  const fetchImpl = async (_url, init) => {
    seen.signal = init.signal;
    await sleep(answerAfter);
    return body();
  };
  fetchBytes(URL_OF_FILE, expected, fetchImpl, (p) => seen.progress.push(p), stallMs, 60_000, DATA_FILE).then(
    (bytes) => {
      seen.outcome = { ok: true, bytes };
      seen.endedAt = Date.now() - began;
    },
    (error) => {
      seen.outcome = { ok: false, error };
      seen.endedAt = Date.now() - began;
    },
  );
  return seen;
}

describe("the stall time of a download", () => {
  it("is counted from the arrival of the answer: headers at 29.5 seconds and the first piece at 30.1 are not 30 seconds of nothing", async () => {
    const seen = start({ stallMs: 30_000, answerAfter: 29_500, body: () => response(halves(), { first: 600, gap: 100 }) });
    await vi.advanceTimersByTimeAsync(31_000);
    expect(seen.outcome, "it ended").toBeDefined();
    expect(seen.outcome.ok, seen.outcome.error?.message).toBe(true);
    expect([...seen.outcome.bytes]).toEqual([...BODY]);
    expect(seen.signal.aborted).toBe(false);
  });

  it("is counted from the arrival of the answer to the first piece, as it is from one piece to the next: it is still the stall time that is the limit", async () => {
    // the answer at 900 ms, then nothing for the stall time of a second: given up at 1,900 ms, not at 1,000
    const seen = start({ stallMs: 1000, answerAfter: 900, body: () => response(halves(), { first: 5000 }) });
    await vi.advanceTimersByTimeAsync(1850);
    expect(seen.outcome, "not yet").toBeUndefined();
    await vi.advanceTimersByTimeAsync(100);
    expect(seen.outcome.ok).toBe(false);
    expect(seen.outcome.error).toBeInstanceOf(EngineFault);
    expect(seen.outcome.error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/stalled.*nothing arrived for 1 seconds/i) });
    expect(seen.endedAt).toBeGreaterThanOrEqual(1900);
    expect(seen.signal.aborted).toBe(true);
  });

  it("still gives up on an answer that never comes: the stall time after the request", async () => {
    const seen = start({ stallMs: 1000, answerAfter: 60_000, body: () => response(halves()) });
    await vi.advanceTimersByTimeAsync(1100);
    expect(seen.outcome.ok).toBe(false);
    expect(seen.outcome.error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/stalled/i) });
    expect(seen.endedAt).toBeGreaterThanOrEqual(1000);
    expect(seen.endedAt).toBeLessThan(1100);
    expect(seen.signal.aborted).toBe(true);
  });

  it("still gives up on a body that stops part way: the stall time after the last piece", async () => {
    const seen = start({ stallMs: 1000, answerAfter: 10, body: () => response(halves(), { first: 100, gap: 100, stopAfter: 1 }) });
    await vi.advanceTimersByTimeAsync(1300);
    expect(seen.outcome.ok).toBe(false);
    expect(seen.outcome.error).toMatchObject({ code: "engine-load", message: expect.stringMatching(/stalled/i) });
    expect(seen.endedAt).toBeGreaterThanOrEqual(1110); // 10 ms for the answer, 100 for the piece, then the stall time
    expect(seen.endedAt).toBeLessThan(1300);
  });

  it("never gives up on a download that keeps delivering, however long it takes in all", async () => {
    const many = Array.from({ length: 60 }, (_, at) => BODY.slice(at * 50, at * 50 + 50));
    const seen = start({ stallMs: 1000, answerAfter: 900, body: () => response(many, { first: 900, gap: 900 }) });
    await vi.advanceTimersByTimeAsync(60 * 900 + 2000);
    expect(seen.outcome.ok, seen.outcome.error?.message).toBe(true);
    expect(seen.outcome.bytes).toHaveLength(3000);
    expect(seen.endedAt).toBeGreaterThan(50_000);
  });

  it("is the same for the WebAssembly and for a data file: the stall time is counted from the arrival of the answer in both", async () => {
    for (const kind of [WASM_FILE, DATA_FILE]) {
      const type = kind === WASM_FILE ? "application/wasm" : "application/json";
      let outcome;
      const fetchImpl = async () => {
        await sleep(900);
        return new Response(
          new ReadableStream({
            async pull(controller) {
              await sleep(500);
              controller.enqueue(BODY);
              controller.close();
            },
          }),
          { status: 200, headers: { "content-type": type } },
        );
      };
      fetchBytes(URL_OF_FILE, BODY.length, fetchImpl, () => {}, 1000, 60_000, kind).then(
        (bytes) => (outcome = { ok: true, bytes }),
        (error) => (outcome = { ok: false, error }),
      );
      await vi.advanceTimersByTimeAsync(2000);
      expect(outcome?.ok, `${kind.noun}: ${outcome?.error?.message}`).toBe(true);
    }
  });
});
