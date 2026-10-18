"""The buff engine: which long buffs a trio has, how they stack, and what the solver has to choose.

Input is the beneficial-spell file the pipeline writes (``derived/client/spells-l50.json``, ``-l55.json``;
see :mod:`trioforge.sources.client_spells`). A spell record there holds the classes that get it, its target
type, its duration, the effect slots with their values at the file's level, and the 148/149 stacking
commands. Three steps turn that into something a MILP can take.

1. :func:`own_buffs` picks the buffs a trio casts on itself, and :func:`group_preset` the 13 common group
   buffs. Both return :class:`Buff` objects, each reduced to a vector over :data:`COMPONENTS` (the stats,
   AC, HP, mana, END, regen, the five resists and spell haste: the things the model scores). Two more presets
   widen the group for the browser's toggles: :func:`enchanter_preset` is the haste line of an Enchanter in the
   group (the best haste an Enchanter can cast on others at the level: 60% at level 50), and :func:`raid_preset`
   is the whole raid: the 13 group buffs plus every long buff that some class can cast on someone else. A raid
   holds everything the group set holds, and it goes through the same stacking engine under the same slot limit,
   so the best kit in a raid can never be worth less than in the group.
2. :func:`exclusions` says which pairs cannot stand together. The rules, all of them symmetric:

   * the same slot number with the same effect (``slot1/spa4``). Effect 79 (instant hit points) and the
     limit effects never collide;
   * two spell hastes: only the best one counts (``haste``);
   * two illusions (``illusion``);
   * a 148 or 149 stacking command: a spell with the command blocks or overwrites another spell that holds
     the named effect (``base``) in the named slot (``limit``) with a value below the threshold (``max``),
     reported as ``cmd148/slot1/spa4``. How the game reads a threshold of 1000 or more is untested:
     ``decode="raw"`` takes the number as stored (1067 is above every value, so the command matches any
     buff in that slot), ``decode="mod1000"`` takes it modulo 1000 (1067 means 67). A command with no
     threshold, which is what the committed spell files hold today (the reader drops ``max``), matches
     any value in the slot.

3. :func:`resolve` turns a list of buffs into a :class:`BuffSet` for the solver:

   * ``always_on`` buffs are in some optimal kit whatever the gear. A buff is always on when it costs
     nothing and is worth at least as much, in every component, as any rivals of it that could stand
     together. Its rivals are then ``dropped`` (``blocked``), and the buffs that only they blocked are
     free in turn, so this repeats until nothing changes;
   * ``dropped`` also holds a buff that a rival beats in every component and whose own rivals the winner
     shares (``dominated``): swapping it for the winner is always allowed, so it is never needed;
   * what is left is ``optional``: one binary each in the MILP, with ``conflicts`` (pairs of exclusive
     buffs, ``x_i + x_j <= 1``) and ``cliques`` (a cover of those pairs by groups of buffs that all
     exclude each other, ``sum x <= 1``, a tighter row for the same pairs);
   * ``cardinality`` is the limit on active buffs (``buffs.max_slots``), reported only when it can bind:
     more buffs can stand together than it allows. Then no buff is always on, because which ones to
     keep is part of the choice, and the row is ``sum x <= cardinality`` over ``optional``.

Every reduction rests on one fact: the score is non-decreasing in every component of the totals (weights are
non-negative and every curve rises or stays flat), so a buff that is at least as good everywhere is never
worse. The tests check the whole resolution against brute force over random pools, conflicts and limits.
Where a step would need an expensive exact answer (a large independent-set search) it gives up on the
reduction instead of guessing: the result is then larger, never wrong.

Not modelled: spell haste of kinds 98 and 119 (no buff of 10 minutes or more carries them, which a test
pins), the client's spell stacking groups (unverified in EQL), the rank of a spell, bard songs (they last
seconds; the song toggle lives in the browser) and a spell file of another level than the scenario's.
"""

from __future__ import annotations

