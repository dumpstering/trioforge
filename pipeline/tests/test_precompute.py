"""Tests for the precompute runner and the shard format: ``trioforge.precompute``.

The runner solves the scenario grid of a trio (race x role x tier x evidence x buffs x weapon setup) with the real
solver and writes compact JSON files under ``<out>/<trio>/``: four shards ``<evidence>-<buffs>.json`` (items, deduplicated
kits and totals, one row per scenario, each held to 200 KB raw and 50 KB gzip), the runner-ups in ``runnerups/<role>.json``
(one file for a role, holding every tier of the run's scope) with an ``index.json``, ``defaults.json`` and, when the robustness module exists, ``robust.json``. Finished work is kept in chunk files (one per race-free view: evidence, buffs, role, setup, tier) that are
written atomically and skipped on a rerun.

The evidence comes in layers:

* the grid itself, against the counts of the design (3,520 scenarios for PAL/MNK/BER) and the roles' setups;
* the pool selection (evidence levels, hand-in and temporary items, deity locks, classes, the private seen flags);
* a tiny grid (two races, one role, two tiers) run through the real solver: every row of the shards is re-solved here
  with the builder and the solver directly (pruned and, for the value, unpruned), the totals are recomputed from the
  stat-window formulas, the runner-ups are enumerated again item by item (three plain swaps and at most one deity-locked
  swap per place), and the gain is checked against the empty kit;
* resuming: a rerun skips finished chunks, a damaged or stale chunk is redone, an exactness error stops the run;
* the safety rules: seen flags are merged only into a folder under ``build/`` (or outside the repository).

Every name, item and number here is invented.
"""

import copy
import dataclasses
import gzip
import hashlib
import json
import os
import random
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import highspy
import pytest
from after_an_add import AfterAnAdd

from trioforge import precompute as pc
from trioforge.data import catalog as catalog_module
from trioforge.data.jsonio import load_strict
from trioforge.data.races import RACE_NAMES
from trioforge.model import formulas as fm
from trioforge.model import weapons as wp
from trioforge.model.buffs import group_preset, own_buffs, resolve, without_spell_haste
from trioforge.model.items import SLOT_GROUPS, SLOT_INSTANCES, at_tier
from trioforge.model.profile import make_profile
from trioforge.model.roles import roles_for
from trioforge.model.tables import REPO, load
from trioforge.precompute import grid, seals, shards
from trioforge.solver import _highs
from trioforge.solver import robust as robust_module
from trioforge.solver import solve as solve_module
from trioforge.solver.haste import solve_scenario
from trioforge.solver.model import BuildOptions, eval_buff_totals
from trioforge.solver.prune import prune
from trioforge.solver.solve import ExactnessError

TRIO = ("PAL", "MNK", "BER")
SLUG = "pal-mnk-ber"
TABLES = load()
RULES = TABLES.rules
SPELLS = json.loads((REPO / "derived" / "client" / "spells-l50.json").read_text(encoding="utf-8"))
TINY_GRID = {"races": ("OGR", "TRL"), "roles": ("tank",), "tiers": (0, 4)}
TINY = {**TINY_GRID, "robustness": False}  # the robustness module is tested on its own
# What the tiny grid holds. Every item of the invented catalog is a wiki item, so without seen flags the strict pool is empty and
# has no shield: the strict level plays two setups (2h, dw) and the wiki level, whose pool has the shield, three (1h-shield too).
TINY_STRICT_CHUNKS = 2 * 2 * 2  # buff sets x setups x tiers
TINY_WIKI_CHUNKS = 2 * 3 * 2
TINY_CHUNKS = TINY_STRICT_CHUNKS + TINY_WIKI_CHUNKS  # 20: a chunk is one view and holds both races
TINY_SCENARIOS = 2 * TINY_CHUNKS  # 40
ZONE = "Test Zone"


# ---- an invented catalog -------------------------------------------------------------------------------------------


def make_item(
    key, name, slots, *, classes=("ALL",), stats=None, sv=None, weight=1.0, weapon=None, item_type=None, flags=(),
    deity=None, level="wiki", more_reasons=(), tier_rule="drop", sources=None, races=("ALL",),
):
    """A catalog item in the shape of ``catalog-item.schema.json`` (with the ``evidence`` the builder adds)."""
    if level in ("strict", "wiki"):
        reasons = [{"code": f"live-source:{ZONE}", "seal": "client", "text": "A source in a live test zone."}]
    elif level == "disputed":
        reasons = [{"code": "out-of-era-tag-live-zone", "seal": "player", "text": "An out-of-era tag in a live zone."}]
    else:
        reasons = [{"code": "zones-not-in-eql", "seal": "client", "text": "No drop zone is part of EQL."}]
    reasons += [{"code": code, "seal": "model", "text": "A reason."} for code in more_reasons]
    if deity:
        reasons.append({"code": "not-for-default-kits", "seal": "model", "text": "Deity-locked."})
    return {
        "key": key, "name": name, "wiki": {"pageid": int(key[1:]), "revid": 1, "title": name}, "slots": list(slots),
        "classes": list(classes), "races": list(races), "deity": deity, "flags": list(flags), "stats": dict(stats or {}),
        "sv": dict(sv or {}), "weight": weight, "size": "SMALL", "item_type": item_type,
        "item_type_source": "statsblock" if item_type else None, "weapon": weapon,
        "container_capacity": None, "instrument_mods": {}, "effects": [], "required_level": None,
        "recommended_level": None,
        "sources": sources or {"drops": [{"zone": ZONE, "npcs": [f"a {name} keeper"]}], "sold_by": [], "quests": [], "crafted": []},
        "categories": [], "era_tags": [], "lucy_img_id": None, "tier_rule": tier_rule, "parse_warnings": [],
        "parse_warnings_overflow": 0, "evidence": {"level": level, "reasons": reasons},
    }  # fmt: skip


def weapon(skill, dmg, delay, bonus=None):
    return {"skill": skill, "dmg": dmg, "delay": delay, "bonus": bonus}


CATALOG = [
    make_item("w9001", "Test Alpha Helm", ["HEAD"], stats={"AC": 20, "STA": 10, "HP": 30}, weight=2.0),
    make_item("w9002", "Test Beta Helm", ["HEAD"], stats={"AC": 15, "STR": 12, "HASTE": 10}, weight=1.5),
    make_item("w9003", "Test Gamma Ring", ["FINGER"], stats={"STA": 8, "AGI": 6, "HP": 15}),
    make_item("w9004", "Test Delta Ring", ["FINGER"], stats={"STR": 10, "ATK": 8, "STA": 30, "HP": 120}, flags=["lore"]),
    make_item("w9005", "Test Epsilon Cloak", ["BACK"], stats={"AC": 10, "AGI": 8}, weight=1.0),
    make_item("w9006", "Test Zeta Chest", ["CHEST"], stats={"AC": 40, "STA": 14, "END": 25}, weight=8.0),
    make_item("w9007", "Test Eta Earring", ["EAR"], stats={"WIS": 10, "MANA": 20, "HP": 10}),
    make_item("w9008", "Test Theta Earring", ["EAR"], stats={"STA": 9}, sv={"FIRE": 10}),
    make_item("w9009", "Test Iota Bracer", ["WRIST"], classes=["PAL", "BER"], stats={"AC": 8, "DEX": 6}, weight=1.0),
    make_item("w9010", "Test Kappa Belt", ["WAIST"], stats={"AC": 12, "STR": 5}, weight=2.0, tier_rule="fixed0",
              sources={"drops": [], "sold_by": [{"zone": ZONE, "npc": "a test vendor"}], "quests": [], "crafted": []}),
    make_item("w9011", "Test Lambda Sword", ["PRIMARY", "SECONDARY"], stats={"STR": 4}, weight=3.0,
              weapon=weapon("1H Slashing", 12, 24, 10)),
    make_item("w9012", "Test Mu Blade", ["PRIMARY", "SECONDARY"], weight=3.5, weapon=weapon("1H Blunt", 14, 28)),
    make_item("w9013", "Test Nu Greatsword", ["PRIMARY"], stats={"STA": 3}, weight=6.0,
              weapon=weapon("2H Slashing", 30, 40, 25)),
    make_item("w9014", "Test Xi Shield", ["SECONDARY"], classes=["PAL", "BER"], stats={"AC": 18, "STA": 5}, weight=4.0,
              item_type="Shield"),
    make_item("w9015", "Test Omicron Crown", ["HEAD"], stats={"AC": 30, "STA": 25, "HP": 50}, deity=["Tunare"]),
    make_item("w9023", "Test Psi Ring", ["FINGER"], stats={"CHA": 1}, deity=["Karana"]),  # locked and too weak to be a swap
    make_item("w9024", "Test Om\u00e9ga Shoulders", ["SHOULDERS"], stats={"AC": 12, "STA": 6}, deity=["Brell Serilis", "Karana"]),
    make_item("w9025", "Test Lesser Cloak", ["BACK"], stats={"AC": 5, "AGI": 4}, weight=1.0),  # a plain swap for the cloak ...
    make_item("w9026", "Test Mirror Cloak", ["BACK"], stats={"AC": 5, "AGI": 4}, weight=1.0, deity=["Karana"]),  # ... and its tie
    make_item("w9016", "Test Pi Pendant", ["NECK"], stats={"STA": 20, "HP": 100}, more_reasons=["not-for-bis"]),
    make_item("w9017", "Test Rho Mask", ["FACE"], stats={"STA": 30, "AC": 30}, level="hidden"),
    make_item("w9018", "Test Sigma Mask", ["FACE"], stats={"STA": 25, "AC": 25}, level="disputed"),
    make_item("w9019", "Test Tau Mask", ["FACE"], stats={"STA": 6, "AC": 5}),
    make_item("w9020", "Test Upsilon Cap", ["HEAD"], classes=["WIZ"], stats={"STA": 40, "AC": 40}),
    make_item("w9021", "Test Phi Pendant", ["NECK"], stats={"AGI": 9, "AC": 6}, weight=0.5),
    make_item("w9022", "Test Chi Ammo", ["AMMO"], stats={"STA": 50}),
]
WEARABLE = {"HEAD", "FACE", "EAR", "NECK", "SHOULDERS", "ARMS", "BACK", "WRIST", "HANDS", "FINGER", "CHEST", "LEGS",
            "FEET", "WAIST", "RANGE", "ANY", "PRIMARY", "SECONDARY"}  # fmt: skip


TOOLS_INPUT = {"file": "https://eqlegendstools.com/zones/nektropos-castle/", "sha256": "00" * 32, "date": "2026-10-27"}  # (the zone page of EQ Legends Tools that the committed catalog was built from)


def write_catalog(path, items=CATALOG, version="2030-01-02"):
    path.write_text(
        json.dumps({"version": version, "license": "test", "attribution": "test", "provenance": {"inputs": [TOOLS_INPUT]}, "items": items}),
        encoding="utf-8",
    )
    return path


def write_seen(path, keys):
    path.write_text(json.dumps({"version": 1, "license": "test", "keys": sorted(keys)}), encoding="utf-8")
    return path


def small_world(root):
    """A copy of the tables in which only the Ogre and the Troll are playable: ``root`` is a ``tables_root`` for ``pc.run``. The whole grid of a
    trio in it (2 races instead of 15) is a few seconds of solving, so that a run which narrows nothing can be made in a test."""
    root = Path(root)
    (root / "rules").mkdir(parents=True, exist_ok=True)
    for name in ("rules.json", "races.json"):
        shutil.copy(REPO / "rules" / name, root / "rules" / name)
    shutil.copytree(REPO / "derived" / "client", root / "derived" / "client", dirs_exist_ok=True)
    races = read(root / "rules" / "races.json")
    for race in races["races"]:
        race["active"] = race["code"] in ("OGR", "TRL")
    (root / "rules" / "races.json").write_text(json.dumps(races), encoding="utf-8")
    return root


def eligible(items, evidence, seen=frozenset()):
    """The test's own rule for the pool of an evidence level (written again here, not taken from the module)."""
    def level(item):
        removed = any(r["code"] in ("removed-by-patch", "removed-by-research") for r in item["evidence"]["reasons"])
        return "strict" if item["evidence"]["level"] == "strict" or (item["key"] in seen and not removed) else item["evidence"]["level"]

    levels = ("strict",) if evidence == "strict" else ("strict", "wiki")
    return [
        i for i in items
        if level(i) in levels and i["deity"] is None and set(i["slots"]) & WEARABLE
        and not any(r["code"] == "not-for-bis" for r in i["evidence"]["reasons"])
        and ("ALL" in i["classes"] or set(i["classes"]) & set(TRIO))
    ]  # fmt: skip


def buffset_of(kind):
    own = own_buffs(TRIO, 50, SPELLS, RULES)
    buffs = own if kind == "own" else [*own, *group_preset(SPELLS)]
    return resolve(buffs if RULES.get("haste.assume_spell") else without_spell_haste(buffs), RULES)  # (the rule: no spell haste in the buffs a kit is chosen with)


def independent(items, tier, race, role, setup, buffs, evidence, *, pruned=True, seen=frozenset()):
    """The solver run on one scenario, straight from the catalog dicts with the builder and the solver."""
    pool = [at_tier(item, tier, RULES) for item in eligible(items, evidence, seen)]
    buffset = buffset_of(buffs)
    profile = make_profile(race, TRIO, 50, role, buffset, None, TABLES, evidence=evidence)
    if pruned:
        pool = prune(pool, profile, tier, setup, buffset)
    found = solve_scenario(profile, pool, setup, buffset)  # the weapons are paid the haste the kit counts, as the precompute pays them
    return found.solution, found.milp, profile, buffset


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def result_files(folder):
    """Every result file under the folder of a trio (not its chunks), as ``{relative path: bytes}``."""
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in sorted(Path(folder).rglob("*")) if p.is_file() and "chunks" not in p.relative_to(folder).parts
    }  # fmt: skip


def runnerup_docs(folder):
    """The runner-up files of the folder of a trio as ``{(role, tier): document}`` (the index is not one of them).

    A file is a role's, with every tier of the run in it (``views`` are ``[tier, race, setup, places]``, and the item table is the file's). Here it is
    split by tier: the document of a tier has that tier's ``views`` as ``[race, setup, places]`` and the file's items, so that a check of the swaps of
    one view reads as it did when there was a file for each tier."""
    out = {}
    for path in sorted((Path(folder) / "runnerups").glob("*.json")):
        if path.name != "index.json":
            doc = read(path)
            for tier in doc["tiers"]:
                out[(doc["role"], tier)] = {**doc, "tier": tier, "views": [view[1:] for view in doc["views"] if view[0] == tier]}
    return out


def expand(shard):
    """``{(race, role, tier, setup): {"kit": [key|None] * 22, "F", "gain", "totals": {name: n}, "buffs": [id], "haste"}}`` of a
    shard."""
    keys = [row[0] for row in shard["items"]]
    out = {}
    for race, role, tier, setup, kit, value, gain, totals, buffs, haste in shard["scenarios"]:
        out[(race, role, tier, setup)] = {
            "kit": [keys[i] if i >= 0 else None for i in shard["kits"][kit]], "F": value, "gain": gain,
            "totals": dict(zip(shard["totals_keys"], shard["totals"][totals])), "buffs": shard["buff_sets"][buffs],
            "haste": haste,
        }  # fmt: skip
    return out


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    root = tmp_path_factory.mktemp("tiny")
    catalog = write_catalog(root / "catalog.json")
    out = root / "out"
    summary = pc.run(SLUG, out, catalog=catalog, processes=1, **TINY)
    return SimpleNamespace(root=root, catalog=catalog, out=out, dir=out / SLUG, summary=summary)


@pytest.fixture
def fresh(tiny, tmp_path):
    """A copy of the tiny run's output folder to rerun in, and the paths to rerun with."""
    out = tmp_path / "out"
    shutil.copytree(tiny.out, out)
    return SimpleNamespace(out=out, dir=out / SLUG, catalog=tiny.catalog)


# ---- the grid ----------------------------------------------------------------------------------------------------


def test_the_catalog_of_these_tests_is_valid_against_the_item_schema():
    from trioforge.data.normalize import validate_item

    for item in CATALOG:
        validate_item(item)


def test_the_full_grid_of_the_milestone_trio_has_the_3520_scenarios_of_the_design():
    scenarios = grid.scenarios(TRIO, TABLES, RULES)
    assert len(scenarios) == 3520 == len(set(scenarios))  # 16 races x 5 build-setup pairs x 11 tiers x 2 evidence levels x 2 buff sets
    assert {s.race for s in scenarios} == {"HUM", "BAR", "ERU", "ELF", "HIE", "DEF", "HEF", "DWF", "TRL", "OGR", "HFL", "GNM", "IKS", "KER", "FRG", "HDE"}
    assert {s.role for s in scenarios} == {"tank", "melee"}  # (a Paladin trio with no caster class: no Shield caster, and no Balanced build any more)
    assert {s.tier for s in scenarios} == set(range(11))
    assert {s.evidence for s in scenarios} == {"strict", "wiki"} and {s.buffs for s in scenarios} == {"own", "group"}
    pairs = {(s.role, s.setup) for s in scenarios}
    assert pairs == {("tank", "1h-shield"), ("tank", "2h"), ("tank", "dw"), ("melee", "2h"), ("melee", "dw")}


