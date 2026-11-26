"""Tests for the weight groups and the composed weight override of ``trioforge.model.roles``.

``weights_override(base, multipliers, custom, regen_T)`` is the one definition of how the slider positions, the custom
weights and the regen window compose:

* the **weight in effect** of each of the nine settable weights (HP AC MANA ATK DEX HASTE END CHA and the resists SV) is
  the custom value when there is one, else the role's own;
* a **slider** (x0.5, x1 or x2 on a group of ``WEIGHT_GROUPS``) multiplies the weights of its group *after* that, so a
  custom weight of 3 under ATK+HASTE x2 is worth 6;
* the weapon damage weight DMG follows the ATK weight in effect: it is the role's own DMG times (ATK in effect / own
  ATK), which is the rule value (450) times the ATK weight and the weapon factor of the build (the Tank 0.5, Melee damage 1, the
  casting builds 0); the ATK+HASTE slider scales it too;
* the three regen weights are ``10 ticks a minute x T x`` the weight in effect of what they return; ``regen_T`` None (or
  a T equal to the role's own) keeps the role's own derivation, so nothing moves; the regen slider scales them last;
* a weight on a currency the trio cannot reach (MANA without a mana pool) stays 0, together with MANAREG.

The tests write the definition out again with exact fractions (``oracle``), compare it with the function on random
compositions, and check the facts that make the composition order-free: the sliders are a last multiplication, T touches
only the regen weights, and a custom weight touches only itself and the weight derived from it.
"""

import copy
import itertools
import json
import math
import random
from fractions import Fraction
from pathlib import Path

import pytest

from trioforge.classes import CLASS_CODES
from trioforge.model import roles
from trioforge.model.formulas import SCHOOLS, WEIGHT_KEYS
from trioforge.model.profile import make_profile
from trioforge.model.roles import MULTIPLIERS, WEIGHT_GROUPS, weights_for, weights_override
from trioforge.model.tables import load as load_tables
from trioforge.rules import Rules
from trioforge.solver import robust

REPO = Path(__file__).resolve().parents[2]
TABLES = load_tables()
RULES = TABLES.rules
RAW = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))
TRIOS = list(itertools.combinations(CLASS_CODES, 3))
SAMPLE = [
    ("PAL", "MNK", "BER"), ("SHD", "CLR", "SHM"), ("WIZ", "MAG", "ENC"), ("WAR", "ROG", "BER"), ("CLR", "MNK", "ROG"),
]  # fmt: skip
MINUTES = RULES.get("regen.value_minutes")
GROUP_OF = {key: group for group, keys in WEIGHT_GROUPS.items() for key in keys}
REGEN = (("HPREG", "HP"), ("MANAREG", "MANA"), ("ENDREG", "END"))


def base_of(trio, role=None, rules=RULES):
    """The weights of a build of the trio (the first it is offered, unless one is named)."""
    return weights_for(trio, role or roles.roles_for(trio)[0], rules)


def every_role():
    for trio in TRIOS:
        for role in roles.roles_for(trio):
            yield trio, role


def q(x):
    """A number as the exact decimal it was written as (a float by its shortest text)."""
    return Fraction(repr(x)) if isinstance(x, float) else Fraction(x)


