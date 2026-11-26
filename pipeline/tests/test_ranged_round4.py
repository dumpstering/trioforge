"""The Bow setup, the fourth round: one policy for a pool that is not there, a pool that is any iterable, and the words of the code.

With no pool to read, a shield is assumed (the design grid of a trio has it) and a bow is not: the Bow setup is the one setup that only a pool offers. The policy is one for every role:
no role has "ranged" among its setups with no pool, and the Ranged role, which is nothing but the Bow setup, has none either, so it is not offered: ``setups_for`` gives ``[]`` for it,
``roles_for(trio, bow=False)`` leaves it out, a profile of it with no pool is refused, a grid with no pool has no scenario of it, and a bundle gives the Ranged role's profile only at
an evidence level. (Assuming the bow for every role, as the shield is, would have changed the setups that every Warrior, Paladin, Ranger, Shadow Knight and Rogue trio has with no pool: 14 tests
of 08c0500, in four files (test_weapons, test_profile, test_bench, test_export_browser), failed under that policy when it was tried, and the old tests stand unchanged under this one.)

Every item here is invented; the classes, the skill name and the trios are public game terms.
"""

from __future__ import annotations

import pytest
from solver_helpers import make_item
from test_ranged import RULES, TABLES, bow
from test_ranged_round2 import ALL_SKILLS, TRIO, caps

from trioforge.classes import CLASS_CODES
from trioforge.model import roles, weapons
from trioforge.model.roles import roles_for
from trioforge.model.profile import make_profile
from trioforge.precompute import grid

TABLE = caps(RNG=("Archery", *ALL_SKILLS), WAR=("Archery", *ALL_SKILLS), CLR=ALL_SKILLS)


# ---- no pool ----------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", [role for role in weapons.ROLES if role in roles_for(TRIO, bow=None)])  # (the builds the trio is offered)
def test_with_no_pool_no_role_has_the_bow_setup_and_the_ranged_role_has_nothing(role):
    setups = weapons.setups_for(TRIO, role, TABLE, level=50)
    assert "ranged" not in setups
    if role == "ranged":
        assert setups == []
        assert setups == weapons.setups_for(TRIO, role, TABLE, level=50, items=[])  # (as for a pool with nothing in it)


def test_the_other_roles_get_the_setups_they_always_got_with_no_pool():
    # a shield is assumed with no pool, as the design grid has it, and nothing else is: these are the lists of 08c0500 for a trio of Ranger, Warrior and Cleric
    assert weapons.setups_for(TRIO, "tank", TABLE, level=50) == ["1h-shield", "2h", "dw"]
    assert weapons.setups_for(TRIO, "melee", TABLE, level=50) == ["2h", "dw"]
    assert weapons.setups_for(TRIO, "shield", TABLE, level=50) == ["1h-shield", "stick"]  # (the Shield caster: the shield, which is assumed with no pool, and the stick)
    casters = ("CLR", "DRU", "WIZ")  # (the trio of the other casting builds: no tank class and two spell classes)
    assert weapons.setups_for(casters, "castertank", TABLE, level=50) == ["1h-shield", "stick"]
    assert weapons.setups_for(casters, "caster", TABLE, level=50) == ["stick", "1h-shield"]  # (the Caster lists the stick first: the first setup wins a tie)


def test_a_profile_of_the_ranged_role_with_no_pool_is_refused_and_no_other_role_has_the_bow_there():
    with pytest.raises(ValueError, match="not offered"):
        make_profile("HUM", TRIO, 50, "ranged", None, None, TABLES)
    for role in ("tank", "shield", "melee"):  # (the builds the trio is offered)
        assert "ranged" not in make_profile("HUM", TRIO, 50, role, None, None, TABLES).setups, role
    # with a pool that has a bow the role is made, and it plays the bow
    assert list(make_profile("HUM", TRIO, 50, "ranged", None, None, TABLES, items=[bow("it-bow", 30, 40)]).setups) == ["ranged"]


def test_a_grid_with_no_pool_has_no_scenario_of_the_bow_setup_or_the_ranged_role():
    plan = grid.scenarios(("RNG", "DRU", "MNK"), TABLES, RULES, races=["HUM"], tiers=[0], evidence=["wiki"], buffs=["own"])
    assert plan and {scenario.role for scenario in plan} == {"melee"}  # (a Ranger and a Monk with one Druid: Melee damage alone)
    assert all(scenario.role != "ranged" and scenario.setup != "ranged" for scenario in plan)
    with pytest.raises(ValueError, match="ranged"):
        grid.scenarios(("RNG", "DRU", "MNK"), TABLES, RULES, roles=["ranged"])  # (a role the trio is not offered)


def test_roles_for_a_pool_that_is_not_there_is_asked_with_bow_false():
    for trio in (TRIO, ("RNG", "BER", "BRD")):
        assert "ranged" not in roles.roles_for(trio, bow=False)
        assert roles.roles_for(trio, bow=None)[-1] == "ranged"  # (a caller that has no pool to ask about at all lists the roles of the trio)


# ---- any iterable -----------------------------------------------------------------------------------------------------------------------


