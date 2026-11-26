// The messages between the page and the solver worker, and the checks that both sides make on them.
//
// A message is a plain object with a version (`v: 1`) and a type; nothing else crosses the boundary: no functions, no classes,
// no typed arrays, no addresses. One exception: the compiled WebAssembly module, which the worker hands to the page after it
// compiled the solver, and which the page hands to the next worker, so that a worker that had to be stopped is replaced
// without downloading or compiling the solver again.
//
//   page -> worker   {v, type: "init", module?}
//                    {v, type: "solve", id, request}
//                    {v, type: "stop", id}   (end the farm path in flight before the next step the worker begins after it has seen the stop: the step being worked
//                                             out is finished and sent, and in a browser that can be one step later than the one the page was looking at; no reply,
//                                             and nothing for any other request)
//                    {v, type: "ping"}   (is the worker still there? it answers with a pong at once)
//   worker -> page   {v, type: "ready", highs, wasm?, module?}
//                    {v, type: "progress", id?, phase, stage?, step?, ...}
//                    {v, type: "step", id, index, ...}   (a farm path: Equip now, then each step)
//                    {v, type: "result", id, kind: "model", status, proven, objective, x, bound, gap, nodes, elapsedMs, label}
//                    {v, type: "result", id, kind: "scenario", mode, ..., elapsedMs}   (the fields of each mode are below)
//                    {v, type: "pong"}
//                    {v, type: "error", id?, code, message}
//
// A request is `{v, kind: "model", model, budgetMs}` (a model as model JSON v1, which the Python exporter writes: all fifteen fields, CSR rows,
// null for an infinite bound, whole-number bounds on the integer columns) or `{v, kind: "scenario", trio, level, mode, scenario, owned, ..., budgetMs}`. No
// request carries an address: the worker works out the paths of its files from the build's manifest, and a request may only name a trio and a level that
// the manifest lists. Every field is checked against an allowlist, and every check returns a fresh copy of what it read (each field is read once), so what
// was checked is what is sent.
//
// A scenario request is of one of five modes, and of no other (any other is a bad request; there is no generic scenario shape and no list of candidates: the
// worker makes the candidates from the tier mode, and the pool of a view from the tier). Every mode has the scenario `{race, role, buffs, evidence, setup, deity?}`, and
// every mode but the best kit has the owned set `[[ident, count], ...]`: an ident is `<key>@<tier>` (the key has the form of the item table's keys, the tier is 0 to 10),
// a count is a whole number from 1 to 99, there are at most 1,000 entries and none has an ident twice. The values of the scenario are short names (checked again in the
// worker against the bundle), and the deity is a short name or null. Every mode also takes `weights` (optional), the same in all five (below). The other fields of each mode:
//
//   equip-now    nothing: the best kit from the owned items alone
//   farm-path    tierMode, steps (a whole number from 1 to 8): the best addition, and then the best one after that, ...
//   best-sets    tierMode, k (2 or 3): the best kit when up to k additions are made at once
//   every-slot   tierMode, kit (exactly 22 places, each an ident or null), buffs (whole numbers from 0, rising, once each), limit (1 to 10, 3 when none):
//                for each place the swaps that gain the most
//   best-kit     tier (a whole number from 0 to 10), options (optional): the best kit of the view over its whole pool, which the worker makes (engine/bestkit.js). No owned
//                set and no tier mode. `options` is `{weaponTierRate?}`, and only the best kit has it: the percent of damage a weapon grows a tier, 5 or 10 (the rule
//                `tier.weapon_damage_pct`, 10, is the default); any other key or value is a bad request.
//
// `weights` is `{multipliers?, custom?, regenT?}`: the slider positions by group (numbers), the custom weights by name (numbers) and the regen window in minutes (a number, or
// null for the role's own). The protocol checks their shape (an allowlist of the three options, short names, at most 32 entries a table) and their numbers: each is finite and
// zero, or at least 0.000001 in size with at most 6 significant digits (WEIGHT_FLOOR, WEIGHT_DIGITS: the exact value of the answer is a text of at most 200 characters, and
// the digits of the weights set its size). Which groups there are, which positions, which weights may be set and the bounds are the bundle's (weight_groups, regen_ratios), and
// the worker holds the request to them with weightsOverride, for every mode alike (engine/bestkit.js, `viewProfile`: weights that are the role's own change nothing). The
// weapons are paid the haste the kit counts, whatever the weights. Whether the trio has a mana pool is the worker's to say, never a field of a request.
//
// where tierMode is `{mode: "ready4"}`, `{mode: "arrives", D}` (D 0 to 4) or `{mode: "fixed", N}` (N 0 to 10), exactly those fields.
//
// The answers. Every answer that has a kit has the 22 places in kit order as idents (null for an empty place) or null when there is none, its exact value `F` as a
// reduced "p/q" text and `value` its number, the ids of the optional `buffs` chosen and the `hasteAssumed`; the honest labels and the rules of the status are those
// of a model result, and what the page asked is checked again in the answer.
//   equip-now    {status, proven, label, F, value, kit, buffs, hasteAssumed, elapsedMs}: the kit wears no more of an item than the request owned
//   farm-path    steps: {v, type: "step", id, index: 0, status, proven, label, F, value, kit, buffs, hasteAssumed} is Equip now; for 1 to 8 {index, found, ident, kind
//                ("new" | "copy" | "upgrade"), sourceTier (an upgrade's, else null), cost ({exp, copiesAtArrival, potentials} or null), F, value, gain, gainValue, kit,
//                buffs, hasteAssumed, status, proven, label}; a step that was not found has null for all that a step has, no kit and the label of a solve that ran out
//                of time with nothing. The result is {stopped ("limit" | "no-gain" | "time" | "stopped": a stop ended it), steps (how many of 1 to 8 were sent), hasteAssumed, elapsedMs}.
//                The page watches the path as a whole (createPathWatch): the steps come in order, each gains exactly its value less the value before it, and the kit
//                wears only what was owned and what the steps acquired. What a step acquires is at the tier of the request's tier mode (+4 for ready4, +N for fixed, +D
//                or +0 for arrives), and so is each addition of a best set, which the set's kit wears.
//   best-sets    {k, acquired: [{ident, kind, sourceTier, cost}], F, value, gain, gainValue, kit, buffs, status, proven, label, baseline: {F, value}, hasteAssumed,
//                elapsedMs}: the gain is exactly the value less that of Equip now, and above 0 exactly when something is acquired
//   best-kit     {status, proven, label, F, value, kit, buffs, hasteAssumed, elapsedMs}: the fields of Equip now's answer, held to the same rules. No owned set bounds the kit; the
//                kit wears only items of the pool, which is all at one tier, so the items of a kit are all of one tier, and the request's when the page names it (`expect.tier`)
//   every-slot   {rows: 22 of {place, index, current, swaps: [{ident, delta, deltaValue}]}, elapsedMs}: best gain first, equal gains by key and tier; `current` is the
//                request's kit in that place, and a swap is an item the visitor owns (as owned) or one at the tier of the tier mode. An owned item that the tier mode cannot
//                give (its tier is not the mode's) is a swap only while the visitor owns more copies of it than the request's kit wears
// The progress of a scenario request carries a `stage` (what it is working on: "loading", "equip-now", "step" with the number of its `step`, "best-sets",
// "every-slot" or "best-kit"), and the page checks it against the mode.
//
// Data hygiene (spec 8.5): lookups go through Map or objects without a prototype; a key such as __proto__ is refused; the
// walk over plain data keeps its own stack and counts its depth and its nodes, so no input can exhaust the call stack.

import { isPlainObject } from "./plain.js";
import { Rational, RationalError } from "./rational.js";

export const PROTOCOL_VERSION = 1;

/**
 * The watchdog of the page stops a worker only this long after the request's whole budget has run out (counted from the last sign of life of the worker for
 * that request: the post of the request, and each report of progress): it is for hangs, not for slow solves and not for slow downloads.
 */
export const WATCHDOG_GRACE_MS = 5000;

/**
 * While a worker loads the data of a scenario it reports so at least this often, whether bytes are arriving or not, so that the watchdog (the budget of the
 * request and WATCHDOG_GRACE_MS from the last report) is always more than this away. A worker that keeps reporting is alive; a download that has stopped is
 * ended by its stall rule (STARTUP_STALL_MS, download.js), not by the watchdog.
 */
export const LOADING_BEAT_MS = 1000;

/**
 * The limits on starting the optimizer (downloading, checking and compiling it), named here and nowhere else. A connection that stalls must not
 * leave the visitor looking at a progress bar for ever, and a slow one that is still delivering must not be cut off for being slow.
 *   STARTUP_STALL_MS     no byte of the download (and no answer to a request for the list of files) for this long: it is given up, and the request
 *                        itself is aborted. This is the only limit on the download: a download that keeps delivering is never cut off, however long
 *                        it takes (the visitor has Cancel).
 *   STARTUP_COMPILE_MS   once the last byte is in, checking the file, compiling it and starting the solver may take this long (a worker that is given
 *                        a compiled module has no download, and has this long from the start). It is also the limit for the body of a response that
 *                        cannot be read in pieces, because nothing can be seen of such a download until it is over.
 */
export const STARTUP_STALL_MS = 20_000;
export const STARTUP_COMPILE_MS = 60_000;
/**
 * A worker that has to download has said nothing at all to the page this long after its start: it reads the list of files (STARTUP_STALL_MS) and waits for the first byte (as long again) before
 * its first report, so the page's limit comes after both and a margin, and is for a worker that never reports (its script did not run) and raised no error either.
 */
export const STARTUP_FIRST_SIGN_MS = 2 * STARTUP_STALL_MS + 5_000;

/**
 * A worker that has worked before is asked whether it is still there before a request is posted to it: one that was stopped without a word (`self.close()`,
 * the browser reclaiming it) raises no error event and takes the request and never answers. An idle worker answers at once; one that does not answer in this
 * time is dropped, and the request goes to a new worker.
 */
export const LIVENESS_TIMEOUT_MS = 1000;

export const LABEL_TIME_LIMIT = "best found, not proven optimal";
export const LABEL_NO_INCUMBENT = "not found in time";

export const LIMITS = Object.freeze({
  maxColumns: 50_000,
  maxRows: 50_000,
  maxNonzeros: 1_000_000,
  maxBudgetMs: 300_000,
  maxLevel: 100,
  maxStringLength: 200,
  maxMessageLength: 300,
  maxManifestBytes: 65_536,
  // the manifest of one trio (engine-trios/<trio>.json: a bundle for each of at most eight levels) is read with a limit of its own
  maxTrioManifestBytes: 8192,
  maxDepth: 8,
  maxNodes: 100_000,
  maxId: 2_147_483_647,
  // Equip now: the owned set of a request, a name of its scenario, and the buffs and the exact value of its answer
  maxOwnedEntries: 1000,
  maxOwnedCount: 99,
  maxNameLength: 40,
  maxBuffs: 1000,
  maxExactLength: 200,
  // a farm path: the most steps a request may ask for; Every slot: the most swaps for a place
  maxPathSteps: 8,
  maxSwaps: 10,
  // the weights of a request: the most entries of a table of them (there are five slider groups and fourteen weights that may be set)
  maxWeightEntries: 32,
});

