"""Tests for the Python reference of the Upgrade tab: ``trioforge.upgrade``.

The reference defines what the browser must reproduce, so each rule is pinned by hand and checked against a brute force
that shares nothing with the builder (``upgrade_helpers``: every legal kit of a small pool, the exact oracle, and a
definition of "one addition" written out again).

* ``equip_now``: the best kit from the owned items at their tiers, each worn at most as often as it is owned.
* ``farm_path``: step 1 is the exact best single addition, and every later step is the exact best single addition after
  the steps before it. An addition is one more copy of a candidate; a candidate whose key the visitor owns at a lower tier is
  an **upgrade** of one copy (the highest tier below it), which becomes the candidate; a candidate owned at its tier is
  another copy; a Lore copy adds nothing. The step's item joins the owned set the same way. The assumed haste of the weapon
  index is fixed for the whole session, so a step's gain is never a revaluation of the kit it started from.
* ``best_sets(k)``: the best kit when up to ``k`` additions may be made at once: sets, not a path. The k steps of the path are k
  additions, so a set of k is never worse than the first k steps; an upgraded copy can be copied inside a set too.
* ``every_slot``: for each of the 22 places, the exact gain of swapping one candidate in with the rest of the kit held fixed.

Every name here is invented.
"""

import dataclasses
import itertools
import random
from fractions import Fraction
from types import SimpleNamespace

import pytest

import solver_helpers as H
import upgrade_helpers as U
from solver_helpers import make_item
from trioforge import upgrade as UP
from trioforge.model import formulas as fm
from trioforge.model.items import SLOT_INSTANCES, WeaponVec
from trioforge.model.tiers import cost_to_reach
from trioforge.solver.model import BuildOptions, build_milp

TRIO = ("PAL", "MNK", "BER")
PROFILE = H.make_profile(TRIO, "OGR", {"HP": 1})  # every point of item HP is worth exactly one
F = Fraction


def opts(**changes):
    return BuildOptions(**{"any_rule": "explicit", "haste_assumed": 0, **changes})


def item(key, hp, *, tier=0, slots=("FINGER",), lore=False, **more):
    return make_item(key, set(slots), stats={"HP": hp}, tier=tier, lore=lore, **more)


def counts_of(kit):
    counts = {}
    for entry in kit:
        if entry is not None:
            name = U.ident(entry)
            counts[name] = counts.get(name, 0) + 1
    return counts


def naked(profile=PROFILE, setup="stick", options=None):
    return UP.equip_now(profile, {}, setup, None, options or opts()).breakdown.F


# ---- equip now --------------------------------------------------------------------------------------------------------


def test_equip_now_wears_each_owned_item_no_more_often_than_it_is_owned():
    big, small = item("big", 10), item("small", 3)
    kit = UP.equip_now(PROFILE, {big: 1, small: 5}, "stick", None, opts())
    assert kit.status == "optimal" and counts_of(kit.kit) == {"big@0": 1, "small@0": 1}
    assert counts_of(UP.equip_now(PROFILE, {big: 2, small: 5}, "stick", None, opts()).kit) == {"big@0": 2}
    assert counts_of(UP.equip_now(PROFILE, {big: 3}, "stick", None, opts()).kit) == {"big@0": 2}  # two places


def test_equip_now_with_nothing_owned_is_the_naked_character():
    kit = UP.equip_now(PROFILE, {}, "stick", None, opts())
    assert kit.kit == (None,) * 22 and kit.F == float(fm.evaluate(PROFILE, [None] * 22).F)


def test_equip_now_leaves_out_the_owned_items_the_profile_cannot_use_and_wears_them_when_it_can():
    locked = make_item("locked-ear", {"EAR"}, stats={"HP": 90}, deity=("Tunare",))
    plain = item("plain", 4, slots=("EAR",))
    assert counts_of(UP.equip_now(PROFILE, {locked: 1, plain: 1}, "stick", None, opts()).kit) == {"plain@0": 1}
    follower = SimpleNamespace(**{f.name: getattr(PROFILE, f.name) for f in dataclasses.fields(fm.EvalProfile)}, deity="Tunare")
    assert counts_of(UP.equip_now(follower, {locked: 1, plain: 1}, "stick", None, opts()).kit) == {"locked-ear@0": 1, "plain@0": 1}


def test_a_count_of_zero_is_not_owned_and_a_bad_count_is_refused():
    big, small = item("big", 10), item("small", 3)
    assert counts_of(UP.equip_now(PROFILE, {big: 0, small: 2}, "stick", None, opts()).kit) == {"small@0": 2}
    for bad in (-1, 1.5, True, "2", None):
        with pytest.raises((ValueError, TypeError)):
            UP.equip_now(PROFILE, {big: bad}, "stick", None, opts())


def test_the_owned_item_options_are_set_by_the_functions_not_by_the_caller():
    big = item("big", 10)
    for bad in (opts(owned_caps={"big@0": 1}), opts(new_keys=frozenset({"big@0"})), opts(max_new=1)):
        with pytest.raises(ValueError):
            UP.equip_now(PROFILE, {big: 1}, "stick", None, bad)
        with pytest.raises(ValueError):
            UP.farm_path(PROFILE, {big: 1}, [item("x", 5)], "stick", None, 1, bad)


def test_equip_now_agrees_with_the_brute_force_on_random_owned_pools():
    bound = 0
    for seed in range(40):
        inst, owned, _ = U.farm_case(seed)
        counts = {U.ident(i): n for i, n in owned.items()}
        kit = UP.equip_now(inst.profile, owned, inst.setup, inst.buffset, U.options_of(inst))
        assert kit.status == "optimal"
        want = U.best_under_counts(dataclasses.replace(inst, items=list(owned)), counts)
        assert kit.breakdown.F == want, f"seed {seed}"
        wears = counts_of(kit.kit)
        assert all(wears[name] <= counts[name] for name in wears), seed
        bound += any(n > 1 for n in counts.values())
    assert bound >= 10


# ---- what a candidate is --------------------------------------------------------------------------------------------------


def test_a_candidate_is_new_another_copy_an_upgrade_or_nothing_by_what_the_visitor_owns():
    own2, own0 = item("band", 5, tier=2), item("charm", 5, tier=0)
    lore = item("crest", 5, tier=3, lore=True)
    owned = {own2: 1, own0: 2, lore: 1}
    assert UP.classify(item("fresh", 9), owned) == ("new", None)
    assert UP.classify(item("band", 5, tier=2), owned) == ("copy", None)  # owned at its tier
    assert UP.classify(item("band", 9, tier=4), owned) == ("upgrade", 2)  # the same key, higher
    assert UP.classify(item("band", 3, tier=1), owned) == ("new", None)  # lower than every owned copy: another copy at its tier
    assert UP.classify(item("crest", 5, tier=3, lore=True), owned) == ("copy", None)  # a Lore copy: callers leave it out
    two = {item("band", 5, tier=1): 1, item("band", 6, tier=3): 1}
    assert UP.classify(item("band", 9, tier=4), two) == ("upgrade", 3)  # from the highest tier below
    assert UP.classify(item("band", 9, tier=2), two) == ("upgrade", 1)


