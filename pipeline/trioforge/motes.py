"""The Python reference of the mote order: in which order to spend void-touched motes on a kit.

A void-touched mote raises any one item by one whole tier, at any tier, up to the top tier (+10), with no limit on the motes an item takes (``tier.void_mote`` in
``rules/rules.json``). The browser reproduces :func:`mote_order`, and a recorded fixture holds it to this module's output (``fixtures/site/mote-orders.json``). Values are
exact (:class:`fractions.Fraction` from the evaluator), never the solver's.

**The kit is fixed.** The kit is the worn items, one for each place that is filled, each at its own tier (the tiers may differ). The same items stay in the same places;
only their tiers change, so a mote never swaps an item. Two worn copies of one item are two separate items.

**A step is a run.** A gain can sit more than one mote away on one item: a weapon whose damage rises only every second tier, a haste that counts only once it passes the best worn
one. So for each worn item below +10 its **run** is the smallest ``k`` from 1 such that raising it ``k`` tiers (the rest of the kit as it stands) changes the kit value by more than
nothing, and its **rate** is that gain divided by ``k``, exactly; an item that gains at no ``k`` up to +10 has no run. Only an item whose one-tier gain is not above nothing is looked at
past ``k = 1``, so the common case costs one evaluation for each item. The kit is valued as the Upgrade tab values it everywhere
(:func:`trioforge.model.formulas.evaluate_truthful`: the weapons are paid the haste the kit counts; the profile's role, race and weights, the weapon setup, and the optional buffs the kit was
made with, all held fixed). A step takes the run with the highest rate; of equal rates the shorter run, then the place that comes first in the kit's order (the order of
:data:`trioforge.model.items.SLOT_INSTANCES`, the page's own), and applies the whole run: one line of the list, ``k`` motes spent. With a limit of motes a run longer than the motes left
is not eligible. In this model a one-tier raise never lowers the value (every stat of an item only rises with its tier and its weight only falls, and the value falls with neither a
stat nor a lighter kit), so every gain is at least nothing; the definition says "more than nothing" all the same, and a loss on the way to a gain is passed over.

**The end.** The order ends when every item is at +10 (``"top"``: there is nothing to spend a mote on; an empty kit ends so too), when the motes asked for are spent or no eligible run fits
in what is left (``"motes"``: ``next_run`` is the length of the run that did not fit, or ``None`` when the limit was reached), or when no item has a run (``"no-gain"``: a stat past its
cap, a haste that cannot pass the best worn one: nothing that is left gains anything, at any length). ``left`` is how many more motes could still be spent (the tiers left under +10 over
every item): after ``"no-gain"`` that many motes are possible and none of them gains anything. ``spent`` is the motes spent, which is more than the number of steps when a run is longer
than one.

**It is greedy.** Each step is the best run after the steps before it, by the gain for each mote. That is not a proven best plan for any number of motes, and the page says so.

**The stats that moved** (:attr:`MoteStep.moved`): the kit totals the evaluator counts (:data:`MOVED_ORDER`: the sheet armor class, the HP, mana and endurance pools, the
seven attributes with the gear, the buffs and the race in them, the haste counted, the attack, the five resists as they count against the cap and the three regens) that
changed by the step, each with its exact change, in that order; and ``DMG``, the weapon damage of the item itself, when the item is a weapon.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from trioforge.model import formulas as fm
from trioforge.model.items import SLOT_INSTANCES, ItemVec, at_tier
from trioforge.model.tiers import MAX_TIER
from trioforge.solver.model import eval_buff_totals

__all__ = ["MOVED_ORDER", "MoteOrder", "MoteStep", "mote_order"]

#: the stats a step may move, in the order they are listed: the totals of the evaluator, then the damage of a weapon
MOVED_ORDER: tuple[str, ...] = (
    "AC", "HP", "MANA", "END", *fm.ATTRIBUTES, "HASTE", "ATK", *fm.SCHOOLS, "HPREG", "MANAREG", "ENDREG", "DMG",
)  # fmt: skip
ENDINGS = ("top", "motes", "no-gain")


@dataclass(frozen=True)
class MoteStep:
    """One run of motes on one item: ``index`` (the line, from 1), the ``place`` of the kit it goes to (an index into ``SLOT_INSTANCES``), the item's ``key`` and the tiers it goes from and to
    (``motes`` of them, one tier each), the exact ``gain`` in kit value of the whole run, the exact value ``F`` of the kit after it, the ``moved`` stats (``(name, change)`` pairs of
    :data:`MOVED_ORDER`, none that changed by nothing) and ``spent``, the motes spent up to and with this step."""

    index: int
    place: int
    key: str
    from_tier: int
    to_tier: int
    gain: Fraction
    F: Fraction
    moved: tuple[tuple[str, Fraction], ...]
    spent: int

    @property
    def motes(self) -> int:
        """How many motes the step takes: the length of its run (``to_tier - from_tier``)."""
        return self.to_tier - self.from_tier


@dataclass(frozen=True)
class MoteOrder:
    """The order: the exact value of the kit before any mote (``start``), the ``steps``, why it ended (``ending``, one of :data:`ENDINGS`), how many more motes could be spent (``left``), how
    many were (``spent``) and, for an order that ended with motes left that no eligible run fits, how long the run that did not fit is (``next_run``; ``None`` otherwise)."""

    start: Fraction
    steps: tuple[MoteStep, ...]
    ending: str
    left: int
    spent: int = 0
    next_run: int | None = None


def _totals(totals: Mapping[str, Any]) -> dict[str, Fraction]:
    """The totals the order lists (everything of :data:`MOVED_ORDER` but the damage of a weapon), as exact numbers."""
    found = {
        "AC": totals["sheet"]["total"], "HP": totals["pools"]["HP"], "MANA": totals["pools"]["MANA"], "END": totals["pools"]["END"],
        "HASTE": totals["haste"]["counted"], "ATK": totals["atk"],
    }  # fmt: skip
    for name in fm.ATTRIBUTES:
        found[name] = totals["attributes"][name]
    for school in fm.SCHOOLS:
        found[school] = totals["resists"][school]["counted"]
    for name in ("HPREG", "MANAREG", "ENDREG"):
        found[name] = totals["regen"][name]["counted"]
    return {name: fm.fr(amount) for name, amount in found.items()}


def _moved(before: Mapping[str, Any], after: Mapping[str, Any], old: ItemVec, new: ItemVec) -> tuple[tuple[str, Fraction], ...]:
    was, now = _totals(before), _totals(after)
    moved = [(name, now[name] - was[name]) for name in MOVED_ORDER if name in now and now[name] != was[name]]
    if old.weapon is not None and new.weapon is not None and new.weapon.dmg != old.weapon.dmg:
        moved.append(("DMG", Fraction(new.weapon.dmg - old.weapon.dmg)))
    return tuple(moved)


def mote_order(
    profile: Any, kit: Sequence[ItemVec | None], records: Mapping[str, Mapping[str, Any]], rules: Any, setup: str | None, buffset: Any = None,
    buffs: Iterable[int] = (), motes: int | None = None, *, weapon_pct: int | None = None,
) -> MoteOrder:
    """The order in which to spend ``motes`` motes (all that can be spent, when ``None``) on ``kit``, a list of 22 items or ``None`` (the places of
    :data:`trioforge.model.items.SLOT_INSTANCES`), each at its own tier. ``records`` are the catalog records by item key (an item at another tier is made from its record by
    :func:`trioforge.model.items.at_tier`, under ``rules`` and the weapon rate ``weapon_pct``). ``profile``, ``setup`` and ``buffset`` are the evaluator's, and ``buffs`` the
    ids of the optional buffs of ``buffset`` that the kit is valued with (none by default); without a ``buffset`` the kit is valued under the profile's own buffs.

    Raises ``ValueError`` for a kit that is not 22 places, an item that has no record, a ``motes`` that is not ``None`` or a whole number of at least 0, and ``buffs`` with no
    ``buffset`` to choose them from."""
    if motes is not None and (type(motes) is not int or motes < 0):
        raise ValueError(f"motes is None or a whole number of at least 0, not {motes!r}")
    slots = list(kit)
    if len(slots) != len(SLOT_INSTANCES):
        raise ValueError(f"a kit has {len(SLOT_INSTANCES)} places, not {len(slots)}")
    for item in slots:
        if item is not None and item.key not in records:
            raise ValueError(f"no record for item {item.key}")
    chosen = tuple(buffs)
    if chosen and buffset is None:
        raise ValueError("buffs are chosen from a buffset: none was given")
    totals = eval_buff_totals(buffset.totals(chosen)) if buffset is not None else None
    p = fm.compile_profile(profile)

    def value(trial: list[ItemVec | None]) -> fm.Breakdown:
        return fm.evaluate_truthful(p, trial, totals, setup=setup)

    current = value(slots)
    start = current.F
    steps: list[MoteStep] = []
    spent = 0
    next_run: int | None = None
    while True:
        left = sum(MAX_TIER - item.tier for item in slots if item is not None)
        if left == 0:
            ending = "top"
            break
        if motes is not None and spent >= motes:
            ending = "motes"
            break
        # the run of each worn item below the top: the fewest motes that gain something, and the gain
        best: tuple[Fraction, int, int, ItemVec, fm.Breakdown] | None = None  # (gain, k, place, raised, result) of the best run that fits
        best_any: tuple[Fraction, int] | None = None  # (gain, k) of the best run, fitting or not
        for place, item in enumerate(slots):
            if item is None or item.tier >= MAX_TIER:
                continue
            for k in range(1, MAX_TIER - item.tier + 1):
                raised = at_tier(records[item.key], item.tier + k, rules, weapon_pct=weapon_pct)
                trial = list(slots)
                trial[place] = raised
                result = value(trial)
                gain = result.F - current.F
                if gain > 0:
                    break
            else:
                continue  # (no run: not at any length)
            if best_any is None or _better(gain, k, best_any):  # (equal rates, equal runs: the earlier place stays)
                best_any = (gain, k)
            if (motes is None or k <= motes - spent) and (best is None or _better(gain, k, best[:2])):
                best = (gain, k, place, raised, result)
        if best_any is None:
            ending = "no-gain"
            break
        if best is None:
            ending = "motes"
            next_run = best_any[1]
            break
        gain, k, place, raised, result = best
        old = slots[place]
        assert old is not None
        spent += k
        steps.append(MoteStep(len(steps) + 1, place, old.key, old.tier, raised.tier, gain, result.F, _moved(current.totals, result.totals, old, raised), spent))
        slots[place] = raised
        current = result
    return MoteOrder(start, tuple(steps), ending, left, spent, next_run)


def _better(gain: Fraction, k: int, than: tuple[Fraction, int]) -> bool:
    """Whether a run of ``k`` motes for ``gain`` beats ``than`` (its gain and length): the higher gain for each mote, of equal rates the shorter run."""
    rate, other = gain / k, than[0] / than[1]
    return rate > other or (rate == other and k < than[1])
