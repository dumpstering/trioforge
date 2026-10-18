"""Tests of the legacy-profile compatibility layer: ``trioforge.solver.compat`` and the two options it needs from the
exact model (``LegacyTerms`` for the evaluator and ``BuildOptions.legacy`` for the builder).

The old tools described a character as a JSON profile (weights, explicit attribute curves, a character-sheet armor
class, caps, weapon setups with fixed hand items and tokens) and a pool of items in an older shape, and scored a kit as
the *gain* over the naked character with the same buffs. ``from_legacy`` maps such a profile, a pool and a scenario onto
what ``build_milp`` accepts; the private regression runs the real old profile through it. Here everything is synthetic:

* the legacy objective is written out again in plain floats (``compat_helpers.Oracle``) and every legal assignment of a
  small pool is enumerated under the old rules (``compat_helpers.best_gain``); the MILP's optimum must equal the best
  gain within 1e-9 relative, on hand-made scenarios and on seeded random ones;
* the pieces that do not need a solve (tier rules of the old views, the eligibility filter, the hand tokens, the
  refusals) are checked on their own.

Every name, item and number is invented.
"""

import dataclasses
import random
from copy import deepcopy
from fractions import Fraction

import pytest

from compat_helpers import PROFILE, best_gain, legacy_item, pool_json, small_pool, sword
from compat_random import random_case
from trioforge.model import formulas as fm
from trioforge.model.formulas import EvalProfile, LegacyCurve, LegacySheet, LegacyTerms, PoolSpec, evaluate
from trioforge.model.items import SLOT_INSTANCES, ItemVec, WeaponVec
from trioforge.solver import compat
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.solve import solve, solve_canonical

F = Fraction
REL = 1e-9


def run(profile_json, items, scenario):
    """from_legacy, build, solve; the gain over the empty kit and the solution."""
    profile, parts, setup, buffset = compat.from_legacy(profile_json, pool_json(items), scenario)
    milp = compat.build(profile, parts, setup, buffset)
    solution = solve(milp)
    assert solution.status == "optimal"
    return compat.gain(solution, profile), solution, profile, parts


def close(got, want):
    return abs(got - want) <= REL * max(1.0, abs(want))


def scenario(**changes):
    base = {"preset": "plain", "buffs": "big", "weapons": None, "tier": 10}
    base.update(changes)
    return base


# ---- the legacy terms of the evaluator -------------------------------------------------------------------------------

DUMMY_POOLS = {"HP": (PoolSpec("WAR", 0, 0),), "MANA": (), "END": (PoolSpec("WAR", 0, 0),)}
NAKED_100 = {k: 100 for k in "STR STA AGI DEX WIS INT CHA".split()}


def eval_profile(**changes):
    base = dict(level=50, naked=NAKED_100, weights={}, pools=DUMMY_POOLS)
    base.update(changes)
    return EvalProfile(**base)


def item(key, slots, *, stats=None, sv=None, haste=0, shield=False, weapon=None, lore=False):
    return ItemVec(
        key=key,
        name=key,
        slots=frozenset(slots),
        classes=frozenset(fm.CLASS_CODES),
        deity=None,
        lore=lore,
        stats=dict(stats or {}),
        sv=dict(sv or {}),
        haste=haste,
        weight10=0,
        weapon=weapon,
        is_shield=shield,
        tier=0,
    )


def kit_of(**places):
    kit = [None] * len(SLOT_INSTANCES)
    for place, entry in places.items():
        kit[SLOT_INSTANCES.index(place)] = entry
    return kit


TERMS = LegacyTerms(
    curves=(
        LegacyCurve("STA", 5, (100, 200), (1, F(1, 2), 0)),
        LegacyCurve("WIS", F(3, 2), (50,), (1, 2)),
    ),
    sheet=LegacySheet(mult=F(4, 3), nongear=60, cap=130, ret=F(33, 100)),
)


def test_the_legacy_objective_is_flat_pools_explicit_curves_and_the_old_sheet():
    prof = eval_profile(weights={"HP": 2, "AC": 3, "MANA": 1, "ATK": 2})
    head = item("head", {"HEAD"}, stats={"AC": 30, "STA": 40, "HP": 7})
    shield = item("shield", {"SECONDARY"}, stats={"AC": 12}, shield=True)
    breakdown = evaluate(prof, kit_of(HEAD=head, SECONDARY=shield), legacy=TERMS)
    # curves: 5 x pwl(STA 140) = 5 x (100 + 40 / 2) and 1.5 x pwl(WIS 100) = 1.5 x (50 + 2 x 50)
    assert breakdown.parts["CURVES"] == 600 + F(3, 2) * 150
    assert breakdown.parts["HP"] == 2 * 7  # the pools are flat: gear and buff points only
    # sheet: X = 4/3 x (30 + 12) + 60 = 116 stays under Y = 130 + 12 = 142; the weight is 3 / (4/3) per sheet point
    assert breakdown.parts["AC"] == F(9, 4) * 116
    assert breakdown.totals["sheet"]["X"] == 116 and breakdown.totals["sheet"]["Y"] == 142
    assert breakdown.F == 600 + F(3, 2) * 150 + 14 + F(9, 4) * 116
    # none of the generated terms is there: no evasion, no strength-to-attack, no DEX proc, no Monk or Iksar bonus
    assert all(breakdown.parts[name] == 0 for name in ("EVASION", "DEX", "MONK", "IKSAR", "MANA", "END", "ATK"))


