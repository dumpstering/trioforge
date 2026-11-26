"""Tests for the solver wrapper: ``trioforge.solver.solve``.

``solve`` runs HiGHS on a built model, reads the kit back, values it with the exact oracle and refuses a model whose
own objective is off. ``solve_canonical`` adds the deterministic second stage: among the kits within 1e-7 relative of
the optimum it takes the one with the least total rank (an item's rank is its place in the sorted keys, a buff's
comes after all items), so ties between different kits resolve the same way on every run and every input order.
Every name, race and item here is invented.
"""

import dataclasses
import random
from fractions import Fraction
from types import SimpleNamespace

import pytest

import solver_helpers as H
from solver_helpers import make_buff, make_buffset, make_item
from trioforge.model import formulas as fm
from trioforge.model.formulas import EvalProfile, PoolSpec, evaluate
from trioforge.model.items import SLOT_INSTANCES, WeaponVec
from trioforge.model.profile import make_profile as real_profile
from trioforge.solver import solve as solve_module
from trioforge.solver._highs import RawResult
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.solve import ExactnessError, Solution, canonical_kit, solve, solve_canonical

F = Fraction
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


def worn(solution):
    """``{place: key}`` of the worn items, by the place of the kit."""
    return {SLOT_INSTANCES[i]: item.key for i, item in enumerate(solution.kit) if item is not None}


def keys_in(solution, group):
    return [item.key if item else None for item, name in zip(solution.kit, SLOT_INSTANCES) if name == group]


# ---- the plain solve ---------------------------------------------------------------------------------------------


def test_solve_returns_the_optimal_kit_its_exact_value_and_the_search_figures():
    prof = profile(weights={"HP": 1, "END": 1})
    items = [make_item("h1", {"HEAD"}, stats={"STA": 10}), make_item("h2", {"HEAD"}, stats={"STA": 30})]
    solution = solve(build(prof, items))
    assert isinstance(solution, Solution) and solution.status == "optimal"
    assert keys_in(solution, "HEAD") == ["h2"] and solution.buffs == ()
    kit = list(solution.kit)
    exact = evaluate(prof, kit)
    assert solution.F == float(exact.F) and solution.breakdown == exact
    assert solution.gap == 0.0 and isinstance(solution.nodes, int)
    assert abs(solution.model_F - solution.F) <= 1e-9 * max(1.0, abs(solution.F))


def test_the_kit_is_a_tuple_of_the_twenty_two_places_and_empty_places_hold_none():
    solution = solve(build(profile(), [make_item("h", {"HEAD"}, stats={"STA": 10})]))
    assert isinstance(solution.kit, tuple) and len(solution.kit) == len(SLOT_INSTANCES) == 22
    assert sum(item is not None for item in solution.kit) == 1


def test_an_empty_pool_is_optimal_and_worth_the_naked_character_with_an_empty_kit():
    prof = profile(weights={"HP": 1, "AC": 2, "HASTE": 1}, buff_totals={"HASTE": 12, "HP": 40})
    for items in ([], [make_item("ammo", {"AMMO"}, stats={"HP": 99})]):
        solution = solve_canonical(build(prof, items))
        assert solution.status == "optimal" and solution.kit == (None,) * 22 and solution.buffs == ()
        assert solution.F == float(evaluate(prof, [None] * 22).F)


def test_the_chosen_buffs_are_reported_and_reproduce_the_solve():
    prof = profile(weights={"HP": 1})
    buffset = make_buffset(optional=[make_buff(1, HP=50), make_buff(2, HP=70), make_buff(3, HP=20)], conflicts=[(1, 2)])
    solution = solve(build(prof, [], buffset=buffset))
    assert solution.buffs == (2, 3)
    again = evaluate(prof, list(solution.kit), H.eval_totals(buffset, solution.buffs))
    assert float(again.F) == solution.F


def test_an_infeasible_model_is_reported_not_raised():
    milp = build(profile(), [make_item("h", {"HEAD"}, stats={"STA": 10})])
    milp.col_lb[milp.index[("HEAD", "h")]] = 2  # the group has one place
    solution = solve(milp)
    assert solution.status == "infeasible" and solution.kit is None and solution.F is None


def test_the_time_limit_status_is_propagated():
    prof = profile(weights={"HP": 1, "END": 1, "AC": 3})
    items = [make_item(f"i{n}", {"HEAD", "NECK", "CHEST"}, stats={"STA": n, "AC": 3 * n}) for n in range(30)]
    solution = solve(build(prof, items), time_limit=0.0)
    assert solution.status == "time_limit"
    assert solution.kit is None and solution.F is None  # nothing was found in no time
    # with an incumbent, the best found comes back labelled as such
    milp = build(prof, items)
    real = solve_module.solve_milp(milp)
    fake = RawResult("time_limit", real.x, real.objective, 0.25, 7, real.objective + 1.0)
    original = solve_module.solve_milp
    solve_module.solve_milp = lambda *a, **k: fake
    try:
        partial = solve(milp, time_limit=1.0)
    finally:
        solve_module.solve_milp = original
    assert partial.status == "time_limit" and partial.kit is not None and partial.gap == 0.25 and partial.nodes == 7
    assert partial.F == float(evaluate(prof, list(partial.kit)).F)


# ---- a solve that runs out of time, with a real incumbent --------------------------------------------------------------


def groups_of(solution):
    """``{group: [items]}`` of a solution's kit."""
    groups = {}
    for item, name in zip(solution.kit, SLOT_INSTANCES):
        if item is not None:
            groups.setdefault(name, []).append(item)
    return groups


