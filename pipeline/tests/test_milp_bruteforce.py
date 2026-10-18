"""Brute force against the MILP builder: ``trioforge.solver.model.build_milp``.

For random tiny instances (4 to 6 slot groups of 2 to 4 items, a real trio, random weights, optional buffs with
conflicts and a limit) every legal kit and every legal buff set is enumerated and valued with the exact oracle
(:func:`trioforge.model.formulas.evaluate`); the MILP's optimum must equal the best of them within 1e-9
relative, and the objective the model reports for its own kit must equal the oracle's value of that kit within
1e-9 relative (production tolerates 1e-6).

The mutation meta-tests then break the builder on purpose, one way at a time, and require the same brute-force
suite to fail on a fixed seed: a moved END knee, a dropped ordering binary, a missing haste clamp. They prove the
suite can see those errors.

The machinery (instances, the independent enumerator, the float evaluator that ranks candidates) lives in
``solver_helpers.py`` and is itself checked here against the oracle.
"""

import random

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import solver_helpers as H
from solver_helpers import check_instance
from trioforge.solver.model import BuildOptions, build_milp

REL = H.REL
FIXED_SEED = 20261013
SUITE = 140  # instances in the fixed-seed suite of the mutation meta-tests


# ---- the machinery is right -----------------------------------------------------------------------------------


def test_the_float_evaluator_agrees_with_the_oracle_on_random_kits_and_buff_sets():
    worst = 0.0
    for seed in range(40):
        rng = random.Random(1000 + seed)
        space = H.Space(H.random_instance(rng))
        for _ in range(25):
            ki = rng.randrange(len(space.kits))
            chosen = rng.choice(space.buff_sets)
            fast = space.values(chosen)[ki]
            exact = float(space.exact(tuple(space.kits[ki]), chosen))
            worst = max(worst, abs(fast - exact) / max(1.0, abs(exact)))
    assert worst < 1e-12


def test_the_enumerator_counts_a_hand_worked_instance():
    # one single slot with 3 items (4 options) and EAR x 2 with a plain item a and a Lore item b: (), a, b, aa, ab
    # (bb is not allowed): 5 options; the Lore item may not also stand in HEAD
    a = H.make_item("a", {"EAR"}, stats={"HP": 1})
    b = H.make_item("b", {"EAR", "HEAD"}, stats={"HP": 2}, lore=True)
    heads = [H.make_item(f"h{n}", {"HEAD"}) for n in range(2)]
    profile = H.make_profile(("WAR", "CLR", "ENC"), "HUM", {"HP": 1})
    inst = H.Instance("hand", profile, [a, b] + heads, "stick", None, 0, any_rule="explicit")
    space = H.Space(inst)
    # HEAD options: (), b, h0, h1; EAR options: (), a, b, aa, ab; the combinations with b in both are out
    assert len(space.kits) == 4 * 5 - 1 * 2  # b in HEAD with b or ab in EAR


def test_the_enumerator_applies_the_two_hander_rule_and_the_setup_rules():
    axe = H.make_item("axe", {"PRIMARY"}, weapon=H.WeaponVec("2H Slashing", 40, 60, None, True))
    sword = H.make_item("sword", {"PRIMARY", "SECONDARY"}, weapon=H.WeaponVec("1H Slashing", 20, 30, None, False))
    shield = H.make_item("shield", {"SECONDARY"}, shield=True, stats={"AC": 10})
    profile = H.make_profile(("WAR", "CLR", "ENC"), "HUM", {"HP": 1})
    counts = {}
    for setup in H.SETUP_NAMES:
        inst = H.Instance("hands", profile, [axe, sword, shield], setup, None, 0, any_rule="explicit")
        counts[setup] = len(H.Space(inst).kits)
    # stick: PRIMARY {-, axe, sword} x SECONDARY {-, sword, shield} minus (axe with a filled secondary: 2)
    assert counts == {"1h-shield": 2 * 2, "2h": 2, "dw": 2 * 2, "stick": 3 * 3 - 2}