def test_the_old_sheet_keeps_a_share_of_what_passes_the_printed_cap_and_the_shield_raises_it():
    prof = eval_profile(weights={"AC": 3})
    big = item("big", {"CHEST"}, stats={"AC": 100})
    x = F(4, 3) * 100 + 60
    y = 130
    capped = F(33, 100) * x + F(67, 100) * y
    assert evaluate(prof, kit_of(CHEST=big), legacy=TERMS).parts["AC"] == F(9, 4) * capped
    # the same armor class on the off-hand shield counts in X and in Y both
    shield = item("shield", {"SECONDARY"}, stats={"AC": 100}, shield=True)
    xs, ys = F(4, 3) * 100 + 60, 130 + 100
    assert evaluate(prof, kit_of(SECONDARY=shield), legacy=TERMS).parts["AC"] == F(9, 4) * min(
        xs, F(33, 100) * xs + F(67, 100) * ys
    )
    # a shield worn in an Any place is armor like any other
    assert evaluate(prof, kit_of(ANY=shield), legacy=TERMS).parts["AC"] == F(9, 4) * capped


def test_without_the_legacy_option_nothing_changes():
    prof = eval_profile(weights={"HP": 1, "AC": 2}, softcap=(100, F(1, 3)))
    head = item("head", {"HEAD"}, stats={"AC": 30, "STA": 40, "HP": 7})
    plain = evaluate(prof, kit_of(HEAD=head))
    assert evaluate(prof, kit_of(HEAD=head), legacy=None) == plain
    assert "CURVES" not in plain.parts
    assert BuildOptions().legacy is None
    with_terms = evaluate(prof, kit_of(HEAD=head), legacy=TERMS)
    assert with_terms.parts["CURVES"] != 0 and with_terms.F != plain.F


def test_the_legacy_terms_check_their_numbers():
    with pytest.raises(ValueError, match="attribute"):
        LegacyCurve("HP", 1, (100,), (1, 0))
    with pytest.raises(ValueError, match="slope|break"):
        LegacyCurve("STA", 1, (100,), (1,))  # one slope too few
    with pytest.raises(ValueError, match="break"):
        LegacyCurve("STA", 1, (100, 100), (1, 1, 1))
    with pytest.raises(ValueError, match="negative|at least"):
        LegacyCurve("STA", -1, (100,), (1, 0))
    with pytest.raises(ValueError, match="negative|at least"):
        LegacyCurve("STA", 1, (100,), (1, -1))
    with pytest.raises(ValueError, match="mult"):
        LegacySheet(mult=0, nongear=0, cap=100, ret=F(1, 3))
    with pytest.raises(ValueError, match="ret|rate"):
        LegacySheet(mult=1, nongear=0, cap=100, ret=F(3, 2))
    with pytest.raises(TypeError):
        evaluate(eval_profile(), [None] * len(SLOT_INSTANCES), legacy={"curves": []})
    with pytest.raises(ValueError, match="sheet"):
        evaluate(eval_profile(weights={"AC": 1}), [None] * len(SLOT_INSTANCES), legacy=LegacyTerms())


def test_the_builder_refuses_legacy_terms_next_to_a_monk_or_an_iksar_bonus():
    for changes in ({"iksar_ac": 35}, {"monk": {"softcap_stones": 20, "hardcap_stones": 36, "full_bonus_ac": 73}}):
        prof = eval_profile(weights={"AC": 1}, **changes)
        with pytest.raises(ValueError, match="Monk|Iksar|legacy"):
            build_milp(prof, [item("h", {"HEAD"}, stats={"AC": 5})], "stick", None, BuildOptions(legacy=TERMS))


def test_in_legacy_mode_the_model_s_own_terms_are_absent_and_the_pools_are_flat():
    prof = eval_profile(weights={"CHA": 1, "DEX": 1, "HP": 1, "MANA": 1, "END": 1, "ATK": 1, "AC": 0})
    stats = {"CHA": 80, "DEX": 80, "STA": 50, "STR": 50, "AGI": 50, "HP": 7, "MANA": 3, "END": 5, "ATK": 2}
    items = [item("h", {"HEAD"}, stats=stats)]
    milp = build_milp(
        prof, items, "stick", None, BuildOptions(any_rule="explicit", haste_assumed=0, legacy=LegacyTerms())
    )
    solution = solve(milp)
    # no charisma, DEX, evasion or strength-to-attack term, and mana counts although the trio has no mana class
    assert solution.breakdown.F == 7 + 3 + 5 + 2
    assert milp.info["pools"] == {"HP": "legacy", "MANA": "legacy", "END": "legacy"}
    plain = build_milp(prof, items, "stick", None, BuildOptions(any_rule="explicit", haste_assumed=0))
    assert solve(plain).breakdown.F > 17 and plain.info["pools"]["MANA"] == "none"


