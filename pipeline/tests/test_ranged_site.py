"""The bow setup and the Ranged role through the precompute, the files it writes and the site built from them.

A real run of the precompute on an invented catalog that has bows (a trio with a Ranger and a Paladin, in a world of two races so that the whole grid is a few seconds
of solving), then the site built from its results:

* the grid has the setup where the solve pool of a level has a bow that a class of the trio may equip, the Ranged role has it and nothing else, and the other roles
  gain it as their last setup; the strict level, whose pool is empty here, has none of it;
* in every scenario of the setup the range place holds a bow, in the others it may hold anything, and the bow with more damage per delay wins when all else is equal;
* the bundle and the item table agree with the shards (the site's reader checks them against each other), the page offers the role and the setup, hides the setup for a
  role that has none, shows the range line only in the setup, and the files the browser reads carry the setup and the role;
* the page of a trio with no bow class (a Warrior, a Cleric and a Berserker have a bow class too, so the trio here is made of classes with none) has no new markup at all.

Every item and name here is invented (the classes, the skill name and the trio are public game terms).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from site_helpers import extract_main, parse
from test_precompute import CATALOG, make_item, small_world, weapon, write_catalog
from test_site_build import MANIFEST, need_node

from trioforge import precompute as pc
from trioforge.model import weapons
from trioforge.model.items import at_tier
from trioforge.precompute import grid
from trioforge.site import build, data
from trioforge.site import view as view_module

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "fixtures" / "site" / "contract-ranged"
TRIO = ("PAL", "RNG", "BER")
SLUG = "pal-rng-ber"
NO_BOW_TRIO = ("MNK", "BST", "BER")
NO_BOW_SLUG = "mnk-bst-ber"
BOWS = [
    make_item("w9101", "Test Bow Alpha", ["RANGE"], classes=["PAL", "RNG"], stats={"DEX": 5}, weapon=weapon("Archery", 12, 40), weight=3.0),
    make_item("w9102", "Test Bow Beta", ["RANGE"], classes=["RNG"], weapon=weapon("Archery", 20, 30), weight=3.0),  # the damage per delay of the two differs (1.17 against 0.8), and neither beats the best hands
    make_item("w9103", "Test Charm Gamma", ["RANGE"], stats={"HP": 60, "STA": 10}),
    make_item("w9104", "Test Arrow Delta", ["AMMO"], classes=["RNG"], stats={"DEX": 3}),
    make_item("w9105", "Test Bow Hidden", ["RANGE"], classes=["RNG"], weapon=weapon("Archery", 90, 20), level="hidden"),
    make_item("w9106", "Test Bow Warrior", ["RANGE"], classes=["WAR"], weapon=weapon("Archery", 50, 20)),  # a class that is not in the trio
]
ITEMS = [*CATALOG, *BOWS]
BOW_KEYS = {"w9101", "w9102"}
RANGE = data.SLOT_INSTANCES.index("RANGE")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    root = tmp_path_factory.mktemp("ranged")
    catalog = write_catalog(root / "catalog.json", ITEMS)
    out = root / "results"
    world = small_world(root / "world")
    for trio in (TRIO, NO_BOW_TRIO):
        summary = pc.run("-".join(trio).lower(), out, catalog=catalog, tables_root=world, processes=1)  # (the seals too: the site reads them)
        assert not summary.violations, summary.violations
    return out


@pytest.fixture(scope="module")
def results_no_bow(tmp_path_factory):
    """The same trio, with a Ranger, solved from a catalog that has no bow in it."""
    root = tmp_path_factory.mktemp("ranged-no-bow")
    catalog = write_catalog(root / "catalog.json", [*CATALOG, *(item for item in BOWS if item["key"] in ("w9103", "w9104"))])  # (a charm and an arrow: nothing to shoot)
    out = root / "results"
    summary = pc.run("-".join(TRIO).lower(), out, catalog=catalog, tables_root=small_world(root / "world"), processes=1)
    assert not summary.violations, summary.violations
    return out


def shard(results, slug, name="wiki-own"):
    return json.loads((results / slug / f"{name}.json").read_text(encoding="utf-8"))


def rows_of(document):
    """``(race, role, tier, setup, kit of keys, value)`` of every scenario of a shard file (the format of ``trioforge.precompute.shards``)."""
    keys = [row[0] for row in document["items"]]
    return [(r[0], r[1], r[2], r[3], [None if i < 0 else keys[i] for i in document["kits"][r[4]]], r[5]) for r in document["scenarios"]]


def test_the_grid_has_the_setup_where_the_pool_has_a_bow_for_the_trio(results):
    wiki, strict = shard(results, SLUG, "wiki-own"), shard(results, SLUG, "strict-own")
    assert "ranged" in wiki["roles"] and wiki["setups"]["ranged"] == ["ranged"]
    for role in ("tank", "melee"):
        assert wiki["setups"][role][-1] == "ranged" and wiki["setups"][role][:-1] == [s for s in wiki["setups"][role] if s != "ranged"], role
    assert "ranged" not in wiki["setups"].get("caster", [])
    # the strict pool of this catalog is empty: no bow, so no role has the setup there, and the Ranged role (which plays the bow and nothing else) has no setup and no row
    assert "ranged" in strict["roles"] and strict["setups"]["ranged"] == []
    assert all("ranged" not in setups for setups in strict["setups"].values())
    assert all(row[1] != "ranged" for row in rows_of(strict))


def test_every_scenario_of_the_setup_holds_a_bow_in_the_range_place_and_the_others_may_hold_anything(results):
    wiki = rows_of(shard(results, SLUG, "wiki-own"))
    ranged = [row for row in wiki if row[3] == "ranged"]
    assert ranged and {row[1] for row in ranged} == {"tank", "melee", "ranged"}
    for race, role, tier, setup, kit, value in ranged:
        assert kit[RANGE] in BOW_KEYS, (race, role, tier, kit[RANGE])
    # the bow of more damage per delay (Beta) is the one the setup picks
    assert {row[4][RANGE] for row in ranged} == {"w9102"}
    others = {row[4][RANGE] for row in wiki if row[3] != "ranged"}
    assert others - BOW_KEYS  # in the other setups the place is for whatever scores most: here the charm


def test_a_ranger_trio_whose_pool_has_no_bow_is_not_offered_the_ranged_role_at_all(results_no_bow):
    wiki, strict = shard(results_no_bow, SLUG, "wiki-own"), shard(results_no_bow, SLUG, "strict-own")
    for doc in (wiki, strict):
        assert "ranged" not in doc["roles"] and "ranged" not in doc["setups"] and "ranged" not in json.dumps(doc["setups"])
        assert all(row[1] != "ranged" and row[3] != "ranged" for row in rows_of(doc))
    bundle = json.loads((results_no_bow / SLUG / "engine-l50.json").read_text(encoding="utf-8"))
    assert "ranged" not in bundle["roles"] and list(bundle["roles"]) == ["tank", "melee"]
    assert all("ranged" not in setups for row in bundle["roles"].values() for setups in row["setups_by_evidence"].values())


def test_the_reader_refuses_a_bundle_that_offers_a_role_that_a_shard_lists_with_no_setup(results, tmp_path):
    import shutil

    folder = tmp_path / SLUG
    shutil.copytree(results / SLUG, folder)
    assert data.load_trio(folder).meta.slug == SLUG  # (as the run wrote it, the strict shard lists the Ranged role with no setup and the bundle says none)
    path = folder / "engine-l50.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["roles"]["ranged"]["setups_by_evidence"]["strict"] = ["ranged"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(data.ResultsError, match="no rows of the ranged role"):
        data.load_trio(folder)


def test_the_bundle_gives_the_ranged_role_only_at_an_evidence_level_for_no_pool_offers_it(results):
    from trioforge.export import browser

    bundle = json.loads((results / SLUG / "engine-l50.json").read_text(encoding="utf-8"))
    assert bundle["roles"]["ranged"]["setups"] == ["ranged"]  # (the setups of the widest pool: a role that only a pool offers has no setup of its own with no pool)
    for role in ("tank", "melee"):
        assert "ranged" not in browser.assemble(bundle, "OGR", role, "own")["setups"], role  # (no pool: the other roles never get the bow)
    with pytest.raises(ValueError, match="evidence level"):
        browser.assemble(bundle, "OGR", "ranged", "own")
    made = browser.assemble(bundle, "OGR", "ranged", "own", evidence="wiki")
    assert made["setups"] == ["ranged"] and made["evidence"] == "wiki" and made["role"] == "ranged"
    with pytest.raises(ValueError, match="not offered"):
        browser.assemble(bundle, "OGR", "ranged", "own", evidence="strict")  # (its strict pool has no bow)


def test_a_trio_with_no_bow_class_is_what_it_was(results):
    wiki = shard(results, NO_BOW_SLUG)
    assert "ranged" not in json.dumps(wiki["setups"]) and "ranged" not in wiki["roles"]
    assert all(row[3] != "ranged" for row in rows_of(wiki))
    bundle = json.loads((results / NO_BOW_SLUG / "engine-l50.json").read_text(encoding="utf-8"))
    assert "ranged" not in bundle["roles"] and all("ranged" not in row["setups"] for row in bundle["roles"].values())
    assert all("ranged" not in setups for row in bundle["roles"].values() for setups in row["setups_by_evidence"].values())


def test_the_bundle_lists_the_role_the_setup_and_the_factor(results):
    bundle = json.loads((results / SLUG / "engine-l50.json").read_text(encoding="utf-8"))
    assert list(bundle["roles"]) == ["tank", "melee", "ranged"]
    assert bundle["roles"]["ranged"]["setups_by_evidence"] == {"strict": [], "wiki": ["ranged"]}
    for role in ("tank", "melee"):
        assert bundle["roles"][role]["setups_by_evidence"]["wiki"][-1] == "ranged"
        assert "ranged" not in bundle["roles"][role]["setups_by_evidence"]["strict"]
    assert bundle["profile_common"]["ranged_factor"] == 1
    assert bundle["weapon_rules"]["bow_skill"] == weapons.BOW_SKILL
    assert bundle["constants"]["weapon_setups"] == list(weapons.SETUPS)


def test_the_bow_the_run_picks_is_the_best_by_the_measure(results):
    config, _ = grid.load_inputs(TRIO, catalog_path=results.parent / "catalog.json", tables_root=results.parent / "world")
    rules = grid.Context(config).rules
    pool = grid.bow_pool(config, rules, "wiki")
    assert {vec.key for vec in pool} == BOW_KEYS  # the hidden bow, the warrior's and the arrow are not in it
    best = max(pool, key=lambda vec: weapons.damage_index_exact(at_tier(next(i for i in config.items if i["key"] == vec.key), 4, rules), "range", "ranged", 0))
    assert best.key == "w9102"
    assert grid.bow_pool(config, rules, "strict") == []


# ---- the page ----------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def site(results, tmp_path_factory):
    need_node()
    out = tmp_path_factory.mktemp("ranged-site") / "dist"
    changelog = out.parent / "changelog.md"
    changelog.write_text("# Changelog\n\n## Unreleased\n\n- a test\n", encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))  # (the fixture's, with a wiki page for each invented item of this catalog too)
    manifest["items"].update({item["key"]: {"title": item["name"], "revid": 300000 + n} for n, item in enumerate(ITEMS)})
    manifest_path = out.parent / "sources-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    build.build(results=results, out=out, noindex=True, sources_manifest=manifest_path, changelog=changelog, without_item_catalog=True)
    return out


def page(site, slug):
    return parse((site / "trio" / slug / "index.html").read_text(encoding="utf-8"))


def test_the_page_offers_the_role_and_the_setup_and_the_role_has_only_the_setup(site):
    doc = page(site, SLUG)
    roles = {node.get("value"): node for node in doc.find_all("input", name="role")}
    assert list(roles) == ["tank", "melee", "ranged"]
    ranged = roles["ranged"]
    assert ranged.get("data-label") == "Archer" and ranged.get("data-setups") == "ranged"
    assert ranged.get("data-hint") == "Damage from a bow first: attack, dexterity and haste, then hit points."
    assert roles["melee"].get("data-setups").split()[-1] == "ranged"
    setups = {node.get("value"): node for node in doc.find_all("input", name="setup")}
    assert list(setups)[-1] == "ranged"
    assert setups["ranged"].get("data-label") == "Bow" and setups["ranged"].get("data-phrase") == "bow"
    assert setups["ranged"].has("hidden") == (doc.find_all("input", id_="role-tank")[0].has("checked") is False and "ranged" not in roles["tank"].get("data-setups").split())


def test_the_ranged_role_names_the_rule_of_its_weights_on_its_radio_and_no_other_role_does(site):
    doc = page(site, SLUG)
    roles = {node.get("value"): node for node in doc.find_all("input", name="role")}
    assert roles["ranged"].get("data-rule") == "roles.ranged_template"
    assert roles["ranged"].get("data-rule-title") == rule_title("roles.ranged_template")
    for code, node in roles.items():
        if code != "ranged":
            assert node.get("data-rule") is None and node.get("data-rule-title") is None, code
    # the notes that cite the templates are there for the page code to add the Ranged role's rule to (the rules page has it under its own heading)
    text = (site / "trio" / SLUG / "index.html").read_text(encoding="utf-8")
    for note in ('id="best-race-rules"', 'id="runnerups-rules"', 'id="role-hint"'):
        assert note in text
    assert text.count('href="/rules/#roles.templates"') >= 3
    rules_page = (site / "rules" / "index.html").read_text(encoding="utf-8")
    assert 'id="roles.ranged_template"' in rules_page or "roles.ranged_template" in rules_page


def test_a_trio_with_no_ranged_role_has_no_rule_on_any_role_radio(site):
    doc = page(site, NO_BOW_SLUG)
    assert all(node.get("data-rule") is None for node in doc.find_all("input", name="role"))


def rule_title(rule_id):
    from trioforge.rules import load as load_rules

    return next(rule["title"] for rule in json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))["rules"] if rule["id"] == rule_id)


def test_the_markup_pays_for_the_controls_only_and_the_page_code_makes_the_range_line_and_the_note(site):
    doc = page(site, SLUG)
    assert not doc.find_all("div", cls="bow-line") and not doc.find_all("p", cls="bow-note")  # the default view of this trio is not the bow's
    script = (REPO / "pipeline" / "trioforge" / "site" / "static" / "trio.js").read_text(encoding="utf-8")
    assert f'const BOW_NOTE = "{view_module.BOW_NOTE}";' in script  # the words of the note are the generator's, said once in the page code


def test_the_baked_line_of_the_bow_among_the_other_setups_names_the_bow_and_the_hands_as_the_other_lines_name_theirs(site):
    html = (site / "trio" / SLUG / "index.html").read_text(encoding="utf-8")
    lines = re.findall(r"<li>([^<]*)</li>", re.search(r'<ul id="w-others".*?</ul>', html, re.S).group(0))
    bows = [line for line in lines if line.startswith("Bow: ")]
    assert len(bows) == 1, lines
    # the bow, then the hands as the other lines give them (the main hand, and the off hand after a plus when there is one: a shield there counts its armor class), then the difference
    assert re.fullmatch(r"Bow: Test Bow (?:Alpha|Beta) with [^()]+? \([−+]?[\d,]+\)", bows[0]), bows[0]
    assert " with " in bows[0] and all(" with " not in line for line in lines if line is not bows[0]), lines


def test_a_page_with_no_bow_class_has_none_of_it(site):
    html = (site / "trio" / NO_BOW_SLUG / "index.html").read_text(encoding="utf-8")
    for word in ("ranged", "Bow", "bow setup", "w-range"):
        assert word not in html, word


def test_the_data_files_carry_the_setup_and_the_role(site):
    wiki = json.loads((site / "data" / SLUG / "wiki-own.json").read_text(encoding="utf-8"))
    assert [row[3] for row in wiki["rows"]].count("ranged") > 0 and {row[1] for row in wiki["rows"]} >= {"ranged"}
    assert (site / "data" / SLUG / "runnerups" / "ranged.json").exists()


def test_the_words_of_the_page_code_and_of_the_generator_agree():
    assert view_module.SETUP_LABELS["ranged"] == "Bow" and view_module.SETUP_PHRASES["ranged"] == "bow"
    assert view_module.ROLE_LABELS["ranged"] == "Archer"
    assert re.fullmatch(r"[A-Z][^.]*\.", view_module.ROLE_HINTS["ranged"])
    shared = (REPO / "pipeline" / "trioforge" / "site" / "static" / "ui" / "shared-kit.js").read_text(encoding="utf-8")
    assert '["ranged", "bow"]' in shared  # the shared kit's own words for a setup the page has no switch for (a test of test_site_build holds the others equal)


# ---- the contract with the browser tests --------------------------------------------------------------------------------------
# tests-js/ranged-page.test.mjs runs the real page code against these committed files, as tests-js/trio.test.mjs does against fixtures/site/contract. If a template or the data
# format changes, regenerate them with
#     TRIOFORGE_UPDATE_CONTRACT=1 python -m pytest pipeline/tests/test_ranged_site.py -k contract


def test_the_committed_contract_files_of_the_bow_trio_are_what_the_build_writes(site):
    files = {"trio-main.html": extract_main((site / "trio" / SLUG / "index.html").read_text(encoding="utf-8"))}
    for name in ("strict-own", "strict-group", "wiki-own", "wiki-group", "robust"):
        files[f"data/{name}.json"] = (site / "data" / SLUG / f"{name}.json").read_text(encoding="utf-8")
    for path in sorted((site / "data" / SLUG / "runnerups").glob("*.json")):
        files[f"data/runnerups/{path.name}"] = path.read_text(encoding="utf-8")
    if os.environ.get("TRIOFORGE_UPDATE_CONTRACT") == "1":
        for name, text in files.items():
            target = CONTRACT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
    for name, text in files.items():
        committed = CONTRACT / name
        assert committed.is_file(), f"{name} is missing; run with TRIOFORGE_UPDATE_CONTRACT=1"
        assert committed.read_text(encoding="utf-8") == text, f"{name} is stale; run with TRIOFORGE_UPDATE_CONTRACT=1"
    expected = {p.relative_to(CONTRACT).as_posix() for p in CONTRACT.rglob("*") if p.is_file()}
    assert expected == set(files), "an unexpected file in fixtures/site/contract-ranged"