def test_the_enumerator_never_puts_a_two_hander_in_the_off_hand():
    staff = H.make_item("staff", {"PRIMARY", "SECONDARY"}, weapon=H.WeaponVec("2H Blunt", 40, 60, None, True))
    held = H.make_item("held", {"SECONDARY"})
    profile = H.make_profile(("WAR", "CLR", "ENC"), "HUM", {"HP": 1})
    counts = {}
    for setup in H.SETUP_NAMES:
        inst = H.Instance("hands", profile, [staff, held], setup, None, 0, any_rule="explicit")
        counts[setup] = len(H.Space(inst).kits)
    # stick: main hand {-, staff} x off hand {-, held} minus (staff with held); 2h: {-, staff} and an empty off hand;
    # dw and 1h-shield: neither item is allowed in a hand
    assert counts == {"1h-shield": 1, "2h": 2, "dw": 1, "stick": 2 * 2 - 1}


# ---- the brute force ------------------------------------------------------------------------------------------


def run_seed(seed, **kwargs):
    inst = H.random_instance(random.Random(seed), **kwargs)
    result = check_instance(inst)
    assert result.ok, f"seed {seed} ({inst.label}): {result.message}"


@settings(max_examples=300, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(seed=st.integers(0, 2**32 - 1))
def test_the_milp_optimum_equals_the_brute_force_maximum(seed):
    run_seed(seed)


@pytest.mark.parametrize("trio_index", range(len(H.TRIO_MENU)))
def test_every_trio_of_the_menu_agrees_with_the_brute_force(trio_index):
    for seed in range(40):
        run_seed(5000 + 100 * trio_index + seed, trio_index=trio_index)


@settings(max_examples=120, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(seed=st.integers(0, 2**32 - 1))
def test_buffs_with_conflicts_a_limit_and_resists_over_the_cap_are_chosen_with_the_gear(seed):
    run_seed(seed, with_buffs=True)


@settings(max_examples=100, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(seed=st.integers(0, 2**32 - 1))
def test_two_or_more_conflicting_haste_buffs_are_chosen_with_the_worn_haste(seed):
    # at least two optional buffs carry a spell haste and exclude each other; the room for worn haste follows the choice
    inst = H.random_instance(random.Random(seed), haste_buffs=True)
    assert sum(1 for b in inst.buffset.optional if b.haste > 0) >= 2
    result = check_instance(inst)
    assert result.ok, f"seed {seed} ({inst.label}): {result.message}"


@settings(max_examples=60, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(seed=st.integers(0, 2**32 - 1), curve=st.sampled_from(["stand_in", "full_until_34"]))
def test_the_monk_trio_below_plus_10_agrees_under_both_curves_and_placements(seed, curve):
    run_seed(seed, trio_index=0, monk_curve=curve)
    run_seed(seed + 1, trio_index=2, monk_curve=curve)


@settings(max_examples=60, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(seed=st.integers(0, 2**32 - 1), rule=st.sampled_from(["all", "explicit"]))
def test_the_any_slots_agree_under_both_rules(seed, rule):
    run_seed(seed, any_rule=rule)


@pytest.mark.parametrize("setup", H.SETUP_NAMES)
def test_every_weapon_setup_agrees_with_the_brute_force(setup):
    for seed in range(40):
        inst = H.random_instance(random.Random(9000 + seed), setup=setup)
        result = check_instance(inst)
        assert result.ok, f"seed {9000 + seed} ({inst.label}): {result.message}"


def test_the_fixed_seed_suite_passes_and_reports_the_errors_it_saw():
    errors = []
    for k in range(SUITE):
        result = check_instance(H.random_instance(random.Random(FIXED_SEED + k)))
        assert result.ok, f"instance {k}: {result.message}"
        errors.append(max(result.kit_error, result.model_error))
    assert max(errors) <= REL


# ---- mutation meta-tests: the suite can see each of the three errors ------------------------------------------------


def failures(mutation, count=SUITE):
    found = []
    for k in range(count):
        inst = H.random_instance(random.Random(FIXED_SEED + k))
        if not check_instance(inst, mutation).ok:
            found.append(k)
    return found


@pytest.mark.parametrize("mutation", ["end_knee_101", "drop_ordering_binary", "skip_haste_clamp"])
def test_a_deliberately_broken_builder_fails_the_fixed_seed_brute_force(mutation):
    caught = failures(mutation)
    assert caught, f"the brute-force suite did not notice the mutation {mutation!r}"


def test_the_mutations_leave_the_default_builder_alone():
    inst = H.random_instance(random.Random(FIXED_SEED))
    plain = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, BuildOptions(**inst.options_kwargs()))
    same = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, BuildOptions(mutation=None, **inst.options_kwargs()))
    assert np.array_equal(plain.c, same.c) and plain.names == same.names
