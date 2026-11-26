"""The browser bundle and the item table: what the site's engine reads, and the Python reference that reads it back.

``python -m trioforge.export.browser --out build/browser --trio pal-mnk-ber`` writes ``bundles/<trio>-l<level>.json``
for each trio asked for, one ``items.json``, and a size report (bytes and gzip bytes of each file). The catalog it reads
makes the item table, and its evidence levels decide the weapon setups of each level in every bundle.

The precompute writes the same two files beside its shards (``<trio>/engine-l<level>.json`` and ``items.json``), made with
:func:`bundle` and :func:`items` from the catalog document of the run and the private seen flags of the run (``seen``): a seen
item is strict in the item table and in the pools the bundle's weapon setups come from, as it is in the pools the run solves
(a patch or research removal still hides it). :func:`render_bundle` and :func:`render_items` give the text of the two files.
The precompute also puts a **fingerprint of its inputs** in both (``inputs``, an optional field: see "The fingerprint" below), so that the
site build can tell an item table and a bundle that were made from other catalogs or from other flags merged into the levels.

The bundle (:func:`bundle`)
===========================

One JSON object per trio and level, with everything the engine needs to rebuild any profile and to run the formulas:

====================  ==============================================================================================
``version``           the format number (1)
``data_release``      ``data-YYYY-MM-DD`` of the data it was made with (the catalog's, when the command has one)
``rules_version``     the version of ``rules/rules.json``
``trio``, ``level``   the class codes in class order and the character level
``profile_common``    every field of ``Profile.to_dict()`` that does not vary with the race, the role or the buff
                      set, with the defaults of the two inputs that are not model rows: the ``evidence`` label
                      (``strict``) and the ``aa`` choices; ``deity`` is null
``evidence_levels``   the evidence labels a profile may carry (``strict``, ``wiki``)
``races``             in the order of the pages (the creation-legal races first): ``code``, ``name``, ``legal``,
                      and the fields that vary with the race: ``naked`` and ``iksar_ac``
``roles``             by role, in the order the trio is offered them: the ``weights``, the weapon ``setups`` and the
                      ``setups_by_evidence`` (see "Weapon setups" below)
``buffs``             for each of ``own``, ``group``, ``group+enchanter`` and ``raid``: the ``buff_totals`` and the
                      ``spell_haste`` of the profile, and the resolved buff set (``set``: the ids of the
                      ``always_on`` and the ``optional`` buffs, the ``conflicts`` as ``[a, b, reasons]``, the
                      ``cliques``, the ``cardinality`` and the ``dropped`` buffs as ``[id, name, reason, by]``); and,
                      beside each, its twin under ``own+haste``, ``group+haste``, ``group+enchanter+haste`` and
                      ``raid+haste``: the same buffs with the haste of the spells in them, which is the set (and the
                      profile) a kit is chosen with when the rule ``haste.assume_spell`` is true. While the rule is
                      false the first four have no spell haste (``spell_haste`` is the 10 of a Monk's Unbound Alacrity,
                      or 0) and the twins are what the reader's "I have a haste spell" solves with in the browser
``buff_table``        by spell id, each buff the sets use: ``name``, ``classes`` (class to level), the ``vec`` of
                      non-zero components as whole numbers (the names of ``constants.buff_components``; a fraction is
                      refused, so that the browser's exact sums and Python's float sums cannot differ), the ``source``
                      (``own`` or ``preset``) and ``illusion`` when it is a form
``buff_table_haste``  the same table for the twins (every buff of those sets, with its haste in ``vec``): a buff that
                      carries haste has two readings of one spell id, so the twins read this table and the sets of the
                      rule read the one above. Equal to ``buff_table`` when the rule keeps the haste
``procs``             the table of weapon procs of the trio (:func:`trioforge.model.procs.to_doc`: the socket tier, the effects with their value as ``"p/q"`` and the donors), which the weapon term of the
                      evaluator, the model and the pruning read, or null when no proc is worth anything to the trio
``constants``         every constant the builder and the evaluator read (see below)
``monk_bins``         the Monk bonus for each whole stone of worn weight (``null`` without a Monk in the trio)
``tier_rules``        what ``at_tier`` reads: the stat rule, the haste and regen growth, the weight rule (a percent of the
                      base a tier, ``weight_pct``) and its floor, the arrival rules
``weapon_rules``      the labelled weapon damage switch (the default rate and both choices), the damage weight, the
                      dual-wield factor (a value for a trio with a Monk and one for a trio without; the
                      profile holds the trio's own), the bow factor (``ranged_factor``, the profile holds it too), the
                      skill of a bow and the hand bonuses
``weight_groups``     the slider groups of :data:`trioforge.model.roles.WEIGHT_GROUPS` with the three positions,
                      the settable weights, the derived ones (what each follows) and the bounds of
                      :func:`trioforge.model.roles.weights_override`
``regen_ratios``      the inputs of the regen weights: ticks a minute, the default window in minutes, its maximum
                      and the tolerance that makes a window the role's own
====================  ==============================================================================================

**Rationals.** Every exact number in ``constants``, ``monk_bins``, ``tier_rules``, ``weapon_rules``,
``weight_groups`` and ``regen_ratios`` is a reduced ``"p/q"`` string (integers too: ``"255/1"``), read by
:func:`unrat`, so that no reader meets a float; a float of the rules file is read as the decimal it is written as
(0.2222 is ``"1111/5000"``). Names, texts and flags stay plain. The profile parts (``profile_common``, ``races``,
``roles``, ``buffs``) hold the plain JSON numbers of ``Profile.to_dict()``, which is what the evaluator reads them as.

**Constants.** ``constants`` has every module constant of :mod:`trioforge.model.formulas` (:data:`FORMULA_CONSTANTS`
says where each one is), the slot groups and stat orders of the item model, the buff components, the softcap rows of
the trio's classes at the level, the regen and resist caps, the haste caps, the AA rules and the mana stat of each
class. A test fails if a constant is added to the formulas module and not exported.

**Weapon setups.** The setups a role plays depend on the item pool it is solved with: the shield setup (``1h-shield``)
exists only if the pool has a shield that a class of the trio can wear, and the bow setup (``ranged``) only if it has a bow that a
class of the trio may equip (:func:`trioforge.model.weapons.setups_for`).
The pool depends on the evidence level (``strict`` is the strict items, ``wiki`` the strict and the wiki items, no
deity-locked item in either: :func:`trioforge.precompute.grid.pool_dicts`), so a strict pool with no shield has no
``1h-shield`` where the wiki pool has it, and the precompute solves each level with its own setups.
``roles[role]["setups_by_evidence"]`` is ``{"strict": [...], "wiki": [...]}``, one list of setup names (in the order of
:data:`trioforge.model.weapons.SETUPS`) for each of ``evidence_levels``: the ``setups`` of the profile that
``make_profile`` makes for that level when it is given the solve pool of the level, as
:meth:`trioforge.precompute.grid.Context.profile` does. :func:`bundle` reads the pools from the catalog it is given
(the command passes the one it reads). ``roles[role]["setups"]`` is what a profile has when there is no pool to read
(``make_profile`` without ``items``): a shield is assumed and there is no bow. A shield that only some races may wear could make the setups
depend on the race; a bundle holds one list for each role and level, so :func:`bundle` refuses such a pool instead of
writing a list that is wrong for some race.

**The fingerprint** (:func:`inputs_fingerprint`, :func:`with_inputs`). ``inputs`` is an optional top-level field of the bundle and of the item
table, after ``rules_version``: the SHA-256 (64 lower-case hexadecimal digits) of the catalog the run was given (the hash of its file) and of the
key and evidence level of every item of the item table, the seen flags merged. It is a function of what the published table says and of nothing
that is not in it: no flag, and not a flag that changes no level (a digest of the list of flags could be tried against guesses about flags that
change nothing in the table). The command does not write one; the precompute does, in the files of every trio and in the table of the folder.

**Reassembling** (:func:`assemble`): the profile of ``(race, role, buffs)`` is ``profile_common`` plus the race part
(``race``, ``naked``, ``iksar_ac``), the role part (``role``, ``weights``, ``setups``) and the buff part
(``buff_totals``, ``spell_haste``), in the field order of ``Profile.to_dict()``. Given an ``evidence`` level, the
``setups`` are ``setups_by_evidence[evidence]``; without one they are ``setups``. It equals
``make_profile(...).to_dict()`` exactly (given an ``evidence`` level, with the solve pool of that level); the tests
check every race, role and buff key of five trio types, and :func:`bundle` checks the corners, at both evidence levels,
before it returns.

The item table (:func:`items`)
==============================

``{"version", "data_release", "rules_version", "count", "defaults", "items"}``. ``items`` holds every wearable of the
catalog (an item that lists a slot the model has), the ones the model never recommends as well, sorted by the number
of the wiki page (an item without one last, by key). A record has only the fields that differ from ``defaults`` (an
absent field means its default), which keeps the table inside its size budget:

====================  ==============================================================================================
``id``, ``key``       the wiki page id, and the item key (absent, null: ``w`` and the id)
``name``              the display name
``match_name``        the wiki title with one trailing ``(...)`` removed (absent, null: the name)
``aliases``           other spellings, from a table the caller gives (none are made up)
``slots``             the slots as the catalog lists them
``classes``, ``races``, ``deity``, ``lore``
                      who may wear it (``ALL`` by default) and whether it is Lore
``stats``, ``sv``     what ``at_tier`` scales
``weight10``          the weight in whole tenths of a stone, ``null`` when the page gives none
``weapon``            ``skill``, ``dmg``, ``delay`` and ``bonus`` of a weapon
``item_type``         ``Shield``; ``item_type_source`` says where the type came from
``tier_rule``         ``drop``, ``fixed0`` or ``spell``
``evidence``          ``{"level", "codes"}``: the evidence level, and the reason codes without their details (the
                      code ``live-source`` is the level itself and left out); no reason text
``owned_only``        true for a ``hidden`` item: the model never recommends it, but a player may own it
``source``            a summary for an item that can be farmed: the first zones it ``drops`` in, is ``sold`` in,
                      the ``quests`` and how many recipes ``crafted`` it, zones to ``forage`` it in, and in
                      ``more`` what was cut; none for an ``owned_only`` item
====================  ==============================================================================================

Titles that differ only by a trailing ``(...)`` ("Gold Ring" and "Gold Ring (Ring of Opolla)") have the same match
name, and so have the items of one family that the wiki tells apart that way. A dump row whose name is such a match name
therefore matches more than one item, and the matcher must call it ambiguous instead of picking one:
:func:`shared_match_names` lists those names with their item keys (the command prints how many there are).

:func:`item_to_catalog` turns a record back into the catalog item that :func:`trioforge.model.items.at_tier` reads,
and a test checks that every wearable comes back to the same item at every tier and both weapon rates.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import functools
import gzip
import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

from trioforge.data.jsonio import load_strict, render
from trioforge.model import formulas as fm
from trioforge.model import items as item_model
from trioforge.model import roles, weapons
from trioforge.model import procs as procs_module
from trioforge.model.buffs import BUFF_SETS, COMPONENTS, BuffSet, buffsets
from trioforge.model.formulas import fr
from trioforge.model.items import SLOT_GROUPS, at_tier
from trioforge.model.profile import EVIDENCE_LEVELS, Profile, haste_caps, make_profile
from trioforge.model.tables import REPO
from trioforge.model.tables import load as load_tables
from trioforge.precompute import grid
from trioforge.sources.client_tables import commit_files

__all__ = [
    "BUFF_SETS",
    "BUNDLE_FIELDS",
    "EXACT_BLOCKS",
    "FORMAT",
    "FORMULA_CONSTANTS",
    "HASTE_BUFF_SETS",
    "HASTE_SUFFIX",
    "ITEM_DEFAULTS",
    "INPUTS_FIELD",
    "ITEM_TABLE_FIELDS",
    "SOURCE_PLACES",
    "assemble",
    "bundle",
    "effective_match_name",
    "inputs_fingerprint",
    "item_to_catalog",
    "items",
    "main",
    "match_name",
    "monk_bins",
    "rat",
    "record_key",
    "render_bundle",
    "render_items",
    "shared_match_names",
    "unrat",
    "with_inputs",
]

FORMAT = 1
#: the fields of a bundle, in order (a reader that checks a bundle asks for these and no others)
BUNDLE_FIELDS = (
    "version", "data_release", "rules_version", "trio", "level", "profile_common", "evidence_levels", "races", "roles", "buffs",
    "buff_table", "buff_table_haste", "procs", "constants", "monk_bins", "tier_rules", "weapon_rules", "weight_groups", "regen_ratios",
)  # fmt: skip
#: the end of the key of a buff set that keeps the haste of the spells (``own+haste``): what the page's "I have a haste spell" solves and shows a kit with
HASTE_SUFFIX = "+haste"
#: the keys of the buff sets that keep the haste of the spells, one beside each of :data:`BUFF_SETS`, in the same order
HASTE_BUFF_SETS = tuple(f"{key}{HASTE_SUFFIX}" for key in BUFF_SETS)
#: the blocks of a bundle in which every number is a reduced ``"p/q"`` string (no bare number; see "Rationals" above)
EXACT_BLOCKS = ("constants", "monk_bins", "tier_rules", "weapon_rules", "weight_groups", "regen_ratios")
#: the fields of the item table, in order
ITEM_TABLE_FIELDS = ("version", "data_release", "rules_version", "count", "defaults", "items")
#: the optional field of a bundle and of the item table that holds the fingerprint of the inputs of the run that made them
INPUTS_FIELD = "inputs"
#: (the buff sets of a bundle are ``trioforge.model.buffs.BUFF_SETS``: the trio's own buffs; plus the 13 group buffs; plus the Enchanter's haste; the full raid)

#: the module constants of :mod:`trioforge.model.formulas` and where ``constants`` of a bundle holds each (dotted)
FORMULA_CONSTANTS = {
    "AGI_TO_AC": "agi_to_ac",
    "ATTRIBUTES": "attributes",
    "BUFF_KEYS": "buff_total_keys",
    "DEX_PAST_KNEE": "dex_past_knee",
    "END_BREAKS": "end_curve.breaks",
    "END_SLOPES": "end_curve.slopes",
    "HAND_PLACES": "hand_places",
    "HP_POOL_CONSTANT": "hp_pool_constant",
    "ITEM_STATS": "item_stats",
    "MANA_BANDS": "mana_bands",
    "MONK_SHAPE": "monk_shape",
    "PART_NAMES": "breakdown_parts",
    "PLACEMENTS": "placements",
    "POOLS_COUNTED": "pools_counted",
    "SCHOOLS": "schools",
    "SETUPS": "setups",
    "SHEET_AGI_DIV": "sheet.agi_div",
    "SHEET_DEFENSE_DIV": "sheet.defense_div",
    "SHEET_ITEM_MULT": "sheet.item_mult",
    "SHEET_SPELL_AC_DIV": "sheet.spell_ac_div",
    "STANDARD_CAPS": "standard_caps",
    "STAT_CAP": "stat_cap",
    "STAT_KNEE": "stat_knee",
    "STA_CURVE": "sta_curve",
    "STR_TO_ATK": "str_to_atk",
    "WEIGHT_KEYS": "weight_keys",
}

#: what an absent field of an item record means
ITEM_DEFAULTS: dict[str, Any] = {
    "key": None,  # w and the page id
    "match_name": None,  # the name
    "classes": ["ALL"],
    "races": ["ALL"],
    "deity": None,
    "lore": False,
    "stats": {},
    "sv": {},
    "weapon": None,
    "item_type": None,
    "item_type_source": None,
    "aliases": [],
    "owned_only": False,
}

_PROFILE_FIELDS = ("format", *(field.name for field in dataclasses.fields(Profile)))
_RACE_FIELDS = ("race", "naked", "iksar_ac")
_ROLE_FIELDS = ("role", "weights", "setups", "stance")
_BUFF_FIELDS = ("buff_totals", "spell_haste")
_RATIONAL = re.compile(r"(-?[0-9]+)/([1-9][0-9]*)")
_MONK_STONES_PAST_HARDCAP = 100  # the penalty has stopped growing 90 stones past the hardcap
_SOURCE_ZONES = {"drops": 3, "sold": 3, "forage": 2}
_SOURCE_QUESTS = 2
#: how many places of each kind the summary of the source of an item names (the rest are counted in ``more``): what a reader of the table may expect
SOURCE_PLACES = {**_SOURCE_ZONES, "quests": _SOURCE_QUESTS}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SCHEMA = Path(__file__).resolve().parents[1] / "data" / "schema" / "catalog-item.schema.json"


# ---- rationals -----------------------------------------------------------------------------------------------------


def rat(value: Any) -> str:
    """A number as a reduced ``"p/q"`` string (a float is read as the decimal it prints as: 0.2222 is 1111/5000)."""
    number = fr(value)
    return f"{number.numerator}/{number.denominator}"


def unrat(text: Any) -> Fraction:
    """The fraction of a reduced ``"p/q"`` string. ``ValueError`` for anything else (a bare number, a ratio not in
    lowest terms, a zero denominator)."""
    match = _RATIONAL.fullmatch(text) if isinstance(text, str) else None
    if match is not None:
        number = Fraction(int(match[1]), int(match[2]))
        if rat(number) == text:
            return number
    raise ValueError(f"not a reduced rational p/q: {text!r}")


def _rationals(value: Any) -> Any:
    """``value`` with every number turned into a ``"p/q"`` string; names, texts, flags and null stay as they are."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float, Fraction)):
        return rat(value)
    if isinstance(value, Mapping):
        return {str(key): _rationals(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rationals(item) for item in value]
    raise TypeError(f"cannot write {type(value).__name__} as a rational block")


# ---- the bundle ----------------------------------------------------------------------------------------------------


def _buffset(buffset: BuffSet) -> dict[str, Any]:
    return {
        "always_on": [buff.id for buff in buffset.always_on],
        "optional": [buff.id for buff in buffset.optional],
        "conflicts": [[a, b, list(reasons)] for (a, b), reasons in buffset.conflict_reasons],
        "cliques": [list(clique) for clique in buffset.cliques],
        "cardinality": buffset.cardinality,
        "dropped": [[dropped.id, dropped.name, dropped.reason, dropped.by] for dropped in buffset.dropped],
    }


_EXACT = 2**53 - 1  # the whole numbers a reader of JSON holds exactly (Number.MAX_SAFE_INTEGER)


def _whole(amount: Any) -> int | None:
    """``amount`` as an int when it is a whole number a double holds exactly, else None (a bool is no number here)."""
    if isinstance(amount, bool):
        return None
    if isinstance(amount, float) and amount.is_integer():
        amount = int(amount)
    elif isinstance(amount, Fraction) and amount.denominator == 1:
        amount = int(amount)
    return amount if isinstance(amount, int) and abs(amount) <= _EXACT else None


def _buff_vec(buff: Any) -> dict[str, int]:
    """The non-zero components of a buff, as whole numbers.

    The browser checks that the always-on buffs of a set add up to the totals of the profile in exact arithmetic, while
    Python adds the same buffs as floats (0.1 + 0.2 is 0.30000000000000004): the two agree for whole numbers and could
    disagree for a fraction. Every value the client files give is whole, so the table takes whole numbers only.
    """
    vec: dict[str, int] = {}
    for name, amount in zip(COMPONENTS, buff.vec, strict=True):
        whole = _whole(amount)
        if whole is None:
            raise ValueError(f"buff {buff.id} ({buff.name}): {name} is {amount!r}, not a whole number (at most 2^53)")
        if whole:
            vec[name] = whole
    return vec


def _buff_entry(buff: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": buff.name,
        "classes": dict(buff.classes),
        "vec": _buff_vec(buff),
        "source": buff.source,
    }
    if buff.illusion:
        entry["illusion"] = True
    return entry


def _constants(codes: tuple[str, ...], level: int, tables: Any, rules: Any) -> dict[str, Any]:
    names = {
        "attributes": list(fm.ATTRIBUTES),
        "schools": list(fm.SCHOOLS),
        "setups": list(fm.SETUPS),
        "hand_places": list(fm.HAND_PLACES),
        "placements": list(fm.PLACEMENTS),
        "breakdown_parts": list(fm.PART_NAMES),
        "weight_keys": sorted(fm.WEIGHT_KEYS),
        "buff_total_keys": sorted(fm.BUFF_KEYS),
        "item_stats": sorted(fm.ITEM_STATS),
        "item_stat_order": [*item_model.STAT_KEYS, *item_model.REGEN_KEYS],
        "sv_keys": list(item_model.SV_KEYS),
        "buff_components": list(COMPONENTS),
        "weapon_setups": list(weapons.SETUPS),
        "monk_shape": fm.MONK_SHAPE,
        "mana_stat_by_class": rules.get("mana.stat_by_class"),
    }
    numbers = {
        "slot_groups": [[name, count] for name, count in SLOT_GROUPS],
        "stat_knee": fm.STAT_KNEE,
        "stat_cap": fm.STAT_CAP,
        "hp_pool_constant": fm.HP_POOL_CONSTANT,
        "pools_counted": fm.POOLS_COUNTED,
        "sta_curve": {"breaks": fm.STA_CURVE[0], "slopes": fm.STA_CURVE[1]},
        "mana_bands": {"breaks": fm.MANA_BANDS[0], "slopes": fm.MANA_BANDS[1]},
        "end_curve": {"breaks": fm.END_BREAKS, "slopes": fm.END_SLOPES},
        "str_to_atk": fm.STR_TO_ATK,
        "agi_to_ac": fm.AGI_TO_AC,
        "dex_past_knee": fm.DEX_PAST_KNEE,
        "sheet": {
            "item_mult": fm.SHEET_ITEM_MULT,
            "defense_div": fm.SHEET_DEFENSE_DIV,
            "spell_ac_div": fm.SHEET_SPELL_AC_DIV,
            "agi_div": fm.SHEET_AGI_DIV,
        },
        "standard_caps": fm.STANDARD_CAPS,
        "weapon_index": {
            "bonus_from_level": weapons.BONUS_FROM_LEVEL,
            "bonus_one_handed": weapons.BONUS_ONE_HANDED,
            "bonus_two_handed": weapons.BONUS_TWO_HANDED,
            "bonus_delay_cap": weapons.BONUS_DELAY_CAP,
            "bonus_delay_div": weapons.BONUS_DELAY_DIV,
            "bonus_level_div": weapons.BONUS_LEVEL_DIV,
        },
        "regen_caps": rules.get("regen.gear_caps", level),
        "resist_cap": rules.get("resist.cap", level),
        "haste": {
            "cap": haste_caps(rules, level)[0],  # (the rule haste.cap_pct has a level dimension: the cap at the level of the bundle)
            "cap_with_monk": haste_caps(rules, level)[1],  # (and what Unbound Alacrity adds, haste.cap_pct_with_monk: the numbers a profile's haste cap is made of, by the same function)
            "worn_per_tier": rules.get("haste.worn_per_tier", level),
        },
        "aa": {
            "combat_stability_pct": rules.get("ac.softcap.combat_stability_pct", level),
            "natural_durability_pct": rules.get("hp.natural_durability_pct", level),
            "physical_enhancement_pct": rules.get("ac.softcap.physical_enhancement_pct", level),
            "pe_for_caster_only_trios": bool(rules.get("ac.softcap.pe_for_caster_only_trios", level)),
        },
        "iksar_ac_bonus": rules.get("race.iksar_ac_bonus", level),
        "softcap_rows": {
            code: {"cap": tables.softcap[(code, level)][0], "rate": tables.softcap[(code, level)][1]} for code in codes
        },
    }
    return {**names, **_rationals(numbers)}


def monk_bins(level: int, rules: Any) -> dict[str, Any]:
    """The Monk bonus for each whole stone of worn weight, from ``monk_bonus`` itself, for the curve and its others: the
    ``monk_bins`` block of a bundle of that level (the parity fixtures of the evaluator carry the same block)."""
    curve = fm.monk_curve(rules, level)
    stones = curve["hardcap_stones"] + _MONK_STONES_PAST_HARDCAP

    def table(shape: Mapping[str, Any]) -> list[int]:
        return [fm.monk_bonus(level, 10 * whole, shape) for whole in range(stones + 1)]

    bonus = table(curve)
    alternatives = []
    for alternative in rules.alternatives("monk.weight_curve"):
        shape = {**curve, **alternative["value"]}
        alternatives.append({"curve": _rationals(shape), "bonus": _rationals(table(shape))})
    return {
        "curve": _rationals({**curve, "shape": fm.MONK_SHAPE}),
        "bonus": _rationals(bonus),
        "alternatives": alternatives,
    }


def _tier_rule_values() -> list[str]:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    return list(schema["properties"]["tier_rule"]["enum"])


def _tier_rules(level: int, rules: Any) -> dict[str, Any]:
    probe = {
        "key": "probe", "name": "probe", "slots": ["HEAD"], "classes": ["ALL"], "deity": None, "flags": [], "stats": {},
        "sv": {}, "weight": 1.0, "weapon": None,
    }  # fmt: skip
    at_tier(probe, 0, rules)  # a rules file that at_tier does not implement is refused here, as it is everywhere
    floor = Fraction(str(rules.get("tier.weight_floor"))) * 10
    return _rationals(
        {
            "max_tier": item_model.MAX_TIER,
            "stat_rule": rules.get("tier.stat_rule"),
            "stat_divisor": 10,  # the 10 of the rule text: base + max(n, floor(base * n / 10))
            "negatives_scale": rules.get("tier.negatives_scale"),
            "unscaled_stats": rules.get("tier.unscaled_stats"),
            "weight_floor10": int(floor),
            "weight_pct": rules.get("tier.weight_pct"),
            "weight_rule": item_model.WEIGHT_RULE_TEXT,
            "unknown_weight10": item_model.UNKNOWN_WEIGHT10,
            "haste_per_tier": rules.get("haste.worn_per_tier", level),
            "regen_per_tier": rules.get("regen.per_tier", level),
            "max_fresh_drop": rules.get("tier.max_fresh_drop", level),
            "exp_needed": rules.get("tier.exp_needed"),
            "arrival": rules.get("tier.arrival"),
            "socket_open": rules.get("tier.socket_open"),
            "accuracy_pct": rules.get("tier.accuracy_pct"),
            "tier_rule_values": _tier_rule_values(),
        }
    )


def _weapon_rules(level: int, rules: Any) -> dict[str, Any]:
    return _rationals(
        {
            "label": "Weapon damage per tier",
            "damage_pct": rules.get("tier.weapon_damage_pct", level),
            "damage_pct_choices": list(item_model.WEAPON_PCTS),
            "damage_rule": item_model.DAMAGE_RULE_TEXT,
            "delay_changes": False,
            "seal": rules.seal("tier.weapon_damage_pct"),
            "test": rules.settled_by("tier.weapon_damage_pct"),
            "damage_weight": rules.get("weapons.damage_weight", level),
            "dual_wield_factor": rules.get("weapons.dual_wield_factor", level),  # {with_monk, without_monk}: the same in every bundle
            "ranged_factor": rules.get("weapons.ranged_factor", level),  # the multiplier of a bow's own damage per delay in the bow setup; the profile holds it too
            "bow_skill": weapons.BOW_SKILL,  # the skill that makes a weapon a bow, read without regard to case
            "bonus_one_handed": weapons.BONUS_ONE_HANDED,
            "bonus_two_handed": weapons.BONUS_TWO_HANDED,
            "setups": list(weapons.SETUPS),
        }
    )


def _weight_groups() -> dict[str, Any]:
    return _rationals(
        {
            "groups": {name: list(keys) for name, keys in roles.WEIGHT_GROUPS.items()},
            "multipliers": list(roles.MULTIPLIERS),
            "custom_keys": list(roles.CUSTOM_KEYS),
            "derived": list(roles.DERIVED_KEYS),
            "damage_follows": roles.DAMAGE_FOLLOWS,
            "regen_sources": dict(roles.REGEN_SOURCES),
            "mana_keys": list(roles.MANA_KEYS),
            "custom_max": roles.CUSTOM_MAX,
            "regen_t_max": roles.REGEN_T_MAX,
        }
    )


def _regen_ratios(level: int, rules: Any) -> dict[str, str]:
    return {
        "ticks_per_minute": rat(roles.TICKS_PER_MINUTE),
        "default_minutes": rat(rules.get("regen.value_minutes", level)),
        "max_minutes": rat(roles.REGEN_T_MAX),
        "match": rat(roles.REGEN_T_MATCH),
    }


@functools.lru_cache(maxsize=2)
def _read_catalog(path: str, modified: int, size: int) -> Any:
    """The catalog file at ``path``, read once for as long as the file keeps its size and its time of change."""
    return load_strict(path)


def _found_catalog() -> Any:
    """The catalog document the command reads by default (:func:`trioforge.precompute.grid.find_catalog`), or None."""
    path = grid.find_catalog()
    if path is None:
        return None
    status = path.stat()
    return _read_catalog(str(path), status.st_mtime_ns, status.st_size)


def _seen_keys(seen: Iterable[str] | None) -> frozenset[str]:
    """The private seen flags as a set of item keys. ``ValueError`` for a text (which would be read as its letters) and for
    anything that is not a collection of texts."""
    if seen is None:
        return frozenset()
    if isinstance(seen, (str, bytes)) or not isinstance(seen, Iterable):
        raise ValueError("the seen flags are a collection of item keys, not a text or a single value")
    keys = frozenset(seen)
    if not all(isinstance(key, str) for key in keys):
        raise ValueError("the seen flags are a collection of item keys (texts)")
    return keys


def _solve_pools(
    catalog: Any, codes: tuple[str, ...], rules: Any, seen: frozenset[str] = frozenset()
) -> dict[str, list[item_model.ItemVec]] | None:
    """The solve pool of each evidence level as item vectors at +0, made the way the precompute makes them
    (:func:`trioforge.precompute.grid.select_items` with the seen flags, :func:`~trioforge.precompute.grid.pool_dicts` and
    ``at_tier``).

    ``catalog`` is the catalog document or its list of items; None is the catalog found on disk, and when there is
    none the answer is None: no pool to read, so that a profile assumes a shield."""
    document = _found_catalog() if catalog is None else catalog
    if document is None:
        return None
    listed = document.get("items") if isinstance(document, Mapping) else document
    if not isinstance(listed, (list, tuple)):
        raise ValueError("the catalog is the document of the builder (an object with a list of items), or that list")
    if not all(isinstance(item, Mapping) and "key" in item and "evidence" in item for item in listed):
        raise ValueError("an item has no key or no evidence level (is this the catalog the builder writes?)")
    selection = grid.select_items(listed, codes, seen)
    return {label: [at_tier(item, 0, rules) for item in grid.pool_dicts(selection, label)] for label in EVIDENCE_LEVELS}


def _setups_by_evidence(role: str, races: Sequence[str], made: Callable[..., Profile]) -> dict[str, list[str]]:
    """The weapon setups of ``role`` at each evidence level: those of the profile ``made(race, role, "own", level)``,
    which must be the same for every race (``ValueError`` when a shield that only some races may wear makes them differ:
    a bundle holds one list for each role and level)."""
    result: dict[str, list[str]] = {}
    for label in EVIDENCE_LEVELS:
        groups: dict[tuple[str, ...], list[str]] = {}
        for race in races:
            try:
                setups = tuple(made(race, role, "own", label).setups)
            except ValueError:  # the role is not offered for the pool of this level (the Ranged role, for a pool with no bow): it has no setups there
                if role != "ranged":
                    raise
                setups = ()
            groups.setdefault(setups, []).append(race)
        if len(groups) > 1:
            detail = "; ".join(f"{' '.join(setups)} for {' '.join(group)}" for setups, group in groups.items())
            raise ValueError(
                f"the weapon setups of the {role} role at the {label} evidence level depend on the race ({detail}); "
                "a bundle holds one list for each role and evidence level"
            )
        ((setups, _),) = groups.items()
        result[label] = list(setups)
    return result


def bundle(
    trio: Sequence[str], level: int, tables: Any, rules: Any, spells: Any, *, data_release: str | None = None,
    catalog: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None, seen: Iterable[str] | None = None, procs: Any = None,
) -> dict[str, Any]:
    """The bundle of ``trio`` at ``level`` (see the module docstring). ``procs`` is the :class:`~trioforge.model.procs.ProcTable` of the trio, or None: the table the run is solved with, which the
    bundle holds (``procs``) so that the browser values a kit and solves a view with the same weapon procs; a table of another trio is refused.

    ``tables`` and ``rules`` are those of :mod:`trioforge.model.tables` (``rules`` None: the tables' own), ``spells``
    the beneficial-spell file of ``level``. ``data_release`` is the release tag the browser compares with the shards;
    the default is ``data-`` and the date the client data was made on, or null for a bare list of spells. ``catalog`` is
    the catalog document, or its list of items, whose evidence levels give the solve pool of each evidence level and so
    its weapon setups (``setups_by_evidence``); None is the catalog the command reads by default
    (:func:`trioforge.precompute.grid.find_catalog`), and with none on disk a shield is assumed at both levels. ``seen`` is
    the private list of item keys seen in game, merged into the pools as the precompute merges it (``None``: none). The
    trio is put in class order. Raises ``ValueError`` for a trio or level the inputs do not cover, for a spell file of
    another level, for a catalog that is not the one the builder writes, for seen flags that are not a collection of keys
    and for a pool that makes the weapon setups of a role depend on the race.
    """
    codes = grid.parse_trio(trio)
    if procs is not None and tuple(procs.trio) != tuple(codes):
        raise ValueError(f"procs: the table is for {'-'.join(procs.trio)}, not for {'-'.join(codes)}")
    rules = tables.rules if rules is None else rules
    sets = buffsets(codes, level, spells, rules, BUFF_SETS)  # (no spell haste in them while the rule haste.assume_spell is false)
    sets.update({f"{key}{HASTE_SUFFIX}": made for key, made in buffsets(codes, level, spells, rules, BUFF_SETS, spell_haste=True).items()})  # (their twins keep it)
    pools = _solve_pools(catalog, codes, rules, _seen_keys(seen))
    races = grid.race_order(codes, tables)
    # (the Ranged role plays the bow and nothing else: it is offered when the widest pool, the wiki one, has a bow that a class of the trio can shoot; with no pool to read it is not)
    offered = roles.roles_for(codes, bow=pools is not None and weapons.bow_available(codes, pools["wiki"], tables=tables, level=level))
    names = {entry["code"]: entry["name"] for entry in tables.races["races"]}

    def made(race: str, role: str, key: str, label: str | None = None) -> Profile:
        """The profile of a scenario; given an evidence ``label``, the one the precompute makes for that level (it is
        solved with the pool of the level, which decides the weapon setups)."""
        options: dict[str, Any] = {}
        if label is not None:
            options = {"evidence": label, "items": None if pools is None else pools[label]}
        return make_profile(race, codes, level, role, sets[key], None, tables, rules, **options)

    def profile(race: str, role: str, key: str, label: str | None = None) -> dict[str, Any]:
        return made(race, role, key, label).to_dict()

    base = profile(races[0][0], offered[0], "own")
    varying = {*_RACE_FIELDS, *_ROLE_FIELDS, *_BUFF_FIELDS}
    race_rows = []
    for code, legal in races:
        part = profile(code, offered[0], "own")
        race_rows.append(
            {"code": code, "name": names[code], "legal": legal, "naked": part["naked"], "iksar_ac": part["iksar_ac"]}
        )
    role_rows = {}
    for role in offered:
        # (a role that only a pool offers has no profile with no pool: its weights and its setups are those of the widest pool's, and `assemble` makes it at a level alone)
        part = profile(races[0][0], role, "own", EVIDENCE_LEVELS[-1] if role in roles.POOL_ROLES else None)
        role_rows[role] = {
            "weights": part["weights"],
            "setups": part["setups"],
            "stance": part["stance"],
            "setups_by_evidence": _setups_by_evidence(role, [code for code, _ in races], made),
        }
    buff_rows: dict[str, Any] = {}
    table: dict[int, Any] = {}
    table_haste: dict[int, Any] = {}
    for key in (*BUFF_SETS, *HASTE_BUFF_SETS):
        part = profile(races[0][0], offered[0], key)
        buff_rows[key] = {
            "buff_totals": part["buff_totals"], "spell_haste": part["spell_haste"], "set": _buffset(sets[key]),
        }  # fmt: skip
        for buff in (*sets[key].always_on, *sets[key].optional):
            (table_haste if key.endswith(HASTE_SUFFIX) else table).setdefault(buff.id, _buff_entry(buff))

    if data_release is None and isinstance(spells, Mapping):
        generated = (spells.get("provenance") or {}).get("generated")
        data_release = f"data-{generated}" if isinstance(generated, str) else None
    result = {
        "version": FORMAT,
        "data_release": data_release,
        "rules_version": rules.version,
        "trio": list(codes),
        "level": level,
        "profile_common": {name: base[name] for name in _PROFILE_FIELDS if name not in varying},
        "evidence_levels": list(EVIDENCE_LEVELS),
        "races": race_rows,
        "roles": role_rows,
        "buffs": buff_rows,
        "buff_table": {str(buff_id): table[buff_id] for buff_id in sorted(table)},
        "buff_table_haste": {str(buff_id): table_haste[buff_id] for buff_id in sorted(table_haste)},
        "procs": None if procs is None else procs_module.to_doc(procs),
        "constants": _constants(codes, level, tables, rules),
        "monk_bins": monk_bins(level, rules) if "MNK" in codes else None,
        "tier_rules": _tier_rules(level, rules),
        "weapon_rules": _weapon_rules(level, rules),
        "weight_groups": _weight_groups(),
        "regen_ratios": _regen_ratios(level, rules),
    }
    _check_corners(result, profile, [code for code, _ in races], offered)
    return result


def _check_corners(data: Mapping[str, Any], profile: Any, races: list[str], offered: list[str]) -> None:
    """The first and the last race, role and buff key, in every combination, reassemble to the profile itself: with no
    evidence level to the profile with no pool, and at each evidence level to the profile of the pool of that level."""
    for race in {races[0], races[-1]}:
        for role in {offered[0], offered[-1]}:
            for key in {BUFF_SETS[0], BUFF_SETS[-1], HASTE_BUFF_SETS[0], HASTE_BUFF_SETS[-1]}:
                if role not in roles.POOL_ROLES and assemble(data, race, role, key) != profile(race, role, key):  # (a role that only a pool offers has no profile with no pool)
                    raise RuntimeError(f"the bundle does not reassemble to the profile of {race} {role} {key}")
                for label in data["evidence_levels"]:
                    if not data["roles"][role]["setups_by_evidence"][label]:
                        continue  # (a role with no setup at a level is not offered there: neither side can make its profile)
                    if assemble(data, race, role, key, evidence=label) != profile(race, role, key, label):
                        raise RuntimeError(
                            f"the bundle does not reassemble to the {label} profile of {race} {role} {key}"
                        )


def assemble(
    data: Mapping[str, Any], race: str, role: str, buffs: str, *, evidence: str | None = None, deity: str | None = None
) -> dict[str, Any]:
    """The reference for putting the parts of a bundle back together: the profile dict of ``(race, role, buffs)``.

    It equals ``make_profile(...).to_dict()``: the common part, the race part, the role part and the buff part, in the
    field order of the profile. ``evidence`` (one of ``data["evidence_levels"]``) and ``deity`` replace the defaults of
    those two inputs. An ``evidence`` level also picks the weapon setups of its solve pool
    (``roles[role]["setups_by_evidence"][evidence]``), so the profile is the one the precompute makes for that level;
    without one the setups are ``roles[role]["setups"]``, those of a profile with no pool to read (a shield is assumed, a bow is
    not). A role that only a pool offers (:data:`trioforge.model.roles.POOL_ROLES`, the Ranged role) has no profile with no pool, and
    its ``setups`` are those of the widest pool: asking for it with no level is a ``ValueError``.
    The result is a copy, so changing it cannot change the bundle. ``ValueError`` for a race, role or buff key the
    bundle does not have, an evidence label it does not know, or a blank deity.
    """
    races = {row["code"]: row for row in data["races"]}
    if race not in races:
        raise ValueError(f"race {race!r} is not in the bundle (it has {', '.join(races)})")
    if role not in data["roles"]:
        raise ValueError(f"role {role!r} is not offered to this trio (its roles are {', '.join(data['roles'])})")
    if buffs not in data["buffs"]:
        raise ValueError(f"buffs {buffs!r} is not a buff set of the bundle (use {', '.join(data['buffs'])})")
    if evidence is None and role in roles.POOL_ROLES:
        raise ValueError(f"role {role!r} is offered by a pool alone (a bow is never assumed): name an evidence level")
    parts = {
        **data["profile_common"],
        "race": race,
        "naked": races[race]["naked"],
        "iksar_ac": races[race]["iksar_ac"],
        "role": role,
        "weights": data["roles"][role]["weights"],
        "setups": data["roles"][role]["setups"],
        "stance": data["roles"][role]["stance"],
        "buff_totals": data["buffs"][buffs]["buff_totals"],
        "spell_haste": data["buffs"][buffs]["spell_haste"],
    }
    if evidence is not None:
        if evidence not in data["evidence_levels"]:
            raise ValueError(f"evidence {evidence!r} is not one of {', '.join(data['evidence_levels'])}")
        parts["evidence"] = evidence
        parts["setups"] = data["roles"][role]["setups_by_evidence"][evidence]
        if not parts["setups"]:
            raise ValueError(f"role {role!r} is not offered for the solve pool of the {evidence} evidence level (it has no weapon setup there)")
    if deity is not None:
        if not isinstance(deity, str) or not deity.strip():
            raise ValueError(f"deity is None or a name, not {deity!r}")
        parts["deity"] = deity
    return copy.deepcopy({name: parts[name] for name in _PROFILE_FIELDS})


# ---- the item table ------------------------------------------------------------------------------------------------


def match_name(title: str) -> str:
    """The wiki title without its trailing disambiguator: one final ``(...)`` group, nested parentheses included.

    ``"Gold Ring (Ring of Opolla)"`` is ``"Gold Ring"`` and ``"Band of (Fire) (RoF)"`` is ``"Band of (Fire)"``; a title
    with no final group, an unbalanced one, or nothing before the group stays as it is (stripped of outer spaces).
    Articles,
    the ``*`` of a name and inner spaces are never touched.
    """
    if not isinstance(title, str):
        raise TypeError(f"a title is text, not {type(title).__name__}")
    text = title.strip()
    if text.endswith(")"):
        depth = 0
        for index in range(len(text) - 1, -1, -1):
            if text[index] == ")":
                depth += 1
            elif text[index] == "(":
                depth -= 1
                if depth == 0:
                    return text[:index].rstrip() or text
    return text


def record_key(record: Mapping[str, Any]) -> str:
    """The item key of a record of the table: its ``key``, else ``w`` and the page id."""
    return record.get("key") or f"w{record['id']}"


def effective_match_name(record: Mapping[str, Any]) -> str:
    """The name a dump row is matched against: the record's ``match_name``, else its name."""
    return record.get("match_name") or record["name"]


def shared_match_names(table: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """The match names that more than one item has, by name, with the keys of those items in table order.

    ``table`` is what :func:`items` returns, or its list of records. A dump row with one of these names matches several
    items, so it is ambiguous (the player chooses) and never silently matched.
    """
    records = table["items"] if isinstance(table, Mapping) else table
    groups: dict[str, list[str]] = {}
    for record in records:
        groups.setdefault(effective_match_name(record), []).append(record_key(record))
    return {name: keys for name, keys in sorted(groups.items()) if len(keys) > 1}


def _alias_table(aliases: Any, keys: set[str]) -> dict[str, list[str]]:
    if aliases is None:
        return {}
    if not isinstance(aliases, Mapping):
        raise ValueError(f"the alias table maps an item key to a list of names, not {type(aliases).__name__}")
    table: dict[str, list[str]] = {}
    for key, names in aliases.items():
        if key not in keys:
            raise ValueError(f"the alias table names an item that is not in the table: {key!r}")
        if isinstance(names, (str, bytes)) or not isinstance(names, Sequence):
            raise ValueError(f"the aliases of {key} are a list of names, not {names!r}")
        if not all(isinstance(name, str) and name.strip() for name in names):
            raise ValueError(f"an alias of {key} is not a non-blank name")
        table[key] = list(names)
    return table


def _codes(evidence: Mapping[str, Any]) -> list[str]:
    codes = {str(reason["code"]).split(":")[0] for reason in evidence.get("reasons", ())}
    return sorted(codes - {"live-source"})


def _source(sources: Mapping[str, Any]) -> dict[str, Any]:
    zones = {
        "drops": [entry.get("zone") for entry in sources.get("drops", ())],
        "sold": [entry.get("zone") for entry in sources.get("sold_by", ())],
        "forage": [entry.get("zone") for entry in sources.get("foraged", ())],
    }
    summary: dict[str, Any] = {}
    more: dict[str, int] = {}
    for kind, names in zones.items():
        unique = list(dict.fromkeys(name for name in names if name))
        if unique:
            summary[kind] = unique[: _SOURCE_ZONES[kind]]
            if len(unique) > _SOURCE_ZONES[kind]:
                more[kind] = len(unique) - _SOURCE_ZONES[kind]
    quests = list(dict.fromkeys(sources.get("quests", ())))
    if quests:
        summary["quests"] = quests[:_SOURCE_QUESTS]
        if len(quests) > _SOURCE_QUESTS:
            more["quests"] = len(quests) - _SOURCE_QUESTS
    if sources.get("crafted"):
        summary["crafted"] = len(sources["crafted"])
    if more:
        summary["more"] = more
    return summary


def _level(item: Mapping[str, Any], seen: frozenset[str]) -> str:
    """The evidence level the precompute solves the item at: the catalog's own, or strict for an item seen in game that no patch
    or research removal hides. The rule is :func:`trioforge.precompute.grid._effective_level` itself, not a copy of it: the
    module is hashed into the fingerprint of the chunks, so a public name added there would have every chunk made again."""
    return grid._effective_level(item, seen)


def _record(item: Mapping[str, Any], aliases: list[str], rules: Any, seen: frozenset[str] = frozenset()) -> dict[str, Any]:
    key = item["key"]
    wiki = item.get("wiki") or {}
    page = wiki.get("pageid") if type(wiki.get("pageid")) is int else None
    evidence = item.get("evidence")
    if not isinstance(evidence, Mapping) or "level" not in evidence:
        raise ValueError(f"item {key} has no evidence level (is this the catalog the builder writes?)")
    vec = at_tier(dict(item), 0, rules)  # also refuses an item that the tier rules cannot read
    record: dict[str, Any] = {"id": page}
    if key != f"w{page}":
        record["key"] = key
    record["name"] = item["name"]
    matched = match_name(wiki.get("title") or item["name"])
    if matched != item["name"]:
        record["match_name"] = matched
    extra = sorted({name for name in aliases if name not in (item["name"], matched)})
    if extra:
        record["aliases"] = extra
    record["slots"] = list(item["slots"])
    for field in ("classes", "races"):
        if item.get(field, ["ALL"]) != ITEM_DEFAULTS[field]:
            record[field] = list(item[field])
    if item.get("deity") is not None:
        record["deity"] = list(item["deity"])
    if "lore" in item.get("flags", ()):
        record["lore"] = True
    for field in ("stats", "sv"):
        if item.get(field):
            record[field] = dict(item[field])
    record["weight10"] = vec.weight10 if vec.weight_known else None
    weapon = item.get("weapon")
    if weapon is not None:
        record["weapon"] = {name: weapon[name] for name in ("skill", "dmg", "delay", "bonus")}
    if item.get("item_type") is not None:
        record["item_type"] = item["item_type"]
        record["item_type_source"] = item.get("item_type_source")
    record["tier_rule"] = item["tier_rule"]
    codes = _codes(evidence)
    level = _level(item, seen)
    record["evidence"] = {"level": level, **({"codes": codes} if codes else {})}
    if level == "hidden":
        record["owned_only"] = True
    else:
        summary = _source(item.get("sources") or {})
        if summary:
            record["source"] = summary
    return record


def items(
    catalog: Any, rules: Any, *, aliases: Mapping[str, Sequence[str]] | None = None, seen: Iterable[str] | None = None
) -> dict[str, Any]:
    """The item table of ``catalog`` (the catalog document, or its list of items; see the module docstring).

    ``aliases`` maps an item key to other names the item may be listed under (an alias table kept by hand; nothing is
    made up). ``seen`` is the private list of item keys seen in game: a seen item is strict in the table (and no longer
    ``owned_only`` if it was hidden), unless a patch or research removal hides it, as in the pools the precompute solves; the
    reason codes stay the catalog's, and nothing in the table says that a flag was merged. ``ValueError`` for an item without
    an evidence level, for an item ``at_tier`` cannot read, for an alias table that names an item the table lacks or holds a
    blank name, and for seen flags that are not a collection of keys.
    """
    flags = _seen_keys(seen)
    document = catalog if isinstance(catalog, Mapping) else {"items": catalog}
    version = document.get("version")
    wearable = [item for item in document["items"] if grid.WEARABLE_SLOTS & set(item["slots"])]
    table = _alias_table(aliases, {item["key"] for item in wearable})

    def order(item: Mapping[str, Any]) -> tuple[int, int, str]:
        page = (item.get("wiki") or {}).get("pageid")
        return (0, page, item["key"]) if type(page) is int else (1, 0, item["key"])

    records = [_record(item, table.get(item["key"], []), rules, flags) for item in sorted(wearable, key=order)]
    return {
        "version": FORMAT,
        "data_release": f"data-{version}" if isinstance(version, str) else None,
        "rules_version": rules.version,
        "count": len(records),
        "defaults": copy.deepcopy(ITEM_DEFAULTS),
        "items": records,
    }


def inputs_fingerprint(catalog_sha256: str, table: Mapping[str, Any]) -> str:
    """The fingerprint of the inputs an item table (and the bundles made beside it) came from: the SHA-256 of ``catalog_sha256``, the hash of the catalog's
    file, and of the key and evidence level of every item of ``table``, in the order of the table, as compact JSON with sorted keys::

        {"catalog": <catalog_sha256>, "levels": [[key, level], ...]}

    The levels are the ones the table publishes (the seen flags already merged), so the fingerprint says nothing that the table does not: no flag, and
    no flag that changes no level. ``ValueError`` for a digest that is not 64 lower-case hexadecimal digits."""
    if not isinstance(catalog_sha256, str) or not _SHA256.fullmatch(catalog_sha256):
        raise ValueError("the digest of the catalog is a SHA-256, 64 lower-case hexadecimal digits")
    levels = [[record_key(record), record["evidence"]["level"]] for record in table["items"]]
    text = json.dumps({"catalog": catalog_sha256, "levels": levels}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def with_inputs(document: Mapping[str, Any], inputs: str) -> dict[str, Any]:
    """A copy of a bundle or of an item table with the fingerprint ``inputs`` after its ``rules_version``. ``ValueError`` for a fingerprint that is
    not 64 lower-case hexadecimal digits and for a document that has one."""
    if not isinstance(inputs, str) or not _SHA256.fullmatch(inputs):
        raise ValueError("the fingerprint of the inputs is a SHA-256, 64 lower-case hexadecimal digits")
    if INPUTS_FIELD in document:
        raise ValueError("the document has a fingerprint of its inputs already")
    stamped: dict[str, Any] = {}
    for name, value in document.items():
        stamped[name] = value
        if name == "rules_version":
            stamped[INPUTS_FIELD] = inputs
    if INPUTS_FIELD not in stamped:
        raise ValueError("the document has no rules_version to put the fingerprint after: it is not a bundle or an item table")
    return stamped


def item_to_catalog(record: Mapping[str, Any], defaults: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The catalog item that :func:`trioforge.model.items.at_tier` reads, rebuilt from an item record.

    ``defaults`` is the table's ``defaults`` (the module's :data:`ITEM_DEFAULTS` when None). Only what ``at_tier``
    reads is rebuilt: the key, name, slots, classes, races, deity, Lore flag, stats, resists, weight, weapon, item
    type and tier rule.
    """
    fill = copy.deepcopy(dict(ITEM_DEFAULTS if defaults is None else defaults))
    fill.update(copy.deepcopy(dict(record)))
    weight10 = fill["weight10"]
    return {
        "key": record_key(fill),
        "name": fill["name"],
        "slots": list(fill["slots"]),
        "classes": list(fill["classes"]),
        "races": list(fill["races"]),
        "deity": None if fill["deity"] is None else list(fill["deity"]),
        "flags": ["lore"] if fill["lore"] else [],
        "stats": dict(fill["stats"]),
        "sv": dict(fill["sv"]),
        "weight": None if weight10 is None else weight10 / 10,
        "weapon": None if fill["weapon"] is None else dict(fill["weapon"]),
        "item_type": fill["item_type"],
        "item_type_source": fill["item_type_source"],
        "tier_rule": fill["tier_rule"],
    }


# ---- the command ---------------------------------------------------------------------------------------------------


def render_bundle(document: Mapping[str, Any]) -> str:
    """The text of a bundle file: the races and the buff table one entry to a line, the rest compact, strict JSON."""
    return render(document, per_line=("races", "buff_table"))


def render_items(document: Mapping[str, Any]) -> str:
    """The text of the item table file: one record to a line."""
    return render(document, per_line=("items",))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.export.browser",
        description="Write the browser bundles of some trios and the item table, and report their sizes.",
    )
    parser.add_argument("--out", required=True, type=Path, help="the folder to write into (bundles/ and items.json)")
    parser.add_argument("--trio", action="append", help="a trio such as pal-mnk-ber; repeat it (default pal-mnk-ber)")
    parser.add_argument("--level", type=int, help="the character level (default: the current level of the rules)")
    parser.add_argument(
        "--catalog", type=Path,
        help="the catalog file (default: $TRIOFORGE_CATALOG, else derived/catalog.json of --root, else the one of the main checkout of its git)",
    )
    parser.add_argument("--root", type=Path, default=REPO, help="the repository with derived/ and rules/")
    return parser


def _report(name: str, text: str) -> str:
    raw = text.encode("utf-8")
    return f"{name:44} {len(raw):>9} bytes {len(gzip.compress(raw, 9)):>8} gzip"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command; returns 0, or 2 after a message on stderr if an input is unusable (nothing is written then)."""
    args = _parser().parse_args(argv)
    try:
        tables = load_tables(args.root)
        rules = tables.rules
        level = rules.get("level.current") if args.level is None else args.level
        trios = [grid.parse_trio(text) for text in (args.trio or ["pal-mnk-ber"])]
        catalog_path = args.catalog if args.catalog is not None else grid.find_catalog(args.root)
        if catalog_path is None:
            raise ValueError("no catalog found; build one or pass --catalog")
        document = load_strict(catalog_path)
        spells = load_strict(args.root / "derived" / "client" / f"spells-l{level}.json")
        version = document.get("version") if isinstance(document, dict) else None
        release = f"data-{version}" if isinstance(version, str) else None
        effect_spells = args.root / "derived" / "client" / "effect-spells.json"
        bundles = {
            f"{grid.trio_slug(codes)}-l{level}.json": render_bundle(
                bundle(
                    codes, level, tables, rules, spells, data_release=release, catalog=document,
                    procs=grid.proc_table(document["items"], codes, rules, effect_spells) if effect_spells.is_file() else None,
                )
            )
            for codes in trios
        }
        listing = items(document, rules)
        table = render_items(listing)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"trioforge.export.browser: {error}", file=sys.stderr)
        return 2
    commit_files(args.out / "bundles", bundles)
    commit_files(args.out, {"items.json": table})
    lines = [_report(f"bundles/{name}", text) for name, text in bundles.items()] + [_report("items.json", table)]
    shared = shared_match_names(listing)
    lines.append(f"match names shared by more than one item: {len(shared)} ({sum(map(len, shared.values()))} items)")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
