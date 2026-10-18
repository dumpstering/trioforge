"""Tests for the owned-item options of the MILP builder and for the names of its rows.

The Upgrade tab asks questions about gear a visitor owns, so the builder takes four options besides the pool
(``trioforge.solver.model.BuildOptions``):

* ``owned_caps``: ``{ident: count}``. An owned item is worn at most its count **over every group it stands in** (one
  row per item, named ``own.<ident>``, only when the count is below what its columns could add up to). The ident of an
  item is ``key@tier``: the same key at two tiers is two items with two counts.
* ``new_keys`` and ``max_new``: ``new.limit`` is the row ``sum(wears of the new items) <= max_new``, over every group.
  An item that is not owned is a new wear; an owned item listed in ``new_keys`` is a **duplicate** (one more copy may be
  acquired, so it may be worn above its count, and each such wear costs one of ``max_new``).
* ``upgrades``: ``{target ident: source ident}``. The target is the same key at a higher tier. Its first copy is made from
  one copy of the owned source: the copy is worn at one tier or the other, so the source's row covers the target too. Every
  further copy of the target is a copy of the target, not another upgrade, and each wear of the target costs one of
  ``max_new``. A target that can be worn once at most is counted by its wear; one that can be worn more often by a 0/1 column
  ``made[<target>]`` that is 1 when it is worn at all (the row ``made.<target>``).

Every row also has a name now (``Milp.row_names``, unique and the same on every build); naming rows must not change a
model. The evidence: hand cases for each rule (several of them drafted by outside models from the plan and checked
against it), a brute force over every legal kit that enforces the wear counts with a definition written out again in
``upgrade_helpers``, and a mutation check that shows the random suite sees a missing row.

Every name here is invented.
"""

import dataclasses
import hashlib
import random
import re
from types import SimpleNamespace

import numpy as np
import pytest

import solver_helpers as H
import upgrade_helpers as U
from solver_helpers import make_item
from trioforge.export import milp_json
from trioforge.model.formulas import EvalProfile
from trioforge.solver._highs import solve_milp
from trioforge.solver.model import BINARY_KINDS, BuildOptions, build_milp
from trioforge.solver.solve import solve

TRIO = ("PAL", "MNK", "BER")
PROFILE = H.make_profile(TRIO, "OGR", {"HP": 1})  # every point of item HP is worth exactly one
OGRE = SimpleNamespace(**{f.name: getattr(PROFILE, f.name) for f in dataclasses.fields(EvalProfile)}, race="OGR", deity=None)


def options(**changes):
    return BuildOptions(**{"any_rule": "explicit", "haste_assumed": 0, **changes})


def build(items, profile=PROFILE, **changes):
    return build_milp(profile, items, "stick", None, options(**changes))


def item(key, hp, *, tier=0, slots=("FINGER",), lore=False, **more):
    return make_item(key, set(slots), stats={"HP": hp}, tier=tier, lore=lore, **more)


def worn(solution):
    """``{ident: copies}`` of the kit."""
    counts = {}
    for entry in solution.kit:
        if entry is not None:
            name = f"{entry.key}@{entry.tier}"
            counts[name] = counts.get(name, 0) + 1
    return counts


def rows_named(milp, prefix):
    return [name for name in milp.row_names if name.startswith(prefix)]


def row_columns(milp, name):
    """``{column name: coefficient}`` of the row called ``name``."""
    r = milp.row_names.index(name)
    lo, hi = milp.A.start[r], milp.A.start[r + 1]
    return {milp.names[c]: float(v) for c, v in zip(milp.A.index[lo:hi], milp.A.value[lo:hi])}


# ---- the names of the rows -------------------------------------------------------------------------------------------

ROW_NAME = re.compile(
    r"""^(
        group\.[A-Z]+ | lore\..+ | two_hander
      | buff\.clique\[[0-9,]+\] | buff\.conflict\[[0-9]+,[0-9]+\] | buff\.limit
      | (curve|legacy)\.[A-Za-z0-9_.]+\.(total|deficit|flat|ord[0-9]+\.(full|empty[0-9]+))
      | cap\.[A-Z]+\.max
      | pool\.(HP|MANA|END)\.(kept\.[A-Z]+\.(le_pool|le_chosen)|picks|twin[0-9]+)
      | monk\.(one|upper|lower) | sheet\.(below|past)
      | haste\.(y[0-9/]+\.worn|one|best|room)
      | (regen\.[A-Z]+|sv\.[A-Z]+)\.max
      | made\..+@[0-9]+ | own\..+@[0-9]+ | new\.limit
    )$""",
    re.X,
)


