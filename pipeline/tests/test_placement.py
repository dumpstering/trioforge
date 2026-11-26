"""Tests for the canonical placement of a solution: ``trioforge.solver.solve.place_canonically``.

The solver decides which items are worn. Where an item that fits several groups stands (a cloak in the back place or in
an Any place, a ring in a finger place or in an Any place) changes nothing about the value of the kit, so the solver may
put it in either, and which one it takes depends on the order of its columns and the path of its search. The wrapper
puts the worn items that are not in a hand into their places by a rule that looks at the items alone: the items in the
order of their ``(key, tier)``, each into the earliest group (in the fixed slot order) that it fits and that still leaves
every other worn item a place. The hands have a rule of their own (see "the hands" below): the main and the off hand carry
the weapon index and the shield bonus, so only an arrangement worth exactly what the solver's is a candidate, and among those
the main hand is filled before it is left empty, by the smaller ``(key, tier)``, and then the off hand the same way.

Every name here is invented, except in the one real-data test, which reads the catalog and prints nothing about it.
"""

import dataclasses
import itertools
import json
import random
from collections import Counter
from fractions import Fraction

import pytest

import solver_helpers as H
from solver_helpers import make_item
from trioforge.model.buffs import group_preset, own_buffs, resolve
from trioforge.model.formulas import EvalProfile, PoolSpec, evaluate
from trioforge.model.items import SLOT_GROUPS, SLOT_INSTANCES, WeaponVec
from trioforge.model.profile import make_profile as real_profile
from trioforge.solver import solve as solve_module
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.solve import solve_canonical

F = Fraction
DW_FACTOR = F(4, 5)  # the dual-wield factor of production: with the evaluator's default of 1 the two hands are worth the same
NAKED_100 = {k: 100 for k in "STR STA AGI DEX WIS INT CHA".split()}
POOLS = {
    "HP": (PoolSpec("WAR", 1500, 5.0), PoolSpec("CLR", 1320, 4.4), PoolSpec("ENC", 1200, 4.0)),
    "MANA": (PoolSpec("CLR", 900, 4.5, "WIS"), PoolSpec("ENC", 900, 4.5, "INT")),
    "END": (PoolSpec("WAR", 900, 4.5), PoolSpec("CLR", 456, 3.25), PoolSpec("ENC", 260, 1.25)),
}


def profile(**changes):
    base = dict(level=50, naked=NAKED_100, weights={"HP": 1}, pools=POOLS)
    base.update(changes)
    return EvalProfile(**base)


def build(prof, items, setup="stick", buffset=None, **opts):
    return build_milp(prof, items, setup, buffset, BuildOptions(**{"any_rule": "explicit", "haste_assumed": 0, **opts}))


def keys_by_group(groups):
    """``{group: [keys]}`` of a ``{group: [items]}`` placement (empty groups left out)."""
    return {group: [item.key for item in placed] for group, placed in groups.items() if placed}


def placement(solution):
    """``((place, key), ...)`` of the worn items of a solution, in the order of the places."""
    return tuple((place, item.key) for place, item in zip(SLOT_INSTANCES, solution.kit) if item is not None)


def cloaks(keys=("c1", "c2", "c3")):
    return [make_item(key, {"BACK"}, stats={"HP": 30}, lore=True) for key in keys]


# ---- the rule, on placements written out by hand -----------------------------------------------------------------


def test_every_worn_item_goes_to_the_earliest_group_it_fits_by_key_whatever_the_solver_chose():
    three = cloaks()
    milp = build(profile(), three, any_rule="all")  # a back place and two Any places for the three cloaks
    want = {"BACK": ["c1"], "ANY": ["c2", "c3"]}
    for back in three:
        any_places = [c for c in three if c is not back]
        got = solve_module.place_canonically(milp, {"BACK": [back], "ANY": any_places})
        assert keys_by_group(got) == want, back.key