# ---- the farm path -----------------------------------------------------------------------------------------------------------


def test_the_first_step_is_the_best_single_addition_and_each_later_step_the_best_after_the_steps_before():
    ring5, ring20, ear16 = item("ring5", 5), item("ring20", 20), item("ear16", 16, slots=("EAR",))
    steps = UP.farm_path(PROFILE, {ring5: 1}, [ring20, ear16], "stick", None, 8, opts())
    assert [(s.item.key, s.kind) for s in steps] == [("ring20", "new"), ("ear16", "new"), ("ear16", "copy"), ("ring20", "copy")]
    assert [s.gain for s in steps] == [20, 16, 16, 15]  # the second ring20 only replaces ring5: 15
    base = UP.equip_now(PROFILE, {ring5: 1}, "stick", None, opts()).breakdown.F
    assert [s.F for s in steps] == [base + 20, base + 36, base + 52, base + 67]
    assert [s.index for s in steps] == [1, 2, 3, 4]


def test_gains_are_exact_fractions_that_add_up_to_the_difference_of_the_values():
    ring5, ring20, ear16 = item("ring5", 5), item("ring20", 20), item("ear16", 16, slots=("EAR",))
    steps = UP.farm_path(PROFILE, {ring5: 1}, [ring20, ear16], "stick", None, 8, opts())
    base = UP.equip_now(PROFILE, {ring5: 1}, "stick", None, opts()).breakdown.F
    assert all(isinstance(s.gain, Fraction) and isinstance(s.F, Fraction) for s in steps)
    assert sum(s.gain for s in steps) == steps[-1].F - base
    assert all(s.F == fm.evaluate(PROFILE, list(s.solution.kit), None, setup="stick", haste_assumed=0).F for s in steps)


def test_a_step_joins_the_owned_set_as_one_more_copy_so_a_second_wear_needs_a_second_step():
    ring = item("ring", 10)
    steps = UP.farm_path(PROFILE, {}, [ring], "stick", None, 8, opts())
    assert [(s.kind, s.gain) for s in steps] == [("new", 10), ("copy", 10)]  # two finger places, then nothing more helps
    assert [dict(s.owned) for s in steps] == [{"ring@0": 1}, {"ring@0": 2}]
    assert [counts_of(s.solution.kit) for s in steps] == [{"ring@0": 1}, {"ring@0": 2}]


def test_the_kit_after_every_step_wears_nothing_more_often_than_the_owned_set_after_it():
    for seed in range(25):
        inst, owned, candidates = U.farm_case(seed)
        for step in UP.farm_path(inst.profile, owned, candidates, inst.setup, inst.buffset, 3, U.options_of(inst)):
            wears, held = counts_of(step.solution.kit), dict(step.owned)
            assert all(wears[name] <= held.get(name, 0) for name in wears), (seed, step.index)


def test_an_upgrade_converts_exactly_one_copy_and_is_charged_from_the_tier_of_the_owned_copy():
    old, new = item("band", 4, tier=2), item("band", 9, tier=4)
    steps = UP.farm_path(PROFILE, {old: 2}, [new], "stick", None, 2, opts())
    # the first step converts one of the two +2 copies; the +4 item is then owned, so the next one is another copy of it
    assert [(s.kind, s.source_tier) for s in steps] == [("upgrade", 2), ("copy", None)]
    assert [dict(s.owned) for s in steps] == [{"band@2": 1, "band@4": 1}, {"band@2": 1, "band@4": 2}]
    assert [s.gain for s in steps] == [5, 5]  # 9 - 4 each
    record = {"key": "band", "tier_rule": "drop"}
    assert cost_to_reach(record, steps[0].source_tier, steps[0].item.tier) == {"exp": 12, "copies_at_arrival": 1, "potentials": 2}
    assert cost_to_reach(record, 0, 4)["exp"] == 15  # not from +0: the owned tier is the base
    one = UP.farm_path(PROFILE, {old: 1}, [new], "stick", None, 3, opts())
    assert [(s.kind, s.source_tier) for s in one] == [("upgrade", 2), ("copy", None)]  # the +2 copy became the +4 one


def test_an_owned_tier_upgrade_wins_when_it_beats_every_new_item_and_loses_when_a_new_item_is_better():
    old, upgraded = item("band", 4), item("band", 40, tier=4)
    for rival, winner in ((item("other", 30), "band"), (item("other", 50), "other")):
        first = UP.farm_path(PROFILE, {old: 1}, [upgraded, rival], "stick", None, 1, opts())[0]
        assert first.item.key == winner
    first = UP.farm_path(PROFILE, {old: 1}, [upgraded, item("other", 30)], "stick", None, 1, opts())[0]
    assert (first.kind, first.source_tier, first.gain) == ("upgrade", 0, 36)  # 40 replaces 4: the new ring would add 30


def test_a_candidate_below_an_owned_tier_is_another_copy_not_a_downgrade_and_a_useless_one_ends_the_path():
    high, low = item("chest", 40, tier=4, slots=("CHEST",)), item("chest", 10, tier=0, slots=("CHEST",))
    assert UP.farm_path(PROFILE, {high: 1}, [low], "stick", None, 8, opts()) == []  # one place: the lower copy adds nothing
    band_high, band_low = item("band", 40, tier=4), item("band", 10, tier=0)
    steps = UP.farm_path(PROFILE, {band_high: 1}, [band_low], "stick", None, 8, opts())
    assert [(s.kind, s.gain, s.item.tier) for s in steps] == [("new", 10, 0)]  # the second finger place takes it
    lore_high, lore_low = item("crest", 40, tier=4, lore=True), item("crest", 10, tier=0, lore=True)
    assert UP.farm_path(PROFILE, {lore_high: 1}, [lore_low], "stick", None, 8, opts()) == []  # a Lore key is worn once
    assert UP.farm_path(PROFILE, {lore_high: 1}, [lore_high], "stick", None, 8, opts()) == []  # and a Lore copy adds nothing