def test_every_row_has_a_name_and_the_names_are_unique_on_random_instances():
    checked = 0
    for seed in range(40):
        inst = H.random_instance(random.Random(seed))
        milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst))
        assert len(milp.row_names) == milp.num_rows > 0, seed
        assert all(isinstance(name, str) and name for name in milp.row_names), seed
        assert len(set(milp.row_names)) == len(milp.row_names), seed
        for name in milp.row_names:
            assert ROW_NAME.match(name), (seed, name)
        checked += milp.num_rows
    assert checked > 500


def test_the_names_are_the_same_on_every_build_and_whatever_the_order_of_the_pool():
    for seed in range(12):
        inst = H.random_instance(random.Random(seed))
        one = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst))
        shuffled = list(inst.items)
        random.Random(seed).shuffle(shuffled)
        two = build_milp(inst.profile, shuffled, inst.setup, inst.buffset, U.options_of(inst))
        assert one.row_names == two.row_names and one.names == two.names, seed
        assert np.array_equal(one.A.value, two.A.value) and np.array_equal(one.row_ub, two.row_ub), seed


def test_the_default_owned_options_add_no_row_and_no_column_to_any_model():
    for seed in range(12):
        inst = H.random_instance(random.Random(seed))
        plain = BuildOptions(any_rule=inst.any_rule, haste_assumed=inst.haste_assumed)
        spelled = BuildOptions(
            any_rule=inst.any_rule, haste_assumed=inst.haste_assumed, owned_caps=None, new_keys=frozenset(), max_new=None,
            upgrades=None,
        )
        one = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, plain)
        two = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, spelled)
        for a, b in (
            (one.c, two.c), (one.A.start, two.A.start), (one.A.index, two.A.index), (one.A.value, two.A.value),
            (one.row_lb, two.row_lb), (one.row_ub, two.row_ub), (one.col_lb, two.col_lb), (one.col_ub, two.col_ub),
        ):
            assert np.array_equal(a, b), seed
        assert one.names == two.names and one.row_names == two.row_names and one.const == two.const and one.info == two.info


def test_the_rows_of_a_small_model_are_named_by_what_they_say():
    items = [
        item("ring-a", 5), item("ring-b", 4), item("ring-c", 3),
        item("ear-lore", 9, slots=("EAR",), lore=True), item("ear-one", 2, slots=("EAR",)), item("ear-two", 1, slots=("EAR",)),
    ]
    milp = build(items)
    assert "group.FINGER" in milp.row_names and "group.EAR" in milp.row_names
    assert "lore.ear-lore" not in milp.row_names  # one column of a Lore item needs no row of its own
    assert row_columns(milp, "group.FINGER") == {"n[FINGER|ring-a]": 1.0, "n[FINGER|ring-b]": 1.0, "n[FINGER|ring-c]": 1.0}
    twice = build(items + [item("ear-lore", 9, tier=2, slots=("EAR",), lore=True)])
    assert row_columns(twice, "lore.ear-lore") == {"n[EAR|ear-lore]": 1.0, "n[EAR|ear-lore@2]": 1.0}  # one key, two tiers


def test_two_rows_that_would_get_one_name_are_told_apart_the_same_way_every_time():
    buffs = [H.make_buff(1, HP=5), H.make_buff(2, HP=6)]
    repeated = H.make_buffset(optional=buffs, conflicts=[(1, 2)], cliques=[(1, 2), (1, 2)])  # a hand-made set repeats a clique
    one = build_milp(PROFILE, [], None, repeated, options())
    two = build_milp(PROFILE, [], None, repeated, options())
    cliques = rows_named(one, "buff.clique")
    assert len(cliques) == 2 and len(set(one.row_names)) == len(one.row_names)
    assert one.row_names == two.row_names


# ---- owned caps ------------------------------------------------------------------------------------------------------


def test_an_owned_item_is_worn_no_more_often_than_it_is_owned():
    big, small = item("big", 10), item("small", 3)
    free = solve(build([big, small]))
    assert worn(free) == {"big@0": 2}  # nothing stops two copies of the big ring
    capped = solve(build([big, small], owned_caps={"big@0": 1, "small@0": 5}))
    assert worn(capped) == {"big@0": 1, "small@0": 1}
    assert capped.F == free.F - 7


def test_the_cap_row_covers_every_group_the_item_fits_including_the_any_group():
    ring = item("ring", 10, slots=("FINGER", "ANY"))  # two finger places and two Any places
    filler = item("filler", 1)
    assert worn(solve(build([ring, filler]))) == {"ring@0": 4}
    one = build([ring, filler], owned_caps={"ring@0": 1})
    assert row_columns(one, "own.ring@0") == {"n[FINGER|ring]": 1.0, "n[ANY|ring]": 1.0}
    assert worn(solve(one)) == {"ring@0": 1, "filler@0": 2}  # the ring in an Any place, fillers in both finger places
    assert worn(solve(build([ring, filler], owned_caps={"ring@0": 2}))) == {"ring@0": 2, "filler@0": 2}
    assert worn(solve(build([ring, filler], owned_caps={"ring@0": 3}))) == {"ring@0": 3, "filler@0": 1}
    assert not rows_named(build([ring, filler], owned_caps={"ring@0": 4}), "own.")  # four places: the cap cannot bind