def oracle(base, multipliers=None, custom=None, regen_T=None, mana_reachable=None):
    """The definition of the module docstring, written again with fractions (no shared code with the module)."""
    b = {key: q(value) for key, value in base.items()}
    slider = {group: Fraction(1) for group in WEIGHT_GROUPS}
    slider.update({group: q(value) for group, value in (multipliers or {}).items()})
    mana = b.get("MANA", 0) > 0 if mana_reachable is None else mana_reachable
    effective = dict(b)
    given = {key: q(value) for key, value in (custom or {}).items()}
    if "SV" in given:
        for school in SCHOOLS:
            effective[f"SV_{school}"] = given["SV"]
        if "SV" in b:
            effective["SV"] = given["SV"]
    effective.update({key: value for key, value in given.items() if key != "SV"})
    if not mana:
        effective["MANA"] = Fraction(0)
    out = {}
    for key in effective:
        if key in ("DMG", "HPREG", "MANAREG", "ENDREG"):
            continue
        out[key] = effective[key] * slider[GROUP_OF[key]] if key in GROUP_OF else effective[key]
    if "DMG" in b:
        ratio = effective["ATK"] / b["ATK"] if b.get("ATK", 0) > 0 else Fraction(1)
        out["DMG"] = b["DMG"] * ratio * slider["ATK+HASTE"]
    minutes = None if regen_T is None else q(regen_T)
    for reg, resource in REGEN:
        if reg not in b:
            continue
        own = b[reg]
        resource_in_effect = effective.get(resource, Fraction(0))
        keeps_own = minutes is None or (
            own > 0 and abs(10 * minutes * b.get(resource, 0) - own) <= own / 10**12
        )
        if keeps_own:
            value = own * (resource_in_effect / b[resource]) if b.get(resource, 0) > 0 else own
        else:
            value = 10 * minutes * resource_in_effect
        out[reg] = value * slider["regen"]
    return {key: float(value) for key, value in out.items()}


# ---- the groups ----------------------------------------------------------------------------------------------------


def test_the_weight_groups_are_defined_once_in_roles_and_the_robustness_module_imports_them():
    assert robust.WEIGHT_GROUPS is WEIGHT_GROUPS is roles.WEIGHT_GROUPS
    assert "WEIGHT_GROUPS" in robust.__all__


def test_the_groups_are_the_five_key_weight_groups_in_the_order_of_the_variants():
    assert list(WEIGHT_GROUPS) == ["AC", "MANA", "ATK+HASTE", "SV", "regen"]
    assert WEIGHT_GROUPS["AC"] == ("AC",) and WEIGHT_GROUPS["MANA"] == ("MANA",)
    assert WEIGHT_GROUPS["ATK+HASTE"] == ("ATK", "HASTE", "DMG")
    assert WEIGHT_GROUPS["SV"] == ("SV", *(f"SV_{school}" for school in SCHOOLS))
    assert WEIGHT_GROUPS["regen"] == ("HPREG", "MANAREG", "ENDREG")


def test_the_groups_are_disjoint_and_hold_only_weights_the_evaluator_reads():
    keys = [key for group in WEIGHT_GROUPS.values() for key in group]
    assert len(keys) == len(set(keys)) and set(keys) <= WEIGHT_KEYS


def test_the_multipliers_are_the_three_slider_positions_and_the_variants_use_the_two_that_change_something():
    assert MULTIPLIERS == (0.5, 1, 2)
    assert robust.FACTORS == (0.5, 2)
    assert set(robust.FACTORS) | {1} == set(MULTIPLIERS)


# ---- what is refused -----------------------------------------------------------------------------------------------


BASE = base_of(("PAL", "MNK", "BER"), "tank")


@pytest.mark.parametrize("value", [0.7, 3, 4, 0, -1, -2, 0.25, 1.5, True, None, "2", float("nan"), float("inf"), [2]])
def test_only_the_three_discrete_multipliers_are_accepted(value):
    with pytest.raises(ValueError, match="multiplier"):
        weights_override(BASE, {"AC": value})


@pytest.mark.parametrize("value", [0.5, 1, 2, 1.0, 2.0, Fraction(1, 2), Fraction(2)])
def test_the_three_positions_are_accepted_in_any_numeric_form(value):
    result = weights_override(BASE, {"AC": value})
    assert result["AC"] == BASE["AC"] * float(value)


def test_half_one_and_double_give_exactly_half_the_weight_the_weight_and_twice_the_weight():
    half, same, double = (weights_override(BASE, {"ATK+HASTE": m}) for m in (0.5, 1, 2))
    for key in ("ATK", "HASTE", "DMG"):
        assert (half[key], same[key], double[key]) == (BASE[key] / 2, BASE[key], BASE[key] * 2)


@pytest.mark.parametrize("group", ["ac", "ATK", "HASTE", "DMG", "HP", "regen ", "", None, 3])
def test_a_slider_group_must_be_one_of_the_five(group):
    with pytest.raises(ValueError, match="group"):
        weights_override(BASE, {group: 2})


