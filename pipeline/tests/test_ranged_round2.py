"""The Bow setup and the Ranged role, the second round: what a review of the first found.

* the bow setup needs a class that has the Archery skill (the client's skill caps, as dual wield and the shield setup are gated);
* the Ranged role is offered only for a pool that has a bow a class of the trio can shoot (no stat stick instead);
* in the bow setup the Range place is always filled: a bow is forced into it, in the builder and in the space of kits, even when damage is worth nothing;
* ``roles.ranged_template`` is a rule of differences from the Melee template, applied to whatever the Melee template is;
* an off-hand shield counts in the bow setup exactly as in the shield setup.

Every item here is invented; the classes, the skill name and the trios are public game terms.
"""

from __future__ import annotations

import copy
from fractions import Fraction as F
from types import SimpleNamespace

import pytest
from solver_helpers import Space, make_item
from test_ranged import BOW_CLASSES, NAKED, POOLS, RAW, RULES, TABLES, best, bow, kit_of, profile, worn

from trioforge.classes import CLASS_CODES
from trioforge.model import roles, weapons
from trioforge.model.formulas import evaluate
from trioforge.model.items import WeaponVec
from trioforge.model.profile import make_profile
from trioforge.rules import Rules
from trioforge.solver.model import BuildOptions, build_milp

TRIO = ("RNG", "WAR", "CLR")


def caps(**by_class):
    """Skill caps of level 50: ``caps(RNG=("Archery", "1H Slashing"))`` is a table in which a Ranger has those two skills."""
    return SimpleNamespace(skillcap={(code, skill, 50): 100 for code, skills in by_class.items() for skill in skills}, rules=RULES)


ALL_SKILLS = (*weapons.ONE_HANDED_SKILLS, *weapons.TWO_HANDED_SKILLS, "Dual Wield")


# ---- the Archery skill ----------------------------------------------------------------------------------------------


def test_the_real_skill_caps_give_archery_to_the_classes_of_the_catalogs_bows_and_to_no_other():
    for level in (50, 55):
        has = {code for code in CLASS_CODES if TABLES.skillcap.get((code, "Archery", level), 0) > 0}
        assert has == BOW_CLASSES, (level, sorted(has ^ BOW_CLASSES))


@pytest.mark.parametrize(
    "table, expected",
    [
        pytest.param(caps(RNG=ALL_SKILLS, WAR=ALL_SKILLS, CLR=ALL_SKILLS), False, id="no archery skill in the trio"),
        pytest.param(caps(CLR=("Archery", *ALL_SKILLS), RNG=ALL_SKILLS, WAR=ALL_SKILLS), False, id="the one class with the skill cannot use the bow"),
        pytest.param(caps(RNG=("Archery", *ALL_SKILLS), WAR=ALL_SKILLS, CLR=ALL_SKILLS), True, id="the Ranger has the skill and the bow"),
        pytest.param(caps(RNG=ALL_SKILLS, WAR=("Archery", *ALL_SKILLS), CLR=ALL_SKILLS), False, id="the skill is the Warrior's and the bow is the Ranger's"),
    ],
)
def test_the_bow_setup_needs_a_class_that_has_the_archery_skill_and_may_equip_the_bow(table, expected):
    pool = [bow("it-bow", 30, 40, classes=("RNG",))]
    for role in ("tank", "melee"):
        assert ("ranged" in weapons.setups_for(TRIO, role, table, level=50, items=pool)) is expected, role
    assert weapons.bow_available(TRIO, pool, tables=table, level=50) is expected
    # and the same pool with no skill table to read is read as it was: the class list alone
    assert weapons.bow_available(TRIO, pool) is True


# ---- the Ranged role is not offered for a pool with no bow ------------------------------------------------------------


def test_the_ranged_role_has_no_setup_but_the_bow_so_a_pool_with_no_bow_leaves_it_none():
    table = caps(RNG=("Archery", *ALL_SKILLS), WAR=ALL_SKILLS, CLR=ALL_SKILLS)
    assert weapons.setups_for(TRIO, "ranged", table, level=50, items=[bow("it-bow", 30, 40)]) == ["ranged"]
    assert weapons.setups_for(TRIO, "ranged", table, level=50, items=[]) == []
    assert weapons.setups_for(TRIO, "ranged", table, level=50, items=[make_item("it-charm", {"RANGE"}, stats={"HP": 9})]) == []
    # (with no pool to read the role has none either: a bow is never assumed, as a shield is; test_ranged_round4.py)
    assert weapons.setups_for(TRIO, "ranged", table, level=50) == []


