"""The plan fixtures: what the browser's re-match of the exalt plan (``static/ui/exalt-plan.js``) is held to.

``python -m trioforge.effects.fixtures [--out fixtures/effects/plan-parity.json] [--check]`` makes ``fixtures/effects/plan-parity.json`` from the public catalog and the
shipped spell text: for a sample of trios and every role they are offered, several kits of real catalog items (seeded, so the file is the same every time) at several tiers,
each with the plan that :func:`trioforge.effects.plan.plan_kit` makes of it. The JavaScript test (``tests-js/exalt-plan.test.mjs``) runs the browser's matcher on every case and
requires the same rows, in the same order, and the same no-room list.

The file holds exactly what the browser has when it re-matches a plan, in the shapes the site publishes::

    {"version": 1, "constants": {...},                           # what the matcher must have as constants (the browser's copies are held to these)
     "effects": [{"id", "k", "c", "d": [[donor key, access], ...]}, ...],   # the rows of effects.json the plans read
     "mass": {class: 0..1},                                     # effects.json "mass"
     "items": {key: {"classes", "slots", "weapon"?: {"skill"}, "tier_rule"}},   # the records of the item table (items.json) of every host and donor
     "lists": {"trio/role": {"classes", "role", "options": {kind: [row]}}},     # the exalt.json rows of a role (the lists, which do not depend on the kit)
     "cases": [{"lists": "trio/role", "tier": int, "kit": [key or null for each of the 22 places, in kit order], "plan": [row], "noroom": [row]}]}

so a case is "options + kit + hosts -> expected rows". Nothing here is read by the site: it is a test input, written by the code that makes the plans.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

from trioforge.classes import CLASS_CODES
from trioforge.data.jsonio import render
from trioforge.effects import files, judgment, plan
from trioforge.effects import layer as layer_module
from trioforge.effects import spells as sp
from trioforge.model.roles import MELEE_CLASSES, roles_for

__all__ = ["PLACES", "SITE_EFFECTS", "VERSION", "build_fixture", "main", "plan_fixture_text", "site_built", "site_catalog", "write_site_fixture"]

VERSION = 1
REPO = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO / "fixtures" / "effects" / "plan-parity.json"
PLACES = (
    "HEAD FACE EAR1 EAR2 NECK SHOULDERS ARMS BACK WRIST1 WRIST2 HANDS FINGER1 FINGER2 CHEST LEGS FEET WAIST RANGE ANY1 ANY2 PRIMARY SECONDARY".split()
)  # the places of a kit, in kit order (the order of the columns of an assignment, which decides ties)
SEED = 20261024
TIERS = (4, 4, 3, 2, 1, 0, 7)  # the tiers the kits are made for (4 is the default view's)
KITS_PER_ROLE = 2
EVERY = 31  # one trio in this many of the 560, plus the trios named below
NAMED = ("pal-mnk-ber", "clr-shd-shm", "wiz-mag-enc", "shd-brd-mag", "war-rog-rng", "bst-enc-shm")


def _usable(record: dict[str, Any], classes: Sequence[str]) -> bool:
    return "ALL" in record["classes"] or any(c in record["classes"] for c in classes)


def random_kit(rng: random.Random, items: dict[str, dict[str, Any]], classes: Sequence[str]) -> list[tuple[str, str]]:
    """A kit of real catalog items: for each place a random item of the place's slot (mostly one that a class of the trio can use), some places left empty."""
    by_slot: dict[str, list[str]] = {}
    for key in sorted(items):
        for slot in items[key]["slots"]:
            by_slot.setdefault(slot, []).append(key)
    usable_slot = {slot: [k for k in keys if _usable(items[k], classes)] for slot, keys in by_slot.items()}
    kit: list[tuple[str, str]] = []
    used: set[str] = set()
    anywhere = [slot for slot in sorted(by_slot) if slot not in ("PRIMARY", "SECONDARY", "RANGE", "AMMO", "CHARM", "POWERSOURCE")]
    for place in PLACES:
        if rng.random() < 0.08:
            continue  # a place left empty
        slot = place.rstrip("12")
        if slot == "ANY":
            slot = rng.choice(anywhere + ["PRIMARY", "SECONDARY"])
        pool = usable_slot.get(slot) if rng.random() < 0.85 else by_slot.get(slot)
        pool = [k for k in (pool or by_slot.get(slot, [])) if k not in used]
        if not pool:
            continue
        key = rng.choice(pool)
        used.add(key)
        kit.append((place, key))
    return kit


def trio_sample() -> list[str]:
    every = ["-".join(c.lower() for c in combo) for combo in combinations(CLASS_CODES, 3)]
    chosen = [slug for index, slug in enumerate(every) if index % EVERY == 0]
    for slug in NAMED:
        if slug in every and slug not in chosen:
            chosen.append(slug)
    return sorted(chosen)


