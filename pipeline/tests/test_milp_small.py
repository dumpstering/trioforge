"""Hand-checked tests of the MILP builder: ``trioforge.solver.model.build_milp``.

Each test builds a tiny model, solves it with the raw engine layer and compares with the exact oracle
(:func:`trioforge.model.formulas.evaluate`) or with numbers worked out by hand. The random brute force lives in
``test_milp_bruteforce.py``. Every name, race and item here is invented.
"""

import dataclasses
import random
from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest

from solver_helpers import (
    TABLES, Instance, check_instance, eval_totals, kit_from_groups, make_buff, make_buffset, make_item, make_profile,
    random_instance,
)
from trioforge.model import formulas as fm
from trioforge.model import weapons as weapons_module
from trioforge.model.formulas import EvalProfile, PoolSpec, evaluate
from trioforge.model.items import WeaponVec
from trioforge.solver._highs import solve_milp
from trioforge.solver.model import BuildOptions, build_milp, plan_top_pools

F = Fraction
NAKED_100 = {k: 100 for k in "STR STA AGI DEX WIS INT CHA".split()}
POOLS = {
    "HP": (PoolSpec("WAR", 1500, 5.0), PoolSpec("CLR", 1320, 4.4), PoolSpec("ENC", 1200, 4.0)),
    "MANA": (PoolSpec("CLR", 900, 4.5, "WIS"), PoolSpec("ENC", 900, 4.5, "INT")),
    "END": (PoolSpec("WAR", 900, 4.5), PoolSpec("CLR", 456, 3.25), PoolSpec("ENC", 260, 1.25)),
}
STICK = "stick"
OPT = BuildOptions(any_rule="explicit")  # only items that list ANY fit the Any group, unless a test says otherwise


def profile(**changes):
    base = dict(level=50, naked=NAKED_100, weights={}, pools=POOLS)
    base.update(changes)
    return EvalProfile(**base)


def solve(prof, items, setup=STICK, buffset=None, force=(), **opts):
    """Build, solve with the raw engine and evaluate the answer exactly.

    ``force`` is a list of ``(group, key)`` columns to wear at least once. Returns (milp, groups, buffs, exact F).
    """
    options = BuildOptions(**{"any_rule": "explicit", "haste_assumed": 0, **opts})
    milp = build_milp(prof, items, setup, buffset, options)
    for group, key in force:
        milp.col_lb[milp.index[(group, key)]] = 1
    res = solve_milp(milp)
    assert res.status == "optimal", res.status
    decoded = milp.decode(res.x)
    kit = kit_from_groups(decoded.groups)
    totals = eval_totals(buffset, decoded.buffs) if buffset is not None else None
    exact = evaluate(prof, kit, totals, setup=setup, haste_assumed=milp.haste_assumed).F
    # the model's own objective is the exact value of its kit
    assert abs(milp.const + res.objective - float(exact)) <= 1e-9 * max(1.0, abs(float(exact)))
    return milp, decoded.groups, decoded.buffs, exact


def keys(groups, group):
    return sorted(i.key for i in groups.get(group, []))


# ---- slots, copies, Lore ---------------------------------------------------------------------------------------


def test_one_slot_three_items_the_best_one_wins():
    prof = profile(weights={"HP": 1})
    items = [make_item(f"h{n}", {"HEAD"}, stats={"STA": n}) for n in (10, 20, 15)]
    _, groups, _, exact = solve(prof, items)
    assert keys(groups, "HEAD") == ["h20"]
    # STA 120: HP pools WAR 5 + 1500 + 5 * 120 and CLR 5 + 1320 + 4.4 * 120
    assert exact == (5 + 1500 + 5 * 120) + (5 + 1320 + F("4.4") * 120)


def test_an_empty_slot_is_allowed_when_every_item_hurts():
    prof = profile(weights={"HP": 1, "END": 1})
    bad = [make_item("bad", {"HEAD"}, stats={"STA": -30, "HP": -50})]
    _, groups, _, exact = solve(prof, bad)
    assert groups.get("HEAD", []) == []
    assert exact == evaluate(prof, [None] * 22).F


def test_a_lore_item_is_worn_once_over_every_group():
    prof = profile(weights={"HP": 1})
    ring = make_item("lore-ring", {"FINGER", "EAR"}, stats={"HP": 100}, lore=True)
    milp, groups, _, exact = solve(prof, [ring])
    assert sum(len(v) for v in groups.values()) == 1
    assert exact == evaluate(prof, [None] * 22).F + 100
    # without Lore it fills all four places of the two groups
    plain = dataclasses.replace(ring, key="plain-ring", lore=False)
    _, groups, _, exact = solve(prof, [plain])
    assert keys(groups, "FINGER") == ["plain-ring"] * 2 and keys(groups, "EAR") == ["plain-ring"] * 2
    assert exact == evaluate(prof, [None] * 22).F + 400


def test_two_lore_items_of_different_keys_may_both_be_worn():
    prof = profile(weights={"HP": 1})
    a = make_item("lore-a", {"FINGER"}, stats={"HP": 100}, lore=True)
    b = make_item("lore-b", {"FINGER"}, stats={"HP": 90}, lore=True)
    _, groups, _, _ = solve(prof, [a, b])
    assert keys(groups, "FINGER") == ["lore-a", "lore-b"]


def test_a_group_holds_no_more_than_its_places():
    prof = profile(weights={"HP": 1})
    chests = [make_item("c1", {"CHEST"}, stats={"HP": 100}), make_item("c2", {"CHEST"}, stats={"HP": 90})]
    wrist = make_item("w", {"WRIST"}, stats={"HP": 10})
    _, groups, _, _ = solve(prof, [*chests, wrist])
    assert keys(groups, "CHEST") == ["c1"] and keys(groups, "WRIST") == ["w", "w"]  # one place: the better piece only


def test_the_any_group_takes_every_item_that_has_a_slot_under_the_all_rule_and_only_listed_ones_otherwise():
    prof = profile(weights={"HP": 1})
    head = make_item("head-piece", {"HEAD"}, stats={"HP": 50})
    sword = make_item("sword", {"PRIMARY"}, stats={"HP": 30}, weapon=WeaponVec("1H Slashing", 10, 30, None, False))
    stick = make_item("stick-piece", {"ANY"}, stats={"HP": 5})
    explicit = build_milp(prof, [head, sword, stick], STICK, None, BuildOptions(any_rule="explicit"))
    assert {(g, k) for g, k in explicit.colmap.values() if g == "ANY"} == {("ANY", "stick-piece")}
    every = build_milp(prof, [head, sword, stick], STICK, None, BuildOptions(any_rule="all"))
    assert {k for g, k in every.colmap.values() if g == "ANY"} == {"head-piece", "sword", "stick-piece"}
    _, groups, _, exact = solve(prof, [head, sword, stick], any_rule="all")
    assert keys(groups, "ANY") == ["head-piece", "head-piece"] and keys(groups, "HEAD") == ["head-piece"]
    assert keys(groups, "PRIMARY") == ["sword"]
    assert exact == evaluate(prof, [None] * 22).F + 50 + 100 + 30


def test_an_item_that_fits_no_group_has_no_column():
    prof = profile(weights={"HP": 1})
    milp = build_milp(prof, [make_item("nowhere", set(), stats={"HP": 100})], STICK, None, BuildOptions(any_rule="all"))
    assert milp.colmap == {}


def test_items_for_other_classes_and_other_deities_are_left_out():
    prof = profile(weights={"HP": 1})
    mine = make_item("mine", {"HEAD"}, stats={"HP": 10}, classes={"WAR"})
    other = make_item("other", {"HEAD"}, stats={"HP": 99}, classes={"MNK"})
    god = make_item("god", {"HEAD"}, stats={"HP": 98}, deity={"Brell"})
    milp = build_milp(prof, [mine, other, god], STICK, None, OPT)
    assert {k for _, k in milp.colmap.values()} == {"mine"}  # the trio is WAR/CLR/ENC; no deity means locked items out
    follower = SimpleNamespace(**{f.name: getattr(prof, f.name) for f in dataclasses.fields(EvalProfile)}, deity="Brell")
    milp = build_milp(follower, [mine, other, god], STICK, None, OPT)
    assert {k for _, k in milp.colmap.values()} == {"mine", "god"}
    stranger = SimpleNamespace(**{**follower.__dict__, "deity": "Tunare"})
    assert {k for _, k in build_milp(stranger, [mine, god], STICK, None, OPT).colmap.values()} == {"mine"}


