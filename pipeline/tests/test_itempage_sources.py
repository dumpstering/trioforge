"""Tests for the source lists of the item page parser, from the second parser review (2026-10-14).

Quest links keep their target (and the label for display); the ``foraged`` parameter is a source; ``{{Loc}}``
templates and prose are not zones; categories are read wherever they stand; the guard against pathological markup
does not count what is not a problem. Pages are the recorded fixtures (real eqlwiki text, see
fixtures/wiki/README.md) or are built here from invented names (Zorblax and friends).
"""

import json
import time
from pathlib import Path

import pytest

from trioforge.sources.eqlwiki import fixture_slug, page_records
from trioforge.sources.itempage import ParsedPage, Skip, parse_page, unmatched_openers

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "wiki"


def fixture(title):
    path = FIXTURES / f"{fixture_slug(title)}.json"
    (record,) = page_records(json.loads(path.read_text(encoding="utf-8")))
    return record


def real(title):
    result = parse_page(fixture(title))
    assert isinstance(result, ParsedPage), (title, result)
    return result


def page(content):
    return {"pageid": 7, "ns": 0, "title": "Zorblax Ring", "revid": 70, "timestamp": "2026-10-01T00:00:00Z", "content": content}


def template(**params):
    return "{{Itempage\n" + "".join(f"|{name}={value}\n" for name, value in params.items()) + "}}"


def parsed(statsblock="Slot: EAR", **params):
    result = parse_page(page(template(itemname="Zorblax Ring", statsblock=statsblock, **params)))
    assert isinstance(result, ParsedPage), result
    return result


# ---- 1: quest links keep the target, the label is for display -----------------------------------------------------


def test_a_quest_link_with_a_label_stores_the_target_and_keeps_the_label():
    result = parsed(relatedquests="* [[Zorblax Tests|Test of Courage]]\n* [[Plain Quest]]")
    assert result.quests == ["Zorblax Tests", "Plain Quest"]
    assert result.quest_labels == [{"title": "Zorblax Tests", "label": "Test of Courage"}]


def test_the_quest_target_keeps_its_parenthesis_and_loses_its_fragment_and_underscores():
    result = parsed(relatedquests="* [[Quuxen_Warbeads (Kaladim Rogue)#Part 2|Warbeads, part two]]\n* [[Blarg Quest#Reward]]")
    assert result.quests == ["Quuxen Warbeads (Kaladim Rogue)", "Blarg Quest"]
    assert result.quest_labels == [{"title": "Quuxen Warbeads (Kaladim Rogue)", "label": "Warbeads, part two"}]


def test_one_target_with_two_labels_is_listed_once_and_keeps_both_labels():
    result = parsed(relatedquests="* [[Zorblax Ring Quests|Zorblax Ring #7]]\n* [[Zorblax Ring Quests|Zorblax Ring #8]]")
    assert result.quests == ["Zorblax Ring Quests"]
    assert result.quest_labels == [
        {"title": "Zorblax Ring Quests", "label": "Zorblax Ring #7"},
        {"title": "Zorblax Ring Quests", "label": "Zorblax Ring #8"},
    ]


def test_a_label_that_only_repeats_the_target_is_not_kept():
    result = parsed(relatedquests="* [[Zorblax Quest|Zorblax Quest]]\n* [[Quuxen Quest| ]]")
    assert result.quests == ["Zorblax Quest", "Quuxen Quest"] and result.quest_labels == []


def test_a_quest_label_is_decoded_once_and_has_no_markup():
    result = parsed(relatedquests="* [[Zorblax Tests|Trial &amp; ''Error'']]")
    assert result.quest_labels == [{"title": "Zorblax Tests", "label": "Trial & Error"}]


def test_a_quest_written_as_plain_text_or_as_a_link_to_a_section_of_this_page_is_still_a_name():
    result = parsed(relatedquests="* A plain quest\n* [[#Part|The Part]]\n* [[File:Quest.png]]")
    assert result.quests == ["A plain quest", "The Part"] and result.quest_labels == []


def test_the_related_quests_section_is_read_the_same_way():
    page_text = template(itemname="Zorblax Ring", statsblock="Slot: EAR") + "\n== Related quests ==\n* [[Zorblax Tests|Test of Courage]]\n"
    result = parse_page(page(page_text))
    assert result.quests == ["Zorblax Tests"] and result.quest_labels == [{"title": "Zorblax Tests", "label": "Test of Courage"}]


def test_griffin_hide_armguards_link_a_quest_page_under_the_name_of_one_test():
    result = real("Griffin-Hide Armguards")  # [[Beastlord Plane of Sky Tests|Beastlord Test of Harpy]]
    assert result.quests == ["Beastlord Plane of Sky Tests"]
    assert result.quest_labels == [{"title": "Beastlord Plane of Sky Tests", "label": "Beastlord Test of Harpy"}]


