"""Tests for the robustness perturbations: ``trioforge.solver.robust``.

A kit is only as good as the judgment constants and the open rules behind it. ``perturbations(profile, rules)`` lists
the variants of a scenario that the robustness seal re-solves: each key weight group (AC, MANA, ATK+HASTE, SV, regen)
at x0.5 and x2, and each open rule switched to the alternative that ``rules/rules.json`` lists (the WIS band above 200,
the Monk curve "full until 34", the Monk placement inside the cap, the Iksar placement inside the cap, the weapon
damage rate of 10 percent a tier). ``robustness(scenario)`` solves the base scenario and every variant and marks each
slot ``"robust"`` when all of them pick the same items there, else with the label of the variant that changed it.

The checks:

* the labels, in their fixed order, for trios that have all, some or none of the things a variant changes;
* every variant changes exactly the fields it should and keeps the profile valid, hashable and JSON-serializable;
* the values come from the rules file (a rules object with another alternative gives another variant);
* the solves: a slot that flips under one variant gets that label; one that never flips is robust; a solve that does
  not end optimal is an error;
* the two accessors of ``Rules`` that the variants read (``alternatives`` and ``settled_by``).

Every item here is invented; the races, classes and trios are public game terms.
"""

import copy
import dataclasses
import json
from functools import cache

import pytest

from trioforge import rules as rules_module
from trioforge.model import formulas as fm
from trioforge.model import profile as profile_module
from trioforge.model import weapons as wp
from trioforge.model.items import SLOT_GROUPS, SLOT_INSTANCES, at_tier
from trioforge.model.profile import Profile, make_profile
from trioforge.model.tables import load
from trioforge.solver import robust
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.robust import (
    Perturbation,
    RobustnessError,
    RobustScenario,
    describe_perturbations,
    perturbations,
    robustness,
    robustness_report,
)
from trioforge.solver.solve import Solution, solve_canonical

TABLES = load()
RULES = TABLES.rules
GROUPS = [name for name, _ in SLOT_GROUPS]
RAW_RULES = json.loads(rules_module.RULES_PATH.read_text(encoding="utf-8"))
OPTIONS = BuildOptions(any_rule="explicit", haste_assumed=0)

FULL_LABELS = [
    "AC x0.5", "AC x2", "MANA x0.5", "MANA x2", "ATK+HASTE x0.5", "ATK+HASTE x2", "SV x0.5", "SV x2",
    "regen x0.5", "regen x2", "WIS band 0.654", "Monk curve full until 34", "Monk placement inside",
    "Iksar placement inside", "Weapon damage +10%",
]  # fmt: skip


@cache
def profile_of(race, trio, role="balanced"):
    return make_profile(race, trio, 50, role, None, None, TABLES)


def with_weights(profile, **weights):
    return dataclasses.replace(profile, weights=weights)


def labels(profile, rules=RULES, setup=None):
    return [label for label, _ in describe_pairs(profile, rules, setup)]


def describe_pairs(profile, rules=RULES, setup=None):
    return [(p.label, p.profile) for p in describe_perturbations(profile, rules, setup=setup)]


def rules_with_alternative(rule_id, value):
    """The real rules with the first alternative of one rule replaced."""
    data = copy.deepcopy(RAW_RULES)
    for rule in data["rules"]:
        if rule["id"] == rule_id:
            rule["alternatives"][0]["value"] = value
    return rules_module.Rules(data)


def raw_item(key, slots, *, stats=None, sv=None, weight=0.1, weapon=None, item_type=None, lore=False):
    """A schema-shaped catalog item with an invented name."""
    return {
        "key": key, "name": f"Invented {key}", "wiki": {"pageid": 1, "revid": 1, "title": key}, "slots": list(slots),
        "classes": ["ALL"], "races": ["ALL"], "deity": None, "flags": ["lore"] if lore else [],
        "stats": dict(stats or {}), "sv": dict(sv or {}), "weight": weight, "size": "SMALL", "item_type": item_type,
        "weapon": weapon,
        "container_capacity": None, "instrument_mods": {}, "effects": [], "required_level": None,
        "recommended_level": None, "sources": {"drops": [], "sold_by": [], "quests": [], "crafted": []},
        "categories": [], "era_tags": [], "lucy_img_id": None, "tier_rule": "drop", "parse_warnings": [],
        "parse_warnings_overflow": 0,
    }  # fmt: skip


def weapon_of(dmg, delay, skill="1H Slashing"):
    return {"skill": skill, "dmg": dmg, "delay": delay, "bonus": None}


