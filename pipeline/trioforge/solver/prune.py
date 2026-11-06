"""Exact dominance pruning: drop the items that no optimal kit needs.

``prune(items, profile, tier, setup, buffset=None, options=None)`` takes the pool that ``build_milp`` would be given and
returns a smaller pool whose best kit is worth exactly what the best kit of the full pool is worth. Pass it the same
``setup``, ``buffset`` and ``options`` as the builder: the groups an item fits depend on the setup and on the Any rule,
and the weapon index depends on the setup. Pruning is per ``(tier, setup)``: ``tier`` is the tier the pool is
viewed at (every item must be at it) and the weapon index changes with the setup.

The rule
========

An item B is **dropped** only if some **kept, plain (non-Lore)** item A can replace it:

* A fits (has a column in) every slot group that B fits, under the setup and the Any rule;
* A is at least as good as B in **every dimension the objective scores** (below), and, for a Monk trio whose worn weight
  is scored, no heavier;
* A is not a two-hander when B is not and B fits the primary hand: a two-hander in the primary hand empties the
  secondary hand, the one row that ties the hands together;
* A is not Lore. **A Lore item never justifies a drop.** It can be worn once in all, so it cannot stand in for every
  copy of B, and it may be needed in another group.

Of two items that are equal in all of this, A may drop B only if ``(key, tier)`` of A is the smaller, so exactly one of two
identical items survives, whatever the order of the pool. A Lore item that equals a plain item is dropped by it.
Items the builder would not use are dropped first and justify nothing: items that no class of the trio can wear, items
locked to a deity that the profile does not admit, items that the race of the profile cannot wear (when the profile has
a race), and items that fit no group.

Why it is exact
===============

Take any legal kit and any dropped item B. The relation "can replace" is transitive on plain items, so B has a kept
plain item A that can replace it (the kept plain items are the maximal ones). Put A in every place of the kit where B
stands. The kit stays legal: the number of items in each group is unchanged; A is plain, so no Lore row binds it; A fits
all of B's groups, with the hand rules of the setup; the two-hander row cannot be broken, by the third condition. And
the value F cannot fall: with the buffs fixed, F is a sum of terms that each rise or stay flat when an item improves
(every weight is at least 0 and every curve is non-decreasing: the stat curves, the pools, the capped sheet armor class,
the capped regen and resists, the best worn haste, the weapon index), except the Monk bonus, which falls with the worn
weight. A is no worse in any dimension, and no heavier where the weight is scored, so F does not fall for any buff set,
and the best buff set does not fall either. Replace the dropped items one by one: the pruned pool has a kit at least as
good. The pruned pool is a subset of the full pool, so its best kit is no better. The tests check each step.

The dimensions
==============

Only what the objective can reward is compared (:func:`scored_dimensions`). Each term of the builder reads these:

=================  =========================================================================================
weight             dimensions it scores
=================  =========================================================================================
``HP``             item HP; STA (through the HP pools)
``END``            item END; STR, STA, DEX and AGI (the END average)
``MANA``           item MANA; WIS and/or INT, the stats of the trio's mana pools (none without a mana class)
``AC``             armor class (worn and off-hand shield apart); AGI (the sheet and the evasion term); the Monk
                   weight, if the trio has a Monk and the bonus can change within the reachable weights
``ATK``            item ATK; STR
``DEX``, ``CHA``   DEX; CHA
``HASTE``          the best worn haste. It is also compared when the weapon term is on, because the weapon
                   term is paid the haste the kit counts (:mod:`trioforge.solver.haste`), which rises with the best
                   worn haste, so a piece with more haste is worth at least as much to the weapons
``HPREG`` ...      each regen, with its own weight
``SV``/``SV_x``    each school's resist, with the school's weight, else ``SV``
``DMG``            the weapon index of a hand, for the setup (at the assumed haste of the options, else the
                   best the scenario offers: the order of the weapons of a hand does not depend on it); not in the
                   stick
=================  =========================================================================================

* **Armor class** counts one way in the primary hand, the Any group and every armor place (worn) and another way for a
  shield in the secondary hand (it also raises the softcap). They are compared apart, group by group, so a shield and a
  held item with more armor class do not replace each other.
* **Weapon index.** The primary hand's index has the damage bonus, the secondary's has the dual-wield factor instead and
  none of the bonus, so two weapons can swap order between the hands; both are compared. The index is exact (a fraction),
  ranked to integers for the comparison. The haste is one factor for every weapon of a hand, so two weapons in one hand
  keep their order at any haste: the ranks, and so the pruned pool, are the same for every haste the truthful solve
  assumes (one program for each haste a kit can count).
* **Weight.** The worn weight only moves the Monk bonus. It is compared (lighter or equal) when the bonus differs within
  the weights the pool can reach (the builder's own range), and then only if the bonus never rises with weight; a curve
  that does rise makes the weight an equality. Otherwise (no Monk, no armor class weight, or every reachable weight gets
  the same bonus, as at +10 where every piece weighs a tenth of a stone) it is ignored.
* Not compared: names, classes and deity (only for who is eligible), the tier (the whole pool is at one), resists
  and stats that nothing scores, and the weight of a trio without a Monk.

Preconditions are those of the builder: non-negative weights and non-negative pool factors (this module raises
``ValueError`` for a negative factor, which the builder would model wrongly). ``_MUTATION`` is a test hook that breaks one
rule on purpose, so that the tests can show they see the error; it is ``None`` in production.

Owned items and mixed tiers
===========================

The Upgrade tab prunes a pool that holds the visitor's items (at the tiers of the dump) and the candidates (at the tier of
the tier mode), under the owned-item options of the builder (``BuildOptions.owned_caps``, ``new_keys``, ``max_new`` and
``upgrades``; items are named by their idents ``key@tier``). Pass ``tier=None`` for such a pool; ``owned`` names the owned
idents besides the keys of ``options.owned_caps`` (an owned item without a count has one copy). The rule above holds, with
these changes:

* An **owned** item is never dropped, even one that is dominated or that the profile cannot use (the builder gives that
  one no column). It is in the result either way.
* A **candidate** (any other item) is dropped only by an item that is allowed to stand in for it:

  - a **candidate at its own tier** (candidates at other tiers drop nothing), or
  - an **owned item with enough copies**: its count is at least the places of its groups, so its row (``own.<ident>``) can
    never bind and it is as good as an unlimited plain item, at any tier.

* An item may not replace one that is **less constrained** than it is. Constraints rank ``free`` (neither owned nor new, or
  owned with enough copies) below ``new`` (a candidate: its wears use ``max_new``; so does an owned duplicate, whose extra
  copies do) below ``target`` (an upgrade: its first wear is made from a copy of its source and every wear uses
  ``max_new``, so it replaces nothing). A free item is not dropped for a new one, which the limit may forbid.

Why it is exact: replace the dropped item B by A, wear for wear. The places, Lore and the two-hander row hold as before. A
is at least as good in every compared dimension. If A is an owned item with enough copies, its row never binds. If A is a
candidate of B's tier that is no more constrained, the copies of A that replace the copies of B cost the same acquisitions
as they did (a duplicate's extra copies are paid for by the column it already has). The replacement relation stays
transitive on the items that may drop others, owned items are never dropped, and so the one-pass sweep finds a kept item
for every dropped one. An upgrade target that is worn more than once (the first wear made from a copy of the source, the
others copies of the target) changes none of this: nothing here reads a bound on the wears of a target from the count of its
source, an item that replaces a target wear for wear costs no more acquisitions than the target did, and the row of a source
with enough copies never binds whatever its targets do (its wears and the copy made for each worn target stay within the
places they share). ``_OWNED_MUTATION`` breaks one clause of this section on purpose for the tests.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, NamedTuple

import numpy as np

from trioforge.classes import CLASS_CODES
from trioforge.model import formulas as fm
from trioforge.model import weapons as wp
from trioforge.model.buffs import BuffSet
from trioforge.model.items import SLOT_GROUPS, ItemVec
from trioforge.solver.model import ANY_RULES, BuildOptions, ident

__all__ = ["MUTATIONS", "OWNED_MUTATIONS", "PruneReport", "fit_groups", "prune", "prune_report", "scored_dimensions"]

GROUPS: tuple[str, ...] = tuple(name for name, _ in SLOT_GROUPS)
GROUP_SIZE = dict(SLOT_GROUPS)
HANDS = ("PRIMARY", "SECONDARY")
MODEL_SLOTS = frozenset(name for name in GROUPS if name != "ANY")
#: the item stats (apart from armor class) that follow the stat rule, in the order dimensions are listed
STAT_DIMS: tuple[str, ...] = (*fm.ATTRIBUTES, "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG")
SCHOOLS = fm.SCHOOLS
#: what a dimension reads for an item that has no place for it (it never blocks a comparison it is not part of)
NO_PLACE = -(10**9)

#: the rules that ``_MUTATION`` can break (a test hook; see the module docstring)
MUTATIONS = (
    None, "lore_dominates", "ignore_groups", "ignore_haste", "ignore_weight", "ignore_resists", "ignore_weapon",
    "ignore_shield", "ignore_two_hander", "ineligible_dominates",
)
_MUTATION: str | None = None
#: the clauses of the owned-item mode that ``_OWNED_MUTATION`` can break (a test hook, kept apart from ``MUTATIONS`` so that
#: the suite of the plain rule does not run them): owned items may be dropped, an owned item dominates without enough
#: copies, an upgrade target may replace others, and how constrained an item is does not matter
OWNED_MUTATIONS = (None, "owned_dropped", "copies_ignored", "target_dominates", "rank_ignored")
_OWNED_MUTATION: str | None = None


# ---- the report ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PruneReport:
    """What :func:`prune_report` found.

    ``kept`` are the surviving items, sorted by ``(key, tier)``. ``dropped`` maps ``(key, tier)`` of every dropped item to
    ``(reason, by)``: ``"class"`` (no class of the trio can wear it), ``"deity"`` (locked to a deity the profile does not
    admit) or ``"race"`` (its races exclude the race of the profile), ``"no-slot"`` (it fits no group under this setup)
    with ``by`` None, or ``"dominated"`` with ``by`` the ``(key, tier)`` of a kept item that replaces it. ``haste_assumed`` is the haste the weapon index was taken at,
    ``compared`` the names of the dimensions compared (``"WEIGHT"`` among them when the Monk weight is) and
    ``weight_rule`` is None (weight not compared), ``"le"`` (no heavier) or ``"eq"`` (equal weight).
    """

    kept: tuple[ItemVec, ...]
    dropped: dict[tuple[str, int], tuple[str, tuple[str, int] | None]]
    haste_assumed: int
    compared: tuple[str, ...]
    weight_rule: str | None


# ---- the builder's view of the pool -------------------------------------------------------------------------------------


def _check_setup(setup: Any) -> None:
    if setup not in fm.SETUPS:
        raise ValueError(f"unknown setup {setup!r} (use {', '.join(map(repr, fm.SETUPS))})")


def fit_groups(item: ItemVec, setup: str | None, any_rule: str = "all") -> frozenset[str]:
    """The slot groups ``item`` has a column in, as ``build_milp`` makes them: a group the item lists (a hand only if the
    setup lets this item stand in it), and the Any group for an item that lists it or, under ``any_rule="all"``, for any
    item that has a slot. Whether the item is eligible (class, deity) is not asked here."""
    _check_setup(setup)
    if any_rule not in ANY_RULES:
        raise ValueError(f"any_rule is one of {', '.join(ANY_RULES)}, not {any_rule!r}")
    setup = setup or "stick"
    fits = set()
    for group in GROUPS:
        if group == "ANY":
            if "ANY" in item.slots or (any_rule == "all" and any(slot in MODEL_SLOTS for slot in item.slots)):
                fits.add(group)
        elif group in item.slots and (group not in HANDS or wp.allowed_in_hand(item, group.lower(), setup)):
            fits.add(group)
    return frozenset(fits)


def _scored(p: fm.EvalProfile, setup: str | None) -> tuple[str, ...]:
    """The dimensions the builder's terms read, from the weights and the pools (see the module docstring)."""
    weights = p.weights

    def on(key: str) -> bool:
        return weights.get(key, 0) > 0

    weapons = on("DMG") and (setup or "stick") != "stick"
    names: set[str] = set()
    if on("HP"):
        names |= {"HP", "STA"}
    if on("END"):
        names |= {"END", "STR", "STA", "DEX", "AGI"}
    if on("MANA") and p.pools["MANA"]:
        names |= {"MANA", *(spec.stat for spec in p.pools["MANA"])}
    if on("AC"):
        names |= {"AC", "AGI"}
    if on("ATK"):
        names |= {"ATK", "STR"}
    for key in ("DEX", "CHA", "HPREG", "MANAREG", "ENDREG"):
        if on(key):
            names.add(key)
    for school in SCHOOLS:  # a school's own weight, else the weight of all resists
        if on(f"SV_{school}" if f"SV_{school}" in weights else "SV"):
            names.add(f"SV_{school}")
    if on("HASTE") or weapons:  # the assumed haste of the weapon term is the best haste of the pool
        names.add("HASTE")
    if weapons:
        names.add("DMG")
    order = (*STAT_DIMS, "AC", "HASTE", *(f"SV_{school}" for school in SCHOOLS), "DMG")
    return tuple(name for name in order if name in names)