def test_wind_rune_meda_links_the_sections_of_one_page():
    result = real("Wind Rune Meda")  # [[Plane of Sky#Bard Tests|Bard Test of Tone]] and five more
    assert result.quests == ["Plane of Sky"]
    assert [entry["label"] for entry in result.quest_labels][:2] == ["Bard Test of Tone", "Cleric Test of Skill"]
    assert len(result.quest_labels) == 6 and {entry["title"] for entry in result.quest_labels} == {"Plane of Sky"}


# ---- 5: {{Loc}} is a place on a map, not a name -------------------------------------------------------------------


def test_a_loc_template_is_dropped_wherever_it_stands_in_a_source_list():
    result = parsed(
        dropsfrom="[[Zorblax Hollow]]\n* [[a rat]]\n** {{Loc|Zorblax Hollow|(10, 20)|(10, 20)}}\n",
        soldby="[[Quuxen Hills]]\n* [[A Vendor]] {{Loc|Quuxen Hills|(1, 2)}}\n",
        relatedquests="* [[Zorblax Quest]]\n* {{Loc|Eastern Wastes|-7000, 1200}}\n",
    )
    assert result.drops == [{"zone": "Zorblax Hollow", "npcs": ["a rat"]}]
    assert result.sold_by == [{"zone": "Quuxen Hills", "npc": "A Vendor"}]
    assert result.quests == ["Zorblax Quest"]


def test_a_loc_template_is_dropped_whatever_its_case_and_even_inside_a_tag():
    result = parsed(dropsfrom="[[Zorblax Hollow]]\n* <span>{{LOC|Zorblax Hollow|(1, 2)}}</span>\n* [[a rat]]")
    assert result.drops == [{"zone": "Zorblax Hollow", "npcs": ["a rat"]}]


def test_crushed_diamonds_has_no_map_position_among_its_names():
    (drop,) = real("Crushed Diamonds").drops  # * [[Timorous Deep]], ** Ground Spawn, *** {{Loc|...}}
    assert drop == {"zone": None, "npcs": ["Timorous Deep", "Ground Spawn"]}


# ---- 5: prose is not a zone ----------------------------------------------------------------------------------------


def test_a_line_of_prose_in_a_drop_list_names_no_zone():
    dropsfrom = (
        "[[Zorblax Hollow]]\n* [[a rat]]\n\n"
        'This item can also be found as a "ground spawn" in Quuxen Hills. They look like small green leaves.\n'
        "One loc is {{Loc|Quuxen Hills|(792,2457)}}; {{Loc|Quuxen Hills|(1460,2789)}}\n"
    )
    assert parsed(dropsfrom=dropsfrom).drops == [{"zone": "Zorblax Hollow", "npcs": ["a rat"]}]


@pytest.mark.parametrize(
    "line",
    [
        "Only drops off the Lower Zorblax variants of these mobs, not Upper Zorblax.",
        "P 630.9438, -522.1356, -42.1978, 0, 240, 0, 2, Evergreen_Leaf",
        "Other 50+ zones",
        "Various Level 40 - 50 Mobs",
        "EQL Note - Dropped from an ogre shaman (9/9/26)",
        "-Staff dropped off Mistress of Scorn on 12th November 2024, 8AM EST",
        "Feels Like random drop from any Kobold.",
        "</pre>",
        "See below the map for code you can put into a <code>zorblax_3.txt</code> file in your maps directory",
        "one two three four five six seven eight nine ten",
    ],
)
def test_prose_codes_and_numbers_are_not_zones(line):
    assert parsed(dropsfrom=f"{line}\n* [[a rat]]").drops == [{"zone": None, "npcs": ["a rat"]}]
    assert parsed(soldby=f"{line}\n* [[A Vendor]]").sold_by == [{"zone": None, "npc": "A Vendor"}]


def test_a_plain_zone_name_and_a_comma_list_of_plain_zone_names_are_still_zones():
    assert [d["zone"] for d in parsed(dropsfrom="Zorblax Hollow").drops] == ["Zorblax Hollow"]
    assert [d["zone"] for d in parsed(dropsfrom="Zorblax Hollow, Quuxen Hills, The Blarg Pass").drops] == [
        "Zorblax Hollow",
        "Quuxen Hills",
        "The Blarg Pass",
    ]


def test_a_comma_list_is_split_only_when_every_part_is_a_name():
    assert parsed(dropsfrom="Zorblax Hollow, and then it is rare, near Quuxen Hills.").drops == []
    assert parsed(dropsfrom="Zorblax Hollow, 12 of them").drops == []


