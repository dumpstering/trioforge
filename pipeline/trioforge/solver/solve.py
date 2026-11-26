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

*The hands first.* Only the two hands (and, under the bow setup, the range place, where the bow that stands is scored and a bow that stands in an Any place is not) make
the place of an item matter to the value: the main hand carries the damage bonus
of the weapon index, the off hand its dual-wield factor and the shield bonus of the armor class. Everything said of the hands below holds for the range place of the bow
setup as well, which is filled after the off hand in the same order. Among the arrangements of
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

**The last stage: kits of the same value and the same total rank.** Two different kits can share a total rank (items
ranked 1 and 4 against 2 and 3, say), and a total of ranks cannot tell them apart. The solver's own path used to decide,
the same on every run of one engine but not the same in the other. Now one more stage settles it, and the answer is a
total order. Once the second stage has a kit of the least total rank ``R``, a program is solved that maximizes the value over the
kits that satisfy the rows ``total rank <= R`` and "the worn items (copies counted) and the chosen buffs are not those of the kit
found", with the cutoff of the first stage's kind at :data:`TIE_PROOF_TOLERANCE` under the best value (the objective that bounds a kit
best, and the narrow band: a tenth of the tie stage's, which is a net for float noise where this proof looks for kits of exactly the best
value; with the rank as the objective the same proof took some seven times the time of the tie stage). A kit of the band that ties on the rank
satisfies the rows and no other does; if there is one it is a member of the tie, and the same is asked again with that kit left
out too, until none is left (a program with no kit worth the cutoff is the proof that the tie has no more members, and it is the
common case: one solve more than before, which finds nothing). The answer is the member
that comes first in this order, on the canonical kits (:func:`canonical_kit`) of the members: **place by place** in the order of
the 22 places of :data:`~trioforge.model.items.SLOT_INSTANCES`, an item before an empty place and two items by ``(key, tier)``
(the key as text, the tier as a number), the first place that differs deciding; and when every place is alike (the same worn items
with other buffs), the chosen buff ids as sorted lists, the lower list first. A member must have the exact value of the second
stage's kit; a kit of the band worth exactly less is left out like any other kit that is not the best, and a kit worth more, or
of a lower rank, takes the place of the answer (the value is first, the rank second, the order of the kits last). The order is
over the kit and not over the path of any solver, so two engines that find the same members give the same answer
(:func:`kit_order` is the sort key). ``canonical`` is true when the proof ran to its end. A time limit that stops a solve of the
stage, or a tie of more than :data:`MAX_TIED_KITS` kits, ends it with the best kit it has and ``canonical`` false (``tie_stage``
is still ``"applied"``).
"""

from __future__ import annotations

import dataclasses
import itertools
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
    "MAX_TIED_KITS",
    "TIE_TOLERANCE",
    "ExactnessError",
    "PlacementError",
    "Solution",
    "canonical_kit",
    "kit_order",
    "place_canonically",
    "revalue",
    "solve",
    "second_is_taken",
    "solve_canonical",
    "tie_ranks",
]

#: the most the model's own value of a kit may differ from the evaluator's, relative (production; tests demand 1e-9)
EXACTNESS_TOLERANCE = 1e-6
#: the second stage keeps every kit within this relative distance of the best value
TIE_TOLERANCE = 1e-7
#: the most kits of one tie (the same exact value, the same total rank) the last stage will set apart one by one; a tie of more is not settled and the answer is not called canonical (a
#: tie of two or three is what the data has; a run of this many is a model that has gone wrong, and the precompute refuses its kit)
MAX_TIED_KITS = 200
#: the last stage looks for kits of exactly the best value, and asks the solver for none worth less than the best by more than this relative distance (a tenth of the band of the tie stage, a hundred times
#: the solver's own tolerance): the model's value of a kit that ties is the exact value to the solver's accuracy, and a narrower band is a far cheaper proof than the band of the tie stage
TIE_PROOF_TOLERANCE = 1e-8


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
    branch-and-bound node count. ``canonical`` is true when the tie stage ran to its end, the last stage that settles kits of the same
    value and the same total rank included (see the module docstring). For a ``time_limit`` solution
    ``F`` is the oracle's exact value of the incumbent's kit (a lower bound of the optimum), ``model_F`` the model's
    own value of the incumbent (never above ``F``, and often below it) and ``gap`` HiGHS's gap of that incumbent, which
    can only overstate the gap of ``F``. ``tie_stage`` is None for a plain :func:`solve` and for a
    :func:`solve_canonical` whose first stage did not end optimal; ``"applied"`` when the tie stage ran and its kit is
    the answer (``canonical`` false when the last stage did not finish: the kit is then the best it had); ``"kept-first"`` when the tie stage's kit was not accepted (it was worth less than the first stage's, by
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


def _arranged(milp: Milp) -> tuple[str, ...]:
    """The groups whose occupant the value depends on, and so the places the canonical rule arranges: the two hands, and under the bow setup the range place too (the
    bow that stands there is scored, and a bow that stands in an Any place is not)."""
    return (*HAND_GROUPS, "RANGE") if milp.setup == "ranged" else HAND_GROUPS


def _columns(milp: Milp) -> tuple[dict[tuple[str, int], list[str]], dict[str, set[tuple[str, int]]]]:
    """The places ``milp`` has a column for: ``{item: [groups outside the hands, in the slot order]}`` and, for each hand
    (and the range place under the bow setup, see :func:`_arranged`), the set of items that have a column there. The columns are what the builder allows: the slots an item lists,
    the Any rule, the weapon setup (``allowed_in_hand``), the class, deity and race rules."""
    arranged = _arranged(milp)
    outside: dict[tuple[str, int], list[str]] = {}
    in_hand: dict[str, set[tuple[str, int]]] = {hand: set() for hand in arranged}
    for _, group, item in milp.item_cols:
        if group in arranged:
            in_hand[group].add(_name(item))
        else:
            outside.setdefault(_name(item), []).append(group)
    for options in outside.values():
        options.sort(key=_GROUP_ORDER.__getitem__)
    return outside, in_hand


def _place_outside(
    items: Sequence[ItemVec], outside: Mapping[tuple[str, int], Sequence[str]], arranged: Sequence[str] = HAND_GROUPS
) -> dict[str, list[ItemVec]]:
    """The items that are not in a hand (or in the range place of the bow setup), each in the earliest group of the slot order that the model has a column for it in and
    that has a place left, provided every item after it can still be given a place; taken in the order of ``(key, tier)``."""
    movable = sorted(items, key=_name)
    options = [outside.get(_name(item), []) for item in movable]
    room = {group: size for group, size in SLOT_GROUPS if group not in arranged}
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
        return fm.evaluate(milp.profile, list(kit), totals, setup=milp.setup, haste_assumed=milp.haste_assumed, procs=milp.options.procs, **legacy)

    return value


def revalue(milp: Milp, solution: Solution, haste: int) -> Solution:
    """``solution`` with its kit valued again by the exact evaluator at the assumed haste ``haste`` (the weapon index at
    that haste) in place of the one ``milp`` assumed: the kit, the buffs and the places stay. ``F`` and ``breakdown`` are the
    new value; ``model_F`` stays what the model said. A solution with no kit is returned as it is."""
    if solution.kit is None:
        return solution
    totals = eval_buff_totals(milp.buffset.totals(solution.buffs)) if milp.buffset is not None else None
    legacy = {} if milp.options.legacy is None else {"legacy": milp.options.legacy}
    breakdown = fm.evaluate(milp.profile, list(solution.kit), totals, setup=milp.setup, haste_assumed=haste, procs=milp.options.procs, **legacy)
    return dataclasses.replace(solution, F=float(breakdown.F), breakdown=breakdown)


def _kit_of(rest: Sequence[ItemVec], chosen: Sequence[ItemVec | None], arranged: Sequence[str] = HAND_GROUPS) -> list[ItemVec | None]:
    """A kit with ``chosen`` in the arranged places (the hands, and the range place under the bow setup) and ``rest`` in the other places in any order (the evaluator reads
    only what stands in the arranged places from the place; the wrapper puts the others in the canonical order when it makes the kit)."""
    free = iter(rest)
    standing = dict(zip(arranged, chosen, strict=True))
    return [standing[place] if place in standing else next(free, None) for place in SLOT_INSTANCES]


def _place(
    milp: Milp, groups: Mapping[str, Sequence[ItemVec]], buffs: Sequence[int]
) -> tuple[dict[str, list[ItemVec]], Fraction | None]:
    """:func:`place_canonically` and, when it had to compare arrangements, the exact value of the solver's own (else None)."""
    arranged = _arranged(milp)
    for hand in arranged:
        if len(groups.get(hand, ())) > 1:
            raise ValueError(f"{len(groups[hand])} items in {hand}, which has one place")
    outside, in_hand = _columns(milp)
    worn = [item for placed in groups.values() for item in placed]
    solver = tuple(next(iter(groups.get(place, ())), None) for place in arranged)
    copies = Counter(_name(item) for item in worn)
    by_name = {_name(item): item for item in worn}
    stand = {group: size for group, size in SLOT_GROUPS if group not in arranged}

    def rest_without(*taken: ItemVec | None) -> list[ItemVec]:
        left = copies - Counter(_name(item) for item in taken if item is not None)
        return [by_name[name] for name in sorted(left.elements())]

    def legal(choice: Sequence[ItemVec | None]) -> list[ItemVec] | None:
        """What is left for the places outside the arranged ones when ``choice`` stands in them, or None when that is not an
        arrangement the builder allows: an item stands in two places only if it is worn twice, a two-hander leaves the off hand
        empty, and everything else must be able to stand outside the arranged places."""
        names = Counter(_name(item) for item in choice if item is not None)
        if any(names[name] > copies[name] for name in names):
            return None
        main, off = choice[0], choice[1]
        if main is not None and off is not None and main.weapon is not None and main.weapon.two_handed:
            return None
        rest = rest_without(*choice)
        return rest if _all_placed([outside.get(_name(item), []) for item in rest], stand) else None

    options = [[by_name[name] for name in sorted(by_name) if name in in_hand[place]] + [None] for place in arranged]
    here = tuple(_hand_order(item) for item in solver)
    value = _evaluator(milp, buffs)
    solver_value: Fraction | None = None
    chosen = solver
    for choice in itertools.product(*options):  # in the order of the places, each filled before it is left empty, by the smaller (key, tier)
        if tuple(_hand_order(item) for item in choice) >= here:
            break  # the solver's own arrangement is reached: none before it was as good, and it stands
        rest = legal(choice)
        if rest is None:
            continue
        if solver_value is None:
            solver_value = value(_kit_of(rest_without(*solver), solver, arranged)).F
        if value(_kit_of(rest, choice, arranged)).F == solver_value:
            chosen = choice
            break
    placed = _place_outside(rest_without(*chosen), outside, arranged)
    for place, item in zip(arranged, chosen, strict=True):
        if item is not None:
            placed[place] = [item]
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


