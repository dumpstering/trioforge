"""The MILP builder: the best kit by the absolute value F, as a mixed-integer program.

``build_milp(profile, items, setup, buffset, options)`` returns a :class:`Milp` whose optimum, plus its constant,
is the maximum over every legal kit and every legal buff choice of ``trioforge.model.formulas.evaluate`` (the
un-floored, absolute F). The builder shares no row with the evaluator: it lays the same formulas out as linear
rows, and the brute-force tests compare the two. What it takes from the evaluator's module are numbers only: the
constants of the rules and the Monk bonus of a whole stone; the damage index of a hand column is the weapons
module's, which the evaluator writes out again (a test keeps the two equal).

The model
=========

* **Columns.** For every slot group (``HEAD FACE EAR NECK ... PRIMARY SECONDARY``, :data:`SLOT_GROUPS`) and every
  item that fits it, one integer column counts the copies worn there: 0 to the size of the group, 0 or 1 for a Lore
  item. A group holds at most its places; a Lore item is worn once over all groups. Items for other classes than
  the trio's, deity-locked items (unless ``profile.deity`` admits them) and items whose ``races`` exclude the
  profile's ``race`` (when it has one) get no column. The Any group takes every item that has a slot
  (``any_rule="all"``, the default: weapons and shields are stat sticks there) or only the items that list
  ``ANY`` (``"explicit"``).
* **Setups** (:mod:`trioforge.model.weapons`): ``2h`` a two-hander in PRIMARY and nothing in SECONDARY; ``dw``
  one-handed weapons in both hands; ``1h-shield`` a one-handed weapon and a shield; ``stick`` anything, with a row
  that a two-hander in PRIMARY leaves SECONDARY empty; ``ranged`` the hands of the stick and a bow, and only a bow, in
  RANGE, which is always filled (the row ``range.bow``: even when damage is worth nothing the place holds a bow, and a pool with no bow for it
  is a ``ValueError``; in every other setup RANGE takes any item that lists it, or none). In every setup a two-hander has no SECONDARY column at all (it
  needs both hands, whatever its page lists), and the pruning agrees because it asks the same function. Whether the
  trio can dual wield is decided by
  ``weapons.setups_for``; the builder only applies the hand rules. A hand column adds ``DMG`` times the weapons
  module's damage index at the program's assumed haste (a constant, see ``BuildOptions.haste_assumed``; the truthful solve of
  :mod:`trioforge.solver.haste` builds a program for each haste a kit can count, with the row ``haste.floor``): the bonus
  is the primary hand's, the off hand of ``dw`` takes the dual-wield factor, the ``stick`` setup scores none, and the ``ranged`` setup
  scores the bow in RANGE on its own damage per delay (no bonus: that is a main hand's) times the profile's ``ranged_factor`` and nothing else.
  With ``BuildOptions.procs`` the hands that swing add the proc they count (``_term_procs``, :mod:`trioforge.model.procs`): ``DMG x value / 600`` with no haste factor, a constant on the
  column of a hand item (its own proc below the tier where procs can be moved, the best proc it can host at and above it) except in ``dw`` at and above that tier, where the two hands
  couple through the copies of a Lore proc and the program has one binary for each proc a hand can host, with the rows ``proc.one``, ``proc.host`` and ``proc.copies``.
* **Absolute objective.** The constants hold the naked character and the always-on buffs, and every curve is laid
  out from a total of 0, over the **reachable** range of its input (multi-copy stacking included: a non-Lore ring
  wearable in four places can add four times its stat). ``F = milp.const + c . x``.
* **Curves.** A piecewise-linear value of a total ``T`` is an incremental set of segments ``x_i`` in ``[0, len_i]``
  with ``sum x_i <= T - T_min``; wherever a later segment is steeper than an earlier one, an *ordering binary* (its
  segment is full, or every later one is empty) makes the fill sequential. A total that can fall below 0 gets one
  *deficit binary* (the value is flat there). A curve with no kink inside the reachable range has no binary.
* **Best two pools** (HP, mana, END): the order of the pools is compared over the reachable ranges of their
  inputs. If one pair is the top two everywhere (:func:`plan_top_pools`), only that pair is summed; otherwise there
  are selection binaries ``z_c`` (sum 2), ``kept_c <= pool_c + B_c (1 - z_c)`` and ``kept_c <= M_c z_c`` with ``M_c``
  the largest absolute pool value over the range and ``B_c = max(0, -min pool_c)``, so that a pool that can fall
  below zero is worth exactly 0 while it is not selected (and its own value, negative or not, while it is).
* **END** uses an auxiliary average of the four stats, each capped at 510 by its own variable.
* **Sheet AC**: ``a <= X`` and ``a <= rate X + (1 - rate) Y``, linear in the gear AC, the off-hand shield AC and the
  capped AGI; the Monk bonus (one binary per whole-stone bin of worn weight, exactly one active) and the Iksar
  constant sit on top of the cap or inside X, as the profile says.
* **Haste**: the best worn piece only (one binary per distinct value), up to the room ``max(0, cap - spell)`` that
  the active spell haste leaves. Spell hastes exclude each other, so the spell haste is a constant per choice: the
  always-on buffs' haste, or the haste of the one chosen haste buff if it is better (a linear term in the buff
  binaries), and the room is a constant per choice in the same way.
* **Regen** and **resists**: capped linear terms. **Buffs**: one binary per optional buff, clique rows for the
  conflicts and a row for the limit; each buff's effect enters the totals linearly (a spell haste takes the best).

**Owned items** (the Upgrade tab). Four options make the builder answer questions about gear a visitor owns; with their
defaults the model is unchanged, row for row. An item is named by its **ident** ``key@tier`` (:func:`ident`): the same key
at two tiers is two items.

* ``owned_caps`` (``{ident: count}``): an owned item is worn at most its count over **every group** it stands in. One row
  ``own.<ident>`` sums its columns; it is left out when the count cannot bind (the count reaches what the columns could add
  up to, and for a Lore item that is 1). A count of 0 keeps the item out of the kit. The Lore row, which spans the tiers of
  a key, is the same row it always was.
* ``new_keys`` and ``max_new``: ``new.limit`` is the row ``sum(wears of the new items) <= max_new`` over every group. An item
  that is not owned and is in ``new_keys`` is **new**: each of its wears is one of the ``max_new``. An item that is owned
  and in ``new_keys`` is a **duplicate**: one more copy may be acquired, so it may be worn above its count. A continuous
  column ``new[<ident>]`` holds the copies above the count (``own.<ident>`` becomes ``sum(x) - new <= count``) and it is the
  column that enters ``new.limit``. A Lore duplicate adds nothing (the Lore row already allows one wear) and is left out.
* ``upgrades`` (``{target ident: source ident}``): the target is the same key at a higher tier. Its **first** copy is made
  from one copy of the owned source; every further copy of the target is a copy of the target (once it is owned it is never
  upgraded again, and making two copies of it from two copies of the source costs as many acquisitions as making one and
  copying it, and leaves fewer of the source, so the model never needs it). The copy that is made stands in one place at one
  tier, so ``own.<source>`` counts it. A target that can be worn at most once (a Lore item, or when its columns and
  ``max_new`` allow one wear) is counted by its wear: ``own.<source>`` covers the target's columns, as it always did. A
  target that can be worn more often has a 0/1 integer column ``made[<target>]`` and the row ``made.<target>``:
  ``sum(columns of the target) - reach * made <= 0``, where ``reach`` is the sum of the upper bounds of its columns, no more
  than ``max_new`` when that is set, so a worn target has ``made = 1``; ``own.<source>`` counts ``made`` in place of the
  target's columns (``made`` is left out with ``own.<source>`` when the count cannot bind). Every wear of the target is one
  of the ``max_new`` (an upgrade is never free, and neither is a copy of it). The ``made`` columns are counted in
  ``info["binaries"]["made"]``, with the other kinds of binary (``BINARY_KINDS``).

``Milp.row_names`` names every row, in the order of the rows: ``group.<GROUP>``, ``lore.<key>``, ``two_hander``,
``buff.clique[..]``, ``buff.conflict[a,b]``, ``buff.limit``, ``<curve label>.total|deficit|flat|ord<i>.full|empty<j>``,
``cap.<ATTR>.max``, ``pool.<family>.kept.<cls>.le_pool|le_chosen``, ``pool.<family>.picks|twin<i>``,
``monk.one|upper|lower``, ``sheet.below|past``, ``haste.y<value>.worn|one|best|room``, ``haste.floor``, ``haste.ceil[<spell>]``, ``haste.over[<spell>]``, ``regen.<NAME>.max``,
``sv.<SCHOOL>.max``, ``made.<ident>`` (each before the ``own.`` row of its source), ``own.<ident>`` and ``new.limit``. A name that would repeat (a hand-made buff set can list a clique
twice) gets ``#2``, ``#3`` and so on: the names are unique, and the same on every build.

``BuildOptions.mutation`` breaks the builder on purpose (a moved END knee, a dropped ordering binary, a missing
haste clamp); the brute-force suite must fail on each (``test_milp_bruteforce.py``). It is never set in production.

``BuildOptions.legacy`` (``formulas.LegacyTerms``) switches the objective to the legacy one, for the private regression
of an old profile (``trioforge.solver.compat``); without it nothing above changes. HP, mana and END are then flat (the
gear and buff points times the weight: there are no pools and no selection binaries), the evasion, strength-to-attack,
DEX and charisma terms are not generated, and in their place the profile's explicit curves are laid out, each ``factor x
curve(total of its attribute)`` with the same segments, ordering binaries and deficit binary as the generated ones.
The sheet armor class is the legacy one (``X = mult (worn + shield) + nongear``, ``Y = cap + shield``), through the same
two rows. A profile with a Monk or Iksar bonus is refused.
"""

from __future__ import annotations

import copy
import dataclasses
import itertools
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, NamedTuple

import numpy as np

from trioforge.classes import CLASS_CODES
from trioforge.model import formulas as fm
from trioforge.model import weapons as wp
from trioforge.model.buffs import Buff, BuffSet
from trioforge.model.items import SLOT_GROUPS, ItemVec
from trioforge.model.procs import PER_MINUTE_TO_INDEX, ProcTable

