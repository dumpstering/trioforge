"""Tests for the owned-aware mode of the dominance pruning: ``prune(..., owned=...)`` at mixed tiers.

The Upgrade tab prunes a pool that holds the visitor's own items (at the tiers of the dump) and the candidates (at the
tier of the tier mode). The rule of ``trioforge.solver.prune`` for that pool:

* an **owned** item (named in ``owned`` or in ``options.owned_caps``) is never dropped, even one that is dominated, that
  no class of the trio can wear or that the profile's deity or race excludes (the builder simply gives it no column);
* a candidate is dropped only by a **candidate at its own tier** that can replace it, or by an owned item that can replace
  it and has **enough copies** to stand in every place it could (its count is at least the places of its groups: then
  its row can never bind);
* an item that is **constrained at least as much** may not replace one that is constrained less: a free item (neither
  owned nor new) is not dropped for a new one, and an upgrade target (made from a copy of its source) replaces nothing;
* with ``tier=None`` the pool may hold items of any tier, as the pool of a session does; with an int every item must be at
  it, as before.

The evidence: the hand cases of each clause, a definition written out again item by item (as ``test_prune`` does for the
plain rule), the MILP optimum of the full pool against the pruned pool on 200 random mixed-tier cases under the
owned-item options, and a mutation check: with one clause broken on purpose (the module's test hook) the random suite
must see a lower optimum.

Every name here is invented.
"""

import dataclasses
import importlib
import random
from collections import Counter
from contextlib import contextmanager
from fractions import Fraction

import pytest

import solver_helpers as H
import upgrade_helpers as U
from solver_helpers import make_item
from trioforge.model import formulas as fm
from trioforge.model.items import SLOT_GROUPS
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.prune import STAT_DIMS, fit_groups, prune, prune_report
from trioforge.solver.solve import solve

prune_module = importlib.import_module("trioforge.solver.prune")

TRIO = ("PAL", "MNK", "BER")
PROFILE = H.make_profile(TRIO, "OGR", {"HP": 1})
REL = 1e-9
SIZE = dict(SLOT_GROUPS)


def options(**changes):
    return BuildOptions(**{"any_rule": "explicit", "haste_assumed": 0, **changes})


def item(key, hp, *, tier=0, slots=("FINGER",), lore=False, **more):
    return make_item(key, set(slots), stats={"HP": hp}, tier=tier, lore=lore, **more)


def idents(items):
    return sorted(f"{i.key}@{i.tier}" for i in items)


def run(items, owned=(), tier=None, **opts):
    return prune(items, PROFILE, tier, "stick", None, options(**opts), owned=frozenset(owned))


def optimum(profile, items, setup, buffset, opts):
    solution = solve(build_milp(profile, items, setup, buffset, opts))
    assert solution.status == "optimal"
    return solution.F


def close(a, b):
    return abs(a - b) <= REL * max(1.0, abs(a), abs(b))


@contextmanager
def broken(mutation):
    saved = prune_module._OWNED_MUTATION
    prune_module._OWNED_MUTATION = mutation
    try:
        yield
    finally:
        prune_module._OWNED_MUTATION = saved


# ---- owned items are never dropped -----------------------------------------------------------------------------------


def test_an_owned_item_is_kept_even_when_a_candidate_is_better_in_every_way():
    own, best = item("chest-own", 10, slots=("CHEST",)), item("chest-best", 100, slots=("CHEST",))
    assert idents(run([own, best])) == ["chest-best@0"]  # nothing owned: the usual rule
    assert idents(run([own, best], owned={"chest-own@0"})) == ["chest-best@0", "chest-own@0"]
    assert idents(run([own, best], owned_caps={"chest-own@0": 1})) == ["chest-best@0", "chest-own@0"]  # the caps name them too


