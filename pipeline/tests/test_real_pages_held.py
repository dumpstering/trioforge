"""Real item pages for the parser fixes, second half: the four pages that the privacy hook holds back for now.

Same idea as test_real_pages.py (see there). These pages are in fixtures/wiki too, but they hold words the
private denylist also lists (an NPC name, a site name, an era template's name), so they are committed
separately. The helpers are copies of those in test_real_pages.py.
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

HELD_FIXTURES = ["Kerasian Axe of Ire", "Yelinak's Talisman", "A Bowyers Guide", "Crushbone Battle Beads"]


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
    return Context(
        flagged={i for i, zone in zones.items() if zone["flagged"]},
        aliases=load_aliases(RULES / "zone-aliases.json", zone_ids=set(zones)),
        hand=load_hand_lists(RULES / "hand-lists.json"),
    )


def verdict(title, context):
    result = classify(item(title), context)
    return result["level"], [reason["code"] for reason in result["reasons"]]


def test_every_held_fixture_parses_normalizes_and_validates():
    for title in HELD_FIXTURES:
        assert item(title)["name"] == title


def test_crushbone_battle_beads_carry_two_banners():
    found = item("Crushbone Battle Beads")  # {{delete}}{{DNE}}
    assert [flag for flag in found["flags"] if flag.startswith("wiki_banner_")] == ["wiki_banner_delete", "wiki_banner_dne"]
    assert [flag for flag in FLAGS if flag in found["flags"] and flag.startswith("wiki_banner_")] == ["wiki_banner_delete", "wiki_banner_dne"]


def test_crushbone_battle_beads_drop_in_a_live_zone_and_the_banner_wins(real_context):
    assert item("Crushbone Battle Beads")["sources"]["drops"][0]["zone"] == "Crushbone"
    assert verdict("Crushbone Battle Beads", real_context) == ("hidden", ["wiki-marked-not-in-eql"])


def test_kerasian_axe_of_ire_is_read_whole_endur_attack_and_the_damage_line_with_ac_in_it():
    found = item("Kerasian Axe of Ire")
    assert found["stats"] == {"AC": 5, "STR": 15, "STA": 20, "DEX": 15, "HP": 125, "END": 100, "ATK": 40, "HASTE": 40}
    assert found["sv"] == {"FIRE": 8, "COLD": 15, "MAGIC": 7, "POISON": 10, "DISEASE": 10}
    assert found["weapon"] == {"skill": "2H Slashing", "dmg": 46, "delay": 37, "bonus": None}
    assert found["required_level"] == 46 and found["classes"] == ["BER"]
    assert found["effects"] == [{"kind": "worn", "name": "Rage of Keras", "raw": "Effect: Kerasian Axe of Ire (Worn) at Level 46"}]
    assert found["parse_warnings"] == []


def test_yelinaks_talisman_has_a_haste_written_as_a_link():
    found = item("Yelinak's Talisman")  # [[Haste]]: +41%
    assert found["stats"]["HASTE"] == 41 and found["parse_warnings"] == []
    assert found["sv"] == {"FIRE": 7, "COLD": 7, "MAGIC": 7, "POISON": 7, "DISEASE": 7}


def test_a_book_for_no_class_and_no_race_has_empty_lists_and_one_warning_each():
    found = item("A Bowyers Guide")  # Class: NONE, Race: NONE
    assert found["classes"] == [] and found["races"] == []
    assert warnings_of(found) == [("no-classes", "class"), ("no-classes", "race")]


def test_an_era_template_keeps_the_spelling_the_page_uses():
    assert item("Kerasian Axe of Ire")["era_tags"] == ["EpicQuests Era"]
    assert item("Engineer's Ring")["era_tags"] == ["Classic Era"]


def test_an_item_for_no_class_is_not_for_bis(real_context):
    level, codes = verdict("A Bowyers Guide", real_context)
    assert "not-for-bis" in codes
    assert "not-for-bis" not in verdict("Batling Eye", real_context)[1]


def test_the_epic_axe_with_an_out_of_era_tag_and_no_live_source_is_hidden_as_out_of_era(real_context):
    assert verdict("Kerasian Axe of Ire", real_context) == ("hidden", ["out-of-era"])


@pytest.mark.parametrize("tag", ["EpicQuests Era", "FearHateRevamp Era", "Epics Era", "Chardok Revamp Era"])
def test_the_era_names_as_the_wiki_spells_them_are_out_of_era_with_the_real_hand_list(real_context, tag):
    live = {"key": "w1", "name": "Zorblax Ring", "sources": {"drops": [{"zone": "Plane of Hate", "npcs": []}]}, "era_tags": [tag]}
    result = classify(live, real_context)
    assert result["level"] == "disputed" and "out-of-era-tag-live-zone" in [reason["code"] for reason in result["reasons"]]
    nowhere = classify({"key": "w2", "name": "Zorblax Ring", "era_tags": [tag]}, real_context)
    assert (nowhere["level"], [reason["code"] for reason in nowhere["reasons"]]) == ("hidden", ["out-of-era"])