def test_a_lore_item_with_a_count_above_one_is_still_worn_once_and_a_cap_that_cannot_bind_makes_no_row():
    lore = item("band", 10, slots=("EAR",), lore=True)
    other = item("stud", 2, slots=("EAR",))
    milp = build([lore, other], owned_caps={"band@0": 2, "stud@0": 9})
    assert worn(solve(milp)) == {"band@0": 1, "stud@0": 1}
    assert not rows_named(milp, "own.")  # the Lore bound is 1 per column, a count of 2 never binds; 9 never does either
    twice = build([lore, item("band", 10, tier=3, slots=("EAR",), lore=True)], owned_caps={"band@0": 5, "band@3": 5})
    assert sum(worn(solve(twice)).values()) == 1  # the Lore row spans the tiers of the key
    none = build([lore, other], owned_caps={"band@0": 0})
    assert rows_named(none, "own.") == ["own.band@0"]
    assert worn(solve(none)) == {"stud@0": 2}


def test_a_count_of_zero_keeps_an_item_out_of_the_kit_and_a_count_at_the_places_makes_no_row():
    ring = item("ring", 10)
    other = item("other", 1)
    assert worn(solve(build([ring, other], owned_caps={"ring@0": 0}))) == {"other@0": 2}
    for count, has_row in ((0, True), (1, True), (2, False), (3, False)):
        assert bool(rows_named(build([ring], owned_caps={"ring@0": count}), "own.")) is has_row, count


def test_the_caps_are_read_in_sorted_order_whatever_the_order_of_the_mapping():
    items = [item(f"r{n}", 10 - n) for n in range(5)]
    items += [item("e", 7, slots=("EAR",)), item("f", 6, slots=("EAR",)), item("g", 5, slots=("EAR",))]
    caps = {f"r{n}@0": 1 for n in range(5)} | {"e@0": 1, "f@0": 1}
    one = build(items, owned_caps=caps)
    two = build(items, owned_caps=dict(reversed(list(caps.items()))))
    assert one.row_names == two.row_names and np.array_equal(one.A.value, two.A.value) and np.array_equal(one.row_ub, two.row_ub)
    own = [name for name in one.row_names if name.startswith("own.")]
    assert len(own) == 7 and own == sorted(own)


def test_an_owned_item_the_profile_cannot_use_is_never_worn_and_does_not_break_the_build():
    locked = make_item("locked-ear", {"EAR"}, stats={"HP": 90}, deity=("Tunare",))
    only_iksar = dataclasses.replace(make_item("scale-back", {"BACK"}, stats={"HP": 90}), races=frozenset({"IKS"}))
    plain = item("plain", 4, slots=("EAR",))
    caps = {"locked-ear@0": 1, "scale-back@0": 1, "plain@0": 1}
    milp = build([locked, only_iksar, plain], OGRE, owned_caps=caps)
    assert worn(solve(milp)) == {"plain@0": 1}
    assert not any("locked-ear" in name or "scale-back" in name for name in milp.names)  # no column for either
    assert not rows_named(milp, "own.locked") and not rows_named(milp, "own.scale")
    follower = SimpleNamespace(**{**vars(OGRE), "deity": "Tunare"})
    assert worn(solve(build([locked, only_iksar, plain], follower, owned_caps=caps))) == {"locked-ear@0": 1, "plain@0": 1}


def test_the_same_key_at_two_tiers_has_one_cap_for_each_tier():
    low, high = item("band", 4, tier=2), item("band", 9, tier=4)
    both = solve(build([low, high], owned_caps={"band@2": 1, "band@4": 1}))
    assert worn(both) == {"band@2": 1, "band@4": 1}
    one_high = solve(build([low, high], owned_caps={"band@2": 5, "band@4": 1}))
    assert worn(one_high) == {"band@2": 1, "band@4": 1}  # not two high copies
    one_low = solve(build([low, high], owned_caps={"band@2": 1, "band@4": 5}))
    assert worn(one_low) == {"band@4": 2}


@pytest.mark.parametrize(
    "bad",
    [
        {"nobody@0": 1},  # not in the pool
        {"ring": 1},  # not an ident
        {"ring@x": 1}, {"ring@-1": 1}, {"ring@11": 1}, {"@0": 1}, {"ring@0@0": 1},
        {"ring@0": -1}, {"ring@0": 1.5}, {"ring@0": True}, {"ring@0": "2"},
    ],
)
def test_bad_owned_caps_are_refused(bad):
    with pytest.raises(ValueError):
        build([item("ring", 5)], owned_caps=bad)


