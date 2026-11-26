"""Tests for the optional file of expected items (``--expected``): the cases a kit may agree with, their forms and the report.

The fixture kits are written from invented items. Every form that the file may take is tried: ``any_of`` and ``none_of``, a role or ``any``, a place, a pair of places or ``any``,
a race, a tier, names spelt in another case or with other punctuation, names that no item has, keys that are not part of a case, and cases that cannot be read.
"""

from __future__ import annotations

import json

import pytest
from kits_fixture import base_items, item, make_results, row

from trioforge import rules as rules_module
from trioforge.checks.expected import ExpectedError, check_case, check_expected, load_cases, render_report
from trioforge.checks.results import Results

TRIO = ["PAL", "MNK", "ENC"]
BACKTICK_NAME = "Quillon" + chr(96) + "s Crest"  # the game writes an apostrophe as a backtick


@pytest.fixture(scope="module")
def rules():
    return rules_module.load()


@pytest.fixture
def results(tmp_path, rules):
    records = base_items() + [item(BACKTICK_NAME, ["HEAD"], None, {"AC": 3})]
    rows = [
        row("tank", 4, {"CHEST": "Ombrel Vestment", "HEAD": BACKTICK_NAME, "EAR1": "Moonstud", "ANY1": "Vlorn Tunic", "FINGER1": "Swiftling Band"}),
        row("melee", 4, {"CHEST": "Tolk Tunic", "HEAD": "Vlorn Helm"}),
        row("melee", 4, {"CHEST": "Quibbit Tunic"}, race="OGR", setup="dw"),
        row("balanced", 4, {"CHEST": "Vlorn Tunic"}),
        row("tank", 10, {"CHEST": "Vlorn Tunic"}),
    ]
    return Results(make_results(tmp_path / "results", records, {"pal-mnk-enc": rows}, race="HUM"), rules=rules)


def case(**fields):
    return {"trio": TRIO, "role": "tank", "slot": "CHEST", **fields}


def status(results, **fields):
    return check_case(case(**fields), 1, results)["status"]


def test_the_kit_of_a_slot_is_one_of_the_names(results):
    report = check_case(case(any_of=["Ombrel Vestment"]), 1, results)
    assert report["status"] == "agree" and report["roles_holding"] == ["tank"]
    assert report["roles"]["tank"]["worn"] == ["Ombrel Vestment"] and report["trio"] == "pal-mnk-enc" and report["tier"] == 4
    other = check_case(case(any_of=["Vlorn Tunic", "Tolk Tunic"]), 1, results)
    assert other["status"] == "disagree" and other["roles_holding"] == [] and other["roles"]["tank"]["worn"] == ["Ombrel Vestment"]


def test_none_of_holds_when_the_item_is_none_of_the_names(results):
    assert status(results, none_of=["Vlorn Tunic"]) == "agree"
    assert status(results, none_of=["Ombrel Vestment", "Vlorn Tunic"]) == "disagree"


def test_an_empty_slot_holds_none_of_the_names_and_is_not_one_of_them(results):
    assert status(results, slot="NECK", any_of=["Vlorn Tunic"]) == "disagree"
    assert status(results, slot="NECK", none_of=["Vlorn Tunic"]) == "agree"


def test_role_any_holds_when_any_role_satisfies_it_and_says_which(results):
    report = check_case(case(role="any", any_of=["Vlorn Tunic"]), 1, results)
    assert report["status"] == "agree" and report["roles_holding"] == ["balanced"]
    assert set(report["roles"]) == {"tank", "melee", "balanced"}
    assert status(results, role="any", any_of=["Brawn Belt"]) == "disagree"  # a known item that no role's kit wears there
    assert status(results, role="any", any_of=["Nothing That Anyone Wears"]) == "invalid"  # no item has that name


def test_role_any_with_none_of_holds_only_when_every_role_avoids_the_names(results):
    report = check_case(case(role="ANY", none_of=["Ombrel Vestment"]), 1, results)
    assert report["status"] == "disagree" and report["roles_holding"] == ["melee", "balanced"]  # in the order of the shard: the tank kit wears it
    assert report["roles_failing"] == ["tank"]
    report = check_case(case(role="any", none_of=["Brawn Belt", "Tolk Tunic"]), 1, results)
    assert report["status"] == "disagree" and report["roles_failing"] == ["melee"]  # the melee kit wears the Tolk Tunic
    report = check_case(case(role="any", none_of=["Brawn Belt"]), 1, results)
    assert report["status"] == "agree" and report["roles_holding"] == ["tank", "melee", "balanced"] and report["roles_failing"] == []
    assert check_case(case(role="any", any_of=["Tolk Tunic", "Brawn Belt"]), 1, results)["status"] == "agree"  # any_of keeps "at least one role"


def test_a_role_is_matched_in_any_case(results):
    assert status(results, role="Tank", any_of=["Ombrel Vestment"]) == "agree"


