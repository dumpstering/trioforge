"""Tests for the race and class tables: rules/races.json and trioforge.data.races.

The tables come from public sources (EQL Tools' published attributes table, and the race pages of
eqlwiki for the primary classes). The loader refuses a file that drifts; the failing cases below
change one thing in a copy of the real file and expect that thing to be named.
"""

import copy
import json
import re
from itertools import combinations
from pathlib import Path

import pytest

from trioforge.data import races
from trioforge.data.races import RacesError, load, naked_stats

REPO_ROOT = Path(__file__).resolve().parents[2]
RACES_PATH = REPO_ROOT / "rules" / "races.json"

# Written out here on purpose, so these tests do not trust the module they are checking.
RACE_CODES = "HUM BAR ERU ELF HIE DEF HEF DWF TRL OGR HFL GNM IKS KER FRG HDE".split()
CLASS_CODES = "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER".split()
STATS = ["STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA"]

# What no public file may mention: the game's client program, an address inside it, or an offset.
# Built from pieces so that a repository-wide search for these words stays empty.
FORBIDDEN_WORDS = ("eq" + "game", "." + "exe", "0" + "x", "off" + "set")
FORBIDDEN_CAPITALS = "R" + "VA"  # case-sensitive: its lowercase form sits inside ordinary words

# The primary-class table of the race pages, typed in again.
PRIMARY_CLASSES = {
    "HUM": "BRD CLR DRU ENC MAG MNK NEC PAL RNG ROG SHD WAR WIZ",
    "BAR": "BST BER ROG SHM WAR",
    "ERU": "CLR ENC MAG NEC PAL SHD WIZ",
    "ELF": "BRD DRU RNG ROG WAR",
    "HIE": "CLR ENC MAG PAL WIZ",
    "DEF": "CLR ENC MAG NEC ROG SHD WAR WIZ",
    "HEF": "BRD DRU PAL RNG ROG WAR",
    "DWF": "BER CLR PAL ROG WAR",
    "TRL": "BST BER SHD SHM WAR",
    "OGR": "BST BER SHD SHM WAR",
    "HFL": "CLR DRU PAL RNG ROG WAR",
    "GNM": "CLR ENC MAG NEC PAL SHD ROG WAR WIZ",
    "IKS": "BST MNK NEC SHD SHM WAR",
    "KER": "BRD BER BST DRU ROG SHM WAR",
    "FRG": "CLR MNK NEC PAL ROG SHD SHM WAR WIZ",
    "HDE": "BRD BER ENC NEC RNG ROG SHD",
}


@pytest.fixture(scope="module")
def data():
    return load()


def race(data, code):
    (found,) = [r for r in data["races"] if r["code"] == code]
    return found


def klass(data, code):
    (found,) = [c for c in data["classes"] if c["code"] == code]
    return found


# ---- the real file ----------------------------------------------------------------------------


def test_the_sixteen_races_are_present_in_code_order(data):
    assert [r["code"] for r in data["races"]] == RACE_CODES
    assert [c["code"] for c in data["classes"]] == CLASS_CODES
    assert [c["id"] for c in data["classes"]] == list(range(1, 17))
    assert data["stat_order"] == STATS


def test_ogre_base_stats(data):
    base = race(data, "OGR")["base"]
    assert {k: base[k] for k in ("STR", "DEX", "AGI", "STA", "INT", "WIS", "CHA")} == {
        "STR": 130,
        "DEX": 70,
        "AGI": 70,
        "STA": 127,
        "INT": 60,
        "WIS": 67,
        "CHA": 37,
    }


def test_troll_stamina_is_114(data):
    assert race(data, "TRL")["base"]["STA"] == 114


def test_monk_modifiers(data):
    mods = klass(data, "MNK")["mods"]
    assert (mods["STR"], mods["DEX"], mods["AGI"], mods["STA"]) == (5, 10, 10, 5)
    assert mods["WIS"] == mods["INT"] == mods["CHA"] == 0


def test_every_class_row_sums_to_30(data):
    for c in data["classes"]:
        assert sum(c["mods"].values()) == 30, c["code"]


