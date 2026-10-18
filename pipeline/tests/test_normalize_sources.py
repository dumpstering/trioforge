"""Tests for the normalizer's side of the second parser review (2026-10-14).

Quest targets and labels, foraged zones, zones written as bullets, URLs in stored text, the keys the first
reader missed (``HP.``, ``Base Dmg``, ``Rec Level``) and charges that do not depend on where their line stands.
Pages are built here from invented names (Zorblax and friends); the real pages are in test_real_pages_sources.py.
"""

import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from trioforge.data.normalize import normalize, promote_bullet_zones, sanitize_text, validate_item
from trioforge.sources.itempage import ParsedPage, parse_page


def parsed_page(statsblock, **params):
    params = {"itemname": "Zorblax Ring", **params}
    body = "".join(f"|{name}={value}\n" for name, value in {"statsblock": statsblock, **params}.items())
    result = parse_page({"pageid": 7, "ns": 0, "title": "Zorblax Ring", "revid": 70, "content": "{{Itempage\n" + body + "}}"})
    assert isinstance(result, ParsedPage), result
    return result


def item_from(statsblock, **params):
    item = normalize(parsed_page(statsblock, **params))
    validate_item(item)
    return item


def lines(*statsblock_lines):
    return "<br>\n".join(statsblock_lines)


def warnings_of(item):
    return [(w["code"], w["field"]) for w in item["parse_warnings"]]


