"""The weapon term is paid the haste the kit really counts (``trioforge.solver.haste``).

Before, the weapon index assumed one haste for the whole scenario (the best spell haste on offer plus the best worn haste of the
pool) whether or not the kit wore that item or took that buff, so a haste belt was rejected for being worth no more than what the
weapons got for free, and the shown value was above the kit's. Now the assumed haste is a decision: one program for each haste a kit
can count, each with a row that the kit counts at least that much, the best truthful value over them, every solution valued at the
haste it counts. These tests hold that, with hand-built pools, a brute force over every kit of random instances, and the real
catalog's war-clr-mnk +4 Ogre dual-wield scenario (the Melee damage build) of the probe of 2026-10-22 (a belt that the old rule rejected).
"""

from __future__ import annotations

import dataclasses
import random
from fractions import Fraction as F

import numpy as np
import pytest

from solver_helpers import Space, eval_totals, legal, make_buff, make_buffset, make_item, random_instance
from trioforge.model.formulas import EvalProfile, PoolSpec, evaluate
from trioforge.model.items import SLOT_INSTANCES, WeaponVec
from trioforge.solver._highs import solve_milp
from trioforge.solver import haste as haste_module
from trioforge.solver._highs import RawResult
from trioforge.solver.haste import solve_scenario
from trioforge.solver.model import BuildOptions, LevelPrograms, build_milp, haste_levels
from trioforge.solver.prune import prune
from trioforge.solver.solve import Solution, solve, solve_canonical

NAKED = {k: 100 for k in "STR STA AGI DEX WIS INT CHA".split()}
POOLS = {
    "HP": (PoolSpec("WAR", 1500, 5.0), PoolSpec("CLR", 1320, 4.4), PoolSpec("ENC", 1200, 4.0)),
    "MANA": (PoolSpec("CLR", 900, 4.5, "WIS"), PoolSpec("ENC", 900, 4.5, "INT")),
    "END": (PoolSpec("WAR", 900, 4.5), PoolSpec("CLR", 456, 3.25), PoolSpec("ENC", 260, 1.25)),
}
EXPLICIT = BuildOptions(any_rule="explicit")
SWORD = make_item("sword", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("1H Slashing", 20, 30, None, False))


def profile(**changes):
    base = dict(level=50, naked=NAKED, weights={}, pools=POOLS)
    base.update(changes)
    return EvalProfile(**base)


def counted(prof, solution, buffset=None, setup="dw"):
    """The haste the kit of ``solution`` counts, by the evaluator."""
    totals = eval_totals(buffset, solution.buffs) if buffset is not None else None
    return int(evaluate(prof, list(solution.kit), totals, setup=setup, haste_assumed=0).totals["haste"]["counted"])


def truthful(prof, solution, buffset=None, setup="dw"):
    """The exact value of the kit of ``solution`` at the haste it counts."""
    totals = eval_totals(buffset, solution.buffs) if buffset is not None else None
    return evaluate(prof, list(solution.kit), totals, setup=setup, haste_assumed=counted(prof, solution, buffset, setup)).F


def worn(solution, place):
    return sorted(item.key for item, name in zip(solution.kit, SLOT_INSTANCES) if item is not None and name == place)


# ---- the levels -----------------------------------------------------------------------------------------------------


def test_the_levels_are_every_spell_haste_crossed_with_no_worn_haste_and_each_worn_value():
    prof = profile(haste_cap=75, buff_totals={"HASTE": 5})
    buffset = make_buffset(always=[make_buff(900, haste=5)], optional=[make_buff(1, haste=30), make_buff(2, haste=40)], conflicts=[(1, 2)])
    items = [make_item("boots", {"FEET"}, haste=15), make_item("belt", {"WAIST"}, haste=25), make_item("cap", {"HEAD"}, haste=15)]
    # spell haste: 5 (no haste buff), 30, 40; worn: none, 15, 25 -> 5 20 30 | 30 45 55 | 40 55 65
    assert haste_levels(prof, items, "stick", buffset, EXPLICIT) == (5, 20, 30, 40, 45, 55, 65)


def test_the_levels_are_cut_at_the_cap_and_each_appears_once():
    prof = profile(haste_cap=60)
    buffset = make_buffset(optional=[make_buff(1, haste=30), make_buff(2, haste=45)], conflicts=[(1, 2)])
    items = [make_item("belt", {"WAIST"}, haste=30), make_item("cloak", {"BACK"}, haste=45)]
    # 0 | 30 | 45 spell, worn 0 30 45: 0 30 45 | 30 60 60 | 45 60 60
    assert haste_levels(prof, items, "stick", buffset, EXPLICIT) == (0, 30, 45, 60)


