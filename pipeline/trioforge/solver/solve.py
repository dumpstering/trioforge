"""The solver wrapper: solve a built model, value the answer exactly, and make ties come out the same way every time.

``solve(milp)`` runs HiGHS with the determinism options of :mod:`trioforge.solver._highs`, reads the kit back, puts it
in the canonical order of the places, values it with the exact evaluator (:func:`trioforge.model.formulas.evaluate`)
and compares that value with the one the model reported. The result is a :class:`Solution`.

**The exactness check.** The model's value of a solution is never above the exact value of its kit: for the integer
choices of the kit (items, buffs) the model's best continuous part *is* the oracle's value, and any other feasible
point is worth less. So a model value more than 1e-6 relative **above** the oracle's is an :class:`ExactnessError`, at
any status: the model and the oracle disagree, which is a bug and never a rounding. A model value below the oracle's is
not an error. A solve that ran out of time (``time_limit``) returns the incumbent HiGHS had, whose continuous columns
need not sit at their best values, and so does the tie stage, which minimizes a rank and not the value. Such a kit is
valued by the oracle (the exact ``F`` and ``breakdown``); ``model_F`` keeps what the model said, and for a
``time_limit`` solution the exact ``F`` is a lower bound of the optimum.

**Where the worn items stand.** The solver decides *which* items are worn; where an item that fits several groups stands (a
cloak in the back place or an Any place, a ring in a finger place or an Any place) changes nothing about the value of the
kit, and which place the solver takes depends on the order of its columns and the path of its search. The kit is
therefore placed by a rule that looks at the items alone (:func:`place_canonically`).

*The hands first.* Only the two hands make the place of an item matter to the value: the main hand carries the damage bonus
of the weapon index, the off hand its dual-wield factor and the shield bonus of the armor class. Among the arrangements of
the worn items that the builder allows (an item stands in a hand only if the model has a column for it there, which is
what the setup, the slots and the class rules say; a two-hander leaves the off hand empty; a pair of the same item needs two
copies; whatever is left must still have a place outside the hands) **and whose exact value equals the solution's**, the
hands are filled by one fixed order: the main hand is filled before it is left empty, by the smaller ``(key, tier)``; then
the off hand the same way. Only arrangements worth exactly as much are candidates, so the value is never touched, and only
the ones that come before the solver's own in that order are valued (an arrangement that is already first costs nothing).
Two engines that choose the same items, with the same value, end with the same hands, whatever hands each of them found.

*The other items.* The worn items that are not in a hand are taken in the order of their ``(key, tier)`` and each goes into
the earliest group, in the fixed slot order of :data:`~trioforge.model.items.SLOT_GROUPS`, that it fits and that still
leaves every item after it a place.

Only the arrangement may change. What is checked after the rule has run is the items (copies counted), always, and the
exact value of the kit, whenever arrangements were compared; a :class:`PlacementError` says that they differ (a bug of the
rule, never of the data). The tie stage cannot change either: its ranks belong to the items alone (:func:`tie_ranks`), not to
the places they stand in.

``solve_canonical(milp)`` adds the second stage that resolves ties. Once the best value F* is known, it solves again
with the extra row ``F >= F* - 1e-7 max(1, |F*|)`` and the objective *minimize the total rank*: every item column
costs the rank of its item (its place in the sorted keys, counted from 1) per copy worn, and every buff binary costs
the rank of its id after all the items. Of all the kits that are as good as the best, the one of least total rank wins
whatever order the pool came in and whatever path the solver took. A paired group (EAR, WRIST, FINGER, ANY) is then
written out in key order and empty places come last (:func:`canonical_kit`). Ranks start at 1 so that an item that
adds nothing is never worn.

**The band is only a net for float noise.** The row ``F >= F* - 1e-7 max(1, |F*|)`` lets kits that are a hair under the
best into the second stage, and with weights of very different sizes (1000 for HP, 0.001 for MANA) a band of that
relative width can hold a kit that is truly worth less, for instance one that drops a held item for a lower rank. So
the second stage's kit is accepted only if its exact value (the oracle, in :class:`fractions.Fraction`) equals the
first stage's exact value. Otherwise the first stage's kit stands and ``tie_stage`` says ``"kept-first"``; that kit is
the optimum, but which of several equally good kits it is was left to the solver. A worse second-stage kit is never an
error; only a model that overstates a kit is (:func:`_check_exactness`).

Two different kits can share a total rank (items ranked 1 and 4 against 2 and 3, say); then the solver's own
order decides, which is still the same on every run of one engine but is not promised across engines.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import numpy as np

from trioforge.model import formulas as fm
from trioforge.model.items import SLOT_GROUPS, SLOT_INSTANCES, ItemVec
from trioforge.solver._highs import RawResult, run_arrays, solve_milp
from trioforge.solver.model import Milp, eval_buff_totals

__all__ = [
    "EXACTNESS_TOLERANCE",
    "TIE_TOLERANCE",
    "ExactnessError",
    "PlacementError",
    "Solution",
    "canonical_kit",
    "place_canonically",
    "revalue",
    "solve",
    "solve_canonical",
    "tie_ranks",
]

#: the most the model's own value of a kit may differ from the evaluator's, relative (production; tests demand 1e-9)
EXACTNESS_TOLERANCE = 1e-6
#: the second stage keeps every kit within this relative distance of the best value
TIE_TOLERANCE = 1e-7


class ExactnessError(RuntimeError):
    """The model's objective for its own kit is above the exact evaluator's value of that kit (a bug of the model)."""


class PlacementError(RuntimeError):
    """The canonical placement changed more than where the worn items stand: other items, or another exact value."""


@dataclass(frozen=True)
class Solution:
    """What a solve returned.

    ``status`` is ``optimal``, ``time_limit`` or ``infeasible``. ``kit`` has one entry for each of the 22 places of
    :data:`trioforge.model.items.SLOT_INSTANCES` (``None`` for an empty place), in canonical order; ``buffs`` are the
    ids of the chosen optional buffs. ``F`` is the evaluator's exact value of the kit with those buffs (as a float)
    and ``breakdown`` its full :class:`~trioforge.model.formulas.Breakdown`; ``model_F`` is what the model said. All
    are ``None`` when no kit was found. ``gap`` is HiGHS's relative gap (0 for a proven optimum) and ``nodes`` its
    branch-and-bound node count. ``canonical`` is true when the tie stage ran to its end. For a ``time_limit`` solution
    ``F`` is the oracle's exact value of the incumbent's kit (a lower bound of the optimum), ``model_F`` the model's
    own value of the incumbent (never above ``F``, and often below it) and ``gap`` HiGHS's gap of that incumbent, which
    can only overstate the gap of ``F``. ``tie_stage`` is None for a plain :func:`solve` and for a
    :func:`solve_canonical` whose first stage did not end optimal; ``"applied"`` when the tie stage ran and its kit is
    the answer; ``"kept-first"`` when the tie stage's kit was not accepted (it was worth less than the first stage's, by
    the exact oracle, or the stage did not finish) and the first stage's kit stands.
    """

    status: str
    F: float | None
    kit: tuple[ItemVec | None, ...] | None
    buffs: tuple[int, ...]
    gap: float | None
    nodes: int | None
    model_F: float | None = None
    breakdown: fm.Breakdown | None = None
    canonical: bool = False
    tie_stage: str | None = None


def canonical_kit(groups: Mapping[str, Sequence[ItemVec]]) -> tuple[ItemVec | None, ...]:
    """The kit of ``{group: [items]}`` with each group sorted by key (then tier) into its places, empty places last."""
    kit: list[ItemVec | None] = []
    for name, size in SLOT_GROUPS:
        placed = sorted(groups.get(name, ()), key=lambda item: (item.key, item.tier))
        if len(placed) > size:
            raise ValueError(f"{len(placed)} items in {name}, which has {size} places")
        kit.extend([*placed, *([None] * (size - len(placed)))])
    return tuple(kit)


HAND_GROUPS = ("PRIMARY", "SECONDARY")
_GROUP_ORDER = {name: number for number, (name, _) in enumerate(SLOT_GROUPS)}


def _all_placed(options: Sequence[Sequence[str]], room: Mapping[str, int]) -> bool:
    """Whether every item (``options[i]`` are the groups item ``i`` may stand in) can have a place, given the places
    ``room`` still left in each group: a matching of items to places, found by augmenting paths."""
    stands: dict[str, list[int]] = {group: [] for group in room}

    def place(item: int, tried: set[str]) -> bool:
        for group in options[item]:
            if group in tried:
                continue
            tried.add(group)
            if len(stands[group]) < room[group]:
                stands[group].append(item)
                return True
            for position, other in enumerate(stands[group]):
                if place(other, tried):  # the other item moves to another group, this one takes its place
                    stands[group][position] = item
                    return True
        return False

    return all(place(item, set()) for item in range(len(options)))


def _name(item: ItemVec) -> tuple[str, int]:
    """What tells one item from another: the same key at the same tier is the same item, whatever object stands for it."""
    return item.key, item.tier


def _columns(milp: Milp) -> tuple[dict[tuple[str, int], list[str]], dict[str, set[tuple[str, int]]]]:
    """The places ``milp`` has a column for: ``{item: [groups outside the hands, in the slot order]}`` and, for each hand,
    the set of items that have a column there. The columns are what the builder allows: the slots an item lists, the Any rule,
    the weapon setup (``allowed_in_hand``), the class, deity and race rules."""
    outside: dict[tuple[str, int], list[str]] = {}
    in_hand: dict[str, set[tuple[str, int]]] = {hand: set() for hand in HAND_GROUPS}
    for _, group, item in milp.item_cols:
        if group in HAND_GROUPS:
            in_hand[group].add(_name(item))
        else:
            outside.setdefault(_name(item), []).append(group)
    for options in outside.values():
        options.sort(key=_GROUP_ORDER.__getitem__)
    return outside, in_hand


def _place_outside(items: Sequence[ItemVec], outside: Mapping[tuple[str, int], Sequence[str]]) -> dict[str, list[ItemVec]]:
    """The items that are not in a hand, each in the earliest group of the slot order that the model has a column for it in and
    that has a place left, provided every item after it can still be given a place; taken in the order of ``(key, tier)``."""
    movable = sorted(items, key=_name)
    options = [outside.get(_name(item), []) for item in movable]
    room = {group: size for group, size in SLOT_GROUPS if group not in HAND_GROUPS}
    placed: dict[str, list[ItemVec]] = {}
    for number, item in enumerate(movable):
        for group in options[number]:
            if room[group] == 0:
                continue
            room[group] -= 1
            if _all_placed(options[number + 1 :], room):
                placed.setdefault(group, []).append(item)
                break
            room[group] += 1
        else:
            raise ValueError(f"no place can be found for {item.key} and the items after it: not a placement of this model")
    return placed


def _hand_order(item: ItemVec | None) -> tuple[int, str, int]:
    """Where an item comes in the order of one hand: a filled hand before an empty one, then the smaller ``(key, tier)``."""
    return (1, "", 0) if item is None else (0, item.key, item.tier)


def _evaluator(milp: Milp, buffs: Sequence[int]) -> Any:
    """``value(kit)``: the exact evaluator under the profile, setup, assumed haste and buff totals of ``milp`` and the chosen
    ``buffs``, as the wrapper values a solution."""
    totals = eval_buff_totals(milp.buffset.totals(buffs)) if milp.buffset is not None else None
    legacy = {} if milp.options.legacy is None else {"legacy": milp.options.legacy}  # the legacy objective values it so

    def value(kit: Sequence[ItemVec | None]) -> fm.Breakdown:
        return fm.evaluate(milp.profile, list(kit), totals, setup=milp.setup, haste_assumed=milp.haste_assumed, **legacy)

    return value


def revalue(milp: Milp, solution: Solution, haste: int) -> Solution:
    """``solution`` with its kit valued again by the exact evaluator at the assumed haste ``haste`` (the weapon index at
    that haste) in place of the one ``milp`` assumed: the kit, the buffs and the places stay. ``F`` and ``breakdown`` are the
    new value; ``model_F`` stays what the model said. A solution with no kit is returned as it is."""
    if solution.kit is None:
        return solution
    totals = eval_buff_totals(milp.buffset.totals(solution.buffs)) if milp.buffset is not None else None
    legacy = {} if milp.options.legacy is None else {"legacy": milp.options.legacy}
    breakdown = fm.evaluate(milp.profile, list(solution.kit), totals, setup=milp.setup, haste_assumed=haste, **legacy)
    return dataclasses.replace(solution, F=float(breakdown.F), breakdown=breakdown)


def _kit_of(rest: Sequence[ItemVec], main: ItemVec | None, off: ItemVec | None) -> list[ItemVec | None]:
    """A kit with ``main`` and ``off`` in the hands and ``rest`` in the other places in any order (the evaluator reads only what
    stands in the hands from the place; the wrapper puts the others in the canonical order when it makes the kit)."""
    free = iter(rest)
    return [main if place == "PRIMARY" else off if place == "SECONDARY" else next(free, None) for place in SLOT_INSTANCES]


def _place(
    milp: Milp, groups: Mapping[str, Sequence[ItemVec]], buffs: Sequence[int]
) -> tuple[dict[str, list[ItemVec]], Fraction | None]:
    """:func:`place_canonically` and, when it had to compare arrangements, the exact value of the solver's own (else None)."""
    for hand in HAND_GROUPS:
        if len(groups.get(hand, ())) > 1:
            raise ValueError(f"{len(groups[hand])} items in {hand}, which has one place")
    outside, in_hand = _columns(milp)
    worn = [item for placed in groups.values() for item in placed]
    solver = (next(iter(groups.get("PRIMARY", ())), None), next(iter(groups.get("SECONDARY", ())), None))
    copies = Counter(_name(item) for item in worn)
    by_name = {_name(item): item for item in worn}
    stand = {group: size for group, size in SLOT_GROUPS if group not in HAND_GROUPS}

    def rest_without(main: ItemVec | None, off: ItemVec | None) -> list[ItemVec]:
        left = copies - Counter(_name(item) for item in (main, off) if item is not None)
        return [by_name[name] for name in sorted(left.elements())]

    def legal(main: ItemVec | None, off: ItemVec | None) -> list[ItemVec] | None:
        """What is left for the places outside the hands when ``main`` and ``off`` stand in the hands, or None when that is not an
        arrangement the builder allows: a pair of one item needs two copies, a two-hander leaves the off hand empty, and
        everything else must be able to stand outside the hands."""
        if main is not None and off is not None:
            if _name(main) == _name(off) and copies[_name(main)] < 2:
                return None
            if main.weapon is not None and main.weapon.two_handed:
                return None
        rest = rest_without(main, off)
        return rest if _all_placed([outside.get(_name(item), []) for item in rest], stand) else None

    mains = [by_name[name] for name in sorted(by_name) if name in in_hand["PRIMARY"]] + [None]
    offs = [by_name[name] for name in sorted(by_name) if name in in_hand["SECONDARY"]] + [None]
    here = (_hand_order(solver[0]), _hand_order(solver[1]))
    value = _evaluator(milp, buffs)
    solver_value: Fraction | None = None
    chosen = solver
    for main in mains:
        for off in offs:
            if (_hand_order(main), _hand_order(off)) >= here:
                break  # the solver's own arrangement is reached: none before it was as good, and it stands
            rest = legal(main, off)
            if rest is None:
                continue
            if solver_value is None:
                solver_value = value(_kit_of(rest_without(*solver), *solver)).F
            if value(_kit_of(rest, main, off)).F == solver_value:
                chosen = (main, off)
                break
        else:
            continue
        break
    placed = _place_outside(rest_without(*chosen), outside)
    for hand, item in zip(HAND_GROUPS, chosen):
        if item is not None:
            placed[hand] = [item]
    return {group: sorted(items, key=_name) for group, items in placed.items()}, solver_value