def test_the_builder_lays_out_the_explicit_curves_and_the_sheet_exactly():
    prof = eval_profile(weights={"HP": 2, "AC": 3}, buff_totals={"HP": 10})
    items = [
        item("a", {"HEAD"}, stats={"AC": 40, "STA": 30, "HP": 5}),
        item("b", {"HEAD"}, stats={"AC": 10, "STA": 90, "WIS": 60}),
        item("s1", {"SECONDARY"}, stats={"AC": 25}, shield=True),
        item("s2", {"SECONDARY"}, stats={"AC": 5, "WIS": 20}),
    ]
    milp = build_milp(prof, items, "stick", None, BuildOptions(any_rule="explicit", legacy=TERMS, haste_assumed=0))
    solution = solve(milp)
    best = max(
        evaluate(prof, kit_of(HEAD=h, SECONDARY=s), legacy=TERMS).F
        for h in (None, *items[:2])
        for s in (None, *items[2:])
    )
    assert solution.status == "optimal" and solution.breakdown.F == best
    assert abs(solution.model_F - float(best)) <= 1e-9 * float(best)


# ---- the tier rules of the old views ---------------------------------------------------------------------------------


def views(item_json, tier, **scenario_changes):
    _, parts, _, _ = compat.from_legacy(PROFILE, pool_json([item_json]), scenario(tier=tier, **scenario_changes))
    (only,) = parts
    return only


def test_the_old_tier_rules_scale_stats_resists_and_regen_alike_and_haste_by_one_a_tier():
    base = legacy_item(
        "probe",
        ["HEAD"],
        stats={"AC": 20, "HPREG": 12, "STR": -3, "HASTE": 41, "MANA": 3, "HP": 0},
        sv={"FIRE": 15, "VOID": 9},
        wt=10.0,
    )
    top = views(base, 10)
    # 20 + max(10, 20), regen 12 + max(10, 12) (the old rule, not the flat +10 of the new tier module), -3 untouched
    assert top.stats == {"AC": 40, "HPREG": 24, "STR": -3, "MANA": 13}
    assert top.haste == 51 and top.sv == {"FIRE": 30}  # the VOID marker is no resist
    assert top.weight10 == 1 and top.tier == 10  # 100 tenths fall to the 0.1 stone floor
    mid = views(base, 4)
    assert mid.stats == {"AC": 28, "HPREG": 16, "STR": -3, "MANA": 7}
    assert mid.haste == 45 and mid.sv == {"FIRE": 21} and mid.weight10 == 60
    zero = views(base, 0)
    assert zero.stats == {"AC": 20, "HPREG": 12, "STR": -3, "MANA": 3} and zero.haste == 41 and zero.weight10 == 100


def test_a_quest_reward_takes_the_quest_tier_and_an_owned_copy_its_own_tier():
    reward = legacy_item("reward", ["HEAD"], stats={"AC": 20}, tier_rule="quest")
    assert views(reward, 10, quest_tier=6).stats == {"AC": 32} and views(reward, 10).stats == {"AC": 40}
    plain = legacy_item("plain", ["HEAD"], stats={"AC": 20})
    assert views(plain, 10, quest_tier=6).stats == {"AC": 40}
    owned = legacy_item("owned@t3", ["HEAD"], stats={"AC": 20}, base_id="owned", tier_override=3, lore=True)
    got = views(owned, 10, quest_tier=6)
    assert got.stats == {"AC": 26} and got.tier == 3 and got.key == "owned"  # Lore keys on the base item
    assert views(legacy_item("unweighed", ["HEAD"], wt=None), 10).weight_known is False


def test_a_weapon_is_a_two_hander_by_its_skill_and_a_shield_by_the_old_rule():
    sw = views(legacy_item("greatsword", ["PRIMARY"], weapon=sword("2H Slashing")), 0)
    assert sw.weapon.two_handed and sw.weapon.skill == "2H Slashing"
    assert not views(legacy_item("dagger", ["PRIMARY"], weapon=sword("Piercing")), 0).weapon.two_handed
    assert views(legacy_item("buckler", ["SECONDARY"], stats={"AC": 4}), 0).is_shield
    assert not views(legacy_item("lantern", ["SECONDARY"], stats={"HP": 4}), 0).is_shield  # no armor class
    assert not views(legacy_item("knocker", ["PRIMARY", "SECONDARY"], stats={"AC": 4}, weapon=sword()), 0).is_shield
    marked = legacy_item("marked", ["SECONDARY"], stats={"HP": 1}, shield=True)
    assert views(marked, 0).is_shield  # an explicit marker wins
    assert not views(legacy_item("unmarked", ["SECONDARY"], stats={"AC": 9}, shield=False), 0).is_shield


# ---- who may use what ------------------------------------------------------------------------------------------------


def keys_of(parts):
    return sorted(i.key for i in parts)


