"""The spells: the file, the category of a spell, the focus limits and what a focus touches.

The spells come from ``derived/client/effect-spells.json`` (:mod:`trioforge.effects.derive`), the client's own spell text. A spell is a dict::

    {"id", "name", "cast_ms", "mana", "duration_ticks", "permanent", "beneficial", "resist", "target", "skill", "levels": {class: level},
     "effects": [{"slot", "spa", "base", "limit", "formula", "max", "value"}]}

``value`` is the effect's number for a caster of the level the record was made at (:func:`trioforge.sources.client_spells.formula_value`), ``None`` for a limit
or a stacking command. ``beneficial`` is 0 detrimental, 1 beneficial, 2 beneficial to the group only; ``target`` is the client's target type (5 single, 6 self,
13 lifetap, 14 pet ...).

The focus rules follow EQEmu and are not verified in EQL. A focus limited to a maximum spell level touches a spell above it at a loss of the limit's percent for
each level above (:func:`focus_weight`), not at all when the limit has no percent.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from trioforge.effects.judgment import Judgment
from trioforge.sources import client_spells as cs

__all__ = [
    "DEFAULT_PATH",
    "FOCUS_KINDS",
    "SpellBook",
    "class_profile",
    "classify_focus",
    "classify_spell",
    "focus_applies",
    "focus_type",
    "focus_weight",
    "has_haste_buff",
    "limit_text",
    "parse_family",
    "pick_spell",
    "spell_from_row",
]

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "derived" / "client" / "effect-spells.json"
LIMIT_SPA = cs.LIMIT_SPA
STACKING_SPA = cs.STACKING_SPA
SELF = 6  # the target type of a spell cast on its caster

FOCUS_KINDS = {
    124: "improved_damage", 125: "improved_healing", 127: "spell_haste", 128: "extended_duration", 129: "extended_range",
    131: "reagent_conservation", 132: "mana_preservation", 167: "pet_power", 413: "instrument_mod", 126: "resist_reduction", 130: "spell_hate",
}  # fmt: skip

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}


# ---- names ---------------------------------------------------------------------------------------------------------


def parse_family(name: str) -> tuple[str, int | None]:
    """``("Spell Haste II")`` -> ``("Spell Haste", 2)``; a name without a trailing roman numeral keeps the tier ``None``."""
    head, _, tail = name.rpartition(" ")
    if head and tail in _ROMAN:
        return head, _ROMAN[tail]
    return name, None


# ---- the spell file ------------------------------------------------------------------------------------------------


def spell_from_row(row: dict[str, Any], level: int) -> dict[str, Any]:
    """A spell record from a row of the derived file, with its effect values and duration worked out for a caster of ``level``."""
    effects = []
    for slot, spa, base, limit, formula, maximum in row["fx"]:
        value = None
        if spa not in LIMIT_SPA and spa not in STACKING_SPA:
            value, _ = cs.formula_value(base, formula, maximum, level)
        effects.append({"slot": slot, "spa": spa, "base": base, "limit": limit, "formula": formula, "max": maximum, "value": value})
    ticks, permanent = cs.duration_ticks(row["dur"][0], row["dur"][1], level)
    return {
        "id": row["id"], "name": row["name"], "cast_ms": row["cast_ms"], "mana": row["mana"],
        "duration_ticks": 0 if permanent else (ticks or 0), "permanent": permanent, "beneficial": row["ben"], "resist": row["res"],
        "target": row["tgt"], "skill": row.get("sk", 0), "levels": dict(row["lv"]), "effects": effects,
    }  # fmt: skip


class SpellBook:
    """The rows of the derived spell file, found by name, and the spells every class gets up to the cap."""

    def __init__(self, rows: list[dict[str, Any]], cap: int, source_sha256: str | None = None) -> None:
        self.cap = cap
        self.rows = rows
        self.source_sha256 = source_sha256  # the SHA-256 of the client's spell text the rows were read from
        self.by_name: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if row["name"]:
                self.by_name.setdefault(row["name"], []).append(row)
        self._class_spells: list[dict[str, Any]] | None = None

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PATH) -> SpellBook:
        """Read the derived file (``ValueError`` if it is not one)."""
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("spells"), list) or type(document.get("cap")) is not int:
            raise ValueError(f"{Path(path).name} is not a derived spell file for the effects layer")
        inputs = (document.get("provenance") or {}).get("inputs") or [{}]
        return cls(document["spells"], document["cap"], inputs[0].get("sha256"))

    def class_spells(self) -> list[dict[str, Any]]:
        """Every spell some class gets at the cap or below, as records for a caster of the cap."""
        if self._class_spells is None:
            self._class_spells = [
                spell_from_row(row, self.cap) for row in self.rows if row["lv"] and min(row["lv"].values()) <= self.cap
            ]
        return self._class_spells


# ---- the category of a spell -------------------------------------------------------------------------------------------


def _value(effect: dict[str, Any]) -> float:
    value = effect.get("value")
    return effect["base"] if value is None else value


def _is_instant(spell: dict[str, Any]) -> bool:
    return spell["duration_ticks"] == 0 and not spell["permanent"]


def _over_time(per_tick: float, spell: dict[str, Any]) -> tuple[float, str]:
    """Total over the spell's duration (a permanent spell keeps its per-tick number)."""
    if spell["permanent"] or not spell["duration_ticks"]:
        return per_tick, "hp_per_tick"
    return per_tick * spell["duration_ticks"], "hp_total"