def test_unbound_alacrity_is_in_every_spell_haste_and_the_lowest_level_is_its_own():
    prof = profile(haste_cap=85, haste_bonus=10)
    buffset = make_buffset(optional=[make_buff(1, haste=40)])
    items = [make_item("belt", {"WAIST"}, haste=25)]
    assert haste_levels(prof, items, "stick", buffset, EXPLICIT) == (10, 35, 50, 75)


def test_a_slow_item_and_an_item_with_no_place_add_no_level():
    prof = profile()
    items = [make_item("anchor", {"FEET"}, haste=-20), make_item("nowhere", set(), haste=30)]
    assert haste_levels(prof, items, "stick", None, EXPLICIT) == (0,)


def test_a_spell_haste_at_the_cap_leaves_one_level():
    prof = profile(haste_cap=75, buff_totals={"HASTE": 80})
    items = [make_item("belt", {"WAIST"}, haste=25), make_item("boots", {"FEET"}, haste=15)]
    assert haste_levels(prof, items, "dw", None, EXPLICIT) == (75,)


# ---- the row ------------------------------------------------------------------------------------------------------------


def test_the_floor_row_makes_the_kit_count_at_least_that_much():
    prof = profile(weights={"HP": 1}, haste_cap=75)
    items = [make_item("belt", {"WAIST"}, haste=30), make_item("sash", {"WAIST"}, stats={"STA": 50})]
    free = build_milp(prof, items, "stick", None, BuildOptions(any_rule="explicit", haste_assumed=0))
    assert "haste.floor" not in free.row_names
    forced = build_milp(prof, items, "stick", None, BuildOptions(any_rule="explicit", haste_assumed=30, haste_floor=30))
    assert "haste.floor" in forced.row_names and forced.info["haste_floor"] == 30
    result = solve_milp(forced)
    assert [item.key for item in forced.decode(result.x).groups["WAIST"]] == ["belt"]  # the sash is worth more, the floor wants the belt
    unforced = solve_milp(free)
    assert [item.key for item in free.decode(unforced.x).groups["WAIST"]] == ["sash"]


def test_a_floor_the_pool_cannot_reach_has_no_solution_and_one_above_the_cap_is_refused():
    prof = profile(weights={"HP": 1}, haste_cap=75)
    items = [make_item("belt", {"WAIST"}, haste=20)]
    unreachable = build_milp(prof, items, "stick", None, BuildOptions(any_rule="explicit", haste_assumed=40, haste_floor=40))
    assert solve_milp(unreachable).status == "infeasible"
    with pytest.raises(ValueError, match="above the haste cap"):
        build_milp(prof, items, "stick", None, BuildOptions(any_rule="explicit", haste_assumed=80, haste_floor=80))
    with pytest.raises(ValueError, match="haste_floor"):
        BuildOptions(haste_floor=-1)


def test_the_floor_counts_an_optional_haste_buff_and_unbound_alacrity():
    prof = profile(weights={"HP": 1}, haste_cap=85, haste_bonus=10)
    buffset = make_buffset(optional=[make_buff(1, haste=40, STA=5)])
    belt = make_item("belt", {"WAIST"}, haste=25)
    # 10 (Unbound Alacrity) + 40 (the buff) + 25 (the belt, 35 of room left) = 75
    milp = build_milp(prof, [belt], "stick", buffset, BuildOptions(any_rule="explicit", haste_assumed=75, haste_floor=75))
    result = solve_milp(milp)
    decoded = milp.decode(result.x)
    assert result.status == "optimal" and decoded.buffs == (1,) and [i.key for i in decoded.groups["WAIST"]] == ["belt"]
    assert solve_milp(build_milp(prof, [belt], "stick", buffset, BuildOptions(any_rule="explicit", haste_assumed=76, haste_floor=76))).status == "infeasible"
    # the floor of the Unbound Alacrity haste alone is no row
    plain = build_milp(prof, [belt], "stick", buffset, BuildOptions(any_rule="explicit", haste_assumed=10, haste_floor=10))
    assert "haste.floor" not in plain.row_names


def test_the_haste_columns_exist_for_a_floor_when_haste_has_no_weight():
    prof = profile(weights={"DMG": 5}, haste_cap=75)
    items = [make_item("belt", {"WAIST"}, haste=30)]
    milp = build_milp(prof, items, "dw", None, BuildOptions(any_rule="explicit", haste_assumed=30, haste_floor=30))
    result = solve_milp(milp)
    assert result.status == "optimal" and [i.key for i in milp.decode(result.x).groups["WAIST"]] == ["belt"]