def scenario(profile, raws, setup="stick", tier=0, **changes):
    def pool(**item_options):
        return [at_tier(raw, tier, RULES, **item_options) for raw in raws]

    return RobustScenario(profile, RULES, pool, setup, tier, options=changes.pop("options", OPTIONS), **changes)


def worn(solution):
    """The item keys of a solution's kit."""
    return sorted(item.key for item in solution.kit if item is not None)


@cache
def full():
    """An Iksar Monk/Cleric/Berserker: mana, a Monk curve, an Iksar bonus and a damage weight are all there."""
    return profile_of("IKS", ("MNK", "CLR", "BER"))


# ---- the labels -------------------------------------------------------------------------------------------------


def test_a_trio_with_everything_gets_all_fifteen_variants_in_a_fixed_order():
    assert labels(full()) == FULL_LABELS
    assert [label for label, _ in perturbations(full(), RULES)] == FULL_LABELS
    assert [label for label, _ in perturbations(full(), RULES)] == labels(full())  # and the same on every call


def test_perturbations_returns_label_and_profile_pairs():
    pairs = perturbations(full(), RULES)
    assert all(isinstance(label, str) and isinstance(p, Profile) for label, p in pairs)
    records = describe_perturbations(full(), RULES)
    assert all(isinstance(record, Perturbation) for record in records)
    assert [(r.label, r.profile) for r in records] == pairs  # the records are the pairs with the item options and the test


def test_a_trio_without_mana_a_monk_or_an_iksar_gets_only_the_variants_that_can_matter():
    # War, Rogue and Berserker: no mana class, no Monk; a Human: no racial bonus. Damage is weighted.
    p = profile_of("HUM", ("WAR", "ROG", "BER"))
    assert labels(p) == [
        "AC x0.5", "AC x2", "ATK+HASTE x0.5", "ATK+HASTE x2", "SV x0.5", "SV x2", "regen x0.5", "regen x2",
        "Weapon damage +10%",
    ]  # fmt: skip


def test_an_all_caster_trio_has_a_mana_band_but_no_damage_to_weigh():
    p = profile_of("HUM", ("WIZ", "MAG", "ENC"))
    assert p.weights["DMG"] == 0 and p.pools["MANA"]
    assert labels(p) == [
        "AC x0.5", "AC x2", "MANA x0.5", "MANA x2", "ATK+HASTE x0.5", "ATK+HASTE x2", "SV x0.5", "SV x2",
        "regen x0.5", "regen x2", "WIS band 0.654",
    ]  # fmt: skip


def test_a_group_whose_weights_are_all_zero_is_left_out():
    p = with_weights(profile_of("HUM", ("WAR", "CLR", "ENC")), HP=1.0, AC=1.0)
    assert labels(p) == ["AC x0.5", "AC x2"]
    assert labels(with_weights(profile_of("HUM", ("WAR", "CLR", "ENC")), HP=1.0)) == []


def test_the_mana_variants_need_a_mana_pool_whatever_the_mana_weight_says():
    p = with_weights(profile_of("HUM", ("WAR", "ROG", "BER")), HP=1.0, MANA=3.0)
    assert not p.pools["MANA"] and labels(p) == []
    q = with_weights(profile_of("HUM", ("CLR", "ROG", "BER")), HP=1.0, MANA=3.0)
    assert labels(q) == ["MANA x0.5", "MANA x2", "WIS band 0.654"]


def test_the_weapon_variant_needs_a_damage_weight_and_a_setup_that_scores_it():
    p = with_weights(profile_of("HUM", ("WAR", "ROG", "BER")), HP=1.0, DMG=100.0)
    both = ["ATK+HASTE x0.5", "ATK+HASTE x2", "Weapon damage +10%"]  # the damage weight is part of the ATK+HASTE group
    assert labels(p) == both and labels(p, setup="2h") == both
    assert labels(p, setup="stick") == both[:2]  # the stick scores no damage, so its damage rate cannot matter
    assert labels(with_weights(p, HP=1.0)) == []


def test_a_variant_that_the_profile_already_is_at_is_left_out():
    p = full()
    inside = dataclasses.replace(p, placement={"monk": "inside", "iksar": "inside"})
    assert "Monk placement inside" not in labels(inside) and "Iksar placement inside" not in labels(inside)
    alt_monk = dataclasses.replace(p, monk={**p.monk, "full_until_stones": 34})
    assert "Monk curve full until 34" not in labels(alt_monk)
    alt_bands = dataclasses.replace(p, bands={"breaks": [100, 200, 510], "slopes": [1, 2.5, 0.654, 0]})
    assert "WIS band 0.654" not in labels(alt_bands)