def test_naked_ogre_shadow_knight_cleric_shaman(data):
    assert naked_stats("OGR", ["SHD", "CLR", "SHM"], data) == {
        "STR": 145,
        "STA": 152,
        "AGI": 70,
        "DEX": 70,
        "WIS": 97,
        "INT": 70,
        "CHA": 47,
    }


def test_naked_stats_are_not_capped_and_the_trio_is_worth_90_to_any_race(data):
    for r in data["races"]:
        stats = naked_stats(r["code"], ["WAR", "BER", "PAL"], data)
        assert sum(stats.values()) == sum(r["base"].values()) + 90
    assert naked_stats("OGR", ["WAR", "BER", "PAL"], data)["STR"] == 165  # above the 150 players report


def test_naked_stats_use_the_trio_in_any_order_and_the_default_file():
    assert naked_stats("HUM", ["WIZ", "MAG", "ENC"]) == naked_stats("HUM", ["ENC", "WIZ", "MAG"])


@pytest.mark.parametrize(
    ("race_code", "classes"),
    [
        ("XXX", ["WAR", "CLR", "PAL"]),
        ("HUM", ["WAR", "CLR", "ZZZ"]),
        ("HUM", ["WAR", "CLR"]),
        ("HUM", ["WAR", "CLR", "PAL", "RNG"]),
        ("HUM", ["WAR", "WAR", "CLR"]),
    ],
    ids=["unknown-race", "unknown-class", "two-classes", "four-classes", "repeated-class"],
)
def test_naked_stats_refuse_what_is_not_a_trio_of_known_classes(data, race_code, classes):
    with pytest.raises(ValueError):
        naked_stats(race_code, classes, data)


def test_all_sixteen_races_are_active(data):
    assert all(r["active"] is True for r in data["races"])


def test_primary_classes_match_the_design_table(data):
    for code, text in PRIMARY_CLASSES.items():
        assert set(race(data, code)["primary"]) == set(text.split()), code
    for r in data["races"]:  # class-id order, so the file reads the same way everywhere
        assert r["primary"] == sorted(r["primary"], key=CLASS_CODES.index)


def test_kerran_druid_is_disputed_and_nothing_else_is(data):
    assert race(data, "KER")["disputed"] == ["DRU"]
    assert "DRU" in race(data, "KER")["primary"]
    assert all(r["disputed"] == [] for r in data["races"] if r["code"] != "KER")


def test_the_primary_table_reproduces_the_designs_legal_pair_counts(data):
    trios = list(combinations(CLASS_CODES, 3))
    assert len(trios) * len(data["races"]) == 8960

    def legal(include_disputed):
        count = 0
        for r in data["races"]:
            allowed = set(r["primary"]) - (set() if include_disputed else set(r["disputed"]))
            count += sum(1 for trio in trios if allowed & set(trio))
        return count

    assert legal(include_disputed=True) == 7231  # (6,755 of the fifteen races before Half Dark Elf, which starts 476 of the 560 trios)
    assert legal(include_disputed=False) == 7195


def test_stats_are_cited_to_the_public_attributes_table(data):
    assert {"kind": "url", "ref": "https://eqltools.com/attributes"} in data["sources"]["stats"]
    assert data["seal"] == "player"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["version"])


def test_the_file_names_no_client_binary_address_or_offset():
    text = RACES_PATH.read_text(encoding="utf-8")
    lowered = text.lower()
    assert [word for word in FORBIDDEN_WORDS if word in lowered] == []
    assert FORBIDDEN_CAPITALS not in text


# ---- the classes a race may start a trio with --------------------------------------------------


def test_legal_primaries_leave_out_the_disputed_class_by_default(data):
    assert races.legal_primaries("KER") == ["WAR", "BRD", "ROG", "SHM", "BST", "BER"]  # no Druid
    assert races.legal_primaries("KER", include_disputed=True) == ["WAR", "DRU", "BRD", "ROG", "SHM", "BST", "BER"]
    assert races.legal_primaries("KER", False, data) == races.legal_primaries("KER")


def test_legal_primaries_of_every_other_race_are_the_whole_primary_table_in_class_id_order(data):
    for code, text in PRIMARY_CLASSES.items():
        expected = sorted(text.split(), key=CLASS_CODES.index)
        if code == "KER":
            continue
        assert races.legal_primaries(code) == expected, code
        assert races.legal_primaries(code, include_disputed=True) == expected, code


