"""The independent exact-formula evaluator: the oracle for every exactness test of the solver.

Everything here is exact (:class:`fractions.Fraction`; a float is read as the decimal it was written as) and
shares no code with the MILP builder. It encodes the rules of ``rules/rules.json`` and the model's design, with
**no integer floors**: the MILP is linear between knees, so the oracle is too. The integer floors of what the
game window prints live in :func:`stat_window` and nowhere else.

What :func:`evaluate` computes
==============================

``F`` is a weighted sum, in HP-equivalents, of the character's totals: naked stats + buffs + the worn kit.
The attribute totals are ``naked + buff + sum over the kit``; ``weights`` is the profile's table of
non-negative weights (a missing key is 0).

=========  =============================================================================================
part       value
=========  =============================================================================================
HP         ``HP`` x :func:`hp_total` (the two largest of ``5 + base_hp + hp_fac x STA'`` + item + buff HP)
MANA       ``MANA`` x :func:`mana_total` (the two largest class pools on their own stat; 0 with no mana
           class, whatever items give)
END        ``END`` x :func:`end_total` (the two largest of ``base_end + end_fac x conv(A)``)
AC         ``AC / (4/3)`` x the capped sheet armor class (:func:`sheet_ac_parts`)
MONK       ``AC / (4/3)`` x the Monk worn-weight bonus, when it sits on top of the cap
IKSAR      ``AC / (4/3)`` x the racial armor class, when it sits on top of the cap
EVASION    ``AC`` x 0.2222 x AGI (AGI counted from 0 to 510)
ATK        ``ATK`` x (0.666667 x STR (0 to 510) + item ATK + buff ATK)
DEX        ``DEX`` x (DEX to 510: a point a point, with no break at 255)
HASTE      ``HASTE`` x the haste counted (below)
REGEN      sum of ``HPREG`` / ``MANAREG`` / ``ENDREG`` x (gear regen up to its cap + buff regen)
RESISTS    per school (FIRE COLD MAGIC POISON DISEASE) ``SV_<school>`` (else ``SV``) x min(gear + buff, cap)
CHA        ``CHA`` x CHA (0 to 510)
WEAPON     ``DMG`` x the sum of the weapon index of the PRIMARY and the SECONDARY item under the setup, and of the
           RANGE item under the ``ranged`` setup (:func:`weapon_index`: the bonus is the primary hand's; a hand the
           setup does not allow, and the ``stick`` setup, score 0; the ``ranged`` setup scores the bow in the range
           place on its own damage per delay, with no damage bonus, times the profile's ``ranged_factor``, and nothing else). With a table of procs
           (``evaluate(..., procs=...)``, :mod:`trioforge.model.procs`) each hand that swings adds ``DMG`` x the proc it counts / 600, with no haste factor
=========  =============================================================================================

* A stat curve is ``pwl`` from total 0: a total at or below zero is worth 0, and every stat stops at 510.
* **Sheet AC.** The worn armor class is every worn item's AC except an off-hand shield's. Only an item that
  is a shield **and sits in the SECONDARY place** is the off-hand shield: a shield in an Any place counts as
  worn armor. AGI in the sheet term is counted to 510. Spell AC is the buff totals' ``AC``.
* **Bonuses on the sheet.** The Monk bonus (the sum of every worn item's ``weight10`` through
  :func:`monk_bonus`) and the Iksar racial armor class sit either **inside** (``placement`` ``"inside"``: added to X before the cap, which is
  the client's reading and the default of a profile) or **on top** (``"top"``: added after the cap, valued at the sheet-point weight, the alternative).
* **Haste.** Only the best worn haste counts. ``counted = min(cap, spell + best worn)`` with
  ``worn counted = min(best worn, max(0, cap - spell))``, so a spell haste at or above the cap leaves no room. The
  ``spell`` here is the best buff haste plus ``haste_bonus``, the flat haste of Unbound Alacrity (10 for a trio with a
  Monk, else 0), which stacks with both and is cut by the same cap.
* **Regen.** Gear regen counts up to the cap (``caps["regen"]``); buff regen sits outside it.
* **Resists.** Gear plus buffs count up to ``caps["resist"]``. Racial resists are not modelled.
* **Pools.** HP pools exist for every class, mana pools for the classes with a mana stat (WIS or INT), END
  pools for every class; the ``POOLS_COUNTED`` (2) largest count, ties in trio order. Natural Durability (AA 107,
  ``hp.natural_durability_pct``) adds its percent to the HP that comes from STA, the ``hp_fac x STA'`` of an HP pool, and to nothing
  else: not the 5, not the class base, not the flat HP of items and buffs. A profile has it in the ``fac`` of its HP pools
  (``Profile.nd_pct`` says how much), so the evaluator, the builder and the browser read it without a rule of their own; the
  functions that read the client's pools themselves (:func:`hp_total`, :func:`counted_pools`, :func:`stat_window`) take ``nd_pct``.

The profile
===========

``evaluate`` reads its profile by attribute (see :class:`EvalProfile`, which has all of them with checks and
defaults); any object with those attributes works. ``profile.buff_totals`` and the ``buffs`` argument are
buff totals in the same shape: attribute and pool keys at the top (``STR ... CHA AC HP MANA END ATK HPREG
MANAREG ENDREG HASTE``) and ``"SV": {school: points}``; when ``buffs`` is given it **replaces**
``profile.buff_totals`` (it is the totals of the always-on buffs plus the chosen ones).

Kit
===

``kit`` is a list with one entry (an :class:`~trioforge.model.items.ItemVec` or None) per place of
:data:`~trioforge.model.items.SLOT_INSTANCES`. The evaluator does not judge whether a kit is legal (slots,
classes, Lore, two-handers): enumerating legal kits is the caller's job. It does refuse a stat or resist it does
not know. The Monk weight is the sum of every worn item's ``weight10``; an item whose page gave no weight has
``weight10 = 10`` (1.0 stone: :func:`trioforge.model.items.at_tier` sets it) and ``weight_known = False``.

The legacy objective
====================

``evaluate(..., legacy=LegacyTerms(...))`` values a kit the way the old tools did, so that the private regression
(``trioforge.solver.compat``) can run an old profile through the exact builder. It is an option and nothing above
changes without it. The differences:

* HP, mana and END are **flat**: the gear and buff points times the weight, with no class pools (the old profile put the
  pools into its curves);
* the attribute curves are the profile's **explicit** ones, :class:`LegacyCurve` (``factor`` x ``pwl`` of the
  attribute total), summed in the part ``CURVES``; the evasion, strength-to-attack, DEX and charisma terms of the
  model are left out;
* the sheet armor class is :class:`LegacySheet`: ``X = mult x (worn + shield) + nongear`` (a constant for what is not
  gear; AGI is not in it), ``Y = cap + shield`` with no floor, the same ``min(X, ret X + (1 - ret) Y)``, valued at
  ``AC / mult`` per sheet point; there is no Monk or Iksar bonus (the profile must have none).

Everything else (haste, regen, resists, weapon damage) is the model's.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, field, fields
from fractions import Fraction
from typing import Any, NamedTuple

from trioforge.classes import CLASS_CODES
from trioforge.model import procs as procs_module
from trioforge.model.items import SLOT_INSTANCES, ItemVec, WeaponVec
from trioforge.model.tables import Tables

__all__ = [
    "AGI_TO_AC",
    "ATTRIBUTES",
    "Breakdown",
    "DEX_PAST_KNEE",
    "EvalProfile",
    "LegacyCurve",
    "LegacySheet",
    "LegacyTerms",
    "MANA_BANDS",
    "POOLS_COUNTED",
    "PoolSpec",
    "SCHOOLS",
    "SETUPS",
    "SHEET_AGI_DIV",
    "SHEET_DEFENSE_DIV",
    "SHEET_ITEM_MULT",
    "SHEET_SPELL_AC_DIV",
    "STAT_CAP",
    "STAT_KNEE",
    "STA_CURVE",
    "STR_TO_ATK",
    "SheetAC",
    "check_legacy",
    "compile_profile",
    "conv_end",
    "conv_mana",
    "counted_pools",
    "effective_sta",
    "end_total",
    "evaluate",
    "evaluate_truthful",
    "fr",
    "haste_cap_at",
    "hp_total",
    "mana_total",
    "monk_bonus",
    "monk_curve",
    "naked",
    "pools_for",
    "pwl",
    "sheet_ac",
    "sheet_ac_parts",
    "stat_window",
    "fallback_bonus",
    "weapon_index",
]

# ---- the model's constants (each is checked against rules/rules.json by the tests) ------------

ATTRIBUTES = ("STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA")
SCHOOLS = ("FIRE", "COLD", "MAGIC", "POISON", "DISEASE")  # CORRUPTION is never scored
SETUPS = (None, "1h-shield", "2h", "dw", "stick", "ranged")

STAT_KNEE = 255  # stats.knee
STAT_CAP = 510  # stats.hard_cap
HP_POOL_CONSTANT = 5  # the 5 in 5 + base_hp + hp_fac x STA'; the client's formula, not a rule
POOLS_COUNTED = 2  # hp.pools_counted, mana.pools_counted
STA_CURVE = ((255, 510), (Fraction(1), Fraction(1, 2), Fraction(0)))  # hp.sta_curve
# mana.wis_bands
MANA_BANDS = ((100, 200, 510), (Fraction(1), Fraction(5, 2), Fraction(5, 4), Fraction(0)))
END_BREAKS = (100, 201)  # the END conversion: x to 100, 2.5 a point to 201, 1.25 a point after
END_SLOPES = (Fraction(1), Fraction(5, 2), Fraction(5, 4))
STR_TO_ATK = Fraction("0.666667")  # stats.str_to_atk
AGI_TO_AC = Fraction("0.2222")  # stats.agi_to_ac
DEX_PAST_KNEE = Fraction(1)  # stats.dex_post255_slope (the client has no break at 255 for dexterity)
SHEET_ITEM_MULT = Fraction(4, 3)  # ac.sheet.item_mult (the rules file prints it to ten digits)
SHEET_DEFENSE_DIV = 3  # ac.sheet.defense_div
SHEET_SPELL_AC_DIV = 4  # ac.sheet.spell_ac_div
SHEET_AGI_DIV = 20  # ac.sheet.agi_div
STANDARD_CAPS = {"regen": {"HP": 30, "MANA": 15, "END": 15}, "resist": 1000}  # regen.gear_caps, resist.cap
HAND_PLACES = ("PRIMARY", "SECONDARY")
_RANGE_PLACE = "RANGE"  # the place a bow stands in, scored under the ``ranged`` setup
_BOW_SKILL = "archery"  # the skill of a bow (weapons.BOW_SKILL, read without regard to case)

_ZERO = Fraction(0)


def haste_cap_at(level: int) -> int:
    """The cap of the total haste at ``level``, the game client's own calculation (``haste.cap_pct``): ``max(level, 30) + 25`` up to level 50 (75 at 50), 85 for levels 51 to 59 and 100 from level 60.
    A trio with a Monk adds the 10 of Unbound Alacrity (``haste.cap_pct_with_monk``)."""
    if type(level) is not int or level < 1:
        raise ValueError(f"level must be a whole number of at least 1, not {level!r}")
    if level >= 60:
        return 100
    if level > 50:
        return 85
    return max(level, 30) + 25


# ---- exact arithmetic ----------------------------------------------------------------------


def fr(x: Any) -> Fraction:
    """A number as a Fraction; a float is read as its shortest decimal text (4.8 is 24/5, not 4.79999...)."""
    if isinstance(x, Fraction):
        return x
    if isinstance(x, bool):
        raise TypeError(f"a number is needed, not {x!r}")
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, float):
        return Fraction(repr(x))
    if isinstance(x, str):
        return Fraction(x.strip())
    raise TypeError(f"a number is needed, not {type(x).__name__}")


def pwl(x: Any, breaks: Sequence[Any], slopes: Sequence[Any]) -> Fraction:
    """The continuous piecewise-linear value of ``x`` from 0: ``slopes[i]`` times the part of ``x`` inside band i.

    Band 0 runs from 0 to ``breaks[0]``, band i from ``breaks[i-1]`` to ``breaks[i]``, and the last band
    from the last break up; ``slopes`` has one more entry than ``breaks``. A value at or below 0 is worth 0.
    """
    x = fr(x)
    total, low = _ZERO, _ZERO
    for brk, slope in zip(breaks, slopes):
        if x <= low:
            return total
        brk = fr(brk)
        total += fr(slope) * (min(x, brk) - low)
        low = brk
    return total + fr(slopes[-1]) * (x - low) if x > low else total


def effective_sta(sta: Any) -> Fraction:
    """STA as the HP pools see it: STA to 255, half a point per point to 510, nothing after."""
    return pwl(sta, *STA_CURVE)


def conv_end(average: Any) -> Fraction:
    """The END average as the END pools see it: x to 100, 2.5 a point to 201, then 1.25 a point (352.5 at 201)."""
    return pwl(average, END_BREAKS, END_SLOPES)


def _bands(bands: Any) -> tuple[Sequence[Any], Sequence[Any]]:
    if bands is None:
        return MANA_BANDS
    breaks, slopes = (bands["breaks"], bands["slopes"]) if isinstance(bands, Mapping) else bands
    rising = all(fr(a) < fr(b) for a, b in zip(breaks, breaks[1:]))
    if len(slopes) != len(breaks) + 1 or not rising or any(fr(s) < 0 for s in slopes):
        raise ValueError("a band curve needs one more slope than breaks, rising breaks and slopes of at least 0")
    return breaks, slopes


def conv_mana(stat: Any, bands: Any = None) -> Fraction:
    """WIS or INT as the mana pools see it, through ``bands`` (``{"breaks", "slopes"}``; the rule default when None)."""
    return pwl(stat, *_bands(bands))


# ---- naked stats and pools -----------------------------------------------------------------


def _trio(trio: Sequence[str]) -> tuple[str, ...]:
    codes = tuple(trio)
    if not codes or len(set(codes)) != len(codes) or any(code not in CLASS_CODES for code in codes):
        raise ValueError(f"a trio is different class codes from {' '.join(CLASS_CODES)}, not {codes!r}")
    return codes


def naked(race: str, trio: Sequence[str], tables: Tables) -> dict[str, int]:
    """A character with no gear and no buffs: the race's base plus the three class modifiers, not capped."""
    codes = _trio(trio)
    if len(codes) != 3:
        raise ValueError(f"a trio is three classes, not {len(codes)}")
    races = {entry["code"]: entry for entry in tables.races["races"]}
    classes = {entry["code"]: entry for entry in tables.races["classes"]}
    if race not in races:
        raise ValueError(f"unknown race {race!r}")
    base = races[race]["base"]
    return {stat: base[stat] + sum(classes[code]["mods"][stat] for code in codes) for stat in ATTRIBUTES}