def assert_a_legal_kit(solution, milp):
    """Every worn item fits its place under the setup and the Any rule, Lore items are worn once, a two-hander leaves
    the off hand empty: the checks of the independent brute force, applied to a kit that a solver stopped early."""
    groups = groups_of(solution)
    assert H.legal(groups, milp.setup)
    for group, placed in groups.items():
        assert all(H.fits(item, group, milp.setup, milp.options.any_rule) for item in placed), group


@pytest.fixture(scope="module")
def big_milp():
    """About a thousand invented items for a Barbarian Berserker/Monk/Warrior in dual wield: HiGHS needs seconds to
    prove the optimum, and a limit of a fraction of a second stops it at the first incumbent it found."""
    prof = real_profile("BAR", ("BER", "MNK", "WAR"), 50, "tank", None, None, H.TABLES)
    return build_milp(prof, H.invented_pool(60, seed=1), "dw")


# seconds; the first incumbent of this pool arrives with the root, so any of the first three gets it on an idle machine,
# and the longer ones are there for a slow or busy one (the solve itself takes seconds, so each of them still stops early)
TINY_LIMITS = (0.02, 0.1, 0.5, 2.0)


def exact_of(solution, milp):
    return evaluate(milp.profile, list(solution.kit), None, setup=milp.setup, haste_assumed=milp.haste_assumed)


def test_a_time_limited_solve_with_a_real_incumbent_reports_the_exact_value_of_its_kit(big_milp):
    # HiGHS hands back the incumbent it has when the time is up. Its continuous columns are not at their best values,
    # so the model's own value of it is *below* the exact value of its kit. That is a result (a lower bound), not an
    # ExactnessError. No faked result here: the incumbent is whatever HiGHS found.
    answered = understated = 0
    for limit in TINY_LIMITS:
        solution = solve(big_milp, time_limit=limit)
        if solution.kit is None:
            continue  # no incumbent yet at this limit
        answered += 1
        assert solution.status == "time_limit" and not solution.canonical
        exact = exact_of(solution, big_milp)
        assert solution.F == float(exact.F) and solution.breakdown == exact
        assert len(solution.kit) == len(SLOT_INSTANCES) and any(item is not None for item in solution.kit)
        scale = 1e-6 * max(1.0, abs(solution.F))
        assert solution.model_F <= solution.F + scale  # the model never overstates what an incumbent is worth
        understated += solution.model_F < solution.F - scale
        assert_a_legal_kit(solution, big_milp)
        if understated:
            break  # a real incumbent below its exact value has been seen and checked: enough
    assert answered >= 1, "no time limit produced an incumbent: this pool no longer exercises the time limit"
    assert understated >= 1, "no incumbent was below its exact value: this pool no longer exercises the old failure"


def test_solve_canonical_returns_a_time_limited_first_stage_as_it_is(big_milp):
    for limit in TINY_LIMITS:
        solution = solve_canonical(big_milp, time_limit=limit)
        if solution.kit is None:
            continue
        assert solution.status == "time_limit" and not solution.canonical
        exact = exact_of(solution, big_milp)
        assert solution.F == float(exact.F)
        assert solution.model_F <= solution.F + 1e-6 * max(1.0, abs(solution.F))  # below its exact value is no error
        assert_a_legal_kit(solution, big_milp)
        return
    pytest.fail("no time limit produced an incumbent")


def test_a_model_that_overstates_its_kit_is_an_error_at_a_time_limit_too():
    # an incumbent can be worth less than its kit; it can never be worth more. The fake is only the status label.
    milp = build(profile(), [make_item("h", {"HEAD"}, stats={"HP": 100})])
    real = solve_module.solve_milp(milp)
    milp.const += 1.0
    fake = RawResult("time_limit", real.x, real.objective, 0.0, 1, real.objective)
    original = solve_module.solve_milp
    solve_module.solve_milp = lambda *args, **kwargs: fake
    try:
        with pytest.raises(ExactnessError, match="overstates.*relative"):
            solve(milp, time_limit=1.0)
    finally:
        solve_module.solve_milp = original


def test_a_model_that_understates_its_kit_is_a_result_not_an_error():
    # ExactnessError is for a model that overstates what its kit is worth; the oracle's value is the answer. (A kit that
    # a limit or the tie stage left with continuous columns below their best values has a model value under its exact one.)
    milp = build(profile(), [make_item("h", {"HEAD"}, stats={"HP": 100})])
    milp.const -= 1.0
    for solution in (solve(milp), solve_canonical(milp)):
        assert solution.status == "optimal" and keys_in(solution, "HEAD") == ["h"]
        assert solution.F == float(evaluate(milp.profile, list(solution.kit)).F)
        assert solution.model_F == pytest.approx(solution.F - 1.0, abs=1e-9)


def test_a_model_whose_objective_is_wrong_raises_an_exactness_error():
    prof = profile(weights={"HP": 1})
    milp = build(prof, [make_item("h", {"HEAD"}, stats={"HP": 100})])
    solve(milp)  # fine as built
    milp.c[milp.index[("HEAD", "h")]] *= 1.01  # a deliberately corrupted coefficient: the model now overstates the kit
    with pytest.raises(ExactnessError):
        solve(milp)
    with pytest.raises(ExactnessError):
        solve_canonical(milp)
    corrupt_const = build(prof, [make_item("h", {"HEAD"}, stats={"HP": 100})])
    corrupt_const.const += 1.0
    with pytest.raises(ExactnessError, match="1e-06|relative"):
        solve(corrupt_const)