__all__ = [
    "ANY_RULES",
    "BuildOptions",
    "Csr",
    "Decoded",
    "LevelPrograms",
    "Milp",
    "MUTATIONS",
    "build_milp",
    "eval_buff_totals",
    "haste_levels",
    "ident",
    "plan_top_pools",
]

GROUP_SIZE = dict(SLOT_GROUPS)
MODEL_SLOTS = tuple(name for name, _ in SLOT_GROUPS if name != "ANY")
HANDS = ("PRIMARY", "SECONDARY")
SETUPS = (None, "1h-shield", "2h", "dw", "stick", "ranged")
#: the groups whose items the weapons module is asked about (the two hands, and the range place for the bow setup)
WEAPON_GROUPS = ("PRIMARY", "SECONDARY", "RANGE")
ANY_RULES = ("all", "explicit")
MUTATIONS = (None, "end_knee_101", "drop_ordering_binary", "skip_haste_clamp")
ATTRIBUTES = fm.ATTRIBUTES
FLATS = ("HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG")
SCHOOLS = fm.SCHOOLS
INF = math.inf
ZERO = Fraction(0)
ONE = Fraction(1)
STAT_CAP = Fraction(fm.STAT_CAP)
BINARY_KINDS = ("ordering", "deficit", "selection", "monk", "haste", "buff", "made")
GEAR_KEYS = frozenset(ATTRIBUTES) | frozenset(FLATS) | {"AC"}
RANGE_SLOT_FITS = frozenset(MODEL_SLOTS)


# ---- the public shapes -------------------------------------------------------------------------------------------


class Csr(NamedTuple):
    """A sparse matrix in compressed row form: ``index``/``value`` of row ``r`` are ``start[r]:start[r + 1]``."""

    start: np.ndarray
    index: np.ndarray
    value: np.ndarray
    shape: tuple[int, int]


_IDENT = re.compile(r"[^@]+@(10|[0-9])")


def ident(key: str, tier: int) -> str:
    """The ident of an item in the owned-item options: ``key@tier`` (a catalog key has no ``@``)."""
    return f"{key}@{tier}"


def _parse_ident(name: Any, what: str) -> tuple[str, int]:
    if type(name) is not str or not _IDENT.fullmatch(name):
        raise ValueError(f"{what}: {name!r} is not an item ident (key@tier, with a tier from 0 to 10)")
    key, _, tier = name.rpartition("@")
    return key, int(tier)


@dataclass(frozen=True)
class BuildOptions:
    """``any_rule``: which items fit the Any group (``"all"`` or ``"explicit"``). ``haste_assumed``: the haste
    percent the weapon index assumes (a constant of the program); ``None`` takes the spell haste the scenario can
    reach plus the best worn haste of the pool, up to the cap, which is a constant the kit need not reach (the truthful
    solve of :mod:`trioforge.solver.haste` sets the assumed haste itself, one program for each level the kit can reach).
    ``haste_floor``: the program has a row ``haste.floor`` that the kit's own counted haste (the active spell haste plus the
    worn haste that counts, up to the cap) is at least this many percent; ``None`` (the default) has no such row. It makes the
    weapon term true when ``haste_assumed`` is the same number. ``haste_exact`` (needs ``haste_floor``) adds the rows ``haste.ceil[<spell>]``
    and ``haste.over[<spell>]`` that make the kit count *exactly* ``haste_floor`` (no worn haste piece above what the active spell
    haste leaves of it, no haste buff that alone counts more): the truthful solve uses it so that the model's value of the kit is the
    kit's own at every point of the search, and a level's relaxation is a bound on the kits that count that haste. ``mutation``: a test hook, see the module docstring.
    ``legacy``: the legacy objective's terms (``formulas.LegacyTerms``) or None, see the module docstring.
    ``procs``: the :class:`~trioforge.model.procs.ProcTable` of the trio, or None (no proc counts: the program is what it was before procs). The weapon term then adds the proc each
    swinging hand counts, a constant on a hand column but for the dual-wield setup at the tier where procs can be moved (see the module docstring).

    ``owned_caps``, ``new_keys``, ``max_new`` and ``upgrades`` are the owned-item options (see the module docstring);
    items are named by their idents ``key@tier``. They are checked here: an ident of the wrong form, a count or a limit
    that is not a whole number from 0 up, an upgrade whose target is not the same key at a higher tier, whose source is
    not owned (a count of at least 1) or whose target is owned. That the idents are items of the pool is checked by the
    builder."""

    any_rule: str = "all"
    haste_assumed: int | None = None
    haste_floor: int | None = None
    haste_exact: bool = False
    mutation: str | None = None
    legacy: fm.LegacyTerms | None = None
    owned_caps: Mapping[str, int] | None = None
    new_keys: frozenset[str] = frozenset()
    max_new: int | None = None
    upgrades: Mapping[str, str] | None = None
    procs: ProcTable | None = None

    def __post_init__(self) -> None:
        if self.legacy is not None and not isinstance(self.legacy, fm.LegacyTerms):
            raise TypeError(f"legacy must be a LegacyTerms, not {type(self.legacy).__name__}")
        if self.procs is not None and not isinstance(self.procs, ProcTable):
            raise TypeError(f"procs must be a ProcTable, not {type(self.procs).__name__}")
        if self.any_rule not in ANY_RULES:
            raise ValueError(f"any_rule is one of {', '.join(ANY_RULES)}, not {self.any_rule!r}")
        if self.mutation not in MUTATIONS:
            raise ValueError(f"unknown mutation {self.mutation!r}")
        if self.haste_assumed is not None and (type(self.haste_assumed) is not int or self.haste_assumed < 0):
            raise ValueError(f"haste_assumed is a whole number of at least 0, not {self.haste_assumed!r}")
        if self.haste_floor is not None and (type(self.haste_floor) is not int or self.haste_floor < 0):
            raise ValueError(f"haste_floor is None or a whole number of at least 0, not {self.haste_floor!r}")
        if self.haste_floor is not None and self.haste_assumed is None:
            raise ValueError("haste_floor needs haste_assumed: a level program pays the weapon term at its own level")
        if type(self.haste_exact) is not bool:
            raise ValueError(f"haste_exact is true or false, not {self.haste_exact!r}")
        if self.haste_exact and self.haste_floor is None:
            raise ValueError("haste_exact needs haste_floor: it makes the kit count exactly that haste")
        caps: dict[str, int] = {}
        if self.owned_caps is not None:
            if not isinstance(self.owned_caps, Mapping):
                raise ValueError(f"owned_caps is a mapping of idents to counts, not {type(self.owned_caps).__name__}")
            for name, count in self.owned_caps.items():
                _parse_ident(name, "owned_caps")
                if type(count) is not int or count < 0:
                    raise ValueError(f"owned_caps: the count of {name} is a whole number of at least 0, not {count!r}")
                caps[name] = count
        object.__setattr__(self, "owned_caps", dict(sorted(caps.items())) or None)
        if isinstance(self.new_keys, (str, bytes)) or not isinstance(self.new_keys, Iterable):
            raise ValueError(f"new_keys is a set of idents, not {self.new_keys!r}")
        news = frozenset(self.new_keys)
        for name in news:
            _parse_ident(name, "new_keys")
        object.__setattr__(self, "new_keys", news)
        if self.max_new is not None and (type(self.max_new) is not int or self.max_new < 0):
            raise ValueError(f"max_new is None or a whole number of at least 0, not {self.max_new!r}")
        ups: dict[str, str] = {}
        if self.upgrades is not None:
            if not isinstance(self.upgrades, Mapping):
                raise ValueError(f"upgrades is a mapping of target idents to source idents, not {type(self.upgrades).__name__}")
            for target, source in self.upgrades.items():
                target_key, target_tier = _parse_ident(target, "upgrades")
                source_key, source_tier = _parse_ident(source, "upgrades")
                if target_key != source_key or target_tier <= source_tier:
                    raise ValueError(f"upgrades: {target} is not the same key as {source} at a higher tier")
                if target in caps:
                    raise ValueError(f"upgrades: the target {target} is owned; an upgrade makes an item the visitor lacks")
                if caps.get(source, 0) < 1:
                    raise ValueError(f"upgrades: the source {source} is not owned (it needs a count of at least 1)")
                ups[target] = source
        object.__setattr__(self, "upgrades", dict(sorted(ups.items())) or None)


@dataclass(frozen=True)
class Decoded:
    """A solution read back: the items worn in each group (sorted by key) and the ids of the chosen optional buffs."""

    groups: dict[str, list[ItemVec]]
    buffs: tuple[int, ...]


@dataclass
class Milp:
    """The program ``maximize const + c . x`` subject to ``row_lb <= A x <= row_ub``, bounds and integrality.

    ``colmap`` maps an item column to ``(slot group, item key)`` and ``index`` is its inverse; ``names`` names every
    column and ``row_names`` every row (unique; see the module docstring). ``info`` describes the build (rows, columns,
    binaries by kind (``BINARY_KINDS``), how each pool family is modelled). The
    arrays are plain numpy arrays: a test may tighten a bound to force a choice. ``profile``, ``items``, ``setup``,
    ``buffset`` and ``haste_assumed`` are what a solution is evaluated with.
    """

    c: np.ndarray
    A: Csr
    row_lb: np.ndarray
    row_ub: np.ndarray
    col_lb: np.ndarray
    col_ub: np.ndarray
    integrality: np.ndarray
    const: float
    colmap: dict[int, tuple[str, str]]
    index: dict[tuple[str, str], int]
    names: list[str]
    item_cols: tuple[tuple[int, str, ItemVec], ...]
    buff_cols: dict[int, int]
    profile: Any
    items: tuple[ItemVec, ...]
    setup: str | None
    buffset: BuffSet | None
    haste_assumed: int
    options: BuildOptions
    info: dict[str, Any] = field(default_factory=dict)
    sense: str = "max"
    row_names: list[str] = field(default_factory=list)

    @property
    def num_cols(self) -> int:
        return int(self.c.shape[0])

    @property
    def num_rows(self) -> int:
        return int(self.row_lb.shape[0])

    def value(self, x: np.ndarray) -> float:
        """The objective of the column vector ``x`` including the constant."""
        return self.const + float(np.dot(self.c, x))

    def decode(self, x: np.ndarray) -> Decoded:
        """The kit and the buffs of a solution vector; refuses a vector whose integer columns are not integers."""
        groups: dict[str, list[ItemVec]] = {}
        for col, group, item in self.item_cols:
            copies = _integral(x[col], self.names[col])
            groups.setdefault(group, []).extend([item] * copies)
        ordered = {g: sorted(groups[g], key=lambda i: (i.key, i.tier)) for g, _ in SLOT_GROUPS if groups.get(g)}
        chosen = tuple(sorted(bid for col, bid in self.buff_cols.items() if _integral(x[col], self.names[col])))
        return Decoded(ordered, chosen)