def test_links_win_over_the_prose_that_stands_next_to_them():
    dropsfrom = "[[Misty Thicket]] As of some previous patch, groundspawns are now random... the locs below are not reliable :/"
    assert [d["zone"] for d in parsed(dropsfrom=dropsfrom).drops] == ["Misty Thicket"]
    assert [d["zone"] for d in parsed(dropsfrom="[[Zorblax Hollow]], [[Quuxen Hills]]").drops] == ["Zorblax Hollow", "Quuxen Hills"]


def test_morning_dew_has_no_zone_made_of_prose_or_of_a_map_position():
    result = real("Morning Dew")
    assert [d["zone"] for d in result.drops] == [None]  # seven creatures, no zone line
    assert len(result.drops[0]["npcs"]) == 7
    assert all(not any(char.isdigit() for char in str(d["zone"])) for d in result.drops)


def test_a_vendor_row_whose_zone_cell_is_prose_has_no_zone_and_one_whose_cell_is_a_name_has_it():
    soldby = (
        "{{ItemWhereRow | Not sold here, or so I was told. | [[A Vendor]] | | (1, 2) }}\n"
        "{{ItemWhereRow | Zorblax Hollow, Quuxen Hills | [[B Vendor]] | | (3, 4) }}\n"
        "{{ItemWhereRow | [[Blarg Pass]] | [[C Vendor]] | | (5, 6) }}\n"
    )
    assert parsed(soldby=soldby).sold_by == [
        {"zone": None, "npc": "A Vendor"},
        {"zone": "Zorblax Hollow", "npc": "B Vendor"},
        {"zone": "Quuxen Hills", "npc": "B Vendor"},
        {"zone": "Blarg Pass", "npc": "C Vendor"},
    ]


def test_a_quest_written_as_an_external_link_is_its_anchor_text():
    result = parsed(relatedquests="* [https://example.invalid/q Anchor Quest]\n* [[Zorblax Tests|Courage]]")
    assert result.quests == ["Anchor Quest", "Zorblax Tests"]
    assert result.quest_labels == [{"title": "Zorblax Tests", "label": "Courage"}]


# ---- 4: the foraged parameter is a source of zones -------------------------------------------------------------------


def test_the_foraged_parameter_lists_zones_and_nothing_else_is_read_from_it():
    result = parsed(foraged="\n* [[Zorblax Hollow]]\n* [[Quuxen|Quuxen Hills]]\n* [[Blarg Pass]]\n")
    assert result.foraged == ["Zorblax Hollow", "Quuxen Hills", "Blarg Pass"]
    assert result.drops == [] and result.quests == []


def test_a_foraged_list_may_hold_text_notes_and_links_in_one_bullet():
    foraged = (
        "* [[Zorblax Hollow]], possibly [[Quuxen Hills]]\n"
        "* [[Blarg Pass]] ?\n"
        "* ''This item can be foraged in most zones.''\n"
        "* Various\n"
        "* [[File:Map.png]]\n"
    )
    assert parsed(foraged=foraged).foraged == ["Zorblax Hollow", "Quuxen Hills", "Blarg Pass", "Various"]


def test_a_blank_or_missing_foraged_parameter_gives_no_zone_and_a_repeat_is_warned_about():
    assert parsed().foraged == [] and parsed(foraged="\n  \n").foraged == []
    result = parse_page(page("{{Itempage|itemname=Zorblax Ring|statsblock=Slot: EAR|foraged=* [[A One]]|foraged=* [[B Two]]}}"))
    assert result.foraged == ["B Two"]
    assert {"code": "duplicate-param", "field": "foraged"} in result.warnings


def test_notes_in_a_foraged_list_name_no_zone():
    foraged = "* None\n* <u>Located in the following locations:</u>\n* N O T _ C L A S S I C\n* ITEM REMOVED FROM GAME\n* [[Zorblax Hollow]]"
    result = parsed(foraged=foraged)
    assert result.foraged == ["Zorblax Hollow"] and result.page_flags == []  # only the drop list can say the item is gone


def test_a_foraged_list_is_read_whatever_the_depth_of_its_bullets():
    assert parsed(foraged="* [[A One]]\n** [[B Two]]\n[[C Three]]").foraged == ["A One", "B Two", "C Three"]


def test_chilled_tundra_root_is_foraged_in_one_zone_and_fishing_grubs_in_eight():
    assert real("Chilled Tundra Root").foraged == ["Everfrost Peaks"]
    grubs = real("Fishing Grubs").foraged  # [[Freeport|East Freeport]] first
    assert len(grubs) == 8 and grubs[0] == "East Freeport" and "Halas" in grubs


def test_morning_dew_is_foraged_in_two_faydarks():
    assert real("Morning Dew").foraged == ["Lesser Faydark", "Greater Faydark"]


