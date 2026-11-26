"""The ranged weapon setup ("Bow") and the Ranged role.

A trio that can use a bow gets a weapon setup in which the Range place must hold a bow and the bow's damage is scored by the
measure a main hand is scored by (the damage plus the bonus, over the delay, at the haste the kit counts), times the rule
``weapons.ranged_factor``. The main hand and the off hand are scored on stats alone there, as in the stat stick. A trio with a
Ranger also gets a role, Ranged, whose template is a rule of its own and whose only setup is the bow. A trio with no class that
can use a bow gets nothing new. Arrows are not counted: a kit has no ammo place.

Every item, bow and name here is invented; the classes, the trios and the skill name are public game terms.
"""

from __future__ import annotations

import itertools
import json
from fractions import Fraction as F
from pathlib import Path
from types import SimpleNamespace

import pytest

from solver_helpers import Space, legal, make_item
from trioforge.classes import CLASS_CODES
from trioforge.model import formulas as fm
from trioforge.model import roles, weapons
from trioforge.model.formulas import EvalProfile, PoolSpec, evaluate
from trioforge.model.items import SLOT_INSTANCES, WeaponVec
from trioforge.model.profile import Profile, make_profile
from trioforge.model.tables import load
from trioforge.rules import load as load_rules
from trioforge.solver.haste import solve_scenario
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.prune import fit_groups, prune
from trioforge.solver.solve import solve

REPO = Path(__file__).resolve().parents[2]
TABLES = load()
RULES = load_rules()
RAW = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))

#: the classes that may use a bow in the catalog (a test of the real catalog below says so); a trio of the others has no bow class
BOW_CLASSES = {"WAR", "PAL", "RNG", "SHD", "ROG"}
NO_BOW = sorted(set(CLASS_CODES) - BOW_CLASSES)
POOLS = {
    "HP": (PoolSpec("RNG", 1500, 5.0), PoolSpec("CLR", 1320, 4.4), PoolSpec("ENC", 1200, 4.0)),
    "MANA": (PoolSpec("CLR", 900, 4.5, "WIS"), PoolSpec("ENC", 900, 4.5, "INT")),
    "END": (PoolSpec("RNG", 900, 4.5), PoolSpec("CLR", 456, 3.25), PoolSpec("ENC", 260, 1.25)),
}
NAKED = {k: 100 for k in "STR STA AGI DEX WIS INT CHA".split()}
EXPLICIT = BuildOptions(any_rule="explicit")


def bow(key, dmg, delay, *, bonus=None, classes=("RNG",), stats=None, tier=0, slots=("RANGE",)):
    return make_item(key, slots, stats=stats, classes=classes, weapon=WeaponVec("Archery", dmg, delay, bonus, False), tier=tier)


def profile(**changes):
    base = dict(level=50, naked=NAKED, weights={"HP": 1, "DMG": 600}, pools=POOLS)
    base.update(changes)
    return EvalProfile(**base)


def kit_of(**places):
    kit = [None] * len(SLOT_INSTANCES)
    for place, item in places.items():
        kit[SLOT_INSTANCES.index(place.upper())] = item
    return kit


def ranged_template():
    """The weights of the Ranged template: the Melee template (as the rules have it) with the factors of ``roles.ranged_template`` on some of its weights."""
    factors = RULES.get("roles.ranged_template")
    return {key: value * factors.get(key, 1) for key, value in RULES.get("roles.templates")["melee"].items()}


def worn(solution, place):
    return sorted(item.key for item, name in zip(solution.kit, SLOT_INSTANCES) if item is not None and name == place)


# ---- the rules ------------------------------------------------------------------------------------------------------


def test_the_ranged_factor_is_a_model_judgment_that_starts_at_one():
    assert RULES.get("weapons.ranged_factor") == 1.0
    assert RULES.seal("weapons.ranged_factor") == "model"
    assert RULES.sources("weapons.ranged_factor") == [{"kind": "public-text", "ref": "TrioForge judgment"}]
    rule = next(rule for rule in RAW["rules"] if rule["id"] == "weapons.ranged_factor")
    assert "judgment" in rule["notes"].lower()  # plain words: it is a judgment, not a measure