# ---- the pick -------------------------------------------------------------------------------------------------------------


def belt_pool():
    sash = make_item("sash", {"WAIST"}, stats={"STA": 10})  # worth about 94 HP
    belt = make_item("belt", {"WAIST"}, haste=30)  # worth nothing but the haste: 30% of the weapons, about 510 at this damage weight
    return [sash, belt, SWORD]


def test_a_haste_belt_the_old_rule_rejected_is_taken_once_the_weapon_credit_is_truthful():
    prof = profile(weights={"DMG": 1000, "HP": 1})
    items = belt_pool()
    old_milp = build_milp(prof, items, "dw", None, EXPLICIT)
    assert old_milp.haste_assumed == 30  # the weapons were paid 30% whatever the kit wore
    old = solve_canonical(old_milp)
    assert worn(old, "WAIST") == ["sash"]
    new = solve_scenario(prof, items, "dw", None, EXPLICIT)
    assert worn(new.solution, "WAIST") == ["belt"]
    assert new.haste == 30 and new.milp.haste_assumed == 30
    # the old kit, valued at the haste it counts, is worth less than the new
    assert truthful(prof, old) < new.solution.breakdown.F
    # and the old value shown for it was above what it is worth
    assert F(old.F) > truthful(prof, old)


def test_the_shown_value_is_the_evaluator_value_at_the_haste_the_kit_counts():
    prof = profile(weights={"DMG": 1000, "HP": 1})
    result = solve_scenario(prof, belt_pool(), "dw", None, EXPLICIT)
    kit = list(result.solution.kit)
    assert result.solution.breakdown.F == evaluate(prof, kit, setup="dw", haste_assumed=result.milp.haste_assumed).F
    assert result.solution.F == float(result.solution.breakdown.F)
    assert result.milp.haste_assumed == counted(prof, result.solution)
    assert abs(result.solution.model_F - result.solution.F) <= 1e-9 * result.solution.F


def test_a_trio_whose_spell_haste_is_at_the_cap_has_one_level_and_the_kit_is_the_old_kit():
    prof = profile(weights={"DMG": 1000, "HP": 1, "AC": 2}, buff_totals={"HASTE": 80}, haste_cap=75)
    sash = make_item("sash", {"WAIST"}, stats={"AC": 30})
    belt = make_item("belt", {"WAIST"}, haste=30, stats={"AC": 5})
    items = [sash, belt, SWORD]
    result = solve_scenario(prof, items, "dw", None, EXPLICIT)
    assert result.levels == (75,) and len(result.runs) == 1 and result.runs[0].outcome == "solved"
    assert "haste.floor" not in result.milp.row_names  # nothing above the base to demand
    old = solve_canonical(build_milp(prof, items, "dw", None, EXPLICIT))
    assert [i.key if i else None for i in result.solution.kit] == [i.key if i else None for i in old.kit]
    assert result.solution.F == old.F and result.haste == 75


def test_an_explicit_haste_assumed_is_one_program_at_that_constant():
    prof = profile(weights={"DMG": 1000, "HP": 1})
    result = solve_scenario(prof, belt_pool(), "dw", None, BuildOptions(any_rule="explicit", haste_assumed=0))
    assert result.levels == (0,) and result.haste == 0
    assert worn(result.solution, "WAIST") == ["sash"]  # at 0% the belt gets nothing: the sash wins, as the old program said
    assert "haste.floor" not in result.milp.row_names
    with pytest.raises(ValueError, match="haste_floor needs haste_assumed"):  # (refused when the options are made, not only by the solve)
        BuildOptions(any_rule="explicit", haste_floor=10)
    with pytest.raises(ValueError, match="haste_floor needs haste_assumed"):
        build_milp(prof, belt_pool(), "dw", None, BuildOptions(any_rule="explicit", haste_exact=False, haste_floor=10))


def test_an_optional_haste_buff_is_taken_for_the_weapons_and_the_belt_for_the_room_it_leaves():
    # the weapons are worth most at the highest haste: Unbound Alacrity 10 plus buff 40 plus the belt's 30 is 80, under the cap of 85
    prof = profile(weights={"DMG": 1000, "HP": 1}, haste_cap=85, haste_bonus=10)
    buffset = make_buffset(optional=[make_buff(1, haste=40), make_buff(2, haste=20, STA=4)], conflicts=[(1, 2)])
    items = belt_pool()
    result = solve_scenario(prof, items, "dw", buffset, EXPLICIT)
    assert result.solution.buffs == (1,) and worn(result.solution, "WAIST") == ["belt"]
    assert result.haste == 80 == counted(prof, result.solution, buffset)


