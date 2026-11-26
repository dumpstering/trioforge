"""Tests for the Python reference of the mote order: ``trioforge.motes``.

A void-touched mote raises any one item by one whole tier, at any tier, up to +10, with no limit per item. ``mote_order`` says in which order to spend motes on a
fixed kit (the same items in the same places, only the tiers change): each step is the one mote that adds the most kit value to the kit as it stands, the exact value
the Upgrade tab uses (:func:`trioforge.model.formulas.evaluate_truthful`: weapons paid the haste the kit counts), ties going to the place that comes first in the kit's
order. It is greedy: the best single next mote, not a proven best plan for any number of motes.
A gain can sit more than one mote away on one item (a weapon whose damage rises every second tier, a haste that counts only once it passes the best worn one), so a step is a **run**: the
fewest motes on one item that add kit value, ranked by the gain for each mote.

Every case here is worked out by hand from the tier rules and written down as numbers, never taken from the function under test:

* HP-only weights (every point of item HP is worth exactly one), so a step's gain is the change in the item's HP, ``base + max(n, base * n // 10)`` at tier ``n``:
  an item with 100 HP gains 10 a tier, 40 HP gains 4, 5 HP gains 1, 20 HP gains 2, and 25 HP gains 3, 2, 3, 2, 3, 2, 3 from +3 to +10 (32, 35, 37, 40, 42, 45, 47, 50);
* haste: the worn haste of an item is ``base + n`` (one percent a tier), and only the best worn haste counts, up to what the cap leaves after the spell haste.

Every name here is invented.
"""

import dataclasses
from fractions import Fraction

import pytest

import solver_helpers as H
from trioforge import motes
from trioforge.model import formulas as fm
from trioforge.model.items import SLOT_INSTANCES, at_tier
from trioforge.model.procs import ProcDonor, ProcEffect, ProcTable
from trioforge.model.tables import load

F = Fraction
RULES = load().rules
TRIO = ("PAL", "MNK", "BER")
PLACE = {name: SLOT_INSTANCES.index(name) for name in SLOT_INSTANCES}  # the first place of each group
HP_ONLY = H.make_profile(TRIO, "OGR", {"HP": 1})  # every point of item HP is worth exactly one
HASTE_TOO = H.make_profile(TRIO, "OGR", {"HP": 1, "HASTE": 10})  # a point of worn haste is worth ten; the cap is 85 with a Monk
HASTE_CAPPED = H.make_profile(TRIO, "OGR", {"HP": 1, "HASTE": 10}, buff_totals={"HASTE": 70})  # spell haste 70: the worn haste counts up to 15 more
SWORD_PROFILE = H.make_profile(TRIO, "OGR", {"HP": 1, "DMG": 1})


def record(key, slots, stats, *, weapon=None):
    """A catalog item with invented contents (the keys of ``at_tier``'s input)."""
    return {
        "key": key, "name": f"Invented {key}", "slots": list(slots), "classes": ["ALL"], "races": ["ALL"], "deity": None, "flags": [], "stats": dict(stats), "sv": {},
        "weight": 1.0, "item_type": None, "weapon": weapon, "tier_rule": "drop",
    }  # fmt: skip


RECORDS = {
    r["key"]: r
    for r in (
        record("w1", ["CHEST"], {"HP": 100}),
        record("w2", ["HEAD"], {"HP": 40}),
        record("w3", ["LEGS"], {"HP": 5}),
        record("w5", ["CHEST"], {"HP": 40}),
        record("w6", ["EAR"], {"HP": 40}),
        record("w7", ["CHEST"], {"HP": 25}),
        record("w8", ["FACE"], {"HP": 5}),
        record("w10", ["HEAD"], {"HP": 20}),
        record("h1", ["NECK"], {"HASTE": 10}),
        record("h2", ["EAR"], {"HASTE": 10}),
        record("h3", ["NECK"], {"HASTE": 20}),
        record("sword", ["PRIMARY"], {}, weapon={"skill": "1H Slashing", "dmg": 20, "delay": 30, "bonus": None}),
        record("dag", ["PRIMARY"], {}, weapon={"skill": "1H Piercing", "dmg": 5, "delay": 20, "bonus": None}),
        record("e25", ["EAR"], {"HASTE": 25}),
        record("e29", ["EAR"], {"HASTE": 29}),
    )
}