def test_the_ranged_template_is_a_melee_template_with_more_dexterity_and_less_armor_class():
    factors = RULES.get("roles.ranged_template")
    melee = RULES.get("roles.templates")["melee"]
    assert RULES.seal("roles.ranged_template") == "model"
    assert set(factors) == {"DEX", "AC"} and factors["DEX"] > 1 and factors["AC"] < 1  # (a rule of differences from the Melee template: test_ranged_round2)
    template = roles.weights_for(("RNG", "WAR", "CLR"), "ranged", RULES)
    assert template["DEX"] == pytest.approx(melee["DEX"] * factors["DEX"]) and template["AC"] == pytest.approx(melee["AC"] * factors["AC"])
    assert RULES.get("roles.templates").keys() == set(roles.TEMPLATES)  # the other builds are not re-weighted (the Archer has no template of its own)


# ---- the vocabulary -------------------------------------------------------------------------------------------------


def test_the_new_setup_name_comes_last_and_the_archer_is_a_build_among_the_builds():
    assert weapons.SETUPS == ("1h-shield", "2h", "dw", "stick", "ranged")
    assert weapons.ROLES == roles.ROLES == ("tank", "shield", "melee", "ranged", "castertank", "caster")
    assert fm.SETUPS == (None, *weapons.SETUPS)


# ---- which setups, which roles --------------------------------------------------------------------------------------


def tables():
    return SimpleNamespace(skillcap={}, rules=RULES)


def with_skills(*classes):
    # (the classes of the catalog's bows have the Archery skill, as the client's skill caps say: test_ranged_round2 holds the real table to it)
    caps = {
        (code, skill, 50): 100
        for code in classes
        for skill in (*weapons.ONE_HANDED_SKILLS, *weapons.TWO_HANDED_SKILLS, "Dual Wield", *(["Archery"] if code in BOW_CLASSES else []))
    }
    return SimpleNamespace(skillcap=caps, rules=RULES)


def test_a_bow_a_class_of_the_trio_may_equip_offers_the_setup_to_tank_and_melee_damage_not_to_the_casting_builds():
    pool = [bow("it-bow", 30, 40, classes=("RNG",))]
    trio = ("RNG", "CLR", "WAR")
    table = with_skills(*trio)
    for role in ("tank", "melee"):
        setups = weapons.setups_for(trio, role, table, level=50, items=pool)
        assert setups[-1] == "ranged", role
        assert setups[:-1] == weapons.setups_for(trio, role, table, level=50, items=[]), role  # the rest as it was
    assert roles.roles_for(trio, bow=True) == ["tank", "shield", "melee", "ranged"]  # (the casting builds this trio is offered: the Shield caster)
    assert weapons.setups_for(trio, "shield", table, level=50, items=pool) == ["stick"]  # (no shield in this pool: the stick alone)
    casters = ("RNG", "CLR", "DRU")  # no tank class and two spell classes: the Caster tank and the Caster
    assert [role for role in roles.roles_for(casters, bow=True) if role in ("castertank", "caster")] == ["castertank", "caster"]
    for role in ("castertank", "caster"):
        assert weapons.setups_for(casters, role, with_skills(*casters), level=50, items=pool) == ["stick"], role
    assert weapons.setups_for(trio, "ranged", table, level=50, items=pool) == ["ranged"]


@pytest.mark.parametrize(
    "pool",
    [
        pytest.param([], id="no items"),
        pytest.param([bow("it-bow", 30, 40, classes=("ROG",))], id="a bow of a class the trio lacks"),
        pytest.param([make_item("it-spear", {"RANGE"}, classes=("RNG",), weapon=WeaponVec("Throwing", 9, 30, None, False))], id="a thrown weapon"),
        pytest.param([make_item("it-charm", {"RANGE"}, classes=("RNG",), stats={"HP": 40})], id="a stat item"),
        pytest.param([make_item("it-arrow", {"AMMO"}, classes=("RNG",), weapon=None)], id="ammunition"),
    ],
)
def test_without_a_bow_for_the_trio_there_is_no_ranged_setup(pool):
    trio = ("RNG", "CLR", "WAR")
    for role in (role for role in roles.roles_for(trio, bow=None) if role != "ranged"):  # (the builds the trio is offered)
        assert "ranged" not in weapons.setups_for(trio, role, with_skills(*trio), level=50, items=pool)


