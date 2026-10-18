"""Tests for the tier rules of the Upgrade tab: ``trioforge.model.tiers``.

* ``tier_for_mode(item, mode, D=4, N=None)``: the tier a candidate is scored at. ``ready4`` is +4 for every item (the
  visitor will bring it there). ``arrives`` is where the item shows up: a ``drop`` at the instance difficulty +D (0 to 4),
  a ``fixed0`` item (quest, crafted or vendor) at +0 and a ``spell`` item (summoned) at +0 until a rank is known.
  ``fixed`` is +N for every item.
* ``cost_to_reach(item, from_tier, to_tier, D=4)``: the merge math of the plan (spec 5.8). Tier N needs ``2^N - 1``
  experience; a copy that arrives at +k gives ``2^k``. The answer has ``exp`` (what is missing, ``2^to - 2^from``),
  ``copies_at_arrival`` (how many arriving copies, at least, supply it) and ``potentials`` (how many Void-touched
  Potentials would do it alone: each gives one tier).

The figures that the plan states are pinned here, and the one it states loosely: +10 from +0 needs **64** D4 copies
(1023 experience, 16 a copy), and +10 from +4 needs **63** (1008 experience), the figure the spec's "64" does not mean.

Every item here is a bare record with a ``tier_rule``; the real catalog is read only in the last test.
"""

import itertools
import math

import pytest

import solver_helpers as H
from trioforge.model import tiers as T
from trioforge.model.tiers import arrival_tier, cost_to_reach, tier_for_mode

RULES = ("drop", "fixed0", "spell")
DIFFICULTIES = range(0, 5)


def record(rule):
    return {"key": "w1", "tier_rule": rule}


# ---- tier_for_mode ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_ready_four_is_plus_four_for_every_item_and_every_difficulty(rule, difficulty):
    assert tier_for_mode(record(rule), "ready4", D=difficulty) == 4
    assert tier_for_mode(record(rule), "ready4", difficulty) == 4  # D is the third argument


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_as_it_arrives_a_drop_is_plus_d_and_a_quest_crafted_vendor_or_summoned_item_is_plus_zero(difficulty):
    assert tier_for_mode(record("drop"), "arrives", D=difficulty) == difficulty
    assert tier_for_mode(record("fixed0"), "arrives", D=difficulty) == 0
    assert tier_for_mode(record("spell"), "arrives", D=difficulty) == 0  # labelled: no rank is known yet


def test_a_drop_at_difficulty_zero_arrives_at_plus_zero_like_a_quest_item():
    assert tier_for_mode(record("drop"), "arrives", D=0) == tier_for_mode(record("fixed0"), "arrives", D=0) == 0


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("n", range(0, 11))
def test_fixed_is_plus_n_for_every_item(rule, n):
    assert tier_for_mode(record(rule), "fixed", N=n) == n
    assert tier_for_mode(record(rule), "fixed", 2, n) == n  # N is the fourth argument; D does not matter


def test_the_defaults_are_a_fresh_drop_at_the_highest_difficulty():
    assert tier_for_mode(record("drop"), "arrives") == 4
    assert arrival_tier(record("drop")) == 4 and arrival_tier(record("fixed0")) == 0 and arrival_tier(record("spell")) == 0


def test_the_item_may_be_a_catalog_record_an_object_with_a_tier_rule_or_the_rule_itself():
    class Thing:
        tier_rule = "drop"

    assert tier_for_mode({"tier_rule": "drop", "name": "x"}, "arrives", D=3) == 3
    assert tier_for_mode(Thing(), "arrives", D=3) == 3
    assert tier_for_mode("drop", "arrives", D=3) == 3