def test_a_small_float_error_is_not_an_exactness_error():
    milp = build(profile(), [make_item("h", {"HEAD"}, stats={"HP": 100})])
    milp.const += 1e-9
    assert solve(milp).status == "optimal"


# ---- the canonical kit -------------------------------------------------------------------------------------------


def test_a_paired_group_is_sorted_by_key_and_empty_places_come_last():
    prof = profile()
    zed = make_item("zed-ring", {"EAR"}, stats={"HP": 50}, lore=True)  # Lore: two different rings fill the pair
    cob = make_item("cob-ring", {"EAR"}, stats={"HP": 40}, lore=True)
    for order in ([zed, cob], [cob, zed]):
        assert keys_in(solve(build(prof, order)), "EAR") == ["cob-ring", "zed-ring"]
    only = solve(build(prof, [make_item("single", {"EAR"}, stats={"HP": 5}, lore=True)]))
    assert keys_in(only, "EAR") == ["single", None]
    twice = solve(build(prof, [make_item("pair", {"WRIST"}, stats={"HP": 5})]))
    assert keys_in(twice, "WRIST") == ["pair", "pair"]


def test_canonical_kit_orders_every_paired_group_and_leaves_the_single_places_alone():
    a, b, c = (make_item(k, {"EAR", "WRIST", "FINGER", "ANY"}) for k in "abc")
    head = make_item("head", {"HEAD"})
    kit = canonical_kit({"HEAD": [head], "EAR": [c, a], "WRIST": [b], "FINGER": [c, c], "ANY": [b, a]})
    paired = ("HEAD", "EAR", "WRIST", "FINGER", "ANY")
    shown = [(n, i.key if i else None) for n, i in zip(SLOT_INSTANCES, kit) if n in paired]
    assert shown == [
        ("HEAD", "head"), ("EAR", "a"), ("EAR", "c"), ("WRIST", "b"), ("WRIST", None), ("FINGER", "c"), ("FINGER", "c"),
        ("ANY", "a"), ("ANY", "b"),
    ]
    assert len(kit) == 22 and canonical_kit({}) == (None,) * 22


def test_two_items_with_identical_stats_in_a_one_place_group_the_smaller_key_always_wins():
    prof = profile()
    for run in range(10):
        items = [make_item(k, {"HEAD"}, stats={"HP": 50}) for k in ("m", "b", "x", "a", "q")]
        random.Random(run).shuffle(items)
        assert keys_in(solve_canonical(build(prof, items)), "HEAD") == ["a"]


# ---- ties between different kits -------------------------------------------------------------------------------------


def test_seven_distinct_equal_value_multisets_give_the_same_kit_on_twenty_runs():
    prof = profile()
    keys = ["k3", "k7", "k1", "k5", "k2", "k6", "k4"]
    seen = set()
    for run in range(20):
        items = [make_item(k, {"HEAD"}, stats={"HP": 40}) for k in keys]
        random.Random(run).shuffle(items)
        seen.add(tuple(worn(solve_canonical(build(prof, items))).items()))
    assert seen == {(("HEAD", "k1"),)}


def test_a_tie_between_different_two_item_sets_resolves_to_the_lower_ranked_one():
    prof = profile()
    for run in range(10):
        items = [make_item(k, {"HEAD"}, stats={"HP": 20}) for k in ("h2", "h1")]
        items += [make_item(k, {"NECK"}, stats={"HP": 20}) for k in ("n2", "n1")]
        random.Random(run).shuffle(items)
        assert worn(solve_canonical(build(prof, items))) == {"HEAD": "h1", "NECK": "n1"}
    # Lore items in a pair of places cannot repeat: the two lowest-ranked of the equal items
    lore = [make_item(k, {"EAR"}, stats={"HP": 15}, lore=True) for k in ("e4", "e1", "e3", "e2")]
    assert keys_in(solve_canonical(build(prof, lore)), "EAR") == ["e1", "e2"]


def test_a_tie_that_involves_two_copies_of_one_non_lore_ring():
    prof = profile()
    ring = lambda key, lore=False: make_item(key, {"EAR"}, stats={"HP": 10}, lore=lore)  # noqa: E731
    # every pair is worth 20: the least total rank wins. A plain lowest ring is worn twice ({a, a}: 1 + 1) ...
    pool = [ring("a"), ring("b"), ring("c")]
    for order in (pool, pool[::-1]):
        assert keys_in(solve_canonical(build(prof, order)), "EAR") == ["a", "a"]
    # ... a Lore lowest ring cannot be: {a, b} costs 1 + 2, {b, b} costs 2 + 2 (a pair of copies of the plain b)
    pool = [ring("a", lore=True), ring("b"), ring("c")]
    for order in (pool, pool[::-1]):
        assert keys_in(solve_canonical(build(prof, order)), "EAR") == ["a", "b"]
    # two copies of the plain ring beat two different plain rings when the copied one ranks first
    assert keys_in(solve_canonical(build(prof, [ring("d"), ring("c")])), "EAR") == ["c", "c"]


