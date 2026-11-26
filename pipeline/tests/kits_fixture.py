"""Invented results for the tests of the kit checks: an item table and the folder of a few trios, written in the format of ``trioforge.precompute.shards``.

Every item name here is made up (no page of the wiki has it), except the one name that the checks themselves look for, which the tests take from
``trioforge.checks.kits.WINDSTRIKER`` so that no test spells it. :func:`make_results` writes the folder; a test builds the kits it wants to look at.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from trioforge import rules as rules_module
from trioforge.checks.kits import WINDSTRIKER
from trioforge.checks.results import PLACE_NAMES, parse_trio

REPO = Path(__file__).resolve().parents[2]

PLATE = ("WAR", "PAL", "SHD", "CLR", "BRD")
CHAIN = (*PLATE, "RNG", "ROG", "SHM")
NONCLOTH = (*CHAIN, "BER", "BST", "DRU", "MNK")
CLOTH = ("ENC", "MAG", "NEC", "WIZ")
ROBE_CLASSES = ("DRU", "SHM", *CLOTH)
PIECES = {"CHEST": "Tunic", "LEGS": "Greaves", "ARMS": "Sleeves", "HEAD": "Helm", "HANDS": "Gloves", "FEET": "Boots"}
TOTALS = ("ac", "hp", "mana", "end", "haste", "atk", "fire", "cold", "magic", "poison", "disease", "hpreg", "manareg", "endreg")
DEFAULTS = {
    "key": None, "match_name": None, "classes": ["ALL"], "races": ["ALL"], "deity": None, "lore": False, "stats": {}, "sv": {}, "weapon": None,
    "item_type": None, "item_type_source": None, "aliases": [], "owned_only": False,
}  # fmt: skip
_ids = iter(range(9001, 99999))


def item(
    name: str, slots: Sequence[str], classes: Sequence[str] | None = None, stats: Mapping[str, int] | None = None, *, sv: Mapping[str, int] | None = None,
    weapon: Mapping[str, Any] | None = None, level: str = "wiki", races: Sequence[str] | None = None, deity: Sequence[str] | None = None,
    lore: bool = False, codes: Sequence[str] = (),
) -> dict[str, Any]:
    """One record of the item table, with only the fields that differ from the table's defaults (``codes`` are the reason codes of its evidence)."""
    record: dict[str, Any] = {"id": next(_ids), "name": name, "slots": list(slots), "weight10": 10, "tier_rule": "drop", "evidence": {"level": level}}
    for field, value in (("classes", classes), ("stats", stats), ("sv", sv), ("weapon", weapon), ("races", races), ("deity", deity)):
        if value:
            record[field] = dict(value) if isinstance(value, Mapping) else list(value)
    if lore:
        record["lore"] = True
    if codes:
        record["evidence"]["codes"] = list(codes)
    if level == "hidden":
        record["owned_only"] = True
    return record


def armour(prefix: str, classes: Sequence[str] | None, ac: int, stats: Mapping[str, int] | None = None) -> list[dict[str, Any]]:
    """The six armour pieces of one set: ``<prefix> Tunic`` ... (one name each, the prefix is the stem)."""
    return [item(f"{prefix} {word}", [slot], classes, {"AC": ac, **(stats or {})}) for slot, word in PIECES.items()]


