"""The exact solver: a MILP builder, the HiGHS layer under it and the wrapper that solves and values the answer.

``build_milp`` (:mod:`trioforge.solver.model`) turns a profile, an item pool, a weapon setup and a buff set into a
mixed-integer program whose optimum is the best kit by the absolute value F of ``trioforge.model.formulas``; it shares
no row with the evaluator, which is the oracle of every exactness test. :mod:`trioforge.solver.solve` solves a built
model with the pinned HiGHS options, values the kit exactly (an :class:`~trioforge.solver.solve.ExactnessError` if the
model overstates what its kit is worth; a run out of time returns its incumbent with that exact value), places the worn
items by a rule that looks at the items alone and, with ``solve_canonical``, resolves ties deterministically.
:mod:`trioforge.solver.compat` maps a profile and a pool in the old JSON shapes onto the builder, for the private
regression against what the old tools recorded.
"""

from trioforge.solver.model import BuildOptions, Milp, build_milp

__all__ = ["BuildOptions", "Milp", "build_milp"]
