"""The engine's data for the synthetic site fixture, and the way it is made.

``fixtures/site/results/pal-mnk-ber`` (the shards, the runner-ups, the defaults and the seals) is hand-written, with invented
names and numbers; the browser engine needs two more files that cannot be written by hand: the bundle of the trio and the item table. They are
made here, with the exporter's own functions (:func:`trioforge.export.browser.bundle` and :func:`~trioforge.export.browser.items`),
from an **invented catalog** that lists the items of the fixture's shards under the same keys, names, slots, tier rules, deities and
evidence levels, with invented stats. The fixture's catalog has no seen flags: the levels in it are the levels the shards show. Both files carry
the fingerprint of their inputs, as the precompute writes it (the SHA-256 of the canonical JSON of the invented catalog stands for the hash of a
catalog file).

* ``fixtures/site/results/items.json`` and ``fixtures/site/results/pal-mnk-ber/engine-l50.json``: the two files, as the precompute
  writes them beside the shards (``trioforge.precompute.shards`` has the format);
* ``fixtures/site/equip-now.json``: three Equip now scenarios (a race, a role, a buff set, an evidence level, a weapon setup, a deity
  or none, and an owned set), each with the answer that Python's reference gives (:func:`trioforge.upgrade.equip_now`, with the tie
  stage): the exact value as a reduced ``p/q``, the kit place for place, the chosen buffs and the haste the kit counts (the weapon index is taken at it). The browser tests
  (``tests-js/engine-scenario.test.mjs``, ``tests-e2e/engine.spec.mjs``) hold the engine to them. The owned sets are chosen so that the
  best kit is the same with and without the tie stage, which the browser's answer does not have.
* ``fixtures/site/best-kit.json``: views of the whole pool (the best-kit mode of the worker), each with a tier and weights as the request
  carries them (``multipliers``, ``custom``, ``regenT``), and the answer that Python's reference gives for them: the pool of the view at
  the tier, pruned, with the weights of the view's profile composed by :func:`trioforge.model.roles.weights_override` (the precompute's
  solve, but for those weights), solved with the tie stage. A view with weights also carries ``own``, the answer at the role's own
  weights, so that a test can see that the weights moved the kit or its value. The best kit is the same with and without the tie stage.
* ``fixtures/site/kit-values.json``: the value of each of those kits under every role and buff set of the bundle in which the kit is still the best arrangement of its own
  items (:func:`kit_values`), as Python's reference works it out: the kit's own items are the whole pool (``upgrade.equip_now`` with the kit as the owned set), so the answer is the
  best value of that kit with the best buffs, the weapon setup is the one the kit was made for, and the weapon index is taken at the haste the kit counts under the buffs
  chosen (the truthful solve of ``trioforge.solver.haste``). The browser tests hold the page's evaluator for a shared kit (``static/engine/kitvalue.js``) to these numbers exactly.
* ``fixtures/site/weighted.json``: the four Upgrade modes under weights. Each Equip now scenario above is given weights drawn from a fixed seed
  (:func:`draw_weights`: ``"trioforge-weights:<scenario>:<draw>"``, a function of its text alone; a draw whose answers depend on the tie stage is skipped, and
  the one after it is looked at), and a tier mode (ready4, arrives, fixed), and carries what Python's reference gives for a profile whose weights are
  :func:`trioforge.model.roles.weights_override`'s: Equip now (``upgrade.equip_now``), a farm path of three steps (``upgrade.farm_path``, with its start: Equip now), the best 2 and 3 sets (``upgrade.best_sets``) and Every slot (``upgrade.every_slot``) from the kit of Equip now. The candidates are those of
  the worker: the items of the evidence level that the precompute offers (:func:`trioforge.precompute.grid.select_items`, deity-locked ones too), each at the tier of the tier mode.
  Every value is that of the kit at the haste it counts, whatever the weights; each answer says it. The browser tests hold the worker to every number of it.
* ``fixtures/site/mote-orders.json``: the order in which to spend void-touched motes on a fixed kit (:func:`trioforge.motes.mote_order`), as Python's reference works it out: each step is
  the one mote (one whole tier on one worn item below +10) that adds the most exact kit value, the kit valued as the Upgrade tab values it (the haste the kit counts, the optional buffs
  the kit was made with held fixed), ties to the earlier place, ending at +10 everywhere, at the motes asked for, or at a best gain of zero. The cases are the kits of the Equip now
  scenarios with a limit of motes, the three small kits in full, the same kits under drawn weights, a kit with every item at one tier (as a published best kit is), the kit the baked trio page
  of the fixture shows, the kit Equip now finds for the gear of the browser test, one a tier from the top and one at the top. Each says its scenario, weights, kit, buffs and limit, and the steps: the place, the item, its tiers, the exact gain and kit value after the step and the stats that moved.
  The browser's port (``static/engine/motes.js``, through ``kitvalue.js``) is held to every number (``tests-js/motes.test.mjs``).
* ``fixtures/site/weapon-rate.json``: best kits of whole-pool views at the weapon tier rate 5 and 10 percent (``at_tier(weapon_pct=)``), and with no rate (``rules``: the rule
  ``tier.weapon_damage_pct``, 10), as the best-kit answers are made. At +0 no weapon has grown and the two rates give one answer.

* ``fixtures/site/results-procs/pal-mnk-ber/engine-l50.json`` and ``fixtures/site/procs-family.json`` (F6): the family with a table of invented procs in its bundle (every other file holds ``"procs": null``), and Python's
  Equip now, farm path, best sets, Every slot and mote orders with that table (``tests-js/engine-procs-family.test.mjs`` holds the worker and the page's mote order to them).

``test_site_engine_fixture.py`` makes them again and fails when a committed file differs. After a change to the exporter, the rules or
the invented items, write them again with::

    PYTHONPATH=pipeline .venv/bin/python pipeline/tests/engine_fixture.py
* ``fixtures/site/upgrade-view.json``: the view and the gear that ``tests-e2e/upgrade.spec.mjs`` gives the page (the dump ``fixtures/dumps/site-small.txt`` read as the page reads it, on the page's
  default view), with the answers of Python's reference: Equip now and a farm path of three steps (``upgrade.equip_now``, ``upgrade.farm_path``, the tie stage on and off agreeing), so that the
  test can pin the Next step and the first step under Then to the reference and not to what the worker said.

Every name and number here is invented: ``test_site_fixture_items.py`` fails when the key or the name of a real item of the wiki
(``derived/catalog.json``) is in this file or anywhere in the fixture.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "fixtures" / "site" / "results"
TRIO_FOLDER = RESULTS / "pal-mnk-ber"
EQUIP_NOW = REPO / "fixtures" / "site" / "equip-now.json"
KIT_VALUES = REPO / "fixtures" / "site" / "kit-values.json"
BEST_KIT = REPO / "fixtures" / "site" / "best-kit.json"
WEIGHTED = REPO / "fixtures" / "site" / "weighted.json"
WEAPON_RATE = REPO / "fixtures" / "site" / "weapon-rate.json"
MOTE_ORDERS = REPO / "fixtures" / "site" / "mote-orders.json"
UPGRADE_VIEW = REPO / "fixtures" / "site" / "upgrade-view.json"
PROCS_BUNDLE = REPO / "fixtures" / "site" / "results-procs" / "pal-mnk-ber" / "engine-l50.json"
PROCS_FAMILY = REPO / "fixtures" / "site" / "procs-family.json"
PROCS_ITEMS = REPO / "fixtures" / "site" / "results-procs" / "items.json"
SLUG = "pal-mnk-ber"
TRIO = ("PAL", "MNK", "BER")
LEVEL = 50
VERSION = "2026-10-14"  # the catalog version: the data release of the shards is data-2026-10-14

#: stats and the rest, by key, of every item the fixture's shards show (the name, slots, tier rule, deity and level come from the
#: shards themselves, so that the two cannot differ). ``weight`` in stones; ``shield`` and ``weapon`` as the catalog writes them.
ITEMS: dict[str, dict[str, Any]] = {
    "w80113": {"stats": {"STR": 8, "ATK": 10}, "weight": 3.0, "weapon": ("1H Blunt", 13, 20, 10)},
    "w80158": {"stats": {"AC": 11, "WIS": 10, "HP": 40}, "weight": 2.0},
    "w80236": {"stats": {"AC": 8, "AGI": 6}, "weight": 1.0},
    "w80392": {"stats": {"AC": 12, "STA": 5}, "weight": 3.0},
    "w80417": {"stats": {"AC": 9, "HP": 50, "MANA": 30}, "weight": 0.5},
    "w80469": {"stats": {"AC": 38, "STA": 14, "END": 25}, "weight": 9.0},
    "w80524": {"stats": {"STR": 12, "STA": 10}, "weight": 7.0, "weapon": ("2H Slashing", 36, 38, 22)},
    "w80583": {"stats": {"AC": 22, "STA": 8}, "weight": 4.5, "shield": True},
    "w80631": {"stats": {"STR": 9, "ATK": 12, "HP": 60}},
    "w80677": {"stats": {"AC": 9, "AGI": 9}, "weight": 1.5},
    "w80712": {"stats": {"AC": 6, "DEX": 8}, "sv": {"FIRE": 14}, "weight": 1.0},
    "w80758": {"stats": {"AC": 26, "STA": 10, "HP": 80}, "weight": 5.0, "shield": True},
    "w80816": {"stats": {"AC": 12, "STA": 11, "ATK": 10}, "weight": 1.0},
    "w80869": {"stats": {"AC": 19, "STR": 6}, "weight": 4.0, "shield": True},
    "w8091": {"stats": {"AC": 16, "STA": 9, "HP": 45}, "weight": 3.0},
    "w80923": {"stats": {"WIS": 10, "MANA": 40}, "weight": 2.0, "weapon": ("1H Piercing", 15, 22, None)},
    "w80974": {"stats": {"WIS": 8, "MANA": 30, "HP": 20}, "weight": 0.5},
    "w80988": {"stats": {"STR": 10, "ATK": 14}, "sv": {"FIRE": 10}, "weight": 3.5, "weapon": ("1H Slashing", 16, 24, None)},
    "w90001": {"stats": {"AC": 30, "STA": 12, "HP": 60}, "weight": 4.0},
    "w90002": {"stats": {"AC": 22, "STR": 8}, "weight": 3.0},
    "w90003": {"stats": {"AC": 34, "STA": 16, "HP": 70}, "weight": 4.5},
    "w90004": {"stats": {"AC": 38, "STA": 20, "HP": 90}, "weight": 5.0},
    "w90006": {"stats": {"AC": 10, "WIS": 9}, "weight": 0.5},
    "w90007": {"stats": {"INT": 6, "MANA": 30, "HP": 25}, "weight": 0.1},
    "w90008": {"stats": {"HASTE": 15, "AGI": 5}, "weight": 0.1},
    "w90009": {"stats": {"STA": 9, "HP": 35}, "weight": 0.1},
    "w90011": {"stats": {"STA": 10, "HP": 55}, "sv": {"MAGIC": 12}, "weight": 0.5},
    "w90013": {"stats": {"AC": 18, "STR": 10}, "weight": 3.5},
    "w90014": {"stats": {"AC": 14, "STR": 9, "ATK": 8}, "weight": 2.0},
    "w90015": {"stats": {"AC": 12, "STA": 7}, "weight": 2.0},
    "w90016": {"stats": {"AC": 17, "HP": 65}, "weight": 2.5},
    "w90020": {"stats": {"AC": 9, "DEX": 7}, "weight": 1.0},
    "w90021": {"stats": {"AC": 10, "HP": 40}, "sv": {"DISEASE": 8}, "weight": 1.0},
    "w90022": {"stats": {"AGI": 6, "HP": 30}, "weight": 0.5},
    "w90023": {"stats": {"AC": 13, "STR": 8, "ATK": 15}, "weight": 2.0},
    "w90024": {"stats": {"AC": 11, "STA": 9}, "weight": 1.5},
    "w90026": {"stats": {"STA": 10, "HP": 50}, "lore": True},
    "w90027": {"stats": {"STR": 7, "ATK": 9}},
    "w90029": {"stats": {"AC": 42, "STA": 12, "HP": 80}, "weight": 10.0},
    "w90030": {"stats": {"AC": 24, "STA": 10}, "weight": 5.0},
    "w90031": {"stats": {"AC": 20, "STR": 8}, "weight": 4.0},
    "w90032": {"stats": {"AC": 14, "AGI": 8}, "weight": 2.0},
    "w90033": {"stats": {"AC": 16, "STR": 9}, "weight": 3.0, "races": ["OGR", "TRL"]},
    "w90037": {"stats": {"ATK": 6}, "weight": None},
    "w90038": {"stats": {"DEX": 8}, "weight": 1.0, "weapon": ("Archery", 12, 36, None)},
    "w90046": {"stats": {"AC": 40, "WIS": 12}, "weight": 6.0},
}

#: items no shard shows: one a trio cannot wear, one that only a player may own (hidden), one that fits no place of a kit (ammunition)
EXTRAS: list[dict[str, Any]] = [
    {"key": "w90040", "name": "Cap of the Archmage", "slots": ["HEAD"], "classes": ["WIZ"], "tier_rule": "drop", "level": "strict",
     "stats": {"INT": 14, "MANA": 100}, "weight": 1.0},
    {"key": "w90041", "name": "Relic Helm of the Elders", "slots": ["HEAD"], "classes": ["ALL"], "tier_rule": "drop", "level": "hidden",
     "stats": {"AC": 50, "STA": 18, "HP": 120}, "weight": 4.0},
    {"key": "w90042", "name": "Quiver of Plenty", "slots": ["AMMO"], "classes": ["ALL"], "tier_rule": "drop", "level": "wiki",
     "stats": {"STA": 50}, "weight": 1.0},
]  # fmt: skip

#: the Equip now scenarios: (name, scenario, owned as (key, tier, count))
CASES: list[dict[str, Any]] = [
    {
        "name": "an Ogre, tank, own buffs, wiki evidence, dual wield",
        "scenario": {"race": "OGR", "role": "tank", "buffs": "own", "evidence": "wiki", "setup": "dw"},
        "owned": [
            ("w90001", 0, 1), ("w90001", 4, 1), ("w90002", 0, 1), ("w90003", 4, 1), ("w90006", 4, 1), ("w90007", 4, 2),
            ("w90008", 0, 1), ("w90009", 4, 1), ("w90011", 4, 1), ("w90013", 4, 1), ("w90014", 4, 1), ("w90015", 0, 1),
            ("w90020", 4, 1), ("w90021", 4, 2), ("w90022", 0, 1), ("w90023", 4, 1), ("w90026", 4, 2), ("w90027", 4, 1),
            ("w90029", 4, 1), ("w90029", 10, 1), ("w90030", 4, 1), ("w90032", 4, 1), ("w90033", 4, 1), ("w90037", 4, 1),
            ("w90038", 4, 1), ("w80988", 4, 2), ("w80113", 0, 1), ("w80923", 4, 1), ("w80524", 4, 1), ("w80758", 4, 1),
            ("w90040", 4, 1), ("w90041", 4, 1), ("w90004", 4, 1),
        ],
    },
    {
        "name": "a Troll, tank, group buffs, strict evidence, one-hander and shield, a follower of the Tribunal",
        "scenario": {"race": "TRL", "role": "tank", "buffs": "group", "evidence": "strict", "setup": "1h-shield", "deity": "The Tribunal"},
        "owned": [
            ("w90004", 4, 1), ("w90046", 4, 1), ("w90001", 4, 1), ("w90013", 4, 1), ("w90016", 4, 1), ("w90023", 4, 1),
            ("w90030", 4, 1), ("w90032", 4, 1), ("w90033", 4, 1), ("w80677", 4, 1), ("w80158", 0, 1), ("w80758", 4, 1),
            ("w80583", 4, 1), ("w80869", 0, 1), ("w80988", 4, 1), ("w80113", 0, 1), ("w80816", 4, 1), ("w90009", 4, 2),
            ("w80631", 4, 1), ("w90026", 4, 2), ("w80712", 4, 1), ("w80469", 4, 1),
        ],
    },
    {
        "name": "an Iksar, melee, group and the Enchanter's haste, wiki evidence, two-hander",
        "scenario": {"race": "IKS", "role": "melee", "buffs": "group+enchanter", "evidence": "wiki", "setup": "2h"},
        "owned": [
            ("w80524", 4, 1), ("w80524", 0, 1), ("w80988", 4, 1), ("w90002", 0, 1), ("w90003", 4, 1), ("w90014", 4, 1),
            ("w90023", 4, 1), ("w90020", 4, 1), ("w90021", 4, 1), ("w90031", 0, 1), ("w90030", 4, 1), ("w90032", 4, 1),
            ("w90008", 0, 1), ("w90009", 4, 1), ("w90007", 4, 1), ("w90011", 4, 1), ("w90027", 4, 1), ("w80631", 4, 2),
            ("w80677", 4, 1), ("w80712", 4, 1), ("w90038", 4, 1), ("w80469", 4, 1),
        ],
    },
    {
        "name": "an Ogre, tank, group buffs and a haste spell, wiki evidence, one-hander and shield",
        "scenario": {"race": "OGR", "role": "tank", "buffs": "group+haste", "evidence": "wiki", "setup": "1h-shield"},
        "owned": [
            ("w90001", 0, 1), ("w90001", 4, 1), ("w90002", 0, 1), ("w90003", 4, 1), ("w90006", 4, 1), ("w90007", 4, 2),
            ("w90008", 0, 1), ("w90009", 4, 1), ("w90011", 4, 1), ("w90013", 4, 1), ("w90014", 4, 1), ("w90015", 0, 1),
            ("w90020", 4, 1), ("w90021", 4, 2), ("w90022", 0, 1), ("w90023", 4, 1), ("w90026", 4, 2), ("w90027", 4, 1),
            ("w90029", 4, 1), ("w90029", 10, 1), ("w90030", 4, 1), ("w90032", 4, 1), ("w90033", 4, 1), ("w90037", 4, 1),
            ("w90038", 4, 1), ("w80988", 4, 2), ("w80113", 0, 1), ("w80923", 4, 1), ("w80524", 4, 1), ("w80758", 4, 1),
            ("w90040", 4, 1), ("w90041", 4, 1), ("w90004", 4, 1),
        ],
    },
    {
        "name": "a Human, melee, the raid buffs and a haste spell, wiki evidence, two-hander",
        "scenario": {"race": "HUM", "role": "melee", "buffs": "raid+haste", "evidence": "wiki", "setup": "2h"},
        "owned": [
            ("w80524", 4, 1), ("w80524", 0, 1), ("w80988", 4, 1), ("w90002", 0, 1), ("w90003", 4, 1), ("w90014", 4, 1),
            ("w90023", 4, 1), ("w90020", 4, 1), ("w90021", 4, 1), ("w90031", 0, 1), ("w90030", 4, 1), ("w90032", 4, 1),
            ("w90008", 0, 1), ("w90009", 4, 1), ("w90007", 4, 1), ("w90011", 4, 1), ("w90027", 4, 1), ("w80631", 4, 2),
            ("w80677", 4, 1), ("w80712", 4, 1), ("w90038", 4, 1), ("w80469", 4, 1),
        ],
    },
]  # fmt: skip


#: kits that are not an answer of the Equip now scenarios above, for the page's value of a shared kit: few items, so that the haste a kit's own items give (a hoop of haste worn, or
#: left in the bag) and the hands (a two-hander alone) are what the value shows. Each is the best kit Python's reference finds for its owned set under its scenario.
KIT_ONLY: list[dict[str, Any]] = [
    {
        "name": "an Ogre with few items: a hoop of haste, a head piece and a one-hander",
        "scenario": {"race": "OGR", "role": "tank", "buffs": "own", "evidence": "wiki", "setup": "dw"},
        "owned": [("w90008", 0, 1), ("w90001", 4, 1), ("w80988", 4, 1)],
    },
    {
        "name": "a Human with a two-hander and a hoop of haste",
        "scenario": {"race": "HUM", "role": "melee", "buffs": "raid", "evidence": "wiki", "setup": "2h"},
        "owned": [("w80524", 4, 1), ("w90008", 0, 1), ("w90013", 4, 1)],
    },
    {
        "name": "a Troll with a one-hander, a shield and a chest piece",
        "scenario": {"race": "TRL", "role": "tank", "buffs": "group", "evidence": "wiki", "setup": "1h-shield"},
        "owned": [("w80988", 4, 1), ("w80583", 4, 1), ("w90029", 4, 1)],
    },
]  # fmt: skip


def shard_items() -> dict[str, dict[str, Any]]:
    """The item rows of the fixture's shards and runner-up files by key: ``name``, ``slots``, ``tier_rule``, ``source``,
    ``evidence`` and ``deity`` of each item they show (the same item reads the same in every file)."""
    names = ("key", "name", "slots", "tier_rule", "arrival", "source", "evidence", "deity")
    found: dict[str, dict[str, Any]] = {}
    paths = [*sorted(TRIO_FOLDER.glob("*-*.json")), *sorted(p for p in (TRIO_FOLDER / "runnerups").glob("*.json") if p.name != "index.json")]
    for path in paths:
        if path.name.startswith("engine-"):
            continue
        for row in json.loads(path.read_text(encoding="utf-8")).get("items", ()):
            found.setdefault(row[0], dict(zip(names, row)))
    return found


def sources_of(row: Mapping[str, Any]) -> dict[str, Any]:
    """Where an item comes from, in the catalog's form, in the words of the shard's own row (a zone, a quest, a vendor, a recipe)."""
    text, none = row["source"], {"drops": [], "sold_by": [], "quests": [], "crafted": []}
    if row["tier_rule"] == "drop":
        return {**none, "drops": [{"zone": text, "npcs": ["a keeper"]}]}
    if text.startswith("Quest in "):
        return {**none, "quests": [f"{text.removeprefix('Quest in ')} quest"]}
    if text.startswith("Vendor in "):
        return {**none, "sold_by": [{"zone": text.removeprefix("Vendor in "), "npc": "a vendor"}]}
    return {**none, "crafted": [{"container": "a forge", "components": []}]}


#: The item the family with procs adds to the catalog (G4): a Lore weapon for either hand that carries an effect of its own, so that a kit that wears it in one hand has the other hand refused its proc.
FAMILY_LORE_WEAPON: dict[str, Any] = {
    "key": "w91101", "name": "Prop Lorebrand of the Quiet Hand", "slots": ["PRIMARY", "SECONDARY"], "stats": {"STR": 6, "ATK": 8}, "weight": 3.0, "weapon": ("1H Slashing", 14, 22, None),
}  # fmt: skip
#: (H3) a plain weapon for either hand, whose key is LARGER than the Lore weapon's, that carries the effect the Lore weapon carries as its second (Prop Squall): the effect has two donors, and the one that
#: the other hand's proc is recorded from is not the smallest key among those the host can take, which the kit's Lore weapon is, but the other.
FAMILY_PLAIN_WEAPON: dict[str, Any] = {
    "key": "w91102", "name": "Prop Quillon of the Loud Hand", "slots": ["PRIMARY", "SECONDARY"], "stats": {"STR": 1}, "weight": 1.0, "weapon": ("1H Slashing", 3, 40, None),
}  # fmt: skip


def catalog(family: bool = False) -> dict[str, Any]:
    """The invented catalog of the fixture: its items are those of the shards (with their level and deity) and the extras (and, for the family with procs, a Lore weapon)."""
    from test_precompute import make_item, weapon

    rows = shard_items()
    missing = sorted(set(rows) - set(ITEMS))
    if missing:
        raise SystemExit(f"the invented stats of these items are missing: {', '.join(missing)}")
    listed = []
    for key in sorted(rows, key=lambda k: int(k[1:])):
        row, more = rows[key], ITEMS[key]
        skill = more.get("weapon")
        listed.append(
            make_item(
                key, row["name"], row["slots"], stats=more["stats"], sv=more.get("sv"), weight=more.get("weight", 1.0),
                weapon=None if skill is None else weapon(*skill), item_type="Shield" if more.get("shield") else None,
                flags=["lore"] if more.get("lore") else (), deity=row["deity"], level=row["evidence"], tier_rule=row["tier_rule"],
                sources=sources_of(row), races=more.get("races", ("ALL",)),
            )
        )
    for extra in EXTRAS:
        listed.append(
            make_item(
                extra["key"], extra["name"], extra["slots"], classes=extra["classes"], stats=extra["stats"], weight=extra["weight"],
                level=extra["level"], tier_rule=extra["tier_rule"],
            )
        )
    if family:
        for added, flags in ((FAMILY_LORE_WEAPON, ["lore"]), (FAMILY_PLAIN_WEAPON, [])):
            listed.append(
                make_item(
                    added["key"], added["name"], added["slots"], stats=added["stats"], weight=added["weight"], weapon=weapon(*added["weapon"]), flags=flags, level="wiki", tier_rule="drop",
                )
            )
    listed.sort(key=lambda item: int(item["key"][1:]))
    return {"version": VERSION, "license": "CC BY-SA 4.0", "attribution": "invented", "provenance": {}, "items": listed}


def documents(family: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(bundle, item table)`` of the fixture, made by the exporter from the invented catalog (no seen flags), each with the fingerprint of its inputs."""
    from trioforge.export import browser
    from trioforge.model.tables import REPO as ROOT
    from trioforge.model.tables import load

    tables = load()
    spells = json.loads((ROOT / "derived" / "client" / f"spells-l{LEVEL}.json").read_text(encoding="utf-8"))
    document = catalog(family)
    made = browser.bundle(TRIO, LEVEL, tables, tables.rules, spells, data_release=f"data-{VERSION}", catalog=document)
    table = browser.items(document, tables.rules)
    catalog_sha256 = hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    inputs = browser.inputs_fingerprint(catalog_sha256, table)
    return browser.with_inputs(made, inputs), browser.with_inputs(table, inputs)