@dataclass(frozen=True)
class PoolSpec:
    """One class's pool: ``base + fac x <input>``. ``stat`` ("WIS" or "INT") names the input of a mana pool."""

    cls: str
    base: Fraction
    fac: Fraction
    stat: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "base", fr(self.base))
        object.__setattr__(self, "fac", fr(self.fac))
        if self.stat not in (None, "WIS", "INT"):
            raise ValueError(f"a mana pool counts WIS or INT, not {self.stat!r}")


def pools_for(trio: Sequence[str], level: int, tables: Tables) -> dict[str, tuple[PoolSpec, ...]]:
    """The HP, mana and END pools of a trio at a level, from the client table.

    HP and END have one pool per class; MANA has one per class that has a mana stat and a mana pool at that
    level, in trio order. Raises ``ValueError`` for a trio that is not distinct class codes and ``KeyError``
    for a level the table does not have.
    """
    codes = _trio(trio)
    stat_of = {code: stat for stat, classes in tables.rules.get("mana.stat_by_class").items() for code in classes}
    hp, mana, end = [], [], []
    for code in codes:
        row = tables.basedata[(code, level)]
        hp.append(PoolSpec(code, row["hp"], row["hp_fac"]))
        end.append(PoolSpec(code, row["end"], row["end_fac"]))
        if code in stat_of and (row["mana"] > 0 or row["mana_fac"] > 0):
            mana.append(PoolSpec(code, row["mana"], row["mana_fac"], stat_of[code]))
    return {"HP": tuple(hp), "MANA": tuple(mana), "END": tuple(end)}