def _integral(value: float, name: str) -> int:
    rounded = round(float(value))
    if abs(value - rounded) > 1e-6:
        raise ValueError(f"column {name} is not an integer: {value!r}")
    return int(rounded)


def eval_buff_totals(totals: Mapping[str, Any]) -> dict[str, Any]:
    """``BuffSet.totals`` (stat names, ``sv``, ``haste``) in the shape ``formulas.evaluate`` reads (``SV``,
    ``HASTE``)."""
    out = {key: value for key, value in totals.items() if key not in ("sv", "haste")}
    out["SV"] = dict(totals["sv"])
    out["HASTE"] = totals["haste"]
    return out


# ---- the best two pools ------------------------------------------------------------------------------------------


def plan_top_pools(specs: Sequence[tuple[Fraction, Fraction, Any, Fraction, Fraction]]) -> tuple[str, tuple[int, ...]]:
    """How to sum the best two of some pools ``base + fac * input`` over the reachable range of their inputs.

    ``specs`` holds ``(base, fac, key, lo, hi)`` per pool: pools with the same ``key`` share one input that runs
    over ``[lo, hi]``; pools with different keys are compared on the boxes of their ranges (a safe overestimate of
    what can happen together). Returns ``(mode, indices)``:

    * ``("none", ())`` without pools and ``("all", ...)`` when no more than two pools exist (all count);
    * ``("fixed", pair)`` when one pair is a top two at every reachable point (the others never beat anything in
      it: their order inside the pair does not matter for the sum);
    * ``("select", all indices)`` otherwise: which two count depends on the gear, and the model needs binaries.
    """
    count = len(specs)
    if count == 0:
        return "none", ()
    if count <= fm.POOLS_COUNTED:
        return "all", tuple(range(count))
    spec = [(Fraction(b), Fraction(f), key, Fraction(lo), Fraction(hi)) for b, f, key, lo, hi in specs]

    def can_beat(e: int, d: int) -> bool:
        be, fe, ke, loe, hie = spec[e]
        bd, fd, kd, lod, hid = spec[d]
        if ke == kd:
            return max((be - bd) + (fe - fd) * loe, (be - bd) + (fe - fd) * hie) > 0
        top_e = max(be + fe * loe, be + fe * hie)
        bottom_d = min(bd + fd * lod, bd + fd * hid)
        return top_e > bottom_d

    for excluded in itertools.combinations(range(count), count - fm.POOLS_COUNTED):
        rest = [i for i in range(count) if i not in excluded]
        if not any(can_beat(e, d) for e in excluded for d in rest):
            return "fixed", tuple(rest)
    return "select", tuple(range(count))


# ---- exact linear expressions ----------------------------------------------------------------------------------


class Lin:
    """``const + sum(coef * column)`` with exact coefficients. Treated as immutable once built."""

    __slots__ = ("const", "terms")

    def __init__(self, const: Any = ZERO, terms: Mapping[int, Any] | None = None) -> None:
        self.const = Fraction(const)
        self.terms: dict[int, Fraction] = {} if terms is None else {c: Fraction(v) for c, v in terms.items() if v}

    def scaled(self, k: Any) -> Lin:
        k = Fraction(k)
        return Lin(self.const * k, {c: v * k for c, v in self.terms.items()}) if k else Lin()

    def plus(self, other: Lin, k: Any = ONE) -> Lin:
        k = Fraction(k)
        terms = dict(self.terms)
        for c, v in other.terms.items():
            terms[c] = terms.get(c, ZERO) + v * k
        return Lin(self.const + other.const * k, terms)


class Conv(NamedTuple):
    """A curve's output: the expression, the range of its value and an identity for pools that share it."""

    lin: Lin
    lo: Fraction
    hi: Fraction
    key: int


# ---- the builder -------------------------------------------------------------------------------------------------


def build_milp(
    profile: Any, items: Iterable[ItemVec], setup: str | None, buffset: BuffSet | None = None,
    options: BuildOptions | None = None,
) -> Milp:
    """Build the program for ``profile`` (an EvalProfile or anything with its attributes), the item pool ``items``,
    the weapon ``setup`` and the buff set; see the module docstring. Raises ``ValueError`` for an unknown setup or
    stat, a repeated item, a ``buff_totals`` that is not the always-on buffs, or optional haste buffs that can be
    active together."""
    return _Builder(profile, items, setup, buffset, options or BuildOptions()).build()


def haste_levels(
    profile: Any, items: Iterable[ItemVec], setup: str | None, buffset: BuffSet | None = None,
    options: BuildOptions | None = None,
) -> tuple[int, ...]:
    """The hastes a kit of this scenario can count, in percent, rising: every spell haste the scenario offers (the always-on
    buffs' with Unbound Alacrity, or the best of those and one optional haste buff's, plus Unbound Alacrity) with 0 and with each
    distinct worn haste of the pool added, each cut at the profile's haste cap. A kit's counted haste is always one of them,
    because only the best worn piece counts and only the best spell haste. ``items`` and ``options`` are the ones given to
    :func:`build_milp` (the options decide the Any rule and so which items have a place). Raises ``ValueError`` for a haste
    that is not a whole number (the program assumes whole percents)."""
    builder = _Builder(profile, items, setup, buffset, options or BuildOptions())
    builder._item_columns()
    builder._buff_columns()
    return builder.haste_levels()


def _csr(rows: Sequence[tuple[dict[int, Fraction], Fraction | None, Fraction | None]]) -> tuple[np.ndarray, ...]:
    """The CSR arrays of rows ``(terms, lb, ub)``: start, index, value, row_lb, row_ub (each row's columns rise)."""
    start, index, value = [0], [], []
    row_lb, row_ub = [], []
    for terms, lb, ub in rows:
        for col in sorted(terms):
            index.append(col)
            value.append(float(terms[col]))
        start.append(len(index))
        row_lb.append(-INF if lb is None else float(lb))
        row_ub.append(INF if ub is None else float(ub))
    return (
        np.array(start, dtype=np.int32), np.array(index, dtype=np.int32), np.array(value, dtype=np.float64),
        np.array(row_lb, dtype=np.float64), np.array(row_ub, dtype=np.float64),
    )


class LevelPrograms:
    """The programs of the haste levels of one scenario (what :func:`build_milp` gives for ``haste_assumed=L``, ``haste_floor=L`` and
    ``haste_exact`` for each level ``L``), made from one build: the columns and the rows that do not depend on the level are
    built once, and ``program_for(level)`` adds the weapon coefficients of the level and the rows that make the kit count it (the arrays are
    those of ``build_milp`` with the same options, to the last bit). ``levels`` are the hastes a kit can count
    (:func:`haste_levels`); ``options`` is what ``build_milp`` takes, and ``haste_assumed``, ``haste_floor`` and ``haste_exact`` are set by the
    level."""

    def __init__(
        self, profile: Any, items: Iterable[ItemVec], setup: str | None, buffset: BuffSet | None = None,
        options: BuildOptions | None = None,
    ):
        self.options = options or BuildOptions()
        template = dataclasses.replace(self.options, haste_assumed=0, haste_floor=0, haste_exact=True)
        builder = _Builder(profile, items, setup, buffset, template)
        builder._capture = True
        self._builder = builder
        builder._item_columns()
        builder._buff_columns()
        self.levels = builder.haste_levels()
        self._base = builder._build_terms()
        self._made: dict[int, Milp] = {}

    def program_for(self, level: int) -> Milp:
        """The program of ``level`` (made once)."""
        made = self._made.get(level)
        if made is not None:
            return made
        builder, base = self._builder, self._base
        opts = dataclasses.replace(self.options, haste_assumed=level, haste_floor=level, haste_exact=True)
        builder.opts = opts
        saved = builder.rows, builder.row_names, builder._row_uses
        builder.rows, builder.row_names, builder._row_uses = [], [], dict(saved[2])
        try:
            builder._haste_level_rows(level)
            rows, names = builder.rows, builder.row_names
        finally:
            builder.rows, builder.row_names, builder._row_uses = saved
        l_start, l_index, l_value, l_lb, l_ub = _csr(rows)
        slot, cut = builder._haste_slot, int(base.A.start[builder._haste_slot])
        start = np.concatenate([base.A.start[: slot + 1], l_start[1:] + cut, base.A.start[slot + 1 :] + len(l_index)]).astype(np.int32)
        index = np.concatenate([base.A.index[:cut], l_index, base.A.index[cut:]]).astype(np.int32)
        value = np.concatenate([base.A.value[:cut], l_value, base.A.value[cut:]])
        row_lb = np.concatenate([base.row_lb[:slot], l_lb, base.row_lb[slot:]])
        row_ub = np.concatenate([base.row_ub[:slot], l_ub, base.row_ub[slot:]])
        row_names = [*base.row_names[:slot], *names, *base.row_names[slot:]]
        c = base.c.copy()
        w = builder._weight("DMG")
        if w != 0:
            for col, hand, item in builder._weapon_cols:
                index_of = wp.damage_index_exact(
                    item, hand, builder.setup or "stick", level, dw_factor=builder.p.dw_factor, ranged_factor=builder.p.ranged_factor,
                    swing_factor=wp.swing_factor_of(builder.p), level=builder.p.level,
                )
                if index_of:
                    c[col] = float(builder.obj.get(col, ZERO) + w * index_of)
        info = copy.deepcopy(base.info)
        info.update(rows=len(row_names), haste_assumed=level)
        info["haste_floor"] = level
        info["haste_exact"] = True
        made = dataclasses.replace(
            base, c=c, A=Csr(start, index, value, (len(row_names), base.A.shape[1])), row_lb=row_lb, row_ub=row_ub,
            col_lb=base.col_lb.copy(), col_ub=base.col_ub.copy(), integrality=base.integrality.copy(), haste_assumed=level, options=opts,
            info=info, row_names=row_names, names=list(base.names),
        )
        self._made[level] = made
        return made