def test_an_item_that_must_take_a_group_is_not_pushed_out_of_it_by_an_earlier_key():
    # x lists the back and the Any group, y only the back: by key x would go first and take the back place, and y would
    # have none. The rule gives every other item a place first.
    x = make_item("a-x", {"BACK", "ANY"}, stats={"HP": 50}, lore=True)
    y = make_item("b-y", {"BACK"}, stats={"HP": 40}, lore=True)
    milp = build(profile(), [x, y])
    assert keys_by_group(solve_module.place_canonically(milp, {"BACK": [y], "ANY": [x]})) == {"BACK": ["b-y"], "ANY": ["a-x"]}


def test_copies_of_one_item_fill_the_earliest_groups_first_and_equal_keys_are_told_apart_by_tier():
    ring = make_item("ring", {"FINGER", "ANY"}, stats={"HP": 10})
    low = dataclasses.replace(make_item("ring", {"FINGER", "ANY"}, stats={"HP": 10}), tier=2)
    milp = build(profile(), [ring, low])
    got = solve_module.place_canonically(milp, {"ANY": [ring, low], "FINGER": [ring, ring]})
    assert [(i.key, i.tier) for i in got["FINGER"]] == [("ring", 0), ("ring", 0)]
    assert [(i.key, i.tier) for i in got["ANY"]] == [("ring", 0), ("ring", 2)]


def test_the_hands_stay_as_the_solver_chose_them_even_when_an_earlier_group_would_take_the_item():
    # in the slot order the Any group comes before the hands, and every item that fits a hand fits the Any group under the
    # "all" rule: the hands are not part of that rule, since they carry the weapon index and the shield bonus (here every
    # other arrangement of these items is worth a different amount, so the hands stay as they are; the rule for the hands
    # that are worth the same is below; the profile has the production dual-wield factor, because with the evaluator's own
    # default of 1 a sword and a dagger are worth the same in either hand)
    sword = make_item("sword", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("1H Slashing", 20, 30, None, False))
    dagger = make_item("dagger", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("Piercing", 8, 20, None, False))
    club = make_item("club", {"PRIMARY"}, weapon=WeaponVec("1H Blunt", 12, 30, None, False))
    cloak = make_item("cloak", {"BACK"}, stats={"HP": 10})
    milp = build(profile(weights={"HP": 1, "DMG": 50}, dw_factor=DW_FACTOR), [sword, dagger, club, cloak], "dw", any_rule="all")
    got = solve_module.place_canonically(milp, {"PRIMARY": [sword], "SECONDARY": [dagger], "ANY": [club, cloak]})
    assert keys_by_group(got) == {"BACK": ["cloak"], "PRIMARY": ["sword"], "SECONDARY": ["dagger"], "ANY": ["club"]}


def test_a_placement_with_no_item_to_move_is_returned_as_it_is():
    milp = build(profile(), cloaks())
    assert solve_module.place_canonically(milp, {}) == {}
    only_hands = {"PRIMARY": [make_item("h", {"PRIMARY"})]}
    assert keys_by_group(solve_module.place_canonically(milp, only_hands)) == {"PRIMARY": ["h"]}


# ---- through the solver --------------------------------------------------------------------------------------------


def test_the_solved_kit_uses_the_rule_whatever_the_order_of_the_pool_and_the_inert_items_around_it():
    three = cloaks()
    seen = set()
    for run, order in enumerate(itertools.permutations(three)):
        pool = list(order)
        for n in range(run % 4):  # inert items (no stat, no weight) with keys all over the sorted order
            pool.append(make_item(f"{'abcxyz'[(run + n) % 6]}-junk{run}{n}", {"FINGER"}))
        random.Random(run).shuffle(pool)
        solution = solve_canonical(build(profile(), pool, any_rule="all"))
        seen.add(placement(solution))
    assert seen == {(("BACK", "c1"), ("ANY", "c2"), ("ANY", "c3"))}


def test_placing_the_items_never_changes_the_value_of_the_kit():
    # the exactness check of the wrapper would raise if a move changed the value; the oracle says it directly
    solution = solve_canonical(build(profile(), cloaks(), any_rule="all"))
    assert solution.breakdown == evaluate(profile(), list(solution.kit))


def varying_instance(seed):
    return H.random_instance(random.Random(seed), any_rule="all", with_buffs=True)