class _Pool(NamedTuple):
    total: Fraction
    counted: tuple[str, ...]  # the classes whose pools count, largest first (ties in trio order)
    extra: Fraction = _ZERO  # END: the average of the four stats


def _best(values: Sequence[Fraction], n: int = POOLS_COUNTED) -> list[int]:
    """Indexes of the ``n`` largest values; ties stay in the order given (the sort is stable)."""
    return sorted(range(len(values)), key=lambda i: -values[i])[:n]


def _hp(pools: Sequence[PoolSpec], sta: Any, item_hp: Any, buff_hp: Any, nd_pct: Any = 0) -> _Pool:
    """The HP pools: ``5 + base + fac x STA'`` with the percent of Natural Durability on the ``fac x STA'`` part, and the flat points after."""
    effective = effective_sta(sta)
    scale = 1 + fr(nd_pct) / 100
    values = [HP_POOL_CONSTANT + p.base + p.fac * effective * scale for p in pools]
    top = _best(values)
    return _Pool(sum((values[i] for i in top), _ZERO) + fr(item_hp) + fr(buff_hp), tuple(pools[i].cls for i in top))


def _mana(pools: Sequence[PoolSpec], wis: Any, int_: Any, item_mana: Any, buff_mana: Any, bands: Any) -> _Pool:
    if not pools:
        return _Pool(_ZERO, ())
    converted = {"WIS": conv_mana(wis, bands), "INT": conv_mana(int_, bands)}
    values = [p.base + p.fac * converted[p.stat] for p in pools]
    top = _best(values)
    return _Pool(sum((values[i] for i in top), _ZERO) + fr(item_mana) + fr(buff_mana), tuple(pools[i].cls for i in top))


def _end(pools: Sequence[PoolSpec], stats: Sequence[Any], item_end: Any, buff_end: Any) -> _Pool:
    average = sum((min(fr(v), STAT_CAP) for v in stats), _ZERO) / 4
    converted = conv_end(average)
    values = [p.base + p.fac * converted for p in pools]
    top = _best(values)
    total = sum((values[i] for i in top), _ZERO) + fr(item_end) + fr(buff_end)
    return _Pool(total, tuple(pools[i].cls for i in top), average)


def hp_total(
    trio: Sequence[str], level: int, sta_total: Any, item_hp: Any, buff_hp: Any, tables: Tables, *, nd_pct: Any = 0
) -> Fraction:
    """Max HP: the two largest of ``5 + base_hp + hp_fac x STA'``, plus item and buff HP.

    ``nd_pct`` is the percent of Natural Durability (0 for none): it multiplies the ``hp_fac x STA'`` part of each pool and not the
    constant, the base or the flat points.
    """
    return _hp(pools_for(trio, level, tables)["HP"], sta_total, item_hp, buff_hp, nd_pct).total


def mana_total(
    trio: Sequence[str], level: int, wis: Any, int_: Any, item_mana: Any, buff_mana: Any, tables: Tables,
    bands: Any = None,
) -> Fraction:
    """Max mana: the two largest class pools ``base_mana + mana_fac x conv(WIS or INT)`` plus item and buff mana.

    A trio with no mana class has no mana, whatever its items give. ``bands`` is the WIS/INT band curve.
    """
    return _mana(pools_for(trio, level, tables)["MANA"], wis, int_, item_mana, buff_mana, bands).total


def end_total(
    trio: Sequence[str], level: int, str_: Any, sta: Any, dex: Any, agi: Any, item_end: Any, buff_end: Any,
    tables: Tables,
) -> Fraction:
    """Max endurance: the two largest ``base_end + end_fac x conv(A)``, A the average of STR, STA, DEX and AGI
    (each counted to 510), plus item and buff END."""
    return _end(pools_for(trio, level, tables)["END"], (str_, sta, dex, agi), item_end, buff_end).total


def counted_pools(
    trio: Sequence[str], level: int, attrs: Mapping[str, Any], tables: Tables, bands: Any = None, *, nd_pct: Any = 0
) -> dict[str, tuple[str, ...]]:
    """Which classes' pools count: ``{"HP": ..., "MANA": ..., "END": ...}``.

    Each tuple lists the classes largest pool first, ties in trio order. ``attrs`` holds the attribute totals
    STR STA AGI DEX WIS INT.
    """
    pools = pools_for(trio, level, tables)
    return {
        "HP": _hp(pools["HP"], attrs["STA"], 0, 0, nd_pct).counted,
        "MANA": _mana(pools["MANA"], attrs["WIS"], attrs["INT"], 0, 0, bands).counted,
        "END": _end(pools["END"], (attrs["STR"], attrs["STA"], attrs["DEX"], attrs["AGI"]), 0, 0).counted,
    }


