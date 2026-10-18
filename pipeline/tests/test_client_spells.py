"""Tests for the beneficial spell effects read from the client's spell file.

The unit tests build small synthetic ``spells_us.txt`` files under ``tmp_path``: each line has the
shape of a real row (``^`` separated, CRLF line ends, class levels in columns 36 to 51, the effect
slots in the last column) and an invented name. The tests that read the real install folder carry
the ``client`` mark and skip when it is absent.
"""

import calendar
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

import trioforge
from trioforge.sources import client_spells as cs
from trioforge.sources import client_tables as ct

CLIENT_DIR = ct.resolve_client_dir()
HAVE_CLIENT = CLIENT_DIR is not None and (CLIENT_DIR / cs.SPELLS_FILE).is_file()

# The row floor as shipped, captured before any test lowers it.
REAL_FLOORS = dict(ct.MINIMUM_ROWS)


def real_client(test):
    """Mark a test as reading the real install folder, and skip it when the folder is absent."""
    test = pytest.mark.client(test)
    return pytest.mark.skipif(not HAVE_CLIENT, reason="EverQuest Legends client folder not found")(test)


@pytest.fixture(autouse=True)
def small_files(monkeypatch):
    """The synthetic spell files below hold a few spells, so the floor is lowered to one for every
    test; the tests of the floor itself put the planned number back."""
    for name in REAL_FLOORS:
        monkeypatch.setitem(ct.MINIMUM_ROWS, name, 1)


CLASS_ORDER = "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER".split()


def spell_line(
    spell_id,
    name,
    classes,
    effects,
    *,
    good=1,
    target=5,
    duration_formula=3,
    duration_cap=720,
    width=174,
):
    """One row of a synthetic spell file: only the columns the reader uses are filled in."""
    fields = ["0"] * width
    fields[0] = str(spell_id)
    fields[1] = name
    fields[11] = str(duration_formula)
    fields[12] = str(duration_cap)
    fields[28] = str(good)
    fields[30] = str(target)
    for position in range(16):
        fields[36 + position] = "255"
    for code, level in classes.items():
        fields[36 + CLASS_ORDER.index(code)] = str(level)
    fields[-1] = effects
    return "^".join(fields)