/** The progress phases: the first three while the worker starts, the last two while it solves. */
export const PHASES = Object.freeze(["loading", "compiling", "starting", "building", "solving"]);
export const ERROR_CODES = Object.freeze(["bad-request", "bad-model", "not-implemented", "not-ready", "solver", "engine-load", "internal"]);
const STATUSES = new Set(["optimal", "time_limit", "infeasible"]);

/** A message or request that is not what the protocol allows. `code` is bad-request (a request) or protocol (a reply). */
export class ProtocolError extends Error {
  constructor(code, detail) {
    super(`${code}: ${detail}`);
    this.name = "ProtocolError";
    this.code = code;
    this.detail = detail;
  }
}
const badRequest = (detail) => new ProtocolError("bad-request", detail);
const badReply = (detail) => new ProtocolError("protocol", detail);

// ---- plain data ---------------------------------------------------------------------------------------------------------------

export { isPlainObject };

/**
 * The own entries of a plain object, read once each. An accessor, a hidden property or a symbol makes it something that is not plain
 * data (a getter could show one value to a check and another to the code that sends it).
 */
export function plainEntries(value, fail) {
  if (!isPlainObject(value)) throw fail("is not a plain object");
  const entries = [];
  for (const key of Reflect.ownKeys(value)) {
    if (typeof key !== "string") throw fail("has a symbol for a key");
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (descriptor === undefined || !("value" in descriptor) || descriptor.enumerable !== true) throw fail(`has a property (${safeKey(key)}) that is not plain data`);
    entries.push([key, descriptor.value]);
  }
  return entries;
}

function safeKey(key) {
  return key.length <= 24 && /^[A-Za-z0-9_.-]*$/.test(key) ? key : "?";
}

/** A SHA-256 digest as text: 64 lower-case hexadecimal digits (what the manifest lists for the WebAssembly, and what the worker reports it loaded). */
const SHA256_HEX = /^[0-9a-f]{64}$/;
export const isSha256 = (value) => typeof value === "string" && SHA256_HEX.test(value);

const isFiniteNumber = (value) => typeof value === "number" && Number.isFinite(value);
const isWholeNumber = (value, low, high) => typeof value === "number" && Number.isInteger(value) && value >= low && value <= high;

function isControl(code) {
  return code < 0x20 || (code >= 0x7f && code <= 0x9f) || code === 0x2028 || code === 0x2029;
}

/** What a browser would take for an address: it has a scheme, or a slash or backslash (a path, a relative address, //host). */
const SCHEME = /^[A-Za-z][A-Za-z0-9+.-]{0,30}:/;
export function isUrlLike(text) {
  if (typeof text !== "string") return false;
  // an address parser ignores tabs and line ends anywhere, and spaces and other control characters at both ends
  let clean = "";
  for (let i = 0; i < text.length; i += 1) {
    const code = text.charCodeAt(i);
    if (code !== 0x09 && code !== 0x0a && code !== 0x0d) clean += text[i];
  }
  let start = 0;
  let end = clean.length;
  while (start < end && clean.charCodeAt(start) <= 0x20) start += 1;
  while (end > start && clean.charCodeAt(end - 1) <= 0x20) end -= 1;
  clean = clean.slice(start, end);
  if (clean.length === 0) return false;
  return SCHEME.test(clean) || clean.includes("/") || clean.includes("\\");
}

/** Text without control characters, at most `max` long. The message of an error is only for the visitor to read, and is never turned into markup. */
function cleanText(value, max, what, fail) {
  if (typeof value !== "string") throw fail(`${what} must be text`);
  if (value.length > max) throw fail(`${what} is too long`);
  for (let i = 0; i < value.length; i += 1) {
    if (isControl(value.charCodeAt(i))) throw fail(`${what} has a control character`);
  }
  return value;
}

function cleanKey(key, what, fail) {
  if (key === "__proto__" || key === "constructor" || key === "prototype") throw fail(`${what} has a field that could poison a lookup`);
}

/**
 * A fresh copy of plain data: null, booleans, finite numbers, text, arrays and plain objects, to a depth and a size that are capped. Iterative, with its own
 * stack. The texts and the keys are labels, any text (the model's info is: milp_json.py takes any), and what is checked is the shape: the depth, the size,
 * finite numbers and no key that could poison a lookup.
 */
function cleanData(root, what, fail) {
  const result = { value: undefined };
  const stack = [{ source: root, depth: 0, put: (copy) => (result.value = copy) }];
  let nodes = 0;
  while (stack.length > 0) {
    const { source, depth, put } = stack.pop();
    nodes += 1;
    if (nodes > LIMITS.maxNodes) throw fail(`${what} is too large`);
    if (source === null || typeof source === "boolean" || typeof source === "string") {
      put(source);
    } else if (typeof source === "number") {
      if (!Number.isFinite(source)) throw fail(`${what} has a number that is not finite`);
      put(source);
    } else if (depth >= LIMITS.maxDepth) {
      throw fail(`${what} is nested too deeply`);
    } else if (Array.isArray(source)) {
      if (source.length > LIMITS.maxNodes) throw fail(`${what} is too large`);
      const copy = new Array(source.length).fill(null);
      put(copy);
      for (let index = source.length - 1; index >= 0; index -= 1) {
        stack.push({ source: source[index], depth: depth + 1, put: (item) => (copy[index] = item) });
      }
    } else if (isPlainObject(source)) {
      const copy = Object.create(null);
      put(copy);
      for (const [key, item] of plainEntries(source, (detail) => fail(`${what} ${detail}`))) {
        cleanKey(key, what, fail);
        stack.push({ source: item, depth: depth + 1, put: (value) => (copy[key] = value) });
      }
    } else {
      throw fail(`${what} holds something that is not plain data`);
    }
  }
  return result.value;
}

// ---- lists of numbers -----------------------------------------------------------------------------------------------------------

function listOf(value, length, what, fail) {
  if (!Array.isArray(value)) throw fail(`${what} must be a list`);
  if (length !== undefined && value.length !== length) throw fail(`${what} has ${value.length} entries, not ${length}`);
  return value;
}

function numberList(value, length, what, fail) {
  const list = listOf(value, length, what, fail);
  if (length === undefined && list.length > LIMITS.maxColumns) throw fail(`${what} is too long`);
  const copy = new Array(list.length);
  for (let i = 0; i < list.length; i += 1) {
    const item = list[i];
    if (!isFiniteNumber(item)) throw fail(`${what} has an entry that is not a finite number`);
    copy[i] = item;
  }
  return copy;
}

/** Bounds: finite numbers, or null for an infinite bound (JSON has no infinity). */
function boundList(value, length, what, fail) {
  const list = listOf(value, length, what, fail);
  const copy = new Array(list.length);
  for (let i = 0; i < list.length; i += 1) {
    const item = list[i];
    if (item !== null && !isFiniteNumber(item)) throw fail(`${what} has an entry that is neither a finite number nor null`);
    copy[i] = item;
  }
  return copy;
}

/** A label of the model (a name, the group or the key of an item column): any text. Nothing reads one as anything but a label. */
function labelText(value, what, fail) {
  if (typeof value !== "string") throw fail(`${what} must be text`);
  return value;
}

function nameList(value, length, what, fail) {
  const list = listOf(value, length, what, fail);
  const copy = new Array(list.length);
  for (let i = 0; i < list.length; i += 1) copy[i] = labelText(list[i], what, fail);
  return copy;
}

function checkBounds(lower, upper, what, fail) {
  for (let i = 0; i < lower.length; i += 1) {
    if (lower[i] !== null && upper[i] !== null && lower[i] > upper[i]) throw fail(`${what} has a lower bound above the upper bound`);
  }
}

/// ---- requests -----------------------------------------------------------------------------------------------------------------

/**
 * The model is model JSON v1 as pipeline/trioforge/export/milp_json.py writes it and reads it (`validate` there): these fifteen fields, all
 * of them, and no other. This reader takes the documents that module takes and refuses the ones it refuses; the files of fixtures/milp/ are
 * judged by both (tests-js/milp-fixtures.test.mjs and pipeline/tests/test_milp_fixtures.py), and milp_json.py is the reference.
 *
 *   * Names (of the columns and the rows), the group and the key of an item column and the keys and texts of the info are labels: any text, of
 *     any length, with any character, whatever it looks like (a slash, "slot:", a control character). Nothing here reads a label as anything
 *     but a label. The checks that a text is short, clean and does not look like an address are for the fields of a scenario request.
 *   * What this reader cannot take is refused in milp_json.py too: a buff id beyond ±(2^53 - 1) (the largest whole number that a double holds
 *     exactly), a number that is not finite (a whole number too big for a double reads as Infinity), an info that is not plain data (more
 *     than 8 levels or 100,000 values, or a key that could poison a lookup: __proto__, constructor, prototype), and a model of more than
 *     50,000 columns, 50,000 rows or 1,000,000 entries of the matrix. The fixtures carry these numbers (`limits`), and a test holds the
 *     two files to them.
 *   * Accepted asymmetry. This reader is given a parsed document (the page's own object, or the structured clone of it that the worker
 *     gets), not JSON text, so two things that only the text shows are invisible to it. A whole number written as 1.0 (or -0.0, or 1e2) is the
 *     number 1 once it is parsed, so where milp_json.py refuses a float for a flag, an index, a tier, a buff id or the version, this reader
 *     takes the whole number. And a key written twice in one object is one key by then (the last), where milp_json.loads refuses the text.
 */
const MODEL_KEYS = [
  "version", "sense", "const", "col_names", "col_lb", "col_ub", "integrality", "c", "row_names", "row_lb", "row_ub", "A", "item_cols", "buff_cols", "info",
]; // fmt: skip
const MATRIX_KEYS = ["start", "index", "value"];
/** The highest tier of an item column (MAX_TIER in milp_json.py). */
const MAX_TIER = 10;

/** Names of the columns or the rows: text, none empty, none twice. */
function uniqueNames(value, length, what, fail) {
  const names = nameList(value, length, what, fail);
  const seen = new Set();
  for (const name of names) {
    if (name.length === 0) throw fail(`${what} has an empty name`);
    if (seen.has(name)) throw fail(`${what} has a name that is used twice`);
    seen.add(name);
  }
  return names;
}

/** The columns that count the copies of an item worn in a group: `[[column, group, key, tier], ...]`, no column twice. */
function itemColumns(value, columns, fail) {
  const list = listOf(value, undefined, "the item columns", fail);
  if (list.length > columns) throw fail("the item columns name a column twice");
  const seen = new Set();
  const copy = new Array(list.length);
  for (let i = 0; i < list.length; i += 1) {
    const entry = list[i];
    if (!Array.isArray(entry) || entry.length !== 4) throw fail("an item column is not [column, group, key, tier]");
    const column = entry[0];
    const group = entry[1];
    const key = entry[2];
    const tier = entry[3];
    if (!isWholeNumber(column, 0, columns - 1)) throw fail("an item column names a column that does not exist");
    if (seen.has(column)) throw fail("the item columns name a column twice");
    seen.add(column);
    if (!isWholeNumber(tier, 0, MAX_TIER)) throw fail(`an item column has a tier that is not a whole number from 0 to ${MAX_TIER}`);
    copy[i] = [column, labelText(group, "an item column's group", fail), labelText(key, "an item column's key", fail), tier];
  }
  return copy;
}

