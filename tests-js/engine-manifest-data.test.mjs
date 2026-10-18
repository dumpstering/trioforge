// The manifests, version 2: engine-manifest.json lists the optimizer's three files, the item table, the release of the data, and, for each trio, the levels a
// request may name; the bundles of a trio are listed in a small manifest of its own (engine-trios/<trio>.json), which the worker fetches for the trio a request
// names. Both are read as strictly as a request: only hashed files under /assets/engine/data/, a SHA-256 for each, whole numbers, a bundle for each level a trio
// lists and for no other, level names without a leading zero, and the release of a trio's manifest is the release of the main one. The first version is
// refused. The site build writes them (pipeline/tests/test_site_build.py holds the two sides to the same format); the rest of the main manifest is tested in
// engine-worker.test.mjs.

import { describe, expect, it } from "vitest";
import {
  DATA_LIMITS,
  MANIFEST_LIMITS,
  MANIFEST_VERSION,
  ManifestError,
  TRIO_MANIFEST_VERSION,
  downloadMegabytes,
  parseManifest,
  parseTrioManifest,
  trioManifestPath,
} from "../pipeline/trioforge/site/static/engine/manifest.js";
import { LIMITS } from "../pipeline/trioforge/site/static/engine/protocol.js";

const ITEMS_PATH = "/assets/engine/data/items-89ABCDEF01234567.json";
const bundlePath = (trio, level, hash = "FEDCBA9876543210") => `/assets/engine/data/${trio}-l${level}-${hash}.json`;
const ITEMS_SHA = "89abcdef01234567" + "1".repeat(48);
const BUNDLE_SHA = "fedcba9876543210" + "2".repeat(48);
const entry = (path, sha256, bytes = 20_000, gzip = 5_000) => ({ path, bytes, gzip, sha256 });

const GOOD = Object.freeze({
  version: 2,
  highs: "1.15.3",
  data_release: "data-2026-10-14",
  rules_version: "2026-10-13",
  client: { path: "/assets/engine/client-AAAAAAAA.js", bytes: 9000, gzip: 3000 },
  worker: { path: "/assets/engine/worker-BBBBBBBB.js", bytes: 120000, gzip: 40000 },
  wasm: { path: "/assets/engine/highs-0123456789ABCDEF.wasm", bytes: 3531385, gzip: 1200000, sha256: "0123456789abcdef" + "f".repeat(48) },
  items: entry(ITEMS_PATH, ITEMS_SHA, 1_900_000, 182_000),
  trios: { "pal-mnk-ber": [50], "pal-shd-ber": [50, 55] },
});
const copy = (change) => {
  const manifest = structuredClone(GOOD);
  change(manifest);
  return manifest;
};