def test_the_multipliers_are_a_mapping_and_so_is_the_custom_table():
    for bad in ([("AC", 2)], "AC", 5):
        with pytest.raises(ValueError, match="multipliers"):
            weights_override(BASE, bad)
        with pytest.raises(ValueError, match="custom"):
            weights_override(BASE, {}, bad)


@pytest.mark.parametrize("key", ["DMG", "HPREG", "MANAREG", "ENDREG", "SV_CORRUPTION", "hp", "LUCK", "", None])
def test_a_custom_weight_must_be_one_of_the_settable_ones(key):
    with pytest.raises(ValueError, match="custom"):
        weights_override(BASE, {}, {key: 1})


@pytest.mark.parametrize(
    "value", [-0.1, -1, float("nan"), float("inf"), True, False, None, "3", [1], roles.CUSTOM_MAX + 1]
)
def test_a_custom_weight_is_a_number_from_0_to_the_maximum(value):
    with pytest.raises(ValueError, match="custom"):
        weights_override(BASE, {}, {"HP": value})


def test_the_ends_of_the_custom_range_are_allowed():
    assert weights_override(BASE, {}, {"HP": 0})["HP"] == 0
    assert weights_override(BASE, {}, {"HP": roles.CUSTOM_MAX})["HP"] == roles.CUSTOM_MAX


@pytest.mark.parametrize("minutes", [-1, -0.001, roles.REGEN_T_MAX + 1, float("nan"), float("inf"), True, "3", [3]])
def test_the_regen_window_is_a_number_of_minutes_from_0_to_the_maximum(minutes):
    with pytest.raises(ValueError, match="regen_T"):
        weights_override(BASE, {}, {}, minutes)


def test_the_ends_of_the_regen_range_are_allowed():
    assert weights_override(BASE, {}, {}, 0)["HPREG"] == 0
    assert weights_override(BASE, {}, {}, roles.REGEN_T_MAX)["HPREG"] == 10 * roles.REGEN_T_MAX * BASE["HP"]


@pytest.mark.parametrize(
    "bad",
    [{"LUCK": 1}, {"HP": -1}, {"HP": float("nan")}, {"HP": True}, {"HP": "1"}, [("HP", 1)], None, 3],
)
def test_the_base_weights_must_be_a_table_of_known_non_negative_numbers(bad):
    with pytest.raises(ValueError, match="base"):
        weights_override(bad, {}, {}, None)


def test_the_derived_weights_and_what_they_follow_are_named_for_the_browser():
    assert roles.DERIVED_KEYS == ("DMG", "HPREG", "MANAREG", "ENDREG") and roles.DAMAGE_FOLLOWS == "ATK"
    assert roles.REGEN_SOURCES == {"HPREG": "HP", "MANAREG": "MANA", "ENDREG": "END"}
    assert roles.MANA_KEYS == ("MANA", "MANAREG")
    assert set(roles.DERIVED_KEYS) <= set(BASE) and not set(roles.DERIVED_KEYS) & set(roles.CUSTOM_KEYS)
    for regen, resource in roles.REGEN_SOURCES.items():  # what weights_for derives, as the override derives it
        assert BASE[regen] == roles.TICKS_PER_MINUTE * MINUTES * BASE[resource]
    assert BASE["DMG"] == RULES.get("weapons.damage_weight") * BASE[roles.DAMAGE_FOLLOWS] * RULES.get("roles.weapon_factor")["tank"] == 600.75  # (the Tank's weapon factor is a half)


def test_the_bounds_are_the_ones_the_bundle_hands_to_the_browser():
    assert roles.CUSTOM_MAX == 1000 and roles.REGEN_T_MAX == 60 and roles.TICKS_PER_MINUTE == 10
    assert roles.REGEN_T_MATCH == Fraction(1, 10**12)
    assert set(roles.CUSTOM_KEYS) == {*roles.TEMPLATE_KEYS, *(f"SV_{school}" for school in SCHOOLS)}