def test_with_no_pool_to_read_there_is_no_ranged_setup_for_the_other_roles():
    trio = ("RNG", "CLR", "WAR")
    for role in (role for role in roles.roles_for(trio, bow=None) if role != "ranged"):  # (a bow is never assumed, a shield is: not for the Archer either, which has no setup then: test_ranged_round4.py)
        assert "ranged" not in weapons.setups_for(trio, role, with_skills(*trio), level=50), role
    assert weapons.setups_for(trio, "ranged", with_skills(*trio), level=50) == []


def test_the_ranged_role_has_no_setup_when_its_pool_has_no_bow():
    trio = ("RNG", "CLR", "WAR")
    assert weapons.setups_for(trio, "ranged", with_skills(*trio), level=50, items=[]) == []  # (it plays the bow and nothing else: it is not offered for that pool)


@pytest.mark.parametrize("trio", list(itertools.combinations(NO_BOW, 3))[:40])
def test_a_trio_with_no_bow_class_gets_no_new_setup_whatever_the_pool_holds(trio):
    everything = [bow("it-bow", 30, 40, classes=tuple(BOW_CLASSES)), bow("it-all", 30, 40, classes=("ALL",))]
    # (a bow listed for ALL classes is a bow every class may equip; the catalog lists none, so this is the one place a bow may reach
    # a trio with no bow class, and it is held apart below)
    pool = everything[:1]
    for role in roles.roles_for(trio, bow=None):  # (the builds the trio is offered: it has no Ranger, so no Archer)
        assert "ranged" not in weapons.setups_for(trio, role, with_skills(*trio), level=50, items=pool)


def test_roles_for_offers_ranged_exactly_to_a_trio_with_a_ranger_and_all_the_others_as_they_were():
    for trio in itertools.combinations(CLASS_CODES, 3):
        offered = roles.roles_for(trio, bow=True)  # (given a pool with a bow: with no pool no trio has it, as before)
        was = roles.roles_for(trio, bow=False)
        assert "ranged" not in was, trio
        if "RNG" in trio:
            assert offered == [role for role in roles.ROLES if role in (*was, "ranged")], trio  # (in the order of the builds: after Melee damage)
        else:
            assert offered == was, trio
        assert roles.roles_for(trio) == was, trio


def test_a_ranger_trio_with_one_build_still_gets_the_archer_build():
    assert roles.roles_for(("RNG", "BER", "BRD"), bow=True) == ["melee", "ranged"]


# ---- the weights ----------------------------------------------------------------------------------------------------


def test_the_ranged_role_weighs_the_rule_s_template_and_scores_the_bow_as_a_melee_main_hand():
    trio = ("RNG", "WAR", "CLR")
    weights = roles.weights_for(trio, "ranged", RULES)
    template = ranged_template()
    for key in ("HP", "AC", "ATK", "DEX", "HASTE", "END", "CHA"):
        assert weights[key] == pytest.approx(template[key])
    assert weights["SV_FIRE"] == pytest.approx(template["SV"])
    assert weights["DMG"] == pytest.approx(RULES.get("weapons.damage_weight") * template["ATK"])
    assert weights["DEX"] > roles.weights_for(trio, "melee", RULES)["DEX"]
    assert weights["AC"] < roles.weights_for(trio, "melee", RULES)["AC"]


def test_the_other_builds_keep_their_weights_and_none_of_them_takes_the_ranged_template_in():
    trio = ("RNG", "WAR", "CLR")
    for name in ("tank", "shield", "melee"):
        template = RULES.get("roles.templates")[name]
        for key in ("HP", "AC", "DEX", "ATK", "HASTE"):
            assert roles.weights_for(trio, name, RULES)[key] == pytest.approx(template[key]), (name, key)


def test_the_ranged_role_is_refused_to_a_trio_with_no_ranger():
    with pytest.raises(ValueError, match="not offered"):
        roles.weights_for(("WAR", "CLR", "ROG"), "ranged", RULES)