def test_roles_for_a_pool_with_no_bow_leaves_out_ranged_and_the_others_are_as_they_were():
    every = roles.roles_for(TRIO, bow=True)
    assert every[-1] == "ranged"
    assert roles.roles_for(TRIO, bow=None) == every
    assert roles.roles_for(TRIO, bow=False) == roles.roles_for(TRIO) == every[:-1]
    assert roles.roles_for(("RNG", "BER", "BRD"), bow=False) == ["melee"]
    for trio in (("WAR", "CLR", "WIZ"), ("MNK", "BST", "BER")):  # (no Ranger: never there)
        assert roles.roles_for(trio, bow=True) == roles.roles_for(trio, bow=False) == roles.roles_for(trio)


def test_a_profile_of_the_ranged_role_for_a_pool_with_no_bow_is_refused_and_with_a_bow_plays_the_bow():
    with pytest.raises(ValueError, match="not offered"):
        make_profile("HUM", TRIO, 50, "ranged", None, None, TABLES, items=[])
    with pytest.raises(ValueError, match="not offered"):
        make_profile("HUM", TRIO, 50, "ranged", None, None, TABLES, items=[bow("it-bow", 30, 40, classes=("ROG",))])
    with_bow = make_profile("HUM", TRIO, 50, "ranged", None, None, TABLES, items=[bow("it-bow", 30, 40)])
    assert with_bow.setups == ("ranged",) or list(with_bow.setups) == ["ranged"]
    with pytest.raises(ValueError, match="not offered"):
        make_profile("HUM", TRIO, 50, "ranged", None, None, TABLES)  # (no pool, no bow)
    # the other roles of the trio do not care that the role is not offered
    assert "ranged" not in make_profile("HUM", TRIO, 50, "tank", None, None, TABLES, items=[]).setups


# ---- the Range place is filled in the bow setup ----------------------------------------------------------------------------


def test_the_range_place_of_the_bow_setup_is_filled_when_damage_is_worth_nothing():
    low, high = bow("it-low", 20, 40), bow("it-high", 33, 40)  # no stats: they are worth nothing but the damage
    ring = make_item("it-ring", {"FINGER"}, stats={"HP": 30})
    for weights in ({"HP": 1, "DMG": 0}, {"HP": 1}):
        solution, _ = best([low, high, ring], "ranged", weights=weights)
        assert len(worn(solution, "RANGE")) == 1, weights  # a bow, though it adds nothing to the value
        assert worn(solution, "RANGE")[0] in ("it-low", "it-high")
        assert "it-ring" in worn(solution, "FINGER")
    # with damage worth something the better bow is the one
    solution, _ = best([low, high, ring], "ranged")
    assert worn(solution, "RANGE") == ["it-high"]


def test_only_the_bow_setup_has_the_row_that_fills_the_range_place():
    low = bow("it-low", 20, 40)
    ring = make_item("it-ring", {"FINGER"}, stats={"HP": 30})
    for setup in ("stick", "2h", "dw", "1h-shield"):
        _, milp = best([low, ring], setup, weights={"HP": 1, "DMG": 0})
        assert "range.bow" not in milp.row_names, setup
    _, milp = best([low, ring], "ranged", weights={"HP": 1, "DMG": 0})
    assert "range.bow" in milp.row_names


def test_the_builder_refuses_the_bow_setup_with_no_bow_to_fill_the_range_place():
    ring = make_item("it-ring", {"FINGER"}, stats={"HP": 30})
    charm = make_item("it-charm", {"RANGE"}, stats={"HP": 30})
    for pool in ([ring], [ring, charm]):
        with pytest.raises(ValueError, match="bow"):
            build_milp(profile(), pool, "ranged", None, BuildOptions(any_rule="explicit", haste_assumed=0))


def test_the_space_of_kits_has_a_bow_in_the_range_place_of_every_kit_of_the_bow_setup():
    from solver_helpers import Instance

    items = [bow("it-a", 30, 40), bow("it-b", 20, 30), make_item("it-ring", {"FINGER"}, stats={"HP": 12})]
    inst = Instance(
        label="ranged", profile=profile(weights={"HP": 1, "DMG": 0}), items=items, setup="ranged", buffset=None, haste_assumed=0, any_rule="explicit"
    )
    space = Space(inst)
    place = space.group_names.index("RANGE")
    assert len(space.kits) > 0 and all(len(space.options[place][combo[place]]) == 1 for combo in space.kits)
    # and the export's own enumeration (the family that the browser's engine is held to) is the same
    from trioforge.export import brute

    mine = brute.Space(brute.ranged_instance(__import__("random").Random(5), trio_index=0))
    gi = mine.group_names.index("RANGE")
    assert all(len(mine.options[gi][combo[gi]]) == 1 for combo in mine.kits)


# ---- the Ranged template is a rule of differences ---------------------------------------------------------------------------