def test_the_pool_may_be_a_generator_the_bow_and_the_shield_are_both_read_from_it():
    pool = [make_item("it-shield", {"SECONDARY"}, shield=True, classes=("WAR", "RNG", "CLR")), bow("it-bow", 30, 40)]  # (the bow last: reading it for the bow reads all of the pool)
    for role in roles_for(TRIO, bow=True):  # (the builds the trio is offered, the Archer with this pool)
        from_list = weapons.setups_for(TRIO, role, TABLE, level=50, items=pool)
        from_generator = weapons.setups_for(TRIO, role, TABLE, level=50, items=(item for item in pool))
        assert from_generator == from_list, role
    assert "ranged" in weapons.setups_for(TRIO, "tank", TABLE, level=50, items=(item for item in pool))
    assert "1h-shield" in weapons.setups_for(TRIO, "tank", TABLE, level=50, items=(item for item in pool))
    assert weapons.setups_for(TRIO, "ranged", TABLE, level=50, items=iter(pool)) == ["ranged"]
    # the same through a profile (whose pool is a generator too)
    made = make_profile("HUM", TRIO, 50, "tank", None, None, TABLES, items=(item for item in pool))
    assert made.setups[-1] == "ranged"


def test_a_class_that_cannot_shoot_is_no_archer_whatever_the_pool():
    every = [bow("it-bow", 30, 40, classes=tuple(CLASS_CODES))]
    assert "ranged" not in weapons.setups_for(("CLR", "DRU", "WIZ"), "castertank", caps(CLR=ALL_SKILLS), level=50, items=every)
    assert weapons.setups_for(("CLR", "DRU", "WIZ"), "ranged", caps(CLR=ALL_SKILLS), level=50, items=every) == []


# ---- the range place under the four old setups ------------------------------------------------------------------------------------------


def test_the_range_place_admits_every_item_that_has_it_in_the_four_old_setups_and_only_a_bow_in_the_bow_setup():
    """What the builder's pruner asks (``fit_groups``) of the range place: ``allowed_in_hand(item, "range", setup)`` is true for every item in the four old setups, so
    adding the range place to the groups the rules decide changes none of them; the browser's pruner (``fitGroups``, tests-js/ranged-round4.test.mjs) is held to the same table."""
    from trioforge.model.items import WeaponVec
    from trioforge.solver.prune import fit_groups

    arrows = bow("it-bow", 45, 60)
    ornament = make_item("it-ornament", {"RANGE"})
    sword = make_item("it-sword", {"PRIMARY", "RANGE"}, weapon=WeaponVec("1H Slashing", 20, 30, None, False))
    old = {
        "it-bow": {"1h-shield": {"RANGE"}, "2h": {"RANGE"}, "dw": {"RANGE"}, "stick": {"RANGE"}},
        "it-ornament": {"1h-shield": {"RANGE"}, "2h": {"RANGE"}, "dw": {"RANGE"}, "stick": {"RANGE"}},
        "it-sword": {"1h-shield": {"PRIMARY", "RANGE"}, "2h": {"RANGE"}, "dw": {"PRIMARY", "RANGE"}, "stick": {"PRIMARY", "RANGE"}},
    }
    for item in (arrows, ornament, sword):
        for setup, groups in old[item.key].items():
            assert fit_groups(item, setup, "explicit") == frozenset(groups), (item.key, setup)
            assert weapons.allowed_in_hand(item, "range", setup) is True, (item.key, setup)
    assert fit_groups(arrows, "ranged", "explicit") == frozenset({"RANGE"})
    assert fit_groups(ornament, "ranged", "explicit") == frozenset()
    assert fit_groups(sword, "ranged", "explicit") == frozenset({"PRIMARY"})


# ---- the roles of a trio, with a pool that has a bow ----------------------------------------------------------------------------------------


def test_roles_for_offers_ranged_to_a_trio_with_a_ranger_only_when_the_pool_has_a_bow():
    """The 08c0500 tests of ``roles_for`` stand as they were (test_roles.py, test_bench.py): with no pool no trio has the Ranged role. These are the new rules, given a pool."""
    import itertools

    for trio in itertools.combinations(CLASS_CODES, 3):
        plain = roles.roles_for(trio)
        assert plain == roles.roles_for(trio, bow=False) and "ranged" not in plain, trio
        with_bow = roles.roles_for(trio, bow=True)
        assert with_bow == [role for role in roles.ROLES if role in (*plain, *(["ranged"] if "RNG" in trio else []))], trio  # (in the order of the builds)
        assert roles.roles_for(trio, bow=None) == with_bow, trio


def test_the_weights_of_the_ranged_role_are_known_and_follow_the_mana_and_damage_rules_of_the_other_roles():
    """The loops of test_roles.py over the roles of every trio run over what ``roles_for`` gives with no pool, which has no Ranged role: these are the same checks for it."""
    from test_roles import DAMAGE_WEIGHT, MANA_CLASSES, MELEE_T, TRIOS as ALL_TRIOS

    from trioforge.rules import load as load_rules

    rules = load_rules()
    ranger_trios = [trio for trio in ALL_TRIOS if "RNG" in trio]
    assert ranger_trios
    for trio in ranger_trios:
        weights = roles.weights_for(trio, "ranged", rules)
        assert all(type(value) in (int, float) and value >= 0 for value in weights.values()), trio
        assert {"HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "CHA", "HPREG", "MANAREG", "ENDREG"} <= set(weights), trio
        assert (weights["MANA"] > 0) == bool(MANA_CLASSES & set(trio)), trio
        assert (weights["MANAREG"] > 0) == bool(MANA_CLASSES & set(trio)), trio
        assert weights["DMG"] == DAMAGE_WEIGHT * MELEE_T["ATK"], trio  # (the Ranged template differs from the Melee one in DEX and AC only)
