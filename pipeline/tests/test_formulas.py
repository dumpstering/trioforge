"""Tests for the independent exact-formula evaluator: ``trioforge.model.formulas``.

The evaluator is the oracle for every exactness test of the solver, so it is checked three ways:

* against **goldens** (``fixtures/goldens/formulas-*.json``): numbers a separate reference produced for invented
  characters: un-floored pools, the floored game window, sheet armor class, the Monk worn-weight bonus;
* against **hand-worked numbers** written out below (every one is plain arithmetic on small inputs);
* against **properties**: more of a good stat never lowers the total value, the game window is the exact value
  with floors, and the constants it uses are the constants of ``rules/rules.json``.

Everything is exact (``fractions.Fraction``). Every name, race and item here is invented or a public game term.
"""

import dataclasses
import json
import types
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from trioforge.data import races as races_module
from trioforge.model import formulas
from trioforge.model import weapons as weapons_module
from trioforge.model.formulas import (
    Breakdown,
    EvalProfile,
    PoolSpec,
    compile_profile,
    conv_end,
    conv_mana,
    counted_pools,
    effective_sta,
    end_total,
    evaluate,
    hp_total,
    mana_total,
    monk_bonus,
    monk_curve,
    naked,
    pools_for,
    sheet_ac,
    sheet_ac_parts,
    stat_window,
    weapon_index,
)
from trioforge.model.items import SLOT_INSTANCES, ItemVec, WeaponVec
from trioforge.model.tables import load

F = Fraction
REPO = Path(__file__).resolve().parents[2]
GOLDENS = REPO / "fixtures" / "goldens"
TABLES = load()
CLASS_CODES = "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER".split()
SCHOOLS = "FIRE COLD MAGIC POISON DISEASE".split()


def golden(name):
    return json.loads((GOLDENS / f"formulas-{name}.json").read_text(encoding="utf-8"))


POOL_FILE, WINDOW_FILE, SHEET_FILE, MONK_FILE = (golden(n) for n in ("pools", "stat-window", "sheet-ac", "monk"))


# ---- small builders ------------------------------------------------------------------------


def vec(key="i1", stats=None, sv=None, haste=0, weight10=1, weapon=None, shield=False, slots=("ANY",), lore=False):
    """An ItemVec with invented contents; tier 0."""
    return ItemVec(
        key=key, name=key, slots=frozenset(slots), classes=frozenset(CLASS_CODES), deity=None, lore=lore,
        stats=dict(stats or {}), sv=dict(sv or {}), haste=haste, weight10=weight10, weapon=weapon, is_shield=shield,
        tier=0,
    )


def kit_of(*placed):
    """A kit list from ``(slot group, item)`` pairs; a paired group fills its first free place."""
    kit = [None] * len(SLOT_INSTANCES)
    for slot, item in placed:
        index = next(i for i, name in enumerate(SLOT_INSTANCES) if name == slot and kit[i] is None)
        kit[index] = item
    return kit


def stats(**given):
    """Attribute totals, 0 unless given."""
    return {"STR": 0, "STA": 0, "AGI": 0, "DEX": 0, "WIS": 0, "INT": 0, **given}


NAKED_100 = {k: 100 for k in "STR STA AGI DEX WIS INT CHA".split()}
# Three HP, two mana and three END pools, written out: a warrior-, cleric- and enchanter-like trio at level 50.
POOLS = {
    "HP": (PoolSpec("WAR", 1500, 5.0), PoolSpec("CLR", 1320, 4.4), PoolSpec("ENC", 1200, 4.0)),
    "MANA": (PoolSpec("CLR", 900, 4.5, "WIS"), PoolSpec("ENC", 900, 4.5, "INT")),
    "END": (PoolSpec("WAR", 900, 4.5), PoolSpec("CLR", 456, 3.25), PoolSpec("ENC", 260, 1.25)),
}


def profile(**changes):
    """An EvalProfile whose every weight is zero unless ``weights`` says otherwise."""
    base = dict(level=50, naked=NAKED_100, weights={}, pools=POOLS)
    base.update(changes)
    return EvalProfile(**base)


def value(weights, kit=None, buffs=None, **changes):
    """The Breakdown of an empty kit (or ``kit``) under ``weights``."""
    return evaluate(profile(weights=weights, **changes), kit if kit is not None else kit_of(), buffs)


# ---- the goldens exist and say what the plan names -----------------------------------------


def test_the_goldens_cover_what_the_plan_names():
    names = {c["name"] for c in POOL_FILE["cases"]}
    # (a) a Human WAR/MNK/ROG at level 50, naked
    assert "hum-war-mnk-rog-naked" in names
    # (b) gear that moves the END average from 95 to 140 in steps of 5
    series = [c for c in POOL_FILE["cases"] if c["name"].startswith("hum-war-mnk-rog-end-average")]
    averages = {F(c["expected"]["end_average"]) for c in series}
    assert set(range(95, 145, 5)) <= averages
    assert {F(399, 4), F(401, 4), F(201)} <= averages  # beside the knees at 100 and 201
    # (c) an Erudite CLR/WIZ/ENC: WIS 150 against INT 120, then INT 210
    assert {"eru-clr-wiz-enc-wis-150-int-120", "eru-clr-wiz-enc-wis-150-int-210"} <= names
    # (d) the sheet AC with and without a 30-AC shield at worn AC 100, 200 and 300
    covered = {(c["worn_ac"], c["shield_ac"]) for c in SHEET_FILE["cases"]}
    assert covered >= {(worn, shield) for worn in (100, 200, 300) for shield in (0, 30)}
    # (e) the Monk bonus at 15/20/25/30/32/34/36/40 stones under both curves
    assert MONK_FILE["headline"]["stones"] == [15, 20, 25, 30, 32, 34, 36, 40]
    assert MONK_FILE["headline"]["stand_in"] == [73, 58, 34, 9, 0, 0, 0, -10]
    assert MONK_FILE["headline"]["full_until_34"] == [73, 73, 73, 73, 73, 73, 0, -10]


def test_the_goldens_name_nobody():
    # Race and class codes, trios and numbers only: no character, no player.
    names = ("pools", "stat-window", "sheet-ac", "monk")
    text = " ".join((GOLDENS / f"formulas-{n}.json").read_text(encoding="utf-8") for n in names)
    for case in POOL_FILE["cases"] + WINDOW_FILE["cases"]:
        assert case["race"] in races_module.RACE_CODES and set(case["trio"]) <= set(CLASS_CODES)
    assert "\\" not in text and ":/" not in text  # no file path


# ---- naked stats ---------------------------------------------------------------------------


def test_naked_ogre_shd_clr_shm():
    want = {"STR": 145, "STA": 152, "AGI": 70, "DEX": 70, "WIS": 97, "INT": 70, "CHA": 47}
    assert naked("OGR", ("SHD", "CLR", "SHM"), TABLES) == want


def test_naked_is_race_base_plus_three_class_mods_and_is_not_capped():
    got = naked("HUM", ("WAR", "MNK", "ROG"), TABLES)
    assert got == {"STR": 90, "STA": 95, "AGI": 105, "DEX": 100, "WIS": 75, "INT": 75, "CHA": 75}
    assert naked("OGR", ("WAR", "BER", "SHD"), TABLES)["STR"] == 130 + 10 + 15 + 10 > 150  # no 150 naked cap


def test_naked_agrees_with_the_race_module_for_every_race_and_trio():
    from itertools import combinations

    for race in races_module.RACE_CODES:
        for trio in combinations(CLASS_CODES, 3):
            assert naked(race, trio, TABLES) == races_module.naked_stats(race, trio, TABLES.races)


@pytest.mark.parametrize(
    "args",
    [
        ("XXX", ("WAR", "MNK", "ROG")), ("HUM", ("WAR", "MNK")), ("HUM", ("WAR", "WAR", "ROG")),
        ("HUM", ("WAR", "MNK", "XXX")),
    ],
)
def test_naked_refuses_what_is_not_a_race_and_a_trio(args):
    with pytest.raises(ValueError):
        naked(*args, TABLES)


# ---- the conversion curves: exact breakpoints ----------------------------------------------


@pytest.mark.parametrize(
    "sta, expected",
    [(-5, 0), (0, 0), (100, 100), (254, 254), (255, 255), (256, F(511, 2)), (257, 256), (258, F(513, 2)), (510, F(765, 2)),
     (511, F(765, 2)), (700, F(765, 2))],
)
def test_sta_counts_fully_to_255_then_half_a_point_to_510_then_nothing(sta, expected):
    assert effective_sta(sta) == expected


@pytest.mark.parametrize(
    "avg, expected",
    [
        (-3, 0), (0, 0), (99, 99), (100, 100), (F(401, 4), F(805, 8)), (101, F(205, 2)), (F(407, 4), F(835, 8)),
        (200, F(705, 2) - F(5, 2)), (201, F(705, 2)), (202, F(1415, 4)), (F(805, 4), F(705, 2) + F(5, 16)),
        (510, F(705, 2) + F(5, 4) * 309),
    ],
)
def test_the_end_average_converts_at_one_then_two_and_a_half_then_one_and_a_quarter(avg, expected):
    assert conv_end(avg) == expected


def test_conv_end_is_continuous_at_its_knees():
    for knee in (100, 201):
        assert conv_end(knee) == conv_end(F(knee) + F(1, 10 ** 9)) - F(1, 10 ** 9) * (F(5, 2) if knee == 100 else F(5, 4))


@pytest.mark.parametrize(
    "stat, expected",
    [
        (-1, 0), (0, 0), (100, 100), (150, 225), (200, 350), (255, F(1675, 4)), (256, 420), (280, 450), (510, F(1475, 2)),
        (511, F(1475, 2)), (900, F(1475, 2)),
    ],
)
def test_mana_bands_default(stat, expected):
    assert conv_mana(stat) == expected


def test_mana_bands_default_has_no_bend_at_255():
    # one slope of 1.25 from 200 to 510: the rule is settled by an in-game reading, so the 255 knee of the stats is not a break
    assert formulas.MANA_BANDS == ((100, 200, 510), (F(1), F(5, 2), F(5, 4), F(0)))
    assert conv_mana(255) - conv_mana(200) == F(5, 4) * 55 and conv_mana(300) - conv_mana(255) == F(5, 4) * 45


def test_mana_bands_given_to_conv_mana_replace_the_default():
    alternative = {"breaks": [100, 200, 510], "slopes": [1, 2.5, 0.654, 0]}  # an invented curve
    assert conv_mana(200, alternative) == 350
    assert conv_mana(300, alternative) == 350 + F("0.654") * 100
    assert conv_mana(510, alternative) == 350 + F("0.654") * 310
    assert conv_mana(511, alternative) == conv_mana(510, alternative)


# ---- pools against the goldens -------------------------------------------------------------


def ids(case):
    return case["name"]


