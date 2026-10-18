"""Tests for the item page parser: the Itempage template, its sections and its parameters.

Pages come from the recorded fixtures (real eqlwiki text, see fixtures/wiki/README.md) or are
built here from invented names (Zorblax and friends).
"""

import json
import time
from pathlib import Path

import mwparserfromhell
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from trioforge.sources.eqlwiki import fixture_slug, page_records
from trioforge.sources.itempage import (
    SKIP_REASONS,
    ParsedPage,
    Skip,
    first_link_target,
    link_target,
    parse_page,
    plain_text,
    unmatched_openers,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "wiki"
FIXTURE_TITLES = [
    "Engineer's Ring",
    "Girdle of Faith",
    "Cloak of Flames",
    "Shield of the Stalwart Seas",
    "Bladestopper",
    "Earthshaker",
    "Wu's Fist of Mastery",
    "Torrid Corruptor",
    "Baton of the Sky",
    "Talisman of Kejaar Kerrath",
    "Skinner's Belt",
    "Imbued Granite Spaulders",
    "Darkwar Mask",
    "Rusty Dagger",
    "Bone Chips",
    "Backpack",
    "Mask of Deception",
    "Dwarven Chain Tunic",
    "Symbol of Marr",
    "Ethereal Mist Chestplate",
]


def fixture(title):
    """The fetch_pages-style record of a recorded page."""
    path = FIXTURES / f"{fixture_slug(title)}.json"
    (record,) = page_records(json.loads(path.read_text(encoding="utf-8")))
    return record


def page(content, **fields):
    record = {"pageid": 7, "ns": 0, "title": "Zorblax Ring", "revid": 70, "timestamp": "2026-10-01T00:00:00Z"}
    record.update(fields)
    record["content"] = content
    return record


def template(**params):
    """Wikitext for an Itempage template with the given parameters."""
    body = "".join(f"|{name}={value}\n" for name, value in params.items())
    return "{{Itempage\n" + body + "}}"


def parse(content, **fields):
    return parse_page(page(content, **fields))


def parsed(statsblock="Slot: EAR", **params):
    """Parse a synthetic page that has the given parameters; it must come out as a ParsedPage."""
    result = parse(template(itemname="Zorblax Ring", statsblock=statsblock, **params))
    assert isinstance(result, ParsedPage), result
    return result


def warning_codes(result):
    return [(w["code"], w["field"]) for w in result.warnings]


# ---- the recorded pages ---------------------------------------------------------------------


def test_engineers_ring_parses_to_the_expected_fields():
    record = fixture("Engineer's Ring")
    result = parse_page(record)
    assert isinstance(result, ParsedPage)
    assert (result.pageid, result.revid, result.title) == (42638, 193407, "Engineer's Ring")
    assert result.name == "Engineer's Ring"
    assert result.statsblock_lines == [
        "Lore Equipped, No Trade",
        "Slot: FINGER",
        "AC: 20",
        "STR: +5  STA: +5  INT: +5  WIS: +5  AGI: +5  DEX: +5  CHA: +5  HP: +5  MANA: +20  END: +20",
        "Size: TINY  WT: 0.1",
        "Class: WAR CLR PAL SHD ROG NEC WIZ MAG ENC",
        "Race: ALL",
    ]
    assert "Slot: FINGER" in result.statsblock_lines
    assert "Class: WAR CLR PAL SHD ROG NEC WIZ MAG ENC" in result.statsblock_lines
    # The link target Innoruuk_(God) with the label Innoruuk gives the label.
    assert result.drops == [{"zone": "Plane of Hate", "npcs": ["Innoruuk"]}]
    assert result.era_tags == ["Classic Era"]
    assert result.lucy_img_id == 616
    assert result.notes_lore == "Ring of an engineer"
    assert result.sold_by == [] and result.quests == [] and result.crafted == []
    assert result.categories == [
        "Cleric Equipment",
        "Enchanter Equipment",
        "Magician Equipment",
        "Necromancer Equipment",
        "Paladin Equipment",
        "Rogue Equipment",
        "Shadow Knight Equipment",
        "Warrior Equipment",
        "Wizard Equipment",
        "Fingers",
        "Plane of Hate",
    ]
    assert result.warnings == []


def test_girdle_of_faith_reads_a_quest_link_by_its_target_and_keeps_the_label():
    result = parse_page(fixture("Girdle of Faith"))
    # [[Plane of Sky#Paladin Tests|Paladin Test of Spirit]]: the target (no #fragment) is what the quest is looked up by
    assert result.quests == ["Plane of Sky"]
    assert result.quest_labels == [{"title": "Plane of Sky", "label": "Paladin Test of Spirit"}]  # it was the label
    assert result.drops == []
    assert "Haste: +41%" in result.statsblock_lines
    assert result.notes_lore == "Dirkog's Girdle of Faith"


def test_shield_keeps_the_effect_markup_for_the_normalizer_and_reads_npc_notes_away():
    result = parse_page(fixture("Shield of the Stalwart Seas"))
    assert "Slot: SECONDARY  Type: Shield" in result.statsblock_lines
    assert "Effect: [[Ultravision|<span class='itemeff'>Ultravision</span>]] (Worn)" in result.statsblock_lines
    # "(unconfirmed for EQL)" after a link is a note, not part of the NPC name
    assert result.drops == [
        {"zone": "Plane of Hate", "npcs": ["an eerie chest", "Lord of Ire", "Maestro of Rancor"]}
    ]


def test_torrid_corruptor_drops_empty_lines_and_keeps_comma_separated_classes():
    result = parse_page(fixture("Torrid Corruptor"))
    assert "" not in result.statsblock_lines
    assert "Class: PAL, SHD" in result.statsblock_lines
    assert "Effect: [[Unrighteous Bash (Worn)]]" in result.statsblock_lines
    assert result.quests == ["The Torrid Corruptor"]


def test_baton_of_the_sky_has_its_indented_effect_lines_stripped():
    lines = parse_page(fixture("Baton of the Sky")).statsblock_lines
    start = lines.index("Effect:  [[Blessing of the Lord Commander]] (Must Equip)")
    assert lines[start + 1 : start + 4] == [
        "Casting Time: Instant",
        "Required Level: 49",
        "Cooldown: 600 seconds",
    ]


def test_rusty_dagger_sources():
    result = parse_page(fixture("Rusty Dagger"))
    assert result.drops == [{"zone": "Various Zones", "npcs": ["Common drop from low-level humanoids"]}]
    # A quest title keeps its parenthesis: it is the quest's name, not a disambiguator to drop.
    assert result.quests == ["Tunare Scouts Dagger", "Black Wolf Skin", "Runnyeye Warbeads (Kaladim Rogue)"]
    assert result.sold_by == [
        {"zone": "East Freeport", "npc": "Harg Tonicka"},
        {"zone": "East Freeport", "npc": "Tohsan Hallard"},
    ]
    # `recipes` lists what the item is used in, not how it is made.
    assert result.crafted == []
    assert result.notes_lore is None
    assert result.warnings == []


def test_bone_chips_two_drop_zones_and_no_lore_in_long_notes():
    result = parse_page(fixture("Bone Chips"))
    assert result.drops == [
        {"zone": "Various Zones", "npcs": ["Many skeleton types"]},
        {"zone": "Najena", "npcs": ["a skeleton"]},
    ]
    assert result.quests == ["Bone Chips Quests"]
    assert result.notes_lore is None  # the notes hold prose, not an Item Lore template
    assert result.categories == ["Quest Items"]


def test_backpack_zones_vendors_and_wrapper_templates():
    result = parse_page(fixture("Backpack"))
    zones = [drop["zone"] for drop in result.drops]
    assert len(zones) == 18 and zones[0] == "Befallen" and zones[-1] == "Toxxulia Forest"
    # {{VeliousGray| [[The Warrens]] }} is unwrapped, and so is the NPC inside another one
    assert {"zone": "The Warrens", "npcs": ["a kobold runt"]} in result.drops
    assert {"zone": "North Qeynos", "npcs": ["a gnoll pup"]} in result.drops  # [[Qeynos|North Qeynos]]
    rows = result.sold_by
    assert rows[0] == {"zone": "Ak'Anon", "npc": "a clockwork merchant"}
    assert {"zone": "East Cabilis", "npc": "Rastok"} in rows  # [[Cabilis|East Cabilis]]
    assert {"zone": "Thurgadin", "npc": "Brigam"} in rows  # an ItemWhereRowVel row
    assert rows.count({"zone": "Icewell Keep", "npc": "Coldain Outcast"}) == 1  # listed twice, once kept
    # 115 ItemWhereRow lines in the page, one of them a repeat of the same zone and vendor
    assert len(rows) == len({(row["zone"], row["npc"]) for row in rows}) == 114
    assert result.quests == [
        "Cheslin's Illusion Cards",
        "Fisherman Convert",
        "Lizard Dolls",
        "Skeleton Killing",
        "Zombie Flesh",
    ]
    assert result.categories == ["Containers", "Vendor Sold", "Quest Items"]
    assert "Weight Reduction: 0%  Capacity: 8  Size Capacity: LARGE" in result.statsblock_lines
    assert result.warnings == []


def test_era_tags_come_from_the_era_templates():
    assert parse_page(fixture("Darkwar Mask")).era_tags == ["Velious Era"]
    assert parse_page(fixture("Mask of Deception")).era_tags == ["Temple Era"]
    assert parse_page(fixture("Bladestopper")).era_tags == []  # this page has no era template


def test_item_lore_missing_is_not_item_lore():
    assert parse_page(fixture("Mask of Deception")).notes_lore is None
    assert parse_page(fixture("Imbued Granite Spaulders")).notes_lore is None
    assert parse_page(fixture("Skinner's Belt")).notes_lore == "Lost belt of Kruss da Troll"


def test_category_links_lose_underscores_and_leading_spaces():
    assert "Hand to Hand" in parse_page(fixture("Wu's Fist of Mastery")).categories  # [[Category:Hand_to_Hand]]
    assert "Illusions" in parse_page(fixture("Mask of Deception")).categories  # [[Category: Illusions]]
    assert "Instant Click Equipment" in parse_page(fixture("Bladestopper")).categories


def test_a_blank_focus_effect_parameter_gives_nothing():
    assert parse_page(fixture("Talisman of Kejaar Kerrath")).focus_effects == []
    # a bare link line is a quest, with or without a bullet
    assert parse_page(fixture("Talisman of Kejaar Kerrath")).quests == ["This Means Warrr"]


def test_the_missing_fixture_is_skipped_as_missing():
    record = fixture("Dwarven Chain Tunic")
    assert parse_page(record) == Skip(None, "Dwarven Chain Tunic", "missing")


def test_every_one_of_the_20_fixtures_parses_or_skips_without_an_exception():
    outcomes = {title: parse_page(fixture(title)) for title in FIXTURE_TITLES}
    assert all(isinstance(outcome, (ParsedPage, Skip)) for outcome in outcomes.values())
    skipped = {title for title, outcome in outcomes.items() if isinstance(outcome, Skip)}
    assert skipped == {"Dwarven Chain Tunic"}
    for title, outcome in outcomes.items():
        if isinstance(outcome, ParsedPage):
            record = fixture(title)
            assert (outcome.pageid, outcome.revid, outcome.title) == (record["pageid"], record["revid"], title)
            assert outcome.name == title and outcome.statsblock_lines
            assert isinstance(outcome.lucy_img_id, int)
            assert outcome.warnings == []


# ---- skips ----------------------------------------------------------------------------------


def test_a_missing_record_is_skipped():
    assert parse_page({"pageid": 9, "title": "Gone", "missing": True}) == Skip(9, "Gone", "missing")


@pytest.mark.parametrize(
    "text",
    [
        "#REDIRECT [[Zorblax Blade]]",
        "#redirect [[Zorblax Blade]]",
        "  \n#Redirect [[Zorblax Blade#History]]\n[[Category:Redirects]]",
        "#REDIRECT: [[Zorblax Blade]]",
        "#REDIRECT[[Zorblax Blade]]",
    ],
)
def test_a_redirect_page_is_skipped_as_a_redirect(text):
    assert parse(text) == Skip(7, "Zorblax Ring", "redirect")


def test_a_redirect_in_the_middle_of_a_page_is_not_a_redirect():
    result = parse("See also:\n#REDIRECT [[x]]\n" + template(statsblock="Slot: EAR"))
    assert isinstance(result, ParsedPage)


@pytest.mark.parametrize(
    "text",
    [
        "Zorblax may refer to:\n* [[Zorblax Ring]]\n* [[Zorblax Blade]]\n{{Disambig}}",
        "{{Spellpage|name=Zorblax Bolt}}",
        "A page with no template at all.",
        "<!-- {{Itempage|statsblock=Slot: EAR}} -->",
        "<nowiki>{{Itempage|statsblock=Slot: EAR}}</nowiki>",
        "{{Item page|statsblock=Slot: EAR}}",
        "{{:Itempage}}",
    ],
)
def test_a_page_without_the_template_is_skipped(text):
    assert parse(text) == Skip(7, "Zorblax Ring", "no-itempage-template")


@pytest.mark.parametrize("text", ["", "   \n\t  ", None])
def test_an_empty_page_is_skipped(text):
    assert parse(text) == Skip(7, "Zorblax Ring", "empty")


@pytest.mark.parametrize("ns", [1, 2, 6, 10, 14, 828])
def test_a_page_outside_the_main_namespace_is_skipped(ns):
    result = parse(template(statsblock="Slot: EAR"), ns=ns, title="Template:Zorblax")
    assert result == Skip(7, "Template:Zorblax", "namespace")


def test_a_record_without_ns_counts_as_the_main_namespace():
    record = page(template(statsblock="Slot: EAR"))
    del record["ns"]
    assert isinstance(parse_page(record), ParsedPage)


@pytest.mark.parametrize("statsblock", ["", "   ", "\n\n", "<br>\n<br/>", "<!-- nothing here -->", "{{Foo}}"])
def test_a_blank_statsblock_is_skipped_never_a_zero_stat_item(statsblock):
    result = parse(template(itemname="Zorblax Ring", statsblock=statsblock))
    assert result == Skip(7, "Zorblax Ring", "empty-statsblock")


def test_a_missing_statsblock_is_skipped():
    assert parse(template(itemname="Zorblax Ring")) == Skip(7, "Zorblax Ring", "empty-statsblock")


# ---- the template and its parameters --------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["Itempage", "itempage", "ITEMPAGE", "Template:Itempage", "template:itempage", " Template : Itempage ", "Itempage\n"],
)
def test_the_template_name_matches_loosely(name):
    result = parse("{{" + name + "|statsblock=Slot: EAR}}")
    assert isinstance(result, ParsedPage)