def test_levels_that_cannot_win_are_not_solved_and_the_answer_is_the_same_without_the_bound():
    prof = profile(weights={"DMG": 1000, "HP": 1})
    bound = solve_scenario(prof, belt_pool(), "dw", None, EXPLICIT)
    every = solve_scenario(prof, belt_pool(), "dw", None, EXPLICIT, bound=False)
    assert [run.outcome for run in every.runs] == ["solved"] * len(every.levels)
    assert bound.solution.breakdown.F == every.solution.breakdown.F
    assert [i.key if i else None for i in bound.solution.kit] == [i.key if i else None for i in every.solution.kit]
    assert bound.haste == every.haste


def test_the_plain_solver_can_stand_in_for_the_canonical_one():
    prof = profile(weights={"DMG": 1000, "HP": 1})
    plain = solve_scenario(prof, belt_pool(), "dw", None, EXPLICIT, solver=solve)
    assert worn(plain.solution, "WAIST") == ["belt"] and plain.solution.tie_stage is None


# ---- the brute force ----------------------------------------------------------------------------------------------------


class TruthSpace(Space):
    """Every legal kit of an instance valued at the haste it counts (the weapon term is built at 0 and scaled)."""

    def counted(self, feat_haste, chosen):
        p = self.p
        b = eval_totals(self.inst.buffset, chosen) if self.inst.buffset is not None else dict(p.buff_totals)
        spell, cap = float(b.get("HASTE", 0)) + float(p.haste_bonus), float(p.haste_cap)
        return min(spell, cap) + np.minimum(feat_haste, max(0.0, cap - spell)), float(b.get("HASTE", 0))

    def values(self, chosen=()):
        base = super().values(chosen)  # the HASTE part of the base knows no Unbound Alacrity: put it right
        p = self.p
        true, spell_without_bonus = self.counted(self.feat["HASTE"], chosen)
        cap = float(p.haste_cap)
        old = min(spell_without_bonus, cap) + np.minimum(self.feat["HASTE"], max(0.0, cap - spell_without_bonus))
        weights = {k: float(v) for k, v in p.weights.items()}
        return base + weights.get("HASTE", 0.0) * (true - old) + weights.get("DMG", 0.0) * self.feat["WEAPON"] * true / 100

    def exact(self, combo, chosen):
        kit = self.kit_of(combo)
        totals = eval_totals(self.inst.buffset, chosen) if self.inst.buffset else None
        first = evaluate(self.inst.profile, kit, totals, setup=self.inst.setup, haste_assumed=0)
        return evaluate(
            self.inst.profile, kit, totals, setup=self.inst.setup, haste_assumed=first.totals["haste"]["counted"]
        ).F


def weapon_instance(seed, bonus):
    """A random small instance with weapons, haste items and (usually) haste buffs, a heavy damage weight and a setup that scores it."""
    rng = random.Random(seed)
    for _ in range(200):
        inst = random_instance(rng, haste_buffs=rng.random() < 0.7, setup=rng.choice(("dw", "dw", "1h-shield", "2h")))
        has_weapon = any(item.weapon is not None and item.weapon.dmg > 0 for item in inst.items)
        hasty = any(item.haste > 0 for item in inst.items)
        if has_weapon and hasty:
            weights = {**dict(inst.profile.weights), "DMG": 200.0}
            profile_ = dataclasses.replace(inst.profile, weights=weights, haste_bonus=bonus)
            return dataclasses.replace(inst, profile=profile_, haste_assumed=0)
    raise AssertionError(f"no instance with weapons and haste items for seed {seed}")


@pytest.mark.parametrize("seed", range(24))
def test_the_truthful_optimum_equals_the_brute_force_over_every_kit(seed):
    inst = weapon_instance(seed, bonus=10 if seed % 3 == 0 else 0)
    space = TruthSpace(inst)
    best, _, _ = space.best()
    options = BuildOptions(any_rule=inst.any_rule)
    result = solve_scenario(inst.profile, inst.items, inst.setup, inst.buffset, options)
    assert result.solution.status == "optimal"
    scale = max(F(1), abs(best))
    assert abs(result.solution.breakdown.F - best) / scale <= F(1, 10**9), (inst.label, float(result.solution.breakdown.F), float(best))
    groups = {}
    for item, place in zip(result.solution.kit, SLOT_INSTANCES):
        if item is not None:
            groups.setdefault(place, []).append(item)
    assert legal(groups, inst.setup)
    # the shown value is the evaluator's at the haste the kit counts, and the model agrees with it
    totals = eval_totals(inst.buffset, result.solution.buffs) if inst.buffset else None
    again = evaluate(inst.profile, list(result.solution.kit), totals, setup=inst.setup, haste_assumed=result.milp.haste_assumed)
    assert again.F == result.solution.breakdown.F
    assert result.milp.haste_assumed == int(again.totals["haste"]["counted"])
    assert abs(result.solution.model_F - float(again.F)) <= 1e-6 * max(1.0, abs(float(again.F)))
    # without the bound: every level solved, the same optimum
    every = solve_scenario(inst.profile, inst.items, inst.setup, inst.buffset, options, solver=solve, bound=False)
    assert every.solution.breakdown.F == result.solution.breakdown.F


