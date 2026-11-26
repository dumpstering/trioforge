"""The weapon procs of a trio, as the weapon term counts them.

A proc adds to the **weapon index** of the hand that swings it (:mod:`trioforge.model.weapons`). The index of a swing is the damage per tenth of a second; a proc
that lands ``ppm`` times a minute for ``D`` damage-equivalents each is ``ppm x D / 600`` of the same unit (a minute is 600 tenths), so one damage point a second from
a proc is worth exactly what one damage point a second from a swing is, and procs inherit the weapon weight of the build (the Tank's factor of the rules and the
zero of the builds that score no weapon among them). **A proc has no haste factor**: procs are paced by the minute, not by the swing, so the swing's index keeps
the ``1 + haste/100`` and the proc's does not. The off hand counts a proc by the dual-wield factor (a judgment: how the off hand paces a proc is not measured).

What a proc is worth, ``value = ppm x D``, is decided by :mod:`trioforge.effects.score` from the effect records of the catalog and the rules; this module holds only
what the model needs once the values are known: the effects with their value and their donors (each with the Lore flag of its item). It imports nothing of the effects layer,
so that the evaluator and the builder can use it.

Which proc a weapon counts
==========================

* **Below the socket tier** (``socket_tier``, the rule ``tier.socket_open`` for procs: +4) only an item's **own** proc works. An item with several own procs counts its
  best by value.
* **At or above it** any proc can be moved from a donor onto a like item, and the weapon counts the **best by value of the procs it can host, its own included**:
  one proc a hand, never a sum (whether a native and a socketed proc both fire is not known). A donor can be hosted by an item when

  - the host shares a slot with the donor,
  - a class of the trio can use both,
  - and a donor that fits only the primary hand (a two-hander, or an item whose one slot is the primary) is hosted in the primary hand itself.

  These are the rules of :func:`trioforge.effects.plan._fit`, written out again here. The donor of an effect that is recorded for a host is its own item when the host is
  a donor of the effect (a native proc moves nothing), else the donor with the smallest item key among those that can be hosted. Entries are ordered by value, then by
  the donor's key and the effect's id, so that the solver's record, the evaluator's and a rerun's name the same donor.
* **Two hands** couple only through the physical copies that supply a proc, and **one copy supplies one hand**, whichever proc it is and whatever the tiers of the two hands. The
  **sources** of a hand for an effect (:meth:`ProcTable.sources`) are the item keys whose copy can supply it: a native proc has one, its own item (the copy that is worn: it does
  not take another donor's copy of the effect in its place), a hosted one has every donor the item can host. A Lore item is one copy and any other item two
  (:meth:`ProcTable.copies`). Two hands count procs (the same or two) only if two distinct copies can supply them: the pair of sources must be two keys, or one key with two
  copies. That fails exactly when both hands have one and the same source, a Lore item (the copy a hand wears or has been given is never also the other hand's). The rule is the
  same at every tier. It is conservative where it could be exact in one case: a hand whose item carries the effect keeps its own copy, so it never frees that copy for the other
  hand by taking another donor's. :meth:`ProcTable.candidates` gives a hand item the procs that the best pair can need: the other hand's choice blocks a proc of this hand only
  when both have the same one Lore item as their only source, so, in the order of value, the best proc of each such item and the first proc that cannot be blocked (and no
  other: a proc behind one that is blocked by the same item, or behind one that is never blocked, is never the best that is allowed). That is two procs when the best proc has
  two sources, and as many as there are Lore items behind the best procs when each has one;
  :meth:`ProcTable.best` takes the best pair that the copies allow and names, for each hand, a source that really supplies it. The pair is exactly the best pair of
  all the procs the two items can count.
* **The Lore rule.** A Lore item is one copy, and **the copy a kit wears is the copy it wears**: a Lore item that is worn anywhere in the kit (in a hand, an Any place, the range place or any other
  place) is not a donor for a hand it is not in. Its own proc still counts in the hand that wears it (a native proc is the copy that is worn). The table does not know the kit, so :meth:`ProcTable.best`
  and :meth:`ProcTable.sources` are given ``worn``, the keys of the Lore donors that the kit wears (the evaluator gives them: :func:`trioforge.model.formulas.evaluate`); the two hands' own items are
  always counted as worn. A proc is **blockable** for an item when every source it could be hosted from is a Lore item (a native proc and a proc with a plain donor are not: a plain item has two
  copies, and the rule names Lore items), and :meth:`ProcTable.candidates` lists the procs of a hand best first up to and including the first one that nothing can block, since a blocked proc
  leaves the next one in its place and the first that cannot be blocked is always there.

Where a proc counts is the caller's: a hand that swings (the primary hand in the one-hand, two-hand and dual-wield setups, the off hand in dual wield) and nowhere
else (not in an Any place, not under the stick or the bow, not in the range place).
"""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, NamedTuple