def test_the_path_stops_when_no_addition_improves_and_never_has_a_zero_gain_step():
    assert len(UP.farm_path(PROFILE, {}, [item("ring", 5), item("ear", 3, slots=("EAR",))], "stick", None, 99, opts())) == 4
    for seed in range(25):
        inst, owned, candidates = U.farm_case(seed)
        steps = UP.farm_path(inst.profile, owned, candidates, inst.setup, inst.buffset, 6, U.options_of(inst))
        assert all(s.gain > 0 for s in steps), seed
        assert [s.index for s in steps] == list(range(1, len(steps) + 1))


def test_degenerate_inputs_give_an_empty_path_or_the_path_from_the_naked_character():
    ring = item("ring", 10)
    assert UP.farm_path(PROFILE, {ring: 1}, [ring], "stick", None, 0, opts()) == []  # no steps asked for
    assert UP.farm_path(PROFILE, {ring: 1}, [], "stick", None, 8, opts()) == []  # nothing to add
    assert UP.farm_path(PROFILE, {}, [], "stick", None, 8, opts()) == []
    steps = UP.farm_path(PROFILE, {}, [ring], "stick", None, 8, opts())
    assert steps[0].gain == 10 and steps[0].F == naked() + 10
    assert UP.farm_path(PROFILE, {ring: 0}, [ring], "stick", None, 1, opts())[0].kind == "new"  # a count of 0 is not owned
    with pytest.raises(ValueError):
        UP.farm_path(PROFILE, {}, [ring, ring], "stick", None, 8, opts())  # the same item offered twice
    with pytest.raises(ValueError):
        UP.farm_path(PROFILE, {}, [ring], "stick", None, -1, opts())


def test_candidates_the_profile_cannot_use_are_never_a_step():
    locked = make_item("locked-ear", {"EAR"}, stats={"HP": 90}, deity=("Tunare",))
    assert UP.farm_path(PROFILE, {}, [locked, item("plain", 4, slots=("EAR",))], "stick", None, 1, opts())[0].item.key == "plain"


def test_a_tie_between_candidates_goes_to_the_smaller_ident_whatever_the_order_and_every_time():
    a, b = item("ring-a", 10), item("ring-b", 10)
    for pool in itertools.permutations([a, b]):
        for _ in range(3):
            assert UP.farm_path(PROFILE, {}, list(pool), "stick", None, 1, opts())[0].item.key == "ring-a"
    # an upgrade and a new item worth the same 10: of the equal kits the one of the smaller total rank (the sorted idents)
    # stands, here the upgraded ring alone (ranks 2) against the old ring and the new one (ranks 1 + 3)
    old_ring, upgraded, rival = item("ring-a", 4, tier=0), item("ring-a", 14, tier=2), item("ring-b", 10)
    for pool in ([rival, upgraded], [upgraded, rival]):
        first = UP.farm_path(PROFILE, {old_ring: 1}, pool, "stick", None, 1, opts())[0]
        assert (first.kind, first.item.tier, first.gain) == ("upgrade", 2, 10)


# ---- the assumed haste is fixed for the session ------------------------------------------------------------------------------


def haste_scenario():
    sword = make_item(
        "sword", {"PRIMARY", "SECONDARY"}, stats={"HP": 1}, weapon=WeaponVec("1H Slashing", 20, 30, None, False)
    )
    cloak = make_item("cloak", {"BACK"}, stats={"HP": 1}, haste=10)
    swift = make_item("swift-helm", {"HEAD"}, stats={"HP": 1}, haste=30)
    profile = H.make_profile(TRIO, "OGR", {"HP": 1, "HASTE": 2, "DMG": 500})
    return profile, {sword: 1, cloak: 1}, [swift]


def test_the_session_haste_comes_from_the_owned_items_and_the_candidates_together():
    profile, owned, candidates = haste_scenario()
    assert UP.session_haste(profile, owned, [], "dw", None, opts(haste_assumed=None)) == 10
    assert UP.session_haste(profile, owned, candidates, "dw", None, opts(haste_assumed=None)) == 30
    assert UP.session_haste(profile, owned, candidates, "dw", None, opts(haste_assumed=12)) == 12  # the caller's value stands


def test_no_step_gain_is_a_revaluation_of_the_kit_it_started_from():
    profile, owned, candidates = haste_scenario()
    session = UP.session_haste(profile, owned, candidates, "dw", None, opts(haste_assumed=None))
    assert session == 30 and session != UP.session_haste(profile, owned, [], "dw", None, opts(haste_assumed=None))
    before = UP.equip_now(profile, owned, "dw", None, opts(haste_assumed=session))
    steps = UP.farm_path(profile, owned, candidates, "dw", None, 3, opts(haste_assumed=None))
    assert len(steps) == 1 and steps[0].item.key == "swift-helm" and steps[0].haste_assumed == session
    again = fm.evaluate(profile, list(steps[0].solution.kit), None, setup="dw", haste_assumed=session).F
    held = fm.evaluate(profile, list(before.kit), None, setup="dw", haste_assumed=session).F
    assert steps[0].F == again and steps[0].gain == again - held == steps[0].F - before.breakdown.F
    weapon_term = lambda haste: fm.evaluate(profile, list(before.kit), None, setup="dw", haste_assumed=haste).F  # noqa: E731
    assert weapon_term(10) != weapon_term(30)  # a gain measured against a kit valued at another haste would differ


def test_the_haste_is_the_same_in_equip_now_and_in_every_step_of_a_random_session():
    for seed in range(20):
        inst, owned, candidates = U.farm_case(seed)
        free = BuildOptions(any_rule=inst.any_rule)
        session = UP.session_haste(inst.profile, owned, candidates, inst.setup, inst.buffset, free)
        steps = UP.farm_path(inst.profile, owned, candidates, inst.setup, inst.buffset, 3, free)
        assert {s.haste_assumed for s in steps} <= {session}, seed
        for step in steps:
            totals = H.eval_totals(inst.buffset, step.solution.buffs) if inst.buffset else None
            assert step.F == fm.evaluate(inst.profile, list(step.solution.kit), totals, setup=inst.setup, haste_assumed=session).F


def test_the_session_haste_is_the_one_the_builder_assumes_for_the_whole_pool_on_random_pools():
    for seed in range(40):
        inst, owned, candidates = U.farm_case(seed)
        pool = {U.ident(i): i for i in [*owned, *candidates]}.values()
        free = BuildOptions(any_rule=inst.any_rule)
        want = build_milp(inst.profile, list(pool), inst.setup, inst.buffset, free).haste_assumed
        assert UP.session_haste(inst.profile, owned, candidates, inst.setup, inst.buffset, free) == want, seed


# ---- exactness against the brute force --------------------------------------------------------------------------------------