def kit_of(placed, records=RECORDS):
    """The 22-place kit of ``{place index: (key, tier)}``."""
    kit = [None] * len(SLOT_INSTANCES)
    for index, (key, tier) in placed.items():
        kit[index] = at_tier(records[key], tier, RULES)
    return kit


def order(profile, placed, motes_to_spend=None, **more):
    records = more.pop("records", RECORDS)
    return motes.mote_order(profile, kit_of(placed, records), records, RULES, more.pop("setup", "stick"), motes=motes_to_spend, **more)


def walk(result):
    """What the steps are, as (place, key, from, to, gain)."""
    return [(s.place, s.key, s.from_tier, s.to_tier, s.gain) for s in result.steps]


def climb(place, key, first, last, gains):
    """The steps of one item raised from tier ``first`` to tier ``last``: one per tier, with the gains given (one number repeated, or one for each tier)."""
    tiers = list(range(first, last))
    gains = [gains] * len(tiers) if isinstance(gains, int) else gains
    assert len(gains) == len(tiers)
    return [(place, key, t, t + 1, F(g)) for t, g in zip(tiers, gains, strict=True)]


def test_the_places_are_the_kits_own_order():
    assert (PLACE["HEAD"], PLACE["EAR"], PLACE["NECK"], PLACE["CHEST"], PLACE["LEGS"], PLACE["PRIMARY"]) == (0, 2, 4, 13, 14, 20)


# ---- the order ------------------------------------------------------------------------------------------------------------------------


def test_the_best_single_mote_comes_first_and_an_item_goes_on_while_it_stays_the_best():
    placed = {PLACE["HEAD"]: ("w2", 0), PLACE["CHEST"]: ("w1", 0), PLACE["LEGS"]: ("w3", 0)}
    result = order(HP_ONLY, placed)
    chest, head, legs = PLACE["CHEST"], PLACE["HEAD"], PLACE["LEGS"]
    assert walk(result) == [*climb(chest, "w1", 0, 10, 10), *climb(head, "w2", 0, 10, 4), *climb(legs, "w3", 0, 10, 1)]
    assert [s.index for s in result.steps] == list(range(1, 31))
    assert (result.ending, result.left) == ("top", 0)


def test_the_values_are_the_evaluators_exact_values_and_the_gains_add_up_to_the_difference():
    placed = {PLACE["HEAD"]: ("w2", 0), PLACE["CHEST"]: ("w1", 0), PLACE["LEGS"]: ("w3", 0)}
    result = order(HP_ONLY, placed)
    kit = kit_of(placed)
    start = fm.evaluate_truthful(HP_ONLY, kit, None, setup="stick").F
    assert result.start == start
    before = start
    for step in result.steps:
        kit[step.place] = at_tier(RECORDS[step.key], step.to_tier, RULES)  # the kit after the step, worked out again by the evaluator
        after = fm.evaluate_truthful(HP_ONLY, kit, None, setup="stick").F
        assert step.F == after and step.gain == after - before and type(step.gain) is Fraction
        before = after
    assert before - start == 150  # ten steps of 10, ten of 4 and ten of 1


def test_a_tie_goes_to_the_place_that_comes_first_in_the_kit():
    # two items that gain 4 a tier in every tier: the head (place 0) goes all the way to +10 before the chest (place 13) gets a mote, since it never falls behind it
    result = order(HP_ONLY, {PLACE["CHEST"]: ("w5", 0), PLACE["HEAD"]: ("w2", 0)})
    assert walk(result) == [*climb(PLACE["HEAD"], "w2", 0, 10, 4), *climb(PLACE["CHEST"], "w5", 0, 10, 4)]