def write_spells(path: Path, *lines: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\r\n" for line in lines).encode("utf-8"))
    return path


def read(tmp_path, level, *lines):
    return cs.read_beneficial(write_spells(tmp_path / "spells_us.txt", *lines), level)


MAX_HP = "1|69|250|0|100|0"  # slot 1, SPA 69 (max HP), base 250, no limit, formula 100, no max


# ---- which spells are kept --------------------------------------------------------------------


def test_a_cleric_buff_gets_its_max_hp_value_and_its_class_level(tmp_path):
    result = read(tmp_path, 50, spell_line(1001, "Test Shield", {"CLR": 39}, MAX_HP, target=51))
    assert result["level"] == 50
    assert result["unknown_formulas"] == {}
    assert result["spells"] == [
        {
            "id": 1001,
            "name": "Test Shield",
            "classes": {"CLR": 39},
            "target": 51,
            "duration_ticks": 720,
            "permanent": False,
            "effects": [
                {"slot": 1, "spa": 69, "name": "maxHP", "base": 250, "limit": 0, "formula": 100, "max": 0, "value": 250}
            ],
            "stacking": [],
        }
    ]


def test_a_spell_for_level_51_is_in_the_level_55_file_only(tmp_path):
    lines = [spell_line(1002, "Late Boon", {"CLR": 51}, MAX_HP)]
    assert read(tmp_path, 50, *lines)["spells"] == []
    (late,) = read(tmp_path, 55, *lines)["spells"]
    assert late["classes"] == {"CLR": 51}


def test_classes_lists_only_the_classes_that_have_the_spell_by_that_level(tmp_path):
    line = spell_line(1003, "Shared Boon", {"CLR": 39, "SHM": 55, "BST": 58, "PAL": 255}, MAX_HP)
    assert read(tmp_path, 50, line)["spells"][0]["classes"] == {"CLR": 39}
    assert read(tmp_path, 55, line)["spells"][0]["classes"] == {"CLR": 39, "SHM": 55}


@pytest.mark.parametrize("position", range(16))
def test_the_class_columns_run_in_class_id_order(tmp_path, position):
    code = CLASS_ORDER[position]
    result = read(tmp_path, 50, spell_line(1004, "Order Test", {code: 10}, MAX_HP))
    assert result["spells"][0]["classes"] == {code: 10}


def test_a_detrimental_spell_is_left_out(tmp_path):
    result = read(tmp_path, 50, spell_line(1005, "Test Bane", {"CLR": 10}, MAX_HP, good=0))
    assert result["spells"] == []


# Shaped like two real group-only beneficial spells (flag 2): a bard song that raises endurance
# regeneration by 1 plus an eighth of the level, up to 7, for three ticks; and a druid illusion with a
# run speed and an attack bonus. The names are invented.
JIG_EFFECTS = "1|189|1|0|119|7"
WOLF_EFFECTS = "1|58|796|0|100|3$2|3|30|0|101|60$3|2|1|0|102|30"
GROUP_ONLY = [
    spell_line(2001, "Group Jig", {"BRD": 3}, JIG_EFFECTS, good=2, target=41, duration_formula=7, duration_cap=3),
    spell_line(2002, "Group Wolf", {"DRU": 35}, WOLF_EFFECTS, good=2, target=41, duration_formula=3, duration_cap=360),
]


def test_a_group_only_beneficial_spell_is_kept(tmp_path):
    jig, wolf = read(tmp_path, 50, *GROUP_ONLY)["spells"]
    assert (jig["id"], jig["classes"], jig["target"], jig["duration_ticks"]) == (2001, {"BRD": 3}, 41, 3)
    assert [(e["name"], e["base"], e["max"], e["value"]) for e in jig["effects"]] == [("end_regen", 1, 7, 7)]
    assert (wolf["id"], wolf["classes"], wolf["duration_ticks"]) == (2002, {"DRU": 35}, 360)
    assert [(e["spa"], e["value"]) for e in wolf["effects"]] == [(58, 796), (3, 55), (2, 30)]
    at_55 = read(tmp_path, 55, *GROUP_ONLY)["spells"]
    assert [e["value"] for e in at_55[1]["effects"]] == [796, 57, 30]  # run speed 30 + 55 // 2, under its max of 60


def test_the_beneficial_flag_is_0_for_detrimental_and_1_or_2_for_beneficial(tmp_path):
    def kept(flag, classes=None):
        line = spell_line(1, "Flagged", classes or {"CLR": 10}, MAX_HP, good=flag)
        return read(tmp_path, 50, line)["spells"]

    assert kept(0) == [] and len(kept(1)) == 1 and len(kept(2)) == 1
    for flag in (3, -1, 255):
        with pytest.raises(ValueError, match=r"line 1\b.*beneficial flag"):
            kept(flag)
        with pytest.raises(ValueError, match=r"line 1\b.*beneficial flag"):
            kept(flag, classes={})  # a flag nobody understands is an error whoever could cast the spell


def test_real_data_like_effects_on_formulas_116_117_and_125(tmp_path):
    # shaped like two cleric symbols (max HP and instant HP on formulas 116 and 117) and a druid and
    # shaman regeneration spell (formula 125, a level-52 and level-54 spell); the names are invented
    lines = [
        spell_line(2101, "Test Symbol A", {"CLR": 21, "PAL": 33}, "3|69|94|0|116|158$4|79|94|0|116|158"),
        spell_line(2102, "Test Symbol B", {"CLR": 31, "PAL": 46}, "3|69|224|0|117|307$4|79|224|0|117|307"),
        spell_line(
            2103, "Test Regrowth", {"DRU": 54, "SHM": 52}, "1|0|16|0|125|38", duration_formula=10, duration_cap=205
        ),
    ]
    at_50 = read(tmp_path, 50, *lines)["spells"]
    assert [spell["id"] for spell in at_50] == [2101, 2102]  # nobody has the regrowth by 50
    assert [effect["value"] for spell in at_50 for effect in spell["effects"]] == [158, 158, 307, 307]
    at_55 = read(tmp_path, 55, *lines)["spells"]
    regrowth = at_55[2]
    assert regrowth["classes"] == {"DRU": 54, "SHM": 52}
    assert regrowth["effects"][0]["value"] == 26  # 16 + 2 * (55 - 50), under its max of 38
    assert regrowth["duration_ticks"] == 175  # duration formula 10: 3 * 55 + 10, under the cap of 205


def test_a_spell_no_class_can_use_is_left_out(tmp_path):
    assert read(tmp_path, 50, spell_line(1006, "Item Copy", {}, MAX_HP))["spells"] == []


def test_an_instant_spell_is_left_out(tmp_path):
    result = read(tmp_path, 50, spell_line(1007, "Instant Heal", {"CLR": 10}, "1|0|100|0|100|0", duration_formula=0))
    assert result["spells"] == []


def test_a_permanent_spell_has_no_tick_count(tmp_path):
    (spell,) = read(tmp_path, 50, spell_line(1008, "Forever Boon", {"CLR": 10}, MAX_HP, duration_formula=50))["spells"]
    assert spell["permanent"] is True
    assert spell["duration_ticks"] is None


def test_a_spell_with_no_stat_type_effect_is_left_out(tmp_path):
    only_illusion = "1|58|12|0|100|0"  # SPA 58 is not a stat-type effect
    assert read(tmp_path, 50, spell_line(1009, "Looks Only", {"CLR": 10}, only_illusion))["spells"] == []


def test_other_effects_of_a_kept_spell_stay_with_a_generated_name(tmp_path):
    (spell,) = read(tmp_path, 50, spell_line(1010, "Mixed Boon", {"CLR": 10}, MAX_HP + "$2|58|12|0|100|0"))["spells"]
    assert [(e["slot"], e["spa"], e["name"]) for e in spell["effects"]] == [(1, 69, "maxHP"), (2, 58, "SPA58")]


def test_blank_slots_and_the_charisma_spacer_are_dropped(tmp_path):
    effects = "$".join([MAX_HP, "2|254|0|0|100|0", "3|10|0|0|100|0", "4|10|5|0|100|0", "5|1", ""])
    (spell,) = read(tmp_path, 50, spell_line(1011, "Spacers", {"CLR": 10}, effects))["spells"]
    assert [(e["slot"], e["spa"]) for e in spell["effects"]] == [(1, 69), (4, 10)]


def test_a_spell_with_only_spacers_is_left_out(tmp_path):
    effects = "1|254|0|0|100|0$2|10|0|0|100|0"
    assert read(tmp_path, 50, spell_line(1012, "Nothing Here", {"CLR": 10}, effects))["spells"] == []


def test_limit_effects_are_kept_without_a_value_and_do_not_make_a_spell_qualify(tmp_path):
    with_stat = spell_line(1013, "Limited Haste", {"BRD": 20}, "1|11|20|0|100|0$2|134|61|0|100|0")
    limit_only = spell_line(1014, "Limit Alone", {"BRD": 20}, "1|134|61|0|100|0")
    result = read(tmp_path, 50, with_stat, limit_only)
    assert [spell["name"] for spell in result["spells"]] == ["Limited Haste"]
    limit = result["spells"][0]["effects"][1]
    assert (limit["name"], limit["spa"], limit["base"], limit["value"]) == ("LIMIT", 134, 61, None)


def test_stacking_commands_go_to_stacking_and_never_make_a_spell_qualify(tmp_path):
    effects = MAX_HP + "$3|148|1069|2|100|0$4|149|69|1|100|0"
    (spell,) = read(tmp_path, 50, spell_line(1015, "Stacker", {"CLR": 10}, effects))["spells"]
    assert [e["spa"] for e in spell["effects"]] == [69]
    assert spell["stacking"] == [
        {"slot": 3, "spa": 148, "kind": "148", "base": 1069, "limit": 2, "max": 0},
        {"slot": 4, "spa": 149, "kind": "149", "base": 69, "limit": 1, "max": 0},
    ]
    assert read(tmp_path, 50, spell_line(1016, "Stack Alone", {"CLR": 10}, "1|148|1069|2|100|0"))["spells"] == []


def test_a_stacking_entry_keeps_its_max_the_threshold_of_the_command(tmp_path):
    # SPA 148 / 149 say "this spell does not stack with spells that have a value past this threshold"; the
    # threshold is the max column of the slot (here 1067) and must not be lost
    effects = MAX_HP + "$3|148|1069|2|100|1067$4|149|69|1|100|52.5"
    (spell,) = read(tmp_path, 50, spell_line(1019, "Threshold", {"CLR": 10}, effects))["spells"]
    assert spell["stacking"] == [
        {"slot": 3, "spa": 148, "kind": "148", "base": 1069, "limit": 2, "max": 1067},
        {"slot": 4, "spa": 149, "kind": "149", "base": 69, "limit": 1, "max": 52.5},
    ]
    assert [effect["spa"] for effect in spell["effects"]] == [69]  # still never an effect


def test_spells_come_back_sorted_by_id_and_a_repeated_name_stays_two_spells(tmp_path):
    lines = [spell_line(30, "Twin", {"CLR": 10}, MAX_HP), spell_line(5, "Twin", {"SHM": 12}, MAX_HP)]
    assert [(s["id"], s["name"]) for s in read(tmp_path, 50, *lines)["spells"]] == [(5, "Twin"), (30, "Twin")]


def test_lines_that_do_not_start_with_a_spell_id_are_skipped(tmp_path):
    result = read(tmp_path, 50, "#header", "", spell_line(1017, "Fine Boon", {"CLR": 10}, MAX_HP))
    assert [spell["id"] for spell in result["spells"]] == [1017]


# ---- effect values and unknown formulas -------------------------------------------------------


def test_the_value_depends_on_the_level_it_is_asked_for(tmp_path):
    line = spell_line(1018, "Growing Boon", {"CLR": 10}, "1|1|100|0|102|0")  # AC: base 100 + level
    assert read(tmp_path, 50, line)["spells"][0]["effects"][0]["value"] == 150
    assert read(tmp_path, 55, line)["spells"][0]["effects"][0]["value"] == 155


def test_a_formula_the_reader_does_not_know_is_counted_and_has_no_value(tmp_path):
    lines = [
        spell_line(1019, "Odd Boon", {"CLR": 10}, "1|4|10|0|999|0$2|5|10|0|999|0$3|6|10|0|1005|0"),
        spell_line(1020, "Odd Bane", {"CLR": 10}, "1|4|10|0|777|0", good=0),  # not kept, so not counted
    ]
    result = read(tmp_path, 50, *lines)
    assert result["unknown_formulas"] == {"999": 2, "1005": 1}
    assert [e["value"] for e in result["spells"][0]["effects"]] == [None, None, None]


def test_an_effect_number_with_a_decimal_point_is_kept_as_a_decimal(tmp_path):
    (spell,) = read(tmp_path, 50, spell_line(1021, "Half Boon", {"CLR": 10}, "1|4|-1.5|0|100|0"))["spells"]
    assert spell["effects"][0]["base"] == -1.5
    assert spell["effects"][0]["value"] == -1.5


# formula_value(base, formula, max, level) -> value; each case is worked out by hand from the
# client's rules: the formula grows |base| with the level, max stops the growth, and a negative
# base keeps the value negative.
FORMULA_CASES = [
    pytest.param(250, 100, 0, 50, 250, id="100-is-the-base"),
    pytest.param(250, 0, 0, 50, 250, id="0-is-the-base"),
    pytest.param(150, 103, 250, 50, 250, id="103-base-plus-2L-stops-at-max"),
    pytest.param(150, 103, 250, 40, 230, id="103-below-the-max"),
    pytest.param(100, 102, 0, 50, 150, id="102-base-plus-L"),
    pytest.param(100, 101, 0, 51, 125, id="101-base-plus-half-L-rounded-down"),
    pytest.param(100, 104, 0, 10, 130, id="104-base-plus-3L"),
    pytest.param(100, 105, 0, 10, 140, id="105-base-plus-4L"),
    pytest.param(100, 108, 0, 50, 116, id="108-base-plus-third-L"),
    pytest.param(100, 109, 0, 50, 112, id="109-base-plus-quarter-L"),
    pytest.param(100, 110, 0, 50, 110, id="110-base-plus-fifth-L"),
    pytest.param(100, 111, 0, 50, 304, id="111-base-plus-6-per-level-above-16"),
    pytest.param(100, 112, 0, 50, 308, id="112-base-plus-8-per-level-above-24"),
    pytest.param(100, 113, 0, 50, 260, id="113-base-plus-10-per-level-above-34"),
    pytest.param(100, 114, 0, 50, 190, id="114-base-plus-15-per-level-above-44"),
    pytest.param(34, 115, 73, 50, 73, id="115-grows-then-stops-at-max"),
    pytest.param(34, 115, 0, 15, 34, id="115-no-growth-up-to-level-15"),
    pytest.param(406, 118, 525, 50, 525, id="118-stops-at-max"),
    pytest.param(406, 118, 525, 44, 406, id="118-no-growth-up-to-level-44"),
    pytest.param(406, 118, 0, 50, 526, id="118-uncapped"),
    # 116, 117 and 125 with the numbers of real spells: max HP of two cleric symbols
    # (base 94, max 158 and base 224, max 307), which reach their max well before level 50, and the
    # hit point regeneration of a druid and shaman spell (base 16, max 38). The multiplier above the
    # start level of 116 and 117 (10 and 12) is the one ported from the research script; at levels
    # 50 and 55 it does not matter, because both spells are stopped by their max by then.
    pytest.param(94, 116, 158, 50, 158, id="116-real-symbol-is-stopped-by-its-max"),
    pytest.param(94, 116, 158, 55, 158, id="116-real-symbol-at-55"),
    pytest.param(94, 116, 158, 24, 94, id="116-no-growth-up-to-level-24"),
    pytest.param(94, 116, 0, 30, 154, id="116-grows-10-per-level-above-24"),
    pytest.param(224, 117, 307, 50, 307, id="117-real-symbol-is-stopped-by-its-max"),
    pytest.param(224, 117, 307, 55, 307, id="117-real-symbol-at-55"),
    pytest.param(224, 117, 307, 34, 224, id="117-no-growth-up-to-level-34"),
    pytest.param(224, 117, 0, 40, 296, id="117-grows-12-per-level-above-34"),
    pytest.param(16, 125, 38, 55, 26, id="125-real-regrowth-grows-2-per-level-above-50"),
    pytest.param(16, 125, 38, 50, 16, id="125-no-growth-up-to-level-50"),
    pytest.param(16, 125, 38, 70, 38, id="125-stopped-by-its-max"),
    pytest.param(-125, 125, 0, 55, -135, id="125-negative-base-grows-in-size"),
    pytest.param(75, 125, 50, 55, 65, id="125-a-max-below-the-base-shrinks-it"),
    pytest.param(1, 119, 0, 50, 7, id="119-base-plus-eighth-L"),
    pytest.param(100, 121, 0, 50, 116, id="121-base-plus-third-L"),
    pytest.param(100, 139, 0, 50, 110, id="139-half-a-point-per-level-above-30"),
    pytest.param(5, 3, 0, 50, 155, id="below-100-is-base-plus-L-times-formula"),
    pytest.param(100, 2002, 0, 50, 10100, id="2000s-multiply-the-base"),
    pytest.param(-100, 103, 150, 36, -150, id="negative-base-grows-in-size-to-max"),
    pytest.param(-100, 103, 0, 36, -172, id="negative-base-uncapped"),
    pytest.param(-100, 100, 0, 50, -100, id="negative-base-formula-100"),
    pytest.param(250, 60, 0, 50, 2, id="60-divides-by-100"),
]


@pytest.mark.parametrize(("base", "formula", "maximum", "level", "expected"), FORMULA_CASES)
def test_formula_values(base, formula, maximum, level, expected):
    assert cs.formula_value(base, formula, maximum, level) == (expected, True)


@pytest.mark.parametrize("formula", [200, 999, 1001, 1002, 5000, -1, 133])
def test_an_unknown_formula_has_no_value(formula):
    assert cs.formula_value(10, formula, 0, 50) == (None, False)


# duration_ticks(formula, cap, level) -> (ticks, permanent); worked out by hand from the client's rules.
DURATION_CASES = [
    pytest.param(3, 720, 50, (720, False), id="3-is-30-per-level-stopped-by-the-cap"),
    pytest.param(3, 0, 10, (300, False), id="3-without-a-cap"),
    pytest.param(1, 0, 50, (25, False), id="1-is-half-the-level"),
    pytest.param(1, 0, 49, (25, False), id="1-rounds-up"),
    pytest.param(2, 0, 50, (30, False), id="2-is-six-tenths-of-the-level"),
    pytest.param(4, 0, 50, (50, False), id="4-is-50-without-a-cap"),
    pytest.param(4, 20, 50, (20, False), id="4-is-the-cap-when-there-is-one"),
    pytest.param(5, 0, 50, (2, False), id="5-is-2"),
    pytest.param(6, 0, 50, (27, False), id="6-is-half-the-level-plus-2"),
    pytest.param(7, 0, 50, (50, False), id="7-is-the-level"),
    pytest.param(8, 0, 50, (60, False), id="8-is-the-level-plus-10"),
    pytest.param(9, 90, 50, (90, False), id="9-is-2L-plus-10-stopped-by-the-cap"),
    pytest.param(10, 0, 50, (160, False), id="10-is-3L-plus-10"),
    pytest.param(11, 0, 50, (1590, False), id="11-is-30-times-level-plus-3"),
    pytest.param(12, 0, 50, (12, False), id="12-is-a-quarter-of-the-level"),
    pytest.param(12, 0, 2, (1, False), id="12-is-at-least-1"),
    pytest.param(13, 0, 50, (210, False), id="13-is-4L-plus-10"),
    pytest.param(14, 0, 50, (260, False), id="14-is-5L-plus-10"),
    pytest.param(15, 0, 50, (300, False), id="15-is-5L-plus-50"),
    pytest.param(3600, 0, 50, (3600, False), id="3600-is-3600"),
    pytest.param(0, 0, 50, (0, False), id="0-is-instant"),
    pytest.param(50, 0, 50, (None, True), id="50-is-permanent"),
    pytest.param(51, 99, 50, (None, True), id="51-is-permanent"),
    pytest.param(77, 40, 50, (40, False), id="an-unknown-formula-lasts-as-long-as-its-cap"),
]


@pytest.mark.parametrize(("formula", "cap", "level", "expected"), DURATION_CASES)
def test_duration_ticks(formula, cap, level, expected):
    assert cs.duration_ticks(formula, cap, level) == expected


def test_the_stat_effect_names_are_the_ported_map():
    assert cs.STAT_SPA[69] == "maxHP"
    assert cs.STAT_SPA[1] == "AC"
    assert cs.STAT_SPA[11] == "haste"
    assert len(cs.STAT_SPA) == 65
    assert not set(cs.STAT_SPA) & set(cs.LIMIT_SPA)
    assert not set(cs.STAT_SPA) & {148, 149}


# ---- the file layout --------------------------------------------------------------------------


@pytest.mark.parametrize("width", [173, 174, 180])
def test_the_effect_slots_are_read_from_the_last_column_whatever_the_width(tmp_path, width):
    (spell,) = read(tmp_path, 50, spell_line(1030, "Wide Boon", {"CLR": 39}, MAX_HP, width=width))["spells"]
    assert spell["effects"][0]["value"] == 250 and spell["classes"] == {"CLR": 39}


@pytest.mark.parametrize("level", [0, -1, 255, 50.0, True, "50", None])
def test_a_level_that_is_not_a_whole_number_from_1_to_254_is_refused(tmp_path, level):
    path = write_spells(tmp_path / "spells_us.txt", spell_line(1, "Fine Boon", {"CLR": 10}, MAX_HP))
    with pytest.raises(ValueError, match="level"):
        cs.read_beneficial(path, level)


def test_a_numbered_row_that_is_too_short_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="line 2"):
        read(
            tmp_path,
            50,
            spell_line(1031, "Fine Boon", {"CLR": 39}, MAX_HP),
            spell_line(1032, "Short", {}, "", width=100),
        )