__all__ = ["PER_MINUTE_TO_INDEX", "ProcDonor", "ProcEffect", "ProcEntry", "ProcTable", "RecordedProcs", "from_doc", "record", "to_doc"]

HANDS = ("PRIMARY", "SECONDARY")
#: a minute is 600 tenths of a second: ``procs a minute x damage / 600`` is damage per tenth of a second, the unit of the weapon index
PER_MINUTE_TO_INDEX = 600
NATIVE, HOSTED = "n", "h"


class ProcEntry(NamedTuple):
    """One proc a hand can count: ``value`` (procs a minute times the damage-equivalent of one), the effect's id and name, the item key of its ``donor`` and the ``mode``,
    ``"n"`` (native: the donor is the host itself) or ``"h"`` (hosted: moved from another item)."""

    value: Fraction
    effect: str
    name: str
    donor: str
    mode: str


@dataclass(frozen=True)
class ProcEffect:
    """A proc effect worth ``value`` (more than 0)."""

    id: str
    name: str
    value: Fraction


@dataclass(frozen=True)
class ProcDonor:
    """An item that carries the effect ``effect``: its key, slots, the classes of the trio that can use it, whether it fits the primary hand only and whether it is a Lore
    item (one copy exists; any other item can be had twice)."""

    effect: str
    key: str
    slots: frozenset[str]
    classes: frozenset[str]
    primary_only: bool = False
    lore: bool = False