def test_mixed_tiers_and_ties_between_items_that_gain_alike():
    # the chest piece (25 HP) is at +3 and the head piece (20 HP, 2 a tier) at +0. The chest gains 3 at once (+3 to +4: 32 to 35), then only 2 (35 to 37); the head's 2 ties it,
    # and the head is the earlier place, so the head goes up to +10 while the chest waits at +4 (its next mote is worth 2 until the head is done); then the chest goes on: 2, 3, 2, 3, 2, 3
    result = order(HP_ONLY, {PLACE["CHEST"]: ("w7", 3), PLACE["HEAD"]: ("w10", 0)})
    assert walk(result) == [
        *climb(PLACE["CHEST"], "w7", 3, 4, [3]),
        *climb(PLACE["HEAD"], "w10", 0, 10, 2),
        *climb(PLACE["CHEST"], "w7", 4, 10, [2, 3, 2, 3, 2, 3]),
    ]
    assert (result.ending, result.left) == ("top", 0)


def test_an_item_at_the_top_gets_no_mote_and_a_kit_at_the_top_has_nothing_to_spend():
    result = order(HP_ONLY, {PLACE["FACE"]: ("w8", 10), PLACE["CHEST"]: ("w7", 8)})
    assert walk(result) == climb(PLACE["CHEST"], "w7", 8, 10, [2, 3])  # 45 HP at +8, 47 at +9, 50 at +10; the face piece is at the top and gets nothing
    top = order(HP_ONLY, {PLACE["FACE"]: ("w8", 10), PLACE["CHEST"]: ("w7", 10), PLACE["HEAD"]: ("w2", 10)})
    assert (top.steps, top.ending, top.left) == ((), "top", 0)
    assert top.start == fm.evaluate_truthful(HP_ONLY, kit_of({PLACE["FACE"]: ("w8", 10), PLACE["CHEST"]: ("w7", 10), PLACE["HEAD"]: ("w2", 10)}), None, setup="stick").F


def test_an_empty_kit_has_nothing_to_spend():
    result = order(HP_ONLY, {})
    assert (result.steps, result.ending, result.left) == ((), "top", 0)


def test_the_number_of_motes_limits_the_list_and_the_list_is_a_prefix_of_the_whole_order():
    placed = {PLACE["HEAD"]: ("w2", 0), PLACE["CHEST"]: ("w1", 0), PLACE["LEGS"]: ("w3", 0)}
    whole = order(HP_ONLY, placed)
    three = order(HP_ONLY, placed, 3)
    assert walk(three) == walk(whole)[:3] == climb(PLACE["CHEST"], "w1", 0, 3, 10)
    assert (three.ending, three.left) == ("motes", 27)  # 27 more motes could be spent
    assert three.steps == whole.steps[:3]
    none = order(HP_ONLY, placed, 0)
    assert (none.steps, none.ending, none.left) == ((), "motes", 30)
    exact = order(HP_ONLY, placed, 30)  # exactly as many as there are: the kit is at the top
    assert (exact.ending, exact.left, len(exact.steps)) == ("top", 0, 30)
    more = order(HP_ONLY, placed, 500)
    assert (more.ending, more.left, len(more.steps)) == ("top", 0, 30)


def test_a_step_that_gains_nothing_is_never_taken_and_the_order_ends_with_how_many_motes_could_still_be_spent():
    # a hoop of 10 haste under 70 spell haste and a cap of 85: the worn haste counts up to 15, so +1 to +5 (11 to 15) are worth 10 each and +6 to +10 are worth nothing.
    # The head piece gains 4 a tier. The haste goes first, then the head; the five motes left on the hoop gain nothing, so the order stops there
    result = order(HASTE_CAPPED, {PLACE["NECK"]: ("h1", 0), PLACE["HEAD"]: ("w2", 0)})
    assert walk(result) == [*climb(PLACE["NECK"], "h1", 0, 5, 10), *climb(PLACE["HEAD"], "w2", 0, 10, 4)]
    assert (result.ending, result.left) == ("no-gain", 5)
    # a kit that has only the capped hoop at the cap: the first best step already gains nothing
    only = order(HASTE_CAPPED, {PLACE["NECK"]: ("h1", 5)})
    assert (only.steps, only.ending, only.left) == ((), "no-gain", 5)