def test_a_class_column_that_is_not_a_number_is_an_error_naming_the_line(tmp_path):
    bad = spell_line(1033, "Bad Level", {"CLR": 39}, MAX_HP).split("^")
    bad[37] = "x"
    with pytest.raises(ValueError, match="line 1"):
        read(tmp_path, 50, "^".join(bad))


def test_an_effect_group_that_is_not_numeric_is_an_error_naming_the_line(tmp_path):
    with pytest.raises(ValueError, match="line 1"):
        read(tmp_path, 50, spell_line(1034, "Bad Slot", {"CLR": 39}, "1|69|lots|0|100|0"))


def test_a_layout_with_no_effect_slots_in_the_last_column_is_refused(tmp_path):
    lines = [spell_line(2000 + n, f"Spell {n}", {"CLR": 10}, "0") for n in range(120)]
    with pytest.raises(ValueError, match="layout"):
        read(tmp_path, 50, *lines)


# ---- fail closed on bad input ------------------------------------------------------------------


@pytest.mark.parametrize("junk", ["junk", "SECRETWORD^x", "12x^name", "SECRETWORD"])
def test_a_line_that_is_not_a_spell_row_is_an_error_naming_the_line_but_not_showing_it(tmp_path, junk):
    with pytest.raises(ValueError, match=r"line 2\b") as caught:
        read(tmp_path, 50, spell_line(1, "Fine Boon", {"CLR": 10}, MAX_HP), junk)
    assert "SECRETWORD" not in str(caught.value) and "junk" not in str(caught.value)


