"""Weapon setups and the per-hand damage index.

A *setup* is a rule for the two hand slots, and the solver picks the weapons inside it together with the armour:

* ``1h-shield``: a one-handed weapon in the primary hand, a shield in the secondary hand;
* ``2h``: a two-handed weapon in the primary hand, the secondary hand empty;
* ``dw``: a one-handed weapon in each hand; the off hand swings only part of the time (the dual-wield factor);
* ``stick``: anything in either hand, chosen for its stats; no damage is scored (a two-hander in the primary hand
  still leaves the secondary hand empty, which the builder's rows see to);
* ``ranged`` ("Bow"): the **range place** holds a bow and the bow's damage is scored; the two hands are the stick's, anything
  chosen for its stats, with no damage scored. Arrows are not counted (a kit has no ammunition place).

In every setup a **two-hander never stands in the secondary hand**: it needs both hands, whatever its page lists as slots.

:func:`setups_for` lists the setups a build gets for a trio. A setup exists when the trio has the skill for it at
the level (a skill cap above zero in some class) and, for the shield, when someone in the trio can wear one:
shield wearers are decided from the class lists of the shields in the item pool, not from skills and not from a list
of classes in the code (:func:`shield_available`). The builds map as follows: Tank gets ``1h-shield``, ``2h`` and ``dw``; Shield caster gets
``1h-shield`` and ``stick``; Melee damage gets ``2h`` and ``dw`` (never the shield); Caster tank gets ``1h-shield`` and ``stick``; Caster gets
``stick`` and ``1h-shield`` too, the stick first: :func:`setup_order` puts the setup a build lists first (``_LISTED_FIRST``: the Caster's stick) before the rest of the order of
:data:`SETUPS`, and the first of two setups of equal value wins a tie, so a Caster that gets the same value from either plays the stick. **Ranged** (the Archer) is offered by :func:`setups_for`
as the last setup of Tank and Melee damage when the item pool has a bow that a class of the trio may equip and that has the Archery skill
(:func:`bow_available`), and it is the one setup of the Archer build, which has no setup, and so is not offered, for a pool with no such bow. The
three casting builds never get the bow.

**With no pool to read** (``items`` None) a shield is assumed, because the design grid of a trio has it, and a bow is not: the Bow
setup is the one setup that only a pool offers. The rule is one for every role: no role has ``ranged`` among its setups with no pool, and
the Archer build, which is nothing but the Bow setup, has none at all (``[]``), so it is not offered either (``roles_for(trio, bow=False)``,
a refused profile, no scenario in a grid, and a bundle that gives its profile only at an evidence level: :data:`trioforge.model.roles.POOL_ROLES`).
The pool may be any iterable: it is read once into a list.

:func:`damage_index` is what a weapon adds in a hand, in the units of the objective's weapon weight: the
auto-attack damage per delay unit at the item's tier and the scenario's haste::

    (damage + bonus) / delay * (1 + haste / 100)

* ``damage`` is the item's damage at its tier (the item view has already applied the per-tier growth) and
  ``delay`` is never changed by tier;
* ``bonus`` is the tooltip's damage bonus when the item lists one, else the client's formula of the level (T9; the rule
  ``weapons.fallback_bonus``): none below level 28, and from there ``(level / 100) x max(damage, level) x f x min(delay, 50) / 40``
  with ``f`` 0.8 for a one-hander and 1.1 for a two-hander (at level 50 half the delay for a one-hander whose damage is no more than
  the level, and 0.6875 x min(delay, 50) for a two-hander);
* a bow in the range place of ``ranged`` scores ``damage / delay x (1 + haste / 100)`` times the rule ``weapons.ranged_factor``, and nothing else
  scores there: no bonus (the damage bonus is a main hand's: the bonus its page lists, else the formula of the level, which is what the melee weapons follow,
  and no rule or shipped data says archery gets it; no bow of the catalog lists one, and one that did would not be counted either), and no arrow damage;
* the off hand in ``dw`` has no bonus and is multiplied by the dual-wield factor: the damage bonus belongs to
  the primary hand, and the factor is the chance that an off-hand swing comes. The rule
  ``weapons.dual_wield_factor`` gives it for each kind of trio, 0.83 with a Monk and 0.69 without
  (``min(1, best Dual Wield skill / 400 x 1.32)`` with the skill at 252 for a Monk and 210 for the other dual
  wielders, a working model :func:`dual_wield_factor_for` picks from). A rule that holds one number gives it to
  every trio. The module default, 0.8, is only for a call with no rules; the ``dw_factor`` argument overrides all;
* an item the setup does not allow in that hand adds nothing (the builder keeps such items out of the hand with its
  setup rows; the index just answers 0 for them), and so does everything in ``stick``;
* procs are listed elsewhere (:mod:`trioforge.effects`) and scored there and in :mod:`trioforge.model.procs`, not here: this module scores the swing, and a proc adds to the index of the hand that swings it.

The haste a program takes is a constant of that program, which keeps the term linear in the item columns; the solve makes
it the haste the kit counts by building one program for each haste a kit can count (:mod:`trioforge.solver.haste`), and
:func:`haste_assumed` is the highest of them (the ceiling of the scenario, what a kit would count with the best spell haste
on offer and the best worn haste of the pool). The index exists as an exact :class:`~fractions.Fraction` for the oracle and
as a float for the model.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from fractions import Fraction
from typing import Any

from trioforge.classes import CLASS_CODES
from trioforge.rules import DEFAULT_LEVEL

__all__ = [
    "BONUS_DELAY_CAP",
    "BONUS_DELAY_DIV",
    "BONUS_FROM_LEVEL",
    "BONUS_LEVEL_DIV",
    "BONUS_ONE_HANDED",
    "BONUS_TWO_HANDED",
    "BOW_SKILL",
    "DUAL_WIELD_FACTOR",
    "HANDS",
    "PLACES",
    "RANGE_FACTOR",
    "RANGE_HAND",
    "ROLES",
    "SETUPS",
    "allowed_in_hand",
    "archers",
    "damage_index",
    "damage_index_exact",
    "dual_wield_factor_for",
    "bow_available",
    "haste_assumed",
    "is_bow",
    "setup_order",
    "fallback_bonus",
    "setups_for",
    "shield_available",
    "swing_factor_of",
]

SETUPS = ("1h-shield", "2h", "dw", "stick", "ranged")
ROLES = ("tank", "shield", "melee", "ranged", "castertank", "caster")
HANDS = ("primary", "secondary")
#: the place a bow stands in, scored under the ``ranged`` setup; the places the weapon index is asked about are the two hands and this one
RANGE_HAND = "range"
PLACES = (*HANDS, RANGE_HAND)
#: the skill of a bow in the catalog (the weapon's ``skill``, read without regard to case); a thrown weapon has another
BOW_SKILL = "Archery"

# classes that cast (the SPELL group of :mod:`trioforge.model.roles`)
CASTER_CLASSES = frozenset({"CLR", "DRU", "SHM", "NEC", "WIZ", "MAG", "ENC"})
# skills the client's skill caps name
ONE_HANDED_SKILLS = ("1H Slashing", "1H Blunt", "1H Piercing")
TWO_HANDED_SKILLS = ("2H Slashing", "2H Blunt", "2H Piercing")
DUAL_WIELD_SKILL = "Dual Wield"

# the damage bonus of a main hand when the item lists none (``weapons.fallback_bonus``, the game client's own calculation):
# (level / 100) x max(damage, level) x factor x min(delay, 50) / 40, from level 28 on
BONUS_FROM_LEVEL = 28  # the first level that has a bonus
BONUS_ONE_HANDED = Fraction(4, 5)  # the factor of a one-hander
BONUS_TWO_HANDED = Fraction(11, 10)  # the factor of a two-hander
BONUS_DELAY_CAP = 50  # the most delay that counts, for either
BONUS_DELAY_DIV = 40  # the delay is counted in fortieths
BONUS_LEVEL_DIV = 100  # and the level in hundredths
DUAL_WIELD_FACTOR = Fraction(4, 5)  # the default chance that the off hand swings
RANGE_FACTOR = Fraction(1)  # the default multiplier of a bow's own damage per delay (``weapons.ranged_factor``)

#: the setups each build can play: a build with a stick has it always, and the weapon setups follow the skills of the trio and the pool (their order is :func:`setup_order`)
_ROLE_SETUPS = {
    "tank": ("1h-shield", "2h", "dw"),
    "shield": ("1h-shield", "stick"),
    "melee": ("2h", "dw"),
    "castertank": ("1h-shield", "stick"),
    "caster": ("stick", "1h-shield"),
}
#: the setup a build lists first where that is not the first of :data:`SETUPS`: the first setup of equal value wins a tie, and for the Caster that is the stat stick
_LISTED_FIRST = {"caster": "stick"}
#: the builds that may also play the Bow setup, when the pool has a bow the trio can shoot
_BOW_ROLES = frozenset({"tank", "melee"})


def setup_order(role: str) -> tuple[str, ...]:
    """The order of the setups of ``role`` wherever they are listed: the order of :data:`SETUPS`, with the setup the build lists first (the Caster's stick) put first. The first
    of two setups of equal value wins the tie, in the precompute, the checker and the site's reader alike."""
    first = _LISTED_FIRST.get(role)
    return SETUPS if first is None else (first, *(setup for setup in SETUPS if setup != first))


# ---- which setups ---------------------------------------------------------------------------------------------


def _admits(classes: Iterable[str], trio: Sequence[str]) -> bool:
    classes = set(classes)
    return "ALL" in classes or any(code in classes for code in trio)


def shield_available(trio: Sequence[str], items: Iterable[Any] | None = None) -> bool:
    """Whether someone in ``trio`` can wear a shield.

    Who can wear a shield is read from the pool: a shield (``is_shield``) in ``items`` whose class list admits a class
    of the trio (or lists ``ALL``) makes it so, and a pool with no such shield does not. No list of classes in the code
    decides it (shields exist for casters and for Monks). With no pool at all (``items`` None) there is nothing to read,
    and a shield is assumed: the solver then finds no shield in the pool and simply wears none.
    """
    if items is None:
        return True
    return any(getattr(item, "is_shield", False) and _admits(item.classes, trio) for item in items)


def is_bow(item: Any) -> bool:
    """Whether ``item`` is a bow: a weapon with a damage and a delay, of the archery skill (:data:`BOW_SKILL`, in any case),
    that fits the range place (when the item says which slots it fits). Ammunition has no delay and is no weapon, and a thrown
    weapon has another skill."""
    weapon = getattr(item, "weapon", None)
    if not _is_weapon(item) or (weapon.skill or "").casefold() != BOW_SKILL.casefold():
        return False
    slots = getattr(item, "slots", None)
    return slots is None or "RANGE" in slots


def archers(trio: Sequence[str], tables: Any, level: int) -> tuple[str, ...]:
    """The classes of ``trio`` that have the Archery skill at ``level`` (the client's skill caps, :data:`BOW_SKILL`: a class with no cap cannot shoot a bow)."""
    return tuple(code for code in trio if tables.skillcap.get((code, BOW_SKILL, level), 0) > 0)


def bow_available(trio: Sequence[str], items: Iterable[Any] | None = None, *, tables: Any = None, level: int | None = None) -> bool:
    """Whether the pool ``items`` has a bow that a class of ``trio`` may equip (the class list of the bow, or ``ALL``). With ``tables`` (and ``level``, which
    defaults to the rules' current level) only a class that has the Archery skill at that level counts, as only a class that has a one-handed skill makes the shield
    setup. With no pool (``items`` None) there is nothing to read and the answer is no: a bow is never assumed (a shield is)."""
    if items is None:
        return False
    classes = trio
    if tables is not None:
        if level is None:
            rules = getattr(tables, "rules", None)
            level = rules.get("level.current") if rules is not None else DEFAULT_LEVEL
        classes = archers(trio, tables, level)
    return any(is_bow(item) and _admits(item.classes, classes) for item in items)


def setups_for(
    trio: Sequence[str], role: str, tables: Any, *, level: int | None = None, items: Iterable[Any] | None = None
) -> list[str]:
    """The setups ``role`` plays for ``trio`` at ``level``, in the order of :func:`setup_order` (the order of :data:`SETUPS`, but for the Caster, whose stick comes first).

    ``tables.skillcap[(class, skill, level)]`` gives the client's skill caps; ``level`` defaults to
    ``tables.rules``' current level. ``items`` is the item pool (any iterable: it is read once into a list), for :func:`shield_available`
    (None: a shield is assumed to exist) and :func:`bow_available` (None: there is no bow, for any role: a bow is never assumed; a class
    needs the Archery skill as it needs a one-handed skill for the shield). The ``stick`` of a casting build is always there. A role that
    ends up with nothing available gets ``["stick"]``, which always works: but the Archer build plays the bow and nothing else, so with no
    pool, or a pool with no bow, it has no setup (``[]``: the build is not offered).
    """
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; use one of {', '.join(ROLES)}")
    unknown = [code for code in trio if code not in CLASS_CODES]
    if unknown:
        raise ValueError(f"not class codes: {', '.join(map(str, unknown))}")
    if level is None:
        rules = getattr(tables, "rules", None)
        level = rules.get("level.current") if rules is not None else DEFAULT_LEVEL
    items = None if items is None else list(items)  # (it is read for the bow and for the shield: a generator would be spent by the first)
    bows = bow_available(trio, items, tables=tables, level=level)
    if role == "ranged":
        return ["ranged"] if bows else []

    def has(*skills: str) -> bool:
        return any(tables.skillcap.get((code, skill, level), 0) > 0 for code in trio for skill in skills)

    available = {
        "1h-shield": has(*ONE_HANDED_SKILLS) and shield_available(trio, items),
        "2h": has(*TWO_HANDED_SKILLS),
        "dw": has(DUAL_WIELD_SKILL),
        "stick": True,
    }
    order = setup_order(role)
    result = sorted((setup for setup in _ROLE_SETUPS[role] if available[setup]), key=order.index)
    result = result or ["stick"]
    if bows and role in _BOW_ROLES:
        result.append("ranged")  # the last of the setups
    return result


# ---- the damage index -----------------------------------------------------------------------------------------


def _check(hand: str, setup: str) -> None:
    if hand not in PLACES:
        raise ValueError(f"unknown hand {hand!r}; use one of {', '.join(PLACES)}")
    if setup not in SETUPS:
        raise ValueError(f"unknown setup {setup!r}; use one of {', '.join(SETUPS)}")


def _frac(number: Any) -> Fraction:
    if isinstance(number, (int, Fraction)):
        return Fraction(number)
    return Fraction(str(number))  # a float such as 0.8 means 4/5, not its binary expansion


def _is_weapon(item: Any) -> bool:
    weapon = getattr(item, "weapon", None)
    return weapon is not None and bool(weapon.dmg) and bool(weapon.delay) and weapon.dmg > 0 and weapon.delay > 0


def _two_handed(item: Any) -> bool:
    weapon = getattr(item, "weapon", None)
    return weapon is not None and bool(weapon.two_handed)


def _ranged_skill(item: Any) -> bool:
    """Whether ``item`` is a weapon of a ranged skill: archery, or one of the throwing skills of the catalog (``Throwing``, ``Throwingv1``, ``Throwingv2``), in any case."""
    weapon = getattr(item, "weapon", None)
    skill = ((weapon.skill if weapon is not None else None) or "").casefold()
    return skill == BOW_SKILL.casefold() or skill.startswith("throwing")


def allowed_in_hand(item: Any, hand: str, setup: str) -> bool:
    """Whether ``setup`` lets ``item`` stand in ``hand``; whether the item fits the slot is for the caller.

    ``2h``: a two-hander in the primary hand and nothing in the secondary. ``dw``: a one-handed weapon in either
    hand. ``1h-shield``: a one-handed weapon in the primary hand, a shield in the secondary. ``stick`` and ``ranged``: anything. In
    every setup a two-hander is refused the secondary hand, and a weapon of a ranged skill (:func:`_ranged_skill`: a bow, a thrown weapon) is refused both hands, whatever slots
    its page lists: it is not a melee weapon, and the range place is the one for it. The **range place** (``hand`` ``"range"``) takes a bow in the ``ranged`` setup
    (:func:`is_bow`) and anything that fits it in the others.
    """
    _check(hand, setup)
    if hand == RANGE_HAND:
        return is_bow(item) if setup == "ranged" else True
    if _ranged_skill(item):
        return False
    if hand == "secondary" and _two_handed(item):
        return False
    if setup in ("stick", "ranged"):
        return True
    if setup == "1h-shield" and hand == "secondary":
        return bool(getattr(item, "is_shield", False))
    if not _is_weapon(item):
        return False
    if setup == "2h":
        return hand == "primary" and bool(item.weapon.two_handed)
    return not item.weapon.two_handed


def fallback_bonus(damage: Any, delay: Any, two_handed: bool, level: int) -> Fraction:
    """The damage bonus of a main hand whose item lists none: ``(level / 100) x max(damage, level) x f x min(delay, 50) / 40``, with ``f`` 0.8 for a one-hander and 1.1 for a two-hander, and 0 below level 28
    (the rule ``weapons.fallback_bonus``: the game client's own calculation, exact here: the client rounds it down when it shows it)."""
    if level < BONUS_FROM_LEVEL:
        return Fraction(0)
    factor = BONUS_TWO_HANDED if two_handed else BONUS_ONE_HANDED
    return Fraction(level, BONUS_LEVEL_DIV) * max(_frac(damage), level) * factor * min(_frac(delay), BONUS_DELAY_CAP) / BONUS_DELAY_DIV


def _bonus(weapon: Any, level: int) -> Fraction:
    if weapon.bonus:
        return _frac(weapon.bonus)
    return fallback_bonus(weapon.dmg, weapon.delay, bool(weapon.two_handed), level)


def dual_wield_factor_for(trio: Sequence[str], rules: Any, level: int = DEFAULT_LEVEL) -> Any:
    """The dual-wield factor of a trio under ``rules``: the rule's ``with_monk`` value when the trio has a Monk and its
    ``without_monk`` value when it has not, or the rule's one number when it is not a pair of values. The value is
    returned as the rules file has it (0.83, 0.69); a pair that lacks one of the two is a ``ValueError``."""
    value = rules.get("weapons.dual_wield_factor", level)
    if not isinstance(value, Mapping):
        return value
    key = "with_monk" if "MNK" in trio else "without_monk"
    if set(value) != {"with_monk", "without_monk"} or any(
        isinstance(number, bool) or not isinstance(number, (int, float)) for number in value.values()
    ):
        raise ValueError(f"weapons.dual_wield_factor is a number or {{with_monk, without_monk}} numbers, not {value!r}")
    return value[key]


def _dual_wield_factor(rules: Any, given: Any) -> Fraction:
    if given is not None:
        return _frac(given)
    try:
        value = rules.get("weapons.dual_wield_factor")
    except (AttributeError, KeyError):  # no rules, or no such rule yet
        return DUAL_WIELD_FACTOR
    if isinstance(value, Mapping):
        raise ValueError(
            "weapons.dual_wield_factor has a value for each kind of trio (with_monk, without_monk): "
            "name the factor with dw_factor, or take it from dual_wield_factor_for"
        )
    return _frac(value)


def _ranged_factor(rules: Any, given: Any) -> Fraction:
    if given is not None:
        return _frac(given)
    try:
        value = rules.get("weapons.ranged_factor")
    except (AttributeError, KeyError):  # no rules, or no such rule yet
        return RANGE_FACTOR
    return _frac(value)


def swing_factor_of(profile: Any) -> Fraction:
    """The factor of the swing speed that a profile's stance gives (the Berserker stance: ``stance.berserker``), 1 for a profile with none: ``damage_index_exact(..., swing_factor=)`` multiplies the hands by it."""
    stance = getattr(profile, "stance", None)
    return Fraction(1) if stance is None else _frac(stance["swing_factor"])


def damage_index_exact(
    item: Any, hand: str, setup: str, haste_pct: Any, rules: Any = None, *, dw_factor: Any = None, ranged_factor: Any = None, swing_factor: Any = None, level: int | None = None
) -> Fraction:
    """What ``item`` adds in ``hand`` under ``setup`` at ``haste_pct`` percent haste, exactly (see above).

    ``level`` is the character level that the fallback bonus of the main hand reads (:func:`fallback_bonus`; None: the default level).

    ``ranged_factor`` is the multiplier of a bow in the range place of ``ranged`` (None: the rule ``weapons.ranged_factor``, else 1). ``swing_factor`` (None: 1) is the factor of the swing speed of a
    stance (:func:`swing_factor_of`): it multiplies a hand that swings, after the haste, and not the range place."""
    _check(hand, setup)
    if setup == "stick" or not allowed_in_hand(item, hand, setup) or not _is_weapon(item):
        return Fraction(0)
    if setup == "ranged" and hand != RANGE_HAND:
        return Fraction(0)  # the hands of the bow setup are stat sticks
    if hand == RANGE_HAND and setup != "ranged":
        return Fraction(0)  # and the range place scores only in it
    weapon = item.weapon
    haste = 1 + _frac(haste_pct) / 100
    damage, delay = _frac(weapon.dmg), _frac(weapon.delay)
    if hand == RANGE_HAND:  # a bow's own damage per delay: the damage bonus is a main hand's, and nothing says that archery gets it
        return damage / delay * haste * _ranged_factor(rules, ranged_factor)
    swing = Fraction(1) if swing_factor is None else _frac(swing_factor)
    if hand == "secondary":
        return damage / delay * haste * _dual_wield_factor(rules, dw_factor) * swing
    return (damage + _bonus(weapon, DEFAULT_LEVEL if level is None else level)) / delay * haste * swing


def damage_index(
    item: Any, hand: str, setup: str, haste_pct: Any, rules: Any = None, *, dw_factor: Any = None, ranged_factor: Any = None, swing_factor: Any = None, level: int | None = None
) -> float:
    """:func:`damage_index_exact` as a float, the coefficient the model uses."""
    return float(damage_index_exact(item, hand, setup, haste_pct, rules, dw_factor=dw_factor, ranged_factor=ranged_factor, swing_factor=swing_factor, level=level))


def haste_assumed(profile: Any, items: Iterable[Any]) -> int:
    """The highest haste a kit of this pool can count: the spell haste on offer plus the best worn haste in the pool, up to the cap.
    (It is the ceiling of the hastes the truthful solve looks at, and the constant the bare builder takes when it is given none; the
    weapon term of a solve is paid the haste the kit really counts.)

    ``profile.haste_cap`` is the cap of the level (:func:`~trioforge.model.formulas.haste_cap_at`: 75 at level 50, 85 for levels 51 to 59, 100 from level 60) and 10 more with a Monk
    (Unbound Alacrity), and ``profile.spell_haste`` the haste of the scenario's buffs, with
    the 10 of Unbound Alacrity when the trio has a Monk (``Profile.haste_bonus``, already in ``spell_haste``).
    Only the best worn piece counts, and a negative worn haste counts for nothing.
    """
    best_worn = max((item.haste for item in items if item.haste > 0), default=0)
    return int(min(profile.haste_cap, max(profile.spell_haste, 0) + best_worn))