def test_only_the_highest_worn_haste_counts():
    # 10 haste on an ear and 20 on the neck, no spell haste: the neck is the best haste and gains a point a tier. The ear's +10 only reaches 20, the neck's starting haste, and the neck
    # is above that by then: not one mote on the ear gains anything
    result = order(HASTE_TOO, {PLACE["EAR"]: ("h2", 0), PLACE["NECK"]: ("h3", 0)})
    assert walk(result) == climb(PLACE["NECK"], "h3", 0, 10, 10)
    assert (result.ending, result.left) == ("no-gain", 10)


def test_two_worn_copies_of_one_item_are_two_separate_items():
    ear1, ear2 = PLACE["EAR"], PLACE["EAR"] + 1
    result = order(HP_ONLY, {ear1: ("w6", 0), ear2: ("w6", 0)})
    assert walk(result) == [*climb(ear1, "w6", 0, 10, 4), *climb(ear2, "w6", 0, 10, 4)]
    mixed = order(HP_ONLY, {ear1: ("w6", 0), ear2: ("w6", 5)})  # a copy at +5 gains what a copy at +0 does: the earlier place first, to +10, then the other
    assert walk(mixed) == [*climb(ear1, "w6", 0, 10, 4), *climb(ear2, "w6", 5, 10, 4)]


# ---- the stats that moved -------------------------------------------------------------------------------------------------------------


def test_the_moved_stats_are_the_kit_totals_that_changed_by_the_step_and_nothing_else():
    result = order(HP_ONLY, {PLACE["HEAD"]: ("w2", 0)}, 1)
    (step,) = result.steps
    assert dict(step.moved) == {"HP": F(4)}  # the 40 HP of the head piece are 44 at +1
    assert all(amount != 0 for _, amount in step.moved)
    haste = order(HASTE_TOO, {PLACE["NECK"]: ("h3", 0)}, 1)
    assert dict(haste.steps[0].moved) == {"HASTE": F(1)}  # 20 haste is 21 at +1


def test_a_weapon_moves_its_damage():
    result = order(SWORD_PROFILE, {PLACE["PRIMARY"]: ("sword", 0)}, 1, setup="1h-shield")
    (step,) = result.steps
    assert step.gain > 0 and step.key == "sword"
    assert dict(step.moved) == {"DMG": F(2)}  # 20 damage is 22 at +1 (ten percent a tier)


def test_the_moved_stats_come_in_a_fixed_order():
    assert motes.MOVED_ORDER[:4] == ("AC", "HP", "MANA", "END")
    assert len(set(motes.MOVED_ORDER)) == len(motes.MOVED_ORDER)
    assert motes.MOVED_ORDER[-1] == "DMG"


# ---- what is refused -------------------------------------------------------------------------------------------------------------------


def test_bad_inputs_are_refused():
    kit = kit_of({PLACE["HEAD"]: ("w2", 0)})
    with pytest.raises(ValueError, match="22"):
        motes.mote_order(HP_ONLY, kit[:21], RECORDS, RULES, "stick")
    with pytest.raises(ValueError, match="w2"):
        motes.mote_order(HP_ONLY, kit, {}, RULES, "stick")
    for bad in (-1, 1.5, True, "3"):
        with pytest.raises(ValueError, match="motes"):
            motes.mote_order(HP_ONLY, kit, RECORDS, RULES, "stick", motes=bad)
    with pytest.raises(ValueError, match="buffset"):
        motes.mote_order(HP_ONLY, kit, RECORDS, RULES, "stick", buffs=(1,))