def test_the_monk_and_iksar_variants_only_matter_when_armor_class_is_weighted():
    p = with_weights(full(), HP=1.0, MANA=1.0)
    assert labels(p) == ["MANA x0.5", "MANA x2", "WIS band 0.654"]


# ---- what each variant changes -------------------------------------------------------------------------------------


CHANGED = {
    "AC x0.5": {"weights"}, "AC x2": {"weights"}, "MANA x0.5": {"weights"}, "MANA x2": {"weights"},
    "ATK+HASTE x0.5": {"weights"}, "ATK+HASTE x2": {"weights"}, "SV x0.5": {"weights"}, "SV x2": {"weights"},
    "regen x0.5": {"weights"}, "regen x2": {"weights"}, "WIS band 0.654": {"bands"},
    "Monk curve full until 34": {"monk"}, "Monk placement inside": {"placement"},
    "Iksar placement inside": {"placement"}, "Weapon damage +10%": set(),
}  # fmt: skip


def changed_fields(a, b):
    return {f.name for f in dataclasses.fields(Profile) if getattr(a, f.name) != getattr(b, f.name)}


@pytest.mark.parametrize("label", FULL_LABELS)
def test_each_variant_changes_exactly_the_fields_it_should(label):
    base = full()
    p = dict(describe_pairs(base))[label]
    assert changed_fields(base, p) == CHANGED[label]


@pytest.mark.parametrize("label", FULL_LABELS)
def test_each_variant_is_a_valid_hashable_json_profile(label):
    p = dict(describe_pairs(full()))[label]
    assert isinstance(p, Profile) and hash(p) == hash(Profile.from_json(p.to_json()))
    assert Profile.from_json(p.to_json()) == p
    fm.evaluate(p, [None] * 22)  # the oracle reads it


def test_the_weight_variants_scale_exactly_their_group_and_nothing_else():
    base = full()
    pairs = dict(describe_pairs(base))
    groups = {
        "AC": ["AC"], "MANA": ["MANA"], "ATK+HASTE": ["ATK", "HASTE", "DMG"],
        "SV": [f"SV_{s}" for s in fm.SCHOOLS], "regen": ["HPREG", "MANAREG", "ENDREG"],
    }  # fmt: skip
    for group, keys in groups.items():
        for factor, text in ((0.5, "0.5"), (2, "2")):
            p = pairs[f"{group} x{text}"]
            for key, value in base.weights.items():
                expected = value * factor if key in keys else value
                assert p.weights[key] == pytest.approx(expected, rel=0, abs=1e-12), (group, factor, key)
            assert set(p.weights) == set(base.weights)


def test_the_rule_variants_carry_the_values_of_the_rules_file():
    base = full()
    pairs = dict(describe_pairs(base))
    assert list(pairs["WIS band 0.654"].bands["breaks"]) == [100, 200, 510]
    assert list(pairs["WIS band 0.654"].bands["slopes"]) == [1, 2.5, 0.654, 0]
    assert pairs["Monk curve full until 34"].monk == {**base.monk, "full_until_stones": 34}
    assert dict(pairs["Monk placement inside"].placement) == {"monk": "inside", "iksar": base.placement["iksar"]}
    assert dict(pairs["Iksar placement inside"].placement) == {"monk": base.placement["monk"], "iksar": "inside"}
    assert base.placement["monk"] == base.placement["iksar"] == "top" and base.iksar_ac == 35


def test_the_weapon_variant_changes_the_items_not_the_profile():
    described = {p.label: p for p in describe_perturbations(full(), RULES)}
    weapon = described["Weapon damage +10%"]
    assert weapon.profile == full() and dict(weapon.item_options) == {"weapon_pct": 10}
    assert all(dict(p.item_options) == {} for label, p in described.items() if label != "Weapon damage +10%")


def test_every_variant_names_the_test_that_settles_it():
    described = {p.label: p for p in describe_perturbations(full(), RULES)}
    tests = {label: p.test for label, p in described.items()}
    assert tests["WIS band 0.654"] == "B4" and tests["Weapon damage +10%"] == "B5"
    assert tests["Monk curve full until 34"] == tests["Monk placement inside"] == "B9"
    assert tests["Iksar placement inside"] == "B17"
    assert all(tests[label] is None for label in FULL_LABELS[:10])
    assert {label: p.kind for label, p in described.items()} == {
        **dict.fromkeys(FULL_LABELS[:10], "weight"), **dict.fromkeys(FULL_LABELS[10:], "rule"),
    }