/** The columns that choose an optional buff: `[[column, buff id], ...]`, no column twice. */
function buffColumns(value, columns, fail) {
  const list = listOf(value, undefined, "the buff columns", fail);
  if (list.length > columns) throw fail("the buff columns name a column twice");
  const seen = new Set();
  const copy = new Array(list.length);
  for (let i = 0; i < list.length; i += 1) {
    const entry = list[i];
    if (!Array.isArray(entry) || entry.length !== 2) throw fail("a buff column is not [column, buff id]");
    const column = entry[0];
    const id = entry[1];
    if (!isWholeNumber(column, 0, columns - 1)) throw fail("a buff column names a column that does not exist");
    if (seen.has(column)) throw fail("the buff columns name a column twice");
    seen.add(column);
    if (!isWholeNumber(id, Number.MIN_SAFE_INTEGER, Number.MAX_SAFE_INTEGER)) throw fail("a buff column has a buff id that is not a whole number");
    copy[i] = [column, id];
  }
  return copy;
}

/** The model, checked and copied: lengths that agree, a CSR matrix that is well formed (the column indices of a row rise), no yes/no column with a bound that is not whole. */
function checkModel(raw) {
  const fail = badRequest;
  const given = new Map(plainEntries(raw, (detail) => fail(`the model ${detail}`)));
  for (const key of given.keys()) {
    if (!MODEL_KEYS.includes(key)) throw fail(`the model has a field that is not allowed (${safeKey(key)})`);
  }
  for (const key of MODEL_KEYS) {
    if (!given.has(key)) throw fail(`the model has no ${key}`);
  }
  if (given.get("version") !== 1) throw fail("the model is of another version");
  const sense = given.get("sense");
  if (sense !== "max" && sense !== "min") throw fail("the model's sense is neither max nor min");
  const constant = given.get("const");
  if (!isFiniteNumber(constant)) throw fail("the model's constant is not a finite number");

  const costs = given.get("c");
  if (!Array.isArray(costs) || costs.length > LIMITS.maxColumns) throw fail("the model has no list of costs or too many columns");
  const columns = costs.length;
  const model = { version: 1, sense, const: constant };
  model.col_names = uniqueNames(given.get("col_names"), columns, "the column names", fail);
  model.col_lb = boundList(given.get("col_lb"), columns, "the column lower bounds", fail);
  model.col_ub = boundList(given.get("col_ub"), columns, "the column upper bounds", fail);
  checkBounds(model.col_lb, model.col_ub, "a column", fail);
  const flags = listOf(given.get("integrality"), columns, "the integrality flags", fail);
  model.integrality = new Array(columns);
  for (let j = 0; j < columns; j += 1) {
    const flag = flags[j];
    if (flag !== 0 && flag !== 1) throw fail("an integrality flag is neither 0 nor 1");
    model.integrality[j] = flag;
  }
  // A yes/no or whole-number column with a bound like 2.5 gets a wrong answer that the solver calls optimal (HiGHS with the presolve off, as it
  // runs here), so such a model is refused and not rounded: rounding would only move the error to whoever rounds. milp_json.validate refuses it too.
  for (let j = 0; j < columns; j += 1) {
    if (model.integrality[j] !== 1) continue;
    for (const bound of [model.col_lb[j], model.col_ub[j]]) {
      if (bound !== null && !Number.isInteger(bound)) throw fail(`the integer column ${j} has a bound that is not a whole number`);
    }
  }
  model.c = numberList(costs, columns, "the costs", fail);

  const rowLower = given.get("row_lb");
  if (!Array.isArray(rowLower) || rowLower.length > LIMITS.maxRows) throw fail("the model has no row bounds or too many rows");
  const rows = rowLower.length;
  model.row_names = uniqueNames(given.get("row_names"), rows, "the row names", fail);
  model.row_lb = boundList(rowLower, rows, "the row lower bounds", fail);
  model.row_ub = boundList(given.get("row_ub"), rows, "the row upper bounds", fail);
  checkBounds(model.row_lb, model.row_ub, "a row", fail);

  const matrix = new Map(plainEntries(given.get("A"), (detail) => fail(`the matrix ${detail}`)));
  for (const key of matrix.keys()) {
    if (!MATRIX_KEYS.includes(key)) throw fail(`the matrix has a field that is not allowed (${safeKey(key)})`);
  }
  for (const key of MATRIX_KEYS) {
    if (!matrix.has(key)) throw fail(`the matrix has no ${key}`);
  }
  const start = listOf(matrix.get("start"), rows + 1, "the matrix starts", fail);
  const copyStart = new Array(rows + 1);
  let previous = 0;
  for (let r = 0; r <= rows; r += 1) {
    const at = start[r];
    if (!isWholeNumber(at, 0, LIMITS.maxNonzeros)) throw fail("a matrix start is not a whole number in range");
    if (r === 0 && at !== 0) throw fail("the matrix starts do not begin at 0");
    if (at < previous) throw fail("the matrix starts go down");
    copyStart[r] = at;
    previous = at;
  }
  const entries = copyStart[rows];
  const index = listOf(matrix.get("index"), entries, "the matrix column indices", fail);
  const value = listOf(matrix.get("value"), entries, "the matrix values", fail);
  const copyIndex = new Array(entries);
  const copyValue = new Array(entries);
  for (let r = 0; r < rows; r += 1) {
    let before = -1;
    for (let k = copyStart[r]; k < copyStart[r + 1]; k += 1) {
      const column = index[k];
      const coefficient = value[k];
      if (!isWholeNumber(column, 0, columns - 1)) throw fail("a matrix column index is out of range");
      if (!isFiniteNumber(coefficient)) throw fail("a matrix value is not a finite number");
      if (column <= before) throw fail(column === before ? "a row names the same column twice" : "the column indices of a row do not rise");
      before = column;
      copyIndex[k] = column;
      copyValue[k] = coefficient;
    }
  }
  model.A = { start: copyStart, index: copyIndex, value: copyValue };
  model.item_cols = itemColumns(given.get("item_cols"), columns, fail);
  model.buff_cols = buffColumns(given.get("buff_cols"), columns, fail);
  const info = given.get("info");
  if (!isPlainObject(info)) throw fail("the model's info must be a plain object");
  model.info = cleanData(info, "the model's info", fail);
  return model;
}

const TRIO_CODE = /^[a-z]{3}-[a-z]{3}-[a-z]{3}$/;
const COMMON_KEYS = ["v", "kind", "budgetMs"];
const MODEL_REQUEST_KEYS = new Set([...COMMON_KEYS, "model"]);

// ---- the scenario modes: the requests -----------------------------------------------------------------------------------------

/** The modes of a scenario request: these five, and no other. */
export const EQUIP_NOW = "equip-now";
export const FARM_PATH = "farm-path";
export const BEST_SETS = "best-sets";
export const EVERY_SLOT = "every-slot";
export const BEST_KIT = "best-kit";
export const SCENARIO_MODES = Object.freeze([EQUIP_NOW, FARM_PATH, BEST_SETS, EVERY_SLOT, BEST_KIT]);
/**
 * What a request of each mode has besides `v`, `kind`, `budgetMs`, `trio`, `level` and `mode`: its allowlist, and which of the fields it must have (the limit of
 * Every slot has a default). A Map, so that no name a request gives finds a member of a prototype. A request carries no candidates: the worker makes them from the
 * tier mode.
 */
const MODE_FIELDS = new Map([
  [EQUIP_NOW, { allowed: ["scenario", "owned", "weights"], required: ["scenario", "owned"] }],
  [FARM_PATH, { allowed: ["scenario", "owned", "tierMode", "steps", "weights"], required: ["scenario", "owned", "tierMode", "steps"] }],
  [BEST_SETS, { allowed: ["scenario", "owned", "tierMode", "k", "weights"], required: ["scenario", "owned", "tierMode", "k"] }],
  [EVERY_SLOT, { allowed: ["scenario", "owned", "tierMode", "kit", "buffs", "limit", "weights"], required: ["scenario", "owned", "tierMode", "kit", "buffs"] }],
  // the best kit has no owned set and no tier mode: the pool is the view's. Lock and exclude will be fields of its own (and checked here as the other fields are).
  [BEST_KIT, { allowed: ["scenario", "tier", "weights", "options"], required: ["scenario", "tier"] }],
]);
/** The highest difficulty of the tier mode `arrives`, the sizes of a best set, and the swaps of a place in Every slot when the request does not say. */
const MAX_DIFFICULTY = 4;
const BEST_SET_SIZES = [2, 3];
const DEFAULT_SWAPS = 3;
/** The choices of a scenario, in the order they are copied, and the one that is optional. */
const SCENARIO_FIELDS = ["race", "role", "buffs", "evidence", "setup", "deity"];
/** A short name: race codes, role names, the buff sets (with a plus sign), evidence levels, the weapon setups (with a hyphen), deities (with a space). */
const SHORT_NAME = /^[A-Za-z0-9][A-Za-z0-9 +._-]*$/;
/** The key of an item of the table (the pattern of the catalog's schema and of site/data.py), and an ident: the key, @, and a tier from 0 to 10. */
// (the key of the item table, items.js: a page id has no zero in front, so that w07 is not another way of writing w7)
const ITEM_KEY = "(?:w[1-9][0-9]{0,14}|r[a-z0-9][a-z0-9-]{0,99})";
const ITEM_IDENT = new RegExp(`^${ITEM_KEY}@(?:0|[1-9]|10)$`);
const MAX_IDENT_LENGTH = 110;
/** The 22 places of a kit. */
const KIT_PLACES = 22;

/** Whether a value is an ident of an item at a tier, `key@tier`. */
export const isItemIdent = (value) => typeof value === "string" && value.length <= MAX_IDENT_LENGTH && ITEM_IDENT.test(value);

/**
 * The items of a list that is plain data: a list, within the length given, whose every entry is an own data property (a hole or an accessor is refused,
 * and nothing is called). The entries are read once each.
 */
function plainList(value, what, max) {
  if (!Array.isArray(value)) throw badRequest(`${what} must be a list`);
  if (value.length > max) throw badRequest(`${what} is too long`);
  const items = new Array(value.length);
  for (let at = 0; at < value.length; at += 1) {
    const descriptor = Object.getOwnPropertyDescriptor(value, at);
    if (descriptor === undefined || !("value" in descriptor)) throw badRequest(`${what} has a hole in it, or an entry that is not plain data`);
    items[at] = descriptor.value;
  }
  return items;
}

/** A short name: text of one sign to `maxNameLength`, made of plain signs (letters, digits, space, plus, point, underscore, hyphen) and not beginning with a sign. */
function shortName(value, what) {
  if (typeof value !== "string" || value.length === 0 || value.length > LIMITS.maxNameLength || !SHORT_NAME.test(value)) {
    throw badRequest(`${what} must be a short name of plain letters and digits`);
  }
  return value;
}

/** The scenario of a request: exactly the five choices and, if given, the deity (a short name, or null). A fresh object. */
function checkScenario(raw) {
  const given = new Map(plainEntries(raw, (detail) => badRequest(`the scenario ${detail}`)));
  for (const key of given.keys()) {
    if (!SCENARIO_FIELDS.includes(key)) throw badRequest(`the scenario has a field that is not allowed (${safeKey(key)})`);
  }
  const scenario = {};
  for (const field of SCENARIO_FIELDS) {
    if (!given.has(field)) {
      if (field === "deity") continue;
      throw badRequest(`the scenario has no ${field}`);
    }
    const value = given.get(field);
    scenario[field] = field === "deity" && value === null ? null : shortName(value, `the scenario's ${field}`);
  }
  return scenario;
}

