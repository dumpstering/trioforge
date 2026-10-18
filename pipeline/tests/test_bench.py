"""Tests for the Phase 2 benchmark: ``trioforge.bench``.

The benchmark measures the real formulation (profile, pruning, build, solve and the canonical second stage) on a stratified
sample of scenarios, gates the presolve option against presolve off, exports models for the browser timing proxy and
extrapolates the CPU time of the whole grid of scenarios to decide the precompute scope. The parts that are plain
arithmetic are tested against numbers worked out by hand here; the parts that run the solver are tested on a small
invented catalog (the real catalog is not in the repository, so its test is skipped without it).

The checks:

* the statistics (percentile, summary) and the quantile picks used for the model export;
* the strata of the trios, the grid they make, and the samples drawn from it (the coverage sample and the uniform one);
* the extrapolation: the interpolation between measured tiers, the post-stratified means, the cuts and the scope rule;
* the presolve comparison and the options hook of the solver layer, the MPS export and the report writer;
* a smoke run of two scenarios (in under a minute) and of the whole command line on the invented catalog.

Every item here is invented; the races, classes and trios are public game terms.
"""

import itertools
import json
import random
import re
import shutil
import time
from collections import Counter
from functools import cache

import pytest

from trioforge import bench
from trioforge.bench import (
    BENCH_RACES,
    GRID_CELLS,
    Inputs,
    Scenario,
    assert_public,
    compare_solutions,
    coverage_sample,
    decide_scope,
    extrapolate,
    grid_shapes,
    interpolate_tiers,
    percentile,
    pick_trios,
    quantile_picks,
    random_sample,
    render_markdown,
    role_set_type,
    stratum_of,
    summarize,
)
from trioforge.classes import CLASS_CODES
from trioforge.model import weapons as wp
from trioforge.model.roles import roles_for
from trioforge.model.tables import load
from trioforge.solver import _highs
from trioforge.solver.model import BINARY_KINDS
from trioforge.solver.solve import solve

TABLES = load()
RULES = TABLES.rules
ALL_TRIOS = list(itertools.combinations(CLASS_CODES, 3))


# ---- statistics -----------------------------------------------------------------------------------------------------


def test_percentile_interpolates_between_the_two_nearest_values():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([4, 1, 3, 2], 50) == 2.5  # the order of the input does not matter
    assert percentile(list(range(1, 101)), 95) == pytest.approx(95.05)
    assert percentile([7.0], 95) == 7.0
    assert percentile([3, 9], 0) == 3 and percentile([3, 9], 100) == 9
    assert percentile([0, 10], 25) == 2.5
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1, 2], 101)


def test_summarize_gives_count_mean_median_p95_max_and_sum():
    s = summarize([1, 2, 3, 4, 10])
    assert s == {"n": 5, "mean": 4.0, "p50": 3.0, "p95": pytest.approx(8.8), "max": 10, "sum": 20}
    assert summarize([]) == {"n": 0}


def test_quantile_picks_take_evenly_spaced_quantile_midpoints():
    values = [float(v) for v in random.Random(3).sample(range(1000), 100)]
    picks = quantile_picks(values, 4)  # the 12.5, 37.5, 62.5 and 87.5 percent points of the sorted values
    ordered = sorted(range(100), key=lambda i: values[i])
    assert [values[i] for i in picks] == [values[ordered[k]] for k in (12, 37, 62, 87)]
    assert len(set(quantile_picks(values, 20))) == 20
    assert sorted(quantile_picks([5.0, 1.0, 3.0], 10)) == [0, 1, 2]  # fewer values than picks: all of them
    assert quantile_picks([], 3) == []


# ---- strata and the grid --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "trio, expected",
    [
        (("WIZ", "MAG", "ENC"), "caster"),
        (("BER", "ROG", "MNK"), "melee"),
        (("PAL", "MNK", "BER"), "tank+melee"),
        (("WAR", "ROG", "BER"), "tank+melee"),
        (("CLR", "ROG", "BRD"), "melee+caster"),
        (("SHD", "CLR", "SHM"), "tank+melee+caster"),
    ],
)
def test_the_role_set_type_names_the_templates_a_trio_can_play(trio, expected):
    assert role_set_type(trio) == expected


def test_every_trio_has_one_of_five_role_set_types_matching_its_roles():
    types = Counter(role_set_type(t) for t in ALL_TRIOS)
    assert types == {
        "caster": 35, "melee": 20, "tank+melee": 64, "melee+caster": 231, "tank+melee+caster": 210,
    }  # fmt: skip
    for trio in ALL_TRIOS:
        templates = role_set_type(trio).split("+")
        assert roles_for(trio) == ["balanced", *(templates if len(templates) > 1 else [])]


def test_the_stratum_adds_the_monk_and_the_three_pools_that_mix_wis_and_int():
    assert stratum_of(("PAL", "MNK", "BER"), TABLES) == "tank+melee|monk|std"
    assert stratum_of(("CLR", "WIZ", "ENC"), TABLES) == "caster|plain|sel"
    assert stratum_of(("SHD", "CLR", "SHM"), TABLES) == "tank+melee+caster|plain|sel"
    assert stratum_of(("WIZ", "MAG", "ENC"), TABLES) == "caster|plain|std"
    assert stratum_of(("MNK", "CLR", "WIZ"), TABLES) == "melee+caster|monk|std"  # two pools: no selection
    assert sum(stratum_of(t, TABLES).endswith("|sel") for t in ALL_TRIOS) == 180  # the 180 trios with three pools that mix WIS and INT


