"""Tests for the EQL Tools cross-check: the name matching, the field-by-field diff and the report.

Everything here is synthetic (invented items, one file written to a scratch folder per test); the one test
that reads a real file is skipped when the git-ignored EQL Tools copy is not there.
"""

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from trioforge.classes import CLASS_CODES
from trioforge.reports.eqltools_diff import (
    CREDIT,
    EXAMPLES,
    FIELD_ORDER,
    diff,
    main,
    match_key,
    norm_name,
    read_catalog,
    read_eqltools,
    render_markdown,
)

REPO = Path(__file__).resolve().parents[2]


def mine(key, name, **fields):
    """One normalized catalog item with the fields the diff reads."""
    item = {
        "key": key,
        "name": name,
        "slots": ["FINGER"],
        "classes": ["ALL"],
        "stats": {"AC": 20},
        "sv": {},
        "weight": 0.1,
        "era_tags": ["Classic Era"],
        "evidence": {"level": "wiki", "reasons": []},
    }
    item.update(fields)
    return item


def theirs(name, **fields):
    """One EQL Tools gear record (short keys), the same item as ``mine`` unless a field is changed."""
    record = {"n": name, "t": name.replace(" ", "_"), "sl": ["Fingers"], "cls": {"all": 1}, "st": {"ac": 20}, "wt": 0.1, "era": "Classic Era"}
    record.update(fields)
    return record


def gear(*records):
    """An EQL Tools file as parsed JSON: items keyed by a lookup key that is not the name."""
    return {
        "meta": {"license": "CC BY-SA 4.0", "source": "eqlwiki.com"},
        "schema": 2,
        "items": {f"lookup-{index}": record for index, record in enumerate(records)},
    }


def one(field, ours_fields=None, theirs_fields=None, name="Zorblax Ring"):
    """Diff a single matched pair and return the result for ``field``."""
    d = diff([mine("w1", name, **(ours_fields or {}))], gear(theirs(name, **(theirs_fields or {}))))
    assert d["totals"]["matched"] == 1
    return d["fields"][field]


def counts(result):
    return (result["equal"], result["different"], result["missing_ours"], result["missing_theirs"])


# ---- the name matching -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("A Rusty Dagger", "rusty dagger"),
        ("An Orc Ear", "orc ear"),
        ("The Ring of Valor", "ring of valor"),
        ("Anvil", "anvil"),  # "an" is an article only before a space
        ("Zorblax's Blade", "zorblaxs blade"),
        ("Zorblax`s Blade", "zorblaxs blade"),
        ("Zorblax’s Blade", "zorblaxs blade"),
        ("Zorblax�s Blade", "zorblaxs blade"),  # a mis-decoded apostrophe
        # As in the maintainer's earlier tools, from which these two functions are ported: NFKD turns the acute
        # accent into a space before the list of quote marks is applied, so it separates words instead of
        # vanishing. No name in either source has one; changing this is a decision for both tools at once.
        ("Zorblax´s Blade", "zorblax s blade"),
        ("Café Au Lait", "cafe au lait"),
        ("Black-and-Gold  Ring", "black and gold ring"),
        ("Club*", "club star"),
        ("Club", "club"),
        ("Tenderizer (Weapon)", "tenderizer"),  # a known alias: the page title carries a disambiguation
        ("Deterioriated Ancient Faydark Longbow", "deteriorated ancient faydark longbow"),
        ("", ""),
    ],
)
def test_names_match_by_the_normalized_key(name, expected):
    assert match_key(name) == expected


def test_the_star_keeps_two_items_apart_and_norm_name_keeps_the_article():
    assert match_key("Club") != match_key("Club*")
    assert norm_name("A Rusty Dagger") == "a rusty dagger"
    assert norm_name("Club*") == "club star"


# ---- the diff ------------------------------------------------------------------------------------------


def test_equal_stats_are_counted_a_different_ac_is_listed_and_a_missing_item_is_counted():
    catalog = [
        mine("w1", "Zorblax Ring"),
        mine("w2", "Quimmet Band"),
        mine("w3", "Vexandra Loop"),  # only in our catalog, wearable
        mine("w4", "Plain Rock", slots=[]),  # only in our catalog, no slot
    ]
    d = diff(catalog, gear(theirs("Zorblax Ring"), theirs("Quimmet Band", st={"ac": 22}), theirs("Orphan Charm")))
    totals = d["totals"]
    assert (totals["ours"], totals["theirs"], totals["matched"]) == (4, 3, 2)
    assert (totals["only_ours"], totals["only_ours_wearable"], totals["only_theirs"]) == (2, 1, 1)
    assert totals["ambiguous"] == 0 and totals["unreadable_ours"] == 0 and totals["unreadable_theirs"] == 0
    ac = d["fields"]["stats.AC"]
    assert counts(ac) == (1, 1, 0, 0)
    assert ac["examples"]["different"] == [{"key": "w2", "name": "Quimmet Band", "ours": 20, "theirs": 22}]
    assert ac["examples"]["equal"] == [{"key": "w1", "name": "Zorblax Ring", "ours": 20, "theirs": 20}]
    assert ac["examples"]["missing_ours"] == [] and ac["examples"]["missing_theirs"] == []
    assert d["examples"]["only_theirs"] == [{"name": "Orphan Charm", "page": "Orphan Charm"}]
    assert d["examples"]["only_ours_wearable"] == [{"key": "w3", "name": "Vexandra Loop"}]