/** The owned set of a scenario request: `[[ident, count], ...]`, at most 1,000 entries, counts from 1 to 99, no ident twice. A fresh list of fresh pairs. */
function checkOwned(raw) {
  const entries = plainList(raw, "the owned set", LIMITS.maxOwnedEntries);
  const seen = new Set();
  return entries.map((entry) => {
    const pair = plainList(entry, "an owned entry", 2);
    if (pair.length !== 2) throw badRequest("an owned entry is an ident and a count");
    const [ident, count] = pair;
    if (!isItemIdent(ident)) throw badRequest("an owned entry does not name an item by an ident of the form key@tier (a tier from 0 to 10)");
    if (!isWholeNumber(count, 1, LIMITS.maxOwnedCount)) throw badRequest(`the count of an owned item is a whole number from 1 to ${LIMITS.maxOwnedCount}`);
    if (seen.has(ident)) throw badRequest("the owned set names an item twice");
    seen.add(ident);
    return [ident, count];
  });
}

/**
 * The tier mode of a request: `{mode: "ready4"}`, `{mode: "arrives", D}` (D a whole number from 0 to 4) or `{mode: "fixed", N}` (N a whole number from 0 to 10),
 * exactly those fields. A fresh object.
 */
function checkTierMode(raw) {
  const given = new Map(plainEntries(raw, (detail) => badRequest(`the tier mode ${detail}`)));
  const mode = given.get("mode");
  const field = mode === "arrives" ? "D" : mode === "fixed" ? "N" : undefined;
  if (mode !== "ready4" && field === undefined) throw badRequest("the tier mode is ready4, arrives or fixed");
  for (const key of given.keys()) {
    if (key !== "mode" && key !== field) throw badRequest(`the tier mode has a field that is not allowed (${safeKey(key)})`);
  }
  const copy = { mode };
  if (field !== undefined) {
    const highest = field === "D" ? MAX_DIFFICULTY : MAX_TIER;
    if (!given.has(field)) throw badRequest(`the tier mode ${mode} has no ${field}`);
    if (!isWholeNumber(given.get(field), 0, highest)) throw badRequest(`the ${field} of the tier mode is a whole number from 0 to ${highest}`);
    copy[field] = given.get(field);
  }
  return copy;
}

/** The steps of a farm path: a whole number from 1 to 8. */
function checkSteps(value) {
  if (!isWholeNumber(value, 1, LIMITS.maxPathSteps)) throw badRequest(`the steps of a path are a whole number from 1 to ${LIMITS.maxPathSteps}`);
  return value;
}

/** The size of a best set: 2 or 3 (a set of one addition is the first step of the path). */
function checkK(value) {
  if (!BEST_SET_SIZES.includes(value)) throw badRequest(`k is ${BEST_SET_SIZES.join(" or ")}`);
  return value;
}

/** The kit of an Every slot request: exactly 22 places, each an ident or empty. A fresh list. */
function checkKit(raw) {
  const places = plainList(raw, "the kit", KIT_PLACES);
  if (places.length !== KIT_PLACES) throw badRequest(`the kit has ${KIT_PLACES} places`);
  for (const place of places) {
    if (place !== null && !isItemIdent(place)) throw badRequest("a place of the kit is neither empty nor an item ident of the form key@tier");
  }
  return places;
}

/** The buffs of an Every slot request: whole numbers from 0, rising (none twice), at most as many as a result may name. A fresh list. */
function checkBuffIds(raw) {
  const ids = plainList(raw, "the buffs", LIMITS.maxBuffs);
  ids.forEach((id, at) => {
    if (!isWholeNumber(id, 0, Number.MAX_SAFE_INTEGER)) throw badRequest("a buff is the id of a buff, a whole number from 0");
    if (at > 0 && id <= ids[at - 1]) throw badRequest("the buffs are not in rising order, once each");
  });
  return ids;
}

/** The swaps of each place in Every slot: a whole number from 1 to 10. */
function checkLimit(value) {
  if (!isWholeNumber(value, 1, LIMITS.maxSwaps)) throw badRequest(`the limit of swaps is a whole number from 1 to ${LIMITS.maxSwaps}`);
  return value;
}

/** The tier of the pool of a best kit: a whole number from 0 to 10. */
function checkTier(value) {
  if (!isWholeNumber(value, 0, MAX_TIER)) throw badRequest(`the tier is a whole number from 0 to ${MAX_TIER}`);
  return value;
}

/** The options of the weights of a request, in the order they are copied. */
const WEIGHT_OPTIONS = ["multipliers", "custom", "regenT"];

/**
 * The finest numbers the weights of a request may carry. A weight is read as the decimal it prints as, so the digits of the weights set the size of the exact value of the answer,
 * a fraction p/q that the page reads only up to `LIMITS.maxExactLength` characters: a custom weight of 5e-324 makes it 657 characters, and a regen window of 1e-100 209. A slider
 * position, a custom weight and the regen window are therefore zero, or at least `WEIGHT_FLOOR` in size and of at most `WEIGHT_DIGITS` significant digits. (With them the longest exact
 * value that fourteen custom weights, five sliders and a window can make is some 40 characters.) The groups, the positions and the largest weight are the bundle's, and not these.
 */
export const WEIGHT_FLOOR = 1e-6;
export const WEIGHT_DIGITS = 6;

/** Whether a finite number may be in the weights of a request: zero, or at least `WEIGHT_FLOOR` in size and with at most `WEIGHT_DIGITS` significant digits (as it prints). */
export function isLegalWeightNumber(value) {
  if (value === 0) return true;
  return Math.abs(value) >= WEIGHT_FLOOR && Number(value.toPrecision(WEIGHT_DIGITS)) === value;
}

/** A number of the weights: finite, and one that `isLegalWeightNumber` takes. */
function weightNumber(value, what) {
  if (!isFiniteNumber(value)) throw badRequest(`${what} hold a number that is not finite`);
  if (!isLegalWeightNumber(value)) throw badRequest(`${what} hold a number that is neither zero nor at least ${WEIGHT_FLOOR} in size with at most ${WEIGHT_DIGITS} significant digits`);
  return value;
}

/**
 * A table of the weights of a request, the slider positions by group or the custom weights by name: a plain object of at most `LIMITS.maxWeightEntries` entries, each a short name
 * (not a word that could poison a lookup) and a number that is zero or neither too small nor too fine (`isLegalWeightNumber`). A fresh object that has no prototype. Which names there
 * are and which numbers they may have is the bundle's, and the worker holds the table to it (weightsOverride).
 */
function checkWeightTable(raw, what) {
  const entries = plainEntries(raw, (detail) => badRequest(`the ${what} ${detail}`));
  if (entries.length > LIMITS.maxWeightEntries) throw badRequest(`the ${what} have too many entries`);
  const table = Object.create(null);
  for (const [name, value] of entries) {
    cleanKey(name, `the ${what}`, badRequest);
    shortName(name, `a name in the ${what}`);
    table[name] = weightNumber(value, `the ${what}`);
  }
  return table;
}

/**
 * The weights of a request: `{multipliers?, custom?, regenT?}`, exactly the options of `weightsOverride` that a page may set (whether the trio has a mana pool is not one: the worker
 * says that), each only if the request has it. `regenT` is a number of minutes (`isLegalWeightNumber`), or null for the role's own. A fresh object.
 */
function checkWeights(raw) {
  const given = new Map(plainEntries(raw, (detail) => badRequest(`the weights ${detail}`)));
  for (const key of given.keys()) {
    if (!WEIGHT_OPTIONS.includes(key)) throw badRequest(`the weights have an option that is not allowed (${safeKey(key)})`);
  }
  const weights = {};
  if (given.has("multipliers")) weights.multipliers = checkWeightTable(given.get("multipliers"), "multipliers");
  if (given.has("custom")) weights.custom = checkWeightTable(given.get("custom"), "custom weights");
  if (given.has("regenT")) {
    const minutes = given.get("regenT");
    if (minutes !== null && !isFiniteNumber(minutes)) throw badRequest("the regen window is a number of minutes, or null");
    weights.regenT = minutes === null ? null : weightNumber(minutes, "the regen window");
  }
  return weights;
}

/** The weapon tier rates a best kit may name: the percent of damage a weapon grows a tier. The rules know these two (`tier.weapon_damage_pct` and its alternative). */
export const WEAPON_TIER_RATES = Object.freeze([5, 10]);
/** The options of a best kit, in the order they are copied. */
const BEST_KIT_OPTIONS = ["weaponTierRate"];

/** The options of a best kit: `{weaponTierRate?}`, each only if the request has it, and a rate of `WEAPON_TIER_RATES`. A fresh object. */
function checkOptions(raw) {
  const given = new Map(plainEntries(raw, (detail) => badRequest(`the options ${detail}`)));
  for (const key of given.keys()) {
    if (!BEST_KIT_OPTIONS.includes(key)) throw badRequest(`the options have an option that is not allowed (${safeKey(key)})`);
  }
  const options = {};
  if (given.has("weaponTierRate")) {
    const rate = given.get("weaponTierRate");
    if (!WEAPON_TIER_RATES.includes(rate)) throw badRequest(`the weapon tier rate is ${WEAPON_TIER_RATES.join(" or ")} percent a tier`);
    options.weaponTierRate = rate;
  }
  return options;
}

/** A request is for a trio and a level the manifest lists. */
export function checkAgainstManifest(request, manifest) {
  if (request.kind !== "scenario") return;
  const entry = manifest.trios.get(request.trio);
  if (entry === undefined) throw badRequest("the manifest does not list this trio");
  if (!entry.levels.includes(request.level)) throw badRequest("the manifest does not list this level for the trio");
}

/**
 * Check a request and return a copy of it. With the manifest, a scenario's trio and level must be listed in it. Throws a ProtocolError
 * with the code bad-request.
 */
