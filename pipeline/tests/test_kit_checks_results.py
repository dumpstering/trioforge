"""Tests for how the kit checks read a results folder: the kit of a trio, the item table and the pool a kit is chosen from.

The folders are written by ``kits_fixture.make_results`` with invented items. What is under test: which scenario is "the kit" of a trio, role and tier (the default race, the
best setup), how an item record becomes the item the model sees at a tier, who can wear what, and what happens to a folder that is not one.
"""

from __future__ import annotations

import json

import pytest
from kits_fixture import PLATE, base_items, item, items_document, make_results, row

from trioforge import rules as rules_module
from trioforge.checks.results import (
    PLACE_NAMES,
    ItemTable,
    Results,
    ResultsError,
    load_kits,
    norm_name,
    parse_trio,
    trio_folders,
)
from trioforge.export import browser
from trioforge.model.items import SLOT_INSTANCES, at_tier


@pytest.fixture(scope="module")
def rules():
    return rules_module.load()


def test_a_trio_is_three_classes_in_class_order_from_any_spelling():
    assert parse_trio("pal-mnk-ber") == ("PAL", "MNK", "BER")
    assert parse_trio("BER/mnk/Pal") == ("PAL", "MNK", "BER")
    assert parse_trio(["ENC", "SHD", "WIZ"]) == ("SHD", "WIZ", "ENC")


@pytest.mark.parametrize("bad", ["pal-mnk", "pal-mnk-mnk", "pal-mnk-xyz", ["PAL", "MNK"], "", "a-b-c-d"])
def test_anything_else_is_not_a_trio(bad):
    with pytest.raises(ValueError):
        parse_trio(bad)


def test_the_places_of_a_kit_are_the_22_of_a_shard():
    assert len(PLACE_NAMES) == len(SLOT_INSTANCES) == 22
    assert PLACE_NAMES[:5] == ("HEAD", "FACE", "EAR1", "EAR2", "NECK")
    assert PLACE_NAMES[-3:] == ("ANY2", "PRIMARY", "SECONDARY")


@pytest.mark.parametrize(
    ("one", "other"),
    [("Zindrel's Fist", "zindrel`s fist"), ("Zindrel's Fist", "ZINDRELS  FIST"), ("Brine-Clasped Girdle", "brine clasped girdle"), ("Ring of the Zindrel", "ring of the zindrel!")],
)
def test_names_are_compared_without_case_punctuation_or_apostrophes(one, other):
    assert norm_name(one) == norm_name(other)


def test_names_that_differ_in_words_stay_different():
    assert norm_name("Ring of the Zindrel") != norm_name("Ring of Zindrel")
    assert norm_name("Zindrels Fist") != norm_name("Zindrel Fist")


def test_only_folders_named_like_a_trio_are_trios(tmp_path):
    for name in ("pal-mnk-ber", "WAR-CLR-PAL", "notes", "pal-mnk", "engine"):
        (tmp_path / name).mkdir()
    (tmp_path / "enc-mag-nec").write_text("a file, not a folder")
    assert [p.name for p in trio_folders(tmp_path)] == ["WAR-CLR-PAL", "pal-mnk-ber"]


def _results(tmp_path, trios, **kwargs):
    return make_results(tmp_path / "results", base_items(), trios, **kwargs)


def test_the_kit_of_a_role_and_tier_is_the_default_race_at_the_best_setup(tmp_path):
    root = _results(
        tmp_path,
        {
            "pal-mnk-enc": [
                row("tank", 4, {"HEAD": "Vlorn Helm"}, setup="2h", value=100.0),
                row("tank", 4, {"HEAD": "Quibbit Helm"}, setup="dw", value=150.0),
                row("tank", 4, {"HEAD": "Zarn Helm"}, setup="1h-shield", value=120.0),
                row("tank", 4, {"HEAD": "Tolk Helm"}, race="OGR", setup="dw", value=999.0),
                row("tank", 10, {"HEAD": "Vlorn Helm"}, setup="2h", value=100.0),
            ]
        },
        race="HUM",
    )
    results = Results(root, rules=rules_module.load())
    kits = results.kits("PAL-MNK-ENC")
    assert [(k.role, k.tier, k.setup, k.race, k.value) for k in kits] == [("tank", 4, "dw", "HUM", 150.0), ("tank", 10, "2h", "HUM", 100.0)]
    keys = {r.name: r.key for r in results.table.records.values()}
    assert dict(kits[0].worn()) == {"HEAD": keys["Quibbit Helm"]}


