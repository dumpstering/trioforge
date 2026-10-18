"""The thin layer over highspy: one function that solves arrays, and one that solves a :class:`Milp`.

The options are the determinism constants of the project: no relative gap, an absolute gap of 1e-9, presolve off
(until a presolve gate shows that it agrees with presolve off), seed 0, one thread, and feasibility tolerances of
1e-9 for the integrality and the primal rows. Problem scaling stays at its default.

The result carries the HiGHS status mapped to ``optimal`` / ``time_limit`` / ``infeasible``. Anything else
(unbounded, an iteration limit, an interrupt) is a fault of the model and raises ``RuntimeError``.

``highs_options`` (a mapping, on every solving function) replaces single options of :data:`OPTIONS` for one call. It is
how the presolve gate runs the same model with ``presolve`` on and off; nothing else in the project sets it, and the
constants above stay the production settings. :func:`write_mps` writes a model as an MPS file (with the objective
constant as the file's objective offset) for the browser timing proxy and for engine-parity checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from os import PathLike
from typing import Any

import highspy
import numpy as np

__all__ = ["OPTIONS", "RawResult", "run_arrays", "solve_milp", "write_mps"]

#: the HiGHS options every solve uses, in one place.
OPTIONS: dict[str, Any] = {
    "output_flag": False,
    "mip_rel_gap": 0.0,
    "mip_abs_gap": 1e-9,
    "presolve": "off",
    "random_seed": 0,
    "threads": 1,
    "mip_feasibility_tolerance": 1e-9,
    "primal_feasibility_tolerance": 1e-9,
}


@dataclass(frozen=True)
class RawResult:
    """What one HiGHS run gave back.

    ``status`` is ``optimal``, ``time_limit`` or ``infeasible``. ``x`` is the column vector (None when there is
    no solution), ``objective`` is ``c . x`` of the problem as passed (the model's constant is not in it), ``gap``
    the relative MIP gap HiGHS reports (0 when proven optimal), ``nodes`` the branch-and-bound node count and
    ``bound`` the best dual bound found.
    """

    status: str
    x: np.ndarray | None
    objective: float | None
    gap: float | None
    nodes: int | None
    bound: float | None


def _make_lp(
    c: np.ndarray,
    start: np.ndarray,
    index: np.ndarray,
    value: np.ndarray,
    row_lb: np.ndarray,
    row_ub: np.ndarray,
    col_lb: np.ndarray,
    col_ub: np.ndarray,
    integrality: np.ndarray,
    maximize: bool,
    offset: float = 0.0,
) -> Any:
    """The HiGHS model of the arrays (rows in CSR form)."""
    n, m = int(c.shape[0]), int(row_lb.shape[0])
    lp = highspy.HighsLp()
    lp.num_col_ = n
    lp.num_row_ = m
    lp.col_cost_ = np.ascontiguousarray(c, dtype=np.float64)
    lp.col_lower_ = np.ascontiguousarray(col_lb, dtype=np.float64)
    lp.col_upper_ = np.ascontiguousarray(col_ub, dtype=np.float64)
    lp.row_lower_ = np.ascontiguousarray(row_lb, dtype=np.float64)
    lp.row_upper_ = np.ascontiguousarray(row_ub, dtype=np.float64)
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    lp.a_matrix_.start_ = np.ascontiguousarray(start, dtype=np.int32)
    lp.a_matrix_.index_ = np.ascontiguousarray(index, dtype=np.int32)
    lp.a_matrix_.value_ = np.ascontiguousarray(value, dtype=np.float64)
    kind = highspy.HighsVarType
    lp.integrality_ = [kind.kInteger if flag else kind.kContinuous for flag in integrality]
    lp.sense_ = highspy.ObjSense.kMaximize if maximize else highspy.ObjSense.kMinimize
    lp.offset_ = float(offset)
    return lp


def run_arrays(
    c: np.ndarray,
    start: np.ndarray,
    index: np.ndarray,
    value: np.ndarray,
    row_lb: np.ndarray,
    row_ub: np.ndarray,
    col_lb: np.ndarray,
    col_ub: np.ndarray,
    integrality: np.ndarray,
    *,
    maximize: bool = True,
    time_limit: float | None = None,
    warm_start: np.ndarray | None = None,
    highs_options: Mapping[str, Any] | None = None,
) -> RawResult:
    """Solve ``max/min c . x`` over the rows given in CSR form (``start``, ``index``, ``value``).

    ``warm_start`` is a column vector offered to HiGHS as a first incumbent; it is used only if it is feasible.
    ``highs_options`` replaces single entries of :data:`OPTIONS` for this call."""
    n = int(c.shape[0])
    if n == 0:  # HiGHS refuses a program without a column: the answer is the empty vector if every row allows 0
        feasible = bool(np.all(row_lb <= 0.0) and np.all(row_ub >= 0.0))
        if not feasible:
            return RawResult("infeasible", None, None, None, 0, None)
        return RawResult("optimal", np.zeros(0), 0.0, 0.0, 0, 0.0)
    lp = _make_lp(c, start, index, value, row_lb, row_ub, col_lb, col_ub, integrality, maximize)
    solver = highspy.Highs()
    for name, setting in {**OPTIONS, **(highs_options or {})}.items():
        solver.setOptionValue(name, setting)
    if time_limit is not None:
        solver.setOptionValue("time_limit", float(time_limit))
    solver.passModel(lp)
    if warm_start is not None and warm_start.shape[0] == n:
        guess = highspy.HighsSolution()
        guess.col_value = [float(v) for v in warm_start]
        solver.setSolution(guess)
    solver.run()
    status = solver.getModelStatus()
    info = solver.getInfo()
    states = highspy.HighsModelStatus
    if status == states.kOptimal:
        label = "optimal"
    elif status == states.kTimeLimit:
        label = "time_limit"
    elif status == states.kInfeasible:
        label = "infeasible"
    else:
        raise RuntimeError(f"HiGHS ended with status {solver.modelStatusToString(status)!r}")
    x = None
    if label == "optimal" or (label == "time_limit" and info.primal_solution_status == 2):
        x = np.array(solver.getSolution().col_value, dtype=np.float64)
    objective = float(np.dot(c, x)) if x is not None else None
    gap = float(info.mip_gap) if label != "infeasible" and np.isfinite(info.mip_gap) else None
    if label == "optimal" and gap is None:
        gap = 0.0
    return RawResult(label, x, objective, gap, int(info.mip_node_count), float(info.mip_dual_bound))


def solve_milp(
    milp: Any, *, time_limit: float | None = None, highs_options: Mapping[str, Any] | None = None
) -> RawResult:
    """Maximize the objective of ``milp`` (without its constant) and return the raw result."""
    return run_arrays(
        milp.c, milp.A.start, milp.A.index, milp.A.value, milp.row_lb, milp.row_ub, milp.col_lb, milp.col_ub,
        milp.integrality, maximize=True, time_limit=time_limit, highs_options=highs_options,
    )


def write_mps(milp: Any, path: str | PathLike[str]) -> None:
    """Write ``milp`` as an MPS file: the objective is a maximum and the model's constant is the file's objective
    offset, so a reader that solves the file gets the model's full value ``const + c . x``. Rows and columns are
    unnamed (HiGHS writes ``r0``, ``c0`` ...), which keeps the file small. Raises ``RuntimeError`` if HiGHS cannot
    write it."""
    lp = _make_lp(
        milp.c, milp.A.start, milp.A.index, milp.A.value, milp.row_lb, milp.row_ub, milp.col_lb, milp.col_ub,
        milp.integrality, True, offset=milp.const,
    )
    solver = highspy.Highs()
    solver.setOptionValue("output_flag", False)
    solver.passModel(lp)
    status = solver.writeModel(str(path))
    if status == highspy.HighsStatus.kError:
        raise RuntimeError(f"HiGHS could not write {path!s}: {status}")