def test_the_item_counts_add_up_and_the_result_is_plain_json():
    catalog = [mine("w1", "Twin Charm"), mine("w2", "Twin Charm"), mine("w3", "Solo Charm"), mine("w4", "Only Mine", slots=[])]
    d = diff(catalog, gear(theirs("Twin Charm"), theirs("Solo Charm"), theirs("Only Theirs")))
    t = d["totals"]
    assert t["ours"] == t["matched"] + t["only_ours"] + t["ambiguous_ours"]
    assert t["theirs"] == t["matched"] + t["only_theirs"] + t["ambiguous_theirs"]
    assert json.loads(json.dumps(d)) == d


def test_the_fields_come_in_a_fixed_order():
    d = diff([mine("w1", "Zorblax Ring")], gear(theirs("Zorblax Ring")))
    assert list(d["fields"]) == list(FIELD_ORDER)
    assert FIELD_ORDER[:2] == ("slots", "classes")
    assert [f for f in FIELD_ORDER if f.startswith("stats.")] == [
        f"stats.{s}" for s in "AC STR STA AGI DEX WIS INT CHA HP MANA END ATK HASTE".split()
    ]
    assert [f for f in FIELD_ORDER if f.startswith("sv.")] == [f"sv.{s}" for s in "FIRE COLD MAGIC POISON DISEASE VOID".split()]
    assert FIELD_ORDER[-3:] == ("weight", "era", "oe")


def test_a_stat_on_one_side_only_is_missing_and_one_on_neither_side_is_not_counted():
    catalog = [
        mine("w1", "Item A", stats={"STR": 5}),
        mine("w2", "Item B", stats={"STR": 5}),
        mine("w3", "Item C", stats={}),
        mine("w4", "Item D", stats={"STR": 4, "HP": 0}),
    ]
    records = [
        theirs("Item A", st={"str": 5}),
        theirs("Item B", st={}),
        theirs("Item C", st={"str": 5}),
        theirs("Item D", st={"str": 5, "hp": 0}),
    ]
    d = diff(catalog, gear(*records))
    strength = d["fields"]["stats.STR"]
    assert counts(strength) == (1, 1, 1, 1)
    assert strength["examples"]["missing_theirs"] == [{"key": "w2", "name": "Item B", "ours": 5, "theirs": None}]
    assert strength["examples"]["missing_ours"] == [{"key": "w3", "name": "Item C", "ours": None, "theirs": 5}]
    assert counts(d["fields"]["stats.HP"]) == (0, 0, 0, 0)  # a zero is no value


def test_a_record_with_no_stats_at_all_has_no_stats():
    assert counts(one("stats.AC", theirs_fields={"st": None})) == (0, 0, 0, 1)
    d = diff([mine("w1", "Zorblax Ring", stats={})], gear({"n": "Zorblax Ring"}))
    assert counts(d["fields"]["stats.AC"]) == (0, 0, 0, 0)


def test_haste_is_read_from_the_top_level_key_and_a_float_equals_an_int():
    assert counts(one("stats.HASTE", {"stats": {"HASTE": 41}}, {"haste": 41.0})) == (1, 0, 0, 0)
    different = one("stats.HASTE", {"stats": {"HASTE": 36}}, {"haste": 41.0})
    assert counts(different) == (0, 1, 0, 0)
    assert different["examples"]["different"][0]["ours"] == 36 and different["examples"]["different"][0]["theirs"] == 41
    assert counts(one("stats.HASTE", {}, {"haste": 41.0})) == (0, 0, 1, 0)


@pytest.mark.parametrize(
    ("ours_sv", "theirs_sv", "school", "expected"),
    [
        ({"FIRE": 5}, {"f": 5}, "sv.FIRE", (1, 0, 0, 0)),
        ({"COLD": 5}, {"c": 6}, "sv.COLD", (0, 1, 0, 0)),
        ({}, {"m": 3}, "sv.MAGIC", (0, 0, 1, 0)),
        ({"POISON": 3}, {}, "sv.POISON", (0, 0, 0, 1)),
        ({"DISEASE": 7}, {"d": 7}, "sv.DISEASE", (1, 0, 0, 0)),
        ({}, {"v": 2}, "sv.VOID", (0, 0, 1, 0)),  # EQL Tools carries a Void resist; the catalog has none
        ({}, {}, "sv.FIRE", (0, 0, 0, 0)),
    ],
)
def test_resists_map_from_the_single_letter_keys(ours_sv, theirs_sv, school, expected):
    assert counts(one(school, {"sv": ours_sv}, {"sv": theirs_sv})) == expected


@pytest.mark.parametrize(
    ("ours_slots", "theirs_slots", "expected"),
    [
        (["PRIMARY", "SECONDARY"], ["Secondary", "Primary"], (1, 0, 0, 0)),  # order does not matter
        (["FINGER"], ["Fingers"], (1, 0, 0, 0)),  # EQL Tools writes the plural
        (["EAR"], ["Ear"], (1, 0, 0, 0)),
        (["SHOULDERS"], ["Shoulder"], (1, 0, 0, 0)),
        (["WRIST"], ["Wrists"], (1, 0, 0, 0)),
        (["HEAD"], ["Face"], (0, 1, 0, 0)),
        (["PRIMARY"], ["Primary", "Secondary"], (0, 1, 0, 0)),
        ([], ["Neck"], (0, 0, 1, 0)),
        (["NECK"], [], (0, 0, 0, 1)),
        ([], [], (0, 0, 0, 0)),
    ],
)
def test_slots_compare_as_sets_of_canonical_names(ours_slots, theirs_slots, expected):
    assert counts(one("slots", {"slots": ours_slots}, {"sl": theirs_slots})) == expected