# ---- the measure of a bow -------------------------------------------------------------------------------------------


def test_a_bow_in_the_range_place_scores_its_own_damage_per_delay_times_the_factor():
    # (the third round: a bow gets no main-hand bonus; test_ranged_round3.py holds the whole measure)
    arrows = bow("it-bow", 33, 44)
    for haste in (0, 25, 75):
        own = F(33, 44) * (1 + F(haste, 100))
        assert weapons.damage_index_exact(arrows, "range", "ranged", haste, ranged_factor=1) == own
        assert weapons.damage_index_exact(arrows, "range", "ranged", haste, ranged_factor=F(3, 4)) == own * F(3, 4)
    assert weapons.damage_index_exact(arrows, "range", "ranged", 0) == F(33, 44)  # no bonus, listed or not
    assert weapons.damage_index_exact(bow("it-b", 20, 40, bonus=9), "range", "ranged", 0) == F(20, 40)


def test_the_factor_comes_from_the_rules_unless_given():
    arrows = bow("it-bow", 20, 40)
    assert weapons.damage_index_exact(arrows, "range", "ranged", 0, RULES) == F(20, 40)
    doubled = SimpleNamespace(get=lambda name, level=50: 2.0 if name == "weapons.ranged_factor" else RULES.get(name, level))
    assert weapons.damage_index_exact(arrows, "range", "ranged", 0, doubled) == F(40, 40)


def test_in_the_ranged_setup_the_hands_score_nothing_and_in_the_others_the_range_place_scores_nothing():
    sword = make_item("it-sword", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("1H Slashing", 20, 30, None, False))
    arrows = bow("it-bow", 20, 40)
    for hand in ("primary", "secondary"):
        assert weapons.damage_index_exact(sword, hand, "ranged", 10) == 0
        assert weapons.damage_index_exact(arrows, hand, "ranged", 10) == 0
    for setup in ("1h-shield", "2h", "dw", "stick"):
        assert weapons.damage_index_exact(arrows, "range", setup, 10) == 0


def test_a_bow_with_more_damage_per_delay_scores_more():
    slow, quick = bow("it-slow", 40, 100), bow("it-quick", 20, 30)  # 0.4 against 0.667 a delay unit, whatever the damage
    assert weapons.damage_index_exact(quick, "range", "ranged", 0) > weapons.damage_index_exact(slow, "range", "ranged", 0)


def test_the_hands_of_the_ranged_setup_take_any_item_but_the_range_place_takes_only_a_bow():
    sword = make_item("it-sword", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("1H Slashing", 20, 30, None, False))
    two = make_item("it-axe", {"PRIMARY"}, weapon=WeaponVec("2H Slashing", 30, 40, None, True))
    orb = make_item("it-orb", {"PRIMARY", "SECONDARY", "RANGE"}, stats={"HP": 10})
    arrows = bow("it-bow", 20, 40)
    spear = make_item("it-spear", {"RANGE"}, weapon=WeaponVec("Throwing", 9, 30, None, False))
    assert weapons.allowed_in_hand(sword, "primary", "ranged") and weapons.allowed_in_hand(sword, "secondary", "ranged")
    assert weapons.allowed_in_hand(orb, "primary", "ranged") and weapons.allowed_in_hand(orb, "secondary", "ranged")
    assert weapons.allowed_in_hand(two, "primary", "ranged") and not weapons.allowed_in_hand(two, "secondary", "ranged")
    assert weapons.allowed_in_hand(arrows, "range", "ranged")
    assert not weapons.allowed_in_hand(orb, "range", "ranged")
    assert not weapons.allowed_in_hand(spear, "range", "ranged")
    assert not weapons.allowed_in_hand(sword, "range", "ranged")
    for setup in ("1h-shield", "2h", "dw", "stick"):
        assert weapons.allowed_in_hand(orb, "range", setup) and weapons.allowed_in_hand(spear, "range", setup)


