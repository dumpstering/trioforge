// Models for the solver tests, in the shape the worker takes (model JSON v1: CSR rows, `null` for an infinite bound). Shared by the
// unit tests (tests-js/engine-worker.test.mjs) and the browser tests (tests-e2e/engine.spec.mjs). Nothing here is read by the site.

/** A small seeded generator, so a "random" model is the same one on every machine. */
export function mulberry32(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Build the CSR arrays from rows given as {lb, ub, entries: [[column, coefficient], ...]}. */
function csr(rows) {
  const start = [0];
  const index = [];
  const value = [];
  for (const row of rows) {
    for (const [column, coefficient] of row.entries) {
      index.push(column);
      value.push(coefficient);
    }
    start.push(index.length);
  }
  return { start, index, value };
}

const HAND = {
  value: [9, 7, 6, 5, 8, 3, 4, 2],
  weight: [5, 4, 3, 3, 6, 2, 3, 1],
  use: [2, 1, 2, 1, 4, 0, 2, 1],
  capacity: 15,
  headroom: 3,
  bonus: 2,
  constant: 10,
};

/**
 * Eight yes/no columns and one continuous column `y` (no upper bound), maximised:
 *   10 + sum(value * x) + 2 * y
 *   weight row    sum(weight * x) <= 15                      (no lower bound)
 *   count row     sum(x) >= 2                                (no upper bound)
 *   room row      y + 0.5 * sum(use * x) <= 3
 *   pair row      x6 + x7 = 1                                (an equality)
 * The optimum is found independently by `handOptimum`, which tries all 256 choices.
 */
export function handMilp() {
  const n = HAND.value.length;
  const rows = [
    { lb: null, ub: HAND.capacity, entries: HAND.weight.map((w, i) => [i, w]) },
    { lb: 2, ub: null, entries: HAND.value.map((_, i) => [i, 1]) },
    { lb: null, ub: HAND.headroom, entries: [...HAND.use.map((u, i) => [i, u / 2]), [n, 1]] },
    { lb: 1, ub: 1, entries: [[6, 1], [7, 1]] },
  ];
  return {
    version: 1,
    sense: "max",
    const: HAND.constant,
    col_names: [...HAND.value.map((_, i) => `x[${i}]`), "y.room"],
    col_lb: new Array(n + 1).fill(0),
    col_ub: [...new Array(n).fill(1), null],
    integrality: [...new Array(n).fill(1), 0],
    c: [...HAND.value, HAND.bonus],
    row_names: ["weight", "count", "room", "pair"],
    row_lb: rows.map((r) => r.lb),
    row_ub: rows.map((r) => r.ub),
    A: csr(rows),
    item_cols: [],
    buff_cols: [],
    info: {},
  };
}

/**
 * A hand-written model as a complete model JSON v1 document: the names, the item columns, the buff columns and the info that the exporter
 * writes with every model (a hand-written one has no items or buffs). Fields it already has are left as they are.
 */
export function canonical(model) {
  const columns = model.c.length;
  const rows = model.row_lb.length;
  return {
    version: 1,
    ...model,
    col_names: model.col_names ?? Array.from({ length: columns }, (_, j) => `col${j}`),
    row_names: model.row_names ?? Array.from({ length: rows }, (_, r) => `row${r}`),
    item_cols: model.item_cols ?? [],
    buff_cols: model.buff_cols ?? [],
    info: model.info ?? {},
  };
}

/**
 * A linear program: no integer column, so HiGHS runs no tree search for it (it reports -1 nodes and a MIP dual bound of 0). Maximise 10 + 2x + y with
 * x <= 4, y <= 3 and x + y <= 5: x = 4, y = 1, 19.
 */
export function lpMilp() {
  return {
    version: 1,
    sense: "max",
    const: 10,
    col_names: ["x", "y"],
    col_lb: [0, 0],
    col_ub: [4, 3],
    integrality: [0, 0],
    c: [2, 1],
    row_names: ["share"],
    row_lb: [null],
    row_ub: [5],
    A: { start: [0, 2], index: [0, 1], value: [1, 1] },
    item_cols: [],
    buff_cols: [],
    info: {},
  };
}

/** A row with no lower bound (null, not 0): minimise y with y <= 4 and y >= -10 as the column's own bound: -10. */
export function openRowMilp() {
  return canonical({
    version: 1,
    sense: "min",
    const: 0,
    col_lb: [-10],
    col_ub: [null],
    integrality: [0],
    c: [1],
    row_lb: [null],
    row_ub: [4],
    A: { start: [0, 1], index: [0], value: [1] },
  });
}

/** The optimum of `handMilp`, by trying every choice of the eight columns (and the best `y` for each). */
export function handOptimum() {
  const n = HAND.value.length;
  let best = null;
  for (let mask = 0; mask < 1 << n; mask += 1) {
    const x = Array.from({ length: n }, (_, i) => (mask >> i) & 1);
    const dot = (a) => a.reduce((s, c, i) => s + c * x[i], 0);
    if (dot(HAND.weight) > HAND.capacity || x.reduce((s, c) => s + c, 0) < 2 || x[6] + x[7] !== 1) continue;
    const y = HAND.headroom - 0.5 * dot(HAND.use);
    if (y < 0) continue; // no room for even y = 0
    const objective = HAND.constant + dot(HAND.value) + HAND.bonus * y;
    if (best === null || objective > best.objective) best = { objective, x: [...x, y] };
  }
  return best;
}

/** Whether a column vector satisfies every bound and row of a model, and the objective it gives (constant included). */
export function check(model, x, tolerance = 1e-6) {
  const problems = [];
  const n = model.c.length;
  if (x.length !== n) return { problems: [`x has ${x.length} entries, the model ${n} columns`], objective: NaN };
  for (let j = 0; j < n; j += 1) {
    if (model.col_lb[j] !== null && x[j] < model.col_lb[j] - tolerance) problems.push(`column ${j} below its lower bound`);
    if (model.col_ub[j] !== null && x[j] > model.col_ub[j] + tolerance) problems.push(`column ${j} above its upper bound`);
    if (model.integrality[j] && Math.abs(x[j] - Math.round(x[j])) > tolerance) problems.push(`column ${j} is not whole`);
  }
  const { start, index, value } = model.A;
  for (let r = 0; r < model.row_lb.length; r += 1) {
    let activity = 0;
    for (let k = start[r]; k < start[r + 1]; k += 1) activity += value[k] * x[index[k]];
    if (model.row_lb[r] !== null && activity < model.row_lb[r] - tolerance) problems.push(`row ${r} below its lower bound`);
    if (model.row_ub[r] !== null && activity > model.row_ub[r] + tolerance) problems.push(`row ${r} above its upper bound`);
  }
  const objective = model.const + model.c.reduce((s, c, j) => s + c * x[j], 0);
  return { problems, objective };
}

/** The hand model with one more row that no choice can meet: at least 3 from the first two yes/no columns. */
export function infeasibleMilp() {
  const model = handMilp();
  model.row_lb.push(3);
  model.row_ub.push(null);
  model.row_names.push("impossible");
  model.A.index.push(0, 1);
  model.A.value.push(1, 1);
  model.A.start.push(model.A.index.length);
  return model;
}

/**
 * A multi-constraint knapsack of `n` yes/no columns and `m` rows with seeded random weights: easy to state, slow to prove
 * optimal. Used where a solve has to last (a time limit, the main thread's responsiveness).
 */
export function knapsackMilp(seed = 7, n = 120, m = 10) {
  const random = mulberry32(seed);
  const whole = (low, high) => low + Math.floor(random() * (high - low + 1));
  const rows = [];
  for (let r = 0; r < m; r += 1) {
    const weights = Array.from({ length: n }, () => whole(5, 99));
    rows.push({ lb: null, ub: Math.floor(weights.reduce((s, w) => s + w, 0) * 0.4), entries: weights.map((w, j) => [j, w]) });
  }
  return {
    version: 1,
    sense: "max",
    const: 0,
    col_names: Array.from({ length: n }, (_, j) => `pick[${j}]`),
    col_lb: new Array(n).fill(0),
    col_ub: new Array(n).fill(1),
    integrality: new Array(n).fill(1),
    c: Array.from({ length: n }, () => whole(10, 120)),
    row_names: rows.map((_, r) => `limit[${r}]`),
    row_lb: rows.map((r) => r.lb),
    row_ub: rows.map((r) => r.ub),
    A: csr(rows),
    item_cols: [],
    buff_cols: [],
    info: {},
  };
}