def test_slot_examples_show_canonical_names_in_slot_order():
    result = one("slots", {"slots": ["PRIMARY", "SECONDARY"]}, {"sl": ["Fingers", "Ear"]})
    assert result["examples"]["different"][0]["ours"] == "PRIMARY SECONDARY"
    assert result["examples"]["different"][0]["theirs"] == "EAR FINGER"


ALL_BUT_WAR = [code for code in CLASS_CODES if code != "WAR"]


@pytest.mark.parametrize(
    ("ours_classes", "theirs_cls", "expected"),
    [
        (["ALL"], {"all": 1}, (1, 0, 0, 0)),
        (ALL_BUT_WAR, {"all": 1, "x": ["WAR"]}, (1, 0, 0, 0)),
        (["ALL"], {"all": 1, "x": ["WAR"]}, (0, 1, 0, 0)),
        (["MNK", "BER", "PAL"], {"c": ["PAL", "MNK", "BER"]}, (1, 0, 0, 0)),
        (["ALL"], {"c": list(CLASS_CODES)}, (1, 0, 0, 0)),  # a full list is ALL
        (["ALL"], {"c": ["WAR", "CLR"]}, (0, 1, 0, 0)),
        (["WAR"], None, (0, 0, 0, 1)),  # EQL Tools has no class list
        ([], {"c": []}, (1, 0, 0, 0)),  # "Class: NONE" on both sides
        ([], {"all": 1}, (0, 1, 0, 0)),
    ],
)
def test_classes_compare_as_sets_with_all_and_all_except(ours_classes, theirs_cls, expected):
    assert counts(one("classes", {"classes": ours_classes}, {"cls": theirs_cls})) == expected


def test_class_examples_say_all_for_a_full_list_and_none_for_an_empty_one():
    result = one("classes", {"classes": []}, {"cls": {"all": 1}})
    assert result["examples"]["different"][0]["ours"] == "NONE"
    assert result["examples"]["different"][0]["theirs"] == "ALL"
    result = one("classes", {"classes": ["MNK", "WAR"]}, {"cls": {"all": 1, "x": ["WAR"]}})
    assert result["examples"]["different"][0]["ours"] == "WAR MNK"
    assert result["examples"]["different"][0]["theirs"] == " ".join(c for c in CLASS_CODES if c != "WAR")


@pytest.mark.parametrize(
    ("ours_weight", "theirs_weight", "expected"),
    [
        (0.1, 0.1, (1, 0, 0, 0)),
        (1.0, 1.5, (0, 1, 0, 0)),
        (1, 1.0, (1, 0, 0, 0)),
        (None, 1.0, (0, 0, 1, 0)),
        (1.0, None, (0, 0, 0, 1)),
        (None, None, (0, 0, 0, 0)),
        (0.1, 0.1 + 1e-9, (1, 0, 0, 0)),
        (0.0, 0.0, (1, 0, 0, 0)),  # a weight of zero is a weight
    ],
)
def test_weight_compares_decimals(ours_weight, theirs_weight, expected):
    assert counts(one("weight", {"weight": ours_weight}, {"wt": theirs_weight})) == expected


@pytest.mark.parametrize(
    ("ours_tags", "theirs_era", "expected"),
    [
        (["Kunark Era"], "kunark Era", (1, 0, 0, 0)),
        (["Fearhaterevamp Era"], "FearHateRevamp Era", (1, 0, 0, 0)),
        (["Classic Era", "Kunark Era"], "Kunark Era", (1, 0, 0, 0)),  # one of ours is theirs
        (["Classic Era"], "Velious Era", (0, 1, 0, 0)),
        ([], "Classic Era", (0, 0, 1, 0)),
        (["Classic Era"], None, (0, 0, 0, 1)),
        ([], None, (0, 0, 0, 0)),
    ],
)
def test_era_compares_the_tag_ignoring_case(ours_tags, theirs_era, expected):
    assert counts(one("era", {"era_tags": ours_tags}, {"era": theirs_era})) == expected


def test_out_of_era_is_compared_with_our_evidence_level_and_cross_tabulated():
    cases = [
        ("Hidden Out", "hidden", 1),  # equal: both say out of era
        ("Disputed Out", "disputed", 1),  # equal
        ("Wiki In", "wiki", None),  # equal: both say in era
        ("Strict In", "strict", None),  # equal
        ("Wiki But Out", "wiki", 1),  # different: EQL Tools says out of era, we trust it
        ("Hidden But In", "hidden", None),  # different: we hide it, EQL Tools does not
        ("No Evidence", None, 1),  # missing-ours
    ]
    catalog = [mine(f"w{n}", name, evidence={"level": level, "reasons": []} if level else {}) for n, (name, level, _) in enumerate(cases)]
    records = [theirs(name, **({"oe": oe} if oe else {})) for name, _, oe in cases]
    d = diff(catalog, gear(*records))
    assert counts(d["fields"]["oe"]) == (4, 2, 1, 0)
    examples = {e["name"]: (e["ours"], e["theirs"]) for e in d["fields"]["oe"]["examples"]["different"]}
    assert examples == {"Wiki But Out": ("wiki", "out of era"), "Hidden But In": ("hidden", "in era")}
    assert d["oe_by_level"] == {
        "out of era": {"strict": 0, "wiki": 1, "disputed": 1, "hidden": 1, "none": 1},
        "in era": {"strict": 1, "wiki": 1, "disputed": 0, "hidden": 1, "none": 0},
    }