def classify_spell(spell: dict[str, Any], j: Judgment) -> dict[str, Any]:
    """The category of a spell from its effect ids, with its magnitude and unit (judgment: the priority order).

    A spell on its caster that spends hit points to give mana (Cannibalize) is ``mana``, not ``damage``. A dispel's magnitude is the number of buffs it strips."""
    effects = [e for e in spell["effects"] if e["spa"] not in LIMIT_SPA and e["spa"] not in STACKING_SPA and e["spa"] != 254]
    spas = {e["spa"] for e in effects}
    beneficial = spell["beneficial"] in (1, 2)
    instant = _is_instant(spell)

    def first(*ids: int) -> dict[str, Any] | None:
        return next((e for e in effects if e["spa"] in ids), None)

    def out(category: str, magnitude: float | None = None, unit: str | None = None) -> dict[str, Any]:
        return {"category": category, "magnitude": magnitude, "unit": unit}

    if 81 in spas:
        return out("resurrect", abs(_value(first(81))), "exp_pct")
    if spas & {26, 83, 88, 104, 145}:
        return out("teleport")
    if spas & {33, 71, 152}:
        return out("summon_pet")
    if 32 in spas:
        return out("summon_item")
    hp = [e for e in effects if e["spa"] in (0, 79, 100)]
    if not instant and spas & {1, 2, 4, 5, 6, 7, 8, 9, 69, 55, 59, 46, 47, 48, 49, 50}:
        hp = [e for e in hp if e["spa"] != 79]  # a lasting buff that also adds current HP (max HP plus HP) is a buff
    if hp:
        e = max(hp, key=lambda x: abs(_value(x)))
        v = _value(e)
        once = instant or e["spa"] == 79  # SPA 79 is a one-time change even inside a lasting spell (a rune plus a heal)
        mana = first(15)
        if v < 0 and spell["target"] == SELF and mana is not None and _value(mana) > 0:
            return out("mana", abs(_value(mana)), "mana")  # hit points spent for mana: the gain is mana
        if v < 0:
            if spell["target"] == 13:
                return out("lifetap", abs(v), "hp")
            if once:
                return out("damage", abs(v), "hp")
            return out("dot", *_over_time(abs(v), spell))
        if v > 0:
            if once:
                return out("heal", v, "hp")
            return out("heal_over_time", *_over_time(v, spell))
    if 192 in spas:
        return out("hate", abs(_value(first(192))), "hate")
    e = first(11)
    if e:
        b = _value(e)
        return out("haste" if (b > 100 and beneficial) else "slow", abs(b - 100), "pct")
    e = first(3)
    if e:
        b = _value(e)
        return out("run_speed" if b > 0 else "snare", abs(b), "pct")
    if 57 in spas:
        return out("levitate")
    if spas & {12, 28, 29}:
        return out("invisibility")
    if 13 in spas:
        return out("see_invisible")
    if spas & {65, 66}:
        return out("vision")
    if 14 in spas:
        return out("water_breathing")
    if spas & {21, 31, 22, 23, 99, 20, 18, 64, 30}:
        return out("crowd_control")
    if 27 in spas:
        return out("dispel", sum(1 for e in effects if e["spa"] == 27), "buffs")
    if 113 in spas:
        return out("mount")
    if 74 in spas:
        return out("feign_death")
    if 25 in spas:
        return out("bind")
    e = first(15)
    if e:
        v = _value(e)
        return out("mana" if v > 0 else "debuff", abs(v), "mana")
    if 97 in spas and beneficial:
        return out("buff_stats", abs(_value(first(97))), "maxMana")
    if spas & {35, 36} and beneficial:
        return out("cure")
    if 58 in spas:
        return out("illusion")
    if spas & {227, 220, 226}:
        e = first(220)
        return out("melee_skill", abs(_value(e)) if e else None, "skill_dmg")
    if spas & {55, 59, 40}:
        return out("buff_protection")
    stat = spas & {1, 2, 4, 5, 6, 7, 8, 9, 69, 189}
    res = spas & {46, 47, 48, 49, 50, 111}
    if stat:
        total = sum(abs(_value(e)) for e in effects if e["spa"] in stat)
        return out("buff_stats" if beneficial else "debuff", total, "stat_points")
    if res:
        total = sum(abs(_value(e)) for e in effects if e["spa"] in res)
        return out("buff_resist" if beneficial else "debuff", total, "resist_points")
    if spas & {85, 323, 367}:
        return out("proc_buff")
    if spas & {35, 36, 120}:
        return out("debuff")
    if spas & j.one_off_spas:
        return out("utility_other")
    return out("other")