import functools
import itertools
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from trioforge.classes import CLASS_CODES
from trioforge.sources.client_spells import LIMIT_SPA

__all__ = [
    "COMPONENTS",
    "DECODES",
    "DEFAULT_LONG_MINUTES",
    "OTHER_TARGETS",
    "PRESET_NAMES",
    "SCHOOLS",
    "SELF_TARGETS",
    "STAT_NAMES",
    "Buff",
    "BuffSet",
    "Dropped",
    "enchanter_preset",
    "exclusion_reason",
    "exclusions",
    "group_preset",
    "own_buffs",
    "raid_preset",
    "resolve",
]

Number = int | float

# ---- vocabulary --------------------------------------------------------------------------------------

STAT_NAMES = (
    "AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG",
)  # fmt: skip
SCHOOLS = ("FIRE", "COLD", "MAGIC", "POISON", "DISEASE")
COMPONENTS = STAT_NAMES + SCHOOLS + ("HASTE",)
_INDEX = {name: position for position, name in enumerate(COMPONENTS)}
_HASTE = _INDEX["HASTE"]

# effect id (SPA) -> the component it feeds; 11 (attack speed) and 111 (all resists) are handled in code
SPA_COMPONENT = {
    0: "HPREG", 1: "AC", 2: "ATK", 4: "STR", 5: "DEX", 6: "AGI", 7: "STA", 8: "INT", 9: "WIS", 10: "CHA",
    15: "MANAREG", 46: "FIRE", 47: "COLD", 48: "POISON", 49: "DISEASE", 50: "MAGIC", 69: "HP", 97: "MANA",
    189: "ENDREG", 190: "END",
}  # fmt: skip
SPA_HASTE, SPA_ILLUSION, SPA_ROOT, SPA_INSTANT_HP, SPA_ALL_RESISTS = 11, 58, 99, 79, 111
STACK_BLOCK, STACK_OVERWRITE = 148, 149
SCORED_SPA = frozenset(SPA_COMPONENT) | {SPA_HASTE, SPA_ALL_RESISTS}
_NO_COLLISION = frozenset({SPA_INSTANT_HP, STACK_BLOCK, STACK_OVERWRITE, 254}) | LIMIT_SPA

# Target types of a spell that can land on its caster: self (6), a single target (5, 51), a group (3, 41, 43,
# the bards' 40) and a group member (56). Pets (14) and the rest are left out.
SELF_TARGETS = frozenset({3, 5, 6, 40, 41, 43, 51, 56})
#: the same without self (6): the targets of a buff that lands on somebody other than its caster, which is what a group
#: or raid member gets from the class that casts it
OTHER_TARGETS = SELF_TARGETS - {6}
TICK_SECONDS = 6
#: how long a buff must last to count as long when no rules object is given: the value of ``buffs.min_duration_minutes``
#: (a test keeps the two equal)
DEFAULT_LONG_MINUTES = 10

PRESET_NAMES = (
    "Talisman of Altuna", "Strength", "Dexterity", "Agility", "Stamina", "Infusion of Spirit", "Alacrity",
    "Spirit of Bih`Li", "Chloroplast", "Symbol of Naltron", "Resolution", "Shield of Words", "Clarity",
)  # fmt: skip

DECODES = ("raw", "mod1000")

# giving up: the number of recursive calls an exact independent-set search may make before the reduction is skipped
_SEARCH_BUDGET = 200_000