def test_out_of_era_examples_carry_our_reason_codes_and_the_disagreements_are_counted_by_reason():
    def evidence(level, *codes):
        return {"level": level, "reasons": [{"code": code, "seal": "client", "text": "x"} for code in codes]}

    catalog = [
        mine("w1", "Hidden In A", evidence=evidence("hidden", "no-known-source", "out-of-era")),
        mine("w2", "Hidden In B", evidence=evidence("hidden", "no-known-source")),
        mine("w3", "Hidden In C", evidence=evidence("hidden")),  # a level with no reason
        mine("w4", "Wiki Out A", evidence=evidence("wiki", "live-source:Zorblax Hollow", "live-source:Quuxen Deep")),
        mine("w5", "Agree Out", evidence=evidence("hidden", "out-of-era")),  # no disagreement: not counted
    ]
    records = [theirs("Hidden In A"), theirs("Hidden In B"), theirs("Hidden In C"), theirs("Wiki Out A", oe=1), theirs("Agree Out", oe=1)]
    d = diff(catalog, gear(*records))
    shown = {e["name"]: e["ours"] for e in d["fields"]["oe"]["examples"]["different"]}
    assert shown == {
        "Hidden In A": "hidden (no-known-source, out-of-era)",
        "Hidden In B": "hidden (no-known-source)",
        "Hidden In C": "hidden",
        "Wiki Out A": "wiki (live-source)",  # the zone after the colon is not part of the code; listed once
    }
    assert d["oe_by_reason"] == {
        "ours out of era, EQL Tools in era": {"no-known-source": 2, "out-of-era": 1, "none": 1},
        "ours in era, EQL Tools out of era": {"live-source": 1},
    }
    assert counts(d["fields"]["oe"]) == (1, 4, 0, 0)


def test_the_report_lists_the_out_of_era_disagreements_by_reason():
    evidence = {"level": "hidden", "reasons": [{"code": "no-known-source", "seal": "model", "text": "x"}]}
    text = render_markdown(diff([mine("w1", "Zorblax Ring", evidence=evidence)], gear(theirs("Zorblax Ring"))))
    assert "| reason | ours out of era, EQL Tools in era | ours in era, EQL Tools out of era |" in text
    assert "| `no-known-source` | 1 | 0 |" in text
    assert "hidden (no-known-source)" in text
    assert "by reason" not in render_markdown(diff([mine("w1", "Zorblax Ring")], gear(theirs("Zorblax Ring"))))


def test_a_page_title_is_shown_without_url_encoding():
    d = diff([], gear(theirs("Bladesman's Axe", t="Bladesman%60s_Axe"), theirs("Crimson Training Tunic*", t="Crimson_Training_Tunic%2A")))
    assert [e["page"] for e in d["examples"]["only_theirs"]] == ["Bladesman`s Axe", "Crimson Training Tunic*"]


def test_items_match_by_normalized_name_not_by_the_lookup_key():
    catalog = [mine("w1", "A Zorblax’s Staff"), mine("w2", "Club"), mine("w3", "Club*")]
    d = diff(catalog, gear(theirs("Zorblax`s Staff"), theirs("Club*", st={"ac": 9}), theirs("Club")))
    assert d["totals"]["matched"] == 3 and d["totals"]["only_theirs"] == 0 and d["totals"]["only_ours"] == 0
    assert counts(d["fields"]["stats.AC"]) == (2, 1, 0, 0)
    assert d["fields"]["stats.AC"]["examples"]["different"] == [{"key": "w3", "name": "Club*", "ours": 20, "theirs": 9}]


def test_a_name_shared_by_several_items_is_ambiguous_and_not_compared():
    catalog = [mine("w1", "Twin Charm"), mine("w2", "Twin Charm", stats={"AC": 1}), mine("w3", "Solo Charm")]
    d = diff(catalog, gear(theirs("Twin Charm"), theirs("Solo Charm"), theirs("Solo Charm", t="Solo_Charm_(Other)")))
    t = d["totals"]
    assert t["ambiguous"] == 2 and t["matched"] == 0
    assert (t["ambiguous_ours"], t["ambiguous_theirs"]) == (3, 3)
    assert counts(d["fields"]["stats.AC"]) == (0, 0, 0, 0)
    assert d["examples"]["ambiguous"] == [
        {"name": "Solo Charm", "ours": ["w3"], "theirs": ["Solo Charm", "Solo Charm (Other)"]},
        {"name": "Twin Charm", "ours": ["w1", "w2"], "theirs": ["Twin Charm"]},
    ]


def test_examples_are_capped_at_twenty_and_come_in_name_order():
    assert EXAMPLES == 20
    catalog = [mine(f"w{n}", f"Zorblax {n:02d}") for n in range(25, 0, -1)]
    records = [theirs(f"Zorblax {n:02d}", st={"ac": 21}) for n in range(1, 26)]
    d = diff(catalog, gear(*records))
    ac = d["fields"]["stats.AC"]
    assert ac["different"] == 25 and len(ac["examples"]["different"]) == 20
    assert [e["name"] for e in ac["examples"]["different"]] == [f"Zorblax {n:02d}" for n in range(1, 21)]
    short = diff(catalog, gear(*records), examples=3)
    assert len(short["fields"]["stats.AC"]["examples"]["different"]) == 3 and short["fields"]["stats.AC"]["different"] == 25


def test_only_ours_examples_list_wearables_only_and_only_theirs_are_capped():
    catalog = [mine(f"w{n}", f"Mine {n:02d}", slots=[] if n % 2 else ["HEAD"]) for n in range(1, 61)]
    records = [theirs(f"Theirs {n:02d}") for n in range(1, 31)]
    d = diff(catalog, gear(*records))
    assert d["totals"]["only_ours"] == 60 and d["totals"]["only_ours_wearable"] == 30
    assert len(d["examples"]["only_ours_wearable"]) == 20 and all(e["key"] for e in d["examples"]["only_ours_wearable"])
    assert len(d["examples"]["only_theirs"]) == 20 and d["totals"]["only_theirs"] == 30