def test_the_ranged_template_is_two_factors_applied_to_the_melee_template():
    value = RULES.get("roles.ranged_template")
    assert set(value) == {"DEX", "AC"} and value["DEX"] > 1 and 0 < value["AC"] < 1
    assert RULES.seal("roles.ranged_template") == "model"
    assert RULES.seal("roles.ranged_template") == RULES.seal("roles.templates")  # (the page code cites it with the seal of the templates: the two must say the same)
    rule = next(rule for rule in RAW["rules"] if rule["id"] == "roles.ranged_template")
    assert "judgment" in rule["notes"].lower() and "melee" in rule["notes"].lower()
    melee = roles.weights_for(TRIO, "melee", RULES)
    ranged = roles.weights_for(TRIO, "ranged", RULES)
    assert ranged["DEX"] == pytest.approx(melee["DEX"] * value["DEX"]) and ranged["AC"] == pytest.approx(melee["AC"] * value["AC"])
    for key in melee:
        if key not in ("DEX", "AC"):
            assert ranged[key] == melee[key], key


def test_a_change_to_the_melee_template_carries_over_to_the_ranged_one():
    data = copy.deepcopy(RAW)
    row = next(rule for rule in data["rules"] if rule["id"] == "roles.templates")
    row["value"]["melee"]["ATK"] = 7
    row["value"]["melee"]["DEX"] = 1.0
    changed = Rules(data)
    melee, ranged = roles.weights_for(TRIO, "melee", changed), roles.weights_for(TRIO, "ranged", changed)
    assert ranged["ATK"] == melee["ATK"] == 7 * 1  # (the weight of the stat, as the template says it)
    factor = changed.get("roles.ranged_template")["DEX"]
    assert ranged["DEX"] == pytest.approx(1.0 * factor)
    assert ranged["DMG"] == melee["DMG"]  # the damage weight is the rule times the template's ATK: the Ranged one follows the Melee ATK


def test_the_effects_layer_reads_the_ranged_role_with_the_derived_template():
    from trioforge.effects import judgment

    template = judgment.Judgment.from_rules(RULES).templates["ranged"] if hasattr(judgment.Judgment, "from_rules") else None
    if template is not None:
        melee = RULES.get("roles.templates")["melee"]
        assert template["DEX"] == pytest.approx(melee["DEX"] * RULES.get("roles.ranged_template")["DEX"])


# ---- an off-hand shield counts in the bow setup ----------------------------------------------------------------------------


def test_an_off_hand_shield_counts_in_the_bow_setup_and_raises_the_soft_cap_as_in_the_shield_setup():
    shield = make_item("it-shield", {"SECONDARY"}, stats={"AC": 40, "HP": 5}, shield=True)
    body = make_item("it-body", {"CHEST"}, stats={"AC": 700})  # far past the soft cap
    arrows = bow("it-bow", 20, 40)
    weights = {"HP": 1, "AC": 1, "DMG": 600}
    with_shield = kit_of(secondary=shield, chest=body, range=arrows)
    without = kit_of(chest=body, range=arrows)
    for prof in (profile(weights=weights), profile(weights=weights, softcap=(F(100), F(1, 4)))):
        shown = {setup: evaluate(prof, with_shield, setup=setup, haste_assumed=0).parts for setup in ("1h-shield", "ranged")}
        assert shown["ranged"]["AC"] == shown["1h-shield"]["AC"] and shown["ranged"]["EVASION"] == shown["1h-shield"]["EVASION"]
        bare = evaluate(prof, without, setup="ranged", haste_assumed=0).parts
        assert shown["ranged"]["AC"] > bare["AC"]  # the shield's armor class counts, and in the soft cap's Y as well
    # a shield in an Any place is no off-hand shield, in the bow setup as in every other
    stray = kit_of(any=shield, chest=body, range=arrows)
    assert evaluate(profile(weights=weights), stray, setup="ranged", haste_assumed=0).parts["AC"] == evaluate(profile(weights=weights), stray, setup="1h-shield", haste_assumed=0).parts["AC"]
    assert evaluate(profile(weights=weights), stray, setup="ranged", haste_assumed=0).parts["AC"] <= evaluate(profile(weights=weights), with_shield, setup="ranged", haste_assumed=0).parts["AC"]


def test_the_solve_of_the_bow_setup_wears_the_shield_for_its_armor_class():
    shield = make_item("it-shield", {"SECONDARY"}, stats={"AC": 40}, shield=True)
    sword = make_item("it-sword", {"SECONDARY"}, stats={"AC": 1}, weapon=WeaponVec("1H Slashing", 20, 30, None, False))
    arrows = bow("it-bow", 20, 40)
    weights = {"AC": 5, "DMG": 600}
    ranged, _ = best([shield, sword, arrows], "ranged", weights=weights)
    assert worn(ranged, "SECONDARY") == ["it-shield"] and worn(ranged, "RANGE") == ["it-bow"]
    shielded, _ = best([shield, sword, arrows], "1h-shield", weights=weights)
    assert worn(shielded, "SECONDARY") == ["it-shield"]
    assert ranged.breakdown.parts["AC"] == shielded.breakdown.parts["AC"]