def test_the_pool_is_filtered_like_the_old_eligible_items():
    pool = [
        legacy_item("mine", ["HEAD"], classes=("CLR",)),
        legacy_item("everyone", ["HEAD"], classes=("ALL",)),
        legacy_item("theirs", ["HEAD"], classes=("PAL", "MNK")),
        legacy_item("short-lived", ["HEAD"], flags=("temporary", "magic")),
        legacy_item("too-high", ["HEAD"], required_level=60),
        legacy_item("just-right", ["HEAD"], required_level=50),
        legacy_item("godly", ["HEAD"], deity="Testgod"),
        legacy_item("other-godly", ["HEAD"], deity="Othergod, Testgod"),
        legacy_item("nobody", ["HEAD"], classes=()),
    ]
    unlisted = legacy_item("unlisted", ["HEAD"])
    del unlisted["classes"]  # no class list at all: anyone may wear it
    pool.append(unlisted)
    keys = lambda **extra: keys_of(compat.from_legacy(PROFILE, pool_json(pool), scenario(**extra))[1])  # noqa: E731
    # no deity chosen: nothing is locked out by a deity (the old rule), temporaries and too-high items are
    assert keys() == ["everyone", "godly", "just-right", "mine", "other-godly", "unlisted"]
    assert keys(include_temporary=True) == [
        "everyone",
        "godly",
        "just-right",
        "mine",
        "other-godly",
        "short-lived",
        "unlisted",
    ]
    assert keys(deity="Othergod") == ["everyone", "just-right", "mine", "other-godly", "unlisted"]
    assert keys(deity="testgod") == ["everyone", "godly", "just-right", "mine", "other-godly", "unlisted"]
    assert keys(exclude=["mine", "godly"]) == ["everyone", "just-right", "other-godly", "unlisted"]
    (item_,) = [
        i for i in compat.from_legacy(PROFILE, pool_json(pool), scenario(deity="Testgod"))[1] if i.key == "godly"
    ]
    assert item_.deity is None  # the builder must not lock it out again


def test_the_any_places_take_what_the_chosen_rule_says():
    pool = [
        legacy_item("helm", ["HEAD"]),
        legacy_item("blade", ["PRIMARY"], weapon=sword()),
        legacy_item("quiver", ["AMMO"]),
        legacy_item("bow", ["RANGE"]),
        legacy_item("nothing", []),
    ]
    every = {i.key: "ANY" in i.slots for i in compat.from_legacy(PROFILE, pool_json(pool), scenario())[1]}
    assert every == {"helm": True, "blade": True, "quiver": True, "bow": True, "nothing": False}
    armor = {
        i.key: "ANY" in i.slots for i in compat.from_legacy(PROFILE, pool_json(pool), scenario(any_rule="armor"))[1]
    }
    assert armor == {"helm": True, "blade": False, "quiver": False, "bow": False, "nothing": False}


def test_an_unknown_lore_flag_is_lore_unless_the_scenario_says_otherwise():
    pool = [
        legacy_item("a", ["HEAD"], lore=None),
        legacy_item("b", ["HEAD"], lore=True),
        legacy_item("c", ["HEAD"], lore=False),
    ]
    got = {i.key: i.lore for i in compat.from_legacy(PROFILE, pool_json(pool), scenario())[1]}
    assert got == {"a": True, "b": True, "c": False}
    got = {i.key: i.lore for i in compat.from_legacy(PROFILE, pool_json(pool), scenario(lore_unknown="nonlore"))[1]}
    assert got == {"a": False, "b": True, "c": False}


# ---- the weapon setups: fixed hand items and tokens ------------------------------------------------------------------


def hands(setup, pool=None):
    """(items by key, forced columns) of a setup over the small pool."""
    profile, parts, mode, buffset = compat.from_legacy(
        PROFILE, pool_json(pool or small_pool()), scenario(weapons=setup)
    )
    assert mode == "stick" and buffset is None
    return {i.key: i for i in parts}, profile.forced


def hand_slots(parts):
    return {
        key: sorted(i.slots & {"PRIMARY", "SECONDARY"})
        for key, i in parts.items()
        if i.slots & {"PRIMARY", "SECONDARY"}
    }


def test_a_setup_that_names_two_items_fixes_them_in_their_hands_and_nothing_else_fits_a_hand():
    parts, forced = hands("blade-free")  # Test Blade in the primary hand, anything in the other
    assert forced == (("PRIMARY", "blade-a"),)
    assert hand_slots(parts) == {
        "blade-a": ["PRIMARY", "SECONDARY"],
        "ward-a": ["SECONDARY"],
        "lamp-a": ["SECONDARY"],
    }
    parts, forced = hands("maul")
    assert forced == (("PRIMARY", "maul-a"),) and hand_slots(parts) == {"maul-a": ["PRIMARY"]}
    parts, forced = hands("twin")
    assert forced == (("PRIMARY", "blade-a"), ("SECONDARY", "blade-a")) and hand_slots(parts) == {
        "blade-a": ["PRIMARY", "SECONDARY"]
    }
    parts, forced = hands("held")
    assert forced == (("SECONDARY", "lamp-a"),) and hand_slots(parts) == {"lamp-a": ["SECONDARY"]}


def test_the_tokens_choose_the_candidates_of_a_hand():
    parts, forced = hands("blade-ward")  # <shield>: the off hand takes non-weapons that are not marked "not a shield"
    assert forced == (("PRIMARY", "blade-a"),)
    assert hand_slots(parts) == {"blade-a": ["PRIMARY"], "ward-a": ["SECONDARY"], "lamp-a": ["SECONDARY"]}
    parts, forced = hands("free")  # <free-1h> and <held>
    assert forced == () and hand_slots(parts) == {
        "blade-a": ["PRIMARY"],
        "ward-a": ["SECONDARY"],
        "lamp-a": ["SECONDARY"],
    }
    parts, forced = hands("free-two")
    assert forced == () and hand_slots(parts) == {"maul-a": ["PRIMARY"]}
    parts, forced = hands("free-free")  # both hands chosen: every item that fits the hand
    assert hand_slots(parts) == {
        "maul-a": ["PRIMARY"],
        "blade-a": ["PRIMARY", "SECONDARY"],
        "ward-a": ["SECONDARY"],
        "lamp-a": ["SECONDARY"],
    }
    parts, forced = hands("free-ward")  # a named off hand keeps the chosen primary hand to one-handers
    assert forced == (("SECONDARY", "ward-a"),)
    assert hand_slots(parts) == {"blade-a": ["PRIMARY"], "ward-a": ["SECONDARY"]}