def test_unreadable_entries_are_counted_and_skipped():
    records = [theirs("Zorblax Ring"), "junk", None, {"t": "No_Name"}, {"n": "   "}, {"n": 5}, {"n": "!!!"}, 7]
    catalog = [mine("w1", "Zorblax Ring"), "not an item", {"key": "w9"}, {"key": "w8", "name": ""}, {"key": "w7", "name": "!!!"}]
    d = diff(catalog, {"items": dict(enumerate(records))})  # a name with no letter or digit has no match key
    assert d["totals"]["theirs"] == 1 and d["totals"]["unreadable_theirs"] == 7
    assert d["totals"]["ours"] == 1 and d["totals"]["unreadable_ours"] == 4
    assert d["totals"]["matched"] == 1


def test_the_gear_items_may_be_a_list_and_a_bare_list_is_accepted():
    catalog = [mine("w1", "Zorblax Ring")]
    for source in ({"items": [theirs("Zorblax Ring")]}, [theirs("Zorblax Ring")]):
        assert diff(catalog, source)["totals"]["matched"] == 1


@pytest.mark.parametrize("source", [{}, {"items": 5}, {"items": "x"}, 5, None])
def test_a_gear_file_with_no_items_is_an_error(source):
    with pytest.raises(ValueError, match="items"):
        diff([mine("w1", "Zorblax Ring")], source)


def test_diff_does_not_change_its_inputs():
    catalog = [mine("w1", "Zorblax Ring"), mine("w2", "Quimmet Band", stats={"AC": 3})]
    source = gear(theirs("Zorblax Ring"), theirs("Quimmet Band", st={"ac": 5}, sv={"f": 1}))
    before = copy.deepcopy((catalog, source))
    diff(catalog, source)
    assert (catalog, source) == before


def test_the_diff_is_the_same_whatever_the_input_order():
    catalog = [mine(f"w{n}", f"Zorblax {n:02d}", stats={"AC": n}) for n in range(1, 30)]
    records = [theirs(f"Zorblax {n:02d}", st={"ac": n + 1}) for n in range(1, 30)]
    first = diff(catalog, gear(*records))
    second = diff(list(reversed(catalog)), gear(*reversed(records)))
    assert first == second


JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=12),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=6), children, max_size=4),
    max_leaves=10,
)
NAMES = st.sampled_from(["Zorblax Ring", "A Zorblax Ring", "Club", "Club*", "!!!", "", "Quimmet‮Band", "<b>x</b>"])


def odd_record(known_keys, name_key):
    """A dict that has the keys a record should have, with any JSON value (and a name that sometimes matches)."""
    return st.fixed_dictionaries({}, optional={**{key: JSON_VALUES for key in known_keys}, name_key: NAMES | JSON_VALUES})


@settings(max_examples=120, deadline=None)
@given(
    st.lists(odd_record(["key", "slots", "classes", "stats", "sv", "weight", "era_tags", "evidence"], "name") | JSON_VALUES, max_size=6),
    st.lists(odd_record(["t", "sl", "cls", "st", "sv", "wt", "era", "oe", "haste"], "n") | JSON_VALUES, max_size=6),
)
def test_odd_input_never_raises_and_the_report_stays_inert(catalog, records):
    if SEEN in json.dumps([catalog, records], ensure_ascii=False).casefold():  # Hypothesis draws strings from the module too
        with pytest.raises(ValueError, match=SEEN):  # the one refusal: input that holds the code of the private flags
            diff(catalog, {"items": records})
        return
    d = diff(catalog, {"items": records})
    text = render_markdown(d)
    assert "<" not in text and ">" not in text
    totals = d["totals"]
    assert totals["ours"] == totals["matched"] + totals["only_ours"] + totals["ambiguous_ours"]
    assert totals["theirs"] == totals["matched"] + totals["only_theirs"] + totals["ambiguous_theirs"]
    json.dumps(d, allow_nan=False)  # plain JSON, no NaN or infinity


# ---- the report ------------------------------------------------------------------------------------------


def sample_diff():
    catalog = [mine("w1", "Zorblax Ring"), mine("w2", "Quimmet Band"), mine("w3", "Vexandra Loop"), mine("w4", "Plain Rock", slots=[])]
    return diff(catalog, gear(theirs("Zorblax Ring"), theirs("Quimmet Band", st={"ac": 22}), theirs("Orphan Charm")))


def test_the_report_credits_eql_tools_and_the_wiki_and_shows_the_numbers():
    text = render_markdown(sample_diff())
    assert CREDIT == "EQL Tools (eqltools.com), gear data CC BY-SA 4.0, used as a cross-check"
    assert CREDIT in text
    assert "eqlwiki" in text and "CC BY-SA 4.0" in text
    assert text.startswith("# ") and text.endswith("\n") and "\r" not in text
    assert "Compared: slots, classes" in text and "Not compared: races" in text
    assert "| AC | 1 | 1 | 0 | 0 |" in text
    assert "| Items in our catalog | 4 |" in text and "| Matched one to one by name | 2 |" in text
    assert "`Quimmet Band`" in text and "`Orphan Charm`" in text and "`Vexandra Loop`" in text
    assert "ours `20`, theirs `22`" in text


