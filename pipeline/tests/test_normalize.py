"""Tests for the statsblock parser, the sanitizer and the catalog item normalizer.

Pages are the recorded fixtures (real eqlwiki text, see fixtures/wiki/README.md) or are built
here from invented names (Zorblax and friends).
"""

import copy
import json
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator, ValidationError

from trioforge.data.normalize import (
    CLASS_CODES,
    DEITIES,
    EFFECT_KINDS,
    FLAGS,
    ITEM_TYPE_SOURCES,
    RACE_CODES,
    SCHEMA_PATH,
    SIZES,
    SLOTS,
    STAT_KEYS,
    SV_KEYS,
    TIER_RULES,
    WARNING_CODES,
    normalize,
    sanitize_text,
    validate_item,
    weapon_incomplete,
)
from trioforge.sources.eqlwiki import fixture_slug, page_records
from trioforge.sources.itempage import ParsedPage, parse_page

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures" / "wiki"
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

# Written out here on purpose, so these tests do not trust the constants they check.
ALL_CLASSES = "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER".split()
ALL_RACES = "HUM BAR ERU ELF HIE DEF HEF DWF TRL OGR HFL GNM IKS KER FRG HDE".split()
FORBIDDEN_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Zl", "Zp"}


def fixture_page(title):
    path = FIXTURES / f"{fixture_slug(title)}.json"
    (record,) = page_records(json.loads(path.read_text(encoding="utf-8")))
    return record


def fixture_item(title):
    parsed = parse_page(fixture_page(title))
    assert isinstance(parsed, ParsedPage), title
    item = normalize(parsed)
    validate_item(item)
    return item


def template(**params):
    return "{{Itempage\n" + "".join(f"|{name}={value}\n" for name, value in params.items()) + "}}"


def parsed_page(statsblock, **params):
    params = {"itemname": "Zorblax Ring", **params}
    page = {
        "pageid": 7,
        "ns": 0,
        "title": "Zorblax Ring",
        "revid": 70,
        "content": template(statsblock=statsblock, **params),
    }
    result = parse_page(page)
    assert isinstance(result, ParsedPage), result
    return result


def item_from(statsblock, **params):
    """Normalize a synthetic page; every item built here must validate against the schema."""
    item = normalize(parsed_page(statsblock, **params))
    validate_item(item)
    return item


def lines(*statsblock_lines):
    return "<br>\n".join(statsblock_lines)


def warnings_of(item):
    return [(w["code"], w["field"]) for w in item["parse_warnings"]]