def test_bad_limits_and_new_items_are_refused():
    for bad in (-1, 1.5, True, "1"):
        with pytest.raises(ValueError):
            options(max_new=bad)
    with pytest.raises(ValueError):
        build([item("ring", 5)], new_keys=frozenset({"ghost@0"}), max_new=1)
    with pytest.raises(ValueError):
        options(new_keys=frozenset({"ring"}))


# ---- the limit on new items -------------------------------------------------------------------------------------------


def test_max_new_one_admits_exactly_one_new_copy_over_every_group():
    ring = item("ring", 10, slots=("FINGER", "ANY"))
    filler = item("filler", 1)
    new = frozenset({"ring@0"})
    milp = build([ring, filler], new_keys=new, max_new=1)
    assert row_columns(milp, "new.limit") == {"n[FINGER|ring]": 1.0, "n[ANY|ring]": 1.0}
    assert worn(solve(milp)) == {"ring@0": 1, "filler@0": 2}  # one new ring (in an Any place), two fillers
    assert worn(solve(build([ring, filler], new_keys=new, max_new=2))) == {"ring@0": 2, "filler@0": 2}
    assert worn(solve(build([ring, filler], new_keys=new, max_new=0))) == {"filler@0": 2}
    assert not rows_named(build([ring, filler], new_keys=new, max_new=4), "new.")  # four places: the limit cannot bind
    assert not rows_named(build([ring, filler], new_keys=new), "new.")  # no limit given


def test_the_limit_counts_copies_over_all_the_new_items_not_the_keys():
    a, b, c = item("a", 10), item("b", 9), item("c", 8, slots=("EAR",))
    everything = frozenset({"a@0", "b@0", "c@0"})
    assert worn(solve(build([a, b, c], new_keys=everything, max_new=1))) == {"a@0": 1}
    assert worn(solve(build([a, b, c], new_keys=everything, max_new=2))) == {"a@0": 2}
    # b is free and fills the finger places; of the two new items c stands in another group, so it is the one acquired
    assert worn(solve(build([a, b, c], new_keys=frozenset({"a@0", "c@0"}), max_new=1))) == {"c@0": 1, "b@0": 2}
    assert worn(solve(build([a, b, c], new_keys=frozenset({"a@0", "b@0"}), max_new=1))) == {"a@0": 1, "c@0": 2}  # c is free


def test_wearing_an_owned_item_does_not_use_up_the_limit():
    owned, fresh = item("own", 5), item("fresh", 4)
    new = frozenset({"fresh@0"})
    assert worn(solve(build([owned, fresh], owned_caps={"own@0": 1}, new_keys=new, max_new=1))) == {"own@0": 1, "fresh@0": 1}
    assert worn(solve(build([owned, fresh], owned_caps={"own@0": 1}, new_keys=new, max_new=0))) == {"own@0": 1}


def test_a_candidate_that_is_also_owned_may_be_worn_above_its_count_for_one_new_copy():
    ring, other = item("ring", 10), item("other", 2)
    new = frozenset({"ring@0"})
    one = solve(build([ring, other], owned_caps={"ring@0": 1}, new_keys=new, max_new=1))
    assert worn(one) == {"ring@0": 2}  # one owned and one acquired
    none = solve(build([ring, other], owned_caps={"ring@0": 1}, new_keys=new, max_new=0))
    assert worn(none) == {"ring@0": 1, "other@0": 1}
    milp = build([ring, other], owned_caps={"ring@0": 1}, new_keys=new, max_new=1)
    assert "new[ring@0]" in milp.names and row_columns(milp, "own.ring@0")["new[ring@0]"] == -1.0


def test_a_candidate_listed_as_owned_with_none_is_a_plain_new_item():
    ring, other = item("ring", 10), item("other", 2)
    milp = build([ring, other], owned_caps={"ring@0": 0}, new_keys=frozenset({"ring@0"}), max_new=1)
    assert worn(solve(milp)) == {"ring@0": 1, "other@0": 1}
    assert "new[ring@0]" not in milp.names and not rows_named(milp, "own.")


def test_a_lore_item_that_is_owned_and_a_candidate_adds_no_column_and_no_use_of_the_limit():
    lore, other = item("band", 10, slots=("EAR",), lore=True), item("stud", 2, slots=("EAR",))
    milp = build([lore, other], owned_caps={"band@0": 1}, new_keys=frozenset({"band@0"}), max_new=1)
    assert worn(solve(milp)) == {"band@0": 1, "stud@0": 1}
    assert "new[band@0]" not in milp.names and not rows_named(milp, "new.")


# ---- upgrades -----------------------------------------------------------------------------------------------------------


