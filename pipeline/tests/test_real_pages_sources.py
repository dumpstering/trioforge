"""Real item pages for the second parser review (2026-10-14): quest links, zones written as bullets,
foraged zones, map positions and prose in drop lists, keys the reader missed, charges, categories inside a template.

The pages are in fixtures/wiki (see its README): real eqlwiki text taken from the cached pull of 2026-10-14, with no
new request. Each test names the page, says what is odd about it and pins what the parser, the normalizer and the
evidence ladder make of it (with the real hand lists, zone aliases, client zones and quest table). The synthetic
versions of the same cases are in test_itempage_sources.py, test_normalize_sources.py and test_evidence_sources.py.
"""

import json
from pathlib import Path

import pytest

from trioforge.data.evidence import Context, QuestTable, classify, is_known_zone, load_aliases, load_hand_lists
from trioforge.data.normalize import normalize, promote_bullet_zones, validate_item
from trioforge.sources.eqlwiki import fixture_slug, page_records
from trioforge.sources.itempage import ParsedPage, parse_page

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures" / "wiki"
RULES = REPO / "rules"
CLIENT = REPO / "derived" / "client"

NEW_FIXTURES = [
    "Griffin-Hide Armguards",
    "Wind Rune Meda",
    "Large Empty Crate",
    "Velium Spear",
    "Crushed Diamonds",
    "Morning Dew",
    "Chilled Tundra Root",
    "Fishing Grubs",
    "Chipped Jade",
    "Crude Coal",
    "Keg Mallet",
    "Essence of Earth",
    "Fine Steel Naginata",
    "Shroud of the Sky",
    "Spiroc Beak Earcuff",
]


def record(title):
    path = FIXTURES / f"{fixture_slug(title)}.json"
    (found,) = page_records(json.loads(path.read_text(encoding="utf-8")))
    return found


def parsed(title):
    result = parse_page(record(title))
    assert isinstance(result, ParsedPage), (title, result)
    return result


def item(title):
    result = normalize(parsed(title))
    validate_item(result)
    return result


def warnings_of(found):
    return [(w["code"], w["field"]) for w in found["parse_warnings"]]


@pytest.fixture(scope="module")
def real_context():
    zones = {zone["id"]: zone for zone in json.loads((CLIENT / "zones.json").read_text(encoding="utf-8"))["zones"]}
    quests = QuestTable.from_data(json.loads((REPO / "derived" / "quests.json").read_text(encoding="utf-8")))
    return Context(
        flagged={i for i, zone in zones.items() if zone["flagged"]},
        aliases=load_aliases(RULES / "zone-aliases.json", zone_ids=set(zones)),
        hand=load_hand_lists(RULES / "hand-lists.json"),
        quests=quests,
    )


def promoted(title, context):
    """The item as the catalog build makes it: zones written as bullets are zones."""
    found = item(title)
    found["sources"]["drops"] = promote_bullet_zones(found["sources"]["drops"], lambda name: is_known_zone(name, context))
    return found


def verdict(found, context):
    result = classify(found, context)
    return result["level"], [reason["code"] for reason in result["reasons"]]


def test_every_new_fixture_parses_normalizes_and_validates():
    for title in NEW_FIXTURES:
        assert item(title)["name"] == title


# ---- 1: a quest page under the name of one of its tests ---------------------------------------------------------------------


def test_griffin_hide_armguards_find_their_quest_by_the_page_that_the_link_names(real_context):
    found = item("Griffin-Hide Armguards")  # [[Beastlord Plane of Sky Tests|Beastlord Test of Harpy]]
    assert found["sources"]["quests"] == ["Beastlord Plane of Sky Tests"]
    assert found["sources"]["quest_labels"] == [{"title": "Beastlord Plane of Sky Tests", "label": "Beastlord Test of Harpy"}]
    assert verdict(found, real_context) == ("wiki", ["live-source:quest"])


def test_quest_links_without_a_label_keep_their_names_and_have_no_label_entry():
    found = item("Chilled Tundra Root")  # [[Druid Epic Quest]] and [[Ranger Epic Quest]]
    assert found["sources"]["quests"] == ["Druid Epic Quest", "Ranger Epic Quest"] and "quest_labels" not in found["sources"]


# ---- 3: zones written as bullets --------------------------------------------------------------------------------------------


def test_wind_rune_meda_drops_in_the_plane_of_sky_which_the_page_writes_as_a_bullet(real_context):
    found = item("Wind Rune Meda")
    assert found["sources"]["drops"] == [{"zone": None, "npcs": ["Plane of Sky"]}]  # before the build promotes it
    found = promoted("Wind Rune Meda", real_context)
    assert found["sources"]["drops"] == [{"zone": "Plane of Sky", "npcs": []}]
    assert verdict(found, real_context) == ("wiki", ["live-source:Plane of Sky"])


def test_a_zone_with_a_creature_under_it_written_as_two_levels_of_bullets(real_context):
    found = promoted("Large Empty Crate", real_context)  # * Warrens, ** [[Smithy Rrarrgin]]
    assert found["sources"]["drops"] == [{"zone": "Warrens", "npcs": ["Smithy Rrarrgin"]}]
    assert "live-source:Warrens" in verdict(found, real_context)[1]