def test_kits_of_equal_total_rank_still_give_one_of_them_and_the_same_one_every_run():
    # a (fire) and b (cold) for the head, c (fire) and d (cold) for the neck; resists stop at 1000 (T4: it was 200, and the items were a fifth of these), so only a fire piece
    # with a cold one is worth 1500: {a, d} and {b, c} are the best, and both cost 1 + 4 = 2 + 3 = 5. The rule alone
    # cannot choose between them; the answer is one of them and it is the same on every run.
    prof = profile(weights={"SV": 1})
    pool = [
        make_item("a", {"HEAD"}, sv={"FIRE": 750}), make_item("b", {"HEAD"}, sv={"COLD": 750}),
        make_item("c", {"NECK"}, sv={"FIRE": 750}), make_item("d", {"NECK"}, sv={"COLD": 750}),
    ]
    seen = set()
    for run in range(10):
        order = list(pool)
        random.Random(run).shuffle(order)
        solution = solve_canonical(build(prof, order))
        assert solution.F == 1500.0
        seen.add(tuple(sorted(worn(solution).items())))
    assert len(seen) == 1
    assert next(iter(seen)) in {(("HEAD", "a"), ("NECK", "d")), (("HEAD", "b"), ("NECK", "c"))}


# ---- the last stage: kits of the same value and the same total rank ------------------------------------------------------------------
#
# The order of the kits that the last stage settles (the head of solver/solve.py and of engine/solve.js say the same): among the kits of the exact value of the best and the
# least total rank, the one whose canonical kit is first, place by place in the order of the 22 places, an item before an empty place and the lower (key, tier) before the higher;
# when every place is alike, the chosen buffs, by their ids, the lower list first.


def tied_pool(names):
    """Fire and cold pieces for the head and the neck, each worth 750 of one resist, with a cap of 1000 a school: only a fire piece with a cold one reaches 1500, so with the names
    of ``names`` (head fire, head cold, neck fire, neck cold) the two best kits are {head fire, neck cold} and {head cold, neck fire}."""
    head_fire, head_cold, neck_fire, neck_cold = names
    return [
        make_item(head_fire, {"HEAD"}, sv={"FIRE": 750}), make_item(head_cold, {"HEAD"}, sv={"COLD": 750}),
        make_item(neck_fire, {"NECK"}, sv={"FIRE": 750}), make_item(neck_cold, {"NECK"}, sv={"COLD": 750}),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("names", "first"),
    [
        (("b", "a", "d", "c"), {"HEAD": "a", "NECK": "d"}),  # {b, c} and {a, d} cost 2 + 3 = 1 + 4: the head comes first, and a is before b
        (("c", "a", "d", "b"), {"HEAD": "a", "NECK": "d"}),  # {c, b} and {a, d}: 3 + 2 = 1 + 4
        (("d", "b", "c", "a"), {"HEAD": "b", "NECK": "c"}),  # {d, a} and {b, c}: 4 + 1 = 2 + 3
        (("a", "b", "c", "d"), {"HEAD": "a", "NECK": "d"}),  # {a, d} and {b, c}: 1 + 4 = 2 + 3
    ],
)
def test_kits_of_the_same_value_and_total_rank_come_out_as_the_first_in_the_order_of_the_kits(names, first):
    prof = profile(weights={"SV": 1})
    pool = tied_pool(names)
    for run in range(12):
        order = list(pool)
        random.Random(run).shuffle(order)
        result = solve_canonical(build(prof, order))
        assert result.F == 1500.0 and result.canonical and result.tie_stage == "applied"
        assert worn(result) == first, (names, run)


def test_equal_buff_subsets_of_the_same_total_rank_come_out_as_the_lower_list_of_ids():
    prof = profile()
    # four buffs worth 15 each; the pairs {1, 2}, {1, 3}, {4, 2} and {4, 3} are refused, so the best are {1, 4} and {2, 3}: 1 + 4 = 2 + 3 in rank
    pairs = make_buffset(
        optional=[make_buff(1, HP=15), make_buff(2, HP=15), make_buff(3, HP=15), make_buff(4, HP=15)],
        conflicts=[(1, 2), (1, 3), (4, 2), (4, 3)], cardinality=2,
    )
    assert solve(build(prof, [], buffset=pairs)).F == 3800.0  # (the naked 3770 and two buffs of 15)
    assert solve_canonical(build(prof, [], buffset=pairs)).buffs == (1, 4)
    renamed = make_buffset(
        optional=[make_buff(5, HP=15), make_buff(6, HP=15), make_buff(7, HP=15), make_buff(8, HP=15)],
        conflicts=[(5, 6), (5, 7), (8, 6), (8, 7)], cardinality=2,
    )  # the same with other ids: {5, 8} before {6, 7}
    assert solve_canonical(build(prof, [], buffset=renamed)).buffs == (5, 8)


def test_the_order_of_the_kits_is_total_on_random_instances_with_twins():
    rng = random.Random(33)
    checked = tied = 0
    for _ in range(160):
        inst = H.random_instance(rng)
        extra = [
            make_item(f"{item.key}-twin", set(item.slots), stats=dict(item.stats), sv=dict(item.sv), haste=item.haste,
                      weight10=item.weight10, lore=item.lore, weapon=item.weapon, shield=item.is_shield)
            for item in rng.sample(inst.items, min(3, len(inst.items)))
        ]
        inst.items = inst.items + extra
        if H.option_product(inst.items, inst.setup, inst.any_rule) > 4 * H.KIT_LIMIT:
            continue
        milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, BuildOptions(**inst.options_kwargs()))
        want = expected_first_in_order(inst, milp)
        if want is None:
            continue
        solution = solve_canonical(milp)
        assert solution.canonical, inst.label
        assert (solution.kit, solution.buffs) == want[:2], inst.label
        checked += 1
        tied += want[2] > 1
    assert checked >= 40 and tied >= 3