def test_an_upgrade_is_made_from_an_owned_copy_so_it_never_adds_a_copy():
    low, high = item("band", 4, tier=2), item("band", 9, tier=4)
    ups = {"band@4": "band@2"}
    milp = build([low, high], owned_caps={"band@2": 2}, upgrades=ups, max_new=1)
    assert row_columns(milp, "own.band@2") == {"n[FINGER|band]": 1.0, "n[FINGER|band@4]": 1.0}
    assert worn(solve(milp)) == {"band@2": 1, "band@4": 1}  # two copies, one of them upgraded
    assert worn(solve(build([low, high], owned_caps={"band@2": 1}, upgrades=ups, max_new=1))) == {"band@4": 1}
    assert worn(solve(build([low, high], owned_caps={"band@2": 2}, upgrades=ups, max_new=2))) == {"band@4": 2}
    assert worn(solve(build([low, high], owned_caps={"band@2": 2}, upgrades=ups, max_new=0))) == {"band@2": 2}


def test_an_upgrade_counts_as_new_but_the_owned_tier_does_not():
    low, high = item("band", 4, tier=0), item("band", 9, tier=4)
    plain = build([low, high], owned_caps={"band@0": 1}, new_keys=frozenset({"band@4"}), max_new=1)
    assert worn(solve(plain)) == {"band@0": 1, "band@4": 1}  # the owned copy does not use the limit; the other tier is new
    up = build([low, high], owned_caps={"band@0": 1}, upgrades={"band@4": "band@0"}, max_new=1)
    assert worn(solve(up)) == {"band@4": 1}
    none = build([low, high], owned_caps={"band@0": 1}, upgrades={"band@4": "band@0"}, max_new=0)
    assert worn(solve(none)) == {"band@0": 1}  # an upgrade is not free: it uses one of the new items


def test_an_upgrade_of_a_candidate_costs_one_more_acquisition():
    low, high = item("band", 4, tier=1), item("band", 9, tier=3)
    kwargs = dict(owned_caps={"band@1": 1}, new_keys=frozenset({"band@1"}), upgrades={"band@3": "band@1"})
    assert worn(solve(build([low, high], max_new=1, **kwargs))) == {"band@3": 1}
    # two acquisitions: a copy of the source upgraded would leave the source and the target, but one upgrade and a copy of the
    # upgrade is two target wears for the same two acquisitions
    assert worn(solve(build([low, high], max_new=2, **kwargs))) == {"band@3": 2}
    assert worn(solve(build([low, high], max_new=3, **kwargs))) == {"band@3": 2}
    row = row_columns(build([low, high], max_new=3, **kwargs), "own.band@1")  # the source acquired and upgraded is still two acquisitions
    assert row == {"n[FINGER|band]": 1.0, "made[band@3]": 1.0, "new[band@1]": -1.0}


# ---- an upgraded item and the copies of it ----------------------------------------------------------------------------------------


def made_of(milp, target):
    """``(lower bound, upper bound, integer)`` of the column ``made[<target>]``."""
    col = milp.names.index(f"made[{target}]")
    return float(milp.col_lb[col]), float(milp.col_ub[col]), int(milp.integrality[col])


def test_a_target_worn_more_than_once_is_made_from_one_copy_of_its_source_and_each_other_wear_is_a_copy_of_the_target():
    low, high, filler = item("band", 4, tier=2), item("band", 9, tier=4), item("filler", 1)
    pool, ups = [low, high, filler], {"band@4": "band@2"}
    milp = build(pool, owned_caps={"band@2": 1}, upgrades=ups, max_new=2)
    assert made_of(milp, "band@4") == (0.0, 1.0, 1)
    assert milp.info["binaries"]["made"] == 1  # counted with the other binaries of the build
    assert row_columns(milp, "made.band@4") == {"n[FINGER|band@4]": 1.0, "made[band@4]": -2.0}  # worn at all: made
    r = milp.row_names.index("made.band@4")
    assert (milp.row_lb[r], milp.row_ub[r]) == (-np.inf, 0.0)
    # one copy of the source, however often the target is worn: the target's own columns are not in the row
    assert row_columns(milp, "own.band@2") == {"n[FINGER|band]": 1.0, "made[band@4]": 1.0}
    assert milp.row_names.index("made.band@4") < milp.row_names.index("own.band@2")
    assert worn(solve(milp)) == {"band@4": 2}  # the owned copy upgraded and one more copy of the upgrade: two acquisitions
    assert worn(solve(build(pool, owned_caps={"band@2": 1}, upgrades=ups, max_new=1))) == {"band@4": 1, "filler@0": 1}
    assert worn(solve(build(pool, owned_caps={"band@2": 1}, upgrades=ups, max_new=3))) == {"band@4": 2}
    assert worn(solve(build(pool, owned_caps={"band@2": 1}, upgrades=ups, max_new=0))) == {"band@2": 1, "filler@0": 1}
    unlimited = build(pool, owned_caps={"band@2": 1}, upgrades=ups)  # no limit: the same two wears, and no new.limit
    assert worn(solve(unlimited)) == {"band@4": 2} and not rows_named(unlimited, "new.")
    assert row_columns(unlimited, "made.band@4") == {"n[FINGER|band@4]": 1.0, "made[band@4]": -2.0}