export function validateRequest(raw, manifest) {
  const given = new Map(plainEntries(raw, (detail) => badRequest(`the request ${detail}`)));
  if (given.get("v") !== PROTOCOL_VERSION) throw badRequest("the request is of another version");
  const kind = given.get("kind");
  const mode = given.get("mode");
  let allowed;
  let fields;
  if (kind === "model") {
    allowed = MODEL_REQUEST_KEYS;
  } else if (kind === "scenario") {
    fields = typeof mode === "string" ? MODE_FIELDS.get(mode) : undefined;
    if (fields === undefined) throw badRequest("the request names no mode that the optimizer answers");
    allowed = new Set([...COMMON_KEYS, "trio", "level", "mode", ...fields.allowed]);
  } else {
    throw badRequest("the request is of an unknown kind");
  }
  for (const key of given.keys()) {
    if (!allowed.has(key)) throw badRequest(`the request has a field that is not allowed (${safeKey(key)})`);
  }
  const budgetMs = given.get("budgetMs");
  if (!isWholeNumber(budgetMs, 1, LIMITS.maxBudgetMs)) throw badRequest("the request's budget is not a whole number of milliseconds in range");
  const request = { v: PROTOCOL_VERSION, kind };
  if (kind === "model") {
    request.model = checkModel(given.get("model"));
  } else {
    const trio = given.get("trio");
    if (typeof trio !== "string" || !TRIO_CODE.test(trio)) throw badRequest("the request names no trio");
    const level = given.get("level");
    if (!isWholeNumber(level, 1, LIMITS.maxLevel)) throw badRequest("the request names no level");
    for (const field of fields.required) {
      if (!given.has(field)) throw badRequest(`a ${mode} request has no ${field}`);
    }
    request.trio = trio;
    request.level = level;
    request.mode = mode;
    request.scenario = checkScenario(given.get("scenario"));
    if (given.has("weights")) request.weights = checkWeights(given.get("weights")); // (the same for every mode: only the fields that the mode allows got this far)
    if (mode === BEST_KIT) {
      request.tier = checkTier(given.get("tier"));
      if (given.has("options")) request.options = checkOptions(given.get("options"));
    } else {
      request.owned = checkOwned(given.get("owned"));
    }
    if (mode !== EQUIP_NOW && mode !== BEST_KIT) request.tierMode = checkTierMode(given.get("tierMode"));
    if (mode === FARM_PATH) request.steps = checkSteps(given.get("steps"));
    if (mode === BEST_SETS) request.k = checkK(given.get("k"));
    if (mode === EVERY_SLOT) {
      request.kit = checkKit(given.get("kit"));
      request.buffs = checkBuffIds(given.get("buffs"));
      request.limit = given.has("limit") ? checkLimit(given.get("limit")) : DEFAULT_SWAPS;
    }
  }
  request.budgetMs = budgetMs;
  if (manifest !== undefined) checkAgainstManifest(request, manifest);
  return request;
}

// ---- messages to the worker ---------------------------------------------------------------------------------------------------

export function isCompiledModule(value) {
  return typeof WebAssembly === "object" && typeof WebAssembly.Module === "function" && value instanceof WebAssembly.Module;
}

/** Check a message the worker received; returns a copy. Throws a ProtocolError with the code bad-request. */
export function validateToWorker(data) {
  const given = new Map(plainEntries(data, (detail) => badRequest(`the message ${detail}`)));
  if (given.get("v") !== PROTOCOL_VERSION) throw badRequest("the message is of another version");
  const type = given.get("type");
  if (type === "init") {
    for (const key of given.keys()) {
      if (key !== "v" && key !== "type" && key !== "module") throw badRequest(`the init message has a field that is not allowed (${safeKey(key)})`);
    }
    const message = { v: PROTOCOL_VERSION, type };
    const module = given.get("module");
    if (module !== undefined) {
      if (!isCompiledModule(module)) throw badRequest("the module is not a compiled WebAssembly module");
      message.module = module;
    }
    return message;
  }
  if (type === "ping") {
    for (const key of given.keys()) {
      if (key !== "v" && key !== "type") throw badRequest(`the ping has a field that is not allowed (${safeKey(key)})`);
    }
    return { v: PROTOCOL_VERSION, type };
  }
  if (type === "stop") {
    for (const key of given.keys()) {
      if (key !== "v" && key !== "type" && key !== "id") throw badRequest(`the stop message has a field that is not allowed (${safeKey(key)})`);
    }
    const id = given.get("id");
    if (!isWholeNumber(id, 1, LIMITS.maxId)) throw badRequest("the stop message has no usable id");
    return { v: PROTOCOL_VERSION, type, id };
  }
  if (type === "solve") {
    for (const key of given.keys()) {
      if (key !== "v" && key !== "type" && key !== "id" && key !== "request") throw badRequest(`the solve message has a field that is not allowed (${safeKey(key)})`);
    }
    const id = given.get("id");
    if (!isWholeNumber(id, 1, LIMITS.maxId)) throw badRequest("the solve message has no usable id");
    return { v: PROTOCOL_VERSION, type, id, request: validateRequest(given.get("request")) };
  }
  throw badRequest("the message is of an unknown type");
}

// ---- messages from the worker -------------------------------------------------------------------------------------------------

const HIGHS_VERSION = /^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$/;
const PROGRESS_KEYS = new Set(["v", "type", "id", "phase", "stage", "step", "loaded", "total", "elapsedMs", "objective", "bound", "gap", "nodes"]);
const RESULT_KEYS = ["v", "type", "id", "kind", "status", "proven", "objective", "x", "bound", "gap", "nodes", "elapsedMs", "label"];

/** The stages of the progress of a scenario request, and the ones that each mode goes through. */
export const STAGES = Object.freeze(["loading", "equip-now", "step", "best-sets", "every-slot", "best-kit"]);
const STAGES_OF = new Map([
  [EQUIP_NOW, ["loading", "equip-now"]],
  [FARM_PATH, ["loading", "equip-now", "step"]],
  [BEST_SETS, ["loading", "best-sets"]],
  [EVERY_SLOT, ["loading", "every-slot"]],
  [BEST_KIT, ["loading", "best-kit"]],
]);

function checkKeys(given, allowed, required, what) {
  for (const key of given.keys()) {
    if (!allowed.has(key)) throw badReply(`${what} has a field that is not allowed (${safeKey(key)})`);
  }
  for (const key of required) {
    if (!given.has(key)) throw badReply(`${what} has no ${key}`);
  }
}

/** An object of exactly these fields, as a Map of its own entries. */
function exactFields(raw, keys, what) {
  const given = new Map(plainEntries(raw, (detail) => badReply(`${what} ${detail}`)));
  checkKeys(given, new Set(keys), keys, what);
  return given;
}

const nullOr = (value, test) => value === null || test(value);

// ---- an answer: what Equip now, a step of the path and a best set have in common ------------------------------------------------

/** The most percent of haste a profile can assume (the caps are the cap of the level, 75 at level 50 and 100 from level 60, and 10 more with a Monk; 1,000 is the size of a total of the shards). */
const MAX_HASTE = 1000;
/** The most experience and the most copies that reaching a tier costs: 2^10 - 1 from +0 to +10. */
const MAX_EXPERIENCE = 1023;
const KINDS = ["new", "copy", "upgrade"];
/** The highest tier an item arrives at (no fresh drop has been seen above +4): the copies of a cost are counted from there at the lowest. */
const MAX_ARRIVAL = 4;
/** The tier of the tier mode `ready4`. */
const READY_TIER = 4;

/**
 * Whether the tier mode of the request gives an item `tier` (tiers.js `tierForMode`): `ready4` scores every item at +4, `fixed` at +N, and `arrives` at +D for an item that
 * drops and +0 for any other. The page does not know which an item is, so under `arrives` the tier is one of the two.
 */
function tierFits(tierMode, tier) {
  if (tierMode.mode === "ready4") return tier === READY_TIER;
  if (tierMode.mode === "fixed") return tier === tierMode.N;
  return tier === 0 || tier === tierMode.D;
}

/** The idents the request owned, with their counts, from the expectation (a list of pairs, or a Map); undefined when the expectation says nothing. */
function ownedOf(owned) {
  if (owned === undefined) return undefined;
  const counts = new Map(owned instanceof Map ? owned : owned.map((entry) => [entry[0], entry[1]]));
  return counts;
}

/** The key and the tier of an ident that `isItemIdent` took. */
function splitIdent(ident) {
  const at = ident.lastIndexOf("@");
  return { key: ident.slice(0, at), tier: Number(ident.slice(at + 1)) };
}

/** Whether the ident `a` comes before `b` in the order of the engine: by key, then by tier (the keys are plain ASCII, so a comparison of texts is the one of code points). */
function identBefore(a, b) {
  const left = splitIdent(a);
  const right = splitIdent(b);
  return left.key === right.key ? left.tier < right.tier : left.key < right.key;
}

/** A list of data that holds no hole and no accessor, at most `max` long, copied. The entries are read once each. */
function denseList(value, what, max) {
  if (!Array.isArray(value)) throw badReply(`${what} must be a list`);
  if (value.length > max) throw badReply(`${what} is too long`);
  const items = new Array(value.length);
  for (let at = 0; at < value.length; at += 1) {
    const descriptor = Object.getOwnPropertyDescriptor(value, at);
    if (descriptor === undefined || !("value" in descriptor)) throw badReply(`${what} has a hole in it, or an entry that is not plain data`);
    items[at] = descriptor.value;
  }
  return items;
}

/** The 22 places of a kit as idents (or null for an empty place), or no kit at all; `worn` counts how many of each ident the kit wears. */
function readKit(rawKit) {
  if (rawKit === null) return { kit: null, worn: new Map() };
  if (!Array.isArray(rawKit) || rawKit.length !== KIT_PLACES) throw badReply(`the kit has ${KIT_PLACES} places, or is null`);
  const kit = new Array(KIT_PLACES);
  const worn = new Map();
  for (let place = 0; place < KIT_PLACES; place += 1) {
    const descriptor = Object.getOwnPropertyDescriptor(rawKit, place);
    if (descriptor === undefined || !("value" in descriptor)) throw badReply("the kit has a hole in it");
    const ident = descriptor.value;
    if (ident !== null && !isItemIdent(ident)) throw badReply("the kit has a place that is neither empty nor an item ident");
    kit[place] = ident;
    if (ident !== null) worn.set(ident, (worn.get(ident) ?? 0) + 1);
  }
  return { kit, worn };
}

/** No item is worn more often than `available` (a Map from ident to count) has copies of it. */
function checkWorn(worn, available, message) {
  for (const [ident, times] of worn) {
    if ((available.get(ident) ?? 0) < times) throw badReply(message);
  }
}

/** An exact value as a reduced p/q text and the number it rounds to (the number beside it must be that number): `{text, number, rational}`. */
function readExact(rawExact, rawNumber, what) {
  if (typeof rawExact !== "string" || rawExact.length > LIMITS.maxExactLength) throw badReply(`${what} is not a reduced rational p/q`);
  let rational;
  let number;
  try {
    rational = Rational.parseLong(rawExact);
    number = rational.toNumber();
  } catch (error) {
    if (!(error instanceof RationalError)) throw error;
    throw badReply(`${what} is not a reduced rational p/q`);
  }
  if (rawNumber !== number) throw badReply(`the number beside ${what} is not ${what} rounded`);
  return { text: rawExact, number, rational };
}

/** What each status must look like: a result cannot claim more than the solver found. */
function checkStatus(status, proven, label, kit) {
  if (status === "optimal") {
    if (proven !== true || kit === null || label !== null) throw badReply("an optimal result must be proven, with a kit and no label");
  } else if (status === "infeasible") {
    if (proven !== true || kit !== null || label !== null) throw badReply("an infeasible result must be proven, with no kit and no label");
  } else {
    if (proven !== false) throw badReply("a time-limited result is never proven");
    if (label !== (kit === null ? LABEL_NO_INCUMBENT : LABEL_TIME_LIMIT)) throw badReply("a time-limited result must carry its honest label");
  }
}

/** The optional buffs chosen: whole numbers, in rising order, and none when there is no kit. */
function readBuffs(rawBuffs, kit) {
  if (!Array.isArray(rawBuffs) || rawBuffs.length > LIMITS.maxBuffs) throw badReply("the buffs are a list");
  const buffs = new Array(rawBuffs.length);
  for (let at = 0; at < rawBuffs.length; at += 1) {
    const descriptor = Object.getOwnPropertyDescriptor(rawBuffs, at);
    if (descriptor === undefined || !("value" in descriptor) || !Number.isSafeInteger(descriptor.value)) throw badReply("a buff is the id of a buff, a whole number");
    if (at > 0 && descriptor.value <= buffs[at - 1]) throw badReply("the buffs are not in rising order, once each");
    buffs[at] = descriptor.value;
  }
  if (kit === null && buffs.length > 0) throw badReply("a result with no kit chose no buffs");
  return buffs;
}