# ---- a gain that sits more than one mote away: the run ------------------------------------------------------------------------------------------
#
# The weapon damage of a tier n is dmg + dmg * n * 10 // 100, so a damage of 5 reads 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10 from +0 to +10: it rises every second tier. A dagger
# of delay 20 with no listed bonus scores (dmg + 10) / 20 a hand, so each rise of one point of damage is worth 1/20 at a damage weight of one, and a mote to +1, +3, +5, +7 or +9
# adds nothing: the gain is two motes away. The worn haste of an item is its base plus one a tier, and only the best one counts: a neck of 20 haste at +10 is 30, and an ear of 25 at
# +0 reaches 30 at +5 (no gain: it ties), and 31 at +6, the first mote that adds anything. HASTE_TOO weighs a point of haste ten.


def test_a_gain_two_motes_away_is_one_line_of_two_motes_and_the_count_of_motes_spent_is_kept():
    result = order(SWORD_PROFILE, {PLACE["PRIMARY"]: ("dag", 0)}, setup="1h-shield")
    runs = [(PLACE["PRIMARY"], "dag", t, t + 2, F(1, 20)) for t in (0, 2, 4, 6, 8)]
    assert walk(result) == runs
    assert [s.index for s in result.steps] == [1, 2, 3, 4, 5]  # the lines
    assert [s.motes for s in result.steps] == [2] * 5 and [s.spent for s in result.steps] == [2, 4, 6, 8, 10]  # the motes: a run of two spends two
    assert all(dict(s.moved) == {"DMG": F(1)} for s in result.steps)  # (5 damage is 6, 6 is 7 ...)
    assert (result.ending, result.left, result.spent, result.next_run) == ("top", 0, 10, None)


def test_a_haste_that_counts_only_once_it_passes_the_best_worn_one_is_a_run_and_then_a_mote_at_a_time():
    result = order(HASTE_TOO, {PLACE["NECK"]: ("h3", 10), PLACE["EAR"]: ("e25", 0)})
    ear = PLACE["EAR"]
    assert walk(result) == [(ear, "e25", 0, 6, F(10)), *((ear, "e25", t, t + 1, F(10)) for t in (6, 7, 8, 9))]  # 31 against 30: one point of haste, ten
    assert [s.motes for s in result.steps] == [6, 1, 1, 1, 1] and [s.spent for s in result.steps] == [6, 7, 8, 9, 10]
    assert [s.index for s in result.steps] == [1, 2, 3, 4, 5]
    assert all(dict(s.moved) == {"HASTE": F(1)} for s in result.steps)
    assert (result.ending, result.left, result.spent) == ("top", 0, 10)


def test_an_item_that_cannot_ever_gain_has_no_run_and_the_order_says_that_nothing_left_gains():
    # an ear of 10 haste reaches 20 at +10, under the neck's 30 (and an ear of 15 reaches 25): no mote on it adds anything, at any length
    result = order(HASTE_TOO, {PLACE["NECK"]: ("h3", 10), PLACE["EAR"]: ("h2", 5)})
    assert (result.steps, result.ending, result.left, result.spent, result.next_run) == ((), "no-gain", 5, 0, None)


def test_a_run_longer_than_the_motes_left_is_not_taken_and_the_order_says_why_it_stopped():
    placed = {PLACE["NECK"]: ("h3", 10), PLACE["EAR"]: ("e25", 0)}
    for few in (1, 3, 5):
        result = order(HASTE_TOO, placed, few)
        assert (result.steps, result.ending, result.spent, result.next_run, result.left) == ((), "motes", 0, 6, 10), few  # the run is six: it does not fit
    six = order(HASTE_TOO, placed, 6)
    assert walk(six) == [(PLACE["EAR"], "e25", 0, 6, F(10))] and (six.ending, six.spent, six.next_run) == ("motes", 6, None)  # the limit is reached
    eight = order(HASTE_TOO, placed, 8)
    assert [s.spent for s in eight.steps] == [6, 7, 8] and (eight.ending, eight.spent, eight.next_run) == ("motes", 8, None)