def test_only_blank_and_hash_lines_are_skipped(tmp_path):
    result = read(tmp_path, 50, "", "# a note", spell_line(1, "Fine Boon", {"CLR": 10}, MAX_HP), "   ", "#another")
    assert [spell["id"] for spell in result["spells"]] == [1]


def test_a_byte_above_127_is_an_error_naming_the_line(tmp_path):
    path = write_spells(tmp_path / "spells_us.txt", spell_line(1, "Fine Boon", {"CLR": 10}, MAX_HP))
    path.write_bytes(path.read_bytes() + b"# caf\xe9\r\n")  # even a comment must be plain ASCII
    with pytest.raises(ValueError, match=r"line 2\b.*ASCII") as caught:
        cs.read_beneficial(path, 50)
    assert "caf" not in str(caught.value)
    with pytest.raises(ValueError, match=r"line 1\b.*ASCII"):
        read(tmp_path, 50, spell_line(1, "Café Boon", {"CLR": 10}, MAX_HP))  # written as UTF-8


def test_a_byte_order_mark_does_not_hide_the_first_spell(tmp_path):
    path = write_spells(tmp_path / "spells_us.txt", spell_line(1, "Fine Boon", {"CLR": 10}, MAX_HP))
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert [spell["id"] for spell in cs.read_beneficial(path, 50)["spells"]] == [1]