def test_spaces_and_underscores_are_equivalent_in_template_names():
    code = "{{Itempage|statsblock=Slot: EAR|notes={{Item_Lore|Zorblax lore}}}}"
    assert parse(code).notes_lore == "Zorblax lore"
    code = "{{Itempage|statsblock=Slot: EAR|notes={{template:item   lore|Zorblax lore}}}}"
    assert parse(code).notes_lore == "Zorblax lore"


def test_parameter_names_match_loosely():
    result = parse("{{Itempage|ItemName = Quuxen Ring |  STATSBLOCK = Slot: EAR |Lucy_Img_Id=12}}")
    assert isinstance(result, ParsedPage)
    assert result.name == "Quuxen Ring" and result.lucy_img_id == 12


def test_several_itempage_templates_first_wins_with_a_warning():
    code = (
        "{{Itempage|itemname=First Ring|statsblock=Slot: EAR}}\n"
        "{{itempage|itemname=Second Ring|statsblock=Slot: NECK}}"
    )
    result = parse(code)
    assert result.name == "First Ring" and result.statsblock_lines == ["Slot: EAR"]
    assert warning_codes(result) == [("multiple-itempage", "itempage")]


def test_duplicate_parameters_last_wins_with_a_warning():
    # MediaWiki shows the last of a repeated parameter, so that is the one read; the warning stays
    code = "{{Itempage|itemname=First Ring|itemname=Second Ring|statsblock=Slot: EAR|statsblock=Slot: NECK}}"
    result = parse(code)
    assert result.name == "Second Ring" and result.statsblock_lines == ["Slot: NECK"]
    assert warning_codes(result) == [("duplicate-param", "itemname"), ("duplicate-param", "statsblock")]


def test_a_duplicate_of_a_parameter_we_do_not_read_is_ignored():
    code = "{{Itempage|statsblock=Slot: EAR|flavour=a|flavour=b}}"
    assert parse(code).warnings == []


@pytest.mark.parametrize("itemname", ["", "   ", "\n"])
def test_a_blank_itemname_falls_back_to_the_title(itemname):
    result = parse(template(itemname=itemname, statsblock="Slot: EAR"), title="Zorblax Ring")
    assert result.name == "Zorblax Ring"


def test_a_missing_itemname_falls_back_to_the_title():
    assert parse(template(statsblock="Slot: EAR"), title="Quuxen Blade").name == "Quuxen Blade"


def test_itemname_entities_decode_and_markup_characters_stay_for_the_sanitizer():
    result = parse(template(itemname="Zorblax&#39;s Ring", statsblock="Slot: EAR"))
    assert result.name == "Zorblax's Ring"
    result = parse(template(itemname="Ring<script>alert(1)</script>", statsblock="Slot: EAR"))
    assert result.name == "Ring<script>alert(1)</script>"  # the sanitizer, not this parser, removes < and >


@pytest.mark.parametrize(
    ("value", "expected", "warns"),
    [
        ("616", 616, False),
        (" 616 ", 616, False),
        ("", None, False),
        ("abc", None, True),
        ("12a", None, True),
        ("-5", None, True),
        ("1.5", None, True),
        ("\u00b2", None, True),  # a superscript two is a digit to str.isdigit() but not to us
        ("\uff11\uff12", None, True),  # full-width digits
        ("1" * 16, None, True),
    ],
)
def test_lucy_img_id(value, expected, warns):
    result = parse(template(itemname="Zorblax Ring", statsblock="Slot: EAR", lucy_img_ID=value))
    assert result.lucy_img_id == expected
    assert warning_codes(result) == ([("bad-lucy-id", "lucy_img_id")] if warns else [])