# ---- the identity --------------------------------------------------------------------------------------------------


def test_with_nothing_asked_the_result_is_the_role_weights_to_the_last_digit_for_all_560_trios():
    count = 0
    for trio, role in every_role():
        base = weights_for(trio, role, RULES)
        assert weights_override(base, {}, {}, None) == base, (trio, role)
        assert weights_override(base) == base, (trio, role)
        count += 1
    assert count == 1394  # the builds of the 560 trios, the Archer left out (no pool): 274 + 210 + 525 + 161 + 224


def test_every_slider_at_1_no_custom_weights_and_the_default_window_change_nothing_exactly():
    ones = dict.fromkeys(WEIGHT_GROUPS, 1)
    for trio, role in every_role():
        base = weights_for(trio, role, RULES)
        assert weights_override(base, ones, {}, MINUTES) == base, (trio, role)
        assert weights_override(base, ones, {}, float(MINUTES)) == base, (trio, role)
        assert weights_override(base, ones, {}, Fraction(MINUTES)) == base, (trio, role)


def test_the_default_window_is_the_role_s_own_even_when_the_stored_weights_are_rounded_fractions():
    # a weight that a float cannot hold (a bundle of an earlier release stored the mean of templates, END = 17/60): 10 x 3 x its float is 8.499999999999998
    base = {**base_of(("SHD", "CLR", "SHM")), "END": 17 / 60, "ENDREG": 8.5}
    assert base["ENDREG"] == 8.5 and q(base["END"]) * 30 != q(base["ENDREG"])  # derived again from the float: 8.499...
    assert weights_override(base, {}, {}, MINUTES)["ENDREG"] == base["ENDREG"]


def test_a_window_within_a_part_in_a_trillion_of_the_role_s_own_is_the_role_s_own_and_a_hair_more_is_not():
    base = base_of(("PAL", "MNK", "BER"))
    assert weights_override(base, {}, {}, 3 * (1 + 1e-13)) == base
    assert weights_override(base, {}, {}, 3 * (1 - 1e-13)) == base
    moved = weights_override(base, {}, {}, 3 * (1 + 1e-9))
    assert moved["HPREG"] != base["HPREG"] and moved["HPREG"] == pytest.approx(base["HPREG"])


def test_the_result_is_a_new_dict_of_floats_and_the_inputs_are_left_alone():
    base = base_of(("PAL", "MNK", "BER"))
    frozen = copy.deepcopy(base)
    multipliers, custom = {"AC": 2, "regen": 0.5}, {"HP": 2, "SV": 1.25}
    given = (copy.deepcopy(multipliers), copy.deepcopy(custom))
    result = weights_override(base, multipliers, custom, 7)
    assert result is not base and base == frozen and (multipliers, custom) == given
    assert all(type(value) is float and math.isfinite(value) and value >= 0 for value in result.values())
    assert list(result) == list(base)  # the keys of the base, in the order of the base


# ---- worked examples -----------------------------------------------------------------------------------------------


def test_a_custom_weight_is_scaled_by_its_slider_and_the_damage_weight_follows_the_attack_weight():
    # Tank: ATK 2.67 and DMG 450 x 2.67 x 0.5 = 600.75 (the Tank's weapon factor is a half). Custom ATK 3 under ATK+HASTE x2 is an ATK of 6, and 225 x 6 = 1350 of DMG.
    result = weights_override(BASE, {"ATK+HASTE": 2}, {"ATK": 3}, None)
    assert result["ATK"] == 6 and result["DMG"] == 1350 == 450 * 0.5 * result["ATK"]
    assert result["HASTE"] == 3  # the role's own 1.5, doubled
    assert result["DMG"] == RULES.get("weapons.damage_weight") * RULES.get("roles.weapon_factor")["tank"] * result["ATK"]