def texts() -> dict[Path, str]:
    """The text of each committed file of the fixture's engine data, by path (the Equip now answers are in :func:`answers`)."""
    from trioforge.export import browser

    made, table = documents()
    return {TRIO_FOLDER / "engine-l50.json": browser.render_bundle(made), RESULTS / "items.json": browser.render_items(table)}


_WORLDS: dict[Any, Any] = {}


def _world(spell_haste: bool | None = None, family: bool = False) -> Any:
    """What the reference answers are worked out from: the tables, the bundle and the item table of the fixture, the four buff sets, the item records by key, and the
    pool of each evidence level. ``spell_haste`` None follows the rule ``haste.assume_spell`` (false: no spell haste in the buff sets); True makes the buff sets with the haste of the
    spells, for the one case that is about a worn haste item past the cap (the bundle of the fixture has such sets under the keys of its twins, which the default world has too)."""
    if (spell_haste, family) not in _WORLDS:
        _WORLDS[(spell_haste, family)] = _make_world(spell_haste, family)
    return _WORLDS[(spell_haste, family)]


def _make_world(spell_haste: bool | None, family: bool = False) -> Any:
    from types import SimpleNamespace

    from trioforge.export import browser
    from trioforge.model import items as item_module
    from trioforge.model.buffs import BUFF_SETS, buffsets as make_buffsets
    from trioforge.model.tables import REPO as ROOT
    from trioforge.model.tables import load
    from trioforge.precompute import grid

    tables = load()
    rules = tables.rules
    spells = json.loads((ROOT / "derived" / "client" / f"spells-l{LEVEL}.json").read_text(encoding="utf-8"))
    made, table = documents(family)
    buffsets = make_buffsets(TRIO, LEVEL, spells, rules, BUFF_SETS, spell_haste=spell_haste)  # (no spell haste in them while the rule haste.assume_spell is false, unless asked)
    if spell_haste is None:  # (the world of the bundle: its twins of the buff sets keep the haste of the spells, which is what a reader's "I have a haste spell" solves with)
        buffsets.update({key + browser.HASTE_SUFFIX: made_set for key, made_set in make_buffsets(TRIO, LEVEL, spells, rules, BUFF_SETS, spell_haste=True).items()})
    records = {browser.record_key(record): record for record in table["items"]}
    selection = grid.select_items(catalog(family)["items"], TRIO)
    pools = {label: [item_module.at_tier(item, 0, rules) for item in grid.pool_dicts(selection, label)] for label in grid.EVIDENCE}
    return SimpleNamespace(
        tables=tables, rules=rules, made=made, table=table, buffsets=buffsets, records=records, pools=pools, selection=selection, spell_haste=spell_haste,
    )