def apply(counts, kind, source, candidate):
    """The owned counts after adding the candidate, written out again."""
    name = U.ident(candidate)
    counts = dict(counts)
    if kind == "upgrade":
        key = f"{candidate.key}@{source}"
        counts[key] -= 1
        if counts[key] == 0:
            del counts[key]
    counts[name] = counts.get(name, 0) + 1
    return counts


@pytest.mark.parametrize("chains", [False, True])
def test_each_farm_step_is_the_best_single_addition_by_brute_force_and_a_path_ends_when_none_improves(chains):
    taken, upgrades, copies, two_tiers = 0, 0, 0, 0
    for seed in range(24):
        inst, owned, candidates = U.farm_case(seed, chains=chains)
        counts = {U.ident(i): n for i, n in owned.items()}
        two_tiers += len({i.key for i in owned}) < len(owned)  # a key owned at two tiers
        options = U.options_of(inst)
        steps = UP.farm_path(inst.profile, owned, candidates, inst.setup, inst.buffset, 3, options)
        before = U.best_under_counts(inst, counts)
        for number in range(1, 4):
            moves = U.single_additions(counts, candidates)
            best = max([U.best_under_counts(inst, after) for *_, after in moves], default=before)
            if number > len(steps):
                assert best <= before, (seed, number)  # the path ended because nothing improves
                break
            step = steps[number - 1]
            assert step.F == best and best > before, (seed, number)
            assert any((c.key, c.tier, kind) == (step.item.key, step.item.tier, step.kind) for c, kind, *_ in moves), (seed, number)
            counts = apply(counts, step.kind, step.source_tier, step.item)
            assert dict(step.owned) == counts, (seed, number)
            before = best
            taken += 1
            upgrades += step.kind == "upgrade"
            copies += step.kind == "copy"
    assert taken >= 20 and upgrades >= 2 and copies >= 4
    assert not chains or two_tiers >= 3  # chains own some keys at two tiers: the upgrade then starts from the higher


def test_pruning_the_pool_of_each_step_changes_no_value_of_the_path():
    seen = 0
    for seed in range(12):
        inst, owned, candidates = U.farm_case(seed, pool="prunable")
        options = U.options_of(inst)
        pruned = UP.farm_path(inst.profile, owned, candidates, inst.setup, inst.buffset, 3, options)
        whole = UP.farm_path(inst.profile, owned, candidates, inst.setup, inst.buffset, 3, options, prune_pool=False)
        assert [s.F for s in pruned] == [s.F for s in whole], seed
        seen += len(pruned)
    assert seen >= 12


# ---- best sets ----------------------------------------------------------------------------------------------------------------


def brute_best_set(inst, counts, candidates, k):
    """The exact best value over the owned counts that up to ``k`` single additions can reach, in any order: each addition is
    classified against the counts the ones before it left (``U.single_additions``), as a step of the path is. So an
    upgraded copy can be copied inside a set, and the first ``k`` steps of the path are one of the sets."""
    reached = {frozenset(counts.items())}
    frontier = set(reached)
    for _ in range(k):
        after = {frozenset(counts_after.items()) for state in frontier for *_, counts_after in U.single_additions(dict(state), candidates)}
        frontier = after - reached
        reached |= after
    return max(U.best_under_counts(inst, dict(state)) for state in reached)


@pytest.mark.parametrize("k", [2, 3])
def test_the_best_set_of_k_additions_matches_the_brute_force_over_every_set(k):
    checked = 0
    for seed in range(40):
        inst, owned, candidates = U.farm_case(seed)
        if not candidates or len(candidates) > 4:
            continue
        counts = {U.ident(i): n for i, n in owned.items()}
        got = UP.best_sets(inst.profile, owned, candidates, k, inst.setup, inst.buffset, U.options_of(inst))
        assert got.k == k and got.F == brute_best_set(inst, counts, candidates, k), (seed, k)
        assert len(got.acquisitions) <= k
        assert got.gain == got.F - UP.equip_now(inst.profile, owned, inst.setup, inst.buffset, U.options_of(inst)).breakdown.F
        checked += 1
        if checked == 4:
            break
    assert checked >= 3


def test_the_best_set_matches_the_brute_force_when_an_upgrade_may_be_copied():
    checked, copied = 0, 0
    for seed in range(60):
        inst, owned, candidates = U.farm_case(seed, repeats=True)
        if not candidates or len(candidates) > 3:
            continue
        counts = {U.ident(i): n for i, n in owned.items()}
        options = U.options_of(inst)
        for k in (2, 3):
            got = UP.best_sets(inst.profile, owned, candidates, k, inst.setup, inst.buffset, options)
            assert got.F == brute_best_set(inst, counts, candidates, k), (seed, k)
            assert len(got.acquisitions) <= k
            copied += any(a.kind == "copy" and a.item in [b.item for b in got.acquisitions if b.kind == "upgrade"] for a in got.acquisitions)
        checked += 1
        if checked == 10:
            break
    assert checked >= 8 and copied >= 2  # sets that upgrade a copy and then copy the upgrade are among the cases


def test_a_best_set_of_k_is_worth_at_least_the_first_k_steps_of_the_path_on_random_sessions():
    compared, copies = 0, 0
    for flavour, seeds in (({}, 20), ({"repeats": True}, 30), ({"pool": "prunable", "repeats": True}, 20)):
        for seed in range(seeds):
            inst, owned, candidates = U.farm_case(seed, **flavour)
            options = U.options_of(inst)
            path = UP.farm_path(inst.profile, owned, candidates, inst.setup, inst.buffset, 3, options)
            for k in range(1, len(path) + 1):
                got = UP.best_sets(inst.profile, owned, candidates, k, inst.setup, inst.buffset, options)
                assert got.F >= path[k - 1].F, (flavour, seed, k)
                compared += 1
            copies += any(
                step.kind == "copy" and any(earlier.kind == "upgrade" and earlier.item == step.item for earlier in path[:at])
                for at, step in enumerate(path)
            )
    assert compared >= 100 and copies >= 5  # the paths that copy an upgrade are among the sessions


