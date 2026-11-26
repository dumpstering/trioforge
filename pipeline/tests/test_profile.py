"""Tests for the profile generator: ``trioforge.model.profile``.

A profile is everything the model needs about one scenario that is not an item: the naked stats and the buffs,
the pools of the best-two rules, the armor class model (softcap, Defense, spell AC, the Monk and Iksar bonuses),
the haste, regen and resist caps, the role weights and the weapon setups. It is a frozen, hashable record that
reads back from its own JSON, and it is accepted by the exact-formula evaluator exactly as it is.

The checks:

* **the numbers** of three trios (PAL/MNK/BER, SHD/CLR/SHM, WIZ/MAG/ENC) against the committed
  client tables, the rules file and hand arithmetic written out below;
* **the inputs that are not model rows**: the AA defaults and the evidence level are listed in the JSON;
* **the pool-selection data**: which of the best-two pool families can change their pair of classes;
* **the record itself**: immutability, one canonical text and hash for equal profiles, a strict JSON reader;
* **the evaluator**: every profile evaluates an empty kit and a small kit, and F(empty) is worked by hand.

Every item, buff and name here is invented; the races, classes and trios are public game terms.
"""

import copy
import dataclasses
import itertools
import json
from fractions import Fraction
from functools import cache
from pathlib import Path
from types import MappingProxyType

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from trioforge.classes import CLASS_CODES
from trioforge.model import formulas, roles, weapons
from trioforge.model import profile as profile_module
from trioforge.model.buffs import Buff, own_buffs, resolve
from trioforge.model.formulas import EvalProfile, PoolSpec, compile_profile, evaluate
from trioforge.model.items import SLOT_INSTANCES, ItemVec, WeaponVec
from trioforge.model.profile import HASTE_CAP_MONK_TEXT, HASTE_CAP_TEXT, Profile, eval_buffs, fixed_pools, make_profile
from trioforge.model.tables import load
from trioforge.rules import Rules

F = Fraction
REPO = Path(__file__).resolve().parents[2]
TABLES = load()
RULES = TABLES.rules
RAW = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))
PBM = ("PAL", "MNK", "BER")
SCS = ("SHD", "CLR", "SHM")
WME = ("WIZ", "MAG", "ENC")
TRIOS = [PBM, SCS, WME]


# ---- builders -------------------------------------------------------------------------------------------


@cache
def spells(level):
    return json.loads((REPO / "derived" / "client" / f"spells-l{level}.json").read_text(encoding="utf-8"))


@cache
def own_set(trio, level=50):
    return resolve(own_buffs(trio, level, spells(level), RULES), RULES)


def rules_with(**changes):
    """The real rules with the value of some rules replaced."""
    data = copy.deepcopy(RAW)
    seen = set()
    for rule in data["rules"]:
        if rule["id"] in changes:
            rule["value"] = changes[rule["id"]]
            seen.add(rule["id"])
    assert seen == set(changes), "a rule id that the real file does not have"
    return Rules(data)


def tables_with(**changes):
    return dataclasses.replace(TABLES, **changes)


def build(race="OGR", trio=PBM, role=None, level=50, buffset="own", aa=None, tables=TABLES, rules=None, **kw):
    """A profile; ``buffset="own"`` is the trio's own buffs from the committed spell file; ``role`` None is the first build the trio is offered."""
    if isinstance(buffset, str):
        buffset = own_set(tuple(trio), level)
    return make_profile(race, trio, level, role or roles.roles_for(trio)[0], buffset, aa, tables, rules, **kw)


def fx(slot, spa, value):
    return {
        "slot": slot, "spa": spa, "name": str(spa), "base": value, "limit": 0, "formula": 100, "max": value,
        "value": value,
    }  # fmt: skip


SPA = {"AC": 1, "STR": 4, "HASTE": 11, "MANAREG": 15, "FIRE": 46, "HP": 69, "MANA": 97}


def buff(sid, name, effects):
    """A permanent buff from invented effects ``(slot, name, value)``."""
    return Buff.from_spell(
        {
            "id": sid, "name": name, "classes": {"WIZ": 1}, "target": 6, "duration_ticks": None, "permanent": True,
            "effects": [fx(slot, SPA[what], value) for slot, what, value in effects], "stacking": [],
        }
    )  # fmt: skip


def vec(key="i1", stats=None, sv=None, haste=0, weight10=1, weapon=None, shield=False, slots=("ANY",)):
    """An ItemVec with invented contents; tier 0."""
    return ItemVec(
        key=key, name=key, slots=frozenset(slots), classes=frozenset(CLASS_CODES), deity=None, lore=False,
        stats=dict(stats or {}), sv=dict(sv or {}), haste=haste, weight10=weight10, weapon=weapon, is_shield=shield,
        tier=0,
    )  # fmt: skip


def kit_of(*placed):
    """A kit list from ``(slot group, item)`` pairs; a paired group fills its first free place."""
    kit = [None] * len(SLOT_INSTANCES)
    for slot, item in placed:
        index = next(i for i, name in enumerate(SLOT_INSTANCES) if name == slot and kit[i] is None)
        kit[index] = item
    return kit


SWORD = WeaponVec("1H Slashing", 20, 30, None, False)
SMALL_KIT = kit_of(
    ("HEAD", vec("helm-a", {"AC": 20, "STA": 10, "HP": 30}, weight10=20, slots=("HEAD",))),
    ("CHEST", vec("vest-a", {"AC": 40, "STR": 10, "WIS": 8, "INT": 8}, {"FIRE": 10}, haste=10, weight10=50)),
    ("FINGER", vec("ring-a", {"DEX": 5, "AGI": 5, "HPREG": 2}, weight10=1)),
    ("PRIMARY", vec("blade-a", {"STR": 3}, weapon=SWORD, weight10=30, slots=("PRIMARY",))),
    ("SECONDARY", vec("guard-a", {"AC": 12}, shield=True, weight10=40, slots=("SECONDARY",))),
)


# ---- the numbers of the three trios ----------------------------------------------------------------------


def test_naked_stats_are_the_race_base_plus_the_three_class_modifiers():
    # an Ogre SHD/CLR/SHM: the same golden as the evaluator's
    assert dict(build("OGR", SCS).naked) == {"STR": 145, "STA": 152, "AGI": 70, "DEX": 70, "WIS": 97, "INT": 70, "CHA": 47}
    assert dict(build("OGR", PBM).naked) == {"STR": 160, "STA": 142, "AGI": 80, "DEX": 90, "WIS": 72, "INT": 60, "CHA": 47}
    for trio in TRIOS:
        assert dict(build("TRL", trio).naked) == formulas.naked("TRL", trio, TABLES)


def test_the_weights_are_the_role_weights_and_there_is_no_blend():
    assert build("OGR", PBM, "tank").weights["AC"] == 12
    assert build("OGR", PBM, "melee").weights["AC"] == 1.5
    with pytest.raises(ValueError, match="role"):
        build("OGR", PBM, "balanced")  # (the build of an earlier release, which no longer exists)
    for trio in TRIOS:
        for role in roles.roles_for(trio):
            assert dict(build("OGR", trio, role).weights) == roles.weights_for(trio, role, RULES)


def test_a_trio_with_no_mana_class_has_no_mana_pool_and_no_mana_weight():
    p = build("HUM", ("WAR", "MNK", "ROG"))
    assert p.pools["MANA"] == ()
    assert p.weights["MANA"] == 0 and p.weights["MANAREG"] == 0
    assert build("HUM", PBM).pools["MANA"] != ()