def test_when_no_run_fits_the_order_says_how_many_motes_the_shortest_one_needs():
    """E7: ``next_run`` is the fewest motes that would let the order go on, the shortest of the runs left (the run of the best rate is not it: a longer run is no help to someone who has one more mote)."""
    profile = H.make_profile(TRIO, "OGR", {"HP": 1, "DMG": 1, "HASTE": 10})
    placed = {PLACE["NECK"]: ("h3", 10), PLACE["EAR"]: ("e25", 0), PLACE["PRIMARY"]: ("dag", 0)}
    # the ear's run is six motes for ten (a rate of 5/3 a mote) and the dagger's two for a twentieth (1/40 a mote): the ear is the better run, and the dagger's is the shorter
    result = order(profile, placed, 1, setup="1h-shield")
    assert (result.steps, result.ending, result.spent, result.left) == ((), "motes", 0, 20)
    assert result.next_run == 2
    assert order(profile, placed, 2, setup="1h-shield").steps[0].key == "dag"  # (with the two motes the order goes on: the shortest run was the number to say)
    assert order(profile, {PLACE["NECK"]: ("h3", 10), PLACE["EAR"]: ("e25", 0)}, 3).next_run == 6  # (one run left: its length)


def test_a_run_that_does_not_fit_gives_way_to_a_shorter_one_and_comes_back_when_the_motes_allow_it():
    # a point of haste is worth 100 here: the run on the ear (six motes for 100) beats the head piece (4 a mote) when it fits, and not when it does not
    heavy = H.make_profile(TRIO, "OGR", {"HP": 1, "HASTE": 100})
    placed = {PLACE["NECK"]: ("h3", 10), PLACE["EAR"]: ("e25", 0), PLACE["HEAD"]: ("w2", 0)}
    whole = order(heavy, placed)
    assert walk(whole)[:2] == [(PLACE["EAR"], "e25", 0, 6, F(100)), (PLACE["EAR"], "e25", 6, 7, F(100))]
    three = order(heavy, placed, 3)
    assert walk(three) == [(PLACE["HEAD"], "w2", t, t + 1, F(4)) for t in (0, 1, 2)] and (three.ending, three.spent, three.next_run) == ("motes", 3, None)
    seven = order(heavy, placed, 7)
    assert [(s.key, s.motes) for s in seven.steps] == [("e25", 6), ("e25", 1)] and (seven.ending, seven.spent) == ("motes", 7)
    assert walk(seven)[:1] == walk(whole)[:1]  # (the limited order is the whole order as far as the whole order's steps fit what is left)


def test_of_equal_rates_the_shorter_run_comes_first_then_the_earlier_place():
    # the ear needs two motes (29 reaches 30 at +1, which ties, and 31 at +2) for 20: ten a mote, as the chest piece's ten HP a tier are. The ear is the earlier place, and the chest piece
    # goes first because its run is one mote; each time they tie again, to the top
    lively = H.make_profile(TRIO, "OGR", {"HP": 1, "HASTE": 20})
    result = order(lively, {PLACE["NECK"]: ("h3", 10), PLACE["EAR"]: ("e29", 0), PLACE["CHEST"]: ("w1", 0)})
    chest, ear = PLACE["CHEST"], PLACE["EAR"]
    assert walk(result) == [*climb(chest, "w1", 0, 10, 10), (ear, "e29", 0, 2, F(20)), *((ear, "e29", t, t + 1, F(20)) for t in range(2, 10))]
    assert result.steps[-1].spent == 20 and result.ending == "top"