def test_items_that_exclude_the_scenario_race_get_no_column():
    prof = profile(weights={"HP": 1})
    plain = make_item("plain", {"HEAD"}, stats={"HP": 10})
    humans = dataclasses.replace(make_item("humans", {"HEAD"}, stats={"HP": 99}), races=frozenset({"HUM", "ELF"}))
    fields = {f.name: getattr(prof, f.name) for f in dataclasses.fields(EvalProfile)}

    def columns(profile_):
        return {k for _, k in build_milp(profile_, [plain, humans], STICK, None, OPT).colmap.values()}

    assert columns(prof) == {"plain", "humans"}  # an evaluator profile has no race: nothing is restricted
    assert columns(SimpleNamespace(**fields, race="ERU")) == {"plain"}
    assert columns(SimpleNamespace(**fields, race="HUM")) == {"plain", "humans"}
    assert columns(SimpleNamespace(**fields, race="ELF")) == {"plain", "humans"}
    # the best kit follows: the 99 hit points are worn by an elf and not by an Erudite
    _, groups, _, _ = solve(SimpleNamespace(**fields, race="ERU"), [plain, humans])
    assert keys(groups, "HEAD") == ["plain"]
    _, groups, _, _ = solve(SimpleNamespace(**fields, race="ELF"), [plain, humans])
    assert keys(groups, "HEAD") == ["humans"]


def test_a_real_profile_carries_the_race_the_builder_filters_by():
    from trioforge.model.profile import make_profile as real_profile

    humans = dataclasses.replace(make_item("humans", {"HEAD"}, stats={"HP": 99}), races=frozenset({"HUM"}))
    plain = make_item("plain", {"HEAD"}, stats={"HP": 10})
    for race, wanted in (("HUM", {"plain", "humans"}), ("ERU", {"plain"})):
        real = real_profile(race, ("CLR", "WIZ", "ENC"), 50, "caster", None, None, TABLES)
        assert {k for _, k in build_milp(real, [plain, humans], STICK, None, OPT).colmap.values()} == wanted, race


def test_the_pool_is_sorted_so_the_input_order_changes_nothing():
    prof = profile(weights={"HP": 1, "MANA": 1})
    items = [make_item(f"i{n}", {"HEAD", "NECK"}, stats={"STA": n, "WIS": 30 - n}) for n in range(6)]
    one = build_milp(prof, items, STICK, None, OPT)
    two = build_milp(prof, list(reversed(items)), STICK, None, OPT)
    assert one.names == two.names and np.array_equal(one.c, two.c) and np.array_equal(one.A.value, two.A.value)


# ---- the hands --------------------------------------------------------------------------------------------------


SWORD = make_item("sword", {"PRIMARY", "SECONDARY"}, stats={"STR": 5}, weapon=WeaponVec("1H Slashing", 20, 30, None, False))
DAGGER = make_item("dagger", {"PRIMARY", "SECONDARY"}, stats={"AGI": 5}, weapon=WeaponVec("Piercing", 8, 20, 4, False))
AXE = make_item("axe", {"PRIMARY"}, stats={"STR": 30}, weapon=WeaponVec("2H Slashing", 40, 60, None, True))
SHIELD = make_item("shield", {"SECONDARY"}, stats={"AC": 20}, shield=True)
LAMP = make_item("lamp", {"PRIMARY", "SECONDARY"}, stats={"WIS": 10})
HANDS = [SWORD, DAGGER, AXE, SHIELD, LAMP]


@pytest.mark.parametrize(
    "setup, primary, secondary",
    [
        ("1h-shield", {"sword", "dagger"}, {"shield"}),
        ("2h", {"axe"}, set()),
        ("dw", {"sword", "dagger"}, {"sword", "dagger"}),
        ("stick", {"sword", "dagger", "axe", "lamp"}, {"sword", "dagger", "shield", "lamp"}),
    ],
)
def test_the_setup_decides_which_items_can_stand_in_each_hand(setup, primary, secondary):
    milp = build_milp(profile(weights={"HP": 1}), HANDS, setup, None, OPT)
    assert {k for g, k in milp.colmap.values() if g == "PRIMARY"} == primary
    assert {k for g, k in milp.colmap.values() if g == "SECONDARY"} == secondary


def test_a_two_hander_in_the_primary_hand_leaves_the_secondary_hand_empty():
    prof = profile(weights={"AC": 3, "ATK": 1})
    milp, groups, _, _ = solve(prof, HANDS, STICK, force=[("PRIMARY", "axe")])
    assert keys(groups, "PRIMARY") == ["axe"] and keys(groups, "SECONDARY") == []  # the shield's AC would pay
    free, groups, _, _ = solve(prof, HANDS, STICK)  # without the axe forced, the shield is worn and the axe is not
    assert keys(groups, "SECONDARY") == ["shield"] and "axe" not in keys(groups, "PRIMARY")


def test_the_two_handed_setup_never_fills_the_secondary_hand():
    prof = profile(weights={"AC": 3, "ATK": 1, "DMG": 2})
    _, groups, _, _ = solve(prof, HANDS, "2h")
    assert keys(groups, "PRIMARY") == ["axe"] and keys(groups, "SECONDARY") == []


STAFF = make_item(  # a two-hander whose page lists the off hand and the back as well
    "staff", {"BACK", "PRIMARY", "SECONDARY"}, stats={"WIS": 7}, weapon=WeaponVec("2H Blunt", 30, 40, None, True)
)
STAR = make_item("star", {"PRIMARY"}, stats={"WIS": 14, "MANA": 56}, weapon=WeaponVec("1H Blunt", 10, 30, None, False))
CLOAK = make_item("z-cloak", {"BACK"}, stats={"WIS": 30})


@pytest.mark.parametrize("setup", ["1h-shield", "2h", "dw", "stick"])
def test_a_two_hander_that_lists_the_off_hand_has_no_column_there_in_any_setup(setup):
    milp = build_milp(profile(weights={"HP": 1}), [STAFF, SWORD, DAGGER, SHIELD, LAMP], setup, None, OPT)
    assert ("SECONDARY", "staff") not in milp.index
    assert (("PRIMARY", "staff") in milp.index) == (setup in ("2h", "stick"))
    assert ("BACK", "staff") in milp.index  # the groups it can stand in keep their columns
    # the rest of the off hand is as the setup says
    assert {k for g, k in milp.colmap.values() if g == "SECONDARY"} == {
        "1h-shield": {"shield"}, "2h": set(), "dw": {"sword", "dagger"}, "stick": {"sword", "dagger", "shield", "lamp"},
    }[setup]


def test_a_two_hander_that_lists_the_off_hand_is_not_worn_there_next_to_a_one_hander():
    # a staff that lists SECONDARY used to end up in the off hand beside a one-hander in the main hand (stick setup)
    prof = profile(weights={"MANA": 1, "HP": 1})
    items = [STAFF, STAR, CLOAK]
    result = check_instance(Instance("off hand", prof, items, STICK, None, 0, any_rule="explicit"))
    assert result.ok, result.message
    _, groups, _, exact = solve(prof, items)
    assert keys(groups, "SECONDARY") == [] and keys(groups, "PRIMARY") == ["star"] and keys(groups, "BACK") == ["z-cloak"]
    assert exact == evaluate(prof, kit_from_groups(groups)).F


def hand_columns(milp):
    return {(g, k): milp.c[col] for (g, k), col in milp.index.items() if g in ("PRIMARY", "SECONDARY")}


def test_weapon_columns_carry_the_damage_index_of_the_weapons_module():
    # dmg + bonus over delay times (1 + haste); the bonus is the primary hand's; the off hand of dw takes the factor
    prof = profile(weights={"DMG": 2}, dw_factor=F(1, 2))
    milp = build_milp(prof, [SWORD, DAGGER], "dw", None, BuildOptions(any_rule="explicit", haste_assumed=50))
    cols = hand_columns(milp)
    assert cols == pytest.approx({
        ("PRIMARY", "sword"): 2 * F(35, 30) * F(3, 2), ("SECONDARY", "sword"): 2 * F(20, 30) * F(3, 2) * F(1, 2),
        ("PRIMARY", "dagger"): 2 * F(12, 20) * F(3, 2), ("SECONDARY", "dagger"): 2 * F(8, 20) * F(3, 2) * F(1, 2),
    }, rel=1e-12)
    for (group, key), value in cols.items():
        item = SWORD if key == "sword" else DAGGER
        assert value == pytest.approx(2 * weapons_module.damage_index(item, group.lower(), "dw", 50, dw_factor=F(1, 2)), rel=1e-12)
    # the single-hander setups score the primary hand only; the stick scores nothing; the two-hander has its own bonus
    one = hand_columns(build_milp(prof, [SWORD, SHIELD], "1h-shield", None, BuildOptions(any_rule="explicit", haste_assumed=50)))
    assert one == pytest.approx({("PRIMARY", "sword"): 2 * F(35, 30) * F(3, 2), ("SECONDARY", "shield"): 0.0}, rel=1e-12)
    two = hand_columns(build_milp(prof, HANDS, "2h", None, BuildOptions(any_rule="explicit", haste_assumed=0)))
    assert two == pytest.approx({("PRIMARY", "axe"): 2 * (40 + F(6875, 10000) * 50) / 60}, rel=1e-12)  # (the delay counts at most 50; T9: 0.6875 at level 50)
    stick = hand_columns(build_milp(prof, HANDS, "stick", None, BuildOptions(any_rule="explicit", haste_assumed=50)))
    assert stick and all(value == 0.0 for value in stick.values())