def _profile(world: Any, scenario: Mapping[str, Any], role: str | None = None, buffs: str | None = None) -> Any:
    """The profile of a scenario, or of a view of it (the role and the buff set may be other than the scenario's), checked against what the browser's bundle assembles."""
    from trioforge.export import browser
    from trioforge.model.profile import make_profile

    role, buffs = role or scenario["role"], buffs or scenario["buffs"]
    profile = make_profile(
        scenario["race"], TRIO, LEVEL, role, world.buffsets[buffs], None, world.tables, evidence=scenario["evidence"],
        deity=scenario.get("deity"), items=world.pools[scenario["evidence"]],
    )
    if not world.spell_haste:  # (the world with the haste of the spells under the keys of the rule is not what the bundle holds under them: it is held to its twins in the default world)
        assert profile.to_dict() == browser.assemble(
            world.made, scenario["race"], role, buffs, evidence=scenario["evidence"], deity=scenario.get("deity")
        ), "the bundle does not reassemble to the profile of the scenario"
    return profile


def _owned(world: Any, idents: Any) -> dict[Any, int]:
    """The owned set of Python's reference for items given as ``(key, tier, count)``: each item at its tier."""
    from trioforge.export import browser
    from trioforge.model import items as item_module

    owned: dict[Any, int] = {}
    for key, tier, count in idents:
        owned[item_module.at_tier(browser.item_to_catalog(world.records[key], world.table["defaults"]), tier, world.rules)] = count
    return owned


def _counted_haste(solution: Any) -> int:
    """The haste percent the kit of a solution counts, which is the haste its value assumes (the truthful solve)."""
    return int(solution.breakdown.totals["haste"]["counted"])


def answers() -> dict[str, Any]:
    """The Equip now scenarios with Python's answers: the reference run on the owned set, with the tie stage."""
    from trioforge import upgrade

    world = _world()
    out = []
    for case in CASES:
        scenario = case["scenario"]
        profile = _profile(world, scenario)
        owned = _owned(world, case["owned"])
        solution = upgrade.equip_now(profile, owned, scenario["setup"], world.buffsets[scenario["buffs"]], canonical=True)
        assert solution.status == "optimal" and solution.breakdown is not None
        plain = upgrade.equip_now(profile, owned, scenario["setup"], world.buffsets[scenario["buffs"]], canonical=False)
        assert plain.breakdown.F == solution.breakdown.F and [i and (i.key, i.tier) for i in plain.kit] == [
            i and (i.key, i.tier) for i in solution.kit
        ] and plain.buffs == solution.buffs, f"{case['name']}: the best kit depends on the tie stage"
        value = solution.breakdown.F
        out.append(
            {
                "name": case["name"],
                "scenario": scenario,
                "owned": [[f"{key}@{tier}", count] for key, tier, count in case["owned"]],
                "F": f"{value.numerator}/{value.denominator}",
                "value": float(value),
                "kit": [None if item is None else f"{item.key}@{item.tier}" for item in solution.kit],
                "buffs": list(solution.buffs),
                "hasteAssumed": _counted_haste(solution),
            }
        )
    return {"trio": SLUG, "level": LEVEL, "cases": out}


#: the roles and the buff sets a kit is valued under (every role of the bundle, and the four buff sets of the engine tests; the page offers two of the sets today)
VIEW_ROLES = ("tank", "melee")
VIEW_BUFFS = ("own", "group", "group+enchanter", "raid", "own+haste", "group+haste", "group+enchanter+haste", "raid+haste")