def scored_dimensions(profile: Any, setup: str | None = None) -> tuple[str, ...]:
    """The names of the dimensions the objective of ``profile`` can reward under ``setup``, and so the ones compared:
    item stats (``STR`` ... ``ENDREG``), ``AC``, ``HASTE``, ``SV_<school>`` and ``DMG`` (the weapon index). ``HASTE`` is
    also there when only the weapon term is on: the weapon index is taken at the best haste of the pool. The Monk weight
    depends on the pool and is not in this list (see :attr:`PruneReport.weight_rule`)."""
    _check_setup(setup)
    return _scored(fm.compile_profile(profile), setup)


def _assumed_haste(
    profile: Any, p: fm.EvalProfile, placed: Iterable[ItemVec], buffset: BuffSet | None, options: BuildOptions
) -> int:
    """The haste percent the builder assumes for the weapon index (``_Builder._assumed_haste``): the options' value, or the
    best spell haste on offer plus the best worn haste of the pool, up to the cap."""
    if options.haste_assumed is not None:
        return options.haste_assumed
    spell = getattr(profile, "spell_haste", None)
    if spell is None:
        offered = [fm.fr(buff.haste) for buff in (buffset.optional if buffset else ())]
        spell = max([Fraction(p.buff_totals.get("HASTE", 0)), *offered]) + p.haste_bonus  # Unbound Alacrity stacks
    worn = max([fm.fr(item.haste) for item in placed if item.haste > 0], default=Fraction(0))
    return int(min(Fraction(p.haste_cap), max(fm.fr(spell), Fraction(0)) + worn))