def test_a_heavy_damage_weight_decides_the_weapons_and_the_oracle_agrees():
    # the damage weight is hundreds of HP per index point: the weapon choice outweighs the stats of the other pieces
    prof = profile(weights={"DMG": 600, "AC": 3, "HP": 1}, dw_factor=F(4, 5))
    good = make_item("good", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("1H Slashing", 30, 30, None, False))
    weak = make_item("weak", {"PRIMARY", "SECONDARY"}, stats={"AC": 50, "HP": 80}, weapon=WeaponVec("1H Blunt", 5, 40, None, False))
    for setup in ("dw", "1h-shield"):
        milp, groups, _, exact = solve(prof, [good, weak, SHIELD], setup, haste_assumed=50)
        assert "good" in keys(groups, "PRIMARY"), setup
        assert exact == evaluate(prof, kit_from_groups(groups), setup=setup, haste_assumed=50).F
    _, groups, _, _ = solve(prof, [good, weak], "dw", haste_assumed=50)
    assert keys(groups, "PRIMARY") == ["good"] and keys(groups, "SECONDARY") == ["good"]  # two copies of the same weapon


def test_a_weapon_in_an_any_slot_scores_its_stats_only():
    prof = profile(weights={"DMG": 5, "ATK": 1})
    stick = make_item("club", {"ANY"}, stats={"ATK": 7}, weapon=WeaponVec("1H Blunt", 30, 30, None, False))
    milp = build_milp(prof, [stick], STICK, None, OPT)
    assert milp.c[milp.index[("ANY", "club")]] == pytest.approx(7.0)


def test_the_assumed_haste_defaults_to_the_attainable_haste_of_the_pool():
    boots = make_item("boots", {"FEET"}, haste=35)
    cap = profile(buff_totals={"HASTE": 30}, haste_cap=75, weights={"DMG": 1})
    assert build_milp(cap, [boots], STICK, None, OPT).haste_assumed == 65
    capped = profile(buff_totals={"HASTE": 50}, haste_cap=75)
    assert build_milp(capped, [boots], STICK, None, OPT).haste_assumed == 75
    with_buff = make_buffset(optional=[make_buff(1, haste=25)])
    assert build_milp(profile(haste_cap=75), [boots], STICK, with_buff, OPT).haste_assumed == 60
    assert build_milp(cap, [boots], STICK, None, BuildOptions(any_rule="explicit", haste_assumed=12)).haste_assumed == 12


# ---- haste: the headroom clamps at zero --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spell, cap, worn, counted",
    [(45, 40, 30, 40), (40, 75, 50, 75), (40, 75, 20, 60), (75, 75, 10, 75), (0, 75, 90, 75), (0, 75, 0, 0)],
)
def test_worn_haste_counts_up_to_the_headroom_and_a_spell_over_the_cap_leaves_none(spell, cap, worn, counted):
    prof = profile(weights={"HASTE": 2}, buff_totals={"HASTE": spell}, haste_cap=cap)
    milp, groups, _, exact = solve(prof, [make_item("h", {"HEAD"}, haste=worn)] if worn else [])
    assert exact == 2 * counted == evaluate(prof, kit_from_groups(groups)).F


@pytest.mark.parametrize(
    "spell, cap, worn, counted",
    [(0, 85, 0, 10), (45, 85, 40, 85), (20, 85, 30, 60), (45, 75, 40, 75), (0, 85, 25, 35), (80, 85, 30, 85), (70, 75, 20, 75)],
)
def test_unbound_alacrity_adds_its_haste_to_the_spell_haste_and_the_room_follows(spell, cap, worn, counted):
    # the Monk's 10 haste stacks with the spell haste and the best worn piece, and the cap cuts the sum
    prof = profile(weights={"HASTE": 2}, buff_totals={"HASTE": spell} if spell else {}, haste_cap=cap, haste_bonus=10)
    _, groups, _, exact = solve(prof, [make_item("h", {"HEAD"}, haste=worn)] if worn else [])
    assert exact == 2 * counted == evaluate(prof, kit_from_groups(groups)).F


def test_unbound_alacrity_shifts_every_spell_haste_choice_and_the_room_left_for_worn_haste():
    # 10 + 40 leaves room for 35 worn haste, 10 + 60 only for 15: 30 worn counts 30 under the first (80) and 15 under the second (85)
    prof = profile(weights={"HASTE": 2}, haste_cap=85, haste_bonus=10)
    buffset = make_buffset(optional=[make_buff(1, haste=40), make_buff(2, haste=60)], conflicts=[(1, 2)])
    _, groups, buffs, exact = solve(prof, [make_item("boots", {"FEET"}, haste=30)], STICK, buffset)
    assert buffs == (2,) and exact == 2 * 85 == evaluate(prof, kit_from_groups(groups), eval_totals(buffset, buffs)).F
    assert solve(prof, [], STICK, buffset)[3] == 2 * 70  # nothing worn: the better spell haste, 60, and the 10 on top


def test_the_assumed_haste_counts_unbound_alacrity_whether_the_profile_names_its_spell_haste_or_not():
    boots = make_item("boots", {"FEET"}, haste=35)
    always = profile(buff_totals={"HASTE": 30}, haste_cap=85, weights={"DMG": 1}, haste_bonus=10)
    assert build_milp(always, [boots], STICK, None, OPT).haste_assumed == 75  # 10 + 30 + 35
    capped = profile(buff_totals={"HASTE": 50}, haste_cap=85, haste_bonus=10)
    assert build_milp(capped, [boots], STICK, None, OPT).haste_assumed == 85
    with_buff = make_buffset(optional=[make_buff(1, haste=25)])
    assert build_milp(profile(haste_cap=85, haste_bonus=10), [boots], STICK, with_buff, OPT).haste_assumed == 70  # 10 + 25 + 35
    named = profile(haste_cap=85, haste_bonus=10)  # a profile that names its spell haste has the 10 in it already
    object.__setattr__(named, "spell_haste", 35)
    assert build_milp(named, [boots], STICK, with_buff, OPT).haste_assumed == 70


def test_spell_haste_over_the_cap_keeps_the_model_feasible_with_no_haste_from_gear():
    prof = profile(weights={"HASTE": 3, "HP": 1}, buff_totals={"HASTE": 45}, haste_cap=40)
    milp, groups, _, exact = solve(prof, [make_item("h", {"HEAD"}, haste=30, stats={"HP": 7})])
    assert keys(groups, "HEAD") == ["h"]
    assert exact == 3 * 40 + evaluate(prof, [None] * 22).parts["HP"] + 7


def test_only_the_best_worn_haste_counts_and_two_items_do_not_add():
    prof = profile(weights={"HASTE": 1}, haste_cap=75)
    items = [make_item("a", {"HEAD"}, haste=20), make_item("b", {"NECK"}, haste=25), make_item("c", {"BACK"}, haste=30)]
    _, _, _, exact = solve(prof, items)
    assert exact == 30


def test_a_spell_haste_buff_that_is_a_choice_counts_the_best_one_up_to_the_cap():
    prof = profile(weights={"HASTE": 1, "HP": 1}, haste_cap=75)
    fast = make_buff(1, haste=40)
    faster = make_buff(2, haste=60, HP=-2)
    buffset = make_buffset(optional=[fast, faster], conflicts=[(1, 2)])
    boots = make_item("boots", {"FEET"}, haste=30)
    _, _, buffs, exact = solve(prof, [boots], STICK, buffset)
    # buff 1: 40 + 30 worn = 70; buff 2: 60 + 15 of the 30 worn = 75, at a flat -2 HP: 73
    base = evaluate(prof, [None] * 22).F
    assert buffs == (2,) and exact == base + 75 - 2
    # two spell hastes that do not conflict are refused: the model counts the best only
    with pytest.raises(ValueError, match="haste"):
        build_milp(prof, [boots], STICK, make_buffset(optional=[fast, faster]), OPT)