@dataclass(frozen=True)
class ProcTable:
    """The procs of a trio: ``effects`` with their value, ``donors`` (every item that carries one of them and can be worn by a class of the trio) and
    ``socket_tier`` (the tier from which a proc can be moved). ``trio`` are the class codes."""

    trio: tuple[str, ...]
    socket_tier: int
    effects: tuple[ProcEffect, ...]
    donors: tuple[ProcDonor, ...]
    memo: dict[Any, tuple[ProcEntry, ...]] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        ids = [e.id for e in self.effects]
        if len(set(ids)) != len(ids):
            raise ValueError("an effect is in the table twice")
        for e in self.effects:
            if not e.value > 0:
                raise ValueError(f"effect {e.id}: a value above 0, not {e.value!r}")
        known = set(ids)
        for d in self.donors:
            if d.effect not in known:
                raise ValueError(f"donor {d.key} carries {d.effect}, which is not in the table")
        object.__setattr__(self, "effects", tuple(sorted(self.effects, key=lambda e: e.id)))
        object.__setattr__(self, "donors", tuple(sorted(self.donors, key=lambda d: (d.effect, d.key))))
        object.__setattr__(self, "trio", tuple(self.trio))

    @functools.cached_property
    def by_id(self) -> dict[str, ProcEffect]:
        return {e.id: e for e in self.effects}

    @functools.cached_property
    def _donors_of(self) -> dict[str, tuple[ProcDonor, ...]]:
        out: dict[str, list[ProcDonor]] = {}
        for d in self.donors:
            out.setdefault(d.effect, []).append(d)
        return {k: tuple(v) for k, v in out.items()}

    @functools.cached_property
    def _lore(self) -> dict[str, bool]:
        return {d.key: d.lore for d in self.donors}

    @functools.cached_property
    def lore_keys(self) -> frozenset[str]:
        """The keys of the donors that are Lore items (the rule of a worn copy names these)."""
        return frozenset(key for key, lore in self._lore.items() if lore)

    @functools.cached_property
    def _own(self) -> dict[str, frozenset[str]]:
        out: dict[str, set[str]] = {}
        for d in self.donors:
            out.setdefault(d.key, set()).add(d.effect)
        return {k: frozenset(v) for k, v in out.items()}

    def __bool__(self) -> bool:
        return bool(self.effects)

    def hosted(self, item: Any) -> bool:
        """Whether ``item`` is at a tier from which a proc can be moved onto it."""
        return item.tier >= self.socket_tier

    def _can_host(self, donor: ProcDonor, item: Any, hand: str) -> bool:
        if donor.primary_only and not (hand == "PRIMARY" and "PRIMARY" in item.slots):
            return False
        if not donor.slots & item.slots:
            return False
        return any(c in donor.classes and c in item.classes for c in self.trio)

    def _every(self, item: Any, hand: str) -> tuple[ProcEntry, ...]:
        """Every proc ``item`` can count in ``hand``, best first (the procs it can host and its own, from the socket tier; its own below it)."""
        if hand not in HANDS:
            raise ValueError(f"a hand is PRIMARY or SECONDARY, not {hand!r}")
        hosted = self.hosted(item)
        memo_key = (item.key, item.slots, item.classes, hosted, hand)
        found = self.memo.get(memo_key)
        if found is not None:
            return found
        own = self._own.get(item.key, frozenset())
        made: list[ProcEntry] = []
        for e in self.effects:
            if e.id in own:
                made.append(ProcEntry(e.value, e.id, e.name, item.key, NATIVE))
            elif hosted:
                keys = [d.key for d in self._donors_of.get(e.id, ()) if self._can_host(d, item, hand)]
                if keys:
                    made.append(ProcEntry(e.value, e.id, e.name, min(keys), HOSTED))
        made.sort(key=lambda m: (-m.value, m.donor, m.effect))
        result = tuple(made)
        self.memo[memo_key] = result
        return result

    def entries(self, item: Any, hand: str) -> tuple[ProcEntry, ...]:
        """The procs ``item`` can count in ``hand`` (``"PRIMARY"`` or ``"SECONDARY"``), best first: below the socket tier its own best one (at most one entry), at or
        above it the best two by value of the procs it can host, its own included (see the module docstring)."""
        every = self._every(item, hand)
        return every[:2] if self.hosted(item) else every[:1]

    def every(self, item: Any, hand: str) -> tuple[ProcEntry, ...]:
        """Every proc ``item`` can count in ``hand``, best first, whatever the kit wears (its own procs; from the socket tier also the procs it can host)."""
        return self._every(item, hand)

    def natives(self, item: Any) -> frozenset[str]:
        """The ids of the effects the item itself carries (its own procs: the copy that is worn)."""
        return self._own.get(item.key, frozenset())

    def blockable(self, item: Any, hand: str, effect: str) -> bool:
        """Whether a worn Lore item could take ``effect`` from ``item`` in ``hand``: it is hosted (not the item's own) and every source it has is a Lore item. A native proc, and a proc a
        plain item can give, are never blocked."""
        if effect in self._own.get(item.key, frozenset()):
            return False
        found = self.sources(item, hand, effect)
        return bool(found) and all(self.copies(key) < 2 for key in found)

    def candidates(self, item: Any, hand: str) -> tuple[ProcEntry, ...]:
        """The procs ``item`` can count in ``hand`` whatever its tier and whatever the kit wears, best first, that the best pair with the other hand can need: every proc up to and including
        the first one that nothing can block (:meth:`blockable`), since a proc that a worn Lore copy blocks leaves the next one in its place, and the first that cannot be blocked is always there.
        It is what :meth:`best` chooses among (:meth:`entries` gives the best two, or one below the socket tier, which is what a hand counts when nothing else is asked), and with it
        :meth:`best` finds the best pair of all the procs the two items can count."""
        key = (item.key, item.slots, item.classes, self.hosted(item), hand, "candidates")
        found = self.memo.get(key)
        if found is None:
            chosen: list[ProcEntry] = []
            for entry in self._every(item, hand):
                chosen.append(entry)
                if not self.blockable(item, hand, entry.effect):
                    break
            found = self.memo[key] = tuple(chosen)
        return found

    def copies(self, key: str) -> int:
        """How many physical copies of the item ``key`` can be had: 1 for a Lore item, 2 for any other."""
        return 1 if self._lore.get(key, False) else 2

    def sources(self, item: Any, hand: str, effect: str, worn: frozenset[str] | set[str] = frozenset()) -> tuple[str, ...]:
        """The item keys whose copy can supply ``effect`` to ``item`` in ``hand``, in the order a record names them: the item's own key alone when it carries the effect
        (a native proc is the copy that is worn), else the keys of the donors it can host (the smallest first; none below the socket tier) that are not a Lore item the kit wears
        (``worn``: the keys of the Lore items worn anywhere in the kit; a plain donor has a second copy and is never left out)."""
        if effect in self._own.get(item.key, frozenset()):
            return (item.key,)
        if not self.hosted(item):
            return ()
        return tuple(sorted({d.key for d in self._donors_of.get(effect, ()) if self._can_host(d, item, hand) and not (d.lore and d.key in worn)}))

    def source_sets(self, item: Any, hand: str) -> dict[str, tuple[str, ...]]:
        """``{effect id: sources}`` for every effect ``item`` can count in ``hand`` (see :meth:`sources`): what a pruning compares between two items of a dual-wield pool,
        since an item whose sources for every effect include another's can stand in for it whatever the other hand takes."""
        return {entry.effect: self.sources(item, hand, entry.effect) for entry in self._every(item, hand)}

    def supply(
        self, primary: Any, secondary: Any, first: str, second: str, worn: frozenset[str] | set[str] = frozenset()
    ) -> tuple[str, str] | None:
        """``(source of the main hand, source of the off hand)`` when two distinct physical copies can supply the effects ``first`` (main hand) and ``second`` (off hand), else
        None: the first source of the main hand that leaves a copy for the off hand, then the first source of the off hand that is not the copy the main hand uses (one key may
        supply both only when it has two copies). ``worn`` is as in :meth:`sources`."""
        for mine in self.sources(primary, "PRIMARY", first, worn):
            for theirs in self.sources(secondary, "SECONDARY", second, worn):
                if mine != theirs or self.copies(mine) >= 2:
                    return mine, theirs
        return None

    def best(
        self, primary: Any | None, secondary: Any | None, factor: Any, worn: frozenset[str] | set[str] = frozenset()
    ) -> tuple[ProcEntry | None, ProcEntry | None]:
        """The proc each hand counts: ``primary`` and ``secondary`` are the items that swing in the two hands (None: the hand swings nothing), ``factor`` the off hand's
        share, ``worn`` the keys of the Lore items the kit wears anywhere (the module docstring has the rule of a worn copy; the two hands' own items count as worn whether they are listed
        or not). The best pair by ``value + factor x value`` among the procs of the two hands (or none) that their sources allow, where two hands that both count a proc need two distinct
        copies to supply them (:meth:`supply`; the module docstring has the rule, which holds at every tier), and each hand's entry names a source that really supplies it. The first of
        equal pairs in the order of the procs (best first) wins. The procs looked through are every proc of a hand (:meth:`_every`), best first, and the search over the off hand stops as soon as
        no later proc can make more than the best pair found: for every kit that can be worn it is the best pair of the :meth:`candidates` (a proc after the first that nothing can block
        is never better than it), and the browser's port looks through them the same way."""
        factor = Fraction(factor)
        lore = self.lore_keys
        blocked = frozenset(worn) & lore | frozenset(item.key for item in (primary, secondary) if item is not None and item.key in lore)
        main = tuple(e for e in self._every(primary, "PRIMARY") if self.sources(primary, "PRIMARY", e.effect, blocked)) if primary is not None else ()
        off = tuple(e for e in self._every(secondary, "SECONDARY") if self.sources(secondary, "SECONDARY", e.effect, blocked)) if secondary is not None else ()
        top: Fraction | None = None
        best: tuple[ProcEntry | None, ProcEntry | None] = (None, None)
        for a in (*main, None):
            for b in (*off, None):
                total = (a.value if a else Fraction(0)) + (factor * b.value if b else Fraction(0))
                if top is not None and total <= top:
                    break  # (the procs of the off hand come best first: no later one makes more)
                chosen_a, chosen_b = a, b
                if a is not None and b is not None:
                    supplied = self.supply(primary, secondary, a.effect, b.effect, blocked)
                    if supplied is None:
                        continue
                    chosen_a = a._replace(donor=supplied[0], mode=NATIVE if supplied[0] == primary.key else HOSTED)
                    chosen_b = b._replace(donor=supplied[1], mode=NATIVE if supplied[1] == secondary.key else HOSTED)
                elif a is not None:  # (one hand counts a proc: its source is the first one the kit leaves free, never a Lore item that the kit wears)
                    source = self.sources(primary, "PRIMARY", a.effect, blocked)[0]
                    chosen_a = a._replace(donor=source, mode=NATIVE if source == primary.key else HOSTED)
                elif b is not None:
                    source = self.sources(secondary, "SECONDARY", b.effect, blocked)[0]
                    chosen_b = b._replace(donor=source, mode=NATIVE if source == secondary.key else HOSTED)
                top, best = total, (chosen_a, chosen_b)
        return best