def test_the_berserker_stance_is_the_melee_builds_of_a_trio_with_a_berserker_and_of_no_other():
    """T8: the swing-speed factor 2.1 and no AGI in mitigation or evasion, for the builds the rule names (the Melee damage build), in a trio that has a Berserker."""
    assert RULES.get("stance.berserker") == {"swing_factor": 2.1, "agi_counts": False, "builds": ["melee"]}
    stanced = build("OGR", PBM, "melee")
    assert dict(stanced.stance) == {"agi_share": 0, "swing_factor": 2.1}
    assert build("OGR", PBM, "tank").stance is None  # (the Tank is not in the list of builds)
    assert build("HUM", ("WAR", "MNK", "ROG"), "melee").stance is None  # (no Berserker in the trio)
    assert build("OGR", PBM, "melee", rules=rules_with(**{"stance.berserker": {"swing_factor": 2.1, "agi_counts": False, "builds": ["tank", "melee"]}})).stance is not None
    assert build("OGR", PBM, "tank", rules=rules_with(**{"stance.berserker": {"swing_factor": 2.1, "agi_counts": False, "builds": ["tank", "melee"]}})).stance is not None
    assert build("OGR", PBM, "melee", rules=rules_with(**{"stance.berserker": {"swing_factor": 1, "agi_counts": True, "builds": []}})).stance is None


@pytest.mark.parametrize("value", [2.1, "2.1", {"swing_factor": 0, "agi_counts": False, "builds": ["melee"]}, {"swing_factor": 2.1, "agi_counts": 0, "builds": ["melee"]}, {"swing_factor": 2.1, "agi_counts": False, "builds": ["wizard"]}, {"swing_factor": 2.1, "agi_counts": False}])
def test_a_stance_rule_the_model_does_not_implement_is_refused(value):
    with pytest.raises(ValueError, match="stance.berserker"):
        build("OGR", PBM, "melee", rules=rules_with(**{"stance.berserker": value}))


def test_the_haste_cap_is_75_and_85_with_a_monk_at_level_50_as_it_was_and_follows_the_level():
    """T7: the cap has a level dimension; at level 50, the level of today, no result changes (75, and 85 with a Monk); the level 55 tables use 85 (95 with a Monk)."""
    assert build("OGR", PBM).haste_cap == 85
    assert build("HUM", ("WAR", "MNK", "ROG")).haste_cap == 85
    assert build("OGR", SCS).haste_cap == 75
    assert build("OGR", WME).haste_cap == 75
    assert build("OGR", PBM, level=55).haste_cap == 95 and build("OGR", SCS, level=55).haste_cap == 85
    assert RULES.get("haste.cap_pct") == HASTE_CAP_TEXT and RULES.get("haste.cap_pct_with_monk") == HASTE_CAP_MONK_TEXT


@pytest.mark.parametrize(
    ("level", "cap"),
    [(1, 55), (20, 55), (30, 55), (31, 56), (40, 65), (49, 74), (50, 75), (51, 85), (55, 85), (59, 85), (60, 100), (65, 100), (99, 100)],
)
def test_the_haste_cap_has_a_level_dimension(level, cap):
    """T7: max(level, 30) + 25 up to level 50, 85 for levels 51 to 59, 100 from level 60 (the game client's own calculation)."""
    assert formulas.haste_cap_at(level) == cap


@pytest.mark.parametrize("level", [0, -1, 50.0, "50", None, True])
def test_the_haste_cap_asks_for_a_whole_level(level):
    with pytest.raises(ValueError, match="level"):
        formulas.haste_cap_at(level)


@pytest.mark.parametrize("rule", ["haste.cap_pct", "haste.cap_pct_with_monk"])
@pytest.mark.parametrize("value", [75, 85, "100 from level 60", ""])
def test_a_haste_cap_the_model_does_not_implement_is_refused(rule, value):
    with pytest.raises(ValueError, match=rule):
        build(rules=rules_with(**{rule: value}))


def test_only_the_iksar_has_racial_armor_class():
    assert build("IKS", PBM).iksar_ac == 35
    assert build("IKS", SCS).iksar_ac == 35
    for race in ("OGR", "HUM", "TRL", "ERU"):
        assert build(race, PBM).iksar_ac == 0
    assert build("IKS", PBM, level=55).iksar_ac == 35


def test_the_racial_and_monk_bonuses_reach_the_value_of_an_empty_kit_at_the_sheet_point_weight():
    per_point = F(str(build("OGR", PBM, "tank").weights["AC"])) / F(4, 3)  # 12 / (4/3) = 9
    top = "on top of the capped sheet AC (bypasses the softcap), valued per sheet point"
    on_top = rules_with(**{"monk.bonus_placement": top, "race.iksar_ac_placement": top})
    plain = evaluate(build("OGR", PBM, rules=on_top), kit_of())
    assert plain.totals["sheet"]["monk_bonus"] == 73  # an empty kit weighs nothing: the full bonus
    assert plain.parts["MONK"] == per_point * 73
    assert plain.parts["IKSAR"] == 0
    iksar = evaluate(build("IKS", PBM, rules=on_top), kit_of())
    assert iksar.parts["IKSAR"] == per_point * 35
    assert evaluate(build("OGR", SCS, rules=on_top), kit_of()).parts["MONK"] == 0  # no Monk, no bonus
    # T3: as the rules have them (inside X before the cap) the two bonuses are in the sheet value, and the parts that sit on top are empty
    inside = evaluate(build("IKS", PBM), kit_of())
    assert inside.totals["sheet"]["monk_bonus"] == 73 and inside.totals["sheet"]["iksar"] == 35
    assert inside.parts["MONK"] == 0 and inside.parts["IKSAR"] == 0
    assert inside.totals["sheet"]["X"] - evaluate(build("IKS", PBM, rules=on_top), kit_of()).totals["sheet"]["X"] == 73 + 35


# ---- the AA defaults and the evidence level: inputs that are not model rows -----------------------------------


def test_the_default_aas_are_combat_stability_3_of_3_and_physical_enhancement_for_melee_trios():
    for trio in (PBM, SCS):
        p = build("OGR", trio)
        assert (p.cs_pct, p.pe_pct) == (10, 2)
        assert dict(p.aa) == {"combat_stability": 3, "natural_durability": 4, "physical_enhancement": True}


def test_an_all_caster_trio_has_no_physical_enhancement_until_test_b10():
    p = build("HUM", WME)
    assert (p.cs_pct, p.pe_pct) == (10, 0)
    assert dict(p.aa) == {"combat_stability": 3, "natural_durability": 4, "physical_enhancement": False}
    assert RULES.get("ac.softcap.pe_for_caster_only_trios") is False


def test_every_all_caster_trio_is_without_physical_enhancement_and_every_other_trio_has_it():
    caster_only = [t for t in itertools.combinations(CLASS_CODES, 3) if set(t) <= roles.CASTER_CLASSES]
    assert len(caster_only) == 35  # C(7, 3) trios of seven casting classes
    for trio in caster_only:
        assert build("HUM", trio, buffset=None).pe_pct == 0
    assert build("HUM", ("CLR", "DRU", "MNK"), buffset=None).pe_pct == 2