const readElapsed = (given) => {
  const elapsedMs = given.get("elapsedMs");
  if (!isFiniteNumber(elapsedMs) || elapsedMs < 0) throw badReply("the elapsed time is not a number from 0 up");
  return elapsedMs;
};

/**
 * What an answer is, whatever asked for it: `status`, `proven`, `label`, the `kit` (22 places, or none), its exact value `F` and its number `value`, the `buffs` and
 * the `hasteAssumed`, checked together. `available` (a Map from ident to count) says what the kit may wear; none says that nothing is checked of it here.
 */
function readAnswer(given, available, wearMessage) {
  const status = given.get("status");
  if (!STATUSES.has(status)) throw badReply("the result has an unknown status");
  const proven = given.get("proven");
  if (typeof proven !== "boolean") throw badReply("the result does not say whether it is proven");
  const label = given.get("label");
  if (label !== null && typeof label !== "string") throw badReply("the label is not text or null");
  // the kit: 22 places, each an ident or null, and no item worn more often than there are copies of it
  const { kit, worn } = readKit(given.get("kit"));
  if (available !== undefined) checkWorn(worn, available, wearMessage);
  // the exact value as a reduced p/q text, and the number it rounds to
  const rawExact = given.get("F");
  const rawValue = given.get("value");
  if ((rawExact === null) !== (kit === null) || (rawValue === null) !== (kit === null)) throw badReply("the kit, its exact value and its number come together or not at all");
  const exact = kit === null ? null : readExact(rawExact, rawValue, "the exact value");
  checkStatus(status, proven, label, kit);
  const buffs = readBuffs(given.get("buffs"), kit);
  const hasteAssumed = given.get("hasteAssumed");
  if (!isWholeNumber(hasteAssumed, 0, MAX_HASTE)) throw badReply("the assumed haste is not a whole number of percent in range");
  return { status, proven, label, kit, worn, exact, buffs, hasteAssumed };
}

/** The fields of an answer as the message carries them. */
const answerFields = (answer) => ({
  status: answer.status,
  proven: answer.proven,
  label: answer.label,
  F: answer.exact === null ? null : answer.exact.text,
  value: answer.exact === null ? null : answer.exact.number,
  kit: answer.kit,
  buffs: answer.buffs,
  hasteAssumed: answer.hasteAssumed,
});

// ---- what an addition costs and what it is --------------------------------------------------------------------------------------

/**
 * What reaching the tier of an acquired item costs: null (the tier mode scores the item below the tier it arrives at, so there is nothing to bring it up to), or
 * `{exp, copiesAtArrival, potentials}` that agree with each other and with the tier: tier N needs 2^N - 1 experience in all, so from a tier M to N it needs
 * 2^N - 2^M, and `potentials` is N - M; the copies that arrive at +k (0 to 4) give 2^k each, so they are at most the experience and at least a sixteenth of it, rounded
 * up. An upgrade is made from the tier it names and always costs something.
 */
function readCost(raw, tier, kind, sourceTier) {
  if (raw === null) {
    if (kind === "upgrade") throw badReply("an upgrade has a cost");
    return null;
  }
  const given = exactFields(raw, ["exp", "copiesAtArrival", "potentials"], "a cost");
  const exp = given.get("exp");
  const copies = given.get("copiesAtArrival");
  const potentials = given.get("potentials");
  if (!isWholeNumber(exp, 0, MAX_EXPERIENCE) || !isWholeNumber(copies, 0, MAX_EXPERIENCE) || !isWholeNumber(potentials, 0, tier)) throw badReply("a cost has numbers out of range");
  const from = tier - potentials;
  if (exp !== 2 ** tier - 2 ** from) throw badReply("the experience of a cost is not what reaching the tier needs");
  if (kind === "upgrade" ? from !== sourceTier : from > MAX_ARRIVAL) throw badReply("a cost is not counted from the tier the item is brought from");
  if (copies > exp || copies < Math.ceil(exp / 2 ** MAX_ARRIVAL)) throw badReply("the copies of a cost do not supply its experience");
  return { exp: given.get("exp"), copiesAtArrival: copies, potentials };
}

/**
 * What is acquired: an ident, its kind, the tier an upgrade is made from (null for the others) and what reaching the tier costs. When the tier mode of the request is known
 * (`tierMode`) the item is at the tier that mode gives: a candidate is read at that tier, and so is what is acquired.
 */
function readAcquisition(ident, kind, sourceTier, cost, tierMode) {
  if (!isItemIdent(ident)) throw badReply("an acquisition does not name an item by an ident of the form key@tier");
  if (!KINDS.includes(kind)) throw badReply("an acquisition is a new item, a copy or an upgrade");
  const { tier } = splitIdent(ident);
  if (tierMode !== undefined && !tierFits(tierMode, tier)) throw badReply("an acquisition is at a tier that the tier mode of the request does not give");
  if (kind === "upgrade" ? !isWholeNumber(sourceTier, 0, tier - 1) : sourceTier !== null) throw badReply("an upgrade is made from a tier below its own, and nothing else is");
  return { ident, kind, sourceTier, cost: readCost(cost, tier, kind, sourceTier) };
}

/** The ident of the copy an upgrade is made from. */
const sourceOf = (acquisition) => `${splitIdent(acquisition.ident).key}@${acquisition.sourceTier}`;

/**
 * The copies there are after the acquisitions: what was owned, one more of each item acquired, and one less of the copy that each upgrade is made from. No count
 * may go below 0. Returns a new Map.
 */
function afterAcquiring(available, acquisitions) {
  const copies = new Map(available);
  for (const acquisition of acquisitions) copies.set(acquisition.ident, (copies.get(acquisition.ident) ?? 0) + 1);
  for (const acquisition of acquisitions) {
    if (acquisition.kind !== "upgrade") continue;
    const source = sourceOf(acquisition);
    copies.set(source, (copies.get(source) ?? 0) - 1);
    if (copies.get(source) < 0) throw badReply("an upgrade is made from a copy that was not owned");
  }
  return copies;
}

const KIT_WEAR_MESSAGE = "the kit wears an item that was neither owned nor acquired, or more of it than was";

// ---- Equip now: the answer ---------------------------------------------------------------------------------------------------

const EQUIP_NOW_RESULT_KEYS = ["v", "type", "id", "kind", "mode", "status", "proven", "label", "F", "value", "kit", "buffs", "hasteAssumed", "elapsedMs"];

/** The answer to an Equip now request (see the head of this file); returns a fresh copy. `expect` says what is in flight: the id, the kind, the mode and the owned set. */
function checkEquipNowReply(given, expect, idOf) {
  checkKeys(given, new Set(EQUIP_NOW_RESULT_KEYS), EQUIP_NOW_RESULT_KEYS, "the result");
  const id = idOf();
  if (given.get("mode") !== EQUIP_NOW || expect.kind !== "scenario" || expect.mode !== EQUIP_NOW) throw badReply("the result is not for an Equip now request");
  const answer = readAnswer(given, ownedOf(expect.owned), "the kit wears an item that was not owned, or more of it than was owned");
  const elapsedMs = readElapsed(given);
  return { v: PROTOCOL_VERSION, type: "result", id, kind: "scenario", mode: EQUIP_NOW, ...answerFields(answer), elapsedMs };
}

// ---- the farm path: the steps and the watch the page keeps of them ---------------------------------------------------------------

const STEP_ZERO_KEYS = ["v", "type", "id", "index", "status", "proven", "label", "F", "value", "kit", "buffs", "hasteAssumed"];
const STEP_KEYS = ["v", "type", "id", "index", "found", "ident", "kind", "sourceTier", "cost", "F", "value", "gain", "gainValue", "kit", "buffs", "hasteAssumed", "status", "proven", "label"];
const FARM_PATH_RESULT_KEYS = ["v", "type", "id", "kind", "mode", "stopped", "steps", "hasteAssumed", "elapsedMs"];
const STOP_REASONS = ["limit", "no-gain", "time", "stopped"];

/**
 * A step message of the farm path, checked and copied. Index 0 is Equip now (the answer to Equip now, checked as that is); 1 to 8 are the steps, found or not. A step
 * that was found acquires an item the kit wears, gains something, and says what the item is and what reaching its tier costs; one that was not found has nothing of
 * that, no kit and the label of a solve that ran out of time with nothing. When `expect.path` is a path watch (`createPathWatch`) the step is checked in its place in the
 * path as well.
 */
function checkStep(given, expect, idOf) {
  const index = given.get("index");
  if (!isWholeNumber(index, 0, LIMITS.maxPathSteps)) throw badReply("the step has no usable index");
  const keys = index === 0 ? STEP_ZERO_KEYS : STEP_KEYS;
  checkKeys(given, new Set(keys), keys, "the step");
  const id = idOf();
  if (expect.kind !== "scenario" || expect.mode !== FARM_PATH) throw badReply("a step answers a farm path request");
  let message;
  if (index === 0) {
    const answer = readAnswer(given, ownedOf(expect.owned), "the kit wears an item that was not owned, or more of it than was owned");
    message = { v: PROTOCOL_VERSION, type: "step", id, index, ...answerFields(answer) };
  } else {
    const found = given.get("found");
    if (typeof found !== "boolean") throw badReply("the step does not say whether it was found");
    const answer = readAnswer(given, undefined, "");
    if (found) {
      if (answer.kit === null) throw badReply("a step that was found has a kit");
      const acquisition = readAcquisition(given.get("ident"), given.get("kind"), given.get("sourceTier"), given.get("cost"), expect.tierMode);
      if (!answer.worn.has(acquisition.ident)) throw badReply("the kit does not wear the item that the step acquired");
      const gain = readExact(given.get("gain"), given.get("gainValue"), "the gain");
      if (gain.rational.sign() <= 0) throw badReply("a step gains something");
      message = { v: PROTOCOL_VERSION, type: "step", id, index, found, ...acquisition, ...answerFields(answer), gain: gain.text, gainValue: gain.number };
    } else {
      for (const field of ["ident", "kind", "sourceTier", "cost", "F", "value", "gain", "gainValue", "kit"]) {
        if (given.get(field) !== null) throw badReply("a step that was not found has none of what a step has");
      }
      if (answer.status !== "time_limit") throw badReply("a step that was not found ran out of time");
      message = { v: PROTOCOL_VERSION, type: "step", id, index, found, ident: null, kind: null, sourceTier: null, cost: null, ...answerFields(answer), gain: null, gainValue: null };
    }
  }
  if (expect.path !== undefined) expect.path.accept(message, wornOf(message.kit));
  return message;
}

/** How many of each ident a checked kit wears (none for no kit). */
function wornOf(kit) {
  const worn = new Map();
  for (const ident of kit ?? []) if (ident !== null) worn.set(ident, (worn.get(ident) ?? 0) + 1);
  return worn;
}