def test_the_lucy_id_may_be_absent():
    result = parsed()
    assert result.lucy_img_id is None and result.warnings == []


# ---- the statsblock -------------------------------------------------------------------------


def test_br_variants_and_newlines_give_identical_lines():
    expected = ["Slot: EAR", "AC: 5", "STR: +3"]
    variants = [
        "Slot: EAR<br>AC: 5<br>STR: +3",
        "Slot: EAR<br/>AC: 5<br/>STR: +3",
        "Slot: EAR<br />AC: 5<br />STR: +3",
        "Slot: EAR<BR>AC: 5<Br/>STR: +3",
        "Slot: EAR<br clear=\"all\">AC: 5<br class='x' />STR: +3",
        "Slot: EAR\nAC: 5\nSTR: +3",
        "Slot: EAR\r\nAC: 5\r\nSTR: +3",
        "\nSlot: EAR<br>\nAC: 5 <br>\n   STR: +3<br>\n",
        "Slot: EAR<br>\n<br>\nAC: 5<br><br><br>STR: +3",
    ]
    for variant in variants:
        assert parsed(statsblock=variant).statsblock_lines == expected, variant


def test_html_entities_decode_exactly_once():
    lines = parsed(statsblock="Effect: Zorblax&#39;s Ring (Worn)<br>x &amp;lt; y<br>&#x41;&amp;amp;B").statsblock_lines
    assert lines == ["Effect: Zorblax's Ring (Worn)", "x &lt; y", "A&amp;B"]


def test_a_non_breaking_space_indent_is_stripped():
    lines = parsed(statsblock="Effect: [[Zorblax Blast]] (Must Equip)<br>&nbsp; Casting Time: Instant").statsblock_lines
    assert lines[1] == "Casting Time: Instant"


def test_html_comments_are_removed_even_across_br():
    lines = parsed(statsblock="Slot: EAR<!-- AC: 99<br>STR: 99 -->\nAC: 5<!-- x -->").statsblock_lines
    assert lines == ["Slot: EAR", "AC: 5"]


def test_nowiki_is_unwrapped():
    lines = parsed(statsblock="<nowiki>Slot: EAR</nowiki><br>AC: <nowiki>5</nowiki>").statsblock_lines
    assert lines == ["Slot: EAR", "AC: 5"]


def test_nested_templates_are_removed_with_a_warning():
    result = parsed(statsblock="Slot: EAR<br>{{Zorblax|a|{{inner}}}}AC: 5<br>STR: {{x}}+3")
    assert result.statsblock_lines == ["Slot: EAR", "AC: 5", "STR: +3"]
    assert warning_codes(result) == [("nested-template", "statsblock")] * 2


def test_links_and_other_markup_stay_in_the_lines_for_the_normalizer():
    line = "Effect:  [[Zorblax Blast|<span class='itemeff'>Zorblax Blast</span>]] (Any Slot, Casting Time: 3.0)"
    assert parsed(statsblock=line + "<br>Slot: EAR").statsblock_lines == [line, "Slot: EAR"]


def test_a_hostile_line_is_kept_verbatim_it_is_the_normalizer_that_refuses_it():
    line = "<meta http-equiv=refresh content=0;url=https://example.invalid/x>"
    assert line in parsed(statsblock="Slot: EAR<br>" + line).statsblock_lines


def test_the_statsblock_of_a_page_with_html_comments_around_the_template_still_parses():
    code = "<!-- a note -->\n" + template(itemname="Zorblax Ring", statsblock="Slot: EAR") + "\n<!-- more -->"
    assert isinstance(parse(code), ParsedPage)


# ---- notes ----------------------------------------------------------------------------------


def test_notes_lore_is_the_item_lore_template_text_only():
    assert parsed(notes="Some prose. {{Item Lore|Forged by a Zorblax smith}} More prose.").notes_lore == (
        "Forged by a Zorblax smith"
    )
    assert parsed(notes="Only prose.").notes_lore is None
    assert parsed(notes="").notes_lore is None
    assert parsed(notes="{{Item Lore|}}").notes_lore is None
    assert parsed(notes="{{Item Lore|   }}").notes_lore is None


def test_notes_lore_loses_wiki_markup_and_decodes_entities_once():
    notes = "{{Item Lore|''A'' [[Zorblax|blade]] &amp;lt; &#39;x&#39; [https://example.invalid/y link]}}"
    assert parsed(notes=notes).notes_lore == "A blade &lt; 'x' link"


def test_the_first_item_lore_template_wins():
    assert parsed(notes="{{Item Lore|one}}{{Item Lore|two}}").notes_lore == "one"


# ---- drops ----------------------------------------------------------------------------------


def test_two_drop_zones_give_two_entries_in_order():
    dropsfrom = "\n[[Plane of Hate]]\n\n* [[Zorblax Lord]]\n* [[Quuxen]]\n\n[[Plane of Fear]]\n\n* [[Blarg]]\n"
    assert parsed(dropsfrom=dropsfrom).drops == [
        {"zone": "Plane of Hate", "npcs": ["Zorblax Lord", "Quuxen"]},
        {"zone": "Plane of Fear", "npcs": ["Blarg"]},
    ]


def test_a_zone_that_appears_twice_stays_twice():
    dropsfrom = "[[Zorblax Keep]]\n* [[A]]\n[[Zorblax Keep]]\n* [[B]]"
    assert [d["zone"] for d in parsed(dropsfrom=dropsfrom).drops] == ["Zorblax Keep", "Zorblax Keep"]


def test_a_zone_given_as_text_and_npcs_as_text():
    assert parsed(dropsfrom="Various Zones\n\n* Common drop from low-level humanoids").drops == [
        {"zone": "Various Zones", "npcs": ["Common drop from low-level humanoids"]}
    ]


def test_a_comma_separated_line_without_bullets_is_split_into_zones():
    assert parsed(dropsfrom="Zorblax Keep, Quuxen Hollow, Blarg Pass").drops == [
        {"zone": "Zorblax Keep", "npcs": []},
        {"zone": "Quuxen Hollow", "npcs": []},
        {"zone": "Blarg Pass", "npcs": []},
    ]
    assert parsed(dropsfrom="[[Zorblax Keep]], [[Quuxen Hollow]]").drops == [
        {"zone": "Zorblax Keep", "npcs": []},
        {"zone": "Quuxen Hollow", "npcs": []},
    ]


def test_commas_inside_a_bullet_do_not_split_the_npc():
    assert parsed(dropsfrom="Zorblax Keep\n* Zorblax, the Mighty").drops == [
        {"zone": "Zorblax Keep", "npcs": ["Zorblax, the Mighty"]}
    ]


def test_labels_beat_targets_and_disambiguators_and_fragments_go():
    dropsfrom = (
        "[[Zorblax_Keep#Loot|Zorblax Keep (Upper)]]\n"
        "* [[Quuxen_(God)|Quuxen]]\n"
        "* [[Blarg (Boss)]]\n"
        "* [[Blarg_Two#History]]\n"
        "* [[Plain Name]]\n"
        "* [[Pipe Target|   ]]\n"
    )
    assert parsed(dropsfrom=dropsfrom).drops == [
        {"zone": "Zorblax Keep (Upper)", "npcs": ["Quuxen", "Blarg", "Blarg Two", "Plain Name", "Pipe Target"]}
    ]


def test_deeper_bullets_are_npcs_too():
    assert parsed(dropsfrom="[[Zorblax Keep]]\n* [[A]]\n** [[B]]\n*** [[C]]").drops == [
        {"zone": "Zorblax Keep", "npcs": ["A", "B", "C"]}
    ]


def test_bullets_before_any_zone_keep_the_npcs_with_no_zone():
    assert parsed(dropsfrom="* [[A]]\n* [[B]]\n[[Zorblax Keep]]\n* [[C]]").drops == [
        {"zone": None, "npcs": ["A", "B"]},
        {"zone": "Zorblax Keep", "npcs": ["C"]},
    ]


def test_drop_lines_may_be_separated_by_br():
    assert parsed(dropsfrom="[[Zorblax Keep]]<br>* [[A]]<br />* [[B]]").drops == [
        {"zone": "Zorblax Keep", "npcs": ["A", "B"]}
    ]


def test_wrapper_templates_are_unwrapped_in_every_source_parameter():
    dropsfrom = "{{VeliousGray| [[Zorblax Keep]] }}\n* {{VeliousGray| [[A]] }}\n* {{Other|1=ignored|[[B]]}}"
    result = parsed(dropsfrom=dropsfrom)
    assert result.drops == [{"zone": "Zorblax Keep", "npcs": ["A", "B"]}]


def test_comments_in_drops_are_ignored():
    assert parsed(dropsfrom="[[Zorblax Keep]] <!-- check -->\n<!-- * [[Hidden]] -->\n* [[A]]").drops == [
        {"zone": "Zorblax Keep", "npcs": ["A"]}
    ]


