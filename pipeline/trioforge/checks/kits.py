"""The kit checks: a scoreboard of what a player would call obviously right in the kits of a results folder.

::

    PYTHONPATH=pipeline python -m trioforge.checks.kits --results build/results [--json out.json] [--gate] [--expected cases.json] [--no-named]

It reads the precompute output of every trio (:mod:`trioforge.checks.results` says which scenario of a trio is its kit: the default race, the best weapon setup, the wiki
pool, the own buffs; one kit for each trio, role and tier), runs every check on every kit, and prints, for each check, how many kits pass, fail or are not applicable
(n.a.) by role and tier, the ten worst trios, and the named cases (:mod:`trioforge.checks.named`). The same command run before and after a change of the solver shows
the change. The output holds counts and item names, never the path of the folder, and is the same for the same folder byte for byte.

It exits 0, unless ``--gate`` is given and a gate check fails (then 1), or an input cannot be read (2). **A gate is only as good as what it read**, so ``--gate`` also exits 2,
with the reason on one line, when it cannot trust the results: no kit was read, a trio gave none (the default race has no scenario), or the results were made with other rules
than this checkout's (:meth:`trioforge.checks.results.Results.rules_mismatch`). Without ``--gate`` the same facts are printed as ``warning:`` lines and written to the JSON. A shard
that lacks a total the checks read, an item the table lacks, an item the model cannot read and a race the tables do not know are errors with exit 2, not tracebacks.

**It is a scoreboard, not a ranking of players' opinions, and not a set of targets.** Each check is one property that is plain on its face. A kit that passes every check is
not therefore the best kit, and a kit that fails one may be the best the objective can do; the numbers say how often, and whether a change of the solver moved them. Two kinds of
check say so in their name: the **gates** (K2 and K3.robe) are the properties a player would call wrong outright, and the **scoreboard only** checks
(:data:`SCOREBOARD_ONLY`) are measurements with no threshold to reach. K1 and K6 are the plainest of these: the objective of the solver is the value of the kit, and a kit with
a high share of mana-pool points or a low share of the strength the pool could give is no defect in itself; they are there to show what the kits are made of. The checks:

==============  ===================================================================================================================================
``K1.attr``     in the tank, melee and archer builds, the share of WIS and INT among the attribute points of the kit's items (STR STA AGI DEX WIS INT CHA);
                scoreboard only
``K1.pool``     the share of the stat points that count for the objective that go to the mana pool (WIS, INT and mana); scoreboard only
``K2``          a pure caster item in a tank, melee or archer kit: an item whose only positive stats are WIS, INT, CHA, mana or mana regeneration (a weapon, with
                its damage, and an item with worn haste are not pure caster items; weight and resists are ignored); the number of distinct items behind
                the failures and the five worn most are printed
``K3``          armour for a tank: in the tank and shield caster builds of a trio with a class of the heaviest armour, the AC of the chest, legs, arms, head, hands and feet
                of the kit as a share of the best AC the trio can wear in that slot at that tier (:data:`K3_MIN_RATIO`). A piece counts for a slot worn in
                its own place **or in an Any place** (the two Any places take any item and a swap leaves the score as it was), and the best AC a trio can wear
                leaves out the pieces whose stats besides AC are only caster stats
``K3.robe``     the best chest piece of such a kit (by AC, a tie to the piece that is no robe) is a robe
``K3.robe_worn``  a robe is worn anywhere in such a kit; scoreboard only
``K4``          one family everywhere: the item-name stems that are sets, and the share of all kits that wear two pieces or more of each (top ten)
``K5``          a bow in the Range slot (or an Any place) of the melee and archer kits of a trio with a Ranger: ``K5.bow`` is any item of the Archery
                skill, ``K5.windstriker`` is the quest bow of the Ranger test of Plane of Sky. The Bow setup scores a bow in the Range place on its own damage per delay
``K6``          strength for melee: in the melee build, the strength of the kit (the naked character's and the gear's, under the stat cap) against the
                most that the pool could give, an item that is not Lore worn in every place that takes it as the solver wears it; scoreboard only
``K7``          resists: the five resists of the kit, as the sheet counts them, summed; scoreboard only
``K8``          soft cap: in the tank and shield caster builds, whether the sheet AC of the kit reaches the soft cap of the trio, and by how much it is past it or short of it;
                scoreboard only
``K9``          the named cases, from public feedback: the kit of each build at +4 and +10 with the result of the checks and K10 (all builds)
``K10``         exchange rates (:mod:`trioforge.checks.exchange`): what one more point of each stat is worth to the objective of the kit, by the project's
                own evaluator; for the named cases and in the JSON; scoreboard only
``K11``         stamina parked under the knee: the STA total of the kit (race and class, buffs and gear) is within :data:`KNEE_BAND` points under
                ``stats.knee``, which fails the kit; the tank and shield caster builds; scoreboard only
``K12``         the weapon setup of a tank kit: its best setup is 1H + shield (the count of passes over the kits is the share of tank kits that hold a shield; not applicable where the
                evidence level has no 1H + shield setup for the Tank at all); scoreboard only
==============  ===================================================================================================================================

**The builds** (:data:`trioforge.model.roles.ROLES`: tank, shield, melee, ranged, castertank, caster) each get the checks that are about them: K1 and K2 the tank, melee and
archer builds, K3, K3.robe, K3.robe_worn, K8, K11 and K12 (tank only) the tank and the shield caster, K5 the melee and archer builds, K6 the melee build, K7 every build.
The checker still **reads** results of the earlier roles (the Balanced build of a release before the builds is one: its kits take only the checks that apply to every build),
so that a release before the builds can stand beside one after it.

The gates are ``K2`` and ``K3.robe``. They fail today, so the release build and CI do not run ``--gate``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trioforge.checks import expected as expected_module
from trioforge.checks import exchange
from trioforge.checks.families import ARMOUR_SLOTS, MIN_SET_ITEMS, armour_classes, is_robe, set_stems
from trioforge.checks.results import PLACE_NAMES, ItemTable, Kit, Results, ResultsError
from trioforge.data import races as races_module
from trioforge.data.jsonio import load_strict
from trioforge.model import roles as roles_module
from trioforge.model import tables as tables_module
from trioforge.model.buffs import assumes_spell_haste, buffsets
from trioforge.model.items import SLOT_INSTANCES, ItemVec

__all__ = [
    "CHECKS",
    "GATES",
    "K3_MIN_RATIO",
    "KNEE_BAND",
    "SCOREBOARD_ONLY",
    "WINDSTRIKER",
    "Check",
    "Context",
    "Outcome",
    "Scoreboard",
    "main",
    "set_pieces",
]

FORMAT = 2
PASS, FAIL, NA, INFO = "pass", "fail", "na", "info"
K3_MIN_RATIO = 0.5  # DECISIONS 2026-11-18: the least that a tank kit's AC in an armour slot may be of the best AC the trio can wear there
KNEE_BAND = 2  # DECISIONS 2026-11-18: points under stats.knee within which the stamina of a kit is parked
NON_CASTING_ROLES = ("tank", "melee", "ranged")  # the builds of K1 and K2: they do not cast for their damage
TANK_ROLES = ("tank", "shield")  # the builds in plate in front: the armour checks (K3, K8) and the stamina check (K11) are about them
MELEE_ROLES = ("melee",)
BOW_ROLES = ("melee", "ranged")  # the builds that can score a bow: not a tank, not a caster
SHIELD_SETUP_ROLES = ("tank",)  # the builds K12 reads the weapon setup of
ATTRIBUTES = ("STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA")
POOL_STATS = ("WIS", "INT", "MANA")  # what feeds the mana pool, and the pool itself
POINT_STATS = ("AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK")  # the stats that are counted as stat points
PURE_CASTER_STATS = frozenset({"WIS", "INT", "CHA", "MANA", "MANAREG"})
RESISTS = ("fire", "cold", "magic", "poison", "disease")
ARCHERY = "archery"  # the weapon skill of a bow
WINDSTRIKER = "Windstriker"  # the bow that the players of a Ranger expect in the Range slot (a public item; the only one these checks name)
GATES = ("K2", "K3.robe")
#: checks that are counted and shown but that no change of the solver is held to; K10 is a table of the named cases and the JSON, not a count
SCOREBOARD_ONLY = ("K1.attr", "K1.pool", "K3.robe_worn", "K4", "K6", "K7", "K8", "K10", "K11", "K12")
#: the order of the builds in the output: the earlier release's Balanced first (a results folder made before the builds is still read), then the builds in their own order
ROLE_ORDER = ("balanced", "tank", "shield", "melee", "ranged", "castertank", "caster")
STANDARD_TIERS = (0, 4, 10)  # the tiers every trio has; the others (the milestone trio's +1 to +9) are shown as one row, "other", in the text
WORST = 10  # trios listed for each check
TOP_ITEMS = 5  # pure caster items listed for K2
TOP_STEMS = 10
RANGE = "RANGE"
CHEST = "CHEST"


@dataclass(frozen=True)
class Check:
    """One line of the scoreboard: ``kind`` is ``rule`` (a kit passes or fails) or ``info`` (a number; the scoreboard shows its distribution)."""

    id: str
    title: str
    sentence: str
    kind: str
    roles: tuple[str, ...] | None  # the roles it applies to; None: every role (it is then n.a. only where a trio lacks what it asks, a Ranger for K5)
    value: str  # what the value of an outcome is
    measure: bool = True  # whether the value is a measure whose distribution is worth showing (False: it is 0 or 1)


CHECKS: tuple[Check, ...] = (
    Check("K1.attr", "WIS and INT among the attributes of a non-casting build",
          "In a tank, melee or archer kit the share of WIS and INT among the attribute points of its items (STR, STA, AGI, DEX, WIS, INT, CHA), as a distribution.",
          "info", NON_CASTING_ROLES, "WIS + INT over the attribute points"),
    Check("K1.pool", "Mana-pool points on a non-casting build",
          "In a tank, melee or archer kit the share of the stat points that count for the objective that go to the mana pool (WIS, INT and mana), as a distribution.",
          "info", NON_CASTING_ROLES, "share of the pool points"),
    Check("K2", "Pure caster item in a tank, melee or archer kit",
          "A tank, melee or archer kit wears no item whose only positive stats are WIS, INT, CHA, mana or mana regeneration.",
          "rule", NON_CASTING_ROLES, "pure caster items worn"),
    Check("K3", "Armour for a tank",
          f"In a tank or shield caster kit of a trio with a heaviest-armour class every armour slot has at least {K3_MIN_RATIO:.0%} of the best AC the trio can wear there.",
          "rule", TANK_ROLES, "lowest share over the six slots"),
    *(
        Check(f"K3.{slot}", f"Armour for a tank: {slot.lower()}",
              f"In a tank or shield caster kit of a trio with a heaviest-armour class the {slot.lower()} piece worn there or in an Any place has at least {K3_MIN_RATIO:.0%} of the best AC the trio can wear there.",
              "rule", TANK_ROLES, "share of the best AC")
        for slot in ARMOUR_SLOTS
    ),
    Check("K3.robe", "A robe as a tank chest",
          "In a tank or shield caster kit of a trio with a heaviest-armour class the best chest piece worn, in the chest or an Any place, is not a robe (a piece of casters that lists a cloth class and no heavy class).",
          "rule", TANK_ROLES, "1 for a robe", False),
    Check("K3.robe_worn", "A robe worn anywhere by a tank",
          "In a tank or shield caster kit of a trio with a heaviest-armour class no robe is worn in any place, which is a count of how many kits wear one.",
          "rule", TANK_ROLES, "1 for a robe worn", False),
    Check("K5.bow", "A bow in the Range slot",
          "In a melee or archer kit of a trio with a Ranger a bow (an item of the Archery skill) is worn in the Range slot or an Any place.", "rule", BOW_ROLES, "1 for a bow", False),
    Check("K5.windstriker", f"{WINDSTRIKER} in the Range slot",
          f"In a melee or archer kit of a trio with a Ranger {WINDSTRIKER} is worn in the Range slot or an Any place.", "rule", BOW_ROLES, "1 for the item", False),
    Check("K6", "Strength for melee",
          "In a melee kit the strength of the kit, under the stat cap, as a share of the most that the pool could give.", "info", MELEE_ROLES,
          "share of the best reachable strength"),
    Check("K7", "Resists", "The five resists of the kit, as the sheet counts them, summed.", "info", None, "sum of the five resists"),
    Check("K8", "Soft cap", "In a tank or shield caster kit the sheet AC reaches the soft cap of the trio; the value is how far past it (or short of it, below 0).",
          "rule", TANK_ROLES, "sheet AC less the soft cap"),
    Check("K11", "Stamina parked under the knee",
          f"In a tank or shield caster kit the stamina total (race and class, buffs and gear) is not within {KNEE_BAND} points under the stat knee; the value is the knee less the stamina.",
          "rule", TANK_ROLES, "the knee less the STA total"),
    Check("K12", "A shield in the tank build",
          "In a tank kit the best weapon setup is 1H + shield (the share of the kits that pass is the share of tank kits that hold a shield; a kit of a level that has no 1H + shield setup at all is not applicable).",
          "rule", SHIELD_SETUP_ROLES, "1 for 1H + shield", False),
)  # fmt: skip
BY_ID = {check.id: check for check in CHECKS}
INFO_ONLY = frozenset({"K1.attr", "K1.pool", "K6", "K7"})  # their outcomes are INFO, and they are never counted as a pass or a fail


@dataclass(frozen=True)
class Outcome:
    """What one check says of one kit: ``status`` (pass, fail, na or info), the ``value`` it measured, how ``bad`` it is (higher is worse; None: every failure is as bad as
    another, so no kit is the worst) and the facts that the named cases print."""

    status: str
    value: float | None = None
    bad: float | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


_NA = Outcome(NA)


def _round(value: float | None) -> float | int | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(float(value), 3)


# ---- the context: what a check needs besides the kit --------------------------------------------------------------------------------


class Context:
    """The item table of a results folder with the facts that the checks derive from it once: the armour classes, the set stems, the rules and the race table."""

    def __init__(self, results: Results, *, min_set_items: int = MIN_SET_ITEMS) -> None:
        self.table: ItemTable = results.table
        self.rules = self.table.rules
        self.armour = armour_classes(self.table, min_items=min_set_items)
        self.stems = set_stems(self.table)
        self.cap = int(self.rules.get("stats.hard_cap"))
        self.knee = int(self.rules.get("stats.knee"))
        self.race_data = races_module.load()
        self._relevant: dict[tuple[tuple[str, ...], str], frozenset[str]] = {}
        self._best_ac: dict[tuple[Any, ...], int] = {}
        self._best_gear: dict[tuple[Any, ...], int] = {}
        self._buffsets: dict[tuple[tuple[str, ...], int], Any] = {}
        self.other_rules = results.rules_mismatch() is not None  # (results of other rules: their buffs were chosen under the other flavour of the spell-haste rule)

    def name(self, key: str) -> str:
        return self.table.records[key].name

    def naked(self, kit: Kit) -> dict[str, int]:
        """The attributes of the character before any gear and buff: the race and the three class modifiers."""
        try:
            return races_module.naked_stats(kit.race, kit.trio, self.race_data)
        except ValueError:
            raise ResultsError(f"{kit.slug}: the race {kit.race!r} is not one of the race table (rules/races.json)") from None

    def buff_totals(self, kit: Kit) -> Mapping[str, Any]:
        """The totals of the own buffs of the kit (the ones always on and the optional ones its shard names): ``BuffSet.totals``."""
        key = (kit.trio, kit.level)
        if key not in self._buffsets:
            path = tables_module.REPO / "derived" / "client" / f"spells-l{kit.level}.json"
            try:
                spells = load_strict(path)
                here = assumes_spell_haste(self.rules)
                # the buffs a kit's shard names are from the own buffs of the rule of this checkout; for a folder made with other rules (a release before the spell-haste rule has the
                # spell haste in its sets) the other flavour is tried second. For a folder of the current rules no such fallback: a buff that is not in the set is an error
                flavours = (here, not here) if self.other_rules else (here,)
                self._buffsets[key] = tuple(buffsets(kit.trio, kit.level, spells, self.rules, ("own",), spell_haste=flavour)["own"] for flavour in flavours)
            except (OSError, ValueError) as error:
                raise ResultsError(f"the buffs of {kit.slug} at level {kit.level} cannot be made: {path.name} ({type(error).__name__})") from None
        missing = None
        for buffset in self._buffsets[key]:
            try:
                return buffset.totals(tuple(kit.buff_ids))
            except KeyError as error:
                missing = missing if missing is not None else error.args[0]
        raise ResultsError(f"{kit.slug}: the buff {missing} that its shard names is not one of the own buffs of the trio")

    def relevant(self, trio: tuple[str, ...], role: str) -> frozenset[str]:
        """The stats that count for the objective of a role: those that the weights of the role (:func:`trioforge.model.roles.weights_for`) give a value to, and
        for WIS and INT only the one that the mana of a class of the trio is made of (a trio with no such class gets nothing from it, nor from mana)."""
        found = self._relevant.get((trio, role))
        if found is None:
            weights = roles_module.weights_for(trio, role, self.rules)
            stats: set[str] = set()
            for weight, own in (("AC", ("AC", "AGI")), ("ATK", ("ATK", "STR")), ("HP", ("HP", "STA")), ("END", ("END", "STA")), ("DEX", ("DEX",)), ("CHA", ("CHA",))):
                if weights.get(weight, 0) > 0:
                    stats.update(own)
            if weights.get("MANA", 0) > 0:
                stats.add("MANA")
                for stat, classes in self.rules.get("mana.stat_by_class").items():
                    if set(classes) & set(trio):
                        stats.add(stat)
            found = self._relevant[(trio, role)] = frozenset(stats)
        return found

    @staticmethod
    def is_pure_caster(vec: ItemVec) -> bool:
        """An item whose only positive stats are WIS, INT, CHA, mana or mana regeneration (it has at least one): no AC, HP, STR or other stat, no worn haste and no weapon."""
        positive = {stat for stat, value in vec.stats.items() if value > 0}
        return bool(positive) and positive <= PURE_CASTER_STATS and vec.haste <= 0 and vec.weapon is None

    @staticmethod
    def is_caster_only(vec: ItemVec) -> bool:
        """A piece whose stats besides AC are only caster stats (the pure caster item of K2 with its AC left aside): armour that a tank would not count as the best there is."""
        positive = {stat for stat, value in vec.stats.items() if value > 0 and stat != "AC"}
        return bool(positive) and positive <= PURE_CASTER_STATS and vec.haste <= 0 and vec.weapon is None

    def kind_items(self, kit: Kit, slot: str) -> list[tuple[str, str]]:
        """``(place, key)`` of the pieces of ``slot`` that the kit wears: in the named place of the slot or in an Any place, whichever it is. The two Any places take any item, so a
        swap of an item between the named place and an Any place leaves the kit's score as it was, and no armour check may read the named place alone."""
        return [(place, key) for place, key in kit.worn() if (place == slot or place.startswith("ANY")) and slot in self.table.records[key].slots]

    def best_ac(self, kit: Kit, slot: str) -> int:
        """The most AC that any piece the trio can wear in ``slot`` has at the tier of the kit (0 when there is none): of the solve pool of the kit's view, and not of a piece
        whose stats besides AC are only caster stats."""
        key = (kit.trio, kit.race, kit.evidence, kit.tier, slot)
        if key not in self._best_ac:
            best = 0
            for r in self.table.eligible(kit.trio, kit.race, kit.evidence):
                if slot in r.slots:
                    vec = self.table.vec(r.key, kit.tier)
                    if not self.is_caster_only(vec):
                        best = max(best, vec.stats.get("AC", 0))
            self._best_ac[key] = best
        return self._best_ac[key]

    def best_gear(self, kit: Kit, stat: str) -> int:
        """The most of ``stat`` that gear of the pool could give at the tier of the kit: the best set of items, one for each of the 22 places, an item in any place that its slots
        list and the two Any places open to every item. An item that is not Lore may be worn in every place that takes it, as the solver wears it; a Lore item once. The hands
        are not held to a setup, so it is an upper bound.

        The weight of an element is the stat of its item, whatever the place, so the best set is found by taking elements in order of weight and keeping each that a matching of
        the places can still hold (an augmenting path of a bipartite matching); the search stops when every place that some element could fill is full."""
        key = (kit.trio, kit.race, kit.evidence, kit.tier, stat)
        if key not in self._best_gear:
            elements: list[tuple[int, str, int, list[int]]] = []
            for r in self.table.eligible(kit.trio, kit.race, kit.evidence):
                value = self.table.vec(r.key, kit.tier).stats.get(stat, 0)
                if value > 0:
                    places = [i for i, group in enumerate(SLOT_INSTANCES) if group == "ANY" or group in r.slots]
                    elements.extend((-value, r.key, copy, places) for copy in range(1 if r.lore else len(places)))
            elements.sort(key=lambda element: element[:3])
            fillable = len({place for element in elements for place in element[3]})
            owner: list[int | None] = [None] * len(SLOT_INSTANCES)

            def seat(index: int, seen: set[int]) -> bool:  # the augmenting path of a matching: the greedy order by value is exact for this structure
                for place in elements[index][3]:
                    if place not in seen:
                        seen.add(place)
                        if owner[place] is None or seat(owner[place], seen):
                            owner[place] = index
                            return True
                return False

            total = held = 0
            for index, element in enumerate(elements):
                if held == fillable:
                    break
                if seat(index, set()):
                    total -= element[0]
                    held += 1
            self._best_gear[key] = total
        return self._best_gear[key]

    # ---- the checks ------------------------------------------------------------------------------------------------------------------

    def evaluate(self, kit: Kit) -> dict[str, Outcome]:
        """The outcome of every check (:data:`CHECKS` by id) for one kit."""
        worn = [(place, key, self.table.vec(key, kit.tier)) for place, key in kit.worn()]
        out: dict[str, Outcome] = {}
        out.update(self._k1(kit, worn))
        out["K2"] = self._k2(kit, worn)
        out.update(self._k3(kit))
        out.update(self._k5(kit))
        out["K6"] = self._k6(kit, worn)
        resists = sum(kit.totals[name] for name in RESISTS)
        out["K7"] = Outcome(INFO, resists, -resists, {name: kit.totals[name] for name in RESISTS})
        out["K8"] = self._k8(kit)
        out["K11"] = self._k11(kit, worn)
        out["K12"] = self._k12(kit)
        return out

    def _k1(self, kit: Kit, worn: Sequence[tuple[str, str, ItemVec]]) -> dict[str, Outcome]:
        if kit.role not in NON_CASTING_ROLES:
            return {"K1.attr": _NA, "K1.pool": _NA}
        out = {}
        attributes = Counter()
        for _, _, vec in worn:
            for stat in ATTRIBUTES:
                if vec.stats.get(stat, 0) > 0:
                    attributes[stat] += vec.stats[stat]
        total = sum(attributes.values())
        if total:
            wis_int = attributes["WIS"] + attributes["INT"]
            out["K1.attr"] = Outcome(INFO, wis_int / total, wis_int / total, {"wis_int": wis_int, "attributes": total})
        try:
            counted = self.relevant(kit.trio, kit.role)
        except ValueError:  # a role that the trio is not offered has no weights to read
            return {"K1.attr": out.get("K1.attr", _NA), "K1.pool": _NA}
        points = Counter()
        for _, _, vec in worn:
            for stat in POINT_STATS:
                if stat in counted and vec.stats.get(stat, 0) > 0:
                    points[stat] += vec.stats[stat]
        total = sum(points.values())
        if total:
            pool = sum(points[stat] for stat in POOL_STATS)
            out["K1.pool"] = Outcome(INFO, pool / total, pool / total, {"pool": pool, "points": total})
        return {"K1.attr": out.get("K1.attr", _NA), "K1.pool": out.get("K1.pool", _NA)}

    def _k2(self, kit: Kit, worn: Sequence[tuple[str, str, ItemVec]]) -> Outcome:
        if kit.role not in NON_CASTING_ROLES:
            return _NA
        names = sorted({self.name(key) for _, key, vec in worn if self.is_pure_caster(vec)})
        return Outcome(FAIL if names else PASS, len(names), len(names), {"items": names})

    def _heavy(self, kit: Kit) -> bool:
        return kit.role in TANK_ROLES and bool(set(kit.trio) & self.armour.heavy)

    def _k3(self, kit: Kit) -> dict[str, Outcome]:
        out = {check.id: _NA for check in CHECKS if check.id.startswith("K3")}
        if not self._heavy(kit):
            return out
        ratios: dict[str, float] = {}
        for slot in ARMOUR_SLOTS:
            best = self.best_ac(kit, slot)
            if best <= 0:
                continue
            ac = max((self.table.vec(key, kit.tier).stats.get("AC", 0) for _, key in self.kind_items(kit, slot)), default=0)
            ratios[slot] = ac / best
            out[f"K3.{slot}"] = Outcome(PASS if ratios[slot] >= K3_MIN_RATIO else FAIL, ratios[slot], 1 - ratios[slot], {"ac": ac, "best": best})
        if ratios:
            lowest = min(ratios.values())
            fails = sorted(slot for slot, ratio in ratios.items() if ratio < K3_MIN_RATIO)
            out["K3"] = Outcome(FAIL if fails else PASS, lowest, 1 - lowest, {"failed": fails})
        chests = [self.table.records[key] for _, key in self.kind_items(kit, CHEST)]
        best = max(chests, key=lambda r: (self.table.vec(r.key, kit.tier).stats.get("AC", 0), not is_robe(r.classes, self.armour)), default=None)  # a tie: the piece that is no robe
        robe = best is not None and is_robe(best.classes, self.armour)
        out["K3.robe"] = Outcome(FAIL if robe else PASS, 1 if robe else 0, None, {"chest": best.name if robe else None})
        worn_robe = any(CHEST in self.table.records[key].slots and is_robe(self.table.records[key].classes, self.armour) for _, key in kit.worn())
        out["K3.robe_worn"] = Outcome(FAIL if worn_robe else PASS, 1 if worn_robe else 0, None, {})
        return out

    def _k5(self, kit: Kit) -> dict[str, Outcome]:
        if "RNG" not in kit.trio or kit.role not in BOW_ROLES:
            return {"K5.bow": _NA, "K5.windstriker": _NA}
        items = self.kind_items(kit, RANGE)
        vecs = [self.table.vec(key, kit.tier) for _, key in items]
        bow = any(vec.weapon is not None and (vec.weapon.skill or "").casefold() == ARCHERY for vec in vecs)
        strike = any(self.name(key).casefold() == WINDSTRIKER.casefold() for _, key in items)
        named = "; ".join(self.name(key) for _, key in items) or None
        return {
            "K5.bow": Outcome(PASS if bow else FAIL, int(bow), None, {"range": named}),
            "K5.windstriker": Outcome(PASS if strike else FAIL, int(strike), None, {"range": named}),
        }

    def _k6(self, kit: Kit, worn: Sequence[tuple[str, str, ItemVec]]) -> Outcome:
        if kit.role not in MELEE_ROLES:
            return _NA
        naked = self.naked(kit)["STR"]
        room = max(0, self.cap - naked)
        gear = min(room, sum(vec.stats.get("STR", 0) for _, _, vec in worn))
        best = min(room, self.best_gear(kit, "STR"))
        if best <= 0:
            return _NA
        share = gear / best
        return Outcome(INFO, share, 1 - share, {"naked": naked, "gear": gear, "best": best})

    @staticmethod
    def _k8(kit: Kit) -> Outcome:
        if kit.role not in TANK_ROLES:
            return _NA
        margin = kit.totals["ac"] - kit.softcap
        return Outcome(PASS if margin >= 0 else FAIL, margin, -margin, {"ac": kit.totals["ac"], "softcap": kit.softcap})

    @staticmethod
    def _k12(kit: Kit) -> Outcome:
        if kit.role not in SHIELD_SETUP_ROLES or "1h-shield" not in kit.setups:  # (a level whose pool has no shield, or no one-hander, has no such setup to choose: no fault of the build)
            return _NA
        shield = kit.setup == "1h-shield"
        return Outcome(PASS if shield else FAIL, int(shield), None, {"setup": kit.setup})

    def _k11(self, kit: Kit, worn: Sequence[tuple[str, str, ItemVec]]) -> Outcome:
        if kit.role not in TANK_ROLES:
            return _NA
        naked = self.naked(kit)["STA"]
        buff = int(self.buff_totals(kit).get("STA", 0))
        gear = sum(vec.stats.get("STA", 0) for _, _, vec in worn)
        total = naked + buff + gear
        gap = self.knee - total
        parked = 1 <= gap <= KNEE_BAND
        return Outcome(FAIL if parked else PASS, gap, KNEE_BAND + 1 - gap if parked else None, {"sta": total, "knee": self.knee, "naked": naked, "buff": buff, "gear": gear})