def _arrangement(kit: Any) -> list[tuple[str, ...]]:
    """A kit as its value depends on it: for each group of places, the sorted idents worn in it (two places of one group, such as the two ears, are alike)."""
    from trioforge.model.items import SLOT_INSTANCES

    groups: dict[str, list[str]] = {}
    for place, ident in zip(SLOT_INSTANCES, kit, strict=True):
        if ident is not None:
            groups.setdefault(place, []).append(ident)
    return [(place, *sorted(idents)) for place, idents in groups.items()]


def kit_values() -> dict[str, Any]:
    """The value of each Equip now kit under each role and buff set of the bundle in which it is still the best arrangement of its own items (see the header).

    A view is kept when Python's best kit from the kit's own items, with the tie stage, wears the same items in the same groups of places: then the value of the best kit is the
    value of the kit, with the best buffs of the view. The setup is the one the kit was made for (it is the kit's hands), and the weapon index is taken at the haste the kit counts.
    """
    from collections import Counter

    from trioforge import upgrade

    world = _world()
    kits, values = [], []
    small = []
    for case in KIT_ONLY:
        profile = _profile(world, case["scenario"])
        owned = _owned(world, case["owned"])
        solution = upgrade.equip_now(profile, owned, case["scenario"]["setup"], world.buffsets[case["scenario"]["buffs"]], canonical=True)
        plain = upgrade.equip_now(profile, owned, case["scenario"]["setup"], world.buffsets[case["scenario"]["buffs"]], canonical=False)
        assert solution.status == "optimal" and [i and (i.key, i.tier) for i in plain.kit] == [i and (i.key, i.tier) for i in solution.kit], f"{case['name']}: the best kit depends on the tie stage"
        small.append({"kit": [None if item is None else f"{item.key}@{item.tier}" for item in solution.kit]})
    for case, answer in [*zip(CASES, answers()["cases"], strict=True), *zip(KIT_ONLY, small, strict=True)]:
        scenario = case["scenario"]
        counts = Counter(ident for ident in answer["kit"] if ident is not None)
        owned = _owned(world, [(ident.split("@")[0], int(ident.split("@")[1]), count) for ident, count in counts.items()])
        kits.append(
            {"name": case["name"], "race": scenario["race"], "evidence": scenario["evidence"], "deity": scenario.get("deity"), "setup": scenario["setup"], "kit": answer["kit"]}
        )
        for role in VIEW_ROLES:
            for buffs in VIEW_BUFFS:
                profile = _profile(world, scenario, role, buffs)
                solution = upgrade.equip_now(profile, owned, scenario["setup"], world.buffsets[buffs], canonical=True)
                assert solution.status == "optimal" and solution.breakdown is not None
                worn = [None if item is None else f"{item.key}@{item.tier}" for item in solution.kit]
                if _arrangement(worn) != _arrangement(answer["kit"]):
                    continue
                value = solution.breakdown.F
                values.append(
                    {
                        "kit": len(kits) - 1,
                        "role": role,
                        "buffs": buffs,
                        "F": f"{value.numerator}/{value.denominator}",
                        "value": float(value),
                        "hasteAssumed": _counted_haste(solution),
                    }
                )
    for index, kit in enumerate(kits):
        views = {(row["role"], row["buffs"]) for row in values if row["kit"] == index}
        if not views:
            raise SystemExit(f"{kit['name']}: the kit is the best arrangement of its own items under no view")
        if index < len(CASES) and len({buffs for _, buffs in views}) < 3:
            raise SystemExit(f"{kit['name']}: the kit is the best arrangement of its own items under too few buff sets ({sorted(views)})")
    return {"trio": SLUG, "level": LEVEL, "kits": kits, "values": values}


def equip_now_text() -> str:
    return json.dumps(answers(), indent=1, ensure_ascii=False) + "\n"


def kit_values_text() -> str:
    return json.dumps(kit_values(), indent=1, ensure_ascii=False) + "\n"


def _view(race: str, role: str, buffs: str, evidence: str, setup: str, **more: str) -> dict[str, str]:
    return {"race": race, "role": role, "buffs": buffs, "evidence": evidence, "setup": setup, **more}


#: the best-kit views: a scenario, a tier and the request's ``weights`` (none: the role's own). The sliders are the positions x0.5 and x2
#: of a group of ``roles.WEIGHT_GROUPS``; ``custom`` and ``regenT`` are the other two options of ``roles.weights_override``. The views are
#: chosen so that the best kit is the same with and without the tie stage, which the browser's answer does not have.
BEST_KIT_CASES: list[dict[str, Any]] = [
    {"name": "an Ogre, tank, own buffs, wiki evidence, dual wield, +4: armor class x2",
     "scenario": _view("OGR", "tank", "own", "wiki", "dw"), "tier": 4, "weights": {"multipliers": {"AC": 2}}},
    {"name": "the same view with armor class x0.5",
     "scenario": _view("OGR", "tank", "own", "wiki", "dw"), "tier": 4, "weights": {"multipliers": {"AC": 0.5}}},
    {"name": "the same view with attack and haste x2",
     "scenario": _view("OGR", "tank", "own", "wiki", "dw"), "tier": 4, "weights": {"multipliers": {"ATK+HASTE": 2}}},
    {"name": "the same view with mana x2",
     "scenario": _view("OGR", "tank", "own", "wiki", "dw"), "tier": 4, "weights": {"multipliers": {"MANA": 2}}},
    {"name": "the same view with regen x2 (the value moves, the kit does not)",
     "scenario": _view("OGR", "tank", "own", "wiki", "dw"), "tier": 4, "weights": {"multipliers": {"regen": 2}}},
    {"name": "an Ogre, tank, own buffs, wiki evidence, one-hander and shield, +0: resists x2 and armor class x0.5",
     "scenario": _view("OGR", "tank", "own", "wiki", "1h-shield"), "tier": 0, "weights": {"multipliers": {"AC": 0.5, "SV": 2}}},
    {"name": "an Iksar, melee, group buffs, strict evidence, two-hander, +4: attack and haste x0.5",
     "scenario": _view("IKS", "melee", "group", "strict", "2h"), "tier": 4, "weights": {"multipliers": {"ATK+HASTE": 0.5}}},
    {"name": "a Troll, tank, group buffs, strict evidence, one-hander and shield, +4: armor class x0.5",
     "scenario": _view("TRL", "tank", "group", "strict", "1h-shield"), "tier": 4, "weights": {"multipliers": {"AC": 0.5}}},
    {"name": "the same view with a custom hit point weight of 3",
     "scenario": _view("TRL", "tank", "group", "strict", "1h-shield"), "tier": 4, "weights": {"custom": {"HP": 3}}},
    {"name": "the same view with regen x2 over a ten-minute window",
     "scenario": _view("TRL", "tank", "group", "strict", "1h-shield"), "tier": 4, "weights": {"multipliers": {"regen": 2}, "regenT": 10}},
    {"name": "an Iksar, tank, raid buffs, wiki evidence, dual wield, +4: armor class x0.5 (the buffs move)",
     "scenario": _view("IKS", "tank", "raid", "wiki", "dw"), "tier": 4, "weights": {"multipliers": {"AC": 0.5}}},
    {"name": "an Iksar, melee, group and the Enchanter's haste, wiki evidence, two-hander, +4: attack and haste x2",
     "scenario": _view("IKS", "melee", "group+enchanter", "wiki", "2h"), "tier": 4, "weights": {"multipliers": {"ATK+HASTE": 2}}},
    {"name": "a Troll, tank, group buffs, wiki evidence, one-hander and shield, +4, a follower of the Tribunal: armor class x2",
     "scenario": _view("TRL", "tank", "group", "wiki", "1h-shield", deity="The Tribunal"), "tier": 4, "weights": {"multipliers": {"AC": 2}}},
    {"name": "an Iksar, tank, raid buffs, wiki evidence, dual wield, +4: the role's own weights",
     "scenario": _view("IKS", "tank", "raid", "wiki", "dw"), "tier": 4},
    {"name": "an Iksar, melee, group and the Enchanter's haste, wiki evidence, two-hander, +4: the role's own weights",
     "scenario": _view("IKS", "melee", "group+enchanter", "wiki", "2h"), "tier": 4},
    {"name": "a Troll, tank, group buffs, wiki evidence, one-hander and shield, +0, a follower of the Tribunal: the role's own weights",
     "scenario": _view("TRL", "tank", "group", "wiki", "1h-shield", deity="The Tribunal"), "tier": 0},
    # the reader's "I have a haste spell": the twin of a buff set keeps the haste of the spells, and the browser's solve with it is Python's solve with the rule haste.assume_spell true
    {"name": "an Ogre, tank, own buffs and a haste spell, wiki evidence, one-hander and shield, +4: the role's own weights",
     "scenario": _view("OGR", "tank", "own+haste", "wiki", "1h-shield"), "tier": 4},
    {"name": "an Iksar, melee, group and the Enchanter's haste and a haste spell, wiki evidence, two-hander, +4: the role's own weights",
     "scenario": _view("IKS", "melee", "group+enchanter+haste", "wiki", "2h"), "tier": 4},
    {"name": "a Troll, tank, raid buffs and a haste spell, wiki evidence, dual wield, +4: armor class x0.5",
     "scenario": _view("TRL", "tank", "raid+haste", "wiki", "dw"), "tier": 4, "weights": {"multipliers": {"AC": 0.5}}},
]  # fmt: skip


def best_kit_answers() -> dict[str, Any]:
    """The best-kit views with Python's answers: the pool of the view, pruned and solved with the tie stage, with the weights of the view.

    The pool is the one the precompute solves (:func:`trioforge.precompute.grid.pool_dicts`: the items of the evidence level that are
    not marked not-for-bis, wearable by a class of the trio, none locked to a deity) at the tier of the view, and with a deity the items
    locked to that deity as well. Everything else is the precompute's solve: the profile of the view, the pruning, the model, the canonical
    solve and the exact value of the kit. The weights are composed by :func:`trioforge.model.roles.weights_override` on the profile's own
    (``mana_reachable`` from the trio's mana pools) and put in the profile before any of it."""
    world = _world()
    out = []
    for case in BEST_KIT_CASES:
        weights = case.get("weights")
        row: dict[str, Any] = {"name": case["name"], "scenario": case["scenario"], "tier": case["tier"]}
        if weights is not None:
            row["weights"] = weights
        row.update(_best_kit_row(world, case["scenario"], case["tier"], weights))
        if weights is not None:
            row["own"] = _best_kit_row(world, case["scenario"], case["tier"], None)
        out.append(row)
    return {"trio": SLUG, "level": LEVEL, "cases": out}


def _composed(profile: Any, weights: Mapping[str, Any] | None) -> Any:
    """The profile with the weights of a request composed on its own by :func:`trioforge.model.roles.weights_override` (``mana_reachable`` from the
    trio's mana pools): the profile itself when there are none."""
    import dataclasses

    from trioforge.model import roles

    if weights is None:
        return profile
    composed = roles.weights_override(
        profile.weights, weights.get("multipliers"), weights.get("custom"), weights.get("regenT"), mana_reachable=bool(profile.pools["MANA"]),
    )  # fmt: skip
    return dataclasses.replace(profile, weights=composed)