def test_the_report_is_the_same_bytes_every_time_and_lists_only_what_has_examples():
    d = sample_diff()
    assert render_markdown(d) == render_markdown(copy.deepcopy(d))
    text = render_markdown(d)
    assert "### AC: different" in text
    assert "### AC: equal" not in text and "### AC: missing-ours" not in text
    assert "### HASTE: different" not in text


def code_spans_close(line):
    """True if every code span of the line (CommonMark: a run of N backticks closes at the next run of exactly N) closes."""
    runs = [len(match.group()) for match in re.finditer(r"`+", line)]
    position = 0
    while position < len(runs):
        closing = next((later for later in range(position + 1, len(runs)) if runs[later] == runs[position]), None)
        if closing is None:
            return False
        position = closing + 1
    return True


def test_the_report_makes_hostile_names_inert():
    hostile = [
        "Quuz|Pipe",
        "Back`tick",
        "``double",
        "<b>bold</b><script>x</script>",
        "see http://evil.example/x now",
        "[link](javascript:alert(1))",
        "line\nbreak",
        "‮Reversed​",
        "![img](x)",
    ]
    catalog = [mine(f"w{n}", name) for n, name in enumerate(hostile)]
    records = [theirs(name, st={"ac": 99}) for name in hostile]
    text = render_markdown(diff(catalog, gear(*records)))
    assert "<" not in text and ">" not in text
    assert "‮" not in text and "​" not in text
    for line in text.split("\n"):
        assert code_spans_close(line), line  # every code span is closed on its own line
    assert "``Back`tick``" in text  # the fence is longer than any backtick run inside
    assert "line break" in text  # a newline is a space


def test_the_report_has_a_table_row_per_field_and_the_same_number_of_cells():
    text = render_markdown(sample_diff())
    rows = [line for line in text.split("\n") if line.startswith("| ") and "---" not in line]
    field_rows = [row for row in rows if row.count("|") == 6]
    assert len(field_rows) >= len(FIELD_ORDER)


def test_the_report_with_meta_names_the_inputs_by_file_name_and_hash():
    d = sample_diff()
    d["meta"] = {
        "generated": "2026-10-14",
        "generator": "trioforge.reports.eqltools_diff 0.0.1",
        "catalog": {"file": "catalog.json", "sha256": "a" * 64, "version": "2026-10-14"},
        "eqltools": {"file": "gear-data-2026-10-11.json", "sha256": "b" * 64, "license": "CC BY-SA 4.0"},
    }
    text = render_markdown(d)
    assert "2026-10-14" in text and "catalog.json" in text and "gear-data-2026-10-11.json" in text
    assert "a" * 64 in text and "b" * 64 in text
    d["meta"]["catalog"]["version"] = None  # a catalog file without a version date
    assert "| version none |" in render_markdown(d)


# ---- reading the two files ---------------------------------------------------------------------------------


def write_json(path, document):
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def catalog_document(items=None, **extra):
    document = {
        "version": "2026-10-14",
        "license": "CC BY-SA 4.0",
        "items": items if items is not None else [mine("w1", "Zorblax Ring"), mine("w2", "Quimmet Band")],
    }
    document.update(extra)
    return document


def test_read_catalog_returns_the_document(tmp_path):
    path = write_json(tmp_path / "catalog.json", catalog_document())
    assert read_catalog(path)["version"] == "2026-10-14"


@pytest.mark.parametrize("document", [[], {}, {"items": 5}, {"items": {"w1": 1}}, "text"])
def test_read_catalog_refuses_a_file_without_a_list_of_items(tmp_path, document):
    with pytest.raises(ValueError, match="items"):
        read_catalog(write_json(tmp_path / "catalog.json", document))


def test_read_catalog_refuses_seen_in_game_flags_because_the_report_is_public(tmp_path):
    seen = mine("w1", "Zorblax Ring", evidence={"level": "strict", "reasons": [{"code": "seen-in-game", "seal": "measured", "text": "x"}]})
    with pytest.raises(ValueError, match="seen-in-game"):
        read_catalog(write_json(tmp_path / "catalog.json", catalog_document([seen])))


def test_read_catalog_allows_other_strict_reasons(tmp_path):
    community = mine("w1", "Zorblax Ring", evidence={"level": "strict", "reasons": [{"code": "community-report", "seal": "player", "text": "x"}]})
    assert len(read_catalog(write_json(tmp_path / "catalog.json", catalog_document([community])))["items"]) == 1


# ---- seen-in-game flags are private, and the report is public --------------------------------------------------------

SEEN = "seen" + "-in-" + "game"  # joined here so that this file does not hold the code of a private flag


def seen_item(reasons=None, **fields):
    reasons = [{"code": SEEN, "seal": "measured", "text": "x"}] if reasons is None else reasons
    return mine("w1", "Zorblax Ring", evidence={"level": "strict", "reasons": reasons}, **fields)


@pytest.mark.parametrize(
    "item",
    [
        seen_item(),
        seen_item([SEEN]),  # a reason stored as a plain string
        seen_item([{"code": SEEN.upper(), "seal": "measured", "text": "x"}]),
        seen_item([{"code": "community-report"}, {"code": SEEN + ":Some Zone"}]),
        seen_item(note=SEEN),  # anywhere in the item, under any name
        seen_item(extra={"deeper": [{"list": (SEEN,)}]}),
        mine("w1", "Zorblax Ring", **{SEEN: True}),  # as a key
        mine("w1", SEEN),  # as a name
    ],
)
def test_diff_refuses_a_catalog_item_that_carries_a_seen_flag_in_any_shape(item):
    with pytest.raises(ValueError, match=SEEN):
        diff([item, mine("w2", "Quimmet Band")], gear(theirs("Zorblax Ring")))