@pytest.mark.parametrize("spelling", ["ombrel vestment", "OMBREL   VESTMENT", "Ombrel-Vestment", "ombrel vestment."])
def test_names_ignore_case_and_punctuation(results, spelling):
    assert status(results, any_of=[spelling]) == "agree"


@pytest.mark.parametrize("spelling", ["Quillon's Crest", "quillon" + chr(96) + "s crest", "QUILLONS CREST", "Quillon’s Crest"])
def test_names_ignore_apostrophes_and_the_games_backtick(results, spelling):
    assert status(results, slot="HEAD", any_of=[spelling]) == "agree"


def test_a_name_that_no_item_has_is_reported_and_is_no_error(results):
    report = check_case(case(any_of=["Ombrel Vestment", "No Such Thing"]), 1, results)
    assert report["status"] == "agree" and report["unknown_names"] == ["No Such Thing"]
    report = check_case(case(none_of=["Vlorn Tunic", "No Such Thing"]), 1, results)
    assert report["status"] == "agree" and report["unknown_names"] == ["No Such Thing"]  # a case with a known name is judged by it


@pytest.mark.parametrize("mode", ["any_of", "none_of"])
def test_a_case_whose_names_are_all_unknown_is_invalid_and_not_agreed_with(results, mode):
    """A misspelt name would otherwise make a none_of case agree with every kit, and an any_of case disagree with every one."""
    report = check_case(case(**{mode: ["No Such Thing", "Nor This One"]}), 1, results)
    assert report["status"] == "invalid" and "no item" in report["reason"]
    assert report["unknown_names"] == ["No Such Thing", "Nor This One"]  # and it says which


def test_the_summary_counts_the_unknown_names(results):
    cases = [case(any_of=["Ombrel Vestment", "No Such Thing"]), case(none_of=["No Such Thing", "Vlorn Tunic"]), case(any_of=["Another Missing"]), case(any_of=["no such  THING"])]
    report = check_expected(cases, results)
    assert report["unknown_name_count"] == 2  # the distinct names, as names are compared: "No Such Thing" in three cases is one name
    assert report["invalid"] == 2 and report["agree"] == 2
    assert "unknown names 2" in render_report(report)


def test_slot_any_is_an_any_place_or_the_items_own_place(results):
    assert status(results, slot="any", any_of=["Vlorn Tunic"]) == "agree"  # worn in an Any place
    assert status(results, slot="any", any_of=["Ombrel Vestment"]) == "agree"  # worn in its own slot
    assert status(results, slot="any", any_of=["Moonstud"]) == "agree"
    assert status(results, slot="any", any_of=["Brawn Belt"]) == "disagree"
    assert status(results, slot="any", none_of=["Vlorn Tunic"]) == "disagree"
    assert status(results, slot="any", none_of=["Brawn Belt"]) == "agree"
    report = check_case(case(role="any", slot="any", any_of=["Vlorn Helm"]), 1, results)
    assert report["roles_holding"] == ["melee"]


def test_a_place_is_one_place_and_a_pair_is_either(results):
    assert status(results, slot="ANY1", any_of=["Vlorn Tunic"]) == "agree"
    assert status(results, slot="ANY2", any_of=["Vlorn Tunic"]) == "disagree"
    assert status(results, slot="EAR", any_of=["Moonstud"]) == "agree"  # EAR1
    assert status(results, slot="EAR2", any_of=["Moonstud"]) == "disagree"
    assert status(results, slot="finger", any_of=["Swiftling Band"]) == "agree"
    assert status(results, slot="WRIST", any_of=["Swiftling Band"]) == "disagree"


def test_a_race_looks_at_the_kits_of_that_race_only(results):
    assert status(results, role="melee", any_of=["Quibbit Tunic"]) == "disagree"  # the default race has another chest
    assert status(results, role="melee", race="ogr", any_of=["Quibbit Tunic"]) == "agree"
    report = check_case(case(role="melee", race="OGR", any_of=["Quibbit Tunic"]), 1, results)
    assert report["roles"]["melee"]["race"] == "OGR" and report["race"] == "OGR"
    assert check_case(case(role="melee", race="ERU", any_of=["Quibbit Tunic"]), 1, results)["status"] == "na"


def test_a_tier_is_four_unless_the_case_says_another(results):
    assert status(results, any_of=["Vlorn Tunic"]) == "disagree"
    assert status(results, tier=10, any_of=["Vlorn Tunic"]) == "agree"
    assert check_case(case(tier=0, any_of=["Vlorn Tunic"]), 1, results)["status"] == "na"


def test_a_case_with_nothing_to_look_at_is_not_applicable_and_says_why(results):
    missing_trio = check_case({"trio": ["WAR", "CLR", "PAL"], "role": "tank", "slot": "CHEST", "any_of": ["Ombrel Vestment"]}, 1, results)
    assert missing_trio["status"] == "na" and "trio" in missing_trio["reason"]
    missing_role = check_case(case(role="caster", any_of=["Ombrel Vestment"]), 1, results)
    assert missing_role["status"] == "na" and "offered" in missing_role["reason"]  # (the trio is not offered the Caster build)