# ---- the scoreboard -----------------------------------------------------------------------------------------------------------------


def _distribution(values: Sequence[float]) -> dict[str, Any] | None:
    """Minimum, 10th percentile, median, 90th percentile and maximum of ``values`` (nearest rank), or None for no value."""
    if not values:
        return None
    ordered = sorted(values)

    def at(fraction: float) -> float | int | None:
        return _round(ordered[int(fraction * (len(ordered) - 1) + 0.5)])

    return {"n": len(ordered), "min": _round(ordered[0]), "p10": at(0.1), "median": at(0.5), "p90": at(0.9), "max": _round(ordered[-1])}


def set_pieces(kit: Kit, stems: Mapping[str, str]) -> dict[str, set[str]]:
    """The distinct items of each set (by stem) that a kit wears: an item worn in two places is one piece. The scoreboard and the named cases (K4) both count by this."""
    pieces: dict[str, set[str]] = defaultdict(set)
    for _, key in kit.worn():
        stem = stems.get(key)
        if stem is not None:
            pieces[stem].add(key)
    return pieces


class Scoreboard:
    """The counts of every check by role and tier, and what the text and the JSON show besides them: the worst trios, the offending items and the sets."""

    def __init__(self, context: Context) -> None:
        self.context = context
        self.kits = 0
        self.trios: set[str] = set()
        self.role_kits: Counter = Counter()
        self.counts: dict[tuple[str, str, int], Counter] = defaultdict(Counter)
        self.values: dict[tuple[str, str, int], list[float]] = defaultdict(list)
        self.worst: dict[str, dict[str, tuple[float, str, int, float | None]]] = defaultdict(dict)
        self.offenders: Counter = Counter()  # pure caster items by name
        self.robes: Counter = Counter()  # the robe that is the best chest piece of a tank kit, by name
        self.robe_cases: list[dict[str, Any]] = []
        self.stem_kits: Counter = Counter()
        self.stem_roles: Counter = Counter()
        self.stem_pieces: dict[str, Counter] = defaultdict(Counter)

    def add(self, kit: Kit, outcomes: Mapping[str, Outcome] | None = None) -> None:
        """Count one kit (the outcomes of ``Context.evaluate`` when not given)."""
        outcomes = self.context.evaluate(kit) if outcomes is None else outcomes
        self.kits += 1
        self.trios.add(kit.slug)
        self.role_kits[kit.role] += 1
        for check_id, outcome in outcomes.items():
            cell = (check_id, kit.role, kit.tier)
            self.counts[cell][outcome.status] += 1
            if outcome.value is not None and outcome.status != NA:
                self.values[cell].append(outcome.value)
            if outcome.bad is not None and outcome.status in (FAIL, INFO):
                old = self.worst[check_id].get(kit.slug)
                if old is None or outcome.bad > old[0]:
                    self.worst[check_id][kit.slug] = (outcome.bad, kit.role, kit.tier, outcome.value)
        for name in outcomes["K2"].detail.get("items", ()):
            self.offenders[name] += 1
        robe = outcomes["K3.robe"]
        if robe.status == FAIL:
            name = robe.detail["chest"]
            self.robes[name] += 1
            self.robe_cases.append({"trio": kit.slug, "tier": kit.tier, "item": name})
        for stem, keys in set_pieces(kit, self.context.stems).items():
            if len(keys) >= 2:
                self.stem_kits[stem] += 1
                self.stem_roles[(stem, kit.role)] += 1
                for key in keys:
                    self.stem_pieces[stem][self.context.name(key)] += 1

    # ---- what is shown ---------------------------------------------------------------------------------------------------------------

    @property
    def roles(self) -> list[str]:
        """The roles of the kits, in the order of :data:`ROLE_ORDER` and then by name."""
        return sorted(self.role_kits, key=lambda role: (ROLE_ORDER.index(role) if role in ROLE_ORDER else len(ROLE_ORDER), role))

    def tiers(self) -> list[int]:
        return sorted({tier for _, _, tier in self.counts})

    def row(self, check_id: str, role: str, tiers: Iterable[int]) -> dict[str, Any]:
        """The counts and the distribution of one check for one role over some tiers."""
        counts, values = Counter(), []
        for tier in tiers:
            counts.update(self.counts.get((check_id, role, tier), Counter()))
            values.extend(self.values.get((check_id, role, tier), ()))
        row: dict[str, Any] = {"kits": sum(counts.values()), "pass": counts[PASS], "fail": counts[FAIL], "na": counts[NA]}
        if check_id in INFO_ONLY:
            row["info"] = counts[INFO]
        dist = _distribution(values)
        if dist is not None:
            row["distribution"] = dist
        return row

    def worst_trios(self, check_id: str) -> list[dict[str, Any]]:
        """The trios whose worst kit is the worst for a check: at most :data:`WORST`, the worst first, a trio once (with the role and tier of its worst kit)."""
        ranked = sorted(self.worst.get(check_id, {}).items(), key=lambda item: (-item[1][0], item[0], item[1][1], item[1][2]))
        return [{"trio": slug, "role": role, "tier": tier, "value": _round(value)} for slug, (_, role, tier, value) in ranked[:WORST]]

    def top_stems(self) -> list[dict[str, Any]]:
        """The ten sets that the most kits wear two pieces or more of (K4), with their share of all kits, by role, and the pieces most worn."""
        ranked = sorted(self.stem_kits.items(), key=lambda item: (-item[1], item[0]))[:TOP_STEMS]
        return [
            {
                "stem": stem, "kits": count, "share": _round(count / self.kits if self.kits else 0),
                "by_role": {role: _round(self.stem_roles[(stem, role)] / self.role_kits[role]) for role in self.roles},
                "pieces": [name for name, _ in sorted(self.stem_pieces[stem].items(), key=lambda piece: (-piece[1], piece[0]))[:4]],
            }
            for stem, count in ranked
        ]  # fmt: skip

    def gates(self) -> dict[str, int]:
        """The number of kits that fail each gate check."""
        return {check_id: sum(c[FAIL] for (cid, _, _), c in self.counts.items() if cid == check_id) for check_id in GATES}

    def document(self) -> dict[str, Any]:
        """Everything the scoreboard holds, as the JSON of ``--json`` (without the named cases, the expected cases and the warnings, which the caller adds)."""
        checks: dict[str, Any] = {}
        for check in CHECKS:
            by_role: dict[str, Any] = {}
            for role in self.roles:
                tiers = {tier: self.row(check.id, role, [tier]) for tier in self.tiers()}
                shown = {str(tier): row for tier, row in tiers.items() if row["kits"] and row["kits"] != row["na"]}
                if shown:
                    by_role[role] = {"all": self.row(check.id, role, self.tiers()), "tiers": shown}
            checks[check.id] = {
                "title": check.title, "sentence": check.sentence, "kind": check.kind, "gate": check.id in GATES, "scoreboard_only": check.id in SCOREBOARD_ONLY,
                "value": check.value,
                "by_role": by_role, "worst": self.worst_trios(check.id),
            }  # fmt: skip
        offenders = [{"item": name, "kits": count} for name, count in sorted(self.offenders.items(), key=lambda i: (-i[1], i[0]))]
        checks["K2"]["offenders"] = offenders
        checks["K2"]["distinct_items"] = len(offenders)
        checks["K2"]["top_items"] = offenders[:TOP_ITEMS]
        checks["K3.robe"]["cases"] = [*self.robe_cases]
        checks["K3.robe"]["items"] = [{"item": name, "kits": count} for name, count in sorted(self.robes.items(), key=lambda i: (-i[1], i[0]))]
        return {
            "format": FORMAT,
            "kits": self.kits,
            "trios": len(self.trios),
            "roles": self.roles,
            "tiers": self.tiers(),
            "thresholds": {"K3_min_ratio": K3_MIN_RATIO, "K11_band": KNEE_BAND},
            "armour": {"heavy": sorted(self.context.armour.heavy), "cloth": sorted(self.context.armour.cloth)},
            "checks": checks,
            "K4": {"title": "One family everywhere", "sets": len(set(self.context.stems.values())), "top": self.top_stems()},
            "K10": {"title": "Exchange rates", "terms": list(exchange.TERMS)},
            "gates": self.gates(),
        }