def base_items(sets_per_list: int = 2) -> list[dict[str, Any]]:
    """The invented item table of the tests: armour sets for each class list (two, or ``sets_per_list`` of them where that is more, which the default thresholds of the
    checks need: ten items in each slot), a robe, and one of each kind of item the checks tell apart."""
    records: list[dict[str, Any]] = []
    for prefixes, classes, ac in (
        (("Vlorn", "Quibbit"), PLATE, 30), (("Zarn", "Mepp"), CHAIN, 15), (("Tolk", "Brux"), NONCLOTH, 10), (("Silvane", "Oomph"), CLOTH, 5),
        (("Plainth", "Gruel"), None, 3), (("Fistwrap", "Palmguard"), ("MNK",), 12),
    ):  # fmt: skip
        more = [f"{prefixes[0][:3]}{n:02d}" for n in range(sets_per_list - 2)] if classes != ("MNK",) else []
        for prefix in (*prefixes, *more):
            records += armour(prefix, classes, ac, {"INT": 8} if classes == CLOTH else {"STA": 4})
    records += [
        item("Ombrel Vestment", ["CHEST"], ROBE_CLASSES, {"AC": 4, "INT": 20, "WIS": 20, "MANA": 40}),
        item("Glimmer Idol", ["FACE"], None, {"INT": 10, "WIS": 10, "CHA": 5}, sv={"MAGIC": 5}),
        item("Tidepool Sigil", ["NECK"], None, {"MANAREG": 2}),
        item("Sorrel Staff", ["PRIMARY"], None, {"INT": 12}, weapon={"skill": "2H Blunt", "dmg": 10, "delay": 30, "bonus": None}),
        item("Swiftling Band", ["FINGER"], None, {"WIS": 5, "HASTE": 10}),
        item("Plain Cloak", ["BACK"], None, None, sv={"FIRE": 10}),
        item("Brawn Belt", ["WAIST"], None, {"STR": 20, "AC": 2}),
        item("Bruiser Mitts", ["HANDS"], None, {"STR": 15}),
        item("Ogrebite Torc", ["NECK"], None, {"STR": 30}, races=["OGR"]),
        item("Fenwick Longbow", ["RANGE"], ["RNG"], {"STR": 3}, weapon={"skill": "Archery", "dmg": 12, "delay": 40, "bonus": None}),
        item(WINDSTRIKER, ["RANGE"], ["RNG"], {"STR": 5, "AGI": 5, "DEX": 5, "HP": 50}, weapon={"skill": "Archery", "dmg": 45, "delay": 60, "bonus": None}),
        item("Dimble Charm", ["RANGE"], None, {"INT": 5}),
        item("Thrown Pebble", ["RANGE"], None, {"DEX": 2}, weapon={"skill": "Throwing", "dmg": 3, "delay": 20, "bonus": None}),
        item("Phantom Helm", ["HEAD"], PLATE, {"AC": 99}, level="hidden"),
        item("Zealot Helm", ["HEAD"], PLATE, {"AC": 80}, deity=["Zeta"]),
        item("Disputed Helm", ["HEAD"], PLATE, {"AC": 70}, level="disputed"),
        item("Ogrebite Helm", ["HEAD"], PLATE, {"AC": 60}, races=["OGR"]),
        item("Bardic Greathelm", ["HEAD"], ["BRD"], {"AC": 50}),
        item("Quiver Stub", ["AMMO"], None, {"STR": 50}),
        item("Moonstud", ["EAR"], None, {"STA": 5}),
        item("Handin Test Helm", ["HEAD"], PLATE, {"AC": 90}, codes=["not-for-bis"]),  # a wiki item that the solver leaves out: a quest takes it on hand-in
        item("Mindcrown Helm", ["HEAD"], None, {"AC": 60, "INT": 20, "WIS": 20}),  # armour with nothing but caster stats besides its AC
        item("Strapweave Tunic", ["CHEST"], (*CLOTH, "DRU", "BST", "MNK", "ROG"), {"AC": 6, "STA": 10}),  # cloth, leather and chain wearers: no robe
    ]
    return records


@lru_cache(maxsize=1)
def checkout_rules_version() -> str:
    """The version of the rules of this checkout: the one a folder of results is made with unless a test says another."""
    return rules_module.load().version


def items_document(records: Sequence[Mapping[str, Any]], rules_version: str | None = None) -> dict[str, Any]:
    return {
        "version": 1, "data_release": "data-2026-01-01", "rules_version": checkout_rules_version() if rules_version is None else rules_version, "inputs": "0" * 64,
        "count": len(records), "defaults": dict(DEFAULTS), "items": list(records),
    }  # fmt: skip


def worn(**places: str | None) -> dict[str, str | None]:
    """A kit as place -> item name (``worn(CHEST="Ombrel Vestment")``); the other places stay empty."""
    return {place: name for place, name in places.items()}


def row(role: str, tier: int, kit: Mapping[str, str | None], *, race: str = "HUM", setup: str = "2h", value: float | None = 1000.0, totals: Mapping[str, int] | None = None) -> dict[str, Any]:
    """One scenario of a trio: its race, role, tier and setup, the value, the kit and the totals it shows (the rest of the totals are 0). ``value=None`` says the value
    that the project's evaluator gives the kit (:func:`evaluator_value`), for a test that asks the evaluator about the kit and so needs the shard to agree with it."""
    return {"race": race, "role": role, "tier": tier, "setup": setup, "value": value, "kit": dict(kit), "totals": dict(totals or {})}


def evaluator_parts(records: Sequence[Mapping[str, Any]], slug: str, race: str, role: str, tier: int, kit: Mapping[str, str | None]) -> tuple[Any, list[Any], dict[str, Any]]:
    """What ``trioforge.model.formulas.evaluate_truthful`` takes for a kit: the compiled profile of the trio, race and role, the 22 items at the tier (None for an empty place),
    and the totals of the own buffs that are always on. Only model code is used (the item records become catalog items by ``export.browser.item_to_catalog``)."""
    from trioforge.data.jsonio import load_strict
    from trioforge.export.browser import item_to_catalog
    from trioforge.model import formulas as fm
    from trioforge.model import tables as tables_module
    from trioforge.model.buffs import buffsets
    from trioforge.model.items import at_tier
    from trioforge.model.profile import eval_buffs, make_profile

    tables = tables_module.load(REPO)
    codes = parse_trio(slug)
    spells = load_strict(REPO / "derived" / "client" / "spells-l50.json")
    buffset = buffsets(codes, 50, spells, tables.rules, ("own",))["own"]
    by_name = {record["name"]: item_to_catalog(record, DEFAULTS) for record in records}
    vecs = [None if not kit.get(place) else at_tier(by_name[kit[place]], tier, tables.rules) for place in PLACE_NAMES]
    profile = make_profile(race, codes, 50, role, buffset, None, tables, evidence="wiki", items=[])
    return fm.compile_profile(profile.eval_profile), vecs, eval_buffs(buffset.totals(()))