def test_keys_that_are_not_part_of_a_case_are_ignored(results):
    assert status(results, any_of=["Ombrel Vestment"], mentions=["x", "y"], note="free text", source="a page", whatever={"a": 1}) == "agree"


def test_the_trio_may_be_a_string_in_any_order(results):
    for spelling in ("pal-mnk-enc", "ENC/MNK/PAL", ["enc", "pal", "mnk"]):
        assert check_case({**case(any_of=["Ombrel Vestment"]), "trio": spelling}, 1, results)["status"] == "agree"


@pytest.mark.parametrize(
    "bad",
    [
        "not an object",
        {"trio": TRIO, "role": "tank", "slot": "CHEST"},  # no names
        {"trio": TRIO, "role": "tank", "slot": "CHEST", "any_of": ["A"], "none_of": ["B"]},  # both
        {"trio": TRIO, "role": "tank", "slot": "CHEST", "any_of": []},
        {"trio": TRIO, "role": "tank", "slot": "CHEST", "any_of": "Ombrel Vestment"},
        {"trio": TRIO, "role": "tank", "slot": "CHEST", "any_of": [""]},
        {"trio": TRIO, "role": "tank", "slot": "CHEST", "any_of": [3]},
        {"trio": ["PAL", "MNK"], "role": "tank", "slot": "CHEST", "any_of": ["A"]},
        {"role": "tank", "slot": "CHEST", "any_of": ["A"]},
        {"trio": TRIO, "slot": "CHEST", "any_of": ["A"]},
        {"trio": TRIO, "role": "tank", "any_of": ["A"]},
        {"trio": TRIO, "role": "tank", "slot": "ELBOW", "any_of": ["A"]},
        {"trio": TRIO, "role": "tank", "slot": "CHEST", "any_of": ["A"], "tier": 11},
        {"trio": TRIO, "role": "tank", "slot": "CHEST", "any_of": ["A"], "tier": "4"},
        {"trio": TRIO, "role": "tank", "slot": "CHEST", "any_of": ["A"], "race": ""},
    ],
)
def test_a_case_that_cannot_be_read_is_invalid_and_the_rest_are_still_checked(results, bad):
    report = check_expected([bad, case(any_of=["Ombrel Vestment"])], results)
    assert [c["status"] for c in report["cases"]] == ["invalid", "agree"]
    assert report["cases"][0]["reason"] and report["invalid"] == 1 and report["agree"] == 1


def test_the_agreement_is_the_share_of_the_cases_that_agree_among_those_that_could_be_judged(results):
    cases = [
        case(any_of=["Ombrel Vestment"]),  # agree
        case(none_of=["Vlorn Tunic"]),  # agree
        case(role="any", any_of=["Vlorn Tunic"]),  # agree
        case(any_of=["Tolk Tunic"]),  # disagree
        case(role="caster", any_of=["Tolk Tunic"]),  # n.a.
        "junk",  # invalid
    ]
    report = check_expected(cases, results)
    assert (report["agree"], report["disagree"], report["na"], report["invalid"]) == (3, 1, 1, 1)
    assert report["agreement"] == 0.75
    assert check_expected([case(role="caster", any_of=["A"])], results)["agreement"] is None
    assert check_expected([], results) == {"agree": 0, "disagree": 0, "na": 0, "invalid": 0, "unknown_name_count": 0, "agreement": None, "cases": []}


def test_the_report_is_json(results):
    report = check_expected([case(any_of=["Ombrel Vestment"]), "junk", case(role="any", none_of=["Brawn Belt"])], results)
    assert json.loads(json.dumps(report)) == report


def test_the_text_says_what_each_case_found(results):
    text = render_report(check_expected([case(any_of=["Vlorn Tunic", "No Such Thing"]), case(role="any", any_of=["Vlorn Tunic"]), case(role="caster", any_of=["Brawn Belt"]), "junk"], results))
    assert text.splitlines()[0] == "Expected cases"
    assert "[disagree]" in text and "[agree]" in text and "[na]" in text and "[invalid]" in text
    assert "unknown names (no item of the table has them): No Such Thing" in text
    assert "roles that satisfy it: balanced" in text
    assert "the kit wears Ombrel Vestment" in text
    assert "agreement 50.0%" in text and "unknown names 1" in text


def test_a_file_of_cases_is_a_json_list(tmp_path):
    good = tmp_path / "cases.json"
    good.write_text(json.dumps([case(any_of=["A"])]), encoding="utf-8")
    assert load_cases(good) == [case(any_of=["A"])]
    for name, text in (("object.json", "{}"), ("broken.json", "[not json")):
        (tmp_path / name).write_text(text, encoding="utf-8")
        with pytest.raises(ExpectedError, match=name):
            load_cases(tmp_path / name)
    with pytest.raises(ExpectedError, match="absent.json"):
        load_cases(tmp_path / "absent.json")