@pytest.mark.parametrize(
    "args, kwargs",
    [
        ((record("drop"), "soon"), {}),  # an unknown mode
        ((record("drop"), "fixed"), {}),  # fixed needs N
        ((record("drop"), "fixed"), {"N": 11}),
        ((record("drop"), "fixed"), {"N": -1}),
        ((record("drop"), "fixed"), {"N": 2.0}),
        ((record("drop"), "fixed"), {"N": True}),
        ((record("drop"), "arrives"), {"D": 5}),  # a fresh drop is never above +4
        ((record("drop"), "arrives"), {"D": -1}),
        ((record("drop"), "arrives"), {"D": 2.5}),
        ((record("drop"), "ready4"), {"D": 5}),  # a bad difficulty is a mistake in every mode
        ((record("loot"), "arrives"), {}),  # an unknown tier rule
        (({"name": "no rule"}, "arrives"), {}),
        ((None, "arrives"), {}),
    ],
)
def test_bad_input_is_refused(args, kwargs):
    with pytest.raises((ValueError, TypeError)):
        tier_for_mode(*args, **kwargs)


# ---- cost_to_reach ------------------------------------------------------------------------------------------------------


def cost(rule, start, stop, difficulty=4):
    return cost_to_reach(record(rule), start, stop, difficulty)


def test_plus_zero_to_plus_four_is_one_copy_that_arrives_at_plus_four():
    assert cost("drop", 0, 4) == {"exp": 15, "copies_at_arrival": 1, "potentials": 4}  # 16 experience supplied for 15 needed


def test_plus_zero_to_plus_four_is_fifteen_plus_zero_copies_for_a_quest_item_and_for_a_drop_at_difficulty_zero():
    assert cost("fixed0", 0, 4) == {"exp": 15, "copies_at_arrival": 15, "potentials": 4}
    assert cost("drop", 0, 4, difficulty=0) == {"exp": 15, "copies_at_arrival": 15, "potentials": 4}
    assert cost("spell", 0, 4) == {"exp": 15, "copies_at_arrival": 15, "potentials": 4}  # +0 until a rank is known


def test_plus_four_to_plus_ten_is_sixty_three_copies_that_arrive_at_plus_four():
    assert cost("drop", 4, 10) == {"exp": 1008, "copies_at_arrival": 63, "potentials": 6}  # 63 * 16 = 1008 exactly


def test_plus_zero_to_plus_ten_is_sixty_four_copies_that_arrive_at_plus_four_the_spec_figure():
    assert cost("drop", 0, 10) == {"exp": 1023, "copies_at_arrival": 64, "potentials": 10}  # 63 * 16 = 1008 falls short


def test_an_owned_item_pays_from_its_own_tier_not_from_plus_zero():
    assert cost("drop", 2, 4) == {"exp": 12, "copies_at_arrival": 1, "potentials": 2}  # (2^4 - 1) - (2^2 - 1)
    assert cost("fixed0", 2, 5) == {"exp": 28, "copies_at_arrival": 28, "potentials": 3}  # 31 - 3, not 31
    assert cost("drop", 3, 4)["exp"] == 8 and cost("drop", 1, 2)["exp"] == 2


def test_the_smallest_steps_and_their_single_copies():
    assert cost("drop", 0, 1) == {"exp": 1, "copies_at_arrival": 1, "potentials": 1}
    assert cost("fixed0", 0, 1) == {"exp": 1, "copies_at_arrival": 1, "potentials": 1}
    assert cost("drop", 4, 5) == {"exp": 16, "copies_at_arrival": 1, "potentials": 1}


def test_a_tier_already_reached_costs_nothing_and_a_lower_tier_is_refused():
    assert cost("drop", 4, 4) == {"exp": 0, "copies_at_arrival": 0, "potentials": 0}
    assert cost("fixed0", 0, 0) == {"exp": 0, "copies_at_arrival": 0, "potentials": 0}
    for start, stop in ((10, 4), (6, 2), (1, 0)):
        with pytest.raises(ValueError):
            cost("drop", start, stop)