def test_two_zone_bullets_and_a_creature_under_the_second(real_context):
    found = promoted("Velium Spear", real_context)  # * Dragon Necropolis, * Great Divide, ** a frost giant berserker
    assert found["sources"]["drops"] == [
        {"zone": "Dragon Necropolis", "npcs": []},
        {"zone": "Great Divide", "npcs": ["a frost giant berserker"]},
    ]
    level, codes = verdict(found, real_context)
    assert level == "hidden" and "zones-not-in-eql" in codes  # both Velious zones are real, and the client does not flag them


# ---- 5: map positions and prose -----------------------------------------------------------------------------------------------


def test_crushed_diamonds_drop_in_one_zone_whose_ground_spawn_is_a_creature_and_whose_position_is_dropped(real_context):
    found = promoted("Crushed Diamonds", real_context)  # * [[Timorous Deep]], ** Ground Spawn, *** {{Loc|...}}
    assert found["sources"]["drops"] == [{"zone": "Timorous Deep", "npcs": ["Ground Spawn"]}]
    assert "(" not in json.dumps(found["sources"]["drops"])


def test_morning_dew_has_seven_creatures_and_neither_prose_nor_map_positions_among_its_zones(real_context):
    found = item("Morning Dew")
    (drop,) = found["sources"]["drops"]
    assert drop["zone"] is None and len(drop["npcs"]) == 7 and drop["npcs"][0] == "A Faerie"
    assert found["sources"]["foraged"] == [{"zone": "Lesser Faydark"}, {"zone": "Greater Faydark"}]


# ---- 4: foraged zones ----------------------------------------------------------------------------------------------------------


def test_chilled_tundra_root_is_foraged_in_everfrost_peaks_a_live_zone(real_context):
    found = item("Chilled Tundra Root")
    assert found["sources"]["foraged"] == [{"zone": "Everfrost Peaks"}] and found["tier_rule"] == "fixed0"
    assert verdict(found, real_context) == ("wiki", ["live-source:foraged"])


def test_fishing_grubs_are_foraged_in_eight_zones_the_first_written_with_a_label(real_context):
    found = item("Fishing Grubs")  # [[Freeport|East Freeport]] ... [[West Commonlands]]
    zones = [entry["zone"] for entry in found["sources"]["foraged"]]
    assert len(zones) == 8 and zones[0] == "East Freeport" and zones[-1] == "West Commonlands"
    assert verdict(found, real_context) == ("wiki", ["live-source:foraged"])


def test_morning_dew_is_foraged_in_two_live_zones(real_context):
    assert verdict(item("Morning Dew"), real_context) == ("wiki", ["live-source:foraged"])


# ---- 6: values that were dropped -------------------------------------------------------------------------------------------------


def test_chipped_jade_has_a_period_where_the_colon_should_be():
    found = item("Chipped Jade")  # HP. +3 MANA +3
    assert found["stats"] == {"AC": 1, "HP": 3, "MANA": 3} and found["parse_warnings"] == []
    assert found["flags"] == ["magic"] and found["size"] == "TINY"


def test_crude_coal_has_a_rec_level_and_a_vendor():
    found = item("Crude Coal")  # Rec Level: 4
    assert found["recommended_level"] == 4 and found["required_level"] is None and found["parse_warnings"] == []
    assert found["sources"]["sold_by"] == [{"zone": "West Commonlands", "npc": "Parus the Strong"}]


def test_keg_mallet_has_a_base_dmg():
    found = item("Keg Mallet")  # Skill: 1H Blunt, Base Dmg: 9, Atk Delay: 30
    assert found["weapon"] == {"skill": "1H Blunt", "dmg": 9, "delay": 30, "bonus": None}
    assert found["stats"] == {"STA": 3, "WIS": 3} and found["parse_warnings"] == []


# ---- 10: charges ----------------------------------------------------------------------------------------------------------------------


def test_essence_of_earth_has_its_two_charges_on_the_line_after_the_effect():
    found = item("Essence of Earth")
    assert found["charges"] == 2 and found["parse_warnings"] == []
    (effect,) = found["effects"]
    assert effect["name"] == "Illusion: Earth Elemental" and effect["kind"] == "click" and "charges" not in effect


# ---- 11: categories -------------------------------------------------------------------------------------------------------------------


def test_fine_steel_naginata_keeps_the_four_categories_that_stand_inside_its_template():
    found = item("Fine Steel Naginata")
    assert found["categories"] == ["Warrior Equipment", "Shadow Knight Equipment", "Paladin Equipment", "2H Slashing"]
    assert found["era_tags"] == ["Classic Era"] and found["sources"]["drops"] == [{"zone": "Stonebrunt Mountains", "npcs": ["Jelquar the Soulslayer"]}]


# ---- 12: Required Level on the effect or on the item ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "level"),
    [
        ("Baton of the Sky", 49),  # Effect, Casting Time, Required Level, Cooldown: four lines
        ("Shroud of the Sky", 46),  # Click Effect, Cast Time, Required Level, Cooldown
        ("Spiroc Beak Earcuff", 46),  # Required Level inside the Click Effect line itself
        ("Azarack Skin Wristwraps", 46),  # Required Level inside the Click Effect line, with a cooldown after it
    ],
)
def test_the_required_level_of_the_four_sky_items_is_the_effects_and_the_item_has_none(title, level):
    found = item(title)
    (effect,) = found["effects"]
    assert effect["required_level"] == level and found["required_level"] is None
    assert found["parse_warnings"] == []