# ---- one buff ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Buff:
    """One spell as the model sees it.

    ``vec`` is the amount per component of :data:`COMPONENTS` (spell haste is the attack speed over 100, and
    0 for a slow). ``effects`` lists every effect slot as ``(slot, spa, value)`` (the stacking commands and
    the limit effects are not effects) and ``commands`` the 148/149 commands as ``(kind, effect, slot,
    threshold)``, the threshold ``None`` when the file does not give it. ``source`` is ``"own"`` for a buff the
    trio casts and ``"preset"`` for a group buff.
    """

    id: int
    name: str
    classes: tuple[tuple[str, int], ...]
    target: int
    duration_ticks: int | None
    permanent: bool
    effects: tuple[tuple[int, int, Number | None], ...]
    commands: tuple[tuple[int, int, int, Number | None], ...]
    vec: tuple[Number, ...]
    illusion: bool
    source: str = "own"

    @classmethod
    def from_spell(cls, record: Mapping[str, Any], *, source: str = "own") -> Buff:
        """Read a spell record of ``derived/client/spells-l*.json``.

        Raises ``ValueError`` when an effect the model scores has no value (the file's formula was unknown).
        """
        effects: list[tuple[int, int, Number | None]] = []
        amounts = [0] * len(COMPONENTS)
        illusion = False
        for effect in record["effects"]:
            spa, slot, value = effect["spa"], effect["slot"], effect.get("value")
            if spa in LIMIT_SPA:
                continue
            effects.append((slot, spa, value))
            illusion = illusion or spa == SPA_ILLUSION
            if spa not in SCORED_SPA:
                continue
            if value is None:
                raise ValueError(f"spell {record['id']}: effect {spa} in slot {slot} has no value")
            if spa == SPA_HASTE:
                amounts[_HASTE] = max(amounts[_HASTE], value - 100)
            elif spa == SPA_ALL_RESISTS:
                for school in SCHOOLS:
                    amounts[_INDEX[school]] += value
            else:
                amounts[_INDEX[SPA_COMPONENT[spa]]] += value
        commands = tuple(
            (
                int(entry["spa"]),
                int(entry["base"]),
                int(entry["limit"]),
                entry.get("max"),
            )
            for entry in record.get("stacking", ())
        )
        classes = record["classes"]
        return cls(
            id=int(record["id"]),
            name=record["name"],
            classes=tuple((code, classes[code]) for code in CLASS_CODES if code in classes),
            target=record["target"],
            duration_ticks=record["duration_ticks"],
            permanent=bool(record["permanent"]),
            effects=tuple(effects),
            commands=commands,
            vec=tuple(amounts),
            illusion=illusion,
            source=source,
        )

    @functools.cached_property
    def keys(self) -> tuple[tuple[int, int], ...]:
        """The (slot, effect) pairs that can collide with another buff's."""
        return tuple(sorted({(slot, spa) for slot, spa, _ in self.effects if spa not in _NO_COLLISION}))

    @property
    def stats(self) -> dict[str, Number]:
        return {name: self.vec[_INDEX[name]] for name in STAT_NAMES}

    @property
    def sv(self) -> dict[str, Number]:
        return {name: self.vec[_INDEX[name]] for name in SCHOOLS}

    @property
    def haste(self) -> Number:
        return self.vec[_HASTE]


@dataclass(frozen=True)
class Dropped:
    """A buff the resolution left out, why, and the buff that decided it (``None`` when none did).

    ``reason`` is ``"duplicate"`` (a later copy of a spell already in the list), ``"inert"`` (nothing the
    model scores), ``"dominated"`` (``by`` is at least as good everywhere and takes its place) or ``"blocked"``
    (``by`` is always on and excludes it).
    """

    id: int
    name: str
    reason: str
    by: int | None


# ---- which spells are own buffs ------------------------------------------------------------------------


