"""Five rule changes of 2026-10-22 (branch p7rules), each held by hand-worked numbers.

* weapon damage grows 10 percent of the base a tier with no minimum step (``tier.weapon_damage_pct``; 5 stays the alternative);
* weight falls 9 percent of the base a tier with no minimum step, to the floor (``tier.weight_pct``, ``tier.weight_floor``);
* Unbound Alacrity gives a trio with a Monk 10 haste on top of the spell haste and the best worn haste (``haste.unbound_alacrity``);
* the dual-wield factor is 0.83 for a trio with a Monk and 0.69 without (``weapons.dual_wield_factor``);
* a two-hander with no damage bonus listed gets 0.67 x min(delay, 50), a one-hander 0.5 x delay.

The numbers are written out by hand, so these tests do not trust the modules they check. Every item is invented.
"""

import dataclasses
import json
from fractions import Fraction

import pytest

from trioforge import rules as rules_module
from trioforge.model import formulas, weapons
from trioforge.model.formulas import weapon_index
from trioforge.model.items import SLOT_INSTANCES, ItemVec, WeaponVec, at_tier
from trioforge.model.profile import make_profile
from trioforge.model.tables import load

F = Fraction
TABLES = load()
RULES = TABLES.rules


def catalog_item(**changes):
    base = {
        "key": "w9001", "name": "Invented Thing", "slots": ["PRIMARY"], "classes": ["ALL"], "races": ["ALL"], "deity": None,
        "flags": [], "stats": {}, "sv": {}, "weight": 1.0, "item_type": None, "weapon": None,
    }  # fmt: skip
    base.update(changes)
    return base


def weapon_item(dmg, delay=30, bonus=None, skill="1H Slashing"):
    return catalog_item(weapon={"skill": skill, "dmg": dmg, "delay": delay, "bonus": bonus})


def rules_with(**changes):
    data = json.loads(rules_module.RULES_PATH.read_text(encoding="utf-8"))
    for rule in data["rules"]:
        if rule["id"] in changes:
            rule["value"] = changes[rule["id"]]
    return rules_module.Rules(data)


# ---- 1. weapon damage: 10 percent of the base a tier, no minimum ---------------------------------------------------


def test_the_weapon_rule_is_ten_percent_and_active_with_five_as_the_alternative():
    assert RULES.get("tier.weapon_damage_pct") == 10
    rule = next(r for r in json.loads(rules_module.RULES_PATH.read_text(encoding="utf-8"))["rules"] if r["id"] == "tier.weapon_damage_pct")
    assert rule["status"] == "active" and rule["date"] == "2026-10-22"
    assert [alternative["value"] for alternative in rule["alternatives"]] == [5]
    assert {entry["ref"] for entry in rule["source"]} >= {
        "https://xm2514-svg.github.io/sites/item-upgrades/", "https://eqlwiki.com/index.php/Item_Upgrade_System",
    }  # fmt: skip


@pytest.mark.parametrize("tier, expected", [(0, 6), (1, 6), (2, 7), (3, 7), (4, 8), (5, 9), (10, 12)])
def test_a_flaming_fist_of_six_reads_eight_at_plus_four_and_nine_at_plus_five(tier, expected):
    assert at_tier(weapon_item(6), tier, RULES).weapon.dmg == expected


def test_a_weapon_of_three_gains_nothing_until_the_percent_adds_up_to_a_point():
    got = [at_tier(weapon_item(3), n, RULES).weapon.dmg for n in range(11)]
    assert got == [3, 3, 3, 3, 4, 4, 4, 5, 5, 5, 6]


def test_the_five_percent_alternative_has_no_minimum_step_either():
    got = [at_tier(weapon_item(3), n, RULES, weapon_pct=5).weapon.dmg for n in range(11)]
    assert got == [3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4]  # 3 * n * 5 // 100 is 1 from +7 on (105 // 100)
    assert at_tier(weapon_item(20), 4, RULES, weapon_pct=5).weapon.dmg == 24


@pytest.mark.parametrize("dmg, tier, expected", [(20, 1, 22), (45, 3, 58), (100, 10, 200), (7, 5, 10)])
def test_weapon_damage_is_the_base_plus_the_ten_percent_rounded_down(dmg, tier, expected):
    assert at_tier(weapon_item(dmg), tier, RULES).weapon.dmg == dmg + dmg * tier * 10 // 100 == expected


def test_delay_and_the_listed_bonus_still_do_not_change():
    vec = at_tier(weapon_item(30, delay=44, bonus=20), 7, RULES)
    assert (vec.weapon.delay, vec.weapon.bonus) == (44, 20)