@pytest.mark.parametrize("seed", range(8))
def test_pruning_keeps_the_truthful_optimum_and_does_not_depend_on_the_haste_it_ranks_weapons_at(seed):
    inst = weapon_instance(100 + seed, bonus=0)
    options = BuildOptions(any_rule=inst.any_rule)
    kept = prune(inst.items, inst.profile, None, inst.setup, inst.buffset, options)
    for haste in (0, 25, 75):  # the weapon index ranks the weapons of a hand alike at every haste
        assert prune(inst.items, inst.profile, None, inst.setup, inst.buffset, dataclasses.replace(options, haste_assumed=haste)) == kept
    full = solve_scenario(inst.profile, inst.items, inst.setup, inst.buffset, options)
    cut = solve_scenario(inst.profile, kept, inst.setup, inst.buffset, options)
    assert full.solution.breakdown.F == cut.solution.breakdown.F


# ---- the real scenario of the probe ---------------------------------------------------------------------------------------


def war_clr_mnk_melee_plus_four():
    """A view of war-clr-mnk (Melee damage build, +4, wiki evidence, own buffs) for the Ogre with dual wield: the profile, the pruned pool and the buff set, as the precompute makes
    them. The build is what matters here and the rule about spell haste is not: the own buffs of this trio carry no haste spell (a Cleric and a Monk have none), so the buffs are the
    same whether the rule ``haste.assume_spell`` is true or false. The probe of 2026-10-22 was made for the Tank of the time, which weighed the weapon enough for the first pass to
    miss the belt; the Tank of the builds weighs it at a factor of 0.5 and has no gap in this view (new F equals the old truth), and Melee damage, which weighs it in full, does."""
    from trioforge.precompute import grid

    catalog = grid.find_catalog()
    if catalog is None:
        pytest.skip("derived/catalog.json is not built")
    config, _ = grid.load_inputs(grid.parse_trio("war-clr-mnk"), catalog_path=catalog, canonical=True)
    context = grid.Context(config)
    prof = context.profile("OGR", "melee", "own", "wiki")
    buffset = context.buffsets["own"]
    pruned = prune(context.pool("wiki", 4), prof, 4, "dw", buffset, grid.BUILD_OPTIONS)
    return grid, context, prof, buffset, pruned


def test_war_clr_mnk_wears_the_belt_of_the_four_winds_and_its_value_is_its_truthful_value():
    grid, context, prof, buffset, pruned = war_clr_mnk_melee_plus_four()
    old = solve_canonical(build_milp(prof, pruned, "dw", buffset, grid.BUILD_OPTIONS))
    old_truth = truthful(prof.eval_profile, old, buffset)
    new = solve_scenario(prof, pruned, "dw", buffset, grid.BUILD_OPTIONS)
    waist = [item.name for item, place in zip(new.solution.kit, SLOT_INSTANCES) if item is not None and place == "WAIST"]
    assert waist == ["Belt of the Four Winds"]
    assert new.solution.breakdown.F > old_truth  # the old kit, valued at the haste it counts, is worth less
    # the shown value is the evaluator's at the haste the kit counts
    totals = grid.eval_buff_totals(buffset.totals(new.solution.buffs))
    kit = list(new.solution.kit)
    assert evaluate(prof.eval_profile, kit, totals, setup="dw", haste_assumed=new.haste).F == new.solution.breakdown.F
    assert new.haste == int(evaluate(prof.eval_profile, kit, totals, setup="dw", haste_assumed=0).totals["haste"]["counted"])
    assert abs(new.solution.model_F - new.solution.F) <= 1e-6 * new.solution.F
    # and the old rule overstated the old kit
    assert old.F > old_truth


# ---- the rows that make a level exact --------------------------------------------------------------------------------------