@pytest.mark.parametrize("lines", [[], [""], ["# only a note"]], ids=["empty-file", "blank-line", "only-a-comment"])
def test_a_spell_file_with_no_rows_is_an_error(tmp_path, lines):
    with pytest.raises(ValueError, match="no data rows"):
        read(tmp_path, 50, *lines)


def test_every_row_must_have_the_same_number_of_columns(tmp_path):
    lines = [
        spell_line(1, "Fine Boon", {"CLR": 10}, MAX_HP, width=174),
        spell_line(2, "Wide Boon", {"CLR": 10}, MAX_HP, width=175),
    ]
    with pytest.raises(ValueError, match=r"line 2\b.*columns"):
        read(tmp_path, 50, *lines)


def test_a_repeated_spell_id_is_an_error_naming_the_second_line(tmp_path):
    lines = [
        spell_line(7, "A", {"CLR": 10}, MAX_HP),
        spell_line(8, "B", {"CLR": 10}, MAX_HP),
        spell_line(7, "C", {"CLR": 10}, MAX_HP),
    ]
    with pytest.raises(ValueError, match=r"line 3\b.*duplicate"):
        read(tmp_path, 50, *lines)
    nobody = [spell_line(9, "A", {}, MAX_HP, good=0), spell_line(9, "B", {}, MAX_HP, good=0)]
    with pytest.raises(ValueError, match=r"line 2\b.*duplicate"):  # also among rows that would not be kept
        read(tmp_path, 50, *nobody)