def test_the_rule_for_caster_only_trios_decides_their_default():
    rules = rules_with(**{"ac.softcap.pe_for_caster_only_trios": True})
    p = build("HUM", WME, rules=rules)
    assert p.pe_pct == 2 and dict(p.aa) == {"combat_stability": 3, "natural_durability": 4, "physical_enhancement": True}


def test_the_aa_argument_overrides_the_defaults_and_is_listed_as_given():
    p = build("OGR", PBM, aa={"combat_stability": 2, "physical_enhancement": False})
    assert (p.cs_pct, p.pe_pct) == (5, 0)
    assert dict(p.aa) == {"combat_stability": 2, "natural_durability": 4, "physical_enhancement": False}
    assert build("OGR", PBM, aa={"combat_stability": 1}).cs_pct == 2
    assert build("OGR", PBM, aa={"combat_stability": 0}).cs_pct == 0
    assert build("OGR", PBM, aa={}).cs_pct == 10  # an empty mapping means the defaults
    assert build("HUM", WME, aa={"physical_enhancement": True}).pe_pct == 2


@pytest.mark.parametrize(
    "aa",
    [{"combat_stability": 4}, {"combat_stability": -1}, {"combat_stability": 2.5}, {"combat_stability": True},
     {"physical_enhancement": 1}, {"physical_enhancement": "yes"}, {"packrat": 3}, "default", 3],
)  # fmt: skip
def test_an_aa_choice_that_is_not_one_of_the_two_is_refused(aa):
    with pytest.raises(ValueError, match="aa"):
        build("OGR", PBM, aa=aa)


def test_the_evidence_level_is_strict_by_default_and_listed_in_the_json():
    assert build().evidence == "strict"
    assert build(evidence="wiki").evidence == "wiki"
    data = json.loads(build(evidence="wiki").to_json())
    assert data["evidence"] == "wiki" and data["aa"] == {"combat_stability": 3, "natural_durability": 4, "physical_enhancement": True}
    with pytest.raises(ValueError, match="evidence"):
        build(evidence="all")


def test_the_evidence_level_and_the_aas_change_nothing_but_themselves():
    base = build()
    other = build(evidence="wiki", aa={"combat_stability": 2, "physical_enhancement": False})
    changed = {"evidence", "aa", "cs_pct", "pe_pct"}
    for field in dataclasses.fields(Profile):
        if field.name not in changed:
            assert getattr(base, field.name) == getattr(other, field.name), field.name


def test_the_deity_is_none_by_default_so_deity_locked_items_are_left_out():
    assert build().deity is None
    assert build(deity="Marr").deity == "Marr"
    with pytest.raises(ValueError, match="deity"):
        build(deity="")


