import loadHighs from "highs";
import { beforeAll, describe, expect, it } from "vitest";
import { EvaluateError, SLOT_INSTANCES, evaluate, profileOf } from "../pipeline/trioforge/site/static/engine/evaluate.js";
import { CLASS_CODES, atTier } from "../pipeline/trioforge/site/static/engine/items.js";
import { LIMIT, compare } from "../pipeline/trioforge/site/static/engine/milpjson.js";
import { ModelError, buildMilp, ident, planTopPools } from "../pipeline/trioforge/site/static/engine/model.js";
import { readBundle } from "../pipeline/trioforge/site/static/engine/profile.js";
import { PROTOCOL_VERSION, validateRequest } from "../pipeline/trioforge/site/static/engine/protocol.js";
import { Rational } from "../pipeline/trioforge/site/static/engine/rational.js";
import { solveModelWith } from "../pipeline/trioforge/site/static/engine/worker.js";
import { mulberry32 } from "./engine-models.mjs";
import { SAMPLE, describeFull } from "./engine-fixtures.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

// The MILP builder of the browser (static/engine/model.js) held to the Python one (pipeline/trioforge/solver/model.py) by the parity fixtures.
//
//   * Model parity. For every case of matrix/, upgrade/ and pmb36/ (and brute/), and each of its solves, the model that buildMilp makes from the
//     case's profile (always `inputs.profile`: the profile of a strict-proxy case cannot be assembled again), the pool of the solve (items read
//     from the records at their tiers), the case's buff set and setup and the options of the solve is the model JSON that Python made: `compare`
//     (milpjson.js) finds no difference under the parity rules, and the info of the build is the same too.
//   * Solving in Node. The model is solved by HiGHS (highs-js 1.15.3) the way the worker solves one (`solveModelWith`, with the options of the
//     Python solver that this build takes: no relative gap, presolve off, seed 0 ... ; the build has one thread and refuses the option), and its
//     objective is the exact value F that Python found, to 1e-9 relative. The kit that comes out is valued by the exact evaluator, which must
//     not be below the model's own value (a model never overstates its kit).
//   * Brute force. The brute/ cases are small invented instances whose best kit was found by trying every legal kit and buff set: F is that value.

const FAMILIES = ["matrix", "upgrade", "pmb36", "brute"];
const REL = 1e-9;
const clone = (value) => JSON.parse(JSON.stringify(value));

/** A copy that nothing can change, all through (so that the builder can only read what it is given). */
function deepFreeze(value) {
  const stack = [value];
  while (stack.length > 0) {
    const node = stack.pop();
    if (node === null || typeof node !== "object" || Object.isFrozen(node)) continue;
    Object.freeze(node);
    for (const child of Array.isArray(node) ? node : Object.values(node)) stack.push(child);
  }
  return value;
}

const relative = (got, want) => Math.abs(got - want) / Math.max(1, Math.abs(want));
/** An exact "p/q" text as a double (a text of the brute-force values can be longer than the 64 digits a bundle takes). */
const exactNumber = (text) => Rational.parseLong(text).toNumber();

// ---- reading a case ----------------------------------------------------------------------------------------------------------------

/** What every case of a set shares: the rules of the tiers of each level (the bundles) and the Monk bins of each level (the evaluator's listing). */
function sharedOf(set) {
  const rules = new Map();
  for (const path of set.paths("bundle")) {
    const bundle = readBundle(set.read(path));
    if (!rules.has(bundle.level)) rules.set(bundle.level, bundle);
  }
  return { rules, bins: set.read("evaluate/profiles.json").monk_bins };
}

/** The inputs of a case as the builder takes them, and the items of its pool (each read once). */
function caseOf(shared, doc) {
  const { inputs } = doc;
  const profile = deepFreeze(clone(inputs.profile));
  const records = new Map(doc.records.map((record) => [record.key ?? `w${record.id}`, record]));
  const rules = shared.rules.get(inputs.level) ?? [...shared.rules.values()][0];
  const items = new Map();
  const itemAt = (key, tier) => {
    const ident = `${key}@${tier}`;
    if (!items.has(ident)) items.set(ident, atTier(records.get(key), tier, rules, { weaponPct: inputs.weapon_pct }));
    return items.get(ident);
  };
  const bins = profile.monk === null ? undefined : deepFreeze(clone(shared.bins[String(inputs.level)]));
  return {
    doc,
    profile,
    setup: inputs.setup,
    buffset: inputs.buffset === null ? null : deepFreeze(clone(inputs.buffset)),
    bins,
    itemAt,
    poolOf: (solve) => solve.pool.map((ident) => itemAt(ident.slice(0, ident.lastIndexOf("@")), Number(ident.slice(ident.lastIndexOf("@") + 1)))),
    optionsOf: (solve) => deepFreeze({ ...clone(solve.options), ...(bins === undefined ? {} : { monk_bins: bins }) }),
  };
}