def _text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def to_doc(table: ProcTable) -> dict[str, Any]:
    """The table as the bundle of the browser holds it (``procs``): ``{"socket_tier", "effects", "donors"}``. An effect is ``[id, name, value]`` with the value as a reduced ``"p/q"`` text
    (the browser reads exact numbers), by id; a donor is ``[effect, key, slots, classes, primary_only, lore]`` with the slots and the classes of the trio sorted and the two flags as 0 or 1, by
    effect and key. The trio is the bundle's own, and is not repeated."""
    return {
        "socket_tier": table.socket_tier,
        "effects": [[e.id, e.name, _text(Fraction(e.value))] for e in table.effects],
        "donors": [[d.effect, d.key, sorted(d.slots), sorted(d.classes), int(d.primary_only), int(d.lore)] for d in table.donors],
    }


_TEXT = re.compile(r"[1-9][0-9]*/[1-9][0-9]*")


def from_doc(doc: Any, trio: Sequence[str]) -> ProcTable:
    """The table of ``trio`` from the document :func:`to_doc` writes: the Python reader that the browser's port is held to. ``ValueError`` for anything else (a value that is not a reduced
    ``"p/q"`` text above zero, a flag that is not 0 or 1, a donor of an effect the table lacks or an effect twice, a field more or fewer)."""
    if not isinstance(doc, dict) or set(doc) != {"socket_tier", "effects", "donors"}:
        raise ValueError("procs: an object with socket_tier, effects and donors")
    tier = doc["socket_tier"]
    if isinstance(tier, bool) or not isinstance(tier, int) or tier < 0:
        raise ValueError("procs.socket_tier: a whole number")
    if not isinstance(doc["effects"], list) or not isinstance(doc["donors"], list):
        raise ValueError("procs: effects and donors are lists")
    effects = []
    for row in doc["effects"]:
        if not (isinstance(row, list) and len(row) == 3 and isinstance(row[0], str) and isinstance(row[1], str) and isinstance(row[2], str) and _TEXT.fullmatch(row[2])):
            raise ValueError(f"procs.effects: [id, name, value] with the value a reduced p/q text above zero, not {row!r}")
        numerator, denominator = (int(part) for part in row[2].split("/"))
        if math.gcd(numerator, denominator) != 1:
            raise ValueError(f"procs.effects: {row[2]!r} is not reduced")
        effects.append(ProcEffect(row[0], row[1], Fraction(numerator, denominator)))
    donors = []
    for row in doc["donors"]:
        if not (
            isinstance(row, list) and len(row) == 6 and isinstance(row[0], str) and isinstance(row[1], str)
            and all(isinstance(part, list) and all(isinstance(one, str) for one in part) for part in (row[2], row[3]))
            and all(flag in (0, 1) and not isinstance(flag, bool) for flag in row[4:])
        ):  # fmt: skip
            raise ValueError(f"procs.donors: [effect, key, slots, classes, primary_only, lore], not {row!r}")
        donors.append(ProcDonor(row[0], row[1], frozenset(row[2]), frozenset(row[3]), bool(row[4]), bool(row[5])))
    return ProcTable(tuple(trio), tier, tuple(effects), tuple(donors))