def test_the_further_copies_of_a_target_do_not_use_up_more_copies_of_its_source():
    low, high, filler = item("band", 4, tier=2), item("band", 9, tier=4), item("filler", 1)
    ups = {"band@4": "band@2"}
    for copies in (1, 2, 3):  # the source keeps its other copies whatever the target does
        milp = build([low, high, filler], owned_caps={"band@2": copies}, upgrades=ups, max_new=2)
        assert worn(solve(milp)) == {"band@4": 2}, copies
    # the one place the target does not take stays with an owned copy of the source
    wide = item("band", 4, tier=2, slots=("FINGER", "EAR")), item("band", 9, tier=4, slots=("FINGER", "EAR"))
    got = worn(solve(build(list(wide), owned_caps={"band@2": 3}, upgrades=ups, max_new=2)))
    assert got == {"band@4": 2, "band@2": 2}  # two finger places taken by the target, two ear places by the source


def test_a_duplicated_source_counts_the_made_column_in_its_row_and_keeps_its_extra_copies():
    low, high, filler = item("band", 4, tier=2), item("band", 9, tier=4), item("filler", 1)
    pool, ups = [low, high, filler], {"band@4": "band@2"}
    milp = build(pool, owned_caps={"band@2": 1}, new_keys=frozenset({"band@2"}), upgrades=ups, max_new=3)
    assert row_columns(milp, "own.band@2") == {"n[FINGER|band]": 1.0, "made[band@4]": 1.0, "new[band@2]": -1.0}
    assert float(milp.col_ub[milp.names.index("new[band@2]")]) == 2.0  # what the row can hold above the count: 2 + 1 - 1
    assert worn(solve(milp)) == {"band@4": 2}
    one = build(pool, owned_caps={"band@2": 1}, new_keys=frozenset({"band@2"}), upgrades=ups, max_new=1)
    assert worn(solve(one)) == {"band@4": 1, "filler@0": 1}


def test_two_targets_of_one_source_each_have_a_made_column_and_share_the_copies_of_the_source():
    pool = [item("band", 4, tier=1), item("band", 7, tier=3), item("band", 9, tier=5)]
    ups = {"band@3": "band@1", "band@5": "band@1"}
    milp = build(pool, owned_caps={"band@1": 1}, upgrades=ups, max_new=2)
    assert [name for name in milp.row_names if name.startswith(("made.", "own."))] == ["made.band@3", "made.band@5", "own.band@1"]
    assert row_columns(milp, "own.band@1") == {"n[FINGER|band]": 1.0, "made[band@3]": 1.0, "made[band@5]": 1.0}
    assert milp.info["binaries"]["made"] == 2
    assert worn(solve(milp)) == {"band@5": 2}  # one copy of the source makes one of the two targets
    shuffled = build(list(reversed(pool)), owned_caps={"band@1": 1}, upgrades=dict(reversed(ups.items())), max_new=2)
    assert shuffled.names == milp.names and shuffled.row_names == milp.row_names  # sorted, whatever the order of a mapping


def test_the_made_column_is_made_only_when_the_row_of_the_source_can_bind():
    pool, ups = [item("band", 4, tier=2), item("band", 9, tier=4)], {"band@4": "band@2"}
    for count, bound in ((1, True), (2, True), (3, False), (9, False)):  # two places of the source and one made: 3
        milp = build(pool, owned_caps={"band@2": count}, upgrades=ups, max_new=2)
        assert ("own.band@2" in milp.row_names) == bound == ("made[band@4]" in milp.names) == ("made.band@4" in milp.row_names), count


def test_a_target_that_can_be_worn_once_at_most_is_counted_by_its_wear_as_it_always_was():
    cases = {
        "a Lore target": (
            [item("stud", 3, tier=1, slots=("EAR",), lore=True), item("stud", 8, tier=3, slots=("EAR",), lore=True)],
            dict(owned_caps={"stud@1": 1}, upgrades={"stud@3": "stud@1"}, max_new=2),
        ),
        "a target of one place": (
            [item("helm", 3, tier=1, slots=("HEAD",)), item("helm", 8, tier=3, slots=("HEAD",))],
            dict(owned_caps={"helm@1": 1}, upgrades={"helm@3": "helm@1"}, max_new=3),
        ),
        "a target of two places when one new wear is allowed": (
            [item("band", 4, tier=2), item("band", 9, tier=4)],
            dict(owned_caps={"band@2": 1}, upgrades={"band@4": "band@2"}, max_new=1),
        ),
        "a target of two places when none is": (
            [item("band", 4, tier=2), item("band", 9, tier=4)],
            dict(owned_caps={"band@2": 1}, upgrades={"band@4": "band@2"}, max_new=0),
        ),
    }
    for name, (pool, more) in cases.items():
        milp = build(pool, **more)
        assert not [n for n in milp.names if n.startswith("made[")] and not rows_named(milp, "made."), name
        assert milp.info["binaries"]["made"] == 0, name
    pool, more = cases["a target of two places when one new wear is allowed"]
    one = build(pool, **more)
    assert row_columns(one, "own.band@2") == {"n[FINGER|band]": 1.0, "n[FINGER|band@4]": 1.0}  # the target's columns, as before
    assert row_columns(one, "new.limit") == {"n[FINGER|band@4]": 1.0}