def stat_window(
    trio: Sequence[str], level: int, attrs: Mapping[str, Any], item: Mapping[str, Any], buff: Mapping[str, Any],
    tables: Tables, bands: Any = None, *, nd_pct: Any = 0,
) -> dict[str, Any]:
    """What the game's stat window prints: the pools of :func:`hp_total` and the others with the integer floors.

    ``attrs`` holds the attribute totals STR STA AGI DEX WIS INT; ``item`` and ``buff`` hold flat ``HP``,
    ``MANA`` and ``END`` points (missing means 0). Each piece is floored the way the client does: STA' (and the
    converted WIS, INT and END average) to a whole number, then each ``factor x that`` to a whole number; the two
    largest pools by those whole numbers count (ties in trio order) and the flat points are added whole. A trio
    without a mana class prints 0 mana. A negative converted value counts as 0.

    ``nd_pct`` is the percent of Natural Durability (0 for none). It applies to the HP that comes from STA: the whole number
    ``floor(hp_fac x STA')`` of each HP pool is multiplied by ``(100 + nd_pct) / 100`` and floored again (245 becomes 274 at 12
    percent), and the 5, the class base and the flat item and buff points are left as they are.

    Returns ``HP``, ``MANA`` and ``END`` (ints), ``hp_pools``, ``mana_pools``, ``end_pools`` (the classes that count)
    and ``hp_pool_values``, ``mana_pool_values``, ``end_pool_values`` (every pool's whole value, by class).
    """
    pools = pools_for(trio, level, tables)
    flat = {k: fr(item.get(k, 0)) + fr(buff.get(k, 0)) for k in ("HP", "MANA", "END")}

    def family(specs: Sequence[PoolSpec], converted: Sequence[int], constant: int, points: Fraction, aa_pct: Any = 0):
        rows = []
        for spec, c in zip(specs, converted):
            part = math.floor(spec.fac * c)
            if aa_pct:
                part = math.floor(part * (100 + fr(aa_pct)) / 100)
            rows.append((spec.cls, constant + math.floor(spec.base) + part, constant + spec.base + part))
        top = _best([row[1] for row in rows])
        total = math.floor(sum((rows[i][2] for i in top), _ZERO) + points) if rows else 0
        return total, tuple(rows[i][0] for i in top), {row[0]: row[1] for row in rows}

    sta_floor = math.floor(effective_sta(attrs["STA"]))
    hp = family(pools["HP"], [sta_floor] * len(pools["HP"]), HP_POOL_CONSTANT, flat["HP"], nd_pct)
    stat_floor = {"WIS": math.floor(conv_mana(attrs["WIS"], bands)), "INT": math.floor(conv_mana(attrs["INT"], bands))}
    mana = family(pools["MANA"], [stat_floor[p.stat] for p in pools["MANA"]], 0, flat["MANA"])
    average = sum((min(fr(attrs[k]), STAT_CAP) for k in ("STR", "STA", "DEX", "AGI")), _ZERO) / 4
    end_floor = math.floor(conv_end(average))
    end = family(pools["END"], [end_floor] * len(pools["END"]), 0, flat["END"])
    return {
        "HP": hp[0], "MANA": mana[0], "END": end[0],
        "hp_pools": hp[1], "mana_pools": mana[1], "end_pools": end[1],
        "hp_pool_values": hp[2], "mana_pool_values": mana[2], "end_pool_values": end[2],
    }


# ---- sheet armor class ---------------------------------------------------------------------


class SheetAC(NamedTuple):
    """X (what the sheet would read without the softcap), Y (the softcap incl. the shield) and the result."""

    x: Fraction
    y: Fraction
    sheet: Fraction


def sheet_ac_parts(
    worn_ac: Any, shield_ac: Any, defense_cap: Any, spell_ac: Any, agi_total: Any, softcap: Any, past_cap_rate: Any,
    cs_pct: Any, pe_pct: Any, *, inside: Any = 0,
) -> SheetAC:
    """The character-sheet armor class and the two values it is made of.

    ``X = 4/3 x (worn + shield) + defense/3 + spell_ac/4 + agi/20 (+ inside)``; ``Y = floor(softcap x (100 + cs + pe)
    / 100) + shield``; the result is ``min(X, rate x X + (1 - rate) x Y)``. ``inside`` is a bonus that rides in X
    before the cap (where the game client puts the Monk worn-weight bonus and the Iksar racial armor class; ``"top"``, after the cap, is the alternative the robustness pass tries).
    """
    rate = fr(past_cap_rate)
    if not 0 <= rate <= 1:
        raise ValueError(f"the rate past the softcap must be from 0 to 1, not {past_cap_rate!r}")
    shield = fr(shield_ac)
    x = (
        SHEET_ITEM_MULT * (fr(worn_ac) + shield)
        + fr(defense_cap) / SHEET_DEFENSE_DIV
        + fr(spell_ac) / SHEET_SPELL_AC_DIV
        + fr(agi_total) / SHEET_AGI_DIV
        + fr(inside)
    )
    y = math.floor(fr(softcap) * (100 + fr(cs_pct) + fr(pe_pct)) / 100) + shield
    return SheetAC(x, y, min(x, rate * x + (1 - rate) * y))


def sheet_ac(
    worn_ac: Any, shield_ac: Any, defense_cap: Any, spell_ac: Any, agi_total: Any, softcap: Any, past_cap_rate: Any,
    cs_pct: Any, pe_pct: Any, *, inside: Any = 0,
) -> Fraction:
    """The character-sheet armor class (see :func:`sheet_ac_parts`)."""
    parts = sheet_ac_parts(
        worn_ac, shield_ac, defense_cap, spell_ac, agi_total, softcap, past_cap_rate, cs_pct, pe_pct, inside=inside
    )
    return parts.sheet


# ---- the Monk worn-weight bonus ------------------------------------------------------------

MONK_SHAPE = "EQEmu fade"


def _full_monk_bonus(level: int) -> int:
    return int((4.0 * (level + 5.0)) / 3.0)


def monk_curve(rules: Any, level: int, *, full_until: int | None = None) -> dict[str, Any]:
    """The Monk bonus curve of ``rules`` (``monk.weight_curve``) at ``level``, for :func:`monk_bonus`.

    ``full_until`` selects the alternative reading ("the full bonus up to N whole stones"; the rules file names 34).
    Raises ``ValueError`` for a curve of another shape.
    """
    value = rules.get("monk.weight_curve", level)
    if value.get("shape") != MONK_SHAPE:
        raise ValueError(f"monk.weight_curve has shape {value.get('shape')!r}, but only {MONK_SHAPE!r} is implemented")
    curve = {key: value[key] for key in ("softcap_stones", "hardcap_stones", "full_bonus_ac")}
    if full_until is not None:
        curve["full_until_stones"] = full_until
    return curve


def monk_bonus(level: int, worn_weight10: int, curve: Mapping[str, Any] | None) -> int:
    """The Monk armor class bonus (negative is a penalty) for a worn weight in tenths of a stone.

    Only whole stones count. The default shape fades from the full bonus at ``softcap_stones`` to nothing, gives
    0 up to the hardcap and a growing penalty after it; ``full_until_stones`` in the curve keeps the full bonus up
    to that many whole stones and follows the same shape above. Float arithmetic exactly as the reference
    (truncation toward zero through ``int``): exact fractions differ on a few weights.
    """
    if curve is None:
        raise ValueError("monk_bonus needs a curve (the profile has none: the trio has no Monk)")
    full = _full_monk_bonus(level)
    if "full_bonus_ac" in curve and curve["full_bonus_ac"] != full:
        raise ValueError(f"the curve's full_bonus_ac is {curve['full_bonus_ac']!r}, but level {level} gives {full}")
    soft, hard = curve["softcap_stones"], curve["hardcap_stones"]
    weight = worn_weight10 // 10
    full_until = curve.get("full_until_stones")
    if full_until is not None and weight <= full_until:
        return full
    if weight < hard - 1:
        temp = level + 5.0
        if weight > soft:
            redux = (weight - soft) * 6.66667
            redux = (100.0 - min(100.0, redux)) * 0.01
            temp = max(0.0, temp * redux)
        return int((4.0 * temp) / 3.0)
    if weight > hard + 1:
        temp = (4.0 * (level + 5.0)) / 3.0
        multiplier = min(1.0, (weight - (hard - 10.0)) / 100.0)
        return -int(temp * multiplier)
    return 0


# ---- weapons -------------------------------------------------------------------------------


def _ranged_skill(weapon: WeaponVec) -> bool:
    """A weapon of the archery skill or of a throwing skill (``Throwing``, ``Throwingv1``, ``Throwingv2``), in any case."""
    skill = (weapon.skill or "").casefold()
    return skill == _BOW_SKILL or skill.startswith("throwing")


