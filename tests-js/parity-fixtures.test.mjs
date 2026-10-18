import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";

// The committed sample of the parity fixtures (python -m trioforge.export.fixtures --sample), read the way the parity tests of the
// engine will read them: the manifest and its hashes, the exact numbers, the model arrays and the records. Nothing here uses the engine.

const SAMPLE = new URL("../fixtures/parity/", import.meta.url);
const RATIONAL = /^-?[0-9]+\/[1-9][0-9]*$/;
const CLASS_CODE = /^[A-Z]{3}$/;

function read(name) {
  const raw = readFileSync(new URL(name, SAMPLE));
  const text = name.endsWith(".gz") ? gunzipSync(raw) : raw;
  return { text, doc: JSON.parse(text.toString("utf8")) };
}

const manifest = read("manifest.json").doc;
const documents = new Map(manifest.files.map((entry) => [entry.path, read(entry.path)]));

function gcd(a, b) {
  let [x, y] = [a < 0n ? -a : a, b];
  while (y) [x, y] = [y, x % y];
  return x;
}

// Every number under a value, and every leaf of an exact tree: loops that run hundreds of thousands of times, so they collect what
// is wrong and the test asserts once.
function* numbers(value) {
  if (typeof value === "number") yield value;
  else if (Array.isArray(value)) for (const item of value) yield* numbers(item);
  else if (value !== null && typeof value === "object") for (const item of Object.values(value)) yield* numbers(item);
}

function* leaves(value) {
  if (Array.isArray(value)) for (const item of value) yield* leaves(item);
  else if (value !== null && typeof value === "object") for (const item of Object.values(value)) yield* leaves(item);
  else yield value;
}

function* breakdowns(doc) {
  if (doc.kind === "case") for (const solve of doc.solves) yield solve.result.breakdown;
  if (doc.kind === "evaluate-kits") for (const evaluation of doc.evaluations) yield evaluation.breakdown;
}

function exactProblem(leaf) {
  if (typeof leaf !== "string") return "a bare value";
  if (RATIONAL.test(leaf)) {
    const [p, q] = leaf.split("/").map(BigInt);
    return gcd(p, q) === 1n ? null : "not in lowest terms";
  }
  return CLASS_CODE.test(leaf) ? null : "neither a p/q string nor a class code";
}

describe("the committed sample of the parity fixtures", () => {
  it("has a complete manifest whose files are the ones listed, with the size and SHA-256 of their text", () => {
    expect(manifest.kind).toBe("manifest");
    expect(manifest.complete).toBe(true);
    expect(manifest.scale).toBe("sample");
    expect(manifest.data_release).toMatch(/^data-/);
    expect(manifest.files.length).toBeGreaterThan(60);
    const wrong = manifest.files.filter(({ path, bytes, sha256 }) => {
      const { text } = documents.get(path);
      return text.length !== bytes || createHash("sha256").update(text).digest("hex") !== sha256;
    });
    expect(wrong.map((entry) => entry.path)).toEqual([]);
  });

  it("carries the release fields of the manifest in every document", () => {
    const wrong = [...documents].filter(
      ([, { doc }]) => doc.data_release !== manifest.data_release || doc.rules_version !== manifest.rules_version,
    );
    expect(wrong.map(([path]) => path)).toEqual([]);
  });

  it("holds only numbers that a double reads exactly: integers are safe, and the exact values are reduced p/q strings", () => {
    const problems = [];
    for (const [path, { doc }] of documents) {
      for (const number of numbers(doc)) {
        if (!Number.isFinite(number) || (Number.isInteger(number) && !Number.isSafeInteger(number))) problems.push(`${path}: ${number}`);
      }
      for (const breakdown of breakdowns(doc)) {
        for (const leaf of leaves(breakdown)) {
          const problem = exactProblem(leaf);
          if (problem) problems.push(`${path}: ${leaf} is ${problem}`);
        }
      }
    }
    expect(problems.slice(0, 5)).toEqual([]);
  });

  it("has models in compressed row form whose arrays agree, and every pool item has a record", () => {
    const problems = [];
    let models = 0;
    for (const [path, { doc }] of documents) {
      if (doc.kind !== "case") continue;
      const records = new Set(doc.records.map((record) => record.key ?? `w${record.id}`));
      for (const solve of doc.solves) {
        const model = solve.model;
        const [cols, rows] = [model.col_names.length, model.row_names.length];
        const lengths = [model.col_lb.length, model.col_ub.length, model.c.length, model.integrality.length];
        if (model.version !== 1 || lengths.some((length) => length !== cols)) problems.push(`${path}: the columns`);
        if (model.row_lb.length !== rows || model.row_ub.length !== rows) problems.push(`${path}: the rows`);
        const { start, index, value } = model.A;
        if (start.length !== rows + 1 || start.at(-1) !== index.length || index.length !== value.length) problems.push(`${path}: A`);
        if (index.some((column) => column < 0 || column >= cols)) problems.push(`${path}: a column index`);
        if (new Set(model.row_names).size !== rows) problems.push(`${path}: row names`);
        for (const ident of solve.pool) {
          if (!records.has(ident.slice(0, ident.lastIndexOf("@")))) problems.push(`${path}: ${ident} has no record`);
        }
        if (solve.result.kit.length !== 22) problems.push(`${path}: the kit`);
        models += 1;
      }
    }
    expect(problems.slice(0, 5)).toEqual([]);
    expect(models).toBeGreaterThan(60);
  });

  it("is plain ASCII with LF line ends, so that a hash of the text is a hash of the file", () => {
    const wrong = [...documents].filter(([, { text }]) => text.some((byte) => byte >= 0x80 || byte === 0x0d));
    expect(wrong.map(([path]) => path)).toEqual([]);
  });
});