def test_a_shield_marked_false_is_not_a_candidate_of_the_shield_token_but_of_the_held_token():
    pool = small_pool() + [legacy_item("charm-a", ["SECONDARY"], stats={"AC": 9}, shield=False)]
    parts, _ = hands("blade-ward", pool)
    assert "SECONDARY" not in parts["charm-a"].slots
    parts, _ = hands("free", pool)
    assert "SECONDARY" in parts["charm-a"].slots and not parts["charm-a"].is_shield


def test_no_setup_leaves_both_hands_empty():
    parts, forced = hands(None)
    assert forced == () and hand_slots(parts) == {}


def test_a_hand_item_keeps_the_places_it_has_besides_the_hands_and_the_any_places():
    pool = small_pool() + [legacy_item("neck-lamp", ["SECONDARY", "NECK"], stats={"HP": 3})]
    parts, _ = hands("held", pool)
    assert parts["neck-lamp"].slots == frozenset({"NECK", "ANY"})
    assert parts["blade-a"].slots == frozenset({"ANY"})


def test_the_refusals_of_the_old_setup_resolver_hold_here_too():
    two = deepcopy(PROFILE)
    two["weapon_setups"] = {
        "bad": ["Maul of Tests", "<held>"],
        "bad2": ["<free-2h>", "<shield>"],
        "missing": ["Nameless Blade", None],
        "lore-twice": ["Lore Blade", "Lore Blade"],
        "unknown-token": ["<free-3h>", None],
    }
    pool = small_pool() + [
        legacy_item("lore-blade", ["PRIMARY", "SECONDARY"], weapon=sword(), lore=True, name="Lore Blade")
    ]
    for name, message in (
        ("bad", "two-hander"),
        ("bad2", "empty"),
        ("missing", "Nameless Blade"),
        ("lore-twice", "Lore"),
        ("unknown-token", "token"),
    ):
        with pytest.raises(ValueError, match=message):
            compat.from_legacy(two, pool_json(pool), scenario(weapons=name))
    with pytest.raises(ValueError, match="nothing-here|setup"):
        compat.from_legacy(PROFILE, pool_json(pool), scenario(weapons="nothing-here"))
    # an excluded item cannot be named by a setup
    with pytest.raises(ValueError, match="Test Blade"):
        compat.from_legacy(PROFILE, pool_json(pool), scenario(weapons="blade-ward", exclude=["blade-a"]))


# ---- the profile -----------------------------------------------------------------------------------------------------


def mapped(profile_json=PROFILE, **changes):
    return compat.from_legacy(profile_json, pool_json(small_pool()), scenario(**changes))[0]


def test_the_profile_carries_the_old_constants_in_the_shape_the_oracle_reads():
    p = mapped()
    assert isinstance(p, EvalProfile) and p.level == 50
    assert p.naked == PROFILE["naked"]
    assert set(p.weights) <= fm.WEIGHT_KEYS  # STR, STA, AGI, WIS and INT are not model weights
    assert p.weights["AC"] == 2 and p.weights["MANA"] == F(3, 2) and p.weights["SV_MAGIC"] == F(1, 2)
    assert "CHA" not in p.weights  # charisma is a linear curve below: the model's own term is capped at 510
    (cha,) = [c for c in p.legacy.curves if c.attr == "CHA"]
    assert (cha.factor, cha.breaks, cha.slopes) == (F(1, 10), (), (1,))
    assert p.haste_cap == 75
    assert p.caps == {"regen": {"HP": 10, "MANA": 8, "END": 6}, "resist": 60}
    assert [spec.cls for spec in p.pools["HP"]] == ["WAR", "CLR", "ENC"] and p.pools["MANA"] == ()
    assert p.monk is None and p.iksar_ac == 0


def test_the_buff_set_becomes_always_on_totals_and_a_buff_resist_counts_only_where_the_profile_says_so():
    p = mapped(buffs="big")
    assert p.buff_totals["STR"] == 40 and p.buff_totals["WIS"] == 30 and p.buff_totals["STA"] == 25
    assert p.buff_totals["HASTE"] == 30 and p.buff_totals["HP"] == 200 and p.buff_totals["ATK"] == 20
    assert p.buff_totals["SV"] == {"MAGIC": 30, "FIRE": 10}
    small = mapped(buffs="small")
    assert small.buff_totals["SV"] == {} and small.buff_totals.get("HASTE", 0) == 0
    closed = deepcopy(PROFILE)
    closed["res"]["buffs_count_toward_cap"] = False
    assert mapped(closed, buffs="big").buff_totals["SV"] == {}
    # no buff set named: the first one of the profile
    assert compat.from_legacy(PROFILE, pool_json(small_pool()), {"preset": "plain"})[0].buff_totals["HASTE"] == 30


