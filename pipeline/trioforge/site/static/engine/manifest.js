// The build's lists of the optimizer's files. Two kinds, both written by the site build and both outside assets/ on purpose: everything under
// /assets/ is cached for a year because its name carries a hash of its content, and these files have the same name in every release, so they keep the
// host's default and are asked for again on every visit. The hashed files they name are under /assets/engine/.
//
// The main manifest, /engine-manifest.json:
//
//   {"version": 2, "highs": "1.15.3", "data_release": "data-2026-10-14", "rules_version": "2026-10-13",
//    "client": {"path", "bytes", "gzip"}, "worker": {...}, "wasm": {"path", "bytes", "gzip", "sha256"},
//    "kitvalue": {"path", "bytes", "gzip", "sha256"},
//    "items": {"path", "bytes", "gzip", "sha256"},
//    "trios": {"pal-mnk-ber": [50], ...}}
//
// `kitvalue` is the evaluator of a kit that came in a link (engine/kitvalue.js): a script of its own, which the page runs for a shared kit and nothing else runs, so the optimizer's
// client does not carry it. The page fetches it, checks its size and its SHA-256, and only then imports it. It is optional here, since the worker and the client need none: a
// manifest that lists none is read, and `kitvalue` is null (the page then cannot work out the value of a shared kit, and says so). The build always writes it.
//
// It lists the optimizer's files, the item table, the release of the data and, for each trio, the levels a request may name, and nothing that grows
// with the data of a trio: the page and the worker refuse a manifest of more than LIMITS.maxManifestBytes (64 KB), and a list that carried the bundles of
// 560 trios would have been over it. The bundles of a trio are in the manifest of the trio, at /engine-trios/<trio>.json:
//
//   {"version": 1, "data_release": "data-2026-10-14", "rules_version": "2026-10-13", "trio": "pal-mnk-ber",
//    "bundles": {"50": {"path", "bytes", "gzip", "sha256"}}}
//
// which the worker fetches for the trio a request names (the page does so for the size of its question). The address is made by trioManifestPath from
// the name of a trio that the main manifest lists, never from the text of a request, and the file has a limit on its size of its own
// (LIMITS.maxTrioManifestBytes) and the release of the main manifest.
//
// The page and the worker both read these files, and neither takes an address from anywhere else: the paths of the worker and of the WebAssembly are
// the manifest's, so are those of the data the worker reads to work out an answer for a visitor's own gear (the item table, and the bundle of a trio at
// a level), and a request may only name a trio and a level that the manifest lists. So the manifests are checked as strictly as a request is: only
// these fields, only hashed files under /assets/engine/ (the data under /assets/engine/data/), a SHA-256 for each file the worker checks before it uses
// it, a bundle for each level a trio lists and for no other, level names without a zero in front (so that "50" and "050" cannot be two names of one
// level), only whole numbers. A path has to look exactly like what the build makes, so that nothing the file says can point the page at another
// place. Version 1 of the main manifest, which lists no data, is refused.

import { isPlainObject, isSha256, plainEntries } from "./protocol.js";

export const MANIFEST_PATH = "/engine-manifest.json";
/** The folder of the manifests of the trios: the manifest of a trio is at `<this><trio>.json`. */
export const TRIO_MANIFEST_DIR = "/engine-trios/";
export const MANIFEST_VERSION = 2;
export const TRIO_MANIFEST_VERSION = 1;
/** The most a data file may be (the budgets of the build, site/build.py LIMITS engine_bundle and engine_items, which a test holds this to). */
export const DATA_LIMITS = Object.freeze({ bundle: 64 * 1024, items: 4 * 1024 * 1024 });
/** The counts the reader accepts: trios in the manifest, levels of a trio, and the highest level (site/build.py MANIFEST_MAX_*, which a test holds these to). */
export const MANIFEST_LIMITS = Object.freeze({ trios: 5000, levels: 8, level: 100 });

export class ManifestError extends Error {
  constructor(detail) {
    super(`manifest: ${detail}`);
    this.name = "ManifestError";
  }
}
/** A manifest of a trio that is not of the release of the main manifest: the site was released again since one of them was read. */
export class ManifestReleaseError extends ManifestError {
  constructor(detail) {
    super(detail);
    this.name = "ManifestReleaseError";
  }
}
const fail = (detail) => new ManifestError(detail);

