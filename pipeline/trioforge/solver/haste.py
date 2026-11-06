"""The truthful solve: the weapon term is paid the haste the kit really counts.

The weapon index of a hand is ``(damage + bonus) / delay * (1 + haste / 100)``, so the weapon term of the objective is a
product of the weapons worn and the kit's haste. A program with one assumed haste for the whole scenario keeps the term
linear in the item columns, and what it assumed was a constant of the scenario (the best spell haste on offer plus the best
worn haste of the pool, whether or not the kit wore that item or took that buff). The kit was then paid for a haste it did
not have, and a haste belt it would have had to wear for it was rejected as worth no more than what the weapons already
got for free.

``solve_scenario`` makes the assumed haste a decision. A kit counts one of a few hastes: an active spell haste (the
always-on buffs', or one optional haste buff's, with the flat haste of Unbound Alacrity) plus the best worn haste piece
(or none), cut at the cap. :func:`~trioforge.solver.model.haste_levels` lists them. For each level ``H`` the program is built
with ``haste_assumed=H``, the row ``haste.floor`` (``haste_floor=H``: the kit counts at least ``H``) and, with ``haste_exact``, the
rows that keep it from counting more (no worn piece above what the active spell haste leaves of ``H``, no buff that alone
counts more). Its optimum is the best kit that counts exactly ``H``, and the model's value of every such kit is its own, at
every point of the search; the best value over the levels is the optimum, because the best kit counts some level ``H*`` and the
program of ``H*`` holds it. Every solution is valued again by the evaluator at the haste it counts
(:func:`~trioforge.solver.solve.revalue`, which changes nothing for a kit that counts its level).

Which solution wins. The largest exact value ``F`` at the haste the kit counts. A solution whose assumed haste is the haste
it counts (consistent: the model's value is the kit's truthful value) goes before one whose kit counts more than was
assumed (its truthful value belongs to a higher level, which has its own program), and among equals the lower level wins.
Each level's own answer is the canonical one (:func:`~trioforge.solver.solve.solve_canonical` by default), so the winner
does not depend on the order the levels were solved in.

The levels are solved best first (the level whose linear relaxation allows the most), and a level whose program cannot reach the
best value found so far is not solved, and none after it: its linear relaxation (an upper bound of every kit that counts exactly that haste) is below the best value by
more than the exactness tolerance. Such a level has no kit that wins or ties. (Without the rows of ``haste_exact`` the programs
of the lower levels would also hold the kits that count more, valued too low; they gave the same kit again and again and
their relaxations were too loose to leave a level out.)

``haste_assumed`` given in the options keeps its old meaning: one program at that constant, no levels, no row. A scenario
that scores no weapon has one program too (see :func:`weapon_term_is_on`).
"""

from __future__ import annotations

import dataclasses
import inspect
import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import numpy as np

from trioforge.model import formulas as fm
from trioforge.model.buffs import BuffSet
from trioforge.model.items import ItemVec
from trioforge.solver._highs import run_arrays
from trioforge.solver.model import BuildOptions, LevelPrograms, Milp, build_milp
from trioforge.solver.solve import EXACTNESS_TOLERANCE, Solution, revalue, solve_canonical

__all__ = ["HasteSolve", "LevelRun", "solve_scenario", "weapon_term_is_on"]


@dataclass(frozen=True)
class LevelRun:
    """What became of one level: ``level`` the haste assumed, ``outcome`` ``"solved"``, ``"infeasible"`` (no kit counts that
    much) or ``"bound"`` (its relaxation is below the best value found: not solved), ``status`` the solver's status
    (``None`` unless solved), ``F`` the truthful value of its kit, ``counted`` the haste the kit counts, ``bound`` the
    relaxation (when asked for), ``seconds`` the time the level took."""

    level: int
    outcome: str
    status: str | None
    F: float | None
    counted: int | None
    bound: float | None
    seconds: float