# ---- 11: categories are read wherever they stand -----------------------------------------------------------------------


def test_a_category_inside_a_template_parameter_is_a_category():
    content = "{{Classic Era}}\n{{Itempage\n|itemname=Zorblax Ring\n|statsblock=Slot: EAR\n|dropsfrom=[[Zorblax Hollow]]\n[[Category:Ring]]\n[[Category:Kunark Era]]\n}}"
    result = parse_page(page(content))
    assert result.categories == ["Ring", "Kunark Era"]
    assert result.era_tags == ["Classic Era", "Kunark Era"]
    assert result.drops == [{"zone": "Zorblax Hollow", "npcs": []}]  # and the category lines are not zones


def test_categories_in_comments_and_nowiki_are_still_not_categories():
    content = (
        "{{Itempage\n|itemname=Zorblax Ring\n|statsblock=Slot: EAR\n|notes=<!-- [[Category:Hidden]] --> <nowiki>[[Category:Escaped]]</nowiki>\n}}\n"
        "<!-- [[Category:Gone]] -->\n[[Category:Shown]]\n[[:Category:Linked]]\n[[ category : Spaced_Out ]]"
    )
    assert parse_page(page(content)).categories == ["Shown", "Spaced Out"]


def test_a_category_that_stands_twice_is_listed_once_in_order():
    content = "{{Itempage\n|itemname=Zorblax Ring\n|statsblock=Slot: EAR\n|notes=[[Category:B Two]]\n}}\n[[Category:A One]]\n[[Category:B Two]]"
    assert parse_page(page(content)).categories == ["B Two", "A One"]


def test_fine_steel_naginata_keeps_its_four_categories():
    result = real("Fine Steel Naginata")  # they stand inside the dropsfrom parameter
    assert result.categories == ["Warrior Equipment", "Shadow Knight Equipment", "Paladin Equipment", "2H Slashing"]
    assert result.drops == [{"zone": "Stonebrunt Mountains", "npcs": ["Jelquar the Soulslayer"]}]


# ---- 7: the guard against pathological markup counts only what is a problem --------------------------------------------


@pytest.mark.parametrize("tag", ["li", "p", "td", "tr", "th", "dd", "dt", "option"])
def test_tags_whose_end_tag_is_optional_in_html_are_not_unmatched_openers(tag):
    assert unmatched_openers(f"<{tag}>x" * 40) == 0
    content = template(itemname="Zorblax Ring", statsblock="Slot: EAR") + "\n" + f"<{tag}>x" * 40
    assert isinstance(parse_page(page(content)), ParsedPage)


def test_a_list_written_with_unclosed_li_tags_is_not_too_complex():
    items = "<ul>" + "".join(f"<li> {n} <span>x</span>" for n in range(30)) + "</ul>"
    assert unmatched_openers(items) == 0


def test_a_lone_angle_bracket_counts_only_when_it_could_open_a_tag():
    assert unmatched_openers("a < b " * 50) == 0
    assert unmatched_openers("I <3 you, x <= 5, y << 2, z <- 1 " * 20) == 0
    assert unmatched_openers("x < " * 50) == 0 and unmatched_openers("<") == 0
    assert unmatched_openers("<1x>" * 20) == 20  # the tokenizer reads <1x> as a tag, and rescans for its end
    assert unmatched_openers("<$x>" * 20) == 20
    assert unmatched_openers("<span " * 20) == 20 and unmatched_openers("<br x=1 <br x=1 ") == 2


@pytest.mark.parametrize(("tag", "count"), [("p", 12_000), ("option", 6_000)])
def test_many_unclosed_paragraphs_are_still_skipped_because_the_parser_is_slow_on_them(tag, count):
    # <p> and <option> are not "single" tags to the tokenizer: it rescans the page from each unclosed one
    start = time.perf_counter()
    result = parse_page(page(template(itemname="Zorblax Ring", statsblock="Slot: EAR", notes=f"<{tag}>x" * count)))
    assert result == Skip(7, "Zorblax Ring", "too-complex")
    assert time.perf_counter() - start < 2


def test_a_page_of_stray_angle_brackets_is_skipped_quickly_and_a_page_of_prose_with_them_is_not():
    start = time.perf_counter()
    result = parse_page(page(template(itemname="Zorblax Ring", statsblock="Slot: EAR", notes="<1x>" * 5000)))
    assert result == Skip(7, "Zorblax Ring", "too-complex") and time.perf_counter() - start < 2
    start = time.perf_counter()
    result = parse_page(page(template(itemname="Zorblax Ring", statsblock="Slot: EAR", notes="< a " * 5000)))
    assert isinstance(result, ParsedPage) and time.perf_counter() - start < 2  # a lone "<" is fast to parse