def test_a_setup_a_role_does_not_play_is_never_in_the_grid():
    scenarios = grid.scenarios(TRIO, TABLES, RULES)
    assert not [s for s in scenarios if s.role == "melee" and s.setup == "1h-shield"]  # review focus 1
    assert all(s.setup in wp.setups_for(TRIO, s.role, TABLES, level=50) for s in scenarios)


def test_the_grid_can_be_narrowed_and_is_always_in_the_same_order():
    narrow = grid.scenarios(TRIO, TABLES, RULES, races=("OGR", "TRL"), roles=("tank",), tiers=(0, 4), evidence=("wiki",), buffs=("own",))
    assert len(narrow) == 2 * 3 * 2 and {s.race for s in narrow} == {"OGR", "TRL"}
    assert narrow == grid.scenarios(TRIO, TABLES, RULES, races=("TRL", "OGR"), roles=("tank",), tiers=(4, 0), evidence=("wiki",), buffs=("own",))
    keys = [grid.chunk_key(s) for s in narrow]
    assert keys == sorted(keys, key=lambda k: keys.index(k))  # the races of one view sit together
    for bad in ({"races": ("XXX",)}, {"roles": ("healer",)}, {"tiers": (11,)}, {"evidence": ("hidden",)}, {"buffs": ("raid",)}):
        with pytest.raises(ValueError):
            grid.scenarios(TRIO, TABLES, RULES, **bad)


def test_a_chunk_is_one_view_and_holds_every_race():
    scenarios = grid.scenarios(TRIO, TABLES, RULES)
    chunks = grid.chunks(scenarios)
    assert len(chunks) == 2 * 2 * 5 * 11 == 220  # evidence x buff sets x (build, setup) pairs x tiers
    assert all(len(races) == 16 for races in chunks.values())
    key = grid.ChunkKey("wiki", "own", "tank", "dw", 4)
    assert key in chunks and chunks[key][0] == "HUM"


def test_creation_legal_races_come_first_and_disputed_legality_does_not_count():
    order = grid.race_order(TRIO, TABLES)
    legal = [code for code, ok in order if ok]
    assert [code for code, ok in order][: len(legal)] == legal  # legal first, then the rest
    assert "ELF" not in legal and "DEF" not in legal and {"OGR", "TRL", "IKS", "KER"} <= set(legal)
    assert len(order) == 16
    # a Kerran may start a Druid trio only if that is confirmed, and it is not
    assert grid.creation_legal("KER", ("DRU", "WIZ", "MAG"), TABLES) is False
    assert grid.creation_legal("HUM", ("DRU", "WIZ", "MAG"), TABLES) is True
    assert grid.creation_legal("KER", ("DRU", "WAR", "MAG"), TABLES) is True  # the Warrior can be the first class


def test_trio_slugs_are_read_in_class_order():
    assert grid.parse_trio("pal-mnk-ber") == ("PAL", "MNK", "BER")
    assert grid.parse_trio("BER-pal-MNK") == ("PAL", "MNK", "BER")
    assert grid.parse_trio(["BER", "PAL", "MNK"]) == ("PAL", "MNK", "BER")
    assert grid.trio_slug(("PAL", "MNK", "BER")) == SLUG
    for bad in ("pal-mnk", "pal-mnk-mnk", "pal-mnk-xyz", "", "pal mnk ber"):
        with pytest.raises(ValueError):
            grid.parse_trio(bad)


# ---- the pool ----------------------------------------------------------------------------------------------------


def test_the_pool_takes_wearable_items_of_the_evidence_level_for_the_trio_without_hand_in_and_deity_items():
    chosen = grid.select_items(CATALOG, TRIO)
    kept = {item["key"] for item in chosen.items}
    assert "w9015" in kept  # deity-locked items stay in the list (runner-ups), flagged by their deity
    assert not kept & {"w9016", "w9017", "w9018", "w9020", "w9022"}  # not-for-bis, hidden, disputed, other class, ammo
    assert chosen.levels["w9001"] == "wiki" and set(chosen.levels.values()) == {"wiki"}
    assert {i["key"] for i in grid.pool_dicts(chosen, "wiki")} == {i["key"] for i in eligible(CATALOG, "wiki")}
    assert grid.pool_dicts(chosen, "strict") == []


@pytest.mark.skipif(not (REPO / "derived" / "catalog.json").is_file(), reason="derived/catalog.json is not built")
def test_no_item_of_the_real_catalog_that_carries_not_for_bis_is_chosen_for_any_trio_and_the_table_carries_the_mark_where_the_browser_reads_it():
    """The export item table holds every wearable, a marked one too (the mark rides in evidence.codes); what keeps it out of every kit and every Upgrade pool is that select_items (here) and
    candidatesFor (tests-js/engine-candidates.test.mjs, on the same catalog) leave out what carries the code. Held on the real catalog: the whole marked set, w60572 and w73494 by name."""
    from trioforge.export import browser

    document = load_strict(REPO / "derived" / "catalog.json")
    items = document["items"]
    marked = {item["key"] for item in items if any(reason["code"] == "not-for-bis" for reason in item["evidence"]["reasons"])}
    by_key = {item["key"]: item for item in items}
    assert {"w60572", "w73494"} <= marked and len(marked) > 1000  # (a blank-line page with no slot, and a hand weapon with no damage; and the many that were marked before)
    trios = ("WAR-CLR-PAL", "RNG-SHD-DRU", "MNK-BRD-ROG", "SHM-NEC-WIZ", "MAG-ENC-BST", "BER-PAL-MNK")  # every class is in one of them
    for trio in trios:
        chosen = {item["key"] for item in grid.select_items(items, grid.parse_trio(trio)).items}
        assert not chosen & marked, (trio, sorted(chosen & marked)[:5])
        assert not chosen & {"w60572", "w73494"}, trio
    # the same items without the mark, and open to every class, are chosen: the mark alone keeps them out (w73494 is one; w60572 has no slot to wear)
    would_be = [
        {**copy.deepcopy(by_key[key]), "classes": ["ALL"], "evidence": {"level": "wiki", "reasons": [r for r in by_key[key]["evidence"]["reasons"] if r["code"] != "not-for-bis"]}}
        for key in sorted(marked)
        if by_key[key]["evidence"]["level"] in ("strict", "wiki") and grid.WEARABLE_SLOTS & set(by_key[key]["slots"])
    ]
    assert "w73494" in {item["key"] for item in would_be} and "w60572" not in {item["key"] for item in would_be} and len(would_be) > 100
    assert {item["key"] for item in grid.select_items(would_be, grid.parse_trio(trios[0])).items} == {item["key"] for item in would_be}
    # and the table writes the mark where the browser's candidates read it, for every marked wearable
    table = browser.items(document, RULES)
    records = {browser.record_key(record): record for record in table["items"]}
    wearable_marked = marked & set(records)
    assert "w73494" in wearable_marked and "w60572" not in records and len(wearable_marked) > 500
    assert all("not-for-bis" in records[key]["evidence"].get("codes", ()) for key in wearable_marked)
    assert not [key for key, record in records.items() if key not in marked and "not-for-bis" in record["evidence"].get("codes", ())]


def test_seen_flags_make_wiki_items_strict_but_never_resurrect_removed_or_hidden_ones():
    removed = make_item("w9030", "Test Removed Ring", ["FINGER"], stats={"STA": 50}, level="hidden", more_reasons=["removed-by-patch"])
    items = [*CATALOG, removed]
    chosen = grid.select_items(items, TRIO, seen=frozenset({"w9001", "w9030", "w9017", "w9099"}))
    assert chosen.levels["w9001"] == "strict" and chosen.levels["w9003"] == "wiki"
    assert "w9030" not in chosen.levels  # a patch removal beats a sighting
    assert chosen.levels["w9017"] == "strict"  # a sighting overrides the wiki signals (hidden: zones not in EQL)
    assert chosen.unknown_seen == 1  # w9099 is not in the catalog
    assert {i["key"] for i in grid.pool_dicts(chosen, "strict")} == {"w9001", "w9017"}
    assert "w9001" in {i["key"] for i in grid.pool_dicts(chosen, "wiki")}


def test_a_strict_item_of_the_catalog_itself_is_strict():
    items = [make_item("w9031", "Test Strict Ring", ["FINGER"], stats={"STA": 5}, level="strict"), *CATALOG]
    assert grid.select_items(items, TRIO).levels["w9031"] == "strict"


def test_the_solve_pool_has_no_deity_locked_item_but_the_runner_up_candidates_do(tmp_path):
    config, _ = grid.load_inputs(TRIO, catalog_path=write_catalog(tmp_path / "catalog.json"))
    ctx = grid.Context(config)
    pool = ctx.pool("wiki", 4)
    assert "w9015" not in {v.key for v in pool} and "w9015" in {v.key for v in ctx.candidates("wiki", 4)}
    assert [v.key for v in pool] == sorted(v.key for v in pool) and all(v.tier == 4 for v in pool)
    assert {v.key for v in pool} == {i["key"] for i in eligible(CATALOG, "wiki")}
    assert ctx.pool("strict", 4) == [] and ctx.candidates("strict", 4) == []
    assert ctx.vecs(0)["w9001"].stats["AC"] == 20 and ctx.vecs(4)["w9001"].stats["AC"] == 28  # the tier rule of the item vectors


def test_source_summary_is_a_short_text_and_arrival_is_the_highest_tier_a_copy_exists_without_merging():
    drop = make_item("w9040", "Test A", ["HEAD"], sources={"drops": [{"zone": "Elsewhere", "npcs": []}, {"zone": ZONE, "npcs": ["a test keeper", "another"]}], "sold_by": [], "quests": [], "crafted": []})
    assert shards.source_summary(drop, {ZONE}) == f"{ZONE} (a test keeper)"
    assert shards.source_summary(drop, set()) == "Elsewhere"  # no live zone known: the first drop
    quest = make_item("w9041", "Test B", ["HEAD"], sources={"drops": [], "sold_by": [], "quests": ["The Test Quest"], "crafted": []})
    assert shards.source_summary(quest, set()) == "quest: The Test Quest"
    vendor = make_item("w9042", "Test C", ["HEAD"], sources={"drops": [], "sold_by": [{"zone": ZONE, "npc": "a vendor"}], "quests": [], "crafted": []})
    assert shards.source_summary(vendor, set()) == f"vendor: {ZONE}"
    crafted = make_item("w9043", "Test D", ["HEAD"], sources={"drops": [], "sold_by": [], "quests": [], "crafted": [{"container": "Test Forge", "ingredients": []}]})
    assert shards.source_summary(crafted, set()) == "crafted: Test Forge"
    none = make_item("w9044", "Test E", ["HEAD"], sources={"drops": [], "sold_by": [], "quests": [], "crafted": []})
    assert shards.source_summary(none, set()) == ""
    long = make_item("w9045", "Test F", ["HEAD"], sources={"drops": [{"zone": "Z" * 200, "npcs": []}], "sold_by": [], "quests": [], "crafted": []})
    assert len(shards.source_summary(long, set())) <= 60
    assert shards.arrival_tier("drop", RULES) == 4 and shards.arrival_tier("fixed0", RULES) == 0  # the highest fresh drop; a quest at +0
    assert shards.arrival_tier("spell", RULES) is None  # a summoned item arrives at its spell rank: no tier to count copies from
    assert type(shards.arrival_tier("drop", RULES)) is int


def sourced(key, name, *, drops=(), quests=(), labels=None, sold_by=(), crafted=(), foraged=None, **more):
    """An item whose sources are given (the optional ``quest_labels`` and ``foraged`` only when asked for)."""
    sources = {"drops": list(drops), "sold_by": list(sold_by), "quests": list(quests), "crafted": list(crafted)}
    if labels is not None:
        sources["quest_labels"] = labels
    if foraged is not None:
        sources["foraged"] = foraged
    return make_item(key, name, ["HEAD"], sources=sources, **more)


def test_a_quest_source_shows_the_label_of_the_quest_link_when_there_is_one_else_the_page_title():
    # sources.quests holds the targets of the quest links (page titles); the text the link showed is in quest_labels
    labelled = sourced("w9046", "Test G", quests=["Test Armor Quests"], labels=[{"title": "Test Armor Quests", "label": "Test Helm Quest"}])
    assert shards.source_summary(labelled, set()) == "quest: Test Helm Quest"
    assert shards.source_summary(labelled, {"quest"}) == "quest: Test Helm Quest"  # a live quest, the same words
    assert shards.source_summary(sourced("w9047", "Test H", quests=["The Test Quest"]), set()) == "quest: The Test Quest"  # no labels at all
    # the label belongs to the title of the first quest, wherever it stands in the list of labels
    several = sourced("w9048", "Test I", quests=["First Quest", "Second Quest"],
                      labels=[{"title": "Second Quest", "label": "Second label"}, {"title": "First Quest", "label": "First label"}])  # fmt: skip
    assert shards.source_summary(several, set()) == "quest: First label"
    only_second = sourced("w9049", "Test J", quests=["First Quest", "Second Quest"], labels=[{"title": "Second Quest", "label": "Second label"}])
    assert shards.source_summary(only_second, set()) == "quest: First Quest"  # the first quest has no label: its title
    long = sourced("w9050", "Test K", quests=["Q"], labels=[{"title": "Q", "label": "L" * 200}])
    summary = shards.source_summary(long, set())
    assert len(summary) == 60 and summary.endswith("...") and summary.startswith("quest: LLL")
    # a drop in a live zone still comes first, and an item whose labels are for other titles shows its own title
    dropped = sourced("w9051", "Test L", drops=[{"zone": ZONE, "npcs": []}], quests=["Q"], labels=[{"title": "Q", "label": "Label"}])
    assert shards.source_summary(dropped, {ZONE}) == ZONE
    assert shards.source_summary(sourced("w9052", "Test M", quests=["Q"], labels=[{"title": "Other", "label": "Label"}]), set()) == "quest: Q"


def test_a_foraged_item_says_in_which_zone_it_is_foraged_and_a_live_drop_or_quest_still_comes_first():
    woods = [{"zone": "Test Woods"}]
    only = sourced("w9053", "Test N", foraged=woods, tier_rule="fixed0", more_reasons=["live-source:foraged"])
    assert shards.source_summary(only) == "Foraged in Test Woods"  # from its own reasons: live-source:foraged is a kind, not a zone
    assert shards.source_summary(only, {"foraged"}) == "Foraged in Test Woods"
    assert shards.source_summary(only, set()) == "Foraged in Test Woods"  # no live source known: it is still the only one it has
    # the zone: the first one that is live, else the first
    zones = sourced("w9054", "Test O", foraged=[{"zone": "Test Plains"}, {"zone": "Test Woods"}, {"zone": "Test Marsh"}])
    assert shards.source_summary(zones, {"foraged", "Test Woods"}) == "Foraged in Test Woods"
    assert shards.source_summary(zones, {"foraged"}) == "Foraged in Test Plains"
    assert shards.source_summary(zones, set()) == "Foraged in Test Plains"
    # order of the sources: a drop in a live zone, a live quest, vendor or recipe, then foraging; with nothing live, the
    # drops, quests, vendors and recipes before foraging
    drop = [{"zone": ZONE, "npcs": ["a keeper"]}]
    assert shards.source_summary(sourced("w9055", "Test P", drops=drop, foraged=woods), {ZONE, "foraged"}) == f"{ZONE} (a keeper)"
    assert shards.source_summary(sourced("w9056", "Test Q", quests=["Q"], foraged=woods), {"quest", "foraged"}) == "quest: Q"
    sells = [{"zone": ZONE, "npc": "a vendor"}]
    assert shards.source_summary(sourced("w9057", "Test R", sold_by=sells, foraged=woods), {"vendor", "foraged"}) == f"vendor: {ZONE}"
    forge = [{"container": "Test Forge", "ingredients": []}]
    assert shards.source_summary(sourced("w9058", "Test S", crafted=forge, foraged=woods), {"craft", "foraged"}) == "crafted: Test Forge"
    assert shards.source_summary(sourced("w9059", "Test T", crafted=forge, foraged=woods), {"foraged"}) == "Foraged in Test Woods"  # craft not live
    assert shards.source_summary(sourced("w9060", "Test U", drops=drop, foraged=woods), set()) == f"{ZONE} (a keeper)"
    assert shards.source_summary(sourced("w9061", "Test V", crafted=forge, foraged=woods), set()) == "crafted: Test Forge"
    assert len(shards.source_summary(sourced("w9062", "Test W", foraged=[{"zone": "Z" * 200}]), set())) == 60
    assert shards.source_summary(sourced("w9063", "Test X", foraged=[])) == ""  # an empty list is no source


def test_items_with_quest_labels_and_foraged_zones_go_through_a_run_with_their_words_in_the_item_table(tmp_path):
    ring = make_item(
        "w9028", "Test Forager Ring", ["FINGER"], stats={"STA": 60, "HP": 300}, tier_rule="fixed0",
        more_reasons=["live-source:foraged"], sources={"drops": [], "sold_by": [], "quests": [], "crafted": [], "foraged": [{"zone": "Test Woods"}]},
    )  # fmt: skip
    cloak = make_item(
        "w9029", "Test Quest Cloak", ["BACK"], stats={"AC": 40, "AGI": 30}, tier_rule="fixed0", more_reasons=["live-source:quest"],
        sources={"drops": [], "sold_by": [], "quests": ["Test Cloak Quests"], "crafted": [],
                 "quest_labels": [{"title": "Test Cloak Quests", "label": "Test Cloak Quest"}]},
    )  # fmt: skip
    out = tmp_path / "out"
    pc.run(SLUG, out, catalog=write_catalog(tmp_path / "catalog.json", [*CATALOG, ring, cloak]), processes=1, robustness=False, **TINY_GRID)
    table = {row[0]: dict(zip(read(out / SLUG / "wiki-own.json")["items_keys"], row)) for row in read(out / SLUG / "wiki-own.json")["items"]}
    assert table["w9028"]["source"] == "Foraged in Test Woods" and table["w9028"]["arrival"] == 0
    assert table["w9029"]["source"] == "quest: Test Cloak Quest"