def _best_kit_row(
    world: Any, scenario: Mapping[str, Any], tier: int, weights: Mapping[str, Any] | None, weapon_pct: int | None = None
) -> dict[str, Any]:
    """The answer of Python's reference for one best-kit view (see :func:`best_kit_answers`). ``weapon_pct`` is the weapon tier rate (5 or 10; none: the
    rule ``tier.weapon_damage_pct``), which the pool's items are made with (:func:`trioforge.model.items.at_tier`)."""
    from trioforge.model import formulas as fm
    from trioforge.model import items as item_module
    from trioforge.solver import solve as solver_solve
    from trioforge.solver.haste import solve_scenario
    from trioforge.solver.model import BuildOptions, eval_buff_totals
    from trioforge.solver.prune import prune

    options = BuildOptions()
    selection = world.selection
    deity, evidence, buffset = scenario.get("deity"), scenario["evidence"], world.buffsets[scenario["buffs"]]
    levels = ("strict",) if evidence == "strict" else ("strict", "wiki")
    chosen = [
        item for item in selection.items
        if selection.levels[item["key"]] in levels and (item["deity"] is None or (deity is not None and deity in item["deity"]))
    ]  # fmt: skip
    profile = _composed(_profile(world, scenario), weights)  # (the profile is checked against what the browser's bundle assembles)
    pool = [item_module.at_tier(item, tier, world.rules, weapon_pct=weapon_pct) for item in chosen]
    pruned = prune(pool, profile, tier, scenario["setup"], buffset, options)
    found = solve_scenario(profile, pruned, scenario["setup"], buffset, options)
    milp, solution = found.milp, found.solution
    assert solution.status == "optimal" and solution.kit is not None
    plain = solve_scenario(profile, pruned, scenario["setup"], buffset, options, solver=solver_solve.solve).solution
    assert [i and (i.key, i.tier) for i in plain.kit] == [i and (i.key, i.tier) for i in solution.kit] and plain.buffs == solution.buffs, (
        "the best kit depends on the tie stage"
    )  # fmt: skip
    kit = list(solution.kit)
    totals = eval_buff_totals(buffset.totals(solution.buffs))
    value = fm.evaluate(profile.eval_profile, kit, totals, setup=scenario["setup"], haste_assumed=milp.haste_assumed).F
    return {
        "F": f"{value.numerator}/{value.denominator}",
        "value": float(value),
        "kit": [None if item is None else f"{item.key}@{item.tier}" for item in kit],
        "buffs": list(solution.buffs),
        "hasteAssumed": milp.haste_assumed,
    }


def best_kit_text(document: dict[str, Any] | None = None) -> str:
    return json.dumps(best_kit_answers() if document is None else document, indent=1, ensure_ascii=False) + "\n"


# ---- the weapon tier rate ---------------------------------------------------------------------------------------------------------------

#: the weapon tier rates a request may name (percent of damage a tier)
WEAPON_RATES = (5, 10)

#: the views of the weapon tier rate: a scenario, a tier and, for one of them, weights. The weapons of the invented catalog are a two-hander (36 damage), a dual-wield pair,
#: a one-hander for the shield setup and a piercing weapon, so that the rate moves a value and, for some views, the kit. At +0 no weapon has grown and the rate is not read.
WEAPON_RATE_CASES: list[dict[str, Any]] = [
    {"name": "an Iksar, melee, group buffs, wiki evidence, two-hander, +10",
     "scenario": _view("IKS", "melee", "group", "wiki", "2h"), "tier": 10},
    {"name": "an Iksar, melee, group buffs, wiki evidence, two-hander, +4",
     "scenario": _view("IKS", "melee", "group", "wiki", "2h"), "tier": 4},
    {"name": "an Ogre, tank, own buffs, wiki evidence, dual wield, +10",
     "scenario": _view("OGR", "tank", "own", "wiki", "dw"), "tier": 10},
    {"name": "an Ogre, tank, own buffs, wiki evidence, dual wield, +4",
     "scenario": _view("OGR", "tank", "own", "wiki", "dw"), "tier": 4},
    {"name": "a Troll, tank, group buffs, wiki evidence, one-hander and shield, +10",
     "scenario": _view("TRL", "tank", "group", "wiki", "1h-shield"), "tier": 10},
    {"name": "an Ogre, tank, own buffs, wiki evidence, dual wield, +10: attack and haste x2",
     "scenario": _view("OGR", "tank", "own", "wiki", "dw"), "tier": 10, "weights": {"multipliers": {"ATK+HASTE": 2}}},
    {"name": "a Troll, tank, group buffs, wiki evidence, one-hander and shield, +4: attack and haste x0.5 (the kit moves with the rate)",
     "scenario": _view("TRL", "tank", "group", "wiki", "1h-shield"), "tier": 4, "weights": {"multipliers": {"ATK+HASTE": 0.5}}},
    {"name": "an Ogre, melee, own buffs, wiki evidence, dual wield, +10: an attack weight of 0.5 (the kit moves with the rate)",
     "scenario": _view("OGR", "melee", "own", "wiki", "dw"), "tier": 10, "weights": {"custom": {"ATK": 0.5}}},
    {"name": "an Ogre, tank, own buffs, wiki evidence, dual wield, +0 (no weapon has grown: the rate is not read)",
     "scenario": _view("OGR", "tank", "own", "wiki", "dw"), "tier": 0},
]  # fmt: skip


def weapon_rate_answers() -> dict[str, Any]:
    """The weapon-rate views with Python's answers (:func:`_best_kit_row`) at each rate, and with the rate left to the rules (``rules``)."""
    world = _world()
    out = []
    for case in WEAPON_RATE_CASES:
        weights = case.get("weights")
        row: dict[str, Any] = {"name": case["name"], "scenario": case["scenario"], "tier": case["tier"]}
        if weights is not None:
            row["weights"] = weights
        row["rates"] = {str(rate): _best_kit_row(world, case["scenario"], case["tier"], weights, weapon_pct=rate) for rate in WEAPON_RATES}
        row["rules"] = _best_kit_row(world, case["scenario"], case["tier"], weights)
        out.append(row)
    return {"trio": SLUG, "level": LEVEL, "cases": out}


def weapon_rate_text(document: dict[str, Any] | None = None) -> str:
    return json.dumps(weapon_rate_answers() if document is None else document, indent=1, ensure_ascii=False) + "\n"


# ---- the Upgrade modes under weights ------------------------------------------------------------------------------------------------------

#: the text every seed of a weighted case begins with; the rest is the place of the scenario in ``CASES`` and the number of the draw
WEIGHTED_SEED = "trioforge-weights"
#: how many weighted cases each Equip now scenario has, and the most draws looked at for them (a draw is skipped when its answers depend on the tie stage, which the browser has none of)
WEIGHTED_PER_SCENARIO = 2
WEIGHTED_DRAWS = 60
#: the farm path's steps, the swaps a place of Every slot lists, and the tier modes the weighted cases are given in turn
PATH_STEPS = 3
SLOT_LIMIT = 3
TIER_MODES: list[dict[str, Any]] = [{"mode": "ready4"}, {"mode": "arrives", "D": 2}, {"mode": "fixed", "N": 6}]
#: what a draw picks from: the two slider positions that are not the role's own, custom weights and regen windows (every number is one the protocol takes)
SLIDER_POSITIONS = (0.5, 2)
CUSTOM_VALUES = (0, 0.25, 0.5, 1.5, 3, 7.5, 12.5, 40)
REGEN_WINDOWS = (1, 5, 10, 20, 60)


class _Unsteady(Exception):
    """A draw that is not a case: an answer of it depends on the tie stage (or its weights leave Equip now as it was)."""


def draw_weights(seed: str) -> dict[str, Any]:
    """The weights of one draw, a function of its ``seed`` text alone: two to four slider groups at x0.5 or x2 (a group at x1 is the role's own and is left out), in
    half of the draws one or two custom weights, and in two of five a regen window. Every number is zero or at least 0.000001 with at most 6 significant digits (the
    rule of the protocol), and the options are those of ``roles.weights_override``, as a request carries them."""
    import random

    from trioforge.model import roles

    rng = random.Random(seed)
    groups = list(roles.WEIGHT_GROUPS)
    picked = sorted(rng.sample(groups, rng.randint(2, 4)), key=groups.index)
    weights: dict[str, Any] = {"multipliers": {group: rng.choice(SLIDER_POSITIONS) for group in picked}}
    if rng.random() < 0.5:
        keys = list(roles.CUSTOM_KEYS)
        weights["custom"] = {key: rng.choice(CUSTOM_VALUES) for key in sorted(rng.sample(keys, rng.randint(1, 2)), key=keys.index)}
    if rng.random() < 0.4:
        weights["regenT"] = rng.choice(REGEN_WINDOWS)
    return weights


def _describe(weights: Mapping[str, Any]) -> str:
    parts = [f"{group} x{factor}" for group, factor in weights["multipliers"].items()]
    parts += [f"{key} = {value}" for key, value in weights.get("custom", {}).items()]
    if "regenT" in weights:
        parts.append(f"regen window {weights['regenT']} min")
    return ", ".join(parts)


def _kit_idents(kit: Any) -> list[str | None]:
    return [None if item is None else f"{item.key}@{item.tier}" for item in kit]


def _exact_text(value: Any) -> str:
    return f"{value.numerator}/{value.denominator}"


def _same(left: Any, right: Any) -> bool:
    """Whether two solutions (of the tie stage and of a plain solve) are one answer: the exact value, the kit place for place and the buffs."""
    return left.breakdown.F == right.breakdown.F and _kit_idents(left.kit) == _kit_idents(right.kit) and tuple(left.buffs) == tuple(right.buffs)


def _candidates(world: Any, scenario: Mapping[str, Any], mode: Mapping[str, Any]) -> list[Any]:
    """The candidates of the worker for a scenario and a tier mode: the items of the evidence level that the precompute offers (``select_items``: not marked not-for-bis,
    wearable by a class of the trio; the deity-locked ones too, as ``Context.candidates`` keeps them), each at the tier of the mode."""
    from trioforge import upgrade

    wanted = ("strict",) if scenario["evidence"] == "strict" else ("strict", "wiki")
    items = [item for item in world.selection.items if world.selection.levels[item["key"]] in wanted]
    return upgrade.scored_candidates(items, mode["mode"], world.rules, mode.get("D", 4), mode.get("N"))