def test_the_grid_counts_every_race_trio_role_and_setup_once():
    shapes = grid_shapes(TABLES)
    expected = 0
    for trio in ALL_TRIOS:
        for role in roles_for(trio):
            expected += len(wp.setups_for(trio, role, TABLES, level=50))
    assert sum(shapes.values()) == 15 * expected
    assert grid_shapes(TABLES, races=3) == {k: v // 5 for k, v in shapes.items()}
    assert GRID_CELLS == 44  # 11 tiers x 2 evidence levels x 2 buff sets
    assert all(re.fullmatch(r"[a-z+]+\|(monk|plain)\|(sel|std)", key) for key in shapes)


# ---- the samples ----------------------------------------------------------------------------------------------------


def test_pick_trios_covers_the_types_monks_mixed_mana_and_all_casters():
    trios = pick_trios(TABLES)
    assert len(trios) == len(set(trios)) >= 40 and trios == sorted(trios)
    assert {role_set_type(t) for t in trios} == {"caster", "melee", "tank+melee", "melee+caster", "tank+melee+caster"}
    assert sum("MNK" in t for t in trios) >= 10
    assert sum(stratum_of(t, TABLES).endswith("|sel") for t in trios) >= 10
    assert sum(role_set_type(t) == "caster" for t in trios) >= 5
    assert {stratum_of(t, TABLES) for t in trios} == set(grid_shapes(TABLES))  # every cell of the grid is sampled


def test_pick_trios_is_deterministic_and_the_seed_changes_it():
    assert pick_trios(TABLES, seed=1) == pick_trios(TABLES, seed=1)
    assert pick_trios(TABLES, seed=1) != pick_trios(TABLES, seed=2)
    assert len(pick_trios(TABLES, n=80)) >= 80


def test_the_coverage_sample_has_every_role_setup_race_tier_and_buff_set():
    trios = [("PAL", "MNK", "BER"), ("WIZ", "MAG", "ENC")]
    sample = coverage_sample(TABLES, trios, races=("HUM", "OGR"), tiers=(0, 4), buffs=("own", "group"))
    per_trio = {
        trio: sum(len(wp.setups_for(trio, role, TABLES, level=50)) for role in roles_for(trio)) for trio in trios
    }
    assert len(sample) == sum(per_trio.values()) * 2 * 2 * 2 and len(set(sample)) == len(sample)
    assert {s.evidence for s in sample} == {"wiki"} and {s.race for s in sample} == {"HUM", "OGR"}
    pmb = [s for s in sample if s.trio == trios[0]]
    assert {(s.role, s.setup) for s in pmb} == {
        (role, setup) for role in roles_for(trios[0]) for setup in wp.setups_for(trios[0], role, TABLES, level=50)
    }
    assert BENCH_RACES == ("ERU", "HUM", "OGR")


def test_the_uniform_sample_is_deterministic_valid_and_covers_the_whole_grid():
    sample = random_sample(TABLES, 3000, seed=7)
    assert sample == random_sample(TABLES, 3000, seed=7) and sample != random_sample(TABLES, 3000, seed=8)
    assert {s.tier for s in sample} == set(range(11)) and len({s.race for s in sample}) == 15
    assert {s.evidence for s in sample} == {"wiki", "strict-proxy"} and {s.buffs for s in sample} == {"own", "group"}
    for s in sample[:300]:
        assert s.role in roles_for(s.trio) and s.setup in wp.setups_for(s.trio, s.role, TABLES, level=50)
    shapes = grid_shapes(TABLES)
    total = sum(shapes.values())
    share = Counter(stratum_of(s.trio, TABLES) for s in sample)
    for key, count in shapes.items():  # proportional to the grid, within sampling noise
        assert share[key] / len(sample) == pytest.approx(count / total, abs=0.03)


def test_a_scenario_has_a_readable_key_and_round_trips_through_a_dict():
    s = Scenario("OGR", ("PAL", "MNK", "BER"), "balanced", "2h", 4, "wiki", "group")
    assert s.key == "OGR PAL/MNK/BER balanced 2h +4 wiki group"
    assert Scenario.from_dict(s.to_dict()) == s


# ---- the extrapolation ------------------------------------------------------------------------------------------------


def test_interpolate_tiers_is_piecewise_linear_between_the_measured_tiers():
    got = interpolate_tiers({0: 1.0, 4: 3.0, 10: 9.0})
    assert [got[t] for t in range(11)] == [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    assert interpolate_tiers({4: 2.0}) == dict.fromkeys(range(11), 2.0)  # one measured tier: flat
    assert interpolate_tiers({4: 2.0, 10: 8.0})[0] == 2.0  # outside the measured range: the nearest value


def cells(per_trio):
    """{trio id: {(tier, buffs): (n, prep, solve, canon sums)}} from {trio id: {(tier, buffs): (prep, solve, canon)}}
    per scenario, with two scenarios in each cell."""
    return {
        trio: {key: (2, 2 * p, 2 * s, 2 * c) for key, (p, s, c) in cost.items()} for trio, cost in per_trio.items()
    }


def test_the_wiki_costs_are_post_stratified_by_the_shapes_of_the_grid_and_averaged_over_buff_sets():
    # stratum A has 3 of every 4 scenarios of the grid, stratum B one; A's trios cost 1 s of prep, B's 5 s
    per = {
        "a1": {(0, "own"): (1, 2, 4), (0, "group"): (1, 4, 8), (10, "own"): (1, 4, 8), (10, "group"): (1, 8, 16)},
        "a2": {(0, "own"): (1, 4, 8), (0, "group"): (1, 6, 12), (10, "own"): (1, 6, 12), (10, "group"): (1, 10, 20)},
        "b1": {(0, "own"): (5, 6, 10), (0, "group"): (5, 10, 14), (10, "own"): (5, 10, 14), (10, "group"): (5, 14, 22)},
    }
    strata = {"a1": "A|plain|std", "a2": "A|plain|std", "b1": "B|plain|std"}
    shapes = {"A|plain|std": 3, "B|plain|std": 1}
    got = bench.wiki_costs(cells(per), strata, shapes)
    assert set(got) == {"prep", "solve", "canon"} and set(got["prep"]) == set(range(11))
    # A, tier 0: solve (2+4)/2 = 3 own and (4+6)/2 = 5 group, so 4 on average; B: (6 + 10)/2 = 8; (3*4 + 1*8)/4 = 5
    assert got["solve"][0] == pytest.approx(5.0)
    # A, tier 10: own (4+6)/2 = 5, group (8+10)/2 = 9, mean 7; B: (10 + 14)/2 = 12; (3*7 + 12)/4 = 8.25
    assert got["solve"][10] == pytest.approx(8.25)
    assert got["solve"][5] == pytest.approx((5.0 + 8.25) / 2)  # linear between the measured tiers
    assert got["prep"][3] == pytest.approx((3 * 1 + 1 * 5) / 4)
    # canon, tier 0: A own (4+8)/2 = 6, group (8+12)/2 = 10, mean 8; B (10+14)/2 = 12; (3*8 + 12)/4 = 9
    assert got["canon"][0] == pytest.approx(9.0)


def test_a_stratum_with_no_sampled_trio_takes_the_mean_of_its_parent_stratum():
    per = {"a": {(4, "own"): (1, 2, 4), (4, "group"): (1, 4, 8)}, "b": {(4, "own"): (3, 6, 10), (4, "group"): (3, 8, 12)}}
    strata = {"a": "T|monk|std", "b": "T|monk|sel"}
    shapes = {"T|monk|std": 1, "T|monk|sel": 1, "T|monk|other": 2}  # the last cell has no sampled trio
    got = bench.wiki_costs(cells(per), strata, shapes)
    # the missing cell takes the mean of the sampled cells with the same type and Monk flag: (3 + 8)/2 = 5.5 of solve
    assert got["solve"][4] == pytest.approx((1 * 3 + 1 * 7 + 2 * 5) / 4)
    only = bench.wiki_costs(cells({"a": per["a"]}), {"a": "T|monk|std"}, {"T|monk|std": 1, "U|plain|std": 5})
    assert only["solve"][4] == pytest.approx(3.0)  # nothing similar sampled: the mean of everything sampled


def shapes_ten():
    return {"s|plain|std": 10}


def flat_costs(prep=1.0, solve_=2.0, canon=3.0):
    return {
        "prep": dict.fromkeys(range(11), prep), "solve": dict.fromkeys(range(11), solve_),
        "canon": dict.fromkeys(range(11), canon),
    }  # fmt: skip


def test_extrapolate_adds_prep_and_a_solve_stage_over_every_cell_of_the_grid():
    out = extrapolate(flat_costs(), {"prep": 1.0, "solve": 1.0, "canon": 1.0}, shapes_ten(), skip_strict=0.0)
    cells_ = 10 * 11 * 2  # shapes x tiers x buff sets, per evidence level
    assert out["scenarios"] == 10 * 44 and out["scale"] == pytest.approx(2_825_460 / 440)
    assert out["tiers"]["all"]["solve"]["none"] == pytest.approx(2 * cells_ * (1 + 2) / 3600)
    assert out["tiers"]["all"]["canon"]["none"] == pytest.approx(2 * cells_ * (1 + 3) / 3600)
    assert out["tiers"]["three"]["canon"]["none"] == pytest.approx(2 * (10 * 3 * 2) * (1 + 3) / 3600)


def test_the_wiki_first_cut_skips_the_share_of_strict_solves_that_the_wiki_kit_already_answers():
    ratio = {"prep": 0.5, "solve": 0.5, "canon": 0.5}  # a strict solve costs half a wiki one
    out = extrapolate(flat_costs(), ratio, shapes_ten(), skip_strict=0.75)
    wiki, strict = 220 * (1 + 3), 220 * 0.5 * (1 + 3)
    assert out["tiers"]["all"]["canon"]["none"] == pytest.approx((wiki + strict) / 3600)
    assert out["tiers"]["all"]["canon"]["wiki-first"] == pytest.approx((wiki + strict * 0.25) / 3600)


def test_the_presolve_cut_divides_only_the_solve_stage_and_only_when_it_is_a_gain():
    ratio = {"prep": 1.0, "solve": 1.0, "canon": 1.0}
    out = extrapolate(flat_costs(), ratio, shapes_ten(), skip_strict=0.0, presolve={"solve": 2.0, "canon": 1.5})
    assert out["tiers"]["all"]["solve"]["wiki-first+presolve"] == pytest.approx(2 * 220 * (1 + 2 / 2) / 3600)
    assert out["tiers"]["all"]["canon"]["wiki-first+presolve"] == pytest.approx(2 * 220 * (1 + 3 / 1.5) / 3600)
    slower = extrapolate(flat_costs(), ratio, shapes_ten(), skip_strict=0.0, presolve={"solve": 0.8, "canon": 0.5})
    assert slower["tiers"]["all"]["canon"]["wiki-first+presolve"] is None  # not a gain: not applied
    assert extrapolate(flat_costs(), ratio, shapes_ten())["tiers"]["all"]["canon"]["wiki-first+presolve"] is None


def test_extrapolate_reports_the_share_of_the_time_that_building_takes():
    out = extrapolate(flat_costs(prep=1.0, canon=3.0), {"prep": 1, "solve": 1, "canon": 1}, shapes_ten())
    assert out["prep_share"] == pytest.approx({"solve": 1 / 3, "canon": 1 / 4})


def test_different_costs_by_tier_change_the_three_tier_scope_and_not_the_per_tier_mean():
    costs = flat_costs()
    costs["canon"] = {t: float(t) for t in range(11)}  # tier t costs t seconds
    out = extrapolate(costs, {"prep": 1, "solve": 1, "canon": 1}, shapes_ten(), skip_strict=0.0)
    per_tier = 10 * 2 * 2  # shapes x buff sets x evidence levels
    assert out["tiers"]["all"]["canon"]["none"] == pytest.approx(per_tier * (55 + 11 * 1) / 3600)  # prep 1 s, canon t
    assert out["tiers"]["three"]["canon"]["none"] == pytest.approx(per_tier * ((0 + 4 + 10) + 3 * 1) / 3600)


def test_the_scope_rule_precomputes_every_tier_unless_the_grid_needs_more_than_the_budget():
    below = decide_scope(250.0, 70.0)
    assert below["scope"] == "all" and below["threshold"] == 300.0
    assert decide_scope(300.0, 80.0)["scope"] == "all"  # the rule is "more than"
    above = decide_scope(300.5, 80.0)
    assert above["scope"] == "0/4/10" and "0/4/10" in above["text"] and "300" in above["text"]
    assert "80" in above["text"] and "above the budget too" not in above["text"]
    both = decide_scope(1200.0, 340.0, basis="with the tie stage and the wiki-first cut")
    assert both["basis"] == "with the tie stage and the wiki-first cut" and "1200 CPU hours with the tie stage" in both["text"]
    assert "340, which is above the budget too" in both["text"]


def test_the_confidence_interval_brackets_the_estimate_and_collapses_without_variance():
    per = {
        f"t{i}": {(t, b): (1.0, 2.0 + i, 3.0 + 2 * i) for t in (0, 4, 10) for b in ("own", "group")} for i in range(6)
    }
    strata = {f"t{i}": ("A|plain|std" if i < 3 else "B|plain|std") for i in range(6)}
    shapes = {"A|plain|std": 5, "B|plain|std": 7}
    ratio = {"prep": 0.5, "solve": 0.5, "canon": 0.5}
    args = (cells(per), strata, shapes, ratio)
    point, low, high = bench.canonical_interval(*args, n_boot=200, seed=1)
    assert low <= point <= high and low < high
    assert bench.canonical_interval(*args, n_boot=200, seed=1) == (point, low, high)
    flat = {k: dict.fromkeys(v, (1.0, 2.0, 3.0)) for k, v in per.items()}
    p, lo, hi = bench.canonical_interval(cells(flat), strata, shapes, ratio, n_boot=50, seed=2)
    assert lo == pytest.approx(p) == pytest.approx(hi)


def rec(trio="WAR/MNK/ROG", tier=4, buffs="own", prep=0.6, solve=1.0, canon=2.0, wall=1.0, **extra):
    """A measured record with invented CPU seconds (``c_``) and wall seconds (``t_``, ``wall`` times as long);
    ``prep`` is split over profile, prune and build."""
    cpu = {"profile": prep / 6, "prune": prep / 3, "build": prep / 2, "solve": solve, "canon": canon}
    base = {"trio": trio.split("/"), "stratum": "tank+melee|monk|std", "tier": tier, "buffs": buffs, "error": None}
    for stage, seconds in cpu.items():
        base[f"c_{stage}"], base[f"t_{stage}"] = seconds, seconds * wall
    return {**base, **extra}


def test_aggregate_sums_the_prep_solve_and_canonical_seconds_by_trio_tier_and_buff_set():
    records = [
        rec(prep=0.6, solve=1.0, canon=2.0), rec(prep=0.4, solve=3.0, canon=4.0),
        rec(buffs="group", prep=1.0, solve=5.0, canon=6.0), rec("CLR/WIZ/ENC", tier=0, stratum="caster|plain|sel"),
        rec(error="ValueError: x"), {k: v for k, v in rec().items() if k != "c_canon"},  # both left out
    ]  # fmt: skip
    cells_, strata = bench.aggregate(records)
    assert set(cells_) == {"WAR/MNK/ROG", "CLR/WIZ/ENC"} and strata["CLR/WIZ/ENC"] == "caster|plain|sel"
    n, prep, solve_, canon = cells_["WAR/MNK/ROG"][(4, "own")]
    assert (n, prep, solve_, canon) == (2, pytest.approx(1.0), 4.0, 6.0)
    assert cells_["WAR/MNK/ROG"][(4, "group")] == (1, pytest.approx(1.0), 5.0, 6.0)


def test_paired_ratio_is_the_cost_of_the_strict_twins_over_the_wiki_ones():
    wiki = [rec(prep=1.0, solve=2.0, canon=4.0), rec(prep=3.0, solve=4.0, canon=8.0), rec(error="boom")]
    strict = [rec(prep=0.5, solve=1.0, canon=1.0), rec(prep=1.5, solve=2.0, canon=3.0), rec(prep=9, solve=9, canon=9)]
    got = bench.paired_ratio(wiki, strict)  # the third pair has an error and is left out
    assert got == {"prep": pytest.approx(0.5), "solve": pytest.approx(0.5), "canon": pytest.approx(1 / 3)}
    with pytest.raises(ValueError):
        bench.paired_ratio([rec(error="x")], [rec()])


def test_uniform_hours_is_half_the_grid_at_each_evidence_level_with_the_strict_half_cut():
    wiki = [rec(prep=1.0, canon=3.0), rec(prep=3.0, canon=5.0)]  # a scenario costs 4 or 8 seconds: mean 6
    strict = [rec(prep=1.0, canon=1.0), rec(prep=1.0, canon=1.0)]  # 2 seconds each
    spec = 3600
    assert bench.uniform_hours(wiki, strict, "canon", 0.0, spec_total=spec) == pytest.approx(spec / 2 * (6 + 2) / 3600)
    assert bench.uniform_hours(wiki, strict, "canon", 0.75, spec_total=spec) == pytest.approx(spec / 2 * (6 + 0.5) / 3600)
    assert bench.uniform_hours(wiki, strict, "solve", 0.0, spec_total=spec) == pytest.approx(
        spec / 2 * ((1 + 1 + 3 + 1) / 2 + 2) / 3600  # prep + solve of 1 second
    )


def test_calibration_is_how_much_slower_the_loaded_run_was_than_the_run_alone():
    loaded = [rec(prep=3.0, solve=2.0, canon=6.0, wall=3.0), rec(prep=1.0, solve=4.0, canon=2.0, wall=3.0), rec(error="x")]
    alone = [rec(prep=1.5, solve=1.0, canon=2.0), rec(prep=0.5, solve=2.0, canon=2.0), rec()]
    got = bench.calibration(loaded, alone)
    assert got["n"] == 2
    assert got["slowdown"] == {"prep": pytest.approx(2.0), "solve": pytest.approx(2.0), "canon": pytest.approx(2.0)}
    assert got["wall_slowdown"] == {"prep": pytest.approx(6.0), "solve": pytest.approx(6.0), "canon": pytest.approx(6.0)}
    assert bench.calibration(loaded[:1], alone[:1])["slowdown"]["canon"] == pytest.approx(3.0)
    with pytest.raises(ValueError):
        bench.calibration([rec(error="x")], [rec()])


def test_tier_seconds_are_the_mean_prep_solve_and_canonical_seconds_of_each_tier():
    records = [rec(tier=0, prep=1.0, solve=1.0, canon=2.0), rec(tier=0, prep=3.0, solve=3.0, canon=4.0),
               rec(tier=10, prep=0.2, solve=0.4, canon=0.6), rec(tier=10, error="x")]  # fmt: skip
    got = bench.tier_seconds(records)
    assert got == {"0": {"prep": 2.0, "solve": 2.0, "canon": 3.0, "n": 2},
                   "10": {"prep": pytest.approx(0.2), "solve": 0.4, "canon": 0.6, "n": 1}}  # fmt: skip


def test_an_error_text_names_the_exception_cuts_long_messages_and_hides_local_paths():
    text = bench._error_text(FileNotFoundError("cannot open C:\\Users\\<user>\\data\\x.json now"))  # <user>: a placeholder
    assert text == "FileNotFoundError: cannot open <path> now"
    assert "<path>" in bench._error_text(OSError("no such file /home/<user>/x/y"))
    assert len(bench._error_text(ValueError("x" * 1000))) == 200
    assert_public({"error": bench._error_text(PermissionError("denied: D:\\data\\secret.bin"))})


# ---- the presolve comparison and the solver hook -----------------------------------------------------------------------


def test_compare_solutions_classifies_a_pair_of_solves():
    assert compare_solutions("optimal", 100.0, "optimal", 100.0) == "ok"
    assert compare_solutions("optimal", 100.0, "optimal", 100.0 + 1e-10) == "ok"
    assert compare_solutions("optimal", 100.0, "optimal", 100.0 + 1e-3) == "mismatch"
    assert compare_solutions("optimal", 1e6, "optimal", 1e6 * (1 + 2e-9)) == "mismatch"  # relative, not absolute
    assert compare_solutions("optimal", 100.0, "time_limit", 90.0) == "guarded"  # re-solved with presolve off
    assert compare_solutions("optimal", 100.0, "infeasible", None) == "guarded"
    assert compare_solutions("time_limit", 100.0, "optimal", 100.0) == "unverified"
    assert compare_solutions("optimal", 100.0, "optimal", 100.0, rel=1e-2) == "ok"


def tiny_inputs():
    return Inputs.from_items(synthetic_items(), tables=TABLES)


def test_the_solver_layer_takes_option_overrides_for_one_call_only():
    inputs = tiny_inputs()
    ctx = bench.Context(inputs)
    scenario = Scenario("HUM", ("WAR", "CLR", "ENC"), "balanced", "dw", 4, "wiki", "own")
    prepared = ctx.prepare(scenario)
    before = dict(_highs.OPTIONS)
    off = solve(prepared.milp)
    on = solve(prepared.milp, highs_options={"presolve": "on"})
    assert off.status == on.status == "optimal" and abs(off.F - on.F) <= 1e-9 * abs(off.F)
    assert _highs.OPTIONS == before and before["presolve"] == "off"  # the production options are untouched
    seen = {}
    real = _highs.highspy.Highs

    class Spy(real):
        def setOptionValue(self, name, value):  # noqa: N802
            seen[name] = value
            return super().setOptionValue(name, value)

    _highs.highspy.Highs = Spy
    try:
        solve(prepared.milp, highs_options={"presolve": "on", "random_seed": 5})
    finally:
        _highs.highspy.Highs = real
    assert seen["presolve"] == "on" and seen["random_seed"] == 5 and seen["threads"] == 1


def test_a_model_written_as_mps_solves_to_the_same_value(tmp_path):
    import highspy

    ctx = bench.Context(tiny_inputs())
    prepared = ctx.prepare(Scenario("OGR", ("PAL", "MNK", "BER"), "balanced", "2h", 4, "wiki", "group"))
    path = tmp_path / "model.mps"
    _highs.write_mps(prepared.milp, path)
    assert path.stat().st_size > 1000
    reader = highspy.Highs()
    reader.setOptionValue("output_flag", False)
    reader.setOptionValue("mip_rel_gap", 0.0)
    reader.setOptionValue("threads", 1)  # HiGHS starts one scheduler per process: every instance must ask for the same
    reader.readModel(str(path))
    reader.run()
    assert reader.getModelStatus() == highspy.HighsModelStatus.kOptimal
    assert reader.getInfo().objective_function_value == pytest.approx(solve(prepared.milp).model_F, rel=1e-9)


def test_the_exported_models_and_their_manifest_solve_to_the_same_value_in_highs_js(tmp_path):
    node = shutil.which("node")
    if node is None or not (bench.REPO / "node_modules" / "highs").is_dir():
        pytest.skip("node or the highs package is not installed")
    ctx = bench.Context(tiny_inputs())
    sample = [
        Scenario("HUM", ("WAR", "MNK", "ROG"), "balanced", "dw", 4, "wiki", "own"),
        Scenario("ERU", ("CLR", "WIZ", "ENC"), "balanced", "stick", 0, "wiki", "group"),
        Scenario("OGR", ("PAL", "MNK", "BER"), "tank", "1h-shield", 10, "wiki", "group"),
    ]
    records = bench.run(sample, inputs=tiny_inputs(), workers=1, time_limit=60.0)
    manifest = bench.export_models(ctx, records, 3, tmp_path)
    assert len(manifest) == 3 and (tmp_path / "manifest.json").is_file()
    result = bench.run_highs_js(tmp_path, reps=1)
    assert not result.get("skipped"), result
    assert result["models"] == 3 and result["all_optimal"] and result["max_rel_objective_diff"] < 1e-9
    assert result["median_ms"] > 0 and result["p95_ms"] >= result["median_ms"]


def test_the_browser_proxy_is_reported_as_skipped_when_node_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(bench.shutil, "which", lambda name: None)
    assert bench.run_highs_js(tmp_path) == {"skipped": True, "reason": "node is not installed"}


# ---- reports ------------------------------------------------------------------------------------------------------


def test_assert_public_refuses_a_path_into_a_user_profile_anywhere_in_the_data():
    assert_public({"a": ["reports/bench-mps", "scripts/bench-highs.mjs", 3, None], "b": {"c": "a/b/c"}})
    for bad in ("C:\\Users\\<user>\\x", "c:/Users/<user>/x", "/Users/<user>/x", "/home/<user>/x", "D:\\data\\x.json"):
        with pytest.raises(ValueError, match="path"):
            assert_public({"deep": [{"x": bad}]})


def full_result(**changes):
    """A report document with invented numbers for every part the markdown writer reads."""
    seconds = summarize([0.5, 1.0, 1.5, 3.0])
    tie = summarize([1.0, 2.0, 3.0, 9.0])
    prep = summarize([0.3, 0.35, 0.4, 0.5])
    size = summarize([900, 1000, 1100, 1200])
    group = {"n": 4, "solve": {"mean": 1.5}, "canon": {"mean": 3.0, "p95": 8.0}, "prep_mean": 0.4, "cols_mean": 1000.0}
    kinds = BINARY_KINDS
    cut = {"none": 900.0, "wiki-first": 700.0, "wiki-first+presolve": None}
    result = {
        "date": "2026-10-14",
        "environment": {"python": "3.12", "highspy": "1.15.1", "highs_version": "1.15.1", "highs_githash": "04024d7",
                        "workers": 20, "threads": 24},
        "gate": {"n": 500, "n_mismatch": 0, "mismatches": [], "max_rel_diff": 0.0, "guarded": 0, "errors": 0,
                 "tolerance": 1e-9, "speedup": {"solve": 0.9, "canon": 0.4},
                 "canonical": {"n": 100, "mismatches": 0, "same_items": 100, "same_kit": 70}},
        "sample": {"trios": 60},
        "bench": {"n": 4, "solve": seconds, "canon": tie, "prep": prep, "prune": prep, "build": prep, "cols": size,
                  "wall_over_cpu": {"solve": 1.7, "canon": 1.8, "prep": 1.5},
                  "rows": size, "item_cols": size, "binaries_total": size, "optional_buffs": size, "nodes_solve": size,
                  "nodes_canon": size, "binaries": {k: summarize([1, 2]) for k in kinds},
                  "by": {part: {"x": group} for part in ("tier", "buffs", "monk", "mixed_mana", "type")}},
        "uniform": {"n": 30, "wiki": {"n": 30, "solve": seconds, "canon": tie, "prep": prep},
                    "cpu_h": {"canon_none": 880.0, "canon_wiki_first": 690.0, "solve_none": 500.0, "solve_wiki_first": 400.0}},
        "calibration": {"n": 60, "workers": 20, "slowdown": {"solve": 1.4, "canon": 1.5, "prep": 1.3},
                        "wall_slowdown": {"solve": 2.0, "canon": 2.0, "prep": 2.0}},
        "grid": {"scenarios": 2_739_000},
        "extrapolation": {
            "spec_tiers": {"all": {"canon": cut, "solve": {"none": 500.0, "wiki-first": 400.0, "wiki-first+presolve": None}},
                           "three": {"canon": {"none": 250.0, "wiki-first": 190.0, "wiki-first+presolve": None},
                                     "solve": {"none": 140.0, "wiki-first": 110.0, "wiki-first+presolve": None}}},
            "headline_canonical_wiki_first": {"cpu_h": 700.0, "low": 650.0, "high": 760.0},
        },
        "decision": {**decide_scope(700.0, 190.0), "wall_hours": {"80_vcpu": 8.75, "pc_workers": 35.0}},
        "highs_js": {"models": 20, "reps": 3, "median_ms": 900.0, "p95_ms": 4000.0, "max_ms": 4500.0, "total_median_ms": 920.0,
                     "phone_median_ms": 3600.0, "phone_p95_ms": 16000.0, "all_optimal": True, "max_rel_objective_diff": 1e-13,
                     "highs": {"version": "1.15.1"}},
    }  # fmt: skip
    result.update(changes)
    return result


def test_the_markdown_report_states_the_result_the_tables_and_the_decision():
    text = render_markdown(full_result())
    lines = text.splitlines()
    assert lines[0] == "# Phase 2 benchmark (2026-10-14)" and len(lines) < 150
    for heading in ("## Result", "## Presolve gate", "## Per-solve times", "## CPU hours", "## Browser timing proxy"):
        assert any(line.startswith(heading) for line in lines), heading
    assert "Tiers +0, +4 and +10 are precomputed" in text and "700" in text and "190" in text
    assert "stays off" in text and "0 mismatches" in text  # the gate passed, but presolve is slower
    assert "**over the budget.**" in text  # 3,600 ms and 16,000 ms on a phone against 1,000 and 5,000
    assert "| solve + tie stage |" in text and "| all 11 tiers | solve + tie stage (production) | 900 | 700 | n/a |" in text
    assert "took 0.67x the CPU time and 0.50x the wall time of the run with 20 workers" in text
    assert "Wall time on this shared machine was 1.80x the CPU time" in text and "(95 percent interval 650 to 760" in text
    assert "C:\\" not in text and "/Users/" not in text


def test_the_result_says_whether_the_first_solve_alone_would_fit_the_budget():
    result = full_result()
    assert "What decides it" not in render_markdown(result)  # the decision does not say which cuts it used
    result["decision"] = {**result["decision"], "cuts": "wiki-first"}
    assert "the first solve alone would need 400 CPU hours for all tiers under the same cuts, above the 300 hour budget" in (
        render_markdown(result)
    )
    result["extrapolation"]["spec_tiers"]["all"]["solve"]["wiki-first"] = 295.0
    assert "would need 295 CPU hours for all tiers under the same cuts, within the 300 hour budget" in render_markdown(result)


def test_the_markdown_report_says_so_when_the_scope_is_all_tiers_or_the_phone_is_in_budget():
    text = render_markdown(full_result(decision=decide_scope(250.0, 70.0), highs_js={**full_result()["highs_js"], "phone_median_ms": 800.0, "phone_p95_ms": 3000.0}))
    assert "All 11 tiers are precomputed" in text and "within the budget" in text and "over the budget" not in text


def test_the_notes_say_where_the_time_goes_and_how_much_of_it_the_selection_trios_take():
    summary = {"prep": {"mean": 0.2}, "solve": {"mean": 0.5}, "canon": {"mean": 1.3},
               "by": {"stratum": {"a|plain|sel": {"canon": {"mean": 3.0}}, "a|plain|std": {"canon": {"mean": 1.0}}}}}  # fmt: skip
    drivers = bench._driver_notes(summary, {"a|plain|sel": 30, "a|plain|std": 70})
    assert drivers[0] == (
        "Where the time goes (mean CPU seconds per production scenario, 1.50): preparing the model 0.20 (13%), the first "
        "solve 0.50 (33%), the tie stage 0.80 (53%)."
    )
    assert "are 30% of the grid and 56% of its time with the tie stage: 3.00 CPU seconds a scenario against 1.00." in drivers[1]
    assert len(bench._driver_notes(summary, {"other|plain|std": 5})) == 1  # no sampled stratum for this grid: only the first


def test_render_rewrites_the_notes_and_the_markdown_of_an_earlier_report(tmp_path):
    path = tmp_path / "earlier.json"
    document = full_result(notes=["stale note"], grid={"scenarios": 2_739_000, "by_stratum": {}})
    bench.write_reports(document, path)
    assert "stale note" in path.with_suffix(".md").read_text(encoding="utf-8")
    assert bench.main(["--render", str(path)]) == 0
    text = path.with_suffix(".md").read_text(encoding="utf-8")
    assert "stale note" not in text and "## Notes" in text and "Strict level:" in text
    assert "stale note" not in path.read_text(encoding="utf-8")  # the JSON has the new notes too


def test_a_gate_that_fails_is_reported_as_failing_and_a_skipped_proxy_as_skipped():
    gate = {**full_result()["gate"], "n_mismatch": 2, "speedup": {"solve": 1.3, "canon": None}}
    text = render_markdown(full_result(gate=gate, highs_js={"skipped": True, "reason": "node is not installed"}))
    assert "The gate fails" in text and "2 mismatches" in text and "Not run: node is not installed" in text


def test_the_markdown_report_of_a_gate_only_run_has_just_the_gate():
    text = render_markdown({"date": "2026-10-14", "environment": {}, "gate": full_result()["gate"]})
    assert "## Presolve gate" in text and "## Per-solve" not in text and "## CPU hours" not in text


# ---- a smoke run ------------------------------------------------------------------------------------------------------


@cache
def synthetic_items():
    """About sixty invented catalog items over the slots, with weapons, shields, Lore items, haste and a class lock."""
    rng = random.Random(11)
    slots = ["HEAD", "NECK", "CHEST", "LEGS", "ARMS", "EAR", "FINGER", "WRIST", "FEET", "WAIST", "BACK", "HANDS"]
    items = []

    def base(key, slot_list, **changes):
        item = {
            "key": key, "name": f"Invented {key}", "wiki": {"pageid": 1, "revid": 1, "title": key},
            "slots": list(slot_list), "classes": ["ALL"], "races": ["ALL"], "deity": None, "flags": [],
            "stats": {}, "sv": {}, "weight": round(rng.uniform(0.1, 9.0), 1), "size": "SMALL", "item_type": None,
            "weapon": None, "container_capacity": None, "instrument_mods": {}, "effects": [], "required_level": None,
            "recommended_level": None, "sources": {"drops": [], "sold_by": [], "quests": [], "crafted": []},
            "categories": [], "era_tags": [], "lucy_img_id": None, "tier_rule": "drop", "parse_warnings": [],
            "parse_warnings_overflow": 0, "evidence": {"level": "wiki", "reasons": []},
        }  # fmt: skip
        base_stats = {s: rng.randint(1, 30) for s in rng.sample(["STR", "STA", "AGI", "DEX", "WIS", "INT", "HP", "MANA", "AC", "ATK"], 3)}
        item["stats"] = base_stats
        if rng.random() < 0.3:
            item["sv"] = {rng.choice(["FIRE", "COLD", "MAGIC", "POISON", "DISEASE"]): rng.randint(3, 25)}
        if rng.random() < 0.2:
            item["flags"] = ["lore"]
        item.update(changes)
        return item

    for n in range(48):
        items.append(base(f"w{n:03d}", [slots[n % len(slots)]]))
    for n in range(6):
        items.append(base(f"w1h{n}", ["PRIMARY", "SECONDARY"], stats={"STR": 5 + n},
                          weapon={"skill": "1H Slashing", "dmg": 10 + 3 * n, "delay": 22 + 4 * n, "bonus": None}))
    for n in range(3):
        items.append(base(f"w2h{n}", ["PRIMARY"], stats={"STA": 4 + n},
                          weapon={"skill": "2H Slashing", "dmg": 30 + 5 * n, "delay": 40 + 6 * n, "bonus": None}))
    for n in range(3):
        items.append(base(f"wsh{n}", ["SECONDARY"], item_type="Shield", stats={"AC": 12 + 4 * n, "STA": 3}))
    items.append(base("whaste", ["WAIST"], stats={"STA": 5}))
    items[-1]["stats"]["HASTE"] = 30
    items.append(base("wlocked", ["HEAD"], classes=["WIZ"], stats={"INT": 40}))
    return items


def test_two_scenarios_run_in_under_a_minute_and_record_every_measurement():
    started = time.perf_counter()
    sample = [
        Scenario("HUM", ("WAR", "MNK", "ROG"), "balanced", "dw", 4, "wiki", "own"),
        Scenario("ERU", ("CLR", "WIZ", "ENC"), "balanced", "stick", 0, "strict-proxy", "group"),
    ]
    records = bench.run(sample, inputs=tiny_inputs(), workers=1, time_limit=60.0)
    assert time.perf_counter() - started < 60
    assert [r["key"] for r in records] == [s.key for s in sample]
    for r in records:
        assert r["error"] is None and r["status_solve"] == r["status_canon"] == "optimal"
        assert r["t_solve"] > 0 and r["t_canon"] > 0 and r["t_prune"] >= 0 and r["t_build"] > 0  # wall seconds
        assert all(r[f"c_{stage}"] >= 0 for stage in ("profile", "prune", "build", "solve", "canon"))  # CPU seconds
        assert r["cols"] > 0 and r["rows"] > 0 and r["n_kept"] <= r["n_pool"]
        assert set(r["binaries"]) == set(BINARY_KINDS)
        assert r["stratum"] == stratum_of(tuple(r["trio"]), TABLES) and r["nodes_solve"] >= 0
        assert abs(r["F_canon"] - r["F_solve"]) <= 1e-9 * abs(r["F_solve"])
    assert records[1]["n_pool"] < records[0]["n_pool"]  # the strict proxy is a part of the wiki pool


def test_a_scenario_that_fails_is_recorded_and_the_run_goes_on():
    bad = Scenario("HUM", ("WIZ", "MAG", "ENC"), "tank", "stick", 4, "wiki", "own")  # casters are not offered the tank role
    good = Scenario("HUM", ("WIZ", "MAG", "ENC"), "balanced", "stick", 4, "wiki", "own")
    records = bench.run([bad, good], inputs=tiny_inputs(), workers=1, time_limit=60.0)
    assert records[0]["error"] is not None and "role" in records[0]["error"] and records[0].get("t_solve") is None
    assert records[1]["error"] is None


def test_the_gate_solves_with_presolve_off_and_on_and_finds_no_mismatch_on_the_invented_pool():
    gate = bench.presolve_gate(6, seed=3, inputs=tiny_inputs(), workers=1, canonical_every=3, time_limit=60.0)
    assert gate["n"] == 6 and gate["n_mismatch"] == 0 and gate["mismatches"] == [] and gate["errors"] == 0
    assert gate["max_rel_diff"] <= 1e-9 and gate["guarded"] == 0
    assert set(gate["speedup"]) == {"solve", "canon"} and set(gate["wall_speedup"]) == {"solve", "canon"}
    assert gate["wall_speedup"]["solve"] > 0 and gate["time_off"]["n"] == 6  # the CPU clock ticks 1/64 s: any value goes
    assert gate["canonical"]["n"] == 2 and 0 <= gate["canonical"]["same_items"] <= 2
    assert gate["highs"]["version"] and gate["options"]["presolve"] == "off"


def test_the_whole_command_line_writes_a_json_and_a_short_markdown_report(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"version": "test", "items": synthetic_items()}), encoding="utf-8")
    out = tmp_path / "bench-test.json"
    code = bench.main([
        "--catalog", str(catalog), "--out", str(out), "--sample", "4", "--bench-trios", "2", "--races", "HUM",
        "--tiers", "4", "--max-scenarios", "6", "--uniform", "4", "--mps", "2", "--mps-dir", str(tmp_path / "mps"),
        "--workers", "1", "--no-node", "--time-limit", "60", "--seed", "1",
    ])  # fmt: skip
    assert code == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    md = out.with_suffix(".md").read_text(encoding="utf-8")
    assert result["gate"]["n"] == 4 and result["bench"]["n"] == 6 and result["uniform"]["n"] == 4
    assert {"decision", "extrapolation", "environment", "highs_js"} <= set(result)
    assert result["highs_js"]["skipped"] and len(list((tmp_path / "mps").glob("*.mps"))) == 2
    assert (tmp_path / "mps" / "manifest.json").is_file()
    assert result["decision"]["scope"] in ("all", "0/4/10") and md.startswith("# ")
    assert_public(result)
    assert str(tmp_path) not in out.read_text(encoding="utf-8") and str(tmp_path) not in md