def test_legal_primaries_follow_the_table_they_are_given(data):
    changed = copy.deepcopy(data)
    race(changed, "HUM")["disputed"] = ["WAR", "MNK"]
    assert "WAR" not in races.legal_primaries("HUM", data=changed)
    assert "MNK" not in races.legal_primaries("HUM", data=changed)
    assert "WAR" in races.legal_primaries("HUM", include_disputed=True, data=changed)
    assert "WAR" in races.legal_primaries("HUM")  # the shipped table is unchanged
    race(changed, "BAR")["disputed"] = list(race(changed, "BAR")["primary"])
    assert races.legal_primaries("BAR", data=changed) == []  # every primary disputed: none is legal yet


@pytest.mark.parametrize("bad", ["XXX", "", "hum", None, 7])
def test_legal_primaries_refuse_an_unknown_race(bad):
    with pytest.raises(ValueError, match="race"):
        races.legal_primaries(bad)


def test_legal_primaries_hand_back_a_list_nobody_else_holds(data):
    first = races.legal_primaries("KER", include_disputed=True, data=data)
    first.append("XXX")
    assert races.legal_primaries("KER", include_disputed=True, data=data)[-1] == "BER"
    assert "XXX" not in race(data, "KER")["primary"]


def test_legal_primaries_agree_with_the_designs_legal_pair_counts(data):
    trios = list(combinations(CLASS_CODES, 3))
    for include_disputed, expected in ((True, 7231), (False, 7195)):  # (6,755 and 6,719 of the fifteen races before the Half Dark Elf, which starts 476 trios)
        count = 0
        for r in data["races"]:
            allowed = set(races.legal_primaries(r["code"], include_disputed=include_disputed))
            count += sum(1 for trio in trios if allowed & set(trio))
        assert count == expected


# ---- one list of class codes for every module --------------------------------------------------


def test_the_class_codes_are_one_shared_constant():
    from trioforge import classes
    from trioforge.sources import client_spells, client_tables

    assert list(classes.CLASS_CODES) == CLASS_CODES  # the order of the class ids 1 to 16, written out above
    assert tuple(classes.CLASS_NAMES) == classes.CLASS_CODES
    assert races.CLASS_CODES is classes.CLASS_CODES
    assert races.CLASS_NAMES is classes.CLASS_NAMES
    assert client_spells.CLASS_CODES is classes.CLASS_CODES
    assert client_tables.CLASS_CODES is classes.CLASS_CODES


# ---- the loader refuses a file that drifts ----------------------------------------------------


def real_file() -> dict:
    return json.loads(RACES_PATH.read_text(encoding="utf-8"))


def break_class_sum(d):
    d["classes"][0]["mods"]["STR"] += 1


def drop_a_race(d):
    del d["races"][3]


def swap_two_races(d):
    d["races"][0], d["races"][1] = d["races"][1], d["races"][0]


def rename_a_race_code(d):
    d["races"][9]["code"] = "OGE"


def rename_a_class_code(d):
    d["classes"][4]["code"] = "SK"


def renumber_a_class(d):
    d["classes"][2]["id"] = 9


def add_a_stat_to_a_race(d):
    d["races"][0]["base"]["LUCK"] = 5


def remove_a_stat_from_a_race(d):
    del d["races"][0]["base"]["CHA"]


def float_stat(d):
    d["races"][0]["base"]["STR"] = 75.0


def boolean_stat(d):
    d["races"][0]["base"]["STR"] = True


def zero_stat(d):
    d["races"][0]["base"]["STR"] = 0


def negative_modifier(d):
    d["classes"][0]["mods"]["INT"] = -5
    d["classes"][0]["mods"]["STA"] += 5


def unknown_primary_class(d):
    d["races"][0]["primary"].append("XXX")


def repeated_primary_class(d):
    d["races"][0]["primary"].append("WAR")


def unordered_primary_classes(d):
    d["races"][0]["primary"].reverse()


def empty_primary_classes(d):
    d["races"][1]["primary"] = []
    d["races"][1]["disputed"] = []


def disputed_outside_primary(d):
    d["races"][1]["disputed"] = ["MNK"]


def inactive_as_text(d):
    d["races"][0]["active"] = "yes"


def unknown_seal(d):
    d["seal"] = "rumour"