@dataclass(frozen=True)
class HasteSolve:
    """The answer of :func:`solve_scenario`. ``solution`` is the winning kit valued at the haste it counts and ``milp``
    the program it came from, with ``haste_assumed`` set to that haste (so that ``formulas.evaluate(...,
    haste_assumed=milp.haste_assumed)`` of the kit is ``solution.F``). ``haste`` is that haste, ``level`` the level whose
    program the kit came from (the same, unless the kit counts more than that program assumed; the model's value of the kit is
    its value at ``level``), ``levels`` the levels of the scenario (rising) and ``runs`` what became of each, in the order they
    were taken. ``build_seconds`` and ``solve_seconds`` add up the time of the builders and of the solver (the relaxations
    included) over the levels."""

    solution: Solution
    milp: Milp
    haste: int
    level: int
    levels: tuple[int, ...]
    runs: tuple[LevelRun, ...]
    build_seconds: float = 0.0
    solve_seconds: float = 0.0


def _counted(solution: Solution) -> int:
    """The haste percent the kit of ``solution`` counts (whole, as the program assumes)."""
    counted = Fraction(solution.breakdown.totals["haste"]["counted"])
    if counted.denominator != 1:
        raise ValueError(f"the kit counts a haste of {counted}, which is not a whole number of percent")
    return int(counted)


def _relaxation(milp: Milp) -> float | None:
    """The best value of the program with its integer columns relaxed (an upper bound of its optimum, the constant included);
    None only when HiGHS proves that no point satisfies the rows. A relaxation that ended any other way (a limit, trouble) gives no
    bound, which is ``inf``: the level is then solved, never left out."""
    try:
        result = run_arrays(
            milp.c, milp.A.start, milp.A.index, milp.A.value, milp.row_lb, milp.row_ub, milp.col_lb, milp.col_ub,
            np.zeros(milp.num_cols, dtype=np.int8), maximize=True,
        )
    except RuntimeError:  # unbounded, numeric trouble, an interrupt: no bound
        return math.inf
    if result.status == "infeasible":
        return None
    if result.status != "optimal" or result.objective is None:
        return math.inf
    return milp.const + result.objective


def weapon_term_is_on(profile: Any, setup: str | None) -> bool:
    """Whether the objective scores weapons at all: a weight on damage and a setup that scores it (not ``None``, not the stick)."""
    return setup not in (None, "stick") and fm.compile_profile(profile).weights.get("DMG", 0) != 0