def place_canonically(
    milp: Milp, groups: Mapping[str, Sequence[ItemVec]], buffs: Sequence[int] | None = None
) -> dict[str, list[ItemVec]]:
    """``{group: [items]}`` with the same items, placed by the canonical rule (see the module docstring).

    The hands come first: of the arrangements of the worn items that the model has columns for, that leave the rest a place
    outside the hands and that are worth exactly what the arrangement in ``groups`` is (valued exactly, under the chosen
    ``buffs`` and the setup and assumed haste of ``milp``), the one that fills the main hand before leaving it empty, by the
    smaller ``(key, tier)``, and then the off hand the same way. The others are taken in the order of their ``(key, tier)``
    (copies of one item are alike), and each goes into the earliest group of the fixed slot order that ``milp`` has a column
    for it in (outside the hands) and that has a place left, provided every item after it can still be given a place. The
    result depends on the set of items alone, not on where the solver put them. The placement the solver found is itself a
    way to give every item a place, so the rule always finds one; ``ValueError`` if it does not (``groups`` is not a
    placement of ``milp``).

    ``buffs`` are the ids of the chosen optional buffs, which the arrangements are valued under. They may be left out only
    when ``milp`` has no optional buff (then the empty choice is the only one): a model with optional buffs and no ``buffs``
    is a ``ValueError``, because valuing under the wrong totals could move a hand that should stay.
    """
    if buffs is None:
        if milp.buff_cols:
            raise ValueError(
                "the model has optional buffs: say which of them are chosen (buffs), "
                "because the arrangements of the hands are valued under them"
            )
        buffs = ()
    return _place(milp, groups, buffs)[0]