#: SHA-256 of the model JSON of programs shaped like those of a farm path (one new wear), taken from the builder as it was before a
#: target could be worn more than once: the rows, the columns and the order of both must not have moved. The text is the one the builder
#: wrote then, so the entry ``made`` that ``info.binaries`` has since (0 in all of them) is left out of it.
BEST_ONE_MODELS = {
    "a ring upgraded from two copies": "c8de70c9fcf4d6eacb7008826c7a9e459c939a4e5a18e46aa3c4f887358f774a",
    "a ring upgraded from one copy": "60588879463106e50a2fc2c83d9e7f1fa002831cda9afce81af6336d471593bd",
    "a Lore target": "720efb3856b9de79331bf07f594428c4f862ada0032ed3fa34ab5590e71242a3",
    "a target of one place": "c850792bb4f257c12592480988ff339de1d8bab737b9331e049974d21164378b",
    "two targets of one source": "7a9a5aeb51307d1a4f6e87bc17eaeb28c04b343db6729c6b0422b343ae0b1f6e",
    "a duplicated source with a target": "bb5ac08612cdfdf28a1d291be8d54ce0b63475866c5bdc71532568949bde8679",
}


def best_one_model(name):
    ring = [item("band", 4, tier=2), item("band", 9, tier=4)]
    if name == "a ring upgraded from two copies":
        return build(ring, owned_caps={"band@2": 2}, upgrades={"band@4": "band@2"}, max_new=1)
    if name == "a ring upgraded from one copy":
        return build(ring, owned_caps={"band@2": 1}, upgrades={"band@4": "band@2"}, max_new=1)
    if name == "a Lore target":
        pool = [item("stud", 3, tier=1, slots=("EAR",), lore=True), item("stud", 8, tier=3, slots=("EAR",), lore=True)]
        return build(pool, owned_caps={"stud@1": 1}, upgrades={"stud@3": "stud@1"}, max_new=2)
    if name == "a target of one place":
        pool = [item("helm", 3, tier=1, slots=("HEAD",)), item("helm", 8, tier=3, slots=("HEAD",))]
        return build(pool, owned_caps={"helm@1": 1}, upgrades={"helm@3": "helm@1"}, max_new=3)
    if name == "two targets of one source":
        pool = [item("band", 4, tier=1), item("band", 7, tier=3), item("band", 9, tier=5)]
        return build(pool, owned_caps={"band@1": 2}, upgrades={"band@3": "band@1", "band@5": "band@1"}, max_new=1)
    pool = [item("band", 4, tier=1), item("band", 9, tier=3)]
    return build(pool, owned_caps={"band@1": 1}, new_keys=frozenset({"band@1"}), upgrades={"band@3": "band@1"}, max_new=1)


def text_before_made_was_counted(milp):
    document = milp_json.to_dict(milp)
    assert document["info"]["binaries"].pop("made") == 0  # none of these programs has a made column
    return milp_json.dumps(document)


@pytest.mark.parametrize("name", sorted(BEST_ONE_MODELS))
def test_the_program_of_one_new_wear_over_an_upgrade_is_the_model_it_always_was(name):
    milp = best_one_model(name)
    assert hashlib.sha256(text_before_made_was_counted(milp).encode("ascii")).hexdigest() == BEST_ONE_MODELS[name]
    assert not [n for n in milp.names if n.startswith("made[")] and not rows_named(milp, "made.")


@pytest.mark.parametrize(
    "caps, ups",
    [
        ({"low@2": 1}, {"low@4": "ghost@2"}),  # the source is not in the pool
        ({"low@2": 1}, {"ghost@4": "low@2"}),  # nor the target
        ({}, {"low@4": "low@2"}),  # the source is not owned
        ({"low@2": 0}, {"low@4": "low@2"}),  # owned none
        ({"low@2": 1, "low@4": 1}, {"low@4": "low@2"}),  # the target is owned
        ({"low@4": 1}, {"low@2": "low@4"}),  # the target is below the source
        ({"low@2": 1}, {"low@2": "low@2"}),  # the same item
        ({"low@2": 1}, {"other@3": "low@2"}),  # another key
        ({"low@2": 1, "low@4": 1, "other@1": 1}, {"other@3": "other@1", "low@4": "low@2", "low@2": "low@4"}),  # a chain
    ],
)
def test_a_bad_upgrade_is_refused(caps, ups):
    pool = [item("low", 3, tier=2), item("low", 9, tier=4), item("other", 1, tier=1), item("other", 5, tier=3)]
    with pytest.raises(ValueError):
        build(pool, owned_caps=caps, upgrades=ups, max_new=1)