/** The list in an order of its own, the same for the same seed. */
function shuffled(list, seed) {
  const random = mulberry32(seed);
  const copy = [...list];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

/** The options with the owned caps, the upgrades and the new items listed the other way round. */
function reversedOptions(options) {
  return deepFreeze({
    ...clone(options),
    owned_caps: Object.fromEntries(Object.entries(options.owned_caps ?? {}).reverse()),
    new_keys: [...(options.new_keys ?? [])].reverse(),
    upgrades: Object.fromEntries(Object.entries(options.upgrades ?? {}).reverse()),
  });
}

const BUILT = new WeakMap();
/** The model that the port builds for a solve of a case (once). */
function builtFor(c, solve) {
  if (!BUILT.has(solve)) BUILT.set(solve, buildMilp(c.profile, c.poolOf(solve), c.setup, c.buffset, c.optionsOf(solve)));
  return BUILT.get(solve);
}

// ---- parity with the Python models ------------------------------------------------------------------------------------------------

function parityTests(set) {
  const shared = sharedOf(set);

  for (const family of FAMILIES) {
    const paths = set.paths("case", `${family}/`);
    describe(`${family}/`, () => {
      it("has cases", () => {
        expect(paths.length).toBeGreaterThan(0);
      });

      for (const path of paths) {
        const doc = set.read(path);
        it(`${doc.id} (${doc.label}): every model is the model Python made`, () => {
          const c = caseOf(shared, doc);
          expect(doc.solves.length).toBeGreaterThan(0);
          for (const [number, solve] of doc.solves.entries()) {
            const model = builtFor(c, solve);
            const differences = compare(model, solve.model);
            expect(differences.slice(0, 5), `${doc.id} ${solve.label}`).toEqual([]);
            expect(model.info, `${doc.id} ${solve.label}: the info of the build`).toEqual(solve.model.info);
            // what the browser's reader takes is what the worker is sent
            expect(() => validateRequest({ v: PROTOCOL_VERSION, kind: "model", model, budgetMs: 1000 }), `${doc.id} ${solve.label}`).not.toThrow();
            // The rule is a tolerance of 1e-12, but the builder is exact, as Python's is: the doubles are the very ones Python wrote, and the text is too.
            expect(JSON.stringify(model) === JSON.stringify(solve.model), `${doc.id} ${solve.label}: the document is not the one Python wrote, to the last digit`).toBe(true);
            // and the model does not depend on the order of the pool or of the mappings of the options
            const again = buildMilp(c.profile, shuffled(c.poolOf(solve), number + 1), c.setup, c.buffset, reversedOptions(c.optionsOf(solve)));
            expect(JSON.stringify(again) === JSON.stringify(model), `${doc.id} ${solve.label}: the model depends on the order of its inputs`).toBe(true);
          }
        });
      }
    });
  }
}

describe("the committed sample", () => parityTests(SAMPLE));
describeFull("the full set", (full) => parityTests(full));

// ---- the model JSON compare -----------------------------------------------------------------------------------------------------------

describe("compare", () => {
  const doc = SAMPLE.read(SAMPLE.paths("case", "brute/")[0]);
  const base = doc.solves[0].model;
  const copy = () => clone(base);
  /** A row of the model that has at least two entries, and the name of its first column. */
  const rowAt = (model) => {
    const r = model.row_names.findIndex((_, i) => model.A.start[i + 1] - model.A.start[i] >= 2);
    return { r, k: model.A.start[r], name: model.row_names[r], column: model.col_names[model.A.index[model.A.start[r]]] };
  };

  it("finds no difference between a model and itself, or its copy", () => {
    expect(compare(base, base)).toEqual([]);
    expect(compare(base, copy())).toEqual([]);
  });

  it("takes the text of a document as well as the document", () => {
    expect(compare(JSON.stringify(base), base)).toEqual([]);
    expect(compare(base, JSON.stringify(base))).toEqual([]);
    expect(compare("not json", "not json")[0]).toMatch(/^invalid model a:/);
  });

  it("does not compare the info, which only describes the build", () => {
    const other = copy();
    other.info = { rows: -1, anything: ["at", "all"] };
    expect(compare(base, other)).toEqual([]);
  });

  it("names the row and the column of a coefficient that differs, and no other", () => {
    const { k, name, column } = rowAt(base);
    const other = copy();
    other.A.value[k] *= 1.001;
    expect(compare(base, other)).toEqual([`coefficient differs: row ${name}, column ${column} (${base.A.value[k]} vs ${other.A.value[k]})`]);
  });

  it("holds coefficients and bounds to 1e-12 relative, with a floor of 1 on their size", () => {
    const { k } = rowAt(base);
    const withValue = (value) => {
      const model = copy();
      model.A.value[k] = value;
      return model;
    };
    // a size above 1 is held to 1e-12 of itself
    expect(compare(withValue(1e9), withValue(1e9 * (1 + 0.9e-12)))).toEqual([]);
    expect(compare(withValue(1e9), withValue(1e9 * (1 + 1.1e-12)))).toHaveLength(1);
    // a size below 1 is held to an absolute 1e-12
    expect(compare(withValue(0.25), withValue(0.25 + 0.9e-12))).toEqual([]);
    expect(compare(withValue(0.25), withValue(0.25 + 1.1e-12))).toHaveLength(1);
    // the constant and an objective coefficient follow the same rule
    const constant = copy();
    constant.const = base.const + 1e-6;
    expect(compare(base, constant)).toEqual([`constant differs: ${base.const} vs ${constant.const}`]);
    const near = copy();
    near.const = base.const + 0.5e-9;
    expect(compare(base, near)).toEqual([]);
    const cost = copy();
    const at = base.c.findIndex((value) => value !== 0);
    cost.c[at] = base.c[at] * 1.001;
    expect(compare(base, cost)).toEqual([`objective coefficient differs: ${base.col_names[at]} (${base.c[at]} vs ${cost.c[at]})`]);
  });

  it("takes a coefficient that is missing and one that is stored as 0 for the same", () => {
    const { r, k } = rowAt(base);
    const stored = copy();
    stored.A.value[k] = 0;
    const missing = copy();
    missing.A.index.splice(k, 1);
    missing.A.value.splice(k, 1);
    for (let i = r + 1; i < missing.A.start.length; i += 1) missing.A.start[i] -= 1;
    expect(compare(stored, missing)).toEqual([]);
    expect(compare(missing, stored)).toEqual([]);
    expect(compare(base, missing)).toHaveLength(1);
  });

  it("names a bound that differs, an infinite one only agreeing with an infinite one", () => {
    const finite = base.row_ub.findIndex((value) => value !== null);
    const open = copy();
    open.row_ub[finite] = null;
    expect(compare(base, open)).toEqual([`row upper bound differs: ${base.row_names[finite]} (${base.row_ub[finite]} vs unbounded)`]);
    expect(compare(open, base)).toEqual([`row upper bound differs: ${base.row_names[finite]} (unbounded vs ${base.row_ub[finite]})`]);
    const lower = base.col_ub.findIndex((value) => value !== null);
    const wider = copy();
    wider.col_ub[lower] += 1;
    expect(compare(base, wider)).toEqual([`column upper bound differs: ${base.col_names[lower]} (${base.col_ub[lower]} vs ${wider.col_ub[lower]})`]);
    const shifted = copy();
    shifted.col_lb[lower] = -1;
    expect(compare(base, shifted)).toEqual([`column lower bound differs: ${base.col_names[lower]} (${base.col_lb[lower]} vs -1)`]);
  });

  it("names an integrality flag that differs", () => {
    const at = base.integrality.indexOf(1);
    const other = copy();
    other.integrality[at] = 0;
    expect(compare(base, other)).toEqual([`integrality differs: ${base.col_names[at]}`]);
  });

  it("names the column or the row that one side lacks, and a change of order of those both have", () => {
    const fewer = copy();
    const last = fewer.col_names.length - 1;
    // drop the last column (it is in no row of the model, or the rows are cut to match)
    const dropped = fewer.col_names[last];
    fewer.col_names.pop();
    fewer.col_lb.pop();
    fewer.col_ub.pop();
    fewer.integrality.pop();
    fewer.c.pop();
    const index = [];
    const value = [];
    const start = [0];
    for (let r = 0; r < fewer.row_names.length; r += 1) {
      for (let k = base.A.start[r]; k < base.A.start[r + 1]; k += 1) {
        if (base.A.index[k] !== last) {
          index.push(base.A.index[k]);
          value.push(base.A.value[k]);
        }
      }
      start.push(index.length);
    }
    fewer.A = { start, index, value };
    fewer.item_cols = fewer.item_cols.filter(([column]) => column !== last);
    fewer.buff_cols = fewer.buff_cols.filter(([column]) => column !== last);
    expect(compare(base, fewer)[0]).toBe(`missing column: ${dropped}`);
    expect(compare(fewer, base)[0]).toBe(`extra column: ${dropped}`);

    const renamed = copy();
    renamed.row_names[0] = "renamed";
    expect(compare(base, renamed).slice(0, 2)).toEqual([`missing row: ${base.row_names[0]}`, "extra row: renamed"]);

    // two columns swapped (names, bounds, costs and the entries of every row move together)
    const swapped = copy();
    const [i, j] = [0, 1];
    for (const key of ["col_names", "col_lb", "col_ub", "integrality", "c"]) [swapped[key][i], swapped[key][j]] = [swapped[key][j], swapped[key][i]];
    swapped.A.index = swapped.A.index.map((column) => (column === i ? j : column === j ? i : column));
    for (let r = 0; r < swapped.row_names.length; r += 1) {
      const from = swapped.A.start[r];
      const to = swapped.A.start[r + 1];
      const pairs = swapped.A.index.slice(from, to).map((column, n) => [column, swapped.A.value[from + n]]).sort((a, b) => a[0] - b[0]);
      pairs.forEach(([column, entry], n) => {
        swapped.A.index[from + n] = column;
        swapped.A.value[from + n] = entry;
      });
    }
    swapped.item_cols = swapped.item_cols.map(([column, ...rest]) => [column === i ? j : column === j ? i : column, ...rest]);
    swapped.buff_cols = swapped.buff_cols.map(([column, ...rest]) => [column === i ? j : column === j ? i : column, ...rest]);
    const order = compare(base, swapped);
    expect(order[0]).toBe(`column order changed: first difference at position 0 (${base.col_names[0]} vs ${base.col_names[1]})`);
  });

  it("names the first column or row that differs first, ahead of the sense and the constant", () => {
    const { r, k, name } = rowAt(base);
    const other = copy();
    other.A.value[k] += 1;
    other.const += 1;
    other.sense = "min";
    const differences = compare(base, other);
    expect(differences).toHaveLength(3);
    expect(differences[0]).toMatch(new RegExp(`^coefficient differs: row ${name.replace(/[$()*+.?[\\\]^{|}]/g, "\\$&")}, `));
    expect(differences[1]).toMatch(/^sense differs/);
    expect(differences[2]).toMatch(/^constant differs/);
    expect(r).toBeGreaterThanOrEqual(0);
  });

  it("lists the rows in the order of the first document, so that the first row that differs comes first", () => {
    const entries = [];
    for (let r = 0; r < base.row_names.length && entries.length < 3; r += 1) {
      if (base.row_ub[r] !== null) entries.push(r);
    }
    expect(entries.length).toBe(3);
    const other = copy();
    for (const r of entries) other.row_ub[r] += 1;
    const differences = compare(base, other);
    expect(differences.map((line) => line.split(": ")[1].split(" (")[0])).toEqual(entries.map((r) => base.row_names[r]));
  });

  it("names the item or buff column that differs", () => {
    const other = copy();
    other.item_cols[0] = [other.item_cols[0][0], "OTHER", other.item_cols[0][2], other.item_cols[0][3]];
    expect(compare(base, other)[0]).toBe(
      `item columns differ: first difference at position 0 (${JSON.stringify([base.col_names[base.item_cols[0][0]], ...base.item_cols[0].slice(1)])} vs ${JSON.stringify([base.col_names[base.item_cols[0][0]], "OTHER", ...base.item_cols[0].slice(2)])})`,
    );
    const fewer = copy();
    fewer.item_cols = fewer.item_cols.slice(0, -1);
    expect(compare(base, fewer)[0]).toMatch(/^item columns differ: first difference at position \d+ \(.*vs none\)$/);
  });

  it("reports another version alone, and a document that is not a model by what the browser's reader refuses in it", () => {
    const other = copy();
    other.version = 2;
    expect(compare(base, other)).toEqual(["version differs: 1 vs 2"]);
    const extra = copy();
    extra.surprise = true;
    expect(compare(base, extra)).toHaveLength(1);
    expect(compare(base, extra)[0]).toMatch(/^invalid model b: /);
    expect(compare(extra, base)[0]).toMatch(/^invalid model a: /);
    expect(compare(null, base)).toEqual(["invalid model a: the document is not an object"]); // not "version differs: undefined vs 1"
    const bad = copy();
    bad.A.start[1] = -1;
    expect(compare(base, bad)[0]).toMatch(/^invalid model b: /);
  });

  it("reports text that is not JSON, and a document that is not an object, as invalid before it looks at a version", () => {
    const cutOff = JSON.stringify(base).slice(0, 40); // text that stops short
    expect(cutOff).not.toBe(JSON.stringify(base));
    expect(compare(base, cutOff)).toEqual(["invalid model b: the text is not JSON"]); // not "version differs: 1 vs undefined"
    expect(compare(cutOff, base)).toEqual(["invalid model a: the text is not JSON"]);
    expect(compare(cutOff, cutOff)).toEqual(["invalid model a: the text is not JSON", "invalid model b: the text is not JSON"]);
    for (const text of ["", " ", "{", "{'version': 1}", "undefined", "NaN", "{\"version\": 1,}", "model"]) {
      expect(compare(base, text), JSON.stringify(text)).toEqual(["invalid model b: the text is not JSON"]);
    }
    // text that says null or a number is JSON, but not a model: it is told apart from text that is not JSON
    for (const given of [null, undefined, "null", [], "[]", 5, "5", true, "true", "\"model\"", () => 1, Symbol("model")]) {
      expect(compare(base, given), String(typeof given === "symbol" ? "symbol" : JSON.stringify(given) ?? given)).toEqual(["invalid model b: the document is not an object"]);
      expect(compare(given, base)).toEqual(["invalid model a: the document is not an object"]);
    }
    expect(compare("null", cutOff)).toEqual(["invalid model a: the document is not an object", "invalid model b: the text is not JSON"]);
    // another version alongside a document that is no document: the faults come first, the versions are not compared
    const other = copy();
    other.version = 2;
    expect(compare(other, cutOff)).toEqual(["invalid model b: the text is not JSON"]);
    expect(compare(cutOff, other)).toEqual(["invalid model a: the text is not JSON"]);
    expect(compare(other, null)).toEqual(["invalid model b: the document is not an object"]);
    expect(compare(other, base)).toEqual(["version differs: 2 vs 1"]);
    // an object with no version is still compared by its version (the reader's faults come after)
    const unversioned = copy();
    delete unversioned.version;
    expect(compare(unversioned, base)).toEqual(["version differs: undefined vs 1"]);
    // the limit cuts the faults too
    expect(compare(cutOff, cutOff, { limit: 1 })).toEqual(["invalid model a: the text is not JSON", "... and 1 more"]);
  });

  it("cuts a long list at the limit and counts the rest", () => {
    const other = copy();
    other.c = other.c.map((value) => value + 1);
    const all = compare(base, other, { limit: 1000 });
    expect(all).toHaveLength(base.c.length);
    const cut = compare(base, other, { limit: 3 });
    expect(cut).toEqual([...all.slice(0, 3), `... and ${all.length - 3} more`]);
    expect(compare(base, other)).toHaveLength(Math.min(all.length, LIMIT) + (all.length > LIMIT ? 1 : 0));
  });

  it("refuses an option it does not read, and a limit that is not a whole number of at least 1", () => {
    expect(() => compare(base, base, { limits: 3 })).toThrow(/limits/);
    for (const limit of [0, -1, 1.5, "3", NaN]) expect(() => compare(base, base, { limit })).toThrow(TypeError);
    expect(() => compare(base, base, [])).toThrow(TypeError);
  });
});

// ---- solving the models in Node ------------------------------------------------------------------------------------------------------------

/** HiGHS as the worker runs it (in Node it reads its own file), started once for this file. */
let highs;
beforeAll(async () => {
  highs = await loadHighs();
});

/** The kit (22 places, from `itemOf(key, tier)`) and the chosen optional buffs of a solution vector. */
function decode(model, x, itemOf) {
  const kit = new Array(SLOT_INSTANCES.length).fill(null);
  for (const [column, group, key, tier] of model.item_cols) {
    for (let copy = 0; copy < Math.round(x[column]); copy += 1) {
      const place = SLOT_INSTANCES.findIndex((name, at) => name === group && kit[at] === null);
      expect(place, `no place left in ${group}`).toBeGreaterThanOrEqual(0);
      kit[place] = itemOf(key, tier);
    }
  }
  const buffs = model.buff_cols.filter(([column]) => Math.round(x[column]) === 1).map(([, id]) => id);
  return { kit, buffs };
}

function solveTests(set, families) {
  const shared = sharedOf(set);

  for (const family of families) {
    describe(`${family}/`, () => {
      for (const path of set.paths("case", `${family}/`)) {
        const doc = set.read(path);
        it(`${doc.id} (${doc.label}): the optimum of every model is the exact value F that Python found`, () => {
          const c = caseOf(shared, doc);
          for (const solve of doc.solves) {
            const model = builtFor(c, solve);
            const want = exactNumber(solve.result.F);
            const got = solveModelWith(highs, model, { budgetMs: 120_000, startedAt: performance.now(), onProgress() {} });
            expect(got.status, `${doc.id} ${solve.label}`).toBe("optimal");
            expect(got.proven).toBe(true);
            expect(relative(got.objective, want), `${doc.id} ${solve.label}: ${got.objective} against ${want}`).toBeLessThanOrEqual(REL);

            // the kit the solver found, valued exactly: the model never overstates it (the check of the Python solver, 1e-6 relative), and
            // since the model's optimum is the best value of any kit, the kit is worth that
            const { kit, buffs } = decode(model, got.x, c.itemAt);
            const options = { setup: c.setup, hasteAssumed: model.info.haste_assumed, monkBins: c.bins, buffset: c.buffset ?? undefined };
            const exact = evaluate(c.profile, kit, c.buffset === null ? null : buffs, options).F.toNumber();
            expect(got.objective, `${doc.id} ${solve.label}: the model overstates its kit`).toBeLessThanOrEqual(exact + 1e-6 * Math.max(1, Math.abs(exact)));
            expect(relative(exact, want), `${doc.id} ${solve.label}: the kit is worth ${exact}`).toBeLessThanOrEqual(REL);
          }
        }, 120_000);
      }
    });
  }
}

describe("solving in Node, the committed sample", () => solveTests(SAMPLE, ["matrix", "upgrade", "pmb36"]));
describeFull("solving in Node, the full set", (full) => solveTests(full, ["matrix", "upgrade", "pmb36"]));

// ---- brute force ------------------------------------------------------------------------------------------------------------------------

function bruteTests(set) {
  const shared = sharedOf(set);

  for (const path of set.paths("case", "brute/")) {
    const doc = set.read(path);
    it(`${doc.id} (${doc.label}): F is the best of every legal kit and buff set`, () => {
      const c = caseOf(shared, doc);
      expect(doc.solves).toHaveLength(1);
      const [solve] = doc.solves;
      const model = builtFor(c, solve);
      const brute = Rational.parseLong(doc.expected.brute_F);
      const got = solveModelWith(highs, model, { budgetMs: 60_000, startedAt: performance.now(), onProgress() {} });
      expect(got.status).toBe("optimal");
      expect(relative(got.objective, brute.toNumber()), `${doc.id}: ${got.objective} against ${brute.toString()}`).toBeLessThanOrEqual(REL);
      // the kit is worth the brute-force value, exactly
      const { kit, buffs } = decode(model, got.x, c.itemAt);
      const options = { setup: c.setup, hasteAssumed: model.info.haste_assumed, monkBins: c.bins, buffset: c.buffset ?? undefined };
      const exact = evaluate(c.profile, kit, c.buffset === null ? null : buffs, options).F;
      expect(relative(exact.toNumber(), brute.toNumber()), `${doc.id}: the kit is worth ${exact.toString()}`).toBeLessThanOrEqual(REL);
    }, 60_000);
  }
}

describe("brute force, the committed sample", () => bruteTests(SAMPLE));
describeFull("brute force, the full set", (full) => bruteTests(full));

// ---- hand-made models ---------------------------------------------------------------------------------------------------------------------
//
// Small models that are worked out by hand, in the way of pipeline/tests/test_milp_small.py and test_milp_owned.py: what the parity fixtures cannot
// say because Python never made the model (a refusal, a name that repeats, a key that sorts differently by code point), and the structure that a
// reader of the builder wants pinned (which rows a rule makes, and when it makes none). Where a model is solved, the answer is valued by the exact
// evaluator and the model's own objective must be that value. Every name, race and item here is invented.

const q = (numerator, denominator = 1) => new Rational(BigInt(numerator), BigInt(denominator));
const NAKED = { STR: 100, STA: 100, AGI: 100, DEX: 100, WIS: 100, INT: 100, CHA: 100 };
const POOLS = {
  HP: [{ cls: "WAR", base: 1500, fac: 5 }, { cls: "CLR", base: 1320, fac: 4.4 }, { cls: "ENC", base: 1200, fac: 4 }],
  MANA: [{ cls: "CLR", base: 900, fac: 4.5, stat: "WIS" }, { cls: "ENC", base: 900, fac: 4.5, stat: "INT" }],
  END: [{ cls: "WAR", base: 900, fac: 4.5 }, { cls: "CLR", base: 456, fac: 3.25 }, { cls: "ENC", base: 260, fac: 1.25 }],
};

/** A profile like an evaluator's: it has no race, no deity and no spell haste (the builder reads the haste on offer from the buffs). */
function profileWith(changes = {}) {
  return deepFreeze({
    level: 50,
    naked: { ...NAKED },
    weights: {},
    pools: clone(POOLS),
    buff_totals: {},
    haste_cap: 75,
    softcap: [0, 0],
    cs_pct: 0,
    pe_pct: 0,
    defense_cap: 0,
    monk: null,
    iksar_ac: 0,
    placement: { monk: "top", iksar: "top" },
    caps: { regen: { HP: 30, MANA: 15, END: 15 }, resist: 200 },
    bands: null,
    dw_factor: 1,
    ...clone(changes),
  });
}

/** An item as atTier gives it. */
function gear(key, slots, more = {}) {
  const { stats = {}, sv = {}, haste = 0, weight10 = 0, lore = false, weapon = null, shield = false, classes = CLASS_CODES, deity = null, races = null, tier = 0 } = more;
  return deepFreeze({
    key,
    name: key,
    slots: [...slots].sort(),
    classes: [...classes],
    deity,
    lore,
    stats: Object.fromEntries(Object.entries(stats).filter(([, amount]) => amount !== 0)),
    sv,
    haste,
    weight10,
    weapon,
    is_shield: shield,
    tier,
    weight_known: true,
    races,
  });
}
const oneHand = (dmg, delay, bonus = null) => ({ skill: "1H Slashing", dmg, delay, bonus, two_handed: false });
const twoHand = (dmg, delay, bonus = null) => ({ skill: "2H Slashing", dmg, delay, bonus, two_handed: true });

/** A buff set as the bundle writes it, from `{id, ...components}` buffs. */
function buffsetOf({ always = [], optional = [], conflicts = [], cliques, cardinality = null }) {
  const table = {};
  for (const { id, ...vec } of [...always, ...optional]) table[String(id)] = { name: `buff-${id}`, classes: {}, vec, source: "own" };
  const pairs = [...conflicts].map(([a, b]) => (a < b ? [a, b] : [b, a])).sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  return deepFreeze({
    set: {
      always_on: always.map(({ id }) => id).sort((a, b) => a - b),
      optional: optional.map(({ id }) => id).sort((a, b) => a - b),
      conflicts: pairs.map(([a, b]) => [a, b, ["test"]]),
      cliques: (cliques ?? pairs).map((clique) => [...clique]),
      cardinality,
      dropped: [],
    },
    table,
  });
}
const buffOf = (id, vec = {}) => ({ id, ...vec });

/** The model of a hand-made scenario; the Any group takes only the items that list it, and no haste is assumed, unless the options say otherwise. */
function modelOf(profile, items, { setup = "stick", buffset = null, ...options } = {}) {
  return buildMilp(profile, items, setup, buffset, { any_rule: "explicit", haste_assumed: 0, ...options });
}

/** The group of each copy that a solution wears, and `{ident: copies}`. */
function wornIn(model, x) {
  const groups = {};
  const idents = {};
  for (const [column, group, key, tier] of model.item_cols) {
    for (let copy = 0; copy < Math.round(x[column]); copy += 1) {
      (groups[group] ??= []).push(key);
      idents[`${key}@${tier}`] = (idents[`${key}@${tier}`] ?? 0) + 1;
    }
  }
  for (const keys of Object.values(groups)) keys.sort();
  return { groups, idents };
}

const columnsOf = (model, group) => model.item_cols.filter(([, name]) => name === group).map(([, , key]) => key).sort();
const rowsNamed = (model, prefix) => model.row_names.filter((name) => name.startsWith(prefix));
/** `{column name: coefficient}` of the row called `name`. */
function rowOf(model, name) {
  const r = model.row_names.indexOf(name);
  expect(r, `no row called ${name}`).toBeGreaterThanOrEqual(0);
  const entries = {};
  for (let k = model.A.start[r]; k < model.A.start[r + 1]; k += 1) entries[model.col_names[model.A.index[k]]] = model.A.value[k];
  return entries;
}

/**
 * Build, solve and value the answer exactly (the model's objective must be the exact value of its kit). `force` is a list of [group, key] columns
 * to wear at least once. Returns the model, what is worn, the chosen buffs and the exact F.
 */
function solved(profile, items, { force = [], ...scenario } = {}) {
  const model = modelOf(profile, items, scenario);
  const document = clone(model);
  for (const [group, key] of force) document.col_lb[document.col_names.indexOf(`n[${group}|${key}]`)] = 1;
  const got = solveModelWith(highs, document, { budgetMs: 60_000, startedAt: performance.now(), onProgress() {} });
  expect(got.status).toBe("optimal");
  const byIdent = new Map(items.map((item) => [`${item.key}@${item.tier}`, item]));
  const { kit, buffs } = decode(model, got.x, (key, tier) => byIdent.get(`${key}@${tier}`));
  const buffset = scenario.buffset ?? null;
  const options = { setup: scenario.setup ?? "stick", hasteAssumed: model.info.haste_assumed, buffset: buffset ?? undefined, monkBins: scenario.monk_bins };
  const exact = evaluate(profile, kit, buffset === null ? null : buffs, options).F;
  expect(relative(got.objective, exact.toNumber()), `the model's ${got.objective} against the kit's ${exact.toString()}`).toBeLessThanOrEqual(1e-9);
  return { model, ...wornIn(model, got.x), buffs, exact };
}
const empty = (profile) => evaluate(profile, new Array(SLOT_INSTANCES.length).fill(null)).F;

describe("hand-made models", () => {
  // -- slots, copies, Lore -----------------------------------------------------------------------------------------------------------------

  it("wears the best of three items in a place, and values the kit as the evaluator does", () => {
    const profile = profileWith({ weights: { HP: 1 } });
    const items = [10, 20, 15].map((sta) => gear(`h${sta}`, ["HEAD"], { stats: { STA: sta } }));
    const { groups, exact } = solved(profile, items);
    expect(groups.HEAD).toEqual(["h20"]);
    // STA 120: the pools of WAR (5 + 1500 + 5 x 120) and CLR (5 + 1320 + 4.4 x 120) count
    expect(exact.toString()).toBe("3958/1");
  });

  it("leaves a place empty when every item hurts", () => {
    const profile = profileWith({ weights: { HP: 1, END: 1 } });
    const { groups, exact } = solved(profile, [gear("bad", ["HEAD"], { stats: { STA: -30, HP: -50 } })]);
    expect(groups.HEAD).toBeUndefined();
    expect(exact.equals(empty(profile))).toBe(true);
  });

  it("wears a Lore item once over every group, and an item that is not Lore in every place", () => {
    const profile = profileWith({ weights: { HP: 1 } });
    const lore = solved(profile, [gear("lore-ring", ["FINGER", "EAR"], { stats: { HP: 100 }, lore: true })]);
    expect(Object.values(lore.groups).flat()).toHaveLength(1);
    expect(lore.exact.equals(empty(profile).add(100))).toBe(true);
    const plain = solved(profile, [gear("plain-ring", ["FINGER", "EAR"], { stats: { HP: 100 } })]);
    expect(plain.groups).toEqual({ FINGER: ["plain-ring", "plain-ring"], EAR: ["plain-ring", "plain-ring"] });
    expect(plain.exact.equals(empty(profile).add(400))).toBe(true);
  });

  it("lets two Lore items of different keys both be worn, and holds a group to its places", () => {
    const profile = profileWith({ weights: { HP: 1 } });
    const lore = solved(profile, [gear("lore-a", ["FINGER"], { stats: { HP: 100 }, lore: true }), gear("lore-b", ["FINGER"], { stats: { HP: 90 }, lore: true })]);
    expect(lore.groups.FINGER).toEqual(["lore-a", "lore-b"]);
    const crowded = solved(profile, [
      gear("c1", ["CHEST"], { stats: { HP: 100 } }),
      gear("c2", ["CHEST"], { stats: { HP: 90 } }),
      gear("w", ["WRIST"], { stats: { HP: 10 } }),
    ]);
    expect(crowded.groups).toEqual({ CHEST: ["c1"], WRIST: ["w", "w"] });
    // the rows: a group has one only when its columns could add up to more than its places
    expect(rowsNamed(crowded.model, "group.")).toEqual(["group.CHEST"]);
    expect(rowOf(crowded.model, "group.CHEST")).toEqual({ "n[CHEST|c1]": 1, "n[CHEST|c2]": 1 });
  });

  it("makes a row for a Lore key only when it has more than one column, across groups and tiers", () => {
    const profile = profileWith({ weights: { HP: 1 } });
    const items = [
      gear("ring-a", ["FINGER"], { stats: { HP: 5 } }),
      gear("ear-lore", ["EAR"], { stats: { HP: 9 }, lore: true }),
      gear("ear-lore", ["EAR"], { stats: { HP: 9 }, lore: true, tier: 2 }),
      gear("both-lore", ["EAR", "FINGER"], { stats: { HP: 9 }, lore: true }),
    ];
    const model = modelOf(profile, items);
    expect(rowsNamed(model, "lore.")).toEqual(["lore.both-lore", "lore.ear-lore"]); // in the order of the first column of each key
    expect(rowOf(model, "lore.ear-lore")).toEqual({ "n[EAR|ear-lore]": 1, "n[EAR|ear-lore@2]": 1 });
    expect(rowOf(model, "lore.both-lore")).toEqual({ "n[EAR|both-lore]": 1, "n[FINGER|both-lore]": 1 });
    expect(rowsNamed(modelOf(profile, items.slice(0, 2)), "lore.")).toEqual([]);
  });

  it("puts the items that have a slot in the Any group under the all rule, and the items that list Any under the explicit rule", () => {
    const profile = profileWith({ weights: { HP: 1 } });
    const head = gear("head-piece", ["HEAD"], { stats: { HP: 50 } });
    const sword = gear("sword", ["PRIMARY"], { stats: { HP: 30 }, weapon: oneHand(10, 30) });
    const listed = gear("stick-piece", ["ANY"], { stats: { HP: 5 } });
    expect(columnsOf(modelOf(profile, [head, sword, listed]), "ANY")).toEqual(["stick-piece"]);
    expect(columnsOf(modelOf(profile, [head, sword, listed], { any_rule: "all" }), "ANY")).toEqual(["head-piece", "stick-piece", "sword"]);
    const { groups, exact } = solved(profile, [head, sword, listed], { any_rule: "all" });
    expect(groups.ANY).toEqual(["head-piece", "head-piece"]);
    expect(groups.HEAD).toEqual(["head-piece"]);
    expect(groups.PRIMARY).toEqual(["sword"]);
    expect(exact.equals(empty(profile).add(50 + 100 + 30))).toBe(true);
  });

  it("gives an item that fits no group no column, and a model with no column at all is still a model", () => {
    const profile = profileWith({ weights: { HP: 1 } });
    const model = modelOf(profile, [gear("nowhere", [], { stats: { HP: 100 } })], { any_rule: "all" });
    expect(model.item_cols).toEqual([]);
    expect(model.col_names).toEqual([]);
    expect(model.A).toEqual({ start: [0], index: [], value: [] });
    expect(model.info.items).toBe(0);
    expect(() => validateRequest({ v: PROTOCOL_VERSION, kind: "model", model, budgetMs: 1000 })).not.toThrow();
  });

  it("leaves out the items of other classes than the trio's, of a deity the profile does not have, and of other races than the profile's", () => {
    const profile = profileWith({ weights: { HP: 1 } }); // the trio is WAR, CLR and ENC
    const mine = gear("mine", ["HEAD"], { stats: { HP: 10 }, classes: ["WAR"] });
    const other = gear("other", ["HEAD"], { stats: { HP: 99 }, classes: ["MNK"] });
    const god = gear("god", ["HEAD"], { stats: { HP: 98 }, deity: ["Brell"] });
    const keys = (changes) => columnsOf(modelOf(profileWith({ weights: { HP: 1 }, ...changes }), [mine, other, god]), "HEAD");
    expect(keys({})).toEqual(["mine"]); // no deity: the locked item is out
    expect(keys({ deity: "Brell" })).toEqual(["god", "mine"]);
    expect(keys({ deity: "Tunare" })).toEqual(["mine"]);
    const humans = gear("humans", ["HEAD"], { stats: { HP: 99 }, races: ["ELF", "HUM"] });
    const plain = gear("plain", ["HEAD"], { stats: { HP: 10 } });
    const raced = (race) => columnsOf(modelOf(profileWith({ weights: { HP: 1 }, race }), [plain, humans]), "HEAD");
    expect(columnsOf(modelOf(profile, [plain, humans]), "HEAD")).toEqual(["humans", "plain"]); // an evaluator profile has no race: nothing is restricted
    expect(raced("ERU")).toEqual(["plain"]);
    expect(raced("HUM")).toEqual(["humans", "plain"]);
    expect(raced("ELF")).toEqual(["humans", "plain"]);
    // an item that no race may wear (a page that says Race: NONE) has no column for any race
    const nobody = gear("nobody", ["HEAD"], { stats: { HP: 99 }, races: [] });
    expect(columnsOf(modelOf(profileWith({ weights: { HP: 1 }, race: "HUM" }), [plain, nobody]), "HEAD")).toEqual(["plain"]);
  });

  it("sorts the pool by key and tier, by code point, so that the order it comes in changes nothing", () => {
    const profile = profileWith({ weights: { HP: 1, MANA: 1 } });
    const items = Array.from({ length: 6 }, (_, n) => gear(`i${n}`, ["HEAD", "NECK"], { stats: { STA: n, WIS: 6 - n } }));
    const one = modelOf(profile, items);
    const two = modelOf(profile, [...items].reverse());
    expect(JSON.stringify(two)).toBe(JSON.stringify(one));
    // a character beyond the Basic Multilingual Plane sorts after the last of it, as Python sorts text (UTF-16 would put it first)
    const astral = gear("a\u{10000}", ["HEAD"], { stats: { HP: 1 } });
    const high = gear("a￿", ["HEAD"], { stats: { HP: 1 } });
    expect(modelOf(profile, [astral, high]).col_names).toEqual(["n[HEAD|a￿]", "n[HEAD|a\u{10000}]"]);
    expect(modelOf(profile, [high, astral]).col_names).toEqual(["n[HEAD|a￿]", "n[HEAD|a\u{10000}]"]);
    // the same key at several tiers: the first column is called by the key, the others by the key and the tier
    const tiers = [4, 0, 10].map((tier) => gear("band", ["FINGER"], { stats: { HP: 1 }, tier }));
    expect(modelOf(profile, tiers).col_names).toEqual(["n[FINGER|band]", "n[FINGER|band@4]", "n[FINGER|band@10]"]);
  });

  // -- the hands ----------------------------------------------------------------------------------------------------------------------------

  const SWORD = gear("sword", ["PRIMARY", "SECONDARY"], { stats: { STR: 5 }, weapon: oneHand(20, 30) });
  const DAGGER = gear("dagger", ["PRIMARY", "SECONDARY"], { stats: { AGI: 5 }, weapon: { skill: "Piercing", dmg: 8, delay: 20, bonus: 4, two_handed: false } });
  const AXE = gear("axe", ["PRIMARY"], { stats: { STR: 30 }, weapon: twoHand(40, 60) });
  const SHIELD = gear("shield", ["SECONDARY"], { stats: { AC: 20 }, shield: true });
  const LAMP = gear("lamp", ["PRIMARY", "SECONDARY"], { stats: { WIS: 10 } });
  const HANDS = [SWORD, DAGGER, AXE, SHIELD, LAMP];

  it.each([
    ["1h-shield", ["dagger", "sword"], ["shield"]],
    ["2h", ["axe"], []],
    ["dw", ["dagger", "sword"], ["dagger", "sword"]],
    ["stick", ["axe", "dagger", "lamp", "sword"], ["dagger", "lamp", "shield", "sword"]],
  ])("lets the %s setup decide which items stand in each hand", (setup, primary, secondary) => {
    const model = modelOf(profileWith({ weights: { HP: 1 } }), HANDS, { setup });
    expect(columnsOf(model, "PRIMARY")).toEqual(primary);
    expect(columnsOf(model, "SECONDARY")).toEqual(secondary);
  });

  it("makes no column in the off hand for a two-hander that lists it, in any setup, and keeps its other columns", () => {
    const staff = gear("staff", ["BACK", "PRIMARY", "SECONDARY"], { stats: { WIS: 7 }, weapon: { skill: "2H Blunt", dmg: 30, delay: 40, bonus: null, two_handed: true } });
    for (const setup of ["1h-shield", "2h", "dw", "stick"]) {
      const model = modelOf(profileWith({ weights: { HP: 1 } }), [staff, SWORD, DAGGER, SHIELD, LAMP], { setup });
      expect(columnsOf(model, "SECONDARY"), setup).not.toContain("staff");
      expect(columnsOf(model, "PRIMARY").includes("staff"), setup).toBe(setup === "2h" || setup === "stick");
      expect(columnsOf(model, "BACK"), setup).toEqual(["staff"]);
    }
  });

  it("leaves the secondary hand empty beside a two-hander in the primary hand", () => {
    const profile = profileWith({ weights: { AC: 3, ATK: 1 } });
    const forced = solved(profile, HANDS, { force: [["PRIMARY", "axe"]] });
    expect(forced.groups.PRIMARY).toEqual(["axe"]);
    expect(forced.groups.SECONDARY).toBeUndefined(); // the shield's armor class would pay
    expect(Object.keys(rowOf(forced.model, "two_hander")).sort()).toEqual(["n[PRIMARY|axe]", "n[SECONDARY|dagger]", "n[SECONDARY|lamp]", "n[SECONDARY|shield]", "n[SECONDARY|sword]"]);
    const free = solved(profile, HANDS);
    expect(free.groups.SECONDARY).toEqual(["shield"]);
    expect(free.groups.PRIMARY ?? []).not.toContain("axe");
    const twoHanded = solved(profileWith({ weights: { AC: 3, ATK: 1, DMG: 2 } }), HANDS, { setup: "2h" });
    expect(twoHanded.groups.PRIMARY).toEqual(["axe"]);
    expect(twoHanded.groups.SECONDARY).toBeUndefined();
    expect(rowsNamed(twoHanded.model, "two_hander")).toEqual([]); // no off-hand column, so nothing to bind
  });

  it("gives a weapon column the damage index at the assumed haste: the bonus is the main hand's, and the off hand of dual wield takes the factor", () => {
    const profile = profileWith({ weights: { DMG: 2 }, dw_factor: 0.5 });
    const index = (model, group, key) => model.c[model.col_names.indexOf(`n[${group}|${key}]`)];
    const dw = modelOf(profile, [SWORD, DAGGER], { setup: "dw", haste_assumed: 50 });
    // (damage + bonus) / delay x (1 + haste / 100) x the weight; the bonus is the listed one, else half the delay
    expect(index(dw, "PRIMARY", "sword")).toBe(q(2).mul(q(35, 30)).mul(q(3, 2)).toNumber());
    expect(index(dw, "SECONDARY", "sword")).toBe(q(2).mul(q(20, 30)).mul(q(3, 2)).mul(q(1, 2)).toNumber());
    expect(index(dw, "PRIMARY", "dagger")).toBe(q(2).mul(q(12, 20)).mul(q(3, 2)).toNumber());
    expect(index(dw, "SECONDARY", "dagger")).toBe(q(2).mul(q(8, 20)).mul(q(3, 2)).mul(q(1, 2)).toNumber());
    // the shield setup scores the main hand only, the stick scores nothing, a two-hander has a bonus of its own (67 hundredths of the delay)
    const shielded = modelOf(profile, [SWORD, SHIELD], { setup: "1h-shield", haste_assumed: 50 });
    expect(index(shielded, "PRIMARY", "sword")).toBe(q(2).mul(q(35, 30)).mul(q(3, 2)).toNumber());
    expect(index(shielded, "SECONDARY", "shield")).toBe(0);
    const two = modelOf(profile, HANDS, { setup: "2h", haste_assumed: 0 });
    expect(index(two, "PRIMARY", "axe")).toBe(q(2).mul(q(40).add(q(67, 100).mul(q(60)))).div(q(60)).toNumber());
    const stick = modelOf(profile, HANDS, { setup: "stick", haste_assumed: 50 });
    expect(stick.item_cols.filter(([, group]) => group === "PRIMARY" || group === "SECONDARY").every(([column]) => stick.c[column] === 0)).toBe(true);
    // a weapon in an Any place scores its stats and no damage
    const club = gear("club", ["ANY"], { stats: { ATK: 7 }, weapon: oneHand(30, 30) });
    const any = modelOf(profileWith({ weights: { DMG: 5, ATK: 1 } }), [club]);
    expect(index(any, "ANY", "club")).toBe(7);
  });

  it("lets a heavy damage weight decide the weapons, and the evaluator agrees", () => {
    const profile = profileWith({ weights: { DMG: 600, AC: 3, HP: 1 }, dw_factor: 0.8 });
    const good = gear("good", ["PRIMARY", "SECONDARY"], { weapon: oneHand(30, 30) });
    const weak = gear("weak", ["PRIMARY", "SECONDARY"], { stats: { AC: 50, HP: 80 }, weapon: { skill: "1H Blunt", dmg: 5, delay: 40, bonus: null, two_handed: false } });
    for (const setup of ["dw", "1h-shield"]) expect(solved(profile, [good, weak, SHIELD], { setup, haste_assumed: 50 }).groups.PRIMARY, setup).toContain("good");
    const copies = solved(profile, [good, weak], { setup: "dw", haste_assumed: 50 });
    expect(copies.groups).toEqual({ PRIMARY: ["good"], SECONDARY: ["good"] }); // two copies of the same weapon
  });

  // -- haste --------------------------------------------------------------------------------------------------------------------------------

  it("assumes the attainable haste of the pool: the haste on offer plus the best worn haste, up to the cap", () => {
    const boots = gear("boots", ["FEET"], { haste: 35 });
    const assumed = (profile, items, buffset = null, options = {}) => buildMilp(profile, items, "stick", buffset, { any_rule: "explicit", ...options }).info.haste_assumed;
    expect(assumed(profileWith({ buff_totals: { HASTE: 30 }, haste_cap: 75, weights: { DMG: 1 } }), [boots])).toBe(65);
    expect(assumed(profileWith({ buff_totals: { HASTE: 50 }, haste_cap: 75 }), [boots])).toBe(75);
    expect(assumed(profileWith({ haste_cap: 75 }), [boots], buffsetOf({ optional: [buffOf(1, { HASTE: 25 })] }))).toBe(60);
    expect(assumed(profileWith({ buff_totals: { HASTE: 30 } }), [boots], null, { haste_assumed: 12 })).toBe(12);
    // the profile's own spell haste, when it has one, is the haste on offer: no buff is looked at
    expect(assumed(profileWith({ spell_haste: 10 }), [boots], buffsetOf({ optional: [buffOf(1, { HASTE: 25 })] }))).toBe(45);
    // a spell haste below 0 is refused (a Profile refuses it: see the inputs of the builder); the haste of the always-on buffs, when the profile has no
    // spell haste of its own, is a haste of 0 if it is below 0
    expect(() => assumed(profileWith({ spell_haste: -10 }), [boots])).toThrow(/spell_haste must be at least 0/);
    expect(assumed(profileWith({ buff_totals: { HASTE: -10 } }), [boots])).toBe(35);
    // a worn haste that is not above 0 counts for nothing, and an item with no column does not count at all
    expect(assumed(profileWith({ spell_haste: 10 }), [gear("slow", ["FEET"], { haste: -20 }), gear("lost", [], { haste: 90 })], null, { any_rule: "all" })).toBe(10);
  });

  it.each([
    [45, 40, 30, 40],
    [40, 75, 50, 75],
    [40, 75, 20, 60],
    [75, 75, 10, 75],
    [0, 75, 90, 75],
    [0, 75, 0, 0],
  ])("counts a worn haste up to the headroom that the spell haste %i leaves under the cap %i: a worn %i is worth %i", (spell, cap, worn, counted) => {
    const profile = profileWith({ weights: { HASTE: 2 }, buff_totals: { HASTE: spell }, haste_cap: cap });
    const { exact } = solved(profile, worn > 0 ? [gear("h", ["HEAD"], { haste: worn })] : []);
    expect(exact.toString()).toBe(`${2 * counted}/1`);
  });

  it("counts only the best worn haste, and the best spell haste of a choice up to the cap", () => {
    const profile = profileWith({ weights: { HASTE: 1 } });
    const items = [20, 25, 30].map((haste, n) => gear(["a", "b", "c"][n], [["HEAD", "NECK", "BACK"][n]], { haste }));
    expect(solved(profile, items).exact.toString()).toBe("30/1");
    const choice = profileWith({ weights: { HASTE: 1, HP: 1 } });
    const buffset = buffsetOf({ optional: [buffOf(1, { HASTE: 40 }), buffOf(2, { HASTE: 60, HP: -2 })], conflicts: [[1, 2]] });
    const boots = gear("boots", ["FEET"], { haste: 30 });
    const best = solved(choice, [boots], { buffset });
    // buff 1: 40 + 30 worn = 70; buff 2: 60 + 15 of the 30 worn = 75, at a flat -2 HP
    expect(best.buffs).toEqual([2]);
    expect(best.exact.equals(empty(choice).add(75 - 2))).toBe(true);
    // two spell hastes that do not conflict are refused: the model counts the best only
    expect(() => modelOf(choice, [boots], { buffset: buffsetOf({ optional: [buffOf(1, { HASTE: 40 }), buffOf(2, { HASTE: 60 })] }) })).toThrow(/spell haste/);
  });

  it("lets the room for worn haste follow the choice among conflicting haste buffs, and an always-on haste and a better optional one count the best", () => {
    for (const [worn, cap, counted] of [[20, 75, 75], [50, 75, 75], [50, 85, 85], [0, 75, 60], [30, 75, 75], [10, 75, 70], [20, 85, 80]]) {
      const profile = profileWith({ weights: { HASTE: 2 }, haste_cap: cap });
      const buffset = buffsetOf({ optional: [buffOf(1, { HASTE: 40 }), buffOf(2, { HASTE: 60 })], conflicts: [[1, 2]] });
      const { exact, buffs } = solved(profile, worn > 0 ? [gear("boots", ["FEET"], { haste: worn })] : [], { buffset });
      expect(exact.toString(), `worn ${worn}, cap ${cap}`).toBe(`${2 * counted}/1`);
      if (worn !== 50) expect(buffs).toEqual([2]); // at 50 both choices reach the cap
    }
    const over = buffsetOf({ optional: [buffOf(1, { HASTE: 80, HP: -5 }), buffOf(2, { HASTE: 30 })], conflicts: [[1, 2]] });
    const profile = profileWith({ weights: { HASTE: 1, HP: 1 } });
    const late = solved(profile, [gear("boots", ["FEET"], { haste: 60 })], { buffset: over });
    // buff 1: 75 and no worn haste, -5 HP; buff 2: 30 + 45 of the 60 worn = 75 at no cost
    expect(late.buffs).toEqual([2]);
    expect(late.exact.equals(empty(profile).add(75))).toBe(true);
    const mixed = buffsetOf({ always: [buffOf(9, { HASTE: 30 })], optional: [buffOf(1, { HASTE: 50 })] });
    const totals = profileWith({ weights: { HASTE: 1 }, buff_totals: { HASTE: 30 } });
    const best = solved(totals, [], { buffset: mixed });
    expect(best.buffs).toEqual([1]);
    expect(best.exact.toString()).toBe("50/1");
  });

  it("keeps a haste buff that is past the cap in the choice when it is the best, and leaves no room for worn haste under it", () => {
    const profile = profileWith({ weights: { HASTE: 1, HP: 1 }, haste_cap: 75 });
    const buffset = buffsetOf({ optional: [buffOf(1, { HASTE: 80, HP: 100 }), buffOf(2, { HASTE: 30 })], conflicts: [[1, 2]] });
    const result = solved(profile, [gear("boots", ["FEET"], { haste: 60 })], { buffset });
    // buff 1: 75, the cap, and no room for the worn 60, with 100 HP; buff 2: 30 + 45 of the worn 60 = 75
    expect(result.buffs).toEqual([1]);
    expect(result.exact.equals(empty(profile).add(75 + 100))).toBe(true);
    expect(result.model.col_names).toEqual(["n[FEET|boots]", "buff[1]", "buff[2]", "haste.y60", "haste.q"]);
    expect(result.model.row_names).toEqual(["buff.clique[1,2]", "haste.y60.worn", "haste.best", "haste.room"]);
    // an always-on haste past the cap leaves no room at all: no binary, no column for the worn haste
    const full = modelOf(profileWith({ weights: { HASTE: 1 }, buff_totals: { HASTE: 80 }, haste_cap: 75 }), [gear("boots", ["FEET"], { haste: 60 })]);
    expect(full.col_names).toEqual(["n[FEET|boots]"]);
    expect(full.row_names).toEqual([]);
    expect(full.const).toBe(75);
  });

  it("names the binary of a haste that is not whole by its fraction, as Python writes the text of a fraction", () => {
    const buffset = buffsetOf({ always: [buffOf(900, { HASTE: 12.5, HP: 2.5 })], optional: [buffOf(1, { HASTE: 20.5, STA: 1.5 }), buffOf(2, { HP: 0.25 })], conflicts: [[1, 2]] });
    const profile = profileWith({ weights: { HASTE: 1.5, HP: 0.3, DMG: 2 }, buff_totals: { HASTE: 12.5, HP: 2.5 } });
    const items = [gear("fast", ["HEAD"], { haste: 70, stats: { HP: 3 } }), gear("fast", ["NECK"], { haste: 33, tier: 1 })];
    const model = modelOf(profile, items, { setup: "dw", buffset, haste_assumed: null });
    // the room under the cap is 75 - 12.5: the worn 70 counts 62.5, which is 125/2
    expect(model.col_names).toEqual(["n[HEAD|fast]", "n[NECK|fast]", "buff[1]", "buff[2]", "curve.HP.sta.seg0", "haste.y33", "haste.y125/2", "haste.q"]);
    expect(model.row_names).toEqual(["buff.clique[1,2]", "curve.HP.sta.total", "haste.y33.worn", "haste.y125/2.worn", "haste.one", "haste.best", "haste.room"]);
    expect(model.info.haste_assumed).toBe(75); // the best haste on offer, 20.5, and the best worn, 70, up to the cap
  });

  // -- buffs --------------------------------------------------------------------------------------------------------------------------------

  it("leaves the better of two conflicting buffs, and lets the gear move the choice", () => {
    // A: STA 30. B: HP 200. They conflict. A STA point is worth 9.4 HP below 255, so A = 282 HP and B = 200 HP
    const buffset = buffsetOf({ optional: [buffOf(1, { STA: 30 }), buffOf(2, { HP: 200 })], conflicts: [[1, 2]] });
    const profile = profileWith({ weights: { HP: 1 } });
    expect(solved(profile, [], { buffset }).buffs).toEqual([1]);
    // the gear takes STA to 245: the 30 points then cross the 255 knee and are worth 10 x 9.4 + 20 x 4.7 = 188, which is under 200
    const moved = solved(profile, [gear("sta", ["HEAD"], { stats: { STA: 145 } })], { buffset });
    expect(moved.groups.HEAD).toEqual(["sta"]);
    expect(moved.buffs).toEqual([2]);
  });

  it("gives a conflict no clique covers its own pair row, and takes a limit of 0 for no buff", () => {
    const profile = profileWith({ weights: { HP: 1 } });
    const pair = buffsetOf({ optional: [buffOf(1, { HP: 100 }), buffOf(2, { HP: 90 })], conflicts: [[1, 2]], cliques: [] });
    const withPair = solved(profile, [], { buffset: pair });
    expect(withPair.buffs).toEqual([1]);
    expect(rowOf(withPair.model, "buff.conflict[1,2]")).toEqual({ "buff[1]": 1, "buff[2]": 1 });
    expect(rowsNamed(withPair.model, "buff.clique")).toEqual([]);
    const zero = solved(profile, [], { buffset: buffsetOf({ optional: [buffOf(1, { HP: 100 }), buffOf(2, { HP: 90 })], cardinality: 0 }) });
    expect(zero.buffs).toEqual([]);
    expect(zero.exact.equals(empty(profile))).toBe(true);
    // a clique covers its pairs: no pair row is made for them
    const triple = buffsetOf({ optional: [1, 2, 3].map((id) => buffOf(id, { HP: 10 * id })), conflicts: [[1, 2], [1, 3], [2, 3]], cliques: [[1, 2, 3]] });
    const covered = solved(profile, [], { buffset: triple });
    expect(covered.buffs).toEqual([3]);
    expect(rowsNamed(covered.model, "buff.")).toEqual(["buff.clique[1,2,3]"]);
  });

  it("limits the active buffs to the cardinality", () => {
    const profile = profileWith({ weights: { HP: 1 } });
    for (const limit of [null, 1, 2, 3]) {
      const buffset = buffsetOf({ optional: [1, 2, 3, 4].map((id) => buffOf(id, { HP: 10 * id })), cardinality: limit });
      const { buffs, model } = solved(profile, [], { buffset });
      expect(buffs, String(limit)).toEqual([1, 2, 3, 4].slice(4 - (limit ?? 4)));
      if (limit !== null) expect(Object.values(rowOf(model, "buff.limit"))).toEqual([1, 1, 1, 1]);
    }
  });

  it("counts a buff's resists only up to the cap, and lets every component of a buff feed the totals it belongs to", () => {
    const capped = solved(
      profileWith({ weights: { SV: 1 } }),
      [gear("res", ["HEAD"], { sv: { FIRE: 170, COLD: 100 } })],
      { buffset: buffsetOf({ optional: [buffOf(1, { FIRE: 40, COLD: 40 }), buffOf(2, { FIRE: 100 })], conflicts: [[1, 2]] }) },
    );
    // fire is over the cap with either buff (210 and 270 against 200): cold decides it
    expect(capped.buffs).toEqual([1]);
    expect(capped.exact.toString()).toBe("340/1");
    const everything = buffOf(1, { STR: 20, STA: 30, AGI: 10, DEX: 12, WIS: 15, INT: 5, CHA: 7, AC: 25, HP: 100, MANA: 50, END: 40, ATK: 11, HPREG: 3, MANAREG: 2, ENDREG: 1, FIRE: 30, COLD: 20, MAGIC: 10, POISON: 5, DISEASE: 15, HASTE: 20 });
    const weights = Object.fromEntries(["HP", "MANA", "END", "AC", "ATK", "DEX", "HASTE", "CHA", "HPREG", "MANAREG", "ENDREG", "SV"].map((key) => [key, key.length / 7]));
    const profile = profileWith({ weights, softcap: [300, 0.4], defense_cap: 100, haste_cap: 75 });
    const fed = solved(profile, [], { buffset: buffsetOf({ optional: [everything] }) });
    expect(fed.buffs).toEqual([1]);
  });

  it("takes a stat that no gear can bring under its cap, and a resist that the buffs hold over it, for the cap itself", () => {
    const profile = profileWith({
      weights: { END: 1, AC: 2, ATK: 1, SV: 1, DEX: 1, CHA: 1 },
      naked: Object.fromEntries(Object.keys(NAKED).map((stat) => [stat, 520])),
      buff_totals: { SV: { FIRE: 250 } },
    });
    const { model } = solved(profile, [gear("ring", ["FINGER"], { stats: { STR: 5 }, sv: { FIRE: 4, COLD: 300 } })]);
    // every stat starts over 510 (no column for a cap), fire is held over 200 by the buffs (a constant), and only the cold of the ring can go either side of its cap
    expect(model.col_names).toEqual(["n[FINGER|ring]", "sheet.a", "sv.COLD"]);
    expect(model.row_names).toEqual(["sheet.below", "sheet.past", "sv.COLD.max"]);
  });

  it("makes a column for the cap of a stat that the gear can take over it, and none for a stat that it cannot", () => {
    const profile = profileWith({ weights: { END: 1, AC: 2 }, naked: Object.fromEntries(Object.keys(NAKED).map((stat) => [stat, 480])) });
    const { model } = solved(profile, [gear("ring", ["FINGER"], { stats: { STR: 30, AGI: 20 } })]);
    expect(model.col_names).toEqual(["n[FINGER|ring]", "cap.STR", "cap.AGI", "curve.END.avg.seg0", "sheet.a", "curve.AC.agi.seg0"]);
    expect(model.row_names).toEqual(["cap.STR.max", "cap.AGI.max", "curve.END.avg.total", "sheet.below", "sheet.past", "curve.AC.agi.total"]);
    expect(rowOf(model, "cap.STR.max")).toEqual({ "cap.STR": 1, "n[FINGER|ring]": -30 });
    const cap = model.col_names.indexOf("cap.STR");
    expect([model.col_lb[cap], model.col_ub[cap], model.integrality[cap]]).toEqual([480, 510, 0]); // from what the gear leaves, to the cap
  });

  it("refuses a buff set whose always-on buffs are not the profile's buff totals", () => {
    const buffset = buffsetOf({ always: [buffOf(9, { STR: 30 })] });
    expect(() => modelOf(profileWith({ weights: { ATK: 1 } }), [], { buffset })).toThrow(/buff_totals disagrees with the always-on buffs of the buffset at STR/);
    expect(() => modelOf(profileWith({ weights: { ATK: 1 }, buff_totals: { STR: 31 } }), [], { buffset })).toThrow(/at STR/);
    expect(modelOf(profileWith({ weights: { ATK: 1 }, buff_totals: { STR: 30 } }), [], { buffset }).const).toBeGreaterThan(0);
    const resist = buffsetOf({ always: [buffOf(9, { FIRE: 5 })] });
    expect(() => modelOf(profileWith({ weights: { SV: 1 } }), [], { buffset: resist })).toThrow(/at FIRE/);
    expect(() => modelOf(profileWith({ weights: { SV: 1 }, buff_totals: { SV: { FIRE: 5 } } }), [], { buffset: resist })).not.toThrow();
  });

  it("tells two rows that would have one name apart, the same way every time", () => {
    const buffset = buffsetOf({ optional: [buffOf(1, { HP: 5 }), buffOf(2, { HP: 6 })], conflicts: [[1, 2]], cliques: [[1, 2], [1, 2], [1, 2]] });
    const model = modelOf(profileWith({ weights: { HP: 1 } }), [], { buffset });
    expect(rowsNamed(model, "buff.clique")).toEqual(["buff.clique[1,2]", "buff.clique[1,2]#2", "buff.clique[1,2]#3"]);
    expect(new Set(model.row_names).size).toBe(model.row_names.length);
    expect(JSON.stringify(modelOf(profileWith({ weights: { HP: 1 } }), [], { buffset }))).toBe(JSON.stringify(model));
  });

  it("calls a pair row by the pair in order, whichever way round the conflict is listed, and sees a clique cover a pair listed the wrong way", () => {
    const setWith = (conflicts, cliques) => {
      const set = clone(buffsetOf({ optional: [buffOf(1, { HP: 5 }), buffOf(2, { HP: 6 }), buffOf(3, { HP: 7 })] }));
      set.set.conflicts = conflicts.map(([a, b]) => [a, b, ["test"]]);
      set.set.cliques = cliques;
      return set;
    };
    const profile = profileWith({ weights: { HP: 1 } });
    const reversed = modelOf(profile, [], { buffset: setWith([[2, 1], [3, 2]], []) });
    expect(reversed.row_names).toEqual(["buff.conflict[1,2]", "buff.conflict[2,3]"]);
    expect(rowOf(reversed, "buff.conflict[2,3]")).toEqual({ "buff[2]": 1, "buff[3]": 1 });
    expect(JSON.stringify(modelOf(profile, [], { buffset: setWith([[1, 2], [2, 3]], []) }))).toBe(JSON.stringify(reversed));
    const covered = modelOf(profile, [], { buffset: setWith([[2, 1], [3, 1], [3, 2]], [[3, 2, 1]]) });
    expect(covered.row_names).toEqual(["buff.clique[3,2,1]"]); // the clique covers the three pairs, however they are listed
  });

  // -- the best two pools -------------------------------------------------------------------------------------------------------------------

  it("sums the fixed pair of pools that cross inside the pair without binaries, and selects where the best pair flips", () => {
    const hp = (pools) => profileWith({ weights: { HP: 1 }, naked: { ...NAKED, STA: 0 }, pools: { ...POOLS, MANA: [], HP: pools } });
    const pair = hp([{ cls: "WAR", base: 25, fac: 3 }, { cls: "SHD", base: 85, fac: 2 }, { cls: "CLR", base: 5, fac: 1 }]);
    const flip = hp([{ cls: "WAR", base: 25, fac: 3 }, { cls: "SHD", base: 85, fac: 2 }, { cls: "CLR", base: 55, fac: 2.5 }]);
    for (const [sta, want] of [[40, "320/1"], [59, "415/1"], [60, "420/1"], [61, "425/1"], [150, "870/1"]]) {
      const result = solved(pair, [gear("sta", ["HEAD"], { stats: { STA: sta } })], { force: [["HEAD", "sta"]] });
      expect(result.exact.toString(), `sta ${sta}`).toBe(want);
      expect(result.model.info.pools.HP).toBe("fixed");
    }
    for (const [sta, want] of [[40, "330/1"], [59, "831/2"], [60, "420/1"], [61, "851/2"], [150, "915/1"]]) {
      const result = solved(flip, [gear("sta", ["HEAD"], { stats: { STA: sta } })], { force: [["HEAD", "sta"]] });
      expect(result.exact.toString(), `sta ${sta}`).toBe(want);
      // the meeting point at 60 lies inside the reachable range only when the item takes STA above it
      expect(result.model.info.pools.HP).toBe(sta > 60 ? "select" : "fixed");
    }
    const selected = modelOf(flip, [gear("sta", ["HEAD"], { stats: { STA: 150 } })]);
    expect(rowsNamed(selected, "pool.HP.")).toEqual([
      "pool.HP.kept.WAR.le_pool", "pool.HP.kept.WAR.le_chosen", "pool.HP.kept.SHD.le_pool", "pool.HP.kept.SHD.le_chosen", "pool.HP.kept.CLR.le_pool", "pool.HP.kept.CLR.le_chosen", "pool.HP.picks",
    ]);
    expect(selected.info.binaries.selection).toBe(3);
  });

  it("counts a pool that is below zero as nothing while it is not selected", () => {
    const pools = { ...POOLS, MANA: [], HP: [{ cls: "WAR", base: 25, fac: 3 }, { cls: "SHD", base: 85, fac: 2 }, { cls: "CLR", base: -500, fac: 10 }] };
    const profile = profileWith({ weights: { HP: 1 }, naked: { ...NAKED, STA: 0 }, pools });
    // the big piece takes STA to 150, where the third pool is the best; it costs far more than it gives, so the kit is the small piece, STA 10,
    // where that pool is -395 and the first two count
    const items = [gear("big", ["NECK"], { stats: { STA: 150, HP: -5000 } }), gear("small", ["HEAD"], { stats: { STA: 10, HP: 1 } })];
    const { model, groups, exact } = solved(profile, items);
    expect(model.info.pools.HP).toBe("select");
    expect(groups).toEqual({ HEAD: ["small"] });
    expect(exact.toString()).toBe("171/1"); // 5 + 25 + 3 x 10 and 5 + 85 + 2 x 10, and 1 of the item; not the -395
  });

  it("uses the fixed pair without binaries for a family whose order cannot change", () => {
    const model = modelOf(profileWith({ weights: { HP: 1, END: 1, MANA: 1 } }), [gear("sta", ["HEAD"], { stats: { STA: 50, WIS: 20 } })]);
    expect(model.info.pools).toEqual({ END: "fixed", HP: "fixed", MANA: "all" });
    expect(model.info.binaries.selection).toBe(0);
    expect(modelOf(profileWith({ weights: { MANA: 1 }, pools: { ...POOLS, MANA: [] } }), []).info.pools.MANA).toBe("none");
    expect(modelOf(profileWith({ weights: {} }), []).info.pools).toEqual({ END: "off", HP: "off", MANA: "off" });
  });

  it("bounds a selected pool by its absolute value, not by a change: forcing the true best pair loses nothing", () => {
    const pools = { ...POOLS, MANA: [{ cls: "CLR", base: 900, fac: 4.5, stat: "WIS" }, { cls: "WIZ", base: 1500, fac: 4.5, stat: "INT" }, { cls: "ENC", base: 900, fac: 4.5, stat: "INT" }] };
    const profile = profileWith({ weights: { MANA: 1 }, pools });
    const item = gear("int", ["HEAD"], { stats: { INT: 110, WIS: 20 } });
    const model = modelOf(profile, [item]);
    expect(model.info.pools.MANA).toBe("select");
    const document = clone(model);
    document.col_lb[document.col_names.indexOf("n[HEAD|int]")] = 1;
    // INT 210: WIZ and ENC are the best two; force exactly that pair
    for (const [at, name] of document.col_names.entries()) {
      if (name.startsWith("pool.MANA.z.")) document.col_lb[at] = document.col_ub[at] = name.endsWith("WIZ") || name.endsWith("ENC") ? 1 : 0;
    }
    const forced = solveModelWith(highs, document, { budgetMs: 60_000, startedAt: performance.now(), onProgress() {} });
    const free = solveModelWith(highs, clone(model), { budgetMs: 60_000, startedAt: performance.now(), onProgress() {} });
    expect(forced.status).toBe("optimal");
    expect(relative(forced.objective, free.objective)).toBeLessThanOrEqual(1e-9);
  });
});

// ---- owned items --------------------------------------------------------------------------------------------------------------------------

describe("the owned-item options", () => {
  const profile = profileWith({ weights: { HP: 1 } }); // every point of item HP is worth exactly one
  const ring = (key, hp, more = {}) => gear(key, more.slots ?? ["FINGER"], { stats: { HP: hp }, ...more });
  const solve = (items, options = {}, p = profile) => solved(p, items, options);
  const idents = (result) => result.idents;

  it("names every row, uniquely and the same on every build, whatever the order of the pool", () => {
    const items = [ring("ring-a", 5), ring("ring-b", 4), ring("ring-c", 3), ring("ear-lore", 9, { slots: ["EAR"], lore: true }), ring("ear-one", 2, { slots: ["EAR"] }), ring("ear-two", 1, { slots: ["EAR"] })];
    const model = modelOf(profile, items);
    expect(model.row_names).toContain("group.FINGER");
    expect(model.row_names).toContain("group.EAR");
    expect(model.row_names).not.toContain("lore.ear-lore"); // one column of a Lore item needs no row of its own
    expect(rowOf(model, "group.FINGER")).toEqual({ "n[FINGER|ring-a]": 1, "n[FINGER|ring-b]": 1, "n[FINGER|ring-c]": 1 });
    const twice = modelOf(profile, [...items, ring("ear-lore", 9, { slots: ["EAR"], lore: true, tier: 2 })]);
    expect(rowOf(twice, "lore.ear-lore")).toEqual({ "n[EAR|ear-lore]": 1, "n[EAR|ear-lore@2]": 1 }); // one key, two tiers
    expect(JSON.stringify(modelOf(profile, [...items].reverse()))).toBe(JSON.stringify(model));
  });

  it("adds no row and no column to a model when the owned-item options are their defaults, spelt out or not", () => {
    const items = [ring("ring-a", 5), ring("ring-b", 4, { slots: ["EAR"] })];
    const plain = modelOf(profile, items);
    for (const options of [{ owned_caps: null, new_keys: [], max_new: null, upgrades: null }, { owned_caps: {}, new_keys: new Set(), upgrades: {} }, {}]) {
      expect(JSON.stringify(modelOf(profile, items, options))).toBe(JSON.stringify(plain));
    }
  });

  it("wears an owned item no more often than it is owned", () => {
    const big = ring("big", 10);
    const small = ring("small", 3);
    const free = solve([big, small]);
    expect(idents(free)).toEqual({ "big@0": 2 }); // nothing stops two copies of the big ring
    const capped = solve([big, small], { owned_caps: { "big@0": 1, "small@0": 5 } });
    expect(idents(capped)).toEqual({ "big@0": 1, "small@0": 1 });
    expect(capped.exact.equals(free.exact.sub(7))).toBe(true);
  });

  it("covers every group an item fits with one cap row, the Any group included, and makes no row for a cap that cannot bind", () => {
    const both = ring("ring", 10, { slots: ["FINGER", "ANY"] }); // two finger places and two Any places
    const filler = ring("filler", 1);
    expect(solve([both, filler]).idents).toEqual({ "ring@0": 4 });
    const one = modelOf(profile, [both, filler], { owned_caps: { "ring@0": 1 } });
    expect(rowOf(one, "own.ring@0")).toEqual({ "n[FINGER|ring]": 1, "n[ANY|ring]": 1 });
    expect(solve([both, filler], { owned_caps: { "ring@0": 1 } }).idents).toEqual({ "ring@0": 1, "filler@0": 2 });
    expect(solve([both, filler], { owned_caps: { "ring@0": 2 } }).idents).toEqual({ "ring@0": 2, "filler@0": 2 });
    expect(solve([both, filler], { owned_caps: { "ring@0": 3 } }).idents).toEqual({ "ring@0": 3, "filler@0": 1 });
    expect(rowsNamed(modelOf(profile, [both, filler], { owned_caps: { "ring@0": 4 } }), "own.")).toEqual([]); // four places: the cap cannot bind
  });

  it("wears a Lore item once whatever its count, and a cap that cannot bind makes no row", () => {
    const lore = ring("band", 10, { slots: ["EAR"], lore: true });
    const other = ring("stud", 2, { slots: ["EAR"] });
    const model = modelOf(profile, [lore, other], { owned_caps: { "band@0": 2, "stud@0": 9 } });
    expect(solve([lore, other], { owned_caps: { "band@0": 2, "stud@0": 9 } }).idents).toEqual({ "band@0": 1, "stud@0": 1 });
    expect(rowsNamed(model, "own.")).toEqual([]); // the Lore bound is 1 per column, a count of 2 never binds; 9 never does either
    const spanning = solve([lore, ring("band", 10, { slots: ["EAR"], lore: true, tier: 3 })], { owned_caps: { "band@0": 5, "band@3": 5 } });
    expect(Object.values(spanning.idents).reduce((a, b) => a + b, 0)).toBe(1); // the Lore row spans the tiers of the key
    const none = modelOf(profile, [lore, other], { owned_caps: { "band@0": 0 } });
    expect(rowsNamed(none, "own.")).toEqual(["own.band@0"]);
    expect(solve([lore, other], { owned_caps: { "band@0": 0 } }).idents).toEqual({ "stud@0": 2 });
  });

  it("keeps an item with a count of 0 out of the kit, and makes no row for a count at the places", () => {
    const one = ring("ring", 10);
    const other = ring("other", 1);
    expect(solve([one, other], { owned_caps: { "ring@0": 0 } }).idents).toEqual({ "other@0": 2 });
    for (const [count, hasRow] of [[0, true], [1, true], [2, false], [3, false]]) {
      expect(rowsNamed(modelOf(profile, [one], { owned_caps: { "ring@0": count } }), "own.").length > 0, String(count)).toBe(hasRow);
    }
  });

  it("reads the caps in sorted order, whatever the order of the mapping", () => {
    const items = [...Array.from({ length: 5 }, (_, n) => ring(`r${n}`, 10 - n)), ring("e", 7, { slots: ["EAR"] }), ring("f", 6, { slots: ["EAR"] }), ring("g", 5, { slots: ["EAR"] })];
    const caps = { r0: 1, r1: 1, r2: 1, r3: 1, r4: 1, e: 1, f: 1 };
    const named = Object.fromEntries(Object.entries(caps).map(([key, count]) => [`${key}@0`, count]));
    const reversed = Object.fromEntries(Object.entries(named).reverse());
    const one = modelOf(profile, items, { owned_caps: named });
    expect(JSON.stringify(modelOf(profile, items, { owned_caps: reversed }))).toBe(JSON.stringify(one));
    const own = rowsNamed(one, "own.");
    expect(own).toHaveLength(7);
    expect(own).toEqual([...own].sort());
  });

  it("never wears an owned item the profile cannot use, and makes it no column and no row", () => {
    const locked = gear("locked-ear", ["EAR"], { stats: { HP: 90 }, deity: ["Tunare"] });
    const onlyIksar = gear("scale-back", ["BACK"], { stats: { HP: 90 }, races: ["IKS"] });
    const plain = ring("plain", 4, { slots: ["EAR"] });
    const caps = { "locked-ear@0": 1, "scale-back@0": 1, "plain@0": 1 };
    const ogre = profileWith({ weights: { HP: 1 }, race: "OGR", deity: null });
    const model = modelOf(ogre, [locked, onlyIksar, plain], { owned_caps: caps });
    expect(solve([locked, onlyIksar, plain], { owned_caps: caps }, ogre).idents).toEqual({ "plain@0": 1 });
    expect(model.col_names.some((name) => name.includes("locked-ear") || name.includes("scale-back"))).toBe(false);
    expect(rowsNamed(model, "own.locked")).toEqual([]);
    expect(rowsNamed(model, "own.scale")).toEqual([]);
    const follower = profileWith({ weights: { HP: 1 }, race: "OGR", deity: "Tunare" });
    expect(solve([locked, onlyIksar, plain], { owned_caps: caps }, follower).idents).toEqual({ "locked-ear@0": 1, "plain@0": 1 });
  });

  it("gives the same key at two tiers a cap for each tier", () => {
    const low = ring("band", 4, { tier: 2 });
    const high = ring("band", 9, { tier: 4 });
    expect(solve([low, high], { owned_caps: { "band@2": 1, "band@4": 1 } }).idents).toEqual({ "band@2": 1, "band@4": 1 });
    expect(solve([low, high], { owned_caps: { "band@2": 5, "band@4": 1 } }).idents).toEqual({ "band@2": 1, "band@4": 1 }); // not two high copies
    expect(solve([low, high], { owned_caps: { "band@2": 1, "band@4": 5 } }).idents).toEqual({ "band@4": 2 });
  });

  it.each([
    [{ "nobody@0": 1 }, /not an item of the pool/],
    [{ ring: 1 }, /not an item ident/],
    [{ "ring@x": 1 }, /not an item ident/],
    [{ "ring@-1": 1 }, /not an item ident/],
    [{ "ring@11": 1 }, /not an item ident/],
    [{ "ring@01": 1 }, /not an item ident/],
    [{ "@0": 1 }, /not an item ident/],
    [{ "ring@0@0": 1 }, /not an item ident/],
    [{ "ring@0": -1 }, /whole number of at least 0/],
    [{ "ring@0": 1.5 }, /whole number of at least 0/],
    [{ "ring@0": true }, /whole number of at least 0/],
    [{ "ring@0": "2" }, /whole number of at least 0/],
    [[["ring@0", 1]], /must be an object/],
  ])("refuses the owned caps %j", (caps, message) => {
    expect(() => modelOf(profile, [ring("ring", 5)], { owned_caps: caps })).toThrow(message);
  });

  it("refuses a bad limit and a bad list of new items", () => {
    for (const bad of [-1, 1.5, true, "1", NaN, Infinity]) expect(() => modelOf(profile, [ring("ring", 5)], { max_new: bad }), String(bad)).toThrow(/max_new/);
    expect(() => modelOf(profile, [ring("ring", 5)], { new_keys: ["ghost@0"], max_new: 1 })).toThrow(/ghost@0 is not an item of the pool/);
    expect(() => modelOf(profile, [ring("ring", 5)], { new_keys: ["ring"] })).toThrow(/not an item ident/);
    expect(() => modelOf(profile, [ring("ring", 5)], { new_keys: "ring@0" })).toThrow(/new_keys is a list/);
    expect(() => modelOf(profile, [ring("ring", 5)], { new_keys: [3] })).toThrow(/not an item ident/);
  });

  // -- the limit on new items --------------------------------------------------------------------------------------------------------------

  it("admits exactly the limit of new copies over every group", () => {
    const both = ring("ring", 10, { slots: ["FINGER", "ANY"] });
    const filler = ring("filler", 1);
    const news = ["ring@0"];
    const model = modelOf(profile, [both, filler], { new_keys: news, max_new: 1 });
    expect(rowOf(model, "new.limit")).toEqual({ "n[FINGER|ring]": 1, "n[ANY|ring]": 1 });
    expect(solve([both, filler], { new_keys: news, max_new: 1 }).idents).toEqual({ "ring@0": 1, "filler@0": 2 }); // one new ring, in an Any place, two fillers
    expect(solve([both, filler], { new_keys: news, max_new: 2 }).idents).toEqual({ "ring@0": 2, "filler@0": 2 });
    expect(solve([both, filler], { new_keys: news, max_new: 0 }).idents).toEqual({ "filler@0": 2 });
    expect(rowsNamed(modelOf(profile, [both, filler], { new_keys: news, max_new: 4 }), "new.")).toEqual([]); // four places: the limit cannot bind
    expect(rowsNamed(modelOf(profile, [both, filler], { new_keys: news }), "new.")).toEqual([]); // no limit given
  });

  it("counts the copies over all the new items, not over the keys", () => {
    const a = ring("a", 10);
    const b = ring("b", 9);
    const c = ring("c", 8, { slots: ["EAR"] });
    expect(solve([a, b, c], { new_keys: ["a@0", "b@0", "c@0"], max_new: 1 }).idents).toEqual({ "a@0": 1 });
    expect(solve([a, b, c], { new_keys: ["a@0", "b@0", "c@0"], max_new: 2 }).idents).toEqual({ "a@0": 2 });
    // b is free and fills the finger places; of the two new items c stands in another group, so it is the one acquired
    expect(solve([a, b, c], { new_keys: ["a@0", "c@0"], max_new: 1 }).idents).toEqual({ "c@0": 1, "b@0": 2 });
    expect(solve([a, b, c], { new_keys: ["a@0", "b@0"], max_new: 1 }).idents).toEqual({ "a@0": 1, "c@0": 2 }); // c is free
  });

  it("does not count the wear of an owned item against the limit", () => {
    const owned = ring("own", 5);
    const fresh = ring("fresh", 4);
    expect(solve([owned, fresh], { owned_caps: { "own@0": 1 }, new_keys: ["fresh@0"], max_new: 1 }).idents).toEqual({ "own@0": 1, "fresh@0": 1 });
    expect(solve([owned, fresh], { owned_caps: { "own@0": 1 }, new_keys: ["fresh@0"], max_new: 0 }).idents).toEqual({ "own@0": 1 });
  });

  it("lets a candidate that is also owned be worn above its count, for one new copy each, through a column of copies above the count", () => {
    const one = ring("ring", 10);
    const other = ring("other", 2);
    const options = { owned_caps: { "ring@0": 1 }, new_keys: ["ring@0"], max_new: 1 };
    expect(solve([one, other], options).idents).toEqual({ "ring@0": 2 }); // one owned and one acquired
    expect(solve([one, other], { ...options, max_new: 0 }).idents).toEqual({ "ring@0": 1, "other@0": 1 });
    const model = modelOf(profile, [one, other], options);
    expect(model.col_names).toContain("new[ring@0]");
    expect(rowOf(model, "own.ring@0")).toEqual({ "n[FINGER|ring]": 1, "new[ring@0]": -1 });
    // the column of copies above the count is continuous, from 0 to the room (the places less the count, or the limit if that is less)
    const at = model.col_names.indexOf("new[ring@0]");
    expect([model.integrality[at], model.col_lb[at], model.col_ub[at]]).toEqual([0, 0, 1]);
    expect(modelOf(profile, [one, other], { ...options, max_new: null }).col_ub[at]).toBe(1);
    const wide = modelOf(profile, [one, other], { owned_caps: { "ring@0": 1 }, new_keys: ["ring@0"] });
    expect(wide.col_ub[wide.col_names.indexOf("new[ring@0]")]).toBe(1); // two places less the count of 1
  });

  it("takes a candidate listed as owned with none for a plain new item", () => {
    const one = ring("ring", 10);
    const other = ring("other", 2);
    const options = { owned_caps: { "ring@0": 0 }, new_keys: ["ring@0"], max_new: 1 };
    const model = modelOf(profile, [one, other], options);
    expect(solve([one, other], options).idents).toEqual({ "ring@0": 1, "other@0": 1 });
    expect(model.col_names).not.toContain("new[ring@0]");
    expect(rowsNamed(model, "own.")).toEqual([]);
  });

  it("adds no column and no use of the limit for a Lore item that is owned and a candidate", () => {
    const lore = ring("band", 10, { slots: ["EAR"], lore: true });
    const other = ring("stud", 2, { slots: ["EAR"] });
    const options = { owned_caps: { "band@0": 1 }, new_keys: ["band@0"], max_new: 1 };
    const model = modelOf(profile, [lore, other], options);
    expect(solve([lore, other], options).idents).toEqual({ "band@0": 1, "stud@0": 1 });
    expect(model.col_names).not.toContain("new[band@0]");
    expect(rowsNamed(model, "new.")).toEqual([]);
  });

  it("takes the count of an item for a Lore count when the item it is upgraded to is Lore, even when the item itself has no column", () => {
    const target = ring("band", 9, { slots: ["EAR", "FINGER"], lore: true, tier: 4 });
    const source = ring("band", 4, { slots: [], lore: true, tier: 2 });
    const model = modelOf(profile, [target, source], { owned_caps: { "band@2": 1 }, upgrades: { "band@4": "band@2" }, max_new: 1 });
    expect(model.row_names).toEqual(["lore.band", "new.limit"]); // a Lore item is worn once whatever the count: no row for the cap
    expect(rowOf(model, "new.limit")).toEqual({ "n[EAR|band]": 1, "n[FINGER|band]": 1 }); // (the only columns of the key: the tier is not in their names)
  });

  it("takes the new items as a list or as a set, and a set of nothing as none", () => {
    const items = [ring("a", 5), ring("b", 4, { slots: ["EAR"] })];
    const options = { owned_caps: { "a@0": 1 }, max_new: 1 };
    const listed = modelOf(profile, items, { ...options, new_keys: ["b@0"] });
    expect(JSON.stringify(modelOf(profile, items, { ...options, new_keys: new Set(["b@0"]) }))).toBe(JSON.stringify(listed));
    expect(JSON.stringify(modelOf(profile, items, { ...options, new_keys: new Set() }))).toBe(JSON.stringify(modelOf(profile, items, options)));
  });

  // -- upgrades -----------------------------------------------------------------------------------------------------------------------------

  it("makes an upgrade from an owned copy, so that it never adds a copy", () => {
    const low = ring("band", 4, { tier: 2 });
    const high = ring("band", 9, { tier: 4 });
    const upgrades = { "band@4": "band@2" };
    const model = modelOf(profile, [low, high], { owned_caps: { "band@2": 2 }, upgrades, max_new: 1 });
    expect(rowOf(model, "own.band@2")).toEqual({ "n[FINGER|band]": 1, "n[FINGER|band@4]": 1 });
    expect(solve([low, high], { owned_caps: { "band@2": 2 }, upgrades, max_new: 1 }).idents).toEqual({ "band@2": 1, "band@4": 1 }); // two copies, one of them upgraded
    expect(solve([low, high], { owned_caps: { "band@2": 1 }, upgrades, max_new: 1 }).idents).toEqual({ "band@4": 1 });
    expect(solve([low, high], { owned_caps: { "band@2": 2 }, upgrades, max_new: 2 }).idents).toEqual({ "band@4": 2 });
    expect(solve([low, high], { owned_caps: { "band@2": 2 }, upgrades, max_new: 0 }).idents).toEqual({ "band@2": 2 });
  });

  it("counts an upgrade as new, and the owned tier as not", () => {
    const low = ring("band", 4);
    const high = ring("band", 9, { tier: 4 });
    expect(solve([low, high], { owned_caps: { "band@0": 1 }, new_keys: ["band@4"], max_new: 1 }).idents).toEqual({ "band@0": 1, "band@4": 1 }); // the owned copy is free; the other tier is new
    expect(solve([low, high], { owned_caps: { "band@0": 1 }, upgrades: { "band@4": "band@0" }, max_new: 1 }).idents).toEqual({ "band@4": 1 });
    expect(solve([low, high], { owned_caps: { "band@0": 1 }, upgrades: { "band@4": "band@0" }, max_new: 0 }).idents).toEqual({ "band@0": 1 }); // an upgrade is not free
  });

  it("costs one more acquisition for the upgrade of a candidate", () => {
    const low = ring("band", 4, { tier: 1 });
    const high = ring("band", 9, { tier: 3 });
    const options = { owned_caps: { "band@1": 1 }, new_keys: ["band@1"], upgrades: { "band@3": "band@1" } };
    expect(solve([low, high], { ...options, max_new: 1 }).idents).toEqual({ "band@3": 1 });
    // two acquisitions: a copy of the source upgraded would leave the source and the target, but one upgrade and a copy of the upgrade is two target wears
    // for the same two acquisitions
    expect(solve([low, high], { ...options, max_new: 2 }).idents).toEqual({ "band@3": 2 });
    expect(solve([low, high], { ...options, max_new: 3 }).idents).toEqual({ "band@3": 2 });
    // the source acquired and upgraded is still two acquisitions
    expect(rowOf(modelOf(profile, [low, high], { ...options, max_new: 3 }), "own.band@1")).toEqual({ "n[FINGER|band]": 1, "made[band@3]": 1, "new[band@1]": -1 });
  });

  // -- an upgraded item and the copies of it -----------------------------------------------------------------------------------------------

  const madeOf = (model, target) => {
    const at = model.col_names.indexOf(`made[${target}]`);
    expect(at, `no column called made[${target}]`).toBeGreaterThanOrEqual(0);
    return [model.col_lb[at], model.col_ub[at], model.integrality[at]];
  };
  const noMade = (model) => model.col_names.every((name) => !name.startsWith("made[")) && rowsNamed(model, "made.").length === 0;

  it("makes a target worn more than once from one copy of its source, and each other wear is a copy of the target", () => {
    const low = ring("band", 4, { tier: 2 });
    const high = ring("band", 9, { tier: 4 });
    const pool = [low, high, ring("filler", 1)];
    const upgrades = { "band@4": "band@2" };
    const model = modelOf(profile, pool, { owned_caps: { "band@2": 1 }, upgrades, max_new: 2 });
    expect(madeOf(model, "band@4")).toEqual([0, 1, 1]);
    expect(model.info.binaries.made).toBe(1); // counted with the other binaries of the build
    expect(rowOf(model, "made.band@4")).toEqual({ "n[FINGER|band@4]": 1, "made[band@4]": -2 }); // worn at all: made
    const r = model.row_names.indexOf("made.band@4");
    expect([model.row_lb[r], model.row_ub[r]]).toEqual([null, 0]);
    // one copy of the source, however often the target is worn: the target's own columns are not in the row
    expect(rowOf(model, "own.band@2")).toEqual({ "n[FINGER|band]": 1, "made[band@4]": 1 });
    expect(model.row_names.indexOf("made.band@4")).toBeLessThan(model.row_names.indexOf("own.band@2"));
    expect(solve(pool, { owned_caps: { "band@2": 1 }, upgrades, max_new: 2 }).idents).toEqual({ "band@4": 2 }); // the owned copy upgraded and a copy of the upgrade
    expect(solve(pool, { owned_caps: { "band@2": 1 }, upgrades, max_new: 1 }).idents).toEqual({ "band@4": 1, "filler@0": 1 });
    expect(solve(pool, { owned_caps: { "band@2": 1 }, upgrades, max_new: 3 }).idents).toEqual({ "band@4": 2 });
    expect(solve(pool, { owned_caps: { "band@2": 1 }, upgrades, max_new: 0 }).idents).toEqual({ "band@2": 1, "filler@0": 1 });
    const unlimited = modelOf(profile, pool, { owned_caps: { "band@2": 1 }, upgrades }); // no limit: the same two wears, and no new.limit
    expect(solve(pool, { owned_caps: { "band@2": 1 }, upgrades }).idents).toEqual({ "band@4": 2 });
    expect(rowsNamed(unlimited, "new.")).toEqual([]);
    expect(rowOf(unlimited, "made.band@4")).toEqual({ "n[FINGER|band@4]": 1, "made[band@4]": -2 });
  });

  it("does not use up more copies of the source for the further copies of a target", () => {
    const pool = [ring("band", 4, { tier: 2 }), ring("band", 9, { tier: 4 }), ring("filler", 1)];
    const upgrades = { "band@4": "band@2" };
    for (const copies of [1, 2, 3]) expect(solve(pool, { owned_caps: { "band@2": copies }, upgrades, max_new: 2 }).idents, String(copies)).toEqual({ "band@4": 2 });
    // the places the target does not take stay with owned copies of the source
    const wide = [ring("band", 4, { tier: 2, slots: ["FINGER", "EAR"] }), ring("band", 9, { tier: 4, slots: ["FINGER", "EAR"] })];
    expect(solve(wide, { owned_caps: { "band@2": 3 }, upgrades, max_new: 2 }).idents).toEqual({ "band@4": 2, "band@2": 2 });
  });

  it("counts the made column in the row of a duplicated source, which keeps its extra copies", () => {
    const pool = [ring("band", 4, { tier: 2 }), ring("band", 9, { tier: 4 }), ring("filler", 1)];
    const options = { owned_caps: { "band@2": 1 }, new_keys: ["band@2"], upgrades: { "band@4": "band@2" } };
    const model = modelOf(profile, pool, { ...options, max_new: 3 });
    expect(rowOf(model, "own.band@2")).toEqual({ "n[FINGER|band]": 1, "made[band@4]": 1, "new[band@2]": -1 });
    expect(model.col_ub[model.col_names.indexOf("new[band@2]")]).toBe(2); // what the row can hold above the count: 2 + 1 - 1
    expect(solve(pool, { ...options, max_new: 3 }).idents).toEqual({ "band@4": 2 });
    expect(solve(pool, { ...options, max_new: 1 }).idents).toEqual({ "band@4": 1, "filler@0": 1 });
  });

  it("gives two targets of one source a made column each, sharing the copies of the source, in the order of the options", () => {
    const pool = [ring("band", 4, { tier: 1 }), ring("band", 7, { tier: 3 }), ring("band", 9, { tier: 5 })];
    const upgrades = { "band@3": "band@1", "band@5": "band@1" };
    const model = modelOf(profile, pool, { owned_caps: { "band@1": 1 }, upgrades, max_new: 2 });
    expect(model.row_names.filter((name) => name.startsWith("made.") || name.startsWith("own."))).toEqual(["made.band@3", "made.band@5", "own.band@1"]);
    expect(rowOf(model, "own.band@1")).toEqual({ "n[FINGER|band]": 1, "made[band@3]": 1, "made[band@5]": 1 });
    expect(model.info.binaries.made).toBe(2);
    expect(solve(pool, { owned_caps: { "band@1": 1 }, upgrades, max_new: 2 }).idents).toEqual({ "band@5": 2 }); // one copy of the source makes one of the two targets
    const reversed = modelOf(profile, [...pool].reverse(), { owned_caps: { "band@1": 1 }, upgrades: { "band@5": "band@1", "band@3": "band@1" }, max_new: 2 });
    expect(JSON.stringify(reversed)).toBe(JSON.stringify(model));
  });

  it("makes the made column only when the row of the source can bind", () => {
    const pool = [ring("band", 4, { tier: 2 }), ring("band", 9, { tier: 4 })];
    for (const [count, bound] of [[1, true], [2, true], [3, false], [9, false]]) {
      // two places of the source and one made: 3
      const model = modelOf(profile, pool, { owned_caps: { "band@2": count }, upgrades: { "band@4": "band@2" }, max_new: 2 });
      expect(model.row_names.includes("own.band@2"), String(count)).toBe(bound);
      expect(model.col_names.includes("made[band@4]"), String(count)).toBe(bound);
      expect(model.row_names.includes("made.band@4"), String(count)).toBe(bound);
    }
  });

  it("counts a target that can be worn once at most by its wear, as it always was", () => {
    const stud = (hp, tier) => ring("stud", hp, { tier, slots: ["EAR"], lore: true });
    const helm = (hp, tier) => ring("helm", hp, { tier, slots: ["HEAD"] });
    const band = [ring("band", 4, { tier: 2 }), ring("band", 9, { tier: 4 })];
    const upgrades = (target, source) => ({ [target]: source });
    const lore = modelOf(profile, [stud(3, 1), stud(8, 3)], { owned_caps: { "stud@1": 1 }, upgrades: upgrades("stud@3", "stud@1"), max_new: 2 });
    const place = modelOf(profile, [helm(3, 1), helm(8, 3)], { owned_caps: { "helm@1": 1 }, upgrades: upgrades("helm@3", "helm@1"), max_new: 3 });
    const one = modelOf(profile, band, { owned_caps: { "band@2": 1 }, upgrades: upgrades("band@4", "band@2"), max_new: 1 });
    const none = modelOf(profile, band, { owned_caps: { "band@2": 1 }, upgrades: upgrades("band@4", "band@2"), max_new: 0 });
    for (const [name, model] of Object.entries({ lore, place, one, none })) {
      expect(noMade(model), name).toBe(true);
      expect(model.info.binaries.made, name).toBe(0);
    }
    expect(rowOf(one, "own.band@2")).toEqual({ "n[FINGER|band]": 1, "n[FINGER|band@4]": 1 }); // the target's columns, as before
    expect(rowOf(one, "new.limit")).toEqual({ "n[FINGER|band@4]": 1 });
    expect(rowOf(place, "own.helm@1")).toEqual({ "n[HEAD|helm]": 1, "n[HEAD|helm@3]": 1 });
  });

  it.each([
    ["the source is not in the pool", { "low@1": 1 }, { "low@4": "low@1" }, /low@1 is not an item of the pool/],
    ["the target is not in the pool", { "low@2": 1 }, { "low@6": "low@2" }, /low@6 is not an item of the pool/],
    ["the source is another key than the target", { "low@2": 1 }, { "low@4": "ghost@2" }, /same key/],
    ["the source is not owned", {}, { "low@4": "low@2" }, /not owned/],
    ["the source is owned none", { "low@2": 0 }, { "low@4": "low@2" }, /not owned/],
    ["the target is owned", { "low@2": 1, "low@4": 1 }, { "low@4": "low@2" }, /is owned/],
    ["the target is below the source", { "low@4": 1 }, { "low@2": "low@4" }, /higher tier/],
    ["the target is the source", { "low@2": 1 }, { "low@2": "low@2" }, /higher tier/],
    ["the key is another", { "low@2": 1 }, { "other@3": "low@2" }, /same key/],
    ["a chain", { "low@2": 1, "low@4": 1, "other@1": 1 }, { "other@3": "other@1", "low@4": "low@2", "low@2": "low@4" }, /higher tier|is owned/],
    ["the source is not an ident", { "low@2": 1 }, { "low@4": "low" }, /not an item ident/],
    ["the upgrades are a list", { "low@2": 1 }, [["low@4", "low@2"]], /must be an object/],
  ])("refuses a bad upgrade: %s", (_, caps, upgrades, message) => {
    const pool = [ring("low", 3, { tier: 2 }), ring("low", 9, { tier: 4 }), ring("other", 1, { tier: 1 }), ring("other", 5, { tier: 3 })];
    expect(() => modelOf(profile, pool, { owned_caps: caps, upgrades, max_new: 1 })).toThrow(message);
  });
});

// ---- what the builder refuses, and how it reads what it is given -----------------------------------------------------------------------------

describe("the inputs of the builder", () => {
  const profile = profileWith({ weights: { HP: 1 } });
  const ring = gear("ring", ["FINGER"], { stats: { HP: 5 } });

  it("builds with no options, no buff set and no setup, and takes an omitted setup for none", () => {
    const model = buildMilp(profile, [ring], null, null);
    expect(model.info.items).toBe(2); // the ring fits a finger place and, under the all rule, an Any place
    expect(JSON.stringify(buildMilp(profile, [ring], undefined, undefined, undefined))).toBe(JSON.stringify(model));
    expect(JSON.stringify(buildMilp(profile, [ring], null, null, {}))).toBe(JSON.stringify(model));
    expect(JSON.stringify(buildMilp(profile, [ring], null, null, null))).toBe(JSON.stringify(model));
  });

  it("refuses a setup it does not know", () => {
    for (const setup of ["BOGUS", "", "2H", 3, false, {}]) expect(() => buildMilp(profile, [ring], setup, null, {}), String(setup)).toThrow(/unknown setup/);
    for (const setup of [null, "1h-shield", "2h", "dw", "stick"]) expect(() => buildMilp(profile, [ring], setup, null, {}), String(setup)).not.toThrow();
  });

  it("refuses an option it does not read, since a misspelt one would change nothing and the model look right", () => {
    for (const name of ["owned_cap", "any-rule", "hasteAssumed", "mutation", "legacy", "new_key", "maxNew", "__proto__", "constructor", ""]) {
      const options = JSON.parse(`{${JSON.stringify(name)}: 1}`);
      expect(() => buildMilp(profile, [ring], null, null, options), name).toThrow(ModelError);
    }
    expect(() => buildMilp(profile, [ring], null, null, { owned_cap: {} })).toThrow(/owned_cap\)/);
    expect(() => buildMilp(profile, [ring], null, null, "any_rule")).toThrow(/must be an object/);
    expect(() => buildMilp(profile, [ring], null, null, [])).toThrow(/must be an object/);
  });

  it("refuses a rule for the Any group that is not one, and a haste that is not a whole number of at least 0", () => {
    for (const rule of ["ALL", "", null, 1, ["all"]]) expect(() => buildMilp(profile, [ring], null, null, { any_rule: rule }), String(rule)).toThrow(/any_rule/);
    for (const haste of [-1, 1.5, "10", true, NaN, Infinity, [1]]) expect(() => buildMilp(profile, [ring], null, null, { haste_assumed: haste }), String(haste)).toThrow(/haste_assumed/);
    expect(buildMilp(profile, [ring], null, null, { haste_assumed: 0 }).info.haste_assumed).toBe(0);
  });

  it("takes an option that is a getter or hidden for what it is not, plain data, and an options object of a class for not an object", () => {
    const getter = {};
    Object.defineProperty(getter, "any_rule", { get: () => "all", enumerable: true });
    expect(() => buildMilp(profile, [ring], null, null, getter)).toThrow(/not plain data/);
    const hidden = Object.defineProperty({}, "any_rule", { value: "all", enumerable: false });
    expect(() => buildMilp(profile, [ring], null, null, hidden)).toThrow(/not plain data/);
    class Options {}
    expect(() => buildMilp(profile, [ring], null, null, new Options())).toThrow(/must be an object/);
    const symbol = { [Symbol("any_rule")]: "all" };
    expect(() => buildMilp(profile, [ring], null, null, symbol)).toThrow(/symbol/);
  });

  it("refuses a list of items that is not one, that has a hole, or that holds what is not an item", () => {
    expect(() => buildMilp(profile, "ring", null, null, {})).toThrow(/list of the pool/);
    expect(() => buildMilp(profile, { length: 1, 0: ring }, null, null, {})).toThrow(/list of the pool/);
    // eslint-disable-next-line no-sparse-arrays
    expect(() => buildMilp(profile, [ring, , ring], null, null, {})).toThrow(/items\[1\] is a hole/);
    expect(() => buildMilp(profile, new Array(2), null, null, {})).toThrow(/hole/);
    for (const bad of [null, 3, "ring", [ring], undefined]) expect(() => buildMilp(profile, [bad], null, null, {}), String(bad)).toThrow(/must be an item/);
  });

  it("refuses an item that is not what atTier gives, and says what is wrong with it", () => {
    const bad = (changes) => () => buildMilp(profile, [{ ...ring, ...changes }], null, null, { any_rule: "all" });
    expect(bad({ key: "" })).toThrow(/must have a key/);
    expect(bad({ key: 7 })).toThrow(/must have a key/);
    expect(bad({ tier: 11 })).toThrow(/tier must be a whole number from 0 to 10/);
    expect(bad({ tier: -1 })).toThrow(/tier/);
    expect(bad({ tier: 1.5 })).toThrow(/tier/);
    expect(bad({ stats: { FLAGELLATION: 3 } })).toThrow(/unknown stat FLAGELLATION/);
    expect(bad({ stats: { HASTE: 3 } })).toThrow(/unknown stat HASTE/); // worn haste is the field haste of the item
    expect(bad({ stats: { HP: 1.5 } })).toThrow(/must be a whole number/);
    expect(bad({ stats: [1] })).toThrow(/must be an object/);
    expect(bad({ sv: { LIGHT: 3 } })).toThrow(/unknown resist LIGHT/);
    expect(bad({ sv: { CORRUPTION: 3 } })).not.toThrow(); // known, and never scored
    expect(bad({ haste: 1.5 })).toThrow(/haste must be a whole number/);
    expect(bad({ weight10: "3" })).toThrow(/weight10 must be a whole number/);
    expect(bad({ lore: 1 })).toThrow(/lore must be true or false/);
    expect(bad({ is_shield: "no" })).toThrow(/is_shield must be true or false/);
    expect(bad({ slots: "FINGER" })).toThrow(/slots must be a list/);
    expect(bad({ slots: ["FINGER", 3] })).toThrow(/list of texts/);
    // eslint-disable-next-line no-sparse-arrays
    expect(bad({ slots: ["FINGER", , "EAR"] })).toThrow(/hole/);
    expect(bad({ classes: undefined })).toThrow(/classes must be a list/);
    expect(bad({ weapon: 3 })).toThrow(/weapon must be null or an object/);
    expect(bad({ weapon: { dmg: 1.5, delay: 3, bonus: null, two_handed: false } })).toThrow(/dmg and delay must be whole numbers/);
    expect(bad({ weapon: { dmg: 10, delay: 3, bonus: "2", two_handed: false } })).toThrow(/bonus/);
    expect(bad({ weapon: { dmg: 10, delay: 3, bonus: null, two_handed: 0 } })).toThrow(/two_handed/);
    expect(bad({ races: "HUM" })).toThrow(/races must be a list/);
    expect(bad({ deity: "Brell" })).toThrow(/deity must be a list/);
  });

  it("refuses an item twice in the pool, and takes the same key at two tiers for two items", () => {
    expect(() => buildMilp(profile, [ring, ring], null, null, {})).toThrow(/item ring \(tier 0\) is in the pool twice/);
    expect(() => buildMilp(profile, [ring, { ...ring, tier: 1 }], null, null, {})).not.toThrow();
  });

  it("builds an item whose key could poison a lookup, since no lookup of a name goes through an object", () => {
    for (const key of ["__proto__", "constructor", "prototype", "toString", "hasOwnProperty"]) {
      const odd = gear(key, ["FINGER", "EAR"], { stats: { HP: 5 }, lore: true });
      const model = buildMilp(profile, [odd], null, null, { any_rule: "explicit", owned_caps: { [`${key}@0`]: 1 }, new_keys: [`${key}@0`] });
      expect(model.col_names, key).toEqual([`n[EAR|${key}]`, `n[FINGER|${key}]`]);
      expect(model.item_cols.map(([, , name]) => name), key).toEqual([key, key]);
      expect(model.row_names, key).toEqual([`lore.${key}`]);
    }
    // a stat or a resist of that name is not one the model knows
    for (const name of ["__proto__", "constructor"]) {
      const stats = JSON.parse(`{${JSON.stringify(name)}: 3}`);
      expect(() => buildMilp(profile, [{ ...ring, stats }], null, null, {})).toThrow(/unknown stat/);
    }
    // nor do the ids of the buffs go through an object: an id is a number, and its entry is found in a map of the table's keys
    const table = JSON.parse('{"__proto__": {"vec": {"HP": 1}}, "1": {"vec": {"HP": 1}}}');
    const set = { always_on: [], optional: [1], conflicts: [], cliques: [], cardinality: null };
    expect(buildMilp(profile, [ring], null, { set, table }, {}).col_names).toContain("buff[1]");
    expect(() => buildMilp(profile, [ring], null, { set: { ...set, optional: [2] }, table }, {})).toThrow(/no entry for the buff 2/);
  });

  it("builds the same model after another reader has tried to change the profile the evaluator remembers for it", () => {
    // profileOf(profile) is compiled once for a profile that is frozen all through and shared by every reader of it: its lists were open to an assignment
    const shared = profileWith({ weights: { HP: 1, AC: 2 } });
    const before = JSON.stringify(modelOf(shared, [ring]));
    const compiled = profileOf(shared);
    expect(() => { compiled.naked[1] = compiled.naked[1].add(compiled.naked[1]); }).toThrow(TypeError);
    expect(() => { compiled.buff[0] = compiled.naked[0]; }).toThrow(TypeError);
    expect(() => { compiled.weights.regen[0] = compiled.naked[0]; }).toThrow(TypeError);
    expect(() => { compiled.regenCaps[0] = compiled.naked[0]; }).toThrow(TypeError);
    expect(JSON.stringify(modelOf(shared, [ring]))).toBe(before);
    expect(JSON.stringify(modelOf(profileWith({ weights: { HP: 1, AC: 2 } }), [ring]))).toBe(before);
  });

  it("does not change what it is given, and takes what is frozen all through", () => {
    const items = [ring, gear("band", ["EAR"], { stats: { HP: 3 }, tier: 2 })];
    const mutable = {
      profile: clone(profile),
      items: clone(items),
      buffset: clone(buffsetOf({ optional: [buffOf(1, { HP: 5 })] })),
      options: { owned_caps: { "band@2": 1 }, new_keys: ["ring@0"], max_new: 1, upgrades: {}, haste_assumed: 0 },
    };
    const before = JSON.stringify(mutable);
    const built = buildMilp(mutable.profile, mutable.items, "stick", mutable.buffset, mutable.options);
    expect(JSON.stringify(mutable)).toBe(before);
    const frozen = buildMilp(profile, items, "stick", deepFreeze(clone(mutable.buffset)), deepFreeze(clone(mutable.options)));
    expect(JSON.stringify(frozen)).toBe(JSON.stringify(built));
    // the document is frozen too: nothing can change it between the builder and the solver
    expect(Object.isFrozen(frozen) && Object.isFrozen(frozen.A) && Object.isFrozen(frozen.A.value) && Object.isFrozen(frozen.item_cols[0])).toBe(true);
    expect(Object.isFrozen(frozen.info) && Object.isFrozen(frozen.info.binaries)).toBe(true);
    expect(Object.keys(frozen)).toEqual(["version", "sense", "const", "col_names", "col_lb", "col_ub", "integrality", "c", "row_names", "row_lb", "row_ub", "A", "item_cols", "buff_cols", "info"]);
  });

  it("refuses a buff set that is not one, with a hole in a list, or with a buff the table does not know", () => {
    const good = clone(buffsetOf({ optional: [buffOf(1, { HP: 5 }), buffOf(2, { HP: 6 })], conflicts: [[1, 2]] }));
    const build = (buffset) => () => buildMilp(profile, [ring], null, buffset, {});
    expect(build(good)).not.toThrow();
    expect(build(7)).toThrow(/null or an object/);
    expect(build({ set: good.set })).toThrow(/needs a set and a table/);
    expect(build({ ...good, table: [] })).toThrow(/needs a set and a table/);
    expect(build({ ...good, set: { ...good.set, optional: "1" } })).toThrow(/list of buff ids/);
    expect(build({ ...good, set: { ...good.set, optional: [1.5] } })).toThrow(/id of a buff/);
    // eslint-disable-next-line no-sparse-arrays
    expect(build({ ...good, set: { ...good.set, optional: [1, , 2] } })).toThrow(/hole/);
    // eslint-disable-next-line no-sparse-arrays
    expect(build({ ...good, set: { ...good.set, cliques: [[1, , 2]] } })).toThrow(/hole/);
    expect(build({ ...good, set: { ...good.set, conflicts: [[1]] } })).toThrow(/pair of buff ids/);
    expect(build({ ...good, set: { ...good.set, cardinality: -1 } })).toThrow(/cardinality/);
    expect(build({ ...good, set: { ...good.set, optional: [1, 3] } })).toThrow(/no entry for the buff 3/);
    expect(build({ ...good, table: { ...good.table, 1: { vec: { LUCK: 3 } } } })).toThrow(/component \(LUCK\)/);
    expect(build({ ...good, table: { ...good.table, 1: { vec: { HP: "5" } } } })).toThrow(/must be a number/);
    expect(build({ ...good, set: { ...good.set, cliques: [[1, 5]] } })).toThrow(/clique names buff 5, which is not optional/);
    expect(build({ ...good, set: { ...good.set, conflicts: [[1, 5, []]] } })).toThrow(/conflict names buff 1 or 5, which is not optional/);
  });

  describe("a buff set that the bundle cannot write", () => {
    // The sets the bundle holds (every trio at both levels, four sets each) name each buff once, never as fixed and as optional at once, with
    // conflicts as [a, b, reasons] and only optional buffs in the conflicts and the cliques: a set that differs is refused, since the
    // columns and rows of a buff would be two of one name, or only one of them would be bound.
    const three = () => clone(buffsetOf({ optional: [buffOf(1, { HP: 5 }), buffOf(2, { HP: 6 }), buffOf(3, { HP: 7 })], conflicts: [[1, 2]] }));
    const build = (buffset, changes = {}) => () => modelOf(profileWith({ weights: { HP: 1 }, ...changes }), [], { buffset });

    it("refuses a buff that a list names twice, where the totals of the profile would not tell", () => {
      const doubled = three();
      doubled.set.optional = [1, 1, 2, 3];
      expect(build(doubled)).toThrow(ModelError);
      expect(build(doubled)).toThrow(/the buff set's optional names buff 1 twice/);
      const twice = clone(buffsetOf({ always: [buffOf(9, { STR: 30 })] }));
      twice.set.always_on = [9, 9];
      expect(build(twice, { buff_totals: { STR: 60 } })).toThrow(/the buff set's always_on names buff 9 twice/); // 60 is what the two copies add up to
      expect(build(twice, { buff_totals: { STR: 30 } })).toThrow(/the buff set's always_on names buff 9 twice/);
      const zero = three();
      zero.set.optional = [0, -0, 2];
      zero.table["0"] = zero.table["1"];
      expect(build(zero)).toThrow(/names buff 0 twice/);
    });

    it("refuses a buff that is both always on and optional", () => {
      const both = clone(buffsetOf({ always: [buffOf(1, { HP: 5 })], optional: [buffOf(2, { HP: 6 })] }));
      both.set.optional = [1, 2];
      expect(build(both, { buff_totals: { HP: 5 } })).toThrow(/buff 1 is both always on and optional/);
      expect(build(both, { buff_totals: { HP: 5 } })).toThrow(ModelError);
      const apart = clone(buffsetOf({ always: [buffOf(1, { HP: 5 })], optional: [buffOf(2, { HP: 6 })] }));
      expect(build(apart, { buff_totals: { HP: 5 } })).not.toThrow();
    });

    it("refuses a conflict that is not a pair of ids with, as the bundle writes it, a list of reasons", () => {
      const conflictsOf = (...conflicts) => {
        const set = three();
        set.set.conflicts = conflicts;
        set.set.cliques = []; // no clique covers a pair: a row binds each conflict
        return set;
      };
      const wrong = [
        [1, 2, 3], [10, 11, 12], [1, 2, "why"], [1, 2, [3]], [1, 2, ["why"], 4], [1, 2, null], [1, 2, { 0: "why" }], [1, 2, [["why"]]],
        [1], [], [1, 2, 3, 4], "12", 12, null, { 0: 1, 1: 2 }, ["1", "2"], [1.5, 2], [1, null], [true, 2],
      ];
      for (const entry of wrong) {
        expect(build(conflictsOf(entry)), JSON.stringify(entry)).toThrow(ModelError);
        expect(build(conflictsOf(entry)), JSON.stringify(entry)).toThrow(/the buff set's conflicts\[0\] must be/);
      }
      // eslint-disable-next-line no-sparse-arrays
      expect(build(conflictsOf([1, 2, ["why", , "why not"]]))).toThrow(/conflicts\[0\]\[2\]\[1\] is a hole/);
      expect(build(conflictsOf([1, 2], [2, 3])), "the second one").not.toThrow();
      expect(build(conflictsOf([1, 2], [2, 3, 4])), "the second one").toThrow(/conflicts\[1\] must be/);
      for (const entry of [[1, 2], [1, 2, []], [1, 2, ["why"]], [1, 2, ["why", "why not"]]]) {
        expect(build(conflictsOf(entry)), JSON.stringify(entry)).not.toThrow();
      }
      // the reasons are not read: a pair with them and one without give the same model
      const profile = profileWith({ weights: { HP: 1 } });
      const withReasons = modelOf(profile, [], { buffset: conflictsOf([1, 2, ["a", "b"]]) });
      const without = modelOf(profile, [], { buffset: conflictsOf([1, 2]) });
      expect(JSON.stringify(withReasons)).toBe(JSON.stringify(without));
      expect(rowsNamed(withReasons, "buff.conflict")).toEqual(["buff.conflict[1,2]"]);
    });

    it("says which conflict or clique names a buff that is not optional", () => {
      const set = three();
      set.set.cliques = [[1, 2, 4]];
      expect(build(set)).toThrow(/clique names buff 4, which is not optional/);
      const fixed = clone(buffsetOf({ always: [buffOf(9, { HP: 1 })], optional: [buffOf(1, { HP: 5 }), buffOf(2, { HP: 6 })], conflicts: [[1, 2]] }));
      fixed.set.conflicts = [[1, 9, ["why"]]];
      fixed.set.cliques = [];
      expect(build(fixed, { buff_totals: { HP: 1 } })).toThrow(/conflict names buff 1 or 9, which is not optional/);
      fixed.set.conflicts = [];
      fixed.set.cliques = [[9, 1]];
      expect(build(fixed, { buff_totals: { HP: 1 } })).toThrow(/clique names buff 9, which is not optional/);
    });
  });

  describe("the names of the columns and rows", () => {
    // Model JSON names every column and every row, and both readers refuse a name twice (validate in milp_json.py, validateRequest in protocol.js):
    // a build that makes two of a name is refused when the second is made, naming it.
    const flip = (classes) => [{ cls: classes[0], base: 25, fac: 3 }, { cls: classes[1], base: 85, fac: 2 }, { cls: classes[2], base: 55, fac: 2.5 }];
    const sta = gear("sta", ["HEAD"], { stats: { STA: 150 } });
    const hp = (classes) => profileWith({ weights: { HP: 1 }, naked: { ...NAKED, STA: 0 }, pools: { ...POOLS, MANA: [], HP: flip(classes) } });

    it("builds the select columns of the pools of three classes, and refuses pools that name one class twice (two columns of one name)", () => {
      const model = modelOf(hp(["WAR", "SHD", "CLR"]), [sta]);
      expect(model.info.pools.HP).toBe("select");
      expect(model.col_names.filter((name) => name.startsWith("pool.HP."))).toEqual(
        ["pool.HP.kept.WAR", "pool.HP.z.WAR", "pool.HP.kept.SHD", "pool.HP.z.SHD", "pool.HP.kept.CLR", "pool.HP.z.CLR"],
      );
      expect(() => modelOf(hp(["WAR", "SHD", "WAR"]), [sta])).toThrow(ModelError);
      expect(() => modelOf(hp(["WAR", "SHD", "WAR"]), [sta])).toThrow(/two columns are called pool\.HP\.kept\.WAR/);
      expect(() => modelOf(hp(["WAR", "WAR", "WAR"]), [sta])).toThrow(/two columns are called pool\.HP\.kept\.WAR/);
    });

    it("gives every column and row of a model that has repeated rows by design its own name", () => {
      const buffset = buffsetOf({ optional: [buffOf(1, { HP: 5 }), buffOf(2, { HP: 6 })], conflicts: [[1, 2]], cliques: [[1, 2], [1, 2], [1, 2]] });
      const model = modelOf(profileWith({ weights: { HP: 1 } }), [], { buffset });
      expect(new Set(model.col_names).size).toBe(model.col_names.length);
      expect(new Set(model.row_names).size).toBe(model.row_names.length);
      expect(rowsNamed(model, "buff.clique")).toEqual(["buff.clique[1,2]", "buff.clique[1,2]#2", "buff.clique[1,2]#3"]);
    });
  });

  it("refuses a spell haste that a Profile would refuse: below 0, or below the haste of the always-on buffs", () => {
    // Profile (profile.py) requires spell_haste >= 0 and >= the HASTE of the always-on buffs; the builder read a negative one as 0 in one place and raw in another
    const boots = gear("boots", ["FEET"], { haste: 35 });
    const build = (changes, buffset = null, options = {}) => () => modelOf(profileWith({ weights: { HASTE: 1, DMG: 1 }, ...changes }), [boots], { buffset, ...options });
    for (const spell of [-10, -1, -0.5, -1e-9]) {
      expect(build({ spell_haste: spell }), String(spell)).toThrow(ModelError);
      expect(build({ spell_haste: spell }), String(spell)).toThrow(/profile\.spell_haste must be at least 0/);
    }
    // whatever the options say: the haste to assume being given does not make a negative spell haste go unread
    expect(build({ spell_haste: -10 }, null, { haste_assumed: 12 })).toThrow(/spell_haste must be at least 0/);
    expect(build({ spell_haste: -10 }, null, { haste_assumed: null })).toThrow(/spell_haste must be at least 0/);
    // below the haste of the always-on buffs
    const slowed = buffsetOf({ always: [buffOf(9, { HASTE: 30 })] });
    expect(build({ spell_haste: 20, buff_totals: { HASTE: 30 } }, slowed)).toThrow(/spell_haste must be at least 0 and at least the haste of the always-on buffs/);
    expect(build({ spell_haste: 29.5, buff_totals: { HASTE: 30 } }, slowed)).toThrow(ModelError);
    for (const spell of [30, 30.5, 60]) expect(build({ spell_haste: spell, buff_totals: { HASTE: 30 } }, slowed), String(spell)).not.toThrow();
    // 0 is a spell haste, no spell haste is a profile with none, and the others are as before
    expect(build({ spell_haste: 0 })).not.toThrow();
    expect(build({ spell_haste: null })).not.toThrow();
    expect(build({})).not.toThrow();
    expect(build({ spell_haste: "10" })).toThrow(/spell_haste must be a number/);
    // an always-on haste below 0 is a haste of 0 (a profile can have no spell haste of its own): spell_haste 0 is then enough
    expect(build({ spell_haste: 0, buff_totals: { HASTE: -10 } })).not.toThrow();
    expect(build({ spell_haste: -5, buff_totals: { HASTE: -10 } })).toThrow(/spell_haste must be at least 0/);
  });

  it("reads the profile as the evaluator does, and says so when the evaluator would not read it", () => {
    const { pools, ...headless } = clone(profile);
    expect(pools).toBeDefined();
    expect(() => buildMilp(headless, [ring], null, null, {})).toThrow(EvaluateError);
    expect(() => buildMilp(null, [ring], null, null, {})).toThrow(/profile/);
    expect(() => buildMilp({ ...clone(profile), deity: 7 }, [ring], null, null, {})).toThrow(/deity and race/);
    expect(() => buildMilp({ ...clone(profile), race: ["HUM"] }, [ring], null, null, {})).toThrow(/deity and race/);
    expect(() => buildMilp({ ...clone(profile), spell_haste: "75" }, [ring], null, null, {})).toThrow(/spell_haste must be a number/);
    expect(() => buildMilp({ ...clone(profile), weights: { HP: -1 } }, [ring], null, null, {})).toThrow(EvaluateError);
  });
});

// ---- the Monk bonus ------------------------------------------------------------------------------------------------------------------------

describe("the Monk bonus of the armor class", () => {
  const listing = SAMPLE.read("evaluate/profiles.json");
  const bins = deepFreeze(clone(listing.monk_bins["50"]));
  const curve = Object.fromEntries(["softcap_stones", "hardcap_stones", "full_bonus_ac"].map((name) => [name, Number(bins.curve[name].split("/")[0])]));
  const monk = (changes = {}) => profileWith({ weights: { AC: 3 }, monk: curve, haste_cap: 85, ...changes });
  const heavy = (key, weight10) => gear(key, ["CHEST"], { stats: { AC: 10 }, weight10 });

  it("needs the Monk bins when the armor class has a weight and the profile has a Monk curve, and not otherwise", () => {
    expect(() => modelOf(monk(), [heavy("plate", 300)])).toThrow(/options.monk_bins/);
    expect(() => modelOf(monk(), [heavy("plate", 300)], { monk_bins: null })).toThrow(/needed to read the bonus/);
    expect(() => modelOf(monk({ weights: { HP: 1 } }), [heavy("plate", 300)])).not.toThrow(); // no armor class, no bonus to read
    expect(() => modelOf(profileWith({ weights: { AC: 3 } }), [heavy("plate", 300)])).not.toThrow(); // no Monk
    expect(() => modelOf(monk({ monk: { ...curve, hardcap_stones: curve.hardcap_stones - 1 } }), [heavy("plate", 300)], { monk_bins: bins })).toThrow(/no bins for the Monk curve/);
    expect(() => modelOf(monk({ level: 55, monk: { ...curve, full_bonus_ac: 80 } }), [heavy("plate", 300)], { monk_bins: bins })).toThrow(/no bins for the Monk curve|another level/);
  });

  it("is a constant when one bin covers every reachable weight, and a choice of bins when the weights reach more", () => {
    const light = modelOf(monk(), [heavy("cloth", 50)], { monk_bins: bins }); // 5 stones: the full bonus
    expect(rowsNamed(light, "monk.")).toEqual([]);
    expect(light.info.binaries.monk).toBe(0);
    const plate = modelOf(monk(), [heavy("plate", 500)], { monk_bins: bins }); // 50 stones: from the full bonus to a penalty
    expect(rowsNamed(plate, "monk.")).toEqual(["monk.one", "monk.upper", "monk.lower"]);
    expect(plate.info.binaries.monk).toBeGreaterThan(1);
    const zs = plate.col_names.filter((name) => name.startsWith("monk.z"));
    expect(zs).toHaveLength(plate.info.binaries.monk);
    expect(rowOf(plate, "monk.one")).toEqual(Object.fromEntries(zs.map((name) => [name, 1])));
    // the weight of the kit is bound between 10 first and 10 last + 9 of the one bin that is chosen
    expect(rowOf(plate, "monk.upper")["n[CHEST|plate]"]).toBe(500);
    expect(rowOf(plate, "monk.lower")["n[CHEST|plate]"]).toBe(-500);
    expect(plate.row_ub[plate.row_names.indexOf("monk.upper")]).toBe(0);
  });

  it("reads the bins by the table and not by the stone: the heaviest kit costs no more to read than a light one", () => {
    const watch = stopwatch();
    const anvil = modelOf(monk(), [gear("anvil", ["CHEST"], { stats: { AC: 1 }, weight10: 900_000_000 })], { monk_bins: bins });
    expectWithin(watch.stop(), 2000, "the model of a kit with the heaviest anvil");
    const count = anvil.info.binaries.monk;
    // one bin for each run of whole stones with the same bonus in the table (the full bonus, the fade, the penalty that grows), the last going on to the end of the reach
    expect(count).toBe(bins.bonus.filter((bonus, at) => at === 0 || bonus !== bins.bonus[at - 1]).length);
    expect(anvil.col_names.filter((name) => name.startsWith("monk.z"))).toHaveLength(count);
    // the last bin is the weights from its first stone to the last stone the kit can reach, 9 x 10^7: 10 x (9 x 10^7 + 1) - 1 tenths
    expect(rowOf(anvil, "monk.upper")[`monk.z${count - 1}`]).toBe(-900_000_009);
  });

  it("values the armor class of a kit as the evaluator does, with the bonus on top of the cap or inside it", () => {
    for (const placement of ["top", "inside"]) {
      const profile = monk({ placement: { monk: placement, iksar: "top" }, softcap: [100, 0.5] });
      const items = [heavy("plate", 500), heavy("mail", 300), gear("ring", ["FINGER"], { stats: { AC: 5 }, weight10: 5 })];
      for (const force of [[], [["CHEST", "plate"]], [["CHEST", "mail"]]]) {
        const { exact, model } = solved(profile, items, { force, monk_bins: bins });
        expect(model.info.binaries.monk, placement).toBeGreaterThan(0);
        expect(exact.toNumber()).toBeGreaterThan(0);
      }
    }
  });
});

// ---- the best two pools, the planner --------------------------------------------------------------------------------------------------------

describe("planTopPools", () => {
  const spec = (base, fac, key, lo, hi) => ({ base: q(...[].concat(base)), fac: q(...[].concat(fac)), key, lo: q(...[].concat(lo)), hi: q(...[].concat(hi)) });
  // each case and its answer are those of plan_top_pools in model.py
  const CASES = {
    none: [[], "none", []],
    one: [[spec(0, 1, 0, 0, 10)], "all", [0]],
    two: [[spec(0, 1, 0, 0, 10), spec(5, 2, 0, 0, 10)], "all", [0, 1]],
    pair_fixed: [[spec(30, 3, 0, 0, 150), spec(90, 2, 0, 0, 150), spec(10, 1, 0, 0, 150)], "fixed", [0, 1]],
    flip_wide: [[spec(30, 3, 0, 0, 150), spec(90, 2, 0, 0, 150), spec(60, [5, 2], 0, 0, 150)], "select", [0, 1, 2]],
    flip_narrow: [[spec(30, 3, 0, 0, 60), spec(90, 2, 0, 0, 60), spec(60, [5, 2], 0, 0, 60)], "fixed", [1, 2]],
    flip_just_past: [[spec(30, 3, 0, 0, 61), spec(90, 2, 0, 0, 61), spec(60, [5, 2], 0, 0, 61)], "select", [0, 1, 2]],
    boxes_apart: [[spec(0, 1, 1, 0, 10), spec(100, 1, 2, 0, 10), spec(200, 1, 3, 0, 10)], "fixed", [1, 2]],
    boxes_touch: [[spec(0, 1, 1, 0, 100), spec(100, 1, 2, 0, 10), spec(200, 1, 3, 0, 10)], "fixed", [1, 2]],
    boxes_overlap: [[spec(0, 1, 1, 0, 500), spec(100, 1, 2, 0, 500), spec(200, 1, 3, 0, 500)], "select", [0, 1, 2]],
    tie_same: [[spec(10, 1, 0, 0, 5), spec(10, 1, 0, 0, 5), spec(10, 1, 0, 0, 5)], "fixed", [1, 2]],
    tie_cross_at_edge: [[spec(10, 1, 0, 0, 5), spec(10, 1, 0, 0, 5), spec(5, 2, 0, 0, 5)], "fixed", [0, 1]],
    fractions: [[spec([1, 3], [1, 7], 0, 0, 30), spec([2, 3], [1, 14], 0, 0, 30), spec([1, 2], [1, 10], 0, 0, 30)], "select", [0, 1, 2]],
    negative_range: [[spec(0, 1, 0, -50, 50), spec(10, 0, 0, -50, 50), spec(-5, 2, 0, -50, 50)], "select", [0, 1, 2]],
    four_first_two: [[spec(100, 1, 0, 0, 10), spec(90, 1, 0, 0, 10), spec(0, 1, 0, 0, 10), spec(0, 2, 0, 0, 10)], "fixed", [0, 1]],
    four_select: [[spec(100, 1, 0, 0, 100), spec(90, 1, 0, 0, 100), spec(0, 3, 0, 0, 100), spec(0, 2, 0, 0, 100)], "select", [0, 1, 2, 3]],
    mixed_keys_same_range: [[spec(0, 2, 1, 0, 100), spec(0, 1, 1, 0, 100), spec(50, 0, 2, 0, 1)], "select", [0, 1, 2]],
  };

  it.each(Object.entries(CASES))("plans %s as Python does", (_, [specs, mode, indices]) => {
    expect(planTopPools(specs)).toEqual({ mode, indices });
  });

  it("is exact where a double is not: a pool that only touches another at the end of the range does not beat it", () => {
    // 0.1 + 0.2 s reaches 0.3 at s = 1, and 0.1 + 0.2 x 1 is 0.30000000000000004 in doubles: a double would say that the third pool beats the second
    const pools = (hi) => [spec(100, 0, 0, 0, hi), spec([3, 10], 0, 0, 0, hi), spec([1, 10], [1, 5], 0, 0, hi)];
    expect(planTopPools(pools(1))).toEqual({ mode: "fixed", indices: [0, 1] });
    expect(planTopPools(pools([1, 2]))).toEqual({ mode: "fixed", indices: [0, 1] });
    expect(planTopPools(pools([10001, 10000]))).toEqual({ mode: "select", indices: [0, 1, 2] }); // one step past the touching point it does
  });

  it("names an item ident the way the options do", () => {
    expect(ident("ring", 4)).toBe("ring@4");
    expect(ident("w16100", 10)).toBe("w16100@10");
  });
});