def test_haste_exact_needs_a_floor_and_adds_the_rows_that_keep_the_kit_from_counting_more():
    with pytest.raises(ValueError, match="haste_exact needs haste_floor"):
        BuildOptions(haste_exact=True)
    prof = profile(weights={"HP": 1}, haste_cap=75, haste_bonus=10)
    buffset = make_buffset(optional=[make_buff(1, haste=30), make_buff(2, haste=45)], conflicts=[(1, 2)])
    items = [make_item("boots", {"FEET"}, haste=15), make_item("belt", {"WAIST"}, haste=25)]
    # level 40: the 10 of Unbound Alacrity leaves 30 for a worn piece, which neither has; the 40 of buff 1 alone is the level, so no piece goes with it; buff 2 alone is 55
    milp = build_milp(prof, items, "stick", buffset, BuildOptions(any_rule="explicit", haste_assumed=40, haste_floor=40, haste_exact=True))
    assert milp.info["haste_exact"] is True
    names = milp.row_names
    assert "haste.ceil[10]" not in names and "haste.ceil[40]" in names and "haste.over[55]" in names
    low = build_milp(prof, items, "stick", buffset, BuildOptions(any_rule="explicit", haste_assumed=20, haste_floor=20, haste_exact=True))
    assert "haste.ceil[10]" in low.row_names and "haste.over[40]" in low.row_names  # at 20 the base leaves 10: both pieces are above; both buffs alone are above
    free = build_milp(prof, items, "stick", buffset, BuildOptions(any_rule="explicit", haste_assumed=40, haste_floor=40))
    assert not [n for n in free.row_names if n.startswith(("haste.ceil", "haste.over"))] and "haste_exact" not in free.info
    # at the cap there is nothing above to keep out
    top = build_milp(prof, items, "stick", buffset, BuildOptions(any_rule="explicit", haste_assumed=75, haste_floor=75, haste_exact=True))
    assert not [n for n in top.row_names if n.startswith(("haste.ceil", "haste.over"))]


def test_an_exact_level_holds_only_the_kits_that_count_that_haste():
    prof = profile(weights={"HP": 1}, haste_cap=75)
    # a belt of 30 and boots of 10 that are worth some HP: at level 0 neither may be worn, at 10 only the boots, at 30 the belt must be
    items = [make_item("belt", {"WAIST"}, haste=30, stats={"STA": 1}), make_item("boots", {"FEET"}, haste=10, stats={"STA": 5})]
    for level, worn_keys in ((0, []), (10, ["boots"]), (30, ["belt", "boots"])):  # (the best piece counts: the boots may stay)
        milp = build_milp(prof, items, "stick", None, BuildOptions(any_rule="explicit", haste_assumed=level, haste_floor=level, haste_exact=True))
        result = solve_milp(milp)
        assert result.status == "optimal", level
        decoded = milp.decode(result.x)
        keys = sorted(item.key for placed in decoded.groups.values() for item in placed)
        assert keys == worn_keys, (level, keys)
        kit = [None] * 22
        for group, placed in decoded.groups.items():
            for item in placed:
                kit[SLOT_INSTANCES.index(group)] = item
        counted = evaluate(prof, kit, setup="stick", haste_assumed=0).totals["haste"]["counted"]
        assert counted == level


# ---- the edges of the level loop (the fix round) ---------------------------------------------------------------------------


def stopped_on_time(milp, **kwargs):
    return Solution("time_limit", None, None, (), None, 5)


def infeasible(milp, **kwargs):
    return Solution("infeasible", None, None, (), None, 0)


def test_when_every_level_is_infeasible_the_answer_is_infeasible_with_the_bound_on_too(monkeypatch):
    prof = profile(weights={"DMG": 1000, "HP": 1})
    monkeypatch.setattr(haste_module, "_relaxation", lambda milp: None)  # every relaxation is proven infeasible
    result = solve_scenario(prof, belt_pool(), "dw", None, EXPLICIT)
    assert result.solution.status == "infeasible" and result.solution.kit is None
    assert len(result.levels) > 1 and all(run.outcome == "infeasible" for run in result.runs)
    assert result.milp.options.haste_exact and result.level == result.levels[-1]
    again = solve_scenario(prof, belt_pool(), "dw", None, EXPLICIT, solver=infeasible, bound=False)
    assert again.solution.status == "infeasible"


def test_a_level_that_stopped_on_its_time_with_no_kit_is_never_called_infeasible():
    prof = profile(weights={"DMG": 1000, "HP": 1})
    calls = []

    def solver(milp, **kwargs):
        calls.append(milp.haste_assumed)
        return stopped_on_time(milp) if len(calls) == 1 else infeasible(milp)

    result = solve_scenario(prof, belt_pool(), "dw", None, EXPLICIT, solver=solver, bound=False)
    assert result.solution.status == "time_limit" and result.solution.kit is None
    assert result.solution.nodes == 5  # the nodes of the level that stopped
    assert result.level == calls[0] == result.levels[-1] and result.milp.haste_assumed == result.level  # the level whose answer it is