def test_the_example_with_every_part_at_once():
    result = weights_override(
        BASE, {"ATK+HASTE": 2, "AC": 0.5, "regen": 2, "SV": 0.5, "MANA": 2}, {"ATK": 3, "HP": 2}, 60
    )
    assert result["ATK"] == 6 and result["HASTE"] == 3 and result["DMG"] == 1350
    assert result["AC"] == 6 and result["MANA"] == pytest.approx(0.3)
    assert all(result[f"SV_{school}"] == 0.2 for school in SCHOOLS)
    assert result["HP"] == 2 and result["DEX"] == BASE["DEX"] and result["END"] == BASE["END"]
    # regen: 10 x 60 x the weight in effect (the slider on MANA does not feed MANAREG), then the regen slider x2
    assert result["HPREG"] == 10 * 60 * 2 * 2 == 2400
    assert result["MANAREG"] == 10 * 60 * 0.15 * 2 == 180
    assert result["ENDREG"] == 10 * 60 * 0.5 * 2 == 600


def test_a_custom_resource_weight_moves_its_regen_weight_with_it_while_the_window_is_the_role_s_own():
    result = weights_override(BASE, {}, {"HP": 2, "END": 1}, None)
    assert result["HPREG"] == BASE["HPREG"] * 2 == 60
    assert result["ENDREG"] == BASE["ENDREG"] * 2 == 30
    assert result["MANAREG"] == BASE["MANAREG"]


def test_the_regen_window_sets_the_value_of_a_regen_point_to_ten_ticks_a_minute_times_the_window():
    result = weights_override(BASE, {}, {}, 1.5)
    assert result["HPREG"] == 10 * 1.5 * BASE["HP"] == 15
    assert result["MANAREG"] == 10 * 1.5 * BASE["MANA"] and result["ENDREG"] == 10 * 1.5 * BASE["END"]
    assert {k: v for k, v in result.items() if "REG" not in k} == {k: v for k, v in BASE.items() if "REG" not in k}
    assert not any(weights_override(BASE, {}, {}, 0)[key] for key in ("HPREG", "MANAREG", "ENDREG"))


def test_the_caster_stick_scores_no_damage_whatever_the_attack_weight():
    caster = base_of(("SHD", "CLR", "SHM"), "caster")
    assert caster["DMG"] == 0
    assert weights_override(caster, {"ATK+HASTE": 2}, {"ATK": 50}, None)["DMG"] == 0


def test_a_build_with_a_weapon_factor_keeps_the_ratio_of_its_own_damage_to_its_attack_weight():
    tank = base_of(("SHD", "CLR", "SHM"), "tank")
    assert tank["DMG"] == pytest.approx(450 * 2.67 * 0.5) and tank["ATK"] == pytest.approx(2.67)
    result = weights_override(tank, {}, {"ATK": 2}, None)
    assert result["DMG"] == pytest.approx(450 * 0.5 * 2) and result["DMG"] < 450 * 2  # the factor of a half stays: a custom attack weight of 2 is 225 a point
    melee = base_of(("PAL", "MNK", "BER"), "melee")
    assert weights_override(melee, {}, {"ATK": 5}, None)["DMG"] == pytest.approx(450 * 5)
    shield = base_of(("SHD", "CLR", "SHM"), "shield")
    assert shield["DMG"] == 0 and weights_override(shield, {"ATK+HASTE": 2}, {"ATK": 50}, None)["DMG"] == 0


def test_a_trio_with_no_mana_class_keeps_mana_and_mana_regen_at_zero():
    melee = base_of(("WAR", "ROG", "BER"), "tank")
    assert melee["MANA"] == 0 and melee["MANAREG"] == 0
    for minutes in (None, 3, 60):
        result = weights_override(melee, {"MANA": 2, "regen": 2}, {"MANA": 9}, minutes)
        assert result["MANA"] == 0 and result["MANAREG"] == 0


def test_the_caller_can_say_whether_mana_is_reachable():
    base = base_of(("PAL", "MNK", "BER"), "tank")
    result = weights_override(base, {}, {"MANA": 8}, 3, mana_reachable=False)
    assert result["MANA"] == 0 and result["MANAREG"] == 0
    assert weights_override(base, {}, {"MANA": 8}, 3, mana_reachable=True)["MANAREG"] == 10 * 3 * 8
    none_ = base_of(("WAR", "ROG", "BER"), "tank")
    forced = weights_override(none_, {}, {"MANA": 8}, 3, mana_reachable=True)
    assert forced["MANA"] == 8 and forced["MANAREG"] == 240


