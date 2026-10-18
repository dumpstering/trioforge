// The model JSON v1 fixtures that the Python tests share (fixtures/milp/, made by pipeline/tests/milp_fixtures.py from the exporter,
// pipeline/trioforge/export/milp_json.py): the reader of the browser engine takes every model the exporter makes, solves it to the answer
// the Python solver found, and gives the same verdict on the documents written by hand as the Python reader does (pipeline/tests/
// test_milp_fixtures.py judges the same files).

import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { parseManifest } from "../pipeline/trioforge/site/static/engine/manifest.js";
import { LIMITS, ProtocolError, validateRequest, validateToWorker } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { loadHighsEngine } from "../pipeline/trioforge/site/static/engine/worker.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = resolve(HERE, "../fixtures/milp");
const WASM_FILE = resolve(HERE, "../node_modules/highs/build/highs.wasm");

const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const models = Object.fromEntries(
  readdirSync(resolve(FIXTURES, "models"))
    .filter((name) => name.endsWith(".json"))
    .map((name) => [name.slice(0, -".json".length), readJson(resolve(FIXTURES, "models", name))]),
);
const expected = readJson(resolve(FIXTURES, "expected.json"));
const cases = readJson(resolve(FIXTURES, "cases.json"));
const asRequest = (model) => ({ v: 1, kind: "model", model, budgetMs: 1000 });

describe("the models the exporter makes", () => {
  it("are all there: the models, and the answers the Python solver found for them", () => {
    expect(Object.keys(models).length).toBeGreaterThanOrEqual(8);
    expect(Object.keys(models).sort()).toEqual(Object.keys(expected).sort());
  });

  for (const [name, model] of Object.entries(models)) {
    it(`${name}: passes the reader, and the copy is the model, every field of it`, () => {
      const clean = validateRequest(asRequest(model));
      expect(clean.model).toEqual(model);
      expect(Object.keys(clean.model)).toHaveLength(15);
      // and the worker takes the same message when the page posts it
      expect(validateToWorker({ v: 1, type: "solve", id: 1, request: asRequest(model) }).request.model).toEqual(model);
    });
  }

  it("include a model with no integer column and a model with no column", () => {
    const pureLp = Object.values(models).filter((m) => m.c.length > 0 && !m.integrality.some(Boolean));
    expect(pureLp.length).toBeGreaterThanOrEqual(1);
    expect(Object.values(models).some((m) => m.c.length === 0)).toBe(true);
  });
});

describe("the real engine on the models the exporter makes", () => {
  const wasmBytes = readFileSync(WASM_FILE);
  const manifest = parseManifest({
    version: 2,
    highs: "1.15.3",
    data_release: "data-2026-10-14",
    rules_version: "2026-10-13",
    client: { path: "/assets/engine/client-AAAAAAAA.js", bytes: 1, gzip: 1 },
    worker: { path: "/assets/engine/worker-BBBBBBBB.js", bytes: 1, gzip: 1 },
    wasm: { path: "/assets/engine/highs-0123456789ABCDEF.wasm", bytes: wasmBytes.length, gzip: 1, sha256: createHash("sha256").update(wasmBytes).digest("hex") },
    items: { path: "/assets/engine/data/items-1111111111111111.json", bytes: 1, gzip: 1, sha256: "1".repeat(64) },
    trios: { "pal-mnk-ber": [50] },
  });
  const engine = loadHighsEngine({
    manifest,
    fetchImpl: async () => new Response(wasmBytes, { status: 200, headers: { "content-type": "application/wasm" } }),
    baseUrl: "https://trioforge.test/assets/engine/worker-BBBBBBBB.js",
  });

  for (const [name, model] of Object.entries(models)) {
    it(`${name}: finds the optimum the Python solver found`, async () => {
      const want = expected[name];
      const clean = validateRequest(asRequest(model)).model;
      const got = await (await engine).solveModel(clean, { budgetMs: 60_000, startedAt: performance.now(), onProgress() {} });
      expect(got.status).toBe(want.status);
      expect(got.proven).toBe(true);
      expect(Math.abs(got.objective - want.objective)).toBeLessThanOrEqual(1e-7 * Math.max(1, Math.abs(want.objective)));
      expect(got.nodes).toBeGreaterThanOrEqual(0);
      if (want.integer_columns === 0) expect(got.nodes).toBe(0); // a linear program has no nodes (HiGHS says -1)
    }, 60_000);
  }
});

describe("the documents written by hand, judged as the Python reader judges them", () => {
  it("are as many as the Python tests expect", () => {
    expect(Object.keys(cases.valid).length).toBeGreaterThanOrEqual(14);
    expect(Object.keys(cases.invalid).length).toBeGreaterThanOrEqual(90);
  });

  for (const [name, document] of Object.entries(cases.valid)) {
    it(`takes: ${name}`, () => {
      expect(validateRequest(asRequest(document)).model).toEqual(document);
    });
  }

  for (const [name, document] of Object.entries(cases.invalid)) {
    it(`refuses: ${name}`, () => {
      let thrown;
      try {
        validateRequest(asRequest(document));
      } catch (error) {
        thrown = error;
      }
      expect(thrown, "the reader took a document that the Python reader refuses").toBeInstanceOf(ProtocolError);
      expect(thrown.code).toBe("bad-request");
    });
  }
});

describe("the sizes both readers hold a document to", () => {
  it("are the same numbers: the ones the Python reader writes into the fixtures (milp_json.MAX_*) and the ones of this reader", () => {
    expect(cases.limits).toEqual({
      columns: LIMITS.maxColumns,
      rows: LIMITS.maxRows,
      nonzeros: LIMITS.maxNonzeros,
      info_depth: LIMITS.maxDepth,
      info_nodes: LIMITS.maxNodes,
      safe_integer: Number.MAX_SAFE_INTEGER,
    });
  });
});