def client_seal(d):
    d["seal"] = "client"


def bad_version(d):
    d["version"] = "2026-13-40"


def wrong_stat_order(d):
    d["stat_order"] = ["STR", "DEX", "AGI", "STA", "INT", "WIS", "CHA"]


def unknown_top_level_key(d):
    d["extra"] = 1


def missing_sources(d):
    del d["sources"]


def source_of_an_unknown_kind(d):
    d["sources"]["stats"] = [{"kind": "rumour", "ref": "somebody"}]


def source_url_that_is_not_https(d):
    d["sources"]["stats"] = [{"kind": "url", "ref": "http://eqltools.com/attributes"}]


def empty_source_list(d):
    d["sources"]["primary_classes"] = []


def client_binary_in_a_source(d):
    d["sources"]["stats"].append({"kind": "public-text", "ref": "the game's " + "eq" + "game" + "." + "exe tables"})


def address_in_a_note(d):
    d["notes"].append("table at " + "0" + "x1F")


def blank_note(d):
    d["notes"].append("  ")


def wrong_race_name(d):
    d["races"][9]["name"] = "Orge"


MUTATIONS = [
    pytest.param(break_class_sum, "WAR", id="class-sums-to-31"),
    pytest.param(drop_a_race, "ELF", id="a-race-is-missing"),
    pytest.param(swap_two_races, "HUM", id="races-out-of-order"),
    pytest.param(rename_a_race_code, "OGR", id="unknown-race-code"),
    pytest.param(rename_a_class_code, "SHD", id="old-class-code"),
    pytest.param(renumber_a_class, "PAL", id="class-id-wrong"),
    pytest.param(add_a_stat_to_a_race, "LUCK", id="extra-stat"),
    pytest.param(remove_a_stat_from_a_race, "CHA", id="missing-stat"),
    pytest.param(float_stat, "STR", id="stat-as-float"),
    pytest.param(boolean_stat, "STR", id="stat-as-boolean"),
    pytest.param(zero_stat, "STR", id="stat-of-zero"),
    pytest.param(negative_modifier, "WAR", id="negative-modifier"),
    pytest.param(unknown_primary_class, "XXX", id="unknown-primary-class"),
    pytest.param(repeated_primary_class, "WAR", id="repeated-primary-class"),
    pytest.param(unordered_primary_classes, "HUM", id="primary-classes-unordered"),
    pytest.param(empty_primary_classes, "BAR", id="no-primary-class"),
    pytest.param(disputed_outside_primary, "MNK", id="disputed-class-not-primary"),
    pytest.param(inactive_as_text, "active", id="active-not-boolean"),
    pytest.param(unknown_seal, "seal", id="unknown-seal"),
    pytest.param(client_seal, "seal", id="client-seal-without-a-client-file"),
    pytest.param(bad_version, "version", id="impossible-date"),
    pytest.param(wrong_stat_order, "stat_order", id="stat-order"),
    pytest.param(unknown_top_level_key, "extra", id="unknown-top-level-key"),
    pytest.param(missing_sources, "sources", id="sources-missing"),
    pytest.param(source_of_an_unknown_kind, "rumour", id="unknown-source-kind"),
    pytest.param(source_url_that_is_not_https, "https", id="source-url-not-https"),
    pytest.param(empty_source_list, "primary_classes", id="no-source-for-a-table"),
    pytest.param(client_binary_in_a_source, "client binary", id="client-binary-in-a-source"),
    pytest.param(address_in_a_note, "client binary", id="address-in-a-note"),
    pytest.param(blank_note, "notes", id="blank-note"),
    pytest.param(wrong_race_name, "OGR", id="race-name-typo"),
]


@pytest.mark.parametrize(("mutate", "mentions"), MUTATIONS)
def test_the_loader_refuses_a_drifted_file_and_names_the_problem(tmp_path, mutate, mentions):
    broken = copy.deepcopy(real_file())
    mutate(broken)
    path = tmp_path / "races.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(RacesError) as caught:
        load(path)
    assert mentions in str(caught.value)
    assert caught.value.problems


def test_the_loader_lists_every_problem_not_just_the_first(tmp_path):
    broken = copy.deepcopy(real_file())
    break_class_sum(broken)
    drop_a_race(broken)
    unknown_seal(broken)
    path = tmp_path / "races.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(RacesError) as caught:
        load(path)
    assert len(caught.value.problems) >= 3