const ENGINE_FILE = {
  client: /^\/assets\/engine\/client-[A-Z0-9]{8,32}\.js$/,
  worker: /^\/assets\/engine\/worker-[A-Z0-9]{8,32}\.js$/,
  wasm: /^\/assets\/engine\/highs-[A-Z0-9]{8,32}\.wasm$/,
  kitvalue: /^\/assets\/engine\/kitvalue-[A-Z0-9]{8,32}\.js$/,
};
const ANY_ENGINE_FILE = /^\/assets\/engine\/(?:client|worker|kitvalue|highs)-[A-Z0-9]{8,32}\.(?:js|wasm)$/;
/** The files the manifest lists with a SHA-256: the WebAssembly (the worker checks it before it compiles it) and the evaluator of a shared kit (the page checks it before it runs it). */
const CHECKED = new Set(["wasm", "kitvalue"]);
/** The data files: the item table, and the bundle of a trio at a level (each name ends in 16 digits of the file's SHA-256, and a level has no zero in front). */
const ITEMS_FILE = /^\/assets\/engine\/data\/items-[A-Z0-9]{16}\.json$/;
const BUNDLE_FILE = /^\/assets\/engine\/data\/([a-z]{3}-[a-z]{3}-[a-z]{3})-l([1-9][0-9]{0,2})-[A-Z0-9]{16}\.json$/;
const LEVEL_KEY = /^[1-9][0-9]{0,2}$/;
const TRIO_CODE = /^[a-z]{3}-[a-z]{3}-[a-z]{3}$/;
const VERSION_TEXT = /^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$/;
const DATA_RELEASE = /^data-[0-9]{4}-[0-9]{2}-[0-9]{2}$/;
const RULES_VERSION = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;
const MAX_PATH = 100;
const MAX_BYTES = 2 ** 28;

/**
 * The text of a response whose body is read in pieces and not past `maxBytes` bytes: a body that grows past the limit is cancelled, and the rest of it
 * is not asked for. A response that cannot be read in pieces is read whole and then measured.
 */
async function readText(response, maxBytes) {
  if (maxBytes === Infinity) return { state: "ok", text: await response.text() };
  const body = response.body;
  if (body && typeof body.getReader === "function") {
    const reader = body.getReader();
    const pieces = [];
    let size = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        reader.cancel().catch(() => {});
        return { state: "toolarge" };
      }
      pieces.push(value);
    }
    const bytes = new Uint8Array(size);
    let at = 0;
    for (const piece of pieces) {
      bytes.set(piece, at);
      at += piece.byteLength;
    }
    return { state: "ok", text: new TextDecoder().decode(bytes) };
  }
  const text = await response.text();
  if (typeof text !== "string" || text.length > maxBytes || new TextEncoder().encode(text).length > maxBytes) return { state: "toolarge" };
  return { state: "ok", text };
}

/**
 * Read a small text file within a time limit on the whole read (the answer, and then its body). Returns `{state: "ok", text}`,
 * `{state: "status", status}` (the server answered with an error), `{state: "failed"}` (the request failed), `{state: "timeout"}` or, when a
 * limit `maxBytes` on the size of the body was given, `{state: "toolarge"}`. On a timeout the request is aborted, and the wait ends even if the
 * fetch takes no notice of the abort: a connection that stalls ends in an answer, not in a wait with no end. A signal in `init` is honoured as well:
 * when it aborts, so does the request, and the answer is `failed` at once. (The request is given the signal of this function's own controller, which
 * both the time limit and the caller's signal feed.)
 */
export async function fetchTextWithin(fetchImpl, input, init, ms, maxBytes = Infinity) {
  const outer = init?.signal;
  if (outer?.aborted) return { state: "failed" };
  const controller = new AbortController();
  let timer;
  let onOuterAbort;
  const ended = new Promise((resolve) => {
    timer = setTimeout(() => {
      controller.abort();
      resolve({ state: "timeout" });
    }, ms);
    onOuterAbort = () => {
      controller.abort();
      resolve({ state: "failed" });
    };
  });
  if (outer) outer.addEventListener("abort", onOuterAbort);
  const reading = (async () => {
    try {
      const response = await fetchImpl(input, { ...init, signal: controller.signal });
      if (!response.ok) return { state: "status", status: response.status };
      return await readText(response, maxBytes);
    } catch {
      return { state: "failed" };
    }
  })();
  try {
    return await Promise.race([reading, ended]);
  } finally {
    clearTimeout(timer);
    if (outer) outer.removeEventListener("abort", onOuterAbort);
  }
}

/** Whether a path is one of the build's hashed engine files (of the given role, or of any role). */
export function isEnginePath(path, role) {
  if (typeof path !== "string" || path.length > MAX_PATH) return false;
  const pattern = role === undefined ? ANY_ENGINE_FILE : ENGINE_FILE[role];
  return pattern !== undefined && pattern.test(path);
}