describe("the main manifest, version 2", () => {
  it("is version 2, and the limits are the build's budgets", () => {
    expect(MANIFEST_VERSION).toBe(2);
    expect(DATA_LIMITS).toEqual({ bundle: 64 * 1024, items: 4 * 1024 * 1024 });
    expect(MANIFEST_LIMITS).toEqual({ trios: 5000, levels: 8, level: 100 });
  });

  it("is read into the optimizer's files, the item table, the release and, for each trio, the levels a request may name", () => {
    const manifest = parseManifest(GOOD);
    expect(manifest.version).toBe(2);
    expect(manifest.dataRelease).toBe("data-2026-10-14");
    expect(manifest.rulesVersion).toBe("2026-10-13");
    expect(manifest.items).toEqual(GOOD.items);
    expect(Object.isFrozen(manifest.items)).toBe(true);
    expect([...manifest.trios.keys()]).toEqual(["pal-mnk-ber", "pal-shd-ber"]);
    expect(manifest.trios.get("pal-shd-ber").levels).toEqual([50, 55]);
    expect(Object.isFrozen(manifest.trios.get("pal-shd-ber").levels)).toBe(true);
    expect(manifest.trios.get("constructor")).toBeUndefined();
    expect("bundles" in manifest.trios.get("pal-mnk-ber")).toBe(false); // the bundles are in the manifest of the trio
  });

  it("keeps a copy: changing the object that was read changes nothing", () => {
    const source = structuredClone(GOOD);
    const manifest = parseManifest(source);
    source.items.path = "/elsewhere";
    source.trios["pal-shd-ber"].push(60);
    expect(manifest.items.path).toBe(ITEMS_PATH);
    expect(manifest.trios.get("pal-shd-ber").levels).toEqual([50, 55]);
  });

  const BAD = {
    "the first version (no items, no data)": [{ version: 1, highs: "1.15.3", client: GOOD.client, worker: GOOD.worker, wasm: GOOD.wasm, trios: { "pal-mnk-ber": { levels: [50] } } }],
    "version 1 with the new fields": [copy((m) => (m.version = 1))],
    "version 3": [copy((m) => (m.version = 3))],
    "a version in text": [copy((m) => (m.version = "2"))],
    "no version": [copy((m) => delete m.version)],
    "no data release": [copy((m) => delete m.data_release)],
    "a data release that is null": [copy((m) => (m.data_release = null))],
    "a data release that is not a release": [copy((m) => (m.data_release = "2026-10-14")), copy((m) => (m.data_release = "data-2026-10-14\n")), copy((m) => (m.data_release = "data-2026-10-14/../x"))],
    "a data release that is a number": [copy((m) => (m.data_release = 20261014))],
    "no rules version": [copy((m) => delete m.rules_version)],
    "a rules version that is not a version of the rules": [copy((m) => (m.rules_version = "latest")), copy((m) => (m.rules_version = "2026-10-13 ")), copy((m) => (m.rules_version = 5))],
    "no item table": [copy((m) => delete m.items)],
    "an item table that is null": [copy((m) => (m.items = null))],
    "an item table that is a list": [copy((m) => (m.items = [ITEMS_PATH]))],
    "an item table that is a text": [copy((m) => (m.items = ITEMS_PATH))],
    "an item table with a field that is not allowed": [copy((m) => (m.items.url = "https://evil.example/items.json"))],
    "an item table with a field that is not allowed (a second digest)": [copy((m) => (m.items.sha512 = "0"))],
    "an item table with no path": [copy((m) => delete m.items.path)],
    "an item table with no size": [copy((m) => delete m.items.bytes)],
    "an item table with no gzip size": [copy((m) => delete m.items.gzip)],
    "an item table with no sha256": [copy((m) => delete m.items.sha256)],
    "an item table whose sha256 is in capitals": [copy((m) => (m.items.sha256 = ITEMS_SHA.toUpperCase()))],
    "an item table whose sha256 is too short": [copy((m) => (m.items.sha256 = ITEMS_SHA.slice(1)))],
    "an item table whose sha256 is too long": [copy((m) => (m.items.sha256 = `${ITEMS_SHA}0`))],
    "an item table whose sha256 is not hexadecimal": [copy((m) => (m.items.sha256 = `g${ITEMS_SHA.slice(1)}`))],
    "an item table whose sha256 is a number": [copy((m) => (m.items.sha256 = 5))],
    "an item table that is not hashed": [copy((m) => (m.items.path = "/assets/engine/data/items.json"))],
    "an item table with a hash in small letters": [copy((m) => (m.items.path = "/assets/engine/data/items-89abcdef01234567.json"))],
    "an item table with a hash that is too short": [copy((m) => (m.items.path = "/assets/engine/data/items-89ABCDEF0123456.json"))],
    "an item table with a hash that is too long": [copy((m) => (m.items.path = "/assets/engine/data/items-89ABCDEF012345678.json"))],
    "an item table that is a script": [copy((m) => (m.items.path = "/assets/engine/data/items-89ABCDEF01234567.js"))],
    "an item table with a query": [copy((m) => (m.items.path = `${ITEMS_PATH}?x=1`))],
    "an item table with a fragment": [copy((m) => (m.items.path = `${ITEMS_PATH}#x`))],
    "an item table outside assets/engine/data": [
      copy((m) => (m.items.path = "/assets/engine/items-89ABCDEF01234567.json")),
      copy((m) => (m.items.path = "/assets/data/items-89ABCDEF01234567.json")),
      copy((m) => (m.items.path = "/data/items-89ABCDEF01234567.json")),
      copy((m) => (m.items.path = "/assets/engine/data/sub/items-89ABCDEF01234567.json")),
    ],
    "an item table that climbs": [copy((m) => (m.items.path = "/assets/engine/data/../items-89ABCDEF01234567.json"))],
    "an item table on another site": [
      copy((m) => (m.items.path = `https://evil.example${ITEMS_PATH}`)),
      copy((m) => (m.items.path = `//evil.example${ITEMS_PATH}`)),
      copy((m) => (m.items.path = `\\\\evil.example${ITEMS_PATH}`)),
    ],
    "an item table that is the bundle of a trio": [copy((m) => (m.items.path = bundlePath("pal-mnk-ber", 50)))],
    "an item table with a path that is not text": [copy((m) => (m.items.path = 5)), copy((m) => (m.items.path = null))],
    "an item table with a negative size": [copy((m) => (m.items.bytes = -1))],
    "an item table with no bytes at all": [copy((m) => (m.items.bytes = 0))],
    "an item table with a size that is not whole": [copy((m) => (m.items.bytes = 1.5)), copy((m) => (m.items.gzip = 0.5))],
    "an item table with a size in text": [copy((m) => (m.items.bytes = "1900000"))],
    "an item table with a size that is not a number": [copy((m) => (m.items.bytes = Number.NaN)), copy((m) => (m.items.bytes = Infinity))],
    "an item table larger than the build allows": [copy((m) => (m.items.bytes = DATA_LIMITS.items + 1))],
    "trios that are a list": [copy((m) => (m.trios = [["pal-mnk-ber", [50]]]))],
    "no trios": [copy((m) => (m.trios = {})), copy((m) => delete m.trios)],
    "a trio under a name that is not a trio code": [copy((m) => (m.trios.constructor = [50])), copy((m) => (m.trios["PAL-MNK-BER"] = [50])), copy((m) => (m.trios["pal-mnk"] = [50]))],
    "a trio in the first layout (levels and bundles in the main manifest)": [
      copy((m) => (m.trios["pal-mnk-ber"] = { levels: [50], bundles: { 50: entry(bundlePath("pal-mnk-ber", 50), BUNDLE_SHA) } })),
      copy((m) => (m.trios["pal-mnk-ber"] = { levels: [50] })),
    ],
    "a trio whose levels are not a list": [copy((m) => (m.trios["pal-mnk-ber"] = 50)), copy((m) => (m.trios["pal-mnk-ber"] = null)), copy((m) => (m.trios["pal-mnk-ber"] = "50"))],
    "a trio with no levels": [copy((m) => (m.trios["pal-mnk-ber"] = []))],
    "a trio with too many levels": [copy((m) => (m.trios["pal-mnk-ber"] = [10, 20, 30, 40, 50, 60, 70, 80, 90]))],
    "a level listed twice": [copy((m) => (m.trios["pal-mnk-ber"] = [50, 50]))],
    "levels out of order": [copy((m) => (m.trios["pal-mnk-ber"] = [55, 50]))],
    "a level that is not a whole number": [copy((m) => (m.trios["pal-mnk-ber"] = [50.5])), copy((m) => (m.trios["pal-mnk-ber"] = ["50"])), copy((m) => (m.trios["pal-mnk-ber"] = [null]))],
    "a level of zero, a negative level and a level above the top": [copy((m) => (m.trios["pal-mnk-ber"] = [0])), copy((m) => (m.trios["pal-mnk-ber"] = [-1])), copy((m) => (m.trios["pal-mnk-ber"] = [101]))],
    "a top-level field that is not allowed": [copy((m) => (m.bundles = {})), copy((m) => (m.data = [])), copy((m) => (m.url = "/x"))],
    "an optimizer file that carries a digest it should not": [copy((m) => (m.worker.sha256 = BUNDLE_SHA))],
  };
  for (const [name, values] of Object.entries(BAD)) {
    it(`refuses ${name}`, () => {
      for (const value of values) expect(() => parseManifest(value)).toThrow(ManifestError);
    });
  }

  it("refuses an entry whose key could poison a lookup, and a manifest built with accessors", () => {
    const poisoned = JSON.parse(JSON.stringify(GOOD));
    poisoned.trios = JSON.parse(`{"pal-mnk-ber": [50], "__proto__": [50]}`);
    expect(() => parseManifest(poisoned)).toThrow(ManifestError);
    const sneaky = structuredClone(GOOD);
    let reads = 0;
    Object.defineProperty(sneaky.items, "path", { enumerable: true, get: () => ((reads += 1), ITEMS_PATH) });
    expect(() => parseManifest(sneaky)).toThrow(ManifestError);
    expect(reads).toBe(0);
  });

  it("says nothing of the visitor's data in its messages: a refusal names the part and never quotes the file", () => {
    const text = (change) => {
      try {
        parseManifest(copy(change));
      } catch (error) {
        return error.message;
      }
      return "";
    };
    expect(text((m) => (m.items.path = "https://evil.example/x"))).not.toContain("evil.example");
    expect(text((m) => (m.data_release = "https://evil.example/x"))).not.toContain("evil.example");
    expect(text((m) => (m.items.url = "https://evil.example/x"))).toMatch(/^manifest: /);
  });
});

