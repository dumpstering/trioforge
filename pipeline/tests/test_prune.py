"""Tests for dominance pruning: ``trioforge.solver.prune``.

``prune`` drops an item only when a *kept, non-Lore* item can wear its places: it fits every slot group the dropped
item fits, it is at least as good in every dimension the objective scores (and no heavier, for a Monk trio whose weight
is scored), and it is not a two-hander that would empty the off hand where the dropped item would not. Lore items
never justify a drop. Of two items that are equal, the one with the smaller key survives. The rule is exact: the best
kit of the pruned pool is worth what the best kit of the full pool is worth.

The evidence comes in layers:

* the cases of addendum F, worked by hand; each is also run with the rule broken on purpose (a test hook of the module)
  to show that the case can see the error;
* the pool is the builder's: which items count, which groups they fit and the assumed haste agree with ``build_milp``;
* the sweep that finds the kept items against the definition, written out again item by item;
* the oracle (``formulas.evaluate``) never falls when a compared dimension gets better, and does not move at all with a
  dimension that the prune leaves out;
* exactness on random pools of four trio types: the MILP optimum of the full pool and of the pruned pool agree, and so
  do the exact brute-force maxima (fractions, no solver) on pools small enough to list;
* real data: the PAL/MNK/BER Ogre pools of the wiki evidence level at +4 (marked ``slow``; skipped without the catalog).

Every name, race and item here is invented, except in the real-data check, which reads the catalog and prints counts.
"""

import dataclasses
import importlib
import itertools
import json
import os
import random
import subprocess
import time
import warnings
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import solver_helpers as H
from solver_helpers import make_item
from trioforge.classes import CLASS_CODES
from trioforge.model import formulas as fm
from trioforge.model.formulas import EvalProfile, PoolSpec, evaluate
from trioforge.model.items import SLOT_GROUPS, SLOT_INSTANCES, WeaponVec, at_tier
from trioforge.model.profile import make_profile
from trioforge.model.tables import REPO, load
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.prune import PruneReport, fit_groups, prune, prune_report, scored_dimensions
from trioforge.solver.solve import solve

prune_module = importlib.import_module("trioforge.solver.prune")