def expected_first_in_order(inst, milp):
    """The canonical answer worked out by brute force with the whole order: among the (kit, buff set) pairs within the tolerance of the best value, the least total rank, and of
    those the first in the order of the kits. ``(kit, buffs, how many tied on the rank)``; None for an instance with a kit in the band where the tolerance decides."""
    space = H.Space(inst)
    grid = [space.values(chosen) for chosen in space.buff_sets]
    top = max(float(g.max()) for g in grid)
    scale = 1e-7 * max(1.0, abs(top))
    floor = top - 0.5 * scale
    if any(((g >= top - scale) & (g < floor)).any() for g in grid):
        return None
    rank = {(item.key, item.tier): n + 1 for n, item in enumerate(sorted(milp.items, key=lambda i: (i.key, i.tier)))}
    optional = sorted(milp.buffset.optional, key=lambda b: b.id) if milp.buffset else []
    buff_rank = {b.id: len(milp.items) + 1 + n for n, b in enumerate(optional)}
    candidates = []
    for chosen, values in zip(space.buff_sets, grid):
        for ki in (values >= floor).nonzero()[0]:
            groups = space.groups_of(tuple(space.kits[ki]))
            total = sum(rank[(i.key, i.tier)] for placed in groups.values() for i in placed) + sum(buff_rank[b] for b in chosen)
            kit = canonical_kit(groups)
            places = tuple((0, item.key, item.tier) if item is not None else (1, "", 0) for item in kit)
            candidates.append((total, places, tuple(chosen), kit))
    best = min(c[0] for c in candidates)
    tied = sorted((c for c in candidates if c[0] == best), key=lambda c: (c[1], c[2]))
    return tied[0][3], tied[0][2], len(tied)


def test_a_last_stage_that_does_not_finish_says_so_and_keeps_the_best_kit_it_has():
    prof = profile(weights={"SV": 1})
    milp = build(prof, tied_pool(("b", "a", "d", "c")))
    original, calls = solve_module.run_arrays, []

    def second_call_runs_out(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs) if len(calls) == 1 else RawResult("time_limit", None, None, None, 0, None)

    solve_module.run_arrays = second_call_runs_out
    try:
        result = solve_canonical(milp, time_limit=30.0)
    finally:
        solve_module.run_arrays = original
    assert len(calls) == 2 and result.tie_stage == "applied" and not result.canonical and result.F == 1500.0


def test_a_tie_of_more_kits_than_the_last_stage_separates_is_not_called_canonical(monkeypatch):
    prof = profile(weights={"SV": 1})
    milp = build(prof, tied_pool(("b", "a", "d", "c")))
    monkeypatch.setattr(solve_module, "MAX_TIED_KITS", 1)
    result = solve_canonical(milp)
    assert result.tie_stage == "applied" and not result.canonical and result.F == 1500.0
    monkeypatch.setattr(solve_module, "MAX_TIED_KITS", 2)
    assert solve_canonical(milp).canonical


def test_the_canonical_solution_is_flagged_and_a_failed_tie_stage_falls_back_to_the_proven_answer():
    prof = profile()
    items = [make_item(k, {"HEAD"}, stats={"HP": 50}) for k in ("b", "a")]
    milp = build(prof, items)
    plain, canonical = solve(milp), solve_canonical(milp)
    assert not plain.canonical and canonical.canonical and canonical.gap == 0.0 and canonical.nodes >= plain.nodes >= 0
    original = solve_module.run_arrays
    seen = {}

    def fails(*args, **kwargs):
        seen["warm"] = kwargs["warm_start"]
        return RawResult("time_limit", None, None, None, 0, None)

    solve_module.run_arrays = fails
    try:
        fallback = solve_canonical(milp, time_limit=5.0)
    finally:
        solve_module.run_arrays = original
    assert not fallback.canonical and fallback.status == "optimal" and fallback.F == plain.F
    assert seen["warm"] is not None and seen["warm"].shape[0] == milp.num_cols  # offered as a first incumbent
    # a first solve that did not end optimal is returned as it is, without a second stage
    assert solve_canonical(milp, time_limit=0.0).status == "time_limit"


# ---- the tie stage never gives up value ------------------------------------------------------------------------------


def kit_value(prof, groups, setup="stick"):
    """The exact value of the kit of ``{group: [items]}``."""
    return evaluate(prof, H.kit_from_groups(groups), setup=setup, haste_assumed=0).F


def test_a_lower_ranked_kit_inside_the_tie_band_that_is_worth_a_little_less_is_not_taken():
    # CHA is worth 0.0002 a point, so the circlet with CHA 2 beats the one with CHA 1 by 0.0002, and the band of the
    # tie stage (1e-7 of a value of about 3,800) is 0.00038: the stage used to take the lower-ranked, worse circlet.
    prof = profile(weights={"HP": 1, "CHA": 0.0002})
    a, b = make_item("a-circlet", {"HEAD"}, stats={"CHA": 1}), make_item("b-circlet", {"HEAD"}, stats={"CHA": 2})
    milp = build(prof, [a, b])
    first = solve(milp)
    assert keys_in(first, "HEAD") == ["b-circlet"]
    loss = first.breakdown.F - kit_value(prof, {"HEAD": [a]})
    assert 0 < loss < solve_module.TIE_TOLERANCE * first.F  # the premise: the worse kit is inside the band
    result = solve_canonical(milp)
    assert keys_in(result, "HEAD") == ["b-circlet"] and result.breakdown.F == first.breakdown.F
    assert result.tie_stage == "kept-first" and not result.canonical and result.status == "optimal"