def test_a_gate_only_run_writes_just_the_gate_and_exits_zero_when_it_passes(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"version": "test", "items": synthetic_items()}), encoding="utf-8")
    out = tmp_path / "gate.json"
    code = bench.main([
        "--catalog", str(catalog), "--out", str(out), "--gate-only", "--sample", "3", "--workers", "1",
        "--canonical-every", "0", "--time-limit", "60", "--seed", "5",
    ])  # fmt: skip
    assert code == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert set(result) == {"date", "environment", "gate"} and result["gate"]["n"] == 3
    assert "## Presolve gate" in out.with_suffix(".md").read_text(encoding="utf-8")


def test_a_gate_only_run_exits_one_on_a_mismatch(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"version": "test", "items": synthetic_items()}), encoding="utf-8")
    real = bench.presolve_gate
    monkeypatch.setattr(bench, "presolve_gate", lambda *a, **k: {**real(2, 1, inputs=bench.Inputs.load(catalog)), "n_mismatch": 1})
    out = tmp_path / "gate.json"
    code = bench.main(["--catalog", str(catalog), "--out", str(out), "--gate-only", "--sample", "2", "--workers", "1"])
    assert code == 1 and json.loads(out.read_text(encoding="utf-8"))["gate"]["n_mismatch"] == 1


# ---- the real catalog -----------------------------------------------------------------------------------------------


def test_the_real_catalog_gives_a_wiki_pool_and_a_scenario_that_solves():
    path = bench.find_catalog()
    if path is None:
        pytest.skip("derived/catalog.json is not built")
    inputs = Inputs.load(path)
    assert len(inputs.items) > 1000 and all(item["slots"] for item in inputs.items)
    proxy = bench.strict_proxy(inputs.items)
    assert 0.3 < len(proxy) / len(inputs.items) < 0.6 and {i["key"] for i in proxy} <= {i["key"] for i in inputs.items}
    ctx = bench.Context(inputs)
    record = ctx.measure(Scenario("OGR", ("PAL", "MNK", "BER"), "balanced", "2h", 4, "wiki", "group"), time_limit=120.0)
    assert record["error"] is None and record["status_canon"] == "optimal" and record["cols"] > 500