def test_an_owned_item_the_profile_cannot_use_is_still_in_the_result_and_a_stranger_is_not():
    locked = make_item("locked-ear", {"EAR"}, stats={"HP": 90}, deity=("Tunare",))
    stranger = make_item("locked-twin", {"EAR"}, stats={"HP": 90}, deity=("Tunare",))
    caster = make_item("caster-ring", {"FINGER"}, stats={"HP": 90}, classes=("CLR", "WIZ"))
    plain = item("plain", 4, slots=("EAR",))
    pool = [locked, stranger, caster, plain]
    kept = run(pool, owned={"locked-ear@0", "caster-ring@0"})
    assert idents(kept) == ["caster-ring@0", "locked-ear@0", "plain@0"]
    report = prune_report(pool, PROFILE, None, "stick", None, options(), owned=frozenset({"locked-ear@0", "caster-ring@0"}))
    assert report.dropped == {("locked-twin", 0): ("deity", None)}
    milp_full = build_milp(PROFILE, pool, "stick", None, options(owned_caps={"locked-ear@0": 1, "caster-ring@0": 1}))
    milp_kept = build_milp(PROFILE, kept, "stick", None, options(owned_caps={"locked-ear@0": 1, "caster-ring@0": 1}))
    assert solve(milp_full).F == solve(milp_kept).F  # the builder gives the owned strangers no column, so nothing changes


def test_without_owned_items_the_new_arguments_change_nothing():
    import test_prune as TP

    inst = TP.case(3)
    plain = BuildOptions(any_rule=inst.any_rule, haste_assumed=inst.haste_assumed)
    old = prune(inst.items, inst.profile, 0, inst.setup, inst.buffset, plain)
    assert old == prune(inst.items, inst.profile, 0, inst.setup, inst.buffset, plain, owned=frozenset())
    assert old == prune(inst.items, inst.profile, 0, inst.setup, inst.buffset, plain, frozenset())


# ---- tiers ---------------------------------------------------------------------------------------------------------------


def test_a_pool_of_many_tiers_needs_tier_none_and_a_number_still_means_every_item_is_at_it():
    pool = [item("a", 5, tier=0, slots=("EAR",)), item("b", 3, tier=4, slots=("EAR",))]
    with pytest.raises(ValueError):
        run(pool, tier=0)
    with pytest.raises(ValueError):
        run(pool, tier=4)
    assert run(pool, tier=None)
    for bad in (1.5, "0", True):
        with pytest.raises(ValueError):
            run(pool, tier=bad)


def test_a_candidate_is_dropped_only_by_a_candidate_at_its_own_tier():
    best_plus4, weak_plus0, weak_plus4 = item("a", 50, tier=4, slots=("EAR",)), item("b", 10, tier=0, slots=("EAR",)), item("c", 10, tier=4, slots=("EAR",))
    assert idents(run([best_plus4, weak_plus0])) == ["a@4", "b@0"]  # a is better in every way but not at b's tier
    assert idents(run([best_plus4, weak_plus4])) == ["a@4"]  # at its own tier it is dropped as always
    assert idents(run([best_plus4, weak_plus0, weak_plus4])) == ["a@4", "b@0"]


def test_an_owned_item_with_enough_copies_drops_a_candidate_whatever_the_tier():
    own, cand = item("ring-own", 10, tier=4), item("ring-cand", 3, tier=0)
    assert idents(run([own, cand], owned={"ring-own@4"}, owned_caps={"ring-own@4": 2})) == ["ring-own@4"]
    assert idents(run([own, cand], owned={"ring-own@4"}, owned_caps={"ring-own@4": 9})) == ["ring-own@4"]


def test_an_owned_item_without_enough_copies_drops_nothing_because_its_row_could_bind():
    own, cand = item("ring-own", 10), item("ring-cand", 3)
    assert idents(run([own, cand], owned_caps={"ring-own@0": 1})) == ["ring-cand@0", "ring-own@0"]
    # the Any group is a place too, once an item lists it: two finger places and two Any places want four copies
    any_own, any_cand = item("any-own", 10, slots=("FINGER", "ANY")), item("any-cand", 3, slots=("FINGER", "ANY"))
    assert idents(run([any_own, any_cand], owned_caps={"any-own@0": 3})) == ["any-cand@0", "any-own@0"]
    assert idents(run([any_own, any_cand], owned_caps={"any-own@0": 4})) == ["any-own@0"]