@pytest.mark.parametrize(("shift", "taken"), [(F(1), True), (F(0), True), (F(-1), False)])
def test_the_second_stage_kit_is_taken_unless_it_is_worth_less_than_the_first(monkeypatch, shift, taken):
    """F4: one rule in Python and in the browser (solve.js ``secondIsTaken``): the tie stage's kit is applied when it is exactly as good or better, and the first answer is kept when it is worse.
    A better second kit can only come from a first stage that stopped inside its gap, so the case is made by handing the second stage's solution a value of its own."""
    prof = profile(weights={"HP": 1, "END": 1})
    milp = build(prof, [make_item("h1", {"HEAD"}, stats={"STA": 10}), make_item("h2", {"HEAD"}, stats={"STA": 30})])
    real = solve_module._solution
    seen = []

    def stage(m, raw):
        solution = real(m, raw)
        seen.append(solution)
        if len(seen) == 2:
            return dataclasses.replace(solution, breakdown=SimpleNamespace(F=seen[0].breakdown.F + shift))
        return solution

    monkeypatch.setattr(solve_module, "_solution", stage)
    result = solve_canonical(milp)
    assert len(seen) == 2
    assert (result.tie_stage, result.canonical) == (("applied", True) if taken else ("kept-first", False))
    assert result.breakdown.F == seen[0].breakdown.F + (shift if taken else 0)


def test_the_rule_of_the_second_stage_is_a_function_of_the_two_exact_values():
    assert solve_module.second_is_taken(F(5), F(5)) and solve_module.second_is_taken(F(5), F(6)) and not solve_module.second_is_taken(F(5), F(4))


def test_large_and_small_weights_the_canonical_answer_keeps_the_small_value_it_would_have_traded_for_rank():
    # HP weighs 1000 and MANA 0.001, so the band (1e-7 of a value in the millions) is wider than the 0.1 that +100 MANA
    # is worth. a (+3000 HP, rank 6) and b (+3000 HP, rank 2) compete for the main hand, and d (+100 MANA, rank 3) is a
    # held item: b is a two-hander, which leaves the off hand empty, so {b, d} is not a kit. {a, d} is the only best
    # kit; {b} alone costs less rank and is 0.1 short of it.
    prof = profile(weights={"HP": 1000, "MANA": 0.001})
    one = WeaponVec("1H Slashing", 10, 30, None, False)
    two = WeaponVec("2H Slashing", 20, 60, None, True)
    a = make_item("k6-a", {"PRIMARY"}, stats={"HP": 3000}, weapon=one)
    b = make_item("k2-b", {"PRIMARY"}, stats={"HP": 3000}, weapon=two)
    d = make_item("k3-d", {"SECONDARY"}, stats={"MANA": 100})
    pads = [make_item(key, {"FACE"}) for key in ("k1-pad", "k4-pad", "k5-pad")]  # they fill ranks 1, 4 and 5
    milp = build(prof, [a, b, d, *pads])
    ranks = {milp.names[col]: rank for col, rank in solve_module.tie_ranks(milp).items()}
    assert (ranks["n[PRIMARY|k6-a]"], ranks["n[PRIMARY|k2-b]"], ranks["n[SECONDARY|k3-d]"]) == (6, 2, 3)
    first = solve(milp)
    assert worn(first) == {"PRIMARY": "k6-a", "SECONDARY": "k3-d"}
    loss = first.breakdown.F - kit_value(prof, {"PRIMARY": [b]})
    assert loss == F("0.1") and loss < solve_module.TIE_TOLERANCE * first.F  # inside the band, and worth 0.1
    result = solve_canonical(milp)
    assert worn(result) == {"PRIMARY": "k6-a", "SECONDARY": "k3-d"}  # {a, d}, not the lower-ranked {b}
    assert result.breakdown.F == first.breakdown.F and result.tie_stage == "kept-first"


def test_a_tie_stage_kit_worse_than_the_first_stage_is_never_an_exactness_error():
    # the model may overstate a kit by up to 1e-6 relative without being refused. Here it overstates q by 0.05 (5e-7 of
    # a value near 100,000); p is the best by a hair, q is cheaper in rank and inside the 0.01 band, and q is truly worth
    # 0.05 less than p, which is more than the band: the stage used to raise "left the tolerance".
    prof = profile(weights={"HP": 0.05, "CHA": 1000})
    p = make_item("z-p", {"HEAD"}, stats={"HP": 201})  # rank 2
    q = make_item("a-q", {"HEAD"}, stats={"HP": 200})  # rank 1
    milp = build(prof, [p, q])
    milp.c[milp.index[("HEAD", "a-q")]] += 0.05 - 1e-6
    assert keys_in(solve(milp), "HEAD") == ["z-p"]
    loss = kit_value(prof, {"HEAD": [p]}) - kit_value(prof, {"HEAD": [q]})
    assert loss == F("0.05") and loss > 2 * solve_module.TIE_TOLERANCE * 100_000
    result = solve_canonical(milp)
    assert keys_in(result, "HEAD") == ["z-p"] and result.tie_stage == "kept-first" and not result.canonical