@pytest.mark.parametrize("value", ["256", "-1", "1000"])
def test_a_class_level_outside_0_to_255_is_an_error(tmp_path, value):
    fields = spell_line(1, "Bad Level", {"CLR": 39}, MAX_HP).split("^")
    fields[37] = value
    with pytest.raises(ValueError, match=r"line 1\b.*out of range"):
        read(tmp_path, 50, "^".join(fields))


@pytest.mark.parametrize(
    ("column", "what"),
    [(11, "duration formula"), (12, "duration cap"), (30, "target")],
    ids=["duration-formula", "duration-cap", "target"],
)
def test_a_negative_number_in_a_column_of_a_kept_spell_is_an_error(tmp_path, column, what):
    fields = spell_line(1, "Bad Number", {"CLR": 10}, MAX_HP).split("^")
    fields[column] = "-1"
    with pytest.raises(ValueError, match=rf"line 1\b.*{what}.*out of range"):
        read(tmp_path, 50, "^".join(fields))


def test_a_spell_nobody_can_cast_is_not_checked_beyond_its_class_and_flag_columns(tmp_path):
    # The real file has one such row: a decimal duration cap on a spell that no class gets. The
    # same cap on a spell somebody can cast is an error.
    fields = spell_line(73879, "Odd Cap", {}, MAX_HP).split("^")
    fields[12] = "20.5"
    assert read(tmp_path, 50, "^".join(fields))["spells"] == []
    fields = spell_line(73879, "Odd Cap", {"CLR": 10}, MAX_HP).split("^")
    fields[12] = "20.5"
    with pytest.raises(ValueError, match=r"line 1\b.*duration cap"):
        read(tmp_path, 50, "^".join(fields))


@pytest.mark.parametrize(
    "group",
    ["-1|69|250|0|100|0", "1|-69|250|0|100|0", "1|69|250|0|-100|0", "1|69|250|0|100|0|9"],
    ids=["slot-negative", "effect-id-negative", "formula-negative", "seventh-value"],
)
def test_an_effect_slot_that_is_out_of_range_or_has_a_seventh_value_is_an_error(tmp_path, group):
    with pytest.raises(ValueError, match=r"line 1\b"):
        read(tmp_path, 50, spell_line(1, "Bad Slot", {"CLR": 10}, group))


# ---- the command line -------------------------------------------------------------------------


def make_client(root: Path) -> Path:
    spells = [
        spell_line(1001, "Test Shield", {"CLR": 39}, MAX_HP, target=51),
        spell_line(1002, "Late Boon", {"CLR": 51}, MAX_HP),
        spell_line(1019, "Odd Boon", {"CLR": 10}, "1|4|10|0|999|0"),
    ]
    path = write_spells(root / cs.SPELLS_FILE, *spells)
    stamp = calendar.timegm((2026, 10, 12, 12, 0, 0))  # noon UTC
    os.utime(path, (stamp, stamp))
    return root


def run_cli(client: Path, out: Path, *extra: str) -> int:
    return cs.main(["--client-dir", str(client), "--out", str(out), "--date", "2026-10-13", *extra])


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_cli_writes_a_file_per_level(tmp_path, capsys):
    client = make_client(tmp_path / "client")
    out = tmp_path / "out"
    assert run_cli(client, out) == 0
    assert sorted(path.name for path in out.iterdir()) == ["manifest.json", "spells-l50.json", "spells-l55.json"]
    l50, l55 = load(out / "spells-l50.json"), load(out / "spells-l55.json")
    assert (l50["level"], l55["level"]) == (50, 55)
    assert [s["id"] for s in l50["spells"]] == [1001, 1019]
    assert [s["id"] for s in l55["spells"]] == [1001, 1002, 1019]
    assert l50["unknown_formulas"] == {"999": 1}
    assert "spells-l50.json: 2 spells" in capsys.readouterr().out


def test_the_cli_files_carry_provenance_with_the_input_hash(tmp_path):
    client = make_client(tmp_path / "client")
    out = tmp_path / "out"
    assert run_cli(client, out) == 0
    digest = hashlib.sha256((client / cs.SPELLS_FILE).read_bytes()).hexdigest()
    for name in ("spells-l50.json", "spells-l55.json"):
        assert load(out / name)["provenance"] == {
            "inputs": [{"file": "spells_us.txt", "sha256": digest, "date": "2026-10-12"}],
            "generator": f"trioforge.sources.client_spells {trioforge.__version__}",
            "generated": "2026-10-13",
        }


def test_the_cli_adds_the_spell_file_to_a_manifest_the_tables_wrote(tmp_path):
    client = make_client(tmp_path / "client")
    out = tmp_path / "out"
    table = {"file": "Resources/ZoneNames.txt", "sha256": "a" * 64, "date": "2026-09-21"}
    earlier = {"file": "zones.json", "inputs": [table["file"]], "generated": "2026-10-12"}
    ct.update_manifest(out, [table], [earlier], "2026-10-12")
    assert run_cli(client, out) == 0
    manifest = load(out / "manifest.json")
    assert [item["file"] for item in manifest["inputs"]] == ["Resources/ZoneNames.txt", "spells_us.txt"]
    assert manifest["generated"] == "2026-10-13"
    assert {entry["file"]: entry["inputs"] for entry in manifest["outputs"]} == {
        "zones.json": ["Resources/ZoneNames.txt"],
        "spells-l50.json": ["spells_us.txt"],
        "spells-l55.json": ["spells_us.txt"],
    }


def test_no_derived_spell_file_names_a_local_path(tmp_path):
    client = make_client(tmp_path / "client")
    out = tmp_path / "out"
    assert run_cli(client, out) == 0
    for path in out.iterdir():
        text = path.read_text(encoding="utf-8")
        assert str(tmp_path) not in text and tmp_path.as_posix() not in text
        assert not re.search(r"[A-Za-z]:[\\/]", text), path.name