def solved_variants(inst, count=5):
    """The canonical solutions of ``inst`` with the pool and the optional buffs in ``count`` different orders."""
    out = []
    for k in range(count):
        optional = list(inst.buffset.optional)
        random.Random(k).shuffle(optional)
        buffset = dataclasses.replace(inst.buffset, optional=tuple(optional))
        items = list(inst.items)
        random.Random(100 + k).shuffle(items)
        out.append(solve_canonical(build_milp(inst.profile, items, inst.setup, buffset, BuildOptions(**inst.options_kwargs()))))
    return out


@pytest.mark.parametrize("seed", [117, 188])
def test_reordering_the_optional_buffs_and_the_pool_never_changes_the_placement(seed):
    # two instances (found by search) whose placement used to follow the order of the buffs: an item that fits a finger
    # place and an Any place, a cloak that fits the neck place and an Any place
    inst = varying_instance(seed)
    assert len(inst.buffset.optional) >= 2
    placements = {placement(solution) for solution in solved_variants(inst)}
    assert len(placements) == 1, placements


def test_over_many_instances_the_same_items_are_always_in_the_same_places():
    compared = 0
    for seed in [*range(60), 117, 188]:
        inst = varying_instance(seed)
        if inst.buffset is None or len(inst.buffset.optional) < 2:
            continue
        by_items = {}
        for solution in solved_variants(inst, 3):
            worn = tuple(sorted((item.key, item.tier) for item in solution.kit if item is not None))
            by_items.setdefault((worn, solution.buffs), set()).add(placement(solution))
        # a kit and a buff set that came out more than once came out in one arrangement
        assert all(len(arrangements) == 1 for arrangements in by_items.values()), (seed, by_items)
        compared += 1
    assert compared >= 15


# ---- the hands -----------------------------------------------------------------------------------------------------
#
# Where the worn items stand changes the value of a kit only through the two hands: the weapon index of what is in them
# and the shield bonus of an off-hand shield. Among the arrangements of the same items that the builder allows and that
# are worth exactly what the solver's is, the hands are filled by one rule that looks at the items alone: the main hand
# is filled before it is left empty, by the smaller (key, tier); then the off hand the same way. Two engines that choose
# the same items therefore end with the same kit, place for place.

HAND_INDEX = (SLOT_INSTANCES.index("PRIMARY"), SLOT_INSTANCES.index("SECONDARY"))


def one_handers(*keys, tier=0, slots=("PRIMARY", "SECONDARY"), lore=False):
    """One-handed weapons that are worth the same wherever they stand when no damage is scored (the stick setup)."""
    return [
        make_item(key, set(slots), stats={"HP": 10}, weapon=WeaponVec("1H Slashing", 10, 30, None, False), tier=tier, lore=lore)
        for key in keys
    ]


def worn_of(groups):
    return sorted((item.key, item.tier) for placed in groups.values() for item in placed)


def names_of(kit):
    """``(key, tier)`` or None for each entry of a kit."""
    return [None if item is None else (item.key, item.tier) for item in kit]


def test_the_hands_are_filled_main_hand_first_by_the_smaller_key_whatever_the_solver_chose():
    three = one_handers("axe", "mace", "sword")
    milp = build(profile(), three, any_rule="all")  # the hands and two Any places for three weapons that are worth the same
    want = {"PRIMARY": ["axe"], "SECONDARY": ["mace"], "ANY": ["sword"]}
    seen = 0
    for places in itertools.permutations(["PRIMARY", "SECONDARY", "ANY", "ANY"], 3):
        groups = {}
        for item, place in zip(three, places):
            groups.setdefault(place, []).append(item)
        got = solve_module.place_canonically(milp, groups)
        assert keys_by_group(got) == want, groups
        assert worn_of(got) == worn_of(groups)
        assert evaluate(profile(), H.kit_from_groups(got), None) == evaluate(profile(), H.kit_from_groups(groups), None)
        seen += 1
    assert seen == 24


def test_a_hand_is_filled_when_it_can_be_though_the_solver_left_it_empty():
    axe, mace = one_handers("axe", "mace")
    milp = build(profile(), [axe, mace], any_rule="all")
    assert keys_by_group(solve_module.place_canonically(milp, {"ANY": [axe, mace]})) == {"PRIMARY": ["axe"], "SECONDARY": ["mace"]}
    assert keys_by_group(solve_module.place_canonically(milp, {"ANY": [mace]})) == {"PRIMARY": ["mace"]}