def test_a_set_can_beat_the_greedy_path_because_the_path_takes_the_best_single_addition_first():
    # the END conversion is steeper above an average of 100 (2.5 a point against 1): from an average of 96, one item of
    # +16 STR reaches the knee and the second is worth 2.5 times as much as the first
    naked_stats = {"STR": 96, "STA": 96, "AGI": 96, "DEX": 96, "WIS": 100, "INT": 100, "CHA": 100}
    profile = H.make_profile(TRIO, "OGR", {"END": 1, "HP": 1}, naked=naked_stats)
    big = make_item("big", {"HEAD"}, stats={"HP": 60})
    one, two = make_item("one", {"NECK"}, stats={"STR": 16}), make_item("two", {"BACK"}, stats={"STR": 16})
    candidates = [big, one, two]
    path = UP.farm_path(profile, {}, candidates, "stick", None, 2, opts())
    pair = UP.best_sets(profile, {}, candidates, 2, "stick", None, opts())
    assert path[0].item.key == "big" and path[0].gain == 60  # the best single addition
    assert {a.item.key for a in pair.acquisitions} == {"one", "two"}
    assert pair.gain > path[-1].F - naked(profile)  # the set is worth more than the path of two steps
    assert path[-1].F - naked(profile) == 60 + 35  # big, then one item: 4 points of conversion at 8.75 END each
    assert pair.gain == F(245, 2)  # 14 points of conversion at 8.75 END each


# ---- every slot ---------------------------------------------------------------------------------------------------------------

SWORD = WeaponVec("1H Slashing", 20, 30, None, False)
AXE = WeaponVec("2H Slashing", 40, 60, None, True)


def kit_of(**groups):
    return H.kit_from_groups({name.upper(): placed for name, placed in groups.items()})


def test_every_slot_has_a_row_for_each_of_the_twenty_two_places_in_kit_order():
    ring = item("ring", 5)
    rows = UP.every_slot(PROFILE, [None] * 22, [ring], "stick", None, opts())
    assert [r.place for r in rows] == list(SLOT_INSTANCES) and [r.index for r in rows] == list(range(22))
    assert all(r.current is None for r in rows)
    for row in rows:
        assert bool(row.swaps) is (row.place == "FINGER"), row.place  # the Any places need the item to list them
        if row.swaps:
            assert [(s.item.key, s.delta) for s in row.swaps] == [("ring", 5)]
    anywhere = UP.every_slot(PROFILE, [None] * 22, [ring], "stick", None, opts(any_rule="all"))
    assert [r.place for r in anywhere if r.swaps] == ["FINGER", "FINGER", "ANY", "ANY"]  # under "all" they take any item


def test_a_swap_is_valued_with_the_rest_of_the_kit_held_fixed_and_past_the_softcap_it_is_not_the_linear_estimate():
    profile = H.make_profile(TRIO, "OGR", {"AC": 6}, softcap=(60, 0.25))
    chest, helm = make_item("chest", {"CHEST"}, stats={"AC": 30}), make_item("helm", {"HEAD"}, stats={"AC": 20})
    better = make_item("chest-plus", {"CHEST"}, stats={"AC": 40})
    kit = kit_of(chest=[chest], head=[helm])
    held = fm.evaluate(profile, kit, None, setup="stick", haste_assumed=0)
    assert held.totals["sheet"]["X"] > held.totals["sheet"]["Y"]  # the kit is past the softcap already
    rows = UP.every_slot(profile, kit, [better], "stick", None, opts())
    row = next(r for r in rows if r.place == "CHEST")
    swapped = fm.evaluate(profile, kit_of(chest=[better], head=[helm]), None, setup="stick", haste_assumed=0).F
    assert row.current == chest and [(s.item.key, s.delta) for s in row.swaps] == [("chest-plus", swapped - held.F)]
    assert 0 < row.swaps[0].delta < 6 * 10  # ten armor class at a weight of 6 is 60 below the cap; past it, much less


def test_a_swap_never_changes_another_place_so_a_two_hander_over_a_worn_off_hand_is_not_offered():
    sword = make_item("sword", {"PRIMARY"}, weapon=SWORD)
    shield = make_item("guard", {"SECONDARY"}, stats={"AC": 5}, shield=True)
    axe = make_item("axe", {"PRIMARY"}, stats={"HP": 90}, weapon=AXE)
    kit = kit_of(primary=[sword], secondary=[shield])
    rows = {r.place: r for r in UP.every_slot(PROFILE, kit, [axe], "1h-shield", None, opts())}
    assert rows["PRIMARY"].swaps == ()  # the axe would need the off hand empty: that is not one swap
    only_axe = kit_of(primary=[axe])
    rows = {r.place: r for r in UP.every_slot(PROFILE, only_axe, [sword, shield], "2h", None, opts())}
    assert rows["SECONDARY"].swaps == () and rows["PRIMARY"].swaps == ()  # the 2h setup allows no one-hander and no shield
    axe2 = make_item("axe2", {"PRIMARY"}, stats={"HP": 95}, weapon=AXE)
    rows = {r.place: r for r in UP.every_slot(PROFILE, only_axe, [axe2], "2h", None, opts())}
    assert [s.item.key for s in rows["PRIMARY"].swaps] == ["axe2"] and rows["SECONDARY"].swaps == ()


def test_the_hands_follow_the_setup_and_a_two_hander_never_stands_in_the_off_hand():
    guard, held = make_item("guard", {"SECONDARY"}, stats={"HP": 4}, shield=True), make_item("orb", {"SECONDARY"}, stats={"HP": 9})
    axe = make_item("axe", {"PRIMARY", "SECONDARY"}, stats={"HP": 50}, weapon=AXE)
    rows = {r.place: r for r in UP.every_slot(PROFILE, [None] * 22, [guard, held, axe], "1h-shield", None, opts())}
    assert [s.item.key for s in rows["SECONDARY"].swaps] == ["guard"]  # only a shield in the shield setup
    rows = {r.place: r for r in UP.every_slot(PROFILE, [None] * 22, [guard, held, axe], "stick", None, opts())}
    assert [s.item.key for s in rows["SECONDARY"].swaps] == ["orb", "guard"]  # anything, but not the two-hander
    assert [s.item.key for s in rows["PRIMARY"].swaps] == ["axe"]
    rows = {r.place: r for r in UP.every_slot(PROFILE, kit_of(primary=[axe]), [held], "stick", None, opts())}
    assert rows["SECONDARY"].swaps == ()  # a two-hander in the main hand leaves the off hand empty


def test_a_lore_item_worn_elsewhere_is_not_offered_but_may_replace_itself_at_another_tier():
    crest, crest_plus = item("crest", 10, slots=("EAR",), lore=True), item("crest", 15, tier=3, slots=("EAR",), lore=True)
    kit = kit_of(ear=[crest])
    rows = UP.every_slot(PROFILE, kit, [crest_plus, crest], "stick", None, opts())
    ears = [r for r in rows if r.place == "EAR"]
    assert [(s.item.key, s.item.tier, s.delta) for s in ears[0].swaps] == [("crest", 3, 5)]  # the same key at +3 in its own place
    assert ears[1].swaps == ()  # the second ear place would hold a second Lore copy
    assert all(r.swaps == () for r in rows if r.place == "ANY")