# the damage bonus of a main hand when the item lists none (``weapons.fallback_bonus``): the definition of :mod:`trioforge.model.weapons` written out again
_BONUS_FROM_LEVEL, _BONUS_LEVEL_DIV, _BONUS_DELAY_CAP, _BONUS_DELAY_DIV = 28, 100, 50, 40
_BONUS_FACTORS = {False: Fraction(4, 5), True: Fraction(11, 10)}  # a one-hander's and a two-hander's


def fallback_bonus(damage: Any, delay: Any, two_handed: bool, level: int) -> Fraction:
    """``(level / 100) x max(damage, level) x f x min(delay, 50) / 40``, f 0.8 for a one-hander and 1.1 for a two-hander, and 0 below level 28 (exact: the client rounds it down when it shows it)."""
    if level < _BONUS_FROM_LEVEL:
        return _ZERO
    return Fraction(level, _BONUS_LEVEL_DIV) * max(fr(damage), level) * _BONUS_FACTORS[bool(two_handed)] * min(fr(delay), _BONUS_DELAY_CAP) / _BONUS_DELAY_DIV


def weapon_index(
    weapon: WeaponVec, hand: str, setup: str | None, haste_assumed: Any, dw_factor: Any, ranged_factor: Any = 1, level: int = 50
) -> Fraction:
    """One hand's damage index under a setup, the definition of :mod:`trioforge.model.weapons` written out again.

    * The **primary** hand scores ``(dmg + bonus) / delay x (1 + haste/100)``: the bonus is the one the page lists, else the client's formula of the level (:func:`fallback_bonus`: at
      level 50 half the delay for a one-hander and 0.6875 x the delay, at most 50, for a two-hander, where the damage is no more than the level) (a listed bonus of 0 counts as not
      listed). The bonus belongs to the primary hand alone.
    * The **secondary** hand scores ``dmg / delay x (1 + haste/100) x dw_factor``: no bonus, and only dual wield
      puts a weapon there.
    * A hand the setup does not allow scores **0**: ``2h`` takes a two-hander in the primary hand and nothing in the
      secondary; ``dw`` takes a one-hander in either hand; ``1h-shield`` takes a one-hander in the primary hand (the
      secondary hand takes a shield, which has no weapon). The ``stick`` setup, and no setup (``None``), score no
      weapon damage at all. A weapon with no damage or no delay scores 0.
    * The **range** place scores under the ``ranged`` setup alone, and only a bow (a weapon of the archery skill) in it: its own
      ``dmg / delay x (1 + haste/100)`` times ``ranged_factor`` (the rule ``weapons.ranged_factor``), with no damage bonus (a bonus
      is a main hand's, and nothing says archery gets it) and no arrow damage. Under ``ranged`` the two hands score nothing.
    """
    if hand not in (*HAND_PLACES, _RANGE_PLACE):
        raise ValueError(f"a hand is PRIMARY, SECONDARY or RANGE, not {hand!r}")
    if setup in (None, "stick") or not weapon.dmg > 0 or not weapon.delay > 0:
        return _ZERO
    if setup == "ranged":
        allowed = hand == _RANGE_PLACE and (weapon.skill or "").casefold() == _BOW_SKILL
    elif hand == _RANGE_PLACE:
        allowed = False
    elif setup == "2h":
        allowed = hand == "PRIMARY" and weapon.two_handed
    elif setup == "dw":
        allowed = not weapon.two_handed
    else:  # "1h-shield"
        allowed = hand == "PRIMARY" and not weapon.two_handed
    if not allowed or (hand != _RANGE_PLACE and _ranged_skill(weapon)):  # (a bow or a thrown weapon is never scored in a hand: the builder refuses it the hand, weapons.allowed_in_hand)
        return _ZERO
    haste = 1 + fr(haste_assumed) / 100
    if hand == "SECONDARY":
        return fr(weapon.dmg) / weapon.delay * haste * fr(dw_factor)
    if hand == _RANGE_PLACE:  # a bow's own damage per delay: no damage bonus (a main hand's), no arrow damage
        return fr(weapon.dmg) / weapon.delay * haste * fr(ranged_factor)
    bonus = fr(weapon.bonus) if weapon.bonus else fallback_bonus(weapon.dmg, weapon.delay, weapon.two_handed, level)
    return (fr(weapon.dmg) + bonus) / weapon.delay * haste


# ---- the profile ---------------------------------------------------------------------------

