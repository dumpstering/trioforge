// Reading the parity fixtures' cases for the tests of the pruning, the sessions and the farm path (engine-prune, engine-solve and engine-path). The
// same reading as tests-js/engine-model.test.mjs does for the builder, kept here so that the three files share it: a case's profile (always
// `inputs.profile`: the profile of a strict-proxy case cannot be assembled again), its items read from the records at their tiers, its buff set, its
// Monk bins, and for an Upgrade case the owned set and the candidates. Nothing here is read by the site, and nothing here uses the engine's solver.

import { atTier } from "../pipeline/trioforge/site/static/engine/items.js";
import { readProcs } from "../pipeline/trioforge/site/static/engine/procs.js";
import { readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { mulberry32 } from "./engine-models.mjs";

/** The families of cases, in the order the tests go through them. */
export const FAMILIES = ["matrix", "upgrade", "pmb36", "brute"];

export const clone = (value) => JSON.parse(JSON.stringify(value));

/** A copy that nothing can change, all through (so that the engine can only read what it is given). */
export function deepFreeze(value) {
  const stack = [value];
  while (stack.length > 0) {
    const node = stack.pop();
    if (node === null || typeof node !== "object" || Object.isFrozen(node)) continue;
    Object.freeze(node);
    for (const child of Array.isArray(node) ? node : Object.values(node)) stack.push(child);
  }
  return value;
}

/** An exact "p/q" text, as the fixtures write it, as a Rational (a text of the brute-force values can be longer than the 64 digits a bundle takes). */
export const exact = (text) => Rational.parseLong(text);

export const identOf = (item) => `${item.key}@${item.tier}`;
export const splitIdent = (name) => [name.slice(0, name.lastIndexOf("@")), Number(name.slice(name.lastIndexOf("@") + 1))];

/** The kit of a solution as the fixtures write it: `[key, tier]` or null for each of the 22 places. */
export const kitPairs = (kit) => kit.map((item) => (item === null ? null : [item.key, item.tier]));

/** The list in an order of its own, the same for the same seed. */
export function shuffled(list, seed) {
  const random = mulberry32(seed);
  const copy = [...list];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

/** What every case of a set shares: the rules of the tiers of each level (the bundles) and the Monk bins of each level (the evaluator's listing). */
export function sharedOf(set) {
  const rules = new Map();
  for (const path of set.paths("bundle")) {
    const bundle = readBundle(set.read(path));
    if (!rules.has(bundle.level)) rules.set(bundle.level, bundle);
  }
  return { rules, bins: set.read("evaluate/profiles.json").monk_bins };
}

/** The inputs of a case as the engine takes them, and the items of its pools (each read once). */
export function caseOf(shared, doc) {
  const { inputs } = doc;
  const profile = deepFreeze(clone(inputs.profile));
  const records = new Map(doc.records.map((record) => [record.key ?? `w${record.id}`, record]));
  const rules = shared.rules.get(inputs.level) ?? [...shared.rules.values()][0];
  const items = new Map();
  const itemAt = (key, tier) => {
    const name = `${key}@${tier}`;
    if (!items.has(name)) items.set(name, atTier(records.get(key), tier, rules, { weaponPct: inputs.weapon_pct }));
    return items.get(name);
  };
  const itemNamed = (name) => itemAt(...splitIdent(name));
  const bins = profile.monk === null ? undefined : deepFreeze(clone(shared.bins[String(inputs.level)]));
  /** The table of weapon procs a case was made with (an instance of the brute family that has one): the builder, the pruning and the evaluator are given it. */
  const procs = readProcs(inputs.procs ?? null, inputs.trio);
  /** The options of a recorded solve or pruning, with the Monk bins the builder reads from the bundle and the table of procs of the case. */
  const withBins = (options) => Object.freeze({ ...deepFreeze({ ...clone(options), ...(bins === undefined ? {} : { monk_bins: bins }) }), ...(procs === null ? {} : { procs }) });
  return {
    doc,
    profile,
    procs,
    setup: inputs.setup,
    buffset: inputs.buffset === null ? null : deepFreeze(clone(inputs.buffset)),
    bins,
    itemAt,
    itemNamed,
    withBins,
    poolOf: (solve) => solve.pool.map(itemNamed),
    optionsOf: (solve) => withBins(solve.options),
    /** An Upgrade case's owned set: `[item, count]` pairs. */
    owned: () => (inputs.owned ?? []).map(([name, count]) => [itemNamed(name), count]),
    /** An Upgrade case's candidates. */
    candidates: () => (inputs.candidates ?? []).map(itemNamed),
  };
}

/**
 * Check that the solver's model of a scenario is the model JSON of it (rows in the order the scenario lists them, columns in the order of the model): the
 * costs, the bounds, the kinds of the columns, and every row by name with its bounds and entries. `expect` is vitest's, `highs` the loaded solver.
 */
export function solverIs(expect, highs, session, name) {
  const scenario = session.scenarios.get(name);
  const model = scenario.model;
  const got = scenario.solver.getModel("csr");
  const inf = highs.infinity;
  const orInf = (value, sign) => (value === null ? sign * inf : value);
  expect(got.numCols).toBe(model.c.length);
  expect(got.numRows).toBe(model.row_lb.length);
  expect(scenario.rowNames.length).toBe(model.row_lb.length);
  expect(Array.from(got.colCost)).toEqual(model.c);
  expect(Array.from(got.colLower)).toEqual(model.col_lb.map((value) => orInf(value, -1)));
  expect(Array.from(got.colUpper)).toEqual(model.col_ub.map((value) => orInf(value, 1)));
  expect(Array.from(got.integrality)).toEqual(model.integrality);
  const rowAt = new Map(model.row_names.map((rowName, at) => [rowName, at]));
  expect(new Set(scenario.rowNames).size, "a row name twice").toBe(scenario.rowNames.length);
  scenario.rowNames.forEach((rowName, r) => {
    const m = rowAt.get(rowName);
    expect(m, `the solver has a row ${rowName} that the model has not`).not.toBeUndefined();
    expect(got.rowLower[r], rowName).toBe(orInf(model.row_lb[m], -1));
    expect(got.rowUpper[r], rowName).toBe(orInf(model.row_ub[m], 1));
    const have = [];
    for (let k = got.matrix.starts[r]; k < got.matrix.starts[r + 1]; k += 1) have.push([got.matrix.indices[k], got.matrix.values[k]]);
    have.sort((a, b) => a[0] - b[0]);
    const want = [];
    for (let k = model.A.start[m]; k < model.A.start[m + 1]; k += 1) want.push([model.A.index[k], model.A.value[k]]);
    expect(have, rowName).toEqual(want);
  });
}