def test_a_rules_file_with_another_alternative_gives_another_variant():
    other = rules_with_alternative("mana.wis_bands", {"breaks": [100, 200, 510], "slopes": [1, 2.5, 0.7, 0]})
    pairs = describe_pairs(full(), other)
    assert "WIS band 0.7" in [label for label, _ in pairs] and "WIS band 0.654" not in [label for label, _ in pairs]
    assert list(dict(pairs)["WIS band 0.7"].bands["slopes"]) == [1, 2.5, 0.7, 0]
    other = rules_with_alternative("monk.weight_curve", {"full_until_stones": 30})
    assert dict(describe_pairs(full(), other))["Monk curve full until 30"].monk["full_until_stones"] == 30
    other = rules_with_alternative("monk.bonus_placement", "on top of the capped sheet AC")
    assert "Monk placement inside" not in labels(full(), other)  # this alternative is the placement the profile has
    other = rules_with_alternative("monk.bonus_placement", "somewhere else")
    with pytest.raises(ValueError, match="placement"):
        describe_perturbations(full(), other)


def test_the_placement_texts_are_the_ones_the_profile_generator_reads():
    assert robust.INSIDE_PLACEMENT in profile_module._PLACEMENT_TEXT
    assert profile_module._PLACEMENT_TEXT[robust.INSIDE_PLACEMENT] == "inside"
    assert RULES.alternatives("monk.bonus_placement")[0]["value"].startswith(robust.INSIDE_PLACEMENT)


# ---- the accessors of Rules ----------------------------------------------------------------------------------------


def test_rules_lists_the_alternatives_of_a_rule_as_copies():
    alternatives = RULES.alternatives("mana.wis_bands")
    assert len(alternatives) == 1 and alternatives[0]["value"]["slopes"] == [1, 2.5, 0.654, 0]
    assert alternatives[0]["seal"] == "measured" and alternatives[0]["source"][0]["kind"] == "url"
    alternatives[0]["value"]["slopes"][2] = 99  # a copy: the rules do not change
    assert RULES.alternatives("mana.wis_bands")[0]["value"]["slopes"][2] == 0.654
    assert RULES.alternatives("tier.weapon_damage_pct")[0]["value"] == 10
    assert RULES.alternatives("monk.weight_curve")[0]["value"] == {"full_until_stones": 34}
    assert RULES.alternatives("hp.sta_curve") == []
    with pytest.raises(KeyError):
        RULES.alternatives("no.such.rule")


def test_rules_names_the_test_that_settles_an_open_rule():
    assert RULES.settled_by("mana.wis_bands") == "B4"
    assert RULES.settled_by("race.iksar_ac_placement") == "B17"
    assert RULES.settled_by("hp.sta_curve") is None
    with pytest.raises(KeyError):
        RULES.settled_by("no.such.rule")


# ---- the solves ------------------------------------------------------------------------------------------------------


def test_a_slot_that_flips_under_a_weight_gets_the_label_of_the_weight():
    # Neck: 40 armor class or 50 hit points. At weight 1 the hit points win; double the armor class and it is 80 to 50.
    p = with_weights(profile_of("HUM", ("WAR", "CLR", "ENC")), HP=1.0, AC=1.0)
    raws = [
        raw_item("head", ["HEAD"], stats={"HP": 10}),
        raw_item("neck-ac", ["NECK"], stats={"AC": 40}),
        raw_item("neck-hp", ["NECK"], stats={"HP": 50}),
    ]
    result = robustness(scenario(p, raws))
    assert list(result) == GROUPS
    assert result["NECK"] == "AC x2"
    assert {slot: label for slot, label in result.items() if slot != "NECK"} == dict.fromkeys(
        [g for g in GROUPS if g != "NECK"], "robust"
    )
    report = robustness_report(scenario(p, raws))
    assert worn(report.base) == ["head", "neck-hp"] and report.picks["NECK"] == ("neck-hp",)
    assert report.flips["NECK"] == ("AC x2",) and report.flips["HEAD"] == ()


def kit_with(**placed):
    """A 22-place kit with the given items in the first place of their group (``BACK=item``)."""
    kit = [None] * len(SLOT_INSTANCES)
    for group, item in placed.items():
        kit[SLOT_INSTANCES.index(group)] = item
    return kit