# ---- focus -----------------------------------------------------------------------------------------------------------


def classify_focus(spell: dict[str, Any]) -> dict[str, Any] | None:
    """Focus data of a spell, or ``None`` when it has no focus effect id. The limits are collected from the limit effect ids."""
    kinds = [e for e in spell["effects"] if e["spa"] in FOCUS_KINDS]
    if not kinds:
        return None
    e = kinds[0]
    lim: dict[str, Any] = {
        "max_level": None, "level_penalty": None, "min_level": None, "resist": {"include": [], "exclude": []},
        "target": {"include": [], "exclude": []}, "effect": {"include": [], "exclude": []}, "spell_type": None,
        "spell_ids": {"include": [], "exclude": []}, "min_duration": None, "instant": None, "min_cast_ms": None, "combat": None,
        "skill": None,
    }  # fmt: skip

    def split(key: str, base: int) -> None:
        (lim[key]["exclude"] if base < 0 else lim[key]["include"]).append(abs(base))

    for x in spell["effects"]:
        s, b = x["spa"], x["base"]
        if s == 134:
            lim["max_level"], lim["level_penalty"] = b, x["limit"]
        elif s == 142:
            lim["min_level"] = b
        elif s == 135:
            split("resist", b)
        elif s == 136:
            split("target", b)
        elif s == 137:
            split("effect", b)
        elif s == 138:
            lim["spell_type"] = b
        elif s == 139:
            split("spell_ids", b)
        elif s == 140:
            lim["min_duration"] = b
        elif s == 141:
            lim["instant"] = b
        elif s == 143:
            lim["min_cast_ms"] = b
        elif s == 311:
            lim["combat"] = b
        elif s == 414:
            lim["skill"] = b
    lo = e["base"]
    hi = e["limit"] if e["limit"] else e["base"]
    return {"kind": FOCUS_KINDS[e["spa"]], "spa": e["spa"], "min_pct": lo, "max_pct": hi, "limits": lim}