@pytest.mark.parametrize(
    "worn, cap, counted", [(20, 75, 75), (50, 75, 75), (50, 85, 85), (0, 75, 60), (30, 75, 75), (10, 75, 70), (20, 85, 80)]
)
def test_two_conflicting_haste_buffs_the_better_total_wins_and_the_room_follows_the_choice(worn, cap, counted):
    # the 40 leaves room for 35 worn haste, the 60 only for 15: the spell haste is one of two constants, and so is the room
    prof = profile(weights={"HASTE": 2}, haste_cap=cap)
    buffset = make_buffset(optional=[make_buff(1, haste=40), make_buff(2, haste=60)], conflicts=[(1, 2)])
    items = [make_item("boots", {"FEET"}, haste=worn)] if worn else []
    _, groups, buffs, exact = solve(prof, items, STICK, buffset)
    assert exact == 2 * counted == evaluate(prof, kit_from_groups(groups), eval_totals(buffset, buffs)).F
    if worn != 50:  # at 50 both choices reach the cap
        assert buffs == (2,)


def test_a_haste_buff_beyond_the_cap_leaves_no_room_and_a_weaker_one_does_not_hurt():
    prof = profile(weights={"HASTE": 1, "HP": 1}, haste_cap=75)
    buffset = make_buffset(optional=[make_buff(1, haste=80, HP=-5), make_buff(2, haste=30)], conflicts=[(1, 2)])
    boots = make_item("boots", {"FEET"}, haste=60)
    _, groups, buffs, exact = solve(prof, [boots], STICK, buffset)
    # buff 1: 75 and no worn haste, -5 HP; buff 2: 30 + 45 of the 60 worn = 75, no cost: buff 2 is better by 5
    assert buffs == (2,) and exact == evaluate(prof, [None] * 22).F + 75


def test_an_always_on_haste_and_a_better_optional_one_count_the_best():
    always = make_buff(9, haste=30)
    better = make_buff(1, haste=50)
    buffset = make_buffset(always=[always], optional=[better])
    prof = profile(weights={"HASTE": 1}, haste_cap=75, buff_totals=eval_totals(buffset, ()))
    _, _, buffs, exact = solve(prof, [], STICK, buffset)
    assert buffs == (1,) and exact == 50


# ---- buffs ----------------------------------------------------------------------------------------------------


def test_conflicting_buffs_leave_the_better_choice_and_gear_moves_the_choice():
    # A: STA 30. B: HP 200. They conflict. A STA point is worth 9.4 HP below 255, so A = 282 HP and B = 200 HP.
    a, b = make_buff(1, STA=30), make_buff(2, HP=200)
    buffset = make_buffset(optional=[a, b], conflicts=[(1, 2)])
    prof = profile(weights={"HP": 1})
    _, _, buffs, exact = solve(prof, [], STICK, buffset)
    assert buffs == (1,)
    # the gear takes STA to 245: A's 30 points then cross the 255 knee and are worth 10 * 9.4 + 20 * 4.7 = 188 < 200
    sta = make_item("sta", {"HEAD"}, stats={"STA": 145})
    _, groups, buffs, exact = solve(prof, [sta], STICK, buffset)
    assert keys(groups, "HEAD") == ["sta"] and buffs == (2,)


def test_conflicts_that_no_clique_covers_still_get_their_pair_rows_and_a_limit_of_zero_means_no_buff():
    prof = profile(weights={"HP": 1})
    pair = make_buffset(optional=[make_buff(1, HP=100), make_buff(2, HP=90)], conflicts=[(1, 2)], cliques=())
    _, _, chosen, _ = solve(prof, [], STICK, pair)
    assert chosen == (1,)
    zero = make_buffset(optional=[make_buff(1, HP=100), make_buff(2, HP=90)], cardinality=0)
    _, _, chosen, exact = solve(prof, [], STICK, zero)
    assert chosen == () and exact == evaluate(prof, [None] * 22).F
    triple = make_buffset(optional=[make_buff(i, HP=10 * i) for i in (1, 2, 3)], conflicts=[(1, 2), (1, 3), (2, 3)], cliques=[(1, 2, 3)])
    _, _, chosen, _ = solve(prof, [], STICK, triple)
    assert chosen == (3,)


def test_a_built_model_is_well_formed_and_deterministic():
    for seed in range(80):
        inst = random_instance(random.Random(3000 + seed))
        args = (inst.profile, inst.items, inst.setup, inst.buffset, BuildOptions(**inst.options_kwargs()))
        milp, again = build_milp(*args), build_milp(*args)
        n, m = milp.num_cols, milp.num_rows
        assert milp.A.shape == (m, n) and milp.A.start[0] == 0 and milp.A.start[-1] == len(milp.A.index) == len(milp.A.value)
        assert np.all(np.diff(milp.A.start) >= 0) and (len(milp.A.index) == 0 or 0 <= milp.A.index.min() <= milp.A.index.max() < n)
        for r in range(m):
            row = milp.A.index[milp.A.start[r]:milp.A.start[r + 1]]
            assert len(set(row)) == len(row) and np.all(milp.A.value[milp.A.start[r]:milp.A.start[r + 1]] != 0)
        assert np.all(milp.row_lb <= milp.row_ub) and np.all(milp.col_lb <= milp.col_ub)  # no empty bounds
        assert np.all(np.isfinite(milp.c)) and np.isfinite(milp.const) and np.all(np.isfinite(milp.A.value))
        binary = (milp.integrality == 1) & (milp.col_ub == 1) & (milp.col_lb == 0)
        assert int(binary.sum()) >= sum(milp.info["binaries"].values()) - 0  # every counted binary is a 0/1 integer column
        assert len(set(milp.names)) == n == len(milp.names)
        assert all(milp.integrality[col] == 1 for col in milp.colmap) and set(milp.colmap) == {c for c, _, _ in milp.item_cols}
        for left, right in ((milp.c, again.c), (milp.A.value, again.A.value), (milp.row_ub, again.row_ub), (milp.col_ub, again.col_ub)):
            assert np.array_equal(left, right)
        assert milp.const == again.const and milp.names == again.names


def test_the_cardinality_row_limits_the_active_buffs():
    buffs = [make_buff(i, HP=10 * i) for i in (1, 2, 3, 4)]
    prof = profile(weights={"HP": 1})
    for limit in (None, 1, 2, 3):
        _, _, chosen, exact = solve(prof, [], STICK, make_buffset(optional=buffs, cardinality=limit))
        assert chosen == tuple(range(5 - (limit or 4), 5))  # the best ones: the highest ids carry the most HP


def test_buffs_that_push_a_resist_over_the_cap_count_only_up_to_it():
    prof = profile(weights={"SV": 1})
    gear = make_item("res", {"HEAD"}, sv={"FIRE": 970, "COLD": 100})  # (T4: the resist cap is 1000 a school)
    buffset = make_buffset(optional=[make_buff(1, FIRE=40, COLD=40), make_buff(2, FIRE=100)], conflicts=[(1, 2)])
    _, _, chosen, exact = solve(prof, [gear], STICK, buffset)
    # fire is over the cap with either buff (1010 and 1070 against 1000): cold decides it
    assert chosen == (1,) and exact == 1000 + 140


def test_the_profiles_buff_totals_must_be_the_always_on_buffs_of_the_buffset():
    buffset = make_buffset(always=[make_buff(9, STR=30)])
    with pytest.raises(ValueError, match="buff_totals"):
        build_milp(profile(weights={"ATK": 1}), [], STICK, buffset, OPT)
    build_milp(profile(weights={"ATK": 1}, buff_totals={"STR": 30}), [], STICK, buffset, OPT)


def test_buffs_enter_every_total_they_feed():
    buff = make_buff(1, STR=20, STA=30, AGI=10, DEX=12, WIS=15, INT=5, CHA=7, AC=25, HP=100, MANA=50, END=40, ATK=11,
                     HPREG=3, MANAREG=2, ENDREG=1, FIRE=30, COLD=20, MAGIC=10, POISON=5, DISEASE=15, haste=20)
    weights = {k: F(k.__len__(), 7) for k in ("HP", "MANA", "END", "AC", "ATK", "DEX", "HASTE", "CHA", "HPREG", "MANAREG", "ENDREG", "SV")}
    prof = profile(weights=weights, softcap=(300, 0.4), defense_cap=100, haste_cap=75)
    buffset = make_buffset(optional=[buff])
    _, _, chosen, exact = solve(prof, [], STICK, buffset)
    assert chosen == (1,)
    assert exact == evaluate(prof, [None] * 22, eval_totals(buffset, (1,))).F