def _records(spells: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> Sequence[Mapping[str, Any]]:
    return spells["spells"] if isinstance(spells, Mapping) else spells


def exclusion_reason(record: Mapping[str, Any], trio: Sequence[str], level: int, min_minutes: Number) -> str | None:
    """Why ``record`` is not an own buff of ``trio`` at ``level``, or ``None`` when it is.

    The first test that fails names the reason: ``class`` (no trio class gets it by ``level``), ``discipline``,
    ``item-benefit``, ``illusion-spell`` (a spell named ``Illusion:``, whose availability is unverified; the
    forms that carry stats stay), ``temperance`` (the Temperance line), ``target`` (cannot land on the caster,
    such as pet-only buffs), ``duration`` (shorter than ``min_minutes``), ``root`` (a rooting form),
    ``unknown-formula`` (a scored effect has no value) and ``inert`` (nothing the model scores).
    """
    classes = record["classes"]
    if not any(0 < classes.get(code, 0) <= level for code in trio):
        return "class"
    name = record["name"]
    if "Discipline" in name:
        return "discipline"
    if name.startswith("Item Benefit"):
        return "item-benefit"
    if name.startswith("Illusion:"):
        return "illusion-spell"
    if "Temperance" in name:
        return "temperance"
    if record["target"] not in SELF_TARGETS:
        return "target"
    if not record["permanent"] and (record["duration_ticks"] or 0) * TICK_SECONDS < min_minutes * 60:
        return "duration"
    if any(effect["spa"] == SPA_ROOT for effect in record["effects"]):
        return "root"
    if any(effect["spa"] in SCORED_SPA and effect.get("value") is None for effect in record["effects"]):
        return "unknown-formula"
    if not any(Buff.from_spell(record).vec):
        return "inert"
    return None


def own_buffs(trio: Sequence[str], level: int, spells: Any, rules: Any) -> list[Buff]:
    """The buffs a character of ``trio`` casts on itself at ``level``, by spell id.

    One class of the trio gets the spell by ``level``; it is permanent or lasts at least
    ``buffs.min_duration_minutes``; it can land on the caster. Disciplines, pet-only buffs, rooting forms, the
    Temperance line and the ``Illusion:`` spells are left out (see :func:`exclusion_reason`); a form with an
    illusion effect stays and carries ``illusion``. ``spells`` is the derived file (a mapping with ``level`` and
    ``spells``) or its list of records; a file of another level than ``level`` is refused, because its values
    and durations belong to its own level.
    """
    unknown = [code for code in trio if code not in CLASS_CODES]
    if unknown:
        raise ValueError(f"not class codes: {', '.join(map(str, unknown))}")
    if isinstance(spells, Mapping) and spells.get("level") not in (None, level):
        raise ValueError(f"the spell file is for level {spells['level']}, not level {level}")
    minutes = rules.get("buffs.min_duration_minutes", level)
    return [
        Buff.from_spell(record, source="own")
        for record in sorted(_records(spells), key=lambda record: record["id"])
        if exclusion_reason(record, trio, level, minutes) is None
    ]


def group_preset(spells: Any, *, level: int | None = None) -> list[Buff]:
    """The 13 common group buffs (:data:`PRESET_NAMES`), in that order, with ``source="preset"``.

    A name is matched exactly as the client spells it (the backtick in ``Spirit of Bih`Li`` included); the
    lowest id wins when a name repeats. A name the file does not have at all is an error naming it, as the
    list is meant to match the file. A spell that no class gets by ``level`` is skipped: the group could not
    cast it yet. ``level`` defaults to the file's, and a bare list of records is not limited by level.
    """
    if level is None and isinstance(spells, Mapping):
        level = spells.get("level")
    by_name: dict[str, Mapping[str, Any]] = {}
    for record in sorted(_records(spells), key=lambda record: record["id"]):
        by_name.setdefault(record["name"], record)
    missing = [name for name in PRESET_NAMES if name not in by_name]
    if missing:
        raise ValueError(f"preset spells not in the spell file: {', '.join(missing)}")
    chosen = [by_name[name] for name in PRESET_NAMES]
    if level is not None:
        chosen = [record for record in chosen if min(record["classes"].values(), default=level + 1) <= level]
    return [Buff.from_spell(record, source="preset") for record in chosen]


def _check_level(level: Any) -> None:
    if type(level) is not int or level < 1:
        raise ValueError(f"level must be a whole number of at least 1, not {level!r}")


def _long_minutes(rules: Any, level: int) -> Number:
    """The length of a long buff: ``buffs.min_duration_minutes`` of ``rules``, else :data:`DEFAULT_LONG_MINUTES`."""
    return DEFAULT_LONG_MINUTES if rules is None else rules.get("buffs.min_duration_minutes", level)


def enchanter_preset(spells: Any, level: int, *, rules: Any = None) -> list[Buff]:
    """The "Enchanter in group" haste line at ``level``: the best haste an Enchanter casts on others, as a list of one.

    Among the spells that an Enchanter gets by ``level``, that can land on somebody other than the caster
    (:data:`OTHER_TARGETS`), that are long (``buffs.min_duration_minutes`` of ``rules``, else
    :data:`DEFAULT_LONG_MINUTES`) and that the model scores, the one with the highest spell haste wins; equal hastes go
    to the lower spell id. The client file gives 60% at level 50 (Swift Like the Wind). The list is empty when no
    Enchanter haste exists at the level yet, and the buff has ``source="preset"``, ready to join the trio's own buffs
    and the group preset in :func:`resolve`. Its values and durations are the file's own, as for
    :func:`group_preset`: the file should be the one of ``level``. ``ValueError`` for a level that is not a whole
    number from 1.
    """
    _check_level(level)
    minutes = _long_minutes(rules, level)
    best: Buff | None = None
    for record in sorted(_records(spells), key=lambda record: record["id"]):
        if record["target"] not in OTHER_TARGETS or exclusion_reason(record, ("ENC",), level, minutes) is not None:
            continue
        buff = Buff.from_spell(record, source="preset")
        if buff.haste > 0 and (best is None or buff.haste > best.haste):
            best = buff
    return [] if best is None else [best]


def raid_preset(spells: Any, level: int, *, rules: Any = None) -> list[Buff]:
    """The buffs a full raid can add to a trio's own: the 13 group buffs, then every other long buff of any class that
    can land on someone else.

    The group preset comes first, in its own order (:func:`group_preset`, with its errors for a file that lacks a
    name); the rest follow by spell id. A buff is added when some class gets it by ``level``, it is castable on others
    (:data:`OTHER_TARGETS`), it is long and the model scores it, and :func:`exclusion_reason` does not turn it away
    (disciplines, item benefits, ``Illusion:`` spells, the Temperance line, rooting forms, pet-only buffs). Every buff
    has ``source="preset"``. Because it holds the whole group preset and, by the same tests, the Enchanter line
    (:func:`enchanter_preset`), merging it with the trio's own buffs through :func:`resolve` under the slot limit lets
    the solver choose any set that the group set allows: the value of the best kit in a raid is never below the group's.
    ``ValueError`` for a level that is not a whole number from 1.
    """
    _check_level(level)
    group = group_preset(spells, level=level)
    taken = {buff.id for buff in group}
    minutes = _long_minutes(rules, level)
    extra = [
        Buff.from_spell(record, source="preset")
        for record in sorted(_records(spells), key=lambda record: record["id"])
        if record["id"] not in taken
        and record["target"] in OTHER_TARGETS
        and exclusion_reason(record, CLASS_CODES, level, minutes) is None
    ]
    return [*group, *extra]


# ---- stacking --------------------------------------------------------------------------------------------


def _check_decode(decode: str) -> None:
    if decode not in DECODES:
        raise ValueError(f"unknown decode {decode!r}; use one of {', '.join(DECODES)}")


def _threshold(raw: Number | None, decode: str) -> Number | None:
    if raw is None or decode == "raw" or raw < 1000:
        return raw
    return raw % 1000


def exclusions(a: Buff, b: Buff, *, decode: str = "raw") -> tuple[str, ...]:
    """The reasons ``a`` and ``b`` cannot be active together, sorted; empty when they stack.

    See the module docstring for the rules and for ``decode``, the reading of thresholds of 1000 and above.
    """
    _check_decode(decode)
    reasons = {f"slot{slot}/spa{spa}" for slot, spa in set(a.keys) & set(b.keys)}
    if a.haste > 0 and b.haste > 0:
        reasons.add("haste")
    if a.illusion and b.illusion:
        reasons.add("illusion")
    for owner, other in ((a, b), (b, a)):
        for kind, effect, slot, raw in owner.commands:
            limit = _threshold(raw, decode)
            for other_slot, spa, value in other.effects:
                if other_slot == slot and spa == effect and (limit is None or value is None or value < limit):
                    reasons.add(f"cmd{kind}/slot{slot}/spa{effect}")
    return tuple(sorted(reasons))


# ---- the resolved set -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BuffSet:
    """What the solver gets: fixed buffs, the buffs it chooses among, and the rows that bind them.

    ``always_on`` and ``optional`` are sorted by spell id. ``conflicts`` are pairs of ids of ``optional`` buffs
    that exclude each other (the lower id first), ``conflict_reasons`` says why, ``cliques`` covers every pair by
    groups of buffs that all exclude each other. ``cardinality`` is ``None``, or the most ``optional`` buffs that
    may be active (and then ``always_on`` is empty). ``dropped`` is sorted by id.
    """

    always_on: tuple[Buff, ...]
    optional: tuple[Buff, ...]
    conflicts: tuple[tuple[int, int], ...]
    conflict_reasons: tuple[tuple[tuple[int, int], tuple[str, ...]], ...]
    cliques: tuple[tuple[int, ...], ...]
    cardinality: int | None
    dropped: tuple[Dropped, ...]

    def reasons(self, a: int, b: int) -> tuple[str, ...]:
        """Why buffs ``a`` and ``b`` of ``optional`` exclude each other; empty when they do not."""
        pair = (a, b) if a < b else (b, a)
        return next((why for key, why in self.conflict_reasons if key == pair), ())

    def totals(self, chosen: Iterable[int] = ()) -> dict[str, Any]:
        """The totals of the always-on buffs plus the ``chosen`` ones (ids of ``optional``).

        The result has the 15 stat names, ``sv`` (the five resist schools) and ``haste`` (the best spell haste
        among the active buffs, as only one counts). Raises ``KeyError`` for an id that is not optional.
        """
        optional = {buff.id: buff for buff in self.optional}
        fixed = {buff.id for buff in self.always_on}
        active = list(self.always_on)
        for buff_id in dict.fromkeys(chosen):
            if buff_id not in fixed:
                active.append(optional[buff_id])
        amounts: list[Number] = [0] * len(COMPONENTS)
        haste: Number = 0
        for buff in active:
            for position, amount in enumerate(buff.vec):
                if position == _HASTE:
                    haste = max(haste, amount)
                else:
                    amounts[position] += amount
        result: dict[str, Any] = {name: amounts[_INDEX[name]] for name in STAT_NAMES}
        result["sv"] = {name: amounts[_INDEX[name]] for name in SCHOOLS}
        result["haste"] = haste
        return result

    def is_legal(self, chosen: Iterable[int]) -> bool:
        """Whether ``chosen`` (ids of ``optional``) has no excluded pair and fits under ``cardinality``."""
        picked = set(chosen)
        known = {buff.id for buff in self.optional}
        if not picked <= known:
            raise KeyError(sorted(picked - known))
        if self.cardinality is not None and len(picked) > self.cardinality:
            return False
        return not any(a in picked and b in picked for a, b in self.conflicts)

    def iter_legal(self) -> Iterator[tuple[int, ...]]:
        """Every legal choice among the ``optional`` buffs, as sorted id tuples. Exponential: for tests."""
        order = [buff.id for buff in self.optional]
        rivals: dict[int, set[int]] = {i: set() for i in order}
        for a, b in self.conflicts:
            rivals[a].add(b)
            rivals[b].add(a)
        limit = self.cardinality
        taken: list[int] = []

        def walk(position: int) -> Iterator[tuple[int, ...]]:
            if position == len(order):
                yield tuple(taken)
                return
            yield from walk(position + 1)
            candidate = order[position]
            if (limit is None or len(taken) < limit) and rivals[candidate].isdisjoint(taken):
                taken.append(candidate)
                yield from walk(position + 1)
                taken.pop()

        yield from walk(0)


# ---- the resolution ---------------------------------------------------------------------------------------


class _SearchGaveUp(Exception):
    """An exact search went over its budget."""


def _components(nodes: frozenset[int], rivals: Mapping[int, set[int]]) -> list[frozenset[int]]:
    parts, seen = [], set()
    for start in sorted(nodes):
        if start in seen:
            continue
        stack, part = [start], {start}
        seen.add(start)
        while stack:
            for other in rivals[stack.pop()] & nodes:
                if other not in seen:
                    seen.add(other)
                    part.add(other)
                    stack.append(other)
        parts.append(frozenset(part))
    return parts


def _heaviest_independent(weights: Mapping[int, Number], rivals: Mapping[int, set[int]]) -> Number | None:
    """The largest total weight of buffs that can stand together, or ``None`` if the search gave up."""
    calls = 0
    memo: dict[frozenset[int], Number] = {}

    def best(nodes: frozenset[int]) -> Number:
        nonlocal calls
        if not nodes:
            return 0
        if nodes in memo:
            return memo[nodes]
        calls += 1
        if calls > _SEARCH_BUDGET:
            raise _SearchGaveUp
        parts = _components(nodes, rivals)
        if len(parts) > 1:
            value = sum(best(part) for part in parts)
        else:
            pivot = max(nodes, key=lambda node: (len(rivals[node] & nodes), -node))
            if not rivals[pivot] & nodes:
                value = sum(weights[node] for node in nodes)
            else:
                value = max(best(nodes - {pivot}), weights[pivot] + best(nodes - {pivot} - rivals[pivot]))
        memo[nodes] = value
        return value

    try:
        return best(frozenset(weights))
    except _SearchGaveUp:
        return None


def _clique_cover_size(nodes: Iterable[int], rivals: Mapping[int, set[int]]) -> int:
    """An upper bound on how many buffs can stand together: the size of a greedy cover by cliques."""
    cliques: list[set[int]] = []
    for node in sorted(nodes):
        for clique in cliques:
            if clique <= rivals[node]:
                clique.add(node)
                break
        else:
            cliques.append({node})
    return len(cliques)


def _more_than(nodes: frozenset[int], rivals: Mapping[int, set[int]], limit: int) -> bool:
    """Whether more than ``limit`` of the buffs can stand together (``True`` when that cannot be told)."""
    if len(nodes) <= limit or _clique_cover_size(nodes, rivals) <= limit:
        return False
    exact = _heaviest_independent(dict.fromkeys(nodes, 1), rivals)
    return exact is None or exact > limit


def _beats(a: int, b: int, vectors: Mapping[int, tuple[Number, ...]]) -> bool:
    """``a`` is at least as good as ``b`` in every component; of two equal buffs the lower id wins."""
    first, second = vectors[a], vectors[b]
    return all(x >= y for x, y in zip(first, second, strict=True)) and (first != second or a < b)


def _beats_every_team(
    a: int, rivals_of_a: set[int], rivals: Mapping[int, set[int]], vectors: Mapping[int, tuple[Number, ...]]
) -> bool:
    """``a`` costs nothing and, in every component, is worth at least as much as any rivals that stand together."""
    mine = vectors[a]
    if any(amount < 0 for amount in mine):
        return False
    for position, own in enumerate(mine):
        weights = {node: vectors[node][position] for node in rivals_of_a if vectors[node][position] > 0}
        if not weights or sum(weights.values()) <= own:
            continue
        team = _heaviest_independent(weights, rivals)
        if team is None or team > own:
            return False
    return True


def _edge_clique_cover(nodes: Sequence[int], rivals: Mapping[int, set[int]]) -> tuple[tuple[int, ...], ...]:
    """Cliques that together contain every pair of buffs that exclude each other, grown greedily."""
    covered: set[tuple[int, int]] = set()
    cliques = []
    for a in nodes:
        for b in sorted(rivals[a]):
            if b < a or (a, b) in covered:
                continue
            clique = [a, b]
            for c in sorted(rivals[a] & rivals[b]):
                if all(c in rivals[member] for member in clique):
                    clique.append(c)
            clique.sort()
            covered.update(itertools.combinations(clique, 2))
            cliques.append(tuple(clique))
    return tuple(cliques)


def resolve(
    buffs: Iterable[Buff], rules: Any = None, *, max_slots: int | None = None, decode: str = "raw"
) -> BuffSet:
    """Turn buffs into the :class:`BuffSet` the solver takes; see the module docstring for the method.

    The first copy of a spell id is kept. ``max_slots`` is the limit on active buffs; when it is not given it is
    ``buffs.max_slots`` of ``rules`` (and there is no limit without either). ``decode`` is the reading of 148/149
    thresholds of 1000 and above (:data:`DECODES`). The result does not depend on the order of ``buffs``.
    """
    _check_decode(decode)
    if max_slots is None and rules is not None:
        max_slots = rules.get("buffs.max_slots")
    if max_slots is not None and (isinstance(max_slots, bool) or not isinstance(max_slots, int) or max_slots < 0):
        raise ValueError(f"max_slots must be a whole number of zero or more, not {max_slots!r}")

    pool: dict[int, Buff] = {}
    dropped: list[Dropped] = []
    for buff in buffs:
        if buff.id in pool:
            dropped.append(Dropped(buff.id, buff.name, "duplicate", None))
        elif not any(buff.vec):
            dropped.append(Dropped(buff.id, buff.name, "inert", None))
        else:
            pool[buff.id] = buff
    order = sorted(pool)
    vectors = {i: pool[i].vec for i in order}
    rivals: dict[int, set[int]] = {i: set() for i in order}
    why: dict[tuple[int, int], tuple[str, ...]] = {}
    for i, j in itertools.combinations(order, 2):
        reasons = exclusions(pool[i], pool[j], decode=decode)
        if reasons:
            rivals[i].add(j)
            rivals[j].add(i)
            why[(i, j)] = reasons

    alive = set(order)

    # A buff that a rival beats everywhere, whose other rivals the winner shares, is never needed.
    reduced = True
    while reduced:
        reduced = False
        for b in sorted(alive):
            near = rivals[b] & alive
            winner = next(
                (a for a in sorted(near) if _beats(a, b, vectors) and (rivals[a] & alive) - {b} <= near), None
            )
            if winner is not None:
                alive.discard(b)
                dropped.append(Dropped(b, pool[b].name, "dominated", winner))
                reduced = True
                break

    binds = max_slots is not None and _more_than(frozenset(alive), rivals, max_slots)
    always: list[int] = []
    if not binds:
        # A buff worth more than any rivals that could stand together is in some optimal kit: take it, drop them.
        settled = False
        while not settled:
            settled = True
            for a in sorted(alive):
                near = rivals[a] & alive
                if _beats_every_team(a, near, rivals, vectors):
                    always.append(a)
                    alive -= {a, *near}
                    dropped.extend(Dropped(n, pool[n].name, "blocked", a) for n in sorted(near))
                    settled = False
                    break

    optional = sorted(alive)
    pairs = tuple((i, j) for i in optional for j in sorted(rivals[i] & alive) if i < j)
    return BuffSet(
        always_on=tuple(pool[i] for i in sorted(always)),
        optional=tuple(pool[i] for i in optional),
        conflicts=pairs,
        conflict_reasons=tuple((pair, why[pair]) for pair in pairs),
        cliques=_edge_clique_cover(optional, {i: rivals[i] & alive for i in optional}),
        cardinality=max_slots if binds else None,
        dropped=tuple(sorted(dropped, key=lambda d: (d.id, d.reason))),
    )