def test_candidates_the_profile_cannot_use_are_not_offered_unless_the_deity_allows_them():
    locked, plain = make_item("locked-ear", {"EAR"}, stats={"HP": 90}, deity=("Tunare",)), item("plain", 4, slots=("EAR",))
    follower = SimpleNamespace(**{f.name: getattr(PROFILE, f.name) for f in dataclasses.fields(fm.EvalProfile)}, deity="Tunare")
    for profile, expected in ((PROFILE, ["plain"]), (follower, ["locked-ear", "plain"])):
        ear = next(r for r in UP.every_slot(profile, [None] * 22, [locked, plain], "stick", None, opts()) if r.place == "EAR")
        assert [s.item.key for s in ear.swaps] == expected
    caster = make_item("caster-ear", {"EAR"}, stats={"HP": 90}, classes=("CLR", "WIZ"))
    ear = next(r for r in UP.every_slot(PROFILE, [None] * 22, [caster, plain], "stick", None, opts()) if r.place == "EAR")
    assert [s.item.key for s in ear.swaps] == ["plain"]


def test_swaps_are_sorted_by_gain_then_key_the_current_item_is_skipped_and_limit_cuts_the_list():
    current = item("ring-current", 10)
    kit = kit_of(finger=[current])
    pool = [item("ring-d", 7), item("ring-b", 12), item("ring-a", 12), item("ring-c", 12), item("ring-low", 1), current]
    first = next(r for r in UP.every_slot(PROFILE, kit, pool, "stick", None, opts()) if r.place == "FINGER")
    assert [(s.item.key, s.delta) for s in first.swaps] == [("ring-a", 2), ("ring-b", 2), ("ring-c", 2)]  # three, best first
    full = next(r for r in UP.every_slot(PROFILE, kit, pool, "stick", None, opts(), limit=6) if r.place == "FINGER")
    assert [s.item.key for s in full.swaps] == ["ring-a", "ring-b", "ring-c", "ring-d", "ring-low"]  # not the current item
    assert [s.delta for s in full.swaps][-2:] == [-3, -9]  # a worse item is a swap with a negative gain
    rows = [r for r in UP.every_slot(PROFILE, kit, pool, "stick", None, opts()) if r.place == "FINGER"]
    assert rows[1].current is None and [s.item.key for s in rows[1].swaps] == ["ring-a", "ring-b", "ring-c"]
    assert rows[1].swaps[0].delta == 12


def test_every_slot_takes_the_kit_of_equip_now_with_its_buffs_and_matches_the_oracle_on_random_cases():
    swaps, rows_seen = 0, 0
    for seed in range(25):
        inst, owned, candidates = U.farm_case(seed)
        options = U.options_of(inst)
        solution = UP.equip_now(inst.profile, owned, inst.setup, inst.buffset, options)
        pool = list({U.ident(i): i for i in [*candidates, *owned]}.values())
        rows = UP.every_slot(inst.profile, solution, pool, inst.setup, inst.buffset, options, limit=50)
        totals = H.eval_totals(inst.buffset, solution.buffs) if inst.buffset else None
        base = fm.evaluate(inst.profile, list(solution.kit), totals, setup=inst.setup, haste_assumed=inst.haste_assumed).F
        assert [r.place for r in rows] == list(SLOT_INSTANCES) and base == solution.breakdown.F
        for row in rows:
            rows_seen += 1
            assert row.current == solution.kit[row.index]
            deltas = [s.delta for s in row.swaps]
            assert deltas == sorted(deltas, reverse=True)
            for swap in row.swaps:
                trial = list(solution.kit)
                trial[row.index] = swap.item
                other = [x for j, x in enumerate(trial) if j != row.index and x is not None]
                assert H.fits(swap.item, row.place, inst.setup, inst.any_rule), (seed, row.place, swap.item.key)
                assert not (swap.item.lore and swap.item.key in {x.key for x in other if x.lore}), seed
                assert swap.delta == fm.evaluate(inst.profile, trial, totals, setup=inst.setup, haste_assumed=inst.haste_assumed).F - base
                swaps += 1
    assert swaps >= 100 and rows_seen == 25 * 22


# ---- every slot counts copies --------------------------------------------------------------------------------------------------
#
# The items on offer for a swap are the candidates of the tier mode and the items the visitor owns. A candidate may be got again,
# so a swap to one has no count; an owned item that is not a candidate is a swap for a place only while the visitor owns more of
# it than the kit wears in its other places (one ring, owned once and worn on Finger 1, is not a swap for Finger 2).


def fingers(rows):
    return [row for row in rows if row.place == "FINGER"]


def test_a_ring_owned_once_and_worn_on_the_first_finger_is_not_a_swap_for_the_second_but_a_second_copy_makes_it_one():
    ring = item("ring", 5)
    kit = kit_of(finger=[ring])
    first, second = fingers(UP.every_slot(PROFILE, kit, [], "stick", None, opts(), owned={ring: 1}))
    assert first.current == ring and first.swaps == ()  # (the item worn in a place is never offered for it)
    assert second.current is None and second.swaps == ()  # the one ring is on Finger 1
    first, second = fingers(UP.every_slot(PROFILE, kit, [], "stick", None, opts(), owned={ring: 2}))
    assert first.swaps == ()
    assert [(s.item.key, s.delta) for s in second.swaps] == [("ring", 5)]  # a spare copy is a swap, worth the ring


def test_a_candidate_has_no_count_and_an_item_that_is_owned_and_a_candidate_counts_as_a_candidate():
    ring = item("ring", 5)
    kit = kit_of(finger=[ring])
    for owned in (None, {}, {ring: 1}, {ring: 3}):  # not owned at all, owned once (worn), owned with spares
        second = fingers(UP.every_slot(PROFILE, kit, [ring], "stick", None, opts(), owned=owned))[1]
        assert [(s.item.key, s.delta) for s in second.swaps] == [("ring", 5)], owned  # another copy: the swap means getting it


def test_the_copies_the_kit_wears_in_all_its_other_places_count_so_a_swap_needs_more_owned_than_that():
    ring = item("ring", 5)
    kit = kit_of(finger=[ring], any=[ring])  # on Finger 1 and on the first Any place, which a ring fits under the "all" rule
    options = opts(any_rule="all")
    rows = UP.every_slot(PROFILE, kit, [], "stick", None, options, owned={ring: 2})
    assert [row.place for row in rows if row.swaps] == []  # both rings are worn: a third place has none to take
    rows = UP.every_slot(PROFILE, kit, [], "stick", None, options, owned={ring: 3})
    assert [(row.index, row.place) for row in rows if row.swaps] == [(12, "FINGER"), (19, "ANY")]  # one spare: the free places