def all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, inner in value.items():
            yield from all_strings(key)
            yield from all_strings(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from all_strings(inner)


# ---- 1 and 4: the sources of an item ----------------------------------------------------------------------------------


def test_quest_targets_and_labels_reach_the_item():
    item = item_from("Slot: EAR", relatedquests="* [[Zorblax Tests|Test of Courage]]\n* [[Plain Quest]]")
    assert item["sources"]["quests"] == ["Zorblax Tests", "Plain Quest"]
    assert item["sources"]["quest_labels"] == [{"title": "Zorblax Tests", "label": "Test of Courage"}]


def test_an_item_with_no_labelled_quest_and_no_foraged_zone_has_neither_field():
    item = item_from("Slot: EAR", relatedquests="* [[Plain Quest]]")
    assert "quest_labels" not in item["sources"] and "foraged" not in item["sources"]
    assert set(item["sources"]) == {"drops", "sold_by", "quests", "crafted"}


def test_foraged_zones_reach_the_item_as_distinct_zone_entries_in_order():
    item = item_from("Slot: EAR", foraged="* [[Zorblax Hollow]]\n* [[Quuxen|Quuxen Hills]]\n* [[Zorblax Hollow]]")
    assert item["sources"]["foraged"] == [{"zone": "Zorblax Hollow"}, {"zone": "Quuxen Hills"}]
    assert item["sources"]["drops"] == []


def test_a_foraged_zone_that_sanitizes_to_nothing_is_dropped_with_a_warning():
    item = item_from("Slot: EAR", foraged="* [[Zorblax Hollow]]\n* [[​​]]")
    assert item["sources"]["foraged"] == [{"zone": "Zorblax Hollow"}] and ("empty-value", "zone") in warnings_of(item)


def test_an_item_that_is_only_foraged_is_fixed0_even_when_it_is_temporary():
    item = item_from("Temporary<br>Slot: EAR", foraged="* [[Zorblax Hollow]]")
    assert item["tier_rule"] == "fixed0"
    assert item_from("Temporary<br>Slot: EAR")["tier_rule"] == "spell"  # no source at all: a summoned item


def test_the_lists_of_the_new_fields_are_capped():
    zones = "".join(f"* [[Zorblax Zone {n}]]\n" for n in range(260))
    item = item_from("Slot: EAR", foraged=zones)
    assert len(item["sources"]["foraged"]) == 200 and ("list-truncated", "foraged") in warnings_of(item)


# ---- 3: zones written as bullets ---------------------------------------------------------------------------------------

KNOWN = {"plane of sky", "warrens", "dragon necropolis", "great divide", "timorous deep", "zorblax hollow"}


def known(name):
    return name.casefold() in KNOWN


def test_a_list_with_no_zone_line_takes_a_bullet_that_is_a_known_zone_for_a_zone():
    assert promote_bullet_zones([{"zone": None, "npcs": ["Plane of Sky"]}], known) == [{"zone": "Plane of Sky", "npcs": []}]


def test_the_bullets_under_such_a_zone_are_its_npcs():
    drops = [{"zone": None, "npcs": ["Warrens", "Smithy Rrarrgin"]}]
    assert promote_bullet_zones(drops, known) == [{"zone": "Warrens", "npcs": ["Smithy Rrarrgin"]}]
    drops = [{"zone": None, "npcs": ["Dragon Necropolis", "Great Divide", "a frost giant berserker", "another"]}]
    assert promote_bullet_zones(drops, known) == [
        {"zone": "Dragon Necropolis", "npcs": []},
        {"zone": "Great Divide", "npcs": ["a frost giant berserker", "another"]},
    ]


def test_a_creature_before_the_first_zone_bullet_stays_without_a_zone():
    drops = [{"zone": None, "npcs": ["a bat", "Zorblax Hollow", "a rat"]}]
    assert promote_bullet_zones(drops, known) == [
        {"zone": None, "npcs": ["a bat"]},
        {"zone": "Zorblax Hollow", "npcs": ["a rat"]},
    ]


def test_a_list_with_a_zone_line_is_left_alone_even_if_a_creature_has_a_zones_name():
    drops = [{"zone": "Zorblax Hollow", "npcs": ["Plane of Sky", "a rat"]}]
    assert promote_bullet_zones(drops, known) == drops
    mixed = [{"zone": None, "npcs": ["Plane of Sky"]}, {"zone": "Zorblax Hollow", "npcs": []}]
    assert promote_bullet_zones(mixed, known) == mixed  # a zone line exists: the earlier bullets stay creatures


def test_a_list_of_creatures_only_is_left_alone():
    drops = [{"zone": None, "npcs": ["a bat", "a rat"]}]
    assert promote_bullet_zones(drops, known) == drops
    assert promote_bullet_zones([], known) == []


def test_promoting_does_not_change_its_argument_and_keeps_the_notes():
    drops = [{"zone": None, "npcs": ["Plane of Sky", "a rat"], "notes": ["rare"]}]
    before = [{"zone": None, "npcs": ["Plane of Sky", "a rat"], "notes": ["rare"]}]
    assert promote_bullet_zones(drops, known) == [{"zone": "Plane of Sky", "npcs": ["a rat"], "notes": ["rare"]}]
    assert drops == before


def test_the_promoted_drops_stay_within_the_schema_limit_of_500():
    drops = [{"zone": None, "npcs": ["Zorblax Hollow"] * 700}]
    assert len(promote_bullet_zones(drops, known)) == 500


# ---- 9: a URL is never stored ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ring https://evil.example/x", "Ring"),
        ("https://evil.example", ""),
        ("Zorblax www.evil.example Ring", "Zorblax Ring"),
        ("a ftp://x.y b", "a b"),
        ("see HTTP://EVIL.EXAMPLE/path?q=1 now", "see now"),
        ("ht​tps://evil.example Ring", "Ring"),  # the invisible character is removed first
        ("ｈｔｔｐｓ：／／evil.example Ring", "Ring"),  # fullwidth, folded by NFKC
        ("javascript://evil.example%0Aalert(1) Ring", "Ring"),
        ("awww.example and wwww. and www", "awww.example and wwww. and www"),  # not a bare www. host
        ("Zorblax's \"Ring\" a=b & (c) [d] {e} 100% #1 http: / x", "Zorblax's \"Ring\" a=b & (c) [d] {e} 100% #1 http: / x"),
    ],
)
def test_a_url_is_removed_from_stored_text(text, expected):
    assert sanitize_text(text) == expected


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet="htps:/.wA b-​xF", max_size=60))
def test_stripping_urls_leaves_a_fixed_point_with_no_url_in_it(text):
    once = sanitize_text(text)
    assert sanitize_text(once) == once and "://" not in once