def test_a_run_is_the_fewest_motes_that_gain_something_and_a_loss_on_the_way_does_not_end_it(monkeypatch):
    # a model in which the first mote on one item LOWERS the value (this one never does: see the next test) and the second raises it: the run is the smallest k with a gain above nothing
    table = {"w1": {0: 0, 1: -1, 2: 5, 3: 5, 4: 7, 5: 7, 6: 7, 7: 7, 8: 7, 9: 7, 10: 7}, "w2": {n: n for n in range(11)}}
    real = fm.evaluate_truthful

    def made_up(profile, kit, buffs=None, **options):
        was = real(profile, kit, buffs, **options)
        return dataclasses.replace(was, F=F(sum(table[item.key][item.tier] for item in kit if item is not None)))

    monkeypatch.setattr(fm, "evaluate_truthful", made_up)
    result = order(HP_ONLY, {PLACE["CHEST"]: ("w1", 0), PLACE["HEAD"]: ("w2", 0)})
    # step 1: w1 loses at +1 and gains 5 at +2 (a run of two, 2.5 a mote); w2 gains 1 at +1 (1 a mote): the run wins
    assert walk(result)[0] == (PLACE["CHEST"], "w1", 0, 2, F(5))
    # step 2: w1 gains 0 at +3 and 2 at +4 (a run of two, 1 a mote), against w2's 1 a mote: equal rates, the shorter run, w2, goes first
    assert walk(result)[1][:2] == (PLACE["HEAD"], "w2")


def test_a_one_tier_raise_never_lowers_the_value_in_this_model():
    """The model's value is monotone in the tier of an item: every stat of an item only rises with its tier, its weight only falls, and the value does not fall with a stat or with a lighter
    kit (weights are not negative; the caps, the softcap, the curves and the fade of the Monk bonus are all non-decreasing). So the gain of a mote is never below nothing, and what the order
    does for a loss is needed by the definition and not by the model. This looks for a counterexample in random instances of the solver's own tests (profiles with Monk curves and bands,
    buffs, caps, every weapon setup) with random items: the gain of every raise of every worn item to every tier above it."""
    import random

    from solver_helpers import random_instance
    from trioforge.solver.model import eval_buff_totals

    stats = ["AC", "STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA", "HP", "MANA", "END", "ATK", "HPREG", "MANAREG", "ENDREG"]
    schools = ["FIRE", "COLD", "MAGIC", "POISON", "DISEASE"]
    checked = 0
    for seed in range(30):
        rng = random.Random(seed)
        instance = random_instance(rng)
        totals = eval_buff_totals(instance.buffset.totals(())) if instance.buffset else None
        kit, records = [None] * 22, {}
        for place in rng.sample(range(22), rng.randint(6, 22)):
            weapon = None
            if SLOT_INSTANCES[place] in ("PRIMARY", "SECONDARY"):
                weapon = {"skill": rng.choice(["1H Slashing", "2H Slashing", "1H Blunt"]), "dmg": rng.randint(1, 40), "delay": rng.randint(15, 45), "bonus": rng.choice([None, None, 10, 25])}
            made = record(f"r{place}", [SLOT_INSTANCES[place]], {s: rng.randint(1, 60) for s in rng.sample(stats, rng.randint(0, 4))} | ({"HASTE": rng.randint(5, 35)} if rng.random() < 0.4 else {}), weapon=weapon)
            made["sv"] = {s: rng.randint(1, 30) for s in rng.sample(schools, rng.randint(0, 2))}
            made["weight"] = rng.choice([None, 0.1, 0.5, 1.0, 3.0, 6.0, 10.0])
            records[made["key"]] = made
            kit[place] = at_tier(made, rng.randint(0, 9), RULES)
        base = fm.evaluate_truthful(instance.profile, kit, totals, setup=instance.setup).F
        for place, item in enumerate(kit):
            for tier in range(item.tier + 1, 11) if item is not None else ():
                trial = list(kit)
                trial[place] = at_tier(records[item.key], tier, RULES)
                assert fm.evaluate_truthful(instance.profile, trial, totals, setup=instance.setup).F >= base, (seed, place, item.tier, tier)
                checked += 1
    assert checked > 2000


# ---- F6: the order with a table of procs (the jump at the socket tier) ----------------------------------------------------------------------------------------------


