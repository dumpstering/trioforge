"""Tests for the checks K1 to K8 and K11 and the scoreboard that counts them.

Each check is tried on kits written by hand from invented items (``kits_fixture``), at +0 where a number has to be worked out on paper and at +4 where the tier rule
is the point. The trio PAL/MNK/ENC of the human race has a plate class (so it is a tank trio with a robe to wear), a mana class of WIS and one of INT.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from kits_fixture import PLATE, armour, base_items, item, make_results, row

from trioforge import rules as rules_module
from trioforge.checks.kits import (
    CHECKS,
    FAIL,
    GATES,
    INFO,
    K3_MIN_RATIO,
    NA,
    PASS,
    SCOREBOARD_ONLY,
    WINDSTRIKER,
    Context,
    Scoreboard,
)
from trioforge.checks.results import Results
from trioforge.data import races
from trioforge.data.jsonio import load_strict
from trioforge.model.buffs import buffsets

TRIO = "pal-mnk-enc"
PIPELINE = Path(__file__).resolve().parents[1]
REPO = PIPELINE.parent


@pytest.fixture(scope="module")
def rules():
    return rules_module.load()


@pytest.fixture
def build(tmp_path, rules):
    """``build(trios, records=None, race="HUM", softcap=400)`` writes a results folder and returns its :class:`Results` and a :class:`Context` of it (two items make a generic set)."""
    counter = iter(range(1000))

    def make(trios, records=None, **kwargs):
        root = make_results(tmp_path / f"results-{next(counter)}", base_items() if records is None else records, trios, **kwargs)
        results = Results(root, rules=rules)
        return results, Context(results, min_set_items=2)

    return make


def outcomes(build, rows, trio=TRIO, **kwargs):
    """The outcomes of the checks for each kit of ``rows`` (a dict by (role, tier))."""
    results, context = build({trio: rows}, **kwargs)
    return {(kit.role, kit.tier): context.evaluate(kit) for kit in results.kits(trio)}, results, context


def test_there_is_one_line_for_every_check_the_brief_names():
    ids = [check.id for check in CHECKS]
    assert ids[:3] == ["K1.attr", "K1.pool", "K2"]
    assert {"K3", "K3.robe", "K3.robe_worn", "K5.bow", "K5.windstriker", "K6", "K7", "K8", "K11"} <= set(ids)
    assert {f"K3.{slot}" for slot in ("CHEST", "LEGS", "ARMS", "HEAD", "HANDS", "FEET")} <= set(ids)
    assert len(ids) == len(set(ids))
    assert all(check.sentence.endswith(".") and check.title for check in CHECKS)


def test_k1_does_not_call_the_mana_pool_caster_stats():
    """The pool number is not "caster stats": the title and the sentence of the check name the mana pool, and the attribute number names WIS and INT."""
    by_id = {check.id: check for check in CHECKS}
    assert "caster" not in by_id["K1.pool"].title.casefold() and "caster" not in by_id["K1.pool"].sentence.casefold()
    assert "mana pool" in by_id["K1.pool"].sentence
    assert "WIS" in by_id["K1.attr"].sentence and "INT" in by_id["K1.attr"].sentence


def test_the_gates_are_k2_and_the_robe_of_k3_and_the_scoreboard_only_checks_are_listed():
    assert GATES == ("K2", "K3.robe")
    assert SCOREBOARD_ONLY == ("K1.attr", "K1.pool", "K3.robe_worn", "K4", "K6", "K7", "K8", "K10", "K11", "K12")
    assert not set(GATES) & set(SCOREBOARD_ONLY)


# ---- K1 ----------------------------------------------------------------------------------------------------------------------------


def test_k1_pool_counts_the_share_of_wis_int_and_mana_among_the_stat_points(build):
    out, *_ = outcomes(build, [row("tank", 0, {"FACE": "Glimmer Idol", "WAIST": "Brawn Belt", "EAR1": "Moonstud"})])
    k1 = out[("tank", 0)]["K1.pool"]
    # INT 10 + WIS 10 + CHA 5 (the face), STR 20 + AC 2 (the belt), STA 5 (the ear)
    assert (k1.detail["pool"], k1.detail["points"]) == (20, 52)
    assert k1.value == pytest.approx(20 / 52) and k1.status == INFO  # a scoreboard: no threshold, no pass and no fail


def test_k1_attr_counts_the_share_of_wis_and_int_among_the_attribute_points_of_the_items(build):
    out, *_ = outcomes(build, [row("tank", 0, {"FACE": "Glimmer Idol", "WAIST": "Brawn Belt", "EAR1": "Moonstud"})])
    k1 = out[("tank", 0)]["K1.attr"]
    # STR 20 and STA 5 and WIS 10, INT 10 and CHA 5: five attributes, AC (2) is none; WIS and INT are 20 of 50
    assert (k1.detail["wis_int"], k1.detail["attributes"]) == (20, 50)
    assert k1.value == pytest.approx(0.4) and k1.status == INFO


def test_k1_attr_is_the_points_of_the_items_whatever_the_trio_can_use(build):
    kit = {"FACE": "Glimmer Idol", "WAIST": "Brawn Belt"}  # WIS 10, INT 10, CHA 5, STR 20 (AC 2)
    no_mana, *_ = outcomes(build, [row("tank", 0, kit)], trio="war-mnk-rog")  # no mana pool: the objective has no use for WIS and INT, the items have them all the same
    assert (no_mana[("tank", 0)]["K1.attr"].detail["wis_int"], no_mana[("tank", 0)]["K1.attr"].detail["attributes"]) == (20, 45)
    assert no_mana[("tank", 0)]["K1.pool"].detail["pool"] == 0  # and the pool number leaves them out


@pytest.mark.parametrize("check_id", ["K1.attr", "K1.pool"])
def test_k1_is_a_distribution_and_never_a_pass_or_a_fail(build, check_id):
    rows = [row("tank", 0, {"RANGE": "Dimble Charm", "EAR1": "Moonstud"}), row("melee", 0, {"WAIST": "Brawn Belt"}), row("tank", 4, {"FACE": "Glimmer Idol", "WAIST": "Brawn Belt"})]
    out, *_ = outcomes(build, rows)
    assert {outcome[check_id].status for outcome in out.values()} == {INFO}
    assert check_id not in GATES


def test_k1_pool_leaves_out_the_stats_the_objective_has_no_use_for(build):
    kit = {"FACE": "Glimmer Idol", "WAIST": "Brawn Belt"}  # INT 10, WIS 10, CHA 5, STR 20, AC 2
    rows = [row("tank", 0, kit)]
    no_mana, *_ = outcomes(build, rows, trio="war-mnk-rog")  # no class has a mana pool: WIS, INT and mana are worth nothing
    assert (no_mana[("tank", 0)]["K1.pool"].detail["pool"], no_mana[("tank", 0)]["K1.pool"].detail["points"]) == (0, 27)
    only_wis, *_ = outcomes(build, rows, trio="pal-war-mnk")  # Paladin mana is made of WIS: INT is worth nothing
    assert (only_wis[("tank", 0)]["K1.pool"].detail["pool"], only_wis[("tank", 0)]["K1.pool"].detail["points"]) == (10, 37)
    both, *_ = outcomes(build, rows, trio=TRIO)  # an Enchanter's mana is made of INT
    assert (both[("tank", 0)]["K1.pool"].detail["pool"], both[("tank", 0)]["K1.pool"].detail["points"]) == (20, 37 + 10)


def test_k1_is_not_applicable_to_other_roles_nor_to_an_empty_kit(build):
    out, *_ = outcomes(build, [row("caster", 0, {"FACE": "Glimmer Idol"}), row("balanced", 0, {"FACE": "Glimmer Idol"}), row("tank", 0, {})])
    for check_id in ("K1.attr", "K1.pool"):
        assert out[("caster", 0)][check_id].status == NA and out[("balanced", 0)][check_id].status == NA
        assert out[("tank", 0)][check_id].status == NA  # no point at all


def test_k1_has_nothing_to_say_of_a_role_the_trio_is_not_offered(build):
    out, *_ = outcomes(build, [row("tank", 0, {"FACE": "Glimmer Idol"})], trio="mnk-enc-wiz")  # no tank class: the weights of the role cannot be read
    assert out[("tank", 0)]["K1.pool"].status == NA


def test_k1_reads_the_stats_at_the_tier_of_the_kit(build):
    out, *_ = outcomes(build, [row("tank", 4, {"RANGE": "Dimble Charm", "HANDS": "Bruiser Mitts"})])
    detail = out[("tank", 4)]["K1.pool"].detail
    assert (detail["pool"], detail["points"]) == (9, 30)  # +4: base + max(4, base * 4 // 10), so INT 5 is 9 and STR 15 is 21
    assert out[("tank", 4)]["K1.attr"].detail == {"wis_int": 9, "attributes": 30}


# ---- K2 ----------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "pure"),
    [
        ("Glimmer Idol", True),  # INT, WIS, CHA, and a resist that is left aside
        ("Tidepool Sigil", True),  # mana regeneration only
        ("Dimble Charm", True),
        ("Sorrel Staff", False),  # a weapon: its damage is a stat
        ("Swiftling Band", False),  # worn haste
        ("Plain Cloak", False),  # a resist and nothing else: no positive stat at all
        ("Brawn Belt", False),
        ("Ombrel Vestment", False),  # AC
        ("Moonstud", False),
        ("Mindcrown Helm", False),  # AC as well, and caster stats besides
    ],
)
def test_k2_pure_caster_items(build, name, pure):
    results, context = build({TRIO: [row("tank", 0, {})]})
    (key,) = results.table.keys_named(name)
    for tier in (0, 4, 10):
        assert context.is_pure_caster(results.table.vec(key, tier)) is pure


def test_k2_fails_a_kit_that_wears_a_pure_caster_item_and_names_it(build):
    kit = {"FACE": "Glimmer Idol", "NECK": "Tidepool Sigil", "PRIMARY": "Sorrel Staff", "FINGER1": "Swiftling Band", "BACK": "Plain Cloak", "ANY1": "Glimmer Idol"}
    out, *_ = outcomes(build, [row("melee", 0, kit), row("tank", 0, {"WAIST": "Brawn Belt"})])
    k2 = out[("melee", 0)]["K2"]
    assert k2.status == FAIL and k2.value == 2 and k2.detail["items"] == ["Glimmer Idol", "Tidepool Sigil"]  # one item worn twice is one item
    assert out[("tank", 0)]["K2"].status == PASS and out[("tank", 0)]["K2"].value == 0


def test_k2_applies_to_melee_and_tank_only(build):
    out, *_ = outcomes(build, [row("caster", 0, {"FACE": "Glimmer Idol"}), row("balanced", 0, {"FACE": "Glimmer Idol"})])
    assert out[("caster", 0)]["K2"].status == NA and out[("balanced", 0)]["K2"].status == NA


def test_k2_says_how_many_distinct_items_are_behind_the_failures_and_which_five_are_worn_most(build):
    pure = [item(f"Pure Trinket {n}", ["EAR"], None, {"WIS": 3}) for n in range(1, 8)]
    # kit t wears the first t + 1 of the seven: Pure Trinket 1 is in seven kits, the last one in one
    rows = [row("melee", t, {place: f"Pure Trinket {n + 1}" for n, place in enumerate(("EAR1", "EAR2", "NECK", "FACE", "BACK", "WAIST", "HANDS")[: t + 1])}) for t in range(7)]
    results, context = build({TRIO: rows}, records=[*base_items(), *pure])
    board = Scoreboard(context)
    for kit in results.all_kits():
        board.add(kit)
    k2 = board.document()["checks"]["K2"]
    assert k2["distinct_items"] == 7
    assert k2["top_items"] == [{"item": f"Pure Trinket {n}", "kits": 8 - n} for n in range(1, 6)]
    assert len(k2["offenders"]) == 7  # the whole list stays in the JSON


# ---- K3 ----------------------------------------------------------------------------------------------------------------------------

MIXED = {"CHEST": "Ombrel Vestment", "LEGS": "Zarn Greaves", "ARMS": "Mepp Sleeves", "HEAD": "Tolk Helm", "HANDS": "Vlorn Gloves"}  # the feet are bare
SLOTS = ("CHEST", "LEGS", "ARMS", "HEAD", "HANDS", "FEET")


def test_k3_compares_each_slot_with_the_best_ac_the_trio_can_wear_there(build):
    out, *_ = outcomes(build, [row("tank", 0, MIXED)])
    k3 = out[("tank", 0)]
    ratios = {slot: k3[f"K3.{slot}"].value for slot in SLOTS}
    # best at +0 is 30 in every slot: the hidden, deity-locked, disputed, hand-in, caster-stat, Ogre-only and Bard-only helms are not there to be worn
    assert ratios == pytest.approx({"CHEST": 4 / 30, "LEGS": 0.5, "ARMS": 0.5, "HEAD": 10 / 30, "HANDS": 1.0, "FEET": 0.0})
    assert K3_MIN_RATIO == 0.5
    assert {slot: k3[f"K3.{slot}"].status for slot in ratios} == {"CHEST": FAIL, "LEGS": PASS, "ARMS": PASS, "HEAD": FAIL, "HANDS": PASS, "FEET": FAIL}
    assert k3["K3"].status == FAIL and k3["K3"].value == 0.0 and k3["K3"].detail["failed"] == ["CHEST", "FEET", "HEAD"]


def test_k3_passes_a_kit_of_the_best_pieces(build):
    kit = {"CHEST": "Vlorn Tunic", "LEGS": "Vlorn Greaves", "ARMS": "Quibbit Sleeves", "HEAD": "Vlorn Helm", "HANDS": "Vlorn Gloves", "FEET": "Vlorn Boots"}
    out, *_ = outcomes(build, [row("tank", 0, kit)])
    assert out[("tank", 0)]["K3"].status == PASS and out[("tank", 0)]["K3"].value == 1.0 and out[("tank", 0)]["K3"].detail["failed"] == []
    assert out[("tank", 0)]["K3.robe"].status == PASS


def test_k3_reads_the_ac_at_the_tier_of_the_kit(build):
    out, *_ = outcomes(build, [row("tank", 4, {"HEAD": "Tolk Helm", "LEGS": "Zarn Greaves"})])
    assert out[("tank", 4)]["K3.HEAD"].value == pytest.approx(14 / 42)  # 10 + 4 against 30 + 12
    assert out[("tank", 4)]["K3.LEGS"].value == pytest.approx(21 / 42)


def test_k3_pool_is_the_one_of_the_race_of_the_kit(build):
    ogre, *_ = outcomes(build, [row("tank", 0, {"HEAD": "Vlorn Helm"}, race="OGR")], race="OGR")
    assert ogre[("tank", 0)]["K3.HEAD"].value == 0.5  # the Ogre-only helm of 60 AC can be worn
    human, *_ = outcomes(build, [row("tank", 0, {"HEAD": "Vlorn Helm"})])
    assert human[("tank", 0)]["K3.HEAD"].value == 1.0


def test_k3_is_for_the_tank_role_of_a_trio_with_a_heavy_class(build):
    melee, *_ = outcomes(build, [row("melee", 0, MIXED)])
    assert {melee[("melee", 0)][check.id].status for check in CHECKS if check.id.startswith("K3")} == {NA}
    tank, results, context = outcomes(build, [row("tank", 0, MIXED)])
    assert tank[("tank", 0)]["K3"].status == FAIL
    context.armour = dataclasses.replace(context.armour, heavy=frozenset())  # a table with no armour weights: no class is the heaviest
    (kit,) = results.kits(TRIO)
    assert {outcome.status for check_id, outcome in context.evaluate(kit).items() if check_id.startswith("K3")} == {NA}


def test_k3_has_nothing_to_say_of_a_slot_with_no_ac_to_wear(build):
    records = base_items()
    for record in records:
        if record["name"].endswith("Boots"):
            record["stats"]["AC"] = 0  # no boots have any AC
    out, *_ = outcomes(build, [row("tank", 0, {"CHEST": "Vlorn Tunic"})], records=records)
    k3 = out[("tank", 0)]
    assert k3["K3.FEET"].status == NA and k3["K3.CHEST"].status == PASS
    assert "FEET" not in k3["K3"].detail["failed"]


def test_k3_best_ac_leaves_out_what_the_solver_leaves_out_and_what_a_tank_would_not_count(build):
    out, results, context = outcomes(build, [row("tank", 0, {"HEAD": "Vlorn Helm"})])
    assert out[("tank", 0)]["K3.HEAD"].detail["best"] == 30  # not the hand-in helm of 90 (not-for-bis), nor the helm of 60 whose other stats are WIS and INT
    plain = [*base_items(), item("Ironbound Helm", ["HEAD"], PLATE, {"AC": 70})]  # AC and nothing else is a tank's piece
    out, *_ = outcomes(build, [row("tank", 0, {"HEAD": "Vlorn Helm"})], records=plain)
    assert out[("tank", 0)]["K3.HEAD"].detail["best"] == 70
    haste = [*base_items(), item("Quickened Helm", ["HEAD"], PLATE, {"AC": 80, "INT": 9, "HASTE": 5})]  # worn haste is no caster stat: it counts
    out, *_ = outcomes(build, [row("tank", 0, {"HEAD": "Vlorn Helm"})], records=haste)
    assert out[("tank", 0)]["K3.HEAD"].detail["best"] == 80


# placement: the two Any places hold any item, and a swap of two places leaves the score of the kit as it was, so no armour check may read the named place alone


def test_k3_reads_the_best_piece_of_the_slot_worn_in_the_named_place_or_in_an_any_place(build):
    kit = {"CHEST": "Ombrel Vestment", "ANY1": "Vlorn Tunic", "HEAD": "Tolk Helm", "ANY2": "Vlorn Helm"}
    out, *_ = outcomes(build, [row("tank", 0, kit)])
    k3 = out[("tank", 0)]
    assert k3["K3.CHEST"].value == 1.0 and k3["K3.CHEST"].detail["ac"] == 30  # the plate piece in the Any place counts for the chest
    assert k3["K3.HEAD"].value == 1.0
    assert k3["K3.LEGS"].value == 0.0  # nothing of the legs anywhere


def test_k3_does_not_count_an_item_of_another_kind_worn_in_an_any_place(build):
    out, *_ = outcomes(build, [row("tank", 0, {"CHEST": "Tolk Tunic", "ANY1": "Brawn Belt", "ANY2": "Vlorn Helm"})])
    assert out[("tank", 0)]["K3.CHEST"].value == pytest.approx(10 / 30)  # the belt is a waist piece, the helm a head piece
    assert out[("tank", 0)]["K3.HEAD"].value == 1.0


PAIRS = list(itertools.permutations(("CHEST", "ANY1", "ANY2"), 2))


@pytest.mark.parametrize(("robe_at", "plate_at"), PAIRS)
def test_swapping_two_places_changes_no_armour_check(build, robe_at, plate_at):
    """The robe and the plate chest piece in every pair of the chest and the two Any places: the same outcome for each, the one of a plate piece and a robe worn together."""
    out, *_ = outcomes(build, [row("tank", 0, {robe_at: "Ombrel Vestment", plate_at: "Vlorn Tunic"})])
    k3 = out[("tank", 0)]
    assert (k3["K3.CHEST"].status, k3["K3.CHEST"].value) == (PASS, 1.0)
    assert k3["K3.robe"].status == PASS  # the best chest piece is the plate one
    assert k3["K3.robe_worn"].status == FAIL  # and the robe is worn all the same
    assert k3["K3"].value == 0.0 and k3["K3"].detail["failed"] == ["ARMS", "FEET", "HANDS", "HEAD", "LEGS"]


def test_k3_robe_is_a_robe_worn_in_the_chest_with_no_better_chest_piece(build):
    out, *_ = outcomes(build, [row("tank", 0, {"CHEST": "Ombrel Vestment"}), row("tank", 4, {"CHEST": "Tolk Tunic"}), row("tank", 10, {})])
    robe = out[("tank", 0)]["K3.robe"]
    assert robe.status == FAIL and robe.detail["chest"] == "Ombrel Vestment"
    assert out[("tank", 4)]["K3.robe"].status == PASS  # leather is no robe
    assert out[("tank", 10)]["K3.robe"].status == PASS  # no chest piece at all is no robe (the chest check fails it instead)
    assert out[("tank", 10)]["K3.CHEST"].status == FAIL


@pytest.mark.parametrize("place", ["CHEST", "ANY1", "ANY2"])
def test_k3_robe_fails_a_robe_that_is_the_only_chest_piece_wherever_it_is_worn(build, place):
    out, *_ = outcomes(build, [row("tank", 0, {place: "Ombrel Vestment", "HEAD": "Vlorn Helm"})])
    assert out[("tank", 0)]["K3.robe"].status == FAIL and out[("tank", 0)]["K3.robe"].detail["chest"] == "Ombrel Vestment"
    assert out[("tank", 0)]["K3.robe_worn"].status == FAIL


def test_k3_robe_passes_a_kit_that_wears_a_plate_piece_in_the_chest_and_a_robe_in_an_any_place(build):
    out, *_ = outcomes(build, [row("tank", 0, {"CHEST": "Vlorn Tunic", "ANY2": "Ombrel Vestment"})])
    assert out[("tank", 0)]["K3.robe"].status == PASS and out[("tank", 0)]["K3.robe_worn"].status == FAIL


def test_k3_robe_looks_at_the_best_chest_piece_by_ac_and_a_tie_goes_to_the_piece_that_is_no_robe(build):
    records = [*base_items(), item("Bare Tunic", ["CHEST"], PLATE, {"STA": 3}), item("Even Tunic", ["CHEST"], PLATE, {"AC": 4})]
    out, *_ = outcomes(
        build,
        [
            row("tank", 0, {"CHEST": "Bare Tunic", "ANY2": "Ombrel Vestment"}),  # an AC-0 piece in the chest and the robe (AC 4) in an Any place: the robe is the best
            row("tank", 4, {"CHEST": "Even Tunic", "ANY1": "Ombrel Vestment"}),  # a tie: the piece that is no robe is the best
            row("tank", 10, {"CHEST": "Ombrel Vestment", "ANY1": "Bare Tunic"}),
        ],
        records=records,
    )
    assert out[("tank", 0)]["K3.robe"].status == FAIL
    assert out[("tank", 4)]["K3.robe"].status == PASS  # +4: AC 4 + 4 for both
    assert out[("tank", 10)]["K3.robe"].status == FAIL


def test_a_chest_piece_that_cloth_leather_and_chain_wearers_share_is_no_robe(build):
    out, *_ = outcomes(build, [row("tank", 0, {"CHEST": "Strapweave Tunic"})])  # usable by a Monk and a Rogue
    assert out[("tank", 0)]["K3.robe"].status == PASS and out[("tank", 0)]["K3.robe_worn"].status == PASS


def test_k3_robe_worn_is_a_scoreboard_count_of_the_kits_that_wear_a_robe_anywhere(build):
    out, *_ = outcomes(build, [row("tank", 0, {"CHEST": "Vlorn Tunic"}), row("tank", 4, {"CHEST": "Vlorn Tunic", "ANY1": "Ombrel Vestment"}), row("melee", 4, {"ANY1": "Ombrel Vestment"})])
    assert out[("tank", 0)]["K3.robe_worn"].status == PASS and out[("tank", 4)]["K3.robe_worn"].status == FAIL
    assert out[("melee", 4)]["K3.robe_worn"].status == NA  # a tank check
    assert "K3.robe_worn" in SCOREBOARD_ONLY and "K3.robe_worn" not in GATES


# ---- K5 ----------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("range_item", "bow", "windstriker"),
    [("Fenwick Longbow", PASS, FAIL), (WINDSTRIKER, PASS, PASS), (WINDSTRIKER.upper(), PASS, PASS), ("Dimble Charm", FAIL, FAIL), ("Thrown Pebble", FAIL, FAIL), (None, FAIL, FAIL)],
)
def test_k5_a_bow_and_the_named_bow_in_the_range_slot_of_a_ranger_trio(build, range_item, bow, windstriker):
    records = base_items() + ([item(WINDSTRIKER.upper(), ["RANGE"], ["RNG"], {"STR": 5}, weapon={"skill": "Archery", "dmg": 45, "delay": 60, "bonus": None})] if range_item == WINDSTRIKER.upper() else [])
    out, *_ = outcomes(build, [row("melee", 0, {"RANGE": range_item} if range_item else {})], trio="rng-mnk-enc", records=records)
    assert (out[("melee", 0)]["K5.bow"].status, out[("melee", 0)]["K5.windstriker"].status) == (bow, windstriker)


def test_k5_is_not_applicable_to_a_trio_without_a_ranger(build):
    out, *_ = outcomes(build, [row("melee", 0, {"RANGE": "Dimble Charm"})])
    assert (out[("melee", 0)]["K5.bow"].status, out[("melee", 0)]["K5.windstriker"].status) == (NA, NA)


def test_k5_names_what_the_range_slot_holds(build):
    out, *_ = outcomes(build, [row("melee", 0, {"RANGE": "Dimble Charm"})], trio="rng-mnk-enc")
    assert out[("melee", 0)]["K5.bow"].detail["range"] == "Dimble Charm"


@pytest.mark.parametrize(("role", "applies"), [("melee", True), ("ranged", True), ("balanced", False), ("tank", False), ("caster", False)])
def test_k5_is_for_the_roles_where_a_bow_can_be_scored(build, role, applies):
    """A bow is scored for the roles that score weapon damage from the Range slot; the solver does not score Range damage today, and the check is for the role that will."""
    out, *_ = outcomes(build, [row(role, 0, {"RANGE": "Dimble Charm"})], trio="rng-war-clr")
    assert (out[(role, 0)]["K5.bow"].status != NA) is applies


@pytest.mark.parametrize("place", ["RANGE", "ANY1", "ANY2"])
def test_k5_a_bow_worn_in_an_any_place_is_worn_all_the_same(build, place):
    other = "RANGE" if place != "RANGE" else "ANY1"
    out, *_ = outcomes(build, [row("melee", 0, {place: WINDSTRIKER, other: "Dimble Charm"})], trio="rng-mnk-enc")
    assert (out[("melee", 0)]["K5.bow"].status, out[("melee", 0)]["K5.windstriker"].status) == (PASS, PASS)


# ---- K6 ----------------------------------------------------------------------------------------------------------------------------


def test_k6_strength_of_the_kit_against_the_best_the_pool_could_give(build):
    out, results, context = outcomes(build, [row("melee", 0, {"WAIST": "Brawn Belt"}), row("melee", 4, {"WAIST": "Brawn Belt", "HANDS": "Bruiser Mitts"}), row("melee", 10, {})])
    k6 = out[("melee", 0)]["K6"]
    # an item that is not Lore may be worn in every place that takes it, as the solver wears it: the belt in the waist and in both Any places, the mitts in the hands
    assert k6.status == INFO and k6.detail["gear"] == 20 and k6.detail["best"] == 20 * 3 + 15  # the Ogre's torc and the Ranger's bows are not for this trio
    assert k6.value == pytest.approx(20 / 75)
    assert k6.detail["naked"] == races.naked_stats("HUM", ("PAL", "MNK", "ENC"))["STR"]
    four = out[("melee", 4)]["K6"]
    assert four.detail["best"] == 28 * 3 + 21 and four.value == pytest.approx(49 / 105)  # +4: 20 + 8 and 15 + 6
    assert out[("melee", 10)]["K6"].value == 0.0


def test_k6_the_pool_of_the_race_includes_its_own_items(build):
    out, *_ = outcomes(build, [row("melee", 0, {"NECK": "Ogrebite Torc"}, race="OGR")], race="OGR")
    assert out[("melee", 0)]["K6"].detail["best"] == 30 * 3 + 20 + 15  # the torc in the neck and the Any places, the belt, the mitts


def test_k6_a_lore_item_is_worn_once(build):
    records = [item("Lore Belt", ["WAIST"], None, {"STR": 20}, lore=True), item("Plain Mitts", ["HANDS"], None, {"STR": 5})]
    out, *_ = outcomes(build, [row("melee", 0, {})], records=records)
    assert out[("melee", 0)]["K6"].detail["best"] == 20 + 5 * 3  # the belt once; the mitts in the hands and in both Any places
    records = [item("Plain Belt", ["WAIST"], None, {"STR": 20}), item("Plain Mitts", ["HANDS"], None, {"STR": 5})]
    out, *_ = outcomes(build, [row("melee", 0, {})], records=records)
    assert out[("melee", 0)]["K6"].detail["best"] == 20 * 3 + 5


def test_k6_is_held_to_the_stat_cap(build):
    records = [item("Colossus Belt", ["WAIST"], None, {"STR": 900}), item("Titan Mitts", ["HANDS"], None, {"STR": 100})]
    out, results, context = outcomes(build, [row("melee", 0, {"WAIST": "Colossus Belt"}), row("melee", 4, {"HANDS": "Titan Mitts"})], records=records)
    naked = out[("melee", 0)]["K6"].detail["naked"]
    room = context.cap - naked
    assert out[("melee", 0)]["K6"].detail["gear"] == room and out[("melee", 0)]["K6"].detail["best"] == room and out[("melee", 0)]["K6"].value == 1.0
    assert out[("melee", 4)]["K6"].detail["gear"] == 100 + 40 and out[("melee", 4)]["K6"].value == pytest.approx(140 / room)


def test_k6_needs_a_melee_kit_and_a_pool_with_strength(build):
    out, *_ = outcomes(build, [row("tank", 0, {"WAIST": "Brawn Belt"})])
    assert out[("tank", 0)]["K6"].status == NA
    out, *_ = outcomes(build, [row("melee", 0, {})], records=armour("Vlorn", PLATE, 30))
    assert out[("melee", 0)]["K6"].status == NA  # nothing in the pool has any strength


def test_the_best_gear_gives_every_lore_item_one_place_and_every_place_one_item(build):
    records = [item("Alpha Cap", ["HEAD"], None, {"STR": 10}, lore=True), item("Beta Cap", ["HEAD", "FACE"], None, {"STR": 9}, lore=True), item("Gamma Cap", ["HEAD"], None, {"STR": 8}, lore=True)]
    records += [item("Delta Cap", ["HEAD"], None, {"STR": 7}, lore=True), item("Epsilon Cap", ["HEAD"], None, {"STR": 6}, lore=True)]
    records += [item(f"Ear {n}", ["EAR"], None, {"STR": n}, lore=True) for n in range(1, 8)]  # seven ears for two ear places and two Any places
    results, context = build({TRIO: [row("melee", 0, {})]}, records=records)
    (kit,) = results.kits(TRIO)
    # four caps fill HEAD, FACE (only Beta fits there, so Beta must not keep HEAD) and the two Any places: 10 + 9 + 8 + 7; the two ears are the best of seven, 7 and 6;
    # the fifth cap and the other ears have no place left
    assert context.best_gear(kit, "STR") == 10 + 9 + 8 + 7 + 7 + 6


def test_the_best_gear_moves_a_lore_item_to_another_place_to_make_room_for_one_that_has_no_other(build):
    records = [item(f"Ear {n}", ["EAR"], None, {"STR": 50 - n}, lore=True) for n in range(4)]  # 50, 49, 48, 47: the two ears and the two Any places
    records += [item("Beta Cap", ["HEAD", "FACE"], None, {"STR": 10}, lore=True), item("Alpha Cap", ["HEAD"], None, {"STR": 9}, lore=True)]
    results, context = build({TRIO: [row("melee", 0, {})]}, records=records)
    (kit,) = results.kits(TRIO)
    # Beta is seated first, in HEAD; Alpha fits nowhere else (the Any places are full), so Beta has to move to FACE
    assert context.best_gear(kit, "STR") == 50 + 49 + 48 + 47 + 10 + 9


def test_the_best_gear_wears_an_item_that_is_not_lore_in_every_place_that_takes_it(build):
    records = [item("Ear A", ["EAR"], None, {"STR": 7}), item("Ear B", ["EAR"], None, {"STR": 5}), item("Cap A", ["HEAD", "FACE"], None, {"STR": 3})]
    results, context = build({TRIO: [row("melee", 0, {})]}, records=records)
    (kit,) = results.kits(TRIO)
    # Ear A in both ears and both Any places (4 x 7), the cap in the head and the face (2 x 3): Ear B is never the best for a place
    assert context.best_gear(kit, "STR") == 7 * 4 + 3 * 2


# ---- K7, K8 and K11 ----------------------------------------------------------------------------------------------------------------


def test_k7_sums_the_five_resists_of_the_sheet(build):
    totals = {"fire": 10, "cold": 20, "magic": 30, "poison": 40, "disease": 50, "hp": 999, "ac": 400}
    out, *_ = outcomes(build, [row("balanced", 4, {}, totals=totals), row("caster", 4, {}, totals={})])
    assert out[("balanced", 4)]["K7"].status == INFO and out[("balanced", 4)]["K7"].value == 150
    assert out[("balanced", 4)]["K7"].detail == {"fire": 10, "cold": 20, "magic": 30, "poison": 40, "disease": 50}
    assert out[("caster", 4)]["K7"].value == 0


@pytest.mark.parametrize(("ac", "status", "margin"), [(410, PASS, 10), (400, PASS, 0), (399, FAIL, -1), (150, FAIL, -250)])
def test_k8_the_sheet_ac_against_the_soft_cap_of_the_trio(build, ac, status, margin):
    out, *_ = outcomes(build, [row("tank", 4, {}, totals={"ac": ac})], softcap=400)
    k8 = out[("tank", 4)]["K8"]
    assert (k8.status, k8.value) == (status, margin) and k8.detail == {"ac": ac, "softcap": 400}


def test_k8_is_for_the_tank_role(build):
    out, *_ = outcomes(build, [row("melee", 4, {}, totals={"ac": 999}), row("balanced", 4, {}, totals={"ac": 999})])
    assert out[("melee", 4)]["K8"].status == NA and out[("balanced", 4)]["K8"].status == NA


def _naked_and_buff_sta(rules, trio, race="HUM"):
    """The STA of the character before any gear: the race and class modifiers, and the always-on buffs of the trio (read straight from the model, not through the checks)."""
    codes = tuple(trio.upper().split("-"))
    naked = races.naked_stats(race, codes)["STA"]
    buffset = buffsets(codes, 50, load_strict(REPO / "derived" / "client" / "spells-l50.json"), rules, ("own",))["own"]  # (the buffs the kits are chosen with: no spell haste in them)
    return naked, buffset.totals(()).get("STA", 0)


@pytest.mark.parametrize(
    ("gap", "status"),
    [(3, PASS), (2, FAIL), (1, FAIL), (0, PASS), (-5, PASS)],  # the knee less the STA total: within 2 points under the knee fails, at it and past it do not
)
def test_k11_counts_the_kits_whose_stamina_sits_within_two_points_under_the_knee(build, rules, gap, status):
    knee = rules.get("stats.knee")
    naked, buff = _naked_and_buff_sta(rules, TRIO)
    gear = knee - gap - naked - buff
    assert gear > 0
    records = [*base_items(), item("Stamina Charm", ["NECK"], None, {"STA": gear})]
    out, *_ = outcomes(build, [row("tank", 0, {"NECK": "Stamina Charm"})], records=records)
    k11 = out[("tank", 0)]["K11"]
    assert (k11.status, k11.value) == (status, gap) and k11.detail["sta"] == knee - gap and k11.detail["knee"] == knee


def test_k11_is_for_the_tank_and_the_shield_caster_builds_and_a_scoreboard_only_check(build):
    out, *_ = outcomes(build, [row("tank", 0, {}), row("shield", 0, {}), row("melee", 0, {}), row("caster", 0, {}), row("balanced", 0, {})])
    assert {o["K11"].status for key, o in out.items() if key[0] in ("tank", "shield")} <= {PASS, FAIL}
    assert {o["K11"].status for key, o in out.items() if key[0] not in ("tank", "shield")} == {NA}
    assert "K11" in SCOREBOARD_ONLY and "K11" not in GATES


def test_k11_reads_the_stamina_at_the_tier_of_the_kit(build, rules):
    knee = rules.get("stats.knee")
    naked, buff = _naked_and_buff_sta(rules, TRIO)
    base = 40
    records = [*base_items(), item("Stamina Charm", ["NECK"], None, {"STA": base})]
    out, *_ = outcomes(build, [row("tank", 4, {"NECK": "Stamina Charm"})], records=records)
    assert out[("tank", 4)]["K11"].detail["sta"] == naked + buff + 40 + max(4, 40 * 4 // 10)  # +4: base + max(4, base * 4 // 10)
    assert out[("tank", 4)]["K11"].value == knee - out[("tank", 4)]["K11"].detail["sta"]


# ---- K4 and the scoreboard ---------------------------------------------------------------------------------------------------------


def _board(results, context):
    board = Scoreboard(context)
    for kit in results.all_kits():
        board.add(kit)
    return board


def test_k4_counts_the_kits_that_wear_two_pieces_of_a_set_or_more(build):
    rows = [
        row("balanced", 4, {"CHEST": "Vlorn Tunic", "HEAD": "Vlorn Helm"}),  # two of Vlorn
        row("tank", 4, {"HEAD": "Vlorn Helm", "ANY1": "Vlorn Helm"}),  # one piece worn twice: not two pieces
        row("melee", 4, {"HEAD": "Zarn Helm", "FEET": "Zarn Boots", "HANDS": "Vlorn Gloves"}),  # two of Zarn
        row("caster", 4, {"HEAD": "Vlorn Helm", "FEET": "Vlorn Boots", "CHEST": "Zarn Tunic", "HANDS": "Zarn Gloves"}),  # both
    ]
    results, context = build({TRIO: rows})
    top = _board(results, context).top_stems()
    assert [(t["stem"], t["kits"], t["share"]) for t in top] == [("vlorn", 2, 0.5), ("zarn", 2, 0.5)]
    assert top[0]["by_role"] == {"balanced": 1.0, "tank": 0.0, "melee": 0.0, "caster": 1.0}
    assert top[1]["by_role"] == {"balanced": 0.0, "tank": 0.0, "melee": 1.0, "caster": 1.0}
    assert set(top[0]["pieces"]) <= {"Vlorn Tunic", "Vlorn Helm", "Vlorn Boots"}


def test_k4_lists_ten_sets_at_most_the_most_worn_first(build):
    sets = ["Vlorn", "Quibbit", "Zarn", "Mepp", "Tolk", "Brux", "Silvane", "Oomph", "Plainth", "Gruel", "Fistwrap", "Palmguard"]
    first = [row("balanced", tier, {"HEAD": f"{name} Helm", "FEET": f"{name} Boots"}) for tier, name in enumerate(sets[:6])]
    second = [row("balanced", tier, {"HEAD": f"{name} Helm", "FEET": f"{name} Boots"}) for tier, name in enumerate(sets[6:])]
    second += [row("tank", 0, {"HEAD": "Gruel Helm", "FEET": "Gruel Boots"}), row("tank", 1, {"HEAD": "Gruel Helm", "FEET": "Gruel Boots"})]
    results, context = build({TRIO: first, "war-clr-pal": second})
    top = _board(results, context).top_stems()
    assert len(top) == 10 and top[0]["stem"] == "gruel" and top[0]["kits"] == 3
    assert [t["stem"] for t in top[1:]] == sorted(t["stem"] for t in top[1:])  # the others tie on one kit each, by name


def test_the_scoreboard_counts_pass_fail_and_na_by_role_and_tier(build):
    rows = [
        row("tank", 4, {"RANGE": "Dimble Charm", "EAR1": "Moonstud"}),  # K2 fail, K1.pool 0.5
        row("tank", 4, {"WAIST": "Brawn Belt"}, setup="dw", value=1.0),  # lower value than the first row of the same view: not the kit
        row("tank", 10, {"WAIST": "Brawn Belt"}),  # K2 pass, K1.pool 0
        row("melee", 4, {"WAIST": "Brawn Belt"}),
        row("caster", 4, {"FACE": "Glimmer Idol"}),
    ]
    results, context = build({TRIO: rows})
    board = _board(results, context)
    assert board.kits == 4 and board.roles == ["tank", "melee", "caster"] and board.tiers() == [4, 10]
    first = board.row("K2", "tank", [4])
    assert (first["kits"], first["pass"], first["fail"], first["na"]) == (1, 0, 1, 0)
    assert (board.row("K2", "tank", [10])["pass"], board.row("K2", "tank", [4, 10])["kits"]) == (1, 2)
    assert (board.row("K2", "caster", [4])["pass"], board.row("K2", "caster", [4])["na"]) == (0, 1)
    assert board.row("K2", "melee", [4])["pass"] == 1
    pool = board.row("K1.pool", "tank", [4])
    assert (pool["kits"], pool["info"], pool["pass"], pool["fail"]) == (1, 1, 0, 0) and pool["distribution"]["median"] == 0.5
    assert board.row("K1.pool", "caster", [4])["na"] == 1
    assert board.row("K7", "tank", [4])["info"] == 1 and board.row("K7", "tank", [4])["pass"] == 0


def test_the_worst_trios_are_listed_once_each_the_worst_first(build):
    trios = {
        "pal-mnk-enc": [row("tank", 0, {"RANGE": "Dimble Charm", "EAR1": "Moonstud"}), row("tank", 4, {"RANGE": "Dimble Charm", "HANDS": "Bruiser Mitts"})],  # 0.5, and 0.3 at +4
        "war-clr-pal": [row("tank", 0, {"FACE": "Glimmer Idol", "WAIST": "Brawn Belt"})],  # WIS 10 of WIS 10 + CHA 5 + STR 20 + AC 2 (their mana is WIS: INT is no use): 0.27
        "war-shd-ber": [row("melee", 0, {"FACE": "Glimmer Idol"})],  # INT 10 of INT 10 + CHA 5 (a Shadow Knight's mana is INT): 0.667
        "war-mnk-rog": [row("tank", 0, {"WAIST": "Brawn Belt"})],  # no mana pool: 0
    }
    results, context = build(trios)
    worst = _board(results, context).worst_trios("K1.pool")
    assert worst == [
        {"trio": "war-shd-ber", "role": "melee", "tier": 0, "value": 0.667},
        {"trio": "pal-mnk-enc", "role": "tank", "tier": 0, "value": 0.5},  # a trio once, with its worst kit
        {"trio": "war-clr-pal", "role": "tank", "tier": 0, "value": 0.27},
        {"trio": "war-mnk-rog", "role": "tank", "tier": 0, "value": 0},  # a scoreboard lists every kit: there is no threshold to pass
    ]


def test_the_worst_list_holds_at_most_ten_trios(build):
    others = ("pal", "rng", "shd", "dru", "mnk", "brd", "rog", "shm", "nec", "wiz", "mag", "enc")
    trios = {f"war-clr-{other}": [row("tank", 0, {"FACE": "Glimmer Idol", "EAR1": "Moonstud"})] for other in others}  # WIS 10 of 20 in each: a Cleric's mana is WIS
    results, context = build(trios)
    assert len(_board(results, context).worst_trios("K1.pool")) == 10


def test_a_failure_that_has_no_order_has_no_worst_trio(build):
    results, context = build({"rng-mnk-enc": [row("melee", 0, {"RANGE": "Dimble Charm"})], "pal-mnk-enc": [row("tank", 0, {"CHEST": "Ombrel Vestment"})]})
    board = _board(results, context)
    assert board.worst_trios("K5.bow") == [] and board.worst_trios("K3.robe") == []


def test_the_gates_count_the_kits_that_fail_them(build):
    trios = {
        TRIO: [
            row("tank", 0, {"FACE": "Glimmer Idol"}),  # K2
            row("tank", 4, {"CHEST": "Ombrel Vestment"}),  # robe
            row("melee", 4, {"WAIST": "Brawn Belt"}),  # neither
        ]
    }
    results, context = build(trios)
    assert _board(results, context).gates() == {"K2": 1, "K3.robe": 1}


def test_the_robe_cases_and_the_offending_items_are_kept_by_name(build):
    results, context = build({TRIO: [row("tank", 0, {"CHEST": "Ombrel Vestment", "FACE": "Glimmer Idol"}), row("melee", 4, {"NECK": "Tidepool Sigil"})]})
    document = _board(results, context).document()
    assert document["checks"]["K3.robe"]["cases"] == [{"trio": TRIO, "tier": 0, "item": "Ombrel Vestment"}]
    assert document["checks"]["K3.robe"]["items"] == [{"item": "Ombrel Vestment", "kits": 1}]
    assert document["checks"]["K2"]["offenders"] == [{"item": "Glimmer Idol", "kits": 1}, {"item": "Tidepool Sigil", "kits": 1}]
    assert document["checks"]["K2"]["distinct_items"] == 2


def test_the_document_is_json_and_the_same_for_the_same_folder(build, tmp_path):
    rows = [row("tank", 0, {"FACE": "Glimmer Idol", "CHEST": "Ombrel Vestment"}), row("melee", 4, {"WAIST": "Brawn Belt"}), row("balanced", 10, {})]
    results, context = build({TRIO: rows, "rng-war-rog": [row("melee", 4, {"RANGE": "Fenwick Longbow"})]})
    first = json.dumps(_board(results, context).document())
    second = json.dumps(_board(results, context).document())
    assert first == second
    document = json.loads(first)
    assert document["kits"] == 4 and document["trios"] == 2 and document["thresholds"] == {"K3_min_ratio": 0.5, "K11_band": 2}
    assert document["armour"] == {"heavy": sorted(PLATE), "cloth": ["ENC", "MAG", "NEC", "WIZ"]}
    assert set(document["checks"]) == {check.id for check in CHECKS}
    assert document["checks"]["K2"]["gate"] is True and document["checks"]["K1.pool"]["gate"] is False
    assert document["checks"]["K1.pool"]["scoreboard_only"] is True and document["checks"]["K2"]["scoreboard_only"] is False
    assert str(tmp_path) not in first  # no path of the computer


def test_the_documented_thresholds_are_those_of_the_decisions_file():
    text = (Path(__file__).resolve().parents[2] / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    assert f"K3 {K3_MIN_RATIO}" in text, "DECISIONS.md must say the threshold of the kit checks"
    assert "K1 0.25" not in text, "K1 is a scoreboard now: it has no threshold"


def test_the_checks_import_the_model_and_the_rules_but_not_the_solver():
    """The solver is changed on other branches; a check that only reads results must not depend on it."""
    code = (
        "import sys, trioforge.checks.kits, trioforge.checks.named, trioforge.checks.expected, trioforge.checks.exchange;"
        "print(sorted(m for m in sys.modules if m.startswith(('trioforge.solver', 'trioforge.precompute', 'trioforge.site', 'highspy'))))"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False, env={**os.environ, "PYTHONPATH": str(PIPELINE)})
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"