def test_a_skill_named_in_any_case_is_a_bow_and_a_bow_that_is_no_range_item_is_not():
    assert weapons.is_bow(bow("it-a", 10, 30))
    assert weapons.is_bow(make_item("it-b", {"RANGE"}, weapon=WeaponVec("archery", 10, 30, None, False)))
    assert not weapons.is_bow(make_item("it-c", {"PRIMARY"}, weapon=WeaponVec("Archery", 10, 30, None, False)))
    assert not weapons.is_bow(make_item("it-d", {"RANGE"}, weapon=WeaponVec("Archery", 0, 30, None, False)))
    assert not weapons.is_bow(make_item("it-e", {"RANGE"}, weapon=None))


# ---- the evaluator --------------------------------------------------------------------------------------------------


def test_the_evaluator_scores_the_bow_in_the_range_place_and_nothing_else_under_the_ranged_setup():
    arrows = bow("it-bow", 20, 40)
    sword = make_item("it-sword", {"PRIMARY"}, weapon=WeaponVec("1H Slashing", 40, 30, None, False))
    kit = kit_of(range=arrows, primary=sword)
    prof = profile()
    index = F(20, 40) * (1 + F(20, 100))
    assert evaluate(prof, kit, setup="ranged", haste_assumed=20).parts["WEAPON"] == 600 * index
    assert evaluate(prof, kit, setup="stick", haste_assumed=20).parts["WEAPON"] == 0
    assert evaluate(prof, kit, setup="2h", haste_assumed=20).parts["WEAPON"] == 0  # no two-hander: the sword and the range place score nothing
    assert evaluate(profile(ranged_factor=2), kit, setup="ranged", haste_assumed=20).parts["WEAPON"] == 1200 * index
    # a sword in the Range place is not a bow
    odd = kit_of(range=make_item("it-sw", {"RANGE"}, weapon=WeaponVec("1H Slashing", 40, 30, None, False)))
    assert evaluate(prof, odd, setup="ranged", haste_assumed=20).parts["WEAPON"] == 0


def test_the_other_setups_score_a_range_place_bow_nothing():
    kit = kit_of(range=bow("it-bow", 20, 40))
    for setup in (None, "1h-shield", "2h", "dw", "stick"):
        assert evaluate(profile(), kit, setup=setup, haste_assumed=20).parts["WEAPON"] == 0


def test_the_weapon_term_of_a_ranged_kit_rises_with_the_haste_the_kit_counts():
    from trioforge.model.formulas import evaluate_truthful

    boots = make_item("it-boots", {"FEET"}, haste=30)
    kit = kit_of(range=bow("it-bow", 20, 40), feet=boots)
    prof = profile(weights={"DMG": 600, "HASTE": 0})
    plain = evaluate_truthful(prof, kit, setup="ranged").parts["WEAPON"]
    assert plain == 600 * F(20, 40) * F(130, 100)  # the kit counts the 30 its boots give


# ---- the profile ----------------------------------------------------------------------------------------------------


def test_a_profile_carries_the_factor_and_reads_it_back():
    prof = make_profile("HUM", ("RNG", "WAR", "CLR"), 50, "ranged", None, None, TABLES, items=[bow("it-bow", 20, 40)])
    assert prof.ranged_factor == 1 and prof.role == "ranged" and prof.setups == ("ranged",)
    assert Profile.from_json(prof.to_json()) == prof
    assert prof.to_dict()["ranged_factor"] == 1
    assert prof.eval_profile.ranged_factor == 1
    assert prof.weights["DMG"] == pytest.approx(RULES.get("weapons.damage_weight") * ranged_template()["ATK"] * RULES.get("roles.weapon_factor")["ranged"])


def test_the_tank_profile_of_a_ranger_trio_gets_the_ranged_setup_when_the_pool_has_a_bow():
    trio = ("RNG", "WAR", "CLR")
    items = [bow("it-bow", 20, 40, classes=("RNG",))]
    with_bow = make_profile("HUM", trio, 50, "tank", None, None, TABLES, items=items)
    without = make_profile("HUM", trio, 50, "tank", None, None, TABLES, items=[])
    assert with_bow.setups[-1] == "ranged" and with_bow.setups[:-1] == without.setups
    assert with_bow.weights == without.weights