def test_equal_keys_are_told_apart_by_tier_in_the_hands():
    low, high = one_handers("axe", tier=2)[0], one_handers("axe", tier=4)[0]
    milp = build(profile(), [low, high])
    got = solve_module.place_canonically(milp, {"PRIMARY": [high], "SECONDARY": [low]})
    assert [(item.key, item.tier) for item in got["PRIMARY"]] == [("axe", 2)]
    assert [(item.key, item.tier) for item in got["SECONDARY"]] == [("axe", 4)]


def test_an_arrangement_worth_more_or_less_is_never_taken_whatever_the_keys_say():
    big = make_item("zz-big", {"PRIMARY", "SECONDARY"}, stats={"HP": 10}, weapon=WeaponVec("1H Slashing", 20, 30, None, False))
    small = make_item("aa-small", {"PRIMARY", "SECONDARY"}, stats={"HP": 10}, weapon=WeaponVec("1H Slashing", 8, 20, None, False))
    milp = build(profile(weights={"HP": 1, "DMG": 50}, dw_factor=DW_FACTOR), [big, small], "dw", any_rule="all")
    # the best arrangement stays: the main hand carries the damage bonus, so the stronger weapon is worth more there
    best = {"PRIMARY": [big], "SECONDARY": [small]}
    assert keys_by_group(solve_module.place_canonically(milp, best)) == {"PRIMARY": ["zz-big"], "SECONDARY": ["aa-small"]}
    # a worse one is not "improved" either: the only candidates are the arrangements worth exactly what the solver's is
    worse = {"PRIMARY": [small], "SECONDARY": [big]}
    assert keys_by_group(solve_module.place_canonically(milp, worse)) == {"PRIMARY": ["aa-small"], "SECONDARY": ["zz-big"]}
    # a weapon in an Any place scores nothing, and a kit that holds it in a hand is worth more: that is another kit
    held = {"PRIMARY": [big], "ANY": [small]}
    assert keys_by_group(solve_module.place_canonically(milp, held)) == {"PRIMARY": ["zz-big"], "ANY": ["aa-small"]}


def test_two_weapons_of_the_same_index_are_told_apart_by_key_only_among_themselves():
    # the index of a weapon is what it adds in a hand: two with the same damage and delay are alike, a third is not
    alike = one_handers("b-alike", "c-alike")
    other = make_item("a-other", {"PRIMARY", "SECONDARY"}, stats={"HP": 10}, weapon=WeaponVec("1H Slashing", 4, 30, None, False))
    milp = build(profile(weights={"HP": 1, "DMG": 50}, dw_factor=DW_FACTOR), [*alike, other], "dw", any_rule="all")
    got = solve_module.place_canonically(milp, {"PRIMARY": [alike[1]], "SECONDARY": [alike[0]], "ANY": [other]})
    assert keys_by_group(got) == {"PRIMARY": ["b-alike"], "SECONDARY": ["c-alike"], "ANY": ["a-other"]}


def test_a_two_hander_leaves_the_off_hand_empty_and_never_stands_in_it():
    axe = make_item("axe-2h", {"PRIMARY"}, stats={"HP": 10}, weapon=WeaponVec("2H Slashing", 20, 40, None, True))
    sword = make_item("sword", {"PRIMARY", "SECONDARY"}, stats={"HP": 10}, weapon=WeaponVec("1H Slashing", 10, 30, None, False))
    milp = build(profile(), [axe, sword], any_rule="all")
    # by key the two-hander is first, and with it in the main hand the sword cannot take the off hand: the next arrangement
    # in the order is the two-hander alone in the hands
    for groups in ({"PRIMARY": [sword], "ANY": [axe]}, {"PRIMARY": [axe], "ANY": [sword]}, {"ANY": [axe, sword]}):
        assert keys_by_group(solve_module.place_canonically(milp, groups)) == {"PRIMARY": ["axe-2h"], "ANY": ["sword"]}, groups
    # with a one-hander whose key is first, that one takes the main hand, and the two-hander has no hand at all to stand in
    lone = make_item("a-lone", {"PRIMARY", "SECONDARY"}, stats={"HP": 10}, weapon=WeaponVec("1H Slashing", 10, 30, None, False))
    milp = build(profile(), [axe, lone], any_rule="all")
    assert keys_by_group(solve_module.place_canonically(milp, {"ANY": [axe, lone]})) == {"PRIMARY": ["a-lone"], "ANY": ["axe-2h"]}