def test_file_and_category_links_are_not_names():
    dropsfrom = "[[Zorblax Keep]]\n* [[File:Boss.png|thumb|A boss]]\n* [[Category:Bosses]]\n* [[A]]"
    assert parsed(dropsfrom=dropsfrom).drops == [{"zone": "Zorblax Keep", "npcs": ["A"]}]


def test_entities_in_labels_decode_once_and_markup_stays_text():
    dropsfrom = "[[Zorblax Keep]]\n* [[Boss|&lt;b&gt;Boss&lt;/b&gt;]]\n* [[Other|&amp;lt;i&amp;gt;]]"
    assert parsed(dropsfrom=dropsfrom).drops == [
        {"zone": "Zorblax Keep", "npcs": ["<b>Boss</b>", "&lt;i&gt;"]}
    ]


def test_external_links_keep_only_their_anchor_text():
    dropsfrom = (
        "[[Zorblax Keep]]\n"
        "* [https://example.invalid/boss Boss Name]\n"
        "* [https://example.invalid/bare]\n"
        "* https://bare.example.invalid/url\n"
        "* [javascript:alert(1) Evil One]\n"
        "* [ JavaScript:alert(1) Evil Two]\n"
        "* [data:text/html,hi Evil Three]\n"
        "* [//example.invalid/proto Proto Name]\n"
    )
    (drop,) = parsed(dropsfrom=dropsfrom).drops
    assert drop["npcs"] == ["Boss Name", "Evil One", "Evil Two", "Evil Three", "Proto Name"]
    flat = json.dumps(drop).lower()
    assert "http" not in flat and "javascript" not in flat and "data:" not in flat


def test_a_drop_zone_given_as_an_external_link_keeps_the_anchor_only():
    (drop,) = parsed(dropsfrom="[https://example.invalid/z Zorblax Keep]\n* [[A]]").drops
    assert drop == {"zone": "Zorblax Keep", "npcs": ["A"]}


# ---- vendors, quests, crafting ---------------------------------------------------------------


def test_vendor_rows_give_zone_and_npc_from_the_row_templates():
    soldby = (
        "{{ItemWhereTable|\n"
        "{{ItemWhereRow | [[Freeport|East Freeport]] | [[Harg Tonicka]] | | (-41, -493) }}\n"
        "{{ItemWhereRowVel| [[Thurgadin]] | [[Brigam (Merchant)]] | | (1, 2) }}\n"
        "{{ItemWhereRow | Plain Zone | Plain Vendor | note | (0, 0) }}\n"
        "{{ItemWhereRow | [[Thurgadin]] | [[Brigam (Merchant)]] | | (3, 4) }}\n"
        "}}"
    )
    assert parsed(soldby=soldby).sold_by == [
        {"zone": "East Freeport", "npc": "Harg Tonicka"},
        {"zone": "Thurgadin", "npc": "Brigam"},
        {"zone": "Plain Zone", "npc": "Plain Vendor"},
    ]


def test_a_row_with_a_blank_vendor_is_skipped():
    soldby = "{{ItemWhereTable|{{ItemWhereRow | [[Zorblax Keep]] | | | (0, 0) }}}}"
    assert parsed(soldby=soldby).sold_by == []


def test_vendors_may_be_listed_like_drops():
    result = parsed(soldby="[[Zorblax Keep]]\n* [[Vendor One]]\n* [[Vendor Two]]\n[[Quuxen Hollow]]\n* [[Vendor Three]]")
    assert result.sold_by == [
        {"zone": "Zorblax Keep", "npc": "Vendor One"},
        {"zone": "Zorblax Keep", "npc": "Vendor Two"},
        {"zone": "Quuxen Hollow", "npc": "Vendor Three"},
    ]


def test_quests_are_link_targets_with_their_parentheses_and_the_labels_are_kept():
    relatedquests = (
        "\n* [[Plane of Sky#Paladin Tests|Paladin Test of Spirit]]\n"
        "* [[Quest_One_(Rivervale)]]\n"
        "[[Bare Quest]]\n"
        "* Plain text quest\n"
        "* [[File:X.png]]\n"
    )
    result = parsed(relatedquests=relatedquests)
    assert result.quests == [  # the first was the label, "Paladin Test of Spirit"
        "Plane of Sky",
        "Quest One (Rivervale)",
        "Bare Quest",
        "Plain text quest",
    ]
    assert result.quest_labels == [{"title": "Plane of Sky", "label": "Paladin Test of Spirit"}]


def test_crafting_comes_from_a_crafting_parameter():
    crafted = "\n* [[Forge]]\n** [[Zorblax Ore]]\n** [[Quuxen Dust]]\n* [[Kiln]]\n** [[Blarg Clay]]\n"
    result = parsed(playercrafted=crafted)
    assert result.crafted == [
        {"container": "Forge", "ingredients": ["Zorblax Ore", "Quuxen Dust"]},
        {"container": "Kiln", "ingredients": ["Blarg Clay"]},
    ]


def test_crafting_may_use_plain_container_lines():
    result = parsed(crafted="Oggok Forge\n* [[Zorblax Ore]]\n* [[Quuxen Dust]]")
    assert result.crafted == [{"container": "Oggok Forge", "ingredients": ["Zorblax Ore", "Quuxen Dust"]}]


def test_ingredients_before_any_container_have_no_container():
    result = parsed(crafted="** [[A]]\n* [[Forge]]\n** [[B]]")
    assert result.crafted == [
        {"container": None, "ingredients": ["A"]},
        {"container": "Forge", "ingredients": ["B"]},
    ]


def test_a_flat_crafting_list_is_a_list_of_containers():
    result = parsed(crafted="* [[A]]\n* [[B]]")
    assert result.crafted == [{"container": "A", "ingredients": []}, {"container": "B", "ingredients": []}]


def test_the_recipes_parameter_is_what_the_item_is_used_in_not_how_it_is_made():
    assert parsed(recipes="* [[Blacksmithing]]\n** [[Tarnished Dagger]]").crafted == []


SECTIONS = (
    template(itemname="Zorblax Ring", statsblock="Slot: EAR")
    + "\n== Sold by ==\n{{ItemWhereTable|{{ItemWhereRow | [[Zorblax Keep]] | [[Vendor One]] | | (0, 0) }}}}\n"
    + "== Related quests ==\n* [[Quest One]]\n* [[Quest Two]]\n"
    + "== Player crafted ==\n* [[Forge]]\n** [[Zorblax Ore]]\n** [[Quuxen Dust]]\n"
    + "== See also ==\n* [[Not a source]]\n"
)


def test_sources_fall_back_to_the_page_sections():
    result = parse(SECTIONS)
    assert result.sold_by == [{"zone": "Zorblax Keep", "npc": "Vendor One"}]
    assert result.quests == ["Quest One", "Quest Two"]
    assert result.crafted == [{"container": "Forge", "ingredients": ["Zorblax Ore", "Quuxen Dust"]}]


def test_sub_headings_inside_the_crafting_section_are_containers():
    code = (
        template(itemname="Zorblax Ring", statsblock="Slot: EAR")
        + "\n== Player crafted ==\n=== Forge ===\n* [[Zorblax Ore]]\n* [[Quuxen Dust]]\n=== Kiln ===\n* [[Blarg Clay]]\n"
        + "== See also ==\n* [[Not an ingredient]]\n"
    )
    assert parse(code).crafted == [
        {"container": "Forge", "ingredients": ["Zorblax Ore", "Quuxen Dust"]},
        {"container": "Kiln", "ingredients": ["Blarg Clay"]},
    ]


def test_a_parameter_beats_a_section_but_a_blank_parameter_does_not():
    code = SECTIONS.replace("|statsblock=Slot: EAR\n", "|statsblock=Slot: EAR\n|relatedquests=* [[Param Quest]]\n|soldby=\n")
    result = parse(code)
    assert result.quests == ["Param Quest"]
    assert result.sold_by == [{"zone": "Zorblax Keep", "npc": "Vendor One"}]  # blank param: use the section


def test_section_headings_match_loosely():
    code = template(itemname="Zorblax Ring", statsblock="Slot: EAR") + "\n==  related   QUESTS ==\n* [[Quest One]]\n"
    assert parse(code).quests == ["Quest One"]


# ---- categories and eras ---------------------------------------------------------------------


def test_categories_are_the_category_links_without_duplicates():
    code = (
        template(itemname="Zorblax Ring", statsblock="Slot: EAR")
        + "\n[[Category:Ear]]\n[[category:Ear]]\n[[Category: Rogue_Equipment ]]\n[[:Category:Not Me]]\n[[Category:Ear|sortkey]]"
    )
    assert parse(code).categories == ["Ear", "Rogue Equipment"]


def test_era_tags_from_templates_and_categories_are_normalized_sorted_and_unique():
    code = (
        "{{classic era}}{{Template:Classic_Era}}{{Kunark Era}}\n"
        + template(itemname="Zorblax Ring", statsblock="Slot: EAR")
        + "\n[[Category:Classic Era]]\n[[Category:velious era]]\n[[Category:Erasers]]\n[[Category:Era]]"
    )
    assert parse(code).era_tags == ["Classic Era", "Kunark Era", "Velious Era"]