def _recorded_procs(breakdown: Any) -> dict[str, Any]:
    """The proc each hand counts in a breakdown, as ``[effect id, donor key, mode, value]`` (the donor a proc records is the item whose copy supplies it), or None for a hand that counts none."""
    from fractions import Fraction

    counted = breakdown.totals["procs"]
    return {
        hand: None if counted[hand] is None else [counted[hand].effect, counted[hand].donor, counted[hand].mode, _exact_text(Fraction(counted[hand].value))] for hand in ("PRIMARY", "SECONDARY")
    }


def _weighted_case(
    world: Any, base: Mapping[str, Any], weights: Mapping[str, Any] | None, mode: Mapping[str, Any], options: Any = None
) -> dict[str, Any]:
    """The answers of Python's reference for one scenario of ``CASES`` under ``weights`` and a tier mode (see the head of this file): every solve is made with the tie
    stage and again without it, and an answer that differs is an :class:`_Unsteady` (the browser has no tie stage). ``weights`` None leaves the role's own, and ``options`` (the builder's
    :class:`~trioforge.solver.model.BuildOptions`, None: the defaults) carries a table of procs for the family of the fixture that has one (:func:`proc_family_answers`)."""
    from trioforge import upgrade

    scenario = base["scenario"]
    setup, buffset = scenario["setup"], world.buffsets[scenario["buffs"]]
    own_profile = _profile(world, scenario)
    profile = _composed(own_profile, weights)
    owned = _owned(world, base["owned"])
    offered = _candidates(world, scenario, mode)

    def both(make: Any) -> Any:
        first, second = make(True), make(False)
        if not _same(first, second):
            raise _Unsteady
        return first

    equip = both(lambda canonical: upgrade.equip_now(profile, owned, setup, buffset, options, canonical=canonical))
    if weights is not None and equip.breakdown.F == upgrade.equip_now(own_profile, owned, setup, buffset, options, canonical=False).breakdown.F:
        raise _Unsteady
    start = equip  # (the path starts from Equip now)
    path = upgrade.farm_path(profile, owned, offered, setup, buffset, PATH_STEPS, options, canonical=True)
    plain = upgrade.farm_path(profile, owned, offered, setup, buffset, PATH_STEPS, options, canonical=False)
    if [(s.item, s.kind, s.source_tier, s.F, _kit_idents(s.solution.kit), s.solution.buffs) for s in path] != [
        (s.item, s.kind, s.source_tier, s.F, _kit_idents(s.solution.kit), s.solution.buffs) for s in plain
    ]:
        raise _Unsteady
    sets = []
    for k in (2, 3):
        found = upgrade.best_sets(profile, owned, offered, k, setup, buffset, options, canonical=True)
        alone = upgrade.best_sets(profile, owned, offered, k, setup, buffset, options, canonical=False)
        if found.acquisitions != alone.acquisitions or not _same(found.solution, alone.solution):
            raise _Unsteady
        sets.append(
            {
                "k": k,
                "acquired": [
                    {"ident": f"{a.item.key}@{a.item.tier}", "kind": a.kind, "sourceTier": a.source_tier} for a in found.acquisitions
                ],
                "F": _exact_text(found.F),
                "value": float(found.F),
                "gain": _exact_text(found.gain),
                "gainValue": float(found.gain),
                "kit": _kit_idents(found.solution.kit),
                "buffs": list(found.solution.buffs),
                "baseline": {"F": _exact_text(found.F - found.gain), "value": float(found.F - found.gain)},
                "hasteAssumed": found.haste_assumed,
            }
        )
    rows = upgrade.every_slot(profile, equip, offered, setup, buffset, options, buffs=equip.buffs, limit=SLOT_LIMIT, owned=owned)
    return {
        "name": f"{base['name']}: {_describe(weights) if weights is not None else 'the role own weights'}",
        "scenario": scenario,
        "owned": [[f"{key}@{tier}", count] for key, tier, count in base["owned"]],
        "weights": weights,
        "tierMode": mode,
        "equipNow": {
            "F": _exact_text(equip.breakdown.F),
            "value": float(equip.breakdown.F),
            "kit": _kit_idents(equip.kit),
            "buffs": list(equip.buffs),
            "hasteAssumed": _counted_haste(equip),
            **({} if options is None or options.procs is None else {"procs": _recorded_procs(equip.breakdown)}),
        },
        "farmPath": {
            "steps": PATH_STEPS,
            "start": {"F": _exact_text(start.breakdown.F), "value": float(start.breakdown.F), "kit": _kit_idents(start.kit), "buffs": list(start.buffs)},
            "path": [
                {
                    "ident": f"{step.item.key}@{step.item.tier}",
                    "kind": step.kind,
                    "sourceTier": step.source_tier,
                    "F": _exact_text(step.F),
                    "value": float(step.F),
                    "gain": _exact_text(step.gain),
                    "gainValue": float(step.gain),
                    "kit": _kit_idents(step.solution.kit),
                    "buffs": list(step.solution.buffs),
                    "hasteAssumed": step.haste_assumed,
                }
                for step in path
            ],
            "stopped": "limit" if len(path) == PATH_STEPS else "no-gain",
        },
        "bestSets": sets,
        "everySlot": {
            "limit": SLOT_LIMIT,
            "kit": _kit_idents(equip.kit),
            "buffs": list(equip.buffs),
            "rows": [
                {
                    "place": row.place,
                    "index": row.index,
                    "current": None if row.current is None else f"{row.current.key}@{row.current.tier}",
                    "swaps": [
                        {"ident": f"{swap.item.key}@{swap.item.tier}", "delta": _exact_text(swap.delta), "deltaValue": float(swap.delta)}
                        for swap in row.swaps
                    ],
                }
                for row in rows
            ],
        },
    }


def weighted_answers() -> dict[str, Any]:
    """The weighted cases: for each scenario of ``CASES``, the first ``WEIGHTED_PER_SCENARIO`` draws of ``draw_weights`` whose answers do not depend on the tie stage
    (the draw's number is in its seed), the tier modes in turn, each with Python's answers in all four modes (:func:`_weighted_case`)."""
    world = _world()
    out: list[dict[str, Any]] = []
    for index, base in enumerate(CASES):
        accepted = 0
        for draw in range(WEIGHTED_DRAWS):
            seed = f"{WEIGHTED_SEED}:{index}:{draw}"
            weights = draw_weights(seed)
            try:
                case = _weighted_case(world, base, weights, TIER_MODES[(index + accepted) % len(TIER_MODES)])
            except _Unsteady:
                continue
            out.append({**case, "seed": seed})
            accepted += 1
            if accepted == WEIGHTED_PER_SCENARIO:
                break
        else:
            raise SystemExit(f"{base['name']}: only {accepted} of {WEIGHTED_PER_SCENARIO} weighted cases in {WEIGHTED_DRAWS} draws")
    return {"trio": SLUG, "level": LEVEL, "cases": out}


def weighted_text(document: dict[str, Any] | None = None) -> str:
    return json.dumps(weighted_answers() if document is None else document, indent=1, ensure_ascii=False) + "\n"


#: the view and the owned set the Upgrade test gives the page: the default view of the trio page, and the items of fixtures/dumps/site-small.txt as the page reads them, as (key, tier, count)
UPGRADE_VIEW_SCENARIO = {"race": "OGR", "role": "tank", "buffs": "own", "evidence": "strict", "setup": "dw"}
UPGRADE_VIEW_OWNED = [
    ("w80631", 4, 1), ("w90020", 0, 1), ("w90029", 4, 1), ("w90011", 0, 1), ("w90023", 1, 1), ("w90001", 4, 2),
    ("w8091", 4, 1), ("w90006", 0, 1), ("w80113", 3, 1), ("w90007", 2, 2), ("w80923", 0, 1), ("w90014", 1, 1),
]  # fmt: skip
UPGRADE_VIEW_STEPS = 3


def upgrade_view_answers() -> dict[str, Any]:
    """Equip now and the first steps of the farm path (ready4) for the view and the gear of the Upgrade test, as Python's reference gives them, with and without the tie stage."""
    from trioforge import upgrade

    world = _world()
    scenario = UPGRADE_VIEW_SCENARIO
    profile = _profile(world, scenario)
    buffset = world.buffsets[scenario["buffs"]]
    owned = _owned(world, UPGRADE_VIEW_OWNED)
    mode = {"mode": "ready4"}
    offered = _candidates(world, scenario, mode)
    equip = upgrade.equip_now(profile, owned, scenario["setup"], buffset, canonical=True)
    plain_equip = upgrade.equip_now(profile, owned, scenario["setup"], buffset, canonical=False)
    assert equip.status == "optimal" and equip.breakdown is not None and _same(equip, plain_equip), "Equip now depends on the tie stage"
    path = upgrade.farm_path(profile, owned, offered, scenario["setup"], buffset, UPGRADE_VIEW_STEPS, canonical=True)
    plain = upgrade.farm_path(profile, owned, offered, scenario["setup"], buffset, UPGRADE_VIEW_STEPS, canonical=False)
    key = lambda s: (s.item, s.kind, s.source_tier, s.F, _kit_idents(s.solution.kit), s.solution.buffs)  # noqa: E731
    assert [key(s) for s in path] == [key(s) for s in plain], "the farm path depends on the tie stage"
    return {
        "trio": SLUG,
        "level": LEVEL,
        "scenario": scenario,
        "owned": [[f"{k}@{t}", c] for k, t, c in UPGRADE_VIEW_OWNED],
        "tierMode": mode,
        "equipNow": {"F": _exact_text(equip.breakdown.F), "value": float(equip.breakdown.F), "kit": _kit_idents(equip.kit), "buffs": list(equip.buffs), "hasteAssumed": _counted_haste(equip)},
        "path": [
            {
                "ident": f"{step.item.key}@{step.item.tier}",
                "kind": step.kind,
                "sourceTier": step.source_tier,
                "F": _exact_text(step.F),
                "value": float(step.F),
                "gain": _exact_text(step.gain),
                "gainValue": float(step.gain),
                "kit": _kit_idents(step.solution.kit),
                "buffs": list(step.solution.buffs),
                "hasteAssumed": step.haste_assumed,
            }
            for step in path
        ],
    }  # fmt: skip


def upgrade_view_text(document: dict[str, Any] | None = None) -> str:
    return json.dumps(upgrade_view_answers() if document is None else document, indent=1, ensure_ascii=False) + "\n"


# ---- the mote order --------------------------------------------------------------------------------------------------------------------------

#: how many motes the long orders are cut at (a full order of an Equip now kit has a hundred steps and more, each with twenty evaluations)
MOTE_LIMIT = 40
WEIGHTED_MOTE_LIMIT = 30
PUBLISHED_TIER = 4


def _exact_moved(moved: Any) -> list[list[str]]:
    return [[name, _exact_text(amount)] for name, amount in moved]


