// What the solver is given, in a module of its own that imports nothing: the options of the Python solver that this build accepts, and the model
// document as the solver's `createModel` takes it. The worker (worker.js) solves one model with them and the sessions (solve.js) keep models in the
// solver between solves; both import this file and neither imports the other (the worker will import the sessions). worker.js exports both again,
// so whatever imported them from there still does.

/**
 * The options of the Python solver (pipeline/trioforge/solver/_highs.py) that this build accepts: the same gaps, tolerances, presolve and
 * seed. The build has one thread and refuses the option, so `threads` is not here.
 */
export const SOLVER_OPTIONS = Object.freeze({
  output_flag: false,
  mip_rel_gap: 0,
  mip_abs_gap: 1e-9,
  presolve: "off",
  random_seed: 0,
  mip_feasibility_tolerance: 1e-9,
  primal_feasibility_tolerance: 1e-9,
});

/** The model JSON v1 as the solver's `createModel` takes it (an infinite bound is `null` in the document and the solver's infinity here). */
export function toModelData(highs, model) {
  const infinity = highs.infinity;
  const columns = model.c.length;
  const rows = model.row_lb.length;
  const orInfinite = (value, sign) => (value === null ? sign * infinity : value);
  return {
    numCols: columns,
    numRows: rows,
    sense: model.sense === "max" ? highs.constants.objectiveSense.maximize : highs.constants.objectiveSense.minimize,
    offset: 0, // the constant is added below, as the Python solver does, so that the solver sees the same numbers
    colCost: model.c,
    colLower: model.col_lb.map((value) => orInfinite(value, -1)),
    colUpper: model.col_ub.map((value) => orInfinite(value, 1)),
    rowLower: model.row_lb.map((value) => orInfinite(value, -1)),
    rowUpper: model.row_ub.map((value) => orInfinite(value, 1)),
    matrix: { format: "csr", numRows: rows, numCols: columns, starts: model.A.start, indices: model.A.index, values: model.A.value },
    integrality: model.integrality,
  };
}
