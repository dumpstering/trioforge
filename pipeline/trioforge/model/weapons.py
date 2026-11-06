"""Weapon setups and the per-hand damage index.

A *setup* is a rule for the two hand slots, and the solver picks the weapons inside it together with the armour:

* ``1h-shield``: a one-handed weapon in the primary hand, a shield in the secondary hand;
* ``2h``: a two-handed weapon in the primary hand, the secondary hand empty;
* ``dw``: a one-handed weapon in each hand; the off hand swings only part of the time (the dual-wield factor);
* ``stick``: anything in either hand, chosen for its stats; no damage is scored (a two-hander in the primary hand
  still leaves the secondary hand empty, which the builder's rows see to).

In every setup a **two-hander never stands in the secondary hand**: it needs both hands, whatever its page lists as slots.

:func:`setups_for` lists the setups a role gets for a trio. A setup exists when the trio has the skill for it at
the level (a skill cap above zero in some class) and, for the shield, when someone in the trio can wear one:
shield wearers are decided from the class lists of the shields in the item pool, not from skills and not from a list
of classes in the code (:func:`shield_available`; with no pool a shield is assumed). The roles map as follows: Tank gets ``1h-shield``, ``2h`` and ``dw``; Melee gets
``2h`` and ``dw``; Caster gets ``stick``; Balanced gets every one of the first three that is available, and
``stick`` too when the trio has a caster.

:func:`damage_index` is what a weapon adds in a hand, in the units of the objective's weapon weight: the
auto-attack damage per delay unit at the item's tier and the scenario's haste::

    (damage + bonus) / delay * (1 + haste / 100)

* ``damage`` is the item's damage at its tier (the item view has already applied the per-tier growth) and
  ``delay`` is never changed by tier;
* ``bonus`` is the tooltip's damage bonus when the item lists one, else 0.5 x delay for a one-hander and
  0.67 x min(delay, 50) for a two-hander (the pattern the Sky weapons follow; the wiki's Game Mechanics page
  caps the delay a two-hander's bonus counts at 50);
* the off hand in ``dw`` has no bonus and is multiplied by the dual-wield factor: the damage bonus belongs to
  the primary hand, and the factor is the chance that an off-hand swing comes. The rule
  ``weapons.dual_wield_factor`` gives it for each kind of trio, 0.83 with a Monk and 0.69 without
  (``min(1, best Dual Wield skill / 400 x 1.32)`` with the skill at 252 for a Monk and 210 for the other dual
  wielders, a working model :func:`dual_wield_factor_for` picks from). A rule that holds one number gives it to
  every trio. The module default, 0.8, is only for a call with no rules; the ``dw_factor`` argument overrides all;
* an item the setup does not allow in that hand adds nothing (the builder keeps such items out of the hand with its
  setup rows; the index just answers 0 for them), and so does everything in ``stick``;
* procs are listed elsewhere and not scored.

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
    "BONUS_TWO_HANDED_DELAY_CAP",
    "DUAL_WIELD_FACTOR",
    "HANDS",
    "ROLES",
    "SETUPS",
    "allowed_in_hand",
    "damage_index",
    "damage_index_exact",
    "dual_wield_factor_for",
    "haste_assumed",
    "setups_for",
    "shield_available",
]

SETUPS = ("1h-shield", "2h", "dw", "stick")
ROLES = ("balanced", "tank", "melee", "caster")
HANDS = ("primary", "secondary")

# classes with a casting role; a trio with one of them has the stick in Balanced
CASTER_CLASSES = frozenset({"CLR", "DRU", "SHM", "NEC", "WIZ", "MAG", "ENC"})
# skills the client's skill caps name
ONE_HANDED_SKILLS = ("1H Slashing", "1H Blunt", "1H Piercing")
TWO_HANDED_SKILLS = ("2H Slashing", "2H Blunt", "2H Piercing")
DUAL_WIELD_SKILL = "Dual Wield"

BONUS_ONE_HANDED = Fraction(1, 2)  # of the delay, when the item lists no damage bonus
BONUS_TWO_HANDED = Fraction(67, 100)
BONUS_TWO_HANDED_DELAY_CAP = 50  # the delay a two-hander's fallback bonus counts: 0.67 x min(delay, 50)
DUAL_WIELD_FACTOR = Fraction(4, 5)  # the default chance that the off hand swings

_ROLE_SETUPS = {"tank": ("1h-shield", "2h", "dw"), "melee": ("2h", "dw"), "balanced": ("1h-shield", "2h", "dw")}


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


def setups_for(
    trio: Sequence[str], role: str, tables: Any, *, level: int | None = None, items: Iterable[Any] | None = None
) -> list[str]:
    """The setups ``role`` plays for ``trio`` at ``level``, in the fixed order of :data:`SETUPS`.

    ``tables.skillcap[(class, skill, level)]`` gives the client's skill caps; ``level`` defaults to
    ``tables.rules``' current level. ``items`` is the item pool, for :func:`shield_available` (None: a shield is
    assumed to exist). A role that ends up
    with nothing available gets ``["stick"]``, which always works.
    """
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; use one of {', '.join(ROLES)}")
    unknown = [code for code in trio if code not in CLASS_CODES]
    if unknown:
        raise ValueError(f"not class codes: {', '.join(map(str, unknown))}")
    if role == "caster":
        return ["stick"]
    if level is None:
        rules = getattr(tables, "rules", None)
        level = rules.get("level.current") if rules is not None else DEFAULT_LEVEL

    def has(*skills: str) -> bool:
        return any(tables.skillcap.get((code, skill, level), 0) > 0 for code in trio for skill in skills)

    available = {
        "1h-shield": has(*ONE_HANDED_SKILLS) and shield_available(trio, items),
        "2h": has(*TWO_HANDED_SKILLS),
        "dw": has(DUAL_WIELD_SKILL),
    }
    result = [setup for setup in _ROLE_SETUPS[role] if available[setup]]
    if role == "balanced" and any(code in CASTER_CLASSES for code in trio):
        result.append("stick")
    return result or ["stick"]


# ---- the damage index -----------------------------------------------------------------------------------------


def _check(hand: str, setup: str) -> None:
    if hand not in HANDS:
        raise ValueError(f"unknown hand {hand!r}; use one of {', '.join(HANDS)}")
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


def allowed_in_hand(item: Any, hand: str, setup: str) -> bool:
    """Whether ``setup`` lets ``item`` stand in ``hand``; whether the item fits the slot is for the caller.

    ``2h``: a two-hander in the primary hand and nothing in the secondary. ``dw``: a one-handed weapon in either
    hand. ``1h-shield``: a one-handed weapon in the primary hand, a shield in the secondary. ``stick``: anything. In
    every setup a two-hander is refused the secondary hand.
    """
    _check(hand, setup)
    if hand == "secondary" and _two_handed(item):
        return False
    if setup == "stick":
        return True
    if setup == "1h-shield" and hand == "secondary":
        return bool(getattr(item, "is_shield", False))
    if not _is_weapon(item):
        return False
    if setup == "2h":
        return hand == "primary" and bool(item.weapon.two_handed)
    return not item.weapon.two_handed


def _bonus(weapon: Any) -> Fraction:
    if weapon.bonus:
        return _frac(weapon.bonus)
    if weapon.two_handed:
        return BONUS_TWO_HANDED * min(_frac(weapon.delay), BONUS_TWO_HANDED_DELAY_CAP)
    return BONUS_ONE_HANDED * _frac(weapon.delay)


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


def damage_index_exact(
    item: Any, hand: str, setup: str, haste_pct: Any, rules: Any = None, *, dw_factor: Any = None
) -> Fraction:
    """What ``item`` adds in ``hand`` under ``setup`` at ``haste_pct`` percent haste, exactly (see above)."""
    _check(hand, setup)
    if setup == "stick" or not allowed_in_hand(item, hand, setup) or not _is_weapon(item):
        return Fraction(0)
    weapon = item.weapon
    haste = 1 + _frac(haste_pct) / 100
    damage, delay = _frac(weapon.dmg), _frac(weapon.delay)
    if hand == "secondary":
        return damage / delay * haste * _dual_wield_factor(rules, dw_factor)
    return (damage + _bonus(weapon)) / delay * haste


def damage_index(
    item: Any, hand: str, setup: str, haste_pct: Any, rules: Any = None, *, dw_factor: Any = None
) -> float:
    """:func:`damage_index_exact` as a float, the coefficient the model uses."""
    return float(damage_index_exact(item, hand, setup, haste_pct, rules, dw_factor=dw_factor))


def haste_assumed(profile: Any, items: Iterable[Any]) -> int:
    """The highest haste a kit of this pool can count: the spell haste on offer plus the best worn haste in the pool, up to the cap.
    (It is the ceiling of the hastes the truthful solve looks at, and the constant the bare builder takes when it is given none; the
    weapon term of a solve is paid the haste the kit really counts.)

    ``profile.haste_cap`` is 75 (85 with a Monk) and ``profile.spell_haste`` the haste of the scenario's buffs, with
    the 10 of Unbound Alacrity when the trio has a Monk (``Profile.haste_bonus``, already in ``spell_haste``).
    Only the best worn piece counts, and a negative worn haste counts for nothing.
    """
    best_worn = max((item.haste for item in items if item.haste > 0), default=0)
    return int(min(profile.haste_cap, max(profile.spell_haste, 0) + best_worn))