# ---- legality of a kit ------------------------------------------------------------------------------------------


def vec(key, tier=4):
    return at_tier(next(i for i in CATALOG if i["key"] == key), tier, RULES)


def kit_of(**places):
    kit = [None] * 22
    for place, item in places.items():
        kit[SLOT_INSTANCES.index(place.rstrip("0123456789"))  + (int(place[-1]) - 1 if place[-1].isdigit() else 0)] = item
    return kit


def test_check_kit_accepts_a_legal_kit_and_names_every_fault_of_an_illegal_one():
    legal = kit_of(HEAD=vec("w9001"), FINGER1=vec("w9003"), FINGER2=vec("w9003"), PRIMARY=vec("w9011"), SECONDARY=vec("w9014"))
    assert grid.check_kit(legal, "1h-shield", TRIO) == []
    wrong_slot = kit_of(HEAD=vec("w9003"))
    assert any("w9003" in p and "HEAD" in p for p in grid.check_kit(wrong_slot, "dw", TRIO))
    lore_twice = kit_of(FINGER1=vec("w9004"), FINGER2=vec("w9004"))
    assert any("w9004" in p and "Lore" in p for p in grid.check_kit(lore_twice, "dw", TRIO))
    two_handed_and_shield = kit_of(PRIMARY=vec("w9013"), SECONDARY=vec("w9014"))
    assert grid.check_kit(two_handed_and_shield, "1h-shield", TRIO)
    assert any("w9013" in p for p in grid.check_kit(kit_of(PRIMARY=vec("w9013")), "dw", TRIO))  # a two-hander in a dual wield
    assert grid.check_kit(kit_of(PRIMARY=vec("w9013")), "2h", TRIO) == []
    assert grid.check_kit(kit_of(SECONDARY=vec("w9011")), "2h", TRIO)  # nothing in the off hand with a two-hander setup
    deity = vec("w9015")
    assert any("deity" in p for p in grid.check_kit(kit_of(HEAD=deity), "dw", TRIO))
    wizard = vec("w9020")
    assert any("w9020" in p for p in grid.check_kit(kit_of(HEAD=wizard), "dw", TRIO))
    assert grid.check_kit([None] * 3, "dw", TRIO)  # not 22 places


# ---- the files of a tiny run ---------------------------------------------------------------------------------------


def test_a_run_writes_four_shards_the_runner_ups_the_defaults_and_chunk_files(tiny):
    names = sorted(p.name for p in tiny.dir.iterdir() if p.is_file())
    assert names == ["defaults.json", "engine-l50.json", "strict-group.json", "strict-own.json", "wiki-group.json", "wiki-own.json"]
    assert sorted(p.name for p in (tiny.dir / "runnerups").iterdir()) == ["index.json", "tank.json"]
    assert not (tiny.dir / "runnerups.json").exists()  # one file for each role instead
    chunk_files = sorted((tiny.dir / "chunks").glob("*.json"))
    assert len(chunk_files) == TINY_CHUNKS + 1 * 2 == 22  # 20 solve chunks, 2 runner-up chunks (role x tier)
    assert not list(tiny.dir.rglob("*.tmp"))
    s = tiny.summary
    assert (s.scenarios, s.chunks, s.solved, s.reused, s.redone) == (TINY_SCENARIOS, TINY_CHUNKS, TINY_SCENARIOS, 0, 0) == (40, 20, 40, 0, 0)
    assert s.partial is True  # the grid was narrowed
    assert s.canonical is True and s.elapsed > 0 and s.mean_solve_seconds > 0
    assert tiny.dir / "wiki-own.json" in s.files and not s.violations


def test_the_shard_header_names_the_data_the_rules_and_the_solver_choice(tiny):
    shard = read(tiny.dir / "wiki-own.json")
    assert shard["version"] == 1 and shard["trio"] == SLUG and shard["classes"] == list(TRIO)
    assert (shard["evidence"], shard["buffs"], shard["level"]) == ("wiki", "own", 50)
    assert shard["data_release"] == "data-2030-01-02" and shard["rules_version"] == RULES.version
    assert shard["game_patch"] == "2026-11-16"
    solver = shard["solver"]
    assert solver["canonical"] is True and solver["time_limit"] is None  # never a time limit
    assert {name: solver[name] for name in _highs.OPTIONS if name != "output_flag"} == {n: v for n, v in _highs.OPTIONS.items() if n != "output_flag"}
    assert (solver["presolve"], solver["mip_rel_gap"], solver["threads"], solver["random_seed"]) == ("off", 0, 1, 0)
    assert solver["highs"] == highspy.Highs().version() and solver["revision"] == highspy.Highs().githash()
    assert shard["build_options"] == {"any_rule": "all", "haste_assumed": None}
    sample = make_profile("OGR", TRIO, 50, "tank", buffset_of("own"), None, TABLES)
    assert shard["assumptions"] == {"aa": dict(sample.aa), "deity": None} == {"aa": {"combat_stability": 3, "natural_durability": 4, "physical_enhancement": True}, "deity": None}
    assert shard["partial"] is True
    assert shard["flags"] == ["strict pool empty"]
    assert shard["pool"] == len(eligible(CATALOG, "wiki"))
    legal_flags = [r["legal"] for r in shard["races"]]
    assert [r["code"] for r in shard["races"]] == [code for code, _ in grid.race_order(TRIO, TABLES) if code in TINY_GRID["races"]]  # the races it has rows for
    assert legal_flags == sorted(legal_flags, reverse=True) and legal_flags.count(True) == 2  # (all 15 races, 13 of them legal, are in test_the_races_of_the_milestone_trio)
    assert shard["places"] == list(shards.PLACES) and len(shard["places"]) == 22
    assert shard["items_keys"] == ["key", "name", "slots", "tier_rule", "arrival", "source", "evidence", "deity"]
    assert shard["totals_keys"] == ["ac", "hp", "mana", "end", "haste", "atk", "fire", "cold", "magic", "poison", "disease", "hpreg", "manareg", "endreg"]
    assert shard["roles"] == ["tank"] and shard["setups"] == {"tank": ["1h-shield", "2h", "dw"]}
    assert shard["tiers"] == [0, 4]
    caps = shard["caps"]
    assert caps["haste"] == 85 and caps["resist"] == 1000 and caps["regen"] == {"HP": 30, "MANA": 15, "END": 15}  # (T4: the resist cap is 1000)
    assert caps["sheet_softcap"] == make_profile("OGR", TRIO, 50, "tank", buffset_of("own"), None, TABLES).effective_softcap


def test_every_row_of_a_wiki_shard_is_the_optimum_the_solver_finds_on_its_own(tiny):
    for buffs in ("own", "group"):
        rows = expand(read(tiny.dir / f"wiki-{buffs}.json"))
        assert len(rows) == 2 * 1 * 2 * 3  # races x roles x tiers x setups
        for (race, role, tier, setup), row in rows.items():
            full, _, _, _ = independent(CATALOG, tier, race, role, setup, buffs, "wiki", pruned=False)
            assert full.status == "optimal"
            assert row["F"] == pytest.approx(full.F, rel=1e-9, abs=0.006), (race, tier, setup, buffs)  # the file keeps two decimals
            same, milp, profile, _ = independent(CATALOG, tier, race, role, setup, buffs, "wiki")
            assert row["kit"] == [item.key if item else None for item in same.kit], (race, tier, setup, buffs)
            assert row["buffs"] == list(same.buffs) and row["haste"] == milp.haste_assumed, (race, tier, setup, buffs)
            assert same.F == pytest.approx(full.F, rel=1e-12)  # pruning is exact


@pytest.mark.parametrize("name", ["strict-own", "strict-group", "wiki-own", "wiki-group"])
def test_a_row_holds_what_a_reader_needs_to_value_its_kit_again(tiny, name):
    # the kit, the chosen optional buffs and the assumed haste of a row, read from the file alone, give back its F
    evidence, buffs = name.split("-")
    shard = read(tiny.dir / f"{name}.json")
    buffset = buffset_of(buffs)
    by_key = {item["key"]: item for item in CATALOG}
    assert shard["scenarios"], name
    for (race, role, tier, setup), row in expand(shard).items():
        profile = make_profile(race, TRIO, 50, role, buffset, None, TABLES, evidence=evidence)
        kit = [at_tier(by_key[key], tier, RULES) if key else None for key in row["kit"]]
        totals = eval_buff_totals(buffset.totals(row["buffs"]))
        exact = fm.evaluate(profile.eval_profile, kit, totals, setup=setup, haste_assumed=row["haste"])
        assert float(exact.F) == pytest.approx(row["F"], abs=0.006), (name, race, role, tier, setup)
        assert buffset.is_legal(row["buffs"])  # a legal choice among the optional buffs
    assert all(set(ids) <= {buff.id for buff in buffset.optional} for ids in shard["buff_sets"])
    if buffs == "group":
        assert any(shard["buff_sets"]) and all(len(ids) <= 15 for ids in shard["buff_sets"])  # the slot limit of the buff set


def test_the_kits_are_deduplicated_and_every_row_points_at_a_real_kit_item_and_totals(tiny):
    shard = read(tiny.dir / "wiki-own.json")
    kits = [tuple(k) for k in shard["kits"]]
    assert len(kits) == len(set(kits)) and all(len(k) == 22 for k in kits)
    assert len(kits) < len(shard["scenarios"])  # several rows share a kit
    assert len({tuple(t) for t in shard["totals"]}) == len(shard["totals"])
    used = {i for k in kits for i in k if i >= 0}
    assert used == set(range(len(shard["items"])))  # the item table lists exactly the items some kit wears
    assert [row[0] for row in shard["items"]] == sorted(row[0] for row in shard["items"])
    buff_sets = [tuple(ids) for ids in shard["buff_sets"]]
    assert len(buff_sets) == len(set(buff_sets)) and all(list(ids) == sorted(ids) for ids in buff_sets)
    for race, role, tier, setup, kit, value, gain, totals, buffs, haste in shard["scenarios"]:
        assert 0 <= kit < len(kits) and 0 <= totals < len(shard["totals"]) and 0 <= buffs < len(buff_sets)
        assert isinstance(value, float) and gain >= 0 and type(haste) is int and 0 <= haste <= shard["caps"]["haste"]
    order = [(r["code"]) for r in shard["races"]]
    keys = [(order.index(row[0]), row[2], ["1h-shield", "2h", "dw"].index(row[3])) for row in shard["scenarios"]]
    assert keys == sorted(keys)  # a fixed row order: race, tier, setup within the role


def test_the_races_of_the_milestone_trio_are_all_listed_the_creation_legal_ones_first():
    races = grid.race_order(TRIO, TABLES)
    flags = [legal for _, legal in races]
    assert len(races) == 16 and [code for code, _ in races][:2] == ["HUM", "BAR"]
    assert flags == sorted(flags, reverse=True) and flags.count(True) == 14  # all but the Wood Elf and Dark Elf (the Half Dark Elf starts a Berserker)


def test_a_narrowed_run_lists_only_the_races_it_has_rows_for(tiny):
    wanted = [(code, legal) for code, legal in grid.race_order(TRIO, TABLES) if code in TINY_GRID["races"]]
    assert sorted(code for code, _ in wanted) == ["OGR", "TRL"]
    for evidence in ("strict", "wiki"):
        for buffs in ("own", "group"):
            shard = read(tiny.dir / f"{evidence}-{buffs}.json")
            assert [(r["code"], r["legal"]) for r in shard["races"]] == wanted, (evidence, buffs)
            assert {row[0] for row in shard["scenarios"]} == {code for code, _ in wanted}, (evidence, buffs)  # no race without a row, no row without a race
    defaults = read(tiny.dir / "defaults.json")
    assert [(r["race"], r["legal"]) for r in defaults["races"]] == wanted
    assert defaults["race"] in {code for code, _ in wanted} and defaults["runner_up_race"] in {code for code, _ in wanted}


# ---- what the files say once for the whole trio ------------------------------------------------------------------------------------------


def test_the_caps_and_the_assumptions_are_one_set_for_every_race_and_role_of_a_trio():
    """The result files give ``caps`` and ``assumptions`` once, from one sample profile: that is right only while no race or role has its
    own. A rule that gave one race another cap would have to change the files; this is the test that notices."""
    facts = {}
    for race, _ in grid.race_order(TRIO, TABLES):
        for role in roles_for(TRIO):
            profile = make_profile(race, TRIO, 50, role, buffset_of("own"), None, TABLES)
            facts[(race, role)] = pc.layout_facts(profile)
    assert len(facts) == 16 * 2
    caps, assumptions = facts[("OGR", "tank")]
    assert (caps["haste"], caps["resist"], caps["regen"]) == (85, 1000, {"HP": 30, "MANA": 15, "END": 15})  # (T4: the resist cap is 1000)
    assert assumptions == {"aa": {"combat_stability": 3, "natural_durability": 4, "physical_enhancement": True}, "deity": None}
    assert {key: value for key, value in facts.items() if value != (caps, assumptions)} == {}


@pytest.mark.parametrize("change", [{"haste_cap": 99}, {"deity": "Test Deity"}, {"caps": {"regen": {"HP": 31, "MANA": 15, "END": 15}, "resist": 200}}])
def test_a_run_stops_when_a_race_has_other_caps_or_assumptions_than_the_sample_the_files_are_written_from(fresh, monkeypatch, change):
    real = grid.Context.profile

    def profile(self, race, role, buffs, evidence):
        found = real(self, race, role, buffs, evidence)
        return dataclasses.replace(found, **change) if race == "TRL" else found

    monkeypatch.setattr(grid.Context, "profile", profile)
    before = sorted(p.name for p in fresh.dir.iterdir())
    with pytest.raises(pc.PrecomputeError, match=r"caps and assumptions.*TRL"):
        pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, **TINY)
    assert sorted(p.name for p in fresh.dir.iterdir()) == before  # no result file was touched


def test_the_item_table_describes_each_item_with_its_tier_rule_arrival_source_and_evidence_badge(tiny):
    shard = read(tiny.dir / "wiki-own.json")
    table = {row[0]: dict(zip(shard["items_keys"], row)) for row in shard["items"]}
    assert set(table) <= {i["key"] for i in eligible(CATALOG, "wiki")}  # no deity, hand-in, hidden or foreign item
    belt = table.get("w9010")
    if belt:
        assert belt["name"] == "Test Kappa Belt" and belt["tier_rule"] == "fixed0" and belt["arrival"] == 0
        assert belt["source"] == f"vendor: {ZONE}" and belt["deity"] is None and belt["evidence"] == "wiki"
        assert belt["slots"] == ["WAIST"]
    some = next(iter(table.values()))
    assert some["tier_rule"] in ("drop", "fixed0") and some["evidence"] in ("strict", "wiki") and isinstance(some["slots"], list)
    assert {row["tier_rule"]: row["arrival"] for row in table.values()} == {"drop": 4, "fixed0": 0}  # whole tiers, as the site counts copies


def test_totals_are_the_whole_numbers_the_game_window_would_print_for_the_exact_kit(tiny):
    shard = read(tiny.dir / "wiki-group.json")
    rows = expand(shard)
    for (race, role, tier, setup), row in rows.items():
        solution, milp, profile, buffset = independent(CATALOG, tier, race, role, setup, "group", "wiki")
        kit = list(solution.kit)
        totals = eval_buff_totals(buffset.totals(solution.buffs))
        breakdown = fm.evaluate(profile.eval_profile, kit, totals, setup=setup, haste_assumed=milp.haste_assumed)
        gear = {k: sum(item.stats.get(k, 0) for item in kit if item) for k in ("HP", "MANA", "END")}
        window = fm.stat_window(TRIO, 50, breakdown.totals["attributes"], gear, {k: totals.get(k, 0) for k in ("HP", "MANA", "END")}, TABLES, profile.bands, nd_pct=profile.nd_pct)
        t = row["totals"]
        assert (t["hp"], t["mana"], t["end"]) == (window["HP"], window["MANA"], window["END"])
        assert t["ac"] == int(breakdown.totals["sheet"]["total"]) and t["haste"] == int(breakdown.totals["haste"]["counted"])
        assert t["atk"] == int(breakdown.totals["atk"])
        for school in ("fire", "cold", "magic", "poison", "disease"):
            assert t[school] == int(breakdown.totals["resists"][school.upper()]["counted"])
        for kind in ("hpreg", "manareg", "endreg"):
            assert t[kind] == int(breakdown.totals["regen"][kind.upper()]["counted"])
        assert abs(t["hp"] - breakdown.totals["pools"]["HP"]) < 12  # the window floors STA' first: under two pools of one point