def all_strings(value):
    """Every string in a nested structure, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, inner in value.items():
            yield from all_strings(key)
            yield from all_strings(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from all_strings(inner)


def assert_clean(item):
    """No string in the item holds an angle bracket, a forbidden character or more than 200 characters."""
    for text in all_strings(item):
        assert len(text) <= 200
        for char in text:
            assert char not in "<>", text
            assert unicodedata.category(char) not in FORBIDDEN_CATEGORIES, (text, hex(ord(char)))


# ---- sanitize_text ----------------------------------------------------------------------------


def test_sanitize_removes_angle_brackets_and_keeps_the_text():
    assert sanitize_text("Ring<script>alert(1)</script>") == "Ringscriptalert(1)/script"


def test_sanitize_removes_bidi_and_zero_width_characters():
    assert sanitize_text("Ri\u202eng") == "Ring"
    assert sanitize_text("Ri\u200bng") == "Ring"
    assert sanitize_text("\ufeffRi\u2066n\u2069g\u200d\u200c\u200e\u200f\u061c\u00ad") == "Ring"


def test_sanitize_turns_whitespace_controls_into_a_space_and_drops_the_other_controls():
    assert sanitize_text("a\tb\nc\rd\x0be\x85f") == "a b c d e f"
    assert sanitize_text("a\x00b\x07c\x1bd\x7fe\x9ff") == "abcdef"


def test_sanitize_applies_nfkc_before_everything_else():
    assert sanitize_text("\uff21\uff22\uff23 \ufb01 a\u00a0b") == "ABC fi a b"
    # fullwidth and small angle brackets become real ones under NFKC, and are then removed
    assert sanitize_text("\uff1cscript\uff1e") == "script"
    assert sanitize_text("\ufe64x\ufe65") == "x"


def test_sanitize_drops_line_separators_surrogates_and_private_use():
    assert sanitize_text("a\u2028b\u2029c") == "abc"
    assert sanitize_text("a\ud800b\udfffc") == "abc"
    assert sanitize_text("a\ue000b\uf8ffc") == "abc"
    assert sanitize_text("a\U000f0000b") == "ab"


def test_sanitize_collapses_and_strips_whitespace():
    assert sanitize_text("  a   b \n\t c  ") == "a b c"
    assert sanitize_text("   ") == ""
    assert sanitize_text("") == ""


def test_sanitize_caps_at_200_characters_and_leaves_no_trailing_space():
    assert sanitize_text("x" * 300) == "x" * 200
    assert sanitize_text("x" * 199 + " y") == "x" * 199
    assert len(sanitize_text("\u00e9" * 500)) == 200


def test_sanitize_passes_none_through():
    assert sanitize_text(None) is None


def test_sanitize_keeps_quotes_equals_and_ordinary_punctuation():
    text = "Zorblax's \"Ring\" a=b & (c) [d] {e} 100% #1 \u00e9\u4e2d"
    assert sanitize_text(text) == text


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=400))
def test_sanitize_is_idempotent_and_its_output_is_clean(text):
    once = sanitize_text(text)
    assert sanitize_text(once) == once
    assert len(once) <= 200 and once == once.strip() and "  " not in once
    for char in once:
        assert char not in "<>" and unicodedata.category(char) not in FORBIDDEN_CATEGORIES


def test_the_allowed_set_is_printable_unicode_minus_the_angle_brackets():
    """Whatever code point goes in, what comes out is printable text and a fixed point.

    Printable is Python's own definition (str.isprintable): no control, format, separator, surrogate,
    private-use or unassigned character, and the only blank is the ASCII space. The rule is written once,
    here, as that one property, not as the sanitizer's category list again, so a category or a Unicode
    update that lets something through shows up.
    """
    stride = 1
    checked = 0
    for codepoint in range(0x110000):
        if codepoint > 0xFFFF:
            stride = 13
        if stride > 1 and codepoint % stride:
            continue
        checked += 1
        char = chr(codepoint)
        result = sanitize_text("a" + char + "b")
        assert result.endswith("b"), hex(codepoint)  # the text around the character survives
        assert all(each.isprintable() and each not in "<>" for each in result), hex(codepoint)
        assert sanitize_text(result) == result, hex(codepoint)
    assert checked > 140_000  # every BMP code point and every 13th beyond it


def test_unassigned_and_non_character_code_points_are_dropped():
    assert sanitize_text("a\u0378b") == "ab"  # unassigned
    assert sanitize_text("a\ufffeb\uffffc") == "abc"  # non-characters
    assert sanitize_text("a\ufdd0b\ufdefc") == "abc"
    assert sanitize_text("a\U0010ffffb") == "ab"
    assert sanitize_text("a\U000e0001b") == "ab"  # a language tag (format)


def test_sanitizing_runs_nfkc_again_after_the_removals():
    # removing the zero-width space lets the base letter and the combining acute accent meet: NFKC joins them
    # on the second pass, and the result is the same as for the text typed without the space
    assert sanitize_text("e\u200b\u0301") == sanitize_text("e\u0301") == "\u00e9"
    assert sanitize_text("\u1100\u200b\u1161") == sanitize_text("\u1100\u1161")  # Hangul jamo become a syllable
    once = sanitize_text("a\u200b\u0308\u200b\u0301b")
    assert sanitize_text(once) == once


MARKS_AND_INVISIBLES = ["e", "a", "\u0301", "\u0308", "\u200b", "\u00ad", "\u0300", "\u1100", "\u1161", "<", ">", " ", "\ufeff"]


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet=st.sampled_from(MARKS_AND_INVISIBLES), max_size=40))
def test_sanitizing_text_made_of_marks_and_invisible_characters_is_a_fixed_point(text):
    once = sanitize_text(text)
    assert sanitize_text(once) == once
    assert all(each.isprintable() and each not in "<>" for each in once)


# ---- the statsblock table ---------------------------------------------------------------------


def test_lore_equipped_no_trade():
    assert item_from("Lore Equipped, No Trade")["flags"] == ["lore", "no_trade"]


def test_magic_lore_no_drop():
    assert item_from("MAGIC ITEM  LORE ITEM  NO DROP")["flags"] == ["lore", "no_drop", "magic"]


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ("Slot: PRIMARY SECONDARY", ["PRIMARY", "SECONDARY"]),
        ("Slot: SECONDARY PRIMARY", ["PRIMARY", "SECONDARY"]),
        ("Slot: PRIMARY  SECONDARY", ["PRIMARY", "SECONDARY"]),
        ("Slot: EAR", ["EAR"]),
        ("Slot: EARS", ["EAR"]),
        ("Slot: FINGERS", ["FINGER"]),
        ("Slot: SHOULDER", ["SHOULDERS"]),
        ("Slot: WRISTS", ["WRIST"]),
        ("Slot: finger", ["FINGER"]),
        ("slot: Neck", ["NECK"]),
        ("Slot: FINGER FINGER", ["FINGER"]),
        ("Slot: BACK WAIST", ["BACK", "WAIST"]),
        ("Slot: power source", ["POWERSOURCE"]),
        ("Slot: POWERSOURCE", ["POWERSOURCE"]),
        ("Slot: RANGE AMMO CHARM", ["RANGE", "AMMO", "CHARM"]),
        ("Slot: HEAD FACE ARMS HANDS CHEST LEGS FEET", ["HEAD", "FACE", "ARMS", "HANDS", "CHEST", "LEGS", "FEET"]),
    ],
)
def test_slots(block, expected):
    item = item_from(block)
    assert item["slots"] == expected
    assert item["parse_warnings"] == []


def test_an_augment_slot_is_not_wearable():
    for word in ("AUG", "AUGMENT", "aug"):
        item = item_from(f"Slot: {word}")
        assert item["slots"] == []
        assert warnings_of(item) == [("augment-slot", "slot")]


def test_an_unknown_slot_word_is_a_warning_and_the_known_ones_stay():
    item = item_from("Slot: BACK ZORBLAX")
    assert item["slots"] == ["BACK"]
    assert warnings_of(item) == [("unknown-slot", "slot")]


def test_slots_are_sorted_in_the_canonical_order():
    item = item_from("Slot: SECONDARY FEET HEAD PRIMARY")
    assert item["slots"] == ["HEAD", "FEET", "PRIMARY", "SECONDARY"]
    assert item["slots"] == [slot for slot in SLOTS if slot in item["slots"]]


def test_no_slot_line_means_no_slots():
    assert item_from("Quest")["slots"] == []


def test_ac():
    assert item_from("AC: 20")["stats"] == {"AC": 20}


def test_several_stats_on_a_line():
    assert item_from("STR: +5  STA: +5  INT: +5")["stats"] == {"STR": 5, "STA": 5, "INT": 5}


def test_a_negative_stat():
    assert item_from("STR: -3")["stats"] == {"STR": -3}


def test_hp_mana_end():
    assert item_from("HP: +5  MANA: +20  END: +20")["stats"] == {"HP": 5, "MANA": 20, "END": 20}


def test_resists():
    item = item_from("SV FIRE: +10  SV COLD: +5")
    assert item["sv"] == {"FIRE": 10, "COLD": 5}
    assert item["stats"] == {}


def test_every_resist_school():
    item = item_from("SV CORRUPTION: +1  SV DISEASE: +2  SV POISON: +3  SV MAGIC: +4  SV COLD: +5  SV FIRE: +6")
    assert item["sv"] == {"FIRE": 6, "COLD": 5, "MAGIC": 4, "POISON": 3, "DISEASE": 2, "CORRUPTION": 1}
    assert list(item["sv"]) == ["FIRE", "COLD", "MAGIC", "POISON", "DISEASE", "CORRUPTION"]


def test_haste():
    assert item_from("Haste: +41%")["stats"] == {"HASTE": 41}
    assert item_from("Haste: 41")["stats"] == {"HASTE": 41}
    assert item_from("HASTE: +36%  ")["stats"] == {"HASTE": 36}


@pytest.mark.parametrize("block", ["Attack: +5", "ATK: +5", "atk: 5", "attack: +5"])
def test_attack(block):
    assert item_from(block)["stats"] == {"ATK": 5}


def test_regen():
    assert item_from("HP Regen: +2  Mana Regen: +1")["stats"] == {"HPREG": 2, "MANAREG": 1}
    assert item_from("HP Regen: 2  Mana Regen: 2  End Regen: 2 ")["stats"] == {"HPREG": 2, "MANAREG": 2, "ENDREG": 2}


def test_a_weapon():
    item = item_from(lines("Skill: 1H Slashing  Atk Delay: 30", "DMG: 12"))
    assert item["weapon"] == {"skill": "1H Slashing", "dmg": 12, "delay": 30, "bonus": None}


@pytest.mark.parametrize(
    "block",
    [
        "Skill: 2H Slashing ATK Delay: 44<br>DMG: 33  DMG Bonus: 20",
        "skill: 2H Slashing  atk delay: 44<br>dmg: 33  dmg bonus: 20",
        "Skill: 2H Slashing<br>Atk Delay: 44<br>DMG: 33<br>DMG Bonus: 20",
        "DMG: 33  DMG Bonus: 20<br>Skill: 2H Slashing  Attack Delay: 44",
        "Skill:  2H   Slashing   ATK  Delay:  44  DMG:  33   DMG  Bonus:  20",
    ],
)
def test_weapon_spellings(block):
    assert item_from(block)["weapon"] == {"skill": "2H Slashing", "dmg": 33, "delay": 44, "bonus": 20}


def test_an_instrument_skill_goes_to_the_weapon():
    item = item_from("Skill: Brass Instruments")
    assert item["weapon"] == {"skill": "Brass Instruments", "dmg": None, "delay": None, "bonus": None}


def test_no_weapon_lines_no_weapon():
    assert item_from("Slot: EAR")["weapon"] is None


def test_size_and_weight():
    item = item_from("Size: TINY  WT: 0.1")
    assert (item["size"], item["weight"]) == ("TINY", 0.1)
    item = item_from("WT: 12.5  Size: giant")
    assert (item["size"], item["weight"]) == ("GIANT", 12.5)
    assert item_from("WT: 7")["weight"] == 7.0


def test_class_all():
    assert item_from("Class: ALL")["classes"] == ["ALL"]


def test_class_all_except_one():
    item = item_from("Class: ALL except WAR")
    assert item["classes"] == [code for code in ALL_CLASSES if code != "WAR"]
    assert len(item["classes"]) == 15


def test_class_all_except_several():
    item = item_from("Class: ALL except CLR PAL DRU MNK SHM")
    assert item["classes"] == "WAR RNG SHD BRD ROG NEC WIZ MAG ENC BST BER".split()
    item = item_from("Class: all EXCEPT war, clr")
    assert item["classes"] == [code for code in ALL_CLASSES if code not in ("WAR", "CLR")]


def test_race_all_except_one():
    item = item_from("Race: ALL except HUM")
    assert item["races"] == ALL_RACES[1:]
    assert item_from("Race: ALL")["races"] == ["ALL"]


@pytest.mark.parametrize(
    "block",
    ["Class: WAR CLR PAL", "Class: WAR, CLR, PAL", "Class: war clr pal", "Class: PAL CLR WAR", "Class:WAR/CLR/PAL"],
)
def test_class_lists_come_out_in_class_id_order(block):
    assert item_from(block)["classes"] == ["WAR", "CLR", "PAL"]


def test_every_class_listed_is_all():
    assert item_from("Class: " + " ".join(ALL_CLASSES))["classes"] == ["ALL"]
    assert item_from("Race: " + " ".join(ALL_RACES))["races"] == ["ALL"]


def test_a_race_list_of_the_fifteen_older_races_is_all_because_such_a_page_predates_the_sixteenth():
    """F7: with the Half Dark Elf in the race codes, a page written before the race that names every other race would no longer be ALL, and the new race could wear none of its items.
    A list that holds every race but HDE is ALL (a rule with a note: the pages predate the race, and whether the item is usable by it in the game is unverified); the rest is as it was."""
    older = [code for code in ALL_RACES if code != "HDE"]
    assert len(older) == 15
    assert item_from("Race: " + " ".join(older))["races"] == ["ALL"]
    assert item_from("Race: " + ", ".join(reversed(older)))["races"] == ["ALL"]  # (in any order)
    assert item_from("Race: " + " ".join(ALL_RACES))["races"] == ["ALL"]  # (all sixteen, as before)
    assert item_from("Race: ALL except HDE")["races"] == older  # (an exclusion the page makes itself is not a gap of its time)
    assert item_from("Race: " + " ".join(older[1:]))["races"] == older[1:]  # (fourteen of the fifteen is a list)
    assert item_from("Race: HDE")["races"] == ["HDE"]
    assert item_from("Class: " + " ".join(ALL_CLASSES[1:]))["classes"] == ALL_CLASSES[1:]  # (the rule is the races')


def test_missing_class_and_race_lines_mean_all():
    item = item_from("Slot: EAR")
    assert (item["classes"], item["races"]) == (["ALL"], ["ALL"])
    assert item["parse_warnings"] == []


def test_unknown_class_and_race_codes_warn_and_the_known_ones_stay():
    item = item_from("Class: WAR XYZ PAL<br>Race: HUM QQQ")
    assert (item["classes"], item["races"]) == (["WAR", "PAL"], ["HUM"])
    assert warnings_of(item) == [("unknown-code", "class"), ("unknown-code", "race")]
    item = item_from("Class: ALL except WAR XYZ")
    assert item["classes"] == [code for code in ALL_CLASSES if code != "WAR"]
    assert warnings_of(item) == [("unknown-code", "class")]


def test_a_class_line_with_nothing_usable_fails_closed():
    item = item_from("Class: XYZ")
    assert item["classes"] == []
    assert warnings_of(item) == [("unknown-code", "class"), ("bad-value", "class")]
    item = item_from("Class:")
    assert item["classes"] == [] and warnings_of(item) == [("bad-value", "class")]


def test_deity():
    assert item_from("Deity: Mithaniel Marr Tunare")["deity"] == ["Mithaniel Marr", "Tunare"]


def test_deity_names_are_matched_greedily():
    item = item_from("Deity: Rallos Zek Cazic Thule The Tribunal Brell Serilis Solusek Ro Rodcet Nife Erollisi Marr")
    assert item["deity"] == [
        "Rallos Zek",
        "Cazic Thule",
        "The Tribunal",
        "Brell Serilis",
        "Solusek Ro",
        "Rodcet Nife",
        "Erollisi Marr",
    ]
    assert item_from("deity: mithaniel marr")["deity"] == ["Mithaniel Marr"]
    assert item_from("Deity: Agnostic Veeshan Bertoxxulous Bristlebane Innoruuk Karana Prexus Quellious")["deity"] == [
        "Agnostic",
        "Veeshan",
        "Bertoxxulous",
        "Bristlebane",
        "Innoruuk",
        "Karana",
        "Prexus",
        "Quellious",
    ]


def test_a_lone_marr_is_not_a_deity():
    item = item_from("Deity: Marr")
    assert item["deity"] is None
    assert warnings_of(item) == [("unknown-deity", "deity")]


def test_unknown_deity_words_warn_and_the_known_ones_stay():
    item = item_from("Deity: Tunare Zorblax Veeshan")
    assert item["deity"] == ["Tunare", "Veeshan"]
    assert warnings_of(item) == [("unknown-deity", "deity")]


def test_no_deity_line_is_none():
    assert item_from("Slot: EAR")["deity"] is None


def test_focus_effect():
    item = item_from("Focus Effect: Improved Healing III")
    assert item["effects"] == [{"kind": "focus", "name": "Improved Healing III", "raw": "Focus Effect: Improved Healing III"}]


@pytest.mark.parametrize(
    ("block", "kind"),
    [
        ("Effect: Cloak of Flames (Worn)", "worn"),
        ("Effect: Cloak of Flames (Combat)", "proc"),
        ("Effect: Cloak of Flames (Any Slot, Casting Time: 3.0)", "click"),
        ("Effect: Cloak of Flames (Must Equip)", "click"),
        ("Effect: Cloak of Flames (Any Slot/Can Equip, Casting Time: 6.0) at Level 15", "click"),
        ("Effect: Cloak of Flames (Combat, Casting Time: Instant) at Level 45", "proc"),
        ("Effect: Cloak of Flames (Combat Req Level 45)", "proc"),
        ("Effect: Cloak of Flames", "other"),
        ("effect: cloak of flames (worn)", "worn"),
        ("EFFECT:   Cloak of Flames   (WORN)", "worn"),
    ],
)
def test_effect_kinds(block, kind):
    (effect,) = item_from(block)["effects"]
    assert effect["kind"] == kind
    assert effect["name"].lower() == "cloak of flames"


def test_effect_names_come_from_the_link_target():
    cases = [
        ("Effect: [[Ultravision|<span class='itemeff'>Ultravision</span>]] (Worn)", "Ultravision", "worn"),
        ("Effect:  [[Zorblax Blast#Rank 2|Blast]] (Worn)", "Zorblax Blast", "worn"),
        ("Effect: [[Unrighteous Bash (Worn)]]", "Unrighteous Bash", "worn"),
        ("Effect: [[Zorblax_Blast_(Spell)]] (Combat)", "Zorblax Blast", "proc"),
        ("Effect:  [[Illusion: Dark Elf]] (Any Slot/Can Equip, Casting Time: 6.0) at Level 15", "Illusion: Dark Elf", "click"),
        ("Effect: [[Oathbreaker's Curse]] (Combat Req Level 45)", "Oathbreaker's Curse", "proc"),
    ]
    for block, name, kind in cases:
        (effect,) = item_from(block)["effects"]
        assert (effect["name"], effect["kind"]) == (name, kind), block


def test_an_effect_keeps_its_line_as_plain_text_in_raw():
    (effect,) = item_from("Effect: [[Ultravision|<span class='itemeff'>Ultravision</span>]] (Worn)")["effects"]
    assert effect["raw"] == "Effect: Ultravision (Worn)"


def test_an_item_can_have_several_effects_in_order():
    item = item_from(lines("Effect: [[Alpha]] (Combat)", "STR: +5", "Effect: [[Beta (Worn)]]", "Focus Effect: Gamma"))
    assert [(e["kind"], e["name"]) for e in item["effects"]] == [("proc", "Alpha"), ("worn", "Beta"), ("focus", "Gamma")]


def test_effect_charges_are_recorded():
    (effect,) = item_from("Effect: [[Zorblax Blast]] (Any Slot, Casting Time: 3.0) Charges: 5")["effects"]
    assert effect["charges"] == 5
    (effect,) = item_from("Effect: [[Zorblax Blast]] (Any Slot, Casting Time: 3.0) 12 charges")["effects"]
    assert effect["charges"] == 12
    item = item_from(lines("Effect: [[Zorblax Blast]] (Must Equip)", "Charges: 7"))
    assert "charges" not in item["effects"][0] and item["charges"] == 7  # a Charges line of its own is the item's
    (effect,) = item_from("Effect: [[Zorblax Blast]] (Worn)")["effects"]
    assert "charges" not in effect


def test_the_indented_lines_after_an_effect_belong_to_it():
    block = lines(
        "Effect:  [[Blessing of the Lord Commander]] (Must Equip)",
        "&nbsp; Casting Time: Instant",
        "&nbsp; Required Level: 49",
        "&nbsp; Cooldown: 600 seconds",
        "WT: 8.0  Size: MEDIUM",
    )
    item = item_from(block)
    (effect,) = item["effects"]
    assert effect["raw"] == (
        "Effect: Blessing of the Lord Commander (Must Equip); Casting Time: Instant; Required Level: 49; "
        "Cooldown: 600 seconds"
    )
    assert item["required_level"] is None  # the 49 is the effect's, not the item's
    assert (item["weight"], item["size"]) == (8.0, "MEDIUM")
    assert item["parse_warnings"] == []


def test_a_required_level_line_not_after_an_effect_is_the_items():
    item = item_from(lines("Effect: [[Zorblax Blast]] (Worn)", "WT: 1.0", "Required Level: 45"))
    assert item["required_level"] == 45


def test_a_casting_time_line_with_no_effect_before_it_is_an_orphan_continuation():
    item = item_from(lines("AC: 5", "Casting Time: Instant"))
    assert warnings_of(item) == [("orphan-continuation", "statsblock")]
    assert item["stats"] == {"AC": 5} and item["effects"] == []
    for word in ("Cast Time: 3.5", "Cooldown: 600 seconds", "Recast Delay: 5", "Reuse Time: 9", "Level: 45"):
        assert warnings_of(item_from(word)) == [("orphan-continuation", "statsblock")], word


@pytest.mark.parametrize(
    ("block", "required", "recommended"),
    [
        ("Required level of 45.", 45, None),
        ("Required level of 45", 45, None),
        ("Required level 45", 45, None),
        ("Required Level: 45", 45, None),
        ("required level of 45.", 45, None),
        ("Recommended level of 30.", None, 30),
        ("Recommended level 30", None, 30),
        ("Required level of 45.<br>Recommended level of 30.", 45, 30),
    ],
)
def test_levels(block, required, recommended):
    item = item_from(block)
    assert (item["required_level"], item["recommended_level"]) == (required, recommended)
    assert item["parse_warnings"] == []


def test_unknown_lines_become_warnings_without_any_text():
    item = item_from(lines("Slot: EAR", "Gibberish: line", "just some words", "AC: 5"))
    assert item["slots"] == ["EAR"] and item["stats"] == {"AC": 5}  # the good lines are kept
    assert warnings_of(item) == [("unparsed-line", "statsblock")] * 2
    assert "Gibberish" not in json.dumps(item) and "just some words" not in json.dumps(item)


@pytest.mark.parametrize(
    "variant",
    [
        "Slot: finger",
        "slot: FINGER",
        "SLOT:finger",
        "Slot :  Finger",
    ],
)
def test_slot_spellings_parse_the_same(variant):
    assert item_from(variant)["slots"] == ["FINGER"]


@pytest.mark.parametrize("block", ["STR:  + 5", "STR: +5", "STR: 5", "str: +5", "STR : + 5", "STR:+5", "STR: &#43;5", "STR: +5 "])
def test_number_spellings_parse_the_same(block):
    item = item_from(block)
    assert item["stats"] == {"STR": 5} and item["parse_warnings"] == []


# ---- numbers ----------------------------------------------------------------------------------


def test_thousands_separators_are_stripped():
    assert item_from("HP: +1,250")["stats"] == {"HP": 1250}
    assert item_from("HP: 1,250")["stats"] == {"HP": 1250}


def test_a_comma_that_is_not_a_thousands_separator_is_a_bad_value():
    item = item_from("HP: 1,25")
    assert item["stats"] == {} and warnings_of(item) == [("bad-value", "hp")]


def test_a_decimal_in_an_integer_field_is_dropped_with_a_warning():
    for block, field in [("STR: +5.5", "str"), ("HP: 5.0", "hp"), ("SV FIRE: 2.5", "sv"), ("Atk Delay: 30.5", "delay")]:
        item = item_from(block)
        assert warnings_of(item) == [("non-integer", field)], block
        assert item["stats"] == {} and item["sv"] == {} and item["weapon"] is None


def test_weight_accepts_decimals():
    assert item_from("WT: 0.25")["weight"] == 0.25


@pytest.mark.parametrize(
    ("block", "field"),
    [
        ("WT: -1", "weight"),
        ("WT: 500.5", "weight"),
        ("WT: 501", "weight"),
        ("STR: -1001", "str"),
        ("STR: +10001", "str"),
        ("HP: 12,345", "hp"),
        ("SV FIRE: 10001", "sv"),
        ("Atk Delay: 0", "delay"),
        ("Atk Delay: 1000", "delay"),
        ("Atk Delay: -5", "delay"),
        ("Capacity: 1001", "capacity"),
        ("Required level of 0.", "required_level"),
        ("Required level of 256.", "required_level"),
    ],
)
def test_out_of_range_values_are_dropped_with_a_warning(block, field):
    item = item_from(block)
    assert warnings_of(item) == [("out-of-range", field)]
    assert item["weight"] is None and item["stats"] == {} and item["sv"] == {}
    assert item["weapon"] is None and item["container_capacity"] is None and item["required_level"] is None


def test_range_limits_themselves_are_in_range():
    item = item_from(lines("STR: -1000", "HP: 10000", "WT: 500", "WT: 0", "Atk Delay: 1", "Capacity: 1000"))
    assert item["stats"] == {"STR": -1000, "HP": 10000}
    assert item["weight"] == 500.0  # the first WT wins; the second is a duplicate
    assert item["weapon"]["delay"] == 1 and item["container_capacity"] == 1000
    assert warnings_of(item) == [("duplicate-key", "wt")]
    assert item_from("Atk Delay: 999")["weapon"]["delay"] == 999
    assert item_from("WT: 0")["weight"] == 0.0


@pytest.mark.parametrize("block", ["STR: abc", "STR:", "STR: +", "STR: --5", "STR: 0x10", "STR: 1e3", "STR: 5apples", "STR: 1,25"])
def test_unreadable_numbers_are_dropped_with_a_bad_value_warning(block):
    item = item_from(block)
    assert item["stats"] == {} and warnings_of(item) == [("bad-value", "str")]


def test_unicode_minus_and_fullwidth_digits_are_read():
    assert item_from("STR: \u22123")["stats"] == {"STR": -3}
    assert item_from("STR: \u20133")["stats"] == {"STR": -3}
    assert item_from("STR: \uff0b\uff15")["stats"] == {"STR": 5}


def test_a_zero_stat_is_omitted():
    item = item_from("AC: 0  STR: +0  SV FIRE: 0  HASTE: 0%")
    assert item["stats"] == {} and item["sv"] == {} and item["parse_warnings"] == []


def test_a_repeated_key_keeps_the_first_value_and_warns():
    item = item_from("STR: +5<br>STR: +9<br>SV FIRE: 1  SV FIRE: 2")
    assert item["stats"] == {"STR": 5} and item["sv"] == {"FIRE": 1}
    assert warnings_of(item) == [("duplicate-key", "str"), ("duplicate-key", "sv_fire")]


def test_stats_come_out_in_the_canonical_order():
    item = item_from("END: 1  HP: 2  CHA: 3  DEX: 4  AGI: 5  STA: 6  STR: 7  AC: 8  MANA: 9  HASTE: 10  ATK: 11")
    assert list(item["stats"]) == [key for key in STAT_KEYS if key in item["stats"]]
    assert list(item["stats"]) == ["AC", "STR", "STA", "AGI", "DEX", "CHA", "HP", "MANA", "END", "ATK", "HASTE"]


def test_resist_all_adds_to_the_five_schools():
    for block in ("Resist All: +5", "All Resists: +5", "resist all: 5"):
        item = item_from(block)
        assert item["sv"] == {"FIRE": 5, "COLD": 5, "MAGIC": 5, "POISON": 5, "DISEASE": 5}, block
    item = item_from("SV FIRE: +3  Resist All: +5  SV CORRUPTION: 2")
    assert item["sv"] == {"FIRE": 8, "COLD": 5, "MAGIC": 5, "POISON": 5, "DISEASE": 5, "CORRUPTION": 2}


def test_an_unknown_resist_school_is_a_warning():
    item = item_from("SV VOID: +2  SV FIRE: 1")
    assert item["sv"] == {"FIRE": 1} and warnings_of(item) == [("unknown-sv", "sv")]


def test_containers():
    item = item_from("Weight Reduction: 0%  Capacity: 8  Size Capacity: LARGE")
    assert item["container_capacity"] == 8 and item["parse_warnings"] == []
    assert item_from("Slot: EAR")["container_capacity"] is None


def test_the_item_type():
    item = item_from("Slot: SECONDARY  Type: Shield")
    assert (item["slots"], item["item_type"]) == (["SECONDARY"], "Shield")


def test_a_bad_size_is_a_warning():
    item = item_from("Size: HUGE")
    assert item["size"] is None and warnings_of(item) == [("bad-value", "size")]


# ---- flags ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ("Quest", ["quest"]),
        ("QUEST ITEM", ["quest"]),
        ("No Rent, Expendable", ["no_rent", "expendable"]),
        ("Ornament", ["ornament"]),
        ("Summoned", ["summoned"]),
        ("Temporary", ["temporary"]),
        ("Heirloom, Attunable, Placeable", ["attunable", "heirloom", "placeable"]),
        ("lore", ["lore"]),
        ("LORE EQUIPPED", ["lore"]),
        ("Lore Equipped No Trade", ["lore", "no_trade"]),
        ("NO DROP,NO TRADE", ["no_trade", "no_drop"]),
        ("Attunable, Lore Equipped, Placeable", ["lore", "attunable", "placeable"]),
        ("MAGIC ITEM LORE ITEM NO DROP", ["lore", "no_drop", "magic"]),
        ("MAGIC ITEM  LORE ITEM  ", ["lore", "magic"]),
    ],
)
def test_flags(block, expected):
    item = item_from(block)
    assert item["flags"] == expected and item["parse_warnings"] == []
    assert item["flags"] == [flag for flag in FLAGS if flag in item["flags"]]


def test_an_unknown_flag_word_is_a_warning_and_the_known_flags_stay():
    item = item_from("Lore Equipped, No Trade, Quest, QuestReward")
    assert item["flags"] == ["lore", "no_trade", "quest"]
    assert warnings_of(item) == [("unknown-flag", "flags")]


def test_flags_and_keys_may_share_a_line():
    item = item_from("Lore Equipped Slot: EAR")
    assert item["flags"] == ["lore"] and item["slots"] == ["EAR"] and item["parse_warnings"] == []


# ---- variants (Review Focus 1) --------------------------------------------------------------

CANONICAL = [
    "Lore Equipped, No Trade",
    "Slot: FINGER",
    "AC: 20",
    "STR: +5  STA: +5  INT: -3",
    "HP: +50  MANA: +20",
    "SV FIRE: +10",
    "Haste: +41%",
    "Skill: 1H Slashing  Atk Delay: 30",
    "DMG: 12",
    "Size: TINY  WT: 0.1",
    "Class: WAR PAL",
    "Race: ALL except HUM",
    "Deity: Tunare",
]


def core(item):
    return {
        key: item[key]
        for key in (
            "slots", "classes", "races", "deity", "flags", "stats", "sv", "weight", "size", "weapon",
            "parse_warnings",
        )
    }


def variant_blocks():
    plain = "<br>\n".join(CANONICAL)
    yield "br-slash", "<br/>\n".join(CANONICAL)
    yield "br-space-slash", "<br />\n".join(CANONICAL)
    yield "BR-upper", "<BR>".join(CANONICAL)
    yield "br-attributes", "<br class='x' clear='all'>".join(CANONICAL)
    yield "newlines-only", "\n".join(CANONICAL)
    yield "crlf", "\r\n".join(CANONICAL)
    yield "trailing-br", plain + "<br>\n"
    yield "blank-lines", "<br>\n<br>\n".join(CANONICAL)
    yield "lowercase-keys", plain.replace("Slot:", "slot:").replace("Class:", "class:").replace("STR:", "str:").replace("Deity:", "deity:")
    yield "uppercase-keys", plain.upper().replace("1H SLASHING", "1H Slashing")
    yield "plus-space", plain.replace("+5", "+ 5").replace("+50", "+ 50")
    yield "no-plus", plain.replace("+", "")
    yield "extra-spaces", plain.replace(": ", ":   ").replace("  ", "      ")
    yield "stat-per-line", plain.replace("  STA:", "<br>STA:").replace("  INT:", "<br>INT:").replace("  MANA:", "<br>MANA:")
    yield "html-plus", plain.replace("+5", "&#43;5")
    yield "nbsp-spaces", plain.replace("  ", "&nbsp;&nbsp;")
    yield "indented-lines", "<br>\n&nbsp; ".join(CANONICAL)
    yield "comment-inside", plain.replace("AC: 20", "AC: <!-- was 5 -->20")
    yield "nowiki", plain.replace("AC: 20", "AC: <nowiki>20</nowiki>")


@pytest.mark.parametrize(("label", "block"), list(variant_blocks()), ids=[label for label, _ in variant_blocks()])
def test_a_statsblock_written_slightly_differently_gives_the_same_item(label, block):
    expected = core(item_from("<br>\n".join(CANONICAL)))
    assert expected["parse_warnings"] == [] and expected["stats"]["INT"] == -3
    assert core(item_from(block)) == expected


def test_the_canonical_statsblock_values():
    item = item_from("<br>\n".join(CANONICAL))
    assert item["stats"] == {"AC": 20, "STR": 5, "STA": 5, "INT": -3, "HP": 50, "MANA": 20, "HASTE": 41}
    assert item["sv"] == {"FIRE": 10}
    assert item["slots"] == ["FINGER"] and item["classes"] == ["WAR", "PAL"]
    assert item["races"] == ALL_RACES[1:] and item["deity"] == ["Tunare"]
    assert item["weapon"] == {"skill": "1H Slashing", "dmg": 12, "delay": 30, "bonus": None}
    assert item["flags"] == ["lore", "no_trade"] and (item["size"], item["weight"]) == ("TINY", 0.1)


def test_entities_in_an_effect_name_decode_once_and_the_name_stays_the_same():
    plain = item_from("Effect: Zorblax's Blast (Worn)")["effects"]
    entity = item_from("Effect: Zorblax&#39;s Blast (Worn)")["effects"]
    assert plain == entity and plain[0]["name"] == "Zorblax's Blast"


# ---- hostile text -----------------------------------------------------------------------------


def test_a_script_tag_in_itemname_loses_its_brackets():
    item = item_from("Slot: EAR", itemname="Ring<script>alert(1)</script>")
    assert item["name"] == "Ringscriptalert(1)/script"
    assert_clean(item)


def test_bidi_and_zero_width_characters_in_itemname_are_removed():
    item = item_from("Slot: EAR", itemname="Ri\u202eng\u200b of Zor\u2066blax")
    assert item["name"] == "Ring of Zorblax"


def test_a_meta_refresh_line_leaves_nothing_but_a_warning():
    item = item_from(lines("Slot: EAR", "<meta http-equiv=refresh content=0;url=https://example.invalid/x>", "AC: 5"))
    assert warnings_of(item) == [("unparsed-line", "statsblock")]
    text = json.dumps(item)
    assert "<" not in text and ">" not in text and "meta" not in text and "example.invalid" not in text
    assert item["stats"] == {"AC": 5}


def test_an_escaped_markup_npc_label_never_becomes_markup():
    item = item_from("Slot: EAR", dropsfrom="[[Zorblax Keep]]\n* [[Boss|&lt;b&gt;Boss&lt;/b&gt;]]")
    assert item["sources"]["drops"] == [{"zone": "Zorblax Keep", "npcs": ["bBoss/b"]}]
    assert_clean(item)


def test_double_encoded_entities_decode_once_only():
    item = item_from("Slot: EAR", dropsfrom="[[Zorblax Keep]]\n* [[Boss|&amp;lt;b&amp;gt;Boss]]")
    assert item["sources"]["drops"][0]["npcs"] == ["&lt;b&gt;Boss"]


def test_every_string_that_reaches_the_item_is_sanitized():
    evil = "\u202e<b>\u200bX\x00\ud800</b>"
    page = ParsedPage(
        pageid=5,
        revid=50,
        title=f"T{evil}",
        name=f"N{evil}",
        statsblock_lines=[
            f"Effect: [[Link{evil}]] (Worn)",
            f"Skill: S{evil}",
            f"Type: T{evil}",
            "Slot: EAR",
        ],
        notes_lore=evil,
        drops=[{"zone": f"Z{evil}", "npcs": [f"N{evil}", evil]}, {"zone": evil, "npcs": []}],
        sold_by=[{"zone": f"Z{evil}", "npc": f"V{evil}"}, {"zone": None, "npc": evil}],
        quests=[f"Q{evil}", evil],
        crafted=[{"container": f"C{evil}", "ingredients": [f"I{evil}", evil]}, {"container": evil, "ingredients": []}],
        categories=[f"C{evil}", evil],
        era_tags=[f"Era{evil} Era", evil],
        lucy_img_id=None,
        focus_effects=[f"F{evil}"],
        warnings=[],
    )
    item = normalize(page)
    validate_item(item)
    assert_clean(item)
    assert item["era_tags"] == ["ErabX/b Era"]  # the other tag does not end in " Era" once cleaned: dropped
    assert item["name"] == "NbX/b" and item["wiki"]["title"] == "TbX/b"
    assert item["sources"]["drops"] == [{"zone": "ZbX/b", "npcs": ["NbX/b", "bX/b"]}, {"zone": "bX/b", "npcs": []}]
    json.dumps(item, ensure_ascii=False).encode("utf-8")  # a lone surrogate would fail here


def test_text_that_sanitizes_to_nothing_is_dropped_and_warned():
    page = ParsedPage(
        pageid=5, revid=50, title="T", name="N", statsblock_lines=["Slot: EAR"], notes_lore=None,
        drops=[{"zone": "<>", "npcs": ["<>", "ok"]}],
        sold_by=[{"zone": "<>", "npc": "<>"}, {"zone": "Z", "npc": "V"}],
        quests=["<>", "q"],
        crafted=[{"container": "<>", "ingredients": ["<>", "i"]}],
        categories=["<>", "c"], era_tags=["<>"], lucy_img_id=None, focus_effects=["<>"], warnings=[],
    )
    item = normalize(page)
    validate_item(item)
    sources = item["sources"]
    assert sources["drops"] == [{"zone": None, "npcs": ["ok"]}]
    assert sources["sold_by"] == [{"zone": "Z", "npc": "V"}]
    assert sources["quests"] == ["q"] and sources["crafted"] == [{"container": None, "ingredients": ["i"]}]
    assert item["categories"] == ["c"] and item["era_tags"] == [] and item["effects"] == []
    assert {code for code, _ in warnings_of(item)} == {"empty-value"}


def test_a_name_that_sanitizes_to_nothing_falls_back_to_the_title_then_the_key():
    page = ParsedPage(5, 50, "Zorblax Ring", "<>", ["Slot: EAR"], None, [], [], [], [], [], [], None)
    assert normalize(page)["name"] == "Zorblax Ring"
    page = ParsedPage(5, 50, "<>", "<>", ["Slot: EAR"], None, [], [], [], [], [], [], None)
    item = normalize(page)
    validate_item(item)
    assert item["name"] == "w5" and item["wiki"]["title"] == "w5"


def test_a_long_name_is_cut_to_200_characters():
    item = item_from("Slot: EAR", itemname="Z" * 500)
    assert item["name"] == "Z" * 200


# ---- warnings ---------------------------------------------------------------------------------


def test_at_most_20_warnings_are_kept_and_the_rest_are_counted():
    item = item_from(lines(*[f"Gibberish {n}" for n in range(25)]))
    assert len(item["parse_warnings"]) == 20 and item["parse_warnings_overflow"] == 5
    assert item_from(lines(*[f"Gibberish {n}" for n in range(20)]))["parse_warnings_overflow"] == 0


def test_a_warning_has_a_code_and_a_field_and_nothing_else():
    item = item_from(lines("Gibberish", "STR: abc", "Slot: ZORBLAX", "Class: XYZ", "Deity: Zorblax", "Lore, Zorblax"))
    assert len(item["parse_warnings"]) >= 6
    for warning in item["parse_warnings"]:
        assert set(warning) == {"code", "field"}
        assert warning["code"] in WARNING_CODES
        assert 1 <= len(warning["field"]) <= 32 and warning["field"].replace("_", "").isalnum()
        assert warning["field"] == warning["field"].lower()


def test_parser_warnings_come_first_then_the_statsblock_ones():
    code = (
        "{{Itempage|itemname=A Ring|statsblock=Slot: NECK|statsblock=Gibberish<br>Slot: EAR{{Nested}}"
        "|lucy_img_ID=abc}}\n{{Itempage|statsblock=Slot: HEAD}}"
    )  # the last statsblock is the one that is read
    result = parse_page({"pageid": 7, "ns": 0, "title": "A Ring", "revid": 70, "content": code})
    item = normalize(result)
    validate_item(item)
    assert warnings_of(item) == [
        ("multiple-itempage", "itempage"),
        ("duplicate-param", "statsblock"),
        ("nested-template", "statsblock"),
        ("bad-lucy-id", "lucy_img_id"),
        ("unparsed-line", "statsblock"),
    ]
    assert item["slots"] == ["EAR"]  # the first statsblock (NECK) was discarded


def test_a_made_up_warning_from_outside_is_replaced_by_a_safe_one():
    page = ParsedPage(5, 50, "T", "N", ["Slot: EAR"], None, [], [], [], [], [], [], None, [], [
        {"code": "<script>", "field": "Not A Field!"},
        {"code": "bad-value", "field": "x" * 99},
    ])
    item = normalize(page)
    validate_item(item)
    assert warnings_of(item) == [("unknown-warning", "unknown"), ("bad-value", "unknown")]


def test_a_huge_statsblock_is_cut_and_the_cut_is_a_warning():
    item = item_from(lines(*["AC: 1"] * 400 + ["Effect: Zorblax (Worn)"] * 400))
    assert ("line-limit", "statsblock") in warnings_of(item)
    assert len(item["effects"]) <= 100


def test_a_page_with_too_many_effects_is_capped():
    item = item_from(lines(*[f"Effect: Zorblax {n} (Worn)" for n in range(150)]))
    assert len(item["effects"]) == 100 and ("list-truncated", "effects") in warnings_of(item)


def test_long_source_lists_are_capped_with_a_warning():
    npcs = "\n".join(f"* [[Npc {n}]]" for n in range(1100))
    item = item_from("Slot: EAR", dropsfrom="[[Zorblax Keep]]\n" + npcs)
    assert len(item["sources"]["drops"][0]["npcs"]) == 1000
    assert ("list-truncated", "npcs") in warnings_of(item)


# ---- sources, categories, eras ----------------------------------------------------------------


def test_sources_come_through_from_the_parsed_page():
    item = item_from(
        "Slot: EAR",
        dropsfrom="[[Zorblax Keep]]\n* [[Boss One]]\n* [[Boss Two]]",
        soldby="{{ItemWhereTable|{{ItemWhereRow | [[Freeport|East Freeport]] | [[Harg Tonicka]] | | (1, 2) }}}}",
        relatedquests="* [[Quest One (Rivervale)]]",
        playercrafted="* [[Forge]]\n** [[Zorblax Ore]]",
    )
    assert item["sources"] == {
        "drops": [{"zone": "Zorblax Keep", "npcs": ["Boss One", "Boss Two"]}],
        "sold_by": [{"zone": "East Freeport", "npc": "Harg Tonicka"}],
        "quests": ["Quest One (Rivervale)"],
        "crafted": [{"container": "Forge", "ingredients": ["Zorblax Ore"]}],
    }


def test_unmapped_zones_stay_in_sources():
    item = item_from("Slot: EAR", dropsfrom="[[Plane of Hate]]\n* [[A]]\n[[Kael Drakkal]]\n* [[B]]")
    assert [d["zone"] for d in item["sources"]["drops"]] == ["Plane of Hate", "Kael Drakkal"]


def test_a_focus_effect_parameter_adds_a_focus_effect_once():
    item = item_from("Slot: EAR", focus_effect="[[Improved Healing III]]")
    assert item["effects"] == [
        {"kind": "focus", "name": "Improved Healing III", "raw": "Focus Effect: Improved Healing III"}
    ]
    item = item_from("Focus Effect: Improved Healing III", focus_effect="[[Improved Healing III]]")
    assert len(item["effects"]) == 1


def test_categories_era_tags_and_the_wiki_block():
    code = "{{Classic Era}}" + template(itemname="Zorblax Ring", statsblock="Slot: EAR") + "\n[[Category:Ear]]\n[[Category:Kunark Era]]"
    parsed = parse_page({"pageid": 7, "ns": 0, "title": "Zorblax Ring", "revid": 70, "content": code})
    item = normalize(parsed)
    validate_item(item)
    assert item["key"] == "w7"
    assert item["wiki"] == {"pageid": 7, "revid": 70, "title": "Zorblax Ring"}
    assert item["categories"] == ["Ear", "Kunark Era"]
    assert item["era_tags"] == ["Classic Era", "Kunark Era"]
    assert item["lucy_img_id"] is None


# ---- tier_rule --------------------------------------------------------------------------------

DROP = "[[Zorblax Keep]]\n* [[Boss]]"


@pytest.mark.parametrize(
    ("block", "params", "expected"),
    [
        ("Slot: EAR", {"dropsfrom": DROP}, "drop"),
        ("Slot: EAR", {"relatedquests": "* [[Quest One]]"}, "fixed0"),
        ("Slot: EAR", {"playercrafted": "* [[Forge]]\n** [[Ore]]"}, "fixed0"),
        ("Slot: EAR", {"soldby": "[[Zorblax Keep]]\n* [[Vendor]]"}, "fixed0"),
        ("Slot: EAR", {}, "fixed0"),
        ("Temporary", {}, "spell"),
        ("Summoned", {}, "spell"),
        ("Temporary, No Drop", {}, "spell"),
        ("Temporary", {"dropsfrom": DROP}, "drop"),
        ("Summoned", {"dropsfrom": DROP, "relatedquests": "* [[Quest One]]"}, "drop"),
        ("Temporary", {"relatedquests": "* [[Quest One]]"}, "fixed0"),
        ("Summoned", {"soldby": "[[Zorblax Keep]]\n* [[Vendor]]"}, "fixed0"),
        ("Temporary", {"playercrafted": "* [[Forge]]"}, "fixed0"),
        ("Slot: EAR", {"dropsfrom": DROP, "relatedquests": "* [[Quest One]]"}, "drop"),
    ],
)
def test_tier_rule(block, params, expected):
    assert item_from(block, **params)["tier_rule"] == expected


def test_a_summoned_name_with_no_source_is_a_spell_item():
    assert item_from("Slot: EAR", itemname="Summoned: Zorblax Dagger")["tier_rule"] == "spell"
    assert item_from("Slot: EAR", itemname="Summoned Zorblax Dagger")["tier_rule"] == "spell"
    assert item_from("Slot: EAR", itemname="Unsummoned Zorblax Dagger")["tier_rule"] == "fixed0"
    assert item_from("Slot: EAR", itemname="Summoned: Zorblax Dagger", dropsfrom=DROP)["tier_rule"] == "drop"


# ---- the recorded pages -----------------------------------------------------------------------


def test_engineers_ring_normalizes_as_the_plan_says():
    item = fixture_item("Engineer's Ring")
    assert item["key"] == "w42638" and item["name"] == "Engineer's Ring"
    assert item["wiki"] == {"pageid": 42638, "revid": 193407, "title": "Engineer's Ring"}
    assert item["slots"] == ["FINGER"]
    assert item["stats"] == {
        "AC": 20, "STR": 5, "STA": 5, "AGI": 5, "DEX": 5, "WIS": 5, "INT": 5, "CHA": 5, "HP": 5, "MANA": 20, "END": 20,
    }
    assert item["weight"] == 0.1 and item["size"] == "TINY"
    assert item["classes"] == ["WAR", "CLR", "PAL", "SHD", "ROG", "NEC", "WIZ", "MAG", "ENC"]
    assert item["races"] == ["ALL"] and item["deity"] is None
    assert {"lore", "no_trade"} <= set(item["flags"])
    assert item["tier_rule"] == "drop"
    assert item["sources"]["drops"] == [{"zone": "Plane of Hate", "npcs": ["Innoruuk"]}]
    assert item["era_tags"] == ["Classic Era"] and item["lucy_img_id"] == 616
    assert item["weapon"] is None and item["effects"] == [] and item["parse_warnings"] == []


EXPECTED = {
    "Girdle of Faith": dict(
        slots=["WAIST"], stats={"AC": 10, "STR": 6, "AGI": 6, "WIS": 6, "HASTE": 41}, classes=["PAL"],
        flags=["lore", "no_trade"], weight=1.0, size="SMALL", tier_rule="fixed0",
    ),
    "Cloak of Flames": dict(
        slots=["BACK"], stats={"AC": 10, "AGI": 9, "DEX": 9, "HP": 50, "HASTE": 36}, sv={"FIRE": 15}, classes=["ALL"],
        flags=["magic"], weight=0.1, size="MEDIUM", tier_rule="drop",
    ),
    "Shield of the Stalwart Seas": dict(
        slots=["SECONDARY"], stats={"AC": 35, "STR": 20, "STA": 20}, classes=["PAL"], item_type="Shield",
        flags=["lore", "attunable", "placeable"], weight=7.3, size="MEDIUM", tier_rule="drop",
        effects=[{"kind": "worn", "name": "Ultravision", "raw": "Effect: Ultravision (Worn)"}],
    ),
    "Bladestopper": dict(
        slots=["SECONDARY"], stats={"AC": 25, "STA": 15, "HP": 50},
        classes=["WAR", "CLR", "PAL", "RNG", "SHD", "BRD", "ROG", "SHM"], flags=["lore", "magic"], weight=7.3,
        size="MEDIUM", tier_rule="drop",
        effects=[{
            "kind": "click", "name": "Rune IV",
            "raw": "Effect: Rune IV (Any Slot, Casting Time: Instant, Level 40); Cooldown: 600 sec",
        }],
    ),
    "Earthshaker": dict(
        slots=["PRIMARY"], stats={"STR": 6, "STA": 6, "DEX": -5}, classes=["WAR", "PAL", "RNG", "SHD", "BER"],
        flags=["lore", "attunable", "placeable"], weight=16.0, size="GIANT", tier_rule="drop",
        weapon={"skill": "2H Slashing", "dmg": 37, "delay": 70, "bonus": None},
        effects=[{
            "kind": "proc", "name": "Earthquake",
            "raw": "Effect: Earthquake (Combat, Casting Time: Instant) at Level 45",
        }],
    ),
    "Wu's Fist of Mastery": dict(
        slots=["PRIMARY", "SECONDARY"], stats={}, classes=["MNK"], flags=["no_trade", "placeable"], weight=0.5,
        size="TINY", tier_rule="fixed0", weapon={"skill": "Hand to Hand", "dmg": 16, "delay": 22, "bonus": None},
    ),
    "Torrid Corruptor": dict(
        slots=["PRIMARY"], stats={"STR": 16, "WIS": 5, "INT": 5, "DEX": 5, "CHA": -30, "HP": 30, "MANA": 30},
        sv={"FIRE": 5, "COLD": 5, "MAGIC": 5, "POISON": 5, "DISEASE": 5}, classes=["PAL", "SHD"],
        flags=["lore", "no_trade", "quest"], weight=0.1, size="LARGE", tier_rule="fixed0",
        weapon={"skill": "2H Slashing", "dmg": 33, "delay": 44, "bonus": 20},
        effects=[
            {"kind": "proc", "name": "Oathbreaker's Curse", "raw": "Effect: Oathbreaker's Curse (Combat Req Level 45)"},
            {"kind": "worn", "name": "Unrighteous Bash", "raw": "Effect: Unrighteous Bash (Worn)"},
        ],
        parse_warnings=[{"code": "unknown-flag", "field": "flags"}],  # QuestReward
    ),
    "Baton of the Sky": dict(
        slots=["PRIMARY"], stats={"AC": 25, "STR": 10, "STA": 10, "WIS": 15, "MANA": 75}, classes=["CLR"],
        flags=["lore", "no_drop", "magic"], weight=8.0, size="MEDIUM", tier_rule="fixed0", required_level=None,
        weapon={"skill": "2H Blunt", "dmg": 33, "delay": 40, "bonus": None},
        effects=[{
            "kind": "click", "name": "Blessing of the Lord Commander",
            "raw": "Effect: Blessing of the Lord Commander (Must Equip); Casting Time: Instant; "
            "Required Level: 49; Cooldown: 600 seconds",
            "required_level": 49,
        }],
    ),
    "Talisman of Kejaar Kerrath": dict(
        slots=["NECK"], stats={"HPREG": 2, "MANAREG": 2, "ENDREG": 2}, classes=["ALL"], flags=["lore", "no_trade"],
        weight=0.1, size="TINY", tier_rule="fixed0",
    ),
    "Skinner's Belt": dict(
        slots=["WAIST"], stats={"AC": 12, "STR": 15, "WIS": 15, "HP": 20, "MANA": 20}, sv={"POISON": 20, "DISEASE": 20},
        classes=["WAR", "SHD", "SHM"], flags=["lore", "no_drop", "magic"], weight=1.0, size="SMALL", tier_rule="drop",
    ),
    "Imbued Granite Spaulders": dict(
        slots=["SHOULDERS"], stats={"AC": 20}, sv={"FIRE": 10, "COLD": 10, "MAGIC": 10, "POISON": 10, "DISEASE": 10},
        classes=["WAR", "CLR", "PAL", "RNG", "SHD", "MNK", "BRD", "ROG", "SHM"], flags=["lore"], weight=45.0,
        size="SMALL", tier_rule="drop",
    ),
    "Darkwar Mask": dict(
        slots=["FACE"], stats={"AC": 10, "STR": 5, "AGI": 5, "DEX": 5}, classes=["WAR"],
        flags=["lore", "no_drop", "magic"], weight=2.5, size="SMALL", tier_rule="drop", era_tags=["Velious Era"],
    ),
    "Rusty Dagger": dict(
        slots=["PRIMARY", "SECONDARY"], stats={}, flags=[], weight=2.5, size="SMALL", tier_rule="drop",
        classes=["WAR", "RNG", "SHD", "BRD", "ROG", "NEC", "WIZ", "MAG", "ENC", "BST", "BER"],
        weapon={"skill": "Piercing", "dmg": 3, "delay": 24, "bonus": None},
    ),
    "Bone Chips": dict(slots=[], stats={}, classes=["ALL"], flags=["quest"], weight=0.1, size="SMALL", tier_rule="drop"),
    "Backpack": dict(
        slots=[], stats={}, classes=["ALL"], flags=["quest"], weight=3.0, size="LARGE", tier_rule="drop",
        container_capacity=8,
    ),
    "Mask of Deception": dict(
        slots=["FACE"], stats={"AC": 4, "CHA": 13}, sv={"MAGIC": 7}, classes=["BRD", "ROG"],
        flags=["lore", "no_drop", "magic"], weight=0.4, size="SMALL", tier_rule="drop", era_tags=["Temple Era"],
        effects=[{
            "kind": "click", "name": "Illusion: Dark Elf",
            "raw": "Effect: Illusion: Dark Elf (Any Slot/Can Equip, Casting Time: 6.0) at Level 15",
        }],
    ),
    "Symbol of Marr": dict(
        slots=["NECK"], stats={"AC": 15, "STR": 5, "WIS": 5}, classes=["PAL"], flags=["lore", "no_trade"], weight=0.1,
        size="TINY", tier_rule="drop",
    ),
    "Ethereal Mist Chestplate": dict(
        slots=["CHEST"], stats={"AC": 28, "STA": 15, "WIS": 15, "HP": 25, "MANA": 25}, classes=["CLR"],
        flags=["lore", "no_trade", "quest"], weight=7.5, size="LARGE", tier_rule="drop",
    ),
}


@pytest.mark.parametrize("title", sorted(EXPECTED))
def test_recorded_page(title):
    item = fixture_item(title)
    for field, expected in EXPECTED[title].items():
        assert item[field] == expected, (title, field)
    assert item["races"] == ["ALL"]
    if "parse_warnings" not in EXPECTED[title]:
        assert item["parse_warnings"] == []
    assert item["parse_warnings_overflow"] == 0
    assert item["name"] == title
    assert_clean(item)


def test_every_recorded_page_validates_and_none_has_more_than_two_warnings():
    seen = 0
    for title in FIXTURE_TITLES:
        parsed = parse_page(fixture_page(title))
        if not isinstance(parsed, ParsedPage):
            assert title == "Dwarven Chain Tunic"  # the page the wiki does not have
            continue
        item = normalize(parsed)
        validate_item(item)
        assert len(item["parse_warnings"]) <= 2, title
        seen += 1
    assert seen == 19


def test_the_recorded_pages_hold_every_vendor_zone_and_npc_as_clean_text():
    item = fixture_item("Backpack")
    assert len(item["sources"]["sold_by"]) == 114
    assert {"zone": "East Cabilis", "npc": "Rastok"} in item["sources"]["sold_by"]
    assert_clean(item)


# ---- the schema -------------------------------------------------------------------------------


def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_the_schema_is_a_valid_2020_12_schema():
    Draft202012Validator.check_schema(schema())
    assert schema()["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_the_schema_enums_agree_with_the_module_constants():
    props = schema()["properties"]
    assert props["slots"]["items"]["enum"] == list(SLOTS)
    assert props["classes"]["items"]["enum"] == ["ALL", *CLASS_CODES]
    assert props["races"]["items"]["enum"] == ["ALL", *RACE_CODES]
    assert props["stats"]["propertyNames"]["enum"] == list(STAT_KEYS)
    assert props["sv"]["propertyNames"]["enum"] == list(SV_KEYS)
    assert props["flags"]["items"]["enum"] == list(FLAGS)
    assert props["deity"]["oneOf"][1]["items"]["enum"] == list(DEITIES)
    assert props["size"]["enum"] == [*SIZES, None]
    assert props["effects"]["items"]["properties"]["kind"]["enum"] == list(EFFECT_KINDS)
    assert props["tier_rule"]["enum"] == list(TIER_RULES)
    assert schema()["$defs"]["warning"]["properties"]["code"]["enum"] == list(WARNING_CODES)


def test_the_module_constants_are_the_ones_in_the_plan():
    assert list(CLASS_CODES) == ALL_CLASSES and list(RACE_CODES) == ALL_RACES
    assert list(SLOTS) == (
        "HEAD FACE EAR NECK SHOULDERS ARMS BACK WRIST HANDS FINGER CHEST LEGS FEET WAIST RANGE AMMO PRIMARY "
        "SECONDARY CHARM POWERSOURCE"
    ).split()
    assert list(STAT_KEYS) == "AC STR STA AGI DEX WIS INT CHA HP MANA END ATK HASTE HPREG MANAREG ENDREG".split()
    assert list(SV_KEYS) == "FIRE COLD MAGIC POISON DISEASE CORRUPTION".split()
    assert list(DEITIES) == [
        "Agnostic", "Bertoxxulous", "Brell Serilis", "Bristlebane", "Cazic Thule", "Erollisi Marr", "Innoruuk",
        "Karana", "Mithaniel Marr", "Prexus", "Quellious", "Rallos Zek", "Rodcet Nife", "Solusek Ro", "The Tribunal",
        "Tunare", "Veeshan",
    ]
    assert set(FLAGS) >= {"lore", "no_trade", "no_drop", "magic", "temporary", "attunable", "heirloom", "placeable"}
    assert set(FLAGS) >= {"no_rent", "expendable", "quest", "ornament", "summoned"}


@pytest.fixture(scope="module")
def valid_item():
    return fixture_item("Engineer's Ring")


def broken(item, edit):
    copy_ = copy.deepcopy(item)
    edit(copy_)
    return copy_


@pytest.mark.parametrize(
    "edit",
    [
        lambda i: i.update(extra=1),
        lambda i: i.pop("tier_rule"),
        lambda i: i.update(tier_rule="spellish"),
        lambda i: i.update(name="<b>x</b>"),
        lambda i: i.update(name="a\u200bb"),
        lambda i: i.update(name="a\x00b"),
        lambda i: i.update(name="a\u202eb"),
        lambda i: i.update(name=""),
        lambda i: i.update(name="x" * 201),
        lambda i: i.update(key="x42"),
        lambda i: i["wiki"].update(extra=1),
        lambda i: i["slots"].append("TOES"),
        lambda i: i.update(slots=["EAR", "EAR"]),
        lambda i: i.update(classes=["WAR", "XYZ"]),
        lambda i: i.update(races=["HUMAN"]),
        lambda i: i.update(deity=[]),
        lambda i: i.update(deity=["Zorblax"]),
        lambda i: i.update(flags=["shiny"]),
        lambda i: i["stats"].update(LUCK=3),
        lambda i: i["stats"].update(STR=0),
        lambda i: i["stats"].update(STR=10001),
        lambda i: i["stats"].update(STR=1.5),
        lambda i: i["sv"].update(VOID=1),
        lambda i: i.update(weight=-1),
        lambda i: i.update(weight=501),
        lambda i: i.update(size="HUGE"),
        lambda i: i.update(weapon={"skill": "x"}),
        lambda i: i.update(weapon={"skill": "x", "dmg": 1, "delay": 0, "bonus": None}),
        lambda i: i.update(effects=[{"kind": "worn", "name": "x"}]),
        lambda i: i.update(effects=[{"kind": "magic", "name": "x", "raw": "x"}]),
        lambda i: i.update(effects=[{"kind": "worn", "name": "x", "raw": "x", "extra": 1}]),
        lambda i: i.update(required_level=0),
        lambda i: i["sources"].pop("quests"),
        lambda i: i["sources"]["drops"].append({"zone": "x"}),
        lambda i: i["sources"].update(sold_by=[{"zone": "x"}]),
        lambda i: i.update(era_tags=["Classic"]),
        lambda i: i.update(parse_warnings=[{"code": "bad-value", "field": "x"}] * 21),
        lambda i: i.update(parse_warnings=[{"code": "bad-value", "field": "Some free text here"}]),
        lambda i: i.update(parse_warnings=[{"code": "free text", "field": "x"}]),
        lambda i: i.update(parse_warnings=[{"code": "bad-value", "field": "x", "text": "line"}]),
        lambda i: i.update(parse_warnings_overflow=-1),
    ],
)
def test_the_schema_rejects(valid_item, edit):
    with pytest.raises(ValidationError):
        validate_item(broken(valid_item, edit))


def test_the_schema_accepts_the_optional_charges_and_null_fields(valid_item):
    item = copy.deepcopy(valid_item)
    item["effects"] = [{"kind": "click", "name": "x", "raw": "x", "charges": 3}]
    item["deity"] = ["Tunare"]
    item["weapon"] = {"skill": None, "dmg": None, "delay": None, "bonus": None}
    validate_item(item)


# ---- stability --------------------------------------------------------------------------------


def test_normalizing_twice_gives_equal_items_and_the_page_is_not_changed():
    parsed = parse_page(fixture_page("Torrid Corruptor"))
    before = copy.deepcopy(parsed)
    assert normalize(parsed) == normalize(parsed)
    assert parsed == before


def test_the_output_does_not_depend_on_hash_order():
    code = (
        "import json, sys\n"
        "sys.path.insert(0, 'pipeline')\n"
        "from pathlib import Path\n"
        "from trioforge.sources.eqlwiki import page_records, fixture_slug\n"
        "from trioforge.sources.itempage import ParsedPage, parse_page\n"
        "from trioforge.data.normalize import normalize\n"
        "titles = json.loads(sys.argv[1])\n"
        "out = []\n"
        "for title in titles:\n"
        "    path = Path('fixtures/wiki') / (fixture_slug(title) + '.json')\n"
        "    page = parse_page(page_records(json.loads(path.read_text(encoding='utf-8')))[0])\n"
        "    if isinstance(page, ParsedPage):\n"
        "        out.append(normalize(page))\n"
        "sys.stdout.write(json.dumps(out, ensure_ascii=False))\n"
    )
    outputs = []
    for seed in ("1", "2", "3"):
        result = subprocess.run(
            [sys.executable, "-c", code, json.dumps(FIXTURE_TITLES)],
            cwd=REPO,
            env={
                "PYTHONHASHSEED": seed,
                "PYTHONUTF8": "1",
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                "PATH": os.environ.get("PATH", ""),
            },
            capture_output=True,
            check=True,
        )
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1] == outputs[2] and len(outputs[0]) > 1000


def test_the_catalog_json_round_trips_through_utf8_without_loss():
    items = [fixture_item(title) for title in FIXTURE_TITLES if title != "Dwarven Chain Tunic"]
    text = json.dumps(items, ensure_ascii=False, indent=1)
    assert json.loads(text.encode("utf-8").decode("utf-8")) == items


# ---- random input -----------------------------------------------------------------------------

LINE_FRAGMENTS = [
    "Slot: ", "AC: ", "STR: +", "STA: -", "HP: ", "MANA: ", "SV FIRE: ", "SV ", "Haste: ", "Class: ", "Race: ",
    "Deity: ", "Skill: ", "Atk Delay: ", "DMG: ", "DMG Bonus: ", "Size: ", "WT: ", "Effect: ", "Focus Effect: ",
    "Capacity: ", "Type: ", "Required level of ", "Recommended level ", "Resist All: ", "Casting Time: ",
    "ALL", "ALL except ", "WAR ", "HUM ", "EAR ", "FINGER", "AUG", "PRIMARY ", "Lore Equipped, ", "NO DROP ", "Quest",
    "Tunare ", "Mithaniel Marr", "(Worn)", "(Combat)", "(Any Slot, Casting Time: 3.0)", "[[Zorblax Blast", "]]",
    "|", "#frag", "_(God)", "{{x}}", "<span>", "</span>", "<script>", "<meta ", ">", "<", "&amp;", "&lt;", "&#39;",
    "&#", "%", "+", "-", "\u2212", ",", ".", "1", "2", "5", "10", "999", "1000", "10001", "0", "1,250", "  ", " ",
    "<br>", "<br/>", "\n", "\u200b", "\u202e", "\ud800", "\x00", "\u00a0", "\uff1c", "Zorblax", "x" * 120,
]


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.sampled_from(LINE_FRAGMENTS), max_size=60).map("".join))
def test_random_statsblocks_always_give_a_valid_clean_item(block):
    page = {
        "pageid": 9,
        "ns": 0,
        "title": "Zorblax Ring",
        "revid": 90,
        "content": template(statsblock="Slot: EAR<br>" + block, itemname=block, dropsfrom=block, relatedquests=block),
    }
    parsed = parse_page(page)
    if isinstance(parsed, ParsedPage):
        item = normalize(parsed)
        validate_item(item)
        assert_clean(item)
        json.dumps(item, ensure_ascii=False).encode("utf-8")
        assert len(item["parse_warnings"]) <= 20


@settings(max_examples=200, deadline=None)
@given(st.lists(st.text(max_size=80), max_size=30))
def test_arbitrary_statsblock_lines_never_raise(block_lines):
    page = ParsedPage(5, 50, "T", "N", [line for line in block_lines if line.strip()] or ["x"], None, [], [], [], [], [], [], None)
    item = normalize(page)
    validate_item(item)
    assert_clean(item)


# ---- a few more edges -------------------------------------------------------------------------


def test_an_augment_slot_anywhere_in_the_slot_line_makes_the_item_not_wearable():
    item = item_from("Slot: PRIMARY AUG")
    assert item["slots"] == [] and warnings_of(item) == [("augment-slot", "slot")]
    item = item_from("Slot: AUGMENT HEAD")
    assert item["slots"] == [] and warnings_of(item) == [("augment-slot", "slot")]


def test_a_flag_is_a_whole_word():
    item = item_from("Lore, Questionable, Loremaster")
    assert item["flags"] == ["lore"]
    assert warnings_of(item) == [("unknown-flag", "flags")] * 2


def test_worn_wins_over_combat_in_one_effect():
    (effect,) = item_from("Effect: Zorblax Blast (Worn, Combat)")["effects"]
    assert effect["kind"] == "worn"


# ---- spellings seen on real wiki statsblocks ---------------------------------------------------


def test_a_charges_line_right_before_the_effect_is_the_items_not_the_effects():
    block = lines("Slot: NECK", "AC: 8", "Charges: 4", "Effect:  [[Zorblax Heal]] (Must Equip, Casting Time: Instant) at Level 45")
    item = item_from(block)
    (effect,) = item["effects"]
    assert "charges" not in effect and effect["kind"] == "click" and item["charges"] == 4  # only the effect's own line
    assert item["parse_warnings"] == []


def test_a_charges_line_followed_by_other_lines_is_the_items_charges_not_the_effects():
    # any line that is not an effect clears the pending charges, so they cannot reach a later, unrelated effect
    block = lines("Slot: NECK", "Charges: 4", "AC: 8", "Effect:  [[Zorblax Heal]] (Must Equip, Casting Time: Instant) at Level 45")
    item = item_from(block)
    (effect,) = item["effects"]
    assert "charges" not in effect and item["charges"] == 4
    assert item["parse_warnings"] == []


def test_unlimited_charges_say_nothing_and_warn_nothing():
    item = item_from(lines("Charges: Unlimited", "Effect: [[Zorblax Heal]] (Must Equip)"))
    (effect,) = item["effects"]
    assert "charges" not in effect and item["parse_warnings"] == []


def test_a_charges_line_with_no_effect_after_it_is_harmless_and_no_effect_gets_it():
    assert item_from("Charges: 3")["effects"] == []
    block = lines("Charges: 3", "Effect: [[Alpha]] (Worn)", "Effect: [[Beta]] (Worn)")
    item = item_from(block)
    assert item["charges"] == 3 and all("charges" not in effect for effect in item["effects"])


def test_the_charges_in_the_effect_line_win_over_an_earlier_charges_line():
    item = item_from(lines("Charges: 3", "Effect: [[Alpha]] (Must Equip) Charges: 9"))
    assert item["effects"][0]["charges"] == 9


@pytest.mark.parametrize(
    ("label", "kind"),
    [("Click Effect", "click"), ("Worn Effect", "worn"), ("Proc Effect", "proc"), ("click effect", "click")],
)
def test_effect_labels_that_name_the_kind(label, kind):
    (effect,) = item_from(f"{label}: [[Zorblax Blast]]")["effects"]  # nothing in brackets: the label decides
    assert effect["kind"] == kind and effect["name"] == "Zorblax Blast"
    assert effect["raw"] == label.title() + ": Zorblax Blast"
    (effect,) = item_from(f"{label}: [[Zorblax Blast]] (Must Equip) Required Level: 46")["effects"]
    assert effect["kind"] == kind and effect["raw"].startswith(label.title() + ": ")


def test_cast_time_and_the_other_continuation_spellings_after_a_click_effect():
    block = lines(
        "Click Effect: [[Zorblax Blast]] (Must Equip)",
        "Cast Time: 3.5 seconds",
        "Required Level: 46",
        "Cooldown: 120 seconds",
        "AC: 8",
    )
    item = item_from(block)
    assert item["effects"][0]["raw"] == (
        "Click Effect: Zorblax Blast (Must Equip); Cast Time: 3.5 seconds; Required Level: 46; Cooldown: 120 seconds"
    )
    assert item["required_level"] is None and item["stats"] == {"AC": 8} and item["parse_warnings"] == []


def test_dmg_bon_is_the_damage_bonus():
    item = item_from(lines("Skill: Hand to Hand  Atk Delay: 22", "DMG: 12", "Dmg Bon: 10"))
    assert item["weapon"] == {"skill": "Hand to Hand", "dmg": 12, "delay": 22, "bonus": 10}


def test_a_damage_bonus_at_a_level_keeps_the_number():
    item = item_from("Skill: 2H Blunt  Atk Delay: 45<br>DMG: 35  DMG Bonus: 30 @ lvl 50  AC: 10")
    assert item["weapon"]["bonus"] == 30 and item["stats"] == {"AC": 10}
    assert item["parse_warnings"] == []
    assert item_from("DMG Bonus: 12 @ lvl. 50")["weapon"]["bonus"] == 12
    item = item_from("DMG Bonus: 12 @ nonsense")  # the number it starts with is taken, the rest is a warning
    assert item["weapon"]["bonus"] == 12 and warnings_of(item) == [("trailing-text", "bonus")]


def test_a_bows_range_is_known_and_not_stored():
    item = item_from("Slot: RANGE<br>Skill: Archery  Atk Delay: 60<br>DMG: 45<br>WT: 4.0  Range: 200  Size: MEDIUM")
    assert item["weight"] == 4.0 and item["size"] == "MEDIUM"
    assert item["weapon"] == {"skill": "Archery", "dmg": 45, "delay": 60, "bonus": None}
    assert item["parse_warnings"] == []


@pytest.mark.parametrize("line", ["Wind Resonance: 12", "Wind Resonance 12", "wind resonance: +12", "WIND RESONANCE:12"])
def test_instrument_resonance(line):
    item = item_from(lines("Slot: PRIMARY", line, "WT: 0.1  Size: TINY"))
    assert item["instrument_mods"] == {"Wind": 12}
    assert item["parse_warnings"] == [] and item["weight"] == 0.1


def test_several_instrument_families_and_a_repeat():
    item = item_from(lines("Stringed Resonance: 10", "Brass Resonance: 15", "Brass Resonance: 3", "Percussion Resonance: 0"))
    assert item["instrument_mods"] == {"Brass": 15, "String": 10}  # zero omitted; first wins; the stringed family has the one key String (the catalog's, from "String Resonance")
    assert list(item["instrument_mods"]) == ["Brass", "String"]  # sorted by name
    assert warnings_of(item) == [("duplicate-key", "resonance_brass")]


@pytest.mark.parametrize(
    "line,mods",
    [
        ("Brass Instrument: 10", {"Brass": 10}),
        ("Stringed Instrument: 10", {"String": 10}),
        ("Wind Instrument: 5", {"Wind": 5}),
        ("Percussion Instruments: 7", {"Percussion": 7}),
        ("brass instrument: +12", {"Brass": 12}),
        ("PERCUSSION INSTRUMENT:3", {"Percussion": 3}),
    ],
)
def test_instrument_modifier_written_as_an_instrument_family(line, mods):
    """``Brass Instrument: 10`` is the modifier that ``Brass Resonance: 10`` is (a tooltip of an item with such a line had it unparsed, and the item no modifier)."""
    item = item_from(lines("Slot: SECONDARY", line, "WT: 0.1  Size: TINY"))
    assert item["instrument_mods"] == mods
    assert item["parse_warnings"] == [] and item["weight"] == 0.1


def test_the_two_spellings_of_an_instrument_modifier_are_one_family_and_the_first_wins():
    item = item_from(lines("Brass Resonance: 15", "Brass Instrument: 3", "Wind Instrument: 4"))
    assert item["instrument_mods"] == {"Brass": 15, "Wind": 4}
    assert warnings_of(item) == [("duplicate-key", "resonance_brass")]


@pytest.mark.parametrize("line", ["Skill: Brass Instruments", "Brass Instrument", "Brass Instrument 10", "Brass Instrument: ten", "Brass Instrument: 10000"])
def test_what_only_looks_like_an_instrument_modifier_is_not_one(line):
    assert item_from(lines("Slot: SECONDARY", line))["instrument_mods"] == {}


@pytest.mark.parametrize("line", ["String Resonance: 7", "Stringed Resonance: 7", "String Instrument: 7", "Stringed Instruments: 7", "stringed instrument: +7"])
def test_the_stringed_family_has_one_key_whatever_the_spelling(line):
    """The catalog keys the family String (from "String Resonance"); "Stringed Instrument: 10" was a second key for the same family."""
    assert item_from(lines("Slot: SECONDARY", line))["instrument_mods"] == {"String": 7}


def test_the_stringed_spellings_together_are_one_family_and_the_first_wins():
    item = item_from(lines("String Resonance: 9", "Stringed Instrument: 3", "Stringed Resonance: 4"))
    assert item["instrument_mods"] == {"String": 9}
    assert warnings_of(item) == [("duplicate-key", "resonance_string")] * 2


def test_the_keys_of_the_instrument_families_are_the_four_of_the_catalog_and_any_other_word_as_it_is_written():
    item = item_from(lines("Wind Resonance: 1", "Brass Instrument: 2", "Percussion Resonance: 3", "Stringed Instrument: 4", "Singing Resonance: 5"))
    assert list(item["instrument_mods"]) == ["Brass", "Percussion", "Singing", "String", "Wind"]
    assert item["instrument_mods"] == {"Brass": 2, "Percussion": 3, "Singing": 5, "String": 4, "Wind": 1}


def test_no_resonance_no_mods():
    assert item_from("Slot: EAR")["instrument_mods"] == {}


def test_at_most_ten_instrument_families():
    names = ["Aaa", "Bbb", "Ccc", "Ddd", "Eee", "Fff", "Ggg", "Hhh", "Iii", "Jjj", "Kkk"]
    item = item_from(lines(*[f"{name} Resonance: 1" for name in names]))
    assert len(item["instrument_mods"]) == 10 and ("list-truncated", "instrument_mods") in warnings_of(item)


def test_the_real_world_class_line_with_nothing_after_all_except():
    item = item_from("Class: ALL except")
    assert item["classes"] == ["ALL"] and warnings_of(item) == [("bad-value", "class")]


def test_the_schema_checks_instrument_mods(valid_item):
    for edit in (
        lambda i: i.update(instrument_mods={"wind": 1}),
        lambda i: i.update(instrument_mods={"Wind": 0}),
        lambda i: i.update(instrument_mods={"Wind": 1.5}),
        lambda i: i.update(instrument_mods={"Wind<": 1}),
        lambda i: i.update(instrument_mods={f"Fam{chr(97 + n)}": 1 for n in range(11)}),
        lambda i: i.pop("instrument_mods"),
    ):
        with pytest.raises(ValidationError):
            validate_item(broken(valid_item, edit))
    ok = copy.deepcopy(valid_item)
    ok["instrument_mods"] = {"Wind": 12, "Brass": -3}
    validate_item(ok)


def test_a_line_longer_than_200_characters_is_parsed_whole():
    stats = "  ".join(f"{key}: +{n + 1}" for n, key in enumerate(["STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END"]))
    block = stats + "  " * 60 + "ATK: +7  HASTE: +9%"
    assert len(block) > 200
    item = item_from(block)
    assert item["stats"] == {
        "STR": 1, "STA": 2, "AGI": 3, "DEX": 4, "WIS": 5, "INT": 6, "CHA": 7, "HP": 8, "MANA": 9, "END": 10,
        "ATK": 7, "HASTE": 9,
    }
    assert item["parse_warnings"] == []


def test_a_long_skill_name_is_stored_cut_but_the_rest_of_the_line_still_parses():
    item = item_from("Skill: " + "x" * 300 + " Atk Delay: 30")
    assert item["weapon"]["skill"] == "x" * 200 and item["weapon"]["delay"] == 30


def test_skill_shield_is_a_shield_not_a_weapon():
    item = item_from(lines("Slot: SECONDARY", "AC: 15", "Skill: Shield"))
    assert item["item_type"] == "Shield" and item["weapon"] is None
    item = item_from(lines("Slot: SECONDARY", "Type: Buckler", "Skill: Shield"))
    assert item["item_type"] == "Buckler" and item["weapon"] is None
    # a shield that is also weighted as a weapon keeps its numbers
    item = item_from(lines("Skill: Shield", "DMG: 3", "Atk Delay: 30"))
    assert item["weapon"] == {"skill": "Shield", "dmg": 3, "delay": 30, "bonus": None}


def test_the_constants_for_the_remaining_enums_are_the_ones_in_the_plan():
    assert list(SIZES) == ["TINY", "SMALL", "MEDIUM", "LARGE", "GIANT"]
    assert list(EFFECT_KINDS) == ["focus", "click", "worn", "proc", "spell", "other"]
    assert list(TIER_RULES) == ["drop", "fixed0", "spell"]


def test_one_enormous_line_is_cut_and_warned_not_scanned_whole():
    huge = "STR: +5  " + "x" * 50_000  # a page over 60,000 characters never reaches the normalizer
    item = item_from(lines("Slot: EAR", huge, "AC: 5"))
    assert item["stats"] == {"STR": 5, "AC": 5}  # the huge line's STR value starts with a number: taken, the rest warned
    assert ("line-limit", "statsblock") in warnings_of(item) and ("trailing-text", "str") in warnings_of(item)
    assert item["slots"] == ["EAR"]


def test_the_kind_can_come_from_the_parenthetical_of_a_labelled_link_target():
    (effect,) = item_from("Effect: [[Zorblax Blast (Worn)|Zorblax Blast]]")["effects"]
    assert (effect["kind"], effect["name"], effect["raw"]) == ("worn", "Zorblax Blast", "Effect: Zorblax Blast")
    (effect,) = item_from("Effect: [[Zorblax Blast (Combat)|Zorblax Blast]]")["effects"]
    assert effect["kind"] == "proc"


# ---- parser fixes: numbers, keys, lists, deities, charges, effects -----------------------------------
# These pin what the statsblock reader must do with the spellings the real pages use. Names are invented.


def page_of(*statsblock_lines, **fields):
    """A ParsedPage built directly (no wikitext), for lines the template parser would change."""
    params = dict(drops=[], sold_by=[], quests=[], crafted=[], categories=[], era_tags=[], lucy_img_id=None)
    params.update(fields)
    return ParsedPage(5, 50, "Zorblax Ring", "Zorblax Ring", list(statsblock_lines), None, **params)


def item_of(*statsblock_lines, **fields):
    item = normalize(page_of(*statsblock_lines, **fields))
    validate_item(item)
    assert_clean(item)
    return item


# -- H3: a number is bounded, whatever its length


@pytest.mark.parametrize(
    ("line", "field"),
    [
        ("STR: " + "9" * 4995, "str"),
        ("Required level of " + "9" * 4900 + ".", "required_level"),
        ("Recommended level of " + "9" * 4900, "recommended_level"),
        ("WT: " + "9" * 4900, "weight"),
        ("WT: 0." + "9" * 4900, "weight"),
        ("Atk Delay: " + "9" * 4900, "delay"),
        ("Haste: " + "9" * 4900 + "%", "haste"),
        ("SV FIRE: -" + "9" * 4900, "sv"),
        ("Capacity: " + "9" * 4900, "capacity"),
        ("Charges: " + "9" * 4900, "charges"),
        ("HP: 1,234,567,890,123", "hp"),
        ("STR: 12345678", "str"),
    ],
)
def test_a_number_of_more_than_seven_digits_is_out_of_range_and_is_never_an_exception(line, field):
    item = item_of(line)
    assert ("out-of-range", field) in warnings_of(item)
    assert item["stats"] == {} and item["sv"] == {} and item["weight"] is None and item["weapon"] is None
    assert item["required_level"] is None and item["recommended_level"] is None and "charges" not in item


@settings(max_examples=250, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(
                ["STR: ", "HP: ", "WT: ", "Atk Delay: ", "Required level of ", "Charges: ", "SV FIRE: ", "Haste: ", "DMG: ",
                 "Capacity: ", "Wind Resonance: ", "BACKSTAB: ", "Fire DMG: ", "DMG Bonus: ", "SV: Cold ", "AC "]
            ),
            st.integers(min_value=1, max_value=5500),
            st.sampled_from(["", ".", "%", ",000", ".5", " apples", "e5", " @ lvl 50", "-5", " / 9"]),
        ),
        max_size=10,
    )
)
def test_normalize_never_raises_on_long_numbers(parts):
    lines = [key + "9" * length + tail for key, length, tail in parts] or ["x"]
    item = normalize(page_of(*lines))
    validate_item(item)
    assert_clean(item)


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=4000))
def test_normalize_never_raises_on_any_statsblock_text(text):
    item = normalize(page_of(*([line for line in text.split("\n") if line.strip()] or ["x"])))
    validate_item(item)
    assert_clean(item)
    json.dumps(item, ensure_ascii=False).encode("utf-8")


@settings(max_examples=200, deadline=None)
@given(st.text(alphabet="0123456789,.+-%*: \nabcSTRHPWTAtkDelayclassraceDeity[]()", max_size=600))
def test_normalize_never_raises_on_statsblock_like_text(text):
    item = normalize(page_of(*([line for line in text.split("\n") if line.strip()] or ["x"])))
    validate_item(item)
    assert_clean(item)


# -- M4: the number a value starts with is taken; anything after it is a warning


def test_text_after_a_number_is_a_trailing_text_warning_and_the_number_is_kept():
    for block, stat in (("STR: 5 apples", {"STR": 5}), ("STR: 5%", {"STR": 5}), ("STR: +5 (with focus)", {"STR": 5}), ("HP: 20 / 25", {"HP": 20})):
        item = item_from(block)
        assert item["stats"] == stat, block
        assert warnings_of(item) == [("trailing-text", block.split(":")[0].lower())], block
    item = item_from("Skill: 1H Slashing  Atk Delay: 30 / 25 / 20")
    assert item["weapon"]["delay"] == 30 and warnings_of(item) == [("trailing-text", "delay")]


@pytest.mark.parametrize("block", ["WT: 0.1.", "STR: 5.", "STR: 5,", "STR: 5 ;", "STR: 5 ?", "HASTE: 41 %", "HASTE: +41%."])
def test_a_trailing_period_comma_or_percent_sign_is_no_warning(block):
    assert item_from(block)["parse_warnings"] == []


def test_a_number_that_runs_into_letters_or_digits_is_a_bad_value():
    for block in ("STR: 5apples", "STR: 0x10", "STR: 1e3", "STR: 5_000", "STR: 1,25", "STR: 12a"):
        item = item_from(block)
        assert item["stats"] == {} and warnings_of(item) == [("bad-value", "str")], block


def test_any_word_with_a_colon_ends_the_value_before_it():
    item = item_from("STR: +15  DEX: +15  STA: +20  HP: +125 ENDUR: +100")
    assert item["stats"] == {"STR": 15, "STA": 20, "DEX": 15, "HP": 125, "END": 100}
    assert item["parse_warnings"] == []
    item = item_from("AC: 5 Velocity: 3 HP: 10")  # an unknown key: its value is skipped, the line is one warning
    assert item["stats"] == {"AC": 5, "HP": 10} and warnings_of(item) == [("unparsed-line", "statsblock")]
    item = item_from("Mount Speed: Moderate")
    assert item["stats"] == {} and warnings_of(item) == [("unparsed-line", "statsblock")]  # one warning, not two


def test_a_link_around_a_key_is_dropped_before_the_line_is_read():
    for block in ("[[Haste]]: +41%", "[[Haste|Haste]]: 41%", "[[Haste]]:+41"):
        assert item_from(block)["stats"] == {"HASTE": 41}, block
    assert item_from("[[Haste]]: +41%  <br>STR: +5")["stats"] == {"HASTE": 41, "STR": 5}


@pytest.mark.parametrize(
    ("block", "stats"),
    [
        ("STR +10", {"STR": 10}),
        ("AC 4", {"AC": 4}),
        ("str +10  sta -3", {"STR": 10, "STA": -3}),
        ("STR: +4 DEX: +5 WIS +4 INT: +4", {"STR": 4, "DEX": 5, "WIS": 4, "INT": 4}),
        ("HP 12 MANA 30", {"HP": 12, "MANA": 30}),
        ("Charisma: 5", {"CHA": 5}),
        ("Strength: 1  Stamina: 2  Agility: 3  Dexterity: 4  Wisdom: 5  Intelligence: 6  Charisma: 7", {"STR": 1, "STA": 2, "AGI": 3, "DEX": 4, "WIS": 5, "INT": 6, "CHA": 7}),
        ("ENDUR: +100", {"END": 100}),
        ("Endurance: 7  Attack: 3", {"END": 7, "ATK": 3}),
        ("Endur Regen: 2", {"ENDREG": 2}),
    ],
)
def test_keys_with_no_colon_and_the_longer_names_of_the_stats(block, stats):
    item = item_from(block)
    assert item["stats"] == stats and item["parse_warnings"] == []


@pytest.mark.parametrize(
    ("block", "sv"),
    [
        ("SV FIRE +5", {"FIRE": 5}),
        ("SV.Cold: 5", {"COLD": 5}),
        ("SV. Cold: 5", {"COLD": 5}),
        ("SV: Disease 4", {"DISEASE": 4}),
        ("MR: +10 FR: +5 CR: 3 DR 4 PR 2", {"FIRE": 5, "COLD": 3, "MAGIC": 10, "POISON": 2, "DISEASE": 4}),
        ("INT: +4  MANA: +15  SV FIRE +5", {"FIRE": 5}),
        ("SV CORRUPTION: 3  SV CORRUPT: 9", {"CORRUPTION": 3}),
    ],
)
def test_resists_in_every_spelling_the_wiki_uses(block, sv):
    item = item_from(block)
    assert item["sv"] == sv
    if "CORRUPT:" not in block:
        assert item["parse_warnings"] == []


def test_a_stat_word_in_prose_is_not_a_key():
    for block in ("This is a hearty meal!", "A hp potion", "Ends at dawn 5", "Cast it at an int", "dr who"):
        item = item_from(block)
        assert item["stats"] == {} and item["sv"] == {} and warnings_of(item) == [("unparsed-line", "statsblock")], block


def test_backstab_is_stored_with_the_weapon():
    item = item_from(lines("Skill: 1H Piercing  Atk Delay: 27", "DMG: 13  BACKSTAB: 13"))
    assert item["weapon"] == {"skill": "1H Piercing", "dmg": 13, "delay": 27, "bonus": None, "backstab": 13}
    assert item["parse_warnings"] == []
    assert item_from("Backstab: 9")["weapon"] == {"skill": None, "dmg": None, "delay": None, "bonus": None, "backstab": 9}
    assert item_from("BACKSTAB: 0")["weapon"] is None


def test_an_elemental_damage_is_stored_with_its_type_and_value():
    item = item_from(lines("Slot: AMMO", "Skill: Archery  Atk Delay: 20", "DMG: 11 Fire DMG: 4"))
    assert item["weapon"] == {"skill": "Archery", "dmg": 11, "delay": 20, "bonus": None, "elemental": {"type": "Fire", "value": 4}}
    assert item["parse_warnings"] == []
    for text, kind in (("Cold DMG: 5", "Cold"), ("poison dmg: 2", "Poison"), ("Magic Damage: 7", "Magic"), ("DISEASE DMG: 1", "Disease")):
        assert item_from(text)["weapon"]["elemental"] == {"type": kind, "value": int(text[-1])}, text
    item = item_from("DMG: 11  Fire DMG: 4  Cold DMG: 3")  # one elemental damage is stored; a second is a duplicate
    assert item["weapon"]["elemental"] == {"type": "Fire", "value": 4} and warnings_of(item) == [("duplicate-key", "elemental")]


def test_a_bane_damage_is_known_and_does_not_disturb_the_damage():
    item = item_from("Skill: 2H Slashing  Atk Delay: 40<br>DMG: 20  Bane DMG: Gnoll +4")
    assert item["weapon"] == {"skill": "2H Slashing", "dmg": 20, "delay": 40, "bonus": None}
    assert item["parse_warnings"] == []


@pytest.mark.parametrize("block", ["Size Capacity: LARGE", "Weight Reduction: 50%", "Range: 200", "Bane DMG: Undead +4", "Bane Damage: Orc 3"])
def test_the_keys_that_are_known_and_not_stored_parse_without_a_warning(block):
    item = item_from(lines("AC: 5", block, "STR: 3"))
    assert item["stats"] == {"AC": 5, "STR": 3} and item["parse_warnings"] == []
    assert item["weapon"] is None and item["container_capacity"] is None


# -- M3: charges


def test_expendable_charges_are_recorded_and_raise_no_flag_warning():
    item = item_from("EXPENDABLE  Charges: 10")
    assert item["flags"] == ["expendable"] and item["charges"] == 10 and item["parse_warnings"] == []
    assert item_from("EXPENDABLE Charges: 2")["charges"] == 2
    assert item_from("MAGIC ITEM  EXPENDABLE  Charges: 7")["flags"] == ["magic", "expendable"]


def test_expendable_charges_on_the_line_before_the_effect_stay_the_items():
    item = item_from(lines("EXPENDABLE  Charges: 10", "Effect: [[Flurry]] (Any Slot, Casting Time: 8.0)", "WT: 0.4  Size: SMALL"))
    (effect,) = item["effects"]
    assert "charges" not in effect and item["charges"] == 10 and item["parse_warnings"] == []


def test_charges_with_a_stat_line_before_the_effect_stay_the_items():
    item = item_from(lines("MAGIC ITEM", "EXPENDABLE  Charges: 1", "INT: +2", "Effect: [[Eye of Zomm]] (Any Slot, Casting Time: Instant)"))
    (effect,) = item["effects"]
    assert "charges" not in effect and item["charges"] == 1 and item["stats"] == {"INT": 2}
    assert item["parse_warnings"] == []


def test_a_charges_line_never_reaches_an_effect_whatever_stands_between_them():
    # no line passes its charges to a neighbouring effect (the first version did, by line order)
    for block in (
        lines("Charges: 3", "Effect: [[Alpha]] (Worn)", "Effect: [[Beta]] (Worn)"),
        lines("Charges: 3", "Size: SMALL", "Effect: [[Alpha]] (Worn)"),
        lines("Charges: 3", "Quest", "Effect: [[Alpha]] (Worn)"),  # even a flag line
        lines("Effect: [[Alpha]] (Worn)", "Size: SMALL", "Charges: 3", "Effect: [[Beta]] (Worn)"),
    ):
        item = item_from(block)
        assert item["charges"] == 3 and all("charges" not in effect for effect in item["effects"]), block


def test_charges_on_the_line_after_an_effect_belong_to_the_item_only():
    item = item_from(lines("Effect: [[Zorblax Blast]] (Must Equip)", "Charges: 7"))
    assert "charges" not in item["effects"][0] and item["charges"] == 7  # it was the effect's, and the item had none


def test_a_word_that_merely_ends_in_charge_is_not_a_charge_count():
    for text in ("Recharge: 5", "Effect: [[Zorblax Blast]] (Any Slot, Casting Time: 3.0) Recharge: 5 seconds", "Effect: [[Zorblax Blast]] (Any Slot) Discharge 4"):
        item = item_from(text)
        assert all("charges" not in effect for effect in item["effects"]), text
        assert "charges" not in item, text
    (effect,) = item_from("Effect: [[Zorblax Blast]] (Any Slot) 3 charges")["effects"]
    assert effect["charges"] == 3


def test_charges_unlimited_and_a_second_charges_line():
    assert "charges" not in item_from("Charges: Unlimited")
    item = item_from(lines("Charges: 2", "AC: 3", "Charges: 9"))
    assert item["charges"] == 2 and warnings_of(item) == [("duplicate-key", "charges")]
    assert item_from("Charges: 0")["charges"] == 0


# -- M5: lists that wrap, slots without a label


def test_a_class_list_continues_on_the_next_line_if_that_line_has_only_class_codes():
    item = item_from(lines("Class: WAR CLR PAL RNG SHD DRU", "MNK BRD ROG SHM", "Race: ALL"))
    assert item["classes"] == "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM".split() and item["parse_warnings"] == []
    item = item_from(lines("Class: WAR CLR PAL RNG SHD DRU MNK BRD ROG", "SHM NEC WIZ MAG ENC", "Race: ALL"))
    assert item["classes"] == "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC".split()
    item = item_from(lines("Class: WAR CLR", "PAL,", "RNG / SHD"))
    assert item["classes"] == "WAR CLR PAL RNG SHD".split()
    item = item_from(lines("Class: WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC", "BST BER"))
    assert item["classes"] == ["ALL"]


def test_a_race_list_continues_on_the_next_line_and_a_class_list_does_not_take_race_codes():
    item = item_from(lines("Race: HUM BAR ERU", "ELF HIE", "VAH"))
    assert item["races"] == ["HUM", "BAR", "ERU", "ELF", "HIE", "KER"] and item["parse_warnings"] == []
    item = item_from(lines("Class: WAR", "HUM BAR"))
    assert item["classes"] == ["WAR"] and warnings_of(item) == [("unparsed-line", "statsblock")]


def test_an_all_except_list_goes_on_excluding_on_the_next_line():
    item = item_from(lines("Class: ALL except WAR CLR", "PAL"))
    assert item["classes"] == [code for code in ALL_CLASSES if code not in ("WAR", "CLR", "PAL")]
    item = item_from(lines("Race: ALL except", "HUM BAR"))  # the first line had nothing after "except": still one warning
    assert item["races"] == ALL_RACES[2:] and warnings_of(item) == [("bad-value", "race")]


def test_a_list_does_not_continue_after_another_line_or_after_all():
    item = item_from(lines("Class: WAR", "AC: 5", "CLR"))
    assert item["classes"] == ["WAR"] and warnings_of(item) == [("unparsed-line", "statsblock")]
    item = item_from(lines("Class: ALL", "WAR"))
    assert item["classes"] == ["ALL"] and warnings_of(item) == [("unparsed-line", "statsblock")]
    item = item_from(lines("WAR CLR"))  # codes with no list before them
    assert warnings_of(item) == [("unparsed-line", "statsblock")]
    item = item_from(lines("Class: WAR", "MNK ZZZ"))  # a code that is no class: not a continuation
    assert item["classes"] == ["WAR"] and warnings_of(item) == [("unparsed-line", "statsblock")]


@pytest.mark.parametrize(
    ("block", "slots"),
    [
        ("Wrist", ["WRIST"]),
        ("WRISTS", ["WRIST"]),
        ("Primary Secondary", ["PRIMARY", "SECONDARY"]),
        ("Power Source", ["POWERSOURCE"]),
        ("Head, Face", ["HEAD", "FACE"]),
        ("FINGER", ["FINGER"]),
    ],
)
def test_a_line_of_slot_words_alone_is_a_slot_line(block, slots):
    item = item_from(lines("No Trade", "Class: BST", block, "AC: 5"))
    assert item["slots"] == slots and item["parse_warnings"] == []


def test_slot_words_alone_add_to_a_slot_line_and_augment_is_not_one():
    assert item_from(lines("Slot: EAR", "Finger"))["slots"] == ["EAR", "FINGER"]
    item = item_from("Augment")
    assert item["slots"] == [] and warnings_of(item) == [("unparsed-line", "statsblock")]
    item = item_from("Wrist Zorblax")  # one word that is no slot: not a slot line
    assert item["slots"] == [] and warnings_of(item) == [("unparsed-line", "statsblock")]


# -- H2: deities


@pytest.mark.parametrize(
    ("block", "deity"),
    [
        ("Deity: Cazic-Thule", ["Cazic Thule"]),
        ("Deity: Bertoxxulous Cazic-Thule Innoruuk Rallos Zek", ["Bertoxxulous", "Cazic Thule", "Innoruuk", "Rallos Zek"]),
        ("Deity: [[The Tribunal]] / [[Rallos Zek]]", ["The Tribunal", "Rallos Zek"]),
        ("Deity: [[The Tribunal]]", ["The Tribunal"]),
        ("Deity: [[Rallos Zek|Rallos]] [[Tunare]]", ["Rallos Zek", "Tunare"]),  # the link target names the god, not the label
        ("Deity: Erollisi-Marr, Mithaniel-Marr", ["Erollisi Marr", "Mithaniel Marr"]),
        ("Deity: Rodcet-Nife/Solusek-Ro", ["Rodcet Nife", "Solusek Ro"]),
        ("Diety: Tunare", ["Tunare"]),
        ("Dieties: Bertoxxulous, Cazic-Thule, Innoruuk, Rallos Zek, Veeshan", ["Bertoxxulous", "Cazic Thule", "Innoruuk", "Rallos Zek", "Veeshan"]),
        ("Deities: Tunare Veeshan", ["Tunare", "Veeshan"]),
        ("deity: karana", ["Karana"]),
    ],
)
def test_deity_lines_in_the_spellings_the_wiki_uses(block, deity):
    item = item_from(block)
    assert item["deity"] == deity and item["parse_warnings"] == []


def test_a_deity_line_with_no_colon_and_a_line_of_deity_names_alone():
    item = item_from(lines("Class: ALL", "Race: ALL", "Deity Prexus"))
    assert item["deity"] == ["Prexus"] and item["parse_warnings"] == []
    item = item_from(lines("Race: ALL", "Tunare"))  # the whole line is a deity name
    assert item["deity"] == ["Tunare"] and item["parse_warnings"] == []
    item = item_from(lines("Race: ALL", "Brell Serilis Karana"))
    assert item["deity"] == ["Brell Serilis", "Karana"]
    item = item_from("Deity Zorblax")
    assert item["deity"] is None and warnings_of(item) == [("unknown-deity", "deity")]


def test_a_deity_list_that_wraps_continues_on_the_next_line():
    item = item_from(lines("Deity: Bertoxxulous Cazic-Thule", "Innoruuk Rallos-Zek", "Race: ALL"))
    assert item["deity"] == ["Bertoxxulous", "Cazic Thule", "Innoruuk", "Rallos Zek"] and item["parse_warnings"] == []


def test_deity_all_is_no_deity_and_a_mixed_line_is_not_a_deity_line():
    item = item_from("Deity: ALL")
    assert item["deity"] is None and item["parse_warnings"] == []
    item = item_from("Tunare is a goddess")  # not only names: a line we do not know
    assert item["deity"] is None and warnings_of(item) == [("unparsed-line", "statsblock")]
    assert item_from("Marr")["deity"] is None


# -- L8, VAH


@pytest.mark.parametrize(("line", "where"), [("Class: NONE", "class"), ("Class: none", "class"), ("CLASS: None", "class"), ("Race: NONE", "race")])
def test_class_none_and_race_none_mean_nobody_with_one_warning(line, where):
    item = item_from(line)
    assert item[where + "es" if where == "class" else "races"] == []
    assert warnings_of(item) == [("no-classes", where)]


def test_class_none_and_race_none_on_one_page_give_one_warning_each_and_both_lists_empty():
    item = item_from(lines("Size: TINY  WT: 0.1", "Class: NONE", "Race: NONE"))
    assert item["classes"] == [] and item["races"] == []
    assert warnings_of(item) == [("no-classes", "class"), ("no-classes", "race")]


def test_vah_is_the_kerran_code():
    assert item_from("Race: ELF DEF VAH")["races"] == ["ELF", "DEF", "KER"]
    assert item_from("Race: VAH")["races"] == ["KER"]
    assert item_from("Race: KER VAH")["races"] == ["KER"]
    item = item_from("Race: ALL except VAH")
    assert item["races"] == [code for code in ALL_RACES if code != "KER"]
    assert item_from("Race: vah")["parse_warnings"] == []
    assert item_from("Class: VAH")["classes"] == []  # only a race code


def test_race_aliases_are_exported():
    from trioforge.data.normalize import RACE_ALIASES

    assert RACE_ALIASES == {"VAH": "KER"}


# -- L4: flags


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ("LORE ITEM  NODROP", ["lore", "no_drop"]),
        ("NODROP", ["no_drop"]),
        ("MAGIC ITEM NODROP NORENT", ["no_drop", "magic", "no_rent"]),
        ("NORENT", ["no_rent"]),
        ("Lore Equipped, Attuneable, Quest", ["lore", "attunable", "quest"]),
        ("attuneable", ["attunable"]),
    ],
)
def test_the_flag_spellings_without_spaces_and_the_extra_e(block, expected):
    item = item_from(block)
    assert item["flags"] == expected and item["parse_warnings"] == []


# -- L6: spell scrolls


def test_a_spell_school_as_the_skill_is_a_spell_scroll_not_a_weapon():
    for school in ("Abjuration", "Alteration", "Conjuration", "Divination", "Evocation", "abjuration"):
        item = item_from(lines("MAGIC ITEM", "Skill: " + school, "Effect: Zorblax Bolt"))
        assert item["weapon"] is None, school
    item = item_from("Skill: Alteration  Atk Delay: 30<br>DMG: 5")  # with numbers it is whatever the page says
    assert item["weapon"] == {"skill": "Alteration", "dmg": 5, "delay": 30, "bonus": None}


# -- L7: the required level of an effect


def test_the_required_level_after_an_effect_is_the_effects_not_the_items():
    block = lines("Effect: [[Zorblax Blast]] (Must Equip)", "Casting Time: Instant", "Required Level: 49", "WT: 1.0")
    item = item_from(block)
    (effect,) = item["effects"]
    assert effect["required_level"] == 49 and item["required_level"] is None
    assert effect["raw"].endswith("Required Level: 49")
    item = item_from(lines("Required level of 45.", "Effect: [[Zorblax Blast]] (Must Equip)"))
    assert item["required_level"] == 45 and "required_level" not in item["effects"][0]


def test_the_required_level_in_the_effect_line_itself_is_the_effects():
    (effect,) = item_from("Click Effect: [[Whirl Bolt]] (Must Equip) - Cast Time: 1.0 seconds, Required Level: 46, Cooldown: 240 seconds")["effects"]
    assert effect["required_level"] == 46 and effect["kind"] == "click" and effect["name"] == "Whirl Bolt"
    (effect,) = item_from("Effect: [[Zorblax Blast]] (Worn) at Level 46")["effects"]
    assert "required_level" not in effect


# -- L3: effects


def test_a_generic_link_target_gives_the_label_as_the_effect_name():
    (effect,) = item_from("Effect: [[Pet Guide|Minion of Air]] (Any Slot, Casting Time: 3.0)")["effects"]
    assert effect["name"] == "Minion of Air" and effect["kind"] == "click"
    (effect,) = item_from("Effect: [[Spells|Spirit of Zorblax]] (Worn)")["effects"]
    assert effect["name"] == "Spirit of Zorblax"
    (effect,) = item_from("Effect: [[Pet Guide]] (Worn)")["effects"]  # no label: the target is all there is
    assert effect["name"] == "Pet Guide"
    (effect,) = item_from("Effect: [[Zorblax Blast|Blast]] (Worn)")["effects"]  # an ordinary target keeps the target
    assert effect["name"] == "Zorblax Blast"


@pytest.mark.parametrize(
    ("block", "kind", "name"),
    [
        ("Combat Effect: [[Knee Shot]] (Req Level 15)", "proc", "Knee Shot"),
        ("combat effect: [[Knee Shot]]", "proc", "Knee Shot"),
        ("Consumable Effect: [[Counteract Poison]]", "click", "Counteract Poison"),
        ("[[Grim Aura]] (Worn)", "worn", "Grim Aura"),
        ("[[Zorblax Blast]] (Combat, Casting Time: Instant) at Level 45", "proc", "Zorblax Blast"),
        ("[[Zorblax Blast]] (Any Slot, Casting Time: 2.0)", "click", "Zorblax Blast"),
        ("[[Effect: Flamesong]] (Combat, Casting Time: Instant) at Level 45", "proc", "Flamesong"),
        ("Worn Effect: Scalp of the Zorblax", "worn", "Scalp of the Zorblax"),
    ],
)
def test_effect_labels_and_an_effect_line_with_no_label(block, kind, name):
    (effect,) = item_from(block)["effects"]
    assert (effect["kind"], effect["name"]) == (kind, name)
    assert effect["raw"].startswith(("Combat Effect: ", "Consumable Effect: ", "Effect: ", "Worn Effect: "))


def test_a_line_that_starts_with_a_link_is_not_an_effect_unless_it_has_a_bracket_with_effect_words():
    for block in ("[[Haste]]: +41%", "[[Zorblax Keep]] (north gate)", "[[Zorblax Blast]]"):
        assert item_from(block)["effects"] == [], block


# -- the continuation machinery


def test_an_indented_continuation_attaches_to_the_current_effect():
    block = lines("Effect: [[Zorblax Blast]] (Must Equip)", "  Casting Time: Instant", "  Cooldown: 600 seconds")
    (effect,) = item_from(block)["effects"]
    assert effect["raw"].endswith("Casting Time: Instant; Cooldown: 600 seconds")


def test_a_continuation_with_no_current_effect_is_a_warning_never_an_error():
    from trioforge.data.normalize import _Block, _Warnings

    warnings = _Warnings()
    _Block(warnings).continuation("Casting Time: Instant")
    assert warnings.items == [{"code": "orphan-continuation", "field": "statsblock"}]
    item = item_from(lines("Effect: [[Zorblax Blast]] (Worn)", "AC: 5", "Casting Time: Instant"))
    assert warnings_of(item) == [("orphan-continuation", "statsblock")]  # the AC line ended the effect


# -- focus effects


def test_focus_effects_of_the_page_are_capped_like_the_other_lists():
    focus = [f"Zorblax Focus {n}" for n in range(150)]
    item = item_of("Slot: EAR", "Effect: [[Alpha]] (Worn)", focus_effects=focus)
    assert len(item["effects"]) == 100 and ("list-truncated", "effects") in warnings_of(item)
    assert item["effects"][0]["name"] == "Alpha"


def test_a_focus_effect_is_compared_after_both_sides_are_sanitized():
    item = item_of("Focus Effect: Improved​ Healing III", focus_effects=["Improved Healing III", "Improved Healing III", "Other Focus"])
    assert [effect["name"] for effect in item["effects"]] == ["Improved Healing III", "Other Focus"]


def test_a_focus_effect_is_sanitized_once_and_its_raw_text_stays_within_200_characters():
    name = "F" * 200
    item = item_of("Slot: EAR", focus_effects=[name + "<b>"])
    (effect,) = item["effects"]
    assert effect["name"] == name and len(effect["raw"]) <= 200 and effect["raw"].startswith("Focus Effect: F")


# -- zones and tier rule


def test_a_zone_that_sanitizes_to_nothing_is_dropped_and_not_stored_as_an_empty_string():
    item = item_of("Slot: EAR", drops=[{"zone": "​", "npcs": []}, {"zone": "<>", "npcs": ["Boss"]}, {"zone": "Zorblax Keep", "npcs": []}])
    assert item["sources"]["drops"] == [{"zone": None, "npcs": ["Boss"]}, {"zone": "Zorblax Keep", "npcs": []}]
    assert warnings_of(item).count(("empty-value", "zone")) == 2


def test_a_note_on_a_drop_zone_is_sanitized_and_kept():
    item = item_of("Slot: EAR", drops=[{"zone": "Temple of Zorblax", "npcs": ["a wurm"], "notes": ["East <b>mobs", "​", "East mobs"]}])
    assert item["sources"]["drops"] == [{"zone": "Temple of Zorblax", "npcs": ["a wurm"], "notes": ["East bmobs", "East mobs"]}]
    assert ("empty-value", "note") in warnings_of(item)
    many = [f"note {n}" for n in range(15)]
    item = item_of("Slot: EAR", drops=[{"zone": "Zorblax Keep", "npcs": [], "notes": many}])
    assert len(item["sources"]["drops"][0]["notes"]) == 10 and ("list-truncated", "notes") in warnings_of(item)


def test_the_tier_rule_compares_the_flags_without_regard_to_case():
    from trioforge.data.normalize import _tier_rule

    empty = {"drops": [], "sold_by": [], "quests": [], "crafted": []}
    assert _tier_rule("Zorblax Ring", {"Temporary"}, empty) == "spell"
    assert _tier_rule("Zorblax Ring", {"SUMMONED"}, empty) == "spell"
    assert _tier_rule("Zorblax Ring", {"lore"}, empty) == "fixed0"


# -- era tags


def test_era_tags_are_deduplicated_without_regard_to_case_and_the_first_sorting_spelling_is_kept():
    item = item_of("Slot: EAR", era_tags=["Kunark Era", "kunark Era", "FearHateRevamp Era", "Fearhaterevamp Era", "Classic Era"])
    assert item["era_tags"] == ["Classic Era", "FearHateRevamp Era", "Kunark Era"]


def test_at_most_twenty_era_tags_are_kept_with_a_warning():
    item = item_of("Slot: EAR", era_tags=[f"Zorblax{n:02d} Era" for n in range(25)])
    assert len(item["era_tags"]) == 20 and ("list-truncated", "era_tags") in warnings_of(item)
    assert item["era_tags"] == sorted(item["era_tags"])


# -- M6: key matching is ASCII-only


@pytest.mark.parametrize(
    "line",
    ["İNT: 5", "ıNT: 5", "STRİ: 5", "SV İRE: 5", "İ AC: 4", "LORE İTEM", "Clıss: WAR", "DEİTY: Tunare", "Rāce: HUM"],
)
def test_a_key_with_a_dotless_i_or_a_dotted_capital_i_is_no_key_and_never_an_error(line):
    item = item_of(line)
    assert item["stats"] == {} or item["stats"] == {"AC": 4}
    assert item["sv"] == {} and item["deity"] is None
    assert item["parse_warnings"]  # something is unknown


def test_an_unknown_key_after_a_known_one_still_leaves_the_known_one():
    assert item_from("AC: 4 İNT: 5")["stats"] == {"AC": 4}


# -- M8: display fields


def test_a_skill_written_as_an_external_link_keeps_only_its_anchor_text():
    item = item_from("Skill: [https://example.invalid/x Slashing]  Atk Delay: 30")
    assert item["weapon"]["skill"] == "Slashing" and item["parse_warnings"] == []
    assert "example.invalid" not in json.dumps(item) and "http" not in json.dumps(item)
    item = item_from("Skill: https://example.invalid/x Slashing")
    assert item["weapon"]["skill"] == "Slashing"
    item = item_from("Skill: [https://example.invalid/bare]")
    assert item["weapon"] is None and ("empty-value", "skill") in warnings_of(item)


def test_a_type_written_as_a_script_link_loses_its_scheme():
    item = item_from("Type: [[javascript:alert(1)]]")
    assert "javascript" not in json.dumps(item).lower() and item["item_type"] == "alert(1)"
    for block in ("Type: javascript:alert(1)", "Type: JavaScript:alert(1)", "Type: [javascript:alert(1) Shield]", "Type: [javascript&#58;alert(1) Shield]"):
        item = item_from(block)
        assert "javascript" not in json.dumps(item).lower(), block
    assert item_from("Type: [javascript&#58;alert(1) Shield]")["item_type"] == "Shield"
    assert item_from("Type: [java&#115;cript:alert(1) Shield]")["item_type"] == "Shield"


def test_an_item_name_written_as_a_script_link_with_entities_keeps_only_its_anchor_text():
    for itemname in ("[java&#115;cript:alert(1) Zorblax Ring]", "[javascript&#58;alert(1) Zorblax Ring]", "[javascript:alert(1) Zorblax Ring]"):
        assert item_from("Slot: EAR", itemname=itemname)["name"] == "Zorblax Ring", itemname
    assert item_from("Slot: EAR", itemname="[java&amp;#115;cript:alert(1) Zorblax Ring]")["name"] == "[java&#115;cript:alert(1) Zorblax Ring]"


def test_a_display_value_is_decoded_exactly_once():
    item = item_from("Type: Shield &amp;lt; Large")
    assert item["item_type"] == "Shield &lt; Large"


def test_markup_in_a_display_value_is_text_never_live():
    item = item_from("Type: <span class='x'>Shield</span> [[Large|big]] '''bold'''")
    assert item["item_type"] == "Shield big bold"
    item = item_from("Skill: <script>alert(1)</script>")
    assert "<" not in json.dumps(item) and item["weapon"] is not None


# -- the page flags reach the item


def test_page_flags_become_item_flags_in_the_order_of_the_flag_list():
    item = item_of("Lore Equipped", page_flags=["wiki_banner_delete", "removed_note", "bogus_flag"])
    assert item["flags"] == ["lore", "removed_note", "wiki_banner_delete"]
    assert item_of("Slot: EAR")["flags"] == []
    every = item_of("Quest", page_flags=["wiki_banner_revamped", "wiki_banner_dne", "wiki_banner_does_not_exist", "wiki_banner_delete", "removed_note"])
    assert every["flags"] == ["quest", "removed_note", "wiki_banner_delete", "wiki_banner_does_not_exist", "wiki_banner_dne", "wiki_banner_revamped"]


def test_the_schema_knows_the_new_flags_and_the_new_optional_fields(valid_item):
    item = copy.deepcopy(valid_item)
    item["flags"] = list(FLAGS)
    item["charges"] = 3
    item["weapon"] = {"skill": "Archery", "dmg": 11, "delay": 20, "bonus": None, "backstab": 5, "elemental": {"type": "Fire", "value": 4}}
    item["effects"] = [{"kind": "click", "name": "x", "raw": "x", "charges": 2, "required_level": 46}]
    item["sources"]["drops"] = [{"zone": "Zorblax Keep", "npcs": ["a"], "notes": ["note"]}]
    item["parse_warnings"] = [{"code": code, "field": "x"} for code in ("trailing-text", "no-classes", "orphan-continuation")]
    validate_item(item)


@pytest.mark.parametrize(
    "edit",
    [
        lambda i: i.update(charges=-1),
        lambda i: i.update(charges="3"),
        lambda i: i.update(weapon={"skill": None, "dmg": None, "delay": None, "bonus": None, "elemental": {"type": "Plasma", "value": 4}}),
        lambda i: i.update(weapon={"skill": None, "dmg": None, "delay": None, "bonus": None, "elemental": {"type": "Fire"}}),
        lambda i: i.update(weapon={"skill": None, "dmg": None, "delay": None, "bonus": None, "backstab": -1}),
        lambda i: i.update(effects=[{"kind": "click", "name": "x", "raw": "x", "required_level": 0}]),
        lambda i: i["sources"].update(drops=[{"zone": "x", "npcs": [], "notes": []}]),
        lambda i: i["sources"].update(drops=[{"zone": "x", "npcs": [], "notes": ["<b>"]}]),
        lambda i: i.update(flags=["wiki_banner_unknown"]),
    ],
)
def test_the_schema_rejects_bad_new_fields(valid_item, edit):
    with pytest.raises(ValidationError):
        validate_item(broken(valid_item, edit))


def test_a_stat_word_after_prose_is_not_read_as_a_stat():
    # a vendor-value note that sits in a statsblock: its "CHA : 68" is a faction level, not a charisma bonus
    item = item_from("<p><b>VALUE TO VENDOR with CHA : 68 and faction at Zorblax</b></p>")
    assert item["stats"] == {} and warnings_of(item) == [("unparsed-line", "statsblock")]
    item = item_from(lines("AC: 5", "Sold to vendors for HP: 30 each", "STR: 3"))
    assert item["stats"] == {"AC": 5, "STR": 3} and warnings_of(item) == [("unparsed-line", "statsblock")]
    # flags before the first key are fine, and so is a line that starts with a key
    assert item_from("Lore Equipped Slot: EAR AC: 5")["stats"] == {"AC": 5}
    assert item_from("Quest AC: 5  HP: 7")["parse_warnings"] == []


# ---- where an item's type came from (item_type_source) --------------------------------------------------------


def test_a_type_that_the_statsblock_states_says_so():
    for block in (
        "Slot: SECONDARY  Type: Shield",
        lines("Slot: SECONDARY", "AC: 15", "Skill: Shield"),  # "Skill: Shield" makes the item a shield, not a weapon
        lines("Slot: SECONDARY", "Type: Buckler", "Skill: Shield"),
    ):
        item = item_from(block)
        assert item["item_type"] is not None, block
        assert item["item_type_source"] == "statsblock", block


def test_an_item_whose_statsblock_states_no_type_has_no_type_source():
    item = item_from(lines("Slot: SECONDARY", "AC: 15", "WT: 5.0  Size: MEDIUM"))
    assert item["item_type"] is None and item["item_type_source"] is None


def test_the_recorded_pages_say_where_a_shield_type_came_from():
    assert fixture_item("Shield of the Stalwart Seas")["item_type"] == "Shield"
    assert fixture_item("Shield of the Stalwart Seas")["item_type_source"] == "statsblock"
    assert fixture_item("Bladestopper")["item_type"] is None  # a shield that its page does not call one
    assert fixture_item("Bladestopper")["item_type_source"] is None
    assert fixture_item("Engineer's Ring")["item_type_source"] is None


def test_the_type_sources_are_the_three_the_catalog_builder_uses():
    assert list(ITEM_TYPE_SOURCES) == ["statsblock", "name", "hand-list"]
    assert schema()["properties"]["item_type_source"]["enum"] == ["statsblock", "name", "hand-list", None]
    assert "item_type_source" in schema()["required"]


@pytest.mark.parametrize("source", ["statsblock", "name", "hand-list"])
def test_the_schema_accepts_each_type_source(valid_item, source):
    item = copy.deepcopy(valid_item)
    item.update(item_type="Shield", item_type_source=source)
    validate_item(item)


@pytest.mark.parametrize(
    "edit",
    [
        lambda i: i.pop("item_type_source"),
        lambda i: i.update(item_type="Shield", item_type_source="guess"),
        lambda i: i.update(item_type="Shield", item_type_source="Name"),
        lambda i: i.update(item_type="Shield", item_type_source=["name"]),
        lambda i: i.update(item_type="Shield", item_type_source=1),
    ],
)
def test_the_schema_rejects_a_type_source_that_is_not_one_of_the_three(valid_item, edit):
    with pytest.raises(ValidationError):
        validate_item(broken(valid_item, edit))


# ---- Class: NONE and Race: NONE, and a page with no Race line --------------------------------------------------


@pytest.mark.parametrize("line", ["Race: NONE", "Race: None", "RACE: NONE", "race: none"])  # the spellings of the cached pull
def test_race_none_in_any_case_is_an_empty_list_with_the_no_classes_warning(line):
    item = item_from(lines("Slot: EAR", line))
    assert item["races"] == [] and warnings_of(item) == [("no-classes", "race")]


@pytest.mark.parametrize("line", ["Class: NONE", "Class: None", "CLASS: NONE"])
def test_class_none_in_any_case_is_an_empty_list_with_the_no_classes_warning(line):
    item = item_from(lines("Slot: EAR", line))
    assert item["classes"] == [] and warnings_of(item) == [("no-classes", "class")]


def test_a_statsblock_with_a_class_line_and_no_race_line_is_all_races_and_says_nothing():
    item = item_from(lines("Slot: ARMS", "Class: WAR PAL"))  # the shape of a real gear page that forgot its Race line
    assert item["races"] == ["ALL"] and item["classes"] == ["WAR", "PAL"] and item["parse_warnings"] == []


def test_there_is_no_no_races_warning():
    assert "no-races" not in WARNING_CODES
    assert "no-races" not in schema()["$defs"]["warning"]["properties"]["code"]["enum"]


# ---- a hand weapon that cannot be scored (weapon-incomplete) -----------------------------------------------------


@pytest.mark.parametrize(
    "block",
    [
        lines("Slot: PRIMARY", "Skill: 2H Slashing", "Atk Delay: 40"),  # no damage
        lines("Slot: PRIMARY SECONDARY", "Skill: 1H Slashing", "DMG: 9"),  # no delay
        lines("Slot: PRIMARY", "Skill: 2H Blunt"),  # neither
        lines("Slot: SECONDARY", "Skill: Piercing", "DMG: 5"),
        lines("Slot: EAR PRIMARY", "Skill: 2H Slashing", "Atk Delay: 40"),
        lines("Slot: PRIMARY", "Skill: 2H Slashing", "Atk Delay: 0", "DMG: 9"),  # a delay of zero is out of range: no delay
    ],
)
def test_a_hand_weapon_with_a_skill_but_no_damage_or_no_delay_is_weapon_incomplete(block):
    item = normalize(parsed_page(block))
    validate_item(item)
    assert ("weapon-incomplete", "weapon") in warnings_of(item)


@pytest.mark.parametrize(
    "block",
    [
        lines("Slot: PRIMARY", "Skill: 1H Slashing", "Atk Delay: 30", "DMG: 9"),  # complete
        lines("Slot: AMMO", "Skill: Archery", "DMG: 7"),  # ammo has no delay
        lines("Slot: RANGE", "Skill: Archery", "DMG: 5"),  # not held in a hand: ranged damage is not modelled
        lines("Slot: PRIMARY", "DMG: 9"),  # no skill
        lines("Slot: SECONDARY", "AC: 15", "Skill: Shield"),  # a shield is not a weapon
        lines("Skill: 1H Slashing", "DMG: 9"),  # worn nowhere
        lines("Slot: PRIMARY", "AC: 5"),  # not a weapon at all
    ],
)
def test_a_complete_weapon_and_anything_not_held_in_a_hand_is_not_weapon_incomplete(block):
    item = normalize(parsed_page(block))
    assert "weapon-incomplete" not in [code for code, _ in warnings_of(item)]


def test_weapon_incomplete_is_a_property_of_the_weapon_and_the_slots():
    held = {"skill": "2H Slashing", "dmg": None, "delay": 40, "bonus": None}
    for slots in (["PRIMARY"], ["SECONDARY"], ["EAR", "PRIMARY"], ("PRIMARY", "SECONDARY")):
        assert weapon_incomplete(held, slots), slots
    assert weapon_incomplete({**held, "dmg": 9, "delay": None}, ["PRIMARY"])
    assert weapon_incomplete({**held, "dmg": None, "delay": None}, ["PRIMARY"])
    for slots in (["AMMO"], ["RANGE"], ["EAR"], []):
        assert not weapon_incomplete(held, slots), slots
    assert not weapon_incomplete(None, ["PRIMARY"])
    assert not weapon_incomplete({**held, "dmg": 9}, ["PRIMARY"])  # complete
    assert not weapon_incomplete({**held, "skill": None}, ["PRIMARY"])  # no skill: nothing says it is a weapon
    assert not weapon_incomplete({"skill": "1H Blunt", "dmg": 0, "delay": 30, "bonus": None}, ["PRIMARY"])  # a damage of zero is a number


@pytest.mark.parametrize("key", ["Base Dmg", "Base Damage", "base dmg", "BASE DMG"])
def test_base_dmg_is_the_damage_of_a_weapon(key):
    item = item_from(lines("Slot: PRIMARY", "Skill: 1H Blunt", f"{key}: 9", "Atk Delay: 30"))
    assert item["weapon"] == {"skill": "1H Blunt", "dmg": 9, "delay": 30, "bonus": None}
    assert item["parse_warnings"] == []


def test_a_second_damage_line_is_still_a_duplicate_key():
    item = item_from(lines("Slot: PRIMARY", "Skill: 1H Blunt", "DMG: 9", "Base Dmg: 7", "Atk Delay: 30"))
    assert item["weapon"]["dmg"] == 9 and warnings_of(item) == [("duplicate-key", "dmg")]


def test_the_schema_knows_the_weapon_incomplete_code(valid_item):
    item = copy.deepcopy(valid_item)
    item["parse_warnings"] = [{"code": "weapon-incomplete", "field": "weapon"}]
    validate_item(item)
    assert "weapon-incomplete" in WARNING_CODES