def test_era_tags_are_in_alphabetical_order_whatever_the_hash_order():
    names = ["Zeta", "Eta", "Theta", "Alpha", "Delta", "Gamma", "Beta", "Iota", "Kappa", "Epsilon"]
    code = "".join("{{" + name + " Era}}" for name in names) + template(itemname="Zorblax Ring", statsblock="Slot: EAR")
    assert parse(code).era_tags == sorted(f"{name} Era" for name in names)


def test_a_template_that_merely_contains_era_is_not_an_era_tag():
    code = "{{Eraser}}{{Era}}{{Item Era Missing}}" + template(itemname="Zorblax Ring", statsblock="Slot: EAR")
    assert parse(code).era_tags == []


# ---- plain_text -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("wikitext", "expected"),
    [
        ("Plain", "Plain"),
        ("  spaced \n\t out  ", "spaced out"),
        ("[[Target|Label]]", "Label"),
        ("[[Target]]", "Target"),
        ("[[File:A.png|thumb]] text", "text"),
        ("[[Category:Cat]]text", "text"),
        ("''italic'' and '''bold'''", "italic and bold"),
        ("<span class='x'>in span</span>", "in span"),
        ("a<br>b<br />c", "a b c"),
        ("a<!-- hidden -->b", "ab"),
        ("a{{template|x}}b", "ab"),
        ("<nowiki>[[x]]</nowiki>", "[[x]]"),
        ("[https://example.invalid/u Anchor]", "Anchor"),
        ("[https://example.invalid/u]", ""),
        ("see https://bare.example.invalid/u now", "see now"),
        ("x&nbsp;y", "x y"),
        ("&amp;lt;", "&lt;"),
        ("&lt;b&gt;x&lt;/b&gt;", "<b>x</b>"),
        ("<script>alert(1)</script>", "<script>alert(1)</script>"),
        ("a<ref>footnote</ref>b", "ab"),
    ],
)
def test_plain_text(wikitext, expected):
    assert plain_text(wikitext) == expected


def test_plain_text_can_leave_entities_alone():
    assert plain_text("&amp;lt; &#39;", unescape=False) == "&amp;lt; &#39;"


# ---- hostile and random input ---------------------------------------------------------------

FRAGMENTS = [
    "{{", "}}", "{{Itempage", "|", "=", "statsblock", "itemname", "dropsfrom", "soldby", "relatedquests", "notes",
    "[[", "]]", "[", "]", "<br>", "<br/", "<!--", "-->", "<nowiki>", "</nowiki>", "&amp;", "&lt;", "&#", ";", "\n",
    "* ", "** ", "== ", " ==", "Slot: EAR", "Zorblax", " ", ":", "#REDIRECT ", "Category:", "{{{", "}}}", "'''", "<",
    ">", "\u200b", "\u202e", "\ud800", "\x00", "{{Item Lore|", "{{ItemWhereRow|", "http://x.invalid/ ", "javascript:",
]


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.sampled_from(FRAGMENTS), max_size=40).map("".join))
def test_random_fragments_never_raise_and_always_return_the_declared_types(content):
    result = parse(content)
    assert isinstance(result, (ParsedPage, Skip))
    if isinstance(result, ParsedPage):
        assert isinstance(result.name, str) and result.name
        assert all(isinstance(line, str) and line for line in result.statsblock_lines)
        assert result.statsblock_lines
        for drop in result.drops:
            assert drop["zone"] is None or (isinstance(drop["zone"], str) and drop["zone"])
            assert all(isinstance(npc, str) and npc for npc in drop["npcs"])
        assert all(isinstance(q, str) and q for q in result.quests)
        assert all(w["code"] and w["field"] for w in result.warnings)
    else:
        assert result.reason in SKIP_REASONS


@settings(max_examples=150, deadline=None)
@given(st.text(max_size=300))
def test_arbitrary_text_never_raises(content):
    assert isinstance(parse(content), (ParsedPage, Skip))
    wrapped = template(itemname=content, statsblock=content, dropsfrom=content, notes=content)
    assert isinstance(parse(wrapped), (ParsedPage, Skip))


def test_a_very_long_page_parses_in_reasonable_time():
    lines = "<br>\n".join(f"STR: +{n}" for n in range(3000))  # about 45,000 characters: the limit is 60,000
    result = parse(template(itemname="Zorblax Ring", statsblock=lines))
    assert isinstance(result, ParsedPage) and len(result.statsblock_lines) == 3000


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    st.lists(st.sampled_from(FRAGMENTS), max_size=25).map("".join),
    st.lists(st.sampled_from(FRAGMENTS), max_size=25).map("".join),
    st.lists(st.sampled_from(FRAGMENTS), max_size=25).map("".join),
)
def test_random_fragments_inside_a_real_template_never_raise(statsblock, sources, notes):
    content = template(
        itemname=sources,
        statsblock="Slot: EAR<br>" + statsblock,
        dropsfrom=sources,
        soldby=sources,
        relatedquests=sources,
        playercrafted=sources,
        focus_effect=sources,
        notes=notes,
        lucy_img_ID=sources,
    )
    result = parse(content)
    assert isinstance(result, (ParsedPage, Skip))
    if isinstance(result, ParsedPage):
        for sold in result.sold_by:
            assert sold["npc"] and (sold["zone"] is None or sold["zone"])
        for craft in result.crafted:
            assert craft["container"] is None or craft["container"]
            assert all(craft["ingredients"])
        assert all(result.focus_effects)
        assert all(tag.endswith(" Era") for tag in result.era_tags)


def test_notes_lore_needs_exactly_the_item_lore_template():
    assert parsed(notes="{{Item Lore Missing|nope}}").notes_lore is None
    assert parsed(notes="{{Item Lore Missing}}{{Item Lore|real lore}}").notes_lore == "real lore"
    assert parsed(notes="{{Some Other Template|stuff}}").notes_lore is None
    assert parsed(notes="{{Item Lore Extra|stuff}}").notes_lore is None


def test_notes_lore_with_an_equals_sign_in_the_text():
    assert parsed(notes="{{Item Lore|a = b}}").notes_lore == "a = b"
    assert parsed(notes="{{Item Lore|1=named one}}").notes_lore == "named one"


def test_plain_text_uses_the_target_when_the_label_is_blank():
    assert plain_text("[[Zorblax Keep|]] and [[Quuxen|  ]]") == "Zorblax Keep and Quuxen"


@pytest.mark.parametrize(
    ("wikitext", "plain", "with_parens"),
    [
        ("[[Zorblax Blast]]", "Zorblax Blast", "Zorblax Blast"),
        ("[[Zorblax_Blast_(Worn)|Label]] (Worn)", "Zorblax Blast", "Zorblax Blast (Worn)"),
        ("text [[File:A.png]] [[Category:Cat]] [[Quuxen#frag|Q]] [[Other]]", "Quuxen", "Quuxen"),
        ("[[:Zorblax]]", "Zorblax", "Zorblax"),
        ("[[Zorblax&amp;Co]]", "Zorblax&Co", "Zorblax&Co"),
    ],
)
def test_first_link_target(wikitext, plain, with_parens):
    assert first_link_target(wikitext) == plain
    assert first_link_target(wikitext, keep_parens=True) == with_parens


def test_first_link_target_without_a_link_or_with_only_namespaced_links():
    assert first_link_target("no links here") is None
    assert first_link_target("[[File:A.png|thumb]] [[Category:Cat]]") is None
    assert first_link_target("") is None


def test_first_link_target_decodes_entities_only_when_told_to():
    assert first_link_target("[[Zorblax &amp;lt; Co]]") == "Zorblax &lt; Co"
    assert first_link_target("[[Zorblax &amp;lt; Co]]", unescape=False) == "Zorblax &amp;lt; Co"


def test_link_target_strips_namespace_colon_fragment_underscores_and_the_parenthetical():
    assert link_target("Innoruuk_(God)") == "Innoruuk"
    assert link_target("Innoruuk_(God)", keep_parens=True) == "Innoruuk (God)"
    assert link_target(":Zorblax#History") == "Zorblax"
    assert link_target("(Only Parens)") == "(Only Parens)"  # never reduced to nothing
    assert link_target("A&amp;lt;B") == "A&lt;B"
    assert link_target("A&amp;lt;B", unescape=False) == "A&amp;lt;B"


def test_templates_and_comments_in_a_huge_statsblock_are_removed_in_linear_time():
    block = "Slot: EAR<br>" + "{{x|{{y}}}}" * 2000 + "<!-- c -->" * 2000 + "<br>AC: 5"
    start = time.perf_counter()
    result = parsed(statsblock=block)
    assert result.statsblock_lines == ["Slot: EAR", "AC: 5"]
    assert time.perf_counter() - start < 10  # quadratic removal took minutes
    # one warning per template, but a hostile page cannot make a million of them
    assert 1 <= len(result.warnings) <= 50