# ---- 2. weight: 9 percent of the base a tier, no minimum step ---------------------------------------------------------


def test_the_weight_rule_is_nine_percent_with_the_floor_unchanged():
    assert RULES.get("tier.weight_pct") == 9 and RULES.get("tier.weight_floor") == 0.1
    rule = next(r for r in json.loads(rules_module.RULES_PATH.read_text(encoding="utf-8"))["rules"] if r["id"] == "tier.weight_pct")
    assert (rule["status"], rule["date"]) == ("active", "2026-11-09")  # (was 2026-10-22: in-game readings now back the rule)


@pytest.mark.parametrize(
    "weight, tier, expected",
    [(1.9, 0, 19), (1.9, 1, 18), (1.0, 4, 7), (0.2, 5, 2), (1.0, 10, 1), (3.5, 10, 4), (0.1, 10, 1), (7.3, 4, 47), (5.0, 3, 37)],
)
def test_the_weight_in_tenths_falls_nine_percent_of_the_base_a_tier(weight, tier, expected):
    assert at_tier(catalog_item(weight=weight), tier, RULES).weight10 == expected


def test_weightless_and_unknown_weights_are_as_before():
    assert at_tier(catalog_item(weight=0), 6, RULES).weight10 == 0
    unknown = at_tier(catalog_item(weight=None), 6, RULES)
    assert (unknown.weight10, unknown.weight_known) == (10, False)


# ---- 3. Unbound Alacrity ----------------------------------------------------------------------------------------------

MNK_TRIO = ("PAL", "MNK", "BER")
PLAIN_TRIO = ("WAR", "ROG", "BER")


def vec(key="h", haste=0, weight10=1, weapon=None, slots=("HEAD",)):
    return ItemVec(
        key=key, name=key, slots=frozenset(slots), classes=frozenset(), deity=None, lore=False, stats={}, sv={}, haste=haste,
        weight10=weight10, weapon=weapon, is_shield=False, tier=0,
    )  # fmt: skip


def kit_with_haste(worn):
    kit = [None] * len(SLOT_INSTANCES)
    if worn:
        kit[SLOT_INSTANCES.index("HEAD")] = vec(haste=worn)
    return kit


def profile_of(trio, **kw):
    return make_profile("HUM", trio, 50, "melee", None, None, TABLES, RULES, **kw)


def counted(trio, spell=0, worn=0):
    prof = profile_of(trio)
    result = formulas.evaluate(dataclasses.replace(prof.eval_profile, weights={"HASTE": 1}), kit_with_haste(worn), {"HASTE": spell})
    return result.totals["haste"]["counted"], result.parts["HASTE"]


def test_the_rule_says_ten_haste_and_ten_more_cap():
    assert RULES.get("haste.unbound_alacrity") == "adds 10 haste and raises the cap by 10"
    assert RULES.get("haste.cap_pct_with_monk") == 85 and RULES.get("haste.cap_pct") == 75


def test_a_trio_with_a_monk_counts_ten_haste_with_nothing_else():
    assert counted(MNK_TRIO) == (10, 10)


def test_unbound_alacrity_stacks_with_the_spell_haste_and_the_best_worn_piece_up_to_the_cap():
    assert counted(MNK_TRIO, spell=45, worn=40)[0] == 85  # min(85, 10 + 45 + 40)
    assert counted(MNK_TRIO, spell=20, worn=30)[0] == 60  # 10 + 20 + 30
    assert counted(MNK_TRIO, spell=0, worn=25)[0] == 35
    assert counted(MNK_TRIO, spell=90, worn=0)[0] == 85  # a spell haste past the cap is cut to it


def test_a_trio_without_a_monk_is_unchanged():
    assert counted(PLAIN_TRIO) == (0, 0)
    assert counted(PLAIN_TRIO, spell=45, worn=40)[0] == 75  # min(75, 85)
    assert counted(PLAIN_TRIO, spell=20, worn=30)[0] == 50


def test_the_profile_carries_the_haste_the_weapon_term_assumes():
    mnk, plain = profile_of(MNK_TRIO), profile_of(PLAIN_TRIO)
    assert (mnk.haste_bonus, plain.haste_bonus) == (10, 0)
    assert (mnk.spell_haste, plain.spell_haste) == (10, 0)
    assert weapons.haste_assumed(mnk, []) == 10
    assert weapons.haste_assumed(mnk, [vec(haste=40)]) == 50
    assert weapons.haste_assumed(plain, [vec(haste=40)]) == 40