def record(entry: ProcEntry | None, hand: str) -> list[Any] | None:
    """The record of a counted proc as the results keep it: ``[hand, effect name, donor item key, mode, value]`` (hand ``P`` or ``S``, ``value`` to four decimals: what
    the proc is worth before the build's weight and before the off hand's factor), None for a hand that counts none."""
    return None if entry is None else [hand[0], entry.name, entry.donor, entry.mode, round(float(entry.value), 4)]


class RecordedProcs:
    """The procs that a result file says its kit counted (:func:`record`), standing in for a table where the table is not at hand: the check of the exchange rates of a kit
    (:mod:`trioforge.checks.exchange`) values the kit again, with one more point of a stat on one of its items, and the procs do not change with the stats. ``best`` answers
    what the file says for the hands that swing, whichever items they hold (a table would choose them again; the record is of a kit that already has its answer)."""

    def __init__(self, records: Any) -> None:
        self._entries: dict[str, ProcEntry] = {}
        for hand, name, donor, mode, value in records:
            self._entries["PRIMARY" if hand == "P" else "SECONDARY"] = ProcEntry(Fraction(str(value)), name, name, donor, mode)

    def best(
        self, primary: Any | None, secondary: Any | None, factor: Any, worn: frozenset[str] | set[str] = frozenset()
    ) -> tuple[ProcEntry | None, ProcEntry | None]:
        return (
            self._entries.get("PRIMARY") if primary is not None else None,
            self._entries.get("SECONDARY") if secondary is not None else None,
        )