@pytest.mark.parametrize("start, stop", [(0, 11), (-1, 4), (11, 11), (0, -1)])
def test_a_tier_outside_zero_to_ten_is_refused(start, stop):
    with pytest.raises(ValueError):
        cost("drop", start, stop)


@pytest.mark.parametrize("start, stop", [(0.0, 4), (0, 4.0), (True, 4), (0, True), ("0", 4), (None, 4)])
def test_a_tier_that_is_not_a_whole_number_is_refused(start, stop):
    with pytest.raises((TypeError, ValueError)):
        cost("drop", start, stop)


def test_the_answer_has_exactly_the_three_fields_and_whole_numbers_in_them():
    for rule, start, stop, difficulty in itertools.product(RULES, (0, 3, 9), (4, 10), DIFFICULTIES):
        if start >= stop:
            continue
        answer = cost(rule, start, stop, difficulty)
        assert set(answer) == {"exp", "copies_at_arrival", "potentials"}
        assert all(type(value) is int for value in answer.values())


def test_the_copies_are_the_fewest_that_supply_the_experience_for_every_pair_of_tiers_and_difficulty():
    for rule in RULES:
        for difficulty in DIFFICULTIES:
            per_copy = 2 ** (difficulty if rule == "drop" else 0)
            for start in range(0, 11):
                for stop in range(start, 11):
                    need = (2**stop - 1) - (2**start - 1)
                    answer = cost(rule, start, stop, difficulty)
                    copies = 0
                    while copies * per_copy < need:  # the definition, one copy at a time
                        copies += 1
                    assert answer == {"exp": need, "copies_at_arrival": copies, "potentials": stop - start}, (
                        rule, difficulty, start, stop,
                    )


def test_a_potential_gives_one_tier_so_the_count_is_the_number_of_tiers():
    for start, stop in ((0, 1), (0, 4), (4, 5), (4, 10), (0, 10)):
        assert cost("drop", start, stop)["potentials"] == stop - start


def test_the_difficulty_matters_for_a_drop_and_for_nothing_else():
    assert cost("fixed0", 0, 6, difficulty=0) == cost("fixed0", 0, 6, difficulty=4)
    assert cost("spell", 0, 6, difficulty=1) == cost("spell", 0, 6, difficulty=3)
    assert cost("drop", 0, 6, difficulty=2)["copies_at_arrival"] == math.ceil(63 / 4)
    with pytest.raises(ValueError):
        cost("drop", 0, 4, difficulty=5)


# ---- the constants are the rules' ------------------------------------------------------------------------------------------


def test_the_constants_say_what_the_rules_file_says():
    rules = H.TABLES.rules
    assert T.MAX_DIFFICULTY == rules.get("tier.max_fresh_drop") == 4
    assert rules.get("tier.exp_needed") == "2^N - 1"
    assert T.MAX_TIER == 10 and T.READY_TIER == 4
    assert set(T.TIER_RULES) == set(RULES) and set(T.MODES) == {"ready4", "arrives", "fixed"}


# ---- the real catalog ---------------------------------------------------------------------------------------------------------


def test_every_item_of_the_catalog_has_a_tier_rule_every_mode_scores_and_a_quest_item_never_arrives_above_plus_zero(capsys):
    items = H.catalog_items()
    counts = {}
    for raw in items:
        rule = raw["tier_rule"]
        counts[rule] = counts.get(rule, 0) + 1
        assert rule in RULES, raw["key"]
        for difficulty in DIFFICULTIES:
            assert tier_for_mode(raw, "ready4", D=difficulty) == 4
            arrives = tier_for_mode(raw, "arrives", D=difficulty)
            assert arrives == (difficulty if rule == "drop" else 0)
        assert tier_for_mode(raw, "fixed", N=7) == 7
    assert counts.get("drop", 0) > 0 and counts.get("fixed0", 0) > 0
    with capsys.disabled():
        print(f"\ncatalog tier rules: {dict(sorted(counts.items()))}")
