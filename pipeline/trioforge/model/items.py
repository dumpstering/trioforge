"""A catalog item at one upgrade tier.

``at_tier(item, tier, rules)`` takes a catalog item (the dict that validates against
``trioforge/data/schema/catalog-item.schema.json``) and returns an :class:`ItemVec`: the numbers the
model sees when the item is worn at tier ``tier`` (0 to 10). The tier rules are read from
``rules/rules.json``:

* **Stats** (AC STR STA AGI DEX WIS INT CHA HP MANA END) and **resists**: ``base + max(n, floor(base *
  n / 10))`` when the base is above zero (``tier.stat_rule``). A **negative** stat moves toward zero by the same
  amount, ``max(n, floor(|base| * n / 10))``, and never passes zero (``tier.negatives_scale``, the game client's own
  calculation: -2 is -1 at +1 and 0 at +2, -20 is -12 at +4); a rules file that says anything else is refused. **Attack** (ATK) is
  not scaled at all (``tier.unscaled_stats``, the same source): an item's attack at +4 or +10 is its +0 value.
* **Worn haste** and the three **regens**: a flat ``haste.worn_per_tier`` / ``regen.per_tier`` a tier when
  the base is above zero. Haste is a field of its own (``ItemVec.haste``), not one of the stats.
* **Weight**, in tenths of a stone: ``max(floor10, w - w * pct * n // 100)`` for a weight ``w`` above zero, with
  ``pct`` = ``tier.weight_pct`` (9, a percent of the base weight a tier, no minimum step) and ``floor10`` the
  ``tier.weight_floor`` in tenths (0.1 stone, so a weight never falls below it). A weightless item stays
  weightless. An item with **no weight on its page** counts as 1.0 stone (``weight10 = 10``) at every tier, for
  the Monk's worn weight, and keeps ``weight_known = False`` so that a pick can be marked ``weight-unknown``: with
  no base weight there is nothing for the tiers to reduce.
* **Races**: ``races`` is None for an item any race may wear (``ALL`` in any case, or no ``races`` field at all, as on
  a hand-built item) and otherwise the frozenset of race codes that may wear it. An **empty list** is a page that
  says ``Race: NONE``: no race may wear the item, so ``races`` is the empty frozenset. The builder and the pruning
  leave out an item whose ``races`` exclude the race of the profile, so that item has no column for any race. A
  ``races`` that is not a list of strings is a ``ValueError`` (a bare ``"HUM"`` would be read as the races H, U and M).
* **Weapon damage**: ``dmg + dmg * n * pct // 100`` with ``pct`` = ``tier.weapon_damage_pct`` (10, or 5 for the
  alternative rule), with no minimum of a point a tier. Delay and the listed damage bonus never change. An item has a
  :class:`WeaponVec` only when the page gives both a damage and a delay, and a shield (below) has none.
* **Shield**: ``is_shield`` is true for an item that fits the off hand (the ``SECONDARY`` slot) and whose catalog
  ``item_type`` is ``Shield`` in any case. Nothing else makes one (see :func:`_is_shield`).

Zero stats are dropped. ``ItemVec`` is a frozen dataclass; it compares by value and hashes by
``(key, tier)``. The catalog item is never changed.

The module also names the twenty-two places a kit has (:data:`SLOT_INSTANCES`), in the order a kit list
uses.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from trioforge.classes import CLASS_CODES

__all__ = [
    "REGEN_KEYS",
    "SLOT_GROUPS",
    "SLOT_INSTANCES",
    "STAT_KEYS",
    "SV_KEYS",
    "ItemVec",
    "WeaponVec",
    "at_tier",
]

#: slot group -> how many places it has; the Any group takes any item.
SLOT_GROUPS: tuple[tuple[str, int], ...] = (
    ("HEAD", 1), ("FACE", 1), ("EAR", 2), ("NECK", 1), ("SHOULDERS", 1), ("ARMS", 1), ("BACK", 1), ("WRIST", 2),
    ("HANDS", 1), ("FINGER", 2), ("CHEST", 1), ("LEGS", 1), ("FEET", 1), ("WAIST", 1), ("RANGE", 1), ("ANY", 2),
    ("PRIMARY", 1), ("SECONDARY", 1),
)  # fmt: skip
#: the group of each place of a kit, in kit order: ``kit[i]`` is worn in ``SLOT_INSTANCES[i]``.
SLOT_INSTANCES: tuple[str, ...] = tuple(name for name, count in SLOT_GROUPS for _ in range(count))

#: stats that follow the stat rule, in the order ``ItemVec.stats`` lists them.
STAT_KEYS: tuple[str, ...] = ("AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK")
#: stats that add a flat amount a tier.
REGEN_KEYS: tuple[str, ...] = ("HPREG", "MANAREG", "ENDREG")
#: the schools the catalog knows; the model scores the first five.
SV_KEYS: tuple[str, ...] = ("FIRE", "COLD", "MAGIC", "POISON", "DISEASE", "CORRUPTION")

MAX_TIER = 10
STAT_RULE_TEXT = "base + max(n, floor(base*n/10))"
NEGATIVES_RULE_TEXT = "toward zero by max(n, floor(|base|*n/10)), never past zero"  # tier.negatives_scale
WEAPON_PCTS = (5, 10)
DAMAGE_RULE_TEXT = "dmg + dmg * n * pct // 100"  # what the browser's bundle names, and items.js checks
WEIGHT_RULE_TEXT = "max(floor, w - w * pct * n // 100)"
UNKNOWN_WEIGHT10 = 10  # an item whose page gives no weight counts as 1.0 stone


@dataclass(frozen=True)
class WeaponVec:
    """A weapon at a tier. ``dmg`` is the tiered damage; ``bonus`` is the damage bonus the page lists, or None."""

    skill: str | None
    dmg: int
    delay: int
    bonus: int | None
    two_handed: bool


@dataclass(frozen=True)
class ItemVec:
    """One catalog item at one tier. See the module docstring for how each number is made."""

    key: str
    name: str
    slots: frozenset[str]
    classes: frozenset[str]
    deity: frozenset[str] | None
    lore: bool
    stats: dict[str, int]
    sv: dict[str, int]
    haste: int
    weight10: int
    weapon: WeaponVec | None
    is_shield: bool
    tier: int
    weight_known: bool = True
    races: frozenset[str] | None = None

    def __hash__(self) -> int:
        # The dict fields cannot be hashed; an item at a tier is identified by its key and tier.
        return hash((self.key, self.tier))


# ---- the rules -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _TierRules:
    weapon_pct: int
    haste_per_tier: int
    regen_per_tier: int
    floor10: int
    weight_pct: int
    unscaled: frozenset[str]


def _whole(value: Any, rule: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{rule} must be a whole number of at least {minimum}, not {value!r}")
    return value


def _check_pct(pct: Any) -> int:
    if type(pct) is not int or pct not in WEAPON_PCTS:
        raise ValueError(f"tier.weapon_damage_pct must be one of {WEAPON_PCTS}, not {pct!r}")
    return pct


@functools.lru_cache(maxsize=16)
def _tier_rules(rules: Any) -> _TierRules:
    """The tier rules of a ``Rules`` object, read once. Refuses a rules file this module does not implement."""
    text = rules.get("tier.stat_rule")
    if text != STAT_RULE_TEXT:
        raise ValueError(f"tier.stat_rule is {text!r}, but trioforge.model.items implements {STAT_RULE_TEXT!r}")
    negatives = rules.get("tier.negatives_scale")
    if negatives != NEGATIVES_RULE_TEXT:
        raise ValueError(f"tier.negatives_scale is {negatives!r}, but trioforge.model.items implements {NEGATIVES_RULE_TEXT!r}")
    unscaled = rules.get("tier.unscaled_stats")
    if not isinstance(unscaled, list) or not all(isinstance(key, str) and key in STAT_KEYS for key in unscaled):
        raise ValueError(f"tier.unscaled_stats must be a list of stats of the model ({', '.join(STAT_KEYS)}), not {unscaled!r}")
    floor = Fraction(str(rules.get("tier.weight_floor"))) * 10
    if floor.denominator != 1 or floor < 1:
        raise ValueError(f"tier.weight_floor must be a whole number of tenths of a stone, not {floor / 10} stone")
    return _TierRules(
        weapon_pct=_check_pct(rules.get("tier.weapon_damage_pct")),
        haste_per_tier=_whole(rules.get("haste.worn_per_tier"), "haste.worn_per_tier"),
        regen_per_tier=_whole(rules.get("regen.per_tier"), "regen.per_tier"),
        floor10=int(floor),
        weight_pct=_whole(rules.get("tier.weight_pct"), "tier.weight_pct"),
        unscaled=frozenset(unscaled),
    )


# ---- the numbers ---------------------------------------------------------------------------


def _check_tier(tier: Any) -> int:
    if type(tier) is not int:
        raise TypeError(f"the tier must be a whole number from 0 to {MAX_TIER}, not {tier!r}")
    if not 0 <= tier <= MAX_TIER:
        raise ValueError(f"the tier must be a whole number from 0 to {MAX_TIER}, not {tier}")
    return tier


def _scaled(base: int, n: int) -> int:
    """The stat rule: ``base + max(n, base * n // 10)`` above zero; below zero the stat moves toward zero by ``max(n, |base| * n // 10)``, never past it; zero stays."""
    if base > 0:
        return base + max(n, base * n // 10)
    if base < 0:
        return base + min(-base, max(n, -base * n // 10))
    return base


def _flat(base: int, n: int, per_tier: int) -> int:
    return base + n * per_tier if base > 0 else base


def _tenths(weight: Any) -> int:
    """Stones as a whole number of tenths, half up, from the decimal the page prints."""
    return math.floor(Fraction(str(weight)) * 10 + Fraction(1, 2))


def _weight10(weight: Any, n: int, floor10: int, weight_pct: int) -> tuple[int, bool]:
    """The weight in tenths at tier ``n``: ``max(floor10, w - w * weight_pct * n // 100)``, no minimum step."""
    if weight is None:
        return UNKNOWN_WEIGHT10, False
    w10 = _tenths(weight)
    if w10 <= 0:
        return 0, True
    return max(floor10, w10 - w10 * weight_pct * n // 100), True


def _races(listed: Any) -> frozenset[str] | None:
    """The races that may wear an item: None for every race, else the set of their codes (empty: no race may).

    ``listed`` is the catalog field ``races``. ``ALL`` in any case lists every race, whatever else the list holds. An
    empty list is a page that says ``Race: NONE``: nobody can wear the item, so the answer is the empty set, not None.
    None (no field at all, as on a hand-built item) means every race. A bare string, or a list that holds anything
    but strings, is a ``ValueError``: a string would be read letter by letter.
    """
    if listed is None:
        return None
    if not isinstance(listed, list) or not all(isinstance(code, str) for code in listed):
        raise ValueError(f"races must be a list of race codes, not {listed!r}")
    if any(code.upper() == "ALL" for code in listed):
        return None
    return frozenset(listed)


def _two_handed(skill: str | None) -> bool:
    text = (skill or "").casefold().replace("-", " ")
    return text.startswith("2h") or text.startswith("two hand")


def _is_shield(item: dict[str, Any], slots: frozenset[str]) -> bool:
    """A shield is an item worn in the off hand whose type says so: the catalog field ``item_type`` is ``Shield``.

    The field is the only thing that makes one. A slot and an armor class do not: a focus crystal, an orb, a totem or an
    instrument sits in the off hand and carries armor class too, without the bonus a shield gives the softcap. The
    catalog builder is what fills ``item_type`` (from the statsblock, a shield word in the name or a reviewed list).
    """
    return "SECONDARY" in slots and (item.get("item_type") or "").lower() == "shield"


def at_tier(item: dict[str, Any], tier: int, rules: Any, *, weapon_pct: int | None = None) -> ItemVec:
    """The catalog ``item`` at upgrade ``tier`` (0 to 10) under ``rules`` (a :class:`trioforge.rules.Rules`).

    ``weapon_pct`` replaces the rule ``tier.weapon_damage_pct`` (5 or 10), for the robustness runs that try the
    other damage rule. Raises ``TypeError`` / ``ValueError`` for a tier that is not a whole number from 0 to
    10, a stat or school the model does not know, a ``races`` that is not a list of strings, or a rules file that
    this module does not implement.
    """
    n = _check_tier(tier)
    rule = _tier_rules(rules)
    pct = rule.weapon_pct if weapon_pct is None else _check_pct(weapon_pct)

    raw = item["stats"]
    unknown = sorted(set(raw) - set(STAT_KEYS) - set(REGEN_KEYS) - {"HASTE"})
    if unknown:
        raise ValueError(f"item {item['key']}: unknown stat {unknown[0]!r}")
    stats: dict[str, int] = {}
    for key in STAT_KEYS:
        if raw.get(key):
            value = raw[key] if key in rule.unscaled else _scaled(raw[key], n)
            if value:  # (a negative stat that the tiers have shrunk to nothing is gone, like any zero)
                stats[key] = value
    for key in REGEN_KEYS:
        if raw.get(key):
            stats[key] = _flat(raw[key], n, rule.regen_per_tier)
    haste = _flat(raw.get("HASTE", 0), n, rule.haste_per_tier)

    raw_sv = item["sv"]
    unknown = sorted(set(raw_sv) - set(SV_KEYS))
    if unknown:
        raise ValueError(f"item {item['key']}: unknown resist {unknown[0]!r}")
    sv = {key: value for key in SV_KEYS if raw_sv.get(key) and (value := _scaled(raw_sv[key], n))}

    slots = frozenset(item["slots"])
    is_shield = _is_shield(item, slots)
    weapon = None
    raw_weapon = item["weapon"]
    if raw_weapon is not None and not is_shield and raw_weapon["dmg"] is not None and raw_weapon["delay"] is not None:
        dmg = raw_weapon["dmg"]
        if dmg > 0:
            dmg += dmg * n * pct // 100
        skill = raw_weapon["skill"]
        weapon = WeaponVec(skill, dmg, raw_weapon["delay"], raw_weapon["bonus"], _two_handed(skill))

    try:
        races = _races(item.get("races"))
    except ValueError as error:
        raise ValueError(f"item {item['key']}: {error}") from None

    weight10, weight_known = _weight10(item["weight"], n, rule.floor10, rule.weight_pct)
    return ItemVec(
        key=item["key"],
        name=item["name"],
        slots=slots,
        classes=frozenset(CLASS_CODES) if "ALL" in item["classes"] else frozenset(item["classes"]),
        deity=None if item["deity"] is None else frozenset(item["deity"]),
        lore="lore" in item["flags"],
        stats=stats,
        sv=sv,
        haste=haste,
        weight10=weight10,
        weapon=weapon,
        is_shield=is_shield,
        tier=n,
        weight_known=weight_known,
        races=races,
    )