/**
 * The page's watch over a farm path: the steps arrive in order (Equip now, then 1, 2, ...), none after the path ended and none beyond the steps asked for, the
 * result says the haste of Equip now (each step says the haste its own kit counts), each step gains exactly its value less the value before it, and the kit wears only what was owned and what the steps
 * acquired (an upgrade turns an owned copy into the item). `request` is the farm path request that was made. `validateFromWorker` calls `accept` for each step and
 * `finish` for the result when the expectation holds the watch; a step that is refused leaves the watch where it was.
 */
export function createPathWatch(request) {
  const wanted = request.steps;
  let available = new Map(request.owned.map(([ident, count]) => [ident, count]));
  let next = 0;
  let made = 0; // the steps after Equip now
  let before = null; // the value before the next step (a Rational), when there is one
  let haste = null;
  let over = false; // the path ended by itself: Equip now was not proven, or a step was not found or not proven the best
  return {
    accept(step, worn) {
      if (over) throw badReply("the path went on after it ended");
      if (step.index !== next) throw badReply("the steps of the path are not in order");
      if (step.index > wanted) throw badReply("the path has more steps than were asked for");
      if (step.index === 0) {
        haste = step.hasteAssumed;
        before = step.F === null ? null : Rational.parseLong(step.F);
        over = step.status !== "optimal";
      } else {
        if (step.found) {
          const value = Rational.parseLong(step.F);
          if (before === null || !value.sub(before).equals(Rational.parseLong(step.gain))) throw badReply("the gain of a step is not its value less the value before it");
          const copies = afterAcquiring(available, [step]);
          checkWorn(worn, copies, KIT_WEAR_MESSAGE);
          available = copies;
          before = value;
          over = step.status !== "optimal";
        } else {
          over = true;
        }
        made += 1;
      }
      next += 1;
    },
    /** The result of the path (`{stopped, steps, hasteAssumed}`) agrees with the steps that were seen. */
    finish(result) {
      if (next === 0) throw badReply("the path ended before Equip now was sent");
      if (result.steps !== made) throw badReply("the result counts other steps than were sent");
      if (haste !== null && result.hasteAssumed !== haste) throw badReply("the result assumes another haste than Equip now did");
      if (over && result.stopped !== "time") throw badReply("a path that ran out of time says so");
      if (result.stopped === "limit" && made !== wanted) throw badReply("a path that made fewer steps than were asked for did not reach its limit");
      if (result.stopped === "no-gain" && made >= wanted) throw badReply("a path that made all its steps did not run out of gain");
    },
  };
}

/** The final result of a farm path: why it stopped, how many steps it made, the haste it assumed, and the time it took. */
function checkFarmPathReply(given, expect, idOf) {
  checkKeys(given, new Set(FARM_PATH_RESULT_KEYS), FARM_PATH_RESULT_KEYS, "the result");
  const id = idOf();
  const stopped = given.get("stopped");
  if (!STOP_REASONS.includes(stopped)) throw badReply("the result says why the path stopped with a reason that is not one");
  const steps = given.get("steps");
  if (!isWholeNumber(steps, 0, LIMITS.maxPathSteps)) throw badReply("the result counts steps out of range");
  const hasteAssumed = given.get("hasteAssumed");
  if (!isWholeNumber(hasteAssumed, 0, MAX_HASTE)) throw badReply("the assumed haste is not a whole number of percent in range");
  const elapsedMs = readElapsed(given);
  const result = { v: PROTOCOL_VERSION, type: "result", id, kind: "scenario", mode: FARM_PATH, stopped, steps, hasteAssumed, elapsedMs };
  if (expect.path !== undefined) {
    expect.path.finish(result);
  } else if (expect.steps !== undefined) {
    if (steps > expect.steps) throw badReply("the path made more steps than were asked for");
    if (stopped === "limit" && steps !== expect.steps) throw badReply("a path that made fewer steps than were asked for did not reach its limit");
    if (stopped === "no-gain" && steps >= expect.steps) throw badReply("a path that made all its steps did not run out of gain");
  }
  return result;
}

// ---- the best sets: the answer -------------------------------------------------------------------------------------------------

const BEST_SETS_RESULT_KEYS = ["v", "type", "id", "kind", "mode", "k", "acquired", "F", "value", "gain", "gainValue", "kit", "buffs", "status", "proven", "label", "baseline", "hasteAssumed", "elapsedMs"];

/**
 * The answer to a best sets request: the additions made at once (at most k), the kit and its exact value, the gain over Equip now and the value of Equip now. A set
 * with no value is a set that was not found in time (no kit, no gain); a set that adds nothing has the kit of Equip now and a gain of 0; a set that adds something gains
 * something, exactly its value less the value of Equip now, and its kit wears what was owned and what it acquires.
 */
function checkBestSetsReply(given, expect, idOf) {
  checkKeys(given, new Set(BEST_SETS_RESULT_KEYS), BEST_SETS_RESULT_KEYS, "the result");
  const id = idOf();
  const k = given.get("k");
  if (!BEST_SET_SIZES.includes(k) || (expect.k !== undefined && k !== expect.k)) throw badReply("the result is for another size of set than was asked for");
  const acquired = denseList(given.get("acquired"), "the additions", k).map((raw) => {
    const entry = exactFields(raw, ["ident", "kind", "sourceTier", "cost"], "an addition");
    return readAcquisition(entry.get("ident"), entry.get("kind"), entry.get("sourceTier"), entry.get("cost"), expect.tierMode);
  });
  const owned = ownedOf(expect.owned);
  const available = owned === undefined ? undefined : afterAcquiring(owned, acquired);
  const answer = readAnswer(given, available, KIT_WEAR_MESSAGE);
  if (answer.kit !== null) {
    // the kit wears what the set acquires, as the kit of a step wears the item it acquired: one copy for each addition of an ident (the least a kit may wear of it)
    const additions = new Map();
    for (const entry of acquired) additions.set(entry.ident, (additions.get(entry.ident) ?? 0) + 1);
    for (const [ident, times] of additions) if ((answer.worn.get(ident) ?? 0) < times) throw badReply("the kit does not wear what the set acquired");
  }
  const base = exactFields(given.get("baseline"), ["F", "value"], "the baseline");
  if ((base.get("F") === null) !== (base.get("value") === null)) throw badReply("the exact value of Equip now and its number come together or not at all");
  const baseline = base.get("F") === null ? null : readExact(base.get("F"), base.get("value"), "the exact value of Equip now");
  let gain = null;
  if (answer.kit === null) {
    if (given.get("gain") !== null || given.get("gainValue") !== null || acquired.length > 0) throw badReply("a set that was not found has no gain and acquires nothing");
  } else {
    if (baseline === null) throw badReply("a set has a gain over an Equip now that has no value");
    gain = readExact(given.get("gain"), given.get("gainValue"), "the gain");
    if (!gain.rational.equals(answer.exact.rational.sub(baseline.rational))) throw badReply("the gain of a set is not its value less the value of Equip now");
    if ((acquired.length > 0) !== (gain.rational.sign() > 0) || gain.rational.sign() < 0) throw badReply("a set acquires something when it gains something, and never loses");
  }
  const elapsedMs = readElapsed(given);
  return {
    v: PROTOCOL_VERSION,
    type: "result",
    id,
    kind: "scenario",
    mode: BEST_SETS,
    k,
    acquired,
    ...answerFields(answer),
    gain: gain === null ? null : gain.text,
    gainValue: gain === null ? null : gain.number,
    baseline: { F: baseline === null ? null : baseline.text, value: baseline === null ? null : baseline.number },
    elapsedMs,
  };
}

// ---- Every slot: the answer ----------------------------------------------------------------------------------------------------

const EVERY_SLOT_RESULT_KEYS = ["v", "type", "id", "kind", "mode", "rows", "elapsedMs"];
/** The names of the 22 places of a kit, in kit order (the evaluator's SLOT_INSTANCES; a test holds the two lists to each other). */
export const KIT_PLACE_NAMES = Object.freeze([
  "HEAD", "FACE", "EAR", "EAR", "NECK", "SHOULDERS", "ARMS", "BACK", "WRIST", "WRIST", "HANDS", "FINGER", "FINGER", "CHEST", "LEGS", "FEET", "WAIST", "RANGE", "ANY", "ANY", "PRIMARY", "SECONDARY",
]); // fmt: skip

/**
 * One row of Every slot: the place, its index, the item worn there and the best swaps there, best first (equal gains by key and tier). `held` says what the request had:
 * `kit` (the item worn there is the one the request's kit has in that place) with `worn` (how many of each ident the kit wears), and `owned` with `tierMode` (a swap offers an
 * item the visitor owns, as it is owned, or one at the tier of the tier mode: the pool of a swap is the candidates and the owned items). The copies are counted: a candidate may
 * be got again, but an owned item that is not a candidate is a swap only while the visitor owns more of it than the kit wears in its other places. The page does not know the
 * candidates, only the tiers the mode gives: an owned item at another tier cannot be one, so it is held to its count (the kit's copies are all in other places, as the row's own
 * item is not offered); one at a tier the mode gives may be a candidate, and is not held. What the request did not have is not checked.
 */
function readRow(raw, at, limit, held) {
  const row = exactFields(raw, ["place", "index", "current", "swaps"], "a row");
  if (row.get("index") !== at || row.get("place") !== KIT_PLACE_NAMES[at]) throw badReply("the rows are not the places of a kit, in the order of a kit");
  const current = row.get("current");
  if (current !== null && !isItemIdent(current)) throw badReply("the item worn in a place is an ident or nothing");
  if (held.kit !== undefined && current !== held.kit[at]) throw badReply("the item worn in a place is not the one the request's kit has there");
  const swaps = [];
  const seen = new Set();
  let previous = null;
  for (const entry of denseList(row.get("swaps"), "the swaps of a place", limit)) {
    const swap = exactFields(entry, ["ident", "delta", "deltaValue"], "a swap");
    const ident = swap.get("ident");
    if (!isItemIdent(ident)) throw badReply("a swap does not name an item by an ident of the form key@tier");
    if (ident === current || seen.has(ident)) throw badReply("a place offers an item once, and not the one worn in it");
    if (held.owned !== undefined && held.tierMode !== undefined && !tierFits(held.tierMode, splitIdent(ident).tier)) {
      if (!held.owned.has(ident)) throw badReply("a swap offers an item that the visitor does not own, at a tier that the tier mode of the request does not give");
      // an owned item that the mode cannot give is no candidate: there must be a copy that the kit does not wear in another place
      if (held.worn !== undefined && held.owned.get(ident) <= (held.worn.get(ident) ?? 0)) {
        throw badReply("a swap offers an item that the visitor owns no more often than the kit wears it in other places, at a tier that the tier mode of the request does not give");
      }
    }
    seen.add(ident);
    const delta = readExact(swap.get("delta"), swap.get("deltaValue"), "the change");
    if (previous !== null) {
      const order = previous.delta.compare(delta.rational);
      if (order < 0 || (order === 0 && !identBefore(previous.ident, ident))) throw badReply("the swaps of a place are not in order: best first, equal gains by key and tier");
    }
    previous = { ident, delta: delta.rational };
    swaps.push({ ident, delta: delta.text, deltaValue: delta.number });
  }
  return { place: KIT_PLACE_NAMES[at], index: at, current, swaps };
}