# ---- the armor class model --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trio", "level", "raw", "rate", "effective"),
    [
        (PBM, 50, 392, 0.33, 439),  # 392 x 1.12 = 439.04
        (SCS, 50, 392, 0.33, 439),
        (WME, 50, 350, 0.3, 385),  # 328 and 0.25 are under the floors (350 and 0.3): 350 x 1.10 = 385, no Physical Enhancement
        (("WAR", "CLR", "DRU"), 50, 410, 0.35, 459),  # 410 x 1.12 = 459.2
        (PBM, 55, 402, 0.33, 450),  # 402 x 1.12 = 450.24
    ],
)
def test_the_softcap_is_the_best_class_cap_and_its_rate_times_the_aas_floored(trio, level, raw, rate, effective):
    p = build("HUM", trio, level=level)
    assert tuple(p.softcap) == (raw, rate)
    assert p.effective_softcap == effective
    assert effective == int(raw * (100 + p.cs_pct + p.pe_pct) // 100)


def test_the_softcap_takes_the_best_cap_and_the_best_rate_of_the_trio_each_by_itself():
    """T2: the client takes the best cap and the best multiplier of the three classes, which can be two classes (it used to take the rate of the class with the best cap)."""
    softcap = dict(TABLES.softcap)
    softcap[("PAL", 50)], softcap[("MNK", 50)], softcap[("BER", 50)] = (400, 0.2), (380, 0.4), (390, 0.9)
    p = build(tables=tables_with(softcap=MappingProxyType(softcap)))
    assert tuple(p.softcap) == (400, 0.9)  # the cap of the Paladin, the rate of the Berserker


def test_the_softcap_is_never_below_the_floors_of_the_rules():
    """T2: a cap under ac.softcap.base_floor is read as the floor, and a rate under ac.softcap.rate_floor as the floor (a trio of casters: 328 and 0.25 become 350 and 0.3)."""
    assert RULES.get("ac.softcap.base_floor") == 350 and RULES.get("ac.softcap.rate_floor") == 0.3
    softcap = dict(TABLES.softcap)
    softcap[("PAL", 50)], softcap[("MNK", 50)], softcap[("BER", 50)] = (300, 0.1), (320, 0.2), (340, 0.29)
    low = tables_with(softcap=MappingProxyType(softcap))
    assert tuple(build(tables=low).softcap) == (350, 0.3)
    other = rules_with(**{"ac.softcap.base_floor": 360, "ac.softcap.rate_floor": 0.2})
    assert tuple(build(tables=low, rules=other).softcap) == (360, 0.29)  # (the best class rate is above this rule's floor)
    assert build("HUM", WME).effective_softcap == 385 and build("HUM", WME, aa={"physical_enhancement": True}).effective_softcap == 392


def test_the_defense_cap_is_the_best_defense_skill_cap_of_the_trio_at_the_level():
    assert build("OGR", PBM).defense_cap == 230  # the Paladin
    assert build("OGR", SCS).defense_cap == 230  # the Shadow Knight
    assert build("HUM", WME).defense_cap == 200
    assert build("OGR", PBM, level=55).defense_cap == 250
    assert build("HUM", ("CLR", "DRU", "SHM")).defense_cap == 210


def test_a_trio_with_no_defense_row_at_the_level_is_refused():
    skills = {k: v for k, v in TABLES.skillcap.items() if k[1] != "Defense"}
    with pytest.raises(ValueError, match="Defense"):
        build(tables=tables_with(skillcap=MappingProxyType(skills)))


def test_the_monk_curve_is_there_for_a_monk_trio_only_and_follows_the_level():
    assert dict(build("OGR", PBM).monk) == {"softcap_stones": 17, "hardcap_stones": 36, "full_bonus_ac": 73}
    assert dict(build("OGR", PBM, level=55).monk) == {"softcap_stones": 20, "hardcap_stones": 40, "full_bonus_ac": 80}
    assert dict(build("OGR", PBM).monk) == formulas.monk_curve(RULES, 50)
    assert build("OGR", SCS).monk is None
    assert build("OGR", WME).monk is None


def test_the_public_texts_give_the_soft_cap_of_a_trio_of_casters_the_model_makes():
    """R8: the note of ``ac.softcap.base_floor`` and the changelog said "392 and not 367" for a trio of casters; the model gives 385 (it was 360) with Combat Stability 3, because a trio of casters is not
    given Physical Enhancement (``ac.softcap.pe_for_caster_only_trios`` is false), and 392 (it was 367) with it. The texts say the model's numbers."""
    casters = build("HUM", WME)
    with_pe = build("HUM", WME, aa={"physical_enhancement": True})
    best_class_cap = max(TABLES.softcap[(code, 50)][0] for code in WME)
    assert best_class_cap == 328 and RULES.get("ac.softcap.base_floor", 50) == 350 and RULES.get("ac.softcap.pe_for_caster_only_trios", 50) is False
    assert (casters.effective_softcap, with_pe.effective_softcap) == (385, 392)
    assert (int(best_class_cap * F(110, 100)), int(best_class_cap * F(112, 100))) == (360, 367)  # what the old cap was, without and with Physical Enhancement
    note = next(rule for rule in RAW["rules"] if rule["id"] == "ac.softcap.base_floor")["notes"]
    assert "385 and not 360" in note and "392 and not 367" in note and "Physical Enhancement" in note.split("392")[1]  # (the 392 is the one with Physical Enhancement, and says so)
    changelog = (REPO / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "385 and not 360" in changelog and "(392 and not 367 at level 50)" not in changelog
    decisions = (REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "had a cap of 360 with Combat Stability 3 and now has 385" in decisions and "a cap of 367 with Combat Stability 3 and Physical Enhancement and now has 392" not in decisions


def test_both_bonuses_ride_inside_the_sheet_value_before_the_cap_as_the_rules_say():
    """T3: the client adds the Monk worn-weight term and the Iksar level term to X, before the soft cap."""
    assert dict(build().placement) == {"monk": "inside", "iksar": "inside"}
    top = "on top of the capped sheet AC (bypasses the softcap), valued per sheet point"
    p = build(rules=rules_with(**{"monk.bonus_placement": top}))
    assert dict(p.placement) == {"monk": "top", "iksar": "inside"}
    q = build("IKS", rules=rules_with(**{"race.iksar_ac_placement": top}))
    assert dict(q.placement) == {"monk": "inside", "iksar": "top"}


def test_an_evaluator_profile_given_no_placement_has_the_placement_the_rules_give():
    """R3: the default of ``EvalProfile`` was ``top`` for both, which the rules no longer say; it follows them (and a change of the rules is a change of this test)."""
    made = build("OGR", PBM).eval_profile
    bare = EvalProfile(level=50, naked=made.naked, weights={}, pools=made.pools)
    assert dict(bare.placement) == dict(made.placement) == {"monk": "inside", "iksar": "inside"}
    assert bare.placement is not EvalProfile(level=50, naked=made.naked, weights={}, pools=made.pools).placement  # (a mapping of its own for each profile)
    assert profile_module.placements(RULES, 50) == dict(bare.placement)
    top = "on top of the capped sheet AC (bypasses the softcap), valued per sheet point"
    assert profile_module.placements(rules_with(**{"monk.bonus_placement": top}), 50) == {"monk": "top", "iksar": "inside"}


def test_past_the_cap_the_weight_of_a_heavy_item_costs_a_monk_only_the_rate_of_its_bonus():
    """T3, in numbers: the Monk bonus rides in X, so a heavy item that takes some of it away moves X by all of that and the sheet by only the rate past the cap."""
    p = build("OGR", PBM)
    light = vec("chest-light", {"AC": 400}, weight10=10, slots=("CHEST",))
    heavy = dataclasses.replace(light, key="chest-heavy", weight10=400)
    a, b = (evaluate(p, kit_of(("CHEST", item))).totals["sheet"] for item in (light, heavy))
    drop = a["monk_bonus"] - b["monk_bonus"]
    assert drop > 0 and a["X"] - b["X"] == drop and a["X"] > a["Y"] and b["X"] > b["Y"]  # (both past the cap, and the whole bonus is in X)
    assert a["capped"] - b["capped"] == F(str(p.softcap[1])) * drop  # (what counts past the cap is the rate of it)
    top = "on top of the capped sheet AC (bypasses the softcap), valued per sheet point"
    c, d = (evaluate(build("OGR", PBM, rules=rules_with(**{"monk.bonus_placement": top})), kit_of(("CHEST", item))).totals["sheet"] for item in (light, heavy))
    assert (c["total"] - d["total"]) - (c["monk_bonus"] - d["monk_bonus"]) == c["capped"] - d["capped"] == 0  # (on top, the sheet is the same and the bonus is the whole change)


def test_the_profile_reads_the_rule_that_an_off_hand_shield_raises_the_softcap():
    assert RULES.get("ac.shield.offhand_raises_cap") is True
    assert build(rules=rules_with(**{"ac.shield.offhand_raises_cap": True})) == build()


@pytest.mark.parametrize("value", [False, 0, "true", "yes"])
def test_a_shield_that_does_not_raise_the_softcap_is_not_implemented_and_is_refused(value):
    # the sheet model adds the off-hand shield to the softcap (Y); another reading would need another model
    rules = rules_with(**{"ac.shield.offhand_raises_cap": value})
    with pytest.raises(ValueError, match="ac.shield.offhand_raises_cap"):
        build(rules=rules)


def test_a_shield_that_the_race_of_the_profile_cannot_wear_does_not_make_the_shield_setup():
    elven = dataclasses.replace(vec("shield-e", {"AC": 10}, shield=True, slots=("SECONDARY",)), races=frozenset({"ELF"}))
    assert build("OGR", PBM, "tank", items=[elven]).setups == ("2h", "dw")
    assert build("ELF", PBM, "tank", items=[elven]).setups == ("1h-shield", "2h", "dw")


@pytest.mark.parametrize("rule", ["monk.bonus_placement", "race.iksar_ac_placement"])
@pytest.mark.parametrize("text", ["wherever it fits", "", 5])
def test_a_placement_the_model_does_not_implement_is_refused(rule, text):
    rules = rules_with(**{rule: text})
    with pytest.raises(ValueError, match=rule):
        build(rules=rules)


def test_the_caps_the_bands_and_the_dual_wield_factor_are_the_rules():
    p = build()
    assert {k: dict(v) if isinstance(v, MappingProxyType) else v for k, v in p.caps.items()} == {
        "regen": {"HP": 30, "MANA": 15, "END": 15}, "resist": 1000,
    }  # fmt: skip
    assert RULES.get("regen.gear_caps") == {"HP": 30, "MANA": 15, "END": 15} and RULES.get("resist.cap") == 1000
    bands = RULES.get("mana.wis_bands")
    assert list(p.bands["breaks"]) == bands["breaks"] and list(p.bands["slopes"]) == bands["slopes"]
    assert p.dw_factor == 0.83 == RULES.get("weapons.dual_wield_factor")["with_monk"]  # PAL/MNK/BER has a Monk
    assert compile_profile(p).dw_factor == F(83, 100)
    assert build(trio=SCS).dw_factor == 0.69 == RULES.get("weapons.dual_wield_factor")["without_monk"]
    other = build(rules=rules_with(**{"weapons.dual_wield_factor": 0.5, "resist.cap": 150}))
    assert other.dw_factor == 0.5 and other.caps["resist"] == 150


# ---- the buffs --------------------------------------------------------------------------------------------


def test_eval_buffs_turns_the_buff_engines_totals_into_the_evaluators_shape():
    totals = {
        "AC": 20, "STR": 10, "STA": 0, "AGI": 0, "DEX": 0, "WIS": 0, "INT": 0, "CHA": 0, "HP": 0, "MANA": 0,
        "END": 0, "ATK": 0, "HPREG": 0, "MANAREG": 3, "ENDREG": 0,
        "sv": {"FIRE": 15, "COLD": 0, "MAGIC": 0, "POISON": 0, "DISEASE": 0}, "haste": 40,
    }  # fmt: skip
    assert eval_buffs(totals) == {"AC": 20, "STR": 10, "MANAREG": 3, "SV": {"FIRE": 15}, "HASTE": 40}
    assert eval_buffs({"sv": {}, "haste": 0, "STR": 0}) == {}
    assert eval_buffs(eval_buffs(totals)) == eval_buffs(totals)  # it reads its own shape too


@pytest.mark.parametrize(
    "totals",
    [
        {"LUCK": 3}, {"sv": {"FIRE": 1, "CORRUPTION": 2}}, {"haste": True}, {"STR": "3"}, {"sv": 3},
        {"sv": {"FIRE": 1}, "SV": {"COLD": 1}},
    ],  # fmt: skip
)
def test_eval_buffs_refuses_what_the_evaluator_would(totals):
    with pytest.raises(ValueError):
        eval_buffs(totals)


def test_buff_totals_are_the_always_on_totals_and_the_spell_haste_is_the_best_haste_on_offer():
    a = buff(1, "Ward Alpha", [(7, "STR", 10), (8, "AC", 20), (9, "FIRE", 15)])
    b = buff(2, "Haste Beta", [(1, "HASTE", 140), (2, "HP", 50)])
    c = buff(3, "Haste Gamma", [(1, "HASTE", 130), (2, "AC", 30)])
    bs = resolve([a, b, c], RULES)
    assert [x.id for x in bs.always_on] == [1] and [x.id for x in bs.optional] == [2, 3] and bs.conflicts == ((2, 3),)
    p = build(buffset=bs)
    assert p.buff_totals == {"STR": 10, "AC": 20, "SV": {"FIRE": 15}}
    assert p.spell_ac == 20
    # Beta (40), which is optional: what the weapon term assumes is the best on offer, with the 10 of Unbound Alacrity
    # that a trio with a Monk (PAL/MNK/BER here) has on top
    assert p.spell_haste == 50 and p.haste_bonus == 10
    assert eval_buffs(bs.totals([2, 3])) == {"STR": 10, "AC": 50, "HP": 50, "SV": {"FIRE": 15}, "HASTE": 40}


def test_a_scenario_without_buffs_has_empty_totals():
    for buffset in (None, resolve([], RULES)):
        p = build(buffset=buffset)
        assert dict(p.buff_totals) == {} and p.spell_ac == 0
        assert p.spell_haste == 10 == p.haste_bonus  # no buff, but the Monk's Unbound Alacrity (PAL/MNK/BER)
        assert build(buffset=buffset, trio=SCS).spell_haste == 0


def test_the_real_own_buffs_of_the_three_trios():
    pbm = build("OGR", PBM)
    assert dict(pbm.buff_totals) == eval_buffs(own_set(PBM).totals(()))
    assert pbm.spell_ac == pbm.buff_totals["AC"] > 0
    # a haste spell stands with every other own buff, and the Monk's Unbound Alacrity adds 10 to it
    assert pbm.spell_haste == pbm.buff_totals["HASTE"] + 10 > 10
    # the 15-slot limit binds for SHD/CLR/SHM: nothing is fixed, the solver chooses, and the haste is on offer
    scs = build("OGR", SCS)
    assert own_set(SCS).cardinality == 15 and own_set(SCS).always_on == ()
    assert dict(scs.buff_totals) == {} and scs.spell_ac == 0
    assert scs.spell_haste == max(b.haste for b in own_set(SCS).optional) > 0
    wme = build("OGR", WME)
    assert dict(wme.buff_totals) == eval_buffs(own_set(WME).totals(()))
    assert wme.spell_haste == max(b.haste for b in (*own_set(WME).always_on, *own_set(WME).optional))


# ---- the pools and the pool-selection data ----------------------------------------------------------------


def test_the_pools_are_the_client_tables_pools_in_trio_order():
    p = build("OGR", PBM, aa={"natural_durability": 0})  # (the default rank puts the AA's percent on the HP factor: test_natural_durability.py)
    assert dict(p.pools) == dict(formulas.pools_for(PBM, 50, TABLES))
    assert p.pools["HP"] == (PoolSpec("PAL", 1440, 4.8), PoolSpec("MNK", 1275, 4.25), PoolSpec("BER", 1275, 4.25))
    assert p.pools["MANA"] == (PoolSpec("PAL", 900, 4.5, "WIS"),)  # the Monk and the Berserker have none
    assert p.pools["END"] == (PoolSpec("PAL", 652, 3.25), PoolSpec("MNK", 900, 4.5), PoolSpec("BER", 995, 4.25))
    assert build("OGR", SCS).pools["MANA"] == (
        PoolSpec("SHD", 900, 4.5, "INT"), PoolSpec("CLR", 900, 4.5, "WIS"), PoolSpec("SHM", 900, 4.5, "WIS"),
    )  # fmt: skip


def test_the_pairs_that_count_when_the_input_may_be_anything():
    assert build("OGR", PBM).pool_choice() == {"HP": ("PAL", "MNK"), "MANA": ("PAL",), "END": ("MNK", "BER")}
    assert build("OGR", SCS).pool_choice() == {"HP": ("SHD", "CLR"), "MANA": None, "END": ("SHD", "CLR")}
    assert build("OGR", WME).pool_choice() == {"HP": ("WIZ", "MAG"), "MANA": ("WIZ", "MAG"), "END": ("WIZ", "MAG")}
    assert build("OGR", ("WAR", "MNK", "ROG")).pool_choice()["MANA"] == ()
    assert build("OGR", ("MNK", "ROG", "BER")).pool_choice()["END"] is None  # the Berserker overtakes the Monk's pool
    assert build("OGR", ("CLR", "WIZ", "ENC")).pool_choice()["MANA"] is None  # WIS against INT


def test_a_narrower_reachable_range_can_fix_a_pair():
    scs = build("OGR", SCS)
    # converted WIS from 100 up, converted INT at most 50: the two WIS pools always lead
    assert scs.pool_choice({"WIS": (100, 300), "INT": (0, 50)})["MANA"] == ("CLR", "SHM")
    # the other way round: the INT pool leads, and one of the equal WIS pools follows
    assert scs.pool_choice({"WIS": (0, 50), "INT": (100, 300)})["MANA"] == ("SHD", "CLR")
    assert scs.pool_choice({"WIS": (0, 300), "INT": (0, 300)})["MANA"] is None
    ber = build("OGR", ("MNK", "ROG", "BER"))  # the Berserker's 995 + 4.25 a point meets the others' 900 + 4.5 at 380
    assert ber.pool_choice({"END": (0, 380)})["END"] == ("MNK", "BER")  # below it the Berserker leads
    assert ber.pool_choice({"END": (0, 381)})["END"] is None
    assert ber.pool_choice({"END": (380, 700)})["END"] == ("MNK", "ROG")  # above it the Monk and the Rogue lead
    with pytest.raises(ValueError, match="range"):
        ber.pool_choice({"STR": (0, 1)})  # not an input of a pool family
    for bad in ((5, 4), (-1, 4), (1,), "ab", None):
        with pytest.raises(ValueError, match="'END'"):  # the message names the input the caller gave
            ber.pool_choice({"END": bad})


def test_fixed_pools_on_pools_written_out():
    a, b, c = PoolSpec("AAA", 100, 1), PoolSpec("BBB", 0, 3), PoolSpec("CCC", 50, 2)  # b = c at 50, a = c at 50
    assert fixed_pools([a, b, c], {None: (0, 40)}) == ("AAA", "CCC")
    assert fixed_pools([a, b, c], {None: (0, 50)}) == ("AAA", "CCC")  # they meet at 50 and part there
    assert fixed_pools([a, b, c], {None: (0, 51)}) is None
    assert fixed_pools([a, b, c], {None: (60, 80)}) == ("BBB", "CCC")
    assert fixed_pools([a, b], {None: (0, 999)}) == ("AAA", "BBB")  # no more pools than count
    assert fixed_pools([a], {None: (0, 999)}) == ("AAA",)
    assert fixed_pools([], {}) == ()
    twins = [PoolSpec("DDD", 10, 2), PoolSpec("EEE", 10, 2), PoolSpec("FFF", 10, 2)]
    assert fixed_pools(twins, {None: (0, 999)}) == ("DDD", "EEE")  # equal pools: the first in trio order
    assert fixed_pools([a, b, c], {None: (0, 51)}, count=1) is None
    assert fixed_pools([a, b, c], {None: (0, 20)}, count=1) == ("AAA",)


def test_fixed_pools_with_two_inputs_compares_the_corners_of_the_box():
    wis = PoolSpec("WWW", 900, 4.5, "WIS")
    wis2 = PoolSpec("XXX", 900, 4.5, "WIS")
    ints = PoolSpec("III", 900, 4.5, "INT")
    box = {"WIS": (100, 200), "INT": (0, 99)}
    assert fixed_pools([wis, ints, wis2], box) == ("WWW", "XXX")
    assert fixed_pools([wis, ints, wis2], {"WIS": (100, 200), "INT": (0, 100)}) == ("WWW", "XXX")  # they may meet, not cross
    assert fixed_pools([wis, ints, wis2], {"WIS": (100, 200), "INT": (0, 101)}) is None
    assert fixed_pools([wis, ints, wis2], {"WIS": (0, 200), "INT": (0, 200)}) is None


@pytest.mark.parametrize(
    "ranges",
    [{None: (5, 4)}, {None: (-1, 4)}, {}, {"WIS": (0, 1)}],
)
def test_fixed_pools_refuses_a_range_that_is_not_one(ranges):
    pools = [PoolSpec("AAA", 100, 1), PoolSpec("BBB", 0, 3), PoolSpec("CCC", 50, 2)]
    with pytest.raises(ValueError, match="range"):
        fixed_pools(pools, ranges)


def test_which_families_need_selection_binaries_over_all_560_trios_at_levels_50_and_55():
    # a data invariant of derived/client/basedata.json: HP pools are proportional (hp = 300 x hp_fac), so the HP pair
    # never changes; the mana pair changes for the 180 trios with three mana classes on both WIS and INT; the END
    # pair changes where the Berserker's pool crosses a Warrior-like one: the Berserker with two of WAR, MNK, ROG
    trios = list(itertools.combinations(CLASS_CODES, 3))
    assert len(trios) == 560
    for level in (50, 55):
        for code in CLASS_CODES:
            row = TABLES.basedata[(code, level)]
            if level == 50:  # exact as decimals
                assert F(str(row["hp"])) == 300 * F(str(row["hp_fac"])), code
            else:  # the client prints hp_fac to three places
                assert row["hp"] == pytest.approx(300 * row["hp_fac"], rel=1e-3), code
        needs = {"HP": [], "MANA": [], "END": []}
        for trio in trios:
            for family, pair in build("HUM", trio, level=level, buffset=None).pool_choice().items():
                if pair is None:
                    needs[family].append(trio)
        assert needs["HP"] == []
        stat_of = {c: s for s, cs in RULES.get("mana.stat_by_class").items() for c in cs}
        mixed = [t for t in trios if len({stat_of[c] for c in t if c in stat_of}) == 2 and sum(c in stat_of for c in t) == 3]
        assert len(mixed) == 180 and needs["MANA"] == mixed
        assert sorted(needs["END"]) == sorted([("WAR", "MNK", "BER"), ("WAR", "ROG", "BER"), ("MNK", "ROG", "BER")])


# ---- the weapon setups ------------------------------------------------------------------------------------


def test_the_setups_are_the_roles_setups_at_the_level():
    for trio in TRIOS:
        for role in roles.roles_for(trio):
            assert build("OGR", trio, role).setups == tuple(weapons.setups_for(trio, role, TABLES, level=50))
    assert build("OGR", PBM, "melee").setups == ("2h", "dw")
    assert build("OGR", PBM, "tank").setups == ("1h-shield", "2h", "dw")
    assert build("OGR", WME).setups == ("1h-shield", "stick")  # with no pool a shield is assumed to exist (the Caster tank: the first build of three casters)
    assert build("OGR", SCS, "caster").setups == ("stick", "1h-shield")  # (the Caster lists the stick first: the first setup wins a tie)


def test_the_pool_given_to_the_profile_decides_the_shield_setup():
    everyone = vec("shield-a", {"AC": 10}, shield=True, slots=("SECONDARY",))
    fighters = dataclasses.replace(vec("shield-b", {"AC": 10}, shield=True, slots=("SECONDARY",)), classes=frozenset({"WAR", "PAL"}))
    held = vec("focus", {"AC": 10}, slots=("SECONDARY",))  # armor class in the off hand, but not a shield
    assert build("OGR", WME, items=[everyone]).setups == ("1h-shield", "stick")
    assert build("OGR", WME, items=[fighters, held]).setups == ("stick",)
    assert build("OGR", WME, items=[]).setups == ("stick",)
    assert build("OGR", PBM, "tank", items=[fighters]).setups == ("1h-shield", "2h", "dw")
    assert build("OGR", PBM, "tank", items=[held]).setups == ("2h", "dw")
    # the pool is not part of the profile: the same setups, the same profile
    assert build("OGR", WME, items=[everyone]) == build("OGR", WME)
    assert build("OGR", WME, items=[fighters]) != build("OGR", WME)


# ---- bad inputs -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "word"),
    [
        ({"race": "XXX"}, "race"),
        ({"level": 200}, "level"),
        ({"level": 0}, "level"),
        ({"level": True}, "level"),
        ({"level": 50.0}, "level"),
        ({"role": "caster"}, "role"),  # a Paladin/Monk/Berserker is not offered the Caster role
        ({"role": "healer"}, "role"),
        ({"trio": ("PAL", "MNK")}, "trio"),
        ({"trio": ("PAL", "MNK", "MNK")}, "trio"),
        ({"trio": ("PAL", "MNK", "XXX")}, "trio"),
    ],
)
def test_make_profile_refuses_what_it_cannot_build_a_profile_for(kwargs, word):
    with pytest.raises(ValueError, match=word):
        build(buffset=None, **kwargs)


# ---- the record: JSON, hash, immutability ----------------------------------------------------------------------


FIELDS = [f.name for f in dataclasses.fields(Profile)]


def test_the_json_lists_every_field_and_a_format_number():
    data = json.loads(build().to_json())
    assert list(data) == ["format", *FIELDS]
    assert data["format"] == 1
    for name in ("race", "trio", "level", "role", "evidence", "aa", "naked", "buff_totals", "spell_haste", "haste_cap",
                 "softcap", "cs_pct", "pe_pct", "defense_cap", "monk", "iksar_ac", "placement", "pools", "caps",
                 "bands", "dw_factor", "weights", "setups", "deity"):
        assert name in FIELDS, name  # the scenario's constants, plus its identity
    assert data["trio"] == list(PBM) and data["pools"]["MANA"][0] == {"cls": "PAL", "base": 900, "fac": 4.5, "stat": "WIS"}


@pytest.mark.parametrize("trio", TRIOS)
def test_a_profile_reads_back_from_its_json(trio):
    for race in ("OGR", "IKS", "HUM"):
        for role in roles.roles_for(trio):
            p = build(race, trio, role)
            q = Profile.from_json(p.to_json())
            assert q == p and hash(q) == hash(p) and q.to_json() == p.to_json()
            assert Profile.from_json(p.to_json(indent=2)) == p
            assert Profile.from_dict(json.loads(p.to_json())) == p


def test_a_profile_is_hashable_and_equal_profiles_share_one_text_and_one_hash():
    p, q = build(), build()
    assert p == q and hash(p) == hash(q) and p.to_json() == q.to_json()
    assert len({p, q}) == 1 and {p: 1}[q] == 1
    assert build(role="melee") != p and build(role="melee").to_json() != p.to_json()
    assert len({build(role=r) for r in roles.roles_for(PBM)}) == 2


def test_numbers_equal_in_value_are_one_number_in_the_record():
    p = build()
    q = dataclasses.replace(p, weights={**p.weights, "HP": 1.0, "CHA": 0.05}, spell_haste=25.0)
    r = dataclasses.replace(p, weights={**p.weights, "HP": 1}, spell_haste=25)
    assert q == r and hash(q) == hash(r) and q.to_json() == r.to_json()
    assert dataclasses.replace(p, buff_totals={**p.buff_totals, "DEX": 0}) == p  # a zero total is no total


def test_a_profile_cannot_be_changed_and_does_not_share_the_dicts_it_was_made_from():
    p = build()
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.level = 51  # type: ignore[misc]
    for name in ("naked", "weights", "placement", "caps", "aa", "buff_totals", "bands", "pools"):
        with pytest.raises(TypeError):
            getattr(p, name)["HP"] = 1
    with pytest.raises(TypeError):
        p.caps["regen"]["HP"] = 1
    with pytest.raises(TypeError):
        p.monk["softcap_stones"] = 1
    weights = dict(p.weights)
    q = dataclasses.replace(p, weights=weights)
    weights["HP"] = 99
    assert q.weights["HP"] == p.weights["HP"]


def test_an_identity_that_differs_makes_a_different_profile():
    p = build()
    for change in ({"race": "HUM"}, {"level": 55}, {"evidence": "wiki"}, {"deity": "Marr"}, {"aa": {"combat_stability": 1}}):
        assert build(**change) != p, change


@pytest.mark.parametrize(
    ("changes", "word"),
    [
        ({"weights": {"HP": -1}}, "weight"),
        ({"weights": {"FOO": 1}}, "FOO"),
        ({"placement": {"monk": "up", "iksar": "top"}}, "placement"),
        ({"placement": {"monk": "top"}}, "placement"),
        ({"evidence": "all"}, "evidence"),
        ({"role": "healer"}, "role"),
        ({"trio": ("PAL", "MNK")}, "trio"),
        ({"aa": {"combat_stability": 3}}, "aa"),
        ({"setups": ("no-such-setup",)}, "setup"),
        ({"pools": {"HP": (), "MANA": (), "END": ()}}, "pool"),
        ({"naked": {"STR": 1}}, "naked"),
        ({"level": 0}, "level"),
        ({"deity": ""}, "deity"),
        ({"spell_haste": -1}, "spell_haste"),
        ({"spell_haste": 10, "buff_totals": {"HASTE": 20}}, "spell_haste"),  # the best on offer is at least the fixed one
        ({"softcap": (392, 1.5)}, "softcap"),
        ({"haste_cap": -5}, "haste_cap"),
        ({"monk": {"softcap_stones": 17}}, "monk"),
        ({"dw_factor": -0.1}, "dw_factor"),
        ({"buff_totals": {"LUCK": 3}}, "buff"),
        ({"cs_pct": float("nan")}, "cs_pct"),
        ({"caps": {"resist": 200}}, "caps"),  # a missing part is a ValueError, not a KeyError
        ({"caps": {"regen": {"HP": 30}, "resist": 200}}, "caps"),
        ({"caps": {"regen": 15, "resist": 200}}, "caps"),
        ({"bands": {"breaks": [100]}}, "bands"),
        ({"bands": {"breaks": [100, 200], "slopes": [1, 2]}}, "band"),  # one slope too few
    ],
)
def test_a_profile_that_the_evaluator_or_the_model_would_refuse_cannot_be_made(changes, word):
    with pytest.raises(ValueError, match=word):
        dataclasses.replace(build(), **changes)


def good():
    return json.loads(build().to_json())


@pytest.mark.parametrize(
    ("mutate", "word"),
    [
        (lambda d: d.pop("evidence"), "evidence"),
        (lambda d: d.update(extra=1), "extra"),
        (lambda d: d.update(format=2), "format"),
        (lambda d: d.pop("format"), "format"),
        (lambda d: d.update(trio=["PAL", "MNK"]), "trio"),
        (lambda d: d.update(weights=[1, 2]), "weights"),
        (lambda d: d.update(pools={"HP": [{"cls": "PAL"}], "MANA": [], "END": []}), "pool"),
        (lambda d: d.update(pools={"HP": [], "END": []}), "pool"),
    ],
)
def test_from_dict_is_strict(mutate, word):
    data = good()
    mutate(data)
    with pytest.raises(ValueError, match=word):
        Profile.from_dict(data)


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[1, 2]", "null", '{"format": 1, "format": 1}', '{"format": NaN}', '{"format": Infinity}'],
)
def test_from_json_refuses_text_that_is_not_one_profile(text):
    with pytest.raises(ValueError):
        Profile.from_json(text)


def test_from_json_refuses_a_duplicate_key_inside_the_profile():
    text = build().to_json()
    twice = text.replace('"level":50', '"level":50,"level":51')
    assert twice != text
    with pytest.raises(ValueError, match="duplicate"):
        Profile.from_json(twice)


@settings(max_examples=120, deadline=None)
@given(
    race=st.sampled_from(["HUM", "OGR", "IKS", "TRL", "ERU", "FRG"]),
    trio=st.lists(st.sampled_from(CLASS_CODES), min_size=3, max_size=3, unique=True),
    level=st.sampled_from([50, 55]),
    pick=st.integers(0, 3),
    aa=st.sampled_from(
        [None, {"combat_stability": 1}, {"physical_enhancement": True}, {"combat_stability": 0, "physical_enhancement": False}]
    ),
)  # fmt: skip
def test_any_profile_reads_back_and_evaluates(race, trio, level, pick, aa):
    offered = roles.roles_for(trio)
    p = build(race, tuple(trio), offered[pick % len(offered)], level=level, buffset=None, aa=aa)
    q = Profile.from_json(p.to_json())
    assert q == p and hash(q) == hash(p)
    assert evaluate(q, kit_of()).F == evaluate(p, kit_of()).F
    assert evaluate(p, SMALL_KIT, setup="1h-shield", haste_assumed=weapons.haste_assumed(p, [])).F >= 0


# ---- the evaluator ----------------------------------------------------------------------------------------


def test_a_profile_has_every_field_the_evaluator_reads_and_compiles_to_the_same_evaluation_profile():
    for trio in TRIOS:
        p = build("OGR", trio)
        assert all(hasattr(p, f.name) for f in dataclasses.fields(EvalProfile))
        ev = p.eval_profile
        assert isinstance(ev, EvalProfile) and compile_profile(p) == ev
        assert compile_profile(ev) is ev
        assert ev.level == 50 and ev.haste_cap == p.haste_cap and dict(ev.pools) == dict(p.pools)


@pytest.mark.parametrize("level", [50, 55])
@pytest.mark.parametrize("trio", TRIOS)
def test_every_real_profile_evaluates_an_empty_kit_and_a_small_kit(trio, level):
    for role in roles.roles_for(trio):
        p = build("OGR", trio, role, level=level)
        empty = evaluate(p, kit_of())
        assert empty.F > 0 and empty.F == sum(empty.parts.values())
        assert evaluate(p.eval_profile, kit_of()).F == empty.F  # a Profile and its evaluation profile agree
        items = [e for e in SMALL_KIT if e is not None]
        assumed = weapons.haste_assumed(p, items)
        small = evaluate(p, SMALL_KIT, setup="1h-shield", haste_assumed=assumed)
        assert small.F > empty.F  # the small kit only adds good things
        assert small.totals["haste"]["worn_best"] == 10
        assert small.totals["sheet"]["worn_ac"] == 60 and small.totals["sheet"]["shield_ac"] == 12


def test_the_buffs_of_a_choice_enter_through_the_evaluators_buffs_argument():
    bs = own_set(SCS)
    chosen = []
    for b in bs.optional:
        if bs.is_legal([*chosen, b.id]):
            chosen.append(b.id)
    p = build("OGR", SCS)
    alone = evaluate(p, kit_of())
    with_buffs = evaluate(p, kit_of(), eval_buffs(bs.totals(chosen)))
    assert with_buffs.F > alone.F  # the profile fixed none of them
    assert with_buffs.totals["haste"]["spell"] == bs.totals(chosen)["haste"]


def test_a_damage_weight_in_the_rules_reaches_the_value_of_a_weapon():
    # the sword of SMALL_KIT has the index (20 + 15) / 30 = 7/6 at no haste; the shield beside it scores no damage
    real = build("OGR", PBM, "melee")
    assert real.weights["DMG"] == 1800  # the real rules: 450 x the ATK weight (4) x the weapon factor of Melee damage (1)
    assert evaluate(real, SMALL_KIT, setup="1h-shield", haste_assumed=0).parts["WEAPON"] == 1800 * F(7, 6) * F("2.1") == 4410  # (T8: the Melee build of a trio with a Berserker swings at the stance's factor 2.1)
    assert build("OGR", PBM, "tank").weights["DMG"] == pytest.approx(450 * 2.67 * 0.5)  # the Tank counts the weapon at half
    weighted = build("OGR", PBM, "melee", rules=rules_with(**{"weapons.damage_weight": 5}))
    assert weighted.weights["DMG"] == 20  # 5 x 4
    assert evaluate(weighted, SMALL_KIT, setup="1h-shield", haste_assumed=0).parts["WEAPON"] == F(20) * F(7, 6) * F("2.1")  # (T8: the stance's factor)
    caster = build("OGR", WME, "caster")  # the Caster build scores no weapon damage
    assert caster.weights["DMG"] == 0
    assert evaluate(caster, SMALL_KIT, setup="1h-shield", haste_assumed=0).parts["WEAPON"] == 0


def test_with_no_damage_weight_in_the_rules_a_weapon_is_worth_nothing_to_the_profile():
    plain = build(rules=rules_with(**{"weapons.damage_weight": None}))  # null is legal while the rule is open
    assert "DMG" not in plain.weights  # weapons are then chosen for their stats alone
    assert evaluate(plain, SMALL_KIT, setup="1h-shield", haste_assumed=0).parts["WEAPON"] == 0


def test_haste_assumed_reads_the_profiles_cap_and_spell_haste():
    p = build("OGR", PBM)  # cap 85
    assert weapons.haste_assumed(p, [vec("a", haste=10)]) == p.spell_haste + 10
    assert weapons.haste_assumed(p, [vec("a", haste=70)]) == 85
    assert weapons.haste_assumed(build("OGR", SCS), []) == build("OGR", SCS).spell_haste


def test_f_of_the_empty_kit_is_the_naked_plus_buff_value_worked_by_hand():
    # A Human WIZ/MAG/ENC at level 50, the Caster build, one invented permanent buff
    # (STR +10, AC +20, HP +100, mana +50, mana regen +4, fire resist +15) and nothing worn.
    ward = buff(
        1, "Ward Delta", [(1, "STR", 10), (2, "AC", 20), (3, "HP", 100), (4, "MANA", 50), (5, "MANAREG", 4), (6, "FIRE", 15)]
    )
    p = build("HUM", WME, "caster", buffset=resolve([ward], RULES), aa={"natural_durability": 0})  # (the AA's percent on the HP factor is worked in test_natural_durability.py)
    result = evaluate(p, kit_of())

    # totals: Human 75 each; the three classes add STA 15 + 15, INT 15 x 3, CHA 15; the buff adds STR 10
    assert result.totals["attributes"] == {"STR": 85, "STA": 105, "AGI": 75, "DEX": 75, "WIS": 75, "INT": 120, "CHA": 90}
    # weights (Caster template): HP 1, AC 1.2, MANA 4, ATK 0.3, DEX 0.1, HASTE 0, END 0.05, CHA 0.05, SV 0.8 a school,
    # regen = 10 x 3 x the resource: mana regen 30 x 4 = 120
    parts = result.parts
    # HP: two pools of 5 + 1200 + 4.0 x 105 = 1625, plus 100 from the buff
    assert parts["HP"] == 1 * (2 * F(1625) + 100) == 3350
    # mana: INT 120 converts to 100 + 2.5 x 20 = 150; two pools of 900 + 4.5 x 150 = 1575, plus 50
    assert parts["MANA"] == 4 * (2 * F(1575) + 50) == 12800
    # END: A = (85 + 105 + 75 + 75) / 4 = 85 (under the knee at 100); two pools of 260 + 1.25 x 85 = 366.25
    assert parts["END"] == F("0.05") * (2 * F("366.25")) == F("36.625")
    # AC: X = 200/3 (Defense 200) + 20/4 (spell AC) + 75/20 (AGI) = 905/12, under Y = floor(350 x 1.10) = 385 (T2: the floor of the cap), so the
    # sheet reads X; each sheet point is worth 1.2 / (4/3) = 0.9
    assert result.totals["sheet"]["Y"] == 385 and result.totals["sheet"]["capped"] == F(905, 12)
    assert parts["AC"] == F(9, 10) * F(905, 12) == F("67.875")
    assert parts["EVASION"] == F("1.2") * F("0.2222") * 75 == F("19.998")
    assert parts["ATK"] == F("0.3") * F("0.666667") * 85 == F("17.0000085")
    assert parts["DEX"] == F("0.1") * 75 == F("7.5")
    assert parts["CHA"] == F("0.05") * 90 == F("4.5")
    assert parts["REGEN"] == 120 * 4 == 480
    assert parts["RESISTS"] == F("0.8") * 15 == 12
    assert parts["HASTE"] == parts["WEAPON"] == parts["MONK"] == parts["IKSAR"] == 0
    assert result.F == (
        F(3350) + 12800 + F("36.625") + F("67.875") + F("19.998") + F("17.0000085") + F("7.5") + F("4.5") + 480 + 12
    )
    assert result.F == F("16795.4980085")
    # the profile's own buff totals and the explicit ones are the same evaluation
    assert evaluate(p, kit_of(), eval_buffs(resolve([ward], RULES).totals(()))).F == result.F