def test_diff_refuses_a_seen_flag_in_a_catalog_given_as_an_iterator_and_in_the_eqltools_data():
    with pytest.raises(ValueError, match=SEEN):
        diff(iter([mine("w2", "Quimmet Band"), seen_item()]), gear(theirs("Zorblax Ring")))
    with pytest.raises(ValueError, match=SEEN):
        diff([mine("w1", "Zorblax Ring")], gear(theirs("Zorblax Ring", note=SEEN)))


def test_diff_still_takes_an_iterator_and_other_strict_reasons():
    community = mine("w1", "Zorblax Ring", evidence={"level": "strict", "reasons": [{"code": "community-report", "seal": "player", "text": "x"}]})
    d = diff(iter([community, mine("w2", "Quimmet Band")]), gear(theirs("Zorblax Ring"), theirs("Quimmet Band")))
    assert d["totals"]["matched"] == 2


def test_the_refusal_is_one_line_and_holds_no_item_name():
    with pytest.raises(ValueError) as caught:
        diff([seen_item()], gear(theirs("Zorblax Ring")))
    assert "\n" not in str(caught.value) and "Zorblax" not in str(caught.value)


def test_a_report_cannot_be_rendered_with_the_code_of_a_seen_flag_in_it():
    d = diff([mine("w1", "Zorblax Ring", evidence={"level": "hidden", "reasons": [{"code": "out-of-era"}]})], gear(theirs("Zorblax Ring", oe=0)))
    assert SEEN not in render_markdown(d)
    d["oe_by_reason"] = {side: {SEEN: 1} for side in d["oe_by_reason"]}  # a result put together by hand
    with pytest.raises(ValueError, match=SEEN):
        render_markdown(d)


def test_the_reviewers_case_a_diff_of_a_seen_catalog_has_no_report():
    """The library path (no file read) used to give a report that listed the code in its table of reasons."""
    seen = mine("w1", "Zorblax Ring", evidence={"level": "strict", "reasons": [{"code": SEEN, "seal": "measured", "text": "Seen in game."}]})
    with pytest.raises(ValueError, match=SEEN):
        render_markdown(diff([seen], gear(theirs("Zorblax Ring", oe=1))))


@pytest.mark.parametrize(
    "text",
    [
        '{"version": "2026-10-14", "items": [], "note": "' + SEEN + '"}',  # anywhere in the text, not only in a reason
        '{"version": "2026-10-14", "items": [], "note": "' + SEEN.upper() + '"}',
        '{"version": "2026-10-14", "items": [], "note": "seen\\u002din-game"}',  # a JSON escape for the hyphen
        '{"version": "2026-10-14", "items": [{"key": "w1", "name": "x", "evidence": {"level": "strict", "reasons": ["' + SEEN + '"]}}]}',
        '{"version": "2026-10-14", "items": [{"key": "w1", "name": "x", "' + SEEN + '": 1}]}',
    ],
)
def test_read_catalog_refuses_a_file_whose_text_mentions_a_seen_flag_anywhere(tmp_path, text):
    path = tmp_path / "catalog.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=SEEN) as caught:
        read_catalog(path)
    assert "\n" not in str(caught.value) and "w1" not in str(caught.value)


def test_read_eqltools_refuses_a_file_whose_text_mentions_a_seen_flag(tmp_path):
    document = gear(theirs("Zorblax Ring"))
    document["meta"]["source"] = "see " + SEEN
    with pytest.raises(ValueError, match=SEEN):
        read_eqltools(write_json(tmp_path / "gear.json", document))
    document["meta"]["source"] = "eqlwiki.com"
    assert len(read_eqltools(write_json(tmp_path / "gear.json", document))["items"]) == 1