def _check_rearranged(
    before: Mapping[str, Sequence[ItemVec]], after: Mapping[str, Sequence[ItemVec]], value_before: Fraction | None,
    value_after: Fraction,
) -> None:
    """Only the arrangement may change: the same items (copies counted) and, when the rule compared values, the same exact
    value. ``value_before`` is None when the hands were left as they were, and nothing could have changed the value."""
    was = Counter(_name(item) for placed in before.values() for item in placed)
    now = Counter(_name(item) for placed in after.values() for item in placed)
    if was != now:
        raise PlacementError(
            f"the canonical placement changed the items: {sorted(was.elements())} became {sorted(now.elements())}"
        )
    if value_before is not None and value_after != value_before:
        raise PlacementError(
            f"the canonical placement changed the value of the kit from {value_before} to {value_after}"
        )


def tie_ranks(milp: Milp) -> dict[int, int]:
    """The rank of every column the tie stage prices: an item column costs its item's place in the sorted pool
    (counted from 1), a buff column costs the place of its id among the optional buffs after all the items."""
    ordered = sorted(milp.items, key=lambda item: (item.key, item.tier))
    position = {(item.key, item.tier): n + 1 for n, item in enumerate(ordered)}
    ranks = {col: position[(item.key, item.tier)] for col, _, item in milp.item_cols}
    base = len(milp.items)
    place = {bid: base + n + 1 for n, bid in enumerate(sorted(milp.buff_cols.values()))}
    ranks.update({col: place[bid] for col, bid in milp.buff_cols.items()})
    return ranks