@pytest.mark.parametrize("case", POOL_FILE["cases"], ids=ids)
def test_exact_pools_match_the_goldens(case):
    trio, level, want = case["trio"], case["level"], case["expected"]
    a, item, buff = case["attrs"], case["item"], case["buff"]
    assert hp_total(trio, level, a["STA"], item["HP"], buff["HP"], TABLES) == F(want["HP"])
    assert mana_total(trio, level, a["WIS"], a["INT"], item["MANA"], buff["MANA"], TABLES) == F(want["MANA"])
    assert end_total(trio, level, a["STR"], a["STA"], a["DEX"], a["AGI"], item["END"], buff["END"], TABLES) == F(want["END"])
    assert counted_pools(trio, level, a, TABLES) == {
        "HP": tuple(want["hp_pools"]), "MANA": tuple(want["mana_pools"]), "END": tuple(want["end_pools"]),
    }


@pytest.mark.parametrize("case", POOL_FILE["cases"], ids=ids)
def test_evaluate_aggregates_the_same_pools(case):
    trio, level, want = case["trio"], case["level"], case["expected"]
    a, item, buff = case["attrs"], case["item"], case["buff"]
    prof = EvalProfile(
        level=level, naked={**a, "CHA": 0}, weights={"HP": 1, "MANA": 1, "END": 1}, pools=pools_for(trio, level, TABLES),
        buff_totals={"HP": buff["HP"], "MANA": buff["MANA"], "END": buff["END"]},
    )
    kit = kit_of(("ANY", vec(stats={k: v for k, v in item.items() if v})))
    result = evaluate(prof, kit)
    assert result.parts["HP"] == F(want["HP"])
    assert result.parts["MANA"] == F(want["MANA"])
    assert result.parts["END"] == F(want["END"])
    assert result.F == F(want["HP"]) + F(want["MANA"]) + F(want["END"])
    counted = {"HP": tuple(want["hp_pools"]), "MANA": tuple(want["mana_pools"]), "END": tuple(want["end_pools"])}
    assert result.totals["counted"] == counted


DERIVED_FROM_NAKED = [
    c for c in POOL_FILE["cases"] if c["gear_added"] or c["name"].endswith(("naked", "level-55", "items-and-buffs"))
]


@pytest.mark.parametrize("case", DERIVED_FROM_NAKED, ids=ids)
def test_golden_attributes_are_the_naked_stats_plus_the_gear_they_name(case):
    got = naked(case["race"], case["trio"], TABLES)
    for stat in ("STR", "STA", "AGI", "DEX"):
        assert case["attrs"][stat] == got[stat] + case["gear_added"].get(stat, 0)


# ---- pools by hand -------------------------------------------------------------------------


def test_hp_of_a_naked_human_warrior_monk_rogue():
    # WAR 5 + 1500 + 5 * 95 = 1980; MNK = ROG = 5 + 1275 + 4.25 * 95 = 1683.75: the two largest are WAR and one other.
    assert hp_total(("WAR", "MNK", "ROG"), 50, 95, 0, 0, TABLES) == F(1980) + F("1683.75")
    assert hp_total(("WAR", "MNK", "ROG"), 50, 95, 120, 300, TABLES) == F(1980) + F("1683.75") + 420


def test_hp_stops_counting_sta_after_510_and_halves_it_between_255_and_510():
    base = hp_total(("WAR", "MNK", "ROG"), 50, 510, 0, 0, TABLES)
    assert hp_total(("WAR", "MNK", "ROG"), 50, 900, 0, 0, TABLES) == base
    # 255 -> 256 adds half a point of STA': (5.0 + 4.25) / 2 = 4.625 for the two pools
    def hp(sta):
        return hp_total(("WAR", "MNK", "ROG"), 50, sta, 0, 0, TABLES)

    assert hp(256) - hp(255) == F("4.625")
    assert hp(255) - hp(254) == F("9.25")


def test_hp_changes_pool_order_when_the_pools_cross():
    # Pools (5 + base + fac * STA'): A = 30 + 3 s, B = 90 + 2 s, C = 10 + s. A and B cross at s = 60; C is always last.
    rows = {("WAR", 50): (25, 3.0), ("SHD", 50): (85, 2.0), ("CLR", 50): (5, 1.0)}
    tables = dataclasses.replace(TABLES, basedata={
        key: {
            "hp": hp, "mana": 0.0, "end": 0.0, "hp_regen": 7.0, "end_regen": 13.0, "hp_fac": fac, "mana_fac": 0.0,
            "end_fac": 0.0,
        }
        for key, (hp, fac) in rows.items()
    })
    trio = ("WAR", "SHD", "CLR")
    for sta, want in ((40, 320), (59, 415), (60, 420), (61, 425), (150, 870)):
        assert hp_total(trio, 50, sta, 0, 0, tables) == want
        assert counted_pools(trio, 50, stats(STA=sta), tables)["HP"] == (
            ("SHD", "WAR") if sta < 60 else ("WAR", "SHD"))  # equal at 60: trio order


def test_mana_counts_the_two_largest_pools_when_wis_and_int_trade_places():
    trio = ("CLR", "WIZ", "ENC")
    # WIS 150 -> 100 + 50 * 2.5 = 225 -> CLR 900 + 4.5 * 225 = 1912.5; INT 120 -> 100 + 20 * 2.5 = 150 -> WIZ = ENC = 1575
    assert mana_total(trio, 50, 150, 120, 0, 0, TABLES) == F("1912.5") + 1575
    assert counted_pools(trio, 50, stats(WIS=150, INT=120), TABLES)["MANA"] == ("CLR", "WIZ")
    # INT 210 -> 100 + 250 + 1.25 * 10 = 362.5 -> WIZ = ENC = 2531.25; CLR (1912.5) drops out
    assert mana_total(trio, 50, 150, 210, 0, 0, TABLES) == F("5062.5")
    assert counted_pools(trio, 50, stats(WIS=150, INT=210), TABLES)["MANA"] == ("WIZ", "ENC")


def test_mana_with_one_mana_class_counts_that_pool_alone():
    assert mana_total(("WAR", "CLR", "ROG"), 50, 100, 500, 10, 5, TABLES) == 900 + F("4.5") * 100 + 15


def test_a_trio_without_a_mana_class_has_no_mana_whatever_the_items_give():
    assert mana_total(("WAR", "MNK", "ROG"), 50, 300, 300, 500, 500, TABLES) == 0
    assert counted_pools(("WAR", "MNK", "ROG"), 50, NAKED_100, TABLES)["MANA"] == ()


def test_mana_uses_the_band_it_is_given():
    alternative = {"breaks": [100, 200, 510], "slopes": [1, 2.5, 0.654, 0]}  # an invented curve
    assert mana_total(("WAR", "CLR", "ROG"), 50, 300, 0, 0, 0, TABLES, alternative) == F(900) + F("4.5") * (350 + F("65.4"))


def test_end_of_a_naked_human_warrior_monk_rogue():
    # A = (90 + 95 + 100 + 105) / 4 = 97.5; every pool is 900 + 4.5 * 97.5 = 1338.75; the two largest.
    assert end_total(("WAR", "MNK", "ROG"), 50, 90, 95, 100, 105, 0, 0, TABLES) == F("2677.5")


def test_end_rate_rises_across_the_knee_at_a_hundred():
    trio = ("WAR", "MNK", "ROG")
    below = end_total(trio, 50, 99, 99, 99, 99, 0, 0, TABLES)
    on = end_total(trio, 50, 100, 100, 100, 100, 0, 0, TABLES)
    above = end_total(trio, 50, 101, 101, 101, 101, 0, 0, TABLES)
    assert on - below == 2 * F("4.5") * 1  # one point of average at rate 1 in two pools
    assert above - on == 2 * F("4.5") * F("2.5")  # then 2.5
    # only the sum of the four stats counts: 404 is an average of 101 wherever the points sit
    spread_out = end_total(trio, 50, 100, 100, 100, 104, 0, 0, TABLES)
    assert spread_out == end_total(trio, 50, 104, 100, 100, 100, 0, 0, TABLES) == above


def test_end_counts_each_stat_to_510_and_no_further():
    trio = ("WAR", "MNK", "ROG")
    assert end_total(trio, 50, 510, 100, 100, 100, 0, 0, TABLES) == end_total(trio, 50, 900, 100, 100, 100, 0, 0, TABLES)
    assert end_total(trio, 50, 510, 510, 510, 510, 0, 0, TABLES) == 2 * (900 + F("4.5") * conv_end(510))


def test_end_best_two_pools_switch_for_a_berserker_with_a_monk_and_a_rogue():
    trio = ("BER", "MNK", "ROG")
    low = end_total(trio, 50, 222, 222, 222, 222, 0, 0, TABLES)  # BER 995 + 4.25 c above MNK 900 + 4.5 c until c = 380
    assert low == (995 + F("4.25") * conv_end(222)) + (900 + F("4.5") * conv_end(222))
    high = end_total(trio, 50, 224, 224, 224, 224, 0, 0, TABLES)
    assert high == 2 * (900 + F("4.5") * conv_end(224))
    assert counted_pools(trio, 50, stats(STR=224, STA=224, AGI=224, DEX=224), TABLES)["END"] == ("MNK", "ROG")


# ---- the floors live in stat_window only ---------------------------------------------------


def window(trio, attrs, item=None, buff=None, level=50, bands=None):
    full = {"STR": 0, "STA": 0, "AGI": 0, "DEX": 0, "WIS": 0, "INT": 0, **attrs}
    return stat_window(trio, level, full, item or {}, buff or {}, TABLES, bands)


def test_sta_258_gives_a_fraction_of_hp_in_the_oracle_and_a_whole_number_in_the_window():
    trio = ("WAR", "MNK", "ROG")
    # STA' = 255 + 3 / 2 = 256.5: WAR 5 + 1500 + 5 * 256.5, MNK 5 + 1275 + 4.25 * 256.5
    assert hp_total(trio, 50, 258, 0, 0, TABLES) == F("2787.5") + F("2370.125") == F(41261, 8)
    # the window floors STA' to 256 first: WAR 5 + 1500 + 5 * 256 = 2785, MNK 5 + 1275 + floor(4.25 * 256 = 1088) = 2368
    got = window(trio, {"STA": 258, "STR": 90, "AGI": 105, "DEX": 100})
    assert got["HP"] == 5153 and isinstance(got["HP"], int)


def test_an_end_average_of_101_75_gives_a_fraction_in_the_oracle_and_whole_numbers_in_the_window():
    trio = ("WAR", "MNK", "ROG")
    # A = (100 + 100 + 103 + 104) / 4 = 101.75, converted 100 + 2.5 * 1.75 = 104.375; two pools of 900 + 4.5 * 104.375
    assert end_total(trio, 50, 100, 100, 103, 104, 0, 0, TABLES) == F("2739.375")
    # the window floors the conversion to 104, then 4.5 * 104 = 468: two pools of 1368
    got = window(trio, {"STR": 100, "STA": 100, "DEX": 103, "AGI": 104})
    assert got["END"] == 2736 and isinstance(got["END"], int)