def test_a_tie_of_value_goes_to_the_setup_the_shard_lists_first(tmp_path):
    root = _results(
        tmp_path,
        {"pal-mnk-enc": [row("tank", 4, {}, setup="dw", value=50.0), row("tank", 4, {}, setup="2h", value=50.0), row("tank", 4, {}, setup="1h-shield", value=50.0)]},
    )
    (kit,) = Results(root, rules=rules_module.load()).kits("pal-mnk-enc")
    assert kit.setup == "dw"


def test_another_race_can_be_asked_for_and_the_default_stays_the_default(tmp_path):
    root = _results(tmp_path, {"pal-mnk-enc": [row("tank", 4, {}, race="HUM", value=1.0), row("tank", 4, {}, race="OGR", value=2.0, setup="dw")]})
    results = Results(root, rules=rules_module.load())
    assert [k.race for k in results.kits("pal-mnk-enc")] == ["HUM"]
    assert [(k.race, k.setup) for k in results.kits("pal-mnk-enc", "ogr")] == [("OGR", "dw")]
    assert results.kits("pal-mnk-enc", "ERU") == []


def test_roles_come_in_the_order_of_the_shard_and_tiers_ascending(tmp_path):
    root = _results(
        tmp_path,
        {"pal-mnk-enc": [row("balanced", 10, {}), row("tank", 0, {}), row("balanced", 0, {}), row("tank", 10, {}), row("melee", 4, {})]},
    )
    kits = Results(root, rules=rules_module.load()).kits("pal-mnk-enc")
    assert [(k.role, k.tier) for k in kits] == [("balanced", 0), ("balanced", 10), ("tank", 0), ("tank", 10), ("melee", 4)]


def test_a_kit_carries_its_places_totals_and_soft_cap(tmp_path):
    root = _results(
        tmp_path,
        {"pal-mnk-enc": [row("tank", 4, {"HEAD": "Vlorn Helm", "ANY2": "Moonstud"}, totals={"ac": 410, "fire": 33, "magic": 5})]},
        softcap=403,
    )
    results = Results(root, rules=rules_module.load())
    (kit,) = results.kits("pal-mnk-enc")
    keys = {r.name: r.key for r in results.table.records.values()}
    assert kit.places[PLACE_NAMES.index("HEAD")] == keys["Vlorn Helm"]
    assert kit.places[PLACE_NAMES.index("ANY2")] == keys["Moonstud"]
    assert kit.places.count(None) == 20
    assert (kit.totals["ac"], kit.totals["fire"], kit.totals["magic"], kit.softcap) == (410, 33, 5, 403)
    assert kit.trio == ("PAL", "MNK", "ENC") and kit.slug == "pal-mnk-enc" and kit.evidence == "wiki" and kit.level == 50 and kit.buff_ids == ()


def test_a_trio_the_folder_lacks_has_no_kit(tmp_path):
    results = Results(_results(tmp_path, {"pal-mnk-enc": [row("tank", 4, {})]}), rules=rules_module.load())
    assert results.kits("war-clr-pal") == []
    assert results.trios() == [("PAL", "MNK", "ENC")]


def test_every_kit_of_the_folder_comes_trio_by_trio(tmp_path):
    root = _results(tmp_path, {"war-clr-pal": [row("tank", 4, {})], "pal-mnk-enc": [row("balanced", 0, {}), row("tank", 4, {})]})
    assert [(k.slug, k.role, k.tier) for k in load_kits(root)] == [("pal-mnk-enc", "balanced", 0), ("pal-mnk-enc", "tank", 4), ("war-clr-pal", "tank", 4)]


def test_an_item_record_is_the_item_the_model_sees(tmp_path, rules):
    document = items_document(base_items())
    table = ItemTable(document, rules)
    defaults = document["defaults"]
    for record in document["items"]:
        key = browser.record_key(record)
        for tier in (0, 4, 10):
            made = at_tier(browser.item_to_catalog(record, defaults), tier, rules)
            ours = table.vec(key, tier)
            assert (ours.stats, ours.sv, ours.haste, ours.weapon, ours.slots, ours.classes, ours.races, ours.lore, ours.weight10) == (
                made.stats, made.sv, made.haste, made.weapon, made.slots, made.classes, made.races, made.lore, made.weight10,
            ), (record["name"], tier)  # fmt: skip


