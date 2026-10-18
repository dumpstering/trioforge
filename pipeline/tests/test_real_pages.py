"""Real item pages for the parser fixes: the layouts the first parser read badly.

The pages are in fixtures/wiki (see its README): real eqlwiki text taken from the cached pull of 2026-10-14,
with no new request. Each test names the page, says what is odd about it and pins what the parser, the
normalizer and the evidence ladder make of it. The synthetic versions of the same cases are in
test_itempage.py, test_normalize.py and test_evidence.py.
"""

import json
from pathlib import Path

import pytest

from trioforge.data.evidence import Context, classify, load_aliases, load_hand_lists
from trioforge.data.normalize import FLAGS, normalize, validate_item
from trioforge.sources.eqlwiki import fixture_slug, page_records
from trioforge.sources.itempage import ParsedPage, parse_page

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures" / "wiki"
RULES = REPO / "rules"
CLIENT = REPO / "derived" / "client"

PARSER_FIXTURES = [
    "Azzar's Dreadful Hat",
    "Imbued Northman Long Dagger",
    "Kejekan Smithy Hammer",
    "Imbued Black Pearl Electrum Choker",
    "Blessed Champion Arrows",
    "Batling Eye",
    "10 Dose Adrenaline Tap",
    "A Crude Stein",
    "Serpent's Tooth",
    "Teir`Dal Adamantite Vambraces",
    "Velvet-Trimmed Satin Robe",
    "Tri-Plated Golden Hackle Hammer",
    "Azarack Skin Wristwraps",
    "Feir`Dal Fletching Kit",
    "Spell: Aegolism",
    "Aerated Pauldrons",
    "Basoon Haste Gauntlets",
    "Bronze Ulak",
    "Blackened Iron Armplates",
    "Robe of Discord",
    "Unadorned Breastplate",
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


def test_every_parser_fixture_parses_normalizes_and_validates():
    for title in PARSER_FIXTURES:
        found = item(title)
        assert found["name"] == title


# ---- H2: deities -------------------------------------------------------------------------------------------


def test_azzars_dreadful_hat_has_a_hyphenated_deity():
    found = item("Azzar's Dreadful Hat")  # Deity: Cazic-Thule
    assert found["deity"] == ["Cazic Thule"] and found["parse_warnings"] == []
    assert found["flags"] == ["lore", "no_trade", "quest"] and found["slots"] == ["HEAD"]


def test_the_northman_long_dagger_is_for_the_tribunal_or_rallos_zek():
    found = item("Imbued Northman Long Dagger")  # Deity: [[The Tribunal]] / [[Rallos Zek]]
    assert found["deity"] == ["The Tribunal", "Rallos Zek"] and found["parse_warnings"] == []


def test_the_smithy_hammer_lists_four_gods_and_the_flag_spelled_without_a_space():
    found = item("Kejekan Smithy Hammer")  # LORE ITEM  NODROP, Deity: Bertoxxulous Cazic-Thule Innoruuk Rallos Zek
    assert found["deity"] == ["Bertoxxulous", "Cazic Thule", "Innoruuk", "Rallos Zek"]
    assert found["flags"] == ["lore", "no_drop"] and found["parse_warnings"] == []


def test_the_black_pearl_choker_names_its_god_with_no_colon():
    found = item("Imbued Black Pearl Electrum Choker")  # Deity Prexus
    assert found["deity"] == ["Prexus"] and found["parse_warnings"] == []


def test_the_champion_arrows_name_their_god_on_a_line_of_its_own():
    found = item("Blessed Champion Arrows")  # a line that says only Tunare
    assert found["deity"] == ["Tunare"]


# ---- M3, L6: charges -----------------------------------------------------------------------------------------


def test_the_batling_eye_records_its_charge_and_raises_no_flag_warning():
    found = item("Batling Eye")  # EXPENDABLE  Charges: 1, then INT: +2, then the effect
    assert found["flags"] == ["magic", "expendable"] and found["charges"] == 1
    assert found["parse_warnings"] == []
    (effect,) = found["effects"]
    assert effect["name"] == "Eye of Zomm" and effect["kind"] == "click" and "charges" not in effect


def test_the_adrenaline_tap_keeps_its_charges_as_the_items_not_the_effects():
    found = item("10 Dose Adrenaline Tap")  # EXPENDABLE  Charges: 10, then the effect
    (effect,) = found["effects"]
    assert "charges" not in effect and found["charges"] == 10 and found["parse_warnings"] == []  # the effect's own line only


def test_a_charges_line_before_the_stats_is_the_items_charges():
    found = item("A Crude Stein")  # Charges: 1, then STA CHA, then the effect
    assert found["charges"] == 1 and "charges" not in found["effects"][0]
    assert found["stats"] == {"STA": 10, "CHA": 15}


def test_a_spell_scroll_is_not_a_weapon_and_keeps_its_charge():
    found = item("Spell: Aegolism")  # Skill: Abjuration
    assert found["weapon"] is None and found["charges"] == 1 and found["slots"] == []
    assert found["effects"][0]["name"] == "Aegolism"


# ---- M4: keys -------------------------------------------------------------------------------------------------


def test_serpents_tooth_has_a_backstab():
    found = item("Serpent's Tooth")  # DMG: 13  BACKSTAB: 13
    assert found["weapon"] == {"skill": "1H Piercing", "dmg": 13, "delay": 27, "bonus": None, "backstab": 13}
    assert found["parse_warnings"] == [] and found["flags"] == ["lore", "attunable", "placeable"]


def test_the_adamantite_vambraces_have_a_wisdom_with_no_colon():
    found = item("Teir`Dal Adamantite Vambraces")  # STR: +4 DEX: +5 WIS +4 INT: +4
    assert found["stats"] == {"AC": 12, "STR": 4, "DEX": 5, "WIS": 4, "INT": 4} and found["parse_warnings"] == []


def test_the_satin_robe_has_a_fire_resist_with_no_colon():
    found = item("Velvet-Trimmed Satin Robe")  # SV FIRE +5
    assert found["sv"] == {"FIRE": 5} and found["stats"] == {"AC": 10, "INT": 4, "MANA": 15}
    assert found["parse_warnings"] == []


def test_the_champion_arrows_have_a_fire_damage_and_a_delay_of_zero_that_is_out_of_range():
    found = item("Blessed Champion Arrows")  # DMG: 11 Fire DMG: 4, Atk Delay: 0
    assert found["weapon"] == {"skill": "Archery", "dmg": 11, "delay": None, "bonus": None, "elemental": {"type": "Fire", "value": 4}}
    assert warnings_of(found) == [("out-of-range", "delay")] and found["slots"] == ["AMMO"]


# ---- M5: lines that wrap ----------------------------------------------------------------------------------------


def test_the_golden_hackle_hammer_has_its_class_list_on_two_lines():
    found = item("Tri-Plated Golden Hackle Hammer")
    assert found["classes"] == "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC".split()
    assert found["parse_warnings"] == [] and found["slots"] == ["PRIMARY", "SECONDARY"]
    assert found["effects"][0]["name"] == "Arch Shielding"


def test_the_wristwraps_have_a_slot_line_with_no_label_and_a_one_line_click_effect():
    found = item("Azarack Skin Wristwraps")  # a line that says only Wrist
    assert found["slots"] == ["WRIST"] and found["classes"] == ["BST"] and found["parse_warnings"] == []
    (effect,) = found["effects"]
    assert (effect["kind"], effect["name"], effect["required_level"]) == ("click", "Whirl Bolt", 46)
    assert found["required_level"] is None  # the 46 is the effect's


# ---- VAH, L8 -----------------------------------------------------------------------------------------------------


def test_the_fletching_kit_is_for_the_vah_shir_who_the_catalog_calls_kerran():
    found = item("Feir`Dal Fletching Kit")  # Race: ELF DEF VAH
    assert found["races"] == ["ELF", "DEF", "KER"] and found["parse_warnings"] == []
    assert found["container_capacity"] == 10
    assert found["sources"]["crafted"] == [
        {"container": "Feir`Dal Forge", "ingredients": ["Water Flask", "Small Brick of Mithril", "Hinge Mold", "Container Base Mold", "Container Lid Mold"]}
    ]


# ---- banners and drop notes (L5) ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "flags"),
    [
        ("Aerated Pauldrons", ["wiki_banner_delete"]),  # {{Delete}}
        ("Basoon Haste Gauntlets", ["removed_note", "wiki_banner_delete"]),  # {{delete}} and ITEM REMOVED FROM GAME
        ("Bronze Ulak", ["wiki_banner_does_not_exist"]),  # {{:Does Not Exist}}
        ("Blackened Iron Armplates", ["wiki_banner_revamped"]),  # {{revamped}}
        ("Engineer's Ring", []),
    ],
)
def test_banner_templates_and_the_removed_note_become_flags(title, flags):
    path = FIXTURES / f"{fixture_slug(title)}.json"
    (found,) = page_records(json.loads(path.read_text(encoding="utf-8")))
    result = normalize(parse_page(found))
    validate_item(result)
    assert [flag for flag in result["flags"] if flag in ("removed_note",) or flag.startswith("wiki_banner_")] == [
        flag for flag in FLAGS if flag in flags
    ]