def solve_scenario(
    profile: Any, items: Iterable[ItemVec], setup: str | None, buffset: BuffSet | None = None,
    options: BuildOptions | None = None, *, solver: Callable[..., Solution] = solve_canonical, time_limit: float | None = None,
    bound: bool = True,
) -> HasteSolve:
    """The best kit of the scenario with the weapon term paid the haste the kit counts (see the module docstring).

    ``profile``, ``items``, ``setup``, ``buffset`` and ``options`` are the ones of :func:`~trioforge.solver.model.build_milp`;
    ``options.haste_assumed`` set means one program at that constant. ``solver(milp, time_limit=...)`` is
    ``solve_canonical`` unless the caller names another (``solve`` for the plain solver); ``bound`` turns the relaxation bound
    off (every level is then solved). The solution's ``status`` is ``optimal`` when every level that was solved ended optimal,
    ``time_limit`` when one did not, ``infeasible`` when no level has a kit; ``nodes`` adds up the levels that were solved.
    A scenario whose objective scores no weapon (no damage weight, or a setup that scores none) has one program, since the haste
    it assumes decides nothing; the kit's haste is still the one it counts."""
    opts = options or BuildOptions()
    pool = list(items)
    clock = time.perf_counter
    if opts.haste_floor is not None and opts.haste_assumed is None:
        raise ValueError("haste_floor without haste_assumed: the levels set both")
    if opts.haste_assumed is not None or not weapon_term_is_on(profile, setup):
        began = clock()
        given = opts if opts.haste_assumed is not None else dataclasses.replace(opts, haste_assumed=0)
        milp = build_milp(profile, pool, setup, buffset, given)
        built = clock()
        solution = solver(milp) if time_limit is None else solver(milp, time_limit=time_limit)
        level = milp.haste_assumed
        if opts.haste_assumed is None and solution.kit is not None:
            # no weapon is scored, so the value is the same at any haste: the program is the same one with the haste the kit counts
            level = _counted(solution)
            milp = build_milp(profile, pool, setup, buffset, dataclasses.replace(opts, haste_assumed=level))
            solution = revalue(milp, solution, level)
        run = LevelRun(level, "solved", solution.status, solution.F, None, None, clock() - began)
        return HasteSolve(solution, milp, level, level, (level,), (run,), built - began, clock() - built)
    began = clock()
    shared = LevelPrograms(profile, pool, setup, buffset, opts)  # the level programs share one build
    levels = shared.levels
    build_time = clock() - began
    runs: list[LevelRun] = []
    won: tuple[Any, Solution, Milp, int] | None = None  # (key, solution at the haste it counts, program, level)
    nodes = 0
    stopped = False
    last: tuple[Solution, Milp, int] | None = None  # the answer of the last level solved, with its program and level
    solve_time = 0.0
    takes_cutoff = "cutoff" in inspect.signature(solver).parameters
    # the programs of the levels, each with the best value its relaxation allows; with the bound they are taken best first (the level that can
    # reach most is solved first, and the levels below the best value found are left out), else from the highest level down
    programs: list[tuple[float | None, int, Milp, float]] = []
    first_milp: Milp | None = None
    for level in reversed(levels):
        started = clock()
        milp = shared.program_for(level)
        first_milp = first_milp or milp
        built_at = clock()
        build_time += built_at - started
        ceiling = None
        if bound and len(levels) > 1:
            ceiling = _relaxation(milp)
            solve_time += clock() - built_at
            if ceiling is None:
                runs.append(LevelRun(level, "infeasible", None, None, None, None, clock() - started))
                continue
        programs.append((ceiling, level, milp, clock() - started))
    if bound and len(levels) > 1:
        programs.sort(key=lambda entry: (-entry[0], -entry[1]))
    for ceiling, level, milp, spent in programs:
        started = clock()
        best = None if won is None else float(won[1].breakdown.F)
        floor_value = None if best is None else best - EXACTNESS_TOLERANCE * max(1.0, abs(best))
        if ceiling is not None and floor_value is not None and ceiling < floor_value:
            runs.append(LevelRun(level, "bound", None, None, None, ceiling, spent))
            continue
        # a level is only worth looking for a kit of at least the best value found: the search is told so (a level that has none ends "infeasible")
        cut = floor_value if (bound and takes_cutoff and not stopped) else None
        kwargs: dict[str, Any] = {} if cut is None else {"cutoff": cut}
        if time_limit is not None:
            kwargs["time_limit"] = time_limit
        solution = solver(milp, **kwargs)
        solve_time += clock() - started
        spent += clock() - started
        if solution.status == "infeasible" or (
            cut is not None and solution.status == "optimal" and (solution.kit is None or solution.model_F < cut)
        ):  # (with a cutoff, a kit worth less than it is what the solver came across, not the level's best: the level cannot win)
            runs.append(LevelRun(level, "bound" if cut is not None else "infeasible", solution.status, None, None, ceiling, spent))
            continue
        last = (solution, milp, level)
        nodes += solution.nodes or 0
        if solution.status != "optimal":
            stopped = True
        if solution.kit is None:
            runs.append(LevelRun(level, "solved", solution.status, None, None, ceiling, spent))
            continue
        counted = _counted(solution)
        consistent = counted == milp.haste_assumed
        if not consistent:
            solution = revalue(milp, solution, counted)
            milp = dataclasses.replace(milp, haste_assumed=counted)
        runs.append(LevelRun(level, "solved", solution.status, solution.F, counted, ceiling, spent))
        key = (solution.breakdown.F, consistent, -level)  # the larger is better: value, then consistent, then the lower level
        if won is None or key > won[0]:
            won = (key, solution, milp, level)
    if won is None:
        # no level has a kit: every level is infeasible, or one stopped on its time with none (then the answer says so)
        if last is None:
            nothing = Solution("infeasible", None, None, (), None, 0)
            return HasteSolve(nothing, first_milp, levels[-1], levels[-1], levels, tuple(runs), build_time, solve_time)
        solution, milp, level = last
        solution = dataclasses.replace(solution, nodes=nodes, status="time_limit" if stopped else solution.status)
        return HasteSolve(solution, milp, milp.haste_assumed, level, levels, tuple(runs), build_time, solve_time)
    _, solution, milp, level = won
    solution = dataclasses.replace(solution, nodes=nodes, status="time_limit" if stopped else solution.status)
    return HasteSolve(solution, milp, milp.haste_assumed, level, levels, tuple(runs), build_time, solve_time)