def build_fixture(catalog: dict[str, Any], built: files.Built | None = None) -> dict[str, Any]:
    """The fixture document (see the module docstring) from a catalog document."""
    j = judgment.default()
    built = built or files.build(catalog, sp.SpellBook.load(), j, "fixture")
    shared = {row["id"]: row for row in files.shared_document(built)["effects"]}
    by_key = {item["key"]: item for item in catalog["items"]}
    rng = random.Random(SEED)
    lists: dict[str, Any] = {}
    cases: list[dict[str, Any]] = []
    used_effects: set[str] = set()
    used_items: set[str] = set()
    for slug in trio_sample():
        classes = [part.upper() for part in slug.split("-")]
        for role in roles_for(classes, bow=None):
            options = layer_module.layer(classes, role, built.ctx)
            rows = {name: [files._row(o) for o in options[name]] for name in files.LISTS}  # noqa: SLF001
            lists[f"{slug}/{role}"] = {"classes": classes, "role": role, "options": rows}
            for name in files.LISTS:
                for row in rows[name]:
                    used_effects.add(row["e"])
            for number in range(KITS_PER_ROLE):
                tier = TIERS[(len(cases) + number) % len(TIERS)]
                kit = random_kit(rng, built.items, classes)
                placed = plan.plan_kit(options, kit, built.items, built.ctx, classes, role, tier)
                filled = dict(kit)
                cases.append({"lists": f"{slug}/{role}", "tier": tier, "kit": [filled.get(place) for place in PLACES], "plan": placed["rows"], "noroom": placed["noroom"]})
                used_items.update(key for _, key in kit)
    effects = [{"id": row["id"], "k": row["k"], "c": row["c"], "d": row["d"]} for eid, row in sorted(shared.items()) if eid in used_effects]
    for row in effects:
        used_items.update(key for key, _ in row["d"])
    items: dict[str, Any] = {}
    for key in sorted(used_items):
        item = by_key[key]
        record: dict[str, Any] = {"classes": item["classes"], "slots": item["slots"], "tier_rule": item.get("tier_rule")}
        skill = (item.get("weapon") or {}).get("skill")
        if skill:
            record["weapon"] = {"skill": skill}
        items[key] = record
    return {
        "version": VERSION,
        "constants": {
            "melee": sorted(MELEE_CLASSES),
            "slot_tier": layer_module.SLOT_TIER,
            "kinds": list(plan.KINDS),
            "reasons": list(plan.REASONS),
            "places": list(PLACES),
        },
        "effects": effects,
        "mass": {c: round(m, 4) for c, m in built.ctx.mass.items()},
        "items": items,
        "lists": lists,
        "cases": cases,
    }


def plan_fixture_text(catalog: dict[str, Any], built: files.Built | None = None) -> str:
    """The text of the fixture file: one effect, item, list and case to a line, so a change shows as a changed line."""
    document = build_fixture(catalog, built)
    text = render(document, per_line=("effects", "items", "lists", "cases"))
    json.loads(text)  # (strict JSON, or this is a bug here)
    return text


# ---- the effects files of the site's fixture results ---------------------------------------------------------------------------------------------
#
# fixtures/site/results is a synthetic run: 48 invented items for the trio pal-mnk-ber, made before the effects layer, and the tests that read it as it is have no effects files. The
# page tests of the section Effects to exalt (pipeline/tests/test_site_exalt.py, the browser tests, scripts/preview.mjs with TRIOFORGE_PREVIEW_EXALT=1) make a copy of it and give the copy
# the two files of the layer, made by the code that makes the real ones from a catalog of those items to which a few effects have been given. The effects are real ones (their names and
# their wiki text, so that the repository's spell text can read them); the items that carry them are the fixture's own, so every key in the files is an item of the fixture's item table.