# ---- the text -----------------------------------------------------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def _text_tiers(tiers: Sequence[int]) -> list[tuple[str, list[int]]]:
    """The rows of the text: each tier every trio has, and the others together as one row."""
    rows = [(f"+{tier}", [tier]) for tier in tiers if tier in STANDARD_TIERS]
    other = [tier for tier in tiers if tier not in STANDARD_TIERS]
    return rows + ([("other", other)] if other else [])


def _k4_lines(doc: Mapping[str, Any]) -> list[str]:
    lines = [f"K4  One family everywhere   [scoreboard only]  ({doc['K4']['sets']} sets in the pool)"]
    lines.append("    the share of all kits that wear two pieces or more of one set (top ten)")
    for row in doc["K4"]["top"]:
        by_role = " ".join(f"{role} {_fmt(share)}" for role, share in row["by_role"].items())
        lines.append(f"    {row['stem']:<24}{row['kits']:>6} kits  {_fmt(row['share']):>6}   by role: {by_role}   pieces: {', '.join(row['pieces'])}")
    return [*lines, ""]


def render_scoreboard(board: Scoreboard, warnings: Sequence[str] = (), folder_trios: int | None = None) -> str:
    """The text of the scoreboard (the module docstring says what it shows). ``warnings`` are the lines that say the results may not be trusted (:func:`_problems`);
    ``folder_trios`` is the number of trios the folder has, said when the kits are of fewer."""
    doc = board.document()
    of_folder = f" (of {folder_trios} in the folder)" if folder_trios is not None and folder_trios != doc["trios"] else ""
    lines = [
        f"TrioForge kit checks: {doc['kits']} kits of {doc['trios']} trios{of_folder} (one kit for each trio, role and tier: the default race, the best setup, the default pool, own buffs)",
        f"threshold: K3 slot AC at least {K3_MIN_RATIO} of the best the trio can wear; K11 within {KNEE_BAND} points under the stat knee. The other checks have none: they are measurements",
        f"heaviest-armour classes (from the item table): {' '.join(doc['armour']['heavy']) or 'none'}; cloth classes: {' '.join(doc['armour']['cloth']) or 'none'}",
        *(f"warning: {text}" for text in warnings),
        "",
    ]
    rows_of = _text_tiers(board.tiers())
    for check in CHECKS:
        if check.id == "K5.bow":
            lines += _k4_lines(doc)
        entry = doc["checks"][check.id]
        tags = ("   [gate]" if check.id in GATES else "") + ("   [scoreboard only]" if check.id in SCOREBOARD_ONLY else "")
        lines += [f"{check.id}  {check.title}{tags}", f"    {check.sentence}", f"    value: {check.value}"]
        shown = False
        header = f"    {'role':<9}{'tier':<7}{'kits':>6}{'pass':>7}{'fail':>7}{'n.a.':>7}   {'min':>8}{'p10':>8}{'median':>8}{'p90':>8}{'max':>8}"
        for role in board.roles:
            for label, tiers in rows_of:
                row = board.row(check.id, role, tiers)
                if not row["kits"] or row["kits"] == row["na"]:
                    continue
                if not shown:
                    lines.append(header)
                    shown = True
                dist = (row.get("distribution") or {}) if check.measure else {}
                counts = f"{row['pass']:>7}{row['fail']:>7}{row['na']:>7}" if check.id not in INFO_ONLY else f"{'-':>7}{'-':>7}{row['na']:>7}"
                lines.append(
                    f"    {role:<9}{label:<7}{row['kits']:>6}{counts}   "
                    + "".join(f"{_fmt(dist.get(name)):>8}" for name in ("min", "p10", "median", "p90", "max"))
                )
        if not shown:
            lines.append("    (applies to no kit of this folder)")
        if entry["worst"]:
            lines.append(f"    worst trios: " + "; ".join(f"{w['trio']} {w['role']} +{w['tier']} {_fmt(w['value'])}" for w in entry["worst"]))
        if check.id == "K2" and entry["offenders"]:
            lines.append(f"    distinct items behind the failures: {entry['distinct_items']}; worn most: " + "; ".join(f"{o['item']} ({o['kits']})" for o in entry["top_items"]))
        if check.id == "K3.robe" and entry["items"]:
            lines.append("    robes that are the best chest piece of a tank kit: " + "; ".join(f"{o['item']} ({o['kits']})" for o in entry["items"]))
            cases = entry["cases"]
            lines.append("    cases: " + "; ".join(f"{c['trio']} +{c['tier']} {c['item']}" for c in cases[:WORST]) + (f"; and {len(cases) - WORST} more (see --json)" if len(cases) > WORST else ""))
        lines.append("")
    lines += ["Gates (with --gate): " + "; ".join(f"{check_id} {'FAIL' if n else 'pass'} ({n} kits)" for check_id, n in doc["gates"].items()), ""]
    return "\n".join(lines)