def test_the_numbers_of_an_item_follow_the_tier_rule(rules):
    record = item("Stat Test Ring", ["FINGER"], None, {"STR": 20, "AC": 3, "HASTE": 10, "MANAREG": 1})
    vec = ItemTable(items_document([record]), rules).vec(f"w{record['id']}", 4)
    assert vec.stats["STR"] == 28  # 20 + max(4, 20 * 4 // 10)
    assert vec.stats["AC"] == 7  # 3 + max(4, 3 * 4 // 10)
    assert vec.haste == 10 + 4 * rules.get("haste.worn_per_tier")


def test_the_pool_of_a_trio_and_a_race_is_what_the_solver_can_use(tmp_path, rules):
    table = ItemTable(items_document(base_items()), rules)

    def pool(trio, race, evidence="wiki"):
        return {r.name for r in table.eligible(trio, race, evidence)}

    plain = pool(("PAL", "MNK", "ENC"), "HUM")
    assert "Vlorn Helm" in plain and "Ombrel Vestment" in plain and "Fistwrap Helm" in plain  # a class of the trio wears each
    assert not {"Phantom Helm", "Disputed Helm", "Zealot Helm", "Quiver Stub", "Handin Test Helm"} & plain  # hidden, disputed, deity-locked, not wearable, not for best in slot
    assert not {"Ogrebite Helm", "Ogrebite Torc"} & plain  # race-locked to Ogres
    assert "Bardic Greathelm" not in plain and "Fenwick Longbow" not in plain  # a class that the trio lacks
    assert {"Ogrebite Helm", "Ogrebite Torc"} <= pool(("PAL", "MNK", "ENC"), "OGR")
    assert {"Bardic Greathelm"} <= pool(("BRD", "MNK", "ENC"), "HUM")
    assert "Fenwick Longbow" in pool(("RNG", "MNK", "ENC"), "HUM")
    assert "Fistwrap Helm" not in pool(("PAL", "WAR", "ENC"), "HUM")  # a Monk-only piece, and no Monk


def test_the_strict_pool_holds_the_strict_items_alone(rules):
    records = [item("Level Test Helm", ["HEAD"], None, {"AC": 5}, level="strict"), item("Wiki Test Helm", ["HEAD"], None, {"AC": 5}, level="wiki")]
    table = ItemTable(items_document(records), rules)
    assert {r.name for r in table.eligible(("PAL", "MNK", "ENC"), "HUM", "strict")} == {"Level Test Helm"}
    assert {r.name for r in table.eligible(("PAL", "MNK", "ENC"), "HUM", "wiki")} == {"Level Test Helm", "Wiki Test Helm"}


def test_an_item_that_no_race_may_wear_is_in_no_pool(rules):
    record = item("Nobody Test Helm", ["HEAD"], None, {"AC": 5})
    record["races"] = []
    table = ItemTable(items_document([record]), rules)
    assert table.eligible(("PAL", "MNK", "ENC"), "HUM", "wiki") == []


def test_a_name_finds_its_items_by_the_comparison_of_names(rules):
    table = ItemTable(items_document(base_items()), rules)
    assert len(table.keys_named("vlorn  HELM")) == 1
    assert table.keys_named("No Such Item") == []


@pytest.mark.parametrize("missing", ["items.json", "defaults.json", "wiki-own.json"])
def test_a_missing_file_is_named_in_the_error(tmp_path, missing):
    root = _results(tmp_path, {"pal-mnk-enc": [row("tank", 4, {})]})
    target = root / missing if missing == "items.json" else root / "pal-mnk-enc" / missing
    target.unlink()
    with pytest.raises(ResultsError, match=missing):
        list(Results(root, rules=rules_module.load()).all_kits())


