// The engine data of the synthetic site fixture (fixtures/site/results: the item table and the bundle of PAL/MNK/BER, made by pipeline/tests/engine_fixture.py)
// and the Equip now answers Python's reference gave for three scenarios (fixtures/site/equip-now.json), for the tests that hold the worker's data loading
// and its Equip now to them. A site is a manifest (version 2) that lists the item table with its real size and SHA-256, the manifest of each trio (which
// lists the bundles of the trio the same way), and a fetch that serves them under their paths and records what it was asked. Every name and number in the
// fixture is invented (pipeline/tests/test_site_fixture_items.py fails when the key or the name of a real item of the wiki is in it).

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseManifest } from "../pipeline/trioforge/site/static/engine/manifest.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const RESULTS = resolve(ROOT, "fixtures/site/results");
export const SLUG = "pal-mnk-ber";
export const ORIGIN = "https://trioforge.test";
/** The address the worker's own file has: the base the data paths of the manifest are made absolute against. */
export const BASE = `${ORIGIN}/assets/engine/worker-BBBBBBBB.js`;

export const ITEMS_BYTES = readFileSync(resolve(RESULTS, "items.json"));
export const BUNDLE_BYTES = readFileSync(resolve(RESULTS, SLUG, "engine-l50.json"));
/** The family of the fixture with a table of procs in its bundle (fixtures/site/results-procs, fixtures/site/procs-family.json, made by engine_fixture.py): the bundle and the item table (the fixture's and a Lore weapon), and Python's answers with the table. */
export const PROCS_BUNDLE_BYTES = readFileSync(resolve(RESULTS, "../results-procs", SLUG, "engine-l50.json"));
export const PROCS_ITEMS_BYTES = readFileSync(resolve(RESULTS, "../results-procs/items.json"));
export const PROCS_FAMILY = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/procs-family.json"), "utf8"));
export const EQUIP_NOW = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/equip-now.json"), "utf8"));
/** Python's answers for the four Upgrade modes under weights (fixtures/site/weighted.json): cases `{name, seed, scenario, owned, weights, tierMode, equipNow, farmPath, bestSets, everySlot}`. */
export const WEIGHTED = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/weighted.json"), "utf8"));
/** Python's best kits of whole-pool views at the weapon tier rates 5 and 10 (fixtures/site/weapon-rate.json): cases `{name, scenario, tier, weights?, rates: {5, 10}, rules}`. */
export const WEAPON_RATE = JSON.parse(readFileSync(resolve(ROOT, "fixtures/site/weapon-rate.json"), "utf8"));

export const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const bytesOf = (value) => (typeof value === "string" ? new TextEncoder().encode(value) : value);
const TABLE = JSON.parse(ITEMS_BYTES.toString("utf8"));
/** The release of the data, as the fixture's item table says it and as the manifests must repeat it. */
export const RELEASE = Object.freeze({ data_release: TABLE.data_release, rules_version: TABLE.rules_version });

/** The bundle of the fixture for another trio: the same document with the trio changed (the worker checks that a bundle is the trio's it was asked for). */
export function bundleFor(trio, level = 50) {
  const document = JSON.parse(BUNDLE_BYTES.toString("utf8"));
  document.trio = trio.split("-").map((code) => code.toUpperCase());
  document.profile_common.trio = [...document.trio];
  document.level = level;
  document.profile_common.level = level;
  return new TextEncoder().encode(JSON.stringify(document));
}

/**
 * A site: `manifestJson` (version 2) listing the item table with the size and the SHA-256 of its bytes, the release of the data and the levels of each trio
 * of `bundles` ({trio: {level: bytes}}; the bundle of the fixture for PAL/MNK/BER by default); `trioJson`, the manifest of each trio (what is served at
 * `/engine-trios/<trio>.json`), which lists the bundles with their sizes and SHA-256; `manifest` (parsed), and `files`, a Map from each path to the bytes that
 * are served there (the data files and the manifests of the trios). `items` replaces the bytes of the item table. `lie` changes what a manifest says of
 * a file after its entry was made, to serve a file that is not the one listed (`lie.items` or `lie.bundle` is merged into the entry).
 */