def test_lore_stays_as_it_is_a_lore_item_worn_in_another_place_is_not_offered_however_many_are_owned():
    sigil = item("sigil", 9, lore=True)
    kit = kit_of(finger=[sigil])
    for owned, candidates in (({sigil: 1}, []), ({sigil: 3}, []), ({sigil: 1}, [sigil]), ({}, [sigil])):
        rows = UP.every_slot(PROFILE, kit, candidates, "stick", None, opts(), owned=owned)
        assert fingers(rows)[1].swaps == (), (owned, candidates)
    for row in fingers(UP.every_slot(PROFILE, [None] * 22, [], "stick", None, opts(), owned={sigil: 1})):
        assert [(s.item.key, s.delta) for s in row.swaps] == [("sigil", 9)]  # worn nowhere: a swap for either finger


def test_an_owned_item_the_profile_cannot_use_is_not_offered_and_a_bad_owned_count_is_refused():
    locked = make_item("locked-ear", {"EAR"}, stats={"HP": 90}, deity=("Tunare",))
    follower = SimpleNamespace(**{f.name: getattr(PROFILE, f.name) for f in dataclasses.fields(fm.EvalProfile)}, deity="Tunare")
    for profile, expected in ((PROFILE, []), (follower, ["locked-ear"])):
        ear = next(r for r in UP.every_slot(profile, [None] * 22, [], "stick", None, opts(), owned={locked: 1}) if r.place == "EAR")
        assert [s.item.key for s in ear.swaps] == expected
    ring = item("ring", 5)
    for bad in (-1, 1.5, True, "2", None):
        with pytest.raises((ValueError, TypeError)):
            UP.every_slot(PROFILE, [None] * 22, [], "stick", None, opts(), owned={ring: bad})
    assert fingers(UP.every_slot(PROFILE, [None] * 22, [], "stick", None, opts(), owned={ring: 0}))[0].swaps == ()  # none owned


def test_without_a_fixed_haste_every_slot_assumes_the_haste_of_the_session_and_the_owned_items_count_in_it():
    profile, held, _ = haste_scenario()  # the sword and a cloak of haste 10 are owned (the helm of haste 30 is a candidate there)
    sword, cloak = held
    owned = {sword: 2, cloak: 1}
    kit = kit_of(primary=[sword])
    second_hand = SLOT_INSTANCES.index("SECONDARY")
    rows = UP.every_slot(profile, kit, [], "dw", None, opts(haste_assumed=None), owned=owned)
    (swap,) = rows[second_hand].swaps
    assert swap.item.key == "sword"
    trial = kit_of(primary=[sword], secondary=[sword])

    def gain(haste):
        worn = fm.evaluate(profile, kit, None, setup="dw", haste_assumed=haste).F
        return fm.evaluate(profile, trial, None, setup="dw", haste_assumed=haste).F - worn

    assert swap.delta == gain(10) != gain(0)  # the cloak is owned, so the weapon index is taken at its 10 percent


def test_with_the_kit_of_equip_now_the_owned_items_offered_are_those_within_the_counts_and_none_of_them_gains():
    offered, held_back = 0, 0
    for seed in range(25):
        inst, owned, candidates = U.farm_case(seed)
        options = U.options_of(inst)
        solution = UP.equip_now(inst.profile, owned, inst.setup, inst.buffset, options)
        rows = UP.every_slot(inst.profile, solution, candidates, inst.setup, inst.buffset, options, limit=50, owned=owned)
        named = {U.ident(c) for c in candidates}
        worn = counts_of(solution.kit)
        for row in rows:
            current = solution.kit[row.index]
            lore_elsewhere = {x.key for j, x in enumerate(solution.kit) if j != row.index and x is not None and x.lore}
            want = set()
            for owned_item, count in owned.items():
                name = U.ident(owned_item)
                fits = H.fits(owned_item, row.place, inst.setup, inst.any_rule)
                if name in named or not fits or (current is not None and U.ident(current) == name):
                    continue
                if owned_item.lore and owned_item.key in lore_elsewhere:
                    continue
                if count > worn.get(name, 0):
                    want.add(name)
                else:
                    held_back += 1
            got = {U.ident(s.item) for s in row.swaps} - named
            if row.place not in ("PRIMARY", "SECONDARY"):  # (the hands have rules of their own, pinned above)
                assert got == want, (seed, row.place)
            for swap in row.swaps:
                name = U.ident(swap.item)
                if name in named:
                    continue
                assert owned[swap.item] > worn.get(name, 0), (seed, row.place, name)  # the kit after the swap wears no more than is owned
                assert swap.delta <= 0, (seed, row.place, name)  # and Equip now is the best kit of what is owned: nothing owned gains
                offered += 1
    assert offered >= 30 and held_back >= 20  # the cases bind: copies were counted, and owned items were offered


# ---- order, empty sets and the candidates of a tier mode -------------------------------------------------------------------


def test_the_path_does_not_depend_on_the_order_of_the_candidates_or_of_the_owned_mapping():
    steps_seen = 0
    for seed in range(15):
        inst, owned, candidates = U.farm_case(seed)
        shuffled = list(candidates)
        random.Random(seed).shuffle(shuffled)
        flipped = dict(reversed(list(owned.items())))
        options = U.options_of(inst)
        one = UP.farm_path(inst.profile, owned, candidates, inst.setup, inst.buffset, 3, options)
        two = UP.farm_path(inst.profile, flipped, shuffled, inst.setup, inst.buffset, 3, options)
        assert [(s.item.key, s.item.tier, s.kind, s.source_tier, s.F, s.owned) for s in one] == [
            (s.item.key, s.item.tier, s.kind, s.source_tier, s.F, s.owned) for s in two
        ], seed
        steps_seen += len(one)
    assert steps_seen >= 15


def test_without_the_tie_stage_the_values_of_the_path_are_the_same():
    for seed in range(8):
        inst, owned, candidates = U.farm_case(seed)
        options = U.options_of(inst)
        canonical = UP.farm_path(inst.profile, owned, candidates, inst.setup, inst.buffset, 3, options)
        quick = UP.farm_path(inst.profile, owned, candidates, inst.setup, inst.buffset, 3, options, canonical=False)
        assert [s.F for s in quick] == [s.F for s in canonical], seed  # the tie stage picks among equal values, never a better one