def test_only_a_proof_of_infeasibility_drops_a_level_in_the_relaxation(monkeypatch):
    prof = profile(weights={"DMG": 1000, "HP": 1})
    want = solve_scenario(prof, belt_pool(), "dw", None, EXPLICIT, bound=False)
    for outcome in (RawResult("time_limit", None, None, None, 0, None), RawResult("kIterationLimit", None, None, None, 0, None)):
        monkeypatch.setattr(haste_module, "run_arrays", lambda *a, **k: outcome)
        assert haste_module._relaxation(build_milp(prof, belt_pool(), "dw", None, BuildOptions(any_rule="explicit", haste_assumed=30))) == float("inf")
    def trouble(*a, **k):
        raise RuntimeError("HiGHS ended with status 'Unbounded'")
    monkeypatch.setattr(haste_module, "run_arrays", trouble)
    assert haste_module._relaxation(build_milp(prof, belt_pool(), "dw", None, BuildOptions(any_rule="explicit", haste_assumed=30))) == float("inf")
    monkeypatch.setattr(haste_module, "run_arrays", lambda *a, **k: RawResult("infeasible", None, None, None, 0, None))
    assert haste_module._relaxation(build_milp(prof, belt_pool(), "dw", None, BuildOptions(any_rule="explicit", haste_assumed=30))) is None
    monkeypatch.undo()
    # no bound means every level is solved and the answer is the same
    monkeypatch.setattr(haste_module, "_relaxation", lambda milp: float("inf"))
    got = solve_scenario(prof, belt_pool(), "dw", None, EXPLICIT)
    assert got.solution.breakdown.F == want.solution.breakdown.F and all(run.outcome in ("solved", "bound") for run in got.runs)


def test_two_haste_buffs_that_can_be_active_together_are_refused_by_the_builder():
    prof = profile(weights={"HP": 1}, haste_cap=75)
    two = make_buffset(optional=[make_buff(1, haste=30), make_buff(2, haste=40)])  # no conflict between them
    with pytest.raises(ValueError, match="both carry spell haste and can be active together"):
        build_milp(prof, [], "stick", two, EXPLICIT)
    with pytest.raises(ValueError, match="both carry spell haste"):
        haste_levels(prof, [], "stick", two, EXPLICIT)
    ok = make_buffset(optional=[make_buff(1, haste=30), make_buff(2, haste=40)], conflicts=[(1, 2)])
    milp = build_milp(prof, [], "stick", ok, EXPLICIT)
    assert any(name.startswith("buff.") for name in milp.row_names)  # the exclusion is a row, so the haste of the active buff is one buff's
    cliqued = make_buffset(optional=[make_buff(1, haste=30), make_buff(2, haste=40), make_buff(3, STA=5)], conflicts=[(1, 2), (1, 3), (2, 3)], cliques=[(1, 2, 3)])
    build_milp(prof, [], "stick", cliqued, EXPLICIT)  # a clique covers the pair


# ---- the level programs are built once (the fix round) -------------------------------------------------------------------------


def same_milp(got, want):
    for name in ("c", "row_lb", "row_ub", "col_lb", "col_ub", "integrality"):
        assert np.array_equal(getattr(got, name), getattr(want, name)), name
    for name in ("start", "index", "value"):
        assert np.array_equal(getattr(got.A, name), getattr(want.A, name)), name
    assert got.A.shape == want.A.shape
    assert got.const == want.const and got.haste_assumed == want.haste_assumed and got.options == want.options
    assert got.names == want.names and got.row_names == want.row_names
    assert got.info == want.info and list(got.info) == list(want.info)
    assert got.colmap == want.colmap and got.index == want.index and got.buff_cols == want.buff_cols and got.setup == want.setup


@pytest.mark.parametrize("seed", range(24))
def test_a_level_program_made_from_the_shared_build_is_the_one_build_milp_makes(seed):
    inst = weapon_instance(seed, bonus=10 if seed % 3 == 0 else 0)
    options = BuildOptions(any_rule=inst.any_rule)
    programs = LevelPrograms(inst.profile, inst.items, inst.setup, inst.buffset, options)
    assert programs.levels == haste_levels(inst.profile, inst.items, inst.setup, inst.buffset, options)
    for level in programs.levels:
        direct = build_milp(
            inst.profile, inst.items, inst.setup, inst.buffset, dataclasses.replace(options, haste_assumed=level, haste_floor=level, haste_exact=True)
        )
        same_milp(programs.program_for(level), direct)
    assert programs.program_for(programs.levels[0]) is programs.program_for(programs.levels[0])