export function makeSite({ items = ITEMS_BYTES, bundles = { [SLUG]: { 50: BUNDLE_BYTES } }, lie = {} } = {}) {
  const files = new Map();
  const entryOf = (stem, bytes, extra = {}) => {
    const digest = sha256(bytes);
    const path = `/assets/engine/data/${stem}-${digest.slice(0, 16).toUpperCase()}.json`;
    files.set(path, bytes);
    return { path, bytes: bytes.length, gzip: Math.max(1, Math.floor(bytes.length / 4)), sha256: digest, ...extra };
  };
  const trios = {};
  const trioJson = {};
  const trioPaths = {};
  for (const [trio, levels] of Object.entries(bundles)) {
    trios[trio] = Object.keys(levels).map(Number);
    trioJson[trio] = {
      version: 1,
      ...RELEASE,
      trio,
      bundles: Object.fromEntries(Object.entries(levels).map(([level, bytes]) => [level, entryOf(`${trio}-l${level}`, bytes, lie.bundle)])),
    };
    trioPaths[trio] = `/engine-trios/${trio}.json`;
    files.set(trioPaths[trio], new TextEncoder().encode(JSON.stringify(trioJson[trio])));
  }
  const manifestJson = {
    version: 2,
    highs: "1.15.3",
    ...RELEASE,
    client: { path: "/assets/engine/client-AAAAAAAA.js", bytes: 9000, gzip: 3000 },
    worker: { path: "/assets/engine/worker-BBBBBBBB.js", bytes: 120000, gzip: 40000 },
    wasm: { path: "/assets/engine/highs-0123456789ABCDEF.wasm", bytes: 3531385, gzip: 1200000, sha256: "0123456789abcdef" + "f".repeat(48) },
    items: entryOf("items", items, lie.items),
    trios,
  };
  return {
    manifestJson,
    trioJson,
    manifest: parseManifest(manifestJson),
    files,
    itemsPath: manifestJson.items.path,
    bundlePath: trioJson[SLUG]?.bundles[50]?.path,
    trioPath: trioPaths[SLUG],
    trioPaths,
  };
}

/**
 * A site whose item table offers no candidate at any level: every record is marked not-for-bis (the items a request owns are still in the table, and still
 * worn). A farm path over it has nothing to add.
 */
export function siteWithNoCandidates() {
  const table = JSON.parse(ITEMS_BYTES.toString("utf8"));
  for (const record of table.items) record.evidence = { ...record.evidence, codes: [...(record.evidence.codes ?? []), "not-for-bis"] };
  return makeSite({ items: new TextEncoder().encode(JSON.stringify(table)) });
}

/**
 * A fetch that serves the files of a site under `ORIGIN`, as a server would (`application/json`), and records what it was asked: `asked` holds the
 * address of each request. `serve(url, init)` may answer for a path instead (a Response, or undefined to go on); `type` and `chunk` change the type
 * and the size of the pieces the body comes in.
 */
export function siteFetch(site, { serve, type = "application/json", chunk = 4096 } = {}) {
  const asked = [];
  const fetchImpl = async (url, init) => {
    asked.push(String(url));
    const custom = serve?.(String(url), init);
    if (custom !== undefined) return custom;
    const path = new URL(String(url)).pathname;
    const bytes = site.files.get(path);
    if (bytes === undefined || new URL(String(url)).origin !== ORIGIN) return new Response("not found", { status: 404 });
    return new Response(piecesOf(bytes, chunk), { status: 200, headers: { "content-type": type } });
  };
  return { asked, fetchImpl };
}

/** A body that comes in pieces of `size` bytes, so that a reader can stop part way. */
export function piecesOf(value, size = 4096, seen = { pulled: 0, cancelled: false }) {
  const bytes = bytesOf(value);
  let at = 0;
  return new ReadableStream({
    pull(controller) {
      if (at >= bytes.length) {
        controller.close();
        return;
      }
      seen.pulled += 1;
      controller.enqueue(bytes.slice(at, at + size));
      at += size;
    },
    cancel() {
      seen.cancelled = true;
    },
  });
}