@pytest.mark.parametrize(
    "text",
    [
        "{ not json",
        "[]",
        '{"version": "2026-10-13", "version": "2026-10-14"}',
        '{"version": NaN}',
        "",
    ],
    ids=["invalid-json", "not-an-object", "duplicate-key", "nan", "empty"],
)
def test_the_loader_refuses_text_that_is_not_strict_json_for_an_object(tmp_path, text):
    path = tmp_path / "races.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RacesError):
        load(path)


def test_the_loader_refuses_a_file_that_is_not_utf_8(tmp_path):
    path = tmp_path / "races.json"
    path.write_bytes(b'{"version": "\xff"}')
    with pytest.raises(RacesError, match="UTF-8"):
        load(path)


def test_a_duplicate_key_is_named_in_the_error(tmp_path):
    text = RACES_PATH.read_text(encoding="utf-8").replace('"seal": "player",', '"seal": "player", "seal": "model",')
    path = tmp_path / "races.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RacesError, match="duplicate key 'seal'"):
        load(path)


def test_a_missing_file_is_a_file_not_found_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nope.json")


def test_the_default_path_is_the_repositorys_rules_file():
    assert races.RACES_PATH == RACES_PATH
    assert load() == load(RACES_PATH) == real_file()


# ---- the Half Dark Elf (the 16th race: an unlocked race, from the page of eqlwiki, revision of 2026-11-05) --------------------------------


HDE_PAGE = "https://eqlwiki.com/index.php?title=Half_Dark_Elf&oldid=200325"


def test_the_half_dark_elf_has_the_base_stats_and_the_primary_classes_of_its_page(data):
    hde = race(data, "HDE")
    assert hde["name"] == "Half Dark Elf" and hde["active"] is True and hde["disputed"] == []
    assert hde["base"] == {"STR": 75, "STA": 75, "AGI": 80, "DEX": 80, "WIS": 55, "INT": 95, "CHA": 70}
    assert hde["primary"] == ["RNG", "SHD", "BRD", "ROG", "NEC", "ENC", "BER"]  # Ranger, Shadow Knight, Bard, Rogue, Necromancer, Enchanter, Berserker: the page's seven, in class-id order
    assert races.legal_primaries("HDE") == hde["primary"]
    assert races.RACE_NAMES["HDE"] == "Half Dark Elf" and races.RACE_CODES[-1] == "HDE" and len(races.RACE_CODES) == 16  # (the last of the codes: no kit link made before it changes)
    assert naked_stats("HDE", ["ENC", "NEC", "SHD"], data) == {"STR": 85, "STA": 80, "AGI": 80, "DEX": 95, "WIS": 55, "INT": 135, "CHA": 90}


def test_the_half_dark_elf_is_cited_to_the_revision_of_its_page_and_its_cursed_heritage_is_a_note_that_is_not_scored(data):
    assert {"kind": "url", "ref": HDE_PAGE} in data["sources"]["stats"] and {"kind": "url", "ref": HDE_PAGE} in data["sources"]["primary_classes"]
    note = race(data, "HDE")["note"]
    assert "Cursed Heritage" in note and "10%" in note and "lifetaps" in note and "runes" in note and "20%" in note and "regeneration" in note and "not scored" in note
    assert [r["code"] for r in data["races"] if "note" in r] == ["HDE"]  # (no other race has one)


def test_a_race_note_is_optional_and_must_be_text(data):
    broken = copy.deepcopy(data)
    race(broken, "HDE")["note"] = 7
    problems = races._problems(broken, json.dumps(broken))
    assert any("note" in problem and "text" in problem for problem in problems)
    broken = copy.deepcopy(data)
    race(broken, "HDE")["note"] = "  "
    assert any("note" in problem for problem in races._problems(broken, json.dumps(broken)))
    broken = copy.deepcopy(data)
    del race(broken, "HDE")["note"]
    assert races._problems(broken, json.dumps(broken)) == []  # (a race with no note is a race)
    broken = copy.deepcopy(data)
    race(broken, "HDE")["notes"] = "x"
    assert any("unexpected key 'notes'" in problem for problem in races._problems(broken, json.dumps(broken)))