PROC_WEIGHTS = {"HP": 1, "DMG": 600}  # a proc of value V adds V / 600 to the weapon index, so with this weight it adds exactly V to the value of the kit
PROC_TABLE = ProcTable(
    TRIO, 4,
    (ProcEffect("e-frost", "Frost", F(300)), ProcEffect("e-borrowed", "Borrowed", F(900))),
    (
        ProcDonor("e-frost", "axe", frozenset({"PRIMARY", "SECONDARY"}), frozenset(TRIO), False, False),
        ProcDonor("e-borrowed", "far-off", frozenset({"PRIMARY", "SECONDARY"}), frozenset(TRIO), False, False),
    ),
)  # fmt: skip
PROC_RECORDS = {  # (a copy: the records of the other tests of the file are not changed by these)
    **RECORDS,
    "axe": record("axe", ["PRIMARY"], {}, weapon={"skill": "1H Slashing", "dmg": 20, "delay": 30, "bonus": None}),
    "chest9": record("chest9", ["CHEST"], {"HP": 600}),
}


def test_a_table_of_procs_adds_the_jump_at_the_socket_tier_to_the_step_and_changes_the_order():
    """The weapon counts its own proc (300) below +4 and the best proc it can host (900) at +4: the step from +3 to +4 gains the swing's rise and 600 more, where the steps below gain the swing only.
    The chest's mote gains less than that jump and more than the swing's rise, so the order puts the weapon first with the table and the chest first without."""
    profile = H.make_profile(TRIO, "OGR", PROC_WEIGHTS)
    placed = {PLACE["PRIMARY"]: ("axe", 3), PLACE["CHEST"]: ("chest9", 3)}
    plain = order(profile, placed, setup="1h-shield", records=PROC_RECORDS)
    held = order(profile, placed, setup="1h-shield", procs=PROC_TABLE, records=PROC_RECORDS)
    assert [(s.place, s.key) for s in plain.steps][:2] != [(s.place, s.key) for s in held.steps][:2]
    chest_gain = next(s.gain for s in plain.steps if s.key == "chest9")
    plain_axe = next(s.gain for s in plain.steps if s.key == "axe")
    held_axe = next(s.gain for s in held.steps if s.key == "axe")
    assert (plain.steps[0].key, held.steps[0].key) == ("chest9", "axe")  # the table moves the weapon's step to the front
    assert plain_axe < chest_gain < held_axe
    assert held_axe - plain_axe == PROC_WEIGHTS["DMG"] * (900 - 300) / 600  # (the jump from the own proc to the best hosted one, exactly)
    assert held.start - plain.start == 600 * 300 / 600  # (the weapon already counts its own proc at +3)
    # below the socket tier a step gains what it does without the table: the proc is the same before and after
    low = order(profile, {PLACE["PRIMARY"]: ("axe", 1)}, 2, setup="1h-shield", procs=PROC_TABLE, records=PROC_RECORDS)
    assert [(s.from_tier, s.to_tier, s.gain) for s in low.steps] == [(s.from_tier, s.to_tier, s.gain) for s in order(profile, {PLACE["PRIMARY"]: ("axe", 1)}, 2, setup="1h-shield", records=PROC_RECORDS).steps]


def test_the_values_of_an_order_made_with_procs_are_the_evaluators_with_the_same_table():
    profile = H.make_profile(TRIO, "OGR", PROC_WEIGHTS)
    placed = {PLACE["PRIMARY"]: ("axe", 2), PLACE["CHEST"]: ("chest9", 0)}
    result = order(profile, placed, setup="1h-shield", procs=PROC_TABLE, records=PROC_RECORDS)
    kit = kit_of(placed, PROC_RECORDS)
    assert result.start == fm.evaluate_truthful(profile, kit, None, setup="1h-shield", procs=PROC_TABLE).F
    for step in result.steps:
        kit[step.place] = at_tier(PROC_RECORDS[step.key], step.to_tier, RULES)
        assert step.F == fm.evaluate_truthful(profile, kit, None, setup="1h-shield", procs=PROC_TABLE).F