def test_the_count_decides_whether_the_weaker_ring_is_needed_and_the_pruned_pool_agrees():
    own, cand = item("ring-own", 10), item("ring-cand", 3)
    for count, expected in ((1, ["ring-cand@0", "ring-own@0"]), (2, ["ring-own@0"])):
        opts = options(owned_caps={"ring-own@0": count}, new_keys=frozenset({"ring-cand@0"}), max_new=1)
        kept = prune([own, cand], PROFILE, None, "stick", None, opts)
        assert idents(kept) == expected, count
        full = optimum(PROFILE, [own, cand], "stick", None, opts)
        restricted = options(owned_caps={"ring-own@0": count}, new_keys=frozenset({"ring-cand@0"} & set(idents(kept))), max_new=1)
        assert close(full, optimum(PROFILE, kept, "stick", None, restricted))
    assert optimum(PROFILE, [own, cand], "stick", None, options(owned_caps={"ring-own@0": 1}, new_keys=frozenset({"ring-cand@0"}), max_new=1)) > optimum(
        PROFILE, [own], "stick", None, options(owned_caps={"ring-own@0": 1})
    )  # with one copy the weaker ring is worth acquiring, so dropping it would have been wrong


# ---- how constrained an item is ------------------------------------------------------------------------------------------


def test_an_upgrade_target_replaces_nothing_because_it_shares_the_copy_of_its_source():
    source, target, other = item("band", 1, tier=2), item("band", 20, tier=4), item("band2", 15, tier=4)
    caps, ups = {"band@2": 1}, {"band@4": "band@2"}
    for max_new in (1, 2):
        opts = options(owned_caps=caps, upgrades=ups, new_keys=frozenset({"band2@4"}), max_new=max_new)
        kept = prune([source, target, other], PROFILE, None, "stick", None, opts)
        assert idents(kept) == ["band2@4", "band@2", "band@4"]
        full = optimum(PROFILE, [source, target, other], "stick", None, opts)
        assert close(full, optimum(PROFILE, kept, "stick", None, opts))
    two = optimum(PROFILE, [source, target, other], "stick", None, options(owned_caps=caps, upgrades=ups, new_keys=frozenset({"band2@4"}), max_new=2))
    naked = optimum(PROFILE, [], "stick", None, options())
    # the upgraded copy and a copy of the upgrade (20 + 20): band2 is no longer needed, though the pruning (exact, not tight) keeps it
    assert close(two, naked + 40)


def test_an_upgrade_target_replaces_nothing_because_its_first_wear_costs_a_copy_of_its_source():
    source, target, other = item("band", 10, tier=2), item("band", 12, tier=4), item("band2", 11, tier=4)
    opts = options(owned_caps={"band@2": 1}, upgrades={"band@4": "band@2"}, new_keys=frozenset({"band2@4"}), max_new=1)
    kept = prune([source, target, other], PROFILE, None, "stick", None, opts)
    assert idents(kept) == ["band2@4", "band@2", "band@4"]
    naked = optimum(PROFILE, [], "stick", None, options())
    assert close(optimum(PROFILE, [source, target, other], "stick", None, opts), naked + 21)  # the owned copy and one acquired band2
    only = options(owned_caps={"band@2": 1}, upgrades={"band@4": "band@2"}, max_new=1)
    assert close(optimum(PROFILE, [source, target], "stick", None, only), naked + 12)  # dropping band2 for the target would lose 9


def test_a_free_item_is_not_dropped_for_a_new_one_that_the_limit_may_forbid():
    new, free = item("new-ring", 20), item("free-ring", 10)
    opts = options(new_keys=frozenset({"new-ring@0"}), max_new=0)
    kept = prune([new, free], PROFILE, None, "stick", None, opts)
    assert "free-ring@0" in idents(kept)
    naked = optimum(PROFILE, [], "stick", None, options())
    assert close(optimum(PROFILE, kept, "stick", None, opts), naked + 20)  # two free rings; the new one may not be acquired
    assert close(optimum(PROFILE, [new, free], "stick", None, opts), naked + 20)
    # the other way round a new item is dropped for a free one: wearing the free one never costs an acquisition
    assert idents(prune([item("new-ring", 10), item("free-ring", 20)], PROFILE, None, "stick", None, opts)) == ["free-ring@0"]


def test_a_duplicate_may_replace_a_new_item_of_its_tier_and_not_one_of_another_tier():
    dup, weak = item("ring-dup", 10), item("ring-weak", 3)
    opts = options(owned_caps={"ring-dup@0": 1}, new_keys=frozenset({"ring-dup@0", "ring-weak@0"}), max_new=1)
    kept = prune([dup, weak], PROFILE, None, "stick", None, opts)
    assert idents(kept) == ["ring-dup@0"]
    full = optimum(PROFILE, [dup, weak], "stick", None, opts)
    assert close(full, optimum(PROFILE, kept, "stick", None, options(owned_caps={"ring-dup@0": 1}, new_keys=frozenset({"ring-dup@0"}), max_new=1)))
    other_tier = item("ring-weak", 3, tier=3)
    opts = options(owned_caps={"ring-dup@0": 1}, new_keys=frozenset({"ring-dup@0", "ring-weak@3"}), max_new=1)
    assert idents(prune([dup, other_tier], PROFILE, None, "stick", None, opts)) == ["ring-dup@0", "ring-weak@3"]