def test_the_tie_stage_is_recorded_on_the_solution():
    items = [make_item(k, {"HEAD"}, stats={"HP": 50}) for k in ("b", "a")]
    milp = build(profile(), items)
    assert solve(milp).tie_stage is None  # no tie stage was asked for
    result = solve_canonical(milp)
    assert result.tie_stage == "applied" and result.canonical and keys_in(result, "HEAD") == ["a"]
    # a first stage that did not end optimal has nothing to break ties between
    limited = solve_canonical(milp, time_limit=0.0)
    assert limited.status == "time_limit" and limited.tie_stage is None and not limited.canonical


def test_a_tie_stage_that_does_not_finish_keeps_the_first_stage_kit_and_says_so():
    milp = build(profile(), [make_item(k, {"HEAD"}, stats={"HP": 50}) for k in ("b", "a")])
    plain = solve(milp)
    original = solve_module.run_arrays
    solve_module.run_arrays = lambda *args, **kwargs: RawResult("time_limit", None, None, None, 0, None)
    try:
        fallback = solve_canonical(milp, time_limit=5.0)
    finally:
        solve_module.run_arrays = original
    assert fallback.tie_stage == "kept-first" and not fallback.canonical and fallback.F == plain.F


def test_the_tie_stage_is_given_the_time_limit_too():
    milp = build(profile(), [make_item("h", {"HEAD"}, stats={"HP": 5})])
    original, limits = solve_module.run_arrays, []

    def spy(*args, **kwargs):
        limits.append(kwargs["time_limit"])
        return original(*args, **kwargs)

    solve_module.run_arrays = spy
    try:
        solve_canonical(milp, time_limit=30.0)
    finally:
        solve_module.run_arrays = original
    assert limits == [30.0, 30.0]  # (the tie stage, and the last stage that proves nothing more ties: each solve has the limit)


def test_a_useless_item_is_never_worn_by_the_canonical_stage():
    prof = profile()
    items = [make_item("aaa", {"HEAD"}), make_item("bbb", {"HEAD"}, stats={"HP": 1})]  # the first has no effect at all
    assert keys_in(solve_canonical(build(prof, items)), "HEAD") == ["bbb"]
    assert keys_in(solve_canonical(build(prof, [make_item("aaa", {"HEAD"})])), "HEAD") == [None]


def test_two_equal_value_buff_subsets_resolve_to_the_lower_ranked_one():
    prof = profile()
    # a single buff worth 20 against two worth 10 each (it conflicts with both; at most two active): ranks 1 and 2 + 3
    pair_rival = make_buffset(
        optional=[make_buff(1, HP=20), make_buff(2, HP=10), make_buff(3, HP=10)], conflicts=[(1, 2), (1, 3)],
        cardinality=2,
    )
    assert solve_canonical(build(prof, [], buffset=pair_rival)).buffs == (1,)
    # the same with the single buff last (rank 4, against 1 + 2): buff 3 is worth nothing and is never on
    single_last = make_buffset(
        optional=[make_buff(1, HP=10), make_buff(2, HP=10), make_buff(3, WIS=1), make_buff(4, HP=20)],
        conflicts=[(1, 4), (2, 4)], cardinality=2)
    assert solve_canonical(build(prof, [], buffset=single_last)).buffs == (1, 2)
    flat = make_buffset(optional=[make_buff(7, HP=10), make_buff(4, HP=10), make_buff(9, HP=10)], cardinality=1)
    assert solve_canonical(build(prof, [], buffset=flat)).buffs == (4,)
    # items and buffs are chosen together: the item is worn and the lowest-ranked buff is on
    mixed = solve_canonical(build(prof, [make_item("x", {"HEAD"}, stats={"HP": 10})], buffset=flat))
    assert keys_in(mixed, "HEAD") == ["x"] and mixed.buffs == (4,)
    # a buff worth nothing is never active in the canonical answer
    idle = make_buffset(optional=[make_buff(1, WIS=5), make_buff(2, HP=3)])
    assert solve_canonical(build(prof, [], buffset=idle)).buffs == (2,)


def test_the_canonical_stage_keeps_the_value_within_its_tolerance_and_reports_the_evaluated_kit():
    rng = random.Random(14)
    for _ in range(30):
        inst = H.random_instance(rng)
        milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, BuildOptions(**inst.options_kwargs()))
        first, canonical = solve(milp), solve_canonical(milp)
        assert first.status == canonical.status == "optimal"
        assert canonical.F >= first.F - 1e-7 * max(1.0, abs(first.F))
        exact = evaluate(
            inst.profile, list(canonical.kit), H.eval_totals(inst.buffset, canonical.buffs) if inst.buffset else None,
            setup=inst.setup, haste_assumed=inst.haste_assumed,
        )
        assert canonical.F == float(exact.F)


def expected_canonical(inst, milp):
    """The canonical answer worked out by brute force: among the (kit, buff set) pairs within the tolerance of the
    best value, the one with the least total rank; None when two share that least total."""
    space = H.Space(inst)
    grid = [space.values(chosen) for chosen in space.buff_sets]
    top = max(float(g.max()) for g in grid)
    scale = 1e-7 * max(1.0, abs(top))
    floor = top - 0.5 * scale  # well inside the solver's tolerance, away from its edge
    if any(((g >= top - scale) & (g < floor)).any() for g in grid):
        return None  # a kit in the band where the tolerance decides: leave the instance out
    rank = {(item.key, item.tier): n + 1 for n, item in enumerate(sorted(milp.items, key=lambda i: (i.key, i.tier)))}
    optional = sorted(milp.buffset.optional, key=lambda b: b.id) if milp.buffset else []
    buff_rank = {b.id: len(milp.items) + 1 + n for n, b in enumerate(optional)}
    best, tied = None, 0
    for chosen, values in zip(space.buff_sets, grid):
        for ki in (values >= floor).nonzero()[0]:
            groups = space.groups_of(tuple(space.kits[ki]))
            total = sum(rank[(i.key, i.tier)] for placed in groups.values() for i in placed)
            total += sum(buff_rank[b] for b in chosen)
            if best is None or total < best[0]:
                best, tied = (total, groups, tuple(chosen)), 1
            elif total == best[0]:
                tied += 1
    if tied != 1:
        return None
    return {g: sorted(i.key for i in placed) for g, placed in best[1].items() if placed}, best[2]