function fileEntry(value, role) {
  const given = new Map(plainEntries(value, (detail) => fail(`${role} ${detail}`)));
  // the WebAssembly is checked before it is compiled and the evaluator of a shared kit before it is run: the manifest lists their SHA-256 (the client and the worker are loaded by the browser)
  const allowed = CHECKED.has(role) ? ["path", "bytes", "gzip", "sha256"] : ["path", "bytes", "gzip"];
  for (const key of given.keys()) {
    if (!allowed.includes(key)) throw fail(`${role} has a field that is not allowed`);
  }
  const path = given.get("path");
  if (!isEnginePath(path, role)) throw fail(`${role} is not a hashed file under /assets/engine/`);
  const entry = { path };
  for (const key of ["bytes", "gzip"]) {
    const size = given.get(key);
    if (!Number.isInteger(size) || size < 0 || size > MAX_BYTES) throw fail(`${role} has a ${key} that is not a whole number of bytes`);
    entry[key] = size;
  }
  if (CHECKED.has(role)) {
    const digest = given.get("sha256");
    if (!isSha256(digest)) throw fail(`${role} has no sha256 of 64 lower-case hexadecimal digits`);
    entry.sha256 = digest;
  }
  return Object.freeze(entry);
}

/**
 * A data file of a manifest: its path (`pattern` is what it has to look like; the match is returned too), its two sizes and its
 * SHA-256, which the worker checks before it reads a byte of the file as text. A file is not empty and not larger than the build allows.
 */
function dataEntry(value, what, pattern, maxBytes) {
  const given = new Map(plainEntries(value, (detail) => fail(`${what} ${detail}`)));
  for (const key of given.keys()) {
    if (!["path", "bytes", "gzip", "sha256"].includes(key)) throw fail(`${what} has a field that is not allowed`);
  }
  const path = given.get("path");
  const match = typeof path === "string" && path.length <= MAX_PATH ? pattern.exec(path) : null;
  if (match === null) throw fail(`${what} is not a hashed file under /assets/engine/data/`);
  const entry = { path };
  for (const key of ["bytes", "gzip"]) {
    const size = given.get(key);
    if (!Number.isInteger(size) || size < 0 || size > MAX_BYTES) throw fail(`${what} has a ${key} that is not a whole number of bytes`);
    entry[key] = size;
  }
  if (entry.bytes < 1 || entry.bytes > maxBytes) throw fail(`${what} is empty or larger than the build allows`);
  const digest = given.get("sha256");
  if (!isSha256(digest)) throw fail(`${what} has no sha256 of 64 lower-case hexadecimal digits`);
  entry.sha256 = digest;
  return { entry: Object.freeze(entry), match };
}

/** The levels a trio lists: one to eight whole numbers from 1 to 100, each above the one before. */
function levelsOf(value) {
  if (!Array.isArray(value) || value.length === 0 || value.length > MANIFEST_LIMITS.levels) throw fail("a trio has no levels or too many");
  let previous = 0;
  for (const level of value) {
    if (!Number.isInteger(level) || level <= previous || level > MANIFEST_LIMITS.level) throw fail("a level is not a whole number above the one before");
    previous = level;
  }
  return Object.freeze([...value]);
}

/**
 * The bundles in the manifest of a trio, by level: one for each level the main manifest lists for the trio and none other, each a file of that trio
 * and that level. A level is named in its canonical form (digits, no zero in front), in the key and in the file name: "050" and "50" would otherwise
 * be two names of one level.
 */
function bundlesOf(value, code, levels) {
  const bundles = new Map();
  for (const [text, file] of plainEntries(value, (detail) => fail(`a trio's bundles ${detail}`))) {
    if (!LEVEL_KEY.test(text) || String(Number(text)) !== text) throw fail("a bundle is listed under a name that is not a level");
    const level = Number(text);
    if (!levels.includes(level)) throw fail("a trio has a bundle for a level it does not list");
    const { entry, match } = dataEntry(file, "a bundle", BUNDLE_FILE, DATA_LIMITS.bundle);
    if (match[1] !== code || match[2] !== text) throw fail("a bundle is a file of another trio or another level");
    bundles.set(level, entry);
  }
  if (bundles.size !== levels.length) throw fail("a trio lists a level that it has no bundle for");
  return bundles;
}

/**
 * Read the parsed main manifest. Returns `{version, highs, dataRelease, rulesVersion, client, worker, wasm, kitvalue, items, trios}`, where `trios` is a Map from the
 * trio's code to `{levels}` and `kitvalue` the file of the evaluator of a shared kit, or null when the manifest lists none. Throws a ManifestError for anything else, a manifest
 * of version 1 included.
 */
