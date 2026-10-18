"""The roles a trio is offered, and the weights of each role.

Which roles (:func:`roles_for`)
===============================

* **Balanced** is offered to every trio.
* **Tank** when the trio has a Warrior, a Paladin or a Shadow Knight.
* **Melee** when a class has the Offensive stance (Berserker, Bard, Beastlord, Monk, Paladin, Ranger, Rogue, Shadow
  Knight, Warrior).
* **Caster** when a class casts (Cleric, Druid, Shaman, Necromancer, Wizard, Magician, Enchanter): healing and nuking
  want the same stats, so they share this one role.

Every class is in exactly one of the last two groups, so every trio can play at least one template. A trio with
only **one** of the three keeps Balanced alone, and Balanced then carries that role's weights (the page shows
Balanced only); asking such a trio for the role itself is an error.

The weights (:func:`weights_for`)
=================================

The templates are ``roles.templates`` in ``rules/rules.json``: for each of ``tank``, ``melee`` and ``caster`` a
weight in HP-equivalents for HP, AC, MANA, ATK, DEX, HASTE, END, SV (per school) and CHA. The result of
:func:`weights_for` has the keys the evaluator reads:

* **Balanced** is the arithmetic mean of the templates the trio can play (all three for a Shadow Knight, Cleric
  and Shaman; Tank and Melee for a Paladin, Monk and Berserker; the one template of a pure caster). The mean is
  taken in exact fractions and rounded once.
* ``SV`` becomes the five schools, ``SV_FIRE`` ... ``SV_DISEASE`` (Corruption is never scored).
* The regen weights are ``HPREG``, ``MANAREG`` and ``ENDREG`` = ``10 ticks a minute x regen.value_minutes x`` the
  weight of the resource they return (HP, MANA, END).
* **Only reachable currencies are weighted.** A trio with no class that has a mana pool has no mana to gain, so its
  ``MANA`` and ``MANAREG`` weights are 0. (``mana_reachable`` says so explicitly; the default looks at
  ``mana.stat_by_class``.)
* The weapon damage weight ``DMG`` is set only when the rule ``weapons.damage_weight`` has a number. The rule is
  HP-equivalents per damage-index point *per unit of the role's ATK weight*, so the ``DMG`` of the Tank and Melee
  templates is that number times the template's own ``ATK`` weight, and the ``DMG`` of the Caster template is 0
  (its stick scores no damage, whatever its ATK weight is). Balanced averages those template weights like every
  other weight, the Caster's 0 included; it is not the rule times Balanced's own mean ``ATK``. A rules file whose
  value is null (the schema allows that while the rule is open, until test B18) sets no ``DMG`` weight, and weapons
  are then chosen for their stats alone.

Every weight is a non-negative number: a template that has a negative, missing, unknown or non-numeric entry is
refused, because the exactness proofs of the solver need non-negative weights.

The groups and the override (:data:`WEIGHT_GROUPS`, :func:`weights_override`)
===========================================================================

The reweight sliders of the site and the robustness seal move the same five **weight groups**: ``AC``; ``MANA``;
``ATK+HASTE`` (ATK, HASTE and DMG); ``SV`` (the five schools); ``regen`` (the three regen weights). A slider has three
positions, x0.5, x1 and x2 (:data:`MULTIPLIERS`); the seal tries the two that change something.

:func:`weights_override` is the one definition of how the sliders, custom weights and the regen window compose. All of
it is exact arithmetic on the decimals the weights are written as, rounded once to a float at the end:

1. **The weight in effect.** For each of the nine settable weights (HP AC MANA ATK DEX HASTE END CHA and SV, which sets
   the five schools; a school of its own beats SV) it is the custom value when there is one, else the role's own.
2. **Derived weights follow.** DMG is the role's own DMG times (ATK in effect / the role's own ATK): the rule
   ``weapons.damage_weight`` (600) times the ATK weight for Tank and Melee, 0 for Caster, the mean of the templates for
   Balanced. The regen weights are ``TICKS_PER_MINUTE x T x`` the weight in effect of the resource they return (HP,
   MANA, END); when ``regen_T`` is None, or equal to the T the role's weights were made with (to one part in
   :data:`REGEN_T_MATCH`, which is float noise), the role's own regen weights are kept to the last digit and only follow
   the resource weight in effect, so that nothing moves unless something was asked.
3. **The sliders come last.** A slider multiplies every weight of its group, derived ones included, whatever is
   behind it: a custom ATK of 3 under ATK+HASTE x2 is an ATK of 6 and a DMG of 600 x 6 for a Tank. The MANA slider
   scales MANA only, and the regen slider scales the regen weights only, as in the robustness variants.
4. **Reachable currencies only.** MANA and MANAREG are 0 for a trio with no mana pool, whatever else is asked.

Each step reads only the values of the step before and the sliders are the last multiplication, so the three overrides
(custom weights, T, sliders) touch independent parts of the result and the order in which a caller thinks of them, or
lists them in its tables, cannot matter. With every slider at x1, no custom weights and the role's own window the result
is the role's weights exactly.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any

from trioforge.classes import CLASS_CODES
from trioforge.model.formulas import SCHOOLS, WEIGHT_KEYS, fr

__all__ = [
    "CASTER_CLASSES",
    "CUSTOM_KEYS",
    "CUSTOM_MAX",
    "DAMAGE_FOLLOWS",
    "DERIVED_KEYS",
    "MANA_KEYS",
    "MELEE_CLASSES",
    "MULTIPLIERS",
    "REGEN_SOURCES",
    "REGEN_T_MATCH",
    "REGEN_T_MAX",
    "ROLES",
    "TANK_CLASSES",
    "TEMPLATE_KEYS",
    "TICKS_PER_MINUTE",
    "WEIGHT_GROUPS",
    "check_trio",
    "roles_for",
    "weights_for",
    "weights_override",
]

ROLES = ("balanced", "tank", "melee", "caster")
TEMPLATES = ("tank", "melee", "caster")

TANK_CLASSES = frozenset({"WAR", "PAL", "SHD"})
MELEE_CLASSES = frozenset({"BER", "BRD", "BST", "MNK", "PAL", "RNG", "ROG", "SHD", "WAR"})  # the Offensive stance
CASTER_CLASSES = frozenset({"CLR", "DRU", "SHM", "NEC", "WIZ", "MAG", "ENC"})
_GROUPS = (("tank", TANK_CLASSES), ("melee", MELEE_CLASSES), ("caster", CASTER_CLASSES))

#: the entries of a template in ``roles.templates``
TEMPLATE_KEYS = ("HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "SV", "CHA")
TICKS_PER_MINUTE = 10  # one regen tick every six seconds
_DAMAGE_TEMPLATES = frozenset({"tank", "melee"})  # the templates that score weapon damage

#: the positions of a reweight slider: half, as it is, double
MULTIPLIERS = (0.5, 1, 2)
#: the weight groups, in the order of the robustness variants; a group's keys that a role does not weigh are left alone
WEIGHT_GROUPS: dict[str, tuple[str, ...]] = {
    "AC": ("AC",),
    "MANA": ("MANA",),
    "ATK+HASTE": ("ATK", "HASTE", "DMG"),
    "SV": ("SV", *(f"SV_{school}" for school in SCHOOLS)),
    "regen": ("HPREG", "MANAREG", "ENDREG"),
}
#: the weights a caller may set: the nine of a template, and a resist school of its own
CUSTOM_KEYS = (*TEMPLATE_KEYS, *(f"SV_{school}" for school in SCHOOLS))
CUSTOM_MAX = 1000  # the largest custom weight, in HP-equivalents a point (the largest template weight is 6)
REGEN_T_MAX = 60  # the longest regen window, in minutes
#: a window this close to the role's own (relative) is the role's own: the stored weights are rounded to floats
REGEN_T_MATCH = Fraction(1, 10**12)
#: the weights that follow another weight instead of being set: DMG follows ATK, a regen weight its resource
DERIVED_KEYS = ("DMG", "HPREG", "MANAREG", "ENDREG")
DAMAGE_FOLLOWS = "ATK"
REGEN_SOURCES = {"HPREG": "HP", "MANAREG": "MANA", "ENDREG": "END"}  # a regen weight and the resource it returns
MANA_KEYS = ("MANA", "MANAREG")  # the weights that are 0 for a trio with no mana pool
_GROUP_OF = {key: group for group, keys in WEIGHT_GROUPS.items() for key in keys}
_ZERO, _ONE = Fraction(0), Fraction(1)


def check_trio(trio: Any) -> tuple[str, ...]:
    """``trio`` as a tuple of three different class codes; ``ValueError`` for anything else."""
    try:
        codes = tuple(trio)
    except TypeError:
        codes = ()
    if len(codes) != 3 or any(code not in CLASS_CODES for code in codes) or len(set(codes)) != 3:
        raise ValueError(f"a trio is three different class codes from {' '.join(CLASS_CODES)}, not {trio!r}")
    return codes


def _templates(codes: Sequence[str]) -> list[str]:
    """The templates a trio can play: ``tank``, ``melee`` and ``caster`` where it has such a class."""
    members = set(codes)
    return [name for name, group in _GROUPS if members & group]


def roles_for(trio: Sequence[str]) -> list[str]:
    """The roles offered to ``trio``, in the fixed order of :data:`ROLES`.

    ``balanced`` always; ``tank``, ``melee`` and ``caster`` as well when the trio can play more than one template.
    """
    templates = _templates(check_trio(trio))
    return ["balanced", *(templates if len(templates) > 1 else [])]


def _number(name: str, value: Any) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a number of at least 0, not {value!r}")
    return fr(value)


def _template(templates: Any, name: str) -> dict[str, Fraction]:
    if not isinstance(templates, Mapping) or not isinstance(templates.get(name), Mapping):
        raise ValueError(f"roles.templates has no {name!r} template")
    row = templates[name]
    missing, unknown = sorted(set(TEMPLATE_KEYS) - set(row)), sorted(set(row) - set(TEMPLATE_KEYS))
    if missing or unknown:
        raise ValueError(f"roles.templates {name!r}: missing {missing}, unknown {unknown}")
    return {key: _number(f"roles.templates {name} {key}", row[key]) for key in TEMPLATE_KEYS}


def weights_for(
    trio: Sequence[str], role: str, rules: Any, *, mana_reachable: bool | None = None
) -> dict[str, float]:
    """The weights of ``role`` for ``trio`` (see the module docstring), as a new dict of floats.

    Raises ``ValueError`` for a trio that is not three class codes, for a role the trio is not offered
    (:func:`roles_for`) and for a template or rule value that is not a usable weight. ``mana_reachable`` says
    whether the trio has a mana pool; when it is None, a class in ``mana.stat_by_class`` decides.
    """
    codes = check_trio(trio)
    offered = roles_for(codes)
    if role not in offered:
        raise ValueError(f"role {role!r} is not offered to {' '.join(codes)}; its roles are {', '.join(offered)}")
    names = _templates(codes) if role == "balanced" else [role]
    rows = [_template(rules.get("roles.templates"), name) for name in names]
    mean = {key: sum((row[key] for row in rows), Fraction(0)) / len(rows) for key in TEMPLATE_KEYS}

    minutes = _number("regen.value_minutes", rules.get("regen.value_minutes"))
    damage = rules.get("weapons.damage_weight")
    if damage is not None:
        damage = _number("weapons.damage_weight", damage)
    if mana_reachable is None:
        mana_classes = {code for classes in rules.get("mana.stat_by_class").values() for code in classes}
        mana_reachable = any(code in mana_classes for code in codes)

    weights = {key: mean[key] for key in TEMPLATE_KEYS if key != "SV"}
    if not mana_reachable:
        weights["MANA"] = Fraction(0)
    for school in SCHOOLS:
        weights[f"SV_{school}"] = mean["SV"]
    per_point = TICKS_PER_MINUTE * minutes
    weights["HPREG"] = per_point * weights["HP"]
    weights["MANAREG"] = per_point * weights["MANA"]
    weights["ENDREG"] = per_point * weights["END"]
    if damage is not None:
        # the rule is per unit of ATK weight: each template that scores damage is worth the rule times its own ATK
        scored = sum(
            (damage * row["ATK"] for name, row in zip(names, rows, strict=True) if name in _DAMAGE_TEMPLATES),
            Fraction(0),
        )
        weights["DMG"] = scored / len(names)
    return {key: float(value) for key, value in weights.items()}


# ---- the composed override -----------------------------------------------------------------------------------------


def _in_range(value: Any, low: Fraction, high: Fraction) -> Fraction | None:
    """``value`` as an exact fraction when it is a finite number (not a bool) from ``low`` to ``high``, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    number = fr(value)
    return number if low <= number <= high else None


