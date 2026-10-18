// The entry of the main manifest for the evaluator of a shared kit: a script of its own (assets/engine/kitvalue-<hash>.js) with its two sizes and its SHA-256, which the page checks
// before it runs it. It is read as strictly as the other entries (a hashed script under /assets/engine/, a digest of 64 lower-case hexadecimal digits, whole numbers, no other
// field), and it is optional: the worker and the client need none, so a manifest without it is read and the entry is null (the page then cannot work out the value of a shared kit,
// and says so).

import { describe, expect, it } from "vitest";
import { ManifestError, isEnginePath, parseManifest } from "../pipeline/trioforge/site/static/engine/manifest.js";
import { makeSite } from "./engine-site-fixture.mjs";

const KITVALUE = { path: "/assets/engine/kitvalue-CCCCCCCC.js", bytes: 61_000, gzip: 21_000, sha256: "c0ffee0123456789".padEnd(64, "3") };
const base = () => makeSite().manifestJson;
const withEntry = (entry) => ({ ...base(), kitvalue: entry });

describe("the manifest's entry for the evaluator of a shared kit", () => {
  it("is read: its path, its sizes and its SHA-256, and nothing else", () => {
    const manifest = parseManifest(withEntry(KITVALUE));
    expect(manifest.kitvalue).toEqual(KITVALUE);
    expect(Object.isFrozen(manifest.kitvalue)).toBe(true);
    expect(Object.keys(manifest.kitvalue).sort()).toEqual(["bytes", "gzip", "path", "sha256"]);
  });

  it("is optional: a manifest that lists none is read, and its entry is null", () => {
    const manifest = parseManifest(base());
    expect(manifest.kitvalue).toBeNull();
    expect(manifest.client.path).toMatch(/client-/);
  });

  it("is a hashed script of the evaluator under /assets/engine/ and nothing else", () => {
    for (const path of [
      "/assets/engine/kitvalue.js",
      "/assets/engine/kitvalue-cccccccc.js",
      "/assets/engine/kitvalue-CCCCCC.js",
      "/assets/engine/kitvalue-CCCCCCCC.wasm",
      "/assets/engine/client-CCCCCCCC.js",
      "/assets/engine/worker-CCCCCCCC.js",
      "/assets/kitvalue-CCCCCCCC.js",
      "/assets/engine/../kitvalue-CCCCCCCC.js",
      "/assets/engine/kitvalue-CCCCCCCC.js?x=1",
      "//evil.example/assets/engine/kitvalue-CCCCCCCC.js",
      "https://evil.example/assets/engine/kitvalue-CCCCCCCC.js",
      `/assets/engine/kitvalue-${"C".repeat(33)}.js`,
    ]) {
      expect(() => parseManifest(withEntry({ ...KITVALUE, path })), path).toThrow(ManifestError);
    }
    expect(isEnginePath(KITVALUE.path, "kitvalue")).toBe(true);
    expect(isEnginePath(KITVALUE.path)).toBe(true);
    expect(isEnginePath(KITVALUE.path, "client")).toBe(false);
    expect(isEnginePath("/assets/engine/client-AAAAAAAA.js", "kitvalue")).toBe(false);
  });

  it("needs a SHA-256 of 64 lower-case hexadecimal digits", () => {
    for (const sha256 of [undefined, null, "", "C0FFEE0123456789".padEnd(64, "3"), "c0ffee0123456789".padEnd(63, "3"), "c0ffee0123456789".padEnd(65, "3"), "g0ffee0123456789".padEnd(64, "3"), 5]) {
      const { sha256: _ignored, ...rest } = KITVALUE;
      expect(() => parseManifest(withEntry(sha256 === undefined ? rest : { ...KITVALUE, sha256 })), String(sha256)).toThrow(ManifestError);
    }
  });

  it("takes whole numbers of bytes for its two sizes, and no other field", () => {
    for (const over of [{ bytes: -1 }, { bytes: 1.5 }, { bytes: "61000" }, { gzip: -1 }, { gzip: Number.NaN }, { gzip: 2 ** 40 }, { extra: 1 }, { sha1: "x" }]) {
      expect(() => parseManifest(withEntry({ ...KITVALUE, ...over })), JSON.stringify(over)).toThrow(ManifestError);
    }
    for (const entry of [null, "kitvalue", [], 5]) expect(() => parseManifest(withEntry(entry)), String(entry)).toThrow(ManifestError);
  });

  it("is not a field a manifest of another shape may carry in its place: the others still take their own fields only", () => {
    expect(() => parseManifest({ ...base(), kitvalue: KITVALUE, evaluator: KITVALUE })).toThrow(ManifestError);
    expect(() => parseManifest({ ...base(), client: { ...base().client, sha256: KITVALUE.sha256 } })).toThrow(ManifestError);
    expect(() => parseManifest({ ...base(), worker: { ...base().worker, sha256: KITVALUE.sha256 } })).toThrow(ManifestError);
  });

  it("does not change what the visitor is asked about: the optimizer's download is the worker and the WebAssembly, not the evaluator of a shared kit", async () => {
    const { downloadMegabytes } = await import("../pipeline/trioforge/site/static/engine/manifest.js");
    const plain = parseManifest(base());
    const listed = parseManifest(withEntry({ ...KITVALUE, gzip: 5_000_000 }));
    expect(downloadMegabytes(listed)).toBe(downloadMegabytes(plain));
  });
});