// ---- the manifest of a trio -----------------------------------------------------------------------------------------------------------

const TRIO_GOOD = Object.freeze({
  version: 1,
  data_release: "data-2026-10-14",
  rules_version: "2026-10-13",
  trio: "pal-shd-ber",
  bundles: { 50: entry(bundlePath("pal-shd-ber", 50), BUNDLE_SHA, 21_600, 5_600), 55: entry(bundlePath("pal-shd-ber", 55, "0123456789ABCDEF"), "0123456789abcdef" + "3".repeat(48), 21_700, 5_650) },
});
const trioCopy = (change) => {
  const document = structuredClone(TRIO_GOOD);
  change(document);
  return document;
};
const MAIN = parseManifest(GOOD);
const read = (document, code = "pal-shd-ber", manifest = MAIN) => parseTrioManifest(document, manifest, code);

describe("the manifest of a trio", () => {
  it("is at an address that is built from the name of a trio the main manifest lists, and from nothing else", () => {
    expect(TRIO_MANIFEST_VERSION).toBe(1);
    expect(trioManifestPath(MAIN, "pal-shd-ber")).toBe("/engine-trios/pal-shd-ber.json");
    expect(trioManifestPath(MAIN, "pal-mnk-ber")).toBe("/engine-trios/pal-mnk-ber.json");
    for (const name of ["war-war-war", "constructor", "__proto__", "toString", "../x", "pal-mnk-ber/../../etc", "PAL-MNK-BER", "pal-mnk-ber.json", "pal-mnk-ber\n", "", undefined, null, 5, ["pal-mnk-ber"], { toString: () => "pal-mnk-ber" }]) {
      expect(trioManifestPath(MAIN, name)).toBeUndefined();
    }
  });

  it("is outside /assets/, where everything is kept for a year", () => {
    expect(trioManifestPath(MAIN, "pal-mnk-ber").startsWith("/assets/")).toBe(false);
  });

  it("is read into the bundles of the trio, by level (the keys are numbers), after the release of the main manifest", () => {
    const trio = read(TRIO_GOOD);
    expect(trio.version).toBe(1);
    expect(trio.trio).toBe("pal-shd-ber");
    expect(trio.dataRelease).toBe("data-2026-10-14");
    expect(trio.rulesVersion).toBe("2026-10-13");
    expect(trio.bundles).toBeInstanceOf(Map);
    expect([...trio.bundles.keys()]).toEqual([50, 55]);
    expect(trio.bundles.get(55)).toEqual(TRIO_GOOD.bundles[55]);
    expect(Object.isFrozen(trio.bundles.get(50))).toBe(true);
    expect(trio.bundles.get(51)).toBeUndefined();
  });

  it("keeps a copy: changing the object that was read changes nothing", () => {
    const source = structuredClone(TRIO_GOOD);
    const trio = read(source);
    source.bundles[50].bytes = 1;
    source.bundles[50].path = "/elsewhere";
    expect(trio.bundles.get(50).bytes).toBe(21_600);
    expect(trio.bundles.get(50).path).toBe(bundlePath("pal-shd-ber", 50));
  });

  const BAD = {
    "another version": [trioCopy((t) => (t.version = 2)), trioCopy((t) => (t.version = 0)), trioCopy((t) => (t.version = "1")), trioCopy((t) => delete t.version)],
    "a field that is not allowed": [trioCopy((t) => (t.url = "/x")), trioCopy((t) => (t.levels = [50, 55])), trioCopy((t) => (t.items = {}))],
    "a field that is missing": [trioCopy((t) => delete t.data_release), trioCopy((t) => delete t.rules_version), trioCopy((t) => delete t.trio), trioCopy((t) => delete t.bundles)],
    "another trio's name": [trioCopy((t) => (t.trio = "pal-mnk-ber")), trioCopy((t) => (t.trio = "PAL-SHD-BER")), trioCopy((t) => (t.trio = null))],
    "another data release than the main manifest's": [trioCopy((t) => (t.data_release = "data-2026-10-20")), trioCopy((t) => (t.data_release = null))],
    "another rules version than the main manifest's": [trioCopy((t) => (t.rules_version = "2026-10-20")), trioCopy((t) => (t.rules_version = 5))],
    "bundles that are a list": [trioCopy((t) => (t.bundles = [t.bundles[50], t.bundles[55]]))],
    "bundles that are null": [trioCopy((t) => (t.bundles = null))],
    "no bundle at all": [trioCopy((t) => (t.bundles = {}))],
    "a bundle for a level the trio does not list": [trioCopy((t) => (t.bundles[60] = entry(bundlePath("pal-shd-ber", 60), BUNDLE_SHA)))],
    "a level that has no bundle": [trioCopy((t) => delete t.bundles[55])],
    "a level name that is not canonical": [
      trioCopy((t) => {
        t.bundles = { 50: t.bundles[50], "055": t.bundles[55] };
      }),
      trioCopy((t) => {
        t.bundles = { "050": t.bundles[50], 55: t.bundles[55] };
      }),
      trioCopy((t) => {
        t.bundles = { 50: t.bundles[50], "55.0": t.bundles[55] };
      }),
      trioCopy((t) => {
        t.bundles = { 50: t.bundles[50], "+55": t.bundles[55] };
      }),
      trioCopy((t) => {
        t.bundles = { 50: t.bundles[50], " 55": t.bundles[55] };
      }),
      trioCopy((t) => {
        t.bundles = { 50: t.bundles[50], "5.5e1": t.bundles[55] };
      }),
      trioCopy((t) => {
        t.bundles = { 50: t.bundles[50], "0x37": t.bundles[55] };
      }),
      trioCopy((t) => {
        t.bundles = { 50: t.bundles[50], "": t.bundles[55] };
      }),
      trioCopy((t) => {
        t.bundles = { 50: t.bundles[50], fifty: t.bundles[55] };
      }),
    ],
    "a level named twice, once with a zero in front (the two would be one entry)": [
      trioCopy((t) => {
        t.bundles = { 50: t.bundles[50], "050": t.bundles[50], 55: t.bundles[55] };
      }),
    ],
    "a bundle with a field that is not allowed": [trioCopy((t) => (t.bundles[50].url = "/x"))],
    "a bundle with no sha256": [trioCopy((t) => delete t.bundles[50].sha256)],
    "a bundle with a sha256 in capitals": [trioCopy((t) => (t.bundles[50].sha256 = BUNDLE_SHA.toUpperCase()))],
    "a bundle with a sha256 that is too short": [trioCopy((t) => (t.bundles[50].sha256 = BUNDLE_SHA.slice(2)))],
    "a bundle with no size": [trioCopy((t) => delete t.bundles[50].bytes)],
    "a bundle with a size that is not whole": [trioCopy((t) => (t.bundles[50].bytes = 21_600.5))],
    "a bundle with a negative gzip size": [trioCopy((t) => (t.bundles[50].gzip = -5))],
    "an empty bundle": [trioCopy((t) => (t.bundles[50].bytes = 0))],
    "a bundle larger than the build allows": [trioCopy((t) => (t.bundles[50].bytes = DATA_LIMITS.bundle + 1))],
    "a bundle that is not hashed": [trioCopy((t) => (t.bundles[50].path = "/assets/engine/data/pal-shd-ber-l50.json"))],
    "a bundle of another trio": [trioCopy((t) => (t.bundles[50].path = bundlePath("pal-mnk-ber", 50)))],
    "a bundle of another level": [trioCopy((t) => (t.bundles[50].path = bundlePath("pal-shd-ber", 55)))],
    "a bundle whose file name writes the level with a zero in front": [
      trioCopy((t) => (t.bundles[50].path = bundlePath("pal-shd-ber", "050"))),
      trioCopy((t) => (t.bundles[55].path = bundlePath("pal-shd-ber", "055", "0123456789ABCDEF"))),
    ],
    "a bundle outside assets/engine/data": [
      trioCopy((t) => (t.bundles[50].path = "/assets/engine/pal-shd-ber-l50-FEDCBA9876543210.json")),
      trioCopy((t) => (t.bundles[50].path = "/data/pal-shd-ber-l50-FEDCBA9876543210.json")),
      trioCopy((t) => (t.bundles[50].path = "/engine-trios/pal-shd-ber-l50-FEDCBA9876543210.json")),
    ],
    "a bundle that climbs": [trioCopy((t) => (t.bundles[50].path = "/assets/engine/data/../pal-shd-ber-l50-FEDCBA9876543210.json"))],
    "a bundle on another site": [trioCopy((t) => (t.bundles[50].path = `https://evil.example${bundlePath("pal-shd-ber", 50)}`))],
    "a bundle with a query": [trioCopy((t) => (t.bundles[50].path = `${bundlePath("pal-shd-ber", 50)}?x=1`))],
    "a bundle that is the item table": [trioCopy((t) => (t.bundles[50].path = ITEMS_PATH))],
  };
  for (const [name, values] of Object.entries(BAD)) {
    it(`refuses ${name}`, () => {
      for (const value of values) expect(() => read(value)).toThrow(ManifestError);
    });
  }

  it("refuses a name that is not a trio of the main manifest, though the document is the trio's own", () => {
    const stranger = { ...structuredClone(TRIO_GOOD), trio: "war-war-war", bundles: { 50: entry(bundlePath("war-war-war", 50), BUNDLE_SHA) } };
    expect(() => read(stranger, "war-war-war")).toThrow(ManifestError);
    expect(() => read(TRIO_GOOD, "pal-mnk-ber")).toThrow(ManifestError); // the document of one trio is not another's
  });

  it("takes the levels from the main manifest: one bundle for each, and no other", () => {
    const only = parseManifest(copy((m) => (m.trios["pal-shd-ber"] = [50])));
    expect(() => read(TRIO_GOOD, "pal-shd-ber", only)).toThrow(ManifestError); // a bundle for 55, which the main manifest does not list
    const more = parseManifest(copy((m) => (m.trios["pal-shd-ber"] = [50, 55, 60])));
    expect(() => read(TRIO_GOOD, "pal-shd-ber", more)).toThrow(ManifestError); // no bundle for 60
  });

  it("refuses an entry whose key could poison a lookup, and a document built with accessors", () => {
    const poisoned = JSON.parse(JSON.stringify(TRIO_GOOD));
    poisoned.bundles = JSON.parse(`{"50": ${JSON.stringify(TRIO_GOOD.bundles[50])}, "55": ${JSON.stringify(TRIO_GOOD.bundles[55])}, "__proto__": {"path": "x"}}`);
    expect(() => read(poisoned)).toThrow(ManifestError);
    const sneaky = structuredClone(TRIO_GOOD);
    let reads = 0;
    Object.defineProperty(sneaky.bundles[50], "path", { enumerable: true, get: () => ((reads += 1), bundlePath("pal-shd-ber", 50)) });
    expect(() => read(sneaky)).toThrow(ManifestError);
    expect(reads).toBe(0);
    for (const notPlain of [null, [], "pal-shd-ber", 5, new Map()]) expect(() => read(notPlain)).toThrow(ManifestError);
  });

  it("says nothing of the file's content in its messages: a refusal names the part and never quotes the file", () => {
    const text = (change) => {
      try {
        read(trioCopy(change));
      } catch (error) {
        return error.message;
      }
      return "";
    };
    expect(text((t) => (t.bundles[50].path = "https://evil.example/x"))).not.toContain("evil.example");
    expect(text((t) => (t.data_release = "https://evil.example/x"))).not.toContain("evil.example");
    expect(text((t) => (t.trio = "https://evil.example/x"))).not.toContain("evil.example");
    expect(text((t) => (t.url = "https://evil.example/x"))).toMatch(/^manifest: /);
  });

  it("has a size limit of its own, below the main manifest's", () => {
    expect(LIMITS.maxTrioManifestBytes).toBe(8192);
    expect(LIMITS.maxTrioManifestBytes).toBeLessThan(LIMITS.maxManifestBytes);
    // a manifest of a trio with all the levels it may list is far inside it
    const levels = [10, 20, 30, 40, 50, 60, 70, 80];
    const main = parseManifest(copy((m) => (m.trios["pal-shd-ber"] = levels)));
    const full = { ...structuredClone(TRIO_GOOD), bundles: Object.fromEntries(levels.map((level) => [level, entry(bundlePath("pal-shd-ber", level), BUNDLE_SHA, 21_600, 5_600)])) };
    expect(read(full, "pal-shd-ber", main).bundles.size).toBe(8);
    expect(JSON.stringify(full).length).toBeLessThan(LIMITS.maxTrioManifestBytes / 2);
  });
});