def test_the_window_floors_the_converted_wis_and_each_pool_product():
    # WIS 255 -> 418.75 -> 418; CLR 900 + floor(4.5 * 418 = 1881)
    got = window(("WAR", "CLR", "ROG"), {"WIS": 255})
    assert got["MANA"] == 900 + 1881
    assert mana_total(("WAR", "CLR", "ROG"), 50, 255, 0, 0, 0, TABLES) == 900 + F("4.5") * F("418.75")


def test_ten_wis_above_255_adds_the_mana_of_the_continuous_curve_in_the_stat_window():
    # The in-game reading that settled mana.wis_bands: WIS 270 -> 280, no buffs. The curve runs at 1.25 from 200 to 510, so
    # the converted value goes 437.5 -> 450, floored 437 and 450; two WIS pools of factor 4.5 give floor(4.5 * 437) = 1966
    # and 4.5 * 450 = 2025, 59 a pool and 118 for the two.
    trio = ("CLR", "SHM", "WAR")
    low, high = window(trio, {"WIS": 270}), window(trio, {"WIS": 280})
    assert list(low["mana_pools"]) == ["CLR", "SHM"] and low["mana_pool_values"]["CLR"] == 900 + 1966
    assert high["mana_pool_values"]["CLR"] == 900 + 2025
    assert high["MANA"] - low["MANA"] == 118


def test_the_window_adds_item_and_buff_points_whole_and_ignores_natural_durability():
    trio = ("WAR", "MNK", "ROG")
    plain = window(trio, {"STR": 90, "STA": 95, "AGI": 105, "DEX": 100})
    more = window(
        trio, {"STR": 90, "STA": 95, "AGI": 105, "DEX": 100}, item={"HP": 100, "END": 10}, buff={"HP": 7, "END": 3}
    )
    assert more["HP"] - plain["HP"] == 107 and more["END"] - plain["END"] == 13


@settings(max_examples=150, deadline=None)
@given(
    sta=st.integers(-20, 700), wis=st.integers(-20, 700), int_=st.integers(-20, 700), s=st.integers(-20, 700),
    dex=st.integers(-20, 700), agi=st.integers(-20, 700),
    trio=st.sampled_from(
        [("WAR", "MNK", "ROG"), ("CLR", "WIZ", "ENC"), ("PAL", "SHD", "BRD"), ("BER", "MNK", "ROG"), ("WAR", "CLR", "ROG")]
    ),
)
def test_the_window_is_the_exact_value_with_floors_never_above_it(sta, wis, int_, s, dex, agi, trio):
    attrs = {"STR": s, "STA": sta, "AGI": agi, "DEX": dex, "WIS": wis, "INT": int_}
    got = stat_window(trio, 50, attrs, {}, {}, TABLES)
    exact = {
        "HP": hp_total(trio, 50, sta, 0, 0, TABLES),
        "MANA": mana_total(trio, 50, wis, int_, 0, 0, TABLES),
        "END": end_total(trio, 50, s, sta, dex, agi, 0, 0, TABLES),
    }
    for key in ("HP", "MANA", "END"):
        gap = exact[key] - got[key]
        assert 0 <= gap < 14, (key, exact[key], got[key])


@pytest.mark.parametrize("case", WINDOW_FILE["cases"], ids=ids)
def test_the_window_matches_the_goldens(case):
    got = stat_window(case["trio"], case["level"], case["attrs"], case["item"], case["buff"], TABLES)
    want = case["expected"]
    assert [got[k] for k in ("HP", "MANA", "END")] == [want[k] for k in ("HP", "MANA", "END")]
    for family in ("hp", "mana", "end"):
        assert list(got[f"{family}_pools"]) == want[f"{family}_pools"]
        assert dict(got[f"{family}_pool_values"]) == want[f"{family}_pool_values"]
    assert all(type(got[k]) is int for k in ("HP", "MANA", "END"))


# ---- sheet armor class ---------------------------------------------------------------------

SHEET_ARGS = ("worn_ac", "shield_ac", "defense_cap", "spell_ac", "agi_total", "softcap", "past_cap_rate", "cs_pct", "pe_pct")


def sheet_id(case):
    return f"worn{case['worn_ac']}-shield{case['shield_ac']}-spell{case['spell_ac']}-agi{case['agi_total']}"


@pytest.mark.parametrize("case", SHEET_FILE["cases"], ids=sheet_id)
def test_sheet_ac_matches_the_goldens(case):
    args = {k: case[k] for k in SHEET_ARGS}
    want = case["expected"]
    assert sheet_ac(**args) == F(want["sheet"])
    parts = sheet_ac_parts(**args)
    assert (parts.x, parts.y, parts.sheet) == (F(want["X"]), F(want["Y"]), F(want["sheet"]))


def test_sheet_ac_below_the_cap_is_x():
    # X = 4/3 * 100 + 230/3 + 40/4 + 80/20 = 133.33.. + 76.66.. + 10 + 4 = 224; Y = 439
    got = sheet_ac_parts(100, 0, 230, 40, 80, 392, 0.33, 10, 2)
    assert (got.x, got.y, got.sheet) == (224, 439, 224)


def test_sheet_ac_past_the_cap_keeps_a_third_of_the_surplus():
    # worn 300: X = 400 + 230/3 + 4 = 1442/3; Y = 439; sheet = 439 + 0.33 * (X - 439)
    got = sheet_ac_parts(300, 0, 230, 0, 80, 392, 0.33, 10, 2)
    assert got.x == F(1442, 3)
    assert got.sheet == 439 + F(33, 100) * (F(1442, 3) - 439)


def test_the_shield_adds_to_x_at_four_thirds_and_to_y_whole():
    plain = sheet_ac_parts(300, 0, 230, 0, 80, 392, 0.33, 10, 2)
    shielded = sheet_ac_parts(300, 30, 230, 0, 80, 392, 0.33, 10, 2)
    assert shielded.x - plain.x == 40 and shielded.y - plain.y == 30


def test_the_softcap_is_floored_after_the_aa_percentages():
    assert sheet_ac_parts(0, 0, 0, 0, 0, 392, 0.33, 10, 2).y == 439  # 439.04
    assert sheet_ac_parts(0, 0, 0, 0, 0, 100, 0.33, 3, 2).y == 105  # 105 exactly
    assert sheet_ac_parts(0, 0, 0, 0, 0, 10, 0.33, 5, 2).y == 10  # 10.7
    assert sheet_ac_parts(0, 0, 0, 0, 0, 333, 0.33, 0, 0).y == 333
    assert sheet_ac_parts(0, 0, 0, 0, 0, 392, 0.33, 0, 0).y == 392


def test_a_rate_of_zero_stops_at_the_cap_and_a_rate_of_one_never_does():
    assert sheet_ac(500, 0, 0, 0, 0, 392, 0, 0, 0) == 392
    assert sheet_ac(500, 0, 0, 0, 0, 392, 1, 0, 0) == F(2000, 3)


def test_a_bonus_placed_inside_x_is_capped_with_it():
    plain = sheet_ac_parts(270, 0, 0, 0, 100, 400, 0.5, 0, 0)  # X = 360 + 5 = 365 under Y = 400
    inside = sheet_ac_parts(270, 0, 0, 0, 100, 400, 0.5, 0, 0, inside=58)
    assert (plain.x, plain.sheet) == (365, 365)
    assert (inside.x, inside.sheet) == (423, 400 + F(1, 2) * 23)


def test_the_sheet_never_lies_below_either_bound_it_is_taken_from():
    for worn in range(0, 700, 37):
        parts = sheet_ac_parts(worn, 0, 230, 0, 80, 392, 0.33, 10, 2)
        assert parts.sheet <= parts.x
        assert parts.sheet == min(parts.x, F(33, 100) * parts.x + F(67, 100) * parts.y)


# ---- the Monk worn-weight bonus ------------------------------------------------------------


def curve_from_golden(level, kind):
    entry = MONK_FILE["levels"][str(level)]
    curve = {
        "softcap_stones": entry["softcap_stones"], "hardcap_stones": entry["hardcap_stones"],
        "full_bonus_ac": entry["full_bonus"],
    }
    return curve if kind == "stand_in" else {**curve, "full_until_stones": 34}


@pytest.mark.parametrize("level", [50, 55])
@pytest.mark.parametrize("kind", ["stand_in", "full_until_34"])
def test_monk_bonus_matches_the_reference_at_every_whole_stone(level, kind):
    entry = MONK_FILE["levels"][str(level)]
    curve = curve_from_golden(level, kind)
    assert entry["stones"] == list(range(46))
    for stones, want in zip(entry["stones"], entry[kind]):
        assert monk_bonus(level, 10 * stones, curve) == want, (level, kind, stones)
        assert type(monk_bonus(level, 10 * stones, curve)) is int


@pytest.mark.parametrize("level", [50, 55])
def test_monk_bonus_counts_whole_stones_only(level):
    entry = MONK_FILE["levels"][str(level)]
    for tenths, want in entry["tenths"].items():
        for kind in ("stand_in", "full_until_34"):
            assert monk_bonus(level, int(tenths), curve_from_golden(level, kind)) == want[kind], (tenths, kind)


def test_monk_headline_values_of_the_plan():
    stand_in, alternative = curve_from_golden(50, "stand_in"), curve_from_golden(50, "full_until_34")
    stones = (15, 20, 25, 30, 32, 34, 36, 40)
    assert [monk_bonus(50, 10 * s, stand_in) for s in stones] == [73, 58, 34, 9, 0, 0, 0, -10]
    assert [monk_bonus(50, 10 * s, alternative) for s in stones] == [73, 73, 73, 73, 73, 73, 0, -10]


def test_a_kit_at_32_stones_has_no_bonus_and_at_31_9_stones_has_four():
    stand_in = curve_from_golden(50, "stand_in")
    assert monk_bonus(50, 320, stand_in) == 0
    assert monk_bonus(50, 319, stand_in) == 4  # 31 whole stones
    assert monk_bonus(50, 319, curve_from_golden(50, "full_until_34")) == 73


def test_the_monk_curve_comes_from_the_rules_for_each_level():
    assert monk_curve(TABLES.rules, 50) == {"softcap_stones": 17, "hardcap_stones": 36, "full_bonus_ac": 73}
    assert monk_curve(TABLES.rules, 55) == {"softcap_stones": 20, "hardcap_stones": 40, "full_bonus_ac": 80}
    assert monk_curve(TABLES.rules, 50, full_until=34) == {**monk_curve(TABLES.rules, 50), "full_until_stones": 34}
    for level in (50, 55):
        assert monk_bonus(level, 0, monk_curve(TABLES.rules, level)) == monk_curve(TABLES.rules, level)["full_bonus_ac"]