def test_a_lore_item_still_never_justifies_a_drop_in_the_owned_mode():
    lore, plain = item("band", 20, slots=("EAR",), lore=True), item("stud", 5, slots=("EAR",))
    opts = options(owned_caps={"band@0": 1}, new_keys=frozenset({"stud@0"}), max_new=1)
    assert idents(prune([lore, plain], PROFILE, None, "stick", None, opts)) == ["band@0", "stud@0"]


# ---- the sweep against the definition -----------------------------------------------------------------------------------------


def contribution(it, group):
    ac = it.stats.get("AC", 0)
    return (0, ac) if (it.is_shield and group == "SECONDARY") else (ac, 0)


def naive_owned_kept(inst, opts, owned):
    """The definition, item by item: a non-owned item goes only if a plain item that is allowed to stand in for it can wear
    its places (a strict order among equals, ties by ident)."""
    report = prune_report(inst.items, inst.profile, None, inst.setup, inst.buffset, opts, owned=frozenset(owned))
    p = fm.compile_profile(inst.profile)
    setup = inst.setup or "stick"
    compared = set(report.compared)
    trio = {spec.cls for spec in p.pools["HP"]}
    deity = getattr(inst.profile, "deity", None)
    race = getattr(inst.profile, "race", None)

    def usable(i):
        return (
            i.classes & trio and (i.deity is None or (deity is not None and deity in i.deity))
            and (race is None or i.races is None or race in i.races)
        )

    pool = [i for i in inst.items if usable(i) and any(H.fits(i, g, setup, opts.any_rule) for g, _ in SLOT_GROUPS)]
    fits = {id(i): frozenset(g for g, _ in SLOT_GROUPS if H.fits(i, g, setup, opts.any_rule)) for i in pool}
    caps, news, ups = dict(opts.owned_caps or {}), set(opts.new_keys) | set(opts.upgrades or {}), dict(opts.upgrades or {})
    protected = set(owned) | set(caps)

    def name(i):
        return f"{i.key}@{i.tier}"

    def places(i):
        return sum(SIZE[g] for g in fits[id(i)])

    def count(i):
        return caps.get(name(i), 1)

    def duplicate(i):
        return name(i) in protected and name(i) in news and count(i) >= 1

    def enough(i):
        return name(i) in protected and not i.lore and count(i) >= places(i)

    def rank(i):
        if name(i) in ups:
            return 2
        if enough(i):
            return -1  # a row that can never bind: as free as an item with no row, and the first to be asked
        return 1 if name(i) in news else 0

    def index(i, group):
        return Fraction(0) if i.weapon is None else fm.weapon_index(i.weapon, group, setup, report.haste_assumed, p.dw_factor)

    def two_handed(i):
        return i.weapon is not None and i.weapon.two_handed

    def dominates(a, b):  # the plain rule: every compared dimension, the places and the hands
        if a.lore or not fits[id(a)] >= fits[id(b)]:
            return False
        for dim in compared:
            if dim in STAT_DIMS and a.stats.get(dim, 0) < b.stats.get(dim, 0):
                return False
            if dim.startswith("SV_") and a.sv.get(dim[3:], 0) < b.sv.get(dim[3:], 0):
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

    def may_replace(a, b):
        if a.lore or name(a) in ups or not dominates(a, b):
            return False
        if enough(a):
            return True  # a row that can never bind: an unlimited plain item, of any tier
        if name(a) in protected and not duplicate(a):
            return False
        return a.tier == b.tier and rank(a) <= rank(b)

    kept = []
    for b in pool:
        if name(b) in protected:
            kept.append(b)
            continue
        gone = any(  # among items that can replace each other, an owned one stays and then the smaller ident
            may_replace(a, b) and (not may_replace(b, a) or name(a) in protected or name(a) < name(b))
            for a in pool if a is not b
        )
        if not gone:
            kept.append(b)
    extra = [i for i in inst.items if name(i) in protected and i not in pool]  # owned strangers stay in the result
    return sorted(name(i) for i in [*kept, *extra]), report