def test_a_bow_a_race_cannot_wear_does_not_make_the_setup():
    trio = ("RNG", "WAR", "CLR")
    narrow = bow("it-bow", 20, 40, classes=("RNG",))
    narrow = type(narrow)(**{**narrow.__dict__, "races": frozenset({"OGR"})})
    assert "ranged" in make_profile("OGR", trio, 50, "tank", None, None, TABLES, items=[narrow]).setups
    assert "ranged" not in make_profile("HUM", trio, 50, "tank", None, None, TABLES, items=[narrow]).setups


TABLES = load()


# ---- the builder and the solver -------------------------------------------------------------------------------------


def best(items, setup, **changes):
    prof = profile(**changes)
    milp = build_milp(prof, items, setup, None, BuildOptions(any_rule="explicit", haste_assumed=0))
    return solve(milp), milp


def test_in_the_ranged_setup_the_range_place_holds_only_a_bow_and_the_bow_is_chosen_for_its_damage():
    stat = make_item("it-charm", {"RANGE"}, stats={"HP": 120}, classes=("RNG",))
    low, high = bow("it-low", 20, 40, stats={"HP": 10}), bow("it-high", 33, 40, stats={"HP": 10})
    pool = [stat, low, high]
    solution, milp = best(pool, "ranged")
    assert worn(solution, "RANGE") == ["it-high"]
    assert {group for (group, key) in milp.index} >= {"RANGE"}
    assert not any(key == "it-charm" for (group, key) in milp.index if group == "RANGE")  # it has no column there
    # in the other setups the stat item wins the place, as it always did: the bow's damage is not scored
    for setup in ("stick", "2h", "dw", "1h-shield"):
        other, _ = best(pool, setup)
        assert worn(other, "RANGE") == ["it-charm"], setup


def test_a_bow_with_more_damage_per_delay_wins_over_one_with_less_all_else_equal():
    slow = bow("it-slow", 45, 100)  # more damage, 0.45 a delay unit
    quick = bow("it-quick", 24, 40)  # less damage, 0.6 a delay unit
    solution, _ = best([slow, quick], "ranged")
    assert worn(solution, "RANGE") == ["it-quick"]
    # and the other way round when the order of the measure is the other way round
    solution, _ = best([bow("it-slow", 45, 60), bow("it-quick", 24, 60)], "ranged")
    assert worn(solution, "RANGE") == ["it-slow"]


def test_a_stat_bow_can_beat_a_damage_bow_when_the_stats_are_worth_more_than_the_damage():
    damage = bow("it-damage", 40, 40)
    stats = bow("it-stats", 36, 40, stats={"HP": 2000})
    solution, _ = best([damage, stats], "ranged")
    assert worn(solution, "RANGE") == ["it-stats"]


def test_the_hands_and_the_any_places_of_the_ranged_setup_are_chosen_for_stats():
    sword = make_item("it-sword", {"PRIMARY", "SECONDARY"}, stats={"HP": 10}, weapon=WeaponVec("1H Slashing", 80, 20, None, False))
    plain = make_item("it-plain", {"PRIMARY", "SECONDARY"}, stats={"HP": 50}, weapon=WeaponVec("1H Slashing", 1, 90, None, False))
    solution, _ = best([sword, plain, bow("it-bow", 20, 40)], "ranged")
    assert worn(solution, "PRIMARY") == ["it-plain"] and worn(solution, "SECONDARY") == ["it-plain"]  # the swordsman's damage is not scored
    assert worn(solution, "RANGE") == ["it-bow"]


def test_the_value_of_the_solve_is_the_evaluators_and_the_kit_is_legal():
    items = [
        bow("it-bow", 30, 40, stats={"HP": 5}), bow("it-bow2", 26, 30),
        make_item("it-sword", {"PRIMARY", "SECONDARY"}, stats={"HP": 20}, weapon=WeaponVec("1H Slashing", 18, 30, None, False)),
        make_item("it-axe", {"PRIMARY"}, stats={"HP": 40}, weapon=WeaponVec("2H Slashing", 30, 50, None, True)),
    ]
    solution, milp = best(items, "ranged", haste_cap=75, buff_totals={"HASTE": 20})
    assert solution.status == "optimal"
    again = evaluate(milp.profile, list(solution.kit), None, setup="ranged", haste_assumed=milp.haste_assumed)
    assert float(again.F) == pytest.approx(solution.F, rel=1e-9)
    groups = {}
    for name, item in zip(SLOT_INSTANCES, solution.kit):
        if item is not None:
            groups.setdefault(name, []).append(item)
    assert legal(groups, "ranged")