def test_a_monk_curve_whose_full_bonus_disagrees_with_the_level_is_refused():
    with pytest.raises(ValueError, match="full_bonus_ac"):
        monk_bonus(50, 100, {"softcap_stones": 17, "hardcap_stones": 36, "full_bonus_ac": 74})
    with pytest.raises(ValueError, match="curve"):
        monk_bonus(50, 100, None)


def test_a_monk_curve_of_another_shape_is_refused():
    linear = {"softcap_stones": 1, "hardcap_stones": 2, "full_bonus_ac": 73, "shape": "linear"}
    rules = types.SimpleNamespace(get=lambda rule, level=50: linear)
    with pytest.raises(ValueError, match="shape"):
        monk_curve(rules, 50)


# ---- the weapon index ----------------------------------------------------------------------


def test_weapon_index_of_a_one_hander_without_a_listed_bonus():
    sword = WeaponVec("1H Slashing", 20, 30, None, False)
    # bonus 0.5 * delay = 15; (20 + 15) / 30 = 7/6; haste 50% -> * 3/2
    assert weapon_index(sword, "PRIMARY", "1h-shield", 50, 1) == F(7, 4)
    assert weapon_index(sword, "PRIMARY", "1h-shield", 0, 1) == F(7, 6)


def test_weapon_index_of_a_two_hander_uses_6875_ten_thousandths_of_the_delay_up_to_50_at_level_50():
    """T9: the client's formula at level 50 for a weapon whose damage is at most the level (it was 0.67)."""
    axe = WeaponVec("2H Slashing", 40, 60, None, True)
    assert weapon_index(axe, "PRIMARY", "2h", 0, 1) == (40 + F(6875, 10000) * 50) / 60  # the delay counts at most 50
    short = WeaponVec("2H Slashing", 40, 40, None, True)
    assert weapon_index(short, "PRIMARY", "2h", 0, 1) == (40 + F(6875, 10000) * 40) / 40


def test_a_listed_bonus_replaces_the_pattern_and_a_listed_zero_is_not_listed():
    assert weapon_index(WeaponVec("1H Blunt", 10, 20, 5, False), "PRIMARY", "1h-shield", 0, 1) == F(15, 20)
    assert weapon_index(WeaponVec("1H Blunt", 10, 20, 0, False), "PRIMARY", "1h-shield", 0, 1) == F(20, 20)


def test_the_off_hand_gets_no_damage_bonus_and_the_dual_wield_factor():
    dagger = WeaponVec("Piercing", 10, 20, 5, False)
    half = F(1, 2)
    assert weapon_index(dagger, "PRIMARY", "dw", 50, half) == F(15, 20) * F(3, 2)  # the bonus belongs to the primary hand
    assert weapon_index(dagger, "SECONDARY", "dw", 50, half) == F(10, 20) * F(3, 2) * half  # 10 / 20: no bonus
    assert weapon_index(WeaponVec("1H Slashing", 20, 30, None, False), "SECONDARY", "dw", 0, 1) == F(20, 30)


def test_the_stick_setup_and_no_setup_score_no_weapon_damage():
    sword = WeaponVec("1H Slashing", 20, 30, None, False)
    axe = WeaponVec("2H Slashing", 40, 60, None, True)
    for setup in ("stick", None):
        for hand in ("PRIMARY", "SECONDARY"):
            assert weapon_index(sword, hand, setup, 50, 1) == 0 and weapon_index(axe, hand, setup, 50, 1) == 0


def test_a_hand_the_setup_does_not_allow_scores_nothing():
    sword = WeaponVec("1H Slashing", 20, 30, None, False)
    axe = WeaponVec("2H Slashing", 40, 60, None, True)
    # 2h: only a two-hander in the primary hand
    assert weapon_index(sword, "PRIMARY", "2h", 0, 1) == 0
    assert weapon_index(axe, "SECONDARY", "2h", 0, 1) == 0 and weapon_index(sword, "SECONDARY", "2h", 0, 1) == 0
    # dw: one-handers in both hands, never a two-hander
    assert weapon_index(axe, "PRIMARY", "dw", 0, 1) == 0 and weapon_index(axe, "SECONDARY", "dw", 0, 1) == 0
    # 1h-shield: a one-hander in the primary hand; the secondary hand takes a shield, never a weapon
    assert weapon_index(axe, "PRIMARY", "1h-shield", 0, 1) == 0 and weapon_index(sword, "SECONDARY", "1h-shield", 0, 1) == 0
    # a weapon with no damage or no delay scores nothing anywhere
    assert weapon_index(WeaponVec("1H Slashing", 0, 30, None, False), "PRIMARY", "dw", 0, 1) == 0
    assert weapon_index(WeaponVec("1H Slashing", 20, 0, None, False), "PRIMARY", "dw", 0, 1) == 0


def test_the_weapon_index_agrees_with_the_weapons_module_for_every_hand_setup_and_weapon():
    # The single definition is trioforge.model.weapons'; the evaluator writes it out again and must agree.
    weapons_list = [
        WeaponVec("1H Slashing", 20, 30, None, False), WeaponVec("1H Blunt", 10, 20, 5, False),
        WeaponVec("Piercing", 12, 25, 0, False), WeaponVec("2H Slashing", 40, 60, None, True),
        WeaponVec("2H Blunt", 33, 45, 22, True), WeaponVec("1H Blunt", 0, 20, None, False),
        WeaponVec("1H Blunt", 9, 0, None, False),
    ]
    for weapon in weapons_list:
        item = vec(key="w", weapon=weapon, slots=("PRIMARY", "SECONDARY"))
        for setup in ("1h-shield", "2h", "dw", "stick"):
            for hand in ("PRIMARY", "SECONDARY"):
                for haste in (0, 37, 85):
                    for factor in (F(4, 5), F(1, 2), 1):
                        want = weapons_module.damage_index_exact(item, hand.lower(), setup, haste, dw_factor=factor)
                        assert weapon_index(weapon, hand, setup, haste, factor) == want, (weapon, hand, setup)


# ---- evaluate: one term at a time ----------------------------------------------------------


def test_an_empty_kit_with_no_weights_is_worth_nothing():
    result = value({})
    assert isinstance(result, Breakdown) and result.F == 0
    assert all(v == 0 for v in result.parts.values())


def test_hp_part():
    # STA 100: WAR 5 + 1500 + 500 = 2005, CLR 5 + 1320 + 440 = 1765, ENC 1605: the two largest = 3770
    assert value({"HP": 2}).F == 2 * 3770
    result = value({"HP": 2}, kit_of(("HEAD", vec(stats={"HP": 30}))), buffs={"HP": 100})
    assert result.parts["HP"] == 2 * (3770 + 30 + 100)
    assert result.totals["pools"]["HP"] == 3900 and result.totals["counted"]["HP"] == ("WAR", "CLR")


def test_hp_uses_sta_from_naked_buffs_and_items():
    result = value({"HP": 1}, kit_of(("HEAD", vec(stats={"STA": 50}))), buffs={"STA": 10})
    assert result.totals["attributes"]["STA"] == 160
    assert result.parts["HP"] == (5 + 1500 + 5 * 160) + (5 + 1320 + F("4.4") * 160)


def test_mana_part():
    assert value({"MANA": 3}).F == 3 * 2700  # WIS = INT = 100: two pools of 900 + 4.5 * 100
    result = value({"MANA": 3}, kit_of(("NECK", vec(stats={"WIS": 50})), ("HEAD", vec(stats={"INT": 120}))))
    # WIS 150 -> 225, INT 220 -> 375: CLR 1912.5, ENC 2587.5
    assert result.parts["MANA"] == 3 * 4500 and result.totals["counted"]["MANA"] == ("ENC", "CLR")  # largest pool first


def test_item_and_buff_mana_join_the_pools():
    result = value({"MANA": 1}, kit_of(("HEAD", vec(stats={"MANA": 40}))), buffs={"MANA": 60})
    assert result.parts["MANA"] == 2700 + 100


def test_a_trio_without_mana_pools_gets_nothing_for_mana():
    kit = kit_of(("HEAD", vec(stats={"MANA": 400, "WIS": 80})))
    result = value({"MANA": 5}, kit, buffs={"MANA": 99}, pools={**POOLS, "MANA": ()})
    assert result.parts["MANA"] == 0


def test_end_part():
    # all four stats 100: conv 100: WAR 900 + 450 = 1350, CLR 456 + 325 = 781, ENC 385: 2131
    assert value({"END": 1}).F == 2131
    stats = {"STR": 50, "STA": 50, "DEX": 50, "AGI": 50}
    result = value({"END": 1}, kit_of(("HEAD", vec(stats=stats))))
    # A = 150 -> 225: WAR 900 + 1012.5, CLR 456 + 731.25
    assert result.parts["END"] == F("1912.5") + F("1187.25")
    assert result.totals["end_average"] == 150


def test_end_uses_the_average_of_the_capped_stats():
    result = value({"END": 1}, kit_of(("HEAD", vec(stats={"STR": 700}))))
    assert result.totals["end_average"] == F(510 + 300, 4)


def test_atk_part_is_two_thirds_of_str_plus_item_and_buff_atk():
    result = value({"ATK": 3}, kit_of(("HEAD", vec(stats={"ATK": 10}))), buffs={"ATK": 5})
    assert result.parts["ATK"] == 3 * (F("0.666667") * 100 + 15)


def test_str_counts_to_510_for_atk_and_item_atk_has_no_cap():
    result = value({"ATK": 1}, kit_of(("HEAD", vec(stats={"STR": 600, "ATK": 7}))))
    assert result.parts["ATK"] == F("0.666667") * 510 + 7


@pytest.mark.parametrize(
    "dex, expected",
    [(100, 100), (255, 255), (256, 256), (300, 300), (510, 510), (700, 510)],
)
def test_dex_is_full_to_510_with_no_break_at_255(dex, expected):
    """T5: the client has no break at 255 for dexterity (it counted a tenth of a point a point from 255 on before)."""
    result = value({"DEX": 1}, naked={**NAKED_100, "DEX": dex})
    assert result.parts["DEX"] == expected
    assert F(str(TABLES.rules.get("stats.dex_post255_slope"))) == formulas.DEX_PAST_KNEE == 1


def test_cha_is_linear_to_510():
    assert value({"CHA": F(1, 20)}).parts["CHA"] == 5
    assert value({"CHA": F(1, 20)}, kit_of(("HEAD", vec(stats={"CHA": 450})))).parts["CHA"] == F(51, 2)


def test_agi_gives_evasion_armor_class_at_the_plain_armor_class_weight():
    result = value({"AC": 4})
    assert result.parts["EVASION"] == 4 * F("0.2222") * 100
    assert value({"AC": 4}, naked={**NAKED_100, "AGI": 900}).parts["EVASION"] == 4 * F("0.2222") * 510