def test_the_sweep_finds_exactly_the_items_the_definition_keeps_in_the_owned_mode():
    with_drops, with_protected = 0, 0
    for seed in range(120):
        inst, caps, news, ups, max_new = U.ownership_case(seed, pool="prunable")
        opts = U.options_of(inst, caps, news, ups, max_new)
        want, report = naive_owned_kept(inst, opts, set(caps))
        got = sorted(f"{i.key}@{i.tier}" for i in report.kept)
        assert got == want, f"seed {seed} ({inst.label})"
        with_drops += len(want) < len(inst.items)
        with_protected += bool(caps)
    assert with_drops >= 80 and with_protected >= 100


# ---- exactness: random mixed-tier cases -------------------------------------------------------------------------------------


def compare(seed, pool="prunable", **kwargs):
    """The MILP optimum of the full pool and of the pruned pool under the owned-item options; ``(ok, message, dropped)``."""
    inst, caps, news, ups, max_new = U.ownership_case(seed, pool=pool, **kwargs)
    opts = U.options_of(inst, caps, news, ups, max_new)
    kept = prune(inst.items, inst.profile, None, inst.setup, inst.buffset, opts, owned=frozenset(caps))
    assert set(caps) <= {f"{i.key}@{i.tier}" for i in kept}  # every owned item survives
    full = solve(build_milp(inst.profile, inst.items, inst.setup, inst.buffset, opts))
    kept_caps, kept_news, kept_ups = U.restrict(kept, caps, news, ups)
    small = solve(build_milp(inst.profile, kept, inst.setup, inst.buffset, U.options_of(inst, kept_caps, kept_news, kept_ups, max_new)))
    if full.status != "optimal" or small.status != "optimal":
        return False, f"status {full.status} / {small.status}", 0
    if not close(full.F, small.F):
        return False, f"full {full.F!r} against pruned {small.F!r}", 0
    return True, "", len(inst.items) - len(kept)


def test_pruning_is_exact_against_the_unpruned_optimum_on_200_random_mixed_tier_cases():
    dropped, failures, cases_with_drops = 0, [], 0
    for seed in range(200):
        ok, message, gone = compare(seed)
        if not ok:
            failures.append((seed, message))
        dropped += gone
        cases_with_drops += gone > 0
    assert not failures, failures[:5]
    assert cases_with_drops >= 100 and dropped >= 300  # the pruning has real work to do in these pools


def test_pruning_is_exact_when_an_upgrade_may_be_worn_more_than_once():
    dropped, failures, twice, made, fallbacks = 0, [], 0, 0, 0
    for seed in range(120):
        ok, message, gone = compare(seed, repeats=True)
        if not ok:
            failures.append((seed, message))
        dropped += gone
        inst, caps, news, ups, max_new = U.ownership_case(seed, pool="prunable", repeats=True)
        milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst, caps, news, ups, max_new))
        wears = Counter(U.ident(worn) for worn in solve(milp).kit if worn is not None)  # (the optimum of the pool before pruning)
        twice += any(wears[target] >= 2 for target in ups)
        made += any(name.startswith("made[") for name in milp.names)
        fallbacks += not any(item.slots & U.WIDE_SLOTS for item in inst.items)  # no item of a group of two places: no twin can be worn twice
    assert not failures, failures[:5]
    assert dropped >= 100  # the pruning has work to do in these pools
    assert twice >= 30  # the unpruned optimum wears an upgrade target at least twice (39 of the 120 cases)
    assert made >= 80 and fallbacks <= 20  # a made column in 96 of the 120; 12 of them have no item that can be worn twice


def test_pruning_is_exact_on_small_pools_when_an_upgrade_may_be_worn_more_than_once():
    for seed in range(60):
        inst, caps, news, ups, max_new = U.ownership_case(seed, repeats=True)
        opts = U.options_of(inst, caps, news, ups, max_new)
        kept = prune(inst.items, inst.profile, None, inst.setup, inst.buffset, opts, owned=frozenset(caps))
        kept_caps, kept_news, kept_ups = U.restrict(kept, caps, news, ups)
        pruned = dataclasses.replace(inst, items=kept)
        assert U.best_under(pruned, kept_caps, kept_news, kept_ups, max_new) == U.best_under(inst, caps, news, ups, max_new), seed