def test_templates_inside_tags_links_and_headings_in_the_statsblock_are_removed_too():
    block = (
        "<span>{{a}}Slot: EAR</span><br>[[Zorblax{{b}}|AC: {{c}}5]]<br>"
        "[https://example.invalid/x {{e}}Anchor]\n=={{d}} STR: +3 =="
    )
    result = parsed(statsblock=block)
    assert [w["code"] for w in result.warnings] == ["nested-template"] * 5
    assert "{{" not in "".join(result.statsblock_lines)


# ---- pathological markup ----------------------------------------------------------------------
# mwparserfromhell's tokenizer rescans the rest of the page from every opener that is never closed,
# so a few KB of "<br " or "{{a|" repeated takes seconds to minutes. Such a page is skipped, fast.

PATHOLOGICAL = {
    "unclosed tag attributes": "<br x=1 " * 5000,
    "unclosed span": "<span " * 5000,
    "unclosed template": "{{a|" * 5000,
    "unclosed argument": "{{{a|" * 5000,
    "unclosed link": "[[a|" * 5000,
    "unclosed external link": "[http://a " * 5000,
    "unclosed tag": "<span>" * 5000,
    "stray angle brackets": "<1x>" * 5000,  # "< a " is a lone "<" and parses fast; the tokenizer reads <1x> as a tag
}


def hostile_page(where, junk):
    params = {"itemname": "Zorblax Ring", "statsblock": "Slot: EAR"}
    suffix = ""
    if where == "statsblock":
        params["statsblock"] = "Slot: EAR<br>" + junk
    elif where == "dropsfrom":
        params["dropsfrom"] = junk
    else:
        suffix = "\n" + junk
    return template(**params) + suffix


@pytest.mark.parametrize("name", sorted(PATHOLOGICAL))
@pytest.mark.parametrize("where", ["statsblock", "dropsfrom", "page"])
def test_a_page_of_unbalanced_markup_is_skipped_quickly_not_parsed(name, where):
    start = time.perf_counter()
    result = parse(hostile_page(where, PATHOLOGICAL[name]))
    assert result == Skip(7, "Zorblax Ring", "too-complex")
    assert time.perf_counter() - start < 2


def test_a_few_unbalanced_openers_are_ordinary_typos_not_an_attack():
    # 3 unclosed "[", 1 "{{", 1 tag and 1 bare "<" are 6 in all: below the limit of 10
    junk = "{{ [[ [ <span> < a "
    result = parse(template(itemname="Zorblax Ring", statsblock="Slot: EAR") + "\n" + junk)
    assert isinstance(result, ParsedPage)


def test_balanced_markup_is_never_too_complex_however_much_of_it_there_is():
    rows = "".join("{{ItemWhereRow | [[Zorblax Keep]] | [[Vendor %d]] | | (0, 0) }}\n" % n for n in range(500))
    nested = "{{a|" * 500 + "}}" * 500
    soldby = "{{ItemWhereTable|" + rows + "}}"
    result = parse(template(itemname="Zorblax Ring", statsblock="Slot: EAR", soldby=soldby, notes=nested))
    assert isinstance(result, ParsedPage) and len(result.sold_by) == 500


def test_the_recorded_pages_have_no_unmatched_openers_at_all():
    for title in FIXTURE_TITLES:
        record = fixture(title)
        if not record.get("missing"):
            assert unmatched_openers(record["content"]) == 0, title


def test_unmatched_openers_adds_up_the_kinds():
    assert unmatched_openers("") == 0
    assert unmatched_openers("{{a|b}} [[c]] [d e] <span>x</span> <br> <br/> <!-- c --> 1 < 2") == 0  # a "<" before a space opens nothing
    assert unmatched_openers("{{ {{ {{ }}") == 2
    assert unmatched_openers("[[ [[ ]] ]] ]]") == 0
    assert unmatched_openers("[ [ [ ]") == 2
    assert unmatched_openers("<span> <span> </span>") == 1
    assert unmatched_openers("</span> </span>") == 0
    assert unmatched_openers("<br x=1 <br x=1 <br x=1 ") == 3
    assert unmatched_openers("}} ]] ] >") == 0
    assert unmatched_openers("{{ { [ <i> <b> <") == 4  # one "{{", one "[", two tags; the "<" at the end opens nothing


def test_an_oversized_page_is_skipped_as_too_large():
    start = time.perf_counter()
    result = parse("{{Itempage|statsblock=Slot: EAR}}" + " " * 200_000)
    assert result == Skip(7, "Zorblax Ring", "too-large")
    assert time.perf_counter() - start < 1
    assert isinstance(parse("{{Itempage|statsblock=Slot: EAR}}" + " " * 25_000), ParsedPage)  # the longest real page


def test_the_limit_is_60000_characters_exactly():
    head = "{{Itempage|statsblock=Slot: EAR}}"
    assert isinstance(parse(head + " " * (60_000 - len(head))), ParsedPage)
    assert parse(head + " " * (60_001 - len(head))) == Skip(7, "Zorblax Ring", "too-large")


def test_a_long_run_of_spaces_inside_a_source_line_does_not_stall_the_parser():
    start = time.perf_counter()
    # "= x", 100,000 spaces, "y": a heading pattern that finds no closing "=" tries every split of the spaces
    result = parse(template(itemname="Zorblax Ring", statsblock="Slot: EAR", dropsfrom="= x" + " " * 50_000 + "y"))
    assert isinstance(result, ParsedPage)
    assert result.drops == [{"zone": "= x y", "npcs": []}]
    assert time.perf_counter() - start < 2
    result = parse(template(itemname="Zorblax Ring", statsblock="Slot: EAR", dropsfrom="== x" + " " * 1000 + "=="))
    assert result.drops == [{"zone": "x", "npcs": []}]  # a real heading line is still a container line


# ---- parser fixes: duplicates, limits and structure ------------------------------------------------


def test_the_last_of_three_repeats_wins_and_names_match_loosely():
    result = parse("{{Itempage|ItemName=One|item_name=Two|statsblock=Slot: EAR|ITEM NAME=Three}}")
    assert result.name == "Three"
    assert warning_codes(result) == [("duplicate-param", "itemname")] * 2


def test_the_limit_is_ten_unclosed_openers_in_all_not_ten_of_each_kind():
    base = template(itemname="Zorblax Ring", statsblock="Slot: EAR") + "\n"
    assert isinstance(parse(base + "[ " * 10), ParsedPage)
    assert parse(base + "[ " * 11) == Skip(7, "Zorblax Ring", "too-complex")
    # braces, brackets, tags and bare angle brackets are added together: 4 + 4 + 4 + 4 = 16
    assert parse(base + "{{ {{ {{ {{ [ [ [ [ <span> <span> <span> <span> < < < <") == Skip(7, "Zorblax Ring", "too-complex")


@pytest.mark.parametrize("error", [RecursionError("maximum recursion depth exceeded"), mwparserfromhell.parser.ParserError("bad")])
def test_a_page_the_wikitext_parser_gives_up_on_is_skipped_as_too_complex_never_raised(monkeypatch, error):
    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(mwparserfromhell, "parse", broken)
    assert parse(template(itemname="Zorblax Ring", statsblock="Slot: EAR")) == Skip(7, "Zorblax Ring", "too-complex")


@pytest.mark.parametrize("depth", [50, 500, 5000])
@pytest.mark.parametrize(
    ("opener", "closer"),
    [("{{a|", "}}"), ("[[a|", "]]"), ("<span>", "</span>"), ("{{{a|", "}}}"), ("{{a|[[b|", "]]}}"), ("''", "''")],
)
def test_deeply_nested_balanced_markup_never_raises(opener, closer, depth):
    nest = opener * depth + "x" + closer * depth
    for where in ("statsblock", "dropsfrom", "notes", "page"):
        params = {"itemname": "Zorblax Ring", "statsblock": "Slot: EAR"}
        suffix = ""
        if where == "page":
            suffix = "\n" + nest
        else:
            params[where] = ("Slot: EAR<br>" if where == "statsblock" else "") + nest
        result = parse(template(**params) + suffix)
        assert isinstance(result, (ParsedPage, Skip))


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    st.sampled_from(["{{", "[[", "{{{", "<span>", "[", "<b><i>"]),
    st.integers(min_value=1, max_value=2500),
    st.sampled_from(["statsblock", "dropsfrom", "soldby", "relatedquests", "playercrafted", "page"]),
)
def test_parse_page_never_raises_on_deeply_nested_markup(opener, depth, where):
    closers = {"{{": "}}", "[[": "]]", "{{{": "}}}", "<span>": "</span>", "[": "]", "<b><i>": "</i></b>"}
    nest = opener * depth + "x" + closers[opener] * depth
    params = {"itemname": "Zorblax Ring", "statsblock": "Slot: EAR"}
    suffix = ""
    if where == "page":
        suffix = "\n" + nest
    else:
        params[where] = nest
    assert isinstance(parse(template(**params) + suffix), (ParsedPage, Skip))


# -- several zones, vendors or containers on one line