# ---- exact breakpoints -----------------------------------------------------------------------------------------


def forced_value(prof, item, setup=STICK):
    """The model's value of the single-item kit {item} and the oracle's, with the item forced in."""
    return forced_values(prof, [item], setup)


def forced_values(prof, items, setup=STICK):
    """The model's value of the kit of ``items`` (each worn in the first group it lists) and the oracle's."""
    milp = build_milp(prof, items, setup, None, BuildOptions(any_rule="explicit", haste_assumed=0))
    for item in items:
        milp.col_lb[milp.index[(sorted(item.slots)[0], item.key)]] = 1
    res = solve_milp(milp)
    assert res.status == "optimal"
    exact = evaluate(prof, kit_from_groups(milp.decode(res.x).groups), setup=setup, haste_assumed=0).F
    return milp.const + res.objective, float(exact)


@pytest.mark.parametrize("sta", [-3, 0, 1, 154, 155, 156, 157, 158, 410, 411, 412, 600])
def test_sta_converts_exactly_around_its_two_breakpoints(sta):
    prof = profile(weights={"HP": 1}, naked={**NAKED_100, "STA": 100})
    model, oracle = forced_value(prof, make_item("sta", {"HEAD"}, stats={"STA": sta}))
    assert model == pytest.approx(oracle, rel=1e-12, abs=1e-9)


@pytest.mark.parametrize("gain", [-60, -1, 0, 1, 2, 3, 4, 5, 99, 100, 101, 400, 401, 402, 403, 404, 405, 800])
def test_the_end_average_converts_exactly_around_its_two_knees(gain):
    # A = (100 + 100 + 100 + 100 + gain) / 4: gain 4 makes 101; the knees sit at 100 and 201 (gain 404)
    prof = profile(weights={"END": 1})
    model, oracle = forced_value(prof, make_item("str", {"HEAD"}, stats={"STR": gain}))
    assert model == pytest.approx(oracle, rel=1e-12, abs=1e-9)


@pytest.mark.parametrize("wis", [-10, 0, 1, 99, 100, 101, 154, 155, 156, 200, 201, 410, 411, 412, 500])
def test_wis_converts_exactly_around_every_band(wis):
    prof = profile(weights={"MANA": 1}, naked={**NAKED_100, "WIS": 0})
    model, oracle = forced_value(prof, make_item("wis", {"HEAD"}, stats={"WIS": wis}))
    assert model == pytest.approx(oracle, rel=1e-12, abs=1e-9)


@pytest.mark.parametrize("dex", [-300, 0, 154, 155, 156, 410, 411, 412, 500])
def test_dex_cha_str_and_agi_stop_counting_at_510(dex):
    prof = profile(weights={"DEX": 1, "CHA": 1, "ATK": 1, "AC": 1})
    for stat in ("DEX", "CHA", "STR", "AGI"):
        model, oracle = forced_value(prof, make_item("t", {"HEAD"}, stats={stat: dex}))
        assert model == pytest.approx(oracle, rel=1e-12, abs=1e-9), stat


def test_totals_below_zero_are_worth_nothing_through_the_deficit_binary():
    prof = profile(weights={"HP": 1, "END": 1, "DEX": 1, "CHA": 1, "ATK": 1, "AC": 1})
    heavy = make_item("neg", {"HEAD"}, stats={k: -500 for k in "STR STA AGI DEX CHA".split()})
    model, oracle = forced_value(prof, heavy)
    assert model == pytest.approx(oracle, rel=1e-12, abs=1e-9)
    milp = build_milp(prof, [heavy], STICK, None, OPT)
    assert milp.info["binaries"]["deficit"] >= 1


def test_stacking_a_non_lore_ring_over_four_places_is_inside_the_reachable_range():
    # STA 230 + 4 * 10: the fourth ring crosses the knee at 255
    prof = profile(weights={"HP": 1}, naked={**NAKED_100, "STA": 230})
    ring = make_item("ring", {"FINGER", "ANY"}, stats={"STA": 10})
    milp, groups, _, exact = solve(prof, [ring], any_rule="explicit")
    assert keys(groups, "FINGER") == ["ring"] * 2 and keys(groups, "ANY") == ["ring"] * 2
    assert exact == evaluate(prof, kit_from_groups(groups)).F  # 270 is over the knee at 255: the curve reaches it


# ---- the best two pools --------------------------------------------------------------------------------------


HP_PAIR = {
    "HP": (PoolSpec("WAR", 25, 3.0), PoolSpec("SHD", 85, 2.0), PoolSpec("CLR", 5, 1.0)),
    "MANA": (),
    "END": POOLS["END"],
}  # +5: 30 + 3 s, 90 + 2 s and 10 + s: the first two cross at s = 60, but the third is always last
HP_FLIP = {
    "HP": (PoolSpec("WAR", 25, 3.0), PoolSpec("SHD", 85, 2.0), PoolSpec("CLR", 55, 2.5)),
    "MANA": (),
    "END": POOLS["END"],
}  # +5: 30 + 3 s, 90 + 2 s and 60 + 2.5 s meet at s = 60: below it SHD and CLR count, above it WAR and CLR


@pytest.mark.parametrize("sta, hp", [(40, 320), (59, 415), (60, 420), (61, 425), (150, 870)])
def test_two_hp_pools_that_cross_inside_the_best_pair_change_nothing(sta, hp):
    prof = profile(weights={"HP": 1}, naked={**NAKED_100, "STA": 0}, pools=HP_PAIR)
    model, oracle = forced_value(prof, make_item("sta", {"HEAD"}, stats={"STA": sta}))
    assert oracle == hp and model == pytest.approx(oracle, rel=1e-12)
    assert build_milp(prof, [make_item("sta", {"HEAD"}, stats={"STA": sta})], STICK, None, OPT).info["pools"]["HP"] == "fixed"


@pytest.mark.parametrize("sta, hp", [(40, 330), (59, F("415.5")), (60, 420), (61, F("425.5")), (150, 915)])
def test_the_best_two_hp_pools_flip_at_the_crossing(sta, hp):
    prof = profile(weights={"HP": 1}, naked={**NAKED_100, "STA": 0}, pools=HP_FLIP)
    model, oracle = forced_value(prof, make_item("sta", {"HEAD"}, stats={"STA": sta}))
    assert oracle == hp and model == pytest.approx(oracle, rel=1e-12)
    milp = build_milp(prof, [make_item("sta", {"HEAD"}, stats={"STA": sta})], STICK, None, OPT)
    # the meeting point at 60 lies inside the reachable range [0, sta] only when sta is above it
    assert milp.info["pools"]["HP"] == ("select" if sta > 60 else "fixed")


def test_a_pool_family_whose_order_cannot_change_uses_the_fixed_pair_without_binaries():
    prof = profile(weights={"HP": 1, "END": 1, "MANA": 1})
    milp = build_milp(prof, [make_item("sta", {"HEAD"}, stats={"STA": 50, "WIS": 20})], STICK, None, OPT)
    assert milp.info["pools"] == {"HP": "fixed", "MANA": "all", "END": "fixed"}
    assert milp.info["binaries"]["selection"] == 0


END_CROSSING = {
    "HP": POOLS["HP"], "MANA": (),
    "END": (PoolSpec("A", 0, 3.0), PoolSpec("B", 100, 2.0), PoolSpec("C", 400, 1.0)),
}  # 3c, 100 + 2c, 400 + c cross at c = 100, 200 and 300


def test_end_pools_with_two_crossings_choose_the_best_two_everywhere_in_the_range():
    prof = profile(weights={"END": 1}, pools=END_CROSSING, naked={k: 80 for k in NAKED_100})
    groups = ("HEAD", "NECK", "CHEST", "LEGS")
    # all four stats rise by g, so the average runs from 80 to 300 with the knees at 100 and 201 and the pool
    # crossings (converted 100, 200, 300) inside
    for gain in (0, 5, 19, 20, 21, 36, 39, 40, 41, 59, 60, 61, 100, 120, 121, 125, 150, 219, 220):
        stats = zip(groups, ("STR", "STA", "DEX", "AGI"))
        items = [make_item(f"g{n}", {g}, stats={stat: gain}) for n, (g, stat) in enumerate(stats)]
        model, oracle = forced_values(prof, items)
        assert model == pytest.approx(oracle, rel=1e-12, abs=1e-9), gain
    milp = build_milp(prof, items, STICK, None, OPT)
    assert milp.info["pools"]["END"] == "select"