def test_a_slot_that_flips_under_a_rule_and_a_weight_is_labelled_by_the_rule():
    p = with_weights(profile_of("HUM", ("CLR", "WAR", "ROG")), HP=1.0, MANA=1.0)  # the one mana class, Cleric, uses WIS
    # Back: WIS up to 215, which puts the neck item's 25 WIS in the 200-255 band. The neck holds that item or 100 HP.
    need = 215 - p.naked["WIS"]
    assert need > 0
    back = at_tier(raw_item("back", ["BACK"], stats={"WIS": need}), 0, RULES)
    neck = at_tier(raw_item("neck-wis", ["NECK"], stats={"WIS": 25}), 0, RULES)
    gain = [
        float(fm.evaluate(prof, kit_with(BACK=back, NECK=neck)).F - fm.evaluate(prof, kit_with(BACK=back)).F)
        for prof in (p, dict(describe_pairs(p))["WIS band 0.654"])
    ]
    hp = 100
    assert gain[1] < hp < gain[0]  # the band flips the neck ...
    assert gain[0] / 2 < hp < gain[0] * 2  # ... and so does mana x0.5, but not mana x2
    raws = [
        raw_item("back", ["BACK"], stats={"WIS": need}),
        raw_item("neck-wis", ["NECK"], stats={"WIS": 25}),
        raw_item("neck-hp", ["NECK"], stats={"HP": hp}),
    ]
    report = robustness_report(scenario(p, raws))
    assert report.picks["NECK"] == ("neck-wis",)
    assert report.flips["NECK"] == ("WIS band 0.654", "MANA x0.5")  # rules come first, then weights in order
    result = robustness(scenario(p, raws))
    assert result["NECK"] == "WIS band 0.654" and result["BACK"] == "robust"


def test_a_slot_that_flips_under_the_monk_curve_gets_that_label():
    # Chest: 30 armor class at 22 stones, or 24 at 5. The stand-in curve takes 25 points off the heavy one's bonus.
    p = with_weights(profile_of("HUM", ("MNK", "WAR", "ROG")), HP=1.0, AC=1.0)
    assert fm.monk_bonus(50, 220, p.monk) == 48 and fm.monk_bonus(50, 50, p.monk) == 73
    assert fm.monk_bonus(50, 220, {**p.monk, "full_until_stones": 34}) == 73
    raws = [
        raw_item("chest-heavy", ["CHEST"], stats={"AC": 30}, weight=22.0),
        raw_item("chest-light", ["CHEST"], stats={"AC": 24}, weight=5.0),
    ]
    assert labels(p) == ["AC x0.5", "AC x2", "Monk curve full until 34", "Monk placement inside"]
    report = robustness_report(scenario(p, raws))
    assert report.picks["CHEST"] == ("chest-light",)
    assert report.flips["CHEST"] == ("Monk curve full until 34",)
    assert robustness(scenario(p, raws))["CHEST"] == "Monk curve full until 34"


def test_a_slot_that_flips_under_the_weapon_damage_rate_gets_that_label():
    # Two one-handers at +4. At 5 percent a tier the short fast one is better; at 10 percent the slow heavy one is.
    p = with_weights(profile_of("HUM", ("WAR", "ROG", "BER")), HP=1.0, DMG=100.0)
    low, high = weapon_of(12, 20), weapon_of(30, 50)
    def score(w, pct):
        item = at_tier(raw_item("w", ["PRIMARY"], weapon=w), 4, RULES, weapon_pct=pct)
        return float(wp.damage_index_exact(item, "primary", "1h-shield", 0))

    index = {pct: [score(w, pct) for w in (low, high)] for pct in (5, 10)}
    assert index[5][0] > index[5][1] and index[10][1] > index[10][0]
    raws = [raw_item("w-low", ["PRIMARY"], weapon=low), raw_item("w-high", ["PRIMARY"], weapon=high)]
    s = scenario(p, raws, setup="1h-shield", tier=4)
    report = robustness_report(s)
    assert report.picks["PRIMARY"] == ("w-low",) and report.flips["PRIMARY"] == ("Weapon damage +10%",)
    assert robustness(s)["PRIMARY"] == "Weapon damage +10%"
    # the stick scores no damage, so there is no such variant and nothing flips
    assert robustness(scenario(p, raws, setup="stick", tier=4))["PRIMARY"] == "robust"