def test_the_cli_output_is_byte_for_byte_repeatable(tmp_path):
    client = make_client(tmp_path / "client")
    assert run_cli(client, tmp_path / "one") == 0
    assert run_cli(client, tmp_path / "two") == 0
    for path in (tmp_path / "one").iterdir():
        assert path.read_bytes() == (tmp_path / "two" / path.name).read_bytes()


def test_a_missing_spell_file_stops_the_cli_with_exit_2(tmp_path, capsys):
    out = tmp_path / "out"
    assert run_cli(tmp_path / "empty-client", out) == 2
    assert cs.SPELLS_FILE in capsys.readouterr().err
    assert not out.exists()


def test_a_malformed_spell_file_stops_the_cli_with_exit_2_and_writes_nothing(tmp_path, capsys):
    client = make_client(tmp_path / "client")
    write_spells(client / cs.SPELLS_FILE, spell_line(1, "Bad Slot", {"CLR": 39}, "1|69|lots|0|100|0"))
    out = tmp_path / "out"
    assert run_cli(client, out) == 2
    assert "spells_us.txt" in capsys.readouterr().err
    assert not out.exists()


def test_the_cli_without_a_client_folder_says_what_to_set(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv(ct.ENV_CLIENT_DIR, raising=False)
    monkeypatch.delenv("PUBLIC", raising=False)
    assert cs.main(["--out", str(tmp_path / "out")]) == 2
    assert ct.ENV_CLIENT_DIR in capsys.readouterr().err


def test_the_default_run_date_is_the_utc_date(tmp_path, monkeypatch):
    client = make_client(tmp_path / "client")
    monkeypatch.setattr(ct, "today_utc", lambda: "2031-02-03")
    assert cs.main(["--client-dir", str(client), "--out", str(tmp_path / "out")]) == 0
    assert load(tmp_path / "out" / "spells-l50.json")["provenance"]["generated"] == "2031-02-03"
    assert load(tmp_path / "out" / "manifest.json")["generated"] == "2031-02-03"


def test_the_file_date_in_the_provenance_is_the_utc_date(tmp_path):
    client = make_client(tmp_path / "client")
    path = client / cs.SPELLS_FILE
    stamp = calendar.timegm((2026, 10, 13, 2, 30, 0))  # 21:30 on the 12th in Chicago, still the 13th in UTC
    os.utime(path, (stamp, stamp))
    assert run_cli(client, tmp_path / "out") == 0
    assert load(tmp_path / "out" / "spells-l50.json")["provenance"]["inputs"][0]["date"] == "2026-10-13"


@pytest.mark.parametrize(
    "error",
    [PermissionError("denied\nin two lines"), ValueError("bad\nthing"), OSError("device gone")],
    ids=["permission-error", "value-error", "os-error"],
)
def test_any_os_or_value_error_ends_the_cli_with_exit_2_and_a_one_line_message(tmp_path, monkeypatch, capsys, error):
    client = make_client(tmp_path / "client")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(ct, "read_checked", fail)
    assert run_cli(client, tmp_path / "out") == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and err.count("\n") == 1


# ---- the row floor ----------------------------------------------------------------------------


def filler(count: int, start: int = 5000) -> list[str]:
    return [spell_line(start + n, f"Filler {n}", {"CLR": 10}, MAX_HP) for n in range(count)]


def test_a_spell_file_with_fewer_beneficial_spells_than_the_floor_stops_the_cli(tmp_path, monkeypatch, capsys):
    floor = REAL_FLOORS["spells"]
    monkeypatch.setitem(ct.MINIMUM_ROWS, "spells", floor)
    client, out = tmp_path / "client", tmp_path / "out"
    write_spells(client / cs.SPELLS_FILE, *filler(floor - 1))
    assert run_cli(client, out) == 2
    assert cs.SPELLS_FILE in capsys.readouterr().err
    assert not out.exists()
    write_spells(client / cs.SPELLS_FILE, *filler(floor))
    assert run_cli(client, out) == 0


def test_the_spell_floor_counts_the_spells_kept_at_each_level_not_the_rows(tmp_path, monkeypatch, capsys):
    floor = REAL_FLOORS["spells"]
    monkeypatch.setitem(ct.MINIMUM_ROWS, "spells", floor)
    client, out = tmp_path / "client", tmp_path / "out"
    banes = [spell_line(9000 + n, f"Bane {n}", {"CLR": 10}, MAX_HP, good=0) for n in range(300)]
    write_spells(client / cs.SPELLS_FILE, *filler(floor - 1), *banes)  # plenty of rows, too few beneficial spells
    assert run_cli(client, out) == 2
    assert "level 50" in capsys.readouterr().err and not out.exists()
    late = [spell_line(9500 + n, f"Late {n}", {"CLR": 52}, MAX_HP) for n in range(floor)]
    write_spells(client / cs.SPELLS_FILE, *late)  # enough at level 55, none at level 50
    assert run_cli(client, out) == 2
    assert "level 50" in capsys.readouterr().err and not out.exists()


# ---- atomic output ------------------------------------------------------------------------------


def snapshot(folder: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir()) if path.is_file()}


def first_run(tmp_path: Path):
    client = make_client(tmp_path / "client")
    out = tmp_path / "out"
    assert run_cli(client, out) == 0
    return client, out, snapshot(out)


def test_a_rerun_replaces_every_file_and_leaves_no_temporary_file(tmp_path):
    client, out, before = first_run(tmp_path)
    assert run_cli(client, out, "--date", "2026-10-14") == 0
    after = snapshot(out)
    assert sorted(after) == sorted(before) == ["manifest.json", "spells-l50.json", "spells-l55.json"]
    assert all(after[name] != before[name] for name in after)