def test_the_selection_bound_is_the_absolute_pool_value_not_a_delta():
    # CLR/WIZ/ENC-like mana pools with a large base: forcing z to the true best pair must lose nothing
    pools = {
        "HP": POOLS["HP"], "END": POOLS["END"],
        "MANA": (PoolSpec("CLR", 900, 4.5, "WIS"), PoolSpec("WIZ", 1500, 4.5, "INT"), PoolSpec("ENC", 900, 4.5, "INT")),
    }
    prof = profile(weights={"MANA": 1}, pools=pools)
    int_item = make_item("int", {"HEAD"}, stats={"INT": 110, "WIS": 20})
    milp = build_milp(prof, [int_item], STICK, None, OPT)
    assert milp.info["pools"]["MANA"] == "select"
    zs = {n: j for j, n in enumerate(milp.names) if n.startswith("pool.MANA.z.")}
    assert len(zs) == 3
    milp.col_lb[milp.index[("HEAD", "int")]] = 1
    # INT 210: WIZ and ENC are the best two; force exactly that pair
    for name, j in zs.items():
        milp.col_lb[j] = milp.col_ub[j] = 1.0 if name.endswith(("WIZ", "ENC")) else 0.0
    res = solve_milp(milp)
    assert res.status == "optimal"
    oracle = evaluate(prof, kit_from_groups(milp.decode(res.x).groups)).F
    assert milp.const + res.objective == pytest.approx(float(oracle), rel=1e-12)
    assert oracle == (1500 + F("4.5") * fm.conv_mana(210)) + (900 + F("4.5") * fm.conv_mana(210))


def test_a_pool_that_is_always_last_is_never_selected():
    # a Berserker pool (995 + 4.25 c) crosses the 900 + 4.5 c pools at c = 380, inside [0, 700]
    ber, mnk, pal = (F(995), F("4.25")), (F(900), F("4.5")), (F(652), F("3.25"))
    spec = lambda pool, key="c": (*pool, key, F(0), F(700))  # noqa: E731
    # a third pool that is below both of them everywhere never counts: the pair is fixed although BER and MNK cross
    assert plan_top_pools([spec(ber), spec(mnk), spec(pal)]) == ("fixed", (0, 1))
    # two identical pools and the Berserker: which two count depends on c
    assert plan_top_pools([spec(ber), spec(mnk), spec(mnk)]) == ("select", (0, 1, 2))
    # two pools: both count
    assert plan_top_pools([spec(ber), spec(mnk)]) == ("all", (0, 1))
    assert plan_top_pools([spec(ber)]) == ("all", (0,)) and plan_top_pools([]) == ("none", ())
    # pools on different inputs are compared on the boxes of their ranges
    apart = [(F(900), F(1), "w", F(0), F(10)), (F(1500), F(2), "i", F(0), F(10)), (F(0), F(1), "x", F(0), F(10))]
    assert plan_top_pools(apart) == ("fixed", (0, 1))
    overlap = [(F(900), F(1), "w", F(0), F(700)), (F(1500), F(2), "i", F(0), F(10)), (F(1200), F(1), "x", F(0), F(10))]
    assert plan_top_pools(overlap)[0] == "select"
    # three lines meeting at s = 60: a change of the best two only once the range goes past it
    meet = lambda hi: [(F(30), F(3), "s", F(0), F(hi)), (F(90), F(2), "s", F(0), F(hi)), (F(60), F("2.5"), "s", F(0), F(hi))]  # noqa: E731
    assert plan_top_pools(meet(60)) == ("fixed", (1, 2))
    assert plan_top_pools(meet(61))[0] == "select"
    # two lines that cross while a third is always last: the pair stays
    assert plan_top_pools([(F(30), F(3), "s", F(0), F(100)), (F(90), F(2), "s", F(0), F(100)), (F(10), F(1), "s", F(0), F(100))]) == (
        "fixed", (0, 1))


HP_NEGATIVE = {
    "HP": (PoolSpec("WAR", 295, 1.0), PoolSpec("SHD", 95, 2.0), PoolSpec("CLR", -405, 5.0)),
    "MANA": (),
    "END": POOLS["END"],
}  # +5: 300 + s, 100 + 2 s and -400 + 5 s: the last is below zero until s = 80 and passes the others at 167 and 175


def forced_with_decoy(prof, kept, decoy):
    """The model's value and the oracle's of the kit {kept}, with a decoy in the pool that nobody wears: it only widens
    the reachable range of the inputs, so that the pool families need their selection binaries."""
    milp = build_milp(prof, [kept, decoy], STICK, None, OPT)
    milp.col_lb[milp.index[(sorted(kept.slots)[0], kept.key)]] = 1
    res = solve_milp(milp)
    assert res.status == "optimal"
    groups = milp.decode(res.x).groups
    assert [i.key for g in groups.values() for i in g] == [kept.key]  # the decoy is not worn
    exact = evaluate(prof, kit_from_groups(groups), setup=STICK, haste_assumed=0).F
    return milp, milp.const + res.objective, exact


@pytest.mark.parametrize(
    "sta, hp",
    [(0, 400), (40, 520), (79, 637), (80, 640), (81, 643), (150, 850), (167, 902), (175, 950), (176, 956), (250, 1450)],
)
def test_a_pool_that_is_below_zero_and_not_selected_counts_as_zero_not_as_its_negative_value(sta, hp):
    # below s = 80 the third pool is negative and not one of the best two: the best two are 300 + s and 100 + 2 s, and
    # the negative pool adds nothing. The selection rows must not subtract it.
    prof = profile(weights={"HP": 1}, naked={**NAKED_100, "STA": 0}, pools=HP_NEGATIVE)
    decoy = make_item("decoy", {"NECK"}, stats={"STA": 250, "HP": -9000})
    milp, model, oracle = forced_with_decoy(prof, make_item("sta", {"HEAD"}, stats={"STA": sta}), decoy)
    assert milp.info["pools"]["HP"] == "select"
    assert oracle == hp and model == pytest.approx(float(oracle), rel=1e-12, abs=1e-9)


def test_forcing_the_pair_that_counts_leaves_the_negative_pool_out_of_the_sum():
    # at s = 0 the pools are 300, 100 and -400: force z to the true best pair (the first two); the third, not selected,
    # must be worth 0 whatever it would be worth if it were
    prof = profile(weights={"HP": 1}, naked={**NAKED_100, "STA": 0}, pools=HP_NEGATIVE)
    sta = make_item("sta", {"HEAD"}, stats={"STA": 250, "HP": -9000})
    milp = build_milp(prof, [sta], STICK, None, OPT)
    assert milp.info["pools"]["HP"] == "select"
    zs = {name.rsplit(".", 1)[1]: j for j, name in enumerate(milp.names) if name.startswith("pool.HP.z.")}
    assert sorted(zs) == ["CLR", "SHD", "WAR"]
    for cls, j in zs.items():
        milp.col_lb[j] = milp.col_ub[j] = 0.0 if cls == "CLR" else 1.0
    res = solve_milp(milp)
    assert res.status == "optimal"
    groups = milp.decode(res.x).groups
    assert groups == {}  # the item costs 9000 hit points: not worn
    assert evaluate(prof, kit_from_groups(groups)).F == 400
    assert milp.const + res.objective == pytest.approx(400.0, rel=1e-12)


def negative_pool_instance(seed):
    """A small random instance on the pool table HP_NEGATIVE: STA runs from the negative region to past the crossings,
    and armor class pulls the best kit back down. The best kit often has a total STA below 80."""
    rng = random.Random(seed)
    prof = profile(
        weights={"HP": 1, "AC": rng.choice((6, 12, 24))}, naked={**NAKED_100, "STA": rng.choice((0, 10, 30, 60))},
        pools=HP_NEGATIVE, softcap=(10 ** 6, 0.5),
    )
    groups = rng.sample(["HEAD", "NECK", "CHEST", "LEGS", "ARMS", "WAIST"], rng.randint(3, 5))
    items = []
    for g in groups:
        for _ in range(rng.randint(1, 2)):
            stats = {"STA": rng.choice((-40, 0, 20, 60, 120, 250)), "AC": rng.choice((-60, -20, 0, 10, 40))}
            if rng.random() < 0.4:
                stats["HP"] = rng.choice((-200, 80, 150))
            items.append(make_item(f"i{len(items):02d}", {g}, stats=stats, lore=rng.random() < 0.2))
    return Instance(f"negative pool {seed}", prof, items, STICK, None, 0, any_rule="explicit")


