"""The Python reference of the Upgrade tab: Equip now, the farm path, Every slot and the best sets.

The browser reproduces every function here, and a parity test holds it to this module's output. They all work from the
**owned set** (``{ItemVec: count}``: the items the visitor owns, each at the tier of the dump) and the **candidates** (a list
of ``ItemVec``: what could be acquired, each at the tier of the tier mode, see :mod:`trioforge.model.tiers`), under one
profile, weapon setup and buff set. Values are exact (:class:`fractions.Fraction` from the evaluator), never the solver's.

What an addition is
===================

An addition is **one more copy** of a candidate, acquired and worn at the candidate's tier (what it costs to bring it there
is :func:`trioforge.model.tiers.cost_to_reach`; the choice of the addition does not depend on that cost). :func:`classify`
tells three kinds from what is owned:

* ``copy``: the candidate is owned at its tier. One more copy may be worn above the count (a Lore copy adds nothing, and a
  Lore candidate that is owned is left out);
* ``upgrade``: the visitor owns the same key at a lower tier. The candidate is an upgrade of one copy, the highest tier
  below it (the cheapest merge): that copy becomes the candidate, so the key has no more copies than before;
* ``new``: any other candidate, including one below every owned tier of its key (another copy, at its tier).

The owned counts after an addition: a copy or a new item adds 1 to its ident; an upgrade takes 1 from the source's ident and
adds 1 to the target's. This is the whole of the semantics, and the builder's options (``owned_caps``, ``new_keys``,
``max_new``, ``upgrades``) express it as rows (see :mod:`trioforge.solver.model`).

**A set of k additions** (:func:`best_sets`) is any k additions in any order, each classified against what the ones before it
left owned, as a step of the path is. So the first k steps of the path are always one of the sets, and a set may upgrade an
owned copy and then add copies of the upgrade: the upgraded item is owned by then, so each further copy of it is a ``copy``,
one addition each. Only the first copy of an upgrade's target is made from the owned source; making two from two copies of the
source would cost as many additions as one upgrade and one copy and leave fewer of the source, so the builder has no such
option. Each candidate is classified against the owned set the session starts with, and the tier modes offer one candidate
per key; two candidates of one key (say two tiers above an owned copy) would not give a set every order a path has, because
a later one would stay an upgrade of the copy that an earlier one used.

The functions
=============

* :func:`equip_now`: the best kit from the owned items alone, each worn at most as often as it is owned.
* :func:`farm_path`: step 1 is the exact best single addition (the best kit when exactly one addition may be made); each
  later step is the exact best single addition after the steps before it, the step's item having joined the owned set as the
  kind above says. The path ends after ``steps`` steps or when no addition improves the value: there is never a step with no
  gain. Of equal additions the canonical solve decides, as everywhere (the kit of the smaller total rank of ``(key, tier)``).
  The label the page gives it: "Each step is the single best addition after the steps before it".
* :func:`best_sets`: the best kit when up to ``k`` additions may be made at once (sets, not a path: the best 2 can be worth
  more than the first two steps, and never less, with one candidate per key, as the tier modes give).
* :func:`every_slot`: for each of the 22 places, the exact gain of swapping one item in with the rest of the kit held fixed
  ("Swap only this slot"). The items on offer are the candidates and the items the visitor owns, and the copies are counted:
  a candidate has no limit (the swap means getting another copy), while an owned item that is not a candidate is a swap only
  while the visitor owns more of it than the kit wears in its other places (see :func:`every_slot`). A swap that cannot be made
  without moving another item (a two-hander over a worn off hand) is not offered.

**The weapon index is taken at the haste the kit counts.** Every solve is the truthful one of
:func:`trioforge.solver.haste.solve_scenario`: the kit is valued at the spell haste it takes and the worn haste it wears, and
the optimum is the best of those values, so the value of a kit is a function of the kit alone and never changes between Equip
now and a step: a step's gain is never a revaluation of the kit it started from. Every slot values each swap the same way, at
the haste the swapped kit counts (a haste item swapped in or out changes what the weapons are worth). Pass the caller's
``options`` with ``haste_assumed`` set to fix one haste for the whole session instead (:func:`session_haste` then returns
it, and every function values every kit at it, as before).

**Pruning** (:func:`trioforge.solver.prune.prune`, owned-aware): each step prunes its own pool, because what is owned and
which candidates are upgrades changes from step to step. Owned items are never pruned. It changes no value (``prune_pool=False``
turns it off, for the tests that show so).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any

from trioforge.classes import CLASS_CODES
from trioforge.model import formulas as fm
from trioforge.model import weapons as wp
from trioforge.model.buffs import BuffSet
from trioforge.model.items import SLOT_GROUPS, SLOT_INSTANCES, ItemVec, at_tier
from trioforge.model.tiers import arrival_tier, cost_to_reach, tier_for_mode
from trioforge.solver.haste import solve_scenario
from trioforge.solver.model import BuildOptions, eval_buff_totals, ident
from trioforge.solver.prune import prune
from trioforge.solver.solve import Solution, solve, solve_canonical

__all__ = [
    "Acquisition",
    "BestSet",
    "SlotRow",
    "Step",
    "Swap",
    "arrival_tier",
    "best_sets",
    "classify",
    "cost_to_reach",
    "equip_now",
    "every_slot",
    "farm_path",
    "scored_candidates",
    "session_haste",
    "tier_for_mode",
]

KINDS = ("new", "copy", "upgrade")
WEARABLE_SLOTS = frozenset(name for name, _ in SLOT_GROUPS)  # the groups an item can list (Any too)
HANDS = ("PRIMARY", "SECONDARY")
SECONDARY_INDEX = SLOT_INSTANCES.index("SECONDARY")
PRIMARY_INDEX = SLOT_INSTANCES.index("PRIMARY")


# ---- the records -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Acquisition:
    """One thing to acquire: ``item`` (at the tier it is brought to), its ``kind`` and, for an ``upgrade``, the tier
    (``source_tier``) of the owned copy it is made from. The cost of reaching the tier is
    ``cost_to_reach(record, source_tier if upgrade else arrival, item.tier, D)``. In a set, every wear of an upgrade's target
    after the first is a ``copy`` of the target."""

    item: ItemVec
    kind: str
    source_tier: int | None


@dataclass(frozen=True)
class Step:
    """One step of the farm path: the addition, the value after it and the owned set after it.

    ``F`` is the exact value of ``solution.kit`` and ``gain`` is ``F`` minus the value before the step (an exact fraction, so
    the gains add up to the difference of the values). ``owned`` is the owned set after the step as sorted
    ``(ident, count)`` pairs and ``haste_assumed`` the haste the value of the step assumes (the haste its kit counts, or
    the one haste the options fix)."""

    index: int
    item: ItemVec
    kind: str
    source_tier: int | None
    F: Fraction
    gain: Fraction
    haste_assumed: int
    owned: tuple[tuple[str, int], ...]
    solution: Solution


@dataclass(frozen=True)
class BestSet:
    """The best kit when up to ``k`` additions are made at once: what to acquire (``acquisitions``, empty when nothing
    improves the value), the exact value ``F`` and ``gain`` over Equip now, and the kit (``solution``)."""

    k: int
    acquisitions: tuple[Acquisition, ...]
    F: Fraction
    gain: Fraction
    haste_assumed: int
    solution: Solution


@dataclass(frozen=True)
class Swap:
    """Swapping ``item`` into one place: ``delta`` is the exact change of the value (negative for a worse item)."""

    item: ItemVec
    delta: Fraction


@dataclass(frozen=True)
class SlotRow:
    """One place of the kit: its name, its index in the kit, what is worn there and the best swaps (best gain first)."""

    place: str
    index: int
    current: ItemVec | None
    swaps: tuple[Swap, ...]


# ---- the owned set ----------------------------------------------------------------------------------------------------


class _Owned:
    """The owned items by ident, counts of at least 1 (a count of 0 is not owned)."""

    def __init__(self, owned: Mapping[ItemVec, int]) -> None:
        self.items: dict[str, ItemVec] = {}
        self.counts: dict[str, int] = {}
        for item, count in owned.items():
            if type(count) is not int or count < 0:
                raise ValueError(f"the count of {item.key} (tier {item.tier}) is a whole number of at least 0, not {count!r}")
            if count == 0:
                continue
            name = ident(item.key, item.tier)
            if name in self.items:
                raise ValueError(f"{item.key} at tier {item.tier} is owned twice (give one count)")
            self.items[name] = item
            self.counts[name] = count

    def tiers(self, key: str) -> list[int]:
        return [item.tier for name, item in self.items.items() if item.key == key]

    def classify(self, item: ItemVec) -> tuple[str, int | None]:
        if ident(item.key, item.tier) in self.counts:
            return "copy", None
        lower = [tier for tier in self.tiers(item.key) if tier < item.tier]
        if lower:
            return "upgrade", max(lower)
        return "new", None

    def add(self, item: ItemVec) -> None:
        name = ident(item.key, item.tier)
        self.items.setdefault(name, item)
        self.counts[name] = self.counts.get(name, 0) + 1

    def take(self, key: str, tier: int) -> None:
        name = ident(key, tier)
        self.counts[name] -= 1
        if self.counts[name] == 0:
            del self.counts[name], self.items[name]

    def snapshot(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self.counts.items()))


def classify(item: ItemVec, owned: Mapping[ItemVec, int]) -> tuple[str, int | None]:
    """``(kind, source tier)`` of a candidate against the owned set (see the module docstring): ``("copy", None)`` for one
    owned at its tier, ``("upgrade", tier)`` for the same key owned below it (the highest such tier), else ``("new", None)``.
    A Lore copy is a ``copy`` whose acquisition adds nothing; the functions leave it out."""
    return _Owned(owned).classify(item)


# ---- options, haste, eligibility ---------------------------------------------------------------------------------------


def _base_options(options: BuildOptions | None) -> BuildOptions:
    opts = BuildOptions() if options is None else options
    if opts.owned_caps or opts.new_keys or opts.max_new is not None or opts.upgrades:
        raise ValueError("owned_caps, new_keys, max_new and upgrades are set by the functions of this module, not by the caller")
    return opts


class _Usable:
    """Whether the profile can use an item at all: a class of the trio, a deity it admits, a race it allows. The builder's
    own test (``_Builder._collect``), written out again for the items that never reach a builder."""

    def __init__(self, profile: Any) -> None:
        pools = fm.compile_profile(profile).pools
        self.trio = frozenset(spec.cls for spec in pools["HP"])
        self.by_class = self.trio <= set(CLASS_CODES)
        self.deity = getattr(profile, "deity", None)
        self.race = getattr(profile, "race", None)

    def __call__(self, item: ItemVec) -> bool:
        if self.by_class and not (item.classes & self.trio):
            return False
        if item.deity is not None and (self.deity is None or self.deity not in item.deity):
            return False
        return self.race is None or item.races is None or self.race in item.races


def session_haste(
    profile: Any, owned: Mapping[ItemVec, int], candidates: Iterable[ItemVec], setup: str | None,
    buffset: BuffSet | None = None, options: BuildOptions | None = None,
) -> int | None:
    """The one haste percent the session values every kit at: ``options.haste_assumed`` when the caller gave one, else None,
    which means that every kit is valued at the haste it counts itself (see the module docstring). The other arguments are
    those of the functions of this module and decide nothing; they stay so that a caller need not change."""
    return (BuildOptions() if options is None else options).haste_assumed


def _haste_of(solution: Solution, options: BuildOptions) -> int:
    """The haste percent the value of a solution assumes: the one the options fix, else the haste its kit counts."""
    if options.haste_assumed is not None:
        return options.haste_assumed
    return int(solution.breakdown.totals["haste"]["counted"])


# ---- one model, one solve ------------------------------------------------------------------------------------------------


def _solve(
    profile: Any, pool: Sequence[ItemVec], setup: str | None, buffset: BuffSet | None, options: BuildOptions, canonical: bool
) -> Solution:
    """The truthful solve of one pool (see the module docstring): the best kit valued at the haste it counts, or at the fixed
    haste of ``options.haste_assumed``."""
    solution = solve_scenario(profile, pool, setup, buffset, options, solver=solve_canonical if canonical else solve).solution
    if solution.status != "optimal":
        raise RuntimeError(f"the solver ended with status {solution.status!r}, not optimal (no time limit is set)")
    return solution


def equip_now(
    profile: Any, owned: Mapping[ItemVec, int], setup: str | None, buffset: BuffSet | None = None,
    options: BuildOptions | None = None, *, canonical: bool = True,
) -> Solution:
    """The best kit from the owned items at their tiers, each worn at most as often as it is owned (the value is exact:
    ``solution.breakdown.F``). Without ``options.haste_assumed`` the kit is valued at the haste it counts. ``canonical=False`` skips the tie stage."""
    ledger = _Owned(owned)
    opts = replace(_base_options(options), owned_caps=dict(ledger.counts) or None)
    return _solve(profile, list(ledger.items.values()), setup, buffset, opts, canonical)


class _Plan:
    """The pool and the owned-item options for one Best-k solve, from the owned set and the candidates."""

    def __init__(self, ledger: _Owned, candidates: Sequence[ItemVec]) -> None:
        self.pool: dict[str, ItemVec] = dict(ledger.items)
        self.caps: dict[str, int] = dict(ledger.counts)
        self.news: set[str] = set()
        self.ups: dict[str, str] = {}
        self.kinds: dict[str, tuple[str, int | None]] = {}
        for cand in sorted(candidates, key=lambda c: (c.key, c.tier)):
            name = ident(cand.key, cand.tier)
            kind, source = ledger.classify(cand)
            if kind == "copy":
                if not cand.lore:  # a Lore copy adds nothing
                    self.news.add(name)
                    self.kinds[name] = (kind, source)
                continue
            self.pool[name] = cand
            self.kinds[name] = (kind, source)
            if kind == "upgrade":
                self.ups[name] = ident(cand.key, source)
            else:
                self.news.add(name)

    def options(self, base: BuildOptions, pool: Sequence[ItemVec], max_new: int) -> BuildOptions:
        """The options for ``pool`` (the whole pool of this solve or a pruned one): idents that are no longer in it are left out."""
        present = {ident(item.key, item.tier) for item in pool}
        ups = {t: s for t, s in self.ups.items() if t in present}
        return replace(
            base, owned_caps=dict(self.caps) or None, new_keys=frozenset(n for n in self.news if n in present),
            max_new=max_new, upgrades=ups or None,
        )


def _candidates(candidates: Iterable[ItemVec]) -> list[ItemVec]:
    out, seen = [], set()
    for cand in candidates:
        name = ident(cand.key, cand.tier)
        if name in seen:
            raise ValueError(f"{cand.key} at tier {cand.tier} is offered twice")
        seen.add(name)
        out.append(cand)
    return out


def _best_additions(
    profile: Any, ledger: _Owned, candidates: Sequence[ItemVec], setup: str | None, buffset: BuffSet | None,
    session: BuildOptions, max_new: int, canonical: bool, prune_pool: bool,
) -> tuple[Solution, _Plan] | None:
    """The best kit when up to ``max_new`` additions are made, and the plan it was solved under; None when the candidates
    offer no addition at all."""
    plan = _Plan(ledger, candidates)
    if not plan.news and not plan.ups:
        return None
    pool = list(plan.pool.values())
    if prune_pool:
        pool = prune(
            pool, profile, None, setup, buffset, plan.options(session, pool, max_new), owned=frozenset(plan.caps)
        )
    return _solve(profile, pool, setup, buffset, plan.options(session, pool, max_new), canonical), plan


def _acquired(solution: Solution, plan: _Plan, ledger: _Owned) -> list[Acquisition]:
    """What the kit acquires, in this order: the upgrade targets worn (the first wear of each is its ``upgrade``, followed by
    a ``copy`` of the target for every other wear), then the new items worn, then the wears above the count of the duplicates
    (the first wear of each of a duplicate's upgrade targets shares one of its copies). Each group is sorted by ident."""
    wears = Counter(ident(i.key, i.tier) for i in solution.kit if i is not None)
    found: list[Acquisition] = []
    for name in sorted(plan.ups):
        if wears[name]:
            item = plan.pool[name]
            found.append(Acquisition(item, *plan.kinds[name]))
            found += [Acquisition(item, "copy", None) for _ in range(wears[name] - 1)]
    for name in sorted(plan.news):
        if name not in ledger.counts:
            found += [Acquisition(plan.pool[name], *plan.kinds[name]) for _ in range(wears[name])]
    for name in sorted(plan.news):
        if name in ledger.counts:
            shared = wears[name] + sum(1 for t, source in plan.ups.items() if source == name and wears[t])
            item = plan.pool.get(name) or ledger.items[name]
            found += [Acquisition(item, *plan.kinds[name]) for _ in range(max(0, shared - ledger.counts[name]))]
    return found


def _join(ledger: _Owned, found: Acquisition) -> None:
    """The owned set after an acquisition (see the module docstring)."""
    if found.kind == "upgrade":
        ledger.take(found.item.key, found.source_tier)
    ledger.add(found.item)


# ---- the farm path ------------------------------------------------------------------------------------------------------


def farm_path(
    profile: Any, owned: Mapping[ItemVec, int], candidates: Iterable[ItemVec], setup: str | None,
    buffset: BuffSet | None = None, steps: int = 8, options: BuildOptions | None = None, *, canonical: bool = True,
    prune_pool: bool = True,
) -> list[Step]:
    """The farm path: up to ``steps`` steps, each the exact best single addition after the steps before it (see the module
    docstring). Ends early when no addition improves the value. Raises ``ValueError`` for a bad count or step number, a
    candidate offered twice and owned-item options in ``options``."""
    if type(steps) is not int or steps < 0:
        raise ValueError(f"steps is a whole number of at least 0, not {steps!r}")
    ledger = _Owned(owned)
    offered = _candidates(candidates)
    base = _base_options(options)
    if steps == 0 or not offered:
        return []
    session = base
    before = equip_now(profile, owned, setup, buffset, session, canonical=canonical).breakdown.F
    path: list[Step] = []
    for number in range(1, steps + 1):
        found = _best_additions(profile, ledger, offered, setup, buffset, session, 1, canonical, prune_pool)
        if found is None:
            break
        solution, plan = found
        acquired = _acquired(solution, plan, ledger)
        gain = solution.breakdown.F - before
        if not acquired or gain <= 0:
            break
        if len(acquired) != 1:
            raise RuntimeError(f"step {number} acquires {len(acquired)} items, not one: the model admitted too much")
        _join(ledger, acquired[0])
        before = solution.breakdown.F
        path.append(Step(
            number, acquired[0].item, acquired[0].kind, acquired[0].source_tier, before, gain, _haste_of(solution, base),
            ledger.snapshot(), solution,
        ))
    return path


def best_sets(
    profile: Any, owned: Mapping[ItemVec, int], candidates: Iterable[ItemVec], k: int, setup: str | None = None,
    buffset: BuffSet | None = None, options: BuildOptions | None = None, *, canonical: bool = True,
    prune_pool: bool = True,
) -> BestSet:
    """The best kit when up to ``k`` additions (``k`` from 1) may be made at once: sets, not a path. The acquisitions are
    those the kit uses, in this order: the upgrades, each followed by the copies of its target the kit wears, then the new
    items, then the copies of owned items above their counts (each group sorted by ident); with none that improves the value
    there are none and the kit is Equip now's."""
    if type(k) is not int or k < 1:
        raise ValueError(f"k is a whole number of at least 1, not {k!r}")
    ledger = _Owned(owned)
    offered = _candidates(candidates)
    base = _base_options(options)
    session = base
    start = equip_now(profile, owned, setup, buffset, session, canonical=canonical)
    found = _best_additions(profile, ledger, offered, setup, buffset, session, k, canonical, prune_pool)
    if found is not None:
        solution, plan = found
        acquired = _acquired(solution, plan, ledger)
        if acquired and solution.breakdown.F > start.breakdown.F:
            gain = solution.breakdown.F - start.breakdown.F
            return BestSet(k, tuple(acquired), solution.breakdown.F, gain, _haste_of(solution, base), solution)
    return BestSet(k, (), start.breakdown.F, Fraction(0), _haste_of(start, base), start)


# ---- every slot -----------------------------------------------------------------------------------------------------------


def _fits_place(item: ItemVec, place: str, setup: str | None, any_rule: str) -> bool:
    """Whether ``item`` can stand in ``place`` under the setup and the Any rule (the builder's columns, written once more)."""
    if place == "ANY":
        return "ANY" in item.slots or (any_rule == "all" and bool(WEARABLE_SLOTS & item.slots))
    if place not in item.slots:
        return False
    return wp.allowed_in_hand(item, place.lower(), setup or "stick") if place in HANDS else True


def every_slot(
    profile: Any, kit: Solution | Sequence[ItemVec | None], candidates: Iterable[ItemVec], setup: str | None = None,
    buffset: BuffSet | None = None, options: BuildOptions | None = None, *, buffs: Iterable[int] | None = None,
    limit: int = 3, owned: Mapping[ItemVec, int] | None = None,
) -> list[SlotRow]:
    """For each of the 22 places, the ``limit`` best swaps: the exact change of the value when one item stands in that place
    and the rest of the kit stays as it is (the buffs too; the swapped kit is valued at the haste it counts). ``kit`` is the :class:`Solution` of
    :func:`equip_now` (its buffs are used) or a sequence of 22 items; ``buffs`` the ids of the chosen optional buffs for a
    sequence.

    **The items on offer, and their copies.** They are the ``candidates`` of the tier mode and the items the visitor owns
    (``owned``, ``{ItemVec: count}`` as everywhere in this module; none by default):

    * a candidate (an item that can be got at the tier of the mode) has no count limit: the swap means getting another copy of
      it, as an addition does. An ident that is both owned and a candidate counts as a candidate;
    * an owned item whose ident is not a candidate's is a swap for a place only while the visitor's owned count of that ident is
      greater than the copies the kit wears in its OTHER places, so that the kit after the swap wears it no more often than it is
      owned. One ring owned once and worn on Finger 1 is not a swap for Finger 2; with a second copy owned it is. (With the
      kit of Equip now, which is the best kit of what is owned, such a swap never gains.)

    An item the profile cannot use, one already worn in that place, a Lore item worn in another place (Lore stays as it is: a
    Lore item is never worn twice, whatever is owned), a two-hander in the main hand over a worn off hand and anything in the off
    hand under a two-hander are not offered. Best gain first, ties by ``(key, tier)``; a worse item is a swap with a negative
    gain."""
    if type(limit) is not int or limit < 0:
        raise ValueError(f"limit is a whole number of at least 0, not {limit!r}")
    opts = BuildOptions() if options is None else options
    if isinstance(kit, Solution):
        slots, chosen = list(kit.kit), kit.buffs if buffs is None else tuple(buffs)
    else:
        slots, chosen = list(kit), () if buffs is None else tuple(buffs)
    if len(slots) != len(SLOT_INSTANCES):
        raise ValueError(f"a kit has {len(SLOT_INSTANCES)} places, not {len(slots)}")
    offered = _candidates(candidates)
    ledger = _Owned({} if owned is None else owned)
    named = {ident(c.key, c.tier) for c in offered}
    # the owned items that are not candidates: they are held to the counts
    counted = {name: item for name, item in ledger.items.items() if name not in named}
    # a swap is valued at the haste the swapped kit counts (the one haste of the options when they fix one)
    haste = opts.haste_assumed
    totals = eval_buff_totals(buffset.totals(chosen)) if buffset is not None else None
    p = fm.compile_profile(profile)
    usable = _Usable(profile)

    def value(trial: list[ItemVec | None]) -> Fraction:
        if haste is None:
            return fm.evaluate_truthful(p, trial, totals, setup=setup).F
        return fm.evaluate(p, trial, totals, setup=setup, haste_assumed=haste).F

    base = value(slots)
    pool = sorted((c for c in [*offered, *counted.values()] if usable(c)), key=lambda c: (c.key, c.tier))
    by_place = {place: [c for c in pool if _fits_place(c, place, setup, opts.any_rule)] for place in dict.fromkeys(SLOT_INSTANCES)}
    wears = Counter(ident(x.key, x.tier) for x in slots if x is not None)
    rows: list[SlotRow] = []
    for index, place in enumerate(SLOT_INSTANCES):
        current = slots[index]
        worn_elsewhere = {x.key for j, x in enumerate(slots) if j != index and x is not None and x.lore}
        swaps: list[Swap] = []
        for cand in by_place[place]:
            if current is not None and (cand.key, cand.tier) == (current.key, current.tier):
                continue
            if cand.lore and cand.key in worn_elsewhere:
                continue
            name = ident(cand.key, cand.tier)
            if name in counted and ledger.counts[name] <= wears[name]:
                continue  # the candidate is not the item worn in this place, so every copy the kit wears is in another place
            trial = list(slots)
            trial[index] = cand
            primary = trial[PRIMARY_INDEX]
            holds_two_hander = primary is not None and primary.weapon is not None and primary.weapon.two_handed
            if place == "PRIMARY" and holds_two_hander and trial[SECONDARY_INDEX] is not None:
                continue
            if place == "SECONDARY" and holds_two_hander:
                continue
            swaps.append(Swap(cand, value(trial) - base))
        swaps.sort(key=lambda s: (-s.delta, s.item.key, s.item.tier))
        rows.append(SlotRow(place, index, current, tuple(swaps[:limit])))
    return rows


# ---- the candidates of a tier mode ----------------------------------------------------------------------------------------


def scored_candidates(
    records: Iterable[Mapping[str, Any]], mode: str, rules: Any, D: int = 4, N: int | None = None, *, weapon_pct: int | None = None
) -> list[ItemVec]:
    """Catalog records as candidates, each at the tier its tier mode gives it (:func:`tier_for_mode`)."""
    return [at_tier(record, tier_for_mode(record, mode, D, N), rules, weapon_pct=weapon_pct) for record in records]