#: invented items for the runs, which no shard shows: a dagger of damage five (its damage rises every second tier), an ear of 25 haste and a neck of 20 (the haste that counts is the best worn one,
#: so the ear is worth a mote only once it passes the neck: six motes from +0 when the neck is at +10). Their keys are not a catalog key, and their names are made up.
MOTE_EXTRAS: list[dict[str, Any]] = [
    {"key": "w91001", "name": "Prop Dagger of the Plateau", "slots": ["PRIMARY", "SECONDARY"], "stats": {}, "weapon": ("1H Piercing", 5, 20, None)},
    {"key": "w91002", "name": "Prop Earloop of the Overtake", "slots": ["EAR"], "stats": {"HASTE": 25}},
    {"key": "w91003", "name": "Prop Neckchain of the Overtake", "slots": ["NECK"], "stats": {"HASTE": 20}},
]


def mote_extra_catalog() -> list[dict[str, Any]]:
    """The catalog items of :data:`MOTE_EXTRAS` (the Python reference works from these) in the form of the catalog."""
    from test_precompute import make_item, weapon

    return [
        make_item(item["key"], item["name"], item["slots"], stats=item["stats"], weight=1.0, weapon=None if "weapon" not in item else weapon(*item["weapon"]), level="wiki", tier_rule="drop")
        for item in MOTE_EXTRAS
    ]


def mote_extra_records() -> list[dict[str, Any]]:
    """The same items as records of the item table, which the browser tests add to the fixture's table (the table the page and the worker have does not hold them)."""
    from trioforge.export import browser
    from trioforge.model.tables import load

    document = {"version": VERSION, "license": "CC BY-SA 4.0", "attribution": "invented", "provenance": {}, "items": mote_extra_catalog()}
    return browser.items(document, load().rules)["items"]