def test_gain_is_the_value_over_the_empty_kit_of_the_same_race_role_and_buffs(tiny):
    for buffs in ("own", "group"):
        for evidence in ("strict", "wiki"):
            rows = expand(read(tiny.dir / f"{evidence}-{buffs}.json"))
            for (race, role, tier, setup), row in rows.items():
                empty, _, _, _ = independent([], 0, race, role, "dw", buffs, evidence)
                assert empty.kit == (None,) * 22
                assert row["gain"] == pytest.approx(row["F"] - empty.F, abs=0.011), (race, tier, setup, buffs, evidence)
                assert row["gain"] >= 0
    own = expand(read(tiny.dir / "wiki-own.json"))
    assert any(row["gain"] > 0 for row in own.values())


def test_the_strict_pool_is_empty_without_seen_flags_so_the_strict_shards_hold_naked_kits_and_say_so(tiny):
    for buffs in ("own", "group"):
        shard = read(tiny.dir / f"strict-{buffs}.json")
        assert shard["flags"] == ["strict pool empty"] and shard["pool"] == 0
        assert shard["kits"] == [[-1] * 22] and shard["items"] == []
        assert all(row[4] == 0 and row[6] == 0 for row in shard["scenarios"])  # the one empty kit, no gain
        assert len(shard["scenarios"]) == 2 * 1 * 2 * 2  # races x roles x tiers x setups: no shield in an empty pool, so two setups
        assert shard["setups"] == {"tank": ["2h", "dw"]}
    wiki = read(tiny.dir / "wiki-own.json")
    assert wiki["flags"] == ["strict pool empty"]  # the default view falls back to wiki evidence


def test_the_defaults_are_the_best_creation_legal_race_by_total_value_in_the_opening_build_plus_four_view(tiny):
    defaults = read(tiny.dir / "defaults.json")
    rows = expand(read(tiny.dir / "wiki-own.json"))
    best = {race: max(row["F"] for (r, role, tier, setup), row in rows.items() if r == race and role == "tank" and tier == 4) for race in ("OGR", "TRL")}
    winner, second = sorted(best, key=lambda race: -best[race])
    assert defaults["version"] == 1 and defaults["trio"] == SLUG
    assert defaults["view"] == {"role": "tank", "tier": 4, "evidence": "wiki", "buffs": "own"}
    assert defaults["strict_pool_empty"] is True
    assert (defaults["race"], defaults["runner_up_race"]) == (winner, second)
    assert defaults["margin"] == pytest.approx(best[winner] - best[second], abs=0.011)
    assert defaults["setup"] in ("1h-shield", "2h", "dw")
    by_setup = {setup: row["F"] for (r, role, tier, setup), row in rows.items() if r == winner and role == "tank" and tier == 4}
    assert by_setup[defaults["setup"]] == max(by_setup.values())
    assert {entry["race"] for entry in defaults["races"]} == {"OGR", "TRL"} and all(entry["legal"] for entry in defaults["races"])
    assert defaults["flip_notes"] == [] and defaults["robustness"] == "skipped: disabled"


def test_the_defaults_carry_the_why_of_the_default_kit_each_stat_valued_again_without_it(tiny):
    """p7kit: ``why.places`` has the 22 places of the default race's kit; the loss of a stat is the exact value of the kit less its value without that stat (``evaluate_truthful`` both times)."""
    defaults = read(tiny.dir / "defaults.json")
    row = expand(read(tiny.dir / "wiki-own.json"))[(defaults["race"], "tank", 4, defaults["setup"])]
    places = defaults["why"]["places"]
    assert [place["key"] if place else None for place in places] == row["kit"]
    _, _, profile, buffset = independent(CATALOG, 4, defaults["race"], "tank", defaults["setup"], "own", "wiki")
    totals = eval_buff_totals(buffset.totals(tuple(row["buffs"])))
    vecs = {item["key"]: at_tier(item, 4, RULES) for item in CATALOG}
    kit = [vecs[key] if key else None for key in row["kit"]]
    base = fm.evaluate_truthful(profile.eval_profile, kit, totals, setup=defaults["setup"]).F
    checked = 0
    for index, place in enumerate(places):
        if place is None:
            continue
        item = kit[index]
        assert [term[0] for term in place["loss"]] == sorted((term[0] for term in place["loss"]), key=lambda t: -dict((x[0], x[1]) for x in place["loss"])[t])
        for term, loss, reason in place["loss"]:
            if term == "HASTE":
                changed = dataclasses.replace(item, haste=0)
            elif term == "DAMAGE":
                changed = dataclasses.replace(item, weapon=None)
            elif term in fm.SCHOOLS:
                changed = dataclasses.replace(item, sv={k: v for k, v in item.sv.items() if k != term})
            else:
                changed = dataclasses.replace(item, stats={k: v for k, v in item.stats.items() if k != term})
            trial = list(kit)
            trial[index] = changed
            assert loss == float(base - fm.evaluate_truthful(profile.eval_profile, trial, totals, setup=defaults["setup"]).F), (index, term)
            assert (reason is None) or loss == 0.0
            checked += 1
    assert checked >= 5  # (the invented kit carries something)


def test_the_default_race_ignores_a_better_race_that_cannot_be_created_and_breaks_ties_in_race_order():
    f = {"ELF": 120.0, "OGR": 100.0, "TRL": 90.0, "KER": 95.0}
    choice = shards.default_race(f, {"OGR", "TRL", "KER"}, ["HUM", "ELF", "OGR", "TRL", "KER"], 1)
    assert (choice["race"], choice["runner_up"], choice["margin"]) == ("OGR", "KER", 5.0)
    tie = shards.default_race({"TRL": 50.0, "OGR": 50.0}, {"OGR", "TRL"}, ["OGR", "TRL"], 1)
    assert (tie["race"], tie["runner_up"], tie["margin"]) == ("OGR", "TRL", 0.0)
    assert shards.default_race({"ELF": 1.0}, set(), ["ELF"], 1) is None
    one = shards.default_race({"OGR": 1.0, "ELF": 5.0}, {"OGR"}, ["OGR", "ELF"], 1)
    assert one["race"] == "OGR" and one["runner_up"] is None and one["margin"] is None


def test_runner_ups_are_exact_swaps_three_plain_ones_and_at_most_one_deity_locked_one_that_beats_them(tiny):
    assert (grid.RUNNER_UPS, grid.DEITY_RUNNER_UPS) == (3, 1)
    docs = runnerup_docs(tiny.dir)
    assert sorted(docs) == [("tank", 0), ("tank", 4)]  # one file for each role holds both tiers
    wiki_own = read(tiny.dir / "wiki-own.json")
    rows = expand(wiki_own)
    situations = {"beats": 0, "too weak": 0, "tie": 0, "no plain swap": 0}
    views = []
    for (role, tier), doc in docs.items():
        assert doc["version"] == 1 and doc["evidence"] == "wiki" and doc["buffs"] == "own" and doc["evidence_fallback"] is True
        assert doc["places"] == list(shards.PLACES) and (doc["role"], doc["tier"]) == (role, tier)
        items = {i: dict(zip(doc["items_keys"], row)) for i, row in enumerate(doc["items"])}
        assert [len(view[2]) for view in doc["views"]] == [22, 22]  # a view for each race, with a list for each place
        views += [(race, role, tier, setup, slots, items) for race, setup, slots in doc["views"]]
    assert len(views) == 2 * 1 * 2  # race x role x tier, for the default assumptions only
    for race, role, tier, setup, slots, items in views:
        best_setup = max(("1h-shield", "2h", "dw"), key=lambda s: (rows[(race, role, tier, s)]["F"], -["1h-shield", "2h", "dw"].index(s)))
        assert setup == best_setup
        assert len(slots) == 22
        solution, milp, profile, buffset = independent(CATALOG, tier, race, role, setup, "own", "wiki")
        kit = list(solution.kit)
        assert [item.key if item else None for item in kit] == rows[(race, role, tier, setup)]["kit"]
        totals = eval_buff_totals(buffset.totals(solution.buffs))
        ep = profile.eval_profile

        def value(trial):  # a swapped kit is valued at the haste it counts
            return fm.evaluate_truthful(ep, trial, totals, setup=setup).F

        base = value(kit)
        pool = {i["key"]: at_tier(i, tier, RULES) for i in CATALOG if i["evidence"]["level"] == "wiki" and set(i["slots"]) & WEARABLE
                and not any(r["code"] == "not-for-bis" for r in i["evidence"]["reasons"]) and ("ALL" in i["classes"] or set(i["classes"]) & set(TRIO))}  # fmt: skip
        for index, place in enumerate(SLOT_INSTANCES):
            plain, locked = [], []  # (delta, key) of every legal swap, by whether the item is locked to a deity
            for cand in pool.values():
                fits = ("ANY" in cand.slots or any(s in WEARABLE for s in cand.slots)) if place == "ANY" else place in cand.slots
                if not fits or (place in ("PRIMARY", "SECONDARY") and not wp.allowed_in_hand(cand, place.lower(), setup)):
                    continue
                if kit[index] is not None and cand.key == kit[index].key:
                    continue
                if cand.lore and any(k is not None and k.key == cand.key for j, k in enumerate(kit) if j != index):
                    continue
                trial = list(kit)
                trial[index] = cand
                if place == "PRIMARY" and cand.weapon and cand.weapon.two_handed and trial[SLOT_INSTANCES.index("SECONDARY")] is not None:
                    continue
                (locked if cand.deity else plain).append((float(value(trial) - base), cand.key))
            plain.sort(key=lambda t: (-t[0], t[1]))
            locked.sort(key=lambda t: (-t[0], t[1]))
            expected = plain[:3]
            beats = bool(locked) and (not plain or locked[0][0] > plain[0][0])  # only a locked swap that beats the best plain one
            if beats:
                expected = sorted([*expected, locked[0]], key=lambda t: (-t[0], t[1]))
            got = [(delta, items[i]["key"]) for i, delta in slots[index]]
            assert len(got) == len(expected) and len(got) <= 4, (race, tier, place, got, expected)
            for (delta, key), (want_delta, want_key) in zip(got, expected):
                assert key == want_key and delta == pytest.approx(want_delta, abs=0.006), (race, tier, place, got, expected)
            assert [d for d, _ in got] == sorted((d for d, _ in got), reverse=True)
            got_locked = [i for i, _ in slots[index] if items[i]["deity"] is not None]
            assert len(got_locked) == (1 if beats else 0), (race, tier, place)
            if locked and plain:
                situations["beats" if beats else "tie" if locked[0][0] == plain[0][0] else "too weak"] += 1
            elif locked:
                situations["no plain swap"] += 1
            for i, delta in slots[index]:
                if items[i]["deity"] is None:
                    assert delta <= 1e-9  # the kit is the best there is, so no swap of a plain item can beat it
                else:
                    assert items[i]["deity"] in (["Tunare"], ["Karana"], ["Brell Serilis", "Karana"])  # the badge names the deity
    assert all(situations.values()), situations  # each case was met: beats, too weak, a tie (the plain swap stays), nothing else


def test_the_robust_file_is_skipped_with_a_note_when_the_module_is_missing_and_stale_copies_are_removed(fresh, monkeypatch):
    (fresh.dir / "robust.json").write_text(json.dumps({"rules_version": RULES.version}), encoding="utf-8")  # (a file of an earlier run of these rules: one with no rules version is old, and the run refuses it)
    monkeypatch.setitem(__import__("sys").modules, "trioforge.solver.robust", None)  # importing it fails
    summary = pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, **TINY_GRID)
    assert not (fresh.dir / "robust.json").exists()
    assert any("robustness" in note and "skipped" in note for note in summary.notes)


def test_runner_ups_are_one_file_for_each_role_with_every_tier_of_the_scope_and_an_index_lists_them_with_sizes_and_hashes(tiny):
    folder = tiny.dir / "runnerups"
    index = read(folder / "index.json")
    assert (index["version"], index["trio"], index["evidence"], index["buffs"]) == (1, SLUG, "wiki", "own")
    assert index["evidence_fallback"] is True and index["data_release"] == "data-2030-01-02" and index["rules_version"] == RULES.version
    assert [(f["role"], f["tiers"], f["file"]) for f in index["files"]] == [("tank", [0, 4], "tank.json")]  # a role, and all the tiers of the run in it
    assert sorted(p.name for p in folder.iterdir()) == sorted([*(f["file"] for f in index["files"]), "index.json"])
    for entry in index["files"]:
        data = (folder / entry["file"]).read_bytes()
        assert entry["bytes"] == len(data) and entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["bytes"] == len(data.decode("utf-8").encode("utf-8"))  # whole UTF-8, no escapes
        assert entry["gzip"] == len(gzip.compress(data, 9)) and entry["gzip"] < entry["bytes"]
        assert list(entry) == ["file", "role", "tiers", "bytes", "gzip", "sha256"]
    for entry in index["files"]:
        doc = read(folder / entry["file"])
        assert list(doc) == [
            "version", "trio", "classes", "level", "data_release", "game_patch", "rules_version", "evidence", "buffs", "evidence_fallback", "role",
            "tiers", "places", "items_keys", "items", "views",
        ]  # fmt: skip
        assert doc["trio"] == SLUG and doc["classes"] == list(TRIO) and doc["data_release"] == index["data_release"]
        assert doc["role"] == entry["role"] and doc["tiers"] == entry["tiers"] == read(tiny.dir / "wiki-own.json")["tiers"]  # the scope the shards record
        assert doc["places"] == list(shards.PLACES) and doc["items_keys"] == list(shards.ITEM_KEYS)
        assert [view[:2] for view in doc["views"]] == [[0, "TRL"], [0, "OGR"], [4, "TRL"], [4, "OGR"]]  # by tier, the races in display order within it
        assert all(len(view) == 4 and view[2] in ("1h-shield", "2h", "dw") and len(view[3]) == 22 for view in doc["views"])
        used = {item for view in doc["views"] for place in view[3] for item, _ in place}
        assert used == set(range(len(doc["items"])))  # the item table is one for the file, and holds what the entries of every tier point at and no more
        assert [row[0] for row in doc["items"]] == sorted(row[0] for row in doc["items"])
        assert any(row[7] for row in doc["items"])  # a badge names the deity of a locked item


def test_a_name_with_a_character_of_two_bytes_is_written_as_utf_8_and_counted_in_bytes(tiny):
    folder = tiny.dir / "runnerups"
    index = read(folder / "index.json")
    sizes = {entry["file"]: entry["bytes"] for entry in index["files"]}
    names = [row[1] for (role, tier), doc in runnerup_docs(tiny.dir).items() for row in doc["items"]]
    assert "Test Om\u00e9ga Shoulders" in names
    for file, size in sizes.items():
        text = (folder / file).read_text(encoding="utf-8")
        assert size == len(text.encode("utf-8")) and (size > len(text) if "Om\u00e9ga" in text else size == len(text))


def test_result_files_are_replaced_in_a_safe_order_the_runner_ups_before_the_rest_and_each_folders_last_file_last(fresh, monkeypatch):
    real, order = os.replace, []

    def spy(source, target, *args, **kwargs):
        order.append(Path(target).relative_to(fresh.dir).as_posix())
        return real(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "replace", spy)
    pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, **TINY)  # every chunk is whole: only result files are written
    monkeypatch.undo()
    runner_ups = [name for name in order if name.startswith("runnerups/")]
    rest = [name for name in order if not name.startswith("runnerups/")]
    assert order == [*runner_ups, *rest] and len(runner_ups) == 2 and len(rest) == 6  # the four shards, the bundle, the defaults
    assert runner_ups[-1] == "runnerups/index.json" and rest[-1] == "defaults.json"


def test_the_old_single_runner_up_file_and_files_of_a_wider_earlier_run_are_removed(fresh):
    stamped = json.dumps({"rules_version": RULES.version})  # (files of an earlier run of these rules: one with no rules version is old, and the run refuses it)
    (fresh.dir / "runnerups.json").write_text(stamped, encoding="utf-8")
    (fresh.dir / "runnerups" / "melee.json").write_text(stamped, encoding="utf-8")  # a role this run does not have
    (fresh.dir / "runnerups" / "tank-0.json").write_text(stamped, encoding="utf-8")  # and the file of a role and tier, as an earlier layout wrote it
    before = result_files(fresh.dir)
    summary = pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, **TINY)
    gone = ("runnerups.json", "runnerups/melee.json", "runnerups/tank-0.json")
    assert not any((fresh.dir / name).exists() for name in gone)
    after = result_files(fresh.dir)
    assert sorted(after) == sorted(name for name in before if name not in gone)
    assert [f["file"] for f in read(fresh.dir / "runnerups" / "index.json")["files"]] == ["tank.json"]
    assert any(path.name == "index.json" for path in summary.files) and "runnerups/index.json" in summary.sizes


def test_a_grid_without_the_default_views_writes_no_runner_up_folder(tmp_path):
    catalog = write_catalog(tmp_path / "catalog.json")
    narrow = {**TINY, "evidence": ("strict",), "buffs": ("group",)}  # the default view is wiki evidence with own buffs
    pc.run(SLUG, tmp_path / "out", catalog=catalog, processes=1, **narrow)
    assert not (tmp_path / "out" / SLUG / "runnerups").exists() and (tmp_path / "out" / SLUG / "strict-group.json").is_file()