@pytest.mark.parametrize("which", ["catalog", "gear"])
def test_the_command_refuses_a_file_with_a_seen_flag_in_it_and_writes_nothing(tmp_path, capsys, which):
    flagged = seen_item(reasons=[SEEN])
    catalog_path, gear_path = files(tmp_path, catalog=catalog_document([flagged]) if which == "catalog" else None)
    if which == "gear":
        document = gear(theirs("Zorblax Ring"))
        document["meta"]["source"] = SEEN
        write_json(gear_path, document)
    out = tmp_path / "out" / "report.md"
    assert main(["--catalog", str(catalog_path), "--eqltools", str(gear_path), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and err.count("\n") == 1 and SEEN in err
    assert not out.exists() and not out.parent.exists()


def test_read_eqltools_requires_the_licence_and_items(tmp_path):
    assert len(read_eqltools(write_json(tmp_path / "gear.json", gear(theirs("Zorblax Ring"))))["items"]) == 1
    for meta in (None, {}, {"license": "All rights reserved"}, {"license": "cc by-sa 4.0"}, "CC BY-SA 4.0"):
        document = gear(theirs("Zorblax Ring"))
        document["meta"] = meta
        with pytest.raises(ValueError, match="licence"):
            read_eqltools(write_json(tmp_path / "gear.json", document))
    with pytest.raises(ValueError, match="items"):
        read_eqltools(write_json(tmp_path / "gear.json", {"meta": {"license": "CC BY-SA 4.0"}}))


@pytest.mark.parametrize("text", ["not json", '{"meta": {"license": "CC BY-SA 4.0"}, "meta": {}}'])
def test_a_file_that_is_not_strict_json_is_refused_without_echoing_it(tmp_path, text):
    path = tmp_path / "gear.json"
    path.write_text(text, encoding="utf-8")
    for reader in (read_eqltools, read_catalog):
        with pytest.raises(ValueError) as caught:
            reader(path)
        assert text[:10] not in str(caught.value)


# ---- the command line -----------------------------------------------------------------------------------------


def files(tmp_path, catalog=None, source=None):
    catalog_path = write_json(tmp_path / "catalog.json", catalog if catalog is not None else catalog_document())
    gear_path = write_json(
        tmp_path / "gear-data-2026-10-11.json",
        source if source is not None else gear(theirs("Zorblax Ring"), theirs("Quimmet Band", st={"ac": 22}), theirs("Orphan Charm")),
    )
    return catalog_path, gear_path


def test_the_command_writes_the_report_and_prints_the_headline(tmp_path, capsys):
    catalog_path, gear_path = files(tmp_path)
    out = tmp_path / "reports" / "eqltools-diff-2026-10-14.md"
    argv = ["--catalog", str(catalog_path), "--eqltools", str(gear_path), "--out", str(out), "--date", "2026-10-14"]
    assert main(argv) == 0
    printed = capsys.readouterr().out
    assert printed.count("\n") == 1 and "eqltools-diff-2026-10-14.md" in printed
    assert "2 matched" in printed and "1 only in EQL Tools" in printed
    assert str(tmp_path) not in printed
    text = out.read_text(encoding="utf-8")
    assert CREDIT in text and "2026-10-14" in text
    assert hashlib.sha256(catalog_path.read_bytes()).hexdigest() in text
    assert hashlib.sha256(gear_path.read_bytes()).hexdigest() in text
    assert "catalog.json" in text and "gear-data-2026-10-11.json" in text
    assert str(tmp_path) not in text and "\\" not in text.replace("\\|", "")  # no folder of this machine in the report
    first = out.read_bytes()
    assert main(argv) == 0
    assert out.read_bytes() == first


def test_the_default_output_is_reports_eqltools_diff_dated(tmp_path, monkeypatch, capsys):
    catalog_path, gear_path = files(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["--catalog", str(catalog_path), "--eqltools", str(gear_path), "--date", "2026-10-14"]) == 0
    assert (tmp_path / "reports" / "eqltools-diff-2026-10-14.md").is_file()
    capsys.readouterr()


@pytest.mark.parametrize("case", ["missing-catalog", "missing-gear", "bad-licence", "seen", "not-json", "no-items"])
def test_the_command_ends_with_status_two_and_one_line_and_writes_nothing(tmp_path, capsys, case):
    seen = mine("w1", "Zorblax Ring", evidence={"level": "strict", "reasons": [{"code": "seen-in-game", "seal": "measured", "text": "x"}]})
    catalog_path, gear_path = files(tmp_path, catalog=catalog_document([seen]) if case == "seen" else None)
    if case == "missing-catalog":
        catalog_path = tmp_path / "nothing.json"
    if case == "missing-gear":
        gear_path = tmp_path / "nothing.json"
    if case == "bad-licence":
        write_json(gear_path, {"meta": {"license": "proprietary"}, "items": {}})
    if case == "not-json":
        gear_path.write_text("not json at all", encoding="utf-8")
    if case == "no-items":
        write_json(gear_path, {"meta": {"license": "CC BY-SA 4.0"}, "items": {}})
    out = tmp_path / "out" / "report.md"
    assert main(["--catalog", str(catalog_path), "--eqltools", str(gear_path), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and err.count("\n") == 1
    assert not out.exists() and not out.parent.exists()


def test_a_failed_run_leaves_an_old_report_as_it_was(tmp_path, capsys):
    catalog_path, gear_path = files(tmp_path)
    out = tmp_path / "report.md"
    out.write_text("old", encoding="utf-8")
    gear_path.write_text("not json", encoding="utf-8")
    assert main(["--catalog", str(catalog_path), "--eqltools", str(gear_path), "--out", str(out)]) == 2
    assert out.read_text(encoding="utf-8") == "old"
    capsys.readouterr()


def test_a_bad_date_is_a_usage_error():
    with pytest.raises(SystemExit) as caught:
        main(["--catalog", "a", "--eqltools", "b", "--date", "2026-02-30"])
    assert caught.value.code == 2


# ---- the real file (skipped when the git-ignored copy is not here) ----------------------------------------------

REAL_GEAR = REPO / "sources" / "eqltools" / "gear-data-2026-10-11.json"


@pytest.mark.skipif(not REAL_GEAR.is_file(), reason="the EQL Tools gear copy is git-ignored and not here")
def test_the_real_gear_file_has_the_shape_the_diff_reads():
    document = read_eqltools(REAL_GEAR)
    records = list(document["items"].values())
    assert len(records) > 6000
    assert all(isinstance(r, dict) and isinstance(r.get("n"), str) and r["n"].strip() for r in records)
    assert all(isinstance(r.get("sl"), list) and r["sl"] for r in records)
    assert {key for r in records if isinstance(r.get("cls"), dict) for key in r["cls"]} == {"all", "x", "c"}
    assert {key for r in records if isinstance(r.get("st"), dict) for key in r["st"]} <= set("ac str sta agi dex wis int cha hp mana end atk".split())
    assert {key for r in records if isinstance(r.get("sv"), dict) for key in r["sv"]} <= set("fcmpdv")
    assert all(isinstance(r["haste"], (int, float)) for r in records if "haste" in r)
    assert all(r["era"] is None or isinstance(r["era"], str) for r in records if "era" in r)
    nothing = diff([], document)
    assert nothing["totals"]["unreadable_theirs"] == 0
    assert nothing["totals"]["only_theirs"] + nothing["totals"]["ambiguous_theirs"] == nothing["totals"]["theirs"]