def test_the_setup_decides_what_may_stand_in_the_off_hand():
    sword, dagger = one_handers("a-sword", "b-dagger")
    guard = make_item("c-guard", {"SECONDARY"}, stats={"HP": 10}, shield=True)
    milp = build(profile(), [sword, dagger, guard], "1h-shield", any_rule="all")
    got = solve_module.place_canonically(milp, {"PRIMARY": [dagger], "ANY": [sword, guard]})
    assert keys_by_group(got) == {"PRIMARY": ["a-sword"], "SECONDARY": ["c-guard"], "ANY": ["b-dagger"]}
    # no weapon may take the off hand under the shield setup, though the sword and the dagger both list it
    weapons = build(profile(), [sword, dagger], "1h-shield", any_rule="all")
    assert keys_by_group(solve_module.place_canonically(weapons, {"PRIMARY": [dagger], "ANY": [sword]})) == {
        "PRIMARY": ["a-sword"], "ANY": ["b-dagger"]
    }


def test_two_copies_of_one_item_may_fill_both_hands_and_one_copy_only_one():
    (dagger,) = one_handers("dagger")
    milp = build(profile(), [dagger], "dw", any_rule="all")
    both = solve_module.place_canonically(milp, {"ANY": [dagger, dagger]})
    assert keys_by_group(both) == {"PRIMARY": ["dagger"], "SECONDARY": ["dagger"]}
    assert keys_by_group(solve_module.place_canonically(milp, {"ANY": [dagger]})) == {"PRIMARY": ["dagger"]}


def test_an_arrangement_that_leaves_an_item_without_a_place_is_not_one():
    (dagger,) = one_handers("a-dagger")  # either hand
    club = make_item("b-club", {"PRIMARY"}, stats={"HP": 10}, weapon=WeaponVec("1H Blunt", 12, 30, None, False))  # the main hand only
    milp = build(profile(), [dagger, club])  # the explicit rule: no Any place takes either
    got = solve_module.place_canonically(milp, {"PRIMARY": [club], "SECONDARY": [dagger]})
    assert keys_by_group(got) == {"PRIMARY": ["b-club"], "SECONDARY": ["a-dagger"]}  # the dagger first would leave the club nowhere


def test_only_the_arrangements_before_the_solvers_in_the_order_are_valued(monkeypatch):
    axe, mace, sword = three = one_handers("axe", "mace", "sword")
    milp = build(profile(), three, any_rule="all")
    calls = []
    real = solve_module.fm.evaluate
    monkeypatch.setattr(solve_module.fm, "evaluate", lambda *a, **k: calls.append(1) or real(*a, **k))
    solve_module.place_canonically(milp, {"PRIMARY": [axe], "SECONDARY": [mace], "ANY": [sword]})
    assert calls == []  # the solver's arrangement is the first of the order: there is nothing to compare it with
    solve_module.place_canonically(milp, {"PRIMARY": [mace], "SECONDARY": [axe], "ANY": [sword]})
    assert len(calls) == 2  # its own value, and the first arrangement of the order, which is worth as much: no more


def test_a_rearrangement_that_changes_the_items_or_the_value_is_refused():
    a, b = one_handers("a", "b")
    check = solve_module._check_rearranged
    check({"ANY": [a, b]}, {"PRIMARY": [b], "SECONDARY": [a]}, F(5), F(5))
    check({"ANY": [a, b]}, {"PRIMARY": [b], "SECONDARY": [a]}, None, F(5))  # the hands were left as they were: no value to compare
    with pytest.raises(solve_module.PlacementError, match="items"):
        check({"ANY": [a, b]}, {"PRIMARY": [b]}, F(5), F(5))
    with pytest.raises(solve_module.PlacementError, match="items"):
        check({"ANY": [a, a]}, {"PRIMARY": [a], "SECONDARY": [b]}, F(5), F(5))
    with pytest.raises(solve_module.PlacementError, match="value"):
        check({"ANY": [a, b]}, {"PRIMARY": [b], "SECONDARY": [a]}, F(5), F(6))