def evaluator_value(records: Sequence[Mapping[str, Any]], slug: str, race: str, role: str, tier: int, setup: str, kit: Mapping[str, str | None]) -> float:
    """The value of a kit by ``evaluate_truthful`` (see :func:`evaluator_parts`), to two decimals as a shard writes it."""
    from trioforge.model import formulas as fm

    compiled, vecs, totals = evaluator_parts(records, slug, race, role, tier, kit)
    return round(float(fm.evaluate_truthful(compiled, vecs, totals, setup=setup).F), 2)


def make_results(
    root: Path, records: Sequence[Mapping[str, Any]], trios: Mapping[str, Sequence[dict[str, Any]]], *, race: str = "HUM", softcap: int = 400, rules_version: str | None = None,
    trio_rules_version: str | None = None,
) -> Path:
    """Write a results folder under ``root``: ``items.json`` and, for each trio slug of ``trios`` (with its scenario rows from :func:`row`), ``defaults.json`` (the default
    race ``race``, the view at the wiki level) and ``wiki-own.json`` (the shard: the items worn, the kits, the totals and the scenarios, in the format of
    ``trioforge.precompute.shards``). The setups that a role lists are those its rows use, in the order they first appear. Every file of a trio records the rules version, as the
    writers of them do: that of ``items.json`` (``rules_version``, the checkout's by default) unless ``trio_rules_version`` says another."""
    root.mkdir(parents=True, exist_ok=True)
    document = items_document(records, rules_version)
    (root / "items.json").write_text(json.dumps(document), encoding="utf-8")
    stamped = document["rules_version"] if trio_rules_version is None else trio_rules_version
    keys = {record["name"]: f"w{record['id']}" for record in records}
    by_name = {record["name"]: record for record in records}
    for slug, rows in trios.items():
        folder = root / slug
        folder.mkdir()
        worn_names = sorted({name for r in rows for name in r["kit"].values() if name})
        shard_items = [[keys[name], name, by_name[name]["slots"], "drop", 4, None, "wiki", None] for name in worn_names]
        index = {name: n for n, name in enumerate(worn_names)}
        kits: list[list[int]] = []
        vectors: list[list[int]] = []
        roles: list[str] = []
        setups: dict[str, list[str]] = {}
        scenarios = []
        for r in rows:
            if r["role"] not in roles:
                roles.append(r["role"])
            if r["setup"] not in setups.setdefault(r["role"], []):
                setups[r["role"]].append(r["setup"])
            kit = [-1 if not r["kit"].get(place) else index[r["kit"][place]] for place in PLACE_NAMES]
            vector = [r["totals"].get(name, 0) for name in TOTALS]
            kits.append(kit)
            vectors.append(vector)
            value = r["value"] if r["value"] is not None else evaluator_value(records, slug, r["race"], r["role"], r["tier"], r["setup"], r["kit"])
            scenarios.append([r["race"], r["role"], r["tier"], r["setup"], len(kits) - 1, value, 0.0, len(vectors) - 1, 0, 0])
        shard = {
            "version": 1, "trio": slug, "classes": [c.upper() for c in slug.split("-")], "level": 50, "rules_version": stamped, "evidence": "wiki", "buffs": "own", "roles": roles, "setups": setups,
            "tiers": sorted({r["tier"] for r in rows}), "caps": {"sheet_softcap": softcap, "haste": 75, "resist": 200}, "places": list(PLACE_NAMES),
            "items_keys": ["key", "name", "slots", "tier_rule", "arrival", "source", "evidence", "deity"], "items": shard_items, "kits": kits,
            "totals_keys": list(TOTALS), "totals": vectors, "buff_sets": [[]], "scenarios": scenarios,
        }  # fmt: skip
        (folder / "wiki-own.json").write_text(json.dumps(shard), encoding="utf-8")
        defaults = {"version": 1, "trio": slug, "rules_version": stamped, "view": {"role": "tank", "tier": 4, "evidence": "wiki", "buffs": "own"}, "race": race, "setup": "2h"}
        (folder / "defaults.json").write_text(json.dumps(defaults), encoding="utf-8")
    return root