# ---- the command --------------------------------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.checks.kits",
        description="Score the kits of a results folder against the checks K1 to K11, and print how many pass, fail or do not apply, by role and tier.",
    )
    parser.add_argument("--results", required=True, type=Path, help="the results folder (a precompute output: one folder for each trio, and items.json)")
    parser.add_argument("--json", type=Path, metavar="FILE", help="write the whole scoreboard as JSON to FILE")
    parser.add_argument(
        "--gate", action="store_true",
        help="exit 1 when a gate check fails (K2, and a robe as the best chest piece of a tank kit); exit 2 when the results cannot be trusted (no kit, a trio without one, other rules)",
    )  # fmt: skip
    parser.add_argument("--expected", type=Path, metavar="FILE", help="a JSON list of cases for a kit to agree with (see trioforge.checks.expected)")
    parser.add_argument("--no-named", action="store_true", help="leave the named cases (K9) and their exchange rates (K10) out of the output")
    return parser


def _problems(results: Results, board: Scoreboard) -> list[str]:
    """What makes the results unsafe to judge by: no kit, a trio without one, rules other than the checkout's. A gate is refused for any of them."""
    found = []
    if board.kits == 0:
        found.append("no kit was read")
    elif results.unread or len(board.trios) < len(results.folders):  # (the second says it again for any way a trio could be missed: the count read is below the folder's)
        missing = len(results.folders) - len(board.trios)
        names = ", ".join(results.unread[:5]) + (f", and {len(results.unread) - 5} more" if len(results.unread) > 5 else "")
        found.append(f"{missing} of {len(results.folders)} trios yielded no kit ({names}): the default race of each has no scenario in its shard")
    mismatch = results.rules_mismatch()
    if mismatch is not None:
        found.append(f"the results were made with the rules of {mismatch[0]} and this checkout has the rules of {mismatch[1]}: the checks value the kits by the rules of this checkout")
    return found