describe("the size of the download that the question names", () => {
  const manifest = parseManifest(GOOD);
  const bundle = TRIO_GOOD.bundles[50];

  it("counts, for a scenario, the worker, the WebAssembly, the item table and the bundle of the trio, as they travel (gzip), rounded up to a tenth of a million bytes", () => {
    // 40,000 + 1,200,000 + 182,000 + 5,600 = 1,427,600
    expect(downloadMegabytes(manifest, { bundle })).toBe(1.5);
    expect(downloadMegabytes(manifest, { bundle: { ...bundle, gzip: 1_000_000 } })).toBe(2.5);
  });

  it("counts the item table and no bundle when no trio is known (the question asked before any request)", () => {
    expect(downloadMegabytes(manifest, { bundle: null })).toBe(1.5);
    expect(downloadMegabytes(parseManifest(copy((m) => (m.items.gzip = 700_000))), { bundle: null })).toBe(2);
  });

  it("counts the worker and the WebAssembly alone for a request that fetches no data (a model)", () => {
    expect(downloadMegabytes(manifest)).toBe(1.3); // 1,240,000
    expect(downloadMegabytes(manifest, undefined)).toBe(1.3);
  });

  it("is never less than the sum, and never a tenth of a million bytes more", () => {
    for (const gzip of [0, 1, 99_999, 100_000, 100_001, 5_600, 59_999, 60_000]) {
      const sum = 40_000 + 1_200_000 + 182_000 + gzip;
      const tenths = Math.round(downloadMegabytes(manifest, { bundle: { ...bundle, gzip } }) * 10);
      expect(tenths * 100_000).toBeGreaterThanOrEqual(sum);
      expect(tenths * 100_000 - sum).toBeLessThan(100_000);
    }
  });
});