#: the effects the fixture's items carry: item key to ``(how the item is got, [(kind, name, wiki text)])``
SITE_EFFECTS: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "w90003": ("vendor", [("focus", "Spell Haste II", "Focus Effect: Spell Haste II")]),
    "w90004": ("drop", [("focus", "Improved Damage III", "Focus Effect: Improved Damage III")]),
    "w90007": ("quest", [("focus", "Mana Preservation II", "Focus Effect: Mana Preservation II")]),
    "w90009": ("drop", [("focus", "Enhancement Haste II", "Focus Effect: Enhancement Haste II")]),
    "w90046": ("raid", [("focus", "Improved Healing III", "Focus Effect: Improved Healing III")]),
    "w80236": ("quest", [("click", "Alacrity", "Effect: Alacrity (Clicky, Must Equip, Casting Time: Instant, Cooldown: 120 seconds) at Level 45")]),
    "w80417": ("vendor", [("click", "Superior Healing", "Effect: Superior Healing (Must Equip, Casting Time: Instant) at Level 30")]),
    "w90020": ("raid", [("click", "Pillage Enchantment", "Effect: Pillage Enchantment (Must Equip, Casting Time: 4.0, Cooldown 240)")]),
    "w90026": ("drop", [("click", "Raging Strength", "Click Effect: Raging Strength (Must Equip); Cast Time: 3.5 seconds; Required Level: 46; Cooldown: 120 seconds")]),
    "w90013": ("drop", [("click", "Spirit Tap", "Effect: Spirit Tap (Charge Clicky, Casting Time: 0.3, Cooldown: 1 seconds, Cooldown Group: 3)")]),
    "w90027": ("vendor", [("click", "Haste", "Effect: Haste (Any Slot, Casting Time: Instant)")]),
    "w80631": ("quest", [("click", "Levitate", "Effect: Levitate (Any Slot, Casting Time: Instant, Cooldown: 120 seconds) at Level 45")]),
    "w80988": ("drop", [("proc", "Oathbreaker's Curse", "Effect: Oathbreaker's Curse (Combat Req Level 45)")]),
    "w80923": ("quest", [("proc", "Flame Shock", "Effect: Flame Shock (Combat, Casting Time: Instant) at Level 45")]),
    "w80113": ("quest", [("proc", "Haste", "Effect: Haste (Combat, Casting Time: Instant) at Level 25")]),
    "w80524": ("drop", [("proc", "Ykesha", "Effect: Ykesha (Combat, Casting Time: Instant) at Level 37")]),
    "w90038": ("drop", [("proc", "Earthquake", "Effect: Earthquake (Combat, Casting Time: Instant) at Level 45")]),
    "w90021": ("vendor", [("proc", "Cleanse", "Effect: Cleanse (Combat, Casting Time: Instant)")]),
    "w90029": ("drop", [("worn", "Ultravision", "Effect: Ultravision (Worn)")]),
    "w80974": ("quest", [("worn", "Heritage of Mistmoore", "Effect: Heritage of Mistmoore (Worn)")]),
}  # fmt: skip
_SOURCES = {
    "vendor": {"drops": [], "sold_by": ["a merchant"], "quests": [], "crafted": []},
    "quest": {"drops": [], "sold_by": [], "quests": ["a quest"], "crafted": []},
    "raid": {"drops": [{"zone": "Plane of Fear", "npcs": []}], "sold_by": [], "quests": [], "crafted": []},
    "drop": {"drops": [{"zone": "Lake of Ill Omen", "npcs": []}], "sold_by": [], "quests": [], "crafted": []},
}


def site_catalog(items_doc: dict[str, Any]) -> dict[str, Any]:
    """A catalog document of the fixture's item table (``fixtures/site/results/items.json``) with the effects of :data:`SITE_EFFECTS` given to its items."""
    items = []
    for record in items_doc["items"]:
        key = record.get("key") or f"w{record['id']}"
        how, effects = SITE_EFFECTS.get(key, ("drop", []))
        items.append({
            "key": key, "name": record["name"], "classes": record.get("classes", ["ALL"]), "slots": record["slots"], "weapon": record.get("weapon"),
            "tier_rule": record["tier_rule"], "evidence": {"level": "wiki"}, "effects": [{"kind": k, "name": n, "raw": raw} for k, n, raw in effects],
            "sources": _SOURCES[how],
        })  # fmt: skip
    missing = sorted(set(SITE_EFFECTS) - {item["key"] for item in items})
    if missing:
        raise ValueError(f"the fixture's item table has no item {missing[0]}")
    return {"version": items_doc["data_release"].removeprefix("data-"), "license": "CC BY-SA 4.0", "attribution": "fixture", "items": items}


def site_built(results: Path) -> files.Built:
    """The layer's inputs for the fixture results: the effects of the fixture's catalog, read with the repository's spell text."""
    items_doc = json.loads((results / "items.json").read_text(encoding="utf-8"))
    return files.build(site_catalog(items_doc), sp.SpellBook.load(), judgment.default(), items_doc["rules_version"])


def write_site_fixture(results: Path, slugs: Sequence[str] = ("pal-mnk-ber",)) -> dict[str, tuple[int, int]]:
    """Write ``effects.json`` and the ``exalt.json`` of each trio into the fixture results (the real writer); returns the sizes."""
    return files.write_release(results, slugs, site_built(results), lambda _line: None)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write (or check) the plan fixtures the browser's matcher is held to, or the effects files of the site's fixture results.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--catalog", type=Path, default=REPO / "derived" / "catalog.json")
    parser.add_argument("--site", type=Path, help="write the effects files of the site's fixture results into this copy of fixtures/site/results instead")
    parser.add_argument("--check", action="store_true", help="do not write: say whether the plan fixtures are what this code makes")
    args = parser.parse_args(argv)
    if args.site is not None:
        if args.site.resolve() == (REPO / "fixtures" / "site" / "results").resolve():
            parser.error("fixtures/site/results is the run made before the effects layer and has none of its files: give a copy of it")
        for name, (raw, packed) in sorted(write_site_fixture(args.site).items()):
            print(f"wrote {args.site / name} ({raw:,} bytes, {packed:,} gzipped)")
        return 0
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    text = plan_fixture_text(catalog)
    if args.check:
        same = args.out.is_file() and args.out.read_bytes() == text.encode("utf-8")  # (the bytes: a file with other line ends is not the file this code writes)
        print("the plan fixtures are up to date" if same else f"{args.out} is not what this code makes: run it without --check")
        return 0 if same else 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {args.out} ({len(text):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
