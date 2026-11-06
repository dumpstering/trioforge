"""The effects of the catalog's items, as records: each distinct effect with its spell, its category and the items that carry it (its donors).

The wiki lists an effect on an item as text ("Effect: Firestrike (Clicky, Must Equip, Casting Time: Instant, Cooldown: 120 seconds) at Level 49"). One record is
made for each distinct (kind, name, cast level, proc rate, click mode); its spell is found by name in the client's spell text. What differs from item to item (the
required level, the cooldown and the cast time in the text of each copy) is kept on the donor, not on the record.

The pool is the wiki-level items of the public catalog; an item with no slot of a place of a kit (a potion, a poison, a scroll, a mount in the ammo slot) is kept as a
donor row but marked not eligible, since it cannot be worn: the item table of the release holds the same items and no others (``grid.WEARABLE_SLOTS``).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from trioforge.effects import spells as sp
from trioforge.effects.derive import ALIASES
from trioforge.effects.judgment import Judgment
from trioforge.precompute.grid import WEARABLE_SLOTS  # (the constant that decides which items the item table of the release has)

__all__ = ["access_cost", "build_effects", "click_mode", "kind_of", "parse_raw", "usable_by"]

OFFENSIVE = frozenset({"damage", "lifetap", "dot", "crowd_control", "debuff", "slow", "snare"})
WEAPON_SLOTS = frozenset({"PRIMARY", "SECONDARY", "RANGE"})


def parse_raw(raw: str) -> dict[str, Any]:
    """Numbers out of the wiki's effect text: cast level, required level, cooldown, proc rate, cast time."""

    def number(pattern: str, cast: Any = int) -> Any:
        m = re.search(pattern, raw, re.I)
        return cast(m.group(1)) if m else None

    cast_time = None
    m = re.search(r"\bCast(?:ing)? Time: ([0-9.]+|Instant)", raw, re.I)  # (not "Recast Time")
    if m:
        cast_time = 0.0 if m.group(1).lower() == "instant" else float(m.group(1))
    return {
        "cast_level": number(r"\b(?:at|as) Level (\d+)"),
        "req_level": number(r"(?:req\.? ?level|Required Level:?)\s*(\d+)"),
        "cooldown_s": number(r"Cooldown: (\d+) seconds"),
        "rate_pct": number(r"Rate ([+-]\d+)%"),  # (signed: a reduced proc rate, "Rate -75%", is a rate of -75)
        "cast_time_s": cast_time,
        "must_equip": "Must Equip" in raw,
        "any_slot": "Any Slot" in raw,
    }


def click_mode(raw: str) -> tuple[str, bool]:
    """``("carry" | "exalt", flagged)``. "Any Slot" clicks work from the bags without being equipped, so they need no exaltation slot (carry the item). "Must Equip"
    clicks compete for click slots. "Can Equip" or no wording is treated as must-equip and flagged."""
    if "Any Slot" in raw:
        return "carry", False
    if "Must Equip" in raw:
        return "exalt", False
    return "exalt", True


def access_cost(item: dict[str, Any], j: Judgment) -> int:
    """How hard an item is to get: 1 vendor, 2 quest or crafted, 3 drop (group zone), 4 drop in a raid zone, 9 no known source (judgment)."""
    s = item["sources"]
    cost = j.access_cost
    best = cost["none"]
    if s.get("sold_by"):
        best = min(best, cost["vendor"])
    if s.get("quests"):
        best = min(best, cost["quest"])
    if s.get("crafted"):
        best = min(best, cost["crafted"])
    for drop in s.get("drops", []):
        zone = drop["zone"]
        best = min(best, cost["raid"] if (zone in j.raid_zones or zone.startswith("Plane of")) else cost["drop"])
    return best


def usable_by(item: dict[str, Any], classes: Any) -> list[str]:
    """The classes of ``classes`` that can use the item."""
    allowed = item["classes"]
    return [c for c in classes if "ALL" in allowed or c in allowed]


def kind_of(effect: dict[str, Any]) -> str:
    """The kind an effect is listed under: its own, an inferred ``proc`` for an unlabeled offensive spell on a weapon, ``click`` for ``other``."""
    return effect.get("kind_inferred") or ("click" if effect["kind"] == "other" else effect["kind"])


def _donor(item: dict[str, Any], raw: str, j: Judgment, flagged: bool = False) -> dict[str, Any]:
    info = parse_raw(raw)
    weapon = item.get("weapon") or {}
    skill = weapon.get("skill") or ""
    rule = item.get("tier_rule")
    slots = list(item.get("slots") or [])  # (an item with no slot list is an item with no slot)
    return {
        "key": item["key"], "name": item["name"], "classes": item["classes"], "slots": slots, "two_hand": skill.startswith("2H"),
        "access": access_cost(item, j), "eligible": bool(WEARABLE_SLOTS & set(slots)), "tier_rule": rule, "arrival": 4 if rule == "drop" else (0 if rule == "fixed0" else None),
        "req_level": info["req_level"], "cooldown_s": info["cooldown_s"], "cast_time_s": info["cast_time_s"],
        "instant": info["cast_time_s"] == 0, "mode_flag": flagged,
    }  # fmt: skip