def test_the_solver_wrapper_refuses_a_placement_that_changed_the_items(monkeypatch):
    three = one_handers("axe", "mace", "sword")
    milp = build(profile(), three, any_rule="all")
    monkeypatch.setattr(solve_module, "_place", lambda milp, groups, buffs: ({"PRIMARY": [three[0]]}, None))
    with pytest.raises(solve_module.PlacementError):
        solve_canonical(milp)


# ---- the hands, against an enumeration written out again -------------------------------------------------------------


def tied_instance(seed):
    """A small instance whose weapons are worth the same in some hands, so that the solver has arrangements to choose
    from: a setup, the Any rule, 3 to 6 weapons and shields (mostly Lore, so that the kit holds different ones; some
    with equal damage and delay) and plain weights."""
    rng = random.Random(seed)
    setup = rng.choice(("stick", "stick", "dw", "1h-shield", "2h"))
    any_rule = rng.choice(("all", "explicit"))
    one, two = WeaponVec("1H Slashing", 10, 30, None, False), WeaponVec("2H Slashing", 24, 50, None, True)
    items = []
    for n in range(rng.randint(3, 6)):
        key = f"{rng.choice('abcdefgh')}{n}"
        lore = rng.random() < 0.85
        if setup == "2h" or (setup == "stick" and rng.random() < 0.3):
            items.append(make_item(key, {"PRIMARY"}, stats={"HP": 10}, weapon=two, lore=lore))
        elif setup == "1h-shield" and rng.random() < 0.4:
            items.append(make_item(key, {"SECONDARY"}, stats={"HP": 10}, shield=True, lore=lore))
        else:
            slots = rng.choice((("PRIMARY", "SECONDARY"), ("PRIMARY", "SECONDARY"), ("PRIMARY",)))
            weapon = one if rng.random() < 0.7 else WeaponVec("1H Blunt", rng.choice((6, 10, 14)), 30, None, False)
            items.append(make_item(key, set(slots), stats={"HP": 10}, weapon=weapon, lore=lore))
    if any_rule == "explicit":
        items += [make_item(f"z{n}", {"ANY"}, stats={"HP": 7}, lore=True) for n in range(rng.randint(0, 3))]
    return setup, any_rule, items, profile(weights={"HP": 1, "DMG": rng.choice((0, 0, 40))})


def legal_hands(worn, setup, any_rule):
    """Every ``(main hand, off hand, assignment of the rest)`` of the worn items that a kit may have, in the order of the
    rule, written out from the helpers of the brute force: the item fits the hand under the setup, a pair needs two copies
    of an item that is in both, a two-hander leaves the off hand empty, and what is left can stand outside the hands."""
    copies = Counter((item.key, item.tier) for item in worn)
    by_name = {(item.key, item.tier): item for item in worn}
    keyed = [by_name[name] for name in sorted(by_name)]
    outside = [group for group, _ in SLOT_GROUPS if group not in H.HANDS]

    def assign(rest):
        room = {group: H.GROUP_SIZE[group] for group in outside}
        stood = {}

        def go(n):
            if n == len(rest):
                return True
            for group in outside:
                if room[group] and H.fits(rest[n], group, setup, any_rule):
                    room[group] -= 1
                    stood.setdefault(group, []).append(rest[n])
                    if go(n + 1):
                        return True
                    stood[group].pop()
                    room[group] += 1
            return False

        return stood if go(0) else None

    found = []
    for main in [*(i for i in keyed if H.fits(i, "PRIMARY", setup, any_rule)), None]:
        for off in [*(i for i in keyed if H.fits(i, "SECONDARY", setup, any_rule)), None]:
            need = Counter((i.key, i.tier) for i in (main, off) if i is not None)
            if any(need[name] > copies[name] for name in need):
                continue
            if main is not None and main.weapon is not None and main.weapon.two_handed and off is not None:
                continue
            stood = assign([by_name[name] for name in (copies - need).elements()])
            if stood is not None:
                found.append((main, off, stood))
    return found