def test_the_weights_are_the_profile_over_the_preset_over_the_scenario():
    assert mapped(preset="tanky").weights["AC"] == 5 and mapped(preset="tanky").weights["HP"] == F(1, 2)
    assert mapped(preset="tanky", weights={"AC": 7}).weights["AC"] == 7
    assert mapped(preset=None).weights["AC"] == 2
    assert mapped(preset="caster").weights.get("HASTE", 0) == 0
    with pytest.raises(ValueError, match="preset"):
        mapped(preset="nonsense")
    with pytest.raises(ValueError, match="buff"):
        mapped(buffs="nonsense")


def test_the_explicit_curves_become_terms_worth_the_weight_of_their_source_times_their_scale():
    p = mapped(preset="plain")
    terms = {(c.attr, c.breaks, c.slopes): c.factor for c in p.legacy.curves}
    assert terms[("STA", (100, 200), (1, F(1, 2), 0))] == 1 * F("5.0")  # HP weight 1 x scale 5
    assert terms[("STA", (200,), (1, 0))] == F("0.3") * 2  # END weight x scale 2
    assert terms[("WIS", (100, 150, 200), (1, F(5, 2), F(5, 4), F(1, 2)))] == F(3, 2) * 4
    assert terms[("STR", (255,), (1, 0))] == 1 * F("0.5")  # ATK weight 1 x scale 0.5
    assert terms[("AGI", (255,), (1, 0))] == 2 * F("0.25")  # AC weight 2 x scale 0.25
    assert terms[("DEX", (150, 255), (1, F(1, 10), 0))] == F("0.2")  # from null: the attribute's own weight
    tanky = {(c.attr, c.breaks): c.factor for c in mapped(preset="tanky").legacy.curves}
    assert tanky[("STA", (100, 200))] == F(1, 2) * 5  # the preset's HP weight


def test_a_source_with_no_weight_adds_no_curve_and_a_curved_attribute_leaves_its_flat_weight_to_the_curve():
    zero = deepcopy(PROFILE)
    zero["presets"]["off"] = {"HP": 0, "ATK": 0}
    legacy = mapped(zero, preset="off").legacy
    assert not [c for c in legacy.curves if c.attr == "STA" and c.breaks == (100, 200)]  # the HP weight is 0
    assert not [c for c in legacy.curves if c.attr == "STR" and c.breaks == (255,)]  # and so is the ATK weight
    assert [c for c in legacy.curves if c.attr == "STA" and c.breaks == (200,)]  # the END component stays
    curved_cha = deepcopy(PROFILE)
    curved_cha["curves"]["CHA"] = {"from": None, "scale": 2, "breaks": [100], "slopes": [1, 0.5]}
    p = mapped(curved_cha)
    # the curve is worth the weight now: no second, linear charisma term next to it
    assert [(c.factor, c.breaks) for c in p.legacy.curves if c.attr == "CHA"] == [(F(1, 10) * 2, (100,))]


def test_an_attribute_with_a_weight_and_no_curve_is_worth_its_old_stat_term():
    plain = deepcopy(PROFILE)
    plain["curves"] = {}
    plain["weights"].update({"STR": 2, "DEX": 0.8, "AGI": 0.5, "STA": 1, "WIS": 0.25, "INT": 0.5})
    plain["post255"] = {"STR": 0.3}
    got = {c.attr: (c.factor, c.breaks, c.slopes) for c in mapped(plain).legacy.curves}
    assert got["STR"] == (2, (255, 510), (1, F(3, 10), 0))
    assert got["DEX"] == (F("0.8"), (255, 510), (1, F(1, 10), 0))  # the defaults: DEX 0.1, the others 0.25
    assert got["AGI"] == (F(1, 2), (255, 510), (1, F(1, 4), 0)) and got["STA"] == (1, (255, 510), (1, F(1, 4), 0))
    # WIS, INT and CHA are linear in the total, as the old lin terms were
    assert got["WIS"] == (F(1, 4), (), (1,))
    assert got["INT"] == (F(1, 2), (), (1,))
    assert got["CHA"] == (F(1, 10), (), (1,))


def test_the_sheet_of_each_armor_class_model():
    sheet = mapped().legacy.sheet
    assert (sheet.mult, sheet.nongear, sheet.cap, sheet.ret) == (F(4, 3), 90, 120, F(33, 100))
    gear = deepcopy(PROFILE)
    gear["ac"] = {"cap": 150, "cap_without_cs": 140, "ret": 0.5, "buff_share": 30}
    sheet = mapped(gear).legacy.sheet
    # the gear model is the sheet with an item multiplier of 1, nothing besides gear and the cap less the buffs' share
    assert (sheet.mult, sheet.nongear, sheet.cap, sheet.ret) == (1, 0, 120, F(1, 2))
    custom = deepcopy(PROFILE)
    custom["ac"] = {"model": "sheet", "cap": 200, "ret": 0.25, "nongear": 11.5, "mult": 1.25}
    sheet = mapped(custom).legacy.sheet
    assert (sheet.mult, sheet.nongear, sheet.cap, sheet.ret) == (F(5, 4), F(23, 2), 200, F(1, 4))


