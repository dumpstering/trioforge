// Model JSON v1, compared: the check that holds the browser's builder (model.js) to the Python one (pipeline/trioforge/solver/model.py). A port of
// `compare` in pipeline/trioforge/export/milp_json.py, which also describes the document: the program `maximize const + c . x` over
// `row_lb <= A x <= row_ub` and `col_lb <= x <= col_ub`, with the columns of `integrality` 1 whole, the rows in compressed row form and an
// infinite bound written as null.
//
//   compare(a, b, {limit}) -> a list of differences, empty when the documents agree
//
// The parity rules, which are those of milp_json.compare in Python:
//   * the column names, their integrality and the row set are identical, in identical order (a column or a row that the other side lacks is
//     named, and so is a change of order of those they share);
//   * coefficients, bounds, the constant and the objective agree within |a - b| <= 1e-12 x max(1, |a|, |b|); an infinite bound agrees only
//     with an infinite one, never with a number; a coefficient that is missing and one that is stored as 0 are the same;
//   * `info` describes a build and is not compared.
//
// The messages use the wording of milp_json.compare ("missing column: x", "coefficient differs: row r, column c (x vs y)" ...) and say what `b` is
// seen from `a`: "missing" is in `a` and not in `b`, "extra" is in `b` and not in `a`. They differ from Python's in four ways:
//   * the order. Python lists the sense and the constant first; here they come last, after the columns (their names and order, then each by name),
//     the rows (the same: the first row that differs comes first) and the item and buff columns. So when a column or a row differs, the first
//     message names the first one that does;
//   * the numbers are printed as JavaScript prints them ("1" where Python writes "1.0", "1e-7" where it writes "1e-07"), the sense is in double
//     quotes (Python's repr has single ones), and an item or buff column is shown as JSON (["name", ...]) where Python shows a tuple;
//   * a document that is not a model JSON v1 is reported by the first thing that the browser's reader (protocol.js) refuses in it, in its words;
//     Python lists all the faults of `validate`. It is not compared;
//   * text that is not JSON (Python raises) and a document that is not an object are reported as invalid, ahead of everything else, and so before
//     the versions are looked at. Otherwise a document of another version is reported alone.
// `limit` (100 unless given) cuts a long list: the rest is counted in a last message.

import { PROTOCOL_VERSION, ProtocolError, validateRequest } from "./protocol.js";

/** The relative tolerance of the parity rules, with a floor of 1 on the size of the numbers. */
export const TOLERANCE = 1e-12;
/** The most differences listed; the rest are counted. */
export const LIMIT = 100;

const OPTION_KEYS = new Set(["limit"]);

const close = (x, y) => Math.abs(x - y) <= TOLERANCE * Math.max(1, Math.abs(x), Math.abs(y));
const sameBound = (x, y) => (x === null || y === null ? x === null && y === null : close(x, y));
const show = (bound) => (bound === null ? "unbounded" : String(bound));

const isObject = (value) => typeof value === "object" && value !== null && !Array.isArray(value);

/** The document of an argument (itself, or what JSON text says), or why there is none: `{document}` or `{fault}`. */
function read(argument) {
  let document = argument;
  if (typeof argument === "string") {
    try {
      document = JSON.parse(argument);
    } catch {
      return { fault: "the text is not JSON" };
    }
  }
  return isObject(document) ? { document } : { fault: "the document is not an object" };
}

/** The faults of a document as the browser's reader finds them (it stops at the first), or none. */
function faults(document) {
  try {
    validateRequest({ v: PROTOCOL_VERSION, kind: "model", model: document, budgetMs: 1 });
    return [];
  } catch (error) {
    if (error instanceof ProtocolError) return [error.detail];
    throw error;
  }
}

/** The messages for the names one side lacks and for a change of order of the names both have; the names both have. */
function orderOf(namesA, namesB, what, out) {
  const inA = new Set(namesA);
  const inB = new Set(namesB);
  for (const name of namesA) if (!inB.has(name)) out.push(`missing ${what}: ${name}`);
  for (const name of namesB) if (!inA.has(name)) out.push(`extra ${what}: ${name}`);
  const commonA = namesA.filter((name) => inB.has(name));
  const commonB = namesB.filter((name) => inA.has(name));
  for (let at = 0; at < commonA.length; at += 1) {
    if (commonA[at] !== commonB[at]) {
      out.push(`${what} order changed: first difference at position ${at} (${commonA[at]} vs ${commonB[at]})`);
      break;
    }
  }
  return new Set(commonA);
}

/** The entries of row `r`, by the name of the column. */
function rowEntries(document, r) {
  const { start, index, value } = document.A;
  const entries = new Map();
  for (let k = start[r]; k < start[r + 1]; k += 1) entries.set(document.col_names[index[k]], value[k]);
  return entries;
}