def test_a_shard_that_is_not_json_is_an_error_that_names_the_file(tmp_path):
    root = _results(tmp_path, {"pal-mnk-enc": [row("tank", 4, {})]})
    (root / "pal-mnk-enc" / "wiki-own.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ResultsError, match="wiki-own.json"):
        Results(root, rules=rules_module.load()).kits("pal-mnk-enc")


def test_a_shard_with_other_places_is_refused(tmp_path):
    root = _results(tmp_path, {"pal-mnk-enc": [row("tank", 4, {})]})
    path = root / "pal-mnk-enc" / "wiki-own.json"
    shard = json.loads(path.read_text(encoding="utf-8"))
    shard["places"] = shard["places"][:-1]
    path.write_text(json.dumps(shard), encoding="utf-8")
    with pytest.raises(ResultsError, match="22"):
        Results(root, rules=rules_module.load()).kits("pal-mnk-enc")


def test_a_shard_with_a_missing_field_is_an_error_not_a_crash(tmp_path):
    root = _results(tmp_path, {"pal-mnk-enc": [row("tank", 4, {})]})
    path = root / "pal-mnk-enc" / "wiki-own.json"
    shard = json.loads(path.read_text(encoding="utf-8"))
    del shard["totals"]
    path.write_text(json.dumps(shard), encoding="utf-8")
    with pytest.raises(ResultsError, match="wiki-own.json"):
        Results(root, rules=rules_module.load()).kits("pal-mnk-enc")


def test_a_shard_that_wears_an_item_the_table_lacks_is_an_error_not_a_crash(tmp_path):
    root = _results(tmp_path, {"pal-mnk-enc": [row("tank", 4, {"HEAD": "Vlorn Helm"})]})
    table = json.loads((root / "items.json").read_text(encoding="utf-8"))
    table["items"] = [record for record in table["items"] if record["name"] != "Vlorn Helm"]
    (root / "items.json").write_text(json.dumps(table), encoding="utf-8")
    results = Results(root, rules=rules_module.load())
    with pytest.raises(ResultsError, match="pal-mnk-enc.*items.json"):
        results.kits("pal-mnk-enc")
    with pytest.raises(ResultsError, match="items.json"):
        list(results.all_kits())


def test_a_wiki_item_marked_not_for_bis_is_in_no_pool(rules):
    """The solver leaves out an item that is temporary or that a quest takes on hand-in, whatever its evidence level says (``precompute.grid.select_items``)."""
    records = [item("Handin Pool Helm", ["HEAD"], None, {"AC": 5}, codes=["out-of-era", "not-for-bis"]), item("Plain Pool Helm", ["HEAD"], None, {"AC": 5}, codes=["out-of-era"])]
    table = ItemTable(items_document(records), rules)
    assert {r.name for r in table.eligible(("PAL", "MNK", "ENC"), "HUM", "wiki")} == {"Plain Pool Helm"}
    assert {r.name for r in table.pool("wiki")} == {"Plain Pool Helm"}


def test_the_pool_of_a_level_is_what_the_solver_could_use_for_any_trio(rules):
    table = ItemTable(items_document(base_items()), rules)
    names = {r.name for r in table.pool("wiki")}
    assert {"Vlorn Helm", "Ombrel Vestment", "Bardic Greathelm", "Ogrebite Helm", "Fenwick Longbow"} <= names  # whatever the class or the race
    assert not {"Phantom Helm", "Disputed Helm", "Zealot Helm", "Quiver Stub", "Handin Test Helm"} & names
    strict = ItemTable(items_document([item("S Helm", ["HEAD"], None, {"AC": 5}, level="strict"), item("W Helm", ["HEAD"], None, {"AC": 5})]), rules)
    assert {r.name for r in strict.pool("strict")} == {"S Helm"} and {r.name for r in strict.pool("wiki")} == {"S Helm", "W Helm"}


def test_an_item_the_model_cannot_read_is_an_error_that_says_so(rules):
    record = item("Odd Test Ring", ["FINGER"], None, {"ZZZ": 3})
    table = ItemTable(items_document([record]), rules)
    with pytest.raises(ResultsError, match="Odd Test Ring"):
        table.vec(f"w{record['id']}", 0)
    ok = item("Odd Test Band", ["FINGER"], None, {"STA": 3})
    with pytest.raises(ResultsError, match="tier"):
        ItemTable(items_document([ok]), rules).vec(f"w{ok['id']}", 11)


def test_a_shard_whose_totals_lack_a_key_the_checks_read_is_an_error_that_names_it(tmp_path):
    root = _results(tmp_path, {"pal-mnk-enc": [row("tank", 4, {})]})
    path = root / "pal-mnk-enc" / "wiki-own.json"
    shard = json.loads(path.read_text(encoding="utf-8"))
    at = shard["totals_keys"].index("ac")
    shard["totals_keys"].pop(at)
    shard["totals"] = [[v for n, v in enumerate(vector) if n != at] for vector in shard["totals"]]
    path.write_text(json.dumps(shard), encoding="utf-8")
    with pytest.raises(ResultsError, match=r"wiki-own.json.*\bac\b"):
        Results(root, rules=rules_module.load()).kits("pal-mnk-enc")


def test_the_rules_the_results_were_made_with_are_compared_with_the_rules_of_the_checkout(tmp_path):
    same = Results(_results(tmp_path / "a", {"pal-mnk-enc": [row("tank", 4, {})]}), rules=rules_module.load())
    assert same.rules_mismatch() is None
    other = Results(_results(tmp_path / "b", {"pal-mnk-enc": [row("tank", 4, {})]}, rules_version="1999-01-01"), rules=rules_module.load())
    assert other.rules_mismatch() == ("1999-01-01", rules_module.load().version)


def test_a_trio_whose_default_race_has_no_scenario_is_listed_as_unread_after_the_kits_are_read(tmp_path):
    root = _results(tmp_path, {"pal-mnk-enc": [row("tank", 4, {})], "war-clr-pal": [row("tank", 4, {}, race="OGR")]})  # the default race is HUM
    results = Results(root, rules=rules_module.load())
    assert [k.slug for k in results.all_kits()] == ["pal-mnk-enc"]
    assert results.unread == ["war-clr-pal"]


def test_a_folder_that_is_not_a_results_folder_is_refused(tmp_path):
    with pytest.raises(ResultsError, match="not a folder"):
        Results(tmp_path / "nowhere", rules=rules_module.load())
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "items.json").write_text(json.dumps(items_document(base_items())), encoding="utf-8")
    with pytest.raises(ResultsError, match="trio"):
        Results(tmp_path / "empty", rules=rules_module.load())