def test_a_nowiki_url_never_reaches_any_field_of_the_item():
    evil = "<nowiki>https://evil.example/x</nowiki>"
    item = item_from(
        lines("Slot: EAR", f"Skill: {evil}", f"Type: {evil}", f"Effect: [[Zorblax Blast]] (Worn) {evil}"),
        itemname=f"{evil} Zorblax Ring",
        dropsfrom=f"[[Zorblax Hollow]]\n* {evil}\n* [[a rat]]",
        soldby=f"[[Quuxen Hills]]\n* {evil}",
        relatedquests=f"* {evil}\n* [[Zorblax Tests|{evil} Trial]]",
        notes=evil,
    )
    for text in all_strings(item):
        assert "://" not in text and "www." not in text, text
    assert item["name"] == "Zorblax Ring"
    assert item["sources"]["drops"] == [{"zone": "Zorblax Hollow", "npcs": ["a rat"]}]


# ---- 6: values that were dropped ---------------------------------------------------------------------------------------


def test_a_stat_key_with_a_period_instead_of_a_colon_is_a_key():
    item = item_from("HP. +3 MANA +3")
    assert item["stats"] == {"HP": 3, "MANA": 3} and item["parse_warnings"] == []
    item = item_from(lines("STR. 5  STA. +6", "AC. 7", "hp. 2", "Haste. 30%"))
    assert item["stats"] == {"AC": 7, "STR": 5, "STA": 6, "HP": 2, "HASTE": 30} and item["parse_warnings"] == []


def test_a_stat_word_with_a_period_and_no_number_is_not_a_key():
    item = item_from("Note about HP. then more words")
    assert item["stats"] == {} and warnings_of(item) == [("unparsed-line", "statsblock")]
    assert item_from("VALUE TO VENDOR with CHA. later")["stats"] == {}


def test_base_dmg_is_the_damage_of_the_weapon():
    item = item_from(lines("Slot: PRIMARY", "Skill: 1H Blunt", "Base Dmg: 9", "Atk Delay: 30", "STA: +3"))
    assert item["weapon"] == {"skill": "1H Blunt", "dmg": 9, "delay": 30, "bonus": None}
    assert item["stats"] == {"STA": 3} and item["parse_warnings"] == []
    assert item_from("Base Damage: 7")["weapon"]["dmg"] == 7


def test_base_dmg_and_dmg_together_are_one_damage_and_a_duplicate():
    item = item_from(lines("Skill: 1H Blunt  Atk Delay: 30", "DMG: 9", "Base Dmg: 11"))
    assert item["weapon"]["dmg"] == 9 and warnings_of(item) == [("duplicate-key", "dmg")]


def test_rec_level_is_the_recommended_level():
    item = item_from(lines("Rec Level: 4", "Size: SMALL  WT: 0.5"))
    assert item["recommended_level"] == 4 and item["required_level"] is None and item["parse_warnings"] == []
    assert item_from("Rec Level: 45")["recommended_level"] == 45
    assert item_from("Recommended Level: 45")["recommended_level"] == 45


# ---- 10: charges do not depend on where their line stands ---------------------------------------------------------------

EFFECT = "Effect: [[Zorblax Blast]] (Must Equip, Casting Time: Instant)"