def test_a_rules_file_that_says_something_else_about_unbound_alacrity_is_refused():
    with pytest.raises(ValueError, match="haste.unbound_alacrity"):
        profile_of_rules = rules_with(**{"haste.unbound_alacrity": "raises the cap only"})
        make_profile("HUM", MNK_TRIO, 50, "melee", None, None, TABLES, profile_of_rules)


# ---- 4. the dual-wield factor by trio ---------------------------------------------------------------------------------


def test_the_rule_holds_both_factors_and_stays_open():
    rule = next(r for r in json.loads(rules_module.RULES_PATH.read_text(encoding="utf-8"))["rules"] if r["id"] == "weapons.dual_wield_factor")
    assert rule["value"] == {"with_monk": 0.83, "without_monk": 0.69}
    assert (rule["status"], rule["date"]) == ("open", "2026-10-22")
    assert rule["source"] == [{"kind": "url", "ref": "https://eqlwiki.com/Skill_Dual_Wield"}]
    assert "working model" in rule["notes"] and "252" in rule["notes"] and "210" in rule["notes"]


def test_a_trio_with_a_monk_gets_point_eight_three_and_one_without_point_six_nine():
    assert profile_of(MNK_TRIO).dw_factor == 0.83
    assert profile_of(PLAIN_TRIO).dw_factor == 0.69
    assert profile_of(("WAR", "MNK", "ROG")).dw_factor == 0.83
    assert profile_of(("SHD", "CLR", "SHM")).dw_factor == 0.69
    assert profile_of(MNK_TRIO).eval_profile.dw_factor == F(83, 100)
    assert profile_of(PLAIN_TRIO).eval_profile.dw_factor == F(69, 100)


def test_a_single_number_in_the_rule_still_applies_to_every_trio():
    rules = rules_with(**{"weapons.dual_wield_factor": 0.5})
    assert make_profile("HUM", MNK_TRIO, 50, "melee", None, None, TABLES, rules).dw_factor == 0.5
    assert make_profile("HUM", PLAIN_TRIO, 50, "melee", None, None, TABLES, rules).dw_factor == 0.5


def test_a_rule_with_a_value_for_each_trio_needs_the_factor_to_be_named_in_the_weapon_index():
    w = weapon_vec_item(20, 30)
    with pytest.raises(ValueError, match="dual_wield_factor"):
        weapons.damage_index_exact(w, "secondary", "dw", 0, RULES)
    assert weapons.damage_index_exact(w, "secondary", "dw", 0, RULES, dw_factor=F(83, 100)) == F(20, 30) * F(83, 100)


# ---- 5. the damage bonus of a two-hander with none listed ---------------------------------------------------------------


def weapon_vec_item(dmg, delay, bonus=None, two_handed=False):
    weapon = WeaponVec("2H Slashing" if two_handed else "1H Slashing", dmg, delay, bonus, two_handed)
    return vec(key="w", weapon=weapon, slots=("PRIMARY", "SECONDARY"))


def test_a_two_hander_with_no_bonus_listed_gets_067_of_the_delay_capped_at_50():
    long = weapon_vec_item(40, 60, two_handed=True)
    short = weapon_vec_item(40, 40, two_handed=True)
    assert weapons.damage_index_exact(long, "primary", "2h", 0) == (40 + F(67, 100) * 50) / 60
    assert weapons.damage_index_exact(short, "primary", "2h", 0) == (40 + F(67, 100) * 40) / 40
    assert weapon_index(long.weapon, "PRIMARY", "2h", 0, 1) == (40 + F(67, 100) * 50) / 60
    assert weapon_index(short.weapon, "PRIMARY", "2h", 0, 1) == (40 + F(67, 100) * 40) / 40


def test_the_cap_of_50_is_inclusive_and_a_listed_bonus_is_not_capped():
    edge = weapon_vec_item(40, 50, two_handed=True)
    assert weapons.damage_index_exact(edge, "primary", "2h", 0) == (40 + F(67, 100) * 50) / 50
    listed = weapon_vec_item(40, 60, bonus=33, two_handed=True)
    assert weapons.damage_index_exact(listed, "primary", "2h", 0) == F(40 + 33, 60)


def test_a_one_hander_keeps_half_the_delay_whatever_the_delay():
    slow = weapon_vec_item(10, 80)
    assert weapons.damage_index_exact(slow, "primary", "dw", 0) == (10 + F(1, 2) * 80) / 80
    assert weapon_index(slow.weapon, "PRIMARY", "dw", 0, 1) == (10 + F(1, 2) * 80) / 80