def mote_cases() -> list[dict[str, Any]]:
    """The cases of :func:`mote_orders`: for each, the scenario, the weights, the kit as idents, the optional buffs the kit is valued with, the limit of motes (``null``: to
    the end) and the order."""
    from trioforge import motes, upgrade
    from trioforge.export import browser
    from trioforge.model import items as item_module

    world = _world()
    catalog = {key: browser.item_to_catalog(record, world.table["defaults"]) for key, record in world.records.items()}
    catalog.update({item["key"]: item for item in mote_extra_catalog()})
    equip = answers()["cases"]
    small = []
    for case in KIT_ONLY:
        scenario = case["scenario"]
        solution = upgrade.equip_now(_profile(world, scenario), _owned(world, case["owned"]), scenario["setup"], world.buffsets[scenario["buffs"]], canonical=True)
        assert solution.status == "optimal" and solution.breakdown is not None
        small.append({"kit": _kit_idents(solution.kit), "buffs": list(solution.buffs)})

    def retier(kit: list[str | None], tier: int) -> list[str | None]:
        return [None if ident is None else f"{ident.rsplit('@', 1)[0]}@{tier}" for ident in kit]

    cases: list[dict[str, Any]] = []

    def add(
        name: str, scenario: Mapping[str, Any], kit: list[str | None], buffs: list[int], limit: int | None, weights: Mapping[str, Any] | None = None
    ) -> None:
        here = world
        profile = _composed(_profile(here, scenario), weights)
        worn = [None if ident is None else item_module.at_tier(catalog[ident.rsplit("@", 1)[0]], int(ident.rsplit("@", 1)[1]), here.rules) for ident in kit]
        order = motes.mote_order(profile, worn, catalog, here.rules, scenario["setup"], here.buffsets[scenario["buffs"]], buffs, limit)
        cases.append(
            {
                "name": name, "scenario": dict(scenario), **({"weights": weights} if weights is not None else {}),
                "kit": kit, "buffs": buffs, "motes": limit,
                "start": _exact_text(order.start), "ending": order.ending, "left": order.left, "spent": order.spent, "nextRun": order.next_run,
                "steps": [
                    {
                        "index": s.index, "place": s.place, "key": s.key, "from": s.from_tier, "to": s.to_tier, "motes": s.motes, "spent": s.spent, "gain": _exact_text(s.gain),
                        "F": _exact_text(s.F), "moved": _exact_moved(s.moved),
                    }
                    for s in order.steps
                ],
            }
        )  # fmt: skip

    for case, answer in zip(CASES, equip, strict=True):
        add(f"Equip now's kit, {MOTE_LIMIT} motes: {case['name']}", case["scenario"], answer["kit"], answer["buffs"], MOTE_LIMIT)
    for case, kit in zip(KIT_ONLY, small, strict=True):
        add(f"the whole order of a small kit: {case['name']}", case["scenario"], kit["kit"], kit["buffs"], None)
    # the hoop of haste of the second small kit is worn under the raid's 70 spell haste, which leaves 15 of the cap: it counts in full at +0, so its motes add nothing but the
    # agility it gives, and with no weight on armor class or endurance (nothing else reads agility) they add nothing at all: the order ends with the motes it could still spend.
    # The rule haste.assume_spell leaves the spell haste out of the buffs, so this case is worked out with the twin of the raid set (``raid+haste``: the browser's "I have a haste spell")
    past_cap = {**KIT_ONLY[1]["scenario"], "buffs": "raid+haste"}
    kit_hasty = upgrade.equip_now(_profile(world, past_cap), _owned(world, KIT_ONLY[1]["owned"]), past_cap["setup"], world.buffsets[past_cap["buffs"]], canonical=True)
    assert kit_hasty.status == "optimal" and kit_hasty.breakdown is not None
    add(f"a hoop past the haste cap under the spells' haste, no weight on armor class or endurance: {KIT_ONLY[1]['name']}", past_cap, _kit_idents(kit_hasty.kit), list(kit_hasty.buffs), None,
        {"multipliers": {}, "custom": {"AC": 0, "END": 0}})  # fmt: skip
    # an extra: a kit under weights that value nothing (every settable weight 0): no mote adds anything, and the order ends at once with the motes it could still spend
    nothing = {key: 0 for key in ("HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "CHA", "SV")}
    add(f"weights that value nothing, so no mote adds anything: {KIT_ONLY[1]['name']}", KIT_ONLY[1]["scenario"], small[1]["kit"], small[1]["buffs"], None,
        {"multipliers": {}, "custom": nothing})  # fmt: skip
    for index, (case, answer) in enumerate(zip(CASES, equip, strict=True)):
        weights = draw_weights(f"{WEIGHTED_SEED}:{index}:0")
        add(f"under drawn weights, {WEIGHTED_MOTE_LIMIT} motes: {case['name']}", case["scenario"], answer["kit"], answer["buffs"], WEIGHTED_MOTE_LIMIT, weights)
    # the kit the fixture's baked trio page shows (its default view, the published row of the shard): the kit a visitor sees in Wear this, at the tier of the view, valued under the view with the
    # best optional buffs for it (the optimum of Python's solve with the kit as the owned set, which the page's own exact search finds too)
    baked = json.loads((TRIO_FOLDER / "defaults.json").read_text(encoding="utf-8"))
    view = baked["view"]
    shard = json.loads((TRIO_FOLDER / f"{view['evidence']}-{view['buffs']}.json").read_text(encoding="utf-8"))
    row = next(r for r in shard["scenarios"] if r[:4] == [baked["race"], view["role"], view["tier"], baked["setup"]])
    page_scenario = {"race": baked["race"], "role": view["role"], "buffs": view["buffs"], "evidence": view["evidence"], "setup": baked["setup"]}
    page_kit = [None if index < 0 else f"{shard['items'][index][0]}@{view['tier']}" for index in shard["kits"][row[4]]]
    held = _owned(world, [(ident.rsplit("@", 1)[0], view["tier"], 1) for ident in page_kit if ident is not None])
    best = upgrade.equip_now(_profile(world, page_scenario), held, page_scenario["setup"], world.buffsets[page_scenario["buffs"]], canonical=True)
    add("the best kit of the fixture's baked page, as Wear this shows it", page_scenario, page_kit, list(best.buffs), None)
    # the kit Equip now finds for the gear that the browser test gives the page (the dump fixtures/dumps/site-small.txt, in the page's default view): the kit the panel is given
    gear = upgrade.equip_now(_profile(world, UPGRADE_VIEW_SCENARIO), _owned(world, UPGRADE_VIEW_OWNED), UPGRADE_VIEW_SCENARIO["setup"], world.buffsets[UPGRADE_VIEW_SCENARIO["buffs"]], canonical=True)
    assert gear.status == "optimal" and gear.breakdown is not None
    add("the kit Equip now finds for the gear of the browser test", UPGRADE_VIEW_SCENARIO, _kit_idents(gear.kit), list(gear.buffs), MOTE_LIMIT)
    # runs: the damage of the dagger rises every second tier, so its motes come in twos (after the head piece, which gains at every tier); the ear passes the neck's haste only at +6, so its first
    # run is six motes, then one at a time; and with few motes the run that does not fit is said, not taken
    ogre = CASES[0]["scenario"]
    ogre_buffs = equip[0]["buffs"]

    def placed(**tiers: tuple[str, int]) -> list[str | None]:
        order_of = {"HEAD": 0, "EAR": 2, "NECK": 4, "PRIMARY": 20}  # (the places of the kit by index)
        kit: list[str | None] = [None] * 22
        for place, (key, tier) in tiers.items():
            kit[order_of[place]] = f"{key}@{tier}"
        return kit

    add("a dagger of damage five, whose damage rises every second tier, and a head piece", ogre, placed(PRIMARY=("w91001", 0), HEAD=("w90001", 4)), ogre_buffs, None)
    overtake = placed(EAR=("w91002", 0), NECK=("w91003", 10))
    add("an ear of 25 haste behind a neck of 20 haste at +10", ogre, overtake, ogre_buffs, None)
    add("the same, with eight motes", ogre, overtake, ogre_buffs, 8)
    add("the same, with three motes: the run of six does not fit", ogre, overtake, ogre_buffs, 3)
    add("a head piece, the ear and the neck, with three motes: the head piece takes them, the run of six does not fit", ogre, placed(HEAD=("w90001", 4), EAR=("w91002", 0), NECK=("w91003", 10)), ogre_buffs, 3)
    # (E7) the run of the best rate is not the shortest: a weight of 1000 on haste makes the ear's run of six the better rate, and the dagger's run of two is the shortest; with one mote nothing fits,
    # and the order says how many motes the shortest run needs (two), where it used to name the run of the best rate (six)
    add("the dagger, the ear and the neck under a heavy weight on haste, with one mote: the shortest run is the one the order names", ogre, placed(PRIMARY=("w91001", 0), EAR=("w91002", 0), NECK=("w91003", 10)), ogre_buffs, 1,
        {"multipliers": {}, "custom": {"HASTE": 1000}})  # fmt: skip
    first, second, third = equip[:3]  # (the cases beyond them are the Equip now cases with a haste spell: the motes orders do not need them)
    add(f"a published-style kit, every item at +{PUBLISHED_TIER}: {CASES[0]['name']}", CASES[0]["scenario"], retier(first["kit"], PUBLISHED_TIER), first["buffs"], WEIGHTED_MOTE_LIMIT)
    add(f"every item a tier from the top: {CASES[1]['name']}", CASES[1]["scenario"], retier(second["kit"], 9), second["buffs"], None)
    add(f"every item at the top: {CASES[2]['name']}", CASES[2]["scenario"], retier(third["kit"], 10), third["buffs"], None)
    return cases


def mote_orders() -> dict[str, Any]:
    """The mote orders of Python's reference (see the head of this file), with every ending in them."""
    cases = mote_cases()
    endings = {case["ending"] for case in cases}
    if endings != {"top", "motes", "no-gain"}:
        raise SystemExit(f"the mote orders end in {sorted(endings)}, not in each of top, motes and no-gain: change the cases")
    return {"trio": SLUG, "level": LEVEL, "extra": mote_extra_records(), "cases": cases}


def mote_orders_text(document: dict[str, Any] | None = None) -> str:
    return json.dumps(mote_orders() if document is None else document, indent=1, ensure_ascii=False) + "\n"


# ---- the family with procs (F6) ------------------------------------------------------------------------------------------------------------------

#: The bundle of every other file of the fixture holds no table of procs (``"procs": null``): the browser's weapon term, mote order and Upgrade answers with procs were held to nothing. This family is
#: the same invented catalog and a Lore weapon, with a table of invented procs in the bundle (``fixtures/site/results-procs``: the bundle and the item table) and Python's answers with that table
#: (``fixtures/site/procs-family.json``): Equip now, a farm path, the best 2 and 3 sets and Every slot (``_weighted_case`` with the table in the options and the role's own weights) and the mote
#: order of Equip now's kits and of a weapon one mote short of the socket tier, where the proc it counts jumps from its own to the best it can host. Every name and number is invented.
#: (G4) the fifth effect, Prop Gust, is carried by the Lore weapon FAMILY_LORE_WEAPON, which fits either hand and is the best proc of the table: a kit that wears the one copy in a hand cannot have the
#: other hand host it, which the recorded donors show. (H3) The sixth, Prop Squall (9,200), is carried by the Lore weapon too and by the plain FAMILY_PLAIN_WEAPON, whose key is the larger: the other
#: hand of that kit records Prop Squall from the plain weapon, not from the smallest key of its donors (the Lore weapon's, whose one copy is worn).
PROC_EFFECTS = (
    ("e-prop-rime", "Prop Rime", 700), ("e-prop-ember", "Prop Ember", 2400), ("e-prop-venom", "Prop Venom", 4100), ("e-prop-tumble", "Prop Tumble", 9000), ("e-prop-squall", "Prop Squall", 9200),
    ("e-prop-gust", "Prop Gust", 9500),
)  # fmt: skip
PROC_DONORS = (  # (effect, item key, slots, fits the primary hand only, a Lore item)
    ("e-prop-rime", "w80113", ("PRIMARY", "SECONDARY"), False, False),
    ("e-prop-ember", "w80923", ("PRIMARY",), True, False),
    ("e-prop-venom", "w80988", ("PRIMARY",), True, False),
    ("e-prop-tumble", "w80524", ("PRIMARY",), True, False),
    ("e-prop-gust", "w91101", ("PRIMARY", "SECONDARY"), False, True),
    ("e-prop-squall", "w91101", ("PRIMARY", "SECONDARY"), False, True),  # (H3: the Lore weapon carries a second effect, which a plain weapon with a larger key carries as well)
    ("e-prop-squall", "w91102", ("PRIMARY", "SECONDARY"), False, False),
)
PROC_CASES = (0, 1, 2)  # the scenarios of CASES it answers (dual wield, one-hander and shield, two-hander)
#: (G4) dual wield with the Lore weapon owned once and the mace once, at +4: the kit wears the Lore weapon in the off hand (its own proc, Prop Gust) and the main hand hosts the best proc that is left
#: (Prop Tumble), where a kit that did not know the rule would have both hands count Prop Gust.
LORE_CASE: dict[str, Any] = {
    "name": "an Ogre, tank, own buffs, wiki evidence, dual wield, with the Lore weapon",
    "scenario": {"race": "OGR", "role": "tank", "buffs": "own", "evidence": "wiki", "setup": "dw"},
    "owned": [item for item in CASES[0]["owned"] if item[0] not in ("w80988", "w80113", "w80923", "w80524")] + [("w91101", 4, 1), ("w80113", 4, 1)],
}


def proc_table() -> Any:
    """The table of invented procs: five effects on the four weapons of the fixture and the Lore weapon of the family, the socket tier of the rules (+4)."""
    from fractions import Fraction

    from trioforge.model.procs import ProcDonor, ProcEffect, ProcTable

    effects = tuple(ProcEffect(effect, name, Fraction(value)) for effect, name, value in PROC_EFFECTS)
    donors = tuple(ProcDonor(effect, key, frozenset(slots), frozenset(TRIO), only, lore) for effect, key, slots, only, lore in PROC_DONORS)
    return ProcTable(TRIO, 4, effects, donors)


def proc_bundle() -> dict[str, Any]:
    """The bundle of the family: the fixture's catalog and the Lore weapon, with the table of procs in it (the inputs fingerprint is that of the family's own item table: the table of procs is not an input of it)."""
    from trioforge.export import browser
    from trioforge.model.tables import REPO as ROOT
    from trioforge.model.tables import load

    tables = load()
    spells = json.loads((ROOT / "derived" / "client" / f"spells-l{LEVEL}.json").read_text(encoding="utf-8"))
    made = browser.bundle(TRIO, LEVEL, tables, tables.rules, spells, data_release=f"data-{VERSION}", catalog=catalog(True), procs=proc_table())
    return browser.with_inputs(made, documents(True)[0]["inputs"])


def proc_bundle_text() -> str:
    from trioforge.export import browser

    return browser.render_bundle(proc_bundle())


def proc_items_text() -> str:
    """The item table of the family: the fixture's, and the Lore weapon."""
    from trioforge.export import browser

    return browser.render_items(documents(True)[1])


def proc_family_answers() -> dict[str, Any]:
    """Python's answers with the table of procs (see above): ``{trio, level, procs, cases, motes}``. A case is :func:`_weighted_case` with the role's own weights and the table in the options."""
    from trioforge import motes, upgrade
    from trioforge.export import browser
    from trioforge.model import items as item_module
    from trioforge.solver.model import BuildOptions

    world = _world(family=True)
    options = BuildOptions(procs=proc_table())
    cases = []
    for number, (index, base) in enumerate([*((i, CASES[i]) for i in PROC_CASES), (0, LORE_CASE)]):
        case = _weighted_case(world, base, None, TIER_MODES[number % len(TIER_MODES)], options)
        scenario = base["scenario"]
        without = upgrade.equip_now(_profile(world, scenario), _owned(world, base["owned"]), scenario["setup"], world.buffsets[scenario["buffs"]], canonical=False)
        case["withoutProcs"] = {"F": _exact_text(without.breakdown.F), "kit": _kit_idents(without.kit)}
        if _exact_text(without.breakdown.F) == case["equipNow"]["F"]:
            raise SystemExit(f"{base['name']}: the table of procs does not move Equip now: change the procs")
        cases.append({"index": index, **({"variant": "lore"} if base is LORE_CASE else {}), **case})
    records = {key: browser.item_to_catalog(record, world.table["defaults"]) for key, record in world.records.items()}
    mote_cases: list[dict[str, Any]] = []

    def add(name: str, scenario: Mapping[str, Any], kit: list[str | None], buffs: list[int], limit: int | None) -> None:
        profile = _profile(world, scenario)
        worn = [None if ident is None else item_module.at_tier(records[ident.rsplit("@", 1)[0]], int(ident.rsplit("@", 1)[1]), world.rules) for ident in kit]
        buffset = world.buffsets[scenario["buffs"]]
        order = motes.mote_order(profile, worn, records, world.rules, scenario["setup"], buffset, buffs, limit, procs=options.procs)
        bare = motes.mote_order(profile, worn, records, world.rules, scenario["setup"], buffset, buffs, limit)
        mote_cases.append(
            {
                "name": name, "scenario": dict(scenario), "kit": kit, "buffs": buffs, "motes": limit,
                "start": _exact_text(order.start), "ending": order.ending, "left": order.left, "spent": order.spent, "nextRun": order.next_run,
                "steps": [
                    {"index": s.index, "place": s.place, "key": s.key, "from": s.from_tier, "to": s.to_tier, "motes": s.motes, "spent": s.spent,
                     "gain": _exact_text(s.gain), "F": _exact_text(s.F), "moved": _exact_moved(s.moved)}
                    for s in order.steps
                ],
                "withoutProcs": [[s.place, s.key, s.from_tier, s.to_tier, _exact_text(s.gain)] for s in bare.steps],
            }
        )  # fmt: skip

    for case in cases:
        add(f"Equip now's kit under the table of procs, {MOTE_LIMIT} motes: {case['name']}", case["scenario"], case["equipNow"]["kit"], case["equipNow"]["buffs"], MOTE_LIMIT)
    kit: list[str | None] = [None] * 22
    kit[20] = "w80113@3"  # the mace one mote short of the socket tier, with a chest piece that gains at every tier
    kit[13] = "w90001@4"
    add("a mace one mote short of the socket tier, and a chest piece: the jump to the best proc it can host", CASES[0]["scenario"], kit, cases[0]["equipNow"]["buffs"], None)
    if not any([[s["place"], s["key"], s["from"], s["to"], s["gain"]] for s in case["steps"]] != case["withoutProcs"] for case in mote_cases):
        raise SystemExit("the table of procs does not move any mote order: change the procs")
    return {"trio": SLUG, "level": LEVEL, "procs": [list(row) for row in PROC_EFFECTS], "cases": cases, "motes": mote_cases}


def proc_family_text(document: dict[str, Any] | None = None) -> str:
    return json.dumps(proc_family_answers() if document is None else document, indent=1, ensure_ascii=False) + "\n"


def write_all() -> None:
    texts_made = {
        **texts(), EQUIP_NOW: equip_now_text(), KIT_VALUES: kit_values_text(), BEST_KIT: best_kit_text(), WEIGHTED: weighted_text(),
        WEAPON_RATE: weapon_rate_text(), UPGRADE_VIEW: upgrade_view_text(), MOTE_ORDERS: mote_orders_text(),
        PROCS_BUNDLE: proc_bundle_text(), PROCS_ITEMS: proc_items_text(), PROCS_FAMILY: proc_family_text(),
    }  # fmt: skip
    for path, text in texts_made.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(REPO).as_posix()} ({len(text.encode('utf-8')):,} bytes)")


if __name__ == "__main__":
    sys.exit(write_all())
