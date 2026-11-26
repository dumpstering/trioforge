"""The builds a trio is offered, and the weights of each build.

A **build** is a way a trio plays: who stands in front, and where the damage comes from. Its id is the word of the code and
of the page's ``role=`` link (the code keeps the word "role"; a reader sees "Build"). The ids, in the order the page shows them:
``tank`` ("Tank"), ``shield`` ("Shield caster"), ``melee`` ("Melee damage"), ``ranged`` ("Archer"), ``castertank`` ("Caster tank")
and ``caster`` ("Caster"). There is no Balanced build: a blend of builds is no way to play.

Class groups (:data:`TANK_CLASSES`, :data:`CASTER_CLASSES`, :data:`MELEE_CLASSES`, :data:`PET_CLASSES`): **TK** = Warrior, Paladin,
Shadow Knight (a taunt and the Defensive stance); **SPELL** = Cleric, Druid, Shaman, Wizard, Necromancer, Magician, Enchanter;
**MELEE** = Warrior, Paladin, Shadow Knight, Monk, Rogue, Berserker, Bard, Beastlord, Ranger (the Offensive stance); **PETC** =
Magician, Necromancer, Beastlord, Enchanter (a pet is the front or the damage).

Which builds (:func:`roles_for`)
================================

* **tank** when the trio has a TK class;
* **shield** when it has a TK class and at least one SPELL class (a tank class whose damage is spells);
* **melee** when it has a MELEE class;
* **ranged** when it has a Ranger and, with a pool, the pool has a bow a class of the trio can shoot (``bow``, below);
* **castertank** when it has no TK class and at least two SPELL classes (a caster who tanks with no tank class);
* **caster** when it has at least one SPELL class and either no MELEE class or at least two SPELL classes.

Every trio is offered at least one build and at most four (a test runs all 560 trios). The weapon setups of each build are in
:mod:`trioforge.model.weapons`.

The opening build (:func:`opening_role`) is the build the trio's page opens on, the first rule that matches: a Ranger with no TK class
and the Archer build offered, ``ranged``; a TK class, ``shield`` for a Shadow Knight or a Paladin with two SPELL classes and for a
Warrior with a Wizard and another SPELL class, else ``tank``; no TK class and either a Monk or at most one SPELL class, ``melee``
(a Monk is the front of its trio); no TK class and two or three SPELL classes, ``caster`` when a PETC class is present, else
``castertank``. The function raises for a trio that no rule matches, and a test runs all 560 trios.

The weights (:func:`weights_for`)
=================================

The templates are ``roles.templates`` in ``rules/rules.json``: for each of ``tank``, ``shield``, ``melee``, ``castertank`` and
``caster`` a weight in HP-equivalents for HP, AC, MANA, ATK, DEX, HASTE, END, SV (per school) and CHA. The ``ranged`` build's is the
Melee template with the factors of the rule ``roles.ranged_template`` on some of its weights. The result of :func:`weights_for` has
the keys the evaluator reads:

* ``SV`` becomes the five schools, ``SV_FIRE`` ... ``SV_DISEASE`` (Corruption is never scored).
* The regen weights are ``10 ticks a minute x regen.value_minutes x`` the weight of the resource they return (HP, MANA, END).
* **Only reachable currencies are weighted.** A trio with no class that has a mana pool has no mana to gain, so its
  ``MANA`` and ``MANAREG`` weights are 0. (``mana_reachable`` says so explicitly; the default looks at
  ``mana.stat_by_class``.)
* The weapon damage weight ``DMG`` is set only when the rule ``weapons.damage_weight`` has a number. It is that number times the
  build's own ``ATK`` weight times the build's **weapon factor** (the rule ``roles.weapon_factor``: a multiplier for each build,
  0 for a build whose weapon is a stick that carries stats). One mechanism for every build: a build that scores no weapon damage
  has the factor 0. A rules file whose damage weight is null (the schema allows that while the rule is open, until test B18)
  sets no ``DMG`` weight, and weapons are then chosen for their stats alone.

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
   ``weapons.damage_weight`` (450) times the ATK weight and the weapon factor of the build (0 for a build that scores no
   weapon damage). The regen weights are ``TICKS_PER_MINUTE x T x`` the weight in effect of the resource they return (HP,
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
    "PET_CLASSES",
    "REGEN_SOURCES",
    "REGEN_T_MATCH",
    "REGEN_T_MAX",
    "REMOVED_ROLES",
    "ROLES",
    "TANK_CLASSES",
    "TEMPLATES",
    "TEMPLATE_KEYS",
    "TICKS_PER_MINUTE",
    "WEIGHT_GROUPS",
    "check_trio",
    "opening_role",
    "roles_for",
    "weapon_factor",
    "weights_for",
    "weights_override",
]

ROLES = ("tank", "shield", "melee", "ranged", "castertank", "caster")
TEMPLATES = ("tank", "shield", "melee", "castertank", "caster")  # the builds that have a template of their own in roles.templates ("ranged" is derived from "melee")
RANGER = "RNG"
#: the builds that only a pool offers: no setup is assumed for them with no pool to read (a bow is never assumed, as a shield is), so they have no profile without an evidence level
POOL_ROLES = frozenset({"ranged"})
#: the roles of an earlier release that no results folder of this one holds: Balanced blended the others (a reader of results refuses a folder that has one)
REMOVED_ROLES = frozenset({"balanced"})

TANK_CLASSES = frozenset({"WAR", "PAL", "SHD"})  # TK: a taunt and the Defensive stance
MELEE_CLASSES = frozenset({"BER", "BRD", "BST", "MNK", "PAL", "RNG", "ROG", "SHD", "WAR"})  # the Offensive stance
CASTER_CLASSES = frozenset({"CLR", "DRU", "SHM", "NEC", "WIZ", "MAG", "ENC"})  # SPELL
PET_CLASSES = frozenset({"MAG", "NEC", "BST", "ENC"})  # PETC: a pet is the front or the damage

#: the entries of a template in ``roles.templates``
TEMPLATE_KEYS = ("HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "SV", "CHA")
TICKS_PER_MINUTE = 10  # one regen tick every six seconds

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


def roles_for(trio: Sequence[str], bow: bool | None = False) -> list[str]:
    """The builds offered to ``trio``, in the fixed order of :data:`ROLES` (the module docstring has the rules).

    ``bow`` says whether the pool the trio is solved with has a bow that a class of it can shoot
    (:func:`trioforge.model.weapons.bow_available`): True leaves ``ranged`` in for a trio with a Ranger and False (the default: no pool to
    read, and a bow is never assumed) leaves it out, for the Archer build plays the bow and nothing else; None, for a caller that asks about
    the builds of the trio before any pool is in question (the weights of a build, the effects layer, the order of the chunks of a run),
    leaves it in.
    """
    members = set(check_trio(trio))
    tank, spell, melee = members & TANK_CLASSES, members & CASTER_CLASSES, members & MELEE_CLASSES
    offered = {
        "tank": bool(tank),
        "shield": bool(tank) and bool(spell),
        "melee": bool(melee),
        "ranged": RANGER in members and bow is not False,
        "castertank": not tank and len(spell) >= 2,
        "caster": bool(spell) and (not melee or len(spell) >= 2),
    }
    return [role for role in ROLES if offered[role]]


def opening_role(trio: Sequence[str], offered: Sequence[str] | None = None) -> str:
    """The build a trio's page opens on (the module docstring has the rules, in order; the first that matches wins).

    ``offered`` is the builds the trio is offered (:func:`roles_for`; None: every build it can have, the Archer build included for a
    Ranger, as a caller with no pool asks). The Archer rule is skipped when the Archer build is not offered. The answer is always one of
    ``offered``; ``ValueError`` for a trio that no rule matches, or whose rule names a build that is not offered (neither happens for any of
    the 560 trios: a test runs them all).
    """
    codes = check_trio(trio)
    members = set(codes)
    available = list(roles_for(codes, bow=None) if offered is None else offered)
    tank, spell = members & TANK_CLASSES, members & CASTER_CLASSES
    if RANGER in members and not tank and "ranged" in available:
        found = "ranged"
    elif tank:
        spell_knight = len(spell) >= 2 and (bool({"SHD", "PAL"} & members) or ("WAR" in members and "WIZ" in members))
        found = "shield" if spell_knight else "tank"
    elif "MNK" in members or len(spell) <= 1:
        found = "melee"  # (a Monk is the front of its trio)
    elif len(spell) >= 2:
        found = "caster" if members & PET_CLASSES else "castertank"
    else:  # (unreachable: every class is a SPELL class or a MELEE class, so the rules above cover every trio)
        raise ValueError(f"no opening build matches the trio {' '.join(codes)}")
    if found not in available:
        raise ValueError(f"the opening build of {' '.join(codes)} is {found!r}, which it is not offered ({', '.join(available)})")
    return found


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


def weapon_factor(rules: Any, role: str) -> Fraction:
    """The weapon damage factor of ``role`` (the rule ``roles.weapon_factor``: a multiplier on the weapon damage weight, 0 for a build whose weapon only carries stats)."""
    table = rules.get("roles.weapon_factor")
    if not isinstance(table, Mapping) or set(table) != set(ROLES):
        raise ValueError(f"roles.weapon_factor is a factor for each of {', '.join(ROLES)}, not {table!r}")
    return _number(f"roles.weapon_factor {role}", table[role])


def _ranged_template(rules: Any) -> dict[str, Fraction]:
    """The Archer template: the Melee template as the rules have it now, each weight named in ``roles.ranged_template`` times its factor."""
    base = _template(rules.get("roles.templates"), "melee")
    factors = rules.get("roles.ranged_template")
    if not isinstance(factors, Mapping) or not factors or set(factors) - set(TEMPLATE_KEYS):
        raise ValueError(f"roles.ranged_template is a factor for each of some of {', '.join(TEMPLATE_KEYS)}, not {factors!r}")
    return {key: base[key] * _number(f"roles.ranged_template {key}", factors[key]) if key in factors else base[key] for key in TEMPLATE_KEYS}


def weights_for(
    trio: Sequence[str], role: str, rules: Any, *, mana_reachable: bool | None = None
) -> dict[str, float]:
    """The weights of the build ``role`` for ``trio`` (see the module docstring), as a new dict of floats.

    Raises ``ValueError`` for a trio that is not three class codes, for a build the trio is not offered
    (:func:`roles_for`) and for a template or rule value that is not a usable weight. ``mana_reachable`` says
    whether the trio has a mana pool; when it is None, a class in ``mana.stat_by_class`` decides.
    """
    codes = check_trio(trio)
    offered = roles_for(codes, bow=None)  # (the weights of a role do not depend on a pool)
    if role not in offered:
        raise ValueError(f"role {role!r} is not offered to {' '.join(codes)}; its roles are {', '.join(offered)}")
    row = _ranged_template(rules) if role == "ranged" else _template(rules.get("roles.templates"), role)

    minutes = _number("regen.value_minutes", rules.get("regen.value_minutes"))
    damage = rules.get("weapons.damage_weight")
    if damage is not None:
        damage = _number("weapons.damage_weight", damage)
    if mana_reachable is None:
        mana_classes = {code for classes in rules.get("mana.stat_by_class").values() for code in classes}
        mana_reachable = any(code in mana_classes for code in codes)

    weights = {key: row[key] for key in TEMPLATE_KEYS if key != "SV"}
    if not mana_reachable:
        weights["MANA"] = Fraction(0)
    for school in SCHOOLS:
        weights[f"SV_{school}"] = row["SV"]
    per_point = TICKS_PER_MINUTE * minutes
    weights["HPREG"] = per_point * weights["HP"]
    weights["MANAREG"] = per_point * weights["MANA"]
    weights["ENDREG"] = per_point * weights["END"]
    if damage is not None:
        # the rule is per unit of ATK weight: the build is worth the rule times its own ATK times its weapon factor (0: no weapon damage)
        weights["DMG"] = damage * row["ATK"] * weapon_factor(rules, role)
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