def test_the_haste_cap_is_the_profiles_number_else_75_and_the_regen_caps_default_to_none():
    capped = deepcopy(PROFILE)
    capped["haste_cap"] = 60
    assert mapped(capped).haste_cap == 60
    bare = deepcopy(PROFILE)
    bare["haste_cap"] = None
    bare["caps"] = {}
    p = mapped(bare)
    assert p.haste_cap == 75
    assert all(cap >= 10**6 for cap in p.caps["regen"].values())  # a stat without a cap stays linear


def test_what_the_profile_asks_for_and_the_exact_model_cannot_carry_is_refused():
    def refused(match, **edit):
        profile = deepcopy(PROFILE)
        for key, value in edit.items():
            profile[key] = value
        with pytest.raises(ValueError, match=match):
            compat.from_legacy(profile, pool_json(small_pool()), scenario())

    refused("Monk", monk=True, classes=["MNK", "CLR", "ENC"])
    refused(
        "per-school|cap_per_school", res={"cap": 60, "cap_per_school": {"FIRE": 30}, "buffs_count_toward_cap": False}
    )
    refused("weights", weights={})
    refused("naked", naked={"STR": 1})
    refused("classes", classes=["WAR", "CLR"])
    refused("negative|weight", weights={**PROFILE["weights"], "AC": -1})
    refused("model", ac={"model": "fancy", "cap": 100})
    with pytest.raises(ValueError, match="scenario"):
        compat.from_legacy(PROFILE, pool_json(small_pool()), scenario(colour="red"))
    with pytest.raises(ValueError, match="tier"):
        compat.from_legacy(PROFILE, pool_json(small_pool()), scenario(tier=11))


def test_the_old_resist_weight_checks_hold():
    mixed = deepcopy(PROFILE)
    mixed["weights"]["SV"] = 0.2  # the sum of all schools next to the per-school weights
    with pytest.raises(ValueError, match="SV"):
        compat.from_legacy(mixed, pool_json(small_pool()), scenario())
    summed = deepcopy(PROFILE)
    summed["weights"] = {**{k: v for k, v in PROFILE["weights"].items() if not k.startswith("SV_")}, "SV": 0.3}
    with pytest.raises(ValueError, match="SV"):  # and buffs count toward the cap only with the per-school form
        compat.from_legacy(summed, pool_json(small_pool()), scenario())
    summed["res"]["buffs_count_toward_cap"] = False
    p = mapped(summed)
    assert p.weights["SV"] == F(3, 10) and p.buff_totals["SV"] == {}


def test_a_monk_in_the_trio_with_the_flag_off_has_no_weight_bonus_and_no_wider_haste_cap():
    profile = deepcopy(PROFILE)
    profile["classes"] = ["MNK", "CLR", "ENC"]
    profile["monk"] = False
    p = mapped(profile)
    assert p.monk is None and p.haste_cap == 75


def test_build_options_pick_explicit_any_places_and_the_legacy_terms():
    p = mapped()
    options = compat.build_options(p)
    assert options.any_rule == "explicit" and options.haste_assumed == 0 and options.legacy == p.legacy
    assert isinstance(options.legacy, LegacyTerms)


def test_the_baseline_is_the_naked_character_with_the_buffs_and_no_fixed_item():
    profile, parts, setup, buffset = compat.from_legacy(PROFILE, pool_json(small_pool()), scenario(weapons="maul"))
    empty = evaluate(profile, [None] * len(SLOT_INSTANCES), setup="stick", legacy=profile.legacy).F
    assert compat.baseline(profile) == empty
    milp = compat.build(profile, parts, setup, buffset)
    assert milp.col_lb[milp.index[("PRIMARY", "maul-a")]] == 1  # the fixed weapon is worn
    solution = solve(milp)
    assert solution.kit[SLOT_INSTANCES.index("PRIMARY")].key == "maul-a"
    assert compat.gain(solution, profile) == float(solution.breakdown.F - empty)
    assert compat.gain(solution, profile) > 0


# ---- the whole path against the brute force --------------------------------------------------------------------------

SETUPS = [None, *PROFILE["weapon_setups"]]


@pytest.mark.parametrize("setup", SETUPS)
@pytest.mark.parametrize(
    ("preset", "buffs", "tier"), [("plain", "big", 10), ("tanky", "small", 4), ("caster", "big", 0)]
)
def test_the_small_pool_reproduces_the_old_gain_under_every_setup(setup, preset, buffs, tier):
    sc = scenario(preset=preset, buffs=buffs, weapons=setup, tier=tier)
    got, solution, _, _ = run(PROFILE, small_pool(), sc)
    want = best_gain(PROFILE, small_pool(), sc)
    assert want is not None and close(got, want), (got, want)
    assert abs(solution.model_F - float(solution.F)) <= 1e-9 * max(1.0, abs(solution.F))