def test_robust_json_holds_the_labels_of_the_robustness_hook_per_role_and_tier_at_the_default_race(fresh):
    calls = []

    def hook(scenario):
        calls.append((scenario.race, scenario.role, scenario.tier))
        return {place: ("robust" if n % 2 else f"depends on AC (test B{n})") for n, place in enumerate(shards.PLACES)}

    summary = pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, robustness=hook, **TINY_GRID)
    doc = read(fresh.dir / "robust.json")
    default = read(fresh.dir / "defaults.json")["race"]
    assert doc["version"] == 1 and doc["race"] == default and doc["tiers"] == [4]  # tier 10 is not in this grid
    assert set(doc["roles"]) == {"tank"} and set(doc["roles"]["tank"]) == {"4"}
    labels = doc["roles"]["tank"]["4"]
    assert set(labels) == set(shards.PLACES) and labels["HEAD"].startswith("depends on") and labels["FACE"] == "robust"
    assert calls == [(default, "tank", 4)]
    assert not any("skipped" in n for n in summary.notes if "robustness" in n)
    assert read(fresh.dir / "defaults.json")["robustness"] == "done"


# ---- resuming, stopping, safety ----------------------------------------------------------------------------------------


def test_a_rerun_skips_finished_chunks_and_gives_the_same_files(fresh, tiny):
    before = result_files(fresh.dir)
    assert "runnerups/index.json" in before and "wiki-own.json" in before
    summary = pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, **TINY)
    assert (summary.chunks, summary.reused, summary.redone, summary.solved) == (TINY_CHUNKS, TINY_CHUNKS, 0, 0)
    assert result_files(fresh.dir) == before


def test_a_corrupted_chunk_is_redone(fresh):
    before = result_files(fresh.dir)
    files = sorted(c for c in (fresh.dir / "chunks").glob("s-*.json"))
    files[0].write_bytes(files[0].read_bytes()[:40])  # cut short
    doc = json.loads(files[1].read_text(encoding="utf-8"))
    doc["rows"][0]["F"] += 1.0
    files[1].write_text(json.dumps(doc), encoding="utf-8")  # still JSON, but the checksum no longer fits
    files[2].write_text("", encoding="utf-8")  # empty
    summary = pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, **TINY)
    assert (summary.reused, summary.redone) == (TINY_CHUNKS - 3, 3)
    assert summary.solved == 3 * 2  # two races a chunk
    assert result_files(fresh.dir) == before


def test_chunks_made_from_another_catalog_are_redone(fresh, tmp_path):
    changed = copy.deepcopy(CATALOG)
    changed[0]["stats"]["STA"] = 11
    other = write_catalog(tmp_path / "other.json", changed)
    summary = pc.run(SLUG, fresh.out, catalog=other, processes=1, **TINY)
    assert summary.reused == 0 and summary.redone == TINY_CHUNKS


def test_chunks_made_by_other_code_are_redone_so_a_fixed_solver_never_serves_old_answers(fresh, monkeypatch):
    assert len(grid._code_hash()) == 64 and grid._code_hash() == grid._code_hash()
    monkeypatch.setattr(grid, "_code_hash", lambda: "the solver after a fix")
    summary = pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, **TINY)
    assert (summary.reused, summary.redone, summary.solved) == (0, TINY_CHUNKS, TINY_SCENARIOS)
    assert summary.runnerup_reused == 0 and any("redone" in note for note in summary.notes)


def test_an_exactness_error_stops_the_run_with_a_clear_message_and_writes_no_shard(tmp_path, monkeypatch):
    catalog = write_catalog(tmp_path / "catalog.json")

    def broken(milp, time_limit=None):
        raise ExactnessError("the model's objective 1.0 and the evaluator's value 2.0 of its kit differ by more than 1e-06 relative")

    monkeypatch.setattr(solve_module, "solve_canonical", broken)
    out = tmp_path / "out"
    with pytest.raises(pc.PrecomputeError) as caught:
        pc.run(SLUG, out, catalog=catalog, processes=1, **TINY)
    message = str(caught.value)
    assert "objective re-check" in message and "differ by more than" in message
    assert "TRL" in message and "tank role" in message and "+0" in message  # which scenario
    assert not list((out / SLUG).glob("*.json"))  # no shard, no defaults: only chunks may exist


def test_a_check_that_fails_outside_the_workers_is_also_one_clear_error(tmp_path, monkeypatch):
    catalog = write_catalog(tmp_path / "catalog.json")

    def broken(self, race, role, buffs):
        raise ExactnessError("the model and the oracle disagree about the naked character")

    monkeypatch.setattr(grid.Context, "empty_value", broken)
    with pytest.raises(pc.PrecomputeError, match="objective re-check failed for the naked character"):
        pc.run(SLUG, tmp_path / "out", catalog=catalog, processes=1, **TINY)

    def hook(scenario):
        raise KeyError("a place")

    monkeypatch.undo()
    with pytest.raises(pc.PrecomputeError) as caught:
        pc.run(SLUG, tmp_path / "out2", catalog=catalog, processes=1, robustness=hook, **TINY_GRID)
    assert all(part in str(caught.value) for part in ("robustness hook failed", "tank +4", "KeyError"))


def test_a_solve_that_is_not_optimal_stops_the_run(tmp_path, monkeypatch):
    catalog = write_catalog(tmp_path / "catalog.json")
    real = solve_module.solve_canonical

    def limited(milp, time_limit=None):
        solution = real(milp, time_limit)
        return solution.__class__(**{**solution.__dict__, "status": "time_limit"})

    monkeypatch.setattr(solve_module, "solve_canonical", limited)
    with pytest.raises(pc.PrecomputeError, match="time_limit"):
        pc.run(SLUG, tmp_path / "out", catalog=catalog, processes=1, **TINY)


def test_seen_flags_are_merged_only_into_a_folder_under_build_or_outside_the_repository(tmp_path, monkeypatch):
    catalog = write_catalog(tmp_path / "catalog.json")
    seen = write_seen(tmp_path / "seen.json", {"w9001", "w9006", "w9011"})
    fake_repo = tmp_path / "repo"
    (fake_repo / "build").mkdir(parents=True)
    (fake_repo / "derived").mkdir()
    monkeypatch.setattr(catalog_module, "REPO_ROOT", fake_repo)
    for forbidden in (fake_repo / "derived" / "results", fake_repo / "results", fake_repo):
        with pytest.raises(pc.PrecomputeError, match="refused"):
            pc.run(SLUG, forbidden, seen_path=seen, catalog=catalog, processes=1, **TINY)
    assert not (fake_repo / "derived" / "results").exists() and not (fake_repo / "results").exists()
    assert not list(fake_repo.glob("*.json"))
    inside = fake_repo / "build" / "results"
    summary = pc.run(SLUG, inside, seen_path=seen, catalog=catalog, processes=1, **TINY)
    assert (inside / SLUG / "wiki-own.json").is_file() and not summary.violations
    elsewhere = tmp_path / "elsewhere"  # outside the repository: allowed
    pc.run(SLUG, elsewhere, seen_path=seen, catalog=catalog, processes=1, **TINY)
    assert (elsewhere / SLUG / "strict-own.json").is_file()


def test_bad_inputs_are_refused_with_one_clear_error(tmp_path):
    catalog = write_catalog(tmp_path / "catalog.json")
    (tmp_path / "seen.json").write_text(json.dumps({"keys": ["not a key"]}), encoding="utf-8")
    with pytest.raises(pc.PrecomputeError, match="seen-flags"):
        pc.run(SLUG, tmp_path / "out", seen_path=tmp_path / "seen.json", catalog=catalog, processes=1, **TINY)
    (tmp_path / "bad.json").write_text("[1, 2", encoding="utf-8")
    with pytest.raises(pc.PrecomputeError, match="bad.json"):
        pc.run(SLUG, tmp_path / "out", catalog=tmp_path / "bad.json", processes=1, **TINY)
    (tmp_path / "notacatalog.json").write_text(json.dumps({"items": [{"name": "x"}], "version": "2030-01-01"}), encoding="utf-8")
    with pytest.raises(pc.PrecomputeError, match="evidence"):
        pc.run(SLUG, tmp_path / "out", catalog=tmp_path / "notacatalog.json", processes=1, **TINY)
    with pytest.raises(pc.PrecomputeError, match="trio"):
        pc.run("pal-mnk", tmp_path / "out", catalog=catalog, processes=1, **TINY)
    with pytest.raises(pc.PrecomputeError, match="race"):
        pc.run(SLUG, tmp_path / "out", catalog=catalog, processes=1, races=("XXX",), robustness=False)
    assert not (tmp_path / "out").exists()  # nothing was made for a run that never started


def test_with_seen_flags_the_strict_pool_has_those_items_and_the_defaults_use_strict_evidence(tmp_path):
    catalog = write_catalog(tmp_path / "catalog.json")
    keys = {"w9001", "w9006", "w9011", "w9099"}
    seen = write_seen(tmp_path / "seen.json", keys)
    out = tmp_path / "out"
    summary = pc.run(SLUG, out, seen_path=seen, catalog=catalog, processes=1, **TINY)
    strict = read(out / SLUG / "strict-own.json")
    assert strict["flags"] == [] and strict["pool"] == 3
    worn = {row[0] for row in strict["items"]}
    assert worn <= {"w9001", "w9006", "w9011"} and worn
    assert {row[0]: row[6] for row in strict["items"]} == dict.fromkeys(worn, "strict")
    wiki = read(out / SLUG / "wiki-own.json")
    badges = {row[0]: row[6] for row in wiki["items"]}
    assert all(badge == "strict" for key, badge in badges.items() if key in keys) and "wiki" in badges.values()
    defaults = read(out / SLUG / "defaults.json")
    assert defaults["view"]["evidence"] == "strict" and defaults["strict_pool_empty"] is False
    assert read(out / SLUG / "runnerups" / "tank.json")["evidence"] == "strict"
    assert read(out / SLUG / "runnerups" / "index.json")["evidence"] == "strict"
    assert any("unknown" in n for n in summary.notes)  # w9099 is not in the catalog
    # the strict value is never above the wiki value of the same scenario, and never below the naked character
    rows_s, rows_w = expand(strict), expand(wiki)
    assert all(rows_s[k]["F"] <= rows_w[k]["F"] + 1e-6 for k in rows_s)
    assert all(row["gain"] >= 0 for row in rows_s.values())
    for path in (out / SLUG).rglob("*.json"):  # the seen file and its path are in no output
        assert "seen.json" not in path.read_text(encoding="utf-8") and str(seen) not in path.read_text(encoding="utf-8")


def test_the_plain_solve_is_recorded_in_the_shards_and_gives_the_same_values(tiny, tmp_path):
    out = tmp_path / "out"
    summary = pc.run(SLUG, out, catalog=tiny.catalog, processes=1, canonical=False, **TINY)
    assert summary.canonical is False and read(out / SLUG / "wiki-own.json")["solver"]["canonical"] is False
    plain, canonical = read(out / SLUG / "wiki-own.json"), read(tiny.dir / "wiki-own.json")
    assert [row[5] for row in plain["scenarios"]] == [row[5] for row in canonical["scenarios"]]  # a tie changes the kit, not F


def test_a_lore_item_worn_in_the_kit_is_not_offered_as_a_swap_for_another_place_of_the_same_kit(tiny):
    rows = expand(read(tiny.dir / "wiki-own.json"))
    assert "w9004" in rows[("OGR", "tank", 4, "dw")]["kit"]  # the Lore ring is worn once
    docs = runnerup_docs(tiny.dir)
    assert docs  # there are files to look at
    for (role, tier), doc in docs.items():
        keys = [row[0] for row in doc["items"]]
        for race, setup, slots in doc["views"]:
            worn = rows[(race, role, tier, setup)]["kit"]
            lore_places = [i for i, key in enumerate(worn) if key == "w9004"]
            for index in range(22):
                offered = [keys[item] for item, _ in slots[index]]
                if lore_places and index not in lore_places:
                    assert "w9004" not in offered, (race, tier, shards.PLACES[index])  # already worn elsewhere in the kit


def test_a_two_hander_is_not_offered_for_the_main_hand_while_the_off_hand_is_worn(tmp_path):
    catalog = write_catalog(tmp_path / "catalog.json")
    config, _ = grid.load_inputs(TRIO, catalog_path=catalog)
    ctx = grid.Context(config)
    primary, secondary = SLOT_INSTANCES.index("PRIMARY"), SLOT_INSTANCES.index("SECONDARY")
    shielded, bare = [None] * 22, [None] * 22
    shielded[primary], shielded[secondary], bare[primary] = "w9011", "w9014", "w9011"
    # the stat stick lets any item into any hand; the pool has two other main-hand items besides the worn Sword
    doc = grid.runnerup_chunk(
        ctx, "tank", 4, [grid.RunnerupInput("OGR", "stick", tuple(shielded), (), 0), grid.RunnerupInput("TRL", "stick", tuple(bare), (), 0)]
    )
    with_shield, without = (view["places"][primary] for view in doc["views"])
    assert "w9013" not in [key for key, _ in with_shield]  # the Greatsword would have to empty the worn off hand
    assert {"w9012", "w9013"} <= {key for key, _ in without}  # with a free off hand it is a legal swap


@pytest.mark.parametrize("processes", [1, 2])
def test_a_failure_inside_a_worker_stops_the_run_with_the_scenario_and_the_reason(tmp_path, processes):
    broken = [*CATALOG, make_item("w9090", "Test Broken Ring", ["FINGER"], stats={"FOO": 3})]
    catalog = write_catalog(tmp_path / "catalog.json", broken)
    with pytest.raises(pc.PrecomputeError) as caught:
        pc.run(SLUG, tmp_path / "out", catalog=catalog, processes=processes, **TINY)
    message = str(caught.value)
    assert "ValueError" in message and "w9090" in message and "FOO" in message and "evidence" in message
    assert not list((tmp_path / "out" / SLUG).glob("*.json"))


def test_worker_processes_are_refused_when_the_main_program_cannot_be_started_again(tmp_path, monkeypatch):
    # a worker is a new interpreter that runs the main program again; a script read from stdin cannot be run again, the
    # worker dies before it has read its settings, and the parent would wait for it for ever
    from types import SimpleNamespace

    stdin_script = SimpleNamespace(__file__="<stdin>", __spec__=None)
    gone = SimpleNamespace(__file__=str(tmp_path / "no-such-script.py"), __spec__=None)
    for bad in (stdin_script, gone):
        with pytest.raises(pc.PrecomputeError, match="processes=1"):
            pc._check_workers_can_start(bad)
    here = SimpleNamespace(__file__=str(Path(__file__)), __spec__=None)  # a script file
    module = SimpleNamespace(__file__="<stdin>", __spec__=object())  # python -m
    interactive = SimpleNamespace(__spec__=None)  # a session or python -c: no file to run again
    for fine in (here, module, interactive, None):
        pc._check_workers_can_start(fine)
    catalog = write_catalog(tmp_path / "catalog.json")
    monkeypatch.setitem(sys.modules, "__main__", stdin_script)
    with pytest.raises(pc.PrecomputeError, match="processes=1"):
        pc.run(SLUG, tmp_path / "out", catalog=catalog, processes=2, **TINY)
    assert not (tmp_path / "out").exists()  # refused before anything was made
    monkeypatch.undo()
    pc._check_workers_can_start(sys.modules["__main__"])  # the test runner itself can start workers


def test_the_limit_stops_after_that_many_chunks_without_writing_shards_and_a_later_run_finishes_the_rest(tmp_path):
    catalog = write_catalog(tmp_path / "catalog.json")
    out = tmp_path / "out"
    first = pc.run(SLUG, out, catalog=catalog, processes=1, limit=5, **TINY)
    assert first.partial is True and first.solved == 5 * 2 and first.chunks == TINY_CHUNKS
    assert len(list((out / SLUG / "chunks").glob("*.json"))) == 5
    assert not list((out / SLUG).glob("*.json"))
    assert any("limit" in n for n in first.notes)
    second = pc.run(SLUG, out, catalog=catalog, processes=1, **TINY)
    assert second.reused == 5 and second.solved == (TINY_CHUNKS - 5) * 2
    assert (out / SLUG / "wiki-own.json").is_file()


def test_worker_processes_write_the_same_files_as_one_process(tiny, tmp_path):
    out = tmp_path / "out"
    summary = pc.run(SLUG, out, catalog=tiny.catalog, processes=2, **TINY)
    assert summary.solved == TINY_SCENARIOS and not summary.violations
    assert result_files(out / SLUG) == result_files(tiny.dir) and "runnerups/tank.json" in result_files(tiny.dir)


def test_the_pruned_pool_does_not_depend_on_the_race():
    pool = [at_tier(i, 4, RULES) for i in eligible(CATALOG, "wiki")]
    buffset = buffset_of("own")
    kept = {}
    for race in ("OGR", "IKS", "HUM", "ERU"):
        profile = make_profile(race, TRIO, 50, "tank", buffset, None, TABLES, evidence="wiki")
        for setup in ("1h-shield", "2h", "dw"):
            kept.setdefault(setup, set()).add(tuple(i.key for i in prune(pool, profile, 4, setup, buffset)))
    assert all(len(variants) == 1 for variants in kept.values())  # the chunk prunes once for all its races


# ---- following the solver and model fixes ------------------------------------------------------------------------------


def context_of(tmp_path, items):
    config, _ = grid.load_inputs(TRIO, catalog_path=write_catalog(tmp_path / "catalog.json", items))
    return grid.Context(config)