def value_of(prof, main, off, stood, setup, totals=None):
    kit = H.kit_from_groups({**stood, "PRIMARY": [main] if main else [], "SECONDARY": [off] if off else []})
    return evaluate(prof, kit, totals, setup=setup, haste_assumed=0).F


@pytest.mark.parametrize("seed", range(60))
def test_the_solved_hands_are_the_first_arrangement_of_the_rule_that_is_worth_as_much(seed):
    setup, any_rule, items, prof = tied_instance(seed)
    solution = solve_canonical(build(prof, items, setup, any_rule=any_rule))
    assert solution.status == "optimal" and solution.tie_stage in ("applied", "kept-first")
    worn = [item for item in solution.kit if item is not None]
    main, off = next(
        (main, off) for main, off, stood in legal_hands(worn, setup, any_rule) if value_of(prof, main, off, stood, setup) == solution.breakdown.F
    )
    assert names_of([solution.kit[i] for i in HAND_INDEX]) == names_of([main, off])


@pytest.mark.parametrize("seed", range(30))
def test_every_arrangement_the_solver_could_have_chosen_gives_the_same_kit(seed):
    # the canonical kit depends on the items alone: every way to stand the same items that is worth as much as the solver's
    # (each one a solver may return) is placed to the same kit, place for place
    setup, any_rule, items, prof = tied_instance(seed)
    milp = build(prof, items, setup, any_rule=any_rule)
    solution = solve_canonical(milp)
    worn = [item for item in solution.kit if item is not None]
    arrangements = 0
    for main, off, stood in legal_hands(worn, setup, any_rule):
        if value_of(prof, main, off, stood, setup) != solution.breakdown.F:
            continue
        groups = {"PRIMARY": [main] if main else [], "SECONDARY": [off] if off else [], **stood}
        got = H.kit_from_groups(solve_module.place_canonically(milp, groups))
        assert names_of(got) == names_of(solution.kit)
        arrangements += 1
    assert arrangements >= 1


def test_the_tie_heavy_instances_do_have_arrangements_to_choose_from():
    # a check of the generator: the two searches above are worth something only if the solver often had a choice
    choices = 0
    for seed in range(60):
        setup, any_rule, items, prof = tied_instance(seed)
        solution = solve_canonical(build(prof, items, setup, any_rule=any_rule))
        worn = [item for item in solution.kit if item is not None]
        equal = [
            1 for main, off, stood in legal_hands(worn, setup, any_rule)
            if value_of(prof, main, off, stood, setup) == solution.breakdown.F
        ]  # fmt: skip
        choices += len(equal) > 1
    assert choices >= 20


def test_the_hands_of_the_solved_kit_do_not_depend_on_the_order_of_the_pool():
    pool = one_handers("k1", "k2", "k3", "k4", "k5", lore=True)  # Lore: the kit holds four different ones, not four copies of the first
    seen = set()
    for run in range(8):
        shuffled = list(pool)
        random.Random(run).shuffle(shuffled)
        seen.add(placement(solve_canonical(build(profile(), shuffled, any_rule="all"))))
    assert seen == {(("ANY", "k3"), ("ANY", "k4"), ("PRIMARY", "k1"), ("SECONDARY", "k2"))}


def test_the_arrangements_are_valued_under_the_chosen_buffs_and_a_caller_that_omits_them_is_refused():
    # a shield in an Any place is worth the same as one in the off hand while the sheet armor class is under its softcap, and less once a buff
    # takes the sheet past it: which buffs are chosen decides whether the shield moves
    guard = make_item("guard", {"SECONDARY"}, stats={"AC": 30}, shield=True, lore=True)
    softcap = profile(weights={"HP": 1, "AC": 6}, softcap=(60, F(1, 4)))
    buffset = H.make_buffset(optional=(H.make_buff(7, AC=200),))
    milp = build(softcap, [guard], "stick", buffset, any_rule="all")
    assert set(milp.buff_cols.values()) == {7}
    assert keys_by_group(solve_module.place_canonically(milp, {"ANY": [guard]}, ())) == {"SECONDARY": ["guard"]}
    assert keys_by_group(solve_module.place_canonically(milp, {"ANY": [guard]}, (7,))) == {"ANY": ["guard"]}
    with pytest.raises(ValueError, match="buffs"):
        solve_module.place_canonically(milp, {"ANY": [guard]})  # the arrangements would be valued under the wrong buff totals
    with pytest.raises(ValueError, match="buffs"):
        solve_module.place_canonically(milp, {"ANY": [guard]}, None)