def test_the_best_set_of_nothing_to_gain_is_the_equip_now_kit():
    ring = item("ring", 10)
    got = UP.best_sets(PROFILE, {ring: 2}, [ring], 3, "stick", None, opts())
    assert got.acquisitions == () and got.gain == 0 and got.F == UP.equip_now(PROFILE, {ring: 2}, "stick", None, opts()).breakdown.F
    assert UP.best_sets(PROFILE, {ring: 1}, [], 2, "stick", None, opts()).acquisitions == ()
    for bad in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            UP.best_sets(PROFILE, {}, [ring], bad, "stick", None, opts())


def test_a_set_may_upgrade_an_owned_copy_and_add_copies_of_the_upgrade_as_the_steps_of_the_path_do():
    # the path upgrades the owned ring and then copies the upgraded one: a copy at its tier needs no source. A set of two additions does
    # the same (the first wear of the target is the upgrade, the second a copy of it), and a third addition has no place to go.
    owned = {item("ring", 10, tier=0): 1}
    target = item("ring", 20, tier=3)
    path = UP.farm_path(PROFILE, owned, [target], "stick", None, 3, opts())
    assert [(step.kind, step.item.tier) for step in path] == [("upgrade", 3), ("copy", 3)]
    upgrade, copy = [("upgrade", 3, 0)], [("copy", 3, None)]
    for k, found, value in ((1, upgrade, path[0].F), (2, upgrade + copy, path[1].F), (3, upgrade + copy, path[1].F)):
        got = UP.best_sets(PROFILE, owned, [target], k, "stick", None, opts())
        assert [(a.kind, a.item.tier, a.source_tier) for a in got.acquisitions] == found, k
        assert got.F == value, k
    assert path[0].F < path[1].F
    start = UP.equip_now(PROFILE, owned, "stick", None, opts()).breakdown.F
    assert UP.best_sets(PROFILE, owned, [target], 2, "stick", None, opts()).gain == path[1].F - start


def test_a_set_lists_each_upgrade_with_the_copies_of_it_then_the_new_items_then_the_extra_copies_of_what_is_owned():
    ring0, ring3 = item("ring", 10, tier=0), item("ring", 20, tier=3)
    stud, helm = item("stud", 9, slots=("EAR",)), item("helm", 30, slots=("HEAD",))
    owned = {ring0: 1, stud: 1}
    candidates = [helm, stud, ring3]  # (in no order of the list)
    got = UP.best_sets(PROFILE, owned, candidates, 4, "stick", None, opts())
    assert [(a.item.key, a.item.tier, a.kind, a.source_tier) for a in got.acquisitions] == [
        ("ring", 3, "upgrade", 0), ("ring", 3, "copy", None), ("helm", 0, "new", None), ("stud", 0, "copy", None),
    ]
    assert got.gain == 10 + 20 + 30 + 9  # (the first ring wear is worth 10 more than the owned one, the second 20)
    three = UP.best_sets(PROFILE, owned, candidates, 3, "stick", None, opts())
    assert [(a.item.key, a.kind) for a in three.acquisitions] == [("ring", "upgrade"), ("ring", "copy"), ("helm", "new")]
    assert three.gain == 60


def test_best_sets_of_one_is_the_first_step_of_the_path():
    for seed in range(15):
        inst, owned, candidates = U.farm_case(seed)
        options = U.options_of(inst)
        steps = UP.farm_path(inst.profile, owned, candidates, inst.setup, inst.buffset, 1, options)
        one = UP.best_sets(inst.profile, owned, candidates, 1, inst.setup, inst.buffset, options)
        if steps:
            assert one.F == steps[0].F and one.gain == steps[0].gain and len(one.acquisitions) == 1, seed
            assert (one.acquisitions[0].item.key, one.acquisitions[0].kind) == (steps[0].item.key, steps[0].kind), seed
        else:
            assert one.acquisitions == () and one.gain == 0, seed


def raw(key, tier_rule, **more):
    """A catalog record with just what the tier views read, for the candidates of a tier mode."""
    record = {
        "key": key, "name": key, "slots": ["FINGER"], "classes": ["ALL"], "races": ["ALL"], "deity": None, "flags": [],
        "stats": {"HP": 10}, "sv": {}, "weight": 0.1, "item_type": None, "weapon": None, "tier_rule": tier_rule,
    }
    return {**record, **more}


def test_the_candidates_of_a_tier_mode_are_the_records_at_the_tier_the_mode_gives_each():
    rules = H.TABLES.rules
    records = [raw("w1", "drop"), raw("w2", "fixed0"), raw("w3", "spell")]
    assert [(c.key, c.tier) for c in UP.scored_candidates(records, "ready4", rules)] == [("w1", 4), ("w2", 4), ("w3", 4)]
    assert [(c.key, c.tier) for c in UP.scored_candidates(records, "arrives", rules, D=3)] == [("w1", 3), ("w2", 0), ("w3", 0)]
    assert [(c.key, c.tier) for c in UP.scored_candidates(records, "fixed", rules, N=6)] == [("w1", 6), ("w2", 6), ("w3", 6)]
    assert UP.scored_candidates(records, "ready4", rules)[0].stats == {"HP": 14}  # 10 + max(4, 10 * 4 // 10) at +4
    assert UP.scored_candidates(records, "arrives", rules, D=0)[0].stats == {"HP": 10}  # a D0 drop is a +0 item


# ---- the real catalog -------------------------------------------------------------------------------------------------------


@H.slow
def test_the_real_pal_mnk_ber_ogre_farm_path_is_the_same_with_and_without_pruning(capsys):
    import time

    profile, buffset, owned, candidates, _ = U.real_session()
    session = BuildOptions()
    haste = UP.session_haste(profile, owned, candidates, "dw", buffset, session)
    timings = {}
    for name, prune_pool in (("pruned", True), ("whole pool", False)):
        started = time.perf_counter()
        steps = UP.farm_path(profile, owned, candidates, "dw", buffset, 3, session, prune_pool=prune_pool)
        timings[name] = (time.perf_counter() - started, steps)
    pruned, whole = timings["pruned"][1], timings["whole pool"][1]
    assert len(pruned) == 3 and [s.F for s in pruned] == [s.F for s in whole]
    assert [(s.item.key, s.item.tier, s.kind) for s in pruned] == [(s.item.key, s.item.tier, s.kind) for s in whole]
    assert {s.haste_assumed for s in pruned} == {haste}
    kinds = [s.kind for s in pruned]
    with capsys.disabled():
        print(f"\n{len(owned)} owned items ({sum(owned.values())} copies), {len(candidates)} candidates, haste {haste}%")
        print(f"farm path of 3 steps: pruned {timings['pruned'][0]:.1f}s, whole pool {timings['whole pool'][0]:.1f}s; kinds {kinds}")
        print("gains", [round(float(s.gain), 3) for s in pruned])