def test_the_profile_of_a_view_follows_the_pool_so_the_shield_setup_needs_a_shield_the_race_can_wear(tmp_path):
    ctx = context_of(tmp_path, CATALOG)
    assert ctx.profile("OGR", "tank", "own", "wiki").setups == ("1h-shield", "2h", "dw")
    assert ctx.profile("OGR", "melee", "own", "wiki").setups == ("2h", "dw")
    assert ctx.profile("OGR", "tank", "own", "strict").setups == ("2h", "dw")  # the strict pool is empty: no shield in it
    no_shield = [item for item in CATALOG if item["key"] != "w9014"]
    ctx = context_of(tmp_path, no_shield)
    assert ctx.profile("OGR", "tank", "own", "wiki").setups == ("2h", "dw")
    only_trolls = [{**item, "races": ["TRL"]} if item["key"] == "w9014" else item for item in CATALOG]
    ctx = context_of(tmp_path, only_trolls)
    assert ctx.profile("TRL", "tank", "own", "wiki").setups == ("1h-shield", "2h", "dw")
    assert ctx.profile("OGR", "tank", "own", "wiki").setups == ("2h", "dw")  # an Ogre can wear no shield of this pool
    assert ctx.profile("TRL", "tank", "own", "wiki") is ctx.profile("TRL", "tank", "own", "wiki")  # still made once


def test_the_grid_lists_the_shield_setup_only_when_the_pool_has_a_shield_for_the_trio(tmp_path):
    no_shield = [item for item in CATALOG if item["key"] != "w9014"]
    out = tmp_path / "out"
    summary = pc.run(SLUG, out, catalog=write_catalog(tmp_path / "catalog.json", no_shield), processes=1, **TINY)
    assert (summary.scenarios, summary.chunks) == (2 * 2 * 2 * 2 * 2, 2 * 2 * 2 * 2)  # races x setups x tiers x evidence x buffs
    for name in shards.SHARD_NAMES:
        shard = read(out / SLUG / name)
        assert shard["setups"] == {"tank": ["2h", "dw"]}
        assert {row[3] for row in shard["scenarios"]} == {"2h", "dw"}
    assert not list((out / SLUG / "chunks").glob("*1h-shield*"))
    assert all(view[1] in ("2h", "dw") for doc in runnerup_docs(out / SLUG).values() for view in doc["views"])
    # grid.scenarios on its own: no pool at all assumes a shield (the 3,520 of the design), a pool decides
    assert len(grid.scenarios(TRIO, TABLES, RULES)) == 3520
    pool = [at_tier(item, 0, RULES) for item in no_shield]
    assert len(grid.scenarios(TRIO, TABLES, RULES, items=pool)) == 16 * 4 * 11 * 2 * 2
    assert not [s for s in grid.scenarios(TRIO, TABLES, RULES, items=pool) if s.setup == "1h-shield"]


def test_a_shield_that_only_some_races_wear_still_makes_the_shield_setup_a_setup_of_the_trio(tmp_path):
    only_trolls = [{**item, "races": ["TRL"]} if item["key"] == "w9014" else item for item in CATALOG]
    out = tmp_path / "out"
    pc.run(SLUG, out, catalog=write_catalog(tmp_path / "catalog.json", only_trolls), processes=1, **TINY)
    assert read(out / SLUG / "wiki-own.json")["setups"] == {"tank": ["1h-shield", "2h", "dw"]}  # one grid for every race
    rows = expand(read(out / SLUG / "wiki-own.json"))
    assert "w9014" not in rows[("OGR", "tank", 4, "1h-shield")]["kit"]  # an Ogre cannot wear it
    assert any("w9014" in rows[("TRL", "tank", tier, "1h-shield")]["kit"] for tier in (0, 4))


# ---- the setups of an evidence level follow the pool of that level ---------------------------------------------------------------


def with_seen(tmp_path, keys, **options):
    """A tiny run (two races, the Tank build, +0 and +4) of the invented catalog with the given keys seen in game; returns
    the summary and the folder of the results. ``keys`` decide the strict pool: a wiki item that is seen is strict."""
    out = tmp_path / "out"
    summary = pc.run(
        SLUG, out, seen_path=write_seen(tmp_path / "seen.json", keys), catalog=write_catalog(tmp_path / "catalog.json"),
        processes=1, **{**TINY, **options},
    )  # fmt: skip
    return summary, out / SLUG


def test_each_evidence_level_lists_the_shield_setup_only_when_its_own_pool_has_a_shield_for_the_trio():
    sword = at_tier(next(i for i in CATALOG if i["key"] == "w9011"), 0, RULES)
    shield = at_tier(next(i for i in CATALOG if i["key"] == "w9014"), 0, RULES)  # a Paladin or a Berserker can wear it
    plan = grid.scenarios(TRIO, TABLES, RULES, items={"strict": [sword], "wiki": [sword, shield]})
    pairs = {kind: {(s.role, s.setup) for s in plan if s.evidence == kind} for kind in ("strict", "wiki")}
    assert pairs["strict"] == {("tank", "2h"), ("tank", "dw"), ("melee", "2h"), ("melee", "dw")}
    assert pairs["wiki"] == pairs["strict"] | {("tank", "1h-shield")}
    assert len(plan) == 16 * 11 * 2 * (4 + 5)  # races x tiers x buff sets x the build and setup pairs of the two levels
    assert not [s for s in plan if s.evidence == "strict" and s.setup == "1h-shield"]
    levels = list(dict.fromkeys((s.evidence, s.buffs) for s in plan))  # the order of the module docstring: the levels in turn
    assert levels == [("strict", "own"), ("strict", "group"), ("wiki", "own"), ("wiki", "group")]
    # a flat pool is the pool of both levels, and no pool at all assumes a shield: the 3,520 scenarios of the design
    assert {s.setup for s in grid.scenarios(TRIO, TABLES, RULES, items=[sword, shield]) if s.evidence == "strict"} == {"1h-shield", "2h", "dw"}
    assert len(grid.scenarios(TRIO, TABLES, RULES)) == 3520
    # a level that is asked for needs a pool of its own; one that is not asked for does not
    with pytest.raises(ValueError, match="strict"):
        grid.scenarios(TRIO, TABLES, RULES, items={"wiki": [sword, shield]})
    wiki_only = grid.scenarios(TRIO, TABLES, RULES, evidence=("wiki",), items={"wiki": [sword, shield]})
    assert len(wiki_only) == 16 * 11 * 2 * 5  # (the Tank's three setups and the Melee damage build's two)


def test_the_shield_pool_of_a_level_holds_the_shields_of_that_level_and_no_deity_locked_one(tmp_path):
    locked = make_item("w9060", "Test Locked Shield", ["SECONDARY"], classes=["PAL"], stats={"AC": 30}, item_type="Shield", deity=["Tunare"])
    strict_shield = make_item("w9061", "Test Seen Shield", ["SECONDARY"], classes=["PAL"], stats={"AC": 12}, item_type="Shield", level="strict")
    items = [*CATALOG, locked, strict_shield]
    config, _ = grid.load_inputs(TRIO, catalog_path=write_catalog(tmp_path / "catalog.json", items))

    def keys(evidence=None):
        pool = grid.shield_pool(config, RULES) if evidence is None else grid.shield_pool(config, RULES, evidence)
        return sorted(v.key for v in pool)

    assert keys("strict") == ["w9061"]  # a shield of the catalog's own strict level; the deity-locked one is never in a solve pool
    assert keys("wiki") == ["w9014", "w9061"]  # the wiki level holds the strict one too
    assert keys() == keys("wiki")  # by default the largest pool, as before
    assert all(v.is_shield and v.tier == 0 for v in grid.shield_pool(config, RULES, "wiki"))
    with pytest.raises(ValueError, match="evidence level"):
        grid.shield_pool(config, RULES, "hidden")
    no_shield = [item for item in CATALOG if item["key"] != "w9014"]
    config, _ = grid.load_inputs(TRIO, catalog_path=write_catalog(tmp_path / "no-shield.json", no_shield))
    assert grid.shield_pool(config, RULES, "strict") == [] and grid.shield_pool(config, RULES, "wiki") == []


def test_a_strict_pool_without_a_shield_has_no_shield_setup_while_the_wiki_pool_keeps_it(tmp_path):
    # a seen helm, chest and sword: a strict pool with items in it, and no shield among them
    summary, folder = with_seen(tmp_path, {"w9001", "w9006", "w9011"})
    assert (summary.scenarios, summary.chunks) == (TINY_SCENARIOS, TINY_CHUNKS)  # 8 strict chunks of two setups, 12 wiki chunks of three
    for buffs in ("own", "group"):
        strict, wiki = (read(folder / f"{evidence}-{buffs}.json") for evidence in ("strict", "wiki"))
        assert strict["flags"] == [] and strict["pool"] == 3  # a real strict pool, not the empty one
        assert strict["setups"] == {"tank": ["2h", "dw"]} and wiki["setups"] == {"tank": ["1h-shield", "2h", "dw"]}
        assert {row[3] for row in strict["scenarios"]} == {"2h", "dw"} and len(strict["scenarios"]) == 2 * 2 * 2
        assert {row[3] for row in wiki["scenarios"]} == {"1h-shield", "2h", "dw"} and len(wiki["scenarios"]) == 2 * 2 * 3
        order = [r["code"] for r in strict["races"]]
        keys = [(order.index(row[0]), row[2], ["1h-shield", "2h", "dw"].index(row[3])) for row in strict["scenarios"]]
        assert keys == sorted(keys)  # the rows keep their order: race, tier, setup
    chunks = sorted(p.name for p in (folder / "chunks").glob("s-*.json"))
    assert not [name for name in chunks if name.startswith("s-strict-") and "-1h-shield-" in name]  # none was ever solved
    assert len([name for name in chunks if "-1h-shield-" in name]) == 2 * 2  # the wiki level's: buff sets x tiers
    # what the strict level does solve is as before: every row holds a legal kit of the 2h or the dw setup, and the answer is strict
    defaults = read(folder / "defaults.json")
    assert defaults["view"]["evidence"] == "strict" and defaults["setup"] in ("2h", "dw") and not summary.violations
    assert all(view[1] in ("2h", "dw") for doc in runnerup_docs(folder).values() for view in doc["views"])


def test_a_strict_pool_with_a_shield_keeps_the_shield_setup(tmp_path):
    _, folder = with_seen(tmp_path, {"w9001", "w9011", "w9014"})  # the seen shield is a Paladin and Berserker one
    for name in shards.SHARD_NAMES:
        assert read(folder / name)["setups"] == {"tank": ["1h-shield", "2h", "dw"]}, name
    strict = expand(read(folder / "strict-own.json"))
    assert any("w9014" in strict[("TRL", "tank", tier, "1h-shield")]["kit"] for tier in (0, 4))  # a strict kit wears the seen shield


def test_the_seals_and_the_flip_check_use_the_setups_of_the_default_evidence_level(tmp_path, monkeypatch):
    calls = []
    real = seals.flip_variants

    def spy(ctx, **kwargs):
        calls.append((kwargs["evidence"], list(kwargs["setups"])))
        return real(ctx, **kwargs)

    monkeypatch.setattr(seals, "flip_variants", spy)
    _, folder = with_seen(tmp_path, {"w9001", "w9006", "w9011"}, robustness=None, tiers=(4,))
    assert calls == [("strict", ["2h", "dw"])]  # the default level has no shield: the shield setup is not solved for it
    robust = read(folder / "robust.json")
    assert robust["roles"]["tank"]["4"]  # and the seals were made, for a kit of the 2h or the dw setup


def test_the_invariants_compare_strict_with_wiki_only_where_both_levels_have_the_scenario():
    # the shield rows of the wiki level have no strict twin, and are not reported as missing
    low = {("strict", "own", "tank", "dw", 4, "OGR"): 90.0}
    high = {**low, ("wiki", "own", "tank", "dw", 4, "OGR"): 100.0, ("wiki", "own", "tank", "1h-shield", 4, "OGR"): 50.0}
    assert shards.check_invariants(high, {}) == []
    assert any("strict above wiki" in v for v in shards.check_invariants({**high, ("strict", "own", "tank", "dw", 4, "OGR"): 101.0}, {}))


def test_the_build_options_of_a_shard_are_the_two_that_decide_an_answer():
    assert grid.build_info() == {"any_rule": "all", "haste_assumed": None}  # not the test hook, not the private legacy terms
    assert grid.BUILD_OPTIONS.legacy is None and grid.BUILD_OPTIONS.mutation is None


def test_a_tie_stage_that_kept_the_first_stage_kit_is_counted_and_is_no_error(tmp_path, monkeypatch):
    real = solve_module.solve_canonical

    def kept_first(milp, time_limit=None):
        solution = real(milp, time_limit)
        return dataclasses.replace(solution, canonical=False, tie_stage="kept-first")  # the optimum, but not canonical

    monkeypatch.setattr(solve_module, "solve_canonical", kept_first)
    out = tmp_path / "out"
    summary = pc.run(SLUG, out, catalog=write_catalog(tmp_path / "catalog.json"), processes=1, **TINY)
    assert summary.kept_first == TINY_SCENARIOS and not summary.violations
    assert any("first-stage" in note and str(TINY_SCENARIOS) in note for note in summary.notes)
    assert read(out / SLUG / "wiki-own.json")["solver"]["kept_first"] == 12  # the rows of this shard
    assert read(out / SLUG / "wiki-own.json")["solver"]["canonical"] is True  # what was asked for; the count says what happened
    monkeypatch.undo()
    clean = pc.run(SLUG, tmp_path / "clean", catalog=tmp_path / "catalog.json", processes=1, **TINY)
    assert clean.kept_first == 0 and not any("first-stage" in note for note in clean.notes)
    assert read(tmp_path / "clean" / SLUG / "wiki-own.json")["solver"]["kept_first"] == 0
    # the kit is the optimum either way: the same values
    kept_values = [r[5] for r in read(out / SLUG / "wiki-own.json")["scenarios"]]
    assert kept_values == [r[5] for r in read(tmp_path / "clean" / SLUG / "wiki-own.json")["scenarios"]]


def test_a_canonical_run_whose_solver_never_ran_the_tie_stage_is_refused(tmp_path, monkeypatch):
    real = solve_module.solve_canonical

    def no_tie_stage(milp, time_limit=None):
        return dataclasses.replace(real(milp, time_limit), canonical=False, tie_stage=None)

    monkeypatch.setattr(solve_module, "solve_canonical", no_tie_stage)
    with pytest.raises(pc.PrecomputeError, match="tie stage"):
        pc.run(SLUG, tmp_path / "out", catalog=write_catalog(tmp_path / "catalog.json"), processes=1, **TINY)


def test_a_canonical_run_whose_last_stage_did_not_finish_is_refused(tmp_path, monkeypatch):
    """R2: the tie stage runs a last stage that settles kits of the same value and rank; a kit that stage left unsettled (a tie of more kits than it separates) is not canonical, and a canonical run refuses it."""
    real = solve_module.solve_canonical

    def unsettled(milp, time_limit=None):
        return dataclasses.replace(real(milp, time_limit), canonical=False, tie_stage="applied")

    monkeypatch.setattr(solve_module, "solve_canonical", unsettled)
    with pytest.raises(pc.PrecomputeError, match="did not settle"):
        pc.run(SLUG, tmp_path / "out", catalog=write_catalog(tmp_path / "catalog.json"), processes=1, **TINY)


def test_no_solve_of_a_run_has_a_time_limit_or_other_options(tmp_path, monkeypatch):
    calls = []
    for name in ("solve", "solve_canonical"):
        real = getattr(solve_module, name)

        def wrapped(*args, _real=real, _name=name, **kwargs):
            calls.append((_name, len(args), tuple(kwargs)))
            return _real(*args, **kwargs)

        monkeypatch.setattr(solve_module, name, wrapped)
    out = tmp_path / "out"
    pc.run(SLUG, out, catalog=write_catalog(tmp_path / "catalog.json"), processes=1, **TINY)
    assert calls and {name for name, _, _ in calls} == {"solve", "solve_canonical"}
    assert all(args == 1 and not kwargs for _, args, kwargs in calls), calls[:3]  # only the model: no time limit, no HiGHS options
    assert read(out / SLUG / "wiki-own.json")["solver"]["time_limit"] is None


def test_an_item_a_race_cannot_wear_is_neither_in_its_kit_nor_a_swap_for_it(tmp_path):
    zulu = make_item("w9027", "Test Zulu Greaves", ["LEGS"], stats={"AC": 99, "STA": 99}, weight=1.0, races=["TRL"])
    catalog = write_catalog(tmp_path / "catalog.json", [*CATALOG, zulu])
    out = tmp_path / "out"
    pc.run(SLUG, out, catalog=catalog, processes=1, **TINY)
    rows = expand(read(out / SLUG / "wiki-own.json"))
    legs = SLOT_INSTANCES.index("LEGS")
    assert rows[("TRL", "tank", 4, "dw")]["kit"][legs] == "w9027"
    assert "w9027" not in rows[("OGR", "tank", 4, "dw")]["kit"]
    doc = runnerup_docs(out / SLUG)[("tank", 4)]
    assert doc["views"]  # there are runner-ups to look at
    for race, setup, slots in doc["views"]:
        keys = [doc["items"][item][0] for place in slots for item, _ in place]
        if race == "OGR":
            assert "w9027" not in keys, "a swap the Ogre cannot wear"
    # a kit of a race that cannot wear one of its items is not legal
    bad = [None] * 22
    bad[legs] = at_tier(zulu, 4, RULES)
    assert grid.check_kit(bad, "dw", TRIO) == []  # without a race nothing is known about it
    assert grid.check_kit(bad, "dw", TRIO, race="TRL") == []
    assert any("w9027" in problem and "OGR" in problem for problem in grid.check_kit(bad, "dw", TRIO, race="OGR"))