def test_the_buffs_may_be_left_out_when_the_model_has_no_optional_buff():
    guard = make_item("guard", {"SECONDARY"}, stats={"AC": 30}, shield=True, lore=True)
    always = H.make_buffset(always=(H.make_buff(3, HP=5),))
    for buffset in (None, always):  # no buff set, and a set of buffs that are always on
        softcap = profile(weights={"HP": 1, "AC": 6}, softcap=(60, F(1, 4)), buff_totals=H.eval_totals(buffset))
        milp = build(softcap, [guard], "stick", buffset, any_rule="all")
        assert not milp.buff_cols
        assert keys_by_group(solve_module.place_canonically(milp, {"ANY": [guard]})) == {"SECONDARY": ["guard"]}
        assert keys_by_group(solve_module.place_canonically(milp, {"ANY": [guard]}, ())) == {"SECONDARY": ["guard"]}


def test_the_solved_kit_is_placed_under_the_buffs_it_was_solved_with():
    # the wrapper passes the chosen buffs: with the buff on, the sheet is past its softcap and the shield stands in the off hand because it is worth more there
    guard = make_item("guard", {"SECONDARY"}, stats={"AC": 30}, shield=True, lore=True)
    softcap = profile(weights={"HP": 1, "AC": 6}, softcap=(60, F(1, 4)))
    milp = build(softcap, [guard], "stick", H.make_buffset(optional=(H.make_buff(7, AC=200),)), any_rule="all")
    solution = solve_canonical(milp)
    assert solution.buffs == (7,) and placement(solution) == (("SECONDARY", "guard"),)
    assert solution.breakdown == evaluate(softcap, list(solution.kit), H.eval_totals(milp.buffset, (7,)), setup="stick", haste_assumed=0)


def test_another_search_path_ends_in_the_same_kit_place_for_place():
    # the property the hands are for: two runs of the solver that search differently (presolve on and off stand for two engines)
    # end in the same kit, hands and Any places included. With the hands left as the solver chose them, 18 of these 100 differed.
    for seed in range(100):
        setup, any_rule, items, prof = tied_instance(seed)
        milp = build(prof, items, setup, any_rule=any_rule)
        plain, searched = solve_canonical(milp), solve_canonical(milp, highs_options={"presolve": "on"})
        assert names_of(plain.kit) == names_of(searched.kit), (seed, setup, any_rule)
        assert plain.breakdown.F == searched.breakdown.F and plain.buffs == searched.buffs


# ---- real data -----------------------------------------------------------------------------------------------------


@H.slow
def test_the_real_pool_of_an_iksar_trio_is_placed_the_same_for_every_order_of_its_optional_buffs():
    # the reviewer's case: a non-Lore cloak and a Lore cloak, both for the back place, and two Any places; the order of
    # the optional buffs used to decide which of them stood in the back place
    trio = ("MNK", "SHM", "NEC")
    spells = json.loads((H.REPO / "derived" / "client" / "spells-l55.json").read_text(encoding="utf-8"))
    buffset = resolve([*own_buffs(trio, 55, spells, H.TABLES.rules), *group_preset(spells)], H.TABLES.rules)
    prof = real_profile("IKS", trio, 55, "melee", buffset, None, H.TABLES)
    pool = H.catalog_pool(trio, 4)
    placements, worn = set(), set()
    for k in range(6):
        optional = list(buffset.optional)
        random.Random(k).shuffle(optional)
        solution = solve_canonical(build_milp(prof, pool, "stick", dataclasses.replace(buffset, optional=tuple(optional))))
        placements.add(placement(solution))
        worn.add(tuple(sorted((item.key, item.tier) for item in solution.kit if item is not None)))
    assert len(worn) == 1, "the same items every time"
    assert len(placements) == 1, placements