def test_a_custom_weight_can_switch_on_a_weight_the_role_does_not_have():
    caster = base_of(("WIZ", "MAG", "ENC"))
    assert caster["HASTE"] == 0
    assert weights_override(caster, {"ATK+HASTE": 2}, {"HASTE": 1.5})["HASTE"] == 3
    assert weights_override(caster, {}, {"HP": 0})["HPREG"] == 0


def test_a_custom_resist_weight_sets_all_five_schools_and_a_school_of_its_own_beats_it():
    result = weights_override(BASE, {}, {"SV": 0.25, "SV_FIRE": 1})
    assert result["SV_FIRE"] == 1 and all(result[f"SV_{s}"] == 0.25 for s in SCHOOLS if s != "FIRE")
    assert weights_override(BASE, {}, {"SV_FIRE": 1, "SV": 0.25}) == result  # the order of the table is no matter
    assert weights_override(BASE, {"SV": 2}, {"SV": 0.25})["SV_COLD"] == 0.5


def test_a_base_with_a_bare_sv_weight_is_set_and_scaled_like_the_five_schools():
    base = {"HP": 1, "AC": 2, "SV": 0.4}
    result = weights_override(base, {"SV": 2}, {"SV": 0.5})
    assert result["SV"] == 1 and result["SV_FIRE"] == 1 and result["HP"] == 1
    assert weights_override(base, {"SV": 2}, {}) == {"HP": 1.0, "AC": 2.0, "SV": 0.8}


# ---- the composition is order-free ---------------------------------------------------------------------------------


def random_composition(rng):
    multipliers = {g: rng.choice((0.5, 1, 2)) for g in rng.sample(list(WEIGHT_GROUPS), rng.randint(0, 5))}
    custom = {
        key: rng.choice((0, 1, 2, 3.5, round(rng.uniform(0, 40), 3), round(rng.uniform(0, 3), 2)))
        for key in rng.sample(list(roles.CUSTOM_KEYS), rng.randint(0, 5))
    }
    minutes = rng.choice((None, None, 0, 0.5, 1.5, 3, 3.0, 7, 60, Fraction(7, 3)))
    return multipliers, custom, minutes


def test_the_function_equals_the_definition_on_500_random_compositions_of_all_roles():
    rng = random.Random(1014)
    pairs = [(trio, role) for trio in SAMPLE for role in roles.roles_for(trio)]
    for _ in range(500):
        trio, role = rng.choice(pairs)
        base = base_of(trio, role)
        multipliers, custom, minutes = random_composition(rng)
        assert weights_override(base, multipliers, custom, minutes) == oracle(base, multipliers, custom, minutes), (
            trio, role, multipliers, custom, minutes,
        )  # fmt: skip


def test_the_order_of_the_tables_never_matters():
    rng = random.Random(7)
    for _ in range(100):
        trio = rng.choice(SAMPLE)
        base = base_of(trio, rng.choice(roles.roles_for(trio)))
        multipliers, custom, minutes = random_composition(rng)
        expected = weights_override(base, multipliers, custom, minutes)
        for _ in range(4):
            shuffled_m = dict(rng.sample(list(multipliers.items()), len(multipliers)))
            shuffled_c = dict(rng.sample(list(custom.items()), len(custom)))
            shuffled_b = dict(rng.sample(list(base.items()), len(base)))
            result = weights_override(shuffled_b, shuffled_m, shuffled_c, minutes)
            assert result == expected and sorted(result) == sorted(expected)


def test_the_sliders_are_a_last_multiplication_so_they_commute_with_custom_weights_and_the_window():
    rng = random.Random(21)
    for _ in range(150):
        trio = rng.choice(SAMPLE)
        base = base_of(trio, rng.choice(roles.roles_for(trio)))
        multipliers, custom, minutes = random_composition(rng)
        plain = weights_override(base, {}, custom, minutes)
        full = weights_override(base, multipliers, custom, minutes)
        for key, value in plain.items():
            factor = q(multipliers.get(GROUP_OF[key], 1)) if key in GROUP_OF else 1
            assert full[key] == float(q(value) * factor), key