def test_a_fixed_hand_item_is_worn_even_when_it_hurts():
    pool = small_pool()
    pool[6] = legacy_item(
        "maul-a", ["PRIMARY"], stats={"AC": -40, "STA": -30}, weapon=sword("2H Slashing", 30, 40), name="Maul of Tests"
    )
    sc = scenario(weapons="maul")
    got, solution, profile, parts = run(PROFILE, pool, sc)
    assert solution.kit[SLOT_INSTANCES.index("PRIMARY")].key == "maul-a" and close(got, best_gain(PROFILE, pool, sc))
    # unforced, the builder would leave the hurtful weapon out of the hand: the forcing is what keeps it worn
    free = solve(build_milp(profile, parts, compat.SETUP, None, compat.build_options(profile)))
    assert free.kit[SLOT_INSTANCES.index("PRIMARY")] is None and free.F > solution.F


def test_the_any_rule_the_lore_default_and_the_exclusions_reach_the_optimum():
    pool = small_pool() + [
        legacy_item("quiver-a", ["AMMO"], stats={"HP": 150}),
        legacy_item("amulet-a", ["NECK"], stats={"WIS": 40, "MANA": 30}, lore=None),
        legacy_item("amulet-b", ["NECK"], stats={"WIS": 35, "HP": 60}, lore=True),
    ]
    for rule in ("all", "armor"):
        for lore in ("lore", "nonlore"):
            sc = scenario(weapons="blade-ward", any_rule=rule, lore_unknown=lore, exclude=["stud-b"])
            got, *_ = run(PROFILE, pool, sc)
            want = best_gain(PROFILE, pool, sc)
            assert close(got, want), (rule, lore, got, want)


@pytest.mark.parametrize("seed", range(60))
def test_random_legacy_instances_reproduce_the_old_gain(seed):
    rng = random.Random(7000 + seed)
    profile, items, sc = random_case(rng)
    want = best_gain(profile, items, sc)
    assert want is not None
    got, solution, _, _ = run(profile, items, sc)
    assert close(got, want), (seed, sc, got, want)


def test_the_sweep_actually_reaches_the_awkward_cases():
    """The random instances reach rising slopes, both armor class models, fixed hands, tokens and the haste room."""
    seen = {
        "rising": 0,
        "sheet": 0,
        "gear": 0,
        "fixed": 0,
        "token": 0,
        "room0": 0,
        "capped": 0,
        "sv-sum": 0,
        "per-school": 0,
    }
    for seed in range(60):
        profile, items, sc = random_case(random.Random(7000 + seed))
        for comps in profile["curves"].values():
            for c in [comps] if isinstance(comps, dict) else comps:
                seen["rising"] += any(a < b for a, b in zip(c["slopes"], c["slopes"][1:]))
        seen["sheet" if profile["ac"].get("model") == "sheet" else "gear"] += 1
        pair = profile["weapon_setups"].get(sc["weapons"]) if sc["weapons"] else None
        if pair:
            seen["fixed"] += any(t and not t.startswith("<") for t in pair)
            seen["token"] += any(t and t.startswith("<") for t in pair)
        buffs = profile["buffs"][sc["buffs"]]
        seen["room0"] += (profile["haste_cap"] or 75) <= buffs.get("spell_haste", 0)
        seen["capped"] += bool(profile["caps"])
        seen["sv-sum" if profile["weights"].get("SV") else "per-school"] += 1
    assert all(count > 0 for count in seen.values()), seen


def test_the_canonical_solve_agrees_and_nothing_given_is_changed():
    profile_before, pool_before = deepcopy(PROFILE), pool_json(small_pool())
    sc = scenario(weapons="free-free", preset="tanky")
    parts = compat.from_legacy(PROFILE, pool_before, sc)
    solution = solve_canonical(compat.build(*parts))
    assert solution.status == "optimal" and solution.canonical
    assert close(compat.gain(solution, parts[0]), best_gain(PROFILE, small_pool(), sc))
    assert PROFILE == profile_before and pool_before == pool_json(small_pool())  # neither was touched


def test_a_pool_nobody_can_wear_is_the_empty_kit():
    got, solution, profile, _ = run(
        PROFILE, [legacy_item("alien", ["HEAD"], classes=("PAL",), stats={"HP": 99})], scenario()
    )
    assert got == 0 and all(entry is None for entry in solution.kit)
    assert solution.F == float(compat.baseline(profile))


def test_the_default_options_of_the_builder_are_untouched():
    fields = {f.name: f.default for f in dataclasses.fields(BuildOptions)}
    assert fields == {
        "any_rule": "all", "haste_assumed": None, "mutation": None, "legacy": None,
        "owned_caps": None, "new_keys": frozenset(), "max_new": None, "upgrades": None,  # the owned-item options: all off
    }
    prof = eval_profile(weights={"HP": 1})
    a = build_milp(prof, [item("h", {"HEAD"}, stats={"STA": 5})], "stick", None, BuildOptions())
    b = build_milp(prof, [item("h", {"HEAD"}, stats={"STA": 5})], "stick", None, BuildOptions(legacy=None))
    assert a.names == b.names and (a.c == b.c).all() and a.const == b.const
    assert a.info["pools"]["HP"] != "legacy"


def test_a_weapon_item_the_builder_sees_is_a_weaponvec_with_whole_numbers():
    only = views(legacy_item("odd", ["PRIMARY"], weapon={"skill": None, "dmg": None, "delay": None}), 0)
    assert isinstance(only, ItemVec) and isinstance(only.weapon, WeaponVec)
    assert (only.weapon.dmg, only.weapon.delay, only.weapon.two_handed) == (0, 0, False)