def test_the_brute_force_agrees_with_a_pool_that_is_negative_over_part_of_its_range():
    # armor class (+40) is worth more than the hit points of the 250 stamina that would lift the third pool above zero,
    # so the best kit sits at a stamina of 0, where that pool is -400 and not one of the best two
    prof = profile(weights={"HP": 1, "AC": 12}, naked={**NAKED_100, "STA": 0}, pools=HP_NEGATIVE, softcap=(10 ** 6, 0.5))
    items = [make_item("sta-big", {"HEAD"}, stats={"STA": 250, "AC": -100}), make_item("ac-chest", {"CHEST"}, stats={"AC": 40})]
    inst = Instance("negative pool", prof, items, STICK, None, 0, any_rule="explicit")
    assert build_milp(prof, items, STICK, None, OPT).info["pools"]["HP"] == "select"
    result = check_instance(inst)
    assert result.ok, result.message
    milp, groups, _, _ = solve(prof, items)
    assert keys(groups, "CHEST") == ["ac-chest"] and keys(groups, "HEAD") == []


@pytest.mark.parametrize("seed", range(80))
def test_random_instances_with_a_negative_pool_agree_with_the_brute_force(seed):
    result = check_instance(negative_pool_instance(seed))
    assert result.ok, f"seed {seed}: {result.message}"


def test_data_invariant_which_pool_families_need_selection_binaries_at_levels_50_and_55():
    # Not an assumption: computed from derived/client/basedata.json over every trio. At level 50 base_hp / hp_fac is
    # 300 for every class (to the rounding of the factor at 55), so the HP lines never cross at a stat of 0 or more.
    from itertools import combinations

    classes = "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER".split()
    mana_classes = {c for c in classes if TABLES.basedata[(c, 50)]["mana"] > 0}
    for level in (50, 55):
        select = {"HP": set(), "MANA": set(), "END": set()}
        full = (F(0), fm.conv_mana(510))
        for trio in combinations(classes, 3):
            pools = fm.pools_for(trio, level, TABLES)
            plans = {
                "HP": [(5 + q.base, q.fac, "s", F(0), F(765, 2)) for q in pools["HP"]],
                "END": [(q.base, q.fac, "c", F(0), fm.conv_end(510)) for q in pools["END"]],
                "MANA": [(q.base, q.fac, q.stat, *full) for q in pools["MANA"]],
            }
            for family, specs in plans.items():
                if plan_top_pools(specs)[0] == "select":
                    select[family].add(trio)
        assert select["HP"] == set()
        assert select["END"] == {("WAR", "MNK", "BER"), ("WAR", "ROG", "BER"), ("MNK", "ROG", "BER")}
        stat_of = {c: ("WIS" if c in "PAL RNG BST CLR SHM DRU".split() else "INT") for c in mana_classes}
        mixed = {
            trio for trio in combinations(classes, 3)
            if set(trio) <= mana_classes and len({stat_of[c] for c in trio}) == 2
        }
        assert select["MANA"] == mixed and len(mixed) == 180  # the 180 trios of three mana classes on both stats


# ---- curves ------------------------------------------------------------------------------------------------------


def test_a_steeper_later_segment_stays_empty_while_an_earlier_one_is_not_full():
    # the best kit has an END average of 40, below the knee at 100, while decoys that nobody wears put the reachable
    # range past the knee at 201: the segment beyond 201 (slope 1.25, steeper than the first) must stay empty
    prof = profile(weights={"AC": 4, "END": 1, "HP": 1}, softcap=(10 ** 6, 0.5))
    bad = make_item("bad", {"CHEST"}, stats={"AC": 300, "STR": -60, "STA": -60, "DEX": -60, "AGI": -60})
    stats = zip(("HEAD", "NECK", "BACK", "LEGS"), ("STR", "STA", "DEX", "AGI"))
    decoys = [make_item(f"d{n}", {g}, stats={stat: 400, "HP": -9000}) for n, (g, stat) in enumerate(stats)]
    inst = Instance("gate", prof, [bad] + decoys, STICK, None, 0, any_rule="explicit")
    result = check_instance(inst)
    assert result.ok, result.message
    milp = build_milp(prof, inst.items, STICK, None, OPT)
    assert milp.info["binaries"]["ordering"] >= 1
    res = solve_milp(milp)
    assert keys(milp.decode(res.x).groups, "CHEST") == ["bad"] and len(milp.decode(res.x).groups) == 1


def test_a_curve_whose_slope_rises_gets_ordering_binaries_and_a_concave_one_does_not():
    rising = profile(weights={"MANA": 1}, bands={"breaks": [100], "slopes": [1, 3]}, naked={**NAKED_100, "WIS": 60})
    wis = make_item("wis", {"HEAD"}, stats={"WIS": 90})
    milp = build_milp(rising, [wis], STICK, None, OPT)
    assert milp.info["binaries"]["ordering"] >= 1
    model, oracle = forced_value(rising, wis)
    assert model == pytest.approx(oracle, rel=1e-12)
    concave = profile(weights={"MANA": 1}, bands={"breaks": [100], "slopes": [3, 1]}, naked={**NAKED_100, "WIS": 60})
    assert build_milp(concave, [wis], STICK, None, OPT).info["binaries"]["ordering"] == 0
    # a curve laid out only above its rising knee needs no binary at all
    above = profile(weights={"MANA": 1}, bands={"breaks": [100], "slopes": [1, 3]}, naked={**NAKED_100, "WIS": 120})
    assert build_milp(above, [wis], STICK, None, OPT).info["binaries"]["ordering"] == 0


def test_an_empty_pool_is_optimal_and_worth_the_naked_character():
    prof = profile(weights={"HP": 1, "AC": 2, "END": 1, "HASTE": 1}, buff_totals={"HASTE": 10, "HP": 25})
    for items in ([], [make_item("x", {"AMMO"}, stats={"HP": 10})]):
        milp = build_milp(prof, items, STICK, None, OPT)
        res = solve_milp(milp)
        assert res.status == "optimal" and milp.decode(res.x).groups == {}
        assert milp.const + res.objective == pytest.approx(float(evaluate(prof, [None] * 22).F), rel=1e-12)


def test_a_pool_whose_hand_items_are_all_excluded_by_the_setup_is_the_naked_character():
    prof = profile(weights={"HP": 1, "DMG": 4})
    milp, groups, _, exact = solve(prof, [AXE, SHIELD], "dw")
    assert groups == {} and exact == evaluate(prof, [None] * 22).F


# ---- the Monk weight bins ----------------------------------------------------------------------------------------


def monk_profile(kind, placement, **changes):
    curve = fm.monk_curve(TABLES.rules, 50, full_until=34 if kind == "alt" else None)
    return make_profile(
        ("WAR", "MNK", "ROG"), "HUM", {"AC": 4}, monk=curve, placement={"monk": placement, "iksar": "top"},
        softcap=(300, F(1, 2)), **changes,
    )


@pytest.mark.parametrize("placement", ["top", "inside"])
@pytest.mark.parametrize("kind", ["stand_in", "alt"])
def test_the_monk_bonus_is_exact_at_every_whole_stone_and_both_edges_of_each(kind, placement):
    prof = monk_profile(kind, placement)
    for stones in range(0, 46):
        for tenths in (0, 9):
            weight = 10 * stones + tenths
            item = make_item("heavy", {"CHEST"}, stats={"AC": 40}, weight10=weight)
            model, oracle = forced_value(prof, item)
            assert model == pytest.approx(oracle, rel=1e-12, abs=1e-9), (stones, tenths)


@pytest.mark.parametrize("placement", ["top", "inside"])
@pytest.mark.parametrize("kind", ["stand_in", "alt"])
def test_the_monk_bonus_agrees_with_the_brute_force_on_weight_only_pools_at_every_whole_stone(kind, placement):
    # one chest piece of the given weight and a modest armor class: the model may wear it or not, and the answer
    # must be the better of the two by the oracle, with the bonus (or the penalty) of exactly that many stones
    prof = monk_profile(kind, placement)
    for stones in range(0, 46):
        for tenths in (0, 9):
            item = make_item("heavy", {"CHEST"}, stats={"AC": 12}, weight10=10 * stones + tenths)
            inst = Instance("weight", prof, [item], STICK, None, 0, any_rule="explicit")
            result = check_instance(inst)
            assert result.ok, (stones, tenths, result.message)


def test_negative_weights_are_refused_before_a_model_is_built():
    with pytest.raises(ValueError, match="negative"):
        build_milp(SimpleNamespace(**{**{f.name: getattr(profile(), f.name) for f in dataclasses.fields(EvalProfile)},
                                      "weights": {"HP": -1}}), [], STICK, None, OPT)