def weights_override(
    base_weights: Mapping[str, Any],
    multipliers: Mapping[str, Any] | None = None,
    custom: Mapping[str, Any] | None = None,
    regen_T: Any = None,
    *,
    mana_reachable: bool | None = None,
) -> dict[str, float]:
    """The weights after the sliders, the custom weights and the regen window, composed as the module docstring says.

    ``base_weights`` are the role's weights (:func:`weights_for`, or a profile's ``weights``). ``multipliers`` maps a
    group of :data:`WEIGHT_GROUPS` to one of :data:`MULTIPLIERS` (a group left out is x1). ``custom`` maps a name of
    :data:`CUSTOM_KEYS` or ``SV`` (all five schools) to a weight from 0 to :data:`CUSTOM_MAX`. ``regen_T`` is the regen
    window in minutes, from 0 to :data:`REGEN_T_MAX`, or None for the role's own. ``mana_reachable`` says whether the
    trio has a mana pool; None reads it from the base (``weights_for`` gives a trio with no mana pool a MANA of 0).

    The result is a new dict of floats with the keys of the base (and the custom weights the base lacks, sorted after
    them). The order of the arguments' tables does not matter. Raises ``ValueError`` for a base that is not a table of
    known non-negative numbers, a slider group that does not exist, a multiplier that is not one of the three
    positions, a custom weight that is not settable or out of range, and a window out of range.
    """
    if not isinstance(base_weights, Mapping):
        raise ValueError(f"base weights must be a table of weights by name, not {type(base_weights).__name__}")
    base: dict[str, Fraction] = {}
    for key, value in base_weights.items():
        number = _in_range(value, _ZERO, Fraction(10**15))
        if key not in WEIGHT_KEYS or number is None:
            raise ValueError(f"base weights hold a name or a value that is not a weight: {key!r}: {value!r}")
        base[key] = number

    if multipliers is None:
        multipliers = {}
    if not isinstance(multipliers, Mapping):
        raise ValueError(f"multipliers must be a table of slider positions by group, not {type(multipliers).__name__}")
    sliders = dict.fromkeys(WEIGHT_GROUPS, _ONE)
    allowed = {fr(position) for position in MULTIPLIERS}
    for group, value in multipliers.items():
        if not isinstance(group, str) or group not in WEIGHT_GROUPS:
            raise ValueError(f"unknown slider group {group!r}; the groups are {', '.join(WEIGHT_GROUPS)}")
        position = _in_range(value, _ZERO, Fraction(2))
        if position is None or position not in allowed:
            positions = ", ".join(map(str, MULTIPLIERS))
            raise ValueError(f"the multiplier for {group} must be one of {positions}, not {value!r}")
        sliders[group] = position

    if custom is None:
        custom = {}
    if not isinstance(custom, Mapping):
        raise ValueError(f"custom must be a table of weights by name, not {type(custom).__name__}")
    values: dict[str, Fraction] = {}
    for key, value in custom.items():
        if not isinstance(key, str) or (key != "SV" and key not in CUSTOM_KEYS):
            raise ValueError(f"custom weight {key!r} cannot be set; use {', '.join(CUSTOM_KEYS)}")
        number = _in_range(value, _ZERO, Fraction(CUSTOM_MAX))
        if number is None:
            raise ValueError(f"custom weight {key} must be a number from 0 to {CUSTOM_MAX}, not {value!r}")
        values[key] = number

    minutes = None
    if regen_T is not None:
        minutes = _in_range(regen_T, _ZERO, Fraction(REGEN_T_MAX))
        if minutes is None:
            raise ValueError(f"regen_T must be a number of minutes from 0 to {REGEN_T_MAX}, not {regen_T!r}")

    # 1. the weight in effect: the custom value when there is one (a school of its own beats SV), else the role's own
    effective = dict(base)
    if "SV" in values:
        for school in SCHOOLS:
            effective[f"SV_{school}"] = values["SV"]
        if "SV" in base:
            effective["SV"] = values["SV"]
    effective.update({key: number for key, number in values.items() if key != "SV"})

    # 3. the sliders, the last multiplication, on the weights in effect
    result: dict[str, Fraction] = {}
    for key, number in effective.items():
        if key not in DERIVED_KEYS:
            group = _GROUP_OF.get(key)
            result[key] = number * sliders[group] if group is not None else number

    # 2. the derived weights follow the weights in effect, then their sliders
    if "DMG" in base:
        own_attack = base.get(DAMAGE_FOLLOWS, _ZERO)
        follows = effective.get(DAMAGE_FOLLOWS, _ZERO) / own_attack if own_attack > 0 else _ONE
        result["DMG"] = base["DMG"] * follows * sliders["ATK+HASTE"]
    for regen, resource in REGEN_SOURCES.items():
        if regen not in base:
            continue
        own, own_resource = base[regen], base.get(resource, _ZERO)
        own_window = minutes is None or (
            own > 0 and abs(TICKS_PER_MINUTE * minutes * own_resource - own) <= own * REGEN_T_MATCH
        )
        if own_window:
            value = own * effective.get(resource, _ZERO) / own_resource if own_resource > 0 else own
        else:
            value = TICKS_PER_MINUTE * minutes * effective.get(resource, _ZERO)
        result[regen] = value * sliders["regen"]

    # 4. a currency the trio cannot reach has no weight
    if mana_reachable is None:
        mana_reachable = base.get("MANA", _ZERO) > 0
    if not mana_reachable:
        result.update({key: _ZERO for key in MANA_KEYS if key in result})

    order = [*base, *sorted(key for key in result if key not in base)]
    return {key: float(result[key]) for key in order if key in result}