def test_npc_bullets_under_a_comma_separated_zone_line_belong_to_every_zone_of_the_line():
    dropsfrom = "[[Zorblax Keep]], [[Quuxen Hollow]], [[Blarg Pass]]\n* [[A]]\n* [[B]]\n[[Other Zone]]\n* [[C]]"
    assert parsed(dropsfrom=dropsfrom).drops == [
        {"zone": "Zorblax Keep", "npcs": ["A", "B"]},
        {"zone": "Quuxen Hollow", "npcs": ["A", "B"]},
        {"zone": "Blarg Pass", "npcs": ["A", "B"]},
        {"zone": "Other Zone", "npcs": ["C"]},
    ]
    # the same for zones written as plain text
    assert parsed(dropsfrom="Zone One, Zone Two\n* [[A]]").drops == [
        {"zone": "Zone One", "npcs": ["A"]},
        {"zone": "Zone Two", "npcs": ["A"]},
    ]


def test_a_line_that_names_no_zone_leaves_the_bullets_with_the_zones_before_it():
    dropsfrom = "[[Zorblax Keep]], [[Quuxen Hollow]]\n<!-- note -->\n* [[A]]"
    assert parsed(dropsfrom=dropsfrom).drops == [
        {"zone": "Zorblax Keep", "npcs": ["A"]},
        {"zone": "Quuxen Hollow", "npcs": ["A"]},
    ]


def test_vendor_bullets_under_a_multi_zone_line_belong_to_every_zone():
    soldby = "[[Zorblax Keep]], [[Quuxen Hollow]]\n* [[Vendor One]]\n* [[Vendor Two]]\n[[Blarg Pass]]\n* [[Vendor Three]]"
    assert parsed(soldby=soldby).sold_by == [
        {"zone": "Zorblax Keep", "npc": "Vendor One"},
        {"zone": "Zorblax Keep", "npc": "Vendor Two"},
        {"zone": "Quuxen Hollow", "npc": "Vendor One"},
        {"zone": "Quuxen Hollow", "npc": "Vendor Two"},
        {"zone": "Blarg Pass", "npc": "Vendor Three"},
    ]


def test_a_vendor_row_keeps_every_vendor_and_every_zone_it_names():
    soldby = (
        "{{ItemWhereTable|\n"
        "{{ItemWhereRow | [[Zorblax Keep]], [[Quuxen Hollow]] | [[Vendor One]], [[Vendor Two]] | | (0, 0) }}\n"
        "{{ItemWhereRow | Plain Zone A, Plain Zone B | [[Vendor Three]] | | (0, 0) }}\n"
        "}}"
    )
    assert parsed(soldby=soldby).sold_by == [
        {"zone": "Zorblax Keep", "npc": "Vendor One"},
        {"zone": "Zorblax Keep", "npc": "Vendor Two"},
        {"zone": "Quuxen Hollow", "npc": "Vendor One"},
        {"zone": "Quuxen Hollow", "npc": "Vendor Two"},
        {"zone": "Plain Zone A", "npc": "Vendor Three"},
        {"zone": "Plain Zone B", "npc": "Vendor Three"},
    ]


def test_a_vendor_row_with_no_zone_still_gives_each_vendor():
    soldby = "{{ItemWhereTable|{{ItemWhereRow |  | [[Vendor One]], [[Vendor Two]] | | (0, 0) }}}}"
    assert parsed(soldby=soldby).sold_by == [{"zone": None, "npc": "Vendor One"}, {"zone": None, "npc": "Vendor Two"}]


def test_ingredient_bullets_under_a_multi_container_line_of_a_plain_outline_belong_to_every_container():
    result = parsed(crafted="* [[Forge]], [[Kiln]]\n** [[Zorblax Ore]]\n** [[Quuxen Dust]]\n* [[Oven]]\n** [[Blarg Flour]]")
    assert result.crafted == [
        {"container": "Forge", "ingredients": ["Zorblax Ore", "Quuxen Dust"]},
        {"container": "Kiln", "ingredients": ["Zorblax Ore", "Quuxen Dust"]},
        {"container": "Oven", "ingredients": ["Blarg Flour"]},
    ]


def test_one_subheading_does_not_demote_the_level_one_bullets_of_an_outline():
    result = parsed(crafted="=== Recipes ===\n* [[Forge]]\n** [[Zorblax Ore]]\n* [[Kiln]]\n** [[Blarg Clay]]")
    assert result.crafted == [
        {"container": "Forge", "ingredients": ["Zorblax Ore"]},
        {"container": "Kiln", "ingredients": ["Blarg Clay"]},
    ]


def test_subheadings_are_containers_only_when_the_bullets_under_them_are_all_one_level():
    result = parsed(crafted="=== Forge ===\n* [[Zorblax Ore]]\n=== Kiln ===\n* [[Blarg Clay]]")
    assert result.crafted == [
        {"container": "Forge", "ingredients": ["Zorblax Ore"]},
        {"container": "Kiln", "ingredients": ["Blarg Clay"]},
    ]


def test_an_ingredient_is_deeper_than_the_skill_line_of_its_own_recipe_whatever_that_depth():
    crafted = (
        "* Recipe one\n"
        "** [[Blacksmithing]] (Trivial: 100)\n"
        "*** In [[Forge]]:\n"
        "*** [[Zorblax Ore]]\n"
        "** [[A link that is a sibling of the skill line]]\n"
    )
    assert parsed(playercrafted=crafted).crafted == [{"container": "Forge", "ingredients": ["Zorblax Ore"]}]


def test_a_level_one_skill_line_still_takes_the_bullets_below_it_as_ingredients():
    crafted = "* [[Alchemy]]\n** [[5 Dose Zorblax Potion]]\n* [[Baking]]\n** [[Quuxen Dough]]\n"
    assert parsed(playercrafted=crafted).crafted == [
        {"container": None, "ingredients": ["5 Dose Zorblax Potion"]},
        {"container": None, "ingredients": ["Quuxen Dough"]},
    ]


def test_a_second_recipe_in_the_same_container_list_after_a_heading_stays_separate():
    crafted = "=== Recipes ===\n* [[Tailoring]]\n** In [[Loom]]:\n:: 1 x [[Quuxen Silk]]\n* [[Smithing]]\n** In [[Forge]]:\n:: 1 x [[Ore One]]\n"
    assert parsed(playercrafted=crafted).crafted == [
        {"container": "Loom", "ingredients": ["Quuxen Silk"]},
        {"container": "Forge", "ingredients": ["Ore One"]},
    ]


# -- templates inside tags


def test_wrapper_templates_inside_html_tags_are_unwrapped():
    dropsfrom = "<span>{{VeliousGray| [[Zorblax Keep]] }}</span>\n* <b>{{VeliousGray| [[A]] }}</b>\n* <i><u>{{Other|[[B]]}}</u></i>"
    assert parsed(dropsfrom=dropsfrom).drops == [{"zone": "Zorblax Keep", "npcs": ["A", "B"]}]


def test_vendor_rows_inside_html_tags_are_collected():
    soldby = (
        "<div>{{ItemWhereTable|\n"
        "{{ItemWhereRow | [[Zorblax Keep]] | [[Vendor One]] | | (0, 0) }}\n"
        "<span>{{ItemWhereRowVel| [[Quuxen Hollow]] | [[Vendor Two]] | | (1, 1) }}</span>\n"
        "}}</div>"
    )
    assert parsed(soldby=soldby).sold_by == [
        {"zone": "Zorblax Keep", "npc": "Vendor One"},
        {"zone": "Quuxen Hollow", "npc": "Vendor Two"},
    ]


def test_a_nowiki_section_is_not_unwrapped_as_a_template():
    drops = parsed(dropsfrom="<nowiki>{{VeliousGray| [[Zorblax Keep]] }}</nowiki>").drops
    assert drops == [{"zone": "{{VeliousGray| [[Zorblax Keep]] }}", "npcs": []}]  # literal text, as typed


# -- notes in a drop list


def test_note_lines_in_a_drop_list_are_not_zones():
    dropsfrom = "None\nN O T _ C L A S S I C \n<u>Located in the following locations:</u><br>\n[[Cabilis]]<br>\n[[Erudin]]<br>"
    result = parsed(dropsfrom=dropsfrom)
    assert result.drops == [{"zone": "Cabilis", "npcs": []}, {"zone": "Erudin", "npcs": []}]
    assert result.page_flags == []


@pytest.mark.parametrize("line", ["none", "NONE", "Located in the following locations", "n o t _ c l a s s i c", "not classic"])
def test_a_note_line_is_found_whatever_its_case_spacing_and_punctuation(line):
    assert parsed(dropsfrom=line + "\n[[Zorblax Keep]]").drops == [{"zone": "Zorblax Keep", "npcs": []}]


def test_a_parenthetical_only_line_is_a_note_on_the_zone_before_it():
    dropsfrom = "[[Temple of Veeshan]]\n(ToV East mobs)\n \n*    [[an ancient wurm]]\n(only on Tuesdays)\n[[Other Zone]]\n* [[A]]"
    assert parsed(dropsfrom=dropsfrom).drops == [
        {"zone": "Temple of Veeshan", "npcs": ["an ancient wurm"], "notes": ["ToV East mobs", "only on Tuesdays"]},
        {"zone": "Other Zone", "npcs": ["A"]},
    ]