def _weight_rule(
    p: fm.EvalProfile, scored: Sequence[str], placed: Sequence[tuple[ItemVec, frozenset[str]]]
) -> str | None:
    """How the worn weight is compared: None, ``"le"`` (no heavier) or ``"eq"`` (equal), see the module docstring."""
    if p.monk is None or "AC" not in scored:
        return None
    top = 0  # the heaviest kit the pool can build, by group (the range the builder lays its Monk bins over)
    for group in GROUPS:
        size = GROUP_SIZE[group]
        take = size
        here = sorted(((item.weight10, 1 if item.lore else size) for item, fits in placed if group in fits), reverse=True)
        for weight, copies in here:
            if take <= 0 or weight <= 0:
                break
            count = min(copies, take)
            top += weight * count
            take -= count
    bonus = [fm.monk_bonus(p.level, 10 * stone, p.monk) for stone in range(int(top // 10) + 1)]
    if len(set(bonus)) == 1:
        return None  # every weight the pool can reach gets the same bonus: the weight is worth nothing
    return "le" if all(a >= b for a, b in zip(bonus, bonus[1:])) else "eq"


def _ranks(values: Sequence[Fraction | None]) -> list[int]:
    """The dense ranks of exact values (None, an item with no place in the hand, below all of them)."""
    rank = {value: n for n, value in enumerate(sorted({v for v in values if v is not None}))}
    return [-1 if value is None else rank[value] for value in values]


def _matrix(
    placed: Sequence[tuple[ItemVec, frozenset[str]]], p: fm.EvalProfile, setup: str | None, scored: Sequence[str],
    weight_rule: str | None, haste_assumed: int,
) -> np.ndarray:
    """One row per item: a vector in which "A can replace B" is "every entry of A is at least that of B"."""
    columns: dict[str, list[int]] = {}
    for group in GROUPS:
        columns[f"fit:{group}"] = [int(group in fits) for _, fits in placed]
    for name in STAT_DIMS:
        if name in scored:
            columns[name] = [item.stats.get(name, 0) for item, _ in placed]
    if "HASTE" in scored:
        columns["HASTE"] = [max(item.haste, 0) for item, _ in placed]  # a slowing item counts for nothing
    for school in SCHOOLS:
        if f"SV_{school}" in scored:
            columns[f"SV_{school}"] = [item.sv.get(school, 0) for item, _ in placed]
    if "AC" in scored:
        ac = [item.stats.get("AC", 0) for item, _ in placed]
        if _MUTATION == "ignore_shield":
            columns["AC"] = ac
        else:
            main = [any(g != "SECONDARY" for g in fits) for _, fits in placed]
            second = ["SECONDARY" in fits for _, fits in placed]
            shield = [item.is_shield for item, _ in placed]
            columns["AC:main"] = [a if m else NO_PLACE for a, m in zip(ac, main)]
            columns["AC:off-worn"] = [(0 if s else a) if o else NO_PLACE for a, o, s in zip(ac, second, shield)]
            columns["AC:off-shield"] = [(a if s else 0) if o else NO_PLACE for a, o, s in zip(ac, second, shield)]
    if "DMG" in scored:
        for hand in HANDS:
            index = [
                wp.damage_index_exact(item, hand.lower(), setup or "stick", haste_assumed, dw_factor=p.dw_factor)
                if hand in fits else None
                for item, fits in placed
            ]
            columns[f"DMG:{hand}"] = _ranks(index)
    if weight_rule is not None:
        columns["WEIGHT:light"] = [-item.weight10 for item, _ in placed]
        if weight_rule == "eq":
            columns["WEIGHT:heavy"] = [item.weight10 for item, _ in placed]
    dropped = {
        "ignore_groups": lambda name: name.startswith("fit:"),
        "ignore_haste": lambda name: name == "HASTE",
        "ignore_weight": lambda name: name.startswith("WEIGHT"),
        "ignore_resists": lambda name: name.startswith("SV_"),
        "ignore_weapon": lambda name: name.startswith("DMG:"),
    }.get(_MUTATION or "", lambda name: False)
    names = [name for name in columns if not dropped(name)]
    if not names:
        return np.zeros((len(placed), 0), dtype=np.int64)
    return np.array([columns[name] for name in names], dtype=np.int64).T


# ---- the sweep ---------------------------------------------------------------------------------------------------------


class _Roles(NamedTuple):
    """What the owned-item mode knows about each position of the pool (see the module docstring).

    ``protected``: owned, never dropped. ``dominates_any``: owned with enough copies, may replace a candidate of any tier.
    ``dominates_same``: may replace a candidate of its own tier whose ``rank`` is at least its own. ``tier`` and ``rank``
    (-1 an owned item with enough copies, 0 free, 1 new, 2 upgrade target) are the numbers those two clauses compare."""

    protected: np.ndarray
    dominates_any: np.ndarray
    dominates_same: np.ndarray
    tier: np.ndarray
    rank: np.ndarray


def _sweep(
    pool: Sequence[ItemVec], fits: Sequence[frozenset[str]], matrix: np.ndarray, roles: _Roles | None = None
) -> tuple[list[int], dict[int, int]]:
    """The positions kept and, for each dropped one, the position of a kept item that replaces it.

    ``A`` can replace ``B`` when A is plain, A's row is at least B's everywhere, and A is not a two-hander where B (which
    fits the primary hand) is not. Of the items that can replace each other, the smaller ``(key, tier)`` stays. A row
    that dominates another has the larger sum, and rows with equal sums that dominate each other are equal, so the items
    sorted by (sum descending, plain before Lore, the two-hander-on-the-primary-hand ones last, key) come after every item
    that can replace them: one pass against the kept plain items finds the maximal ones.

    ``roles`` (the owned-item mode) adds to "can replace": an item never dropped if it is protected; and A replaces B only
    if A is an owned item with enough copies, or A is a candidate of B's tier that is no more constrained (rank at most B's).
    Among equals the less constrained comes first (an owned item with enough copies before all, then the owned before the
    rest of its rank), so the sweep sees it before the item it may replace. Without ``roles`` every item is a candidate
    of one tier and rank 0, and nothing changes.
    """
    n = len(pool)
    lore = np.array([item.lore and _MUTATION != "lore_dominates" for item in pool], dtype=bool)
    two_handed = np.array([item.weapon is not None and item.weapon.two_handed for item in pool], dtype=bool)
    if _MUTATION == "ignore_two_hander":
        two_handed = np.zeros(n, dtype=bool)
    primary = np.array(["PRIMARY" in f for f in fits], dtype=bool)
    blocks = two_handed & primary
    score = matrix.sum(axis=1)
    idents = [(item.key, item.tier) for item in pool]
    if roles is None:
        roles = _Roles(
            np.zeros(n, dtype=bool), np.zeros(n, dtype=bool), np.ones(n, dtype=bool),
            np.array([item.tier for item in pool], dtype=np.int64), np.zeros(n, dtype=np.int64),
        )
    protected, dominates_any, dominates_same, tiers, rank = roles
    order = sorted(
        range(n),
        key=lambda i: (-int(score[i]), bool(lore[i]), bool(blocks[i]), int(rank[i]), not protected[i], idents[i]),
    )
    plain_rows = np.empty_like(matrix)
    plain_two_handed = np.zeros(n, dtype=bool)
    plain_any = np.zeros(n, dtype=bool)
    plain_tier = np.zeros(n, dtype=np.int64)
    plain_rank = np.zeros(n, dtype=np.int64)
    plain: list[int] = []
    kept: list[int] = []
    replaced_by: dict[int, int] = {}
    for i in order:
        if plain and not protected[i]:
            count = len(plain)
            able = (plain_rows[:count] >= matrix[i]).all(axis=1)
            if primary[i] and not two_handed[i]:
                able &= ~plain_two_handed[:count]
            able &= plain_any[:count] | ((plain_tier[:count] == tiers[i]) & (plain_rank[:count] <= rank[i]))
            hits = np.flatnonzero(able)
            if hits.size:
                replaced_by[i] = plain[int(hits[0])]
                continue
        kept.append(i)
        if not lore[i] and (dominates_any[i] or dominates_same[i]):
            at = len(plain)
            plain_rows[at] = matrix[i]
            plain_two_handed[at] = two_handed[i]
            plain_any[at] = dominates_any[i]
            plain_tier[at] = tiers[i]
            plain_rank[at] = 0 if _OWNED_MUTATION == "target_dominates" else rank[i]
            plain.append(i)
    return kept, replaced_by


# ---- the entry points --------------------------------------------------------------------------------------------------


def _owned_idents(owned: Iterable[str], options: BuildOptions) -> frozenset[str]:
    """The idents that are never dropped: ``owned`` and the keys of ``options.owned_caps``."""
    if isinstance(owned, (str, bytes)):
        raise ValueError(f"owned is a set of idents (key@tier), not {owned!r}")
    names = frozenset(owned)
    for name in names:
        if type(name) is not str:
            raise ValueError(f"owned names idents (key@tier), not {name!r}")
    return names | frozenset(options.owned_caps or ())


def prune_report(
    items: Iterable[ItemVec], profile: Any, tier: int | None, setup: str | None, buffset: BuffSet | None = None,
    options: BuildOptions | None = None, owned: Iterable[str] = frozenset(),
) -> PruneReport:
    """:func:`prune` with the reasons: which item was dropped for what, the assumed haste and the dimensions compared.

    Raises ``ValueError`` for an unknown setup, a tier that is not a whole number or None, or (for a whole number) that an
    item is not at, an item twice in the pool, a stat or resist the model does not know and a negative pool factor."""
    options = BuildOptions() if options is None else options
    _check_setup(setup)
    if tier is not None and type(tier) is not int:
        raise ValueError(f"the tier is a whole number, or None for a pool of many tiers, not {tier!r}")
    protected_idents = frozenset() if _OWNED_MUTATION == "owned_dropped" else _owned_idents(owned, options)
    p = fm.compile_profile(profile)
    for family in p.pools.values():
        for spec in family:
            if spec.fac < 0:
                raise ValueError(f"the pool factor of {spec.cls} is negative ({spec.fac}); the objective is not monotone")
    trio = frozenset(spec.cls for spec in p.pools["HP"])  # one HP pool per class
    by_class = trio <= set(CLASS_CODES)
    deity = getattr(profile, "deity", None)
    race = getattr(profile, "race", None)  # an evaluator profile has none: no item is left out for its race

    dropped: dict[tuple[str, int], tuple[str, tuple[str, int] | None]] = {}
    eligible: list[ItemVec] = []
    outsiders: list[ItemVec] = []
    strangers: list[ItemVec] = []  # owned items the builder gives no column: in the result all the same
    seen: set[tuple[str, int]] = set()
    for item in items:
        pair = (item.key, item.tier)
        if tier is not None and item.tier != tier:
            raise ValueError(f"item {item.key} is at tier {item.tier}, but the pool is at tier {tier}")
        if pair in seen:
            raise ValueError(f"item {item.key} (tier {item.tier}) is in the pool twice")
        seen.add(pair)
        for stat in item.stats:
            if stat not in fm.ITEM_STATS:
                raise ValueError(f"item {item.key}: unknown stat {stat!r}")
        for school in item.sv:
            if school not in SCHOOLS and school != "CORRUPTION":
                raise ValueError(f"item {item.key}: unknown resist {school!r}")
        reason = None
        if by_class and not (item.classes & trio):
            reason = "class"
        elif item.deity is not None and (deity is None or deity not in item.deity):
            reason = "deity"
        elif race is not None and item.races is not None and race not in item.races:
            reason = "race"
        if reason is None:
            eligible.append(item)
        elif ident(item.key, item.tier) in protected_idents:
            strangers.append(item)
        else:
            dropped[pair] = (reason, None)
            outsiders.append(item)

    placed: list[tuple[ItemVec, frozenset[str]]] = []
    for item in eligible:
        fits = fit_groups(item, setup, options.any_rule)
        if fits:
            placed.append((item, fits))
        elif ident(item.key, item.tier) in protected_idents:
            strangers.append(item)
        else:
            dropped[(item.key, item.tier)] = ("no-slot", None)
    haste_assumed = _assumed_haste(profile, p, [item for item, _ in placed], buffset, options)
    scored = _scored(p, setup)
    weight_rule = _weight_rule(p, scored, placed)
    pool = list(placed)
    if _MUTATION == "ineligible_dominates":
        pool += [(item, fits) for item in outsiders if (fits := fit_groups(item, setup, options.any_rule))]
    matrix = _matrix(pool, p, setup, scored, weight_rule, haste_assumed)
    roles = _roles(pool, options, protected_idents)
    kept_at, replaced_by = _sweep([item for item, _ in pool], [fits for _, fits in pool], matrix, roles)
    outsider_idents = {(item.key, item.tier) for item in outsiders}
    for position, by in replaced_by.items():
        item, other = pool[position][0], pool[by][0]
        if (item.key, item.tier) not in outsider_idents:
            dropped[(item.key, item.tier)] = ("dominated", (other.key, other.tier))
    kept = sorted(
        [pool[i][0] for i in kept_at if (pool[i][0].key, pool[i][0].tier) not in outsider_idents] + strangers,
        key=lambda item: (item.key, item.tier),
    )
    compared = (*scored, "WEIGHT") if weight_rule is not None else scored
    return PruneReport(tuple(kept), dropped, haste_assumed, compared, weight_rule)


def _roles(
    pool: Sequence[tuple[ItemVec, frozenset[str]]], options: BuildOptions, protected_idents: frozenset[str]
) -> _Roles | None:
    """The :class:`_Roles` of a pool under the owned-item options; None when no option is set and nothing is owned (the
    plain rule, unchanged)."""
    caps = options.owned_caps or {}
    ups = options.upgrades or {}
    news = set(options.new_keys) | set(ups)
    if not protected_idents and not news:
        return None
    names = [ident(item.key, item.tier) for item, _ in pool]
    n = len(pool)
    lore = np.array([item.lore for item, _ in pool], dtype=bool)
    protected = np.array([name in protected_idents for name in names], dtype=bool)
    target = np.array([name in ups for name in names], dtype=bool)
    new = np.array([name in news for name in names], dtype=bool)
    count = np.array([caps.get(name, 1) for name in names], dtype=np.int64)
    places = np.array([sum(GROUP_SIZE[group] for group in fits) for _, fits in pool], dtype=np.int64)
    enough = protected & ~lore & ((count >= places) | (_OWNED_MUTATION == "copies_ignored"))
    duplicate = protected & new & (count >= 1)
    rank = np.where(target, 2, np.where(enough, -1, np.where(new, 1, 0))).astype(np.int64)
    if _OWNED_MUTATION == "rank_ignored":
        rank = np.zeros(n, dtype=np.int64)
    dominates_same = (~protected | duplicate) & (~target | (_OWNED_MUTATION == "target_dominates"))
    tiers = np.array([item.tier for item, _ in pool], dtype=np.int64)
    return _Roles(protected, enough, dominates_same, tiers, rank)


def prune(
    items: Iterable[ItemVec], profile: Any, tier: int | None, setup: str | None, buffset: BuffSet | None = None,
    options: BuildOptions | None = None, owned: Iterable[str] = frozenset(),
) -> list[ItemVec]:
    """The pool without the items that a kept plain item can replace (see the module docstring), sorted by ``(key, tier)``.

    ``profile`` is anything the builder takes (an ``EvalProfile`` or a ``Profile``; its ``deity`` decides which
    deity-locked items count); ``tier`` the tier of the pool, or None for a pool of many tiers (the owned-item mode of the
    module docstring); ``setup`` one of ``None``, ``"1h-shield"``, ``"2h"``, ``"dw"``, ``"stick"``; ``buffset`` and
    ``options`` the ones given to ``build_milp`` (they decide the Any rule, the haste the weapon index is taken at and the
    owned-item options); ``owned`` the idents (``key@tier``) of owned items besides the keys of ``options.owned_caps``:
    they are never dropped. The input is not changed. Raises ``ValueError`` as :func:`prune_report` does.
    """
    return list(prune_report(items, profile, tier, setup, buffset, options, owned).kept)