def test_a_removed_item_has_no_zone_and_a_not_classic_note_is_not_a_zone():
    assert item("Basoon Haste Gauntlets")["sources"]["drops"] == []  # ITEM REMOVED FROM GAME
    assert item("Bronze Ulak")["sources"]["drops"] == []  # N O T _ C L A S S I C


def test_the_header_of_a_list_of_cities_is_not_a_zone():
    zones = [drop["zone"] for drop in item("Robe of Discord")["sources"]["drops"]]
    assert zones[:3] == [None, "Cabilis", "Erudin"] and "Located in the following locations:" not in zones
    assert len(zones) == 14


def test_a_parenthesis_under_a_zone_is_a_note_on_that_zone():
    (drop,) = item("Unadorned Breastplate")["sources"]["drops"]
    assert drop["zone"] == "Temple of Veeshan" and drop["notes"] == ["ToV East mobs"]
    assert len(drop["npcs"]) == 13 and all(not npc.startswith("(") for npc in drop["npcs"])


# ---- M7: era names ----------------------------------------------------------------------------------------------


# ---- the evidence ladder on these pages (real hand lists, aliases and client zones) ----------------------------


@pytest.fixture(scope="module")
def real_context():
    zones = {zone["id"]: zone for zone in json.loads((CLIENT / "zones.json").read_text(encoding="utf-8"))["zones"]}
    return Context(
        flagged={i for i, zone in zones.items() if zone["flagged"]},
        aliases=load_aliases(RULES / "zone-aliases.json", zone_ids=set(zones)),
        hand=load_hand_lists(RULES / "hand-lists.json"),
    )


def verdict(title, context):
    result = classify(item(title), context)
    return result["level"], [reason["code"] for reason in result["reasons"]]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Aerated Pauldrons", ("hidden", ["wiki-marked-not-in-eql"])),
        ("Bronze Ulak", ("hidden", ["wiki-marked-not-in-eql"])),
        ("Basoon Haste Gauntlets", ("hidden", ["wiki-marked-not-in-eql", "wiki-marked-removed"])),
        ("Blackened Iron Armplates", ("wiki", ["live-source:Clan Runnyeye", "wiki-marked-revamped"])),  # {{revamped}} is only a note
    ],
)
def test_the_wiki_banners_hide_an_item_and_revamped_only_adds_a_note(real_context, title, expected):
    assert verdict(title, real_context) == expected


def test_the_vah_shir_fletching_kit_made_only_in_a_cultural_forge_is_hidden(real_context):
    assert verdict("Feir`Dal Fletching Kit", real_context) == ("hidden", ["cultural-container"])