def focus_weight(lim: dict[str, Any], spell: dict[str, Any], level: int) -> float:
    """How much of a focus a spell cast at class level ``level`` gets: 0 when a limit rules the spell out, else 1 minus the loss for a level above the focus's maximum.

    The loss is the limit's percent for each level above the maximum, ``max(0, 1 - percent x (level - maximum))``: Spell Haste II (spells to level 44, 5 percent a
    level) gives a level-49 spell 75 percent. A maximum level with no percent rules every higher spell out. EQEmu rules, not verified in EQL."""
    factor = 1.0
    if lim["max_level"] is not None and level > lim["max_level"]:
        percent = lim["level_penalty"] or 0
        if percent <= 0:
            return 0.0
        factor = max(0.0, 1 - percent / 100 * (level - lim["max_level"]))
        if factor <= 0:
            return 0.0
    if lim["min_level"] is not None and level < lim["min_level"]:
        return 0.0
    if lim["skill"] is not None and spell.get("skill") != lim["skill"]:
        return 0.0  # an instrument focus covers the songs of its own instrument skill and no other spell
    for key, value in (("resist", spell["resist"]), ("target", spell["target"])):
        inc, exc = lim[key]["include"], lim[key]["exclude"]
        if value in exc or (inc and value not in inc):
            return 0.0
    spas = {e["spa"] for e in spell["effects"]}
    inc, exc = lim["effect"]["include"], lim["effect"]["exclude"]
    if spas & set(exc) or (inc and not spas & set(inc)):
        return 0.0
    inc, exc = lim["spell_ids"]["include"], lim["spell_ids"]["exclude"]
    if spell["id"] in exc or (inc and spell["id"] not in inc):
        return 0.0
    beneficial = spell["beneficial"] in (1, 2)
    if lim["spell_type"] == 0 and beneficial:
        return 0.0
    if lim["spell_type"] == 1 and not beneficial:
        return 0.0
    ticks = 10**6 if spell["permanent"] else spell["duration_ticks"]
    if lim["min_duration"] is not None and ticks < lim["min_duration"]:
        return 0.0
    instant = _is_instant(spell)
    if lim["instant"] == 1 and not instant:
        return 0.0
    if lim["instant"] == 0 and instant:
        return 0.0
    if lim["min_cast_ms"] is not None and spell["cast_ms"] < lim["min_cast_ms"]:
        return 0.0
    return factor


def focus_applies(lim: dict[str, Any], spell: dict[str, Any], level: int) -> bool:
    """Whether a focus touches a spell at all (its weight is above 0)."""
    return focus_weight(lim, spell, level) > 0


def focus_type(focus: dict[str, Any]) -> str:
    """The stacking type of a focus: its effect id. Pet-power foci are told apart by element and instrument modifiers by skill (they have separate limits, so
    one cannot replace another) - judgment."""
    kind = str(focus["spa"])
    if focus["kind"] == "pet_power":
        kind += ":" + ",".join(map(str, focus["limits"]["resist"]["include"]))
    elif focus["kind"] == "instrument_mod":
        kind += ":" + str(focus["limits"]["skill"])
    return kind


_TARGET = {2: "area", 4: "area around you", 8: "area", 13: "life tap", 17: "area", 18: "area"}
_SCHOOL = {1: "magic", 2: "fire", 3: "cold", 4: "poison", 5: "disease"}
_EFFECT = {0: "a hit-point effect", 33: "a pet summon", 71: "an animate dead", 32: "an item summon"}