# ---- the size budget of a shard ----------------------------------------------------------------------------------------


def test_the_budget_of_a_shard_is_200_kb_raw_and_50_kb_gzip():
    assert (shards.SHARD_RAW_LIMIT, shards.SHARD_GZIP_LIMIT) == (200_000, 50_000)  # a KB is 1,000 bytes; totals stay in the shard
    assert shards.SHARD_NAMES == ("strict-own.json", "strict-group.json", "wiki-own.json", "wiki-group.json")


def test_check_budget_names_the_file_and_the_size_that_is_over():
    fits = b"x" * shards.SHARD_RAW_LIMIT  # exactly at the limit, and it packs to almost nothing
    assert shards.check_budget("wiki-own.json", fits) == []
    over = shards.check_budget("wiki-own.json", fits + b"x")
    assert len(over) == 1 and "wiki-own.json" in over[0] and "200,001" in over[0] and "200,000" in over[0] and "raw" in over[0]
    noise = random.Random(1).randbytes(120_000)  # under the raw limit, but no gzip makes it small
    packed = shards.check_budget("strict-own.json", noise)
    assert len(packed) == 1 and "strict-own.json" in packed[0] and "gzip" in packed[0] and "50,000" in packed[0]
    both = shards.check_budget("wiki-group.json", random.Random(2).randbytes(210_000))
    assert len(both) == 2 and any("raw" in text for text in both) and any("gzip" in text for text in both)
    assert shards.gzip_size(fits) < 1_000 and shards.gzip_size(noise) > 100_000


def test_a_run_reports_a_shard_over_the_budget_and_still_writes_the_files(fresh, monkeypatch):
    summary = pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, **TINY)
    assert summary.violations == [] and max(raw for name, (raw, _) in summary.sizes.items() if name in shards.SHARD_NAMES) < 10_000
    monkeypatch.setattr(shards, "SHARD_RAW_LIMIT", 3_500)  # the wiki shards of the tiny grid are about 4.9 KB, the strict ones 2.5 KB
    over = pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, **TINY)
    assert sorted(text.split(" ")[0] for text in over.violations) == ["wiki-group.json", "wiki-own.json"]
    assert (fresh.dir / "wiki-own.json").is_file() and (fresh.dir / "defaults.json").is_file()
    monkeypatch.setattr(shards, "SHARD_RAW_LIMIT", 200_000)
    monkeypatch.setattr(shards, "SHARD_GZIP_LIMIT", 1_300)  # gzip: the wiki shards pack to about 1.6 KB, the strict ones to 1.0 KB
    packed = pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, **TINY)
    assert sorted(text.split(" ")[0] for text in packed.violations) == ["wiki-group.json", "wiki-own.json"] and "gzip" in packed.violations[0]


def test_the_real_shards_of_a_finished_run_are_within_the_budget():
    folder = REPO / "build" / "results" / SLUG
    found = [folder / name for name in shards.SHARD_NAMES if (folder / name).is_file()]
    if not found:
        pytest.skip("build/results/pal-mnk-ber has no shards: run python -m trioforge.precompute first")
    for path in found:
        assert shards.check_budget(path.name, path.read_bytes()) == [], path


# ---- the cross-scenario invariants -------------------------------------------------------------------------------------


def key6(evidence="wiki", buffs="own", role="tank", setup="dw", tier=4, race="OGR"):
    return (evidence, buffs, role, setup, tier, race)


def test_invariants_pass_for_a_consistent_set_of_values_and_name_every_kind_of_violation():
    good = {key6(tier=0): 100.0, key6(tier=1): 110.0, key6(evidence="strict", tier=0): 90.0, key6(buffs="group", tier=0): 105.0}
    base = {("OGR", "tank", "own"): 50.0, ("OGR", "tank", "group"): 55.0}
    assert shards.check_invariants(good, base) == []
    lower_tier = {**good, key6(tier=1): 99.0}
    assert any("tier" in v for v in shards.check_invariants(lower_tier, base))
    strict_above = {**good, key6(evidence="strict", tier=0): 101.0}
    assert any("strict" in v for v in shards.check_invariants(strict_above, base))
    group_below = {**good, key6(buffs="group", tier=0): 99.0}
    assert any("group" in v for v in shards.check_invariants(group_below, base))
    below_empty = {**good, key6(tier=0): 40.0, key6(tier=1): 41.0}
    assert any("empty kit" in v for v in shards.check_invariants(below_empty, base))
    assert shards.check_invariants({key6(tier=0): 100.0, key6(tier=1): 100.0 - 1e-12}, base) == []  # float noise is not a violation


# ---- the robustness seals and the flip notes ------------------------------------------------------------------------------


def group_of(place):
    return place.rstrip("0123456789")


def best_independent_setup(race, role, tier):
    """The role's best setup of a race by the solver's own unrounded values (the first of a tie, as the run takes it)."""
    best = None
    for setup in wp.setups_for(TRIO, role, TABLES, level=50):
        value = independent(CATALOG, tier, race, role, setup, "own", "wiki")[0].F
        if best is None or value > best[0]:
            best = (value, setup)
    return best[1]


def independent_seal(race, role, tier, setup):
    """``robustness`` of the module, called straight on the catalog dicts: ``{slot group: "robust" or a label}``."""
    items = eligible(CATALOG, "wiki")
    buffset = buffset_of("own")
    profile = make_profile(race, TRIO, 50, role, buffset, None, TABLES, evidence="wiki", items=[at_tier(i, tier, RULES) for i in items])
    scenario = robust_module.RobustScenario(
        profile, RULES, robust_module.catalog_pool(items, tier, RULES), setup, tier, buffset, BuildOptions()
    )
    return robust_module.robustness(scenario)


def test_the_robustness_module_makes_robust_json_by_default_and_it_matches_a_run_of_the_module_on_its_own(tmp_path):
    out = tmp_path / "out"
    catalog = write_catalog(tmp_path / "catalog.json")
    summary = pc.run(SLUG, out, catalog=catalog, processes=1, races=("OGR", "TRL"), roles=("tank",), tiers=(0, 4, 10))
    folder = out / SLUG
    doc, defaults = read(folder / "robust.json"), read(folder / "defaults.json")
    assert defaults["robustness"] == "done" and not any("robustness" in note for note in summary.notes)
    assert (doc["version"], doc["trio"], doc["race"], doc["tiers"]) == (1, SLUG, defaults["race"], [4, 10])  # +0 is not sealed
    assert set(doc["roles"]) == {"tank"} and set(doc["roles"]["tank"]) == {"4", "10"}
    known = {"robust", *robust_module_labels()}
    for tier in (4, 10):
        labels = doc["roles"]["tank"][str(tier)]
        assert list(labels) == list(shards.PLACES)  # a label for each of the 22 places, in kit order
        assert set(labels.values()) <= known, set(labels.values()) - known
        wanted = independent_seal(doc["race"], "tank", tier, best_independent_setup(doc["race"], "tank", tier))
        assert labels == {place: wanted[group_of(place)] for place in shards.PLACES}, tier  # a pair's places share one label
        for pair in ("EAR", "WRIST", "FINGER", "ANY"):
            assert labels[f"{pair}1"] == labels[f"{pair}2"]
    assert any(label != "robust" for tier in ("4", "10") for label in doc["roles"]["tank"][tier].values())  # a seal that says something


def robust_module_labels():
    """Every label the module can give, for the trios and the rules of this repository."""
    from trioforge.solver.robust import describe_perturbations

    profile = make_profile("IKS", ("MNK", "CLR", "BER"), 50, "melee", None, None, TABLES)
    return [p.label for p in describe_perturbations(profile, RULES)]


def test_every_role_gets_its_seals_at_the_default_race(tmp_path):
    out = tmp_path / "out"
    catalog = write_catalog(tmp_path / "catalog.json")
    pc.run(SLUG, out, catalog=catalog, processes=1, races=("OGR", "TRL"), roles=("tank", "melee"), tiers=(4,))
    doc = read(out / SLUG / "robust.json")
    assert set(doc["roles"]) == {"tank", "melee"} and doc["tiers"] == [4]
    for role in ("tank", "melee"):
        wanted = independent_seal(doc["race"], role, 4, best_independent_setup(doc["race"], role, 4))
        assert doc["roles"][role]["4"] == {place: wanted[group_of(place)] for place in shards.PLACES}, role


def test_the_seals_are_computed_without_a_time_limit_and_stop_the_run_if_they_describe_another_kit(tmp_path, monkeypatch):
    real = robust_module.robustness_report
    calls = []

    def watched(*args, **kwargs):
        calls.append((len(args), tuple(kwargs)))
        return real(*args, **kwargs)

    monkeypatch.setattr(robust_module, "robustness_report", watched)
    out = tmp_path / "out"
    catalog = write_catalog(tmp_path / "catalog.json")
    pc.run(SLUG, out, catalog=catalog, processes=1, races=("OGR", "TRL"), roles=("tank",), tiers=(4,))
    assert calls == [(1, ())]  # the scenario alone: no time limit, no other solver

    def other_kit(*args, **kwargs):
        report = real(*args, **kwargs)
        picks = {**report.picks, "HEAD": ("w0000",)}  # the base of the seal wears something else than the kit does
        return dataclasses.replace(report, picks=picks)

    monkeypatch.setattr(robust_module, "robustness_report", other_kit)
    with pytest.raises(pc.PrecomputeError) as caught:
        pc.run(SLUG, tmp_path / "again", catalog=catalog, processes=1, races=("OGR", "TRL"), roles=("tank",), tiers=(4,))
    assert all(part in str(caught.value) for part in ("robustness hook failed", "tank +4", "HEAD"))


def test_the_labels_of_a_group_are_given_to_each_place_of_it():
    groups = {"HEAD": "robust", "EAR": "AC x2", "FINGER": "robust", "ANY": "Weapon damage +5%"}
    places = seals.place_labels({**dict.fromkeys((group for group, _ in SLOT_GROUPS), "robust"), **groups})
    assert list(places) == list(shards.PLACES) and len(places) == 22
    assert [group for group, _ in SLOT_GROUPS] == list(dict.fromkeys(group_of(place) for place in shards.PLACES))  # the 18 groups
    assert (places["EAR1"], places["EAR2"], places["ANY1"], places["ANY2"], places["HEAD"], places["FINGER2"]) == (
        "AC x2", "AC x2", "Weapon damage +5%", "Weapon damage +5%", "robust", "robust"
    )
    with pytest.raises(KeyError):
        seals.place_labels({"HEAD": "robust"})  # a group without a label is a bug of the caller, not a guess


def variant(label, rule, test, **values):
    return seals.Variant(label, rule, test, values)


def test_a_flip_note_names_the_race_a_rule_alternative_puts_on_top_the_rule_and_its_test():
    base = {"OGR": 100.0, "TRL": 90.0, "IKS": 80.0, "ELF": 95.0}
    legal, order = {"OGR", "TRL", "IKS"}, ["OGR", "TRL", "IKS", "ELF"]
    variants = [
        variant("Iksar placement inside", "race.iksar_ac_placement", "B17", IKS=120.0),
        variant("Monk placement inside", "monk.bonus_placement", "B9", OGR=80.0, TRL=90.0, IKS=85.0, ELF=500.0),
        variant("Iksar placement inside", "race.iksar_ac_placement", "B17", OGR=100.0 - 1e-12, TRL=100.0),
        variant("Weapon damage +10%", "tier.weapon_damage_pct", "B5", TRL=200.0, OGR=210.0),
        variant("Monk curve full until 34", "monk.weight_curve", None, TRL=120.0),
    ]
    notes = seals.flip_notes(variants, base, "OGR", legal, order, 1)
    assert notes == [
        "Iksar, if Iksar AC stacks on top of the cap (test B17)",
        "Troll, if the Monk worn-weight bonus counts on top of the AC cap (test B9)",  # an illegal Wood Elf never wins
        "Troll, if the Monk worn-weight curve is the other one",  # an open rule without a named test
    ]
    assert RACE_NAMES["IKS"] == "Iksar" and RACE_NAMES["TRL"] == "Troll"
    # no flip: a tie is no flip, a float's noise is none, the same winner is none, and no variant gives no note
    assert seals.flip_notes([], base, "OGR", legal, order, 1) == []
    assert seals.flip_notes([variant("Iksar placement inside", "race.iksar_ac_placement", "B17", TRL=100.0 + 1e-12)], base, "OGR", legal, order, 1) == []
    assert seals.flip_notes([variant("Iksar placement inside", "race.iksar_ac_placement", "B17", OGR=500.0)], base, "OGR", legal, order, 1) == []
    # an unknown rule is named by the label of its variant
    assert seals.flip_notes([variant("Some new variant", "some.rule", "B99", TRL=300.0)], base, "OGR", legal, order, 1) == [
        "Troll, if Some new variant (test B99)"
    ]
    # the same note is made once
    twice = [variant("A", "race.iksar_ac_placement", "B17", IKS=120.0), variant("B", "race.iksar_ac_placement", "B17", IKS=130.0)]
    assert seals.flip_notes(twice, base, "OGR", legal, order, 1) == ["Iksar, if Iksar AC stacks on top of the cap (test B17)"]


def test_the_flip_notes_of_a_run_come_from_solving_every_race_under_each_open_rule(tmp_path, monkeypatch):
    out = tmp_path / "out"
    catalog = write_catalog(tmp_path / "catalog.json")
    grid_options = dict(races=("OGR", "TRL"), roles=("tank",), tiers=(4,))
    pc.run(SLUG, out, catalog=catalog, processes=1, **grid_options)
    default = read(out / SLUG / "defaults.json")
    other = default["runner_up_race"]
    assert default["race"] != other and default["robustness"] == "done"
    real = robust_module.describe_perturbations

    def describe(profile, rules, *, setup=None):
        if profile.race != other:
            return real(profile, rules, setup=setup)
        scaled = dataclasses.replace(profile, weights={key: value * 10 for key, value in profile.weights.items()})
        return [robust_module.Perturbation("Monk placement inside", "rule", scaled, {}, "monk.bonus_placement", "B9")]

    monkeypatch.setattr(robust_module, "describe_perturbations", describe)
    pc.run(SLUG, out, catalog=catalog, processes=1, **grid_options)  # every chunk is whole: only the seals and flips are made
    flipped = read(out / SLUG / "defaults.json")
    note = f"{RACE_NAMES[other]}, if the Monk worn-weight bonus counts on top of the AC cap (test B9)"
    assert note in flipped["flip_notes"] and note not in default["flip_notes"]
    assert flipped["race"] == default["race"] and flipped["robustness"] == "done"  # the page's best race is still the base one


def test_no_flip_notes_when_the_robustness_is_off_or_the_module_is_missing(tmp_path, monkeypatch):
    catalog = write_catalog(tmp_path / "catalog.json")
    off = pc.run(SLUG, tmp_path / "off", catalog=catalog, processes=1, robustness=False, races=("OGR", "TRL"), roles=("tank",), tiers=(4,))
    defaults = read(tmp_path / "off" / SLUG / "defaults.json")
    assert defaults["flip_notes"] == [] and defaults["robustness"] == "skipped: disabled"
    assert not (tmp_path / "off" / SLUG / "robust.json").exists() and any("skipped: disabled" in n for n in off.notes)
    monkeypatch.setitem(sys.modules, "trioforge.solver.robust", None)
    pc.run(SLUG, tmp_path / "gone", catalog=catalog, processes=1, races=("OGR", "TRL"), roles=("tank",), tiers=(4,))
    gone = read(tmp_path / "gone" / SLUG / "defaults.json")
    assert gone["flip_notes"] == [] and gone["robustness"].startswith("skipped:") and "not available" in gone["robustness"]


def test_a_custom_hook_still_makes_robust_json_and_the_flip_notes_come_from_the_module(tmp_path):
    def hook(scenario):
        return {place: "robust" for place in shards.PLACES}

    out = tmp_path / "out"
    pc.run(SLUG, out, catalog=write_catalog(tmp_path / "catalog.json"), processes=1, robustness=hook, races=("OGR", "TRL"), roles=("tank",), tiers=(4,))
    assert set(read(out / SLUG / "robust.json")["roles"]["tank"]["4"].values()) == {"robust"}
    assert isinstance(read(out / SLUG / "defaults.json")["flip_notes"], list)


# ---- the tier scope ------------------------------------------------------------------------------------------------


GRID_TIERS = (0, 4, 10)


def test_the_scope_of_a_run_is_tiers_0_4_10_for_the_grid_and_every_tier_for_the_milestone_trio():
    assert pc.GRID_TIERS == GRID_TIERS and pc.default_tiers(TRIO) == grid.TIERS == tuple(range(11))
    assert pc.default_tiers(("PAL", "SHD", "BER")) == pc.default_tiers("war-clr-wiz") == GRID_TIERS
    assert pc.default_tiers("ber-pal-mnk") == pc.default_tiers("PAL-MNK-BER") == grid.TIERS  # the same trio, however it is written