export function parseManifest(value) {
  const given = new Map(plainEntries(value, (detail) => fail(`it ${detail}`)));
  for (const key of given.keys()) {
    if (!["version", "highs", "data_release", "rules_version", "client", "worker", "wasm", "kitvalue", "items", "trios"].includes(key)) throw fail("it has a field that is not allowed");
  }
  if (given.get("version") !== MANIFEST_VERSION) throw fail("it is of another version");
  const highs = given.get("highs");
  if (typeof highs !== "string" || !VERSION_TEXT.test(highs)) throw fail("it does not name the solver's version");
  const dataRelease = given.get("data_release");
  if (typeof dataRelease !== "string" || !DATA_RELEASE.test(dataRelease)) throw fail("it does not name the release of the data");
  const rulesVersion = given.get("rules_version");
  if (typeof rulesVersion !== "string" || !RULES_VERSION.test(rulesVersion)) throw fail("it does not name the version of the rules");
  const trios = new Map();
  const listed = given.get("trios");
  if (!isPlainObject(listed)) throw fail("its trios are not an object");
  for (const [code, levels] of plainEntries(listed, (detail) => fail(`its trios ${detail}`))) {
    if (!TRIO_CODE.test(code)) throw fail("it lists a trio under a name that is not a trio code");
    trios.set(code, Object.freeze({ levels: levelsOf(levels) }));
    if (trios.size > MANIFEST_LIMITS.trios) throw fail("it lists too many trios");
  }
  if (trios.size === 0) throw fail("it lists no trio");
  return Object.freeze({
    version: MANIFEST_VERSION,
    highs,
    dataRelease,
    rulesVersion,
    client: fileEntry(given.get("client"), "client"),
    worker: fileEntry(given.get("worker"), "worker"),
    wasm: fileEntry(given.get("wasm"), "wasm"),
    kitvalue: given.has("kitvalue") ? fileEntry(given.get("kitvalue"), "kitvalue") : null,
    items: dataEntry(given.get("items"), "the item table", ITEMS_FILE, DATA_LIMITS.items).entry,
    trios,
  });
}

/**
 * The address of the manifest of a trio: `/engine-trios/<trio>.json`, made from the name of a trio that the main manifest lists (the string the manifest
 * holds, not the one that was asked for), or undefined for a name that it does not list. A request's text is never part of an address.
 */
export function trioManifestPath(manifest, code) {
  for (const listed of manifest.trios.keys()) {
    if (listed === code) return `${TRIO_MANIFEST_DIR}${listed}.json`;
  }
  return undefined;
}

/**
 * Read the parsed manifest of a trio, for the trio `code` of the main manifest `manifest`: the same fields and the same release as the main one, the trio's
 * own name, and a bundle for each level that the main manifest lists for it and for no other. Returns `{version, dataRelease, rulesVersion, trio, bundles}`,
 * `bundles` a Map from a level to the bundle's file `{path, bytes, gzip, sha256}`. Throws a ManifestError for anything else.
 */
export function parseTrioManifest(value, manifest, code) {
  const entry = typeof code === "string" ? manifest.trios.get(code) : undefined;
  if (entry === undefined) throw fail("a trio's list of files is read for a trio that the manifest does not list");
  const given = new Map(plainEntries(value, (detail) => fail(`a trio's list of files ${detail}`)));
  const fields = ["version", "data_release", "rules_version", "trio", "bundles"];
  for (const key of given.keys()) {
    if (!fields.includes(key)) throw fail("a trio's list of files has a field that is not allowed");
  }
  for (const key of fields) {
    if (!given.has(key)) throw fail("a trio's list of files lacks a field");
  }
  if (given.get("version") !== TRIO_MANIFEST_VERSION) throw fail("a trio's list of files is of another version");
  if (given.get("trio") !== code) throw fail("a trio's list of files is for another trio");
  if (given.get("data_release") !== manifest.dataRelease || given.get("rules_version") !== manifest.rulesVersion) {
    throw new ManifestReleaseError("a trio's list of files is of another release than the manifest");
  }
  return Object.freeze({
    version: TRIO_MANIFEST_VERSION,
    dataRelease: manifest.dataRelease,
    rulesVersion: manifest.rulesVersion,
    trio: code,
    bundles: bundlesOf(given.get("bundles"), code, entry.levels),
  });
}

/**
 * How many megabytes the optimizer is to download, for the question before it is downloaded: the gzip sizes the build measured of what travels (the sizes
 * the files have once unpacked are about three times as big and are not what the visitor's connection carries), rounded up to a tenth of a million bytes.
 * `data` says what else the request fetches: nothing for a request that works from a model it carries, and for a scenario `{bundle}`, the item table and
 * the bundle of the trio (`bundle` is the file of the trio's manifest, or null when no trio is known yet, as for a question asked before any request:
 * then the item table is counted and no bundle). The figure is for the first request: a later request for another trio fetches that trio's bundle, a few
 * kilobytes, which it does not count.
 */
export function downloadMegabytes(manifest, data) {
  let bytes = manifest.worker.gzip + manifest.wasm.gzip;
  if (data !== undefined && data !== null) {
    bytes += manifest.items.gzip;
    if (data.bundle) bytes += data.bundle.gzip;
  }
  return Math.ceil(bytes / 100_000) / 10;
}