def test_the_truthful_solve_pays_the_bow_the_haste_the_kit_counts():
    boots = make_item("it-boots", {"FEET"}, haste=30)
    bows = [bow("it-bow", 20, 40, stats={"HP": 3})]
    prof = profile(weights={"HP": 1, "DMG": 600}, haste_cap=75)
    solved = solve_scenario(prof, [*bows, boots], "ranged", None, EXPLICIT)
    assert worn(solved.solution, "FEET") == ["it-boots"]  # the boots are worth 600 x 0.75 x 0.3 to the bow, and cost nothing
    assert solved.solution.F == pytest.approx(float(evaluate(prof, list(solved.solution.kit), None, setup="ranged", haste_assumed=30).F), rel=1e-9)


def test_a_ranged_program_has_the_hand_rules_of_the_stick():
    items = [
        make_item("it-axe", {"PRIMARY"}, stats={"HP": 1}, weapon=WeaponVec("2H Slashing", 30, 50, None, True)),
        make_item("it-orb", {"SECONDARY"}, stats={"HP": 1}),
        bow("it-bow", 20, 40),
    ]
    stick = build_milp(profile(), items, "stick", None, EXPLICIT)
    ranged = build_milp(profile(), items, "ranged", None, EXPLICIT)
    assert [name for name in ranged.row_names if name != "range.bow"] == stick.row_names  # the two-hander row, the groups: the same, and the row that fills the range place
    assert sorted(stick.index) == sorted(ranged.index)


def test_the_pruning_keeps_what_a_best_kit_needs_in_the_ranged_setup():
    items = [
        bow("it-a", 30, 40), bow("it-b", 30, 40, stats={"HP": 4}), bow("it-c", 20, 40, stats={"HP": 9}), bow("it-d", 10, 40),
        make_item("it-sword", {"PRIMARY"}, stats={"HP": 5}),
    ]
    prof = profile()
    kept = prune(items, prof, 0, "ranged", None, BuildOptions(any_rule="explicit", haste_assumed=0))
    full, _ = best(items, "ranged")
    pruned, _ = best(list(kept), "ranged")
    assert pruned.F == pytest.approx(full.F, rel=1e-12)
    keys = {item.key for item in kept}
    assert "it-d" not in keys and "it-b" in keys  # a bow with fewer stats and less damage than another is dropped; one with more is kept
    charm = make_item("it-charm", {"RANGE"}, stats={"HP": 3})
    assert fit_groups(items[0], "ranged", "explicit") == {"RANGE"}
    assert fit_groups(charm, "ranged", "explicit") == frozenset()
    assert fit_groups(charm, "stick", "explicit") == {"RANGE"}
    assert fit_groups(charm, "ranged") == {"ANY"}  # a stat item still stands in an Any place, where it scores no damage


def test_a_scenario_of_a_trio_with_no_bow_is_what_it_was(monkeypatch):
    """A trio whose classes cannot use a bow gets no new setup and no new role, so nothing in its grid changes."""
    trio = ("CLR", "SHM", "DRU")
    pool = [bow("it-bow", 30, 40, classes=("RNG",))]
    for role in roles.roles_for(trio):
        before = make_profile("HUM", trio, 50, role, None, None, TABLES, items=[])
        after = make_profile("HUM", trio, 50, role, None, None, TABLES, items=pool)
        assert before.setups == after.setups and before.weights == after.weights