/** The item or buff columns, each as text with the name of its column first: what has to be equal, in this order. */
function tagged(document, key) {
  return document[key].map(([column, ...rest]) => JSON.stringify([document.col_names[column], ...rest]));
}

function cut(lines, limit) {
  return lines.length <= limit ? lines : [...lines.slice(0, limit), `... and ${lines.length - limit} more`];
}

/**
 * What differs between two model JSON v1 documents (parsed, or their text) under the parity rules of the head of this file; an empty list means
 * they agree. `options` is `{limit}` or none; any other option is an error, since a misspelt limit would be ignored.
 */
export function compare(a, b, options) {
  if (options !== undefined && options !== null && (typeof options !== "object" || Array.isArray(options))) throw new TypeError("the options are an object, such as {limit: 10}");
  for (const key of Object.keys(options ?? {})) {
    if (!OPTION_KEYS.has(key)) throw new TypeError(`the options have an option (${key.length <= 24 ? key : "?"}) that compare does not read (it reads limit)`);
  }
  const limit = options?.limit ?? LIMIT;
  if (!Number.isInteger(limit) || limit < 1) throw new TypeError("limit is a whole number of at least 1");

  const readA = read(a);
  const readB = read(b);
  const unread = [
    ...(readA.fault === undefined ? [] : [`invalid model a: ${readA.fault}`]),
    ...(readB.fault === undefined ? [] : [`invalid model b: ${readB.fault}`]),
  ];
  if (unread.length > 0) return cut(unread, limit);
  const docA = readA.document;
  const docB = readB.document;
  if (docA.version !== docB.version) return [`version differs: ${docA.version} vs ${docB.version}`];
  const invalid = [...faults(docA).map((fault) => `invalid model a: ${fault}`), ...faults(docB).map((fault) => `invalid model b: ${fault}`)];
  if (invalid.length > 0) return cut(invalid, limit);

  const out = [];
  const atA = new Map(docA.col_names.map((name, i) => [name, i]));
  const atB = new Map(docB.col_names.map((name, i) => [name, i]));
  const columns = orderOf(docA.col_names, docB.col_names, "column", out);
  for (const name of docA.col_names) {
    if (!columns.has(name)) continue;
    const i = atA.get(name);
    const j = atB.get(name);
    if (docA.integrality[i] !== docB.integrality[j]) out.push(`integrality differs: ${name}`);
    for (const [key, label] of [["col_lb", "lower"], ["col_ub", "upper"]]) {
      const x = docA[key][i];
      const y = docB[key][j];
      if (!sameBound(x, y)) out.push(`column ${label} bound differs: ${name} (${show(x)} vs ${show(y)})`);
    }
    if (!close(docA.c[i], docB.c[j])) out.push(`objective coefficient differs: ${name} (${docA.c[i]} vs ${docB.c[j]})`);
  }

  const rowAtA = new Map(docA.row_names.map((name, i) => [name, i]));
  const rowAtB = new Map(docB.row_names.map((name, i) => [name, i]));
  const rows = orderOf(docA.row_names, docB.row_names, "row", out);
  for (const name of docA.row_names) {
    if (!rows.has(name)) continue;
    const r = rowAtA.get(name);
    const s = rowAtB.get(name);
    for (const [key, label] of [["row_lb", "lower"], ["row_ub", "upper"]]) {
      const x = docA[key][r];
      const y = docB[key][s];
      if (!sameBound(x, y)) out.push(`row ${label} bound differs: ${name} (${show(x)} vs ${show(y)})`);
    }
    const entriesA = rowEntries(docA, r);
    const entriesB = rowEntries(docB, s);
    for (const column of [...entriesA.keys(), ...[...entriesB.keys()].filter((c) => !entriesA.has(c))]) {
      const x = entriesA.get(column) ?? 0;
      const y = entriesB.get(column) ?? 0;
      if (!close(x, y)) out.push(`coefficient differs: row ${name}, column ${column} (${x} vs ${y})`);
    }
  }

  for (const [key, label] of [["item_cols", "item columns"], ["buff_cols", "buff columns"]]) {
    const listA = tagged(docA, key);
    const listB = tagged(docB, key);
    let at = 0;
    while (at < listA.length && at < listB.length && listA[at] === listB[at]) at += 1;
    if (at < listA.length || at < listB.length) {
      out.push(`${label} differ: first difference at position ${at} (${at < listA.length ? listA[at] : "none"} vs ${at < listB.length ? listB[at] : "none"})`);
    }
  }

  if (docA.sense !== docB.sense) out.push(`sense differs: ${JSON.stringify(docA.sense)} vs ${JSON.stringify(docB.sense)}`);
  if (!close(docA.const, docB.const)) out.push(`constant differs: ${docA.const} vs ${docB.const}`);
  return cut(out, limit);
}