def test_when_every_variant_agrees_every_slot_is_robust():
    p = with_weights(profile_of("HUM", ("WAR", "CLR", "ENC")), HP=1.0, AC=1.0)
    raws = [raw_item("head", ["HEAD"], stats={"HP": 90, "AC": 10}), raw_item("junk", ["HEAD"], stats={"HP": 3})]
    assert robustness(scenario(p, raws)) == dict.fromkeys(GROUPS, "robust")
    assert robustness(scenario(p, [])) == dict.fromkeys(GROUPS, "robust")  # an empty pool is robust too


def test_a_pair_slot_flips_when_the_set_of_its_two_items_does():
    p = with_weights(profile_of("HUM", ("WAR", "CLR", "ENC")), HP=1.0, AC=1.0)
    raws = [  # Lore, so that a second copy of the best one cannot take the other ear
        raw_item("ear-a", ["EAR"], stats={"HP": 60}, lore=True),
        raw_item("ear-b", ["EAR"], stats={"HP": 45}, lore=True),
        raw_item("ear-c", ["EAR"], stats={"AC": 40}, lore=True),
    ]
    report = robustness_report(scenario(p, raws))
    assert report.picks["EAR"] == ("ear-a", "ear-b")  # 60 and 45 beat 40
    assert report.flips["EAR"] == ("AC x2",)  # at x2 the 80 of ear-c beats ear-b


def test_robustness_agrees_with_solving_each_variant_directly():
    p = with_weights(profile_of("HUM", ("MNK", "WAR", "ROG")), HP=1.0, AC=1.0)
    raws = [
        raw_item("chest-heavy", ["CHEST"], stats={"AC": 30}, weight=22.0),
        raw_item("chest-light", ["CHEST"], stats={"AC": 24}, weight=5.0),
        raw_item("neck-a", ["NECK"], stats={"AC": 40}),
        raw_item("neck-b", ["NECK"], stats={"HP": 50}),
    ]
    s = scenario(p, raws)
    base = robust.picks(solve_canonical(build_milp(p, s.pool(), s.setup, None, OPTIONS)))
    flipped = {group: set() for group in GROUPS}
    for label, prof in perturbations(p, RULES):
        other = robust.picks(solve_canonical(build_milp(prof, s.pool(), s.setup, None, OPTIONS)))
        for group in GROUPS:
            if other[group] != base[group]:
                flipped[group].add(label)
    assert flipped["CHEST"] == {"Monk curve full until 34"} and flipped["NECK"] == {"AC x2"}
    report = robustness_report(s)
    result = robustness(s)
    for group in GROUPS:
        assert set(report.flips[group]) == flipped[group]
        assert (result[group] == "robust") == (not flipped[group])
        assert result[group] in ({"robust"} | flipped[group])


def test_a_solve_that_does_not_end_optimal_is_an_error():
    p = with_weights(profile_of("HUM", ("WAR", "CLR", "ENC")), HP=1.0, AC=1.0)
    raws = [raw_item("neck-ac", ["NECK"], stats={"AC": 40}), raw_item("neck-hp", ["NECK"], stats={"HP": 50})]
    calls = []

    def late(milp, time_limit=None):
        calls.append(time_limit)
        real = solve_canonical(milp)
        if len(calls) == 3:
            return dataclasses.replace(real, status="time_limit")
        return real

    with pytest.raises(RobustnessError, match="time_limit"):
        robustness(scenario(p, raws), solver=late, time_limit=7.5)
    assert calls[:3] == [7.5, 7.5, 7.5]
    nothing = Solution("infeasible", None, None, (), None, None)
    with pytest.raises(RobustnessError, match="infeasible"):
        robustness(scenario(p, raws), solver=lambda milp, time_limit=None: nothing)


def test_the_pool_is_pruned_unless_the_scenario_says_not_to():
    p = with_weights(profile_of("HUM", ("WAR", "CLR", "ENC")), HP=1.0, AC=1.0)
    raws = [raw_item(f"neck-{n}", ["NECK"], stats={"HP": n}) for n in range(1, 6)]
    seen = []

    def spy(milp, time_limit=None):
        seen.append(len(milp.items))
        return solve_canonical(milp)

    robustness(scenario(p, raws), solver=spy)
    pruned = seen[0]
    seen.clear()
    robustness(scenario(p, raws, prune=False), solver=spy)
    assert pruned == 1 and seen[0] == 5
    assert robustness(scenario(p, raws)) == robustness(scenario(p, raws, prune=False))