def test_the_manifest_is_put_in_place_last(tmp_path, monkeypatch):
    real_replace = os.replace
    targets: list[str] = []

    def recording_replace(source, target):
        targets.append(Path(target).name)
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", recording_replace)
    assert run_cli(make_client(tmp_path / "client"), tmp_path / "out") == 0
    assert sorted(targets[:-1]) == ["spells-l50.json", "spells-l55.json"] and targets[-1] == "manifest.json"


def test_an_invalid_manifest_stops_the_cli_before_any_file_is_touched(tmp_path, capsys):
    client, out, _ = first_run(tmp_path)
    (out / "manifest.json").write_text('{"inputs": 5, "outputs": []}', encoding="utf-8")
    before = snapshot(out)
    capsys.readouterr()
    assert run_cli(client, out, "--date", "2026-10-14") == 2
    assert "manifest" in capsys.readouterr().err
    assert snapshot(out) == before


def test_a_failure_while_rendering_leaves_the_old_files_alone(tmp_path, monkeypatch, capsys):
    client, out, before = first_run(tmp_path)
    real_render = ct.render_json
    calls: list[int] = []

    def fail_on_the_manifest(data):
        calls.append(1)
        if len(calls) == 3:  # two spell files, then the manifest: the last text to be made
            raise ValueError("cannot render")
        return real_render(data)

    monkeypatch.setattr(ct, "render_json", fail_on_the_manifest)
    capsys.readouterr()
    assert run_cli(client, out, "--date", "2026-10-14") == 2
    assert "cannot render" in capsys.readouterr().err
    assert snapshot(out) == before


def test_a_failure_while_putting_the_files_in_place_puts_the_old_ones_back(tmp_path, monkeypatch, capsys):
    client, out, before = first_run(tmp_path)
    real_replace = os.replace
    calls: list[str] = []

    def lock_the_second(source, target):
        calls.append(Path(target).name)
        if len(calls) == 2:
            raise PermissionError("locked by another program")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", lock_the_second)
    capsys.readouterr()
    assert run_cli(client, out, "--date", "2026-10-14") == 2
    assert "locked by another program" in capsys.readouterr().err
    assert snapshot(out) == before


# ---- the real client --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real():
    """The real spell file read at both levels, once."""
    return {level: cs.read_beneficial(CLIENT_DIR / cs.SPELLS_FILE, level) for level in cs.LEVELS}


def named(result, name):
    return [spell for spell in result["spells"] if spell["name"] == name]


def max_hp(spell):
    return [effect for effect in spell["effects"] if effect["spa"] == 69]


@real_client
def test_talisman_of_altuna_gives_shamans_250_max_hp_at_level_50(real):
    (talisman,) = named(real[50], "Talisman of Altuna")
    assert talisman["classes"] == {"SHM": 40}
    (hp,) = max_hp(talisman)
    assert (hp["base"], hp["formula"], hp["max"]) == (150, 103, 250)
    assert hp["value"] == 250


@real_client
def test_symbol_of_naltrons_max_hp_value_is_reported(real, capsys):
    values = {}
    for level in cs.LEVELS:
        (symbol,) = named(real[level], "Symbol of Naltron")
        (hp,) = max_hp(symbol)
        values[level] = hp["value"]
        assert symbol["classes"] == {"CLR": 41}
        assert (hp["base"], hp["formula"], hp["max"]) == (406, 118, 525)
    with capsys.disabled():
        print(f"\nSymbol of Naltron max HP: level 50 -> {values[50]}, level 55 -> {values[55]} (base 406, cap 525)")
    assert values[50] in (406, 525) and values[55] in (406, 525)


@real_client
def test_the_real_file_is_read_with_the_expected_shape_at_both_levels(real, capsys):
    with capsys.disabled():
        for level in cs.LEVELS:
            result = real[level]
            print(f"\nlevel {level}: {len(result['spells'])} spells, unknown formulas {result['unknown_formulas']}")
    assert len(real[55]["spells"]) > len(real[50]["spells"]) > 100
    for level in cs.LEVELS:
        for spell in real[level]["spells"]:
            assert spell["classes"] and all(0 < at <= level for at in spell["classes"].values())
            assert any(effect["spa"] in cs.STAT_SPA for effect in spell["effects"])
            assert spell["permanent"] or spell["duration_ticks"] > 0
            assert all(spell_effect["spa"] not in (148, 149) for spell_effect in spell["effects"])
    ids = [spell["id"] for spell in real[50]["spells"]]
    assert ids == sorted(set(ids))


@real_client
def test_every_unknown_formula_in_the_real_file_is_counted_and_has_no_value(real):
    for level in cs.LEVELS:
        result = real[level]
        effects = [effect for spell in result["spells"] for effect in spell["effects"]]
        missing = sum(1 for effect in effects if effect["name"] != "LIMIT" and effect["value"] is None)
        assert missing == sum(result["unknown_formulas"].values())


@real_client
def test_group_only_beneficial_spells_are_in_the_real_output_at_both_levels(real):
    # both of these carry the beneficial flag 2 in the client file
    raw_flags = {}
    with (CLIENT_DIR / cs.SPELLS_FILE).open("rb") as handle:
        for line in handle:
            fields = line.decode("ascii").split("^")
            if fields[1] in ("Jaxan's Jig o` Vigor", "Share Wolf Form"):
                raw_flags[fields[1]] = fields[28]
    assert raw_flags == {"Jaxan's Jig o` Vigor": "2", "Share Wolf Form": "2"}
    for level in cs.LEVELS:
        (jig,) = named(real[level], "Jaxan's Jig o` Vigor")
        assert (jig["classes"], jig["target"]) == ({"BRD": 3}, 41)
        (wolf,) = named(real[level], "Share Wolf Form")
        assert (wolf["classes"], wolf["target"]) == ({"DRU": 35}, 41)