@pytest.mark.parametrize(
    "block",
    [
        lines("Charges: 2", EFFECT),
        lines(EFFECT, "Charges: 2"),
        lines("EXPENDABLE  Charges: 2", EFFECT),
        lines("Charges: 2", "AC: 5", EFFECT),
        lines(EFFECT, "Casting Time: Instant", "Charges: 2", "Cooldown: 60 seconds"),
        lines(EFFECT, "AC: 5", "Charges: 2"),
    ],
)
def test_a_charges_line_is_the_items_wherever_it_stands_and_never_the_effects(block):
    item = item_from(block)
    assert item["charges"] == 2
    assert all("charges" not in effect for effect in item["effects"])


def test_a_charges_line_between_the_lines_of_an_effect_does_not_end_the_effect():
    block = lines("Click Effect: [[Zorblax Blast]] (Must Equip)", "Casting Time: Instant", "Charges: 2", "Required Level: 49", "Cooldown: 600 seconds")
    item = item_from(block)
    (effect,) = item["effects"]
    assert item["charges"] == 2 and item["required_level"] is None and item["parse_warnings"] == []
    assert effect["required_level"] == 49 and "Cooldown: 600 seconds" in effect["raw"] and "Charges" not in effect["raw"]


def test_charges_written_in_the_line_of_the_effect_are_that_effects():
    for text, expected in (
        ("Effect: [[Zorblax Blast]] (Any Slot, Casting Time: 3.0) Charges: 5", 5),
        ("Effect: [[Zorblax Blast]] (Any Slot, Casting Time: 3.0) 12 charges", 12),
    ):
        item = item_from(text)
        assert item["effects"][0]["charges"] == expected and "charges" not in item
    item = item_from(lines("Charges: 3", "Effect: [[Alpha]] (Must Equip) Charges: 9"))
    assert item["effects"][0]["charges"] == 9 and item["charges"] == 3


def test_a_second_effect_never_gets_charges_from_a_line_next_to_it():
    item = item_from(lines("Effect: [[Alpha]] (Worn)", "Effect: [[Beta]] (Must Equip)", "Charges: 4"))
    assert item["charges"] == 4 and all("charges" not in effect for effect in item["effects"])


def test_a_word_that_only_contains_charge_is_not_charges():
    item = item_from("Effect: [[Zorblax Blast]] (Any Slot) recharge: 5")
    assert "charges" not in item["effects"][0]


def test_the_new_item_fields_are_clean_text():
    item = item_from("Slot: EAR", foraged="* [[Zorblax Hollow]]", relatedquests="* [[Zorblax Tests|Test of Courage]]")
    for text in all_strings(item):
        assert len(text) <= 200 and "<" not in text and ">" not in text
        assert all(unicodedata.category(char) not in {"Cc", "Cf", "Cs", "Co", "Zl", "Zp"} for char in text)


# ---- 12: Required Level on the effect or on the item ---------------------------------------------------------------------


def test_a_required_level_in_the_block_of_an_effect_is_the_effects_and_a_standalone_one_is_the_items():
    # on the Effect line, or in the lines right after it (casting time, a charges line, cooldown): the effect's
    item = item_from("Click Effect: [[Zorblax Blast]] (Must Equip) Required Level: 46")
    assert item["effects"][0]["required_level"] == 46 and item["required_level"] is None
    item = item_from(lines("Click Effect: [[Zorblax Blast]] (Must Equip)", "Cast Time: Instant", "Required Level: 46", "Cooldown: 120 seconds"))
    assert item["effects"][0]["required_level"] == 46 and item["required_level"] is None and item["parse_warnings"] == []
    # a line of its own, before the effect or after a line that is not part of the effect's block: the item's
    for block in (
        lines("AC: 5", "Required Level: 46"),
        lines("Required Level: 46", "Click Effect: [[Zorblax Blast]] (Must Equip)"),
        lines("Click Effect: [[Zorblax Blast]] (Must Equip)", "WT: 1.0  Size: SMALL", "Required Level: 46"),
    ):
        item = item_from(block)
        assert item["required_level"] == 46 and all("required_level" not in effect for effect in item["effects"]), block
