"""Item pages: which items get one, and what the model of a page says (the page itself is rendered and checked in ``test_site_item_pages.py``).

An item gets a page when it is a wearable (it lists a slot that a place of a kit has: ``grid.WEARABLE_SLOTS``) whose evidence level in the item table
of the results is ``strict`` or ``wiki``. The level is the table's own, the release's, and never a private flag: the table is the file the kits were
made from, so a page and a kit of the same build always agree. A disputed or hidden item has no page. What a page says is worked out from the record
of the table: the stats at every tier are ``at_tier``'s, figure for figure, and nothing between two tiers is estimated.

Every name here is invented (the fixture's items, or items made for one test), except in the tests that read ``derived/catalog.json`` (the wiki's
catalog, which is committed): they pick items by their shape and name none.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from trioforge import rules as rules_module
from trioforge.data import evidence
from trioforge.export import browser
from trioforge.model.items import REGEN_KEYS, STAT_KEYS, SV_KEYS, at_tier
from trioforge.precompute import grid
from trioforge.site import build, content, data, view

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "fixtures" / "site" / "results"
RULES = REPO / "rules" / "rules.json"
CATALOG = REPO / "derived" / "catalog.json"
TIERS = range(11)
MINUS = "−"


def number(cell: str) -> float:
    """The figure a cell of a page shows, as a number (a true minus sign and a thousands separator are the page's way of writing it)."""
    return float(cell.replace(MINUS, "-").replace(",", ""))


@pytest.fixture(scope="module")
def world():
    table = json.loads((RESULTS / "items.json").read_text(encoding="utf-8"))
    return SimpleNamespace(
        rules=rules_module.load(RULES),
        book=content.load_rulebook(RULES),
        table=table,
        records={browser.record_key(record): record for record in table["items"]},
    )


def page_of(world, key: str, **more) -> view.ItemPage:
    return view.item_page(
        world.records[key], defaults=world.table["defaults"], rules=world.rules, book=world.book, wiki=more.pop("wiki", ("A wiki page", 4242)), **more
    )


def expected_rows(original: dict, rules) -> dict[str, list[float]]:
    """The rows a page must show for a catalog item, by the key of the stat, from ``at_tier`` alone: only a stat the item has, a figure for each tier."""
    vecs = [at_tier(original, tier, rules) for tier in TIERS]
    rows: dict[str, list[float]] = {}
    for key in (*STAT_KEYS, *REGEN_KEYS):
        values = [vec.stats.get(key, 0) for vec in vecs]
        if any(values):
            rows[key] = values
    if any(vec.haste for vec in vecs):
        rows["HASTE"] = [vec.haste for vec in vecs]
    for key in SV_KEYS:
        values = [vec.sv.get(key, 0) for vec in vecs]
        if any(values):
            rows[key] = values
    if vecs[0].weight_known:
        rows["WEIGHT"] = [vec.weight10 / 10 for vec in vecs]
    return rows


def shown_rows(page: view.ItemPage) -> dict[str, list[float]]:
    return {row.key: [number(cell) for cell in row.cells] for row in page.rows}


# ---- which items get a page ----------------------------------------------------------------------------------------------------------------


def test_the_wearable_slots_of_the_build_are_the_places_a_kit_has():
    assert build.WEARABLE_SLOTS == grid.WEARABLE_SLOTS
    assert "ANY" in build.WEARABLE_SLOTS and "AMMO" not in build.WEARABLE_SLOTS  # (a place, never a slot, of an item; and a slot no place has)


def test_a_page_is_made_for_every_strict_or_wiki_wearable_of_the_table_and_for_no_other(world):
    keys = build.item_page_keys(world.table)
    levels = {browser.record_key(record): record["evidence"]["level"] for record in world.table["items"]}
    assert Counter(levels.values()) == {"strict": 44, "wiki": 3, "hidden": 1}
    assert keys == sorted(key for key, level in levels.items() if level in ("strict", "wiki"))
    assert len(keys) == 47  # the fixture's count, whole and exact: 48 records, one of them hidden
    assert "w90041" not in keys and "w90040" in keys  # a hidden helm has none; a cap that no class of the trio can wear is a strict item all the same


def test_the_levels_that_make_a_page_and_the_slots_that_make_an_item_wearable_decide_it_and_nothing_else():
    def record(page, level, slots, **more):
        return {"id": page, "name": f"Item {page}", "slots": slots, "evidence": {"level": level}, **more}

    table = {
        "items": [
            record(1, "strict", ["HEAD"]),
            record(2, "wiki", ["PRIMARY", "SECONDARY"]),
            record(3, "wiki", ["AMMO"]),  # no place of a kit
            record(4, "strict", ["CHARM", "POWERSOURCE"]),
            record(5, "disputed", ["HEAD"]),
            record(6, "hidden", ["HEAD"], owned_only=True),
            record(7, "wiki", ["AMMO", "RANGE"]),  # a thrown weapon fits the range place and the ammo place
            record(8, "strict", ["EAR"], key="rmoon-ring"),  # an item with no page on the wiki has a key of its own
            record(9, "disputed", ["AMMO"]),
        ]
    }
    assert build.item_page_keys(table) == ["rmoon-ring", "w1", "w2", "w7"]


def test_the_levels_are_the_tables_and_a_record_of_another_level_is_not_made_a_page_by_anything_else(world):
    table = json.loads(json.dumps(world.table))
    changed = {browser.record_key(r): r for r in table["items"]}
    changed["w90001"]["evidence"] = {"level": "disputed", "codes": ["out-of-era-tag-live-zone"]}  # strict -> disputed
    changed["w90003"]["evidence"] = {"level": "hidden"}  # wiki -> hidden
    changed["w90003"]["owned_only"] = True
    keys = build.item_page_keys(table)
    assert "w90001" not in keys and "w90003" not in keys and len(keys) == 45


@pytest.mark.parametrize("bad", ["", "W1", "w 1", "w1/../x", "../w1", "w1.html", "a/b", "w" + "1" * 100, "é1"])
def test_a_key_that_would_not_be_one_path_segment_is_refused_before_it_makes_a_page(bad):
    table = {"items": [{"id": 1, "key": bad, "name": "x", "slots": ["HEAD"], "evidence": {"level": "strict"}}]}
    with pytest.raises(build.BuildError, match="not an item key"):
        build.item_page_keys(table)


KEYS = [
    "w1", "w90001", "w999999999999999", "rmoon-ring", "ra", "r" + "a" * 100, "r" + "9" * 100,  # (a page id of up to 15 digits, a key of an item with no page, one of 101 characters)
    "", "w", "w0", "w01", "w1234567890123456", "W1", "r", "r-a", "r" + "a" * 101, "w1/../x", "a1", "item-1", "x90001", "rÉ", "r a", "w1 ", " w1", "w1\n",
]  # fmt: skip


@pytest.mark.parametrize("key", KEYS)
def test_the_reader_of_the_results_and_the_list_of_pages_take_the_same_keys(key):
    """One pattern of an item key: a record the reader accepts is a record that can have a page, and a key that would not be an address is refused by the reader as well."""
    assert (data._KEY.match(key) is not None) == (build._ITEM_KEY.fullmatch(key) is not None), repr(key)


def test_the_longest_key_the_reader_accepts_gets_a_page_and_the_pattern_is_one_text_in_both_places():
    longest = "r" + "a" * 100
    table = {"items": [{"id": None, "key": longest, "name": "x", "slots": ["HEAD"], "evidence": {"level": "wiki"}}]}
    assert build.item_page_keys(table) == [longest]
    assert data.KEY_PATTERN in (data._KEY.pattern, build._ITEM_KEY.pattern) and build._ITEM_KEY.pattern == data.KEY_PATTERN


def test_a_key_that_two_records_have_is_refused(world):
    table = {"items": [world.records["w90001"], world.records["w90001"]]}
    with pytest.raises(build.BuildError, match="twice"):
        build.item_page_keys(table)


@pytest.mark.parametrize(
    "other",
    [
        {"evidence": {"level": "hidden"}, "owned_only": True},
        {"evidence": {"level": "disputed", "codes": ["out-of-era-tag-live-zone"]}},
        {"slots": ["AMMO"]},  # no place of a kit
        {"evidence": {"level": "hidden"}, "owned_only": True, "slots": ["AMMO"]},
    ],
    ids=["hidden", "disputed", "not a wearable", "hidden and not a wearable"],
)
def test_a_key_that_a_page_and_a_record_without_a_page_share_is_refused_whichever_comes_first(world, other):
    """The page is built from the record the lookup keeps, which is the last of the two: so every record of the table counts, and not only the ones that get a page."""
    twin = {**world.records["w90001"], **other}
    for records in ([world.records["w90001"], twin], [twin, world.records["w90001"]]):
        with pytest.raises(build.BuildError, match=r"w90001 twice"):
            build.item_page_keys({"items": records})


def test_a_key_that_two_records_without_a_page_share_is_refused_too_and_distinct_keys_are_not(world):
    hidden = {**world.records["w90001"], "evidence": {"level": "hidden"}, "owned_only": True}
    with pytest.raises(build.BuildError, match=r"w90001 twice"):
        build.item_page_keys({"items": [hidden, dict(hidden)]})
    other = {**hidden, "id": 90099}
    assert build.item_page_keys({"items": [world.records["w90001"], hidden | {"id": 90098}, other]}) == ["w90001"]  # (a hidden record of another key is no twin)


# ---- the stats at every tier -----------------------------------------------------------------------------------------------------------------


def test_the_tier_table_of_every_item_of_the_fixture_is_at_tier_figure_for_figure(world):
    checked = 0
    for key in build.item_page_keys(world.table):
        original = browser.item_to_catalog(world.records[key], world.table["defaults"])
        page = page_of(world, key)
        assert page.tiers == tuple(f"+{tier}" for tier in TIERS), key
        assert shown_rows(page) == expected_rows(original, world.rules), key
        assert all(len(row.cells) == 11 for row in page.rows), key
        checked += 1
    assert checked == 47


def test_a_stat_is_worked_out_by_the_tier_rule_and_not_between_two_tiers(world):
    # Helm of the Stoneward: AC 30, STA 12, HP 60 and 4.0 stone at +0. A stat is base + max(n, floor(base * n / 10)): at least one a tier, and a tenth of the base a tier when that is more.
    page = page_of(world, "w90001")
    rows = {row.key: row for row in page.rows}
    assert [number(c) for c in rows["AC"].cells] == [30, 33, 36, 39, 42, 45, 48, 51, 54, 57, 60]
    assert [number(c) for c in rows["STA"].cells] == [12, 13, 14, 15, 16, 18, 19, 20, 21, 22, 24]  # +1 a tier up to +4, then 12 * n // 10
    assert [number(c) for c in rows["HP"].cells] == [60, 66, 72, 78, 84, 90, 96, 102, 108, 114, 120]
    assert rows["WEIGHT"].cells == ("4.0", "3.6", "3.2", "2.8", "2.4", "2.0", "1.6", "1.2", "0.8", "0.4", "0.1")  # (a tenth of a stone is the least an item weighs)


def test_the_rows_are_the_stats_the_item_has_in_the_order_of_the_model_then_haste_resists_and_weight(world):
    page = page_of(world, "w80988")  # a pike: STR, ATK and a fire resist
    assert [row.key for row in page.rows] == ["STR", "ATK", "FIRE", "WEIGHT"]
    haste = page_of(world, "w90008")  # a hoop of haste
    assert [row.key for row in haste.rows] == ["AGI", "HASTE", "WEIGHT"]
    assert [number(cell) for cell in {r.key: r for r in haste.rows}["HASTE"].cells] == [15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25]  # a flat step a tier, not a percentage


def test_the_weight_falls_with_the_tier_to_a_floor_and_an_item_with_no_weight_has_no_row(world):
    page = page_of(world, "w90029")  # a breastplate of 10.0 stone
    weight = {row.key: row for row in page.rows}["WEIGHT"]
    assert weight.cells[0] == "10.0" and number(weight.cells[10]) < 10
    assert all(len(cell.split(".")[1]) == 1 for cell in weight.cells)  # tenths of a stone
    assert "WEIGHT" not in {row.key for row in page_of(world, "w90037").rows}  # the page gives no weight
    assert dict((fact.label, fact.value) for fact in page_of(world, "w90037").facts)["Weight"] == "not listed"


def test_a_negative_stat_stays_as_it_is_at_every_tier_with_a_true_minus_sign():
    record = {
        "id": 9, "name": "Heavy Hat", "slots": ["HEAD"], "stats": {"AC": 10, "AGI": -5}, "weight10": 20, "tier_rule": "drop",
        "evidence": {"level": "wiki"},
    }  # fmt: skip
    table = {"defaults": browser.ITEM_DEFAULTS, "items": [record]}
    page = view.item_page(
        record, defaults=table["defaults"], rules=rules_module.load(RULES), book=content.load_rulebook(RULES), wiki=("Heavy Hat", 1)
    )
    agi = {row.key: row for row in page.rows}["AGI"]
    assert set(agi.cells) == {f"{MINUS}5"}


def test_a_thousand_is_written_with_the_separator_of_the_trio_page():
    record = {
        "id": 9, "name": "Titan Plate", "slots": ["CHEST"], "stats": {"AC": 1200, "HP": 5000}, "weight10": 100, "tier_rule": "drop",
        "evidence": {"level": "wiki"},
    }  # fmt: skip
    page = view.item_page(
        record, defaults=browser.ITEM_DEFAULTS, rules=rules_module.load(RULES), book=content.load_rulebook(RULES), wiki=("Titan Plate", 1)
    )
    ac = {row.key: row for row in page.rows}["AC"]
    assert ac.cells[0] == "1,200" and ac.cells[10] == "2,400"
    assert view.fmt_int(1200) == "1,200"


def test_an_item_with_no_stat_and_no_weight_has_no_rows_at_all():
    record = {"id": 9, "name": "Bare Ring", "slots": ["FINGER"], "weight10": None, "tier_rule": "fixed0", "evidence": {"level": "strict"}}
    page = view.item_page(
        record, defaults=browser.ITEM_DEFAULTS, rules=rules_module.load(RULES), book=content.load_rulebook(RULES), wiki=("Bare Ring", 1)
    )
    assert page.rows == () and page.rules == ()


def test_the_rules_the_rows_follow_are_named_with_their_seals(world):
    page = page_of(world, "w90008")  # stats, haste and weight
    assert [ref.id for ref in page.rules] == ["tier.stat_rule", "haste.worn_per_tier", "tier.weight_floor"]
    assert all(ref.seal in content.SEALS and ref.seal_icon == f"i-{ref.seal}" for ref in page.rules)
    assert [ref.id for ref in page_of(world, "w80158").rules] == ["tier.stat_rule", "tier.weight_floor"]


# ---- weapons -----------------------------------------------------------------------------------------------------------------------------------


def test_a_weapon_shows_its_damage_and_delay_at_every_tier_with_the_seal_of_the_weapon_tier_rule(world):
    weapons = [key for key in build.item_page_keys(world.table) if (world.records[key].get("weapon") or {}).get("dmg") is not None and not world.records[key].get("item_type")]
    assert len(weapons) == 5
    for key in weapons:
        original = browser.item_to_catalog(world.records[key], world.table["defaults"])
        vecs = [at_tier(original, tier, world.rules) for tier in TIERS]
        page = page_of(world, key)
        assert page.weapon is not None, key
        rows = {row.key: [number(c) for c in row.cells] for row in page.weapon.rows}
        assert rows == {"DAMAGE": [vec.weapon.dmg for vec in vecs], "DELAY": [vecs[0].weapon.delay] * 11}, key
        assert page.weapon.skill == original["weapon"]["skill"] and page.weapon.two_handed == vecs[0].weapon.two_handed
        assert page.weapon.rule.id == "tier.weapon_damage_pct" and page.weapon.rule.seal == "player" and page.weapon.rule.open_test is not None


def test_damage_grows_by_five_percent_a_tier_and_at_least_one_and_the_delay_does_not_change(world):
    page = page_of(world, "w80524")  # a two-hander of 36 damage and a delay of 38
    rows = {row.key: row for row in page.weapon.rows}
    assert [number(c) for c in rows["DAMAGE"].cells] == [36, 37, 39, 41, 43, 45, 46, 48, 50, 52, 54]  # dmg + max(n, dmg * n * 5 // 100)
    assert rows["DELAY"].cells == ("38",) * 11 and page.weapon.two_handed is True and page.weapon.skill == "2H Slashing"
    assert page.weapon.bonus == "22"  # the damage bonus the page lists does not change either


def test_a_shield_and_an_item_that_is_no_weapon_have_no_weapon_table(world):
    assert page_of(world, "w80583").weapon is None  # a targe
    assert page_of(world, "w90001").weapon is None  # a helm


def test_a_weapon_that_names_no_skill_still_has_its_table_and_says_nothing_of_a_bonus_it_does_not_have():
    record = {
        "id": 9, "name": "Plain Club", "slots": ["PRIMARY"], "weapon": {"skill": None, "dmg": 10, "delay": 20, "bonus": None}, "weight10": 10,
        "tier_rule": "drop", "evidence": {"level": "wiki"},
    }  # fmt: skip
    page = view.item_page(record, defaults=browser.ITEM_DEFAULTS, rules=rules_module.load(RULES), book=content.load_rulebook(RULES), wiki=("Plain Club", 1))
    assert page.weapon is not None and page.weapon.skill is None and page.weapon.bonus is None and page.weapon.two_handed is False
    assert [number(c) for c in page.weapon.rows[0].cells] == [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]


@pytest.mark.parametrize("level", ["disputed", "hidden"])
def test_an_item_of_a_level_that_has_no_page_is_refused_by_the_model_whatever_else_is_asked_of_it(world, level):
    record = {**world.records["w90001"], "evidence": {"level": level}}
    with pytest.raises(ValueError, match="has no page"):
        view.item_page(record, defaults=world.table["defaults"], rules=world.rules, book=world.book, wiki=("A wiki page", 1))


# ---- the facts, the sources, the evidence and the credit -----------------------------------------------------------------------------------------


def facts(page: view.ItemPage) -> dict[str, str]:
    return {fact.label: fact.value for fact in page.facts}


def test_the_facts_are_the_name_s_slots_classes_races_deity_lore_and_weight(world):
    mallet = facts(page_of(world, "w80113"))
    assert mallet["Slots"] == "Main hand, Off hand" and mallet["Classes"] == "All" and mallet["Races"] == "All" and mallet["Weight"] == "3.0 stone"
    assert "Deity" not in mallet and "Lore" not in mallet
    assert facts(page_of(world, "w90040"))["Classes"] == "Wizard"
    assert facts(page_of(world, "w90033"))["Races"] == "Ogre, Troll"
    assert facts(page_of(world, "w90004"))["Deity"] == "Needs deity: The Tribunal"
    assert facts(page_of(world, "w90046"))["Deity"] == "Needs deity: The Tribunal or Rodcet Nife"
    assert facts(page_of(world, "w90026"))["Lore"] == "Yes (only one can be carried)"
    assert facts(page_of(world, "w90001"))["Slot"] == "Head"
    assert facts(page_of(world, "w80583"))["Type"] == "Shield"


def test_an_item_that_no_class_and_no_race_may_wear_says_none_and_a_list_of_classes_is_in_the_order_of_the_game():
    base = {"id": 9, "name": "Void Ring", "slots": ["FINGER"], "weight10": 10, "tier_rule": "drop", "evidence": {"level": "wiki"}}
    args = {"defaults": browser.ITEM_DEFAULTS, "rules": rules_module.load(RULES), "book": content.load_rulebook(RULES), "wiki": ("Void Ring", 1)}
    nobody = facts(view.item_page({**base, "classes": [], "races": []}, **args))
    assert nobody["Classes"] == "None" and nobody["Races"] == "None"  # a page that says Class: NONE and Race: NONE
    some = facts(view.item_page({**base, "classes": ["BER", "PAL", "WAR"], "races": ["TRL", "HUM", "OGR"]}, **args))
    assert some["Classes"] == "Warrior, Paladin, Berserker"  # in the order of the class ids
    assert some["Races"] == "Human, Ogre, Troll"  # by name, as the race switch of a trio page lists them


def test_the_sources_are_what_the_table_holds_with_what_did_not_fit_counted(world):
    def sources(key):
        return [(line.label, line.text) for line in page_of(world, key).sources]

    assert sources("w90001") == [("Drops in", "The Hole")]
    assert sources("w80158") == [("Quests", "Lake Rathetear quest")]
    assert sources("w90008") == [("Vendors in", "Freeport")]
    assert sources("w80236") == [("Crafted", "1 recipe")]
    record = {
        "id": 9, "name": "Far-flung Ring", "slots": ["FINGER"], "tier_rule": "drop", "evidence": {"level": "wiki"}, "weight10": 10,
        "source": {
            "drops": ["Alpha", "Beta", "Gamma"], "sold": ["Delta"], "forage": ["Epsilon", "Zeta"], "quests": ["Eta", "Theta"], "crafted": 3,
            "more": {"drops": 16, "quests": 1, "forage": 4},
        },
    }  # fmt: skip
    page = view.item_page(
        record, defaults=browser.ITEM_DEFAULTS, rules=rules_module.load(RULES), book=content.load_rulebook(RULES), wiki=("Far-flung Ring", 1)
    )
    assert [(line.label, line.text) for line in page.sources] == [
        ("Drops in", "Alpha, Beta, Gamma and 16 more"),
        ("Quests", "Eta, Theta and 1 more"),
        ("Vendors in", "Delta"),
        ("Crafted", "3 recipes"),
        ("Foraged in", "Epsilon, Zeta and 4 more"),
    ]


def test_an_item_with_no_source_in_the_table_says_so_and_has_no_lines(world):
    record = {"id": 9, "name": "Lost Ring", "slots": ["FINGER"], "weight10": 10, "tier_rule": "drop", "evidence": {"level": "strict"}}
    page = view.item_page(
        record, defaults=browser.ITEM_DEFAULTS, rules=rules_module.load(RULES), book=content.load_rulebook(RULES), wiki=("Lost Ring", 1)
    )
    assert page.sources == ()


def test_the_evidence_level_has_the_seal_and_the_words_of_the_trio_page(world):
    strict, wiki = page_of(world, "w90001"), page_of(world, "w90003")
    assert (strict.level, strict.level_seal, strict.level_icon) == ("strict", "Seen in game", "i-strict")
    assert (wiki.level, wiki.level_seal, wiki.level_icon) == ("wiki", "Wiki", "i-wiki")
    assert (strict.level_seal, strict.level_icon) == (view.ITEM_SEALS["strict"][0], view.ITEM_SEALS["strict"][1])
    assert strict.level_text != wiki.level_text and strict.level_text.startswith("Strict evidence") and wiki.level_text.startswith("Wiki evidence")  # (the words of the Assumes line)
    assert "strict kits leave it out" in wiki.level_text and "Seen in game" not in wiki.level_text  # an item the wiki lists is not one that was seen: it says so


LADDER = REPO / "pipeline" / "trioforge" / "data" / "evidence.py"


def ladder_codes() -> set[str]:
    """The reason codes the evidence ladder can give, read from its source (the live-source reasons, which the item table leaves out, have a colon in their code and are not among them)."""
    text = LADDER.read_text(encoding="utf-8")
    return set(re.findall(r'\b(?:reasons|strict)\["([a-z]+(?:-[a-z]+)*)"\]\s*=\s*_reason\(', text))


NOTES = {"not-for-bis", "not-for-default-kits", "wiki-marked-revamped"}  # (the ladder's own list of the notes about an item: evidence.NOTE_CODES)
NOT_FOR_BIS = "Kept in the catalog and not used for best-in-slot"  # how the words of that note begin


def page_with_codes(world, level: str, codes: list[str], **record):
    return view.item_page(
        {"id": 9, "name": "Rescued Ring", "slots": ["FINGER"], "weight10": 10, "tier_rule": "drop", "evidence": {"level": level, "codes": codes}, **record},
        defaults=browser.ITEM_DEFAULTS, rules=world.rules, book=world.book, wiki=("Rescued Ring", 1),
    )  # fmt: skip


def test_the_wiki_reason_does_not_say_where_the_source_is_and_is_the_same_for_an_item_that_is_crafted_only(world):
    """A wiki item can be live by a drop, a quest, a vendor, a recipe or foraging, so its reason says that the wiki lists a source that the site counts as live, and no more: an item that is
    crafted and dropped nowhere has no zone, and a sentence about one would be false beside the line that says how it is made."""
    wiki = page_of(world, "w90003")
    assert wiki.level_text == "Wiki evidence: the wiki lists a source that the site counts as live. Not seen in game yet, so strict kits leave it out."
    assert "zone" not in wiki.level_text and "EQL" not in wiki.level_text
    crafted = page_with_codes(world, "wiki", [], source={"crafted": 2})
    assert crafted.level_text == wiki.level_text and [(line.label, line.text) for line in crafted.sources] == [("Crafted", "2 recipes")]


def test_a_note_about_the_item_is_said_with_its_seal_and_a_sentence(world):
    deity = page_of(world, "w90004")  # a deity-locked crown
    assert [(note.seal, note.icon, note.seal_label) for note in deity.notes] == [("model", "i-model", "Model")]
    assert "Deity-locked" in deity.notes[0].text
    assert page_of(world, "w90001").notes == ()
    revamped = page_with_codes(world, "wiki", ["wiki-marked-revamped"])
    assert [(note.seal, note.icon) for note in revamped.notes] == [("player", "i-player")] and "revamped" in revamped.notes[0].text


def test_the_notes_are_the_ones_about_the_item_in_the_order_of_the_table_and_each_has_words(world):
    page = page_with_codes(world, "wiki", ["not-for-bis", "not-for-default-kits", "wiki-marked-revamped"])
    assert [note.seal for note in page.notes] == ["model", "model", "player"]
    assert all(note.text.endswith(".") and not any(code in note.text for code in NOTES) for note in page.notes)  # a sentence, not a code
    assert set(view.ITEM_NOTES) == NOTES == evidence.NOTE_CODES


@pytest.mark.parametrize("code", sorted(ladder_codes() - NOTES))
def test_a_reason_of_the_evidence_is_never_shown_on_a_page_of_either_level_even_where_the_table_keeps_it(world, code):
    """The table keeps the reasons of the public catalog on an item that a seen flag made strict, so the reason an item was hidden or disputed for can be on a strict record.
    Shown under "Seen in game" it would tell that a sighting rescued the item, and it is about the evidence, which the page words by its level."""
    for level in ("strict", "wiki"):
        page = page_with_codes(world, level, [code, "not-for-bis"])
        assert len(page.notes) == 1 and page.notes[0].text.startswith(NOT_FOR_BIS), (level, code, [note.text for note in page.notes])  # the note about the item, and nothing about the evidence
        assert page.level_text.startswith(("Strict evidence", "Wiki evidence")) and code not in page.level_text


def test_an_item_that_a_seen_flag_made_strict_shows_the_words_of_its_level_and_only_the_notes_about_the_item(world):
    hidden_for = ["cultural-container", "out-of-era", "out-of-era-ingredient", "zones-not-in-eql", "no-known-source", "wiki-marked-not-in-eql"]
    page = page_with_codes(world, "strict", [*hidden_for, "not-for-bis"])
    assert (page.level, page.level_seal) == ("strict", "Seen in game") and page.level_text.startswith("Strict evidence")
    assert len(page.notes) == 1 and page.notes[0].text.startswith(NOT_FOR_BIS), [note.text for note in page.notes]
    assert not any(code in note.text for note in page.notes for code in hidden_for)


def test_a_code_the_ladder_does_not_give_is_refused_and_never_shown_raw(world):
    with pytest.raises(ValueError, match="a-code-from-the-future"):
        page_with_codes(world, "wiki", ["wiki-marked-revamped", "a-code-from-the-future"])
    with pytest.raises(ValueError, match="rrescued-ring"):  # (and the message says which item, by its key)
        page_with_codes(world, "strict", ["x"], key="rrescued-ring")


def test_the_codes_the_site_knows_are_the_ones_the_ladder_gives_so_a_new_code_must_be_worded_or_set_aside_before_a_page_can_show_it():
    given = ladder_codes()
    assert len(given) >= 20 and {"seen-in-game", "out-of-era", "not-for-bis", "removed-by-patch", "conflict-note"} <= given  # (the scan of the source found its codes)
    assert view.EVIDENCE_CODES | set(view.ITEM_NOTES) == given
    assert not view.EVIDENCE_CODES & set(view.ITEM_NOTES)


def test_the_wiki_credit_is_the_page_title_and_the_revision_with_the_address_of_that_revision(world):
    page = page_of(world, "w90001", wiki=("Helm of the Stoneward", 200000))
    assert (page.wiki_title, page.wiki_revid) == ("Helm of the Stoneward", 200000)
    assert page.wiki_href == content.wiki_url("Helm of the Stoneward", 200000) == "https://eqlwiki.com/index.php?title=Helm_of_the_Stoneward&oldid=200000"


NO_WIKI_PAGE = {
    "id": None, "key": "rmoon-ring", "name": "Moonlit Ring", "slots": ["FINGER"], "stats": {"AC": 5}, "weight10": 10, "tier_rule": "drop", "evidence": {"level": "strict"},
}  # an invented item that has no page on the wiki: no page id, a key of its own (an r, and small letters, digits and hyphens)


def test_an_item_with_no_wiki_page_has_a_page_and_no_wiki_credit(world):
    page = view.item_page(NO_WIKI_PAGE, defaults=world.table["defaults"], rules=world.rules, book=world.book, wiki=None)
    assert page.key == "rmoon-ring" and page.name == "Moonlit Ring" and page.title == "Moonlit Ring · TrioForge"
    assert (page.wiki_title, page.wiki_revid, page.wiki_href) == (None, None, None)  # nothing to credit: no empty title, no revision 0, no address of nothing
    original = browser.item_to_catalog(NO_WIKI_PAGE, world.table["defaults"])
    assert shown_rows(page) == expected_rows(original, world.rules)  # (the rest of the page is what any page is: at_tier's figures)
    assert page.level == "strict" and page.best_for == ()


def test_a_credit_is_given_to_the_wiki_page_an_item_was_read_from_and_only_to_one(world):
    with pytest.raises(ValueError, match=r"rmoon-ring.*no wiki page"):  # a title and a revision for an item that is not from a wiki page
        view.item_page(NO_WIKI_PAGE, defaults=world.table["defaults"], rules=world.rules, book=world.book, wiki=("A wiki page", 4242))
    with pytest.raises(ValueError, match=r"w90001.*credit"):  # an item that is from a wiki page, and no title and revision to credit it with
        view.item_page(world.records["w90001"], defaults=world.table["defaults"], rules=world.rules, book=world.book, wiki=None)


def test_the_title_and_the_description_name_the_item_and_the_title_is_not_another_page_s(world):
    titles = {page_of(world, key).title for key in build.item_page_keys(world.table)}
    assert len(titles) == 47  # one for each
    page = page_of(world, "w90001")
    assert page.title == "Helm of the Stoneward · TrioForge" and page.name == "Helm of the Stoneward" and page.key == "w90001"
    assert "Helm of the Stoneward" in page.description and len(page.description) <= 240
    long = {"id": 9, "name": "Z" * 300, "slots": ["HEAD"], "weight10": None, "tier_rule": "drop", "evidence": {"level": "wiki"}}
    assert len(view.item_page(long, defaults=browser.ITEM_DEFAULTS, rules=rules_module.load(RULES), book=content.load_rulebook(RULES), wiki=("x", 1)).description) <= 240


# ---- best for these trios ----------------------------------------------------------------------------------------------------------------------


def trio_names(count: int) -> list[tuple[str, str]]:
    """``(slug, name)`` of ``count`` trios, in the order of their slugs (class order)."""
    from itertools import combinations

    from trioforge.classes import CLASS_CODES

    return [("-".join(code.lower() for code in trio), view.trio_name(trio)) for trio in list(combinations(CLASS_CODES, 3))[:count]]


def test_none_is_said_plainly_when_no_default_answer_wears_the_item(world):
    page = page_of(world, "w90001", wearers=())
    assert page.best_for == () and page.best_more == 0


def test_the_trios_that_wear_the_item_are_listed_in_the_order_of_their_slugs_as_the_home_page_lists_them(world):
    wearers = trio_names(6)
    page = page_of(world, "w90001", wearers=list(reversed(wearers)))  # (given in any order)
    assert [(link.slug, link.name) for link in page.best_for] == sorted(wearers) and page.best_more == 0
    assert [link.slug for link in page.best_for] == sorted(slug for slug, _ in wearers)


@pytest.mark.parametrize(("count", "shown", "more"), [(1, 1, 0), (19, 19, 0), (20, 20, 0), (21, 20, 1), (25, 20, 5), (560, 20, 540)])
def test_at_most_twenty_trios_are_listed_and_the_rest_are_counted(world, count, shown, more):
    from itertools import combinations

    from trioforge.classes import CLASS_CODES

    assert view.BEST_FOR_MAX == 20
    everyone = [("-".join(code.lower() for code in trio), view.trio_name(trio)) for trio in combinations(CLASS_CODES, 3)]
    wearers = everyone[:count]
    page = page_of(world, "w90001", wearers=wearers)
    assert len(page.best_for) == shown and page.best_more == more
    assert [link.slug for link in page.best_for] == [slug for slug, _ in sorted(wearers)[:shown]]  # the first twenty by slug


# ---- which trios wear an item ------------------------------------------------------------------------------------------------------------------


def test_the_default_answer_of_a_trio_wears_the_items_of_the_default_scenario_and_no_other():
    results = data.load_trio(RESULTS / "pal-mnk-ber")
    # read the plain way, from the compact data the page fetches: the scenario the defaults name, and the items of its kit
    shard = json.loads((RESULTS / "pal-mnk-ber" / "strict-own.json").read_text(encoding="utf-8"))
    defaults = json.loads((RESULTS / "pal-mnk-ber" / "defaults.json").read_text(encoding="utf-8"))
    row = next(r for r in shard["scenarios"] if r[:4] == [defaults["race"], defaults["view"]["role"], defaults["view"]["tier"], defaults["setup"]])
    worn = {shard["items"][index][0] for index in shard["kits"][row[4]] if index >= 0}
    assert len(worn) >= 15 and (defaults["view"]["evidence"], defaults["view"]["buffs"]) == ("strict", "own")
    assert view.default_kit_keys(results) == frozenset(worn)
    assert "w90040" not in worn  # the wizard's cap is in the table and in no kit


# ---- the same page for real items --------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    rules = rules_module.load(RULES)
    table = browser.items(catalog, rules)
    originals = {item["key"]: item for item in catalog["items"]}
    return SimpleNamespace(
        rules=rules, book=content.load_rulebook(RULES), table=table, originals=originals,
        records={browser.record_key(record): record for record in table["items"]},
    )  # fmt: skip


def twenty(real) -> list[str]:
    """Twenty real wearables of the wiki level, picked by their shape and not by name: weapons of every skill the catalog has (first), a shield, an item of haste, one
    with a regeneration, one with a negative stat, an item with no weight, and plain armour, spread evenly over the keys."""
    pool = sorted(key for key, record in real.records.items() if record["evidence"]["level"] == "wiki")

    def weapon(key):
        w = real.records[key].get("weapon") or {}
        return w.get("dmg") is not None and w.get("delay") is not None and not real.records[key].get("item_type")

    weapons = [key for key in pool if weapon(key)]
    skills = {}
    for key in weapons:
        skills.setdefault(real.records[key]["weapon"]["skill"], key)
    chosen = list(skills.values())[:8]
    chosen += [key for key in pool if (real.records[key].get("item_type") or "").lower() == "shield"][:1]
    chosen += [key for key in pool if real.records[key].get("stats", {}).get("HASTE")][:1]
    chosen += [key for key in pool if any(real.records[key].get("stats", {}).get(k) for k in REGEN_KEYS)][:1]
    chosen += [key for key in pool if any(v < 0 for v in real.records[key].get("stats", {}).values())][:1]
    chosen += [key for key in pool if real.records[key].get("weight10") is None][:1]
    rest = [key for key in pool if key not in chosen and not weapon(key)]
    chosen += rest[:: max(1, len(rest) // (20 - len(chosen)))][: 20 - len(chosen)]
    assert len(chosen) == 20 and len(set(chosen)) == 20
    return chosen


def test_the_tier_table_of_twenty_real_items_is_at_tier_figure_for_figure_weapons_among_them(real):
    keys = twenty(real)
    weapons = 0
    for key in keys:
        original = real.originals[key]
        record = real.records[key]
        page = view.item_page(record, defaults=real.table["defaults"], rules=real.rules, book=real.book, wiki=("A wiki page", 1))
        assert shown_rows(page) == expected_rows(original, real.rules), key
        vecs = [at_tier(original, tier, real.rules) for tier in TIERS]
        if vecs[0].weapon is not None:
            weapons += 1
            rows = {row.key: [number(c) for c in row.cells] for row in page.weapon.rows}
            assert rows == {"DAMAGE": [vec.weapon.dmg for vec in vecs], "DELAY": [vecs[0].weapon.delay] * 11}, key
        else:
            assert page.weapon is None, key
    assert weapons >= 6


def test_every_wearable_of_the_wiki_catalog_has_a_page_model_that_needs_nothing_the_table_lacks(real):
    keys = build.item_page_keys(real.table)
    assert len(keys) > 1500  # (the public catalog has no strict item: these are the wiki level)
    for key in keys[:: max(1, len(keys) // 300)]:
        page = view.item_page(real.records[key], defaults=real.table["defaults"], rules=real.rules, book=real.book, wiki=("A wiki page", 1))
        assert page.key == key and page.level == "wiki" and len(page.description) <= 240