def test_pruning_is_exact_on_pools_small_enough_to_list_every_kit():
    for seed in range(60):
        inst, caps, news, ups, max_new = U.ownership_case(seed)
        opts = U.options_of(inst, caps, news, ups, max_new)
        kept = prune(inst.items, inst.profile, None, inst.setup, inst.buffset, opts, owned=frozenset(caps))
        kept_caps, kept_news, kept_ups = U.restrict(kept, caps, news, ups)
        pruned = dataclasses.replace(inst, items=kept)
        assert U.best_under(pruned, kept_caps, kept_news, kept_ups, max_new) == U.best_under(inst, caps, news, ups, max_new), seed


def test_the_report_does_not_depend_on_the_order_of_the_pool():
    for seed in range(15):
        inst, caps, news, ups, max_new = U.ownership_case(seed, pool="prunable")
        opts = U.options_of(inst, caps, news, ups, max_new)
        one = prune_report(inst.items, inst.profile, None, inst.setup, inst.buffset, opts, owned=frozenset(caps))
        shuffled = list(inst.items)
        random.Random(seed).shuffle(shuffled)
        two = prune_report(shuffled, inst.profile, None, inst.setup, inst.buffset, opts, owned=frozenset(caps))
        assert [(i.key, i.tier) for i in one.kept] == [(i.key, i.tier) for i in two.kept], seed
        assert one.dropped == two.dropped, seed


# ---- the broken rules are seen ------------------------------------------------------------------------------------------------


def hand_case(mutation):
    """``(items, options)`` in which the clause that ``mutation`` breaks decides the optimum by hand."""
    if mutation == "owned_dropped":  # two owned rings, one better in every way: both are needed, one copy each
        return [item("ring-low", 10), item("ring-high", 100)], options(owned_caps={"ring-low@0": 1, "ring-high@0": 1})
    if mutation == "copies_ignored":  # one copy of the better ring is not enough to do without the weaker new one
        return [item("ring-own", 10), item("ring-cand", 3)], options(
            owned_caps={"ring-own@0": 1}, new_keys=frozenset({"ring-cand@0"}), max_new=1
        )
    if mutation == "target_dominates":  # the owned copy and one acquired item are both worn: upgrading the copy leaves the target alone
        return [item("band", 10, tier=2), item("band", 12, tier=4), item("band2", 11, tier=4)], options(
            owned_caps={"band@2": 1}, upgrades={"band@4": "band@2"}, new_keys=frozenset({"band2@4"}), max_new=1
        )
    return [item("new-ring", 20), item("free-ring", 10)], options(new_keys=frozenset({"new-ring@0"}), max_new=0)  # rank_ignored


@pytest.mark.parametrize("mutation", ["owned_dropped", "copies_ignored", "target_dominates", "rank_ignored"])
def test_each_broken_rule_is_seen_by_the_hand_case_that_needs_it(mutation):
    items, opts = hand_case(mutation)
    full = optimum(PROFILE, items, "stick", None, opts)
    assert close(full, optimum(PROFILE, prune(items, PROFILE, None, "stick", None, opts), "stick", None, opts))  # right as it is
    with broken(mutation):
        kept = prune(items, PROFILE, None, "stick", None, opts)
    names = set(idents(kept))
    caps, news, ups = U.restrict(kept, opts.owned_caps or {}, opts.new_keys, opts.upgrades or {})
    small = optimum(PROFILE, kept, "stick", None, options(owned_caps=caps, new_keys=frozenset(news), upgrades=ups, max_new=opts.max_new))
    assert not close(full, small) or not set(opts.owned_caps or {}) <= names, mutation


@pytest.mark.parametrize("mutation", ["owned_dropped", "copies_ignored", "target_dominates", "rank_ignored"])
def test_each_broken_rule_makes_the_random_suite_fail(mutation):
    seen = 0
    for seed in range(200):
        with broken(mutation):
            ok, _, _ = compare_quietly(seed)
        seen += not ok
        if seen >= 2:
            break
    assert seen >= 1, f"no case notices the broken rule {mutation!r}"


def compare_quietly(seed):
    try:
        return compare(seed)
    except AssertionError as error:  # an owned item missing from the result is a failure too
        return False, str(error), 0