F = Fraction
OPT = BuildOptions(any_rule="explicit", haste_assumed=0)  # only items that list ANY fit the Any group
TRIO = ("WAR", "CLR", "ENC")  # a Warrior, a Cleric (mana on WIS) and an Enchanter (mana on INT)
PMB = {"trio": ("PAL", "MNK", "BER"), "race": "OGR"}  # the only mana class is the Paladin, on WIS; a Monk is in it
FOUR_TRIOS = (
    ("OGR", ("PAL", "MNK", "BER")),
    ("DEF", ("SHD", "CLR", "SHM")),
    ("GNM", ("WIZ", "MAG", "ENC")),
    ("HUM", ("MNK", "BRD", "WAR")),
)
REL = 1e-9
SWORD = WeaponVec("1H Slashing", 20, 30, None, False)
AXE = WeaponVec("2H Slashing", 40, 60, None, True)
ALL_WEIGHTS = ("HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "CHA", "HPREG", "MANAREG", "ENDREG", "DMG", "SV")


def prof(weights, trio=TRIO, race="HUM", **changes):
    return H.make_profile(trio, race, weights, **changes)


def keys_of(items):
    return sorted(item.key for item in items)


def run(profile, items, setup="stick", options=OPT, buffset=None, tier=0):
    return prune(items, profile, tier, setup, buffset, options)


def optimum(profile, items, setup="stick", options=OPT, buffset=None):
    solution = solve(build_milp(profile, items, setup, buffset, options))
    assert solution.status == "optimal"
    return solution.F


def close(a, b):
    return abs(a - b) <= REL * max(1.0, abs(a), abs(b))


def agree(profile, items, setup="stick", options=OPT, buffset=None):
    """The kept keys; asserts on the way that the full pool and the pruned pool have the same optimum."""
    kept = run(profile, items, setup, options, buffset)
    full, small = optimum(profile, items, setup, options, buffset), optimum(profile, kept, setup, options, buffset)
    assert close(full, small), f"full {full!r} against pruned {small!r}"
    return keys_of(kept)


def empty_value(profile):
    return float(evaluate(profile, [None] * len(SLOT_INSTANCES)).F)


@contextmanager
def broken(mutation):
    """The prune with one rule broken on purpose (the module's test hook)."""
    saved = prune_module._MUTATION
    prune_module._MUTATION = mutation
    try:
        yield
    finally:
        prune_module._MUTATION = saved


def sees(mutation, profile, items, setup="stick", options=OPT, buffset=None):
    """Whether the case notices the broken rule: the pruned pool then has a lower optimum than the full pool."""
    full = optimum(profile, items, setup, options, buffset)
    with broken(mutation):
        kept = run(profile, items, setup, options, buffset)
    return not close(full, optimum(profile, kept, setup, options, buffset))


# ---- the rule, by hand (addendum F) -------------------------------------------------------------------------------


def test_a_dominated_item_is_dropped_and_the_report_names_the_item_that_replaces_it():
    p = prof({"HP": 1})
    items = [make_item("big", {"HEAD"}, stats={"HP": 50}), make_item("small", {"HEAD"}, stats={"HP": 30})]
    report = prune_report(items, p, 0, "stick", None, OPT)
    assert isinstance(report, PruneReport) and keys_of(report.kept) == ["big"]
    assert report.dropped == {("small", 0): ("dominated", ("big", 0))}
    assert agree(p, items) == ["big"]


def test_two_lore_dominators_do_not_justify_dropping_a_plain_item():
    # GLM's case: B is plain and fits the fingers; A2 and A3 are Lore and fit the ears and the fingers. The ears can only
    # be filled by A2 and A3, so the fingers need B: dropping B for "two dominators" loses 100 of 215
    p = prof({"HP": 1})
    b = make_item("b-ring", {"FINGER"}, stats={"HP": 50})
    a2 = make_item("a2-ring", {"EAR", "FINGER"}, stats={"HP": 60}, lore=True)
    a3 = make_item("a3-ring", {"EAR", "FINGER"}, stats={"HP": 55}, lore=True)
    items = [b, a2, a3]
    assert agree(p, items) == ["a2-ring", "a3-ring", "b-ring"]
    assert close(optimum(p, items), empty_value(p) + 60 + 55 + 50 + 50)
    assert close(optimum(p, [a2, a3]), empty_value(p) + 60 + 55)  # without B only the two Lore rings are worn, once each
    assert sees("lore_dominates", p, items)


def test_the_three_ear_case_an_item_goes_only_to_a_plain_dominator():
    # MiniMax's case: WIS 10, 9 and 8 for the two ear places, as (WIS, Lore) per item
    p = prof({"MANA": 1})
    ear = lambda key, wis, lore: make_item(key, {"EAR"}, stats={"WIS": wis}, lore=lore)  # noqa: E731
    cases = [
        ((10, True), (9, False), (8, False), ["a", "b"]),  # A is Lore, so B stays; B is plain, so C goes
        ((10, True), (9, True), (8, False), ["a", "b", "c"]),  # two Lore dominators: C stays
        ((10, False), (9, False), (8, False), ["a"]),  # all plain: the best one is worn twice
        ((10, True), (9, True), (8, True), ["a", "b", "c"]),  # all Lore: nothing can go
        ((10, False), (9, True), (8, True), ["a"]),  # the plain A replaces both Lore items
    ]
    for a, b, c, kept in cases:
        assert agree(p, [ear("a", *a), ear("b", *b), ear("c", *c)]) == kept, (a, b, c)
    items = [ear("a", 10, True), ear("b", 9, False), ear("c", 8, False)]
    assert prune_report(items, p, 0, "stick", None, OPT).dropped == {("c", 0): ("dominated", ("b", 0))}
    assert sees("lore_dominates", p, [ear("a", 10, True), ear("b", 9, True), ear("c", 8, True)])


def test_two_identical_items_leave_exactly_one_the_smaller_key_whatever_the_input_order():
    p = prof({"HP": 1})
    twins = [make_item(k, {"HEAD"}, stats={"HP": 30}) for k in ("head-b", "head-c", "head-a")]
    for order in itertools.permutations(twins):
        assert keys_of(run(p, list(order))) == ["head-a"]
    assert agree(p, twins) == ["head-a"]


def test_identical_lore_items_both_stay_because_both_ear_places_can_hold_one_each():
    p = prof({"HP": 1})
    lores = [make_item(k, {"EAR"}, stats={"HP": 30}, lore=True) for k in ("e-b", "e-a")]
    assert agree(p, lores) == ["e-a", "e-b"]
    plain = make_item("e-z", {"EAR"}, stats={"HP": 30})  # an identical plain item replaces both Lore twins
    assert agree(p, lores + [plain]) == ["e-z"]


def test_an_item_that_fits_fewer_groups_does_not_replace_one_that_fits_more():
    p = prof({"HP": 1})
    wide = make_item("wide", {"EAR", "FINGER"}, stats={"HP": 20})
    narrow = make_item("narrow", {"EAR"}, stats={"HP": 90})
    assert agree(p, [wide, narrow]) == ["narrow", "wide"]  # the fingers still need the wide one
    assert sees("ignore_groups", p, [wide, narrow])
    best = make_item("best", {"EAR", "FINGER"}, stats={"HP": 95})
    assert agree(p, [wide, narrow, best]) == ["best"]


def test_equal_stats_and_more_groups_replace_the_narrow_twin_whatever_the_keys():
    p = prof({"HP": 1})
    wide = make_item("zz-wide", {"EAR", "FINGER"}, stats={"HP": 20})
    narrow = make_item("aa-narrow", {"EAR"}, stats={"HP": 20})
    assert agree(p, [wide, narrow]) == ["zz-wide"]


DIMENSIONS = {  # dimension -> the keywords of an item that is better in it only
    "STR": {"stats": {"STR": 4}}, "STA": {"stats": {"STA": 4}}, "AGI": {"stats": {"AGI": 4}}, "DEX": {"stats": {"DEX": 4}},
    "WIS": {"stats": {"WIS": 4}}, "INT": {"stats": {"INT": 4}}, "CHA": {"stats": {"CHA": 4}},
    "HP": {"stats": {"HP": 40}}, "MANA": {"stats": {"MANA": 40}}, "END": {"stats": {"END": 40}},
    "ATK": {"stats": {"ATK": 4}},
    "HPREG": {"stats": {"HPREG": 2}}, "MANAREG": {"stats": {"MANAREG": 2}}, "ENDREG": {"stats": {"ENDREG": 2}},
    "AC": {"stats": {"AC": 9}}, "HASTE": {"haste": 9},
    **{f"SV_{school}": {"sv": {school: 9}} for school in fm.SCHOOLS},
}


@pytest.mark.parametrize("dimension", sorted(DIMENSIONS))
def test_an_item_that_is_better_in_a_scored_dimension_and_worse_in_another_does_not_replace_it(dimension):
    scored = prof(dict.fromkeys(ALL_WEIGHTS, 1))  # every weight on: every dimension counts
    gives = make_item("gives", {"HEAD"}, **DIMENSIONS[dimension])
    hp = make_item("hp-only", {"HEAD"}, stats={"HP": 41} if dimension != "HP" else {"MANA": 41})
    assert agree(scored, [gives, hp]) == ["gives", "hp-only"], dimension


UNSCORED_BY_HP = ["STR", "AGI", "DEX", "WIS", "INT", "CHA", "MANA", "END", "ATK", "AC", "HASTE", "SV_FIRE"]


@pytest.mark.parametrize("dimension", UNSCORED_BY_HP)
def test_an_item_that_is_better_only_in_an_unscored_dimension_is_replaced(dimension):
    only_hp = prof({"HP": 1})  # HP scores HP and STA and nothing else
    gives = make_item("gives", {"HEAD"}, **DIMENSIONS[dimension])
    hp = make_item("hp-only", {"HEAD"}, stats={"HP": 41})
    assert agree(only_hp, [gives, hp]) == ["hp-only"], dimension


def test_the_dimensions_that_a_trio_cannot_use_do_not_block_a_drop():
    # Paladin, Monk, Berserker: the only mana class is the Paladin, on WIS, so INT is worth nothing to this trio
    pmb = prof({"HP": 1, "MANA": 1}, **PMB)
    a = make_item("a", {"HEAD"}, stats={"HP": 50})
    b = make_item("b", {"HEAD"}, stats={"HP": 40, "INT": 30})
    assert agree(pmb, [a, b]) == ["a"]
    wis = make_item("c", {"HEAD"}, stats={"HP": 40, "WIS": 30})
    assert agree(pmb, [a, wis]) == ["a", "c"]
    assert agree(prof({"HP": 1, "MANA": 1}), [a, b]) == ["a", "b"]  # an Enchanter's mana is on INT: there it counts
    none = prof({"HP": 1, "MANA": 1}, trio=("WAR", "MNK", "ROG"))  # no mana class: no mana to gain, whatever the weight
    mana = make_item("m", {"HEAD"}, stats={"HP": 40, "MANA": 90, "WIS": 20})
    assert agree(none, [a, mana]) == ["a"]


# ---- weapons ----------------------------------------------------------------------------------------------------------


def dw_pool():
    # in the primary hand W5 hits harder (the listed bonus); in the off hand W6 does (no bonus there); W7 is W6 plus HP
    w5 = make_item("w5", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("1H Slashing", 18, 20, 30, False))
    w6 = make_item("w6", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("1H Slashing", 20, 20, None, False))
    w7 = make_item("w7", {"PRIMARY", "SECONDARY"}, stats={"HP": 5}, weapon=WeaponVec("1H Slashing", 20, 20, None, False))
    return [w5, w6, w7]


@pytest.mark.parametrize("haste", [0, 25, 50, 85])
def test_a_weapon_better_in_one_hand_and_worse_in_the_other_is_kept_at_every_assumed_haste(haste):
    p = prof({"DMG": 300, "HP": 1}, dw_factor=F(4, 5))
    options = BuildOptions(any_rule="explicit", haste_assumed=haste)
    # the index is (dmg + bonus) / delay x (1 + haste): the haste is one factor for every weapon, so two weapons in one
    # hand keep their order at any haste; what changes the order is the hand (the bonus is the primary hand's)
    assert F(18 + 30, 20) > F(20 + 10, 20) and F(18, 20) < F(20, 20)
    assert agree(p, dw_pool(), "dw", options) == ["w5", "w7"]  # w6 is w7 without the HP
    assert sees("ignore_weapon", p, dw_pool(), "dw", options)


def test_the_assumed_haste_never_changes_what_a_weapon_pool_prunes_to():
    p = prof({"DMG": 300, "HP": 1}, dw_factor=F(4, 5))
    kept = {
        haste: keys_of(run(p, dw_pool(), "dw", BuildOptions(any_rule="explicit", haste_assumed=haste)))
        for haste in (0, 40, 85)
    }
    assert kept[0] == kept[40] == kept[85]


def test_weapons_are_compared_per_setup_and_the_stick_scores_no_weapon_at_all():
    p = prof({"DMG": 300, "HP": 1}, dw_factor=F(4, 5))
    heavy = make_item("heavy", {"PRIMARY"}, weapon=AXE)
    light = make_item("light", {"PRIMARY"}, stats={"HP": 3}, weapon=WeaponVec("2H Blunt", 10, 60, None, True))
    assert agree(p, [heavy, light], "2h") == ["heavy", "light"]  # heavy hits harder, light has HP: neither goes
    assert agree(p, [heavy, light], "stick") == ["light"]  # the stick scores no damage: the HP of the light one decides
    only_damage = prof({"DMG": 300})
    assert agree(only_damage, [heavy, light], "2h") == ["heavy"]
    assert agree(only_damage, [heavy, light], "stick") == ["heavy"]  # nothing is scored in the stick: the smaller key stays


def test_the_off_hand_index_has_no_bonus_and_takes_the_dual_wield_factor():
    p = prof({"DMG": 300}, dw_factor=F(1, 2))
    bonus = make_item("bonus", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("1H Slashing", 10, 20, 40, False))
    plain = make_item("plain", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("1H Slashing", 12, 20, None, False))
    assert agree(p, [bonus, plain], "dw") == ["bonus", "plain"]  # bonus wins the primary hand, plain wins the off hand
    only_primary = make_item("only-primary", {"PRIMARY"}, weapon=WeaponVec("1H Slashing", 10, 20, 40, False))
    assert agree(p, [only_primary, bonus], "dw") == ["bonus"]  # the wider item with the same primary index replaces it


def test_a_shield_is_compared_by_its_armor_class_and_a_worn_point_does_not_stand_for_a_shield_point():
    p = prof({"AC": 3, "HP": 1}, softcap=(100, F(1, 5)))
    big = make_item("big", {"SECONDARY"}, stats={"AC": 30}, shield=True)
    small = make_item("small", {"SECONDARY"}, stats={"AC": 20}, shield=True)
    assert agree(p, [big, small], "1h-shield") == ["big"]
    # in the stick a held item with more armor class does not replace a shield: past the softcap a shield point counts
    # for more than a worn point (the softcap rises with the shield), so the pool keeps both
    chest = make_item("chest", {"CHEST"}, stats={"AC": 160})
    held = make_item("held", {"SECONDARY"}, stats={"AC": 25})
    pool = [chest, small, held]
    assert agree(p, pool, "stick") == ["chest", "held", "small"]
    assert optimum(p, pool, "stick") > optimum(p, [chest, held], "stick")
    assert sees("ignore_shield", p, pool, "stick")


def test_only_a_typed_shield_fits_the_off_hand_of_the_shield_setup_a_held_item_with_armor_class_does_not():
    # the shield definition (the catalog type, nothing else) reaches the pruning through is_shield: in the shield setup a
    # held item has no place in the off hand however much armor class it carries, and in the stick the two stay apart
    held = make_item("focus", {"SECONDARY"}, stats={"AC": 30, "WIS": 5})
    guard = make_item("guard", {"SECONDARY"}, stats={"AC": 10}, shield=True)
    p = prof({"AC": 3, "HP": 1}, softcap=(100, F(1, 5)))
    assert fit_groups(held, "1h-shield", "explicit") == frozenset()
    assert fit_groups(guard, "1h-shield", "explicit") == frozenset({"SECONDARY"})
    report = prune_report([held, guard], p, 0, "1h-shield", None, OPT)
    assert keys_of(report.kept) == ["guard"] and report.dropped == {("focus", 0): ("no-slot", None)}
    assert agree(p, [held, guard], "1h-shield") == ["guard"]
    assert agree(p, [held, guard], "stick") == ["focus", "guard"]  # a shield point and a worn point are not alike


def test_a_two_hander_does_not_replace_a_one_hander_that_could_share_the_hands_with_a_secondary_item():
    # T is better than O in every dimension and fits every hand O fits (O lists only the main hand: a two-hander never
    # stands in the off hand, so T would not fit it if O did), but a two-hander in the primary hand empties the
    # secondary hand, where the held item X is worth 100
    p = prof({"HP": 1})
    t = make_item("t", {"PRIMARY", "SECONDARY"}, stats={"HP": 60}, weapon=AXE)
    o = make_item("o", {"PRIMARY"}, stats={"HP": 50}, weapon=SWORD)
    x = make_item("x", {"SECONDARY"}, stats={"HP": 100})
    assert agree(p, [t, o, x]) == ["o", "t", "x"]
    assert close(optimum(p, [t, o, x]), empty_value(p) + 150)
    assert optimum(p, [t, x]) < empty_value(p) + 150
    assert sees("ignore_two_hander", p, [t, o, x])
    better = make_item("better", {"PRIMARY", "SECONDARY"}, stats={"HP": 70}, weapon=SWORD)
    assert agree(p, [t, better, x]) == ["better", "x"]  # a one-hander that beats a two-hander replaces it


def test_a_two_hander_that_lists_the_off_hand_does_not_fit_it_so_it_cannot_replace_what_does():
    # t is better than b in every dimension and lists the off hand, but a two-hander never stands there: b must stay
    # (the best kit is c in the main hand and b in the off hand, 105; t alone is 60)
    p = prof({"HP": 1})
    t = make_item("t", {"PRIMARY", "SECONDARY"}, stats={"HP": 60}, weapon=AXE)
    b = make_item("b", {"SECONDARY"}, stats={"HP": 50})
    c = make_item("c", {"PRIMARY"}, stats={"HP": 55}, weapon=SWORD)
    for setup in (None, "stick", "2h", "dw", "1h-shield"):
        assert "SECONDARY" not in fit_groups(t, setup, "explicit") and "SECONDARY" not in fit_groups(t, setup)
    assert fit_groups(t, "stick", "explicit") == frozenset({"PRIMARY"})
    assert agree(p, [t, b, c]) == ["b", "c", "t"]  # t cannot replace c either: it would empty the off hand
    assert close(optimum(p, [t, b, c]), empty_value(p) + 105)
    assert close(optimum(p, [t, c]), empty_value(p) + 60)
    # the builder makes no column for it in the off hand, which is what fit_groups says
    milp = build_milp(p, [t, b, c], "stick", None, OPT)
    assert {g for _, g, item in milp.item_cols if item.key == "t"} == {"PRIMARY"}


# ---- the Monk's weight --------------------------------------------------------------------------------------------------


def monk_pair(heavy_weight):
    heavy = make_item("heavy", {"CHEST"}, stats={"AC": 40, "HP": 100}, weight10=heavy_weight)
    light = make_item("light", {"CHEST"}, stats={"AC": 30, "HP": 80}, weight10=10)
    return [heavy, light]


def test_a_lighter_weaker_item_is_kept_for_a_monk_trio_whose_weight_matters():
    pmb = prof({"AC": 3, "HP": 1}, **PMB)
    assert agree(pmb, monk_pair(330)) == ["heavy", "light"]  # 33 stones against 1 stone: the fade costs more than the stats
    assert optimum(pmb, monk_pair(330)) > optimum(pmb, monk_pair(330)[:1])
    assert sees("ignore_weight", pmb, monk_pair(330))
    assert agree(prof({"AC": 3, "HP": 1}), monk_pair(330)) == ["heavy"]  # a trio without a Monk: weight is worth nothing


def test_the_weight_is_ignored_when_every_reachable_weight_earns_the_full_bonus():
    pmb = prof({"AC": 3, "HP": 1}, **PMB)
    assert agree(pmb, monk_pair(60)) == ["heavy"]  # one chest piece alone can never reach the seventeen stones of the fade
    assert prune_report(monk_pair(60), pmb, 0, "stick", None, OPT).weight_rule is None
    legs = [make_item(f"legs{n}", {"LEGS"}, stats={"HP": 1}, weight10=w) for n, w in enumerate((100, 90))]
    report = prune_report(monk_pair(100) + legs, pmb, 0, "stick", None, OPT)
    assert report.weight_rule == "le"  # a chest piece and legs together can reach the fade
    assert keys_of(report.kept) == ["heavy", "legs1", "light"]  # the lighter legs replace the heavier ones; the pair stays
    assert agree(pmb, monk_pair(100) + legs) == ["heavy", "legs1", "light"]


def test_weight_is_not_scored_without_an_armor_class_weight():
    pmb = prof({"HP": 1}, **PMB)
    assert agree(pmb, monk_pair(330)) == ["heavy"]
    assert prune_report(monk_pair(330), pmb, 0, "stick", None, OPT).weight_rule is None


@pytest.mark.parametrize("full_until", [None, 34])
@pytest.mark.parametrize("placement", ["top", "inside"])
def test_the_weight_rule_holds_under_both_curves_and_both_placements(full_until, placement):
    monk = fm.monk_curve(H.TABLES.rules, 50, full_until=full_until)
    pmb = prof({"AC": 3, "HP": 1}, monk=monk, placement={"monk": placement, "iksar": "top"}, **PMB)
    pool = monk_pair(420) + [make_item("mid", {"CHEST"}, stats={"AC": 35, "HP": 90}, weight10=200)]
    assert agree(pmb, pool) == ["heavy", "light", "mid"]


def test_the_monk_bonus_never_rises_with_the_weight_so_a_lighter_item_is_never_worse():
    # the premise of the weight rule, for both curves and both levels the tables have
    for level in (50, 55):
        for full_until in (None, 34):
            curve = fm.monk_curve(H.TABLES.rules, level, full_until=full_until)
            values = [fm.monk_bonus(level, 10 * stone, curve) for stone in range(0, 150)]
            assert all(a >= b for a, b in zip(values, values[1:])), (level, full_until)
            assert values[0] > 0 > values[-1]


def test_a_curve_that_is_not_monotone_makes_the_weight_an_equality(monkeypatch):
    def bumpy(level, worn_weight10, curve):  # no real curve does this; the rule must not depend on it
        stones = worn_weight10 // 10
        return 40 if stones % 5 == 0 else (0 if stones % 2 else 10)

    monkeypatch.setattr(fm, "monk_bonus", bumpy)
    pmb = prof({"AC": 3, "HP": 1}, **PMB)
    twin = make_item("heavy2", {"CHEST"}, stats={"AC": 39, "HP": 99}, weight10=330)
    pool = monk_pair(330) + [twin]
    report = prune_report(pool, pmb, 0, "stick", None, OPT)
    assert report.weight_rule == "eq"
    assert agree(pmb, pool) == ["heavy", "light"]  # equal weight: heavy replaces heavy2; unequal weight: nothing else goes
    for seed in range(25):
        run_seed(100 + seed, trio_index=0)


# ---- haste, eligibility, odds and ends ----------------------------------------------------------------------------------


def test_haste_blocks_a_drop_only_when_haste_is_scored():
    a = make_item("a", {"HEAD"}, stats={"HP": 100})
    b = make_item("b", {"HEAD"}, stats={"HP": 10}, haste=60)
    scored = prof({"HASTE": 2, "HP": 1})
    assert agree(scored, [a, b]) == ["a", "b"]
    assert optimum(scored, [a, b]) > optimum(scored, [a])
    assert sees("ignore_haste", scored, [a, b])
    assert agree(prof({"HP": 1}), [a, b]) == ["a"]
    # the weapon term assumes the best worn haste of the pool, so it keeps its source of haste too
    weapons_only = prof({"DMG": 300, "HP": 1})
    assert agree(weapons_only, [a, b], "2h") == ["a", "b"]
    assert agree(weapons_only, [a, b], "stick") == ["a"]


def test_a_slowing_item_counts_for_no_haste_at_all():
    # worn haste below zero is no haste: the builder and the oracle both start the best worn haste at 0
    p = prof({"HASTE": 2, "HP": 1})
    slow = make_item("a-slow", {"HEAD"}, stats={"HP": 5}, haste=-10)
    plain = make_item("b-plain", {"HEAD"}, stats={"HP": 5})
    assert agree(p, [slow, plain]) == ["a-slow"]  # equal in every compared dimension: the smaller key stays
    assert agree(p, [plain, make_item("c-quick", {"HEAD"}, stats={"HP": 5}, haste=5)]) == ["c-quick"]


def test_a_dominated_resist_is_dropped_and_a_resist_in_another_school_is_not():
    p = prof({"SV": 1})
    ears = (("fire", "FIRE", 150), ("cold", "COLD", 150), ("less", "FIRE", 100))
    fire, cold, less = (make_item(k, {"EAR"}, sv={s: n}) for k, s, n in ears)
    assert agree(p, [fire, cold, less]) == ["cold", "fire"]
    # a resist stops at 200: two of one school give 200, one of each school give 300, so both are worn
    assert close(optimum(p, [fire, cold, less]), empty_value(p) + 150 + 150)
    assert sees("ignore_resists", p, [fire, cold])
    assert agree(prof({"SV_FIRE": 1}), [fire, cold, less]) == ["fire"]  # only the fire resist is scored


def test_items_of_other_classes_and_of_other_deities_are_dropped_first_and_replace_nothing():
    p = prof({"HP": 1})
    mine = make_item("mine", {"HEAD"}, stats={"HP": 10}, classes={"WAR"})
    other = make_item("other", {"HEAD"}, stats={"HP": 99}, classes={"MNK"})
    god = make_item("god", {"HEAD"}, stats={"HP": 98}, deity={"Brell"})
    report = prune_report([mine, other, god], p, 0, "stick", None, OPT)
    assert keys_of(report.kept) == ["mine"]
    assert report.dropped == {("other", 0): ("class", None), ("god", 0): ("deity", None)}
    assert agree(p, [mine, other, god]) == ["mine"]
    assert sees("ineligible_dominates", p, [mine, other, god])
    follower = SimpleNamespace(**{f.name: getattr(p, f.name) for f in dataclasses.fields(EvalProfile)}, deity="Brell")
    assert agree(follower, [mine, other, god]) == ["god"]  # the Brell item beats "mine" and replaces it
    stranger = SimpleNamespace(**{**follower.__dict__, "deity": "Tunare"})
    assert agree(stranger, [mine, god]) == ["mine"]


def test_items_that_exclude_the_scenario_race_are_dropped_first_and_replace_nothing():
    p = prof({"HP": 1})
    plain = make_item("plain", {"HEAD"}, stats={"HP": 10})
    humans = dataclasses.replace(make_item("humans", {"HEAD"}, stats={"HP": 99}), races=frozenset({"HUM"}))
    fields = {f.name: getattr(p, f.name) for f in dataclasses.fields(EvalProfile)}
    erudite, human = SimpleNamespace(**fields, race="ERU"), SimpleNamespace(**fields, race="HUM")
    report = prune_report([plain, humans], erudite, 0, "stick", None, OPT)
    assert keys_of(report.kept) == ["plain"] and report.dropped == {("humans", 0): ("race", None)}
    assert agree(erudite, [plain, humans]) == ["plain"]
    assert agree(human, [plain, humans]) == ["humans"]  # the human item beats "plain" and replaces it
    assert agree(p, [plain, humans]) == ["humans"]  # a profile with no race restricts nothing
    assert sees("ineligible_dominates", erudite, [plain, humans])  # an item the race cannot wear replaces nothing


def test_a_real_profile_is_read_by_attribute_for_its_deity_and_its_spell_haste():
    tables = load()
    profile = make_profile("OGR", ("PAL", "MNK", "BER"), 50, "balanced", None, None, tables, deity="Karana")
    assert profile.deity == "Karana"
    plain = make_item("plain", {"HEAD"}, stats={"HP": 10})
    blessed = make_item("blessed", {"HEAD"}, stats={"HP": 90}, deity={"Karana"})
    other = make_item("other", {"HEAD"}, stats={"HP": 80}, deity={"Tunare"})
    assert keys_of(prune([plain, blessed, other], profile, 0, "stick")) == ["blessed"]
    unaligned = dataclasses.replace(profile, deity=None)
    assert keys_of(prune([plain, blessed, other], unaligned, 0, "stick")) == ["plain"]
    # the default options: the Any rule "all" and the assumed haste from the profile's spell haste and the pool
    boots = make_item("boots", {"FEET"}, haste=20)
    hasty = dataclasses.replace(profile, spell_haste=30)
    report = prune_report([boots], hasty, 0, "2h")
    assert report.haste_assumed == 50 == build_milp(hasty, [boots], "2h").haste_assumed


def test_an_item_that_fits_no_group_is_dropped_as_having_no_place():
    p = prof({"HP": 1})
    ammo = make_item("ammo", {"AMMO"}, stats={"HP": 99})
    head = make_item("head", {"HEAD"}, stats={"HP": 5})
    every = BuildOptions(any_rule="all", haste_assumed=0)
    report = prune_report([ammo, head], p, 0, "stick", None, every)
    assert keys_of(report.kept) == ["head"] and report.dropped == {("ammo", 0): ("no-slot", None)}
    two_hander = make_item("axe", {"PRIMARY"}, weapon=AXE)
    assert fit_groups(two_hander, "dw") == frozenset({"ANY"})  # no hand takes it in dual wield; the Any group does
    assert fit_groups(two_hander, "dw", "explicit") == frozenset()
    assert fit_groups(two_hander, "2h") == frozenset({"PRIMARY", "ANY"})
    assert fit_groups(two_hander, None) == fit_groups(two_hander, "stick") == frozenset({"PRIMARY", "ANY"})


def test_the_any_group_follows_the_any_rule():
    p = prof({"HP": 1})
    head = make_item("head", {"HEAD"}, stats={"HP": 50})
    sticky = make_item("sticky", {"ANY"}, stats={"HP": 60})
    every = BuildOptions(any_rule="all", haste_assumed=0)
    assert agree(p, [head, sticky], options=OPT) == ["head", "sticky"]
    assert agree(p, [head, sticky], options=every) == ["head", "sticky"]  # sticky fits only Any; head fits both
    better_head = make_item("head2", {"HEAD"}, stats={"HP": 70})
    # "all": the better head piece fits the Any group too, so it replaces the Any piece; "explicit": it does not fit there
    assert agree(p, [head, better_head, sticky], options=every) == ["head2"]
    assert agree(p, [head, better_head, sticky], options=OPT) == ["head2", "sticky"]


def test_the_result_is_sorted_by_key_and_tier_the_input_is_left_alone_and_the_defaults_work():
    p = prof({"HP": 1, "END": 1})
    assert prune([], p, 0, "stick", None, OPT) == []
    items = [make_item(k, {"HEAD"}, stats={"STA": n}) for n, k in zip((1, 2, 3), "cba")]
    items += [make_item(k, {"NECK"}, stats={"HP": 7}) for k in "qp"]
    before = list(items)
    kept = prune(items, p, 0, "stick", None, OPT)
    assert items == before and [i.key for i in kept] == ["a", "p"]
    assert [i.key for i in prune(items, p, 0, "stick")] == ["a", "p"]  # no buff set, default options
    assert [i.key for i in prune(items[::-1], p, 0, "stick", None, OPT)] == ["a", "p"]


def test_bad_input_is_refused_like_the_builder_refuses_it():
    p = prof({"HP": 1})
    ok = make_item("ok", {"HEAD"}, stats={"HP": 1})
    with pytest.raises(ValueError, match="setup"):
        prune([ok], p, 0, "bow", None, OPT)
    with pytest.raises(ValueError, match="twice"):
        prune([ok, ok], p, 0, "stick", None, OPT)
    with pytest.raises(ValueError, match="unknown stat"):
        prune([make_item("bad", {"HEAD"}, stats={"LUCK": 3})], p, 0, "stick", None, OPT)
    with pytest.raises(ValueError, match="unknown resist"):
        prune([make_item("bad", {"HEAD"}, sv={"LUCK": 3})], p, 0, "stick", None, OPT)
    with pytest.raises(ValueError, match="tier"):
        prune([make_item("high", {"HEAD"}, tier=4)], p, 0, "stick", None, OPT)
    with pytest.raises(ValueError, match="tier"):
        prune([ok], p, "0", "stick", None, OPT)
    negative = prof({"HP": 1}, pools={
        "HP": (PoolSpec("WAR", 1500, -1.0), PoolSpec("CLR", 1320, 4.4), PoolSpec("ENC", 1200, 4.0)),
        "MANA": (), "END": (PoolSpec("WAR", 900, 4.5),),
    })
    with pytest.raises(ValueError, match="factor"):
        prune([ok], negative, 0, "stick", None, OPT)


# ---- the compared dimensions follow the weights ----------------------------------------------------------------------

EXPECTED_DIMENSIONS = {  # the one weight that is on -> the dimensions the builder's terms read, written out by hand
    "HP": {"HP", "STA"}, "AC": {"AC", "AGI"}, "MANA": {"MANA", "WIS", "INT"}, "ATK": {"ATK", "STR"}, "DEX": {"DEX"},
    "HASTE": {"HASTE"}, "END": {"END", "STR", "STA", "DEX", "AGI"}, "CHA": {"CHA"}, "HPREG": {"HPREG"},
    "MANAREG": {"MANAREG"}, "ENDREG": {"ENDREG"}, "DMG": {"DMG", "HASTE"},
    "SV": {f"SV_{s}" for s in fm.SCHOOLS}, "SV_FIRE": {"SV_FIRE"},
}


@pytest.mark.parametrize("weight", sorted(EXPECTED_DIMENSIONS))
def test_each_weight_scores_exactly_the_dimensions_the_builder_reads(weight):
    assert set(scored_dimensions(prof({weight: 1}), "2h")) == EXPECTED_DIMENSIONS[weight]


def test_the_weapon_term_is_off_in_the_stick_and_without_a_setup():
    p = prof({"DMG": 5})
    assert scored_dimensions(p, "stick") == () and scored_dimensions(p, None) == ()
    assert set(scored_dimensions(p, "dw")) == {"DMG", "HASTE"}
    assert scored_dimensions(prof({"DMG": 5, "HASTE": 1}), "stick") == ("HASTE",)


def test_a_pool_that_the_trio_does_not_have_scores_no_dimension():
    ogre = prof({"MANA": 1, "MANAREG": 1}, **PMB)
    assert set(scored_dimensions(ogre, "stick")) == {"MANA", "WIS", "MANAREG"}
    barbarian = prof({"MANA": 1, "MANAREG": 1}, trio=("WAR", "MNK", "ROG"), race="BAR")
    assert set(scored_dimensions(barbarian, "stick")) == {"MANAREG"}


def test_the_dimension_lists_cover_everything_an_item_can_carry_and_every_weight_scores_something():
    assert set(prune_module.STAT_DIMS) | {"AC"} == set(fm.ITEM_STATS)
    assert set(prune_module.SCHOOLS) == set(fm.SCHOOLS)
    assert set(ALL_WEIGHTS) | {f"SV_{s}" for s in fm.SCHOOLS} == set(fm.WEIGHT_KEYS)
    for weight in fm.WEIGHT_KEYS:
        assert scored_dimensions(prof({weight: 1}), "2h"), weight


BUMPS = {  # the dimension -> a function that makes an item better in that dimension only
    **{stat: (lambda item, stat=stat: dataclasses.replace(item, stats={**item.stats, stat: item.stats.get(stat, 0) + 3}))
       for stat in H.STAT_MENU},
    "HASTE": lambda item: dataclasses.replace(item, haste=item.haste + 10),
    **{
        f"SV_{s}": (lambda item, s=s: dataclasses.replace(item, sv={**item.sv, s: item.sv.get(s, 0) + 5}))
        for s in fm.SCHOOLS
    },
    "DMG": lambda item: dataclasses.replace(item, weapon=dataclasses.replace(item.weapon, dmg=item.weapon.dmg + 5)),
}


def place(item):
    kit = [None] * len(SLOT_INSTANCES)
    kit[SLOT_INSTANCES.index("PRIMARY")] = item
    return kit


@pytest.mark.parametrize("weight", sorted(EXPECTED_DIMENSIONS))
def test_the_oracle_moves_with_a_dimension_exactly_when_the_prune_scores_it(weight):
    p = prof({weight: 1})
    scored = set(scored_dimensions(p, "2h"))
    held = make_item("held", {"PRIMARY"}, weapon=AXE, stats={"AC": 10})
    base = evaluate(p, place(held), setup="2h", haste_assumed=20).F
    for name, bump in BUMPS.items():
        moved = evaluate(p, place(bump(held)), setup="2h", haste_assumed=20).F != base
        if moved:
            assert name in scored, f"{name} moves the value under the weight {weight} but is not scored"
        if name in EXPECTED_DIMENSIONS[weight] and not (weight == "DMG" and name == "HASTE"):
            assert moved, f"{name} does not move the value under the weight {weight}"


# ---- the pool is the builder's -----------------------------------------------------------------------------------------


@contextmanager
def trio_menu(menu):
    saved = H.TRIO_MENU
    H.TRIO_MENU = menu
    try:
        yield
    finally:
        H.TRIO_MENU = saved


def variant(rng, src, key):
    """An item made from ``src``: a twin, a better one, a worse one, a mixed one, a Lore flip, new slots or a new weapon."""
    kind = rng.choice(("twin", "better", "better", "worse", "worse", "worse", "mixed", "lore", "slots", "weapon", "hands"))
    stats, sv = dict(src.stats), dict(src.sv)
    haste, weight, lore, slots, weapon = src.haste, src.weight10, src.lore, set(src.slots), src.weapon
    shield = src.is_shield

    def bump(sign, count):
        for name in rng.sample(H.STAT_MENU, count):
            if src.is_shield and name != "AC":
                continue
            step = rng.randint(1, 12) * (10 if name in ("HP", "MANA", "END") else 1)
            stats[name] = stats.get(name, 0) + sign * step

    if kind == "better":
        bump(+1, rng.randint(1, 3))
        weight = max(0, weight - rng.choice((0, 0, 10, 40)))
        if rng.random() < 0.3:
            school = rng.choice(fm.SCHOOLS)
            sv[school] = sv.get(school, 0) + rng.randint(1, 20)
        if rng.random() < 0.3:
            haste += rng.randint(1, 15)
        if rng.random() < 0.3:
            lore = False
        if rng.random() < 0.2:
            slots.add(rng.choice(H.MODEL_SLOTS if rng.random() < 0.8 else ("ANY",)))
    elif kind == "worse":
        bump(-1, rng.randint(1, 3))
        weight += rng.choice((0, 10, 40))
        if rng.random() < 0.3:
            lore = True
        if rng.random() < 0.3 and sv:
            sv[next(iter(sorted(sv)))] -= rng.randint(1, 4)
        if rng.random() < 0.2 and len(slots) > 1:
            slots.discard(rng.choice(sorted(slots)))
        if rng.random() < 0.2:
            haste = max(0, haste - rng.randint(1, 15))
    elif kind == "mixed":
        bump(+1, 1)
        bump(-1, 1)
        weight += rng.choice((-10, 0, 10))
    elif kind == "lore":
        lore = not lore
    elif kind == "slots":
        if rng.random() < 0.6:
            slots.add(rng.choice(H.MODEL_SLOTS))
        elif len(slots) > 1:
            slots.discard(rng.choice(sorted(slots)))
    elif kind == "weapon" and weapon is not None:
        weapon = WeaponVec(
            weapon.skill, max(1, weapon.dmg + rng.randint(-6, 6)), rng.choice((weapon.delay, weapon.delay, 20, 40)),
            rng.choice((weapon.bonus, None, rng.randint(3, 30))), weapon.two_handed,
        )
    elif kind == "hands":  # the same item as a shield and a held piece, or as a one-hander and a two-hander
        if src.is_shield or (weapon is None and slots == {"SECONDARY"}):
            shield = not src.is_shield
            stats["AC"] = max(1, stats.get("AC", 0) + rng.randint(0, 6))
        elif weapon is not None:
            weapon = WeaponVec(
                "2H Slashing" if not weapon.two_handed else "1H Slashing", weapon.dmg, weapon.delay, weapon.bonus,
                not weapon.two_handed,
            )
            if rng.random() < 0.5:
                bump(+1, 1)
    return make_item(
        key, slots, stats=stats, sv=sv, haste=haste, weight10=weight, lore=lore, weapon=weapon, shield=shield,
        classes=src.classes, deity=src.deity,
    )


def prunable_pool(rng, inst, small=False):
    """Random items plus variants of them (twins, better, worse, Lore flips, other slots, other weapons) with the keys in
    a random order, so that either of two twins can have the smaller key; a few items that are for other classes or
    another deity. ``small`` pools are short enough to list every kit."""
    monk = inst.profile.monk is not None
    power = rng.choice((1.0, 1.0, 2.0, 3.5))
    setup = inst.setup or "stick"
    menu = ["HEAD", "NECK", "CHEST", "EAR", "FINGER", "WRIST", "ARMS", "HANDS", "PRIMARY", "SECONDARY"]
    groups = rng.sample(menu, rng.randint(2, 3) if small else rng.randint(3, 6))
    if setup != "stick" and "PRIMARY" not in groups:
        groups.append("PRIMARY")
    if setup in ("dw", "1h-shield") and "SECONDARY" not in groups:
        groups.append("SECONDARY")
    items = []
    for group in groups:
        for _ in range(rng.randint(1, 2) if small else rng.randint(2, 4)):
            items.append(H.random_item(rng, f"p{len(items):03d}", group, monk, power))
    if inst.any_rule == "explicit":
        for _ in range(rng.randint(0, 2)):
            items.append(make_item(
                f"p{len(items):03d}", {"ANY"} | ({rng.choice(groups)} if rng.random() < 0.4 else set()),
                stats={rng.choice(H.STAT_MENU): rng.randint(5, 60)}, weight10=rng.randint(0, 200), lore=rng.random() < 0.3,
            ))
    for _ in range(rng.randint(2, 4) if small else rng.randint(len(items) // 2, len(items))):
        items.append(variant(rng, rng.choice(items), f"p{len(items):03d}"))
    if not small:
        trio = {spec.cls for spec in fm.compile_profile(inst.profile).pools["HP"]}
        for _ in range(rng.choice((0, 0, 1, 2))):
            n = rng.randrange(len(items))
            if rng.random() < 0.5:
                items[n] = dataclasses.replace(items[n], deity=frozenset({rng.choice(("Ardent", "Bold"))}))
            else:
                items[n] = dataclasses.replace(items[n], classes=frozenset(CLASS_CODES) - trio)
    order = list(range(len(items)))
    rng.shuffle(order)
    items = [dataclasses.replace(item, key=f"p{order[n]:03d}", name=f"p{order[n]:03d}") for n, item in enumerate(items)]
    rng.shuffle(items)
    return items


def hand_pairs(seed, count=3):
    """Pairs that only the two-hander rule of the sweep keeps apart: an item that lists only the main hand, a two-hander
    that is at least as good in every dimension and lists the same hand, and a held item for the off hand that is worth
    more than the gain. Drawn from a generator of their own, so that the pools of a seed are the same with or without
    them."""
    rng = random.Random(seed + 7_000_003)
    items = []
    for _ in range(count):
        stats = {name: rng.randint(1, 12) * (10 if name in ("HP", "MANA", "END") else 1) for name in rng.sample(H.STAT_MENU, 3)}
        weight = rng.randint(0, 100)
        if rng.random() < 0.5:
            one = make_item(f"q{len(items):03d}", {"PRIMARY"}, stats=stats, weight10=weight, weapon=SWORD)
        else:
            one = make_item(f"q{len(items):03d}", {"PRIMARY"}, stats=stats, weight10=weight)  # a held item in the main hand
        items.append(one)
        better = {name: value + rng.randint(0, 3) for name, value in stats.items()}
        items.append(make_item(f"q{len(items):03d}", {"PRIMARY"}, stats=better, weight10=max(0, weight - rng.choice((0, 10))), weapon=AXE))
        held_stats = {name: rng.randint(3, 15) * (10 if name in ("HP", "MANA", "END") else 1) for name in rng.sample(H.STAT_MENU, 3)}
        items.append(make_item(f"q{len(items):03d}", {"SECONDARY"}, stats=held_stats, weight10=rng.randint(0, 100)))
    return items


def case(seed, trio_index=None, small=False, pairs=False, **kwargs):
    rng = random.Random(seed)
    with trio_menu(FOUR_TRIOS):
        inst = H.random_instance(rng, trio_index=seed % 4 if trio_index is None else trio_index, **kwargs)
    if rng.random() < 0.35:  # a low softcap: shields, which raise it, and worn armor class are worth different amounts
        softcap = (rng.choice((40, 90, 160, 300)), rng.choice((0.1, 0.25, 0.4)))
        inst.profile = dataclasses.replace(inst.profile, softcap=softcap)
    inst.items = prunable_pool(rng, inst, small)
    if not small and rng.random() < 0.3:  # a follower of the deity whose items some pools hold
        fields = {f.name: getattr(inst.profile, f.name) for f in dataclasses.fields(EvalProfile)}
        inst.profile = SimpleNamespace(**fields, deity="Ardent")
    if pairs:
        inst.items = inst.items + hand_pairs(seed)
    return inst


def options_of(inst, explicit_haste=True):
    return BuildOptions(any_rule=inst.any_rule, haste_assumed=inst.haste_assumed if explicit_haste else None)


def eligible_independent(inst, items):
    """The items the builder uses, decided here again: a class of the trio, and a deity the profile admits."""
    trio = {spec.cls for spec in fm.compile_profile(inst.profile).pools["HP"]}
    deity = getattr(inst.profile, "deity", None)
    return [i for i in items if i.classes & trio and (i.deity is None or (deity is not None and deity in i.deity))]


def test_the_columns_the_builder_makes_are_the_groups_prune_says_an_item_fits():
    checked = 0
    for seed in range(60):
        inst = case(seed, small=seed % 2 == 0)
        milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, options_of(inst))
        columns = {}
        for _, group, item in milp.item_cols:
            columns.setdefault((item.key, item.tier), set()).add(group)
        for item in milp.items:
            assert fit_groups(item, inst.setup, inst.any_rule) == frozenset(columns.get((item.key, item.tier), ())), seed
            checked += 1
    assert checked > 500


def test_prune_uses_the_items_the_builder_uses_and_the_assumed_haste_the_builder_assumes():
    for seed in range(80):
        inst = case(seed, small=seed % 3 == 0)
        for explicit in (True, False):
            options = options_of(inst, explicit)
            milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, options)
            report = prune_report(inst.items, inst.profile, 0, inst.setup, inst.buffset, options)
            assert {i.key for i in eligible_independent(inst, inst.items)} == {i.key for i in milp.items}, seed
            ineligible = {ident for ident, (reason, _) in report.dropped.items() if reason in ("class", "deity")}
            assert ineligible == {(i.key, i.tier) for i in inst.items} - {(i.key, i.tier) for i in milp.items}, seed
            assert report.haste_assumed == milp.haste_assumed, (seed, explicit)
            rebuilt = build_milp(inst.profile, list(report.kept), inst.setup, inst.buffset, options)
            assert rebuilt.haste_assumed == milp.haste_assumed or not ({"HASTE", "DMG"} & set(report.compared)), seed


def test_the_report_does_not_depend_on_the_order_of_the_pool():
    rng = random.Random(5)
    for seed in range(60):
        inst = case(seed, small=seed % 3 == 0)
        options = options_of(inst, explicit_haste=seed % 2 == 0)
        shuffled = list(inst.items)
        rng.shuffle(shuffled)
        one = prune_report(inst.items, inst.profile, 0, inst.setup, inst.buffset, options)
        two = prune_report(shuffled, inst.profile, 0, inst.setup, inst.buffset, options)
        assert one == two, seed  # the kept items, who replaced whom and why, the assumed haste, the dimensions


# ---- the sweep against the definition ---------------------------------------------------------------------------------


def contribution(item, group):
    """(worn armor class, off-hand shield armor class) that an item adds in a group."""
    ac = item.stats.get("AC", 0)
    return (0, ac) if (item.is_shield and group == "SECONDARY") else (ac, 0)


def naive_kept(inst, options):
    """The definition, item by item: B goes only if a plain item A can wear its places (a strict order, ties by key)."""
    report = prune_report(inst.items, inst.profile, 0, inst.setup, inst.buffset, options)
    p = fm.compile_profile(inst.profile)
    setup = inst.setup or "stick"
    compared = set(report.compared)
    pool = [
        i for i in eligible_independent(inst, inst.items)
        if any(H.fits(i, g, setup, options.any_rule) for g, _ in SLOT_GROUPS)
    ]
    fits = {id(i): frozenset(g for g, _ in SLOT_GROUPS if H.fits(i, g, setup, options.any_rule)) for i in pool}

    def index(item, group):
        return F(0) if item.weapon is None else fm.weapon_index(item.weapon, group, setup, report.haste_assumed, p.dw_factor)

    def two_handed(item):
        return item.weapon is not None and item.weapon.two_handed

    def can_replace(a, b):
        if a.lore or not fits[id(a)] >= fits[id(b)]:
            return False
        for name in compared:
            if name in prune_module.STAT_DIMS and a.stats.get(name, 0) < b.stats.get(name, 0):
                return False
            if name.startswith("SV_") and a.sv.get(name[3:], 0) < b.sv.get(name[3:], 0):
                return False
        if "HASTE" in compared and max(a.haste, 0) < max(b.haste, 0):
            return False
        for group in fits[id(b)]:
            if "AC" in compared and any(x < y for x, y in zip(contribution(a, group), contribution(b, group))):
                return False
            if "DMG" in compared and group in ("PRIMARY", "SECONDARY") and index(a, group) < index(b, group):
                return False
        if report.weight_rule == "le" and a.weight10 > b.weight10:
            return False
        if report.weight_rule == "eq" and a.weight10 != b.weight10:
            return False
        return not ("PRIMARY" in fits[id(b)] and two_handed(a) and not two_handed(b))

    ident = lambda i: (i.key, i.tier)  # noqa: E731
    plain = [i for i in pool if not i.lore]
    kept = []
    for b in pool:
        if b.lore:
            gone = any(can_replace(a, b) for a in plain)
        else:
            gone = any(can_replace(a, b) and (not can_replace(b, a) or ident(a) < ident(b)) for a in plain if a is not b)
        if not gone:
            kept.append(b)
    return sorted(ident(i) for i in kept), report


def test_the_sweep_finds_exactly_the_items_the_definition_keeps():
    with_drops = 0
    for seed in range(150):
        inst = case(seed, small=seed % 3 == 0)
        options = options_of(inst, explicit_haste=seed % 2 == 0)
        want, report = naive_kept(inst, options)
        assert sorted((i.key, i.tier) for i in report.kept) == want, f"seed {seed} ({inst.label})"
        with_drops += len(want) < len(eligible_independent(inst, inst.items))
    assert with_drops >= 120


# ---- exactness: random pools --------------------------------------------------------------------------------------------


@dataclasses.dataclass
class Outcome:
    ok: bool
    message: str = ""
    dropped: int = 0


def compare(inst, explicit_haste=True):
    """Solve the full pool and the pruned pool of an instance with the MILP; they must agree within 1e-9 relative."""
    options = options_of(inst, explicit_haste)
    kept = prune(inst.items, inst.profile, 0, inst.setup, inst.buffset, options)
    full = solve(build_milp(inst.profile, inst.items, inst.setup, inst.buffset, options))
    small = solve(build_milp(inst.profile, kept, inst.setup, inst.buffset, options))
    dropped = len(eligible_independent(inst, inst.items)) - len(kept)
    if full.status != "optimal" or small.status != "optimal":
        return Outcome(False, f"status {full.status} / {small.status}", dropped)
    if not close(full.F, small.F):
        return Outcome(False, f"full {full.F!r} against pruned {small.F!r}", dropped)
    return Outcome(True, "", dropped)


def run_seed(seed, **kwargs):
    inst = case(seed, **kwargs)
    outcome = compare(inst, explicit_haste=seed % 2 == 0)
    assert outcome.ok, f"seed {seed} ({inst.label}): {outcome.message}"
    return outcome


@settings(max_examples=300, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(seed=st.integers(0, 2**32 - 1))
def test_the_pruned_pool_has_the_optimum_of_the_full_pool_on_the_four_trio_types(seed):
    run_seed(seed)


@pytest.mark.parametrize("trio_index", range(len(FOUR_TRIOS)))
def test_every_trio_type_agrees_on_a_fixed_set_of_seeds(trio_index):
    dropped = sum(run_seed(7000 + 4 * k + trio_index, trio_index=trio_index).dropped for k in range(40))
    assert dropped > 40  # the pools do have things to drop


@pytest.mark.parametrize("setup", ["1h-shield", "2h", "dw", "stick"])
def test_every_weapon_setup_agrees_on_a_fixed_set_of_seeds(setup):
    for k in range(40):
        run_seed(9000 + k, setup=setup)


@pytest.mark.parametrize("setup", ["1h-shield", "2h", "dw", "stick"])
def test_pools_with_main_hand_items_and_better_two_handers_prune_exactly(setup):
    # the pairs of hand_pairs: a two-hander that lists the off hand does not fit it, and replaces what it can replace
    dropped = 0
    for k in range(40):
        inst = case(9500 + k, setup=setup, pairs=True)
        outcome = compare(inst, explicit_haste=k % 2 == 0)
        assert outcome.ok, f"seed {9500 + k} ({inst.label}): {outcome.message}"
        dropped += outcome.dropped
    assert dropped > 40


@settings(max_examples=120, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(seed=st.integers(0, 2**32 - 1), curve=st.sampled_from(["stand_in", "full_until_34"]))
def test_monk_weight_under_both_curves_and_both_placements_prunes_exactly(seed, curve):
    run_seed(seed, trio_index=0, monk_curve=curve)
    run_seed(seed + 1, trio_index=3, monk_curve=curve)


@settings(max_examples=100, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(seed=st.integers(0, 2**32 - 1))
def test_conflicting_haste_buffs_and_the_default_assumed_haste_prune_exactly(seed):
    inst = case(seed, haste_buffs=True)
    outcome = compare(inst, explicit_haste=False)
    assert outcome.ok, f"seed {seed} ({inst.label}): {outcome.message}"


def shrink(inst):
    """Drop random items until every legal kit of the pool can be listed."""
    rng = random.Random(len(inst.items))
    while H.option_product(inst.items, inst.setup, inst.any_rule) > 2 * H.KIT_LIMIT and len(inst.items) > 3:
        counts = {
            g: len(H.group_options(H.candidates(inst.items, g, inst.setup, inst.any_rule), size)) for g, size in SLOT_GROUPS
        }
        worst = max(counts, key=lambda g: counts[g])
        inst.items.remove(rng.choice([i for i in inst.items if H.fits(i, worst, inst.setup, inst.any_rule)]))


@settings(max_examples=250, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(seed=st.integers(0, 2**32 - 1))
def test_the_exact_brute_force_maximum_is_the_same_before_and_after_pruning(seed):
    # fractions, no solver: every legal kit and buff set of a pool short enough to list
    inst = case(seed, small=True)
    inst.items = eligible_independent(inst, inst.items)
    shrink(inst)
    kept = prune(inst.items, inst.profile, 0, inst.setup, inst.buffset, options_of(inst))
    before = H.Space(inst).best()[0]
    after = H.Space(dataclasses.replace(inst, items=kept)).best()[0]
    assert before == after, f"seed {seed} ({inst.label})"


def test_the_random_pools_lose_items_to_pruning_and_hold_every_kind_of_item():
    dropped = total = with_drop = 0
    kinds = dict.fromkeys(("lore", "twin", "haste", "multi", "weapon", "shield", "resist", "ineligible"), 0)
    for seed in range(60):
        inst = case(seed)
        eligible = eligible_independent(inst, inst.items)
        kept = prune(inst.items, inst.profile, 0, inst.setup, inst.buffset, options_of(inst))
        dropped += len(eligible) - len(kept)
        total += len(eligible)
        with_drop += len(eligible) > len(kept)
        kinds["ineligible"] += len(inst.items) - len(eligible)
        signatures = set()
        for item in inst.items:
            kinds["lore"] += item.lore
            kinds["haste"] += item.haste > 0
            kinds["multi"] += len(item.slots) > 1
            kinds["weapon"] += item.weapon is not None
            kinds["shield"] += item.is_shield
            kinds["resist"] += bool(item.sv)
            signature = (tuple(sorted(item.stats.items())), tuple(sorted(item.sv.items())), item.haste, item.weight10,
                         item.lore, tuple(sorted(item.slots)), item.weapon, item.is_shield)
            kinds["twin"] += signature in signatures
            signatures.add(signature)
    assert with_drop >= 50 and dropped >= 0.15 * total, (with_drop, dropped, total)
    assert all(count > 0 for count in kinds.values()), kinds


# ---- the oracle is monotone in what the prune compares ------------------------------------------------------------------


def random_kit(rng, items):
    kit = [None] * len(SLOT_INSTANCES)
    for index in rng.sample(range(len(kit)), rng.randint(1, 12)):
        fitting = [i for i in items if SLOT_INSTANCES[index] in i.slots]
        if fitting:
            kit[index] = rng.choice(fitting)
    return kit


@settings(max_examples=300, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(seed=st.integers(0, 2**32 - 1))
def test_the_value_never_falls_when_one_dimension_of_a_worn_item_gets_better(seed):
    rng = random.Random(seed)
    inst = case(seed)
    kit = random_kit(rng, inst.items)
    worn = [i for i, item in enumerate(kit) if item is not None]
    if not worn:
        return
    at = rng.choice(worn)
    item = kit[at]
    buffs = H.eval_totals(inst.buffset, ()) if inst.buffset is not None else None
    kwargs = dict(setup=inst.setup, haste_assumed=inst.haste_assumed)
    base = evaluate(inst.profile, kit, buffs, **kwargs).F
    for _ in range(8):
        better = rng.choice(("stat", "stat", "resist", "haste", "weight", "damage", "delay"))
        if better == "stat":
            name = rng.choice(H.STAT_MENU)
            changed = dataclasses.replace(item, stats={**item.stats, name: item.stats.get(name, 0) + rng.randint(1, 80)})
        elif better == "resist":
            school = rng.choice(fm.SCHOOLS)
            changed = dataclasses.replace(item, sv={**item.sv, school: item.sv.get(school, 0) + rng.randint(1, 120)})
        elif better == "haste":
            changed = dataclasses.replace(item, haste=item.haste + rng.randint(1, 60))
        elif better == "weight":
            changed = dataclasses.replace(item, weight10=max(0, item.weight10 - rng.randint(1, 300)))
        elif item.weapon is None:
            continue
        elif better == "damage":
            heavier = dataclasses.replace(item.weapon, dmg=item.weapon.dmg + rng.randint(1, 20))
            changed = dataclasses.replace(item, weapon=heavier)
        else:
            changed = dataclasses.replace(item, weapon=dataclasses.replace(item.weapon, delay=max(1, item.weapon.delay - 5)))
        other = list(kit)
        other[at] = changed
        assert evaluate(inst.profile, other, buffs, **kwargs).F >= base, (seed, better)


def test_every_stat_is_monotone_across_every_knee_of_every_curve():
    # one item with a growing stat on profiles that score everything: the value never falls from -30 to past 600
    for trio, race in (PMB.values(), (("WIZ", "MAG", "ENC"), "GNM"), (("SHD", "CLR", "SHM"), "DEF")):
        p = prof(dict.fromkeys(ALL_WEIGHTS, 1), trio=trio, race=race)
        for name in H.STAT_MENU:
            last = None
            for amount in list(range(-30, 140, 7)) + list(range(140, 620, 13)):
                value = evaluate(p, place(make_item("x", {"PRIMARY"}, stats={name: amount}))).F
                assert last is None or value >= last, (trio, name, amount)
                last = value


# ---- the rule broken on purpose -----------------------------------------------------------------------------------------


# the pools each broken rule needs to show itself in: a Monk for the weight, the stick for the two-hander row, ...
MUTATION_CASES = {
    "ignore_weight": {"trio_index": 0}, "ignore_two_hander": {"setup": "stick", "pairs": True},
    "ignore_shield": {"setup": "stick"}, "ignore_weapon": {"setup": "dw"},
}


@pytest.mark.parametrize("mutation", [m for m in prune_module.MUTATIONS if m])
def test_each_broken_rule_makes_the_random_suite_fail(mutation):
    """The suite must be able to see each error: with the rule broken, some random pool prunes to a pool whose optimum is
    lower than the full pool's (the hand-worked tests above see the same errors on their own cases)."""
    for seed in range(400):
        inst = case(seed, **MUTATION_CASES.get(mutation, {}))
        options = options_of(inst)
        right = keys_of(prune(inst.items, inst.profile, 0, inst.setup, inst.buffset, options))
        with broken(mutation):
            wrong = prune(inst.items, inst.profile, 0, inst.setup, inst.buffset, options)
        if keys_of(wrong) == right:
            continue
        full = solve(build_milp(inst.profile, inst.items, inst.setup, inst.buffset, options)).F
        if not close(full, solve(build_milp(inst.profile, wrong, inst.setup, inst.buffset, options)).F):
            return
    pytest.fail(f"no random pool noticed the broken rule {mutation!r}")


# ---- real data ---------------------------------------------------------------------------------------------------------

with warnings.catch_warnings():  # "slow" is not registered in the project's pytest settings; the mark still selects
    warnings.simplefilter("ignore", pytest.PytestUnknownMarkWarning)
    slow = pytest.mark.slow


def find_catalog():
    candidates = []
    if os.environ.get("TRIOFORGE_CATALOG"):
        candidates.append(Path(os.environ["TRIOFORGE_CATALOG"]))
    candidates.append(REPO / "derived" / "catalog.json")
    try:  # a worktree keeps the built data in the main checkout
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=REPO, capture_output=True, text=True,
            timeout=30, check=True,
        ).stdout.strip()
        candidates.append(Path(common).parent / "derived" / "catalog.json")
    except (OSError, subprocess.SubprocessError):
        pass
    return next((path for path in candidates if path.is_file()), None)


@slow
def test_the_real_pal_mnk_ber_ogre_wiki_pools_at_plus_four_prune_exactly(capsys):
    from trioforge.model.buffs import group_preset, own_buffs, resolve

    path = find_catalog()
    if path is None:
        pytest.skip("derived/catalog.json is not built")
    tables = load()
    rules = tables.rules
    trio = ("PAL", "MNK", "BER")
    spells = json.loads((REPO / "derived" / "client" / "spells-l50.json").read_text(encoding="utf-8"))
    buffset = resolve([*own_buffs(trio, 50, spells, rules), *group_preset(spells)], rules)
    profile = make_profile("OGR", trio, 50, "balanced", buffset, None, tables, evidence="wiki")
    catalog = json.loads(path.read_text(encoding="utf-8"))["items"]
    # the wiki level: strict items are wiki items by definition; temporary items and hand-in items are not candidates
    wanted = [
        item for item in catalog
        if item["evidence"]["level"] in ("strict", "wiki") and item["slots"]
        and not any(reason["code"] == "not-for-bis" for reason in item["evidence"]["reasons"])
    ]
    pool = [at_tier(item, 4, rules) for item in wanted]
    assert len(profile.setups) == 3
    lines = [f"pool {len(pool)} items at +4, {len(buffset.optional)} optional buffs"]
    for setup in profile.setups:
        kept = prune(pool, profile, 4, setup, buffset)
        started = time.perf_counter()
        full = build_milp(profile, pool, setup, buffset)
        full_build = time.perf_counter() - started
        started = time.perf_counter()
        full_solution = solve(full)
        full_time = time.perf_counter() - started
        started = time.perf_counter()
        small = build_milp(profile, kept, setup, buffset)
        small_build = time.perf_counter() - started
        started = time.perf_counter()
        small_solution = solve(small)
        small_time = time.perf_counter() - started
        assert full_solution.status == small_solution.status == "optimal"
        assert close(full_solution.F, small_solution.F), (setup, full_solution.F, small_solution.F)
        lines.append(
            f"{setup}: items {len(full.items)} -> {len(kept)}; item columns {full.info['items']} -> {small.info['items']}; "
            f"all columns {full.num_cols} -> {small.num_cols}; rows {full.num_rows} -> {small.num_rows}; "
            f"build {full_build:.1f}s -> {small_build:.1f}s; solve {full_time:.1f}s -> {small_time:.1f}s; "
            f"F {full_solution.F:.6f} = {small_solution.F:.6f}"
        )
    with capsys.disabled():
        print("\n" + "\n".join(lines))