def test_ac_part_is_the_sheet_at_the_weight_per_sheet_point():
    # AC weight 4 -> 4 / (4/3) = 3 per sheet point. worn 150: X = 200 + 100/20 = 205 under Y = 400
    prof = dict(softcap=(400, 0.5))
    result = value({"AC": 4}, kit_of(("CHEST", vec(stats={"AC": 150}))), **prof)
    assert result.parts["AC"] == 3 * 205
    assert result.totals["sheet"]["worn_ac"] == 150 and result.totals["sheet"]["capped"] == 205
    past = value({"AC": 4}, kit_of(("CHEST", vec(stats={"AC": 450}))), **prof)
    assert past.parts["AC"] == 3 * (400 + F(1, 2) * 205)  # X = 600 + 5 = 605


def test_combat_stability_and_physical_enhancement_raise_the_softcap_in_the_sheet():
    chest = kit_of(("CHEST", vec(stats={"AC": 450})))  # X = 600 + 5 = 605
    plain = value({"AC": 4}, chest, softcap=(392, 0.33))
    boosted = value({"AC": 4}, chest, softcap=(392, 0.33), cs_pct=10, pe_pct=2)
    assert plain.totals["sheet"]["Y"] == 392 and boosted.totals["sheet"]["Y"] == 439
    assert plain.parts["AC"] == 3 * (392 + F(33, 100) * (605 - 392))
    assert boosted.parts["AC"] == 3 * (439 + F(33, 100) * (605 - 439))


def test_defense_and_spell_armor_class_enter_x():
    prof = dict(softcap=(1000, 0.5), defense_cap=230)
    result = value({"AC": 4}, buffs={"AC": 40}, **prof)
    assert result.parts["AC"] == 3 * (F(230, 3) + 10 + 5)


def test_gear_agi_counts_in_the_sheet_to_510():
    prof = dict(softcap=(1000, 0.5))
    result = value({"AC": 4}, kit_of(("HEAD", vec(stats={"AGI": 600}))), **prof)
    assert result.parts["AC"] == 3 * F(510, 20)


def test_only_a_shield_in_the_off_hand_counts_as_a_shield():
    prof = dict(softcap=(400, F(1, 2)))
    worn = ("CHEST", vec(stats={"AC": 450}))
    shield = vec(stats={"AC": 30}, shield=True, slots=("SECONDARY",))
    off_hand = value({"AC": 4}, kit_of(worn, ("SECONDARY", shield)), **prof)
    in_any = value({"AC": 4}, kit_of(worn, ("ANY", shield)), **prof)
    # X = 4/3 * 480 + 5 = 645 in both; Y = 400 + 30 with the shield in the off hand, 400 in an Any slot
    assert off_hand.parts["AC"] == 3 * (430 + F(1, 2) * (645 - 430)) and off_hand.totals["sheet"]["shield_ac"] == 30
    assert in_any.parts["AC"] == 3 * (400 + F(1, 2) * (645 - 400)) and in_any.totals["sheet"]["shield_ac"] == 0
    assert off_hand.parts["AC"] > in_any.parts["AC"]


def test_a_non_shield_in_the_off_hand_is_worn_armor_class():
    prof = dict(softcap=(400, F(1, 2)))
    held = vec(stats={"AC": 30}, slots=("SECONDARY",))
    result = value({"AC": 4}, kit_of(("CHEST", vec(stats={"AC": 450})), ("SECONDARY", held)), **prof)
    assert result.totals["sheet"]["shield_ac"] == 0 and result.totals["sheet"]["worn_ac"] == 480


TOP = {"monk": "top", "iksar": "top"}  # (R3: the default placement is "inside" now, the client's; the tests of the "top" reading name it)


def test_monk_bonus_sits_on_top_of_the_capped_sheet():
    curve = monk_curve(TABLES.rules, 50)
    prof = dict(softcap=(400, F(1, 2)), monk=curve, placement=TOP)
    chest = vec(stats={"AC": 270}, weight10=200)  # 20 stones -> bonus 58
    result = value({"AC": 4}, kit_of(("CHEST", chest)), **prof)
    assert result.totals["sheet"]["monk_bonus"] == 58
    assert result.parts["AC"] == 3 * 365  # X = 360 + 5, under the cap
    assert result.parts["MONK"] == 3 * 58 and result.totals["sheet"]["total"] == 365 + 58
    # past the cap the bonus still counts in full
    past = value({"AC": 4}, kit_of(("CHEST", vec(stats={"AC": 450}, weight10=200))), **prof)
    assert past.parts["MONK"] == 3 * 58 and past.parts["AC"] == 3 * (400 + F(1, 2) * 205)


def test_monk_bonus_placed_inside_x_is_capped_with_the_rest():
    curve = monk_curve(TABLES.rules, 50)
    prof = dict(softcap=(400, F(1, 2)), monk=curve, placement={"monk": "inside", "iksar": "top"})
    result = value({"AC": 4}, kit_of(("CHEST", vec(stats={"AC": 270}, weight10=200))), **prof)
    assert result.parts["MONK"] == 0
    assert result.parts["AC"] == 3 * (400 + F(1, 2) * 23)  # X = 365 + 58 = 423


def test_monk_weight_sums_every_worn_item_and_a_heavy_kit_is_penalized():
    curve = monk_curve(TABLES.rules, 50)
    heavy = kit_of(("CHEST", vec(weight10=250)), ("LEGS", vec(weight10=150)))  # 40 stones
    result = value({"AC": 4}, heavy, softcap=(10 ** 6, 0.5), monk=curve, placement=TOP)
    assert result.totals["weight10"] == 400 and result.totals["sheet"]["monk_bonus"] == -10
    assert result.parts["MONK"] == 3 * -10


def test_a_trio_without_a_monk_has_no_weight_term():
    result = value({"AC": 4}, kit_of(("CHEST", vec(weight10=900))), softcap=(10 ** 6, 0.5))
    assert result.parts["MONK"] == 0 and result.totals["sheet"]["monk_bonus"] == 0


def test_iksar_armor_class_sits_on_top_or_inside():
    top = value({"AC": 4}, kit_of(("CHEST", vec(stats={"AC": 450}))), softcap=(400, F(1, 2)), iksar_ac=35, placement=TOP)
    assert top.parts["IKSAR"] == 3 * 35 and top.parts["AC"] == 3 * (400 + F(1, 2) * 205)
    assert top.totals["sheet"]["iksar"] == 35 and top.totals["sheet"]["total"] == F("502.5") + 35
    inside = value({"AC": 4}, kit_of(("CHEST", vec(stats={"AC": 450}))), softcap=(400, F(1, 2)), iksar_ac=35,
                   placement={"monk": "top", "iksar": "inside"})
    assert inside.parts["IKSAR"] == 0 and inside.parts["AC"] == 3 * (400 + F(1, 2) * 240)
    assert value({"AC": 4}, iksar_ac=0).parts["IKSAR"] == 0


@pytest.mark.parametrize(
    "spell, items, cap, worn_counted, counted",
    [
        (40, (50,), 75, 35, 75), (40, (20,), 75, 20, 60), (40, (), 75, 0, 40), (0, (20, 30), 75, 30, 30),
        (45, (30,), 40, 0, 40), (0, (90,), 75, 75, 75), (75, (10,), 75, 0, 75), (0, (), 75, 0, 0),
    ],
)
def test_only_the_best_worn_haste_counts_up_to_the_cap_minus_the_spell(spell, items, cap, worn_counted, counted):
    places = ("HEAD", "BACK", "NECK")
    kit = kit_of(*[(places[i], vec(key=f"h{i}", haste=h)) for i, h in enumerate(items)])
    result = value({"HASTE": 2}, kit, buffs={"HASTE": spell}, haste_cap=cap)
    want = {"spell": spell, "worn_best": max(items, default=0), "worn_counted": worn_counted, "counted": counted}
    assert result.totals["haste"] == want
    assert result.parts["HASTE"] == 2 * counted


def test_haste_headroom_never_goes_below_zero():
    result = value({"HASTE": 1}, kit_of(("HEAD", vec(haste=30))), buffs={"HASTE": 45}, haste_cap=40)
    assert result.totals["haste"]["worn_counted"] == 0 and result.parts["HASTE"] == 40


def test_regen_counts_gear_to_the_cap_and_buffs_outside_it():
    kit = kit_of(
        ("HEAD", vec(stats={"HPREG": 20, "MANAREG": 10, "ENDREG": 20})), ("BACK", vec(stats={"HPREG": 15})),
    )
    result = value({"HPREG": 2, "MANAREG": 3, "ENDREG": 4}, kit, buffs={"HPREG": 5, "MANAREG": 2})
    assert result.parts["REGEN"] == 2 * (30 + 5) + 3 * (10 + 2) + 4 * 15
    assert result.totals["regen"]["HPREG"] == {"gear": 35, "buff": 5, "counted": 35}


def test_resists_count_each_school_to_1000_with_buffs_inside_the_cap():
    """T4: the game client's resist cap is 1000 a school (it was a judgment of 200): gear and buffs count together up to it."""
    kit = kit_of(("HEAD", vec(sv={"FIRE": 900, "COLD": 100})), ("BACK", vec(sv={"MAGIC": -10})))
    result = value({"SV": F(1, 2)}, kit, buffs={"SV": {"FIRE": 200}})
    assert result.parts["RESISTS"] == F(1, 2) * (1000 + 100 - 10)
    assert result.totals["resists"]["FIRE"] == {"gear": 900, "buff": 200, "counted": 1000}
    plain = value({"SV": F(1, 2)}, kit_of(("HEAD", vec(sv={"FIRE": 150, "COLD": 100}))), buffs={"SV": {"FIRE": 70}})
    assert plain.totals["resists"]["FIRE"] == {"gear": 150, "buff": 70, "counted": 220}  # (what the old cap of 200 cut short)


def test_a_school_weight_replaces_the_general_resist_weight():
    kit = kit_of(("HEAD", vec(sv={"FIRE": 10, "COLD": 10})))
    result = value({"SV": 1, "SV_FIRE": 3}, kit)
    assert result.parts["RESISTS"] == 3 * 10 + 1 * 10


def test_corruption_is_never_scored():
    result = value({"SV": 1}, kit_of(("HEAD", vec(sv={"CORRUPTION": 80, "FIRE": 5}))))
    assert result.parts["RESISTS"] == 5


STANCE = {"swing_factor": F("2.1"), "agi_share": 0}  # T8: the Berserker stance of the client's calculation (x2.1 on the swing timer after the haste cap, no AGI in mitigation or evasion)