# ---- the evidence of the brute force --------------------------------------------------------------------------------------


@pytest.mark.parametrize("chains", [False, True])
def test_the_builder_agrees_with_the_brute_force_under_owned_caps_new_items_duplicates_and_upgrades(chains):
    bound, upgrades, duplicates, two_tiers, failures = 0, 0, 0, 0, []
    for seed in range(60):
        inst, caps, news, ups, max_new = U.ownership_case(seed, chains=chains)
        ok, message = U.check_owned(inst, caps, news, ups, max_new)
        if not ok:
            failures.append((seed, message))
        bound += U.best_under(inst, caps, news, ups, max_new) < U.best_under(inst)
        upgrades += bool(ups)
        duplicates += bool(news & set(caps))
        owned_keys = [name.rpartition("@")[0] for name, count in caps.items() if count]
        two_tiers += len(set(owned_keys)) < len(owned_keys)  # a key owned at two tiers
    assert not failures, failures[:5]
    assert bound >= 15 and upgrades >= 10 and duplicates >= 10  # the cases bind, upgrade and duplicate often enough to mean something
    assert not chains or two_tiers >= 4


@pytest.mark.parametrize("family", ["own.", "new.limit"])
def test_a_missing_row_is_seen_by_the_random_suite(family):
    """Drop every row of a family from the built model: the brute force must see a difference in some case."""
    seen = 0
    for seed in range(60):
        inst, caps, news, ups, max_new = U.ownership_case(seed)
        broken = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst, caps, news, ups, max_new))
        rows = [r for r, name in enumerate(broken.row_names) if name.startswith(family)]
        if not rows:
            continue
        for r in rows:
            broken.row_lb[r], broken.row_ub[r] = -np.inf, np.inf
        best = float(U.best_under(inst, caps, news, ups, max_new))
        seen += abs(broken.const + solve_milp(broken).objective - best) > 1e-7 * max(1.0, abs(best))
    assert seen >= 3, f"only {seen} cases notice a missing {family} row"


def test_the_builder_agrees_with_the_brute_force_when_an_upgrade_may_be_worn_more_than_once():
    """Sources owned once or twice and room for several acquisitions: the made rows are in many of the models and bind."""
    made, bound, failures = 0, 0, []
    for seed in range(60):
        inst, caps, news, ups, max_new = U.ownership_case(seed, repeats=True)
        ok, message = U.check_owned(inst, caps, news, ups, max_new)
        if not ok:
            failures.append((seed, message))
        milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst, caps, news, ups, max_new))
        made += any(name.startswith("made[") for name in milp.names)
        bound += U.best_under(inst, caps, news, ups, max_new) < U.best_under(inst, caps, news, ups, None)
    assert not failures, failures[:5]
    assert made >= 15 and bound >= 10  # the cases make the column, and the limit and the copies of the source bind


def test_a_missing_made_row_is_seen_by_the_random_suite():
    """Drop every made row: the target is then worn without a copy of its source, and the brute force must see it."""
    seen = 0
    for seed in range(150):
        inst, caps, news, ups, max_new = U.ownership_case(seed, repeats=True)
        broken = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst, caps, news, ups, max_new))
        rows = [r for r, name in enumerate(broken.row_names) if name.startswith("made.")]
        for r in rows:
            broken.row_lb[r], broken.row_ub[r] = -np.inf, np.inf
        if rows:
            best = float(U.best_under(inst, caps, news, ups, max_new))
            seen += abs(broken.const + solve_milp(broken).objective - best) > 1e-7 * max(1.0, abs(best))
    assert seen >= 5, f"only {seen} cases notice a missing made row"


def test_the_made_binaries_of_every_model_are_counted_in_its_info():
    counted, with_made, models = 0, 0, 0
    for seed in range(60):
        for flavour in ({}, {"repeats": True}):
            inst, caps, news, ups, max_new = U.ownership_case(seed, **flavour)
            milp = build_milp(inst.profile, inst.items, inst.setup, inst.buffset, U.options_of(inst, caps, news, ups, max_new))
            made = sum(name.startswith("made[") for name in milp.names)
            assert milp.info["binaries"]["made"] == made, (seed, flavour)
            assert set(milp.info["binaries"]) == set(BINARY_KINDS), (seed, flavour)
            # every counted binary is a 0/1 integer column of the model
            ones = int(((milp.integrality == 1) & (milp.col_lb == 0) & (milp.col_ub == 1)).sum())
            assert ones >= sum(milp.info["binaries"].values()), (seed, flavour)
            counted += made
            with_made += made > 0
            models += 1
    assert counted >= 25 and with_made >= 20 and models == 120  # many models have made columns