def _solution(milp: Milp, raw: RawResult) -> Solution:
    if raw.x is None:
        return Solution(raw.status, None, None, (), raw.gap, raw.nodes)
    decoded = milp.decode(raw.x)
    groups, solver_value = _place(milp, decoded.groups, decoded.buffs)
    kit = canonical_kit(groups)
    exact = _evaluator(milp, decoded.buffs)(kit)
    _check_rearranged(decoded.groups, groups, solver_value, exact.F)
    value = float(exact.F)
    model_value = milp.const + float(np.dot(milp.c, raw.x))
    _check_exactness(model_value, value)
    return Solution(raw.status, value, kit, decoded.buffs, raw.gap, raw.nodes, model_value, exact)


def _check_exactness(model_value: float, value: float) -> None:
    """Refuse a model that overstates what its own kit is worth (see the module docstring)."""
    if model_value > value + EXACTNESS_TOLERANCE * max(1.0, abs(value)):
        raise ExactnessError(
            f"the model's objective {model_value!r} overstates the evaluator's value {value!r} of its kit by more "
            f"than {EXACTNESS_TOLERANCE:g} relative"
        )


def _first_stage(milp: Milp, highs_options: Mapping[str, Any] | None, cutoff: float | None) -> Mapping[str, Any] | None:
    """The HiGHS options of the first stage: ``highs_options``, and with a ``cutoff`` (a value of the model, the constant included, that a
    kit must reach: HiGHS stops a search that cannot) its ``objective_bound``. The program is maximized and HiGHS minimizes the
    negative, so the bound is the negative of what the objective without the constant must reach."""
    if cutoff is None:
        return highs_options
    return {**(highs_options or {}), "objective_bound": -(cutoff - milp.const)}