def test_the_berserker_stance_multiplies_the_swing_after_the_haste_cap_and_takes_agi_out_of_the_sheet_and_the_evasion():
    sword = vec(weapon=WeaponVec("1H Slashing", 20, 30, None, False), slots=("PRIMARY",))
    boots = vec("boots", haste=30, slots=("FEET",))
    kit = kit_of(("PRIMARY", sword), ("FEET", boots))
    weights = {"DMG": 10, "AC": 4, "HASTE": 1}
    plain = evaluate(profile(weights=weights, naked={**NAKED_100, "AGI": 100}), kit, {"HASTE": 20}, setup="1h-shield", haste_assumed=50)
    stanced = evaluate(profile(weights=weights, naked={**NAKED_100, "AGI": 100}, stance=STANCE), kit, {"HASTE": 20}, setup="1h-shield", haste_assumed=50)
    assert stanced.parts["WEAPON"] == plain.parts["WEAPON"] * F("2.1")  # the factor multiplies the whole of the swing's index
    assert stanced.totals["haste"] == plain.totals["haste"] and stanced.parts["HASTE"] == plain.parts["HASTE"]  # (the stance does not change the haste that counts: the factor comes after the cap)
    assert plain.parts["EVASION"] > 0 and stanced.parts["EVASION"] == 0  # (no AGI in the evasion)
    assert plain.totals["sheet"]["X"] - stanced.totals["sheet"]["X"] == F(100, formulas.SHEET_AGI_DIV)  # (and none in the armor class: AGI / 20 less)
    assert stanced.parts["MANA"] == plain.parts["MANA"] and stanced.parts["HP"] == plain.parts["HP"]


def test_the_stance_factor_is_for_the_hands_that_swing_and_not_for_a_bow_or_a_proc():
    bow = vec("bow", weapon=WeaponVec("Archery", 40, 60, None, False), slots=("RANGE",))
    kit = kit_of(("RANGE", bow))
    weights = {"DMG": 10}
    plain = evaluate(profile(weights=weights, ranged_factor=F(3, 4)), kit, setup="ranged", haste_assumed=0)
    stanced = evaluate(profile(weights=weights, ranged_factor=F(3, 4), stance=STANCE), kit, setup="ranged", haste_assumed=0)
    assert plain.parts["WEAPON"] > 0 and stanced.parts["WEAPON"] == plain.parts["WEAPON"]  # (a bow shoots as it did)
    main = vec("main", weapon=WeaponVec("1H Slashing", 20, 30, None, False), slots=("PRIMARY",))
    off = vec("off", weapon=WeaponVec("1H Slashing", 18, 36, None, False), slots=("SECONDARY",))
    both = kit_of(("PRIMARY", main), ("SECONDARY", off))
    a = evaluate(profile(weights=weights, dw_factor=F(69, 100)), both, setup="dw")
    b = evaluate(profile(weights=weights, dw_factor=F(69, 100), stance=STANCE), both, setup="dw")
    assert b.parts["WEAPON"] == a.parts["WEAPON"] * F("2.1")  # (both hands swing faster)


@pytest.mark.parametrize("stance", [{"swing_factor": 0, "agi_share": 0}, {"swing_factor": -1, "agi_share": 0}, {"swing_factor": 2, "agi_share": 2}, {"swing_factor": 2}, {"agi_share": 0}, {"swing_factor": 2, "agi_share": 0, "x": 1}, 5, "berserker"])
def test_a_stance_that_is_not_a_factor_of_the_swing_and_a_share_of_agi_is_refused(stance):
    with pytest.raises(ValueError, match="stance"):
        profile(stance=stance)


def test_weapon_damage_part():
    sword = vec(weapon=WeaponVec("1H Slashing", 20, 30, None, False), slots=("PRIMARY",))
    result = evaluate(profile(weights={"DMG": 10}), kit_of(("PRIMARY", sword)), setup="1h-shield", haste_assumed=50)
    assert result.parts["WEAPON"] == 10 * F(7, 4)


def test_dual_wield_second_hand_is_scaled_without_a_bonus_and_the_stick_scores_nothing():
    main = vec(weapon=WeaponVec("1H Slashing", 20, 30, None, False), slots=("PRIMARY",))
    off = vec(key="off", weapon=WeaponVec("Piercing", 10, 20, 5, False), slots=("SECONDARY",))
    prof = profile(weights={"DMG": 4}, dw_factor=F(1, 2))
    dw = evaluate(prof, kit_of(("PRIMARY", main), ("SECONDARY", off)), setup="dw", haste_assumed=50)
    assert dw.parts["WEAPON"] == 4 * (F(7, 4) + F(10, 20) * F(3, 2) * F(1, 2))  # the off hand: no bonus, times the factor
    stick = evaluate(prof, kit_of(("PRIMARY", main), ("SECONDARY", off)), setup="stick", haste_assumed=50)
    assert stick.parts["WEAPON"] == 0


def test_evaluate_scores_a_hand_the_setup_does_not_allow_as_zero():
    sword = vec(key="sword", weapon=WeaponVec("1H Slashing", 20, 30, None, False), slots=("PRIMARY", "SECONDARY"))
    axe = vec(key="axe", weapon=WeaponVec("2H Slashing", 40, 60, None, True), slots=("PRIMARY",))
    prof = profile(weights={"DMG": 1})
    for setup, kit, want in (
        ("2h", kit_of(("PRIMARY", sword)), 0),  # a one-hander in the two-hander setup
        ("2h", kit_of(("PRIMARY", axe), ("SECONDARY", sword)), (40 + F(6875, 10000) * 50) / 60),  # only the axe counts (T9: 0.6875)
        ("dw", kit_of(("PRIMARY", axe)), 0),
        ("1h-shield", kit_of(("PRIMARY", sword), ("SECONDARY", sword)), F(7, 6)),  # the second sword is no shield
    ):
        assert evaluate(prof, kit, setup=setup, haste_assumed=0).parts["WEAPON"] == want, setup


def test_a_shield_or_a_held_item_has_no_weapon_value_and_no_setup_scores_no_weapon():
    main = vec(weapon=WeaponVec("1H Slashing", 20, 30, None, False), slots=("PRIMARY",))
    shield = vec(key="s", stats={"AC": 10}, shield=True, slots=("SECONDARY",))
    prof = profile(weights={"DMG": 1})
    with_shield = evaluate(prof, kit_of(("PRIMARY", main), ("SECONDARY", shield)), setup="1h-shield")
    assert with_shield.parts["WEAPON"] == F(7, 6)
    assert evaluate(prof, kit_of(("PRIMARY", main))).parts["WEAPON"] == 0  # no setup, no weapon plan: nothing scored


def test_a_weapon_in_an_any_slot_is_a_stat_stick_with_no_damage_value():
    main = vec(weapon=WeaponVec("1H Slashing", 20, 30, None, False), stats={"STR": 10}, slots=("PRIMARY",))
    result = evaluate(profile(weights={"DMG": 5, "ATK": 1}), kit_of(("ANY", main)))
    assert result.parts["WEAPON"] == 0 and result.parts["ATK"] == F("0.666667") * 110


# ---- evaluate: everything at once ----------------------------------------------------------


def test_the_total_is_the_sum_of_the_parts_and_matches_a_worked_example():
    weights = {
        "HP": 1, "AC": 6, "MANA": F(1, 2), "ATK": 2, "DEX": F(1, 10), "HASTE": F(3, 2), "END": F(1, 2), "CHA": F(1, 20),
        "HPREG": 30, "MANAREG": 15, "ENDREG": 15, "SV": F(2, 5), "DMG": 5,
    }
    prof = profile(
        weights=weights, level=50, softcap=(392, 0.33), cs_pct=10, pe_pct=2, defense_cap=230, haste_cap=85,
        iksar_ac=0, monk=monk_curve(TABLES.rules, 50), placement=TOP,
    )
    kit = kit_of(
        ("HEAD", vec(stats={"AC": 30, "STA": 20, "HP": 40, "HPREG": 2}, weight10=40)),
        ("CHEST", vec(key="c", stats={"AC": 90, "STR": 15, "AGI": 10}, sv={"FIRE": 20}, weight10=100, haste=30)),
        ("NECK", vec(key="n", stats={"WIS": 30, "MANA": 25, "CHA": 12}, weight10=1)),
        ("FINGER", vec(key="f1", stats={"DEX": 14, "ATK": 8, "END": 20}, sv={"COLD": 11}, weight10=1)),
        ("PRIMARY", vec(key="p", weapon=WeaponVec("1H Slashing", 25, 30, 10, False), slots=("PRIMARY",), weight10=25)),
        ("SECONDARY", vec(key="s", stats={"AC": 35, "STA": 10}, shield=True, slots=("SECONDARY",), weight10=60)),
    )
    buffs = {"STR": 20, "AC": 20, "HP": 100, "HASTE": 25, "SV": {"FIRE": 10}, "HPREG": 3}
    result = evaluate(prof, kit, buffs, setup="1h-shield", haste_assumed=55)
    assert result.F == sum(result.parts.values())
    # --- the same, worked out part by part (plain arithmetic) ---
    sta, str_, agi, dex, wis, int_, cha = 100 + 20 + 10, 100 + 20 + 15, 100 + 10, 100 + 14, 100 + 30, 100, 100 + 12
    hp = (5 + 1500 + 5 * sta) + (5 + 1320 + F("4.4") * sta) + 40 + 100
    assert result.parts["HP"] == hp
    mana = (900 + F("4.5") * (100 + F(5, 2) * 30)) + (900 + F("4.5") * 100) + 25
    assert result.parts["MANA"] == F(1, 2) * mana
    avg = F(min(str_, 510) + sta + dex + agi, 4)
    conv = 100 + F(5, 2) * (avg - 100) if avg > 100 else avg
    end = (900 + F("4.5") * conv) + (456 + F("3.25") * conv) + 20
    assert result.parts["END"] == F(1, 2) * end
    worn_ac, shield_ac = 30 + 90, 35
    x = F(4, 3) * (worn_ac + shield_ac) + F(230, 3) + F(20, 4) + F(agi, 20)
    y = 439 + shield_ac
    sheet = min(x, F(33, 100) * x + F(67, 100) * y)
    weight10 = 40 + 100 + 1 + 1 + 25 + 60
    bonus = MONK_FILE["levels"]["50"]["stand_in"][22]  # 227 tenths = 22 whole stones
    assert weight10 == 227 and bonus == 48
    assert result.parts["AC"] == 6 * sheet / F(4, 3)
    assert result.parts["MONK"] == 6 * bonus / F(4, 3)
    assert result.parts["EVASION"] == 6 * F("0.2222") * agi
    assert result.parts["ATK"] == 2 * (F("0.666667") * str_ + 8)
    assert result.parts["DEX"] == F(1, 10) * dex
    assert result.parts["CHA"] == F(1, 20) * cha
    assert result.parts["HASTE"] == F(3, 2) * min(85, 25 + 30)
    assert result.parts["REGEN"] == 30 * (2 + 3)
    assert result.parts["RESISTS"] == F(2, 5) * (min(30, 200) + 11)
    assert result.parts["WEAPON"] == 5 * ((25 + 10) * F(155, 100) / 30)