WEIGHT_KEYS = frozenset(
    {"HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "CHA", "HPREG", "MANAREG", "ENDREG", "DMG", "SV"}
    | {f"SV_{school}" for school in SCHOOLS}
)
BUFF_KEYS = frozenset(set(ATTRIBUTES) | {"AC", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG", "HASTE", "SV"})
ITEM_STATS = frozenset(set(ATTRIBUTES) | {"AC", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG"})  # not HASTE
PLACEMENTS = ("top", "inside")


def _default_placement() -> dict[str, str]:
    """Where a profile that is given no placement puts the Monk bonus and the Iksar racial armor class: inside X before the cap, as the game client does (the rules ``monk.bonus_placement``
    and ``race.iksar_ac_placement``, which :func:`trioforge.model.profile.placements` reads; a test holds the two together)."""
    return {"monk": "inside", "iksar": "inside"}



def _pool_spec(entry: Any) -> PoolSpec:
    if isinstance(entry, PoolSpec):
        return entry
    if isinstance(entry, Mapping):
        return PoolSpec(entry["cls"], entry["base"], entry["fac"], entry.get("stat"))
    return PoolSpec(*entry)


def _number(value: Any) -> Any:
    """A whole number stays an int (faster sums); anything else becomes a Fraction."""
    return value if type(value) is int else fr(value)


def _non_negative(name: str, value: Any) -> Fraction:
    number = fr(value)
    if number < 0:
        raise ValueError(f"{name} must not be negative, not {value!r}")
    return number


@dataclass(frozen=True)
class EvalProfile:
    """Everything :func:`evaluate` reads about a scenario, checked and normalized (weights and pools as Fractions).

    ``level``, ``naked`` (the seven attributes), ``weights`` (see the module docstring) and ``pools`` (``HP``,
    ``MANA`` and ``END`` tuples of :class:`PoolSpec`; HP and END are never empty) are required. The rest default
    to "nothing": ``buff_totals`` (the always-on buffs), ``haste_cap``, ``softcap`` = ``(cap, rate past it)``,
    ``cs_pct`` and ``pe_pct`` (percent added to the softcap), ``defense_cap``, ``monk`` (a curve for
    :func:`monk_bonus`, or None), ``iksar_ac``, ``placement`` (``"top"`` or ``"inside"`` for ``monk`` and
    ``iksar``; both ``"inside"`` by default, the client's), ``caps`` (``{"regen": {"HP", "MANA", "END"}, "resist": n}``), ``bands`` (the mana band curve,
    None for the rule default), ``dw_factor`` (the multiplier of the second hand under dual wield), ``ranged_factor`` (the
    multiplier of a bow in the range place under the ``ranged`` setup; 1 by default),
    ``haste_bonus`` (the flat haste of Unbound Alacrity, added to the buff haste; 0 by default) and ``stance`` (None, or ``{"swing_factor", "agi_share"}``: the Berserker stance,
    whose factor multiplies the swing of the two hands after the haste cap, and whose share of AGI is what counts of it in the sheet armor class and the evasion).
    """

    level: int
    naked: Mapping[str, Any]
    weights: Mapping[str, Any]
    pools: Mapping[str, Sequence[PoolSpec]]
    buff_totals: Mapping[str, Any] = field(default_factory=dict)
    haste_cap: Any = 75
    softcap: Sequence[Any] = (0, 0)
    cs_pct: Any = 0
    pe_pct: Any = 0
    defense_cap: Any = 0
    monk: Mapping[str, Any] | None = None
    iksar_ac: Any = 0
    placement: Mapping[str, str] = field(default_factory=_default_placement)
    caps: Mapping[str, Any] = field(
        default_factory=lambda: {"regen": dict(STANDARD_CAPS["regen"]), "resist": STANDARD_CAPS["resist"]}
    )
    bands: Any = None
    dw_factor: Any = 1
    haste_bonus: Any = 0
    ranged_factor: Any = 1
    stance: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        def put(name: str, value: Any) -> None:
            object.__setattr__(self, name, value)

        if type(self.level) is not int or self.level < 1:
            raise ValueError(f"level must be a whole number of at least 1, not {self.level!r}")
        missing = [stat for stat in ATTRIBUTES if stat not in self.naked]
        if missing:
            raise ValueError(f"naked lacks {', '.join(missing)}")
        put("naked", {stat: _number(self.naked[stat]) for stat in ATTRIBUTES})
        unknown = sorted(set(self.weights) - WEIGHT_KEYS)
        if unknown:
            raise ValueError(f"unknown weight {unknown[0]!r} (use {' '.join(sorted(WEIGHT_KEYS))})")
        put("weights", {key: _non_negative(f"weight {key}", value) for key, value in self.weights.items()})
        pools = {key: tuple(_pool_spec(entry) for entry in self.pools[key]) for key in ("HP", "MANA", "END")}
        if not pools["HP"] or not pools["END"]:
            raise ValueError("a trio has HP and END pools")
        if any(spec.stat is None for spec in pools["MANA"]):
            raise ValueError("a mana pool names its stat, WIS or INT")
        put("pools", pools)
        put("buff_totals", _buff_view(self.buff_totals))
        put("haste_cap", _non_negative("haste_cap", self.haste_cap))
        cap, rate = self.softcap
        put("softcap", (_non_negative("softcap", cap), fr(rate)))
        if not 0 <= self.softcap[1] <= 1:
            raise ValueError(f"the rate past the softcap must be from 0 to 1, not {rate!r}")
        for name in ("cs_pct", "pe_pct", "defense_cap", "iksar_ac", "dw_factor", "haste_bonus", "ranged_factor"):
            put(name, _non_negative(name, getattr(self, name)))
        if self.stance is not None:
            stance = self.stance
            if not isinstance(stance, Mapping) or set(stance) != {"swing_factor", "agi_share"}:
                raise ValueError(f"stance is None or a swing_factor and an agi_share, not {stance!r}")
            swing, share = fr(stance["swing_factor"]), fr(stance["agi_share"])
            if not swing > 0 or not 0 <= share <= 1:
                raise ValueError(f"stance is a swing_factor above 0 and an agi_share from 0 to 1, not {dict(stance)!r}")
            put("stance", {"swing_factor": swing, "agi_share": share})
        if self.monk is not None and not {"softcap_stones", "hardcap_stones"} <= set(self.monk):
            raise ValueError("a monk curve names softcap_stones and hardcap_stones")
        if set(self.placement) != {"monk", "iksar"} or any(v not in PLACEMENTS for v in self.placement.values()):
            raise ValueError(f"placement must say 'top' or 'inside' for monk and iksar, not {dict(self.placement)!r}")
        put("placement", dict(self.placement))
        regen = self.caps["regen"]
        put("caps", {"regen": {k: fr(regen[k]) for k in ("HP", "MANA", "END")}, "resist": fr(self.caps["resist"])})
        if self.bands is not None:
            breaks, slopes = _bands(self.bands)
            put("bands", {"breaks": tuple(fr(b) for b in breaks), "slopes": tuple(fr(s) for s in slopes)})


def _buff_view(totals: Mapping[str, Any]) -> dict[str, Any]:
    """Buff totals checked and normalized: known keys only, numbers as ints or Fractions, resists under "SV"."""
    unknown = sorted(set(totals) - BUFF_KEYS)
    if unknown:
        raise ValueError(f"unknown buff total {unknown[0]!r} (use {' '.join(sorted(BUFF_KEYS))})")
    view: dict[str, Any] = {k: _number(v) for k, v in totals.items() if k != "SV"}
    sv = totals.get("SV", {})
    bad = sorted(set(sv) - set(SCHOOLS))
    if bad:
        raise ValueError(f"unknown resist school {bad[0]!r} in the buff totals (use {' '.join(SCHOOLS)})")
    view["SV"] = {school: _number(sv[school]) for school in sv}
    return view


def compile_profile(profile: Any) -> EvalProfile:
    """``profile`` as an :class:`EvalProfile`: itself, or one made from the attributes of any object that has them."""
    if isinstance(profile, EvalProfile):
        return profile
    values = {}
    for item in fields(EvalProfile):
        if hasattr(profile, item.name):
            values[item.name] = getattr(profile, item.name)
        elif item.default is MISSING and item.default_factory is MISSING:
            raise ValueError(f"the profile has no {item.name!r}")
    return EvalProfile(**values)


# ---- the legacy objective (an option of evaluate and of the builder) -------------------------


@dataclass(frozen=True)
class LegacyCurve:
    """One explicit attribute curve of an old profile: ``factor`` x :func:`pwl` of the total of ``attr``.

    ``factor`` is the weight of the source the curve is worth (HP, mana, END ...) times the curve's scale. Like
    :func:`pwl`, ``slopes`` has one more entry than ``breaks``; the breaks rise strictly from above 0 and the slopes
    and the factor are at least 0 (the old exact solver needed a concave objective in every weight). Slopes may rise.
    """

    attr: str
    factor: Any
    breaks: Sequence[Any]
    slopes: Sequence[Any]

    def __post_init__(self) -> None:
        if self.attr not in ATTRIBUTES:
            raise ValueError(f"a legacy curve is on an attribute ({' '.join(ATTRIBUTES)}), not {self.attr!r}")
        breaks = tuple(fr(b) for b in self.breaks)
        slopes = tuple(fr(s) for s in self.slopes)
        if len(slopes) != len(breaks) + 1:
            raise ValueError(
                f"a legacy curve needs one more slope than breaks ({len(breaks)} breaks, {len(slopes)} slopes)"
            )
        if any(b <= 0 for b in breaks) or any(a >= b for a, b in zip(breaks, breaks[1:])):
            raise ValueError(f"the breaks of a legacy curve rise strictly from above 0, not {list(map(str, breaks))}")
        if any(s < 0 for s in slopes):
            raise ValueError("the slopes of a legacy curve must be at least 0")
        factor = fr(self.factor)
        if factor < 0:
            raise ValueError("the factor of a legacy curve must be at least 0")
        object.__setattr__(self, "factor", factor)
        object.__setattr__(self, "breaks", breaks)
        object.__setattr__(self, "slopes", slopes)


@dataclass(frozen=True)
class LegacySheet:
    """The old character-sheet armor class: ``X = mult x (worn + shield) + nongear``, ``Y = cap + shield`` (no floor),
    the result ``min(X, ret X + (1 - ret) Y)``, worth ``AC weight / mult`` per sheet point. With ``mult`` 1 and
    ``nongear`` 0 it is the old gear rule: gear armor class in full up to ``cap``, ``ret`` of the rest, the off-hand
    shield on top."""

    mult: Any
    nongear: Any
    cap: Any
    ret: Any

    def __post_init__(self) -> None:
        mult, nongear, cap, ret = (fr(v) for v in (self.mult, self.nongear, self.cap, self.ret))
        if mult <= 0:
            raise ValueError(f"the sheet's item multiplier (mult) must be above 0, not {self.mult!r}")
        if nongear < 0 or cap < 0:
            raise ValueError("the sheet's nongear and cap must be at least 0")
        if not 0 <= ret <= 1:
            raise ValueError(f"the share past the cap (ret) must be from 0 to 1, not {self.ret!r}")
        for name, value in (("mult", mult), ("nongear", nongear), ("cap", cap), ("ret", ret)):
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class LegacyTerms:
    """The option that switches :func:`evaluate` (and ``BuildOptions.legacy``) to the legacy objective: the explicit
    ``curves`` and the ``sheet`` (None only while the AC weight is 0). See the module docstring."""

    curves: Sequence[LegacyCurve] = ()
    sheet: LegacySheet | None = None

    def __post_init__(self) -> None:
        curves = tuple(self.curves)
        if not all(isinstance(c, LegacyCurve) for c in curves):
            raise TypeError("the curves of the legacy terms are LegacyCurve objects")
        if self.sheet is not None and not isinstance(self.sheet, LegacySheet):
            raise TypeError("the sheet of the legacy terms is a LegacySheet")
        object.__setattr__(self, "curves", curves)


def check_legacy(p: EvalProfile, legacy: LegacyTerms) -> None:
    """Refuse a profile the legacy terms cannot value: the old objective has no Monk or Iksar armor class bonus."""
    if not isinstance(legacy, LegacyTerms):
        raise TypeError(f"legacy must be a LegacyTerms, not {type(legacy).__name__}")
    if p.monk is not None or p.iksar_ac:
        raise ValueError("the legacy terms carry no Monk or Iksar armor class bonus: the profile must have none")


# ---- evaluate ------------------------------------------------------------------------------

PART_NAMES = (
    "HP", "MANA", "END", "AC", "EVASION", "ATK", "DEX", "HASTE", "REGEN", "RESISTS", "CHA", "WEAPON", "MONK", "IKSAR",
)


@dataclass(frozen=True)
class Breakdown:
    """The value of a kit. ``F`` is the sum of ``parts`` (see the module docstring for each); ``totals`` holds what
    the parts were made from: ``attributes``, ``pools`` (HP, MANA, END), ``counted`` (the classes whose pools count),
    ``end_average``, ``sheet`` (worn_ac, shield_ac, X, Y, capped, monk_bonus, iksar, total), ``haste`` (spell,
    worn_best, worn_counted, counted), ``regen``, ``resists``, ``weight10`` and ``atk``."""

    F: Fraction
    parts: dict[str, Fraction]
    totals: dict[str, Any]


def evaluate(
    profile: Any, kit: Sequence[ItemVec | None], buffs: Mapping[str, Any] | None = None, *, setup: str | None = None,
    haste_assumed: Any = 0, legacy: LegacyTerms | None = None, procs: Any = None,
) -> Breakdown:
    """The value F of ``kit`` under ``profile`` and the buff totals ``buffs`` (the profile's own when None).

    ``setup`` (None, ``"1h-shield"``, ``"2h"``, ``"dw"``, ``"stick"`` or ``"ranged"``) decides which places score weapon damage
    and how (:func:`weapon_index`; ``None`` and ``"stick"`` score none); ``haste_assumed`` is the haste percent the
    weapon index assumes (a constant of the scenario, not the kit's own haste). ``legacy`` (default None) values the
    kit by the legacy objective instead (see the module docstring). ``procs`` (default None: no proc counts, and the result is what it was before procs)
    is the :class:`trioforge.model.procs.ProcTable` of the trio: the hands that swing add the proc they count to their index, **with no haste factor**
    (:mod:`trioforge.model.procs`), to the part ``WEAPON``, and ``totals["procs"]`` then says what each hand counts
    (``{"PRIMARY": entry or None, "SECONDARY": entry or None, "index": the index the procs add, "part": their share of WEAPON}``); the legacy objective counts none.
    Raises ``ValueError`` for a kit of the wrong
    length, an unknown setup, an unknown buff key or a profile that cannot be read, and for legacy terms next to a
    Monk or Iksar bonus or without a sheet while the AC weight is above 0.
    """
    p = compile_profile(profile)
    if legacy is not None:
        check_legacy(p, legacy)
    if len(kit) != len(SLOT_INSTANCES):
        raise ValueError(f"a kit has one entry for each of the {len(SLOT_INSTANCES)} places, not {len(kit)}")
    if setup not in SETUPS:
        raise ValueError(f"unknown setup {setup!r} (use {', '.join(map(repr, SETUPS))})")
    b = p.buff_totals if buffs is None else _buff_view(buffs)
    w = p.weights

    gear: dict[str, int] = {}
    gear_sv = dict.fromkeys(SCHOOLS, 0)
    worn_ac = shield_ac = weight10 = best_haste = 0
    hands: dict[str, ItemVec] = {}
    for place, entry in zip(SLOT_INSTANCES, kit):
        if entry is None:
            continue
        for key, amount in entry.stats.items():
            if key == "AC":
                if place == "SECONDARY" and entry.is_shield:
                    shield_ac += amount
                else:
                    worn_ac += amount
            elif key in ITEM_STATS:
                gear[key] = gear.get(key, 0) + amount
            else:
                hint = " (worn haste is the field ItemVec.haste)" if key == "HASTE" else ""
                raise ValueError(f"item {entry.key}: unknown stat {key!r}{hint}")
        for school, amount in entry.sv.items():
            if school in gear_sv:
                gear_sv[school] += amount
            elif school != "CORRUPTION":  # never scored
                raise ValueError(f"item {entry.key}: unknown resist {school!r}")
        best_haste = max(best_haste, entry.haste)
        weight10 += entry.weight10
        if place in HAND_PLACES or place == _RANGE_PLACE:
            hands[place] = entry

    total = {stat: p.naked[stat] + b.get(stat, 0) + gear.get(stat, 0) for stat in ATTRIBUTES}
    parts = dict.fromkeys(PART_NAMES, _ZERO)

    if legacy is None:
        hp = _hp(p.pools["HP"], total["STA"], gear.get("HP", 0), b.get("HP", 0))
        mana = _mana(p.pools["MANA"], total["WIS"], total["INT"], gear.get("MANA", 0), b.get("MANA", 0), p.bands)
        four = (total["STR"], total["STA"], total["DEX"], total["AGI"])
        end = _end(p.pools["END"], four, gear.get("END", 0), b.get("END", 0))
    else:  # flat pools: the old profile has the class pools in its curves
        flat = {name: gear.get(name, 0) + b.get(name, 0) for name in ("HP", "MANA", "END")}
        hp, mana, end = (_Pool(flat[name], ()) for name in ("HP", "MANA", "END"))
    parts["HP"] = w.get("HP", 0) * hp.total
    parts["MANA"] = w.get("MANA", 0) * mana.total
    parts["END"] = w.get("END", 0) * end.total

    # armor class: the sheet, with the Monk and Iksar bonuses on top of the cap or inside X
    monk = monk_bonus(p.level, weight10, p.monk) if p.monk is not None else 0
    iksar = p.iksar_ac
    inside = (monk if p.placement["monk"] == "inside" else 0) + (iksar if p.placement["iksar"] == "inside" else 0)
    on_top_monk = monk if p.placement["monk"] == "top" else 0
    on_top_iksar = iksar if p.placement["iksar"] == "top" else 0
    swing = p.stance["swing_factor"] if p.stance is not None else 1  # (the Berserker stance: the swing of the hands is faster, after the haste cap)
    agi_share = p.stance["agi_share"] if p.stance is not None else 1  # (and agility counts for nothing in the armor class and the evasion)
    cap, rate = p.softcap
    if legacy is None:
        sheet = sheet_ac_parts(
            worn_ac, shield_ac, p.defense_cap, b.get("AC", 0), min(total["AGI"], STAT_CAP) * agi_share, cap, rate, p.cs_pct,
            p.pe_pct, inside=inside,
        )
        per_sheet_point = w.get("AC", 0) / SHEET_ITEM_MULT
    elif legacy.sheet is not None:
        old = legacy.sheet
        x = old.mult * (worn_ac + shield_ac) + old.nongear
        y = old.cap + shield_ac
        sheet = SheetAC(x, y, min(x, old.ret * x + (1 - old.ret) * y))
        per_sheet_point = w.get("AC", 0) / old.mult
    elif w.get("AC", 0):
        raise ValueError("the legacy terms need a sheet while the AC weight is above 0")
    else:
        sheet = SheetAC(_ZERO, _ZERO, _ZERO)
        per_sheet_point = _ZERO
    parts["AC"] = per_sheet_point * sheet.sheet
    parts["MONK"] = per_sheet_point * on_top_monk
    parts["IKSAR"] = per_sheet_point * on_top_iksar

    if legacy is None:
        parts["EVASION"] = w.get("AC", 0) * AGI_TO_AC * pwl(total["AGI"], (STAT_CAP,), (1, 0)) * agi_share
        atk = STR_TO_ATK * pwl(total["STR"], (STAT_CAP,), (1, 0)) + gear.get("ATK", 0) + b.get("ATK", 0)
        parts["DEX"] = w.get("DEX", 0) * pwl(total["DEX"], (STAT_KNEE, STAT_CAP), (1, DEX_PAST_KNEE, 0))
        parts["CHA"] = w.get("CHA", 0) * pwl(total["CHA"], (STAT_CAP,), (1, 0))
    else:  # the attributes are worth what the explicit curves say (charisma too), not the model's terms
        atk = gear.get("ATK", 0) + b.get("ATK", 0)
        parts["CURVES"] = sum((c.factor * pwl(total[c.attr], c.breaks, c.slopes) for c in legacy.curves), _ZERO)
    parts["ATK"] = w.get("ATK", 0) * atk

    spell = b.get("HASTE", 0) + p.haste_bonus
    worn_counted = min(best_haste, max(_ZERO, p.haste_cap - spell))
    haste_counted = min(spell, p.haste_cap) + worn_counted
    parts["HASTE"] = w.get("HASTE", 0) * haste_counted

    regen: dict[str, dict[str, Any]] = {}
    for key, cap_key in (("HPREG", "HP"), ("MANAREG", "MANA"), ("ENDREG", "END")):
        counted = min(gear.get(key, 0), p.caps["regen"][cap_key]) + b.get(key, 0)
        regen[key] = {"gear": gear.get(key, 0), "buff": b.get(key, 0), "counted": counted}
        parts["REGEN"] += w.get(key, 0) * counted
    resists: dict[str, dict[str, Any]] = {}
    for school in SCHOOLS:
        buff_sv = b["SV"].get(school, 0)
        counted = min(gear_sv[school] + buff_sv, p.caps["resist"])
        resists[school] = {"gear": gear_sv[school], "buff": buff_sv, "counted": counted}
        parts["RESISTS"] += w.get(f"SV_{school}", w.get("SV", 0)) * counted

    swinging: dict[str, ItemVec] = {}
    for place, entry in hands.items():
        if entry.weapon is not None:
            index = weapon_index(entry.weapon, place, setup, haste_assumed, p.dw_factor, p.ranged_factor, p.level)
            if place in HAND_PLACES:
                index *= swing  # (the stance's factor: after the haste, on the hands that swing and not on a bow)
            parts["WEAPON"] += w.get("DMG", 0) * index
            if index and place in HAND_PLACES:
                swinging[place] = entry  # (a hand that swings: a weapon in an Any place, or under the stick or the bow, scores no index and carries no proc)
    proc_totals = None
    if procs is not None and legacy is None:
        lore = getattr(procs, "lore_keys", frozenset())
        worn_lore = frozenset(item.key for item in kit if item is not None and item.key in lore)  # (the Lore items the kit wears anywhere: their copy is not a donor for a hand they are not in)
        main, off = procs.best(swinging.get("PRIMARY"), swinging.get("SECONDARY"), p.dw_factor, worn_lore) if w.get("DMG", 0) else (None, None)
        proc_index = (main.value if main else _ZERO) / procs_module.PER_MINUTE_TO_INDEX + (off.value if off else _ZERO) * p.dw_factor / procs_module.PER_MINUTE_TO_INDEX
        proc_part = w.get("DMG", 0) * proc_index  # (no haste factor: a proc is paced by the minute, and the swing's index keeps its own)
        parts["WEAPON"] += proc_part
        proc_totals = {"PRIMARY": main, "SECONDARY": off, "index": proc_index, "part": proc_part}

    totals = {
        "attributes": total,
        "pools": {"HP": hp.total, "MANA": mana.total, "END": end.total},
        "counted": {"HP": hp.counted, "MANA": mana.counted, "END": end.counted},
        "end_average": end.extra,
        "sheet": {
            "worn_ac": worn_ac, "shield_ac": shield_ac, "X": sheet.x, "Y": sheet.y, "capped": sheet.sheet,
            "monk_bonus": monk, "iksar": iksar, "total": sheet.sheet + on_top_monk + on_top_iksar,
        },
        "haste": {"spell": spell, "worn_best": best_haste, "worn_counted": worn_counted, "counted": haste_counted},
        "regen": regen,
        "resists": resists,
        "weight10": weight10,
        "atk": atk,
    }
    if proc_totals is not None:
        totals["procs"] = proc_totals
    return Breakdown(F=sum(parts.values(), _ZERO), parts=parts, totals=totals)


def evaluate_truthful(
    profile: Any, kit: Sequence[ItemVec | None], buffs: Mapping[str, Any] | None = None, *, setup: str | None = None,
    legacy: LegacyTerms | None = None, procs: Any = None,
) -> Breakdown:
    """:func:`evaluate` with the weapon index taken at the haste the kit itself counts (``totals["haste"]["counted"]``) and
    not at a haste the caller assumes: the value of a kit as it is, the one the solver's truthful optimum (see
    :mod:`trioforge.solver.haste`) is the maximum of. A kit that counts no haste, or that scores no weapon, is valued once. The procs (``procs``, see :func:`evaluate`)
    have no haste factor, so the haste scales the swing's share of ``WEAPON`` and leaves the proc's share as it is."""
    first = evaluate(profile, kit, buffs, setup=setup, haste_assumed=0, legacy=legacy, procs=procs)
    counted = first.totals["haste"]["counted"]
    if counted == 0 or first.parts["WEAPON"] == 0:  # (the index is its value at 0 haste times 1 + haste / 100)
        return first
    if legacy is not None:
        return evaluate(profile, kit, buffs, setup=setup, haste_assumed=counted, legacy=legacy)
    # nothing but the weapon part depends on the assumed haste, and each weapon's index is its value at 0 haste times 1 + haste / 100
    # (the same rational numbers as a second evaluation at the counted haste, to the last bit: tests hold that), so the kit is not evaluated twice
    weapon = first.parts["WEAPON"]
    proc_part = first.totals["procs"]["part"] if "procs" in first.totals else _ZERO
    scaled = (weapon - proc_part) * (1 + fr(counted) / 100) + proc_part
    return Breakdown(F=first.F - weapon + scaled, parts={**first.parts, "WEAPON": scaled}, totals=first.totals)