/** The answer to an Every slot request: 22 rows, one for each place of a kit, in order, with at most the limit of swaps each. */
function checkEverySlotReply(given, expect, idOf) {
  checkKeys(given, new Set(EVERY_SLOT_RESULT_KEYS), EVERY_SLOT_RESULT_KEYS, "the result");
  const id = idOf();
  const raw = denseList(given.get("rows"), "the rows", KIT_PLACES);
  if (raw.length !== KIT_PLACES) throw badReply(`Every slot has ${KIT_PLACES} rows`);
  const limit = expect.limit === undefined ? LIMITS.maxSwaps : expect.limit;
  const held = { kit: expect.kit, worn: Array.isArray(expect.kit) ? wornOf(expect.kit) : undefined, owned: ownedOf(expect.owned), tierMode: expect.tierMode };
  const rows = raw.map((entry, at) => readRow(entry, at, limit, held));
  return { v: PROTOCOL_VERSION, type: "result", id, kind: "scenario", mode: EVERY_SLOT, rows, elapsedMs: readElapsed(given) };
}

// ---- the best kit: the answer --------------------------------------------------------------------------------------------------

/**
 * The tier of the items a best kit wears. The pool of a view is made at one tier, so the items of a kit are all at one tier; and when the page names the tier of the request
 * (`tier`) it is that one. (A kit of no item has no tier to check. The page does not know the pool, so which items of that tier the kit may wear is the worker's.)
 */
function checkOneTier(kit, tier) {
  if (kit === null) return;
  let seen = null;
  for (const ident of kit) {
    if (ident === null) continue;
    const at = splitIdent(ident).tier;
    if (seen !== null && at !== seen) throw badReply("the kit wears items of different tiers, and the pool of a best kit is at one tier");
    seen = at;
  }
  if (tier !== undefined && seen !== null && seen !== tier) throw badReply("the kit wears items at another tier than the request's");
}

/**
 * The answer to a best kit request: the fields of Equip now's answer, held to the same rules (the status and its label, the exact value and its number, the 22 places, the buffs,
 * the assumed haste, the time). No owned set bounds the kit, and the items are those of the pool of the view, all at one tier (`checkOneTier`).
 */
function checkBestKitReply(given, expect, idOf) {
  checkKeys(given, new Set(EQUIP_NOW_RESULT_KEYS), EQUIP_NOW_RESULT_KEYS, "the result");
  const id = idOf();
  if (given.get("mode") !== BEST_KIT || expect.kind !== "scenario" || expect.mode !== BEST_KIT) throw badReply("the result is not for a best kit request");
  const answer = readAnswer(given, undefined, "");
  checkOneTier(answer.kit, expect.tier);
  const elapsedMs = readElapsed(given);
  return { v: PROTOCOL_VERSION, type: "result", id, kind: "scenario", mode: BEST_KIT, ...answerFields(answer), elapsedMs };
}

/** The final result of a scenario request, by its mode: the mode must be the one in flight. */
function checkScenarioReply(given, expect, idOf) {
  const mode = given.get("mode");
  if (expect.kind !== "scenario" || !SCENARIO_MODES.includes(mode) || mode !== expect.mode) throw badReply("the result is not for the mode of the request in flight");
  if (mode === EQUIP_NOW) return checkEquipNowReply(given, expect, idOf);
  if (mode === FARM_PATH) return checkFarmPathReply(given, expect, idOf);
  if (mode === BEST_SETS) return checkBestSetsReply(given, expect, idOf);
  if (mode === BEST_KIT) return checkBestKitReply(given, expect, idOf);
  return checkEverySlotReply(given, expect, idOf);
}

/**
 * Check a message the page received from the worker; returns a copy. `expect` says what is in flight: `id`, the request's `kind` and, for a
 * model, its number of `columns`; for a scenario its `mode`, its `owned` set (an Equip now kit and the kit of a path or a set wear what is owned), and what it
 * asked: `steps` and `path` (a watch, `createPathWatch`) for a farm path, `k` for best sets, `limit` for Every slot, and `tierMode` (what is acquired is at the tier of the mode,
 * and so is a swap that is not an owned item) and, for Every slot, `kit` (the item a row says is worn in its place is the request's, and an owned item at a tier the mode
 * does not give is a swap only while the visitor owns more of it than the kit wears), and for a best kit its `tier` (the kit wears only items at that tier; without it the items
 * of the kit are still held to one tier). Throws a ProtocolError with the code protocol.
 */
export function validateFromWorker(data, expect = {}) {
  const given = new Map(plainEntries(data, (detail) => badReply(`the message ${detail}`)));
  if (given.get("v") !== PROTOCOL_VERSION) throw badReply("the message is of another version");
  const type = given.get("type");
  const idOf = () => {
    const id = given.get("id");
    if (!isWholeNumber(id, 1, LIMITS.maxId)) throw badReply("the message has no usable id");
    if (expect.id === undefined || id !== expect.id) throw badReply("the message answers a request that is not in flight");
    return id;
  };

  if (type === "ready") {
    checkKeys(given, new Set(["v", "type", "highs", "wasm", "module"]), ["highs"], "the ready message");
    const highs = given.get("highs");
    if (typeof highs !== "string" || !HIGHS_VERSION.test(highs)) throw badReply("the solver's version is not a version");
    const message = { v: PROTOCOL_VERSION, type, highs };
    // `wasm` is the SHA-256 of the file the worker downloaded, checked and compiled; a worker that was given a compiled module has none
    if (given.get("wasm") !== undefined) {
      if (!isSha256(given.get("wasm"))) throw badReply("the checksum of the optimizer's file is not a SHA-256");
      message.wasm = given.get("wasm");
    }
    if (given.get("module") !== undefined) {
      if (message.wasm === undefined) throw badReply("the compiled module comes without the checksum of the file it was made from");
      if (!isCompiledModule(given.get("module"))) throw badReply("the module is not a compiled WebAssembly module");
      message.module = given.get("module");
    }
    return message;
  }

  if (type === "pong") {
    checkKeys(given, new Set(["v", "type"]), [], "the pong");
    return { v: PROTOCOL_VERSION, type };
  }

  if (type === "progress") {
    checkKeys(given, PROGRESS_KEYS, ["phase"], "the progress report");
    const phase = given.get("phase");
    if (!PHASES.includes(phase)) throw badReply("the progress report has an unknown phase");
    const message = { v: PROTOCOL_VERSION, type, phase };
    if (given.get("id") !== undefined) message.id = idOf();
    // the stage of a scenario request (what it is working on), and the step of the stage of a step
    const stage = given.get("stage");
    const step = given.get("step");
    if (stage !== undefined) {
      const stages = expect.kind === "scenario" ? STAGES_OF.get(expect.mode) : undefined;
      if (typeof stage !== "string" || stages === undefined || !stages.includes(stage)) throw badReply("the progress report has a stage that its request does not have");
      message.stage = stage;
    }
    if ((step !== undefined) !== (stage === "step")) throw badReply("the progress report has a step without the stage of a step, or the stage of a step without a step");
    if (step !== undefined) {
      if (!isWholeNumber(step, 1, LIMITS.maxPathSteps)) throw badReply("the progress report has a step that is not a whole number in range");
      message.step = step;
    }
    const loaded = given.get("loaded");
    const total = given.get("total");
    if ((loaded === undefined) !== (total === undefined)) throw badReply("the progress report has only one of loaded and total");
    if (loaded !== undefined) {
      if (!isWholeNumber(loaded, 0, Number.MAX_SAFE_INTEGER) || !isWholeNumber(total, 0, Number.MAX_SAFE_INTEGER) || loaded > total) {
        throw badReply("the progress report has sizes that do not add up");
      }
      message.loaded = loaded;
      message.total = total;
    }
    for (const key of ["elapsedMs", "gap"]) {
      const item = given.get(key);
      if (item === undefined) continue;
      if (!isFiniteNumber(item) || item < 0) throw badReply(`the progress report has a ${key} that is not a number from 0 up`);
      message[key] = item;
    }
    for (const key of ["objective", "bound"]) {
      const item = given.get(key);
      if (item === undefined) continue;
      if (!isFiniteNumber(item)) throw badReply(`the progress report has a ${key} that is not a finite number`);
      message[key] = item;
    }
    if (given.get("nodes") !== undefined) {
      if (!isWholeNumber(given.get("nodes"), 0, Number.MAX_SAFE_INTEGER)) throw badReply("the progress report has a node count that is not whole");
      message.nodes = given.get("nodes");
    }
    return message;
  }

  if (type === "step") return checkStep(given, expect, idOf);

  if (type === "error") {
    checkKeys(given, new Set(["v", "type", "id", "code", "message"]), ["code", "message"], "the error");
    const code = given.get("code");
    if (!ERROR_CODES.includes(code)) throw badReply("the error has an unknown code");
    const message = { v: PROTOCOL_VERSION, type, code, message: cleanText(given.get("message"), LIMITS.maxMessageLength, "the error's message", badReply) };
    if (given.get("id") !== undefined) message.id = idOf();
    return message;
  }

  if (type === "result") {
    if (given.get("kind") === "scenario") return checkScenarioReply(given, expect, idOf);
    checkKeys(given, new Set(RESULT_KEYS), RESULT_KEYS, "the result");
    const id = idOf();
    if (given.get("kind") !== "model" || (expect.kind !== undefined && expect.kind !== "model")) throw badReply("the result is not for a model request");
    const status = given.get("status");
    if (!STATUSES.has(status)) throw badReply("the result has an unknown status");
    const proven = given.get("proven");
    if (typeof proven !== "boolean") throw badReply("the result does not say whether it is proven");
    const x = given.get("x") === null ? null : numberList(given.get("x"), expect.columns, "the solution", badReply);
    const objective = given.get("objective");
    if (!nullOr(objective, isFiniteNumber)) throw badReply("the objective is not a finite number or null");
    const bound = given.get("bound");
    if (!nullOr(bound, isFiniteNumber)) throw badReply("the bound is not a finite number or null");
    const gap = given.get("gap");
    if (!nullOr(gap, (item) => isFiniteNumber(item) && item >= 0)) throw badReply("the gap is not a number from 0 up or null");
    const nodes = given.get("nodes");
    if (!nullOr(nodes, (item) => isWholeNumber(item, 0, Number.MAX_SAFE_INTEGER))) throw badReply("the node count is not a whole number or null");
    const elapsedMs = given.get("elapsedMs");
    if (!isFiniteNumber(elapsedMs) || elapsedMs < 0) throw badReply("the elapsed time is not a number from 0 up");
    const label = given.get("label");
    if (label !== null && typeof label !== "string") throw badReply("the label is not text or null");
    // what each status must look like: a result cannot claim more than the solver found
    if (status === "optimal") {
      if (proven !== true || x === null || objective === null || label !== null) throw badReply("an optimal result must be proven, with a solution and no label");
    } else if (status === "infeasible") {
      if (proven !== true || x !== null || objective !== null || label !== null) throw badReply("an infeasible result must be proven, with no solution and no label");
    } else {
      if (proven !== false) throw badReply("a time-limited result is never proven");
      if ((x === null) !== (objective === null)) throw badReply("a time-limited result has a solution and an objective, or neither");
      if (label !== (x === null ? LABEL_NO_INCUMBENT : LABEL_TIME_LIMIT)) throw badReply("a time-limited result must carry its honest label");
    }
    return { v: PROTOCOL_VERSION, type, id, kind: "model", status, proven, objective, x, bound, gap, nodes, elapsedMs, label };
  }

  throw badReply("the message is of an unknown type");
}