def test_a_note_on_a_multi_zone_line_belongs_to_each_of_its_zones():
    drops = parsed(dropsfrom="[[Zorblax Keep]], [[Quuxen Hollow]]\n(rare)\n* [[A]]").drops
    assert drops == [
        {"zone": "Zorblax Keep", "npcs": ["A"], "notes": ["rare"]},
        {"zone": "Quuxen Hollow", "npcs": ["A"], "notes": ["rare"]},
    ]


def test_a_parenthetical_line_before_any_zone_is_dropped():
    assert parsed(dropsfrom="(a note)\n[[Zorblax Keep]]").drops == [{"zone": "Zorblax Keep", "npcs": []}]


def test_a_zone_that_is_only_a_parenthesis_inside_a_link_label_is_still_a_zone():
    assert parsed(dropsfrom="[[Zorblax Keep|(Upper)]]").drops == [{"zone": "(Upper)", "npcs": []}]


def test_item_removed_from_game_in_the_drop_list_sets_the_removed_note_flag():
    result = parsed(dropsfrom="\nITEM REMOVED FROM GAME\n")
    assert result.drops == [] and result.page_flags == ["removed_note"]
    assert parsed(dropsfrom="Item removed from game.\n[[Zorblax Keep]]").page_flags == ["removed_note"]
    assert parsed(dropsfrom="[[Zorblax Keep]]").page_flags == []


# -- banners


@pytest.mark.parametrize(
    ("banner", "flag"),
    [
        ("{{Delete}}", "wiki_banner_delete"),
        ("{{delete}}", "wiki_banner_delete"),
        ("{{delete|no longer present}}", "wiki_banner_delete"),
        ("{{ DELETE }}", "wiki_banner_delete"),
        ("{{:Does Not Exist}}", "wiki_banner_does_not_exist"),
        ("{{: Does Not Exist}}", "wiki_banner_does_not_exist"),
        ("{{Does_Not_Exist}}", "wiki_banner_does_not_exist"),
        ("{{DNE}}", "wiki_banner_dne"),
        ("{{dne}}", "wiki_banner_dne"),
        ("{{revamped}}", "wiki_banner_revamped"),
        ("{{Revamped}}", "wiki_banner_revamped"),
        ("{{Template:Revamped}}", "wiki_banner_revamped"),
    ],
)
def test_a_banner_template_sets_its_wiki_banner_flag(banner, flag):
    result = parse(banner + " Replaced in EQL\n\n" + template(itemname="Zorblax Ring", statsblock="Slot: EAR"))
    assert isinstance(result, ParsedPage)
    assert result.page_flags == [flag]


def test_several_banners_give_several_flags_in_sorted_order():
    result = parse("{{delete}}{{DNE}}{{revamped}}\n" + template(itemname="Zorblax Ring", statsblock="Slot: EAR"))
    assert result.page_flags == ["wiki_banner_delete", "wiki_banner_dne", "wiki_banner_revamped"]
    assert parse("{{DNE}}{{delete}}{{delete}}\n" + template(statsblock="Slot: EAR")).page_flags == ["wiki_banner_delete", "wiki_banner_dne"]


def test_a_page_without_a_banner_has_no_page_flags():
    assert parsed().page_flags == []
    assert parse("{{Classic Era}}\n" + template(statsblock="Slot: EAR")).page_flags == []


@pytest.mark.parametrize(
    "wrapper",
    ["<!-- {{Delete}} -->", "<nowiki>{{Delete}}</nowiki>", "<pre>{{Delete}}</pre>"],
)
def test_a_banner_in_a_comment_or_nowiki_is_no_banner(wrapper):
    assert parse(wrapper + "\n" + template(itemname="Zorblax Ring", statsblock="Slot: EAR")).page_flags == []


def test_a_banner_inside_a_template_parameter_is_no_banner_of_the_page():
    assert parsed(notes="{{Delete}} see the talk page").page_flags == []


def test_a_banner_inside_a_tag_that_wraps_the_page_counts():
    code = "<div>{{Delete}}</div>\n<onlyinclude>" + template(itemname="Zorblax Ring", statsblock="Slot: EAR") + "</onlyinclude>"
    assert parse(code).page_flags == ["wiki_banner_delete"]


# -- categories and namespaces


def test_categories_are_read_wherever_they_stand_in_a_template_parameter_or_a_tag_or_at_the_top():
    # this reverses the first rule, which read only top-level links: a page may end its template after its categories
    code = (
        template(itemname="Zorblax Ring", statsblock="Slot: EAR", notes="See [[Category:Hidden In A Parameter]]")
        + "\n[[Category:Ear]]\n<onlyinclude>[[Category:Inside A Tag]]</onlyinclude>\n{{Other|[[Category:Inside Another Template]]}}"
    )
    assert parse(code).categories == ["Hidden In A Parameter", "Ear", "Inside A Tag", "Inside Another Template"]


def test_a_category_link_in_a_comment_or_nowiki_is_no_category():
    code = template(itemname="Zorblax Ring", statsblock="Slot: EAR") + "\n<!-- [[Category:Commented]] -->\n<nowiki>[[Category:Escaped]]</nowiki>"
    assert parse(code).categories == []


@pytest.mark.parametrize(
    "link",
    ["[[Category:Zorblax]]", "[[category:Zorblax]]", "[[ Category : Zorblax ]]", "[[Category_:Zorblax]]", "[[_Category_: Zorblax]]"],
)
def test_the_category_prefix_may_have_spaces_and_underscores_around_the_colon(link):
    code = template(itemname="Zorblax Ring", statsblock="Slot: EAR") + "\n" + link
    assert parse(code).categories == ["Zorblax"]


@pytest.mark.parametrize("link", ["[[:Category:Zorblax]]", "[[: Category:Zorblax]]"])
def test_a_link_with_a_leading_colon_is_a_link_to_the_category_not_a_category(link):
    code = template(itemname="Zorblax Ring", statsblock="Slot: EAR") + "\n" + link
    assert parse(code).categories == []


@pytest.mark.parametrize("prefix", ["File", "file", " File ", "File_", "Image", "Media", "Category", "Category_"])
def test_a_namespaced_link_names_nothing(prefix):
    assert parsed(dropsfrom=f"[[Zorblax Keep]]\n* [[{prefix}:Boss.png|thumb]]\n* [[A]]").drops == [{"zone": "Zorblax Keep", "npcs": ["A"]}]
    assert plain_text(f"x [[{prefix}:Boss.png]] y") == "x y"


def test_a_link_with_a_leading_colon_names_something():
    assert parsed(dropsfrom="[[Zorblax Keep]]\n* [[:File:Boss.png]]").drops == [{"zone": "Zorblax Keep", "npcs": ["File:Boss.png"]}]


# -- script links hidden in entities: decode first, then neutralize


@pytest.mark.parametrize(
    "wikitext",
    [
        "[javascript:alert(1) Evil]",
        "[javascript&#58;alert(1) Evil]",
        "[javascript&colon;alert(1) Evil]",
        "[javascript&#x3a;alert(1) Evil]",
        "[java&#115;cript:alert(1) Evil]",
        "[&#106;avascript:alert(1) Evil]",
        "&#91;javascript:alert(1) Evil&#93;",
        "[data&#58;text/html,hi Evil]",
        "[ vbscript&#58;msgbox(1) Evil]",
    ],
)
def test_a_script_link_hidden_in_entities_keeps_only_its_anchor_text(wikitext):
    assert plain_text(wikitext) == "Evil"
    (drop,) = parsed(dropsfrom="[[Zorblax Keep]]\n* " + wikitext).drops
    assert drop["npcs"] == ["Evil"]
    assert parsed(relatedquests="* " + wikitext).quests == ["Evil"]
    assert parse(template(itemname=wikitext, statsblock="Slot: EAR")).name == "Evil"


def test_an_entity_is_decoded_exactly_once_before_the_script_link_check():
    # &amp;#115; is the text "&#115;" after one decoding: not a letter, so not a script link, and not decoded again
    assert plain_text("[java&amp;#115;cript:alert(1) Evil]") == "[java&#115;cript:alert(1) Evil]"
    assert plain_text("[javascript&amp;#58;alert(1) Evil]") == "[javascript&#58;alert(1) Evil]"


def test_the_text_of_a_script_link_without_anchor_leaves_nothing():
    assert plain_text("a [javascript&#58;alert(1)] b") == "a b"


def test_a_line_with_words_between_two_parentheses_is_not_a_note():
    assert [d["zone"] for d in parsed(dropsfrom="(Upper) Zorblax Keep (Lower)").drops] == ["(Upper) Zorblax Keep (Lower)"]
    assert parsed(dropsfrom="[[Zorblax Keep]]\n(rare (north gate))").drops == [{"zone": "Zorblax Keep", "npcs": []}, {"zone": "(rare (north gate))", "npcs": []}]
    assert parsed(dropsfrom="[[Zorblax Keep]]\n  ''(rare)''  ").drops == [{"zone": "Zorblax Keep", "npcs": [], "notes": ["rare"]}]