def test_a_kit_at_exactly_32_stones_has_no_bonus_and_at_31_9_has_four():
    prof = monk_profile("stand_in", "top")
    for weight, bonus in ((320, 0), (319, 4)):
        item = make_item("w", {"CHEST"}, stats={"AC": 40}, weight10=weight)
        milp = build_milp(prof, [item], STICK, None, OPT)
        milp.col_lb[milp.index[("CHEST", "w")]] = 1
        res = solve_milp(milp)
        got = evaluate(prof, kit_from_groups(milp.decode(res.x).groups))
        assert got.totals["sheet"]["monk_bonus"] == bonus
        assert milp.const + res.objective == pytest.approx(float(got.F), rel=1e-12)


def test_weights_spread_over_several_items_add_up_in_the_bins():
    prof = monk_profile("stand_in", "top")
    items = [make_item(f"p{n}", {g}, stats={"AC": 10}, weight10=w) for n, (g, w) in enumerate(
        [("HEAD", 55), ("CHEST", 120), ("LEGS", 90), ("FEET", 33), ("ARMS", 77)])]
    for subset in ([0], [0, 1], [0, 1, 2, 3], [0, 1, 2, 3, 4]):
        chosen = [items[i] for i in subset]
        milp = build_milp(prof, items, STICK, None, OPT)
        for n in range(5):
            milp.col_ub[milp.index[(sorted(items[n].slots)[0], items[n].key)]] = 1.0 if n in subset else 0.0
            milp.col_lb[milp.index[(sorted(items[n].slots)[0], items[n].key)]] = 1.0 if n in subset else 0.0
        res = solve_milp(milp)
        oracle = evaluate(prof, kit_from_groups(milp.decode(res.x).groups)).F
        assert milp.const + res.objective == pytest.approx(float(oracle), rel=1e-12)


def test_a_pool_that_cannot_leave_the_first_stones_has_no_weight_bins():
    prof = monk_profile("stand_in", "top")
    light = [make_item(f"l{n}", {g}, stats={"AC": 10}, weight10=1) for n, g in enumerate(["HEAD", "CHEST", "LEGS"])]
    milp = build_milp(prof, light, STICK, None, OPT)
    assert milp.info["binaries"]["monk"] == 0  # at +10 every piece weighs a tenth of a stone: the bonus is always full
    heavy = [make_item("h", {"CHEST"}, stats={"AC": 10}, weight10=400)]
    assert build_milp(prof, heavy, STICK, None, OPT).info["binaries"]["monk"] > 5


def test_the_iksar_constant_sits_on_top_or_inside_the_cap():
    for placement in ("top", "inside"):
        prof = make_profile(
            ("WAR", "CLR", "ENC"), "IKS", {"AC": 4}, iksar_ac=35, softcap=(300, F(1, 2)),
            placement={"monk": "top", "iksar": placement},
        )
        item = make_item("ac", {"CHEST"}, stats={"AC": 300})
        model, oracle = forced_value(prof, item)
        assert model == pytest.approx(oracle, rel=1e-12)


# ---- the sheet ---------------------------------------------------------------------------------------------------


def test_the_off_hand_shield_raises_the_cap_and_a_shield_in_an_any_slot_does_not():
    prof = profile(weights={"AC": 4}, softcap=(400, F(1, 2)))
    chest = make_item("chest", {"CHEST"}, stats={"AC": 450})
    in_hand = make_item("shield", {"SECONDARY"}, stats={"AC": 30}, shield=True)
    stuck = make_item("any-shield", {"ANY"}, stats={"AC": 30}, shield=True)
    _, groups, _, exact = solve(prof, [chest, in_hand])
    assert keys(groups, "SECONDARY") == ["shield"]
    off_hand = evaluate(prof, kit_from_groups({"CHEST": [chest], "SECONDARY": [in_hand]})).F
    in_any = evaluate(prof, kit_from_groups({"CHEST": [chest], "ANY": [stuck]})).F
    assert off_hand > in_any and exact == off_hand
    model, oracle = forced_value(prof, stuck)
    assert model == pytest.approx(oracle, rel=1e-12)


@pytest.mark.parametrize("rate", [0, F(1, 3), 1])
def test_the_sheet_is_exact_below_at_and_past_the_cap_for_any_rate(rate):
    prof = profile(weights={"AC": 3}, softcap=(300, rate), defense_cap=60, buff_totals={"AC": 40}, cs_pct=5, pe_pct=2)
    for ac in (0, 100, 190, 191, 192, 400, 800):
        model, oracle = forced_value(prof, make_item("ac", {"CHEST"}, stats={"AC": ac, "AGI": 10}))
        assert model == pytest.approx(oracle, rel=1e-12), ac


# ---- flat terms --------------------------------------------------------------------------------------------------


def test_regen_counts_gear_to_its_cap_and_resists_to_theirs():
    prof = profile(weights={"HPREG": 2, "MANAREG": 3, "ENDREG": 4, "SV": 1, "SV_FIRE": F(1, 2)})
    items = [
        make_item("a", {"HEAD"}, stats={"HPREG": 20, "MANAREG": 10}, sv={"FIRE": 150, "COLD": 100}),
        make_item("b", {"BACK"}, stats={"HPREG": 15, "ENDREG": 40}, sv={"FIRE": 80, "MAGIC": -10}),
    ]
    milp, groups, _, exact = solve(prof, items)
    assert keys(groups, "HEAD") == ["a"] and keys(groups, "BACK") == ["b"]
    assert exact == evaluate(prof, kit_from_groups(groups)).F


def test_mana_is_worth_nothing_for_a_trio_without_a_mana_class_whatever_the_items_give():
    pools = {**POOLS, "MANA": ()}
    prof = profile(weights={"MANA": 3, "HP": 0}, pools=pools)
    milp, groups, _, exact = solve(prof, [make_item("m", {"HEAD"}, stats={"MANA": 500, "WIS": 90})])
    assert exact == 0 and milp.info["pools"]["MANA"] == "none"


def test_flat_hp_mana_end_and_atk_are_linear_terms():
    prof = profile(weights={"HP": 1, "MANA": 2, "END": 3, "ATK": 5})
    item = make_item("flat", {"HEAD"}, stats={"HP": 10, "MANA": 20, "END": 30, "ATK": 40})
    milp, groups, _, exact = solve(prof, [item])
    assert exact == evaluate(prof, [None] * 22).F + 10 + 40 + 90 + 200


# ---- inputs it refuses -------------------------------------------------------------------------------------------


def test_an_unknown_setup_and_unknown_stats_are_refused():
    with pytest.raises(ValueError, match="setup"):
        build_milp(profile(), [], "bow", None, OPT)
    with pytest.raises(ValueError, match="BOGUS"):
        build_milp(profile(), [make_item("x", {"HEAD"}, stats={"BOGUS": 1})], STICK, None, OPT)
    with pytest.raises(ValueError, match="any_rule"):
        BuildOptions(any_rule="some")
    with pytest.raises(ValueError, match="mutation"):
        BuildOptions(mutation="nothing")


def test_the_same_item_twice_is_refused():
    item = make_item("dup", {"HEAD"})
    with pytest.raises(ValueError, match="dup"):
        build_milp(profile(), [item, dataclasses.replace(item, name="again")], STICK, None, OPT)


# ---- the shape of a big model ---------------------------------------------------------------------------------


def test_a_realistic_pool_builds_a_model_of_the_expected_shape():
    rng = random.Random(5)
    groups = ["HEAD", "FACE", "EAR", "NECK", "SHOULDERS", "ARMS", "BACK", "WRIST", "HANDS", "FINGER", "CHEST", "LEGS", "FEET",
              "WAIST", "RANGE"]
    items = []
    for n in range(480):
        g = groups[n % len(groups)]
        stats = {k: rng.randint(1, 40) for k in rng.sample(["AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "HP", "MANA", "END"], 4)}
        items.append(make_item(f"p{n:03d}", {g}, stats=stats, lore=rng.random() < 0.15, weight10=rng.randint(1, 80),
                               haste=rng.choice((0, 0, 0, 15, 30))))
    weights = {k: F(1, 2) for k in ("HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "SV", "HPREG")}
    prof = make_profile(("PAL", "MNK", "BER"), "OGR", weights, softcap=(392, 0.33))
    milp = build_milp(prof, items, STICK, None, BuildOptions(any_rule="all"))
    assert milp.num_cols == len(milp.names) == milp.c.shape[0] == milp.integrality.shape[0]
    assert milp.A.shape == (milp.num_rows, milp.num_cols) and milp.A.start.shape[0] == milp.num_rows + 1
    assert len(milp.colmap) >= 480 and milp.info["binaries"]["monk"] > 0
    assert milp.num_rows < 400 and milp.num_cols < 1700