def build_effects(pool: list[dict[str, Any]], book: sp.SpellBook, j: Judgment) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """One record per distinct (kind, effect name, cast level, rate, click mode) of the items of ``pool``, with its classification and its donors, and the list of
    effect names with no spell.

    A record has ``id`` (``e000`` ...), ``kind`` (``focus``, ``click``, ``worn``, ``proc`` or ``other``), ``name``, ``cast_level``, ``rate_pct``, ``mode``
    (``carry`` or ``exalt``, for a click; only the mode keys a record: whether a copy's wording is unclear is a mark on the donor, ``mode_flag``, and the record is unverified
    for ``equip`` when any donor has it), ``resolved``, ``candidates``, ``ambiguous``, ``spell_id``, the category, magnitude and unit of the spell, ``focus`` (a focus's
    family, tier, kind and limits), ``kind_inferred``, ``unverified`` (the reasons the row is unverified) and ``items`` (its donors, each with the required level, cooldown
    and cast time of its own copy of the text).

    An effect with no trigger wording (kind ``other``) whose spell is offensive is a proc on a weapon and a click anywhere else: the copies are told apart one by one, and the
    two kinds are two records (the proc one has ``kind_inferred`` ``proc``), so a record never mixes kinds."""
    groups: dict[tuple[Any, ...], dict[str, Any]] = defaultdict(dict)
    for item in pool:
        for effect in item["effects"]:
            info = parse_raw(effect["raw"])
            mode, flagged = click_mode(effect["raw"]) if effect["kind"] in ("click", "other") else (None, False)
            key = (effect["kind"], effect["name"], info["cast_level"], info["rate_pct"], mode)
            groups[key][item["key"]] = _donor(item, effect["raw"], j, flagged)
    made: list[dict[str, Any]] = []
    misses: list[dict[str, str]] = []
    for key in sorted(groups, key=lambda k: (k[0], k[1], k[2] or 0, k[3] or 0, str(k[4]))):
        kind, name, cast_level, rate, mode = key
        level = min(cast_level or j.cap, j.cap)
        rows = book.by_name.get(ALIASES.get(name, name), [])
        record: dict[str, Any] = {
            "kind": kind, "name": name, "cast_level": cast_level, "rate_pct": rate, "resolved": bool(rows), "candidates": len(rows), "ambiguous": False,
        }  # fmt: skip
        if mode:
            record["mode"] = mode
        donors = list(groups[key].values())
        unverified: list[str] = []
        if not rows:
            misses.append({"kind": kind, "name": name})
            record.update({"category": "unresolved", "magnitude": None, "unit": None})
        else:
            spells = [sp.spell_from_row(row, level) for row in rows]
            spell, ambiguous = sp.pick_spell(spells, kind)
            record["ambiguous"] = ambiguous
            record["spell_id"] = spell["id"]
            record["spell"] = {k: spell[k] for k in ("cast_ms", "mana", "duration_ticks", "permanent", "beneficial", "resist", "target")}
            record.update(sp.classify_spell(spell, j))
            focus = sp.classify_focus(spell) if kind in ("focus", "other", "worn") else None
            if focus:
                family, tier = sp.parse_family(name)
                if tier is None:
                    family = sp.strip_number(family)  # "Wind Resonance 14": the number is the modifier, not a tier
                record["focus"] = {"family": family, "tier": tier, **focus}
                record["category"] = "focus_" + focus["kind"]
                record["magnitude"] = (focus["min_pct"] + focus["max_pct"]) / 2
                record["unit"] = "pct"
            elif kind == "focus":
                record["note"] = "labelled focus but has no focus effect id"
            record["_spell"] = spell
            if ambiguous:
                unverified.append("ambiguous")
        if name in j.unverified_names:
            unverified.append("description")
        parts: list[tuple[dict[str, Any], list[dict[str, Any]], list[str]]] = []
        if kind == "other" and record.get("category") in OFFENSIVE:
            on_weapon = [d for d in donors if set(d["slots"]) & WEAPON_SLOTS]
            elsewhere = [d for d in donors if not set(d["slots"]) & WEAPON_SLOTS]
            if elsewhere:
                parts.append((dict(record), elsewhere, list(unverified)))
            if on_weapon:  # no trigger wording, offensive spell on a weapon: players list it as a proc
                proc = {k: v for k, v in record.items() if k != "mode"}
                proc["kind_inferred"] = "proc"
                parts.append((proc, on_weapon, [*unverified, "inferred"]))
        else:
            parts.append((record, donors, unverified))
        for part, part_donors, reasons in parts:
            part["items"] = part_donors
            if part.get("kind_inferred") is None and any(d["mode_flag"] for d in part_donors):
                reasons.append("equip")
                part["mode_flag"] = True
            part["unverified"] = sorted(set(reasons), key=["ambiguous", "equip", "inferred", "description"].index)
            made.append(part)
    for number, part in enumerate(made):
        part["id"] = f"e{number:03d}"
    return [{"id": part.pop("id"), **part} for part in made], misses