def limit_text(focus: dict[str, Any]) -> str:
    """The limits of a focus in plain words ("detrimental, instant spells of single targets, up to spell level 44 (weaker above)")."""
    lim = focus["limits"]
    parts: list[str] = []
    if lim["spell_type"] == 0:
        parts.append("detrimental")
    elif lim["spell_type"] == 1:
        parts.append("beneficial")
    if lim["instant"] == 1:
        parts.append("instant")
    elif lim["instant"] == 0:
        parts.append("lasting")
    text = ", ".join(parts + ["spells"]) if parts else "all spells"
    if len(parts) == 2:
        text = f"{parts[0]} and {parts[1]} spells"
    extra: list[str] = []
    if lim["min_duration"] is not None:
        extra.append(f"lasting at least {lim['min_duration'] * 6} s")
    if lim["min_cast_ms"] is not None:
        extra.append(f"with a cast time of {lim['min_cast_ms'] / 1000:g} s or more")
    if lim["effect"]["include"]:
        extra.append("with " + " or ".join(_EFFECT.get(x, f"effect {x}") for x in lim["effect"]["include"]))
    if lim["effect"]["exclude"]:
        extra.append("without " + " or ".join(_EFFECT.get(x, f"effect {x}") for x in lim["effect"]["exclude"]))
    if lim["target"]["exclude"]:
        extra.append("not " + " or ".join(sorted({_TARGET.get(x, f"target {x}") for x in lim["target"]["exclude"]})))
    if lim["target"]["include"]:
        extra.append("only " + " or ".join(sorted({_TARGET.get(x, f"target {x}") for x in lim["target"]["include"]})))
    if lim["resist"]["include"]:
        extra.append("of " + " or ".join(_SCHOOL.get(x, f"school {x}") for x in lim["resist"]["include"]))
    if lim["spell_ids"]["exclude"] or lim["spell_ids"]["include"]:
        extra.append("some spells excepted" if lim["spell_ids"]["exclude"] else "named spells only")
    if lim["min_level"] is not None:
        extra.append(f"from spell level {lim['min_level']}")
    if lim["max_level"] is not None:
        extra.append(f"up to spell level {lim['max_level']}" + (" (weaker above)" if lim["level_penalty"] else ""))
    return " ".join([text, ", ".join(extra)]).strip() if extra else text


# ---- choosing among spells of one name -----------------------------------------------------------------------------------


def _max_hp(spell: dict[str, Any]) -> float:
    return max((abs(_value(e)) for e in spell["effects"] if e["spa"] in (0, 79, 100)), default=0)


def _signature(spell: dict[str, Any]) -> tuple[Any, ...]:
    return tuple((e["spa"], e["base"], e["limit"], e["formula"], e["max"]) for e in spell["effects"])


def pick_spell(spells: list[dict[str, Any]], kind: str) -> tuple[dict[str, Any], bool]:
    """Choose among same-named spells: the lowest id (the classic spell), after preferring the type that fits the effect kind (a proc is an offensive spell, a
    worn effect a permanent one). Sanity: NPC-scale damage (over 20,000) and ids from 20,000 up are not trusted for the proc preference.
    Returns ``(spell, ambiguous)``."""
    ordered = sorted(spells, key=lambda x: x["id"])
    pool = ordered
    if kind == "proc":
        detrimental = [x for x in ordered if x["beneficial"] == 0 and x["id"] < 20000 and _max_hp(x) <= 20000]
        pool = detrimental or ordered
    elif kind == "worn":
        permanent = [x for x in ordered if x["permanent"] or x["duration_ticks"] >= 3000]
        pool = permanent or ordered
    return pool[0], len({_signature(x) for x in ordered}) > 1


# ---- what a class casts --------------------------------------------------------------------------------------------------


def has_haste_buff(spells: list[dict[str, Any]], cls: str, j: Judgment) -> bool:
    """Does the class have a haste buff for a player (at least ``min_pct`` percent, not pet-only) up to the cap?"""
    for spell in spells:
        level = spell["levels"].get(cls)
        if level is None or not 0 < level <= j.cap or spell["target"] == 14 or spell["beneficial"] not in (1, 2):
            continue
        c = classify_spell(spell, j)
        if c["category"] == "haste" and (c["magnitude"] or 0) >= j.haste_min_pct:
            return True
    return False


def class_profile(spells: list[dict[str, Any]], cls: str, j: Judgment) -> dict[str, Any]:
    """Counts of what ``cls`` casts up to the cap, by category (all levels and the late ones)."""
    by: Counter[str] = Counter()
    by_late: Counter[str] = Counter()
    for spell in spells:
        level = spell["levels"].get(cls)
        if level is None or not 0 < level <= j.cap:
            continue
        category = classify_spell(spell, j)["category"]
        by[category] += 1
        if level >= j.late:
            by_late[category] += 1
    return {
        "total": sum(by.values()), "by_category": dict(by), "late_total": sum(by_late.values()), "late_by_category": dict(by_late),
    }  # fmt: skip


_NUMBER_SUFFIX = re.compile(r" \d+$")


def strip_number(family: str) -> str:
    """``"Wind Resonance 14"`` -> ``"Wind Resonance"``: the number of an instrument modifier is its size, not a tier."""
    return _NUMBER_SUFFIX.sub("", family)