describe("reading a small file within a limit on its size", () => {
  const stream = (chunks, seen) =>
    new ReadableStream({
      pull(controller) {
        if (seen.at >= chunks.length) return controller.close();
        seen.pulled += 1;
        controller.enqueue(chunks[seen.at++]);
        return undefined;
      },
      cancel() {
        seen.cancelled = true;
      },
    });
  const answer = (body) => async () => new Response(body, { status: 200, headers: { "content-type": "application/json" } });
  const piece = (size) => new Uint8Array(size).fill(0x20);

  it("returns the text of a file within the limit, as before", async () => {
    const { fetchTextWithin } = await import("../pipeline/trioforge/site/static/engine/manifest.js");
    expect(await fetchTextWithin(answer("{}"), "/x", {}, 1000, 100)).toEqual({ state: "ok", text: "{}" });
    expect(await fetchTextWithin(answer("{}"), "/x", {}, 1000)).toEqual({ state: "ok", text: "{}" });
    expect(await fetchTextWithin(answer(new Uint8Array(100).fill(0x20)), "/x", {}, 1000, 100)).toMatchObject({ state: "ok" }); // exactly the limit
  });

  it("stops reading a body that grows past the limit, and does not ask for the rest of it", async () => {
    const { fetchTextWithin } = await import("../pipeline/trioforge/site/static/engine/manifest.js");
    const seen = { at: 0, pulled: 0, cancelled: false };
    const chunks = Array.from({ length: 1000 }, () => piece(100));
    expect(await fetchTextWithin(answer(stream(chunks, seen)), "/x", {}, 1000, 250)).toEqual({ state: "toolarge" });
    expect(seen.cancelled).toBe(true);
    expect(seen.pulled).toBeLessThanOrEqual(5); // within a piece or two of the limit, not the whole of 100,000 bytes
  });

  it("refuses a body that cannot be read in pieces and is longer than the limit, and one that is one byte too long", async () => {
    const { fetchTextWithin } = await import("../pipeline/trioforge/site/static/engine/manifest.js");
    const whole = (text) => async () => ({ ok: true, status: 200, body: null, text: async () => text });
    expect(await fetchTextWithin(whole("x".repeat(101)), "/x", {}, 1000, 100)).toEqual({ state: "toolarge" });
    expect(await fetchTextWithin(whole("x".repeat(100)), "/x", {}, 1000, 100)).toMatchObject({ state: "ok" });
    expect(await fetchTextWithin(answer(piece(101)), "/x", {}, 1000, 100)).toEqual({ state: "toolarge" });
  });

  it("counts bytes, not characters", async () => {
    const { fetchTextWithin } = await import("../pipeline/trioforge/site/static/engine/manifest.js");
    expect(await fetchTextWithin(answer("é".repeat(60)), "/x", {}, 1000, 100)).toEqual({ state: "toolarge" }); // 120 bytes
  });

  it("gives up on a body that stalls, as on an answer that does not come", async () => {
    const { fetchTextWithin } = await import("../pipeline/trioforge/site/static/engine/manifest.js");
    const stalled = new ReadableStream({ pull: () => new Promise(() => {}) });
    expect(await fetchTextWithin(answer(stalled), "/x", {}, 30, 100)).toEqual({ state: "timeout" });
  });
});