def test_an_item_table_that_is_not_one_is_refused(tmp_path):
    root = _results(tmp_path, {"pal-mnk-enc": [row("tank", 4, {})]})
    (root / "items.json").write_text(json.dumps({"items": "no"}), encoding="utf-8")
    with pytest.raises(ResultsError, match="items.json"):
        Results(root, rules=rules_module.load())


def test_a_plate_class_list_is_read_as_the_five_classes(rules):
    record = item("List Test Helm", ["HEAD"], PLATE, {"AC": 5})
    (found,) = ItemTable(items_document([record]), rules).eligible(("WAR", "MNK", "ENC"), "HUM", "wiki")
    assert found.classes == frozenset(PLATE)


def test_a_kit_carries_the_weapon_procs_its_shard_says_it_counts(tmp_path, rules):
    kit = {"PRIMARY": "Sorrel Staff", "CHEST": "Vlorn Tunic"}
    folder = make_results(tmp_path / "r", base_items(), {"pal-mnk-enc": [row("tank", 4, kit, setup="2h"), row("melee", 4, kit, setup="2h")]})
    path = folder / "pal-mnk-enc" / "wiki-own.json"
    shard = json.loads(path.read_text(encoding="utf-8"))
    counted = [["P", "Moon Brand", "w1", "h", 300.0]]
    shard["procs"] = {"rows": [counted], "at": [-1, 0]}  # (what a run writes: the distinct lists, and one index for each scenario)
    path.write_text(json.dumps(shard), encoding="utf-8")
    kits = {k.role: k for k in Results(folder, rules=rules).kits("pal-mnk-enc")}
    assert kits["tank"].procs == () and kits["melee"].procs == (("P", "Moon Brand", "w1", "h", 300.0),)
    shard.pop("procs")
    path.write_text(json.dumps(shard), encoding="utf-8")
    assert all(k.procs == () for k in Results(folder, rules=rules).kits("pal-mnk-enc"))  # a shard with no key: no procs, as before


@pytest.mark.parametrize(("at", "what"), [([-1, 0], "shorter than the scenarios"), ([-1, 0, 5], "an index of a row that is not there"), ([-1, 0, "a"], "an index that is no number")])
def test_a_procs_key_that_does_not_match_the_scenarios_is_refused_even_where_the_scenarios_it_covers_are_not_the_kits(tmp_path, rules, at, what):
    kit = {"PRIMARY": "Sorrel Staff", "CHEST": "Vlorn Tunic"}
    # the kits are those of the default race (HUM); the third scenario is another race's, which no kit reads
    rows = [row("tank", 4, kit, setup="2h"), row("melee", 4, kit, setup="2h"), row("tank", 4, kit, setup="2h", race="BAR")]
    folder = make_results(tmp_path / "r", base_items(), {"pal-mnk-enc": rows})
    path = folder / "pal-mnk-enc" / "wiki-own.json"
    shard = json.loads(path.read_text(encoding="utf-8"))
    shard["procs"] = {"rows": [[["P", "Moon Brand", "w1", "h", 300.0]]], "at": at}
    path.write_text(json.dumps(shard), encoding="utf-8")
    with pytest.raises(ResultsError, match="procs"):
        Results(folder, rules=rules).kits("pal-mnk-enc")