def solve(
    milp: Milp, time_limit: float | None = None, highs_options: Mapping[str, Any] | None = None, *, cutoff: float | None = None
) -> Solution:
    """Solve ``milp`` and value the answer exactly (see the module docstring). Raises :class:`ExactnessError`.

    ``highs_options`` replaces single HiGHS options for this call (the presolve gate sets ``presolve``); the project's
    determinism options (:data:`trioforge.solver._highs.OPTIONS`) hold when it is None."""
    return _solution(milp, solve_milp(milp, time_limit=time_limit, highs_options=_first_stage(milp, highs_options, cutoff)))


def solve_canonical(
    milp: Milp, time_limit: float | None = None, highs_options: Mapping[str, Any] | None = None, *, cutoff: float | None = None
) -> Solution:
    """:func:`solve`, then the tie stage: the least total rank among the kits as good as the best.

    ``time_limit`` is given to each of the two solves. If the first does not end optimal it is returned as it is. If
    the second does not end optimal, or its kit is not exactly as good as the first stage's by the oracle, the first
    answer is returned (``canonical`` false, ``tie_stage`` ``"kept-first"``) because its value is proven.
    ``highs_options`` is passed to both solves, as in :func:`solve`. ``cutoff`` is given to the first stage only: a kit worth less
    than it is not looked for. A search that finds none ends ``infeasible`` or ``optimal`` with some kit that is worth less than the
    cutoff (the solver may report one it came across): the answer is then "no kit of the cutoff", and the tie stage is not run.
    """
    found = solve_milp(milp, time_limit=time_limit, highs_options=_first_stage(milp, highs_options, cutoff))
    first = _solution(milp, found)
    if first.status != "optimal":
        return first
    if cutoff is not None and first.model_F is not None and first.model_F < cutoff:
        return first  # the search ended with no kit worth the cutoff (what it reports is not the level's best): nothing to separate
    best = first.model_F
    tolerance = TIE_TOLERANCE * max(1.0, abs(best))
    cost = np.zeros(milp.num_cols)
    for col, rank in tie_ranks(milp).items():
        cost[col] = rank
    live = np.flatnonzero(milp.c).astype(np.int32)  # the row F >= best - tolerance, over the columns that carry value
    start = np.append(milp.A.start, milp.A.start[-1] + len(live)).astype(np.int32)
    index = np.concatenate([milp.A.index, live]).astype(np.int32)
    value = np.concatenate([milp.A.value, milp.c[live]])
    row_lb = np.append(milp.row_lb, best - milp.const - tolerance)
    row_ub = np.append(milp.row_ub, np.inf)
    raw = run_arrays(
        cost, start, index, value, row_lb, row_ub, milp.col_lb, milp.col_ub, milp.integrality, maximize=False,
        time_limit=time_limit, warm_start=found.x, highs_options=highs_options,
    )
    if raw.status != "optimal" or raw.x is None:
        return dataclasses.replace(first, tie_stage="kept-first")
    second = _solution(milp, raw)  # raises only if the model overstates the kit; a worse kit is no error
    if second.breakdown.F != first.breakdown.F:  # exact: the band is a net for float noise, not a licence to lose value
        return dataclasses.replace(first, tie_stage="kept-first")
    nodes = None if first.nodes is None or raw.nodes is None else max(first.nodes, 0) + max(raw.nodes, 0)
    return dataclasses.replace(second, gap=first.gap, nodes=nodes, canonical=True, tie_stage="applied")