def _silence_stdout() -> None:
    """After a closed pipe: point the standard output at nothing, so that the interpreter does not fail again when it flushes it on the way out."""
    try:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except (AttributeError, OSError, ValueError):
        pass


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command; returns 0, 1 for a failed gate with ``--gate``, or 2 after a message on stderr when an input cannot be read (or, with ``--gate``, cannot be trusted)."""
    args = _parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    try:
        from trioforge.checks import named  # the named cases read the kits again, by trio

        results = Results(args.results)
        context = Context(results)
        board = Scoreboard(context)
        for kit in results.all_kits():
            board.add(kit)
        problems = _problems(results, board)
        document = board.document()
        document["trios_in_folder"] = len(results.folders)
        document["warnings"] = problems
        text = [render_scoreboard(board, problems, len(results.folders))]
        if not args.no_named and results.rules_mismatch() is not None:
            # results made with other rules were solved with other templates: the evaluator of this checkout does not give their values, and no exchange rate is made of a kit it
            # does not value alike. K9 and K10 are not applicable there (the warning above, from _problems, says why); every other check runs as it does for any folder
            document["K9"], document["K9_na"] = [], named.NA_REASON
            text.append(named.render_na())
        elif not args.no_named:
            cases = named.named_cases(results, context)
            document["K9"] = cases
            text.append(named.render_cases(cases))
        if args.expected is not None:
            report = expected_module.check_expected(expected_module.load_cases(args.expected), results)
            document["expected"] = report
            text.append(expected_module.render_report(report))
        if args.json is not None:
            args.json.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    except (ResultsError, expected_module.ExpectedError, OSError) as error:
        print(f"kit checks: {error}", file=sys.stderr)
        return 2
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as error:  # something in a file that the readers did not foresee
        print(f"kit checks: the results cannot be read ({type(error).__name__}: {error})", file=sys.stderr)
        return 2
    failed = [check_id for check_id, count in document["gates"].items() if count]
    code, message = 0, ""
    if args.gate and problems:
        code, message = 2, f"the gate is refused: {'; '.join(problems)}"
    elif args.gate and failed:
        code, message = 1, f"the gate fails for {', '.join(failed)}"
    try:
        print("\n".join(text))
    except BrokenPipeError:  # a closed pipe (| head) must not hide the answer of a gate
        _silence_stdout()
    if message:
        print(f"kit checks: {message}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