def test_a_run_that_has_the_scope_it_was_asked_for_is_not_partial_and_a_narrowing_makes_it_partial():
    full, plan = pc.grids(TRIO, TABLES, RULES, tiers=GRID_TIERS)
    assert plan == full and len(full) == 3520 * 3 // 11 == 960 and {s.tier for s in full} == set(GRID_TIERS)  # +0, +4 and +10: the grid, whole
    for tiers in ((4,), (0, 4), tuple(range(11))):
        full, plan = pc.grids(TRIO, TABLES, RULES, tiers=tiers)
        assert plan == full and {s.tier for s in plan} == set(tiers)  # whatever scope is asked for is the whole of that run
    for narrowing in ({"races": ("OGR",)}, {"roles": ("tank",)}, {"evidence": ("wiki",)}, {"buffs": ("own",)}):
        full, plan = pc.grids(TRIO, TABLES, RULES, tiers=GRID_TIERS, **narrowing)
        assert len(plan) < len(full) and set(plan) < set(full), narrowing
    full, plan = pc.grids(TRIO, TABLES, RULES)  # no scope given: the milestone trio's, which is every tier
    assert plan == full and len(full) == 3520
    full, plan = pc.grids(("PAL", "SHD", "BER"), TABLES, RULES)
    assert plan == full and {s.tier for s in full} == set(GRID_TIERS)
    with pytest.raises(ValueError, match="tier"):
        pc.grids(TRIO, TABLES, RULES, tiers=(4, 11))


@pytest.fixture(scope="module")
def complete(tmp_path_factory):
    """A run that narrows nothing: every role and setup, both evidence levels and buff sets, the tiers of the grid, in a world of two races."""
    root = tmp_path_factory.mktemp("complete")
    world = small_world(root / "world")
    catalog = write_catalog(root / "catalog.json")
    out = root / "out"
    summary = pc.run(SLUG, out, catalog=catalog, processes=1, tables_root=world, tiers=GRID_TIERS, robustness=False)
    return SimpleNamespace(root=root, world=world, catalog=catalog, out=out, dir=out / SLUG, summary=summary)


def test_a_run_of_tiers_0_4_10_that_narrows_nothing_is_not_partial(complete):
    summary = complete.summary
    assert summary.partial is False and summary.tiers == GRID_TIERS and not summary.violations
    assert (summary.scenarios, summary.chunks) == (108, 54)  # 2 races; 5 build-setup pairs of the wiki level and 4 of the strict one; 2 buff sets; 3 tiers
    for name in shards.SHARD_NAMES:
        shard = read(complete.dir / name)
        assert shard["partial"] is False and shard["tiers"] == list(GRID_TIERS), name
        assert shard["roles"] == ["tank", "melee"] and [race["code"] for race in shard["races"]] == ["TRL", "OGR"]


def test_a_run_of_its_scope_writes_one_runner_up_file_for_each_role_with_every_tier_and_an_index_that_lists_them(complete):
    folder = complete.dir / "runnerups"
    index = read(folder / "index.json")
    assert [(f["role"], f["file"], f["tiers"]) for f in index["files"]] == [
        ("tank", "tank.json", [0, 4, 10]), ("melee", "melee.json", [0, 4, 10]),
    ]  # fmt: skip
    assert sorted(p.name for p in folder.iterdir()) == ["index.json", "melee.json", "tank.json"]  # 2 files, where there were 6
    for entry in index["files"]:
        doc = read(folder / entry["file"])
        assert doc["role"] == entry["role"] and doc["tiers"] == [0, 4, 10]
        assert [view[:2] for view in doc["views"]] == [[tier, race] for tier in GRID_TIERS for race in ("TRL", "OGR")]  # every race at every tier of the scope, once
    assert complete.summary.sizes["runnerups/tank.json"][0] == next(f["bytes"] for f in index["files"] if f["role"] == "tank")


def test_a_run_narrowed_to_some_races_is_partial_all_the_same(complete, tmp_path):
    kwargs = dict(catalog=complete.catalog, processes=1, tables_root=complete.world, tiers=GRID_TIERS, robustness=False)
    again = pc.run(SLUG, tmp_path / "out", races=("OGR",), roles=("tank",), **kwargs)
    assert again.partial is True and again.tiers == GRID_TIERS
    for name in shards.SHARD_NAMES:
        shard = read(tmp_path / "out" / SLUG / name)
        assert shard["partial"] is True and shard["tiers"] == list(GRID_TIERS) and [race["code"] for race in shard["races"]] == ["OGR"]


def test_a_runner_up_file_over_the_budget_of_a_shard_is_a_violation_of_the_run(fresh, monkeypatch):
    size = (fresh.dir / "runnerups" / "tank.json").stat().st_size
    monkeypatch.setattr(shards, "SHARD_RAW_LIMIT", size - 1)  # one byte under the runner-up file of the tiny run
    summary = pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, **TINY)
    assert [line for line in summary.violations if line.startswith("runnerups/")] == [
        f"runnerups/tank.json is {size:,} bytes raw, over the {size - 1:,}-byte budget"
    ]  # the index is no data file of the page: it is not held to it
    assert (fresh.dir / "runnerups" / "tank.json").is_file()  # (the files are still written)


def writer_layout(tiers):
    """A layout of two races and one role for the writer of the runner-up files, with two invented items."""
    row = lambda key, name: [key, name, ["HEAD"], "drop", 4, "a test zone", "wiki", None]  # noqa: E731
    return shards.Layout(
        trio=SLUG, classes=TRIO, level=50, data_release="data-2030-01-02", game_patch="2026-10-13", rules_version=RULES.version, solver={}, build_options={},
        assumptions={}, races=[("TRL", True), ("OGR", True)], roles=["tank"], setups={"tank": ["dw"]}, tiers=list(tiers), caps={}, pools={},
        default_evidence="wiki", expected={}, item_rows={"w90002": row("w90002", "Test Beta"), "w90001": row("w90001", "Test Alpha")},
    )  # fmt: skip


def writer_chunk(*keys):
    """The chunk document of one tier: a view for each race (the Ogre listed first, as chunks list them), the first place naming ``keys``."""
    return {
        "views": [
            {"race": race, "setup": "dw", "places": [[[key, -1.5 * (n + 1)] for n, key in enumerate(keys)], *([[]] * 21)]} for race in ("OGR", "TRL")
        ]
    }


def test_the_writer_puts_every_tier_of_a_role_in_one_file_with_one_table_of_items():
    layout = writer_layout((0, 4, 10))
    chunks = {("tank", 4): writer_chunk("w90002"), ("tank", 10): writer_chunk("w90001", "w90002"), ("tank", 0): writer_chunk("w90001")}  # (in no order)
    texts = shards.runnerup_texts(layout, chunks)
    assert sorted(texts) == ["runnerups/index.json", "runnerups/tank.json"]
    doc = json.loads(texts["runnerups/tank.json"])
    assert doc["role"] == "tank" and doc["tiers"] == [0, 4, 10]
    assert [view[:3] for view in doc["views"]] == [[tier, race, "dw"] for tier in (0, 4, 10) for race in ("TRL", "OGR")]  # by tier, the races in display order
    assert [row[0] for row in doc["items"]] == ["w90001", "w90002"]  # one table, sorted by key, holding each item once
    swaps = {(view[0], view[1]): [item for item, _ in view[3][0]] for view in doc["views"]}
    assert swaps[(0, "OGR")] == [0] and swaps[(4, "TRL")] == [1] and swaps[(10, "OGR")] == [0, 1]  # a tier's swaps point into the table of the file
    entry = json.loads(texts["runnerups/index.json"])["files"][0]
    data = texts["runnerups/tank.json"].encode("utf-8")
    assert entry == {"file": "tank.json", "role": "tank", "tiers": [0, 4, 10], "bytes": len(data), "gzip": shards.gzip_size(data), "sha256": hashlib.sha256(data).hexdigest()}
    assert shards.runnerup_texts(layout, {}) == {}  # no documents, no texts: not even an index


def test_the_writer_stamps_every_runner_up_file_and_the_index_with_the_format_number_the_reader_asks_for():
    from trioforge.site import data as reader

    texts = shards.runnerup_texts(writer_layout((0, 4, 10)), {("tank", tier): writer_chunk("w90001") for tier in (0, 4, 10)})
    assert sorted(texts) == ["runnerups/index.json", "runnerups/tank.json"]
    for name, text in texts.items():
        assert json.loads(text)["version"] == shards.FORMAT == reader.FORMAT_VERSION == 1, name


def test_the_writer_refuses_a_role_that_lacks_a_tier_of_the_scope_or_has_one_beyond_it():
    layout = writer_layout((0, 4, 10))
    with pytest.raises(ValueError, match=r"tank role are for the tiers \[0, 4\], and the scope of the run is \[0, 4, 10\]"):
        shards.runnerup_texts(layout, {("tank", 0): writer_chunk("w90001"), ("tank", 4): writer_chunk("w90001")})
    with pytest.raises(ValueError, match=r"for the tiers \[0, 4, 7, 10\]"):
        shards.runnerup_texts(layout, {("tank", tier): writer_chunk("w90001") for tier in (0, 4, 7, 10)})
    with pytest.raises(ValueError, match="holds every tier of the run, and no other"):
        shards.runnerup_texts(layout, {("tank", 4): writer_chunk("w90001")})


def test_a_run_whose_tiers_leave_out_the_tier_of_the_default_view_is_refused_before_it_writes_anything(fresh):
    """+4 is the tier of the default view (defaults.json, the page, the seals). A run without it would be called a full grid, write no defaults.json and take
    an old one away, and no build could read what it left."""
    assert pc.DEFAULT_TIER == 4
    before = result_files(fresh.dir)
    chunks = sorted(p.name for p in (fresh.dir / "chunks").iterdir())
    assert "defaults.json" in before
    for tiers in ((0, 10), (10,), (0,), (0, 1, 2, 3, 5, 6, 7, 8, 9, 10)):
        with pytest.raises(pc.PrecomputeError) as caught:
            pc.run(SLUG, fresh.out, catalog=fresh.catalog, processes=1, races=("OGR", "TRL"), roles=("tank",), tiers=tiers, robustness=False)
        message = str(caught.value)
        assert "leave out +4, the tier of the default view" in message and "\n" not in message, message
    assert result_files(fresh.dir) == before  # the files of the earlier run, defaults.json among them, are as they were
    assert sorted(p.name for p in (fresh.dir / "chunks").iterdir()) == chunks


def test_a_run_that_asks_for_a_tier_that_does_not_exist_is_still_told_so_first(tmp_path):
    catalog = write_catalog(tmp_path / "catalog.json")
    with pytest.raises(pc.PrecomputeError, match="tier"):
        pc.run(SLUG, tmp_path / "out", catalog=catalog, processes=1, races=("OGR", "TRL"), roles=("tank",), tiers=(0, 11), robustness=False)
    assert not (tmp_path / "out").exists()


def test_the_command_line_refuses_tiers_without_the_tier_of_the_default_view(tmp_path, capsys):
    from trioforge.precompute.__main__ import main

    catalog = write_catalog(tmp_path / "catalog.json")
    out = tmp_path / "out"
    assert main(["--trio", SLUG, "--out", str(out), "--catalog", str(catalog), "--tiers", "0,10", "--processes", "1"]) == 2
    error = capsys.readouterr().err
    assert error.startswith("error: ") and "+4" in error and len(error.splitlines()) == 1, error
    assert not out.exists()


def test_the_summary_says_which_tiers_the_run_covers_and_whether_it_is_the_whole_of_them(capsys):
    from trioforge.precompute.__main__ import _print_summary

    base = dict(trio=SLUG, out_dir=Path("out"), scenarios=168, chunks=84)
    _print_summary(pc.RunSummary(partial=False, tiers=GRID_TIERS, **base))
    printed = capsys.readouterr().out
    assert "full grid" in printed and "+0, +4, +10" in printed and "partial" not in printed
    _print_summary(pc.RunSummary(partial=True, tiers=GRID_TIERS, **base))
    assert "partial run" in capsys.readouterr().out


# ---- the command line ----------------------------------------------------------------------------------------------


def test_the_command_line_narrows_the_grid_and_can_skip_the_robustness(tmp_path, capsys):
    from trioforge.precompute.__main__ import main

    catalog = write_catalog(tmp_path / "catalog.json")
    narrow = ["--races", "OGR,TRL", "--roles", "tank", "--tiers", "0,4", "--evidence", "strict,wiki", "--buffs", "own", "--processes", "1"]
    out = tmp_path / "out"
    assert main(["--trio", SLUG, "--out", str(out), "--catalog", str(catalog), *narrow]) == 0
    printed = capsys.readouterr().out
    assert "partial run" in printed
    assert sorted(p.name for p in (out / SLUG).glob("*.json")) == ["defaults.json", "engine-l50.json", "robust.json", "strict-own.json", "wiki-own.json"]
    skipped = tmp_path / "skipped"
    assert main(["--trio", SLUG, "--out", str(skipped), "--catalog", str(catalog), *narrow, "--no-robustness"]) == 0
    assert "skipped: disabled" in capsys.readouterr().out
    assert not (skipped / SLUG / "robust.json").exists() and read(skipped / SLUG / "defaults.json")["robustness"] == "skipped: disabled"
    assert main(["--trio", SLUG, "--out", str(tmp_path / "x"), "--catalog", str(catalog), "--races", "XXX"]) == 2
    assert "race" in capsys.readouterr().err
    with pytest.raises(SystemExit) as caught:  # a list that cannot be read is the parser's own usage error
        main(["--trio", SLUG, "--out", str(tmp_path / "x"), "--catalog", str(catalog), "--tiers", "4,eleven"])
    assert caught.value.code == 2 and "tier" in capsys.readouterr().err


def test_the_command_line_runs_a_limited_pass_and_reports_errors_with_status_two(tmp_path, capsys):
    from trioforge.precompute.__main__ import main

    catalog = write_catalog(tmp_path / "catalog.json")
    out = tmp_path / "out"
    assert main(["--trio", SLUG, "--out", str(out), "--catalog", str(catalog), "--processes", "1", "--limit", "2"]) == 0
    printed = capsys.readouterr()
    assert "partial" in printed.out and "scenarios" in printed.out
    assert len(list((out / SLUG / "chunks").glob("*.json"))) == 2
    assert main(["--trio", "pal-mnk", "--out", str(out), "--catalog", str(catalog)]) == 2
    assert "error" in capsys.readouterr().err
    assert main(["--trio", SLUG, "--out", str(out), "--catalog", str(tmp_path / "missing.json")]) == 2
    assert "error" in capsys.readouterr().err
    seen = write_seen(tmp_path / "seen.json", {"w9001"})
    refused = REPO / "derived" / "never-written-by-tests"
    assert main(["--trio", SLUG, "--out", str(refused), "--seen", str(seen), "--catalog", str(catalog)]) == 2
    assert "refused" in capsys.readouterr().err and not refused.exists()


def test_running_the_module_prints_help():
    import subprocess
    import sys

    env = dict(os.environ, PYTHONPATH=str(REPO / "pipeline"))
    result = subprocess.run([sys.executable, "-m", "trioforge.precompute", "--help"], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0 and "--trio" in result.stdout and "--seen" in result.stdout and "--limit" in result.stdout


# ---- real data -----------------------------------------------------------------------------------------------------


def find_catalog():
    if os.environ.get("TRIOFORGE_CATALOG") and Path(os.environ["TRIOFORGE_CATALOG"]).is_file():
        return Path(os.environ["TRIOFORGE_CATALOG"])
    return grid.find_catalog()


@pytest.fixture(scope="module")
def after_an_add(tmp_path_factory):
    """The real catalog once reports have been accepted for a live wearable (strict now) and for two that the wiki or the zones outweigh."""
    path = find_catalog()
    if path is None:
        pytest.skip("derived/catalog.json is not built")
    return AfterAnAdd(tmp_path_factory.mktemp("after-an-add"), load_strict(path))


@pytest.mark.parametrize("after", [False, True], ids=["the committed catalog", "the catalog after an accepted report"])
def test_the_real_catalog_gives_the_pool_the_design_expects_for_the_milestone_trio(request, after):
    path = request.getfixturevalue("after_an_add").path if after else find_catalog()
    if path is None:
        pytest.skip("derived/catalog.json is not built")
    config, meta = grid.load_inputs(TRIO, catalog_path=path)
    wiki = [i for i in config.items if config.levels[i["key"]] in ("strict", "wiki") and i["deity"] is None]
    assert 1000 < len(wiki) < 3000
    strict = [i for i in config.items if config.levels[i["key"]] == "strict"]
    for item in strict:  # no seen flags and no listing: what is strict rests on a report, which is public
        found = {reason["code"] for reason in item["evidence"]["reasons"]}
        assert "community-report" in found and not found & {"seen-in-game", "eql-catalog"}, item["key"]
    strict_pool = [i for i in strict if i["deity"] is None]
    assert config.default_evidence == ("strict" if strict_pool else "wiki") and meta.data_release.startswith("data-")  # (the strict view is the default once its pool is not empty)
    ctx = grid.Context(config)
    assert len(ctx.pool("wiki", 4)) == len(wiki) and len(ctx.pool("strict", 4)) == len(strict_pool)