def test_the_window_touches_only_the_regen_weights():
    rng = random.Random(33)
    for _ in range(100):
        trio = rng.choice(SAMPLE)
        base = base_of(trio, rng.choice(roles.roles_for(trio)))
        multipliers, custom, minutes = random_composition(rng)
        with_t = weights_override(base, multipliers, custom, minutes)
        without = weights_override(base, multipliers, custom, None)
        other = {k: v for k, v in with_t.items() if "REG" not in k}
        assert other == {k: v for k, v in without.items() if "REG" not in k}


def test_a_custom_weight_touches_only_itself_and_the_weight_derived_from_it():
    rng = random.Random(44)
    derived = {"ATK": {"DMG"}, "HP": {"HPREG"}, "MANA": {"MANAREG"}, "END": {"ENDREG"}}
    for _ in range(100):
        trio = rng.choice(SAMPLE[:2])
        base = base_of(trio)
        key = rng.choice(["HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "CHA"])
        value = round(rng.uniform(0.1, 9), 3)
        changed = {k for k, v in weights_override(base, {}, {key: value}).items() if v != base[k]}
        assert changed <= {key} | derived.get(key, set()), (key, changed)
        assert key in changed or base[key] == value


# ---- the sliders are the robustness variants -----------------------------------------------------------------------


@pytest.mark.parametrize("trio", SAMPLE)
def test_a_slider_is_exactly_the_weight_variant_of_the_robustness_seal(trio):
    seen = 0
    for role in roles.roles_for(trio):
        profile = make_profile("HUM", trio, 50, role, None, None, TABLES)
        for variant in robust.describe_perturbations(profile, RULES):
            if variant.kind != "weight":
                continue
            group, factor = variant.label.rsplit(" x", 1)
            result = weights_override(
                dict(profile.weights), {group: float(factor)}, {}, None, mana_reachable=bool(profile.pools["MANA"])
            )
            assert result == dict(variant.profile.weights), (trio, role, variant.label)
            seen += 1
    assert seen > 0


def test_every_group_at_either_factor_matches_the_variant_arithmetic_for_all_560_trios():
    for trio, role in every_role():
        base = weights_for(trio, role, RULES)
        for group, keys in WEIGHT_GROUPS.items():
            for factor in robust.FACTORS:
                expected = {k: (v * factor if k in keys else v) for k, v in base.items()}
                assert weights_override(base, {group: factor}, {}, None) == expected, (trio, role, group, factor)


# ---- other rules files ---------------------------------------------------------------------------------------------


def rules_with(**changes):
    data = copy.deepcopy(RAW)
    for rule in data["rules"]:
        if rule["id"] in changes:
            rule["value"] = changes[rule["id"]]
    return Rules(data)


def test_a_window_of_another_rules_file_is_the_role_s_own_for_that_file():
    other = rules_with(**{"regen.value_minutes": 2.5})
    base = weights_for(("PAL", "MNK", "BER"), "melee", other)
    assert base["HPREG"] == 10 * 2.5 * base["HP"]
    assert weights_override(base, {}, {}, 2.5) == base
    assert weights_override(base, {}, {}, None) == base
    assert weights_override(base, {}, {}, 3)["HPREG"] == 10 * 3 * base["HP"]


def test_a_base_without_a_damage_weight_stays_without_one():
    other = rules_with(**{"weapons.damage_weight": None})
    base = weights_for(("PAL", "MNK", "BER"), "tank", other)
    assert "DMG" not in base
    assert "DMG" not in weights_override(base, {"ATK+HASTE": 2}, {"ATK": 9}, 7)


def test_a_zero_attack_weight_keeps_the_damage_weight_and_scales_it_with_its_slider_only():
    base = {"HP": 1, "ATK": 0, "DMG": 50}
    assert weights_override(base, {"ATK+HASTE": 2}, {"ATK": 5}, None)["DMG"] == 100
