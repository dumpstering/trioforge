"""Legacy compatibility: run a profile and a pool in the old JSON shapes through the exact builder.

The old tools described a character as a JSON profile and scored a kit as the *gain* over the naked character with the
same buffs. ``from_legacy(profile_json, pool_json, scenario)`` maps such a profile, its pool and one scenario onto what
``build_milp`` takes, and ``build`` / ``gain`` finish the job::

    profile, items, setup, buffset = from_legacy(profile_json, pool_json, scenario)
    milp = build(profile, items, setup, buffset)        # BuildOptions.legacy, explicit Any places, fixed hand items
    solution = solve(milp)
    score = gain(solution, profile)                      # solution value minus the value of the empty kit

The private regression compares that gain with the optimum the old tools recorded. This module is the one place that
knows the old shapes; the exact model knows only the two options it needs for them (``formulas.LegacyTerms``).

What is mapped
==============

* **The scenario** (a dict): ``preset`` (a name in the profile's ``presets`` or None), ``buffs`` (a name in ``buffs``;
  the first one when missing), ``weapons`` (a name in ``weapon_setups``; None leaves both hands empty), ``tier`` (0 to
  10, default 10), ``quest_tier`` (for items whose ``tier_rule`` is ``quest``), ``weights`` (over the preset),
  ``exclude`` (item ids to leave out: the caller's evidence filter), ``lore_unknown`` (``"lore"``, the default, or
  ``"nonlore"``: how an item with an unknown Lore flag is treated), ``any_rule`` (``"all"``, the default, or
  ``"armor"``), ``include_temporary`` and ``deity``. ``name`` and ``headline`` are labels and are ignored; any other
  key is refused.
* **The weights** are the profile's, then the preset's, then the scenario's. The keys the model does not know (``STR``,
  ``STA``, ``AGI``, ``WIS``, ``INT``) were weights on attributes: they live on in the curves. ``DEX`` too.
* **The attribute curves.** Each component ``{from, scale, breaks, slopes}`` of the profile's ``curves`` becomes a
  :class:`~trioforge.model.formulas.LegacyCurve` worth ``weight[from] x scale`` (``weight[attribute] x scale`` when
  ``from`` is null). An attribute with a weight and no curve gets the old stat term as a curve: STR, DEX, AGI and STA
  count in full to 255, then at their ``post255`` rate to 510; WIS, INT and CHA count linearly. HP, mana and END come
  in as flat gear points: the old profile put the class pools into its curves.
* **The armor class** is the old sheet, ``LegacySheet``: model ``"sheet"`` with its ``mult`` (4/3), ``nongear``, printed
  ``cap`` and ``ret``; model ``"gear"`` (the default) is the same sheet with ``mult`` 1, ``nongear`` 0 and the cap less
  ``buff_share``.
* **Buffs** become the always-on totals of the profile: attribute points, the spell haste, and the flat HP, mana, attack
  and regen points (constants that cancel in a gain). A buff's resists count toward the cap only when
  ``res.buffs_count_toward_cap`` says so. A buff's ``ac`` was never read by the old objective and is not carried.
* **Caps.** Worn regen is capped where ``caps`` says and linear elsewhere (a cap that never binds); resists are
  capped at ``res.cap`` per school; the haste cap is the profile's number, else 75.
* **The items.** An item is usable when one of the trio's classes may wear it (``ALL`` means every class), it is not
  ``temporary`` (unless asked), its ``deity`` text admits the scenario's deity (none given: every item), its
  ``required_level`` is not above the profile's level and its id is not in ``exclude``. Its numbers are the old tier
  view (below), not ``items.at_tier``: the old rule scales regen like any other stat.
* **The Any places** take every usable item that has a slot (``any_rule="all"``) or every non-weapon with an armor or
  jewelry slot (``"armor"``). The items carry ``ANY`` explicitly and :func:`build_options` asks the builder for explicit
  Any places, so nothing else is let in.
* **The hands.** The setup ``weapon_setups[weapons]`` names a PRIMARY and a SECONDARY entry: an item name (the item is
  fixed in that hand: its column is forced to 1), null (the hand stays empty) or a token: ``<free>`` (anything that
  fits the hand), ``<free-2h>`` / ``<free-1h>`` (primary: two-handers / one-handers), ``<shield>`` (secondary:
  non-weapons not marked ``shield: false``) and ``<held>`` (secondary: non-weapons). Only the items a hand may hold
  carry the hand's slot, so the builder's ``stick`` setup (any item in a hand, a two-hander empties the off hand) is
  the whole hand rule. The checks of the old resolver hold: a two-hander in the primary hand needs an empty off hand,
  ``<free-2h>`` likewise, a Lore weapon cannot fill both hands, a named item must be usable.

The old tier view
=================

``stat + max(n, stat x n // 10)`` for every stat, regen and resist above zero (a negative or zero one is
unchanged), worn haste ``+ n``, weight in tenths of a stone ``max(1, w - max(n, w x n // 10))`` with ``n`` the tier
(the quest tier for a quest reward when one is given; an item's own ``tier_override`` wins over both). The ``VOID``
mark is no resist.

What is refused
===============

A Monk worn-weight bonus (``monk`` true), per-school resist caps, an incomplete profile (no ``classes``, ``naked`` or
``weights``: the old defaults were one character's numbers), negative weights, an unknown preset, buff set or setup.
Totals below zero are not modelled the old linear way (an attribute total never gets there with a real naked
character).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Any

from trioforge.classes import CLASS_CODES
from trioforge.model import formulas as fm
from trioforge.model.formulas import LegacyCurve, LegacySheet, LegacyTerms, PoolSpec
from trioforge.model.items import SLOT_INSTANCES, ItemVec, WeaponVec
from trioforge.solver.model import BuildOptions, Milp, build_milp

if TYPE_CHECKING:  # (only the annotation of gain: importing this module needs no HiGHS)
    from trioforge.solver.solve import Solution

__all__ = ["SETUP", "LegacyProfile", "baseline", "build", "build_options", "from_legacy", "gain"]

#: the setup string every legacy scenario is built with: any item in a hand, a two-hander empties the off hand
SETUP = "stick"

ATTRIBUTES = fm.ATTRIBUTES
SCHOOLS = fm.SCHOOLS
HANDS = ("PRIMARY", "SECONDARY")
HAND_TOKENS = {"PRIMARY": ("<free>", "<free-2h>", "<free-1h>"), "SECONDARY": ("<free>", "<shield>", "<held>")}
ARMOR_SLOTS = (
    "HEAD", "FACE", "EAR", "NECK", "SHOULDERS", "ARMS", "BACK", "WRIST", "HANDS", "FINGER", "CHEST", "LEGS", "FEET",
    "WAIST",
)  # fmt: skip
OLD_WEIGHT_KEYS = frozenset(
    {"AC", "HP", "MANA", "END", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "ATK", "HASTE"}
    | {"HPREG", "MANAREG", "ENDREG", "SV"}
    | {f"SV_{school}" for school in SCHOOLS}
)  # fmt: skip
WEIGHT_ALIASES = {"MPREG": "MANAREG", "HPREGEN": "HPREG"}
KEPT_WEIGHTS = (
    "AC", "HP", "MANA", "END", "ATK", "HASTE", "HPREG", "MANAREG", "ENDREG", "SV", *(f"SV_{s}" for s in SCHOOLS),
)  # fmt: skip
OLD_POST255 = {"STR": Fraction(1, 4), "DEX": Fraction(1, 10), "AGI": Fraction(1, 4), "STA": Fraction(1, 4)}
REGEN_CAP_KEYS = {"HPREG": "HP", "MANAREG": "MANA", "ENDREG": "END"}
NEVER_BINDS = 10**9  # the cap of a regen stat the profile does not cap
SCENARIO_KEYS = frozenset(
    {"preset", "buffs", "weapons", "tier", "quest_tier", "weights", "exclude", "lore_unknown", "any_rule"}
    | {"include_temporary", "deity", "name", "headline"}
)  # fmt: skip
BUFF_FLATS = (
    ("hp", "HP"), ("mana", "MANA"), ("atk", "ATK"), ("hpreg", "HPREG"), ("manareg", "MANAREG"), ("endreg", "ENDREG"),
)  # fmt: skip
QUOTES = "`'" + "".join(chr(c) for c in (0x2018, 0x2019, 0x201B, 0x2032, 0xB4, 0xFFFD))


@dataclass(frozen=True)
class LegacyProfile(fm.EvalProfile):
    """An :class:`~trioforge.model.formulas.EvalProfile` that also carries the legacy terms of the profile and the fixed
    hand items of the scenario it was made for (``forced``: ``(group, item key)`` pairs, each worn once)."""

    legacy: LegacyTerms | None = None
    forced: tuple[tuple[str, str], ...] = ()


# ---- small helpers ----------------------------------------------------------------------------------------------


def _number(value: Any, where: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction, str)):
        raise ValueError(f"{where} must be a number, not {value!r}")
    try:
        return fm.fr(value)
    except (ValueError, ZeroDivisionError) as err:
        raise ValueError(f"{where} must be a number, not {value!r}") from err


def _non_negative(value: Any, where: str) -> Fraction:
    number = _number(value, where)
    if number < 0:
        raise ValueError(f"{where} must not be negative, not {value!r}")
    return number


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be an object, not {value!r}")
    return value


def _norm_name(text: Any, *, article: bool = True) -> str:
    """The old name key: lowercase, quotes dropped, every other run of non-alphanumerics one space, ``*`` as ``star``;
    a leading article is dropped unless ``article`` is false (a deity is compared with it)."""
    folded = unicodedata.normalize("NFKD", str(text))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()
    folded = "".join(ch for ch in folded if ch not in QUOTES).replace("*", " star ")
    key = " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())
    return re.sub(r"^(a|an|the) ", "", key) if article else key


def _whole(value: Any, where: str) -> int:
    number = _number(value, where)
    if number.denominator != 1:
        raise ValueError(f"{where} must be a whole number, not {value!r}")
    return int(number)


# ---- the profile -------------------------------------------------------------------------------------------------


def _read_curves(raw: Any) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for attr, comp in _mapping(raw, "curves").items():
        if attr not in ATTRIBUTES:
            raise ValueError(f"curves: {attr!r} is not an attribute (use {' '.join(ATTRIBUTES)})")
        parts = [comp] if isinstance(comp, Mapping) else list(comp)
        if not parts:
            raise ValueError(f"curves.{attr}: a list of components needs at least one")
        read = []
        for n, part in enumerate(parts):
            where = f"curves.{attr}[{n}]"
            part = _mapping(part, where)
            source = part.get("from")
            if source is not None:
                source = WEIGHT_ALIASES.get(str(source).upper(), str(source).upper())
                if source not in OLD_WEIGHT_KEYS:
                    raise ValueError(f"{where}.from: {part.get('from')!r} is neither null nor a weight key")
            scale = _non_negative(part.get("scale", 1), f"{where}.scale")
            breaks = [_number(b, f"{where}.breaks") for b in part.get("breaks", ())]
            slopes = [_number(s, f"{where}.slopes") for s in part.get("slopes", ())]
            LegacyCurve(attr, 1, breaks, slopes)  # checks the shape; the factor comes with the weights
            read.append({"from": source, "scale": scale, "breaks": breaks, "slopes": slopes})
        out[attr] = read
    return out


def _read_profile(raw: Any) -> dict[str, Any]:
    """The profile JSON as plain numbers (Fractions) with the old defaults filled in, or ValueError naming the key."""
    raw = _mapping(raw, "the profile")
    classes = raw.get("classes")
    if (
        not isinstance(classes, (list, tuple))
        or len(classes) != 3
        or len(set(classes)) != 3
        or any(c not in CLASS_CODES for c in classes)
    ):
        raise ValueError(f"classes must be three different class codes ({' '.join(CLASS_CODES)}), not {classes!r}")
    naked_raw = raw.get("naked")
    if not isinstance(naked_raw, Mapping) or any(a not in naked_raw for a in ATTRIBUTES):
        raise ValueError(f"naked must give the seven attributes ({' '.join(ATTRIBUTES)}), not {naked_raw!r}")
    naked = {a: _non_negative(naked_raw[a], f"naked.{a}") for a in ATTRIBUTES}
    level = _whole(raw.get("level", 50), "level")
    if level < 1:
        raise ValueError(f"level must be at least 1, not {level}")
    weights_raw = raw.get("weights")
    if not isinstance(weights_raw, Mapping) or not weights_raw:
        raise ValueError("weights are needed: the old defaults were one character's numbers and are not carried here")
    ac = _mapping(raw.get("ac", {}), "ac")
    model = ac.get("model", "gear")
    if model not in ("gear", "sheet"):
        raise ValueError(f'ac.model must be "gear" or "sheet", not {model!r}')
    ret = _number(ac.get("ret", Fraction(33, 100)), "ac.ret")
    if not 0 <= ret <= 1:
        raise ValueError(f"ac.ret must be from 0 to 1, not {ac.get('ret')!r}")
    cap = _non_negative(ac.get("cap", 439), "ac.cap")
    buff_share = _non_negative(ac.get("buff_share", 0), "ac.buff_share")
    if model == "sheet":
        if buff_share:
            raise ValueError("ac.buff_share belongs to the gear model; the sheet model has nongear")
        mult = _number(ac.get("mult", Fraction(4, 3)), "ac.mult")
        if mult <= 0:
            raise ValueError(f"ac.mult must be above 0, not {ac.get('mult')!r}")
        sheet = LegacySheet(mult, _non_negative(ac.get("nongear", 0), "ac.nongear"), cap, ret)
    else:
        if "mult" in ac or "nongear" in ac:
            raise ValueError('ac.mult and ac.nongear only apply to the "sheet" model, not to "gear"')
        sheet = LegacySheet(1, 0, max(cap - buff_share, Fraction(0)), ret)
    monk = raw.get("monk", "MNK" in classes)
    if not isinstance(monk, bool):
        raise ValueError(f"monk must be true or false, not {monk!r}")
    if monk:
        raise ValueError("the legacy Monk worn-weight bonus is not carried (monk is true): the profile must have none")
    haste_cap = raw.get("haste_cap")
    res = _mapping(raw.get("res", {}), "res")
    if _mapping(res.get("cap_per_school", {}), "res.cap_per_school"):
        raise ValueError("per-school resist caps (res.cap_per_school) are not carried: the model has one resist cap")
    buffs_raw = raw.get("buffs", {"solo": {}})
    if not isinstance(buffs_raw, Mapping) or not buffs_raw:
        raise ValueError("buffs must name at least one buff set")
    post_raw = _mapping(raw.get("post255", {}), "post255")
    return {
        "classes": list(classes),
        "naked": naked,
        "level": level,
        "weights": _read_weights(weights_raw, "weights"),
        "sheet": sheet,
        "haste_cap": None if haste_cap is None else _non_negative(haste_cap, "haste_cap"),
        "res_cap": _non_negative(res.get("cap", 150), "res.cap"),
        "res_buffs": bool(res.get("buffs_count_toward_cap", False)),
        "caps": _read_caps(raw.get("caps", {})),
        "curves": _read_curves(raw.get("curves", {})),
        "post255": {k: _non_negative(post_raw.get(k, v), f"post255.{k}") for k, v in OLD_POST255.items()},
        "presets": {
            n: _read_weights(w, f"presets.{n}") for n, w in _mapping(raw.get("presets", {}), "presets").items()
        },
        "setups": dict(_mapping(raw.get("weapon_setups", {}), "weapon_setups")),
        "buffs": dict(buffs_raw),
    }


def _read_caps(raw: Any) -> dict[str, Fraction]:
    caps = {}
    for key, value in _mapping(raw, "caps").items():
        if key not in REGEN_CAP_KEYS:
            raise ValueError(f"caps: {key!r} is not a worn regen stat (use {' '.join(REGEN_CAP_KEYS)})")
        caps[key] = _non_negative(value, f"caps.{key}")
    return caps


def _read_weights(raw: Any, where: str) -> dict[str, Fraction]:
    out: dict[str, Fraction] = {}
    for key, value in _mapping(raw, where).items():
        name = WEIGHT_ALIASES.get(str(key).upper(), str(key).upper())
        if name not in OLD_WEIGHT_KEYS:
            raise ValueError(f"{where}: unknown weight key {key!r}")
        if name in out:
            raise ValueError(f"{where}: weight {name} given twice")
        out[name] = _non_negative(value, f"{where}.{key}")
    return out


def _read_scenario(raw: Any) -> dict[str, Any]:
    raw = _mapping(raw, "the scenario")
    unknown = sorted(set(raw) - SCENARIO_KEYS)
    if unknown:
        raise ValueError(f"unknown scenario key {unknown[0]!r} (use {' '.join(sorted(SCENARIO_KEYS))})")
    tier = _whole(raw.get("tier", 10), "tier")
    if not 0 <= tier <= 10:
        raise ValueError(f"the tier must be from 0 to 10, not {tier}")
    quest = raw.get("quest_tier")
    if quest is not None:
        quest = _whole(quest, "quest_tier")
        if not 0 <= quest <= 10:
            raise ValueError(f"the quest tier must be from 0 to 10, not {quest}")
    lore_unknown = raw.get("lore_unknown", "lore")
    if lore_unknown not in ("lore", "nonlore"):
        raise ValueError(f"lore_unknown must be 'lore' or 'nonlore', not {lore_unknown!r}")
    any_rule = raw.get("any_rule", "all")
    if any_rule not in ("all", "armor"):
        raise ValueError(f"any_rule must be 'all' or 'armor', not {any_rule!r}")
    deity = raw.get("deity")
    return {
        "preset": raw.get("preset"),
        "buffs": raw.get("buffs"),
        "weapons": raw.get("weapons"),
        "tier": tier,
        "quest_tier": quest,
        "weights": _read_weights(raw.get("weights", {}), "the scenario's weights"),
        "exclude": frozenset(raw.get("exclude", ())),
        "lore_unknown": lore_unknown,
        "any_rule": any_rule,
        "include_temporary": bool(raw.get("include_temporary", False)),
        "deity": None if not deity else str(deity),
    }


# ---- weights, curves, buffs ---------------------------------------------------------------------------------------


def _merged_weights(profile: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Fraction]:
    weights = dict(profile["weights"])
    preset = scenario["preset"]
    if preset:
        if preset not in profile["presets"]:
            raise ValueError(f"unknown preset {preset!r} (use {', '.join(profile['presets']) or 'none defined'})")
        weights.update(profile["presets"][preset])
    weights.update(scenario["weights"])
    return weights


def _legacy_curves(profile: dict[str, Any], weights: Mapping[str, Fraction]) -> list[LegacyCurve]:
    """The profile's explicit components worth ``weight[from] x scale``, then the old stat terms of the attributes that
    have no curve, as curves."""
    curves = profile["curves"]
    out: list[LegacyCurve] = []
    for attr in ATTRIBUTES:
        for part in curves.get(attr, ()):
            source = part["from"]
            weight = weights.get(source, 0) if source else weights.get(attr, 0)
            factor = weight * part["scale"]
            if factor:
                out.append(LegacyCurve(attr, factor, part["breaks"], part["slopes"]))
    for attr in ("STR", "DEX", "AGI", "STA"):  # counted in full to 255, then at the post-255 rate to 510
        if attr not in curves and weights.get(attr, 0):
            out.append(LegacyCurve(attr, weights[attr], (255, 510), (1, profile["post255"][attr], 0)))
    for attr in ("WIS", "INT", "CHA"):  # worth the weight per point, linearly (the old linear terms)
        if attr not in curves and weights.get(attr, 0):
            out.append(LegacyCurve(attr, weights[attr], (), (1,)))
    return out


def _buff_set(profile: dict[str, Any], name: Any) -> dict[str, Any]:
    buffs = profile["buffs"]
    if name is None:
        name = next(iter(buffs))
    if name not in buffs:
        raise ValueError(f"unknown buff set {name!r} (use {', '.join(buffs)})")
    raw = _mapping(buffs[name], f"buffs.{name}")
    totals: dict[str, Any] = {}
    for attr, value in _mapping(raw.get("attrs", {}), f"buffs.{name}.attrs").items():
        if attr not in ATTRIBUTES:
            raise ValueError(f"buffs.{name}.attrs: {attr!r} is not an attribute")
        points = _number(value, f"buffs.{name}.attrs.{attr}")
        if points:
            totals[attr] = points
    spell = _non_negative(raw.get("spell_haste", 0), f"buffs.{name}.spell_haste")
    if spell:
        totals["HASTE"] = spell
    for key, label in BUFF_FLATS:
        value = _non_negative(raw.get(key, 0), f"buffs.{name}.{key}")
        if value:
            totals[label] = value
    counted = {}
    for school, value in _mapping(raw.get("sv", {}), f"buffs.{name}.sv").items():
        if school not in SCHOOLS:
            raise ValueError(f"buffs.{name}.sv: {school!r} is not a resist school")
        points = _non_negative(value, f"buffs.{name}.sv.{school}")
        if points and profile["res_buffs"]:  # a buff's resist counts toward the cap only where the profile says so
            counted[school] = points
    totals["SV"] = counted
    return totals


# ---- the items ---------------------------------------------------------------------------------------------------


def _tier_stat(base: int, n: int) -> int:
    """The old stat rule: ``base + max(n, base x n // 10)`` above zero, anything else unchanged."""
    return base + max(n, base * n // 10) if base > 0 else base


def _stat_value(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        raise ValueError(f"{where} must be a whole number, not {value!r}")
    return int(value)


def _weight10(weight: Any, tier: int) -> int:
    if weight is None:
        return 0
    tenths = int(Fraction(str(weight)) * 10 + Fraction(1, 2))
    return 0 if tenths <= 0 else max(1, tenths - max(tier, tenths * tier // 10))


def _tier_of(item: Mapping[str, Any], tier: int, quest_tier: int | None) -> int:
    chosen = quest_tier if (quest_tier is not None and item.get("tier_rule") == "quest") else tier
    override = item.get("tier_override")
    if override is not None:
        if isinstance(override, bool) or not isinstance(override, int) or not 0 <= override <= 10:
            raise ValueError(
                f"tier_override must be a whole number from 0 to 10, not {override!r} (item {item.get('id')})"
            )
        chosen = override
    return chosen


def _is_two_hander(item: Mapping[str, Any]) -> bool:
    return str((item.get("weapon") or {}).get("skill", "")).startswith("2H")


def _is_shield(item: Mapping[str, Any]) -> bool:
    """The old rule: an explicit ``shield`` marker decides, else a non-weapon that fits the off hand and has armor
    class."""
    if isinstance(item.get("shield"), bool):
        return item["shield"]
    return (
        not item.get("weapon") and "SECONDARY" in item.get("slots", ()) and (item.get("stats", {}).get("AC") or 0) > 0
    )


def _weapon(item: Mapping[str, Any]) -> WeaponVec | None:
    raw = item.get("weapon")
    if not raw:
        return None
    skill = raw.get("skill")
    bonus = raw.get("dmg_bonus")
    return WeaponVec(
        skill if isinstance(skill, str) else None,
        int(raw.get("dmg") or 0),
        int(raw.get("delay") or 0),
        None if bonus is None else int(bonus),
        _is_two_hander(item),
    )


def _lore(item: Mapping[str, Any], lore_unknown: str) -> bool:
    flag = item.get("lore")
    return flag is True or (flag is None and lore_unknown == "lore")


def _lore_key(item: Mapping[str, Any]) -> str:
    """What Lore and the columns are keyed on: the base item (an owned copy at another tier is the same Lore item)."""
    return item.get("base_id") or re.sub(r"@t\d+$", "", item["id"])


def _any_fits(item: Mapping[str, Any], rule: str) -> bool:
    slots = item.get("slots", ())
    if rule == "armor":
        return not item.get("weapon") and any(s in ARMOR_SLOTS for s in slots)
    return bool(slots)


def _usable(
    items: Iterable[Mapping[str, Any]], profile: dict[str, Any], scenario: dict[str, Any]
) -> list[Mapping[str, Any]]:
    trio = set(profile["classes"])
    out = []
    for item in items:
        classes = item["classes"] if "classes" in item else ["ALL"]
        if "ALL" not in classes and not trio & set(classes):
            continue
        if not scenario["include_temporary"] and "temporary" in (item.get("flags") or ()):
            continue
        want, locked = scenario["deity"], item.get("deity")
        if want and locked and _norm_name(want, article=False) not in _norm_name(locked, article=False):
            continue
        if item["id"] in scenario["exclude"]:
            continue
        required = item.get("required_level")
        if required is not None and required > profile["level"]:
            continue
        out.append(item)
    return out


# ---- the hands ---------------------------------------------------------------------------------------------------


def _hands(
    profile: dict[str, Any], name: Any, usable: Sequence[Mapping[str, Any]], lore_unknown: str
) -> tuple[dict[str, Mapping[str, Any]], dict[str, set[str]]]:
    """``(fixed, candidates)``: the item fixed in each named hand, and for each hand a token chooses the ids it may
    hold."""
    setups = profile["setups"]
    if name is None:
        return {}, {}
    if name not in setups:
        raise ValueError(f"unknown weapons setup {name!r} (use {', '.join(setups) or 'none defined'})")
    pair = setups[name]
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        raise ValueError(f"weapon_setups.{name} must be a [PRIMARY, SECONDARY] pair, not {pair!r}")
    by_name: dict[str, Mapping[str, Any]] = {}
    for item in usable:
        by_name.setdefault(_norm_name(item["name"]), item)
    fixed: dict[str, Mapping[str, Any]] = {}
    tokens: dict[str, str] = {}
    for hand, entry in zip(HANDS, pair):
        if entry is None:
            continue
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"weapon_setups.{name}: {hand} must be an item name, a token or null, not {entry!r}")
        if entry.startswith("<"):
            if entry not in HAND_TOKENS[hand]:
                raise ValueError(
                    f"weapon_setups.{name}: {entry!r} is not a {hand} token (use {' '.join(HAND_TOKENS[hand])})"
                )
            tokens[hand] = entry
        else:
            item = by_name.get(_norm_name(entry))
            if item is None:
                raise ValueError(f"weapons setup {name} needs {entry!r}, which is not among the usable items")
            fixed[hand] = item
    primary, secondary = pair
    if primary == "<free-2h>" and secondary is not None:
        raise ValueError(
            f"weapon_setups.{name}: <free-2h> leaves the SECONDARY hand empty, but SECONDARY is {secondary!r}"
        )
    two = fixed.get("PRIMARY")
    if two is not None and _is_two_hander(two) and secondary is not None:
        raise ValueError(
            f"weapons setup {name}: {two['name']} is a two-hander, which leaves the offhand empty, "
            f"but SECONDARY is {secondary!r}"
        )
    if (
        len(fixed) == 2
        and _lore_key(fixed["PRIMARY"]) == _lore_key(fixed["SECONDARY"])
        and _lore(fixed["PRIMARY"], lore_unknown)
    ):
        raise ValueError(f"a Lore weapon cannot be worn twice: {fixed['PRIMARY']['name']}")
    one_hander_only = "SECONDARY" in fixed  # a free primary hand cannot take a two-hander while the off hand is filled
    candidates = {
        hand: {it["id"] for it in usable if _may_hold(it, hand, token, one_hander_only)}
        for hand, token in tokens.items()
    }
    return fixed, candidates


def _may_hold(item: Mapping[str, Any], hand: str, token: str, one_hander_only: bool) -> bool:
    """Whether the token of a hand lets ``item`` fill it (the item must list the hand among its slots)."""
    if hand not in item.get("slots", ()):
        return False
    if hand == "PRIMARY":
        if token == "<free-2h>":
            return _is_two_hander(item)
        if token == "<free-1h>":
            return not _is_two_hander(item)
        return not (one_hander_only and _is_two_hander(item))  # <free>
    if token == "<shield>":
        return not item.get("weapon") and item.get("shield") is not False
    if token == "<held>":
        return not item.get("weapon")
    return True  # <free>


# ---- from_legacy ---------------------------------------------------------------------------------------------------


def from_legacy(
    profile_json: Mapping[str, Any],
    pool_json: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    scenario: Mapping[str, Any],
) -> tuple[LegacyProfile, list[ItemVec], str, None]:
    """Map an old profile, its pool and one scenario onto the inputs of ``build_milp``.

    Returns ``(profile, items, setup, buffset)``: a :class:`LegacyProfile` (an ``EvalProfile`` that also carries the
    legacy terms and the fixed hand items), the usable items as tier views, the setup string (:data:`SETUP`) and the
    buff set (None: the old buffs are constants, already in the profile). Build with :func:`build`, which supplies the
    options the legacy terms need. Nothing in the arguments is changed. Raises ``ValueError`` for an incomplete profile
    or scenario and for anything the module docstring says is refused.
    """
    profile = _read_profile(profile_json)
    sc = _read_scenario(scenario)
    raw_items = pool_json["items"] if isinstance(pool_json, Mapping) else pool_json
    weights = _merged_weights(profile, sc)
    per_school = [s for s in SCHOOLS if weights.get(f"SV_{s}")]
    if weights.get("SV") and (per_school or profile["res_buffs"]):
        # the old weight checks: one form of resist weight, and buffs count toward the cap only with the per-school form
        raise ValueError(
            "the resist weight SV (the sum of all schools) cannot be used together with per-school SV_* weights "
            "or with res.buffs_count_toward_cap"
        )
    buff_totals = _buff_set(profile, sc["buffs"])
    usable = _usable(raw_items, profile, sc)
    fixed, candidates = _hands(profile, sc["weapons"], usable, sc["lore_unknown"])

    items = []
    for raw in usable:
        slots = {s for s in raw.get("slots", ()) if s not in HANDS}
        for hand in HANDS:
            if raw["id"] in candidates.get(hand, ()) or (hand in fixed and fixed[hand]["id"] == raw["id"]):
                slots.add(hand)
        if _any_fits(raw, sc["any_rule"]):
            slots.add("ANY")
        items.append(_item(raw, sc, frozenset(slots)))

    curves = _legacy_curves(profile, weights)
    kept = {key: weights[key] for key in KEPT_WEIGHTS if weights.get(key)}
    caps = profile["caps"]
    eval_profile = LegacyProfile(
        level=profile["level"],
        naked=profile["naked"],
        weights=kept,
        pools={
            "HP": tuple(PoolSpec(c, 0, 0) for c in profile["classes"]),
            "MANA": (),
            "END": tuple(PoolSpec(c, 0, 0) for c in profile["classes"]),
        },
        buff_totals=buff_totals,
        haste_cap=75 if profile["haste_cap"] is None else profile["haste_cap"],
        softcap=(profile["sheet"].cap, profile["sheet"].ret),
        caps={
            "regen": {label: caps.get(key, NEVER_BINDS) for key, label in REGEN_CAP_KEYS.items()},
            "resist": profile["res_cap"],
        },
        legacy=LegacyTerms(curves, profile["sheet"]),
        forced=tuple((hand, _lore_key(fixed[hand])) for hand in HANDS if hand in fixed),
    )
    return eval_profile, items, SETUP, None


def _item(raw: Mapping[str, Any], sc: dict[str, Any], slots: frozenset[str]) -> ItemVec:
    tier = _tier_of(raw, sc["tier"], sc["quest_tier"])
    stats: dict[str, int] = {}
    haste = 0
    for key, value in (raw.get("stats") or {}).items():
        amount = _stat_value(value, f"item {raw['id']}: {key}")
        if not amount:
            continue
        if key == "HASTE":
            haste = amount + tier if amount > 0 else amount
        elif key in fm.ITEM_STATS:
            stats[key] = _tier_stat(amount, tier)
    sv = {}
    for school, value in (raw.get("sv") or {}).items():
        amount = _stat_value(value, f"item {raw['id']}: {school}")
        if amount and school in SCHOOLS:  # the VOID mark of an upgrade is no resist
            sv[school] = _tier_stat(amount, tier)
    classes = raw["classes"] if "classes" in raw else ["ALL"]
    return ItemVec(
        key=_lore_key(raw),
        name=raw["name"],
        slots=slots,
        classes=frozenset(CLASS_CODES) if "ALL" in classes else frozenset(classes),
        deity=None,
        lore=_lore(raw, sc["lore_unknown"]),
        stats=stats,
        sv=sv,
        haste=haste,
        weight10=_weight10(raw.get("wt"), tier),
        weapon=_weapon(raw),
        is_shield=not raw.get("weapon") and _is_shield(raw),
        tier=tier,
        weight_known=raw.get("wt") is not None,
    )


# ---- building and valuing -------------------------------------------------------------------------------------------


def build_options(profile: LegacyProfile) -> BuildOptions:
    """The options a legacy model is built with: the legacy terms, explicit Any places (the items name theirs), and no
    assumed haste (no weapon damage is scored)."""
    return BuildOptions(any_rule="explicit", haste_assumed=0, legacy=profile.legacy)


def build(profile: LegacyProfile, items: Sequence[ItemVec], setup: str = SETUP, buffset: Any = None) -> Milp:
    """``build_milp`` with :func:`build_options`, and every fixed hand item forced into its hand."""
    milp = build_milp(profile, items, setup, buffset, build_options(profile))
    for group, key in profile.forced:
        column = milp.index.get((group, key))
        if column is None:
            raise ValueError(f"the fixed item {key} has no column in {group}")
        milp.col_lb[column] = 1
    return milp


def baseline(profile: LegacyProfile) -> Fraction:
    """The value of the naked character with the buffs and nothing worn, not even a fixed hand item: what the old gain
    is measured from."""
    return fm.evaluate(profile, [None] * len(SLOT_INSTANCES), setup=SETUP, legacy=profile.legacy).F


def gain(solution: Solution, profile: LegacyProfile) -> float:
    """The old score of a solution: its exact value less :func:`baseline`, as a float."""
    if solution.breakdown is None:
        raise ValueError("the solution has no kit")
    return float(solution.breakdown.F - baseline(profile))