def test_the_shared_build_serves_the_hand_built_belt_pool_and_a_level_that_is_the_cap():
    prof = profile(weights={"DMG": 1000, "HP": 1}, haste_cap=60, haste_bonus=10, buff_totals={"HASTE": 5})
    buffset = make_buffset(always=[make_buff(900, haste=5)], optional=[make_buff(1, haste=30), make_buff(2, haste=45)], conflicts=[(1, 2)])
    items = [*belt_pool(), make_item("cloak", {"BACK"}, haste=45)]
    programs = LevelPrograms(prof, items, "dw", buffset, EXPLICIT)
    assert programs.levels[-1] == 60 and len(programs.levels) > 3
    for level in programs.levels:
        same_milp(programs.program_for(level), build_milp(prof, items, "dw", buffset, dataclasses.replace(EXPLICIT, haste_assumed=level, haste_floor=level, haste_exact=True)))
    with pytest.raises(ValueError, match="above the haste cap"):
        programs.program_for(61)


# ---- the cutoff of a level's search (the fix round) -----------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(24))
def test_a_cutoff_never_hides_a_kit_that_reaches_it_and_a_level_below_it_gives_none_that_reaches_it(seed):
    inst = weapon_instance(seed, bonus=10 if seed % 3 == 0 else 0)
    options = BuildOptions(any_rule=inst.any_rule)
    programs = LevelPrograms(inst.profile, inst.items, inst.setup, inst.buffset, options)
    for level in programs.levels:
        milp = programs.program_for(level)
        plain = solve(milp)
        if plain.status == "infeasible":
            assert solve(milp, cutoff=0.0).status == "infeasible"
            continue
        best = plain.model_F
        scale = max(1.0, abs(best))
        for cutoff in (best - 1e-6 * scale, best - 5.0 * scale, best + 1e-3 * scale, best + 10.0 * scale):
            cut = solve(milp, cutoff=cutoff)
            if cut.status == "optimal" and cut.kit is not None and cut.model_F >= cutoff:
                assert abs(cut.model_F - best) <= 1e-7 * scale, (seed, level, cutoff)  # a kit that reaches the cutoff is the level's best
            elif best >= cutoff:
                raise AssertionError(f"the cutoff {cutoff} hid the best kit {best} of level {level} (seed {seed}): {cut.status} {cut.model_F}")
            else:
                assert cut.status in ("infeasible", "optimal") and (cut.kit is None or cut.model_F < cutoff)


def test_solve_scenario_with_the_cutoff_gives_the_answer_without_it_and_a_solver_that_takes_none_works_too():
    for seed in range(12):
        inst = weapon_instance(seed, bonus=10 if seed % 3 == 0 else 0)
        options = BuildOptions(any_rule=inst.any_rule)
        with_cut = solve_scenario(inst.profile, inst.items, inst.setup, inst.buffset, options, solver=solve_canonical)
        without = solve_scenario(inst.profile, inst.items, inst.setup, inst.buffset, options, solver=solve_canonical, bound=False)
        plain = solve_scenario(inst.profile, inst.items, inst.setup, inst.buffset, options, solver=lambda milp, **kw: solve_canonical(milp, **kw))
        for got in (without, plain):
            assert got.solution.breakdown.F == with_cut.solution.breakdown.F and got.level == with_cut.level and got.haste == with_cut.haste
            assert [i.key if i else None for i in got.solution.kit] == [i.key if i else None for i in with_cut.solution.kit]


# ---- evaluate_truthful values a kit once (the fix round) ----------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(24))
def test_evaluate_truthful_is_the_evaluation_at_the_haste_the_kit_counts_to_the_last_bit(seed):
    from trioforge.model.formulas import evaluate_truthful

    inst = weapon_instance(seed, bonus=10 if seed % 3 == 0 else 0)
    space = TruthSpace(inst)
    rng = random.Random(seed)
    chosen_sets = space.buff_sets
    for _ in range(40):
        combo = rng.choice(space.kits)
        chosen = rng.choice(chosen_sets)
        kit = space.kit_of(combo)
        totals = eval_totals(inst.buffset, chosen) if inst.buffset else None
        first = evaluate(inst.profile, kit, totals, setup=inst.setup, haste_assumed=0)
        again = evaluate(inst.profile, kit, totals, setup=inst.setup, haste_assumed=first.totals["haste"]["counted"])
        got = evaluate_truthful(inst.profile, kit, totals, setup=inst.setup)
        assert got == again and list(got.parts) == list(again.parts)