def test_a_breakdown_is_frozen_and_keeps_every_part_name():
    result = value({})
    assert set(result.parts) == {
        "HP", "MANA", "END", "AC", "EVASION", "ATK", "DEX", "HASTE", "REGEN", "RESISTS", "CHA", "WEAPON", "MONK", "IKSAR",
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.F = 1


# ---- buffs, deficits, bands and the totals -------------------------------------------------


def test_the_buffs_argument_replaces_the_profiles_buff_totals():
    prof = profile(weights={"HP": 1}, buff_totals={"HP": 100})
    assert evaluate(prof, kit_of()).parts["HP"] == 3770 + 100
    assert evaluate(prof, kit_of(), {"HP": 30}).parts["HP"] == 3770 + 30
    assert evaluate(prof, kit_of(), {}).parts["HP"] == 3770


@pytest.mark.parametrize("buffs", [{"HPP": 1}, {"SV": {"VOID": 3}}, {"SV": {"CORRUPTION": 3}}, {"haste": 3}])
def test_buff_totals_with_an_unknown_key_are_refused(buffs):
    with pytest.raises(ValueError):
        value({"HP": 1}, buffs=buffs)
    with pytest.raises(ValueError):
        profile(buff_totals=buffs)


def test_totals_below_zero_are_worth_nothing_and_never_less():
    kit = kit_of(("HEAD", vec(stats={k: -500 for k in "STR STA AGI DEX CHA".split()})))
    result = value({"HP": 1, "END": 1, "DEX": 1, "CHA": 1, "ATK": 1, "AC": 1}, kit)
    assert result.parts["DEX"] == result.parts["CHA"] == result.parts["ATK"] == result.parts["EVASION"] == 0
    assert result.parts["HP"] == (5 + 1500) + (5 + 1320)  # STA' is 0: the bases alone
    assert result.parts["END"] == 900 + 456  # the END average is below zero: the bases alone


def test_a_negative_converted_value_counts_as_zero_in_the_window_too():
    got = window(("WAR", "MNK", "ROG"), {"STR": -50, "STA": -50, "DEX": -50, "AGI": -50})
    assert got["END"] == 1800 and got["HP"] == (5 + 1500) + (5 + 1275)


def test_a_mana_pool_names_wis_or_int_and_only_those():
    with pytest.raises(ValueError, match="WIS or INT"):
        PoolSpec("CLR", 900, 4.5, "STR")
    with pytest.raises(ValueError):
        profile(pools={**POOLS, "MANA": (PoolSpec("CLR", 900, 4.5),)})  # a mana pool without its stat


def test_the_profiles_band_curve_replaces_the_default():
    alternative = {"breaks": [100, 200, 510], "slopes": [1, 2.5, 0.654, 0]}  # an invented curve
    wis_300 = {**NAKED_100, "WIS": 300}
    default = value({"MANA": 1}, naked=wis_300)
    other = value({"MANA": 1}, naked=wis_300, bands=alternative)
    # default: 100 + 250 + 1.25 * 100 = 475 for the cleric; the enchanter stays at INT 100 -> 1350
    assert default.parts["MANA"] == (900 + F("4.5") * 475) + 1350
    assert other.parts["MANA"] == (900 + F("4.5") * (350 + F("65.4"))) + 1350


def test_the_totals_carry_the_keys_the_solver_tests_rely_on():
    result = value({"HP": 1}, kit_of(("CHEST", vec(stats={"AC": 10}, weight10=5))))
    assert set(result.totals) == {
        "attributes", "pools", "counted", "end_average", "sheet", "haste", "regen", "resists", "weight10", "atk",
    }
    assert set(result.totals["attributes"]) == set("STR STA AGI DEX WIS INT CHA".split())
    assert set(result.totals["sheet"]) == {"worn_ac", "shield_ac", "X", "Y", "capped", "monk_bonus", "iksar", "total"}
    assert set(result.totals["pools"]) == set(result.totals["counted"]) == {"HP", "MANA", "END"}
    assert set(result.totals["regen"]) == {"HPREG", "MANAREG", "ENDREG"} and set(result.totals["resists"]) == set(SCHOOLS)


def test_items_made_at_a_tier_feed_the_evaluator():
    from trioforge.model.items import at_tier

    def piece(key, slot, ac, weight):
        return {
            "key": key, "name": key, "slots": [slot], "classes": ["ALL"], "deity": None, "flags": [], "stats": {"AC": ac},
            "sv": {}, "weight": weight, "item_type": None, "weapon": None,
        }

    catalog = [piece("w1", "HEAD", 20, 3.0), piece("w2", "CHEST", 40, 10.0), piece("w3", "LEGS", 30, 8.0)]
    prof = profile(weights={"AC": 4}, softcap=(10 ** 6, 0.5), monk=monk_curve(TABLES.rules, 50))
    fade = MONK_FILE["levels"]["50"]["stand_in"]
    # tier: (worn AC, tenths of a stone). 3.0 / 10.0 / 8.0 stones lose 9 % of the base a tier, rounded down, to a floor of 0.1 each.
    for tier, (worn_ac, tenths) in {0: (90, 210), 4: (126, 136), 10: (180, 21)}.items():
        kit = kit_of(*[(item["slots"][0], at_tier(item, tier, TABLES.rules)) for item in catalog])
        result = evaluate(prof, kit)
        assert result.totals["sheet"]["worn_ac"] == worn_ac and result.totals["weight10"] == tenths, tier
        assert result.totals["sheet"]["monk_bonus"] == fade[tenths // 10], tier
    assert fade[21] < 73 and fade[13] == fade[2] == fade[0] == 73  # +0 is over the fade, +4 and +10 are light enough for the full bonus


# ---- inputs it refuses ---------------------------------------------------------------------


def test_the_kit_must_have_one_entry_per_place():
    with pytest.raises(ValueError, match="22"):
        evaluate(profile(), [None] * 21)
    with pytest.raises(ValueError, match="22"):
        evaluate(profile(), [None] * 23)


@pytest.mark.parametrize("changes", [dict(stats={"HASTE": 10}), dict(stats={"BOGUS": 1}), dict(sv={"VOID": 3})])
def test_an_item_stat_the_model_does_not_know_is_refused_not_ignored(changes):
    with pytest.raises(ValueError, match="unknown"):
        evaluate(profile(), kit_of(("HEAD", vec(**changes))))


def test_an_unknown_setup_is_refused():
    with pytest.raises(ValueError, match="setup"):
        evaluate(profile(), kit_of(), setup="bow")


@pytest.mark.parametrize(
    "changes",
    [
        dict(weights={"HP": -1}), dict(weights={"MP": 1}), dict(placement={"monk": "under", "iksar": "top"}),
        dict(placement={"monk": "top"}), dict(naked={"STR": 1}), dict(pools={"HP": ()}), dict(haste_cap=-1),
    ],
)
def test_a_profile_that_cannot_be_evaluated_is_refused(changes):
    with pytest.raises((ValueError, KeyError, TypeError)):
        profile(**changes)


def test_a_profile_of_another_class_is_read_by_its_attributes():
    plain = profile(weights={"HP": 1, "AC": 2, "HASTE": 1}, softcap=(400, 0.5), haste_cap=75)
    duck = types.SimpleNamespace(**{f.name: getattr(plain, f.name) for f in dataclasses.fields(EvalProfile)})
    kit = kit_of(("CHEST", vec(stats={"AC": 100, "HP": 5}, haste=20)))
    assert evaluate(duck, kit).F == evaluate(plain, kit).F
    assert compile_profile(plain) is plain
    assert isinstance(compile_profile(duck), EvalProfile)


def test_pools_for_lists_every_class_for_hp_and_end_and_only_mana_classes_for_mana():
    pools = pools_for(("BER", "CLR", "SHD"), 50, TABLES)
    assert [p.cls for p in pools["HP"]] == [p.cls for p in pools["END"]] == ["BER", "CLR", "SHD"]
    assert [(p.cls, p.stat) for p in pools["MANA"]] == [("CLR", "WIS"), ("SHD", "INT")]
    assert pools["HP"][0] == PoolSpec("BER", F(1275), F("4.25"))
    assert pools["END"][0] == PoolSpec("BER", F(995), F("4.25"))
    assert pools["MANA"][1] == PoolSpec("SHD", F(900), F("4.5"), "INT")
    assert pools_for(("WAR", "MNK", "ROG"), 50, TABLES)["MANA"] == ()
    with pytest.raises(ValueError):
        pools_for(("WAR", "WAR", "ROG"), 50, TABLES)
    with pytest.raises(ValueError):
        pools_for(("WAR", "XXX", "ROG"), 50, TABLES)
    with pytest.raises(KeyError):
        pools_for(("WAR", "MNK", "ROG"), 99, TABLES)


def test_pools_for_leaves_out_a_mana_class_without_mana_and_a_class_without_a_mana_stat():
    row = {
        "hp": 100.0, "mana": 0.0, "end": 50.0, "hp_regen": 7.0, "end_regen": 13.0, "hp_fac": 1.0, "mana_fac": 0.0,
        "end_fac": 1.0,
    }
    tables = dataclasses.replace(TABLES, basedata={
        ("CLR", 3): dict(row),  # a mana class that has no mana yet
        ("PAL", 3): dict(row, mana=15.0, mana_fac=0.075),
        ("WAR", 3): dict(row, mana=15.0, mana_fac=0.075),  # no mana stat: never a mana class, whatever the table says
    })
    pools = pools_for(("CLR", "PAL", "WAR"), 3, tables)
    assert [(p.cls, p.stat) for p in pools["MANA"]] == [("PAL", "WIS")]
    assert [p.cls for p in pools["HP"]] == ["CLR", "PAL", "WAR"]


# ---- properties ----------------------------------------------------------------------------

POSITIVE_STATS = "AC STR STA AGI DEX WIS INT CHA HP MANA END ATK HPREG MANAREG ENDREG".split()
TRIOS = [("PAL", "MNK", "BER"), ("CLR", "WIZ", "ENC"), ("SHD", "CLR", "SHM"), ("WAR", "MNK", "ROG")]


@st.composite
def kits(draw):
    placed = []
    for slot in SLOT_INSTANCES:
        if not draw(st.booleans()):
            continue
        weapon = None
        if slot in ("PRIMARY", "SECONDARY") and draw(st.booleans()):
            two_handed = draw(st.booleans())
            weapon = WeaponVec(
                "2H Blunt" if two_handed else "1H Blunt", draw(st.integers(1, 80)), draw(st.integers(10, 80)),
                draw(st.one_of(st.none(), st.integers(1, 40))), two_handed,
            )
        item = vec(
            key=f"k{len(placed)}",
            stats=draw(st.dictionaries(st.sampled_from(POSITIVE_STATS), st.integers(1, 150), max_size=6)),
            sv=draw(st.dictionaries(st.sampled_from(SCHOOLS), st.integers(1, 90), max_size=3)),
            haste=draw(st.integers(0, 60)), weight10=draw(st.integers(0, 120)), weapon=weapon,
            shield=slot == "SECONDARY" and weapon is None and draw(st.booleans()), slots=(slot,),
        )
        placed.append((slot, item))
    return kit_of(*placed)


FULL_WEIGHTS = {
    "HP": 1, "AC": 6, "MANA": F(1, 2), "ATK": 2, "DEX": F(1, 10), "HASTE": F(3, 2), "END": F(1, 2), "CHA": F(1, 20),
    "HPREG": 30, "MANAREG": 15, "ENDREG": 15, "SV": F(2, 5), "DMG": 5,
}


def full_profile(trio, **changes):
    return EvalProfile(
        level=50, naked=naked("HUM", trio, TABLES), weights=FULL_WEIGHTS, pools=pools_for(trio, 50, TABLES),
        softcap=(392, 0.33),
        cs_pct=10, pe_pct=2, defense_cap=230, haste_cap=85, monk=monk_curve(TABLES.rules, 50) if "MNK" in trio else None,
        iksar_ac=35, dw_factor=F(3, 5), **changes,
    )


def raised(item, what, delta):
    """``item`` with one positive number raised by ``delta``."""
    if what == "haste":
        return dataclasses.replace(item, haste=item.haste + delta)
    if what == "dmg":
        return dataclasses.replace(item, weapon=dataclasses.replace(item.weapon, dmg=item.weapon.dmg + delta))
    kind, key = what
    table = dict(item.stats if kind == "stats" else item.sv)
    table[key] = table[key] + delta
    return dataclasses.replace(item, **{kind: table})


@settings(max_examples=120, deadline=None)
@given(
    kit=kits(), trio=st.sampled_from(TRIOS), choice=st.randoms(use_true_random=False), delta=st.integers(1, 60),
    placement=st.sampled_from([{"monk": m, "iksar": i} for m in ("top", "inside") for i in ("top", "inside")]),
    setup=st.sampled_from([None, "dw", "2h", "1h-shield", "stick"]), spell_haste=st.integers(0, 90),
)
def test_a_larger_positive_number_on_a_worn_item_never_lowers_the_total(
    kit, trio, choice, delta, placement, setup, spell_haste
):
    options = [(i, ("stats", k)) for i, it in enumerate(kit) if it for k in it.stats]
    options += [(i, ("sv", k)) for i, it in enumerate(kit) if it for k in it.sv]
    options += [(i, "haste") for i, it in enumerate(kit) if it]
    options += [(i, "dmg") for i, it in enumerate(kit) if it and it.weapon]
    if not options:
        return
    index, what = choice.choice(options)
    changed = list(kit)
    changed[index] = raised(kit[index], what, delta)
    prof = full_profile(trio, placement=placement)
    buffs = {"HASTE": spell_haste, "AC": 10}
    before = evaluate(prof, kit, buffs, setup=setup, haste_assumed=40)
    after = evaluate(prof, changed, buffs, setup=setup, haste_assumed=40)
    assert after.F >= before.F, (index, what)
    assert before.F == sum(before.parts.values())


@settings(max_examples=60, deadline=None)
@given(kit=kits(), trio=st.sampled_from(TRIOS))
def test_a_kit_of_weightless_items_is_never_worth_less_than_an_empty_one(kit, trio):
    light = [dataclasses.replace(it, weight10=0) if it else None for it in kit]
    prof = full_profile(trio)
    assert evaluate(prof, light).F >= evaluate(prof, kit_of()).F


# ---- the constants are the rules file's ----------------------------------------------------


def test_the_constants_in_the_evaluator_are_the_ones_in_rules_json():
    rules = TABLES.rules
    sta = rules.get("hp.sta_curve")
    assert (list(formulas.STA_CURVE[0]), [float(s) for s in formulas.STA_CURVE[1]]) == (sta["breaks"], sta["slopes"])
    bands = rules.get("mana.wis_bands")
    assert (list(formulas.MANA_BANDS[0]), [float(s) for s in formulas.MANA_BANDS[1]]) == (bands["breaks"], bands["slopes"])
    assert formulas.STAT_KNEE == rules.get("stats.knee") and formulas.STAT_CAP == rules.get("stats.hard_cap")
    assert formulas.STR_TO_ATK == F(str(rules.get("stats.str_to_atk")))
    assert formulas.AGI_TO_AC == F(str(rules.get("stats.agi_to_ac")))
    assert formulas.DEX_PAST_KNEE == F(str(rules.get("stats.dex_post255_slope")))
    assert formulas.POOLS_COUNTED == rules.get("hp.pools_counted") == rules.get("mana.pools_counted")
    assert (formulas.SHEET_DEFENSE_DIV, formulas.SHEET_SPELL_AC_DIV, formulas.SHEET_AGI_DIV) == (
        rules.get("ac.sheet.defense_div"), rules.get("ac.sheet.spell_ac_div"), rules.get("ac.sheet.agi_div"))
    # the rules file prints 4/3 to ten digits; the evaluator keeps it exact
    assert abs(F(str(rules.get("ac.sheet.item_mult"))) - formulas.SHEET_ITEM_MULT) < F(1, 10 ** 9)
    assert formulas.SCHOOLS == tuple(SCHOOLS)
    assert rules.get("resist.cap") == 1000 and rules.get("regen.gear_caps") == {"HP": 30, "MANA": 15, "END": 15}


def test_the_default_caps_are_the_rules_caps():
    prof = profile()
    assert prof.caps == {"regen": {"HP": 30, "MANA": 15, "END": 15}, "resist": 1000}
    assert dict(prof.placement) == {"monk": "inside", "iksar": "inside"}  # (R3: the default is the rules' placement, the client's; it was "top")


def test_rules_that_the_evaluator_leaves_to_the_profile_are_open_or_null():
    # the weapon damage weight is a judgment the profile carries (per build, times the build's ATK weight and weapon factor), open until
    # test B18; the evaluator reads it only through the DMG weight of the profile it is given
    assert TABLES.rules.get("weapons.damage_weight") == 450


# ---- F5: a weapon of a ranged skill scores nothing in a hand, in the evaluator as in the builder ---------------------------------------------------------------------------------


@pytest.mark.parametrize("skill", ["Archery", "archery", "Throwing", "Throwingv1", "Throwingv2"])
@pytest.mark.parametrize("setup", ["1h-shield", "2h", "dw", "stick", "ranged", None])
@pytest.mark.parametrize("hand", ["PRIMARY", "SECONDARY"])
def test_a_weapon_of_a_ranged_skill_scores_nothing_in_a_hand_whatever_the_setup(skill, setup, hand):
    """The builder refuses such a weapon a hand (weapons.allowed_in_hand, E8); the evaluator, which writes the definition out again, scores 0 there too: they are one rule."""
    weapon = WeaponVec(skill, 30, 40, None, False)
    assert weapon_index(weapon, hand, setup, 25, F(4, 5)) == 0
    assert weapon_index(WeaponVec(skill, 30, 40, None, True), hand, setup, 25, F(4, 5)) == 0  # (a two-hander of a ranged skill too)
    melee = WeaponVec("1H Piercing", 30, 40, None, False)
    assert weapon_index(melee, hand, "dw", 25, F(4, 5)) > 0  # (the same numbers of a melee skill are scored)


def test_the_range_place_scores_a_bow_under_the_bow_setup_and_a_thrown_weapon_nowhere():
    bow = WeaponVec("Archery", 30, 40, None, False)
    assert weapon_index(bow, "RANGE", "ranged", 0, F(4, 5), F(1)) == F(30, 40)
    assert weapon_index(WeaponVec("Throwing", 30, 40, None, False), "RANGE", "ranged", 0, F(4, 5), F(1)) == 0  # (a thrown weapon is no bow)
    assert weapon_index(bow, "RANGE", "dw", 0, F(4, 5)) == 0


@pytest.mark.parametrize("skill", ["Archery", "Throwing", "Throwingv2", "Piercing", "Hand to Hand", "1H Slashing", None])
@pytest.mark.parametrize("setup", ["1h-shield", "2h", "dw", "stick", "ranged"])
@pytest.mark.parametrize("hand", ["primary", "secondary", "range"])
def test_the_evaluator_and_the_builder_agree_on_what_a_hand_scores(skill, setup, hand):
    from trioforge.model import weapons as wp

    for two_handed in (False, True):
        vec = WeaponVec(skill, 30, 40, None, two_handed)
        item = types.SimpleNamespace(weapon=vec, slots=frozenset({"PRIMARY", "SECONDARY", "RANGE"}), is_shield=False)
        assert weapon_index(vec, hand.upper(), setup, 10, F(4, 5), F(1)) == wp.damage_index_exact(item, hand, setup, 10, dw_factor=F(4, 5), ranged_factor=F(1)), (skill, setup, hand, two_handed)


def test_the_evaluator_does_not_judge_where_an_item_stands_and_only_the_weapon_term_refuses_a_hand_to_a_ranged_weapon():
    """(G8) ``evaluate`` values the kit it is given: the stats of an item count in whatever place it stands (the callers, the builder, the pruning and the page's own reader of a shared kit, make legal
    kits and refuse the others), and the weapon term is the one thing that looks at the place: a hand scores the weapons the setup lets stand there. So an Archery or Throwing item in a hand counts its stats
    and no swing, as a sword in the chest counts its stats and no swing."""
    from solver_helpers import make_item, make_profile

    profile = make_profile(("PAL", "MNK", "BER"), "OGR", {"HP": 1, "DMG": 600})
    ring = make_item("ring", {"FINGER"}, stats={"HP": 40})
    bow = make_item("bow", {"RANGE", "PRIMARY"}, stats={"HP": 40}, weapon=WeaponVec("Archery", 30, 40, None, False))
    sword = make_item("sword", {"PRIMARY"}, stats={"HP": 40}, weapon=WeaponVec("1H Slashing", 30, 40, None, False))

    def value(**places):
        kit = [None] * len(SLOT_INSTANCES)
        for place, item in places.items():
            kit[SLOT_INSTANCES.index(place)] = item
        return evaluate(profile, kit, setup="dw", haste_assumed=0).F

    empty = value()
    assert value(HEAD=ring) == value(FINGER=ring) > empty  # a ring in the head counts as in the finger: no place is refused
    assert value(CHEST=sword) == value(FINGER=ring)  # a sword in the chest counts its stats and no swing
    assert value(PRIMARY=bow) == value(FINGER=ring)  # an Archery weapon in the main hand: its stats, no swing (F5)
    assert value(PRIMARY=sword) > value(PRIMARY=bow)  # (the same numbers of a sword score the swing)