def second_is_taken(first: Any, second: Any) -> bool:
    """Whether the tie stage's kit replaces the first stage's: its exact value is not less (the band of the tie stage is a net for float noise, not a licence to lose value; a kit that is worth
    more than a first stage that stopped inside its gap is the better answer)."""
    return not second < first


def solve_canonical(
    milp: Milp, time_limit: float | None = None, highs_options: Mapping[str, Any] | None = None, *, cutoff: float | None = None
) -> Solution:
    """:func:`solve`, then the tie stage: the least total rank among the kits as good as the best.

    ``time_limit`` is given to each of the two solves. If the first does not end optimal it is returned as it is. If
    the second does not end optimal, or its kit is worth less than the first stage's by the oracle (:func:`second_is_taken`: a kit that is
    exactly as good or better is applied, and the browser's ``secondIsTaken`` is the same rule), the first answer is returned (``canonical``
    false, ``tie_stage`` ``"kept-first"``) because its value is proven.
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
    if not second_is_taken(first.breakdown.F, second.breakdown.F):
        return dataclasses.replace(first, tie_stage="kept-first")
    nodes = None if first.nodes is None or raw.nodes is None else max(first.nodes, 0) + max(raw.nodes, 0)
    settled, complete, more = _settle_ties(
        milp, cost, (start, index, value, row_lb, row_ub), second, raw, time_limit, highs_options, first.model_F
    )
    if nodes is not None:
        nodes += more
    return dataclasses.replace(settled, gap=first.gap, nodes=nodes, canonical=complete, tie_stage="applied")


def kit_order(kit: Sequence[ItemVec | None], buffs: Sequence[int]) -> tuple[Any, ...]:
    """The sort key of the order of the kits that the last stage settles (see the module docstring): the 22 places in turn (an item is ``(0, key, tier)``, an empty place
    ``(1, "", 0)``, so that it comes after every item), then the chosen buff ids as a list."""
    return tuple((0, item.key, item.tier) if item is not None else (1, "", 0) for item in kit), tuple(buffs)


@dataclass
class _Program:
    """The arrays of the second stage as lists, so that rows and binary columns can be added (rows in CSR form), and the program made again from them for each solve of the last stage."""

    cost: list[float]
    col_lb: list[float]
    col_ub: list[float]
    integrality: list[int]
    start: list[int]
    index: list[int]
    value: list[float]
    row_lb: list[float]
    row_ub: list[float]

    def add_binary(self) -> int:
        self.cost.append(0.0)
        self.col_lb.append(0.0)
        self.col_ub.append(1.0)
        self.integrality.append(1)
        return len(self.cost) - 1

    def add_row(self, terms: Sequence[tuple[int, float]], lb: float, ub: float) -> int:
        for col, coefficient in terms:
            self.index.append(col)
            self.value.append(coefficient)
        self.start.append(len(self.index))
        self.row_lb.append(lb)
        self.row_ub.append(ub)
        return len(self.row_lb) - 1

    def arrays(self) -> tuple[np.ndarray, ...]:
        return (
            np.asarray(self.cost, dtype=np.float64), np.asarray(self.start, dtype=np.int32), np.asarray(self.index, dtype=np.int32),
            np.asarray(self.value, dtype=np.float64), np.asarray(self.row_lb, dtype=np.float64), np.asarray(self.row_ub, dtype=np.float64),
            np.asarray(self.col_lb, dtype=np.float64), np.asarray(self.col_ub, dtype=np.float64), np.asarray(self.integrality, dtype=np.int32),
        )  # fmt: skip


def _exclude_kit(milp: Milp, program: _Program, by_item: Mapping[tuple[str, int], list[int]], x: np.ndarray) -> None:
    """Add to ``program`` the row that says "not the worn items (copies counted) and the chosen buffs of ``x``". An item's copies are the sum of its columns, ``N_i``; ``more_i``
    may be 1 only if ``N_i >= N*_i + 1`` and ``fewer_i`` only if ``N_i <= N*_i - 1`` (a binary each, with a row each), a column of an item the kit does not wear counts for itself, and
    a buff counts when it is on and the kit has it off, or off and the kit has it on. The row is the sum of all of these, at least 1: a kit that differs in an item, a copy or a
    buff makes one of them 1, and the kit of ``x`` (in any of its places) makes none. Where the items stand is not a difference: the kit is the canonical one."""
    differs: list[tuple[int, float]] = []
    on_already = 0
    for cols in by_item.values():
        worn = round(sum(float(x[col]) for col in cols))
        if worn == 0:
            differs.extend((col, 1.0) for col in cols)
            continue
        reach = round(sum(program.col_ub[col] for col in cols))
        own = [(col, 1.0) for col in cols]
        if reach > worn:
            more = program.add_binary()
            program.add_row([*own, (more, -(worn + 1.0))], 0.0, np.inf)
            differs.append((more, 1.0))
        fewer = program.add_binary()
        program.add_row([*own, (fewer, reach - worn + 1.0)], -np.inf, float(reach))
        differs.append((fewer, 1.0))
    for col in milp.buff_cols:
        if round(float(x[col])) == 1:
            differs.append((col, -1.0))  # (1 - y): 1 when the buff is off
            on_already += 1
        else:
            differs.append((col, 1.0))
    program.add_row(differs, 1.0 - on_already, np.inf)


def _settle_ties(
    milp: Milp, cost: np.ndarray, rows: tuple[Any, ...], best: Solution, raw: RawResult, time_limit: float | None, highs_options: Mapping[str, Any] | None, first_model_F: float
) -> tuple[Solution, bool, int]:
    """The last stage (see the module docstring): ``best`` is the kit of the second stage and ``raw`` its raw result. Returns the answer, whether the proof that nothing
    more ties ran to its end, and the nodes of the solves of the stage."""
    start, index, value, row_lb, row_ub = rows
    n = milp.num_cols
    by_item: dict[tuple[str, int], list[int]] = {}
    for col, _, item in milp.item_cols:
        by_item.setdefault((item.key, item.tier), []).append(col)
    if not by_item and not milp.buff_cols:
        return best, True, 0  # (no column carries a rank: one kit)
    program = _Program(
        cost.tolist(), milp.col_lb.tolist(), milp.col_ub.tolist(), [int(flag) for flag in milp.integrality],
        start.tolist(), index.tolist(), value.tolist(), row_lb.tolist(), row_ub.tolist(),
    )  # fmt: skip
    ranked = np.flatnonzero(cost)
    # the program of the stage maximizes the value (the objective that bounds a kit best, as the first stage does) over the kits of the band that are not those found, with the cutoff of the
    # first stage's kind: a search that finds none worth the cutoff ends infeasible, or optimal with a kit worth less than it (the solver may report one it came across)
    program.cost[:n] = (-milp.c).tolist()
    floor = float(first_model_F) - TIE_PROOF_TOLERANCE * max(1.0, abs(float(first_model_F)))  # the lowest value (the constant included) of a kit that can tie
    program.row_lb[milp.num_rows] = floor - milp.const  # (the row of the band that the second stage added, narrowed)
    options = {**(highs_options or {}), "objective_bound": -(floor - milp.const)}
    rank_row = program.add_row([(int(col), float(cost[col])) for col in ranked], -np.inf, np.inf)  # total rank <= R, with R set before each solve

    def rank_of(x: np.ndarray) -> int:
        return round(float(np.dot(cost[:n], x[:n])))

    best_rank = rank_of(raw.x)
    best_key = (-best.breakdown.F, best_rank, kit_order(best.kit, best.buffs))
    _exclude_kit(milp, program, by_item, raw.x)
    nodes = 0
    for _ in range(MAX_TIED_KITS):
        program.row_ub[rank_row] = float(best_rank)
        probe = run_arrays(*program.arrays(), maximize=False, time_limit=time_limit, warm_start=None, highs_options=options)
        nodes += max(probe.nodes or 0, 0)
        if probe.status == "infeasible":
            return best, True, nodes
        if probe.status != "optimal" or probe.x is None:
            return best, False, nodes
        if milp.value(probe.x[:n]) < floor:
            return best, True, nodes  # (the kit the solver came across is worth less than the cutoff: none of the band is left)
        found = _solution(milp, dataclasses.replace(probe, x=probe.x[:n]))
        rank = rank_of(probe.x)
        key = (-found.breakdown.F, rank, kit_order(found.kit, found.buffs))
        if key < best_key:
            best, best_key, best_rank = found, key, rank
        _exclude_kit(milp, program, by_item, probe.x)
    return best, False, nodes