class _Builder:
    def __init__(
        self, profile: Any, items: Iterable[ItemVec], setup: str | None, buffset: BuffSet | None, options: BuildOptions
    ):
        if setup not in SETUPS:
            raise ValueError(f"unknown setup {setup!r} (use {', '.join(map(repr, SETUPS))})")
        self.opts = options
        self.legacy = options.legacy
        self.setup = setup
        self.profile_in = profile
        self.p = fm.compile_profile(profile)
        if self.legacy is not None:
            fm.check_legacy(self.p, self.legacy)
        self.buffset = buffset
        self.deity = getattr(profile, "deity", None)
        self.race = getattr(profile, "race", None)  # an evaluator profile has none: no item is left out for its race
        self.trio = frozenset(spec.cls for spec in self.p.pools["HP"])  # one HP pool per class
        self.by_class = self.trio <= set(CLASS_CODES)  # pools named by something else: no class to filter the pool by
        self.w = self.p.weights
        # columns
        self.names: list[str] = []
        self.lb: list[Fraction | None] = []
        self.ub: list[Fraction | None] = []
        self.integer: list[int] = []
        self.obj: dict[int, Fraction] = {}
        self.const = ZERO
        self.rows: list[tuple[dict[int, Fraction], Fraction | None, Fraction | None]] = []
        self.row_names: list[str] = []
        self._row_uses: dict[str, int] = {}
        self.input_idents: set[str] = set()
        self.col_group: dict[int, str] = {}
        self.item_cols: list[tuple[int, str, ItemVec]] = []
        self.index: dict[tuple[str, str], int] = {}
        self.cols_of_item: dict[int, list[int]] = {}
        self.buff_cols: dict[int, int] = {}
        self.buff_of_col: dict[int, Buff] = {}
        self.info: dict[str, Any] = {
            "pools": {"HP": "off", "MANA": "off", "END": "off"}, "binaries": dict.fromkeys(BINARY_KINDS, 0),
        }
        self._keys = itertools.count()
        self._cache: dict[Any, Lin] = {}
        self._dropped_ordering = False
        # the programs of the haste levels (LevelPrograms) build once and leave out what depends on the level: the rows after the worn-haste
        # columns (``haste.floor`` and the ceilings) and the weapon part of the objective
        self._capture = False
        self._haste_ctx: tuple[Fraction, Fraction, list[tuple[int, Fraction]], int | None] | None = None
        self._haste_slot = 0
        self._weapon_cols: list[tuple[int, str, ItemVec]] = []
        self.items = self._collect(items)

    # -- small helpers ------------------------------------------------------------------------------------------

    def _new(self, name: str, lb: Any, ub: Any, *, integer: bool = False) -> int:
        self.names.append(name)
        self.lb.append(None if lb is None else Fraction(lb))
        self.ub.append(None if ub is None else Fraction(ub))
        self.integer.append(1 if integer else 0)
        return len(self.names) - 1

    def _row(self, name: str, terms: Mapping[int, Any], lb: Any, ub: Any) -> None:
        """Add the row ``lb <= terms <= ub`` called ``name`` (a name that repeats gets ``#2``, ``#3``, ...)."""
        clean = {c: Fraction(v) for c, v in terms.items() if v}
        uses = self._row_uses.get(name, 0) + 1
        self._row_uses[name] = uses
        self.row_names.append(name if uses == 1 else f"{name}#{uses}")
        self.rows.append((clean, None if lb is None else Fraction(lb), None if ub is None else Fraction(ub)))

    def _add_obj(self, col: int, coef: Any) -> None:
        self.obj[col] = self.obj.get(col, ZERO) + Fraction(coef)

    def _add_lin(self, lin: Lin, weight: Any) -> None:
        weight = Fraction(weight)
        self.const += lin.const * weight
        for col, coef in lin.terms.items():
            self._add_obj(col, coef * weight)

    def _weight(self, key: str) -> Fraction:
        return Fraction(self.w.get(key, 0))

    # -- the item pool -------------------------------------------------------------------------------------------

    def _collect(self, items: Iterable[ItemVec]) -> list[ItemVec]:
        kept: list[ItemVec] = []
        seen: set[tuple[str, int]] = set()
        for item in items:
            pair = (item.key, item.tier)
            if pair in seen:
                raise ValueError(f"item {item.key} (tier {item.tier}) is in the pool twice")
            seen.add(pair)
            self.input_idents.add(ident(item.key, item.tier))
            for stat in item.stats:
                if stat not in fm.ITEM_STATS:
                    raise ValueError(f"item {item.key}: unknown stat {stat!r}")
            for school in item.sv:
                if school not in SCHOOLS and school != "CORRUPTION":
                    raise ValueError(f"item {item.key}: unknown resist {school!r}")
            if self.by_class and not (item.classes & self.trio):
                continue
            if item.deity is not None and (self.deity is None or self.deity not in item.deity):
                continue
            if self.race is not None and item.races is not None and self.race not in item.races:
                continue
            kept.append(item)
        return sorted(kept, key=lambda i: (i.key, i.tier))

    def _fits(self, item: ItemVec, group: str) -> bool:
        if group == "ANY":
            listed = "ANY" in item.slots
            return listed or (self.opts.any_rule == "all" and any(s in RANGE_SLOT_FITS for s in item.slots))
        if group not in item.slots:
            return False
        if group in WEAPON_GROUPS:
            return wp.allowed_in_hand(item, group.lower(), self.setup or "stick")
        return True

    # -- build -------------------------------------------------------------------------------------------------

    def build(self) -> Milp:
        self._item_columns()
        self._buff_columns()
        return self._build_terms()

    def _build_terms(self) -> Milp:
        self.haste_assumed = self._assumed_haste()
        if self.legacy is not None:
            self.info["pools"] = dict.fromkeys(("HP", "MANA", "END"), "legacy")
        for term in (
            self._term_hp, self._term_mana, self._term_end, self._term_ac, self._term_atk, self._term_dex,
            self._term_cha, self._term_haste, self._term_regen, self._term_resists, self._term_weapons,
            self._term_procs, self._term_legacy_curves,
        ):
            term()
        return self._finish()

    def _item_columns(self) -> None:
        by_group: dict[str, list[int]] = {}
        lore_cols: dict[str, list[int]] = {}
        for group, size in SLOT_GROUPS:
            for position, item in enumerate(self.items):
                if not self._fits(item, group):
                    continue
                label = item.key if (group, item.key) not in self.index else f"{item.key}@{item.tier}"
                col = self._new(f"n[{group}|{label}]", 0, 1 if item.lore else size, integer=True)
                self.col_group[col] = group
                self.item_cols.append((col, group, item))
                self.index[(group, label)] = col
                self.cols_of_item.setdefault(position, []).append(col)
                by_group.setdefault(group, []).append(col)
                if item.lore:
                    lore_cols.setdefault(item.key, []).append(col)
        for group, cols in by_group.items():
            if sum(self.ub[c] for c in cols) > GROUP_SIZE[group]:
                self._row(f"group.{group}", {c: 1 for c in cols}, None, GROUP_SIZE[group])
        if self.setup == "ranged":  # the bow setup is the one in which the range place holds a bow: it is filled even when the damage is worth nothing
            bows = by_group.get("RANGE", [])
            if not bows:
                raise ValueError("the ranged setup needs a bow for the range place, and the items have none that fits it")
            self._row("range.bow", {c: 1 for c in bows}, 1, None)
        for key, cols in lore_cols.items():
            if len(cols) > 1:
                self._row(f"lore.{key}", {c: 1 for c in cols}, None, 1)
        # a two-hander in the primary hand leaves the secondary hand empty
        two_handed = [
            col for col, group, item in self.item_cols
            if group == "PRIMARY" and item.weapon is not None and item.weapon.two_handed
        ]
        secondary = [col for col, group, _ in self.item_cols if group == "SECONDARY"]
        if two_handed and secondary:
            self._row("two_hander", {c: 1 for c in two_handed + secondary}, None, 1)
        self._ownership_rows()
        self.info["items"] = len(self.item_cols)

    def _ownership_rows(self) -> None:
        """The rows of the owned-item options: ``own.<ident>`` for every count that can bind (with a ``made.<target>`` row
        before it for each upgrade target that can be worn more than once), then ``new.limit`` (see the module docstring).
        The options are read in sorted order, so the rows do not depend on the order of a mapping."""
        caps = self.opts.owned_caps or {}
        ups = self.opts.upgrades or {}
        news = set(self.opts.new_keys) | set(ups)  # an upgrade is a new wear whether or not it is listed
        if not caps and not news:
            return
        absent = sorted((set(caps) | news | set(ups.values())) - self.input_idents)
        if absent:
            raise ValueError(f"{absent[0]} is not an item of the pool")
        by_ident: dict[str, list[int]] = {}
        lore: dict[str, bool] = {}
        for col, _, item in self.item_cols:
            name = ident(item.key, item.tier)
            by_ident.setdefault(name, []).append(col)
            lore[name] = item.lore
        targets_of: dict[str, list[str]] = {}
        for target in sorted(ups):
            targets_of.setdefault(ups[target], []).append(target)
        new_terms: dict[int, Fraction] = {}
        for name in sorted(caps):
            cap = caps[name]
            if name in news and cap == 0:
                continue  # listed as owned with none, and a candidate: a plain new item, below
            members = list(by_ident.get(name, ()))
            repeated: list[tuple[str, list[int], Fraction | int]] = []  # targets that can be worn more than once, with their reach
            for target in targets_of.get(name, ()):
                columns = list(by_ident.get(target, ()))
                top = sum(self.ub[c] for c in columns)  # the most wears of the target the model can hold
                if self.opts.max_new is not None:
                    top = min(top, self.opts.max_new)
                if columns and not lore.get(target, False) and top > 1:  # more than one wear (the reach is a whole number)
                    repeated.append((target, columns, top))  # one copy of the source makes the first wear (below)
                else:
                    members += columns  # worn once at most: the upgraded copy is its wear
            if not members and not repeated:
                continue  # the profile cannot use it: no column, nothing to count
            is_lore = lore.get(name, False) or any(lore.get(t, False) for t in targets_of.get(name, ()))
            reach = sum(self.ub[c] for c in members) + len(repeated)  # (a repeated target counts at most one copy)
            if cap >= (min(reach, 1) if is_lore else reach):
                continue  # the count can never bind (a Lore item is worn once whatever its count)
            terms = {c: ONE for c in members}
            for target, columns, top in repeated:  # made[target] is 1 when the target is worn at all
                made = self._new(f"made[{target}]", 0, 1, integer=True)
                self.info["binaries"]["made"] += 1
                self._row(f"made.{target}", {**dict.fromkeys(columns, ONE), made: -top}, None, 0)
                terms[made] = ONE
            if name in news and not is_lore:  # a duplicate: copies above the count are acquired ones
                room = reach - cap if self.opts.max_new is None else min(reach - cap, self.opts.max_new)
                extra = self._new(f"new[{name}]", 0, room)
                terms[extra] = -ONE
                new_terms[extra] = ONE
            self._row(f"own.{name}", terms, None, cap)
        for name in sorted(n for n in news if caps.get(n, 0) == 0):
            for col in by_ident.get(name, ()):
                new_terms[col] = ONE
        if self.opts.max_new is not None and new_terms:
            if self.opts.max_new < sum(self.ub[c] for c in new_terms):
                self._row("new.limit", new_terms, None, self.opts.max_new)

    # -- buffs ---------------------------------------------------------------------------------------------------

    def _bconst(self, name: str) -> Fraction:
        return Fraction(self.p.buff_totals.get(name, 0))

    def _bconst_sv(self, school: str) -> Fraction:
        return Fraction(self.p.buff_totals["SV"].get(school, 0))

    def _buff_columns(self) -> None:
        buffset = self.buffset
        if buffset is None:
            return
        if buffset.always_on:
            want = fm._buff_view(eval_buff_totals(buffset.totals(())))
            have = self.p.buff_totals
            keys = set(want) | set(have)
            for key in sorted(keys - {"SV"}):
                if Fraction(want.get(key, 0)) != Fraction(have.get(key, 0)):
                    raise ValueError(f"profile.buff_totals disagrees with the always-on buffs of the buffset at {key}")
            for school in SCHOOLS:
                if Fraction(want["SV"].get(school, 0)) != Fraction(have["SV"].get(school, 0)):
                    raise ValueError(
                        f"profile.buff_totals disagrees with the always-on buffs of the buffset at SV {school}"
                    )
        optional = {buff.id: buff for buff in buffset.optional}
        for buff in buffset.optional:
            col = self._new(f"buff[{buff.id}]", 0, 1, integer=True)
            self.buff_cols[col] = buff.id
            self.buff_of_col[col] = buff
        self.info["binaries"]["buff"] = len(buffset.optional)
        col_of = {bid: col for col, bid in self.buff_cols.items()}
        covered: set[tuple[int, int]] = set()
        for clique in buffset.cliques:
            unknown = [bid for bid in clique if bid not in optional]
            if unknown:
                raise ValueError(f"a clique names buff {unknown[0]}, which is not optional")
            self._row("buff.clique[" + ",".join(map(str, clique)) + "]", {col_of[bid]: 1 for bid in clique}, None, 1)
            covered.update(itertools.combinations(sorted(clique), 2))
        for a, b in buffset.conflicts:
            if a not in optional or b not in optional:
                raise ValueError(f"a conflict names buff {a} or {b}, which is not optional")
            pair = (a, b) if a < b else (b, a)
            if pair not in covered:
                self._row(f"buff.conflict[{pair[0]},{pair[1]}]", {col_of[a]: 1, col_of[b]: 1}, None, 1)
                covered.add(pair)
        if buffset.cardinality is not None:
            self._row("buff.limit", {col: 1 for col in self.buff_cols}, None, buffset.cardinality)
        hasty = sorted(bid for bid, buff in optional.items() if buff.haste > 0)
        for a, b in itertools.combinations(hasty, 2):
            if (a, b) not in covered:
                raise ValueError(
                    f"buffs {a} and {b} both carry spell haste and can be active together: only the best counts"
                )

    def _buff_coef(self, buff: Buff, name: str) -> Fraction:
        if name.startswith("SV_"):
            return fm.fr(buff.sv[name[3:]])
        return fm.fr(buff.stats[name])

    # -- quantities as expressions -------------------------------------------------------------------------------

    def _item_coef(self, name: str, item: ItemVec, group: str) -> int:
        if name in GEAR_KEYS and name != "AC":
            return item.stats.get(name, 0)
        if name in ("ACW", "ACS"):
            ac = item.stats.get("AC", 0)
            off_hand_shield = item.is_shield and group == "SECONDARY"
            return ac if (name == "ACS") == off_hand_shield else 0
        if name == "W10":
            return item.weight10
        if name.startswith("SV_"):
            return item.sv.get(name[3:], 0)
        raise KeyError(name)

    def _gear(self, name: str) -> Lin:
        """The worn items' part of a quantity, with no constant."""
        key = ("gear", name)
        if key not in self._cache:
            terms = {}
            for col, group, item in self.item_cols:
                coef = self._item_coef(name, item, group)
                if coef:
                    terms[col] = coef
            self._cache[key] = Lin(ZERO, terms)
        return self._cache[key]

    def _buffpart(self, name: str) -> Lin:
        """The buffs' part of a quantity: the always-on constant and one term per optional buff."""
        key = ("buff", name)
        if key not in self._cache:
            const = self._bconst_sv(name[3:]) if name.startswith("SV_") else self._bconst(name)
            terms = {}
            for col, buff in self.buff_of_col.items():
                coef = self._buff_coef(buff, name)
                if coef:
                    terms[col] = coef
            self._cache[key] = Lin(const, terms)
        return self._cache[key]

    def _total(self, name: str) -> Lin:
        """Naked (attributes only) + buffs + gear."""
        key = ("total", name)
        if key not in self._cache:
            total = self._gear(name).plus(self._buffpart(name))
            if name in ATTRIBUTES:
                total = Lin(total.const + Fraction(self.p.naked[name]), total.terms)
            self._cache[key] = total
        return self._cache[key]

    def _range(self, lin: Lin) -> tuple[Fraction, Fraction]:
        """The lowest and highest value ``lin`` can take (item columns by group, with the places of each)."""
        lo = hi = lin.const
        by_group: dict[str, list[tuple[Fraction, int]]] = {}
        for col, coef in lin.terms.items():
            group = self.col_group.get(col)
            if group is None:
                low, high = self.lb[col], self.ub[col]
                if low is None or high is None:
                    raise RuntimeError(f"column {self.names[col]} is unbounded inside a range")
                a, b = coef * low, coef * high
                lo += min(a, b)
                hi += max(a, b)
            else:
                by_group.setdefault(group, []).append((coef, int(self.ub[col])))
        for group, entries in by_group.items():
            places = GROUP_SIZE[group]
            take = places
            for coef, ub in sorted((e for e in entries if e[0] > 0), reverse=True):
                if take <= 0:
                    break
                n = min(ub, take)
                hi += coef * n
                take -= n
            take = places
            for coef, ub in sorted(e for e in entries if e[0] < 0):
                if take <= 0:
                    break
                n = min(ub, take)
                lo += coef * n
                take -= n
        return lo, hi

    # -- curves --------------------------------------------------------------------------------------------------

    def _curve(self, lin: Lin, breaks: Sequence[Any], slopes: Sequence[Any], label: str) -> Conv:
        """The value ``f(max(lin, 0))`` of a piecewise-linear curve from 0, as an expression over new columns.

        The curve is laid out over the reachable range of ``lin`` only. Every user of the result is non-decreasing
        in it, so the maximizing solver fills the segments as far as the total allows.
        """
        breaks = [Fraction(b) for b in breaks]
        slopes = [Fraction(s) for s in slopes]
        t_lo, t_hi = self._range(lin)
        eff_lo = max(t_lo, ZERO)
        f_lo = fm.pwl(eff_lo, breaks, slopes)
        f_hi = fm.pwl(max(t_hi, ZERO), breaks, slopes)
        key = next(self._keys)
        if f_hi == f_lo:  # flat over the whole range (or the range is a point)
            return Conv(Lin(f_lo), f_lo, f_hi, key)
        bands: list[tuple[Fraction, Fraction]] = []
        for k, slope in enumerate(slopes):
            start = ZERO if k == 0 else breaks[k - 1]
            stop = breaks[k] if k < len(breaks) else None
            a = max(start, eff_lo)
            b = t_hi if stop is None else min(stop, t_hi)
            if b > a:
                bands.append((slope, b - a))
        while bands and bands[-1][0] == 0:  # a flat tail needs no segment: the sum below is only bounded above
            bands.pop()
        xs = [self._new(f"{label}.seg{k}", 0, length) for k, (_, length) in enumerate(bands)]
        row = {x: ONE for x in xs}
        for col, coef in lin.terms.items():
            row[col] = row.get(col, ZERO) - coef
        if t_lo >= 0:
            self._row(f"{label}.total", row, None, lin.const - eff_lo)  # sum of the segments <= total - lowest total
        else:  # the total can be negative, where the value is flat: u is the deficit, one binary decides
            u = self._new(f"{label}.u", 0, -t_lo)
            wz = self._new(f"{label}.wz", 0, 1, integer=True)
            self.info["binaries"]["deficit"] += 1
            row[u] = -ONE
            self._row(f"{label}.total", row, None, lin.const)
            self._row(f"{label}.deficit", {u: ONE, wz: -t_lo}, None, -t_lo)
            self._row(f"{label}.flat", {**{x: ONE for x in xs}, wz: -sum(length for _, length in bands)}, None, 0)
        count = len(bands)
        for i in range(count - 1):
            if not any(bands[j][0] > bands[i][0] for j in range(i + 1, count)):
                continue
            if self.opts.mutation == "drop_ordering_binary" and not self._dropped_ordering:
                self._dropped_ordering = True
                continue
            z = self._new(f"{label}.ord{i}", 0, 1, integer=True)
            self.info["binaries"]["ordering"] += 1
            self._row(f"{label}.ord{i}.full", {xs[i]: ONE, z: -bands[i][1]}, 0, None)  # segment i is full when z = 1
            for j in range(i + 1, count):
                self._row(f"{label}.ord{i}.empty{j}", {xs[j]: ONE, z: -bands[j][1]}, None, 0)  # and every later one is empty when z = 0
        return Conv(Lin(f_lo, {x: s for x, (s, _) in zip(xs, bands)}), f_lo, f_hi, key)

    def _capped(self, name: str) -> Lin:
        """``min(total, 510)`` of an attribute: the total itself when it cannot reach 510, else a capped column."""
        key = ("capped", name)
        if key not in self._cache:
            total = self._total(name)
            lo, hi = self._range(total)
            if hi <= STAT_CAP:
                lin = total
            elif lo >= STAT_CAP:
                lin = Lin(STAT_CAP)
            else:
                col = self._new(f"cap.{name}", lo, STAT_CAP)
                row = {col: ONE}
                for c, coef in total.terms.items():
                    row[c] = row.get(c, ZERO) - coef
                self._row(f"cap.{name}.max", row, None, total.const)
                lin = Lin(ZERO, {col: ONE})
            self._cache[key] = lin
        return self._cache[key]

    # -- pools ---------------------------------------------------------------------------------------------------

    def _pool_family(
        self, family: str, specs: Sequence[tuple[str, Fraction, Fraction, Conv]], weight: Fraction
    ) -> None:
        mode, chosen = plan_top_pools([(base, fac, conv.key, conv.lo, conv.hi) for _, base, fac, conv in specs])
        self.info["pools"][family] = mode
        if mode in ("all", "fixed"):
            for i in chosen:
                _, base, fac, conv = specs[i]
                self.const += weight * base
                self._add_lin(conv.lin, weight * fac)
            return
        kept, flags = [], []
        for cls, base, fac, conv in specs:
            top = max(base + fac * conv.hi, ZERO)  # the largest absolute pool value, never a delta
            bottom = min(base + fac * conv.lo, ZERO)
            depth = -bottom  # B: how far below zero the pool can fall; 0 for a pool that never does
            k = self._new(f"pool.{family}.kept.{cls}", bottom, top)
            z = self._new(f"pool.{family}.z.{cls}", 0, 1, integer=True)
            row = {k: ONE, z: depth}
            for c, coef in conv.lin.terms.items():
                row[c] = row.get(c, ZERO) - fac * coef
            # kept <= pool + B (1 - z): the pool itself when selected; when not, a pool below zero must not be subtracted
            self._row(f"pool.{family}.kept.{cls}.le_pool", row, None, base + fac * conv.lin.const + depth)
            self._row(f"pool.{family}.kept.{cls}.le_chosen", {k: ONE, z: -top}, None, 0)  # and zero unless the pool is selected
            self._add_obj(k, weight)
            kept.append(k)
            flags.append(z)
        self._row(f"pool.{family}.picks", {z: ONE for z in flags}, fm.POOLS_COUNTED, fm.POOLS_COUNTED)
        for i in range(len(specs) - 1):  # identical pools are interchangeable: take the first
            (_, b1, f1, c1), (_, b2, f2, c2) = specs[i], specs[i + 1]
            if (b1, f1, c1.key) == (b2, f2, c2.key):
                self._row(f"pool.{family}.twin{i}", {flags[i]: ONE, flags[i + 1]: -ONE}, 0, None)
        self.info["binaries"]["selection"] += len(specs)

    def _term_hp(self) -> None:
        w = self._weight("HP")
        if w == 0:
            return
        self._add_lin(self._total("HP"), w)
        if self.legacy is not None:  # flat: the old profile's curves carry the pools
            return
        sta = self._curve(self._total("STA"), fm.STA_CURVE[0], fm.STA_CURVE[1], "curve.HP.sta")
        specs = [(q.cls, fm.HP_POOL_CONSTANT + q.base, q.fac, sta) for q in self.p.pools["HP"]]
        self._pool_family("HP", specs, w)

    def _term_mana(self) -> None:
        w = self._weight("MANA")
        pools = self.p.pools["MANA"]
        if w == 0:
            return
        if self.legacy is not None:  # flat: the old profile's curves carry the pools
            self._add_lin(self._total("MANA"), w)
            return
        if not pools:  # no mana class: no mana, whatever the items give
            self.info["pools"]["MANA"] = "none"
            return
        breaks, slopes = fm.MANA_BANDS if self.p.bands is None else (self.p.bands["breaks"], self.p.bands["slopes"])
        self._add_lin(self._total("MANA"), w)
        convs: dict[str, Conv] = {}
        specs = []
        for q in pools:
            if q.stat not in convs:
                convs[q.stat] = self._curve(self._total(q.stat), breaks, slopes, f"curve.MANA.{q.stat}")
            specs.append((q.cls, q.base, q.fac, convs[q.stat]))
        self._pool_family("MANA", specs, w)

    def _term_end(self) -> None:
        w = self._weight("END")
        if w == 0:
            return
        self._add_lin(self._total("END"), w)
        if self.legacy is not None:  # flat: the old profile's curves carry the pools
            return
        average = Lin()
        for stat in ("STR", "STA", "DEX", "AGI"):
            average = average.plus(self._capped(stat), Fraction(1, 4))
        breaks = (101, 201) if self.opts.mutation == "end_knee_101" else fm.END_BREAKS
        conv = self._curve(average, breaks, fm.END_SLOPES, "curve.END.avg")
        specs = [(q.cls, q.base, q.fac, conv) for q in self.p.pools["END"]]
        self._pool_family("END", specs, w)

    # -- armor class, attack, dexterity, charisma ------------------------------------------------------------------

    def _monk_bonus_lin(self) -> Lin:
        """The Monk bonus as an expression: a constant when one bin covers the reachable weights, else bin binaries."""
        p = self.p
        weight = self._gear("W10")
        _, top = self._range(weight)
        stones = int(top // 10)
        values = [fm.monk_bonus(p.level, 10 * k, p.monk) for k in range(stones + 1)]
        bins: list[list[int]] = []  # [first stone, last stone, bonus]
        for stone, bonus in enumerate(values):
            if bins and bins[-1][2] == bonus:
                bins[-1][1] = stone
            else:
                bins.append([stone, stone, bonus])
        if len(bins) == 1:
            return Lin(bins[0][2])
        zs = [self._new(f"monk.z{n}", 0, 1, integer=True) for n in range(len(bins))]
        self.info["binaries"]["monk"] += len(bins)
        self._row("monk.one", {z: ONE for z in zs}, 1, 1)
        upper = {c: v for c, v in weight.terms.items()}
        self._row("monk.upper", {**upper, **{z: -(10 * b[1] + 9) for z, b in zip(zs, bins)}}, None, 0)  # W <= 10 hi + 9 of the bin
        lower = {**{c: -v for c, v in upper.items()}, **{z: 10 * b[0] for z, b in zip(zs, bins)}}
        self._row("monk.lower", lower, None, 0)  # 10 lo <= W
        return Lin(ZERO, {z: b[2] for z, b in zip(zs, bins)})

    def _capped_sheet(self, x: Lin, y: Lin, rate: Fraction, per_point: Fraction) -> None:
        """The two rows ``a <= X`` and ``a <= rate X + (1 - rate) Y`` and the worth of ``a``: ``per_point`` each."""
        a = self._new("sheet.a", None, None)
        below = {a: ONE}
        past = {a: ONE}
        for col, coef in x.terms.items():
            below[col] = below.get(col, ZERO) - coef
            past[col] = past.get(col, ZERO) - rate * coef
        for col, coef in y.terms.items():
            past[col] = past.get(col, ZERO) - (1 - rate) * coef
        self._row("sheet.below", below, None, x.const)
        self._row("sheet.past", past, None, rate * x.const + (1 - rate) * y.const)
        self._add_obj(a, per_point)

    def _term_ac(self) -> None:
        w = self._weight("AC")
        if w == 0:
            return
        if self.legacy is not None:
            sheet = self.legacy.sheet
            if sheet is None:
                raise ValueError("the legacy terms need a sheet while the AC weight is above 0")
            gear, shield = self._gear("ACW"), self._gear("ACS")
            x = gear.plus(shield).scaled(sheet.mult).plus(Lin(sheet.nongear))
            self._capped_sheet(x, Lin(sheet.cap).plus(shield), sheet.ret, w / sheet.mult)
            return
        p = self.p
        per_point = w / fm.SHEET_ITEM_MULT
        monk = self._monk_bonus_lin() if p.monk is not None else Lin()
        iksar = Fraction(p.iksar_ac)
        inside = Lin()
        if p.placement["monk"] == "inside":
            inside = inside.plus(monk)
        else:
            self._add_lin(monk, per_point)
        if p.placement["iksar"] == "inside":
            inside = inside.plus(Lin(iksar))
        else:
            self.const += per_point * iksar
        gear, shield = self._gear("ACW"), self._gear("ACS")
        agi_share = Fraction(p.stance["agi_share"]) if p.stance is not None else ONE  # (the Berserker stance: agility counts for nothing in the armor class and the evasion)
        x = (
            gear.plus(shield).scaled(fm.SHEET_ITEM_MULT)
            .plus(Lin(Fraction(p.defense_cap) / fm.SHEET_DEFENSE_DIV))
            .plus(self._buffpart("AC"), Fraction(1, fm.SHEET_SPELL_AC_DIV))
        )
        if agi_share:
            x = x.plus(self._capped("AGI"), Fraction(1, fm.SHEET_AGI_DIV) * agi_share)
        x = x.plus(inside)
        cap, rate = Fraction(p.softcap[0]), Fraction(p.softcap[1])
        floor = math.floor(cap * (100 + Fraction(p.cs_pct) + Fraction(p.pe_pct)) / 100)
        y = Lin(floor).plus(shield)
        self._capped_sheet(x, y, rate, per_point)
        if agi_share:
            evasion = self._curve(self._total("AGI"), (fm.STAT_CAP,), (1, 0), "curve.AC.agi")
            self._add_lin(evasion.lin, w * fm.AGI_TO_AC * agi_share)

    def _term_atk(self) -> None:
        w = self._weight("ATK")
        if w == 0:
            return
        self._add_lin(self._total("ATK"), w)
        if self.legacy is not None:  # the old profile's strength curve carries the attack it gives
            return
        strength = self._curve(self._total("STR"), (fm.STAT_CAP,), (1, 0), "curve.ATK.str")
        self._add_lin(strength.lin, w * fm.STR_TO_ATK)

    def _term_dex(self) -> None:
        w = self._weight("DEX")
        if w == 0 or self.legacy is not None:  # (legacy: the dexterity curve is one of the explicit ones)
            return
        dex = self._curve(self._total("DEX"), (fm.STAT_KNEE, fm.STAT_CAP), (1, fm.DEX_PAST_KNEE, 0), "curve.DEX.dex")
        self._add_lin(dex.lin, w)

    def _term_cha(self) -> None:
        w = self._weight("CHA")
        if w == 0 or self.legacy is not None:  # (legacy: charisma is worth what the explicit curves say)
            return
        cha = self._curve(self._total("CHA"), (fm.STAT_CAP,), (1, 0), "curve.CHA.cha")
        self._add_lin(cha.lin, w)

    # -- haste, regen, resists -------------------------------------------------------------------------------------

    def _assumed_haste(self) -> int:
        """The haste percent the weapon index assumes: the best spell haste on offer (the profile's ``spell_haste``
        when it has one) plus the best worn haste of the pool, up to the cap."""
        if self.opts.haste_assumed is not None:
            return self.opts.haste_assumed
        spell = getattr(self.profile_in, "spell_haste", None)
        if spell is None:
            offered = [fm.fr(b.haste) for b in (self.buffset.optional if self.buffset else ())]
            spell = max([self._bconst("HASTE")] + offered) + self.p.haste_bonus  # Unbound Alacrity stacks
        worn = max([fm.fr(i.haste) for n, i in enumerate(self.items) if i.haste > 0 and n in self.cols_of_item] + [ZERO])
        return int(min(Fraction(self.p.haste_cap), max(fm.fr(spell), ZERO) + worn))

    def haste_levels(self) -> tuple[int, ...]:
        """:func:`haste_levels` of the item columns and the buff columns that were made."""
        cap = Fraction(self.p.haste_cap)
        base = max(self._bconst("HASTE") + fm.fr(self.p.haste_bonus), ZERO)
        spells = {base}
        for buff in self.buff_of_col.values():
            if buff.haste > 0:
                spells.add(max(base, fm.fr(buff.haste) + fm.fr(self.p.haste_bonus)))
        worn = {ZERO}
        for position, item in enumerate(self.items):
            if item.haste > 0 and position in self.cols_of_item:
                worn.add(fm.fr(item.haste))
        levels = sorted({min(cap, spell + piece) for spell in spells for piece in worn})
        for level in levels:
            if level.denominator != 1:
                raise ValueError(f"a haste of {level} is not a whole number of percent: the weapon term assumes whole percents")
        return tuple(int(level) for level in levels)

    def _haste_binaries(self, value_of) -> list[tuple[int, Fraction]]:
        """One binary per distinct effective haste value; it may be 1 only if some item of that value is worn."""
        by_value: dict[Fraction, list[int]] = {}
        for position, item in enumerate(self.items):
            if item.haste > 0 and position in self.cols_of_item:
                value = value_of(Fraction(item.haste))
                if value > 0:
                    by_value.setdefault(value, []).extend(self.cols_of_item[position])
        flags = []
        for value in sorted(by_value):
            y = self._new(f"haste.y{value}", 0, 1, integer=True)
            self._row(f"haste.y{value}.worn", {y: ONE, **{c: -ONE for c in by_value[value]}}, None, 0)
            flags.append((y, value))
        self.info["binaries"]["haste"] += len(flags)
        if len(flags) > 1:
            self._row("haste.one", {y: ONE for y, _ in flags}, None, 1)
        return flags

    def _term_haste(self) -> None:
        w = self._weight("HASTE")
        floor = self.opts.haste_floor
        if w == 0 and floor is None:
            return
        cap = Fraction(self.p.haste_cap)
        if floor is not None and floor > cap:
            raise ValueError(f"haste_floor {floor} is above the haste cap {cap}")
        # The spell haste is the buff haste plus the flat haste of Unbound Alacrity (a trio with a Monk): adding it to the
        # always-on haste and to each buff's own haste shifts every spell haste by the same amount, so "the best one counts"
        # still picks the same buff.
        bonus = fm.fr(self.p.haste_bonus)
        base = self._bconst("HASTE") + bonus  # the haste of the always-on buffs, with Unbound Alacrity
        clamp = (lambda v: v) if self.opts.mutation == "skip_haste_clamp" else (lambda v: max(ZERO, v))
        # Only the best spell haste counts and the haste buffs exclude each other, so the spell haste is one of a few
        # constants: the base while no haste buff is active, max(base, h) while the buff of haste h is.
        choices = [(col, fm.fr(buff.haste) + bonus) for col, buff in self.buff_of_col.items() if buff.haste > 0]
        self.const += w * min(base, cap)
        for col, h in choices:
            self._add_obj(col, w * (min(max(base, h), cap) - min(base, cap)))
        # worn haste: the best piece counts, up to the room the active spell haste leaves, max(0, cap - spell)
        room0 = clamp(cap - base)
        rooms = [(col, clamp(cap - max(base, h))) for col, h in choices]
        top = max([room0] + [room for _, room in rooms])
        flags = self._haste_binaries(lambda h: min(h, top)) if top > 0 else []
        q = None
        if flags or self.opts.mutation == "skip_haste_clamp":
            q = self._new("haste.q", 0, None)
            self._row("haste.best", {q: ONE, **{y: -v for y, v in flags}}, None, 0)  # no more than the best worn piece
            self._row("haste.room", {q: ONE, **{col: -(room - room0) for col, room in rooms}}, None, room0)  # nor than the room left
            if w != 0:
                self._add_obj(q, w)
        self._haste_ctx = (base, cap, choices, q)
        self._haste_slot = len(self.rows)
        if floor is not None and not self._capture:
            self._haste_level_rows(floor)

    def _haste_level_rows(self, floor: int) -> None:
        """The rows that make the kit count the haste ``floor`` (the only rows of the haste term that depend on it)."""
        assert self._haste_ctx is not None
        base, cap, choices, q = self._haste_ctx
        if floor > cap:
            raise ValueError(f"haste_floor {floor} is above the haste cap {cap}")
        if floor > min(base, cap):
            # the haste the kit counts is the spell haste of its buffs plus the worn haste q: at least `floor`, so that the
            # weapon term, which assumed `floor`, is true of the kit (the weapon index rises with the haste)
            terms = {col: min(max(base, h), cap) - min(base, cap) for col, h in choices}
            if q is not None:
                terms[q] = ONE
            self._row("haste.floor", terms, floor - min(base, cap), None)
        if self.opts.haste_exact and floor < cap:
            self._haste_ceiling(Fraction(floor), base, choices)

    def _haste_ceiling(self, floor: Fraction, base: Fraction, choices: list[tuple[int, Fraction]]) -> None:
        """The kit counts no more than ``floor`` (below the cap): under each spell haste ``s`` that a choice of buffs can make
        active, no worn piece has more than ``floor - s`` haste, and a haste buff whose own spell haste is above ``floor`` is
        not taken. With ``haste.floor`` the kit counts exactly ``floor``. The spell hastes are the base (no buff, or a buff
        that is no stronger) and the distinct ``max(base, h)`` of the haste buffs; the haste buffs exclude each other, so the
        active one is the sum of its class' buff columns."""
        if floor < base:
            raise ValueError(f"haste_floor {floor} is below the haste {base} that the always-on buffs and Unbound Alacrity give")
        classes: dict[Fraction, list[int]] = {}
        for col, h in choices:
            if max(base, h) > base:
                classes.setdefault(max(base, h), []).append(col)
        stronger = [col for cols in classes.values() for col in cols]

        def over(allowed: Fraction) -> list[int]:
            return [
                col for position, item in enumerate(self.items) if item.haste > allowed and item.haste > 0 and position in self.cols_of_item
                for col in self.cols_of_item[position]
            ]

        def big(cols: list[int]) -> Fraction:
            return sum((self.ub[c] for c in cols), ZERO)

        pieces = over(floor - base)
        if pieces:  # no buff stronger than the base is active: the worn piece may not be above what the base leaves
            m = big(pieces)
            self._row(f"haste.ceil[{base}]", {**dict.fromkeys(pieces, ONE), **dict.fromkeys(stronger, -m)}, None, 0)
        for spell in sorted(classes):
            cols = classes[spell]
            if spell > floor:
                self._row(f"haste.over[{spell}]", dict.fromkeys(cols, ONE), None, 0)
                continue
            pieces = over(floor - spell)
            if pieces:
                m = big(pieces)
                self._row(f"haste.ceil[{spell}]", {**dict.fromkeys(pieces, ONE), **dict.fromkeys(cols, m)}, None, m)

    def _term_regen(self) -> None:
        for name, cap_key in (("HPREG", "HP"), ("MANAREG", "MANA"), ("ENDREG", "END")):
            w = self._weight(name)
            if w == 0:
                continue
            self._add_lin(self._buffpart(name), w)
            gear = self._gear(name)
            cap = Fraction(self.p.caps["regen"][cap_key])
            lo, hi = self._range(gear)
            self._capped_term(gear, cap, lo, hi, w, f"regen.{name}")

    def _term_resists(self) -> None:
        for school in SCHOOLS:
            key = f"SV_{school}"
            w = Fraction(self.w[key]) if key in self.w else self._weight("SV")
            if w == 0:
                continue
            total = self._gear(key).plus(self._buffpart(key))
            lo, hi = self._range(total)
            self._capped_term(total, Fraction(self.p.caps["resist"]), lo, hi, w, f"sv.{school}")

    def _capped_term(self, lin: Lin, cap: Fraction, lo: Fraction, hi: Fraction, w: Fraction, name: str) -> None:
        """``w * min(lin, cap)``: linear when the cap cannot bind, a constant when it always does, else a column."""
        if hi <= cap:
            self._add_lin(lin, w)
        elif lo >= cap:
            self.const += w * cap
        else:
            r = self._new(name, None, cap)
            row = {r: ONE}
            for col, coef in lin.terms.items():
                row[col] = row.get(col, ZERO) - coef
            self._row(f"{name}.max", row, None, lin.const)
            self._add_obj(r, w)

    # -- weapons ------------------------------------------------------------------------------------------------

    def _term_weapons(self) -> None:
        w = self._weight("DMG")
        if w == 0:
            return
        setup = self.setup or "stick"
        if self._capture:  # (the coefficients are those of a level: LevelPrograms.program_for adds them)
            self._weapon_cols = [(col, group.lower(), item) for col, group, item in self.item_cols if group in WEAPON_GROUPS]
            return
        for col, group, item in self.item_cols:
            if group in WEAPON_GROUPS:
                hand = group.lower()
                index = wp.damage_index_exact(
                    item, hand, setup, self.haste_assumed, dw_factor=self.p.dw_factor, ranged_factor=self.p.ranged_factor,
                    swing_factor=wp.swing_factor_of(self.p), level=self.p.level,
                )
                if index:
                    self._add_obj(col, w * index)

    def _term_procs(self) -> None:
        """The procs of the hands that swing (:mod:`trioforge.model.procs`): ``DMG x value / 600`` for the proc a hand counts, with no haste factor (so it is part of the base
        objective of every haste level), the off hand's by the dual-wield factor.

        A hand counts one proc, the best its item can: its own below the socket tier, the best of its own and the ones it can host from it. While no proc a hosted column can count has a Lore
        item among its sources the hands do not meet, and the proc is a constant on the column. A Lore item is one copy (see the module docstring of :mod:`trioforge.model.procs`): the copy a
        kit wears is no donor, and one copy supplies one hand. When a hosted proc has Lore sources the program has, for each hand, a binary for every way a proc can be counted there: ``proc.n[e,hand]``
        (the proc ``e`` of an item that carries it, which is the copy that is worn), ``proc.f[e,hand]`` (``e`` taken from a donor that has a second copy, which nothing blocks) and
        ``proc.l[e,hand,k]`` (``e`` taken from the Lore item ``k``, for the columns that have no donor with a second copy), with the rows ``proc.host.<kind>[...]`` (a way counts only if a column that can
        take ``e`` that way stands in the hand), ``proc.one[hand]`` (one proc a hand), ``proc.worn[e,hand,k]`` (``proc.l`` and the columns of ``k`` in any place at most one: a worn copy is no donor) and
        ``proc.copies[k]`` (the dual-wield hands take at most one proc from the one copy of ``k``). The stick, the bow setup and the range place score no proc, and nothing is added for a build whose
        damage weight is 0."""
        table, w = self.opts.procs, self._weight("DMG")
        if table is None or w == 0 or self.legacy is not None or self.setup not in ("1h-shield", "2h", "dw"):
            return
        hands = HANDS if self.setup == "dw" else HANDS[:1]
        factor = {"PRIMARY": ONE, "SECONDARY": fm.fr(self.p.dw_factor)}
        swinging: dict[str, list[tuple[int, ItemVec]]] = {hand: [] for hand in hands}
        for col, group, item in self.item_cols:
            if group in hands and wp.damage_index_exact(item, group.lower(), self.setup, 0, dw_factor=self.p.dw_factor, ranged_factor=self.p.ranged_factor, level=self.p.level):  # (the stance's factor leaves 0 at 0)
                swinging[group].append((col, item))  # (the item swings here)
        counts = {hand: [(col, item, table.candidates(item, hand)) for col, item in swinging[hand]] for hand in hands}  # (the procs a hand can need: after the first that nothing blocks, none is ever better)
        # a hosted proc whose sources include a Lore item ties the program to the kit (the Lore rule: a worn copy is no donor; one copy supplies one hand): only then does it need binaries
        lored = any(
            table.copies(key) < 2
            for hand in hands for _, item, entries in counts[hand] for entry in entries
            if entry.effect not in table.natives(item) for key in table.sources(item, hand, entry.effect)
        )  # fmt: skip
        if not lored:
            for hand in hands:  # (no Lore source: the hands are independent, and each column carries the best proc its item can count there)
                for col, _, entries in counts[hand]:
                    if entries:
                        self._add_obj(col, w * factor[hand] * Fraction(entries[0].value) / PER_MINUTE_TO_INDEX)
            return
        by_key: dict[str, list[int]] = {}
        for col, _, item in self.item_cols:
            by_key.setdefault(item.key, []).append(col)  # (every column of an item, in any place: a Lore donor that is worn there is no donor)
        flags: list[int] = []
        lone: dict[str, list[int]] = {}  # the flags that take the proc from the one copy of a Lore item, by item (both hands)
        for hand in hands:
            native: dict[str, list[int]] = {}  # the effect: the columns of the hand whose item carries it
            plain: dict[str, list[int]] = {}  # the effect: the columns that can host it from a donor with a second copy
            lore: dict[tuple[str, str], list[int]] = {}  # (effect, Lore donor): the columns whose only donors of it are Lore items
            for col, item, entries in counts[hand]:
                own = table.natives(item)
                for entry in entries:
                    if entry.effect in own:
                        native.setdefault(entry.effect, []).append(col)
                        continue
                    found = table.sources(item, hand, entry.effect)
                    if any(table.copies(key) >= 2 for key in found):
                        plain.setdefault(entry.effect, []).append(col)
                    else:
                        for key in found:
                            lore.setdefault((entry.effect, key), []).append(col)
            mine: list[int] = []
            kinds = [("n", e, "", cols) for e, cols in native.items()] + [("f", e, "", cols) for e, cols in plain.items()] + [("l", e, key, cols) for (e, key), cols in lore.items()]
            for kind, effect, key, cols in sorted(kinds, key=lambda found: (found[1], found[0], found[2])):
                label = f"{effect},{hand}" + (f",{key}" if key else "")
                y = self._new(f"proc.{kind}[{label}]", 0, 1, integer=True)
                flags.append(y)
                mine.append(y)
                self._add_obj(y, w * factor[hand] * table.by_id[effect].value / PER_MINUTE_TO_INDEX)
                self._row(f"proc.host.{kind}[{label}]", {y: ONE, **{col: -ONE for col in cols}}, None, 0)
                if kind == "l":
                    lone.setdefault(key, []).append(y)
                    if key in by_key:  # a Lore donor that the kit wears is not free: the flag and the columns of the item at most one
                        self._row(f"proc.worn[{label}]", {y: ONE, **{col: ONE for col in by_key[key]}}, None, 1)
            if len(mine) > 1:
                self._row(f"proc.one[{hand}]", {y: ONE for y in mine}, None, 1)
        if self.setup == "dw":
            for key, found in sorted(lone.items()):
                if len(found) > 1:  # (the one copy of a Lore item supplies one hand: the flags of the two hands that take a proc from it)
                    self._row(f"proc.copies[{key}]", {y: ONE for y in found}, None, 1)
        if flags:
            self.info["binaries"]["proc"] = len(flags)

    # -- the legacy curves ---------------------------------------------------------------------------------------

    def _term_legacy_curves(self) -> None:
        """The explicit curves of the legacy objective: ``factor x curve(total of the attribute)`` each."""
        if self.legacy is None:
            return
        for n, curve in enumerate(self.legacy.curves):
            if curve.factor == 0:
                continue
            conv = self._curve(self._total(curve.attr), curve.breaks, curve.slopes, f"legacy.{curve.attr}.{n}")
            self._add_lin(conv.lin, curve.factor)

    # -- the arrays ----------------------------------------------------------------------------------------------

    def _finish(self) -> Milp:
        n = len(self.names)
        c = np.zeros(n)
        for col, coef in self.obj.items():
            c[col] = float(coef)
        col_lb = np.array([-INF if v is None else float(v) for v in self.lb])
        col_ub = np.array([INF if v is None else float(v) for v in self.ub])
        start, index, value, row_lb, row_ub = _csr(self.rows)
        a = Csr(start, index, value, (len(self.rows), n))
        self.info.update(rows=len(self.rows), cols=n, haste_assumed=self.haste_assumed)
        if self.opts.haste_floor is not None:
            self.info["haste_floor"] = self.opts.haste_floor
        if self.opts.haste_exact:
            self.info["haste_exact"] = True
        return Milp(
            c=c, A=a, row_lb=row_lb, row_ub=row_ub, col_lb=col_lb, col_ub=col_ub,
            integrality=np.array(self.integer, dtype=np.int8), const=float(self.const),
            colmap={col: (group, item.key) for col, group, item in self.item_cols}, index=dict(self.index),
            names=list(self.names), item_cols=tuple(self.item_cols), buff_cols=dict(self.buff_cols), profile=self.p,
            items=tuple(self.items), setup=self.setup, buffset=self.buffset, haste_assumed=self.haste_assumed,
            options=self.opts, info=self.info, row_names=list(self.row_names),
        )