def test_the_canonical_answer_is_the_least_total_rank_among_the_equal_value_kits_found_by_brute_force():
    rng = random.Random(21)
    checked = 0
    for _ in range(120):
        inst = H.random_instance(rng)
        extra = [
            make_item(f"{item.key}-twin", set(item.slots), stats=dict(item.stats), sv=dict(item.sv), haste=item.haste,
                      weight10=item.weight10, lore=item.lore, weapon=item.weapon, shield=item.is_shield)
            for item in rng.sample(inst.items, min(3, len(inst.items)))
        ]  # identical twins make ties
        inst.items = inst.items + extra
        if H.option_product(inst.items, inst.setup, inst.any_rule) > 4 * H.KIT_LIMIT:
            continue
        milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, BuildOptions(**inst.options_kwargs()))
        want = expected_canonical(inst, milp)
        if want is None:
            continue
        solution = solve_canonical(milp)
        got = {}
        for item, place in zip(solution.kit, SLOT_INSTANCES):
            if item is not None:
                got.setdefault(place, []).append(item.key)
        assert ({g: sorted(keys) for g, keys in got.items()}, solution.buffs) == want, inst.label
        checked += 1
    assert checked >= 40


@pytest.mark.parametrize("seed", range(40))
def test_the_canonical_solve_matches_the_brute_force_value(seed):
    inst = H.random_instance(random.Random(8000 + seed))
    milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, BuildOptions(**inst.options_kwargs()))
    solution = solve_canonical(milp)
    best, _, _ = H.Space(inst).best()
    assert solution.status == "optimal"
    assert abs(Fraction(solution.F) - best) <= Fraction(1, 10**7) * max(1, abs(best))


def test_ranks_put_items_before_buffs_and_start_above_zero():
    from trioforge.solver.solve import tie_ranks

    prof = profile()
    buffset = make_buffset(optional=[make_buff(8, HP=1), make_buff(3, HP=1)])
    milp = build(prof, [make_item("b", {"HEAD", "NECK"}), make_item("a", {"HEAD"})], buffset=buffset)
    ranks = tie_ranks(milp)
    by_name = {milp.names[col]: value for col, value in ranks.items()}
    assert by_name["n[HEAD|a]"] == 1 and by_name["n[HEAD|b]"] == by_name["n[NECK|b]"] == 2
    assert by_name["buff[3]"] == 3 and by_name["buff[8]"] == 4


# ---- real data ---------------------------------------------------------------------------------------------------------


@H.slow
def test_a_time_limited_solve_on_the_real_pool_of_a_barbarian_trio_is_a_lower_bound_of_the_optimum():
    trio = ("BER", "MNK", "WAR")
    pool = H.catalog_pool(trio, 4)
    prof = real_profile("BAR", trio, 50, "tank", None, None, H.TABLES)
    milp = build_milp(prof, pool, "dw")
    limited = None
    for limit in TINY_LIMITS:
        found = solve(milp, time_limit=limit)  # the first incumbent of this pool is worth far less than its kit
        if found.kit is not None:
            limited = found
            break
    assert limited is not None and limited.status == "time_limit"
    exact = exact_of(limited, milp)
    assert limited.F == float(exact.F) and limited.model_F < limited.F
    assert_a_legal_kit(limited, milp)
    best = solve(milp)
    assert best.status == "optimal" and abs(best.model_F - best.F) <= 1e-9 * best.F
    assert limited.F <= best.F + 1e-9 * best.F  # a kit of the pool cannot beat the optimum


@H.slow
def test_the_one_hander_and_shield_kit_of_a_caster_trio_wears_a_real_shield_never_a_held_item():
    # a focus crystal sits in the off hand and carries armor class: it used to be taken for a shield, and the kit gained
    # the shield bonus to the softcap from it
    trio = ("CLR", "WIZ", "ENC")
    pool = H.catalog_pool(trio, 10)
    typed = {raw["key"] for raw in H.catalog_items() if (raw["item_type"] or "").lower() == "shield"}
    held = {raw["key"] for raw in H.catalog_items() if set(raw["categories"]) & {"Focus Items", "Bard Instrument"}}
    assert held and typed
    prof = real_profile("ERU", trio, 50, "caster", None, None, H.TABLES, items=pool)
    assert "1h-shield" in prof.setups  # a shield in the pool admits one of the three classes
    solution = solve(build_milp(prof, pool, "1h-shield"))
    off_hand = solution.kit[SLOT_INSTANCES.index("SECONDARY")]
    assert solution.status == "optimal"
    assert off_hand is None or (off_hand.is_shield and off_hand.key in typed and off_hand.key not in held)
    assert solution.breakdown.totals["sheet"]["shield_ac"] == (off_hand.stats.get("AC", 0) if off_hand else 0)