def test_the_space_of_kits_agrees_with_the_builder_on_a_small_ranged_instance():
    from solver_helpers import Instance, check_instance

    items = [
        bow("it-a", 30, 40, stats={"HP": 6}), bow("it-b", 20, 30, stats={"HP": 30}),
        make_item("it-sword", {"PRIMARY", "SECONDARY"}, stats={"HP": 10}, weapon=WeaponVec("1H Slashing", 18, 30, None, False)),
        make_item("it-ring", {"FINGER"}, stats={"HP": 12}),
    ]
    trio = ("RNG", "WAR", "CLR")
    prof = EvalProfile(level=50, naked=NAKED, weights={"HP": 1, "DMG": 300, "HASTE": 0.5}, pools=POOLS, haste_cap=75, ranged_factor=F(3, 4))
    inst = Instance(label="ranged", profile=prof, items=items, setup="ranged", buffset=None, haste_assumed=25, any_rule="explicit")
    result = check_instance(inst)
    assert result.ok, result.message
    assert Space(inst).best()[0] > 0


def test_a_spare_bow_in_an_any_place_does_not_take_the_range_place_from_the_damage_bow():
    """A bow is a stat stick in an Any place (the Any rule lets any item with a slot stand there), where it scores no damage. The canonical placement puts
    the items that are not in a hand into the earliest group that has a column for them, by key: for a bow that is the range place, which would give it to the
    spare bow whose key comes first. The range place is arranged with the hands under the bow setup, so the damage bow keeps it, in both solvers."""
    from trioforge.solver.solve import solve_canonical

    damage = bow("it-z-damage", 40, 40, stats={"HP": 1})
    spare = bow("it-a-spare", 10, 100, stats={"HP": 300})
    milp = build_milp(profile(), [damage, spare], "ranged", None, BuildOptions(haste_assumed=0))
    for solver in (solve, solve_canonical):
        solution = solver(milp)
        assert worn(solution, "RANGE") == ["it-z-damage"] and worn(solution, "ANY") == ["it-a-spare", "it-a-spare"], solver.__name__  # (a copy in each Any place: it is no Lore item)
        again = evaluate(milp.profile, list(solution.kit), None, setup="ranged", haste_assumed=0)
        assert float(again.F) == pytest.approx(solution.F, rel=1e-12)


def test_the_placement_test_sees_the_fault_it_guards_against(monkeypatch):
    """With the range place left out of the arranged places (the rule as it was for the hands alone) the spare bow, whose key comes first, takes the range place."""
    from trioforge.solver import solve as solve_module

    monkeypatch.setattr(solve_module, "_arranged", lambda milp: solve_module.HAND_GROUPS)
    damage = bow("it-z-damage", 40, 40, stats={"HP": 1})
    spare = bow("it-a-spare", 10, 100, stats={"HP": 300})
    milp = build_milp(profile(), [damage, spare], "ranged", None, BuildOptions(haste_assumed=0))
    try:
        solution = solve(milp)
    except Exception:  # noqa: BLE001 - the exact evaluator refuses a kit worth less than the model's: that is the fault seen
        return
    assert worn(solution, "RANGE") != ["it-z-damage"]


def test_the_effects_layer_reads_the_ranged_role_as_a_melee_role_with_the_ranged_template():
    """The exalt file of a trio is made for every role it is offered, so the layer must know the new one: a Ranger is a melee class, and the mana and attack weights of the
    role come from its own template."""
    from trioforge.effects import judgment, layer

    j = judgment.default()
    classes = ["RNG", "CLR", "WIZ"]
    off = j.score_shape["off_role_class"]
    assert layer.role_weights("ranged", classes, j) == {"RNG": 1.0, "CLR": off, "WIZ": off} == layer.role_weights("melee", classes, j)
    template = ranged_template()
    spell_factor, mana, attack = layer.role_rel("ranged", classes, j)
    most_mana, most_attack = max(row["MANA"] for row in j.templates.values()), max(row["ATK"] for row in j.templates.values())
    assert (mana, attack) == (template["MANA"] / most_mana, template["ATK"] / most_attack)  # (a share of the largest of the templates of the rules)
    for kind in ("heal", "damage", "slow"):
        assert j.relevance_of(kind, "ranged", classes, {"tank": frozenset(), "melee": frozenset(), "caster": frozenset()}) == j.relevance_of(kind, "melee", classes, {})
